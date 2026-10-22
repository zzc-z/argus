"""Dashboard 概览与系统状态接口的测试。

## 这两个接口防的是什么

它们替代了 `/dashboard` 与 `/settings` 页上原先那套**编出来的** KPI 与
状态数字。改错的后果不是「显示不准」这么轻——

- 少算一份报告，用户会以为系统没保存成功，去重复跑一次研究（真花钱）
- 算进别人的报告/资料，用户会以为自己有��少数据，运维会顺着错数据
  往下查

所以每个用例都显式造**两个用户**的数据，断言「只算我的」——单用户
的测试在这两处都会通过（只有一个用户时"不隔离"和"隔离"结果相同）。
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.models.report import Report


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


async def _chunk(db: AsyncSession, source_id: int, count: int = 1) -> list[int]:
    """造 count 个切片，返回它们的 id。

    返回 id 是为了能造向量影子表的行——``chunk_embeddings_rowids`` 的一行
    对应一个 chunk_id。
    """
    ids: list[int] = []
    for i in range(count):
        chunk = DocumentChunk(
            source_id=source_id,
            chunk_index=i,
            content="正文",
            page=None,
            start_offset=0,
            end_offset=2,
        )
        db.add(chunk)
        await db.flush()
        ids.append(chunk.id)
    await db.commit()
    return ids


async def _embed(db: AsyncSession, chunk_ids: list[int]) -> None:
    """造向量影子表的行。

    ``chunk_embeddings`` 是 vec0 虚表，测试库不建它；vec0 为虚表建的
    影子表 ``chunk_embeddings_rowids`` 是**真实表**，普通 SQL 就能插——
    而统计用的正是它。
    """
    await db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS chunk_embeddings_rowids "
            "(chunk_id INTEGER PRIMARY KEY)"
        )
    )
    for cid in chunk_ids:
        await db.execute(
            text("INSERT INTO chunk_embeddings_rowids (chunk_id) VALUES (:cid)"),
            {"cid": cid},
        )
    await db.commit()


async def _report(
    db: AsyncSession,
    user_id: int,
    question: str,
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    created_at: datetime | None = None,
) -> Report:
    report = Report(
        user_id=user_id,
        question=question,
        content="正文",
        session_id=f"sess-{question}",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_ms=1000,
    )
    if created_at is not None:
        report.created_at = created_at
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


def _auth(client: TestClient, user: User | int) -> None:
    from app.services.token import create_access_token

    uid = user.id if isinstance(user, User) else user
    client.cookies.set("argus_session", create_access_token(uid))


# ── dashboard ─────────────────────────────────────────────
async def test_dashboard_counts_only_own_data(
    db_session: AsyncSession, client: TestClient
) -> None:
    """KPI 只统计当前用户的报告与资料。

    **这个用例要两个用户**——只有一个用户时，「不隔离」与「隔离」的结果
    完全一样，测不出隔离逻辑有没有写。
    """
    me = await _user(db_session, "me@example.com")
    other = await _user(db_session, "other@example.com")

    await _report(db_session, me.id, "我的报告", input_tokens=10, output_tokens=20)
    await _report(db_session, other.id, "别人的报告", input_tokens=999, output_tokens=999)

    my_source = await _source(db_session, me.id, "我的资料")
    await _source(db_session, other.id, "别人的资料")
    await _chunk(db_session, my_source.id, count=3)

    _auth(client, me)
    resp = client.get("/api/v1/dashboard")
    assert resp.status_code == 200
    body = resp.json()

    assert body["report_count"] == 1
    assert body["source_count"] == 1
    assert body["chunk_count"] == 3
    assert body["total_input_tokens"] == 10
    assert body["total_output_tokens"] == 20
    assert [r["question"] for r in body["recent_reports"]] == ["我的报告"]


async def test_dashboard_empty_for_new_user(
    db_session: AsyncSession, client: TestClient
) -> None:
    """新用户看不到任何别人的数据。

    反过来也成立：库里有别人的数据时，新用户的 KPI 必须全是 0。
    """
    other = await _user(db_session, "other@example.com")
    await _report(db_session, other.id, "别人的报告")
    me = await _user(db_session, "me@example.com")

    _auth(client, me)
    body = client.get("/api/v1/dashboard").json()

    assert body["report_count"] == 0
    assert body["source_count"] == 0
    assert body["chunk_count"] == 0
    assert body["total_input_tokens"] == 0
    assert body["total_output_tokens"] == 0
    assert body["recent_reports"] == []


async def test_dashboard_recent_reports_sorted_newest_first(
    db_session: AsyncSession, client: TestClient
) -> None:
    """最近报告按时间倒序——页面上「最新生成」在第一条。

    三条报告的 created_at 显式拉开间隔：同秒创建的报告在 SQLite 里
    排序不稳定，测试会偶发通过偶发失败。
    """
    me = await _user(db_session, "me@example.com")
    base = datetime(2026, 10, 1, tzinfo=UTC)
    await _report(db_session, me.id, "最旧", created_at=base)
    await _report(db_session, me.id, "最新", created_at=base + timedelta(hours=2))
    await _report(db_session, me.id, "中间", created_at=base + timedelta(hours=1))

    _auth(client, me)
    body = client.get("/api/v1/dashboard").json()

    assert body["report_count"] == 3
    assert [r["question"] for r in body["recent_reports"]] == ["最新", "中间", "最旧"]


async def test_dashboard_requires_auth(client: TestClient) -> None:
    """未登录拿不到任何统计。"""
    resp = client.get("/api/v1/dashboard")
    assert resp.status_code == 401


# ── settings/status ───────────────────────────────────────
async def test_settings_status_reports_vector_index(
    db_session: AsyncSession, client: TestClient
) -> None:
    """向量索引规模按当前用户统计。"""
    me = await _user(db_session, "me@example.com")
    other = await _user(db_session, "other@example.com")

    my_source = await _source(db_session, me.id, "我的资料")
    await _source(db_session, other.id, "别人的资料")
    await _chunk(db_session, my_source.id, count=2)

    _auth(client, me)
    resp = client.get("/api/v1/settings/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["vector_index"]["source_count"] == 1
    assert body["vector_index"]["chunk_count"] == 2
    # 嵌入数走 vec0 虚拟表，测试库里没建 → 0，且不能因此让整个接口 500。
    assert body["vector_index"]["embedded_chunk_count"] == 0


async def test_settings_status_counts_only_own_embeddings(
    db_session: AsyncSession, client: TestClient
) -> None:
    """已向量化的数量按当前用户过滤，与「检索切片」同口径。

    vec0 虚表没有 user_id 列，所以数向量要 join 一条到 sources。**不
    join 的话页面上会出现「已向量化 7398 > 检索切片 7388」**——两个数
    不同口径并排显示，用户没法解读（多用户下更离谱：别人的向量算进
    我的索引里）。

    影子表 ``chunk_embeddings_rowids`` 在测试库里不存在（它是 vec0 运行时
    建的），所以这里手工造一张——它就是一张普通表，普通 SQL 能查。
    """
    me = await _user(db_session, "me@example.com")
    other = await _user(db_session, "other@example.com")

    my_source = await _source(db_session, me.id, "我的资料")
    other_source = await _source(db_session, other.id, "别人的资料")
    my_chunks = await _chunk(db_session, my_source.id, count=2)
    other_chunks = await _chunk(db_session, other_source.id, count=1)

    # 两个用户的切片都已向量化——共 3 个向量。
    await _embed(db_session, [*my_chunks, *other_chunks])

    _auth(client, me)
    body = client.get("/api/v1/settings/status").json()

    assert body["vector_index"]["chunk_count"] == 2
    # 只有我自己的 2 个——别人的那个不能算进来。
    assert body["vector_index"]["embedded_chunk_count"] == 2


async def test_settings_status_never_leaks_secrets(
    db_session: AsyncSession, client: TestClient
) -> None:
    """响应里不能出现任何密钥内容。

    ``detail`` 只说「配了没有」——把 key 的一小段放进去（比如给排障用）
    就是把凭据写进前端 bundle 与浏览器历史。
    """
    me = await _user(db_session, "me@example.com")
    _auth(client, me)

    body = client.get("/api/v1/settings/status").json()
    raw = str(body)

    from app.config import get_settings

    settings = get_settings()
    for secret in (
        settings.anthropic_api_key,
        settings.tavily_api_key,
        settings.embedding_api_key,
    ):
        if secret is None:
            continue
        value = secret.get_secret_value()
        if value:
            assert value not in raw
            # 连密钥的前 6 位也不能漏——那也是凭据的一部分。
            assert value[:6] not in raw


async def test_settings_status_lists_all_providers(
    db_session: AsyncSession, client: TestClient
) -> None:
    """三个外部能力都要出现在列表里——少一个用户就看不出少了什么。"""
    me = await _user(db_session, "me@example.com")
    _auth(client, me)

    body = client.get("/api/v1/settings/status").json()
    ids = {p["id"] for p in body["providers"]}
    assert ids == {"anthropic", "tavily", "embedding"}
    for provider in body["providers"]:
        assert isinstance(provider["configured"], bool)
        assert provider["detail"]


async def test_settings_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/settings/status")
    assert resp.status_code == 401
