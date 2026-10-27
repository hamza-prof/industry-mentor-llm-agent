import pytest

from app.parsing import (
    Block,
    ParseError,
    build_sections,
    detect_language,
    heading_level,
    parse_file,
)


def write(tmp_path, name, content, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(content.encode(encoding) if isinstance(content, str) else content)
    return p


def parse(tmp_path, name, content, encoding="utf-8"):
    return parse_file(write(tmp_path, name, content, encoding), doc_type="report")


# ---- markdown / text parser -------------------------------------------------


def test_markdown_headings_give_nested_levels(tmp_path):
    doc = parse(tmp_path, "a.md", "# Intro\n\nHello there.\n\n## Detail\n\nMore text.\n")
    assert [(s.id, s.heading, s.level) for s in doc.sections] == [
        ("S1", "Intro", 1),
        ("S2", "Detail", 2),
    ]
    assert doc.paragraph("S1.P1").text == "Hello there."
    assert doc.paragraph("S2.P1").text == "More text."


def test_lines_in_one_paragraph_are_joined(tmp_path):
    doc = parse(tmp_path, "a.md", "# T\n\nfirst line\nsecond line\n\n中文第一行\n中文第二行\n")
    texts = [p.text for p in doc.sections[0].paragraphs]
    assert texts == ["first line second line", "中文第一行中文第二行"]


def test_markdown_list_items_are_separate_list_paragraphs(tmp_path):
    doc = parse(tmp_path, "a.md", "# 目标\n\n1. 构建平台。\n2. 训练模型。\n- bullet\n")
    paras = doc.sections[0].paragraphs
    assert [p.kind for p in paras] == ["list", "list", "list"]
    assert paras[0].text == "1. 构建平台。"


def test_numbered_plain_text_headings(tmp_path):
    txt = "1 绪论\n\n本文研究设备维护。\n\n1.1 研究背景\n\n背景内容。\n\n2 方案\n\n方案内容。\n"
    doc = parse(tmp_path, "a.txt", txt)
    assert [(s.heading, s.level) for s in doc.sections] == [
        ("1 绪论", 1),
        ("1.1 研究背景", 2),
        ("2 方案", 1),
    ]


def test_no_structure_falls_back_to_pseudo_sections(tmp_path):
    body = "\n\n".join(["这是一段没有标题的文字。" * 10] * 12)
    doc = parse(tmp_path, "a.txt", body)
    assert "NO_HEADINGS_DETECTED" in doc.warnings
    assert len(doc.sections) > 1
    assert doc.sections[0].heading == "Part 1"


def test_gbk_encoded_text_is_decoded(tmp_path):
    doc = parse(tmp_path, "a.txt", "# 标题\n\n中文内容\n", encoding="gbk")
    assert doc.sections[0].heading == "标题"


def test_utf8_bom_crlf_and_fullwidth_spaces(tmp_path):
    raw = "﻿# Title\r\n\r\n　　indented text  \r\n".encode()
    doc = parse(tmp_path, "a.md", raw)
    assert doc.sections[0].heading == "Title"
    assert doc.paragraph("S1.P1").text == "indented text"


def test_undecodable_bytes_rejected(tmp_path):
    with pytest.raises(ParseError) as e:
        parse(tmp_path, "a.txt", b"\x81\x30\xff\xff\xfe\x00" * 50)
    assert e.value.code == "UNSUPPORTED_ENCODING"


def test_empty_file_rejected(tmp_path):
    with pytest.raises(ParseError) as e:
        parse(tmp_path, "a.txt", "  \n\n \t ")
    assert e.value.code == "EMPTY_DOCUMENT"


def test_unsupported_extension_rejected(tmp_path):
    with pytest.raises(ParseError) as e:
        parse(tmp_path, "a.pptx", "x")
    assert e.value.code == "UNSUPPORTED_FILE_TYPE"


def test_extension_is_case_insensitive(tmp_path):
    assert parse(tmp_path, "A.MD", "# X\n\ny\n").sections[0].heading == "X"


def test_markdown_image_kept_as_unanalysable_figure(tmp_path):
    doc = parse(tmp_path, "a.md", "# T\n\n![系统架构图](arch.png)\n")
    p = doc.paragraph("S1.P1")
    assert p.kind == "figure"
    assert p.figure.alt_text == "系统架构图"
    assert p.figure.analysable is False


def test_reparse_gives_identical_ids(tmp_path):
    path = write(tmp_path, "a.md", "# A\n\nx\n\n# B\n\ny\n\nz\n")
    a, b = parse_file(path, doc_type="report"), parse_file(path, doc_type="report")
    assert a.all_paragraph_ids() == b.all_paragraph_ids() == ["S1.P1", "S2.P1", "S2.P2"]


def test_sample_proposal_parses_sensibly():
    from pathlib import Path

    sample = Path(__file__).parents[2] / "docs/samples/proposal_zh.md"
    if not sample.exists():
        pytest.skip("samples not present")
    doc = parse_file(sample, doc_type="proposal")
    headings = [s.heading for s in doc.sections]
    assert "一、项目背景" in headings and "3.3 模型设计" in headings
    assert doc.language == "zh"


# ---- sectionizer rules ------------------------------------------------------


@pytest.mark.parametrize(
    "line,level",
    [
        ("1 绪论", 1),
        ("1.1 背景", 2),
        ("1.1.1 细节", 3),
        ("一、项目背景", 1),
        ("（一）数据采集", 2),
        ("第一章 绪论", 1),
        ("第3节 方法", 2),
        ("2. Methodology", 1),
    ],
)
def test_numbered_heading_patterns(line, level):
    secs, _ = build_sections([Block(line), Block("body")])
    assert (secs[0].heading, secs[0].level) == (line, level)


@pytest.mark.parametrize(
    "line",
    [
        "2023年的数据显示设备停机严重",
        "1. 构建设备振动与温度数据的实时采集平台。",
        "3 months later the system was deployed to production across all sites, which took long",
    ],
)
def test_sentences_are_not_headings(line):
    assert heading_level(line) is None


def test_text_before_first_heading_is_front_matter():
    secs, _ = build_sections([Block("作者：张三"), Block("1 绪论"), Block("x")])
    assert (secs[0].id, secs[0].heading) == ("S0", "Front matter")
    assert secs[1].id == "S1"


def test_table_of_contents_is_dropped():
    blocks = [
        Block("目录"),
        Block("1 绪论 .......... 1"),
        Block("2 方案 .......... 5"),
        Block("1 绪论"),
        Block("正文"),
    ]
    secs, _ = build_sections(blocks)
    assert [s.heading for s in secs] == ["1 绪论"]
    assert secs[0].paragraphs[0].text == "正文"


def test_duplicate_headings_get_distinct_ids():
    secs, _ = build_sections([Block("Intro", level=1), Block("a"), Block("Intro", level=1)])
    assert [s.id for s in secs] == ["S1", "S2"]


def test_empty_section_kept():
    secs, _ = build_sections([Block("A", level=1), Block("B", level=1), Block("x")])
    assert secs[0].paragraphs == []


# ---- language ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,lang",
    [("这是中文文本", "zh"), ("plain English text", "en"), ("基于LSTM的预测模型研究", "zh")],
)
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_single_leading_h1_is_document_title(tmp_path):
    doc = parse(tmp_path, "a.md", "# My Report\n\n## 1. Intro\n\nx\n\n## 2. Method\n\ny\n")
    assert doc.title == "My Report"
    assert [(s.heading, s.level) for s in doc.sections] == [("1. Intro", 2), ("2. Method", 2)]


def test_several_h1_are_sections_not_title(tmp_path):
    doc = parse(tmp_path, "a.md", "# A\n\nx\n\n# B\n\ny\n")
    assert doc.title is None and [s.heading for s in doc.sections] == ["A", "B"]
