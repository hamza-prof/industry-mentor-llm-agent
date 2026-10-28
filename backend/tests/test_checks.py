from pathlib import Path

from app.checks import format_checks
from app.parsing import parse_file
from app.schemas import Figure, Paragraph, ParsedDocument, Section


def fig(pid, caption=None, analysable=True):
    f = Figure(image_id="a" * 32, source="embedded", caption=caption, analysable=analysable)
    return Paragraph(id=pid, text=f"[Figure] {caption}", kind="figure", figure=f)


def doc(*sections, doc_type="technical") -> ParsedDocument:
    """sections: (heading, level, [text | Paragraph, ...])"""
    out = []
    for i, (heading, level, paras) in enumerate(sections, 1):
        ps = [
            p if isinstance(p, Paragraph) else Paragraph(id=f"S{i}.P{j}", text=p)
            for j, p in enumerate(paras, 1)
        ]
        out.append(Section(id=f"S{i}", heading=heading, level=level, paragraphs=ps))
    return ParsedDocument(filename="x", doc_type=doc_type, language="zh", sections=out)


def problems(d, **kw):
    return [c.problem for c in format_checks(d, **kw)]


def find(d, word, **kw):
    return [c for c in format_checks(d, **kw) if word in c.problem]


def test_all_rule_comments_are_rule_origin():
    d = doc(("1 A", 1, []), ("3 B", 1, ["x"]), doc_type="proposal")
    cs = format_checks(d)
    assert cs and all(c.origin == "rule" for c in cs)


# 1. heading numbering
def test_heading_gap_detected():
    d = doc(("2 方法", 1, ["a"]), ("2.1 数据", 2, ["b"]), ("2.3 模型", 2, ["c"]))
    gaps = find(d, "2.2")
    assert len(gaps) == 1 and gaps[0].section_id == "S3" and gaps[0].category == "format"


def test_heading_duplicate_detected():
    d = doc(("1 引言", 1, ["a"]), ("2 方法", 1, ["b"]), ("2 方法二", 1, ["c"]))
    assert [c.section_id for c in find(d, "重复") + find(d, "duplicate")] == ["S3"]


def test_chinese_numeral_gap_detected():
    d = doc(("一、背景", 1, ["a"]), ("二、目标", 1, ["b"]), ("四、计划", 1, ["c"]))
    assert find(d, "三")


def test_correct_numbering_has_no_comment():
    d = doc(
        ("一、背景", 1, ["a"]),
        ("二、方案", 1, []),
        ("2.1 数据", 2, ["b"]),
        ("2.2 模型", 2, ["c"]),
        ("三、计划", 1, ["d"]),
    )
    assert [c for c in format_checks(d) if c.category == "format"] == []


def test_numbering_restarts_under_each_chinese_heading():
    d = doc(
        ("一、背景", 1, ["a"]),
        ("1 现状", 2, ["b"]),
        ("2 问题", 2, ["c"]),
        ("二、方案", 1, ["d"]),
        ("1 数据", 2, ["e"]),
        ("2 模型", 2, ["f"]),
    )
    assert [c for c in format_checks(d) if c.category == "format"] == []


def test_stray_figure_caption_line_means_missing_figure():
    d = doc(("1 结果", 1, ["图3 系统架构"]))
    assert [c.paragraph_id for c in find(d, "图3")] == ["S1.P1"]


# 2 + 3. references
def test_missing_references_section():
    assert find(doc(("1 方法", 1, ["如文献[1]所述"])), "参考文献")
    assert find(doc(("1 Intro", 1, ["text"]), doc_type="report"), "参考文献")
    assert not find(doc(("1 Intro", 1, ["no citations here"])), "参考文献")  # technical


def test_citation_not_in_reference_list_and_uncited_reference():
    d = doc(
        ("1 方法", 1, ["已有研究[1]表明，另见[3]。"]),
        ("参考文献", 1, ["[1] Zhang. A paper. 2020.", "[2] Li. Another. 2021."]),
    )
    missing = find(d, "[3]")
    assert len(missing) == 1 and missing[0].paragraph_id == "S1.P1"
    assert missing[0].category == "citation"
    uncited = find(d, "[2]")
    assert len(uncited) == 1 and uncited[0].paragraph_id == "S2.P2"


