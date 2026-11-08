"""agent 主循环与 Supervisor / Analyst / Critic 三个节点的集成测试。

覆盖的四个不变量（都是这轮改出来的）：

1. **critic 的耗时包含校验本身**——以前校验跑在节点窗口之外，DAG 上
   显示 0.0s 而实际跑了最多 6 分钟。
2. **analyst 真干活**——有检索证据时它会激活并产出核对结论，不是占位。
3. **多轮节点的耗时是累计的**——researcher/writer 会被激活多次。
4. **节点产出摘要**——用户能看到这个节点干了什么，而不只是角色说明。
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.services import agent as agent_module
from app.services import stages
from app.services.agent import TurnChunk, TurnResult, run_agent
from app.services.citation import Reference
from app.services.stream import FaithfulnessEvent, NodeEvent


def _turn(
    text: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
) -> TurnResult:
    calls = tool_calls or []
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.extend(calls)
    return TurnResult(
        content=content,
        text=text,
        tool_calls=calls,
        stop_reason="tool_use" if calls else "end_turn",
        input_tokens=100,
        output_tokens=50,
    )


def _tool_call(call_id: str = "toolu_1") -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": "tavily_search", "input": {"query": "x"}}


def _reference(n: int = 1, chunk_id: int = 1) -> Reference:
    return Reference(
        n=n,
        chunk_id=chunk_id,
        source_id=1,
        chunk_index=0,
        page=None,
        title=f"来源{n}",
        excerpt="这是一段证据原文",
        recall="BM25",
    )


def _nodes(events: list[Any]) -> list[NodeEvent]:
    return [e for e in events if isinstance(e, NodeEvent)]


def _lifecycle(events: list[Any]) -> list[tuple[str, str]]:
    return [(e.node_id, e.lifecycle) for e in _nodes(events)]


def _completed(events: list[Any], node_id: str) -> NodeEvent | None:
    """取该节点**最后一个** completed 帧。

    ## 为什么要取最后一个

    一个节点可以被激活多次（researcher 每轮工具调用切回来一次），
    每次切换都会发一个 completed 帧。**累计耗时只在最后一个里**——
    前面的帧各自带着「到那一刻为止的累计值」。

    所以取第一个会拿到段 1 的值，而不是最终累计值。
    """
    found: NodeEvent | None = None
    for event in _nodes(events):
        if event.node_id == node_id and event.lifecycle == "completed":
            found = event
    return found


# ── 桩 ────────────────────────────────────────────────────────


def _stub_turns(monkeypatch: pytest.MonkeyPatch, script: list[TurnResult]) -> None:
    """按脚本返回 TurnResult。与 test_agent_loop 里的同名桩同构。"""
    remaining = list(script)

    async def _fake_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        if not remaining:
            raise AssertionError("agent 调用轮数超出脚本预期")
        result = remaining.pop(0)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _fake_run_turn)


def _stub_tools(
    monkeypatch: pytest.MonkeyPatch,
    refs: list[Reference],
) -> None:
    """桩掉工具执行：直接产出引用，不发网络请求。

    产出的引用通过 ``collected_refs`` 累积——与真实路径同构。
    """

    async def _fake_run_tools(
        tool_calls: list[dict[str, Any]],
        sink: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> AsyncIterator[Any]:
        collected_refs.extend(refs)
        for call in tool_calls:
            sink.append({"type": "tool_result", "tool_use_id": call["id"], "content": "ok"})
        yield  # pragma: no cover —— 让它成为异步生成器
        return

    monkeypatch.setattr(agent_module, "_run_tools", _fake_run_tools)


# ── critic 计时 ───────────────────────────────────────────────


async def test_critic_elapsed_includes_the_verification_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """critic 的耗时必须包含校验本身。

    ## 要防的回归

    以前的顺序是 ``activate(CRITIC) → complete(CRITIC) → verify_citations()``：
    节点在调用前就关了，于是 DAG 上 critic 永远显示 0.0s，而校验实际
    可能跑满 120s × 3 次重试（6 分钟）。用户看到「0.0 秒」完全被骗。

    ## 怎么测

    把校验桩成一个睡 0.3 秒的协程，然后断言 critic 的 ``elapsed_ms``
    至少 250 毫秒。变异方式：把 ``verify_citations`` 挪回节点窗口之外
    （即先 complete 再校验），这条会红。
    """
    _stub_turns(monkeypatch, [_turn(text="答案")])

    async def _slow_verify(client: Any, report_text: str, sources: dict[int, str]) -> Any:
        await asyncio.sleep(0.3)
        return stages_faithfulness_report()

    monkeypatch.setattr(agent_module, "verify_citations", _slow_verify)

    events = await _collect()
    critic = _completed(events, "critic")

    assert critic is not None, "critic 节点必须完成"
    assert critic.elapsed_ms is not None
    assert critic.elapsed_ms >= 250, f"critic 耗时 {critic.elapsed_ms}ms，没算上校验时间"


def stages_faithfulness_report() -> Any:
    """构造一个「没检查到什么」的校验结果。"""
    from app.services.faithfulness import FaithfulnessReport

    return FaithfulnessReport(
        checked=0,
        supported=0,
        unsupported=[],
        missing=[],
        skipped=True,
        reason="报告没有任何引用角标",
    )


async def test_critic_runs_before_the_faithfulness_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """校验帧在 critic 节点**关闭之后**才发。

    顺序反了的话，用户会先看到校验结论，再看到 DAG 上的 critic 完成勾——
    而结论是在 critic 节点窗口内部算出来的，勾应该先亮。

    ## 断言为什么只认 completed 帧

    早期版本把 critic 的**所有**帧都算进去，用 ``kinds.index("critic")``
    定位。结果取到的是 ``active`` 帧——它永远在 faithfulness 之前，
    断言恒成立。变异测试时发现：把 faithfulness 的 yield 挪到
    ``complete()`` 之前，这条测试仍然全绿。

    所以只认 ``completed`` 帧：它才是「节点关掉了」这个时刻。
    """
    _stub_turns(monkeypatch, [_turn(text="答案")])
    monkeypatch.setattr(agent_module, "verify_citations", _slow_no_cite)

    events = await _collect()
    kinds = [
        "critic"
        if isinstance(e, NodeEvent) and e.node_id == "critic" and e.lifecycle == "completed"
        else "faithfulness"
        if isinstance(e, FaithfulnessEvent)
        else ""
        for e in events
    ]
    kinds = [k for k in kinds if k]

    assert "critic" in kinds, kinds
    assert "faithfulness" in kinds, kinds
    assert kinds.index("critic") < kinds.index("faithfulness"), kinds


async def _slow_no_cite(client: Any, report_text: str, sources: dict[int, str]) -> Any:
    return stages_faithfulness_report()


# ── analyst ───────────────────────────────────────────────────


async def test_analyst_runs_when_evidence_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """有检索证据时 analyst 会激活——它不是占位节点。"""
    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()]), _turn(text="答案")],
    )
    _stub_tools(monkeypatch, [_reference(1), _reference(2, chunk_id=2)])
    _stub_analyst(monkeypatch, conflicts=["A 与 B 矛盾"])

    events = await _collect()

    assert ("analyst", "active") in _lifecycle(events)
    analyst = _completed(events, "analyst")
    assert analyst is not None
    assert "矛盾" in analyst.note


async def test_analyst_result_reaches_the_next_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """核对结论要进模型上下文——Writer 得知道有矛盾。

    ## 怎么测

    桩掉 ``_run_turn`` 时把每次调用的 messages 记下来，检查第二轮的
    user 消息里有没有「矛盾」两个字。
    """
    seen_messages: list[list[dict[str, Any]]] = []
    script = [_turn(tool_calls=[_tool_call()]), _turn(text="答案")]

    async def _recording_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        seen_messages.append([dict(m) for m in messages])
        result = script.pop(0)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _recording_run_turn)
    _stub_tools(monkeypatch, [_reference(1), _reference(2, chunk_id=2)])
    _stub_analyst(monkeypatch, conflicts=["A 与 B 矛盾"])

    await _collect()

    # 第二轮的**最后**一条 user 消息（tool_result + 核对结论打包在一起）。
    # 取最后一条而不是第一条——第一���是初始提问。
    second_turn = seen_messages[1]
    user_msgs = [m for m in second_turn if m["role"] == "user"]
    blob = str(user_msgs[-1]["content"])
    assert "矛盾" in blob, f"核对结论没进上下文：{blob[:500]}"


async def test_analyst_skipped_without_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型一次都没调工具时没有证据可核对——analyst 不做实际工作。

    它仍然会在 DAG 上出现（``_settle`` 补的空跑），但产出摘要必须说
    清楚「没有证据可核对」——不能给一个看起来干了活的节点。
    """
    _stub_turns(monkeypatch, [_turn(text="直接回答")])

    called = False

    async def _tracking_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        nonlocal called
        called = True
        return stages.Analysis()

    monkeypatch.setattr(stages, "analyze_evidence", _tracking_analyze)

    await _collect()

    assert called is False, "没有证据时不该调核对模型"


