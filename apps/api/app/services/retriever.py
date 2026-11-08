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
from enum import StrEnum

from sqlalchemy import func, select
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
    query_vector: list[float] | None = None,
    query_vector_given: bool = False,
) -> list[Retrieved]:
    """混合检索。只搜当前用户的资料。

    两路都按 ``user_id`` 收窄——用户私有资料必须先隔离，这是唯一的防线。

    ## 两路都过相关性下限

    向量路在 :func:`vectorstore.knn_search` 内部过滤；BM25 路拿不到距离，
    要靠 :func:`vectorstore.chunk_distances` 回头查这些 id 的向量距离再过滤。

    只给向量路设下限不够：BM25 的 MATCH 是 **OR** 语义（jieba 分词后
    「手机 质量 参数」里只要有一个 token 命中，切片就进候选），实测
    「手机 质量 参数」能命中 50 条医保接口文档里的字段行，不相关的切片
    照样进证据块。

    ## 去重

    融合之后、截断 ``limit`` **之前**按正文全文去重。同一份资料里
    「参保人手机 | tel | String | 50」在几千个切片里出现几十次，不去重
    就会把 10 个引用位占满，模型拿到的证据里四条是同一句话。

    ## ``query_vector_given``：调用方已经算好查询向量

    传入 ``query_vector_given=True`` 表示「这个向量是调用方算的，直接用」。
    调用方（:mod:`app.services.tools`）需要它来判断「语义相关性判断能不能跑」，
    而**再算一次就是第二次调嵌入服务**——慢，而且嵌入服务欠费时会直接
    让整次检索失败。

    所以那两个参数必须成对使用：给了 ``query_vector_given=True`` 却没给
    ``query_vector``，按「向量不可用」处理。
    """
    source_ids = await _user_source_ids(db, user_id)
    if not source_ids:
        return []

    # 先 ensure：用户一份资料都没摄取过时，两张索引表都不存在。
    await ensure_index_tables(vec_engine)
    # 查询向量只算一次，两路共用——不额外调嵌入服务。
    if not query_vector_given:
        query_vector = await _query_vector(question)
    vector_hits = await _vector_recall(vec_engine, query_vector, source_ids)
    bm25_hits = await _bm25_recall(vec_engine, question, query_vector, source_ids)

    if not vector_hits and not bm25_hits:
        return []

    fused = _rrf_fuse(vector_hits, bm25_hits)
    pairs = await _load_chunks(db, fused)
    return _dedupe(pairs, fused, limit)


# ── 各路召回 ───────────────────────────────────────────────
async def _user_source_ids(db: AsyncSession, user_id: int) -> list[int]:
    sources = await Source.list_owned(db, user_id)
    return [s.id for s in sources]


class NoResultReason(StrEnum):
    """检索返回 0 条的**原因**——三种 0 条给模型的话不一样。

    混成一句话会害用户：

    - :attr:`NO_MATERIAL`：资料库压根没有切片——正常空态。
    - :attr:`NOT_EVALUATED`：**相关性从未被评估过**（没配嵌入 key，
      向量路没跑）或**索引还没建好**（资料刚上传，摄取中途）。
      这两种情况下说「资料与问题不相关」是**事实性错误**——用户的资料
      可能高度相关，只是此刻还没法判断。
    - :attr:`IRRELEVANT`：确实评估过了，候选全被相关性下限挡掉——
      这才是「资料与问题无关」。
    """

    NO_MATERIAL = "no_material"
    NOT_EVALUATED = "not_evaluated"
    IRRELEVANT = "irrelevant"


