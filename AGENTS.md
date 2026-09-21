# AGENTS.md — Argus 项目 AI Agent 协作指南

> 本文档适配自 [ECC plugin](https://github.com/...) 的 agents / skills / commands 体系。  
> 适用于在 argus 项目上工作的所有 AI 编程助手（Claude Code / Cursor / Cline 等）。

## 1. 项目快速画像

- **项目**：Argus — 多智能体深度研报平台
- **栈**：pnpm + Turborepo（monorepo）+ Next.js 14.2.18 + React 19 + Tailwind v3.4.19 + shadcn/ui（new-york 风格）+ Geist / GeistSans 字体 + Material Symbols Outlined
- **后端（W2 启动）**：Python 3.12 + uv + FastAPI + LangGraph + Supabase + pgvector
- **设计 token**：47 个 color + 11 个 fontFamily + 11 个 fontSize（precision_technical_light 集）

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

## 3. ECC Agents 速查（按需调用）

argus 常用 ECC agents（不在 `plugins/marketplaces/ecc/.agents/skills/` 而在 `/Users/ext.zhangjianpeng11/.claude/plugins/marketplaces/ecc/.agents/skills/`）：

| Agent                  | 用途               | 何时调用                         |
| ---------------------- | ------------------ | -------------------------------- |
| `planner`              | 任务分解与依赖分析 | 大型任务（W2+ 启动）             |
| `tdd-guide`            | TDD 测试驱动       | 写新功能 / 修 bug                |
| `code-reviewer`        | 代码 review        | PR 提交前                        |
| `security-reviewer`    | 安全审查           | OAuth / API / 数据库改动         |
| `build-error-resolver` | 编译错误排查       | `pnpm tsc` / `pnpm build` 失败时 |
| `e2e-runner`           | Playwright E2E     | 端到端验证                       |
| `refactor-cleaner`     | 死代码清理         | 阶段性重构                       |
| `doc-updater`          | 文档同步           | 功能变更后                       |

## 4. ECC Skills 速查（按需调阅）

| Skill               | 用途                                               |
| ------------------- | -------------------------------------------------- |
| `frontend-design`   | 设计美学守则                                       |
| `react-patterns`    | React 组件 / Hooks / State 决策                    |
| `react-testing`     | RTL + Vitest + Playwright                          |
| `react-performance` | 70+ 性能规则（waterfalls / bundle / re-render）    |
| `accessibility`     | WCAG 2.2 AA + 24×24px touch target                 |
| `coding-standards`  | 代码质量守则（KISS / DRY / YAGNI / 不可变 / 命名） |
| `tdd-workflow`      | 80% coverage + 单元/集成/E2E                       |
| `security-review`   | Secrets / 注入 / Auth / XSS / CSRF / Rate Limit    |

## 5. ECC Commands 速查（argus 常用）

| Command         | 用途              |
| --------------- | ----------------- |
| `/tdd`          | TDD 流程          |
| `/plan`         | 任务规划          |
| `/e2e`          | E2E 测试          |
| `/code-review`  | 代码 review       |
| `/react-review` | React 专项 review |
| `/build-fix`    | 编译错误排查      |
| `/learn`        | 提取经验          |
| `/skill-create` | 创建新 skill      |
| `/feature-dev`  | 功能开发完整流程  |
| `/project-init` | 项目初始化        |

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
8. **新增 ECC agent / skill / command** → 更新 `AGENTS.md §3-5`

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

### 16.2 Less 样式策略

- Next.js 15 内置 `.module.less` 支持，**无需新增 less-loader 依赖**
- 样式用 Less 原生 `&` 嵌套，写在 `index.module.less`
- 颜色统一用 CSS 变量 `var(--token-xxx, #fallback)`，fallback 取 `tailwind.config.ts` 的 47 token 原色
- `globals.css` 只放全局 token（@font-face / Material Symbols base / .tech-grid-pattern / .tech-dot-pattern），**不放任何组件样式**

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
- ❌ 自己起 playwright / curl / screenshot 验证 → 项目统一人工验证
- ❌ 把 shadcn 组件文件名改成小写（`button.tsx`）→ PascalCase 强制

---

- [apps/web/CONTRIBUTING.md](./apps/web/CONTRIBUTING.md)
- [apps/api/CONTRIBUTING.md](./apps/api/CONTRIBUTING.md)
- [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)
- [docs/CODE-QUALITY.md](./docs/CODE-QUALITY.md)
- [prd/PRD 总览](./prd/README.md)
