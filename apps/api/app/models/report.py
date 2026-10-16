"""研究报告及其引用到的资料。

一张研究跑完后落盘，便于「历史报告」列表与「这份报告引用了哪些私有资料」
的反查。关系存在 ``report_sources`` 而不是 ``Report.sources``：

    reports
      └ report_sources   报告 ↔ 被引用的切片
             └ sources

## 为什么引用要落到 chunk 而不是只记 source

**为了让 ``n`` 有地方存。** 报告正文里写死了 ``[1]``、``[2]`` 这样的角标，
读者点角标要能落到具体切片；只存 ``(report_id, source_id)`` 的话，
角标 1 和角标 2 会指向同一份资料、无法区分。

**不是为了 sources 页那个「关联报告 N 篇」计数**——那个数按**报告去重**，
存 chunk 级和存 source 级算出来完全一样（一份报告引同一资料的 5 个切片，
两种存法都是 1 篇）。所以那条列并不构成「必须存 chunk」的理由。

``cite_count`` 是这个 chunk 上的角标在正文里出现的次数（由
``citation.count_citation_markers`` 数 `[n]` 得到）。详情页当前按 ``n``
排序展示，不按它排；它是给「这条引用有多重要」留的口子，不参与上面那个
「N 篇」的去重。

向量与切片正文都不在这里——见 ``app/models/source.py`` 顶部的说明。
"""

from datetime import datetime
from typing import Self

from sqlalchemy import ForeignKey, Index, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime


class Report(Base):
    """一次研究跑完产出的报告。"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 提问原文。正文只是答案，问句往往才是这份报告的标题。
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # 模型产出的最终正文。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 与 DoneEvent.session_id 同源——一次 SSE 流对应一条 reports 记录。
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
    )

    # 父侧一律 lazy="raise"：列表页只读 question/content，不需要连带拉出
    # 引用关系（那是 sources 页要的，且要走 ReportSource 的显式查询）。
    # 理由同 app/models/source.py 里 Source.chunks 的注释。
    sources: Mapped[list["ReportSource"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_reports_user_id", "user_id"),
        # 同一 session 只能有一份报告。真正的约束是「一次研究一条」，
        # 而 session_id 由 run_agent 内部现生成 uuid4，重放请求必然拿到
        # 新 id——所以这条索引当前拦不住任何真实场景。它保留是因为
        # 「同一 session 只落一条」本来就是不变式，写进 schema 比留给
        # 代码里的自觉可靠；真要改成「重放复用同一个 session」时它立刻生效。
        Index("ux_reports_session_id", "session_id", unique=True),
    )

    @classmethod
    async def find_owned(cls, session: AsyncSession, report_id: int, user_id: int) -> Self | None:
        """按 id 查报告，**并校验归属**。

        user_id 不可省，理由与 ``Source.find_owned`` 相同：只按 id 查等于
        没有鉴权，别人的 report_id 照样能读。
        """
        stmt = select(cls).where(cls.id == report_id, cls.user_id == user_id)
        return await session.scalar(stmt)


class ReportSource(Base):
    """报告引用到的一个切片。"""

    __tablename__ = "report_sources"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 角标编号。正文里写死了 `[n]`，不存它就没法把角标还原成切片——
    # 报告详情页会拿到一串点不开的编号。
    #
    # 可由 chunk_id 唯一确定：`ReferenceTable.register` 对同一个 chunk
    # 复用原号（见 citation.py 的 register docstring），所以一个 chunk
    # 在一次研究里只会分到一个 n。
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    # 该切片在这份报告里被引用了几次。同一 chunk 被多句引用时计数 > 1——
    # 所以复合主键是 (report_id, chunk_id) 而不是再加 source_id。
    cite_count: Mapped[int] = mapped_column(Integer, default=1)

    report: Mapped[Report] = relationship(back_populates="sources", lazy="raise")

    __table_args__ = (Index("ix_report_sources_chunk_id", "chunk_id"),)
