"""agent 可调用的工具：schema 定义 + 执行分发。

工具是模型与外部世界之间唯一的接口。模型不直接发 HTTP，只能说
「我要调 tavily_search，参数是 xxx」，由本模块替它执行并把结果送回。

两条硬约束贯穿全文件：

1. **执行失败不抛异常，返回 ok=False**。tool_result 是协议的一部分，
   把错误文本喂回模型让它自己纠正（换关键词、改参数、或放弃用工具），
   比中断整个 SSE 流好得多。模型看到 is_error=True 会知道这次调用没成。
2. **结果必须裁剪**。tool_result 原样进下一轮上下文，Tavily 原始响应
   动辄上万 token，不裁剪的话几轮就能把上下文撑爆、单次请求费用失控。
"""

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.services import citation
from app.services.citation import Reference, ReferenceTable
from app.services.embedder import EmbeddingError
from app.services.errors import Classified, classify_embedding_error, classify_tool_error
from app.services.errors_base import RetrievalNoMatchError
from app.services.llm import LLMNotConfiguredError, get_tavily_client
from app.services.urls import canonicalize_url
from app.services.web_sources import (
    ToolEvidence,
    register_web_sources,
    render_web_evidence,
    web_citation_rules,
)

# ── 常量 ──────────────────────────────────────────────────────

# 单次搜索取几条结果。5 条够模型判断趋势，再多只是往上下文里塞噪声。
SEARCH_MAX_RESULTS = 5

# 单条搜索结果的正文截断长度。Tavily 的 content 字段可能包含整篇网页，
# 一条就够撑爆一轮上下文。
RESULT_CONTENT_CHARS = 800

# 全部搜索结果的总量上限。超了追加截断标记——静默截断会让模型误以为
# 搜索只有这几条，编出「没有更多资料」的结论。
RESULT_TOTAL_CHARS = 4000

# 单条搜索结果作为「待核对证据」时的摘要长度。
#
# 比 ``RESULT_CONTENT_CHARS`` 短：核对要判断的是「这条说的是不是同一
# 件事、有没有互相矛盾」，那个判断只需要看到结论层面的内容。
EVIDENCE_EXCERPT_CHARS = 200

# 本地检索取几条切片。与 citation.MAX_REFERENCES 对齐：引用表 10 条封顶，
# 检索取更多只会让超出的部分被**静默丢弃**——第一次调用就把表灌满的话，
# 第二次调用注册的全是新切片、整段被丢，证据块是空字符串（模型只拿到
# 「编号 [1] 到 [10]」却一条证据都没有）。
LOCAL_SEARCH_TOP_K = 10

# Tavily SDK 自带的超时（只管 HTTP 连接阶段）。
TAVILY_TIMEOUT_SECONDS = 10.0

# 外层兜底。SDK 的 timeout 管不到 DNS 解析慢、建连挂起这类情况。
TAVILY_HARD_TIMEOUT_SECONDS = 15.0

logger = logging.getLogger(__name__)


