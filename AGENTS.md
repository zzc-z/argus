# AGENTS.md — Argus 项目 AI Agent 协作指南

> 适用于在 argus 项目上工作的所有 AI 编程助手（Claude Code / Cursor / Cline 等）。

## 1. 项目快速画像

- **项目**：Argus — 多智能体深度研报平台
- **栈**：pnpm + Turborepo（monorepo）+ Next.js 16.3.7 + React 19.3 + Tailwind v3.4.19 + shadcn/ui（new-york 风格）+ Geist / GeistSans 字体 + Material Symbols Outlined
- **后端（W2 启动）**：Python 3.12 + uv + FastAPI + LangGraph + Supabase + pgvector
- **设计 token**：47 个 color + 11 个 fontFamily + 11 个 fontSize（precision_technical_light 集）
- **代码图谱**：CodeGraph（`@colbymchenry/codegraph`，项目级 MCP server；索引 140 文件 / 1153 节点 / 2296 边；agent 优先用 `mcp__codegraph__codegraph_explore` 而不是 grep/find）

## 2. 项目结构

```
argus/
├── apps/
│   ├── web/                # Next.js 前端
│   │   ├── app/           # App Router
│   │   ├── components/
│   │   │   └── ui/        # shadcn CLI 装包自动生成（`pnpm dlx shadcn@latest add ...`）
│   │   ├── lib/
│   │   │   └── utils.ts   # shadcn CLI init 自动生成（cn = twMerge(clsx(...))）
│   │   └── ...
│   └── api/               # FastAPI 后端（W2 启动）
├── packages/
│   └── shared/            # 前后端共享类型
├── prd/                   # PRD 13 份文档（只读）
└── docs/
    ├── STRUCTURE.md       # 项目结构
    ├── CONVENTIONS.md     # 代码规范（命名 / 嵌套 / 状态 / a11y / 性能）
    └── CODE-QUALITY.md    # 前后端代码质量控制（工具链 + 自动化拦截）
```

## 6. 项目硬配置（Hard Gate）

**禁止 commit 不合规代码**。三层硬拦截：

1. **Pre-commit hook**（`.husky/pre-commit`）—— 跑 `lint-staged`（仅 staged 文件）+ `tsc --noEmit`
2. **Commit-msg hook**（`.husky/commit-msg`）—— 跑 `commitlint` 验 Conventional Commits
3. **CI**（未来加 GitHub Actions）—— 跑完整 `lint + typecheck + test`

**Conventional Commits 11 个 type**：
`feat / fix / perf / refactor / style / test / build / chore / ci / docs / revert`

**Argus scope 自动发现**（commitlint-plugin-workspace-scopes）：
`apps/web / apps/api / packages / docs / prd / root` —— 必须在 commit 行写明

## 7. 项目命令速查

```bash
# 仓库根
pnpm install                              # 装所有依赖
pnpm --filter web dev                     # 启动 web
pnpm --filter web build                   # 构建 web
pnpm --filter web lint                    # 跑 lint
pnpm --filter web lint:fix                # 自动修复
pnpm --filter web format                  # prettier 格式化
pnpm --filter web format:check            # 验格式化
pnpm --filter web tsc --noEmit            # 类型检查

# 前端 husky
pnpm --filter web prepare                 # 安装 git hooks

# 前端 shadcn
pnpm --filter web dlx shadcn@latest init  # 初始化（自动建 components.json + lib/utils.ts）
pnpm --filter web dlx shadcn@latest add button card input label  # 装组件

# 后端（W2 启用）
cd apps/api
uv sync                                   # 装 Python 依赖
uv run ruff check .                       # 验 ruff 规则
uv run ruff format --check .              # 验 format
uv run mypy --strict .                    # 验类型
uv run pytest -m smoke                    # 跑烟测
uv run pre-commit install                 # 装 pre-commit hooks
```

## 7.5 开发收尾流程（强制，2026-10-13 立）

**每写完一批代码，必须依次走「质量门 → 测试 → CR」，缺一不可。**

### 什么算「一批」

由 Claude 按工作量自行划定，判据是**改动可以独立验证**。默认粒度：

| 场景 | 一批 = |
|---|---|
| 单个功能 / 单个 commit 的功能 | 该功能的全部改动 |
| 一个 sprint day | 一天的工作量 |
| 一份 plan | plan 的一个阶段 |

