"""URL 归一化：判定「两个 URL 是不是同一篇文章」。

## 为什么单独成模块

``tools.py`` 与 ``web_sources.py`` 都要用它，而 ``tools.py`` 本身要 import
``web_sources.py``（联网搜索结果落成可引用来源）。共用逻辑放在
``tools.py`` 里会形成循环 import。

所以放到一个与业务无关的模块里，两边都从这儿取。

## 判定的依据

同一个网页的分享链接往往带不同的跟踪参数（utm_*、gclid、Yahoo 的
``fr=``…）。把它们当成不同来源会出问题：同一篇文章占两个角标号，
而模型会把它们当成「两个独立来源互相印证」——那是错的。

实测（2026-11-08）：Yahoo Finance 同一篇报道带
``?fr=sycsrp_catchall`` 与不带，被算成两条独立证据。
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 跟踪参数：不影响页面内容，去掉后才是「同一篇文章」。
#
# utm_* 与 gclid/fbclid 是标准做法；``fr``（Yahoo / 新浪的分享来源
# 标记）与 ``from``/``source``/``ref``/``referrer`` 是实测遇到的同类
# 参数（2026-11-08）。
TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "fr",
        "from",
        "source",
        "ref",
        "referrer",
    }
)


def canonicalize_url(url: str) -> str:
    """把 URL 归一化成「同一篇文章」的判定依据。

    去掉 utm/fr 等跟踪参数、去掉 fragment（#anchor 不影响页面内容）、
    统一 host 小写、去掉 www. 前缀与路径尾斜杠，并按字母序重排剩余 query
    ——参数顺序不同但内容相同的 URL 也应该判为同一条。
    """
    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    kept = sorted((k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_PARAMS)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(kept), ""))
