"""摄取编排的测试。

重点是**失败后的状态**——source 卡在中间态（比如 status 停在 parsing、
旧切片没清掉）比直接报错更难排查。失败必须落库成 failed + error_message。
"""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.services import bm25, vectorstore
from app.services.chunker import TextChunker
from app.services.ingest import IngestError, ingest, parser_for
from app.services.vectorstore import create_vector_engine

PDF_BYTES = b""  # 占位；PDF 路径在 test_ingest_pdf 里现场生成


@pytest.fixture
async def vec_engine(tmp_path) -> AsyncEngine:
    engine = create_vector_engine(f"sqlite+aiosqlite:///{tmp_path / 'ingest.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(_create_schema)
    yield engine
    await engine.dispose()


def _create_schema(metadata: Any) -> None:
    from app.models import Base

    Base.metadata.create_all(metadata)


async def _make_user(db: AsyncSession) -> User:
    user = User(email="ingest@test.local", display_name="t")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_source(db: AsyncSession, user: User, **kw: Any) -> Source:
    data: dict[str, Any] = {
        "title": "测试资料",
        "source_type": SourceType.TEXT,
        "status": SourceStatus.PENDING,
    }
    data.update(kw)
    source = Source(user_id=user.id, **data)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


def _patch_embed(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    """把 embed_or_none 换成固定返回值。``value`` 若是 list 则原样返回。"""

    async def _fake(texts: Any) -> Any:
        if isinstance(value, Exception):
            raise value
        if value == "no_vectors":
            return None
        return [[0.5] * 1536 for _ in texts]

    monkeypatch.setattr("app.services.ingest.embed_or_none", _fake)


SAMPLE_TEXT = (
    "2024 年 NVIDIA 发布 Blackwell 架构。该架构采用台积电定制 4NP 工艺，"
    "相比上一代提升约 2.5 倍能效。\f"
    "第二章 技术细节。Blackwell Ultra 版本将于 2025 年推出，"
    "在推理场景中大语言模型的吞吐量是核心指标。"
)


# ── 正常路径 ───────────────────────────────────────────────
async def test_ingest_indexes_text_source(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    assert source.status == SourceStatus.INDEXED
    assert source.error_message is None
    assert source.char_count > 0
    assert source.chunk_count > 0
    assert len(await DocumentChunk.list_for_source(db_session, source.id)) == source.chunk_count


async def test_ingest_writes_vectors(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    chunks = await DocumentChunk.list_for_source(db_session, source.id)
    hits = await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=100, source_ids=[source.id])
    assert len(hits) == len(chunks)


async def test_chunks_carry_page_numbers(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    """页码要一路带到 chunk 上——引用写 [1, p.3] 全靠它。"""
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    pages = {c.page for c in await DocumentChunk.list_for_source(db_session, source.id)}
    assert pages == {1, 2}


async def test_without_embedding_key_still_indexes_text(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    """没配 key 时正文仍要入库——用户可能只想存档，不该整份失败。"""
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, "no_vectors")

    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    assert source.status == SourceStatus.INDEXED
    assert len(await DocumentChunk.list_for_source(db_session, source.id)) > 0
    assert (
        await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=10, source_ids=[source.id])
        == []
    )


# ── 重跑 ───────────────────────────────────────────────────
async def test_reingest_replaces_chunks_not_duplicates(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    """重跑要替换而不是叠加——chunk_index 唯一约束会撞车。"""
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())
    first_count = source.chunk_count
    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    chunks = await DocumentChunk.list_for_source(db_session, source.id)
    assert len(chunks) == first_count
    assert [c.chunk_index for c in chunks] == list(range(first_count))


async def test_reingest_purges_orphan_vectors(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    """重跑时旧向量要清掉——向量表没有外键，留着就是永久孤儿。"""
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())
    stale_count = len(
        await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=100, source_ids=[source.id])
    )

    _patch_embed(monkeypatch, "no_vectors")
    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    assert (
        await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=100, source_ids=[source.id])
        == []
    )
    assert stale_count > 0


# ── 失败路径 ───────────────────────────────────────────────
async def test_parse_failure_is_recorded_on_source(
    db_session: AsyncSession,
    vec_engine: AsyncEngine,
) -> None:
    """解析失败要留在库里，否则用户只看到请求超时，无从重试。"""
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)

    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, b"")

    await db_session.refresh(source)
    assert source.status == SourceStatus.FAILED
    assert source.error_message


