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
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import get_session
from app.gateway.deps import CurrentUser
from app.schemas.research import AskRequest
from app.services.agent import run_agent
from app.services.errors import classify_unknown_error
from app.services.llm import LLMNotConfiguredError, get_anthropic_client
from app.services.stream import ErrorEvent, encode_frame
from app.services.vectorstore import get_vector_engine

router = APIRouter(prefix="/api/v1/research", tags=["research"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

# 向量 engine 必须走 Depends 注入，不能在函数体里直接调 get_vector_engine()。
#
# dependency_overrides 只对依赖**求解器**生效：它把「声明过的依赖」映射到
# 替代实现，而模块级函数直接调用是普通函数调用，覆盖表根本不会被查。
# Day 11 的 CR 抓过同一类问题的 get_session 版本——自己 SessionLocal() 开
# session，测试静悄悄连上开发库 argus.db 而全部测试绿灯。向量 engine 是
# 同一个坑的第二个实例：潜伏至今是因为路由测试都换成了假 agent，一旦有人
# 写一个「真实 agent + local_search」的端到端测试就会踩到。
VecEngineDep = Annotated[AsyncEngine, Depends(get_vector_engine)]

# 并发上限。SSE 是长连接，一个研究请求要跑 30-60 秒；不设上限的话
# 几十个并发就能把连接池和上游额度吃满，而每个请求其实只占一个协程。
MAX_CONCURRENT_STREAMS = 4

logger = logging.getLogger(__name__)

_slots = asyncio.Semaphore(MAX_CONCURRENT_STREAMS)


@router.post("/ask", summary="提问并流式返回研究过程")
async def ask(
    payload: AskRequest, user: CurrentUser, db: DbSession, vec_engine: VecEngineDep
) -> StreamingResponse:
    """发起一次研究，返回 SSE 事件流。

    事件类别见 ``app/services/stream.py``：node / delta / tool_call /
    reference / done / error。每帧是 ``data: {json}\\n\\n`` 单行 envelope，
    前端 ``split("\\n\\n")`` + ``JSON.parse`` 即可统一解析。
    """
    # 抢槽位与判定必须在**同一个同步块**里完成，否则是 TOCTOU：
    # 第一版先 _reject_if_full() 检查、真正 acquire 放到生成器里，
    # 中间隔着「响应开始发送」的 await。实测 10 个并发请求全部拿到 200，
    # 503 一次都不触发，闸门等于不存在；而排队请求各自 pin 住一条 DB
    # 连接（CurrentUser 的 session.get() 已开事务），十几条就能打爆池子，
    # 把 /api/v1/me、OAuth、上传全部饿死。
    #
    # acquire 在开流**之前**：满了要能发 503，前端读 detail。
    # release 在生成器 **finally**：客户端提前断开时 finally 仍会执行
    # （已实测 aclose() 触发），否则槽位会逐次泄漏到全部 503。
    if not await _try_acquire_slot():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "当前并发查询已满，请稍后重试",
            headers={"Retry-After": "5"},
        )
    _reject_if_llm_unconfigured()

    return StreamingResponse(
        _stream(payload.question, user.id, db, vec_engine),
        media_type="text/event-stream",
        headers={
            # 关掉 nginx / 反向代理的缓冲。不关的话事件会被攒成一坨
            # 在响应结束时一次性吐出，前端完全看不到流式效果。
            "X-Accel-Buffering": "no",
            # no-store 而非 no-cache：no-cache 是「可缓存但需重新验证」，
            # 对 SSE 没有意义且允许中间层存一份。no-transform 阻止 gzip
            # 之类变换，避免缓冲重新被引入。
            "Cache-Control": "no-store, no-transform",
        },
    )


async def _try_acquire_slot() -> bool:
    """原子地抢一个并发槽位。满则返回 False，**绝不排队等**。

    ``asyncio.Semaphore.acquire()`` 在有槽位时走快路径——源码第一句就是
    ``if not self.locked(): self._value -= 1; return True``，**一个 await
    都没有**。在协程里调它，有槽位就是立即返回，因此「检查 + 获取」是原子的。

    满了它会去等（登记 waiter 然后 await future），而排队正是我们要避免的：
    排队请求已经通过了鉴权、已经 checkout 了一条 DB 连接，等一轮就是
    30-60 秒 × N 条连接。所以先用 ``locked()`` 挡掉，挡掉之后调用
    ``acquire()`` 必然走快路径，不存在「判断后又被抢走」的窗口——
    单协程在两次调用之间不会被打断。

    第一版是这个逻辑的镜像错误：判断在端点、获取在生成器，中间隔着
    「响应开始发送」的 await，于是 10 个并发请求全部拿到 200，503 一次
    都不触发。**判断和获取必须在同一个同步块里。**
    """
    if _slots.locked():
        return False
    await _slots.acquire()  # 必然走快路径立即返回
    return True


def _reject_if_llm_unconfigured() -> None:
    """模型未配置时直接拒，同样要赶在开流之前。

    注意它跑在 ``_try_acquire_slot()`` **之后**：抛异常时槽位已经被占了，
    必须释放，否则每次「模型未配置」都会永久扣掉一个槽位。

    **用 400 而不是 503**：503 的语义是「服务暂时不可用，稍后重试」，
    而「模型未配置」是部署问题——重试一万次也一样，必须去改配置。
    两者混在同一个状态码里，前端就没法区分「等一会儿」和「去改配置」。
    """
    try:
        get_anthropic_client()
    except LLMNotConfiguredError as exc:
        _slots.release()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "模型服务未配置：缺少 ANTHROPIC_API_KEY",
        ) from exc


async def _stream(
    question: str, user_id: int, db: AsyncSession, vec_engine: AsyncEngine
) -> AsyncIterator[bytes]:
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

    ## release 放在 finally，不放在 except 之后

    客户端提前断开时生成器收到 GeneratorExit，``except Exception`` 捕不到
    （3.8+ 起 CancelledError/GeneratorExit 都继承 BaseException）。
    只在正常路径和 ``except Exception`` 里 release 的话，断连一次漏一个
    槽，几次之后全部请求 503——而且症状指向「并发闸门坏了」，真正原因
    在几十行外的 finally 里。

    **别把 except 改成 BaseException**：那会吞掉取消信号，
    槽位和 DB 连接一起泄漏。
    """
    try:
        try:
            async for event in run_agent(
                question, user_id=user_id, db=db, vec_engine=vec_engine
            ):
                yield encode_frame(event)
        except Exception as exc:
            # 兜底的兜底：agent 内部已经把能归类的异常转成 ErrorEvent 了，
            # 能走到这里说明是意料之外的 bug。照旧转成事件，绝不让连接裸断。
            logger.warning("研究流发生未预期异常", exc_info=exc)
            classified = classify_unknown_error(exc, "研究流程")
            yield encode_frame(
                ErrorEvent(
                    code=classified.code,
                    message=classified.message,
                    retryable=classified.retryable,
                )
            )
    finally:
        _slots.release()
