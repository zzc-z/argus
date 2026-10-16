"""引用忠实度校验：报告里的每条 [n] 是否真能在它引用的原文里找到支撑。

Critic 节点的实现（sprint plan Day 13）。产出「通过率 + 未支撑条目」，
**不阻断、不改写**——模型已经跑完多轮检索，剔除内容等于让它白跑，
而标注出来让用户自己判断，成本为零。

## 为什么不用嵌入相似度

**实测否掉的**（2026-10-15，真实 embedder + 真实 chunk）：

=======================================  ==========  ==========
用例                                      余弦        期望
=======================================  ==========  ==========
原句（真的）                                 1.0000     支撑
数字 ×100（原文 2.5 倍 → 100 倍）            0.9996     **不支撑**
「能效略有下降」（结论说反）                   0.9866     **不支撑**
工艺反了（台积电 → 三星）                     0.9522     **不支撑**
张冠李戴（换成另一段 chunk 的内容）            0.4755     不支撑
完全无关                                    0.1528     不支撑
=======================================  ==========  ==========

嵌入向量编码的是**语义主题**：把「2.5 倍」改成「100 倍」主题没变，
余弦几乎不动。它能抓「跑了题」，抓不到「说反了」和「数字错 40 倍」——
而后者恰是研报最致命的两类错误。用它产出的「通过率」是自欺欺人。

## 因此：LLM 逐条判定，全部塞进一次调用

不用每句一次（那是 checked × N 次调用，成本不可接受），而是把全部
句子与其引用原文拼成一份 JSON 交给模型一次判定。报告 2300 字、20 条
引用的大头，约 15k tokens 输入、几百 tokens 输出。

**解析失败时降级为「无法校验」**，不假装通过也不假装失败——把降级状态
与「判定失败」区分开，否则线上 JSON 格式漂移会被读成「全部引用无据」。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import DocumentChunk
from app.services.citation import Reference

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


# ── 抽取报告里带角标的句子 ──────────────────────────────────

# 行内角标 [1] / [1,2] / [1][2]。
#
# `\d{1,3}` 而非 `\d+`：引用表编号是「每个请求独立从 1 起」的自增序号，
# 实际不会超过三位数。用 `\d+` 会把 "[2024] 年的报告" 里的年份当成编号
# 2024——那是个没人引用的编号，会让校验报告里凭空多一条「引用缺失」。
_FOOTNOTE_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+")


def extract_cited_sentences(text: str) -> dict[int, list[str]]:
    """按引用编号收集带角标的句子。

    返回 ``{引用编号: [句子, ...]}``。同一句里带多个角标时，它会同时
    出现在每个编号下——**这句话确实同时引用了多条资料**，两两都要校验。
    """
    result: dict[int, list[str]] = {}
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for group in _FOOTNOTE_RE.findall(sentence):
            for raw in group.split(","):
                number = int(raw.strip())
                result.setdefault(number, []).append(sentence)
    return result


# ── 判定结果 ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Unsupported:
    """一条没通过校验的句子。"""

    footnote: int
    sentence: str
    reason: str


@dataclass(frozen=True, slots=True)
class FaithfulnessReport:
    """校验结论。``checked`` 为 0 表示压根没走到校验这一步。"""

    checked: int
    supported: int
    unsupported: list[Unsupported]
    # 正文引用了但引用表里没有的编号——标注层面的错，不是忠实度问题。
    missing: list[int]
    skipped: bool
    reason: str = ""

    @property
    def pass_rate(self) -> float:
        """通过率。``checked == 0`` 时返回 0.0 而不是除零。"""
        if self.checked == 0:
            return 0.0
        return self.supported / self.checked


SKIPPED_REASON_NO_CITATIONS = "报告没有任何引用角标"
SKIPPED_REASON_NO_MODEL = "未配置模型客户端"


JUDGE_PROMPT = """你是一个研报引用审核员。给定报告里若干条带角标的句子，以及每条句子所引用的原文片段，逐条判断该句子的结论能否从原文中得到。

判定标准（**按重要性排序，务必严格执行**）：
1. 数字必须一致。原文说 2.5 倍、句子说 100 倍 → verdict 必须是 "unsupported"。
2. 结论方向必须一致。原文说「提升」、句子说「下降」→ 必须是 "unsupported"。
3. 主体、机构、型号、工艺等专有名词不得替换。
4. 允许改写、概括、跨句综合；只要结论能被原文支撑就算 supported。
5. 原文没有的信息，句子不得凭空补上。

对每个 id 只输出 verdict（"supported" 或 "unsupported"）与 reason（中文一句话）。

