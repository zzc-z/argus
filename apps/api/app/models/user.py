"""用户与外部身份绑定。

两层模型（Auth.js 事实标准，见 docs/CODE-QUALITY.md 引用）：

- ``users``      argus 眼里的「这个人是谁」，与登录方式无关
- ``accounts``   「这个人通过哪个 provider 的哪个 ID 登录过」

拆开的理由：prd/tech-stack.md 规划了 GitHub + Google 双 provider。
单表方案会让 users 越来越宽（每加一个 provider 多几列 nullable），
且无法表达「同一人同时绑了 GitHub 和 Google」。
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, PrimaryKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Provider(StrEnum):
    """已支持的 OAuth provider。

    存库时仍是普通字符串（加 provider 不必改 schema），
    但 Python 侧用枚举收口，避免拼错大小写。

    用 StrEnum 而非 str+Enum：后者 f-string 会输出 ``Provider.GITHUB``
    而不是 ``github``，日志和错误消息里会出现意料之外的文本。
    """

    GITHUB = "github"
    GOOGLE = "google"


class User(Base):
    """argus 用户账号。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 邮箱可为空：OAuth 用户可能隐藏邮箱、或多个 provider 邮箱不同。
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    accounts: Mapped[list["Account"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Account(Base):
    """外部身份绑定：provider +该 provider 内的唯一 ID。

    复合主键 (provider, provider_account_id)——GitHub 的 12345 和
    Google 的 12345 是不同的人，只凭 account_id 无法区分。

    token 字段目前不使用（YAGNI：argus 登录只需要身份 + 公开资料）。
    W3 若要拉GitHub 私有邮箱 / 私有仓库再启用，届时需要加密存储。
    """

    __tablename__ = "accounts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)

    access_token: Mapped[str | None] = mapped_column(String(512))
    refresh_token: Mapped[str | None] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="accounts")

    __table_args__ = (
        PrimaryKeyConstraint("provider", "provider_account_id"),
        Index("ix_accounts_user_id", "user_id"),
    )
