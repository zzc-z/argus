"""每用户的外部能力凭据与路由配置 + 共享默认凭据。

## 为什么单独一张表

外部 AI 能力（Anthropic / Tavily / Embedding）的 API key 与 base_url
原先只有一处来源：进程环境变量（``.env``）。那意味着**同一台部署上的
所有账号共用一把 key**——测试人员没法各自配自己的中转站，也没法在不
动部署配置的前提下换线路。

这张表让配置**按 user_id 落地**：

    users
      └ provider_credentials   这个人的 key / base_url / 模型路由

一行一人（``user_id`` 唯一）。三个能力各自占一组列，而不是「一行一个
能力」的多行设计——理由是三个能力总是**一起读**（每次研究都要看
Anthropic 的 key、Tavily 的 key、Embedding 的 key），一行读一次比三行
读三次省，也让「这个人配了没有」一眼可见。

## 两层：共享默认行 + 用户行

``scope`` 列区分两种行：

- ``'default'`` —— **全库一行**，所有没自己配的用户共用。开箱即用靠它。
- ``'user'``    —— 某个人自己配的，覆盖默认行。

解析顺序：**用户行 > 默认行 > 环境变量**（见
``app/services/credentials.py``）。

**为什么用 scope 列而不是 ``user_id IS NULL``**：那样的话「用户行」与
「默认行」的差别藏在一个 NULL 里，而 NULL 在 SQL 里还意味着「未指定」，
三种含义混在一个值上。而且 user_id 上那个唯一索引对 NULL 不生效
（SQLite 允许多行 NULL），无法再保证「默认行只有一行」。

## 密钥加密存

key 存的是 **Fernet 密文**（前缀 ``enc:v1:``），见
``app/services/secret_store.py``。

明文存的话，一次库文件泄露（备份、误提交、容器镜像层）就等于所有
key 一次性暴露。加密的主密钥来自 ``CREDENTIALS_ENCRYPTION_KEY``
环境变量，与 ``JWT_SECRET_KEY`` 分开——后者会轮换，轮换后存量密文
全解不开。

⚠️ **接口会回显密钥内容**——这是本项目的明确取舍：设置页要在输入框
里预填「当前生效值」，用户才看得见自己配的是什么。前提是**只有
登录用户能拿到**，而 key 本来就只对登录用户生效。
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UtcDateTime

# scope 的两个取值。
SCOPE_DEFAULT = "default"
"""共享默认行——全库一行，所有人兜底用。"""

SCOPE_USER = "user"
"""某个用户自己配的行。"""


class ProviderCredentials(Base):
    """一个用户的外部能力凭据与路由配置。"""

    __tablename__ = "provider_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    """拥有这行配置的用户。**共享默认行为 NULL**（没有具体主人）。"""

    scope: Mapped[str] = mapped_column(
        String(16),
        default=SCOPE_USER,
        server_default=SCOPE_USER,
        nullable=False,
    )
    """``'user'``（某个用户自己配的）或 ``'default'``（全库共享默认行）。

    ``server_default`` **必须与迁移一致**——``alembic/env.py`` 开了
    ``compare_server_default=True``，模型这边不声明而迁移声明了的话，
    下次 ``alembic revision --autogenerate`` 会生成一条「删掉 DB 层默认值」
    的迁移（两边不一致时 autogenerate 只看到差异，不知道哪个是对的）。
    """
    """``'user'``（某个用户自己配的）或 ``'default'``（全库共享默认行）。

    默认行**没有 user_id**——它不属于任何人，是所有用户的兜底。

    解析顺序（``services/credentials.py``）：用户行 > 默认行 > 环境变量。
    """

    # ── Anthropic（主模型服务）─────────────────────────────
    anthropic_api_key: Mapped[str | None] = mapped_column(Text)
    """Anthropic API key。**密文**（``enc:v1:`` 前缀）。

    留空 = 落到下一层（默认行 / 环境变量）。
    """

    anthropic_base_url: Mapped[str | None] = mapped_column(String(512))
    """中转站地址。留空 = 走官方端点。

    存时**已去掉尾部斜杠**——``base_url`` 拼路径时多一个斜杠会让
    中转站返回 404，而那种 404 的报错信息完全看不出是斜杠的问题。

    **不是秘密**（地址本身不含密钥），所以明文存、明文回显。
    """

    anthropic_complex_model: Mapped[str | None] = mapped_column(String(128))
    """复杂任务的模型（Researcher / Writer / Critic）。"""

    anthropic_default_model: Mapped[str | None] = mapped_column(String(128))
    """简单任务的模型（Supervisor / Analyst / Summarizer）。"""

    anthropic_critic_model: Mapped[str | None] = mapped_column(String(128))
    """Critic（引用忠实度判定）的模型。

    留空时退到 complex_model——**那时 critic 与 writer 是同一个模型**，
    自偏好偏差会让通过率系统性偏高（arXiv 2410.21819）。
    """

    # ── Tavily（联网搜索）─────────────────────────────────
    tavily_api_key: Mapped[str | None] = mapped_column(Text)
    """Tavily API key。**密文**。"""

    # ── Embedding（向量嵌入）──────────────────────────────
    embedding_api_key: Mapped[str | None] = mapped_column(Text)
    """嵌入服务 API key。**密文**。"""

    embedding_base_url: Mapped[str | None] = mapped_column(String(512))
    """OpenAI 兼容端点。留空 = 落到下一层。**不是秘密**，明文存。"""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_provider_credentials_user_id", "user_id", unique=True),
        Index(
            "uq_provider_credentials_default_scope",
            "scope",
            unique=True,
            sqlite_where=text("scope = 'default'"),
            postgresql_where=text("scope = 'default'"),
        ),
    )
    """两个唯一索引——各管一层。

    - ``user_id`` 唯一：一个人只有一行用户配置。
    - **部分唯一索引** ``WHERE scope='default'``：共享默认行只能有一行。

    ⚠️ ``scope`` 上**不能**建普通的唯一索引——所有用户行的 scope 都是
    ``'user'``，普通唯一索引会让第二个用户行直接插入失败。
    「scope='default' 只能有一行」这条约束必须用**部分索引**表达
    （``WHERE scope='default'``），SQLite 与 Postgres 都支持。

    部分索引的 WHERE 子句**没有类型标注**（``text()`` 的返回值是
    ``TextClause``），SQLAlchemy 的 ``Index`` 接受它。

    与迁移文件保持一致——两边不一样的话，
    ``alembic revision --autogenerate`` 会生成一条「删掉唯一约束」的
    迁移（见 CLAUDE.md §6：改 models 后要 autogenerate）。
    """

    @classmethod
    async def find_by_user(
        cls, session: AsyncSession, user_id: int
    ) -> "ProviderCredentials | None":
        """取这个用户的**用户行**。没有就返回 None（不是新建空行）。

        返回 None 而不是造一行空记录：空记录与「配了但值都是空」是两种
        状态，后者会让「这人的配置从哪来」的判断变复杂（到底是没配，
        还是配了但都被清空了）。
        """
        stmt = select(cls).where(cls.user_id == user_id, cls.scope == SCOPE_USER)
        return await session.scalar(stmt)

    @classmethod
    async def find_default(cls, session: AsyncSession) -> "ProviderCredentials | None":
        """取**共享默认行**。没有就返回 None。"""
        stmt = select(cls).where(cls.scope == SCOPE_DEFAULT)
        return await session.scalar(stmt)

    @classmethod
    async def find_user_and_default(
        cls, session: AsyncSession, user_id: int
    ) -> tuple["ProviderCredentials | None", "ProviderCredentials | None"]:
        """**一次查询**取回用户行与共享默认行。

        返回 ``(user_row, default_row)``，各自可能为 None。

        ## 为什么要合成一次查询

        解析凭据在请求热路径上（``agent.py`` 每次研究一次、
        ``ingest.py`` 每份资料一次）。分成两次 SELECT 就是两次往返——
        每次研究多一次查询，批量摄取时是每份资料多一次。

        一次查询的结果一样：``scope='user' AND user_id=?""`` **或**
        ``scope='default'``——用 OR 连起来，两行都可能被命中。

        ⚠️ **不能用 ``session.scalar``**——它只返回第一行。必须用
        ``scalars().all()`` 拿全部，再按 scope 分开。

        ⚠️ **OR 要用 ``or_()`` 显式写**——``where(a, b)`` 是 **AND**
        连接（SQLAlchemy 的多参数 where 就是 AND），写成那样会变成
        「既是用户行又是默认行」，一条都查不出来。
        """
        stmt = select(cls).where(
            or_(
                (cls.scope == SCOPE_USER) & (cls.user_id == user_id),
                cls.scope == SCOPE_DEFAULT,
            )
        )
        rows = (await session.scalars(stmt)).all()
        user_row: ProviderCredentials | None = None
        default_row: ProviderCredentials | None = None
        for row in rows:
            if row.scope == SCOPE_DEFAULT:
                default_row = row
            else:
                user_row = row
        return user_row, default_row


__all__ = ["SCOPE_DEFAULT", "SCOPE_USER", "ProviderCredentials"]