async def test_embedding_failure_marks_failed(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, RuntimeError("上游炸了"))

    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    await db_session.refresh(source)
    assert source.status == SourceStatus.FAILED


async def test_failure_does_not_leak_internal_details(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    """未预期的错误不能把内部异常信息透给用户。"""
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, RuntimeError("数据库密码是 hunter2"))

    with pytest.raises(IngestError) as exc:
        await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    assert "hunter2" not in str(exc.value)
    await db_session.refresh(source)
    assert "hunter2" not in (source.error_message or "")


async def test_failed_source_can_be_retried(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    """失败后重传要能成功——error_message 要被清掉。"""
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)

    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, b"")
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    await db_session.refresh(source)
    assert source.status == SourceStatus.INDEXED
    assert source.error_message is None


# ── 类型分派 ───────────────────────────────────────────────
def test_parser_for_known_types() -> None:
    assert parser_for(SourceType.PDF) is not None
    assert parser_for(SourceType.HTML) is not None
    assert parser_for(SourceType.TEXT) is not None


def test_parser_for_unknown_type_raises() -> None:
    """未知类型要报错，不能退化成纯文本硬解——那会产出垃圾。"""
    with pytest.raises(IngestError, match="暂不支持"):
        parser_for("mp4")


async def test_ingest_pdf(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    """PDF 端到端。现场生成真 PDF，不用固定字节流。"""
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Page one: Blackwell efficiency.", fontsize=12)
    doc.new_page().insert_text((72, 100), "Page two: revenue grew 22 percent.", fontsize=12)
    pdf = doc.tobytes()
    doc.close()

    user = await _make_user(db_session)
    source = await _make_source(db_session, user, source_type=SourceType.PDF)
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, source, pdf)

    chunks = await DocumentChunk.list_for_source(db_session, source.id)
    assert chunks
    assert "Blackwell" in "".join(c.content for c in chunks)


# ── 跨连接写入的补偿 ─────────────────────────────────────────
async def _seed_and_count(
    db: AsyncSession,
    vec_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Source, int]:
    """先成功摄取一遍，返回 source 与切片数。用作重跑被破坏前的基线。"""
    user = await _make_user(db)
    source = await _make_source(db, user)
    _patch_embed(monkeypatch, "vectors")
    await ingest(db, vec_engine, source, SAMPLE_TEXT.encode())
    return source, source.chunk_count


@pytest.mark.parametrize("broken_step", ["bm25", "vectors"])
async def test_failed_reingest_leaves_no_partial_chunks(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
    broken_step: str,
) -> None:
    """重跑中途失败，不能留下「有正文、没索引」的半截状态。

    正文行在第 2 步就已提交，索引在第 3、4 步才写进**另一条连接**。
    失败时没有跨连接事务可回滚，只能由补偿把这份资料退回零切片。

    半截状态比零切片危险：source 会被标成 failed，但库里明明还有正文行，
    检索时正文查得到、向量查不到，两路结果对不上，且没有任何报错指向它。
    """
    db_session, vec_engine = shared_db
    source, baseline = await _seed_and_count(db_session, vec_engine, monkeypatch)
    assert baseline > 0

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("索引写入失败")

    target = (
        "app.services.ingest.bm25.index_chunks"
        if broken_step == "bm25"
        else "app.services.ingest.upsert_embeddings"
    )
    monkeypatch.setattr(target, _boom)

    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    assert await DocumentChunk.list_for_source(db_session, source.id) == []


async def _fts_row_count(vec_engine: AsyncEngine) -> int:
    """直接数 FTS 虚表里的行数——经 ``bm25.search`` 查会漏掉孤儿。

    检索按 ``source_ids`` 走 ``document_chunks`` 子查询，孤儿行天然查不到，
    所以「搜不到」证明不了「不存在」。这里绕开检索直接读表。
    """
    from sqlalchemy import text

    async with vec_engine.connect() as conn:
        result = await conn.execute(text(f"SELECT count(*) FROM {bm25.FTS_TABLE}"))
        return int(result.scalar_one())