# ── 数据类型 ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """一个工具的声明：模型看得见的名字/描述/入参 schema。

    刻意与执行逻辑分开——模型只需要知道「有这么个工具、参数长这样」，
    至于 Python 怎么实现，与它无关。
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """工具执行所需的会话级依赖。

    为什么要单独传而不是让工具自己去 ``get_session()``：那是 FastAPI 的
    依赖注入，SSE 端点里拿不到——生成器跑的时候请求已经结束，依赖的生命周期
    早就过了。连接必须由 agent 循环从网关层接进来传下去。

    ``user_id`` 不能省：本地检索必须按用户收窄，这是私域隔离的唯一防线。
    少了它，``local_search`` 会把所有人的资料混在一起返回。

    ``citations`` 由 agent 循环创建并跨整轮循环持有——每次 ``local_search``
    调用都必须共用同一个，否则正文里的 ``[1]`` 在不同段落指向不同切片。
    """

    db: AsyncSession
    user_id: int
    citations: ReferenceTable
    vec_engine: AsyncEngine | None = None
    """向量引擎。**只有 ``local_search`` 需要它**。

    可选的原因：联网搜索结果落成可引用来源只需要 ``db``（见
    ``app/services/web_sources.py``）。而把 ``vec_engine`` 设成必填的话，
    「没有向量引擎」会连累「联网来源不占角标号」——那两件事没关系。

    ``local_search`` 在缺它时自己报「没有检索上下文」而不是崩掉。
    """
    session_maker: async_sessionmaker[AsyncSession] | None = None
    """后台任务用的 session 工厂。

    ## 为什么公开来源要**另开一个 session**

    研究流跑 30-60 秒，而 SQLite 是默认数据库（写锁是库级的）。如果
    公开来源用主 session 落库（``flush`` 但不 ``commit``），那个写锁
    会**持有整轮研究**——期间：

    - 别的研究一 ``flush`` 就 ``database is locked``（默认超时 5 秒）
    - 用户的资料上传同样被阻塞

    实测（2026-11-08）：两个并发研究，第二个 5.3 秒后报
    ``OperationalError: database is locked``，而且它的 session 被毒化
    （SAVEPOINT 回滚救不了——那不是约束失败）。

    所以公开来源用**独立的短事务**：写完立刻 ``commit``，锁立刻释放。
    """
    seen_web_urls: set[str] = field(default_factory=set)
    """已登记过的公开来源 URL（**归一化后**）。

    跨轮累积——同一个 URL 在多轮搜索里会被搜到多次（实测 2026-11-08：
    SEC 的 nvda-20250126 在两轮里各出现一次）。不去重的话同一篇资料
    占两个角标号，而模型会把它们当成「两个独立来源互相印证」。

    这是个**可变**的 set（虽然 dataclass 本身 frozen）——它要在多轮之间
    累积，而 ``ToolContext`` 是每次请求新建、跨轮持有的。
    """


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """一次工具执行的结果。

    ``content`` 是要喂回模型的文本（已裁剪）；``preview`` 是给前端看的
    简短摘要，几十字以内——完整内容已经在 SSE 的 delta 里流过了，
    检查器面板只需要一行说明。

    ``references`` 是本次调用产出的引用表（本地检索才有）。模型看不到这个
    字段，但 agent 循环会把它透传给前端的 ``reference`` 事件。

    ``error_code`` 是这一档的错误码（空串 = 没有）。「本地资料与问题无关」
    这一档要挂码：用户必须知道自己的私有资料被跳过了，否则他以为报告里
    没有引用是因为资料库里确实没有。模型看不到这个字段。

    ``evidence`` 是本次调用拿到的**搜索结果**（联网搜索专用）。

    它的用途是**中转**：``_format_search_results`` 把 Tavily 的原始结果
    转成这个形状，``_run_tavily_search`` 再把它们落成正经引用
    （``Source`` + ``DocumentChunk`` + 角标号）。

    落成引用之后它们就在 ``references`` 里了——``evidence`` 只是那份
    中转数据，不会再单独流向模型或 Analyst（那会造成同一条证据被算两遍：
    一遍带角标号、一遍不带）。
    """

    ok: bool
    content: str
    preview: str = ""
    references: tuple[Reference, ...] = ()
    error_code: str = ""
    evidence: tuple[ToolEvidence, ...] = ()
    """这次调用拿到的**搜索结果**（联网搜索专用）。

    它的用途是**中转**：``_format_search_results`` 把 Tavily 的原始结果
    转成这个形状，``_run_tavily_search`` 再把它们落成正经引用
    （``Source`` + ``DocumentChunk`` + 角标号）。

    落成引用之后它们就在 ``references`` 里了——``evidence`` 只是那份
    中转数据，不会再单独流向模型或 Analyst（那会造成同一条证据被算两遍：
    一遍带角标号、一遍不带）。
    """


