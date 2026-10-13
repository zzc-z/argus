"""抓取层的测试。

**全程零网络**。HTTP 用 httpx.MockTransport 打桩——真实抓站的测试在 CI 上
必炸（站点改版、代理、超时），而且验证不了重定向与 SSRF 这些真正要守的行为。
DNS 用 monkeypatch 打桩成受控 IP 表，同理。

重点是**错误路径与 SSRF**：抓取是唯一一处「用户给的字符串会变成对外网络请求」
的地方，挡不住就是任意内网读取。成功路径只做薄薄一层，正文质量由
tests/test_parser.py 与实抓对比覆盖。
"""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest

from app.models import SourceType
from app.services import fetcher
from app.services.fetcher import FetchError, fetch_for_ingest

ARTICLE = (
    "The actual body discusses retrieval augmented generation and its evaluation. "
    "A retriever with poor recall starves the generator of key evidence. "
    "A generator that ignores instructions wastes whatever the retriever found. "
    "The usual engineering trade-off is a large candidate set followed by a rerank, "
    "at the cost of one extra model call per query in the research pipeline."
)

# 正文长度取真实量级。实测 trafilatura 在正文只有几十字时会判定「文本密度不足」
# 退回宽松策略，连 <nav> 一起留下；正文够长时才认得出 <article> 是正文块。
# fixture 太短会让「导航不该进正文」这条断言测到的是 trafilatura 的短页行为，
# 而不是「正文提取确实在干活」——那不是我们想锁的东西。
PAGE_WITH_NOISE = f"""<html><head><title>Real Article</title></head><body>
<nav>Skip to content / Main menu / Sign in</nav>
<article><h1>Real Article</h1><p>{ARTICLE}{ARTICLE}{ARTICLE}</p></article>
<footer>Privacy policy / All rights reserved / Subscribe to our newsletter</footer>
</body></html>""".encode()

BODY_ONLY = f"<html><body><article><p>{ARTICLE}</p></article></body></html>".encode()


# ── 打桩工具 ──────────────────────────────────────────────
def _install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Any, **kwargs: Any
) -> None:
    """把 fetcher 用的 httpx client 换成 MockTransport。

    替换构造函数而不是 client 实例：``_download`` 内部自己建 client，
    换实例就得改生产代码结构。kwargs 透传给真实构造函数（timeout 等）。
    """
    real = httpx.AsyncClient

    def _factory(**client_kwargs: Any) -> httpx.AsyncClient:
        client_kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **client_kwargs)

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", _factory)


def _resolve_to(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str]) -> None:
    """让 DNS 解析结果固定下来：``mapping`` 里没有的域名一律解析失败。"""

    def _fake(host: str, *_a: Any, **_kw: Any) -> list[tuple[Any, ...]]:
        if host not in mapping:
            raise socket.gaierror(f"无法解析 {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], 80))]

    monkeypatch.setattr(fetcher.socket, "getaddrinfo", _fake)


def _raise(exc: Exception) -> Any:
    """构造一个「一被调用就抛 exc」的 handler。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


PUBLIC = {"93.184.216.34": "93.184.216.34", "cdn.example.com": "93.184.216.34"}
# 首跳公网、跳板目标内网。cdn.example.com 必须在表里——它不在的话首跳就因
# DNS 解析失败被拒，测试会因为「拒绝发生了」而绿，但没验到重定向那一跳。
PRIVATE = {"cdn.example.com": "93.184.216.34", "internal.example.com": "127.0.0.1"}


# ── 正文提取 ──────────────────────────────────────────────
async def test_fetch_strips_navigation_and_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """导航与页脚不该进正文——它们会污染 embedding，进而污染检索结果。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=PAGE_WITH_NOISE))
    _resolve_to(monkeypatch, PUBLIC)

    payload = await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)

    text = payload.decode()
    assert "retrieval augmented generation" in text
    assert "cookie" not in text.lower()
    assert "newsletter" not in text.lower()
    assert "privacy policy" not in text.lower()