async def explain_no_result(
    db: AsyncSession,
    vec_engine: AsyncEngine,
    question: str,
    user_id: int,
    query_vector: list[float] | None = None,
    query_vector_given: bool = False,
) -> NoResultReason:
    """判断「0 条命中」到底是因为什么。

    与 :func:`retrieve` 分开，不改它的返回类型——既有调用与测试都断言
    ``await retrieve(...) == []``。

    判据按「确定性」从高到低：

    1. 没有切片 → :attr:`NO_MATERIAL`（资料库是空的）。
    2. 有切片但**一个向量都没有** → :attr:`NOT_EVALUATED`。
       两种成因都归这一档：没配嵌入 key（向量路压根没跑），
       或摄取刚写完切片、还没建索引。
    3. 有向量、候选也跑过了，只是全被下限挡掉 → :attr:`IRRELEVANT`。

    ``query_vector_given=True`` 表示调用方已经算好查询向量——避免
    第二次调嵌入服务（嵌入服务欠费时那会让整次提问失败）。
    """
    if not await library_has_material(db, user_id):
        return NoResultReason.NO_MATERIAL

    # 切片在、向量不在 → 从来没算过（或还没算完）相关性。
    if await vectorstore.count_embeddings(db, user_id) == 0:
        return NoResultReason.NOT_EVALUATED

    source_ids = await _user_source_ids(db, user_id)
    if not source_ids:
        return NoResultReason.NO_MATERIAL
    if not query_vector_given:
        query_vector = await _query_vector(question)
    if query_vector is None:
        # 算不出查询向量 → 相关性没法评估。
        return NoResultReason.NOT_EVALUATED

    # **原始候选**（没过下限的）。:func:`_bm25_recall` 返回的是过滤后的，
    # 用它判断「有没有候选」分不清「压根没候选」和「全被挡掉」。
    raw_bm25 = await bm25.search(vec_engine, question, BM25_TOP_K, source_ids)
    if not raw_bm25:
        # 字面一个字都没命中。向量路本该能捞到东西（切片有向量），
        # 捞不到说明向量索引也没就绪——**相关性从没被评估过**。
        return NoResultReason.NOT_EVALUATED

    # 有字面候选。它们是不是全被相关性下限挡掉了？
    distances = await vectorstore.chunk_distances(
        vec_engine, query_vector, [hit.chunk_id for hit in raw_bm25], source_ids
    )
    if any(hit.chunk_id not in distances for hit in raw_bm25):
        # 有候选**连距离都算不出来**（它没有向量）——对这些候选来说
        # 相关性从没被评估过。这时说「资料与问题不相关」是事实性错误。
        return NoResultReason.NOT_EVALUATED
    # 每个候选都有距离，而 retrieve 仍然返回 0 ⇒ 它们全被下限挡掉了。
    return NoResultReason.IRRELEVANT


async def library_has_material(db: AsyncSession, user_id: int) -> bool:
    """用户有没有已摄取的切片？

    用来区分两种「0 条命中」：资料库压根是空的（正常空态）与
    「有资料但检索不到相关内容」（相关性下限把它们挡掉了）。这两种情况
    给模型的话不一样——后者必须说清「这些资料与问题无关，别当证据」。

    切片数**直接 count(document_chunks)**，不用 ``sources.chunk_count`` 求和：
    那是摄取时写进去的缓存字段，摄取中途失败留下半截数据时它对不上。
    """
    # **排除公开来源**（``source_type="web"``）——联网搜索结果不是用户
    # 上传的资料。混进来会让「没上传任何资料、只搜过一次网」的用户
    # 被判成「资料库非空」，于是 ``explain_no_result`` 返回
    # ``not_evaluated`` 而不是 ``no_material``——模型于是收到「无法评估
    # 你的私有资料与这个问题是否相关（资料索引尚未就绪）」，而真相是
    # 「用户压根没有资料」。那是对模型的事实性错误陈述。
    count = await db.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .join(Source, Source.id == DocumentChunk.source_id)
        .where(Source.owned_clause(user_id))
    )
    return bool(count)


def semantic_filter_active(query_vector: list[float] | None) -> bool:
    """语义相关性判断**能不能跑**——看查询向量算出来了没有。

    ## 为什么需要它

    算不出查询向量时（没配 ``EMBEDDING_API_KEY``、嵌入服务欠费、
    维度不匹配），:func:`_vector_recall` 直接返回空、:func:`_bm25_recall`
    整路不设下限——只剩关键词匹配。

    这时喂给模型的切片**没做过语义相关性判断**，只是字面沾边。模型
    不知道这件事，会把它们当成「检索到的相关证据」用。原始事故里那句
    「参保人手机 | tel」就是这么进上下文的。

    所以这条要**告诉模型**：这些只是关键词命中，关联度未经确认。

    ## 为什么收查询向量而不是自己再算一次

    之前这个函数自己调 :func:`_query_vector` —— 那是**第二次调嵌入服务**：
    慢，而且嵌入服务欠费时直接让整次检索失败（用户看到的是「接口报错、
    没有内容」）。现在由调用方把已经算好的向量传进来。
    """
    return query_vector is not None


async def _query_vector(question: str) -> list[float] | None:
    """把问题变成向量。算不出来时返回 None——那一路静默跳过，不报错。

    **捕获全部嵌入异常**，不只是「未配置 key」：嵌入服务欠费、超时、
    维度不匹配抛的都是 :class:`EmbeddingError`。它们不该把整个
    ``local_search`` 拖垮——向量路只是「降级成纯 BM25」，检索仍能跑。
    （实测：嵌入服务欠费时 ``embed_texts`` 抛 ``EmbeddingError``，
    只 catch ``EmbeddingNotConfiguredError`` 会让它冒到工具层，
    整次提问直接报错、没有任何内容。）
    """
    try:
        vectors = await embedder.embed_texts([question])
    except embedder.EmbeddingError:
        return None
    if not vectors:
        return None
    return vectors[0]


