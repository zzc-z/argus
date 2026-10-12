"""资料源路由的测试。

重点是**鉴权**：每个端点都必须校验归属，越权一律 404（不是 403——
403 等于确认了这个 id 存在，是信息泄露）。

摄取走后台任务，端点本身不跑管线，所以这里把 `_schedule_ingest` 换掉，
只覆盖「HTTP 边界 + 鉴权 + 参数校验」。管线行为由 tests/test_ingest.py 负责。
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceStatus, SourceType, User

TXT = "第一章 绪论。本文讨论检索增强生成的实现路径与评估方法。"


# ── fixtures ───────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path: Path) -> None:
    """上传目录指向临时目录，别污染仓库。"""
    from app.config import get_settings

    get_settings().source_upload_dir = str(tmp_path / "uploads")


@pytest.fixture(autouse=True)
def _no_background_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """把后台摄取换成空实现——端点测试不该跑管线。"""
    monkeypatch.setattr("app.gateway.sources._schedule_ingest", lambda _sid, _p: None)


# ── helpers ───────────────────────────────────────────────
# 测试写成 async def 直接 await（asyncio_mode=auto 让 async 测试无需装饰器）。
# 不套 TestClient 的同步测试——那需要 get_event_loop().run_until_complete，
# 在不同 pytest/asyncio 版本下行为不一致。
async def _user(db: AsyncSession, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0])
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _source(db: AsyncSession, user_id: int, **kw: Any) -> Source:
    data: dict[str, Any] = {
        "title": "资料",
        "source_type": SourceType.TEXT,
        "status": SourceStatus.INDEXED,
    }
    data.update(kw)
    row = Source(user_id=user_id, **data)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _auth(client: TestClient, user: User | int) -> None:
    from app.services.token import create_access_token

    uid = user.id if isinstance(user, User) else user
    client.cookies.set("argus_session", create_access_token(uid))


def _upload(name: str = "report.txt", body: bytes | None = None) -> dict[str, Any]:
    payload = TXT.encode() if body is None else body
    return {"file": (name, payload, "text/plain")}


# ── 鉴权 ───────────────────────────────────────────────────
def test_list_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/sources").status_code == 401


def test_upload_requires_login(client: TestClient) -> None:
    assert client.post("/api/v1/sources", files=_upload()).status_code == 401


def test_create_from_url_requires_login(client: TestClient) -> None:
    resp = client.post("/api/v1/sources/url", json={"title": "x", "url": "https://x.test"})
    assert resp.status_code == 401


async def test_read_other_users_source_returns_404(
    client: TestClient, api_db: AsyncSession
) -> None:
    """越权要 404 不是 403——403 等于确认 id 存在。"""
    me = await _user(api_db, "mine@t.local")
    owner = await _user(api_db, "owner@t.local")
    their_sid = (await _source(api_db, owner.id)).id
    _auth(client, me)

    assert client.get(f"/api/v1/sources/{their_sid}").status_code == 404


async def test_chunks_of_other_users_source_returns_404(
    client: TestClient, api_db: AsyncSession
) -> None:
    me = await _user(api_db, "mine@t.local")
    owner = await _user(api_db, "owner2@t.local")
    sid = (await _source(api_db, owner.id)).id
    _auth(client, me)

    assert client.get(f"/api/v1/sources/{sid}/chunks").status_code == 404


async def test_delete_other_users_source_returns_404(
    client: TestClient, api_db: AsyncSession
) -> None:
    me = await _user(api_db, "mine@t.local")
    owner = await _user(api_db, "owner3@t.local")
    sid = (await _source(api_db, owner.id)).id
    _auth(client, me)

    assert client.delete(f"/api/v1/sources/{sid}").status_code == 404


async def test_list_excludes_other_users_sources(
    client: TestClient, api_db: AsyncSession
) -> None:
    me = await _user(api_db, "mine@t.local")
    other = await _user(api_db, "other@t.local")
    await _source(api_db, me.id, title="我的资料")
    await _source(api_db, other.id, title="别人的资料")
    _auth(client, me)

    body = client.get("/api/v1/sources").json()

    assert [s["title"] for s in body["items"]] == ["我的资料"]
    assert body["total"] == 1


# ── 上传 ───────────────────────────────────────────────────
async def test_upload_creates_source(client: TestClient, api_db: AsyncSession) -> None:
    user = await _user(api_db, "u@t.local")
    _auth(client, user)

    resp = client.post("/api/v1/sources", files=_upload())

    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "report.txt"
    assert body["source_type"] == "text"
    assert body["status"] == "pending"


async def test_upload_rejects_unsupported_extension(
    client: TestClient, api_db: AsyncSession
) -> None:
    user = await _user(api_db, "u2@t.local")
    _auth(client, user)

    resp = client.post(
        "/api/v1/sources",
        files={"file": ("clip.mp4", b"\x00" * 100, "video/mp4")},
    )

    assert resp.status_code == 415


async def test_upload_rejects_empty_file(client: TestClient, api_db: AsyncSession) -> None:
    user = await _user(api_db, "u3@t.local")
    _auth(client, user)

    resp = client.post("/api/v1/sources", files=_upload(body=b""))

    assert resp.status_code == 400


async def test_upload_detects_pdf_type(client: TestClient, api_db: AsyncSession) -> None:
    user = await _user(api_db, "u6@t.local")
    _auth(client, user)

    resp = client.post("/api/v1/sources", files=_upload("paper.pdf", b"%PDF-1.7"))

    assert resp.json()["source_type"] == "pdf"


async def test_upload_schedules_ingest(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上传后必须排上摄取任务，否则 source 永远停在 pending。"""
    user = await _user(api_db, "u4@t.local")
    _auth(client, user)
    recorded: list[int] = []
    monkeypatch.setattr(
        "app.gateway.sources._schedule_ingest",
        lambda sid, _payload: recorded.append(sid),
    )

    resp = client.post("/api/v1/sources", files=_upload())

    assert recorded == [resp.json()["id"]]


