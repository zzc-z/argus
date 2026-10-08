"""ORM 基类。

所有模型继承 ``Base``，SQLAlchemy 会把它们登记到 ``Base.metadata``，
Alembic 生成 migration 时靠遍历这份注册表对比数据库实际结构。

新增模型后必须在这里 import，否则 Alembic 找不到它：
    from app.models import user  # noqa: F401
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
