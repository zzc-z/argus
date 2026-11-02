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

### 3.6 前端：run id 在 URL 上

run id 放在 **`/explore?run=xxx`** 的查询参数里。这不只是「刷新能恢复」——
它带来三件别处得不到的东西：

1. **可分享**：把链接发给别人，对方打开看到同一轮研究
2. **可收藏**：浏览器的收藏夹能存住某一轮研究
3. **多标签页隔离**：每个标签页有自己的 URL，各跑各的，互不干扰

第三条是 localStorage 方案做不到的 —— 它是全局一份，两个标签页会互相
覆盖（一个标签页的提问被另一个抢走）。

| 文件 | 职责 |
|---|---|
| `lib/api/client.ts` | 新增 `apiStreamGet`（GET 版 SSE），解析逻辑与 POST 共用 `consumeSse` |
| `lib/api/sse.ts` | 新增 `RunEventV` 镜像类型 |
| `explore/useRunSession.ts` | **新**。连接与 run id 的生命周期：发起 / 接回 / 写 URL |
| `explore/activeRun.ts` | 存最近一轮的 run id 到 localStorage（**只是回退线索**） |
| `explore/page.tsx` | 处理 `run` 帧；挂载时接回 |

**URL 是权威，localStorage 只是线索**：用户从别的页面直接点进 `/explore`
（地址栏里没有 run id）时，问一次后端「我最近一轮是什么」，拿到就把 URL
补上（`replaceState`），照常接回。

**为什么用 `window.history.replaceState` 而不是 `router.replace`**：本项目
开了 `typedRoutes`，`router.replace` 只接受**字面量**路由（动态拼出来的
字符串编译不过）。而这里改的只是查询参数、路径不变 —— Next 官方文档给的
正是这个用法（`docs/01-app/02-guides/single-page-applications.md`）。Next
会 patch `history.replaceState`，所以 `useSearchParams` 会跟着更新。

**`replaceState` 而非 `pushState`**：重问不该让浏览器后退键回到上一轮 ——
用户按后退期待的是离开这个页面，不是看上一轮的报告。

**重置界面的时机**：放在「run 帧」里（第一帧），不放在 effect 里。第一帧
天然标记「新的一轮开始了」；而且 effect 里同步 setState 会触发级联渲染
（`react-hooks/set-state-in-effect` 规则）。重连与新开跑因此走同一条路径，
界面状态只有一处来源。

### 3.7 后端：按 id 精确取消

`AskRequest` 加了 `replace_run_id`。提新问题时取消**它**。

**为什么按 id 而不是「用户最近一轮」**：用户可能开着两个标签页各跑一个
研究。按「最近一轮」取消的话，第二个标签页一提问就把第一个标签页的生成
掐掉 —— 那一个标签页的人正盯着正文往上长，突然停了。前端知道自己那个
标签页正在跑哪一轮（URL 里的 id），精确传上来。

别人的 id 一律忽略（不报错）——「要取消的东西不存在或不是你的」对用户
没有可执行的动作。

### 3.8 后端：`GET /runs/latest`

用户从别的页面直接点进 `/explore`（没有 run id）时的回退：返回最近一轮的
id 与问题。只给 id 不给内容 —— 内容要走 SSE 重放（那才是一致的那一份）。

404 = 没有过 run，前端停在空态。

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
- **run 在内存里，跨设备访问不了**。链接发给别人的时候，他打开会看到
  404（那个 run 只在本进程内存里）。真要跨设备得把 run 落库。

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
