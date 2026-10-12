"""source / document_chunks 模型的测试。

重点是归属校验——``Source.find_owned`` 不校验 user_id 的话，
别人的 source_id 就能被读到。
"""

import pytest
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
