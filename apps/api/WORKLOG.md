# Argus API 开发工作日志

> 用途：上下文压缩后据此恢复开发状态。最新在底部。
> 最后更新：2026-10-12

## 当前进度：W1 Day 4 完成（单 agent + tool calling + SSE 全链路已通）

### 已提交（本地 master，领先 origin/master 7 个）

| commit | 内容 |
|---|---|
| `4d877a0` | **LLM client 单例 + Tavily 配置**（`app/services/llm.py`） |
| `c4bae5c` | **工具层：`tavily_search` + `dedup`**（`app/services/tools.py`） |
| `7b6784b` | **agent 主循环 + 事件契约 + 打字机切片**（`agent.py` / `stream.py`） |
| `90756fc` | **SSE 端点 `POST /api/v1/research/ask`**（`gateway/research.py`） |

前端 3 个 commit（`d584dbe` / `a260805` / `2b4027c` 等）把 explore 页接到上面
这个端点上，已实跑验证。


### 质量门（全绿）

```
ruff    ✅ All checks passed
mypy    ✅ no issues found in 24 source files（strict）
pytest  ✅ 157 passed
```

## ⚠️ 接续开发必读：本次会话的实测结论

这些是**跑真实模型测出来的**，不是从文档推断的。重写相关代码前先看这段。

### 1. LLM 服务商是「llmapi.pro 中转站」，不是 Anthropic 官方

`ANTHROPIC_BASE_URL=https://llmapi.pro`。它的行为和官方 API 有两处**实测差异**，照官方文档写会踩：

| 现象 | 官方 API | 中转站实测 |
|---|---|---|
| 文本流式粒度 | 逐 token | **整段缓冲**，243 字符只给 1 个 `text_delta` |
| `model_dump()` 带 null 字段 | 严格模式会拒 | **接受**（`citations: null` 照发不误） |

所以后端的打字机效果是**自己切的**（`TextSlicer`，见下），不是依赖上游分块。

`exclude_none=True` 仍然保留——理由从「不这样会 400」改成「直连官方 API 更保守，当前零成本」。

### 2. Sonnet 5 会返回 `thinking` block，且必须原样回传

实测返回结构：`['thinking', 'text', 'tool_use']`。

- **必须回传**：thinking 里带 `signature`，改动会被上游拒
- **绝不能发给用户**：前端只要研究结论，原始 CoT 不该出站

代码里 `messages.append({"role": "assistant", "content": result.content})` 就是干这个的，`agent.py` 顶部 docstring 写了完整理由。**这条约束由 `tests/test_turn_request.py` 守护**（12 个测试专门测 `_run_turn` 的请求构造与响应解析）。

### 3. `_run_turn` 是最脆的一环，别改它不测

它是 agent 与 SDK 之间**唯一**的接缝（`agent.py:292` 附近）。行覆盖率看不出来——大部分测试用 `monkeypatch` 把它替换掉了，coverage 会把「import 期执行过」算成已覆盖。

代码审查时用**变异测试**发现的：把 signature 字段删掉，125 个测试照样全绿。

### 4. `_is_word_char` 必须限定 ASCII

修「`100,000` 被劈成两半」时用了 `isalnum()`——但**中文的 `isalnum()` 也是 `True`**，导致所有中文标点的切分全被跳过，退化成硬切，连 `QPS` 都劈成 `Q` + `PS`。

现在有 `isascii()` 守卫，且 `LONG_TEXT` 测试数据里同时含中文和千分位。

**教训**：修 bug 的测试必须覆盖**受影响的主路径**（中文），不能只覆盖触发场景（数字）。

## 本次新增的代码约定

| 位置 | 约定 |
|---|---|
| `services/llm.py` | client 单例用 `@lru_cache`，配 `clear_client_cache()` 供测试重置。缺 key 抛 `LLMNotConfiguredError`，不返回 `None` |
| `services/tools.py` | 工具执行失败**不抛异常**，返回 `ok=False`。`except Exception` 分两类：网络类给「外部服务不可用」，其余给「工具内部出错，请勿重试」——代码 bug 不能报成用户参数问题 |
| `services/stream.py` | 事件用 JSON envelope（`{"type": "...", "v": {...}}`）而非 SSE 原生 `event:` 行，消费端一条 `split("\n\n")` + `JSON.parse` 就能统一分发 |
| `gateway/research.py` | 并发上限 4（信号量），超了直接 503 不开流。`X-Accel-Buffering: no` 防 Nginx 缓冲 |
| `services/stream.py::TextSlicer` | 标点贪心切片，窗口放宽到 `chunk_size * 1.5`，搜索范围是窗口内**最靠后**的标点。粒度 24 字 |

