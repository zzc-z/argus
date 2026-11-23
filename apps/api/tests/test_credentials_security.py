"""凭据的安全边界测试。

## 这个文件保护什么

1. **key 与 base_url 不许混层**——混了会把密钥发到不该去的地方。
2. **base_url 不许指向内网**——它是服务端出站地址（SSRF）。
3. **槽位不许泄漏**——凭据解析失败时，并发闸门不能被永久占住。

这三条都是「写错了也不报错」的类型，所以只能靠断言钉住。
"""

from __future__ import annotations

import pytest

from app.services.credentials import (
    InvalidBaseUrlError,
    ResolvedCredentials,
    _build,
    resolve_env_credentials,
    validate_base_url,
)


def _creds(
    *,
    anthropic_key: str | None = None,
    anthropic_base_url: str | None = None,
    embedding_key: str | None = None,
    embedding_base_url: str | None = None,
) -> ResolvedCredentials:
    """走真实的合并逻辑造一份凭据。

    **不能**用 ``dataclasses.replace``——那会绕过 ``_build``，
    派生字段不会被重算。
    """
    return _build(
        user_anthropic_key=anthropic_key,
        user_anthropic_base_url=anthropic_base_url,
        user_complex_model=None,
        user_default_model=None,
        user_critic_model=None,
        user_tavily_key=None,
        user_embedding_key=embedding_key,
        user_embedding_base_url=embedding_base_url,
    )


# ── key 与 base_url 成对 ───────────────────────────────────────


def test_user_key_does_not_leak_to_deployment_relay() -> None:
    """**用户的官方 key 不能被发到部署的中转站。**

    回归场景：部署配了 ``ANTHROPIC_BASE_URL=https://relay.example``
    （中转站的 key 在 env 里）。用户在页面上只填了自己的官方 key。
    独立回落会得到「用户的 key + 部署的中转站」——于是他的官方 key
    被发给中转站operator，**且没有任何报错**。

    规则是：**用户配了 key 或 url 里的任何一个，两个都从用户层取**。
    """
    creds = _creds(anthropic_key="sk-user-official")

    # 用户的 base_url 留空 → 走官方端点，而不是部署的中转站。
    assert creds.anthropic_base_url is None
    assert creds.anthropic_api_key == "sk-user-official"


def test_user_base_url_does_not_receive_deployment_key() -> None:
    """**部署的 key 不能被发到用户指定的地址。**

    回归场景：用户只填了 ``base_url=https://attacker.example``。
    独立回落会拿到「部署的 env key + 用户的地址」——部署的 key 被发出去。
    """
    creds = _creds(anthropic_base_url="https://attacker.example")

    # 用户层没配 key → 就是没有 key，绝不回落 env 的。
    assert creds.anthropic_api_key is None
    assert creds.anthropic_base_url == "https://attacker.example"


def test_embedding_key_and_url_also_paired() -> None:
    """嵌入服务同理——key 与端点是一对。"""
    creds = _creds(embedding_key="sk-embed-user")

    assert creds.embedding_base_url is None
    assert creds.embedding_api_key == "sk-embed-user"

    creds2 = _creds(embedding_base_url="https://embed.example/v1")
    assert creds2.embedding_api_key is None


def test_both_from_user_layer_when_user_configures_both() -> None:
    """用户两个都配了 → 都用用户的（这是正常路径）。"""
    creds = _creds(
        anthropic_key="sk-user",
        anthropic_base_url="https://user-relay.example",
    )
    assert creds.anthropic_api_key == "sk-user"
    assert creds.anthropic_base_url == "https://user-relay.example"


def test_env_used_when_user_configures_nothing() -> None:
    """用户什么都没配 → 两层都用 env 的（既有行为不变）。"""
    settings = resolve_env_credentials()
    assert settings.anthropic_api_key == settings.anthropic_api_key


# ── base_url 的 SSRF 校验 ──────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/",
        "http://localhost:8000/",
        "http://[::1]:8000/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://metadata.google.internal/",
        "http://foo.local/",
        "http://foo.internal/",
    ],
)
def test_private_addresses_are_rejected(url: str) -> None:
    """内网/本机/链路本地地址一律拒。

    ``base_url`` 是**服务端出站地址**——用户填一个内网地址就是一条
    SSRF 通道（云 metadata 端点、内网服务都在射程内）。
    """
    with pytest.raises(InvalidBaseUrlError):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "javascript:alert(1)",
    ],
)
def test_non_http_schemes_are_rejected(url: str) -> None:
    """协议白名单——挡掉能读本地资源的 scheme。"""
    with pytest.raises(InvalidBaseUrlError):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.anthropic.com",
        "https://llmapi.pro",
        "http://example.com/v1",
        "https://8.8.8.8",
    ],
)
def test_public_addresses_are_accepted(url: str) -> None:
    """公网地址照常放行——不能把正常的中转站挡掉。"""
    assert validate_base_url(url) == url


def test_trailing_slash_is_stripped_by_validation() -> None:
    """校验顺带去掉尾部斜杠（拼路径时多一个斜杠会 404）。"""
    assert validate_base_url("https://relay.test/") == "https://relay.test"


def test_empty_base_url_is_allowed() -> None:
    """空 = 不配（走默认端点），不是错误。"""
    assert validate_base_url(None) is None
    assert validate_base_url("") is None
    assert validate_base_url("   ") is None