# ── 工具 schema ───────────────────────────────────────────────

TAVILY_SEARCH_SPEC = ToolSpec(
    name="tavily_search",
    description=(
        "联网搜索。用于查找当前事件的最新信息、官方数据、技术基准等。"
        "查询越具体越好——带上公司名、时间范围、技术型号。"
        "返回的每条结果包含标题、URL、摘要和相关度。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {
                "type": "integer",
                "description": f"返回条数，1-{SEARCH_MAX_RESULTS}，默认 3",
                "minimum": 1,
                "maximum": SEARCH_MAX_RESULTS,
            },
        },
        "required": ["query"],
    },
)

DEDUP_SPEC = ToolSpec(
    name="dedup",
    description=(
        "对已有的搜索结果按 URL 去重。同一篇文章的不同分享链接（带 utm 参数、"
        "带锚点、大小写不同）会被识别为同一条并合并，保留第一次出现的那条。"
        "多次搜索后调用它，避免把重复资料当成多份独立证据。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "待去重的 URL 列表",
            },
        },
        "required": ["urls"],
    },
)

LOCAL_SEARCH_SPEC = ToolSpec(
    name="local_search",
    description=(
        "在用户上传的私有资料里检索（PDF / 网页 / Markdown / 纯文本）。"
        "问及用户自己的文档、特定公司或产品的具体数据、"
        "或联网搜不到的内容时用它。\n"
        "返回的每条素材都已编号，形如 [1] 标题（第 3 页，第 2 段），"
        "引用这些内容时必须标上对应编号。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索关键词。用用户问题里的核心名词，"
                "不要把整句问题塞进来——切面太宽会召回不相关的段落",
            },
        },
        "required": ["query"],
    },
)

ALL_TOOLS: tuple[ToolSpec, ...] = (TAVILY_SEARCH_SPEC, LOCAL_SEARCH_SPEC, DEDUP_SPEC)

# 工具名序列，:func:`available_tools` 按它决定输出顺序。
ALL_TOOLS_NAMES: tuple[str, ...] = tuple(spec.name for spec in ALL_TOOLS)


def available_tools(*, has_local: bool = True) -> tuple[ToolSpec, ...]:
    """按外部依赖是否就绪过滤工具列表。

    Tavily key 没配时摘掉 tavily_search，并让调用方在 system prompt 里
    说明「当前没有联网搜索」。这比让它撞满 MAX_TURNS 次同样的错误优雅得多——
    模型看不到这个工具，就不会调它。

    ``has_local`` 为 False 时摘掉 local_search：没有数据库连接时它必然
    执行不了，而模型看不到就不会浪费一轮去调它。
    """
    names = set(ALL_TOOLS_NAMES)
    try:
        get_tavily_client()
    except LLMNotConfiguredError:
        names.discard(TAVILY_SEARCH_SPEC.name)
    if not has_local:
        names.discard(LOCAL_SEARCH_SPEC.name)
    by_name = {
        TAVILY_SEARCH_SPEC.name: TAVILY_SEARCH_SPEC,
        LOCAL_SEARCH_SPEC.name: LOCAL_SEARCH_SPEC,
        DEDUP_SPEC.name: DEDUP_SPEC,
    }
    # 按 ALL_TOOLS 的声明顺序返回，不按 set 的迭代顺序——set 顺序随
    # PYTHONHASHSEED 变，同一份配置两次启动给出的 tools 数组顺序不同，
    # 会让 prompt 缓存失效。
    return tuple(by_name[n] for n in ALL_TOOLS_NAMES if n in names)


def tool_schemas(tools: tuple[ToolSpec, ...]) -> list[dict[str, Any]]:
    """转成 Anthropic messages API 的 tools 参数格式。"""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
        }
        for spec in tools
    ]


