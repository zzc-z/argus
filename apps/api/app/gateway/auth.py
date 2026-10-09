"""OAuth 登录路由（GitHub）。

安全设计对齐 RFC 9700（2026 OAuth 安全 BCP）：
- 授权码流程（不用已废弃的 Implicit Grant）
- PKCE 强制 S256——防授权码拦截
- state 参数——防 CSRF
- redirect_uri 精确匹配

state 与 code_verifier 放在itsdangerous 签名 cookie 里，而非 Authlib 默认的
session 存储或 Redis：无状态、多worker 安全（登录请求打A worker、
回调打 B worker 也能校验），且带签名防篡改。

不用 Authlib 的 authorize_access_token——那个方法依赖 request.session，
会与argus 自己的 JWT cookie 方案打架。这里只用它的底层 OAuth2Client，
state 校验与 token 交换都自己控制。
"""

from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from authlib.common.security import generate_token
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.gateway.deps import SESSION_COOKIE, SESSION_COOKIE_PATH
from app.models import Provider
from app.services.auth import OAuthProfile, get_or_create_user
from app.services.token import create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

OAUTH_STATE_COOKIE = "argus_oauth_state"
OAUTH_TTL_SECONDS = 600  # 10 分钟，OAuth 往返的合理上限
GITHUB_SCOPE = "read:user user:email"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE = "https://api.github.com"


@dataclass(frozen=True, slots=True)
class OAuthFlowState:
    """登录流程中间态，序列化后存进签名 cookie。"""

    state: str
    code_verifier: str


def build_oauth_client(settings: Settings) -> OAuth:
    """装配 Authlib 的 OAuth 客户端（只用到它的 register/create_client 能力）。"""
    oauth = OAuth()
    client_id = settings.github_oauth_client_id
    client_secret = settings.github_oauth_client_secret
    if client_id is None or client_secret is None:
        raise RuntimeError("GitHub OAuth 凭据未配置，无法初始化登录流程")

    oauth.register(
        name="github",
        client_id=client_id,
        client_secret=client_secret.get_secret_value(),
        access_token_url=GITHUB_TOKEN_URL,
        authorize_url=GITHUB_AUTHORIZE_URL,
        # S256 是 RFC 7636 里唯一不会泄露 verifier 的方法，
        # plain 绝对不用。设了这个 create_authorization_url 才会算 challenge。
        client_kwargs={"scope": GITHUB_SCOPE, "code_challenge_method": "S256"},
    )
    return oauth


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    secret = settings.jwt_secret_key
    if secret is None:
        raise RuntimeError("JWT_SECRET_KEY 未配置，无法签发登录流程 cookie")
    return URLSafeTimedSerializer(secret.get_secret_value(), salt="argus-oauth")


def _set_state_cookie(response: Response, settings: Settings, flow: OAuthFlowState) -> None:
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=_serializer(settings).dumps({"state": flow.state, "verifier": flow.code_verifier}),
        max_age=OAUTH_TTL_SECONDS,
        httponly=True,      # JS 读不到——XSS 也偷不走
        secure=settings.cookie_secure,
        samesite="lax",     # OAuth callback 是顶级导航 GET，lax 刚好放行
        path="/api/v1/auth",  # 只在 auth 路径上传，缩小暴露面
    )


def _load_state_cookie(request: Request, settings: Settings) -> OAuthFlowState:
    raw = request.cookies.get(OAUTH_STATE_COOKIE)
    if raw is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登录流程已失效，请重新发起")

    try:
        data = _serializer(settings).loads(raw, max_age=OAUTH_TTL_SECONDS)
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登录超时，请重新发起") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登录流程校验失败") from exc

    return OAuthFlowState(state=data["state"], code_verifier=data["verifier"])


def _clear_state_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/v1/auth")


@router.get("/github/login", summary="发起 GitHub 登录")
async def github_login(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """生成授权 URL并 302 跳转到 GitHub。

    state 与 PKCE verifier 一并写进签名 cookie，回调时取回校验。
    """
    # Authlib 的 create_client 无返回类型标注，只能 ignore 到调用点。
    client = build_oauth_client(settings).create_client("github")  # type: ignore[no-untyped-call]
    flow = OAuthFlowState(state=generate_token(32), code_verifier=generate_token(48))

    result = await client.create_authorization_url(
        settings.github_oauth_callback_url,
        code_verifier=flow.code_verifier,
        state=flow.state,
    )
    response = Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": str(result["url"])},
    )
    _set_state_cookie(response, settings, flow)
    return response


