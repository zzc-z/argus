# Argus — 系统架构

> Version: 0.1.0 · Date: 2026-09-18

## 1. 顶层架构图（含中文注解）

```
┌────────────────────────────────────────────────────────────────────────┐
│                     【前端层】Browser (Next.js 14 / React 19)          │
│  · 用户面：上传 / 提问 / 订阅                                          │
│  · 实时展示：agent 工作流时间轴（LangGraph Studio 风格）                │
│  · 多视图切换：报告 / 对比表 / 时间线 / 决策清单                       │
│  · 通知中心：cron 拉取的新内容推送                                     │
└───────────────────────┬────────────────────────────────────────────────┘
                        │ REST（请求/响应）+ SSE（服务端单向流，推送 agent 进度）
                        ▼
┌────────────────────────────────────────────────────────────────────────┐
│                【网关层】FastAPI Gateway (Python 3.12 / async)         │
│  · 鉴权：OAuth 2.0（GitHub / Google，Authlib）                         │
│  · 路由：/api/research /api/upload /api/subscriptions 等               │
│  · 流式响应：把 LangGraph 节点事件实时转 SSE 给前端                    │
└───────────────────────┬────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐
│【智能层①】  │ │【智能层②】  │ │【智能层③】          │
│ LangGraph   │ │ RAG Service │ │ Cron Worker          │
│ Runtime     │ │ (pgvector)  │ │ (APScheduler)        │
│             │ │             │ │                      │
│ 多 agent    │ │ 文档入库 +  │ │ · 后台拉 RSS / API   │
│ 编排：      │ │ 检索融合：  │ │ · 跨源去重            │
│ · Supervisor│ │ · chunking  │ │ · 调用 LLM 生成摘要   │
│ · Researcher│ │ · embedding │ │ · 写入向量库 + 通知   │
│ · Analyst   │ │ · rerank    │ │                      │
│ · Writer    │ │ · citation  │ │                      │
│ · Critic    │ │             │ │                      │
└──────┬──────┘ └──────┬──────┘ └──────────┬───────────┘
       │               │                  │
       └───────────────┼──────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│         【存储层】Postgres 16 + pgvector（HNSW） + Redis 7             │
│  · users / sessions / subscriptions（用户与会话）                      │
│  · documents / chunks（向量维度 512，存 OpenAI text-embedding-3-small）│
│  · reports / agent_runs（LangGraph checkpointer 落盘的状态快照）       │
│  · notifications / scheduled_jobs（订阅与定时任务）                    │
│  · Redis：SSE 流缓冲 / 限流计数 / Embedding 缓存 / JWT 黑名单         │
└────────────────────────────────────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐
│【横切层①】   │ │【横切层②】   │ │【横切层③】         │
│ Memory       │ │ Phoenix      │ │ External APIs        │
│ Backend      │ │ (Arize)      │ │ （外部服务）         │
│ (Mem0)       │ │              │ │                      │
│              │ │ 可观测性：   │ │ · Anthropic Claude   │
│ · 用户偏好   │ │ · trace      │ │   （Sonnet 4.5 /     │
│ · 主题历史   │ │ · evaluate   │ │    Haiku 4.5）        │
│ · 反思记忆   │ │ · datasets   │ │ · OpenAI（embedding）│
│              │ │              │ │ · Tavily（搜索）     │
│              │ │              │ │ · Firecrawl（抓取）  │
│              │ │              │ │ · AWS S3 / MinIO     │
│              │ │              │ │   （文件存储）        │
└──────────────┘ └──────────────┘ └─────────────────────┘
```

**流向说明**：
- 主路径：浏览器 → 网关 → LangGraph / RAG / Cron → Postgres → 网关 SSE 推回浏览器
- 写路径：用户上传 → S3 → 后端处理 → pgvector 写入
- 评测路径：LangGraph / RAG 调用 → Phoenix 自动收集 trace → 触发 LLM-as-judge → 落 Postgres

## 2. 模块拆分

### 2.1 前端（apps/web）

| 路径 | 职责 |
|---|---|
| `app/(auth)/login` | OAuth 登录页 |
| `app/(dashboard)/topics` | 主题订阅 / 管理 |
| `app/(dashboard)/sources` | 上传文档 / 链接 / RSS 管理 |
| `app/(dashboard)/research/[id]` | 研究会话 + 实时 agent 工作流 |
| `app/(dashboard)/reports/[id]` | 多视图报告查看 |
| `app/(dashboard)/notifications` | 通知中心 |
| `components/agent-flow` | 自研 agent 时间轴组件（参考 LangGraph Studio） |
| `components/report-views` | 4 种视图渲染器 |
| `lib/api` | FastAPI 客户端 + SSE 订阅 |

### 2.2 后端（apps/api）

