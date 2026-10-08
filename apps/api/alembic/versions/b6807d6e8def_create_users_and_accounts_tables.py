"""创建 users 与 accounts 表

Revision ID: b6807d6e8def
Revises:
Create Date: 2026-10-08

两张表对应两层身份模型：users 管「argus 眼里这个人是谁」，
accounts 管「这个人通过哪个 provider 的哪个 ID 登录」。

复合主键 (provider, provider_account_id)——GitHub 的 12345 与
Google 的 12345 是不同的人，只凭 account_id 无法区分。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6807d6e8def"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建表。"""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "accounts",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_account_id", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.String(length=512), nullable=True),
        sa.Column("refresh_token", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provider", "provider_account_id"),
    )
    op.create_index("ix_accounts_user_id", "accounts", ["user_id"], unique=False)


def downgrade() -> None:
    """回滚建表。先删子表再删父表，否则 accounts 的外键会挡住。"""
    op.drop_index("ix_accounts_user_id", table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("users")