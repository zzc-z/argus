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

from sqlalchemy import delete, select, update
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

    ## 跨连接写入只能补偿，不能回滚

    ``db`` 与 ``vec_engine`` 是两条独立连接（后者加载了 sqlite-vec 扩展，
    不能并进业务连接）。跨连接就没有一个 SQLite 事务能同时覆盖它们，
    所以任一步失败时都**不能回滚**——已经提交的 chunk 行收不回来。

    这不是可以接受的：``ingest`` 捕获异常后把 source 标成 failed，用户
    重传就好；但旧切片在第 1 步就被删了。失败一次，这份资料就变成
    「一条正文都没有、但状态是 failed」——重传之前它彻底不可检索，
    而用户看到的是「之前能搜到的资料突然搜不到了」。

    代价由 :func:`_clear_stored` 兜住：任何一步失败都退回到**这份资料
    一条切片都没有**的状态。比半截状态好——至少「没有就是没有」，
    用户重传即刻恢复。做不到的是「失败不影响旧版本」，那需要新旧共存，
    而 ``ux_document_chunks_source_index`` 唯一索引恰好禁止（见 ``_clear_stored``）。
    """
    # 建表要在最前面，不受「有没有向量」影响。
    await ensure_index_tables(vec_engine)

    try:
        records = await _replace_chunks(db, vec_engine, source, chunks)
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
    except BaseException:
        # BaseException 而非 Exception：CancelledError 在 Python 3.8+ 起继承自
        # BaseException，进程关闭 / 任务被 cancel 时走不到上面的分支。
        # 那正是运维最常见的操作（滚动重启），而此时旧切片已删、新切片已提交、
        # 索引可能只写了一半——不留补偿就是货真价实的半截状态，且没有日志
        # （异常直接穿到 asyncio，只留下一句 "Task exception was never retrieved"）。
        await _clear_stored(db, vec_engine, source.id)
        raise


async def _replace_chunks(
    db: AsyncSession,
    vec_engine: AsyncEngine,
    source: Source,
    chunks: Sequence[Chunk],
) -> list[DocumentChunk]:
    """把这份资料的切片整个换成新的，返回落库后的记录（含自增 id）。

    重跑摄取必须先删旧的，否则 chunk_index 唯一约束会撞车。
    两张索引表都要**先**删：它们没有外键，等 chunk 行没了就再也查不出
    哪些 id 该清，只会留下永远查不到也删不掉的孤儿数据。
    """
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
    return records


async def _clear_stored(db: AsyncSession, vec_engine: AsyncEngine, source_id: int) -> None:
    """把一份资料退回「零切片」状态。失败时调用，**绝不向外抛**。

    ## rollback 的正确位置：包住，不是挪出去

    这里改过两次，两次都是错的：

    1. 原版 rollback 在 try 里第一行。原始异常来自 ``db`` 本身时
       （commit 撞 IntegrityError、库被锁、磁盘满），SQLAlchemy 2.0 会把
       session 标记 ``is_active=False``，此后任何 db 操作都抛
       ``PendingRollbackError``——包括 rollback 自己。补偿一行不跑。
    2. 改成「提到 try 之前」。方向反了：``_rollback_impl`` 末尾显式重抛
       连接层错误，DB 真挂时 rollback 照样抛 → 补偿一行不跑 + 裸 ``raise``
       拿不到原始异常 → ``ingest`` 的 except 接不住 CancelledError →
       ``mark_failed`` 不跑 → source 卡在中间态且 error_message 为空。

    正确做法是让 rollback 走 :func:`_rollback_quietly`：调用要早（先救回
    session 才有资格查），但失败必须吞（清理代码不能顶掉原始异常）。

    ## 绝不外抛

    它跑在 ``except`` 里，任何逸出的异常都会替换掉原始异常——而那正是
    排查要的。同时也是取消信号能传到 ``asyncio`` 的前提（见
    ``gateway/research.py`` 里的同类告诫）。

    ## 为什么是零切片而不是旧切片

    想做到「失败也不影响旧版本」，新切片得与旧切片并存——但
    ``ux_document_chunks_source_index`` (source_id, chunk_index) 唯一，
    新旧同序号直接撞车。真要并存得给切片加版本号，那是动 schema 的改造，
    超出「补上补偿」的范围。

    零切片是**有损**的：重跑在插新切片那步失败，旧版本已经没了（`_replace_chunks`
    第一步就是删旧）。这是「先删后插」这个顺序的固有代价，唯一索引挡住了
    「先插后删」。用户重传即恢复。

    ## 为什么按 source_id 删而不是按本轮 records 的 id 删

    按 id 精确删更安全——不会误伤并发摄取的另一份写入。但当前 HTTP 面没有
    「对已有 source 重跑」的入口，每次建源只调度一次，所以并发写同一
    source 走不到。按 source_id 删能让补偿在「异常发生前 records 还没算完」
    的场景下也有意义（那时手上没有 id 列表）。若将来加了重跑端点，必须同时
    给摄取加 per-source 锁，否则这里会删掉别人刚提交的成功数据。
    """
    await _rollback_quietly(db)
    try:
        stale = list(
            await db.scalars(select(DocumentChunk.id).where(DocumentChunk.source_id == source_id))
        )
        await purge_index_entries(vec_engine, stale)
        await db.execute(delete(DocumentChunk).where(DocumentChunk.source_id == source_id))
        # chunk_count 必须一起归零：它在 ingest 流程里已随 CHUNKING 阶段提交，
        # 不复位就留下「status=failed 但 chunk_count=21、实际 0 行」的自相矛盾，
        # 而 SourceResponse.chunk_count 是直接下发给前端队列监视器的对外契约。
        await db.execute(update(Source).where(Source.id == source_id).values(chunk_count=0))
        await db.commit()
    except Exception:
        await _rollback_quietly(db)
        logger.exception("source %s 补偿清理失败，可能残留半截切片", source_id)


async def _rollback_quietly(db: AsyncSession) -> None:
    """回滚，失败也吞掉。

    ## 为什么必须吞

    补偿跑在异常处理里，它抛出的异常会**顶掉原始异常**——而原始异常才是
    排查要的。更糟的是 ``db.rollback()`` 真的会抛：SQLAlchemy 的
    ``SessionTransaction._rollback_impl`` 末尾显式重抛连接层错误
    （``session.py`` 里 ``if rollback_err and rollback_err[1]: raise``）。

    而 DB 真挂（磁盘满、连接被 kill）恰恰是最需要补偿的场景。于是最初
    那版「把 rollback 提到 try 之外」在这里反转：rollback 抛 → 补偿一行
    不跑 → 裸 ``raise`` 拿不到原始异常 → ``ingest`` 的 except 接不住
    CancelledError → ``mark_failed`` 不跑 → source 卡在中间态且
    ``error_message`` 为空，用户看不到任何可诊断信息。

    对比 ``gateway/research.py`` 里同类的告诫（「别把 except 改成
    BaseException：那会吞掉取消信号」）——那里靠裸 ``raise`` 保住信号，
    这里则是靠**不让清理代码把信号吃掉**。
    """
    try:
        await db.rollback()
    except Exception:
        logger.debug("回滚失败，session 已不可用", exc_info=True)


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
