"""研究提问的流式端点。

``POST /api/v1/research/ask`` 返回 ``text/event-stream``，把 agent 的研究
过程逐事件推给前端。

为什么用 POST + fetch 而不是 EventSource：EventSource 只支持 GET，
且 ``withCredentials`` 默认 false——而本端点必须带 ``argus_session``
cookie 鉴权。把问题放URL 又会撑爆访问日志和浏览器地址栏。

SSE 的一个硬约束贯穿全文件：**HTTP 状态码在第一个字节发出时就定了，
之后改不了**。所以端点把错误分成两类：

- 开流之前（鉴权、参数校验、模型未配置）→ 正常 ``HTTPException``，
  前端拿 ``resp.ok === false`` 就能读到 detail
- 开流之后（LLM 中途挂、循环崩）→ 发 ``ErrorEvent`` 再关流，
  前端要能识别这个事件并把界面收尾，否则会一直转圈
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.gateway.deps import CurrentUser
from app.schemas.research import AskRequest
from app.services.agent import run_agent
from app.services.llm import LLMNotConfiguredError, get_anthropic_client
from app.services.stream import ErrorEvent, encode_frame

router = APIRouter(prefix="/api/v1/research", tags=["research"])

# 并发上限。SSE 是长连接，一个研究请求要跑 30-60 秒；不设上限的话
# 几十个并发就能把连接池和上游额度吃满，而每个请求其实只占一个协程。
MAX_CONCURRENT_STREAMS = 4

logger = logging.getLogger(__name__)

# 每开一扇门就 +1，关门时 -1。用 Semaphore 而不是裸计数器，是因为它
# 在并发释放时不会丢计数，而「先 +1 再判断」的写法在竞争下会超发。
_slots = asyncio.Semaphore(MAX_CONCURRENT_STREAMS)


@router.post("/ask", summary="提问并流式返回研究过程")
async def ask(payload: AskRequest, user: CurrentUser) -> StreamingResponse:
    """发起一次研究，返回 SSE 事件流。

    事件类别见 ``app/services/stream.py``：node / delta / tool_call /
    done / error。每帧是 ``data: {json}\\n\\n`` 单行 envelope，前端
    ``split("\\n\\n")`` + ``JSON.parse`` 即可统一解析。
    """
    del user  # 鉴权已在依赖里完成；SSE 端点暂不落库，用不到用户资料
    _reject_if_full()
    _reject_if_llm_unconfigured()

    return StreamingResponse(
        _stream(payload.question),
        media_type="text/event-stream",
        headers={
            # 关掉 nginx / 反向代理的缓冲。不关的话事件会被攒成一坨
            # 在响应结束时一次性吐出，前端完全看不到流式效果。
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


def _reject_if_full() -> None:
    """并发已满时直接 503，不进生成器。

    必须在开流之前判断——占了流再告诉前端「满了」，前端已经收到了 200，
    只能靠 error 事件才知道，多绕一圈。
    """
    if _slots.locked():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "当前并发查询已满，请稍后重试",
        )


def _reject_if_llm_unconfigured() -> None:
    """模型未配置时 503，同样要赶在开流之前。"""
    try:
        get_anthropic_client()
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "模型服务未配置",
        ) from exc


async def _stream(question: str) -> AsyncIterator[bytes]:
    """把 agent 事件编码成 SSE 帧。

    所有异常都转成 ``ErrorEvent``：连接一旦以 200 建立，前端只能靠事件
    判断成败。裸断连接会让前端永远转圈。
    """
    async with _slots:
        try:
            async for event in run_agent(question):
                yield encode_frame(event)
        except Exception as exc:
            # 兜底的兜底：agent 内部已经把能归类的异常转成 ErrorEvent 了，
            # 能走到这里说明是意料之外的 bug。照旧转成事件，绝不让连接裸断。
            logger.warning("研究流发生未预期异常", exc_info=exc)
            yield encode_frame(
                ErrorEvent(
                    code="internal_error",
                    message="服务内部错误",
                    retryable=False,
                )
            )
