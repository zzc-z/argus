"""Golden set 的**离线**校验。

## 这组测试测什么

**不需要 API key**，因此能在 CI 里跑。它验证的是评测基础设施本身没坏：

1. 数据集能加载、格式合法、id 不重复
2. **期望判定与正文里的角标对得上** —— 脚注号与变体序号必须与
   ``extract_cited_sentences`` 的实际抽取结果一致
3. **数据集能覆盖关键场景** —— 少了几类错误，这个集就不再有代表性
4. **判定解析层没漂移** —— 用数据集里的期望判定构造模型输出，
   走真实的 ``_parse_verdicts``，断言能全部还原

第 4 条是关键：它把「数据集」与「解析层」绑在一起。解析层改了 key 格式
（比如把变体序号换掉），这里立刻红——而不是等到跑真实模型评测时才发现
所有条目的判定都对不上。

## 测不了什么

**测不了 judge 的准确率。** 那需要真实模型 + 人工标注的对照，
见 ``eval/calibrate_judge.py``。这组测试的价值是让那条路随时可走：
数据集格式一变、解析层一动，这里先拦一道。
"""

from __future__ import annotations

import json

import pytest

from app.services.citation import extract_cited_sentences
from app.services.faithfulness import _parse_verdicts
from eval.golden import DEFAULT_DATASET, GoldenSet, load_golden_set

# 必须覆盖的错误类别。少一类，这个集就不再能代表「模型会犯的错」。
REQUIRED_CATEGORIES = {
    "baseline_supported",
    "numeric_magnitude_error",
    "reversed_conclusion",
    "entity_substitution",
    "legitimate_paraphrase",
    "same_footnote_two_sentences",
    "same_footnote_mixed_verdicts",
    "not_in_source",
    "multiple_markers_one_sentence",
}


@pytest.fixture(scope="module")
def golden() -> GoldenSet:
    return load_golden_set()


class TestGoldenSetLoads:
    def test_dataset_loads(self, golden: GoldenSet) -> None:
        assert len(golden.cases) >= 20, f"golden 集只有 {len(golden.cases)} 条，太少"

    def test_ids_unique(self, golden: GoldenSet) -> None:
        ids = [c.id for c in golden.cases]
        assert len(ids) == len(set(ids)), "id 重复"

    def test_every_case_has_note(self, golden: GoldenSet) -> None:
        """每条都要写清「这条要防什么」。

        没有 note 的样例，过三个月就没人知道它为什么在这儿——而看不懂
        意图的样例很容易在重构时被当成冗余删掉。
        """
        for case in golden.cases:
            assert case.note.strip(), f"{case.id} 缺 note"

    def test_required_categories_covered(self, golden: GoldenSet) -> None:
        """关键错误类别必须都在。

        少了「数字错 40 倍」这一类，这个集就测不出嵌入相似度方案的软肋；
        少了「同一脚注多句」，就测不出 id 碰撞。两个都是**曾经真实发生
        或极可能发生**的错误。
        """
        covered = set(golden.categories)
        missing = REQUIRED_CATEGORIES - covered
        assert not missing, f"缺少这些类别：{sorted(missing)}"


class TestGoldenExpectationsMatchText:
    def test_expected_verdicts_match_extracted_citations(self, golden: GoldenSet) -> None:
        """期望判定的 (脚注号, 变体序号) 必须与正文抽取结果一致。

        数据集里手写的 variant 如果与 ``extract_cited_sentences`` 的实际
        抽取对不上，评测时就会「看起来跑通了」但比对的是错的东西。

        **悬空角标（``expected_missing``）不在比对范围内**——它没有对应
        原文，是「引用表里没有这个条目」，不属于「有据 / 无据」的判定。
        """
        for case in golden.cases:
            if case.expected_skipped:
                continue
            sentences = extract_cited_sentences(case.report_text)
            actual: set[tuple[int, int]] = set()
            for footnote, variants in sentences.items():
                if footnote in case.expected_missing:
                    continue
                for variant_index in range(len(variants)):
                    actual.add((footnote, variant_index))
            expected = {(v.footnote, v.variant) for v in case.expected_verdicts}
            assert expected == actual, (
                f"{case.id}（{case.category}）期望判定与正文角标对不上："
                f"期望 {sorted(expected)}，实际 {sorted(actual)}"
            )

    def test_missing_expectations_only_for_absent_footnotes(
        self, golden: GoldenSet
    ) -> None:
        """``expected_missing`` 的角标必须**确实不在** sources 里。"""
        for case in golden.cases:
            for footnote in case.expected_missing:
                assert footnote not in case.sources, (
                    f"{case.id}：{footnote} 在 sources 里，不该期望为悬空"
                )

    def test_missing_footnote_appears_in_report(self, golden: GoldenSet) -> None:
        """``expected_missing`` 的角标必须在正文里真的出现过。

        否则这条声明是空的——「期望某个编号悬空」而正文里根本没这个编号，
        说明数据集写错了，评测时会白等一个永远不来的 missing。
        """
        for case in golden.cases:
            if not case.expected_missing:
                continue
            sentences = extract_cited_sentences(case.report_text)
            for footnote in case.expected_missing:
                assert footnote in sentences, (
                    f"{case.id}：期望 {footnote} 悬空，但正文里没有这个角标"
                )


class TestParserRoundTrip:
    def test_expected_verdicts_survive_parser(self, golden: GoldenSet) -> None:
        """用数据集里的期望判定构造模型输出，走真实解析层，还原。

        这是「数据集」与「解析层」的接缝。解析层的 key 格式一变
        （比如变体序号改法），这里立刻红——而不是等真实模型评测时才发现
        所有条目的判定都对不上。
        """
        for case in golden.cases:
            if not case.expected_verdicts:
                continue
            verdicts = [
                {
                    # tag 规则（第 k 句，k 从 1 起）：k=1 → "n"；k=2 → "nb"；
                    # k>=3 → "nb(k-1)"。注意 "b2" 对应的是 variant 2（第三句），
                    # 不是 variant 3。
                    "id": (
                        v.footnote
                        if v.variant == 0
                        else (f"{v.footnote}b" if v.variant == 1 else f"{v.footnote}b{v.variant}")
                    ),
                    "verdict": v.verdict,
                    "reason": "人工标注",
                }
                for v in case.expected_verdicts
            ]
            raw = json.dumps({"verdicts": verdicts}, ensure_ascii=False)

            expected_ids = {(v.footnote, v.variant) for v in case.expected_verdicts}
            got = _parse_verdicts(raw, expected_ids)

            assert set(got) == expected_ids, (
                f"{case.id}（{case.category}）：解析后 key 与期望不符 —— "
                f"期望 {sorted(expected_ids)}，实际 {sorted(got)}"
            )
            for v in case.expected_verdicts:
                assert got[(v.footnote, v.variant)][0] == (v.verdict == "supported"), (
                    f"{case.id}：({v.footnote}, {v.variant}) 的判定被解析错了"
                )


class TestDatasetFileShape:
    def test_dataset_is_jsonl(self) -> None:
        """每行一个 JSON 对象。

        JSONL 而不是 JSON 数组：行级的 diff 在 git 里可读——改了第 12 条
        只显示第 12 行变了，不会整个文件重排。
        """
        for lineno, line in enumerate(
            DEFAULT_DATASET.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            obj = json.loads(line)
            assert isinstance(obj, dict), f"第 {lineno} 行不是对象"
