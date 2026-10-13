"""URL 建源的后台管线测试：抓取 → 落盘 → 摄取 → 状态落库。

这一层要验的是**状态与错误信息**的流转，字节正确性由 tests/test_fetcher.py 管。
端点只返回 201 就走，用户唯一的反馈渠道就是轮询到的 status / error_message——
所以「失败时这两者有没有写对」比抓到什么内容更要紧。

库用 ``shared_db`` fixture：业务表与向量索引必须在同一个 SQLite 文件里，
否则混合检索的子查询查不到行（见 conftest 的说明）。绝不碰开发库 argus.db。
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway import sources as sources_gateway
from app.models import DocumentChunk, Source, SourceStatus, SourceType, User
from app.services import fetcher, storage

ARTICLE = (
    "检索增强生成把外部知识接进大模型的上下文窗口，从而缓解模型参数中知识的过时问题。"
    "评估这类系统时常用答案正确率与召回率两个指标对比不同实现的优劣。"
    "检索器的召回不足会让生成器缺少关键证据，生成器的指令跟随不足则会浪费检索到的内容。"
    "工程上常见的折中是先召回较大候选集再重排，代价是多一次模型调用。"
)

# 正文长度取真实量级。实测 trafilatura 在正文只有几十字时会判定「密度不足」
# 退回宽松策略，连导航一起留下；正文够长时才认得出 <article> 是正文块。
PAGE = f"""<html><head><title>T</title></head><body>
<nav>Skip to content / Main menu / Sign in</nav>
<article><p>{ARTICLE}{ARTICLE}{ARTICLE}</p></article>
<footer>Privacy policy / All rights reserved</footer>
</body></html>""".encode()


@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path: Path) -> None:
    from app.config import get_settings

    get_settings().source_upload_dir = str(tmp_path / "uploads")


@pytest.fixture(autouse=True)
def _no_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有 embedding key 时摄取照样走完（只少向量），不引入网络调用。"""

    async def _none(_texts: Any) -> None:
        return None

    monkeypatch.setattr("app.services.ingest.embed_or_none", _none)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 DNS 解析钉死，杜绝测试真的去联网。"""

    def _fake(_host: str, *_a: Any, **_kw: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    monkeypatch.setattr(fetcher.socket, "getaddrinfo", _fake)


def _transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    real = httpx.AsyncClient
    monkeypatch.setattr(
        fetcher.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


async def _user(db: AsyncSession) -> User:
    user = User(email="url@test.local", display_name="t")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _source(db: AsyncSession, user: User, url: str = "https://a.test/x") -> Source:
    source = Source(
        user_id=user.id,
        title="网页",
        source_type=SourceType.HTML,
        url=url,
        status=SourceStatus.PENDING,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@pytest.fixture
def bind_gateway_db(monkeypatch: pytest.MonkeyPatch, shared_db: tuple) -> Any:
    """把后台任务用的 SessionLocal 换到测试库。

    不换的话 ``_fetch_then_ingest`` 会开一个连 argus.db 的 session——
    测试写进开发库，而且症状是「测试全绿」，不会报错。
    """
    session, engine = shared_db
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(sources_gateway, "SessionLocal", factory)
    monkeypatch.setattr(sources_gateway, "get_vector_engine", lambda: engine)
    return session, engine


# ── 正常路径 ──────────────────────────────────────────────
async def test_url_source_ends_up_indexed(
    bind_gateway_db: tuple, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """抓到的内容要真的走完管线，状态落到 indexed 并切出正文。"""
    session, _engine = bind_gateway_db
    _transport(monkeypatch, lambda _r: httpx.Response(200, content=PAGE))
    user = await _user(session)
    src = await _source(session, user)

    await sources_gateway._fetch_then_ingest(src.id, src.url, SourceType.HTML)

    await session.refresh(src)
    assert src.status == SourceStatus.INDEXED
    assert src.chunk_count > 0
    assert src.char_count > 0
    assert src.error_message is None

    chunks = await DocumentChunk.list_for_source(session, src.id)
    joined = "".join(c.content for c in chunks)
    assert "检索增强生成" in joined
    # 导航不进正文——否则它会污染 embedding
    assert "Skip to content" not in joined


async def test_fetched_bytes_are_persisted(
    bind_gateway_db: tuple, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """抓到的字节要落盘。

    摄取失败最常见的原因是没配 embedding key，用户重跑时不该还要
    那个站点恰好在线、恰好返回同样的内容。
    """
    session, _engine = bind_gateway_db
    _transport(monkeypatch, lambda _r: httpx.Response(200, content=PAGE))
    user = await _user(session)
    src = await _source(session, user)

    await sources_gateway._fetch_then_ingest(src.id, src.url, SourceType.HTML)

    await session.refresh(src)
    assert src.storage_path is not None
    assert src.size_bytes is not None and src.size_bytes > 0
    assert storage.read_upload(src.storage_path)


# ── 错误路径：抓取失败要落进 error_message ────────────────
@pytest.mark.parametrize(
    ("status", "needle"),
    [(404, "404"), (403, "403"), (500, "500")],
)
async def test_http_error_is_recorded_on_source(
    bind_gateway_db: tuple,
    offline: None,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    needle: str,
) -> None:
    """非 2xx 要落成 failed + 带状态码的 error_message。

    用户据此判断是该换链接还是换个时间再试——不给状态码等于让他瞎猜。
    """
    session, _engine = bind_gateway_db
    _transport(monkeypatch, lambda _r: httpx.Response(status))
    user = await _user(session)
    src = await _source(session, user)

    await sources_gateway._fetch_then_ingest(src.id, src.url, SourceType.HTML)

    await session.refresh(src)
    assert src.status == SourceStatus.FAILED
    assert needle in (src.error_message or "")
    assert await DocumentChunk.list_for_source(session, src.id) == []


async def test_ssrf_block_is_recorded_without_leaking_internals(
    bind_gateway_db: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内网地址要被拒，且 message 里不能出现被拦下的原始响应内容。"""

    def _fake(host: str, *_a: Any, **_kw: Any) -> list[tuple[Any, ...]]:
        ip = "127.0.0.1" if host == "a.test" else "10.0.0.5"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    monkeypatch.setattr(fetcher.socket, "getaddrinfo", _fake)
    _transport(monkeypatch, lambda _r: httpx.Response(200, content=b"SECRET"))
    session, _engine = bind_gateway_db
    user = await _user(session)
    src = await _source(session, user, url="http://a.test/x")

    await sources_gateway._fetch_then_ingest(src.id, src.url, SourceType.HTML)

    await session.refresh(src)
    assert src.status == SourceStatus.FAILED
    assert "内网" in (src.error_message or "")
    assert "SECRET" not in (src.error_message or "")


