"""错误分类：异常 → 具体的 code + 文案。

## 为什么这些测试存在

改之前，所有非流中断的失败都报「模型服务暂时不可用」。用户看到它
只知道「再试一次」，但 key 失效、账户欠费、限流、内容被拦的处置方式
完全不同——有的重试一万次也没用。

分类器就是把这些差异变成机器可读的 code 与人类可读的文案。

## 注入回归

每条测试都对照一个「错误实现也会通过吗」的候选：

- ``test_auth_failure_not_reported_as_unavailable`` —— 断言 code 是
  ``llm_auth_failed``。写「不是 unavailable」的话，把认证失败也归到
  unavailable 的实现同样能过；断言具体 code 才行。
- ``test_arrearage_detected_from_body_code`` —— 构造 body 里的
  ``code: "Arrearage"``。只判状态码（400）的实现会把欠费报成「参数错」。
- ``test_content_filter_distinguished_from_bad_request`` —— 两者都是 400，
  只判状态码的实现分不开。
- ``test_retryable_flag_differs`` —— 断言 retryable 的取值。只断言
  「文案里含某个词」的实现分不出可重试与否。
"""

import re
from typing import Any

import httpx
import httpx2
import openai
import pytest
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)
from tavily.errors import (
    BadRequestError as TavilyBadRequestError,
)
from tavily.errors import (
    ForbiddenError as TavilyForbiddenError,
)
from tavily.errors import (
    InvalidAPIKeyError as TavilyInvalidAPIKeyError,
)
from tavily.errors import (
    TimeoutError as TavilyTimeoutError,
)
from tavily.errors import (
    UsageLimitExceededError as TavilyUsageLimitExceededError,
)

from app.services import errors as errors_module
from app.services import retriever as retriever_module
from app.services import tools as tools_module
from app.services.embedder import (
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingNotConfiguredError,
)
from app.services.errors import (
    EMBEDDING_ARREARAGE,
    EMBEDDING_AUTH_FAILED,
    EMBEDDING_NOT_CONFIGURED,
    EMBEDDING_RATE_LIMITED,
    INTERNAL_ERROR,
    LLM_AUTH_FAILED,
    LLM_BAD_REQUEST,
    LLM_CONNECTION_FAILED,
    LLM_CONTENT_FILTERED,
    LLM_NOT_CONFIGURED,
    LLM_OVERLOADED,
    LLM_PERMISSION_DENIED,
    LLM_QUOTA_EXHAUSTED,
    LLM_RATE_LIMITED,
    LLM_SERVER_ERROR,
    LLM_STREAM_INTERRUPTED,
    LLM_TIMEOUT,
    LLM_UNAVAILABLE,
    classify_embedding_error,
    classify_llm_error,
    classify_tool_error,
    classify_unknown_error,
)
from app.services.errors_base import (
    TOOL_AUTH_FAILED,
    TOOL_BAD_REQUEST,
    TOOL_FORBIDDEN,
    TOOL_INTERNAL_ERROR,
    TOOL_NOT_CONFIGURED,
    TOOL_RATE_LIMITED,
    TOOL_TIMEOUT,
    TOOL_UNAVAILABLE,
)
from app.services.llm import LLMNotConfiguredError

# ── 造异常 ────────────────────────────────────────────────────


def _status_error(status: int, body: dict[str, Any] | None = None) -> Exception:
    """造一个带 status_code 与 body 的 SDK 状态异常。

    真造 SDK 的异常需要 httpx.Response + request，麻烦且掩盖了我们要
    测的东西（状态码与响应体如何影响分类）。这里用一个同形的替身：
    分类器只读 ``status_code`` / ``body`` / ``message`` 三个属性。

    **只给 anthropic / openai 这类带 ``status_code`` 的 SDK 用。**
    Tavily 的错误类不带这个属性——给它们套这个替身会造出一种生产上
    不存在的异常，让「按状态码分的档在 Tavily 路径上永远不命中」这个
    真实缺陷在测试里完全看不出来（Tavily 那几条用真异常，见
    ``test_tavily_*``）。
    """

    class _Fake(Exception):
        def __init__(self) -> None:
            super().__init__(f"HTTP {status}")
            self.status_code = status
            self.body = body
            self.message = f"HTTP {status}"

    return _Fake()


