import asyncio
import re
import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlmodel import Session, create_engine, select

from app import prompts, runner
from app.config import Settings
from app.db import init_db
from app.models import Document, Review, ReviewComment
from app.runner import ReviewModels, recover_stuck, run_review
from app.schemas import (
    KBHit,
    Paragraph,
    ParsedDocument,
    RawComment,
    Section,
    SectionReview,
    SummaryField,
    SummaryOutput,
)

SUMMARY = SummaryOutput(
    **{
        f: SummaryField(text=f, source_ids=["S1.P1"])
        for f in (
            "research_problem",
            "objectives",
            "technical_approach",
            "main_conclusions",
            "innovations",
            "limitations",
        )
    }
)


class FakeChat:
    def __init__(self, fail_sections=(), fail_summary=False):
        self.fail_sections, self.fail_summary = set(fail_sections), fail_summary
        self.reviewed: list[str] = []
        self.stages: list[str] = []
        self.engine = None

    async def ainvoke(self, msgs):
        return AIMessage("notes")

    def with_structured_output(self, schema, **kw):
        async def run(msgs):
            if schema is SummaryOutput:
                if self.fail_summary:
                    raise RuntimeError("LLM unreachable")
                return SUMMARY
            text = "\n".join(m.content for m in msgs if m.type == "human")
            sid = re.search(r"\[(S\d+)\.P\d+\]", text)[1]
            self.reviewed.append(sid)
            if self.engine:
                with Session(self.engine) as s:
                    self.stages.append(s.exec(select(Review)).first().stage)
            if sid in self.fail_sections:
                raise RuntimeError(f"boom {sid}")
            return SectionReview(
                comments=[
                    RawComment(
                        paragraph_id=f"{sid}.P1",
                        quote="claim",
                        category="evidence",
                        severity="high",
                        problem=f"Unsupported claim in {sid}",
                        suggestion="Add data.",
                    )
                ]
            )

        return RunnableLambda(run)


def parsed_doc() -> ParsedDocument:
    secs = [
        Section(
            id=f"S{i}",
            heading=f"{i} Part",
            level=1,
            paragraphs=[Paragraph(id=f"S{i}.P1", text=f"A claim without data in part {i}. " * 8)],
        )
        for i in (1, 2, 3)
    ]
    secs.append(Section(id="S4", heading="4 Empty", level=1))
    return ParsedDocument(filename="x.md", doc_type="technical", language="en", sections=secs)


@pytest.fixture
def engine(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    init_db(e)
    with Session(e) as s:
        prompts.seed_defaults(s)
    return e


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, llm_api_key="k")


def new_review(engine) -> int:
    with Session(engine) as s:
        doc = Document(
            filename="x.md",
            sha256=uuid.uuid4().hex,
            stored_name="u.md",
            doc_type="technical",
            parsed=parsed_doc().model_dump(mode="json", exclude={"figure_count", "char_count"}),
        )
        s.add(doc)
        s.commit()
        r = Review(document_id=doc.id)
        s.add(r)
        s.commit()
        return r.id


def go(engine, settings, chat, rid=None, **kw):
    rid = rid or new_review(engine)
    asyncio.run(run_review(rid, engine, settings, ReviewModels(chat=chat), **kw))
    with Session(engine) as s:
        r = s.get(Review, rid)
        cs = s.exec(select(ReviewComment).where(ReviewComment.review_id == rid)).all()
        return r, list(cs)


def test_happy_path_done_with_comments(engine, settings):
    chat = FakeChat()
    r, cs = go(engine, settings, chat)
    assert r.status == "done" and r.stage == "done" and r.errors == []
    assert r.summary["research_problem"]["text"] == "research_problem"
    assert r.started_at and r.finished_at
    ai = [c for c in cs if c.origin == "ai"]
    assert {c.paragraph_id for c in ai} == {"S1.P1", "S2.P1", "S3.P1"}
    assert all(c.anchored and c.quote == "claim" and c.status == "pending" for c in ai)
    assert sorted(chat.reviewed) == ["S1", "S2", "S3"]  # empty S4 skipped


def test_rule_comments_saved(engine, settings):
    _, cs = go(engine, settings, FakeChat())
    rules = [c for c in cs if c.origin == "rule"]
    assert any(c.section_id == "S4" and c.category == "completeness" for c in rules)


def test_one_section_fails_is_partial(engine, settings):
    r, cs = go(engine, settings, FakeChat(fail_sections={"S2"}))
    assert r.status == "partial"
    assert [e["section_id"] for e in r.errors] == ["S2"] and "boom S2" in r.errors[0]["error"]
    assert {c.paragraph_id for c in cs if c.origin == "ai"} == {"S1.P1", "S3.P1"}


def test_summary_failure_is_failed(engine, settings):
    r, cs = go(engine, settings, FakeChat(fail_summary=True))
    assert r.status == "failed" and "LLM unreachable" in r.errors[0]["error"]
    assert r.errors[0]["section_id"] is None and cs == []


