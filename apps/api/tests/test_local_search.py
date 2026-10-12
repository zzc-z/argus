"""local_search 工具测试：真实 SQLite + 打桩嵌入。

不打网络——嵌入服务用 monkeypatch 换成定长向量。BM25 那一路是真跑的，
因为本地检索的核心价值恰恰在专有名词与同义词的互补上。

这里守两条线：
- 私域隔离（去掉 source_ids 过滤就会漏别人的资料）
- 编号跨调用稳定
"""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.services import bm25, retriever, vectorstore
from app.services import tools as tools_module
from app.services.citation import ReferenceTable
from app.services.ingest import ensure_index_tables
from app.services.tools import ToolContext, execute_tool

DOCS = [
    "NVIDIA Blackwell 架构能效比 Hopper 提升 2.5 倍，是新一代的核心指标",
    "公司本季度营业收入 32.1 亿美元，同比增长 22%",
]


async def _seed(db: AsyncSession, email: str, contents: list[str]) -> tuple[int, list[DocumentChunk]]:
    user = User(email=email, display_name="t")
    db.add(user)
    await db.flush()
    source = Source(
        user_id=user.id,
        title="测试资料",
        source_type=SourceType.TEXT,
        status=SourceStatus.INDEXED,
    )
    db.add(source)
    await db.flush()
    chunks = [
        DocumentChunk(source_id=source.id, chunk_index=i, content=c, page=i + 1)
        for i, c in enumerate(contents)
    ]
    db.add_all(chunks)
    await db.commit()
    for c in chunks:
        await db.refresh(c)
    return user.id, chunks


async def _index(engine: AsyncEngine, chunks: list[DocumentChunk]) -> None:
    """按**各自的**正文建 BM25 索引。

    不能图省事给所有切片写同一段文本——那样 BM25 对每条的评分完全相同，
    排序退化成任���，断言「哪条排第一」就成了随机事件。
    """
    await ensure_index_tables(engine)
    await bm25.index_chunks(engine, [(c.id, c.content) for c in chunks])
    await vectorstore.upsert_embeddings(engine, [(c.id, [0.5] * 1536) for c in chunks])


@pytest.fixture
def _stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩嵌入：给查询一个与文档向量可区分的方向。

    向量距离是 L2，给查询 [0.5]*1536 而文档也是 [0.5]*1536，距离为 0——
    完全命中。所有切片都「同样相关」，向量那一路就没有区分度，
    排序全靠 BM25 兜。想验语义那一路得让查询向量与文档向量分开。
    """

    async def _fake(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr("app.services.embedder.embed_texts", _fake)


@pytest.fixture
def _no_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟未配置 embedding key——检索降级成纯 BM25。

    这是唯一能确定拿到「0 条命中」的组合：向量那一路只要能算就会返回
    top-K，压根不管距离多远，所以「检索不到」只在 BM25 也没命中时成立。
    """

    async def _fake(texts: list[str]) -> list[list[float]]:
        from app.services.embedder import EmbeddingNotConfiguredError

        raise EmbeddingNotConfiguredError("未配置")

    monkeypatch.setattr("app.services.embedder.embed_texts", _fake)


def _context(db: AsyncSession, engine: AsyncEngine, user_id: int) -> ToolContext:
    return ToolContext(db=db, vec_engine=engine, user_id=user_id, citations=ReferenceTable())


# ── 基本路径 ──────────────────────────────────────────────────


async def test_local_search_returns_numbered_evidence(
    shared_db: tuple[AsyncSession, AsyncEngine], _stub_embed: None
) -> None:
    db, engine = shared_db
    uid, chunks = await _seed(db, "me@t.local", DOCS)
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    outcome = await execute_tool("local_search", {"query": "能效"}, ctx)

    assert outcome.ok
    assert "[1]" in outcome.content


async def test_local_search_emits_references(
    shared_db: tuple[AsyncSession, AsyncEngine], _stub_embed: None
) -> None:
    """references 要回传给 agent，由它转成前端的 reference 事件。"""
    db, engine = shared_db
    uid, chunks = await _seed(db, "me2@t.local", DOCS)
    await _index(engine, chunks)

    outcome = await execute_tool("local_search", {"query": "能效"}, _context(db, engine, uid))

    assert outcome.references
    assert outcome.references[0].chunk_id == chunks[0].id


async def test_local_search_rejects_blank_query(
    shared_db: tuple[AsyncSession, AsyncEngine],
) -> None:
    db, engine = shared_db
    uid, _ = await _seed(db, "me3@t.local", DOCS)

    outcome = await execute_tool("local_search", {"query": "   "}, _context(db, engine, uid))

    assert not outcome.ok
    assert "不能为空" in outcome.content


async def test_local_search_without_context_returns_error(
    shared_db: tuple[AsyncSession, AsyncEngine],
) -> None:
    """没有 db 时返回错误字符串，而不是 AttributeError 崩流。"""
    outcome = await execute_tool("local_search", {"query": "能效"}, None)

    assert not outcome.ok
    assert "上下文" in outcome.content


