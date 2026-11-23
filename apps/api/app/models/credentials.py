"""每用户的外部能力凭据与路由配置。

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

## 密钥明文存

**刻意不加密。** argus 现在没有密钥管理设施，加一层 Fernet 就要引入
密钥来源、轮换策略、备份流程三套运维负担，而这个项目的定位是
**给测试人员用的多账号环境**——库文件本身已经在开发者手里。

这是有意识的取舍，不是遗漏：生产部署要加密时，替换的是本模块的
读写两个函数，其余代码不受影响。

⚠️ **接口永不回显密钥内容**——见 ``app/schemas/credentials.py`` 的
响应模型：只报「配了没有」与「来自哪一层」。
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UtcDateTime


class ProviderCredentials(Base):
    """一个用户的外部能力凭据与路由配置。"""

    __tablename__ = "provider_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Anthropic（主模型服务）─────────────────────────────
    anthropic_api_key: Mapped[str | None] = mapped_column(Text)
    """Anthropic API key。留空 = 用环境变量里的那把（或没有）。"""

    anthropic_base_url: Mapped[str | None] = mapped_column(String(512))
    """中转站地址。留空 = 走官方端点。

    存时**已去掉尾部斜杠**——``base_url`` 拼路径时多一个斜杠会让
    中转站返回 404，而那种 404 的报错信息完全看不出是斜杠的问题。
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

    # ── Embedding（向量嵌入）──────────────────────────────
    embedding_api_key: Mapped[str | None] = mapped_column(Text)
    embedding_base_url: Mapped[str | None] = mapped_column(String(512))
    """OpenAI 兼容端点。留空 = 用环境变量里的（默认百炼）。"""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (Index("ix_provider_credentials_user_id", "user_id", unique=True),)
    """**唯一**索引——一个用户只有一行凭据。

    普通索引允许重复行，而不同行的 key 不一样：``find_by_user`` 返回
    任意一行，同一个人的两次研究可能用不同的 key，且**没有任何报错**。

    与迁移文件 ``f7c2b9e4a183`` 保持一致——两边不一样的话，
    ``alembic revision --autogenerate`` 会生成一条「删掉唯一约束」的
    迁移（见 CLAUDE.md §6：改 models 后要 autogenerate）。
    """

    @classmethod
    async def find_by_user(
        cls, session: AsyncSession, user_id: int
    ) -> "ProviderCredentials | None":
        """取这个用户的凭据行。**没有就返回 None**（不是新建空行）。

        返回 None 而不是造一行空记录：空记录与「配了但值都是空」是两种
        状态，后者会让「这人的配置从哪来」的判断变复杂（到底是没配，
        还是配了但都被清空了）。
        """
        stmt = select(cls).where(cls.user_id == user_id)
        return await session.scalar(stmt)
