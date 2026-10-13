"""source / document_chunks 模型的测试。

重点是归属校验——``Source.find_owned`` 不校验 user_id 的话，
别人的 source_id 就能被读到。
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User


async def _make_user(session: AsyncSession, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0])
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_source(session: AsyncSession, user: User, **kwargs: object) -> Source:
    defaults: dict[str, object] = {
        "title": "测试资料",
        "source_type": SourceType.TEXT,
        "status": SourceStatus.PENDING,
    }
    defaults.update(kwargs)
    source = Source(user_id=user.id, **defaults)  # type: ignore[arg-type]
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


# ── 归属校验 ────────────────────────────────────────────────
async def test_find_owned_returns_own_source(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "owner@test.local")
    source = await _make_source(db_session, user)

    found = await Source.find_owned(db_session, source.id, user.id)

    assert found is not None
    assert found.id == source.id


async def test_find_owned_rejects_other_users_source(db_session: AsyncSession) -> None:
    """别人的 source_id 必须查不到——这是唯一的越权防线。"""
    owner = await _make_user(db_session, "owner@test.local")
    attacker = await _make_user(db_session, "attacker@test.local")
    source = await _make_source(db_session, owner)

    assert await Source.find_owned(db_session, source.id, attacker.id) is None


async def test_find_owned_rejects_missing_id(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "owner@test.local")

    assert await Source.find_owned(db_session, 99999, user.id) is None


async def test_list_owned_only_returns_own(db_session: AsyncSession) -> None:
    mine = await _make_user(db_session, "mine@test.local")
    theirs = await _make_user(db_session, "theirs@test.local")
    await _make_source(db_session, mine, title="我的 A")
    await _make_source(db_session, mine, title="我的 B")
    await _make_source(db_session, theirs, title="别人的")

    owned = await Source.list_owned(db_session, mine.id)

    assert {s.title for s in owned} == {"我的 A", "我的 B"}


async def test_list_owned_empty_for_new_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "fresh@test.local")

    assert await Source.list_owned(db_session, user.id) == []


async def test_list_owned_does_not_load_chunk_content(db_session: AsyncSession) -> None:
    """列资料不能把切片正文拖回来——列表页只显示 title/status。

    ``Source.chunks`` 曾经是 ``lazy="selectin"``，无条件 eager：查任何
    Source 都会连带 SELECT 它的全部切片（含 content）。实测 list_owned
    会发出两条 SQL，第二条把整份资料的正文拉进内存，一个字符都用不上。

    现在是 ``lazy="raise"``——碰它直接报错，逼调用方显式查询。这比
    「默默加载一大坨用不上的东西」安全得多。
    """
    user = await _make_user(db_session, "eager@test.local")
    source = await _make_source(db_session, user)
    db_session.add(DocumentChunk(source_id=source.id, chunk_index=0, content="正文"))
    await db_session.commit()

    loaded = await Source.list_owned(db_session, user.id)

    assert len(loaded) == 1
    with pytest.raises(InvalidRequestError):
        _ = loaded[0].chunks


# ── 默认值 ─────────────────────────────────────────────────
async def test_source_defaults(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "d@test.local")
    source = await _make_source(db_session, user)

    assert source.status == SourceStatus.PENDING
    assert source.chunk_count == 0
    assert source.char_count == 0
    assert source.credibility_score == 0.5
    assert source.url is None


# ── chunk ──────────────────────────────────────────────────
async def test_chunk_unique_index_per_source(db_session: AsyncSession) -> None:
    """同一资料内 chunk_index 不能重复——引用编号依赖它唯一。"""
    user = await _make_user(db_session, "c@test.local")
    source = await _make_source(db_session, user)
    db_session.add(DocumentChunk(source_id=source.id, chunk_index=0, content="第一片"))
    await db_session.commit()

    db_session.add(DocumentChunk(source_id=source.id, chunk_index=0, content="重复序号"))

    with pytest.raises(Exception):  # noqa: B017 — IntegrityError 的子类随驱动变化
        await db_session.commit()


async def test_same_index_allowed_across_sources(db_session: AsyncSession) -> None:
    """唯一约束是 (source_id, chunk_index) 复合的，不同资料的 0 号片不冲突。"""
    user = await _make_user(db_session, "c2@test.local")
    a = await _make_source(db_session, user, title="A")
    b = await _make_source(db_session, user, title="B")

    db_session.add(DocumentChunk(source_id=a.id, chunk_index=0, content="A-0"))
    db_session.add(DocumentChunk(source_id=b.id, chunk_index=0, content="B-0"))
    await db_session.commit()

    assert len(await DocumentChunk.list_for_source(db_session, a.id)) == 1
    assert len(await DocumentChunk.list_for_source(db_session, b.id)) == 1


async def test_list_for_source_ordered_by_index(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "c3@test.local")
    source = await _make_source(db_session, user)
    for i in reversed([0, 1, 2]):
        db_session.add(DocumentChunk(source_id=source.id, chunk_index=i, content=f"片 {i}"))
    await db_session.commit()

    chunks = await DocumentChunk.list_for_source(db_session, source.id)

    assert [c.chunk_index for c in chunks] == [0, 1, 2]


async def test_find_many_empty_returns_nothing(db_session: AsyncSession) -> None:
    """空 id 列表不该生成 ``IN ()`` 这种语法错误的 SQL。"""
    assert await DocumentChunk.find_many(db_session, []) == []


async def test_deleting_source_cascades_to_chunks(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "c4@test.local")
    source = await _make_source(db_session, user)
    db_session.add(DocumentChunk(source_id=source.id, chunk_index=0, content="片"))
    await db_session.commit()

    await db_session.delete(source)
    await db_session.commit()

    assert await DocumentChunk.list_for_source(db_session, source.id) == []


# ── 时间语义 ─────────────────────────────────────────────────
async def test_server_default_timestamps_come_back_utc_aware(db_session: AsyncSession) -> None:
    """server_default 写的行也必须是 aware。

    这条路径与显式赋值不同：``func.now()`` 在**数据库侧**求值，根本不经过
    ``process_bind_param``。装饰器只挡住了 Python 侧显式赋值的那一半，
    读回那一半（``process_result_value``）才决定这两种写法是否一致。
    两边不一致时，同一列里的值取决于当时用了哪种写法。
    """
    user = await _make_user(db_session, "tz@test.local")
    source = await _make_source(db_session, user)

    for label, value in (
        ("source.created_at", source.created_at),
        ("source.updated_at", source.updated_at),
        ("user.created_at", user.created_at),
    ):
        assert value is not None, label
        assert value.utcoffset() == UTC.utcoffset(None), label


async def test_timestamps_are_comparable_with_aware_now(db_session: AsyncSession) -> None:
    """库里读出的时间能与 ``datetime.now(UTC)`` 直接相减。

    这是 naive 值最常见的炸点：``aware - naive`` 抛 TypeError，而调用点
    通常是个看起来无害的「算一下过期了没有」。token.py 的签发时间就是
    这么和库里的记录对上的。
    """
    user = await _make_user(db_session, "cmp@test.local")

    age = datetime.now(UTC) - user.created_at

    assert timedelta(0) <= age < timedelta(minutes=5)


async def test_explicit_aware_value_normalized_to_utc(db_session: AsyncSession) -> None:
    """写入带时区的时间，取回时是同一个瞬间、UTC 标注。

    存进去的是 +08:00 的值，取回来必须是等价的 UTC 值——不能是原样带
    +08:00 读出（跨时区展示会错），更不能是被当成本地时间改写（数据漂移）。
    """
    user = await _make_user(db_session, "tz8@test.local")
    shanghai = timezone(timedelta(hours=8))
    moment = datetime(2026, 3, 1, 12, 0, tzinfo=shanghai)

    source = Source(
        user_id=user.id,
        title="跨时区",
        source_type=SourceType.TEXT,
        status=SourceStatus.PENDING,
        created_at=moment,
    )
    db_session.add(source)
    await db_session.commit()

    # populate_existing：identity map 里躺着的还是刚插入的那个 Python 对象，
    # 直接 get() 拿到它就绕过了 process_result_value，测不到任何东西。
    row = await db_session.get(Source, source.id, populate_existing=True)
    assert row is not None
    assert row.created_at == moment
    assert row.created_at.utcoffset() == UTC.utcoffset(None)


async def test_naive_explicit_value_kept_as_is(db_session: AsyncSession) -> None:
    """显式写入 naive 值不被拒绝，也不被静默改写。

    刻意如此：拒绝会让所有手写 ``datetime(2026, 1, 1)`` 的调用方（脚本、
    测试夹具）全炸；静默改写会让「我以为存的是 UTC」变成无法验证的假设。
    这里的契约是「按 UTC 解读」，读回来就是带 UTC 的那个瞬间。
    """
    user = await _make_user(db_session, "naive@test.local")
    moment = datetime(2026, 3, 1, 12, 0)

    source = Source(
        user_id=user.id,
        title="裸时间",
        source_type=SourceType.TEXT,
        status=SourceStatus.PENDING,
        created_at=moment,
    )
    db_session.add(source)
    await db_session.commit()

    # populate_existing：identity map 里躺着的还是刚插入的那个 Python 对象，
    # 直接 get() 拿到它就绕过了 process_result_value，测不到任何东西。
    row = await db_session.get(Source, source.id, populate_existing=True)
    assert row is not None
    assert row.created_at == moment.replace(tzinfo=UTC)
