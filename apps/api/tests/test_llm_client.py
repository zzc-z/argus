"""LLM client 缓存测试。

不打真实网络——这里只验证三件事：配置缺失时抛什么错、缓存是否真的复用、
**换凭据后是否拿到新 client**。

真正的网络交互由 app/services/agent.py 的测试打桩。
"""

import dataclasses

import pytest
from anthropic import AsyncAnthropic

from app.services.credentials import ResolvedCredentials, resolve_env_credentials
from app.services.llm import (
    LLMNotConfiguredError,
    clear_client_cache,
    get_anthropic_client,
    get_tavily_client,
)

# 测试用的凭据。按部署默认解析——本文件测的是 client 的**缓存语义**。
_CREDS = resolve_env_credentials()


@pytest.fixture(autouse=True)
def _clear_clients() -> None:
    """每个测试前后清掉 client 缓存，避免串味。"""
    clear_client_cache()


def _creds(
    *,
    anthropic_key: str | None = None,
    anthropic_base_url: str | None = None,
    tavily_key: str | None = None,
) -> ResolvedCredentials:
    """造一份指定凭据。

    刻意**直接改 ``ResolvedCredentials``** 而不是改 ``Settings``——
    client 现在从凭据读，不再从 env 读。
    """
    return dataclasses.replace(
        _CREDS,
        anthropic_api_key=anthropic_key,
        anthropic_base_url=anthropic_base_url,
        tavily_api_key=tavily_key,
    )


# ── 配置缺失 ───────────────────────────────────────────────────


def test_missing_anthropic_key_raises() -> None:
    """没配 API key 时抛 LLMNotConfiguredError，不是崩溃。"""
    with pytest.raises(LLMNotConfiguredError) as caught:
        get_anthropic_client(_creds(anthropic_key=None))

    assert "ANTHROPIC_API_KEY" in str(caught.value)


def test_missing_tavily_key_raises() -> None:
    """没配 Tavily key 时同样抛错——工具层会把它转成给模型看的提示。"""
    with pytest.raises(LLMNotConfiguredError) as caught:
        get_tavily_client(_creds(tavily_key=None))

    assert "TAVILY_API_KEY" in str(caught.value)


def test_blank_key_is_treated_as_missing() -> None:
    """空串等于没配。

    页面回显时「配了但填了空」会显示成「已配置」，而实际调不通——
    判空必须把空串算进去。
    """
    with pytest.raises(LLMNotConfiguredError):
        get_anthropic_client(_creds(anthropic_key=""))


# ── 缓存复用 ───────────────────────────────────────────────────


def test_anthropic_client_is_cached() -> None:
    """同一份凭据两次调用返回同一个实例——连接池不能每次新建。"""
    creds = _creds(anthropic_key="sk-test-a")
    first = get_anthropic_client(creds)
    second = get_anthropic_client(creds)
    assert first is second
    assert isinstance(first, AsyncAnthropic)


def test_tavily_client_is_cached() -> None:
    """Tavily 同理。"""
    creds = _creds(tavily_key="tvly-test-a")
    first = get_tavily_client(creds)
    second = get_tavily_client(creds)
    assert first is second


# ── 换凭据后必须换 client ─────────────────────────────────────


def test_different_key_gets_different_client() -> None:
    """**换了 key 必须拿到新 client**——否则用户改了配置却在用旧的。

    这是「按用户配凭据」的核心保证：缓存按 (key, base_url) 分桶，
    不按 user_id。少了这条，用户在页面上保存了新 key，页面上说「已保存」，
    实际还在用老 key 调模型——而且不报错。
    """
    first = get_anthropic_client(_creds(anthropic_key="sk-test-a"))
    second = get_anthropic_client(_creds(anthropic_key="sk-test-b"))
    assert first is not second


def test_different_base_url_gets_different_client() -> None:
    """**换了中转站必须拿到新 client**——同一把 key 连不同上游是两条线路。"""
    first = get_anthropic_client(
        _creds(anthropic_key="sk-test-a", anthropic_base_url="https://a.test")
    )
    second = get_anthropic_client(
        _creds(anthropic_key="sk-test-a", anthropic_base_url="https://b.test")
    )
    assert first is not second


def test_client_uses_configured_base_url() -> None:
    """base_url 真的被用上了——填了中转站就连中转站。"""
    client = get_anthropic_client(
        _creds(anthropic_key="sk-test-a", anthropic_base_url="https://relay.test")
    )
    assert "relay.test" in str(client.base_url)
