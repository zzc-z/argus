"""模型路由的测试：按角色取模型 + critic 与 writer 必须不同型号。

## 为什么「critic ≠ writer」是硬要求

LLM 评委给自己的输出打高分，是被反复观测到的**自偏好偏差**
（arXiv 2410.21819）。业界的建议直接写明：

    "Considering the significant self-enhancement bias, we should avoid using
     the same model as the evaluator."

argus 的默认配置下，**critic 与 writer 就是同一个模型**
（两者都落到 ``anthropic_complex_model`` = claude-sonnet-5），
自偏好偏差是一个**现在就存在**的问题，而不是「将来可能发生的风险」。

这类偏差不会抛异常、不会打日志——它只是让「通过率」系统性偏高。
唯一挡得住的时机是客户端创建时显式断言。
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.llm import (
    assert_distinct_judge_and_writer,
    model_for,
)


class TestModelFor:
    def test_role_override_wins(self) -> None:
        """按角色覆盖优先于任务级默认。"""
        settings = get_settings()
        original = settings.anthropic_analyst_model
        try:
            settings.anthropic_analyst_model = "some-other-model"
            assert model_for("analyst") == "some-other-model"
        finally:
            settings.anthropic_analyst_model = original

    def test_blank_override_falls_back(self) -> None:
        """覆盖项留空时退到任务级默认（不是空串）。"""
        settings = get_settings()
        original = settings.anthropic_analyst_model
        try:
            settings.anthropic_analyst_model = None
            assert model_for("analyst") == settings.anthropic_default_model
            settings.anthropic_analyst_model = ""
            assert model_for("analyst") == settings.anthropic_default_model
        finally:
            settings.anthropic_analyst_model = original

    def test_critic_falls_back_to_complex_not_default(self) -> None:
        """critic 留空时退到 complex_model（判定是复杂任务）。

        与 supervisor / analyst 不同——那两个是「结构化的短输出」，
        走 default（快、便宜）；critic 要真读原文判「说反了」和
        「数字错了 40 倍」，走 default 会明显变弱。
        """
        settings = get_settings()
        original = settings.anthropic_critic_model
        try:
            settings.anthropic_critic_model = None
            assert model_for("critic") == settings.anthropic_complex_model
        finally:
            settings.anthropic_critic_model = original


class TestDistinctJudgeAndWriter:
    def test_same_model_is_rejected_in_prod(self) -> None:
        """prod 环境下 critic 与 writer 同型号 → 抛错，不静默通过。

        自偏好偏差不会自己暴露——它只会让指标变得好看。
        """
        settings = get_settings()
        original_critic = settings.anthropic_critic_model
        original_env = settings.app_env
        try:
            # 让 critic 明确等于 writer 实际用的那个型号
            settings.anthropic_critic_model = settings.anthropic_complex_model
            settings.app_env = "prod"
            with pytest.raises(ValueError) as excinfo:
                assert_distinct_judge_and_writer()
            assert "自偏好" in str(excinfo.value)
            assert settings.anthropic_complex_model in str(excinfo.value)
        finally:
            settings.anthropic_critic_model = original_critic
            settings.app_env = original_env

    def test_same_model_only_warns_outside_prod(self) -> None:
        """非 prod 环境只警告，不阻断。

        本地开发与测试用同一个型号是合理的（省额度、行为一致好复现）。
        线上不行——那个「通过率」是要给用户看的产品指标。
        """
        settings = get_settings()
        original_critic = settings.anthropic_critic_model
        original_env = settings.app_env
        try:
            settings.anthropic_critic_model = settings.anthropic_complex_model
            settings.app_env = "dev"
            assert_distinct_judge_and_writer()  # 不抛异常即通过
        finally:
            settings.anthropic_critic_model = original_critic
            settings.app_env = original_env

    def test_different_model_passes(self) -> None:
        """不同型号 → 断言通过。"""
        settings = get_settings()
        original_critic = settings.anthropic_critic_model
        original_env = settings.app_env
        try:
            settings.anthropic_critic_model = "a-critic-model-that-differs"
            settings.app_env = "prod"
            assert_distinct_judge_and_writer()
        finally:
            settings.anthropic_critic_model = original_critic
            settings.app_env = original_env

    def test_default_config_is_same_model(self) -> None:
        """**记录当前事实**：默认配置下 critic 与 writer 同型号。

        这条测试的作用不是断言「应该不同」，而是把现状钉住——
        哪天有人改了 ``config.py`` 的默认值让它变成不同型号，
        这条会红，提醒人同步更新文档与 ``.env.example``。
        """
        settings = get_settings()
        judge = settings.anthropic_critic_model or settings.anthropic_complex_model
        writer = settings.anthropic_complex_model
        assert judge == writer, (
            "默认配置下 critic 与 writer 已不同型号——"
            "更新 CLAUDE.md / .env.example 的说明，并把本测试改成断言「不同」"
        )
