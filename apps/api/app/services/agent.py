"""agent 主循环：提问 → 模型决定要不要调工具 → 执行 → 再问 → 出正文。

这是 argus 第一个真正的 agent，只有一个模型循环，没有多智能体编排
（那是 W2 的 LangGraph）。但它已经具备 agent 的三个本质特征：

1. 模型自己决定调哪个工具、调几次（不是代码写死的流程）
2. 工具结果回喂给模型，它能根据结果改变下一步
3. 循环有终止条件与上下文保护，不会无限烧钱

协议上的两个硬约束：

- **thinking block 不转发给用户，但必须原样回传给下一轮。** 模型的
  扩展思考带 signature，改动或丢失会导致第二轮请求被拒。它是内部
  推理过程，前端要的是研究结论不是思维链。
- **任一时刻只有一个节点 active。** 前端 AgentDAG 用 findIndex 定位
  高亮轨道，两个 active 会让它算错位置。由 ``NodeTracker`` 断言保证。
"""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast
from uuid import uuid4

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import get_settings
from app.services.citation import ReferenceTable
from app.services.llm import get_anthropic_client
from app.services.stream import (
    AgentEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    NodeEvent,
    ReferenceEvent,
    TextSlicer,
    ToolCallEvent,
)
from app.services.tools import (
    ToolContext,
    ToolSpec,
    available_tools,
    execute_tool,
    tool_schemas,
)

# ── 常量 ──────────────────────────────────────────────────────

MAX_TURNS = 6  # 循环轮数上限。单轮经中转站实测数秒，6 轮约 30-60 秒
MAX_OUTPUT_TOKENS = 4096  # 单轮输出预算。thinking 与正文共享，不能太小

# 最后一轮强制收尾时传进去的空工具列表——模型看到空列表就不会再要工具。
no_tools: tuple[ToolSpec, ...] = ()

# 强制收尾指令。占位符 {} 会被填成 MAX_TURNS，让模型知道自己是被上限
# 打断的而不是自己选择收尾——否则它会再解释一轮为什么不早停。
FINALIZE_INSTRUCTION = "你已达到 {} 次检索上限。请基于已有信息直接给出最终答案，不要再调用工具。"

# 只写**跨工具的编排规则**，不写「有工具 X 可用」——那些已经在各自的
# description 里了（见 app/services/tools.py 的 *_SPEC.description）。
#
# Anthropic 官方的分工是：工具的「是什么/何时用」属于 tool description，
# system prompt 负责「when and when not to use」这类编排。重复写一遍是
# 冗余 token，还会和 tools 数组脱节——写死在这里的 tavily_search 在
# 没配 key 时并不存在，模型却被指示去调它。
#
# 下面第 2 条是**唯一**必须在 system prompt 里说的：它是跨两个工具的
# 优先级顺序，任何单个 description 都承载不了这个信息。
SYSTEM_PROMPT = """你是 Argus 的研究助手，回答用户的研究类问题。

工作方式：
- 你有若干可用工具，各工具的适用场景写在它自己的描述里，按描述选择。
- 检索优先级：先用私有资料工具查用户自己的文档；它没有覆盖的部分，
  再考虑联网搜索。私有资料是用户特意上传的，优先级高于公开搜索结果。
- 检索到的链接用 dedup 清理，避免把同一篇文章当成多份独立证据。
- 资料不足时，明确说明缺什么，不要编造数据或引用。
- 最终回答用中文，结构清晰；涉及数据时写明来源。

写作要求：
- 先给结论，再给依据。
- 用 Markdown 组织内容，该用小标题和列表就用。
- 不要输出思考过程，只输出结论与依据。"""

logger = logging.getLogger(__name__)


