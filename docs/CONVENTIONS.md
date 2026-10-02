# docs/CONVENTIONS.md — Argus 代码规范与设计约定

> 本文档是 AI 编程助手 + 代码 review 的核心参考。  
> **优先级**：`~/.claude/rules/{core,coding,tools}.md` > 本文档 > 个人习惯。

## 1. 代码质量 4 原则（Karpathy / Forrest Chang / CLAUDE.md §1.2）

1. **Think Before Coding** — 写代码前先想清楚；**有歧义就问而非假设**
2. **DRY** — 抽公共逻辑，禁止 copy-paste > 3 次
3. **YAGNI** — 不写将来才需要的功能
4. **Simple > Clever** — 2 个指头能做的事不用 3 个

## 2. 命名约定

- **文件 / 类 / React 组件**：`PascalCase.tsx`（如 `LoginForm.tsx`）
- **工具函数 / 变量**：`camelCase.ts`（如 `formatDate.ts`）
- **常量**：`UPPER_SNAKE_CASE.ts`（如 `API_ENDPOINTS.ts`）
- **路由**：`kebab-case`（如 `/login-form`）
- **shadcn 组件**：`kebab-case.tsx`（如 `button.tsx`，CLI 强制）
- **环境变量**：`SCREAMING_SNAKE_CASE`
- **数据库表**：`snake_case`（如 `users` / `research_reports`）
- **LangGraph node 名**：`snake_case`（如 `plan_agent` / `search_agent` / `synthesize_node`）

## 3. 函数 / 文件 / 嵌套 守则（CLAUDE.md §1.2）

- 单个函数 ≤ **50 行**（不含注释 / 空行）
- 单个文件 ≤ **800 行**
- JSX 嵌套 ≤ **4 层**（超出必须抽子组件）
- 不可变 mutation：`const` 优先；`let` 仅限 reducer / 计时器 / 累加器
- 删除走不到的 if 分支、未引用的 import、同时存在的旧路径
- Token 预算：单任务 ≤ 4k，会话 ≤ 30k

## 4. 状态管理边界

- 本地状态：React `useState`（仅组件内部）
- 跨组件：`Context API`（轻量场景）
- 跨路由：URL params（Next.js searchParams）
- 服务端状态：SWR / React Query（**禁止**直接 fetch + useState）
- 全局状态：Zustand（**禁止** Redux / MobX——与本项目栈不兼容）
- 服务端会话：JWT access（15min） + refresh（30day）

## 5. Material Symbols 图标

- 字体：Google `Material Symbols Outlined`（已在 `app/layout.tsx` 引入）
- name **优先**从 `design/code.html` 12 个 design 里找
- name **fallback**：可用 `lucide-react`（shadcn 默认依赖）
- **禁止**：自己画 SVG / 用 emoji / 用 lucide 替代 design 里已存在的同义 icon
- 封装组件 `<MaterialSymbol name="..." />`（自定义 helper），传入 name prop

## 6. 字体

- 阿里巴巴普惠体（Alibaba PuHuiTi），通过阿里妈妈 Smart Font 远程加载
- 远程 URL：`https://at.alicdn.com/t/c/font_你的项目ID.css`
- 字体声明：`globals.css` `@layer base` `html, body { font-family: 'AlibabaPuHuiTi', ... }`
- tailwind.config.ts fontFamily 11 个 token 全部用 `'var(--font-alibaba-puhuiti), AlibabaPuHuiTi', ...`

## 7. shadcn/ui 组件使用规范

### 7.1 安装方式

shadcn 是 copy-paste ownership 模式，通过 CLI 装包：

```bash
pnpm dlx shadcn@latest init --yes
pnpm dlx shadcn@latest add button card input label
```

### 7.2 必须用 shadcn/ui 的组件（不直接复制源码）

button / card / input / label / badge / sheet / dialog / select / switch / tabs / tooltip / dropdown-menu / accordion / avatar / skeleton / separator / checkbox / radio-group / textarea / form / popover / command / sonner / scroll-area / breadcrumb / pagination / sidebar / alert

### 7.3 token 适配

