"""parser 的测试。

用真 PDF（pymupdf 现场生成），不用固定字节流——字节流在库升级后会静默失效，
而现场生成能保证测试的仍是当前 pymupdf 的真实行为。
"""

import pymupdf
import pytest

from app.services.parser import HtmlParser, ParsedBlock, ParseError, PdfParser, TextParser


def _make_pdf(pages: list[str]) -> bytes:
    """造一个多页 PDF。文本用 ASCII——内置字体没有中文字形。"""
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 100), body, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


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


# ── 通用契约 ───────────────────────────────────────────────
def test_parsed_block_is_frozen() -> None:
    """冻结 dataclass：解析结果在管线里传递时被误改会很难查。"""
    block = ParsedBlock(text="x", page=1)

    with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError
        block.text = "y"  # type: ignore[misc]