async def test_upload_stores_file_on_disk(
    client: TestClient, api_db: AsyncSession
) -> None:
    """文件系统的阻塞调用用 to_thread 丢到线程池（ruff ASYNC240）。

    不能为了躲 lint 就把这个测试改成同步——那样就得用 run_until_complete
    那套 hack，反而更脆。
    """
    import asyncio
    from functools import partial

    from app.config import get_settings

    user = await _user(api_db, "u5@t.local")
    _auth(client, user)

    resp = client.post("/api/v1/sources", files=_upload())
    assert resp.status_code == 201

    upload_dir = Path(get_settings().source_upload_dir)
    exists, count = await asyncio.gather(
        asyncio.to_thread(upload_dir.is_dir),
        asyncio.to_thread(lambda: len(list(upload_dir.iterdir()))),
    )
    assert exists
    assert count == 1


# ── URL 建源 ───────────────────────────────────────────────
async def test_create_from_url(client: TestClient, api_db: AsyncSession) -> None:
    user = await _user(api_db, "url@t.local")
    _auth(client, user)

    resp = client.post(
        "/api/v1/sources/url",
        json={"title": "某篇报道", "url": "https://example.com/a", "source_type": "html"},
    )

    assert resp.status_code == 201
    assert resp.json()["url"] == "https://example.com/a"


async def test_create_from_url_rejects_blank_title(
    client: TestClient, api_db: AsyncSession
) -> None:
    user = await _user(api_db, "url2@t.local")
    _auth(client, user)

    resp = client.post("/api/v1/sources/url", json={"title": "  ", "url": "https://x.test"})

    assert resp.status_code == 422


# ── 读与删 ─────────────────────────────────────────────────
async def test_read_own_source(client: TestClient, api_db: AsyncSession) -> None:
    user = await _user(api_db, "r@t.local")
    sid = (await _source(api_db, user.id, title="我的研报")).id
    _auth(client, user)

    body = client.get(f"/api/v1/sources/{sid}").json()

    assert body["title"] == "我的研报"


async def test_read_missing_source_returns_404(client: TestClient, api_db: AsyncSession) -> None:
    user = await _user(api_db, "r2@t.local")
    _auth(client, user)

    assert client.get("/api/v1/sources/999999").status_code == 404


async def test_delete_own_source(client: TestClient, api_db: AsyncSession) -> None:
    user = await _user(api_db, "d@t.local")
    sid = (await _source(api_db, user.id)).id
    _auth(client, user)

    assert client.delete(f"/api/v1/sources/{sid}").status_code == 204
    assert client.get(f"/api/v1/sources/{sid}").status_code == 404


async def test_list_chunks_of_own_source(client: TestClient, api_db: AsyncSession) -> None:
    from app.models import DocumentChunk

    user = await _user(api_db, "c@t.local")
    sid = (await _source(api_db, user.id)).id

    api_db.add(DocumentChunk(source_id=sid, chunk_index=0, content="第一片", page=1))
    await api_db.commit()
    _auth(client, user)

    body = client.get(f"/api/v1/sources/{sid}/chunks").json()

    assert len(body) == 1
    assert body[0]["content"] == "第一片"
    assert body[0]["page"] == 1
