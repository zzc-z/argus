"""健康检查响应模型。"""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查响应体。

    /api/v1/healthz 与 /api/v1/readyz 共用。
    """

    status: str = Field(description="ok（健康）| unavailable（依赖不可用）")
    service: str = Field(description="服务名，固定 argus-api")
    version: str = Field(description="服务版本")
    detail: str | None = Field(default=None, description="不可用时的原因，OK 时为 null")
