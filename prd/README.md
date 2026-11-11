# Argus · 多视角新闻 / 舆情 / 趋势追踪研究助手

> **Argus** — Multi-perspective research assistant for news, sentiment, and trend tracking.
> 一个由多 agent 编排驱动的个人 / 小团队研究助手，融合工具调用、RAG、多 agent 协作、长期记忆四项能力。

希腊神话 Argus Panoptes 百眼巨人——多视角、不遗漏。

[![LangChain](https://img.shields.io/badge/LangChain-1.3.x-blue)]()
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.x-blue)]()
[![Phoenix](https://img.shields.io/badge/Phoenix-13.x-purple)]()
[![Claude](https://img.shields.io/badge/Claude-Sonnet%205-orange)]()
[![Visibility](https://img.shields.io/badge/visibility-PUBLIC-green)]()
[![Status](https://img.shields.io/badge/status-MVP-yellow)]()

> 本 README 记录的是 W0 设计阶段（2026-09-19）的方案。实现已在 `apps/api` 与
> `apps/web` 中落地，当前状态见[仓库根 README](../README.md)。
> 本文件保留为设计决策的历史记录——里面的技术选型有些已被实现推翻
> （例如向量存储实际用 sqlite-vec 而非 pgvector），以正文为准。

---

## 一句话定位

用户上传文档、订阅主题或粘贴 URL，Supervisor agent 自动调度 Researcher / Analyst / Writer / Critic 四类子 agent，从多源（用户资料库 + 实时网页 + 长期记忆）聚合、去重、分析、写作，最终以「报告 / 对比表 / 时间线 / 决策清单」多视图交付**带引用的研究产出**。

---

## 核心能力（四件套）

| 能力 | Argus 的实现 |
|---|---|
| 🛠 **工具调用** | 自定义工具（tavily_search / web_scrape / rag_retrieve / memory_recall / dedup / sentiment ...） |
| 📚 **RAG** | 多路召回（向量 + BM25）+ Cohere Rerank v3 + pgvector（HNSW）+ 引用可追溯 |
| 🤖 **多 agent 编排** | LangGraph 1.x 状态机：Supervisor → Researcher / Analyst / Writer → Critic 闭环 |
| 🧠 **长期记忆** | Mem0 集成 + MemoryBackend 抽象 + 会话级反思（preference / history / reflection） |

---

## 架构速览

```
┌─────────────────────────────────────────────────────────────────┐
│             【前端】Browser (Next.js 14 / React 19)              │
│   · 上传 / 提问 / 订阅 UI                                       │
│   · agent 工作流时间轴（LangGraph Studio 风格）                  │
│   · 4 种视图：报告 / 对比表 / 时间线 / 决策清单                  │
└───────────────────────┬─────────────────────────────────────────┘
                        │ REST + SSE
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│       【网关】FastAPI Gateway (Python 3.12 / async)             │
│   · OAuth (GitHub / Google) + 流式响应                          │
└────┬──────────────────┬───────────────────┬────────────────────┘
     ▼                  ▼                   ▼
┌────────────┐  ┌──────────────┐  ┌──────────────────┐
│ LangGraph  │  │ RAG Service  │  │ Cron Worker      │
│ 5-Agent    │  │ (pgvector)   │  │ (APScheduler)    │
│ 编排       │  │ + Cohere     │  │ · RSS / 去重     │
│ Supervisor │  │ Rerank       │  │ · 摘要 / 通知    │
│ +4 Worker  │  │ + Citation   │  │                  │
└─────┬──────┘  └──────┬───────┘  └────────┬─────────┘
      └────────────────┼───────────────────┘
                       ▼
        ┌──────────────────────────────────┐
        │ Postgres 16 + pgvector + Redis   │
        │  · docs / chunks / reports / run │
        │  · RLS 用户级隔离                │
        └──────────────────────────────────┘

  横切：Mem0 长期记忆 · Phoenix trace · External APIs
       (Anthropic Claude · OpenAI · Tavily · Firecrawl · S3)
```

---

## 目录导航

> 本 README 是入口。**所有详细设计都在同级目录的 8 份文档里**。

| 文档 | 内容 |
|---|---|
| [prd.md](./prd.md) | 产品 PRD：问题、目标、用户故事、范围、验收、风险 |
| [architecture.md](./architecture.md) | 系统架构图 + 模块拆分 + 数据流 + 关键技术决策 |
| [tech-stack.md](./tech-stack.md) | 完整技术选型 + 理由 + 备选（LangChain 1.x / LangGraph 1.x / pgvector / Mem0） |
| [multi-agent-design.md](./multi-agent-design.md) | LangGraph 5 agent 状态机 + 协作协议 + 工具调用 |
| [rag-pipeline.md](./rag-pipeline.md) | RAG 全链路：chunking / embedding / 混合检索 / rerank / citation |
| [memory-design.md](./memory-design.md) | Mem0 集成 + MemoryBackend 抽象 + 反思策略 |
| [evaluation.md](./evaluation.md) | Phoenix + 自研指标 + 数据集 + CI 集成 |
| [deployment.md](./deployment.md) | Docker Compose + Vercel + CI/CD + 监控 + 备份 + 成本 |
| [sprint-plan.md](./sprint-plan.md) | W1-W4（28 天）每日任务 + 验收标准 + 回退方案 |
| [risk-and-compliance.md](./risk-and-compliance.md) | 退役警告（Sonent 4.5 11 天后）/ CVE 提醒 / 版本基线 / 许可证矩阵 |
| [W0-decisions.md](./W0-decisions.md) | 22 项关键决策点 + 排除项 + 立项日期，便于 W1 启动回看 |
| [CHANGELOG.md](./CHANGELOG.md) | 项目变更日志（联网核实 13 个核心库版本号 + Anthropic 退役预警） |

---

## 快速开始（5 分钟跑起来）

> **前提**：Docker、Docker Compose、≥4GB RAM。

```bash
# 1. 克隆
git clone https://github.com/yourname/argus.git
cd argus

# 2. 准备环境变量
cp .env.example .env
# 编辑 .env，至少填入：
#   ANTHROPIC_API_KEY
#   OPENAI_API_KEY
#   TAVILY_API_KEY
#   COHERE_API_KEY
#   MEM0_API_KEY
#   GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET
#   GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET

# 3. 启动
docker compose up -d

# 4. 等服务就绪（约 1-3 分钟）
docker compose ps

# 5. 打开浏览器
#   · 前端  http://localhost:3000
#   · API   http://localhost:8000/docs
#   · Phoenix trace  http://localhost:6006
```

预置 200 篇 AI / 科技 demo 数据集由 `scripts/seed_demo_data.py` 自动加载。

---

## 路线图（4 周）

| 周 | 主题 | 关键交付 |
|---|---|---|
| W1 | Repo + 单 agent + UI 骨架 | 可跑通「提问 → 单 agent 答」 |
| W2 | RAG + 多 agent + 长期记忆 | 可跑通「上传 PDF → 多 agent 出报告」 |
| W3 | 主动追踪 + 多视图 + Auth + 评测 | 完整产品形态 + 评测指标上线 |
| W4 | 部署 + CI + 开源包装 + 文档 | 公开 repo + 一键跑起来 |

详见 [sprint-plan.md](./sprint-plan.md)。

---

## 技术栈亮点

- **LangGraph 1.2.x**：状态机 + Postgres checkpointer（4.x）+ LangGraph Studio 可视化 + streaming v3
- **LangChain 1.3.x**：可选 `create_agent`（高阶抽象）+ Middleware（HITL / PII / Summarization）+ MCP 原生（`langchain_mcp_adapters`）；Argus 走自研状态机以保留可控性
- **pgvector + HNSW**：向量与关系数据一体，RLS 用户级隔离
- **Mem0**：长期记忆云服务，MemoryBackend 抽象可替换自研
- **Phoenix (Arize)**：trace + evaluate 自动收集
- **Anthropic Claude Sonnet 5 / Haiku 4.5**：复杂任务 Sonnet 5，简单任务 Haiku 4.5 路由（**Sonnet 4.5 已在 09-29 退役**）
- **Next.js 14 (App Router) + React 19 + Tailwind + shadcn/ui**：现代前端
- **FastAPI (Python 3.12) + SQLAlchemy 2.0 async + uv**：高性能异步后端
- **Docker Compose + Vercel**：本地 / VPS / 生产全覆盖

---

## 用户场景示例

1. **订阅「AI 行业动态」**：每 6 小时后台自动拉取新文章，UI 通知中心提示。
2. **上传 NVIDIA 财报 PDF**：问「H100 与 Blackwell 差异」→ 多 agent 出带引用的对比表。
3. **时间线视图**：同一主题按周 / 月聚合事件，判断趋势走向。
4. **跨会话记忆**：agent 记住你上次关心的子主题，下次自动优先。
5. **点击追溯**：报告里 `[3]` 可点开，看 chunk 原文 + 文档来源。

---

## 贡献

- 🐛 [Issues](https://github.com/yourname/argus/issues) — Bug / Feature 报告
- 🔀 [Pull Requests](https://github.com/yourname/argus/pulls) — 代码贡献
- 📋 [CONTRIBUTING.md](../../CONTRIBUTING.md)（仓库根目录）— 开发流程、PR 模板

---

## License

MIT © 2026 Argus Contributors

> 命名 Argus 取自希腊神话百眼巨人 Argus Panoptes，象征「多视角洞察，不遗漏」。