"""local_search 工具测试：真实 SQLite + 打桩嵌入。

不打网络——嵌入服务用 monkeypatch 换成定长向量。BM25 那一路是真跑的，
因为本地检索的核心价值恰恰在专有名词与同义词的互补上。

这里守两条线：
- 私域隔离（去掉 source_ids 过滤就会漏别人的资料）
- 编号跨调用稳定
"""

import contextlib
import dataclasses
import re
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.services import bm25, retriever, vectorstore
from app.services import tools as tools_module
from app.services.citation import MAX_REFERENCES, ReferenceTable
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
    排序退化成任意顺序，断言「哪条排第一」就成了随机事件。
    """
    await ensure_index_tables(engine)
    await bm25.index_chunks(engine, [(c.id, c.content) for c in chunks])
    await vectorstore.upsert_embeddings(engine, [(c.id, [0.5] * 1536) for c in chunks])


@pytest.fixture
def _stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩嵌入：给查询一个与文档向量**方向不同**的向量。

    相关性按**余弦距离**判定（见 ``vectorstore.MAX_RELEVANT_DISTANCE``），
    余弦只看方向不看模长。所以「让查询与文档可区分」必须靠**方向**，
    不能靠幅度——``[0.5]*1536`` 与 ``[0.1]*1536`` 的模长差 5 倍，
    但方向完全相同（cos = 1.0），余弦距离仍是 0，压根区分不出来。

    这里让查询的第 0 维是 0.9、其余维是 0.1，文档是 ``[0.5]*1536``：
    两者夹角很小（余弦距离约 0.04），语义上「相关」，但**不是完全相同**
    ——这样向量那一路有区分度，排序不��全靠 BM25 兜。
    """

    async def _fake(texts: list[str]) -> list[list[float]]:
        query = [0.1] * 1536
        query[0] = 0.9
        return [list(query) for _ in texts]

    monkeypatch.setattr("app.services.embedder.embed_texts", _fake)


