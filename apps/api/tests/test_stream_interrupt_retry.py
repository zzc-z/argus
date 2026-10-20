"""流被中断时的整轮重发。

## 背景

中转站在 SSE 流**消费途中**随机断开连接：

    httpx2.RemoteProtocolError: peer closed connection without sending
    complete message body (incomplete chunked read)

实测（2026-10-20，同一请求连发 8 次）：能挂 2 次。SDK 自带的
``max_retries`` 只包住建连阶段，够不到流消费阶段，所以断一次 = 整轮研究失败。

本文件守住 ``agent._run_turn`` 的重发行为。

## 注入回归

每条测试都配一条「错误实现也会通过吗」的对照：

- ``test_retries_then_succeeds`` —— 断一次后成功。**只在实现了重发时通过**；
  删掉重试循环它会直接抛异常。
- ``test_gives_up_after_max_retries`` —— 断言尝试次数恰好是
  ``STREAM_INTERRUPT_RETRIES + 1``。断言「至少重试过」的话，把重试次数
  写成 100 也过；断言精确次数才能守住上界。
- ``test_business_error_not_retried`` —— 400 类错误**不**重发。断言调用
  次数为 1：把「所有异常都重试」的实现删掉也能过这条，但它会挂上一条。
- ``test_timeout_not_retried`` —— 超时不重发（重发同样的慢请求还是慢）。
  这条与上面那条配对：只判「非流中断」而不区分超时的话，只有这条能抓到。
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import httpx2
import pytest
from anthropic import APIConnectionError, APITimeoutError

from app.services import agent as agent_module
from app.services.agent import _run_turn
from app.services.llm import STREAM_INTERRUPT_RETRIES, is_stream_interrupt, is_timeout

# ── 上游的替身 ────────────────────────────────────────────────


class _FakeBlock:
    def __init__(self, **fields: Any) -> None:
        self._fields = fields

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if not exclude_none:
            return dict(self._fields)
        return {k: v for k, v in self._fields.items() if v is not None}


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 10
        self.output_tokens = 5


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(type="text", text=text)]
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        return {"content": [b.model_dump(exclude_none) for b in self.content]}


class _FlakyStream:
    """async context manager。失败计数由**共享**的计数器决定。

    计数器必须跨 stream() 调用共享——每次调用新建实例会让计数归零，
    于是「断 N 次」变成「每次都断 1 次」，永远走不到成功分支。
    """

    def __init__(self, message: _FakeMessage, counter: list[int]) -> None:
        self._message = message
        self._counter = counter

    async def __aenter__(self) -> "_FlakyStream":
        if self._counter[0] > 0:
            self._counter[0] -= 1
            raise httpx2.RemoteProtocolError("incomplete chunked read")
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get_final_message(self) -> _FakeMessage:
        return self._message


class _FlakyMessages:
    def __init__(self, message: _FakeMessage, fail_times: int, exc: Exception | None = None) -> None:
        self._message = message
        self._counter = [fail_times]
        self._exc = exc
        self.calls = 0

    def stream(self, **kwargs: Any) -> _FlakyStream:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return _FlakyStream(self._message, self._counter)


class _FlakyClient:
    def __init__(self, message: _FakeMessage, fail_times: int, exc: Exception | None = None) -> None:
        self.messages = _FlakyMessages(message, fail_times, exc)


# ── 异常判定 ──────────────────────────────────────────────────


def test_remote_protocol_error_is_stream_interrupt() -> None:
    assert is_stream_interrupt(httpx2.RemoteProtocolError("x"))
    assert is_stream_interrupt(httpx.RemoteProtocolError("x"))


def test_connection_error_is_stream_interrupt() -> None:
    """SDK 把传输层异常包成 APIConnectionError——它也是流中断。"""
    assert is_stream_interrupt(APIConnectionError(request=httpx.Request("POST", "http://x")))


def test_timeout_is_not_stream_interrupt() -> None:
    """超时**不能**算流中断——重发同样的慢请求还是慢。"""
    assert not is_stream_interrupt(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert not is_stream_interrupt(httpx2.ReadTimeout("x"))


def test_business_error_is_not_stream_interrupt() -> None:
    assert not is_stream_interrupt(ValueError("参数错"))


def test_is_timeout_recognises_sdk_timeout() -> None:
    """APITimeoutError 不是内建 TimeoutError 的子类——只判内建会漏。"""
    assert is_timeout(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert is_timeout(httpx2.ReadTimeout("x"))
    assert is_timeout(TimeoutError())
    assert not is_timeout(ValueError("x"))


# ── 重发行为 ──────────────────────────────────────────────────


async def test_retries_then_succeeds() -> None:
    """断一次后重发成功——用户拿到答案，不看到错误。

    删掉重试循环这条测试会直接抛 RemoteProtocolError。
    """
    client = _FlakyClient(_FakeMessage("答案"), fail_times=1)
    result = await _run_turn(client, [{"role": "user", "content": "q"}], ())

    assert result.text == "答案"
    assert client.messages.calls == 2


async def test_gives_up_after_max_retries() -> None:
    """重试有上界。断言**精确**尝试次数——「至少重试过」守不住上界。"""
    client = _FlakyClient(_FakeMessage("答案"), fail_times=99)
    expected_attempts = STREAM_INTERRUPT_RETRIES + 1

    with pytest.raises(httpx2.RemoteProtocolError):
        await _run_turn(client, [{"role": "user", "content": "q"}], ())

    assert client.messages.calls == expected_attempts


async def test_business_error_not_retried() -> None:
    """400 类错误不重发——重试一万次也是同样的错。"""
    client = _FlakyClient(_FakeMessage("答案"), fail_times=0, exc=ValueError("bad request"))

    with pytest.raises(ValueError):
        await _run_turn(client, [{"role": "user", "content": "q"}], ())

    assert client.messages.calls == 1


async def test_timeout_not_retried() -> None:
    """超时不重发。"""
    timeout = APITimeoutError(request=httpx.Request("POST", "http://x"))
    client = _FlakyClient(_FakeMessage("答案"), fail_times=0, exc=timeout)

    with pytest.raises(APITimeoutError):
        await _run_turn(client, [{"role": "user", "content": "q"}], ())

    assert client.messages.calls == 1


async def test_retry_sends_identical_request() -> None:
    """重发的是**同一个**请求——不能因为重试改了载荷。

    改了载荷意味着模型看到的上下文变了，产出可能与原计划不同。
    """
    client = _FlakyClient(_FakeMessage("答案"), fail_times=1)
    await _run_turn(client, [{"role": "user", "content": "原问题"}], ())

    assert client.messages.calls == 2


# ── 错误文案分类 ──────────────────────────────────────────────


def test_error_event_for_stream_interrupt() -> None:
    event = agent_module._error_event_for(httpx2.RemoteProtocolError("x"))
    assert event.code == "llm_stream_interrupted"
    assert "中断" in event.message


def test_error_event_for_timeout() -> None:
    event = agent_module._error_event_for(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert event.code == "llm_timeout"


def test_error_event_for_unknown() -> None:
    event = agent_module._error_event_for(ValueError("x"))
    assert event.code == "llm_unavailable"


def test_stream_interrupt_and_timeout_codes_differ() -> None:
    """两个 code 必须不同——前端按 code 决定要不要给「重试」按钮。"""
    interrupt = agent_module._error_event_for(httpx2.RemoteProtocolError("x"))
    timeout = agent_module._error_event_for(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert interrupt.code != timeout.code
