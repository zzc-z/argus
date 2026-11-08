"""研究失败与取消时的收尾路径。

## 为什么独立成模块

``run_agent`` 的主循环已经够长了（项目规范：函数 ≤50 行），而「取消」
与「崩溃」这两条收尾路径加起来近百行——它们逻辑自洽、输入输出清晰，
拆出来正好。

## 两条路径的共同点

- **都落盘已生成的正文**——用户已经看到的半截内容是有价值的
  （主流项目也是这个行为：ChatGPT 的停止按钮之后，那条消息仍在历史里）
- **都标 ``truncated=True``**——这份报告不完整，历史列表要能区分
- **都发 done 帧**——它是唯一带 session_id 与 token 数的事件。缺了它，
  已经烧掉的 token 就成了用量统计的黑洞（而这恰恰是最需要留痕的场景）

## 两条路径的差别

- 取消：**不发 error 帧**。用户是主动停的，看到红色横幅会以为出错了
- 崩溃：发 error 帧，让前端显示失败横幅
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_ledger import TurnLedger
from app.services.agent_nodes import NodeTracker, _fail
from app.services.citation import Reference
from app.services.errors import error_event_for
from app.services.persistence import PERSIST_TIMEOUT_CRASH_SECONDS, persist_report
from app.services.stream import AgentEvent

logger = logging.getLogger(__name__)


async def _handle_cancel(
    *,
    db: AsyncSession | None,
    question: str,
    ledger: TurnLedger,
    report_body: list[str],
    current_turn_text: list[str],
    collected_refs: list[Reference],
) -> AsyncIterator[AgentEvent]:
    """取消时的收尾：落盘已生成的正文 + 发 done。

    ## 为什么这里要落盘

    用户点了「新建会话」，这一轮已经烧掉的 token 就白烧了 —— 但
    **已经生成的那半截正文是有价值的**。不落盘的话：用户点了「新建
    会话」，回头在历史报告里找不到这轮 —— 他明明看到了一半的报告。

    ## 为什么把「当前这一轮」也算进去

    ``report_body`` 攒的是**已收尾**的轮次。而取消常常发生在某一轮
    **中途**——那一轮已经流出去的正文不在 ``report_body`` 里。用户看到
    的就是它，不能因为「取消发生在这一轮中途」而丢。
    """
    logger.info("研究被取消，落盘已生成的部分")
    ledger = ledger.mark_truncated()
    pending = "".join(current_turn_text)
    content = "\n".join([*report_body, *([pending] if pending else [])])
    report_id = (
        await persist_report(
            db=db,
            question=question,
            content=content,
            ledger=ledger,
            refs=collected_refs,
            persist_timeout=PERSIST_TIMEOUT_CRASH_SECONDS,
        )
        if content.strip()
        else None
    )
    # 取消不是失败：发 done（带 report_id），不发 error。
    yield ledger.with_report_id(report_id).done()


async def _handle_crash(
    *,
    db: AsyncSession | None,
    question: str,
    ledger: TurnLedger,
    report_body: list[str],
    collected_refs: list[Reference],
    tracker: NodeTracker,
    exc: BaseException,
) -> AsyncIterator[AgentEvent]:
    """崩溃时的收尾：标失败节点 + 落盘 + 发 done + 发 error。

    ## 为什么节点标 failed 而不是 completed

    失败路径原先也走 ``complete()``，于是前端 DAG 上**每个节点都是打勾
    的「通过」**——哪怕整次研究崩了、模型服务挂了。用户看到的是「全部
    通过」，实际上一件事都没成。

    ## 为什么一个字都没产出时不能落盘

    那会写进一条空报告，前端照样渲染「查看完整报告 ↗」，点进去是空白。
    正常路径有 ``produced_text`` 守卫（见 empty_response 分支），崩溃
    路径必须同样守住。
    """
    logger.warning("agent 循环异常中止（已完成 %d 轮）", ledger.turns, exc_info=exc)
    ledger = ledger.mark_truncated()
    # 崩溃 → 当前节点标**失败**，不是「完成」。
    for event in _fail(tracker, "执行中断"):
        yield event
    report_id = (
        await persist_report(
            db=db,
            question=question,
            content="\n".join(report_body),
            ledger=ledger,
            refs=collected_refs,
            persist_timeout=PERSIST_TIMEOUT_CRASH_SECONDS,
        )
        if ledger.produced_text
        else None
    )
    yield ledger.with_report_id(report_id).done()
    yield error_event_for(exc)


__all__ = ["_handle_cancel", "_handle_crash"]
