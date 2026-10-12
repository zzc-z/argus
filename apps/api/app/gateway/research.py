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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.gateway.deps import CurrentUser
from app.schemas.research import AskRequest
from app.services.agent import run_agent
from app.services.llm import LLMNotConfiguredError, get_anthropic_client
from app.services.stream import ErrorEvent, encode_frame
from app.services.vectorstore import get_vector_engine

router = APIRouter(prefix="/api/v1/research", tags=["research"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

# 并发上限。SSE 是长连接，一个研究请求要跑 30-60 秒；不设上限的话
# 几十个并发就能把连接池和上游额度吃满，而每个请求其实只占一个协程。
MAX_CONCURRENT_STREAMS = 4

logger = logging.getLogger(__name__)

# 每开一扇门就 +1，关门时 -1。用 Semaphore 而不是裸计数器，是因为它
# 在并发释放时不会丢计数，而「先 +1 再判断」的写法在竞争下会超发。
_slots = asyncio.Semaphore(MAX_CONCURRENT_STREAMS)


@router.post("/ask", summary="提问并流式返回研究过程")
async def ask(
    payload: AskRequest, user: CurrentUser, db: DbSession
) -> StreamingResponse:
    """发起一次研究，返回 SSE 事件流。

    事件类别见 ``app/services/stream.py``：node / delta / tool_call /
    reference / done / error。每帧是 ``data: {json}\\n\\n`` 单行 envelope，
    前端 ``split("\\n\\n")`` + ``JSON.parse`` 即可统一解析。
    """
    _reject_if_full()
    _reject_if_llm_unconfigured()

    return StreamingResponse(
        _stream(payload.question, user.id, db),
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


async def _stream(question: str, user_id: int, db: AsyncSession) -> AsyncIterator[bytes]:
    """把 agent 事件编码成 SSE 帧。

    ## 端点注入的 session 在流期间是可用的（实测结论）

    第一版这里自己开 session，理由是「FastAPI 的 yield 依赖在
    ``await response(...)`` 之前就关了」。**那个前提是错的**，实测推翻了它：

        dep OPEN → gen yield0 query=1 → yield1 query=1 → yield2 query=1
        → gen done → dep CLOSED → CLIENT 收到全部 chunk

    三次真实 SQL 查询在生成器里都跑通了，依赖在生成器结束**之后**才关闭。

    错在哪：``fastapi/routing.py:147-152`` 有两层 ``AsyncExitStack``，
    内层 ``function_stack`` 确实在 ``await response(...)`` 之前出栈——
    但 ``Depends()`` 默认 ``scope="request"``，依赖挂的是**外层**
    ``request_stack``（``dependencies/utils.py:664-667``），外层在响应
    发完才关。只有显式写 ``Depends(scope="function")`` 才会早关。

    FastAPI 0.118.0 把「yield 依赖提前关闭」当 bug revert 了（release notes
    原话：*"if you had a database session in a dependency with yield, the
    StreamingResponse would not be able to use that session while streaming"*）。
    本项目装的是 0.142.2。

    所以这里**必须用端点注入的 db**——它走了 ``Depends()`` 求解，
    测试里的 ``dependency_overrides`` 才生效。自己 ``SessionLocal()`` 或
    ``asynccontextmanager(get_session)()`` 都是普通函数调用，绕过求解器，
    测试会连到开发库 ``argus.db``（conftest 的首要约定就是测试绝不碰它）。

    ## 已知的连接占用

    db 在整个 agent 循环期间持有（30-60 秒），即 pin 住连接池一个连接。
    这是 ``scope="request"`` 的既定行为，不是 bug。``MAX_CONCURRENT_STREAMS``
    就是它的兜底——见 WORKLOG「已知缺口」。

    所有异常都转成 ``ErrorEvent``：连接一旦以 200 建立，前端只能靠事件
    判断成败。裸断连接会让前端永远转圈。

    ``get_vector_engine()`` 刻意放在 try **里面**：它是懒初始化的单例，
    首次调用才会建连接，而 sqlite-vec 扩展加载失败 / 数据库文件不可写
    都在这一步抛。放在 try 外的话，那类部署问题会变成裸 500——
    前端连 ``error`` 事件都收不到，只能一直转圈。
    """
    async with _slots:
        try:
            vec_engine = get_vector_engine()
            async for event in run_agent(
                question, user_id=user_id, db=db, vec_engine=vec_engine
            ):
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
