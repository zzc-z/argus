"""Judge 一致率校准：量化 Critic 的真阳性率 / 真负率 / Cohen's κ。

## 为什么需要这个

``verify_citations`` 输出的「通过率」是一个**没有分母校准的数字**。

业界的警告很直接（Hamel, *The Unreliability of LLM Judges*）：

    "if an error occurs in 5% of examples, a judge that always predicts Pass
     still has 95% agreement while detecting none of the errors."

也就是说——**只看「一致率」会被骗**。一个永远说「有据支撑」的 judge
一致率可以高达 95%，却一条错误都没抓到。

所以这里算的是：

- **TPR**（真阳性率）：该判无据的，判出来了多少 —— **漏判是致命的**
  （编造的数字混进报告，用户看不出来）
- **TNR**（真阴性率）：该判有据的，判对了多少 —— 误伤方向是「质疑
  用户自己写的结论」，比漏判糟得多
- **Cohen's κ**：剔除「碰巧一致」后的真实一致性。基准：> 0.7 可接受，
  > 0.8 好

## 怎么跑

    cd apps/api
    uv run python -m eval.calibrate_judge              # 全量
    uv run python -m eval.calibrate_judge --repeat 3   # 每条跑 3 次看方差

## 会暴露什么

1. **判��准吗** —— κ 与 TPR/TNR
2. **稳吗** —— 同一输入跑 N 次的判定是否一致（非确定性）
3. **顺序有影响吗** —— 打乱判定顺序后判定是否改变（position bias）

第 3 条尤其重要：``JUDGE_PROMPT`` 里要求「逐条独立判定」，但那只是
**一句请求**，不是保证。实测才知道模型听不听。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.credentials import resolve_env_credentials
from app.services.faithfulness import (
    _parse_verdicts,
)
from app.services.llm import get_anthropic_client
from eval.golden import GoldenCase, GoldenSet, load_golden_set


@dataclass
class CaseOutcome:
    """一条 golden 样例的判定结果。"""

    case_id: str
    category: str
    expected: dict[tuple[int, int], bool]
    actual: dict[tuple[int, int], bool]
    skipped: bool = False
    reason: str = ""


def _cohen_kappa(pairs: Sequence[tuple[bool, bool]]) -> float:
    """Cohen's κ —— 剔除「碰巧一致」后的真实一致性。

    κ = (Po - Pe) / (1 - Pe)
      Po = 实际一致的比例
      Pe = 随机猜的一致比例（按两类的边缘分布算）
    """
    if not pairs:
        return 0.0
    total = len(pairs)
    observed = sum(1 for e, a in pairs if e == a) / total
    expected_count = sum(1 for e, _ in pairs if e)
    actual_count = sum(1 for _, a in pairs if a)
    p_e = (expected_count / total) * (actual_count / total) + (1 - expected_count / total) * (
        1 - actual_count / total
    )
    if math.isclose(p_e, 1.0):
        # 两类里有一类从不出现 → 随机猜也有 100% 一致率，κ 无定义。
        # 返回 1.0 表示「无从区分」，由调用方结合 TPR/TNR 一起看。
        return 1.0
    return (observed - p_e) / (1 - p_e)


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 置信区间。

    小样本下不要用正态近似的置信区间——它会给出越界或过窄的结果。
    """
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


