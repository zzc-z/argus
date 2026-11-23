"""创建 provider_credentials 表

Revision ID: f7c2b9e4a183
Revises: a1b2c3d4e5f6
Create Date: 2026-11-23

每用户的外部能力凭据与路由配置——把 API key / base_url 从「进程环境变量
（全账号共用一把）」改成「按 user_id 落地」。

密钥明文存（与 model 的 docstring 同口径）：这是给测试人员用的多账号
环境，库文件本来就在开发者手里；生产要加密时替换读写两个函数即可。

user_id 上建唯一索引而不是普通索引：一个用户只有一行凭据，普通索引
允许重复行会让「取这个人的凭据」返回任意一行——而不同行的 key 不一样，
于是同一个人的两次研究可能用不同的 key，且没有任何报错。

**没有 embedding_model 列**：嵌入模型名是部署级配置，不按用户分。

向量索引（``chunk_embeddings`` vec0 虚表）是全库共享的，维度写死在
建表 DDL 里（1536）。改了模型就会出现两套向量坐标系混在同一张表里——
新切片是模型 A 的向量，老切片是模型 B 的，而查询向量只有一个，
余弦距离在混合坐标系里算出来没有意义。

症状是静默的：检索质量下降，不报错。而重建索引的入口这个项目还没有，
用户改了就回不去了。

嵌入的 **key 与端点**可以按用户配（那是「连到哪」）；**模型名**是
「用什么坐标系」，必须全局一致。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7c2b9e4a183"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建表。"""
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("anthropic_api_key", sa.Text(), nullable=True),
        sa.Column("anthropic_base_url", sa.String(length=512), nullable=True),
        sa.Column("anthropic_complex_model", sa.String(length=128), nullable=True),
        sa.Column("anthropic_default_model", sa.String(length=128), nullable=True),
        sa.Column("anthropic_critic_model", sa.String(length=128), nullable=True),
        sa.Column("tavily_api_key", sa.Text(), nullable=True),
        sa.Column("embedding_api_key", sa.Text(), nullable=True),
        sa.Column("embedding_base_url", sa.String(length=512), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    # **唯一**索引：一个用户一行凭据。见模块 docstring 的理由。
    op.create_index(
        "ix_provider_credentials_user_id",
        "provider_credentials",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    """回滚建表。"""
    op.drop_index("ix_provider_credentials_user_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
