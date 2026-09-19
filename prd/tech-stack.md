# Argus — 技术选型

> Version: 0.1.0 · Date: 2026-09-18

## 1. 总览

| 层 | 选型 | 理由 |
|---|---|---|
| 前端框架 | Next.js 14 (App Router) + React 19 | Server Components / Streaming UI / Vercel 部署首选 |
| 前端样式 | Tailwind CSS + shadcn/ui | 主流 / 可定制 / 暗色友好 |
| 前端状态 | Zustand + React Query | 轻量 / SSE 友好 |
| 后端框架 | FastAPI (Python 3.12) | 异步 / 文档自动生成 / 生态成熟 |
| 后端 ORM | SQLAlchemy 2.0 (async) + Alembic | 类型友好 / 迁移成熟 |
| Agent 编排 | LangGraph 1.2+ | 状态机 / 持久化 / Studio 可视化（1.x 已 GA，2025-10-22 发布；当前 1.2.11） |
| RAG | LangChain 1.3+（仅用 loader / splitter） + 自研 retriever | 不过度依赖 LangChain，1.x 后老 API 迁到 `langchain-classic` 包 |
| MCP（可选）| `langchain-mcp-adapters` + `MultiServerMCPClient` | LangChain 1.x 原生支持 MCP，未来接入外部 MCP 服务（如内部工具） |
| Embedding | OpenAI text-embedding-3-small | 性价比 / 多语言 |
| Rerank | Cohere Rerank v3 | 行业标准 / 公开 benchmark 强 |
| 向量存储 | pgvector (HNSW) | 一体化部署 |
| 数据库 | Postgres 16 | 主流 + pgvector 同源 |
| 缓存 / 队列 | Redis 7 | session / rate limit / stream buffer |
| 长期记忆 | Mem0 (云 API) | 集成简单 / 抽象 backend 接口 |
| 评测 | **Arize Phoenix 13.x + `arize-phoenix-evals` 2.12+** | 开源 / LangGraph 集成完善 / 支持 OpenTelemetry |
| Cron | APScheduler | 轻量 / 进程内 / 适合 demo |
| 对象存储 | AWS S3 / MinIO（本地） | 通用 / presigned URL |
| 抓取 | Tavily + Firecrawl | 结构化抓取 / 抗反爬 |
| OCR | Tesseract (本地) + GPT-4V (云) | 文本走本地 / 复杂走云 |
| 视频转写 | AssemblyAI / Whisper API | 业界标准 |
| 鉴权 | Authlib + OAuth (GitHub + Google) | 标准库 / 灵活 |
| 部署 | Vercel (前端) + Docker Compose (后端) | 简单 / 可移植 |
| CI | GitHub Actions + ruff + pytest + Playwright | 主流组合 |
| 包管理 | uv (Python) + pnpm (Node) | 快 / 锁文件清晰 |
| Monorepo | pnpm workspaces + Turborepo | 快 / 增量构建 |

## 2. LLM 选型

> **2026-09 注**：LangChain 1.x 起官方推荐 `langchain.agents.create_agent`（高级抽象，1 行代码起 LangGraph runtime agent）+ Middleware 系统（Summarization / Human-in-the-loop / PII / Guardrails）。Argus 仍走自研 LangGraph 状态机以保留对协作流程的可视化与可控性；Middleware 思路可单独借鉴（尤其 HITL 与 PII 防护）。
>
> **⚠ Anthropic 模型生命周期（关键）**：Claude Sonnet 4.5 在 **2026-09-29** 退役（距今 11 天）— Argus 全线已升级到 **Sonnet 5**（2026-06 末 GA）；Claude Haiku 4.5 在 **2026-10-15** 退役（28 天后）— MVP 期间暂用，**完成后必须升级到 Haiku 5**。Sonnet 5 价格 $2/$10 per 1M tokens，与 Sonnet 4.5 相同（永久保留此价）。Anthropic Python SDK（现已改名为 **Claude SDK**）0.84+ 提供原生 MCP helpers（`mcp_tool` / `async_mcp_tool` / `mcp_message`），未来可挂接外部 MCP 服务。

| 任务 | 模型 | 理由 |
|---|---|---|
| Supervisor 决策 | **Claude Sonnet 5** | 复杂推理 / 工具选择稳定 |
| Researcher 检索规划 | **Claude Sonnet 5** | 同上 |
| Analyst 分析 | **Claude Haiku 4.5** | 性价比 / 简单分析足够（10-15 后须升 Haiku 5） |
| Writer 写作 | **Claude Sonnet 5** | 长文质量 / 引用规范 |
| Critic 自检 | **Claude Haiku 4.5** | 规则校验 / 成本低（10-15 后须升 Haiku 5） |
| Embedding | OpenAI text-embedding-3-small | 多语言 / 维度灵活 |
| 摘要（cron） | **Claude Haiku 4.5** | 性价比 |