**不拆批的情况**：单批改动 ≤3 个文件，或只是纯文档/注释/配置调整——直接走质量门即可，不必起 CR。

**必须拆批的情况**：改动跨越质量门之外的东西（schema、migration、鉴权、并发控制、事务边界）。

### 三步流程

```bash
# 1. 质量门（apps/api）
uv run ruff check app/ tests/ alembic/
uv run mypy app/

# 前端
pnpm --filter web lint && pnpm --filter web tsc --noEmit

# 2. 测试
uv run pytest tests/ -q --no-header -p no:cacheprovider
```

两步都过 → 起 CR 审查（`reviewer-fresh` 代理，独立上下文只读审查）。

CR 发现问题时：**修完重跑质量门 + 测试**，再复审一轮。CR 没发现严重/重要级问题才算这一批结束。

### 为什么 CR 不省

Claude 自己改完的代码，自己检查等于用同一套假设验同一套假设——盲区完全重合。CR 用独立上下文重读 diff，能发现「删一行会不会报错」这类自检答案的盲区。

**实证（2026-10-13，W2 Day 11）**：CR 报出 2 个严重 + 6 个重要问题，其中两个是我「以为验证过了」的：

1. **绕过 `dependency_overrides`**——我自己开的 session 让测试静悄悄地连上开发库 `argus.db`，而 conftest 的首要约定就是测试绝不碰开发库。症状是「测试全绿」，没有任何报错。
2. **读错 FastAPI 源码**——我看到 `function_stack` 在 `await response(...)` 之前出栈，就断定「依赖提前关闭」，于是自己开 session 并写了段 docstring 论证设计合理性。**而那个前提是错的**：`Depends()` 默认 `scope="request"`，依赖挂的是**外层** stack，要等响应发完才关。FastAPI 0.118.0 专门把这个行为 revert 过。

第 2 条尤其说明问题：**读源码看到「某个 stack 在某行之前出栈」就下结论，是把「内层 stack 早关」和「依赖挂在内层」混成了一件事**。改这类东西之前先写个 10 行的 TestClient 实测脚本验一遍，比读源码推断可靠。

本项目已用变异测试验证过测试的有效性（故意改坏代码，测试是否会失败）：

| 变异 | 失败数 | 说明 |
|---|---|---|
| 引用编号不续编 | 10 | 只有测试能守住这类不变量 |
| 去掉私域过滤 | 5 | 数据泄露防线 |
| 证据块截断为 excerpt | 1 | — |

**自检三连（CR 之前必做）**：

1. 删掉一个未引用的 import / 走不到的 if 分支 / 三元死分支
2. 「这里删一行会报错吗？不能 → 删得还不够」
3. 同时存在的新旧两条路径 → 先删旧的
4. **改动依赖外部行为时（框架版本、数据库语义、第三方 API），写实测脚本验一遍，别只读源码**

## 8. 设计 token 使用

完整 token 速查表见 [apps/web/CONTRIBUTING.md § 设计 token](./apps/web/CONTRIBUTING.md)。

**关键速记**：

- 颜色：`bg-surface-container / bg-primary / text-on-surface / text-primary / bg-error-container`
- 字体：`font-headline-xl / font-body-md / font-code`
- 字号：`text-headline-xl / text-body-sm / text-code`
- 圆角：`rounded-lg`（默认）/ `rounded-full`（圆形按钮）
- 阴影：`shadow-sm`（卡片默认）

## 10. 协作约定

- 每个新文件必须满足：函数 ≤50 行 / 文件 ≤800 行 / 嵌套 ≤4 层 / 不可变 mutation / 命名一致
- 提交前自检：删除走不到的 if 分支、未引用的 import、同时存在的旧路径
- Token 预算：单任务 ≤4k，会话 ≤30k；接近红线主动总结
- **调研不超过 5 个回合**——超过就停下来问用户
- **shadcn/ui 组件**通过 `pnpm dlx shadcn@latest add button card ...` 装包到 `apps/web/components/ui/`——所有新功能优先用这些组件，不要重新发明

## 11. 文档自动更新机制

**触发场景**：当以下情况之一发生时，**必须**同步更新相关文档：

