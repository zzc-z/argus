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

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any, Self, cast
from uuid import uuid4

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import get_settings
from app.models.report import Report, ReportSource
from app.models.source import DocumentChunk
from app.services.citation import Reference, ReferenceTable, count_citation_markers
from app.services.errors import classify_llm_error, error_event_for
from app.services.faithfulness import (
    load_source_texts,
    verify_citations,
)
from app.services.llm import (
    STREAM_INTERRUPT_BACKOFF_SECONDS,
    STREAM_INTERRUPT_RETRIES,
    get_anthropic_client,
    is_stream_interrupt,
)
from app.services.stream import (
    AgentEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    FaithfulnessEvent,
    NodeEvent,
    ReferenceEvent,
    ToolCallEvent,
    Typewriter,
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
MAX_OUTPUT_TOKENS = 4096  # 单轮输出总预算。thinking 有自己的上限（THINKING_BUDGET_TOKENS）

# 扩展思考的**独立**预算。
#
# 不设它，思考会膨胀到把 MAX_OUTPUT_TOKENS 吃光，正文一个字写不出来
# （实测：output_tokens=4096、正文 0 字、stop_reason="max_tokens"），
# 而重试没用——连打 5 次全部同样被吃光。详见 _build_turn_request 的说明。
#
# 2048 是实测的折中值：1024 思考偏浅、3072 留给正文的余量变少。
# 改这个值前请重跑那组实测。
THINKING_BUDGET_TOKENS = 2048

# 最后一轮强制收尾时传进去的空工具列表——模型看到空列表就不会再要工具。
no_tools: tuple[ToolSpec, ...] = ()

# 落盘的等待上限。比 ``MODEL_TIMEOUT_SECONDS`` 短得多：正文已经流给用户了，
# 历史报告是附加价值，卡着不放只会占住并发槽位。超时即降级。
PERSIST_TIMEOUT_SECONDS = 5.0

# 崩溃路径的落盘上限，比正常路径短得多。
#
# 正常路径上正文已经完整流给用户了，落盘慢一点用户顶多等一会儿；
# 崩溃路径上用户正盯着红色横幅等失败通知，多等 5 秒是白等——那 5 秒里
# 界面上的转圈还在转，什么新信息都没有。1 秒够本地 SQLite 写完。
PERSIST_TIMEOUT_CRASH_SECONDS = 1.0

# 强制收尾指令。措辞必须说「轮」而不是「检索次数」：一轮里模型可以并行发
# 多个 tool_use，6 轮完全可能对应 15 次检索。告诉模型「你已达到 6 次检索
# 上限」会误导它自己判断证据够不够，进而在答案里加「检索不足，可信度有限」
# 这种画蛇添足的免责声明——而报告正文是用户直接读的东西。
#
# {} 是 MAX_TURNS：让模型知道自己是被上限打断的而不是自己选择收尾，
# 否则它会再解释一轮为什么不早停。
FINALIZE_INSTRUCTION = (
    "你已达到本轮研究的调用轮数上限（共 {} 轮）。请基于已有信息直接给出最终答案，不要再调用工具。"
)

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


@dataclass(frozen=True, slots=True)
class TurnChunk:
    """一轮流式请求里的一个片段。

    ``kind="text"`` 是正文增量（已经过展示切片，可以直接发给前端）；
    ``kind="result"`` 是这一轮的收尾——usage / stop_reason / tool_calls；
    ``kind="reset"`` 表示「已发出的正文作废，从头再来」——只在流被掐断
    后整轮重发时出现。
    """

    kind: str  # "text" | "result" | "reset"
    text: str = ""
    result: TurnResult | None = None


@dataclass(slots=True)
class _FinalizeOut:
    """强制收尾那一步的回传通道。

    见 ``_finalize`` 的说明：生成器只有一个 yield 通道，而这里要同时交回
    「正文整段」与「新账本」两样东西。
    """

    ledger: TurnLedger
    text: str = ""


@dataclass(frozen=True, slots=True)
class TurnLedger:
    """一次研究的用量与产出记账。

    把这些散落的局部变量收进一个对象，是因为它们有**跨方法**的读者：
    ``turns`` / token 数在异常路径上要读，已经在 try 块外赋过值；
    ``produced_text`` 在循环外的收尾分支要读。摊平成局部变量时，
    读到的值到底是「哪一次请求累加的」只有读代码的人知道。

    ## 为什么 frozen

    每个更新方法都返回**新的**账本对象，调用方重新绑定。这样「谁改了什么」
    一眼可见——可变版本里 ``ledger.truncated = True`` 在主循环内有 3 处分散的
    写入点，读代码时得先找出全部写点才知道这个值被谁设成什么。

    代价是调用点要 ``ledger = ledger.record(result)`` 而不是 ``ledger.record(result)``。
    值得：那行多出来的赋值本身就是「这里更新了账本」的显式标记，
    而可变版本里的静默 mutation 恰恰是 AGENTS.md 要防的东西。
    """

    session_id: str
    started_at: float
    user_id: int
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    truncated: bool = False
    produced_text: bool = False
    report_id: int | None = None

    def begin_turn(self) -> Self:
        """占用一轮额度，返回新账本。

        计数在**请求发出之前**递增：崩溃的那一轮同样烧掉了额度，
        少算一轮就等于告诉用量统计「这次几乎没花钱」，重试时
        也就看不到上次真正的开销。
        """
        return replace(self, turns=self.turns + 1)

    def record(self, result: TurnResult) -> Self:
        """累加一轮的 token 用量，并记住是否产出了正文。"""
        return replace(
            self,
            input_tokens=self.input_tokens + result.input_tokens,
            output_tokens=self.output_tokens + result.output_tokens,
            produced_text=self.produced_text or bool(result.text),
        )

    def mark_truncated(self) -> Self:
        return replace(self, truncated=True)

    def with_report_id(self, report_id: int | None) -> Self:
        """记下刚落盘的报告 id。None = 落盘失败或没落（db 为 None）。"""
        return replace(self, report_id=report_id)

    def done(self) -> DoneEvent:
        return DoneEvent(
            session_id=self.session_id,
            elapsed_ms=int((time.monotonic() - self.started_at) * 1000),
            turns=self.turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            truncated=self.truncated,
            report_id=self.report_id,
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

    def fail(self, detail: str = "") -> NodeEvent | None:
        """把当前 active 节点标成**失败**；没有 active 时返回 None。

        ## 为什么要有 failed 而不是一律 completed

        失败路径原先也走 :meth:`complete`，于是前端的 DAG 上**每个节点都是
        打勾的「通过」**——哪怕整次研究崩了、模型服务挂了、检索全被过滤。
        用户看到的是「全部通过」，实际上一件事都没成。

        「通过」和「失败」必须能区分开，否则那张图没有信息量。
        """
        if self._active is None:
            return None
        elapsed = int((time.monotonic() - self._started_at) * 1000)
        failed = NodeEvent(
            node_id=self._active.value,
            lifecycle="failed",
            detail=detail,
            elapsed_ms=elapsed,
        )
        self._active = None
        return failed

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
    ledger = TurnLedger(
        session_id=str(uuid4()),
        started_at=time.monotonic(),
        user_id=user_id,
    )
    tracker = NodeTracker()

    # 本地拼装提示词，让前端能看到「调度」这一步。
    yield tracker.activate(Stage.SUPERVISOR)
    context = _build_context(user_id, db, vec_engine)
    tools = available_tools(has_local=context is not None)
    prompt = _build_user_prompt(question, tools, context is not None)
    # Critic 校验要用两样东西：
    #
    # collected_refs —— 每轮工具产出的引用。
    # report_body    —— **所有轮**的正文拼接。用户看到的报告是这几轮
    # DeltaEvent 连起来的，只校验最后一轮等于「抽查标成全检」。实测这
    # 条路径在轮数用尽时更糟：_finalize 那一轮的正文已经发出去，
    # 但循环里的 result 还指着它之前那轮，结论段完全没被校验。
    collected_refs: list[Reference] = []
    report_body: list[str] = []

    # 先确认客户端可用，再关掉 supervisor 节点。反过来的话，客户端不可用时
    # supervisor 已经被标成「完成」——DAG 上打勾的「通过」配着一句红横幅，
    # 自相矛盾。
    try:
        client = get_anthropic_client()
    except Exception as exc:
        logger.warning("模型客户端不可用，流程中止", exc_info=exc)
        for event in _fail(tracker, "模型服务不可用"):
            yield event
        classified = classify_llm_error(exc)
        yield ErrorEvent(
            code=classified.code,
            message=classified.message,
            retryable=classified.retryable,
        )
        return

    for event in _close(tracker):
        yield event

    yield tracker.activate(Stage.RESEARCHER)

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    # 每轮的 tool_result 累积在局部变量里，不放模块级全局——SSE 并发时
    # 全局变量会让两个用户的搜索结果互相污染。
    tool_results: list[dict[str, Any]] = []

    try:
        for turn in range(MAX_TURNS):
            ledger = ledger.begin_turn()
            result: TurnResult | None = None
            # 正文边收边发：上游的 text_delta 一到就切片发给用户。
            #
            # 「先切到 writer 节点再发」：节点切换必须在第一个正文片段
            # **之前**发生，否则前端会先收到一段正文、然后 DAG 才切到
            # writer，顺序反了。
            writer_active = False
            async for chunk in _run_turn(client, messages, tools):
                if chunk.kind == "text":
                    if not writer_active:
                        writer_active = True
                        for event in tracker.switch(Stage.WRITER):
                            yield event
                    yield DeltaEvent(node_id=Stage.WRITER.value, text=chunk.text)
                elif chunk.kind == "reset":
                    # 流被掐断后整轮重发：已发的正文作废，前端清零后重收。
                    yield DeltaEvent(node_id=Stage.WRITER.value, text="", reset=True)
                else:
                    result = chunk.result

            # 流中断重发全部失败时 _run_turn 会抛异常，不会走到这里。
            # result 为 None 说明一轮都没产出任何 chunk——不可能
            # （_run_turn 至少会 yield 一个 result），但显式报错比
            # 后面 AttributeError 强。
            if result is None:
                raise RuntimeError("模型一轮请求没有返回结果")
            ledger = ledger.record(result)
            if result.text:
                report_body.append(result.text)

            # thinking block 原样回传——带 signature，改动会被上游拒绝。
            messages.append({"role": "assistant", "content": result.content})

            # 截断标记与「要不要继续调工具」是两件事，必须分开判。
            # Anthropic 官方说明响应被 max_tokens 切断时可以同时带着 tool_use
            # 块返回；把判断埋在「没有工具调用」的分支里，这种一轮里同时发生
            # 截断与工具调用的响应就会漏标 truncated——用户拿到一份自称完整、
            # 实际少了一截的报告。
            # https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons
            if result.stop_reason == "max_tokens":
                ledger = ledger.mark_truncated()

            if not result.tool_calls:
                break

            # 还要继续调工具：切回 researcher 节点。
            for event in tracker.switch(Stage.RESEARCHER):
                yield event

            async for tool_event in _run_tools(result.tool_calls, tool_results, context, collected_refs):
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
                ledger = ledger.mark_truncated()
                # 收尾指令作为**同一条** user 消息的第二个 block，不能另起
                # 一条 user 消息——那会构造出连续同角色消息，上游可能拒收。
                messages[-1]["content"] = [
                    *messages[-1]["content"],
                    {"type": "text", "text": FINALIZE_INSTRUCTION.format(MAX_TURNS)},
                ]
                # begin_turn 放在调用方而不是 _finalize 内部：它必须在
                # 主循环这个 try 里赋值，_finalize 抛异常时账本已经记上了
                # 这一轮。和主循环同语义——「崩了也算」。
                ledger = ledger.begin_turn()
                out = _FinalizeOut(ledger=ledger)
                async for finalize_event in _finalize(client, ledger, messages, tracker, out):
                    yield finalize_event
                ledger = out.ledger
                # 追加**整段** final.text，与主循环同粒度。不能用 DeltaEvent
                # 的切片：那些是展示节奏（每 20-36 字一片），`"\n".join`
                # 会在每个逗号处插换行，落盘正文与用户读到的完全不一样。
                if out.text:
                    report_body.append(out.text)
                break
    except Exception as exc:
        logger.warning("agent 循环异常中止（已完成 %d 轮）", ledger.turns, exc_info=exc)
        ledger = ledger.mark_truncated()
        # 崩溃 → 当前节点标**失败**，不是「完成」。前端 DAG 上打勾的
        # 「通过」会让人以为整条流水线跑通了，实际上一件事都没成。
        for event in _fail(tracker, "执行中断"):
            yield event
        # 崩溃也要发 DoneEvent：它是唯一带 session_id 与 token 数的事件。
        # 缺了它，已经烧掉的 token 就成了用量统计的黑洞——而这恰恰是
        # 最需要留痕的场景（重试也才知道上次烧了多少）。
        #
        # done 帧要带 report_id：已生成的正文必须落盘。崩溃时那几轮正文
        # 已经烧掉了 token（实测一次崩溃烧掉 29548 输入 token），丢掉它
        # 等于用户只拿到一句红横幅、正文一个字节都拿不到，而历史报告里
        # 也没有这份——最贵的一次失败变成最没有产出的失败。
        #
        # 但**一个字都没产出时不能落盘**——那会写进一条空报告，前端
        # 照样渲染「查看完整报告 ↗」，点进去是空白。正常路径有
        # ``produced_text`` 守卫（见下面的 empty_response 分支），
        # 崩溃路径必须同样守住。
        report_id = (
            await _persist_report(
                db=db,
                question=question,
                content="\n".join(report_body),
                ledger=ledger,
                refs=collected_refs,
                persist_timeout=PERSIST_TIMEOUT_CRASH_SECONDS,
            )
            if ledger.produced_text
            else None
        )
        yield ledger.with_report_id(report_id).done()
        yield error_event_for(exc)
        return

    # 一个字的正文都没产出时，必须发 error 让前端显示失败。
    #
    # 触发场景：模型只回 thinking（stop_reason="end_turn"）或直接 refusal。
    # 实测那种情况下 stop_reason 是正常的、tool_calls 为空，循环照常
    # break，truncated 也是 False——前端于是把一份空白报告标成「已完成」，
    # DAG 上 writer 节点从未 activate，用户看不到任何错误提示。
    #
    # 但 DoneEvent 仍然要发，理由与崩溃路径相同：这条路径可能已经跑满
    # 几轮、烧掉几十万 token，只发 ErrorEvent 就等于 session_id 与用量
    # 一个都上报不出去。前端两条都处理（error 显横幅、done 显示统计），
    # 两条同时到不会让报告被标成正常——error 事件排在最后，前端据此收尾。
    if not ledger.produced_text:
        # 一个字都没产出 = 失败，不是「完成」
        for event in _fail(tracker, "未产出内容"):
            yield event
        yield ledger.done()
        yield ErrorEvent(
            code="empty_response",
            message="模型未产出内容，请重试",
            retryable=True,
        )
        return

    # 收尾：关掉当前节点，再过 analyst，最后 critic 真做校验（Day 13）。
    #
    # 校验需要**原文全文**而非引用表里的 120 字 excerpt——回查 document_chunks。
    # db 为 None 时（无检索上下文的单测路径）拿不到原文，critic 自行降级。
    sources: dict[int, str] = {}
    if db is not None and collected_refs:
        try:
            sources = await load_source_texts(db, collected_refs)
        except Exception:
            # 校验是可选增强。DB 抖动不能把已经流出去的正文收尾也带走——
            # 那会让 done 永远不发出，用户看到「报告读完突然报错」，
            # 连 token 用量都没了。降级成拿不到原文，critic 自己会跳过。
            logger.warning("critic 取原文失败，本次跳过引用校验", exc_info=True)
            # **必须回滚**，与下面 _persist_report 的兜底同一个理由：读失败
            # 可能已经把事务打成无效，不回滚的话紧接着的落盘 flush 会抛
            # PendingRollbackError，被那边吞成「报告落盘失败」——真正的
            # 根因在这里，而日志会写「报告落盘失败」，排查时被带偏一整轮。
            try:
                await db.rollback()
            except Exception:
                logger.warning("critic 取原文失败后回滚也失败", exc_info=True)

    # 报告落盘。必须在 done 之前：done 帧带 report_id，前端拿它才能在
    # 历史报告里找到这份。落盘失败不能影响流——与上面 critic 取原文同理，
    # DB 抖动不该把已经流出去的正文收尾带走。
    report_id = await _persist_report(
        db=db,
        question=question,
        content="\n".join(report_body),
        ledger=ledger,
        refs=collected_refs,
    )

    # done **先于**校验帧发出。校验是可选增强，而 judge 调用最坏要
    # 120s × 3 次重试 = 6 分钟；挡在 done 前面的话，用户在报告读完
    # 之后还要干等，且 MAX_CONCURRENT_STREAMS 只有 4——几个并发就能
    # 把准入闸门堵死。先把报告与 token 用量交出去，校验随后补一帧。
    yield ledger.with_report_id(report_id).done()

    async for settle_event in _settle(
        tracker, client, "\n".join(report_body), sources
    ):
        yield settle_event


async def _finalize(
    client: AsyncAnthropic,
    ledger: TurnLedger,
    messages: list[dict[str, Any]],
    tracker: NodeTracker,
    out: _FinalizeOut,
) -> AsyncIterator[AgentEvent]:
    """轮数用尽后的强制收尾：关掉工具，再基于已有信息作答。

    产出正文增量（DeltaEvent）。**正文整段与新账本通过 ``out`` 回传**：
    DeltaEvent 的 text 是展示切片，而 ``report_body`` 最后是
    ``"\\n".join(...)``——从切片拼回来的话，每个切片边界都会插一个换行，
    于是落盘的报告在每个逗号处断行，与用户通过 SSE 读到的连续文本对不上
    （2026-10-17 CR 实测复现）。主循环 append 的是 ``result.text`` 整段，
    这里同粒度。

    做成异步生成器而不是「返回事件列表」：强制收尾是用户能看到的最后一段
    正文，攒完再发就又变成「憋一下整段蹦出来」——那正是这个改动要修的问题。

    ``out`` 是一个可变容器而不是返回值：生成器只有一个 yield 通道，
    而这里要同时交回「正文整段」与「新账本」两样东西。塞进事件流当哨兵
    值（靠 isinstance 分流）的老做法不行——那条「最后一项必须是账本」的
    不变式没有任何东西强制，漏写一个 yield 就是静默丢 token。
    """
    final: TurnResult | None = None
    writer_active = False
    async for chunk in _run_turn(client, messages, no_tools):
        if chunk.kind == "text":
            if not writer_active:
                writer_active = True
                for event in tracker.switch(Stage.WRITER):
                    yield event
            yield DeltaEvent(node_id=Stage.WRITER.value, text=chunk.text)
        elif chunk.kind == "reset":
            yield DeltaEvent(node_id=Stage.WRITER.value, text="", reset=True)
        else:
            final = chunk.result

    if final is None:
        raise RuntimeError("强制收尾没有返回结果")
    out.ledger = ledger.record(final)
    out.text = final.text


def _close(tracker: NodeTracker) -> list[NodeEvent]:
    """关掉当前 active 节点；本来就没有 active 时给空列表。

    单独抽出来是因为这个「可能有值、可能没有」的两行模式在主循环里
    出现过四次，每次都要 ``if ... is not None: yield ...``。
    """
    closing = tracker.complete()
    return [] if closing is None else [closing]


def _fail(tracker: NodeTracker, detail: str = "") -> list[NodeEvent]:
    """把当前 active 节点标成失败（而不是「完成」）。

    失败路径必须用它，不能用 :func:`_close`——否则前端 DAG 上每个节点
    都是打勾的「通过」，哪怕整次研究什么都没产出。
    """
    failed = tracker.fail(detail)
    return [] if failed is None else [failed]


async def _persist_report(
    *,
    db: AsyncSession | None,
    question: str,
    content: str,
    ledger: TurnLedger,
    refs: Sequence[Reference],
    persist_timeout: float = PERSIST_TIMEOUT_SECONDS,
) -> int | None:
    """把这一轮的报告写进 ``reports``，返回新记录的 id。

    **任何失败都降级成「没存上」返回 None，绝不向上抛。** 与上面 critic
    取原文是同一个理由：正文已经通过 SSE 流出去了，落盘是附加价值，
    让它把收尾带走等于「报告读完突然报错」，连 token 用量都没了。
    而这里的失败概率比 critic 高得多——要写两张表、算引用计数。

    ``persist_timeout`` 让崩溃路径能用更短的上限：那条路径上用户正盯着
    红色横幅等失败通知，多等几秒是白等（见
    :data:`PERSIST_TIMEOUT_CRASH_SECONDS`）。
    """
    if db is None:
        # 无检索上下文的单测路径（``run_agent`` 的 db 形参默认 None）。
        return None

    report = Report(
        user_id=ledger.user_id,
        question=question,
        content=content,
        session_id=ledger.session_id,
        input_tokens=ledger.input_tokens,
        output_tokens=ledger.output_tokens,
        elapsed_ms=int((time.monotonic() - ledger.started_at) * 1000),
        # 落盘时带上截断标记。崩溃落盘的报告正文不完整——历史列表里
        # 要能把它和完整报告区分开。
        truncated=ledger.truncated,
    )
    try:
        # **必须设超时**：这一步卡在「最后一条 delta」与「done 帧」之间，
        # 而 `run_agent` 是被 `_stream` 的 `async for` 同步消费的，槽位
        # （`MAX_CONCURRENT_STREAMS = 4`）在 `_stream` 的 finally 里释放——
        # await 卡住则 finally 不执行，槽位被**永久**占住，之后每个
        # /research/ask 都 503。切换 Postgres 后 DB 锁等待没有默认上限，
        # 一次长事务就能把 4 个槽位全占死。
        #
        # 超时语义与其它失败一致：降级成「没存上」，正文照常交付。
        async with asyncio.timeout(persist_timeout):
            await _write(db, report, refs, content)
    except Exception:
        # 带 session_id：没有它，日志里只有一句「报告落盘失败」，而落盘
        # 失败是**静默**的（流照常结束、用户拿到完整报告），运维无法把它
        # 和某次具体请求对上——这个功能可以长期完全不工作而没人发现。
        logger.warning(
            "报告落盘失败，本次不记入历史报告",
            extra={"session_id": ledger.session_id, "user_id": ledger.user_id},
            exc_info=True,
        )
        # **失败处理本身也要有上限**。
        #
        # 落盘超时的成因往往就是「DB 卡住/被锁」——同一个坏连接上再
        # await 一次（回滚、查一次确认入库没有）会**再等一次**，而这次
        # 没有上限。而 ``yield ledger.done()`` / ``yield error_event_for(exc)``
        # 都在 :func:`_persist_report` **之后**——用户永远等不到失败横幅，
        # 界面一直转圈，SSE 流挂死。
        #
        # 所以整个失败处理路径共用一个更短的上限：宁可放弃「确认是否
        # 已入库」这个附加价值，也不能让用户等不到失败通知。
        try:
            async with asyncio.timeout(persist_timeout):
                # 必须回滚再返回：session 停在 failed 状态，后续任何查询都会报
                # PendingRollbackError。回滚本身也可能抛（DB 真挂），所以再兜一层。
                try:
                    await db.rollback()
                except Exception:
                    logger.warning("报告落盘失败后回滚也失败", exc_info=True)
                return await _recover_persisted_id(db, report, ledger)
        except TimeoutError:
            logger.warning(
                "报告落盘失败后的清理也超时，放弃确认入库状态",
                extra={"session_id": ledger.session_id, "user_id": ledger.user_id},
            )
            return None
    return report.id


async def _recover_persisted_id(
    db: AsyncSession, report: Report, ledger: TurnLedger
) -> int | None:
    """落盘失败后，确认这行到底进没进库。

    ## 为什么需要这一步

    超时取消的是 ``commit()`` 里的 await。若 COMMIT 已经到达服务端，
    取消不会撤销它——行真的在库里，但我们已经走进 except 分支。此时
    返回 None 会让前端拿不到 ``report_id``，界面上不显示「查看完整报告」，
    而历史报告列表里却多了一条。用户会以为这次没产出。

    反过来，若行没进库（flush 之后 commit 失败，事务已回滚），
    ``report.id`` 虽然有值（主键在 flush 时就分配了），但那行并不存在——
    返回它会指向一条不存在的报告。

    所以查一次，让 ``report_id`` 与库里的事实一致。
    """
    if report.id is None:
        return None
    try:
        existing = await db.get(Report, report.id)
    except Exception:
        logger.warning(
            "报告落盘失败后无法确认是否已入库",
            extra={"session_id": ledger.session_id, "user_id": ledger.user_id},
            exc_info=True,
        )
        return None
    if existing is None:
        return None
    logger.info(
        "报告落盘超时，但行已入库，按已入库处理",
        extra={"session_id": ledger.session_id, "report_id": existing.id},
    )
    return existing.id


async def _write(
    db: AsyncSession,
    report: Report,
    refs: Sequence[Reference],
    content: str,
) -> None:
    """真正执行落盘的三步。单独抽出是为了能给它套一个超时。"""
    db.add(report)
    await db.flush()
    await _record_citations(db, report.id, refs, content)
    await db.commit()


async def _record_citations(
    db: AsyncSession, report_id: int, refs: Sequence[Reference], content: str
) -> None:
    """按 chunk 聚合角标与引用次数，攒进 session 等待 commit。

    同一个 chunk 只写一行，所以复合主键是 ``(report_id, chunk_id)``。
    直接逐条 append 会撞主键约束。

    ``n`` 取该 chunk **第一次**出现时的编号：`ReferenceTable.register`
    对同一 chunk 复用原号，所以同一个 chunk 不会拿到两个不同的 n。

    ``cite_count`` 取 ``content`` 里 ``[n]`` 角标的实际出现次数，而不是
    ``refs`` 的长度——理由见下面那段注释。

    ## 为什么先查存在性

    研究跑 30-60 秒，期间用户可以在另一个标签页删掉被引用的资料，
    `document_chunks` 行随之级联消失。此时若照单插入会撞
    `report_sources.chunk_id` 的外键，**整个事务回滚——连 `reports`
    那行完整正文一起丢**，而用户已经读完了流、只是历史列表里没它。
    一条悬空引用不该让整份报告陪葬，所以这里跳过已消失的 chunk。

    读路径（``gateway/reports.py``）本来也按 inner join 过滤掉了这些，
    写路径必须与它对齐。
    """
    numbers: dict[int, int] = {}
    for ref in refs:
        # **不能按 refs 出现次数累加**：`tools.py` 的 local_search 每轮返回
        # 的是 `context.citations.all`（全量引用表快照，不是增量），所以同
        # 一个 chunk 会在每一轮都出现一次——数出来的是「这个 chunk 在几轮
        # 工具结果里出现过」，与「被引用几次」毫无关系。
        #
        # 真正的引用次数要数正文里的 [n] 角标出现几次，见 `count_markers`。
        numbers.setdefault(ref.chunk_id, ref.n)
    markers = count_citation_markers(content)
    # **只写正文里真出现过的角标**。``collected_refs`` 是全量引用表快照，
    # 模型检索到 10 个切片但正文只写了 [1] 和 [4] 时，其余 8 个从未被引用；
    # 给它们也写一行会让 sources 页的「关联报告 N 篇」虚高（那份资料在报告
    # 里根本没有角标），报告详情页也会多出 8 条 cite_count=0 的幽灵引用。
    counts = {
        chunk_id: markers[n]
        for chunk_id, n in numbers.items()
        if markers.get(n, 0) > 0
    }
    if not counts:
        return

    alive = set(
        (
            await db.execute(
                select(DocumentChunk.id).where(DocumentChunk.id.in_(list(counts)))
            )
        )
        .scalars()
        .all()
    )
    dropped = [cid for cid in counts if cid not in alive]
    if dropped:
        logger.info("落盘时跳过 %d 个已被删除的切片", len(dropped))

    for chunk_id, cite_count in counts.items():
        if chunk_id not in alive:
            continue
        db.add(
            ReportSource(
                report_id=report_id,
                chunk_id=chunk_id,
                n=numbers[chunk_id],
                cite_count=cite_count,
            )
        )


async def _settle(
    tracker: NodeTracker,
    client: AsyncAnthropic,
    report_text: str,
    sources: dict[int, str],
) -> AsyncIterator[AgentEvent]:
    """正常收尾：关掉当前节点 → analyst 占位 → critic 真做校验。

    analyst 仍不做实际工作，只为让 DAG 走完 5 步（用户看到的进度条
    不会停在 writer）。critic 从 Day 13 起是真干活：校验报告里每条
    [n] 是否被它引用的原文支撑。

    ## 事件顺序：节点事件先 yield，校验最后

    反过来的话，LLM 调用慢或失败时用户会看到 DAG 停在半路。

    ## 校验不阻断

    模型已跑完 4-6 轮检索，剔除内容等于让它的工作白费，而把结论标注
    出来让用户自己判断，成本为零。校验失败（LLM 报错、JSON 解析不了）
    一律降级成 ``skipped``，不影响报告本身。
    """
    events: list[AgentEvent] = list(_close(tracker))
    events.append(tracker.activate(Stage.ANALYST))
    events.extend(_close(tracker))
    events.append(tracker.activate(Stage.CRITIC))
    events.extend(_close(tracker))
    for event in events:
        yield event

    report = await verify_citations(client, report_text, sources)
    yield FaithfulnessEvent(
        checked=report.checked,
        supported=report.supported,
        unsupported=[asdict(u) for u in report.unsupported],
        missing=report.missing,
        skipped=report.skipped,
        reason=report.reason,
    )


# ── 单轮请求 ──────────────────────────────────────────────────


async def _run_turn(
    client: AsyncAnthropic,
    messages: list[dict[str, Any]],
    tools: tuple[ToolSpec, ...],
) -> AsyncIterator[TurnChunk]:
    """跑一轮流式请求，**边收边发**。

    ## 为什么必须是生成器而不是「收完再返回」

    原实现是 ``await stream.get_final_message()`` —— 把整轮流攒完再返回，
    主循环随后一次性把正文切好发出去。用户看到的是「憋十几秒，然后整段
    蹦出来」，完全没有打字机效果。

    而上游**本来就是真流式**（实测 2026-10-30，中转站 llmapi.pro）：

    | 正文长度 | 上游到达方式 |
    |---|---|
    | 156 字 | 49 个 text_delta 全在 4.082s 那一刻挤着到 |
    | 1662 字 | 526 个 text_delta，5.0s→13.9s 渐进到达 |

    也就是说长文本的上游逐字吐，我们把增量全丢掉、攒成整段才发。
    改成消费 ``content_block_delta`` 就能拿到真流式。

    ## 正文与工具调用分家

    一轮响应里既有 text 块也有 tool_use 块（实测 thinking → text →
    tool_use 的顺序）。只有 **text 块**的增量能发给用户：tool_use 的
    ``partial_json`` 是工具入参，发出去会漏出模型没打算展示的内容，
    而且前端会把它当正文渲染。

    ## 流被掐断时的整轮重发

    中转站会在 SSE 流消费途中随机断开连接，而 SDK 的 ``max_retries`` 只覆盖
    建连阶段，够不到这里。见 ``llm.is_stream_interrupt`` 的说明。断流后
    **整轮重发**——已发出的正文不能撤，只能整轮重来。

    重发会从头再生成一遍，而上游有随机性（实测同一 prompt 连发 4 次，
    字数 1653/1155/1737/2164 各不相同），没法靠裁剪前缀去重。所以重发前
    发一个 ``reset`` 标记，让前端把这一轮已收到的正文清零——少了它，
    用户会看到同一段正文出现两遍。
    """
    request = _build_turn_request(messages, tools)
    last_exc: BaseException | None = None
    # 这一轮是否已经往用户那里发过正文。断流重发时要靠它决定
    # 要不要发 reset 标记。
    sent_any = False

    for attempt in range(STREAM_INTERRUPT_RETRIES + 1):
        try:
            async for chunk in _stream_turn_once(client, request):
                if chunk.kind == "text":
                    sent_any = True
                yield chunk
            return
        except Exception as exc:
            if not is_stream_interrupt(exc):
                raise
            last_exc = exc
            logger.warning(
                "模型流被中断，第 %d 次重发整轮请求：%s",
                attempt + 1,
                type(exc).__name__,
            )
            # 已经发出去的正文作废——重发会从头再来一遍。
            # 只在**确实发过东西**时才发 reset：纯工具轮断流，
            # 前端正文区是空的，清它没有意义。
            if sent_any:
                yield TurnChunk(kind="reset")
            if attempt < STREAM_INTERRUPT_RETRIES:
                # 指数退避：第 n 次重发等 ``基数 * 2**(n-1)`` 秒（1s → 2s）。
                #
                # 固定间隔的实测问题（2026-11-01）：本机网络层抖动时
                # （Tavily 与 Anthropic 同秒断开），3 次重发挤在同一秒里
                # 全挂在同一个坏窗口内。指数退避把最后一次重发推到
                # 3 秒之后，抖动窗口大概率已过。
                await asyncio.sleep(STREAM_INTERRUPT_BACKOFF_SECONDS * (2**attempt))
            continue

    # 走到这里说明每次尝试都被掐断了。把最后一次的异常原样抛出去——
    # 调用方要靠它判断「流中断」还是别的错误来决定错误文案。
    assert last_exc is not None
    raise last_exc


async def _stream_turn_once(
    client: AsyncAnthropic,
    request: dict[str, Any],
) -> AsyncIterator[TurnChunk]:
    """跑一次流式请求，把上游事件翻译成 ``TurnChunk``。

    产出顺序：正文增量（``kind="text"``，可以有多段）→ 整轮结果
    （``kind="result"``）。``result`` 一定在最后——它是这一轮的收尾
    （usage / stop_reason / tool_calls），调用方靠它记账。
    """
    typewriter = Typewriter()

    async with client.messages.stream(**cast("Any", request)) as stream:
        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            chunk_text = getattr(delta, "text", None)
            # text_delta 才有 text；input_json_delta 是 partial_json——
            # 那是工具入参，不能发给用户（会漏出模型没打算展示的内容）。
            if not isinstance(chunk_text, str):
                continue
            # 切完立刻发。不攒着：攒到最后就退化成「收完再发」，
            # 那正是这个改动要修的问题。
            async for piece in typewriter.feed(chunk_text):
                yield TurnChunk(kind="text", text=piece)

        # 流结束：把尾巴切出来，与前面的片段同一粒度。
        async for piece in typewriter.flush():
            yield TurnChunk(kind="text", text=piece)

        final = await stream.get_final_message()

    yield TurnChunk(kind="result", result=_to_turn_result(final))


def _build_turn_request(
    messages: list[dict[str, Any]],
    tools: tuple[ToolSpec, ...],
) -> dict[str, Any]:
    """拼出一轮请求的载荷。空 tools 时不带 tools 参数。

    ## 为什么必须单独限制 thinking 预算

    不设 ``thinking`` 时模型的扩展思考**没有上限**，会一直膨胀到把
    ``max_tokens`` 吃光——正文一个字都写不出来。实测（2026-10-29，中转站
    llmapi.pro，claude-sonnet-5，max_tokens=4096）：

    | 请求里的 thinking | thinking 消耗 | 正文 |
    |---|---|---|
    | **不设（现状）** | 吃满 4096 | **0 字** ❌ |
    | ``budget_tokens=1024`` | 独立预算 | 6443 字 ✅ |
    | ``budget_tokens=2048`` | 独立预算 | 1523 字 ✅ |
    | ``type=disabled`` | 关掉 | 6456 字 ✅ |

    症状是 ``stop_reason="max_tokens"`` 且正文为空 → 循环跑完 → ``empty_response``：
    「模型未产出内容，请重试」。而重试**没用**——实测连打 5 次全部同样被吃光
    （每次 output_tokens 都是 4096、正文 0 字），它是确定性的，不是偶发。

    所以修复点是**限制 thinking 预算**，而不是加大 ``max_tokens``（那只是让
    思考吃更多）。``max_tokens`` 保持不变：它管总输出上限，thinking 有自己的
    上限，两者不冲突。

    ## 为什么选 2048

    实测三个预算都能出正文，但 1024 时思考空间偏小（模型会更快转向正文、
    深度不足）；3072 时留给正文的余量变少。2048 是「思考够用、正文够写」
    的折中。改这个值前请重跑上表那组实测——**不同问题对思考深度的需求不同**。

    注意 ``stop_reason="max_tokens"`` 在设了 thinking 预算之后**仍然常见**
    （实测每次都是）：它表示「总输出触顶」，在 thinking 有独立预算后**不再
    等于失败**。判据是「有没有正文」，不是 stop_reason。
    """
    settings = get_settings()
    request: dict[str, Any] = {
        "model": settings.anthropic_complex_model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": messages,
        "thinking": {"type": "enabled", "budget_tokens": THINKING_BUDGET_TOKENS},
    }
    if tools:
        request["tools"] = tool_schemas(tools)
    return request


def _to_turn_result(final: Any) -> TurnResult:
    """把 SDK 的 Message 收成 TurnResult。"""
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
    collected_refs: list[Reference],
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
            error_code=outcome.error_code,
        )

        if outcome.references:
            # 累积给 critic 用。ReferenceTable 是 **per-request** 的
            #（在 _build_context 里创建一次，循环外），所以跨轮编号稳定，
            # 正文里的 [n] 与它对得上。tools 返回的是全量表而非增量，
            # 这里累积会有重复，但按 chunk_id 去重后无影响。
            collected_refs.extend(outcome.references)
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
