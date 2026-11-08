"""FastAPI 应用入口—— 只做装配，不写业务。

职责边界（docs/STRUCTURE.md 约定）：
- 本文件：创建 app 实例、注册 lifespan、挂中间件、include_router
- app/gateway/：所有 HTTP 路由（health / auth / sources / reports ...）
- app/services/：业务逻辑
- app/repositories/：数据访问

API 前缀统一 /api/v1（2026-10-06 决策），由各router 自己声明 prefix。
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.gateway import (
    auth_router,
    dashboard_router,
    health_router,
    reports_router,
    research_router,
    sources_router,
    users_router,
)
from app.security import SecurityHeadersMiddleware, build_security_headers

_settings = get_settings()


def _configure_logging() -> None:
    """配置 root logger，让应用自己的 ``logger.info`` 能输出。

    ## 为什么必须配

    uvicorn 只配置它自己的 ``uvicorn.*`` logger，**root logger 留在
    WARNING**（Python 默认）。于是全仓 9 处 ``logger.info`` 全部被
    静默丢弃——包括「研究被取消，落盘已生成的部分」这种关键事件。

    症状极隐蔽：代码明明写了日志，日志里就是没有。排查时会以为是
    那段代码没执行。

    ## 为什么只配 app 命名空间

    root logger 一旦设成 INFO，第三方库的 INFO 也会涌进来（httpx、
    asyncio 之类），把真正的日志淹掉。所以只把 ``app.*`` 设成 INFO，
    其它保持 WARNING。

    uvicorn 自己的日志级别由 ``--log-level`` 控制，不受这里影响。

    ## 依赖 uvicorn 的加载顺序（实测确认）

    uvicorn 的 ``Config.load()`` 会 import 应用模块——所以本函数运行时，
    uvicorn 已经先用 ``dictConfig`` 配好了它的 logger（root 置成
    「无 handler + WARNING」）。于是 ``basicConfig`` 能装上 root 的
    handler。

    **若把本函数挪进 lifespan，root 会变成 INFO**，第三方库（httpx、
    asyncio 之类）的 INFO 全涌进来。改这里之前先读一遍
    ``uvicorn/config.py`` 的 ``configure_logging``。
    """
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("app").setLevel(logging.INFO)


_configure_logging()


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
app.include_router(dashboard_router)