async def test_analyst_node_still_walked_when_no_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有证据时 analyst 也要走完 DAG（作为占位）——5 步流程不能少一步。

    但它的产出摘要必须**如实说明**「没有证据可核对」，不能编一个耗时。
    """
    _stub_turns(monkeypatch, [_turn(text="直接回答")])

    events = await _collect()

    analyst = _completed(events, "analyst")
    assert analyst is not None, "analyst 节点必须出现在 DAG 上"
    assert "没有检索证据" in analyst.note


async def test_analyst_analysis_is_in_the_same_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """核对结论必须与 tool_result 打包在**同一条** user 消息里。

    单独 append 一条 user 消息会构造出连续同角色消息，上游会拒收
    整个请求——症状是「第一次检索正常，第二次就报 400」。
    """
    seen_messages: list[list[dict[str, Any]]] = []
    script = [_turn(tool_calls=[_tool_call()]), _turn(text="答案")]

    async def _recording_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        seen_messages.append([dict(m) for m in messages])
        result = script.pop(0)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _recording_run_turn)
    _stub_tools(monkeypatch, [_reference(1), _reference(2, chunk_id=2)])
    _stub_analyst(monkeypatch, conflicts=["矛盾"])

    await _collect()

    roles = [m["role"] for m in seen_messages[1]]
    # user / assistant / user —— 不能出现连续两个 user
    assert "user" not in [r for i, r in enumerate(roles) if i > 0 and roles[i - 1] == "user"], roles


def _stub_analyst(monkeypatch: pytest.MonkeyPatch, conflicts: list[str]) -> None:
    """桩掉 analyst 的核对，让它返回指定的矛盾。"""

    async def _fake_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        return stages.Analysis(
            conflicts=conflicts,
            synthesis="综合",
            input_tokens=20,
            output_tokens=10,
        )

    monkeypatch.setattr(stages, "analyze_evidence", _fake_analyze)


async def test_analyst_note_is_always_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Analyst 的产出摘要**一定要有值**。

    ## 要防的回归

    之前只在「有矛盾」或「有综合结论」时才 set_note。模型两者都没给
    时 note 是空串——DAG 上那个节点只有耗时、没有产出，用户看不出它
    到底干了什么（实测一次研究里 analyst 跑了 23 秒，note 是空的）。

    「核对了 N 条证据」本身就是产出。
    """
    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()]), _turn(text="答案")],
    )
    _stub_tools(monkeypatch, [_reference(1), _reference(2, chunk_id=2)])
    # 模型既没给矛盾也没给综合结论
    _stub_analyst(monkeypatch, conflicts=[])

    async def _empty_analysis(client: Any, evidence: list[Any]) -> stages.Analysis:
        return stages.Analysis(conflicts=[], synthesis="")

    monkeypatch.setattr(stages, "analyze_evidence", _empty_analysis)

    events = await _collect()

    analyst = _completed(events, "analyst")
    assert analyst is not None
    assert analyst.note, "Analyst 的产出摘要不能为空"
    assert "证据" in analyst.note, analyst.note


