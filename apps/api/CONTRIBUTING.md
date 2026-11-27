# apps/api — 后端贡献指南

> 本文档描述的是**已落地**的实现。目录结构、环境要求与实际代码一致。

## 1. 环境要求

- **Python** ≥3.12 且 <3.15（实际用 **3.14**，由 `.python-version` 固定）
- **uv** ≥ 0.4（包管理）
- **无外部数据库**——用的是 SQLite（`apps/api/argus.db`）+ sqlite-vec 扩展，
  随 `uv sync` 装进虚拟表，不需要起 Postgres/Redis

**为什么卡 <3.15**：`ormsgpack`（`langgraph-checkpoint` 的传递依赖）目前只发到
**cp314** 的 wheel。3.15 上没有预编译轮子，`uv sync` 会回退源码编译，然后被
maturin / PyO3 拒绝（`PYO3_PYTHON=cpython-3.15` 编译失败）——**装依赖这一步
就炸**，不是运行时才炸。`pyproject.toml` 的 `requires-python` 因此写成
`>=3.12,<3.15`，避免允许一种装不上的环境。

`.python-version`（`3.14`）是真正决定本机与 CI 用哪个版本的地方——`uv sync`
不带 `--python` 时读它；CI 的 `setup-uv` 额外用 `python-version: "3.14"`
显式 pin 一遍（优先级高于 `.python-version`），防止 runner 默认版本漂移。

## 2. 安装

```bash
cd apps/api
uv sync        # 装 pyproject.toml 列出的依赖（自动按 .python-version 选 Python）
uv run pre-commit install   # 装 pre-commit
```

## 3. 目录结构

```
apps/api/
├── app/                              # 主代码包
│   ├── main.py                       # FastAPI app factory
│   ├── config.py                     # pydantic-settings 配置
│   ├── db.py                         # engine + sessionmaker
│   ├── security.py                   # JWT / 密码哈希
│   ├── gateway/                      # HTTP 路由层
│   │   ├── auth.py  dashboard.py  deps.py  health.py
│   │   ├── reports.py  research.py  sources.py  users.py
│   ├── models/                       # SQLAlchemy ORM
│   │   ├── base.py  report.py  source.py  user.py
│   ├── schemas/                      # Pydantic 请求/响应模型
│   │   ├── dashboard.py  health.py  report.py  research.py  source.py  user.py
│   ├── services/                     # 业务逻辑层（34 个模块）
│   │   ├── agent.py                  # 多智能体主循环（手写，不用 LangGraph）
│   │   ├── agent_nodes.py            # Stage 枚举 + NodeTracker 生命周期
│   │   ├── agent_turn.py             # 单轮请求：拼请求 / 发流式 / 收结果
│   │   ├── agent_tools.py            # 工具执行与检索上下文
│   │   ├── agent_ledger.py           # TurnLedger（用量与产出记账）
│   │   ├── agent_failures.py  stages.py  persistence.py
│   │   ├── llm.py                    # Anthropic / Tavily 客户端
│   │   ├── errors.py errors_base.py errors_tavily.py   # 错误分类
│   │   ├── stream.py                 # SSE 事件契约
│   │   ├── retriever.py bm25.py embedder.py vectorstore.py
│   │   ├── ingest.py parser.py fetcher.py chunker.py storage.py
│   │   ├── web_sources.py urls.py
│   │   ├── citation.py faithfulness.py
│   │   ├── runs.py tasks.py auth.py token.py tools.py
├── alembic/                          # 数据库 migration
├── eval/                             # agent 评测
│   ├── calibrate_judge.py            # judge 一致率校准（TPR / TNR / Cohen's κ）
│   ├── golden.py  datasets/golden_v1.jsonl
│   ├── injection_probe.py            # prompt 注入对照实验
│   └── reports/                      # 校准与注入探测结果
├── tests/                            # pytest（48 个文件）
│   ├── conftest.py
│   └── ...
├── scripts/dev_login.py              # 本地造 session（绕过 GitHub OAuth）
├── uploads/                          # 摄取的原文件落地目录
├── pyproject.toml                    # uv + ruff + mypy + pytest
├── .ruff.toml                        # ruff 独立配置（保留供 pre-commit 单独跑 ruff）
├── .pre-commit-config.yaml           # pre-commit hooks
├── py.typed                          # PEP 561 标记
├── .gitignore
└── README.md
```

## 4. 开发命令

```bash
uv sync                              # 装所有 deps
uv run uvicorn app.main:app --port 8000   # 起后端（**没开 --reload**）
uv run alembic upgrade head          # 跑迁移（改了 app/models/*.py 之后）
uv run pytest                        # 跑测试
uv run pytest --cov                  # 跑覆盖率（fail_under = 80）
uv run mypy app/                     # 类型检查（strict 模式）
uv run ruff check .                  # lint
uv run ruff format .                 # 格式化
uv run pre-commit run --all-files    # 跑全部 pre-commit hook
```

### 4.1 改完后端代码后必须重启

`uvicorn` **没开 `--reload`**——改了 Python 文件不重启，跑的还是旧代码。

最隐蔽的形态是 **schema 变更**：新加的响应字段会**静默消失**，前端拿到
`undefined` 而不是报错，看起来像「后端没实现这个字段」。

```bash
# 改完 Python 文件后
pkill -f "uvicorn app.main:app"    # 停掉旧的
uv run uvicorn app.main:app --port 8000
```

改了 `app/models/*.py` 还要跑迁移（见 §10）。

## 5. 代码规范（ruff + mypy strict）

### 5.1 ruff 规则集

`select = ["E", "F", "W", "I", "B", "UP", "SIM", "PT", "C4", "RUF", "ASYNC"]`

| 规则 | 作用 |
|---|---|
| E / W | PEP 8 风格 |
| F | 未使用 import / 变量 |
| I | import 排序 |
| B | 常见 bug |
| UP | Python 3.12+ 语法升级 |
| SIM | 代码简化 |
| PT | pytest 风格 |
| C4 | comprehensions 列表推导 |
| RUF | ruff 特定规则 |
| ASYNC | async/await 检查 |

`ignore = ["E501", "B008"]` —— E501 行长交给 ruff format；B008 函数默认参数调用（FastAPI Depends 需要）

### 5.2 mypy strict 模式

`strict = true` + `disallow_untyped_defs` + `disallow_incomplete_defs` + `no_implicit_optional` + `warn_redundant_casts` + `warn_unused_ignores` + `strict_equality` + `strict_concatenate`

`tests/*` 排除 `disallow_untyped_defs` —— 测试 fixture 灵活。

## 6. pre-commit hook（Python 侧）

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    hooks: [trailing-whitespace / end-of-file-fixer / check-yaml / check-toml / check-added-large-files / detect-private-key / no-commit-to-branch]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks: [ruff --fix / ruff-format]
  - repo: https://github.com/pre-commit/mirrors-mypy
    hooks: [mypy --config-file=pyproject.toml]
  - hooks: [pytest-smoke]
```

## 7. 测试规范

- 烟测必跑：`pytest -m smoke`（test_smoke.py）
- 单元测试：每个 service / agent 必须有对应 test_xxx.py
- 覆盖率：`fail_under = 80`（CI 阻断）
- 异步测试：`pytest-asyncio mode = "auto"`，无需 `@pytest.mark.asyncio` 装饰

## 8. API 设计规范

- 版本：`/api/v1/...`（FastAPI APIRouter include prefix）
- 响应：`Pydantic v2 BaseModel` + `model_config = ConfigDict(from_attributes=True)`
- 错误：自定义 `AppError` + FastAPI exception_handler 统一处理
- auth：FastAPI Depends + JWT / OAuth2 bearer token
- OpenAPI：自动生成 `@app.get("/api/v1/...")`

## 9. 安全

- **依赖审计**：`pip-audit` / `uv pip audit` CI 阻断（待 W2 配）
- **密钥**：用环境变量，绝不 hardcode
- **SQL 注入**：只用 SQLAlchemy 参数化查询
- **JWT**：HS256 + 短期 access token（15min）+ 长期 refresh token（30day）
- **CORS**：白名单 origin，禁止 `*`

## 10. 数据库

- **数据库**：SQLite（`apps/api/argus.db`），异步驱动 `aiosqlite`
- **向量**：sqlite-vec 扩展，`chunk_embeddings` 表用 `vec0` 虚表，1536 维
  （与嵌入模型 `text-embedding-v4` 的输出维度一致，**改嵌入模型必须重建索引表**）
- **migration**：Alembic（每次 model 变更 `alembic revision --autogenerate`）
- **测试**：内存 SQLite（`tests/conftest.py` 的 `db_session`），不复用 dev DB

### 10.1 改了 model 之后（顺序不能错）

```bash
cd apps/api
uv run alembic revision --autogenerate -m "描述"   # 1. 生成迁移
uv run alembic upgrade head                          # 2. 跑迁移
# 3. 重启后端进程 —— uvicorn 没开 --reload，不重启跑的还是旧代码
```

**第 3 步不做不会报错**，只是响应里新字段**静默消失**（前端拿到 `undefined`）。
详见 [docs/LOCAL-DEV.md](../../docs/LOCAL-DEV.md)。

SQLite 的两个坑：

- 加 `NOT NULL` 列必须给 `server_default`，否则 `ALTER TABLE` 直接失败
  （`Cannot add a NOT NULL column with default value NULL`）
- `server_default` 的**值会留在库里**。ORM 的 `default=` 只管 Python 侧插入，
  两者要都写

## 11. 链接

- [CLAUDE.md 根配置](../../CLAUDE.md)
- [AGENTS.md（仓库根）](../../AGENTS.md)
- [apps/web/CONTRIBUTING.md](../../apps/web/CONTRIBUTING.md)
- [docs/CONVENTIONS.md](../../docs/CONVENTIONS.md)
- [docs/LOCAL-DEV.md](../../docs/LOCAL-DEV.md)
- [prd/architecture.md](../../prd/architecture.md)
- [prd/tech-stack.md](../../prd/tech-stack.md)
- [prd/multi-agent-design.md](../../prd/multi-agent-design.md)
- [prd/rag-pipeline.md](../../prd/rag-pipeline.md)
- [prd/risk-and-compliance.md](../../prd/risk-and-compliance.md)

## 12. 特殊配置文件作用（后端 7 个）

| 文件 | 作用 | 谁维护 |
|---|---|---|
| `pyproject.toml` | uv 项目清单：dependencies（FastAPI / Pydantic / SQLAlchemy+aiosqlite / sqlite-vec / anthropic / openai / tavily-python / httpx / httpx2 / pyjwt / alembic）+ devDeps（ruff / mypy / pytest / pre-commit）+ `[tool.ruff]` / `[tool.mypy]` / `[tool.pytest.ini_options]` / `[tool.coverage]` 配置。**注意**：`langgraph` / `langchain-core` / `redis` / `asyncpg` 声明了但代码里一处没用——是计划遗留，别以为装了就等于用上了 | 改 Python 依赖时 |
| `.python-version` | uv 读它决定用哪个 Python（当前 `3.14`）。**没有它，`uv sync` 会取 latest（3.15）并因 ormsgpack 无 cp315 轮子而失败** | 升 Python 版本时 |
| `.ruff.toml` | ruff 独立配置（保留以便 pre-commit 单独跑 ruff）：target-version py312 / line-length 100 / select E F W I B UP SIM PT C4 RUF ASYNC / ignore E501 B008 | 改 ruff 规则时 |
| `.pre-commit-config.yaml` | pre-commit hooks：trailing-whitespace / end-of-file-fixer / check-yaml / check-toml / check-added-large-files + ruff（check + format）+ mypy + pytest smoke | 改 pre-commit 时 |
| `py.typed` | PEP 561 标记：本包对外提供类型注解（mypy 可识别） | 永远不需要改 |
| `tests/conftest.py` | pytest 全局 fixture：`_reset_env` 自动重置 `APP_ENV=test` / `LOG_LEVEL=warning`，防止测试依赖真实 env vars | 加新全局 fixture 时 |
| `tests/test_smoke.py` | 烟测：确保 app 包可被 import + Python 版本 ≥ 3.4 | 加新烟测时 |