def test_all_sections_fail_is_failed(engine, settings):
    r, _ = go(engine, settings, FakeChat(fail_sections={"S1", "S2", "S3"}))
    assert r.status == "failed" and len(r.errors) == 3


def test_stage_updates_observed(engine, settings, monkeypatch):
    monkeypatch.setattr(runner, "CONCURRENCY", 1)
    chat = FakeChat()
    chat.engine = engine
    go(engine, settings, chat)
    assert chat.stages == ["sections 0/3", "sections 1/3", "sections 2/3"]


def test_retry_only_failed_sections(engine, settings):
    rid = new_review(engine)
    go(engine, settings, FakeChat(fail_sections={"S2"}), rid)
    chat = FakeChat()
    r, cs = go(engine, settings, chat, rid, only_sections=["S2"])
    assert chat.reviewed == ["S2"] and r.status == "done" and r.errors == []
    ai = [c.paragraph_id for c in cs if c.origin == "ai"]
    assert sorted(ai) == ["S1.P1", "S2.P1", "S3.P1"]  # nothing duplicated
    assert len([c for c in cs if c.origin == "rule"]) == len(
        [c for c in go(engine, settings, FakeChat())[1] if c.origin == "rule"]
    )


def test_document_deleted_mid_run_aborts_cleanly(engine, settings):
    rid = new_review(engine)

    class Deleting(FakeChat):
        def with_structured_output(self, schema, **kw):
            inner = super().with_structured_output(schema, **kw)

            async def run(msgs):
                if schema is SectionReview:
                    with Session(engine) as s:
                        s.delete(s.get(Review, rid))
                        s.commit()
                return await inner.ainvoke(msgs)

            return RunnableLambda(run)

    asyncio.run(run_review(rid, engine, settings, ReviewModels(chat=Deleting())))  # no exception
    with Session(engine) as s:
        assert s.get(Review, rid) is None
        assert s.exec(select(ReviewComment).where(ReviewComment.review_id == rid)).all() == []


def test_kb_unavailable_warns_and_reviews(engine, settings):
    r, _ = go(engine, settings, FakeChat())
    assert any(w.startswith("KB_UNAVAILABLE") for w in r.warnings)


def test_kb_hits_used(engine, settings, monkeypatch):
    seen = []

    def fake_search(store, query, category, doc_type, k=4):
        seen.append((category, doc_type))
        return [
            KBHit(
                chunk_id="1:0",
                source_id=1,
                filename="rubric.md",
                category=category,
                text="Claims need data.",
                score=0.1,
            )
        ]

    monkeypatch.setattr(runner.kb, "search", fake_search)
    monkeypatch.setattr(runner.kb, "needs_reindex", lambda *a: False)
    rid = new_review(engine)
    asyncio.run(run_review(rid, engine, settings, ReviewModels(chat=FakeChat(), store=object())))
    with Session(engine) as s:
        assert not any(w.startswith("KB_") for w in s.get(Review, rid).warnings)
    assert ("standard", "technical") in seen and ("exemplar", "technical") in seen


def test_recover_stuck(engine):
    rid = new_review(engine)
    with Session(engine) as s:
        s.get(Review, rid).status = "running"
        s.commit()
    assert recover_stuck(engine) == 1
    with Session(engine) as s:
        r = s.get(Review, rid)
        assert r.status == "failed" and "restarted" in r.errors[0]["error"]


def test_ai_comment_duplicating_a_rule_comment_is_skipped(engine, settings, monkeypatch):
    from app.schemas import Comment

    rule = Comment(
        section_id="S1",
        paragraph_id="S1.P1",
        anchored=True,
        category="evidence",
        severity="low",
        problem="Unsupported claim in S1",
        origin="rule",
    )
    monkeypatch.setattr(runner, "format_checks", lambda parsed, required: [rule])
    _, cs = go(engine, settings, FakeChat())
    s1 = [(c.origin, c.paragraph_id) for c in cs if c.section_id == "S1"]
    assert s1 == [("rule", "S1.P1")]


def test_full_rerun_replaces_old_comments(engine, settings):
    rid = new_review(engine)
    first = len(go(engine, settings, FakeChat(), rid)[1])
    assert len(go(engine, settings, FakeChat(), rid)[1]) == first


def test_kb_search_failure_reviews_without_standards(engine, settings, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("embedding API returned NaN")

    monkeypatch.setattr(runner.kb, "search", broken)
    monkeypatch.setattr(runner.kb, "needs_reindex", lambda *a: False)
    rid = new_review(engine)
    chat = FakeChat()
    asyncio.run(run_review(rid, engine, settings, ReviewModels(chat=chat, store=object())))
    with Session(engine) as s:
        r = s.get(Review, rid)
    assert r.status == "done" and sorted(chat.reviewed) == ["S1", "S2", "S3"]
    kb_warnings = [w for w in r.warnings if w.startswith("KB_SEARCH_FAILED")]
    assert len(kb_warnings) == 1 and "NaN" in kb_warnings[0]