class Stage(StrEnum):
    """前端约定的 5 个节点 id。

    本阶段只有 ``RESEARCHER`` 真正调 LLM（搜索取证），``WRITER`` 承接
    最终正文，其余是时序占位——让前端的 DAG 有完整的推进过程可演。
    W2 接 LangGraph 多智能体后，这几个节点会各自绑定真实的 agent。
    """

    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    CRITIC = "critic"


NODE_DETAILS: dict[Stage, str] = {
    Stage.SUPERVISOR: "正在拆解问题意图",
    Stage.RESEARCHER: "正在检索与取证",
    Stage.ANALYST: "正在交叉核对证据",
    Stage.WRITER: "正在撰写研究报告",
    Stage.CRITIC: "正在校验引用",
}


# ── 内部 DTO ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TurnResult:
    """一轮模型请求的结果。

    ``content`` 是原样回传给下一轮的 assistant 内容——含 thinking block
    及其 signature。``text`` 是这轮产出的正文，供前端流式展示。
    """

    content: list[dict[str, Any]]
    text: str
    tool_calls: list[dict[str, Any]]
    stop_reason: str
    input_tokens: int
    output_tokens: int


@dataclass(slots=True)
class TurnLedger:
    """一次研究的用量与产出记账。

    把这些散落的局部变量收进一个对象，是因为它们有**跨方法**的读者：
    ``turns`` / token 数在异常路径上要读，已经在 try 块外赋过值；
    ``produced_text`` 在循环外的收尾分支要读。摊平成局部变量时，
    读到的值到底是「哪一次请求累加的」只有读代码的人知道。
    """

    session_id: str
    started_at: float
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    truncated: bool = False
    produced_text: bool = False

    def begin_turn(self) -> None:
        """占用一轮额度。

        计数在**请求发出之前**递增：崩溃的那一轮同样烧掉了额度，
        少算一轮就等于告诉用量统计「这次几乎没花钱」，重试时
        也就看不到上次真正的开销。
        """
        self.turns += 1

    def record(self, result: TurnResult) -> None:
        """累加一轮的 token 用量，并记住是否产出了正文。"""
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        if result.text:
            self.produced_text = True

    def done(self) -> DoneEvent:
        return DoneEvent(
            session_id=self.session_id,
            elapsed_ms=int((time.monotonic() - self.started_at) * 1000),
            turns=self.turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            truncated=self.truncated,
        )


class NodeTracker:
    """节点生命周期的单写者。

    断言「同一时刻只有一个 active」不是装饰：前端 AgentDAG 用
    ``nodes.findIndex(n => n.lifecycle === 'active')`` 算高亮轨道的
    位置，两个 active 会让它算错。把它变成后端显式失败，比让前端静默
    渲染错位置好排查得多。
    """

    def __init__(self) -> None:
        self._active: Stage | None = None
        self._started_at = 0.0

    def activate(self, stage: Stage) -> NodeEvent:
        assert self._active is None, f"节点 {self._active} 尚未结束，不能激活 {stage}"
        self._active = stage
        self._started_at = time.monotonic()
        return NodeEvent(node_id=stage.value, lifecycle="active", detail=NODE_DETAILS[stage])

    def complete(self) -> NodeEvent | None:
        """结束当前 active 节点；没有 active 时返回 None。"""
        if self._active is None:
            return None
        elapsed = int((time.monotonic() - self._started_at) * 1000)
        done = NodeEvent(
            node_id=self._active.value,
            lifecycle="completed",
            elapsed_ms=elapsed,
        )
        self._active = None
        return done

    def switch(self, stage: Stage) -> list[NodeEvent]:
        """从当前节点切到下一个：先关旧的，再开新的。"""
        events: list[NodeEvent] = []
        closing = self.complete()
        if closing is not None:
            events.append(closing)
        events.append(self.activate(stage))
        return events


# ── 主循环 ────────────────────────────────────────────────────