- button `variant="default"`：`bg-primary text-on-primary`
- button `variant="secondary"`：`bg-primary-container text-on-primary-container`
- button `variant="destructive"`：`bg-error text-on-error`
- button `variant="ghost"`：`hover:bg-surface-container`

### 7.4 禁止事项

- ❌ **直接复制 UI 库的源码**到本项目；使用 UI 库应通过 npm 装包引入
- ❌ 装 MUI / Chakra / Mantine / Ant Design / daisyui
- ❌ 手动改 `apps/web/components/ui/` 下的文件——shadcn CLI 是唯一 source of truth
- ❌ 在 `components/ui/` 下添加新文件（除非 shadcn CLI 添加）

### 7.5 允许的事

- ✅ 自己封装组件（如 `<MetricCard>` / `<LiveStreamLog>` / `<DAGNode>` 等业务组件）
- ✅ 把封装组件放到 `apps/web/components/`（业务组件）或 `apps/web/components/ui/`（被 shadcn CLI 管理的纯 UI 组件）

## 8. 颜色 token

`tailwind.config.ts` `theme.extend.colors` 共 **47 个**：

- 主色：`primary` / `primary-container` / `on-primary` / `on-primary-container` / `primary-fixed` / `on-primary-fixed` / `primary-fixed-variant`
- 第二色：`secondary` / `secondary-container` / `on-secondary-container` / `secondary-fixed` / `secondary-fixed-variant`
- 第三色：`tertiary` / `tertiary-container` / `on-tertiary-container` / `tertiary-fixed` / `tertiary-fixed-variant`
- 错误色：`error` / `error-container` / `on-error-container`
- 表面色：`surface` / `surface-container-lowest` / `surface-container-low` / `surface-container` / `surface-container-high` / `surface-container-highest` / `on-surface` / `on-surface-variant`
- 描边：`outline` / `outline-variant`
- 反色：`inverse-surface` / `inverse-primary` / `inverse-on-surface`
- 静态色：`surface-container-low` 等同 surface 5 层
- 反差 / 阴影：暗色模式下的 inverse-* token

**禁止**用 `bg-[#XXXXXX]` hardcode 颜色——全部用 token。

## 9. 字号 token

`tailwind.config.ts` `fontSize` 共 **11 个**：

- 标题（headline）：`text-headline-sm` / `text-headline-md` / `text-headline-lg` / `text-headline-xl` / `text-headline-xl-mobile`
- 正文（body）：`text-body-sm` / `text-body-md` / `text-body-lg`
- 标签（label）：`text-label-sm` / `text-label-md`
- 代码：`text-code`

## 10. 字体家族 token

`tailwind.config.ts` `fontFamily` 共 **11 个**：

- `font-headline-xl-mobile` / `font-headline-xl` / `font-headline-lg` / `font-headline-md` / `font-headline-sm`
- `font-body-lg` / `font-body-md` / `font-body-sm`
- `font-label-md` / `font-label-sm`
- `font-code`

## 11. 间距 / 圆角 / 阴影

- 间距：`gap-1` / `gap-2` / `gap-3` / `gap-4` / `px-3 py-2` 等 tailwind 标准
- 圆角：`rounded-md`（按钮） / `rounded-lg`（卡片） / `rounded-full`（徽章、按钮 icon）
- 阴影：`shadow-sm`（卡片） / `shadow-md`（弹窗） / `shadow-lg`（模态）

## 12. a11y 基线

- 所有 `<button>` 必须有 `aria-label` 或可见文字
- 所有 `<img>` 必须有 `alt`
- 所有 `<input>` 必须关联 `<label htmlFor="...">`
- 颜色对比度 ≥ 4.5:1（WCAG AA）
- 键盘导航：Tab / Enter / Esc / Arrow keys 全可用
- 焦点环：`focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-primary`

## 13. 全局规则速查

- 本文档范围之外 → `~/.claude/rules/{core,coding,tools}.md`
- 前端开发流程 → `apps/web/CONTRIBUTING.md`
- 后端开发流程 → `apps/api/CONTRIBUTING.md`
- 前端 / 后端工具链 → `docs/CODE-QUALITY.md`
- PRD 设计文档 → `prd/`（只读）
