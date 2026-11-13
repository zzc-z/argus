# AGENTS.md — Argus 项目 AI Agent 协作指南

> 适用于在 argus 项目上工作的所有 AI 编程助手（Claude Code / Cursor / Cline 等）。
>
> **本文件只放项目特有的事实与硬约束。** 通用的编码规范、流程骨架、回复风格
> 见全局 `~/.claude/rules/`（`coding.md` / `dev-flow.md` / `core.md`），不在此重复。

## 1. 项目快速画像

- **项目**：Argus — 多智能体深度研报平台
- **前端**：pnpm + Turborepo（monorepo）+ Next.js 16.3.7 + React 19.3 + Tailwind v3.4.19 + shadcn/ui（new-york 风格）+ Geist / GeistSans 字体
- **后端**：Python ≥3.12 + uv + FastAPI + SQLite（`sqlite+aiosqlite`）+ sqlite-vec
  - **不是** Supabase / pgvector——dev 环境没有 Postgres，向量层用 sqlite-vec 扩展。
    换 pgvector 只改 `app/services/vectorstore.py`，调用方不动。
- **设计 token**：50 个 color + 11 个 fontFamily + 11 个 fontSize（precision_technical_light 集）
- **图标字体**：Google Material Symbols Outlined，**本地 woff2**
  （`apps/web/public/fonts/material-symbols-outlined.woff2`，在 `globals.css` 里 `@font-face`）
- **代码图谱**：CodeGraph（项目级 MCP server，索引 258 文件）。agent 优先用
  `mcp__codegraph__codegraph_explore` 而不是 grep/find

## 2. 项目结构

```
argus/
├── apps/
│   ├── web/                # Next.js 前端
│   │   ├── app/           # App Router
│   │   ├── components/
│   │   │   ├── ui/        # shadcn CLI 装包自动生成（`pnpm dlx shadcn@latest add ...`）
│   │   │   └── common/    # 自建公共组件，一个组件一个文件夹
│   │   ├── lib/
│   │   │   └── utils.ts   # shadcn CLI init 自动生成（cn = twMerge(clsx(...))）
│   │   └── ...
│   └── api/               # FastAPI 后端
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

1. **Pre-commit hook**（`apps/web/.husky/pre-commit`，`core.hooksPath` 指向它）
   —— 跑前端 `eslint` + `tsc`，**有后端文件改动时**再跑后端 `ruff` + `mypy`
   （只跑快的，十秒级；全量测试留给 CI）
2. **Commit-msg hook**（同目录）—— 跑 `commitlint` 验 Conventional Commits
   （配置在 `apps/web/commitlint.config.mjs`）
3. **CI**（`.github/workflows/ci.yml`）—— 后端 `ruff + mypy + pytest`（并行）
   与前端 `eslint + tsc`，master push 与 PR 自动跑

**Conventional Commits**：type 取 `feat / fix / perf / refactor / style / test / build / chore / ci / docs / revert`。

**scope 可选**——`scope-enum` 规则关掉了，`feat: xxx` 这种不带 scope 的写法合法。

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
pnpm --filter web exec tsc --noEmit       # 类型检查（必须带 exec，见下）

# 前端 husky
pnpm --filter web prepare                 # 安装 git hooks

# 前端 shadcn
pnpm --filter web dlx shadcn@latest init  # 初始化（自动建 components.json + lib/utils.ts）
pnpm --filter web dlx shadcn@latest add button card input label  # 装组件

# 后端
cd apps/api
uv sync                                   # 装 Python 依赖
uv run ruff check app/ tests/ alembic/    # 验 ruff 规则
uv run ruff format --check .              # 验 format
uv run mypy app/                          # 验类型（strict）
uv run pytest tests/ -q --no-header -p no:cacheprovider  # 跑测试（并行配在 addopts）
```

### 7.1 本地环境：启动、重启、迁移

**先读 [docs/LOCAL-DEV.md](docs/LOCAL-DEV.md)。** 那里写了几件「做错不报错、只表现为数据是旧的」的事：

