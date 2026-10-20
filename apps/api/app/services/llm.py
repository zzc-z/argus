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

import httpx
import httpx2
from anthropic import APIConnectionError, APITimeoutError, AsyncAnthropic
from tavily import AsyncTavilyClient

from app.config import get_settings

# 单次模型请求的上限。SSE 长连接里一轮研究可能连续打好几轮，
# 每轮都等满默认超时会让整个请求挂死，用户看不到任何反馈。
MODEL_TIMEOUT_SECONDS = 120.0

# 429/5xx 由 SDK 自带退避重试；两次足够覆盖瞬时抖动，再多只是拖长失败反馈。
MODEL_MAX_RETRIES = 2

# **流被中断**时的整轮重发次数（不含首次尝试）。
#
# ## 为什么 SDK 自带的 max_retries 不够
#
# SDK 的重试循环只包住「拿到 response」这一步。流式请求在
# ``get_final_message()`` 里消费 SSE 流——连接是在**消费途中**被掐断的，
# 那时已经跳出 SDK 的重试循环，异常直接冒到调用方。
#
# 实测（中转站 llmapi.pro，2026-10-20）：同一请求连发 8 次全部成功，
# 换个时机同一请求 1/3 失败，异常恒为
# ``httpx2.RemoteProtocolError: peer closed connection without sending
# complete message body (incomplete chunked read)``。失败耗时 72-136 秒
# （长生成被掐），成功 2-13 秒。与 prompt 长度、工具集、max_tokens 均无关。
#
# ## 为什么是「整轮重发」而不是「续流」
#
# 断在流中途时，已经收到的增量无法安全地接续——上游的 thinking block 带
# signature，中途截断的 assistant 消息回传过去会被拒。整轮重发是唯一
# 安全的恢复方式，代价是断掉那一轮的 token 白烧。
#
# 2 次：实测失败率约 1/3，两次重发后仍失败的概率降到约 1/9。更多次会
# 拖长失败反馈（用户盯着转圈等 3 分钟比直接看到错误更糟）。
STREAM_INTERRUPT_RETRIES = 2

# 整轮重发之间的等待。中转站的断连是随机抖动，退避用不上；给 1 秒纯粹
# 是别在对方刚断开的瞬间立刻再撞上去。
STREAM_INTERRUPT_BACKOFF_SECONDS = 1.0


def is_stream_interrupt(exc: BaseException) -> bool:
    """这个异常是不是「流被中途掐断」。

    ## 判据

    只认两种情况：

    1. ``anthropic.APIConnectionError`` —— SDK 把 httpx 的传输层异常包成了
       它。**排除**它的子类 ``APITimeoutError``：超时是「等太久了」，
       重发同样的请求多半还是超时（模型生成慢），重发只会浪费时间。
    2. ``httpx.RemoteProtocolError`` —— ``incomplete chunked read``。
       httpx2 是 anthropic 1.9.0 依赖的新包名，与 httpx 是**两个不同的
       包**，异常类不通用。两个都判，否则按 anthropic 依赖升级前的
       httpx 抛出的断连就识别不出来。

    ## 为什么不用「所有 Exception 都重试」

    业务错误（400 参数错、401 key 错、404）重发一万次也是同样的错。
    把它们一起重试，用户会盯着 3 倍时长的转圈才看到错误。
    """
    if isinstance(exc, APITimeoutError):
        return False
    if isinstance(exc, APIConnectionError):
        return True
    return isinstance(exc, (httpx.RemoteProtocolError, httpx2.RemoteProtocolError))


def is_timeout(exc: BaseException) -> bool:
    """这个异常是不是「等太久了」。

    与 ``is_stream_interrupt`` 互斥：超时**不**重发同样的请求——模型生成
    慢，重发大概率还是超时，只是让用户多等一轮。超时该做的是让用户
    缩小问题范围。

    ``APITimeoutError`` 是 SDK 对 httpx 超时的包装，**不是**内建的
    ``TimeoutError`` 的子类——只判内建的那个会漏掉全部真实超时。
    """
    if isinstance(exc, APITimeoutError):
        return True
    if isinstance(exc, (httpx.TimeoutException, httpx2.TimeoutException)):
        return True
    return isinstance(exc, TimeoutError)


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

