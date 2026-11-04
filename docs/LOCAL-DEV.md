# 本地开发环境（argus）

**2026-10-23 立。** 新会话接手时先读这份 —— 下面几件事做错不会报错，只会「看起来正常但数据是旧的」。

## 0. 只用 `~/Desktop/argus` 这一份

**2026-11-01 定。** 机器上曾经有两份 argus 指向**同一个** GitHub 仓库：

| 路径 | remote | 说明 |
|---|---|---|
| `~/Desktop/argus` | SSH over 443 | **用这份** |
| `~/Projects/argus` | HTTPS | 旧副本，2026-11-01 时落后 131 个 commit |

两份指向同一个仓库，但各自有独立的本地状态 —— 在 `Projects/argus` 里
`git log` 看不到另一份的 commit，看起来像「推送没成功」。

**VSCode 请打开 `~/Desktop/argus`。** `.vscode/settings.json` 的注释里
也记着这个坑（2026-10-09 那次是解释器路径解析失败）。

验证自己在哪份：

```bash
pwd && git remote -v && git log --oneline -1
```

## 1. 跑起来

```bash
# 后端（apps/api）
cd apps/api
uv run uvicorn app.main:app --port 8000

# 前端（仓库根）
pnpm --filter web dev
```

前端默认打 `http://localhost:8000`（`apps/web/lib/api/client.ts` 的 `API_BASE`），
可用 `NEXT_PUBLIC_API_BASE` 覆盖。

### 1.1 前端 dev 必须用 webpack（`--webpack`）

**`pnpm --filter web dev` 已经固定带 `--webpack`**，不要改成裸 `next dev`。

原因（实测 2026-11-01，Next 16.3.8）：**Turbopack 下 `next/font/google`
的字体 loader 解析不了**，页面直接 500：

```
Error: Module not found: Can't resolve '@vercel/turbopack-next/internal/font/google/font'
next/font/google queries have exactly one entry
```

同一个代码用 `--webpack` 起来就是 200。这是 Next 16.3.8 + Turbopack 的
既存问题，与项目代码无关（`git stash` 到 HEAD 同样 500）。

`@vercel/turbopack-next` 是 Next 的**虚拟模块**（不在 npm registry 上），
由 Next 自己的 loader 解析——16.3.8 的包里没有对应的解析代码。

想试 Turbopack 用 `pnpm --filter web dev:turbopack`，但预期是 500。

### 1.2 `next/font/google` 全项目只能有一个导入入口

Next 16 要求 `next/font/google` 只有**一处** import。字体的 CSS 变量统一
在 `app/layout.tsx` 声明（`--font-geist` / `--font-jetbrains-mono` /
`--font-inter`），页面里用 `var(--font-inter)` 引用，**不要在自己页面里
再 import 一次**。

## 2. 改了后端代码 → 必须重启

**后端没开 `--reload`。** 改了 Python 文件不重启，进程跑的还是旧代码。

最容易踩的是 **schema 变更**（改了 `app/models/` 或 `app/schemas/`）：

| 你改了什么 | 不重启的后果 |
|---|---|
| 加了响应字段（如 `reports.truncated`） | 前端拿到 `undefined` —— 字段**静默消失**，不报错。列表页会全都显示成「已交叉验证」 |
| 加了请求字段 | 后端读不到，前端传了等于没传 |
| 改了分类逻辑 | 报错文案还是旧的，用户看到「暂时不可用」而不是具体原因 |

**判断方法**：改了后端却看到旧行为，先怀疑没重启。

前端是 Next.js dev server，有热更新，不用管。

## 3. 改了数据库结构 → 先跑迁移

```bash
cd apps/api
uv run alembic upgrade head          # 应用迁移
uv run alembic current               # 看当前版本
uv run alembic downgrade -1          # 回退一条（可逆才做）
```

**改了 `app/models/*.py` 就要写迁移**。仓库用 Alembic，迁移文件在
`alembic/versions/`。

### 3.1 SQLite 的坑

- **Alembic 的 `add_column` 对 SQLite 是「重建表」**，不是真的 ALTER。
  表越大越慢（argus.db 约 50MB，几十秒级）。
- **加 NOT NULL 列必须给 `server_default`**。ORM 里的 `default=False`
  只是 Python 层的默认值，SQLite 加列时拿不到 → 迁移会失败。
  写法：`sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false())`。
- **`downgrade` 里的 `drop_column` 同样走重建表**，数据会丢。回退前先备份。

### 3.2 备份

```bash
cp apps/api/argus.db /tmp/argus.db.backup
```

