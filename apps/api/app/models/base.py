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
    ``timezone=True`` 这个参数被静默忽略。实测 `server_default=func.now()`
    在 SQLite 下存的是 ``'2026-10-13 04:20:31'``（本机时区），
    读回是 **naive** datetime：没有 tzinfo，也没有「它是 UTC」的标记。

    这个洞平时不咬人——直到有代码按 aware 来用。``token.py`` 的
    ``datetime.now(UTC)`` 与库里的 naive 值一比就 ``TypeError``；
    换成 ``datetime.now()`` 又会在换季时差出一个小时，而偏移量没有任何
    地方记着，没法事后判断是几点的记录。

    所以语义在本层钉死：**数据库里一律 UTC，ORM 层一律 aware**。
    写入前统一转 UTC，读出后统一补 ``tzinfo=UTC``。

    ## 为什么按方言分支

    Postgres 的 ``timestamptz`` 自己就会把值归一到 UTC 并在读回时附带
    会话时区，套一层转换只是多两次字符串拼接；而非 UTC 的 Postgres
    会话（``SET TIMEZONE 'Asia/Shanghai'``）下，反而是这一层保证读回
    的一定是 UTC——否则同一张表在不同 worker 上读出不同的偏移量。
    两条分支的对外契约一致：进去 aware，出来 aware + UTC。

    ## 历史数据

    装饰器不迁移已有行。切换前写入的值按 UTC 解读——这个假设成立的前提
    是数据库一直跑在 UTC 容器里；``func.now()`` 那批行若是在非 UTC 机器上
    生成的，需要单独 ``UPDATE`` 修正后再上线。
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
        if value.tzinfo is None:
            # 裸 datetime 按 UTC 解读。静默假设比直接拒绝好：拒绝会让
            # 所有手写 `datetime(2026, 1, 1)` 的调用方（测试、脚本）全炸。
            return value
        if dialect.name == "sqlite":
            # SQLite 的 DATETIME 绑定格式里没有偏移量位置，塞进去会
            # 直接写入字面量 '+00:00'，读回时解析失败。
            return value.astimezone(UTC).replace(tzinfo=None)
        return value.astimezone(UTC)

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
