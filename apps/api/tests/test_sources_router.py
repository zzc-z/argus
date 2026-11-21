"""资料源路由的测试。

重点是**鉴权**：每个端点都必须校验归属，越权一律 404（不是 403——
403 等于确认了这个 id 存在，是信息泄露）。

摄取走后台任务，端点本身不跑管线，所以这里把 `_schedule_ingest` 换掉，
只覆盖「HTTP 边界 + 鉴权 + 参数校验」。管线行为由 tests/test_ingest.py 负责。
"""

from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway import sources as sources_mod
from app.models import Source, SourceStatus, SourceType, User

TXT = "第一章 绪论。本文讨论检索增强生成的实现路径与评估方法。"

# 在 autouse fixture 把它换成空实现**之前**抓住真身。
# 用模块级常量而不是 monkeypatch.undo()——后者会把 conftest 的
# _reset_env（APP_ENV=test）一起撤掉，等于绕过测试的环境约定。
_REAL_SCHEDULE_URL_INGEST = sources_mod._schedule_url_ingest


# ── fixtures ───────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path: Path) -> None:
    """上传目录指向临时目录，别污染仓库。"""
    from app.config import get_settings

    get_settings().source_upload_dir = str(tmp_path / "uploads")


@pytest.fixture(autouse=True)
def _no_background_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """把后台摄取换成空实现——端点测试不该跑管线。

    URL 建源的后台任务同样要停：它会真去发网络请求。
    """
    monkeypatch.setattr("app.gateway.sources._schedule_ingest", lambda _sid, _p: None)
    monkeypatch.setattr("app.gateway.sources._schedule_url_ingest", lambda *_a: None)


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


async def test_create_from_url_schedules_fetch(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """建源后必须排上抓取任务，否则 source 永远停在 pending。

    这正是本任务修的缺口：端点原来只登记不抓取。
    """
    user = await _user(api_db, "url3@t.local")
    _auth(client, user)
    recorded: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        "app.gateway.sources._schedule_url_ingest",
        lambda sid, url, stype: recorded.append((sid, url, stype)),
    )

    resp = client.post(
        "/api/v1/sources/url",
        json={"title": "报道", "url": "https://example.com/a", "source_type": "html"},
    )

    assert recorded == [(resp.json()["id"], "https://example.com/a", "html")]


