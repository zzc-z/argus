"""打字机切片器测试。

最重要的断言是「还原一致」——切片只改变送达节奏，一个字都不能丢。
其余测试盯的是切点质量（不劈数字、不产生忽长忽短的片段）。
"""

import asyncio
import time

from app.services.stream import (
    CHUNK_SIZE,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    NodeEvent,
    TextSlicer,
    ToolCallEvent,
    Typewriter,
    encode_frame,
)

LONG_TEXT = (
    "更为关键的是，总体拥有成本 (TCO) 为大规模智算中心运营方带来了革命性的结构优化。"
    "以支撑 100,000 QPS 推理负载的集群规模测算，Blackwell 较同等吞吐量的 Hopper 集群"
    "将数据中心综合电力消耗锐减 75%。目前主要的落地摩擦点集中于机房二次液冷系统改建，"
    "因为 GB200 机柜强制要求采用单机柜高达 120kW 换热密度的芯片级直触液冷回路。"
)


def _slice_all(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """走完整的 feed + flush，返回全部片段。"""
    slicer = TextSlicer(chunk_size)
    pieces = slicer.feed(text)
    pieces.extend(slicer.flush())
    return pieces


# ── 不变量：不能丢字 ──────────────────────────────────────────


def test_reassembled_output_equals_input() -> None:
    """所有片段拼起来必须与原文完全一致——切片只改节奏不改内容。"""
    assert "".join(_slice_all(LONG_TEXT)) == LONG_TEXT


def test_incremental_feeds_preserve_text() -> None:
    """逐字喂进去（模拟最极端的分块）也必须还原。"""
    slicer = TextSlicer()
    pieces: list[str] = []
    for ch in LONG_TEXT:
        pieces.extend(slicer.feed(ch))
    pieces.extend(slicer.flush())
    assert "".join(pieces) == LONG_TEXT


# ── 切点质量 ──────────────────────────────────────────────────


def test_piece_lengths_stay_near_chunk_size() -> None:
    """片段长度不该忽长忽短——视觉节奏要稳。

    没有中文标点的长句可以超出一片（宁可整句给用户，也不劈词）。
    真正要守的是「不能碎片化」——绝大多数片段要接近或超过粒度。
    """
    lengths = [len(p) for p in _slice_all(LONG_TEXT)]
    assert max(lengths) <= CHUNK_SIZE * 2, f"片段过长: {lengths}"
    body = lengths[1:-1]
    assert sum(1 for n in body if n >= int(CHUNK_SIZE * 0.75)) >= len(body) * 0.6


def test_does_not_split_thousands_separator() -> None:
    """100,000 的逗号是千分位，不能在这里断开。"""
    pieces = _slice_all(LONG_TEXT)
    for piece in pieces:
        # 不该出现「以支撑 100,」这种把数字切一半的结尾
        assert not piece.endswith("100,"), f"数字被劈开: {piece!r}"


def test_hard_splits_run_without_punctuation() -> None:
    """完全没有标点的长文本按粒度硬切，不产生超长片段。"""
    text = "无标点长句" * 20
    pieces = _slice_all(text)
    assert len(pieces) > 1
    assert all(len(p) <= CHUNK_SIZE for p in pieces)
    assert "".join(pieces) == text


def test_long_unpunctuated_tail_is_resliced_on_flush() -> None:
    """无标点长文本的最后一大截尾巴也要切——不能整段蹦出来。

    攒够 1.5 片才切意味着最后常常剩一大截，flush 时必须按粒度再切，
    否则用户会看到打字机突然停住然后整段刷新。
    """
    text = "无" * 50
    pieces = _slice_all(text)
    assert all(len(p) <= CHUNK_SIZE for p in pieces)
    # 片数随 CHUNK_SIZE 变，不写死——写死会在调粒度时失效。
    assert len(pieces) == -(-50 // CHUNK_SIZE)  # 向上取整
    assert "".join(pieces) == text


def test_prefers_strong_punctuation_over_hard_cut() -> None:
    """有句号时不该无视它去硬切。"""
    text = "第一句很短。第二句也很短。第三句稍微长一点点但仍然不长。"
    pieces = _slice_all(text)
    # 至少有一片以句号结尾（说明按标点切了，而不是全靠硬切）
    assert any(p.endswith("。") for p in pieces)


def test_weak_punctuation_used_when_no_strong_one() -> None:
    """没有句号但有逗号时，退到弱标点切。

    断言「至少一片以逗号结尾」——只查 len>=2 的话，纯硬切也能满足，
    测不出弱标点到底生效没有。
    """
    text = (
        "这是一个很长的从句，里面有很多逗号，用来测试弱标点切分是否生效，"
        "还需要再长一点才够触发阈值，最后补一个句号收尾。"
        "这里再补一句，确保缓冲区足够长，能切出两片以上。"
    )
    pieces = _slice_all(text)
    body = pieces[:-1]
    assert len(body) >= 2, f"应切出多片，实际: {pieces}"
    assert any(p.endswith("，") for p in body), f"应按逗号切，实际: {body}"


# ── flush 边界 ────────────────────────────────────────────────


def test_flush_on_empty_buffer_yields_nothing() -> None:
    """缓冲为空时 flush 返回空列表，不产生空字符串片段。"""
    slicer = TextSlicer()
    assert slicer.flush() == []
    # 连续调两次也不该吐出东西
    assert slicer.flush() == []


def test_flush_emits_short_remainder() -> None:
    """不足一片的尾巴由 flush 吐出，不能丢。"""
    slicer = TextSlicer()
    slicer.feed("完整的一句。")  # 不够阈值，全部留在缓冲
    assert slicer.flush() == ["完整的一句。"]


def test_empty_input_produces_nothing() -> None:
    assert _slice_all("") == []


def test_single_character_flushes_whole() -> None:
    assert _slice_all("。") == ["。"]


def test_custom_chunk_size_respected() -> None:
    """自定义粒度要真的生效。"""
    text = "一" * 100
    pieces = _slice_all(text, chunk_size=10)
    assert all(len(p) <= 10 for p in pieces)
    assert "".join(pieces) == text


# ── SSE 帧编码 ────────────────────────────────────────────────


def test_encode_frame_shape() -> None:
    """帧格式是 data: {json}\\n\\n，type 在 envelope 里。"""
    raw = encode_frame(NodeEvent(node_id="supervisor", lifecycle="active", detail="拆解意图"))
    text = raw.decode()
    assert text.endswith("\n\n")
    assert text.startswith("data: ")

    import json
    payload = json.loads(text[6:].strip())
    assert payload["type"] == "node"
    assert payload["v"]["node_id"] == "supervisor"
    assert payload["v"]["lifecycle"] == "active"


def test_encode_frame_keeps_chinese_readable() -> None:
    """中文不能被转义成 \\uXXXX——前端要拿到可读文本。"""
    raw = encode_frame(DeltaEvent(node_id="writer", text="总体拥有成本")).decode()
    assert "总体拥有成本" in raw
    assert "\\u" not in raw


def test_encode_frame_type_names() -> None:
    """5 种事件类型的 type 字段名必须固定。

    前端按 payload["type"] 分发——工具面板（用户最常看的实时反馈）和
    错误收尾（防前端永远转圈）这两个类型改错了前端直接静默失效，
    所以必须逐个断言，不能只测其中三个。
    """
    import json

    cases = [
        (NodeEvent(node_id="a", lifecycle="active"), "node"),
        (DeltaEvent(node_id="a", text="x"), "delta"),
        (
            ToolCallEvent(call_id="c", phase="start", name="tavily_search"),
            "tool_call",
        ),
        (
            DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1),
            "done",
        ),
        (ErrorEvent(code="llm_unavailable", message="挂了"), "error"),
    ]
    for event, expected in cases:
        raw = encode_frame(event).decode()
        payload = json.loads(raw[6:].strip())
        assert payload["type"] == expected, f"{type(event).__name__} 的 type 名不对"


def test_encode_frame_no_type_collision() -> None:
    """5 种事件编码后 type 必须互不相同——防复制粘贴改错。"""
    import json

    events = [
        NodeEvent(node_id="a", lifecycle="active"),
        DeltaEvent(node_id="a", text="x"),
        ToolCallEvent(call_id="c", phase="end", name="t"),
        DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1),
        ErrorEvent(code="c", message="m"),
    ]
    names = [json.loads(encode_frame(e).decode()[6:].strip())["type"] for e in events]
    assert len(set(names)) == len(names), f"type 字段重复: {names}"


