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

import asyncio
from collections.abc import AsyncIterator
from itertools import pairwise
from typing import Any

import httpx
import httpx2
import pytest
from anthropic import APIConnectionError, APITimeoutError

from app.services import agent as agent_module
from app.services.agent import _run_turn
from app.services.errors import error_event_for
from app.services.llm import (
    STREAM_INTERRUPT_BACKOFF_SECONDS,
    STREAM_INTERRUPT_RETRIES,
    is_stream_interrupt,
    is_timeout,
)
from tests.conftest import collect_turn

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


class _FakeDelta:
    """模拟 SDK 的 text_delta。"""

    def __init__(self, text: str) -> None:
        self.type = "text_delta"
        self.text = text


class _FakeDeltaEvent:
    """模拟 SDK 的 content_block_delta 事件。"""

    def __init__(self, text: str) -> None:
        self.type = "content_block_delta"
        self.delta = _FakeDelta(text)


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

    async def __aiter__(self) -> AsyncIterator[Any]:
        """产出假的上游事件——``_run_turn`` 消费它们实现流式展示。"""
        for ch in self._message.content[0].model_dump(exclude_none=True).get("text", ""):
            yield _FakeDeltaEvent(ch)

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
    result = await collect_turn(client, [{"role": "user", "content": "q"}], ())

    assert result.text == "答案"
    assert client.messages.calls == 2


async def test_gives_up_after_max_retries() -> None:
    """重试有上界。断言**精确**尝试次数——「至少重试过」守不住上界。"""
    client = _FlakyClient(_FakeMessage("答案"), fail_times=99)
    expected_attempts = STREAM_INTERRUPT_RETRIES + 1

    with pytest.raises(httpx2.RemoteProtocolError):
        await collect_turn(client, [{"role": "user", "content": "q"}], ())

    assert client.messages.calls == expected_attempts


async def test_business_error_not_retried() -> None:
    """400 类错误不重发——重试一万次也是同样的错。"""
    client = _FlakyClient(_FakeMessage("答案"), fail_times=0, exc=ValueError("bad request"))

    with pytest.raises(ValueError):
        await collect_turn(client, [{"role": "user", "content": "q"}], ())

    assert client.messages.calls == 1


async def test_timeout_not_retried() -> None:
    """超时不重发。"""
    timeout = APITimeoutError(request=httpx.Request("POST", "http://x"))
    client = _FlakyClient(_FakeMessage("答案"), fail_times=0, exc=timeout)

    with pytest.raises(APITimeoutError):
        await collect_turn(client, [{"role": "user", "content": "q"}], ())

    assert client.messages.calls == 1


async def test_retry_sends_identical_request() -> None:
    """重发的是**同一个**请求——不能因为重试改了载荷。

    改了载荷意味着模型看到的上下文变了，产出可能与原计划不同。
    """
    client = _FlakyClient(_FakeMessage("答案"), fail_times=1)
    await collect_turn(client, [{"role": "user", "content": "原问题"}], ())

    assert client.messages.calls == 2


# ── 错误文案分类 ──────────────────────────────────────────────


def test_error_event_for_stream_interrupt() -> None:
    event = error_event_for(httpx2.RemoteProtocolError("x"))
    assert event.code == "llm_stream_interrupted"
    assert "中断" in event.message


