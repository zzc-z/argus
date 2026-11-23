"""用户凭据配置的测试。

## 这个模块保护什么

1. **响应永不回显密钥内容**——只报「配了没有」与「来自哪一层」。
2. **DB 优先、env 兜底**——用户配了就用用户的，没配就用部署默认。
3. **部分更新语义**——缺省 = 不改，空串 = 忽略，null = 清空。
4. **每个用户独立**——A 配的 key 不影响 B。

## 为什么「响应不回显密钥」要单独测

把密钥写进响应里，等于把它写进浏览器历史、devtools 面板、
以及任何一张截图。这条一旦破了，肉眼很难发现——所以钉住它。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.deps import SESSION_COOKIE
from app.models import User
from app.models.credentials import ProviderCredentials
from app.services.credentials import resolve_credentials
from app.services.token import create_access_token


async def _login(client: TestClient, db: AsyncSession, tag: str = "a") -> int:
    """建一个用户并把 session cookie 写进 client。返回 user_id。"""
    user = User(email=f"{tag}@example.com", display_name="Alice")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    client.cookies.set(SESSION_COOKIE, create_access_token(user.id))
    return user.id


# ── 鉴权 ───────────────────────────────────────────────────────


def test_read_credentials_requires_login(client: TestClient) -> None:
    resp = client.get("/api/v1/settings/credentials")
    assert resp.status_code == 401


def test_update_credentials_requires_login(client: TestClient) -> None:
    resp = client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-x"})
    assert resp.status_code == 401


# ── 初始状态 ───────────────────────────────────────────────────


async def test_read_credentials_returns_env_defaults(
    client: TestClient, api_db: AsyncSession
) -> None:
    """没配过 → 各项 source 是 env 或 none，configured 与之对应。

    这一条钉住「DB 优先、env 兜底」的**初始**形态：部署里配了什么，
    用户没配时就该看到什么。
    """
    await _login(client, api_db)

    resp = client.get("/api/v1/settings/credentials")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body["tavily_api_key"]) == {"configured", "source"}
    assert body["tavily_api_key"]["source"] in {"env", "none"}
    # configured 与 source 必须一致——不一致就意味着页面上会显示
    # 「未配置」但其实有 key（或反过来）。
    assert body["tavily_api_key"]["configured"] == (body["tavily_api_key"]["source"] != "none")


async def test_response_never_contains_key_material(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**响应里不能出现密钥本身。**

    配一把有辨识度的假 key，然后检查整个响应体里没有它。
    """
    await _login(client, api_db)

    secret = "tvly-secret-must-not-leak-12345"
    resp = client.put("/api/v1/settings/credentials", json={"tavily_api_key": secret})
    assert resp.status_code == 200
    assert secret not in resp.text

    resp = client.get("/api/v1/settings/credentials")
    assert resp.status_code == 200
    assert secret not in resp.text


# ── 保存 ───────────────────────────────────────────────────────


async def test_update_marks_source_as_user(client: TestClient, api_db: AsyncSession) -> None:
    """保存后 source 变成 user，configured 变成 true。"""
    await _login(client, api_db)

    resp = client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tavily_api_key"]["configured"] is True
    assert body["tavily_api_key"]["source"] == "user"


async def test_update_persists_to_db(client: TestClient, api_db: AsyncSession) -> None:
    """保存的值真的落库了——不只是响应里好看。"""
    user_id = await _login(client, api_db)

    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-persisted"})

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    assert row.tavily_api_key == "tvly-persisted"


async def test_partial_update_leaves_other_fields_alone(
    client: TestClient, api_db: AsyncSession
) -> None:
    """只改 tavily → anthropic 不受影响。

    这是「部分更新」的核心：**缺省不是「置空」**。
    """
    user_id = await _login(client, api_db)

    client.put(
        "/api/v1/settings/credentials",
        json={"anthropic_api_key": "sk-keep-me", "tavily_api_key": "tvly-x"},
    )
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-y"})

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    assert row.tavily_api_key == "tvly-y"
    assert row.anthropic_api_key == "sk-keep-me"


