"""研究资料源与其语义切片。

三层结构对应 prd/rag-pipeline.md 的处理流程：

    sources          一份原始资料（一篇网页 / 一个 PDF / 一个 RSS 订阅）
      └ document_chunks   切成 N 片，每片是检索的最小单位

向量本身**不存这里**，在 sqlite-vec 的 ``chunk_embeddings`` 虚拟表里
（见 app/services/vectorstore.py）。存两处的理由：vec0 表没有列可以放
业务字段，而 chunk 文本要能被 BM25 之类的全文检索读到，必须在普通表里。

``document_chunks.id`` 就是 ``chunk_embeddings.chunk_id``——两表靠这个
整数主键对齐，不是各自的主键+外键。

第四层是版本分组：

    source_groups    一个逻辑文档（同一份资料的多个版本）
      └ sources         该组下的各个版本，组内至多一份 is_active
"""

from datetime import datetime
from enum import StrEnum
from typing import Self

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    and_,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from app.models.base import Base, UtcDateTime


class SourceType(StrEnum):
    """资料来源类型——决定用哪个 parser。"""

    PDF = "pdf"
    HTML = "html"
    TEXT = "text"
    DOCX = "docx"


WEB_SOURCE_TYPE = "web"
"""联网搜索结果落成的来源类型。

与用户上传的资料区分开的唯一标记。**刻意不新增一列**——``sources``
表加列要写 Alembic 迁移，按项目规范（AGENTS.md）得单独审。

它的用法：
- :meth:`Source.list_owned` 排除它——不进资料列表、不进本地检索
- 它**不走摄取管线**（没有原始文件要解析），所以
  ``ingest.parser_for`` 遇到它会报错，但那条路径永远碰不到
"""


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
    SUPERSEDED = "superseded"
    """被更新的同内容资料取代——它**什么都不是**，不是失败。

    ## 什么时候出现

    用户误点两次上传（或客户端重试）时，两条内容完全相同的 Source
    都会建出来。若都建成索引，检索会召回两份一模一样的证据，模型把
    同一段话当成两个独立来源互相印证。

    老的那些被标成 superseded：不生效、不进检索池、不算重复。

    ## 为什么不是 FAILED

    failed 的语义是「处理失败，原因是 X」——用户要看到那个原因
    （嵌入服务欠费是已知状态）。superseded 的语义是「它被取代了，
    没什么可看的」——混进 failed 会让用户以为自己的资料坏了。

    **行不删**：删掉会让「这份资料曾经失败过」的历史消失，而失败原因
    是用户需要的诊断信息。
    """


