---
name: project-conventions
description: argus 项目的编码规范、Hard Gate、设计 token 与约定。任何写代码/改代码的动作前必读。请在以下场景使用：(1) 写新组件；(2) 改 UI 样式；(3) 重构现有代码；(4) 用户提到"按规范"或"按 argus 约定"。阅读 docs/CONVENTIONS.md、docs/CODE-QUALITY.md、AGENTS.md 第 6 节、docs/STRUCTURE.md。
---

# argus project-conventions

> 写代码 / 改代码前**强制**走本 skill：先 Read 4 个 docs 文件，再下笔。

## 1. 必读清单（强制）

每次写代码 / 改代码前，用 Read 工具按顺序读：

1. `/Users/zjp/Desktop/argus/AGENTS.md` — 项目硬配置（Hard Gate §6）、命令速查、图标规则、设计 token 速记
2. `/Users/zjp/Desktop/argus/docs/CONVENTIONS.md` — 命名 / 嵌套 / 状态 / shadcn / a11y / 性能
3. `/Users/zjp/Desktop/argus/docs/CODE-QUALITY.md` — 工具链（前端 ESLint + 后端 ruff/mypy）+ commitlint
4. `/Users/zjp/Desktop/argus/docs/STRUCTURE.md` — 项目目录结构与 W 状态

读完再开工。**禁止凭印象绕过**。

## 2. 核心约束速查（Hard Gate）

### 2.1 技术栈（锁版本，禁止升级/降级）

- 包管理：pnpm + Turborepo（monorepo）
- 前端：Next.js 16.3.7 + React 19.3 + Tailwind v3.4.19
- shadcn/ui：**new-york 风格**（CLI 装包到 `apps/web/components/ui/`）
- 设计 token：50 color + 11 fontFamily + 11 fontSize（**precision_technical_light**，锁定不可改）
- 后端：Python ≥3.12 + uv + FastAPI + SQLite（`sqlite+aiosqlite`）+ sqlite-vec
  - **不是** Supabase / pgvector；`langgraph` 虽在依赖里但代码未使用
- 图标：Google `Material Symbols Outlined`（本地 woff2，唯一来源，禁止自定义 SVG / emoji / lucide / react-icons）

### 2.2 提交拦截（不可绕过）

```
git commit
  → husky/pre-commit
     ├─ 前端（总是跑）：pnpm run lint + pnpm exec tsc --noEmit
     └─ 后端（仅当 staged 含 apps/api/*）：ruff check + mypy
  → husky/commit-msg: commitlint 校验 Conventional Commits
  不通过 → commit 拒绝
```

**Conventional Commits 11 type**：`feat / fix / perf / refactor / style / test / build / chore / ci / docs / revert`

**scope 可选**——commitlint 的 `scope-enum` 规则已关闭。实际用法是 `api` / `web` / `api,web`。

header ≤ 100 字符。

### 2.3 代码硬规则（CONVENTIONS.md §1-3）

- 函数 ≤ **50 行**（不含注释/空行）
- 文件 ≤ **800 行**
- JSX 嵌套 ≤ **4 层**（超出抽子组件）
- **不可变 mutation**：`const` 优先；`let` 仅限 reducer / 计时器 / 累加器
- 命名：组件 `PascalCase.tsx` / 函数 `camelCase.ts` / 常量 `UPPER_SNAKE_CASE.ts` / 路由 `kebab-case` / 数据库表 `snake_case`
- 严禁：复制粘贴 > 3 次（DRY）、写将来才用的功能（YAGNI）、用 3 个指头能做的事用 2 个指头（KISS）

### 2.3.1 审查速查：规则 → 条款出处

审查时引用具体条款编号用这张表（全局 `reviewer-fresh` agent 审 argus 代码时
需要它定位依据）：

| # | 规则 | 出处 |
|---|---|---|
| 1 | **不可变 mutation**：禁止原地改数组/对象；spread / map / filter 返回新引用 | CONVENTIONS §3 |
| 2 | **嵌套 ≤ 4 层**：超出必须抽子组件 | CONVENTIONS §3 |
| 3 | **函数 ≤ 50 行 / 文件 ≤ 800 行** | CONVENTIONS §3 |
| 4 | **命名严格**：PascalCase=组件/类、camelCase=工具/变量、UPPER_SNAKE_CASE=常量、kebab-case=路由、snake_case=数据库表/LangGraph node | CONVENTIONS §2 |
| 5 | **设计 token 禁偏离**：禁止 `bg-[#XXX]` / `bg-oklch(...)` 任意值；必须用 `tailwind.config.ts` 的 color token | CONVENTIONS §8 |
| 6 | **a11y**：`<button>` 必有 aria-label 或可见文字；`<img>` 必有 alt；`<input>` 必关联 `<label htmlFor>`；焦点环 `focus-visible:ring-2` | CONVENTIONS §12 |
| 7 | **状态管理边界**：本地 `useState` / 跨路由 searchParams / 服务端 `fetch + useState`（项目**未装** Zustand / SWR / React Query，import 它们会构建失败） | CONVENTIONS §4 |
| 8 | **TypeScript strict**：禁止 `any`；pre-commit 跑 `tsc --noEmit` | CODE-QUALITY §2.1-2.2 |
| 9 | **错误路径必有**：async/await 必有 catch；API route 必返回错误状态；不可静默吞错 | CONVENTIONS §3 + 全局 `rules/coding.md`「大声报错」 |
| 10 | **shadcn 优先**：禁止装 MUI/Chakra/Mantine/Ant Design；禁止手改 `components/ui/` 下文件；新功能复用 shadcn 组件 | CONVENTIONS §7 |

### 2.4 设计稿还原 4 步（AGENTS.md §14）

触发：还原 `argus设计稿/argus_*/code.html` 到 React 组件