async def test_fetch_keeps_html_shape_for_html_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTML 类型必须交出 HTML——ingest 之后还要过 parser.HtmlParser。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=PAGE_WITH_NOISE))
    _resolve_to(monkeypatch, PUBLIC)

    payload = await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)

    assert b"<" in payload
    from app.services.parser import HtmlParser

    assert "retrieval augmented generation" in HtmlParser().parse(payload)[0].text


async def test_text_type_yields_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEXT 类型交纯文本，ingest 之后走 TextParser（按 \\f 分页）。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=PAGE_WITH_NOISE))
    _resolve_to(monkeypatch, PUBLIC)

    payload = await fetch_for_ingest("http://cdn.example.com/a", SourceType.TEXT)

    assert b"<p>" not in payload
    assert b"retrieval augmented generation" in payload


async def test_pdf_passes_through_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """PDF 是二进制，正文提取器对它只会返回 None——必须原样透传。"""
    raw = b"%PDF-1.7\nbinary\x00stuff"
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=raw))
    _resolve_to(monkeypatch, PUBLIC)

    assert await fetch_for_ingest("http://cdn.example.com/p.pdf", SourceType.PDF) == raw


async def test_undegradable_body_falls_back_to_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """提不出正文时退回原始字节，不在这里报错。

    理由：真正「这是不是可用正文」由解析器判断，它的报错更贴切
    （ParseError 会带上「网页里没有可提取的正文」）。抓取层抢答只会
    把信息说糙。
    """
    raw = b'{"data": [1, 2, 3]}'
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=raw))
    _resolve_to(monkeypatch, PUBLIC)

    assert await fetch_for_ingest("http://cdn.example.com/api.json", SourceType.HTML) == raw


async def test_extractor_crash_falls_back_to_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """提取器抛异常也不能让整次抓取失败——它只是优化，不是必经环节。"""
    raw = b"<html><body><p>body</p></body></html>"

    def _boom(*_a: Any, **_kw: Any) -> str:
        raise RuntimeError("trafilatura exploded")

    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=raw))
    _resolve_to(monkeypatch, PUBLIC)
    monkeypatch.setattr(fetcher.trafilatura, "extract", _boom)

    assert await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML) == raw


async def test_tiny_page_keeps_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    """**已知残留**：正文短到几十字时，导航会被一起留下。

    实测 trafilatura 在这种页面上判定「文本密度不足」，退回宽松策略把
    <nav> 当正文。真实页面（Wikipedia / 新浪财经 / 网易）实测噪声命中为 0，
    所以不加 ``favor_precision``——它在 163.com 上直接返回 0 字符，
    为了去掉导航而丢掉整篇文章，代价大得多。

    这条测试锁住「我们知道有这个边界」，不是锁住「已解决」。将来若换了解析器，
    它会先失败并提醒重新评估。
    """
    tiny = b"""<html><body><nav>Skip to content</nav>
    <article><p>Short.</p></article></body></html>"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=tiny))
    _resolve_to(monkeypatch, PUBLIC)

    payload = await fetch_for_ingest("http://cdn.example.com/tiny", SourceType.HTML)

    assert b"Skip to content" in payload


# ── HTTP 错误路径 ─────────────────────────────────────────
@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 502, 503])
async def test_non_2xx_raises_with_status(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """非 2xx 必须报出状态码——用户要分得清「404 链接没了」和「被限流」。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(code))
    _resolve_to(monkeypatch, PUBLIC)

    with pytest.raises(FetchError, match=str(code)):
        await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)


async def test_timeout_raises_user_readable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时对用户是「站点太慢」，不是 httpx 的异常类名。"""
    _install_transport(monkeypatch, _raise(httpx.ReadTimeout("slow")))
    _resolve_to(monkeypatch, PUBLIC)

    with pytest.raises(FetchError, match="超时"):
        await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("refused"),
        httpx.ReadError("peer reset"),
        httpx.RemoteProtocolError("server disconnected"),
        httpx.ProxyError("bad proxy"),
    ],
)
async def test_transport_errors_become_fetch_error(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    """连接层失败要转成 FetchError。

    不转的话 httpx 异常会一路冒到后台任务，被上层当「未预期错误」记成
    「抓取时发生内部错误」——用户看到的是一句误导性的内部错误，
    而实际只是那个站点挂了。
    """
    _install_transport(monkeypatch, _raise(exc))
    _resolve_to(monkeypatch, PUBLIC)

    with pytest.raises(FetchError, match="无法连接"):
        await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)


async def test_connect_timeout_reports_timeout_not_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ConnectTimeout 既是 TimeoutException 又是 TransportError。

    超时分支要排在前面：用户看到「超时」才知道该等或换个时间再试，
    看到「无法连接」只会以为是链接写错了。
    """
    _install_transport(monkeypatch, _raise(httpx.ConnectTimeout("handshake")))
    _resolve_to(monkeypatch, PUBLIC)

    with pytest.raises(FetchError, match="超时"):
        await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)


