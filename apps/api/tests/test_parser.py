"""parser 的测试。

用真 PDF（pymupdf 现场生成）和真 docx（python-docx 现场生成），不用固定字节流——
字节流在库升级后会静默失效，而现场生成能保证测试的仍是当前库的真实行为。
"""

import io
import struct
import zipfile
import zlib
from collections.abc import Callable

import docx
import pymupdf
import pytest

from app.services.parser import (
    DocxParser,
    HtmlParser,
    ParsedBlock,
    ParseError,
    PdfParser,
    TextParser,
)


def _make_pdf(pages: list[str]) -> bytes:
    """造一个多页 PDF。文本用 ASCII——内置字体没有中文字形。"""
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 100), body, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _make_docx(build: Callable[[docx.Document], None]) -> bytes:
    """造一个 docx 字节流。内容交给 build 现场拼。"""
    document = docx.Document()
    build(document)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _flat_text(blocks: list[ParsedBlock]) -> str:
    """把所有块拼成一条文本流，用来断言「块的先后顺序」。

    表格的切块粒度规格没定（一块 / 一行 / 一格都可能），所以顺序一律用
    「拼起来之后子串的位置」来断言——三种粒度下都成立。
    """
    return "".join(block.text for block in blocks)


def _pos(text: str, needle: str) -> int:
    """needle 在 text 里的位置。没抽到就给出可读的失败信息，
    而不是让 ``.index`` 抛一个看不懂的 ValueError。"""
    assert needle in text, f"输出里没有 {needle!r}：{text!r}"
    return text.index(needle)


def _one_pixel_png() -> bytes:
    """现场造 1x1 PNG。仓库里不放二进制 fixture（需求如此）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8bit, truecolor
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )


def _make_zip_with_text() -> bytes:
    """造一个合法 zip 但不是 docx——真实世界里的 .odt / .epub / .jar 就是这种。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("hello.txt", "not a docx")
    return buf.getvalue()


# ── PDF ────────────────────────────────────────────────────
def test_pdf_extracts_each_page() -> None:
    pdf = _make_pdf(["Page one about Blackwell.", "Page two about Hopper."])

    blocks = PdfParser().parse(pdf)

    assert len(blocks) == 2
    assert "Blackwell" in blocks[0].text
    assert blocks[0].page == 1
    assert "Hopper" in blocks[1].text
    assert blocks[1].page == 2


def test_pdf_pages_are_one_based() -> None:
    """页码从 1 起——跟人类说的「第 3 页」对齐，存 0 起的会全错位一格。"""
    blocks = PdfParser().parse(_make_pdf(["A", "B", "C"]))

    assert [b.page for b in blocks] == [1, 2, 3]


def test_pdf_skips_blank_pages() -> None:
    """空白页跳过，但**页码不重排**——引用必须指向 PDF 的真实页。"""
    pdf = _make_pdf(["Content one."])
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    doc.new_page()  # 空白页
    doc.new_page()
    page_with_text = doc.new_page()
    page_with_text.insert_text((72, 100), "Page four.", fontsize=12)
    pdf2 = doc.tobytes()
    doc.close()

    blocks = PdfParser().parse(pdf2)

    assert len(blocks) == 2
    assert [b.page for b in blocks] == [1, 4]


def test_pdf_rejects_corrupted_bytes() -> None:
    with pytest.raises(ParseError, match="损坏"):
        PdfParser().parse(b"this is definitely not a pdf")


def test_pdf_rejects_encrypted() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "secret", fontsize=12)
    encrypted = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u"
    )
    doc.close()

    with pytest.raises(ParseError, match="加密"):
        PdfParser().parse(encrypted)


def test_pdf_rejects_textless_document() -> None:
    """扫描件抽不出字。要说清楚是「要 OCR」，不是含糊的「解析失败」。"""
    doc = pymupdf.open()
    doc.new_page()
    empty = doc.tobytes()
    doc.close()

    with pytest.raises(ParseError, match="OCR"):
        PdfParser().parse(empty)


# ── HTML ───────────────────────────────────────────────────
def test_html_extracts_text_and_drops_tags() -> None:
    html = b"<html><body><p>First paragraph.</p><p>Second one.</p></body></html>"

    blocks = HtmlParser().parse(html)

    assert len(blocks) == 1
    assert "First paragraph." in blocks[0].text
    assert "<p>" not in blocks[0].text


