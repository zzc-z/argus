# apps/web — 前端贡献指南

## 1. 环境要求

- **Node.js** ≥ 20
- **pnpm** ≥ 9
- 沙盒 / 网络限制 npm registry 时：`pnpm config set registry https://registry.npmmirror.com`

## 2. 安装

```bash
cd /Users/zjp/Desktop/argus
pnpm install

# 只装 web
cd apps/web && pnpm install
```

## 3. 目录结构

```
apps/web/
├── app/                              # Next.js App Router（无 app/api/ 路由，只调后端）
│   ├── layout.tsx                    # 根 layout，含 metadata + next/font + body className
│   ├── globals.css                   # 全局 token + 字体声明（Material Symbols @font-face）
│   ├── icon.svg                      # favicon
│   ├── (auth)/login/                 # 登录页（12 个子组件）
│   ├── (dashboard)/                  # 主应用（layout = 侧边栏 + 顶栏 + AuthGuard）
│   └── (error)/error-500/            # 500 错误页
├── public/                           # 静态资源
│   └── fonts/material-symbols-outlined.woff2   # Material Symbols 本地字体
├── eslint.config.mjs                 # ESLint flat config
├── commitlint.config.mjs             # commitlint 规则
├── .prettierignore                   # Prettier 忽略（**没有 prettier 配置文件，用默认值**）
├── .husky/                           # git hooks
│   ├── pre-commit                    # 跑 pnpm run lint + tsc --noEmit（后端门禁仅在改了 apps/api/* 时跑）
│   └── commit-msg                    # 跑 commitlint
├── package.json                      # deps + devDeps + scripts
├── tsconfig.json                     # TypeScript 配置
├── next.config.js                    # Next.js 配置
├── tailwind.config.ts                # Tailwind v3.4.19 配置（50 color + 11 font + 11 size token）
├── postcss.config.js                 # PostCSS + tailwindcss + autoprefixer
├── components.json                   # shadcn CLI 配置（new-york + baseColor:custom + cssVariables:true）
├── lib/                              # 共享层
│   ├── api/                          # client.ts（fetch 封装）+ sse.ts + 各域类型与调用
│   ├── auth/                         # UserContext.tsx（登录态，含 AuthStatus 四态）
│   ├── notifications/                # NotificationsContext.tsx
│   ├── theme/                        # ThemeContext.tsx
│   ├── hooks/                        # useStickToBottom.ts
│   ├── markdown/                     # parse.ts
│   └── utils.ts                      # cn = twMerge(clsx(...))
└── components/                       # 业务组件
    ├── ui/                           # shadcn CLI 装的组件（Button/Card/Input/Label/Badge/Separator）
    │                                 # 绝对禁止手改，统一走 pnpm dlx shadcn@latest add
    └── common/                       # 自建公共组件，12 个（一个组件一个文件夹）
```

## 4. 开发命令

```bash
pnpm dev                              # 起 Next.js dev server（--webpack）
pnpm dev:turbopack                    # 起 dev server（Turbopack）
pnpm build                            # production build
pnpm start                            # 跑 production server
pnpm lint                             # eslint app components lib
pnpm format                           # prettier --write
pnpm format:check                     # prettier --check（CI 用）
pnpm exec tsc --noEmit                # 类型检查（**必须带 exec**，见下）
pnpm dlx shadcn@latest add <name>     # 加新 shadcn 组件到 components/ui/（自动装 peer deps）
```

**没有 `lint:fix` / `typecheck` script。** `pnpm tsc --noEmit` 是**空命令**——
package.json 里没有 `tsc` script，它会打印「None of the selected packages has a
"tsc" script」然后退出码 0，什么都没跑。类型检查必须写 `pnpm exec tsc --noEmit`。

## 5. 提交前自检 (CLAUDE.md §1.2)

函数 ≤50 行 / 文件 ≤800 行 / 嵌套 ≤4 层 / 不可变 mutation / 命名一致。