async def test_malformed_url_is_reported_as_bad_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空字节这类畸形 URL 要报「格式不合法」。

    httpx 抛的 InvalidURL 不在 TransportError 继承里（实测直接挂在 HTTPError 下），
    少接一个分支它就会一路冒到后台任务，被记成「抓取时发生内部错误」——那是误导。

    打桩 DNS 让它先过 SSRF 复检：这里要测的是**过了复检之后** httpx 的反应，
    不是 DNS 那一步。
    """
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=BODY_ONLY))
    monkeypatch.setattr(
        fetcher.socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
    )

    with pytest.raises(FetchError, match="格式不合法"):
        await fetch_for_ingest("http://cdn.example.com/\x00", SourceType.HTML)


async def test_oversized_body_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """超上限要在流式读取中就中断，不是收完 1GB 再判断。"""
    huge = b"<html><body>" + b"x" * (fetcher.MAX_FETCH_BYTES + 1) + b"</body></html>"
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=huge))
    _resolve_to(monkeypatch, PUBLIC)

    with pytest.raises(FetchError, match="上限"):
        await fetch_for_ingest("http://cdn.example.com/big", SourceType.HTML)


async def test_body_just_under_cap_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    """上限是硬边界不是保守估计——刚好卡在下面的合法页面要能过。"""
    filler = b"y" * (fetcher.MAX_FETCH_BYTES - 200)
    raw = b"<html><body><article><p>keep</p></article>" + filler + b"</body></html>"
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=raw))
    _resolve_to(monkeypatch, PUBLIC)

    assert await fetch_for_ingest("http://cdn.example.com/ok", SourceType.HTML)


async def test_empty_body_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 但空 body 不是抓取的错——解析器会给出「没有可提取的正文」。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=b""))
    _resolve_to(monkeypatch, PUBLIC)

    assert await fetch_for_ingest("http://cdn.example.com/empty", SourceType.HTML) == b""


# ── 重定向 ────────────────────────────────────────────────
async def test_follows_relative_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """相对 Location 必须按 RFC 3986 解析，不能原样当绝对 URL 发出去。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, content=BODY_ONLY)

    _install_transport(monkeypatch, handler)
    _resolve_to(monkeypatch, PUBLIC)

    payload = await fetch_for_ingest("http://cdn.example.com/start", SourceType.HTML)

    assert b"retrieval" in payload