- 后端**没开 `--reload`**，改了 Python 文件必须重启，否则跑的是旧代码
  （schema 变更后最隐蔽：响应字段**静默消失**，前端拿到 `undefined`）
- 改了 `app/models/*.py` 要写并跑 Alembic 迁移
- 改了后端 schema 要手动同步前端类型镜像（`apps/web/lib/api/*.ts`）

**`pnpm --filter web tsc --noEmit` 是空命令**——`apps/web/package.json` 里没有
`tsc` script，它会打印「None of the selected packages has a "tsc" script」然后
**退出码 0**，什么都没跑。类型检查必须写 `pnpm --filter web exec tsc --noEmit`。

## 7.5 开发收尾流程（强制，2026-10-13 立，2026-10-13 修订）

**每写完一批代码，必须依次走「质量门 → 测试 → CR」，缺一不可。CR 不是可选项。**

**CR 机制本身（怎么起、起不起的判据、审查维度、置信度门槛、独立验证、
报告怎么处置）全部在全局配置里，本节不重复**：

| 内容 | 位置 |
|---|---|
| 什么时候必须起 CR / 免起的豁免 | `~/.claude/rules/workflow-sop.md` |
| 审查机制（官方 `/code-review`：4 agent 并行、置信度 ≥80、逐条独立验证） | 官方内置 skill；规则依据见根 [`CLAUDE.md`](./CLAUDE.md) 与全局 `~/.claude/CLAUDE.md` §5 |
| 流程骨架（分层反馈环、并行测试、范围纪律） | `~/.claude/rules/dev-flow.md` |
| 编码约束与「注释里的技术断言要么实测过」 | `~/.claude/rules/coding.md` |

**本节只写本项目特有的部分：具体命令、测试对应关系、实证数据。**

### 7.5.1 本项目的三步命令

```bash
# 1. 质量门（apps/api）
uv run ruff check app/ tests/ alembic/
uv run mypy app/

# 前端
pnpm --filter web lint && pnpm --filter web exec tsc --noEmit

# 2. 测试
#   并行配置在 pyproject.toml 的 addopts 里（-n 4 --dist=worksteal），
#   所以直接跑就是并行的（全量 32.5s → 12.9s）。
uv run pytest tests/ -q --no-header -p no:cacheprovider
```

**编辑期跑相关测试，不要跑全量**（改一处 → 跑全量是本项目最大的一笔浪费，实测
一轮 116 次全量 = 61 分钟纯等待）。相关测试按模块名匹配：改
`app/services/stages.py` → `tests/test_stages.py`、`tests/test_agent_stages.py`。

**推送到远端后 CI 会自动跑全量**，所以「提交前跑一次全量」是安全的，漏跑会被 CI 拦下。

### 7.5.2 提交前的最后一道

`git commit` 之前，回头检查这三件事。任何一条不满足就不要提交：

- [ ] 本批代码走完了「质量门 → 测试 → CR」三步，CR 结论已写进 commit message
- [ ] commit message 里写的每条理由，都能在代码或实测里找到支撑
- [ ] 新加的每个测试都**注入过回归验证过它真的会红**

### 7.5.3 为什么 CR 不省（本项目实证）

Claude 自己改完的代码，自己检查等于用同一套假设验同一套假设——盲区完全重合。
CR 用独立上下文重读 diff，能发现「删一行会不会报错」这类自检答案的盲区。

**实证（2026-10-13 ~ 10-15，四轮）**：CR 累计报出 5 个严重 + 20 多个重要问题。
其中最典型的一类，是「**声称解决了某个问题，但实现只覆盖了一部分**」：

- 补偿写了正文、FTS、向量三处，漏了 `chunk_count`（用户可见字段）
- 竞态令牌加在「连点角标」，漏了「点 DAG 节点」和「收到新 reference 帧」
- `_clear_stored` 的 `db.rollback()` 放错位置——session 在 commit 失败后不可用，
  rollback 放在 try 内它自己也抛，整个补偿一行不跑
