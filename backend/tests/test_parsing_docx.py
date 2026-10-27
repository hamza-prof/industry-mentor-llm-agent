import pytest

from app.parsing import ParseError, parse_file
from tests.helpers import add_chart, add_picture, add_raw_image, make_png, new_docx


def save(doc, tmp_path, name="a.docx"):
    p = tmp_path / name
    doc.save(p)
    return p


def parse(path, tmp_path, **kw):
    return parse_file(path, doc_type="report", figures_dir=tmp_path / "figures", **kw)


# ---- text structure ---------------------------------------------------------


def test_heading_styles_become_sections(tmp_path):
    d = new_docx()
    d.add_heading("Intro", level=1)
    d.add_paragraph("Body one.")
    d.add_heading("Detail", level=2)
    d.add_paragraph("Body two.")
    doc = parse(save(d, tmp_path), tmp_path)
    assert [(s.heading, s.level) for s in doc.sections] == [("Intro", 1), ("Detail", 2)]
    assert doc.paragraph("S2.P1").text == "Body two."


def test_title_style_sets_document_title(tmp_path):
    d = new_docx()
    d.add_heading("我的实践报告", level=0)  # level 0 = Title style
    d.add_heading("1 绪论", level=1)
    d.add_paragraph("内容")
    doc = parse(save(d, tmp_path), tmp_path)
    assert doc.title == "我的实践报告"
    assert [s.heading for s in doc.sections] == ["1 绪论"]


def test_numbered_headings_without_styles(tmp_path):
    d = new_docx()
    for t in ["一、项目背景", "背景内容。", "二、项目目标", "目标内容。"]:
        d.add_paragraph(t)
    doc = parse(save(d, tmp_path), tmp_path)
    assert [s.heading for s in doc.sections] == ["一、项目背景", "二、项目目标"]


def test_table_kept_in_reading_order(tmp_path):
    d = new_docx()
    d.add_heading("Data", level=1)
    d.add_paragraph("before")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "指标", "数值"
    t.cell(1, 0).text, t.cell(1, 1).text = "停机", "12h"
    d.add_paragraph("after")
    paras = parse(save(d, tmp_path), tmp_path).sections[0].paragraphs
    assert [p.kind for p in paras] == ["text", "table", "text"]
    assert paras[1].text == "指标 | 数值\n停机 | 12h"


def test_list_paragraphs_and_empty_paragraphs(tmp_path):
    d = new_docx()
    d.add_heading("Goals", level=1)
    d.add_paragraph("first", style="List Bullet")
    d.add_paragraph("")
    d.add_paragraph("second", style="List Number")
    paras = parse(save(d, tmp_path), tmp_path).sections[0].paragraphs
    assert [(p.kind, p.text) for p in paras] == [("list", "first"), ("list", "second")]


def test_corrupt_docx_rejected(tmp_path):
    p = tmp_path / "bad.docx"
    p.write_bytes(b"PK\x03\x04 this is not really a zip")
    with pytest.raises(ParseError) as e:
        parse(p, tmp_path)
    assert e.value.code == "CORRUPT_FILE"


def test_doc_renamed_to_docx_rejected(tmp_path):
    p = tmp_path / "old.docx"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600)  # OLE2 .doc header
    with pytest.raises(ParseError) as e:
        parse(p, tmp_path)
    assert e.value.code == "CORRUPT_FILE"


# ---- figures ----------------------------------------------------------------


def test_picture_becomes_figure_paragraph_in_order(tmp_path):
    d = new_docx()
    d.add_heading("方案", level=1)
    d.add_paragraph("系统如下。")
    add_picture(d.add_paragraph(), make_png())
    d.add_paragraph("之后的文字。")
    doc = parse(save(d, tmp_path), tmp_path)
    paras = doc.sections[0].paragraphs
    assert [p.kind for p in paras] == ["text", "figure", "text"]
    fig = paras[1].figure
    assert fig.source == "embedded" and fig.analysable
    assert (tmp_path / "figures" / fig.file).exists()
    assert (fig.width, fig.height) == (200, 120)
    assert doc.figure_count == 1


def test_caption_after_picture_is_merged(tmp_path):
    d = new_docx()
    d.add_heading("方案", level=1)
    add_picture(d.add_paragraph(), make_png())
    d.add_paragraph("图 2-1 系统架构")
    d.add_paragraph("正文")
    paras = parse(save(d, tmp_path), tmp_path).sections[0].paragraphs
    assert [p.kind for p in paras] == ["figure", "text"]
    assert paras[0].figure.caption == "图 2-1 系统架构"
    assert paras[0].text == "[Figure] 图 2-1 系统架构"


def test_caption_before_picture_is_merged(tmp_path):
    d = new_docx()
    d.add_heading("Results", level=1)
    d.add_paragraph("Table 3 Measured downtime")
    add_picture(d.add_paragraph(), make_png())
    paras = parse(save(d, tmp_path), tmp_path).sections[0].paragraphs
    assert len(paras) == 1 and paras[0].figure.caption == "Table 3 Measured downtime"


