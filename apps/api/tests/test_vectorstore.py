"""vectorstore 的测试。

重点不是「能不能搜」，而是**扩展到底加载上没有**——sqlite-vec 加载失败时
不报任何错，只是后续所有 vec_* 调用报 "no such function"。
下面每个用例都先断言 vec_version() 可用，等于在测这个前提本身。
"""

import ast
import inspect
import math
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Base
from app.services import vectorstore
from app.services.vectorstore import EMBEDDING_DIM, create_vector_engine, ensure_vector_table


@pytest_asyncio.fixture
async def vec_engine(tmp_path) -> AsyncIterator[AsyncEngine]:
    """带 sqlite-vec 的临时库 + 普通表 schema，测完删除。

    普通表也要建：knn_search 的 source 过滤是子查询 document_chunks，
    没这张表会直接报 no such table。
    """
    db_path = tmp_path / "vec_test.db"
    engine = create_vector_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _vec(weight: float = 1.0, seed: int = 0) -> list[float]:
    """造一个维度正确、第 seed 维为 weight 的单位向量。

    weight 不同才能让距离有区分度。单维单位向量两两正交、距离全相同，
    而 vec0 是 ANN 索引，等距项的返回顺序未定义——不能用它断言排序。
    """
    v = [0.0] * EMBEDDING_DIM
    v[seed] = weight
    return v


# ── 扩展加载 ────────────────────────────────────────────────
async def test_extension_is_loaded(vec_engine: AsyncEngine) -> None:
    """扩展没加载就全盘失败——这是所有后续测试的前提。"""
    async with vec_engine.connect() as conn:
        version = (await conn.execute(text("SELECT vec_version()"))).scalar()

    assert version is not None


async def test_rejects_non_sqlite_url() -> None:
    """换 Postgres 时要立刻报清楚，而不是等到建表时才发现扩展没加载。"""
    with pytest.raises(ValueError, match="只支持 SQLite"):
        create_vector_engine("postgresql+asyncpg://user:pwd@localhost:5432/argus")


async def test_engine_is_singleton() -> None:
    """进程内单例，避免每个检索请求都新建连接池。"""
    first = vectorstore.get_vector_engine()
    second = vectorstore.get_vector_engine()

    assert first is second

    await vectorstore.dispose_vector_engine()


# ── 建表 ────────────────────────────────────────────────────
async def test_ensure_table_is_idempotent(vec_engine: AsyncEngine) -> None:
    """重复调用不能报错——摄取会重跑。"""
    await ensure_vector_table(vec_engine)
    await ensure_vector_table(vec_engine)


# ── 写入与检索 ──────────────────────────────────────────────
async def test_knn_returns_nearest_first(vec_engine: AsyncEngine) -> None:
    """三个权重递减的同向向量，最近的必须是权重最大的那个。"""
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 3)
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(cids[0], _vec(1.0, seed=0)), (cids[1], _vec(0.8, seed=0)), (cids[2], _vec(0.5, seed=0))],
    )

    hits = await vectorstore.knn_search(
        vec_engine, _vec(1.0, seed=0), limit=3, source_ids=[sid]
    )

    assert [cid for cid, _ in hits] == cids
    assert hits[0][1] == pytest.approx(0.0, abs=1e-5)


async def test_knn_distance_increases(vec_engine: AsyncEngine) -> None:
    """距离必须递增，否则排序逻辑是错的。"""
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 2)
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(cids[0], _vec(1.0, seed=0)), (cids[1], _vec(0.5, seed=0))],
    )

    hits = await vectorstore.knn_search(
        vec_engine, _vec(1.0, seed=0), limit=2, source_ids=[sid]
    )

    assert hits[0][1] < hits[1][1]


async def test_knn_limit_respected(vec_engine: AsyncEngine) -> None:
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 20)
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(cids[i], _vec(1.0 - i / EMBEDDING_DIM)) for i in range(20)],
    )

    hits = await vectorstore.knn_search(vec_engine, _vec(1.0), limit=5, source_ids=[sid])

    assert len(hits) == 5


