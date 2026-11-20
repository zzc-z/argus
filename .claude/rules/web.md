---
paths:
  - "apps/web/**/*.tsx"
  - "apps/web/**/*.ts"
  - "apps/web/**/*.css"
---

# argus · 前端审查规则

> 适用 `apps/web/**` 改动。通用规则见根 `CLAUDE.md`，跨项目通用规则见全局 `~/.claude/CLAUDE.md` §5。
> 每条写成可判定的形式——审查时需要能引用原文说明违反哪条。

## W1. 组件必须文件夹形式封装

每个组件一个文件夹，**PascalCase**（`Button.tsx` 不是 `button.tsx`），
文件夹内固定两文件：`index.tsx` + `index.module.css`。

**违反判据**：新增组件是单个 `.tsx` 文件（而非文件夹形式），
或文件名不是 PascalCase。

**例外**：`components/ui/<Name>.tsx` 是 shadcn 组件——单文件、无 css。

## W2. 样式用 `.module.css`，不用 `.module.less`

**违反判据**：出现 `.module.less` 文件，或 CSS 里用了 Less 的 `&` 父选择器嵌套。

**为什么**：Next.js 15+ 不内置 `.module.less`，手配 loader 会有 css 文本
丢失、className 注入问题。改用 `.module.css` 是 next 内置方案，零配置。
嵌套规则必须展开成完整 css selector。

**颜色**：统一 `var(--token-xxx, #fallback)`，fallback 取 `tailwind.config.ts`
的 token 原色。禁止 `bg-[#XXX]` / `bg-oklch(...)` 任意值。

## W3. shadcn 优先，禁止引新组件库

**违反判据**：引入 MUI / Chakra / Mantine / Ant Design；
或手改 `components/ui/` 下的文件（那些由 CLI 生成，下次装组件会覆盖）。

**新功能**：先看 `components/ui/{Button, Card, Input, Label, Badge, Separator}`
有没有现成的。新增组件走 `pnpm dlx shadcn@latest add <name>`。

## W4. Hook：默认不包 `useCallback` / `useMemo`

**argus 现状**：React 19.3 + **React Compiler 未启用**，全项目 `React.memo` 0 处。

通用判据见全局 `~/.claude/rules/cr-react.md`（React Compiler 未启用时，
白包反而制造渲染期引用不稳定的风险）。argus 特有的**白包形态**：

- **空函数 `useCallback(() => {}, [])`** —— 零收益纯噪音
- **单纯「怕子组件重渲染」但子组件没 memo** —— 白包
- 函数体内没读响应式值，deps 却写满 —— 本来就不会变
- 「以防万一」预包 —— YAGNI

**这四种之外仍可包**：
- 函数传给 `React.memo` 子组件 / 第三方 `memo()` 组件
- 函数是 `useEffect` / `useMemo` 的依赖，且闭包里有 state/props

**依赖数组必须诚实**：闭包里读了什么就写什么，禁止为了少写几个删依赖。
`react-hooks/exhaustive-deps` 已配为 `error`——**依赖数组的问题 lint 会抓，
不要重复报**；只有「白包 / 空包」这类 lint 抓不到的才报。

## W5. 轮询与定时器

**违反判据**：用固定 `setInterval` 对每个 pending id 各发一个请求，
且 effect 依赖是 `[]`（定时器永不停）。

**为什么**：请求慢于间隔时请求会堆叠，传 20 份文件后端 QPS 悄悄涨一个量级。

**正确做法**：每个 id 一条自调度链——请求完成后才安排下一拍。
资料进入终态（indexed/failed）链自然结束；组件卸载时全部停掉。

## W6. 图标

唯一来源：Google `Material Symbols Outlined`（本地 woff2）。
不用 lucide-react、不用 emoji、不自定义 SVG 替代。

## W7. a11y 补充（argus 特有）

通用底线见全局 `~/.claude/rules/cr-react.md` R7。argus 补充：

- 焦点环用 `focus-visible:ring-2`（不是 `focus:ring-2`）
- 资料状态（indexed / failed / pending）不能只靠颜色——加图标或文字

## What NOT to Flag（argus 前端）

> 通用不报项见全局 `~/.claude/rules/cr-react.md` 的 What NOT to Flag
> 与全局 `~/.claude/CLAUDE.md` §5.0.4。以下是 **argus 特有**的：

- **eslint / tsc 能抓到的**——依赖数组、hooks 规则、未用变量、
  类型不匹配。官方 CR 会单独跑门禁。
- **「应该用 shadcn 组件替代手写的」**——除非违反 W1 的文件夹形式
  或 W3 的「手改 components/ui/」。
- **「组件应该拆得更细」**——除非触发 W1/W4 的具体判据。
- **CSS 间距与颜色的微差**——除非违反 W2 的 token 规范。
- **「应该加 useMemo 优化」**——argus 未启用 React Compiler，
  白包反而制造渲染期引用不稳定的风险（见全局 R1）。
- **「应该用 Suspense / 虚拟列表」**——性能建议，除非改动引入
  可复现的卡顿。
- **「应该改用 React Server Components」**——架构偏好，
  本项目是 Next.js App Router + 客户端交互的既定选型。
- **测试代码里的**——快照不精确、mock 缺失。
- **「应该用 `light-dark()` / `@layer` / 四层 token 命名」**——本项目主题是
  `html[data-theme]` 手动切换，`light-dark()` 与之不通；token 真源是
  `tailwind.config.ts`。理由见 `AGENTS.md §10.1`。
- **「应该用 `modern-web-guidance` 指南里的 X」**——该插件在 argus 只开放
  a11y / 平台 UI 原语 / 环境适配三块，其余建议不采。

## W8. 已实测的 a11y 缺口（改动碰到对应文件时先看）

以下问题**已经实测并记录在 `docs/TODO-frontend-a11y-platform-ui.md`**，
每条带 `file:line`：

| 缺口 | 涉及文件 |
|---|---|
| 无 skip link | 全局 |
| 无 polite `aria-live` 区域 | 全局（只有 `role="alert"` 与 1 处 `role="status"`） |
| `prefers-reduced-motion` 覆盖 1/85 | 全局 |
| `prefers-contrast` / `forced-colors` 覆盖 0 | 全局 |
| 3 处 `:focus` 而非 `:focus-visible` | EmailInput / SsoPanel / UrlRssTabs |
| 弹层无 focus trap / 焦点不归还 | 全局（Esc 只有 PromptInput 一处） |
| SlashCommandPopover 缺 `aria-activedescendant` | `explore/components/SlashCommandPopover/index.tsx:31` |
| UserMenu 声明 `role="menu"` 但无方向键导航 | `dashboard/components/UserMenu/index.tsx` |
| UserMenu 注释里的 `matchMedia` 未实现 | `dashboard/components/UserMenu/index.tsx:24` |
| FilterDrawer 是 inline `<aside>`，非 dialog 语义 | `reports/components/FilterDrawer/index.tsx` |

**审查判据**：改到对应文件时，**如果改动正好落在缺口上**（比如给 popover 加
方向键、给弹层加焦点管理），那是对的，不要报。
如果改动**没碰**缺口而 CR 报「这里缺 skip link」这类——
那是既有问题（全局 §5.9），**不报**。

**「注释里的技术断言与实现不符」是要报的**（根 `CLAUDE.md` §4）——
`UserMenu` 的 `matchMedia` 就是一个实例，注释声称做了、实际没做。

---

**相关**：完整前端规范见 `apps/web/CONTRIBUTING.md`（人类阅读）。
