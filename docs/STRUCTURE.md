# Argus 项目结构

> 最后更新：2026-10-19（Word 支持 + add-sources 修复落地）
> ⚠️ 2026-09 之前本文档描述的是**实施计划**（大量 "W1/W2 待写"），实际早已实现。
> 现已按磁盘现状重写。

## 顶层

```
argus/
├── prd/                  # 13 份 W0 设计文档
├── apps/
│   ├── api/              # FastAPI 后端（uv）
│   └── web/              # Next.js 16 前端（pnpm）
├── packages/shared/      # 前后端共享 TS 类型
├── docs/                 # 项目文档
├── AGENTS.md             # agent 入口约定
├── package.json          # 根 monorepo（pnpm workspace + turbo）
├── pnpm-workspace.yaml
├── turbo.json
└── tsconfig.base.json
```

> `infra/` 与 `scripts/` 在计划里出现过，**实际不存在**。数据库是 SQLite
> （`apps/api/argus.db`），无 postgres / redis / nginx。

## apps/api/ — FastAPI 后端

`app/` 下只有 4 个包：

| 路径 | 作用 |
|---|---|
| `app/gateway/` | HTTP 路由。`auth` / `sources` / `reports` / `research` / `users` / `health` / `deps`（鉴权依赖） |
| `app/services/` | 业务逻辑。`parser`（PDF/HTML/TXT/DOCX 解析）、`ingest`（摄取管线）、`chunker`、`embedder`、`retriever`、`vectorstore`、`bm25`、`fetcher`、`citation`、`faithfulness`（Critic 引用校验）、`agent`（LangGraph）、`llm`、`stream`（SSE 编码）、`storage`、`auth`、`token`（JWT）、`tools` |
| `app/models/` | SQLAlchemy ORM。`user` / `source` / `report` |
| `app/schemas/` | Pydantic 出入参。**改 API 前必读**（前端 `SourceV` 等类型与之对应） |

| 其他 | 作用 |
|---|---|
| `alembic/` `alembic.ini` | DB 迁移。**改了 `app/models/` 必须生成迁移** |
| `tests/` | pytest，30 个文件 |
| `scripts/dev_login.py` | 本地造 session（绕过 GitHub OAuth） |
| `argus.db` | SQLite 数据库文件 |
| `WORKLOG.md` | **后端开发日志，顶部优先** —— 恢复上下文先读它 |

## apps/web/ — Next.js 16 前端

### 路由组

| 路径 | 作用 |
|---|---|
| `app/(auth)/login/` | OAuth 登录页 |
| `app/(dashboard)/` | 主应用（`layout.tsx` = 侧边栏 + 顶栏 + `AuthGuard`） |
| `app/(error)/` | 500 错误页 |

### (dashboard) 页面

| 路径 | 后端状态 |
|---|---|
| `add-sources/` | ✅ 已接真接口（上传 / URL 建源 / 摄取队列轮询） |
| `sources/` | ✅ 已接真接口 |
| `explore/` | ⚠️ 仍有残留 mock（`explore/mock.ts`） |
| `dashboard/` `topics/` `reports/` `report/[id]/` `notifications/` `settings/` | ❌ 仍用 mock（后端无对应端点） |
| `components/` | `AuthGuard`（登录守卫）、`UserMenu`（顶栏用户菜单）、`QuickKeys`、`NavLink` |
| `error-404/` | 静态 404 页 |

### 共享层

| 路径 | 作用 |
|---|---|
| `components/common/` | `PageLayout` `PageHeader` `DataTable` `PlainTable` `TableCells/` `EmptyState` `IconSpan` `SegmentedTab` `StatusDot` `ThemeToggle` `ArgusMark` |
| `components/ui/` | shadcn 基础组件 |
| `lib/api/` | `client.ts`（fetch 封装 + SSE）、`sources.ts`（资料 API + 模块级 chunk 缓存） |
| `lib/auth/` | `UserContext.tsx`（登录态，含 `AuthStatus` 四态） |
| `lib/notifications/` `lib/theme/` | 通知中心 / 主题 |

## packages/shared/

`types/index.ts` + `schemas/index.ts`（Pydantic 对应的 TS 类型）。目前实际使用很少。

---

## 维护约定

1. **先 `find` → diff 本文 → 再更新，禁止主观臆断**
2. 不修改 `prd/` 下的设计文档
3. 每个目录 1-2 行说明，区块 ≤30 行
4. 顶部「最后更新：」时间戳每次刷新
5. 状态标注区分三档：**✅ 已接真接口** / **⚠️ 部分残留** / **❌ 仍 mock**
