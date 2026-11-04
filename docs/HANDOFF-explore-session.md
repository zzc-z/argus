# 交接：explore 页的会话化（2026-11-01 ~ 11-04）

> **新会话接手先读这份，再读 `docs/LOCAL-DEV.md`。**
> 技术规格见 `docs/SPEC-run-session.md`，踩过的坑见
> `docs/WORKLOG-run-session.md`。

## 一句话

explore 页从「刷新就重置」改成「刷新/切页回来内容还在，生成继续」，
run id 进了 URL（可分享、可收藏、多标签页隔离），加了「新建会话」。

## 状态

| | |
|---|---|
| 仓库 | `~/Desktop/argus`（**只有这一份**，见 LOCAL-DEV.md §0） |
| 分支 | `master`，与 `origin/master` 同步 |
| commit | `956fc93`（本轮 5 个 commit 全部已推送） |
| 后端 | http://localhost:8000（**改了 Python 必须重启**，无 `--reload`） |
| 前端 | http://localhost:3000（**必须 webpack 模式**，Turbopack 会 500） |

## 本轮的 5 个 commit

| commit | 内容 |
|---|---|
| `0daa70d` | 研究会话服务端持有 —— 刷新/切页不终止生成 |
| `990b904` | run id 放进 URL —— 多标签页隔离 + 可分享 |
| `292a0c8` | 「新建会话」+ 取消时保留已生成的正文 |
| `3f116ad` | 修反复重连导致的「一下全出 + 页面卡」 |
| `956fc93` | 补上这轮踩的坑与环境事实 |

## 架构（改之前 vs 改之后）

```
改之前                          改之后
──────                          ──────
客户端 ──HTTP──> 生成器           客户端 ──HTTP──> 订阅者 ↑ ↑
              agent 在这里跑              agent 在后台任务里跑 连接断了 = agent 死          事件先进 run 缓冲
                                         连接断了 = 只是不再收帧 重连 = 从缓冲里补齐
```

**run id 在 URL 上**（`/explore?run=xxx`）—— 不是补丁，是核心设计。
它顺带解决：可分享、可收藏、多标签页隔离（localStorage 是全局一份，
两个标签页会互相覆盖）。

## 三个 id 别搞混

| id | 谁生成 | 干什么 | 生命周期 |
|---|---|---|---|
| **run_id** | 后端 `uuid4()` | **会话句柄** —— 找到「那一轮」 | 易失（进程重启就没） |
| **session_id** | 后端 `uuid4()` | **用量记账** —— token 数、日志对账 | 持久（落进 `reports` 表） |
| **report_id** | 数据库自增 | **落盘的报告** —— `/report/123` | 永久 |

前端只跟 run_id 打交道。

## 关键文件

| 文件 | 职责 |
|---|---|
| `apps/api/app/services/runs.py` | run 注册表：事件缓冲 + 订阅广播 + 按 id 取消 |
| `apps/api/app/services/tasks.py` | 后台任务入口（保住强引用） |
| `apps/api/app/gateway/research.py` | 4 个端点（见下） |
| `apps/api/app/services/agent.py` | 取消分支落盘 + 正文边流边攒 |
| `apps/web/app/(dashboard)/explore/useRunSession.ts` | 连接与 run id 的生命周期 |
| `apps/web/app/(dashboard)/explore/activeRun.ts` | localStorage 线索（**只是回退**） |

### 4 个端点

```
POST   /api/v1/research/ask                  提问（建 run、起后台任务、SSE）
GET    /api/v1/research/runs/{run_id}/stream  接回那一轮（只订阅）
GET    /api/v1/research/runs/latest           最近一轮（无 id 时的回退）
DELETE /api/v1/research/runs/{run_id}         取消那一轮（「新建会话」用）
```

## 三个最容易踩的坑（详细版在 LOCAL-DEV.md）

### ① `useSearchParams()` 每次渲染都是新对象

放进 `useCallback` 依赖 → 回调每次渲染都变 → 依赖它的 effect 每次都
重跑 → **每次都重连** → 服务端把缓冲里的正文**一次性回放**（用户看到
「一下全出」）+ 连接反复重建（页面卡）。

实测同一个 run 被订阅了 **39314 次**。

修法两处**缺一不可**：
1. 用 ref 读最新 searchParams
2. **hook 的返回值用 `useMemo` 包起来**（页面的 effect 依赖整个对象）

