"""创建 reports 与 report_sources 表

Revision ID: c3d9e1f27a04
Revises: 500a268181fc
Create Date: 2026-10-16

研究跑完后把报告落盘，让「历史报告」与「这份报告引用了哪些私有资料」可查。

report_sources 存 (report_id, chunk_id) 复合主键而不是只记 source_id，
**为了放得下角标编号 n**：报告正文里写死了 ``[1]``、``[2]``，只记
source 的话角标 1 和角标 2 会指向同一份资料、无法区分。

（早期版本在这里写的理由是「sources 列表页的『关联报告 N 篇』列要显示
被引 20 次」——那条是错的：那个数按**报告**去重，存 chunk 级与存
source 级算出来完全一样。真实理由见 ``app/models/report.py`` 顶部。）

chunk_id 上加 CASCADE，删资料时连带清掉引用记录——留着会指向不存在的
切片，且那一行的外键会因为 document_chunks 已删而悬空。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d9e1f27a04"
down_revision: str | Sequence[str] | None = "500a268181fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建表。"""
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_user_id", "reports", ["user_id"], unique=False)
    op.create_index("ux_reports_session_id", "reports", ["session_id"], unique=True)

    op.create_table(
        "report_sources",
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        # 角标编号。正文里写死了 [n]，不存就没法把角标还原成切片。
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("cite_count", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id", "chunk_id"),
    )
    op.create_index("ix_report_sources_chunk_id", "report_sources", ["chunk_id"], unique=False)


def downgrade() -> None:
    """回滚建表。先删子表再删父表，否则 report_sources 的外键会挡住。"""
    op.drop_index("ix_report_sources_chunk_id", table_name="report_sources")
    op.drop_table("report_sources")
    op.drop_index("ux_reports_session_id", table_name="reports")
    op.drop_index("ix_reports_user_id", table_name="reports")
    op.drop_table("reports")
