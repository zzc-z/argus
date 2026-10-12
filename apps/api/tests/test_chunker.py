"""chunker 的测试。

重点覆盖三件实测出来的事（都在 app/services/chunker.py 的 docstring 里）：
1. 默认 separators 不产生单字符碎片（自定义 separators 会）
2. overlap 真的生效（易被误判为没生效）
3. 偏移量在重复段落 / 无分隔符文本里也能正确定位
"""

import pytest

from app.services.chunker import Chunk, ChunkingError, TextChunker
from app.services.parser import ParsedBlock

REPORT = (
    "更为关键的是，总体拥有成本（TCO）为大规模智算中心运营方带来了革命性的结构优化。"
    "以支撑 100,000 QPS 推理负载的集群规模测算，Blackwell 较同等吞吐量的 Hopper "
    "集群将数据中心综合电力消耗锐减 75%。"
    "混合注意力机制使长上下文推理的显存占用下降约 40%。"
    "根据 Omdia 2024 年第三季度报告，全球 AI 加速卡出货量同比增长 192%。"
)


def _chunker(size: int = 120, overlap: int = 20) -> TextChunker:
    return TextChunker(chunk_size=size, chunk_overlap=overlap)


# ── 基本不变量 ─────────────────────────────────────────────
def test_chunks_index_is_globally_sequential() -> None:
    """引用格式 [1] 对应 index+1，序号乱了引用全错。"""
    chunks = _chunker().chunk_blocks([ParsedBlock(text=REPORT, page=1)])

    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_never_exceeds_size() -> None:
    """超长 chunk 会撑爆 embedding 的 token 预算。"""
    chunks = _chunker(size=120, overlap=20).chunk_blocks(
        [ParsedBlock(text=REPORT, page=1)]
    )

    assert all(len(c.text) <= 120 for c in chunks)


def test_offsets_point_at_real_text() -> None:
    """偏移量必须能取回原文本身——引用高亮全靠它。"""
    block = ParsedBlock(text=REPORT, page=1)
    chunks = _chunker().chunk_blocks([block])

    for chunk in chunks:
        assert block.text[chunk.start_offset : chunk.end_offset] == chunk.text


def test_all_characters_covered_by_some_chunk() -> None:
    """内容不能丢：拼接所有 chunk（去重叠）要覆盖全文。"""
    block = ParsedBlock(text=REPORT, page=1)
    chunks = _chunker().chunk_blocks([block])

    covered = "".join(block.text[c.start_offset : c.end_offset] for c in chunks)

    assert len(covered) >= len(REPORT)
    for piece in REPORT.split("。"):
        if piece.strip():
            assert piece[:10] in covered


# ── overlap ────────────────────────────────────────────────
def test_overlap_repeats_text_between_chunks() -> None:
    """overlap 的意义：跨片的一句话仍能被完整看到。

    断言方式不能是「片 i 尾 == 片 i+1 头」——重叠是错位对齐，不是等长复制。
    正确做法：片 i 的尾部片段应出现在片 i+1 里。
    """
    chunks = _chunker(size=100, overlap=30).chunk_blocks(
        [ParsedBlock(text=REPORT, page=1)]
    )

    assert len(chunks) >= 2, "样本太短，测不出重叠"
    for i in range(len(chunks) - 1):
        tail = chunks[i].text[-10:]
        assert tail in chunks[i + 1].text, f"片{i} 尾部未出现在片{i+1}"


def test_no_overlap_when_zero() -> None:
    chunks = TextChunker(chunk_size=100, chunk_overlap=0).chunk_blocks(
        [ParsedBlock(text=REPORT, page=1)]
    )

    for i in range(len(chunks) - 1):
        assert chunks[i].text[-10:] not in chunks[i + 1].text


# ── 无碎片（默认 separators 的核心收益）──────────────────────
# 这段文本 + chunk_size=50 是实测能触发孤立「。」片的组合——用别的尺寸
# 测不出来（碎片不是普遍现象，是特定组合的结果）。
FRAGMENT_TRIGGER = (
    "更为关键的是，总体拥有成本（TCO）为大规模智算中心运营方带来了革命性的结构优化。"
    "以支撑 100,000 QPS 推理负载的集群规模测算，Blackwell 较同等吞吐量的 Hopper "
    "集群将数据中心综合电力消耗锐减 75%。"
)