ESLint 的 `exhaustive-deps` 不报这个 —— 它只查「依赖有没有漏」，不查
「依赖是不是稳定」。

### ② `CancelledError` 继承 `BaseException` 而非 `Exception`

`except Exception` 捕不到它。取消路径要单独一个分支（`agent.py` 的
`run_agent` 里那个）。

### ③ 取消时要 await 后台任务结束

agent 捕到 `CancelledError` 后的落盘是 `await` —— 不等的话结束标记先发，
随后那个带 `report_id` 的 `done` 帧没人收，落盘的报告成了**孤儿**。

## 已验证的行为（真实浏览器，Playwright）

- 重连次数：39314 → **每个 run 1 次**
- 流式：正文每帧 **~100ms / 每次 +8 字**，90 次变化
- 页面帧间隔中位 **17ms**（60fps 满帧），最大 19ms —— 不卡
- 刷新后内容完整保留（1535 字一字不差，URL 不变）
- 「新建会话」：URL 换成新 run id、正文清空、输入框获得焦点
- 取消时已生成的正文落盘（`truncated=True`）

门禁：685 pytest / ruff / mypy / tsc / eslint 全绿。

## 接下来做什么

### ① 把 run 落库（最值得做的一件事）

**现状**：URL 已经可分享了，但 run 在内存里 —— 链接发给朋友他打开是
**404**（那个 run 只在本进程内存中）。

**要做的**：
- 新增 `research_runs` 表（run_id / user_id / question / created_at /
  事件 JSON / 状态）
- Alembic 迁移 —— **按 AGENTS.md 这属于「动 schema」，必须单独审**
- 注册表改成「内存缓存 + 落库兜底」，进程重启后能恢复
- 多 worker 部署时不同进程能互相看见（现在看不见）

**注意**：事件可能有几百到几千帧，落库要考虑体积（压 JSON？还是只存
最终正文 + 关键节点事件？）。这是设计决策，不是纯实现。

### ② run id 放进 URL 的后续

- **分享链接给朋友**（依赖 ①）
- 浏览器前进/后退时切会话 —— 现在 `replaceState` 不加历史记录，所以
  后退键不会切会话。主流项目是 `pushState`（每个会话一个历史项）。
  改了要考虑「重问时用 replace 还是 push」。

### ③ 「新建会话」的按钮位置

现在在标题栏右侧。主流项目（ChatGPT）把它放在**左侧会话列表**的头部。
我们没有会话列表（run 在内存里，没有持久的历史），所以标题栏是合理
的过渡形态。等 ① 做完有历史了，可以加侧边栏。

### ④ 前端测试

**前端目前没有自动化测试**（没有 vitest/jest）。这两轮的前端 bug
（重连循环）都是靠 Playwright 手工验证抓到的。如果要加，最该覆盖的是：

- `useRunSession` 的回调身份稳定性（memo + ref 模式）
- hook 返回值不 memo 会导致的重连循环

## 已确认不用管的（别重复调查）

- **`reports.truncated` 的前端渲染已经是对的** —— `reports/view.ts:295`
  把它映射成 `status: 'truncated'`，`ReportTable` 有专门的徽章。所以取消
  时落盘的那份报告，在历史列表里会显示成「已截断」，不会被当成完整报告
  读。（这轮新加的取消落盘路径复用了同一套标记，不需要额外改前端。）
- **`useStickToBottom` 的滚动跟随** —— 上一轮就做完并验证过（贴底滚动、
  上滚暂停、回底恢复、浮标按钮）。见 `docs/SPEC-streaming-typewriter.md`。
- **`apps/web/next-env.d.ts`** 是 `next dev` 自动改的，提交它能让工作树干净。

## 关键链接

- [docs/SPEC-run-session.md](SPEC-run-session.md) — 完整技术规格
- [docs/WORKLOG-run-session.md](WORKLOG-run-session.md) — 踩过的坑与变异验证
- [docs/LOCAL-DEV.md](LOCAL-DEV.md) — **环境事实（先读这个）**
- [docs/SPEC-streaming-typewriter.md](SPEC-streaming-typewriter.md) — 流式打字机与滚动跟随
- [docs/WORKLOG-streaming-typewriter.md](WORKLOG-streaming-typewriter.md) — 那一轮的记录
