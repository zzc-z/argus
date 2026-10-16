"""引用忠实度校验（Critic 节点，sprint plan Day 13）。"""

from typing import Any

import pytest

from app.services.faithfulness import (
    FaithfulnessReport,
    Unsupported,
    extract_cited_sentences,
)


# ── 抽取引用句子 ──────────────────────────────────────────────


class TestExtractCitedSentences:
    def test_single_footnote(self) -> None:
        text = "Blackwell 能效提升 2.5 倍[1]。部署需要液冷[2]。"
        # 角标**保留**：LLM 判定时要看到「这条句子引用了哪条」。
        assert extract_cited_sentences(text) == {
            1: ["Blackwell 能效提升 2.5 倍[1]"],
            2: ["部署需要液冷[2]"],
        }

    def test_multi_footnote_in_one_marker(self) -> None:
        """``[1,2]`` 是一条引用两处，不是「编号 12」。"""
        text = "两个来源都提到了这一点[1,2]。"
        got = extract_cited_sentences(text)
        assert got[1] == ["两个来源都提到了这一点[1,2]"]
        assert got[2] == ["两个来源都提到了这一点[1,2]"]
        assert 12 not in got

    def test_year_is_not_a_footnote(self) -> None:
        """``[2024]`` 是方括号里的年份，不是角标。

        实测踩过：正则若写成 ``\\[(\\d+)\\]``，模型写「[2024] 年报告」
        就会被当成引用编号 2024，而引用表里根本没有它。
        """
        got = extract_cited_sentences("根据 [2024] 年的数据[1]。")
        assert got == {1: ["根据 [2024] 年的数据[1]"]}
        assert 2024 not in got

    def test_sentence_without_footnote_excluded(self) -> None:
        text = "第一句没有角标。第二句有[1]。"
        got = extract_cited_sentences(text)
        assert list(got) == [1]
        assert "第一句没有角标" not in got[1][0]

    def test_multiple_sentences_same_footnote(self) -> None:
        text = "A 成立[1]。B 也成立[1]。C 不成立[2]。"
        got = extract_cited_sentences(text)
        assert got[1] == ["A 成立[1]", "B 也成立[1]"]
        assert got[2] == ["C 不成立[2]"]

    def test_footnote_at_very_end_without_punctuation(self) -> None:
        """模型经常把角标甩在最后且不加句号。"""
        assert extract_cited_sentences("结论如上[1]") == {1: ["结论如上[1]"]}

    def test_empty_text(self) -> None:
        assert extract_cited_sentences("") == {}


# ── 报告结构 ──────────────────────────────────────────────────


class TestFaithfulnessReport:
    def test_pass_rate_zero_checked_is_zero_not_division_error(self) -> None:
        """checked=0 时不能除零。"""
        report = FaithfulnessReport(
            checked=0, supported=0, unsupported=[], missing=[], skipped=True
        )
        assert report.pass_rate == 0.0

    def test_pass_rate(self) -> None:
        report = FaithfulnessReport(
            checked=4,
            supported=3,
            unsupported=[Unsupported(footnote=2, sentence="x", reason="y")],
            missing=[],
            skipped=False,
        )
        assert report.pass_rate == 0.75


# ── 端到端：agent 是否发出 faithfulness 事件 ─────────────────


async def test_run_agent_emits_faithfulness_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """成功跑完必须有一条 faithfulness 事件，且五个节点事件都在。

    ## 这个测试要防的具体回归

    实现 ``_settle`` 时我构建了 ``events`` 列表却忘了 yield——async
    generator 只认 yield，构建 list 不产生任何事件，于是 analyst /
    critic / writer 三个节点**静默消失**，DAG 停在 researcher。

    症状极隐蔽：没有异常，节点测试也只是「completed 少了几项」，
    不看断言内容会以为是别的问题。
    """
    from collections.abc import AsyncIterator

    from app.services import agent as agent_mod
    from app.services.stream import DoneEvent, FaithfulnessEvent, NodeEvent

    calls: list[int] = []

    async def _fake_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> agent_mod.TurnResult:
        calls.append(1)
        return agent_mod.TurnResult(
            content=[],
            text="结论如上[1]。",
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
        )

    monkeypatch.setattr(agent_mod, "_run_turn", _fake_run_turn)

    async def _collect() -> list[Any]:
        out: list[Any] = []
        async for e in agent_mod.run_agent("问题", user_id=1):
            out.append(e)
        return out

    events = await _collect()
    node_events = [e for e in events if isinstance(e, NodeEvent)]
    completed = [e.node_id for e in node_events if e.lifecycle == "completed"]
    assert completed == ["supervisor", "researcher", "writer", "analyst", "critic"]

    assert any(isinstance(e, FaithfulnessEvent) for e in events), (
        "成功跑完必须发 faithfulness 事件，否则前端拿不到校验结论"
    )
    assert any(isinstance(e, DoneEvent) for e in events)


async def test_faithfulness_event_is_last_before_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """校验事件必须在 done 之前。

    反过来的话前端会先标记「已完成」再弹校验结论，顺序反了。
    """
    from app.services import agent as agent_mod
    from app.services.stream import DoneEvent, FaithfulnessEvent

    async def _fake_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> agent_mod.TurnResult:
        return agent_mod.TurnResult(
            text="x",
            tool_calls=[],
            content=[],
            stop_reason="end_turn",

            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr(agent_mod, "_run_turn", _fake_run_turn)

    events = [
        e async for e in agent_mod.run_agent("问题", user_id=1)
    ]
    faith_idx = next(
        i for i, e in enumerate(events) if isinstance(e, FaithfulnessEvent)
    )
    done_idx = next(i for i, e in enumerate(events) if isinstance(e, DoneEvent))
    assert faith_idx < done_idx


async def test_error_path_emits_no_faithfulness_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """崩溃路径不该发校验事件——报告根本没写出来，校验无从谈起。"""
    from app.services import agent as agent_mod
    from app.services.stream import ErrorEvent, FaithfulnessEvent

    async def _boom(client: Any, messages: list[dict[str, Any]], tools: Any) -> Any:
        raise RuntimeError("中转站挂了")

    monkeypatch.setattr(agent_mod, "_run_turn", _boom)

    events = [e async for e in agent_mod.run_agent("问题", user_id=1)]
    assert any(isinstance(e, ErrorEvent) for e in events)
    assert not any(isinstance(e, FaithfulnessEvent) for e in events)


async def test_empty_response_path_still_sends_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空正文也要有 done（烧掉的 token 要报得出去），但校验无从做起。"""
    from app.services import agent as agent_mod
    from app.services.stream import DoneEvent, ErrorEvent, FaithfulnessEvent

    async def _thinking_only(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> agent_mod.TurnResult:
        return agent_mod.TurnResult(
            text="",
            tool_calls=[],
            content=[],
            stop_reason="end_turn",

            input_tokens=300,
            output_tokens=150,
        )

    monkeypatch.setattr(agent_mod, "_run_turn", _thinking_only)
    events = [e async for e in agent_mod.run_agent("问题", user_id=1)]
    assert any(isinstance(e, ErrorEvent) for e in events)
    assert any(isinstance(e, DoneEvent) for e in events)
    assert not any(isinstance(e, FaithfulnessEvent) for e in events)
