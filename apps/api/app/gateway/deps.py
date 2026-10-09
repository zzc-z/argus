"""鉴权依赖——把「这次请求是谁」变成一个可注入的参数。

放在 gateway 层而不是 services 层：读 cookie 是 HTTP 关注点，
service 只该看到已经解析出来的 User。
"""

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.services.token import InvalidTokenError, decode_access_token

SESSION_COOKIE = "argus_session"
SESSION_COOKIE_PATH = "/"


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    """从会话 cookie 里的 JWT 解出当前用户，失败一律 401。

    缺 cookie / 票据签名不对或过期 / 用户已不存在——这三种都归到同一个
    401 且用同一句提示。对前端来说它们的处理动作完全一样（跳登录页），
    区分开只会让它多写两套没用的分支。
    """
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")

    try:
        user_id = decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录状态已失效，请重新登录") from exc

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录状态已失效，请重新登录")

    return user


# 路由里写 `user: CurrentUser` 即可，等价于 Depends(get_current_user)
CurrentUser = Annotated[User, Depends(get_current_user)]
