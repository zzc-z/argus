# Argus · AI Code Review Guide

> 本文件是 **`/code-review` 审查 argus 改动时的规则依据**。
> 规则写成可判定的形式——审查 agent 需要能**引用原文**并说明违反哪条，
> 所以每条都带编号与明确的判据，不写散文。
>
> 跨项目通用规则见全局 `~/.claude/CLAUDE.md` §5（补偿路径、竞态令牌、
> React 渲染期引用、模块级状态跨用户等），本文件只写 argus 特有的。

## 0. 规则加载指令（先读这段）

审查规则分四层。**改哪层就读哪层**——官方 CR 只自动读 CLAUDE.md 体系，
其余要显式读。

| 层 | 位置 | 何时读 |
|---|---|---|
| 通用口径 | 全局 `~/.claude/CLAUDE.md` §5 | 每次审查（补偿路径、举证要求、严重度锚点、Nit 上限、噪音过滤、What NOT to Flag） |
| 语言专项 | 全局 `~/.claude/rules/cr-python.md` / `cr-typescript.md` / `cr-react.md` | 审对应语言的代码时 |
| 项目专项 | 本仓库 `.claude/rules/api.md` / `web.md` | 审 `apps/api/**` / `apps/web/**` 时（错误分类、补偿四态、组件形式、shadcn 等） |
| 本文件 | 根 `CLAUDE.md` | 项目画像、跨模块语义一致性、静默失败、文档断言 |

**审 `apps/api/**`（`.py`）改动前，完整读这两份**：
`~/.claude/rules/cr-python.md` → `.claude/rules/api.md`。
**审 `apps/web/**`（`.tsx` / `.ts`）改动前，完整读这两份**：
`~/.claude/rules/cr-react.md`（`.tsx`）+ `~/.claude/rules/cr-typescript.md`（`.ts`）
→ `.claude/rules/web.md`。

（带 `paths` frontmatter 的文件，Claude Code 会在触碰匹配文件时自动加载；
显式读一遍是保险——官方 CR 的子代理是否触发条件加载不做保证。）

## 1. 项目是什么

多智能体深度研报平台。后端 FastAPI + SQLAlchemy (async) + SQLite/sqlite-vec，
前端 Next.js 16 + React 19 + TypeScript + Tailwind v3 + shadcn/ui。

**审查时不要假设的技术栈**（本项目实际**没有**用）：

| 常见误判 | 本项目实际 |
|---|---|
| LangGraph 状态机 | **没有**。agent 编排是**手写**的（`app/services/agent_nodes.py`） |
| LangChain agent | **没有**。只用 `langchain_text_splitters` 切文本 |
| pgvector / Postgres | **没有**。向量存储是 **sqlite-vec**（`app/services/vectorstore.py`） |
| Cohere Rerank | **没有**。重排是自己实现的 |
| Mem0 长期记忆 | **没有** |
| Redis | **只有配置项**，无实装（`config.py` 的 `redis_url`） |
| Zustand / SWR / React Query | **没装**，import 会构建失败 |

审查里出现「这里应该用 X」而 X 在本项目不存在 → 是噪音，不报。

## 2. 跨模块语义一致性（**最该报的一类**）

**声称解决了某个问题，但实现只覆盖了一部分**——这是本项目 CR 历史上
最常见、也最贵的 bug 类型。逐条核对，不要只看改动的那几行。

> 通用判据见全局 `~/.claude/CLAUDE.md` §5.1–§5.3（补偿覆盖全部状态 /
> 补偿在唯一有意义的场景下执行 / 修复引入的新前提）。本节只补
> argus 特有的。

- **argus 的一次摄取写四处状态**：正文行 / FTS 虚表 / 向量虚表 /
  `sources.chunk_count`。补偿必须四处都清——漏 `chunk_count` 时
  用户看到「失败」却配着「21 块」。
- **调用方与被改函数的签名要一致**：改了返回值结构、错误码、字段名，
  所有调用方（含前端）都要跟着改。
- **对外字段是契约**：`SourceResponse.chunk_count` 这类字段被前端直接读，
  改了语义就是破坏契约。

