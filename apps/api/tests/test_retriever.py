"""混合检索的测试。

RRF 融合用纯函数单测（分数数学不依赖数据库）；端到端那部分打桩嵌入，
只验「向量 + BM25 两路都参与」「私域隔离」这两件结构性的事。
"""

from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.services import bm25, retriever, vectorstore
from app.services.bm25 import Bm25Hit
from app.services.ingest import ensure_index_tables
from app.services.retriever import RRF_K, Retrieved, _rrf_fuse
from app.services.vectorstore import create_vector_engine

CHINESE_DOCS = [
    "NVIDIA Blackwell 架构能效比 Hopper 提升 2.5 倍，能效是新一代的核心指标",
    "公司本季度营业收入 32.1 亿美元，同比增长 22%",
    "数据中心电力消耗锐减 75%，算力供给成为新瓶颈",
]


def _patch_embed(monkeypatch: pytest.MonkeyPatch, vectors: list[list[float]] | None) -> None:
    """打桩嵌入。``None`` 表示模拟未配置 key。"""

    async def _fake(_texts):  # type: ignore[no-untyped-def]
        if vectors is None:
            from app.services.embedder import EmbeddingNotConfiguredError

            raise EmbeddingNotConfiguredError("未配置")
        return vectors

    monkeypatch.setattr("app.services.embedder.embed_texts", _fake)


async def _seed_user_and_source(db: AsyncSession, email: str) -> tuple[int, int]:
    user = User(email=email, display_name="t")
    db.add(user)
    await db.flush()
    source = Source(
        user_id=user.id,
        title="测试研报",
        source_type=SourceType.TEXT,
        status=SourceStatus.INDEXED,
    )
    db.add(source)
    await db.commit()
    await db.refresh(user)
    await db.refresh(source)
    return user.id, source.id


# ── RRF 数学（纯函数）──────────────────────────────────────
def test_rrf_scores_descend() -> None:
    fused = _rrf_fuse([(1, 0.1), (2, 0.5)], [])

    scores = [s for _, s, _, _ in fused]
    assert scores == sorted(scores, reverse=True)


def test_rrf_ranks_start_at_one() -> None:
    """排名从 1 起——0 会被 k 抵消，写进 Retrieved 也没法让用户看懂。"""
    fused = _rrf_fuse([(7, 0.1), (8, 0.2)], [])

    ranks = {cid: vr for cid, _, vr, _ in fused}
    assert ranks[7] == 1
    assert ranks[8] == 2


def test_rrf_rewards_appearing_in_both_lists() -> None:
    """两路都命中的文档分数更高——这是混合检索的核心收益。"""
    only_vector = _rrf_fuse([(1, 0.1)], [])
    both = _rrf_fuse([(2, 0.1)], [Bm25Hit(chunk_id=2, score=-1.0)])
    only_bm25 = _rrf_fuse([], [Bm25Hit(chunk_id=3, score=-1.0)])

    def first_score(rows: list[tuple[int, float, int | None, int | None]]) -> float:
        return rows[0][1]

    assert first_score(both) > first_score(only_vector)
    assert first_score(both) > first_score(only_bm25)


def test_rrf_head_is_damped_by_k() -> None:
    """第 1 名不该赢第 10 名十倍——k=60 的作用。"""
    first = _rrf_fuse([(1, 0.0)], [])[0][1]
    tenth = _rrf_fuse([(1, 0.0)] * 1, [])[0][1]  # 单条，用于对照

    assert first == pytest.approx(1.0 / (RRF_K + 1))
    assert tenth == pytest.approx(first)


def test_rrf_merges_and_dedupes() -> None:
    """同一 chunk_id 在两路都出现只算一条。"""
    fused = _rrf_fuse([(5, 0.1)], [Bm25Hit(chunk_id=5, score=-1.0)])

    assert len(fused) == 1
    _, _, v_rank, b_rank = fused[0]
    assert v_rank == 1 and b_rank == 1


def test_rrf_with_empty_inputs() -> None:
    assert _rrf_fuse([], []) == []


def test_rrf_records_which_list_hit() -> None:
    """要能看出命中来源——前端要标注「来自向量召回」还是「关键词命中」。"""
    fused = _rrf_fuse([(1, 0.1), (2, 0.2)], [Bm25Hit(chunk_id=2, score=-1.0)])

    by_id = {cid: (v, b) for cid, _, v, b in fused}
    assert by_id[1] == (1, None)
    assert by_id[2] == (2, 1)


# ── 端到端 helper ──────────────────────────────────────────
async def _seed(
    db: AsyncSession, contents: Sequence[str]
) -> tuple[int, int, list[DocumentChunk]]:
    """建一个用户 + 一份资料 + N 条切片，返回 (user_id, source_id, chunks)。"""
    uid, sid = await _seed_user_and_source(db, "seed@t.local")
    rows = [
        DocumentChunk(source_id=sid, chunk_index=i, content=text, page=i + 1)
        for i, text in enumerate(contents)
    ]
    db.add_all(rows)
    await db.commit()
    for r in rows:
        await db.refresh(r)
    return uid, sid, rows


