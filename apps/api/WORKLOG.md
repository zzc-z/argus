# Argus API 开发工作日志

> 用途：上下文压缩后据此恢复开发状态。**最新的章节在顶部**。
> 最后更新：2026-10-13（W2 Day 10 完成）

---

# 🔴 最新：W2 Day 10 完成（混合检索已通）

## 进度

W1 全完成，W2 Day 9 + Day 10 完成。**296 tests 全绿**（W1 结束时 157）。

```
ruff    ✅
mypy    ✅ 35 source files
pytest  ✅ 296 passed
```

已推送到 origin/master（`ce7830c..78124dd`）。

| commit | 内容 |
|---|---|
| `3ae4549` | **fix**：补齐 RAG 依赖声明 |
| `fac9e5c` | BM25 全文检索（jieba + FTS5） |
| `78124dd` | 混合检索（RRF k=60） |

## ⚠️ Day 10 的实测结论（都是跑出来的，不是照文档）

### 1. SQLite FTS5 自带分词器对中文全不可用——必须 jieba 预分词

| 分词器 | 「能效」「营收」「算力」「功耗」 |
|---|---|
| `unicode61`（默认） | 整句当一个词，**0 命中** |
| `trigram` | 要求 ≥3 字符，**所有 2 字词 0 命中** |

2 字词恰好是中文技术词汇的主力。jieba 预分词后全部命中。
PRD §7.2 写的是 Postgres 的 `to_tsvector('simple')`，在 SQLite 上完全用不上。

### 2. contentless FTS5 不支持 DELETE

`content=''` 省存储，但实测报 `cannot DELETE from contentless fts5 table`。
重跑摄取必须能删旧条目，所以用普通 FTS5。

### 3. BM25 漏同义词、向量漏专有名词——混合检索不是可选项

jieba 把「营业收入」切成「营业 收入」，查「营收」交集为空，一条命中不了
（2 字滑窗也救不了：原文滑窗是「业收」不是「营收」）。这类靠向量兜。

反过来问「H200 的实测 QPS」，BM25 靠专有名词命中、向量排第二——靠 BM25 兜。
端到端实测四组查询全对，这个互补关系是实测出来的，不是推演。

### 4. RRF 而不是加权平均

向量给 L2 距离（实测 0.0–1.3），BM25 给负分（−1 到 −10，**随语料规模漂移**）。
归一化参数（min-max 要看当次候选集、z-score 要看语料统计）在两路各自的
分布上都不稳定。RRF 只用排名，天然免疫量纲差异。

### 5. 虚表是运行时建的（Alembic 不认），入口必须收口

这个坑在 Day 10 **重复踩了三次**：`no such table: chunk_embeddings` ×2、
`no such table: chunk_fts`、`no such module: vec0`。全新部署上用户一份资料
都没摄取时必崩。现收口成 `ensure_index_tables()`，且 `bm25.search` /
`index_chunks` / `vectorstore.knn_search` 各自兜底。

### 6. `from x import f` 会让 monkeypatch 失效

导入时绑定了函数对象，patch 模块属性对它无效。`retriever.py` 改成
`embedder.embed_texts(...)` 模块级调用。**写测试打桩时要记住这条。**

## Day 10 的设计决策

1. **jieba 而非纯向量**——理由见实测 1
2. **RRF k=60**——PRD §7.1 指定值
3. **BM25 索引在「没有向量」的分支之前建**——全文检索不依赖嵌入服务，
   没配 key 时照样能用。只被 `vectors is None` 挡住的话，未配置嵌入的
   部署只剩空的那一路，等于没建索引
4. **`shared_db` 测试 fixture**——业务表与向量索引必须在**同一个** SQLite
   文件里，否则 `source_ids` 的过滤子查询永远查不到行。症状是「索引明明
   有数据却一条都检索不到」
5. **`retr...da` (PRIVATE_URL) `bm25.py` 的 `tokenize` 丢掉无字母数字的 token**——
   纯标点（`，。%`）在 FTS5 里是分隔符，留着只会让 MATCH 表达式变脏

### 变异测试（确认测试真在保护设计）

- 去掉 `source_ids` 过滤 → **3 个测试失败**（泄露别人的 chunk）
- 去掉 BM25 融合 → **2 个测试失败**

---

# W2 Day 9 完成（RAG 摄取管线已通）

## 进度

W1 全部完成（单 agent + tool calling + SSE）。W2 Day 9 完成：RAG 摄取管线
四步（解析 → 切片 → 嵌入 → 落库）已端到端跑通，HTTP 端点已就绪。