def test_html_drops_script_and_style() -> None:
    """脚本内容会污染 embedding——「var x = 1」不是正文。"""
    html = b"""<html><head>
        <title>My Page</title>
        <style>.a{color:red}</style>
        <script>var tracking = 1;</script>
        </head><body><p>Real content.</p></body></html>"""

    block = HtmlParser().parse(html)[0]

    assert "tracking" not in block.text
    assert "color:red" not in block.text
    assert "Real content." in block.text


def test_html_unescapes_entities() -> None:
    block = HtmlParser().parse(b"<p>AT&amp;T &lt;tag&gt; &#65;</p>")[0]

    assert "AT&T" in block.text
    assert "<tag>" in block.text


def test_html_captures_title_as_meta() -> None:
    block = HtmlParser().parse(b"<title>Quarterly Report</title><p>x</p>")[0]

    assert block.meta == {"title": "Quarterly Report"}
    assert block.page is None


def test_html_without_title_has_empty_meta() -> None:
    block = HtmlParser().parse(b"<p>no title here</p>")[0]

    assert block.meta is None


def test_html_rejects_tag_only_document() -> None:
    """全是标签没正文是失败——返回空串会让摄取静默「成功」但库里是空的。"""
    with pytest.raises(ParseError, match="正文"):
        HtmlParser().parse(b"<html><body><div></div></body></html>")


# ── 纯文本 ─────────────────────────────────────────────────
def test_text_single_page() -> None:
    blocks = TextParser().parse(b"Just some plain text.")

    assert len(blocks) == 1
    assert blocks[0].text == "Just some plain text."
    assert blocks[0].page == 1


def test_text_splits_on_form_feed() -> None:
    """`\\f` 是纯文本/Markdown 的换页约定，页码要跟着走。"""
    blocks = TextParser().parse(b"Page one.\fPage two.\fPage three.")

    assert [b.page for b in blocks] == [1, 2, 3]


def test_text_skips_blank_sections() -> None:
    blocks = TextParser().parse(b"First.\f\f\fSecond.")

    assert len(blocks) == 2
    assert [b.page for b in blocks] == [1, 4]


def test_text_rejects_empty() -> None:
    with pytest.raises(ParseError, match="为空"):
        TextParser().parse(b"   \n  ")


def test_text_handles_invalid_utf8() -> None:
    """坏字节不能抛异常——errors='replace' 保证解析继续。"""
    blocks = TextParser().parse(b"good \xff\xfe bytes")

    assert blocks and "good" in blocks[0].text


# ── DOCX ───────────────────────────────────────────────────
# 规格只要求「文案是给用户看的中文」，没定死措辞——下面几种说法都算达标，
# 但纯英文/空文案不行：异常会直接进 API 响应给用户看。
_DAMAGED_HINT = "损坏|不是有效|无法解析|无法读取|不支持|格式错误"


def test_docx_extracts_paragraphs_in_order() -> None:
    payload = _make_docx(
        lambda d: [d.add_paragraph(t) for t in ("第一段。", "第二段。", "第三段。")]
    )

    blocks = DocxParser().parse(payload)

    assert [b.text for b in blocks] == ["第一段。", "第二段。", "第三段。"]


def test_docx_block_pages_are_none() -> None:
    """docx 没有页概念。引用退化成 [1]，但**不能瞎编一个页码 1**——
    报告里会印出「[1, p.1]」，指向一个不存在的位置。"""
    payload = _make_docx(lambda d: [d.add_paragraph(t) for t in ("甲。", "乙。")])

    blocks = DocxParser().parse(payload)

    assert all(b.page is None for b in blocks)


def test_docx_extracts_heading_only_document() -> None:
    payload = _make_docx(lambda d: d.add_heading("第一章 总则", level=1))

    blocks = DocxParser().parse(payload)

    assert [b.text for b in blocks] == ["第一章 总则"]


def test_docx_keeps_headings_in_document_order() -> None:
    def build(d: docx.Document) -> None:
        d.add_heading("标题一", level=1)
        d.add_paragraph("正文甲。")
        d.add_heading("标题二", level=2)
        d.add_paragraph("正文乙。")

    flat = _flat_text(DocxParser().parse(_make_docx(build)))

    positions = [_pos(flat, x) for x in ("标题一", "正文甲。", "标题二", "正文乙。")]
    assert positions == sorted(positions)


def test_docx_skips_empty_paragraph() -> None:
    payload = _make_docx(lambda d: [d.add_paragraph(t) for t in ("正文一。", "", "正文二。")])

    assert len(DocxParser().parse(payload)) == 2


def test_docx_skips_whitespace_only_paragraph() -> None:
    """只有空白字符的段落跟空段落一样——strip 之后是空的，不能变成一个全是空白的块。"""
    payload = _make_docx(lambda d: [d.add_paragraph(t) for t in ("正文一。", "   \t ", "正文二。")])

    assert len(DocxParser().parse(payload)) == 2


