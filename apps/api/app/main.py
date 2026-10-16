"""FastAPI 应用入口—— 只做装配，不写业务。

职责边界（docs/STRUCTURE.md 约定）：
- 本文件：创建 app 实例、注册 lifespan、挂中间件、include_router
- app/gateway/：所有 HTTP 路由（health / auth / sources / reports ...）
- app/services/：业务逻辑
- app/repositories/：数据访问

API 前缀统一 /api/v1（2026-10-06 决策），由各router 自己声明 prefix。
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.gateway import (
    auth_router,
    health_router,
    reports_router,
    research_router,
    sources_router,
    users_router,
)
from app.security import SecurityHeadersMiddleware, build_security_headers

_settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期钩子。

    ``yield`` 之前 = 启动阶段。当前无重资源需创建（engine 在 app.db 导入时已建为模块级单例）。
    ``yield`` 之后 = 关闭阶段。Day 5 接 Redis 时在此创建/释放连接。

    需要跨端点共享的运行时对象挂到 ``app.state``（如 app.state.redis）。
    """
    yield


app = FastAPI(
    title="Argus API",
    description="Argus 多智能体研究助手 · 后端服务",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全头在最外层：middleware 按注册顺序反向包裹（后注册的先收到请求），
# 所以后加的 SecurityHeaders 会包住 CORS——CORS 拒绝预检时直接短路返回的
# 响应也能带上安全头。app/security.py 解释了为什么这里只有 frame-ancestors
# 而没有完整 CSP。
app.add_middleware(
    SecurityHeadersMiddleware,
    headers=build_security_headers(enable_hsts=_settings.app_env == "prod"),
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(research_router)
app.include_router(sources_router)
app.include_router(reports_router)
