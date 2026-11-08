"""研究报告的测试。

分两块：**落盘**（agent 跑完时写 reports）与 **读取**（reports 路由）。

落盘那部分的每个用例都写明了「它要防的具体回归」——因为这一层的失败
模式是**静默**的：DB 写不进去时流照样结束，用户拿到完整报告，只是历史
报告里没有它。症状极隐蔽，没有断言盯着就会一直漏。
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.models.report import Report, ReportSource
from app.services import agent as agent_mod
from app.services import persistence as persistence_mod
from app.services.citation import Reference
from app.services.stream import DoneEvent
from tests.conftest import turn_chunks


# ── helpers ───────────────────────────────────────────────
async def _user(db: AsyncSession, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0])
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _source(db: AsyncSession, user_id: int, title: str = "资料") -> Source:
    source = Source(
        user_id=user_id,
        title=title,
        source_type=SourceType.TEXT,
        status=SourceStatus.INDEXED,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def _chunk(
    db: AsyncSession, source_id: int, content: str = "正文", index: int = 0
) -> DocumentChunk:
    chunk = DocumentChunk(
        source_id=source_id,
        chunk_index=index,
        content=content,
        page=None,
        start_offset=0,
        end_offset=len(content),
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return chunk


def _ref(n: int, chunk: DocumentChunk, source: Source) -> Reference:
    return Reference(
        n=n,
        chunk_id=chunk.id,
        source_id=source.id,
        chunk_index=chunk.chunk_index,
        page=chunk.page,
        title=source.title,
        excerpt=chunk.content[:120],
        recall="向量",
    )


def _auth(client: TestClient, user: User | int) -> None:
    from app.services.token import create_access_token

    uid = user.id if isinstance(user, User) else user
    client.cookies.set("argus_session", create_access_token(uid))


async def _fake_turn(
    client: Any, messages: list[dict[str, Any]], tools: Any
) -> AsyncIterator[agent_mod.TurnChunk]:
    """一轮就产出正文的假模型。"""
    from app.services import agent as agent_mod

    for chunk in turn_chunks(
        agent_mod.TurnResult(
            text="结论如上[1]。",
            tool_calls=[],
            content=[],
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
        )
    ):
        yield chunk


async def _fake_verify(client: Any, report_text: str, sources: dict[int, str]) -> Any:
    """跳过 critic 的 LLM 判定，返回「未校验」。

    落盘与校验是两件事，这个用例只关心前者。让真 judge 跑既慢又会
    发网络请求，而结论不影响 reports 里的任何一行。
    """
    from app.services.faithfulness import (
        SKIPPED_REASON_NO_MODEL,
        FaithfulnessReport,
    )

    return FaithfulnessReport(
        checked=0,
        supported=0,
        unsupported=[],
        missing=[],
        skipped=True,
        reason=SKIPPED_REASON_NO_MODEL,
    )


# ── 落盘：成功的路径 ───────────────────────────────────────
async def test_report_persisted_with_citations(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跑完一次，reports 里有这份报告，引用关系也在。

    角标 ``n`` 必须落盘：正文里写死了 ``[1]``，不存它的话报告详情页
    拿不到「角标 1 指向哪个切片」。

    ``collected_refs`` 是经 ``_run_tools`` 累积的，所以假模型第一轮必须
    **先请求工具**、第二轮才产出正文——否则 collected_refs 全空，
    断言「有一行引用」会通过而实际上什么都没验证到。
    """
    from app.services import agent as agent_mod

    user = await _user(db_session, "u@report.test")
    source = await _source(db_session, user.id)
    chunk = await _chunk(db_session, source.id)

    calls = {"n": 0}

    async def _two_turns(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        """第一轮请求工具，第二轮产出正文。

        **只有第一轮给 tool_calls**：主循环看到工具调用就继续，而一旦
        tool_calls 非空却没产出正文，收尾那轮会拿真模型去跑——测试就变成
        在发真实网络请求。
        """
        calls["n"] += 1
        if calls["n"] == 1:
            for chunk in turn_chunks(
                agent_mod.TurnResult(
                    text="",
                    tool_calls=[{"id": "t1", "name": "local_search", "input": {"query": "q"}}],
                    content=[],
                    stop_reason="tool_use",
                    input_tokens=10,
                    output_tokens=5,
                )
            ):
                yield chunk
            return
        for chunk in turn_chunks(
            agent_mod.TurnResult(
                text="结论如上[1]。",
                tool_calls=[],
                content=[],
                stop_reason="end_turn",
                input_tokens=100,
                output_tokens=50,
            )
        ):
            yield chunk

    async def _fake_tools(
        tool_calls: Any,
        tool_results: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> Any:
        # async generator：调用点是 `async for`，写成普通 async def 会得到
        # 一个 coroutine 而不是可迭代对象（TypeError，且被 agent 的兜底
        # try/except 吞成「循环异常中止」，症状绕得很远）。
        collected_refs.append(_ref(1, chunk, source))
        if False:
            yield  # 让函数成为 async generator

    monkeypatch.setattr(agent_mod, "_run_turn", _two_turns)

    # 桩成一个真实的 ToolContext——agent 会读它的 ``vec_engine`` 字段
    # 判断能不能本地检索（``object()`` 上没这个属性）。
    def _fake_context(*_a, **_k):
        from app.services.citation import ReferenceTable
        from app.services.tools import ToolContext

        return ToolContext(
            db=db_session,
            vec_engine=None,
            user_id=1,
            citations=ReferenceTable(),
        )

    monkeypatch.setattr(agent_mod, "_build_context", _fake_context)
    monkeypatch.setattr(agent_mod, "_run_tools", _fake_tools)
    # critic 的 judge 调用**必须单独挡**。``_run_turn`` 只拦主循环，
    # ``_settle`` 里 verify_citations 是直接 ``client.messages.stream``，
    # 拦不到——本例实测就从这条路径发出了真实请求，整个测试挂住 40s+。
    # conftest 只挡 Tavily（见它的 _reset_env 注释），Anthropic 侧各测试自理。
    monkeypatch.setattr(agent_mod, "verify_citations", _fake_verify)

    events = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]

    report: Report = (await db_session.execute(select_report())).scalar_one()
    assert report.question == "问题"
    assert "结论如上" in report.content
    assert report.input_tokens == 110
    assert report.output_tokens == 55

    links = (
        (
            await db_session.execute(
                ReportSource.__table__.select().where(
                    ReportSource.__table__.c.report_id == report.id
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(links) == 1
    assert links[0]["n"] == 1
    assert links[0]["chunk_id"] == chunk.id

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.report_id == report.id


def select_report() -> Any:
    from sqlalchemy import select

    return select(Report)


async def test_uncited_chunk_gets_no_row_at_all(
    db_session: AsyncSession,
) -> None:
    """只在检索结果里、正文一次没引用的切片，**不该有任何行**。

    ## 这个测试要防的具体回归（2026-10-17 CR 第二轮）

    ``collected_refs`` 是**全量引用表快照**——模型检索到 3 个切片、正文只写
    了 [1] 和 [3] 时，refs 里第 2 个从未被引用。给它也写一行（``cite_count=0``）
    会造成两个用户可见的错误：

      1. sources 页「关联报告 N 篇」把那份资料也算进去，而报告里根本没有它的角标
      2. 报告详情页多出 8 条 cite_count=0 的幽灵引用

    所以断言的是**行数**，不是 cite_count 的值——写成「cite_count 为 0」的话，
    「写了行但计数为 0」和「没写行」两种实现都能过。

    ## 为什么不用 run_agent

    这里要精确控制 refs 与正文的关系。refs 每轮都是全量快照，用真循环
    去凑「3 个切片进表、只引用 2 个」很难稳定复现；直接调被测函数，
    把「refs 含 3 条、正文只提 [1][3]」这个不变量直接摆出来。
    """
    from app.services.citation import Reference
    from app.services.persistence import _record_citations

    user = await _user(db_session, "uncited@report.test")
    source = await _source(db_session, user.id)
    chunks = [await _chunk(db_session, source.id, content=f"第{i}片", index=i) for i in range(3)]
    report = Report(user_id=user.id, question="Q", content="", session_id="s-uncited")
    db_session.add(report)
    await db_session.flush()

    # refs 里三条（对应角标 1/2/3），正文只提 1 和 3
    await _record_citations(
        db_session,
        report.id,
        [
            Reference(
                n=n,
                chunk_id=chunk.id,
                source_id=source.id,
                chunk_index=chunk.chunk_index,
                page=None,
                title="t",
                excerpt="e",
                recall="向量",
            )
            for n, chunk in enumerate(chunks, start=1)
        ],
        "第一段[1]。第二段跟第一段说的一样[1]。第三段完全另说[3]。",
    )
    await db_session.commit()

    rows = (
        (
            await db_session.execute(
                select(ReportSource.n, ReportSource.cite_count).where(
                    ReportSource.report_id == report.id
                )
            )
        )
        .mappings()
        .all()
    )
    assert sorted(rows, key=lambda r: r["n"]) == [
        {"n": 1, "cite_count": 2},
        {"n": 3, "cite_count": 1},
    ], f"角标 2 从未被引用，不该有行；实际落盘 {rows}"


async def test_same_chunk_twice_writes_one_row_and_cite_count_comes_from_text(
    db_session: AsyncSession,
) -> None:
    """同一 chunk 重复出现在 refs 里 → 只写一行，``cite_count`` 数正文角标。

    ## 这个测试要防的具体回归（两层，都要防）

    第一层：直接逐条 append 会撞 ``(report_id, chunk_id)`` 复合主键。

    第二层（更隐蔽）：``cite_count`` 若按 ``refs`` 的长度或重复次数算，
    得到的**不是引用次数**。``local_search`` 每轮返回的是全量引用表快照，
    于是「两轮检索、正文只写一次 ``[3]``」会得到 cite_count=2——比实际
    引用次数多一倍，而且没有任何报错。真实计数只能来自正文里的 ``[n]``。

    所以这个用例刻意让 **refs 里出现两次、内容里只写一次**：
    两种错误实现都会得到 2，而正确答案必须是 1。
    """
    from app.services.persistence import _record_citations

    user = await _user(db_session, "u2@report.test")
    source = await _source(db_session, user.id)
    chunk = await _chunk(db_session, source.id)

    report = Report(
        user_id=user.id,
        question="q",
        content="能效提升明显[3]。",
        session_id="s-dup",
    )
    db_session.add(report)
    await db_session.flush()

    await _record_citations(
        db_session,
        report.id,
        [_ref(3, chunk, source), _ref(3, chunk, source)],
        report.content,
    )
    await db_session.commit()

    rows = (
        (
            await db_session.execute(
                ReportSource.__table__.select().where(
                    ReportSource.__table__.c.report_id == report.id
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1
    assert rows[0]["n"] == 3
    assert rows[0]["cite_count"] == 1, (
        "refs 里同一 chunk 出现两次只说明它出现在两轮工具结果里，"
        f"实际引用次数是正文里 [3] 出现的 1 次；实际得到 {rows[0]['cite_count']}"
    )


# ── 落盘：失败的路径（这层的失败是静默的）──────────────────
async def test_finalize_text_is_persisted_without_slicer_newlines(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """轮数用尽时的强制收尾，正文落盘不能被切片器切碎。

    ## 这个测试要防的具体回归（2026-10-17 CR 严重级）

    主循环 append 的是**整轮** `result.text`，而 `_finalize` 分支曾经
    append 每个 `DeltaEvent.text`——那是 `_slice_for_display` 的**展示切片**。
    于是 `"\n".join(report_body)` 会在每个切片边界插换行：用户通过 SSE
    读到连续文本，落盘的报告却在每个逗号处断行。

    ## 为什么断言用「不该出现的换行」而不是逐字比对全文

    全文比对会被切片器内部调参（chunk_size、切点优先级）带着走，那些改动
    本来就是允许的。要防的是「多出来的换行」这一类，所以断言正文里不含
    「，\\n」——中文逗号后紧跟换行只可能是切片边界插的，正文自己不会这么写。

    正文用 200+ 字，确保一定切出多个切片——短段落每段都在一个切片内，
    这种 bug 在短文本上完全看不见（第一版测试就是这么漏掉的）。
    """
    from app.services import agent as agent_mod

    user = await _user(db_session, "final@report.test")
    long_text = (
        "根据公司内部测算，2024年新增机柜约1200个，其中约800个已经完成上架并开始计费。"
        "从历史数据看，收入增速与上架节奏高度相关，因此市场对本次收缩的解读可能过于悲观。"
        "管理层在电话会上重申全年指引不变，并表示会继续推进液冷机柜的规模化交付。"
        "此外，公司在软件栈上的优化已经把单卡吞吐提升了约四成，"
        "这部分收益不依赖新增硬件，可以在存量部署上直接兑现。" * 2
    )

    finalize_text = "【收尾轮专用标记】" + long_text

    calls = {"n": 0}

    async def _all_tool_turns(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        """每轮都要工具，直到第 MAX_TURNS 轮才作答——逼出 `_finalize`。

        **最后一轮也要 tool_calls**：`run_agent` 的 `_finalize` 分支在
        `turn == MAX_TURNS - 1` **且** `result.tool_calls` 非空时才走到。
        第一版这里让最后一轮返回空 tool_calls，循环当场 `break`，整条
        `_finalize` 路径从没执行——断言却被「主循环那轮也没产出正文」
        顺带满足，测试是废的（实测哨兵级变异都杀不掉）。

        **主循环那一轮不给正文**（text=""）：正文只由 `_finalize` 产出。
        否则 `long_text in content` 可能命中的是主循环那份，与 finalize
        路径无关，断言就钉不住要防的东西。
        """
        if not tools:
            for chunk in turn_chunks(
                agent_mod.TurnResult(
                    text=finalize_text,
                    tool_calls=[],
                    content=[],
                    stop_reason="end_turn",
                    input_tokens=100,
                    output_tokens=200,
                )
            ):
                yield chunk
            return
        calls["n"] += 1
        for chunk in turn_chunks(
            agent_mod.TurnResult(
                text="",
                tool_calls=[{"id": f"t{calls['n']}", "name": "local_search", "input": {}}],
                content=[],
                stop_reason="tool_use",
                input_tokens=10,
                output_tokens=5,
            )
        ):
            yield chunk

    async def _empty_tools(
        tool_calls: Any,
        tool_results: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> Any:
        if False:
            yield  # async generator：调用点是 `async for`

    monkeypatch.setattr(agent_mod, "_run_turn", _all_tool_turns)

    # 桩成一个真实的 ToolContext——agent 会读它的 ``vec_engine`` 字段
    # 判断能不能本地检索（``object()`` 上没这个属性）。
    def _fake_context(*_a, **_k):
        from app.services.citation import ReferenceTable
        from app.services.tools import ToolContext

        return ToolContext(
            db=db_session,
            vec_engine=None,
            user_id=1,
            citations=ReferenceTable(),
        )

    monkeypatch.setattr(agent_mod, "_build_context", _fake_context)
    monkeypatch.setattr(agent_mod, "_run_tools", _empty_tools)
    monkeypatch.setattr(agent_mod, "verify_citations", _fake_verify)

    _ = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]

    report: Report = (await db_session.execute(select_report())).scalar_one()
    # 只断言**收尾那轮**的文本。主循环那些轮次的 text 是空的，所以这
    # 一段只可能来自 `_finalize`——写成 `long_text in content` 时，
    # 「主循环也没产出正文」这种错误实现同样能过。
    assert finalize_text in report.content, (
        "强制收尾的正文应原样落盘；实际落盘内容里找不到它，"
        f"说明被切片器切碎了（前 120 字：{report.content[:120]!r}）"
    )
    assert "，\n" not in report.content, (
        "中文逗号后紧跟换行只可能是切片边界插的——正文自己不会这么写"
    )


async def test_dangling_citation_does_not_lose_the_whole_report(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引用到的资料被删掉 → 跳过那条引用，但报告本身要留下。

    ## 这个测试要防的具体回归（2026-10-17 CR 严重级）

    `report_sources.chunk_id` 是 CASCADE 外键且强制生效。研究跑 30-60 秒，
    期间用户可以在另一个标签页删掉被引的资料 → `document_chunks` 级联消失
    → 照单插入会撞外键 → **整个事务回滚，连 reports 那行完整正文一起丢**，
    而用户已经读完流了，只发现历史列表里没有它，且没有任何报错。

    症状比「丢一条引用」严重得多：丢的是整份报告。
    """
    from app.services import agent as agent_mod
    from app.services.citation import Reference

    user = await _user(db_session, "dangling@report.test")
    source = await _source(db_session, user.id)
    chunk = await _chunk(db_session, source.id)
    ghost = await _chunk(db_session, source.id, content="会被删掉的那片", index=1)

    calls = {"n": 0}

    async def _fake_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        """第一轮请求工具、第二轮产出正文。

        必须分两轮：主循环见到 ``tool_calls=[]`` 就直接 break，
        ``_run_tools`` 根本不会被调，``collected_refs`` 永远是空的
        ——那样这个用例什么也测不到。
        """
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            for chunk in turn_chunks(
                agent_mod.TurnResult(
                    text="",
                    tool_calls=[{"id": f"t{calls['n']}", "name": "local_search", "input": {}}],
                    content=[],
                    stop_reason="tool_use",
                    input_tokens=10,
                    output_tokens=5,
                )
            ):
                yield chunk
            return
        for chunk in turn_chunks(
            agent_mod.TurnResult(
                text="结论如上[1][2]。",
                tool_calls=[],
                content=[],
                stop_reason="end_turn",
                input_tokens=10,
                output_tokens=5,
            )
        ):
            yield chunk

    async def _tools_with_ghost(
        tool_calls: Any,
        tool_results: list[dict[str, Any]],
        context: Any,
        collected_refs: list[Reference],
    ) -> Any:
        collected_refs.extend(
            [
                Reference(
                    n=1,
                    chunk_id=chunk.id,
                    source_id=source.id,
                    chunk_index=0,
                    page=None,
                    title="t",
                    excerpt="e",
                    recall="向量",
                ),
                Reference(
                    n=2,
                    chunk_id=ghost.id,
                    source_id=source.id,
                    chunk_index=1,
                    page=None,
                    title="t",
                    excerpt="e",
                    recall="向量",
                ),
            ]
        )
        if False:
            yield

    monkeypatch.setattr(agent_mod, "_run_turn", _fake_turn)
    monkeypatch.setattr(agent_mod, "_run_tools", _tools_with_ghost)
    monkeypatch.setattr(agent_mod, "verify_citations", _fake_verify)

    # 先跑一次，拿到这次的 session_id——落盘的 report 会撞唯一索引
    events = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]
    first = next(e for e in events if isinstance(e, DoneEvent))
    assert first.report_id is not None, "第一次落盘应成功"

    # 把被引的那片删掉：资料删除会级联删掉它的 chunk
    await db_session.delete(ghost)
    await db_session.commit()

    # 第二次：refs 指向已删除的 chunk
    events = [e async for e in agent_mod.run_agent("问题2", user_id=user.id, db=db_session)]
    second = next(e for e in events if isinstance(e, DoneEvent))

    assert second.report_id is not None, "一条悬空引用不该让整份报告陪葬——这里 report_id 变 None 了"
    saved = await db_session.get(Report, second.report_id)
    assert saved is not None and "结论如上" in saved.content, (
        "报告正文必须真的在库里，而不只是拿到了一个 id"
    )
    links = (
        (
            await db_session.execute(
                ReportSource.__table__.select().where(
                    ReportSource.__table__.c.report_id == second.report_id
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(links) == 1, f"只有还活着的那片该留下，实际 {len(links)} 行"


async def test_persist_failure_does_not_break_the_stream(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB 写不进去时，done 帧仍要发出。

    ## 这个测试要防的具体回归

    落盘包在 try 里是对的，但**回滚那行**很容易被写成裸 ``await
    db.rollback()`` 或干脆不写——前者 DB 真挂时自己会抛，后者让 session
    卡在 failed 状态，连带把后面 critic 的查询也带崩（``_settle`` 就在
    done 之后跑）。症状是「报告读完了，突然整条流报错」。

    ## 为什么用唯一约束冲突而不是 patch 掉 flush

    第一版 patch ``db.flush`` 让它无条件抛。那样**回滚测不出来**：
    没有真实失败的事务时 ``rollback()`` 本来就是空操作，把
    ``await db.rollback()`` 整行删掉测试照样全绿（实测 13 passed）。

    所以改成制造一次**真实的事务失败**：把 ``uuid4`` 固定成一个已知值，
    预先插入一条同 ``session_id`` 的报告，于是 agent 落盘时撞
    ``ux_reports_session_id``。这是 SQLAlchemy 认得的失败，此时不回滚
    就真的会让 session 卡在 failed。
    """
    from app.services import agent as agent_mod

    user = await _user(db_session, "u3@report.test")
    monkeypatch.setattr(agent_mod, "_run_turn", _fake_turn)
    monkeypatch.setattr(agent_mod, "verify_citations", _fake_verify)

    fixed = "00000000-0000-4000-8000-000000000001"
    monkeypatch.setattr(agent_mod, "uuid4", lambda: UUID(fixed))
    db_session.add(Report(user_id=user.id, question="预埋", content="x", session_id=fixed))
    await db_session.commit()

    events = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.report_id is None, "落盘失败时 report_id 必须是 None"
    # 流本身要完整：正文流出去过、done 也发了。
    assert any("结论如上" in str(getattr(e, "text", "")) for e in events)

    # 回滚有没有真的发生：session 必须还能继续用。不回滚时它卡在 failed，
    # 下面这条 execute 会抛 PendingRollbackError。
    probe = await db_session.execute(
        Report.__table__.select().where(Report.__table__.c.session_id == fixed)
    )
    assert len(probe.mappings().all()) == 1, "预埋那条应还在（回滚只回滚本次事务）"


async def test_persist_skipped_when_db_is_none() -> None:
    """db 为 None（单测路径）不落盘，也不报错。"""
    from app.services import agent as agent_mod

    monkey = pytest.MonkeyPatch()
    monkey.setattr(agent_mod, "_run_turn", _fake_turn)
    try:
        events = [e async for e in agent_mod.run_agent("问题", user_id=1)]
    finally:
        monkey.undo()

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.report_id is None


# ── 读取路由 ───────────────────────────────────────────────
def test_list_reports_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/reports").status_code == 401


def test_read_report_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/reports/1").status_code == 401


def test_delete_report_requires_login(client: TestClient) -> None:
    assert client.delete("/api/v1/reports/1").status_code == 401


async def test_delete_report_cascades_citation_rows(
    db_session: AsyncSession, client: TestClient
) -> None:
    """删报告 → 204，引用行跟着 CASCADE 走。

    ## 这个测试要防的具体回归

    `Report.sources` 用了 `lazy="raise"` + `delete-orphan`。级联删走的是
    bulk DELETE，不该触发加载；但**这一点是推断的**——源码里 `Source.chunks`
    是完全一样的组合，而那条路径有 `test_sources_router.py` 兜着，本批的
    报告路径此前只测了 401 / 404，真要是抛 `InvalidRequestError`，
    `db.delete(report)` 会直接 500。实测一下，不靠推断。
    """
    user = await _user(db_session, "del@report.test")
    source = await _source(db_session, user.id)
    chunk = await _chunk(db_session, source.id)
    report = Report(user_id=user.id, question="Q", content="C", session_id="s-del")
    db_session.add(report)
    await db_session.flush()
    db_session.add(ReportSource(report_id=report.id, chunk_id=chunk.id, n=1, cite_count=1))
    await db_session.commit()

    _auth(client, user)
    assert client.delete(f"/api/v1/reports/{report.id}").status_code == 204

    rows = (
        (await db_session.execute(select(ReportSource).where(ReportSource.report_id == report.id)))
        .scalars()
        .all()
    )
    assert rows == [], f"引用行应被级联删除，实际残留 {len(rows)} 行"
    # 被引用的切片本身不该动——CASCADE 方向是「删 chunk 才清引用行」，
    # 反过来删报告不该把资料带走。
    assert await db_session.get(DocumentChunk, chunk.id) is not None


async def test_list_reports_only_returns_my_reports(
    db_session: AsyncSession, client: TestClient
) -> None:
    """列表端点必须按 user_id 过滤。

    ## 这个测试要防的具体回归

    ``gateway/reports.py`` 里那句 ``.where(Report.user_id == user.id)`` 被删掉
    时，库里只有**一个**用户的用例照样全绿——单用户数据下「过滤」与「不过滤」
    结果完全一样。读 / 删路径有 ``test_read_other_users_report_returns_404``
    兜着，列表没有，所以这条不变量本来是**零覆盖**。

    所以这里必须造两个用户各一份报告：只有真的过滤了才会少一条。
    """
    mine = await _user(db_session, "mine@report.test")
    theirs = await _user(db_session, "theirs@report.test")
    db_session.add(Report(user_id=mine.id, question="我的", content="c", session_id="s-mine"))
    db_session.add(Report(user_id=theirs.id, question="他的", content="c", session_id="s-theirs"))
    await db_session.commit()

    _auth(client, mine)
    body = client.get("/api/v1/reports").json()
    titles = {r["question"] for r in body["items"]}
    assert titles == {"我的"}, f"列表混进了别人的报告：{titles}"
    assert body["total"] == 1


async def test_read_other_users_report_returns_404(
    db_session: AsyncSession, client: TestClient
) -> None:
    """越权一律 404 而不是 403——403 等于确认了这个 id 存在。"""
    owner = await _user(db_session, "owner@report.test")
    other = await _user(db_session, "other@report.test")
    report = Report(user_id=owner.id, question="q", content="c", session_id="s-404")
    db_session.add(report)
    await db_session.commit()

    _auth(client, other)
    assert client.get(f"/api/v1/reports/{report.id}").status_code == 404
    assert client.delete(f"/api/v1/reports/{report.id}").status_code == 404


async def test_read_report_returns_content_and_citations(
    db_session: AsyncSession, client: TestClient
) -> None:
    user = await _user(db_session, "reader@report.test")
    source = await _source(db_session, user.id, title="私有财报")
    chunk = await _chunk(db_session, source.id, content="Blackwell 采用台积电 4NP 工艺")
    report = Report(
        user_id=user.id, question="q", content="能效提升 2.5 倍[1]。", session_id="s-ok"
    )
    db_session.add(report)
    await db_session.flush()
    db_session.add(ReportSource(report_id=report.id, chunk_id=chunk.id, n=1, cite_count=1))
    await db_session.commit()

    _auth(client, user)
    resp = client.get(f"/api/v1/reports/{report.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "能效提升 2.5 倍[1]。"
    assert len(body["citations"]) == 1
    assert body["citations"][0]["n"] == 1
    assert body["citations"][0]["title"] == "私有财报"
    assert body["citations"][0]["chunk_id"] == chunk.id


async def test_list_reports_total_is_not_page_length(
    db_session: AsyncSession, client: TestClient
) -> None:
    """``total`` 必须是全量计数，不是当页条数。

    拿 ``len(items)`` 当 total 的症状：第二页起页码算错，最后一页之后
    还能再往前翻，点过去永远是空的。
    """
    user = await _user(db_session, "pager@report.test")
    for i in range(5):
        db_session.add(Report(user_id=user.id, question=f"q{i}", content="c", session_id=f"s-{i}"))
    await db_session.commit()

    _auth(client, user)
    body = client.get("/api/v1/reports?limit=2&offset=0").json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0

    last = client.get("/api/v1/reports?limit=2&offset=4").json()
    assert last["total"] == 5
    assert len(last["items"]) == 1


async def test_list_reports_rejects_out_of_range_page(
    db_session: AsyncSession, client: TestClient
) -> None:
    """limit=0 或 limit>100 必须 422，而不是悄悄返回一堆。

    鉴权在参数校验之前跑，所以这个断言必须先登录——未登录时拿到的是
    401，那证明不了 Query 约束生效。
    """
    user = await _user(db_session, "range@report.test")
    _auth(client, user)
    assert client.get("/api/v1/reports?limit=0").status_code == 422
    assert client.get("/api/v1/reports?limit=101").status_code == 422
    assert client.get("/api/v1/reports?offset=-1").status_code == 422


# ── citation_count 回填 ────────────────────────────────────
async def test_citation_count_counts_distinct_reports(
    db_session: AsyncSession, client: TestClient
) -> None:
    """「关联报告 N 篇」按**报告去重**，不是按引用次数。

    ## 这个测试要防的具体回归

    一份资料被同一篇报告引了 3 个切片。写成 ``count(*)`` 会显示「3 篇」，
    而用户问的是「有几篇报告用过我」——答案显然是 1。

    ## 为什么必须造两篇报告

    第一版只有一篇报告引 3 片，断言 ``== 1``。那样把实现换成「恒返回 1」
    也照样通过（实测变异存活：13 passed）——**单份资料的场景分不清
    「去重后是 1」和「写死 1」**。所以这里再加第二篇报告：正确答案 2，
    任何退化实现（恒 1 / 按行数数=5 / 按切片数算）都会露出来。
    """
    user = await _user(db_session, "cited@report.test")
    source = await _source(db_session, user.id)
    # chunk_index 在一份资料内唯一（ux_document_chunks_source_index），
    # 所以三片必须给三个不同序号，否则插第二条就撞约束。
    chunks = [await _chunk(db_session, source.id, content=f"第{i}段", index=i) for i in range(3)]

    # 第一篇引 3 片
    first = Report(user_id=user.id, question="q1", content="c", session_id="s-cited-1")
    db_session.add(first)
    await db_session.flush()
    for i, chunk in enumerate(chunks):
        db_session.add(ReportSource(report_id=first.id, chunk_id=chunk.id, n=i + 1))

    # 第二篇只引其中 1 片 —— 总引用行数 4、涉及切片 3、去重后报告 2
    second = Report(user_id=user.id, question="q2", content="c", session_id="s-cited-2")
    db_session.add(second)
    await db_session.flush()
    db_session.add(ReportSource(report_id=second.id, chunk_id=chunks[0].id, n=1))
    await db_session.commit()

    _auth(client, user)
    body = client.get("/api/v1/sources").json()
    row = next(r for r in body["items"] if r["id"] == source.id)
    assert row["citation_count"] == 2, (
        "两篇报告（第一篇引 3 片、第二篇引 1 片）应算 2 篇；"
        f"实际 {row['citation_count']}——按引用行数会得到 4"
    )


async def test_citation_count_zero_for_uncited(
    db_session: AsyncSession, client: TestClient
) -> None:
    """没被引过的资料 citation_count 是 0，不是缺字段。"""
    user = await _user(db_session, "uncited@report.test")
    source = await _source(db_session, user.id)

    _auth(client, user)
    body = client.get("/api/v1/sources").json()
    row = next(r for r in body["items"] if r["id"] == source.id)
    assert row["citation_count"] == 0


# ── 崩溃路径也要落盘 ───────────────────────────────────────


async def test_crash_still_persists_partial_report(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第 2 轮崩掉时，第 1 轮已生成的正文必须落盘。

    ## 要防的回归

    崩溃路径原来在 ``persist_report`` **之前**就 ``return`` 了。于是：
    用户拿到一句红横幅，正文一个字节都没有，历史报告里也没有这份——
    而那几轮已经烧掉了真实 token（实测一次崩溃烧掉 29548 输入 token）。
    最贵的一次失败变成最没有产出的失败。

    ## 注入回归

    把异常路径的落盘删掉（恢复旧的 ``yield ledger.done()`` + ``return``），
    这条会红：``report_id`` 变 None，且库里查不到报告。
    """
    from app.services import agent as agent_mod

    user = await _user(db_session, "crash@report.test")
    script = [
        agent_mod.TurnResult(
            content=[{"type": "text", "text": "第一轮的结论"}],
            text="第一轮的结论",
            tool_calls=[
                {"type": "tool_use", "id": "toolu_1", "name": "tavily_search", "input": {}}
            ],
            stop_reason="tool_use",
            input_tokens=100,
            output_tokens=50,
        ),
    ]

    async def _boom(
        client: Any, messages: list[Any], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        if script:
            for chunk in turn_chunks(script.pop(0)):
                yield chunk
            return
        raise ConnectionError("第 2 轮挂掉")
        yield  # pragma: no cover —— 生成器函数需要 unreachable 的 yield

    async def _no_tools(calls: list[Any], sink: list[Any], context: Any, refs: list[Any]) -> Any:
        if False:
            yield

    monkeypatch.setattr(agent_mod, "_run_turn", _boom)
    monkeypatch.setattr(agent_mod, "_run_tools", _no_tools)

    events = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.report_id is not None, (
        "崩溃时已生成的正文必须落盘——report_id 是 None 说明走了旧的丢正文路径"
    )
    saved = await db_session.get(Report, done.report_id)
    assert saved is not None, "report_id 指向的记录必须真的在库里"
    assert "第一轮的结论" in saved.content, "落盘的内容必须包含崩溃前已生成的正文"
    assert saved.user_id == user.id


async def test_crash_with_no_text_does_not_persist_empty_report(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """崩溃时一个字都没产出，不该落盘出一条空报告。

    ## 要防的回归

    崩溃路径无条件落盘时，``content=""`` 也会插进 ``reports``。
    前端 ``done.report_id != null`` 就渲染「查看完整报告 ↗」，点进去
    是空白；历史报告列表也多一条空记录，用户分不清「跑崩了」与
    「模型什么都没产出」。

    正常路径有 ``produced_text`` 守卫，崩溃路径必须同样守住。

    ## 注入回归

    把崩溃路径的 ``if ledger.produced_text`` 去掉，这条会红：
    report_id 变成非 None。
    """
    from app.services import agent as agent_mod

    user = await _user(db_session, "crash-empty@report.test")

    async def _boom(
        client: Any, messages: list[Any], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        raise ConnectionError("第 1 轮就挂掉")
        yield  # pragma: no cover —— 生成器函数需要 unreachable 的 yield

    monkeypatch.setattr(agent_mod, "_run_turn", _boom)

    events = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.report_id is None, "没有正文时不该落盘——否则会写出一条空报告"
    rows = (await db_session.execute(select(Report).where(Report.user_id == user.id))).all()
    assert len(rows) == 0, f"库里不该有这条用户的报告，实际有 {len(rows)} 条"


async def test_crash_path_persist_timeout_is_shorter(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """崩溃路径的落盘超时必须比正常路径短。

    ## 要防的回归

    崩溃时用户正盯着红色横幅等失败通知。落盘如果按正常路径的 5 秒上限
    等下去，那 5 秒里界面还在转圈，什么新信息都没有——白等。

    ## 注入回归

    把 ``timeout=PERSIST_TIMEOUT_CRASH_SECONDS`` 去掉（回到默认 5 秒），
    这条会红。
    """
    from app.services import agent as agent_mod

    user = await _user(db_session, "crash-timeout@report.test")
    seen: list[float] = []
    script = [
        agent_mod.TurnResult(
            content=[{"type": "text", "text": "第一轮正文"}],
            text="第一轮正文",
            tool_calls=[{"type": "tool_use", "id": "t1", "name": "tavily_search", "input": {}}],
            stop_reason="tool_use",
            input_tokens=100,
            output_tokens=50,
        ),
    ]

    async def _boom(
        client: Any, messages: list[Any], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        if script:
            for chunk in turn_chunks(script.pop(0)):
                yield chunk
            return
        raise ConnectionError("第 2 轮挂掉")
        yield  # pragma: no cover —— 生成器函数需要 unreachable 的 yield

    async def _no_tools(calls: list[Any], sink: list[Any], context: Any, refs: list[Any]) -> Any:
        if False:
            yield

    original = agent_mod.persist_report

    async def _spy(**kwargs: Any) -> int | None:
        seen.append(kwargs.get("persist_timeout", -1.0))
        return await original(**kwargs)

    monkeypatch.setattr(agent_mod, "_run_turn", _boom)
    monkeypatch.setattr(agent_mod, "_run_tools", _no_tools)
    # persist_report 现在住在 agent_failures 模块里（那条路径被拆出去了）
    monkeypatch.setattr(
        "app.services.agent_failures.persist_report", _spy
    )

    _ = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]

    assert seen, "崩溃路径应该调过 persist_report"
    assert seen[0] == persistence_mod.PERSIST_TIMEOUT_CRASH_SECONDS
    assert seen[0] < persistence_mod.PERSIST_TIMEOUT_SECONDS, (
        "崩溃路径的落盘超时必须短于正常路径——用户正在等错误提示"
    )


async def test_persist_timeout_after_commit_still_returns_report_id(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落盘中途超时、但行已入库时，仍要返回 report_id。

    ## 要防的回归

    超时取消的是 ``commit()`` 里的 await。若 COMMIT 已到达服务端，取消不
    会撤销它——行真在库里，但代码已走进 except 分支。若那时返回 None，
    前端拿不到 report_id（不显示「查看完整报告」），而历史列表里却多
    了一条——用户以为这次没产出。
    """
    user = await _user(db_session, "persist-orphan@report.test")

    original_write = persistence_mod._write
    committed = False

    async def _write_then_hang(db: Any, report: Any, refs: Any, content: Any) -> None:
        nonlocal committed
        await original_write(db, report, refs, content)
        committed = True
        # 行已入库，之后卡住直到超时。
        await asyncio.sleep(10)

    monkeypatch.setattr(persistence_mod, "_write", _write_then_hang)

    ledger = agent_mod.TurnLedger(
        session_id="s-orphan",
        user_id=user.id,
        input_tokens=10,
        output_tokens=20,
        started_at=time.monotonic(),
        turns=1,
    )
    report_id = await persistence_mod.persist_report(
        db=db_session,
        question="问题",
        content="正文",
        ledger=ledger,
        refs=[],
        persist_timeout=0.5,
    )
    assert committed, "前置条件：行应该已经入库"
    assert report_id is not None, "行已入库时必须返回 report_id，否则前端以为没产出"


async def test_persist_failure_cleanup_is_bounded_by_timeout(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落盘失败后的**清理路径**也必须有上限。

    ## 要防的回归

    落盘超时的成因往往就是「DB 卡住/被锁」。同一个坏连接上再 await 一次
    （``db.rollback()``、``_recover_persisted_id`` 里的 ``db.get()``）会
    **再等一次**，而那两次 await 原本**没有上限**。

    而 ``yield ledger.done()`` / ``yield error_event_for(exc)`` 都在
    ``persist_report`` **之后**——用户永远等不到失败横幅，界面一直转圈，
    SSE 流挂死。

    ## 反例实现

    把清理路径的 ``asyncio.timeout`` 去掉 → 这条会红（挂死 10 秒）。
    """
    user = await _user(db_session, "persist-hang-cleanup@report.test")

    async def _hang_write(db: Any, report: Any, refs: Any, content: Any) -> None:
        # 卡住直到外层超时
        await asyncio.sleep(10)

    async def _hang_rollback() -> None:
        # 回滚也卡住——模拟「DB 真挂了」的场景
        await asyncio.sleep(10)

    monkeypatch.setattr(persistence_mod, "_write", _hang_write)
    monkeypatch.setattr(db_session, "rollback", _hang_rollback)

    ledger = agent_mod.TurnLedger(
        session_id="s-hang",
        user_id=user.id,
        input_tokens=10,
        output_tokens=20,
        started_at=time.monotonic(),
        turns=1,
    )

    started = time.monotonic()
    report_id = await persistence_mod.persist_report(
        db=db_session,
        question="问题",
        content="正文",
        ledger=ledger,
        refs=[],
        persist_timeout=0.5,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"失败清理路径没有上限，耗时 {elapsed:.1f}s（用户等不到错误横幅）"
    assert report_id is None


async def test_crash_persisted_report_is_marked_truncated(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """崩溃落盘的报告必须标 truncated。

    ## 要防的回归

    ``truncated`` 之前只活在 SSE 帧里，不落库。崩溃落盘的报告正文不完整，
    可它在历史列表里和完整报告长得一样——读者会当成完整报告读。

    ## 注入回归

    去掉 ``truncated=ledger.truncated`` → 断言 ``saved.truncated is True`` 变红。
    """
    user = await _user(db_session, "truncated-flag@report.test")
    script = [
        agent_mod.TurnResult(
            content=[{"type": "text", "text": "第一轮正文"}],
            text="第一轮正文",
            tool_calls=[{"type": "tool_use", "id": "t1", "name": "local_search", "input": {}}],
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
        ),
    ]

    async def _run(
        client: Any, messages: list[Any], tools: Any
    ) -> AsyncIterator[agent_mod.TurnChunk]:
        if script:
            for chunk in turn_chunks(script.pop(0)):
                yield chunk
            return
        raise ConnectionError("第 2 轮挂掉")
        yield  # pragma: no cover —— 生成器函数需要 unreachable 的 yield

    async def _no_tools(*args: Any, **kwargs: Any) -> Any:
        if False:
            yield None

    monkeypatch.setattr(agent_mod, "_run_turn", _run)
    monkeypatch.setattr(agent_mod, "_run_tools", _no_tools)

    events = [e async for e in agent_mod.run_agent("问题", user_id=user.id, db=db_session)]
    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.report_id is not None, "崩溃前有正文，应该落盘"
    assert done.truncated is True

    saved = await db_session.get(Report, done.report_id)
    assert saved is not None
    assert saved.truncated is True, "崩溃落盘的报告必须标 truncated——否则读者当成完整报告读"