async def _index(engine: AsyncEngine, rows: Sequence[DocumentChunk]) -> None:
    """同时建 BM25 与向量两路索引。"""
    await ensure_index_tables(engine)
    await bm25.index_chunks(engine, [(r.id, r.content) for r in rows])
    await vectorstore.upsert_embeddings(
        engine, [(r.id, [0.5] * 1536) for r in rows]
    )


# ── 端到端 ────
async def test_retrieve_returns_chunks(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    uid, sid, rows = await _seed(db_session, CHINESE_DOCS)
    await _index(vec_engine, rows)
    _patch_embed(monkeypatch, [[0.5] * 1536])

    got = await retriever.retrieve(db_session, vec_engine, "能效", user_id=uid, limit=5)

    assert got
    assert all(isinstance(r, Retrieved) for r in got)
    assert all(r.source.id == sid for r in got)


async def test_retrieve_isolates_users(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """最关键的一条：查不到别人的资料。"""
    db_session, vec_engine = shared_db
    my_id, _ = await _seed_user_and_source(db_session, "mine@t.local")
    other_id, other_source = await _seed_user_and_source(db_session, "other@t.local")

    theirs = DocumentChunk(source_id=other_source, chunk_index=0, content="他的资料 能效")
    db_session.add(theirs)
    await db_session.commit()
    await db_session.refresh(theirs)

    await _index(vec_engine, [theirs])
    _patch_embed(monkeypatch, [[0.5] * 1536])

    # 我的账号一条资料都没有 → 什么都检索不到，更拿不到他的
    got = await retriever.retrieve(db_session, vec_engine, "能效", user_id=my_id, limit=10)

    assert got == []
    assert theirs.id not in [r.chunk.id for r in got]
    assert other_id != my_id


async def test_retrieve_excludes_other_users_chunks(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两人都有资料时，只返回自己的那一条。"""
    db_session, vec_engine = shared_db
    my_id, my_source = await _seed_user_and_source(db_session, "mine2@t.local")
    _other, other_source = await _seed_user_and_source(db_session, "other2@t.local")

    mine = DocumentChunk(source_id=my_source, chunk_index=0, content="我的资料 能效")
    theirs = DocumentChunk(source_id=other_source, chunk_index=0, content="他的资料 能效")
    db_session.add_all([mine, theirs])
    await db_session.commit()
    await db_session.refresh(mine)
    await db_session.refresh(theirs)

    await _index(vec_engine, [mine, theirs])
    _patch_embed(monkeypatch, [[0.5] * 1536])

    got = await retriever.retrieve(db_session, vec_engine, "能效", user_id=my_id, limit=10)

    assert [r.chunk.id for r in got] == [mine.id]


async def test_retrieve_empty_for_user_without_sources(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没资料的用户不该触发外部调用——先短路。"""
    db_session, vec_engine = shared_db
    user = User(email="fresh@t.local", display_name="f")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    def _boom(*_a, **_k):  # pragma: no cover — 不该被调到
        raise AssertionError("没有资料时不该调嵌入服务")

    monkeypatch.setattr("app.services.embedder.embed_texts", _boom)

    assert await retriever.retrieve(db_session, vec_engine, "x", user_id=user.id) == []


async def test_retrieve_survives_missing_embedding_key(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没配 key 时降级成纯 BM25，不该整体失败。"""
    db_session, vec_engine = shared_db
    uid, _sid, rows = await _seed(db_session, ["能效提升的关键路径 与成本分析"])
    await _index(vec_engine, rows)
    _patch_embed(monkeypatch, None)

    got = await retriever.retrieve(db_session, vec_engine, "能效", user_id=uid)

    assert [r.chunk.id for r in got] == [rows[0].id]
    assert got[0].vector_rank is None
    assert got[0].bm25_rank == 1


async def test_retrieve_limit_respected(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session, vec_engine = shared_db
    uid, _sid, rows = await _seed(
        db_session, [f"能效 第 {i} 段" for i in range(5)]
    )
    await _index(vec_engine, rows)
    _patch_embed(monkeypatch, None)

    got = await retriever.retrieve(db_session, vec_engine, "能效", user_id=uid, limit=2)

    assert len(got) <= 2


async def test_bm25_rescues_proper_noun_missed_by_vector(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """混合检索的核心价值：向量漏掉的专有名词，BM25 捞回来。

    构造一个「向量必然排错」的场景——所有向量都相同（相似度无区分度），
    只有 BM25 能靠关键词分出高下。纯向量检索在这个场景下会丢命。
    """
    db_session, vec_engine = shared_db
    uid, _sid, rows = await _seed(
        db_session,
        [
            "无关的内容，纯粹占位",
            "H100 的规格与供货情况",
            "另一段无关内容",
        ],
    )
    await ensure_index_tables(vec_engine)
    await bm25.index_chunks(vec_engine, [(r.id, r.content) for r in rows])
    await vectorstore.upsert_embeddings(
        vec_engine, [(r.id, [0.5] * 1536) for r in rows]
    )
    # 查询向量刻意远离所有文档向量：向量那路的正确答案是「都不相关」
    _patch_embed(monkeypatch, [[-0.5] * 1536])

    got = await retriever.retrieve(db_session, vec_engine, "H100", user_id=uid, limit=3)

    assert got[0].chunk.id == rows[1].id
    assert got[0].bm25_rank == 1
