"""agent 与前端之间的事件契约：事件 DTO + 打字机切片器。

放在 services 而不是 gateway，因为这些类型是 ``agent.run_agent`` 的
**返回类型**——agent 不 import 它就没法写下去。gateway 只负责把事件
编码成 SSE 字节。

事件一律走 JSON envelope 里的 ``type`` 字段区分，不用 SSE 原生的
``event:`` 行：前端用 ``fetch`` + ``ReadableStream`` 消费，一个
``split("\\n\\n")`` + ``JSON.parse`` 就能统一解析，少一层协议。
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
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
    lifecycle: str  # "active" | "completed" | "failed"
    detail: str = ""
    elapsed_ms: int | None = None
    note: str = ""
    """这个节点的产出摘要（完成时才有）。

    ``detail`` 是**进行时**的描述（「正在校验引用」），节点跑完后后端发
    completed 且 detail 为空串，此时前端回落到静态 role。

    ``note`` 补上第三种信息：**这个节点干了什么、结果如何**。例如
    Supervisor 的「拆解出 3 个子任务」、Analyst 的「核对 12 条证据，
    发现 2 处矛盾」。

    没有它，前端只能显示角色的静态说明（「拆解问题意图」）——用户
    看不到节点的实际产出，那张 DAG 就只是一张流程图。

    刻意与 ``detail`` 分开：``detail`` 在 active 时有值、完成后清空；
    ``note`` 在 active 时为空、完成后才有值。两者的生命周期相反，
    塞进同一个字段必然有一边显示错。
    """


@dataclass(frozen=True, slots=True)
class DeltaEvent:
    """正文增量。一小段，不是全文——前端 ``streamedText += delta.text``。

    ``reset=True`` 表示「把已经收到的正文清掉，从这里重新开始」。
    它只在**流被掐断后整轮重发**时出现：重发会从头再生成一遍，
    而上游有随机性（实测同一 prompt 连发 4 次，字数 1653/1155/1737/2164
    各不相同），没法靠裁剪前缀来去重——只能让前端把这一轮先收到的丢掉。

    前端收到它要把本轮的正文清零。少了这个信号，用户会看到同一段
    正文出现两遍（前半截是断流前的，后半截是重发后的）。
    """

    node_id: str
    text: str
    reset: bool = False


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
    error_code: str = ""
    """这一档的错误码（空串 = 没有）。

    与 ``ok`` 互补：``ok=False`` 是「工具坏了」；``error_code`` 非空而
    ``ok=True`` 是「工具正常跑完，但结果落在某一档特殊情况里」——
    比如 ``retrieval_no_match``（私有资料与问题不相关）。用户需要看见它：
    资料被跳过了，得让他知道。
    """


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
class RunEvent:
    """流的**第一帧**：告诉前端这次研究的 run id 与问题原文。

    ## 为什么用事件而不是响应头

    run id 必须让前端知道，才能在刷新 / 切页之后接回那一轮
    （见 ``app/services/runs.py``）。用 HTTP 响应头下发要额外配
    ``CORSMiddleware(expose_headers=...)``——跨域下 JS 读不到没
    expose 的自定义头，读到的是 null，而症状是「重连永远 404」，
    很难查。事件帧走的是流本身，没有这个坑。

    ## 为什么必须是第一帧

    前端拿到 run id 之后要**存下来**（刷新后还要用）。如果它排在
    正文中间，用户可能在正文已经出来之前就刷新了——那时候前端手里
    没有 run id，接不回来。所以它必须先于一切内容到达。

    ## 为什么带 question

    重连时前端是空的，它不知道这一轮问的是什么。服务端知道（run 里有），
    所以由第一帧带过去——省得前端再存一份 question 到 localStorage，
    也避免两份数据不一致（前端存的那份可能是上一轮的）。
    """

    run_id: str
    question: str


@dataclass(frozen=True, slots=True)
class DoneEvent:
    """正常收尾。必须带 session_id 与 token 数——前端 DAG 头部要显示。"""

    session_id: str
    elapsed_ms: int
    turns: int
    input_tokens: int
    output_tokens: int
    truncated: bool = False
    report_id: int | None = None
    """刚落盘的报告 id。

    None 有两种含义，**故意不区分**：无 db（单测路径）与落盘失败。前端
    只需知道「这次没进历史报告」，而区分它们对用户没有价值——真要查根因
    看服务端日志，那里有 ``session_id`` 与完整 traceback。
    """


@dataclass(frozen=True, slots=True)
class FaithfulnessEvent:
    """Critic 节点的校验结论。``skipped`` 为真时只带 reason。

    刻意**不阻断**：模型已跑完多轮检索，把未支撑的角标从正文里剔除
    等于让它的工作白费，而把结论标注出来让用户自己判断，成本为零。
    """

    checked: int
    supported: int
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    missing: list[int] = field(default_factory=list)
    skipped: bool = False
    reason: str = ""


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
    RunEvent
    | NodeEvent
    | DeltaEvent
    | ToolCallEvent
    | ReferenceEvent
    | FaithfulnessEvent
    | DoneEvent
    | ErrorEvent
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
        RunEvent: "run",
        NodeEvent: "node",
        DeltaEvent: "delta",
        ToolCallEvent: "tool_call",
        ReferenceEvent: "reference",
        DoneEvent: "done",
        FaithfulnessEvent: "faithfulness",
        ErrorEvent: "error",
    }[type(event)]


# ── 打字机切片 ───────────────────────────────────────────────

# 优先切点：句末标点。这里切出来的片段一定是完整可读的短句。
BREAK_CHARS = "。！？；\n"

# 次级切点：句中标点。只在优先切点找不到时用。
SOFT_BREAK_CHARS = "，、：,;:"

CHUNK_SIZE = 8  # 每片的字数上限

# 两片之间的最小间隔（秒）。
#
# 它只是**兜底**，不是主要节奏——主要节奏由 ``TARGET_CHARS_PER_SECOND``
# 的令牌桶控制。设成 16ms（约一帧）是防「一个字一个字蹦」：上游逐字
# 吐时每片 8 字，正常会隔 50ms 以上；真出现 16ms 一片说明上游在
# 疯狂推送，这时至少留一点间隔让浏览器有机会渲染。
MIN_PIECE_INTERVAL_SECONDS = 0.016

# 展示速度（字/秒）。
#
# ## 怎么定的（2026-10-30 用户反馈后重标定）
#
# 用户反馈：「不能算是流式了，一次性蹦出太多字符，两次就生成完全文，
# 一次生成的字符一定要少」。第一版取 24 字/片 + 35ms 间隔，实测
# **800 字正文在 0.8 秒内全部送出**——用户等了 25 秒上游，然后全文
# 在 1 秒内涌出来，视觉上就是「一下蹦出」。
#
# 现在按「每秒多少字」定，而不是按「每片多少毫秒」：
#
# - 中文阅读速度约 300-500 字/分钟 = **5-8 字/秒**
# - 打字机要比阅读快，但快到能看出「在动」就够了
#
# 取 **80 字/秒**：800 字要 10 秒。配合 8 字/片，是每 100ms 增长一段。
# 肉眼能看出逐段生长，又不至于让人等得不耐烦。
#
# ## 为什么按字数而不是按片数
#
# 按「每片固定等 N 毫秒」的话，上游真流式的情况会被拖慢（实测 720 字
# 上游 5 秒能吐完，加固定 200ms 间隔后变 19.2 秒）。按字数算（令牌桶）
# 就两全：上游缓冲时慢放，上游真流式时跟随上游。
TARGET_CHARS_PER_SECOND = 80.0


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
        窗口太窄就只能在很靠前的位置切，切出参差不齐的结果。窗口放宽后
        能等到后面那个真正的句号。

        切点优先级：强标点（句号等）> 弱标点（逗号等）> 硬切。

        ## 为什么切点不能落在缓冲区末尾

        流式下缓冲区里是「**已经收到的**」文本。逗号正好落在缓冲区
        末尾时，后面那个 ``000`` 还没到——此时无法判断这是千分位还是
        真逗号，只能赌。而赌错的后果是 ``100,000`` 被切成
        ``100,`` + ``000``（2026-10-30 实测复现）。

        所以切点后面必须**至少还有一个字符**，否则这个标点还不能用，
        等下一次 feed 补齐了再判断。
        """
        if len(text) < self._min_cut_at:
            return 0

        window = text[: self._min_cut_at]
        for chars in (BREAK_CHARS, SOFT_BREAK_CHARS):
            for cut in range(len(window) - 1, -1, -1):
                if cut + 1 >= len(text):
                    # 后面还没有字符，看不出是词内还是词间——不能切。
                    continue
                if window[cut] in chars and not _splits_a_token(text, cut):
                    return cut + 1

        # 窗口内一个标点都没有：硬切在粒度上，不等更远。
        #
        # 硬切也不能落在词中间——``Blackwell`` 被切成 ``Blackwel`` + ``l``
        # 在界面上就是「英文单词被劈开」。往后找第一个非 ASCII 字母数字
        # 的位置；找不到（词一直延伸到缓冲区末尾）就说明后面还有字没到，
        # 此时不切，等下一次 feed。
        hard_cut = min(self._chunk_size, len(text))
        while hard_cut < len(text) and text[hard_cut].isascii() and text[hard_cut].isalnum():
            hard_cut += 1
        if hard_cut >= len(text):
            return 0
        if hard_cut > 0 and _splits_a_token(text, hard_cut - 1):
            # 找到的边界本身还在词内（前面是 ASCII 字母数字）——继续往后。
            while hard_cut < len(text) and text[hard_cut].isascii() and text[hard_cut].isalnum():
                hard_cut += 1
            if hard_cut >= len(text):
                return 0
        return hard_cut


