"""思考摘要流（「AI 正在想什么」）的测试。

覆盖从上游 ``thinking_delta`` 到前端 ``ThinkingEvent`` 的整条路径：

- 请求必须显式要 ``display="summarized"``——Sonnet 5 默认 ``omitted``，
  thinking 文本是空串，前端什么都显示不了。
- ``_run_turn`` 把思考增量切成 ``kind="thinking"`` 片段，**一个字不丢**、
  **先于正文**、**不混进正文**，且帧数受控（不逐字一帧挤爆 run 缓冲）。
- 断流重发时发 ``thinking_reset``，否则前端会看到同一段思考两遍。
- 主循环把片段翻译成带轮号的 ``ThinkingEvent``，且思考不进正文 / 落盘。

每条测试注明「哪种错误实现下会红」。
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest

from app.services import agent as agent_module
from app.services import agent_turn
from app.services.agent import TurnChunk, TurnResult, run_agent
from app.services.agent_turn import THINKING_CHUNK_SIZE, _build_turn_request, _run_turn
from app.services.credentials import resolve_env_credentials
from app.services.stream import DeltaEvent, DoneEvent, ErrorEvent, ThinkingEvent, encode_frame

_CREDS = resolve_env_credentials()

# 足够长：超过切片器「攒够 1.5 片才切」的门槛，能切出多帧。
_LONG_THINKING = (
    "用户问的是近三年的营收变化，先确认口径：按财年还是自然年。"
    "再看私有资料里有没有年报，没有的话联网查公开披露，"
    "最后核对两处数字是否一致，不一致要标出来源差异。"
) * 2

# ── 上游替身 ──────────────────────────────────────────────────


class _Obj:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


def _thinking_delta(text: str) -> _Obj:
    return _Obj(type="content_block_delta", delta=_Obj(type="thinking_delta", thinking=text))


def _text_delta(text: str) -> _Obj:
    return _Obj(type="content_block_delta", delta=_Obj(type="text_delta", text=text))


_STOP = _Obj(type="content_block_stop")


class _FinalMessage:
    def __init__(self, text: str) -> None:
        self._content = [
            {"type": "thinking", "thinking": "摘要", "signature": "SIG"},
            {"type": "text", "text": text},
        ]
        self.stop_reason = "end_turn"
        self.usage = _Obj(input_tokens=10, output_tokens=20)

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        return {"content": self._content}


class _ScriptedStream:
    """按脚本吐事件；``fail_at`` 给定时在该位置断流（中转站的真实断法）。"""

    def __init__(self, events: list[_Obj], final_text: str, fail_at: int | None = None) -> None:
        self._events = events
        self._final = _FinalMessage(final_text)
        self._fail_at = fail_at

    async def __aenter__(self) -> "_ScriptedStream":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def __aiter__(self) -> AsyncIterator[_Obj]:
        for index, event in enumerate(self._events):
            if index == self._fail_at:
                raise httpx2.RemoteProtocolError("incomplete chunked read")
            yield event

    async def get_final_message(self) -> _FinalMessage:
        return self._final


class _ScriptedClient:
    def __init__(self, *streams: _ScriptedStream) -> None:
        self._streams = list(streams)
        self.messages = self

    def stream(self, **kwargs: Any) -> _ScriptedStream:
        return self._streams.pop(0)


def _thinking_then_text(thinking: str, text: str) -> list[_Obj]:
    """上游真实顺序：thinking 块（逐字）→ stop → text 块（逐字）→ stop。"""
    return [
        *(_thinking_delta(ch) for ch in thinking),
        _STOP,
        *(_text_delta(ch) for ch in text),
        _STOP,
    ]


async def _chunks(client: _ScriptedClient) -> list[TurnChunk]:
    return [c async for c in _run_turn(client, [{"role": "user", "content": "q"}], (), _CREDS)]


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """断流重发的指数退避不真等。"""
    real_sleep = agent_turn.asyncio.sleep

    async def _fake_sleep(_delay: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(agent_turn.asyncio, "sleep", _fake_sleep)


# ── 请求 ──────────────────────────────────────────────────────


def test_request_asks_for_summarized_thinking() -> None:
    """不写 display 时 Sonnet 5 默认 omitted，思考文本为空串。

    红：删掉 ``"display": "summarized"``。
    """
    request = _build_turn_request([{"role": "user", "content": "q"}], (), _CREDS)
    assert request["thinking"]["display"] == "summarized"
    # 预算方案不变：display 只管可见性。
    assert request["thinking"]["type"] == "enabled"
    assert request["thinking"]["budget_tokens"] < request["max_tokens"]


# ── _run_turn 的切片 ──────────────────────────────────────────


async def test_thinking_chunks_are_lossless_and_precede_text() -> None:
    """思考一个字不丢、全部先于正文、且不混进正文。

    红：不消费 thinking_delta（拼出来是空串）；把思考当 text 发
    （正文里出现思考）；只在流末 flush（思考排到正文后面）。
    """
    client = _ScriptedClient(
        _ScriptedStream(_thinking_then_text(_LONG_THINKING, "结论。"), "结论。")
    )
    chunks = await _chunks(client)

    kinds = [c.kind for c in chunks]
    thinking = "".join(c.text for c in chunks if c.kind == "thinking")
    text = "".join(c.text for c in chunks if c.kind == "text")

    assert thinking == _LONG_THINKING
    assert text == "结论。"
    last_thinking = max(i for i, k in enumerate(kinds) if k == "thinking")
    first_text = kinds.index("text")
    assert last_thinking < first_text, f"思考必须全部先于正文：{kinds}"
    assert kinds[-1] == "result"


async def test_thinking_frames_are_coalesced() -> None:
    """上游逐字吐思考时，后端要合并成帧，不能一字一帧。

    帧数直接占 run 的事件缓冲（满了从最老的丢，第一帧 run 会被挤掉）。
    红：每个 thinking_delta 原样转发（帧数 == 字数）。
    """
    client = _ScriptedClient(_ScriptedStream(_thinking_then_text(_LONG_THINKING, "好"), "好"))
    frames = [c for c in await _chunks(client) if c.kind == "thinking"]

    assert len(frames) > 1, "长思考应当分多帧推送，前端才看得到它在动"
    assert len(frames) <= len(_LONG_THINKING) // (THINKING_CHUNK_SIZE // 2)


async def test_short_thinking_flushed_at_block_stop() -> None:
    """不足一帧的短思考要在 thinking 块结束时发出，不能压到正文后面。

    红：只在整条流结束时 flush 思考缓冲（短思考会排在正文之后）。

    正文必须够长，打字机在流**中途**就开始吐；正文太短的话打字机也等到
    流末才 flush，两边一起出来，顺序碰巧对，测不出这个 bug。
    """
    text = "营收三年复合增长约百分之十二，主要来自海外业务，国内持平，毛利率略降。" * 2
    client = _ScriptedClient(_ScriptedStream(_thinking_then_text("先查年报。", text), text))
    kinds = [c.kind for c in await _chunks(client)]

    assert "thinking" in kinds
    assert kinds.index("thinking") < kinds.index("text"), f"短思考被压到了正文后面：{kinds}"


async def test_omitted_thinking_yields_no_chunks() -> None:
    """display=omitted（或中转站不实现 summarized）时 thinking_delta 是空串：不发空帧。

    红：对空串也发 thinking 片段（前端收到一串空帧）。
    """
    events = [_thinking_delta(""), _thinking_delta(""), _STOP, _text_delta("结论。"), _STOP]
    kinds = [c.kind for c in await _chunks(_ScriptedClient(_ScriptedStream(events, "结论。")))]

    assert "thinking" not in kinds
    assert "text" in kinds


async def test_interrupt_mid_thinking_emits_thinking_reset() -> None:
    """思考发到一半断流：重发前必须发 thinking_reset，否则前端思考区出现两遍。

    红：重试分支只判 sent_any（正文）而漏了思考。
    """
    events = _thinking_then_text(_LONG_THINKING, "结论。")
    client = _ScriptedClient(
        _ScriptedStream(events, "结论。", fail_at=len(_LONG_THINKING) - 5),
        _ScriptedStream(events, "结论。"),
    )
    chunks = await _chunks(client)
    kinds = [c.kind for c in chunks]

    assert "thinking_reset" in kinds, f"断流重发必须发 thinking_reset：{kinds}"
    reset_at = kinds.index("thinking_reset")
    assert "thinking" in kinds[:reset_at], "reset 之前应当已经发过思考"
    after = "".join(c.text for c in chunks[reset_at:] if c.kind == "thinking")
    assert after == _LONG_THINKING, "重发后的思考应当完整重来一遍"
    assert "reset" not in kinds, "断在思考阶段时还没发过正文，不该发正文 reset"
    assert kinds[-1] == "result"


# ── 主循环：片段 → ThinkingEvent ───────────────────────────────


def _turn(text: str = "", tool_calls: list[dict[str, Any]] | None = None) -> TurnResult:
    calls = tool_calls or []
    content: list[dict[str, Any]] = [{"type": "thinking", "thinking": "x", "signature": "S"}]
    if text:
        content.append({"type": "text", "text": text})
    return TurnResult(
        content=[*content, *calls],
        text=text,
        tool_calls=calls,
        stop_reason="tool_use" if calls else "end_turn",
        input_tokens=1,
        output_tokens=1,
    )


async def test_agent_emits_thinking_events_per_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """每轮的思考带轮号发出；思考不进正文，也不进落盘报告。

    红：思考塞进 DeltaEvent；没带轮号（多轮思考混成一段）；
    主循环用 else 兜 result 时没给 thinking 加分支（result 被覆盖成 None → 报错）。
    """
    script = [
        (
            "先查一下年报",
            _turn(tool_calls=[{"type": "tool_use", "id": "t1", "name": "dedup", "input": {}}]),
        ),
        ("证据够了，写结论", _turn(text="结论正文。")),
    ]

    async def _fake_run_turn(*_args: Any) -> AsyncIterator[TurnChunk]:
        thinking, result = script.pop(0)
        yield TurnChunk(kind="thinking", text=thinking)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _fake_run_turn)
    events = [e async for e in run_agent("测试问题", user_id=1)]

    thinking = [e for e in events if isinstance(e, ThinkingEvent)]
    assert [(e.turn, e.text) for e in thinking] == [(0, "先查一下年报"), (1, "证据够了，写结论")]

    body = "".join(e.text for e in events if isinstance(e, DeltaEvent))
    assert "年报" not in body
    assert "写结论" not in body
    assert body == "结论正文。"
    assert any(isinstance(e, DoneEvent) for e in events)


_TOOL = {"type": "tool_use", "id": "t1", "name": "dedup", "input": {}}


def _stub_chunks(monkeypatch: pytest.MonkeyPatch, runs: list[list[TurnChunk]]) -> None:
    """每次调用 ``_run_turn`` 按顺序吐出一组预设片段（含主循环与强制收尾）。"""
    remaining = list(runs)

    async def _fake_run_turn(*_args: Any) -> AsyncIterator[TurnChunk]:
        for chunk in remaining.pop(0):
            yield chunk

    monkeypatch.setattr(agent_module, "_run_turn", _fake_run_turn)


def _result(result: TurnResult) -> TurnChunk:
    return TurnChunk(kind="result", result=result)


async def test_agent_forwards_thinking_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``thinking_reset`` 片段要翻译成 ``ThinkingEvent(reset=True)``，轮号不变。

    红：``_thinking_event`` 丢掉 reset 标志（断流后前端思考区出现两遍）。
    """
    _stub_chunks(
        monkeypatch,
        [
            [
                TurnChunk(kind="thinking", text="想到一半"),
                TurnChunk(kind="thinking_reset"),
                TurnChunk(kind="thinking", text="重来"),
                TurnChunk(kind="text", text="结论。"),
                _result(_turn(text="结论。")),
            ]
        ],
    )
    events = [e async for e in run_agent("测试问题", user_id=1)]

    thinking = [(e.turn, e.text, e.reset) for e in events if isinstance(e, ThinkingEvent)]
    assert thinking == [(0, "想到一半", False), (0, "", True), (0, "重来", False)]


