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

## 生成与连接解耦（2026-11-01）

以前 agent 直接跑在 ``StreamingResponse`` 的生成器里，**客户端一断开
生成就停**——用户刷新页面、切到别的页面再回来，只看到一片空白，
已经烧掉的 token 白烧。

现在生成跑在**后台任务**里，事件先进 ``services.runs`` 的注册表，
HTTP 连接只是「订阅者」：

- ``POST /ask`` 建 run、启后台任务、订阅并转发
- ``GET /runs/{run_id}/stream`` 只订阅——用来在刷新/切页后接回那一轮

这与主流项目（ChatGPT / Claude / Perplexity）一致：会话在服务端持有，
客户端是渲染器。
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session, get_sessionmaker
from app.gateway.deps import CurrentUser
from app.schemas.research import AskRequest
from app.services.agent import run_agent
from app.services.credentials import resolve_credentials
from app.services.errors import classify_llm_error, classify_unknown_error
from app.services.llm import LLMNotConfiguredError, get_anthropic_client
from app.services.runs import Run, get_run_registry, subscribe_run
from app.services.stream import AgentEvent, DoneEvent, ErrorEvent, RunEvent, encode_frame
from app.services.tasks import spawn
from app.services.vectorstore import get_vector_engine

router = APIRouter(prefix="/api/v1/research", tags=["research"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

# 后台任务用的 session 工厂。做成依赖而不是直接调 ``SessionLocal()``——
# 直接调是普通函数调用，``dependency_overrides`` 对它无效，测试里后台
# 任务会静悄悄连上开发库 argus.db。
SessionMakerDep = Annotated["async_sessionmaker[AsyncSession]", Depends(get_sessionmaker)]

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
#
# 闸门拦的是「同时开多少个**研究**」，与谁在读流无关：生成已经移到后台
# 任务，但一个研究仍然占一条 DB 连接（30-60 秒）并烧上游额度。
MAX_CONCURRENT_STREAMS = 4

# 报告交付（done）之前，连续这么久没有任何新事件就判定卡住，报超时收尾。
#
# 单次模型调用在 SDK 层最长要等 120s × 3 次（含重试），再叠上断流整轮重发，
# 中转站挂住时用户会干等十几分钟——页面一直「运行中」却不报错。
# 取 180s：正常的一轮（含思考、联网搜索）远短于此，又比单次 120s 超时长，
# 能让上游自己的超时错误先报出来。
RUN_IDLE_TIMEOUT_SECONDS = 180.0

logger = logging.getLogger(__name__)

_slots = asyncio.Semaphore(MAX_CONCURRENT_STREAMS)

# SSE 响应头。关掉反向代理的缓冲——不关的话事件会被攒成一坨在响应结束
# 时一次性吐出，前端完全看不到流式效果。
#
# no-store 而非 no-cache：no-cache 是「可缓存但需重新验证」，对 SSE 没有
# 意义且允许中间层存一份。no-transform 阻止 gzip 之类变换，避免缓冲
# 重新被引入。
_SSE_HEADERS = {
    "X-Accel-Buffering": "no",
    "Cache-Control": "no-store, no-transform",
}


@router.post("/ask", summary="提问并流式返回研究过程")
async def ask(
    payload: AskRequest,
    user: CurrentUser,
    db: DbSession,
    vec_engine: VecEngineDep,
    session_maker: SessionMakerDep,
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
    # release 在**研究跑完之后**（见下面的 `task.add_done_callback`）：
    # 槽位跟着研究本身，不跟着 HTTP 连接——客户端断开时研究还在跑，
    # 槽位不能提前还。
    if not await _try_acquire_slot():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "当前并发查询已满，请稍后重试",
            headers={"Retry-After": "5"},
        )
    await _reject_if_llm_unconfigured(user.id, db)

    registry = get_run_registry()
    # 提新问题时取消**上一轮**。生成现在跑在服务端，不取消的话它会继续烧
    # token（一次研究几十万）并占着并发槽位（闸门只有 4 个）。
    # 旧行为（生成绑在连接上）本来就是「重问 = 上一轮停」。
    #
    # **按 id 精确取消**，不按「用户最近一轮」：用户可能开着两个标签页
    # 各跑一个研究，按「最近一轮」会把另一个标签页的生成掐掉。前端把
    # 自己那一轮的 id 传上来（URL 里的那个），服务端只取消它。
    if payload.replace_run_id:
        await registry.cancel_by_id(payload.replace_run_id, user.id)

    run = registry.create(user_id=user.id, question=payload.question)

    # 槽位状态——LLM 阶段结束与任务结束都会尝试还，只能还一次。
    slot = _SlotState()

    # 后台任务自己开 session——请求的 db session 随响应结束就关了，
    # 后台任务跑到一半 session 已关，错误还很难看出来。
    task = spawn(
        _drive_run(
            run,
            question=payload.question,
            user_id=user.id,
            vec_engine=vec_engine,
            session_maker=session_maker,
            slot=slot,
        )
    )
    # 登记任务，取消时才能打断它。
    run.attach_task(task)
    # 槽位在任务**结束**时还——用 done_callback 而不是任务体里的 finally。
    #
    # 为什么不用 finally：任务在开始执行前就被取消（create_task 之后
    # 立刻 cancel）时，协程体从未运行，finally **不会执行**——槽位就
    # 永久泄漏了。几次这样的泄漏之后全部请求 503，而症状指向「并发
    # 闸门坏了」，真正原因在几十行外。
    #
    # done_callback 覆盖**所有**结束路径：正常跑完、抛异常、被取消。
    #
    # 但「任务结束」太晚了：引用校验（critic）最长 6 分钟，
    # 期间没有一次 LLM 调用在跑，槽位却被占着——4 个并发全卡在校验上时，
    # 新请求全部 503。所以 done_callback 只在**槽位还没被提前还过**时释放。
    task.add_done_callback(lambda _t: _release_slot_once(slot))

    return StreamingResponse(
        _forward(run, first=RunEvent(run_id=run.id, question=run.question)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/runs/{run_id}/stream", summary="接回一个正在进行或已完成的研究")
async def stream_run(run_id: str, user: CurrentUser) -> StreamingResponse:
    """订阅一个 run 的事件流。

    刷新页面或切到别的页面再回来时，前端拿它保存的 ``run_id`` 调这里，
    把那一轮从头重放一遍。**不需要重新问一次**——已烧的 token 不白烧。

    鉴权：run 属于当前用户才给订阅。别人的 run 一律 404（不区分
    「不存在」与「不是你的」——那会泄露 run_id 的存在性）。
    """
    run = get_run_registry().get(run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这次研究已不存在")

    return StreamingResponse(
        _forward(run, first=RunEvent(run_id=run.id, question=run.question)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/runs/latest", summary="当前用户最近的一轮研究")
async def latest_run(user: CurrentUser) -> dict[str, str]:
    """取当前用户最近的一轮研究（只要 id 与问题，不给事件流）。

    ## 为什么需要这个端点

    run id 在 **URL** 上（主流项目的做法）。但用户从别的页面直接点进
    ``/explore``（地址栏里没有 run id），那一轮就接不回来了 —— 他会看到
    一片空白，以为自己刚才白问了。

    这个端点给「无 id 时的回退」：前端在 ``/explore``（没 id）时问一次
    「我最近一轮是什么」，拿到 id 就把 URL 补上（``replaceState``），
    然后照常接回。

    ## 只给 id 不给内容

    内容要走 SSE 重放（那才是一致的那一份）。这个端点只是**找到它**。

    404 = 没有过 run（或者都过期了）。前端据此停在空态。
    """
    run = get_run_registry().latest_for_user(user.id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "没有进行中的研究")
    return {"run_id": run.id, "question": run.question}


@router.delete("/runs/{run_id}", summary="取消一轮正在进行的研究")
async def cancel_run(run_id: str, user: CurrentUser) -> dict[str, bool]:
    """取消一轮正在跑的研究。

    ## 为什么需要

    「新建会话」时，上一轮若还在跑，它会继续烧 token、继续占着并发槽位
    （闸门只有 4 个）。而生成现在跑在服务端，**客户端断开不会终止它**
    ——所以必须显式取消。

    ## 取消不是失败

    取消时已生成的那半截正文会**落盘**（标 ``truncated=True``），
    用户在历史报告里仍能看到它。主流项目也是这个行为（ChatGPT 的停止
    按钮：停掉的那条消息仍在对话里）。

    200 = 取消了；404 = 那一轮不存在、不是你的、或已经跑完了（没有可停的）。
    """
    cancelled = await get_run_registry().cancel_by_id(run_id, user.id)
    if not cancelled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这次研究已结束或不存在")
    return {"cancelled": True}


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
    """
    if _slots.locked():
        return False
    await _slots.acquire()  # 必然走快路径立即返回
    return True


class _SlotState:
    """一次研究占用的槽位，保证**只还一次**。

    ## 为什么需要它

    槽位有两个释放点：

    1. **LLM 阶段结束**（进入 critic 校验前）——提前还，校验那 6 分钟
       不占着闸门
    2. **任务结束**（``done_callback``）——兜底，覆盖取消、崩溃、
       以及 1 没走到的情况

    两个点都会触发时，重复 release 会让 Semaphore 的计数虚高
    （``_value`` 变大），闸门形同虚设——并发限制彻底失效。

    所以这里用一个标志位保证**只还一次**。
    """

    __slots__ = ("_released",)

    def __init__(self) -> None:
        self._released = False

    def release(self) -> None:
        """还槽位。已还过则什么都不做。"""
        if self._released:
            return
        self._released = True
        _slots.release()

    @property
    def released(self) -> bool:
        return self._released


def _release_slot_once(state: _SlotState) -> None:
    """``done_callback`` 用的包装（回调签名要求单参数）。"""
    state.release()


async def _reject_if_llm_unconfigured(user_id: int, db: AsyncSession) -> None:
    """模型未配置时直接拒，同样要赶在开流之前。

    注意它跑在 ``_try_acquire_slot()`` **之后**：抛异常时槽位已经被占了，
    必须释放，否则每次「模型未配置」都会永久扣掉一个槽位。

    **用 400 而不是 503**：503 的语义是「服务暂时不可用，稍后重试」，
    而「模型未配置」是部署问题——重试一万次也一样，必须去改配置。
    两者混在同一个状态码里，前端就没法区分「等一会儿」和「去改配置」。

    **判的是「这个用户」有没有配 key**——用户在设置页可以配自己的
    API key（见 ``app/services/credentials.py``）。查的是他的配置，
    不是部署的默认配置：别人配了不代表他能用。

    ## 槽位必须在**任何**异常下都还回去

    ``resolve_credentials`` 是一次 DB 查询，它可能失败（库被锁、连接断了）。
    那个异常若直接冒出去，槽位就永久漏掉——之后**每个**研究请求都
    503「并发已满」，而实际上一个研究都没在跑。

    所以两条失败路径都要还槽位：``LLMNotConfiguredError``（模型没配）
    与「凭据解析本身炸了」（DB 错误）。后者用 ``except Exception``
    兜住——它不改变异常的类型，只是保证槽位还回去。
    """
    try:
        credentials = await resolve_credentials(db, user_id)
        get_anthropic_client(credentials)
    except LLMNotConfiguredError as exc:
        _slots.release()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "模型服务未配置：请在设置页配置 ANTHROPIC_API_KEY",
        ) from exc
    except Exception:
        # 凭据解析失败（DB 错误等）——槽位必须还，否则整个研究闸门
        # 永久卡死（原异常照原样冒出去，不该被这个 400 掩盖）。
        _slots.release()
        raise


async def _drive_run(
    run: Run,
    *,
    question: str,
    user_id: int,
    vec_engine: AsyncEngine,
    session_maker: SessionMakerDep,
    slot: _SlotState,
) -> None:
    """后台跑一次研究，把事件推进 run 的缓冲里。

    ## 为什么自己开 session

    端点注入的 db session 是 ``scope="request"``——它在响应发完后才关闭
    （FastAPI 0.118.0 起 yield 依赖不再提前关闭）。但后台任务的生命周期
    **可能超过响应**（响应早就发完了，任务还在跑），依赖的关闭时机由框架
    决定，我们控制不了。

    所以后台任务自己开一个 session——工厂由依赖注入，测试能换成测试库的。

    ## 为什么传 ``slot``

    LLM 阶段结束（进入 critic 校验前）就还槽位——校验最长 6 分钟，
    占着闸门会让 4 个并发全卡死、新请求全 503。
    任务真正结束时 ``done_callback`` 再兜底还一次，但 ``_SlotState``
    保证只还一次。
    """
    try:
        async with session_maker() as bg_db:
            try:
                try:
                    await _pump_events(
                        run,
                        run_agent(
                            question,
                            user_id=user_id,
                            db=bg_db,
                            vec_engine=vec_engine,
                            # 公开来源要另开短事务落库——主事务的 SQLite 写锁
                            # 不能持有整轮研究（30-60 秒），期间会阻塞并发研究与
                            # 用户的资料上传。
                            session_maker=session_maker,
                            on_llm_done=slot.release,
                        ),
                    )
                except _IdleTimeoutError as exc:
                    logger.warning(
                        "研究连续 %.0f 秒没有新事件，判定卡住并中止", RUN_IDLE_TIMEOUT_SECONDS
                    )
                    classified = classify_llm_error(exc.__cause__ or exc)
                    await run.publish(
                        ErrorEvent(
                            code=classified.code,
                            message=classified.message,
                            retryable=classified.retryable,
                        )
                    )
            except Exception as exc:
                # 兜底的兜底：agent 内部已经把能归类的异常转成 ErrorEvent 了，
                # 能走到这里说明是意料之外的 bug。照旧转成事件，绝不让订阅者
                # 永远等下去。
                logger.warning("研究流发生未预期异常", exc_info=exc)
                classified = classify_unknown_error(exc, "研究流程")
                await run.publish(
                    ErrorEvent(
                        code=classified.code,
                        message=classified.message,
                        retryable=classified.retryable,
                    )
                )
    finally:
        # 无论怎么收尾都要关闭 run——订阅者靠结束标记判断流结束。
        # 漏掉这一步订阅者会一直挂着（HTTP 连接不关）。
        #
        # 槽位**不在这里还**——见端点里 ``task.add_done_callback`` 的
        # 说明：任务在开始执行前就被取消时，这段 finally 根本不执行。
        await run.close()


class _IdleTimeoutError(Exception):
    """报告交付前连续 ``RUN_IDLE_TIMEOUT_SECONDS`` 没有新事件。"""


async def _pump_events(run: Run, events: AsyncIterator[AgentEvent]) -> None:
    """把 agent 的事件逐个推进 run；报告交付前空闲太久就中止。

    每来一个事件就把截止时间往后推；收到 done 之后不再计时——那之后只剩
    引用校验，报告已经交给用户了。

    超时由 ``asyncio.timeout`` 取消 agent，agent 的取消分支照常落盘、
    发 done，然后这里转成 :class:`_IdleTimeoutError`，与 agent 自己抛的
    ``TimeoutError`` 区分开。
    """
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(RUN_IDLE_TIMEOUT_SECONDS) as deadline:
            async for event in events:
                await run.publish(event)
                if deadline.expired():
                    continue
                if isinstance(event, DoneEvent):
                    deadline.reschedule(None)
                else:
                    deadline.reschedule(loop.time() + RUN_IDLE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        if not deadline.expired():
            raise
        raise _IdleTimeoutError from exc


async def _forward(run: Run, *, first: RunEvent | None = None) -> AsyncIterator[bytes]:
    """把 run 的事件编码成 SSE 帧。

    **订阅者断开不影响生成**——事件已经进了 run 的缓冲，重连时能补上。

    ``first`` 是插在最前面的那一帧（run id）。重连时也发——前端拿到
    重复的 run id 是幂等的，不发反而要让前端处理「这次没有 run id」
    的分支。
    """
    if first is not None:
        yield encode_frame(first)
    async for event in subscribe_run(run):
        yield encode_frame(event)
