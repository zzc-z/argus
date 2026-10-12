"""agent 与前端之间的事件契约：事件 DTO + 打字机切片器。

放在 services 而不是 gateway，因为这些类型是 ``agent.run_agent`` 的
**返回类型**——agent 不 import 它就没法写下去。gateway 只负责把事件
编码成 SSE 字节。

事件一律走 JSON envelope 里的 ``type`` 字段区分，不用 SSE 原生的
``event:`` 行：前端用 ``fetch`` + ``ReadableStream`` 消费，一个
``split("\\n\\n")`` + ``JSON.parse`` 就能统一解析，少一层协议。
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# ── 事件 DTO ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NodeEvent:
    """智能体节点生命周期变化。

    ``node_id`` 必须是前端约定的 5 个固定 id 之一。前端 AgentDAG 用
    ``findIndex(n => n.lifecycle === 'active')`` 算高亮轨道位置，
    因此**任一时刻只允许一个 active**——由 agent 的 NodeTracker 保证。
    """

    node_id: str
    lifecycle: str  # "active" | "completed"
    detail: str = ""
    elapsed_ms: int | None = None


@dataclass(frozen=True, slots=True)
class DeltaEvent:
    """正文增量。一小段，不是全文——前端 ``streamedText += delta.text``。"""

    node_id: str
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    """一次工具调用的开始 / 结束两段。

    分两段是因为搜索可能要好几秒，前端要能立刻显示「正在搜索」，
    搜完了再显示耗时和结果概要。
    """

    call_id: str
    phase: str  # "start" | "end"
    name: str
    tool_input: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    elapsed_ms: int = 0
    preview: str = ""


@dataclass(frozen=True, slots=True)
class ReferenceEvent:
    """引用表下发。前端拿它把正文里的 ``[n]`` 渲染成可点角标。

    为什么单独一个事件而不是塞进 ``done``：引用在正文**之前**就要到，
    否则用户读到 ``[3]`` 时还没法点击。单独一个事件让前端在收到第一条
    delta 之前就能把角标组件准备好。
    """

    references: list[dict[str, Any]]
    """见 :class:`app.services.citation.Reference`。用 dict 而不是
    dataclass 是因为 SSE 帧最终要 JSON 化，多包一层转换没意义。"""


@dataclass(frozen=True, slots=True)
class DoneEvent:
    """正常收尾。必须带 session_id 与 token 数——前端 DAG 头部要显示。"""

    session_id: str
    elapsed_ms: int
    turns: int
    input_tokens: int
    output_tokens: int
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    """开流之后的错误。

    SSE 的硬约束：HTTP 状态码在第一个字节发出时就定了，改不了。所以
    流开始后的一切失败只能靠这个事件传达，前端收到后要把 DAG 收尾，
    不能一直转圈。
    """

    code: str
    message: str
    retryable: bool = True


AgentEvent = (
    NodeEvent | DeltaEvent | ToolCallEvent | ReferenceEvent | DoneEvent | ErrorEvent
)


def encode_frame(event: AgentEvent) -> bytes:
    """把事件编码成一帧 SSE。

    ``ensure_ascii=False`` 让中文直接出 UTF-8 而不是 \\uXXXX 转义——
    前端拿到的 JSON 里就是可读中文，体积也小一半。
    """
    payload = {"type": _type_name(event), "v": asdict(event)}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _type_name(event: AgentEvent) -> str:
    """事件类型名。用类名小写而不是枚举——少一层映射。"""
    return {
        NodeEvent: "node",
        DeltaEvent: "delta",
        ToolCallEvent: "tool_call",
        ReferenceEvent: "reference",
        DoneEvent: "done",
        ErrorEvent: "error",
    }[type(event)]


# ── 打字机切片 ───────────────────────────────────────────────

# 优先切点：句末标点。这里切出来的片段一定是完整可读的短句。
BREAK_CHARS = "。！？；\n"

# 次级切点：句中标点。只在优先切点找不到时用。
SOFT_BREAK_CHARS = "，、：,;:"

CHUNK_SIZE = 24  # 无标点时的硬切粒度，用户确认的视觉密度


class TextSlicer:
    """把整段文本切成打字机片段。

    为什么需要：中转站会把整个 text 块缓冲成一次 text_delta——
    实测 243 字符只给 1 个事件。前端拿到就是「憋一下再整段蹦出来」，
    没有打字机效果。这个类在后端补上那一层。

    切法是「先按标点断句，再贪心合并到接近 CHUNK_SIZE」，而不是按
    CHUNK_SIZE 硬切。硬切会把标点切成独立片段（「。」独占一段），
    打字机在那儿会顿一下，看起来像卡住。

    不变量：``"".join(feed(文本) + flush())`` 必须等于输入的文本。
    切片只改变送达节奏，一个字都不能丢。
    """

    def __init__(self, chunk_size: int = CHUNK_SIZE) -> None:
        self._chunk_size = chunk_size
        # 攒够 1.5 片才允许切，避免切在刚过阈值的位置造成忽长忽短。
        self._min_cut_at = int(chunk_size * 1.5)
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """吃进一段文本，吐出可以立即发送的片段。

        保留不足一片的尾巴在缓冲区里，等下一次 feed 或 flush 再发。
        """
        self._buffer += text
        pieces: list[str] = []
        while True:
            cut = self._find_cut(self._buffer)
            if cut <= 0:
                break
            pieces.append(self._buffer[:cut])
            self._buffer = self._buffer[cut:]
        return pieces

    def flush(self) -> list[str]:
        """流结束时把缓冲区清空。

        尾巴通常是一个短句，一次吐掉即可。但无标点的长文本可能剩下一大截
        （攒够 1.5 片才切，最后往往不够阈值），一次性吐出去会丢掉打字机
        效果——用户看到的是「打字机停住，然后整段蹦出来」。所以尾巴也要
        按粒度切。
        """
        if not self._buffer:
            return []

        remainder = self._buffer
        self._buffer = ""
        if len(remainder) <= self._chunk_size:
            return [remainder]
        return [
            remainder[i : i + self._chunk_size] for i in range(0, len(remainder), self._chunk_size)
        ]

    def _find_cut(self, text: str) -> int:
        """找一个合适的切点，返回切点下标；找不到返回 0。

        等攒够 ``chunk_size * 1.5`` 才考虑切——只攒够一片就急着切会
        切在刚过阈值的位置，片段长度忽长忽短，视觉上节奏不稳。

        搜索窗口放宽到 ``_min_cut_at``（而不是一个 chunk_size）再从后往前
        找：技术文本里常有整句没有中文标点（《TCO》这种全角括号不算），
        窗口太窄就只能在很靠前的位置切，切出「7 字 + 24 字 + 12 字」
        这种参差不齐的结果。窗口放宽后能等到后面那个真正的句号。

        切点优先级：强标点（句号等）> 弱标点（逗号等）> 硬切。
        """
        if len(text) < self._min_cut_at:
            return 0

        window = text[: self._min_cut_at]
        for chars in (BREAK_CHARS, SOFT_BREAK_CHARS):
            for cut in range(len(window) - 1, -1, -1):
                if window[cut] in chars and not _splits_a_token(window, cut):
                    return cut + 1

        # 窗口内一个标点都没有：硬切在粒度上，不等更远。
        return min(self._chunk_size, len(text))


def _splits_a_token(window: str, cut: int) -> bool:
    """在 ``cut`` 处切会不会把一个西文词 / 数字劈成两半。

    ``100,000`` 的逗号是千分位、``3.14`` 的点是小数点——切在这些位置
    会让 ``100,000`` 变成 ``100,`` + ``000`` 两条 delta，看着像 bug。

    **只对 ASCII 判断。** 中文字符的 ``str.isalnum()`` 同样返回 True，
    若不限定 ASCII，「算力。」的句号两侧都是汉字，整句会被误判成
    「劈开了词」而跳过——结果是中文标点切分 100% 失效，全部退化成
    硬切，连词都被劈（``QPS`` → ``Q`` + ``PS``）。
    """
    if cut == 0 or cut + 1 >= len(window):
        return False
    before = window[cut - 1]
    after = window[cut + 1]
    return (
        before.isascii()
        and after.isascii()
        and before.isalnum()
        and after.isalnum()
    )
