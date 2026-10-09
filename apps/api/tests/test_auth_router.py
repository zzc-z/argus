"""OAuth 路由测试。

不用 respx——TestClient 走 ASGI transport，respx 会把 TestClient 自己的请求
也拦掉。改用 monkeypatch 直接替换两个发HTTP 请求的函数：
app.gateway.auth._exchange_code_for_token 与 _fetch_github_profile。

这样测的是「argus 自己的逻辑」：state 校验、PKCE 传递、JWT 签发、
cookie 属性——外部 HTTP 交互被桩函数接管，行为完全确定。
"""

from urllib.parse import parse_qs, urlparse

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
    """用户在 GitHub 点「取消授权」→ 400 且带原因。"""
    resp = client.get(f"/api/v1/auth/github/callback?error=access_denied&state={github_state}")

    assert resp.status_code == 400
    assert "拒绝授权" in resp.json()["detail"]


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
