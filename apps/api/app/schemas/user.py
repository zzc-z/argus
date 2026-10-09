"""用户资料响应模型。"""

from pydantic import BaseModel, ConfigDict, Field


class MeResponse(BaseModel):
    """当前登录用户的公开资料。

    字段都可为空：OAuth 用户可能隐藏邮箱，也可能没设头像。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="argus 用户 id")
    email: str | None = Field(default=None, description="主邮箱，可能为空")
    display_name: str | None = Field(default=None, description="展示名")
    avatar_url: str | None = Field(default=None, description="头像地址")
