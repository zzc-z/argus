"""摄取编排的测试。

重点是**失败后的状态**——source 卡在中间态（比如 status 停在 parsing、
旧切片没清掉）比直接报错更难排查。失败必须落库成 failed + error_message。
"""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.services import bm25, vectorstore
from app.services.chunker import TextChunker
from app.services.ingest import IngestError, _clear_stored, ingest, parser_for
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


async def test_embedding_failure_resets_chunk_count(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """嵌入失败后 ``chunk_count`` 必须归零。

    ## 为什么这条重要

    摄取四步里 ``CHUNKING`` 那步已经把 ``chunk_count = len(chunks)`` 提交了
    （21），但嵌入失败发生在 ``_store`` **之前**——切片从未落库。
    不归零的话库里留下「失败 · 21 切片」，实际 ``document_chunks`` 0 行。

    前端 ``toSourceRow`` 按 ``chunk_count > 0`` 渲染「21 切片」，
    用户点进去是空的——**状态自相矛盾，且矛盾的是对外契约**。

    ## 注入回归

    把 ``mark_failed`` 里的 ``source.chunk_count = 0`` 删掉，这条会红。
    """
    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, RuntimeError("上游炸了"))

    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    await db_session.refresh(source)
    assert source.status == SourceStatus.FAILED
    # 失败 = 这份资料一条切片都没有。
    assert source.chunk_count == 0
    # 且真的没有切片行——两者必须一致，不能一个说 0 一个说有。
    assert await DocumentChunk.list_for_source(db_session, source.id) == []


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


