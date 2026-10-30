"""错误分类：把各层异常翻译成「具体、可执行」的错误。

## 为什么要有这个模块

出错时用户只能看到一行字。这一行字必须回答两个问题：

1. **到底哪坏了** —— 模型服务？嵌入服务？工具？数据库？
2. **我该干什么** —— 等一会儿重试？还是去改配置？

「模型服务暂时不可用，请稍后重试」把四种完全不同的失败揉成一句话：
key 失效、账户欠费、参数错、连接掐断。用户看到它只知道「再试一次」，
但「key 失效」重试一万次也没用。

## 分层

每个外部能力有自己的失败形态，分类必须分层做，不能各写各的：

- **模型服务**（Anthropic）—— 见 :func:`classify_llm_error`
- **嵌入服务**（DashScope / OpenAI）—— 见 :func:`classify_embedding_error`
- **工具**（Tavily 等）—— 见 :func:`classify_tool_error`

## 边界

**只对用户暴露「可行动的」信息。** 密钥、内部路径、堆栈不进文案——
但**原因必须具体**：把「欠费」说成「暂时不可用」等于没报。分类的作用
是让用户知道该做什么，不是泄密。

判定依据全部来自异常类与状态码，不靠猜。无法归类的异常一律落到
``*_unknown`` 兜底分支，并打日志——**兜底不等于不报**。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import httpx2
from anthropic import AnthropicError

from app.services.embedder import (
    DimensionMismatchError,
    EmbeddingNotConfiguredError,
)
from app.services.errors_base import (
    TOOL_AUTH_FAILED,
    TOOL_INTERNAL_ERROR,
    TOOL_NOT_CONFIGURED,
    TOOL_RATE_LIMITED,
    TOOL_TIMEOUT,
    TOOL_UNAVAILABLE,
    Classified,
    RetrievalNoMatchError,
    RetrievalNotEvaluatedError,
    cause_chain,
)
from app.services.errors_tavily import classify_tavily_error, find_tavily_error
from app.services.llm import LLMNotConfiguredError, is_stream_interrupt, is_timeout
from app.services.stream import ErrorEvent

logger = logging.getLogger(__name__)

# ── 错误 code ─────────────────────────────────────────────────
#
# code 是给程序看的：前端把它显示在错误横幅上（用户据此判断该等还是
# 该改配置），日志里也能按它归类。命名规则：``<层>_<原因>``。新增 code
# 时前端 ``lib/api/sse.ts`` 的 ErrorEventV 不用改（code 是 string），
# 但文案要跟着改。

# 模型服务
LLM_AUTH_FAILED = "llm_auth_failed"
"""API key 无效 / 账户状态异常。重试无用，必须换 key 或充值。"""

LLM_PERMISSION_DENIED = "llm_permission_denied"
"""key 有效但没这个模型的权限。"""

LLM_QUOTA_EXHAUSTED = "llm_quota_exhausted"
"""上游**配额/额度用完**（试用额度、余额、套餐请求数上限）。

跟 :data:`LLM_PERMISSION_DENIED` 分开是因为**处置方式完全不同**：
额度用完要去充值或换套餐，而「没模型权限」要去申请权限——照着错的
诊断做，用户会一直找错方向。

实测（2026-10-27，中转站 llmapi.pro）：试用配额用完时上游返回的是
**403 + permission_error**，但 message 写的是
「Trial quota (40 requests) used up. Please upgrade to a plan.」
——只看状态码会误判成「没模型权限」。
"""

LLM_BAD_REQUEST = "llm_bad_request"
"""请求本身被上游拒（参数错、模型名不存在、内容安全拦截）。"""

LLM_RATE_LIMITED = "llm_rate_limited"
"""被限流。退避后重试可能成功。"""

LLM_SERVER_ERROR = "llm_server_error"
"""上游 5xx。服务端问题，重试可能成功。"""

LLM_OVERLOADED = "llm_overloaded"
"""上游过载（529）。比 5xx 更明确的重试信号。"""

LLM_STREAM_INTERRUPTED = "llm_stream_interrupted"
"""SSE 流消费途中被掐断。整轮重发后仍失败。"""

LLM_CONNECTION_FAILED = "llm_connection_failed"
"""连不上模型服务（建连阶段就失败，请求根本没发出去）。"""

LLM_TIMEOUT = "llm_timeout"
"""等太久没响应。"""

LLM_CONTENT_FILTERED = "llm_content_filtered"
"""上游内容安全拦截。

