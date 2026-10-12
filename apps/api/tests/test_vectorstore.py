"""vectorstore 的测试。

重点不是「能不能搜」，而是**扩展到底加载上没有**——sqlite-vec 加载失败时
不报任何错，只是后续所有 vec_* 调用报 "no such function"。
下面每个用例都先断言 vec_version() 可用，等于在测这个前提本身。
"""

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
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(1, _vec(1.0, seed=0)), (2, _vec(0.8, seed=0)), (3, _vec(0.5, seed=0))],
    )

    hits = await vectorstore.knn_search(vec_engine, _vec(1.0, seed=0), limit=3)

    assert [cid for cid, _ in hits] == [1, 2, 3]
    assert hits[0][1] == pytest.approx(0.0, abs=1e-5)


async def test_knn_distance_increases(vec_engine: AsyncEngine) -> None:
    """距离必须递增，否则排序逻辑是错的。"""
    await ensure_vector_table(vec_engine)
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(1, _vec(1.0, seed=0)), (2, _vec(0.5, seed=0))],
    )

    hits = await vectorstore.knn_search(vec_engine, _vec(1.0, seed=0), limit=2)

    assert hits[0][1] < hits[1][1]


async def test_knn_limit_respected(vec_engine: AsyncEngine) -> None:
    await ensure_vector_table(vec_engine)
    await vectorstore.upsert_embeddings(
        vec_engine,
        [(i + 1, _vec(1.0 - i / EMBEDDING_DIM)) for i in range(20)],
    )

    hits = await vectorstore.knn_search(vec_engine, _vec(1.0), limit=5)

    assert len(hits) == 5


async def test_knn_on_empty_table_returns_nothing(vec_engine: AsyncEngine) -> None:
    await ensure_vector_table(vec_engine)

    assert await vectorstore.knn_search(vec_engine, _vec(), limit=5) == []


async def test_upsert_replaces_existing(vec_engine: AsyncEngine) -> None:
    """重跑摄取会重复写同一 chunk_id，旧向量必须被替换而不是重复插入。"""
    await ensure_vector_table(vec_engine)
    await vectorstore.upsert_embeddings(vec_engine, [(1, _vec(1.0, seed=0))])
    await vectorstore.upsert_embeddings(vec_engine, [(1, _vec(1.0, seed=1))])

    hits = await vectorstore.knn_search(vec_engine, _vec(1.0, seed=1), limit=5)

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
        await vectorstore.knn_search(vec_engine, [0.1, 0.2, 0.3], limit=5)


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
    await vectorstore.upsert_embeddings(vec_engine, [(1, stored)])

    hits = await vectorstore.knn_search(vec_engine, query, limit=1)
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
    await vectorstore.upsert_embeddings(
        vec_engine, [(i + 1, v) for i, v in enumerate(candidates)]
    )

    hits = await vectorstore.knn_search(vec_engine, query, limit=4)
    by_cos = sorted(
        range(len(candidates)),
        key=lambda i: -_cosine(query, candidates[i]),
    )

    assert [cid - 1 for cid, _ in hits] == by_cos


# ── 建数据的辅助 ────────────────────────────────────────────
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
