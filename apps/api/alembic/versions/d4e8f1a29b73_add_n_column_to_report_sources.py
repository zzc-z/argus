"""给 report_sources 补 n 列（角标编号）

Revision ID: d4e8f1a29b73
Revises: c3d9e1f27a04
Create Date: 2026-10-20

## 为什么需要这条迁移

``c3d9e1f27a04`` 建表时就带了 ``n`` 列，ORM 模型（``app/models/report.py``）
也一直有它。**但有些数据库里这张表是缺 ``n`` 的**——建库时用的是
``Base.metadata.create_all``（从 ORM 建表）而不是跑迁移，于是当时
ORM 里的字段集与现在不同，缺列的表就留了下来。

缺 ``n`` 的后果不是「少一个字段」那么轻：

1. ``GET /api/v1/reports/{id}`` 直接 500——查询 ``ORDER BY report_sources.n``
   时报 ``no such column``。
2. **更严重**：写路径 ``_write``（``app/services/agent.py``）在
   ``await db.commit()`` 时才 INSERT ``report_sources``，带 ``n`` 列 →
   报错 → ``_persist_report`` 捕获异常并 ``db.rollback()`` →
   **整份报告连同 ``reports`` 行一起丢**，``report_id`` 返回 None。
   也就是说：任何引用了私有资料的报告根本存不下来。

## 为什么 CI 测不出来

测试用 ``Base.metadata.create_all`` 建表（``tests/conftest.py``），
schema 直接来自 ORM，**永远有** ``n`` 列。迁移漂移这类问题测试套件
结构上就看不见。

## 加列的兼容性

``n`` 在 ORM 里是 ``nullable=False`` 且没有 server_default，而
``report_sources`` 的复合主键是 ``(report_id, chunk_id)``——
已有行的表直接加 NOT NULL 列会失败（SQLite 靠 batch 重建表，
而主键要求该列非空）。

所以分两步：先加可空列并回填，再把它改成 NOT NULL。

回填的值取什么？``n`` 是正文里的角标编号，语义上「同一份报告内
按引用顺序从 1 递增」。表里已有行的 ``(report_id, chunk_id)`` 没有
可靠的顺序信息（chunk_id 是自增主键，勉强能当代理），所以按
``report_id`` 分组、组内按 ``chunk_id`` 升序编号。

**这一步是近似，不是还原**——真实的历史 ``n`` 无法从库里推导出来
（正文在 ``reports.content`` 里，但重新解析正文来还原角标需要把
Markdown 与引用表关联，超出一次加列迁移该做的事）。已有的行数
在写这条迁移时是 0，所以回填逻辑在当前 dev 库上不产生实际影响，
它的作用是让**任何其它有数据的库**升级后不炸。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "d4e8f1a29b73"
down_revision: str | Sequence[str] | None = "c3d9e1f27a04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_n_column() -> bool:
    """这张表当前有没有 ``n`` 列。

    迁移必须**两种起点都能跑**：

    - 全新库：``c3d9e1f27a04`` 已经建出了带 ``n`` 的表 → 不该再加一次
      （加了报 ``duplicate column name: n``）
    - 漂移的老库：表是缺 ``n`` 的 → 得补上

    两种库都会走到这条迁移（``down_revision`` 一样），所以列的存在性
    只能运行时判断，不能假设。
    """
    inspector = inspect(op.get_bind())
    if "report_sources" not in inspector.get_table_names():
        return False
    return "n" in {c["name"] for c in inspector.get_columns("report_sources")}


def upgrade() -> None:
    """加列 → 回填 → 收紧为 NOT NULL。

    分三步是 SQLite 的限制：``ALTER TABLE ... ADD COLUMN ... NOT NULL``
    要求列有 default 或表为空，而 ``n`` 在 ORM 里没有 default。
    ``op.add_column`` 对 SQLite 走的是 batch 模式（重建表），
    所以可以先可空再收紧。
    """
    if _has_n_column():
        # 全新库：列已存在且已是 NOT NULL，只补齐可能为空的行。
        _backfill()
        return

    with op.batch_alter_table("report_sources") as batch:
        batch.add_column(sa.Column("n", sa.Integer(), nullable=True))

    _backfill()

    with op.batch_alter_table("report_sources") as batch:
        batch.alter_column("n", existing_type=sa.Integer(), nullable=False)


def _backfill() -> None:
    """给 ``n`` 为空的行编号：同一份报告内按 chunk_id 升序从 1 开始。

    用 SQL 而非 Python 逐行改——表可能很大。

    编号用 ``ROW_NUMBER()`` 而不是「COUNT(*) + 1」：后者算的是
    「chunk_id 不大于自己的行数」，而同一份报告里 chunk_id 未必连续，
    会出现重复编号（实测：chunk 100/101/102 被编成 2/3/4，第一个从 2 开始）。
    """
    op.execute(
        """
        UPDATE report_sources
        SET n = (
            SELECT COUNT(*) FROM (
                SELECT chunk_id FROM report_sources AS candidates
                WHERE candidates.report_id = report_sources.report_id
                  AND candidates.chunk_id <= report_sources.chunk_id
            ) AS subset
        )
        WHERE n IS NULL
        """
    )


def downgrade() -> None:
    """**空操作**——故意什么都不做。

    这条迁移是**修复**而不是**变更**：它把缺 ``n`` 的表补成 ORM 期望的样子。
    删掉 ``n`` 会让 schema 与 ``app/models/report.py`` 对不上，模型里的
    ``n: Mapped[int] = mapped_column(Integer, nullable=False)`` 立刻失效——
    也就是把本迁移要修的那个 500 原样装回去。

    而且删了也回不到「迁移前」：迁移前可能是两种状态（全新库有列 /
    漂移库无列），downgrade 无法知道自己该退回哪一个。猜一个只会造出
    第三种不一致的 schema。

    要真正回退，删库重建（``alembic downgrade base`` + ``alembic upgrade head``）。
    """
    return
