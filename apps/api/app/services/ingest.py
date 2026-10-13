"""摄取编排：把一份原始资料走完「解析 → 切片 → 嵌入 → 落库」。

对应 prd/rag-pipeline.md §3.2。流程有两条硬约束：

## 1. 状态必须逐段落库，不能最后一次性更新

前端 add-sources 页面有队列监视器，要显示「正在切片 142/180」这类进度。
状态存在内存里的话，页面一刷新就没了。所以每进入一个阶段就commit 一次——
多几次写换来可观测的进度，值得。

## 2. 失败要留在库里，不能只抛异常

解析失败、嵌入服务挂掉，用户得能在页面上看到「这份资料失败了，原因是 X」
并重传。异常只走内存的话，用户只看到请求超时就结束了，无从重试。
所以 :func:`ingest` 捕获异常后把 ``status=failed`` + ``error_message``
写回库，再把异常抛给调用方（HTTP 层据此返回 500）。

## 事务边界

解析和切片是纯 CPU 计算，不碰库——不占着 DB 连接。
只有「写状态」和「写结果」才开事务，且两者之间会发网络请求（嵌入），
所以嵌入安排在事务之外，避免长时间持有连接。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType
from app.services import bm25
from app.services.chunker import Chunk, ChunkingError, TextChunker
from app.services.embedder import embed_or_none
from app.services.parser import (
    HtmlParser,
    ParsedBlock,
    ParseError,
    Parser,
    PdfParser,
    TextParser,
)
from app.services.vectorstore import ensure_vector_table, upsert_embeddings

logger = logging.getLogger(__name__)

# 来源类型 → 解析器。加新格式只改这一处。
_PARSERS: dict[str, Parser] = {
    SourceType.PDF: PdfParser(),
    SourceType.HTML: HtmlParser(),
    SourceType.TEXT: TextParser(),
}


class IngestError(Exception):
    """摄取失败。message 是给用户看的，不能含内部细节。"""


def parser_for(source_type: str) -> Parser:
    """按资料类型取解析器。未知类型要报出来，不能退化成纯文本硬解。"""
    try:
        return _PARSERS[source_type]
    except KeyError:
        raise IngestError(f"暂不支持的资料类型：{source_type}") from None


async def ingest(
    db: AsyncSession,
    vec_engine: AsyncEngine,
    source: Source,
    payload: bytes,
    chunker: TextChunker | None = None,
) -> Source:
    """跑完整条摄取管线。返回更新后的 source。

    ``source`` 必须已经在库里且属于调用方（调用方负责校验）。
    无论成功失败都会更新它的 status——成功是 ``indexed``，
    失败是 ``failed`` + error_message。
    """
    chunker = chunker or TextChunker()

    try:
        blocks = _parse(source, payload)
        await _set_status(db, source, SourceStatus.PARSING, char_count=_total_chars(blocks))

        chunks = chunker.chunk_blocks(blocks)
        await _set_status(db, source, SourceStatus.CHUNKING, chunk_count=len(chunks))

        await _set_status(db, source, SourceStatus.EMBEDDING)
        vectors = await embed_or_none([c.text for c in chunks])
        await _store(db, vec_engine, source, chunks, vectors)
    except (ParseError, ChunkingError, IngestError) as exc:
        # 统一抛 IngestError 而非原样 raise：调用方（HTTP 层）靠这一个类型
        # 区分「用户可见的处理失败」和「代码 bug」。裸 raise 会把 ParseError
        # 漏出去，调用方只能靠字符串猜。
        await mark_failed(db, source, str(exc))
        raise IngestError(str(exc)) from exc
    except Exception as exc:
        logger.exception("摄取 source %s 时发生未预期错误", source.id)
        await mark_failed(db, source, "处理时发生内部错误")
        raise IngestError("处理时发生内部错误") from exc

    await _set_status(db, source, SourceStatus.INDEXED, chunk_count=len(chunks))
    return source


# ── 各阶段 ─────────────────────────────────────────────────
def _parse(source: Source, payload: bytes) -> list[ParsedBlock]:
    return parser_for(source.source_type).parse(payload)


def _total_chars(blocks: Sequence[ParsedBlock]) -> int:
    return sum(len(b.text) for b in blocks)


async def _set_status(
    db: AsyncSession,
    source: Source,
    status: SourceStatus,
    *,
    char_count: int | None = None,
    chunk_count: int | None = None,
) -> None:
    """更新状态并立刻提交——前端轮询时能看到中间进度。"""
    source.status = status
    source.error_message = None
    if char_count is not None:
        source.char_count = char_count
    if chunk_count is not None:
        source.chunk_count = chunk_count
    await db.commit()


async def mark_failed(db: AsyncSession, source: Source, message: str) -> None:
    """写入失败状态。回滚后单独开一次提交，避免污染调用方的事务。

    对外暴露而不只给管线自己用：URL 建源在**抓取**阶段就可能失败
    （超时、404、非 200），那一刻管线还没开始，没人来写 error_message。
    抓取失败与摄取失败对用户是同一种事——「这份资料失败了，原因是 X」，
    所以必须写进同一个字段，轮询端点才能一视同仁。
    """
    await db.rollback()
    source.status = SourceStatus.FAILED
    source.error_message = message
    await db.commit()


async def _store(
    db: AsyncSession,
    vec_engine: AsyncEngine,
    source: Source,
    chunks: Sequence[Chunk],
    vectors: list[list[float]] | None,
) -> None:
    """落库：正文切片 → BM25 全文索引 → 向量。

    顺序有讲究——后两路的索引都用 ``document_chunks.id`` 当 key，
    必须先拿到 chunk 的自增 id。反过来做不到。

    BM25 索引在「没有向量」的分支**之前**建：全文检索不依赖嵌入服务，
    没配 key 时它照样能用。只被 ``vectors is None`` 挡住的话，
    未配置嵌入的部署就只剩向量一路，而那一路是空的——等于没建索引。
    """
    # 建表要在最前面，不受「有没有向量」影响。
    await ensure_index_tables(vec_engine)

    # 重跑摄取时清掉旧切片。否则 chunk_index 唯一约束会撞车。
    # 两张索引表都要**先**删：它们没有外键，等 chunk 行没了就再也查不出
    # 哪些 id 该清，只会留下永远查不到也删不掉的孤儿数据。
    stale = list(
        await db.scalars(select(DocumentChunk.id).where(DocumentChunk.source_id == source.id))
    )
    await purge_index_entries(vec_engine, stale)
    await db.execute(delete(DocumentChunk).where(DocumentChunk.source_id == source.id))
    await db.commit()

    records = [
        DocumentChunk(
            source_id=source.id,
            chunk_index=c.index,
            content=c.text,
            page=c.page,
            start_offset=c.start_offset,
            end_offset=c.end_offset,
            meta={"source_type": source.source_type},
        )
        for c in chunks
    ]
    db.add_all(records)
    await db.commit()

    await bm25.index_chunks(vec_engine, [(r.id, r.content) for r in records])

    if vectors is None:
        # 未配置嵌入 key：正文与全文索引已入库，只有语义检索是空的。
        # 不当失败——用户可能只想存档，等配好 key 再重跑摄取。
        logger.info("source %s 未生成向量（嵌入服务未配置）", source.id)
        return

    await upsert_embeddings(
        vec_engine,
        [(r.id, v) for r, v in zip(records, vectors, strict=True)],
    )


async def ensure_index_tables(vec_engine: AsyncEngine) -> None:
    """确保两张虚表存在——摄取与检索的**唯一**建表入口。

    虚表是运行时建的（Alembic 不认虚表），所以每个碰它们的入口都得先调这个。
    之前分散在 ingest / retriever 两处各写一遍，已经漏了三次
    （「no such table: chunk_embeddings」×2、「no such table: chunk_fts」×1），
    所以收口成这一个函数。
    """
    await ensure_vector_table(vec_engine)
    await bm25.ensure_fts_table(vec_engine)


async def purge_index_entries(vec_engine: AsyncEngine, chunk_ids: Sequence[int]) -> None:
    """删正文切片时同步清两张索引表。都没有外键，必须显式清。"""
    if not chunk_ids:
        return
    await ensure_index_tables(vec_engine)
    ids = ",".join(str(i) for i in chunk_ids)
    async with vec_engine.begin() as conn:
        await conn.exec_driver_sql(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({ids})")
        await conn.exec_driver_sql(f"DELETE FROM chunk_fts WHERE rowid IN ({ids})")
