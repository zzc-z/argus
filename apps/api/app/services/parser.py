"""资料解析层：把原始文件 / 网页变成「带页码的纯文本块」。

输出的 ``ParsedBlock.page`` 是 RAG 引用溯源的根——模型在报告里写
「[1, p.3]」时，靠它回到原文的第 3 页。丢掉页码整套引用就废了，
所以解析层宁可报错也不能静默返回无页码的文本。

各parser 的共同契约：
- 只做「抽文本」，不做切片、不调模型——那是 chunker 和 embedder 的事
- 抽不出任何文字时抛 :class:`ParseError`，不返回空字符串让下游误判成功
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Protocol

import docx
import pymupdf
from docx.document import Document as DocumentObject
from docx.table import Table
from docx.text.paragraph import Paragraph


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


# ── DOCX ───────────────────────────────────────────────────
# 「这个文件不是一份能读的 Word」在 python-docx + lxml 里散成好几类异常，
# 收成一个元组，避免 try 里越列越长、且漏掉哪一类都表现为 500。
#
# SyntaxError 在列表里是必要的：lxml 的 XMLSyntaxError 继承它而不是
# ValueError，只 catch (BadZipFile, ValueError) 会漏掉「ZIP 合法但
# document.xml 不是合法 XML」这条最常见的损坏路径。
_MALFORMED: tuple[type[BaseException], ...] = (
    zipfile.BadZipFile,
    KeyError,
    ValueError,
    OSError,
    SyntaxError,  # lxml.etree.XMLSyntaxError 的基类——它继承 SyntaxError
    #      而不是 ValueError，只 catch (BadZipFile, ValueError) 会漏掉它
)

# 正文里需要**递归进去**的元素（Clark 记法的短名）。
#
# 它们自身不是段落也不是表格，但内部装着正文：跳过它们就等于静默丢内容。
# `sdt` 是 Word 的自动目录 / 内容控件 / 内置封面页，`txbxContent` 是文本框。
# 没见过 `sdt` 的场景：Word 里点「引用 → 目录」自动生成的目录，
# 以及 Word 内置封面模板的标题与作者行——它们整体包在一个 `w:sdt` 里。
_CONTAINER_TAGS = frozenset({"sdt", "sdtContent", "txbxContent", "tc", "body"})

# 解压后的文档 XML 上限。**必须在解析前查**——zipfile 自己不看这个，
# 而 MAX_UPLOAD_BYTES（storage.py，50MB）只管上传的压缩包体积。
#
# 实测放大比随文档大小上升：8000 段的纯文本 docx，上传 58KB 却展开成
# 0.7MB 的 document.xml（13x）。python-docx 会把整个 XML 建成 lxml DOM
# 常驻内存，再乘上对象开销。不设上限的话，一个 50MB 的上传能展开到 GB 级，
# 单个已登录用户就能把 API 进程打到 OOM——那不是这一个请求失败，是整个
# 服务不可用。
#
# 取 64MB：一份正常的长报告 docx（几百页）展开后也在这个量级，
# 而它已经远大于任何合理文档的实际需要。
_MAX_XML_BYTES = 64 * 1024 * 1024


def _guard_xml_size(payload: bytes) -> None:
    """解压前检查 document.xml 的声明体积，超限就拒。

    只读 ZIP 目录里的 ``file_size``（中央目录里就有），**不解压**——所以
    拒绝的成本与文件内容无关。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info = archive.getinfo("word/document.xml")
    except _MALFORMED as exc:
        # 结构不对的交给 parse() 去报错并给用户一句人话，这里不重复处理。
        raise ParseError("文件不是有效的 Word 文档（.docx），可能已损坏") from exc
    if info.file_size > _MAX_XML_BYTES:
        raise ParseError(
            f"文档内容过大（解压后约 {info.file_size // 1024 // 1024}MB），"
            f"上限 {_MAX_XML_BYTES // 1024 // 1024}MB。请删减后重试"
        )