```
ruff    ✅ All checks passed
mypy    ✅ no issues found in 33 source files（strict）
pytest  ✅ 264 passed（W1 结束时 157）
```

## 新增文件

| 文件 | 行数 | 职责 |
|---|---|---|
| `app/models/source.py` | 180 | Source / DocumentChunk / SourceType / SourceStatus |
| `app/services/vectorstore.py` | 190 | sqlite-vec 接入：建表、写入、KNN 检索 |
| `app/services/parser.py` | 140 | PDF / HTML / 纯文本三个解析器 |
| `app/services/chunker.py` | 115 | 512 字切片 + 偏移量定位 |
| `app/services/embedder.py` | 130 | 嵌入调用、批处理、维度校验 |
| `app/services/ingest.py` | 180 | 四步编排 + 状态机 + 失败落库 |
| `app/services/storage.py` | 75 | 上传文件落盘 |
| `app/gateway/sources.py` | 200 | 6 个 HTTP 端点 |
| `app/schemas/source.py` | 77 | 请求/响应模型 |
| `alembic/versions/500a268181fc_*.py` | — | 建 sources / document_chunks |

## ⚠️ 接续开发必读：本次的实测结论

### 1. 嵌入走阿里云百炼，不走 OpenAI 官方

**OpenAI 官方这条路走不通**（实测）：

- `https://platform.openai.com` 屏蔽中国大陆 IP
- 开通后 429 `credit_balance_exhausted`——key 有效但余额为 0
- OpenAI **只收境外信用卡**，支付宝/微信/银联都不行

**百炼能用**（实测）：OpenAI 兼容端点，支付宝可付，新用户送 100 万 token
（90 天有效）。单价 0.0005 元/千 token，一份 50 页研报约 **2 毛钱**。
实测 4 条文本 0.32 秒，跨语言检索正常（中文查询命中中文内容，英文查询也能中）。

配置全走 `.env`，换服务商不改代码：

```
EMBEDDING_API_KEY = "sk-..."          # 百炼的 key
EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMBEDDING_MODEL = "text-embedding-v4"
```

**tokenPlus 查过了，不行**：`/embeddings` 端点存在但模型广场「向量」分类是 0，
没有可用的嵌入模型。

### 2. 百炼的 text-embedding-v4 必须显式传 dimensions

不传时默认返回 **1024 维**，与索引表的 1536 不符 → `DimensionMismatchError`。
显式传 `dimensions=1536` 才行（实测 1536 / 1024 都支持）。

这正是维度校验的价值：没这道校验会把 1024 维向量写进 1536 维的 vec0 表，
然后**检索结果全是乱码但不报任何错**。

### 3. sqlite-vec 的加载：唯一可行入口是 `async_creator`

**不能用 SQLAlchemy 的 `connect` 事件加载扩展**——这是本次最大的坑。

事件回调里拿到的 `dbapi_conn.driver_connection` 是 `aiosqlite.Connection`，
它的 `enable_load_extension` 是 **async** 方法。同步回调里调用只造一个协程对象
就被丢弃，扩展**静默不加载**，之后所有 `vec_*` 调用报
`no such function: vec_version`，且加载期一句错都没有。

唯一可行入口：

```python
create_async_engine("sqlite+aiosqlite://", async_creator=lambda: _open(path))
```

### 4. vec0 返回的是 L2 欧氏距离，不是余弦距离

实测（单位向量，真实 cos=0.5304）：`distance=0.9692`，而 `1-cos=0.4696`、
`√(2-2cos)=0.9692`——与 L2 **逐位吻合**。

排序不受影响：单位向量下 `L2 = √(2-2cos)` 是 cos 的单调递减变换。
但**阈值不能跨度量套用**——「distance < 0.5」在两种度量下含义完全不同。
换 pgvector 时记得改。

由 `tests/test_vectorstore.py::test_distance_is_l2_not_cosine` 锁住。

### 5. 嵌入不是确定性的

同一段文本两次调嵌入服务，向量有 ~1e-3 量级浮点差异（累加顺序不同）。
实测中三个切片两两余弦接近时（0.4679 vs 0.4485），这点噪声足以让 top1/top2 互换。

**不要断言排名的绝对值**，只断言「正确答案在前列」。真实场景 top50 召回
再 rerank，单条抖动不影响结果。

### 6. 切片：不要传 PRD 那串自定义 separators

PRD §4.1 写的 `["\n\n", "\n", "。", ...]` 在「中文研报段落 + chunk_size=50」
时会切出一片孤立的 `。`——单字符片变成垃圾 embedding。