async def test_create_from_url_delegates_to_spawner(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点只负责「排上任务」，不负责跑任务。

    抓一个慢站点要耗满 20 秒超时；端点里同步跑等于让前端转圈 20 秒
    才拿到一个必然失败的响应。这里断言端点把活交给 _spawn——
    _spawn 内部用 create_task，不阻塞调用方。
    """
    user = await _user(api_db, "url4@t.local")
    _auth(client, user)
    # autouse fixture 把 _schedule_url_ingest 换成了空实现，
    # 不还原的话端点走不到 _spawn，测的是 fixture 而不是端点。
    monkeypatch.setattr("app.gateway.sources._schedule_url_ingest", _REAL_SCHEDULE_URL_INGEST)
    spawned: list[int] = []

    def _fake_spawn(coro: Coroutine[Any, Any, None]) -> None:
        spawned.append(1)
        # 不 await 的话协程会被 GC 掉并抛 RuntimeWarning；
        # 本项目的 filterwarnings=error 会把它升级成失败。显式 close 掉。
        coro.close()

    monkeypatch.setattr("app.gateway.sources._spawn", _fake_spawn)

    resp = client.post("/api/v1/sources/url", json={"title": "x", "url": "https://x.test"})

    assert resp.status_code == 201
    assert len(spawned) == 1


async def test_spawn_returns_before_coroutine_finishes() -> None:
    """_spawn 必须立即返回，不等被排的协程跑完。

    这是「端点不等抓取」真正成立的地方。用 Event 而不是 sleep 计时：
    协程被确定地卡在 Event 上，_spawn 若同步等它就必然死锁/超时，
    测试失败是确定的，不受机器快慢影响。
    """
    import asyncio

    gate = asyncio.Event()
    started = asyncio.Event()

    async def _blocked() -> None:
        started.set()
        await gate.wait()

    sources_mod._spawn(_blocked())
    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert not gate.is_set()  # 协程确实还卡着，而 _spawn 已经返回了
    gate.set()


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


# ── 版本分组：activate 端点与重复上传 ──────────────────────
async def test_activate_switches_active_version_in_group(
    client: TestClient, api_db: AsyncSession
) -> None:
    """把归档版本设为生效版，同组旧版自动转归档。

    **在哪种错误实现下也会通过**：只把目标设成 is_active=True、却不归档
    同组其他版本的实现，会撞部分唯一索引（组内至多一条生效版）而 500；
    而「用普通唯一索引 (group_id, is_active)」的实现则会让两条归档版
    建不出来——上面的 ``_source`` helper 建同组两份 is_active=False 就炸。
    所以这条同时验证了「先归档后激活」的顺序与部分索引的形态。
    """
    from app.models import SourceGroup

    user = await _user(api_db, "act@t.local")
    group = SourceGroup(user_id=user.id)
    api_db.add(group)
    await api_db.commit()
    await api_db.refresh(group)
    group_id = group.id

    old = await _source(api_db, user.id, group_id=group_id, is_active=True, version_no=1)
    new = await _source(api_db, user.id, group_id=group_id, is_active=False, version_no=2)
    _auth(client, user)

    resp = client.patch(f"/api/v1/sources/{new.id}/activate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # 重新查库看真实状态。
    #
    # 用 ``populate_existing`` 绕开 identity map——不绕的话查回来的还是
    # 那个已被 expire 的对象，属性访问会触发**同步上下文里的懒加载**
    # （MissingGreenlet：greenlet_spawn has not been called）。
    states = {
        row.id: row.is_active
        for row in (
            await api_db.execute(
                select(Source)
                .where(Source.group_id == group_id)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    }
    assert states[new.id] is True
    assert states[old.id] is False


async def test_activate_other_users_source_returns_404(
    client: TestClient, api_db: AsyncSession
) -> None:
    """越权 404 不是 403——403 等于确认 id 存在。"""
    me = await _user(api_db, "act-me@t.local")
    owner = await _user(api_db, "act-owner@t.local")
    their_sid = (await _source(api_db, owner.id)).id
    _auth(client, me)

    assert client.patch(f"/api/v1/sources/{their_sid}/activate").status_code == 404


async def test_upload_rejects_identical_content_with_409(
    client: TestClient, api_db: AsyncSession
) -> None:
    """内容完全相同、**且已建成索引**的文件重复上传 → 409。

    **在哪种错误实现下也会通过**：只按 ``title`` 查重的实现会漏掉
    「改了名但内容一样」的情况——这里两次上传用的是**不同文件名**，
    同样内容。所以这条验证的是按 content_hash 查重，不是按名字。

    ## 为什么要先标成 indexed

    查重只拦**已建成索引**的那份（见
    ``app.services.grouping.find_duplicate_hash``）：没建成索引的
    重传是恢复动作，不是重复上传。而本测试的摄取被 fixture 换成了
    空实现，所以第一份停在 pending——直接再传会走「恢复」那条路，
    不会 409。要验「真正的重复」得先把第一份标成 indexed。
    """
    user = await _user(api_db, "dup@t.local")
    _auth(client, user)

    first = client.post("/api/v1/sources", files=_upload("a.txt"))
    assert first.status_code == 201

    row = (
        await api_db.execute(
            select(Source)
            .where(Source.id == first.json()["id"])
            .execution_options(populate_existing=True)
        )
    ).scalars().one()
    row.status = SourceStatus.INDEXED
    await api_db.commit()

    second = client.post("/api/v1/sources", files=_upload("b.txt"))
    assert second.status_code == 409


async def test_upload_allows_different_content(
    client: TestClient, api_db: AsyncSession
) -> None:
    """内容不同的文件即使同名也该放行——那是「新版本」，不是重复。

    **在哪种错误实现下也会通过**：按 title 查重的实现会把这条拦成 409。
    """
    user = await _user(api_db, "diff@t.local")
    _auth(client, user)

    first = client.post("/api/v1/sources", files=_upload("same.txt"))
    assert first.status_code == 201

    other = TXT + "补充说明：第二版新增了结论章节与参考文献。"
    second = client.post("/api/v1/sources", files=_upload("same.txt", other.encode()))
    assert second.status_code == 201


async def test_upload_duplicate_does_not_leak_other_users_content(
    client: TestClient, api_db: AsyncSession
) -> None:
    """别人的文件内容与自己相同**不该**被拒——查重带 user_id 约束。

    **在哪种错误实现下也会通过**：查重漏掉 ``user_id`` 条件的实现会
    把这条变成 409，而 409 的文案会暴露「有人上传过同样内容」。
    """
    owner = await _user(api_db, "owner-dup@t.local")
    await _source(api_db, owner.id, content_hash=_sha256(TXT.encode()))

    me = await _user(api_db, "me-dup@t.local")
    _auth(client, me)

    resp = client.post("/api/v1/sources", files=_upload())
    assert resp.status_code == 201


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


# ── 版本分组：生效版的资格与删除后的接管 ──────────────────────


async def test_activate_rejects_not_indexed_source(
    client: TestClient, api_db: AsyncSession
) -> None:
    """摄取失败的版本不能设为生效版 → 409。

    ## 为什么这条是硬约束

    生效版是检索候选集的一员。**没有切片的资料占了这个位置**，
    等于「整组都搜不到」：

    旧版（indexed，10 切片）是唯一能用的，被顶掉归档；
    失败版（failed，0 切片）成为生效版，但它一条切片都没有。

    用户看到的是「资料都还在，搜不到任何东西」，且没有任何错误提示。
    嵌入服务欠费（已知状态）会让摄取失败的版本很常见。

    **在哪种错误实现下也会通过**：只断言「返回 200」的旧实现会红；
    只拒绝 ``status=pending`` 但放行 ``failed`` 的实现也会红——
    所以这里明确用 ``failed`` 造场景。
    """
    from app.models import SourceGroup

    user = await _user(api_db, "notindexed@t.local")
    group = SourceGroup(user_id=user.id)
    api_db.add(group)
    await api_db.commit()
    await api_db.refresh(group)
    group_id = group.id

    old = await _source(
        api_db, user.id, group_id=group_id, is_active=True, version_no=1,
        status=SourceStatus.INDEXED, chunk_count=10,
    )
    failed = await _source(
        api_db, user.id, group_id=group_id, is_active=False, version_no=2,
        status=SourceStatus.FAILED, chunk_count=0, error_message="嵌入服务欠费",
    )
    _auth(client, user)

    resp = client.patch(f"/api/v1/sources/{failed.id}/activate")

    assert resp.status_code == 409, "没建成索引的版本不能接管生效位"

    # 旧版必须仍是生效版——不能因为这次被拒的请求而受影响。
    states = {
        row.id: row.is_active
        for row in (
            await api_db.execute(
                select(Source)
                .where(Source.group_id == group_id)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    }
    assert states[old.id] is True, "旧版必须仍是生效版"
    assert states[failed.id] is False


async def test_delete_active_version_promotes_remaining_one(
    client: TestClient, api_db: AsyncSession
) -> None:
    """删掉组内的生效版 → 组里剩下的版本接管生效位。

    ## 为什么必须有接管

    检索候选集是「组内 ``is_active=True`` 的那些」。删掉生效版而不接管，
    组里剩下的版本全是 ``is_active=False``——还在库里、还能点开，
    但**一份都召不回来**。这是「只检索生效版」引入的行为回归。

    **在哪种错误实现下也会通过**：只断言「删除返回 204」的实现会绿——
    所以这条必须回头查库里的 ``is_active``。
    """
    from app.models import SourceGroup

    user = await _user(api_db, "delpromote@t.local")
    group = SourceGroup(user_id=user.id)
    api_db.add(group)
    await api_db.commit()
    await api_db.refresh(group)
    group_id = group.id

    old = await _source(
        api_db, user.id, group_id=group_id, is_active=False, version_no=1,
        status=SourceStatus.INDEXED,
    )
    active = await _source(
        api_db, user.id, group_id=group_id, is_active=True, version_no=2,
        status=SourceStatus.INDEXED,
    )
    _auth(client, user)

    resp = client.delete(f"/api/v1/sources/{active.id}")
    assert resp.status_code == 204

    states = {
        row.id: row.is_active
        for row in (
            await api_db.execute(
                select(Source)
                .where(Source.group_id == group_id)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    }
    assert states[old.id] is True, "剩下的版本必须接管生效位，否则它永远召不回来"


async def test_reupload_after_failed_ingest_is_allowed(
    client: TestClient, api_db: AsyncSession
) -> None:
    """摄取失败后重传同一份文件 → **放行**（201），不拦 409。

    ## 为什么

    摄取失败时库里留下的那行**一条切片都没有**，用户重传同一份文件是
    **恢复动作**，不是「重复上传」——``app/services/ingest.py`` 的
    ``mark_failed`` docstring 明写「用户重传即刻恢复」。

    若把 failed 的也算重复，用户会遇到死路：重传被 409 拒，而唯一能
    解开的办法是先手动删掉那份失败资料——而 409 的文案
    「这份资料已经上传过了」只字未提要删。进程重启丢掉后台摄取任务
    同样会留下 failed 行，重传是那里的唯一出路。

    **在哪种错误实现下也会通过**：只测「成功的那份被拦」的实现会绿——
    所以这条先把第一份标成 failed 再重传。
    """
    user = await _user(api_db, "retry@t.local")
    _auth(client, user)

    first = client.post("/api/v1/sources", files=_upload("a.txt"))
    assert first.status_code == 201
    first_id = first.json()["id"]

    # 把那份标成摄取失败（嵌入服务欠费是已知状态）。
    row = (
        await api_db.execute(
            select(Source).where(Source.id == first_id).execution_options(populate_existing=True)
        )
    ).scalars().one()
    row.status = SourceStatus.FAILED
    row.error_message = "嵌入服务欠费"
    await api_db.commit()

    second = client.post("/api/v1/sources", files=_upload("a.txt"))

    assert second.status_code == 201, "失败后重传是恢复动作，不该被 409 拦"


async def test_upload_skips_parsing_when_pool_too_small(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """候选池不足时，上传**不解析正文**。

    ## 为什么

    池子不足 ``MIN_CANDIDATES_FOR_GROUPING`` 份时归组**一定不成立**
    ——那时的解析结果会被直接丢掉。50MB 的 DOCX 展开 XML 要好几秒，
    用户的 201 响应被拖住，而结果被扔了。

    顺序反过来还有个副作用：解析失败会走「归组退化为自建新组」，
    白打一条 warning 日志。

    **在哪种错误实现下也会通过**：只断言「上传成功」的实现——
    上传确实成功，差别只在解析有没有被调用。所以这条必须数
    ``parse`` 的调用次数。
    """
    from app.services import source_versions as sv_mod

    user = await _user(api_db, "noparse@t.local")
    _auth(client, user)

    calls: list[bytes] = []
    original = sv_mod._parse_blocks

    def counting_parse(payload: bytes, source_type: str) -> Any:
        calls.append(payload)
        return original(payload, source_type)

    monkeypatch.setattr(sv_mod, "_parse_blocks", counting_parse)

    resp = client.post("/api/v1/sources", files=_upload("a.txt"))

    assert resp.status_code == 201
    assert calls == [], "候选池只有 0 份，不该解析正文——结果会被丢掉"


async def test_duplicate_upload_supersedes_the_pending_one(
    client: TestClient, api_db: AsyncSession
) -> None:
    """误点两次上传 → 旧的 pending 行被作废，不产生两份重复资料。

    ## 为什么

    两条内容完全相同的 Source 若都建成索引，都会生效、都进检索池——
    检索会召回两份一模一样的证据，模型把同一段话当成两个独立来源
    互相印证。

    ## 为什么不是 409

    409 会把「进程重启丢掉后台摄取任务」后的恢复路径也堵死——重传被
    拒，用户只能手动删僵尸行，而 409 的文案只字未提要删。

    所以：已建成索引的 → 拒（409）；没建成索引的 → 作废，让新的接管。

    **在哪种错误实现下也会通过**：只断言「两次都是 201」的实现——
    所以这条必须查库里那条旧行变成什么了。
    """
    user = await _user(api_db, "duppending@t.local")
    _auth(client, user)

    first = client.post("/api/v1/sources", files=_upload("a.txt"))
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post("/api/v1/sources", files=_upload("b.txt"))
    assert second.status_code == 201

    rows = (
        await api_db.execute(
            select(Source).where(Source.user_id == user.id).order_by(Source.id)
        )
    ).scalars().all()

    first_row = next(r for r in rows if r.id == first_id)
    second_row = next(r for r in rows if r.id != first_id)
    assert first_row.status == SourceStatus.SUPERSEDED, "旧的 pending 行该被作废"
    assert first_row.is_active is False, "作废的行不能是生效版"
    assert second_row.status == SourceStatus.PENDING, "新的照常走摄取"