- 第二轮修复自己引入严重问题：把 rollback 从 try 内挪到 try 外，理由是「它自己
  也会抛」。查 SQLAlchemy 源码确认 `Session._rollback_impl` 末尾
  `if rollback_err and rollback_err[1]: raise`——DB 真挂时 rollback 照样抛，
  补偿一行不跑、裸 `raise` 拿不到原始异常，source 卡在 `chunking`。
  **修复在它唯一有意义的场景下静默失效。** 正确解法是包住而不是挪出去

**变异测试也抓不到前两个**——测试本身也没覆盖全。

**修 A 引入 B、修 B 引入 C 是这类改动的固有风险**：每一步都有充分的理由，
合起来是一条错的路。所以 CR 的产出不能只看「问题修了吗」，还要问
「这个修复引入了什么新的前提」。连续三轮在同一片代码上打转时就该停——
边际产出已经变成「写看起来很有道理的注释」。

完整复盘见 [docs/DEV-FLOW-ANALYSIS.md](docs/DEV-FLOW-ANALYSIS.md)。

### 7.5.4 变异测试（验证测试真的有效）

**改动依赖外部行为时（框架版本、数据库语义、第三方 API），写实测脚本验一遍，
别只读源码**——而且**实测的结论必须覆盖到 docstring 和 commit message**。

**2026-11-09 起工具化**：清单在 `apps/api/tests/mutations.yaml`，跑
`uv run python -m tests.mutation`（可加 id 只跑指定几条）。它会区分
「测试跑了但全绿」（测试是废的）与「测试根本没跑」（变异太粗暴，把代码
改到无法导入）——混为一谈会给出假阳性。

| 变异 | 失败数 | 说明 |
|---|---|---|
| 引用编号不续编 | 10 | 只有测试能守住这类不变量 |
| 去掉私域过滤 | 5 | 数据泄露防线 |
| 证据块截断为 excerpt | 1 | — |
| 补偿不复位 chunk_count | 1 | 2026-10-13 补 |
| 补偿越界清空他人索引 | 1 | 2026-10-13 补 |
| 两 source 隔离 | 1 | 2026-10-13 补 |
| 节点耗时不算累计 | 1 | 2026-11-09 加 |
| 节点完成帧不带产出摘要 | 1 | 2026-11-09 加 |
| Analyst 降级时说「未发现矛盾」 | 1 | 2026-11-09 加 |
| Supervisor 取消时不发 done | 1 | 2026-11-09 加 |
| 公开来源漏传 session_maker | 1 | 2026-11-09 加 |
| 畸形 URL 让整批失败 | 1 | 2026-11-09 加 |
| 证据块丢掉 URL | 1 | 2026-11-09 加 |
| 落库用短摘要而非原文 | 1 | 2026-11-09 加 |

**测不出来就别硬凑**：`test_compensation_rolls_back_before_touching_db` 写了又删——
它断言「rollback 被调用过」，而把 rollback 挪进 try 里同样会被调用，测试通过却
证明不了想证明的事。留下一个骗自己的测试比没有测试更糟。

## 7.6 文档与注释：写下 ≠ 核实过

**规则本身在全局 `~/.claude/rules/coding.md`「注释与文档：不许编造事实」**
（判据、核实成本三档、「什么时候不要写理由」都在那里），本节不重复。

**本项目的两次踩坑（实证）**：

- 2026-10-15 审计 WORKLOG 的「已知问题」表，四条里**三条是假的**——一条引用了
  项目文档里根本不存在��约定，一条把有意设计当成缺陷，一条描述的问题三周前
  就修好并验证过了
- 2026-10-13 CR 发现 `UtcDateTime` 的 docstring 写着「SQLite 存的是本机时区，
  历史数据需 UPDATE 修正」——实测 SQLite 的 `CURRENT_TIMESTAMP` **就是 UTC**。
  照那条补救指引操作会把所有历史时间戳平移一个时区偏移，**把正确的数据改坏**

