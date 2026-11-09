# CODE-QUALITY.md — Argus 前后端代码质量控制规范

> 本文档独立于 [CONVENTIONS.md](./CONVENTIONS.md)——只谈**工具链 + 自动化拦截**，
> 不谈命名 / 嵌套 / 状态等代码风格（那些在 CONVENTIONS.md）。

## 1. 设计目标

1. **所有提交必须通过本地自动化检查**（pre-commit）—— 不通过则 commit 被拒
2. **所有 commit message 必须遵守 Conventional Commits** —— commitlint 校验
3. **CI 跑完整 lint + typecheck + test** —— 三个工作流并行
4. **前后端规则对仗** —— 前端 ESLint，后端 ruff；前端 TypeScript strict，后端 mypy strict

## 2. 前端（apps/web/）

### 2.1 工具链一览

| 工具 | 版本 | 配置 | 作用 |
|---|---|---|---|
| ESLint | 9.x（flat config） | `eslint.config.mjs` | 代码静态检查 |
| eslint-config-next | 16.3.7 | 同上 | Next.js 规则（含 react-hooks） |
| typescript-eslint | 8.71.1 | 同上 | TypeScript 类型感知规则 |
| Prettier | 3.3 | 无配置文件（用默认值；只有 `.prettierignore`） | 格式化 |
| prettier-plugin-tailwindcss | 0.6 | — | class 排序（未在配置中启用） |
| Husky | 9.1.7 | `.husky/` | git hook |
| lint-staged | 17.6.0 | 无配置 | **未启用**——`.lintstagedrc.json` 已删（它一直是死配置：没有任何 hook 调用它）。依赖仍留在 package.json 里备用 |
| commitlint | 21.2.3 | `commitlint.config.mjs` | commit message 校验 |
| TypeScript | 5.6 | `tsconfig.json` | 类型检查 |

### 2.2 提交前拦截链路

```
$ git commit
→ .husky/pre-commit
   ├─ 前端（总是跑）：pnpm run lint + pnpm exec tsc --noEmit
   └─ 后端（仅当 staged 里有 apps/api/*）：ruff check app/ tests/ + mypy app/
→ .husky/commit-msg 跑 commitlint --edit "$1"
   不通过 → commit 拒绝
```

**没有 lint-staged**——pre-commit 直接对全工程跑 eslint + tsc。
`.lintstagedrc.json` 已删（它是死配置：没有任何 hook 调用它）。

### 2.3 npm scripts（package.json）

| 命令 | 作用 |
|---|---|
| `pnpm dev` | 起 Next.js dev server（`--webpack`） |
| `pnpm dev:turbopack` | 起 dev server（Turbopack） |
| `pnpm build` | production 构建 |
| `pnpm start` | 跑 production 服务 |
| `pnpm lint` | `eslint app components lib` |
| `pnpm format` | prettier --write |
| `pnpm format:check` | prettier --check（CI 用） |
| `pnpm clean` | 删 `.next` / `.turbo` |
| `pnpm prepare` | husky install（自动） |

**没有** `lint:fix`、**没有** `typecheck`。类型检查要写
`pnpm exec tsc --noEmit`——`pnpm tsc --noEmit` 是空命令（package.json 里没有
`tsc` script），它会打印「None of the selected packages has a "tsc" script」
然后**退出码 0**，什么都没跑。

`pnpm lint` 里也**没有** `--max-warnings=0`。

### 2.4 本机安装

```bash
cd /Users/zjp/Desktop/argus
pnpm install                    # 装 devDeps
pnpm dlx shadcn@latest init     # 建 components.json + lib/utils.ts
pnpm dlx shadcn@latest add button card input label  # 装首批组件
pnpm exec tsc --noEmit          # 验类型（必须带 exec）
pnpm lint                       # 验 ESLint
```

### 2.5 工具拦不住的坑（2026-10-19 补）

以下三类问题 lint / tsc / build **全绿**，只有肉眼或运行时能发现。
每条都是本项目实际踩过的。

#### CSS Modules 引用了不存在的类 → 样式静默失效

```tsx
<span className={styles.empty} />   // css 里没有 .empty
```

CSS Modules 把未定义的类解析成 `undefined`，模板字符串拼成字面量
`"undefined"` 的 class 名，**不报错、样式不生效**。