def test_error_event_for_timeout() -> None:
    event = error_event_for(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert event.code == "llm_timeout"


def test_error_event_for_unknown() -> None:
    """归不出类的异常报 internal_error，不是「模型服务不可用」。

    ``ValueError`` 是我们自己的 bug。报成「模型服务暂时不可用」会让
    排查方向指向中转站，而真因在代码里——这正是「具体问题要有具体
    报错」要消灭的那类误导。
    """
    event = error_event_for(ValueError("x"))
    assert event.code == "internal_error"
    assert event.retryable is False


def test_error_event_for_connection_failure() -> None:
    """连不上模型服务 —— 与「我们自己的 bug」分开。"""
    event = error_event_for(ConnectionError("中转站不可达"))
    assert event.code == "llm_unavailable"
    assert event.retryable is True


def test_stream_interrupt_and_timeout_codes_differ() -> None:
    """两个 code 必须不同——前端按 code 决定要不要给「重试」按钮。"""
    interrupt = error_event_for(httpx2.RemoteProtocolError("x"))
    timeout = error_event_for(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert interrupt.code != timeout.code


# ── 消费途中断流：已发出的正文要作废 ──────────────────────────


class _MidStreamFailure:
    """吐了一半才断的上游——模拟「消费途中被掐断」。"""

    def __init__(self, message: _FakeMessage, emit: int) -> None:
        self._message = message
        self._emit = emit

    async def __aenter__(self) -> "_MidStreamFailure":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def __aiter__(self) -> AsyncIterator[Any]:
        text = self._message.content[0].model_dump(exclude_none=True).get("text", "")
        for ch in text[: self._emit]:
            yield _FakeDeltaEvent(ch)
        raise httpx2.RemoteProtocolError("incomplete chunked read")

    async def get_final_message(self) -> _FakeMessage:
        return self._message


class _MidStreamMessages:
    """第一次吐一半就断，第二次正常。

    断流点在**消费途中**——这才是真实的中转站行为（实测
    ``httpx2.RemoteProtocolError: incomplete chunked read``）。
    """

    def __init__(self, message: _FakeMessage, emit: int) -> None:
        self._message = message
        self._emit = emit
        self.calls = 0

    def stream(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls == 1:
            return _MidStreamFailure(self._message, self._emit)
        return _FlakyStream(self._message, [0])


class _MidStreamClient:
    def __init__(self, message: _FakeMessage, emit: int) -> None:
        self.messages = _MidStreamMessages(message, emit)


async def test_retry_resets_already_sent_text() -> None:
    """消费途中断流后重发，必须先发 reset 让前端清掉已收的正文。

    ## 要防的回归

    改成真流式之后，正文在**上游还在吐的时候**就已经发到前端了。
    断流重发会从头再生成一遍，而上游有随机性（实测同一 prompt 连发 4 次，
    字数 1653/1155/1737/2164 各不相同）——没法靠裁剪前缀去重。

    少了 reset，用户会看到同一段正文出现两遍：前半截是断流前的，
    后半截是重发后的。

    这条断言盯的是**事件序列**：正文片段之后必须紧跟一个 reset，
    然后才是重发后的正文。
    """
    message = _FakeMessage(
        "这是一段会在中途断流的正文，用来验证重发时的重置行为，"
        "它必须足够长才能被切片器切出至少一片出来。"
    )
    # 切断点要够长（> 切片器的 36 字门槛），否则第一轮一个字都发不出去，
    # 也就没有「已发正文要作废」这回事——那测的是另一条路径。
    client = _MidStreamClient(message, emit=45)

    kinds: list[str] = []
    texts: list[str] = []
    async for chunk in _run_turn(client, [{"role": "user", "content": "q"}], ()):
        kinds.append(chunk.kind)
        if chunk.kind == "text":
            texts.append(chunk.text)
        if chunk.kind == "reset":
            texts.append("")

    assert "reset" in kinds, f"断流重发必须发 reset，实际事件：{kinds}"
    reset_at = kinds.index("reset")
    assert reset_at > 0, "reset 之前应当已经发过正文（否则没有可清的东西）"
    assert "result" in kinds
    assert kinds[-1] == "result", f"result 必须是最后一个事件，实际：{kinds}"


async def test_no_reset_when_nothing_was_sent() -> None:
    """建连就断（一个字都没发）时不该发 reset。

    纯工具轮断流时前端正文区是空的，发 reset 没有意义——多一个
    无谓的帧，前端还要多跑一次清空逻辑。
    """
    client = _FlakyClient(_FakeMessage("答案"), fail_times=1)

    kinds: list[str] = []
    async for chunk in _run_turn(client, [{"role": "user", "content": "q"}], ()):
        kinds.append(chunk.kind)

    assert "reset" not in kinds, f"没发过正文就不该有 reset，实际：{kinds}"


# ── 退避：必须指数递增，不能是固定间隔 ────────────────────────


async def test_retry_backoff_is_exponential(monkeypatch: pytest.MonkeyPatch) -> None:
    """重发之间的等待必须**指数递增**。

    ## 要防的回归（2026-11-01 实测）

    当时断连的根因是本机网络层抖动——Tavily 与 Anthropic 两个不同的服务
    在**同一秒**断开。日志时间线：

    ```
    17:10:53  POST /api/v1/research/ask 200
    17:11:01  模型流被中断，第 1 次重发整轮请求
    17:11:01  模型流被中断，第 2 次重发整轮请求
    17:11:01  模型流被中断，第 3 次重发整轮请求
    ```

    3 次重发挤在同一秒里全挂——**固定的 1 秒间隔让所有重试都落在同一个
    坏窗口内**，白等。指数退避把最后一次重发推到 3 秒之后。

    断言**递增**而不是断言具体秒数：写死「等于 2.0」的断言在参数调整后
    会失效，而「后一次比前一次长」是真正要守住的性质。
    """
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        await real_sleep(0)  # 不真的等

    monkeypatch.setattr(agent_module.asyncio, "sleep", _fake_sleep)

    client = _FlakyClient(_FakeMessage("答案"), fail_times=99)
    with pytest.raises(httpx2.RemoteProtocolError):
        await collect_turn(client, [{"role": "user", "content": "q"}], ())

    assert len(sleeps) == STREAM_INTERRUPT_RETRIES, f"退避次数不对：{sleeps}"
    # 严格递增——不是「非递减」。``sorted(sleeps) == sleeps`` 只能防递减，
    # 固定间隔（[1.0, 1.0]）照样能过，是废断言。真正抓住「固定间隔」的
    # 是这条与下面那条。
    assert all(a < b for a, b in pairwise(sleeps)), f"退避没有严格递增：{sleeps}"
    assert sleeps[-1] > sleeps[0], f"退避不是指数增长：{sleeps}"
    assert sleeps[0] == STREAM_INTERRUPT_BACKOFF_SECONDS, f"退避基数不对：{sleeps}"
