"""_run_turn 的请求构造与响应解析测试。

这一层是 agent 循环与 Anthropic SDK 之间**唯一的接缝**，也是最脆的一环：
上游返回什么、我们怎么转成下一轮能接受的载荷，全在这里。

不打真实网络——``client.messages.stream`` 是 async context manager，
用桩替换它就能喂进任意形状的上游响应。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.services import agent as agent_module
from app.services.agent import _run_turn
from app.services.tools import DEDUP_SPEC, TAVILY_SEARCH_SPEC

# ── 上游响应的替身 ────────────────────────────────────────────


class _FakeBlock:
    """模拟 SDK 的 content block。只有 model_dump() 会被用到。"""

    def __init__(self, **fields: Any) -> None:
        self._fields = fields

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if not exclude_none:
            return dict(self._fields)
        return {k: v for k, v in self._fields.items() if v is not None}


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeMessage:
    """模拟 SDK 的 Message。代码调的是它自己的 model_dump()，
    它再转发给每个 block 的 model_dump()。"""

    def __init__(self, blocks: list[_FakeBlock], stop_reason: str | None) -> None:
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(input_tokens=123, output_tokens=45)

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        return {"content": [b.model_dump(exclude_none) for b in self.content]}


class _FakeStream:
    """async context manager，yield 自己后 get_final_message 返回预设响应。"""

    def __init__(self, message: _FakeMessage) -> None:
        self._message = message
        self.entered = False

    async def __aenter__(self) -> "_FakeStream":
        self.entered = True
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get_final_message(self) -> _FakeMessage:
        return self._message


class _FakeMessages:
    def __init__(self, message: _FakeMessage) -> None:
        self._message = message

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.last_kwargs = kwargs
        return _FakeStream(self._message)


class _FakeClient:
    def __init__(self, message: _FakeMessage) -> None:
        self.messages = _FakeMessages(message)


def _thinking(signature: str = "SIG-REAL", text: str = "先确认要查什么") -> _FakeBlock:
    return _FakeBlock(type="thinking", thinking=text, signature=signature)


def _text(text: str, citations: Any = None) -> _FakeBlock:
    return _FakeBlock(type="text", text=text, citations=citations)


def _tool_use(name: str = "tavily_search", **inp: Any) -> _FakeBlock:
    return _FakeBlock(type="tool_use", id="toolu_x", name=name, input=inp or {"query": "x"})


# ── 核心约束：signature 原样回传 ──────────────────────────────


async def test_signature_survives_model_dump() -> None:
    """thinking block 的 signature 必须完整保留在回传载荷里。

    这是整个 tool calling 能跑通的前提——signature 是上游用来防篡改的，
    丢了或被 exclude_none 洗掉，第二轮请求直接被拒。
    """
    message = _FakeMessage([_thinking(), _text("好的，我来查。"), _tool_use()], "tool_use")
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    thinking_blocks = [b for b in result.content if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0]["signature"] == "SIG-REAL"
    assert thinking_blocks[0]["thinking"] == "先确认要查什么"


async def test_exclude_none_strips_null_citations() -> None:
    """无引用时 text block 的 citations 是 None，不能原样塞回去。

    中转站实测能接受，但直连官方 API 的严格模式可能拒收。
    """
    message = _FakeMessage([_text("无引用的正文")], "end_turn")
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    text_block = next(b for b in result.content if b.get("type") == "text")
    assert "citations" not in text_block
    assert text_block["text"] == "无引用的正文"


async def test_citations_kept_when_present() -> None:
    """有引用时 citations 要保留——不能被 exclude_none 误伤。"""
    message = _FakeMessage([_text("带引用的正文", citations=[{"type": "char_location"}])], "end_turn")
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    text_block = next(b for b in result.content if b.get("type") == "text")
    assert text_block["citations"] == [{"type": "char_location"}]


# ── 解析 ──────────────────────────────────────────────────────


async def test_text_concatenated_across_blocks() -> None:
    """多个 text block 要拼成完整正文，不能只取第一个。"""
    message = _FakeMessage([_thinking(), _text("第一段。"), _text("第二段。")], "end_turn")
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    assert result.text == "第一段。第二段。"


async def test_tool_calls_filtered_from_content() -> None:
    """tool_use block 要能被单独挑出来执行。"""
    message = _FakeMessage(
        [_text("我去查一下"), _tool_use("tavily_search"), _tool_use("dedup")],
        "tool_use",
    )
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    assert [c["name"] for c in result.tool_calls] == ["tavily_search", "dedup"]
    # content 里也要保留，供下一轮回传
    assert len(result.content) == 3


async def test_usage_parsed() -> None:
    """token 计数要被读出来——前端 DAG 头部要显示。"""
    message = _FakeMessage([_text("答案")], "end_turn")
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    assert result.input_tokens == 123
    assert result.output_tokens == 45


async def test_stop_reason_none_falls_back() -> None:
    """上游没给 stop_reason 时兜底成 end_turn，不能是 None。"""
    message = _FakeMessage([_text("答案")], None)
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    assert result.stop_reason == "end_turn"


# ── 请求构造 ──────────────────────────────────────────────────


async def test_request_shape() -> None:
    """请求必须带 model / max_tokens / system / messages。"""
    message = _FakeMessage([_text("答案")], "end_turn")
    client = _FakeClient(message)

    await _run_turn(client, [{"role": "user", "content": "问题"}], (TAVILY_SEARCH_SPEC, DEDUP_SPEC))
    kwargs = client.messages.last_kwargs

    assert kwargs["model"]
    assert kwargs["max_tokens"] == agent_module.MAX_OUTPUT_TOKENS
    assert "Argus" in kwargs["system"]
    assert kwargs["messages"] == [{"role": "user", "content": "问题"}]
    assert [t["name"] for t in kwargs["tools"]] == ["tavily_search", "dedup"]


async def test_tools_omitted_when_empty() -> None:
    """工具列表为空时不要传 tools 参数——部分上游对空数组敏感。"""
    message = _FakeMessage([_text("答案")], "end_turn")
    client = _FakeClient(message)

    await _run_turn(client, [{"role": "user", "content": "问题"}], ())
    assert "tools" not in client.messages.last_kwargs


async def test_empty_text_when_only_thinking() -> None:
    """只有 thinking 没有 text 时，正文应为空串而不是 None。"""
    message = _FakeMessage([_thinking()], "tool_use")
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    assert result.text == ""
    assert result.tool_calls == []


# ── 上下文回传完整性 ──────────────────────────────────────────


async def test_content_is_json_serializable() -> None:
    """回传载荷必须能 JSON 序列化——它是直接塞进 messages 的。"""
    message = _FakeMessage([_thinking(), _text("正文"), _tool_use()], "tool_use")
    result = await _run_turn(_FakeClient(message), [{"role": "user", "content": "q"}], (DEDUP_SPEC,))

    dumped = json.dumps({"role": "assistant", "content": result.content}, ensure_ascii=False)
    assert "SIG-REAL" in dumped
    assert "正文" in dumped


async def test_roundtrip_through_messages() -> None:
    """端到端：上游响应 → TurnResult.content → 直接当下一轮 messages 用。

    这条测试守着最核心的闭环：第 2 轮请求的 messages 里必须带着
    第 1 轮完整的 assistant 内容（含 signature），否则上游拒收。
    """
    first = _FakeMessage([_thinking(), _text("我要查一下"), _tool_use()], "tool_use")
    messages: list[dict[str, Any]] = [{"role": "user", "content": "问题"}]

    turn1 = await _run_turn(_FakeClient(first), messages, (DEDUP_SPEC,))
    messages.append({"role": "assistant", "content": turn1.content})
    messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_x", "content": "结果"}]})

    second = _FakeMessage([_text("最终答案")], "end_turn")
    client = _FakeClient(second)
    await _run_turn(client, messages, ())

    sent = client.messages.last_kwargs["messages"]
    assert sent[0]["role"] == "user"
    assert sent[1]["role"] == "assistant"
    assert sent[2]["role"] == "user"

    assistant_blocks = sent[1]["content"]
    assert any(
        b.get("type") == "thinking" and b.get("signature") == "SIG-REAL"
        for b in assistant_blocks
    ), "第二轮必须带着第一轮的 thinking + signature"