```bash
# 单文件核对（推荐）：左边 < 是「用了但没定义」，右边 > 是「定义了没人用」
diff <(grep -ohE "styles\.[A-Za-z_]+" index.tsx | sed 's/styles\.//' | sort -u) \
     <(grep -ohE "^\.[A-Za-z_]+" index.module.css | sed 's/^\.//' | sort -u)
```

**必须逐文件跑**，不要全仓 diff——CSS 类可以跨文件复用
（`TableCells/cells.module.css` 的类被多个组件 import），全仓比对会把
「A 文件定义、B 文件引用」误报成缺失或死类。

改了 `index.module.css` 后必须跑一遍。**同时清理死类**——删掉 UI 组件后
对应的样式没人引用，属于纯负担（2026-10-19 在 add-sources 一次清掉 59 个）。

#### `useSearchParams` 必须包在 Suspense 里

哪怕调用方是 Server Component 也不行：只要**该路由会被静态预渲染**，
`next build` 就以 `missing-suspense-with-csr-bailout` 失败。

实测踩过：`(dashboard)/layout.tsx` 里的守卫用了 `useSearchParams`，
`/error-404` 预渲染直接挂掉。

替代方案（当只想读 `pathname` 时）：`usePathname()` 不需要 Suspense。

#### prettier 会在 `cd` 进子目录后作用于整个仓库

```bash
cd apps/web/app/xxx && prettier --write .   # ❌ 把整个仓库都格式化了
```

实测一次误格式化 61 个无关文件（1960 增 / 1437 删，内容零变化），
`git checkout --` 回滚。**必须传显式文件列表**：

```bash
prettier --write "app/(dashboard)/layout.tsx" lib/auth/UserContext.tsx
```

## 3. 后端（apps/api/）

### 3.1 工具链一览

| 工具 | 版本 | 配置 | 作用 |
|---|---|---|---|
| Python | 3.12+ | `.python-version` | 运行时 |
| uv | 0.4+ | — | 包管理（替代 pip + poetry） |
| FastAPI | 0.141+ | `app/main.py` | web framework |
| Pydantic | 2.10+ | 散落在 model 文件 | 数据验证 |
| SQLAlchemy | 2.0.36+ | `app/db/` | ORM（async） |
| asyncpg | 0.30+ | — | Postgres async driver |
| Alembic | 1.13+ | `alembic/` | 数据库 migration |
| Redis | 5.2+ | — | LangGraph checkpointer |
| LangGraph | 1.2.11+ | `app/agents/` | 多智能体状态机 |
| ruff | 0.7+ | `pyproject.toml` [tool.ruff] | linter + formatter（替代 flake8+isort+black） |
| mypy | 1.13+ | `pyproject.toml` [tool.mypy] | 静态类型检查（strict 模式） |
| pytest | 8.3+ | `pyproject.toml` [tool.pytest.ini_options] | 测试 |
| pytest-asyncio | 0.24+ | 同上 | 异步测试 |
| pytest-cov | 5.0+ | 同上 | 覆盖率（fail_under = 80%） |
| pre-commit | 4.0+ | `.pre-commit-config.yaml` | git hook |

### 3.2 ruff 规则集（pyproject.toml）

`select = ["E", "F", "W", "I", "B", "UP", "SIM", "PT", "C4", "RUF", "ASYNC"]`

| 规则 | 来源 | 作用 |
|---|---|---|
| E / W | pycodestyle | PEP 8 风格 |
| F | pyflakes | 未使用 import / 变量 |
| I | isort | import 排序 |
| B | bugbear | 常见 bug |
| UP | pyupgrade | Python 3.12+ 语法升级 |
| SIM | simplify | 代码简化 |
| PT | pytest | pytest 风格 |
| C4 | comprehensions | 列表推导式 |
| RUF | ruff-specific | ruff 特定规则 |
| ASYNC | flake8-async | async/await 检查 |

`ignore = ["E501", "B008"]` —— E501 行长交给 ruff format 处理；B008 函数默认参数调用（FastAPI Depends 模式需要）

### 3.3 mypy strict 模式（pyproject.toml）

```toml
strict = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
strict_equality = true
strict_concatenate = true
```

