"""Golden set 的加载与校验。

## 为什么有这个东西

argus 此前**没有任何质量评测**——769 条测试全在验证「代码按我写的逻辑跑」，
没有一条回答「这个 agent 产出的报告，质量是变好了还是变差了」。

Golden set 是那条路的起点：一份**人工标注过期望判定**的固定数据集，
每次改动后跑一遍，看指标是升还是降。

## 两层用法

1. **CI 可跑**（不需要 API key）：验证数据集本身与判定解析层没有漂移。
   见 ``tests/eval/test_golden.py``。
2. **需要 key**（真实测 judge）：跑真实模型算通过率、TPR / TNR、顺序一致性。
   见 ``calibrate_judge.py``。

## 数据格式

每行一个 JSON：

```json
{
  "id": "g001",
  "category": "numeric_magnitude_error",
  "note": "这条要防什么",
  "report_text": "带 [n] 角标的正文",
  "sources": {"1": "角标 1 对应的原文全文"},
  "expected_verdicts": [
    {"footnote": 1, "variant": 0, "verdict": "supported"}
  ]
}
```

- ``expected_verdicts[].variant`` 是**同一角标内的变体序号**（从 0 起）：
  角标 1 被两个句子引用时，第一个句子是 variant 0，第二个是 variant 1。
- ``expected_skipped: true`` 表示期望整个校验被跳过（无角标 / 全部悬空）。
- ``expected_missing`` 列出期望被报为悬空的角标。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

EVAL_DIR = Path(__file__).parent
DEFAULT_DATASET = EVAL_DIR / "datasets" / "golden_v1.jsonl"

VALID_VERDICTS = frozenset({"supported", "unsupported"})


@dataclass(frozen=True)
class ExpectedVerdict:
    """一条期望的判定。"""

    footnote: int
    variant: int
    verdict: str


@dataclass(frozen=True)
class GoldenCase:
    """一条 golden 样例。"""

    id: str
    category: str
    note: str
    report_text: str
    sources: dict[int, str]
    expected_verdicts: tuple[ExpectedVerdict, ...]
    expected_skipped: bool = False
    expected_missing: tuple[int, ...] = ()


@dataclass(frozen=True)
class GoldenSet:
    """一份 golden 集合。"""

    name: str
    cases: tuple[GoldenCase, ...] = field(default_factory=tuple)

    def by_category(self) -> dict[str, list[GoldenCase]]:
        out: dict[str, list[GoldenCase]] = {}
        for case in self.cases:
            out.setdefault(case.category, []).append(case)
        return out

    @property
    def categories(self) -> list[str]:
        return sorted({c.category for c in self.cases})


def load_golden_set(path: Path | None = None) -> GoldenSet:
    """读并**校验**一份 golden 集。

    校验失败要早——数据集里的笔误会让评测结果没有意义，而「评测结果
    没意义」这件事本身不会报错。
    """
    target = path or DEFAULT_DATASET
    if not target.exists():
        raise FileNotFoundError(f"找不到 golden 数据集：{target}")

    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()

    for lineno, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target.name}:{lineno} 不是合法 JSON：{exc}") from exc

        case_id = str(data.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"{target.name}:{lineno} 缺 id")
        if case_id in seen_ids:
            raise ValueError(f"{target.name}:{lineno} id 重复：{case_id}")
        seen_ids.add(case_id)

        report_text = str(data.get("report_text", ""))
        if not report_text:
            raise ValueError(f"{target.name}:{lineno}（{case_id}）缺 report_text")

        sources_raw = data.get("sources", {})
        if not isinstance(sources_raw, dict):
            raise ValueError(f"{target.name}:{lineno}（{case_id}）的 sources 必须是对象")
        sources = {int(k): str(v) for k, v in sources_raw.items()}

        verdicts: list[ExpectedVerdict] = []
        for item in data.get("expected_verdicts", []):
            verdict = str(item.get("verdict", ""))
            if verdict not in VALID_VERDICTS:
                raise ValueError(
                    f"{target.name}:{lineno}（{case_id}）的 verdict 非法：{verdict!r}"
                    f"（只允许 {sorted(VALID_VERDICTS)}）"
                )
            verdicts.append(
                ExpectedVerdict(
                    footnote=int(item["footnote"]),
                    variant=int(item.get("variant", 0)),
                    verdict=verdict,
                )
            )

        cases.append(
            GoldenCase(
                id=case_id,
                category=str(data.get("category", "uncategorized")),
                note=str(data.get("note", "")),
                report_text=report_text,
                sources=sources,
                expected_verdicts=tuple(verdicts),
                expected_skipped=bool(data.get("expected_skipped", False)),
                expected_missing=tuple(int(n) for n in data.get("expected_missing", [])),
            )
        )

    if not cases:
        raise ValueError(f"{target.name} 是空的")

    return GoldenSet(name=target.stem, cases=tuple(cases))
