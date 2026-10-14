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

import logging
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

logger = logging.getLogger(__name__)


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


def _bounce_to_login(settings: Settings, error: str) -> Response:
    """用户放弃授权时送回登录页，而不是抛 400。

    「点取消」是用户的正常选择，不是系统故障。抛 400 会让浏览器停在
    一页裸 JSON 上——用户既看不懂也不知道下一步做什么。跳回登录页并
    把原因带在 query 里，前端读出来显示一行提示即可重新发起。

    error 值来自 GitHub（受控枚举），拼进 Location 前仍做白名单校验，
    只保留字母和下划线，防止意外构造出可注入的 URL。
    """
    safe_error = "".join(ch for ch in error if ch.isalnum() or ch == "_")[:32] or "unknown"
    response = Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={
            "Location": f"{settings.frontend_base_url}/login?error={safe_error}",
        },
    )
    _clear_state_cookie(response, settings)
    return response


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
        return _bounce_to_login(settings, error)

    flow = _load_state_cookie(request, settings)
    returned_state = request.query_params.get("state", "")
    if not returned_state or returned_state != flow.state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "state 校验失败，可能被篡改")

    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少授权码")

    # 与 GitHub 的两次交互都兜住：它们是外部依赖，代理抖动或 GitHub 限流
    # 都可能让连接中途断开。不接住的话异常会一路冒到 FastAPI，用户看到
    # 500 Internal Server Error——既看不懂也不知道能不能重试。
    #
    # 两类故障分开处理，因为排查方向不同：
    #   HTTPStatusError —— GitHub 明确回了错误状态（401 token 失效、
    #                       403 限流）。是我们凭据或请求本身的问题。
    #   其他 HTTPError   —— 连不上（断开、超时、代理错误）。是网络问题，
    #                       用户等一下重试通常就好了。
    try:
        access_token = await _exchange_code_for_token(code, flow.code_verifier, settings)
        profile = await _fetch_github_profile(access_token)
    except httpx.HTTPStatusError as exc:
        logger.warning("GitHub 返回错误状态，登录流程中止", exc_info=exc)
        return _bounce_to_login(settings, "provider_rejected")
    except httpx.HTTPError as exc:
        logger.warning("与 GitHub 通信失败，登录流程中止", exc_info=exc)
        return _bounce_to_login(settings, "provider_unavailable")

    result = await get_or_create_user(session, profile)

    redirect = Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"{settings.frontend_base_url}/dashboard"},
    )
    # session cookie 的属性，逐条都有理由：
    #
    # - httponly：JS 读不到，XSS 也偷不走（OWASP 必须项）
    # - secure：默认 True，见 config.cookie_secure
    # - samesite=lax：挡住跨站 POST（OWASP 认可 lax 为可接受）。选 lax 而非
    #   strict 的具体代价未逐一核过——session cookie 只被 require_current_user
    #   读（deps.py），而挂它的 /me、/research/ask、/sources 都不是靠跨站导航
    #   到达的，理论上升到 strict 不会断登录。没实测过就不下结论。
    # - path=/：会话 cookie 服务于**所有** API，不只 auth。收窄到 /api/v1/auth
    #   会让 /api/v1/research/ask 读不到
    # - **不设 domain**：不发 Domain 属性 → cookie 只发给设它的那个确切主机，
    #   不会外溢到任何子域。这是 OWASP 建议的 __Host- / __Secure- 前缀真正
    #   起作用的那部分。
    #
    # 没有用 `__Host-` 前缀是有意的（2026-10-14 查过）：它强制 Secure，而
    # http://localhost 下浏览器是否接受 Secure cookie 各家不一致（MDN 明确
    # 标注 Safari 不支持），本地开发会时好时坏。argus 无子域，前缀带来的防
    # 子域伪造收益本就为零。
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
    依然能通过校验。真要立刻失效得加撤销名单（黑名单表 / Redis）。

    ## 为什么现在不做撤销（这是权衡，不是规范许可）

    OWASP Session Management 把「会话到期或用户主动登出时必须采取主动措施」
    列为对 web 应用的要求。本项目**有意偏离**它：

    - 7 天窗口内窃取 cookie 的攻击者本来就能直接调任何接口，黑名单只把
      「立刻失效」变成「每次请求多一次在线校验」，并不能挽回已发生的泄露；
    - 撤销名单本身要有状态（DB 表或 Redis），而这个项目的数据层是单机
      SQLite——为「事后失效」引入一个必须与主库保持一致的第二份状态，
      失败模式（名单写了但库挂了 → 撤销失效）比它要解决的问题更糟；
    - OWASP 同一份文档也写着建议「会话标识在登录时重新生成」，本项目的
      登录态本就是每次登录重新签发 JWT，没有可重放的旧标识。

    这是风险取舍。**触发重新评估的条件**：接入多实例部署、账号体系开放给
    他人使用、或开始承载任何「泄露后必须立即止血」的数据（支付、密钥、他人
    私有内容）。届时按 OWASP 的建议加 denylist，键用 ``jti`` 而不是 JWT
    原文——原文当键会被 malleability 绕过。

    另见 OWASP JWT Cheat Sheet 关于「JWT 也能做用户会话，只需额外解决
    失效问题」的说明；浏览器侧架构要求见 RFC 10017（OAuth 2.0 for
    Browser-Based Applications），其安全要求派生自 RFC 9700（BCP 240）。
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