async def run_agent(
    question: str,
    *,
    user_id: int,
    db: AsyncSession | None = None,
    vec_engine: AsyncEngine | None = None,
) -> AsyncIterator[AgentEvent]:
    """跑一轮完整的研究流程，逐个产出事件。

    终止条件任一满足即停：模型不再要工具、轮数超上限、LLM 抛异常。
    无论怎么停，最后都会补一个 ``DoneEvent`` 或 ``ErrorEvent``——前端
    靠它收尾，缺了会一直转圈。

    ``user_id`` 是私域检索的边界，没有它就查不了本地资料。
    ``db`` / ``vec_engine`` 缺省时摘掉 ``local_search`` 工具——
    测试里大量场景不接数据库，强行造连接比少一个工具更麻烦。
    """
    ledger = TurnLedger(session_id=str(uuid4()), started_at=time.monotonic())
    tracker = NodeTracker()

    # 本地拼装提示词，让前端能看到「调度」这一步。
    yield tracker.activate(Stage.SUPERVISOR)
    context = _build_context(user_id, db, vec_engine)
    tools = available_tools(has_local=context is not None)
    prompt = _build_user_prompt(question, tools, context is not None)
    for event in _close(tracker):
        yield event

    try:
        client = get_anthropic_client()
    except Exception as exc:
        logger.warning("模型客户端不可用，流程中止", exc_info=exc)
        yield ErrorEvent(code="llm_not_configured", message="模型服务未配置")
        return

    yield tracker.activate(Stage.RESEARCHER)

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    # 每轮的 tool_result 累积在局部变量里，不放模块级全局——SSE 并发时
    # 全局变量会让两个用户的搜索结果互相污染。
    tool_results: list[dict[str, Any]] = []

    try:
        for turn in range(MAX_TURNS):
            ledger.begin_turn()
            result = await _run_turn(client, messages, tools)
            ledger.record(result)

            # thinking block 原样回传——带 signature，改动会被上游拒绝。
            messages.append({"role": "assistant", "content": result.content})

            if result.text:
                # 扩展思考模型常一边调工具一边说话，这段也要给用户看。
                for event in tracker.switch(Stage.WRITER):
                    yield event
                for piece in _slice_for_display(result.text):
                    yield DeltaEvent(node_id=Stage.WRITER.value, text=piece)

            if not result.tool_calls:
                ledger.truncated = result.stop_reason == "max_tokens"
                break

            # 还要继续调工具：切回 researcher 节点。
            for event in tracker.switch(Stage.RESEARCHER):
                yield event

            async for tool_event in _run_tools(result.tool_calls, tool_results, context):
                yield tool_event

            # Anthropic 协议：同一轮的多个 tool_result 必须打包进一条
            # user 消息，逐条 append 成多条会被拒。
            # 重新绑定而不是 .clear()——messages 里存的是这个列表的引用，
            # clear 会把已 append 的 tool_result 一起清空。
            messages.append({"role": "user", "content": tool_results})
            tool_results = []

            if turn == MAX_TURNS - 1:
                # 最后一轮还在要工具：强制收尾，让模型基于现有信息作答，
                # 用户仍能拿到答案，只是没有新的检索。
                ledger.truncated = True
                # 收尾指令作为**同一条** user 消息的第二个 block，不能另起
                # 一条 user 消息——那会构造出连续同角色消息，上游可能拒收。
                messages[-1]["content"] = [
                    *messages[-1]["content"],
                    {"type": "text", "text": FINALIZE_INSTRUCTION.format(MAX_TURNS)},
                ]
                async for finalize_event in _finalize(client, ledger, messages, tracker):
                    yield finalize_event
                break
    except Exception as exc:
        logger.warning("agent 循环异常中止（已完成 %d 轮）", ledger.turns, exc_info=exc)
        ledger.truncated = True
        for event in _close(tracker):
            yield event
        # 崩溃也要发 DoneEvent：它是唯一带 session_id 与 token 数的事件。
        # 缺了它，已经烧掉的 token 就成了用量统计的黑洞——而这恰恰是
        # 最需要留痕的场景（重试也才知道上次烧了多少）。
        yield ledger.done()
        yield ErrorEvent(code="llm_unavailable", message="模型服务暂时不可用，请稍后重试")
        return

    # 一个字的正文都没产出时，必须发 error 而不是让 done 带空正文收尾。
    #
    # 触发场景：模型只回 thinking（stop_reason="end_turn"）或直接 refusal。
    # 实测那种情况下 stop_reason 是正常的、tool_calls 为空，循环照常
    # break，truncated 也是 False——前端于是把一份空白报告标成「已完成」，
    # DAG 上 writer 节点从未 activate，用户看不到任何错误提示。
    if not ledger.produced_text:
        for event in _close(tracker):
            yield event
        yield ErrorEvent(
            code="empty_response",
            message="模型未产出内容，请重试",
            retryable=True,
        )
        return

    # 收尾：关掉当前节点，再过 analyst / critic 占位，让 DAG 走完 5 步。
    for event in _settle(tracker):
        yield event
    yield ledger.done()