async def test_redirect_chain_is_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    """多跳要跟到底——正常站点常有 http→https→带尾斜杠 两跳。"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/a":
            return httpx.Response(301, headers={"Location": "/b"})
        if path == "/b":
            return httpx.Response(302, headers={"Location": "https://cdn.example.com/c"})
        return httpx.Response(200, content=BODY_ONLY)

    _install_transport(monkeypatch, handler)
    _resolve_to(monkeypatch, PUBLIC)

    assert b"retrieval" in await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)


async def test_redirect_loop_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """互相跳转的死循环要停——否则后台任务会永远占着一个连接。"""
    _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(302, headers={"Location": "http://cdn.example.com/loop"}),
    )
    _resolve_to(monkeypatch, PUBLIC)

    with pytest.raises(FetchError, match="重定向"):
        await fetch_for_ingest("http://cdn.example.com/loop", SourceType.HTML)


async def test_redirect_without_location_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3xx 但没有 Location 是畸形响应，报错要明确。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(302))
    _resolve_to(monkeypatch, PUBLIC)

    with pytest.raises(FetchError, match="Location"):
        await fetch_for_ingest("http://cdn.example.com/a", SourceType.HTML)


# ── SSRF ──────────────────────────────────────────────────
async def test_redirect_into_private_network_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**最关键的一条**：公网 URL 302 到 127.0.0.1 必须被拒。

    httpx 自带的 follow_redirects=True 实测会把内网响应原样读出来。
    这里守的是「逐跳复检」这个设计，改成 follow_redirects 就会挂。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "internal.example.com":
            return httpx.Response(200, content=b"SECRET-INTERNAL-DATA")
        return httpx.Response(302, headers={"Location": "http://internal.example.com/admin"})

    _install_transport(monkeypatch, handler)
    _resolve_to(monkeypatch, PRIVATE)

    with pytest.raises(FetchError, match="内网"):
        await fetch_for_ingest("http://cdn.example.com/go", SourceType.HTML)


async def test_direct_private_host_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户直接贴内网地址也要挡——不能只防重定向那一条路。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=b"leak"))
    _resolve_to(monkeypatch, PRIVATE)

    with pytest.raises(FetchError, match="内网"):
        await fetch_for_ingest("http://internal.example.com/admin", SourceType.HTML)


async def test_cloud_metadata_endpoint_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """169.254.169.254 是云厂商 metadata 端点，拿它能换到实例凭据。"""
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=b"{}"))
    _resolve_to(monkeypatch, {"meta.internal": "169.254.169.254"})

    with pytest.raises(FetchError, match="内网"):
        await fetch_for_ingest("http://meta.internal/latest/meta-data/", SourceType.HTML)


@pytest.mark.parametrize(
    "raw_ip",
    ["127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254", "::1", "fc00::1"],
)
def test_is_public_ip_rejects_private_ranges(raw_ip: str) -> None:
    assert fetcher._is_public_ip(raw_ip) is False


@pytest.mark.parametrize("raw_ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111"])
def test_is_public_ip_accepts_public_addresses(raw_ip: str) -> None:
    assert fetcher._is_public_ip(raw_ip) is True


@pytest.mark.parametrize("raw_ip", ["224.0.0.1", "ff02::1"])
def test_is_public_ip_rejects_multicast(raw_ip: str) -> None:
    """224.0.0.1 实测 ``is_global`` 仍返回 True——这是 stdlib 的坑，必须单独挡。

    不加这一条，多播地址会被当成公网地址放行。
    """
    assert fetcher._is_public_ip(raw_ip) is False


async def test_mixed_dns_answer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS 同时给公网与内网记录时要全拒。

    只看第一条等于让攻击者靠轮询把判定摇成「安全」。
    """

    def _mixed(host: str, *_a: Any, **_kw: Any) -> list[tuple[Any, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ]

    monkeypatch.setattr(fetcher.socket, "getaddrinfo", _mixed)
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=BODY_ONLY))

    with pytest.raises(FetchError, match="内网"):
        await fetch_for_ingest("http://evil.example.com/x", SourceType.HTML)


async def test_unresolvable_host_reports_dns_not_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解析失败不能报成「不允许抓取内网地址」。

    用户贴错一个域名是很常见的失误，报成安全问题他既看不懂也改不动——
    正确的提示要指向「链接可能写错了」。
    """
    _resolve_to(monkeypatch, PUBLIC)  # 不含下面的域名 → 解析失败
    _install_transport(monkeypatch, lambda _r: httpx.Response(200, content=BODY_ONLY))

    with pytest.raises(FetchError, match="域名解析失败"):
        await fetch_for_ingest("http://typo.exmaple.com/x", SourceType.HTML)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://x/y", "gopher://x", "javascript:alert(1)"]
)
def test_non_http_scheme_is_rejected(url: str) -> None:
    """协议白名单。file:// 能读本地文件，gopher:// 在部分客户端能走私请求。"""
    with pytest.raises(FetchError, match="http"):
        fetcher._public_host(url)


def test_url_without_host_is_rejected() -> None:
    with pytest.raises(FetchError, match="主机名"):
        fetcher._public_host("http:///no-host")