# ── 执行分发 ──────────────────────────────────────────────────


async def execute_tool(
    name: str,
    tool_input: dict[str, Any],
    context: ToolContext | None = None,
) -> ToolOutcome:
    """按名字执行工具，任何失败都转成 ok=False 的结果。

    不抛异常是刻意的：见模块 docstring 的「两条硬约束」第 1 条。
    未知工具名也要返回错误而不是 KeyError——模型偶尔会幻觉出不存在的
    工具名，让它看到明确的「没有这个工具」比崩掉整个流有用。

    ``context`` 只有 ``local_search`` 需要。缺它时返回错误而不是崩溃——
    见 :func:`_run_local_search` 的注释。
    """
    try:
        if name == TAVILY_SEARCH_SPEC.name:
            return await _run_tavily_search(tool_input, context)
        if name == LOCAL_SEARCH_SPEC.name:
            if context is None:
                return ToolOutcome(
                    ok=False,
                    content="local_search 需要检索上下文，本次调用无法执行。",
                    preview="缺少上下文",
                )
            return await _run_local_search(context, tool_input)
        if name == DEDUP_SPEC.name:
            return _run_dedup(tool_input)
    except LLMNotConfiguredError as exc:
        # 走分类器而不是就地拼文案：code 与其它失败路径统一（前端按
        # code 归类），文案也带上具体缺哪个配置项。
        classified = _classify_tool_failure(name, exc)
        return ToolOutcome(
            ok=False,
            content=classified.message,
            preview=classified.preview,
        )
    except TimeoutError:
        logger.warning("工具 %s 执行超时，重试可能仍失败但值得一试", name)
        return ToolOutcome(
            ok=False,
            content=f"工具 {name} 执行超时（{TAVILY_HARD_TIMEOUT_SECONDS:.0f}秒）。请调整参数后重试。",
            preview="执行超时",
        )
    except Exception as exc:
        # 宽兜底，但**不把异常文本喂给模型**。原始异常（AttributeError、
        # TypeError 这类）会进下一轮上下文，模型很可能在正文里原样复述
        # 「Invalid IPv6 URL」这类内部细节；更糟的是它会当成参数问题
        # 去改 query、重试到耗尽轮数上限，而真正的原因是我们自己的 bug。
        #
        # 分档：网络类异常值得重试，其余一律让模型直接用已有信息作答。
        # 真实原因只进日志。
        #
        # 但「分档」不能只有「网络类 / 非网络类」两档——嵌入服务欠费
        # 属于 BadRequestError（不是网络类），报成「工具内部错误」会让
        # 用户以为是自己传的资料有问题，而真因是账户欠费。分类见
        # ``errors.classify_tool_error``。
        classified = _classify_tool_failure(name, exc)
        logger.warning(
            "工具 %s 执行失败（%s，可重试=%s）",
            name,
            classified.code,
            classified.retryable,
            exc_info=exc,
        )
        return ToolOutcome(
            ok=False,
            content=classified.message,
            preview=classified.preview,
        )

    return ToolOutcome(
        ok=False,
        content=f"不存在名为 {name} 的工具。可用工具：{', '.join(s.name for s in ALL_TOOLS)}。",
        preview="未知工具",
    )


def _classify_tool_failure(name: str, exc: BaseException) -> Classified:
    """把工具异常分类成一条具体的错误。

    ``local_search`` 走嵌入服务，失败原因与 Tavily 完全不同——嵌入服务
    欠费要报「欠费」，不能报成「外部服务不可用」。所以按工具名分派到
    对应的分类器。

    参数顺序反了（把异常当工具名传）要当场报错：照着错位的参数继续走，
    只会得到一个看不懂的 AttributeError。
    """
    if not isinstance(exc, BaseException):
        raise TypeError(f"exc 必须是异常，收到 {type(exc).__name__}")
    if name == LOCAL_SEARCH_SPEC.name and isinstance(exc, EmbeddingError):
        return classify_embedding_error(exc)
    return classify_tool_error(exc, name)


