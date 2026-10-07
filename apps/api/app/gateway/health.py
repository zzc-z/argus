"""健康检查路由。

两个探针的语义不同，K8s 里分别配 livenessProbe / readinessProbe：

- ``/api/v1/healthz``（liveness）——进程活着就 200。**不查任何外部依赖**，
  否则 DB 挂了会触发无限重启循环，而重启救不了外部依赖。
- ``/api/v1/readyz``（readiness）——DB 连得上才 200，否则 503。
  失败只让 K8s 摘流量，不重启容器。
"""

from fastapi import APIRouter, Response, status

from app.db import check_db_health
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])

SERVICE_NAME = "argus-api"
SERVICE_VERSION = "0.1.0"


def _ok() -> HealthResponse:
    """构造健康响应体。响应结构在两个端点间保持一致，监控解析逻辑只需一套。"""
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="存活探针",
    description="进程存活即返回 200，不检查任何外部依赖。",
)
async def healthz() -> HealthResponse:
    return _ok()


@router.get(
    "/readyz",
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
    return _ok()