async def test_unexpected_error_does_not_leak_internals(
    bind_gateway_db: tuple, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """抓取器抛未预期异常时，message 要概括，细节只进日志。

    否则内部异常文案（可能含路径、主机名）会直接显示在页面上。
    """

    def _boom(*_a: Any, **_kw: Any) -> bytes:
        raise RuntimeError("secret internal detail at /var/run/x.sock")

    monkeypatch.setattr("app.gateway.sources.fetch_for_ingest", _boom)
    session, _engine = bind_gateway_db
    user = await _user(session)
    src = await _source(session, user)

    await sources_gateway._fetch_then_ingest(src.id, src.url, SourceType.HTML)

    await session.refresh(src)
    assert src.status == SourceStatus.FAILED
    assert src.error_message == "抓取时发生内部错误"
    assert "secret internal detail" not in (src.error_message or "")


@pytest.mark.parametrize(
    ("body", "label"),
    [(b"", "空 body"), (b"<html><body><div></div></body></html>", "只有标签没有文字")],
)
async def test_page_without_text_fails_with_parser_message(
    bind_gateway_db: tuple,
    offline: None,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    label: str,
) -> None:
    """抓到了但整页没文字——状态要落 failed，且带上解析器的原话。

    端到端验证「抓取成功不等于摄取成功」：这条链路上用户唯一能看到结果的
    就是 status 与 error_message，中间卡住等于什么都没发生。
    """
    session, _engine = bind_gateway_db
    _transport(monkeypatch, lambda _r: httpx.Response(200, content=body))
    user = await _user(session)
    src = await _source(session, user)

    await sources_gateway._fetch_then_ingest(src.id, src.url, SourceType.HTML)

    await session.refresh(src)
    assert src.status == SourceStatus.FAILED, label
    assert "正文" in (src.error_message or "")


async def test_json_body_is_indexed_not_rejected(
    bind_gateway_db: tuple, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """锁定一个**已知取舍**：贴 JSON API 地址会切出一个垃圾片，但不报错。

    抓取层退回原始字节后，HtmlParser 剥完标签仍能从 ``{"json": true}`` 里
    取出文字，于是照样入库。这不是 bug 修复没做，是「JSON 不算研究资料」
    属于产品规则、不该由抓取层替用户决定。这条测试的作用是：将来真要加
    content-type 拦截时，它会先失败，提醒你这是**有意**的行为变更。
    """
    session, _engine = bind_gateway_db
    _transport(monkeypatch, lambda _r: httpx.Response(200, content=b'{"json": true}'))
    user = await _user(session)
    src = await _source(session, user)

    await sources_gateway._fetch_then_ingest(src.id, src.url, SourceType.HTML)

    await session.refresh(src)
    assert src.status == SourceStatus.INDEXED
    chunks = await DocumentChunk.list_for_source(session, src.id)
    assert "".join(c.content for c in chunks)


async def test_missing_source_does_not_crash(
    bind_gateway_db: tuple, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """建源与后台任务之间被删——任务要安静退出，不能把后台任务抛爆。"""
    _transport(monkeypatch, lambda _r: httpx.Response(200, content=PAGE))

    await sources_gateway._fetch_then_ingest(999999, "https://a.test/gone", SourceType.HTML)