async def test_finalize_thinking_turn_and_reset_keeps_prior_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """强制收尾：思考轮号为 MAX_TURNS；断流 reset 只清收尾这一段，保留前几轮正文。

    红：收尾的思考沿用 MAX_TURNS-1（并进最后一个工具轮）；收尾的 reset
    不带 reset_keep_chars（前端 ``slice(0, 0)`` 把整篇报告清空，落盘却完整）。
    """
    turn_texts = [f"第{i}轮的正文。" for i in range(agent_module.MAX_TURNS)]
    runs = [
        [TurnChunk(kind="text", text=t), _result(_turn(text=t, tool_calls=[_TOOL]))]
        for t in turn_texts
    ]
    runs.append(
        [
            TurnChunk(kind="thinking", text="收尾思考"),
            TurnChunk(kind="text", text="断流前的半截"),
            TurnChunk(kind="reset"),
            TurnChunk(kind="text", text="收尾正文。"),
            _result(_turn(text="收尾正文。")),
        ]
    )
    _stub_chunks(monkeypatch, runs)
    events = [e async for e in run_agent("测试问题", user_id=1)]

    thinking = [(e.turn, e.text) for e in events if isinstance(e, ThinkingEvent)]
    assert thinking == [(agent_module.MAX_TURNS, "收尾思考")]

    resets = [e for e in events if isinstance(e, DeltaEvent) and e.reset]
    assert len(resets) == 1
    assert resets[0].reset_keep_chars == sum(len(t) for t in turn_texts)


