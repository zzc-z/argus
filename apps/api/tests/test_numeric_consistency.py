"""数字与日期的确定性一致性检查。

## 为什么数字要单独走一条通道

CRITIC 最致命的一类错误是**数字错**——原文说 2.5 倍，句子说 100 倍。
你自己的对照实验已经证明它有多难抓：

| 用例 | 嵌入相似度 | LLM 判定 | 确定性比对 |
|---|---|---|---|
| 原文 2.5 倍 → 句子 100 倍 | 0.9996（抓不到） | 靠 prompt 判据 1 | **直接判定不一致** |
| 原文「提升」→ 句子「下降」 | 0.9866（抓不到） | 靠 prompt 判据 2 | 方向判定抓不到，交给 LLM |

**数字是可以被程序精确比对的**，方向不行。所以数字类断言走确定性通道，
其余仍由 LLM 判 —— 这样既提高了最致命那类的准确率，又不牺牲覆盖面。

## 判据有多强

只判**明确不一致**，不判「一致」：

- 句子里出现了原文没有的数字 → 不一致（除非是句号/编号/角标之类的噪声）
- 同一个数字在句与原文中**单位不同** → 不一致（「32.1 亿元」vs「32.1 亿美元」）
- 同一个数字在句与原文中**量级不同** → 不一致（「2.5 倍」vs「100 倍」）

判不准的（原文根本没这个数、或是区间、或是近似说法）一律**放行**，
交给 LLM 判 —— 因为**误伤方向是质疑用户自己写的结论**，比漏判糟得多。

## 与 LLM 判定的关系

确定性通道**只做减法**：它判「不一致」时直接给 unsupported，
判不出来时**完全交给 LLM**。它不产生 supported 的结论 ——
那需要判断语义对应关系，程序做不了。
"""

from __future__ import annotations

import pytest

# 实现尚未落地（2026-11-18 进度）。用 importorskip 而不是让整个
# 测试文件报错——文件先落地，实现后补上；CI 不该因为「还没写」而红。
numeric_check = pytest.importorskip(
    "app.services.numeric_check",
    reason="数字一致性检查尚未实现（见 TASKS-国外接单.md）",
)

NumericVerdict = numeric_check.NumericVerdict
check_numeric_consistency = numeric_check.check_numeric_consistency
extract_numbers = numeric_check.extract_numbers


class TestExtractNumbers:
    def test_extracts_decimal_and_percent(self) -> None:
        assert extract_numbers("提升 2.5 倍") == [2.5]
        assert extract_numbers("同比增长 25%") == [25.0]
        assert extract_numbers("营收 32.1 亿美元") == [32.1]

    def test_strips_thousands_separator(self) -> None:
        assert extract_numbers("员工 1,200 人") == [1200.0]

    def test_ignores_footnote_markers(self) -> None:
        """角标 [1] 不是数字。"""
        assert extract_numbers("能效提升 2.5 倍[1]。") == [2.5]

    def test_ignores_year_in_quarterly_date(self) -> None:
        """「2025 年 3 月」的两个数都要抽出来（月份也要比对）。"""
        assert extract_numbers("于 2025 年 3 月发布") == [2025.0, 3.0]

    def test_no_numbers_returns_empty(self) -> None:
        assert extract_numbers("没有数字的一句话") == []


