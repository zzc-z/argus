"""run 注册表与「生成与连接解耦」的行为。

## 要守住什么

2026-11-01 之前，agent 直接跑在 ``StreamingResponse`` 的生成器里——
客户端一断开（刷新、切页、关标签）**生成就停**，用户回来只看到一片
空白，已经烧掉的 token 白烧。

改成「服务端持有 run、客户端只是订阅者」之后，要守住两件事：

1. **断开不影响生成**：run 继续跑，事件继续进缓冲。
2. **重连能补齐**：新订阅者拿到「订阅之前发生过的全部事件」+「之后的
   增量」，合起来是完整序列，不重不漏。

## 每条测试的「错误实现也会通过吗」对照

- ``test_events_published_before_subscribe_are_replayed`` —— 断言回放
  带上订阅前的事件。删掉回放逻辑它会空数组失败 ✓
- ``test_replay_and_live_do_not_overlap`` —— 断言回放与队列**不重叠**。
  实现成「回放全部 + 队列也从头发」就会重帧 ✓
- ``test_live_events_reach_subscriber`` —— 断言订阅后的事件到得了。
  只回放不推送的话它会挂死 ✓
- ``test_generation_continues_after_subscriber_leaves`` —— 断开后事件
  仍进缓冲。这条守的就是「生成与连接解耦」本身 ✓
- ``test_close_is_idempotent`` —— 重复 close 只发一次结束标记。
  少了守卫会发两个，订阅者会多等一次 ✓
"""

import asyncio

import pytest

from app.services.runs import END_OF_RUN, EndOfRun, Run, RunRegistry, subscribe_run
from app.services.stream import DeltaEvent, DoneEvent, NodeEvent


def _node() -> NodeEvent:
    return NodeEvent(node_id="writer", lifecycle="active")


def _delta(text: str) -> DeltaEvent:
    return DeltaEvent(node_id="writer", text=text)


# ── 回放与实时 ────────────────────────────────────────────────


async def test_events_published_before_subscribe_are_replayed() -> None:
    """订阅之前发生的事件，回放时要带上。"""
    run = Run(id="r1", user_id=1, question="q")
    await run.publish(_node())
    await run.publish(_delta("第一片"))

    _queue, replay = await run.subscribe()

    assert len(replay) == 2, "订阅前的���件没有回放——重连的用户会看到空白"


async def test_replay_and_live_do_not_overlap() -> None:
    """回放与实时增量**不能重叠**——重叠就是用户看到同一段正文两遍。"""
    run = Run(id="r1", user_id=1, question="q")
    await run.publish(_delta("早"))

    queue, replay = await run.subscribe()
    await run.publish(_delta("晚"))

    live = [await asyncio.wait_for(queue.get(), timeout=1)]

    texts = [e.text for e in replay if isinstance(e, DeltaEvent)]
    live_texts = [e.text for e in live if isinstance(e, DeltaEvent)]
    assert texts == ["早"]
    assert live_texts == ["晚"], f"回放与实时重叠了：{texts} + {live_texts}"


async def test_live_events_reach_subscriber() -> None:
    """订阅之后的事件要推给订阅者。"""
    run = Run(id="r1", user_id=1, question="q")
    queue, _replay = await run.subscribe()

    await run.publish(_delta("新"))

    item = await asyncio.wait_for(queue.get(), timeout=1)
    assert isinstance(item, DeltaEvent)
    assert item.text == "新"


async def test_generation_continues_after_subscriber_leaves() -> None:
    """订阅者走了，生成**继续**，事件继续进缓冲。

    这条是「生成与连接解耦」的核心：旧实现里客户端一断，生成就停。
    """
    run = Run(id="r1", user_id=1, question="q")
    queue, _replay = await run.subscribe()
    await run.unsubscribe(queue)

    await run.publish(_delta("断开之后"))

    _queue2, replay = await run.subscribe()
    texts = [e.text for e in replay if isinstance(e, DeltaEvent)]
    assert texts == ["断开之后"], "断开后的事件没进缓冲——生成被连接带走了"


# ── 收尾 ──────────────────────────────────────────────────────


async def test_close_is_idempotent() -> None:
    """重复 close 只发一次结束标记。

    多发一个结束标记的话，订阅者会多等一次才结束——流明显卡一下。
    """
    run = Run(id="r1", user_id=1, question="q")
    queue, _replay = await run.subscribe()

    await run.close()
    await run.close()

    first = await asyncio.wait_for(queue.get(), timeout=1)
    assert isinstance(first, EndOfRun)
    assert queue.empty(), "重复 close 发出了多个结束标记"


async def test_subscribe_run_ends_after_close() -> None:
    """run 收尾后订阅，流要结束（不能永远挂着）。"""
    run = Run(id="r1", user_id=1, question="q")
    await run.publish(_delta("内容"))
    await run.close()

    events = [e async for e in subscribe_run(run)]

    assert len(events) == 1
    assert isinstance(events[0], DeltaEvent)