def test_citation_ranges_count_as_cited():
    d = doc(
        ("1 方法", 1, ["见[1-3]和[4, 5]"]), ("References", 1, [f"[{i}] R{i}" for i in range(1, 6)])
    )
    assert [c for c in format_checks(d) if c.category == "citation"] == []


# 4. figures and tables
def test_figure_reference_without_figure():
    d = doc(("1 结果", 1, ["如图3所示，效率提升。", fig("S1.P2", "图1 架构")]))
    cs = find(d, "图3")
    assert len(cs) == 1 and cs[0].paragraph_id == "S1.P1"


def test_figure_without_caption_and_unreferenced():
    d = doc(("1 Results", 1, ["See Figure 1.", fig("S1.P2", "Figure 1 Flow"), fig("S1.P3")]))
    no_caption = find(d, "caption") + find(d, "图注")
    assert [c.paragraph_id for c in no_caption] == ["S1.P3"]
    assert not [c for c in format_checks(d) if c.paragraph_id == "S1.P2"]


def test_figure_never_referenced():
    d = doc(("1 结果", 1, ["效率提升。", fig("S1.P2", "图1 架构")]))
    assert [c.paragraph_id for c in format_checks(d)] == ["S1.P2"]


def test_figure_numbering_gap_and_duplicate():
    d = doc(
        (
            "1 结果",
            1,
            [
                "见图1、图2和图4。",
                fig("S1.P2", "图1 a"),
                fig("S1.P3", "图2 b"),
                fig("S1.P4", "图4 c"),
                fig("S1.P5", "图4 d"),
            ],
        ),
    )
    assert find(d, "图3")
    assert [c.paragraph_id for c in find(d, "图4") if c.paragraph_id] == ["S1.P5"]


def test_table_reference_needs_table_caption():
    ok = doc(
        (
            "1 结果",
            1,
            ["见表1。", "表1 指标对比", Paragraph(id="S1.P3", text="a | b", kind="table")],
        )
    )
    assert not find(ok, "表1")
    bad = doc(("1 结果", 1, ["见表2。"]))
    assert find(bad, "表2")


def test_unanalysable_figure_noted():
    d = doc(("1 结果", 1, ["见图1。", fig("S1.P2", "图1 流程", analysable=False)]))
    cs = format_checks(d)
    assert [c.paragraph_id for c in cs] == ["S1.P2"] and cs[0].severity == "low"


# 5. empty section
def test_empty_section_but_not_parent_heading():
    d = doc(("1 方法", 1, []), ("1.1 数据", 2, ["a"]), ("2 结果", 1, []), ("3 结论", 1, ["b"]))
    empty = [c for c in format_checks(d) if c.category == "completeness"]
    assert [c.section_id for c in empty] == ["S3"]


# 6. long paragraph
def test_long_paragraph():
    d = doc(("1 方法", 1, ["很长" * 800, "短"]))
    cs = [c for c in format_checks(d) if c.category == "clarity"]
    assert [c.paragraph_id for c in cs] == ["S1.P1"]


# 7. required sections
def test_required_sections_for_proposal():
    d = doc(("一、项目背景", 1, ["a"]), ("二、项目目标", 1, ["b"]), doc_type="proposal")
    missing = [c for c in format_checks(d) if c.category == "completeness"]
    assert missing and all(c.section_id is None for c in missing)
    assert any("风险" in c.problem for c in missing)
    assert not any("背景" in c.problem for c in missing)


def test_required_sections_configurable():
    d = doc(("1 Intro", 1, ["a"]), doc_type="proposal")
    assert not [c for c in format_checks(d, required_sections={}) if c.category == "completeness"]


def test_rules_survive_document_without_headings():
    d = doc(("Part 1", 1, ["a" * 100]), ("Part 2", 1, ["b"]), doc_type="report")
    format_checks(d)


def test_sample_proposal_flags():
    parsed = parse_file(Path(__file__).parents[2] / "docs/samples/proposal_zh.md", "proposal")
    text = " ".join(problems(parsed))
    assert "3.2" in text  # 3.1 → 3.3 jump
    assert "风险" in text and "参考文献" in text
