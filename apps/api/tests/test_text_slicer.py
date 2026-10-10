"""打字机切片器测试。

最重要的断言是「还原一致」——切片只改变送达节奏，一个字都不能丢。
其余测试盯的是切点质量（不劈数字、不产生忽长忽短的片段）。
"""

from app.services.stream import (
    CHUNK_SIZE,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    NodeEvent,
    TextSlicer,
    ToolCallEvent,
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
    assert len(pieces) == 3  # 24 + 24 + 2
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