def _splits_a_token(text: str, cut: int) -> bool:
    """在 ``cut`` 处切会不会把一个西文词 / 数字劈成两半。

    ``100,000`` 的逗号是千分位、``3.14`` 的点是小数点——切在这些位置
    会让 ``100,000`` 变成 ``100,`` + ``000`` 两条 delta，看着像 bug。

    **看的是完整文本，不是搜索窗口。** 窗口只有 ``chunk_size * 1.5``
    字（chunk_size=8 时是 12 字），标点常落在窗口末尾——此时窗口里
    看不到下一个字符，判断不了它是词内还是词间，只能放行，于是
    ``100,000`` 被劈成 ``100,`` + ``000``（2026-10-30 实测复现）。

    **只对 ASCII 判断。** 中文字符的 ``str.isalnum()`` 同样返回 True，
    若不限定 ASCII，「算力。」的句号两侧都是汉字，整句会被误判成
    「劈开了词」而跳过——结果是中文标点切分 100% 失效，全部退化成
    硬切，连词都被劈（``QPS`` → ``Q`` + ``PS``）。
    """
    if cut <= 0 or cut + 1 >= len(text):
        return False
    before = text[cut - 1]
    after = text[cut + 1]
    return before.isascii() and after.isascii() and before.isalnum() and after.isalnum()


