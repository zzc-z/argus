"""argus 自己的登录票据（JWT）签发与校验。

与 OAuth 完全无关——OAuth 负责「证明你是 GitHub 上的谁」，
JWT 负责「证明你是 argus 的哪个用户」。两者密钥必须独立。

payload 只放 user_id，不放 email / display_name 等资料：
票据只用于身份识别，用户资料一律实时读库，避免陈旧数据。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.config import get_settings


class InvalidTokenError(Exception):
    """票据不可用——签名不匹配、已过期或格式非法。

    携带原始异常信息供日志排查，但不透给 HTTP 响应体。
    """


def create_access_token(user_id: int) -> str:
    """为指定用户签发 JWT。

    payload 只含三项：sub（用户 id）、iat（签发时间）、exp（过期时间）。
    不含任何用户资料——资料实时读库。
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_expire_seconds),
    }
    secret = settings.jwt_secret_key
    if secret is None:
        raise RuntimeError("JWT_SECRET_KEY 未配置，无法签发登录票据")

    return jwt.encode(
        payload,
        secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> int:
    """校验 JWT 并返回其中的 user_id。

    任何异常（签名不匹配 / 已过期 / 格式错误）都统一抛 InvalidTokenError，
    不把内部细节透给调用方——调用方只需知道「这个票据不能用」。
    """
    settings = get_settings()
    secret = settings.jwt_secret_key
    if secret is None:
        raise RuntimeError("JWT_SECRET_KEY 未配置，无法校验登录票据")

    try:
        payload = jwt.decode(
            token,
            secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    sub = payload.get("sub")
    if sub is None:
        raise InvalidTokenError("payload 缺少 sub")

    try:
        return int(sub)
    except ValueError as exc:
        raise InvalidTokenError(f"sub 不是合法整数: {sub!r}") from exc