注意这不是普遍现象（换尺寸/换文本都不出现），但默认配置没这个问题。
用默认配置还有个好处：**overlap 看起来才正常**。自定义 separators 把标点留在
片头，会吃掉重叠窗口（实测 `test_overlap_repeats_text_between_chunks` 失败）。

### 7. SQLite 默认不执行外键——踩过

`PRAGMA foreign_keys` 默认 **0**。不开它，模型里所有 `ondelete="CASCADE"`
形同虚设：删用户会留下一堆孤儿 `sources` / `document_chunks`，而且**测试不会报警**
（我第一个 CASCADE 测试就是这么「通过」的，实际什么都没删）。

已在两处打开：`app/db.py::_enable_sqlite_foreign_keys`（挂 connect 事件）
与 `tests/conftest.py::db_session`。对 Postgres 是 no-op，不用分支。

### 8. pytest 的 faulthandler 插件与 pymupdf 在 Python 3.14 上冲突

`-p no:faulthandler` 写进了 `pyproject.toml` 的 `addopts`。不加的话
一 import pymupdf 就段错误，且崩在 C 扩展初始化期——faulthandler 打的栈
也定位不到根因。它本来只在崩溃时打栈，对我们没净收益。

同时加了 filterwarnings 规则忽略 SWIG 的 `has no __module__ attribute`。

### 9. pymupdf 的实测行为（1.28.2）

| 场景 | 行为 |
|---|---|
| 损坏文件 | `FileDataError` |
| 加密文件 | `needs_pass` 为真；直接读报 `ValueError: document closed or encrypted` |
| 空白页 | `get_text()` 返回空串，跳过即可（不是错误） |
| 全无文字 | 要单独报「需 OCR」，不能含糊成「解析失败」 |

`Document` 声明成 `Iterable[Never]`（没写 `__iter__` 签名），用
`range(doc.page_count)` + `doc[i]` 绕开可迭代协议，mypy 就自洽了。

### 10. 偏移量靠 `str.find` 顺序扫描定位

langchain 的 `create_documents` 不返回字符偏移，而引用高亮必须要有。
实测（中文/无分隔符连续字符/中英混排/重复段落）每个 chunk 都能在原文定位成功。

必须用**带 cursor 的顺序 find**，朴素 `find` 会让重复段落全部贴到文首。

### 11. `python-multipart` 是 FastAPI 收上传的硬依赖

不装的话 FastAPI 启动即报错。已加进 `pyproject.toml`。

## 设计决策（勿推翻）

1. **向量库用 sqlite-vec，W3 换 pgvector**——dev 环境无 Docker、5432 未开。
   向量逻辑全部收口在 `app/services/vectorstore.py`，换库只改这一个文件。
   模型/parser/chunker/embedder/ingest 都不碰数据库细节。
2. **向量不进 ORM 表**——存 `document_chunks`（正文，给全文检索）+ `chunk_embeddings`
   （vec0 虚拟表）两处，靠 `document_chunks.id == chunk_embeddings.chunk_id` 对齐。
   vec0 表没有列能放业务字段。
3. **摄取状态逐阶段 commit**——前端要显示「正在切片 142/180」，状态存内存
   刷新就没了。多几次写换可观测进度。
4. **摄取是后台任务，不阻塞 HTTP**——50 页 PDF 要 30-60 秒。端点只建源就返回 201，
   前端轮询状态端点。与 research 的 SSE 是两套机制（摄取不需要逐 token 反馈）。
5. **失败要落库**——`status=failed` + `error_message`，不能只抛异常。
   否则用户只看到请求超时就结束，无从重试。
6. **解析器抽不出文字时抛错，不返回空串**——空串会让摄取「成功」入库，
   然后检索时静默地什么都搜不到。扫描件单独报「需 OCR」。
7. **上传文件名用 uuid4 + 净化后的扩展名**——绝不用用户上传的原名
   （可能有 `../`、中文、超长、撞车）。
8. **越权一律 404 不是 403**——403 等于确认了这个 id 存在，是信息泄露。

## 已知缺口（不是设计，是没做）

1. **`DELETE /sources/{id}` 不清原始文件与向量**——向量表没外键，DB 级联删不到。
   当前用量下不影响正确��（检索按 chunk_id 回查，查不到就丢弃），但要补。
2. **URL 建源只登记不抓取**——抓取要接 Tavily/Firecrawl。
3. **没有任务队列**——进程重启会丢正在跑的摄取（status 卡在中间态）。
   YAGNI：先这样，真需要时接 Redis + worker。
4. **没有 rerank**——PRD §8 的 cross-encoder 重排。当前 top-50 直接给模型，
   精度够用，要提精度再上（`_rrf_fuse` 已按 PRD 预留 top-50 召回）。
