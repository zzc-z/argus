"""agent 主循环测试。

不打真实网络——``_run_turn`` 是模块级私有函数，用 monkeypatch 换成桩，
让它按预设脚本返回 TurnResult。这样多轮循环、thinking 回传、终止条件
全都是确定的。
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.services import agent as agent_module
from app.services.agent import MAX_TURNS, NodeTracker, Stage, TurnResult, run_agent
from app.services.stream import (
    AgentEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    NodeEvent,
    ToolCallEvent,
)

# ── 测试替身 ──────────────────────────────────────────────────


def _turn(
    text: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    stop_reason: str | None = None,
    thinking: str | None = None,
) -> TurnResult:
    """构造一个 TurnResult。

    带 ``thinking`` 时会生成带 signature 的 thinking block——这是实测
    中转站真实返回的结构，用来验证回传路径。
    """
    content: list[dict[str, Any]] = []
    if thinking is not None:
        content.append({"type": "thinking", "thinking": thinking, "signature": "SIG-abc123"})
    if text:
        content.append({"type": "text", "text": text})
    calls = tool_calls or []
    content.extend(calls)
    return TurnResult(
        content=content,
        text=text,
        tool_calls=calls,
        stop_reason=stop_reason or ("tool_use" if calls else "end_turn"),
        input_tokens=100,
        output_tokens=50,
    )


def _tool_call(name: str = "tavily_search", call_id: str = "toolu_1", **inp: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": inp or {"query": "x"}}


def _stub_turns(
    monkeypatch: pytest.MonkeyPatch,
    script: list[TurnResult],
) -> list[list[dict[str, Any]]]:
    """按脚本依次返回 TurnResult，并记录每次调用时的 messages 快照。"""
    calls: list[list[dict[str, Any]]] = []
    remaining = list(script)

    async def _fake_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> TurnResult:
        calls.append([dict(m) for m in messages])
        if not remaining:
            raise AssertionError("agent 调用轮数超出脚本预期")
        return remaining.pop(0)

    monkeypatch.setattr(agent_module, "_run_turn", _fake_run_turn)
    return calls


async def _collect(question: str = "测试问题") -> list[AgentEvent]:
    """跑一轮 agent。不传 db/vec_engine —— 那条路径由 test_local_search_* 覆盖。

    不传时 agent 会摘掉 local_search 工具，所以这些用例只验循环本身。
    """
    return [event async for event in run_agent(question, user_id=1)]


# ── 单轮直答 ──────────────────────────────────────────────────


async def test_single_turn_produces_text_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型直接回答：产出正文 + done。"""
    _stub_turns(monkeypatch, [_turn(text="这是答案。")])
    events = await _collect()

    assert any(isinstance(e, DoneEvent) for e in events)
    deltas = [e for e in events if isinstance(e, DeltaEvent)]
    assert len(deltas) == 1
    assert deltas[0].text == "这是答案。"


async def test_done_carries_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    """done 必须带 session_id 与 token 数——前端 DAG 头部要显示。"""
    _stub_turns(monkeypatch, [_turn(text="答案")])
    done = next(e for e in await _collect() if isinstance(e, DoneEvent))

    assert done.session_id
    assert done.input_tokens == 100
    assert done.output_tokens == 50
    assert done.turns == 1
    assert done.truncated is False


# ── 工具轮 ────────────────────────────────────────────────────


async def test_tool_use_produces_tool_call_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """工具调用产出 start / end 两段事件。

    桩模型点名 tavily_search，而测试环境没配 TAVILY_API_KEY，所以 end 事件
    是 ok=False——这正是设计行为：工具失败不炸流，错误喂回模型让它降级。
    """
    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()]), _turn(text="根据搜索结果，答案是这样。")],
    )
    events = await _collect()

    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(calls) == 2
    assert calls[0].phase == "start"
    assert calls[0].name == "tavily_search"
    assert calls[1].phase == "end"
    assert calls[1].preview == "搜索工具未配置"


