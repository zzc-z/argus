"""FastAPI 应用入口。

- ``lifespan``：启动 / 关闭钩子，取代已废弃的 ``@app.on_event``。
- ``/api/v1/healthz``：liveness 探针，进程活着就返回 200。
- ``/api/v1/readyz``：readiness 探针，DB 连得上才返回 200，否则 503。

API 前缀统一为 ``/api/v1``（2026-10-06 决策），后续所有 endpoint 都挂在这个前缀下。
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import check_db_health
from app.schemas.health import HealthResponse

_settings = get_settings()

SERVICE_NAME = "argus-api"
SERVICE_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期钩子。

    ``yield`` 之前 = 启动阶段（此处暂无重资源，engine 在 app.db 导入时已建）。
    ``yield`` 之后 = 关闭阶段（Day 5 接 Redis 时在此关闭连接）。
    """
    yield


app = FastAPI(
    title="Argus API",
    description="Argus 多智能体研究助手 · 后端服务",
    version=SERVICE_VERSION,
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


@app.get(
    "/api/v1/healthz",
    response_model=HealthResponse,
    summary="存活探针",
    description="进程存活即返回 200，不检查任何外部依赖。",
)
async def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )


@app.get(
    "/api/v1/readyz",
    response_model=HealthResponse,
    summary="就绪探针",
    description="数据库连接可用才返回 200，否则 503。",
)
async def readyz(response: Response) -> HealthResponse:
    try:
        await check_db_health()
    except Exception as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="unavailable",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            detail=type(exc).__name__,
        )
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )
