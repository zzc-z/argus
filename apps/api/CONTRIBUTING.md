# apps/api — 后端贡献指南

> ⚠️ **W2 启用**。当前 `apps/api/` 目录的 Python 代码还未填充，本文档列出 W2 启动时按此执行。

## 1. 环境要求

- **Python** ≥ 3.12
- **uv** ≥ 0.4（包管理）
- **Postgres** ≥ 16 + pgvector extension
- **Redis** ≥ 7（用于 LangGraph checkpointer）

## 2. 安装

```bash
cd /Users/ext.zhangjianpeng11/Desktop/argus/apps/api
uv sync        # 装 pyproject.toml 列出的依赖
uv run pre-commit install   # 装 pre-commit
```

## 3. 目录结构（计划）

```
apps/api/
├── app/                              # 主代码包
│   ├── main.py                       # FastAPI app factory
│   ├── api/                          # HTTP 路由
│   │   └── v1/                       # API v1 版本
│   ├── agents/                        # LangGraph 多智能体
│   ├── db/                           # SQLAlchemy async session + models
│   ├── schemas/                      # Pydantic schemas
│   ├── services/                     # 业务逻辑层
│   ├── core/                         # 配置 / 日志 / 异常
│   └── alembic/                      # 数据库 migration
├── tests/                            # pytest
│   ├── conftest.py
│   ├── test_smoke.py
│   └── ...
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
uv run pytest                        # 跑测试
uv run pytest --cov                  # 跑覆盖率（fail_under = 80）
uv run mypy app/                     # 类型检查（strict 模式）
uv run ruff check .                  # lint
uv run ruff format .                 # 格式化
uv run pre-commit run --all-files    # 跑全部 pre-commit hook
```

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

- **migration**：Alembic（每次 model 变更 `alembic revision --autogenerate`）
- **测试**：用 testcontainers 起临时 Postgres（不复用 dev DB）
- **向量**：pgvector extension，列类型 `Vector(1536)`（OpenAI text-embedding-3-small 维度）
- **LangGraph checkpointer**：用 Postgres（不是 Redis 内存版），跨进程可恢复

## 11. 链接

- [CLAUDE.md 根配置](../../CLAUDE.md)
- [AGENTS.md（仓库根）](../../AGENTS.md)
- [apps/web/CONTRIBUTING.md](../../apps/web/CONTRIBUTING.md)
- [docs/CONVENTIONS.md](../../docs/CONVENTIONS.md)
- [docs/CODE-QUALITY.md](../../docs/CODE-QUALITY.md)
- [prd/architecture.md](../../prd/architecture.md)
- [prd/tech-stack.md](../../prd/tech-stack.md)
- [prd/multi-agent-design.md](../../prd/multi-agent-design.md)
- [prd/rag-pipeline.md](../../prd/rag-pipeline.md)
- [prd/security-review.md](../../prd/security-review.md)

## 12. 特殊配置文件作用（后端 6 个）

| 文件 | 作用 | 谁维护 |
|---|---|---|
| `pyproject.toml` | uv 项目清单：dependencies（FastAPI / Pydantic / LangGraph / SQLAlchemy / pgvector / httpx / pytest-asyncio）+ devDeps（ruff / mypy / pytest / pre-commit）+ `[tool.ruff]` / `[tool.mypy]` / `[tool.pytest.ini_options]` / `[tool.coverage]` 配置 | 改 Python 依赖时 |
| `.ruff.toml` | ruff 独立配置（保留以便 pre-commit 单独跑 ruff）：target-version py312 / line-length 100 / select E F W I B UP SIM PT C4 RUF ASYNC / ignore E501 B008 | 改 ruff 规则时 |
| `.pre-commit-config.yaml` | pre-commit hooks：trailing-whitespace / end-of-file-fixer / check-yaml / check-toml / check-added-large-files + ruff（check + format）+ mypy + pytest smoke | 改 pre-commit 时 |
| `py.typed` | PEP 561 标记：本包对外提供类型注解（mypy 可识别） | 永远不需要改 |
| `tests/conftest.py` | pytest 全局 fixture：`_reset_env` 自动重置 `APP_ENV=test` / `LOG_LEVEL=warning`，防止测试依赖真实 env vars | 加新全局 fixture 时 |
| `tests/test_smoke.py` | 烟测：确保 app 包可被 import + Python 版本 ≥ 3.4 | 加新烟测时 |
