"""研究资料源与其语义切片。

三层结构对应 prd/rag-pipeline.md 的处理流程：

    sources          一份原始资料（一篇网页 / 一个 PDF / 一个 RSS 订阅）
      └ document_chunks   切成 N 片，每片是检索的最小单位

向量本身**不存这里**，在 sqlite-vec 的 ``chunk_embeddings`` 虚拟表里
（见 app/services/vectorstore.py）。存两处的理由：vec0 表没有列可以放
业务字段，而 chunk 文本要能被 BM25 之类的全文检索读到，必须在普通表里。

``document_chunks.id`` 就是 ``chunk_embeddings.chunk_id``——两表靠这个
整数主键对齐，不是各自的主键+外键。
"""

from datetime import datetime
from enum import StrEnum
from typing import Self

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SourceType(StrEnum):
    """资料来源类型——决定用哪个 parser。"""

    PDF = "pdf"
    HTML = "html"
    TEXT = "text"


class SourceStatus(StrEnum):
    """摄取状态机。

    刻意不设 ``error`` 之外的终态：``failed`` 之外都是可重试的中间态。
    用户重传同类型资料时直接复用这条记录并回到 ``pending``。
    """

    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"


class Source(Base):
    """一份待摄取的研究资料。"""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SourceStatus.PENDING)

    # 网页/RSS 才有；本地 PDF 走 multipart 上传，不经过 URL。
    url: Mapped[str | None] = mapped_column(String(2048))
    # 原始文件存哪。W2 用本地磁盘，W3 换 S3/MinIO 时只改这个字段的写入方。
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int | None] = mapped_column(Integer)

    # 来源可信度 0-1，供下游给引用加权。RSS > 官方网页 > 个人博客。
    credibility_score: Mapped[float] = mapped_column(Float, default=0.5)

    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    # 解析出的纯文本长度。chunk_count * 平均片长 ≈ 这个值，用来发现
    # 「解析成功但文本为空」这种静默失败。
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_sources_user_id", "user_id"),)

    @classmethod
    async def find_owned(cls, session: AsyncSession, source_id: int, user_id: int) -> Self | None:
        """按 id 查资料，**并校验归属**。

        user_id 不可省：只按 id 查等于没有鉴权——别人的 source_id 照样能读。
        所有对外暴露 source 的入口都必须走这个方法。
        """
        stmt = select(cls).where(cls.id == source_id, cls.user_id == user_id)
        return await session.scalar(stmt)

    @classmethod
    async def list_owned(cls, session: AsyncSession, user_id: int) -> list[Self]:
        """列出某用户全部资料，按创建时间倒序。"""
        stmt = select(cls).where(cls.user_id == user_id).order_by(cls.created_at.desc())
        return list((await session.scalars(stmt)).all())


class DocumentChunk(Base):
    """资料的一个语义切片——检索的最小单位。"""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 该片在这份资料里的序号，从 0 起。引用格式是 [1]，页码是 [1, p.3]，
    # 都要靠它把「模型的引用」映射回「人类能读的位置」。
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # PDF 的页码（1 起）；网页/纯文本为 None。
    page: Mapped[int | None] = mapped_column(Integer)
    # 切片用的字符区间 [start, end)，用于高亮原文。
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 附加元数据（作者、发布时间等）。JSON 列：字段随 parser 演进，
    # 加一个不该改表结构。
    meta: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    source: Mapped[Source] = relationship(back_populates="chunks", lazy="selectin")

    __table_args__ = (
        # 一个资料内序号唯一。id 单列主键撑不住这个约束。
        Index("ux_document_chunks_source_index", "source_id", "chunk_index", unique=True),
        Index("ix_document_chunks_source_id", "source_id"),
    )

    @classmethod
    async def list_for_source(cls, session: AsyncSession, source_id: int) -> list[Self]:
        """取某资料的全部切片，按序号排。"""
        stmt = (
            select(cls)
            .where(cls.source_id == source_id)
            .order_by(cls.chunk_index)
        )
        return list((await session.scalars(stmt)).all())

    @classmethod
    async def find_many(cls, session: AsyncSession, ids: list[int]) -> list[Self]:
        """按主键批量取。检索结果可能乱序，调用方自行按 id 回查映射。"""
        if not ids:
            return []
        stmt = select(cls).where(cls.id.in_(ids))
        return list((await session.scalars(stmt)).all())
