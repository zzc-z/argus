"""当前用户相关路由。

只放「跟登录用户自己」有关的端点，不做用户列表、不做用户搜索——
那些属于 W2 的协作场景。
"""

from fastapi import APIRouter

from app.gateway.deps import CurrentUser
from app.schemas.user import MeResponse

router = APIRouter(prefix="/api/v1", tags=["users"])


@router.get("/me", response_model=MeResponse, summary="取当前登录用户")
async def read_me(user: CurrentUser) -> MeResponse:
    """返回当前用户资料。

    这个端点同时充当「登录状态探针」：能拿到 200 就说明 cookie 有效，
    前端不必在刷新页面后再单独调一个校验接口。
    """
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
    )