1. 定位 `argus_*/code.html`（`title` / `<h1>` / 关键词匹配）
2. Read 全量 code.html（90-130 行/批）
3. 写 Next.js 组件：用项目设计 token 替换颜色、用 shadcn 替换交互、保留暗色 inline `style={{ background: "#0e1017" }}`
4. **人工浏览器目测**（不要自己起 playwright / curl / screenshot 验设计还原度）

### 2.5 反模式（CONVENTIONS.md §7.4 + AGENTS.md §16.7）

- ❌ 直接复制 UI 库源码（必须通过 npm 装包）
- ❌ 装 MUI / Chakra / Mantine / Ant Design / daisyui
- ❌ 手动改 `apps/web/components/ui/` 下文件（shadcn CLI 是唯一 source of truth）
- ❌ 用 `bg-[#XXXXXX]` hardcode 颜色（必须用设计 token）
- ❌ 用 `bg-oklch(...)`（Tailwind v3 不解析）
- ❌ 复制 design 的 `<script src="cdn.tailwindcss.com">`（用 Next.js build-time tailwind）
- ❌ 把 shadcn 组件文件名改成小写（PascalCase 强制）
- ❌ 自己起 playwright / curl / screenshot 验证设计还原度（人类美学判断）
- ❌ 跳过 placeholder / 文案 1:1 对齐

## 3. 写代码前置 checklist

按顺序自检再下笔：

- [ ] **Read 规范**：4 个 docs 已 Read（AGENTS.md / CONVENTIONS.md / CODE-QUALITY.md / STRUCTURE.md）
- [ ] **token 一致性**：颜色用 50 个 color token、字号用 11 个、字体用 11 个 fontFamily（不用 `bg-[#...]` / `text-[Npx]` arbitrary value / `bg-oklch(...)`）
- [ ] **shadcn 优先**：交互元素（button / card / input / label / dialog 等）从 `apps/web/components/ui/` 取，不自造
- [ ] **图标来源**：Material Symbols Outlined，封装用 `components/common/IconSpan`，强制 inline `style={{ fontSize }}`（Tailwind v3 `text-[Npx]` 在 route group 路径下不可靠）
- [ ] **嵌套 ≤4 层**：JSX 嵌套超过必须抽子组件
- [ ] **状态机可推导**：本地 `useState` / 跨路由 URL params / 服务端 `fetch` + `useState`（**项目没装 Zustand / SWR / React Query / Redux / MobX——不要 import 它们**）
- [ ] **a11y 通过**：button 有 `aria-label` / img 有 `alt` / input 关联 `<label htmlFor>` / 焦点环 `focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-primary` / 对比度 ≥ 4.5:1 / 键盘导航完整
- [ ] **不可变**：mutation 禁止；spread / filter / map 返回新引用
- [ ] **组件文件夹**：`PascalCase/`（**B 必须大写**）+ `index.tsx` + `index.module.css`（**`.module.css` 不用 `.module.less`**——Next.js 15 不内置 less）
- [ ] **Commit 自检**：删除走不到的 if 分支、未引用的 import、同时存在的旧路径

## 4. 常见违规（CONVENTIONS.md 重点禁止项）

| 违规 | 后果 | 正确做法 |
|---|---|---|
| 用 `bg-[#XXXXXX]` 写颜色 | 设计 token 一致性破坏 | 用 `bg-primary` / `bg-surface-container` 等 |
| 用 `text-[Npx]` 写图标大小 | route group 下失效，落回 24px | 强制 inline `style={{ fontSize: 13 }}` 等档位（13/14/15/16/18/20/22/24） |
| 复制 design 的 inline `tailwind.config = {...}` | 设计 token 重复定义 | 用项目 `tailwind.config.ts` 已映射的 token |
| 用 `<details open>` + vanilla JS | React state 错位 | `useState` + `cn(..., !open && "hidden")` |
| 用 `document.getElementById` 操作组件内 DOM | 与 React 渲染冲突 | 保留——快捷键反馈场景合法（keydown 200ms add/remove class） |
| 复制 design 的 CDN tailwindcss 链接 | Next.js build-time 不支持 CDN | 用 Next.js 内置 tailwind |
| 把 shadcn 组件文件名改成小写 | PascalCase 强制 | `Button.tsx` 不是 `button.tsx` |
| 自己起 playwright 验设计稿还原度 | 越权（人类美学判断） | 等人工浏览器目测 |
| 改多处重复 className 不 grep 计数 | 漏改 | 先 grep 计数，用 `replace_all: true` 或更具体上下文 |
| 压扁 template-string `<span className={`...`}>` 成单行 | JSX 闭合错乱 build error | 保留多行 template |
| 用 MUI / Chakra / Mantine / Ant Design / daisyui | 与项目设计 token 不兼容 | 装 shadcn（new-york 风格）|
| import Zustand / SWR / React Query / Redux / MobX | **项目没装这些包**，import 会构建失败 | 服务端状态用 `fetch` + `useState`；真需要全局状态用 `Context API` |

## 5. 调试 / 验证策略

- **设计稿还原**：人工浏览器目测（不要自己起 playwright）
- **运行 bug**：可以用浏览器 MCP（chrome-devtools / playwright）介入——抓 console error、看页面渲染异常、对照 network panel 排查请求失败
- **类型检查**：`pnpm --filter web exec tsc --noEmit`（**必须带 `exec`**——`pnpm --filter web tsc --noEmit` 是空命令，退出码 0 但什么都没跑）
- **Lint**：`pnpm --filter web lint`
- **格式化**：`pnpm --filter web format`（`lint:fix` 与 `typecheck` script 不存在）

---

**详细规范让 Claude 自己 Read 上述 4 个 docs 文件**——本 skill 只做硬规则速查。