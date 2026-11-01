"""后台任务的统一入口。

为什么要有这个模块：``asyncio.create_task`` 只持**弱引用**，任务在跑完
之前可能被 GC 回收——症状是「偶尔那个后台动作没开始，也没报错」。
所以必须自己保住一份强引用。
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

# 所有后台任务的强引用集合。任务跑完时由 done_callback 摘掉。
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def spawn(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """建后台任务并保住强引用。返回任务本身。

    返回任务是为了让调用方能 ``cancel()`` 它——「用户提了新问题，
    上一轮要停」就需要这个。
    """
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task