def test_docx_emits_no_blank_block() -> None:
    """不变量：任何输入下都不能产出空块或全空白块（引用会指向一个空块）。"""

    def build(d: docx.Document) -> None:
        d.add_paragraph("")
        d.add_paragraph("  ")
        table = d.add_table(rows=1, cols=3)
        table.cell(0, 0).text = "有字"
        table.cell(0, 1).text = ""
        table.cell(0, 2).text = "也有字"
        d.add_paragraph("尾巴。")

    blocks = DocxParser().parse(_make_docx(build))

    assert all(b.text.strip() for b in blocks)


def test_docx_extracts_every_table_cell() -> None:
    def build(d: docx.Document) -> None:
        table = d.add_table(rows=2, cols=3)
        for r in range(2):
            for c in range(3):
                table.cell(r, c).text = f"R{r + 1}C{c + 1}"

    flat = _flat_text(DocxParser().parse(_make_docx(build)))

    missing = [
        f"R{r + 1}C{c + 1}" for r in range(2) for c in range(3) if f"R{r + 1}C{c + 1}" not in flat
    ]
    assert missing == []


def test_docx_reads_table_cells_row_major() -> None:
    """按行优先——逐行逐列读（规格原话「按行、按列」）。
    列优先的实现会把 R1C1 R2C1 R1C2 ... 这样吐出来。"""

    def build(d: docx.Document) -> None:
        table = d.add_table(rows=2, cols=2)
        for r in range(2):
            for c in range(2):
                table.cell(r, c).text = f"R{r + 1}C{c + 1}"

    flat = _flat_text(DocxParser().parse(_make_docx(build)))

    wanted = ["R1C1", "R1C2", "R2C1", "R2C2"]
    positions = [_pos(flat, x) for x in wanted]
    assert positions == sorted(positions)


def test_docx_extracts_every_cell_of_a_three_by_three_table() -> None:
    """3x3 是边界样本——只看第一行的话，漏读后两行照样「看起来对」。"""

    def build(d: docx.Document) -> None:
        table = d.add_table(rows=3, cols=3)
        for r in range(3):
            for c in range(3):
                table.cell(r, c).text = f"格子{r}{c}"

    flat = _flat_text(DocxParser().parse(_make_docx(build)))

    missing = [f"格子{r}{c}" for r in range(3) for c in range(3) if f"格子{r}{c}" not in flat]
    assert missing == []


def test_docx_extracts_table_when_document_has_no_paragraph_text() -> None:
    """纯表格文档：只遍历 document.paragraphs 的实现会返回空——那在摄取里
    等于「成功但库里是空的」。"""

    def build(d: docx.Document) -> None:
        table = d.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "项目"
        table.cell(0, 1).text = "金额"
        other = d.add_table(rows=1, cols=1)
        other.cell(0, 0).text = "只有表格"

    flat = _flat_text(DocxParser().parse(_make_docx(build)))

    assert "只有表格" in flat


def test_docx_reads_cells_around_an_empty_cell() -> None:
    """空格夹在中间时不能漏读/错位后面的格子。断言用「拼起来的位置」而不是
    块的数量——规格允许一格一块或一行一块，两种都要过。"""

    def build(d: docx.Document) -> None:
        table = d.add_table(rows=2, cols=3)
        table.cell(0, 0).text = "上左"
        table.cell(0, 2).text = "上右"
        table.cell(1, 0).text = "下左"
        table.cell(1, 1).text = "下中"
        table.cell(1, 2).text = "下右"

    flat = _flat_text(DocxParser().parse(_make_docx(build)))

    wanted = ["上左", "上右", "下左", "下中", "下右"]
    positions = [_pos(flat, x) for x in wanted]
    assert positions == sorted(positions)


def test_docx_interleaves_paragraphs_and_tables_in_document_order() -> None:
    """「段-表-段」：输出必须保持文档出现顺序。先把所有段落倒完再倒表格
    是一种可选实现，但本测试要求的是文档顺序——取舍在这里显式化。"""

    def build(d: docx.Document) -> None:
        d.add_paragraph("段前。")
        table = d.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "表头一"
        table.cell(0, 1).text = "表头二"
        d.add_paragraph("段后。")

    flat = _flat_text(DocxParser().parse(_make_docx(build)))

    positions = [_pos(flat, x) for x in ("段前。", "表头一", "段后。")]
    assert positions == sorted(positions)


