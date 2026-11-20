# 待办：前端可访问性缺口 + 平台 UI 原语 + 主题机制三处问题

> 2026-11-20 立。来源：评估 `GoogleChrome/modern-web-guidance`（Chrome 团队的
> web 平台最佳实践 skill）对 argus 的适配度时，逐条核对 `apps/web` 现状得出。
>
> **本文只记「实测到的问题」，不含实现方案**——实现方案要单独立项。
> 每条都标了 `file:line`，可以自己复核。

## 背景：为什么评估这个插件

`modern-web-guidance` v1.0.1 已装到**全局**（`modern-web-guidance@googlechrome`，
user scope）。它是纯 skill 形态：**无 hook、无 MCP、无自动注入**，只在 agent
主动 `npx modern-web-guidance@latest search|retrieve` 时把指南拉进 context。

对 argus 的适配度结论：

- **技术栈零适配**。指南全是 vanilla HTML/CSS/JS；`grep -ril
  "tailwind|shadcn|radix" skills/` 只命中 SKILL.md 自己一行。argus 是
  CSS Modules 主力（`styles.` 引用 1037 处 vs Tailwind class 57 处）+
  shadcn/ui + Tailwind v3。
- **只两块值得用**：可访问性深度（`accessibility/accessibility.md`，585 行）、
  平台 UI 原语（`ui-components/dialog.md`、`ui-components/menu.md`、
  `ui-behaviors/declarative-dialog-popover-control.md`）。
- **三块明确不用**：CSS 架构 / dark mode 主题机制 / token 体系 —— 解法与 argus
  架构不兼容（详见本文 §1.3、§3）。

**在本项目使用时的边界**（已写入 `AGENTS.md §10.1` 与 `.claude/rules/web.md`）：
只查 a11y、平台 UI 原语、forced-colors / reduced-motion 这类环境适配；
不查不改主题机制、`light-dark()`、token 体系、`@layer`、CSS 架构。
指南与 W1/W2/W3 冲突时以 argus 规则为准。

**遥测已关**（2026-11-21）：`~/.claude/settings.json` 的 `env` 块设了
`DISABLE_TELEMETRY=1`。默认会上报 agent 生成的**搜索词原文**与
retrieve 的 guide_id 到 Google Clearcut（`play.googleapis.com/log`）——
搜索词若带了项目语境就会外泄。

---

## 1. 主题机制（`color-scheme`）

### 1.1 `:root` 未声明 `color-scheme` —— 亮色模式下原生控件跟随系统

**实测**：`app/globals.css:80` 的 `:root` 块里**没有** `color-scheme`；
只有 `app/globals.css:248` 的 `html[data-theme='dark']` 声明了
`color-scheme: dark`。

**后果**：亮色模式下，UA 渲染的原生控件（滚动条、`<input>`/`<select>` 原生外观、
日期选择器）**跟随操作系统**。系统是暗色时，页面是亮的但滚动条是暗的。

**不是「风格差异」，是实际的不一致。**

### 1.2 首屏主题闪烁（FOUC）

**实测**：`components/common/ThemeToggle/index.tsx:29-33` 在 `useEffect` 里才
从 `localStorage` 读 `argus.theme` 并写 `document.documentElement.dataset.theme`。
服务端渲染时读不到 localStorage → **首帧必然是亮色**（默认 `'light'`）。
深色主题用户每次加载都会看到一次亮色闪屏。

**注**：ThemeToggle 的注释里已经标出这个问题的根因是「服务端拿不到 localStorage」，
并说「真正的修法是让服务端也拿到这个值（cookie 持久化 + SSR 读 cookie），
属于架构改动」——**这条待办要么接受架构改动，要么接受闪屏，要么走中间方案**。

### 1.3 `light-dark()` 不可用（结论，非问题）

`light-dark()` 靠 computed `color-scheme` 判定，而 argus 是手动
`data-theme` 切换 → 两者不通。**所以 `visual-design/dark-mode.md` 的
`light-dark()` 方案对 argus 不适用**，不要照搬。

**待决策**：argus 是否应该跟随系统偏好（`prefers-color-scheme`）？
现状是**刻意不跟随**（默认 light，不看系统）。这是产品选择，改不改是决策。

---

## 2. 可访问性缺口

### 2.1 无 skip link

**实测**：`grep -ril "skip" app components` 无命中（只有 explore/page.tsx
的注释里出现 "skipped" 一词，指报告状态，与 a11y 无关）。