提交前自检 5 条：

1. 删除走不到的 if 分支
2. 删除未引用的 import
3. 删除同时存在的旧路径
4. Token 预算：单任务 ≤4k，会话 ≤30k
5. 调研不超过 5 个回合——超过就停下来问用户

## 6. shadcn/ui 组件用法

shadcn 不是 npm 包，是 **copy-paste ownership** 模式（源码所有权）。

**W1 已完成首次安装**（`components.json` + `lib/utils.ts` + `components/ui/{button,card,input,label}.tsx`），加新组件统一走：

```bash
pnpm dlx shadcn@latest add <name>     # 例：add dialog dropdown-menu select
```

CLI 自动做的事：

1. 下载组件源码到 `apps/web/components/ui/`
2. 装 peer deps 到 `apps/web/package.json`
3. 不改 `tailwind.config.ts` / `globals.css`（因为 `components.json` 设了 `cssVariables: false`）

**禁止**手动改 `apps/web/components/ui/` 下的文件——shadcn CLI 是唯一 source of truth，下次 add 会覆盖。

如果 `components.json` 被误删，重跑 `pnpm dlx shadcn@latest init --yes` 重建（不会覆盖 `components/ui/`）。

## 7. 设计 token 使用规范

- 颜色：`bg-primary` / `text-on-surface` / `border-outline-variant` 等 47 个 token（见 `tailwind.config.ts` `theme.extend.colors`）
- 字号：`text-body-sm` / `text-headline-md` / `text-label-sm` 等 11 个（见 `tailwind.config.ts` `fontSize`）
- 字体家族：`font-body-sm` / `font-headline-md` / `font-label-sm` 等 11 个（见 `tailwind.config.ts` `fontFamily`）

禁止直接用 `bg-[#XXXXXX]` hardcode 颜色——全部用 token。

## 8. Material Symbols 图标

所有图标统一使用 Google 字体 `Material Symbols Outlined`（已在 `app/layout.tsx` 引入）。
图标的 name **优先在 design 12 个页面里找**（design/code.html）；**design 没有的**可用 `lucide-react`（shadcn 默认依赖）。
禁止：自己画 SVG icon / 用 emoji / 用 lucide 替代 design 里已存在的同义 icon。

## 9. 字体

阿里巴巴普惠体（Alibaba PuHuiTi）通过阿里妈妈 Smart Font 远程加载：

- 本地路径：`apps/web/public/fonts/`（已清空，远程方案不需要 .woff2）
- 远程加载：app/layout.tsx `<head>` 里的 `<link href="https://at.alicdn.com/t/c/font_你的ID.css">`
- 字体声明：`globals.css` `@layer base` `html, body { font-family: 'AlibabaPuHuiTi', system-ui, ... }`

## 10. 命名边界

- **组件文件**：`PascalCase.tsx`（如 `LoginForm.tsx`）
- **工具函数**：`camelCase.ts`（如 `formatDate.ts`）
- **常量**：`UPPER_SNAKE_CASE.ts`（如 `API_ENDPOINTS.ts`）
- **路由**：`kebab-case`（如 `/login-form`）
- **shadcn 组件**：`kebab-case.tsx`（如 `button.tsx`，CLI 强制）

## 11. 状态管理边界

- **本地状态**：React useState（仅组件内部）
- **跨组件**：Context API（轻量）
- **跨路由**：URL params（Next.js searchParams）
- **服务端状态**：SWR / React Query（**禁止**直接 fetch + useState）
- **全局状态**：Zustand（**禁止** Redux / MobX——与本项目栈不兼容）

## 12. a11y 基线

- 所有 `<button>` 必须有 `aria-label` 或可见文字
- 所有 `<img>` 必须有 `alt`
- 所有 `<input>` 必须关联 `<label htmlFor="...">`
- 颜色对比度 ≥ 4.5:1（WCAG AA）
- 键盘导航：Tab / Enter / Esc / Arrow keys 全可用