async def test_compensation_resets_chunk_count(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补偿要归零 chunk_count——它在 CHUNKING 阶段就已提交，不复位就自相矛盾。

    实测（CR 抓到）：重跑失败后 status=failed、chunk_count=21、实际 0 行。
    状态实际落在四个地方（正文行 / FTS / 向量 / sources.chunk_count），
    补了三处漏了一处。而 chunk_count 是 SourceResponse 的对外字段，
    前端队列监视器直接读它——用户看到「失败」却配着「21 块」。
    """
    db_session, vec_engine = shared_db
    source, baseline = await _seed_and_count(db_session, vec_engine, monkeypatch)
    assert baseline > 0

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("向量写入失败")

    monkeypatch.setattr("app.services.ingest.upsert_embeddings", _boom)
    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())

    await db_session.refresh(source)
    assert source.status == SourceStatus.FAILED
    assert source.chunk_count == 0
    assert await DocumentChunk.list_for_source(db_session, source.id) == []


async def test_compensation_survives_failing_rollback(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rollback 自己抛时，补偿仍要跑完，且异常不外泄。

    ## 为什么必须这样测

    ``db.rollback()`` 会抛——SQLAlchemy 的 ``_rollback_impl`` 末尾显式重抛
    连接层错误。而 DB 真挂（磁盘满、连接被 kill）恰恰是最需要补偿的场景。

    第一版修复把 rollback 提到 try 之外，在这里直接反转：rollback 抛 →
    补偿一行不跑 → 裸 ``raise`` 拿不到原始异常 → ``ingest`` 的 except
    接不住 CancelledError → ``mark_failed`` 不跑 → source 卡在中间态且
    error_message 为空。**修复在它唯一有意义的场景下静默失效。**

    正确做法是包住而不是挪出去（见 ``_rollback_quietly``）。
    """
    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    source = await _make_source(db_session, user)
    _patch_embed(monkeypatch, "vectors")
    await ingest(db_session, vec_engine, source, SAMPLE_TEXT.encode())
    assert source.chunk_count > 0

    real_rollback = AsyncSession.rollback
    state = {"first": True}

    async def _flaky_rollback(self: AsyncSession) -> None:
        # 只让第一次 rollback 抛，模拟「DB 刚挂、随后恢复」。
        if state["first"]:
            state["first"] = False
            raise OperationalError("ROLLBACK", {}, Exception("connection killed"))
        return await real_rollback(self)

    monkeypatch.setattr(AsyncSession, "rollback", _flaky_rollback)

    await _clear_stored(db_session, vec_engine, source.id)  # 不得抛

    assert await DocumentChunk.list_for_source(db_session, source.id) == []
    await db_session.refresh(source)
    assert source.chunk_count == 0


# ── 版本分组：生效版切换只在成功路径 ────────────────────────
async def test_failed_new_version_keeps_old_version_active(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**新版本摄取失败时，旧版必须仍是生效版。**

    ## 为什么这条是整个方案最关键的不变量

    嵌入服务欠费是已知状态（项目记忆里的 embedding-api-arrearage）。
    用户改完简历重新上传，摄取因欠费失败——如果这时把旧版归档了、
    新版切成生效，用户会**同时失去两份可检索资料**：旧版被顶掉，
    新版又根本没建好。

    所以切换必须只发生在摄取成功的路径上。

    ## 在哪种错误实现下也会通过

    只测「成功路径会切换」的实现（``is_active`` 一律为 True）——
    那条路径下旧版根本没被归档，这条照样过。所以这条显式地
    **先建好旧版**（is_active=True），再让新版本摄取失败，
    断言旧版的 ``is_active`` 仍是 True。

    反例实现：在 ``except`` 分支里也调切换（变异测试会红）。
    """
    from app.models import SourceGroup

    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    group = SourceGroup(user_id=user.id)
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    # 存 int 而不是 ORM 对象：后面 expire_all() 会让对象的属性全部过期，
    # 再读 group.id 会触发隐式 SELECT——async 场景下那是 MissingGreenlet。
    group_id = int(group.id)

    old = await _make_source(
        db_session, user, group_id=group_id, is_active=True, version_no=1
    )
    new = await _make_source(
        db_session, user, group_id=group_id, is_active=False, version_no=2
    )

    # 让嵌入服务失败——这是摄取失败最常见的真实成因。
    _patch_embed(monkeypatch, RuntimeError("上游炸了"))

    with pytest.raises(IngestError):
        await ingest(db_session, vec_engine, new, SAMPLE_TEXT.encode())

    db_session.expire_all()
    states = {
        row.id: row.is_active
        for row in (
            await db_session.execute(
                select(Source).where(Source.group_id == group_id)
            )
        ).scalars().all()
    }
    assert states[old.id] is True, "旧版被归档了——新版本还没建好，用户会一份都搜不到"
    assert states[new.id] is False, "摄取失败的新版本不该是生效版"


async def test_successful_new_version_becomes_active_and_archives_old(
    shared_db: tuple[AsyncSession, AsyncEngine],
) -> None:
    """摄取成功后：新版本成为生效版，旧版转归档。

    **在哪种错误实现下也会通过**：只切新版本不归档旧版的实现会撞
    部分唯一索引（组内至多一条生效版）而报错——所以这条顺带验证了
    「先归档后激活」的顺序。
    """
    from app.models import SourceGroup

    db_session, vec_engine = shared_db
    user = await _make_user(db_session)
    group = SourceGroup(user_id=user.id)
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    # 存 int 而不是 ORM 对象：后面 expire_all() 会让对象的属性全部过期，
    # 再读 group.id 会触发隐式 SELECT——async 场景下那是 MissingGreenlet。
    group_id = int(group.id)

    old = await _make_source(
        db_session, user, group_id=group_id, is_active=True, version_no=1
    )
    new = await _make_source(
        db_session, user, group_id=group_id, is_active=False, version_no=2
    )

    await ingest(db_session, vec_engine, new, SAMPLE_TEXT.encode())

    db_session.expire_all()
    states = {
        row.id: row.is_active
        for row in (
            await db_session.execute(
                select(Source).where(Source.group_id == group_id)
            )
        ).scalars().all()
    }
    assert states[new.id] is True
    assert states[old.id] is False