@router.get("/github/callback", summary="GitHub 登录回调")
async def github_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """校验 state → 换 token → 拉用户资料 → 建/找用户 → 签发 argus JWT。

    三个安全检查任一不过即拒绝：
      1. state 签名 cookie 存在且未过期（itsdangerous 验签）
      2. 回调带回的 state 与 cookie 里的一致（防 CSRF）
      3. PKCE verifier 附在换 token 的请求里（防授权码拦截）
    """
    error = request.query_params.get("error")
    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"GitHub 拒绝授权：{error}")

    flow = _load_state_cookie(request, settings)
    returned_state = request.query_params.get("state", "")
    if not returned_state or returned_state != flow.state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "state 校验失败，可能被篡改")

    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少授权码")

    access_token = await _exchange_code_for_token(code, flow.code_verifier, settings)
    profile = await _fetch_github_profile(access_token)
    result = await get_or_create_user(session, profile)

    redirect = Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"{settings.frontend_base_url}/dashboard"},
    )
    redirect.set_cookie(
        key=SESSION_COOKIE,
        value=create_access_token(result.user.id),
        max_age=settings.jwt_expire_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=SESSION_COOKIE_PATH,
    )
    _clear_state_cookie(redirect, settings)
    return redirect


@router.post("/logout", summary="登出")
async def logout() -> Response:
    """删掉会话 cookie，客户端即退出登录。

    不校验当前是否已登录——重复登出返回 200 才对，
    前端不必先判断状态再决定调不调。

    服务端不存 session，所以「已发出去的 JWT」在过期前（默认 7 天）
    依然能通过校验。真要立刻失效得加撤销名单（黑名单表 / Redis），
    当前不做：7 天窗口内窃取 cookie 的攻击者本来就能直接调任何接口，
    黑名单只把「立刻失效」变成「需要额外的在线校验」，收益不大。
    """
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path=SESSION_COOKIE_PATH)
    return response


async def _exchange_code_for_token(
    code: str,
    code_verifier: str,
    settings: Settings,
) -> str:
    """用授权码 + PKCE verifier 换 access_token。

    客户端认证用 client_secret 走 HTTP Basic（GitHub 要求），
    code_verifier 让 GitHub 校验 SHA256(verifier) == 授权请求里的 challenge，
    没有 verifier 的截获者换不到 token。
    """
    client_id = settings.github_oauth_client_id
    client_secret = settings.github_oauth_client_secret
    if client_id is None or client_secret is None:
        raise RuntimeError("GitHub OAuth 凭据未配置")

    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret.get_secret_value(),
                "code": code,
                "redirect_uri": settings.github_oauth_callback_url,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "向 GitHub 换取token 失败")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "GitHub 未返回 access_token")
    return str(token)


async def _fetch_github_profile(access_token: str) -> OAuthProfile:
    """用 access_token 调 GitHub API 拿用户资料，转成统一的 OAuthProfile。

    邮箱取/user/emails 里 primary 且 verified 的那条——/user 端点在用户
    隐藏邮箱时返回 null。自动账号关联依赖「邮箱已验证」这个前提，
    所以不能用未验证条目。
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=10.0) as http:
        user_resp = await http.get(f"{GITHUB_API_BASE}/user", headers=headers)
        user_resp.raise_for_status()
        data: dict[str, Any] = user_resp.json()

        email = data.get("email")
        if not email:
            emails_resp = await http.get(f"{GITHUB_API_BASE}/user/emails", headers=headers)
            emails_resp.raise_for_status()
            for item in emails_resp.json():
                if item.get("primary") and item.get("verified"):
                    email = item["email"]
                    break

    return OAuthProfile(
        provider=Provider.GITHUB,
        provider_account_id=str(data["id"]),
        email=email,
        display_name=data.get("name") or data.get("login"),
        avatar_url=data.get("avatar_url"),
    )
