"""外部 AI 能力的 client 缓存。

Anthropic 与 Tavily 的客户端都缓存起来——它们各自内部持有一个
连接池，每次请求新建 client 会让 TCP/TLS 握手开销远超实际收益，尤其在
SSE 这种长连接场景下，一个研究请求要连打好几轮模型。

## 缓存的键是「凭据」而不是「用户」

用户可以在设置页配自己的 API key 与中转站（见
``app/services/credentials.py``），所以同一个部署上会有多把 key 在用。
缓存按 ``(api_key, base_url)`` 分桶：

- 同一把 key + 同一个地址 → 同一个 client（连接池复用）
- 换了 key 或换了中转站 → 另一个 client

**为什么不按 user_id 分桶**：换了 key 之后同一个 user_id 会拿到**旧的**
client——用户改了配置，页面上说「已保存」，实际还在用老 key 调模型。
而这种不一致不会报错，只会让测试人员以为自己的新 key 没生效。

**为什么 key 直接进缓存键**：key 是敏感值，不能进日志或异常消息。
所以缓存键**只在内存里**，不打印、不落盘、不进任何对外响应。
（真要泄露，进程内存里本来就有这把 key——多放一份在字典键里不增加
暴露面。）

配置缺失统一抛 ``LLMNotConfiguredError``，由调用方决定怎么处理——
是直接失败还是降级，取决于缺的是哪一项能力。
"""

import logging
from functools import lru_cache

import httpx
import httpx2
from anthropic import APIConnectionError, APITimeoutError, AsyncAnthropic
from tavily import AsyncTavilyClient

from app.services.credentials import ResolvedCredentials

logger = logging.getLogger(__name__)

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

# 整轮重发之间的等待基数。**按指数退避**：第 n 次重发等
# ``BASE * 2**(n-1)`` 秒（1s → 2s）。
#
# ## 为什么固定 1 秒不够（2026-11-01 实测）
#
# 断连的根因当时是**本机网络层**——Tavily 与 Anthropic 两个不同的服务在
# **同一秒**断开（`Server disconnected without sending a response`，
# 连响应头都没收到）。日志时间线：
#
# ```
# 17:10:53  POST /api/v1/research/ask 200
# 17:11:01  模型流被中断，第 1 次重发整轮请求
# 17:11:01  模型流被中断，第 2 次重发整轮请求
# 17:11:01  模型流被中断，第 3 次重发整轮请求
# ```
#
# 3 次重发挤在同一秒里全挂——**固定的 1 秒间隔让所有重试都落在同一个
# 坏窗口内**，白等。指数退避把最后一次重发推到 3 秒之后，抖动的窗口
# 大概率已经过去。
#
# 1 秒也留着当基数：网络抖动的窗口通常在秒级，2s / 4s 这种长退避
# 会让用户盯着转圈等太久（一次研究本来就 30-60 秒）。
STREAM_INTERRUPT_BACKOFF_SECONDS = 1.0


def fallback_models(credentials: ResolvedCredentials) -> list[str]:
    """取备胎模型链（按顺序尝试）。

    ## 为什么要有备胎

    业界通行的三层模型路由（Oracle / AWS / MLflow）都包含
    **pre-configured fallback logic**：主模型崩了、超时了、被限流了，
    自动切到已知可用的备胎，而不是让用户盯着转圈等错误。

    对 argus 尤其重要——中转站的断流是**常态**（实测失败率约 1/3），
    单模型意味着三分之一的研究直接失败。

    配置项 ``ANTHROPIC_FALLBACK_MODELS``，逗号分隔的 alias 列表。
    留空表示没有备胎（保持原行为）。
    """
    return list(credentials.fallback_models)


def model_for(credentials: ResolvedCredentials, role: str) -> str:
    """取某个角色的模型。

    优先级（业界静态分层路由的标准做法）：

    1. **按角色覆盖** —— ``ANTHROPIC_{ROLE}_MODEL``（如
       ``ANTHROPIC_ANALYST_MODEL``）。最具体，优先级最高。
    2. **任务级默认** —— ``ANTHROPIC_DEFAULT_MODEL``。

    ## 为什么不硬编码

    早先这里写死 ``_DEFAULT_MODELS``，而 ``ANTHROPIC_DEFAULT_MODEL``
    这个配置项**全仓零读取点**——改了 ``.env`` 也不生效。
    模型退役或要换中转线路时，只能改代码重新发版。

    现在统一走配置：``.env`` 里改一行就生效，代码不用动。

    ## critic 的回落档位与其它角色不同

    Critic 逐条判定「这句话能不能从它引用的原文得到」——20 条引用、
    15k tokens 输入，这是**复杂任务**（判「说反了」和「数字错了 40 倍」
    需要真读原文），不是 supervisor / analyst 那种结构化短输出。
    所以 critic 留空时退到 ``complex_model``，其余角色退到 ``default_model``。

    ## 为什么放在这里而不是 stages.py

    模型路由是**跨模块**的：``stages.py`` 的 supervisor / analyst 与
    ``faithfulness.py`` 的 critic 都要读它。放在 stages.py 里，后者就得
    跨模块 import 一个私有函数（``_model_for``）——迟早有人绕过它，
    然后两处路由就漂移了。
    """
    return credentials.model_for(role)