键盘用户每次导航都要 Tab 过整个侧边栏。

### 2.2 无 `aria-live` 区域

**实测**：只有 `role="alert"`（8 处，assertive，会打断读屏）与
`role="status"`（1 处，`FaithfulnessPanel/index.tsx:90`）。
**没有 polite live region** 承载异步状态更新（如报告生成进度）。

### 2.3 `prefers-reduced-motion` 覆盖率 1/85

**实测**：85 个 css 文件里只有 1 处
（`app/(dashboard)/add-sources/components/QueueMonitor/index.module.css:213`）。

### 2.4 `prefers-contrast` / `forced-colors` 覆盖 0

**实测**：两者均 0 处。

**注**：Windows 高对比度模式下浏览器会覆盖作者颜色、移除 `box-shadow` 与渐变背景。
argus 大量用 `box-shadow` 做层次（`box-shadow: 0 1px 2px rgba(0,0,0,0.04)` 等），
高对比度下会消失。

### 2.5 3 处 `:focus` 而非 `:focus-visible`

**实测**（与 `.claude/rules/web.md` W7 相悖）：
- `app/(auth)/login/components/EmailInput/index.module.css:48`
- `app/(auth)/login/components/SsoPanel/index.module.css:110`
- `app/(dashboard)/add-sources/components/UrlRssTabs/index.module.css:77`

其余 6 处用的是 `:focus-visible`（UserMenu ×5、explore/page ×1）。

### 2.6 弹层无 focus trap / 焦点不归还

**实测**：`grep -rn "focusTrap|focus-trap|tabIndex={-1}|autoFocus" app components`
无命中。Esc 键处理全项目只有 1 处
（`app/(dashboard)/explore/components/PromptInput/index.tsx:83`，且只管 slash 面板）。

**后果**：弹层打开时焦点不进去，关闭时不回来。

**已有的正面例子**：`app/(dashboard)/explore/components/InspectorDrawer/index.tsx:73`
用了 `inert={!open}`，注释里引了 WCAG 2.4.3 / 4.1.2 —— 这条做对了，
其余弹层没有同等处理。

### 2.7 （不算缺口，记录一下）a11y 底子比预期好

`lang="zh-CN"`、38 处 `aria-label`、8 处 `role="alert"`、6 处
`:focus-visible`、`inert` 用法 —— `.claude/rules/web.md` W7 与全局
`cr-react.md` R7 那几条硬底线基本都守住了。

**缺口不在硬底线，在深度**（§2.1–§2.6）。

---

## 3. 平台 UI 原语（手写了原生能给的）

### 3.1 SlashCommandPopover 缺 `aria-activedescendant`

**实测**：`app/(dashboard)/explore/components/SlashCommandPopover/index.tsx:31`
用 `role="listbox"`，子项 `role="option"` + `aria-selected={i === activeIndex}`。
但**没有 `aria-activedescendant`**，option 也没分配 id。

**后果**：`activeIndex` 只改了 CSS class 和 `aria-selected`。读屏用户知道
「有 3 个选项」，但不知道「当前高亮第 2 个」；方向键移动的是视觉高亮，
不是读屏焦点。

### 3.2 UserMenu 声明了 `role="menu"` 但没有方向键导航

**实测**：`app/(dashboard)/components/UserMenu/index.tsx` 用 `role="menu"` +
`role="menuitem"`，但 `grep -n "onKeyDown|ArrowDown|tabIndex"` 无命中。

**后果**：menu 角色隐含「用方向键移动」，读屏会按这个播报，用户按 ↓ 没反应。

### 3.3 UserMenu 注释里的 `matchMedia` 根本没实现

**实测**：注释（`UserMenu/index.tsx:24`）写「再用 matchMedia 排除掉纯 hover 的
指针类型，避免桌面端触屏误触」。但全项目 `grep -rn "matchMedia"` **只命中这一行注释**，
没有任何实现。

**这正是根 `CLAUDE.md` §4 点名的类型**——注释里的技术断言与现状不符。

### 3.4 FilterDrawer 是 inline `<aside>`，非 dialog 语义

**实测**：`app/(dashboard)/reports/components/FilterDrawer/index.tsx`
渲染 `<aside className={styles.root}>`，无 `aria-modal`、无焦点管理、无 Esc。

**注**：它是常驻侧栏（宽度 18rem，不遮挡页面），**可能本来就不该是 dialog**。
需先确认产品意图再决定改不改。

---

## 4. `transition: all`（12 处）