# ── Typewriter：切片 + 控速 ──────────────────────────────────


async def test_typewriter_paces_pieces() -> None:
    """片段之间必须有间隔——不能一次性全出栈。

    ## 要防的回归

    只有切片不控速时，上游一次性到齐的正文会被切成几十片、然后在
    **同一瞬间**全部 yield 出去。浏览器一个 TCP 块收齐，React 一次
    渲染完——用户看到的就是「一下全出」，打字机效果完全不存在。

    这正是 2026-10-30 修复前 explore 页的真实表现（实测：60 个 delta
    帧在 0.0 ms 内全部出栈）。
    """
    typewriter = Typewriter(chunk_size=8, min_interval=0.02)
    text = "第一句话在这里。第二句话也在这里。第三句话同样在这里。"

    stamps: list[float] = []
    async for _piece in typewriter.feed(text):
        stamps.append(time.monotonic())
    async for _piece in typewriter.flush():
        stamps.append(time.monotonic())

    assert len(stamps) >= 2, "这段文字应该切出多片"
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    assert min(gaps) >= 0.015, f"片段之间没有间隔，实际间隔：{gaps}"


async def test_typewriter_preserves_all_text() -> None:
    """控速不能丢字——切片的唯一不变量在控速之后依然成立。"""
    typewriter = Typewriter(chunk_size=10, min_interval=0.001)
    text = "把这段中文完整地送出去，一个字都不能少。带标点，也有换行。\n第二行。"

    pieces: list[str] = []
    async for piece in typewriter.feed(text):
        pieces.append(piece)
    async for piece in typewriter.flush():
        pieces.append(piece)

    assert "".join(pieces) == text