async def _finalize(
    client: AsyncAnthropic,
    ledger: TurnLedger,
    messages: list[dict[str, Any]],
    tracker: NodeTracker,
) -> AsyncIterator[AgentEvent]:
    """轮数用尽后的强制收尾：关掉工具，再基于已有信息作答。

    ``messages`` 在调用前已被就地追加了收尾指令，这里不再回传 assistant
    内容——主循环随即 break，``messages`` 不再被读，多存一份只是让人
    以为它还有用。
    """
    ledger.begin_turn()
    final = await _run_turn(client, messages, no_tools)
    ledger.record(final)
    if not final.text:
        return
    for event in tracker.switch(Stage.WRITER):
        yield event
    for piece in _slice_for_display(final.text):
        yield DeltaEvent(node_id=Stage.WRITER.value, text=piece)


def _close(tracker: NodeTracker) -> list[NodeEvent]:
    """关掉当前 active 节点；本来就没有 active 时给空列表。

    单独抽出来是因为这个「可能有值、可能没有」的两行模式在主循环里
    出现过四次，每次都要 ``if ... is not None: yield ...``。
    """
    closing = tracker.complete()
    return [] if closing is None else [closing]


def _settle(tracker: NodeTracker) -> list[NodeEvent]:
    """正常收尾：关掉当前节点，再过 analyst / critic 占位。

    analyst 与 critic 目前不做实际工作，只为让前端的 DAG 走完 5 步——
    用户看到的进度条不会停在 writer 上。将来这两步接真实逻辑时，
    也应该走同一套 activate/complete 语义，而不是另开一条路。
    """
    events = _close(tracker)
    for stage in (Stage.ANALYST, Stage.CRITIC):
        events.append(tracker.activate(stage))
        events.extend(_close(tracker))
    return events


# ── 单轮请求 ──────────────────────────────────────────────────


