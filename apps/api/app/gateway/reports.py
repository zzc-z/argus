"""研究报告路由。

只有读，没有写——报告由 ``run_agent`` 在跑完时落盘（那时正文、引用、
token 用量都在手上）。这一层不提供「手动保存」或「编辑」，那属于 W3 的
协作场景。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.gateway.deps import CurrentUser
from app.models.report import Report, ReportSource
from app.models.source import DocumentChunk, Source
from app.schemas.report import (
    ReportCitationV,
    ReportDetailV,
    ReportListResponse,
    ReportSummaryV,
)
from app.services.citation import EXCERPT_CHARS

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

# 与 research.py / sources.py 同款：局部声明而非放 deps。
DbSession = Annotated[AsyncSession, Depends(get_session)]

# 上限 100 是给「一次性拿完」的常见用法留的余地。真要翻更多页，
# 前端该用 limit/offset 逐页取，而不是把这个上限往上调。
MAX_PAGE_SIZE = 100


@router.get("", response_model=ReportListResponse, summary="列出我的报告")
async def list_reports(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReportListResponse:
    """按创建时间倒序返回报告摘要，不含正文。

    ``total`` 单独 count：``items`` 是分页后的那一段，拿 ``len(items)``
    当总数会让最后一页的页码算错。
    """
    total = await db.scalar(
        select(func.count()).select_from(Report).where(Report.user_id == user.id)
    )
    rows = (
        await db.scalars(
            select(Report)
            .where(Report.user_id == user.id)
            .order_by(Report.created_at.desc(), Report.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ReportListResponse(
        items=[ReportSummaryV.model_validate(r) for r in rows],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/{report_id}", response_model=ReportDetailV, summary="取单份报告")
async def read_report(report_id: int, user: CurrentUser, db: DbSession) -> ReportDetailV:
    """返回报告正文与引用表。仅限报告所有者。"""
    report = await _owned(db, report_id, user.id)
    citations = await _load_citations(db, report.id)
    return ReportDetailV(
        **ReportSummaryV.model_validate(report).model_dump(),
        content=report.content,
        citations=citations,
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除报告")
async def delete_report(report_id: int, user: CurrentUser, db: DbSession) -> None:
    """删报告。引用记录靠 CASCADE 跟着走。

    删了不影响私有资料——``report_sources`` 是从报告指向切片，
    不是切片指向报告。
    """
    await db.delete(await _owned(db, report_id, user.id))
    await db.commit()


# ── 内部 ───────────────────────────────────────────────────
async def _owned(db: AsyncSession, report_id: int, user_id: int) -> Report:
    """取报告并校验归属。找不到或不是本人的，一律 404。

    不区分「不存在」和「不是你的」——报 403 等于确认了这个 id 存在，
    是信息泄露。理由与 ``app/gateway/sources.py`` 的同名内部函数一致。
    """
    report = await Report.find_owned(db, report_id, user_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    return report


async def _load_citations(db: AsyncSession, report_id: int) -> list[ReportCitationV]:
    """回查引用表：编号从 ``report_sources`` 取，正文与标题从切片/资料取。

    **只按 chunk_id 查，不按 report_id 连带关系取**——``Report.sources``
    是 ``lazy="raise"``，碰它就报错。批量的那条走显式查询，与
    ``app/models/source.py`` 里 Source.chunks 的处理方式一致。
    """
    rows = (
        await db.execute(
            select(
                ReportSource.n,
                ReportSource.cite_count,
                DocumentChunk.id,
                DocumentChunk.chunk_index,
                DocumentChunk.page,
                DocumentChunk.content,
                DocumentChunk.source_id,
                Source.title,
            )
            .join(DocumentChunk, DocumentChunk.id == ReportSource.chunk_id)
            .join(Source, Source.id == DocumentChunk.source_id)
            .where(ReportSource.report_id == report_id)
            .order_by(ReportSource.n)
        )
    ).all()

    # 切片可能已被删（资料被删 → CASCADE 掉了 chunk → 这里就没有行）。
    # 那种情况这条引用自然不出现在列表里，而不是拿半条数据糊出去。
    return [
        ReportCitationV(
            n=n,
            chunk_id=chunk_id,
            source_id=source_id,
            chunk_index=chunk_index,
            page=page,
            title=title,
            excerpt=_excerpt(content),
            cite_count=cite_count,
        )
        for (
            n,
            cite_count,
            chunk_id,
            chunk_index,
            page,
            content,
            source_id,
            title,
        ) in rows
    ]


def _excerpt(content: str) -> str:
    """角标 tooltip 用的 120 字前缀。

    与 ``app/services/citation.py`` 的私有 ``_excerpt`` 同一套规则——
    包括末尾那个 ``…``。这里重新写一份而不是 import 私有名，是为了
    避免跨模块依赖下划线前缀的内部函数；两条规则若要改，得一起改。
    """
    if len(content) <= EXCERPT_CHARS:
        return content
    return content[:EXCERPT_CHARS] + "…"