## 未完成 / 待办

1. **`tool_call` 事件驱动 InspectorDrawer 的 Input/Output/Prompt/Tabs** —— 现在 Tools 标签页有数据了，另外三个标签仍共用同一份 `jsonText`
2. **`ToolCall` 类型与后端 `ToolCallEvent` 的映射**已做，但 citation 溯源（`Citation`）还没接 SSE
3. **`apps/api/scripts/dev_login.py`** —— 调试脚本（生成 JWT），未提交也未 gitignore
4. **7 个 commit 未推送** —— 代理（APNetwork）需用户手动启动
5. **Day 5-7**：W1 Demo + 前端剩余接线

## 下一步：W1 Day 5-7 或 W2

- **W1 收尾**：citation 溯源接 SSE、`DAG_STATS` 静态 import 清理、W1 Demo
- **W2（重头）**：RAG 管线（PyMuPDF / Trafilatura / chunking / embedding）+ 多 agent 编排

### W2 换 LangGraph 的判断依据（已与用户确认）

现在手写的是「单循环」，`agent.py` 里 `_run_turn` 那 44 行胶水是唯一能被框架替代的部分。`tools.py`（365 行）和 `stream.py`（221 行）LangGraph 完全用不上——前端要的事件格式不是 LangGraph 的回调格式。

**W2 换的理由**：状态在节点间传递、条件边、断点续跑、并行调度。这些手写就是几百行状态机。`prd/multi-agent-design.md` 已定义好 `ResearchState`。

**换的时候保留**：`tools.py` 整个、`stream.py` 整个、`llm.py` 的 client 单例可复用。只重写 `agent.py` 的循环部分。

⚠️ **W2 的一个已知冲突**：现在 `NodeTracker` 强制「任一时刻只有一个节点 active」（前端 `AgentDAG` 用 `findIndex` 算高亮轨道位置）。LangGraph 并行调度会天然产生多个 active，**这个约束要先解决**。

## 目录结构现状

