"""语义切片：把一段带页码的文本切成检索单元。

设计取舍（都是实测出来的，不是照文档抄）：

## 1. 用 langchain 的默认 separators，不自己传

PRD 写的是 ``["\\n\\n", "\\n", "。", "！", "？", ".", "!","?", " ", ""]``。
它在某些组合下会产出**只有「。」一个字符**的碎片片——实测中文研报段落
（以「……锐减 75%。」结尾）+ chunk_size=50：

- 默认配置 → 3 片，每片都是完整句，末片带句号收尾
- 传上述自定义 → 4 片，末尾多一片孤立的 ``。``

原因：自定义列表把 ``。`` 排在 ``.`` 之前，句末标点被当成独立分隔符切走。
单字符片会变成一条垃圾 embedding，白占索引还可能被检索出来。

注意这不是普遍现象——换 chunk_size 或换文本都不会出现碎片。但它确实会在
真实参数下发生，而默认配置没有这个问题，所以没必要冒这个险。

## 2. overlap 是生效的，别误判

「片 i 尾部 == 片 i+1 头部」这种等长比较**永远不成立**——重叠是错位对齐，
不是复制。实测 chunk_size=60/overlap=15 时片0 尾 ``hotel india``
出现在片1 头，overlap 正常工作。

反过来说：**自定义 separators 会让 overlap 看起来失效**——标点被留在片头，
吃掉了一部分本该重叠的窗口。变异测试确认过：换回自定义配置后
``test_overlap_repeats_text_between_chunks`` 立刻失败。

## 3. 偏移量靠 ``str.find`` 在原文里定位，不让 splitter 报

langchain 的 ``create_documents`` 不返回字符偏移，而引用高亮需要它。
实测（中文/无分隔符连续字符/中英混排/重复段落）每个 chunk 都能在原文中
定位成功，所以用**顺序 find**（带 cursor，不从头找）扫一遍即可。
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.parser import ParsedBlock

# PRD rag-pipeline.md §4.1。chunk_size 单位是**字符**不是 token——
# langchain 的默认 length_function 就是 len()，换 token 计数会与
# EMBEDDING_DIM 的预算对不上。
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


class ChunkingError(Exception):
    """切片失败。文本能解析但切不出可用切片。"""


@dataclass(frozen=True, slots=True)
class Chunk:
    """一个检索单元。位置字段让引用能回到原文。"""

    text: str
    index: int
    """在整份资料里的全局序号，从 0 起。引用格式 [1] 就是 index + 1。"""
    page: int | None
    start_offset: int
    """相对**该页**文本的字符起点（页内偏移，不是全文偏移）。"""
    end_offset: int


class TextChunker:
    """按 PRD 参数的切片器。构造一次复用——内部 splitter 无状态。"""

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError(f"overlap({chunk_overlap}) 必须小于 size({chunk_size})")
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def chunk_blocks(self, blocks: list[ParsedBlock]) -> list[Chunk]:
        """把若干文本块切成全局有序的切片列表。

        每个 block 独立切片（不能把整份文档拼起来切——那样 page 就丢了），
        再把页内偏移换算成全局序号。
        """
        chunks: list[Chunk] = []
        for block in blocks:
            chunks.extend(self._chunk_one(block, start_index=len(chunks)))
        if not chunks:
            raise ChunkingError("文本切片后为空，解析结果可能有问题")
        return chunks

    def _chunk_one(self, block: ParsedBlock, start_index: int) -> list[Chunk]:
        pieces = self._splitter.split_text(block.text)

        # 顺序扫描定位：cursor 只前进不回退，否则重复段落会全部贴到文首。
        cursor = 0
        chunks: list[Chunk] = []
        for offset, piece in enumerate(pieces):
            start = block.text.find(piece, cursor)
            if start < 0:  # pragma: no cover — 实测各场景都能定位，兜底不静默丢片
                raise ChunkingError(f"切片无法在原文中定位：{piece[:40]!r}")
            chunks.append(
                Chunk(
                    text=piece,
                    index=start_index + offset,
                    page=block.page,
                    start_offset=start,
                    end_offset=start + len(piece),
                )
            )
            # +1 而非 +len：重叠区允许下一片从当前位置内部开始，
            # 但要让 cursor 严格单调递增，否则同一段文本会被反复命中。
            cursor = start + 1
        return chunks
