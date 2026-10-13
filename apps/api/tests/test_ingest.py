"""摄取编排的测试。

重点是**失败后的状态**——source 卡在中间态（比如 status 停在 parsing、
旧切片没清掉）比直接报错更难排查。失败必须落库成 failed + error_message。
"""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.services import vectorstore
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
    assert await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=10, source_ids=[source.id]) == []


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
    stale_count = len(await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=100, source_ids=[source.id]))

    _patch_embed(monkeypatch, "no_vectors")
    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    assert await vectorstore.knn_search(vec_engine, [0.5] * 1536, limit=100, source_ids=[source.id]) == []
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