async def test_failed_reingest_leaves_no_orphan_index_entries(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补偿要同时清两张索引表——它们没有外键，清不掉的行永远查不到也删不掉。

    断点选在**向量写入**失败：此时正文行已提交、BM25 索引已写入，
    只有向量是空的。补偿若只清正文不清索引，FTS 里就留下一批指向
    已删 chunk_id 的行——它们永远不会被检索命中，却一直占着表，
    且让「FTS 行数 == 正文行数」这个不变式彻底失效。

    断点不选 bm25：它失败时两张索引表都还是上一轮的（已被 purge 清空），
    断言「为空」会无条件通过，测不到任何东西。
    """
    db_session, vec_engine = shared_db
    source, baseline = await _seed_and_count(db_session, vec_engine, monkeypatch)
    assert await _fts_row_count(vec_engine) == baseline

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("向量写入失败")

    monkeypatch.setattr("app.services.ingest.upsert_embeddings", _boom)
    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    assert await _fts_row_count(vec_engine) == 0
    assert (
        await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=100, source_ids=[source.id])
        == []
    )


async def test_compensation_does_not_touch_other_sources(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补偿只清失败的那份资料，别人的资料必须完好。

    单 source 的用例看不见这类越界：库里只有一份资料时，「全清」与
    「精确清」结果完全一样。但用户库里同时躺着几十份资料，一份重传失败
    把别人的索引全purge 掉——那些资料的正文行还在、向量索引没了，
    两路检索结果对不上，且没有任何报错指向它。

    比这更隐蔽的是正文：``delete(...).where(source_id == ...)`` 写对了
    就不会波及，而索引那一步走的是 ``chunk_id`` 列表，少一个 where 就
    变成按整表清。
    """
    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    victim = await _make_source(db_session, user, title="受害者")
    bystander = await _make_source(db_session, user, title="旁观者")
    _patch_embed(monkeypatch, "vectors")

    await ingest(db_session, vec_engine, victim, SAMPLE_TEXT.encode())
    await ingest(db_session, vec_engine, bystander, SAMPLE_TEXT.encode())
    bystander_chunks = bystander.chunk_count
    assert bystander_chunks > 0

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("向量写入失败")

    monkeypatch.setattr("app.services.ingest.upsert_embeddings", _boom)
    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, victim, SAMPLE_TEXT.encode())

    assert await DocumentChunk.list_for_source(db_session, victim.id) == []
    assert len(await DocumentChunk.list_for_source(db_session, bystander.id)) == bystander_chunks
    assert (
        len(
            await vectorstore.knn_search(
                vec_engine, [0.5] * 1536, limit=100, source_ids=[bystander.id]
            )
        )
        == bystander_chunks
    )


async def test_reingest_after_compensation_recovers_fully(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补偿之后重传要能完全恢复，且两份索引与正文重新对齐。

    原本这里只断言「重传成功」——那测不到补偿，因为重传路径**本来**就能
    自己清干净（purge 旧行、按新 id 写索引）。补偿写坏了也不影响重传成功，
    用户不会卡住，只是拿到一份切片 id 与索引对不上的资料。

    所以断言落在不变式上：FTS 行数 == 正文行数 == 向量命中数。
    少了是补偿清过头（重传后少了一部分切片可检索），多了是残留孤儿
    （切片在库里却永远搜不到）。两种错位都不会以任何方式报错。
    """
    db_session, vec_engine = shared_db
    source, baseline = await _seed_and_count(db_session, vec_engine, monkeypatch)

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("向量写入失败")

    monkeypatch.setattr("app.services.ingest.upsert_embeddings", _boom)
    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    monkeypatch.undo()
    _patch_embed(monkeypatch, "vectors")
    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    chunks = await DocumentChunk.list_for_source(db_session, source.id)
    hits = await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=100, source_ids=[source.id])
    assert len(chunks) == baseline
    assert len(hits) == baseline
    assert await _fts_row_count(vec_engine) == baseline
