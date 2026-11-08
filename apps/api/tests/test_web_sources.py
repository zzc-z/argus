"""公开来源落库与角标编号的测试。

覆盖的四个不变量：

1. **公开来源能占角标号** —— 正文里的 ``[n]`` 要唯一、可点开、可被
   critic 校验。
2. **不进用户资料列表** —— 用户没上传过它们，且不能被本地检索召回。
3. **不建索引** —— 进索引就会污染后续的本地检索。
4. **落库失败不阻断** —— 正文已经流给用户了，公开来源是增益。
"""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import WEB_SOURCE_TYPE, DocumentChunk, Source
from app.models.user import User
from app.services.citation import Reference, ReferenceTable
from app.services.retriever import _user_source_ids
from app.services.web_sources import (
    ToolEvidence,
    register_web_sources,
    render_web_evidence,
    web_citation_rules,
)


async def _make_user(db) -> int:
    """建一个用户。``sources.user_id`` 有 FK 指向 ``users.id``。"""
    user = User(email=f"web-{id(db)}@test.local", display_name="测试")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


def _evidence(count: int = 2) -> list[ToolEvidence]:
    return [
        ToolEvidence(
            title=f"报道{i}",
            excerpt=f"这是第 {i} 条搜索结果的摘要",
            url=f"https://example.com/{i}",
        )
        for i in range(1, count + 1)
    ]


async def test_web_source_becomes_a_citable_chunk(db_session) -> None:
    """公开来源落成真正的 Source + DocumentChunk。

    ## 为什么

    critic 校验的是「正文里的 [n] 是不是被它引用的原文支撑」，而原文
    来自 ``document_chunks``。公开来源不落成 chunk，critic 就永远跳过。
    """
    table = ReferenceTable()
    user_id = await _make_user(db_session)

    references = await register_web_sources(
        db_session, user_id=user_id, table=table, evidence=_evidence(2)
    )

    assert len(references) == 2
    for _n, _item, ref in references:
        chunk = await db_session.get(DocumentChunk, ref.chunk_id)
        assert chunk is not None, "公开来源必须落成 DocumentChunk"
        assert chunk.source_id == ref.source_id
        source = await db_session.get(Source, ref.source_id)
        assert source is not None
        assert source.source_type == WEB_SOURCE_TYPE
        assert source.url == f"https://example.com/{ref.n}"


async def test_multiple_web_sources_get_distinct_numbers(db_session) -> None:
    """同一批的多个公开来源必须拿到**各不相同**的编号。

    ## 要防的回归

    早先的写法是「造好引用后 ``table.add()``，而编号取
    ``len(table.all) + 1``」——同一批里每条算出的都是同一个号（表还没
    变），于是 5 条公开来源全都是 ``[11]``。

    症状极隐蔽：角标能显示、点开也有内容，只是全都指向同一处。而正文
    里的 ``[3]`` 会指向一个不存在的引用——没有任何报错。
    """
    table = ReferenceTable()

    references = await register_web_sources(
        db_session, user_id=await _make_user(db_session), table=table, evidence=_evidence(5)
    )

    numbers = [n for n, _item, _ref in references]
    assert len(numbers) == 5
    assert len(set(numbers)) == 5, f"编号重复了：{numbers}"
    assert numbers == sorted(numbers), f"编号应当递增：{numbers}"
    assert numbers == list(range(1, 6)), numbers


async def test_same_url_across_rounds_is_not_registered_twice(db_session) -> None:
    """同一篇资料在多轮搜索里出现时**只占一个角标号**。

    ## 要防的回归

    实测（2026-11-08）：SEC 的 nvda-20250126 在两轮搜索里各出现一次，
    于是占了 ``[4]`` 与 ``[7]`` 两个号——正文里两个角标指向同一处，
    而模型会把它们当成「两个独立来源互相印证」。那是错的结论。

    ## 怎么测

    调两次 ``register_web_sources``，传同一个 ``seen_urls`` 集合，
    断言第二次不产生新引用。
    """
    table = ReferenceTable()
    user_id = await _make_user(db_session)
    seen: set[str] = set()
    url = "https://www.sec.gov/Archives/edgar/data/1045810/nvda-20250126.htm"

    first = await register_web_sources(
        db_session,
        user_id=user_id,
        table=table,
        evidence=[ToolEvidence(title="SEC 10-K", excerpt="正文", url=url)],
        seen_urls=seen,
    )
    second = await register_web_sources(
        db_session,
        user_id=user_id,
        table=table,
        evidence=[ToolEvidence(title="SEC 10-K", excerpt="正文", url=url)],
        seen_urls=seen,
    )

    assert len(first) == 1
    assert second == [], f"同一篇资料重复登记了：{[n for n, _i, _r in second]}"
    assert len(table.all) == 1


