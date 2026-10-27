from app.schemas import Figure, Paragraph, ParsedDocument, Section


def make_doc() -> ParsedDocument:
    fig = Figure(image_id="a" * 32, source="embedded", caption="图1 架构")
    return ParsedDocument(
        filename="x.docx",
        doc_type="proposal",
        language="zh",
        sections=[
            Section(id="S1", heading="背景", level=1, paragraphs=[Paragraph(id="S1.P1", text="t")]),
            Section(
                id="S2",
                heading="方案",
                level=1,
                paragraphs=[
                    Paragraph(id="S2.P1", text="u"),
                    Paragraph(id="S2.P2", text="[Figure] 图1 架构", kind="figure", figure=fig),
                ],
            ),
        ],
    )


def test_paragraph_lookup_by_id():
    doc = make_doc()
    assert doc.paragraph("S2.P1").text == "u"
    assert doc.paragraph("S9.P1") is None


def test_all_paragraph_ids_in_reading_order():
    assert make_doc().all_paragraph_ids() == ["S1.P1", "S2.P1", "S2.P2"]


def test_figures_and_counts():
    doc = make_doc()
    assert [p.id for p in doc.figures()] == ["S2.P2"]
    assert doc.figure_count == 1
    assert doc.char_count == len("t") + len("u")  # figure placeholder text not counted


def test_round_trips_through_json():
    doc = make_doc()
    assert ParsedDocument.model_validate_json(doc.model_dump_json()) == doc