`argus.db` 是 dev 库，但里面有本地向量索引（`chunk_embeddings` vec0 表），
重建要重跑嵌入 —— 别随手删。

### 3.3 迁移要幂等

迁移文件的 `upgrade()` 里先检查列在不在：

```python
if _has_truncated_column():
    return
```

理由：`alembic stamp` 之后手工改过表、或从别的分支 merge 过来时，
schema 状态和版本号可能对不上。上一条迁移（`d4e8f1a29b73`）就踩过这个。

## 4. 改了前端类型 → 两边都要改

前端类型**不是自动生成**的，是手写的镜像：

| 后端 | 前端 |
|---|---|
| `app/schemas/report.py` | `apps/web/lib/api/reports.ts` |
| `app/services/stream.py` | `apps/web/lib/api/sse.ts` |

改了后端 schema 要手动同步前端类型。`reports.ts` 的注释里写着
「改了那边必须同步改这里」。

## 5. 质量门（提交前必跑）

```bash
# 后端
cd apps/api
uv run ruff check app/ tests/ alembic/
uv run ruff format --check app/ tests/ alembic/
uv run mypy app/
uv run pytest tests/ -q --no-header -p no:cacheprovider

# 前端
pnpm --filter web lint
pnpm --filter web exec tsc --noEmit
```

**`pnpm --filter web tsc --noEmit` 是空命令**——`apps/web/package.json` 里没有
`tsc` script，它会打印「None of the selected packages has a "tsc" script」然后
**退出码 0**，什么都没跑。必须用 `exec tsc --noEmit`。

`ruff format --check` 在全库目前是红的（ruff 版本差异导致的既有状态，
改动前就红）。只保证**你改动的文件**干净，别去格式化别人的代码。

## 6. 已知的环境事实

- **数据库是 SQLite**（`apps/api/argus.db`），不是 Postgres。
  向量用 `sqlite-vec` 扩展，维度 1536（写死在 vec0 表 DDL 里）。
- **嵌入服务走阿里云百炼**（`EMBEDDING_API_KEY`）。欠费时
  `local_search` 的向量召回整个挂掉，报告会是 0 引用但**不报错**。
  实测：`cd apps/api && .venv/bin/python -c "import asyncio; from app.services.embedder import embed_texts; print(len(asyncio.run(embed_texts(['t']))[0]))"`
  返回 1536 就是正常。
- **模型服务走中转站** `llmapi.pro`（`ANTHROPIC_BASE_URL`）。它会在 SSE
  流消费途中随机断连，报 `RemoteProtocolError`。代码里有整轮重发兜底
  （`app/services/agent.py` 的 `_run_turn`），但重发 3 次全失败就会
  看到「模型连接在生成途中被中断」。**这是上游问题，不是代码 bug。**
- **中转站的 key 有多套，额度各算各的**。`apps/api/.env` 的
  `ANTHROPIC_API_KEY` 与 `~/.claude/settings.json` 的
  `ANTHROPIC_AUTH_TOKEN` **不是同一个令牌**（格式一样、额度池不同）。
  中转站报 403「Trial quota used up」时先拿另一个 key 试一次——同一个
  base_url、同一个模型，一个能用一个不能，就是令牌不同，跟服务无关。
- **中转站的配额错误会伪装成权限错误**。试用额度用完时上游返回
  **403 + permission_error**，message 才是真因
  （「Trial quota (40 requests) used up」）。只看状态码会报成
  「没有该模型的权限」，把排查方向带偏。
- **流式请求的错误不走状态码**。响应头发出时是 **200**，错误随后以 SSE
  ``error`` 事件送达（Anthropic 官方说明：``overloaded_error`` 等在流式下
  就是 200 + 流内 error 事件，非流式才对应 529/429）。
  只按状态码分类的话，这类错误全落进「200 → 兜底」，报成
  「模型服务暂时不可用」——而上游 message 往往明写 "Please retry"，
  实际重试一次就能过。

  实测（2026-10-31，中转站 llmapi.pro）：
  `{"type":"error","error":{"type":"api_error","code":"subscription_identity_review_unavailable","message":"The protected subscription response could not be approved. Please retry."}}`

  处理在 `app/services/errors.py` 的 `_in_stream_error_classified`：
  按 `error.type` 分档（与**非流式同类型分到同一档**），未知类型落到
  `llm_upstream_error`（可重试）。
- **`httpx2` 与 `httpx` 的异常类不通用**。`httpx2.ConnectError` 不是内建
  `ConnectionError` 的子类，判网络类异常时两个都得认。
