"""agent 主循环：提问 → 模型决定要不要调工具 → 执行 → 再问 → 出正文。

这是 argus 第一个真正的 agent，只有一个模型循环，没有多智能体编排
（那是 W2 的 LangGraph）。但它已经具备 agent 的三个本质特征：

1. 模型自己决定调哪个工具、调几次（不是代码写死的流程）
2. 工具结果回喂给模型，它能根据结果改变下一步
3. 循环有终止条件与上下文保护，不会无限烧钱

## 本模块只留「多轮之间怎么推进」

这一块原本和节点定义、账本、单轮请求、工具执行挤在一个文件里
（1390 行，超了项目规范的 800 行上限）。现在拆成：

| 模块 | 职责 |
|---|---|
| ``agent.py``（本文件） | 主循环：轮次推进、节点切换、异常与取消路径 |
| ``agent_nodes.py`` | ``Stage`` 枚举、``NodeTracker``（节点生命周期） |
| ``agent_ledger.py`` | ``TurnLedger``（用量与产出记账） |
| ``agent_turn.py`` | 单轮请求：拼请求、发流式、收结果 |
| ``agent_tools.py`` | 工具执行与检索上下文 |
| ``stages.py`` | Supervisor / Analyst 两个节点的实现 |
| ``persistence.py`` | 报告落盘 |

``app.services.agent`` 里**拆分时搬走的那些名字**保持可从原处 import
（见下方 ``__all__``）——拆分不该让调用方改 import。

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
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.services.agent_failures import _handle_cancel, _handle_crash
from app.services.agent_ledger import TurnLedger, _FinalizeOut
from app.services.agent_nodes import NodeTracker, Stage, _close, _fail
from app.services.agent_tools import (
    _build_context,
    _build_user_prompt,
    _run_tools,
)
from app.services.agent_turn import (
    MAX_OUTPUT_TOKENS,
    THINKING_BUDGET_TOKENS,
    TurnChunk,
    TurnResult,
    _build_turn_request,
    _run_turn,
    _stream_turn_once,
    _to_turn_result,
)
from app.services.citation import Reference
from app.services.errors import classify_llm_error
from app.services.faithfulness import (
    load_source_texts,
    verify_citations,
)
from app.services.llm import get_anthropic_client
from app.services.persistence import (
    persist_report,
)
from app.services.stages import (
    Evidence,
    _AnalystOut,
    _run_analyst,
    analyze_evidence,
    plan_subtasks,
)
from app.services.stream import (
    AgentEvent,
    DeltaEvent,
    ErrorEvent,
    FaithfulnessEvent,
)
from app.services.tools import ToolSpec, available_tools

# ── 公开接口的再导出 ─────────────────────────────────────────
#
# 这些名字**原本定义在本文件里**，现在拆到了 ``agent_turn`` /
# ``agent_nodes`` / ``agent_ledger``。但外部（网关、测试）一直按
# ``from app.services.agent import TurnChunk, ...`` 取它们——
# 拆分不该让调用方改 import（改了就是「顺手改无关的地方」）。
#
# 所以在这里显式再导出。ruff 的 F401 对「import 后未使用」会报错，
# 用 ``__all__`` 声明它们是被有意再导出的。
#
# ## 范围：只再导出**本项目真正用到的**
#
# 拆分前的 agent.py 因为 import 了 Report / DocumentChunk / DoneEvent
# 等一堆东西，那些名字**顺带**也能从 ``app.services.agent`` 拿到。
# 它们不是有意的公开接口（没人写「from app.services.agent import
# DocumentChunk」），而是被 import 语句顺带暴露的。
#
# 全量再导出它们会把「这个模块的公开面」撑到 30+ 个名字，其中大半与
# 「agent 主循环」无关——那才是真正的契约混乱。所以这里只再导出**拆分
# 时真正搬走的那几个**，以及本模块直接使用的。
#
# 真有外部代码依赖了某个顺带暴露的名字（CR 实测：仓库内没有），改用
# 那个名字自己的模块 import 即可——那才是它该待的地方。

__all__ = [
    "MAX_OUTPUT_TOKENS",
    "MAX_TURNS",
    "THINKING_BUDGET_TOKENS",
    "Evidence",
    "NodeTracker",
    "Stage",
    "TurnChunk",
    "TurnLedger",
    "TurnResult",
    "_build_turn_request",
    "_run_analyst",
    "_run_turn",
    "_stream_turn_once",
    "_to_turn_result",
    "analyze_evidence",
    "plan_subtasks",
    "run_agent",
]

# ── 常量 ──────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

MAX_TURNS = 6  # 循环轮数上限。单轮经中转站实测数秒，6 轮约 30-60 秒

# 最后一轮强制收尾时传进去的空工具列表——模型看到空列表就不会再要工具。
no_tools: tuple[ToolSpec, ...] = ()

# 强制收尾指令。措辞必须说「轮」而不是「检索次数」：一轮里模型可以并行发
# 多个 tool_use，6 轮完全可能对应 15 次检索。告诉模型「你已达到 6 次检索
# 上限」会误导它自己判断证据够不够，进而在答案里加「检索不足，可信度有限」
# 之类的免责声明。
FINALIZE_INSTRUCTION = (
    "你已达到本轮研究的调用轮数上限（共 {} 轮）。请基于已有信息直接给出最终答案，不要再调用工具。"
)


async def run_agent(
    question: str,
    *,
    user_id: int,
    db: AsyncSession | None = None,
    vec_engine: AsyncEngine | None = None,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
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

    yield tracker.activate(Stage.SUPERVISOR)
    context = _build_context(user_id, db, vec_engine, session_maker)
    # ``has_local`` 指的是「能不能做本地检索」——那要**向量引擎**，
    # 不只是 db。联网搜索结果落成可引用来源只需要 db，所以「有 context」
    # 与「能本地检索」是两件事（见 ``_build_context`` 的说明）。
    has_local = context is not None and context.vec_engine is not None
    tools = available_tools(has_local=has_local)
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

    # **Supervisor 真正拆解问题**。
    #
    # 以前这里只做本地拼 prompt（毫秒级），DAG 上却写着「正在拆解问题
    # 意图」——用户看到的是一个假的执行图。现在它真的调一次模型产出
    # 检索子任务，拆解结果进 Researcher 的提示。
    #
    # 拆解失败不阻断（降级成「没有拆解结果」，模型自己决定搜什么），
    # 理由见 ``services/stages.py`` 的模块说明。
    #
    # ## 为什么单独包一层 CancelledError
    #
    # 这一步是**第一次真正的模型调用**（SDK 默认 timeout 120s × 2 次
    # 重试），而它在主循环的 ``try`` **之外**——那个 except 块捕不到它。
    #
    # 实测（2026-11-08）：把 ``plan_subtasks`` 打桩成 ``await
    # asyncio.sleep(10)`` 然后取消，产出是「只有一个 supervisor active
    # 帧」——**没有 done、没有 error、没有落盘**。前端 runState 停在
    # running，用户看到转圈不结束。
    #
    # 改动前 Supervisor 是本地拼 prompt（毫秒级），取消窗口几乎为零，
    # 这个洞是新开出来的。所以这里要有自己的取消分支：落盘 + 发 done +
    # 重抛（与主循环的取消分支同语义）。
    try:
        plan = await plan_subtasks(client, question, has_local=has_local)
    except asyncio.CancelledError:
        logger.info("研究在拆解阶段被取消")
        ledger = ledger.mark_truncated()
        # **不落盘**——Supervisor 阶段还没有正文产出，无可落盘。
        #
        # 这不是「忘了」，而是这个阶段本来就没有内容可存。将来 Supervisor
        # 若产出正文（它现在只产出子任务列表），这里要改成落盘——否则
        # 那部分内容会静默丢失。
        yield ledger.done()
        raise
    ledger = ledger.record_stage_usage(plan.input_tokens, plan.output_tokens)
    if plan.subtasks:
        tracker.set_note(Stage.SUPERVISOR, f"拆解出 {len(plan.subtasks)} 个子任务")

    prompt = _build_user_prompt(question, tools, has_local, plan=plan)

    for event in _close(tracker):
        yield event

    yield tracker.activate(Stage.RESEARCHER)

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    # 每轮的 tool_result 累积在局部变量里，不放模块级全局——SSE 并发时
    # 全局变量会让两个用户的搜索结果互相污染。
    tool_results: list[dict[str, Any]] = []

    # **已经核对过的证据的键**。Analyst 只核对没见过的那些。
    #
    # 键的形状：``("ref", chunk_id)`` 是用户资料里的切片，
    # ``("web", (url, 摘要))`` 是公开来源。两种来源不会撞车。
    seen_evidence_keys: set[tuple[str, object]] = set()

    # Analyst 节点是否激活过。
    #
    # 模型一次都没调工具时没有证据可核对，analyst 不会跑——那时
    # ``_settle`` 补一次空跑（见那里的说明）。
    analyst_ran = False

    # **当前这一轮流出的正文**。边收边攒，不是等 result.text ——
    # 用户已经看到的正文必须能在「中途被取消」时落盘。
    #
    # 早先只从 `result.text` 攒，于是「取消发生在一轮中途」时，用户看到
    # 的那半截正文**不在** report_body 里 —— 落盘出来是空的。那是真 bug：
    # 用户明明看到了一半的报告，历史里却找不到。
    #
    # 放在循环**外面**是因为取消分支（``except asyncio.CancelledError``）
    # 要读它 —— 那是循环外的 except 块，看不到循环内的局部变量。
    current_turn_text: list[str] = []

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
            current_turn_text = []
            async for chunk in _run_turn(client, messages, tools):
                if chunk.kind == "text":
                    if not writer_active:
                        writer_active = True
                        for event in tracker.switch(Stage.WRITER):
                            yield event
                    current_turn_text.append(chunk.text)
                    yield DeltaEvent(node_id=Stage.WRITER.value, text=chunk.text)
                elif chunk.kind == "reset":
                    # 流被掐断后整轮重发：已发的正文作废，前端清零后重收。
                    # 本轮攒的也要作废 —— 否则重发的那份会跟它叠在一起。
                    current_turn_text.clear()
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
            if current_turn_text:
                report_body.append("".join(current_turn_text))
            elif result.text:
                # 没有流式片段（理论上不该发生——真流式下 text 一定先于
                # result 到达）。留着这个回落：**宁可内容重复也不要丢**。
                report_body.append(result.text)
            # 本轮已收尾，清空「当前轮」——下一轮会重新填。
            current_turn_text = []

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

            async for tool_event in _run_tools(
                result.tool_calls, tool_results, context, collected_refs
            ):
                yield tool_event

            # **Analyst 真正交叉核对证据**。
            #
            # 放在工具执行之后、正文之前：它要读的是**已经检索到的**
            # 证据，放在检索之前没东西可核对；放在正文之后就成了事后
            # 诸葛亮，而正文是模型的最终产物，核对结论来不及影响它。
            #
            # 核对结论进下一轮的上下文，Writer 写正文时能看到「这几条
            # 证据互相矛盾」——不能把打架的证据并列成两个事实。
            analyst_out = _AnalystOut()
            async for analyst_event in _run_analyst(
                client,
                tracker,
                collected_refs,
                seen_evidence_keys,
                analyst_out,
            ):
                yield analyst_event
            analyst_ran = analyst_ran or analyst_out.ran
            ledger = ledger.record_stage_usage(analyst_out.input_tokens, analyst_out.output_tokens)

            # Anthropic 协议：同一轮的多个 tool_result 必须打包进一条
            # user 消息，逐条 append 成多条会被拒。
            # 重新绑定而不是 .clear()——messages 里存的是这个列表的引用，
            # clear 会把已 append 的 tool_result 一起清空。
            #
            # **核对结论必须进这同一条消息**（不能单独 append 一条 user
            # 消息）：那会构造出连续同角色消息，上游会拒收整个请求。
            # 消息里 tool_result 在前、文本在后——这是合法的混排顺序。
            user_blocks: list[dict[str, Any]] = list(tool_results)
            if analyst_out.text:
                user_blocks.append({"type": "text", "text": analyst_out.text})
            messages.append({"role": "user", "content": user_blocks})
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
    except asyncio.CancelledError:
        # **被取消**（用户点了「新建会话」，或重问时替换上一轮）。
        #
        # `CancelledError` 继承 `BaseException` 而不是 `Exception`——
        # 所以下面那个 `except Exception` 捕不到它，会直接往上抛。
        async for cancel_event in _handle_cancel(
            db=db,
            question=question,
            ledger=ledger,
            report_body=report_body,
            current_turn_text=current_turn_text,
            collected_refs=collected_refs,
        ):
            yield cancel_event
        # 重新抛出，保持「这个任务确实被取消」的语义 ——
        # 吞掉它会让 `task.cancel()` 变成「正常结束」。
        raise
    except Exception as exc:
        async for crash_event in _handle_crash(
            db=db,
            question=question,
            ledger=ledger,
            report_body=report_body,
            collected_refs=collected_refs,
            tracker=tracker,
            exc=exc,
        ):
            yield crash_event
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
            # **必须回滚**，与下面 persist_report 的兜底同一个理由：读失败
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
    report_id = await persist_report(
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
        tracker, client, "\n".join(report_body), sources, analyst_ran=analyst_ran
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


async def _settle(
    tracker: NodeTracker,
    client: AsyncAnthropic,
    report_text: str,
    sources: dict[int, str],
    *,
    analyst_ran: bool,
) -> AsyncIterator[AgentEvent]:
    """正常收尾：analyst 兜底 → critic 真做校验。

    ## analyst 兜底

    analyst 现在是**真干活**的（核对检索到的证据，见
    ``services/stages.py``），它在主循环里跑——检索到证据之后就核对，
    结论进下一轮上下文，Writer 写正文时能看到。

    但**模型可能一次都没调工具**（它直接回答了）。那时没有证据可核对，
    analyst 从未激活，DAG 上它会永远停在 pending。这里补一次「空跑」，
    让 DAG 走完 5 步，并如实说明「没有证据可核对」——不是编一个耗时。

    ## critic 的耗时必须包含校验本身

    这是这轮修的**真 bug**：以前 ``activate(CRITIC)`` 后面紧跟
    ``complete(CRITIC)``，然后才调 ``verify_citations``。于是 DAG 上
    critic 显示 0.0s，而校验实际跑了最长 120s × 3 次重试 = 6 分钟。

    现在校验**在 critic 节点窗口内部**跑完才关节点。用户等校验的那段
    时间里，DAG 停在「审阅智能体 · 正在校验引用」——而不是一个空白面板
    配一个 0.0s 的节点。

    ## 校验不阻断

    模型已跑完 4-6 轮检索，剔除内容等于让它的工作白费，而把结论标注
    出来让用户自己判断，成本为零。校验失败（LLM 报错、JSON 解析不了）
    一律降级成 ``skipped``，不影响报告本身。
    """
    if not analyst_ran:
        for event in _close(tracker):
            yield event
        yield tracker.activate(Stage.ANALYST)
        tracker.set_note(Stage.ANALYST, "没有检索证据可核对")
        for event in _close(tracker):
            yield event

    for event in _close(tracker):
        yield event
    yield tracker.activate(Stage.CRITIC)

    # **校验在 critic 节点窗口内部**。见上面的说明。
    report = await verify_citations(client, report_text, sources)

    if report.skipped:
        tracker.set_note(
            Stage.CRITIC, f"跳过校验：{report.reason}" if report.reason else "跳过校验"
        )
    else:
        tracker.set_note(
            Stage.CRITIC,
            f"核对 {report.checked} 条引用，{report.supported} 条有据支撑",
        )
    for event in _close(tracker):
        yield event

    yield FaithfulnessEvent(
        checked=report.checked,
        supported=report.supported,
        unsupported=[asdict(u) for u in report.unsupported],
        missing=report.missing,
        skipped=report.skipped,
        reason=report.reason,
    )