async def test_share_tracking_params_do_not_create_duplicates(db_session) -> None:
    """带分享参数的链接与原文算**同一篇**。

    ## 为什么

    实测（2026-11-08）：Yahoo Finance 同一篇报道
    ``?fr=sycsrp_catchall`` 与不带，被算成两条独立证据，各占一个号。

    归一化靠 ``urls.canonicalize_url``——去掉跟踪参数、统一 host 大小写、
    去掉 www. 与尾斜杠。
    """
    table = ReferenceTable()
    user_id = await _make_user(db_session)
    seen: set[str] = set()

    first = await register_web_sources(
        db_session,
        user_id=user_id,
        table=table,
        evidence=[
            ToolEvidence(
                title="Yahoo 报道",
                excerpt="正文",
                url="https://finance.yahoo.com/news/nvidia-212000223.html",
            )
        ],
        seen_urls=seen,
    )
    second = await register_web_sources(
        db_session,
        user_id=user_id,
        table=table,
        evidence=[
            ToolEvidence(
                title="Yahoo 报道",
                excerpt="正文",
                url="https://finance.yahoo.com/news/nvidia-212000223.html?fr=sycsrp_catchall",
            )
        ],
        seen_urls=seen,
    )

    assert len(first) == 1
    assert second == [], "带跟踪参数的同一篇链接不该重复登记"


async def test_independent_session_does_not_hold_the_write_lock(db_session, tmp_path) -> None:
    """公开来源用**独立 session** 落库并立即提交——不占主事务的写锁。

    ## 要防的回归（CR 实测，2026-11-08）

    研究流跑 30-60 秒，SQLite 的写锁是**库级**的。公开来源若用主
    session 落库（``flush`` 不 ``commit``），那个写锁会持有整轮研究：

    - 别的研究一 ``flush`` 就 ``database is locked``（默认超时 5 秒）
    - 用户的资料上传（``upload_source`` → ``db.commit()``）同样被阻塞

    实测两个并发 session：s1 flush 未提交 → s2 flush 5.3 秒后报
    ``OperationalError: database is locked``，且 s2 的 session 被毒化
    （SAVEPOINT 回滚救不了——那不是约束失败）。

    ## 怎么测

    用**文件型** SQLite（内存库的每条连接是独立数据库，测不出锁），
    起两个 session：s1 用独立 session 落库并提交，然后 s2 写入——
    断言 s2 **没有被阻塞**。
    """
    import time

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import _enable_sqlite_foreign_keys
    from app.models.base import Base

    db_path = tmp_path / "lock_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    _enable_sqlite_foreign_keys(engine.sync_engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        # s1：研究的主 session（模拟跑了一半，事务未提交）
        async with factory() as s1:
            s1.add(User(email="owner@test.local", display_name="o"))
            await s1.commit()

            # 主 session 此时**没有未提交的写**——研究的主 session 只在
            # 末尾落盘报告时才写（``persist_report``：add → flush → commit）。
            #
            # 锁问题的关键就在这里：公开来源若用主 session 落库
            # （flush 不 commit），那个写锁会被**持有整轮研究**。

            # 公开来源走**独立 session**，写完立刻提交
            table = ReferenceTable()
            await register_web_sources(
                s1,
                user_id=1,
                table=table,
                evidence=[ToolEvidence(title="网页", excerpt="内容", url="https://x.test/1")],
                session_maker=factory,
            )

            # s2：另一个用户的资料上传（要 commit）
            started = time.monotonic()
            async with factory() as s2:
                s2.add(User(email="other@test.local", display_name="o2"))
                await s2.commit()
            elapsed = time.monotonic() - started

            # 没被锁住（SQLite 默认 busy_timeout 是 5 秒）
            assert elapsed < 2.0, f"另一个写入被阻塞了 {elapsed:.1f} 秒——写锁被研究持有"
    finally:
        await engine.dispose()


