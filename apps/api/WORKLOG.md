# Argus API 开发工作日志

> 用途：上下文压缩后据此恢复开发状态。最新在底部。
> 最后更新：2026-10-09

## 当前进度：W1 Day 2 完成，Day 3 待开始

### 已提交的 commit（本地master，领先 origin/master 4 个）

| commit | 内容 |
|---|---|
| `d2dfb14` | GitHub OAuth 登录 + argus JWT（Day 2 下半③） |
| `6d64f03` | OAuth 登录编排：找或建用户 + 账号自动关联（Day 2 下半②） |
| `756a3dd` | users/accounts 两层身份模型 + Alembic（Day 2 下半①） |
| `a0eed9a` | 路由下沉到 app/gateway/，main.py 只做装配 |
| `1bd1c41` | config / db / 健康检查骨架（Day 2 上半） |

**GitHub 推送失败**：网络连不上 github.com:443（75s timeout）。所有 commit 均已在本地，联网后 `git push origin master` 即可。

### 质量门状态（全绿）

```
ruff    ✅ All checks passed
mypy    ✅ Success: no issues found in 15 source files
pytest  ✅ 38 passed
```

命令（在 `apps/api/` 下）：
```bash
uv run ruff check app/ tests/ alembic/
uv run mypy app/
uv run pytest tests/ -q --no-header -p no:cacheprovider
```

## 目录结构现状

```
apps/api/app/
├── __init__.py
├── config.py           Settings（pydantic-settings + SecretStr + lru_cache）
├── db.py               engine + SessionLocal + get_session + check_db_health
├── main.py             仅装配：建 app、lifespan、CORS、include_router
├── gateway/            HTTP 边界
│   ├── health.py       /api/v1/healthz + /api/v1/readyz
│   └── auth.py         /api/v1/auth/github/login + /callback
├── models/             SQLAlchemy ORM
│   ├── base.py         Base(DeclarativeBase)
│   └── user.py         User + Account + Provider(StrEnum)
├── schemas/            Pydantic 响应模型
│   └── health.py       HealthResponse
└── services/           业务编排
    ├── auth.py         OAuthProfile / LoginResult / get_or_create_user
    └── token.py        JWT 签发与校验

apps/api/alembic/       已接好，target_metadata = Base.metadata
apps/api/tests/         38 个测试，内存 SQLite 隔离
```

## 关键技术决策（勿推翻）

1. **API 前缀统一 `/api/v1`**——各router 自己声明 prefix，不在main.py 里统一加
2. **两层身份模型**（Auth.js 事实标准）：`users` 管「是谁」，`accounts` 管「从哪登录」。复合主键 `(provider, provider_account_id)`
3. **邮箱 unique + 自动关联**——OAuth provider 信任主邮箱（GitHub/Google 强制验证）。**若将来接入允许未验证邮箱的 provider，必须关掉 `get_or_create_user` 的第2 段查找**，否则账号劫持
4. **不建 repository 层**——2026 业界轻量化趋势，查询以 `@classmethod` 挂在模型上
5. **JWT payload 只放 user_id**，资料实时读库
6. **JWT 密钥与 OAuth secret 独立**——泄露后果不同
7. **state / PKCE verifier 存itsdangerous 签名 cookie**，不用 Redis（无状态 + 多worker 安全）
8. **不用 Authlib 的 `authorize_access_token`**——它依赖 `request.session`，与 argus 自己的 JWT cookie 方案打架。只用底层 `OAuth2Client` 生成授权 URL，token 交换用 httpx 直调 GitHub
9. **测试不用 respx**——TestClient 走 ASGI transport，respx 会拦掉 TestClient 自己的请求导致假 404。改用 `monkeypatch` 替换发 HTTP 的函数 + `dependency_overrides` 换DB session
10. **测试绝不用 `SessionLocal`**——用 conftest.py 的 `db_session` fixture（内存 SQLite），否则污染 dev 库

## 环境相关的坑

- **PyPI 网络不稳**：报 `Failed to connect` / `peer closed connection`。改用阿里云镜像：
  ```bash
  uv sync --extra dev --index-url https://mirrors.aliyun.com/pypi/simple/
  ```
- **`uv remove` 会连带卸载整个 dev extra**。改 pyproject 后用 `sed` 编辑 + `uv sync --extra dev`，不要用 `uv remove`
- **VS Code 报红（无法解析导入 sqlalchemy/itsdangerous）**：IDE 解释器没指对，代码本身没问题。`Cmd+Shift+P` → Python: Select Interpreter → 选带 `.venv` 的项
- **ruff 读 `.ruff.toml` 而非 `pyproject.toml` 的 `[tool.ruff]`**——两处配置要同步
- **已装依赖**：`sqlalchemy[asyncio]`、`aiosqlite`（dev extra）、`itsdangerous`、`types-authlib`（dev extra）。已移除 `types-pyjwt`（过时 stub，会把 `jwt.encode` 误标为返回 bytes）

## 凭据状态（.env 已配好，不要在对话里贴值）

| 变量 | 状态 |
|---|---|
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | ✅ 已填（值相同，互填了，不影响 GitHub 匹配） |
| `GITHUB_OAUTH_CALLBACK_URL` | ✅ `http://localhost:8000/api/v1/auth/github/callback`（GitHub 后台 Redirect URI 已同步改成这个） |
| `JWT_SECRET_KEY` | ✅ 用户自己生成填入 |
| `ANTHROPIC_API_KEY` | ❌ 空——Day 3 用 |
| `ANTHROPIC_BASE_URL` | ❌ 空——Day 3 接中转站时填 `https://llmapi.pro` |

## 下一步：补完登录闭环（3 项）

按用户要求，接下来做这个（不是直接进 Day 3）：

### 1. JWT 校验依赖（`get_current_user`）

- 位置：`app/gateway/deps.py`（或 `app/services/token.py` 里加）
- 从 `request.cookies["argus_session"]` 取 JWT → `decode_access_token()` → 查 DB 拿 `User`
- 失败统一 401
- 用 `Annotated[..., Depends(...)]` 现代语法

### 2. `GET /api/v1/me` 端点

- 位置：`app/gateway/auth.py` 加，或新建 `app/gateway/users.py`
- 返回当前登录用户的 id / email / display_name / avatar_url
- 响应模型放 `app/schemas/user.py`

### 3. `POST /api/v1/auth/logout`

- 删 `argus_session` cookie
- JWT 无状态，服务端不存 session，所以「登出」只是删 cookie（浏览器清掉即可）。要真正撤销需加黑名单表——当前不做（YAGNI，7 天过期可接受）

## 测试要求

新增功能必须配测试，沿用现有模式：
- DB 用 `db_session` fixture（内存 SQLite）
- 路由用 `api_db` fixture 做 `dependency_overrides`
- 外部 HTTP 用 `monkeypatch` 替换，不用 respx
- OAuth 相关请求要加 `follow_redirects=False`

## Day 3 预告（sprint-plan.md）

单 agent + tool calling：
| 内容 | 新概念 |
|---|---|
| Anthropic SDK 接中转站 | async client、`base_url` 配置 |
| 2 个工具（tavily_search / dedup） | tool calling 协议、JSON schema 定义 |
| `/api/v1/research/ask` 端点 | SSE 流式（前端 explore 页要用） |

模型配置已在 `config.py`：complex走 `claude-sonnet-5`，default 走 `claude-haiku-4-5`（Haiku 4.5 在 2026-10-15 退役，之后须升 Haiku 5）。