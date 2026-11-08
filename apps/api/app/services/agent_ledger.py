"""一次研究的用量与产出记账。

## 为什么独立成模块

账本被主循环、强制收尾、落盘三处读写——摊平成局部变量时，读到的值
到底是「哪一次请求累加的」只有读代码的人知道。收进一个对象后，
「谁改了什么」一眼可见。

## 为什么 frozen

每个更新方法都返回**新的**账本对象，调用方重新绑定。可变版本里
``ledger.truncated = True`` 在主循环内有 3 处分散的写入点，读代码时得
先找出全部写点才知道这个值被谁设成什么。

代价是调用点要 ``ledger = ledger.record(result)`` 而不是 ``ledger.record(result)``。
值得：那行多出来的赋值本身就是「这里更新了账本」的显式标记，
而可变版本里的静默 mutation 恰恰是 AGENTS.md 要防的东西。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Self

from app.services.agent_turn import TurnResult
from app.services.stream import DoneEvent


@dataclass(slots=True)
class _FinalizeOut:
    """强制收尾那一步的回传通道。

    见 ``_finalize`` 的说明：生成器只有一个 yield 通道，而这里要同时交回
    「正文整段」与「新账本」两样东西。
    """

    ledger: TurnLedger
    text: str = ""


@dataclass(frozen=True, slots=True)
class TurnLedger:
    """一次研究的用量与产出记账。

    把这些散落的局部变量收进一个对象，是因为它们有**跨方法**的读者：
    ``turns`` / token 数在异常路径上要读，已经在 try 块外赋过值；
    ``produced_text`` 在循环外的收尾分支要读。摊平成局部变量时，
    读到的值到底是「哪一次请求累加的」只有读代码的人知道。

    ## 为什么 frozen

    每个更新方法都返回**新的**账本对象，调用方重新绑定。这样「谁改了什么」
    一眼可见——可变版本里 ``ledger.truncated = True`` 在主循环内有 3 处分散的
    写入点，读代码时得先找出全部写点才知道这个值被谁设成什么。

    代价是调用点要 ``ledger = ledger.record(result)`` 而不是 ``ledger.record(result)``。
    值得：那行多出来的赋值本身就是「这里更新了账本」的显式标记，
    而可变版本里的静默 mutation 恰恰是 AGENTS.md 要防的东西。
    """

    session_id: str
    started_at: float
    user_id: int
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    truncated: bool = False
    produced_text: bool = False
    report_id: int | None = None

    def begin_turn(self) -> Self:
        """占用一轮额度，返回新账本。

        计数在**请求发出之前**递增：崩溃的那一轮同样烧掉了额度，
        少算一轮就等于告诉用量统计「这次几乎没花钱」，重试时
        也就看不到上次真正的开销。
        """
        return replace(self, turns=self.turns + 1)

    def record(self, result: TurnResult) -> Self:
        """累加一轮的 token 用量，并记住是否产出了正文。"""
        return replace(
            self,
            input_tokens=self.input_tokens + result.input_tokens,
            output_tokens=self.output_tokens + result.output_tokens,
            produced_text=self.produced_text or bool(result.text),
        )

    def mark_truncated(self) -> Self:
        return replace(self, truncated=True)

    def record_stage_usage(self, input_tokens: int, output_tokens: int) -> Self:
        """记一次**非主循环**调用的用量（Supervisor / Analyst）。

        这两个节点各自调了一次模型，不记的话用量统计会系统性偏低——
        用户按账估算成本会算错，而「账算不准」这种功能可以长期完全不工作
        而没人发现。
        """
        if input_tokens <= 0 and output_tokens <= 0:
            return self
        return replace(
            self,
            input_tokens=self.input_tokens + input_tokens,
            output_tokens=self.output_tokens + output_tokens,
        )

    def with_report_id(self, report_id: int | None) -> Self:
        """记下刚落盘的报告 id。None = 落盘失败或没落（db 为 None）。"""
        return replace(self, report_id=report_id)

    def done(self) -> DoneEvent:
        return DoneEvent(
            session_id=self.session_id,
            elapsed_ms=int((time.monotonic() - self.started_at) * 1000),
            turns=self.turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            truncated=self.truncated,
            report_id=self.report_id,
        )
