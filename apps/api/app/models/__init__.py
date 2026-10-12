"""ORM 模型包。

``Base.metadata`` 只收录「被 import 过」的模型——Alembic autogenerate 依赖这一点，
所以本文件必须把models 包里的每个模块都拉进来。
"""

from app.models.base import Base
from app.models.source import DocumentChunk, Source, SourceStatus, SourceType
from app.models.user import Account, Provider, User

__all__ = [
    "Account",
    "Base",
    "DocumentChunk",
    "Provider",
    "Source",
    "SourceStatus",
    "SourceType",
    "User",
]
