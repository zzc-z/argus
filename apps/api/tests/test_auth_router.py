"""OAuth 路由测试。

不用 respx——TestClient 走 ASGI transport，respx 会把 TestClient 自己的请求
也拦掉。改用 monkeypatch 直接替换两个发HTTP 请求的函数：
app.gateway.auth._exchange_code_for_token 与 _fetch_github_profile。

这样测的是「argus 自己的逻辑」：state 校验、PKCE 传递、JWT 签发、
cookie 属性——外部 HTTP 交互被桩函数接管，行为完全确定。
"""

from urllib.parse import parse_qs, quote, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway import auth as auth_module
from app.gateway.auth import OAUTH_STATE_COOKIE
from app.models import Account, Provider, User
from app.services.auth import OAuthProfile
from app.services.token import decode_access_token


def _stub_github(
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str | None = "alice@example.com",
) -> dict[str, object]:
    """把两个 HTTP 函数换成桩，记录调用参数供断言。"""
    calls: dict[str, object] = {}

    async def _fake_exchange(code: str, code_verifier: str, settings: object) -> str:
        calls["code"] = code
        calls["code_verifier"] = code_verifier
        return "gho_test_token"

    async def _fake_profile(access_token: str) -> OAuthProfile:
        calls["access_token"] = access_token
        return OAuthProfile(
            provider=Provider.GITHUB,
            provider_account_id="12345",
            email=email,
            display_name="Alice",
            avatar_url="https://avatars.githubusercontent.com/u/12345",
        )

    monkeypatch.setattr(auth_module, "_exchange_code_for_token", _fake_exchange)
    monkeypatch.setattr(auth_module, "_fetch_github_profile", _fake_profile)
    return calls


def _extract_jwt(set_cookie_header: str) -> str:
    return set_cookie_header.split("argus_session=")[1].split(";")[0]


# ── 授权 URL 生成 ────────────────────────────────────────────


def test_login_redirects_to_github(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/github/login", follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"].startswith("https://github.com/login/oauth/authorize")


def test_login_url_carries_pkce_and_state(client: TestClient) -> None:
    """授权 URL 必须带 PKCE challenge（S256）与 state。"""
    location = client.get("/api/v1/auth/github/login", follow_redirects=False).headers["location"]

    assert "code_challenge=" in location
    assert "code_challenge_method=S256" in location
    assert "state=" in location
    assert "client_id=" in location
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fv1%2Fauth%2Fgithub%2Fcallback" in location


def test_pkce_challenge_differs_per_request(client: TestClient) -> None:
    """每次登录生成新的 verifier——否则 challenge 可被重放。"""
    first = client.get("/api/v1/auth/github/login", follow_redirects=False).headers["location"]
    second = client.get("/api/v1/auth/github/login", follow_redirects=False).headers["location"]

    def challenge(url: str) -> str:
        return parse_qs(urlparse(url).query)["code_challenge"][0]

    assert challenge(first) != challenge(second)


def test_login_sets_httponly_state_cookie(client: TestClient) -> None:
    """state cookie 必须 HttpOnly + SameSite=lax，JS 读不到。"""
    raw = client.get("/api/v1/auth/github/login", follow_redirects=False).headers["set-cookie"]

    assert OAUTH_STATE_COOKIE in raw
    assert "HttpOnly" in raw
    assert "SameSite=lax" in raw
    assert "Path=/api/v1/auth" in raw


def test_scope_is_minimal(client: TestClient) -> None:
    """只申请读用户资料与邮箱，不申请仓库权限。"""
    location = client.get("/api/v1/auth/github/login", follow_redirects=False).headers["location"]
    scopes = parse_qs(urlparse(location).query)["scope"][0].split()

    assert scopes == ["read:user", "user:email"]
    assert "repo" not in scopes


# ── 三道安全闸 ───────────────────────────────────────────────


def test_callback_without_state_cookie_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/github/callback?code=abc&state=xyz")

    assert resp.status_code == 400
    assert "失效" in resp.json()["detail"]


def test_callback_with_mismatched_state_rejected(client: TestClient, github_state: str) -> None:
    """state cookie 与回调参数不一致 → 400（防 CSRF）。"""
    resp = client.get("/api/v1/auth/github/callback?code=abc&state=forged-state")

    assert resp.status_code == 400
    assert "state 校验失败" in resp.json()["detail"]


def test_callback_with_tampered_cookie_rejected(client: TestClient) -> None:
    """state cookie 被改过 → 签名校验失败 → 400。"""
    client.get("/api/v1/auth/github/login", follow_redirects=False)
    client.cookies.set(OAUTH_STATE_COOKIE, "forged.payload.sig")

    resp = client.get("/api/v1/auth/github/callback?code=abc&state=forged")

    assert resp.status_code == 400
    assert "校验失败" in resp.json()["detail"]