class DocxParser:
    """Word (.docx) 解析器（python-docx 1.2.0）。

    ## 为什么单独一个 SourceType 而不是并进 TEXT

    .docx 是 ZIP 包（里面装 XML），把它映射到 ``SourceType.TEXT`` 会让
    ``TextParser`` 拿 utf-8 去解二进制，产出满屏乱码且**不报错**——比直接
    失败更糟。所以它必须有自己的一路分发。

    ## 页码一律是 None（这是产品决策，不是偷懒）

    docx 是流式文档格式，「第几页」是 Word 排版时的副产物，不存在于文件里
    （真正的 OOXML 里页面由渲染器分，文件只存内容流）。所以
    ``ParsedBlock.page`` 恒为 None。

    代价要说清楚：报告里引用一份 Word 文档只能写成 ``[1]``，而不是
    ``[1, p.3]``。用户点引用能跳到那份文档，但跳不到具体某一页。需要精确
    页码的引用溯源请用 PDF 导出。

    ## 不抽页眉与页脚（有意为之，实测后决定的）

    实测确认 ``document.paragraphs`` **完全看不到**页眉页脚——它们在
    独立的 part 里，只有 ``document.sections[i].header/footer`` 能读到。
    所以现在的实现是有意跳过，不是漏了。

    不抽的理由不是「省事」，是抽了会让检索更差：

    - 页眉是**所有页共用**的一个 part。「第 X 页 共 Y 页」这类文字会按
      页数重复 N 份进向量库，N 越大正文的相对权重被稀释得越厉害；
    - 它给不出真实页码——那只是页眉上印的字，不代表内容落在第几页；
    - 政府与企业模板的页眉常是「XX 公司内部资料」「机密」这类噪声，
      直接进 embedding 会污染检索结果。

    代价：正文之外只写在页眉里的信息会丢（例如页眉里的文档标题）。
    对「问答检索 + 引用溯源」这个用途可以接受——页眉本就不是正文。
    哪天真需要了，正确做法是存进元数据供展示，而不是混进检索向量。

    ## 不支持 .doc（二进制老格式）

    ``python-docx`` 只读 OOXML；``.doc`` 是完全不同的二进制格式（Compound
    File Binary），没有纯 Python 库可靠解析它。这里**不接受** ``.doc``——
    上传会直接 415 并告诉用户导出成 .docx 或 PDF。这比装个半可靠的解析器
    静默丢内容诚实。
    """

    def parse(self, payload: bytes, **_kwargs: str) -> list[ParsedBlock]:
        """按文档顺序抽段落与表格。

        段落和表格**交替**出现在正文里（「先说一段、再插一张表」是正常
        写法），所以要遍历 ``document.element.body`` 的子元素而不是分别取
        ``document.paragraphs`` 和 ``document.tables``——后者会把表格全甩到
        段落后面，丢失原始顺序，embedding 的上下文就串了。

        ``_MALFORMED`` 覆盖了「ZIP 结构对但里面不是合法 Word」的全部分支，
        **包括遍历正文的阶段**——``Paragraph`` / ``Table`` 在构造时也要
        解析 XML，畸形内容在那时才炸，不是在 ``Document()`` 那一步。
        """
        _guard_xml_size(payload)
        try:
            document = docx.Document(io.BytesIO(payload))
            return self._extract(document)
        except ParseError:
            raise
        except _MALFORMED as exc:
            # python-docx 的失败模式分散在好几层：不是 zip 抛
            # BadZipFile；zip 里没有 word/document.xml 抛 KeyError；
            # document.xml 不是合法 XML 抛 lxml 的 XMLSyntaxError——它继承
            # SyntaxError 而**不是** ValueError，只 catch ValueError 会漏掉
            # 它，用户就看到 500 而不是一句「这份文件读不了」。
            raise ParseError("文件不是有效的 Word 文档（.docx），可能已损坏") from exc

    @staticmethod
    def _extract(document: DocumentObject) -> list[ParsedBlock]:
        """遍历正文产出文本块。异常由 :meth:`parse` 统一收口。"""
        blocks: list[ParsedBlock] = []
        DocxParser._walk(document.element.body, document, blocks)
        if not blocks:
            raise ParseError("Word 文档里没有可提取的文字（可能只有图片）")
        return blocks

    @classmethod
    def _walk(cls, container: object, document: DocumentObject, blocks: list[ParsedBlock]) -> None:
        """按文档顺序遍历 ``container`` 的子元素，递归进容器类元素。

        **为什么要递归而不是只认 p / tbl**：Word 的正文里混着三类容器，
        只认前两类会静默吞掉内容——文档照样标记 ``indexed``，用户却发现
        引用的那段话检索不到：

        - ``w:tbl``：表格**单元格内部**还能再嵌表格（合同的附表、财报的
          分项明细常见）。``_Cell.text`` 只拼段落、不含嵌套表，所以不递归
          进去的话，嵌套表所在的那一行整行变空，被 ``if line:`` 跳过，
          **整张外层表格连同嵌套内容一起消失**。
        - ``w:sdt``（结构化文档标签）：Word 的**自动目录**、内容控件、
          内置封面页里的标题/副标题/作者/日期，全都包在这个元素里。它既不
          是 p 也不是 tbl，当年的 if/elif 会把它整个跳过。
        - ``w:txbxContent``：文本框内容。

        """
        for element in container:  # type: ignore[attr-defined]
            tag = element.tag.rsplit("}", 1)[-1]

            if tag == "p":
                text = Paragraph(element, document).text.strip()
                if text:
                    blocks.append(ParsedBlock(text=text, page=None))
            elif tag == "tbl":
                cls._table_blocks(Table(element, document), document, blocks)
            elif tag in _CONTAINER_TAGS:
                cls._walk(element, document, blocks)

    @classmethod
    def _walk_extras(
        cls, container: object, document: DocumentObject, blocks: list[ParsedBlock]
    ) -> None:
        """只抽「段落类」元素抽不到的东西：嵌套表格与 w:sdt 容器。

        与 :meth:`_walk` 的区别就是**跳过裸段落**——调用方（_table_blocks）
        已经用 ``cell.text`` 把单元格里的普通段落抽过一遍了，再抽一次就
        重复。裸段落之外的一切（嵌套表、内容控件、文本框）``cell.text``
        都看不到，仍然要递归进去。
        """
        for element in container:  # type: ignore[attr-defined]
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "p":
                continue
            if tag == "tbl":
                cls._table_blocks(Table(element, document), document, blocks)
            elif tag in _CONTAINER_TAGS:
                cls._walk(element, document, blocks)

    @classmethod
    def _table_blocks(
        cls, table: Table, document: DocumentObject, blocks: list[ParsedBlock]
    ) -> None:
        """一张表 → 每行一个块，追加到 ``blocks``。

        行而不是单元格：表格的语义单位是行（表头 + 数据行），拆成单元格
        会让「列名」和「它对应的值」分到两个远隔的块里，检索时召不回两者
        构成的那条记录。
        """
        for row in table.rows:
            # 合并单元格的判据是 **tc 元素身份**，不是文本相等。
            #
            # 横向合并时 row.cells 会把同一个 `_tc` 对象重复返回——那要去重，
            # 否则一行 2 列的合并格会输出「值 | 值」。但拿「相邻文本相同」
            # 当代理会吃掉合法数据：年份对照表 `2024 | 2024`、状态表
            # `通过 | 通过`，这些表里两列相同是常态，丢了就召不回记录。
            #
            # 纵向合并则相反：每行各有自己的 tc（内容一样但是两个真实
            # 单元格），按 tc 身份判断就**不会**误去重——这是之前版本
            # 把纵向合并内容重复输出一份的原因。
            seen: set[int] = set()
            cells: list[str] = []
            for cell in row.cells:
                key = id(cell._tc)
                if key in seen:
                    continue
                seen.add(key)
                # 只递归抽 `cell.text` 抽不到的部分——嵌套表与 w:sdt 容器。
                # 全量 `_walk` 会把单元格的普通段落也抽一遍，而紧接着的
                # `cell.text` 又抽一次，于是每格文字出现两遍（实测普通表格
                # 从 3 块涨到 8 块），重复内容把 embedding 权重白白抬高。
                cls._walk_extras(cell._tc, document, blocks)
                text = cell.text.strip()
                if text:
                    cells.append(text)
            line = " | ".join(cells)
            if line:
                blocks.append(ParsedBlock(text=line, page=None))
