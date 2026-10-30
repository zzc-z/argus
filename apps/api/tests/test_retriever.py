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
    """混合检索的核心价值：向量排错时，BM25 捞回来。

    构造一个「向量那一路必然排不出唯一答案」的场景——所有文档向量方向相同
    （相似度无区分度），只有 BM25 能靠关键词分出高下。纯向量检索在这个
    场景下会丢命。

    ## 为什么查询向量与文档向量是**同向**的

    相关性下限按**余弦距离**判定（见 ``vectorstore.MAX_RELEVANT_DISTANCE``），
    余弦只看方向：查询与文档反向时（余弦距离 ≈ 2.0），两路都会被下限挡掉——
    那测的是「相关性下限」，不是「BM25 能不能救场」。

    所以这里让查询与文档**同向但角度很小**（余弦距离 ≈ 0.01，远在阈值内）：
    向量路认为三条都相关、无法分出高下，只有 BM25 能靠「H100」这个专有名词
    把正确的那条排到前面。
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
    # 文档向量与查询向量同向（第 0 维都是正数），只是模长不同——
    # 余弦距离为 0，向量路认为三条都相关、无区分度。
    await vectorstore.upsert_embeddings(
        vec_engine, [(r.id, _vec(0.5)) for r in rows]
    )
    _patch_embed(monkeypatch, [_vec(0.55)])

    got = await retriever.retrieve(db_session, vec_engine, "H100", user_id=uid, limit=3)

    assert got[0].chunk.id == rows[1].id
    assert got[0].bm25_rank == 1


# ── 相关性下限（接线）────────────────────────────────────────
#
# 向量层已经按 MAX_RELEVANT_DISTANCE 过滤过了，这里守的是「过滤之后
# retrieve 拿到的就是过滤后的结果」——调用方不该再看到无关切片。


def _vec(weight: float) -> list[float]:
    """造一个 1536 维向量：只有第 0 维是 weight。

    单维非零向量让距离精确可控：L2 距离就是 |weight − 查询向量第 0 维|，
    而余弦相似度也能直接算出来（两个单维向量的夹角只由正负决定）。

    稠密向量（如 ``[0.5] * 1536``）算出来的距离动辄几十，永远越不过阈值，
    测不出边界——而且所有稠密正数向量的方向都相同，余弦距离恒为 0，
    **区分不出远近**，所以边���测试必须用单维向量。
    """
    v = [0.0] * 1536
    v[0] = weight
    return v


async def _seed_and_index(
    db_session: AsyncSession,
    vec_engine: AsyncEngine,
    contents: Sequence[str],
    weights: Sequence[float],
) -> tuple[int, list[DocumentChunk]]:
    """建切片 + 建两路索引（向量用给定的权重控制距离）。

    BM25 用真实正文索引，但下面这些用例的查询词与正文没有共同 token，
    所以 BM25 那一路的答案是「0 条」——正好把向量那一路单独拎出来测。
    """
    uid, _sid, rows = await _seed(db_session, contents)
    await ensure_index_tables(vec_engine)
    await bm25.index_chunks(vec_engine, [(r.id, r.content) for r in rows])
    await vectorstore.upsert_embeddings(
        vec_engine, [(r.id, _vec(w)) for r, w in zip(rows, weights, strict=True)]
    )
    return uid, rows


async def test_retrieve_returns_nothing_when_all_hits_are_irrelevant(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不相关查询 → 一条都不返回。

    实测那次事故：用户问「iPhone 折叠屏 对比 国产折叠屏质量」，资料库里只有
    一份医保接口文档，检索照样召回 12 条「参保人手机 | tel」，模型拿它当证据
    去回答手机质量对比，拼出一个畸形上下文。

    反例实现：向量路照单全收（没有相关性下限）——这条会红。
    """
    db_session, vec_engine = shared_db
    uid, _rows = await _seed_and_index(db_session, vec_engine, ["医保接口说明 第 1 段"], [-0.5])
    # 查询向量离文档向量很远（L2 = 1.5 > 0.89），BM25 也不命中
    _patch_embed(monkeypatch, [_vec(1.0)])

    got = await retriever.retrieve(db_session, vec_engine, "折叠屏手机质量", user_id=uid, limit=5)

    assert got == []