async def test_knn_on_empty_table_returns_nothing(vec_engine: AsyncEngine) -> None:
    await ensure_vector_table(vec_engine)

    assert await vectorstore.knn_search(vec_engine, _vec(), limit=5, source_ids=[1]) == []


async def test_upsert_replaces_existing(vec_engine: AsyncEngine) -> None:
    """重跑摄取会重复写同一 chunk_id，旧向量必须被替换而不是重复插入。"""
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 1)
    await vectorstore.upsert_embeddings(vec_engine, [(cids[0], _vec(1.0, seed=0))])
    await vectorstore.upsert_embeddings(vec_engine, [(cids[0], _vec(1.0, seed=1))])

    hits = await vectorstore.knn_search(
        vec_engine, _vec(1.0, seed=1), limit=5, source_ids=[sid]
    )

    assert len(hits) == 1
    assert hits[0][1] == pytest.approx(0.0, abs=1e-5)


async def test_upsert_empty_is_noop(vec_engine: AsyncEngine) -> None:
    await ensure_vector_table(vec_engine)

    assert await vectorstore.upsert_embeddings(vec_engine, []) == 0


# ── 维度与过滤 ──────────────────────────────────────────────
async def test_knn_rejects_wrong_dimension(vec_engine: AsyncEngine) -> None:
    """维度不匹配时 vec0 会报难懂的错，这里要提前拦下来。"""
    await ensure_vector_table(vec_engine)

    with pytest.raises(ValueError, match="维度"):
        await vectorstore.knn_search(vec_engine, [0.1, 0.2, 0.3], limit=5, source_ids=[1])


async def test_knn_filters_by_source_ids(vec_engine: AsyncEngine) -> None:
    """用户私域隔离：source_ids 之外的 chunk 一律看不见。

    两个 chunk 向量完全相同，唯一区别是所属 source——不加过滤就会串库。
    """
    from app.models import DocumentChunk, Source, SourceType, User

    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        user_id = await _seed_source(conn, "u1")
        mine_id = await _seed_source(conn, "我的资料", user_id)
        other_id = await _seed_source(conn, "别人的资料", user_id)
        mine_chunk = await _seed_chunk(conn, mine_id, 0)
        other_chunk = await _seed_chunk(conn, other_id, 0)
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(mine_chunk, _vec(1.0)), (other_chunk, _vec(1.0))],
    )

    hits = await vectorstore.knn_search(vec_engine, _vec(1.0), limit=10, source_ids=[mine_id])

    assert [cid for cid, _ in hits] == [mine_chunk]


async def test_knn_empty_source_list_returns_nothing(vec_engine: AsyncEngine) -> None:
    """空 source 集合要短路——生成 ``IN ()`` 是语法错误。"""
    await ensure_vector_table(vec_engine)
    await vectorstore.upsert_embeddings(vec_engine, [(1, _vec(1.0))])

    assert await vectorstore.knn_search(vec_engine, _vec(1.0), limit=10, source_ids=[]) == []


# ── 距离语义 ───────────────────────────────────────────────
def _cosine(a: list[float], b: list[float]) -> float:
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def _l2(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


async def test_distance_is_l2_not_cosine(vec_engine: AsyncEngine) -> None:
    """vec0 返回 L2 欧氏距离，不是余弦距离。

    锁住这条是因为换 pgvector（默认余弦）时会变，而调用方可能已经把
    阈值写成了余弦语义。单位向量下 L2 = sqrt(2-2cos)，与 1-cos 差别很大。
    """
    query = _vec(1.0, seed=0)
    stored = _vec(0.5, seed=0)  # 单位向量，与 query 夹角固定
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 1)
    await vectorstore.upsert_embeddings(vec_engine, [(cids[0], stored)])

    hits = await vectorstore.knn_search(vec_engine, query, limit=1, source_ids=[sid])
    reported = hits[0][1]

    assert reported == pytest.approx(_l2(query, stored), abs=1e-5)
    assert reported != pytest.approx(1 - _cosine(query, stored), abs=1e-3)