def test_callback_handles_provider_denial(client: TestClient, github_state: str) -> None:
    """用户在 GitHub 点「取消授权」→ 送回登录页并带 error，不抛 400。

    点取消是用户的正常选择，不是系统故障——浏览器不能停在裸 JSON 上。
    """
    resp = client.get(
        f"/api/v1/auth/github/callback?error=access_denied&state={github_state}",
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert resp.headers["location"] == (
        "http://localhost:3000/login?error=access_denied&next=%2Fdashboard"
    )


def test_denial_clears_state_cookie(client: TestClient, github_state: str) -> None:
    """拒绝后 state cookie 必须清掉，否则下次发起登录会撞上旧的。"""
    resp = client.get(
        f"/api/v1/auth/github/callback?error=access_denied&state={github_state}",
        follow_redirects=False,
    )

    assert f"{OAUTH_STATE_COOKIE}=" in resp.headers["set-cookie"]
    assert "Max-Age=0" in resp.headers["set-cookie"]


def test_denial_error_param_is_sanitized(client: TestClient) -> None:
    """error 值拼进 Location 前做白名单过滤，防止 URL 注入。"""
    resp = client.get(
        "/api/v1/auth/github/callback?error=../../evil%23path",
        follow_redirects=False,
    )

    location = resp.headers["location"]
    assert location.startswith("http://localhost:3000/login?error=")
    assert ".." not in location
    assert "#" not in location


def test_denial_without_state_cookie_still_redirects(client: TestClient) -> None:
    """拒绝时不校验 state——用户都还没授权，state 有没有都该送回登录页。"""
    resp = client.get("/api/v1/auth/github/callback?error=access_denied", follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"] == (
        "http://localhost:3000/login?error=access_denied&next=%2Fdashboard"
    )


def test_callback_without_code_rejected(client: TestClient, github_state: str) -> None:
    resp = client.get(f"/api/v1/auth/github/callback?state={github_state}")

    assert resp.status_code == 400
    assert "缺少授权码" in resp.json()["detail"]


# ── 完整流程 ─────────────────────────────────────────────────


def test_callback_success_sets_session_cookie(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """完整流程：换 token → 拉资料 → 建用户 → 下发 JWT cookie。"""
    _stub_github(monkeypatch)

    resp = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}",
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert resp.headers["location"] == "http://localhost:3000/dashboard"
    session_cookie = resp.headers["set-cookie"]
    assert "argus_session=" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie


def test_pkce_verifier_forwarded_to_token_exchange(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """换 token 时必须带上 PKCE verifier——GitHub 靠它做 challenge 校验。"""
    calls = _stub_github(monkeypatch)

    client.get(f"/api/v1/auth/github/callback?code=abc&state={github_state}")

    assert calls["code"] == "abc"
    verifier = calls["code_verifier"]
    assert isinstance(verifier, str)
    assert len(verifier) >= 43


async def test_user_and_account_rows_created(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """登录成功后 users 与 accounts 各有一行。"""
    _stub_github(monkeypatch)

    client.get(f"/api/v1/auth/github/callback?code=abc&state={github_state}")

    assert await api_db.scalar(select(func.count()).select_from(User)) == 1
    assert await api_db.scalar(select(func.count()).select_from(Account)) == 1


async def test_second_login_reuses_same_user(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """同一 GitHub 身份二次登录不新建账号，两个 JWT 指向同一 user。"""
    _stub_github(monkeypatch)

    first = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}", follow_redirects=False
    )
    first_jwt = _extract_jwt(first.headers["set-cookie"])

    state2 = parse_qs(
        urlparse(
            client.get("/api/v1/auth/github/login", follow_redirects=False).headers["location"]
        ).query
    )["state"][0]
    second = client.get(
        f"/api/v1/auth/github/callback?code=def&state={state2}", follow_redirects=False
    )
    second_jwt = _extract_jwt(second.headers["set-cookie"])

    assert decode_access_token(first_jwt) == decode_access_token(second_jwt)
    assert await api_db.scalar(select(func.count()).select_from(User)) == 1


def test_github_user_without_email_still_works(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub 隐藏邮箱时也能完成登录（跳过账号关联环节）。"""
    _stub_github(monkeypatch, email=None)

    resp = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}",
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert "argus_session=" in resp.headers["set-cookie"]


# ── 外部依赖故障降级 ────────────────────────────────────────
#
# 与 GitHub 的通信走公网，代理抖动 / GitHub 限流都可能让连接中途断。
# 这些异常必须降级成跳回登录页，而不是冒到 FastAPI 变成 500——
# 用户看到 Internal Server Error 既看不懂，也不知道能不能重试。


def test_network_failure_during_token_exchange_redirects(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """换 token 时连接断开 → 跳回登录页，不抛 500。"""

    async def _boom(code: str, code_verifier: str, settings: object) -> str:
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(auth_module, "_exchange_code_for_token", _boom)

    resp = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}",
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert resp.headers["location"] == (
        "http://localhost:3000/login?error=provider_unavailable&next=%2Fdashboard"
    )


def test_network_failure_during_profile_fetch_redirects(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拉用户资料时连接断开（代理抖动最常见的一步）→ 同样降级。"""

    async def _fake_exchange(code: str, code_verifier: str, settings: object) -> str:
        return "gho_test_token"

    async def _boom(access_token: str) -> OAuthProfile:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(auth_module, "_exchange_code_for_token", _fake_exchange)
    monkeypatch.setattr(auth_module, "_fetch_github_profile", _boom)

    resp = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}",
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert "provider_unavailable" in resp.headers["location"]


def test_github_error_status_gets_distinct_code(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub 明确回错（401 等）→ provider_rejected，不跟网络故障混为一谈。

    网络不通是网络问题，重试就好；GitHub 说「这个 token 无效」是我们凭据
    或请求本身有问题，重试没用。两者排查方向不同，错误码必须能区分开。
    """

    async def _fake_exchange(code: str, code_verifier: str, settings: object) -> str:
        return "gho_test_token"

    async def _rejected(access_token: str) -> OAuthProfile:
        raise httpx.HTTPStatusError(
            "401 Unauthorized",
            request=httpx.Request("GET", "https://api.github.com/user"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr(auth_module, "_exchange_code_for_token", _fake_exchange)
    monkeypatch.setattr(auth_module, "_fetch_github_profile", _rejected)

    resp = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}",
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert resp.headers["location"] == (
        "http://localhost:3000/login?error=provider_rejected&next=%2Fdashboard"
    )


async def test_no_user_created_when_provider_unreachable(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """外部故障时不能留下半截数据——users 表应保持为空。"""

    async def _fake_exchange(code: str, code_verifier: str, settings: object) -> str:
        return "gho_test_token"

    async def _boom(access_token: str) -> OAuthProfile:
        raise httpx.ReadTimeout("read timed out")

    monkeypatch.setattr(auth_module, "_exchange_code_for_token", _fake_exchange)
    monkeypatch.setattr(auth_module, "_fetch_github_profile", _boom)

    client.get(f"/api/v1/auth/github/callback?code=abc&state={github_state}")

    assert await api_db.scalar(select(func.count()).select_from(User)) == 0


def test_internal_error_not_exposed_to_user(
    client: TestClient, github_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跳转 URL 里不能出现内部异常细节（网络拓扑、主机名、堆栈）。"""

    async def _boom(code: str, code_verifier: str, settings: object) -> str:
        raise httpx.RemoteProtocolError("connection to 10.0.0.5:443 refused")

    monkeypatch.setattr(auth_module, "_exchange_code_for_token", _boom)

    resp = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}",
        follow_redirects=False,
    )

    location = resp.headers["location"]
    assert "10.0.0.5" not in location
    assert "RemoteProtocolError" not in location
    assert "refused" not in location


class TestLoginNextPath:
    """``?next=`` 深链：登录完成后回到用户原本要去的页面。"""

    @staticmethod
    def _next_in_cookie(client: TestClient) -> str:
        """解出签名 cookie 里的 next 字段。

        cookie 是 itsdangerous 的 base64 签名载荷，**明文里看不到路径**——
        直接在 cookie 字符串上找 `/sources` 是查不出来的（第一版就这么
        写错了）。要 loads 之后再断言。
        """
        raw = client.cookies.get(OAUTH_STATE_COOKIE)
        assert raw is not None, "登录时没写 state cookie"
        # 局部导入：_serializer 需要 settings 里的密钥，走 get_settings()
        # 拿测试环境的配置（conftest 已把它隔离好）。
        from app.config import get_settings
        from app.gateway.auth import _serializer

        return str(_serializer(get_settings()).loads(raw).get("next", ""))

    def test_next_is_stored_in_signed_cookie(self, client: TestClient) -> None:
        client.get("/api/v1/auth/github/login?next=/sources", follow_redirects=False)

        assert self._next_in_cookie(client) == "/sources"

    def test_next_keeps_query_string(self, client: TestClient) -> None:
        """/report/12?tab=bench 这种带 query 的路径要原样保留。"""
        client.get(
            "/api/v1/auth/github/login?next=/report/12%3Ftab%3Dbench",
            follow_redirects=False,
        )

        assert self._next_in_cookie(client) == "/report/12?tab=bench"

    @pytest.mark.parametrize(
        "hostile",
        [
            "https://evil.example/steal",  # 绝对 URL → 开放重定向
            "//evil.example/steal",  # protocol-relative
            "javascript:alert(1)",  # 任意 scheme
            "/path\r\nX-Injected: 1",  # header 注入
        ],
    )
    def test_next_rejects_open_redirect_and_injection(
        self, client: TestClient, hostile: str
    ) -> None:
        """非站内相对路径一律回落到 /dashboard。"""
        client.get(
            f"/api/v1/auth/github/login?next={quote(hostile, safe='')}",
            follow_redirects=False,
        )

        assert self._next_in_cookie(client) == "/dashboard"