5. **`Source.chunks` 的 lazy='selectin'** 会让每次查 source 都带出全部切片。
   列表页 `list_owned` 用不上，应该改成 `lazy='raise'` 或 `raiseload` + 显式查询。

## 下一步：W2 Day 11-12（citation 溯源 + 前端接线）

Day 10 的混合检索已完成（见上），剩下的：

1. **Citation Builder**——给每条检索结果加 doc_id / chunk_id / page，
   让前端引用能点回原文。`Retrieved` 已经带了 chunk + source，
   缺的只是把它序列化进 SSE / agent 上下文
2. **explore 页接上检索**——现在只走 Tavily 搜索，没用本地资料。
   `app/gateway/research.py` 要加一个 `search_sources` 工具
3. **URL 抓取**——`POST /api/v1/sources/url` 现在只登记不抓取，
   要接 Tavily extract 或 Firecrawl
4. **rerank**（PRD §8）——可选，先不做

⚠️ 前端 citation 契约要看 `explore/components/InspectorDrawer` 的
`buildCitationPayload`，别自己另立一套字段。

---

## W2 Day 10：混合检索（已提交）

### 实测结论（都是跑出来的，不是照文档）

**1. SQLite FTS5 的分词器对中文全不可用**

| 分词器 | 「能效」「营收」「算力」「功耗」 |
|---|---|
| `unicode61`（默认） | 整句当一个词，0 命中 |
| `trigram` | 要求 ≥3 字符，**所有 2 字词 0 命中** |

2 字词恰好是中文技术词汇的主体。必须 **jieba 预分词 → FTS5 存词**
（`app/services/bm25.py`）。装好后全部命中。

**2. 不能用 contentless FTS5（`content=''`）**

实测报 `cannot DELETE from contentless fts5 table`——它不支持 DELETE，
而重跑摄取必须能删旧条目。

**3. RRF 是对的选择，不是因为「业界流行」**

两路量纲完全不同：向量给 **L2 距离**（实测 0.0-1.3），BM25 给**负分**
（−1 到 −10，且随语料规模漂移）。加权平均要先归一化，而归一化参数
（min-max 要看当次候选集、z-score 要看语料统计）在两路各自的分布上都不稳定。
RRF 只用**排名**，天然免疫量纲差异。

**4. 混合检索不是可选项**

端到端实测：
- 问「H200 的实测 QPS」→ BM25 靠**专有名词 H200** 命中
- 问「股价最高到过多少」→ BM25 **完全没命中**（`b-`），全靠向量兜
- 问「revenue grew」→ BM25 命中不了「营业收入」（jieba 切出「营业 收入」，
  与「营收」交集为空）

**向量漏专有名词，BM25 漏同义词。** 两路都要。

### 踩过的坑

| 坑 | 说明 |
|---|---|
| **虚表要 ensure，已漏三次** | 虚表运行时建（Alembic 不认），原先 4 个调用点各自 ensure，结果报过 `no such table: chunk_embeddings` / `chunk_fts` / `no such module: vec0`。现收口成 `ingest.ensure_index_tables()` 单一入口，且 `bm25.search` / `index_chunks` / `knn_search` 各自兜底 |
| **`shared_db` fixture** | 业务表与向量索引必须在**同一个** SQLite 文件里。分两个库的话 `source_ids` 的过滤子查询永远查不到行——症状是「索引明明有数据却检索不到」 |
| **`from x import f` 打桩无效** | 函数对象在导入时绑定，monkeypatch 模块属性对它没用。改用 `embedder.embed_texts(...)` 调用形式 |
| **RAG 依赖装漏** | `pymupdf` / `langchain-text-splitters` / `sqlite-vec` 当初用 `uv pip install` 装的，没写进 `pyproject.toml`。`uv sync` 会卸掉它们——开发机正常，干净环境 import 失败。已补 |

### 变异测试（确认测试真在保护设计）

- 去掉 `source_ids` 过滤 → **3 个测试失败**（泄露别人的 chunk）
- 去掉 BM25 融合 → **2 个测试失败**

---

## 历史：W1 Day 4 完成（单 agent + tool calling + SSE 全链路已通）

### 已提交（W1 Day 4 时的状态）

| commit | 内容 |
|---|---|
| `4d877a0` | **LLM client 单例 + Tavily 配置**（`app/services/llm.py`） |
| `c4bae5c` | **工具层：`tavily_search` + `dedup`**（`app/services/tools.py`） |
| `7b6784b` | **agent 主循环 + 事件契约 + 打字机切片**（`agent.py` / `stream.py`） |
| `90756fc` | **SSE 端点 `POST /api/v1/research/ask`**（`gateway/research.py`） |