async def test_l2_and_cosine_give_same_ranking(vec_engine: AsyncEngine) -> None:
    """单位向量下 L2 是 cos 的单调变换——排序一致，阈值语义不一致。

    这条是上面那条的推论：正因为排序一致，摄取与检索混用度量不会排错，
    只有「距离 < X」这类阈值会失效。
    """
    query = _vec(1.0, seed=0)
    candidates = [_vec(1.0), _vec(0.8), _vec(0.6), _vec(0.4)]
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 4)
    await vectorstore.upsert_embeddings(
        vec_engine, [(cids[i], v) for i, v in enumerate(candidates)]
    )

    hits = await vectorstore.knn_search(vec_engine, query, limit=4, source_ids=[sid])
    by_cos = sorted(
        range(len(candidates)),
        key=lambda i: -_cosine(query, candidates[i]),
    )

    assert [cid - 1 for cid, _ in hits] == by_cos


# ── 相关性下限 ──────────────────────────────────────────────
#
# 背景：用户问「iPhone 折叠屏 对比 国产折叠屏质量」，资料库里只有一份
# 《北京市医疗保障信息平台…》。向量 top50 + BM25 top50 融合后**直接取前 N 条**，
# 于是模型拿着「个人编号 / 参保人手机 / 身份证」当证据去回答手机质量对比。
#
# 真实成因是检索侧没有相关性下限，不是上游拦内容。
#
# 阈值量的是**余弦距离**（1 - cos），不是 L2：
# - L2 对模长敏感——dev 库里 7398 个向量有 9 个模长是 19.596（早期测试留下的
#   [0.5]*1536 脏数据），用 L2 判相关性等于让「这个切片的模长恰好多大」
#   决定它相不相关
# - 归一化会抹掉既有测试要的区分度（既有测试用「幅度」造距离）
# - sqlite-vec 有 vec_distance_cosine，返回 1 - cos，对模长完全不敏感
#
# knn_search 的**返回值仍然是 L2**（项目既有契约，test_distance_is_l2_not_cosine
# 锁死了它），只有「相关性过滤」用余弦距离。


def test_max_relevant_distance_is_the_calibrated_value() -> None:
    """绝对阈值 0.45 是实测标定出来的，不能随手换。

    标定依据（生产库同一份资料实测，2026-10-26，7 组相关 + 7 组不相关查询）：
    相关查询 top-20 余弦距离全部 ≤ **0.4006**，不相关查询 top-20 全部 ≥ **0.6234**。
    0.45 取在两者之间。

    为什么不是 0.40：实测 0.40 会误杀 4 条「本接口用于查询医保个人账户的交易
    明细信息。」（距离 0.4006）——那是「个人医疗消费」之外的**另一个实体**的
    证据，丢掉它答案就变单边。

    **注入回归**：把 0.45 改成极大值（等于不设限）——这条会红。
    """
    assert vectorstore.MAX_RELEVANT_DISTANCE == 0.45


def test_max_relevant_distance_docstring_records_metric_and_calibration() -> None:
    """阈值必须写明四件事，缺一条后面就有人会照着错的语义改它。

    - **用的是余弦距离**：0.40 是按余弦标的，拿它当 L2 阈值会把「模长差很多的
      同向切片」全滤掉（见 test_knn_filter_ignores_vector_magnitude）
    - **为什么不用 L2**：L2 对模长敏感，而库里确实有模长 19.596 的脏数据
    - **换 pgvector 要重新标定**：距离度量一变，0.40 这个数就作废
    - **标定依据**（相关 ≤0.2126 / 不相关 ≥0.6234）：没有依据的阈值没人敢动

    反例实现：只写 `MAX_RELEVANT_DISTANCE = 0.40` 不带任何说明——这条会红。
    """
    doc = _constant_docstring(vectorstore, "MAX_RELEVANT_DISTANCE")

    assert doc, "MAX_RELEVANT_DISTANCE 必须带 docstring"
    assert "余弦" in doc or "cosine" in doc.lower(), "必须写明阈值量的是余弦距离"
    assert "L2" in doc or "欧氏" in doc, "必须写明为什么不用 L2"
    assert "pgvector" in doc.lower(), "必须写明换 pgvector 时要重新标定"
    assert "0.4006" in doc or "0.40" in doc, "必须写明相关查询的标定值"
    assert "0.6234" in doc or "0.62" in doc, "必须写明不相关查询的标定值"


