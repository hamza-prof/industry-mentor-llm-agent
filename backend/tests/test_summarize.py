import asyncio
import os
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app import prompts
from app.config import Settings
from app.schemas import OutlineItem, Paragraph, ParsedDocument, Section, SummaryField, SummaryOutput
from app.summarize import summarize_document

FIELDS = (
    "research_problem",
    "objectives",
    "technical_approach",
    "main_conclusions",
    "innovations",
    "limitations",
)


class FakeLLM:
    """Stands in for a chat model: `ainvoke` → map notes, `with_structured_output` → summary."""

    def __init__(self, summary=None, notes=lambda msgs: "notes [S1.P1]", fail=lambda msgs: False):
        self.summary = output() if summary is None else summary
        self.notes, self.fail = notes, fail
        self.calls: list[tuple[str, list]] = []
        self.active = self.max_active = 0

    async def ainvoke(self, msgs):
        self.calls.append(("map", msgs))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if self.fail(msgs):
            raise RuntimeError("model down")
        return AIMessage(self.notes(msgs))

    def with_structured_output(self, schema, **kw):
        assert schema is SummaryOutput

        async def run(msgs):
            self.calls.append(("reduce", msgs))
            if isinstance(self.summary, list):  # a sequence of replies, one per call
                return self.summary.pop(0)
            return self.summary

        return RunnableLambda(run)

    def kinds(self):
        return [k for k, _ in self.calls]


def output(**overrides) -> SummaryOutput:
    data = {f: SummaryField(text=f"{f} text", source_ids=["S1.P1"]) for f in FIELDS}
    data["outline"] = [OutlineItem(section_id="S1", heading="Intro", one_line="intro line")]
    return SummaryOutput(**{**data, **overrides})


def doc(*sections: list[str], language="en", title="T") -> ParsedDocument:
    return ParsedDocument(
        filename="x.docx",
        doc_type="report",
        language=language,
        title=title,
        sections=[
            Section(
                id=f"S{i}",
                heading=f"Heading {i}",
                level=1,
                paragraphs=[Paragraph(id=f"S{i}.P{j}", text=t) for j, t in enumerate(texts, 1)],
            )
            for i, texts in enumerate(sections, 1)
        ],
    )


LONG = "word " * 60  # ~75 tokens per paragraph


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def run(parsed, session, llm, **kw):
    return asyncio.run(summarize_document(parsed, session, settings(**kw), model=llm))


def human(msgs) -> str:
    return msgs[-1].content


def test_short_doc_is_one_structured_call_with_labelled_text(session):
    llm = FakeLLM()
    s = run(doc(["Problem text.", "More."], ["Method."]), session, llm)
    assert llm.kinds() == ["reduce"]
    sent = human(llm.calls[0][1])
    assert "[S1.P1] Problem text." in sent and "[S2.P1] Method." in sent
    assert "[S2] Heading 2" in sent
    assert s.title == "T" and s.doc_type == "report"
    assert s.research_problem.text == "research_problem text"


def test_long_doc_maps_each_section_then_reduces(session):
    llm = FakeLLM(notes=lambda msgs: "NOTE<" + re.search(r"\[(S\d+)\.P", human(msgs))[1] + ">")
    parsed = doc([LONG] * 3, [LONG] * 3, [LONG] * 3, [LONG] * 3)
    run(parsed, session, llm, llm_context_tokens=1000)  # budget 600 < ~900 tokens
    assert llm.kinds() == ["map"] * 4 + ["reduce"]
    reduce_text = human(llm.calls[-1][1])
    for i in range(1, 5):
        assert f"[S{i}] Heading {i}\nNOTE<S{i}>" in reduce_text
    assert llm.max_active <= 3


def test_section_bigger_than_budget_is_split_by_paragraphs(session):
    llm = FakeLLM()
    run(doc([LONG] * 12), session, llm, llm_context_tokens=500)  # budget 300 ≈ 4 paragraphs
    maps = [human(m) for k, m in llm.calls if k == "map"]
    assert len(maps) >= 3
    assert all("[S1.P1]" not in m for m in maps[1:])  # each paragraph sent once
    assert sum(m.count("[S1.P") for m in maps) == 12


def test_unknown_source_ids_are_dropped(session):
    bad = SummaryField(text="x", source_ids=["S1.P1", "S99.P1"])
    s = run(doc(["a"]), session, FakeLLM(output(innovations=bad)))
    assert s.innovations.source_ids == ["S1.P1"]


