"""工具执行与检索上下文。

## 为什么独立成模块

主循环只管「什么时候调工具」，这一层管「怎么调、调完把什么交给模型」。
两者各自都够长，合在一个文件里会超 800 行。

## 一条硬约束

``execute_tool`` 保证不抛异常——工具失败会变成 ok=False 的 tool_result
喂回模型，让它自己决定重试还是换路径，用户至少还能拿到答案。
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.source import Source
from app.services.citation import Reference, ReferenceTable
from app.services.stages import Plan
from app.services.stream import AgentEvent, ReferenceEvent, ToolCallEvent
from app.services.tools import ToolContext, ToolSpec, execute_tool

logger = logging.getLogger(__name__)


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
            # （在 _build_context 里创建一次，循环外），所以跨轮编号稳定，
            # 正文里的 [n] 与它对得上。
            #
            # local_search 返回的是**全量表**（累积会有重复，按 chunk_id
            # 去重后无影响）；联网搜索返回的是**本次新增**的那些——
            # 两种来源都要累积，落盘的 report_sources 才知道有哪些角标
            # 该记。
            collected_refs.extend(outcome.references)
            # 公开来源有 URL（``Source.url``）——前端角标 tooltip 要能
            # 显示它。用户上传的资料没有 URL，传空串。
            urls = await _source_urls(context, {ref.source_id for ref in outcome.references})
            yield ReferenceEvent(
                references=[
                    ref.to_citation(url=urls.get(ref.source_id, "")) for ref in outcome.references
                ],
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
    session_maker: async_sessionmaker[AsyncSession] | None = None,
) -> ToolContext | None:
    """能拿到数据库就建上下文，否则返回 None（对应「无检索上下文」）。

    每次调用新建一个 ``ReferenceTable``：编号是**每个请求独立**的，
    共用会让两个并发请求的 ``[1]`` 指向不同切片。

    ## 为什么 ``vec_engine`` 可以是 None

    只有 ``local_search`` 需要向量引擎。联网搜索结果落成可引用来源
    （见 ``app/services/web_sources.py``）只需要 ``db``——而把
    ``vec_engine`` 设成必填的话，「没有向量引擎」会连累「联网来源不占
    角标号」，那两件事没关系。

    缺向量引擎时 ``local_search`` 自己报「没有检索上下文」，不会崩。

    ``session_maker`` 传给公开来源用——它们要另开短事务落库，不能占着
    主事务的 SQLite 写锁跑完整个研究（见 ``ToolContext.session_maker``）。
    """
    if db is None:
        return None
    return ToolContext(
        db=db,
        vec_engine=vec_engine,
        user_id=user_id,
        citations=ReferenceTable(),
        session_maker=session_maker,
    )


def _build_user_prompt(
    question: str,
    tools: tuple[ToolSpec, ...],
    has_local: bool,
    plan: Plan | None = None,
) -> str:
    """拼用户提示词。工具不可用时明说，避免模型编造引用。

    不说的话模型会按「应该联网」的常识去编造引用——用户分不清哪些是
    查到的、哪些是模型想象的。

    ``plan`` 是 Supervisor 的拆解结果。它的子任务拼在**末尾**而不是
    开头：问题原文必须是模型看到的第一样东西，否则它会把「检索建议」
    当成用户的要求来回答。
    """
    names = {spec.name for spec in tools}
    notes: list[str] = []
    if "tavily_search" not in names:
        notes.append("未配置联网搜索工具")
    if not has_local:
        notes.append("无法检索你的私有资料")
    body = question
    if notes:
        body = (
            f"{question}\n\n（注意：当前环境{'、'.join(notes)}，"
            "请基于已有知识回答，并说明信息可能不完整。）"
        )
    if plan is not None:
        body += plan.as_prompt_line()
    return body


async def _source_urls(
    context: ToolContext | None,
    source_ids: set[int],
) -> dict[int, str]:
    """取一批来源的 URL。查不到就不给。

    公开来源（``source_type="web"``）有 URL，用户上传的资料没有。

    **一条查询**而不是每个 source_id 查一次——一轮研究最多 10 条引用，
    逐个查就是 10 次 SELECT（N+1）。

    查不到不是错误——引用表里的 chunk 可能来自已被删除的资料。
    """
    if context is None or not source_ids:
        return {}
    try:
        rows = (
            await context.db.execute(select(Source.id, Source.url).where(Source.id.in_(source_ids)))
        ).all()
    except Exception:
        logger.warning("取来源 URL 失败", exc_info=True)
        return {}
    return {row_id: url or "" for row_id, url in rows}