async def test_analyst_note_says_failed_not_no_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """核对失败时 note **不能说**「未发现矛盾」。

    ## 要防的回归（CR 实测，2026-11-08）

    模型调用失败时 ``analyze_evidence`` 返回全空的 ``Analysis``，而
    「调用失败」与「跑成功但确实没发现矛盾」两者的产出完全一样——调用方
    分不出来。于是 note 写「核对 12 条证据，未发现矛盾」，而真相是
    **一次都没核对**。

    那比 0.0s 更坏：0.0s 至少暴露了可疑，「未发现矛盾」让用户以为
    系统核对过。本次改动的全部意义就是「让 DAG 显示真实发生的事」。
    """
    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()]), _turn(text="答案")],
    )
    _stub_tools(monkeypatch, [_reference(1), _reference(2, chunk_id=2)])

    async def _failing_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        return stages.Analysis(degraded=True, skipped_reason="模型调用失败")

    monkeypatch.setattr(stages, "analyze_evidence", _failing_analyze)

    events = await _collect()

    analyst = _completed(events, "analyst")
    assert analyst is not None
    assert "未发现矛盾" not in analyst.note, analyst.note
    assert "核对未完成" in analyst.note, analyst.note


async def test_single_evidence_does_not_claim_a_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有 1 条证据时**根本没调模型**，note 不能说核对了。

    ``analyze_evidence`` 在少于 2 条证据时直接返回（一条证据没有
    「交叉」的对象）。但 note 仍会写「核对 1 条证据，未发现矛盾」。
    """
    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()]), _turn(text="答案")],
    )
    _stub_tools(monkeypatch, [_reference(1)])

    # **不桩 analyze_evidence**——要验的是它自己的降级行为：
    # 少于 2 条证据时它直接返回（不调模型），且必须标 degraded。
    #
    # 桩掉它就等于把要验的东西换掉了。
    #
    # 模型调用要挡住——``_call_structured`` 会真的发请求。
    async def _no_call(client: Any, **kwargs: Any) -> Any:
        raise AssertionError("少于 2 条证据时不该调模型")

    monkeypatch.setattr(stages, "_call_structured", _no_call)

    events = await _collect()

    analyst = _completed(events, "analyst")
    assert analyst is not None
    assert "未发现矛盾" not in analyst.note, analyst.note


async def test_evidence_outside_the_window_is_still_checked_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """窗口外的证据不能被提前标记成「核对过」。

    ## 要防的回归（CR 实测，2026-11-08）

    早先的判据拿「全部 unique 的键」算差集，然后把**全部**键记进
    ``seen``。但实际喂给模型的只有最后 12 条——前面那些从未被核对过，
    ``seen`` 却说核对过了。

    后果：第 1 轮 20 条证据 → 前 8 条永远不会被核对，而 note 写「核对
    12 条证据」，用户以为全对了。而这在真实路径上会触发（引用表封顶
    10，两轮不同查询就超过 12）。
    """
    # 第一轮：15 条引用（超过窗口 12）
    many = [_reference(i, chunk_id=i) for i in range(1, 16)]
    _stub_tools(monkeypatch, many)

    checked_rounds: list[list[int]] = []

    async def _tracking_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        checked_rounds.append([e.n for e in evidence])
        return stages.Analysis(synthesis="x")

    monkeypatch.setattr(stages, "analyze_evidence", _tracking_analyze)

    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()]), _turn(text="答案")],
    )

    await _collect()

    assert checked_rounds, "Analyst 没被调用"
    # 第一轮只喂窗口内的 12 条
    assert len(checked_rounds[0]) == stages.MAX_ANALYST_EVIDENCE
    # 被挤出窗口的那几条**不能**被算成「核对过」——
    # 它们的 chunk_id 是 1、2、3（最早的三条），而窗口取的是最后 12 条
    # （n=4..15）。
    assert checked_rounds[0] == sorted(checked_rounds[0])
    assert 1 not in checked_rounds[0], "窗口外的证据不该在第一轮被喂"


async def test_evidence_outside_the_window_is_checked_on_the_next_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """窗口外的证据在下一轮**必须**被核对。

    这是上一条测试的另一半：窗口外的证据不能被提前标记成「核对过」，
    否则它们永远没有机会被核对。

    ## 怎么测

    第一轮 15 条（窗口 12）→ 最早的 3 条没进模型。第二轮证据变成 13 条
    （窗口取最后 12 = 第 2..13 条），于是第 1 条**进入**窗口——
    它必须在这一轮被核对。
    """
    # 第一轮 15 条
    first_batch = [_reference(i, chunk_id=i) for i in range(1, 16)]
    # 第二轮再补一条 → 共 16 条，窗口取最后 12（第 5..16 条）
    second_batch = [_reference(16, chunk_id=16)]

    batches = [first_batch, second_batch]
    checked_rounds: list[list[int]] = []

    async def _fake_run_tools(
        tool_calls: list[dict[str, Any]],
        sink: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> AsyncIterator[Any]:
        collected_refs.extend(batches.pop(0) if batches else [])
        for call in tool_calls:
            sink.append({"type": "tool_result", "tool_use_id": call["id"], "content": "ok"})
        yield  # pragma: no cover

    monkeypatch.setattr(agent_module, "_run_tools", _fake_run_tools)

    async def _tracking_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        checked_rounds.append([e.n for e in evidence])
        return stages.Analysis(synthesis="x")

    monkeypatch.setattr(stages, "analyze_evidence", _tracking_analyze)

    _stub_turns(
        monkeypatch,
        [
            _turn(tool_calls=[_tool_call()]),
            _turn(tool_calls=[_tool_call("toolu_2")]),
            _turn(text="答案"),
        ],
    )

    await _collect()

    assert len(checked_rounds) >= 2, f"第二轮没重跑核对：{checked_rounds}"
    # 第二轮必须包含窗口外的那些（n=4、5… 之前被挤出去的）
    assert len(checked_rounds[1]) == stages.MAX_ANALYST_EVIDENCE

    # **关键断言：被挤出窗口的证据必须「还没核对过」**。
    #
    # 第 1 轮喂的是 n=4..15（窗口取最后 12 条），n=1、2、3 没进模型。
    # 它们**必须**留在「未核对」状态——否则它们永远没有机会被核对，
    # 而 note 会说「核对 12 条证据」，用户以为全对了。
    #
    # 怎么验这个状态？第 2 轮如果证据数不变，窗口也不变，被标记过的那
    # 几条就永远不会重新进窗口。所以造一个场景：证据数减少，让窗口
    # 回退到包含 n=1 的范围——如果 n=1 被提前标记成「核对过」，它就
    # 不会被重新核对。
    assert checked_rounds[0] == [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], checked_rounds[0]


async def test_analyst_note_reports_the_total_when_some_are_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """证据超过窗口时，note 必须说清「核对了几条 / 共几条」。

    ## 要防的回归（CR 实测，2026-11-08）

    证据是累加的，而一次最多喂 12 条（``MAX_ANALYST_EVIDENCE``）。
    note 写「核对 12 条证据」在有 20 条证据时**不完整**——用户会以为
    全都核对过了。

    而且这在真实路径上会触发：引用表封顶 10，两轮不同查询就超过 12。
    """
    many = [_reference(i, chunk_id=i) for i in range(1, 16)]
    _stub_tools(monkeypatch, many)

    async def _tracking_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        return stages.Analysis(synthesis="x")

    monkeypatch.setattr(stages, "analyze_evidence", _tracking_analyze)

    _stub_turns(
        monkeypatch,
        [_turn(tool_calls=[_tool_call()]), _turn(text="答案")],
    )

    events = await _collect()

    analyst = _completed(events, "analyst")
    assert analyst is not None
    assert "共 15 条" in analyst.note, analyst.note


async def test_analyst_does_not_rerun_without_new_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有**新**证据时，Analyst 不重跑。

    ## 要防的回归

    证据是累加的，而每轮工具调用都会把**全量**结果再累积一遍（联网搜索
    每次返回自己的结果，local_search 返回全量引用表快照）。若「有证据
    就跑」，第 4 轮会把第 1 轮的证据原样再核对一遍——同样的输入、同样的
    输出，纯烧钱。

    实测（2026-11-04）：一次研究里 analyst 跑了两次，第二次核对的
    还是那 8 条一模一样的证据。

    ## 怎么测

    三轮工具调用，但每次的证据**完全相同**（同一条 web evidence）。
    断言核对模型只被调了一次。
    """
    calls = 0

    async def _counting_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        nonlocal calls
        calls += 1
        return stages.Analysis(synthesis="综合")

    async def _fake_run_tools(
        tool_calls: list[dict[str, Any]],
        sink: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> AsyncIterator[Any]:
        from app.services.citation import Reference

        # 每次都产出**同一条**证据——模拟「同一批结果被重复累积」
        collected_refs.append(
            Reference(
                n=1,
                chunk_id=902,
                source_id=802,
                chunk_index=0,
                page=None,
                title="同一条",
                excerpt="内容",
                recall="网页搜索",
            )
        )
        for call in tool_calls:
            sink.append({"type": "tool_result", "tool_use_id": call["id"], "content": "ok"})
        yield  # pragma: no cover

    monkeypatch.setattr(stages, "analyze_evidence", _counting_analyze)
    monkeypatch.setattr(agent_module, "_run_tools", _fake_run_tools)
    _stub_turns(
        monkeypatch,
        [
            _turn(tool_calls=[_tool_call()]),
            _turn(tool_calls=[_tool_call("toolu_2")]),
            _turn(tool_calls=[_tool_call("toolu_3")]),
            _turn(text="答案"),
        ],
    )

    await _collect()

    assert calls == 1, f"同样的证据核对了 {calls} 次，应该只核对一次"


async def test_web_evidence_reaches_the_analyst(monkeypatch: pytest.MonkeyPatch) -> None:
    """**联网搜索的结果**也要参与 Analyst 的核对。

    ## 为什么

    Analyst 之前只看得到 ``local_search`` 的产物（用户上传资料里的
    切片）。没有上传资料的用户（绝大多数）看到的永远是「没有检索
    证据可核对」——而跨来源核对矛盾恰恰是 Analyst 最该干的活。

    现在联网搜索结果会落成**正经引用**（``Source`` + ``DocumentChunk`` +
    角标号），所以它们就在 ``collected_refs`` 里，Analyst 自然看得到。

    ## 怎么测

    桩掉 ``_run_tools`` 让它产出一条联网引用，桩掉 ``analyze_evidence``
    记录它收到的证据条数。
    """
    seen: list[list[Any]] = []

    async def _fake_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        seen.append(evidence)
        return stages.Analysis(synthesis="综合")

    async def _fake_run_tools(
        tool_calls: list[dict[str, Any]],
        sink: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> AsyncIterator[Any]:
        from app.services.citation import Reference

        collected_refs.append(
            Reference(
                n=1,
                chunk_id=900,
                source_id=800,
                chunk_index=0,
                page=None,
                title="网上的一条说法",
                excerpt="销量是 100 万",
                recall="网页搜索",
            )
        )
        for call in tool_calls:
            sink.append({"type": "tool_result", "tool_use_id": call["id"], "content": "ok"})
        yield  # pragma: no cover —— 让它成为异步生成器

    monkeypatch.setattr(stages, "analyze_evidence", _fake_analyze)
    monkeypatch.setattr(agent_module, "_run_tools", _fake_run_tools)
    _stub_turns(monkeypatch, [_turn(tool_calls=[_tool_call()]), _turn(text="答案")])

    await _collect()

    assert seen, "Analyst 没有被调用——联网证据没进核对"
    # 证据里必须有那条联网结果
    titles = [e.title for e in seen[0]]
    assert any("网上的一条说法" in t for t in titles), titles
    # 公开来源现在是**正经引用**——有正的角标号，与用户资料共用编号空间
    numbers = [e.n for e in seen[0]]
    assert all(n > 0 for n in numbers), numbers


async def test_web_evidence_alone_triggers_the_analyst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**只有**联网证据（没有本地资料）时，Analyst 也要跑。"""
    seen: list[list[Any]] = []

    async def _fake_analyze(client: Any, evidence: list[Any]) -> stages.Analysis:
        seen.append(evidence)
        return stages.Analysis(synthesis="综合")

    async def _fake_run_tools(
        tool_calls: list[dict[str, Any]],
        sink: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> AsyncIterator[Any]:
        from app.services.citation import Reference

        collected_refs.append(
            Reference(
                n=1,
                chunk_id=901,
                source_id=801,
                chunk_index=0,
                page=None,
                title="公开来源",
                excerpt="内容",
                recall="网页搜索",
            )
        )
        for call in tool_calls:
            sink.append({"type": "tool_result", "tool_use_id": call["id"], "content": "ok"})
        yield  # pragma: no cover

    monkeypatch.setattr(stages, "analyze_evidence", _fake_analyze)
    monkeypatch.setattr(agent_module, "_run_tools", _fake_run_tools)
    _stub_turns(monkeypatch, [_turn(tool_calls=[_tool_call()]), _turn(text="答案")])

    events = await _collect()

    assert seen, "只有联网证据时 Analyst 也该跑"
    analyst = _completed(events, "analyst")
    assert analyst is not None
    assert "没有检索证据" not in analyst.note, analyst.note


# ── 累计耗时 ──────────────────────────────────────────────────


async def test_active_frame_carries_the_accumulated_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """active 帧要带上「本段开始前的累计耗时」。

    ## 为什么

    前端算实时秒数需要两个值：基线（这个节点之前累计跑了多久）与
    本段起点。基线只有后端知道——前端只看到帧，看不到「这个节点一共
    活跃了多久」。

    不带的话，前端只能从 0 开始算这一段，于是 researcher 分多段跑时
    用户看到的秒数会**归零重来**：0 → 10 → 0 → 1 → 0 → 5。而 completed
    帧给的是累计值（16.2s），两者对不上。

    ## 怎么测

    跑一个两轮检索的场景，第一轮故意睡 200ms（否则累计值是 0，
    基线断言恒真），检查第二轮 researcher 的 active 帧带的
    ``elapsed_ms`` 不为 0。
    """
    script = [
        _turn(tool_calls=[_tool_call()]),
        _turn(tool_calls=[_tool_call("toolu_2")]),
        _turn(text="答案"),
    ]
    first = True

    async def _slow_first_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        nonlocal first
        if first:
            first = False
            await asyncio.sleep(0.2)
        result = script.pop(0)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _slow_first_run_turn)
    _stub_tools(monkeypatch, [])

    events = await _collect()

    researcher_actives = [
        e for e in _nodes(events) if e.node_id == "researcher" and e.lifecycle == "active"
    ]
    assert len(researcher_actives) >= 2, "测试前提不成立：researcher 没有多次激活"
    # 第二个 active 帧必须带非零基线
    assert researcher_actives[1].elapsed_ms is not None
    assert researcher_actives[1].elapsed_ms >= 150, (
        f"第二次激活没带累计基线：{researcher_actives[1].elapsed_ms}"
    )


async def test_repeated_researcher_elapsed_is_accumulated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """researcher 被激活多次时，耗时是**累计**的。

    ## 要防的回归

    只算「最后一段」的话，用户看到的是「检索 0.0s」而实际检索了
    好几轮。每次工具调用都会切回 researcher，所以这是常态而不是边角。

    ## 断言为什么要有两段可分辨的耗时

    早期版本的断言只有 ``elapsed_ms is not None``——那恒真，
    变异测试时发现「把累计改成只算最后一段」这条仍然全绿。

    现在第一段明确睡 200ms、第二段几乎不睡，于是：

    - 累计正确 → ``elapsed_ms >= 200``
    - 只算最后一段 → ``elapsed_ms`` 接近 0 → 红
    """
    delays = [0.2, 0.0, 0.0]
    script = [
        _turn(tool_calls=[_tool_call()]),
        _turn(tool_calls=[_tool_call("toolu_2")]),
        _turn(text="答案"),
    ]

    async def _slow_first_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        if delays:
            await asyncio.sleep(delays.pop(0))
        result = script.pop(0)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _slow_first_run_turn)
    _stub_tools(monkeypatch, [])

    events = await _collect()

    activations = [
        e for e in _nodes(events) if e.node_id == "researcher" and e.lifecycle == "active"
    ]
    assert len(activations) >= 2, f"测试前提不成立：researcher 只激活了 {len(activations)} 次"

    researcher = _completed(events, "researcher")
    assert researcher is not None
    assert researcher.elapsed_ms is not None
    assert researcher.elapsed_ms >= 200, (
        f"researcher 累计耗时 {researcher.elapsed_ms}ms，没算上第一段那 200ms"
    )


async def test_node_note_carries_the_production_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """节点完成帧带产出摘要——用户能看到这个节点干了什么。"""
    _stub_turns(monkeypatch, [_turn(text="答案")])

    events = await _collect()

    critic = _completed(events, "critic")
    assert critic is not None
    assert critic.note, "critic 必须带产出摘要"


async def test_supervisor_note_reports_subtask_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """supervisor 的摘要说明拆解出几个子任务。"""

    async def _fake_plan(client: Any, question: str, *, has_local: bool) -> stages.Plan:
        return stages.Plan(subtasks=["a", "b", "c"], input_tokens=30, output_tokens=15)

    monkeypatch.setattr(agent_module, "plan_subtasks", _fake_plan)
    _stub_turns(monkeypatch, [_turn(text="答案")])

    events = await _collect()

    supervisor = _completed(events, "supervisor")
    assert supervisor is not None
    assert "3" in supervisor.note


async def test_supervisor_subtasks_reach_the_model_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supervisor 拆解出的子任务必须进模型的第一轮提示。

    ## 要防的回归

    ``plan_subtasks`` 调了模型、``NodeTracker`` 记了摘要，用户也看得见
    「拆解出 3 个子任务」——但如果 ``_build_user_prompt`` 忘了拼
    ``plan.as_prompt_line()``，**拆解就白做了**：模型从头到尾没看到过
    子任务，检索还是它自己瞎猜。

    这条接线原先没有任何测试覆盖（``test_agent_loop.py`` 里三个
    ``_build_user_prompt`` 用例都不传 ``plan``）——变异测试时发现
    「删掉 ``body += plan.as_prompt_line()``」全量 715 个测试仍然全绿。

    ## 怎么测

    桩掉 ``_run_turn`` 并记录第一轮收到的 messages，检查里面有没有
    子任务的文字。
    """
    seen_messages: list[list[dict[str, Any]]] = []

    async def _recording_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        seen_messages.append([dict(m) for m in messages])
        yield TurnChunk(
            kind="result",
            result=_turn(text="答案"),
        )

    async def _fake_plan(client: Any, question: str, *, has_local: bool) -> stages.Plan:
        return stages.Plan(subtasks=["查市场规模", "查主要玩家"])

    monkeypatch.setattr(agent_module, "plan_subtasks", _fake_plan)
    monkeypatch.setattr(agent_module, "_run_turn", _recording_run_turn)

    await _collect()

    first_turn = seen_messages[0]
    blob = str(first_turn[0]["content"])
    assert "查市场规模" in blob, f"子任务没进第一轮提示：{blob[:500]}"
    assert "查主要玩家" in blob, blob[:500]


async def test_stage_token_usage_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """supervisor / analyst 的 token 要计入账本。

    不记的话用量统计系统性偏低——用户按账估算成本会算错。
    """

    async def _fake_plan(client: Any, question: str, *, has_local: bool) -> stages.Plan:
        return stages.Plan(subtasks=["a"], input_tokens=30, output_tokens=15)

    monkeypatch.setattr(agent_module, "plan_subtasks", _fake_plan)
    _stub_turns(monkeypatch, [_turn(text="答案")])

    events = await _collect()

    from app.services.stream import DoneEvent

    done = next(e for e in events if isinstance(e, DoneEvent))
    # 主循环 1 轮：100 输入 / 50 输出；supervisor：30 / 15
    assert done.input_tokens == 130
    assert done.output_tokens == 65


# ── 辅助 ──────────────────────────────────────────────────────


async def _collect() -> list[Any]:
    return [event async for event in run_agent("测试问题", user_id=1)]
