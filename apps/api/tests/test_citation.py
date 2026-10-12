"""Citation Builder 测试。

编号分配是这里唯一有真实风险的逻辑——错了不会报错，只会让用户点角标
跳到错的原文。所以重点覆盖跨调用稳定性与去重。
"""

from app.models import DocumentChunk, Source, SourceStatus, SourceType
from app.services.citation import (
    MAX_REFERENCES,
    ReferenceTable,
    citation_rules,
    render_evidence,
)
from app.services.retriever import Retrieved


def _make(
    content: str = "内容",
    *,
    page: int | None = None,
    idx: int = 0,
    title: str = "测试资料",
    vector_rank: int | None = 1,
    bm25_rank: int | None = None,
) -> Retrieved:
    """造一个 Retrieved。真实对象关系太重，这里只喂 citation 读到的字段。"""
    chunk = DocumentChunk(id=idx + 1, source_id=1, chunk_index=idx, content=content, page=page)
    source = Source(
        id=1,
        user_id=1,
        title=title,
        source_type=SourceType.TEXT,
        status=SourceStatus.INDEXED,
    )
    return Retrieved(
        chunk=chunk,
        source=source,
        rrf_score=0.016,
        vector_rank=vector_rank,
        bm25_rank=bm25_rank,
    )


# ── 编号 ──────────────────────────────────────────────────────


def test_numbers_start_at_one() -> None:
    """从 1 起：0 容易被误读成「未标注」，也与 PRD §9.1 的示例不一致。"""
    table = ReferenceTable()
    pairs = table.register([_make(idx=0), _make(idx=1)])

    assert [ref.n for ref, _ in pairs] == [1, 2]


def test_numbers_follow_retrieval_rank() -> None:
    table = ReferenceTable()
    results = [_make(idx=0), _make(idx=1), _make(idx=2)]

    pairs = table.register(results)

    assert [ref.chunk_id for ref, _ in pairs] == [r.chunk.id for r in results]


def test_second_call_continues_numbering() -> None:
    """最关键的一条：第二次调用不能从 1 重编，否则正文里的 [1] 会指错。"""
    table = ReferenceTable()
    table.register([_make(idx=0)])
    pairs = table.register([_make(idx=1)])

    assert [ref.n for ref, _ in pairs] == [2]


def test_repeated_chunk_reuses_its_number() -> None:
    """同一个切片被两轮召回时不能占两个号——那会让引用表凭空多一条。"""
    table = ReferenceTable()
    first = table.register([_make(idx=0)])
    second = table.register([_make(idx=0), _make(idx=1)])

    assert [ref.n for ref, _ in second] == [first[0][0].n, 2]
    assert len(table.all) == 2


def test_all_is_sorted_by_number() -> None:
    """all 给前端用，必须按编号升序——顺序乱了角标映射就错。"""
    table = ReferenceTable()
    table.register([_make(idx=0)])
    table.register([_make(idx=1), _make(idx=2)])

    assert [ref.n for ref in table.all] == [1, 2, 3]


def test_all_starts_empty() -> None:
    assert ReferenceTable().all == []


# ── 引用表上限 ────────────────────────────────────────────────


def test_table_caps_at_max_references() -> None:
    """不封顶的话 6 轮 × 12 片能堆到 72 条，模型记不住那么大的编号跨度。"""
    table = ReferenceTable()

    table.register([_make(idx=i) for i in range(20)])

    assert len(table.all) == MAX_REFERENCES
    assert [r.n for r in table.all] == list(range(1, MAX_REFERENCES + 1))


def test_dropped_count_is_reported() -> None:
    table = ReferenceTable()
    table.register([_make(idx=i) for i in range(20)])

    assert table.dropped == 20 - MAX_REFERENCES


def test_dropped_still_reuses_existing_numbers() -> None:
    """表满之后，已编过号的切片仍要能用——模型可能换个词再查一次同一片。"""
    table = ReferenceTable()
    table.register([_make(idx=0), _make(idx=1)])
    table.register([_make(idx=0), _make(idx=1)])

    assert [r.n for r in table.all] == [1, 2]
    assert table.dropped == 0


def test_rules_tell_model_more_exists() -> None:
    """截断了就要明说，否则模型会以为资料库就这么大。"""
    table = ReferenceTable()
    table.register([_make(idx=i) for i in range(20)])

    assert "没有展示" in citation_rules(table)


def test_rules_omit_overflow_note_when_nothing_dropped() -> None:
    table = ReferenceTable()
    table.register([_make(idx=0), _make(idx=1)])

    assert "没有展示" not in citation_rules(table)


def test_dropped_accumulates_across_calls() -> None:
    table = ReferenceTable()
    table.register([_make(idx=i) for i in range(12)])
    table.register([_make(idx=i) for i in range(12, 20)])

    assert table.dropped == 20 - MAX_REFERENCES


# ── 引用内容 ──────────────────────────────────────────────────


def test_reference_carries_locator_fields() -> None:
    """前端跳原文靠 source_id + chunk_id + page，缺一个就跳不动。"""
    table = ReferenceTable()
    pairs = table.register([_make(page=3, idx=5)])

    ref = pairs[0][0]
    assert ref.source_id == 1
    assert ref.chunk_index == 5
    assert ref.page == 3


def test_page_is_none_for_non_pdf() -> None:
    table = ReferenceTable()
    pairs = table.register([_make(page=None)])

    assert pairs[0][0].page is None


# ── 前端契约 ──────────────────────────────────────────────────


