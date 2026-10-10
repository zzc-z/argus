"""外部 AI 能力的 client 单例。

Anthropic 与 Tavily 的客户端都做成进程内单例——它们各自内部持有一个
连接池，每次请求新建 client 会让 TCP/TLS 握手开销远超实际收益，尤其在
SSE 这种长连接场景下，一个研究请求要连打好几轮模型。

与 ``app/config.py`` 的 ``get_settings`` 同一个模式：``lru_cache`` 缓存，
测试里 ``cache_clear()`` 可重置。

配置缺失统一抛 ``LLMNotConfiguredError``，由调用方决定怎么处理——
是直接失败还是降级，取决于缺的是哪一项能力。
"""

from functools import lru_cache

from anthropic import AsyncAnthropic
from tavily import AsyncTavilyClient

from app.config import get_settings

# 单次模型请求的上限。SSE 长连接里一轮研究可能连续打好几轮，
# 每轮都等满默认超时会让整个请求挂死，用户看不到任何反馈。
MODEL_TIMEOUT_SECONDS = 120.0

# 429/5xx 由 SDK 自带退避重试；两次足够覆盖瞬时抖动，再多只是拖长失败反馈。
MODEL_MAX_RETRIES = 2


class LLMNotConfiguredError(RuntimeError):
    """外部 AI 能力未配置——缺 API key 之类。

    继承 RuntimeError 而非 Exception：它表达的是「部署环境没配好」，
    而不是代码逻辑出错。跟 ``app/services/token.py`` 里
    ``RuntimeError("JWT_SECRET_KEY 未配置")`` 同一类。
    """


def _require(value: str | None, name: str) -> str:
    """取出 SecretStr 里的明文，缺配置时抛 ``LLMNotConfiguredError``。"""
    if value is None or not value:
        raise LLMNotConfiguredError(f"{name} 未配置，无法调用该能力")
    return value


@lru_cache(maxsize=1)
def get_anthropic_client() -> AsyncAnthropic:
    """返回进程内单例的 Anthropic async 客户端。

    ``base_url`` 传 None 时走 Anthropic 官方端点；填了则走中转站。
    不在这里判断走哪条路——配置里有没有填就是唯一的判断依据。

    注意中转站的 model 实际身份不一定是配置字段标称的版本，
    ANTHROPIC_*_MODEL 填的值必须用中转站能认的 alias。
    """
    settings = get_settings()
    key = _require(
        settings.anthropic_api_key.get_secret_value()
        if settings.anthropic_api_key
        else None,
        "ANTHROPIC_API_KEY",
    )
    return AsyncAnthropic(
        api_key=key,
        base_url=settings.anthropic_base_url,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )


@lru_cache(maxsize=1)
def get_tavily_client() -> AsyncTavilyClient:
    """返回进程内单例的 Tavily async 客户端。

    没配 TAVILY_API_KEY 时抛 ``LLMNotConfiguredError``——由调用方
    （app/services/tools.py 的 dispatch）转成给模型看的错误字符串，
    而不是让整个 agent 流崩掉。
    """
    settings = get_settings()
    key = _require(
        settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else None,
        "TAVILY_API_KEY",
    )
    return AsyncTavilyClient(api_key=key)


def clear_client_cache() -> None:
    """清掉两个单例——测试改了配置后调用，否则拿到的是旧配置的 client。"""
    get_anthropic_client.cache_clear()
    get_tavily_client.cache_clear()