async def test_knn_drops_rows_beyond_relevance_threshold(vec_engine: AsyncEngine) -> None:
    """与查询同向的留下、反向的挡掉。

    反例实现：
    - 干脆不过滤 —— 这条会红
    - 过滤条件写反（留 `distance > threshold` 的）—— 这条会红
    - 过滤写在调用方而不是 knn_search 里 —— knn_search 自己仍然返回无关切片，这条会红
    """
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 2)
    near, far = cids
    await vectorstore.upsert_embeddings(vec_engine, [(near, _vec(0.5)), (far, _vec(-0.4))])

    hits = await vectorstore.knn_search(vec_engine, _vec(1.0), limit=5, source_ids=[sid])

    assert [cid for cid, _ in hits] == [near]


async def test_knn_filter_ignores_vector_magnitude(vec_engine: AsyncEngine) -> None:
    """同一个方向的向量，模长差 10 倍也要照样留下。

    这是「用余弦不用 L2」的核心：L2 对模长敏感——库里确实有模长 19.596 的脏数据
    （早期测试留下的 [0.5]*1536），用 L2 判相关性等于让「这个切片的模长恰好多大」
    决定它相不相关。

    反例实现：过滤仍用 L2 —— 这个切片的 L2 距离是 9.0 > 0.40，被挡掉 → 这条会红。
    """
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 1)
    (cid,) = cids
    await vectorstore.upsert_embeddings(vec_engine, [(cid, _vec2(10.0, 0.0))])

    hits = await vectorstore.knn_search(vec_engine, _vec2(1.0, 0.0), limit=5, source_ids=[sid])

    assert [c for c, _ in hits] == [cid]


async def test_knn_skips_zero_norm_row_instead_of_crashing(vec_engine: AsyncEngine) -> None:
    """零范数向量不能把整条检索路炸掉。

    sqlite-vec 的 ``vec_distance_cosine`` 在任一侧模长为 0 时返回 **NULL**
    （实测：`SELECT chunk_id, distance, vec_distance_cosine(...)` → `(99, None, None)`）。
    直接 ``float(None)`` 会抛 TypeError → 该用户所有查询的本地检索全挂——
    不是「那一条切片被跳过」，是整条路断掉。

    反例实现：不判 None 直接 float() —— 这条会红（TypeError）。
    """
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 1)
    (cid,) = cids
    # 一条正常向量 + 一条零范数向量
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(cid, _vec2(1.0, 0.0)), (cids[0] + 1000, [0.0] * 1536)],
    )

    hits = await vectorstore.knn_search(vec_engine, _vec2(1.0, 0.0), limit=5, source_ids=[sid])

    # 零范数那行被挡掉，正常那行留下——关键是**不抛异常**
    assert [c for c, _ in hits] == [cid]


async def test_chunk_distances_skips_zero_norm_row(vec_engine: AsyncEngine) -> None:
    """``chunk_distances`` 同样要跳过零范数行，而不是 float(None) 崩掉。

    BM25 路靠它给命中切片补距离——它一崩，BM25 路跟着整条死。
    """
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 1)
    (cid,) = cids
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(cid, _vec2(1.0, 0.0)), (cids[0] + 1000, [0.0] * 1536)],
    )

    distances = await vectorstore.chunk_distances(
        vec_engine, _vec2(1.0, 0.0), [cid, cids[0] + 1000], [sid]
    )

    assert cid in distances
    assert cids[0] + 1000 not in distances


async def test_knn_keeps_row_just_inside_threshold(vec_engine: AsyncEngine) -> None:
    """余弦距离 0.30（阈值 0.40 之内）必须留下——阈值不能收得太紧。

    反例实现：阈值写成 0.2 之类——相关内容被一起滤掉，这条会红。
    """
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 1)
    (cid,) = cids
    await vectorstore.upsert_embeddings(vec_engine, [(cid, _vec_at_cosine_distance(0.30))])

    hits = await vectorstore.knn_search(vec_engine, _vec2(1.0, 0.0), limit=5, source_ids=[sid])

    assert [c for c, _ in hits] == [cid]


