# Argus — RAG Pipeline 设计

> Version: 0.1.0 · Date: 2026-09-18

## 1. 总览

Argus 的 RAG 不是简单「embedding + 相似度检索」，而是**多路召回 + rerank + 引用可追溯 + 评估驱动**的工程化 pipeline。

## 2. Pipeline 全景（含中文注解）

```
                          【离线入库路径】
                    ┌────────────────────────┐
   用户上传/网络拉取 →│     ① Document        │ 入口：接收文件 / URL / RSS
                    │      Ingestion        │  · 写 S3 + 入库 documents 表
                    └──────────┬─────────────┘
                               │ 拿到原始 bytes / HTML
                               ▼
                    ┌────────────────────────┐
                    │ ② Parser（解析器）     │  · PyMuPDF / Trafilatura / Tesseract / AssemblyAI
                    │     PDF/Web/OCR/音视频  │  · 输出「干净文本 + 段落边界」
                    └──────────┬─────────────┘
                               │ text blocks
                               ▼
                    ┌────────────────────────┐
                    │ ③ Chunker（切片器）     │  · RecursiveTextSplitter
                    │   - 512 tokens / 片     │  · overlap 64
                    │   - 元数据注入          │  · 给每片注入 doc_id / chunk_id / section / lang
                    └──────────┬─────────────┘
                               │ chunks（512 ~ 64 个/篇）
                               ▼
                    ┌────────────────────────┐
                    │ ④ Embedder（向量化）    │  · OpenAI text-embedding-3-small
                    │   - batch 64            │  · 维度降到 512 省存储
                    │   - Redis 缓存命中      │  · 同一文本 24h 内不重复请求
                    └──────────┬─────────────┘
                               │ vector(512)
                               ▼
                    ┌────────────────────────┐
                    │ ⑤ pgvector（HNSW）     │  · 余弦相似度索引
                    │   - 用户级 RLS          │  · m=16 / ef_construction=64
                    │   - 关联 doc_id/user_id │  · 每用户私域隔离
                    └──────────┬─────────────┘
                               │ 写入完成 → 文档可检索
                               │
                               ╔══════════════════════════════════╗
                               ║                                  ║
                               ║      【在线检索路径】             ║
                               ║                                  ║
                               ╚══════════════════════════════════╝
                               │
   用户提问 ─────────────────────┘  query
                               │
                               ▼
                    ┌────────────────────────┐
                    │ ⑥ Hybrid Retriever     │  · 向量召回 top 50（cosine）
                    │   - vector cosine       │  · BM25 召回 top 50（pg fulltext）
                    │   - BM25 fulltext       │  · RRF（k=60）合并去重
                    └──────────┬─────────────┘
                               │ ~50 候选
                               ▼
                    ┌────────────────────────┐
                    │ ⑦ Reranker（重排）     │  · Cohere Rerank v3
                    │   - top 50 → top 10     │  · 按 query-chunk 相关度重排
                    │   - 按相关性精排        │  · 备选 BGE Reranker v2（本地）
                    └──────────┬─────────────┘
                               │ top 10 chunks
                               ▼
                    ┌────────────────────────┐
                    │ ⑧ Citation Builder     │  · 给每条加 doc_id / chunk_id / offset
                    │   - 引用编号生成         │  · 准备 references 列表给 LLM
                    │   - 元数据对齐          │  · UI 端点击 [n] 可追溯
                    └──────────┬─────────────┘
                               │ chunks + citations
                               ▼
                    ┌────────────────────────┐
                    │ ⑨ LLM Prompt 组装       │  · system prompt + query
                    │   - system + query      │  · chunks 注入到 context
                    │   - + top 10 chunks     │  · 强制 LLM 输出 [n] 引用
                    └──────────┬─────────────┘
                               │
                               ▼
                    ┌────────────────────────┐
                    │ ⑩ Writer Agent 写作    │  · 草稿带 [n] 引用
                    │   · 报告 / 对比表 /     │  · Critic 校验引用真实性
                    │     时间线 / 决策清单   │  · 不通过回 Writer 重写
                    └────────────────────────┘
```