- **扩展思考会吃光输出预算**。请求里不设 `thinking.budget_tokens` 时，
  思考没有上限，会膨胀到把 `max_tokens` 吃光，正文一个字写不出来
  （表现为 `empty_response`）。**重试没用**——实测连打 5 次全部同样被
  吃光，是确定性的不是偶发。详见 `app/services/agent.py` 的
  `THINKING_BUDGET_TOKENS`。
- **中转站的流式是「越长越流式」**。短输出被上游缓冲成一次性吐完，
  长输出才逐字吐（实测 2026-10-30，同一个 prompt 连发 4 次）：

  | 正文长度 | 上游帧数 | 到达跨度 |
  |---|---|---|
  | ~100 字 | 5 | 0.00s（一次性到齐） |
  | ~300 字 | 14 | 0.44s |
  | ~1800 字 | 105 | 10.31s |

  所以**「等上游逐字吐」不能只靠上游**——短报告照样会「一下全出」。
  后端 `stream.py` 的 `Typewriter` 因此做了两件事：切片（粒度，8 字/片）+
  控速（节奏，令牌桶按 **80 字/秒** 限速）。上游缓冲时靠控速拆开；
  上游真流式时跟随上游速度，不拖慢它。
  详见 `docs/SPEC-streaming-typewriter.md`。
- **explore 页的滚动宿主是 `.center`，不是 `window`**。`page.module.css` 里
  `.shell` 是 `overflow: hidden` + 固定高度，整页不滚；只有 `.center`
  （`overflow-y: auto`）滚。要做「跟随底部」之类的效果，ref 要挂在
  `.center` 上。主流项目的贴底滚动在 `lib/hooks/useStickToBottom.ts`：
  内容增长自动跟底，用户上滚则暂停并给「回到底部」浮标。
- **断流重发会重复正文**。上游有随机性（同一 prompt 连发 4 次，
  字数 1653/1155/1737/2164 各不相同），裁剪前缀去重不可靠。改成真流式
  后正文在流途中就发出去了，重发必须先发 `reset` 让前端清零——
  少了它用户会看到同一段正文出现两遍。
- **重发的退避必须是指数的**。固定 1 秒间隔会让所有重试落在同一个网络
  坏窗口里（实测 2026-11-01：3 次重发挤在同一秒全挂）。现在按
  `基数 * 2**(n-1)`（1s → 2s），见 `app/services/agent.py` 的
  `_run_turn`。
- **研究流现在是「服务端持有」的**（2026-11-01）。agent 跑在**后台任务**
  里，事件先进 `app/services/runs.py` 的进程内注册表，HTTP 连接只是
  订阅者。所以**刷新 / 切页不会终止生成**——用户切回来靠
  `GET /api/v1/research/runs/{run_id}/stream` 接回那一轮。
  详见 `docs/SPEC-run-session.md`。
  - run 存在**内存**里：后端进程重启后未完成的 run 会丢；多 worker 部署
    时不同进程看不见彼此的 run（本项目现在是单进程，不构成问题）。
  - run 保留 **30 分钟**（`RUN_TTL_SECONDS`）。**不能按「已收尾」删**——
    完成的那一刻删掉，用户切回来看到空白。
  - 重问会取消上一轮，**按 id 精确取消**（`cancel_by_id` + 前端传的
    `replace_run_id`）。**不能按「用户最近一轮」**——用户可能开着两个
    标签页各跑一个，按「最近一轮」会把另一个标签页的生成掐掉。
    生成在服务端跑着，不取消的话上一轮继续烧 token、继续占并发槽位
    （闸门只有 4 个）。
  - run id 在 **URL** 上（`/explore?run=xxx`），localStorage 只是「无 id
    时找回这一轮」的线索。
  - 「新建会话」= `DELETE /runs/{id}` + URL 去掉 run 参数。取消时**已生成
    的那半截正文会落盘**（标 `truncated=True`）——主流项目也是这个行为
    （ChatGPT 的停止按钮）。
- **后台任务的 DB session 必须走依赖注入**（`app/db.py` 的
  `get_sessionmaker`）。直接调 `SessionLocal()` 是普通函数调用，
  `dependency_overrides` 对它无效——测试里后台任务会静悄悄连上开发库
  `argus.db`，症状是「测试全绿，但开发库被写了」。
