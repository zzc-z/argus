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

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import jiter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk
from app.services.citation import Reference, extract_cited_sentences
from app.services.llm import model_for

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


# ── 判定结果 ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Unsupported:
    """一条没通过校验的句子。

    ``variant`` 是同一脚注内的**变体序号**（从 0 起）：脚注 n 被多个句子
    引用时，第 k 句就是变体 k。它是 ``(footnote, variant)`` 这个二元 key
    的后半段——前端用它做 React key，因为一个脚注现在可能产出多条 Unsupported。
    """

    footnote: int
    variant: int
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


class JudgeTruncated(RuntimeError):
    """judge 的输出被 max_tokens 截断。

    这是**配置问题**，不是「模型判不了」。两者必须分开：

    - 截断 → 输出不完整 → JSON 解析必然失败 → 整批判定丢失
    - 判不了 → 输出完整但内容不足 → 可以只丢没判出的那几条

    早先没有这个区分，截断会落进通用的 except 分支，被标成「无法校验」，
    排查方向会完全跑偏（以为是模型能力不足，实际是 max_tokens 不够）。
    """


JUDGE_PROMPT = """你是一个研报引用审核员。给定报告里若干条带角标的句子，以及每条句子所引用的原文片段，逐条判断该句子的结论能否从原文中得到。

判定标准（**按重要性排序，务必严格执行**）：
1. 数字必须一致。原文说 2.5 倍、句子说 100 倍 → verdict 必须是 "unsupported"。
2. 结论方向必须一致。原文说「提升」、句子说「下降」→ 必须是 "unsupported"。
3. 主体、机构、型号、工艺等专有名词不得替换。
4. 允许改写、概括、跨句综合；只要结论能被原文支撑就算 supported。
5. 原文没有的信息，句子不得凭空补上。

逐条独立判定：每条句子只看它自己对应的那段原文，不要因为其他句子的判定结果而调整你的判断。

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
            # 变体 tag 必须**每个都唯一**。早先所有非首变体都叫 f"{n}b"，
            # 于是同一脚注的**第 2 句与第 3 句拿到同一个 tag**——模型对这两句
            # 只能给一个判定，第 3 句的判定要么丢失、要么与第 2 句碰撞。
            #
            # 规则：**后缀数字就是变体序号**。
            #   variant 0 → "n"；variant 1 → "nb"；variant 2 → "nb2"；…
            # 解析侧见 :func:`_verdict_key`（"b2" → variant 2），两边必须一致。
            tag = n if index == 0 else (f"{n}b" if index == 1 else f"{n}b{index}")
            sentence_blocks.append(f"### 句子 {tag}（对应「原文 {n}」）\n{sentence}")

    return "\n\n".join(sentence_blocks) + "\n\n" + source_block


# verdict 词汇白名单。**未知值归为「无法判定」而不是 unsupported**——
# 误伤方向是质疑用户写的结论，那比漏判糟得多。
_SUPPORTED_WORDS = {"supported", "support", "ok", "pass"}
_UNSUPPORTED_WORDS = {"unsupported", "not_supported", "fail", "contradicted"}


def _parse_verdicts(
    raw: str, expected_ids: set[tuple[int, int]]
) -> dict[tuple[int, int], tuple[bool, str]]:
    """解析模型输出。对不上的 id 直接丢弃——宁可少判几条，也不要编一个。

    宁可少判也不猜：模型编出来的 verdict 会让通过率变成假数字，而
    通过率是验收标准本身。

    ## key 是 ``(脚注号, 变体序号)`` 而不是字符串

    同一脚注被多个句子引用时，``_build_user_prompt`` 给它们编号
    ``"1"`` / ``"1b"``（见那里）。早先这里用 ``rstrip("b")`` 归一化成
    字符串 key，于是 **``"1b"`` 被压成 ``"1"``**——两条判定互相覆盖：
    后写的赢，前写的被丢弃。

    实测两��方向都会出错（同一脚注被两句引用，句A 有据、句B 数字错 40 倍）：

    - ``1=supported, 1b=unsupported`` → ``1`` 变成 unsupported，
      **有据的句子被误报成无据**（理由还是另一句的）
    - ``1b=unsupported, 1=supported`` → unsupported **被完全丢弃**，
      编造的引用被当成有据通过

    而且消费端只查 ``str(n)``（脚注号），``"1b"`` 这个键**永远取不到**。

    改成二元组后，两条判定各归各位，消费端也能逐变体取到。
    """
    start = raw.find("{")
    if start == -1:
        return {}
    try:
        # 用 jiter 而不是 json.loads：模型爱给 ```json 围栏，`json.loads`
        # 遇到任何尾随文本就抛——那正是最常见的输出形式，抛了等于校验
        # 在最该生效的场景里静默失效。jiter 容忍尾随内容且快得多。
        payload = jiter.from_json(raw[start:].encode(), partial_mode=True)
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}

    out: dict[tuple[int, int], tuple[bool, str]] = {}
    for item in payload.get("verdicts", []):
        # 每一层都要类型校验——模型返回 {"verdicts": "supported"} 时，
        # 迭代出的是字符 's'，直接 .get() 会 AttributeError 逃出降级路径。
        # 实测三种返回都会炸：字符串 / 数字数组 / 字典（迭代出 key）。
        if not isinstance(item, dict):
            continue
        key = _verdict_key(item.get("id"))
        if key is None or key not in expected_ids:
            logger.debug("丢弃无法对应的 verdict id: %r", item.get("id"))
            continue
        # 严格相等会把 "Supported" / "SUPPORTED" / "部分支撑" 全判成
        # unsupported——**误伤方向是质疑用户**，比漏判更糟。归一化后再判，
        # 认不出来的单独归为「无法判定」而不是 unsupported。
        verdict = str(item.get("verdict", "")).strip().lower()
        reason = str(item.get("reason", ""))
        if verdict in _SUPPORTED_WORDS:
            out[key] = (True, reason)
        elif verdict in _UNSUPPORTED_WORDS:
            out[key] = (False, reason)
        else:
            logger.debug("verdict 词汇无法归类: %r（不计入通过也不计入失败）", verdict)
    return out


def _verdict_key(raw_id: object) -> tuple[int, int] | None:
    """把模型回的 id 拆成 ``(脚注号, 变体序号)``。

    形如 ``"1"`` → ``(1, 0)``、``"1b"`` → ``(1, 1)``、``"1b2"`` → ``(1, 2)``。
    规则：**后缀数字就是变体序号**，与 ``_build_user_prompt`` 的 tag 规则
    一一对应——两边必须一致，否则第 3 个变体永远判不出来。

    **不能靠 ``rstrip("b")``**——它把 ``"1b"`` 压成 ``"1"``，
    让同一脚注的两个变体拿到同一个 key（见 :func:`_parse_verdicts` 的说明）。

    认不出来的形态返回 ``None``，由调用方丢弃——宁可少判，不猜。
    """
    text = str(raw_id).strip()
    # 形如 "1" / "1b" / "1b2" / "1b3" —— 后缀是 "b" 可选跟一个数字。
    # 注意 ``(b*)`` 不够：它只吃连续的 b，"1b2" 里的 "2" 匹配不上，
    # 整个 id 会被当成无法对应而丢弃（第 3 个变体就永远判不出来）。
    m = re.fullmatch(r"(\d+)(?:b(\d*))?", text)
    if m is None:
        return None
    suffix_num = m.group(2)
    if suffix_num is None:
        variant = 0
    elif suffix_num == "":
        variant = 1
    else:
        # tag 规则是「第 k 句 → nb(k-1)」，所以 "b2" 对应第 3 句 = variant 2。
        variant = int(suffix_num)
    return int(m.group(1)), variant


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

    # max_tokens 必须**按待判条数给**。硬编码 2048 时，20 条引用各带一句
    # 中文 reason 会被截断——JSON 不完整 → 解析抛异常 → 整批判定被丢弃，
    # 用户看到「无法校验」。而截断是**配置问题**，不是模型判不了，
    # 两者混在一起会让排查方向完全跑偏。
    #
    # 每条判定含 id + verdict + 中文 reason，约 150 tokens；留 2 倍余量。
    expected_count = sum(len(sentences[n]) for n in verifiable)
    max_tokens = max(2048, expected_count * 300)
    request: dict[str, Any] = {
        # 走**统一路由**（``llm.model_for``），不自己读配置。
        #
        # 早先这里直接读 ``anthropic_critic_model or anthropic_complex_model``，
        # 绕过了 stages 的路由——那意味着有人设了
        # ``ANTHROPIC_WRITER_MODEL=claude-sonnet-5`` 时，judge 与 writer
        # 会静默变成同模型，自偏好偏差让通过率系统性偏高，而代码层面
        # 没有任何提示。现在统一路由 + 启动即断言（见 llm.assert_distinct_...）。
        "model": model_for("critic"),
        "max_tokens": max_tokens,
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
    except JudgeTruncated:
        raise
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

    # **截断要单独识别**。stop_reason == "max_tokens" 时 JSON 必然不完整，
    # 解析会抛异常并落进上面的通用 except —— 那样用户看到的是「无法校验」，
    # 而真因是 max_tokens 不够。两者都叫「无法校验」，排查方向完全不同：
    # 前者要调配置，后者要换模型或改判定方式。
    if final.stop_reason == "max_tokens":
        raise JudgeTruncated(
            f"判定输出被截断（max_tokens={max_tokens} 不足以容纳 {expected_count} 条判定）"
        )

    content = cast("list[dict[str, Any]]", final.model_dump(exclude_none=True)["content"])
    raw = "".join(b.get("text", "") for b in content if b.get("type") == "text")

    # expected 是「(脚注号, 变体序号)」的集合。同一脚注被多个句子引用时，
    # 每个句子都是一条独立待判项——这是「逐条判定」的前提。
    expected = set()
    for n in verifiable:
        for variant_index in range(len(sentences[n])):
            expected.add((n, variant_index))
    verdicts = _parse_verdicts(raw, expected)

    # **解析失败与「模型没给判定」要分开**。两者都表现为「没拿到 verdict」，
    # 但真因完全不同：
    #
    # - 解析失败 → 模型返回的不是合法 JSON → **输出格式坏了**，可诊断
    # - 没给判定 → 模型返回了合法 JSON 但没 verdict → **能力/内容问题**
    #
    # 混成一句话「模型未返回任何判定」会让排查方向跑偏：前者要改
    # prompt 或换模型，后者可能是 max_tokens 不够或判定本身做不了。
    if not verdicts and raw.strip():
        stripped = raw.strip()
        looks_like_json = stripped.startswith("{") or stripped.startswith("[")
        if not looks_like_json:
            logger.warning("judge 输出不是合法 JSON，无法解析。原文前 200 字：%r", stripped[:200])
            return FaithfulnessReport(
                checked=0,
                supported=0,
                unsupported=[],
                missing=list(missing),
                skipped=True,
                reason="判定输出无法解析（不是合法 JSON）",
            )

    passed = 0
    unsupported: list[Unsupported] = []
    unjudged: list[tuple[int, int]] = []
    for n in verifiable:
        for variant_index, sentence in enumerate(sentences[n]):
            verdict = verdicts.get((n, variant_index))
            if verdict is None:
                # 模型没回这条。**必须从分母里剔除**——留在 checked 里会让
                # 「通过 3 条、0 条未支撑」这种自相矛盾的数字出现，而且分母
                # 永远不减、通过率系统性偏低。
                unjudged.append((n, variant_index))
                continue
            ok, reason = verdict
            if ok:
                passed += 1
            else:
                # **报告的必须是实际被判定的那一句**。早先这里恒用
                # `sentences[n][0]`，同一脚注的第二句即便判定为无据，
                # 报出来的也是第一句——用户按提示去原文找不到问题。
                unsupported.append(
                    Unsupported(footnote=n, variant=variant_index, sentence=sentence, reason=reason)
                )

    if unjudged and not passed and not unsupported:
        # 全都没判出来——这是「无法校验」，不是「全部无据」。
        return FaithfulnessReport(
            checked=0,
            supported=0,
            unsupported=[],
            missing=list(missing),
            skipped=True,
            reason="模型未返回任何判定",
        )

    return FaithfulnessReport(
        checked=len(expected) - len(unjudged),
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

    # **必须 select(id, content)** 再按 id 建字典。不能只 select(content)
    # 然后 zip——SQL 没有 ORDER BY，返回顺序与 wanted 的 key 顺序没有任何
    # 关系，那样配出来的是「角标 1 拿到 5 号 chunk 的正文」，整份校验
    # 结果方向相反且无任何报错（2026-10-16 CR 实测复现）。
    rows = (
        await db.execute(
            select(DocumentChunk.id, DocumentChunk.content).where(DocumentChunk.id.in_(wanted))
        )
    ).all()
    by_chunk_id = dict(rows)
    return {n: by_chunk_id[cid] for cid, n in wanted.items() if cid in by_chunk_id}
