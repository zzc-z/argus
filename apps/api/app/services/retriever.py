"""混合检索：向量 KNN + BM25 合并成一份排序。

## 为什么用 RRF 而不是加权分数

两路的分数量纲完全不同：

- 向量检索给 **L2 距离**（实测0.0-1.3，越小越相关）
- BM25 给**负分**（-1 到 -10 量级，越小越相关，但随语料规模漂移）

加权平均需要先把两者都归一化到同一尺度，而归一化参数（min-max 要看当前
候选集、z-score 要看语料统计）在两路各自的分布上都不稳定。实测中向量距离
只差 0.02 就该分出胜负，BM25 差 3 分可能毫无意义——没有可靠的换算系数。

RRF（Reciprocal Rank Fusion）只看**排名**，不看分数：

    score(d) = Σ  1 / (k + rank_i(d))

它天然免疫量纲问题。k=60 取自 Cormack 等人的原始论文，用来压制头部：
第 1 名贡献 1/61，第 10 名只贡献 1/70——排在最前不等于该赢十倍。

两路同时命中的文档两次加分，这是混合检索的核心收益：向量懂语义
（「能效」↔「能源效率」），BM25 懂精确词（「H100」这种专有名词）。

## RRF 分数的方向

本模块返回的 ``score`` 是**越大越相关**（RRF 的定义就是倒数求和），
与两路原始方向的「越小越近」相反。调用方不要自己再翻转。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source
from app.services import bm25, embedder, vectorstore
from app.services.ingest import ensure_index_tables

# Cormack et al. 2009 的原始取值。改这个数会改变头部排名的敏感度。
RRF_K = 60

# PRD §7.1：两路各召回 top 50，合并后交给 rerank 精排。
VECTOR_TOP_K = 50
BM25_TOP_K = 50


@dataclass(frozen=True, slots=True)
class Retrieved:
    chunk: DocumentChunk
    source: Source
    rrf_score: float
    """越大越相关。"""
    vector_rank: int | None
    bm25_rank: int | None


async def retrieve(
    db: AsyncSession,
    vec_engine: AsyncEngine,
    question: str,
    user_id: int,
    limit: int = 10,
) -> list[Retrieved]:
    """混合检索。只搜当前用户的资料。

    两路都按 ``user_id`` 收窄——用户私有资料必须先隔离，这是唯一的防线。
    """
    source_ids = await _user_source_ids(db, user_id)
    if not source_ids:
        return []

    # 先 ensure：用户一份资料都没摄取过时，两张索引表都不存在。
    await ensure_index_tables(vec_engine)
    vector_hits = await _vector_recall(vec_engine, question, source_ids)
    bm25_hits = await bm25.search(vec_engine, question, BM25_TOP_K, source_ids)

    if not vector_hits and not bm25_hits:
        return []

    fused = _rrf_fuse(vector_hits, bm25_hits)
    pairs = await _load_chunks(db, fused[:limit])
    # 保持 fused 的排名顺序：dict 按插入序（Python 3.7+ 保证），
    # 所以直接迭代 fused 过滤掉取不到的孤儿行即可。
    return [
        Retrieved(
            chunk=pairs[cid][0],
            source=pairs[cid][1],
            rrf_score=score,
            vector_rank=v_rank,
            bm25_rank=b_rank,
        )
        for cid, score, v_rank, b_rank in fused[:limit]
        if cid in pairs
    ]


# ── 各路召回 ───────────────────────────────────────────────
async def _user_source_ids(db: AsyncSession, user_id: int) -> list[int]:
    sources = await Source.list_owned(db, user_id)
    return [s.id for s in sources]


async def _vector_recall(
    engine: AsyncEngine,
    question: str,
    source_ids: Sequence[int],
) -> list[tuple[int, float]]:
    """向量召回。没配嵌入 key 时返回空——那一路静默跳过，不报错。

    查表前必须 ensure：全新部署上用户可能一份资料都没摄取过，
    chunk_embeddings 虚表压根不存在，直接查会报
    ``no such table: chunk_embeddings``。
    """
    try:
        vectors = await embedder.embed_texts([question])
    except embedder.EmbeddingNotConfiguredError:
        return []
    if not vectors:
        return []
    await ensure_index_tables(engine)
    return await vectorstore.knn_search(engine, vectors[0], VECTOR_TOP_K, source_ids)


# ── RRF 合并 ───────────────────────────────────────────────
def _rrf_fuse(
    vector_hits: Sequence[tuple[int, float]],
    bm25_hits: Sequence[bm25.Bm25Hit],
) -> list[tuple[int, float, int | None, int | None]]:
    """两路排名融合。返回 [(chunk_id, rrf_score, vector_rank, bm25_rank)]，分数降序。

    排名从 1 起（0 会被公式里的 k 抵消，没意义）。
    """
    scores: dict[int, float] = {}
    vector_ranks: dict[int, int] = {}
    bm25_ranks: dict[int, int] = {}

    for rank, (chunk_id, _dist) in enumerate(vector_hits, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        vector_ranks[chunk_id] = rank

    for rank, hit in enumerate(bm25_hits, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        bm25_ranks[hit.chunk_id] = rank

    return sorted(
        (
            (cid, score, vector_ranks.get(cid), bm25_ranks.get(cid))
            for cid, score in scores.items()
        ),
        key=lambda item: -item[1],
    )


async def _load_chunks(
    db: AsyncSession,
    ordered: Sequence[tuple[int, float, int | None, int | None]],
) -> dict[int, tuple[DocumentChunk, Source]]:
    """按 id 批量取切片与所属资料，返回 {chunk_id: (chunk, source)}。

    向量表可能有孤儿行（chunk 已删、向量还在），这里自然取不到，
    由 :func:`retrieve` 在组装结果时过滤掉。
    """
    rows = await DocumentChunk.find_many(db, [cid for cid, *_ in ordered])
    return {c.id: (c, c.source) for c in rows}