- **`useSearchParams()` 返回的每次渲染都是新对象**（Next 不做 memo）。
  放进任何 `useCallback` 的依赖里 → 那个回调每次渲染都变 → 依赖它的
  effect 每次渲染都重跑。

  **这个坑的实际代价（2026-11-04 实测）**：explore 页的 effect 依赖
  `session` 对象（hook 的返回值），而 `session` 的身份取决于内部那些
  回调 —— 链条：`useSearchParams` → `writeRunIdToUrl` → `start` →
  `session` → effect → **每次渲染都重连**。重连时服务端把缓冲里的正文
  一次性回放，用户看到「一下全出」，连接被反复重建 → 页面卡。
  实测同一个 run 被订阅了 **39314 次**。

  **ESLint 的 `exhaustive-deps` 不会报这个** —— 它只检查「依赖有没有漏」，
  不检查「依赖是不是稳定」。这是那条规则的盲区。

  两处都要做，缺一不可：
  1. 用 ref 读最新的 `searchParams`（`searchParamsRef`），依赖里换成
     稳定的东西
  2. **hook 的返回值用 `useMemo` 包起来** —— 页面 effect 依赖整个对象
     （lint 规则要求），「安全」的前提就是它 memo 了

- **hook 返回「内嵌 ref 的对象」会被 ESLint 判成「渲染期访问 ref」**。
  `react-hooks/refs` 规则（v7，React Compiler 基础）把「返回对象里含
  ref」的值整体当成「可能是个 ref」，于是在渲染期读它的**任何**属性都
  报错（`stick.ref`、`stick.paused` 都中招）。

  同一份代码在加了一个 hook 之前是绿的 —— 编译器分析的对象图变了，
  规则行为就跟着变。**规则报的「哪里」不可信，要看它真正在防什么**
  （它防的是「渲染期读 ref 可能拿到不一致的值」，而那时读的是 state）。

  修法：ref 改由调用方建、传进 hook（`useStickToBottom(scrollRef, len)`），
  hook 返回的只有普通值与函数。这也是 React 里更常见的写法：ref 归组件所有。

- **`CancelledError` 继承 `BaseException` 而不是 `Exception`**。所以
  `except Exception` **捕不到**它 —— 取消路径要单独一个分支
  （`app/services/agent.py` 的 `run_agent` 里那个）。想判「是不是取消」
  用 `except asyncio.CancelledError:`，它会先于 `except Exception` 命中。

- **取消 run 时要 `await` 后台任务结束**（`runs.py` 的 `Run.cancel`）。
  agent 捕到 `CancelledError` 后的落盘是 `await` ——不等的话结束标记先发，
  随后那个带 `report_id` 的 `done` 帧没人收，那份落盘的报告成了**孤儿**
  （用户看不到「查看完整报告」的入口）。

- **取消时用户已看到的正文要落盘**（`agent.py` 的正文攒取是**边流边攒**）。
  `report_body` 原来只从 `result.text` 攒（那一轮的**收尾**），而正文是
  边收边发的 —— 取消发生在一轮中途时，用户看到的那半截正文既不在
  `result.text` 里也不在 `report_body` 里，落盘出来是空的。变量要放在
  **循环外面**（取消分支是循环外的 `except` 块，看不到循环内的局部变量）。

- **`TestClient` 里的 `asyncio.Event` 不能跨循环用**。`TestClient` 把 app
  跑在另一个线程的另一个事件循环里（portal），测试代码跑在 pytest-asyncio
  的循环里——`asyncio.Event` 绑定创建它的那��循环，跨循环 `set()` 不唤醒
  等待者，测试**永久挂住**。用 `threading.Event`，agent 侧
  `await asyncio.to_thread(ev.wait, timeout)` 等它。

## 链接
- [AGENTS.md（仓库根）](../AGENTS.md) — 硬配置、收尾流程
- [apps/api/CONTRIBUTING.md](../apps/api/CONTRIBUTING.md) — 后端贡献指南
- [docs/CONVENTIONS.md](CONVENTIONS.md) — 编码与设计约定
- [docs/CODE-QUALITY.md](CODE-QUALITY.md) — 代码质量约定
- [docs/SPEC-streaming-typewriter.md](SPEC-streaming-typewriter.md) — 流式打字机与滚动跟随的规格
- [docs/WORKLOG-streaming-typewriter.md](WORKLOG-streaming-typewriter.md) — 那一轮的进展记录与未完成项
- [docs/SPEC-run-session.md](SPEC-run-session.md) — 研究会话（run）与可重连的流的规格
- [docs/WORKLOG-run-session.md](WORKLOG-run-session.md) — 那一轮的进展记录与踩过的坑（含「新建会话」与重连修复）
