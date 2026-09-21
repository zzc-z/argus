# apps/web — 前端贡献指南

## 1. 环境要求

- **Node.js** ≥ 20
- **pnpm** ≥ 9
- 沙盒 / 网络限制 npm registry 时：`pnpm config set registry https://registry.npmmirror.com`

## 2. 安装

```bash
cd /Users/ext.zhangjianpeng11/Desktop/argus
pnpm install

# 只装 web
cd apps/web && pnpm install
```

## 3. 目录结构

```
apps/web/
├── app/                              # Next.js App Router
│   ├── layout.tsx                    # 根 layout，含 metadata + font link + body className
│   ├── globals.css                   # 全局样式 + 字体声明
│   └── (auth)/
│       └── login/
│           └── page.tsx              # 登录页（拆分前是单文件，拆后是 7 个子组件）
├── public/                           # 静态资源（远程字体方案下无需 woff2）
├── eslint.config.mjs                 # ESLint flat config + FlatCompat
├── commitlint.config.js              # commitlint + workspace-scopes
├── .lintstagedrc.json                # lint-staged 配置
├── .prettierrc.json                  # Prettier 格式
├── .prettierignore                   # Prettier 忽略
├── .husky/                           # git hooks
│   ├── pre-commit                    # 跑 lint-staged + tsc --noEmit
│   └── commit-msg                    # 跑 commitlint
├── package.json                      # deps + devDeps + scripts
├── tsconfig.json                     # TypeScript 配置
├── next.config.js                    # Next.js 配置
├── tailwind.config.ts                # Tailwind v3.4.19 配置（47 color + 11 font + 11 size token）
├── postcss.config.js                 # PostCSS + tailwindcss + autoprefixer
├── components.json                   # shadcn CLI 配置（new-york + cssVariables:false）
├── lib/                              # 工具函数
│   └── utils.ts                      # cn = twMerge(clsx(...))
└── components/                       # 业务组件
    ├── ui/                           # shadcn CLI 装的组件（W1 已装 button/card/input/label）
    │                                 # 绝对禁止手改，统一走 pnpm dlx shadcn@latest add
    └── ...                           # 手写业务组件（W2+ 启用）
```

## 4. 开发命令

```bash
pnpm dev                              # 起 Next.js dev server
pnpm build                            # production build
pnpm start                            # 跑 production server
pnpm lint                             # next lint
pnpm lint:fix                         # eslint . --fix --max-warnings=0
pnpm format                           # prettier --write
pnpm format:check                     # prettier --check（CI 用）
pnpm typecheck                        # tsc --noEmit
pnpm dlx shadcn@latest add <name>     # 加新 shadcn 组件到 components/ui/（自动装 peer deps）
```

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

## 13. 测试

待 Vitest / React Testing Library 启用后配。本期 W1 仅 `apps/api/tests/test_smoke.py`（pytest）。

## 14. 部署

待 Vercel / 阿里云启用后配。本期 W1 仅本地 dev。

## 15. 特殊配置文件作用

| 文件 | 作用 | 谁维护 |
|---|---|---|
| `eslint.config.mjs` | ESLint 9 flat config + FlatCompat 桥接 `next/core-web-vitals` + typescript-eslint strict-type-checked + react-hooks + jsx-a11y + import + tailwindcss + prettier bridge | 改 lint 规则时 |
| `.prettierrc.json` | Prettier 3.x 配置：printWidth 100 / semi true / singleQuote false / trailingComma all / arrowParens always / plugins 含 `prettier-plugin-tailwindcss` | 改 format 规则时 |
| `.prettierignore` | Prettier 忽略：`.next` / `node_modules` / `out` / `dist` / `coverage` / 锁文件 | 加新忽略项时 |
| `commitlint.config.js` | commitlint + 11 type + workspace-scopes 自动 monorepo scope | 改 commit 规范时 |
| `.lintstagedrc.json` | lint-staged 配置：TS/TSX 跑 `eslint --fix + prettier --write`；JSON/MD 跑 `prettier --write` | 改 staged hooks 时 |
| `.husky/pre-commit` | husky git hook：跑 `pnpm exec lint-staged` + `pnpm exec tsc --noEmit` | 改 pre-commit 行为时 |
| `.husky/commit-msg` | husky git hook：跑 `pnpm exec commitlint --edit "$1"` | 改 commit msg 行为时 |
| `components.json` | shadcn/ui 配置：new-york 风格 / RSC / TSX / tailwind 路径 / aliases（由 `pnpm dlx shadcn@latest init` 自动生成） | 改 shadcn 风格时 |
| `lib/utils.ts` | `cn = twMerge(clsx(...))` helper（由 shadcn CLI 自动生成） | 改 cn helper 时 |

## 16. 链接

- [CLAUDE.md 根配置](../../CLAUDE.md)
- [AGENTS.md（仓库根）](../../AGENTS.md)
- [apps/api/CONTRIBUTING.md](../../apps/api/CONTRIBUTING.md)
- [docs/CONVENTIONS.md](../../docs/CONVENTIONS.md)
- [docs/CODE-QUALITY.md](../../docs/CODE-QUALITY.md)
- [prd/tech-stack.md](../../prd/tech-stack.md)
- [shadcn/ui 文档](https://ui.shadcn.com)