class SourceGroup(Base):
    """一个逻辑文档组——同一份资料的多个版本。

    ## 为什么要这张表，而不是复用 sources.id

    ``group_id`` 需要一个**独立于 sources.id 的自增空间**。

    拿「组内第一份资料的 id」当 group_id 不行：新建组时那份资料的 id
    还没拿到（要先插 source 才知道 id），得反过来再插一次；而用
    「max(source.id)+1」分配又会与未来新 source 的 id 撞车——两者共用
    一个序列。

    所以 group_id 由这张表分配，``sources.group_id`` 是指向它的外键。

    ## 组里存什么

    **只有身份，不存内容**。组内各版本的内容在各自的 ``sources`` 行里。
    这张表存在的唯一理由是「需要一个稳定的组 id」。
    """

    __tablename__ = "source_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
    )

    __table_args__ = (Index("ix_source_groups_user_id", "user_id"),)


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

    # ── 版本分组 ────────────────────────────────────────────
    #
    # 同一份资料的多个版本（改过的简历、改过的报告）归到一个 group。
    # 检索**只取组内生效的那一份**，旧版留档但默认召不到。
    #
    # 为什么不用「文件名相同」当分组键：文件名取自上传时的原名
    # （gateway/sources.py 的 upload_source），用户改个名就破组；
    # 而同名不同文档（两份不同人的「简历.pdf」）又会被误并。
    # 所以 group_id 由内容判定（services/grouping.py），不靠名字。
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_groups.id", ondelete="SET NULL"),
    )
    """逻辑文档组 id。指向 source_groups.id。NULL = 不参与分组。

    非空时，同组内至多一条 ``is_active=True``——由
    ``ux_sources_group_active`` 部分唯一索引在数据库层保证。

    ``ON DELETE SET NULL``：组没了，组内资料退回「各自独立、都生效」，
    而不是跟着被删。
    """
    content_hash: Mapped[str | None] = mapped_column(String(64))
    """原始文件的 sha256 十六进制摘要。

    **只用来识别「完全相同的文件」，不用来判断哪个版本权威**——
    权威性由 ``is_active`` 决定。两份 hash 相同说明它们是同一份内容，
    不说明哪份更新（用户可能故意重传同一份来覆盖）。
    """
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    """是否是该组的**生效版本**。组内至多一条为 True。

    默认 True：单份资料（没有其他版本竞争）天然是生效的，
    不需要用户做任何操作。

    「组内至多一条」由 ``ux_sources_group_active`` 这个**部分唯一索引**
    在数据库层保证，不靠应用层自觉。
    """
    version_no: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    """组内版本号，从 1 起。用于 UI 展示「第 2 版」与人工核对。

    **server_default 不能省**：``default=1`` 是 **Python 层**默认值，
    只在 ORM 构造对象时生效——裸 SQL INSERT 不带这一列时它是 NULL。
    而这一列是 NOT NULL，于是那条 INSERT 报
    ``NOT NULL constraint failed: sources.version_no``。

    用 ``Base.metadata.create_all`` 建表的库（测试库就是）**没有迁移**，
    server_default 是唯一的兜底——所以它必须写在 ORM 上，不能只写在
    迁移文件里。
    """

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        # selectin 是无条件 eager：查任何 Source 都会连带拉它全部切片的
        # **正文**。实测 `list_owned`（列表页只显示 title/status）发出两条
        # SQL，第二条把整份资料的正文拖进内存，一个字符都用不上。
        #
        # 改成 lazy="raise"：默认不加载，碰它就报错而不是悄悄发一条
        # SELECT。文档里的说法是 "raise"，"raiseload" 是 1.x 的旧写法，
        # SQLAlchemy 2.x 会报 "Can't find strategy (('lazy', 'raiseload'),)"。
        #
        # 真要用切片时显式查（DocumentChunk.list_for_source）；摄取流程
        # 需要它，那里有明确的显式查询。
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_sources_user_id", "user_id"),
        # **部分唯一索引**：保证「同一个组里至多一条生效版本」。
        #
        # 为什么用部分索引（`WHERE is_active`）而不是普通唯一索引：
        # 普通唯一索引建在 (group_id, is_active) 上会把「组内两条归档版本」
        # 也管住——两条 is_active=False 就会撞车，而归档版本本来可以有多份。
        #
        # 为什么 `group_id IS NOT NULL`：group_id 为 NULL 的行（公开来源、
        # 未归组资料）不参与版本竞争，它们的 is_active 恒为 True，多行共存
        # 是正常的。SQLite 与 Postgres 的唯一索引都把 NULL 视作互不相等，
        # 但显式排除更清楚，也省掉「靠 NULL 语义碰巧不撞车」的隐式依赖。
        Index(
            "ux_sources_group_active",
            "group_id",
            unique=True,
            sqlite_where=text("is_active = 1 AND group_id IS NOT NULL"),
            postgresql_where=text("is_active = true AND group_id IS NOT NULL"),
        ),
    )

    @classmethod
    async def find_owned(cls, session: AsyncSession, source_id: int, user_id: int) -> Self | None:
        """按 id 查资料，**并校验归属**。

        user_id 不可省：只按 id 查等于没有鉴权——别人的 source_id 照样能读。
        所有对外暴露 source 的入口都必须走这个方法。
        """
        stmt = select(cls).where(cls.id == source_id, cls.user_id == user_id)
        return await session.scalar(stmt)

    @classmethod
    def owned_clause(cls, user_id: int) -> ColumnElement[bool]:
        """「用户自己上传的资料」这个条件。

        ## 为什么要有这个

        联网搜索结果也落成 ``Source`` 行（``source_type="web"``，见
        ``app/services/web_sources.py``），但它们**不是**用户上传的资料。
        凡是统计「用户有多少资料」的地方都要排除它们，否则：

        - 概览页显示「我的资料 6 份」而用户只上传过 1 份
        - 本地检索的候选集里混进网页摘要

        所以做成一个共用的条件，三处（``list_owned`` / dashboard 的两个
        计数）都用它——三处各写一遍的话，漏一处那个数就是错的。
        """
        return and_(cls.user_id == user_id, cls.source_type != WEB_SOURCE_TYPE)

    @classmethod
    async def list_owned(cls, session: AsyncSession, user_id: int) -> list[Self]:
        """列出某用户**上传的资料**，按创建时间倒序。

        ## 为什么排除 ``source_type="web"``

        联网搜索结果会落成 ``Source`` 行（见
        ``app/services/web_sources.py``），它们不是用户上传的资料：

        - 出现在「我的资料」列表里是误导——用户没上传过它们
        - 本地检索按 ``list_owned`` 的结果收窄 source_ids
          （``retriever._user_source_ids``），混进去会让「我的资料里
          有没有说过 X」检索到网上搜来的片段

        排除靠 ``source_type`` 而**不是新增一列**——加列要写 Alembic
        迁移，按项目规范得单独审。

        要拿到公开来源（角标点开看原文）走
        ``GET /sources/{id}/chunks``，那个端点按 source_id 直查，
        不经过本方法。

        ## 这个方法返回**全部**版本（含归档的旧版）

        资料页要展示旧版（用户能看见「这组有 3 个版本」）。检索的候选集
        用 :meth:`list_active_owned`。

        ## 但**不含 superseded** 的行

        superseded 是「被同内容的新上传取代」的内部状态（见
        :data:`SourceStatus.SUPERSEDED`）。它不是用户的一份资料——
        用户没主动上传过它（是误点两次或客户端重试产生的），把它
        列进「我的资料」只会让用户困惑「这份我没传过」。
        """
        stmt = (
            select(cls)
            .where(cls.owned_clause(user_id), cls.status != SourceStatus.SUPERSEDED)
            .order_by(cls.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    @classmethod
    async def list_active_owned(cls, session: AsyncSession, user_id: int) -> list[Self]:
        """列出某用户**生效版本**的资料——检索的候选集。

        ## 与 :meth:`list_owned` 的区别

        ``list_owned`` 返回**全部**上传的资料（含旧版本），给资料页展示用；
        本方法只返回 ``is_active=True`` 的那些，给本地检索收窄 source_ids 用。

        ## 为什么旧版本不参与检索

        同一份资料的旧版本与新版本**内容高度相似**——旧版答对了也不新鲜，
        新版答对了才对。两版都进候选池时，向量检索会把它们都召回来，
        模型收到互相冲突的证据，于是可能选中旧版、或把两版混着编。

        语义相似不等于事实有效：旧版可以和问题一样匹配，但已经不是当前答案。
        所以旧版留档（可查、可切回）但不进默认检索。

        ## 归档版本怎么办

        归档版本仍在库里，只是不在这里返回。用户可以在资料页手动把它设为
        生效版（``PATCH /sources/{id}/activate``），或问历史问题。
        """
        stmt = (
            select(cls)
            .where(cls.owned_clause(user_id), cls.is_active.is_(True))
            .order_by(cls.created_at.desc())
        )
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
        UtcDateTime(),
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
        stmt = select(cls).where(cls.source_id == source_id).order_by(cls.chunk_index)
        return list((await session.scalars(stmt)).all())

    @classmethod
    async def find_many(cls, session: AsyncSession, ids: list[int]) -> list[Self]:
        """按主键批量取。检索结果可能乱序，调用方自行按 id 回查映射。"""
        if not ids:
            return []
        stmt = select(cls).where(cls.id.in_(ids))
        return list((await session.scalars(stmt)).all())
