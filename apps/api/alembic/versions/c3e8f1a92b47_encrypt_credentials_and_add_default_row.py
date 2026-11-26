"""凭据加密 + 共享默认行

Revision ID: c3e8f1a92b47
Revises: f7c2b9e4a183
Create Date: 2026-11-23

三件事：

1. **加 scope 列**——区分「用户自己的行」与「共享默认行」。
   共享默认行是全库一行，所有没自己配的用户共用它。开箱即用靠它。

   ``user_id`` 改为可空：默认行**不属于任何用户**，它的 user_id 是 NULL。

2. **key 改密文存**——列类型不变（Text 装得下），但写入的内容变成
   ``enc:v1:`` 前缀的 Fernet 密文。

   **历史数据不自动重写**：迁移里读不出明文——主密钥在环境变量里，
   迁移脚本未必能拿到（CI、生产的迁移环境各不相同）。
   加解密函数对「没带前缀的值」原样返回，所以**旧行照常能用**。

   本次迁移**不提供重写存量数据的入口**——存量明文 key 保持可用，
   它们会在用户下次保存该字段时被重新加密（写入路径一律走加密）。

3. **加部分唯一索引** ``WHERE scope='default'``——保证共享默认行
   只有一行。

   ⚠️ 不能在 scope 上建**普通**唯一索引：所有用户行的 scope 都是
   ``'user'``，普通唯一索引会让第二个用户行直接插入失败。

scope 的取值：``'user'``（用户自己的）/ ``'default'``（共享默认行）。

存量行的 scope 全部置为 ``'user'``——迁移前只有用户行，没有默认行。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8f1a92b47"
down_revision: str | Sequence[str] | None = "f7c2b9e4a183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """加 scope 列、放宽 user_id、加部分唯一索引。"""
    # 1. scope 列。存量行全部是用户行。
    op.add_column(
        "provider_credentials",
        sa.Column(
            "scope",
            sa.String(length=16),
            nullable=False,
            server_default="user",
        ),
    )

    # 2. user_id 改可空——共享默认行没有主人。
    #
    # SQLite 不支持直接 ALTER COLUMN，改用 batch 模式（alembic 会
    # 重建表）。batch 模式下「加带默认值的非空列」在 SQLite 上是先
    # 加可空列再回填再改非空——这正是上面分两步做的原因。
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    # 3. 部分唯一索引：共享默认行只能有一行。
    #
    # 用 raw SQL 而不是 op.create_index——部分索引的 WHERE 子句
    # 在 op.create_index 上没有跨库统一的表达（sqlite_where 是
    # SQLite 专属，postgresql_where 是 PG 专属），而这里两个库都要
    # 支持。
    op.execute(
        "CREATE UNIQUE INDEX uq_provider_credentials_default_scope "
        "ON provider_credentials (scope) WHERE scope = 'default'"
    )


def downgrade() -> None:
    """回滚。"""
    op.execute("DROP INDEX IF EXISTS uq_provider_credentials_default_scope")

    # scope 列直接删——回滚后不需要区分两层。
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.drop_column("scope")

    # **先删掉共享默认行**——它的 user_id 是 NULL。
    #
    # 不删的话下一步（user_id 改回非空）会失败：SQLite 的 batch 模式
    # 重建表，NOT NULL 约束在重建时校验到 NULL 行就报错。
    # 实测报 `NOT NULL constraint failed: _alembic_tmp_provider_credentials.user_id`
    # ——`alembic downgrade` 直接卡住，人还不知道要干嘛。
    #
    # ⚠️ **这是删数据**。但删的是**共享默认行**——它是本次迁移引入的
    # 概念（没有 scope 的世界里不存在「不属于任何人的凭据行」），
    # 回滚时丢弃它在语义上是正确的，不是删用户数据。
    # **用户自己的行（scope='user'）一个都不动**。
    op.execute("DELETE FROM provider_credentials WHERE user_id IS NULL")

    # user_id 改回非空。
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
