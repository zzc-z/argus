"""错误分类的基础件：结果类型、异常链遍历、工具层的错误码。

## 为什么单独一个模块

``errors.py``（通用分类）与 ``errors_tavily.py``（Tavily 专属）都要用
``Classified`` 与 ``cause_chain``。两者放在同一个文件里就会循环导入：
``errors`` 要 import ``errors_tavily``，而 ``errors_tavily`` 要 import
``errors`` 的 ``Classified``。

把共用件抽出来，依赖就是单向的：

    errors_base  ←  errors
                ←  errors_tavily

工具层的 ``TOOL_*`` 错误码也放这里——它们描述的是「某个外部工具失败
了」，与具体供应商无关（Tavily 只是当前的联网工具）。放在
``errors_tavily.py`` 会让「换供应商」变成「改错误码所在文件」。
"""

from __future__ import annotations

# ── 工具层的错误 code ─────────────────────────────────────────
#
# 工具层的 code 全在这里：它们描述的是「某个外部工具失败了」，
# 而 Tavily 是唯一的联网工具，它的错误形态决定了这些 code 怎么分。

TOOL_AUTH_FAILED = "tool_auth_failed"
"""API key 无效。"""
TOOL_FORBIDDEN = "tool_forbidden"
"""key 有效但没这个接口的权限。"""
TOOL_BAD_REQUEST = "tool_bad_request"
"""工具自己拒绝了这次请求（参数错、查询写得不合法）。"""
TOOL_RATE_LIMITED = "tool_rate_limited"
TOOL_NOT_CONFIGURED = "tool_not_configured"
"""工具压根没配 key。与「key 无效」分开——两者的处置不同（补配置 vs 换 key），
监控按 code 聚合时也不该混在一起。"""
TOOL_TIMEOUT = "tool_timeout"
TOOL_UNAVAILABLE = "tool_unavailable"
TOOL_INTERNAL_ERROR = "tool_internal_error"
"""工具本身的问题（参数错、代码 bug）。不可重试——重试会耗尽轮次上限。"""


class RetrievalNoMatchError(Exception):
    """本地资料与问题不相关——检索有候选，但全被相关性下限挡掉了。

    分类器认这个异常类：工具层在「0 条命中」时用它把「检索无相关性」
    这一档交给分类器；它冒泡到错误路径时也会被归到同一档。

    放这里而不是 ``errors.py``：那个模块 import 了本模块，
    反过来会成环。
    """


class RetrievalNotEvaluatedError(Exception):
    """**没法**判断相关性——与 :class:`RetrievalNoMatchError` 是两回事。

    没配嵌入 key（向量路根本没跑）、或资料刚上传、摄取还在进行
    （切片已入库但索引未建）——这时候说「资料与问题不相关」是
    **事实性错误**：用户的资料可能高度相关，只是我们还没能评估。

    混成同一句话会让模型当面对用户说「您的资料与本次问题不相关」，
    而那份资料可能正是答案所在。
    """


class Classified:
    """一次分类的结果：code + 文案 + 短标签 + 是否值得重试。

    ``message`` 与 ``preview`` 分开是契约要求，不是冗余：
    ``message`` 是完整说明（可以进模型上下文、可以进错误横幅），
    ``preview`` 是几十字以内的一行摘要——前端的工具轨迹表只有一行宽，
    塞整段文案会把表格撑破。
    """

    __slots__ = ("code", "message", "preview", "retryable")

    def __init__(
        self,
        code: str,
        message: str,
        *,
        preview: str,
        retryable: bool = True,
    ) -> None:
        self.code = code
        self.message = message
        self.preview = preview
        self.retryable = retryable

    def __repr__(self) -> str:  # pragma: no cover — 调试用
        return f"Classified(code={self.code!r}, retryable={self.retryable})"


def cause_chain(exc: BaseException) -> list[BaseException]:
    """异常本身 + 整条 ``__cause__`` 链。

    ## 为什么必须走链

    业务代码普遍会把 SDK 异常包一层再抛：

        raise EmbeddingError(f"调用嵌入服务失败：{type(exc).__name__}") from exc

    包过之后，原始异常的 ``status_code`` / ``body`` / ``message`` 都只在
    ``__cause__`` 上。只看异常本身的话，欠费会掉进兜底报成「暂时不可用」。

    用 ``id()`` 集合防环——``raise X from X`` 不是合法写法，但
    ``__cause__`` 是可以手动赋值的，赋成自己也造得出环。
    """
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__
    return chain


__all__ = [
    "TOOL_AUTH_FAILED",
    "TOOL_BAD_REQUEST",
    "TOOL_FORBIDDEN",
    "TOOL_INTERNAL_ERROR",
    "TOOL_NOT_CONFIGURED",
    "TOOL_RATE_LIMITED",
    "TOOL_TIMEOUT",
    "TOOL_UNAVAILABLE",
    "Classified",
    "RetrievalNoMatchError",
    "RetrievalNotEvaluatedError",
    "cause_chain",
]