# ── tavily_search 实现 ────────────────────────────────────────


async def _run_tavily_search(
    tool_input: dict[str, Any],
    context: ToolContext | None = None,
) -> ToolOutcome:
    """调 Tavily 搜索并压成模型能读的紧凑文本。

    双重超时：SDK 的 ``TAVILY_TIMEOUT_SECONDS`` 只管 HTTP 连接，外层
    ``asyncio.wait_for`` 兜住 DNS 解析慢、建连挂起这类边缘情况。
    """
    client = get_tavily_client()

    query = str(tool_input.get("query", "")).strip()
    if not query:
        return ToolOutcome(ok=False, content="搜索关键词不能为空。", preview="参数错误")

    raw_max = tool_input.get("max_results", 3)
    try:
        max_results = max(1, min(int(raw_max), SEARCH_MAX_RESULTS))
    except (TypeError, ValueError):
        max_results = 3

    raw = await asyncio.wait_for(
        _search(client, query, max_results),
        timeout=TAVILY_HARD_TIMEOUT_SECONDS,
    )
    outcome = _format_search_results(cast(dict[str, Any], raw), max_results)

    if context is None or not outcome.evidence:
        return outcome

    # 落成可引用来源。失败不阻断——搜索结果本身仍是有效证据。
    try:
        entries = await register_web_sources(
            context.db,
            context.user_id,
            context.citations,
            outcome.evidence,
            seen_urls=context.seen_web_urls,
            # **必须传**——公开来源要用独立 session 落库（见
            # ``ToolContext.session_maker`` 的说明）。漏传的话生产会走
            # SAVEPOINT 路径，而那条路径在 pysqlite 下
            # 「RELEASE SAVEPOINT == COMMIT」，会**偷偷提交主 session 的
            # 事务**，破坏主循环的事务边界。
            session_maker=context.session_maker,
        )
        references = [reference for _n, _item, reference in entries]
    except Exception:
        logger.warning("公开来源登记失败，本次不产生角标", exc_info=True)
        return outcome

    if not references:
        return outcome

    # **重新渲染成带角标号的证据块**。
    #
    # 原先 Tavily 的结果用它自己的 ``[1] [2]`` 序号，与角标编号是两套
    # 编号——模型在正文里写 ``[3]`` 时可能指 Tavily 的第 3 条，而引用表
    # 里的 3 号是用户资料的某个切片。角标指错，且没有任何报错。
    # **用实际登记成功的那些条目渲染**——编号直接取引用表里的值。
    #
    # 早先渲染的是全量 ``outcome.evidence``、编号从 ``references[0].n``
    # 起算：登记时跳过的条目（去重命中、摘要空白、表满）造成整体错位，
    # 模型写 ``[3]`` 而引用表里 3 号是另一条——角标指错。
    blocks = render_web_evidence(entries)
    rules = web_citation_rules(entries[0][0], entries[-1][0])
    # **表满了要告诉模型**。
    #
    # 引用表封顶 ``MAX_REFERENCES``（10）。超出的搜索结果没有编号——
    # 而模型看到的证据块里没有它们，它却已经付了这次调用的钱。不说
    # 的话，模型会以为「就这些资料」，在结论里下「没有更多数据」的判断。
    saturated = citation.render_saturated_notice(context.citations.dropped)
    content = "\n\n".join(part for part in (blocks, rules, saturated) if part)
    # **发全量引用表**，不是本次新增的那些。
    #
    # 前端是**整体替换**（``h.setCitations(event.references)``）。发增量
    # 的话，前一次 local_search 的引用会被这次的结果覆盖掉——正文里
    # ``[1]``（本地资料）变成裸字符，点不动。
    #
    # 实测：一轮里先 local_search 再 tavily_search，前端最终只剩
    # tavily 那一条，1、2 号全没了。而这正是本次改动鼓励的组合。
    return replace(
        outcome,
        content=content,
        references=tuple(context.citations.all),
    )