**一个错误的技术断言留在文档里，比没有文档更危险。**

## 8. 设计 token 使用

完整 token 速查表见 [apps/web/CONTRIBUTING.md §7 设计 token](./apps/web/CONTRIBUTING.md)。

**关键速记**：

- 颜色：`bg-surface-container / bg-primary / text-on-surface / text-primary / bg-error-container`
- 字体：`font-headline-xl / font-body-md / font-code`
- 字号：`text-headline-xl / text-body-sm / text-code`
- 圆角：`rounded-lg`（默认）/ `rounded-full`（圆形按钮）
- 阴影：`shadow-sm`（卡片默认）

## 10. 协作约定

项目特有的部分：

- **shadcn/ui 组件**通过 `pnpm dlx shadcn@latest add button card ...` 装包到
  `apps/web/components/ui/`——所有新功能优先用这些组件，不要重新发明
- **调研不超过 5 个回合**——超过就停下来问用户

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

- [`apps/web/CONTRIBUTING.md §15`](./apps/web/CONTRIBUTING.md) — 前端配置文件作用
- [`apps/api/CONTRIBUTING.md §12`](./apps/api/CONTRIBUTING.md) — 后端 6 个配置文件作用

## 13. 图标来源规则（design 一致性）

1. **图标源**：Google `Material Symbols Outlined`，**本地 woff2**
   （`apps/web/public/fonts/material-symbols-outlined.woff2`，在 `globals.css` 里
   `@font-face` 声明为 `Material Symbols Outlined Local`）——0 新依赖，无 CDN 请求。
2. **优先用 design/code.html 里的**——每个 icon name 必须能在
   `argus设计稿/argus_*/code.html` 找到，不允许自己写 SVG / 字符 emoji /
   lucide-react / react-icons 替代。
3. **唯一封装组件**：`components/common/IconSpan`
   ```tsx
   <IconSpan name="icon_name" size={16} />
   ```
   **强制 inline `style={{ fontSize }}`** —— Tailwind v3 的 `text-[Npx]` arbitrary
   value 在 route group 路径下不可靠，会落回 24px。
4. **size 档位**：`13 / 14 / 15 / 16 / 18 / 20 / 22 / 24` 像素
   （`IconSpan` 的 `IconSize` 类型已约束）
5. **禁止**：自定义 SVG icon / emoji / lucide-react / react-icons（与
   precision_technical_light token 不兼容）。

## 14. 设计稿还原工作流（html → React）

**触发场景**：还原 `argus设计稿/argus_*/code.html` 到 React 组件（登录页 /
dashboard / 设置页等任意页面）。

**核心原则**：把 design code.html 当成**视觉契约**——布局 / 文案 / 颜色 / 间距 /
字号 / icon 都要 1:1 对齐；但**实现方式用 Next.js + Tailwind build-time**，
不是 design 的 CDN tailwindcss。

> 设计稿源文件**不在仓内**（`design-argus-3.html` / `design_argus_3_code.html` 已删）。

### 流程（4 步）

1. **定位设计稿**：`argus设计稿/argus_*/code.html`（每个 `argus_*` 子目录对应一个
   页面 / 状态变体）。找法：`title` / `<h1>` / 唯一关键词（"登录" / "Dashboard" 等）
   匹配到具体子目录。验证：`code.html` + `screen.png` + `code.html` 末尾 `<script>`
   三件套齐全才算完整设计稿。
2. **读 code.html 全量**：用 Read 工具分批读（90-130 行 / 批），避免单次 Read 爆
   context。不要用 python regex 抽——HTML 结构复杂，regex 容易挂；直接 Read +
   grep 关键 token 即可。
3. **写 React 组件**：
   - **token**：用 `tailwind.config.ts` 的 50 color + 11 fontFamily，不要复制 design
     的 inline `tailwind.config` JS。
   - **shadcn 组件**：复用 `apps/web/components/ui/{button,card,input,label}`
     （已重写干净，0 oklch 残留）。
   - **暗色硬编码**（`#0e1017` / `#16191f` 等）：保留 inline
     `style={{ background: "#0e1017" }}`（W1 spec "must stay inline"）。
   - **placeholder / 文案**：必须 1:1 对齐 design（`name@company.com` /
     `acme-corp` / `.argus.internal` 等）。
   - **icon**：用 `<IconSpan name="..." />`（参见 §13）。