1. **新增 / 删除 / 重命名文件或目录** → 更新 `docs/STRUCTURE.md` + `AGENTS.md §2 项目结构` + `apps/{web,api}/CONTRIBUTING.md §目录结构`
2. **新增 / 修改 / 删除依赖包** → 更新 `package.json` / `apps/api/pyproject.toml` + `AGENTS.md §1 项目快速画像`
3. **新增 / 修改 / 删除 shadcn/ui 组件** → 更新 `AGENTS.md §10` + `apps/web/CONTRIBUTING.md § shadcn/ui 用法`
4. **新增 / 修改 / 删除后端配置**（ruff / mypy / pre-commit）→ 更新 `apps/api/CONTRIBUTING.md` + `docs/CODE-QUALITY.md §3 后端`
5. **修改 git hooks / husky 配置** → 更新 `docs/CODE-QUALITY.md §2 前端` + `AGENTS.md §6 硬配置`
6. **修改设计 token（Tailwind config）** → 更新 `apps/web/CONTRIBUTING.md § 设计 token` + `AGENTS.md §8`
7. **修改 commit message 规范** → 更新 `docs/CODE-QUALITY.md §4 commit` + `AGENTS.md §6 Conventional Commits`

**检查清单**（提交前自检）：

- [ ] `git status` 看了所有变更文件
- [ ] 列出了每个变更文件**影响的文档**（按上表映射）
- [ ] 对应文档已 Read → Edit / Write 更新
- [ ] 自检：文档内容与代码现状一致（路径、版本号、章节、§硬配置）
- [ ] `git diff -- <doc>` 跑一次确认改动合理

**反向引用约定**：每个特殊配置文件（如 `.ruff.toml`）的"作用"说明**出现在各子项目 `CONTRIBUTING.md`**，**不在 `AGENTS.md`**——`AGENTS.md` 只列出章节标题 + 链接。

## 12. 特殊配置文件作用

详见：

- [`apps/web/CONTRIBUTING.md §14`](./apps/web/CONTRIBUTING.md) — 前端 9 个配置文件作用
- [`apps/api/CONTRIBUTING.md §12`](./apps/api/CONTRIBUTING.md) — 后端 6 个配置文件作用

## 链接

- [CLAUDE.md 根配置](../../CLAUDE.md)

## 13. 图标来源规则（design 一致性）

1. **图标源**：Google 字体 `Material Symbols Outlined`（已在 `app/layout.tsx` L29 引入，0 新依赖）。
2. **优先用 design/code.html 里的**——每个 icon name 必须能在 `argus设计稿/argus_*/code.html` 找到，不允许自己写 SVG / 字符 emoji / lucide-react icon 替代。
3. **用法**：
   ```tsx
   <span className="material-symbols-outlined text-[16px] leading-none">
     icon_name
   </span>
   ```
4. **size 档位**：`text-[13px]` `text-[14px]` `text-[15px]` `text-[16px]` `text-[18px]` `text-[20px]` `text-[22px]` —— 大厂主流 5 档。
5. **禁止**：自定义 SVG icon / emoji / lucide-react / react-icons（与 precision_technical_light token 不兼容）。

---

## 14. 设计稿还原工作流（html → React）

**触发场景**：还原 `argus设计稿/argus_*/code.html` 到 React 组件（登录页 / dashboard / 设置页等任意页面）。

**核心原则**：把 design code.html 当成**视觉契约**——布局 / 文案 / 颜色 / 间距 / 字号 / icon 都要 1:1 对齐；但**实现方式用 Next.js + Tailwind build-time**，不是 design 的 CDN tailwindcss。

### 流程（4 步）

1. **定位设计稿**：`argus设计稿/argus_*/code.html`（每个 `argus_*` 子目录对应一个页面 / 状态变体）。
   - 找法：`title` / `<h1>` / 唯一关键词（"登录" / "Dashboard" 等）匹配到具体子目录。
   - 验证：`code.html` + `screen.png` + `code.html` 末尾 `<script>` 三件套齐全才算完整设计稿。

2. **读 code.html 全量**：用 Read 工具分批读（90-130 行 / 批），避免单次 Read 爆 context。
   - 不要用 python regex 抽——HTML 结构复杂，regex 容易挂；直接 Read + grep 关键 token 即可。

