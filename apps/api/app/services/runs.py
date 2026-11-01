"""研究 run 的进程内注册表。

## 要解决什么

explore 页的生成态以前**只活在 HTTP 连接里**：agent 在 ``StreamingResponse``
的生成器里边收边发，客户端一断开（刷新、切页、关标签），生成就停了，
用户回来只看到一片空白——已经烧掉的 token 白烧。

主流项目（ChatGPT / Claude / Perplexity）的做法是**会话在服务端持有**，
客户端只是订阅者：断开不终止生成，重新连上还能接着看。

这个模块提供那个「服务端持有」：一个 run 把事件流缓冲下来，任何数量的
订阅者都能从任意位置接着读。

## 为什么放内存而不是数据库

用户的决定是「存在内存里」。理由：

- 不动 schema → 不用写 Alembic 迁移 → 不触发「动 schema 必须单独审」的
  硬门禁
- 后端进程重启后未完成的 run 会丢。但那本来也不是「会话历史」——落盘的
  报告在 ``reports`` 表里，刷新后仍能看（见 ``ResumeRunCard``）

代价（多 worker 部署时不同进程的 run 互相看不见）记在
``docs/LOCAL-DEV.md`` 的已知缺口里。

## 事件不丢、不重

``publish`` 与 ``subscribe`` 走**同一把锁**：

- ``publish`` 在锁内把事件 append 到 ``_events``，然后按绝对序号投给订阅者
- ``subscribe`` 在锁内登记队列并记下 ``start_seq = _next_seq``

于是「订阅者登记那一刻」之前的事件全在 ``_events`` 里（走回放），
之后的事件序号 ≥ ``start_seq``（走队列）。**两者不重叠**——回放与实时
部分合起来正好是完整事件序列，没有重复也没有遗漏。

竞态推演（``publish`` 与 ``subscribe`` 并发）：

- publish 先拿到锁 → 事件进 ``_events``，此时还没有队列 → subscribe
  之后回放会带上它 ✓
- subscribe 先拿到锁 → ``start_seq`` = 已有的事件数，之后 publish 的
  序号从 ``start_seq`` 开始 → 走队列 ✓

## 为什么用「绝对序号」而不是列表下标

缓冲满了会丢最旧的一帧，列表下标会整体前移——用下标算「这个订阅者该
从哪一帧开始收」就会错位，订阅者要么漏帧要么重帧。绝对序号与列表位置
无关，丢帧不影响它。

## 流的结束信号是「结束标记」，不是 ``done`` 帧

``done`` 之后还有 ``faithfulness`` 帧（引用校验结论，见
``agent._settle``）——拿 ``done`` 当结束信号会把它截掉，用户看不到校验
面板。所以流以**显式的结束标记**结束，由跑 run 的那侧在收尾时发出。
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

from app.services.stream import AgentEvent

logger = logging.getLogger(__name__)

# run 的存活时长（秒）。
#
# 完成后仍然保留一段时间：用户刷新、关标签页、过一会儿再回来，都还能
# 看到完整的那一轮。取 30 分钟——覆盖「切到别的页面看看资料再切回来」。
#
# 超时的 run 会被清理：它的事件缓冲是内存，不回收就是缓慢泄漏。
RUN_TTL_SECONDS = 30 * 60

# 事件缓冲的上限（帧）。
#
# 一次研究大约几百到几千帧（打字机切片后正文 800 字 ≈ 100 帧，加上节点、
# 工具、引用事件）。给 20000 帧的余量后仍超上限的，丢掉**最旧的**帧——
# 那是最早的正文，用户回来看到的是「少了开头」，比整轮丢失好。
#
# 收尾帧不会丢：它们在末尾，而丢的永远是最旧的。
MAX_BUFFERED_EVENTS = 20_000


class EndOfRun:
    """流的结束标记。

    单独一个类型而不是 ``None``：队列装的事件类型是 ``AgentEvent``，
    用 ``None`` 当哨兵会让类型变成 ``AgentEvent | None``，读的时候
    每次都要判空，而 ``None`` 本身在别处也有别的含义。
    """

    def __repr__(self) -> str:
        return "<EndOfRun>"


END_OF_RUN = EndOfRun()

# 队列里可能装事件，也可能装结束标记。
QueueItem = AgentEvent | EndOfRun


@dataclass
class Run:
    """一次研究。

    事件按到达顺序存在 ``_events`` 里；订阅者各自拿一个队列接收**增量**。
    """

    id: str
    user_id: int
    question: str
    created_at: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        # (绝对序号, 事件)
        self._events: list[tuple[int, AgentEvent]] = []
        self._next_seq = 0
        # 订阅者队列 → 它的起始绝对序号。
        self._subscribers: dict[asyncio.Queue[QueueItem], int] = {}
        self._closed = False
        self._cancelled = False
        # 跑这个 run 的后台任务。取消时要打断它——否则 agent 继续跑，
        # 白烧 token 还占着并发槽位。
        self._task: asyncio.Task[None] | None = None

    @property
    def closed(self) -> bool:
        """run 是否已经收尾。"""
        return self._closed

    @property
    def cancelled(self) -> bool:
        """run 是否被用户主动取消。"""
        return self._cancelled

    def attach_task(self, task: asyncio.Task[None]) -> None:
        """登记跑这个 run 的后台任务。"""
        self._task = task

    async def cancel(self) -> None:
        """取消这个 run。

        ## 为什么必须有

        生成现在跑在服务端，客户端断开**不会**终止它。用户提一个新问题时，
        上一轮还在跑——它会继续烧 token（一次研究几十万 token）、继续占着
        并发槽位（``MAX_CONCURRENT_STREAMS = 4``）。几次重问就把闸门占满。

        取消要打断后台任务而不只是标记状态：``Task.cancel`` 会在下一个
        await 点抛 ``CancelledError``，agent 的 ``async for`` 随之退出。
        """
        async with self._lock:
            self._cancelled = True
            task = self._task
        if task is not None and not task.done():
            task.cancel()
        await self.close()

    async def publish(self, event: AgentEvent) -> None:
        """追加一个事件并投给所有订阅者。"""
        async with self._lock:
            seq = self._next_seq
            self._next_seq += 1
            if len(self._events) >= MAX_BUFFERED_EVENTS:
                # 丢最旧的一帧（见常量注释）。
                self._events.pop(0)
            self._events.append((seq, event))
            for queue, start_seq in list(self._subscribers.items()):
                if seq >= start_seq:
                    queue.put_nowait(event)

    async def close(self) -> None:
        """标记 run 结束，并给所有订阅者发结束标记。

        重复调用无害——结束标记只发一次。
        """
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            for queue in self._subscribers:
                queue.put_nowait(END_OF_RUN)

    async def subscribe(self) -> tuple[asyncio.Queue[QueueItem], list[AgentEvent]]:
        """登记一个订阅者。

        返回 ``(队列, 回放片段)``：回放片段是订阅这一刻**已经发生**的
        全部事件，队列里只会有**之后**的新事件。两者拼起来就是完整序列。
        """
        queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        async with self._lock:
            start_seq = self._next_seq
            self._subscribers[queue] = start_seq
            replay = [event for seq, event in self._events if seq < start_seq]
        return queue, replay

    async def unsubscribe(self, queue: asyncio.Queue[QueueItem]) -> None:
        """注销订阅者。客户端断开时必须调，否则队列会一直留着。"""
        async with self._lock:
            self._subscribers.pop(queue, None)


class RunRegistry:
    """进程内所有 run 的索引。单例。见 :func:`get_run_registry`。"""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, *, user_id: int, question: str) -> Run:
        """建一个新 run 并登记。"""
        self._prune()
        run = Run(id=str(uuid4()), user_id=user_id, question=question)
        self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        """按 id 取 run。找不到返回 None——调用方据此回 404。"""
        self._prune()
        return self._runs.get(run_id)

    def latest_for_user(self, user_id: int) -> Run | None:
        """取这个用户最近的一个 run。

        用来在用户提新问题时取消上一轮——见 :meth:`Run.cancel` 的说明。

        **用插入顺序而不是 ``created_at``**：``created_at`` 是
        ``time.monotonic()``，两次创建可能落在同一个浮点值上（同一微秒
        内），取 max 就变成任取一个——可能取消了**新**的那轮而留下旧的
        继续烧 token。字典保序（Python 3.7+ 语言保证），最后一个就是
        最近创建的。
        """
        self._prune()
        latest: Run | None = None
        for run in self._runs.values():
            if run.user_id == user_id:
                latest = run
        return latest

    async def cancel_latest_for_user(self, user_id: int) -> None:
        """取消这个用户最近的一个 run（如果还在跑）。"""
        run = self.latest_for_user(user_id)
        if run is None or run.closed:
            return
        await run.cancel()

    def clear(self) -> None:
        """清空全部 run。测试用——单例跨用例残留会互相干扰。"""
        self._runs.clear()

    def _prune(self) -> None:
        """删掉过期的 run。

        **只按 TTL 删，不按「已收尾」删。** 已收尾的 run 必须留着——用户
        刷新页面、切到别的页面再回来，正要靠它把那一轮重放一遍。按
        「已收尾就删」的话，完成的那一刻 run 就消失了，用户切回来只会
        看到空白。
        """
        now = time.monotonic()
        stale = [
            run_id for run_id, run in self._runs.items() if now - run.created_at > RUN_TTL_SECONDS
        ]
        for run_id in stale:
            del self._runs[run_id]
        if stale:
            logger.info("清理了 %d 个过期 run", len(stale))


_registry = RunRegistry()


def get_run_registry() -> RunRegistry:
    """进程内单例。"""
    return _registry


async def subscribe_run(run: Run) -> AsyncIterator[AgentEvent]:
    """订阅一个 run 的事件流。

    先吐回放片段，再吐队列里的增量。run 已经收尾时，吐完回放就结束。
    """
    queue, replay = await run.subscribe()
    try:
        for event in replay:
            yield event
        if run.closed:
            return
        while True:
            item = await queue.get()
            if isinstance(item, EndOfRun):
                return
            yield item
    finally:
        await run.unsubscribe(queue)