```
apps/api/app/
├── __init__.py
├── config.py           Settings（pydantic-settings + SecretStr + lru_cache）
├── db.py               engine + SessionLocal + get_session + check_db_health
├── main.py             仅装配：建 app、lifespan、CORS、include_router
├── gateway/            HTTP 边界
│   ├── health.py       /api/v1/healthz + /api/v1/readyz
│   ├── auth.py         /api/v1/auth/github/{login,callback} + /logout
│   ├── users.py        /api/v1/me
│   └── deps.py         get_current_user（cookie→JWT→User），CurrentUser 别名
├── models/             SQLAlchemy ORM
│   ├── base.py         Base(DeclarativeBase)
│   └── user.py         User + Account + Provider(StrEnum)
├── schemas/            Pydantic 响应模型
│   ├── health.py       HealthResponse
│   └── user.py         MeResponse
└── services/           业务编排
    ├── auth.py         OAuthProfile / LoginResult / get_or_create_user
    └── token.py        JWT 签发与校验

apps/api/alembic/       已接好，target_metadata = Base.metadata
apps/api/tests/         49 个测试，内存 SQLite 隔离
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
11. **鉴权失败只有一种 401 文案**——缺 cookie / 票据坏 / 用户已删全返回同一句。前端处理动作完全一样，区分开只会多写无用分支；顺带不向攻击者泄露失败原因
12. **登出只删 cookie，不撤销票据**——JWT 无状态，服务端不存 session。已抄走的 cookie 在 7 天内仍能调通接口。补救要加撤销名单（表或 Redis），当前不做：等真要「踢人下线」时再上

## 环境相关的坑

- **PyPI 网络不稳**：报 `Failed to connect` / `peer closed connection`。改用阿里云镜像：
  ```bash
  uv sync --extra dev --index-url https://mirrors.aliyun.com/pypi/simple/
  ```
- **`uv remove` 会连带卸载整个 dev extra**。改 pyproject 后用 `sed` 编辑 + `uv sync --extra dev`，不要用 `uv remove`
- **VS Code 报红（无法解析导入 sqlalchemy/itsdangerous）**：IDE 解释器没指对，代码本身没问题。命令行 `uv run pytest` 走 `.venv` 所以全绿，但 Pylance 用你指定的解释器找包，两套机制独立。
  - 已修（2026-10-09）：项目根 `.vscode/settings.json` 设了 `python.defaultInterpreterPath = "apps/api/.venv/bin/python3"` + `python.analysis.extraPaths = ["apps/api"]`。改完要 `Cmd+Shift+P` → `Developer: Reload Window`，Pylance 不会自动重载
  - **venv 唯一实体在 `apps/api/.venv`**（uv 在 apps/api 下建的）。排查时别在仓库根跑 `find . -name .venv` 再把结果当根目录的——那样 `find` 的 `.` 是 cwd，会误报成 `./.venv`。先 `pwd` 确认再解读
  - **局限**：`defaultInterpreterPath` 对「已存在的 venv」生效。删掉 `.venv` 重装后 VS Code 会忽略这项，仍需手动选一次解释器
  - `.vscode/` 被根 `.gitignore:8` 忽略（解释器路径机器相关，入库添乱），换机器要照 WORKLOG 重建
- **ruff 读 `.ruff.toml` 而非 `pyproject.toml` 的 `[tool.ruff]`**——两处配置要同步
- **已装依赖**：`sqlalchemy[asyncio]`、`aiosqlite`（dev extra）、`itsdangerous`、`types-authlib`（dev extra）。已移除 `types-pyjwt`（过时 stub，会把 `jwt.encode` 误标为返回 bytes）

## 凭据状态（.env 18 个 key 全部已填，不要在对话里贴值）

2026-10-09 复核：全部齐了，Day 3 无前置阻塞。

| 变量 | 状态 |
|---|---|
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | ✅ 已填 |
| `GITHUB_OAUTH_CALLBACK_URL` | ✅ `http://localhost:8000/api/v1/auth/github/callback`（GitHub 后台 Redirect URI 已同步） |
| `JWT_SECRET_KEY` | ✅ 已填（64 字符） |
| `ANTHROPIC_API_KEY` | ✅ 已填（Day 3 用） |
| `ANTHROPIC_BASE_URL` | ✅ `https://llmapi.pro`（中转站） |
| 7 个 `ANTHROPIC_*_MODEL` | ✅ 已填（complex 走 `claude-sonnet-5`，default 走 `claude-haiku-4-5`） |

**坑**：`.env` 第 1 行 `GITHUB_OAUTH_CLIENT_ID = "xxx"` 的等号两边有空格。
pydantic-settings 走 python-dotenv 能容忍，功能正常；但 `grep '^\([A-Z_]*\)='` 这类
脚本会漏掉它。排查 env 时用宽松正则 `^\s*[A-Za-z_][A-Za-z0-9_]*\s*=`。

## 登录闭环（已完成 2026-10-09，未提交）

| 文件 | 内容 |
|---|---|
| `app/gateway/deps.py` | `get_current_user` + `CurrentUser` 别名 |
| `app/gateway/users.py` | `GET /api/v1/me` |
| `app/gateway/auth.py` | `POST /api/v1/auth/logout`（204，不校验登录态，幂等） |
| `app/schemas/user.py` | `MeResponse` |
| `tests/conftest.py` | 提上来共用：`api_db` / `client` / `github_state` |
| `tests/test_session_routes.py` | 11 个测试 |

真实 HTTP 已验证（uvicorn + curl）：无 cookie 401、坏 cookie 401、真票据 200、
登出后 `set-cookie` 带 `Max-Age=0; Path=/`。dev 库未被污染。

## 测试要求

新增功能必须配测试，沿用现有模式：
- DB 用 `db_session` fixture（内存 SQLite）
- 路由用 `api_db` fixture 做 `dependency_overrides`
- 外部 HTTP 用 `monkeypatch` 替换，不用 respx
- OAuth 相关请求要加 `follow_redirects=False`

## 本次会话的实测结论（重新开发前必读）

### 1. 中转站 llmapi.pro 的真实行为

不是照文档猜的，是实测的（`AsyncAnthropic(base_url=...)`）：

| 事实 | 影响 |
|---|---|
| **支持 tool calling**，`stop_reason: tool_use` | 可用 |
| **支持流式**，但会把 243 字符缓冲成 1 个 `text_delta` | 打字机效果必须后端自己补，已由 `TextSlicer` 承担 |
| 流式能收到 `input_json_delta`（工具入参增量） | 可用 |
| **模型返回 `thinking` block**（Sonnet 5 扩展思考） | 必须原样回传，见下条 |
| `model_dump()` 漏 `exclude_none` **不会 400**（中转站接受 `citations: null`） | 但仍保留 `exclude_none=True`：直连官方 API 更保守 |

