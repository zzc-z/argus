"""Tavily 相关的错误码与异常分类。

## 为什么单独一个模块

Tavily 的错误形态是**它自己**的事：它的异常类全是裸 ``Exception`` 子类、
不带 ``status_code``，与其它 HTTP 客户端的约定完全不同。把这层知识塞进
通用的 ``errors.py``，那个文件就同时装着「怎么分类」与「Tavily 怎么
报错」两件事——换掉 Tavily 时要动的地方也多一处。

Tavily 是可替换的外部服务（换供应商只改 ``tools.py`` 的实现），它
的异常知识就该跟着它走。

依赖是单向的：

    errors_base  ←  errors_tavily  ←  errors

## 判据

异常类型，不看状态码。类名与含义的对应关系读 ``tavily/tavily.py`` 的
raise 点确认过：``InvalidAPIKeyError`` = 401，``UsageLimitExceededError``
= 429，``ForbiddenError`` = 403，``BadRequestError`` = 400。
"""

from __future__ import annotations

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

from app.services.errors_base import (
    TOOL_AUTH_FAILED,
    TOOL_BAD_REQUEST,
    TOOL_FORBIDDEN,
    TOOL_INTERNAL_ERROR,
    TOOL_RATE_LIMITED,
    TOOL_TIMEOUT,
    Classified,
    cause_chain,
)

# Tavily 的全部错误类。分类时按 isinstance 逐个认。
_TAVILY_ERRORS = (
    TavilyInvalidAPIKeyError,
    TavilyUsageLimitExceededError,
    TavilyForbiddenError,
    TavilyBadRequestError,
    TavilyTimeoutError,
)


def find_tavily_error(exc: BaseException) -> BaseException | None:
    """找出异常链上的 Tavily 错误类。认不出来返回 None。

    沿 cause 链找：Tavily SDK 的错误可能被我们的代码包过一层。
    """
    for item in cause_chain(exc):
        if isinstance(item, _TAVILY_ERRORS):
            tavily_exc: BaseException = item
            return tavily_exc
    return None


def classify_tavily_error(exc: BaseException, tool_name: str) -> Classified:
    """Tavily 的错误 → 分类。

    ## 为什么必须认这些具体类

    Tavily SDK 的错误类全是裸 ``Exception`` 子类，**不带 ``status_code``**
    （见 ``tavily/errors.py``）。所以按状态码分的 401/429 两档在 Tavily
    路径上永远不命中——所有失败都会落到「内部错误」，而「内部错误」的
    文案是「不要重复调用它」：key 无效时让模型别重试，正好和「该换
    key」的处置相反。
    """
    if isinstance(exc, TavilyInvalidAPIKeyError):
        return Classified(
            TOOL_AUTH_FAILED,
            f"工具 {tool_name} 鉴权失败：API key 无效，请检查 TAVILY_API_KEY",
            preview=f"{tool_name} key 无效",
            retryable=False,
        )
    if isinstance(exc, TavilyUsageLimitExceededError):
        return Classified(
            TOOL_RATE_LIMITED,
            f"工具 {tool_name} 超出用量上限，请稍后重试",
            preview=f"{tool_name} 超出用量上限",
        )
    if isinstance(exc, TavilyForbiddenError):
        return Classified(
            TOOL_FORBIDDEN,
            f"工具 {tool_name} 被拒绝访问：当前 key 没有该接口的权限",
            preview=f"{tool_name} 无权限",
            retryable=False,
        )
    if isinstance(exc, TavilyBadRequestError):
        return Classified(
            TOOL_BAD_REQUEST,
            f"工具 {tool_name} 拒绝了这次请求，请调整参数后重试",
            preview=f"{tool_name} 请求被拒",
            retryable=False,
        )
    if isinstance(exc, TavilyTimeoutError):
        return Classified(
            TOOL_TIMEOUT,
            f"工具 {tool_name} 执行超时",
            preview=f"{tool_name} 超时",
        )
    # 走到这里说明是 Tavily 的其它异常类（KeylessUnsupportedEndpointError
    # 之类）——没有对应档位就当内部错误，让模型别再调它。
    return Classified(
        TOOL_INTERNAL_ERROR,
        f"工具 {tool_name} 内部出错，本次调用没有完成。请不要重复调用它，"
        f"直接基于已有信息作答。",
        preview="工具内部错误",
        retryable=False,
    )
