# 代码质量：规则失效根因（已实测定位）+ 工具方案调研进度

> 2026-11-24 立。用户诉求：**「这类问题在写的时候就需要解决的，不知道为什么设定的规则无法生效。先研究这个规则问题……研究下使用什么工具或者 skill 可以提升我们写代码的质量，不限于 react、ts、py、sql 等——我们目前使用的所有语言都要处理代码质量问题」**
>
> 本文件是**工作台账**：记录已实测的根因、已完成的调研、下一步待办。
> 结论优先给证据，标 `[实测]` / `[查证]` / `[未核实]` 区分证据强度。

---

## 一、根因：不是「规则没加载」，是「规则形态不对」

### 1.1 结论（推翻此前判断）

此前 memory 里记的诊断是**「规则只写在 AGENTS.md 里，不在加载路径上，所以对模型无效」**——
**这个诊断是错的，已实测推翻**。

`[实测]` 证据链（会话 jsonl：`~/.claude/projects/-Users-zzc-z-argus/c87df605-7ca6-4db7-9fe1-25c12ba771cc.jsonl`）：

| 时刻 | 事件 | 证据 |
|---|---|---|
| 13:16:04 | `.claude/rules/web.md` **完整文本**（含 W4）进入 API 请求载荷 | line 61 的 `api-request-blob`，message.content 第 5 项，len=4113，含「## W4. Hook：默认不包 `useCallback` / `useMemo`」整段 |
| 13:29:21 | 我 `Edit` 写入 `CredentialsPanel/index.tsx`，**引入 `useCallback`** | line 320，tool_use 输入含 `useCallback` |
| 13:34:43 / 13:40:17 | 继续在 `useCredentials.ts` 引入 `useCallback` | line 569 / 677 |

即：**规则在写代码前 13 分钟就已经在 context 里，规则完整、位置正确、无压缩打断**
（本 session 唯一的 compact_boundary 在 line 5059，远晚于上述时刻）。

**所以「规则没加载」不成立。真正的原因在下面。**

### 1.2 真正的根因：规则是「散落在长文档里的一句话」，不是「可执行的判据」

`[实测]` W4 的实际文本形态：

```
## W4. Hook：默认不包 `useCallback` / `useMemo`

**argus 现状**：React 19.3 + **React Compiler 未启用**，全项目 `React.memo` 0 处。

通用判据见全局 `~/.claude/rules/cr-react.md`（...）。
argus 特有的**白包形态**：

- **空函数 `useCallback(() => {}, [])`** —— 零收益纯噪音
- **单纯「怕子组件重渲染」但子组件没 memo** —— 白包
- 函数体内没读响应式值，deps 却写满 —— 本来就不会变
- 「以防万一」预包 —— YAGNI

**这四种之外仍可包**：
- 函数传给 `React.memo` 子组件 / 第三方 `memo()` 组件
- 函数是 `useEffect` / `useMemo` 的依赖，且闭包里有 state/props
```

对照我实际写的代码：

```tsx
const handleCredentialsSaved = React.useCallback(() => {
  setToast({ message: '配置已保存', tone: 'success' })
  reloadCredentials()
  reload()
}, [reloadCredentials, reload])
```

**逐条比对 W4 的四种白包形态**：
- 不是空函数 ❌
- 不是「怕子组件重渲染」 ❌
- 函数体没读响应式值？——**读了**（`reloadCredentials`、`reload` 都是 state/函数），
  deps 也写满了 ❌
- 不是「以防万一」预包 ❌

**它落在 W4 说的「这四种之外仍可包」的第二个例外里**：
「函数是 `useEffect` / `useMemo` 的依赖，且闭包里有 state/props」。

**而这个例外——恰恰是错的。** `handleCredentialsSaved` 传给的是
`<CredentialsPanel onSaved={...}>`，**CredentialsPanel 没有 `React.memo`**（全项目 `React.memo` 0 处，
W4 自己也写了这一点）。它不是任何 Hook 的依赖。React 官方对 `useCallback` 的判据是
**「传给 memo 组件」或「作为某 Hook 的依赖」**——两个都不满足。

### 1.3 所以真正的机制是这三条

