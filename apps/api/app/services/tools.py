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
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.services import citation
from app.services.citation import Reference, ReferenceTable
from app.services.llm import LLMNotConfiguredError, get_tavily_client

# ── 常量 ──────────────────────────────────────────────────────

# 单次搜索取几条结果。5 条够模型判断趋势，再多只是往上下文里塞噪声。
SEARCH_MAX_RESULTS = 5

# 单条搜索结果的正文截断长度。Tavily 的 content 字段可能包含整篇网页，
# 一条就够撑爆一轮上下文。
RESULT_CONTENT_CHARS = 800

# 全部搜索结果的总量上限。超了追加截断标记——静默截断会让模型误以为
# 搜索只有这几条，编出「没有更多资料」的结论。
RESULT_TOTAL_CHARS = 4000

# 本地检索取几条切片。citation.MAX_REFERENCES 是 10，这里取 12 是为了给
# RRF 融合后的一点重排留余量——超出 10 的会被引用表截掉，但模型仍能拿到
# 排名靠前的那几条。
LOCAL_SEARCH_TOP_K = 12

# Tavily SDK 自带的超时（只管 HTTP 连接阶段）。
TAVILY_TIMEOUT_SECONDS = 10.0

# 外层兜底。SDK 的 timeout 管不到 DNS 解析慢、建连挂起这类情况。
TAVILY_HARD_TIMEOUT_SECONDS = 15.0

# URL 里这些跟踪参数不参与身份判定——同一篇文章带不同 utm 就是同一条。
TRACKING_PARAMS = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"})

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
    vec_engine: AsyncEngine
    user_id: int
    citations: ReferenceTable


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """一次工具执行的结果。

    ``content`` 是要喂回模型的文本（已裁剪）；``preview`` 是给前端看的
    简短摘要，几十字以内——完整内容已经在 SSE 的 delta 里流过了，
    检查器面板只需要一行说明。

    ``references`` 是本次调用产出的引用表（本地检索才有）。模型看不到这个
    字段，但 agent 循环会把它透传给前端的 ``reference`` 事件。
    """

    ok: bool
    content: str
    preview: str = ""
    references: tuple[Reference, ...] = ()


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
            return await _run_tavily_search(tool_input)
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
        return ToolOutcome(ok=False, content=str(exc), preview="搜索工具未配置")
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
        retryable = isinstance(exc, (ConnectionError, TimeoutError, OSError))
        logger.warning("工具 %s 执行失败（可重试=%s）", name, retryable, exc_info=exc)
        if retryable:
            return ToolOutcome(
                ok=False,
                content=f"工具 {name} 暂时无法连接到外部服务。请稍后重试，或改用其他方式回答。",
                preview="外部服务不可用",
            )
        return ToolOutcome(
            ok=False,
            content=f"工具 {name} 内部出错，本次调用没有完成。请不要重复调用它，"
            f"直接基于已有信息作答。",
            preview="工具内部错误",
        )

    return ToolOutcome(
        ok=False,
        content=f"不存在名为 {name} 的工具。可用工具：{', '.join(s.name for s in ALL_TOOLS)}。",
        preview="未知工具",
    )


# ── tavily_search 实现 ────────────────────────────────────────


async def _run_tavily_search(tool_input: dict[str, Any]) -> ToolOutcome:
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
    return _format_search_results(cast(dict[str, Any], raw), max_results)


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

        block = f"[{idx}] {title}\nURL: {url}\n{content}"
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
    return ToolOutcome(
        ok=True,
        content=text,
        preview=f"共 {found} 条结果"
        + (f"，超长丢弃 {over_budget} 条" if over_budget else "")
        + (f"，按上限裁掉 {dropped_by_request} 条" if dropped_by_request else ""),
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

    results = await retriever.retrieve(
        context.db,
        context.vec_engine,
        query,
        user_id=context.user_id,
        limit=LOCAL_SEARCH_TOP_K,
    )
    if not results:
        # 明确说「没有」而不是返回空串：模型看到空 tool_result 会以为
        # 工具坏了，转而去编造或反复重试。
        return ToolOutcome(
            ok=True,
            content="用户的资料库里没有检索到相关内容。请如实说明资料中没有，"
            "不要凭猜测补充数字。",
            preview="0 条命中",
        )

    pairs = context.citations.register(results)
    rules = citation.citation_rules(context.citations)
    return ToolOutcome(
        ok=True,
        content=f"{citation.render_evidence(pairs)}\n\n{rules}",
        preview=f"命中 {len(results)} 条本地资料",
        references=tuple(context.citations.all),
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


def canonicalize_url(url: str) -> str:
    """把 URL 归一化成「同一篇文章」的判定依据。

    去掉 utm/gclid 等跟踪参数、去掉 fragment（#anchor 不影响页面内容）、
    统一 host 小写、去掉 www. 前缀与路径尾斜杠，并按字母序重排剩余 query
    ——参数顺序不同但内容相同的 URL 也应该判为同一条。
    """
    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    kept = sorted((k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_PARAMS)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(kept), ""))