async def _search(client: Any, query: str, max_results: int) -> Any:
    """真正发请求的一层——单独拆出来是为了让 wait_for 能整体包住。"""
    return await client.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
        include_answer=False,
        include_raw_content=False,
        timeout=TAVILY_TIMEOUT_SECONDS,
    )


def _format_search_results(data: dict[str, Any], requested: int) -> ToolOutcome:
    """把 Tavily 响应压成带总量上限的紧凑文本。

    单条超长先截到 ``RESULT_CONTENT_CHARS``，总量再截到
    ``RESULT_TOTAL_CHARS``。两截都要留标记——静默截断会让模型误判
    「就这么多资料」。
    """
    results = cast(list[dict[str, Any]], data.get("results") or [])
    if not results:
        return ToolOutcome(ok=True, content="没有搜到相关结果。", preview="0 条结果")

    candidates = results[:requested]
    lines: list[str] = []
    total = 0
    # 因字符预算没塞进去的条数。idx 是 1-based，在 idx 处 break 时
    # 实际保留了 idx-1 条，丢弃数是 len(candidates) - (idx - 1)。
    over_budget = 0

    for idx, item in enumerate(candidates, start=1):
        title = str(item.get("title") or "（无标题）")
        url = str(item.get("url") or "")
        content = str(item.get("content") or "")
        if len(content) > RESULT_CONTENT_CHARS:
            content = content[:RESULT_CONTENT_CHARS] + "…（本条已截断）"

        # **不用方括号编号**。
        #
        # 方括号是角标的语法（``[1]`` = 引用表里的第 1 条）。用方括号
        # 编号却不在引用表里，模型会在正文里写 ``[1]``，而引用表里
        # 没有 1 号——角标指错，且没有任何报错。
        #
        # 没有 context 时（无 db 的路径）搜索结果进不了引用表，所以用
        # 「结果 N」这种不会与角标混淆的写法。
        block = f"结果 {idx}. {title}\nURL: {url}\n{content}"
        if total + len(block) > RESULT_TOTAL_CHARS:
            over_budget = len(candidates) - (idx - 1)
            break

        lines.append(block)
        total += len(block)

    text = "\n\n".join(lines)
    # 两种截断分开报：按 max_results 裁掉的，和因字符预算放不下的。
    # 混成一句「另有 N 条未显示」会让模型去找本来就没请求的资料。
    notes: list[str] = []
    dropped_by_request = len(results) - len(candidates)
    if dropped_by_request > 0:
        notes.append(f"（结果已按 max_results={requested} 裁掉另外 {dropped_by_request} 条）")
    if over_budget > 0:
        notes.append(f"（内容超长，另有 {over_budget} 条未显示）")
    if notes:
        text += "\n\n" + "".join(notes)

    found = len(lines)
    # 同时产出**待核对证据**——给 Analyst 节点用。
    #
    # 证据取的是**实际进了 content 的那几条**（``candidates[:found]``），
    # 不是全部 results：被字符预算丢掉的内容模型都没看到，拿去核对
    # 就是核对模型没读过的东西。
    #
    # excerpt 用未截断的 content（按 EVIDENCE 的上限再截一次）——
    # content 里那份已经按 RESULT_CONTENT_CHARS 截过了，正好是核对
    # 需要的粒度。
    evidence = tuple(
        ToolEvidence(
            title=str(item.get("title") or "（无标题）"),
            excerpt=str(item.get("content") or "")[:EVIDENCE_EXCERPT_CHARS],
            # 完整内容——给落库与 critic 校验用（见 ToolEvidence 的说明）。
            content=str(item.get("content") or "")[:RESULT_CONTENT_CHARS],
            url=str(item.get("url") or ""),
        )
        for item in candidates[:found]
    )

    return ToolOutcome(
        ok=True,
        content=text,
        preview=f"共 {found} 条结果"
        + (f"，超长丢弃 {over_budget} 条" if over_budget else "")
        + (f"，按上限裁掉 {dropped_by_request} 条" if dropped_by_request else ""),
        evidence=evidence,
    )