async def test_unknown_chunk_kind_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """未知的片段类型要显式报错，不能被兜底分支吞掉。

    红：消费方用 ``else`` 兜 result——未知 kind 先把 result 设成 None，
    后面真正的 result 片段又把它覆盖回来，整轮被当成正常结束，没有 error；
    或静默忽略未知 kind。

    崩溃路径按约定先发 done 再发 error（``agent_failures._handle_crash``），
    所以断言 error 是最后一帧，并从日志确认报的是真因。
    """
    _stub_chunks(
        monkeypatch,
        [[TurnChunk(kind="bogus"), TurnChunk(kind="text", text="答"), _result(_turn(text="答"))]],
    )
    events = [e async for e in run_agent("测试问题", user_id=1)]

    assert isinstance(events[-1], ErrorEvent)
    assert any(
        r.exc_info and "未处理的 TurnChunk kind：bogus" in str(r.exc_info[1])
        for r in caplog.records
    ), "崩溃日志里应当是「未处理的 kind」这个真因"


async def test_unknown_chunk_kind_in_finalize_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """同上，但发生在强制收尾 ``_finalize`` 里——那是第二个消费方。

    红：``_finalize`` 写回 ``else: final = chunk.result``（未知 kind 被吞，正常结束）。
    """
    runs = [
        [TurnChunk(kind="text", text="正文。"), _result(_turn(text="正文。", tool_calls=[_TOOL]))]
        for _ in range(agent_module.MAX_TURNS)
    ]
    runs.append([TurnChunk(kind="bogus"), _result(_turn(text="收尾。"))])
    _stub_chunks(monkeypatch, runs)
    events = [e async for e in run_agent("测试问题", user_id=1)]

    assert isinstance(events[-1], ErrorEvent)
    assert any(
        r.exc_info and "未处理的 TurnChunk kind：bogus" in str(r.exc_info[1])
        for r in caplog.records
    ), "崩溃日志里应当是「未处理的 kind」这个真因"


def test_thinking_event_frame_type() -> None:
    """SSE 帧的 type 是 thinking——前端按这个字段分流。

    红：漏了 ``_type_name`` 映射（KeyError）或写成别的名字。
    """
    frame = encode_frame(ThinkingEvent(turn=2, text="想"))
    assert frame.startswith(b'data: {"type": "thinking"')
    assert '"turn": 2' in frame.decode()