def test_table_caption_after_figure_is_not_stolen(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    add_picture(d.add_paragraph(), make_png())
    d.add_paragraph("表1 参数")
    d.add_table(rows=1, cols=1).cell(0, 0).text = "x"
    paras = parse(save(d, tmp_path), tmp_path).sections[0].paragraphs
    assert paras[0].figure.caption is None
    assert paras[1].text == "表1 参数"


def test_sentence_mentioning_figure_is_not_a_caption(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    add_picture(d.add_paragraph(), make_png())
    d.add_paragraph("图3显示了停机时间明显下降，这说明方案有效。")
    paras = parse(save(d, tmp_path), tmp_path).sections[0].paragraphs
    assert paras[0].figure.caption is None and len(paras) == 2


def test_picture_in_table_cell_found(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    cell = d.add_table(rows=1, cols=1).cell(0, 0)
    add_picture(cell.paragraphs[0], make_png())
    doc = parse(save(d, tmp_path), tmp_path)
    assert doc.figure_count == 1


def test_alt_text_read(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    add_picture(d.add_paragraph(), make_png(), alt="Bar chart of downtime")
    assert (
        parse(save(d, tmp_path), tmp_path).figures()[0].figure.alt_text == "Bar chart of downtime"
    )


def test_tiny_icon_skipped(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    d.add_paragraph("text")
    add_picture(d.add_paragraph(), make_png(16, 16))
    doc = parse(save(d, tmp_path), tmp_path)
    assert doc.figure_count == 0
    assert any(w.startswith("FIGURES_SKIPPED") for w in doc.warnings)


def test_same_image_twice_one_file_two_figures(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    png = make_png()
    add_picture(d.add_paragraph(), png)
    d.add_paragraph("middle")
    add_picture(d.add_paragraph(), png)
    doc = parse(save(d, tmp_path), tmp_path)
    assert doc.figure_count == 2
    assert len(list((tmp_path / "figures").iterdir())) == 1


def test_rgba_and_large_images_normalised(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    add_picture(d.add_paragraph(), make_png(3200, 800, color=(0, 0, 0, 0), mode="RGBA"))
    fig = parse(save(d, tmp_path), tmp_path).figures()[0].figure
    assert (fig.width, fig.height) == (1600, 400)
    from PIL import Image

    assert Image.open(tmp_path / "figures" / fig.file).mode == "RGB"


def test_emf_kept_but_not_analysable(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    d.add_paragraph("text")
    add_raw_image(d, d.add_paragraph(), b"\x01\x00\x00\x00" + b"\x00" * 200, "image/x-emf")
    doc = parse(save(d, tmp_path), tmp_path)
    fig = doc.figures()[0].figure
    assert fig.analysable is False and fig.file is None
    assert "FIGURE_FORMAT_UNSUPPORTED" in doc.warnings


def test_corrupt_image_skipped_rest_of_doc_parsed(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    d.add_paragraph("still here")
    add_raw_image(d, d.add_paragraph(), b"\x89PNG garbage", "image/png", name="bad.png")
    doc = parse(save(d, tmp_path), tmp_path)
    assert doc.figure_count == 0
    assert doc.paragraph("S1.P1").text == "still here"
    assert "FIGURE_UNREADABLE" in doc.warnings


def test_native_chart_data_extracted(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    add_chart(d, d.add_paragraph())
    d.add_paragraph("图3 季度停机时间")
    fig = parse(save(d, tmp_path), tmp_path).figures()[0].figure
    assert fig.source == "docx_chart"
    assert fig.caption == "图3 季度停机时间"
    assert "停机时间" in fig.chart_data
    assert "Q1, Q2" in fig.chart_data and "2023: 12, 8" in fig.chart_data


def test_images_only_docx(tmp_path):
    d = new_docx()
    add_picture(d.add_paragraph(), make_png())
    path = save(d, tmp_path)
    with pytest.raises(ParseError) as e:
        parse(path, tmp_path)
    assert e.value.code == "EMPTY_DOCUMENT" and "VISION_MODEL" in e.value.detail
    assert parse(path, tmp_path, allow_figures_only=True).figure_count == 1


def test_figure_cap_marks_extras_unanalysable(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    for i in range(3):
        add_picture(d.add_paragraph(), make_png(100 + i, 100))
    doc = parse(save(d, tmp_path), tmp_path, max_figures=2)
    assert [f.figure.analysable for f in doc.figures()] == [True, True, False]
    assert any(w.startswith("TOO_MANY_FIGURES") for w in doc.warnings)


def test_no_figures_dir_still_records_figures(tmp_path):
    d = new_docx()
    d.add_heading("R", level=1)
    add_picture(d.add_paragraph(), make_png())
    doc = parse_file(save(d, tmp_path), doc_type="report")  # e.g. KB ingestion
    assert doc.figures()[0].figure.file is None