async def test_local_search_zero_hits_tells_model_not_to_invent(
    shared_db: tuple[AsyncSession, AsyncEngine], _no_embed: None
) -> None:
    """空结果要明说「没有」——模型看到空 tool_result 会以为工具坏了，转去编造。

    两个前提缺一不可：
    - ``_no_embed``：只要向量那路能算就返回 top-K，不管距离多远，所以
      「一条都检索不到」只在它被摘掉时才成立
    - 纯字母数字的查询：jieba 会把中文句子切成单字，而 BM25 是 OR 语义，
      「不存在的词」里的「词」照样命中语料（实测）。单个乱码词才真的零交集
    """
    db, engine = shared_db
    uid, chunks = await _seed(db, "me4@t.local", DOCS)
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    outcome = await execute_tool("local_search", {"query": "zzzqqqxyz"}, ctx)

    assert outcome.ok
    assert "没有检索到" in outcome.content
    assert outcome.references == ()


# ── 私域隔离 ──────────────────────────────────────────────────


async def test_local_search_never_leaks_other_users_chunks(
    shared_db: tuple[AsyncSession, AsyncEngine], _stub_embed: None
) -> None:
    """最关键的一条：查不到别人的资料。"""
    db, engine = shared_db
    _other_uid, theirs = await _seed(db, "them@t.local", DOCS)
    my_uid, _mine = await _seed(db, "me5@t.local", [])
    await _index(engine, theirs)

    outcome = await execute_tool("local_search", {"query": "能效"}, _context(db, engine, my_uid))

    assert outcome.references == ()


async def test_local_search_isolates_when_both_have_data(
    shared_db: tuple[AsyncSession, AsyncEngine], _stub_embed: None
) -> None:
    """两人都有资料时，只返回自己的那一条。"""
    db, engine = shared_db
    my_uid, mine = await _seed(db, "me6@t.local", DOCS)
    _other, theirs = await _seed(db, "them2@t.local", DOCS)
    await _index(engine, mine + theirs)

    outcome = await execute_tool("local_search", {"query": "能效"}, _context(db, engine, my_uid))

    assert {ref.chunk_id for ref in outcome.references} == {c.id for c in mine}


# ── 编号跨调用稳定 ────────────────────────────────────────────


async def test_numbering_stable_across_two_calls(
    shared_db: tuple[AsyncSession, AsyncEngine], _no_embed: None
) -> None:
    """两次调用的编号不能重叠——否则正文里同一个 [1] 指两个切片。

    走 ``_no_embed`` 是刻意的：向量那一路只要能算就返回 top-K，两次查询
    都会拿到全部切片，编号自然重合，测不出「续编」。让 BM25 一路按关键词
    精确命中不同切片，才能观察到编号往前走。
    """
    db, engine = shared_db
    uid, chunks = await _seed(db, "me7@t.local", DOCS)
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    # 「能效」「营业收入」是语料里唯一且互不重叠的词（jieba 切出来是
    # 「能效」与「营业 收入」），所以 BM25 各只命中一片。
    first = await execute_tool("local_search", {"query": "能效"}, ctx)
    second = await execute_tool("local_search", {"query": "营业收入"}, ctx)

    assert [r.chunk_id for r in first.references] == [chunks[0].id]
    # 第二次返回的是**全量**引用表（前端要的是整张表，不是增量），
    # 所以第一片仍占 1 号，新命中的那片续编成 2 号——而不是重头从 1 开始。
    assert [(r.n, r.chunk_id) for r in second.references] == [
        (1, chunks[0].id),
        (2, chunks[1].id),
    ]


async def test_repeated_query_does_not_duplicate_references(
    shared_db: tuple[AsyncSession, AsyncEngine], _no_embed: None
) -> None:
    """模型重复调同一个查询时，引用表不该翻倍。"""
    db, engine = shared_db
    uid, chunks = await _seed(db, "me7b@t.local", DOCS)
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    await execute_tool("local_search", {"query": "能效"}, ctx)
    second = await execute_tool("local_search", {"query": "能效"}, ctx)

    assert len(second.references) == len({r.n for r in second.references})


# ── 与 retriever 的接线 ───────────────────────────────────────


async def test_local_search_delegates_to_retrieve(
    shared_db: tuple[AsyncSession, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    """确保走的是 retriever.retrieve 而不是自己查一遍——重复实现必然漂移。"""
    seen: dict[str, Any] = {}

    async def _fake_retrieve(*args: Any, **kwargs: Any) -> list[Any]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(retriever, "retrieve", _fake_retrieve)
    db, engine = shared_db
    uid, _ = await _seed(db, "me9@t.local", DOCS)

    await execute_tool("local_search", {"query": "q"}, _context(db, engine, uid))

    assert seen["user_id"] == uid
    assert seen["limit"] == tools_module.LOCAL_SEARCH_TOP_K


def test_local_search_schema_declares_query() -> None:
    spec = tools_module.LOCAL_SEARCH_SPEC
    assert "query" in spec.input_schema["properties"]
    assert spec.input_schema["required"] == ["query"]
