"""LLM client 单例测试。

不打真实网络——这里只验证两件事：配置缺失时抛什么错、单例是否真的复用。
真正的网络交互由 app/services/agent.py 的测试打桩。
"""

import pytest
from anthropic import AsyncAnthropic

from app.config import Settings
from app.services.llm import (
    LLMNotConfiguredError,
    clear_client_cache,
    get_anthropic_client,
    get_tavily_client,
)


@pytest.fixture(autouse=True)
def _clear_clients() -> None:
    """每个测试前后清掉 client 单例，避免串味。"""
    clear_client_cache()


def _settings_without(field: str) -> Settings:
    """构造一份缺某个 key 的 Settings。"""
    settings = Settings()
    setattr(settings, field, None)
    return settings


# ── 配置缺失 ───────────────────────────────────────────────────


def test_missing_anthropic_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 ANTHROPIC_API_KEY 时抛 LLMNotConfiguredError，不是崩溃。"""
    settings = _settings_without("anthropic_api_key")
    monkeypatch.setattr("app.services.llm.get_settings", lambda: settings)
    clear_client_cache()

    with pytest.raises(LLMNotConfiguredError) as caught:
        get_anthropic_client()

    assert "ANTHROPIC_API_KEY" in str(caught.value)


def test_missing_tavily_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 TAVILY_API_KEY 时同样抛错——工具层会把它转成给模型看的提示。"""
    settings = _settings_without("tavily_api_key")
    monkeypatch.setattr("app.services.llm.get_settings", lambda: settings)
    clear_client_cache()

    with pytest.raises(LLMNotConfiguredError) as caught:
        get_tavily_client()

    assert "TAVILY_API_KEY" in str(caught.value)


# ── 单例复用 ───────────────────────────────────────────────────


def test_anthropic_client_is_singleton() -> None:
    """两次调用返回同一个实例——连接池不能每次新建。"""
    clear_client_cache()
    first = get_anthropic_client()
    second = get_anthropic_client()
    assert first is second
    assert isinstance(first, AsyncAnthropic)