3. **写 React 组件**：
   - **token**：用 `tailwind.config.ts` 的 47 color + 9 fontFamily，不要复制 design 的 inline `tailwind.config` JS。
   - **shadcn 组件**：复用 `apps/web/components/ui/{button,card,input,label}`（已重写干净，0 oklch 残留）。
   - **暗色硬编码**（`#0e1017` / `#16191f` 等）：保留 inline `style={{ background: "#0e1017" }}`（W1 spec "must stay inline"）。
   - **placeholder / 文案**：必须 1:1 对齐 design（`name@company.com` / `acme-corp` / `.argus.internal` 等）。
   - **icon**：用 `<span className="material-symbols-outlined">{icon_name}</span>`（参见 §13）。

4. **人工验证**：代码改完即返回，**统一人工浏览器目测**（不走 playwright / curl / screenshot / console 检查 / lint / tsc）。设计稿还原流程以用户的浏览器判断为唯一标准。

### 反模式（不要做）

- 复制 design 的 `<script src="cdn.tailwindcss.com">` → Next.js 用 build-time tailwind，不支持 CDN 模式
- 用 design 的 inline `tailwind.config = {...}` → 47 token 已在 `tailwind.config.ts`，不要重复定义
- 用 `bg-oklch(...)` 等任意值类名 → Tailwind v3 不解析，必须用 47 token
- 跳过 placeholder / 文案 1:1 对齐 → user 会立刻发现"和设计稿不一样"
- 改后自己起 playwright / curl / screenshot 验证 → 项目统一人工验证，agent 不要自动跑

### 已知差异处理表

| design 用                                   | Next.js 改用                                    | 原因                                         |
| ------------------------------------------- | ----------------------------------------------- | -------------------------------------------- |
| `bg-[#16191f]`                              | `bg-[#16191f]` 或 `bg-on-surface`               | inline 颜色允许；或用 token                  |
| `font-family: Geist` (CDN)                  | `font-headline-md` 等                           | tailwind.config.ts 已映射                    |
| `font-mono`                                 | `font-code`                                     | 47 token 的 fontFamily 命名                  |
| `<details open>` 折叠                       | React `useState` + `cn(..., !open && "hidden")` | 设计稿用 vanilla JS，React 用 state          |
| vanilla `keydown` 监听器                    | `useEffect` + `window.addEventListener`         | 同上                                         |
| `document.getElementById(...)` 直接操作 DOM | 保留——快捷键反馈是合法的 DOM 操作场景           | keydown listener 200ms add/remove class 反馈 |

---

## 16. 组件开发规范与设计还原

### 16.1 文件夹形式封装组件（强制）

每个组件一个文件夹，**PascalCase**（B 必须大写：`Button.tsx` 不是 `button.tsx`），文件夹内固定两文件：

- `index.tsx`（组件实现）
- `index.module.less`（Less 模块样式并且样式代码嵌套编写方式）

按用途分三类落位：

| 类型                   | 路径                                                       | 示例                                 |
| ---------------------- | ---------------------------------------------------------- | ------------------------------------ |
| 公共组件（跨页复用）   | `apps/web/components/common/<Name>/`                       | `common/ArgusMark/`                  |
| 页面组件（仅本页面用） | `apps/web/app/(auth)/<page>/components/<Name>/`            | `(auth)/login/components/LoginForm/` |
| shadcn UI              | `apps/web/components/ui/<Name>.tsx`（**单文件，无 less**） | `ui/Button.tsx`                      |

### 16.2 CSS Modules 样式策略

- **项目用 `.module.css` 而非 `.module.less`**（Next.js 15 改用方案，2026-09-22 落地）
- 原因：Next.js 15 不内置 .module.less（Vercel 官方支持矩阵：Less 标 "Planned via plugins / Not yet supported by default"），手动配 `less-loader` + `css-loader` + fix-loader 仍存在 css 文本丢失、className 注入等问题；改用 `.module.css` 是 next 内置方案，零配置
- 文件命名：`index.module.css`（与原 `.module.less` 同位置，命名仅改扩展名）
- 写法：纯 CSS 标准语法（**不支持** Less 的 `&` 父选择器嵌套；嵌套规则必须展开为完整 css selector）
- 颜色统一用 CSS 变量 `var(--token-xxx, #fallback)`，fallback 取 `tailwind.config.ts` 的 47 token 原色
- `globals.css` 只放全局 token（@font-face / Material Symbols base / .tech-grid-pattern / .tech-dot-pattern），**不放任何组件样式**
- 全局类型声明见 `apps/web/globals.d.ts`：`declare module "*.module.css"` 用 `export default classes`
- 组件 import：`import styles from "./X.module.css"`（默认导入，next 内置 css-loader 自动支持）
- `apps/web/next.config.js` 无需任何 webpack rule，base 版本即可
- 历史背景：2026-09-21/22 一天内从 `.module.less` 路径迁到 `.module.css`，迁移期间删除 less-loader / css-loader / fix-loader 等附加依赖

