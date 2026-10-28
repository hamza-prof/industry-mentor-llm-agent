import asyncio

from langchain_core.runnables import RunnableLambda

from app import prompts
from app.config import Settings
from app.figures import describe_figures
from app.schemas import Figure, FigureDescription, Paragraph, ParsedDocument, Section
from tests.helpers import make_png


class FakeVision:
    def __init__(self, desc=None, fail=lambda msgs: False):
        self.desc = desc or FigureDescription(
            kind="chart",
            summary="Bar chart of orders",
            key_data=["2021: 120", "2023: 280"],
            issues=["The y-axis has no unit."],
        )
        self.fail, self.calls = fail, []

    def with_structured_output(self, schema, **kw):
        assert schema is FigureDescription

        async def run(msgs):
            self.calls.append(msgs)
            if self.fail(msgs):
                raise RuntimeError("vision down")
            return self.desc

        return RunnableLambda(run)


def figure(
    pid, image_id, source="embedded", analysable=True, caption="图1 年订单数量", chart_data=None
):
    f = Figure(
        image_id=image_id,
        file=f"{image_id}.png",
        source=source,
        caption=caption,
        analysable=analysable,
        chart_data=chart_data,
    )
    return Paragraph(id=pid, text=f"[Figure] {caption}", kind="figure", figure=f)


def doc(*figs) -> ParsedDocument:
    paras = [
        Paragraph(id="S1.P1", text="订单逐年增长。"),
        *figs,
        Paragraph(id="S1.P9", text="见上图。"),
    ]
    return ParsedDocument(
        filename="x",
        doc_type="report",
        language="zh",
        sections=[Section(id="S1", heading="1 结果", level=1, paragraphs=paras)],
    )


def setup(tmp_path, *ids):
    for i in ids:
        (tmp_path / f"{i}.png").write_bytes(make_png())
    return tmp_path


def run(parsed, figdir, session, model, **kw):
    return asyncio.run(
        describe_figures(parsed, figdir, session, Settings(_env_file=None, **kw), model)
    )


A, B, C = "a" * 32, "b" * 32, "c" * 32


def test_each_analysable_figure_described_once_with_image(session, tmp_path):
    d = doc(figure("S1.P2", A), figure("S1.P3", B, caption="图2 x"))
    vision = FakeVision()
    res = run(d, setup(tmp_path, A, B), session, vision)
    assert len(vision.calls) == 2 and res.analysed == 2
    human = vision.calls[0][-1].content
    assert human[1]["type"] == "image_url" and human[1]["image_url"]["url"].startswith(
        "data:image/png"
    )
    assert "图1 年订单数量" in human[0]["text"] and "订单逐年增长" in human[0]["text"]


def test_figure_text_rebuilt_with_description(session, tmp_path):
    res = run(doc(figure("S1.P2", A)), setup(tmp_path, A), session, FakeVision())
    assert res.parsed.paragraph("S1.P2").text == (
        "[Figure: 图1 年订单数量] Bar chart of orders; data: 2021: 120, 2023: 280"
    )


def test_issues_become_anchored_comments(session, tmp_path):
    res = run(doc(figure("S1.P2", A)), setup(tmp_path, A), session, FakeVision())
    [c] = res.comments
    assert (c.paragraph_id, c.section_id, c.anchored, c.origin) == ("S1.P2", "S1", True, "ai")
    assert c.problem == "The y-axis has no unit." and c.category == "format"


def test_second_run_uses_cache(session, tmp_path):
    figdir = setup(tmp_path, A)
    run(doc(figure("S1.P2", A)), figdir, session, FakeVision())
    vision = FakeVision()
    res = run(doc(figure("S1.P2", A)), figdir, session, vision)
    assert vision.calls == [] and "Bar chart of orders" in res.parsed.paragraph("S1.P2").text


def test_new_prompt_version_invalidates_cache(session, tmp_path):
    figdir = setup(tmp_path, A)
    run(doc(figure("S1.P2", A)), figdir, session, FakeVision())
    spec = prompts.DEFAULT_PROMPTS["figure_describe"]
    prompts.save_version(session, "figure_describe", spec.system, spec.user + " Be brief.")
    vision = FakeVision()
    run(doc(figure("S1.P2", A)), figdir, session, vision)
    assert len(vision.calls) == 1


def test_unanalysable_and_chart_figures_skip_vision(session, tmp_path):
    d = doc(
        figure("S1.P2", A, analysable=False),
        figure(
            "S1.P3", B, source="docx_chart", caption="图2 停机", chart_data="Chart: Q1 12, Q2 8"
        ),
    )
    vision = FakeVision()
    res = run(d, setup(tmp_path, A, B), session, vision)
    assert vision.calls == []
    assert res.parsed.paragraph("S1.P3").text == "[Figure: 图2 停机] Chart: Q1 12, Q2 8"
    assert res.parsed.paragraph("S1.P2").text == "[Figure] 图1 年订单数量"


def test_no_vision_model_warns_and_continues(session, tmp_path):
    res = run(doc(figure("S1.P2", A)), setup(tmp_path, A), session, None)
    assert any(w.startswith("FIGURES_NOT_ANALYSED") for w in res.warnings)
    assert res.parsed.paragraph("S1.P2").text == "[Figure] 图1 年订单数量" and res.comments == []


def test_no_warning_when_nothing_to_analyse(session, tmp_path):
    assert run(doc(), tmp_path, session, None).warnings == []


def test_failing_figure_keeps_caption_and_others_continue(session, tmp_path):
    d = doc(figure("S1.P2", A), figure("S1.P3", B, caption="图2 x"))
    vision = FakeVision(fail=lambda msgs: "图2 x" in msgs[-1].content[0]["text"])
    res = run(d, setup(tmp_path, A, B), session, vision)
    assert len(vision.calls) == 3  # A once, B twice
    assert res.parsed.paragraph("S1.P3").text == "[Figure] 图2 x"
    assert "Bar chart" in res.parsed.paragraph("S1.P2").text
    assert any("FIGURE_DESCRIBE_FAILED" in w and "S1.P3" in w for w in res.warnings)
    assert res.analysed == 1


def test_original_document_not_modified(session, tmp_path):
    d = doc(figure("S1.P2", A))
    run(d, setup(tmp_path, A), session, FakeVision())
    assert d.paragraph("S1.P2").text == "[Figure] 图1 年订单数量"


def test_concurrency_capped(session, tmp_path):
    ids = [f"{i:032x}" for i in range(6)]
    active = {"now": 0, "max": 0}

    class Slow(FakeVision):
        def with_structured_output(self, schema, **kw):
            async def run_(msgs):
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
                await asyncio.sleep(0.01)
                active["now"] -= 1
                return self.desc

            return RunnableLambda(run_)

    figs = [figure(f"S1.P{i + 2}", x, caption=f"图{i + 1} x") for i, x in enumerate(ids)]
    run(doc(*figs), setup(tmp_path, *ids), session, Slow())
    assert active["max"] <= 3
