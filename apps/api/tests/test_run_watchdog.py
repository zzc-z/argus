"""研究长时间没有新事件时必须报错收尾，不能让用户一直等。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.gateway import research
from app.services.runs import Run
from app.services.stream import DoneEvent, ErrorEvent, NodeEvent


@asynccontextmanager
async def _no_db() -> AsyncIterator[None]:
    yield None


async def _drive(monkeypatch: pytest.MonkeyPatch, agent: Any) -> list[Any]:
    monkeypatch.setattr(research, "RUN_IDLE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(research, "run_agent", agent)
    run = Run(id="r1", user_id=1, question="q")

    await asyncio.wait_for(
        research._drive_run(
            run,
            question="q",
            user_id=1,
            vec_engine=None,  # type: ignore[arg-type]
            session_maker=_no_db,  # type: ignore[arg-type]
            slot=research._SlotState(),
        ),
        timeout=5,
    )
    _queue, events = await run.subscribe()
    return events


async def test_silent_agent_ends_with_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型调用挂住、一个事件都不再来：超时后发 error 并关闭 run。"""

    async def _hanging_agent(*_args: Any, **_kw: Any) -> AsyncIterator[Any]:
        yield NodeEvent(node_id="supervisor", lifecycle="active")
        await asyncio.sleep(60)

    events = await _drive(monkeypatch, _hanging_agent)

    assert isinstance(events[-1], ErrorEvent), events
    assert events[-1].code == "llm_timeout"


async def test_steady_events_keep_the_run_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """总时长超过时限、但事件持续在来：不算卡住。"""

    async def _slow_but_alive(*_args: Any, **_kw: Any) -> AsyncIterator[Any]:
        for _ in range(4):
            await asyncio.sleep(0.1)
            yield NodeEvent(node_id="researcher", lifecycle="active")

    events = await _drive(monkeypatch, _slow_but_alive)

    assert not any(isinstance(e, ErrorEvent) for e in events), events


async def test_no_timeout_after_report_is_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """报告交付（done）之后只剩引用校验，用户不在等，不再计时。"""

    async def _slow_after_done(*_args: Any, **_kw: Any) -> AsyncIterator[Any]:
        yield DoneEvent(session_id="s", elapsed_ms=0, turns=1, input_tokens=0, output_tokens=0)
        await asyncio.sleep(0.5)
        yield NodeEvent(node_id="critic", lifecycle="completed")

    events = await _drive(monkeypatch, _slow_after_done)

    assert not any(isinstance(e, ErrorEvent) for e in events), events
    assert isinstance(events[-1], NodeEvent)