async def query_vector_for(question: str) -> list[float] | None:
    """算查询向量，**算不出来时返回 None 而不是抛异常**。

    给 :mod:`app.services.tools` 用——它需要这个向量做两件事：
    传给 :func:`retrieve`（避免重复调嵌入服务），以及判断
    :func:`semantic_filter_active`。

    算不出来时（没配 key / 欠费 / 超时）返回 None，检索降级成纯 BM25，
    **不该让整次提问失败**。
    """
    return await _query_vector(question)


async def _vector_recall(
    engine: AsyncEngine,
    query_vector: list[float] | None,
    source_ids: Sequence[int],
) -> list[tuple[int, float]]:
    """向量召回。查询向量为 None（没配嵌入 key）时返回空。

    查表前必须 ensure：全新部署上用户可能一份资料都没摄取过，
    chunk_embeddings 虚表压根不存在，直接查会报
    ``no such table: chunk_embeddings``。

    相关性下限在 :func:`vectorstore.knn_search` 内部生效。
    """
    if query_vector is None:
        return []
    await ensure_index_tables(engine)
    return await vectorstore.knn_search(engine, query_vector, VECTOR_TOP_K, source_ids)


async def _bm25_recall(
    engine: AsyncEngine,
    question: str,
    query_vector: list[float] | None,
    source_ids: Sequence[int],
) -> list[bm25.Bm25Hit]:
    """BM25 召回，并让它也过相关性下限。

    BM25 只知道「哪些切片字面命中了」，不知道距离——距离得回头查
    :func:`vectorstore.chunk_distances`（复用同一个查询向量，不额外调嵌入）。

    查不到距离的切片**保留**：查不到距离不等于不相关，把它们丢掉等于
    让一次向量写入失败静默吞掉整份资料。没有查询向量（没配嵌入 key）时
    整路不设下限——那时连向量路都是关的。
    """
    hits = await bm25.search(engine, question, BM25_TOP_K, source_ids)
    if not hits or query_vector is None:
        return hits
    distances = await vectorstore.chunk_distances(
        engine, query_vector, [hit.chunk_id for hit in hits], source_ids
    )
    # 与向量路同一个判定（vectorstore.is_relevant）——同一个度量、同一个阈值。
    relevant: list[bm25.Bm25Hit] = []
    for hit in hits:
        distance = distances.get(hit.chunk_id)
        # 查不到距离 = 这个切片没有向量（写入失败）。查不到不等于不相关，
        # 丢掉它等于让一次向量写入失败静默吞掉整份资料。
        if distance is None or vectorstore.is_relevant(distance):
            relevant.append(hit)
    return relevant


def _dedupe(
    pairs: dict[int, tuple[DocumentChunk, Source]],
    fused: Sequence[tuple[int, float, int | None, int | None]],
    limit: int,
) -> list[Retrieved]:
    """按正文全文去重，再截到 ``limit`` 条。

    去重键是 ``chunk.content`` 全文，不是截断后的——两条切片前 1000 字
    相同、只有结尾不同，那是两条不同的内容。

    保留**第一次出现**的（融合分数最高的那个）。去重必须在截断之前：
    先截 limit 再去重的话，去重后可能凑不满 limit 条。
    """
    seen: set[str] = set()
    results: list[Retrieved] = []
    # 保持 fused 的排名顺序：dict 按插入序（Python 3.7+ 保证），
    # 所以直接迭代 fused 过滤掉取不到的孤儿行即可。
    for cid, score, v_rank, b_rank in fused:
        pair = pairs.get(cid)
        if pair is None:
            continue
        chunk, source = pair
        if chunk.content in seen:
            continue
        seen.add(chunk.content)
        results.append(
            Retrieved(
                chunk=chunk,
                source=source,
                rrf_score=score,
                vector_rank=v_rank,
                bm25_rank=b_rank,
            )
        )
        if len(results) >= limit:
            break
    return results


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
        ((cid, score, vector_ranks.get(cid), bm25_ranks.get(cid)) for cid, score in scores.items()),
        key=lambda item: -item[1],
    )


async def _load_chunks(
    db: AsyncSession,
    ordered: Sequence[tuple[int, float, int | None, int | None]],
) -> dict[int, tuple[DocumentChunk, Source]]:
    """按 id 批量取切片与所属资料，返回 {chunk_id: (chunk, source)}。

    取的是**全部**融合候选，不是前 limit 条——去重在截断之前做，
    先截后去重会凑不满 limit。

    向量表可能有孤儿行（chunk 已删、向量还在），这里自然取不到，
    由 :func:`_dedupe` 在组装结果时过滤掉。
    """
    rows = await DocumentChunk.find_many(db, [cid for cid, *_ in ordered])
    return {c.id: (c, c.source) for c in rows}