前端 3 个 commit（`d584dbe` / `a260805` / `2b4027c` 等）把 explore 页接到上面
这个端点上，已实跑验证。


### 质量门（全绿）

```
ruff    ✅ All checks passed
mypy    ✅ no issues found in 24 source files（strict）
pytest  ✅ 157 passed
```

## ⚠️ 接续开发必读：本次会话的实测结论

这些是**跑真实模型测出来的**，不是从文档推断的。重写相关代码前先看这段。

### 1. LLM 服务商是「llmapi.pro 中转站」，不是 Anthropic 官方

`ANTHROPIC_BASE_URL=https://llmapi.pro`。它的行为和官方 API 有两处**实测差异**，照官方文档写会踩：

| 现象 | 官方 API | 中转站实测 |
|---|---|---|
| 文本流式粒度 | 逐 token | **整段缓冲**，243 字符只给 1 个 `text_delta` |
| `model_dump()` 带 null 字段 | 严格模式会拒 | **接受**（`citations: null` 照发不误） |

所以后端的打字机效果是**自己切的**（`TextSlicer`，见下），不是依赖上游分块。

`exclude_none=True` 仍然保留——理由从「不这样会 400」改成「直连官方 API 更保守，当前零成本」。

### 2. Sonnet 5 会返回 `thinking` block，且必须原样回传

实测返回结构：`['thinking', 'text', 'tool_use']`。

- **必须回传**：thinking 里带 `signature`，改动会被上游拒
- **绝不能发给用户**：前端只要研究结论，原始 CoT 不该出站

代码里 `messages.append({"role": "assistant", "content": result.content})` 就是干这个的，`agent.py` 顶部 docstring 写了完整理由。**这条约束由 `tests/test_turn_request.py` 守护**（12 个测试专门测 `_run_turn` 的请求构造与响应解析）。

### 3. `_run_turn` 是最脆的一环，别改它不测

它是 agent 与 SDK 之间**唯一**的接缝（`agent.py:292` 附近）。行覆盖率看不出来——大部分测试用 `monkeypatch` 把它替换掉了，coverage 会把「import 期执行过」算成已覆盖。

代码审查时用**变异测试**发现的：把 signature 字段删掉，125 个测试照样全绿。

### 4. `_is_word_char` 必须限定 ASCII

修「`100,000` 被劈成两半」时用了 `isalnum()`——但**中文的 `isalnum()` 也是 `True`**，导致所有中文标点的切分全被跳过，退化成硬切，连 `QPS` 都劈成 `Q` + `PS`。

现在有 `isascii()` 守卫，且 `LONG_TEXT` 测试数据里同时含中文和千分位。

**教训**：修 bug 的测试必须覆盖**受影响的主路径**（中文），不能只覆盖触发场景（数字）。

## 本次新增的代码约定

| 位置 | 约定 |
|---|---|
| `services/llm.py` | client 单例用 `@lru_cache`，配 `clear_client_cache()` 供测试重置。缺 key 抛 `LLMNotConfiguredError`，不返回 `None` |
| `services/tools.py` | 工具执行失败**不抛异常**，返回 `ok=False`。`except Exception` 分两类：网络类给「外部服务不可用」，其余给「工具内部出错，请勿重试」——代码 bug 不能报成用户参数问题 |
| `services/stream.py` | 事件用 JSON envelope（`{"type": "...", "v": {...}}`）而非 SSE 原生 `event:` 行，消费端一条 `split("\n\n")` + `JSON.parse` 就能统一分发 |
| `gateway/research.py` | 并发上限 4（信号量），超了直接 503 不开流。`X-Accel-Buffering: no` 防 Nginx 缓冲 |
| `services/stream.py::TextSlicer` | 标点贪心切片，窗口放宽到 `chunk_size * 1.5`，搜索范围是窗口内**最靠后**的标点。粒度 24 字 |

## 未完成 / 待办

1. **`tool_call` 事件驱动 InspectorDrawer 的 Input/Output/Prompt/Tabs** —— 现在 Tools 标签页有数据了，另外三个标签仍共用同一份 `jsonText`
2. **`ToolCall` 类型与后端 `ToolCallEvent` 的映射**已做，但 citation 溯源（`Citation`）还没接 SSE
3. **`apps/api/scripts/dev_login.py`** —— 调试脚本（生成 JWT），未提交也未 gitignore
4. **7 个 commit 未推送** —— 代理（APNetwork）需用户手动启动
5. **Day 5-7**：W1 Demo + 前端剩余接线

## 下一步（当时的，已完成）：W1 Day 5-7 或 W2