| 模块 | 职责 | 文件 |
|---|---|---|
| `gateway` | FastAPI 路由 + OAuth | `gateway/main.py` |
| `agents` | LangGraph 状态机 + 4 子 agent | `agents/graph.py` `agents/{researcher,analyst,writer,critic}.py` |
| `rag` | chunking / embedding / rerank | `rag/{chunker,embedder,reranker,retriever}.py` |
| `memory` | Mem0 适配器 + 反思循环 | `memory/{backend,reflector}.py` |
| `tools` | 工具注册表 + schema | `tools/{search,scrape,parse,dedup,sentiment,image_caption}.py` |
| `scheduler` | APScheduler cron jobs | `scheduler/{rss_poller,dedup_worker}.py` |
| `models` | SQLAlchemy ORM | `models/{user,document,subscription,report,notification}.py` |
| `eval` | Phoenix 客户端 + 自研指标 | `eval/{phoenix,metrics}.py` |

### 2.3 共享（packages/shared）

| 模块 | 职责 |
|---|---|
| `schemas` | Pydantic models（前后端共享） |
| `types` | TypeScript type（前端 import） |
| `prompts` | 所有 agent prompt 模板 |
| `config` | 环境变量 + 配置加载 |

## 3. 数据流（核心路径）

### 3.1 用户提问路径
```
1. 用户在 UI 输入：「对比英伟达 H100 与 Blackwell」
2. 前端 POST /api/research → FastAPI
3. FastAPI 创建 agent_run（state 初始）
4. Supervisor agent 进入 LangGraph 状态机：
   a. Researcher 接收任务 → 调用 tavily_search / fetch / scrape → 拿到网页
   b. Researcher 调用 RAG retriever 从 pgvector 取相关 chunks
   c. Analyst 拿到原始资料 → 调用 sentiment / dedup / classify 工具
   d. Writer 收到结构化分析 → 写报告草稿（含 [1][2] 引用标记）
   e. Critic 校验 faithfulness（对照原文）→ 若不通过则回 Writer 重写
   f. 终稿写入 reports 表
5. SSE 推送每步状态到前端
6. 前端实时渲染时间轴 + 最终报告
```

### 3.2 Cron 拉取路径
```
1. APScheduler 每 6h 触发主题扫描
2. 对每个订阅：
   a. RSS poller 抓 RSS / API
   b. dedup worker 用 simhash + URL canonicalize 去重
   c. summarizer agent 给每条新内容生成摘要
   d. embedding + 写入 pgvector
   e. notification 写入 notifications 表
3. UI 通过 SSE 收到通知
```

### 3.3 上传文档路径
```
1. 用户拖拽 PDF / 图片 → 前端直传 S3（presigned URL）
2. S3 触发 Lambda → 调后端 /api/process_document
3. 后端：
   a. parser 提取文本（PyMuPDF / Tesseract OCR）
   b. chunker 切片（RecursiveTextSplitter, 512/64）
   c. embedder 生成向量（OpenAI text-embedding-3-small）
   d. 批量写入 pgvector（事务）
4. SSE 通知前端「已就绪」
```

## 4. 关键技术决策

### 4.1 为什么 LangGraph 而非 AutoGen / CrewAI
- 状态机可视化（LangGraph Studio）
- interrupt / resume 支持（人机协作）
- 持久化（Postgres checkpointer）开箱即用
- Phoenix 集成最完善

### 4.2 为什么 pgvector 而非 Qdrant
- 一体化部署（少一个服务）
- 200 篇 demo 数据集量级够用
- HNSW 索引性能足够

### 4.3 为什么 Vercel + Docker Compose
- 前端 Vercel 一键部署、自动 HTTPS、edge
- 后端 Docker Compose 本地 / VPS 都能跑
- 前后端解耦，符合现代部署范式

### 4.4 为什么 Mem0 而非 Letta
- Mem0 API 更简单、易集成
- 反思策略可通过 prompt 自定义
- Letta 更适合「agent 自身记忆」，Argus 主要是「用户偏好记忆」

## 5. 安全 / 鉴权

- OAuth 2.0（GitHub + Google）通过 Authlib
- JWT 短期 access token + refresh token（Redis 黑名单）
- 所有 RAG 查询带 user_id 过滤（RLS 行级安全）
- 文件上传走 presigned URL，前端不可直传后端
- API 限流：每用户 60 req/min（Redis token bucket）

## 6. 可观测性

- **Trace**：每个 agent_run → Phoenix project，spans 记录 LLM/tool 调用
- **Log**：structlog → Loki（Docker Compose 内置）
- **Metric**：Prometheus → Grafana（token / 延迟 / 失败率）
- **Alert**：研究任务失败率 > 5% / 平均 token > 20k 触发 webhook

## 7. 扩展点

| 当前 | 未来可扩展 |
|---|---|
| Tavily search | 接入 Bing / Brave / 自建爬虫集群 |
| Mem0 | 自研 MemoryBackend（高级反思） |
| Phoenix | 接入 LangSmith / 自研评测平台 |
| APScheduler | Temporal / Argo Workflows（生产级） |
| pgvector | Qdrant / Milvus（百万级） |