**重试无用**——重试按钮重发的还是同一个问题、同一份资料。换问法也没用：
实测复刻那次失败的请求，连发 10 次全部通过，上游没误伤。

**成因提示（2026-10-25 修订）**：相关性下限上线后，「检索到的资料与问题
不匹配」这条成因基本被消除了——无关切片不会再进上下文。所以再遇到这一档，
最可能是**资料本身与问题相关，但内容含敏感信息**（个人身份信息、医疗/保险
类文档的敏感段落等），被上游策略拦下。要做的是检查或脱敏那份资料，
而不是改措辞。
"""

LLM_UNAVAILABLE = "llm_unavailable"
"""模型服务兜底：归不出类的失败。"""

LLM_NOT_CONFIGURED = "llm_not_configured"
"""没配 API key。"""

# 嵌入服务（本地资料检索用）
EMBEDDING_ARREARAGE = "embedding_arrearage"
"""嵌入账户欠费。充值前本地向量召回全挂。"""

EMBEDDING_AUTH_FAILED = "embedding_auth_failed"
"""嵌入 key 无效。"""

EMBEDDING_NOT_CONFIGURED = "embedding_not_configured"
"""没配 EMBEDDING_API_KEY。"""

EMBEDDING_DIMENSION_MISMATCH = "embedding_dimension_mismatch"
"""返回维度与索引表不符。要重建索引表，改配置解决不了。"""

EMBEDDING_RATE_LIMITED = "embedding_rate_limited"
"""嵌入服务限流。等一会儿就好——与「暂时不可用」的处置不同。"""

EMBEDDING_UNAVAILABLE = "embedding_unavailable"
"""嵌入服务兜底。"""

# 检索（本地资料）
RETRIEVAL_NO_MATCH = "retrieval_no_match"
"""本地资料与问题不相关：检索有候选，但全被相关性下限挡掉了。

不可重试——同一个问题重新检索一次，大概率还是同一份错配的资料。
"""

RETRIEVAL_NOT_EVALUATED = "retrieval_not_evaluated"
"""**没法**判断相关性——与「判了，不相关」是两回事。

什么时候落这一档：没配嵌入 key（向量路根本没跑）、或资料刚上传、摄取还在
进行（切片入库了但索引没建好）。这两种情况下说「资料与问题不相关」是
**事实性错误**——用户的资料可能高度相关。

