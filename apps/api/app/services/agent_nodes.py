"""DAG 的节点定义与生命周期跟踪。

## 为什么独立成模块

``agent.py`` 的主循环很长（项目规范：单文件 ≤800 行），而节点这一块
**自成一体**：它只管「哪个节点 active、各自跑了多久、产出了什么」，
不碰模型调用、不碰工具、不碰落盘。

## 硬不变式：任一时刻只有一个 active

前端 ``AgentDAG`` 用 ``nodes.findIndex(n => n.lifecycle === 'active')``
算高亮轨道的位置，两个 active 会让它算错位置。由 :class:`NodeTracker`
的断言保证——把它变成后端显式失败，比让前端静默渲染错位置好排查得多。
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum

from app.services.stream import NodeEvent

logger = logging.getLogger(__name__)


class Stage(StrEnum):
    """前端约定的 5 个节点 id。

    五个节点**都真干活**（2026-11-04 起）：

    - ``SUPERVISOR`` 拆解用户问题成检索子任务（``services/stages.py``）
    - ``RESEARCHER`` 检索私有资料与公开来源
    - ``ANALYST`` 交叉核对证据（找矛盾 + 综合结论）
    - ``WRITER`` 撰写正文
    - ``CRITIC`` 校验引用是否被原文支撑

    早先只有 ``RESEARCHER`` 与 ``WRITER`` 真调 LLM，其余是时序占位——
    让前端的 DAG 有完整的推进过程可演。那种「占了位但没干活」的节点
    在 DAG 上显示 0.0s，用户分不清「它很快」与「它什么都没做」。
    """

    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    CRITIC = "critic"


NODE_DETAILS: dict[Stage, str] = {
    Stage.SUPERVISOR: "正在拆解问题意图",
    Stage.RESEARCHER: "正在检索与取证",
    Stage.ANALYST: "正在交叉核对证据",
    Stage.WRITER: "正在撰写研究报告",
    Stage.CRITIC: "正在校验引用",
}


class NodeTracker:
    """节点生命周期的单写者。

    断言「同一时刻只有一个 active」不是装饰：前端 AgentDAG 用
    ``nodes.findIndex(n => n.lifecycle === 'active')`` 算高亮轨道的
    位置，两个 active 会让它算错。把它变成后端显式失败，比让前端静默
    渲染错位置好排查得多。
    """

    def __init__(self) -> None:
        self._active: Stage | None = None
        self._started_at = 0.0
        # 每个节点累计消耗的毫秒数。
        #
        # **为什么要有累计**：researcher / writer 会被激活多次——每轮
        # 工具调用切回 researcher、每次正文重发切回 writer。只算「最后
        # 一段」的话，用户看到的是「检索 0.0s」而实际检索了几十秒。
        #
        # 累计值在这里算而不是前端算：前端只能看到帧，看不到「这个节点
        # 一共活跃了多久」——它只知道最后一次的帧。
        self._accumulated_ms: dict[Stage, int] = {}
        # 每个节点的产出摘要，完成时随帧带出。
        self._notes: dict[Stage, str] = {}

    def activate(self, stage: Stage) -> NodeEvent:
        assert self._active is None, f"节点 {self._active} 尚未结束，不能激活 {stage}"
        self._active = stage
        self._started_at = time.monotonic()
        # active 帧带上**本段开始前的累计耗时**。
        #
        # 前端用它当实时秒数的基线：researcher 分多段跑时，用户看到的
        # 应该是「11.0s → 12.0s → 16.2s」这样**连续增长**的数字，
        # 而不是每段都从 0 开始跳（0 → 10 → 0 → 1 → 0 → 5）。
        #
        # 不带基线的话，前端只知道「这一段从什么时候开始」，
        # 算不出「这个节点一共跑了多久」——那个数只在 completed 帧里。
        return NodeEvent(
            node_id=stage.value,
            lifecycle="active",
            detail=NODE_DETAILS[stage],
            elapsed_ms=self._accumulated_ms.get(stage, 0),
        )

    def set_note(self, stage: Stage, note: str) -> None:
        """记下某个节点的产出摘要。

        在节点**仍 active** 时调用：摘要在完成帧里带出，而完成帧是
        ``complete()`` 生成的。
        """
        if note:
            self._notes[stage] = note

    def complete(self) -> NodeEvent | None:
        """结束当前 active 节点；没有 active 时返回 None。"""
        if self._active is None:
            return None
        elapsed = self._consume_elapsed(self._active)
        done = NodeEvent(
            node_id=self._active.value,
            lifecycle="completed",
            elapsed_ms=elapsed,
            note=self._notes.pop(self._active, ""),
        )
        self._active = None
        return done

    def fail(self, detail: str = "") -> NodeEvent | None:
        """把当前 active 节点标成**失败**；没有 active 时返回 None。

        ## 为什么要有 failed 而不是一律 completed

        失败路径原先也走 :meth:`complete`，于是前端的 DAG 上**每个节点都是
        打勾的「通过」**——哪怕整次研究崩了、模型服务挂了、检索全被过滤。
        用户看到的是「全部通过」，实际上一件事都没成。

        「通过」和「失败」必须能区分开，否则那张图没有信息量。
        """
        if self._active is None:
            return None
        elapsed = self._consume_elapsed(self._active)
        failed = NodeEvent(
            node_id=self._active.value,
            lifecycle="failed",
            detail=detail,
            elapsed_ms=elapsed,
            note=self._notes.pop(self._active, ""),
        )
        self._active = None
        return failed

    def _consume_elapsed(self, stage: Stage) -> int:
        """结算某节点这一段的耗时，并累加到该节点的总耗时上。"""
        segment = int((time.monotonic() - self._started_at) * 1000)
        total = self._accumulated_ms.get(stage, 0) + segment
        self._accumulated_ms[stage] = total
        return total

    def switch(self, stage: Stage) -> list[NodeEvent]:
        """从当前节点切到下一个：先关旧的，再开新的。"""
        events: list[NodeEvent] = []
        closing = self.complete()
        if closing is not None:
            events.append(closing)
        events.append(self.activate(stage))
        return events


def _close(tracker: NodeTracker) -> list[NodeEvent]:
    """关掉当前 active 节点；本来就没有 active 时给空列表。

    单独抽出来是因为这个「可能有值、可能没有」的两行模式在主循环里
    出现过四次，每次都要 ``if ... is not None: yield ...``。
    """
    closing = tracker.complete()
    return [] if closing is None else [closing]


def _fail(tracker: NodeTracker, detail: str = "") -> list[NodeEvent]:
    """把当前 active 节点标成失败（而不是「完成」）。

    失败路径必须用它，不能用 :func:`_close`——否则前端 DAG 上每个节点
    都是打勾的「通过」，哪怕整次研究什么都没产出。
    """
    failed = tracker.fail(detail)
    return [] if failed is None else [failed]