4. **人工验证**：代码改完即返回，**统一人工浏览器目测**（不走 playwright / curl /
   screenshot / console 检查 / lint / tsc）。设计稿还原流程以用户的浏览器判断为
   唯一标准。

### 反模式（不要做）

- 复制 design 的 `<script src="cdn.tailwindcss.com">` → Next.js 用 build-time
  tailwind，不支持 CDN 模式
- 用 design 的 inline `tailwind.config = {...}` → 设计 token 已在
  `tailwind.config.ts`，不要重复定义
- 用 `bg-oklch(...)` 等任意值类名 → Tailwind v3 不解析，必须用设计 token
- 跳过 placeholder / 文案 1:1 对齐 → user 会立刻发现"和设计稿不一样"
- 改后自己起 playwright / curl / screenshot 验证 → 项目统一人工验证，agent 不要自动跑

### 已知差异处理表

| design 用                                   | Next.js 改用                                    | 原因                                         |
| ------------------------------------------- | ----------------------------------------------- | -------------------------------------------- |
| `bg-[#16191f]`                              | `bg-[#16191f]` 或 `bg-on-surface`               | inline 颜色允许；或用 token                  |
| `font-family: Geist` (CDN)                  | `font-headline-md` 等                           | tailwind.config.ts 已映射                    |
| `font-mono`                                 | `font-code`                                     | 设计 token 的 fontFamily 命名                  |
| `<details open>` 折叠                       | React `useState` + `cn(..., !open && "hidden")` | 设计稿用 vanilla JS，React 用 state          |
| vanilla `keydown` 监听器                    | `useEffect` + `window.addEventListener`         | 同上                                         |
| `document.getElementById(...)` 直接操作 DOM | 保留——快捷键反馈是合法的 DOM 操作场景           | keydown listener 200ms add/remove class 反馈 |

## 16. 组件开发规范与设计还原

### 16.1 文件夹形式封装组件（强制）

每个组件一个文件夹，**PascalCase**（B 必须大写：`Button.tsx` 不是 `button.tsx`），
文件夹内固定两文件：

- `index.tsx`（组件实现）
- `index.module.css`（CSS Modules，样式代码**不嵌套**——见 §16.2）

按用途分三类落位：

| 类型                   | 路径                                                       | 示例                                 |
| ---------------------- | ---------------------------------------------------------- | ------------------------------------ |
| 公共组件（跨页复用）   | `apps/web/components/common/<Name>/`                       | `common/ArgusMark/`                  |
| 页面组件（仅本页面用） | `apps/web/app/(auth)/<page>/components/<Name>/`            | `(auth)/login/components/LoginForm/` |
| shadcn UI              | `apps/web/components/ui/<Name>.tsx`（**单文件，无 css**） | `ui/Button.tsx`                      |

### 16.2 CSS Modules 样式策略

- **项目用 `.module.css` 而非 `.module.less`**（Next.js 15 改用方案，2026-09-22 落地）
- 原因：Next.js 15 不内置 `.module.less`（Vercel 官方支持矩阵：Less 标
  "Planned via plugins / Not yet supported by default"），手动配 `less-loader` +
  `css-loader` + fix-loader 仍存在 css 文本丢失、className 注入等问题；改用
  `.module.css` 是 next 内置方案，零配置
- 文件命名：`index.module.css`（与原 `.module.less` 同位置，命名仅改扩展名）
- 写法：纯 CSS 标准语法（**不支持** Less 的 `&` 父选择器嵌套；嵌套规则必须展开为
  完整 css selector）
- 颜色统一用 CSS 变量 `var(--token-xxx, #fallback)`，fallback 取
  `tailwind.config.ts` 的 token 原色
