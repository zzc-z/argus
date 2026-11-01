"""引用忠实度校验（Critic 节点，sprint plan Day 13）。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.citation import extract_cited_sentences
from app.services.faithfulness import (
    FaithfulnessReport,
    Unsupported,
    _build_user_prompt,
    _parse_verdicts,
    load_source_texts,
)
from tests.conftest import turn_chunks

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
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        calls.append(1)
        for chunk in turn_chunks(
            agent_mod.TurnResult(
                content=[],
                text="结论如上[1]。",
                tool_calls=[],
                stop_reason="end_turn",
                input_tokens=100,
                output_tokens=50,
            )
        ):
            yield chunk

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


async def test_done_precedes_faithfulness_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """done 必须在校验帧**之前**。

    judge 调用最坏 120s × 3 次重试。挡在 done 前面的话，用户在报告读完
    之后还要干等 6 分钟，而 MAX_CONCURRENT_STREAMS 只有 4——几个并发就能
    把准入闸门堵死（新请求直接 503）。
    """
    from app.services import agent as agent_mod
    from app.services.stream import DoneEvent, FaithfulnessEvent

    async def _fake_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        for chunk in turn_chunks(
            agent_mod.TurnResult(
                text="x",
                tool_calls=[],
                content=[],
                stop_reason="end_turn",
                input_tokens=1,
                output_tokens=1,
            )
        ):
            yield chunk

    monkeypatch.setattr(agent_mod, "_run_turn", _fake_run_turn)

    events = [e async for e in agent_mod.run_agent("问题", user_id=1)]
    faith_idx = next(i for i, e in enumerate(events) if isinstance(e, FaithfulnessEvent))
    done_idx = next(i for i, e in enumerate(events) if isinstance(e, DoneEvent))
    assert done_idx < faith_idx


async def test_error_path_emits_no_faithfulness_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """崩溃路径不该发校验事件——报告根本没写出来，校验无从谈起。"""
    from app.services import agent as agent_mod
    from app.services.stream import ErrorEvent, FaithfulnessEvent

    async def _boom(client: Any, messages: list[dict[str, Any]], tools: Any) -> Any:
        raise RuntimeError("中转站挂了")
        yield  # pragma: no cover —— 生成器函数需要 unreachable 的 yield

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
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        for chunk in turn_chunks(
            agent_mod.TurnResult(
                text="",
                tool_calls=[],
                content=[],
                stop_reason="end_turn",
                input_tokens=300,
                output_tokens=150,
            )
        ):
            yield chunk

    monkeypatch.setattr(agent_mod, "_run_turn", _thinking_only)
    events = [e async for e in agent_mod.run_agent("问题", user_id=1)]
    assert any(isinstance(e, ErrorEvent) for e in events)
    assert any(isinstance(e, DoneEvent) for e in events)
    assert not any(isinstance(e, FaithfulnessEvent) for e in events)


# ── 解析层：CR 报出的六个缺陷全在这一层 ──────────────────────
class TestParseVerdicts:
    """`_parse_verdicts` 曾是零覆盖——CR 报出的六个缺陷全在这里。"""

    def _p(self, raw: str, ids: set[str] | None = None) -> dict[str, tuple[bool, str]]:
        return _parse_verdicts(raw, ids or {"1", "2"})

    def test_malformed_verdicts_types_do_not_raise(self) -> None:
        """C5：模型返回非 list 的 verdicts 时不抛 AttributeError。

        实测三种返回都会炸：字符串（迭代出字符）、数字数组、字典（迭代出 key）。
        抛出去会逃出降级路径，把 done 事件一起带走。
        """
        for raw in (
            '{"verdicts": "supported"}',
            '{"verdicts": [1, 2]}',
            '{"verdicts": {"1": "supported"}}',
        ):
            assert self._p(raw) == {}

    def test_unknown_verdict_word_is_not_unsupported(self) -> None:
        """I6：`partially_supported` 之类的新词汇不能算成「未支撑」。

        误伤方向必须是「无法判定」——把用户自己写的结论判成无据，
        比漏判糟得多。
        """
        got = self._p(
            '{"verdicts": [{"id": 1, "verdict": "partially_supported", "reason": "一半"}]}'
        )
        assert got == {}, f"未知词汇应被丢弃而不是判失败：{got}"

    def test_verdict_whitespace_and_case_tolerated(self) -> None:
        """I6：`"Supported"` / `"supported "` 也该认。"""
        got = self._p('{"verdicts": [{"id": 1, "verdict": " Supported ", "reason": "ok"}]}')
        assert got.get("1", (None,))[0] is True

    def test_id_drift_is_dropped_not_guessed(self) -> None:
        """I7：id 是 `"1.0"` 这类无法对应的形态时被丢弃——宁可少判，不猜。

        `" 1"`（带空格）**应该**被接受：模型加空格是格式噪声不是语义漂移，
        丢掉它等于白白少判一条。
        """
        assert self._p('{"verdicts": [{"id": 1.0, "verdict": "supported", "reason": "x"}]}') == {}
        assert self._p('{"verdicts": [{"id": " 1", "verdict": "supported", "reason": "x"}]}').get(
            "1"
        ) is not None

    def test_json_fenced_output_parsed(self) -> None:
        """模型常带 ```json 围栏。"""
        raw = '```json\n{"verdicts": [{"id": 1, "verdict": "supported", "reason": "ok"}]}\n```'
        assert self._p(raw).get("1", (None,))[0] is True

    def test_toplevel_array_and_trailing_text(self) -> None:
        """顶层是数组、JSON 后跟尾随文本——都不该抛，也不该编。"""
        assert self._p('[{"id": 1}]') == {}
        assert self._p('{"verdicts": []} 谢谢') == {}


# ── 原文加载：CR 的 C1 曾让整份校验方向相反 ──────────────────
async def test_load_source_texts_maps_by_chunk_id_not_position(
    db_session: AsyncSession,
) -> None:
    """C1：角标 n 必须拿到 chunk_id 对应的那段原文。

    原实现 `select(DocumentChunk.content)` 之后 `zip(wanted, rows)`，
    靠**位置**配对。SQL 没有 ORDER BY，返回顺序与 wanted 的 key 顺序
    无关——实测角标 1 会拿到 5 号 chunk 的正文，整份校验结果方向相反，
    而且没有任何报错。

    这里的 chunk id 故意用乱序（100/3/57），插入顺序与 id 顺序不一致。
    """
    from app.models import DocumentChunk, Source, SourceType, User
    from app.services.citation import Reference

    db_session.add(User(id=1, email="u@t.local"))
    await db_session.flush()
    db_session.add(Source(id=1, user_id=1, title="t", source_type=SourceType.TEXT))
    ids = {}
    for chunk_id, content in [(100, "甲"), (3, "乙"), (57, "丙")]:
        obj = DocumentChunk(source_id=1, chunk_index=chunk_id, content=content, page=None)
        obj.id = chunk_id
        db_session.add(obj)
        ids[chunk_id] = content
    await db_session.flush()

    # chunk_id 与角标的对应顺序刻意不等于插入顺序
    refs = [
        Reference(n=n, chunk_id=cid, source_id=1, chunk_index=cid, page=None,
                  title="t", excerpt=ids[cid], recall="向量")
        for n, cid in [(1, 100), (2, 3), (3, 57)]
    ]

    got = await load_source_texts(db_session, refs)

    assert got == {1: "甲", 2: "乙", 3: "丙"}
