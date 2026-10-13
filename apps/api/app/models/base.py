"""ORM 基类与共用的列类型。

所有模型继承 ``Base``，SQLAlchemy 会把它们登记到 ``Base.metadata``，
Alembic 生成 migration 时靠遍历这份注册表对比数据库实际结构。

新增模型后必须在这里 import，否则 Alembic 找不到它：
    from app.models import user  # noqa: F401
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """时间列：落库存 UTC naive，读回来一定是 aware。

    ## 为什么需要它

    ``DateTime(timezone=True)`` 只在**方言支持**时才有意义。Postgres 有
    ``timestamptz``，列本身带时区；**SQLite 没有**——它只存一串字符串，
    ``timezone=True`` 这个参数被静默忽略。落库的值是对的（实测 SQLite
    的 ``CURRENT_TIMESTAMP`` 与 ``datetime.now(UTC)`` 逐秒一致，它按定义
    就是 UTC，与机器时区无关），但**读回来是 naive**：没有 tzinfo，
    也没有「它是 UTC」的标记。

    问题就在这个标记上。Python 侧 ``aware - naive`` 直接抛 ``TypeError``，
    而 ``naive - naive`` 会静默给出一个没有意义的差值——换季时还能对得上，
    跨时区就差 8 小时，而偏移量没有任何地方记着，事后无从判断是几点的
    记录。所以语义在本层钉死：**数据库里一律 UTC，ORM 层一律 aware**。

    ## 为什么按方言分支

    Postgres 的 ``timestamptz`` 自己会把值归一到 UTC 并在读回时附带会话
    时区，套一层转换只是多两次字符串拼接；而非 UTC 的 Postgres 会话
    （``SET TIMEZONE 'Asia/Shanghai'``）下，反而是这一层保证读回的一定是
    UTC——否则同一张表在不同 worker 上读出不同的偏移量。两条分支的对外
    契约一致：进去 aware，出来 aware + UTC。

    ## 历史数据

    **无需迁移。** SQLite 的 ``CURRENT_TIMESTAMP`` 与 Postgres 的 ``now()``
    都返回 UTC，装饰器只是补回 Python 侧丢掉的 tzinfo 标记，读出来的
    值与之前完全一致，只是多了个 UTC 标注。

    （此前这里写着「若在非 UTC 机器上生成需 UPDATE 修正」，那是错的——
    ``CURRENT_TIMESTAMP`` 与机器时区无关。照那条做会把所有历史时间戳
    平移一个时区偏移，把正确的数据改坏。）
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        # naive 按 UTC 解读后再归一。**不能**在 naive 时直接 return：
        # SQLite 侧原样返回确实等价于「按 UTC 解读」，但 Postgres 会按会话
        # 的 TimeZone GUC 解释裸 datetime（``SET TIMEZONE 'Asia/Shanghai'``
        # 下写 datetime(2026,3,1,12,0) 会落成 04:00+00，静默差 8 小时）。
        # 补上 UTC 再走方言分支，两边才真的是同一个语义。
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        if dialect.name == "sqlite":
            # SQLite 的 DATETIME 绑定格式里没有偏移量位置，塞进去会
            # 直接写入字面量 '+00:00'，读回时解析失败。
            return aware.astimezone(UTC).replace(tzinfo=None)
        return aware.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