async def _run_turn(
    client: AsyncAnthropic,
    messages: list[dict[str, Any]],
    tools: tuple[ToolSpec, ...],
) -> TurnResult:
    """跑一轮流式请求，把 SDK 结果收成 TurnResult。

    这里用流式而不是一次性 create，只为拿到 usage 里的 token 计数——
    非流式响应不带完整 usage。中转站会把整个 text 块缓冲成一次
    text_delta（实测 243 字符只给 1 个事件），逐字流式在这里拿不到；
    展示节奏由 ``_slice_for_display`` 补。
    """
    settings = get_settings()
    request: dict[str, Any] = {
        "model": settings.anthropic_complex_model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        request["tools"] = tool_schemas(tools)

    async with client.messages.stream(**cast("Any", request)) as stream:
        final = await stream.get_final_message()

    # exclude_none：text block 的 citations 字段在无引用时是 None。
    # 中转站实测能接受，但直连官方 API 时可能被严格模式拒收，
    # 带上 exclude_none 没有代价。
    content = cast("list[dict[str, Any]]", final.model_dump(exclude_none=True)["content"])

    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    tool_calls = [b for b in content if b.get("type") == "tool_use"]

    return TurnResult(
        content=content,
        text=text,
        tool_calls=tool_calls,
        stop_reason=final.stop_reason or "end_turn",
        input_tokens=final.usage.input_tokens,
        output_tokens=final.usage.output_tokens,
    )


# ── 工具执行 ──────────────────────────────────────────────────


async def _run_tools(
    tool_calls: list[dict[str, Any]],
    sink: list[dict[str, Any]],
    context: ToolContext | None,
) -> AsyncIterator[AgentEvent]:
    """执行一轮里模型要的所有工具，产出 start/end 事件并往 sink 累积结果。

    execute_tool 保证不抛异常——工具失败会变成 ok=False 的 tool_result
    喂回模型，让它自己决定重试还是换路径，用户至少还能拿到答案。

    sink 与 context 都由调用方持有而不是模块级全局：SSE 是并发的，两个
    用户同时提问时全局变量会让 tool_result 互相污染，模型拿到别人的
    搜索结果。context 里的引用表同理——共用一个表会让两个请求串号。
    """
    for call in tool_calls:
        call_id = str(call.get("id", ""))
        name = str(call.get("name", ""))
        tool_input = cast("dict[str, Any]", call.get("input") or {})

        yield ToolCallEvent(
            call_id=call_id,
            phase="start",
            name=name,
            tool_input=tool_input,
        )

        started = time.monotonic()
        outcome = await execute_tool(name, tool_input, context)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        yield ToolCallEvent(
            call_id=call_id,
            phase="end",
            name=name,
            ok=outcome.ok,
            elapsed_ms=elapsed_ms,
            preview=outcome.preview,
        )

        if outcome.references:
            yield ReferenceEvent(
                references=[ref.to_citation() for ref in outcome.references],
            )

        sink.append(
            {
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": outcome.content,
                "is_error": not outcome.ok,
            }
        )


# ── 辅助 ──────────────────────────────────────────────────────


def _build_context(
    user_id: int,
    db: AsyncSession | None,
    vec_engine: AsyncEngine | None,
) -> ToolContext | None:
    """能拿到数据库就建上下文，否则返回 None（对应「无本地检索」）。

    每次调用新建一个 ``ReferenceTable``：编号是**每个请求独立**的，
    共用会让两个并发请求的 ``[1]`` 指向不同切片。
    """
    if db is None or vec_engine is None:
        return None
    return ToolContext(
        db=db,
        vec_engine=vec_engine,
        user_id=user_id,
        citations=ReferenceTable(),
    )


def _build_user_prompt(
    question: str,
    tools: tuple[ToolSpec, ...],
    has_local: bool,
) -> str:
    """拼用户提示词。工具不可用时明说，避免模型编造引用。

    不说的话模型会按「应该联网」的常识去编造引用——用户分不清哪些是
    查到的、哪些是模型想象的。
    """
    names = {spec.name for spec in tools}
    notes: list[str] = []
    if "tavily_search" not in names:
        notes.append("未配置联网搜索工具")
    if not has_local:
        notes.append("无法检索你的私有资料")
    if not notes:
        return question
    return (
        f"{question}\n\n（注意：当前环境{'、'.join(notes)}，"
        "请基于已有知识回答，并说明信息可能不完整。）"
    )


def _slice_for_display(text: str) -> list[str]:
    """把一轮产出的整段正文切成展示片段。

    放在 service 层而不是 gateway，是因为「按什么节奏展示」是 agent 的
    输出语义；gateway 只负责把片段编码成 SSE 字节。
    """
    slicer = TextSlicer()
    pieces = slicer.feed(text)
    pieces.extend(slicer.flush())
    return pieces
