"""URL 抓取：把一个网址变成能直接喂给摄取管线的字节。

对应 prd/rag-pipeline.md §3.1。这一层只解决两件事——**把字节安全取回来**，
以及**把网页正文挑出来**；切片 / 嵌入 / 落库仍由 services/ingest.py 负责。

## 抓取用 httpx、正文提取用 trafilatura

实测（2026-10-13，见最终报告）：

- 直连 httpx 抓 bbc / yahoo / arxiv / theverge / 新浪 / 网易 全部 200，
  不需要任何 API key。本项目 ``TAVILY_API_KEY`` 是**可选配置**，
  拿它当唯一路径等于让「没配 key」的部署完全不可用。
- 现有 :class:`~app.services.parser.HtmlParser` 是正则剥标签，
  对同一份 Wikipedia HTML 提取 30748 字符、命中 6 处导航/页脚噪音
  （"Jump to content" / "Main menu" / "hide"）；trafilatura 提 15399 字符、
  0 处噪音。中文站差距更大——新浪财经正文中文占比 0.66，HtmlParser 只有 0.05。
  导航文案进 embedding 会直接污染检索，这是要引 trafilatura 的唯一理由。

## 正文提取与 HtmlParser 的分工

trafilatura **不替代** HtmlParser，两者串联：

- trafilatura 答「哪些是正文」（它扔掉导航、页脚、侧栏、广告）
- HtmlParser 答「标签怎么转文本」（项目已测过实体反转义、script/style 剥离）

trafilatura 不能独自顶替 HtmlParser——实测它对 ``<p>AT&amp;T &lt;tag&gt;</p>``
和 ``<html><body><div></div></body></html>`` 都返回 ``None``，
会挂掉 tests/test_parser.py 的既有用例。串联后两边都不动。

## SSRF：每一跳重定向都要复检

实测 httpx 默认 ``follow_redirects=True`` 会一路跟到底，中间不给检查机会：
公网 URL 302 到 ``127.0.0.1`` 后，它老老实实把内网响应读了出来。
所以这里手动跟重定向，每一跳都重新判定目标地址是否公网。

已知残留风险（不假装已解决）：DNS rebinding 窗口——我们解析一次判定、
httpx 再解析一次发请求，两次之间攻击者可换记录。要彻底堵需要把 IP 钉死并
自行处理 TLS SNI 与 Host 头，代价远大于当前收益。私有网段仍由
``ipaddress.is_global`` 挡住，挡住的是绝大多数实际攻击。

另外：正文提取对「正文短到几十字」的页面会连导航一起留下（见 ``_run_extractor``
的注释），这是保召回的取舍，不是没发现。
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Final
from urllib.parse import urlsplit

import httpx
import trafilatura

from app.models import SourceType

logger = logging.getLogger(__name__)

# 实测慢站点（theverge 4.6s）远低于 20s；设更高只是让失败的用户多等。
FETCH_TIMEOUT_SECONDS: Final = 20.0
# 实测真实网页 40KB-1.4MB。10MB 足够宽松，同时挡住「返回无限流」这类站点。
# 上限在流式读取中判定并中断，不收完整个响应（实测 100KB 上限 0.006s 就停了）。
MAX_FETCH_BYTES: Final = 10 * 1024 * 1024
# 正常跳转链 1-2 跳（http→https、补尾斜杠）。5 跳够用，再多基本是循环或跳板。
MAX_REDIRECTS: Final = 5

# 必须伪装成浏览器：不少站点对 httpx 默认 UA 返回 403 或空页。
USER_AGENT: Final = "Mozilla/5.0 (compatible; argus-research/0.1; +https://github.com/argus)"

# 只放行 http/https。file:// / gopher:// / ftp:// 都能读本地或协议层资源。
ALLOWED_SCHEMES: Final = frozenset({"http", "https"})


class FetchError(Exception):
    """抓取失败。message 是给用户看的，不能含内部细节。

    与 :class:`~app.services.parser.ParseError` 同类：都是「用户输入的问题」，
    不是代码 bug。调用方据此把 source 标成 failed 并写 error_message。
    """


async def fetch_for_ingest(url: str, source_type: str) -> bytes:
    """抓 ``url`` 并转成 ``source_type`` 对应解析器吃得下的字节。

    ``source_type`` 决定要不要做正文提取——PDF 是二进制，正文提取器对它
    只会返回 None，原样交给 PdfParser 才对。
    """
    raw = await _download(url)
    return await asyncio.to_thread(_extract, raw, source_type, url)


# ── 下载 ──────────────────────────────────────────────────
async def _download(url: str) -> bytes:
    """跟随重定向把内容取回来，途中逐跳复检目标地址。

    重定向必须手动跟：httpx 的 ``follow_redirects=True`` 会一路跟到底，
    中间每一跳都不给检查的机会——实测它能从公网 URL 跳进 127.0.0.1
    并把内网响应读出来。手动跟才谈得上 SSRF 防护。
    """
    try:
        return await _stream_with_redirects(url)
    except httpx.TimeoutException as exc:
        # 超时是用户最常遇到的情况（站点慢），给一句他能据此行动的话。
        # 必须排在 TransportError 前面：ConnectTimeout 同时是两者，
        # 而「超时」才提示得了用户该等或换个时间再试。
        raise FetchError(f"抓取超时（超过 {int(FETCH_TIMEOUT_SECONDS)} 秒）") from exc
    except httpx.TransportError as exc:
        # 连接被拒 / DNS 抖动 / TLS 失败 / 中途断连。类名对用户没有意义，
        # 但保留下来写进日志，排查时能对上号。
        logger.warning("抓取传输失败：%s", type(exc).__name__)
        raise FetchError("无法连接到该网址，请检查链接是否正确") from exc
    except httpx.InvalidURL as exc:
        # 不是 TransportError（实测 httpx 异常继承里它直接挂在 HTTPError 下），
        # 但确实可达——URL 里带空字节这类畸形输入会走到这里。
        raise FetchError("链接格式不合法") from exc


async def _stream_with_redirects(url: str) -> bytes:
    """发请求并逐跳跟随重定向，拿到最终响应体。"""
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            await _ensure_public(url)
            async with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    url = _redirect_target(resp)
                    continue
                if not resp.is_success:
                    raise FetchError(f"目标站点返回 {resp.status_code}")
                return await _read_capped(resp)
    raise FetchError("重定向次数过多")


def _redirect_target(resp: httpx.Response) -> str:
    """取下一跳的绝对地址。

    用 ``next_request.url`` 而不是自己拼 ``urljoin``：相对路径
    （``Location: /final``）由 httpx 按 RFC 3986 解析，实测 ``/final``、
    ``sub``、``../up``、跨域绝对地址四种形式都解析正确。
    """
    nxt = resp.next_request
    if nxt is None:
        raise FetchError("重定向响应缺少 Location 头")
    return str(nxt.url)


async def _read_capped(resp: httpx.Response) -> bytes:
    """流式读取并在超上限时立刻中断。

    收完再判大小的话，一个 1GB 的响应会先把内存吃穿。实测流式判定
    在 100KB 上限下 0.006s 就断开，不会把整包下完。
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > MAX_FETCH_BYTES:
            raise FetchError(f"网页超过 {MAX_FETCH_BYTES // 1024 // 1024}MB 上限")
        chunks.append(chunk)
    return b"".join(chunks)


