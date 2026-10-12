"""BM25 检索的测试。

核心是 **2 字中文词能不能查到**——这是本层存在的唯一理由。
实测 FTS5 的 trigram 分词器对「能效」「营收」「算力」「功耗」全部返回 0 条，
默认的 unicode61 更是把整句当一个词。所以必须 jieba 预分词。
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Base
from app.services import bm25
from app.services.vectorstore import create_vector_engine

DOCS = [
    (1, "NVIDIA Blackwell 架构能效比 Hopper 提升 2.5 倍"),
    (2, "公司本季度营业收入 32.1 亿美元，同比增长 22%"),
    (3, "数据中心电力消耗锐减 75%"),
    (4, "算力需求激增，供电成为新瓶颈"),
]


@pytest_asyncio.fixture
async def engine(tmp_path) -> AsyncIterator[AsyncEngine]:
    eng = create_vector_engine(f"sqlite+aiosqlite:///{tmp_path / 'bm25.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await bm25.ensure_fts_table(eng)
    await bm25.index_chunks(eng, DOCS)
    yield eng
    await eng.dispose()


# ── 分词 ───────────────────────────────────────────────────
def test_tokenize_splits_cjk_into_words() -> None:
    """「营业收入」要能被切开，否则 FTS5 把它当整串匹配。"""
    tokens = bm25.tokenize("公司本季度营业收入").split()

    assert "营业收入" not in tokens, "jieba 应该切分而不是保留整词"
    assert len(tokens) > 1


def test_tokenize_keeps_ascii_terms() -> None:
    """专有名词不能被切碎——BM25 的价值就在精确匹配 H100 这类词。"""
    tokens = bm25.tokenize("使用 H100 和 Blackwell 训练").split()

    assert "h100" in tokens or "H100" in tokens
    assert "blackwell" in tokens or "Blackwell" in tokens


def test_tokenize_drops_punctuation_and_space() -> None:
    """标点会产生空 token，FTS5 里是噪音。"""
    tokens = bm25.tokenize("能效，提升，  75%。").split()

    assert all(t.strip() for t in tokens)
    assert "," not in tokens and "。" not in tokens


# ── 2 字中文词（本层存在的理由）─────────────────────────────
@pytest.mark.parametrize(
    ("query", "expect_id"),
    [
        ("能效", 1),  # 2 字
        ("算力", 4),  # 2 字
        ("电力消耗", 3),  # 4 字
        ("Hopper", 1),  # 英文专有名词——BM25 的真正强项
    ],
)
async def test_finds_chinese_terms(
    engine: AsyncEngine, query: str, expect_id: int
) -> None:
    hits = await bm25.search(engine, query, limit=10)

    assert expect_id in [h.chunk_id for h in hits], f"「{query}」查不到 # {expect_id}"


async def test_synonym_is_missed_and_that_is_expected(engine: AsyncEngine) -> None:
    """「营收」查不到含「营业收入」的文档——这是已知的召回缺口。

    jieba 把「营业收入」切成「营业 收入」，文档里压根没有「营收」这两个字，
    2 字滑窗也救不了（原文滑窗是「业收」）。这类同义词靠向量那一路兜。

    这条测试的作用是**把这个缺口钉在测试里**：哪天换了分词策略或加了同义词
    扩展，它会失败提醒你更新预期，而不是默默变成另一个行为。
    """
    assert await bm25.search(engine, "营收", limit=10) == []
    # 但「营业收入」本身查得到
    assert len(await bm25.search(engine, "营业收入", limit=10)) == 1


# ── 排序 ───────────────────────────────────────────────────
async def test_ranks_best_match_first(engine: AsyncEngine) -> None:
    hits = await bm25.search(engine, "电力消耗", limit=10)

    assert hits[0].chunk_id == 3


async def test_score_is_ascending(engine: AsyncEngine) -> None:
    """bm25() 返回负分，越小越相关。"""
    hits = await bm25.search(engine, "收入", limit=10)

    scores = [h.score for h in hits]
    assert scores == sorted(scores)


async def test_respects_limit(engine: AsyncEngine) -> None:
    assert len(await bm25.search(engine, "能效 收入 电力 算力", limit=2)) <= 2


# ── 空与边界 ───────────────────────────────────────────────
async def test_empty_query_returns_nothing(engine: AsyncEngine) -> None:
    """空查询不该发 MATCH——FTS5 对空 pattern 会报错。"""
    assert await bm25.search(engine, "", limit=10) == []
    assert await bm25.search(engine, "   ", limit=10) == []
    assert await bm25.search(engine, "!!!", limit=10) == []


async def test_no_match_returns_nothing(engine: AsyncEngine) -> None:
    assert await bm25.search(engine, "完全无关的词条", limit=10) == []


async def test_indexing_empty_is_noop(engine: AsyncEngine) -> None:
    assert await bm25.index_chunks(engine, []) is None


# ── 重跑 ───────────────────────────────────────────────────
async def test_reindex_replaces_not_duplicates(engine: AsyncEngine) -> None:
    """FTS5 没有 upsert，靠先 DELETE 再 INSERT。"""
    await bm25.index_chunks(engine, [(1, "完全不同的新内容 关于量子计算")])

    hits = await bm25.search(engine, "量子计算", limit=10)

    assert [h.chunk_id for h in hits] == [1]
    # 旧内容不该还能查到
    assert await bm25.search(engine, "Hopper", limit=10) == []


async def test_ensure_table_is_idempotent(engine: AsyncEngine) -> None:
    await bm25.ensure_fts_table(engine)
    await bm25.ensure_fts_table(engine)


# ── 私域隔离 ───────────────────────────────────────────────
async def test_filters_by_source_ids(engine: AsyncEngine) -> None:
    """source_ids 之外的一律看不见——两路检索都必须做这件事。"""
    # 先建资料行让子查询能命中
    async with engine.begin() as conn:
        for cid, _ in DOCS:
            await conn.exec_driver_sql(
                "INSERT INTO document_chunks "
                "(id, source_id, chunk_index, content, start_offset, end_offset, meta) "
                f"VALUES ({cid}, {cid}, 0, 'x', 0, 1, '{{}}')"
            )

    hits = await bm25.search(engine, "能效", limit=10, source_ids=[1])

    assert [h.chunk_id for h in hits] == [1]


async def test_empty_source_ids_short_circuits(engine: AsyncEngine) -> None:
    """空集合要短路——生成 ``IN ()`` 是语法错误。"""
    assert await bm25.search(engine, "能效", limit=10, source_ids=[]) == []
