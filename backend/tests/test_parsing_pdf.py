import io

import pymupdf
import pytest
from PIL import Image

from app.parsing import ParseError, parse_file
from tests.helpers import make_png

BODY = "This paragraph is ordinary body text used to set the median font size of the page."


def new_pdf(n_pages=1):
    doc = pymupdf.open()
    for _ in range(n_pages):
        doc.new_page()  # A4-ish 595 x 842
    return doc


def text(page, y, s, size=11, font="helv"):
    page.insert_text((72, y), s, fontsize=size, fontname=font)


def save(doc, tmp_path, name="a.pdf", **kw):
    p = tmp_path / name
    doc.save(p, **kw)
    return p


def parse(path, tmp_path):
    return parse_file(path, doc_type="report", figures_dir=tmp_path / "figures")


def test_font_size_headings_become_sections(tmp_path):
    doc = new_pdf()
    pg = doc[0]
    text(pg, 80, "Introduction", size=18)
    text(pg, 110, BODY)
    text(pg, 140, "Background", size=14)
    text(pg, 170, BODY)
    text(pg, 200, "Method", size=18)
    text(pg, 230, BODY)
    parsed = parse(save(doc, tmp_path), tmp_path)
    assert [(s.heading, s.level) for s in parsed.sections] == [
        ("Introduction", 1),
        ("Background", 2),
        ("Method", 1),
    ]
    assert parsed.paragraph("S1.P1").page == 1


def test_chinese_pdf_text(tmp_path):
    doc = new_pdf()
    text(doc[0], 80, "一、项目背景", size=16, font="china-s")
    text(doc[0], 110, "设备非计划停机已成为影响生产效率的主要因素。", font="china-s")
    parsed = parse(save(doc, tmp_path), tmp_path)
    assert parsed.sections[0].heading == "一、项目背景"
    assert parsed.language == "zh"


def test_wrapped_lines_and_hyphenation_joined(tmp_path):
    doc = new_pdf()
    text(doc[0], 80, "Heading", size=18)
    doc[0].insert_text((72, 110), "the infor-\nmation system\nworks well", fontsize=11)
    parsed = parse(save(doc, tmp_path), tmp_path)
    assert parsed.paragraph("S1.P1").text == "the information system works well"


def test_repeated_header_footer_and_page_numbers_removed(tmp_path):
    doc = new_pdf(3)
    for i, pg in enumerate(doc, 1):
        text(pg, 30, "XX University Practical Report", size=9)
        text(pg, 120, f"Section {i}", size=18)
        text(pg, 150, BODY)
        text(pg, 820, f"- {i} -", size=9)
    parsed = parse(save(doc, tmp_path), tmp_path)
    all_text = " ".join(p.text for s in parsed.sections for p in s.paragraphs)
    assert "University" not in all_text and "- 2 -" not in all_text
    assert [s.heading for s in parsed.sections] == ["Section 1", "Section 2", "Section 3"]


def test_encrypted_pdf_rejected(tmp_path):
    doc = new_pdf()
    text(doc[0], 80, BODY)
    path = save(doc, tmp_path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    with pytest.raises(ParseError) as e:
        parse(path, tmp_path)
    assert e.value.code == "ENCRYPTED_PDF"


def test_corrupt_pdf_rejected(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"%PDF-1.7 garbage garbage")
    with pytest.raises(ParseError) as e:
        parse(p, tmp_path)
    assert e.value.code == "CORRUPT_FILE"


def test_blank_pdf_is_empty(tmp_path):
    with pytest.raises(ParseError) as e:
        parse(save(new_pdf(), tmp_path), tmp_path)
    assert e.value.code == "EMPTY_DOCUMENT"


def test_scanned_pdf_rejected(tmp_path):
    doc = new_pdf(2)
    for pg in doc:
        pg.insert_image(pg.rect, stream=make_png(600, 840, color=(240, 240, 240)))
    with pytest.raises(ParseError) as e:
        parse(save(doc, tmp_path), tmp_path)
    assert e.value.code == "SCANNED_PDF"


def test_text_with_photo_is_not_scanned_and_figure_in_order(tmp_path):
    doc = new_pdf()
    pg = doc[0]
    text(pg, 80, "Results", size=18)
    text(pg, 110, BODY)
    pg.insert_image(pymupdf.Rect(72, 130, 372, 310), stream=make_png(300, 180))
    text(pg, 330, "Figure 1 Downtime per quarter", size=10)
    text(pg, 360, BODY)
    parsed = parse(save(doc, tmp_path), tmp_path)
    paras = parsed.sections[0].paragraphs
    assert [p.kind for p in paras] == ["text", "figure", "text"]
    fig = paras[1].figure
    assert fig.caption == "Figure 1 Downtime per quarter"
    assert paras[1].page == 1
    assert (tmp_path / "figures" / fig.file).exists()


def test_cmyk_image_converted(tmp_path):
    buf = io.BytesIO()
    Image.new("CMYK", (200, 150), (0, 120, 200, 10)).save(buf, "JPEG")
    doc = new_pdf()
    text(doc[0], 80, BODY)
    doc[0].insert_image(pymupdf.Rect(72, 100, 272, 250), stream=buf.getvalue())
    fig = parse(save(doc, tmp_path), tmp_path).figures()[0].figure
    assert Image.open(tmp_path / "figures" / fig.file).mode == "RGB"


def draw_bar_chart(pg, x=72, y=120):
    pg.draw_line((x, y), (x, y + 200))
    pg.draw_line((x, y + 200), (x + 300, y + 200))
    for i in range(6):
        h = 30 + i * 25
        pg.draw_rect(
            pymupdf.Rect(x + 10 + i * 48, y + 200 - h, x + 40 + i * 48, y + 200),
            fill=(0.2, 0.4, 0.8),
        )


def test_vector_chart_rendered_as_figure_with_its_labels(tmp_path):
    doc = new_pdf()
    pg = doc[0]
    text(pg, 80, "Results", size=18)
    text(pg, 100, BODY)
    draw_bar_chart(pg)
    pg.insert_text((80, 140), "hours", fontsize=8)  # axis label inside the chart area
    text(pg, 350, "Figure 2 Bars", size=10)
    parsed = parse(save(doc, tmp_path), tmp_path)
    figs = parsed.figures()
    assert len(figs) == 1 and figs[0].figure.source == "pdf_vector"
    assert figs[0].figure.caption == "Figure 2 Bars"
    assert "hours" in figs[0].figure.chart_data
    assert all("hours" not in p.text for p in parsed.sections[0].paragraphs if p.kind != "figure")


def test_table_grid_is_not_a_chart(tmp_path):
    doc = new_pdf()
    pg = doc[0]
    text(pg, 80, BODY)
    for i in range(6):  # 5x5 grid of plain lines
        pg.draw_line((72, 120 + i * 30), (372, 120 + i * 30))
        pg.draw_line((72 + i * 60, 120), (72 + i * 60, 270))
    assert parse(save(doc, tmp_path), tmp_path).figure_count == 0


def test_logo_on_every_page_skipped(tmp_path):
    doc = new_pdf(3)
    logo = make_png(120, 80, color=(200, 0, 0))
    for i, pg in enumerate(doc, 1):
        pg.insert_image(pymupdf.Rect(480, 20, 560, 60), stream=logo)
        text(pg, 120, f"Section {i}", size=18)
        text(pg, 150, BODY)
    parsed = parse(save(doc, tmp_path), tmp_path)
    assert parsed.figure_count == 0
    assert any(w.startswith("FIGURES_SKIPPED") for w in parsed.warnings)
