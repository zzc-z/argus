"""网关层：FastAPI 路由 + 依赖装配。

本包只放「HTTP 边界」相关的东西——路由声明、请求/响应校验、鉴权入口。
业务逻辑一律下沉到 app/services/，数据访问挂在 ORM 模型上，
避免路由层变成什么都往里塞的杂物袋。
"""

from app.gateway.auth import router as auth_router
from app.gateway.health import router as health_router
from app.gateway.research import router as research_router
from app.gateway.sources import router as sources_router
from app.gateway.users import router as users_router

__all__ = [
    "auth_router",
    "health_router",
    "research_router",
    "sources_router",
    "users_router",
]