- `globals.css` 只放全局 token（@font-face / Material Symbols base /
  `.tech-grid-pattern` / `.tech-dot-pattern`），**不放任何组件样式**
- 全局类型声明见 `apps/web/globals.d.ts`：`declare module "*.module.css"` 用
  `export default classes`
- 组件 import：`import styles from "./X.module.css"`（默认导入，next 内置 css-loader
  自动支持）
- `apps/web/next.config.js` 无需任何 webpack rule，base 版本即可

### 16.3 shadcn 优先

- 新功能优先用 `apps/web/components/ui/{Button, Card, Input, Label, Badge, Separator}`
- 不要重新发明已有 shadcn 组件
- shadcn 默认 OKLCH 配色 → 必须在 `components.json` 设 `baseColor: "custom"` +
  `cssVariables: true`，替换为项目设计 token

### 16.4 图标规则（§13 固化）

- 唯一来源：Google `Material Symbols Outlined`（本地 woff2，见 §13）
- 唯一封装组件：`components/common/IconSpan`
- **强制 inline `style={{ fontSize }}`** —— Tailwind v3 的 `text-[Npx]` arbitrary
  value 在 route group 路径下不可靠，会落回 24px
- size 档位：`13 / 14 / 15 / 16 / 18 / 20 / 22 / 24` 像素
- 禁止：自定义 SVG / emoji / lucide-react / react-icons

### 16.6 主题色（dual theme）

- 项目支持亮色 + 深色两主题
- `argus_2` 是深色（`<html class="dark">`），`argus_1` / `argus_3` /
  `argus_dashboard` 等为亮色
- 缺失的对应主题可在 design 模式二次设计补全
- 当前登录页（`argus_3`）只实现亮色 Material 3 风

### 16.7 反模式

- ❌ 复制 design 的 `<script src="cdn.tailwindcss.com">`
- ❌ 复制 design 的 inline `tailwind.config = {...}`
- ❌ 改用 `bg-oklch(...)` → 与项目设计 token 不兼容
- ❌ `material-symbols-outlined` 只用 `text-[Npx]` className，没有 inline
  `style={{ fontSize }}` → 落回 24px（走 `IconSpan` 组件）
- ❌ 改多处重复 className 时不先 grep 计数 → 用 `replace_all: true` 或更具体上下文
- ❌ 压扁 template-string `<span className={\`...\`}>` 成单行 → JSX 闭合错乱，build error
- ❌ 自己起 playwright / curl / screenshot **验证设计稿还原程度** → 那是人类美学判断
- 🔧 修复运行 bug 时 agent 可以用浏览器 MCP（chrome-devtools / playwright）介入——抓
  console error、看页面渲染异常、对照 network panel 排查请求失败
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

规则光写文档会烂。`apps/web/eslint.config.mjs` 已配好
`react-hooks/exhaustive-deps: error`，`pnpm --filter web lint` 会真实拦截。
**改动后必须跑一遍。**

配置踩过的坑别重复踩：Next 16 已废弃 `next lint`（它把 `lint` 当目录名 → lint
从未真正跑过），必须用 `eslint` CLI 直接跑；`eslint .` 在 pnpm workspace 里会把
`apps/api/.venv` 的第三方 JS 全扫进来（7 万条噪音），要显式写目录
`eslint app components lib`。

#### React Compiler 一旦启用，本节作废

Compiler 会自动做记忆化，届时 `useCallback` / `useMemo` 大部分不再需要。
启用 Compiler 的同时必须回改本节，否则规则会误导。

---

- [apps/web/CONTRIBUTING.md](./apps/web/CONTRIBUTING.md)
- [apps/api/CONTRIBUTING.md](./apps/api/CONTRIBUTING.md)
- [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)
- [docs/CODE-QUALITY.md](./docs/CODE-QUALITY.md)
- [docs/DEV-FLOW-ANALYSIS.md](./docs/DEV-FLOW-ANALYSIS.md)
- [prd/PRD 总览](./prd/README.md)