**模型路由代码示例**：

```python
# 所有 agent 模型常量集中管理
MODEL_SUPERVISOR = "claude-sonnet-5"
MODEL_RESEARCHER = "claude-sonnet-5"
MODEL_ANALYST = "claude-haiku-4-5"
MODEL_WRITER = "claude-sonnet-5"
MODEL_CRITIC = "claude-haiku-4-5"
MODEL_SUMMARIZER = "claude-haiku-4-5"
```

**路由策略**：每个 agent 内部按 prompt 复杂度自动选 model（prompt cache 命中率 > 80% 时优先 Haiku）。

## 3. 关键库版本

```toml
# backend pyproject.toml
[project]
name = "argus-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.141",          # 2026-07 后 0.141.1（约第 300 次发布），OpenAPI 3.1 + Pydantic v2 native
    "langgraph>=1.2",          # 已 1.x GA，老版本请用 langgraph-classic
    "langchain>=1.3",          # 1.x 后老 API 迁到 langchain-classic
    "langchain-core>=1.6",
    # 可选："langchain-classic" 仅在需要老 LLMChain / AgentExecutor 时装
    # 可选："langchain[mcp]>=1.3" 当接入 MCP 服务时
    # 可选："langchain-mcp-adapters>=0.3.1" 当需要 MultiServerMCPClient 连接外部 MCP server（2026-07-27 发布）
    "pydantic>=2.10",          # 2026-08 后 v2.x 持续更新
    "sqlalchemy[asyncio]>=2.0.36",  # 2026-04 后 2.0.x 持续维护
    "asyncpg>=0.30",
    "pgvector>=0.3",
    "redis>=5.2",
    "mem0ai>=2.0",           # 2026-06-17 发布的 2.0.7
    "tavily-python>=0.8",    # 2026-09-11 发布的 0.8.1
    "firecrawl-py>=4.34",     # 2026-08-04 发布的 4.34.0；>=1.0 已过时
    "arize-phoenix>=13.0",   # 13.18.0+（含 prompt diff / structured evals）
    "arize-phoenix-evals>=2.12",
    "assemblyai>=0.65",       # 0.65+ 引入 asyncio AsyncTranscriber（2026-08）
    "authlib>=1.8",          # 2026-05-06；必须 >=1.6.9 修复 CVE-2026-28498 OIDC ID Token 验证 fail-open
    "structlog>=24.4",
    "apscheduler>=3.10",
    "openai>=3.14",          # 2026-09-15 发布的 3.14.1
    "anthropic>=0.84",        # Claude SDK（原 Anthropic Python SDK，已在 0.84+ 引入原生 MCP helpers mcp_tool/async_mcp_tool/mcp_message）
    "pymupdf>=1.24",
    "pytesseract>=0.3",
    "cohere>=7.1",           # 2026-08-31 发布的 7.1.1
    "tenacity>=9.0",
    "uvicorn[standard]>=0.32",
]
```

```json
// frontend package.json
{
  "dependencies": {
    "next": "^14.2",
    "react": "^19.0",
    "tailwindcss": "^3.4",
    "@radix-ui/react-*": "latest",
    "zustand": "^5.0",
    "@tanstack/react-query": "^5.59",
    "date-fns": "^4.1",
    "recharts": "^2.13"
  }
}
```

## 4. 备选与回退

| 选型 | 备选 | 何时切 |
|---|---|---|
| LangGraph 1.x | AutoGen / CrewAI / 手写 | 多 agent 协作失败 / 调试困难（LangChain 1.0 后 LangGraph 是新 agent 工作流的官方推荐，老 AgentExecutor 已弃用） |
| Mem0 | Letta / 自研 | Mem0 API 不可用 / 反思质量不达标 |
| pgvector | Qdrant / Milvus | 数据 > 100k / 检索延迟 > 1s |
| FastAPI | Django / Litestar | 团队熟悉度差异 |
| Next.js | Remix / SvelteKit | 团队偏好 |
| Anthropic | OpenAI / Gemini | 价格 / 政策变动 |
| Tavily | Bing / Brave / Serper | API 不稳定 |
| APScheduler | Celery / Temporal | 任务复杂度升级 |
| Authlib | Clerk / Supabase Auth | 想要省力 / 多 SSO |

## 5. 不选型

| 项 | 不选原因 |
|---|---|
| LlamaIndex | 抽象太重，与 LangGraph 1.x 重复 |
| HuggingFace transformers | 本地推理成本高，demo 不需要 |
| Airflow | 重，APScheduler 足够 |
| Pinia / Redux | 前端选 Zustand 更轻 |
| WebSocket | SSE 足够（单向流） |
| GraphQL | REST + JSON Schema 更易调试 |