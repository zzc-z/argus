"""Supervisor 与 Analyst 两个节点的实现。

## 为什么这两个节点以前是「时序占位」

``agent.py`` 的 ``Stage`` 枚举注释直说：只有 ``RESEARCHER`` 真正调 LLM，
其余是占位——为了让前端的 DAG 有完整的推进过程可演。于是 DAG 上：

- Supervisor 显示「正在拆解问题意图」，实际只做了一次本地拼 prompt（毫秒级）
- Analyst 显示「正在交叉核对证据」，实际**什么都没做**（0ms）

用户看到的是一个假的执行图。而且 Analyst 是 PRD
（``prd/multi-agent-design.md`` §1.3）里明确列出的角色：去重、分类、
实体抽取、冲突检测。

本模块给这两个节点各自补上一次真实的 LLM 调用。

## 为什么两次调用都要能降级

主循环已经跑完多轮检索、正文已经流给用户了，这两次调用是**增益**不是
必需品。它们失败时：

- 不抛异常（抛出去会让整轮研究崩掉，已烧的 token 白烧）
- 不阻断（没有拆解结果照样能检索，模型自己会决定搜什么）
- 记日志（静默失败的功能会长期完全不工作而没人发现）

降级后的表现是「节点照常走完，但产出为空」——与占位时代的观感一致，
但正常路径上是真的干了活。

## 为什么 Analyst 在检索之后、正文之前跑

它读的是**已经检索到的证据**。放在检索之前它没东西可核对；放在正文
之后它就成了「事后诸葛亮」，而正文是模型的最终产物，Analyst 的结论
来不及影响它。

所以顺序是：Supervisor 拆解 → Researcher 检索 → Analyst 核对证据 →
Writer 写正文 → Critic 校验引用。Analyst 的结论会进 Writer 的上下文，
让正文能引用核对过的结论。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import jiter

from app.services.agent_nodes import NodeTracker, Stage, _close
from app.services.citation import Reference
from app.services.stream import NodeEvent

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


# ── 配置 ──────────────────────────────────────────────────────

# 两个节点的独立模型。
#
# 留空则退到 default（Haiku）——这两个节点都是结构化的短输出，
# 用复杂模型是浪费。复杂模型的调用留给 Researcher 与 Writer。
#
# 注意：中转站返回的 model 实际身份不一定是配置字段标称的版本，
# 填的值必须是中转站能认的 alias。
ANALYST_MODEL = "claude-haiku-4-5"

# 单次调用的输出上限。
#
# 两个节点都只输出结构化的短结果（几个子任务 / 几条冲突），2048 是
# 绰绰有余的余量——设大了也不会多输出，反而给模型「可以写长」的错觉。
#
# 与主循环的 ``MAX_OUTPUT_TOKENS`` 是**两回事**：主循环那个管「一整轮
# 研究能写多少字」，这里管「一次结构化输出能写多少 JSON」。不要合并。
MAX_STAGE_TOKENS = 2048

# Analyst 一次最多核对多少条证据。
#
# 证据是累加的，一轮研究可能召回数十条。全喂进去会让 prompt 膨胀到
# 几万 token，而模型要判断的只是「这几条说的是不是同一件事、有没有
# 互相矛盾」——超过这个量之后收益递减。
#
# 取**最后**这些：最新的证据通常最相关，而最早的往往已被后续证据
# 取代或印证。
MAX_ANALYST_EVIDENCE = 12

# 引用证据时每条截多少字。
#
# 证据原文可能上千字，全部贴进去会让 prompt 膨胀到几万 token，而
# 模型要判断的只是「这几条说的是不是同一件事 / 有没有互相矛盾」，
# 截到 200 字足够看清主题与结论，冲突检测关心的正是结论层面的矛盾。
EVIDENCE_EXCERPT_CHARS = 200


# ── Supervisor：拆解意图 ──────────────────────────────────────

SUPERVISOR_PROMPT = """你是 Argus 研究的调度者。你的任务是把用户的研究问题拆解成检索子任务。

要求：
- 输出 2 到 5 个子任务，每个是一句「要查什么」的陈述句。
- 子任务之间不重叠，覆盖问题的关键面（时间、主体、数据、对比等，按问题性质取舍）。
- 不要写答案，只写要检索什么。
- 全部用中文。

