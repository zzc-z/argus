# 规格：研究会话（run）与可重连的流

> **2026-11-01 立。** 解决「explore 页刷新 / 切页回来，内容全丢」。

## 1. 问题

explore 页的生成态全部活在组件的 `useState` 里，而 agent 直接跑在
`StreamingResponse` 的生成器中。两件事叠在一起：

1. **组件卸载 = 状态蒸发**：切到别的页面再回来，`streamedText`、DAG 推进、
   引用表、工具轨迹、token 统计全部归零。
2. **连接断开 = 生成终止**：SSE 生成器被取消，agent 跟着死。即使把状态
   存下来，那一轮也停在半截。

已烧掉的 token 白烧——一次研究 30-60 秒、几十万 token。

## 2. 主流项目的做法

ChatGPT / Claude / Perplexity 都是**会话在服务端持有**：

- 服务端持有「一次对话」的状态与生成过程
- 客户端只是**订阅者**：连上就收帧，断开只是不再收
- URL 带会话 id，刷新 / 换标签页 / 换设备都能接回同一会话

关键点：**断开不终止生成**。这是「刷新后内容还在」的前提。

## 3. 方案

### 3.1 后端：run 注册表

新增 `app/services/runs.py`：

| 部件 | 职责 |
|---|---|
| `Run` | 一次研究。持事件缓冲、订阅者队列、取消句柄 |
| `RunRegistry` | 进程内所有 run 的索引（单例） |
| `subscribe_run()` | 订阅者：先吐**回放**（订阅前发生的事件），再吐**增量** |

**事件不丢不重**：`publish` 与 `subscribe` 走同一把锁。`subscribe` 记下
`start_seq = _next_seq`，之前的事件走回放（`_events` 里），之后的走队列。
两者按绝对序号划分，不重叠。

用**绝对序号**而不是列表下标：缓冲满了会丢最旧的一帧，下标会整体前移，
用下标算「从哪一帧开始收」会错位。

### 3.2 后端：生成与连接解耦

```
POST /api/v1/research/ask
  ├─ 抢并发槽位（满了 503）
  ├─ 建 run，启**后台任务**跑 agent
  └─ 订阅 run，转成 SSE 帧推给客户端

GET /api/v1/research/runs/{run_id}/stream
  └─ 只订阅（不重跑）
```

后台任务自己开 DB session（请求的 session 随响应结束就关，跑不到那么久）。
session 工厂走依赖注入（`get_sessionmaker`）——直接调 `SessionLocal()` 是
普通函数调用，`dependency_overrides` 对它无效，测试会静悄悄连开发库。

**并发槽位跟着研究走，不跟着 HTTP 连接走**：客户端断开时研究还在跑，
槽位不能提前还。

### 3.3 后端：重问要取消上一轮

生成在服务端跑着，不取消的话上一轮会继续烧 token、继续占槽位（闸门
只有 4 个）。旧行为（生成绑在连接上）本来就是「重问 = 上一轮停」。

`Run.cancel()` 打断后台任务（`Task.cancel()`）而不只是打标记。

### 3.4 后端：流的第一帧是 `run`

```
data: {"type":"run","v":{"run_id":"...","question":"..."}}
```

前端要拿 run id 才能在刷新后接回那一轮。用**事件帧**而不是响应头：
响应头要额外配 `CORSMiddleware(expose_headers=...)`，跨域下 JS 读不到
没 expose 的自定义头（读到 null），症状是「重连永远 404」，很难查。

必须是**第一帧**：它要先于正文到达，否则用户在正文出来之前刷新，
前端手里没有 run id。

`question` 也由这一帧带——重连时前端是空的，它不知道这一轮问的是什么。
服务端知道，省得前端再存一份（也避免两份不一致）。

### 3.5 流的结束信号

`done` 帧**不是**结束信号——它之后还有 `faithfulness` 帧（引用校验结论）。
流以**显式的结束标记**（`EndOfRun` 哨兵）结束，由跑 run 的那侧在收尾时
发出。

### 3.6 前端

| 文件 | 职责 |
|---|---|
| `lib/api/client.ts` | 新增 `apiStreamGet`（GET 版 SSE），解析逻辑与 POST 共用 `consumeSse` |
| `lib/api/sse.ts` | 新增 `RunEventV` 镜像类型 |
| `explore/activeRun.ts` | 存当前 run id 到 localStorage |
| `explore/page.tsx` | 处理 `run` 帧；挂载时接回上一轮；重问时清掉旧 id |

**挂载时接回**：`useEffect` 跑一次 `reconnect()`——拿本地记的 run id 调
`GET /runs/{id}/stream`。接不上（404 = 被 TTL 清理）就安静回到空态。

**StrictMode 双调用**：开发模式下 effect 会跑两次。用 `reconnectedRef`
记住「已经接过了」，第二次跳过——重复订阅会让同一批帧处理两次，正文重复。

**重问时清 id**：新 run 的第一帧要等一会儿才到，这段时间本地记的还是
上一轮的 id——用户此时刷新会接回**上一轮**，看起来像「我刚问的问题没跑」。

## 4. 存哪里

**内存**（用户的决定）。理由：

- 不动 schema → 不用写 Alembic 迁移 → 不触发「动 schema 必须单独审」的硬门禁
- 后端进程重启后未完成的 run 会丢。但那本来也不是「会话历史」——落盘的
  报告在 `reports` 表里，刷新后仍能看（`ResumeRunCard`）

### 已知缺口

- **多 worker 部署时不同进程看不见彼此的 run**。本项目现在是单进程
  （`uvicorn app.main:app`），不构成问题；要多 worker 时得换共享存储
  （Redis / Postgres）。
- **进程重启丢未完成的 run**。
- **run id 存 localStorage，两个标签页会互相覆盖**。真正的问题不是
  「接错」（接的是同一个 run，内容一致），而是「一个标签页的提问被
  另一个标签页抢走」。彻底解决要把 run id 放进 URL——主流项目的做法，
  留到下一轮。

## 5. TTL

run 完成后保留 **30 分钟**。用户刷新、关标签页、过一会儿再回来都能看到
完整的那一轮。

**不能按「已收尾」删**——完成的那一刻 run 就消失的话，用户切回来看到
空白。

## 6. 测试

`tests/test_runs.py`（注册表语义）+ `tests/test_run_reconnect.py`（端到端
重连）+ `tests/test_research_router.py`（第一帧位置、鉴权）。

### 踩过的坑

**`asyncio.Event` 跨事件循环无效**：`TestClient` 把 app 跑在另一个线程的
另一个事件循环里（portal）。测试代码跑在 pytest-asyncio 的循环里。
`asyncio.Event` 绑定创建它的那���循环——跨循环 `set()` 不唤醒等待者，
测试**永久挂住**（第一版就这么挂的，120 秒超时）。

用 `threading.Event`（不绑循环，跨线程安全），agent 侧
`await asyncio.to_thread(release.wait, timeout)` 等它。

## 7. 关联

- [docs/SPEC-streaming-typewriter.md](SPEC-streaming-typewriter.md) — 流式打字机与滚动跟随
- [docs/LOCAL-DEV.md](LOCAL-DEV.md) — 环境事实
