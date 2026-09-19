# Argus · CHANGELOG

> 项目变更日志。遵循 [Keep a Changelog](https://keepachangelog.com/) 格式。

## [Unreleased]

### Added
- 初始 PRD + 9 份设计文档 + README 落地到 `~/Projects/argus/prd/`
- LangChain / LangGraph 升级到 1.x GA 选型
- 3 个核心流程图（顶层架构 / LangGraph 节点图 / RAG pipeline）全部加中文注解
- **CHANGELOG.md**（本文件）建立版本管理基线

### Verified（2026-09-18 联网核查）

| 项 | 事实 |
|---|---|
| **LangGraph 稳定版** | **1.2.11**（2026-08-11，PyPI 确认） |
| **LangChain 稳定版** | **1.3.x**（1.0 首发于 2025-10-22） |
| **LangChain v1.x 关键新特性** | `langchain.agents.create_agent` + Middleware（SUMM/HITL/PII/Guardrails） + `langchain_mcp_adapters`（`MultiServerMCPClient`） + Structured output |
| **LangGraph 1.x 关键新特性** | `langgraph-checkpoint` 4.x + DeltaChannel（beta，增量快照） + Streaming v3（per-channel 投影） + 细粒度 interrupt |
| **Anthropic 当前活跃模型** | **Haiku 4.5 / Sonnet 5 / Opus 5 / Fable 5**（4 档，Sonnet 5 于 2026-06 末 GA） |
| **⚠ 退役警告（影响 Argus LLM 路由）** | **Claude Sonnet 4.5 将在 2026-09-29 退役（11 天后）** / **Claude Haiku 4.5 将在 2026-10-15 退役（28 天后）** |
| **Mem0 Python 包** | **`mem0ai` v2.0.7**（2026-06-17，Apache-2.0，`from mem0 import Memory`） |
| **Mem0 默认配置** | OpenAI gpt-5-mini + text-embedding-3-small（1536 维）+ Qdrant + SQLite history |
| **Arize Phoenix** | **`arize-phoenix` 13.x + `arize-phoenix-evals` 2.12+**（`pip install arize-phoenix arize-phoenix-evals openai`） |

### Changed
- **LLM 路由（紧急）**：所有 agent 的 Sonnet 4.5 → **Sonnet 5**（避免 11 天后 API 失效）
- **Sonnet 5 价格**：$2 / $10 output per 1M tokens（与 Sonnet 4.5 相同，永久保留此价）
- **Critic 模型（暂用）**：仍走 Haiku 4.5；MVP 完成后须升级到 Haiku 5 或 Sonnet 5
- **Phoenix 版本**：`>=6.0` → `>=13.0` + 新增 `arize-phoenix-evals>=2.12`
- **Docker 镜像**：`arizephoenix/phoenix:latest` → `arizephoenix/phoenix:version-13.18.0`（官方命名规则 `version-X.X.X`，确保可重现构建）
- **pyproject 版本号全面校准**（联网核实 2026-09）：
  - `openai >=1.50` → **`openai >=3.14`**（3.14.1 / 2026-09-15）
  - `cohere >=5.13` → **`cohere >=7.1`**（7.1.1 / 2026-08-31）
  - `tavily-python >=0.5` → **`tavily-python >=0.8`**（0.8.1 / 2026-09-11）
  - `mem0ai >=0.1` → **`mem0ai >=2.0`**（2.0.7 / 2026-06-17）
- **9 份文档统一升级**：tech-stack / multi-agent / evaluation / deployment / sprint-plan / prd / README / CHANGELOG 全部同步到 Sonnet 5 / Phoenix 13 / Mem0 2.0.7 / OpenAI 3.14 / Cohere 7.1 / Tavily 0.8
- **第二批 pyproject 升级**（联网核实 2026-09）：
  - `assemblyai >=0.35` → **`>=0.65`**（2026-08 引入 asyncio AsyncTranscriber）
  - `anthropic >=0.40` → **`>=0.84`**（**SDK 已改名为 Claude SDK**，0.84+ 原生 MCP helpers）
  - `firecrawl-py >=1.0` → **`>=4.34`**（2026-08-04 最新）
  - `authlib >=1.3` → **`>=1.8`**（**必须 ≥1.6.9 修复 CVE-2026-28498** OIDC ID Token fail-open）
- ⚠ **安全提醒**：Argus 部署前必须确认 `pip install` 拉到 authlib ≥1.6.9；老版本 OIDC 验证存在 bypass 风险
- **新增 2 份文档**：
  - `risk-and-compliance.md` — 集中登记退役警告（Sonent 4.5 11 天后）、CVE-2026-28498（authlib）、许可证矩阵、能力边界
  - `W0-decisions.md` — 22 项关键决策点 + 用户主动排除项 + 立项日期，便于 W1-W4 启动回看
- **README / CHANGELOG / tech-stack 已同步**：目录导航覆盖全部 13 份设计文档
- **第三批 pyproject 升级**（联网核实 2026-09）：
  - `fastapi >=0.115` → **`>=0.141`**（2026-07 后 0.141.1，约第 300 次发布）
  - `pydantic >=2.9` → **`>=2.10`**（Rust-backed 持续更新）
  - `sqlalchemy[asyncio] >=2.0` → **`>=2.0.36`**（2.0.x 持续维护）
  - 新增注释：`langchain-mcp-adapters>=0.3.1`（可选，2026-07-27 发布，用于 MultiServerMCPClient）
- **13 个核心库版本号全部联网核实完毕**

---

## [0.1.0] - 2026-09-18

### Added
- 项目命名 **Argus**（希腊神话百眼巨人，象征多视角洞察）
- 场景定位：**新闻 / 舆情 / 趋势追踪**研究助手（不做论文方向）
- 4 件套核心能力：工具调用 / RAG / 多 agent 编排 / 长期记忆
- 8 份设计文档 + 1 份 PRD + 1 份 README：
  - `prd.md` — 产品需求
  - `architecture.md` — 系统架构 + 数据流
  - `tech-stack.md` — 完整技术选型
  - `multi-agent-design.md` — LangGraph 5 agent 状态机
  - `rag-pipeline.md` — RAG 全链路
  - `memory-design.md` — Mem0 长期记忆集成
  - `evaluation.md` — Phoenix + 自研指标
  - `deployment.md` — Docker Compose + Vercel
  - `sprint-plan.md` — 4 周（W1-W4）每日任务

### 关键决策（已锁定）
- 多 agent 框架：**LangGraph 1.2.x**（自研状态机，保留可视化与可控性）
- 长期记忆：**Mem0（`mem0ai` v2.0.7）** 集成 + MemoryBackend 抽象（可换 Letta / 自研）
- 向量存储：**pgvector** 一体化（HNSW）
- LLM 路由（**2026-09 升级**）：**Claude Sonnet 5** 复杂任务 / **Haiku 4.5** 简单任务
- 抓取：**Tavily + Firecrawl**（含 OCR / 视频转写）
- Embedding：**OpenAI text-embedding-3-small**（维度 512）
- Rerank：**Cohere Rerank v3**
- 评测：**Arize Phoenix 13.x + `arize-phoenix-evals` 2.12+** + 自研指标
- 鉴权：**OAuth (GitHub + Google)** + Postgres RLS
- 部署：**Vercel（前端） + Docker Compose（后端）**
- CI：**ruff + pytest + Playwright e2e**

### 演示数据集
- 预置 **200 篇** AI / 科技领域文章
  - 100 篇 LLM / Agent
  - 50 篇 机器人 / 自动驾驶
  - 30 篇 芯片 / 硬件
  - 20 篇 政策 / 监管

### 演示能力
- 多视图：报告 / 对比表 / 时间线 / 决策清单
- 多模态输入：文本 + 图片
- 抓取深度：重量级（视频转写 / OCR）
- 主动追踪：订阅主题 + cron 6h 后台拉取
- 推送渠道：UI 内通知
- 多用户：OAuth 登录 + 订阅隔离

---

## 版本说明

- 当前阶段：**W0 文档阶段**（PRD + 架构落地，未写代码）
- 下一步：**W1** Repo 骨架 + 单 agent + UI（详见 `sprint-plan.md`）
- 公开仓库：**待定**（W4 验收后发布）
- ⚠ **行动项**：在 **2026-09-29 前**完成 Anthropic 模型从 Sonnet 4.5 → Sonnet 5 的全部代码迁移

---

## W0 阶段总结（2026-09-18）

**交付**：13 份文档落地 `~/Projects/argus/prd/`，**14 个核心库版本号联网核实完毕**。

**关键事实**：
- ✅ 所有 agent 模型路由从 Sonnet 4.5 → **Sonnet 5**（09-29 退役前完成）
- ✅ Anthropic Claude SDK 改名、0.84+ 原生 MCP helpers 已纳入
- ✅ LangGraph 1.2.11 / LangChain 1.3.x / LangChain MCP 0.3.1 已锁版本
- ✅ Phoenix 13.x + Docker 镜像 `version-13.18.0` 已固定
- ✅ authlib CVE-2026-28498 已在 pyproject 强制 ≥1.8
- ✅ Mem0 2.0.7 / OpenAI 3.14 / Cohere 7.1 / Tavily 0.8 / Firecrawl 4.34 / AssemblyAI 0.65 全部最新

**W1 启动 checklist**（来自 `sprint-plan.md` Day 1-3）：
- [ ] monorepo init（pnpm + uv + Turborepo）
- [ ] Docker Compose 起 Postgres + Redis
- [ ] FastAPI 骨架 + SQLAlchemy + Alembic
- [ ] **OAuth 集成（authlib ≥1.8，避开 CVE-2026-28498）**
- [ ] 单 agent 接入 **Claude Sonnet 5**（**不是** Sonent 4.5，09-29 退役）
- [ ] 工具调用闭环：tavily_search / web_fetch / dedup

**W4 验收前必须完成**：
- [ ] 2026-10-15 前把 Haiku 4.5 升到 Haiku 5
- [ ] 监控 `authlib >= 1.6.9`（CVE 修复线）
- [ ] 13 份文档随 W1-W4 实现同步更新（不要变成过期文档）

**非本阶段交付（不在 prd/ 目录）**：
- LICENSE / CONTRIBUTING.md / Issue Templates（仓库根目录）
- seed_demo_data.py（scripts/）
- .env.example（部署时直接写）