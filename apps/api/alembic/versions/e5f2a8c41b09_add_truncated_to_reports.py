"""给 reports 补 truncated 列（这份报告是否被截断）

Revision ID: e5f2a8c41b09
Revises: d4e8f1a29b73
Create Date: 2026-10-23

## 为什么需要这条迁移

``DoneEvent`` 带 ``truncated`` 标记，但它只活在 SSE 帧里——**不落库**。
后果是：流程中途崩溃时已经生成的正文会被落盘（这部分正文是真的，
token 也真的花了），可这份报告在历史列表里和完整报告长得一模一样，
读者会以为它读到了完整的研究结论。

崩溃落盘是 2026-10-22 加的（``app/services/agent.py`` 的异常路径现在
会落盘并返回 ``report_id``）。加了落盘就必须同时加这个标记——
否则「不丢正文」的改进反而引入了「读者被误导」的新问题。

## 加列的兼容性

``truncated`` 在 ORM 里是 ``nullable=False``、``default=False``。
**Python 层的 default 不是 server_default**——``ALTER TABLE ... ADD
COLUMN ... NOT NULL`` 在 SQLite 上要求列有 server_default 或表为空。

所以显式给 ``server_default=sa.false()``：已有行会被填成 False，
即「迁移前落盘的报告都当完整报告处理」。这是对的——迁移前只有正常
跑完的报告（崩溃落盘是 2026-10-22 才有的，而这条迁移紧跟其后）。

用 ``batch_alter_table`` 是为了 SQLite——它走「重建表」而不是
``ALTER TABLE``，能把 NOT NULL + default 一次做对。

## 两种起点都能跑

跟 ``d4e8f1a29b73`` 一样：迁移必须能处理「表已经有这一列」的情况
（建库时用 ``Base.metadata.create_all`` 从 ORM 建表的库，列已经在了）。
列存在性只能运行时判断。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "e5f2a8c41b09"
down_revision: str | Sequence[str] | None = "d4e8f1a29b73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_truncated_column() -> bool:
    """``reports`` 表当前有没有 ``truncated`` 列。

    两种起点：

    - 全新库：从 ORM 建表（``create_all``）→ 列已存在 → 不该再加一次
    - 迁移链上的库：``c3d9e1f27a04`` 建表时没这列 → 得补上
    """
    inspector = inspect(op.get_bind())
    if "reports" not in inspector.get_table_names():
        return False
    return "truncated" in {c["name"] for c in inspector.get_columns("reports")}


def upgrade() -> None:
    """加一列 ``truncated``，已有行填 False。"""
    if _has_truncated_column():
        return

    with op.batch_alter_table("reports") as batch:
        batch.add_column(
            sa.Column(
                "truncated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    """删列。

    降级后 ORM 里仍有 ``truncated`` 字段——模型与 schema 会不一致，
    读写报告时报 ``no such column``。所以真要回退，得连
    ``app/models/report.py`` 的字段一起删（那是代码改动，不是迁移能
    做的）。
    """
    if not _has_truncated_column():
        return

    with op.batch_alter_table("reports") as batch:
        batch.drop_column("truncated")