def _anthropic_error(
    exc_class: type[Exception], status: int, body: dict[str, Any] | None = None
) -> Exception:
    """造一个真的 anthropic SDK 异常。

    ``anthropic.BadRequestError`` 等需要 httpx.Response。构造一个最简的
    响应对象即可——SDK 只在 ``__init__`` 里读 ``response.status_code``
    与 ``response.headers``。
    """
    response = httpx.Response(
        status, headers={"request-id": "req_test"}, request=httpx.Request("POST", "http://x")
    )
    return exc_class("boom", response=response, body=body)


# ── 模型服务 ──────────────────────────────────────────────────


def test_stream_interrupt_gets_its_own_code() -> None:
    classified = classify_llm_error(httpx2.RemoteProtocolError("x"))
    assert classified.code == LLM_STREAM_INTERRUPTED


def test_timeout_gets_its_own_code() -> None:
    classified = classify_llm_error(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert classified.code == LLM_TIMEOUT


def test_auth_failure_not_reported_as_unavailable() -> None:
    """401 必须是 llm_auth_failed，不能是 unavailable。

    反例实现：所有非流中断都归 unavailable——这条会抓到它。
    """
    exc = _anthropic_error(AuthenticationError, 401)
    classified = classify_llm_error(exc)
    assert classified.code == LLM_AUTH_FAILED
    assert classified.code != LLM_UNAVAILABLE
    # 重试无用：key 无效时重试一万次也是同样结果
    assert classified.retryable is False


def test_permission_denied_gets_its_own_code() -> None:
    exc = _anthropic_error(PermissionDeniedError, 403)
    assert classify_llm_error(exc).code == LLM_PERMISSION_DENIED


def test_connection_failure_distinguished_from_stream_interrupt() -> None:
    """「压根没连上」与「生成途中被掐断」要分开报。

    SDK 把两者都包成 ``APIConnectionError``，靠 ``__cause__`` 链区分。

    反例实现：``APIConnectionError`` 一律报 llm_stream_interrupted——
    这条会抓到它。报「生成途中被中断」而实际一个字都没生成，是假话；
    用户会以为是中转站随机抖动，而真因可能是 base_url 写错了。
    """
    request = httpx2.Request("POST", "http://x")

    try:
        try:
            raise httpx2.ConnectError("conn refused")
        except Exception as err:
            raise APIConnectionError(request=request) from err
    except APIConnectionError as exc:
        classified = classify_llm_error(exc)

    assert classified.code == LLM_CONNECTION_FAILED
    assert classified.code != LLM_STREAM_INTERRUPTED


def test_stream_interrupt_still_reported_when_cause_is_protocol_error() -> None:
    """cause 是 RemoteProtocolError 时仍报「流中断」——不能被新分支误伤。

    反例实现：把 cause 里任何 httpx 异常都当成建连失败——这条会抓到它。
    """
    request = httpx2.Request("POST", "http://x")

    try:
        try:
            raise httpx2.RemoteProtocolError("incomplete chunked read")
        except Exception as err:
            raise APIConnectionError(request=request) from err
    except APIConnectionError as exc:
        classified = classify_llm_error(exc)

    assert classified.code == LLM_STREAM_INTERRUPTED


def test_bare_protocol_error_is_stream_interrupt() -> None:
    """没被 SDK 包装的裸 RemoteProtocolError 仍报流中断。"""
    assert classify_llm_error(httpx2.RemoteProtocolError("x")).code == LLM_STREAM_INTERRUPTED


def test_rate_limit_is_retryable() -> None:
    exc = _anthropic_error(RateLimitError, 429)
    classified = classify_llm_error(exc)
    assert classified.code == LLM_RATE_LIMITED
    assert classified.retryable is True


def test_server_error_reports_status() -> None:
    exc = _status_error(500)
    classified = classify_llm_error(exc)
    assert classified.code == LLM_SERVER_ERROR
    assert "500" in classified.message


def test_overloaded_has_dedicated_code() -> None:
    """529 是「过载」，与普通 5xx 的处置不完全一样，单独一档。"""
    exc = _status_error(529)
    assert classify_llm_error(exc).code == LLM_OVERLOADED


def test_content_filter_distinguished_from_bad_request() -> None:
    """内容安全拦截与普通 400 都是 400，只判状态码分不开。

    反例实现：400 一律报 llm_bad_request——这条会抓到它。
    """
    exc = _anthropic_error(
        BadRequestError,
        400,
        body={"error": {"message": "检测到内容包含敏感或不合规信息,已被内容安全合规系统拦截"}},
    )
    classified = classify_llm_error(exc)
    assert classified.code == LLM_CONTENT_FILTERED
    assert classified.code != LLM_BAD_REQUEST


def test_plain_bad_request_is_not_content_filtered() -> None:
    """真正的参数错仍然报 bad_request——不能把所有 400 都当内容拦截。"""
    exc = _anthropic_error(
        BadRequestError, 400, body={"error": {"message": "max_tokens too large"}}
    )
    assert classify_llm_error(exc).code == LLM_BAD_REQUEST


def test_unknown_exception_falls_back_to_unavailable() -> None:
    classified = classify_llm_error(ValueError("完全不认识"))
    assert classified.code == LLM_UNAVAILABLE


def test_not_configured_detected() -> None:
    """LLMNotConfiguredError 报「未配置」，不是「不可用」。"""
    classified = classify_llm_error(LLMNotConfiguredError("ANTHROPIC_API_KEY 未配置"))
    assert classified.code == LLM_NOT_CONFIGURED
    assert classified.retryable is False


def test_runtime_error_about_missing_config_is_not_configured() -> None:
    """项目里「未配置」有两种抛法——llm.py 抛 LLMNotConfiguredError，
    token.py 抛普通 RuntimeError。后者也要报「未配置」。

    反例实现：只 isinstance 判 LLMNotConfiguredError——这条会抓到它。
    """
    classified = classify_llm_error(RuntimeError("JWT_SECRET_KEY 未配置，无法签发登录票据"))
    assert classified.code == LLM_NOT_CONFIGURED


# ── 嵌入服务 ──────────────────────────────────────────────────


def test_arrearage_detected_from_body_code() -> None:
    """阿里云欠费返回 400 + code: Arrearage。

    反例实现：只看状态码 → 报成「参数错」；只判 body["type"] 而不判
    body["code"] → 漏判。

    **用例的 message 刻意不含欠费字样**——只放 code。如果 message 里也
    写着 "in good standing"，那么只判文案的实现同样能过，这条测试就抓
    不到它了（废测试）。文案分支由下面那条单独守。
    """
    exc = _status_error(400,
        body={"error": {"message": "request rejected", "code": "Arrearage"}},
    )
    classified = classify_embedding_error(exc)
    assert classified.code == EMBEDDING_ARREARAGE
    assert classified.retryable is False


def test_arrearage_detected_from_message() -> None:
    """只认 body["code"] 的实现会漏掉只有文案的情形。"""
    exc = _status_error(400, body={"error": {"message": "your account is overdue, access denied"}}
    )
    assert classify_embedding_error(exc).code == EMBEDDING_ARREARAGE


def test_embedding_auth_failure_distinguished_from_arrearage() -> None:
    exc = _status_error(401)
    classified = classify_embedding_error(exc)
    assert classified.code == EMBEDDING_AUTH_FAILED
    assert classified.code != EMBEDDING_ARREARAGE


def test_wrapped_embedding_error_keeps_arrearage_signal() -> None:
    """走 embedder 真实包装路径的欠费，必须仍判成 embedding_arrearage。

    ## 要防的回归

    ``embedder._embed_one_batch`` 把 SDK 异常包成
    ``EmbeddingError("调用嵌入服务失败：BadRequestError")``，原始异常的
    ``status_code`` / ``body`` 只在 ``__cause__`` 上。分类器若只看
    异常本身，欠费会掉进兜底报成「嵌入服务暂时不可用」。

    而这正是本项目真出过的事故（阿里云 EMBEDDING_API_KEY 欠费 →
    报告 0 引用），改动最该覆盖的场景却没覆盖到。

    ## 注入回归

    把分类器的取值函数改回「只看异常本身」，这条会红。
    """

    response = httpx.Response(
        400, headers={"x-request-id": "r1"}, request=httpx.Request("POST", "http://x")
    )
    sdk_exc = openai.BadRequestError(
        "request rejected",
        response=response,
        body={
            # **message 刻意不含欠费字样**——只放 code。若 message 里也
            # 写着 "in good standing"，那么只判文案的实现同样能过，这条
            # 测试就抓不到它了（废测试）。
            "error": {
                "message": "request rejected",
                "type": "Arrearage",
                "code": "Arrearage",
            }
        },
    )
    # 复刻 embedder.py 的包装方式
    wrapped = EmbeddingError(f"调用嵌入服务失败：{type(sdk_exc).__name__}")
    wrapped.__cause__ = sdk_exc

    classified = classify_embedding_error(wrapped)
    assert classified.code == EMBEDDING_ARREARAGE
    assert classified.retryable is False


def test_wrapped_embedding_error_keeps_auth_signal() -> None:
    """同一条路径，401 也要报鉴权失败。"""

    response = httpx.Response(
        401, headers={"x-request-id": "r2"}, request=httpx.Request("POST", "http://x")
    )
    sdk_exc = openai.AuthenticationError(
        "invalid api key", response=response, body={"error": {"message": "invalid api key"}}
    )
    wrapped = EmbeddingError(f"调用嵌入服务失败：{type(sdk_exc).__name__}")
    wrapped.__cause__ = sdk_exc

    assert classify_embedding_error(wrapped).code == EMBEDDING_AUTH_FAILED


def test_auth_failure_wins_over_arrearage_wording() -> None:
    """401 优先于欠费判断——文案里含 "overdue" 的 401 仍是鉴权失败。

    鉴权是更确定的信号。先判欠费会把「key 无效」指向「充值」，
    方向完全错了。
    """
    exc = _status_error(401, body={"error": {"message": "account overdue, key rejected"}}
    )
    classified = classify_embedding_error(exc)
    assert classified.code == EMBEDDING_AUTH_FAILED
    assert classified.code != EMBEDDING_ARREARAGE


def test_embedding_not_configured() -> None:

    classified = classify_embedding_error(EmbeddingNotConfiguredError("EMBEDDING_API_KEY 未配置"))
    assert classified.code == EMBEDDING_NOT_CONFIGURED
    assert classified.retryable is False


def test_embedding_dimension_mismatch_is_not_retryable() -> None:
    """维度不符要重建索引表，重试一万次也不会变。"""

    exc = DimensionMismatchError("模型返回 1024 维，配置期望 1536 维")
    classified = classify_embedding_error(exc)
    assert classified.retryable is False
    assert "1536" in classified.message


# ── 工具 ──────────────────────────────────────────────────────


def test_tool_rate_limit() -> None:
    exc = _status_error(429)
    classified = classify_tool_error(exc, "tavily_search")
    assert classified.code == TOOL_RATE_LIMITED


def test_tool_auth_failure_not_retryable() -> None:
    exc = _status_error(401)
    classified = classify_tool_error(exc, "tavily_search")
    assert classified.code == TOOL_AUTH_FAILED
    assert classified.retryable is False


def test_tool_unavailable_names_the_tool() -> None:
    """文案必须点名是哪个工具——三个工具的失败原因完全不同。"""
    classified = classify_tool_error(ConnectionError("boom"), "local_search")
    assert classified.code == TOOL_UNAVAILABLE
    assert "local_search" in classified.message


def test_tool_internal_error_is_not_retryable() -> None:
    """我们自己的 bug 不可重试，且要让模型别再调它。

    ## 要防的回归

    旧实现把非网络类异常报成「工具内部出错…请不要重复调用它」，
    那句「不要重复调用」是护栏：坏工具被反复重试会耗尽 MAX_TURNS、
    烧光 token。若改成「请稍后重试」，模型会在同一个坏工具上打转，
    最后什么都产不出来。

    反例实现：一切归 tool_unavailable（retryable=True）——这条会抓到它。
    """
    classified = classify_tool_error(AttributeError("'NoneType' has no attribute 'x'"), "tavily_search")
    assert classified.code == TOOL_INTERNAL_ERROR
    assert classified.retryable is False
    assert "不要重复调用" in classified.message


def test_tool_not_configured_has_own_code() -> None:
    """「没配 key」与「key 无效」分开——处置不同，监控也不该混。"""

    classified = classify_tool_error(LLMNotConfiguredError("TAVILY_API_KEY 未配置"), "tavily_search")
    assert classified.code == TOOL_NOT_CONFIGURED
    assert classified.code != TOOL_AUTH_FAILED


# ── 工具：真实 Tavily 异常 ───────────────────────────────────
#
# 上面那些用 ``_status_error`` 造的替身**带 status_code**，而真实
# Tavily SDK 的错误类全是裸 Exception 子类、不带 status_code。
# 拿替身测 Tavily 路径会得到假信心：分类器按状态码分的档在真实路径上
# 一条都命不中，所有 Tavily 失败都掉进「内部错误」兜底。
#
# 所以这一组用**真的** tavily.errors 类。


def test_tavily_invalid_api_key_is_auth_failure() -> None:
    """key 无效 → 该换 key，不是「内部错误、请不要重复调用」。

    ## 要防的回归

    Tavily 的 ``InvalidAPIKeyError`` 不带 status_code。若分类器只按
    状态码分档，它会掉进兜底分支，文案变成「不要重复调用它」——正好
    和「该换 key」的处置相反。
    """
    classified = classify_tool_error(TavilyInvalidAPIKeyError("invalid key"), "tavily_search")
    assert classified.code == TOOL_AUTH_FAILED
    assert classified.retryable is False
    assert "TAVILY_API_KEY" in classified.message


def test_tavily_usage_limit_is_retryable() -> None:
    """超出用量上限 → 等一会儿还能用，可重试。"""
    classified = classify_tool_error(TavilyUsageLimitExceededError("limit"), "tavily_search")
    assert classified.code == TOOL_RATE_LIMITED
    assert classified.retryable is True


def test_tavily_forbidden_is_not_retryable() -> None:
    classified = classify_tool_error(TavilyForbiddenError("forbidden"), "tavily_search")
    assert classified.code == TOOL_FORBIDDEN
    assert classified.retryable is False


def test_tavily_bad_request_is_not_retryable() -> None:
    """参数错不可重试——重发同一个坏参数还是错。"""
    classified = classify_tool_error(TavilyBadRequestError("bad query"), "tavily_search")
    assert classified.code == TOOL_BAD_REQUEST
    assert classified.retryable is False


def test_tavily_timeout_is_retryable() -> None:
    classified = classify_tool_error(TavilyTimeoutError(15.0), "tavily_search")
    assert classified.code == TOOL_TIMEOUT
    assert classified.retryable is True


def test_httpx_connect_error_is_network_failure() -> None:
    """httpx 的 ConnectError **不是**内建 ConnectionError 的子类。

    实测 ``issubclass(httpx.ConnectError, OSError)`` 为 False——
    只认内建网络异常的话，真网络断连会被报成「内部错误」。
    """
    classified = classify_tool_error(httpx.ConnectError("refused"), "tavily_search")
    assert classified.code == TOOL_UNAVAILABLE
    assert classified.retryable is True


def test_our_own_os_error_is_not_treated_as_network_failure() -> None:
    """FileNotFoundError 是 OSError 子类，但它是**我们自己的 bug**。

    报成「暂时无法连接外部服务，请稍后重试」会让模型反复重试同一个
    坏调用，把 MAX_TURNS 耗光。
    """
    classified = classify_tool_error(FileNotFoundError("missing"), "tavily_search")
    assert classified.code == TOOL_INTERNAL_ERROR
    assert classified.retryable is False


def test_tool_network_error_is_retryable() -> None:
    """网络类仍然可重试——这是旧实现保留下来的语义。"""
    classified = classify_tool_error(ConnectionError("boom"), "tavily_search")
    assert classified.code == TOOL_UNAVAILABLE
    assert classified.retryable is True


def test_tool_preview_is_short() -> None:
    """preview 是给前端轨迹表的一行摘要，不能是整段文案。

    反例实现：preview 直接塞 message——这条会抓到它。
    """
    classified = classify_tool_error(ConnectionError("boom"), "local_search")
    assert len(classified.preview) <= 20
    assert classified.preview != classified.message


# ── 兜底 ──────────────────────────────────────────────────────


def test_unknown_error_has_code_and_place() -> None:
    classified = classify_unknown_error(ValueError("x"), "研究流程")
    assert classified.code == INTERNAL_ERROR
    assert "研究流程" in classified.message
    assert classified.retryable is False


def test_every_classified_has_code_message_and_preview() -> None:
    """所有分类都要有 code / message / preview 三样。

    空 preview 会让前端工具轨迹表出现一个空格子——看不出是失败还是
    没跑。这是契约，不是风格。
    """
    cases = [
        classify_llm_error(httpx2.RemoteProtocolError("x")),
        classify_llm_error(APITimeoutError(request=httpx.Request("POST", "http://x"))),
        classify_llm_error(ValueError("x")),
        classify_embedding_error(ValueError("x")),
        classify_tool_error(ValueError("x"), "dedup"),
        classify_unknown_error(ValueError("x"), "研究流程"),
    ]
    for classified in cases:
        assert classified.code, classified
        assert classified.message, classified
        assert classified.preview, classified


def test_embedding_rate_limited_has_own_code() -> None:
    """嵌入服务限流要单独一档。

    「限流」与「暂时不可用」都可重试，但处置不同：限流是「等一会儿再试」，
    不可用可能是别的原因。报成兜底文案，用户不知道要等。
    """
    exc = _status_error(429, body={"error": {"message": "rate limited"}})
    classified = classify_embedding_error(exc)
    assert classified.code == EMBEDDING_RATE_LIMITED
    assert classified.retryable is True


# ── 内容安全拦截：这一档要留，文案要改 ───────────────────────
#
# 实测（2026-10-23）：用完全虚构的等价负载复刻那次失败请求，连发 10 次全部通过；
# 换真实标题、换 50 条高密度个人字段、换多轮结构、换饱和引用表形态——全部通过。
# 失败率 0/10。**上游没拦。** 真实成因是检索侧没有相关性下限：
# 模型拿着「个人编号 / 参保人手机 / 身份证」当证据去回答手机质量对比，
# 拼出一个畸形上下文，上游对这个上下文报了内容安全。
#
# 所以：上游内容安全这一档**要保留**（Anthropic 官方确实有这套机制，我们分不清
# 「上游拦了真内容」和「上游对畸形上下文报内容安全」），但文案不能再说「调整问题措辞」。


def _content_filtered_exc() -> Exception:
    """上游报内容安全拦截的那个 400。

    正文刻意用上游的原话（实测抓到的报文），保证关键词匹配路径被走到。
    """
    return _anthropic_error(
        BadRequestError,
        400,
        body={"error": {"message": "检测到内容包含敏感或不合规信息,已被内容安全合规系统拦截"}},
    )


def test_quota_exhausted_distinguished_from_permission_denied() -> None:
    """配额用完要和「没模型权限」分开——处置方式完全不同。

    ## 要防的回归

    实测（2026-10-27，中转站 llmapi.pro）：试用配额用完时上游返回的是
    **403 + permission_error**，message 是
    「Trial quota (40 requests) used up. Please upgrade to a plan.」
    只按状态码分档会报成「当前 key 没有该模型的权限」——把用户引向
    「去申请模型权限」，而真正要做的是**充值或换套餐**。

    反例实现：403 一律报 llm_permission_denied —— 这条会红。
    """
    exc = _anthropic_error(
        PermissionDeniedError,
        403,
        body={
            "error": {
                "type": "permission_error",
                "message": "Trial quota (40 requests) used up. Please upgrade to a plan.",
            }
        },
    )
    classified = classify_llm_error(exc)

    assert classified.code == LLM_QUOTA_EXHAUSTED
    assert classified.code != LLM_PERMISSION_DENIED
    # 文案要指向充值/换套餐，不能说「申请模型权限」
    assert "配额" in classified.message or "额度" in classified.message, classified.message
    assert "权限" not in classified.message, classified.message
    # 配额不会自己恢复 → 不可重试
    assert classified.retryable is False


def test_quota_exhausted_on_401_also_recognized() -> None:
    """有的中转站在余额耗尽时返回 401 而不是 403——同样要能识别。

    反例实现：只查 403 —— 这条会红。
    """
    exc = _anthropic_error(
        AuthenticationError,
        401,
        body={
            "error": {
                "type": "authentication_error",
                "message": "Insufficient balance. Please top up your account.",
            }
        },
    )
    classified = classify_llm_error(exc)

    assert classified.code == LLM_QUOTA_EXHAUSTED
    assert classified.code != LLM_AUTH_FAILED


def test_real_permission_denied_still_reported_as_permission() -> None:
    """真的「没模型权限」不能被误判成配额用完。

    反例实现：把任何 403 都报成配额 —— 这条会红。
    """
    exc = _anthropic_error(
        PermissionDeniedError,
        403,
        body={
            "error": {
                "type": "permission_error",
                "message": "Your API key does not have access to model claude-opus-5",
            }
        },
    )
    classified = classify_llm_error(exc)

    assert classified.code == LLM_PERMISSION_DENIED
    assert classified.code != LLM_QUOTA_EXHAUSTED


def test_content_filtered_tier_is_kept() -> None:
    """这一档不能删——上游确实可能拦内容。

    反例实现：把 LLM_CONTENT_FILTERED 并进 llm_bad_request——这条会红。
    """
    classified = classify_llm_error(_content_filtered_exc())

    assert classified.code == LLM_CONTENT_FILTERED
    assert classified.code != LLM_BAD_REQUEST


def test_content_filtered_message_does_not_ask_user_to_rephrase() -> None:
    """文案不能让人去改措辞。

    **注入回归**：把文案改回「请求被上游内容安全策略拦截，请调整问题措辞后重试」
    —— 这条会红。

    为什么这条重要：用户看到「调整问题措辞」会以为是自己写错了问题，反复改措辞
    重试，而真正的原因是资料库和问题的错配——改一万次措辞也没用。
    """
    message = classify_llm_error(_content_filtered_exc()).message

    for banned in ("措辞", "换个问法", "换一种问法", "改写问题", "重新表述"):
        assert banned not in message, f"文案仍在让用户改问法：{message}"


def test_content_filtered_message_points_at_sensitive_material() -> None:
    """文案要指向**资料含敏感信息**，而不是「资料与问题不匹配」。

    2026-10-25 修订的理由：相关性下限上线后，无关切片不会再进上下文——
    「检索到的资料与问题不匹配」这条成因基本被消除了。再遇到内容安全拦截，
    最可能是资料本身与问题相关、但含敏感信息（个人身份信息、医疗/保险类
    文档的敏感段落）。文案还指向已被修掉的成因，会把用户引到错误方向。

    反例实现：文案只写「请稍后重试」或仍写「资料与问题不匹配」——这条会红。
    """
    message = classify_llm_error(_content_filtered_exc()).message

    assert any(k in message for k in ("资料", "检索", "内容", "证据")), message
    # 要点出「敏感」——用户该做的是脱敏，不是改措辞
    assert any(k in message for k in ("敏感", "脱敏", "安全策略", "安全")), message
    # 不能再把已被修掉的成因当主要解释
    assert "不匹配" not in message, message
    assert "无关" not in message, message


def test_content_filtered_is_not_retryable() -> None:
    """这一档不可重试。

    判断依据：重试按钮重发的是**同一个问题**。上游真拦了，重试无用；真因是
    资料错配的话，同一个问题重发一百次还是同一份错配的资料。「换个问题」不是重试，
    那是用户改输入。
    """
    assert classify_llm_error(_content_filtered_exc()).retryable is False


# ── 新的「检索无相关性」一档 ─────────────────────────────────
#
# 这是**本项目自己的**错误，不是上游的：local_search 返回空的时候，
# 现在那条路径是 ok=True 的正常分支，模型会看到「用户的资料库里没有检索到相关内容」
# 然后继续用联网搜索作答，用户完全不知道自己的私有资料被跳过了。


_RETRIEVAL_CODE_PATTERN = re.compile(r"(match|retriev|relevan|irrelev)")


def _retrieval_codes() -> list[str]:
    """errors.__all__ 里语义属于「检索没命中」的错误码。

    规格给了建议名（``retrieval_no_match``）但明确允许实现方自选
    （「建议 retrieval_no_match，但你可以选更好的名字」），所以这里按语义关键词找，
    而不是钉死一个字符串。既有错误码（llm_* / tool_* / embedding_* / internal_*）
    都不含这些词，不会被误认。
    """
    exported = getattr(errors_module, "__all__", None)
    assert exported, "errors.py 必须有 __all__（新错误码要在这里导出）"
    return [code for code in exported if _RETRIEVAL_CODE_PATTERN.search(code)]


def _classify_tool_failure(exc: Exception, tool: str = "local_search") -> Any:
    """把异常分类。分类入口按实现可能的位置都试一遍。

    规格只承诺「tools.py 的 _classify_tool_failure 要能产生这一档」，
    而它多半只是 errors.classify_tool_error 的一层壳——两个都试，
    参数顺序也两种都试（_classify_tool_failure 是 (name, exc)，
    classify_tool_error 是 (exc, tool_name)）。
    """
    candidates: list[Any] = []
    private = getattr(tools_module, "_classify_tool_failure", None)
    if callable(private):
        candidates.append(private)
    candidates.append(classify_tool_error)

    for fn in candidates:
        for args in ((exc, tool), (tool, exc), (exc,)):
            try:
                return fn(*args)
            except TypeError:
                continue
    raise AssertionError(
        "找不到可用的工具失败分类入口（_classify_tool_failure / classify_tool_error）"
    )


def _produced_retrieval_codes() -> dict[str, Any]:
    """找出「能被造出来」的新错误码。

    触发方式规格没规定（专用异常 / 标志位都行），所以这里把 tools / errors /
    retriever 三个模块里暴露的异常类都过一遍分类器，看哪些能造出这一档。
    """
    wanted = set(_retrieval_codes())
    produced: dict[str, Any] = {}
    for module in (tools_module, errors_module, retriever_module):
        for obj in vars(module).values():
            if not (isinstance(obj, type) and issubclass(obj, Exception)):
                continue
            try:
                exc = obj("boom")
            except Exception:
                continue
            try:
                classified = _classify_tool_failure(exc)
            except Exception:
                # 分类器对某些合成异常会自己炸（如异常链里有非异常对象）。
                # 那是分类器的边界，不是本用例要断言的东西——跳过即可。
                continue
            code = getattr(classified, "code", None)
            if code in wanted:
                produced[code] = classified
    return produced


def test_new_retrieval_error_code_is_exported_and_named_by_convention() -> None:
    """新错误码必须存在、已导出、且符合命名约定。

    命名约定（见 errors_base.py 的 TOOL_* 段与 errors.py 的 LLM_* 段）：
    小写下划线，「语义前缀 + 具体含义」。

    反例实现：
    - 用了大写 / 驼峰 / 短横线 —— 这条会红
    - 定义了但没进 __all__ —— 这条会红
    - 干脆没定义 —— 这条会红
    """
    codes = _retrieval_codes()

    assert codes, "errors.__all__ 里必须有「检索无相关性」这一档的错误码"
    for code in codes:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), f"{code} 不是小写下划线命名"
        assert code.count("_") >= 1, f"{code} 缺少「语义前缀 + 具体含义」的分段"
        assert hasattr(errors_module, code), f"{code} 没从 errors.py 导出"


def test_new_retrieval_error_code_can_be_produced() -> None:
    """这一档必须真的能被造出来，不是只写了个常量。

    反例实现：错误码定义了但分类器里没接，任何异常都造不出它——这条会红。
    """
    produced = _produced_retrieval_codes()

    assert produced, "没有任何路径能造出「检索无相关性」这一档"


def test_new_retrieval_error_code_is_not_retryable() -> None:
    """不可重试：重新检索一次大概率还是同样结果。

    反例实现：retryable 取 True（前端给用户一个「重试」按钮，点了还是同样的
    错配资料，只是白烧一轮 token）—— 这条会红。
    """
    produced = _produced_retrieval_codes()

    assert produced
    for code, classified in produced.items():
        assert classified.code == code
        assert classified.message, f"{code} 缺 message"
        assert classified.preview, f"{code} 缺 preview"
        assert classified.retryable is False, f"{code} 不该可重试"