也不可重试：重试不会让索引突然建好，也不会让嵌入 key 出现。
"""

# 错误码对外暴露的是**小写码串**（前端错误横幅、监控聚合都按它走），
# 所以模块同时导出小写别名：按码串就能取到，不必先知道 Python 常量名。
retrieval_no_match = RETRIEVAL_NO_MATCH
retrieval_not_evaluated = RETRIEVAL_NOT_EVALUATED

# 工具层的 code 定义在 ``errors_tavily.py``——工具的错误形态由各外部
# 服务自己的 SDK 决定，代码跟着服务走。

# 通用
INTERNAL_ERROR = "internal_error"
"""意料之外的 bug。retryable=False。"""


# ── 分类结果 ─────────────────────────────────────────────────


def _status_code(exc: BaseException) -> int | None:
    """取异常链上的 HTTP 状态码。两个 SDK 的 APIStatusError 都有这字段。"""
    for item in cause_chain(exc):
        value = getattr(item, "status_code", None)
        if isinstance(value, int):
            return value
        response = getattr(item, "response", None)
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def _error_body(exc: BaseException) -> dict[str, Any]:
    """取异常链上响应体里的 error 对象。拿不到就返回空 dict。

    上游的错误细节都在 ``body["error"]`` 里——阿里云的 ``Arrearage``
    就在 ``error["code"]``。没有它就分不出「欠费」和「参数错」。
    """
    for item in cause_chain(exc):
        body = getattr(item, "body", None)
        if not isinstance(body, dict):
            continue
        error = body.get("error")
        if isinstance(error, dict):
            return error
        return body
    return {}


def _error_code(exc: BaseException) -> str:
    """取上游的业务错误码（阿里云的 ``Arrearage``、OpenAI 的 ``invalid_api_key``）。

    来自响应体而不是异常类——同一个 400 可能欠费也可能参数错，只有响应体
    里的 code 能区分。
    """
    body = _error_body(exc)
    for key in ("code", "type"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _error_message(exc: BaseException) -> str:
    """取上游给的人类可读错误说明。取不到就用异常本身的 message。"""
    body = _error_body(exc)
    value = body.get("message")
    if isinstance(value, str) and value:
        return value
    for item in cause_chain(exc):
        message = getattr(item, "message", None)
        if isinstance(message, str) and message:
            return message
    return str(exc)


# ── 模型服务 ─────────────────────────────────────────────────


# HTTP 状态码 → 分类。**按状态码查表**，不写一长串 if。
#
# 表里放的是「每一档的处置方式不同」的那些：401 要换 key、403 要换权限、
# 429 要等、5xx 只能重试。写成一串 if 的话，加一档要改函数体，
# 而函数体已经接近项目 50 行的上限。
#
# 值是 (code, 文案, 短标签, 是否可重试)。
_STATUS_CLASSES: dict[int, tuple[str, str, str, bool]] = {
    401: (
        LLM_AUTH_FAILED,
        "模型服务鉴权失败：API key 无效或已失效，请检查 ANTHROPIC_API_KEY",
        "API key 无效",
        False,
    ),
    403: (
        LLM_PERMISSION_DENIED,
        "模型服务拒绝访问：当前 key 没有该模型的权限",
        "无模型权限",
        False,
    ),
    429: (
        LLM_RATE_LIMITED,
        "模型服务限流，请稍后重试",
        "模型服务限流",
        True,
    ),
    529: (
        LLM_OVERLOADED,
        "模型服务当前过载，请稍后重试",
        "模型服务过载",
        True,
    ),
}


def classify_llm_error(exc: BaseException) -> Classified:
    """把模型服务的异常分类成一条具体的错误。

    分档依据与优先级：

    1. **连接层**（断流 / 超时）—— 换 payload 重试有意义。
    2. **状态码**（401 / 403 / 429 / 5xx）—— 每一档的处置方式不同。
    3. **内容安全**—— 400 里的一类特殊情形，重试无用，必须单独分出来。

    「内容安全」为什么要从 400 里单独挖出来：上游**确实**有这套机制
    （返回 ``检测到内容包含敏感或不合规信息,已被内容安全合规系统拦截``），
    报成「请求被拒」会把它和参数错混在一起。

    但**不能告诉用户去改问法**：实测复刻那次被判「内容安全」的请求，
    连发 10 次全部通过，上游没误伤——真实成因是检索侧没有相关性下限，
    模型拿着「参保人手机 | tel」当证据去回答手机质量对比，拼出一个畸形
    上下文，上游对这个上下文报了内容安全。**上游返回的内容是结果，不是原因。**
    而「换个问法」对这种成因没用：问题在资料库与问题的错配上。

    这一档仍要保留：我们没法区分「上游拦了真内容」与「上游对畸形上下文
    报内容安全」——两种情况的响应体一样。所以文案改成指向**大概率**的
    成因（资料与问题不匹配），而不是让用户去改措辞。
    """
    if _is_not_configured(exc):
        return _not_configured_classified(exc)

    if is_stream_interrupt(exc):
        return _stream_interrupt_classified(exc)

    if is_timeout(exc):
        return Classified(
            LLM_TIMEOUT,
            "模型响应超时，请缩小问题范围后重试",
            preview="模型响应超时",
        )

    status = _status_code(exc)
    if status is None:
        return Classified(
            LLM_UNAVAILABLE,
            "模型服务暂时不可用，请稍后重试",
            preview="模型服务不可用",
        )

    if status == 400:
        return _bad_request_classified(exc)

    # 配额/额度耗尽的判定**在状态码表之前**。
    #
    # 实测（2026-10-27，中转站 llmapi.pro）：试用配额用完时上游返回
    # **403 + permission_error**，message 是
    # 「Trial quota (40 requests) used up. Please upgrade to a plan.」
    # 只看状态码会落进 403 那档，报成「当前 key 没有该模型的权限」——
    # 用户会去申请模型权限，而真正要做的是充值或换套餐。
    #
    # 401 同样要查：有的中转站在余额耗尽时返回 401 而非 403。
    if status in (401, 403) and _is_quota_exhausted(_error_message(exc)):
        return Classified(
            LLM_QUOTA_EXHAUSTED,
            "模型服务配额已用完（试用额度或账户余额不足），请充值或更换套餐后重试",
            preview="模型服务配额用完",
            retryable=False,
        )

    # 表查询**在 5xx 判断之前**：529（过载）也在 5xx 区间里，但它有
    # 独立的处置方式与更明确的文案。
    entry = _STATUS_CLASSES.get(status)
    if entry is not None:
        code, message, preview, retryable = entry
        return Classified(code, message, preview=preview, retryable=retryable)

    if status >= 500:
        return Classified(
            LLM_SERVER_ERROR,
            f"模型服务返回 {status}，请稍后重试",
            preview=f"模型服务 {status}",
        )

    return Classified(
        LLM_UNAVAILABLE,
        "模型服务暂时不可用，请稍后重试",
        preview="模型服务不可用",
    )


def _not_configured_classified(exc: BaseException) -> Classified:
    """「没配」这一档。

    文案跟着异常走，不写死变量名。``llm.py`` 抛的是
    「ANTHROPIC_API_KEY 未配置」，但同一个判据也会命中 ``token.py``
    的「JWT_SECRET_KEY 未配置」——写死 ANTHROPIC 会把运维指向错误的变量。
    """
    return Classified(
        LLM_NOT_CONFIGURED,
        f"服务未配置：{_trim(str(exc), 60)}",
        preview="服务未配置",
        retryable=False,
    )


def _stream_interrupt_classified(exc: BaseException) -> Classified:
    """「流被掐断」这一档。

    「流消费途中被掐断」与「压根没连上」是两回事，处置也不同：
    前者是中转站随机断连，等一会儿重试可能就过了；后者是网络不通
    或地址错了，重试多半还是连不上。
    """
    if _is_connection_failure(exc):
        return Classified(
            LLM_CONNECTION_FAILED,
            "连不上模型服务，请检查网络或 ANTHROPIC_BASE_URL 配置后重试",
            preview="连不上模型服务",
        )
    return Classified(
        LLM_STREAM_INTERRUPTED,
        "模型连接在生成途中被中断，已自动重试仍失败，请稍后重试",
        preview="模型连接中断",
    )


def _bad_request_classified(exc: BaseException) -> Classified:
    """400 这一档——内容安全拦截要从普通参数错里分出来。

    **不回显上游原文**。400 的 message 可能把请求内容带回来
    （「字段 X 的值 Y 不合法」这类），原样透给用户等于把我们的输入
    暴露到错误横幅上。分类已经够具体，原文进日志即可。
    """
    detail = _error_message(exc)
    if _is_content_filtered(detail):
        return Classified(
            LLM_CONTENT_FILTERED,
            "模型服务拒绝了这次请求：送进去的资料内容触发了上游的安全策略。"
            "常见原因是资料本身与问题相关，但其中含有敏感信息（个人身份信息、"
            "医疗或保险类文档的敏感段落等）。请检查或脱敏资料库里的相关文档"
            "后重试。",
            preview="内容被安全策略拦截",
            retryable=False,
        )
    logger.info("模型服务拒绝请求（400）：%s", detail)
    return Classified(
        LLM_BAD_REQUEST,
        "模型服务拒绝了这次请求，请检查问题描述后重试",
        preview="请求被模型服务拒绝",
        retryable=False,
    )


# 内容安全拦截的特征词。命中即判定为「内容被拦」而非「参数错」。
#
# 为什么用关键词匹配而不是只看 400：上游返回的 400 有两类，一类是
# 内容安全拦截（400 + 这类文案），一类是真正的参数错。它们的处置
# 完全不同——前者要改问法，后者要改代码。
_CONTENT_FILTER_MARKERS = (
    "内容安全",
    "敏感",
    "不合规",
    "合规系统",
    "safety",
)


def _is_content_filtered(detail: str) -> bool:
    lowered = detail.lower()
    return any(marker in lowered for marker in _CONTENT_FILTER_MARKERS)


# 配额/额度耗尽的特征词。
#
# **为什么不能只看状态码**：实测（2026-10-27，中转站 llmapi.pro）上游在
# 试用配额用完时返回的是 **403 + permission_error**，message 为
# 「Trial quota (40 requests) used up. Please upgrade to a plan.」。
# 只按状态码分档会报成「当前 key 没有该模型的权限」——把用户引向
# 「去申请模型权限」，而真正要做的是充值或换套餐。
#
# 与 _CONTENT_FILTER_MARKERS 同理：**响应体里的 message 才有信息**，
# 状态码只是粗粒度的分类。
_QUOTA_MARKERS = (
    "quota",
    "trial quota",
    "used up",
    "upgrade to a plan",
    "insufficient",
    "余额不足",
    "额度不足",
    "配额不足",
    "已达上限",
)


def _is_quota_exhausted(detail: str) -> bool:
    """上游是不是「配额/额度用完」了。"""
    lowered = detail.lower()
    return any(marker in lowered for marker in _QUOTA_MARKERS)


def _is_not_configured(exc: BaseException) -> bool:
    """判断是不是「没配 key」。

    不只认 ``LLMNotConfiguredError``：项目里「未配置」有两种抛法——
    ``llm.py`` 抛前者，而 ``token.py`` 抛的是普通
    ``RuntimeError("JWT_SECRET_KEY 未配置")``。后者也是部署问题，
    报成「模型服务不可用」会让运维查错方向。

    判据是异常类型 + 消息里的「未配置」字样，两者都要。
    """
    if isinstance(exc, LLMNotConfiguredError):
        return True
    return isinstance(exc, RuntimeError) and "未配置" in str(exc)


# 建连阶段失败的 httpx 异常。``RemoteProtocolError`` **不在**其中——
# 那是「连上了但响应没发完」，属于流中断。
_CONNECTION_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx2.ConnectError,
    httpx2.ConnectTimeout,
)


def _is_connection_failure(exc: BaseException) -> bool:
    """判断是不是「压根没连上」。

    ## 为什么能区分

    SDK 把所有传输层异常都包成 ``APIConnectionError``，不带「建连失败」
    还是「流消费途中断连」的信息——但它用 ``raise ... from err`` 包，
    原始 httpx 异常留在 ``__cause__`` 里。顺着 cause 链找就能分清。

    ## 为什么这个区分值得做

    两者都归「流中断」的话，文案会说「模型连接在生成途中被中断」——
    但建连失败时**一个字都还没生成**，说「生成途中」是假的。用户会以为是
    中转站随机抖动，等一会儿重试；真因可能是 base_url 写错了。

    链上找不到 httpx 异常时返回 False：宁可报「流中断」也不要把
    「没连上」误报出去——那会把配置问题引向错误的排查方向。
    """
    return any(isinstance(item, _CONNECTION_ERRORS) for item in cause_chain(exc))


def _trim(text: str, limit: int = 120) -> str:
    """截断上游原文，避免把整段 HTML 塞进错误文案。"""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


# ── 嵌入服务 ─────────────────────────────────────────────────


def classify_embedding_error(exc: BaseException) -> Classified:
    """把嵌入服务的异常分类成一条具体的错误。

    嵌入服务挂在 ``local_search`` 下面：问句要先被编码成向量才能查本地
    资料，所以嵌入服务一挂，本地检索那一路就整个断掉——但报告仍然能出
    （走联网检索）。用户必须知道「本地资料没被查」这件事，否则会以为
    报告里没有引用是因为资料库里确实没有。
    """
    if isinstance(exc, EmbeddingNotConfiguredError):
        return Classified(
            EMBEDDING_NOT_CONFIGURED,
            "嵌入服务未配置：缺少 EMBEDDING_API_KEY，本地资料检索不可用",
            preview="嵌入服务未配置",
            retryable=False,
        )

    if isinstance(exc, DimensionMismatchError):
        return Classified(
            EMBEDDING_DIMENSION_MISMATCH,
            f"嵌入模型返回的维度与索引表不符：{_trim(str(exc))}",
            preview="嵌入维度不匹配",
            retryable=False,
        )

    # **401 排在欠费前面**：鉴权失败是更确定的信号，而欠费靠文案里的
    # "overdue" 之类的词判——一个 401 的文案里若恰好含这类词，
    # 先判欠费就会把「key 无效」误报成「欠费」，指向错误的处置。
    status = _status_code(exc)
    if status == 401:
        return Classified(
            EMBEDDING_AUTH_FAILED,
            "嵌入服务鉴权失败：API key 无效，请检查 EMBEDDING_API_KEY",
            preview="嵌入 key 无效",
            retryable=False,
        )

    if _is_arrearage(exc):
        return Classified(
            EMBEDDING_ARREARAGE,
            "嵌入服务账户欠费，本地资料向量检索不可用，请充值后重试",
            preview="嵌入服务欠费",
            retryable=False,
        )

    if status == 429:
        return Classified(
            EMBEDDING_RATE_LIMITED,
            "嵌入服务被限流，本地资料向量检索不可用，请稍后重试",
            preview="嵌入服务被限流",
        )

    return Classified(
        EMBEDDING_UNAVAILABLE,
        "嵌入服务暂时不可用，本地资料向量检索不可用",
        preview="嵌入服务不可用",
    )


def _is_arrearage(exc: BaseException) -> bool:
    """判断是不是「账户欠费」。

    阿里云百炼返回 400 + ``code: "Arrearage"``，文案是英文的
    "Access denied, please make sure your account is in good standing"。
    两种都认——只认 code 会漏掉别的厂商用文案表达同一件事。
    """
    if _error_code(exc).lower() == "arrearage":
        return True
    message = _error_message(exc).lower()
    return "arrearage" in message or "overdue" in message or "in good standing" in message


# ── 工具 ─────────────────────────────────────────────────────


# 网络类异常——「连不上外部服务」，值得重试。
#
# **不用 OSError 全族**：``FileNotFoundError`` / ``PermissionError`` 也
# 是 OSError 的子类，但它们是我们自己的 bug（路径写错、文件没权限），
# 不是外部服务不可用。报成「暂时无法连接，请稍后重试」会让模型反复
# 重试同一个坏调用，把 MAX_TURNS 耗光。
#
# httpx 的 ``ConnectError`` **不是**内建 ``ConnectionError`` 的子类
# （实测 ``issubclass(httpx.ConnectError, OSError)`` 为 False），
# 所以 httpx 的传输层异常必须单列。
_NETWORK_ERRORS = (
    ConnectionError,
    TimeoutError,
    httpx.TransportError,
    httpx2.TransportError,
)


def _retrieval_no_match_classified() -> Classified:
    """「本地资料与问题无关」这一档。

    不是外部服务挂了，是**我们的检索**判它不相关——所以 code 带 retrieval
    前缀，不跟 tool_* 那一族混在一起。

    不可重试：同一个问题重新检索一次，大概率还是同一份错配的资料。
    """
    return Classified(
        RETRIEVAL_NO_MATCH,
        "用户的资料库里没有检索到与问题相关的内容——已有资料与本次问题"
        "不相关，不要把它们当证据。本次回答没有使用私有资料，请如实向"
        "用户说明这一点，也不要凭猜测补充数字。",
        preview="资料与问题不相关",
        retryable=False,
    )


def _retrieval_not_evaluated_classified() -> Classified:
    """「**没法**判断相关性」这一档——与「判了，不相关」是两回事。

    什么时候落这一档：没配嵌入 key（向量路根本没跑）、或资料刚上传、
    摄取还在进行（切片入库了但索引没建好）。这两种情况下说「资料与
    问题不相关」是**事实性错误**——用户的资料可能高度相关。

    也不可重试：重试不会让索引突然建好，也不会让嵌入 key 出现。
    """
    return Classified(
        RETRIEVAL_NOT_EVALUATED,
        "本次无法检索用户的私有资料——检索索引尚未就绪，或语义检索未启用。"
        "**不要据此说用户的资料与问题无关**（那可能是错的），也不要凭猜测"
        "补充私有资料里的内容。如实说明这次没有用到私有资料即可。",
        preview="无法评估资料相关性",
        retryable=False,
    )


def classify_tool_error(exc: BaseException, tool_name: str) -> Classified:
    """把工具的异常分类成一条具体的错误。

    ``tool_name`` 进文案：三个工具的失败原因完全不同，说清楚是哪个工具
    挂了，用户才知道该检查哪个服务。

    ## 为什么按 Tavily 的异常类判，而不是按状态码

    Tavily SDK 的错误类全是裸 ``Exception`` 子类，**不带 ``status_code``**
    （见 ``tavily/errors.py``）。只看状态码的话，它抛的每一个错都会掉进
    兜底分支，一律报成「工具内部出错，请不要重复调用它」——key 无效、
    限流、超时全部一样，处置方式全错。
    """
    if isinstance(exc, RetrievalNoMatchError):
        return _retrieval_no_match_classified()

    if isinstance(exc, RetrievalNotEvaluatedError):
        return _retrieval_not_evaluated_classified()

    if _is_not_configured(exc):
        # 文案带上具体缺哪个配置项——异常消息里已经有（"TAVILY_API_KEY
        # 未配置"）。写成通用的「未配置」会让运维去猜是哪个变量。
        return Classified(
            TOOL_NOT_CONFIGURED,
            f"工具 {tool_name} 未配置，无法调用：{_trim(str(exc), 60)}",
            preview=f"{tool_name} 未配置",
            retryable=False,
        )

    tavily_class = find_tavily_error(exc)
    if tavily_class is not None:
        return classify_tavily_error(tavily_class, tool_name)

    status = _status_code(exc)
    if status == 401:
        return Classified(
            TOOL_AUTH_FAILED,
            f"工具 {tool_name} 鉴权失败：API key 无效",
            preview=f"{tool_name} key 无效",
            retryable=False,
        )
    if status == 429:
        return Classified(
            TOOL_RATE_LIMITED,
            f"工具 {tool_name} 被限流，请稍后重试",
            preview=f"{tool_name} 被限流",
        )
    if is_timeout(exc):
        return Classified(
            TOOL_TIMEOUT,
            f"工具 {tool_name} 执行超时",
            preview=f"{tool_name} 超时",
        )

    # 网络类异常值得重试；其余一律不可重试。
    #
    # 分这一档不是为了「显得具体」，而是为了护住 agent 循环：坏工具
    # （参数错、我们自己的 bug）被反复重试，会把 MAX_TURNS 耗光、
    # token 烧光，最后什么都产不出来。所以文案必须明确说「不要重复
    # 调用」，让模型换路径或直接用已有信息作答。
    #
    # 判据是**具体的传输层异常类**，不是整个 ``OSError`` 族：
    # ``FileNotFoundError`` / ``PermissionError`` 也是 ``OSError``
    # 子类，但它们是我们自己的 bug（本地文件读不到），不是外部服务
    # 连不上，报成「请稍后重试」会让模型一直重试一个坏调用。
    if isinstance(exc, _NETWORK_ERRORS):
        return Classified(
            TOOL_UNAVAILABLE,
            f"工具 {tool_name} 暂时无法连接到外部服务。请稍后重试，或改用其他方式回答。",
            preview="外部服务不可用",
        )

    return Classified(
        TOOL_INTERNAL_ERROR,
        f"工具 {tool_name} 内部出错，本次调用没有完成。请不要重复调用它，直接基于已有信息作答。",
        preview="工具内部错误",
        retryable=False,
    )


# ── 兜底 ─────────────────────────────────────────────────────


def classify_unknown_error(exc: BaseException, where: str) -> Classified:
    """归不出类的异常。

    ``where`` 说明发生在哪一层（"研究流程"），写进文案让用户知道出事
    的位置。真实异常类型只进日志。

    文案里**不说「请稍后重试」**——``retryable`` 是 False，前端会同时
    渲染「不可重试」徽章，一句「请稍后重试」和它自相矛盾。这里的失败
    是我们自己的 bug，重试同样的输入只会再失败一次。

    **只打一行不带 traceback 的日志**：调用方（agent 循环、research 网关）
    已经在同一异常上打过带 ``exc_info`` 的日志，traceback 打两遍只是
    让日志翻倍。
    """
    logger.warning("%s 发生未分类异常：%s", where, type(exc).__name__)
    return Classified(
        INTERNAL_ERROR,
        f"{where}发生内部错误，请联系管理员",
        preview="内部错误",
        retryable=False,
    )


# ── 事件包装 ─────────────────────────────────────────────────


def is_llm_failure(exc: BaseException) -> bool:
    """这个异常是不是「模型服务那边的问题」。

    认三类：SDK 自己的异常基类（``AnthropicError``，覆盖鉴权、限流、
    参数错、断连）、httpx 的传输层异常（``TransportError``，覆盖没被
    SDK 包装的裸 httpx 错误）、内建的网络异常（``ConnectionError`` /
    ``TimeoutError``）。

    **不认裸 ``OSError``**：``FileNotFoundError`` / ``PermissionError``
    都是它的子类，但那是**我们自己的 bug**（路径写错、文件没权限），
    报成「模型服务暂时不可用」会把排查方向指向中转站。而
    ``ConnectionError`` / ``TimeoutError`` 本身就是 ``OSError`` 的子类，
    认它们就够了。

    沿 ``__cause__`` 链找——异常可能被上游 SDK 包过一层。
    """
    network_errors = (ConnectionError, TimeoutError)
    for item in cause_chain(exc):
        if isinstance(
            item,
            (AnthropicError, httpx.TransportError, httpx2.TransportError, *network_errors),
        ):
            return True
    return False


def error_event_for(exc: BaseException, where: str = "研究流程") -> ErrorEvent:
    """把异常翻译成给用户看的错误事件。

    ## 为什么不一律说「模型服务暂时不可用」

    那是**兜底**文案，不是诊断。它把四种完全不同的失败揉成一句话：
    流被掐断、超时、参数错、key 失效。用户看到它只知道「再试一次」，
    但「key 失效」重试一万次也没用。

    分开报，用户至少知道该等还是该改配置。

    ## 为什么要先分「是不是模型服务的错」

    agent 循环里抛的异常不只有 LLM 的：``NodeTracker`` 的断言、
    ``TurnLedger`` 的 replace、我们自己代码里的 ``AttributeError``……
    全都落在这一个 except 里。统统按「模型服务」分类的话，一句
    「模型服务暂时不可用」会盖住真正的 bug——而这正是这次改动要消灭
    的那类误导性文案。

    判据是异常类型：SDK 的 ``AnthropicError`` 与 httpx 的
    ``TransportError`` 才算模型服务的问题。其余归 internal_error。
    """
    classified = (
        classify_llm_error(exc) if is_llm_failure(exc) else classify_unknown_error(exc, where)
    )
    return ErrorEvent(
        code=classified.code,
        message=classified.message,
        retryable=classified.retryable,
    )


__all__ = [
    # 错误码常量——模块的主要公开面。日志与测试都按它们归类。
    "EMBEDDING_ARREARAGE",
    "EMBEDDING_AUTH_FAILED",
    "EMBEDDING_DIMENSION_MISMATCH",
    "EMBEDDING_NOT_CONFIGURED",
    "EMBEDDING_RATE_LIMITED",
    "EMBEDDING_UNAVAILABLE",
    "INTERNAL_ERROR",
    "LLM_AUTH_FAILED",
    "LLM_BAD_REQUEST",
    "LLM_CONNECTION_FAILED",
    "LLM_CONTENT_FILTERED",
    "LLM_NOT_CONFIGURED",
    "LLM_OVERLOADED",
    "LLM_PERMISSION_DENIED",
    "LLM_QUOTA_EXHAUSTED",
    "LLM_RATE_LIMITED",
    "LLM_SERVER_ERROR",
    "LLM_STREAM_INTERRUPTED",
    "LLM_TIMEOUT",
    "LLM_UNAVAILABLE",
    "RETRIEVAL_NOT_EVALUATED",
    "RETRIEVAL_NO_MATCH",
    "Classified",
    "cause_chain",
    "classify_embedding_error",
    "classify_llm_error",
    "classify_tool_error",
    "classify_unknown_error",
    "error_event_for",
    "is_llm_failure",
    "retrieval_no_match",
    "retrieval_not_evaluated",
]
