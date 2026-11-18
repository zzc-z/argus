"""``verify_citations`` 的集成测试 —— 判定链路本身。

## 为什么单独一个文件

``test_faithfulness.py`` 覆盖的是**解析层**（``_parse_verdicts``）与
**事件接线**（``run_agent`` 是否发出 faithfulness 帧）。而
``verify_citations`` 的**主体**——构造 prompt、调用模型、解析判定、
逐条消费、组装报告——长期是零覆盖：

    app/services/faithfulness.py   116 stmts   49 miss   53.90%
    Missing: 122-130, 147, 153-154, 156, 177, 220-290, 309-323

于是出现了一个结构性的漏洞：**解析层修得再好，链路层的错也测不出来**。

最典型的例子是同一个脚注被多个句子引用时，解析出的两条 verdict
（「1」与「1b」）在消费端被归一成同一个 key——解析层的单测全绿，
用户看到的通过率却是错的。这个文件就是补上这一层。

## 测什么

1. **端到端计数**：判定数、通过数、未支撑列表必须自洽
2. **同一脚注多句**：两条句子各自独立判定，且报告指向**正确的那一句**
3. **分母纪律**：模型没回的条目必须从分母里剔除
4. **降级**：模型报错 → skipped；截断 → 可区分的 reason
5. **max_tokens 随条数增长**：不能硬编码
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.services.faithfulness import (
    JudgeTruncated,
    verify_citations,
)

# ── 测试替身 ──────────────────────────────────────────────────


class _FakeMessage:
    """模拟 ``final`` 消息。"""

    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self._text = text
        self.stop_reason = stop_reason
        self.usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 5})()

    def model_dump(self, exclude_none: bool = True) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeStream:
    def __init__(self, message: _FakeMessage | Exception) -> None:
        self._message = message

    async def __aenter__(self) -> _FakeStream:
        if isinstance(self._message, Exception):
            raise self._message
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get_final_message(self) -> _FakeMessage:
        assert not isinstance(self._message, Exception)
        return self._message


class _FakeMessages:
    def __init__(self, message: _FakeMessage | Exception) -> None:
        self._message = message
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        return _FakeStream(self._message)


class _FakeClient:
    def __init__(self, message: _FakeMessage | Exception) -> None:
        self.messages = _FakeMessages(message)


def _client(text: str, stop_reason: str = "end_turn") -> _FakeClient:
    return _FakeClient(_FakeMessage(text, stop_reason=stop_reason))


# ── 端到端计数 ────────────────────────────────────────────────


class TestVerifyCitationsCounting:
    async def test_supported_and_unsupported_are_counted_separately(self) -> None:
        """两条引用、一条有据一条无据 → checked=2, supported=1。"""
        client = _client(
            '{"verdicts": ['
            '{"id": "1", "verdict": "supported", "reason": "原文支持"},'
            '{"id": "2", "verdict": "unsupported", "reason": "原文说的是相反的"}'
            "]}"
        )

        report = await verify_citations(
            client,  # type: ignore[arg-type]
            "能效提升 2.5 倍[1]。工艺是台积电[2]。",
            {1: "Blackwell 能效提升 2.5 倍", 2: "工艺由三星代工"},
        )

        assert report.skipped is False
        assert report.checked == 2
        assert report.supported == 1
        assert report.pass_rate == 0.5
        assert len(report.unsupported) == 1
        assert report.unsupported[0].footnote == 2
        assert "工艺是台积电" in report.unsupported[0].sentence

    async def test_no_citations_skipped(self) -> None:
        """报告没有任何角标 → skipped，不是「全部无据」。"""
        report = await verify_citations(
            _client("{}"),  # type: ignore[arg-type]
            "没有任何引用的报告。",
            {1: "原文"},
        )

        assert report.skipped is True
        assert report.checked == 0
        assert report.supported == 0
        assert report.pass_rate == 0.0
        assert report.unsupported == []

    async def test_all_footnotes_missing_skipped(self) -> None:
        """角标指向的条目引用表里没有 → 无法核对，skipped。"""
        report = await verify_citations(
            _client("{}"),  # type: ignore[arg-type]
            "引用了 [1]。",
            {},  # 引用表是空的
        )

        assert report.skipped is True
        assert report.checked == 0
        assert report.missing == [1]

    async def test_missing_footnote_excluded_from_denominator(self) -> None:
        """`missing` 的条目不进分母——但要单独报出来。

        角标 [9] 在引用表里不存在，说明正文引用了一个不存在的条目。
        这类错误**不能混进通过率**：它既不是「无据支撑」，也不是
        「无法核对」——它是引用表与正文不一致。
        """
        client = _client(
            '{"verdicts": [{"id": "1", "verdict": "supported", "reason": "ok"}]}'
        )

        report = await verify_citations(
            client,  # type: ignore[arg-type]
            "有据的一句[1]。编造的一句[9]。",
            {1: "原文"},
        )

        assert report.missing == [9]
        assert report.checked == 1
        assert report.supported == 1
        assert report.pass_rate == 1.0


# ── 同一脚注被多个句子引用 ────────────────────────────────────


class TestVerifyCitationsMultipleSentences:
    async def test_two_sentences_same_footnote_judged_independently(self) -> None:
        """同一脚注被两句引用 → 两句各自判定，互不影响。

        研报里「先给结论、再展开论证」引用同一脚注是常规写法。
        早先的实现把两条 verdict 归一成同一个 key——后写的赢，
        于是**有据的句子被误报成无据**，或**编造的句子被放过**。
        """
        client = _client(
            '{"verdicts": ['
            '{"id": "1", "verdict": "supported", "reason": "原文说 2.5 倍"},'
            '{"id": "1b", "verdict": "unsupported", "reason": "原文是 2.5 倍不是 100 倍"}'
            "]}"
        )

        report = await verify_citations(
            client,  # type: ignore[arg-type]
            "营收增长 2.5 倍[1]。营收增长 100 倍[1]。",
            {1: "营收增长 2.5 倍"},
        )

        assert report.skipped is False
        assert report.checked == 2, "两句都要计入分母"
        assert report.supported == 1
        assert report.pass_rate == 0.5
        assert len(report.unsupported) == 1
        # **报告的必须是实际被判定的那一句**，不是第一句
        assert "100 倍" in report.unsupported[0].sentence
        assert "2.5 倍" not in report.unsupported[0].sentence.replace("不是 2.5 倍", "")

    async def test_reverse_order_same_result(self) -> None:
        """verdict 的顺序不能决定归属。"""
        client = _client(
            '{"verdicts": ['
            '{"id": "1b", "verdict": "unsupported", "reason": "原文是 2.5 倍"},'
            '{"id": "1", "verdict": "supported", "reason": "原文说 2.5 倍"}'
            "]}"
        )

        report = await verify_citations(
            client,  # type: ignore[arg-type]
            "营收增长 2.5 倍[1]。营收增长 100 倍[1]。",
            {1: "营收增长 2.5 倍"},
        )

        assert report.checked == 2
        assert report.supported == 1
        assert len(report.unsupported) == 1
        assert "100 倍" in report.unsupported[0].sentence

    async def test_three_sentences_same_footnote_get_distinct_tags(self) -> None:
        """同一脚注被**三句**引用时，每句的 tag 必须唯一。

        早先 ``_build_user_prompt`` 给所有非首变体都标 ``f"{n}b"``——
        于是第 2 句与第 3 句拿到同一个 tag，模型对这两句只能给一个判定，
        第 3 句的判定要么丢失、要么与第 2 句碰撞。
        """
        from app.services.faithfulness import _build_user_prompt

        sentences = {1: ["句A", "句B", "句C"]}
        prompt = _build_user_prompt(sentences, {1: "原文"})

        tags = re.findall(r"### 句子 (\S+?)（", prompt)
        assert tags == ["1", "1b", "1b2"], f"三个变体的 tag 必须互不相同：{tags}"

        # 三个 tag 都要能被解析成不同的 (脚注号, 变体序号)
        from app.services.faithfulness import _verdict_key

        keys = [_verdict_key(t) for t in tags]
        assert keys == [(1, 0), (1, 1), (1, 2)]
        assert len(set(keys)) == 3, "三个变体解析后不能撞到同一个 key"

    async def test_three_sentences_same_footnote_all_judged(self) -> None:
        """三句都要能独立判定，且互不影响。"""
        client = _client(
            '{"verdicts": ['
            '{"id": "1", "verdict": "supported", "reason": "a"},'
            '{"id": "1b", "verdict": "unsupported", "reason": "b"},'
            '{"id": "1b2", "verdict": "supported", "reason": "c"}'
            "]}"
        )

        report = await verify_citations(
            client,  # type: ignore[arg-type]
            "营收增长 25%[1]。营收增长 100%[1]。海外增长放缓[1]。",
            {1: "2025 年营收同比增长 25%，华东区是主要增长来源。"},
        )

        assert report.checked == 3, "三句都要计入分母"
        assert report.supported == 2
        assert len(report.unsupported) == 1
        assert "100%" in report.unsupported[0].sentence
        assert report.unsupported[0].variant == 1


# ── 分母纪律 ──────────────────────────────────────────────────


class TestVerifyCitationsDenominator:
    async def test_unjudged_excluded_from_denominator(self) -> None:
        """模型没回的条目必须从分母里剔除。

        留在 ``checked`` 里会出现「通过 1 条、0 条未支撑」这种自相矛盾
        的数字，而且分母永远不减 → 通过率系统性偏低。
        """
        client = _client(
            '{"verdicts": [{"id": "1", "verdict": "supported", "reason": "ok"}]}'
        )

        report = await verify_citations(
            client,  # type: ignore[arg-type]
            "第一句[1]。第二句[2]。",
            {1: "原文一", 2: "原文二"},
        )

        assert report.checked == 1, "没判出的那条不进分母"
        assert report.supported == 1
        assert report.pass_rate == 1.0
        assert report.unsupported == []

    async def test_all_unjudged_is_skipped_not_all_unsupported(self) -> None:
        """一条都没判出来 → 「无法校验」，不是「全部无据」。"""
        report = await verify_citations(
            _client('{"verdicts": []}'),  # type: ignore[arg-type]
            "第一句[1]。",
            {1: "原文"},
        )

        assert report.skipped is True
        assert report.checked == 0
        assert report.supported == 0
        assert report.unsupported == []


# ── 降级路径 ──────────────────────────────────────────────────


class TestVerifyCitationsDegradation:
    async def test_model_error_degrades_to_skipped(self) -> None:
        """模型调用失败 → skipped，reason 是「校验调用失败」。"""
        client = _FakeClient(RuntimeError("boom"))

        report = await verify_citations(
            client,  # type: ignore[arg-type]
            "一句话[1]。",
            {1: "原文"},
        )

        assert report.skipped is True
        assert report.reason == "校验调用失败"
        assert report.checked == 0

    async def test_truncated_output_raises_distinct_exception(self) -> None:
        """截断必须与「调用失败」区分开。

        截断是**配置问题**（max_tokens 不够），解析失败是模型返回了
        非法结构。两者的排查方向完全不同：前者调配置，后者改判定方式。
        混成一句话「无法校验」，排查会直接跑偏。
        """
        client = _client('{"verdicts": [{"id": "1"', stop_reason="max_tokens")

        with pytest.raises(JudgeTruncated) as excinfo:
            await verify_citations(
                client,  # type: ignore[arg-type]
                "一句话[1]。",
                {1: "原文"},
            )

        assert "截断" in str(excinfo.value)
        assert "max_tokens" in str(excinfo.value)

    async def test_malformed_json_degrades_to_skipped(self) -> None:
        """模型返回非法 JSON（但没截断）→ 降级，且**文案能区分**。

        「输出不是合法 JSON」与「模型返回了合法 JSON 但没给判定」都表现为
        「没拿到 verdict」，但真因完全不同：前者是输出格式坏了（可诊断），
        后者是能力/内容问题。混成一句话会让排查方向跑偏。
        """
        report = await verify_citations(
            _client("这不是 JSON"),  # type: ignore[arg-type]
            "一句话[1]。",
            {1: "原文"},
        )

        assert report.skipped is True
        assert "无法解析" in report.reason
        assert report.checked == 0

    async def test_valid_json_without_verdicts_is_distinct_reason(self) -> None:
        """合法 JSON 但没有 verdict 条目 → 与「解析失败」区分开。"""
        report = await verify_citations(
            _client('{"verdicts": []}'),  # type: ignore[arg-type]
            "一句话[1]。",
            {1: "原文"},
        )

        assert report.skipped is True
        assert report.reason == "模型未返回任何判定"


# ── max_tokens ────────────────────────────────────────────────


class TestVerifyCitationsMaxTokens:
    async def test_max_tokens_scales_with_number_of_items(self) -> None:
        """max_tokens 必须随待判条数增长，不能硬编码。

        硬编码 2048 时，20 条引用各带一句中文 reason 会被截断——
        JSON 不完整 → 解析抛异常 → 整批判定被丢弃。
        """
        client = _client("{}")

        report = "句子[1]。句子[2]。句子[3]。句子[4]。句子[5]。" * 4
        sources = dict.fromkeys(range(1, 21), "原文")

        await verify_citations(client, report, sources)  # type: ignore[arg-type]

        sent = client.messages.calls[0]
        assert sent["max_tokens"] > 2048, "20 条引用时 max_tokens 必须大于 2048"

    async def test_max_tokens_has_floor(self) -> None:
        """条目少时也不能低于下限。"""
        client = _client("{}")

        await verify_citations(client, "一句话[1]。", {1: "原文"})  # type: ignore[arg-type]

        assert client.messages.calls[0]["max_tokens"] >= 2048