async def test_knn_drops_row_just_outside_threshold(vec_engine: AsyncEngine) -> None:
    """余弦距离 0.55（绝对阈值 0.45 之外）必须挡掉。

    反例实现：阈值放到 0.6 之上——不相关内容照单全收，这条会红。

    为什么是 0.55 而不是 0.40：绝对阈值 2026-10-26 重新标定为 0.45
    （相关查询 top-20 距离全部 ≤ 0.4006，不相关全部 ≥ 0.6234）。
    0.40 会误杀「第二实体」的证据——见 test_relative_threshold_keeps_second_entity。
    """
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 1)
    (cid,) = cids
    await vectorstore.upsert_embeddings(vec_engine, [(cid, _vec_at_cosine_distance(0.55))])

    hits = await vectorstore.knn_search(vec_engine, _vec2(1.0, 0.0), limit=5, source_ids=[sid])

    assert hits == []


async def test_threshold_keeps_second_entity_evidence(vec_engine: AsyncEngine) -> None:
    """阈值要保住「第二实体」的证据——0.40 会切掉它，0.45 才留得住。

    实测反例（2026-10-26，生产库）：查询「个人医疗消费费用清单」时，
    top-1 距离 0.1855，而「本接口用于查询医保个人账户的交易明细信息。」
    距离 0.4006——那是**另一个实体**的证据，切掉它答案就变单边
    （只讲「个人医疗消费」，漏掉「医保个人账户」）。

    这条锁住阈值不能被改回 0.40：0.4006 > 0.40，那 4 条会被切掉。

    反例实现：阈值改回 0.40 —— 这条会红。
    """
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 2)
    near, second = cids
    await vectorstore.upsert_embeddings(
        vec_engine,
        [
            (near, _vec_at_cosine_distance(0.1855)),
            # 0.4006 = 实测里那条被误杀的证据的距离（≤0.45 保留，>0.40 切掉）
            (second, _vec_at_cosine_distance(0.4006)),
        ],
    )

    hits = await vectorstore.knn_search(vec_engine, _vec2(1.0, 0.0), limit=5, source_ids=[sid])

    assert {c for c, _ in hits} == {near, second}, (
        f"第二实体的证据被切掉了：{hits}"
    )