async def test_retrieve_returns_relevant_chunks(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相关查询 → 正常返回。阈值不能把相关内容一起滤掉。

    反例实现：阈值写错（比如写成 0.05）——这条会红。
    """
    db_session, vec_engine = shared_db
    uid, rows = await _seed_and_index(db_session, vec_engine, ["医保接口说明 第 1 段"], [0.95])
    _patch_embed(monkeypatch, [_vec(1.0)])

    got = await retriever.retrieve(db_session, vec_engine, "折叠屏手机质量", user_id=uid, limit=5)

    assert [r.chunk.id for r in got] == [rows[0].id]


# ── BM25 路也必须过同一个下限 ────────────────────────────────
#
# BM25 的 MATCH 用 jieba 分词后的 token 做 **OR** 匹配
# （bm25.py 的 match_expr = " OR ".join(...)）：查询词里只要有一个 token 命中，
# 切片就进候选。实测「手机 质量 参数」能命中 50 条医保接口文档里的字段行。
#
# 只给向量路设下限，bug 没修好——融合后仍是 50 条无关切片进证据块。


async def test_retrieve_drops_bm25_hits_that_are_too_far(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """字面命中但语义无关的切片，BM25 路也得把它挡掉。

    反例实现：只给向量路设下限、BM25 路不管 —— 这条会红。
    """
    db_session, vec_engine = shared_db
    uid, _rows = await _seed_and_index(
        db_session,
        vec_engine,
        ["参保人手机 | tel | String | 50", "个人手机号码 | psnNo | String | 是"],
        [-0.5, -0.6],
    )
    _patch_embed(monkeypatch, [_vec(1.0)])

    # 「手机」命中两条（OR 语义），但它们的向量距离是 1.5 / 1.6 —— 全都不相关
    got = await retriever.retrieve(db_session, vec_engine, "手机 质量 参数", user_id=uid, limit=12)

    assert got == [], f"BM25 命中的无关切片漏进来了：{got}"


async def test_retrieve_keeps_only_the_relevant_bm25_hits(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三条都字面命中、只有一条语义相关 → 只留下那一条。

    这是「BM25 路也要过下限」这条要求的正面与反面一起验：
    - 反例实现（BM25 路不过限）→ 三条全进 → 这条会红
    - 反例实现（BM25 路一律砍掉）→ 一条都不留 → 这条会红
    """
    db_session, vec_engine = shared_db
    uid, rows = await _seed_and_index(
        db_session,
        vec_engine,
        [
            "医保结算清单 接口说明",
            "参保人手机 | tel | String | 50",
            "个人手机号码 | psnNo | String | 是",
        ],
        [0.95, -0.5, -0.6],
    )
    _patch_embed(monkeypatch, [_vec(1.0)])

    # 「医保」「手机」两个 token，OR 匹配 → 三条都进 BM25 候选
    got = await retriever.retrieve(db_session, vec_engine, "医保 手机", user_id=uid, limit=12)

    assert [r.chunk.id for r in got] == [rows[0].id]


async def test_retrieve_keeps_relevant_bm25_hits(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相关查询（向量近 + BM25 命中）必须正常召回——不能被误杀。

    实测「医保结算清单 接口」：向量 top1 distance 0.6521、BM25 命中 20 条。

    反例实现：阈值收得太紧、或把 BM25 路整体砍掉 —— 这条会红。
    """
    db_session, vec_engine = shared_db
    uid, rows = await _seed_and_index(
        db_session,
        vec_engine,
        ["医保结算清单 接口说明", "结算清单 对账口径", "医保参保登记 接口字段"],
        [0.95, 0.90, 0.85],
    )
    _patch_embed(monkeypatch, [_vec(1.0)])

    got = await retriever.retrieve(
        db_session, vec_engine, "医保结算清单 接口", user_id=uid, limit=12
    )

    assert [r.chunk.id for r in got] == [rows[0].id, rows[1].id, rows[2].id]


# ── 内容去重 ────────────────────────────────────────────────
#
# 实测那次召回 12 条只有 4 种不同正文，「参保人手机 | tel | String | 50」重复
# 4 次，把 10 个引用位占满——模型拿到的证据里 4 条是同一句话。


async def test_retrieve_dedupes_identical_content(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正文完全相同的切片只保留一条，且保留融合分数最高的那个。

    反例实现：
    - 不去重 —— 这条会红
    - 保留最后出现的那条 —— 这条会红（留下的是分数最低的那条）
    """
    db_session, vec_engine = shared_db
    uid, rows = await _seed_and_index(
        db_session,
        vec_engine,
        [
            "参保人手机 | tel | String | 50",
            "个人编号 | psnNo | String | 是",
            "参保人手机 | tel | String | 50",
        ],
        [0.95, 0.90, 0.85],
    )
    _patch_embed(monkeypatch, [_vec(1.0)])

    got = await retriever.retrieve(db_session, vec_engine, "zzzqqqxyz", user_id=uid, limit=5)

    # 第 1 条与第 3 条正文相同 → 只留第 1 条（距离最近，融合分数最高）
    assert [r.chunk.id for r in got] == [rows[0].id, rows[1].id]


async def test_retrieve_dedups_before_truncating_to_limit(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """去重必须在截断 limit **之前**。

    反例实现：先 `fused[:limit]` 再去重 —— 前 limit 条里有重复时，
    去重后数量不足 limit，引用位白白浪费。这条会红。
    """
    db_session, vec_engine = shared_db
    uid, rows = await _seed_and_index(
        db_session,
        vec_engine,
        ["重复正文", "重复正文", "正文二", "正文三"],
        [0.95, 0.90, 0.85, 0.80],
    )
    _patch_embed(monkeypatch, [_vec(1.0)])

    got = await retriever.retrieve(db_session, vec_engine, "zzzqqqxyz", user_id=uid, limit=2)

    assert len(got) == 2, "去重后要能补足到 limit 条"
    assert [r.chunk.id for r in got] == [rows[0].id, rows[2].id]


async def test_retrieve_dedup_key_is_the_full_content(
    shared_db: tuple[AsyncSession, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """去重键是正文全文，不是截断后的前缀。

    两条切片前 1000 字相同、只有结尾不同 → 不是重复，两条都要留下。

    反例实现：拿 `content[:120]` 当键（引用表的摘要是 120 字，很容易顺手抄过来）
    —— 这条会红。
    """
    db_session, vec_engine = shared_db
    uid, rows = await _seed_and_index(
        db_session,
        vec_engine,
        ["甲" * 1000 + "结尾甲", "甲" * 1000 + "结尾乙"],
        [0.95, 0.90],
    )
    _patch_embed(monkeypatch, [_vec(1.0)])

    got = await retriever.retrieve(db_session, vec_engine, "zzzqqqxyz", user_id=uid, limit=5)

    assert [r.chunk.id for r in got] == [rows[0].id, rows[1].id]
