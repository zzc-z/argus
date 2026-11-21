"""给 sources 加版本分组列（group_id / content_hash / is_active / version_no）
并新建 source_groups 表

Revision ID: a1b2c3d4e5f6
Revises: e5f2a8c41b09
Create Date: 2026-11-20

## 为什么需要这条迁移

同一份资料会有多个版本（改过的简历、改过的报告）。没有版本概念时，
它们是彼此独立的 Source，各自切片、各自索引，检索时一起进候选池。

后果是模型收到互相冲突的证据：旧版与新版内容高度相似，两版都能匹配问题，
模型可能选中旧版、或把两版混着编。语义相似不等于事实有效。

加了分组后，检索只取组内**生效版本**，旧版留档但默认召不到。

## 为什么要有 source_groups 这张表

``group_id`` 需要一个**独立于 sources.id 的自增空间**。

不能拿「组内第一份资料的 id」当 group_id：新建组时那份资料的 id 还没拿到
（要先插 source 才知道 id），得反过来再插一次；而用「max(source.id)+1」
分配又会与未来新 source 的 id 撞车——两者共用一个序列。

所以 group_id 是 ``source_groups.id``，由这张表分配。sources.group_id 是
指向它的外键。

``ON DELETE SET NULL``：组没了，组内资料不该跟着删——它们退回「各自独立、
都生效」的状态（这也是部分唯一索引排除 group_id IS NULL 的原因）。

## 列的语义

- ``group_id`` —— 逻辑文档组 id。指向 source_groups.id。NULL = 不参与分组。
- ``content_hash`` —— 原始文件 sha256。只用于识别「完全相同的文件」，
  **不用于判断权威性**。
- ``is_active`` —— 是否为组内生效版本。组内至多一条为 True。
- ``version_no`` —— 组内版本号，从 1 起。

## 唯一索引是部分索引

``ux_sources_group_active`` 建在 ``(group_id)`` 上，条件
``is_active = 1 AND group_id IS NOT NULL``。

用部分索引而不是 ``(group_id, is_active)`` 普通唯一索引：后者会把
「组内两条归档版本」也管住——两条 is_active=False 就撞车，
而归档版本本来可以有多份。

## 已有行的默认值

全部资料的 ``is_active`` 默认 True、``version_no`` 默认 1、``group_id`` 为
NULL。这意味着**迁移后行为与迁移前完全一致**（每份资料都独立、都在检索池里），
分组是靠后续上传的新文件归组建立的——老资料不会被自动归组。

这是刻意的：自动归组老资料需要重算相似度（要重新解析正文），代价高且
可能误并。归组只对新上传的资料生效。

## 两种起点都能跑

跟 ``e5f2a8c41b09`` 一样：迁移必须能处理「表/列已经存在」的情况
（用 ``Base.metadata.create_all`` 从 ORM 建表的库，列已经在了）。
列存在性只能运行时判断。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e5f2a8c41b09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GROUPING_COLUMNS = ("group_id", "content_hash", "is_active", "version_no")


def _table_names() -> set[str]:
    inspector = inspect(op.get_bind())
    return set(inspector.get_table_names())


def _existing_columns(table: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _has_grouping_columns() -> bool:
    """分组相关列是否都已存在。

    全新库：从 ORM 建表（``create_all``）→ 列已存在 → 不该再加一次。
    迁移链上的库：``500a268181fc`` 建表时没这些列 → 得补上。
    """
    existing = _existing_columns("sources")
    return all(col in existing for col in _GROUPING_COLUMNS)


def _has_active_index() -> bool:
    """部分唯一索引是否已存在。"""
    inspector = inspect(op.get_bind())
    if "sources" not in inspector.get_table_names():
        return False
    return "ux_sources_group_active" in {idx["name"] for idx in inspector.get_indexes("sources")}


def _has_groups_table() -> bool:
    return "source_groups" in _table_names()


def upgrade() -> None:
    """建 source_groups 表 + 给 sources 加四列 + 部分唯一索引。"""
    if not _has_groups_table():
        op.create_table(
            "source_groups",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                # timezone=True：ORM 侧是 ``UtcDateTime``（impl 是
                # ``DateTime(timezone=True)``），迁移与 ORM 的时区语义必须一致。
                # 本迁移链上的其他迁移（``500a268181fc`` / ``c3d9e1f27a04`` /
                # ``b6807d6e8def``）也都用 timezone=True——写裸 DateTime
                # 会让 Postgres 建出 ``timestamp without time zone``，
                # 而 ORM 读它时按会话 TimeZone GUC 解释，静默差一个时区偏移。
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_source_groups_user_id", "source_groups", ["user_id"])

    if not _has_grouping_columns():
        existing = _existing_columns("sources")
        with op.batch_alter_table("sources") as batch:
            if "group_id" not in existing:
                batch.add_column(sa.Column("group_id", sa.Integer(), nullable=True))
            if "content_hash" not in existing:
                batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
            if "is_active" not in existing:
                # NOT NULL + server_default：SQLite 上 ALTER TABLE ADD COLUMN
                # NOT NULL 要求列有 server_default 或表为空。
                # 已有行会被填成 True —— 迁移后每份资料都独立可检索，
                # 与迁移前行为一致。
                batch.add_column(
                    sa.Column(
                        "is_active",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.true(),
                    )
                )
            if "version_no" not in existing:
                batch.add_column(
                    sa.Column(
                        "version_no",
                        sa.Integer(),
                        nullable=False,
                        server_default="1",
                    )
                )

        # 外键单独加：batch_alter_table 重建表时加外键会让 SQLite 走
        # 「建新表 + 拷数据 + 换名」，而 source_groups 必须**先存在**
        # （上面已建好），顺序是对的。
        with op.batch_alter_table("sources") as batch:
            batch.create_foreign_key(
                "fk_sources_group_id",
                "source_groups",
                ["group_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if not _has_active_index():
        op.create_index(
            "ux_sources_group_active",
            "sources",
            ["group_id"],
            unique=True,
            sqlite_where=sa.text("is_active = 1 AND group_id IS NOT NULL"),
            postgresql_where=sa.text("is_active = true AND group_id IS NOT NULL"),
        )


def downgrade() -> None:
    """删索引、外键、四列与 source_groups 表。

    降级后 ORM 里仍有这些字段——模型与 schema 会不一致，读写资料时报
    ``no such column``。所以真要回退，得连 ``app/models/source.py`` 的
    字段一起删（那是代码改动，不是迁移能做的）。
    """
    if _has_active_index():
        op.drop_index("ux_sources_group_active", table_name="sources")

    if _has_grouping_columns():
        with op.batch_alter_table("sources") as batch:
            batch.drop_constraint("fk_sources_group_id", type_="foreignkey")
            for col in ("version_no", "is_active", "content_hash", "group_id"):
                batch.drop_column(col)

    if _has_groups_table():
        op.drop_index("ix_source_groups_user_id", table_name="source_groups")
        op.drop_table("source_groups")