def test_not_found_field_has_no_text_or_sources(session):
    nf = SummaryField(text="guessed", not_found=True, source_ids=["S1.P1"])
    empty = SummaryField(text="  ")
    s = run(doc(["a"]), session, FakeLLM(output(innovations=nf, limitations=empty)))
    assert s.innovations == SummaryField(text=None, not_found=True, source_ids=[])
    assert s.limitations.not_found is True and s.limitations.text is None


def test_outline_has_every_real_section_in_order(session):
    outline = [
        OutlineItem(section_id="S3", heading="wrong", one_line="three"),
        OutlineItem(section_id="S9", heading="ghost", one_line="ghost"),
        OutlineItem(section_id="S1", heading="Heading 1", one_line="one"),
    ]
    s = run(doc(["a"], ["b"], ["c"]), session, FakeLLM(output(outline=outline)))
    assert [(o.section_id, o.heading, o.one_line) for o in s.outline] == [
        ("S1", "Heading 1", "one"),
        ("S2", "Heading 2", ""),
        ("S3", "Heading 3", "three"),
    ]


def test_map_failure_retries_once_then_succeeds(session):
    tries = {"n": 0}

    def fail(msgs):
        if "[S2.P1]" in human(msgs):
            tries["n"] += 1
            return tries["n"] == 1
        return False

    llm = FakeLLM(fail=fail)
    s = run(doc([LONG] * 6, [LONG] * 6), session, llm, llm_context_tokens=1000)
    assert tries["n"] == 2 and s.warnings == []


def test_section_failing_twice_is_skipped_with_warning(session):
    llm = FakeLLM(fail=lambda msgs: "[S2.P1]" in human(msgs))
    s = run(doc([LONG] * 6, [LONG] * 6), session, llm, llm_context_tokens=1000)
    assert llm.kinds()[-1] == "reduce"
    assert "Heading 2" not in human(llm.calls[-1][1])
    assert any(w.startswith("SUMMARY_SECTION_FAILED") and "S2" in w for w in s.warnings)


def test_all_map_calls_failing_raises(session):
    llm = FakeLLM(fail=lambda msgs: True)
    with pytest.raises(RuntimeError, match="model down"):
        run(doc([LONG] * 6, [LONG] * 6), session, llm, llm_context_tokens=1000)


def test_empty_structured_summary_is_retried_once(session):
    llm = FakeLLM(summary=[None, output()])
    s = run(doc(["one"]), session, llm)
    assert llm.kinds() == ["reduce", "reduce"]
    assert s.research_problem.text == "research_problem text"


def test_empty_structured_summary_twice_raises_a_clear_error(session):
    llm = FakeLLM(summary=[None, None])
    with pytest.raises(ValueError, match="no structured summary"):
        run(doc(["one"]), session, llm)


def test_very_short_doc_warns(session):
    assert "DOCUMENT_TOO_SHORT" in run(doc(["tiny"]), session, FakeLLM()).warnings
    assert run(doc(["x" * 300]), session, FakeLLM()).warnings == []


@pytest.mark.parametrize(
    ("doc_lang", "setting", "expected"),
    [("zh", "auto", "Chinese"), ("en", "auto", "English"), ("zh", "en", "English")],
)
def test_output_language(session, doc_lang, setting, expected):
    llm = FakeLLM()
    run(doc(["a"], language=doc_lang), session, llm, output_language=setting)
    assert f"Write all output text in {expected}" in llm.calls[0][1][0].content


def test_uses_the_mentors_active_prompt(session):
    prompts.save_version(session, "summary_reduce", "SYS", "MY PROMPT {document}")
    llm = FakeLLM()
    run(doc(["a"]), session, llm)
    assert human(llm.calls[0][1]).startswith("MY PROMPT")


def test_figures_are_sent_with_their_text(session):
    parsed = doc(["Intro."])
    parsed.sections[0].paragraphs.append(
        Paragraph(id="S1.P2", text="[Figure] 图1 年订单数量", kind="figure")
    )
    llm = FakeLLM()
    run(parsed, session, llm)
    assert "[S1.P2] [Figure] 图1 年订单数量" in human(llm.calls[0][1])


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call a real LLM")
def test_live_summary_of_sample_report(session):
    from app.parsing import parse_file

    parsed = parse_file(Path(__file__).parents[2] / "docs/samples/report_en.md", "report")
    s = asyncio.run(summarize_document(parsed, session, Settings()))
    ids = set(parsed.all_paragraph_ids())
    for name in ("research_problem", "technical_approach", "main_conclusions"):
        f = getattr(s, name)
        assert f.text and f.source_ids and set(f.source_ids) <= ids, name
    assert [o.section_id for o in s.outline] == [x.id for x in parsed.sections]