# ── local_search 实现 ─────────────────────────────────────────


async def _run_local_search(context: ToolContext, tool_input: dict[str, Any]) -> ToolOutcome:
    """在用户私有资料里做混合检索，把命中切片压成带编号的素材块。

    编号走 ``context.citations``——整轮循环共用同一个表，所以第二次调用
    拿到的是续编的号，不会覆盖第一次的号。
    """
    from app.services import retriever  # 顶层 import 会成环：retriever → citation

    query = str(tool_input.get("query", "")).strip()
    if not query:
        return ToolOutcome(ok=False, content="检索关键词不能为空。", preview="参数错误")

    # 没有向量引擎 → 本地检索跑不了。
    #
    # 它与「联网来源能不能占角标号」无关（那个只要 db），所以这里是
    # **局部**降级，不是整个 context 都不给。
    if context.vec_engine is None:
        return ToolOutcome(
            ok=False,
            content="本地检索不可用（没有向量索引），请改用联网搜索。",
            preview="缺少检索上下文",
        )

    # 查询向量**在这里算一次**，两处复用：
    # 1. 传给 retrieve（它内部不再重复算）
    # 2. 判断「语义相关性判断能不能跑」
    # 之前这两处各算一次 = 两次调嵌入服务——慢，且嵌入服务欠费时
    # 整次 local_search 直接失败（用户看到「接口报错、没有内容」）。
    query_vector = await retriever.query_vector_for(query)
    results = await retriever.retrieve(
        context.db,
        context.vec_engine,
        query,
        user_id=context.user_id,
        limit=LOCAL_SEARCH_TOP_K,
        query_vector=query_vector,
        query_vector_given=True,
    )
    if not results:
        # 明确说「没有」而不是返回空串：模型看到空 tool_result 会以为
        # 工具坏了，转而去编造或反复重试。
        return await _empty_retrieval_outcome(context, query, query_vector)

    pairs = context.citations.register(results)
    rules = citation.citation_rules(context.citations)
    # 引用表满了、这批新切片全被丢弃时，证据块是空的——必须明说，
    # 否则模型收到「编号 [1] 到 [10]」却零条证据，会拿编号编内容。
    saturated = citation.render_saturated_notice(context.citations.dropped)
    evidence = citation.render_evidence(pairs)
    if saturated and not evidence:
        evidence = saturated
    # 没配嵌入 key 时相关性下限**根本没跑**，这批命中只是字面匹配——
    # 要告诉模型「这些是关键词命中，没做语义相关性判断」，否则它会把
    # 字面沾边的切片当成「检索到的相关证据」。
    unchecked = ""
    if not retriever.semantic_filter_active(query_vector):
        unchecked = (
            "（注意：本次只做了关键词匹配，没有做语义相关性判断——"
            "下面这些素材与问题的关联度未经确认，请自行判断是否采信。）"
        )
    parts = [part for part in (evidence, unchecked, rules) if part]
    return ToolOutcome(
        ok=True,
        content="\n\n".join(parts),
        preview=f"命中 {len(results)} 条本地资料",
        references=tuple(context.citations.all),
    )