async def test_independent_session_path_does_not_block_other_writes(tmp_path) -> None:
    """**独立 session 路径**（生产用的那条）不阻塞别人的写入。

    ## 为什么要有这条测试

    上一条测的是 SAVEPOINT 路径（测试里 ``session_maker`` 是 None）。
    而**生产走的是独立 session**——两条路径的行为不同，必须分别验。

    实测（2026-11-08）：裸 ``flush`` 不 commit 会持有 SQLite 的库级写锁，
    别人 5.3 秒后报 ``database is locked``。独立 session 写完立刻
    ``commit``，锁立刻释放。

    这条测试走**生产路径**：真的开一个独立 session 落库，然后立刻验证
    另一个 session 能写。
    """
    import time

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import _enable_sqlite_foreign_keys
    from app.models.base import Base

    db_path = tmp_path / "independent.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    _enable_sqlite_foreign_keys(engine.sync_engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as main_db:
            user = User(email="owner@test.local", display_name="o")
            main_db.add(user)
            await main_db.commit()
            await main_db.refresh(user)

            table = ReferenceTable()
            registered = await register_web_sources(
                main_db,
                user_id=user.id,
                table=table,
                evidence=[ToolEvidence(title="网页", excerpt="内容", url="https://x.test/1")],
                session_maker=factory,
            )
            assert len(registered) == 1

            # **另一个用户的写入不该被阻塞**。
            #
            # 关键是「register_web_sources 返回之后锁就释放了」——研究还要
            # 跑 30-60 秒，那段时间里主 session 不能持有写锁。
            #
            # 注意「在 register_web_sources 内部并发写」测不出这个：那个
            # 窗口本来就短。要验的是**返回之后**的锁状态。
            started = time.monotonic()
            async with factory() as other:
                other.add(User(email="other@test.local", display_name="o2"))
                await other.commit()
            elapsed = time.monotonic() - started

            assert elapsed < 2.0, (
                f"另一个写入被阻塞了 {elapsed:.1f} 秒——写锁在 register 返回后仍被持有"
            )

            # **主 session 也不能持有写锁**。
            #
            # 主 session 接下来还要跑 30-60 秒（正文流式发送），最后才
            # 落盘报告（``persist_report``：add → flush → commit）。
            #
            # 如果它已经因为公开来源的写入而持有锁，那整个研究期间别的
            # 写入（别的研究、用户的资料上传）全被阻塞。
            started = time.monotonic()
            async with factory() as other2:
                other2.add(User(email="other2@test.local", display_name="o3"))
                await other2.commit()
            elapsed2 = time.monotonic() - started

            assert elapsed2 < 2.0, f"主 session 仍持有写锁（另一个写入被阻塞 {elapsed2:.1f} 秒）"
    finally:
        await engine.dispose()


