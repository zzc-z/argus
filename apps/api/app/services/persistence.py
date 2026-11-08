"""报告落盘：把一轮研究写进 ``reports`` 与 ``report_sources``。

## 为什么独立成模块

``agent.py`` 原来就超过 800 行的上限（项目编码规范），这轮给三个节点
加真实现后更大了。落盘这一块是**自成一体**的：它只被主循环调用两次
（正常路径与崩溃路径），不依赖 agent 的循环状态，拆出来正好。

拆分的另一个好处：落盘有自己的「降级语义」（任何失败都不能把已经
流出去的正文收尾带走），单独成文件后这条规则在文件头就能讲清楚，
不用在 agent 的循环里插注释。

## 硬规则：任何失败都降级，绝不向上抛

正文已经通过 SSE 流给用户了。落盘是**附加价值**——历史报告列表里
多一条记录。让它把收尾带走等于「报告读完突然报错」，连 token 用量
都没了。而这里的失败概率比 critic 高得多：要写两张表、算引用计数。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report, ReportSource
from app.models.source import DocumentChunk
from app.services.citation import Reference, count_citation_markers

logger = logging.getLogger(__name__)

# 落盘的等待上限。比 ``MODEL_TIMEOUT_SECONDS`` 短得多：正文已经流给用户了，
# 历史报告是附加价值，卡着不放只会占住并发槽位。超时即降级。
PERSIST_TIMEOUT_SECONDS = 5.0

# 崩溃路径的落盘上限，比正常路径短得多。
#
# 正常路径上正文已经完整流给用户了，落盘慢一点用户顶多等一会儿；
# 崩溃路径上用户正盯着红色横幅等失败通知，多等 5 秒是白等——那 5 秒里
# 界面上的转圈还在转，什么新信息都没有。1 秒够本地 SQLite 写完。
PERSIST_TIMEOUT_CRASH_SECONDS = 1.0


async def persist_report(
    *,
    db: AsyncSession | None,
    question: str,
    content: str,
    ledger: LedgerLike,
    refs: Sequence[Reference],
    persist_timeout: float = PERSIST_TIMEOUT_SECONDS,
) -> int | None:
    """把这一轮的报告写进 ``reports``，返回新记录的 id。

    **任何失败都降级成「没存上」返回 None，绝不向上抛。** 与上面 critic
    取原文是同一个理由：正文已经通过 SSE 流出去了，落盘是附加价值，
    让它把收尾带走等于「报告读完突然报错」，连 token 用量都没了。
    而这里的失败概率比 critic 高得多——要写两张表、算引用计数。

    ``persist_timeout`` 让崩溃路径能用更短的上限：那条路径上用户正盯着
    红色横幅等失败通知，多等几秒是白等（见
    :data:`PERSIST_TIMEOUT_CRASH_SECONDS`）。
    """
    if db is None:
        # 无检索上下文的单测路径（``run_agent`` 的 db 形参默认 None）。
        return None

    report = Report(
        user_id=ledger.user_id,
        question=question,
        content=content,
        session_id=ledger.session_id,
        input_tokens=ledger.input_tokens,
        output_tokens=ledger.output_tokens,
        elapsed_ms=int((time.monotonic() - ledger.started_at) * 1000),
        # 落盘时带上截断标记。崩溃落盘的报告正文不完整——历史列表里
        # 要能把它和完整报告区分开。
        truncated=ledger.truncated,
    )
    try:
        # **必须设超时**：这一步卡在「最后一条 delta」与「done 帧」之间，
        # 而 `run_agent` 是被 `_stream` 的 `async for` 同步消费的，槽位
        # （`MAX_CONCURRENT_STREAMS = 4`）在 `_stream` 的 finally 里释放——
        # await 卡住则 finally 不执行，槽位被**永久**占住，之后每个
        # /research/ask 都 503。切换 Postgres 后 DB 锁等待没有默认上限，
        # 一次长事务就能把 4 个槽位全占死。
        #
        # 超时语义与其它失败一致：降级成「没存上」，正文照常交付。
        async with asyncio.timeout(persist_timeout):
            await _write(db, report, refs, content)
    except Exception:
        # 带 session_id：没有它，日志里只有一句「报告落盘失败」，而落盘
        # 失败是**静默**的（流照常结束、用户拿到完整报告），运维无法把它
        # 和某次具体请求对上——这个功能可以长期完全不工作而没人发现。
        logger.warning(
            "报告落盘失败，本次不记入历史报告",
            extra={"session_id": ledger.session_id, "user_id": ledger.user_id},
            exc_info=True,
        )
        # **失败处理本身也要有上限**。
        #
        # 落盘超时的成因往往就是「DB 卡住/被锁」——同一个坏连接上再
        # await 一次（回滚、查一次确认入库没有）会**再等一次**，而这次
        # 没有上限。而 ``yield ledger.done()`` / ``yield error_event_for(exc)``
        # 都在 :func:`persist_report` **之后**——用户永远等不到失败横幅，
        # 界面一直转圈，SSE 流挂死。
        #
        # 所以整个失败处理路径共用一个更短的上限：宁可放弃「确认是否
        # 已入库」这个附加价值，也不能让用户等不到失败通知。
        try:
            async with asyncio.timeout(persist_timeout):
                # 必须回滚再返回：session 停在 failed 状态，后续任何查询都会报
                # PendingRollbackError。回滚本身也可能抛（DB 真挂），所以再兜一层。
                try:
                    await db.rollback()
                except Exception:
                    logger.warning("报告落盘失败后回滚也失败", exc_info=True)
                return await _recover_persisted_id(db, report, ledger)
        except TimeoutError:
            logger.warning(
                "报告落盘失败后的清理也超时，放弃确认入库状态",
                extra={"session_id": ledger.session_id, "user_id": ledger.user_id},
            )
            return None
    return report.id


async def _recover_persisted_id(db: AsyncSession, report: Report, ledger: LedgerLike) -> int | None:
    """落盘失败后，确认这行到底进没进库。

    ## 为什么需要这一步

    超时取消的是 ``commit()`` 里的 await。若 COMMIT 已经到达服务端，
    取消不会撤销它——行真的在库里，但我们已经走进 except 分支。此时
    返回 None 会让前端拿不到 ``report_id``，界面上不显示「查看完整报告」，
    而历史报告列表里却多了一条。用户会以为这次没产出。

    反过来，若行没进库（flush 之后 commit 失败，事务已回滚），
    ``report.id`` 虽然有值（主键在 flush 时就分配了），但那行并不存在——
    返回它会指向一条不存在的报告。

    所以查一次，让 ``report_id`` 与库里的事实一致。
    """
    if report.id is None:
        return None
    try:
        existing = await db.get(Report, report.id)
    except Exception:
        logger.warning(
            "报告落盘失败后无法确认是否已入库",
            extra={"session_id": ledger.session_id, "user_id": ledger.user_id},
            exc_info=True,
        )
        return None
    if existing is None:
        return None
    logger.info(
        "报告落盘超时，但行已入库，按已入库处理",
        extra={"session_id": ledger.session_id, "report_id": existing.id},
    )
    return existing.id


async def _write(
    db: AsyncSession,
    report: Report,
    refs: Sequence[Reference],
    content: str,
) -> None:
    """真正执行落盘的三步。单独抽出是为了能给它套一个超时。"""
    db.add(report)
    await db.flush()
    await _record_citations(db, report.id, refs, content)
    await db.commit()


async def _record_citations(
    db: AsyncSession, report_id: int, refs: Sequence[Reference], content: str
) -> None:
    """按 chunk 聚合角标与引用次数，攒进 session 等待 commit。

    同一个 chunk 只写一行，所以复合主键是 ``(report_id, chunk_id)``。
    直接逐条 append 会撞主键约束。

    ``n`` 取该 chunk **第一次**出现时的编号：`ReferenceTable.register`
    对同一 chunk 复用原号，所以同一个 chunk 不会拿到两个不同的 n。

    ``cite_count`` 取 ``content`` 里 ``[n]`` 角标的实际出现次数，而不是
    ``refs`` 的长度——理由见下面那段注释。

    ## 为什么先查存在性

    研究跑 30-60 秒，期间用户可以在另一个标签页删掉被引用的资料，
    `document_chunks` 行随之级联消失。此时若照单插入会撞
    `report_sources.chunk_id` 的外键，**整个事务回滚——连 `reports`
    那行完整正文一起丢**，而用户已经读完了流、只是历史列表里没它。
    一条悬空引用不该让整份报告陪葬，所以这里跳过已消失的 chunk。

    读路径（``gateway/reports.py``）本来也按 inner join 过滤掉了这些，
    写路径必须与它对齐。
    """
    numbers: dict[int, int] = {}
    for ref in refs:
        # **不能按 refs 出现次数累加**：`tools.py` 的 local_search 每轮返回
        # 的是 `context.citations.all`（全量引用表快照，不是增量），所以同
        # 一个 chunk 会在每一轮都出现一次——数出来的是「这个 chunk 在几轮
        # 工具结果里出现过」，与「被引用几次」毫无关系。
        #
        # 真正的引用次数要数正文里的 [n] 角标出现几次，见 `count_markers`。
        numbers.setdefault(ref.chunk_id, ref.n)
    markers = count_citation_markers(content)
    # **只写正文里真出现过的角标**。``collected_refs`` 是全量引用表快照，
    # 模型检索到 10 个切片但正文只写了 [1] 和 [4] 时，其余 8 个从未被引用；
    # 给它们也写一行会让 sources 页的「关联报告 N 篇」虚高（那份资料在报告
    # 里根本没有角标），报告详情页也会多出 8 条 cite_count=0 的幽灵引用。
    counts = {chunk_id: markers[n] for chunk_id, n in numbers.items() if markers.get(n, 0) > 0}
    if not counts:
        return

    alive = set(
        (await db.execute(select(DocumentChunk.id).where(DocumentChunk.id.in_(list(counts)))))
        .scalars()
        .all()
    )
    dropped = [cid for cid in counts if cid not in alive]
    if dropped:
        logger.info("落盘时跳过 %d 个已被删除的切片", len(dropped))

    for chunk_id, cite_count in counts.items():
        if chunk_id not in alive:
            continue
        db.add(
            ReportSource(
                report_id=report_id,
                chunk_id=chunk_id,
                n=numbers[chunk_id],
                cite_count=cite_count,
            )
        )


class LedgerLike(Protocol):
    """落盘只需要账本上的这几个字段。

    用 Protocol 而不是直接 import ``TurnLedger``：那个类在
    ``agent_ledger.py`` 里，而 ``agent_ledger.py`` 要 import 本模块
    的东西——直接 import 会形成循环依赖。Protocol 把依赖方向反转
    （依赖倒置）。

    属性声明成**只读**（``@property``）：``TurnLedger`` 是 frozen
    dataclass，它的字段本来就只读。声明成可写的话 mypy 会报
    「Protocol member expected settable variable, got read-only」。
    """

    @property
    def user_id(self) -> int: ...

    @property
    def session_id(self) -> str: ...

    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...

    @property
    def started_at(self) -> float: ...

    @property
    def truncated(self) -> bool: ...