**实测**：`grep -rn "transition: all|transition-all" app components` → 12 处。

| 文件 | 行 |
|---|---|
| `app/(auth)/login/components/OAuthButton/index.module.css` | 12 |
| `app/(auth)/login/components/EmailInput/index.module.css` | 38 |
| `app/(auth)/login/components/LoginHeader/index.module.css` | 68 |
| `app/(auth)/login/components/SsoPanel/index.module.css` | 22 |
| `app/(dashboard)/explore/page.module.css` | 45 |
| `app/(dashboard)/add-sources/components/UploadDropZone/index.module.css` | 55 |
| `app/(dashboard)/add-sources/components/UrlRssTabs/index.module.css` | 70 |
| `app/(dashboard)/sources/components/SourceFilterBar/index.module.css` | 43, 91 |
| `app/(dashboard)/reports/components/FilterDrawer/index.module.css` | 11 |
| `components/common/TableCells/cells.module.css` | 178 |
| `components/common/PageHeader/index.module.css` | 342 |

**为什么是问题**：`all` 会过渡所有可动画属性，含 `width`/`height`/`padding`
这类触发 layout 的属性。且将来新增任何属性都会被意外过渡。

**注意**：`modern-web-guidance` **不覆盖这条**——`css.md` 不谈 transition，
`forms/brand-consistent-forms.md:131` 里反而有一处示例 `transition: all 0.2s ease`。
**这条要自己改，不用插件。**

---

## 5. token 体系（argus 较脆，但不是「标准问题」）

**实测**：`app/globals.css` 里 44 个 Material 3 token 在 `:root`（第 80 行起）
和 `html[data-theme='dark']`（第 247 行起）**各手写一遍**。改一个值要改两处。

`css.md` 建议四层 token（literal → semantic → UI → component）+ cascade layers。

**但**：argus 的真源是 `tailwind.config.ts`，`var(--token-xxx, #fallback)`
这套是「Tailwind config 值 → 手工同步到 CSS 变量」的桥。照搬指南的四层命名
会**引入第二套 token 命名**，跟 `tailwind.config.ts` 打架。

**结论**：argus 这里确实脆，但指南的解法不对口。**要改得另立方案**，
（例如让 Tailwind config 成为唯一真源、构建期生成 CSS 变量），不是照搬指南。

---

## 6. 其他实测到的可选项

- `@container`（container query）0 处，54 处 `@media` —— 是否值得引入看组件复用需求
- `scrollbar-color` / `scrollbar-width` 0 处 —— 跟 §1.1 的 `color-scheme` 相关
- `!important` 0 处 —— 这条是好的

---

## 7. 待办清单（按「不依赖外部决策」排序）

- [ ] **T1** `:root` 补 `color-scheme: light`（§1.1）—— 修原生控件与页面主题分裂
- [ ] **T2** `transition: all` 改成显式属性列表（§4）—— 12 处
- [ ] **T3** 3 处 `:focus` → `:focus-visible`（§2.5）
- [ ] **T4** UserMenu 注释与实现对齐：要么实现 `matchMedia`，要么删掉注释里的断言（§3.3）
- [ ] **T5** `prefers-reduced-motion` 补齐（§2.3）
- [ ] **T6** `forced-colors` 兜底（§2.4）
- [ ] **T7** skip link（§2.1）
- [ ] **T8** polite live region 承载异步状态（§2.2）
- [ ] **T9** SlashCommandPopover 的 `aria-activedescendant`（§3.1）
- [ ] **T10** UserMenu 方向键导航（§3.2）
- [ ] **T11** 弹层 focus trap / 焦点归还（§2.6）
- [ ] **T12** 首屏 FOUC（§1.2）—— 需决策走哪条路
- [ ] **T13** FilterDrawer 是否该改 dialog 语义（§3.4）—— 需先确认产品意图
- [ ] **T14** 是否跟随系统主题偏好（§1.3）—— 产品决策
- [ ] **T15** token 单一真源改造（§5）—— 架构级，另立项

---

## 相关

- `CLAUDE.md` §2 跨模块语义一致性 / §4 文档断言 / §6 审查时的项目事实
- `.claude/rules/web.md` W2（token 规范）、W7（a11y 补充）
- `~/.claude/rules/cr-react.md` R7（可访问性硬底线）、What NOT to Flag
- `modern-web-guidance` 指南：
  `accessibility/accessibility.md`、`ui-components/dialog.md`、
  `ui-components/menu.md`、`visual-design/color.md`、`ui-behaviors/motion.md`
