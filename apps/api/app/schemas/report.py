"""研究报告相关的响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportCitationV(BaseModel):
    """报告引用的一个切片。

    字段名与 ``apps/web/lib/api/sse.ts`` 的 ``ReferenceV`` **基本**对齐
    （``n`` / ``chunk_id`` / ``source_id`` / ``chunk_index`` / ``page`` /
    ``title`` / ``excerpt``），少一个 ``recall``——那是检索召回来源
    （'向量+BM25' / '向量' / 'BM25'），只在那次流里有意义，历史报告里
    没有对应的现场。前端复用角标渲染时要单独处理这个字段的缺失。

    ``title`` / ``excerpt`` 不在 ``report_sources`` 表里：那份 title 是
    资料名、excerpt 是切片前 120 字，都还在 ``document_chunks`` /
    ``sources`` 上。这里按 chunk_id 回查一次，避免落盘时抄一份——资料
    改名后历史报告会跟着变，那是对的。
    """

    n: int
    chunk_id: int
    source_id: int
    chunk_index: int
    page: int | None
    title: str
    excerpt: str
    cite_count: int = Field(description="该切片在这份报告里被引用了几次")


class ReportSummaryV(BaseModel):
    """报告摘要。列表页用——不含正文，避免长报告把列表撑爆。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    session_id: str
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    created_at: datetime
    # 这份报告是否被截断。截断的报告正文不完整——通常是流程中途失败
    # 或撞到了轮次上限。列表页要标出来，否则读者会当成完整报告。
    truncated: bool = False
    # 这份报告引用了多少个**切片**（不是资料数）。列表页要显示「N 条引用」。
    #
    # 不在 ORM 上：它要从 ``report_sources`` 数出来，而那个表与 reports
    # 是多对多。要么在列表查询里带子查询，要么多打一次查询——列表页
    # 一次要渲染 20 行，逐行查就是 N+1。
    citation_count: int = 0


class ReportDetailV(ReportSummaryV):
    """报告详情。多了正文与引用表。"""

    content: str
    citations: list[ReportCitationV]


class ReportListResponse(BaseModel):
    """报告列表。``total`` 是全量计数，供前端算页码。"""

    items: list[ReportSummaryV]
    total: int
    limit: int
    offset: int


__all__ = [
    "ReportCitationV",
    "ReportDetailV",
    "ReportListResponse",
    "ReportSummaryV",
]