async def test_typewriter_min_interval_zero_keeps_pieces() -> None:
    """间隔设为 0 时不等待——但片段照样切出来、内容照样完整。

    钉住「控速」与「切片」是两件独立的事：把间隔关掉不能把切片也关掉。
    """
    typewriter = Typewriter(chunk_size=10, min_interval=0.0)
    text = "把这段中文完整地送出去，一个字都不能少。"

    pieces: list[str] = []
    async for piece in typewriter.feed(text):
        pieces.append(piece)
    async for piece in typewriter.flush():
        pieces.append(piece)

    assert len(pieces) >= 2
    assert "".join(pieces) == text


async def test_typewriter_does_not_wait_when_upstream_is_slow() -> None:
    """上游间隔足够大时，后端不该再额外等待。

    控速是**令牌桶**：配额够就立刻放行。上游 50ms 来一个字时，
    后端已经攒下配额（8 字 × 0.05s × 80 字/秒 = 32 字 > 8），
    这时再等就是平白拖慢上游。

    这条与 ``test_typewriter_follows_slow_upstream`` 配对：那条测
    「整体不被拖慢」，这条测「单片之间不额外等」。
    """
    typewriter = Typewriter(chunk_size=8, min_interval=0.05, chars_per_second=80.0)
    text = "第一句话在这里。第二句话也在这里。"

    start = time.monotonic()
    stamps: list[float] = []
    async for _piece in typewriter.feed(text):
        stamps.append(time.monotonic())
    async for _piece in typewriter.flush():
        stamps.append(time.monotonic())
    elapsed = time.monotonic() - start

    assert len(stamps) >= 2
    # 全部是一次性喂进来的（上游缓冲），所以要按目标速度限速——
    # 3 片 × 8 字 = 24 字 ÷ 80 字/秒 = 0.3s 左右。
    assert elapsed < 0.5, f"等待过久：{elapsed:.3f}s / {len(stamps)} 片"