async def _empty_retrieval_outcome(
    context: ToolContext, query: str, query_vector: list[float] | None = None
) -> ToolOutcome:
    """0 条命中时的三种结局，文案不一样。

    - **资料库里压根没有相关内容** → 现有文案，模型如实说明即可
    - **有资料但与问题无关，被相关性下限过滤掉了** → 新文案，要明确告诉
      模型这些资料与问题无关、不要拿它们当证据；并挂上错误码——用户必须
      知道自己的私有资料被跳过了，否则他以为报告里没有引用是因为资料库里
      确实没有
    - **相关性根本没被评估过**（没配嵌入 key，或资料刚上传、索引还没建好）
      → **不能**说「资料与问题无关」：用户的资料可能高度相关，只是此刻
      还无法判断。那是事实性错误陈述，模型会照着对用户说。

    三种都是 ``ok=True``：检索本身没失败，模型应该继续用联网搜索作答。
    """
    from app.services import retriever  # 顶层 import 会成环：retriever → citation

    # 向量引擎在 ``_run_local_search`` 开头已经验过不为 None——到这里
    # 必然有值。断言而不是静默兜底：真缺了就是 bug，应该响。
    assert context.vec_engine is not None

    reason = await retriever.explain_no_result(
        context.db,
        context.vec_engine,
        query,
        context.user_id,
        query_vector=query_vector,
        query_vector_given=query_vector is not None,
    )
    if reason is retriever.NoResultReason.NO_MATERIAL:
        return ToolOutcome(
            ok=True,
            content="用户的资料库里没有检索到相关内容。请如实说明资料中没有，不要凭猜测补充数字。",
            preview="0 条命中",
        )
    if reason is retriever.NoResultReason.NOT_EVALUATED:
        # 索引还没建好 / 无法评估相关性——只说「没法评估」，不许说「不相关」。
        return ToolOutcome(
            ok=True,
            content="无法评估用户的私有资料与这个问题是否相关（资料索引尚未就绪，"
            "或语义检索未启用）。请不要断言资料与问题无关——只说本次回答没有"
            "使用私有资料，并在有联网结果时正常作答。",
            preview="0 条命中 · 相关性未评估",
        )
    classified = _classify_tool_failure(LOCAL_SEARCH_SPEC.name, RetrievalNoMatchError(query))
    return ToolOutcome(
        ok=True,
        content=classified.message,
        preview=f"0 条命中 · {classified.preview}（{classified.code}）",
        error_code=classified.code,
    )


# ── dedup 实现 ────────────────────────────────────────────────


def _run_dedup(tool_input: dict[str, Any]) -> ToolOutcome:
    """按规范化 URL 去重，保序返回。

    存在的意义不只是省 token：模型看到同一篇文章出现三次会当成三份
    独立证据，得出「多方证实」的错误结论。给模型一个显式的去重动作，
    比指望它自己看穿更可靠。
    """
    raw_urls = tool_input.get("urls")
    if not isinstance(raw_urls, list):
        return ToolOutcome(ok=False, content="urls 必须是数组。", preview="参数错误")

    seen: set[str] = set()
    kept: list[str] = []
    skipped = 0
    for raw in raw_urls:
        # 只收真正的字符串。str(None) 得到 "None"、str(123) 得到 "123"，
        # 混进结果会被模型当成合法链接继续用——比漏掉几条结果更糟。
        if not isinstance(raw, str):
            skipped += 1
            continue
        url = raw.strip()
        if not url:
            skipped += 1
            continue
        try:
            canonical = canonicalize_url(url)
        except ValueError:
            # urlsplit 对全角斜杠等 NFKC 异常字符直接抛 ValueError。
            # 一条坏 URL 不该让整批好 URL 的去重结果消失——dedup 的作用
            # 是清理证据，坏数据跳过即可。
            skipped += 1
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        kept.append(url)

    dropped = len(raw_urls) - len(kept) - skipped
    lines = "\n".join(kept) if kept else "（全部 URL 去重后为空）"
    note = f"（另有 {skipped} 条不是合法 URL 已忽略）" if skipped else ""
    return ToolOutcome(
        ok=True,
        content=lines + note,
        preview=f"保留 {len(kept)} 条，去掉重复 {dropped} 条"
        + (f"，忽略 {skipped} 条" if skipped else ""),
    )