def test_to_citation_matches_frontend_shape() -> None:
    """字段名必须对上前端 ``Citation``，否则点角标拿不到数据。

    前端定义在 ``apps/web/app/(dashboard)/explore/mock.ts``：
    ``{ id, sourceTitle, url, date }``，由
    ``InspectorDrawer.buildCitationPayload`` 直接消费。字段名对不上就
    得在前端多写一层转换，而那个转换迟早会漏。
    """
    table = ReferenceTable()
    ref = table.register([_make("正文", page=2, idx=0)])[0][0]

    payload = ref.to_citation()

    for frontend_field in ("id", "sourceTitle"):
        assert frontend_field in payload, f"前端要 {frontend_field}，后端没给"


def test_to_citation_uses_camel_case_source_title() -> None:
    """``sourceTitle`` 是 camelCase——前端那个文件通篇 camelCase。"""
    table = ReferenceTable()
    ref = table.register([_make(idx=0, title="财报")])[0][0]

    assert ref.to_citation()["sourceTitle"] == "财报"


def test_to_citation_id_matches_numbering() -> None:
    """前端的 ``id`` 就是正文里的 ``[n]``，两者必须一致。"""
    table = ReferenceTable()
    pairs = table.register([_make(idx=0), _make(idx=1)])

    assert [p[0].to_citation()["id"] for p in pairs] == [1, 2]


def test_to_citation_carries_locator_for_chunk_fetch() -> None:
    """前端点开后要调 ``GET /sources/{id}/chunks``，得知道去哪个 source 取哪一片。"""
    table = ReferenceTable()
    ref = table.register([_make(page=3, idx=5)])[0][0]

    payload = ref.to_citation()

    assert payload["source_id"] == 1
    assert payload["chunk_id"] == ref.chunk_id
    assert payload["page"] == 3


def test_to_citation_is_json_serializable() -> None:
    """最终要进 SSE 帧——含 datetime 之类会直接炸掉。"""
    import json

    table = ReferenceTable()
    ref = table.register([_make(page=1, idx=0)])[0][0]

    assert json.loads(json.dumps(ref.to_citation()))["id"] == 1


def test_recall_label_marks_double_hits() -> None:
    """两路都命中说明证据强，前端给更高的置信样式。"""
    table = ReferenceTable()
    both = table.register([_make(idx=0, vector_rank=1, bm25_rank=2)])
    vec_only = table.register([_make(idx=1, vector_rank=1, bm25_rank=None)])
    bm25_only = table.register([_make(idx=2, vector_rank=None, bm25_rank=1)])

    assert both[0][0].recall == "向量+BM25"
    assert vec_only[0][0].recall == "向量"
    assert bm25_only[0][0].recall == "BM25"


def test_excerpt_is_truncated() -> None:
    """excerpt 只给 tooltip 用，太长会让 reference 事件膨胀。"""
    table = ReferenceTable()
    pairs = table.register([_make("字" * 500, idx=0)])

    assert len(pairs[0][0].excerpt) < 200


def test_excerpt_untouched_when_short() -> None:
    table = ReferenceTable()
    pairs = table.register([_make("很短", idx=0)])

    assert pairs[0][0].excerpt == "很短"


# ── 证据块渲染 ────────────────────────────────────────────────


def test_evidence_contains_number_and_page() -> None:
    table = ReferenceTable()
    pairs = table.register([_make("能效提升 2.5 倍", page=3, idx=1)])

    text = render_evidence(pairs)

    assert "[1] 测试资料（第 3 页，第 2 段）" in text
    assert "能效提升 2.5 倍" in text


def test_evidence_omits_page_for_non_pdf() -> None:
    """没有页码时硬写「第 None 页」——前端会直接显示出来。"""
    table = ReferenceTable()
    pairs = table.register([_make("内容", page=None, idx=0)])

    assert render_evidence(pairs) == "[1] 测试资料（第 1 段）\n内容"


def test_evidence_full_body_not_excerpt() -> None:
    """喂模型必须给完整正文，只给 120 字前缀等于让它猜。"""
    table = ReferenceTable()
    body = "字" * 500
    pairs = table.register([_make(body, idx=0)])

    text = render_evidence(pairs)

    assert body in text


def test_evidence_empty_when_no_results() -> None:
    assert render_evidence([]) == ""


def test_second_call_renders_its_own_number() -> None:
    """第二轮的证据块要带续编的号，否则模型回引时对不上第一轮。"""
    table = ReferenceTable()
    table.register([_make("第一块", idx=0)])
    pairs = table.register([_make("第二块", idx=1)])

    assert render_evidence(pairs).startswith("[2]")


# ── 写作规则 ──────────────────────────────────────────────────


def test_rules_empty_without_references() -> None:
    assert citation_rules(ReferenceTable()) == ""


def test_rules_state_the_valid_range() -> None:
    """必须显式给上界，否则模型会自己编 [7]。"""
    table = ReferenceTable()
    table.register([_make(idx=0), _make(idx=1), _make(idx=2)])

    rules = citation_rules(table)

    assert "[1] 到 [3]" in rules
    assert "严禁编造" in rules


def test_rules_use_table_total_not_last_call_size() -> None:
    """模型可能第三轮才首次用工具，拿「本轮号数」当上界会漏掉前两轮。"""
    table = ReferenceTable()
    table.register([_make(idx=0), _make(idx=1)])
    table.register([_make(idx=2)])

    assert "[1] 到 [3]" in citation_rules(table)