严格只输出 JSON，不要任何解释文字或 markdown 代码块。格式：
{"subtasks": ["子任务1", "子任务2"]}"""


@dataclass(frozen=True, slots=True)
class Plan:
    """Supervisor 的拆解结果。"""

    subtasks: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    """这次调用烧掉的 token。

    必须记账——Supervisor 现在真的调了一次模型，不记的话用量统计会
    系统性偏低，用户按账估算成本会算错。
    """

    def as_prompt_line(self) -> str:
        """把拆解结果拼成给 Researcher 的一行提示。

        为空时返回空串——调用方据此判断「这次没有拆解结果」。
        """
        if not self.subtasks:
            return ""
        items = "\n".join(f"- {task}" for task in self.subtasks)
        return f"\n\n检索建议按以下子任务展开：\n{items}"


async def plan_subtasks(
    client: AsyncAnthropic,
    question: str,
    *,
    has_local: bool,
) -> Plan:
    """拆解用户问题，产出检索子任务。

    ``has_local`` 影响提示里的措辞：能查私有资料时明说它可用，
    否则模型会规划出依赖私有库的子任务，而那部分检索拿不到结果。

    **失败时返回空的 Plan**（不抛）。见模块 docstring 的「为什么两次调用
    都要能降级」。
    """
    prompt = f"用户的研究问题：\n{question}\n"
    if not has_local:
        prompt += "\n注意：本次无法检索用户的私有资料，只有公开来源可用。\n"

    call = await _call_structured(
        client,
        model=_model_for("supervisor"),
        system=SUPERVISOR_PROMPT,
        user_prompt=prompt,
    )
    if call is None:
        return Plan()

    raw = call.text
    try:
        payload = jiter.from_json(_json_part(raw).encode(), partial_mode=True)
    except ValueError:
        logger.warning("Supervisor 拆解结果不是合法 JSON，本次不采用")
        return Plan(input_tokens=call.input_tokens, output_tokens=call.output_tokens)
    if not isinstance(payload, dict):
        return Plan(input_tokens=call.input_tokens, output_tokens=call.output_tokens)

    subtasks = payload.get("subtasks")
    if not isinstance(subtasks, list):
        return Plan(input_tokens=call.input_tokens, output_tokens=call.output_tokens)
    # 只留字符串项：模型偶尔会混入数字或 null，直接拼进提示会渲染成
    # "None" 之类的东西喂回模型。
    cleaned = [
        str(item).strip() for item in subtasks if isinstance(item, str) and str(item).strip()
    ]
    if not cleaned:
        return Plan(input_tokens=call.input_tokens, output_tokens=call.output_tokens)

    logger.info("Supervisor 拆解出 %d 个子任务", len(cleaned))
    return Plan(
        subtasks=cleaned[:5],
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
    )


# ── Analyst：交叉核对证据 ─────────────────────────────────────

ANALYST_PROMPT = """你是 Argus 研究的分析员。你会拿到若干条检索到的证据片段，需要做交叉核对。

每条证据的标题会标明它的来源类型：「（公开来源）」的是网上搜索到的网页摘要，其余是用户上传资料里的切片。两类都要核对，而且**跨来源的口径差异往往正是最值得报告的矛盾**——私有资料说一个数、公开报道说另一个数，用户需要知道。

要求：
1. 找出**互相矛盾**的证据（同一件事被说成互相冲突的结论），逐条写出来。
2. 给出一段综合结论：这些证据合起来说明了什么，哪些方面证据不足。

没有矛盾是正常结果——空数组即可，不要为了凑数编造矛盾。

