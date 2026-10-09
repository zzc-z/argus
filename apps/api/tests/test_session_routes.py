"""登出与当前用户端点测试。

覆盖两条主线：
- 登录闭环是否打通（OAuth 回调拿到的 cookie 能不能被 /me 认出来）
- 鉴权依赖在各种坏票据下是否都统一 401
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.gateway import auth as auth_module
from app.gateway.deps import SESSION_COOKIE
from app.models import Provider, User
from app.services.auth import OAuthProfile
from app.services.token import create_access_token


async def _make_user(
    db: AsyncSession,
    *,
    email: str = "alice@example.com",
    display_name: str = "Alice",
) -> User:
    user = User(email=email, display_name=display_name, avatar_url="https://x/1.png")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _login(client: TestClient, monkeypatch: pytest.MonkeyPatch, github_state: str) -> str:
    """跑完一次 OAuth 回调，把 session cookie 写进 client。返回 JWT。"""

    async def _fake_exchange(code: str, code_verifier: str, settings: object) -> str:
        return "gho_test_token"

    async def _fake_profile(access_token: str) -> OAuthProfile:
        return OAuthProfile(
            provider=Provider.GITHUB,
            provider_account_id="12345",
            email="alice@example.com",
            display_name="Alice",
            avatar_url="https://x/1.png",
        )

    monkeypatch.setattr(auth_module, "_exchange_code_for_token", _fake_exchange)
    monkeypatch.setattr(auth_module, "_fetch_github_profile", _fake_profile)

    resp = client.get(
        f"/api/v1/auth/github/callback?code=abc&state={github_state}",
        follow_redirects=False,
    )
    assert resp.status_code == 307
    return resp.headers["set-cookie"].split(f"{SESSION_COOKIE}=")[1].split(";")[0]


# ── 闭环：OAuth 拿到的票据能被 /me 认出来 ────────────────────


def test_me_returns_profile_after_oauth_login(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, github_state: str
) -> None:
    """登录 → 调 /me 能拿到同一份资料，闭环通了。"""
    _login(client, monkeypatch, github_state)

    resp = client.get("/api/v1/me")

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["display_name"] == "Alice"
    assert body["avatar_url"] == "https://x/1.png"
    assert body["id"] > 0


async def test_me_reflects_latest_db_values_not_stale_jwt_payload(
    client: TestClient, api_db: AsyncSession
) -> None:
    """JWT 里只有 user_id——改了库里资料，/me 立刻返回新值。"""
    user = await _make_user(api_db, display_name="旧名字")
    client.cookies.set(SESSION_COOKIE, create_access_token(user.id))

    user.display_name = "新名字"
    await api_db.commit()

    assert client.get("/api/v1/me").json()["display_name"] == "新名字"


async def test_me_tolerates_user_without_optional_fields(
    client: TestClient, api_db: AsyncSession
) -> None:
    """邮箱/头像都可能为空——隐藏邮箱的 GitHub 用户不能 500。"""
    user = await _make_user(api_db)
    user.email = None
    user.avatar_url = None
    await api_db.commit()
    client.cookies.set(SESSION_COOKIE, create_access_token(user.id))

    body = client.get("/api/v1/me").json()

    assert body["email"] is None
    assert body["avatar_url"] is None


# ── 鉴权依赖的失败路径 ───────────────────────────────────────


def test_me_without_cookie_returns_401(client: TestClient) -> None:
    assert client.get("/api/v1/me").status_code == 401


def test_me_with_garbage_cookie_returns_401(client: TestClient) -> None:
    """乱码票据不能崩，也不能被当成有效。"""
    client.cookies.set(SESSION_COOKIE, "not-a-jwt.at-all")

    assert client.get("/api/v1/me").status_code == 401


def test_me_with_tampered_payload_returns_401(client: TestClient) -> None:
    """改了 payload 但没改签名 → 签名校验失败。"""
    settings = get_settings()
    assert settings.jwt_secret_key is not None
    forged = jwt.encode(
        {"sub": "1", "exp": 9_999_999_999},
        "attacker-secret-" + "0" * 40,
        algorithm=settings.jwt_algorithm,
    )
    client.cookies.set(SESSION_COOKIE, forged)

    assert client.get("/api/v1/me").status_code == 401


async def test_me_with_expired_token_returns_401(client: TestClient, api_db: AsyncSession) -> None:
    """过期票据直接拒——7 天窗口到了就该失效。"""
    user = await _make_user(api_db)
    settings = get_settings()
    assert settings.jwt_secret_key is not None
    past = datetime.now(UTC) - timedelta(days=8)
    expired = jwt.encode(
        {"sub": str(user.id), "iat": past, "exp": past + timedelta(hours=1)},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    client.cookies.set(SESSION_COOKIE, expired)

    assert client.get("/api/v1/me").status_code == 401


async def test_me_with_valid_token_for_deleted_user_returns_401(
    client: TestClient, api_db: AsyncSession
) -> None:
    """票据本身有效、但用户已被删 → 仍要 401，否则会读到空对象。"""
    user = await _make_user(api_db)
    token = create_access_token(user.id)

    await api_db.delete(user)
    await api_db.commit()
    client.cookies.set(SESSION_COOKIE, token)

    assert client.get("/api/v1/me").status_code == 401


# ── 登出 ────────────────────────────────────────────────────


def test_logout_clears_session_cookie(client: TestClient) -> None:
    """登出必须删 cookie，且 path 与下发时一致（否则浏览器删不掉）。"""
    resp = client.post("/api/v1/auth/logout")

    assert resp.status_code == 204
    raw = resp.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in raw
    assert "Max-Age=0" in raw or "expires=Thu, 01 Jan 1970" in raw.lower()
    assert "Path=/" in raw


def test_logout_is_idempotent(client: TestClient) -> None:
    """没登录也返回 204——前端不必先判断状态。"""
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_me_returns_401_after_logout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, github_state: str
) -> None:
    """登录 → 登出 → /me 变 401，这是整个闭环的验收点。"""
    _login(client, monkeypatch, github_state)
    assert client.get("/api/v1/me").status_code == 200

    client.post("/api/v1/auth/logout")

    assert client.get("/api/v1/me").status_code == 401