def test_docx_preserves_chinese_text() -> None:
    payload = _make_docx(lambda d: d.add_paragraph("中文段落，含标点与数字 2026。"))

    assert [b.text for b in DocxParser().parse(payload)] == ["中文段落，含标点与数字 2026。"]


def test_docx_returns_parsed_block_instances() -> None:
    payload = _make_docx(lambda d: d.add_paragraph("正文。"))

    blocks = DocxParser().parse(payload)

    assert all(isinstance(b, ParsedBlock) for b in blocks)


def test_docx_accepts_unknown_kwargs() -> None:
    """Parser 协议是 parse(payload, **kwargs: str)——多传关键字参数不该炸。"""
    payload = _make_docx(lambda d: d.add_paragraph("正文。"))

    blocks = DocxParser().parse(payload, source_name="报告.docx")

    assert len(blocks) == 1


# ── DOCX 失败路径 ───────────────────────────────────────────
def test_docx_rejects_empty_document() -> None:
    with pytest.raises(ParseError, match="没有可提取的文字"):
        DocxParser().parse(_make_docx(lambda _d: None))


def test_docx_rejects_image_only_document() -> None:
    """整篇只有图：一个字都抽不出来，必须说清是「没有文字」而不是静默返回空。"""

    def build(d: docx.Document) -> None:
        d.add_picture(io.BytesIO(_one_pixel_png()))

    with pytest.raises(ParseError, match="没有可提取的文字"):
        DocxParser().parse(_make_docx(build))


def test_docx_rejects_plain_text_bytes() -> None:
    with pytest.raises(ParseError, match=_DAMAGED_HINT):
        DocxParser().parse(b"this is definitely not a docx")


def test_docx_rejects_pdf_bytes() -> None:
    with pytest.raises(ParseError, match=_DAMAGED_HINT):
        DocxParser().parse(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n" + b"0" * 200)


def test_docx_rejects_empty_payload() -> None:
    with pytest.raises(ParseError, match=_DAMAGED_HINT):
        DocxParser().parse(b"")


def test_docx_rejects_zip_that_is_not_a_docx() -> None:
    """合法 zip 但没有 [Content_Types].xml（.odt / .epub / .jar 都是这形状）。
    python-docx 1.2.0 这里抛的是 KeyError，不是 BadZipFile——只抓 BadZipFile 会漏。"""
    with pytest.raises(ParseError, match=_DAMAGED_HINT):
        DocxParser().parse(_make_zip_with_text())


def test_docx_rejects_docx_with_corrupted_archive() -> None:
    """真 docx 被改坏尾部（EOCD / 中央目录损坏）。python-docx 1.2.0 抛
    ValueError，不是 BadZipFile——错误处理要覆盖 zipfile 的多种失败。"""
    payload = _make_docx(lambda d: d.add_paragraph("正文。"))

    with pytest.raises(ParseError, match=_DAMAGED_HINT):
        DocxParser().parse(payload[:-5] + b"XXXXX")


# ── 通用契约 ───────────────────────────────────────────────
def test_parsed_block_is_frozen() -> None:
    """冻结 dataclass：解析结果在管线里传递时被误改会很难查。"""
    block = ParsedBlock(text="x", page=1)

    with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError
        block.text = "y"  # type: ignore[misc]


class TestDocxSkipsHeaderAndFooter:
    """页眉页脚**有意不抽**（见 DocxParser docstring 的取舍说明）。

    这几条是防回归的：页眉是所有页共用的一个 part，抽进来会按页数重复
    N 份稀释正文权重。哪天要改这个决策，先改 docstring 再改这里。
    """

    @staticmethod
    def _with_header_footer() -> bytes:
        import docx

        d = docx.Document()
        d.add_paragraph("正文段落。")
        d.sections[0].header.paragraphs[0].text = "第 3 页 共 10 页"
        d.sections[0].footer.paragraphs[0].text = "XX 公司内部资料"
        buf = io.BytesIO()
        d.save(buf)
        return buf.getvalue()

    def test_header_text_is_not_extracted(self) -> None:
        texts = [b.text for b in DocxParser().parse(self._with_header_footer())]

        assert texts == ["正文段落。"]

    def test_footer_text_is_not_extracted(self) -> None:
        texts = [b.text for b in DocxParser().parse(self._with_header_footer())]

        assert not any("内部资料" in t for t in texts)

    def test_header_page_number_does_not_enter_the_index(self) -> None:
        """页眉里的「第 3 页」不该变成可检索内容——它不是正文。"""
        texts = [b.text for b in DocxParser().parse(self._with_header_footer())]

        assert not any("第 3 页" in t for t in texts)