def test_no_single_char_fragments() -> None:
    """单字符碎片是纯噪声：一条垃圾 embedding，白占索引。

    换成 PRD 那串自定义 separators 就会多出一片孤立的「。」。
    变异测试确认过这个测试在保护设计决策。
    """
    chunks = TextChunker(chunk_size=50, chunk_overlap=10).chunk_blocks(
        [ParsedBlock(text=FRAGMENT_TRIGGER, page=1)]
    )

    assert all(len(c.text.strip()) > 1 for c in chunks), f"出现碎片片：{[c.text for c in chunks]}"


def test_punctuation_not_isolated() -> None:
    """句号不该独占一片。"""
    chunks = TextChunker(chunk_size=50, chunk_overlap=10).chunk_blocks(
        [ParsedBlock(text=FRAGMENT_TRIGGER, page=1)]
    )

    assert all(c.text.strip("。！？.!?\n") for c in chunks)


# ── 多页 ───────────────────────────────────────────────────
def test_page_carried_to_every_chunk() -> None:
    """页码必须每片都带着——引用要写 [1, p.3]。"""
    blocks = [
        ParsedBlock(text=REPORT, page=1),
        ParsedBlock(text=REPORT, page=2),
    ]

    chunks = _chunker().chunk_blocks(blocks)

    assert {c.page for c in chunks} == {1, 2}


def test_offsets_are_page_relative() -> None:
    """偏移量是**页内**偏移，不是全文偏移——跨页拼接会让页码和偏移错配。"""
    page2_text = REPORT
    blocks = [ParsedBlock(text="短文本。", page=1), ParsedBlock(text=page2_text, page=2)]

    chunks = _chunker().chunk_blocks(blocks)
    on_page2 = [c for c in chunks if c.page == 2]

    assert all(c.start_offset < len(page2_text) for c in on_page2)
    assert all(page2_text[c.start_offset : c.end_offset] == c.text for c in on_page2)


# ── 难定位的场景 ───────────────────────────────────────────
def test_repeated_paragraphs_offsets_advance() -> None:
    """重复文本时偏移量必须往前推，不能全部贴到文首。

    这是用顺序 find（带 cursor）而非朴素 find 的原因。
    """
    repeated = "结论是先做检索增强。详细推导过程见附录。" * 5
    chunks = _chunker(size=80, overlap=10).chunk_blocks(
        [ParsedBlock(text=repeated, page=1)]
    )

    starts = [c.start_offset for c in chunks]
    assert starts == sorted(starts), f"偏移量必须单调不减，实际 {starts}"


def test_no_separator_text_still_locatable() -> None:
    """无分隔符的连续字符会触发字符级硬切，最容易定位失败。"""
    text = "A" * 300
    chunks = TextChunker(chunk_size=50, chunk_overlap=10).chunk_blocks(
        [ParsedBlock(text=text, page=1)]
    )

    assert len(chunks) >= 5
    for chunk in chunks:
        assert text[chunk.start_offset : chunk.end_offset] == chunk.text


def test_mixed_cjk_ascii_locatable() -> None:
    """中英混排无空格——真实研报里很常见。"""
    text = "深度学习模型transformer架构的训练需要大量标注数据2024年" * 8
    chunks = TextChunker(chunk_size=50, chunk_overlap=10).chunk_blocks(
        [ParsedBlock(text=text, page=1)]
    )

    for chunk in chunks:
        assert text[chunk.start_offset : chunk.end_offset] == chunk.text


# ── 错误路径 ───────────────────────────────────────────────
def test_rejects_overlap_not_smaller_than_size() -> None:
    """overlap >= size 会死循环，必须在构造时挡掉。"""
    with pytest.raises(ValueError, match="overlap"):
        TextChunker(chunk_size=50, chunk_overlap=50)


def test_empty_blocks_raise() -> None:
    """空输入不返回空列表——摄取流程会静默「成功」但库里没东西。"""
    with pytest.raises(ChunkingError):
        _chunker().chunk_blocks([])


def test_chunk_is_frozen() -> None:
    chunk = Chunk(text="x", index=0, page=1, start_offset=0, end_offset=1)

    with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError
        chunk.text = "y"  # type: ignore[misc]