### 12.1 已实测的缺口（2026-11-21）

上面 5 条是**硬底线**，项目已守住。以下是实测出的**深度缺口**，逐条带
`file:line`，待办清单见
[`docs/TODO-frontend-a11y-platform-ui.md`](../../docs/TODO-frontend-a11y-platform-ui.md)：

- 无 skip link
- 无 polite `aria-live` 区域（只有 `role="alert"` 与 1 处 `role="status"`）
- `prefers-reduced-motion` 覆盖 1/85 个 css 文件
- `prefers-contrast` / `forced-colors` 覆盖 0
- 3 处 `:focus` 而非 `:focus-visible`（EmailInput / SsoPanel / UrlRssTabs）
- 弹层无 focus trap / 焦点不归还（Esc 只有 1 处处理）

### 12.2 平台 UI 原语

`SlashCommandPopover` 与 `UserMenu` 手写了 listbox / menu 的 a11y 语义，但：

- SlashCommandPopover 缺 `aria-activedescendant`（读屏不知道当前高亮第几项）
- UserMenu 声明 `role="menu"` 却无方向键导航
- UserMenu 的注释声称用 `matchMedia` 排除纯 hover 指针类型——**该实现不存在**

**写新的浮层组件前**先查全局的 `modern-web-guidance` 插件（`<dialog>` / popover
/ anchor positioning 原生方案），用法与边界见 `AGENTS.md §10.1`。

## 13. 测试

待 Vitest / React Testing Library 启用后配。本期 W1 仅 `apps/api/tests/test_smoke.py`（pytest）。

## 14. 部署

待 Vercel / 阿里云启用后配。本期 W1 仅本地 dev。

## 15. 特殊配置文件作用

| 文件                   | 作用                                                                                                              | 谁维护               |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------- |
| `eslint.config.mjs`    | ESLint 9 flat config：@eslint/js + eslint-config-next + typescript-eslint（含 `react-hooks/exhaustive-deps: error`） | 改 lint 规则时       |
| `.prettierignore`      | Prettier 忽略：`.next` / `node_modules` / `out` / `dist` / `coverage` / 锁文件                                  | 加新忽略项时         |
| `commitlint.config.mjs` | commitlint 规则：Conventional Commits；`scope-enum` 已关闭（scope 可选），header 上限 100 字符                  | 改 commit 规范时     |
| `.husky/pre-commit`    | husky git hook：前端 `pnpm run lint` + `pnpm exec tsc --noEmit`；后端仅在 staged 含 `apps/api/*` 时跑 ruff + mypy | 改 pre-commit 行为时 |
| `.husky/commit-msg`    | husky git hook：跑 `pnpm exec commitlint --edit "$1"`                                                             | 改 commit msg 行为时 |
| `components.json`      | shadcn/ui 配置：new-york 风格 / RSC / TSX / `baseColor: custom` / `cssVariables: true` / aliases              | 改 shadcn 风格时     |
| `lib/utils.ts`         | `cn = twMerge(clsx(...))` helper（由 shadcn CLI 自动生成）                                                        | 改 cn helper 时      |

**Prettier 没有配置文件**——只有 `.prettierignore`，其余走 Prettier 默认值。

## 16. 链接

- [CLAUDE.md 根配置](../../CLAUDE.md)
- [AGENTS.md（仓库根）](../../AGENTS.md)
- [apps/api/CONTRIBUTING.md](../../apps/api/CONTRIBUTING.md)
- [docs/CONVENTIONS.md](../../docs/CONVENTIONS.md)
- [docs/CODE-QUALITY.md](../../docs/CODE-QUALITY.md)
- [docs/TODO-frontend-a11y-platform-ui.md](../../docs/TODO-frontend-a11y-platform-ui.md)
- [prd/tech-stack.md](../../prd/tech-stack.md)
- [shadcn/ui 文档](https://ui.shadcn.com)