| # | 机制 | 说明 |
|---|---|---|
| 1 | **规则文本有歧义，模型按「合理化」方向解释** | W4 写「这四种之外仍可包」，我写的东西不在四种之内 → 读起来像「不在禁止列表里就是允许」。**禁止列表 + 例外列表 = 空白区** |
| 2 | **规则没有「判定步骤」，只有「结论 + 案例」** | W4 给的是 4 个坏形态 + 2 个好形态，**没给判定流程**。模型要判断「这个函数是 memo 组件的 prop 吗」得自己跨组件读代码，而 W4 就在同一句里说「全项目 `React.memo` 0 处」——这个事实本该直接推出「不许包」，但规则没把它写成判据 |
| 3 | **W4 在一个 4000 字的「审查规则」文件里，位置靠中段** | `.claude/rules/web.md` 是**审查视角**的规则文件（标题「argus · 前端审查规则」），W4 混在里面。它在 13:16 一次性与另外 5 个规则文件一起作为「system-reminder 文本块」塞进消息历史——**长文档中的单条规则，注意力权重远低于短文件里的强规则** |

### 1.4 关键旁证：我自己「引用了规则，却违反了它」

`[实测]` 在 `CredentialsPanel/index.tsx` 里我写的注释：

```
// 用 useMemo：每次渲染新建对象的话，handleSave 的依赖每次都变——
// 那个 useCallback 就永远重建（web.md W4：没启 React Compiler 时
// 依赖不稳的白包反而制造问题）。
```

**注释引用了 W4，代码却违反 W4。** 这说明问题不是「没看到规则」，
而是**规则被当成「解释性知识」而非「判定步骤」**——引用它来论证某个写法，
恰恰说明它是**可选的论证素材**，不是**必须满足的约束**。

### 1.5 结论 → 修法方向

| 诊断 | 对应修法 |
|---|---|
| 禁止列表 + 例外列表留空白 | 改成**闭合判定**：「满足以下任一条件才允许出现 useCallback，否则禁止」 |
| 只给结论不给判定步骤 | 规则写成**可执行的检查步骤**（先问 A，是→查 B……） |
| 混在长审查文件里权重低 | 拆成**独立的短规则文件**，直接对应「写代码时的约束」层（`gen-*`） |
| 靠模型自觉遵守 | 加**机器门禁**：能自动查的交给 lint / 编译器，不靠规则文本 |

**最重要的一条**：**官方 React 工具链查不出「不必要 useCallback」**（见 §2 调研结论），
所以这件事**不能只靠规则文本**——必须靠**改写代码 + CR 判据 +（未来）React Compiler**。

---

## 二、工具方案调研（已完成 1/4，其余 3 个已中止待续）

### 2.1 前端（TS/React）——已完成

> 完整报告见本会话 agent `a1f7b141f606666e8` 的输出。要点：

**关键发现**

| 结论 | 依据 |
|---|---|
| **React 官方 ESLint 插件查不出「不必要的 useMemo/useCallback」** | `react-hooks/use-memo` 只查「useMemo 无返回值」；`preserve-manual-memoization` 查的是「依赖不全」，**方向相反**。react.dev 规则全集 18 条，无一条查「这个 memo 没必要」 |
| React Compiler lint **已并入 `eslint-plugin-react-hooks` v7**，`eslint-plugin-react-compiler` 已废弃 | react.dev/blog/2025/10/07/react-compiler-1 |
| 第三方 `eslint-react` 有 `no-unnecessary-use-callback`，但**官方自述「实验性，不建议用于生产」**，且判据只是「依赖数组为空」 | eslint-react.xyz |
| **`eslint-config-next`（Next 16.3）已间接装了 react-hooks v7** —— 开 `reactHooks.configs.flat.recommended` 是**零新增依赖** | ⚠️ 该项**未实测**：本机 `apps/web/node_modules/eslint-plugin-react-hooks` 目录不存在（pnpm 虚拟存储），落地前需 `pnpm ls eslint-plugin-react-hooks` 确认 |
| `tseslint.configs.recommendedTypeChecked` 值不值得开 | **值得，但分批**。它含 `no-floating-promises` / `no-misused-promises` / `no-unsafe-*`(8条)，与现有 `gen-typescript.md` G-T4/G-T5/G-T7 高度对应。`strictTypeChecked` **暂不采纳**（semver 不稳定 + 一次性炸几百处） |
| `projectService: true` 的坑 | **要求每个被 lint 的文件都在某个 tsconfig 的 `include` 里**，否则报 "tsconfig does not include this file"。本项目 `lint` 脚本是 `eslint app components lib`——需确认 `components/` 在 tsconfig include 内 |
| 死代码检测用 **knip**（ts-prune 上游已归档并推荐 knip） | knip.dev/explanations/comparison-and-migration。knip 内置 Next app router 入口识别 |
| **Next 16 的 `next build` 已不再跑 ESLint** | nextjs.org/docs/app/api-reference/config/eslint。**CI 必须显式跑 `pnpm lint`** |
| ESLint 10 现在**不能升** | `eslint-plugin-react@7.37.5` 只声明支持到 ESLint 9，ESLint 10 下崩 |