**thinking + signature 是硬约束**：`signature` 是上游的防篡改签名，改一个字节下一轮就拒。
必须 `final.model_dump(exclude_none=True)` 原样回传进 messages；但**不能**转发给用户
（Anthropic 不建议向非受信端暴露原始 CoT）。这就是「不转发但必须存」的原因。

### 2. `tavily-python` 0.8.5

- `AsyncTavilyClient` 是真协程（`inspect.iscoroutinefunction` 为 True），不用自己包线程池
- 支持注入 `httpx.AsyncClient` 复用连接池
- 无 `py.typed`，已在 `pyproject.toml` 加 mypy override

### 3. 前端硬约束：任一时刻最多一个节点 `active`

前端 `AgentDAG` 用 `findIndex(n => n.lifecycle === 'active')` 算高亮轨道位置，
两个 active 会直接算错。`NodeTracker.activate` 里的 `assert` 是强制这个约束的，
不是装饰代码。

**W2 接 LangGraph 时会冲突**——并行调度天然产生多个 active，必须先解决。

### 4. 节点 id 会重复出现

实测模型「先说话再调工具」时，事件序列是：
`researcher → researcher → writer → researcher → writer...`
（同一个 `researcher` 出现 3 次）。

前端契约必须写死：**按到达顺序追加，不得按 id 去重**。

### 5. SSE 协议

单行 JSON envelope，不用 SSE 原生的多路 `event:`：

```
data: {"type": "delta", "v": {"node_id": "writer", "text": "..."}}

data: {"type": "done", "v": {"session_id": "...", "elapsed_ms": 5432}}
```

五类事件：`node` / `delta` / `tool_call` / `error` / `done`。

**开流后 HTTP 状态码改不了**——鉴权、参数校验都必须在开流前完成；
开流后的失败只能走 `error` 事件。

必须加 `X-Accel-Buffering: no`，否则 Nginx 会缓冲，SSE 攒成一坨最后吐出来。

### 6. 未解决 / 待办

| 事项 | 状态 |
|---|---|
| `TAVILY_API_KEY` | **未申请**。`tavily_search` 返回错误字符串，agent 照常跑完但搜不到东西 |
| `stop_reason == "max_tokens"` 且同时有 tool_calls 时，`truncated` 标记走不到 | 已知 bug，未修（`agent.py`） |
| service 层引入了 logger | 与既有约定「logging 归 gateway」冲突，**待用户定夺** |
| 「打字机」无节奏控制 | `_slice_for_display` 是同步函数，片段同 tick 吐完 |
| `tool_call` 事件驱动 InspectorDrawer | 已做（前端 `bd4e232`） |
| W2 换 LangGraph | 保留 `tools.py`(365 行) / `stream.py`(221 行) / `llm.py` client 单例，只重写循环 |

### 7. 代码审查发现并已修的 bug（别再犯）

1. **`_is_word_char` 用 `isalnum()`，中文也算** → 所有中文标点切分失效，退化成硬切，连 `QPS` 都劈成 `Q` + `PS`。
   必须限定 `isascii()`。
2. **模块级 `_tool_results` 全局变量** → SSE 并发时两个用户的搜索结果互相污染。已改局部变量。
3. **`canonicalize_url` 遇畸形 URL 抛 ValueError** → 一条坏 URL 让整批 dedup 结果消失。
4. **截断计数 off-by-one**，且把「requested 裁掉的」和「字符预算裁掉的」混算 → 模型被告知错误数字。
5. **`RunState` 死代码**：加了 `'error'` 但从不赋值，已删。
6. **heredoc 在本环境会被 shell 截断**（含中文/长字符串时）→ 批量替换多次写坏代码。
   长文本改用 Edit/Write 工具。

### 8. 环境

- 后端 venv 在 `apps/api/.venv`，**不在仓库根**
- uvicorn 启动：`cd apps/api && uv run uvicorn app.main:app --port 8000`
- 调 GitHub API 需要代理 `HTTP_PROXY=http://127.0.0.1:62531`（APNetwork 未运行时不要设）
- `/tmp/jwt.txt` 等临时文件：`rm` 被 `dangerous-cmd-block` hook 拦，需手动删