- **W1 收尾**：citation 溯源接 SSE、`DAG_STATS` 静态 import 清理、W1 Demo
- **W2（重头）**：RAG 管线（PyMuPDF / Trafilatura / chunking / embedding）+ 多 agent 编排

### W2 换 LangGraph 的判断依据（已与用户确认）

现在手写的是「单循环」，`agent.py` 里 `_run_turn` 那 44 行胶水是唯一能被框架替代的部分。`tools.py`（365 行）和 `stream.py`（221 行）LangGraph 完全用不上——前端要的事件格式不是 LangGraph 的回调格式。

**W2 换的理由**：状态在节点间传递、条件边、断点续跑、并行调度。这些手写就是几百行状态机。`prd/multi-agent-design.md` 已定义好 `ResearchState`。

**换的时候保留**：`tools.py` 整个、`stream.py` 整个、`llm.py` 的 client 单例可复用。只重写 `agent.py` 的循环部分。

⚠️ **W2 的一个已知冲突**：现在 `NodeTracker` 强制「任一时刻只有一个节点 active」（前端 `AgentDAG` 用 `findIndex` 算高亮轨道位置）。LangGraph 并行调度会天然产生多个 active，**这个约束要先解决**。

## 目录结构现状

```
apps/api/app/
├── __init__.py
├── config.py           Settings（pydantic-settings + SecretStr + lru_cache）
├── db.py               engine + SessionLocal + get_session + check_db_health
├── main.py             仅装配：建 app、lifespan、CORS、include_router
├── gateway/            HTTP 边界
│   ├── health.py       /api/v1/healthz + /api/v1/readyz
│   ├── auth.py         /api/v1/auth/github/{login,callback} + /logout
│   ├── users.py        /api/v1/me
│   └── deps.py         get_current_user（cookie→JWT→User），CurrentUser 别名
├── models/             SQLAlchemy ORM
│   ├── base.py         Base(DeclarativeBase)
│   └── user.py         User + Account + Provider(StrEnum)
├── schemas/            Pydantic 响应模型
│   ├── health.py       HealthResponse
│   └── user.py         MeResponse
└── services/           业务编排
    ├── auth.py         OAuthProfile / LoginResult / get_or_create_user
    └── token.py        JWT 签发与校验

apps/api/alembic/       已接好，target_metadata = Base.metadata
apps/api/tests/         49 个测试，内存 SQLite 隔离
```

## 关键技术决策（勿推翻）

1. **API 前缀统一 `/api/v1`**——各router 自己声明 prefix，不在main.py 里统一加
2. **两层身份模型**（Auth.js 事实标准）：`users` 管「是谁」，`accounts` 管「从哪登录」。复合主键 `(provider, provider_account_id)`
3. **邮箱 unique + 自动关联**——OAuth provider 信任主邮箱（GitHub/Google 强制验证）。**若将来接入允许未验证邮箱的 provider，必须关掉 `get_or_create_user` 的第2 段查找**，否则账号劫持
4. **不建 repository 层**——2026 业界轻量化趋势，查询以 `@classmethod` 挂在模型上
5. **JWT payload 只放 user_id**，资料实时读库
6. **JWT 密钥与 OAuth secret 独立**——泄露后果不同
7. **state / PKCE verifier 存itsdangerous 签名 cookie**，不用 Redis（无状态 + 多worker 安全）
8. **不用 Authlib 的 `authorize_access_token`**——它依赖 `request.session`，与 argus 自己的 JWT cookie 方案打架。只用底层 `OAuth2Client` 生成授权 URL，token 交换用 httpx 直调 GitHub
9. **测试不用 respx**——TestClient 走 ASGI transport，respx 会拦掉 TestClient 自己的请求导致假 404。改用 `monkeypatch` 替换发 HTTP 的函数 + `dependency_overrides` 换DB session
10. **测试绝不用 `SessionLocal`**——用 conftest.py 的 `db_session` fixture（内存 SQLite），否则污染 dev 库
11. **鉴权失败只有一种 401 文案**——缺 cookie / 票据坏 / 用户已删全返回同一句。前端处理动作完全一样，区分开只会多写无用分支；顺带不向攻击者泄露失败原因
12. **登出只删 cookie，不撤销票据**——JWT 无状态，服务端不存 session。已抄走的 cookie 在 7 天内仍能调通接口。补救要加撤销名单（表或 Redis），当前不做：等真要「踢人下线」时再上

## 环境相关的坑

- **PyPI 网络不稳**：报 `Failed to connect` / `peer closed connection`。改用阿里云镜像：
  ```bash
  uv sync --extra dev --index-url https://mirrors.aliyun.com/pypi/simple/
  ```