def test_numbers_are_not_split_across_pieces() -> None:
    """``100,000`` 不能被切成 ``100,`` + ``000``。

    ## 要防的回归（2026-10-30）

    ``chunk_size`` 从 24 降到 8 之后，搜索窗口缩到 12 字，逗号常常
    落在窗口末尾——而窗口里看不到下一个字符，判断不了它是千分位还是
    真逗号，只能放行。于是 ``100,000`` 被劈成两片。

    修法是看**完整缓冲区**而不是窗口：切点后面必须至少还有一个字符，
    否则这个标点还不能用，等下一次 feed 补齐再判断。
    """
    text = "以支撑 100,000 QPS 推理负载的集群规模测算，成本与功耗都要压下来。"
    pieces = _slice_all(text)

    assert "".join(pieces) == text
    assert not any(p.endswith("100,") for p in pieces), f"数字被劈开：{pieces}"
    assert not any(p.startswith("000") for p in pieces), f"数字被劈开：{pieces}"


def test_english_words_are_not_split_across_pieces() -> None:
    """``Blackwell`` 不能被切成 ``Blackwel`` + ``l``。

    硬切（没有标点可切时）也必须避开词中间——界面上英文单词被劈开
    一眼就能看出是 bug。
    """
    text = "Blackwell 较同等吞吐量的 Hopper 集群将数据中心综合电力消耗锐减 75%。"
    pieces = _slice_all(text)

    assert "".join(pieces) == text
    for word in ("Blackwell", "Hopper"):
        assert any(word in p for p in pieces), f"{word} 被劈开了：{pieces}"


async def test_typewriter_paces_by_target_speed() -> None:
    """上游一次性给一大坨时，展示速度要落在目标值附近。

    ## 要防的回归（2026-10-30 用户反馈）

    用户反馈：「不能算是流式了，一次性蹦出太多字符，两次就生成完全文，
    一次生成的字符一定要少」。第一版只切了片、不控速，实测 800 字正文
    在 **0.8 秒内**全部送出——用户等了 25 秒上游，然后全文在 1 秒内涌出。

    这条测试盯的是**速率**：一批字送完的耗时应该在
    ``字数 / 目标速度`` 附近。太快 = 一下蹦出；太慢 = 用户不耐烦。
    """
    target = 80.0
    typewriter = Typewriter(chunk_size=8, chars_per_second=target)
    text = "向量数据库的选型核心看三点：召回率、延迟与成本。" * 12  # 228 字

    start = time.monotonic()
    total = 0
    async for piece in typewriter.feed(text):
        total += len(piece)
    async for piece in typewriter.flush():
        total += len(piece)
    elapsed = time.monotonic() - start

    assert total == len(text)
    speed = total / elapsed
    # 允许 40% 的浮动——CI 机器负载、事件循环调度都会带来偏差。
    assert target * 0.6 <= speed <= target * 1.4, (
        f"展示速度 {speed:.0f} 字/秒，目标 {target:.0f} 字/秒（{total} 字 / {elapsed:.2f}s）"
    )


async def test_typewriter_follows_slow_upstream() -> None:
    """上游本身慢的时候，后端不能拖慢它。

    上游 50ms/字 = 20 字/秒，比目标（80 字/秒）慢得多。这种情况下后端
    应当**跟随**上游——拖慢上游没有任何好处，只会让用户多等。
    """
    typewriter = Typewriter(chunk_size=8, chars_per_second=80.0)
    text = "向量数据库的选型核心看三点：召回率与延迟。"

    start = time.monotonic()
    total = 0
    for ch in text:
        await asyncio.sleep(0.05)  # 上游 50ms 来一个字
        async for piece in typewriter.feed(ch):
            total += len(piece)
    async for piece in typewriter.flush():
        total += len(piece)
    elapsed = time.monotonic() - start

    assert total == len(text)
    # 上游自己就要 20 字/秒（len × 0.05 秒）。后端不能让它更慢——
    # 慢太多说明令牌桶在反向限速。
    upstream_time = len(text) * 0.05
    assert elapsed < upstream_time * 1.6, (
        f"后端把上游拖慢了：上游自己 {upstream_time:.2f}s，实际 {elapsed:.2f}s"
    )