@pytest.fixture
def _stub_embed_irrelevant(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩嵌入：查询向量与文档向量**方向相反**。

    用于验「有资料但与问题无关」这一档：余弦距离 ≈ 2.0（完全反向），
    远超 ``vectorstore.MAX_RELEVANT_DISTANCE``，向量路与 BM25 路都该把它挡掉。

    方向相反是最容易构造的「不相关」——同向的向量不管模长差多少，
    余弦距离都是 0，压根区分不出来（见 :func:`_stub_embed` 的说明）。
    """

    async def _fake(texts: list[str]) -> list[list[float]]:
        query = [-0.1] * 1536
        query[0] = -0.9
        return [list(query) for _ in texts]

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
    """空结果要明说「没法评估」——模型看到空 tool_result 会以为工具坏了，转去编造。

    两个前提缺一不可：
    - ``_no_embed``：只要向量那路能算就返回 top-K，不管距离多远，所以
      「一条都检索不到」只在它被摘掉时才成立
    - 纯字母数字的查询：jieba 会把中文句子切成单字，而 BM25 是 OR 语义，
      「不存在的词」里的「词」照样命中语料（实测）。单个乱码词才真的零交集

    **为什么文案是「无法评估」而不是「没有检索到」**（2026-10-25 修订）：
    ``_no_embed`` 意味着没配嵌入 key，**相关性从未被评估过**。这时候说
    「资料与问题不相关」是事实性错误——用户的资料可能高度相关，只是我们
    此刻没法判断。模型会照着文案对用户说，说错了就是用户的损失。
    """
    db, engine = shared_db
    uid, chunks = await _seed(db, "me4@t.local", DOCS)
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    outcome = await execute_tool("local_search", {"query": "zzzqqqxyz"}, ctx)

    assert outcome.ok
    assert "无法评估" in outcome.content
    assert "不相关" not in outcome.content
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


async def test_local_search_survives_embedding_service_failure(
    shared_db: tuple[AsyncSession, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    """嵌入服务挂了（欠费/超时），local_search 仍要能跑。

    ## 要防的回归

    ``embedder.embed_texts`` 在**欠费、超时、维度不匹配**时抛的是
    ``EmbeddingError``，只有「没配 key」才抛 ``EmbeddingNotConfiguredError``。
    只 catch 后者的话，欠费时异常会冒到工具层 → 整次 local_search 失败
    → 用户看到「接口报错、没有任何内容」。

    向量路本来就只是「降级成纯 BM25」，不该因为它挂了就让检索整体崩掉。

    反例实现：只 catch ``EmbeddingNotConfiguredError`` —— 这条会红。
    """
    from app.services.embedder import EmbeddingError

    async def _boom(texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("调用嵌入服务失败：BalanceInsufficient")

    monkeypatch.setattr("app.services.embedder.embed_texts", _boom)

    db, engine = shared_db
    uid, chunks = await _seed(db, "embed-fail@t.local", ["能效指标说明 第一段"])
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    outcome = await execute_tool("local_search", {"query": "能效"}, ctx)

    assert outcome.ok, "嵌入服务挂了不该让 local_search 失败"
    # 降级成纯 BM25：字面命中的那一条仍要能召回
    assert outcome.references, "降级成 BM25 后仍应召回字面命中的切片"
    # 且要告诉模型只做了关键词匹配
    assert "关键词匹配" in outcome.content, outcome.content


async def test_local_search_warns_when_semantic_check_could_not_run(
    shared_db: tuple[AsyncSession, AsyncEngine], _no_embed: None
) -> None:
    """没配嵌入 key 时，必须告诉模型「只做了关键词匹配」。

    ## 要防的回归

    没配 ``EMBEDDING_API_KEY`` → 查询向量算不出来 → 语义相关性下限
    **整路没跑**，只剩 BM25 的字面匹配。模型不知道这件事，会把
    「只是词沾边」的切片当成「检索到的相关证据」用。

    原始事故里那句「参保人手机 | tel | String | 50」就是这么进的上下文：
    它与「iPhone 折叠屏质量」毫无关系，只是都含「手机」。

    ## 反例实现

    不加这句提示 → 这条会红（模型无从判断这些证据的可信度）。
    """
    db, engine = shared_db
    uid, chunks = await _seed(db, "no-embed-warn@t.local", ["能效指标说明 第一段"])
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    outcome = await execute_tool("local_search", {"query": "能效"}, ctx)

    assert outcome.ok
    assert "关键词匹配" in outcome.content, outcome.content
    assert "未经确认" in outcome.content or "没有做语义" in outcome.content, outcome.content


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


# ── 检索条数与引用表容量对齐 ─────────────────────────────────
#
# 引用表 10 条封顶（MAX_REFERENCES），检索一次却要 12 条（LOCAL_SEARCH_TOP_K），
# 错配的后果是：第一次调用就把表灌满，第二次调用注册的全是新切片 → 全部被丢弃
# → 证据块是空字符串，模型只看到「编号 [1] 到 [10]」却一条证据都没有。


def test_local_search_top_k_matches_max_references() -> None:
    """检索条数必须与引用表容量一致。

    **注入回归**：把 LOCAL_SEARCH_TOP_K 改回 12 —— 这条会红。

    为什么是改检索条数而不是调大引用表：MAX_REFERENCES=10 是有意选的
    （docstring 写了「模型会被告知『编号 [1] 到 [72]』，那个跨度它根本记不住」），
    调大要重新论证；改检索条数最小，且不动那个论证。
    """
    assert tools_module.LOCAL_SEARCH_TOP_K == MAX_REFERENCES
    assert tools_module.LOCAL_SEARCH_TOP_K == 10


async def test_second_local_search_still_carries_evidence(
    shared_db: tuple[AsyncSession, AsyncEngine], _no_embed: None
) -> None:
    """第二次 local_search 的证据块不能是空字符串。

    ## 要防的回归

    第一次调用把引用表灌满 → 第二次调用注册的全是新切片 → 全部被丢弃 →
    证据块是空字符串，模型只拿到引用规则（「编号 [1] 到 [10]」）。

    本用例造一个「第一次调用留下余量」的场景：第一次命中 12 条但只有 8 种
    正文（去重后 8 条 → 表里 8 条，还剩 2 个位置），第二次命中 2 条新切片。

    ## 反例实现

    - 不做正文去重（第一次就灌满 10 条）→ 第二次证据块为空 → 这条会红
    - 去重放在截断之后（第一次仍然 10 条）→ 第二次证据块为空 → 这条会红
    """
    db, engine = shared_db
    # 前 8 条各不相同；第 9~12 条与第 1~4 条正文完全相同（实测事故里的形态：
    # 「参保人手机 | tel | String | 50」在 7388 个切片里出现 82 次）
    contents = [f"医保接口说明 第 {i} 段" for i in range(1, 9)]
    contents += [f"医保接口说明 第 {i} 段" for i in range(1, 5)]
    contents += [f"结算清单 对账口径 第 {i} 段" for i in range(1, 3)]
    uid, chunks = await _seed(db, "second-call@t.local", contents)
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    first = await execute_tool("local_search", {"query": "医保"}, ctx)
    second = await execute_tool("local_search", {"query": "结算"}, ctx)

    assert first.ok
    assert second.ok
    # 第二次的证据块不是空的——里面有新命中的那两条
    assert second.content.strip(), "第二次 local_search 的证据块是空字符串"
    assert "结算清单" in second.content, "第二次调用没带来新证据"
    # 引用表必须真的多出两条（否则第二次的证据被整段丢弃了）
    assert len(second.references) > len(first.references)
    assert {chunks[12].id, chunks[13].id} <= {r.chunk_id for r in second.references}


async def test_second_local_search_says_so_when_reference_table_is_full(
    shared_db: tuple[AsyncSession, AsyncEngine], _no_embed: None
) -> None:
    """引用表灌满后，第二次调用**不能只给一个空的证据块**。

    ## 要防的回归

    引用表封顶 ``MAX_REFERENCES = 10`` 后，超出的切片不进证据块。
    第一次调用命中 10 条互不相同的正文（**生产常态**）→ 表满 →
    第二次调用的新切片全被丢弃 → 证据块是空字符串。

    模型这时收到的是「你有一批证据，编号 [1] 到 [10]」+ **零条证据**——
    它会以为工具坏了，或者更糟：拿编号编造内容。

    ## 为什么单独立一条用例

    上面的 ``test_second_local_search_still_carries_evidence`` 造的是
    「第一次只占 8 位、留下余量」的场景——那条测的是**去重**是否生效。
    它碰不到「表真的满了」这个生产常态，那是另一条独立的失效路径。

    反例实现：证据块为空时不加任何说明 → 这条会红。
    """
    db, engine = shared_db
    # 10 条互不相同的正文 —— 第一次调用正好把引用表灌满
    contents = [f"医保接口说明 第 {i} 段" for i in range(1, 11)]
    contents += ["结算清单 对账口径 第 1 段", "结算清单 对账口径 第 2 段"]
    uid, chunks = await _seed(db, "full-table@t.local", contents)
    await _index(engine, chunks)
    ctx = _context(db, engine, uid)

    first = await execute_tool("local_search", {"query": "医保"}, ctx)
    second = await execute_tool("local_search", {"query": "结算"}, ctx)

    assert first.ok
    assert second.ok
    # 第二次没有新证据可展示（表满了），但**必须明说**
    assert second.content.strip(), "第二次 local_search 的证据块是空字符串"
    assert "引用表已满" in second.content, second.content
    # 且要指向此前已收录的编号，而不是让模型以为没有证据
    assert "[1]" in second.content, second.content


# ── 两种「0 条命中」要分开 ───────────────────────────────────


async def test_local_search_distinguishes_empty_library_from_irrelevant_materials(
    shared_db: tuple[AsyncSession, AsyncEngine], _stub_embed_irrelevant: None
) -> None:
    """两种「0 条」必须分开说。

    - 「资料库里压根没有相关内容」→ 现有文案（模型如实说明即可）
    - 「有资料但与问题无关，被相关性下限过滤掉了」→ 新文案，要明确告诉模型
      **这些资料与问题无关，不要拿它们当证据**

    反例实现：
    - 两种情况说同一句话 —— 这条会红（模型会以为资料库是空的）
    - 新的那档根本没实现（不相关查询照旧召回无关切片）—— 这条会红
    """
    db, engine = shared_db
    # 空资料库：连 source 都没有
    empty_user = User(email="empty-lib@t.local", display_name="t")
    db.add(empty_user)
    await db.commit()
    await db.refresh(empty_user)

    # 有资料，但与问题无关：正文里带「手机」，BM25 会字面命中（OR 语义），
    # 向量距离又远得离谱——两路都得被相关性下限挡掉
    uid, chunks = await _seed(db, "irrelevant@t.local", ["参保人手机 | tel | String | 50"])
    await _index(engine, chunks)

    query = "手机 质量 参数"
    empty = await execute_tool(
        "local_search", {"query": query}, _context(db, engine, empty_user.id)
    )
    irrelevant = await execute_tool("local_search", {"query": query}, _context(db, engine, uid))

    assert empty.references == ()
    assert irrelevant.references == ()
    # 空资料库：沿用现有文案
    assert "没有检索到" in empty.content
    # 有资料但无关：文案必须与空资料库那档不同，且点明「与问题无关」
    irrelevant_text = irrelevant.content
    assert irrelevant_text != empty.content
    relevance_words = ("无关", "不相关", "不匹配", "无关联", "相关性")
    assert any(k in irrelevant_text for k in relevance_words), irrelevant_text


# ── 新错误码要能被调用方拿到 ─────────────────────────────────


def _retrieval_codes() -> list[str]:
    """errors.__all__ 里语义属于「检索没命中」的错误码。

    规格给了建议名但允许自选（「但你可以选更好的名字」），所以按语义关键词找。
    """
    from app.services import errors as errors_module

    exported = getattr(errors_module, "__all__", [])
    pattern = re.compile(r"(match|retriev|relevan|irrelev)")
    return [code for code in exported if pattern.search(code)]


def _codes_on(outcome: object) -> set[str]:
    """把工具结果上所有可能的错误码挖出来。

    实现方式规格没定（ToolOutcome 上加字段 / 把 code 写进文案都可能），
    所以这里把结果对象上的字符串字段全扫一遍。
    """
    found: set[str] = set()
    values: list[str] = []
    with contextlib.suppress(TypeError):
        values.extend(v for v in vars(outcome).values() if isinstance(v, str))
    with contextlib.suppress(TypeError):
        for field in dataclasses.fields(outcome):  # type: ignore[arg-type]
            value = getattr(outcome, field.name, None)
            if isinstance(value, str):
                values.append(value)
    found.update(values)
    text = f"{getattr(outcome, 'content', '')} {getattr(outcome, 'preview', '')}"
    found.update(code for code in _retrieval_codes() if code in text)
    return found


async def test_local_search_no_match_carries_the_new_error_code(
    shared_db: tuple[AsyncSession, AsyncEngine], _stub_embed_irrelevant: None
) -> None:
    """「有资料但全被相关性过滤掉」这一档的 code 必须能被调用方拿到。

    规格要求这个 code 能出现在**用户可见的错误横幅**上——前端渲染的是 error 帧的
    code / message / retryable。agent 拿到的是工具结果而不是原始异常，
    所以 code 必须能从工具结果上取出来，否则这一档永远显示不出来。

    反例实现：新错误码只写进了错误文案、工具结果上取不到 —— 这条会红。
    """
    db, engine = shared_db
    uid, chunks = await _seed(db, "no-match@t.local", ["参保人手机 | tel | String | 50"])
    await _index(engine, chunks)

    outcome = await execute_tool(
        "local_search", {"query": "手机 质量 参数"}, _context(db, engine, uid)
    )

    codes = _retrieval_codes()
    assert codes, "errors.__all__ 里必须有「检索无相关性」这一档的错误码"
    found = _codes_on(outcome) & set(codes)
    assert found, f"工具结果上找不到新错误码（候选 {codes}），调用方拿不到它"