## 3. 静默失败（**第二该报的一类**）

> 通用判据见全局 `~/.claude/CLAUDE.md` §5.2 与
> `~/.claude/rules/cr-python.md` P2 / `cr-typescript.md` T1
> （不吞取消信号、吞异常后返回默认值）。本节只补 argus 特有的。

- **catch 块吞掉本该冒泡的异常**——记了日志或返回默认值，但调用方以为成功。
- **fallback 掩盖真因**——降级到默认值，用户和调用方都看不出出过问题。
- **argus 特有**：`error_event_for` 的错误分档按 `error.type` 而非
  字符串关键词匹配——按关键词会在上游改措辞时失效。

## 4. 文档与注释：写下 ≠ 核实过

**注释里的技术断言，要么实测过，要么不写。**

- 一个**错误的技术断言**留在文档里比没有文档更危险——它不是描述现状，
  是**指示操作**。照着错的指引做会损坏生产数据。
- 断言框架行为时，**去框架源码确认**，不要凭记忆。
  （例：SQLAlchemy 的 `SessionTransaction.rollback` 的 `declare_states`
  **接受** DEACTIVE 状态，rollback 本身不抛 `PendingRollbackError`；
  抛错的是 `commit`/`flush`/`execute`。）
- 改了行为要同步改 docstring 与 commit message——**实测的结论必须覆盖到文档里**。

## 5. 不要报什么（argus 特有）

通用边界见全局 `~/.claude/CLAUDE.md` §5.9（既有问题、lint 能抓到的、
注释命名格式、需要跑代码才能确认的、严重度按后果定）。

以下是 **argus 特有的噪音源**：

- **「本项目应该用某个更流行的库」**——见 §1，本项目的技术选型是刻意的
- **纯文档改动、纯格式化**
- 前端 lint 抓得到的（组件文件夹形式、依赖数组、a11y 基础项）→ 不报

## 6. 审查时的项目事实

- **测试用内存 SQLite**（`tests/conftest.py` 的 `db_session`），
  **绝不碰开发库** `apps/api/argus.db`。
- **CI 需要几个环境变量存在，但不需要真值**：
  `ANTHROPIC_API_KEY` / `JWT_SECRET_KEY`（≥32 字节，否则 PyJWT 报长度告警）/
  `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` /
  `GITHUB_OAUTH_CALLBACK_URL`（**必须带 `/api/v1` 前缀**）/
  `COOKIE_SECURE=false`（默认 True，CI 走 http 时 Secure cookie 不会被送回）。
- 改 `app/models/*.py` 之后要 `alembic revision --autogenerate` + `upgrade head`。
- **前端 lint 真的会跑**：`eslint app components lib`，配置在 `apps/web/eslint.config.mjs`。
  （`next lint` 在 Next 16 已废弃，项目用的是 flat config 的 `eslint`。）

## 7. 与 AGENTS.md 的分工

`AGENTS.md` 是**人类开发规范**，官方 CR 读不到它——仓库同时存在
`AGENTS.md` 和 `CLAUDE.md` 时，Claude Code 默认**只读 `CLAUDE.md`**。

**所以：CR 规则一律写在本文件与 `.claude/rules/` 下。**
`AGENTS.md` 里若出现与本文件冲突的 CR 相关内容，以本文件为准。

| 文件 | 用途 |
|---|---|
| `AGENTS.md` | 完整项目规范（人类阅读，26KB，不在审查时加载） |
| `CLAUDE.md`（本文件） | argus 审查规则：项目画像 + 跨模块语义 + 静默失败 + 文档断言 |
| `.claude/rules/api.md` | argus 后端专项审查规则 |
| `.claude/rules/web.md` | argus 前端专项审查规则 |
| 全局 `~/.claude/CLAUDE.md` §5 | 跨项目通用审查口径（举证要求、严重度、Nit 上限、边界） |
| 全局 `~/.claude/rules/cr-*.md` | 语言专项审查规则 |
| `apps/api/CONTRIBUTING.md` | 后端贡献指南（人类阅读） |
| `apps/web/CONTRIBUTING.md` | 前端贡献指南（人类阅读） |