严格只输出 JSON，不要任何解释文字或 markdown 代码块。格式：
{"verdicts": [{"id": 1, "verdict": "supported", "reason": "..."}]}"""


def _build_user_prompt(
    sentences: dict[int, list[str]],
    sources: dict[int, str],
) -> str:
    """把待判条目拼成 prompt。

    逐条独立判定，不让句子之间互相参考——否则模型会看到「同一 chunk 的
    其他句子都被判 supported」，倾向于给剩下的也判 supported。
    """
    # 原文独立成块、句子按编号引用——同一 chunk 被多条句子引用时只贴一次。
    #
    # 早先的写法是「每条句子后面紧跟它的原文全文」，同一 chunk 引用 3 次
    # 就贴 3 遍。报告 20 条引用挤在 10 个 chunk 上时，重复占 prompt 的
    # 六成，而 FTS 的 chunk 上限 512 字符，重复量是线性叠加的。
    source_block = "\n\n".join(f"### 原文 {n}\n{text}" for n, text in sorted(sources.items()))

    sentence_blocks = []
    for n, variants in sorted(sentences.items()):
        for index, sentence in enumerate(variants):
            tag = n if index == 0 else f"{n}b"
            sentence_blocks.append(f"### 句子 {tag}（对应「原文 {n}」）\n{sentence}")

    return "\n\n".join(sentence_blocks) + "\n\n" + source_block


def _parse_verdicts(raw: str, expected_ids: set[str]) -> dict[str, tuple[bool, str]]:
    """解析模型输出。对不上的 id 直接丢弃——宁可少判几条，也不要编一个。

    宁可少判也不猜：模型编出来的 verdict 会让通过率变成假数字，而
    通过率是验收标准本身。
    """
    start = raw.find("{")
    if start == -1:
        return {}
    try:
        payload = json.loads(raw[start:])
    except json.JSONDecodeError:
        return {}

    out: dict[str, tuple[bool, str]] = {}
    for item in payload.get("verdicts", []):
        raw_id = str(item.get("id", "")).rstrip("b")
        if raw_id not in expected_ids:
            continue
        out[raw_id] = (item.get("verdict") == "supported", str(item.get("reason", "")))
    return out


async def verify_citations(
    client: AsyncAnthropic,
    report_text: str,
    sources: dict[int, str],
) -> FaithfulnessReport:
    """校验报告正文里的引用是否被原文支撑。

    ``sources`` 是 ``角标序号 -> 原文全文``。函数**不发起网络请求**，
    需要调用方保证 client 已配置——配置缺失时应当由调用方提前返回，
    本函数只处理 LLM 调用本身失败的情况（降级为无法校验）。
    """
    sentences = extract_cited_sentences(report_text)
    cited = sorted(sentences)
    if not cited:
        return FaithfulnessReport(
            checked=0,
            supported=0,
            unsupported=[],
            missing=[],
            skipped=True,
            reason=SKIPPED_REASON_NO_CITATIONS,
        )

    # 角标指向引用表里不存在的条目：无法核对，不计入分母。
    verifiable = [n for n in cited if n in sources]
    missing = sorted(set(cited) - set(verifiable))

    if not verifiable:
        return FaithfulnessReport(
            checked=0,
            supported=0,
            unsupported=[],
            missing=list(missing),
            skipped=True,
            reason="引用表里没有对应原文",
        )

    settings = get_settings()
    request: dict[str, Any] = {
        "model": settings.anthropic_complex_model,
        "max_tokens": 2048,
        "system": JUDGE_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": _build_user_prompt({n: sentences[n] for n in verifiable}, sources),
            }
        ],
    }
    try:
        async with client.messages.stream(**cast("Any", request)) as stream:
            final = await stream.get_final_message()
    except Exception:
        logger.exception("引用校验的 LLM 调用失败，降级为无法校验")
        return FaithfulnessReport(
            checked=0,
            supported=0,
            unsupported=[],
            missing=list(missing),
            skipped=True,
            reason="校验调用失败",
        )

    content = cast("list[dict[str, Any]]", final.model_dump(exclude_none=True)["content"])
    raw = "".join(b.get("text", "") for b in content if b.get("type") == "text")

    expected = set()
    for n in verifiable:
        expected.add(str(n))
        if len(sentences[n]) > 1:
            expected.add(f"{n}b")
    verdicts = _parse_verdicts(raw, expected)

    passed = 0
    unsupported: list[Unsupported] = []
    for n in verifiable:
        verdict = verdicts.get(str(n))
        if verdict is None:
            continue
        ok, reason = verdict
        if ok:
            passed += 1
        else:
            unsupported.append(Unsupported(footnote=n, sentence=sentences[n][0], reason=reason))

    return FaithfulnessReport(
        checked=len(verifiable),
        supported=passed,
        unsupported=unsupported,
        missing=list(missing),
        skipped=False,
    )


async def load_source_texts(
    db: AsyncSession,
    references: Sequence[Reference],
) -> dict[int, str]:
    """按引用列表取出 ``角标序号 -> 原文全文``。

    ``Reference.excerpt`` 只有 120 字（``citation._excerpt`` 的截断），
    拿它去校验等于用摘要证明摘要——判出来的通过率没有意义。要判定
    「这句话能不能从原文得到结论」，就得给校验器看完整原文。
    """
    wanted = {ref.chunk_id: ref.n for ref in references}
    if not wanted:
        return {}

    rows = await db.scalars(
        select(DocumentChunk.content).where(DocumentChunk.id.in_(wanted))
    )
    by_chunk_id = dict(zip(wanted, rows, strict=False))
    return {n: by_chunk_id[cid] for cid, n in wanted.items() if cid in by_chunk_id}