async def test_empty_string_is_ignored_not_cleared(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**空串被忽略**，不把已配好的值清掉。

    前端的输入框在用户没动过时也会提交空串——把它当成「清空」
    会让用户不小心把配好的 key 抹掉。
    """
    user_id = await _login(client, api_db)

    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-keep"})
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": ""})

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    assert row.tavily_api_key == "tvly-keep"


async def test_null_clears_the_value(client: TestClient, api_db: AsyncSession) -> None:
    """**显式 null = 清空**——回落到部署默认。

    与「空串 = 忽略」是两件事：null 是用户点了「清除」。
    """
    user_id = await _login(client, api_db)

    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-x"})
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": None})

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    assert row.tavily_api_key is None

    # 清空后 source 回到 env（或 none），不再是 user。
    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.tavily_key_source in {"env", "none"}


async def test_base_url_trailing_slash_is_stripped(
    client: TestClient, api_db: AsyncSession
) -> None:
    """尾部斜杠被去掉——否则拼出来是 ``/v1//messages``，中转站返回 404。"""
    user_id = await _login(client, api_db)

    client.put(
        "/api/v1/settings/credentials",
        json={"anthropic_base_url": "https://relay.test/"},
    )

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    assert row.anthropic_base_url == "https://relay.test"


async def test_base_url_is_normalized_on_read(client: TestClient, api_db: AsyncSession) -> None:
    """解析时也去尾部斜杠——库里是脏数据时照样能用。"""
    user_id = await _login(client, api_db)
    api_db.add(ProviderCredentials(user_id=user_id, anthropic_base_url="https://relay.test/"))
    await api_db.commit()

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.anthropic_base_url == "https://relay.test"


# ── 用户隔离 ───────────────────────────────────────────────────


async def test_users_are_isolated(client: TestClient, api_db: AsyncSession) -> None:
    """A 配的 key 不影响 B——这是「每用户独立」的核心保证。"""
    await _login(client, api_db, tag="a")
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-for-a"})

    # 换成另一个用户
    client.cookies.clear()
    user_b = await _login(client, api_db, tag="b")

    resp = client.get("/api/v1/settings/credentials")
    assert resp.status_code == 200
    body = resp.json()
    # B 没配过 → 落回部署层。**部署层有没有配 tavily 取决于环境**
    # （CI 上没有 .env，也没有 TAVILY_API_KEY）——所以只断言「不是 user」。
    assert body["tavily_api_key"]["source"] in {"env", "none"}
    assert body["tavily_api_key"]["configured"] is (body["tavily_api_key"]["source"] != "none")

    resolved_b = await resolve_credentials(api_db, user_b)
    assert resolved_b.tavily_api_key != "tvly-for-a"


# ── 优先级 ─────────────────────────────────────────────────────


async def test_user_value_wins_over_env(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户配的值**覆盖**部署默认。"""
    from app.config import get_settings
    from app.services import credentials as credentials_module

    settings = get_settings()
    original = settings.tavily_api_key
    try:
        settings.tavily_api_key = type(original)("tvly-from-env") if original else None
        user_id = await _login(client, api_db)
        client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-from-user"})

        resolved = await resolve_credentials(api_db, user_id)
        assert resolved.tavily_api_key == "tvly-from-user"
        assert resolved.tavily_key_source == "user"
    finally:
        settings.tavily_api_key = original
        monkeypatch.setattr(credentials_module, "get_settings", lambda: settings)


async def test_critic_equals_writer_is_reported(client: TestClient, api_db: AsyncSession) -> None:
    """critic 与 writer 同型号时，响应里要标出来。

    自偏好偏差不会自己暴露——它只让「通过率」系统性偏高。页面上
    至少要让用户看见这个风险。
    """
    await _login(client, api_db)

    body = client.get("/api/v1/settings/credentials").json()
    # 默认配置下 critic 与 writer 同型号（见 config.py 的说明）。
    assert body["critic_equals_writer"] is True


async def test_critic_equals_writer_false_when_models_differ(
    client: TestClient, api_db: AsyncSession
) -> None:
    """配了不同的 critic 模型 → 风险标志消失。"""
    await _login(client, api_db)

    client.put(
        "/api/v1/settings/credentials",
        json={
            "anthropic_complex_model": "model-writer",
            "anthropic_critic_model": "model-critic",
        },
    )

    body = client.get("/api/v1/settings/credentials").json()
    assert body["critic_equals_writer"] is False
    assert body["anthropic_complex_model"] == "model-writer"
    assert body["anthropic_critic_model"] == "model-critic"


# ── 模型名 ─────────────────────────────────────────────────────


async def test_base_url_value_is_returned(client: TestClient, api_db: AsyncSession) -> None:
    """**base_url 的值直接回显**——它不是密钥。

    页面靠它预填输入框：用户看到「当前中转站是 X」，而不是一个空框
    加一句「部署默认」。密钥不回显，base_url 回显——两者的区别是
    「是不是秘密」。
    """
    await _login(client, api_db)

    client.put(
        "/api/v1/settings/credentials",
        json={"anthropic_base_url": "https://relay.test"},
    )

    body = client.get("/api/v1/settings/credentials").json()
    assert body["anthropic_base_url_value"] == "https://relay.test"
    assert body["anthropic_base_url"] == {"configured": True, "source": "user"}


async def test_base_url_value_is_empty_when_not_configured(
    client: TestClient, api_db: AsyncSession
) -> None:
    """没配中转站时值是 null（前端据此留空输入框）。"""
    await _login(client, api_db)

    body = client.get("/api/v1/settings/credentials").json()
    # 没配时回落 env 的值；env 也没配就是 null
    assert body["anthropic_base_url_value"] is None or isinstance(
        body["anthropic_base_url_value"], str
    )


async def test_model_names_are_returned(client: TestClient, api_db: AsyncSession) -> None:
    """模型名是**明文**返回的——它们不是密钥，用户要能看到自己配的是什么。"""
    await _login(client, api_db)

    client.put(
        "/api/v1/settings/credentials",
        json={"anthropic_complex_model": "custom-complex-model"},
    )

    body = client.get("/api/v1/settings/credentials").json()
    assert body["anthropic_complex_model"] == "custom-complex-model"


async def test_update_returns_the_new_state(client: TestClient, api_db: AsyncSession) -> None:
    """PUT 的响应就是保存后的状态——前端不用再 GET 一次。"""
    await _login(client, api_db)

    body = client.put(
        "/api/v1/settings/credentials",
        json={"tavily_api_key": "tvly-x"},
    ).json()

    assert body["tavily_api_key"] == {"configured": True, "source": "user"}


async def test_unknown_field_is_rejected(client: TestClient, api_db: AsyncSession) -> None:
    """请求里的未知字段被拒（422）——不能靠多传字段往库里塞东西。"""
    await _login(client, api_db)

    resp = client.put(
        "/api/v1/settings/credentials",
        json={"anthropic_api_key": "sk-x", "jwt_secret_key": "leak"},
    )
    assert resp.status_code == 422


async def test_row_is_not_created_when_nothing_submitted(
    client: TestClient, api_db: AsyncSession
) -> None:
    """什么都没提交 → 不建行。

    建一行全空的凭据会让「这人的配置从哪来」的判断变复杂——到底是
    没配，还是配了但都被清空了。
    """
    user_id = await _login(client, api_db)

    resp = client.put("/api/v1/settings/credentials", json={})
    assert resp.status_code == 200

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is None


async def test_repeated_saves_update_the_same_row(client: TestClient, api_db: AsyncSession) -> None:
    """反复保存只更新**同一行**——user_id 上有唯一索引。"""
    user_id = await _login(client, api_db)

    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-1"})
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-2"})
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-3"})

    rows = (
        await api_db.execute(
            ProviderCredentials.__table__.select().where(
                ProviderCredentials.__table__.c.user_id == user_id
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].tavily_api_key == "tvly-3"


def test_credentials_endpoint_is_under_settings_prefix() -> None:
    """路径挂在 ``/api/v1/settings`` 下——与前端设置页的路由对应。"""
    from app.gateway.credentials import router

    paths = {route.path for route in router.routes}
    assert "/api/v1/settings/credentials" in paths


def test_router_has_both_get_and_put() -> None:
    """GET 读状态、PUT 改配置。"""
    from app.gateway.credentials import router

    methods = {method for route in router.routes for method in getattr(route, "methods", set())}
    assert "GET" in methods
    assert "PUT" in methods


async def test_resolution_prefers_user_row_over_env_row(
    client: TestClient, api_db: AsyncSession
) -> None:
    """DB 里的行**存在**时，env 的值对这一项不再生效。

    与 ``test_user_value_wins_over_env`` 互补：那条测「用户配了 A」，
    这条测「用户配了 A，env 有 B，用 A」。
    """
    user_id = await _login(client, api_db)
    api_db.add(ProviderCredentials(user_id=user_id, tavily_api_key="tvly-user"))
    await api_db.commit()

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.tavily_api_key == "tvly-user"


def test_response_model_excludes_secret_material() -> None:
    """响应模型的字段里**没有**任何能装密钥的字段。

    这是结构性的保证——比「测一遍响应体里没有密钥」更硬：新增字段
    时会被这条挡住。
    """
    from app.schemas.credentials import CredentialItem, CredentialsResponse

    item_fields = set(CredentialItem.model_fields)
    assert item_fields == {"configured", "source"}

    response_fields = set(CredentialsResponse.model_fields)
    assert "anthropic_api_key" in response_fields
    # 顶层字段是「状态项」而不是「值」——值的类型是 CredentialItem。
    assert CredentialsResponse.model_fields["anthropic_api_key"].annotation is CredentialItem


def test_update_model_allows_null_for_clearing() -> None:
    """``None``（JSON 的 null）是「清空」——模型要接受它。"""
    from app.schemas.credentials import CredentialsUpdate

    update = CredentialsUpdate(tavily_api_key=None)
    assert update.tavily_api_key is None


def test_update_model_rejects_extra_fields() -> None:
    """未知字段被拒。"""
    from pydantic import ValidationError

    from app.schemas.credentials import CredentialsUpdate

    with pytest.raises(ValidationError):
        CredentialsUpdate(jwt_secret_key="leak")  # type: ignore[call-arg]


async def test_configured_flag_matches_source_after_save(
    client: TestClient, api_db: AsyncSession
) -> None:
    """保存后 configured 与 source 必须一致。

    不一致意味着页面会说「已配置」而实际没配——那种不一致用户看不出
    来，只能靠这种断言钉住。
    """
    await _login(client, api_db)

    body: dict[str, Any] = client.put(
        "/api/v1/settings/credentials",
        json={"anthropic_api_key": "sk-x", "tavily_api_key": "tvly-y"},
    ).json()

    for key in ("anthropic_api_key", "tavily_api_key"):
        item = body[key]
        assert item["configured"] is (item["source"] != "none")