**两条路径汇总**：
- **离线入库（①~⑤）**：异步、批处理，可并发多文档
- **在线检索（⑥~⑩）**：低延迟（目标 P95 ≤ 800ms），带引用可追溯

## 3. Ingestion

### 3.1 文件类型支持

| 类型 | 解析器 | 备注 |
|---|---|---|
| PDF | PyMuPDF (fitz) | 文本 + 图片 + 表格 |
| Word | python-docx | 段落 + 表格 |
| HTML | Trafilatura | 正文提取 + 去噪 |
| Markdown | 直接读 | 标题分级 |
| 图片 | Tesseract OCR + GPT-4V | 文字 + 视觉描述 |
| 视频 URL | yt-dlp + AssemblyAI | 字幕转写 |
| 音频 | AssemblyAI | 转写 |

### 3.2 处理流程

```python
async def ingest(source: Source) -> List[Document]:
    # 1. 抓取/读取
    raw_bytes = await fetch(source)

    # 2. 解析
    parser = get_parser(source.type)
    text_blocks = await parser.parse(raw_bytes)

    # 3. 切片
    chunks = chunker.split(text_blocks, chunk_size=512, overlap=64)

    # 4. 元数据
    for chunk in chunks:
        chunk.metadata = {
            "doc_id": source.id,
            "user_id": source.user_id,
            "source_type": source.type,
            "url": source.url,
            "title": source.title,
            "fetched_at": source.fetched_at,
            "credibility_score": source.credibility_score,  # RSS > 网页 > X
        }

    # 5. 入库（事务）
    await db.bulk_insert_chunks(chunks)

    return chunks
```

## 4. Chunking 策略

### 4.1 默认参数

- **chunk_size**: 512 tokens
- **overlap**: 64 tokens
- **splitter**: RecursiveTextSplitter
- **separators**: ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]

### 4.2 元数据增强

每个 chunk 携带：
- `doc_id`: 文档唯一 ID
- `chunk_id`: 文档内序号
- `chunk_offset`: 字符 offset
- `section`: 所在章节（从 markdown / HTML 解析）
- `lang`: 语言（zh / en 混合）

### 4.3 特殊处理

- **代码块**：不切分，整块保留
- **表格**：转 markdown 表格 + caption
- **图片**：OCR 文本 + `image_caption` 生成描述
- **重复内容**：chunk-level simhash 去重

## 5. Embedding

### 5.1 模型

- **默认**：OpenAI `text-embedding-3-small`
  - 维度：1536（可降至 512）
  - 多语言支持
  - 价格：$0.02 / 1M tokens

### 5.2 缓存策略

```python
@cached_redis(ttl=86400, key="emb:{hash(text)}")
async def embed(text: str) -> List[float]:
    return await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
```

同一文本不重复请求。Redis TTL 24h。

### 5.3 批量

```python
async def embed_batch(texts: List[str]) -> List[List[float]]:
    # OpenAI 限制 2048 inputs/batch
    return await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
        dimensions=512,  # 降维省存储
    )
```

## 6. 向量存储

### 6.1 pgvector Schema

```sql
CREATE TABLE document_chunks (
    id BIGSERIAL PRIMARY KEY,
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chunk_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(512) NOT NULL,  -- text-embedding-3-small 降维
    metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(doc_id, chunk_id)
);

CREATE INDEX idx_chunks_embedding ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunks_user ON document_chunks(user_id);
CREATE INDEX idx_chunks_doc ON document_chunks(doc_id);
```

### 6.2 RLS（行级安全）

```sql
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY chunks_user_isolation ON document_chunks
USING (user_id = current_setting('app.current_user_id')::UUID);
```

每次连接 SET `app.current_user_id`。