class Typewriter:
    """把上游的增量变成**有节奏**的展示片段。

    它是 ``TextSlicer`` 的上一层：切片决定「在哪断」，控速决定「隔多久送」。

    ## 为什么两件事都要做

    只切片不控速——用户看到的是「一下全出」：上游把整段缓冲成一次
    送达，切片器切出来的几十片在同一瞬间全部出栈，浏览器一个 TCP 块
    收齐，React 一次渲染完。切片白做了。

    只控速不切片——用户看到的是「一个字一个字蹦」，每个 delta 帧
    可能只有 1 个字（实测上游逐字吐时帧长就是 1-2 字），DOM 里全是
    碎片段，Markdown 的行内格式（``**加粗**``）会被切在中间。

    所以：切片器负责粒度，控速负责节奏。

    ## 为什么必须是异步生成器而不是「返回列表」

    返回列表的话，控速的等待发生在**函数内部**——调用方一次性拿到
    全部片段再往下游发，等待等于白费：等完之后所有片段仍然在同一
    瞬间交付出去。

    做成生成器，等待发生在**每次交付之前**：调用方取下一片时才等，
    等完立刻把这一片发出去。节奏才是真的。

    ## 控速是「令牌桶」，不是「每片固定等 N 毫秒」

    固定间隔会把上游真流式的情况也拖慢（实测：720 字上游 12 秒能吐完，
    加固定间隔后变成 19.2 秒）。而上游缓冲的情况又需要被拖慢。

    令牌桶能同时满足两者：**按累计字数算**，而不是按片数算。

    - 上游缓冲（一次来 500 字）→ 累积字数远超配额 → 必须等 → 慢放
    - 上游真流式（一个字一个字来）→ 累积字数一直贴着配额 → 不用等 →
      跟随上游速度

    配额是 ``chars_per_second``。每送出一片就消耗那片字数对应的「时间
    配额」；不够就得等到配额够。
    """

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        min_interval: float = MIN_PIECE_INTERVAL_SECONDS,
        chars_per_second: float = TARGET_CHARS_PER_SECOND,
    ) -> None:
        self._slicer = TextSlicer(chunk_size)
        self._min_interval = min_interval
        self._chars_per_second = chars_per_second
        # 「还能立刻送出的字数」。正数表示有余量，负数表示欠着（要等）。
        self._credit = 0.0
        # 配额上限：不设的话上游停顿时会攒下巨量配额，恢复后一瞬间涌出。
        # 上限给 2 片——够覆盖一次正常停顿，又不会攒出「一下蹦出」。
        self._max_credit = float(chunk_size * 2)
        self._last_sent_at: float | None = None

    async def feed(self, text: str) -> AsyncIterator[str]:
        """吃进一段上游增量，逐片**按节奏**送出。

        不足一片的尾巴留在切片器缓冲区里，等下一次 feed 或 flush。
        """
        for piece in self._slicer.feed(text):
            await self._wait(piece)
            yield piece

    async def flush(self) -> AsyncIterator[str]:
        """流结束时把缓冲区清空，同样按节奏送出。"""
        for piece in self._slicer.flush():
            await self._wait(piece)
            yield piece

    async def _wait(self, piece: str) -> None:
        """按令牌桶节奏等到「配额够」再放这一片出去。

        ``_credit`` 是**还能立刻送出的字数**：每送一片扣掉它的字数，
        欠了就等——等的时间就是欠的字数除以目标速度。
        """
        if self._last_sent_at is not None:
            # 距上一片的时间流逝会补回配额：这段时间上游「送」了那么多字，
            # 我们也就有那么多字可以立刻发出去。
            elapsed = time.monotonic() - self._last_sent_at
            self._credit = min(
                self._credit + elapsed * self._chars_per_second,
                self._max_credit,
            )
            # 至少隔 ``min_interval``——不然会变成「一个字一个字蹦」。
            min_wait = self._min_interval - elapsed
            if self._credit < 0:
                min_wait = max(min_wait, -self._credit / self._chars_per_second)
            if min_wait > 0:
                await asyncio.sleep(min_wait)
                # 等够了，欠的配额补平（多等出来的时间算富余）。
                self._credit = max(0.0, self._credit + min_wait * self._chars_per_second)

        self._credit -= len(piece)
        self._last_sent_at = time.monotonic()