- **`uv remove` 会连带卸载整个 dev extra**。改 pyproject 后用 `sed` 编辑 + `uv sync --extra dev`，不要用 `uv remove`
- **VS Code 报红（无法解析导入 sqlalchemy/itsdangerous）**：IDE 解释器没指对，代码本身没问题。命令行 `uv run pytest` 走 `.venv` 所以全绿，但 Pylance 用你指定的解释器找包，两套机制独立。
  - 已修（2026-10-09）：项目根 `.vscode/settings.json` 设了 `python.defaultInterpreterPath = "apps/api/.venv/bin/python3"` + `python.analysis.extraPaths = ["apps/api"]`。改完要 `Cmd+Shift+P` → `Developer: Reload Window`，Pylance 不会自动重载
  - **venv 唯一实体在 `apps/api/.venv`**（uv 在 apps/api 下建的）。排查时别在仓库根跑 `find . -name .venv` 再把结果当根目录的——那样 `find` 的 `.` 是 cwd，会误报成 `./.venv`。先 `pwd` 确认再解读
  - **局限**：`defaultInterpreterPath` 对「已存在的 venv」生效。删掉 `.venv` 重装后 VS Code 会忽略这项，仍需手动选一次解释器
  - `.vscode/` 被根 `.gitignore:8` 忽略（解释器路径机器相关，入库添乱），换机器要照 WORKLOG 重建
- **ruff 读 `.ruff.toml` 而非 `pyproject.toml` 的 `[tool.ruff]`**——两处配置要同步
- **已装依赖**：`sqlalchemy[asyncio]`、`aiosqlite`（dev extra）、`itsdangerous`、`types-authlib`（dev extra）。已移除 `types-pyjwt`（过时 stub，会把 `jwt.encode` 误标为返回 bytes）

## 凭据状态（.env 18 个 key 全部已填，不要在对话里贴值）

2026-10-09 复核：全部齐了，Day 3 无前置阻塞。

| 变量 | 状态 |
|---|---|
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | ✅ 已填 |
| `GITHUB_OAUTH_CALLBACK_URL` | ✅ `http://localhost:8000/api/v1/auth/github/callback`（GitHub 后台 Redirect URI 已同步） |
| `JWT_SECRET_KEY` | ✅ 已填（64 字符） |
| `ANTHROPIC_API_KEY` | ✅ 已填（Day 3 用） |
| `ANTHROPIC_BASE_URL` | ✅ `https://llmapi.pro`（中转站） |
| 7 个 `ANTHROPIC_*_MODEL` | ✅ 已填（complex 走 `claude-sonnet-5`，default 走 `claude-haiku-4-5`） |

**坑**：`.env` 第 1 行 `GITHUB_OAUTH_CLIENT_ID = "xxx"` 的等号两边有空格。
pydantic-settings 走 python-dotenv 能容忍，功能正常；但 `grep '^\([A-Z_]*\)='` 这类
脚本会漏掉它。排查 env 时用宽松正则 `^\s*[A-Za-z_][A-Za-z0-9_]*\s*=`。

## 登录闭环（已完成 2026-10-09，未提交）

| 文件 | 内容 |
|---|---|
| `app/gateway/deps.py` | `get_current_user` + `CurrentUser` 别名 |
| `app/gateway/users.py` | `GET /api/v1/me` |
| `app/gateway/auth.py` | `POST /api/v1/auth/logout`（204，不校验登录态，幂等） |
| `app/schemas/user.py` | `MeResponse` |
| `tests/conftest.py` | 提上来共用：`api_db` / `client` / `github_state` |
| `tests/test_session_routes.py` | 11 个测试 |

真实 HTTP 已验证（uvicorn + curl）：无 cookie 401、坏 cookie 401、真票据 200、
登出后 `set-cookie` 带 `Max-Age=0; Path=/`。dev 库未被污染。

## 测试要求

新增功能必须配测试，沿用现有模式：
- DB 用 `db_session` fixture（内存 SQLite）
- 路由用 `api_db` fixture 做 `dependency_overrides`
- 外部 HTTP 用 `monkeypatch` 替换，不用 respx
- OAuth 相关请求要加 `follow_redirects=False`

## 本次会话的实测结论（重新开发前必读）

### 1. 中转站 llmapi.pro 的真实行为

不是照文档猜的，是实测的（`AsyncAnthropic(base_url=...)`）：