def assert_distinct_judge_and_writer() -> None:
    """断言 critic（判定者）与 writer（生成者）不是同一个模型。

    ## 为什么这是硬要求

    LLM 评委给自己的输出打高分，是被反复观测到的**自偏好偏差**
    （arXiv 2410.21819）。业界的建议直接写明：

        "Considering the significant self-enhancement bias, we should avoid
         using the same model as the evaluator."

    ## argus 的现状（2026-11-18 实测）

    主循环（Researcher + Writer）走 ``agent_turn._build_turn_request``，
    硬编码 ``settings.anthropic_complex_model``（默认 claude-sonnet-5）；
    Critic 也用 ``anthropic_critic_model or anthropic_complex_model``
    （默认同样是 claude-sonnet-5）。

    **也就是说：默认配置下 judge 与 writer 就是同一个模型。**
    自偏好偏差不是一个「将来可能发生的风险」，而是**现在就在**——
    通过率会系统性偏高，而没有任何外部证据能发现它。

    ## 为什么只在 prod 强制

    本地开发与测试用同一个型号是合理的（省额度、行为一致好复现）。
    **线上不行**——线上那个「通过率」是要给用户看的产品指标，
    系统性偏高会直接误导判断。

    ``APP_ENV=prod`` 时才强制；dev / test 只记警告。

    ## 这条只管**部署默认**

    用户可以在设置页配自己的模型（见 ``app/services/credentials.py``），
    那时 critic 与 writer 是不是同一个型号由用户自己定——这条断言
    管不到，也不该管（它管的是「部署者不知道自己在配什么」的情况，
    而用户是明知道自己在配什么才填的）。

    用户配成同一个型号时，``/settings/credentials`` 的响应里
    ``critic_equals_writer`` 会标出来，页面据此给提示——那是**警告**
    而不是阻断：阻断会让用户的整个研究跑不起来，而这个项目的定位是
    给测试人员用的。
    """
    from app.config import get_settings

    settings = get_settings()
    judge = settings.anthropic_critic_model or settings.anthropic_complex_model
    # writer 的真实模型：主循环硬编码 complex_model（``anthropic_writer_model``
    # 这个配置项全仓无人读取——别被它的名字骗了）。
    writer = settings.anthropic_complex_model
    if judge == writer:
        message = (
            f"critic 与 writer 用了同一个模型（{judge}）——自偏好偏差会让通过率"
            f"系统性偏高。给 ANTHROPIC_CRITIC_MODEL 配一个与 writer 不同的型号。"
        )
        if settings.app_env == "prod":
            raise ValueError(message)
        logger.warning("（非 prod 环境，仅提示）%s", message)


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
    """取出明文，缺配置时抛 ``LLMNotConfiguredError``。"""
    if value is None or not value:
        raise LLMNotConfiguredError(f"{name} 未配置，无法调用该能力")
    return value


@lru_cache(maxsize=32)
def _anthropic_client_cached(api_key: str, base_url: str | None) -> AsyncAnthropic:
    """按 (key, base_url) 分桶的 Anthropic client。

    ``base_url`` 传 None 时走 Anthropic 官方端点；填了则走中转站。
    不在这里判断走哪条路——配置里有没有填就是唯一的判断依据。

    注意中转站的 model 实际身份不一定是配置字段标称的版本，
    模型名填的值必须用中转站能认的 alias。

    ``maxsize=32``：一台部署上通常只有几个测试账号，32 够用；而
    无上限的字典会被「改了 100 次 key」的测试撑爆——每个 client
    都持有一个连接池。
    """
    return AsyncAnthropic(
        api_key=api_key,
        base_url=base_url,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )


@lru_cache(maxsize=32)
def _tavily_client_cached(api_key: str) -> AsyncTavilyClient:
    """按 key 分桶的 Tavily client。"""
    return AsyncTavilyClient(api_key=api_key)


def get_anthropic_client(credentials: ResolvedCredentials) -> AsyncAnthropic:
    """取这个用户的 Anthropic client。

    ``credentials`` 由调用方解析好（见 ``app/services/credentials.py``）——
    这里不查 DB：client 的创建点在请求热路径上，而凭据解析需要一次
    SELECT，调用方解析一次传下来更省。

    没配 key 时抛 ``LLMNotConfiguredError``——调用方决定是直接失败
    还是降级。
    """
    key = _require(credentials.anthropic_api_key, "ANTHROPIC_API_KEY")
    return _anthropic_client_cached(key, credentials.anthropic_base_url)


def get_tavily_client(credentials: ResolvedCredentials) -> AsyncTavilyClient:
    """取这个用户的 Tavily client。

    没配 key 时抛 ``LLMNotConfiguredError``——由调用方
    （app/services/tools.py 的 dispatch）转成给模型看的错误字符串，
    而不是让整个 agent 流崩掉。
    """
    key = _require(credentials.tavily_api_key, "TAVILY_API_KEY")
    return _tavily_client_cached(key)


def clear_client_cache() -> None:
    """清掉所有 client 缓存——测试改了配置后调用，否则拿到的是旧配置的 client。"""
    _anthropic_client_cached.cache_clear()
    _tavily_client_cached.cache_clear()