# ── SSRF ──────────────────────────────────────────────────
async def _ensure_public(url: str) -> None:
    """URL 指向公网才放行。解析 DNS 是阻塞调用，丢线程池。"""
    host = _public_host(url)
    addresses = await asyncio.to_thread(_resolve, host)
    if not addresses:
        # 解析失败与解析到内网要分开报。混成一句「不允许抓取内网地址」的话，
        # 用户贴了个拼错的域名也会被告知是安全问题——他既看不懂也改不动。
        raise FetchError("域名解析失败，请检查链接是否正确")
    if not all(_is_public_ip(a) for a in addresses):
        raise FetchError("不允许抓取内网地址")


def _public_host(url: str) -> str:
    """取出主机名并校验协议。

    协议白名单挡掉 ``file://`` 这类能读本地文件/资源的 scheme——
    httpx 自己会报 UnsupportedProtocol，但那时已经把 URL 递进传输层了。
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise FetchError("只支持 http/https 链接")
    host = parts.hostname
    if not host:
        raise FetchError("链接缺少主机名")
    return host


def _resolve(host: str) -> set[str]:
    """解析域名，返回它当前指向的全部 IP。解析失败返回空集。

    返回**全部**而不是第一条：DNS 可以同时给出公网 A 记录和内网 A 记录，
    只看一条等于让攻击者靠轮询把判定结果摇成「安全」。
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return set()
    # sockaddr 第 0 位是地址。类型标注成 str | int，但传 AF_INET/AF_INET6
    # 时实测恒为 str（实测 127.0.0.1 / ::1 两种都取到字符串）。
    return {str(info[4][0]) for info in infos}


