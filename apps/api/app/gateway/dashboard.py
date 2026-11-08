"""Dashboard 概览与系统状态路由。

## 为什么有这两个接口

`/dashboard` 与 `/settings` 原先是整页 mock——KPI 数字、活动流、供应商
状态、向量索引的「89 / 120」全是编的。页面上看不出来是假数据，但用户
会照着这些数字做判断。

这两个接口把**真能从库里读出来的**那部分接回去：

- ``GET /api/v1/dashboard`` —— 报告数、资料数、切片数、token 用量、
  最近报告。全部是 ``reports`` / ``sources`` 的聚合。
- ``GET /api/v1/settings/status`` —— 外部能力的配置状态与向量索引规模。

**读不到的不给。** 没有 topics 表就没有「订阅数」，没有 notifications 表
就没有「未读数」。响应里不含这些字段，前端也不该画它们。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.gateway.deps import CurrentUser
from app.models.report import Report
from app.models.source import DocumentChunk, Source
from app.schemas.dashboard import (
    DashboardResponse,
    ProviderStatusV,
    SettingsStatusResponse,
    VectorIndexV,
)
from app.schemas.report import ReportSummaryV
from app.services.vectorstore import count_embeddings

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

# 「继续研究」列表显示几篇。5 篇是侧栏一屏能放下的量。
RECENT_REPORTS_LIMIT = 5


@router.get("/dashboard", response_model=DashboardResponse, summary="Dashboard 概览")
async def read_dashboard(user: CurrentUser, db: DbSession) -> DashboardResponse:
    """我的研究概览。

    **全部数字都是当前用户的**——按 user_id 过滤，不跨账号统计。
    """
    report_count = (
        await db.scalar(select(func.count()).select_from(Report).where(Report.user_id == user.id))
    ) or 0
    source_count = (
        # **排除公开来源**（``source_type="web"``）——它们是联网搜索的
        # 结果，不是用户上传的资料。用户看到「我的资料 6 份」而实际只
        # 上传过 1 份，那个数是假的。
        await db.scalar(select(func.count()).select_from(Source).where(Source.owned_clause(user.id)))
    ) or 0

    # 切片数**直接 count(document_chunks)**，不用 sources.chunk_count 求和。
    #
    # sources.chunk_count 是摄取时写进去的**缓存字段**——资料删了但缓存
    # 没同步、或摄取中途失败留下半截数据时，它与实际切片行数对不上。
    # 概览数字宁可慢一次 join，也不能显示一个错的数。
    chunk_total = (
        await db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Source, Source.id == DocumentChunk.source_id)
            .where(Source.owned_clause(user.id))
        )
    ) or 0

    token_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Report.input_tokens), 0),
                func.coalesce(func.sum(Report.output_tokens), 0),
            ).where(Report.user_id == user.id)
        )
    ).one()

    recent = (
        await db.scalars(
            select(Report)
            .where(Report.user_id == user.id)
            .order_by(Report.created_at.desc(), Report.id.desc())
            .limit(RECENT_REPORTS_LIMIT)
        )
    ).all()

    return DashboardResponse(
        report_count=report_count,
        source_count=source_count,
        chunk_count=int(chunk_total),
        total_input_tokens=int(token_row[0]),
        total_output_tokens=int(token_row[1]),
        recent_reports=[ReportSummaryV.model_validate(r) for r in recent],
        latest_report_at=recent[0].created_at if recent else None,
    )


@router.get(
    "/settings/status",
    response_model=SettingsStatusResponse,
    summary="系统状态（供应商配置 + 向量索引）",
)
async def read_settings_status(user: CurrentUser, db: DbSession) -> SettingsStatusResponse:
    """外部能力的配置状态与向量索引规模。

    **只说「配了没有」，不返回任何密钥内容**——``detail`` 是给人看的一句话。

    鉴权沿用 CurrentUser：这个接口要按 user_id 统计向量索引规模（别人的
    资料不该出现在你的设置页里）。配置状态本身是全局的，但混在一个响应里
    就不再拆了。
    """
    source_count = (
        # **排除公开来源**（``source_type="web"``）——它们是联网搜索的
        # 结果，不是用户上传的资料。用户看到「我的资料 6 份」而实际只
        # 上传过 1 份，那个数是假的。
        await db.scalar(select(func.count()).select_from(Source).where(Source.owned_clause(user.id)))
    ) or 0
    chunk_count = (
        await db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Source, Source.id == DocumentChunk.source_id)
            .where(Source.owned_clause(user.id))
        )
    ) or 0

    # 已向量化的切片数——**按 user_id 过滤**，与上面的 chunk_count 同口径。
    #
    # vec0 虚表没有 user_id 列（主键就是 chunk_id），所以要 join 一条：
    # 影子表 → document_chunks → sources。早先的版本直接数全库，页面上
    # 就出现「已向量化 7398 > 检索切片 7388」这种自相矛盾的数字——两个数
    # 不同口径，用户没法解读。宁可多一次 join 也要口径一致。
    try:
        embedded = await count_embeddings(db, user.id)
    except Exception:
        # 向量库不可用（表不存在）不该让整个状态接口 500。
        # 保守地报 0——「0 个已嵌入」是安全的下界。
        embedded = 0

    return SettingsStatusResponse(
        providers=_provider_statuses(),
        vector_index=VectorIndexV(
            source_count=source_count,
            chunk_count=int(chunk_count),
            embedded_chunk_count=embedded,
        ),
    )


def _provider_statuses() -> list[ProviderStatusV]:
    """列出各外部能力的配置状态。

    **只判断「有没有配」，不碰密钥内容。** 密钥是 SecretStr，取它就够
    判空；把它写进响应是安全事故。
    """
    settings = get_settings()

    anthropic_ok = bool(
        settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value()
    )
    tavily_ok = bool(settings.tavily_api_key and settings.tavily_api_key.get_secret_value())
    embedding_ok = bool(
        settings.embedding_api_key and settings.embedding_api_key.get_secret_value()
    )

    anthropic_detail = "已配置"
    if not anthropic_ok:
        anthropic_detail = "未配置 ANTHROPIC_API_KEY"
    elif settings.anthropic_base_url:
        anthropic_detail = f"已配置（经中转站 {settings.anthropic_base_url}）"

    return [
        ProviderStatusV(
            id="anthropic",
            name="模型服务 (Anthropic)",
            configured=anthropic_ok,
            detail=anthropic_detail,
        ),
        ProviderStatusV(
            id="tavily",
            name="联网搜索 (Tavily)",
            configured=tavily_ok,
            detail="已配置" if tavily_ok else "未配置 TAVILY_API_KEY",
        ),
        ProviderStatusV(
            id="embedding",
            name="向量嵌入 (Embedding)",
            configured=embedding_ok,
            detail="已配置" if embedding_ok else "未配置 EMBEDDING_API_KEY",
        ),
    ]