async def test_knn_keeps_row_exactly_at_threshold(
    vec_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """余弦距离**恰好等于**阈值要留下——过滤条件是 `> threshold` 而不是 `>= threshold`。

    阈值这里取 0.0，因为它能被二进制精确表示，而且「余弦距离正好 0.0」的情形
    真实存在：同向的两个向量（哪怕模长差一倍）余弦距离正好是 0.0，反向的两个
    正好是 2.0（实测逐位一致）。这样「刚好卡在阈值上」是精确的，不靠浮点误差
    碰运气——0.40 在 float32 里表示不精确，卡在 0.40 上测边界只能是随机事件。

    单维向量做不到这件事（同向恒为 0、反向恒为 2，分不出阈值内/外），
    所以边界用例必须用能控夹角的两维向量。

    这条同时锁住「阈值真的从那个常量读」——写死数字、换了常量不生效的实现会红。
    """
    monkeypatch.setattr(vectorstore, "MAX_RELEVANT_DISTANCE", 0.0)
    await ensure_vector_table(vec_engine)
    async with vec_engine.begin() as conn:
        sid, cids = await _seed_source_with_chunks(conn, 2)
    same_dir, opposite = cids
    await vectorstore.upsert_embeddings(
        vec_engine, [(same_dir, _vec2(2.0, 0.0)), (opposite, _vec2(-2.0, 0.0))]
    )

    hits = await vectorstore.knn_search(vec_engine, _vec2(1.0, 0.0), limit=5, source_ids=[sid])

    # 同向（余弦距离正好 0.0 == 阈值）留下，反向（2.0）挡掉
    assert [cid for cid, _ in hits] == [same_dir]


# ── 建数据的辅助 ────────────────────────────────────────────
def _vec2(x: float, y: float) -> list[float]:
    """造一个只有前两维非零的向量。

    余弦距离只看方向，单维向量分不出「刚好在阈值内/外」（同向恒为 0、反向恒为 2），
    所以边界用例要用两维、能控夹角的向量。
    """
    v = [0.0] * EMBEDDING_DIM
    v[0] = x
    v[1] = y
    return v


def _vec_at_cosine_distance(distance: float) -> list[float]:
    """造一个与查询向量 (1,0,…) 夹角对应的向量，余弦距离正好是 distance。

    余弦距离 = 1 - cos θ，所以 cos θ = 1 - distance；再取同夹角的正交分量凑成单位向量。
    """
    cos_theta = 1.0 - distance
    return _vec2(cos_theta, math.sqrt(1.0 - cos_theta * cos_theta))


def _constant_docstring(module: object, name: str) -> str | None:
    """取模块级常量后面紧跟的字符串字面量。

    常量的「docstring」按 PEP 258 是赋值语句后面那个独立的字符串表达式，
    运行时拿不到（`X.__doc__` 对模块级常量是 None），只能读源码。
    """
    tree = ast.parse(inspect.getsource(module))
    body = tree.body
    for idx, node in enumerate(body):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        if idx + 1 >= len(body):
            return None
        nxt = body[idx + 1]
        if (
            isinstance(nxt, ast.Expr)
            and isinstance(nxt.value, ast.Constant)
            and isinstance(nxt.value.value, str)
        ):
            return nxt.value.value
    return None


async def _seed_source_with_chunks(conn, n: int, user_id: int = 1) -> tuple[int, list[int]]:
    """建一个 user + 一个 source + n 条切片，返回 (source_id, [chunk_id...])。

    必须建 source：``knn_search`` 的 ``source_ids`` 过滤是子查询
    ``document_chunks``，chunk 没挂 source 就永远查不出来——而
    ``source_ids`` 是必填参数，不存在「不传就搜全库」这条路径。
    """
    user_id = await _seed_source(conn, "u", user_id)
    source_id = await _seed_source(conn, "资料", user_id)
    chunk_ids = [await _seed_chunk(conn, source_id, i) for i in range(n)]
    return source_id, chunk_ids


async def _seed_source(conn, title: str, user_id: int = 1) -> int:
    """裸 SQL 建 source。

    必须显式给全 NOT NULL 列——模型上的 ``default=`` 只在 ORM 层生效，
    绕过 SQLAlchemy 直接 INSERT 时数据库看不到它。
    """
    result = await conn.execute(
        text(
            "INSERT INTO sources "
            "(user_id, title, source_type, status, credibility_score, chunk_count, char_count) "
            "VALUES (:u, :t, 'text', 'indexed', 0.5, 0, 0)"
        ),
        {"u": user_id, "t": title},
    )
    return int(result.lastrowid or 0)


async def _seed_chunk(conn, source_id: int, index: int) -> int:
    result = await conn.execute(
        text(
            "INSERT INTO document_chunks (source_id, chunk_index, content, start_offset, end_offset, meta) "
            "VALUES (:s, :i, '内容', 0, 2, '{}')"
        ),
        {"s": source_id, "i": index},
    )
    return int(result.lastrowid or 0)


async def _seed_chunks(vec_engine: AsyncEngine, n: int) -> tuple[int, list[int]]:
    """建一个资料 + n 条切片，返回 (source_id, [chunk_id, ...])。

    ``knn_search`` 的 source_ids 是**必填**（漏传会串库，见函数 docstring），
    所以每条要检索的切片都必须挂在一个真实 source 下——光往向量表塞裸
    chunk_id 检索不到，因为 source 过滤是子查询 document_chunks。
    """
    async with vec_engine.begin() as conn:
        user_id = await _seed_source(conn, "u")
        source_id = await _seed_source(conn, "资料", user_id)
        chunk_ids = [await _seed_chunk(conn, source_id, i) for i in range(n)]
    return source_id, chunk_ids