严格只输出 JSON，不要任何解释文字或 markdown 代码块。格式：
{"conflicts": ["矛盾描述"], "synthesis": "综合结论"}"""


@dataclass(frozen=True, slots=True)
class Evidence:
    """一条待核对的证据。"""

    n: int
    """证据编号 = 角标编号（与正文里的 ``[n]`` 对应）。

    **恒为正数**。公开来源（网上搜到的网页摘要）现在也走
    ``ReferenceTable``，占的是正经角标号——所以它与用户资料共用一个
    编号空间。

    两类证据靠**标题里的来源标注**区分（公开来源带「（公开来源）」），
    不靠编号的符号。（早先的约定是「负数 = 公开来源」，但那套编号
    从未实现——公开来源落成可引用来源后就有真角标号了。）
    """
    title: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class Analysis:
    """Analyst 的核对结果。"""

    conflicts: list[str] = field(default_factory=list)
    synthesis: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    """这次调用烧掉的 token。见 :attr:`Plan.input_tokens`。"""
    degraded: bool = False
    """这次核对**没有真正完成**。

    ## 为什么需要它

    模型调用失败时 ``_call_structured`` 返回 None，``analyze_evidence``
    返回一个全空的 ``Analysis``。而「调用失败」与「跑成功但确实没发现
    矛盾」两者的产出**完全一样**——调用方分不出来。

    后果是 DAG 上会写「核对 12 条证据，未发现矛盾」，而真相是
    **一次都没核对**。那比 0.0s 更坏：0.0s 至少暴露了可疑，
    「未发现矛盾」让用户以为系统核对过。

    所以降级要能被看见。
    """
    skipped_reason: str = ""
    """降级原因（degraded 为真时有值）。"""

    def as_prompt_block(self) -> str:
        """把核对结论拼成给 Writer 的一段提示。

        两类产出都值得带：**矛盾**是 Writer 必须正面处理的（不能把
        互相打架的证据并列成两个事实），**综合结论**给正文一个骨架。

        **降级时返回空串**——没有核对结果就没有可传的结论。传一句
        「证据之间存在矛盾」给 Writer，而实际上根本没核对过，那是在
        凭空制造一个结论。
        """
        if self.degraded:
            return ""
        parts: list[str] = []
        if self.conflicts:
            items = "\n".join(f"- {item}" for item in self.conflicts)
            parts.append(f"证据之间存在以下矛盾，正文里必须正面说明，不要并列成事实：\n{items}")
        if self.synthesis:
            parts.append(f"证据综合：{self.synthesis}")
        if not parts:
            return ""
        return "\n\n证据核对结果：\n" + "\n\n".join(parts)


async def analyze_evidence(
    client: AsyncAnthropic,
    evidence: list[Evidence],
) -> Analysis:
    """交叉核对检索到的证据。

    证据少于 2 条时直接返回空结果——一条证据没有「交叉」的对象，
    而硬凑一次调用只烧 token。

    **失败时返回空的 Analysis**（不抛）。见模块 docstring。
    """
    if len(evidence) < 2:
        # 一条证据没有「交叉」的对象，**根本没调模型**。
        # 标 degraded ——否则 note 会写「核对 1 条证据，未发现矛盾」。
        return Analysis(
            degraded=True,
            skipped_reason=f"证据只有 {len(evidence)} 条，不足以交叉核对",
        )

    blocks = []
    for item in evidence:
        excerpt = item.excerpt[:EVIDENCE_EXCERPT_CHARS]
        # **标题里标明来源类型**——模型据此分清「用户上传的资料」与
        # 「网上搜到的网页摘要」，跨来源的口径差异正是最常见的矛盾。
        #
        # 靠标题而不是编号的符号：公开来源现在也占正经角标号（恒正数），
        # 没有符号可区分。
        blocks.append(f"### 证据 [{item.n}] {item.title}\n{excerpt}")

    call = await _call_structured(
        client,
        model=_model_for("analyst"),
        system=ANALYST_PROMPT,
        user_prompt="\n\n".join(blocks),
    )
    if call is None:
        return Analysis(degraded=True, skipped_reason="模型调用失败")

    raw = call.text
    try:
        payload = jiter.from_json(_json_part(raw).encode(), partial_mode=True)
    except ValueError:
        logger.warning("Analyst 核对结果不是合法 JSON，本次不采用")
        return Analysis(
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            degraded=True,
            skipped_reason="模型返回的不是合法 JSON",
        )
    if not isinstance(payload, dict):
        return Analysis(
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            degraded=True,
            skipped_reason="模型返回的结构不是预期形状",
        )

    conflicts_raw = payload.get("conflicts")
    conflicts: list[str] = []
    if isinstance(conflicts_raw, list):
        conflicts = [
            str(item).strip()
            for item in conflicts_raw
            if isinstance(item, str) and str(item).strip()
        ]
    synthesis = str(payload.get("synthesis", "")).strip()

    logger.info("Analyst 核对出 %d 条矛盾", len(conflicts))
    return Analysis(
        conflicts=conflicts,
        synthesis=synthesis,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
    )


# ── 内部 ──────────────────────────────────────────────────────


def _json_part(raw: str) -> str:
    """从模型输出里截出 JSON 部分。

    ## 为什么要显式处理「没有 ``{``」

    早先的写法是 ``raw[raw.find("{"):]``——``find`` 返回 -1 时那等价于
    ``raw[-1:]``，即**最后一个字符**而不是空串。模型返回「这不是 JSON」
    时会拿一个字符去喂 jiter，靠抛异常才走到降级分支。

    两条路都碰巧能降级，但依赖的是「-1 切片索引」的隐式行为。显式写成
    「找不到就返回空串」，失败原因更清楚。
    """
    start = raw.find("{")
    return "" if start == -1 else raw[start:]


def _model_for(role: str) -> str:
    """取某个角色的模型。

    优先用配置里的按角色覆盖（``ANTHROPIC_ANALYST_MODEL`` 等），
    没配就用本模块的默认值。
    """
    from app.config import get_settings

    settings = get_settings()
    override = getattr(settings, f"anthropic_{role}_model", None)
    return override or _DEFAULT_MODELS[role]


_DEFAULT_MODELS = {
    "supervisor": "claude-haiku-4-5",
    "analyst": ANALYST_MODEL,
}


@dataclass(frozen=True, slots=True)
class _Call:
    """一次结构化调用的结果。"""

    text: str
    input_tokens: int
    output_tokens: int


async def _call_structured(
    client: AsyncAnthropic,
    *,
    model: str,
    system: str,
    user_prompt: str,
) -> _Call | None:
    """调一次模型，拿到原始文本输出与用量。

    返回 None 表示这次调用没成（已记日志）。**不抛异常**——调用方都是
    增益路径，抛出去会让整轮研究崩掉。

    ## 为什么降级用 warning 而不是 info

    应用没有配置 root logger（uvicorn 的默认配置把 root 留在 WARNING），
    所以 ``logger.info`` **根本不会输出**。降级是「功能没按预期工作」，
    必须能被看到——它用 warning，今天就能进日志。
    """
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_STAGE_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    try:
        final = await client.messages.create(**cast("Any", request))
    except Exception:
        logger.warning("%s 节点的模型调用失败，本次降级", model, exc_info=True)
        return None

    content = cast("list[dict[str, Any]]", final.model_dump(exclude_none=True)["content"])
    text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
    return _Call(
        text=text,
        input_tokens=final.usage.input_tokens,
        output_tokens=final.usage.output_tokens,
    )


@dataclass(slots=True)
class _AnalystOut:
    """Analyst 的回传通道。

    与 :class:`_FinalizeOut` 同模式：生成器只有一个 yield 通道，而这里
    要同时交回「节点事件」与「核对结论文本」。

    ## 为什么这里可以破 immutable 的例

    本模块整体是 immutable 风格（``Analysis`` / ``Plan`` 都是 frozen
    dataclass）。这个容器是**例外**，理由同 ``_FinalizeOut``：生成器
    只有一个 yield 通道，而这里要交回好几样东西——节点事件走 yield，
    核对结论与用量走容器。

    换成 frozen dataclass 的话，每次更新都要 ``replace()`` 再赋回去，
    而「交回通道」这个用途下那只是把同样的赋值换个写法。
    """

    text: str = ""
    ran: bool = False
    """Analyst 节点是否真的激活过。

    模型一次都没调工具时没有证据可核对，analyst 不会跑——那时
    ``_settle`` 要补一次空跑，让 DAG 走完 5 步。
    """
    input_tokens: int = 0
    output_tokens: int = 0
    """这次核对烧掉的 token。要记进用量账本——见
    :meth:`TurnLedger.record_stage_usage`。"""


def _checked_note(evidence: list[Any], total: int) -> str:
    """「核对了 N 条证据」这句话——总数不同时要说清。

    ## 为什么要在总数与核对数不同时说明

    证据是累加的，而一次最多喂 12 条（``MAX_ANALYST_EVIDENCE``）。所以
    「核对 12 条证据」在有 20 条证据时**不完整**——用户会以为全都核对过。

    说「核对最近 12 条（共 20 条）」才是实情。早先的 note 只写核对数，
    省略了总数（CR 实测，2026-11-08）。
    """
    checked = len(evidence)
    if total <= checked:
        return f"核对 {checked} 条证据"
    return f"核对最近 {checked} 条证据（共 {total} 条）"


async def _run_analyst(
    client: AsyncAnthropic,
    tracker: NodeTracker,
    collected_refs: list[Reference],
    seen: set[tuple[str, object]],
    out: _AnalystOut,
) -> AsyncIterator[NodeEvent]:
    """跑 Analyst 的证据核对。

    产出节点事件（researcher → analyst → researcher 的切换），
    核对结论通过 ``out.text`` 回传。

    ## 为什么只核对**新增**的证据

    证据是累加的。第 3 轮新增 2 条时，把前 5 轮的全部 20 条再核对一遍
    是重复烧钱（同样的证据、同样的矛盾、同样的结论）。

    跑的时候喂**全部**证据（上限 ``MAX_ANALYST_EVIDENCE`` 条）——
    矛盾检测需要上下文，只喂新增的那几条会漏掉跨轮的矛盾。超过上限时
    取**最后**那些：最新的证据通常最相关，而最早的往往已被后续取代。

    ## 触发条件： seen 集合

    ``seen`` 装着「已经核对过的证据的键」。有新键才跑。

    ## 为什么用「键集合」而不是「条数」

    同一个查询在多轮里被重复执行会返回同一批结果，累积列表里于是有
    大量**重复项**。若按「条数」判断，「有证据」永远成立 → 每轮都重跑
    核对，纯烧钱（实测一次研究里 analyst 跑了两次，第二次核对的是
    同一批一模一样的证据）。

    ## 为什么判据只有这一处

    「什么算新证据」只有一个定义：不在 ``seen`` 里的键。调用方不再另算
    一份计数——两处各算一份时可能不一致（一处按去重算、一处按原始算），
    不一致的那次就是一次纯浪费的模型调用。

    ## 为什么失败不抛

    见 ``services/stages.py`` 的模块说明：这是增益路径，失败只降级。
    """
    # 按 chunk_id 去重的引用。
    # _run_tools 每轮都会把**全量**引用表累积进 collected_refs（见那里
    # 的注释），不去重的话同一个 chunk 会出现多次，模型会看到
    # 「三条证据说的是同一件事」。
    unique: dict[int, Reference] = {}
    for ref in collected_refs:
        unique.setdefault(ref.chunk_id, ref)

    # **只喂最后 MAX_ANALYST_EVIDENCE 条**——全喂进去 prompt 会膨胀到
    # 几万 token，而收益递减。
    selected = list(unique.values())[-MAX_ANALYST_EVIDENCE:]

    # 新的键 = 不在 seen 里的，且**在这次要喂的范围里**。
    #
    # ## 为什么判据要限定在 selected 内
    #
    # 早先的写法是拿「全部 unique 的键」算差集，然后把**全部**键记进
    # ``seen``。但实际喂给模型的只有最后 12 条——前面那些**从未被核对过**，
    # ``seen`` 却说它们核对过了。
    #
    # 后果：第 1 轮 20 条证据 → seen 记 20 个键，模型只看到 12 条，
    # 前 8 条永远不会被核对；而 note 写「核对 12 条证据」，用户以为全对
    # 了。而这在真实路径上会触发（引用表封顶 10，两轮不同查询就超过 12）。
    new_keys = {("ref", ref.chunk_id) for ref in selected} - seen
    if not new_keys:
        # 没有新证据——没有新增的东西要核对。
        return
    # 只记**实际送进模型的那几条**的键。没送进模型的不能算「核对过」。
    seen.update({("ref", ref.chunk_id) for ref in selected})
    evidence = [Evidence(n=ref.n, title=ref.title, excerpt=ref.excerpt) for ref in selected]

    # 关掉 researcher，切到 analyst，跑完再切回 researcher。
    #
    # analyst 必须**占住节点**才能让它的耗时被正确计入——NodeTracker
    # 一次只允许一个 active，而 analyst 的那段耗时正是用户要看的。
    for event in _close(tracker):
        yield event
    yield tracker.activate(Stage.ANALYST)
    out.ran = True

    analysis = await analyze_evidence(client, evidence)
    out.text = analysis.as_prompt_block()
    out.input_tokens = analysis.input_tokens
    out.output_tokens = analysis.output_tokens
    # **摘要一定要有值**。
    #
    # 之前只在「有矛盾」或「有综合结论」时才 set_note——模型两者都没给
    # 时 note 是空串，DAG 上那个节点只有耗时、没有产出，用户看不出它
    # 到底干了什么（实测一次研究里 analyst 跑了 23 秒，note 是空的）。
    #
    # 「核对了 N 条证据」本身就是产出——它告诉用户这个节点确实查过。
    if analysis.degraded:
        # **降级时不能说「未发现矛盾」**。
        #
        # 那等于告诉用户「核对过、没问题」，而真相是**一次都没核对**。
        # 本次改动的全部意义是「让 DAG 显示真实发生的事」——降级路径上
        # 说假话比显示 0.0s 更坏。
        tracker.set_note(
            Stage.ANALYST,
            f"核对未完成（{analysis.skipped_reason or '未知原因'}）",
        )
    elif analysis.conflicts:
        tracker.set_note(
            Stage.ANALYST,
            f"{_checked_note(evidence, len(unique))}，发现 {len(analysis.conflicts)} 处矛盾",
        )
    else:
        tracker.set_note(Stage.ANALYST, f"{_checked_note(evidence, len(unique))}，未发现矛盾")

    for event in _close(tracker):
        yield event
    yield tracker.activate(Stage.RESEARCHER)