def _is_public_ip(raw: str) -> bool:
    """判断单个 IP 是否公网可达。

    ``is_global`` 已覆盖私网 / 回环 / 链路本地 / 保留段，实测
    127.0.0.1、10.x、169.254.169.254（云 metadata）、::1、fc00::、
    100.64.x（CGNAT）、198.18.x（基准测试段）都判 False。

    但多播地址 224.0.0.1 实测 ``is_global`` 仍为 True，所以要单独排除。

    代价（实测于本机开发环境）：带 DNS 拦截的环境会把合法域名解析到
    198.18.0.0/15（RFC 2544 基准测试段）。本机实测 en.wikipedia.org 被解析成
    198.18.1.7，于是被判成内网拒掉——同一环境用 httpx 直连却是能通的。
    这里**不**为此放宽默认：198.18/15 本来就不是公网地址，放开等于给 SSRF
    开口子。真在生产遇到，再加一个显式的白名单配置，而不是改默认判定。
    """
    ip = ipaddress.ip_address(raw)
    return ip.is_global and not ip.is_multicast


# ── 正文提取 ──────────────────────────────────────────────
def _extract(raw: bytes, source_type: str, url: str) -> bytes:
    """把响应体转成目标解析器吃得下的形态。

    提不出正文时**退回原始字节**，不报错——「什么是正文」的判断权交给解析器，
    它的报错更贴切（比如空 body 会得到「网页里没有可提取的正文」）。

    已知代价（实测，不是推测）：用户贴一个 JSON API 地址时，trafilatura 返回
    None，退回原始字节后 HtmlParser 剥完标签仍会得到 ``{"json": true}`` 这类
    文本，于是照样入库成一个十几字的垃圾切片。这里不加 content-type 拦截——
    「JSON 不算研究资料」是产品规则不是技术规则，YAGNI。等真有人抱怨了再加。
    """
    if source_type == SourceType.PDF:
        # PDF 是二进制，正文提取器对它只会返回 None。原样交给 PdfParser。
        return raw

    picked = _run_extractor(raw, source_type, url)
    return raw if picked is None else picked.encode("utf-8")


def _run_extractor(raw: bytes, source_type: str, url: str) -> str | None:
    """调 trafilatura 提正文。

    ``include_comments=False``：默认会连 HTML 注释一起提，那些是给开发者看的
    「TODO / 广告位」，进 embedding 纯污染。

    ``favor_precision`` 实测**不能用**，虽然它能把短页面残留的导航文案彻底去掉
    （实测同一合成页：默认残留 "Skip to content"，precision 模式归零）：它在
    163.com 首页上直接返回 0 字符，把整篇文章丢了。研究平台丢正文比多收一段
    导航严重得多，所以走默认的 favor_recall。

    残留的代价是有界的：实测真实页面（Wikipedia / 新浪财经 / 网易）走默认参数
    噪声命中数均为 0，只有正文短到几十个字的合成页才会漏导航——那种页面本来
    也没什么可索引的。
    """
    output_format = "txt" if source_type == SourceType.TEXT else "html"
    try:
        return trafilatura.extract(
            raw,
            url=url,
            output_format=output_format,
            include_comments=False,
        )
    except Exception as exc:
        # trafilatura 对畸形 HTML 偶有未捕获异常。提取失败不该让整次抓取失败，
        # 退回原始字节交给解析器判断即可。
        logger.warning("正文提取失败，退回原始字节：%s", type(exc).__name__)
        return None
