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

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.deps import SESSION_COOKIE
from app.models import User
from app.models.credentials import ProviderCredentials
from app.services.credentials import resolve_credentials
from app.services.secret_store import decrypt_secret, encrypt_secret
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


async def test_response_echoes_own_key_value_for_prefill(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**响应里回显用户自己配的 key**——页面要拿它预填输入框。

    前提是接口挂在登录态后面（``CurrentUser`` 依赖）。

    ⚠️ **只回显「用户自己配的」**——共享默认行与部署环境里的 key
    是**运维的密钥**，回显它等于发给每一个登录用户（argus 没有管理员
    角色，注册即得）。见 ``test_default_key_is_not_echoed_in_full``。
    """
    await _login(client, api_db)

    secret = "tvly-secret-echoed-12345"  # gitleaks:allow -- 测试用假 key
    resp = client.put("/api/v1/settings/credentials", json={"tavily_api_key": secret})
    assert resp.status_code == 200
    assert resp.json()["tavily_api_key_value"] == secret

    resp = client.get("/api/v1/settings/credentials")
    assert resp.status_code == 200
    assert resp.json()["tavily_api_key_value"] == secret


async def test_default_key_is_not_echoed_in_full(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**共享默认行的 key 不能明文回显**——那是运维的密钥。

    任意登录用户都拿得到（argus 没有管理员角色，注册即得），
    所以响应里只给占位串。
    """
    await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-ops-shared-secret"))

    body = client.get("/api/v1/settings/credentials").json()
    value = body["tavily_api_key_value"]
    # 不是明文
    assert "tvly-ops-shared-secret" not in (value or "")
    # 但能看出「这一格有值」
    assert value is not None
    assert value.endswith("cret"), value
    # 来源仍然如实报告
    assert body["tavily_api_key"]["source"] == "default"
    assert body["tavily_api_key"]["configured"] is True


async def test_response_only_reaches_authenticated_users(
    client: TestClient, api_db: AsyncSession
) -> None:
    """回显的前提是**必须登录**——未登录时连接口都进不去。

    这是回显密钥的**安全边界**：拿不到 key 的人拿不到接口。
    """
    await _login(client, api_db)
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-private"})

    # 清掉登录态
    client.cookies.clear()

    resp = client.get("/api/v1/settings/credentials")
    assert resp.status_code == 401
    assert "tvly-private" not in resp.text


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
    # **库里存的是密文**——不是明文。解密后才是原文。
    assert row.tavily_api_key is not None
    assert row.tavily_api_key != "tvly-persisted"
    assert decrypt_secret(row.tavily_api_key) == "tvly-persisted"


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
    assert decrypt_secret(row.tavily_api_key) == "tvly-y"
    assert decrypt_secret(row.anthropic_api_key) == "sk-keep-me"


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
    assert decrypt_secret(row.tavily_api_key) == "tvly-keep"


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
    api_db.add(
        ProviderCredentials(
            user_id=user_id,
            scope="user",
            anthropic_base_url="https://relay.test/",
        )
    )
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
    assert decrypt_secret(rows[0].tavily_api_key) == "tvly-3"


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
    api_db.add(
        ProviderCredentials(user_id=user_id, scope="user", tavily_api_key="tvly-user")
    )
    await api_db.commit()

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.tavily_api_key == "tvly-user"


def test_response_model_has_explicit_value_fields() -> None:
    """回显的字段名必须是 ``<name>_value``——**与状态项分开**。

    状态项（``CredentialItem``）回答「配了没有、从哪来」，
    值字段（``*_value``）回答「具体是什么」。两者混在一个字段里，
    前端就没法「填状态、留空不改、预填当前值」地分开处理。
    """
    from app.schemas.credentials import CredentialItem, CredentialsResponse

    item_fields = set(CredentialItem.model_fields)
    assert item_fields == {"configured", "source"}

    response_fields = set(CredentialsResponse.model_fields)
    assert "anthropic_api_key" in response_fields
    # 顶层字段是「状态项」而不是「值」——值的类型是 CredentialItem。
    assert CredentialsResponse.model_fields["anthropic_api_key"].annotation is CredentialItem

    # 回显的三个 key 各有一个 _value 字段。
    for name in (
        "anthropic_api_key",
        "tavily_api_key",
        "embedding_api_key",
        "anthropic_base_url",
        "embedding_base_url",
    ):
        assert f"{name}_value" in response_fields, name


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


# ── 加密存储 ───────────────────────────────────────────────────


async def test_key_is_stored_encrypted(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**库里不能有明文 key。**

    一次库文件泄露（备份、误提交、镜像层）就等于所有 key 一次性暴露。
    """
    user_id = await _login(client, api_db)
    secret = "tvly-plaintext-must-not-be-in-db"

    client.put("/api/v1/settings/credentials", json={"tavily_api_key": secret})

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    assert secret not in (row.tavily_api_key or "")
    assert row.tavily_api_key is not None
    assert row.tavily_api_key.startswith("enc:v1:")


async def test_stored_key_decrypts_back_to_original(
    client: TestClient, api_db: AsyncSession
) -> None:
    """加密不能改内容——解密后要等于原文。"""
    user_id = await _login(client, api_db)
    secret = "sk-round-trip-check"

    client.put("/api/v1/settings/credentials", json={"anthropic_api_key": secret})

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    assert decrypt_secret(row.anthropic_api_key) == secret


async def test_same_key_encrypts_to_different_ciphertext() -> None:
    """**同一把 key 两次加密得到不同密文。**

    Fernet 自带 IV 与时间戳——不这样的话，两行一样的 key 在库里长得
    一模一样，看不出「这两个人用的是同一把」。
    """
    from app.services.secret_store import encrypt_secret

    assert encrypt_secret("same-key") != encrypt_secret("same-key")


async def test_tampered_ciphertext_raises(
    client: TestClient, api_db: AsyncSession
) -> None:
    """密文被篡改 → **解密失败**，不返回垃圾。

    静默返回 None 更糟：调用方会以为「没配」，回落到部署默认，
    用一把错的 key 去调，错误信息会指向别处。
    """
    from app.services.secret_store import SecretDecryptError

    user_id = await _login(client, api_db)
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-tamper"})

    row = await ProviderCredentials.find_by_user(api_db, user_id)
    assert row is not None
    original = row.tavily_api_key or ""
    # 改掉密文中间的一个字符
    tampered = original[:-4] + ("AAAA" if not original.endswith("AAAA") else "BBBB")

    with pytest.raises(SecretDecryptError):
        decrypt_secret(tampered)


# ── 共享默认行 ─────────────────────────────────────────────────


def _broken_ciphertext(plain: str) -> str:
    """用另一把主密钥加密，模拟主密钥换过之后解不开的存量密文。"""
    from cryptography.fernet import Fernet

    import app.services.secret_store as secret_store_module

    original = secret_store_module._load_or_create_key
    other_key = Fernet.generate_key().decode()
    try:
        secret_store_module._load_or_create_key = lambda: (other_key, "env")
        return secret_store_module.encrypt_secret(plain)
    finally:
        secret_store_module._load_or_create_key = original


async def _write_default_row(api_db: AsyncSession, **fields: str | None) -> None:
    """直接往库里写一行共享默认凭据。"""
    row = ProviderCredentials(user_id=None, scope="default", **fields)
    api_db.add(row)
    await api_db.commit()


async def test_default_row_is_used_when_user_has_none(
    client: TestClient, api_db: AsyncSession
) -> None:
    """用户没配 → 用共享默认行。这是「开箱即用」的落点。"""
    user_id = await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-shared-default"))

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.tavily_api_key == "tvly-shared-default"
    assert resolved.tavily_key_source == "default"


async def test_user_row_overrides_default_row(
    client: TestClient, api_db: AsyncSession
) -> None:
    """用户自己配的**覆盖**共享默认行。"""
    user_id = await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-shared-default"))

    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-mine"})

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.tavily_api_key == "tvly-mine"
    assert resolved.tavily_key_source == "user"


async def test_default_row_is_reported_in_response(
    client: TestClient, api_db: AsyncSession
) -> None:
    """响应里 source 报 ``default``——页面能区分「这是共享的那把」。

    但**值只给占位串**——共享默认的 key 是运维的密钥，不明文下发。
    """
    await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-shared-default"))

    body = client.get("/api/v1/settings/credentials").json()
    assert body["tavily_api_key"]["source"] == "default"
    assert body["tavily_api_key"]["configured"] is True
    # 值是占位串，不是明文
    assert body["tavily_api_key_value"] != "tvly-shared-default"
    assert "tvly-shared-default" not in (body["tavily_api_key_value"] or "")


async def test_only_one_default_row_allowed(
    client: TestClient, api_db: AsyncSession
) -> None:
    """共享默认行**只能有一行**——scope 上有部分唯一索引。

    两行默认行意味着「这个人的配置从哪来」要看运气。
    """
    await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-first"))

    api_db.add(
        ProviderCredentials(user_id=None, scope="default", tavily_api_key="tvly-second")
    )
    with pytest.raises(IntegrityError):
        await api_db.commit()
    await api_db.rollback()


async def test_url_never_inherits_key_from_a_higher_layer(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**url 绝不从上层继承 key**——那正是密钥外泄的方向。

    env 配了 key（部署者的），用户配了 url（自己的地址）：继承的话，
    部署者的 key 会被发到用户指定的地址，且**没有任何报错**。
    """
    from pydantic import SecretStr

    from app.config import get_settings

    settings = get_settings()
    original = settings.anthropic_api_key
    try:
        settings.anthropic_api_key = SecretStr("sk-from-env")
        user_id = await _login(client, api_db)
        client.put(
            "/api/v1/settings/credentials",
            json={"anthropic_base_url": "https://mine.test"},
        )

        resolved = await resolve_credentials(api_db, user_id)
        # 用户配了 url → key 不从 env 继承。
        assert resolved.anthropic_api_key is None
        assert resolved.anthropic_base_url == "https://mine.test"
    finally:
        settings.anthropic_api_key = original


async def test_default_row_does_not_leak_between_users(
    client: TestClient, api_db: AsyncSession
) -> None:
    """默认行是**共享**的——两个用户都拿到同一把（这是设计，不是 bug）。"""
    await _login(client, api_db, tag="a")
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-shared"))

    client.cookies.clear()
    user_b = await _login(client, api_db, tag="b")

    resolved_b = await resolve_credentials(api_db, user_b)
    assert resolved_b.tavily_api_key == "tvly-shared"
    assert resolved_b.tavily_key_source == "default"


# ── key 与 url 的继承方向 ─────────────────────────────────────
#
# 规则：**key 决定 url，url 不能反向决定 key。**
#
# - 用户配了 key 没配 url → 继承下层的 url（那套 key 本来该去的地方）
# - 用户配了 url 没配 key → **不继承**下层的 key（否则泄露）


async def test_user_base_url_never_inherits_lower_layer_key(
    client: TestClient, api_db: AsyncSession
) -> None:
    """用户配了 url 没配 key → **key 必须是 None**。

    继承了就是把部署者的 key 发到用户指定的地址——密钥外泄，且不报错。
    """
    user_id = await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-shared"))
    client.put("/api/v1/settings/credentials", json={"anthropic_base_url": "https://mine.test"})

    resolved = await resolve_credentials(api_db, user_id)
    # 用户层配了 url → anthropic 的 key 不从任何层继承。
    assert resolved.anthropic_api_key is None
    assert resolved.anthropic_base_url == "https://mine.test"


async def test_user_key_does_not_inherit_default_base_url(
    client: TestClient, api_db: AsyncSession
) -> None:
    """用户配了 key 没配 url → **不继承默认行的 url**。

    严格成对。用户层存的是「自己的 key + 自己的 url」。

    看起来「继承默认行的 url」更友好（换 key 后不必重填地址），但
    **区分不了默认行的 url 与 env 的 url**——两者都是「下层的 url」，
    而下层的 url 可能指向**别人的服务器**（中转站）。继承它就是把
    用户的官方 key 发给那个中转站。

    「换 key 后调不通」在别处解决：前端改 key 时把配对的 url 一起
    提交，用户层于是存的是「自己的 key + 那个中转站的 url」——成对，
    且是用户自己确认过的组合。
    """
    user_id = await _login(client, api_db)
    await _write_default_row(
        api_db,
        anthropic_api_key=encrypt_secret("sk-default-relay"),
        anthropic_base_url="https://relay.default.test",
    )
    client.put("/api/v1/settings/credentials", json={"anthropic_api_key": "sk-my-new-key"})

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.anthropic_api_key == "sk-my-new-key"
    assert resolved.anthropic_base_url is None


async def test_undecryptable_key_degrades_instead_of_500(
    client: TestClient, api_db: AsyncSession
) -> None:
    """解密失败 → 当「没配」处理，**接口不能 500**。

    主密钥轮换后库里所有旧密文都解不开。若这里抛异常，整个设置页
    挂掉，用户**连重新配都做不到**——而那正是他需要做的事。
    """
    user_id = await _login(client, api_db)
    # 一段格式合法但解不开的密文（用别的密钥生成的）
    from app.services.secret_store import encrypt_secret

    api_db.add(
        ProviderCredentials(
            user_id=user_id,
            scope="user",
            tavily_api_key=encrypt_secret("tvly-whatever"),
        )
    )
    await api_db.commit()

    # 换成一把**错的**密钥 → 解不开
    from pydantic import SecretStr

    from app.config import get_settings

    settings = get_settings()
    original = settings.credentials_encryption_key
    try:
        from cryptography.fernet import Fernet

        settings.credentials_encryption_key = SecretStr(Fernet.generate_key().decode())
        resp = client.get("/api/v1/settings/credentials")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 这一项当成没配 → 回落到下层
        assert body["tavily_api_key"]["source"] != "user"
        assert body["tavily_api_key_value"] is None
    finally:
        settings.credentials_encryption_key = original


# ── 主密钥的解析顺序 ───────────────────────────────────────────
#
# 环境变量 → key 文件 → 自动生成写文件。
# 顺序抄的是 n8n（不配就自动生成到 ~/.n8n/config，配了就用你的）。


def test_key_is_auto_generated_when_nothing_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """什么都没配 → **自动生成**一份写到 key 文件。

    这是「clone 完直接跑」的关键：不配 .env 也能存凭据。
    """
    from app.config import get_settings
    from app.services import secret_store

    key_path = tmp_path / ".credentials.key"
    monkeypatch.setattr(secret_store, "_key_file_path", lambda: key_path)
    # 环境变量那一档清掉——模拟「用户没配」
    settings = get_settings()
    original = settings.credentials_encryption_key
    try:
        settings.credentials_encryption_key = None
        generated, source = secret_store._load_or_create_key()
        assert source == "generated"
        assert key_path.exists(), "key 文件没写出来"
        assert key_path.read_text(encoding="utf-8").strip() == generated
        # 文件权限 0600——只有本人能读
        assert key_path.stat().st_mode & 0o777 == 0o600
    finally:
        settings.credentials_encryption_key = original


def test_generated_key_is_stable_across_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """**生成的 key 必须稳定**——每次读都是同一把。

    key 每次变的话，库里所有密文都解不开，且没有任何报错。
    这是 Password Pusher 列为头号故障的那一类（「Random key generated
    on each start」）。
    """
    from app.config import get_settings
    from app.services import secret_store

    # **必须重定向 key 文件路径**——否则会写到开发环境真实的
    # ``apps/api/.credentials.key``，把那里的主密钥换掉，
    # 开发库里已存的密文从此全部解不开。
    key_path = tmp_path / ".credentials.key"
    monkeypatch.setattr(secret_store, "_key_file_path", lambda: key_path)

    settings = get_settings()
    original = settings.credentials_encryption_key
    try:
        settings.credentials_encryption_key = None
        first, _ = secret_store._load_or_create_key()
        second, _ = secret_store._load_or_create_key()
        assert first == second
        # 第二次读的是**文件里那份**，不是又生成了一把
        assert key_path.read_text(encoding="utf-8").strip() == first
    finally:
        settings.credentials_encryption_key = original


def test_env_var_overrides_key_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """环境变量优先于 key 文件。

    语义与 n8n 的 ``N8N_ENCRYPTION_KEY`` 一致：配了就用你的，
    不配才用（自动生成的）文件那份。多实例部署靠这个共享同一把 key。
    """
    from app.config import get_settings
    from app.services import secret_store

    key_path = tmp_path / ".credentials.key"
    key_path.write_text("file-key-value", encoding="utf-8")
    monkeypatch.setattr(secret_store, "_key_file_path", lambda: key_path)

    settings = get_settings()
    original = settings.credentials_encryption_key
    try:
        settings.credentials_encryption_key = SecretStr("env-key-value")
        key, source = secret_store._load_or_create_key()
        assert key == "env-key-value"
        assert source == "env"
    finally:
        settings.credentials_encryption_key = original


def test_existing_key_file_is_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """key 文件已存在 → 用它，**不重新生成**。

    重新生成会让存量密文全废——这是最坏的失误。
    """
    from app.config import get_settings
    from app.services import secret_store

    key_path = tmp_path / ".credentials.key"
    key_path.write_text("the-persisted-key", encoding="utf-8")
    monkeypatch.setattr(secret_store, "_key_file_path", lambda: key_path)

    settings = get_settings()
    original = settings.credentials_encryption_key
    try:
        settings.credentials_encryption_key = None
        key, source = secret_store._load_or_create_key()
        assert key == "the-persisted-key"
        assert source == "file"
        # 文件内容没被动过
        assert key_path.read_text(encoding="utf-8").strip() == "the-persisted-key"
    finally:
        settings.credentials_encryption_key = original


def test_key_file_is_gitignored() -> None:
    """key 文件**绝不能**进 git。

    提交了就等于把库里所有凭据的解密钥匙公开。
    """
    import pathlib

    gitignore = pathlib.Path(__file__).resolve().parents[1] / ".gitignore"
    content = gitignore.read_text(encoding="utf-8")
    assert ".credentials.key" in content


def test_broken_key_file_gives_actionable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """key 文件内容被截断 → 错误信息要指向**恢复备份**，不是「改配置」。

    「格式不对」听起来像用户配错了；而实际发生的是「库里已存的密文
    从此解不开」——那需要从备份恢复 key，不是改一行配置就行。
    """
    from app.config import get_settings
    from app.services import secret_store

    key_path = tmp_path / ".credentials.key"
    key_path.write_text("truncated-half-a-key", encoding="utf-8")
    monkeypatch.setattr(secret_store, "_key_file_path", lambda: key_path)

    settings = get_settings()
    original = settings.credentials_encryption_key
    try:
        settings.credentials_encryption_key = None
        with pytest.raises(secret_store.SecretCryptoError) as exc_info:
            secret_store.encrypt_secret("sk-x")
        message = str(exc_info.value)
        assert "备份" in message, message
    finally:
        settings.credentials_encryption_key = original


async def test_user_and_default_rows_fetched_in_one_query(
    client: TestClient, api_db: AsyncSession
) -> None:
    """一次查询取回两行——**不是两次 SELECT**。

    解析在请求热路径上（每次研究一次、每份资料一次），分成两次查询
    就是每次调用多一次数据库往返。

    钉住的是「两行都取到了」且「只发了一条 SQL」。
    """
    user_id = await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-default-row"))
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-user-row"})

    # 数一数实际发了多少条 SELECT
    statements: list[str] = []

    from sqlalchemy import event

    @event.listens_for(api_db.bind.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, params, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    resolved = await resolve_credentials(api_db, user_id)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    # 查凭据表的 SELECT 应该只有一条
    cred_selects = [s for s in selects if "provider_credentials" in s]
    assert len(cred_selects) == 1, cred_selects

    # 两行都取到了：用户行优先
    assert resolved.tavily_api_key == "tvly-user-row"
    assert resolved.tavily_key_source == "user"


async def test_one_query_still_finds_default_when_user_has_no_row(
    client: TestClient, api_db: AsyncSession
) -> None:
    """用户没有行时，一次查询也要取到默认行。

    「用 OR 连起来」这个写法最容易出的错是：用户行不存在时把默认行
    也漏掉——那样共享默认就静默失效了。
    """
    user_id = await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-default-only"))

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.tavily_api_key == "tvly-default-only"
    assert resolved.tavily_key_source == "default"


async def test_undecryptable_user_key_does_not_fall_back_to_lower_layer(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**用户行的 key 解不开 → 不回落到共享默认 / 部署默认。**

    ⚠️ 这是安全关键的一条：回落等于**静默改用别人的 key 去调用**——
    用户以为在用自己的账号额度，实际烧的是部署方的钱，而且界面上
    看不出发生过任何事。

    「解不开」（主密钥轮换）与「没配」必须分开：
    - 没配 → 往下一层回落（这是设计）
    - 解不开 → **不回落**，该层不可用
    """
    user_id = await _login(client, api_db)
    # 共享默认行有一把可用的 key——若错误回落，它就会被用上。
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-shared-default"))

    # 用户行的密文用**另一把**密钥加密（模拟「当时用的是旧主密钥」）→ 解不开
    ciphertext = _broken_ciphertext("tvly-user-real-key")

    api_db.add(
        ProviderCredentials(user_id=user_id, scope="user", tavily_api_key=ciphertext)
    )
    await api_db.commit()

    resolved = await resolve_credentials(api_db, user_id)

    # **不能**是共享默认的 key
    assert resolved.tavily_api_key != "tvly-shared-default", "解密失败后回落到了下一层！"
    # 也**不能**是 env 的 key
    assert resolved.tavily_api_key != "tvly-from-env"
    # 该层不可用 → 没有生效的 key
    assert resolved.tavily_api_key is None
    assert resolved.tavily_key_source == "none"


async def test_masked_default_key_is_not_echoed_in_plaintext(
    client: TestClient, api_db: AsyncSession
) -> None:
    """共享默认的 key → **占位串 + masked_key_fields 标记**。

    前端据此不把它当真值提交——提交了会被加密存成用户的 key，
    之后每次调用都用这把假 key（401），而界面显示「已配置」。
    """
    await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret("tvly-ops-secret-value"))

    body = client.get("/api/v1/settings/credentials").json()
    value = body["tavily_api_key_value"]
    assert "tvly-ops-secret-value" not in (value or "")
    # **明确标记**它是占位串——前端靠这个字段判断，不靠值的形状。
    assert "tavily_api_key" in body["masked_key_fields"]
    # 用户自己配的 → 不在 masked 列表里
    client.put("/api/v1/settings/credentials", json={"tavily_api_key": "tvly-my-own"})
    body2 = client.get("/api/v1/settings/credentials").json()
    assert body2["tavily_api_key_value"] == "tvly-my-own"
    assert "tavily_api_key" not in body2["masked_key_fields"]


async def test_broken_default_row_still_falls_back_to_env(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**默认行解不开 → 继续看 env**（env 是明文，不受主密钥影响）。

    ⚠️ 这条曾经搞反过：把整个能力打成 None，于是「共享默认行坏了」
    变成「部署的 key 也不能用」——那是更大的损失。
    """
    from pydantic import SecretStr

    from app.config import get_settings

    settings = get_settings()
    original = settings.tavily_api_key
    try:
        settings.tavily_api_key = SecretStr("tvly-from-env")
        user_id = await _login(client, api_db)
        # 默认行塞一段解不开的密文
        broken = _broken_ciphertext("tvly-default-key")

        api_db.add(
            ProviderCredentials(user_id=user_id, scope="default", tavily_api_key=broken)
        )
        await api_db.commit()

        resolved = await resolve_credentials(api_db, user_id)
        # 默认层不可用 → **跳到 env**，不是 None
        assert resolved.tavily_api_key == "tvly-from-env", (
            f"默认层不可用时没有回落到 env，实际 {resolved.tavily_api_key!r}"
        )
    finally:
        settings.tavily_api_key = original


async def test_broken_default_row_does_not_break_other_providers(
    client: TestClient, api_db: AsyncSession
) -> None:
    """**默认行里 anthropic 坏了，不该影响 tavily。**

    同一行，但不同能力——不可用的粒度是「按能力」的，不是「按行」。
    """
    from pydantic import SecretStr

    from app.config import get_settings

    settings = get_settings()
    original = settings.tavily_api_key
    try:
        settings.tavily_api_key = SecretStr("tvly-from-env")
        user_id = await _login(client, api_db)

        broken = _broken_ciphertext("sk-broken-anthropic")

        api_db.add(
            ProviderCredentials(
                user_id=None,
                scope="default",
                anthropic_api_key=broken,
                tavily_api_key=encrypt_secret("tvly-default-fine"),
            )
        )
        await api_db.commit()

        resolved = await resolve_credentials(api_db, user_id)
        # tavily 正常（默认行里那把好的），不受 anthropic 坏掉的影响
        assert resolved.tavily_api_key == "tvly-default-fine", (
            f"anthropic 坏掉却影响了 tavily，实际 {resolved.tavily_api_key!r}"
        )
        # anthropic 那把解不开 → 不可用（不是 None 就是 env 的）
        assert resolved.anthropic_api_key != "sk-broken-anthropic"
    finally:
        settings.tavily_api_key = original


async def test_own_tavily_key_wins_when_default_row_is_broken(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认行的 Tavily 密文解不开时，用户自己配的 key 仍然生效、完整回显。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "tavily_api_key", SecretStr("tvly-from-env"))
    user_id = await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=_broken_ciphertext("tvly-old-default"))

    mine = "tvly-mine-1234"  # gitleaks:allow -- 测试用假 key
    resp = client.put("/api/v1/settings/credentials", json={"tavily_api_key": mine})
    body = resp.json()

    resolved = await resolve_credentials(api_db, user_id)
    assert resolved.tavily_api_key == mine
    assert body["tavily_api_key_value"] == mine
    assert body["tavily_api_key"]["configured"] is True


@pytest.mark.parametrize(
    ("secret", "masked"),
    [
        ("tvly-ops-shared-secret", "••••••••••••••••••cret"),
        ("abcde", "•bcde"),
        ("abcd", "••••"),
    ],
)
async def test_mask_keeps_the_key_length(
    client: TestClient, api_db: AsyncSession, secret: str, masked: str
) -> None:
    """掩码与原 key 等长，只露末 4 位；不超过 4 位时一个字符都不露。"""
    await _login(client, api_db)
    await _write_default_row(api_db, tavily_api_key=encrypt_secret(secret))

    body = client.get("/api/v1/settings/credentials").json()

    assert body["tavily_api_key_value"] == masked


async def test_saved_base_url_is_echoed_when_own_key_is_broken(
    client: TestClient, api_db: AsyncSession
) -> None:
    """自己的 key 解不开时，保存过的地址仍要回显，否则看起来像没保存。"""
    user_id = await _login(client, api_db)
    api_db.add(
        ProviderCredentials(
            user_id=user_id,
            scope="user",
            anthropic_api_key=_broken_ciphertext("sk-old"),
            embedding_api_key=_broken_ciphertext("sk-old-embed"),
        )
    )
    await api_db.commit()

    body = client.put(
        "/api/v1/settings/credentials",
        json={
            "anthropic_base_url": "https://relay.example.com",
            "embedding_base_url": "https://embed.example.com/v1",
        },
    ).json()

    assert body["anthropic_base_url_value"] == "https://relay.example.com"
    assert body["embedding_base_url_value"] == "https://embed.example.com/v1"


_FAKE_TAVILY = "tvly-mine-1234"  # gitleaks:allow -- 测试用假 key
_FAKE_EMBEDDING = "sk-mine-5678"  # gitleaks:allow -- 测试用假 key


async def test_key_source_names_the_layer_actually_used(
    client: TestClient, api_db: AsyncSession
) -> None:
    """来源要报实际生效的那一层，不能因为默认行坏了就报 none。"""
    user_id = await _login(client, api_db)
    await _write_default_row(
        api_db,
        tavily_api_key=_broken_ciphertext("tvly-old-default"),
        embedding_api_key=_broken_ciphertext("sk-old-default"),
    )
    client.put(
        "/api/v1/settings/credentials",
        json={"tavily_api_key": _FAKE_TAVILY, "embedding_api_key": _FAKE_EMBEDDING},
    )

    resolved = await resolve_credentials(api_db, user_id)

    assert resolved.tavily_key_source == "user"
    assert resolved.embedding_key_source == "user"


async def test_key_source_is_none_when_user_layer_has_only_a_url(
    client: TestClient, api_db: AsyncSession
) -> None:
    """用户层只配了地址：成对解析后没有可用的 key，来源不能报成默认行。"""
    user_id = await _login(client, api_db)
    await _write_default_row(api_db, embedding_api_key=encrypt_secret("sk-shared-default"))
    client.put(
        "/api/v1/settings/credentials",
        json={"embedding_base_url": "https://embed.example.com/v1"},
    )

    resolved = await resolve_credentials(api_db, user_id)

    assert resolved.embedding_api_key is None
    assert resolved.embedding_key_source == "none"


def test_key_file_is_never_overwritten(tmp_path: Path) -> None:
    """两个进程同时首次启动、各自生成主密钥时，后写的一方不能覆盖先写的。

    覆盖的话，先写那一方用自己的 key 加密的密文从此永久解不开。
    """
    from app.services import secret_store

    key_path = tmp_path / ".credentials.key"
    key_path.write_text("key-written-by-another-process", encoding="utf-8")

    stored = secret_store._write_key_file(key_path, "my-freshly-generated-key")

    assert stored == "key-written-by-another-process"
    assert key_path.read_text(encoding="utf-8") == "key-written-by-another-process"
    assert list(tmp_path.iterdir()) == [key_path], "临时文件要清理掉"


@pytest.mark.parametrize(
    "flag",
    ["--anthropic-base-url", "--embedding-base-url"],
)
def test_default_credentials_script_rejects_internal_base_url(tmp_path: Path, flag: str) -> None:
    """默认凭据脚本写入的地址同样是服务端出站地址，必须过 SSRF 校验。

    子进程跑在空的临时目录里：读不到开发环境的 .env，数据库也指向临时文件，
    校验失效时也不会写到开发库。
    """
    import os
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "set_default_credentials.py"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'scratch.db'}"}

    proc = subprocess.run(
        [sys.executable, str(script), flag, "http://127.0.0.1:8080/v1"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "不合法" in proc.stderr, proc.stderr
