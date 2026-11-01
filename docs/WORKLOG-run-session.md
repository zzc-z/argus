# 进展记录：研究会话（run）与可重连的流

> **2026-11-01。** 解决「explore 页刷新 / 切页回来，内容全丢」。
> 技术细节与实测见 `docs/SPEC-run-session.md`。

## 起点：用户报的问题

「explore 页有个问题，如果内容正在生成中，点击刷新就会重置了，跳到别的页再回来
也是这样，预期保留，你参考主流项目优化这个页的一系列问题」

## 根因

两件事叠在一起：

1. **组件卸载 = 状态蒸发**：explore 的生成态全在 `useState` 里，切页即丢。
2. **连接断开 = 生成终止**：agent 跑在 `StreamingResponse` 的生成器中，
   客户端一断（刷新 / 切页 / 关标签），SSE 生成器被取消，agent 跟着死。

第 2 条更要命：即使把状态存下来，那一轮也停在半截，已烧的 token 白烧
（一次研究 30-60 秒、几十万 token）。

## 方案：会话在服务端持有（主流做法）

ChatGPT / Claude / Perplexity 都是这个结构——服务端持有会话，客户端只是
订阅者，**断开不终止生成**。

```
后端                                  前端
────                                  ────
run 注册表（内存）                     存 run id 到 localStorage
  ├─ 事件缓冲                          ├─ 挂载时读 run id
  ├─ 订阅者队列                        ├─ GET /runs/{id}/stream 接回
  └─ 后台任务跑 agent                  └─ 逐帧渲染
```

## 改动

| 文件 | 改动 |
|---|---|
| `app/services/runs.py` | **新**。run 注册表：事件缓冲 + 订阅广播 + 取消 |
| `app/services/tasks.py` | **新**。后台任务的统一入口（保住强引用） |
| `app/gateway/research.py` | agent 移到后台任务；新增 `GET /runs/{id}/stream`；重问取消上一轮 |
| `app/services/stream.py` | 新增 `RunEvent`（第一帧带 run id 与问题） |
| `app/db.py` | 新增 `get_sessionmaker()`（后台任务用，可被 override） |
| `apps/web/lib/api/client.ts` | 新增 `apiStreamGet`；解析逻辑抽成共用的 `consumeSse` |
| `apps/web/lib/api/sse.ts` | 新增 `RunEventV` 镜像 |
| `apps/web/app/(dashboard)/explore/activeRun.ts` | **新**。存当前 run id |
| `apps/web/app/(dashboard)/explore/page.tsx` | 处理 `run` 帧；挂载时接回；重问时清 id |

**没有动 schema**（用户的决定：存内存）。不用写 Alembic 迁移。

## 关键设计点

### 事件不丢不重

`publish` 与 `subscribe` 走同一把锁。`subscribe` 记下 `start_seq`，
之前的事件走**回放**（`_events` 里），之后的走**队列**。按绝对序号划分，
不重叠。

用绝对序号而不是列表下标：缓冲满了会丢最旧的一帧，下标整体前移，
用下标算「从哪一帧开始收」会错位。

### 流的结束信号不是 `done`

`done` 之后还有 `faithfulness` 帧（引用校验结论）。拿 `done` 当结束信号会
把它截掉，用户看不到校验面板。改用显式的结束标记（`EndOfRun` 哨兵）。

### 重问要取消上一轮

生成在服务端跑着，不取消的话上一轮继续烧 token、继续占并发槽位（闸门
只有 4 个）。`Run.cancel()` 打断后台任务（`Task.cancel()`），不只是打标记。

### 第一帧用事件而不是响应头

run id 必须让前端知道才能接回。用响应头要额外配
`CORSMiddleware(expose_headers=...)`——跨域下 JS 读不到没 expose 的
自定义头（读到 null），症状是「重连永远 404」，很难查。事件帧走的是流
本身，没有这个坑。

### 槽位跟着研究走，不跟着连接走

客户端断开时研究还在跑，槽位不能提前还——否则并发上限形同虚设。

## 踩过的坑

### 1. `asyncio.Event` 跨事件循环无效（测试永久挂住）

`TestClient` 把 app 跑在**另一个线程**的另一个事件循环里（portal）。
测试代码跑在 pytest-asyncio 的循环里。`asyncio.Event` 绑定创建它的
那个循环——跨循环 `set()` 不唤醒等待者，测试**120 秒超时**。

改用 `threading.Event`（不绑循环，跨线程安全），agent 侧
`await asyncio.to_thread(release.wait, timeout)` 等它。

### 2. 变异验证第一版是废的

第一次做 M2（模拟旧架构）时，我在 HTTP 生成器里既 yield 事件**又**
`await run.publish(event)`——缓冲照样有内容，属性照样成立，测试照样绿。

**教训**：变异要改的是「被守的那个性质」，不是「看起来像旧代码」。
第一版变异证明的是「我改了代码但没改行为」。

### 3. `latest_for_user` 用 `created_at` 取最大不可靠

两次创建可能落在同一个浮点值上（同一微秒内），取 max 就变成任取一个——
可能取消了**新**的那轮而留下旧的继续烧 token。改用字典的插入顺序
（Python 3.7+ 语言保证）。

### 4. 前端重问时必须清掉旧 run id

新 run 的第一帧要等一会儿才到（要走一遍鉴权、建 run、起后台任务），
这段时间本地记的还是上一轮的 id——用户此时刷新，接回来的是**上一轮**
的内容，看起来像「我刚问的问题没跑」。

### 5. StrictMode 双调用会重复订阅

开发模式下 effect 跑两次。重复订阅让同一批帧被处理两次——正文重复。
用 `reconnectedRef` 记住「已经接过了」。

## 变异验证

| 变异 | 抓到它的测试 | 结果 |
|---|---|---|
| 去掉回放（订阅者拿不到历史事件） | `test_events_published_before_subscribe_are_replayed` 等 | 7 条红 |
| agent 跑回 HTTP 生成器、事件不进缓冲 | `test_generation_continues_after_client_disconnects` | 1 条红 |
| 回放与实时重叠（正文发两遍） | `test_reconnect_does_not_duplicate_text` 等 | 7 条红 |
| 取消只打标记不打断任务 | `test_cancel_interrupts_the_background_task` | 1 条红 |
| 收尾的 run 立刻被删（重连无内容） | `test_registry_keeps_finished_run_for_replay` 等 | 5 条红 |

每条都是**先改坏 → 跑测试 → 改回来**，跑完确认工作树无残留
（`grep -c MUTATION` 为 0，671 pytest 全绿）。

## 已知缺口

- **多 worker 部署时不同进程看不见彼此的 run**（本项目现在是单进程，不构成
  问题）
- **进程重启丢未完成的 run**
- **run id 存 localStorage，两个标签页会互相覆盖**。真正的问题不是「接错」
  （接的是同一个 run，内容一致），而是「一个标签页的提问被另一个标签页
  抢走」。彻底解决要把 run id 放进 URL——主流项目的做法，留到下一轮。

## 门禁

- 后端：670 pytest / ruff / mypy 全绿
- 前端：tsc / eslint 全绿

## 关键链接

- [docs/SPEC-run-session.md](SPEC-run-session.md) — 完整技术规格
- [docs/SPEC-streaming-typewriter.md](SPEC-streaming-typewriter.md) — 流式打字机与滚动跟随
- [docs/LOCAL-DEV.md](LOCAL-DEV.md) — 环境事实