async def _judge_once(
    client: Any,
    case: GoldenCase,
    order: Sequence[tuple[int, int]] | None = None,
) -> dict[tuple[int, int], bool]:
    """跑一次判定，返回 ``{(脚注号, 变体序号): 是否支撑}``。

    ``order`` 指定待判项的顺序——用于测 position bias（同一批内容，
    打乱顺序后判定是否改变）。
    """
    from app.services.citation import extract_cited_sentences

    sentences = extract_cited_sentences(case.report_text)
    verifiable = [n for n in sorted(sentences) if n in case.sources]

    items: list[tuple[int, int]] = []
    for n in verifiable:
        for variant_index in range(len(sentences[n])):
            items.append((n, variant_index))
    if order is not None:
        items = [it for it in order if it in set(items)]

    if not items:
        return {}

    # 按 order 重排句子与原文，构造 prompt
    ordered_sentences: dict[int, list[str]] = {}
    for n in verifiable:
        ordered_sentences[n] = list(sentences[n])

    # _build_user_prompt 按 (n, variant) 顺序输出；要测顺序效应就得能重排。
    # 这里直接自己拼，顺序由 order 决定。
    source_block = "\n\n".join(f"### 原文 {n}\n{case.sources[n]}" for n in sorted(case.sources))
    sentence_blocks = []
    for n, variant_index in items:
        tag = (
            n if variant_index == 0 else (f"{n}b" if variant_index == 1 else f"{n}b{variant_index}")
        )
        sentence_blocks.append(
            f"### 句子 {tag}（对应「原文 {n}」）\n{ordered_sentences[n][variant_index]}"
        )
    prompt = "\n\n".join(sentence_blocks) + "\n\n" + source_block

    from app.services.faithfulness import JUDGE_PROMPT

    request: dict[str, Any] = {
        "model": _critic_model(),
        "max_tokens": max(2048, len(items) * 300),
        "system": JUDGE_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with client.messages.stream(**request) as stream:
        final = await stream.get_final_message()

    content = final.model_dump(exclude_none=True)["content"]
    raw = "".join(b.get("text", "") for b in content if b.get("type") == "text")

    expected_ids = set(items)
    verdicts = _parse_verdicts(raw, expected_ids)
    return {key: ok for key, (ok, _) in verdicts.items()}


def _critic_model() -> str:
    from app.config import get_settings

    settings = get_settings()
    return settings.anthropic_critic_model or settings.anthropic_complex_model


async def _run_case(client: Any, case: GoldenCase) -> CaseOutcome:
    expected = {(v.footnote, v.variant): v.verdict == "supported" for v in case.expected_verdicts}
    try:
        actual = await _judge_once(client, case)
    except Exception as exc:
        return CaseOutcome(
            case_id=case.id,
            category=case.category,
            expected=expected,
            actual={},
            skipped=True,
            reason=f"调用失败：{exc}",
        )
    return CaseOutcome(
        case_id=case.id,
        category=case.category,
        expected=expected,
        actual=actual,
    )


async def calibrate(
    golden: GoldenSet,
    repeat: int = 1,
    check_order: bool = True,
) -> dict[str, Any]:
    """跑完整轮校准，产出指标。"""
    # 校准脚本是**部署级**工具（不针对某个用户），用环境变量里的凭据。
    client = get_anthropic_client(resolve_env_credentials())

    outcomes: list[CaseOutcome] = []
    for case in golden.cases:
        for _ in range(repeat):
            outcomes.append(await _run_case(client, case))

    # ── 逐条比对 ──
    #
    # 混淆矩阵的定义（**别弄反**）：
    #   TP = 期望无据，实际也判无据  → 正确抓到
    #   FN = 期望无据，实际判成有据  → **漏判**（危险：编造的数字混进报告）
    #   TN = 期望有据，实际也判有据  → 正确放过
    #   FP = 期望有据，实际判成无据  → **误伤**（质疑用户自己写的结论）
    #
    # 「模型没给判定」**既不是 FP 也不是 FN** —— 它是「未判定」，单独统计。
    # 把它算进 FN 会让「漏判率」虚高（实际上模型只是没回答，不是答错）。
    pairs: list[tuple[bool, bool]] = []
    per_category: dict[str, dict[str, int]] = {}
    for out in outcomes:
        bucket = per_category.setdefault(
            out.category,
            {"total": 0, "correct": 0, "tp": 0, "fn": 0, "tn": 0, "fp": 0, "unjudged": 0},
        )
        for key, expected_ok in out.expected.items():
            actual_ok = out.actual.get(key)
            bucket["total"] += 1
            if actual_ok is None:
                bucket["unjudged"] += 1
                continue
            bucket["correct"] += 1 if expected_ok == actual_ok else 0
            pairs.append((expected_ok, actual_ok))
            if not expected_ok and not actual_ok:
                bucket["tp"] += 1
            elif not expected_ok and actual_ok:
                bucket["fn"] += 1
            elif expected_ok and actual_ok:
                bucket["tn"] += 1
            else:
                bucket["fp"] += 1

    total = len(pairs)
    tp = sum(1 for e, a in pairs if not e and not a)
    fn = sum(1 for e, a in pairs if not e and a)
    tn = sum(1 for e, a in pairs if e and a)
    fp = sum(1 for e, a in pairs if e and not a)
    unjudged = sum(1 for out in outcomes for key in out.expected if out.actual.get(key) is None)

    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    kappa = _cohen_kappa(pairs)

    # ── 非确定性：同一输入跑 N 次判定是否一致 ──
    stability: dict[str, Any] = {}
    if repeat > 1:
        by_case: dict[str, list[CaseOutcome]] = {}
        for out in outcomes:
            by_case.setdefault(out.case_id, []).append(out)
        unstable = []
        for case_id, outs in by_case.items():
            keys = [tuple(sorted(o.actual.items())) for o in outs]
            if len(set(keys)) > 1:
                unstable.append(case_id)
        stability = {
            "repeat": repeat,
            "unstable_cases": unstable,
            "stable_ratio": 1 - len(unstable) / len(by_case) if by_case else 0.0,
        }

    # ── position bias：打乱顺序后判定是否改变 ──
    order_sensitivity: dict[str, Any] = {}
    if check_order:
        changed: list[str] = []
        for case in golden.cases:
            from app.services.citation import extract_cited_sentences

            sentences = extract_cited_sentences(case.report_text)
            items = [
                (n, vi)
                for n in sorted(sentences)
                if n in case.sources
                for vi in range(len(sentences[n]))
            ]
            if len(items) < 2:
                continue
            baseline = await _judge_once(client, case)
            reversed_order = await _judge_once(client, case, order=list(reversed(items)))
            for key in set(baseline) & set(reversed_order):
                if baseline[key] != reversed_order[key]:
                    changed.append(f"{case.id}:{key}")
                    break
        order_sensitivity = {
            "cases_checked": sum(
                1
                for c in golden.cases
                if len(
                    [
                        (n, vi)
                        for n in sorted(extract_cited_sentences(c.report_text))
                        if n in c.sources
                        for vi in range(len(extract_cited_sentences(c.report_text)[n]))
                    ]
                )
                >= 2
            ),
            "changed": changed,
        }

    return {
        "dataset": golden.name,
        "cases": len(golden.cases),
        "repeat": repeat,
        "judged_items": total,
        "unjudged_items": unjudged,
        "tpr": tpr,
        "tnr": tnr,
        "tpr_ci": _wilson_interval(tp, tp + fn) if (tp + fn) else (0.0, 0.0),
        "tnr_ci": _wilson_interval(tn, tn + fp) if (tn + fp) else (0.0, 0.0),
        "cohen_kappa": kappa,
        "confusion": {"tp": tp, "fn": fn, "tn": tn, "fp": fp, "unjudged": unjudged},
        "per_category": per_category,
        "stability": stability,
        "order_sensitivity": order_sensitivity,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge 一致率校准")
    parser.add_argument("--repeat", type=int, default=1, help="每条跑几次（测非确定性）")
    parser.add_argument("--no-order-check", action="store_true", help="跳过 position bias 检查")
    parser.add_argument("--out", type=Path, default=None, help="结果写到这个 JSON 文件")
    args = parser.parse_args(argv)

    golden = load_golden_set()
    result = asyncio.run(calibrate(golden, repeat=args.repeat, check_order=not args.no_order_check))

    out_path = args.out or Path(__file__).parent / "reports" / "judge_calibration.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"数据集：{result['dataset']}（{result['cases']} 条）")
    print(f"判定条目：{result['judged_items']}（未判定 {result['unjudged_items']}）")
    print(f"TPR（该判无据的，判出来了多少）：{result['tpr']:.1%}  ← 漏判最危险")
    print(f"TNR（该判有据的，没误伤多少）：{result['tnr']:.1%}")
    print(f"Cohen's κ：{result['cohen_kappa']:.3f}  （>0.7 可接受，>0.8 好）")
    print(f"混淆：{result['confusion']}")
    if result["stability"]:
        print(
            f"稳定性（{result['stability']['repeat']} 次重跑）：{result['stability']['stable_ratio']:.1%}"
        )
        if result["stability"]["unstable_cases"]:
            print(f"  不稳定的条目：{result['stability']['unstable_cases']}")
    if result["order_sensitivity"]:
        print(f"顺序敏感：{result['order_sensitivity']['changed']}")
    print(f"\n结果写入：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
