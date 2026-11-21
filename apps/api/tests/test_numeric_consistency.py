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

    def test_same_currency_different_scale_is_flagged(self) -> None:
        """同币种、不同量级的单位 → 不一致。

        「32.1 亿元」写成「32.1 元」——数字一样，但量级差 1e8。
        这是**单位量级搞错**最常见的形态（写报告时把「亿」丢了）。

        按单位**字面**比会漏掉它（「元」≠「亿元」），必须按归一值比。
        """
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 元[1]。",
            "公司本季度营业收入 32.1 亿元。",
        )

        assert verdict.mismatch is True

    def test_wan_yuan_vs_yi_yuan_is_flagged(self) -> None:
        """万元与亿元之间同样按归一值比。"""
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 万元[1]。",
            "公司本季度营业收入 32.1 亿元。",
        )

        assert verdict.mismatch is True

    def test_yi_and_yi_yuan_are_the_same_dimension(self) -> None:
        """「32.1 亿」与「32.1 亿元」是同一句话的两种写法 → 放行。

        中文里「亿」默认就是亿元。判成量纲冲突是对用户自己写的结论的
        误伤——而命中确定性的条目**不进 LLM 复核**，误伤直接呈现给用户。
        """
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 亿[1]。",
            "公司本季度营业收入 32.1 亿元。",
        )

        assert verdict.mismatch is False, verdict.detail

    def test_wan_and_wan_yuan_are_the_same_dimension(self) -> None:
        """「万」与「万元」同理。"""
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 万[1]。",
            "公司本季度营业收入 32.1 万元。",
        )

        assert verdict.mismatch is False, verdict.detail

    def test_yi_yuan_vs_usd_yuan_is_still_a_conflict(self) -> None:
        """「亿」与「亿美元」**不是**同一量纲 → 仍判冲突。

        这是上一条测试护不住的：上一条两侧都是 cny 相容，这一条是
        scale vs usd——「亿」没说是哪种钱，不能和「美元」相容。
        """
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 亿[1]。",
            "公司本季度营业收入 32.1 亿美元。",
        )

        assert verdict.mismatch is True

    def test_bare_number_does_not_trigger_magnitude(self) -> None:
        """裸数之间不比量级。
        「本文共 3 页」vs「该文档共 30 页」——「页」不在单位表里，两边
        都是裸数。裸数没有量纲信息，比出 10 倍差异纯属噪音。
        """
        verdict = check_numeric_consistency(
            "本文共 3 页[1]。",
            "该文档共 30 页。",
        )

        assert verdict.mismatch is False

    def test_count_and_amount_are_not_compared(self) -> None:
        """「用户数」与「营收」不是同一个量 → 不比量级。

        「累计用户 1.2 亿，营收 32.1 亿元」——「1.2 亿」与「32.1 亿元」
        归一后差 26 倍，按「量纲相容」放它们一起比会误判成量级错误。

        研报里「用户数」与「营收」并列是常规写法，触发面不小。
        """
        verdict = check_numeric_consistency(
            "累计用户 1.2 亿，营收 32.1 亿元[1]。",
            "2025 年营收 32.1 亿元。",
        )

        assert verdict.mismatch is False, verdict.detail

    def test_ambiguous_scale_vs_count_is_not_a_conflict(self) -> None:
        """「1.2 万」与「12000 人」归一值相等，但不是单位冲突。

        「1.2 万」说的是不是人，程序无从知道（也可能是 1.2 万元）。
        歧义单位与非币种族比较时**不算冲突**。
        """
        verdict = check_numeric_consistency(
            "员工 1.2 万人[1]。",
            "员工 12000 人。",
        )

        assert verdict.mismatch is False, verdict.detail

    def test_cross_currency_same_number_is_a_conflict(self) -> None:
        """「32.1 万元」与「32.1 亿美元」→ 冲突。

        原值相同、币种不同——单位写错了。这条与
        ``test_yi_yuan_vs_usd_yuan_is_still_a_conflict`` 一起守住
        「币种错配」这一类。
        """
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 万元[1]。",
            "公司本季度营业收入 32.1 亿美元。",
        )

        assert verdict.mismatch is True

    def test_percentage_point_vs_percent_is_a_conflict(self) -> None:
        """「2.5 个百分点」与「2.5%」→ 冲突。

        百分点是**差值**、百分比是**比率**，量纲不同。混用是研报里
        真实发生过的错误。
        """
        verdict = check_numeric_consistency(
            "毛利率提升 2.5 个百分点[1]。",
            "毛利率 2.5%。",
        )

        assert verdict.mismatch is True

    def test_magnitude_detail_points_at_the_closest_number(self) -> None:
        """量级理由要指向**最接近**的那个原文数。

        「成本 3000 万元」vs 原文「成本 3.21 亿元」——真正的对应是这两个
        （差 10.7 倍），而「32.1 亿元」差 107 倍。理由指错方向比判错更
        麻烦：用户按提示去核对营收，核不到问题。
        """
        verdict = check_numeric_consistency(
            "营收 32.1 亿元，成本 3000 万元[1]。",
            "营收 32.1 亿元，成本 3.21 亿元。",
        )

        assert verdict.mismatch is True
        assert "3.21" in verdict.detail, f"理由指向了错的数：{verdict.detail}"
        assert "3000" in verdict.detail, verdict.detail

    def test_year_in_brackets_is_content_not_a_footnote(self) -> None:
        """「[2024] 年」里的 2024 是**内容**，不是角标。

        角标编号是 1-3 位（``citation._FOOTNOTE_RE`` 刻意如此），
        数字通道的角标正则必须与之一致——不限位数就会把年份当角标
        剥掉，真日期错（2024 vs 2025）就漏判了。
        """
        numbers = extract_numbers("根据 [2024] 年的数据，营收 32.1 亿元[1]。")

        assert 2024.0 in numbers, "「[2024] 年」里的年份不该被当角标剥掉"
        assert 1.0 not in numbers, "真正的角标 [1] 应当被忽略"

    def test_date_mismatch_with_bracket_year_is_flagged(self) -> None:
        """带方括号年份的真日期错仍要抓到。"""
        verdict = check_numeric_consistency(
            "根据 [2024] 年的数据发布[1]。",
            "公司于 2025 年发布。",
        )

        assert verdict.mismatch is True

    def test_duration_prefix_with_de_is_recognized(self) -> None:
        """「过去的 5 年」也要认得出是时长。

        回看窗口小于 4 会把「过去」截成「去」而漏判——于是「过去的 5 年」
        被当**日期**，与原文的「2025 年」比出「日期不一致」。

        理由指错方向比判错更麻烦：用户看到「日期不一致」会以为自己写错了
        年份，而真正的问题是他写的是一段时间。
        """
        verdict = check_numeric_consistency(
            "过去的 5 年营收复合增长 18%[1]。",
            "2025 年营收 32.1 亿美元，同比增长 18%。",
        )

        assert "日期不一致" not in verdict.detail, f"时长被当成了日期：{verdict.detail}"

    def test_magnitude_detail_names_the_units(self) -> None:
        """量级不一致的理由要带上单位。

        归一后可比，但用户看到的是原始写法——「32.1 与 32.1 相差过大」
        根本看不出哪里错。
        """
        verdict = check_numeric_consistency(
            "本季度营业收入 32.1 元[1]。",
            "公司本季度营业收入 32.1 亿元。",
        )

        assert "元" in verdict.detail and "亿元" in verdict.detail, verdict.detail

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

    def test_approximation_does_not_count_towards_extra_numbers(self) -> None:
        """近似数**不计入**「原文没有的数字」的计数。

        这是上一条测试护不住的场景：上一条里句子与原文的 % 各一个，
        近似与否都不影响结论；而这里原文只有一个 %，句子里有两个
        （一个近似、一个确定）——若把近似数也算进去，「30%」会被误判成
        编造数字。

        变异测试（M26）发现的缺口：删掉 soft 过滤后这条用例会变红。
        """
        verdict = check_numeric_consistency(
            "营收增长约 25%，海外增长 30%[1]。",
            "营收增长 25%。",
        )

        assert verdict.mismatch is False, "近似数不该算进计数——否则「30%」被误判成原文没有的数字"

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

    def test_duration_is_not_treated_as_date(self) -> None:
        """时长不是日期 → 放行。

        「最近 5 年」与「最近 3 年」是**两个不同的陈述**——句子引用的是
        原文的某一段，原文谈 3 年、句子谈 5 年完全可能合法。按日期规则
        去比会误伤用户自己写的结论，而**误伤比漏判糟得多**。
        """
        verdict = check_numeric_consistency(
            "最近 5 年[1]。",
            "公司最近 3 年增长稳健。",
        )

        assert verdict.mismatch is False

    def test_past_duration_is_not_treated_as_date(self) -> None:
        """「过去 N 年」同理。"""
        verdict = check_numeric_consistency(
            "过去 5 年[1]。",
            "过去 3 年公司增长稳健。",
        )

        assert verdict.mismatch is False

    def test_duration_against_date_is_not_called_a_magnitude_error(self) -> None:
        """时长与日期相比时，理由不能是「量级不一致」。

        「最近 5 年」的 5 与「2025 年」的 2025 同属 date_year 类别，
        归一后差 400 倍——按量级规则看是「相差过大」，但那是**两回事**：
        用户看到「量级不一致」会去核对倍数，而真正的问题是他把时长
        和日期点搞混了。理由指错方向比判错更麻烦。
        """
        verdict = check_numeric_consistency(
            "最近 5 年[1]。",
            "发布于 2025 年。",
        )

        assert "量级" not in verdict.detail, f"理由指错了方向：{verdict.detail}"

    def test_real_date_still_flagged_after_duration_fix(self) -> None:
        """排除时长**不能**把真日期错放过去。

        这是上一条测试护不住的：上一条的「5 年」与这里的「2024 年」
        都是 date_year 类别，修法若写成「跳过所有含年的数」，
        真日期错就一起漏了。
        """
        verdict = check_numeric_consistency(
            "公司于 2024 年发布[1]。",
            "公司于 2025 年发布。",
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