`tests/*` 排除 `disallow_untyped_defs` —— 测试 fixture 灵活。

### 3.4 提交前拦截链路

```
$ git commit
→ pre-commit hooks:
   ├─ trailing-whitespace / end-of-file-fixer
   ├─ check-yaml / check-toml
   ├─ check-added-large-files (max 512KB)
   ├─ detect-private-key
   ├─ no-commit-to-branch (main / master)
   ├─ ruff --fix
   ├─ ruff-format
   ├─ mypy --config-file=pyproject.toml
   └─ pytest smoke tests
→ commitlint 校验 commit message
   不通过 → commit 拒绝
```

### 3.5 npm scripts 没有，pyproject.toml 提供

| 命令 | 作用 |
|---|---|
| `uv sync` | 装所有 deps（含 dev） |
| `uv run pytest` | 跑测试 |
| `uv run pytest --cov` | 跑覆盖率 |
| `uv run mypy app/` | 类型检查 |
| `uv run ruff check .` | lint |
| `uv run ruff format .` | 格式化 |
| `uv run pre-commit run --all-files` | 跑全部 hook |

### 3.6 本机安装

```bash
cd /Users/zjp/Desktop/argus/apps/api
uv sync                # 装所有 deps（含 dev）
uv run pre-commit install   # 装 pre-commit
uv run pytest         # 跑烟测
uv run mypy app/      # 类型检查
uv run ruff check .   # lint
```

## 4. commit message 规范（前后端共用）

### 4.1 Conventional Commits 格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

### 4.2 type-enum（11 个）

| type | 用途 |
|---|---|
| feat | 新功能 |
| fix | bug 修复 |
| docs | 文档变更 |
| style | 格式（不改代码逻辑） |
| refactor | 重构（既不是 feat 也不是 fix） |
| perf | 性能优化 |
| test | 测试 |
| build | 构建系统 |
| ci | CI 配置 |
| chore | 其他 |
| revert | 回滚 |

### 4.3 scope（可选）

`scope-enum` 规则**已关闭**（`apps/web/commitlint.config.mjs` 里 `'scope-enum': [0]`），
所以 `feat: xxx` 这种不带 scope 的写法合法。

项目实际用法是 `api` / `web` / `api,web`（如 `feat(api,web): ...`）。
`commitlint-plugin-workspace-scopes` **没有安装**——不要按
`apps/web` / `packages/shared` 那种枚举去校验。

### 4.4 header-max-length

**100 字符**（`commitlint.config.mjs` 实配 `header-max-length: [2, 'always', 100]`）。
body / footer 100 字符/行（`body-max-line-length` 已关闭为 `[0]`，不强制）。

### 4.5 breaking change 标记

`feat!:` 或 footer `BREAKING CHANGE:` —— 强制升级 major version。

## 5. CI（GitHub Actions）

待 W2 启用 .github/workflows/ 时配：

| workflow | 触发 | 跑啥 |
|---|---|---|
| `web-lint.yml` | PR to main | pnpm install + lint + format:check + typecheck |
| `web-test.yml` | PR to main | pnpm install + vitest run |
| `api-lint.yml` | PR to main | uv sync + ruff + mypy |
| `api-test.yml` | PR to main | uv sync + pytest --cov |
| `e2e.yml` | PR to main（label: e2e） | playwright install + playwright test |

## 6. 异常处理

- **临时跳过 hook**：`git commit --no-verify`（仅紧急 hotfix 用，PR review 必须看 why）
- **单个文件 ruff 跳过**：`# noqa: E501`（带具体规则名）
- **mypy 跳过**：`# type: ignore[import-untyped]`（带具体 error code）

## 7. 与本项目其他文档的关系

- [CONVENTIONS.md](./CONVENTIONS.md) — 代码风格与设计约定
- [apps/web/CONTRIBUTING.md](../apps/web/CONTRIBUTING.md) — 前端开发流程
- [apps/api/CONTRIBUTING.md](../apps/api/CONTRIBUTING.md) — 后端开发流程
- [prd/tech-stack.md](../prd/tech-stack.md) — 技术栈锁定版本
- [AGENTS.md](../AGENTS.md) — 项目 AI agent 协作指南