async def test_tool_result_packed_into_single_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一轮的多个 tool_result 必须打包进一条 user 消息。

    这是 Anthropic 协议的硬要求，逐条 append 成多条 user 消息会被拒。
    """
    calls = _stub_turns(
        monkeypatch,
        [
            _turn(tool_calls=[_tool_call(call_id="a"), _tool_call(call_id="b")]),
            _turn(text="答案"),
        ],
    )
    await _collect()

    # 第二轮请求时，tool_result 应该已经在一条 user 消息里
    second_round = calls[1]
    tool_messages = [m for m in second_round if m["role"] == "user"]
    packed = [m for m in tool_messages if isinstance(m["content"], list)
              and all(c.get("type") == "tool_result" for c in m["content"])]
    assert len(packed) == 1, "多个 tool_result 必须合并为一条 user 消息"
    assert len(packed[0]["content"]) == 2


async def test_thinking_block_echoed_back_with_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第二轮请求的 assistant 内容必须原样含 thinking + signature。

    signature 是上游校验用的，改动或丢失会导致工具轮直接被拒。
    """
    calls = _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()], thinking="先想想该搜什么"), _turn(text="答案")],
    )
    await _collect()

    assistant = [m for m in calls[1] if m["role"] == "assistant"]
    assert len(assistant) == 1
    thinking_blocks = [b for b in assistant[0]["content"] if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0]["signature"] == "SIG-abc123"
    assert thinking_blocks[0]["thinking"] == "先想想该搜什么"


async def test_thinking_never_emitted_as_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """思考过程是内部推理，不能发给用户——只给研究结论。"""
    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()], thinking="内部思考不该外泄"), _turn(text="答案")],
    )
    events = await _collect()

    all_text = " ".join(e.text for e in events if isinstance(e, DeltaEvent))
    assert "内部思考不该外泄" not in all_text
    assert "答案" in all_text


async def test_tool_error_feeds_back_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    """工具失败要变成 is_error 的 tool_result 喂回模型，流程继续。"""
    calls = _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call(name="不存在的工具")]), _turn(text="我换个方式回答")],
    )
    events = await _collect()

    assert any(isinstance(e, DoneEvent) for e in events)
    tool_end = next(e for e in events if isinstance(e, ToolCallEvent) and e.phase == "end")
    assert tool_end.ok is False

    packed = [
        m for m in calls[1]
        if m["role"] == "user" and isinstance(m["content"], list)
    ]
    assert packed[0]["content"][0]["is_error"] is True


# ── 终止条件 ──────────────────────────────────────────────────


async def test_max_turns_forces_finalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """轮数用尽时强制收尾，标 truncated，流程仍正常收尾。"""
    script = [_turn(tool_calls=[_tool_call()]) for _ in range(MAX_TURNS)]
    script.append(_turn(text="基于现有信息的最终答案"))
    _stub_turns(monkeypatch, script)

    events = await _collect()
    done = next(e for e in events if isinstance(e, DoneEvent))

    assert done.truncated is True
    assert any(isinstance(e, DeltaEvent) and "最终答案" in e.text for e in events)


async def test_max_tokens_marks_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """因长度上限被切断时标 truncated，但不报错。"""
    _stub_turns(monkeypatch, [_turn(text="很长很长…", stop_reason="max_tokens")])
    done = next(e for e in await _collect() if isinstance(e, DoneEvent))
    assert done.truncated is True


async def test_llm_failure_emits_error_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型挂掉要变成 error 事件，不能抛异常炸掉 SSE 流。"""

    async def _boom(client: Any, messages: list[Any], tools: Any) -> TurnResult:
        raise ConnectionError("中转站不可达")

    monkeypatch.setattr(agent_module, "_run_turn", _boom)
    events = await _collect()

    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].code == "llm_unavailable"
    # error 必须是流的最后一个事件——前端靠它收尾，否则一直转圈
    assert isinstance(events[-1], ErrorEvent)


async def test_failure_still_reports_consumed_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """崩溃后已烧掉的 token 不能丢——否则用量统计出现黑洞。

    DoneEvent 是唯一带 session_id 与 token 数的事件，崩溃时也必须发。
    """
    script = [
        _turn(tool_calls=[_tool_call()]),
        _turn(tool_calls=[_tool_call()]),
    ]

    async def _fail_on_third(client: Any, messages: list[Any], tools: Any) -> TurnResult:
        if not script:
            raise ConnectionError("第 3 轮挂掉")
        return script.pop(0)

    monkeypatch.setattr(agent_module, "_run_turn", _fail_on_third)
    events = await _collect()

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.turns == 3  # 2 轮成功 + 1 轮失败，失败那次也要计入
    # 失败那次上游没返回 usage，不凭空造 token——只报已知的 2 轮
    assert done.input_tokens == 200
    assert done.output_tokens == 100
    assert done.truncated is True
    # 崩溃路径同样要有 session_id，前端才追得回这次请求
    assert done.session_id


async def test_missing_api_key_emits_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 API key 时给出明确的 llm_not_configured 错误。"""

    def _raise() -> None:
        raise RuntimeError("ANTHROPIC_API_KEY 未配置")

    monkeypatch.setattr(agent_module, "get_anthropic_client", _raise)
    errors = [e for e in await _collect() if isinstance(e, ErrorEvent)]
    assert errors[0].code == "llm_not_configured"