**建议采纳清单（前端）**

| 优先级 | 工具 / 规则 | 能查什么 | 接入 | 误报风险 |
|---|---|---|---|---|
| P0 | `reactHooks.configs.flat.recommended` | Rules of React 全套：render 期 setState / 改 props / 读写 ref / 组件重建 / 手动 memo 依赖不全 | ESLint 配置 | 低 |
| P0 | `react-hooks/unsupported-syntax` 提到 error | 标记「compiler 会静默跳过此组件」 | ESLint 配置 | 低 |
| P1 | `tseslint.configs.recommendedTypeChecked`（+ `projectService: true`） | no-floating-promises / no-misused-promises / no-unsafe-* | ESLint + CI | 中（首次量大） |
| P1 | strict 档单条：`no-non-null-assertion` / `only-throw-error` / `use-unknown-in-catch-callback-variable` | 禁 `!` / 禁 `throw 'str'` / catch 变量为 unknown | 逐条手动开 | 低 |
| P2 | knip | 未使用文件 / 导出 / 类型 / 依赖 / 循环依赖 | CI | 中 |
| P2 | eslint-plugin-perfectionist（**仅 sort-imports**） | import 排序 | ESLint | 低 |
| ❌ | `strictTypeChecked` 整包 / ts-prune / eslint-plugin-sonarjs 整包 / SonarQube / `@ianvs/prettier-plugin-sort-imports` | — | — | 见 agent 报告 |

**但注意**：以上全部**查不出「这个 useCallback 没必要」**。§1.5 的结论不变——
这一条只能靠**规则改写 + CR 判据 + 代码改写**。

### 2.2 Python —— **未完成**（agent 已中止）

要查的问题清单（agent 任务书原文，可直接复用）：

1. ruff 更严档：`select = ["ALL"]` 的噪音、官方推荐的生产配置
2. 新增规则组 `ANN` / `ARG` / `PL` / `PTH` / `TRY` / `S` / `PERF` / `DTZ` / `BLE` / `A` / `N` / `COM` / `ISC` / `FA` / `TD` / `FIX` / `ERA` —— 哪些与本项目技术栈（SQLAlchemy async / FastAPI Depends / Pydantic v2 / pytest / async-await）直接相关，哪些误报多
3. mypy 之外：pydantic mypy plugin、**pyright vs mypy strict** 的官方对比、SQLAlchemy 2.0 的 stub 现状
4. 死代码：vulture（含 whitelist 机制）、ruff F401 与它的分工
5. **变异测试：mutmut vs cosmic-ray**（哪个活跃、能否跑 asyncio 测试、官方对「变异测试能证明什么」的说明）
6. 复杂度度量：radon vs flake8 C901，业界是否还推荐
7. 依赖安全：pip-audit vs safety（safety 是否已停更）、ruff S 规则与安全扫描的分工
8. **SQL**：sqlfluff 支持的 dialect（sqlite 在不在）、能否 lint Python 里的 SQL 字符串；**SQLAlchemy 2.0 有没有官方的「防手写字符串拼接 SQL」检查手段**（`sqlalchemy.event` 监听编译后 SQL / `literal_binds` / Executable 编译钩子）

### 2.3 Claude Code 自动化门禁 —— **未完成**（agent 已中止）

1. 官方 hooks 事件全表：**PostToolUse 在 Edit|Write 后触发，能否拿到改动文件路径、能否跑 lint 并阻断**
2. hook 配置格式、匹配器写法、输入 JSON 字段、**输出怎么表达「阻断并让 Claude 重试」**
3. 官方 skill / plugin marketplace 里有没有现成的 lint / quality 插件
4. `AGENTS.md` vs `CLAUDE.md` vs `.claude/rules/` 的**官方加载语义**（`paths` frontmatter 是不是官方支持）
5. 能不能用 hook 触发 `/code-review`
6. 本机已有 hook 的写法参考（`~/.claude/hooks/instructions-loaded-log.mjs` 等 7 个）

### 2.4 变异测试与测试有效性 —— **未完成**（agent 已中止）