async def test_production_call_site_passes_the_session_maker(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """**生产调用点**必须把 session_maker 传下去。

    ## 要防的回归（CR 实测，2026-11-08）

    ``register_web_sources`` 有两条路径：独立 session（生产）与 SAVEPOINT
    （测试兜底）。上一版里 ``tools.py`` 的调用点**漏传** ``session_maker=``，
    于是生产永远走 SAVEPOINT 路径——而那条路径在 pysqlite 下
    「RELEASE SAVEPOINT == COMMIT」，会偷偷提交主 session 的事务。

    而上一版的测试**直接调** ``register_web_sources(..., session_maker=factory)``，
    绕过了生产调用点——所以这个漏传永远测不出来。

    ## 怎么测

    不直接调 ``register_web_sources``，而是走**生产的调用点**
    （``tools._run_tavily_search``），断言 ``register_web_sources`` 收到的
    ``session_maker`` 不是 None。
    """
    from app.services import tools as tools_module

    seen: list[object] = []
    original = tools_module.register_web_sources

    async def _spy(*args: Any, **kwargs: Any):
        seen.append(kwargs.get("session_maker"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(tools_module, "register_web_sources", _spy)

    async def _fake_search(client: Any, query: str, max_results: int) -> Any:
        return {"results": [{"title": "报道", "url": "https://x.test/1", "content": "内容"}]}

    monkeypatch.setattr(tools_module, "_search", _fake_search)
    monkeypatch.setattr(tools_module, "get_tavily_client", lambda: object())

    from app.services.citation import ReferenceTable

    context = tools_module.ToolContext(
        db=db_session,
        vec_engine=None,
        user_id=1,
        citations=ReferenceTable(),
        # **有工厂**——模拟生产
        session_maker=object(),  # type: ignore[arg-type]
    )

    await tools_module.execute_tool("tavily_search", {"query": "x"}, context)

    assert seen, "register_web_sources 没被调用"
    assert seen[0] is not None, (
        "生产调用点漏传 session_maker——公开来源会走 SAVEPOINT 路径，"
        "而那条路径会偷偷提交主 session 的事务"
    )


async def test_main_session_sees_independently_committed_chunks(tmp_path) -> None:
    """主 session 能看到独立 session 提交的 chunk。

    ## 为什么这条要紧

    critic 校验时用**主 session** 回查原文（``load_source_texts``）。而公开
    来源的 chunk 是**独立 session** 写的——如果主 session 看不到那些行，
    critic 就永远「引用表里没有对应原文」，公开来源等于白做。

    ## 怎么测

    主 session 先开一个读事务（模拟研究期间），独立 session 写并提交，
    然后主 session 读那个 chunk。

    这条锁住的是「独立 session 这条路真的可用」——万一将来有人改回
    SAVEPOINT 路径，症状会退化成「校验静悄悄失效」。
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import _enable_sqlite_foreign_keys
    from app.models.base import Base
    from app.models.user import User

    db_path = tmp_path / "visibility.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    _enable_sqlite_foreign_keys(engine.sync_engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as main_db:
            user = User(email="owner@test.local", display_name="o")
            main_db.add(user)
            await main_db.commit()
            await main_db.refresh(user)

            # 主 session 开一个读事务（模拟研究期间）
            await main_db.execute(select(Source.id).limit(1))

            # 独立 session 写并提交
            table = ReferenceTable()
            registered = await register_web_sources(
                main_db,
                user_id=user.id,
                table=table,
                evidence=[ToolEvidence(title="网页", excerpt="内容", url="https://x.test/1")],
                session_maker=factory,
            )
            assert len(registered) == 1
            chunk_id = registered[0][2].chunk_id

            # **主 session 读得到**
            rows = (
                await main_db.execute(
                    select(DocumentChunk.id, DocumentChunk.content).where(
                        DocumentChunk.id == chunk_id
                    )
                )
            ).all()
            assert rows, "主 session 看不到独立 session 提交的 chunk——critic 会查不到原文"
            assert rows[0][1].strip(), "chunk 内容是空的"
    finally:
        await engine.dispose()


async def test_independent_session_failure_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """独立 session 抛异常时**降级**，不抛出去。

    ## 为什么

    公开来源是增益——落库失败时那些结果仍然作为纯文本证据参与 Analyst
    核对，只是不产生角标。抛出去会让整批搜索结果失去角标（连同批里
    正常的那几条），而且没有提示。

    这条路径由 ``tools.py`` 的 ``except Exception`` 兜住并返回无角标的
    outcome——但那层兜的是**整个批次**。这里验的是更细的一层：某一条
    落库失败时，其余的照常登记。
    """
    from app.services import web_sources

    original = web_sources._create_web_source
    calls = {"n": 0}

    async def _sometimes_fails(*args: Any, **kwargs: Any):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("独立 session 挂了")
        return await original(*args, **kwargs)

    monkeypatch.setattr(web_sources, "_create_web_source", _sometimes_fails)

    table = ReferenceTable()
    registered = await register_web_sources(
        db_session,
        user_id=await _make_user(db_session),
        table=table,
        evidence=[
            ToolEvidence(title="会失败的", excerpt="内容", url="https://a.test/1"),
            ToolEvidence(title="正常的", excerpt="内容", url="https://b.test/2"),
        ],
    )

    assert len(registered) == 1, "一条失败不该让整批失败"
    assert registered[0][1].title == "正常的"


async def test_stored_content_is_the_long_one_not_the_summary(db_session) -> None:
    """落库的正文要用**长的**那份，不是给 Analyst 的短摘要。

    ## 要防的回归（CR 实测，2026-11-08）

    ``ToolEvidence`` 早先只有一个字段承担两个职责：给 Analyst 核对的短摘要
    （200 字）与给 DB 的正文（该是 800 字）。短的赢了 —— 于是落库的
    ``DocumentChunk.content`` 只有 200 字。

    后果：critic 校验时回查的是这个 200 字的 chunk，**校验的是摘要而不是
    原文**——正是 ``faithfulness.py`` 那条注释（「拿它去校验等于用摘要证明
    摘要」）想避免的事，在公开来源上原样发生了。
    """
    from sqlalchemy import select

    long_text = "详细的内容。" * 300  # 远大于 200 字
    table = ReferenceTable()

    registered = await register_web_sources(
        db_session,
        user_id=await _make_user(db_session),
        table=table,
        evidence=[
            ToolEvidence(
                title="长内容来源",
                excerpt="短摘要",
                url="https://x.test/1",
                content=long_text,
            )
        ],
    )
    assert len(registered) == 1
    await db_session.commit()

    stored = (await db_session.execute(select(DocumentChunk.content))).scalars().first()
    assert stored is not None
    assert len(stored) > 200, f"落库的正文只有 {len(stored)} 字——用的是短摘要"


async def test_malformed_url_does_not_kill_the_whole_batch(db_session) -> None:
    """一条畸形 URL 不能让**整批**搜索结果失去角标。

    ## 要防的回归（CR 实测，2026-11-08）

    ``urlsplit`` 对含 NFKC 异常字符的 URL（全角斜杠等）抛 ValueError。
    一条坏 URL 抛出去 → 整批都失败 → ``tools.py`` 兜住后返回**没有角标**
    的 outcome——用户看到 3 条搜索结果，模型一条也引用不了，且无任何提示。
    """
    table = ReferenceTable()

    registered = await register_web_sources(
        db_session,
        user_id=await _make_user(db_session),
        table=table,
        evidence=[
            ToolEvidence(title="坏 URL", excerpt="内容", url="https://example.com／path"),
            ToolEvidence(title="好 URL", excerpt="内容", url="https://good.test/1"),
        ],
    )

    # **两条都要登记**——坏 URL 只是「没法归一化去重」，不是「不能用」。
    # 它仍然是一条有标题有摘要的证据，仍然该占角标号。
    assert len(registered) == 2, "一条坏 URL 不该让整批失败"
    titles = [item.title for _n, item, _ref in registered]
    assert "坏 URL" in titles and "好 URL" in titles, titles


async def test_evidence_block_includes_the_url(db_session) -> None:
    """证据块里必须带 URL。

    ## 为什么

    ``SYSTEM_PROMPT`` 明确要求「检索到的链接用 dedup 清理，避免把同一篇
    文章当成多份独立证据」——而 dedup 工具的入参是 URL 数组。模型在
    tool_result 里看不到链接，就**没法执行这条指令**，也没法在正文里写出
    出处链接。

    早先的改造把 URL 丢了（只渲染标题 + 摘要）——那是遗漏不是取舍
    （CR 实测，2026-11-08）。
    """
    table = ReferenceTable()
    registered = await register_web_sources(
        db_session,
        user_id=await _make_user(db_session),
        table=table,
        evidence=[ToolEvidence(title="报道", excerpt="内容", url="https://news.test/a")],
    )

    blocks = render_web_evidence(registered)

    assert "https://news.test/a" in blocks
    assert "URL:" in blocks


async def test_web_source_gets_a_citation_number(db_session) -> None:
    """公开来源占角标号，且与用户资料**共用一个编号空间**。

    ## 为什么

    两套编号会让角标指错：模型写 ``[3]`` 时可能指 Tavily 的第 3 条，
    而引用表里的 3 号是用户资料的切片——而且没有任何报错。
    """
    table = ReferenceTable()
    user_id = await _make_user(db_session)

    # 先占掉 1、2 号（模拟用户资料已经检索到两条）
    table.add(
        Reference(
            n=1,
            chunk_id=101,
            source_id=201,
            chunk_index=0,
            page=None,
            title="用户资料",
            excerpt="用户资料的内容",
            recall="向量+BM25",
        )
    )
    table.add(
        Reference(
            n=2,
            chunk_id=102,
            source_id=201,
            chunk_index=1,
            page=None,
            title="用户资料",
            excerpt="用户资料的内容",
            recall="向量+BM25",
        )
    )

    references = await register_web_sources(
        db_session, user_id=user_id, table=table, evidence=_evidence(1)
    )

    assert references[0][0] == 3, "公开来源必须接着用户资料的编号继续编"
    assert {r.n for r in table.all} == {1, 2, 3}


async def test_web_sources_are_not_in_the_users_library(db_session) -> None:
    """公开来源**不进**用户的资料列表。

    ## 为什么

    两个后果：
    - 出现在「我的资料」里是误导——用户没上传过它们
    - 本地检索按 ``list_owned`` 的结果收窄 source_ids
      （``retriever._user_source_ids``），混进去会让「我的资料里有没有
      说过 X」检索到网上搜来的片段
    """
    user_id = await _make_user(db_session)
    await register_web_sources(
        db_session, user_id=user_id, table=ReferenceTable(), evidence=_evidence(2)
    )
    # 用户自己上传的一份
    db_session.add(
        Source(
            user_id=user_id,
            title="我上传的资料",
            source_type="pdf",
            status="indexed",
            chunk_count=1,
            char_count=10,
        )
    )
    await db_session.commit()

    owned = await Source.list_owned(db_session, user_id)

    titles = [s.title for s in owned]
    assert "我上传的资料" in titles
    assert "报道1" not in titles, f"公开来源不该出现在资料列表里：{titles}"


async def test_web_source_chunks_are_not_indexed(db_session) -> None:
    """公开来源的切片**不进** BM25 / 向量索引。

    ## 为什么这条最要紧

    索引表（``chunk_embeddings`` / FTS）都按 ``document_chunks.id`` 建。
    公开来源的切片一旦进了索引，本地检索在**别的过滤条件失效**时
    就可能召回它们——而它们是网页摘要，不是用户上传的资料。

    ## 怎么验

    直接查索引表有没有它的行。这比「检索搜不到」更准：检索还有
    source_ids 过滤兜着，而索引表里有没有它是更根本的事实。

    之所以不用「没调 ingest 所以没进索引」的说法：那验证的是
    「我们没调那个函数」，不是「结果真的没进索引」。
    """
    from sqlalchemy import text

    from app.services import bm25
    from app.services.ingest import ensure_index_tables
    from app.services.vectorstore import create_vector_engine

    user_id = await _make_user(db_session)
    references = await register_web_sources(
        db_session, user_id=user_id, table=ReferenceTable(), evidence=_evidence(1)
    )
    await db_session.commit()
    chunk_id = references[0][2].chunk_id

    vec_engine = create_vector_engine("sqlite+aiosqlite:///:memory:")
    try:
        await ensure_index_tables(vec_engine)
        # **手工**把公开来源的切片塞进 BM25 索引——模拟「万一有人
        # 不小心把它索引了」的最坏情况。
        await bm25.index_chunks(vec_engine, [(chunk_id, "公开来源的内容 销量 100 万")])

        # BM25 索引里有它（我们手工塞的）
        hits = await bm25.search(vec_engine, "公开来源的内容", 10, None)
        assert len(hits) >= 1, "前置条件不成立：BM25 里应该有这条"

        # 但本地检索的 source_ids **不包含**它——
        # ``Source.list_owned`` 排除了 web 类型。
        source_ids = await _user_source_ids(db_session, user_id)
        assert references[0][2].source_id not in source_ids, (
            f"公开来源的 source_id {references[0][2].source_id} 不该进本地检索的候选集"
        )

        # 且按候选集过滤后搜不到
        filtered = await bm25.search(vec_engine, "公开来源的内容", 10, source_ids)
        assert filtered == [], f"公开来源不该被本地检索召回：{filtered}"
    finally:
        await vec_engine.dispose()


async def test_registration_failure_does_not_raise(db_session, monkeypatch) -> None:
    """落库失败**不抛**——正文已经流给用户了，公开来源是增益。"""
    from app.services import web_sources

    async def _boom(*args, **kwargs):
        raise RuntimeError("DB 挂了")

    monkeypatch.setattr(web_sources, "_create_web_source", _boom)

    references = await register_web_sources(
        db_session, user_id=1, table=ReferenceTable(), evidence=_evidence(2)
    )

    assert references == []


async def test_registration_failure_does_not_poison_the_session(db_session, monkeypatch) -> None:
    """落库失败后 session 还能用——失败的那条不能连累整轮研究。

    ## 要防的回归

    flush 失败后 session 进入「事务已回滚」状态，后续任何 ``db.add()`` /
    ``flush()`` 都抛 ``PendingRollbackError``。实测（2026-11-07，
    SQLite + 开启 FK）：第一次 flush 抛 IntegrityError，之后的 flush
    全部抛 PendingRollbackError。

    不回滚的话，一条公开来源落库失败会**连累落盘报告**——
    ``persist_report`` 用的是同一个 session，它一失败报告就没了。
    而公开来源只是增益。

    ## 怎么测

    造一个真的会触发约束失败的写入（user_id 指向不存在的用户），
    然后断言：登记失败之后，这个 session 还能正常写入别的东西。
    """
    user_id = await _make_user(db_session)

    from app.services import web_sources

    original = web_sources._create_web_source

    async def _failing(db, uid, table, item, content, *, n):
        # **真的让 flush 失败**：user_id 指向不存在的用户 → FK 违规。
        #
        # 手抛 IntegrityError 不行——那样 session 并没有进入 failed 状态，
        # 后续写入照样成功，测不到「一次失败连累整轮研究」这个 bug。
        # 必须是**真实的约束失败**（flush 真的失败）才会污染 session。
        return await original(db, 99999, table, item, content, n=n)

    monkeypatch.setattr(web_sources, "_create_web_source", _failing)

    await register_web_sources(
        db_session, user_id=user_id, table=ReferenceTable(), evidence=_evidence(1)
    )

    # **关键**：这个 session 还能用
    db_session.add(
        Source(
            user_id=user_id,
            title="失败之后还能写的资料",
            source_type="pdf",
            status="indexed",
            chunk_count=1,
            char_count=10,
        )
    )
    await db_session.flush()
    await db_session.commit()

    owned = await Source.list_owned(db_session, user_id)
    assert any(s.title == "失败之后还能写的资料" for s in owned), (
        f"session 被失败的那次写入污染了，后续写入全失败：{owned}"
    )


async def test_registration_failure_keeps_other_writes_in_the_transaction(
    db_session, monkeypatch
) -> None:
    """一条公开来源失败**不能**把本轮已写入的其它内容一起丢掉。

    ## 为什么这条与上一条不同

    上一条验的是「session 还能用」。这一条验的是「**别的内容还在**」。

    修法有两条路：

    - ``db.rollback()`` —— 回滚**整个**事务。本轮已写入的其它内容
      （比如别的工具刚写的行）一起没了。
    - ``begin_nested()``（SAVEPOINT）—— 只回滚这一段，外层事务不受影响。

    两条路都能让 session 继续用，所以「session 还能用」这个断言**分不出
    它们**。要分开就得验「本轮之前写的东西还在不在」。

    ## 怎么测

    先写一条用户资料（同一事务里），再让公开来源落库失败，
    然后断言那条用户资料还在。
    """
    from app.services import web_sources

    user_id = await _make_user(db_session)

    # **同一事务里**先写一条用户资料
    db_session.add(
        Source(
            user_id=user_id,
            title="本轮之前写入的资料",
            source_type="pdf",
            status="indexed",
            chunk_count=1,
            char_count=10,
        )
    )
    await db_session.flush()

    original = web_sources._create_web_source

    async def _failing(db, uid, table, item, content, *, n):
        return await original(db, 99999, table, item, content, n=n)

    monkeypatch.setattr(web_sources, "_create_web_source", _failing)

    await register_web_sources(
        db_session, user_id=user_id, table=ReferenceTable(), evidence=_evidence(1)
    )
    await db_session.commit()

    owned = await Source.list_owned(db_session, user_id)
    titles = [s.title for s in owned]
    assert "本轮之前写入的资料" in titles, f"一次公开来源落库失败把本轮已写入的内容也丢了：{titles}"


async def test_empty_evidence_is_a_noop(db_session) -> None:
    """没有搜索结果时什么都不做。"""
    references = await register_web_sources(
        db_session, user_id=1, table=ReferenceTable(), evidence=[]
    )  # user_id 无所谓——没有证据就不会碰库
    assert references == []


def test_render_web_evidence_uses_the_reference_numbers() -> None:
    """渲染的证据块用**引用表里的实际编号**，不是算出来的。

    ## 为什么

    早先用「渲染全量 evidence + 从 ``references[0].n`` 起算」——登记时
    跳过的条目（去重命中、摘要空白、表满）会造成整体错位：提示词里的
    ``[3]`` 在引用表里是另一条。模型写 ``[3]`` → 前端点开是 B 的原文，
    提示词说的却是 A。

    现在渲染直接用登记时记下的编号，两者必然一致。
    """
    entries = [
        (3, _evidence(2)[0], _fake_reference(3)),
        (4, _evidence(2)[1], _fake_reference(4)),
    ]

    blocks = render_web_evidence(entries)

    assert "[3]" in blocks
    assert "[4]" in blocks
    # 不能出现从 1 开始的另一套编号
    assert "[1]" not in blocks
    assert "[2]" not in blocks


def test_render_web_evidence_skips_unregistered_entries() -> None:
    """没登记上的条目**不渲染**——否则编号会错位。

    这是 S1 那个 bug 的核心：渲染全量 evidence 而编号只给已登记的那些。
    """
    # 只登记了第 2 条（第 1 条被去重跳过）
    entries = [(7, _evidence(2)[1], _fake_reference(7))]

    blocks = render_web_evidence(entries)

    assert "[7]" in blocks
    assert "[6]" not in blocks, "未登记的条目不能占编号"
    assert "第 1 条" not in blocks


def _fake_reference(n: int) -> Reference:
    return Reference(
        n=n,
        chunk_id=n,
        source_id=1,
        chunk_index=0,
        page=None,
        title="来源",
        excerpt="内容",
        recall="网页搜索",
    )


def test_web_citation_rules_state_the_actual_range() -> None:
    """编号规则必须写**实际**区间，并禁止编造编号。

    ## 为什么强调「实际」

    早先的版本只写上界（``web_citation_rules(upper)``），渲染出来是
    「编号 [1] 到 [3]」——而这批公开来源实际是 [3] 到 [3]。模型看到
    「[1] 到 [3]」就会去引用 1 号，而 1 号可能是用户资料的切片。
    角标指错，且没有任何报错。
    """
    rules = web_citation_rules(3, 5)

    assert "[3] 到 [5]" in rules
    assert "[1] 到" not in rules, "不能写从 1 开始——那些号是用户资料的"
    assert "严禁编造" in rules


def test_web_citation_rules_with_a_single_source() -> None:
    """只有一条时区间是同一个号——写法要成立。"""
    rules = web_citation_rules(3, 3)

    assert "[3] 到 [3]" in rules


def test_web_citation_rules_is_empty_without_references() -> None:
    assert web_citation_rules(0, 0) == ""


async def test_reference_table_add_rejects_duplicates() -> None:
    """同一个 chunk 重复登记不占新号。"""
    table = ReferenceTable()
    ref = Reference(
        n=1,
        chunk_id=101,
        source_id=201,
        chunk_index=0,
        page=None,
        title="来源",
        excerpt="内容",
        recall="网页搜索",
    )

    assert table.add(ref) is True
    assert table.add(ref) is False
    assert len(table.all) == 1


async def test_reference_table_add_respects_the_cap() -> None:
    """引用表满了之后 ``add`` 返回 False 并计入丢弃数。"""
    from app.services.citation import MAX_REFERENCES

    table = ReferenceTable()
    for i in range(MAX_REFERENCES):
        assert (
            table.add(
                Reference(
                    n=i + 1,
                    chunk_id=100 + i,
                    source_id=201,
                    chunk_index=0,
                    page=None,
                    title="来源",
                    excerpt="内容",
                    recall="网页搜索",
                )
            )
            is True
        )

    overflow = table.add(
        Reference(
            n=MAX_REFERENCES + 1,
            chunk_id=999,
            source_id=201,
            chunk_index=0,
            page=None,
            title="来源",
            excerpt="内容",
            recall="网页搜索",
        )
    )

    assert overflow is False
    assert table.dropped == 1


@pytest.mark.parametrize("excerpt", ["", "   "])
async def test_blank_excerpt_is_skipped(db_session, excerpt: str) -> None:
    """空摘要不产生来源——那会建出一条没有任何内容的切片。"""
    user_id = await _make_user(db_session)
    references = await register_web_sources(
        db_session,
        user_id=user_id,
        table=ReferenceTable(),
        evidence=[ToolEvidence(title="空结果", excerpt=excerpt, url="https://x.test")],
    )

    assert references == []