# ── 节点约束（前端硬需求）─────────────────────────────────────


async def test_never_two_active_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """任一时刻 active 节点数 ≤ 1。

    前端 AgentDAG 用 findIndex 定位高亮轨道，两个 active 会让它算错位置。
    """
    _stub_turns(
        monkeypatch,
        [_turn(text="我要先说明一下", tool_calls=[_tool_call()]), _turn(text="最终答案")],
    )
    events = await _collect()

    active = 0
    for event in events:
        if not isinstance(event, NodeEvent):
            continue
        if event.lifecycle == "active":
            active += 1
            assert active == 1, f"出现第二个 active：{event.node_id}"
        else:
            active -= 1
        assert active in (0, 1), f"active 计数异常：{active}"
    assert active == 0, "结束时不应有未关闭的 active 节点"


async def test_all_five_nodes_appear(monkeypatch: pytest.MonkeyPatch) -> None:
    """DAG 走完 5 个节点——前端要看到完整推进过程。"""
    _stub_turns(monkeypatch, [_turn(tool_calls=[_tool_call()]), _turn(text="答案")])
    seen = {e.node_id for e in await _collect() if isinstance(e, NodeEvent)}

    assert seen == {s.value for s in Stage}


async def test_nodes_use_frontend_agreed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """节点 id 必须与前端 mock 约定的 5 个完全一致。"""
    _stub_turns(monkeypatch, [_turn(text="答案")])
    ids = {e.node_id for e in await _collect() if isinstance(e, NodeEvent)}

    assert ids <= {"supervisor", "researcher", "analyst", "writer", "critic"}


# ── NodeTracker 本身 ──────────────────────────────────────────


def test_tracker_rejects_double_activate() -> None:
    """未结束就激活下一个节点必须报错——这是前端硬约束。"""
    tracker = NodeTracker()
    tracker.activate(Stage.SUPERVISOR)
    with pytest.raises(AssertionError, match="尚未结束"):
        tracker.activate(Stage.RESEARCHER)


def test_tracker_switch_closes_previous() -> None:
    """switch 先关旧节点再开新节点，保证不多 active。"""
    tracker = NodeTracker()
    events = tracker.switch(Stage.WRITER)  # 从未激活直接切，关闭事件为 None
    assert len(events) == 1
    assert events[0].lifecycle == "active"

    events = tracker.switch(Stage.CRITIC)
    assert [e.lifecycle for e in events] == ["completed", "active"]


def test_tracker_complete_on_idle_returns_none() -> None:
    assert NodeTracker().complete() is None


# ── 提示词组装 ────────────────────────────────────────────────


def test_prompt_warns_when_search_unavailable() -> None:
    """没配 Tavily 时要在提示词里明说，否则模型会编造引用。"""
    prompt = agent_module._build_user_prompt("最新政策是什么", (), has_local=False)
    assert "未配置联网搜索工具" in prompt


def test_prompt_warns_when_local_unavailable() -> None:
    """没有数据库连接时也要明说——否则模型会声称查过用户资料。"""
    from app.services.tools import TAVILY_SEARCH_SPEC

    prompt = agent_module._build_user_prompt("问题", (TAVILY_SEARCH_SPEC,), has_local=False)
    assert "无法检索你的私有资料" in prompt
    assert "未配置联网搜索工具" not in prompt


def test_prompt_untouched_when_both_available() -> None:
    """两路都可用时提示词原样透传，不加任何警告。"""
    from app.services.tools import LOCAL_SEARCH_SPEC, TAVILY_SEARCH_SPEC

    prompt = agent_module._build_user_prompt(
        "问题", (TAVILY_SEARCH_SPEC, LOCAL_SEARCH_SPEC), has_local=True
    )
    assert prompt == "问题"