### 16.3 shadcn 优先（§10 固化）

- 新功能优先用 `apps/web/components/ui/{Button, Card, Input, Label, Badge, Separator}`
- 不要重新发明已有 shadcn 组件
- shadcn 默认 OKLCH 配色 → 必须在 `components.json` 设 `baseColor: "custom"` + `cssVariables: true`，替换为项目 47 token

### 16.4 图标规则（§13 固化）

- 唯一来源：Google `Material Symbols Outlined`，走 CDN `<link>`（在 `app/layout.tsx` 合并引入）
- 唯一封装组件：`components/common/IconSpan`
- **强制 inline `style={{ fontSize }}`** —— Tailwind v3 的 `text-[Npx]` arbitrary value 在 route group 路径下不可靠
- size 档位：`13 / 14 / 15 / 16 / 18 / 20 / 22 / 24` 像素
- 禁止：自定义 SVG / emoji / lucide-react / react-icons

### 16.5 设计稿还原流程（§15 固化）

触发：还原 `~/Desktop/argus设计稿/argus_*/code.html` 到 React 组件。

四步走：定位 → 读 → 写 → 人工验证

1. 定位 design 文件夹下对应的 `argus_*` 子目录
2. 读 `code.html` 提取结构与样式意图（**不复制 CDN 链接与 inline tailwind.config**）
3. 写 Next.js 组件 + `.module.less`，用项目 47 token 替换颜色，shadcn 替换交互元素
4. **人工浏览器目测** —— 不起 playwright / curl / screenshot / console 检查 / lint / tsc

设计稿源文件 **不保存在仓内**（`design-argus-3.html` / `design_argus_3_code.html` 已删）。

### 16.6 主题色（dual theme）

- 项目支持亮色 + 深色两主题
- `argus_2` 是深色（`<html class="dark">`），`argus_1` / `argus_3` / `argus_dashboard` 等为亮色
- 缺失的对应主题可在 design 模式二次设计补全
- 当前登录页（`argus_3`）只实现亮色 Material 3 风

### 16.7 反模式（追加）

- ❌ 复制 design 的 `<script src="cdn.tailwindcss.com">`
- ❌ 复制 design 的 inline `tailwind.config = {...}`
- ❌ 改用 `bg-oklch(...)` → 与 47 token 不兼容
- ❌ `material-symbols-outlined` 只用 `text-[Npx]` className，没有 inline `style={{ fontSize }}` → 落回 24px
- ❌ 改多处重复 className 时不先 grep 计数 → 用 `replace_all: true` 或更具体上下文
- ❌ 压扁 template-string `<span className={\`...\`}>` 成单行 → JSX 闭合错乱，build error
- ❌ 自己起 playwright / curl / screenshot **验证设计稿还原程度** → 那是人类美学判断
- 🔧 修复运行 bug 时 agent 可以用浏览器 MCP（chrome-devtools / playwright）介入——抓 console error、看页面渲染异常、对照 network panel 排查请求失败
- ❌ 把 shadcn 组件文件名改成小写（`button.tsx`）→ PascalCase 强制
- ❌ 预防性地包 `useCallback` / `useMemo` → 见 §16.8「Hook 使用规则」

### 16.8 Hook 使用规则：useCallback / useMemo（2026-10-10 立）

**现状**：React 19.3 + **React Compiler 未启用**，全项目 `React.memo` 0 处。
这两条决定了本节规则。

#### 判断标准（满足任一条才准用）

