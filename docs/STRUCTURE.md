# Argus 项目结构

> 最后更新：2026-11-21（按磁盘现状核对：mock 状态、services 拆分、docs 清单）
> ⚠️ 2026-09 之前本文档描述的是**实施计划**（大量 "W1/W2 待写"），实际早已实现。
> 现已按磁盘现状重写。

## 顶层

```
argus/
├── prd/                  # 13 份 W0 设计文档（只读）
├── apps/
│   ├── api/              # FastAPI 后端（uv）
│   └── web/              # Next.js 16 前端（pnpm）
├── packages/shared/      # 前后端共享 TS 类型（types/ + schemas/，实际使用很少）
├── docs/                 # 项目文档（13 份，见下表）
├── AGENTS.md             # agent 入口约定
├── CLAUDE.md             # /code-review 的审查规则依据
├── package.json          # 根 monorepo（pnpm workspace + turbo）
├── pnpm-workspace.yaml
├── turbo.json
└── tsconfig.base.json
```

> `infra/` 与 `scripts/` 在计划里出现过，**实际不存在**。数据库是 SQLite
> （`apps/api/argus.db`），无 postgres / redis / nginx。

## docs/ — 项目文档

| 文件 | 作用 |
|---|---|
| `STRUCTURE.md` | 本文件。项目结构 |
| `CONVENTIONS.md` | 代码规范（命名 / 嵌套 / 状态 / a11y / token） |
| `LOCAL-DEV.md` | 本地环境。**新会话接手先读这份**——几件「做错不报错、只表现为数据是旧的」的事写在这里 |
| `TODO-frontend-a11y-platform-ui.md` | 前端待办：a11y 缺口 + 平台 UI 原语 + 主题机制三处问题 |

> `prd/` 是只读的设计文档，**不随实现改动**。

## apps/api/ — FastAPI 后端

`app/` 下只有 4 个包 + 4 个顶层模块：

| 路径 | 作用 |
|---|---|
| `app/gateway/` | HTTP 路由。`auth` / `dashboard` / `sources` / `reports` / `research` / `users` / `health` / `deps`（鉴权依赖） |
| `app/services/` | 业务逻辑。34 个模块，见下表 |
| `app/models/` | SQLAlchemy ORM。`user` / `source` / `report` |
| `app/schemas/` | Pydantic 出入参。**改 API 前必读**（前端 `lib/api/*.ts` 的类型与之对应） |

`app/services/` 按职责分组：

| 组 | 模块 |
|---|---|
| agent 主循环 | `agent`（主循环）、`agent_nodes`（Stage 枚举 / NodeTracker）、`agent_turn`（单轮请求）、`agent_tools`（工具执行与检索上下文）、`agent_ledger`（用量记账）、`agent_failures`、`stages`（Supervisor / Analyst） |
| 检索 | `retriever` `bm25` `embedder` `vectorstore`（sqlite-vec）`chunker` |
| 摄取 | `ingest` `parser` `fetcher` `storage` `web_sources` `urls` |
| 引用与校验 | `citation` `faithfulness`（Critic 引用校验） |
| 错误分类 | `errors_base` `errors` `errors_tavily` |
| 其他 | `llm` `stream`（SSE 编码）`persistence` `runs` `tasks` `auth` `token`（JWT）`tools` |

> **agent 编排是手写的**，`agent.py` 的 docstring 明确「不用 LangGraph」。
> `pyproject.toml` 里声明了 `langgraph` / `langchain-core`，但**代码里一处没用**——
> 是计划遗留，别以为装了就等于用上了。

| 其他 | 作用 |
|---|---|
| `alembic/` `alembic.ini` | DB 迁移。**改了 `app/models/` 必须生成迁移** |
| `eval/` | agent 评测：`calibrate_judge.py`（judge 一致率校准）、`golden.py` + `datasets/golden_v1.jsonl`、`injection_probe.py`、`reports/`（校准与注入探测结果） |
| `tests/` | pytest，48 个文件 |
| `scripts/dev_login.py` | 本地造 session（绕过 GitHub OAuth） |
| `uploads/` | 摄取的原文件落地目录 |
| `argus.db` | SQLite 数据库文件 |

## apps/web/ — Next.js 16 前端

**无 `app/api/` 路由**——前端只调后端 `http://localhost:8000/api/v1/*`。

### 路由组

| 路径 | 作用 |
|---|---|
| `app/(auth)/login/` | OAuth 登录页（12 个子组件） |
| `app/(dashboard)/` | 主应用（`layout.tsx` = 侧边栏 + 顶栏 + `AuthGuard`） |
| `app/(error)/error-500/` | 500 错误页 |

### (dashboard) 页面与数据来源

| 路径 | 后端状态 |
|---|---|
| `add-sources/` | ✅ 已接真接口（上传 / URL 建源 / 摄取队列轮询） |
| `sources/` | ✅ 已接真接口 |
| `explore/` | ✅ 已接真接口（run / SSE 流 / 引用校验面板） |
| `reports/` `report/[id]/` | ✅ 已接真接口（`fetchReports` / 报告详情） |
| `dashboard/` | ✅ 已接真接口（`GET /api/v1/dashboard`）——`view.ts` 里的假数据已删，只剩静态文案与映射函数 |
| `settings/` | ✅ 已接真接口 |
| `topics/` | 静态导航页（只列「下一步去哪」的三张卡片，无数据） |
| `notifications/` | ⚠️ 后端无 notifications 表也无查询接口。页面只显示 `NotificationsContext` 推送的真实增量事件；`mock.ts` 里只剩**类型定义与筛选常量**（文件名保留，导入方不动） |
| `error-404/` | 静态 404 页。`mock.ts` 是诊断快照（原设计的「集群故障」假数据已删——后端一个字段都没有） |
| `components/` | `AuthGuard`（登录守卫）、`UserMenu`（顶栏用户菜单）、`ServiceStatusCard` / `ServiceStatusPill`、`SessionBadge`、`QuickKeys.tsx` |

### 共享层

| 路径 | 作用 |
|---|---|
| `components/common/` | 12 个公共组件：`ArgusMark` `DataTable` `EmptyState` `IconSpan` `KbdHint` `PageHeader` `PageLayout` `PlainTable` `SegmentedTab` `StatusDot` `TableCells` `ThemeToggle` |
| `components/ui/` | shadcn 基础组件（`Button` `Card` `Input` `Label` `Badge` `Separator`） |
| `lib/api/` | `client.ts`（fetch 封装）、`sse.ts`、`dashboard.ts`、`health.ts`、`reports.ts`、`settings.ts`、`sources.ts` |
| `lib/auth/` | `UserContext.tsx`（登录态，含 `AuthStatus` 四态） |
| `lib/notifications/` | `NotificationsContext.tsx` |
| `lib/theme/` | `ThemeContext.tsx` |
| `lib/hooks/` | `useStickToBottom.ts` |
| `lib/markdown/` | `parse.ts` |

## packages/shared/

`types/index.ts` + `schemas/index.ts`（Pydantic 对应的 TS 类型）。目前实际使用很少。

---

## 维护约定

1. **先 `find` → diff 本文 → 再更新，禁止主观臆断**
2. 不修改 `prd/` 下的设计文档
3. 每个目录 1-2 行说明，区块 ≤30 行
4. 顶部「最后更新：」时间戳每次刷新
5. 状态标注区分三档：**✅ 已接真接口** / **⚠️ 部分残留** / **❌ 仍 mock**