class TestNumericConsistency:
    def test_magnitude_mismatch_is_flagged(self) -> None:
        """原文 2.5 倍 → 句子 100 倍：量级不同，明确不一致。"""
        verdict = check_numeric_consistency(
            "能效比 Hopper 提升 100 倍[1]。",
            "NVIDIA Blackwell 架构能效比 Hopper 提升 2.5 倍。",
        )

        assert verdict.mismatch is True
        assert verdict.detail, "要能说明是哪个数对不上"

    def test_matching_number_passes_through(self) -> None:
        """数字一致 → 不判定为不一致，交给 LLM 判语义。"""
        verdict = check_numeric_consistency(
            "能效比 Hopper 提升 2.5 倍[1]。",
            "NVIDIA Blackwell 架构能效比 Hopper 提升 2.5 倍。",
        )

        assert verdict.mismatch is False
        assert verdict.detail == ""

    def test_unit_mismatch_is_flagged(self) -> None:
        """同一个数，单位不同 → 不一致。

        「32.1 亿元」vs「32.1 亿美元」——数值相同但量级差 1e8。
        """
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 亿元[1]。",
            "公司本季度营业收入 32.1 亿美元。",
        )

        assert verdict.mismatch is True

    def test_number_absent_from_source_is_not_flagged(self) -> None:
        """句子里的数字原文根本没提 → **放行**，交给 LLM。

        程序无法区分「原文没这个数所以是编的」与「原文用别的说法表达
        了同一个意思」。判不一致就是误伤。
        """
        verdict = check_numeric_consistency(
            "营收同比增长 25%[1]。",
            "公司本季度营业收入 32.1 亿美元，同比增长 22%。",
        )

        assert verdict.mismatch is False

    def test_range_in_source_is_not_flagged(self) -> None:
        """原文给的是区间，句子给其中一个值 → 放行。

        「3-5 倍」的区间里取 4 倍是合理的，不能判不一致。
        """
        verdict = check_numeric_consistency(
            "成本降低 4 倍[1]。",
            "成本降低 3-5 倍。",
        )

        assert verdict.mismatch is False

    def test_approximation_is_not_flagged(self) -> None:
        """近似说法（25% vs 约 25%）→ 放行。

        「约」「接近」「超过」这类限定词让严格比对失去意义。
        """
        verdict = check_numeric_consistency(
            "营收同比增长约 25%[1]。",
            "公司本季度营收同比增长 25%。",
        )

        assert verdict.mismatch is False

    def test_extra_number_in_sentence_is_flagged(self) -> None:
        """句子多出一个原文没有的数字 → 不一致。

        这是**编造数字**最直接的形态。
        """
        verdict = check_numeric_consistency(
            "营收 32.1 亿美元，净利润 8.2 亿美元[1]。",
            "公司本季度营业收入 32.1 亿美元。",
        )

        assert verdict.mismatch is True

    def test_date_mismatch_is_flagged(self) -> None:
        """日期不一致 → 不一致。"""
        verdict = check_numeric_consistency(
            "公司于 2024 年 3 月发布季度财报[1]。",
            "公司于 2025 年 3 月发布季度财报。",
        )

        assert verdict.mismatch is True

    def test_sentence_without_numbers_never_mismatches(self) -> None:
        """句子没数字 → 永远放行。"""
        verdict = check_numeric_consistency(
            "该工艺由台积电代工[1]。",
            "该工艺由三星代工。",
        )

        assert verdict.mismatch is False

    def test_verdict_carries_source_and_sentence_numbers(self) -> None:
        """判定要带上具体的数，方便在报告里说清哪里不对。"""
        verdict = check_numeric_consistency(
            "提升 100 倍[1]。",
            "提升 2.5 倍。",
        )

        assert isinstance(verdict, NumericVerdict)
        assert verdict.sentence_numbers
        assert verdict.source_numbers
        assert verdict.detail


class TestNumericCheckIsAdditiveOnly:
    """确定性通道**只做减法** —— 它从不产生 supported。"""

    def test_never_returns_support(self) -> None:
        """数字完全一致时，结论是「不判定」，不是「有据支撑」。"""
        verdict = check_numeric_consistency(
            "提升 2.5 倍[1]。",
            "提升 2.5 倍。",
        )

        assert verdict.mismatch is False
        assert verdict.detail == ""

    def test_mismatch_never_depends_on_semantics(self) -> None:
        """同一个数、同一句话，判定结果与语义无关 —— 这是确定性的定义。"""
        a = check_numeric_consistency("提升 100 倍[1]。", "提升 2.5 倍。")
        b = check_numeric_consistency("提升 100 倍[1]。", "提升 2.5 倍。")

        assert a.mismatch == b.mismatch
