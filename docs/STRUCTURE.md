# Argus 项目结构

> 最后更新：2026-09-19 19:36
> 总目录：9 个 · 总文件：17 个（不含 prd/、node_modules/、.git/）

## 顶层

```
argus/
├── prd/                  # 13 份 W0 设计文档（已有）
├── apps/                 # 应用层（前后端）
├── packages/             # 共享层
├── infra/                # 基础设施配置
├── scripts/              # 一次性脚本（seed / migrate）
├── docs/                 # 项目文档（STRUCTURE.md 等）
├── package.json          # 根 monorepo 配置
├── pnpm-workspace.yaml   # workspaces 配置
├── turbo.json            # Turborepo 任务编排
└── tsconfig.base.json    # 共享 TS 配置
```

## apps/

### apps/api/ （Python 后端，FastAPI + LangGraph，uv 管）

| 路径 | 作用 | 状态 |
|---|---|---|
| `app/gateway/` | FastAPI 路由 + OAuth | W1 待写 |
| `app/agents/` | LangGraph 状态机 + 4 子 agent | W2 待写 |
| `app/rag/` | chunking / embedding / rerank | W2 待写 |
| `app/memory/` | Mem0 适配器 + 反思循环 | W2 待写 |
| `app/tools/` | 工具注册表 + schema | W2 待写 |
| `app/scheduler/` | APScheduler cron jobs | W3 待写 |
| `app/models/` | SQLAlchemy ORM | W1 待写 |
| `app/eval/` | Phoenix 客户端 + 自研指标 | W3 待写 |
| `tests/` | pytest | 后续 |

### apps/web/ （前端，Next.js 14 + React 19，pnpm 管）

| 路径 | 作用 | 状态 |
|---|---|---|
| `app/(auth)/login` | OAuth 登录页 | W1 已实现 ✅ |
| `app/(dashboard)/topics` | 主题订阅 / 管理 | W2 待写 |
| `app/(dashboard)/sources` | 上传文档 / 链接 / RSS 管理 | W2 待写 |
| `app/(dashboard)/research/[id]` | 研究会话 + 实时 agent 工作流 | W2 待写 |
| `app/(dashboard)/reports/[id]` | 多视图报告查看 | W3 待写 |
| `app/(dashboard)/notifications` | 通知中心 | W3 待写 |
| `app/layout.tsx` | 全局 layout + Geist 字体 | W1 已写 ✅ |
| `app/page.tsx` | 根路由 redirect → /login | W1 已写 ✅ |
| `app/globals.css` | Tailwind 全局样式 | W1 已写 ✅ |
| `components/ArgusLogo.tsx` | Argus Panoptes SVG | W1 已写 ✅ |
| `components/agent-flow/` | 自研 agent 时间轴（参考 LangGraph Studio） | W2 待写 |
| `components/report-views/` | 4 种视图渲染器 | W3 待写 |
| `components/ui/` | shadcn 基础组件 | W1+ 累积 |
| `lib/api/` | FastAPI 客户端 + SSE 订阅 | W2 待写 |
| `lib/auth/` | OAuth helpers | W2 待写 |
| `lib/utils/` | 通用工具 | W1+ 累积 |
| `public/` | 静态资源 | 后续 |
| `styles/` | 额外 CSS | 后续 |
| `tests/` | Playwright e2e | W3 待写 |
| `next.config.js` `tailwind.config.ts` `postcss.config.js` `tsconfig.json` `package.json` | Next.js 构建配置 | W1 已写 ✅ |

## packages/

### packages/shared/ （前后端共享类型 / prompt / 配置，pnpm 管）

| 路径 | 作用 | 状态 |
|---|---|---|
| `types/index.ts` | TypeScript 类型定义（前端 import） | W1 占位已建 |
| `schemas/index.ts` | Pydantic 对应 TS schema（前后端共享） | 后续 |
| `prompts/` | 所有 agent prompt 模板 | W2 待写 |
| `config/` | 环境变量 + 配置加载 | 后续 |
| `package.json` | workspace 包配置 | W1 已写 |

## infra/

| 路径 | 作用 |
|---|---|
| `postgres/` | init.sql / 迁移 |
| `redis/` | 配置 |
| `nginx/` | 反向代理配置 |

## scripts/

| 路径 | 作用 |
|---|---|
| `seed_demo_data.py` | 200 篇 AI / 科技演示数据采集 |

> 当前 `scripts/` 为空目录，seed 脚本 W1 待写。

---

## 用法

用户在以下场景调用本 agent：

1. **新建文件 / 目录**——「我在 apps/web/components/agent-flow/ 加了 X.tsx，更新文档」
2. **删除**——「删了 apps/web/lib/auth/，更新文档」
3. **批量改动**——「W2 启动后，全面同步结构文档」
4. **检查状态**——「现在结构长什么样」—— 读 STRUCTURE.md + find 对比

**约束**：

- 不修改 prd/ 下的设计文档
- 只同步文档，不写代码
- 每个目录 1-2 行说明，区块 ≤30 行
- 顶部「最后更新：」时间戳每次刷新
- 流程：先 `find` → diff STRUCTURE.md → 再更新，禁止主观臆断