| 事实 | 影响 |
|---|---|
| **支持 tool calling**，`stop_reason: tool_use` | 可用 |
| **支持流式**，但会把 243 字符缓冲成 1 个 `text_delta` | 打字机效果必须后端自己补，已由 `TextSlicer` 承担 |
| 流式能收到 `input_json_delta`（工具入参增量） | 可用 |
| **模型返回 `thinking` block**（Sonnet 5 扩展思考） | 必须原样回传，见下条 |
| `model_dump()` 漏 `exclude_none` **不会 400**（中转站接受 `citations: null`） | 但仍保留 `exclude_none=True`：直连官方 API 更保守 |

**thinking + signature 是硬约束**：`signature` 是上游的防篡改签名，改一个字节下一轮就拒。
必须 `final.model_dump(exclude_none=True)` 原样回传进 messages；但**不能**转发给用户
（Anthropic 不建议向非受信端暴露原始 CoT）。这就是「不转发但必须存」的原因。

### 2. `tavily-python` 0.8.5

- `AsyncTavilyClient` 是真协程（`inspect.iscoroutinefunction` 为 True），不用自己包线程池
- 支持注入 `httpx.AsyncClient` 复用连接池
- 无 `py.typed`，已在 `pyproject.toml` 加 mypy override

### 3. 前端硬约束：任一时刻最多一个节点 `active`

前端 `AgentDAG` 用 `findIndex(n => n.lifecycle === 'active')` 算高亮轨道位置，
两个 active 会直接算错。`NodeTracker.activate` 里的 `assert` 是强制这个约束的，
不是装饰代码。

**W2 接 LangGraph 时会冲突**——并行调度天然产生多个 active，必须先解决。

### 4. 节点 id 会重复出现

实测模型「先说话再调工具」时，事件序列是：
`researcher → researcher → writer → researcher → writer...`
（同一个 `researcher` 出现 3 次）。

前端契约必须写死：**按到达顺序追加，不得按 id 去重**。

### 5. SSE 协议

单行 JSON envelope，不用 SSE 原生的多路 `event:`：

```
data: {"type": "delta", "v": {"node_id": "writer", "text": "..."}}

data: {"type": "done", "v": {"session_id": "...", "elapsed_ms": 5432}}
```

五类事件：`node` / `delta` / `tool_call` / `error` / `done`。

**开流后 HTTP 状态码改不了**——鉴权、参数校验都必须在开流前完成；
开流后的失败只能走 `error` 事件。

必须加 `X-Accel-Buffering: no`，否则 Nginx 会缓冲，SSE 攒成一坨最后吐出来。

### 6. 未解决 / 待办

| 事项 | 状态 |
|---|---|
| `TAVILY_API_KEY` | **未申请**。`tavily_search` 返回错误字符串，agent 照常跑完但搜不到东西 |
| `stop_reason == "max_tokens"` 且同时有 tool_calls 时，`truncated` 标记走不到 | 已知 bug，未修（`agent.py`） |
| service 层引入了 logger | 与既有约定「logging 归 gateway」冲突，**待用户定夺** |
| 「打字机」无节奏控制 | `_slice_for_display` 是同步函数，片段同 tick 吐完 |
| `tool_call` 事件驱动 InspectorDrawer | 已做（前端 `bd4e232`） |
| W2 换 LangGraph | 保留 `tools.py`(365 行) / `stream.py`(221 行) / `llm.py` client 单例，只重写循环 |

### 7. 代码审查发现并已修的 bug（别再犯）

1. **`_is_word_char` 用 `isalnum()`，中文也算** → 所有中文标点切分失效，退化成硬切，连 `QPS` 都劈成 `Q` + `PS`。
   必须限定 `isascii()`。
2. **模块级 `_tool_results` 全局变量** → SSE 并发时两个用户的搜索结果互相污染。已改局部变量。
3. **`canonicalize_url` 遇畸形 URL 抛 ValueError** → 一条坏 URL 让整批 dedup 结果消失。
4. **截断计数 off-by-one**，且把「requested 裁掉的」和「字符预算裁掉的」混算 → 模型被告知错误数字。
5. **`RunState` 死代码**：加了 `'error'` 但从不赋值，已删。
6. **heredoc 在本环境会被 shell 截断**（含中文/长字符串时）→ 批量替换多次写坏代码。
   长文本改用 Edit/Write 工具。

### 8. 环境

- 后端 venv 在 `apps/api/.venv`，**不在仓库根**
- uvicorn 启动：`cd apps/api && uv run uvicorn app.main:app --port 8000`
- 调 GitHub API 需要代理 `HTTP_PROXY=http://127.0.0.1:62531`（APNetwork 未运行时不要设）
- `/tmp/jwt.txt` 等临时文件：`rm` 被 `dangerous-cmd-block` hook 拦，需手动删
