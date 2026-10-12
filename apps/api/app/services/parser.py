"""资料解析层：把原始文件 / 网页变成「带页码的纯文本块」。

输出的 ``ParsedBlock.page`` 是 RAG 引用溯源的根——模型在报告里写
「[1, p.3]」时，靠它回到原文的第 3 页。丢掉页码整套引用就废了，
所以解析层宁可报错也不能静默返回无页码的文本。

各parser 的共同契约：
- 只做「抽文本」，不做切片、不调模型——那是 chunker 和 embedder 的事
- 抽不出任何文字时抛 :class:`ParseError`，不返回空字符串让下游误判成功
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import pymupdf


class ParseError(Exception):
    """解析失败。区别于代码 bug——调用方应转成用户可见的失败状态。"""


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    """一段带来源定位的纯文本。"""

    text: str
    # PDF 的页码（1 起）；网页/纯文本为 None。
    page: int | None = None
    meta: dict[str, object] | None = None


class Parser(Protocol):
    """解析器协议。换格式只加一个实现，摄取流程不动。"""

    def parse(self, payload: bytes, **kwargs: str) -> list[ParsedBlock]:
        """把原始字节解析成文本块。失败抛 :class:`ParseError`。"""
        ...


# ── PDF ────────────────────────────────────────────────────
class PdfParser:
    """PDF 解析器（pymupdf 1.28）。

    按页抽文本而不是整篇一次性抽：引用要精确到页，
    而 pymupdf 的 ``get_text()`` 逐页调用是最直接的映射。
    """

    def parse(self, payload: bytes, **_kwargs: str) -> list[ParsedBlock]:
        """逐页抽文本。

        实测的三个边界（pymupdf 1.28.2）：
        - 损坏文件   → ``FileDataError``
        - 加密文件   → ``ValueError: document closed or encrypted``，
                       ``needs_pass`` 为真时要在读之前就拒掉
        - 空白页     → ``get_text()`` 返回空串，跳过即可（不是错误）
        """
        try:
            doc = pymupdf.open(stream=payload, filetype="pdf")  # type: ignore[no-untyped-call]
        except pymupdf.FileDataError as exc:
            raise ParseError("文件不是有效的 PDF，可能已损坏") from exc

        with doc:
            if doc.needs_pass:
                raise ParseError("PDF 已加密，无法读取内容")

            blocks: list[ParsedBlock] = []
            # Document 声明成 Iterable[Never]（它没写 __iter__ 的签名），
            # 运行时却真能迭代出 Page。用 range + __getitem__ 绕开可迭代协议，
            # 类型也就自洽了——行为已由 tests/test_parser.py 实测覆盖。
            for index in range(doc.page_count):
                text: str = doc[index].get_text().strip()  # type: ignore[no-untyped-call]
                if not text:
                    continue
                blocks.append(ParsedBlock(text=text, page=index + 1))

        if not blocks:
            raise ParseError("PDF 里没有可提取的文字，可能是扫描件（需 OCR）")
        return blocks


# ── HTML ───────────────────────────────────────────────────
class HtmlParser:
    """HTML 解析器。

    不引 bs4/lxml——用正则剥标签足够处理我们存下来的网页快照。
    引第三方 parser 是 YAGNI：真要精确还原 DOM 时再换不迟。
    """

    # 脚本与样式的内容不该进正文，它们会污染 embedding。
    _DROP = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
    _TAG = re.compile(r"<[^>]+>")
    _WHITESPACE = re.compile(r"\n{3,}")

    def parse(self, payload: bytes, **_kwargs: str) -> list[ParsedBlock]:
        """剥标签后返回单块文本（网页不分页）。"""
        html = payload.decode("utf-8", errors="replace")
        title = self._extract_title(html)

        text = self._DROP.sub(" ", html)
        text = self._TAG.sub("\n", text)
        text = self._unescape(text)
        text = self._WHITESPACE.sub("\n\n", text).strip()

        if not text:
            raise ParseError("网页里没有可提取的正文")

        meta: dict[str, object] | None = {"title": title} if title else None
        return [ParsedBlock(text=text, page=None, meta=meta)]

    @staticmethod
    def _extract_title(html: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _unescape(text: str) -> str:
        from html import unescape

        return unescape(text)


class TextParser:
    """纯文本 / Markdown。与 PDF 一样按 ``\\f``（换页符）分页。"""

    def parse(self, payload: bytes, **_kwargs: str) -> list[ParsedBlock]:
        text = payload.decode("utf-8", errors="replace").strip()
        if not text:
            raise ParseError("文件内容为空")

        blocks: list[ParsedBlock] = []
        # split 保留分隔符，才能算出每页的真实页码
        pages = text.split("\f")
        for index, page in enumerate(pages):
            cleaned = page.strip()
            if cleaned:
                blocks.append(ParsedBlock(text=cleaned, page=index + 1))
        return blocks