async def test_subscribe_run_ends_on_close_while_subscribed() -> None:
    """订阅期间 run 收尾，流要结束。"""
    run = Run(id="r1", user_id=1, question="q")

    received: list[object] = []

    async def _consume() -> None:
        async for event in subscribe_run(run):
            received.append(event)

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)  # 让订阅者先登记上
    await run.publish(_delta("最后一帧"))
    await run.close()

    await asyncio.wait_for(task, timeout=1)
    assert len(received) == 1


async def test_subscriber_is_unregistered_on_exit() -> None:
    """订阅者退出后要从注册表里摘掉——否则队列会一直留着。"""
    run = Run(id="r1", user_id=1, question="q")
    await run.publish(_delta("x"))
    await run.close()

    async for _ in subscribe_run(run):
        pass

    assert not run._subscribers, "订阅者退出后还留在注册表里"


# ── 注册表 ────────────────────────────────────────────────────


async def test_registry_returns_created_run() -> None:
    registry = RunRegistry()
    run = registry.create(user_id=7, question="问题")

    found = registry.get(run.id)
    assert found is not None
    assert found.user_id == 7
    assert found.question == "问题"


def test_registry_returns_none_for_unknown_id() -> None:
    assert RunRegistry().get("不存在") is None


async def test_registry_keeps_finished_run_for_replay() -> None:
    """收尾的 run **不能**立刻删——用户刷新回来正要靠它重放。

    按「已收尾就删」的话，完成那一刻 run 就没了，用户切回来看到空白。
    """
    registry = RunRegistry()
    run = registry.create(user_id=1, question="q")
    await run.publish(_delta("内容"))
    await run.close()

    assert registry.get(run.id) is not None, "收尾的 run 被删了——重连就没得重放"


async def test_registry_prunes_expired_run() -> None:
    """过期（超过 TTL）的 run 要被清掉——事件缓冲在内存里，不回收就是泄漏。"""
    registry = RunRegistry()
    run = registry.create(user_id=1, question="q")
    # 把创建时间推到 TTL 之外
    run.created_at -= 3600

    registry.get(run.id)  # 触发 _prune

    assert registry.get(run.id) is None, "过期的 run 没被清理"


@pytest.mark.parametrize("size", [10, 100])
async def test_many_subscribers_all_receive_events(size: int) -> None:
    """多个订阅者都要收到同一批事件（同一页开两个标签的情况）。"""
    run = Run(id="r1", user_id=1, question="q")
    queues = []
    for _ in range(size):
        queue, _replay = await run.subscribe()
        queues.append(queue)

    await run.publish(_delta("广播"))

    for queue in queues:
        item = await asyncio.wait_for(queue.get(), timeout=1)
        assert isinstance(item, DeltaEvent)


async def test_end_of_run_sentinel_is_distinct_from_none() -> None:
    """结束标记不能是 ``None``——那样类型就变成 ``AgentEvent | None``。"""
    assert END_OF_RUN is not None
    assert isinstance(END_OF_RUN, EndOfRun)


# ── 取消 ──────────────────────────────────────────────────────


async def test_cancel_marks_the_run_and_closes_it() -> None:
    """取消后 run 标记为 cancelled 并关闭——订阅者不会永远挂着。"""
    run = Run(id="r1", user_id=1, question="q")
    await run.cancel()

    assert run.cancelled
    assert run.closed


async def test_cancel_interrupts_the_background_task() -> None:
    """取消要**打断**后台任务，而不只是打标记。

    只打标记的话，agent 会继续跑完——继续烧 token（一次研究几十万）
    并占着并发槽位（闸门只有 4 个）。几次重问就把闸门占满。
    """
    started = asyncio.Event()
    cancelled = False

    async def _forever() -> None:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled = True
            raise

    run = Run(id="r1", user_id=1, question="q")
    task = asyncio.create_task(_forever())
    run.attach_task(task)
    await started.wait()

    await run.cancel()
    await asyncio.sleep(0)

    assert cancelled, "后台任务没被打断——它还在烧 token"
    assert task.cancelled()


async def test_cancel_on_finished_run_is_harmless() -> None:
    """对已收尾的 run 取消不能抛——收尾与取消可能撞上。"""
    run = Run(id="r1", user_id=1, question="q")
    await run.close()
    await run.cancel()
    assert run.closed


async def test_registry_cancels_latest_run_for_user() -> None:
    """取消这个用户**最近创建**的那一轮。

    ## 调用时机决定语义

    端点是在**建新 run 之前**调它的——那时「最近的那个」就是上一轮，
    取消它正是「重问 = 上一轮停」的语义。

    所以这条测试模拟真实顺序：先有一轮（旧的），再调取消 → 取消的
    应该是旧的。
    """
    registry = RunRegistry()
    old = registry.create(user_id=1, question="旧问题")

    await registry.cancel_latest_for_user(1)

    assert old.cancelled


async def test_registry_does_not_cancel_other_users_run() -> None:
    """不能取消别人的 run。"""
    registry = RunRegistry()
    other = registry.create(user_id=2, question="别人的")

    await registry.cancel_latest_for_user(1)

    assert not other.cancelled


async def test_registry_cancel_is_noop_without_runs() -> None:
    """没有 run 时取消不能抛。"""
    await RunRegistry().cancel_latest_for_user(1)