### 6.3 检索 SQL

```sql
SELECT id, doc_id, chunk_id, content, metadata,
       1 - (embedding <=> $1::vector) AS similarity
FROM document_chunks
WHERE user_id = $2
ORDER BY embedding <=> $1::vector
LIMIT 50;
```

## 7. 混合检索

### 7.1 策略

- **向量召回**：top 50（cosine similarity）
- **BM25 召回**：top 50（pg fulltext search）
- **合并**：RRF (Reciprocal Rank Fusion) k=60
- **去重**：相同 doc_id + chunk_id 只保留一条

### 7.2 BM25 配置

```sql
-- pg_trgm + tsvector
ALTER TABLE document_chunks ADD COLUMN tsv tsvector
GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;

CREATE INDEX idx_chunks_tsv ON document_chunks USING GIN(tsv);
```

中文用 `to_tsvector('simple', ...)`（zhparser 或 jieba 分词）。

## 8. Rerank

### 8.1 模型

- **Cohere Rerank v3**
- 输入：query + 50 chunks
- 输出：top 10 重排

```python
from cohere import AsyncClient

co = AsyncClient(api_key=COHERE_API_KEY)

async def rerank(query: str, chunks: List[Chunk]) -> List[Chunk]:
    docs = [c.content for c in chunks]
    results = await co.rerank(
        model="rerank-english-v3.0",
        query=query,
        documents=docs,
        top_n=10,
    )
    return [chunks[r.index] for r in results.results]
```

### 8.2 备选

- BGE Reranker v2（本地，CPU 推理够 demo）
- 自研 cross-encoder（最后选项）

## 9. Citation

### 9.1 引用格式

```
In NVIDIA's Q2 2026 earnings report [1], data center revenue reached
$39.2 billion, up 154% YoY [1][2]. This contrasts with AMD's MI300
contribution [3]...

References:
[1] NVIDIA Q2 FY26 Earnings, 2026-08-28, source=nvidia.com
[2] Reuters "NVIDIA beats...", 2026-08-28
[3] AMD Q2 FY26 Earnings, 2026-08-06
```

### 9.2 引用生成

LLM 输出时**强制**标注 `[n]`，每个 `[n]` 必须在 references 列表中。Critic 校验每个引用 chunk_id 是否真在 evidence 集合内。

### 9.3 UI 追溯

- 点击 `[n]` → 弹窗显示 chunk 原文 + 文档链接 + 元数据
- 引用边可视化（哪个 chunk 被用了多少次）

## 10. 评估

### 10.1 数据集

`eval/datasets/retrieval_v1.jsonl`：
```json
{
  "query": "英伟达 H100 与 Blackwell 性能对比",
  "ground_truth_doc_ids": ["nvidia-h100-spec", "nvidia-blackwell-spec"],
  "relevance_scores": {"chunk-1": 0.9, "chunk-2": 0.7, ...}
}
```

### 10.2 指标

| 指标 | 定义 | 目标 |
|---|---|---|
| Precision@5 | 前 5 个结果中相关比例 | ≥ 0.75 |
| Recall@10 | 前 10 个结果覆盖相关文档比例 | ≥ 0.85 |
| MRR | 第一个相关结果的倒数排名 | ≥ 0.70 |
| NDCG@10 | 归一化折损累积增益 | ≥ 0.75 |
| Faithfulness | 引用真实性（自动 + 人工） | ≥ 0.85 |
| Latency | P95 检索耗时 | ≤ 800ms |

### 10.3 回归测试

CI 中跑 retrieval eval suite：
- 默认 100 条 query
- 跑完对比 baseline
- 退化 > 5% 报警

## 11. 已知边界

- 中文 embedding 略弱于英文（备选 BGE-M3）
- 跨语言检索（zh ↔ en）需要 cross-lingual embedding
- 大文档（>1000 页 PDF）需要分层摘要
- 多模态 chunk 检索精度待优化