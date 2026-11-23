"""凭据解析的优先级测试。

## 为什么这些要单独测

「用户配的」与「部署默认的」谁优先，是这个功能的核心语义。
写错时的症状**不明显**：功能「能用」，只是用的不是你配的那把——
用户会以为自己的配置没生效，而代码不会报任何错。

三条规则：

1. 用户配了某项 → 用用户的
2. 用户没配 → 用部署默认
3. **用户的 complex 与 critic 的联动**——用户换了 complex 却没换 critic 时，
   critic 必须跟着走（否则 critic 还在用部署的旧型号，而页面上看不出来）
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.services.credentials import (
    _build,
    resolve_env_credentials,
)


def _creds(
    *,
    complex_model: str | None = None,
    default_model: str | None = None,
    critic_model: str | None = None,
    anthropic_key: str | None = None,
    tavily_key: str | None = None,
) -> Any:
    """造一份「用户层」的值，走真实的合并逻辑。

    **不能**用 ``dataclasses.replace``——那会绕过 ``_build``，
    派生字段（critic 的回落）就不会被重新算。测试要走真实路径。
    """
    return _build(
        user_anthropic_key=anthropic_key,
        user_anthropic_base_url=None,
        user_complex_model=complex_model,
        user_default_model=default_model,
        user_critic_model=critic_model,
        user_tavily_key=tavily_key,
        user_embedding_key=None,
        user_embedding_base_url=None,
    )


# ── 用户优先 ───────────────────────────────────────────────────


def test_user_key_wins_over_env_key() -> None:
    """用户配的 key 覆盖部署默认的。"""
    creds = _creds(anthropic_key="sk-user", tavily_key="tvly-user")
    assert creds.anthropic_api_key == "sk-user"
    assert creds.tavily_api_key == "tvly-user"
    assert creds.anthropic_key_source == "user"
    assert creds.tavily_key_source == "user"


def test_env_key_used_when_user_has_none() -> None:
    """用户没配 → 用部署默认的，source 是 env。"""
    settings = get_settings()
    original = settings.anthropic_api_key
    try:
        settings.anthropic_api_key = type(original)("sk-from-env") if original else None
        creds = _creds()
        if settings.anthropic_api_key is not None:
            assert creds.anthropic_api_key == "sk-from-env"
            assert creds.anthropic_key_source == "env"
    finally:
        settings.anthropic_api_key = original


# ── critic 与 complex 的联动 ───────────────────────────────────


def test_critic_follows_user_complex_model() -> None:
    """**用户配了 complex 却没配 critic → critic 跟着 complex 走。**

    回归场景：用户把模型从 claude-sonnet-5 换成 claude-opus-5-5，
    critic 却还在用部署里的 claude-sonnet-5。页面显示「Critic 模型」
    与「复杂任务模型」不同——看上去正常（以为是有意配的），
    实际 critic 用的是部署者配的旧型号。

    这条钉住：**用户配了 complex 时，critic 必须跟着用户走**。
    """
    creds = _creds(complex_model="claude-opus-5-5")
    assert creds.anthropic_complex_model == "claude-opus-5-5"
    assert creds.critic_model == "claude-opus-5-5"
    assert creds.model_for("critic") == "claude-opus-5-5"


def test_user_critic_model_wins_over_everything() -> None:
    """用户显式配了 critic → 用用户的，与 complex 无关。"""
    creds = _creds(complex_model="claude-opus-5-5", critic_model="claude-haiku-5-5")
    assert creds.critic_model == "claude-haiku-5-5"


def test_env_critic_does_not_apply_when_user_configured_complex() -> None:
    """**用户配了 complex 时，env 的 critic 覆盖不再适用。**

    env 的 critic 是部署者给**默认那套**配的，不是给用户这套配的。
    用户配了 complex 却让 critic 跟着 env 走，等于用户的配置只生效一半。
    """
    settings = get_settings()
    original = settings.anthropic_critic_model
    try:
        settings.anthropic_critic_model = "env-critic-model"
        creds = _creds(complex_model="user-complex-model")
        assert creds.critic_model == "user-complex-model"
    finally:
        settings.anthropic_critic_model = original


def test_env_critic_applies_when_user_configured_nothing() -> None:
    """用户什么都没配 → env 的 critic 照旧生效（既有行为不变）。"""
    settings = get_settings()
    original = settings.anthropic_critic_model
    try:
        settings.anthropic_critic_model = "env-critic-model"
        creds = _creds()
        assert creds.critic_model == "env-critic-model"
    finally:
        settings.anthropic_critic_model = original


def test_critic_model_is_single_source_of_truth() -> None:
    """critic 的型号只有**一处**存着。

    以前它同时是个字段和 ``role_models["critic"]`` 里的一项——
    改了一处忘了另一处，页面显示的与实际调用的就分家了。
    """
    creds = _creds(complex_model="single-source-model")
    assert creds.critic_model == creds.role_models["critic"]


# ── 其它角色的回落 ─────────────────────────────────────────────


def test_other_roles_fall_back_to_default_model() -> None:
    """supervisor / analyst 等角色没覆盖时退到 default_model。"""
    creds = _creds(default_model="my-default-model")
    assert creds.model_for("supervisor") == "my-default-model"
    assert creds.model_for("analyst") == "my-default-model"
    assert creds.model_for("researcher") == "my-default-model"
    assert creds.model_for("summarizer") == "my-default-model"


def test_user_default_model_wins_over_env_default() -> None:
    """用户配的 default 覆盖部署默认的。"""
    creds = _creds(default_model="my-default-model")
    assert creds.anthropic_default_model == "my-default-model"
    assert creds.model_for("analyst") == "my-default-model"


def test_env_role_override_still_applies() -> None:
    """**按角色的 env 覆盖照旧生效**——那是部署级的调参项。

    用户可配的是 complex / default / critic 三个「任务级默认」；
    supervisor / analyst 这类角色覆盖是部署者的事，页面上不暴露，
    但也不能因此失效。
    """
    settings = get_settings()
    original = settings.anthropic_analyst_model
    try:
        settings.anthropic_analyst_model = "env-analyst-model"
        creds = _creds(default_model="my-default-model")
        assert creds.model_for("analyst") == "env-analyst-model"
    finally:
        settings.anthropic_analyst_model = original


# ── base_url 归一 ──────────────────────────────────────────────


def test_base_url_trailing_slash_is_stripped() -> None:
    """尾部斜杠被去掉。"""
    from app.services.credentials import _normalize_base_url

    assert _normalize_base_url("https://relay.test/") == "https://relay.test"
    assert _normalize_base_url("https://relay.test///") == "https://relay.test"
    assert _normalize_base_url("  https://relay.test/  ") == "https://relay.test"
    assert _normalize_base_url(None) is None
    assert _normalize_base_url("   ") is None


# ── 空值归一 ───────────────────────────────────────────────────


def test_blank_user_value_is_treated_as_missing() -> None:
    """空串等于没配——页面回显时不能显示成「已配置」但调不通。"""
    from app.services.credentials import _clean

    assert _clean("") is None
    assert _clean("   ") is None
    assert _clean(None) is None
    assert _clean("  x  ") == "x"


def test_blank_user_value_falls_back_to_env() -> None:
    """用户那格填了空格 → 当没配 → 用部署默认。"""
    creds = _build(
        user_anthropic_key="   ",
        user_anthropic_base_url=None,
        user_complex_model=None,
        user_default_model=None,
        user_critic_model=None,
        user_tavily_key=None,
        user_embedding_key=None,
        user_embedding_base_url=None,
    )
    # 空串被 _clean 归一成 None，于是这里应该是 env 的值（或 None）
    settings = get_settings()
    env_value = (
        settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    )
    assert creds.anthropic_api_key == env_value
    assert creds.anthropic_key_source in {"env", "none"}


# ── 备胎模型链 ─────────────────────────────────────────────────


def test_fallback_models_parsed_from_env() -> None:
    """备胎链从 env 解析，逗号分隔、去空白、丢掉空项。"""
    settings = get_settings()
    original = settings.anthropic_fallback_models
    try:
        settings.anthropic_fallback_models = "backup-1, backup-2 ,"
        creds = resolve_env_credentials()
        assert creds.fallback_models == ("backup-1", "backup-2")
    finally:
        settings.anthropic_fallback_models = original


def test_empty_fallback_models_is_empty_tuple() -> None:
    """没配备胎 → 空元组（不是空列表——类型要一致）。"""
    settings = get_settings()
    original = settings.anthropic_fallback_models
    try:
        settings.anthropic_fallback_models = ""
        creds = resolve_env_credentials()
        assert creds.fallback_models == ()
    finally:
        settings.anthropic_fallback_models = original