1. mutation testing 的原始定义与 mutants 分类（一手论文/官方文档）
2. mutmut vs cosmic-ray（活跃度、asyncio 适配）；Stryker（JS/TS）的 `--threshold` CI 门禁用法
3. **变异分数该不该当硬门禁**（业界反面意见）
4. 弱断言自动检测（pytest 有插件吗）
5. hypothesis 补哪类覆盖缺口
6. **覆盖率当门禁的批评**（coverage gaming）
7. pytest-randomly / `--collect-only`
8. AI 辅助开发时代「测试有效性」的官方指南（Anthropic / OpenAI / Copilot）
9. **最小可行实践**：一条命令、成本几十秒、结论落成清单文件

---

## 三、待办清单

### 3.1 立即可做（不依赖未完成的调研）

- [ ] **改写 `gen-react.md`**，把 W4 的「禁止列表 + 例外列表」改成**闭合判定**：
      「满足以下任一条件才允许出现 `useCallback` / `useMemo`，否则禁止」，
      并把 React 官方两条判据（传给 memo 组件 / 作为某 Hook 依赖）写成主判据，
      W4 的四种形态降级为「典型反例」。
      **依据**：react.dev/reference/react/useCallback + /useMemo（agent 已查证）
- [ ] **改写 `gen-react.md` 的 G-R7**：现在只说「依赖数组要诚实」，**没有一条说「不该包就别包」**
- [ ] **执行去白包改造**（改法已定，见 §4）
- [ ] **补齐 `gen-*.md`**：新增 SQL、CSS；每个补「不该用的东西不要用」类判据
- [ ] **修 `gen-typescript.md` 的 paths**：缺 `.js`/`.jsx`/`.mjs`/`.cjs`（与 `cr-typescript.md` 不一致）
      —— ⚠️ **实测复查**：`gen-typescript.md` 的 frontmatter **已经包含** `.js`/`.jsx`/`.mjs`/`.cjs`，
      **这条已修复**，memory 里的记录过时了
- [ ] **更新 memory**：`argus-code-quality-rules-not-effective.md` 的根因段是错的，要改写

### 3.2 等调研补完

- [ ] 完成 §2.2（Python）→ 出「Python 侧采纳清单」
- [ ] 完成 §2.3（Claude Code 门禁）→ 出「hook 自动跑 lint」方案
- [ ] 完成 §2.4（变异测试）→ 出「一条命令证明测试有效」方案
- [ ] 汇总成一份跨语言门禁矩阵，落到 `~/.claude/rules/gen-*.md` + 项目 CI

### 3.3 本次会话其它未收尾（与本议题无关但需要清账）

- [ ] **20 个文件未提交**（后端 9 改 + 3 新增，前端 6 改 + 1 新增目录）
- [ ] 开发库 `apps/api/argus.db` 的 `provider_credentials` 表有 3 行测试残留，
      用户需在终端跑：
      `cd apps/api && sqlite3 argus.db "DELETE FROM provider_credentials WHERE scope='user';"`

---

## 四、去白包改造（改法已定，React 官方依据已查证）

React 官方原文（agent 已查证，react.dev/reference/react/useCallback）：

> "Caching a function with `useCallback` is only valuable in a few cases:
> You pass it as a prop to a component wrapped in `memo`.
> The function you're passing is later used as a dependency of some Hook.
> **There is no benefit to wrapping a function in `useCallback` in other cases.**"

| 位置 | 改成 | 理由 |
|---|---|---|
| `page.tsx` 的 `handleCredentialsSaved` / `handleCredentialsReload` / `handleNothingChanged` / `handleSaveFailed` | 普通函数 | 非 memo 组件 prop、非 effect 依赖 |
| `page.tsx` 的 `providers` / `diagnostic` / `profile` 三个 useMemo | **保留** | 纯计算缓存，有实际开销 |
| `CredentialsPanel` 的 `currentUrls` / `maskedKeys` | 普通计算 | 同上 |
| `CredentialsPanel` 的 `handleChange` / `handleSave` | 普通函数 | 同上 |
| `useCredentials` 的 `state` useMemo | **保留** | 参与 currentUrls 计算 |
| `Toast` 的 `dismissRef` | **保留** | useRef 是「只想读不想触发重渲染」的正确工具 |

---

## 五、证据强度标注说明

- `[实测]` —— 本机跑过命令 / 读过文件 / 解析过会话 jsonl，结论可复现
- `[查证]` —— 有官方文档 URL 支撑（本文件 §2.1 的表格来自 agent 实访官方文档）
- `[未核实]` —— 推断或二手来源，**落地前必须自己确认**