| 场景 | 准用 | 说明 |
|---|---|---|
| 函数传给 `React.memo` 子组件 | ✅ | useCallback 唯一无可替代的用途 |
| 函数是 `useEffect` / `useMemo` 的依赖，且闭包里有 state/props | ✅ | 否则 effect 每次渲染都重跑 |
| 函数传给 `memo()` 的第三方组件 | ✅ | 同上 |
| **单纯「怕子组件重渲染」但子组件没 memo** | ❌ | 没 memo 就没有重渲染可省，纯粹白包 |
| **空函数 `useCallback(() => {}, [])`** | ❌ | 零收益，纯噪音 |
| **函数体内没读任何响应式值，deps 却写满** | ❌ | 本来就不会变，不用包 |
| **「以防万一」预包** | ❌ | YAGNI。有性能问题再包不迟 |

#### 规则

1. **默认不写 `useCallback` / `useMemo`**，需要时再加
2. 包之前先回答：这个函数被 `memo` 组件消费，或被 `useEffect` 当依赖吗？两个都不是 → 别包
3. 一旦用了，**依赖数组必须诚实**——闭包里读了什么就写什么，禁止为了「少写几个」删依赖
4. 禁止空包裹：`useCallback(() => {}, [])` 一律删掉
5. 禁止用 `useCallback` 代替 `useRef` 存「只想读不想触发重渲染」的值——那是 `useRef` 的活

#### 依赖数组删错的修法

依赖警告不要靠 `eslint-disable` 消掉。正确顺序：

```
1. 把函数体里用到的 props/state 解构成局部变量 → 依赖写局部变量（不是整个 props 对象）
2. 确实要保持引用稳定 → useCallback
3. 实在绕不开 → 写 disable 注释并附一句为什么（不能只写 disable）
```

```tsx
// ❌ 依赖整个 props，对象每次渲染都是新的 → 白包
const handleSubmit = useCallback(() => props.onSubmit(emails), [emails, props])

// ✅ 解构出用到的那个函数，依赖精确
const { onSubmit } = props
const handleSubmit = useCallback(() => onSubmit(emails), [emails, onSubmit])
```

#### 机器强制（eslint.config.mjs）

规则光写文档会烂。`apps/web/eslint.config.mjs` 已配好 `react-hooks/exhaustive-deps: error`，
`npm run lint` 会真实拦截。**改动后必须跑一遍。**

配置踩过的坑，别重复踩：

| 坑 | 症状 | 正确做法 |
|---|---|---|
| 用 `next lint` | Next 16 已废弃该命令，它把 `lint` 当目录名 → lint 从未真正跑过 | 用 `eslint` CLI 直接跑 |
| 用 ESLint 内置 `no-unused-vars` | 不认 TS 语法，误报 84 处，信号全淹 | 必须配 `typescript-eslint`，并关掉内置那两条 |
| `eslint .` | 在 pnpm workspace 里 `.` 解析到仓库根，把 `apps/api/.venv` 的第三方 JS 全扫进来（7 万条噪音） | 显式写目录：`eslint app components lib` |
| ignores 不独立成块 | `.next/` 构建产物被扫进去 | ignore 必须是数组首个、只含 `ignores` 键的对象 |

#### React Compiler 一旦启用，本节作废

Compiler 会自动做记忆化，届时 `useCallback` / `useMemo` 大部分不再需要。
启用 Compiler 的同时必须回改本节，否则规则会误导。

#### 当前债务（2026-10-10 盘点）

`useCallback` 59 处，其中 `settings/page.tsx` 12 处、`explore/page.tsx` 6 处、
`notifications/page.tsx` 5 处 大多属「预防性包裹」。
**不要一次性全改**——逐个文件碰到时顺手清理，改一处测一处。

lint 首次跑通后暴露的**真实 bug**（依赖缺失，闭包读到过期值）：

| 位置 | 问题 |
|---|---|
| `topics/components/TopicTable/index.tsx:156` | `useMemo` 缺 `toggleSelectAll` |
| `components/common/DataTable/index.tsx:31` | `useEffect` 缺 `sel` |
| `components/common/PlainTable/index.tsx:30` | `useEffect` 缺 `selection` |

另有 4 处 `react-hooks/set-state-in-effect`（ThemeContext / ThemeToggle 等在 effect 里
同步 setState）——这个先不动，属于架构问题，改动面大，等单独排期。

---
---

- [apps/web/CONTRIBUTING.md](./apps/web/CONTRIBUTING.md)
- [apps/api/CONTRIBUTING.md](./apps/api/CONTRIBUTING.md)
- [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)
- [docs/CODE-QUALITY.md](./docs/CODE-QUALITY.md)
- [prd/PRD 总览](./prd/README.md)
