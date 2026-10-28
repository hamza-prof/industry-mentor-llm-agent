"""Run one review end to end: figures → summary → format rules → sections (≤3 at once).
Each step opens its own DB session; comments are saved per section so the UI sees them arrive.
Must run on the server's event loop (BackgroundTasks), not in a fresh asyncio.run per job:
the OpenAI client is cached per URL and bound to the loop that first used it."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from sqlalchemy import Engine, delete
from sqlmodel import Session, select

from app import kb
from app.checks import format_checks
from app.config import Settings
from app.figures import describe_figures
from app.models import Document, Review, ReviewComment
from app.review import dedupe_comments, review_section, summary_text
from app.schemas import Comment, ParsedDocument, StructuredSummary
from app.summarize import summarize_document

CONCURRENCY = 3
HITS_PER_CATEGORY = 4


@dataclass
class ReviewModels:
    chat: BaseChatModel
    vision: BaseChatModel | None = None
    store: Any = None  # Chroma, or None when embeddings aren't configured


class _Gone(Exception):
    """The review (or its document) was deleted while running."""


def _now() -> datetime:
    return datetime.now(UTC)


def _update(engine: Engine, review_id: int, **fields) -> None:
    with Session(engine) as s:
        r = s.get(Review, review_id)
        if r is None:
            raise _Gone
        for k, v in fields.items():
            setattr(r, k, v)
        s.commit()


def _save(engine: Engine, review_id: int, comments: list[Comment]) -> None:
    with Session(engine) as s:
        if s.get(Review, review_id) is None:
            raise _Gone
        s.add_all(ReviewComment(review_id=review_id, **c.model_dump()) for c in comments)
        s.commit()


def _existing(engine: Engine, review_id: int, section_id: str) -> list[Comment]:
    with Session(engine) as s:
        q = select(ReviewComment).where(
            ReviewComment.review_id == review_id, ReviewComment.section_id == section_id
        )
        return [Comment.model_validate(c, from_attributes=True) for c in s.exec(q)]


def _kb_status(engine: Engine, settings: Settings, store) -> str | None:
    if store is None:
        return "KB_UNAVAILABLE: embeddings not configured, reviewed without standards"
    with Session(engine) as s:
        if kb.needs_reindex(s, settings):
            return "KB_NEEDS_REINDEX: embedding model changed, reviewed without standards"
    return None


async def run_review(
    review_id: int,
    engine: Engine,
    settings: Settings,
    models: ReviewModels,
    only_sections: list[str] | None = None,
) -> None:
    """only_sections=None → full run; a list → re-review just those (retry of a partial)."""
    try:
        await _run(review_id, engine, settings, models, only_sections)
    except _Gone:  # drop anything saved before the review disappeared
        with Session(engine) as s:
            s.execute(delete(ReviewComment).where(ReviewComment.review_id == review_id))
            s.commit()
    except Exception as e:  # noqa: BLE001 — never leave a review stuck in "running"
        try:
            _update(
                engine,
                review_id,
                status="failed",
                stage="done",
                finished_at=_now(),
                errors=[{"section_id": None, "error": f"{type(e).__name__}: {e}"[:500]}],
            )
        except _Gone:
            pass


async def _run(review_id, engine, settings, models, only_sections) -> None:
    full = only_sections is None
    with Session(engine) as s:
        r = s.get(Review, review_id)
        doc = s.get(Document, r.document_id) if r else None
        if doc is None:
            raise _Gone
        parsed = ParsedDocument(**doc.parsed)
        figures_dir = settings.data_dir / "uploads" / Path(doc.stored_name).stem / "figures"
        old_errors, warnings = list(r.errors), [] if full else list(r.warnings)
        summary = StructuredSummary(**r.summary) if r.summary and not full else None
        if full:
            s.execute(delete(ReviewComment).where(ReviewComment.review_id == review_id))
        s.commit()
    _update(
        engine,
        review_id,
        status="running",
        stage="figures",
        started_at=_now(),
        finished_at=None,
        errors=[] if full else old_errors,
    )

    with Session(engine) as s:
        fig = await describe_figures(parsed, figures_dir, s, settings, models.vision)
    parsed = fig.parsed  # figure paragraphs now carry what the vision model saw
    if full:
        warnings += [*parsed.warnings, *fig.warnings]
        _save(engine, review_id, fig.comments)

    if summary is None:
        _update(engine, review_id, stage="summary")
        try:
            with Session(engine) as s:
                summary = await summarize_document(parsed, s, settings, models.chat)
        except Exception as e:  # noqa: BLE001
            _update(
                engine,
                review_id,
                status="failed",
                stage="done",
                finished_at=_now(),
                warnings=warnings,
                errors=[{"section_id": None, "error": f"summary: {e}"[:500]}],
            )
            return
        warnings += summary.warnings
        _update(
            engine,
            review_id,
            summary=summary.model_dump(mode="json"),
            figures_analysed=fig.analysed,
        )

    if full:
        _update(engine, review_id, stage="format")
        _save(engine, review_id, format_checks(parsed, settings.required_sections))

    if kb_warning := _kb_status(engine, settings, models.store):
        warnings.append(kb_warning)
    store = None if kb_warning else models.store
    targets = [s for s in parsed.sections if s.paragraphs and (full or s.id in only_sections)]
    errors = [] if full else [e for e in old_errors if e["section_id"] not in set(only_sections)]
    done = 0
    _update(engine, review_id, stage=f"sections 0/{len(targets)}", warnings=warnings)
    sem = asyncio.Semaphore(CONCURRENCY)
    gist = summary_text(summary)

    async def _search(section) -> dict:
        """Standards for this section; a KB failure only loses context, not the section."""
        if store is None:
            return {}
        query = f"{section.heading}\n" + " ".join(p.text for p in section.paragraphs)[:500]
        try:
            return {
                cat: await asyncio.to_thread(
                    kb.search, store, query, cat, parsed.doc_type, HITS_PER_CATEGORY
                )
                for cat in kb.CATEGORIES
            }
        except Exception as e:  # noqa: BLE001
            if not any(w.startswith("KB_SEARCH_FAILED") for w in warnings):
                warnings.append(f"KB_SEARCH_FAILED: reviewed without standards ({e})"[:300])
            return {}

    async def one(section) -> None:
        nonlocal done
        async with sem:
            try:
                hits = await _search(section)
                with Session(engine) as s:
                    new = await review_section(
                        parsed, section, hits, gist, s, settings, models.chat
                    )
                kept = _existing(engine, review_id, section.id)
                fresh = []
                for c in new:  # skip what a rule or figure comment already says
                    if len(dedupe_comments([*kept, c])) > len(kept):
                        kept.append(c)
                        fresh.append(c)
                _save(engine, review_id, fresh)
            except _Gone:
                raise
            except Exception as e:  # noqa: BLE001 — one section failing must not stop the rest
                errors.append({"section_id": section.id, "error": str(e)[:500]})
            done += 1
            _update(engine, review_id, stage=f"sections {done}/{len(targets)}")

    await asyncio.gather(*(one(s) for s in targets))
    failed_all = targets and len([e for e in errors if e["section_id"]]) >= len(targets) and full
    status = "failed" if failed_all else "partial" if errors else "done"
    _update(
        engine,
        review_id,
        status=status,
        stage="done",
        finished_at=_now(),
        warnings=warnings,
        errors=sorted(errors, key=lambda e: e["section_id"] or ""),
    )


def recover_stuck(engine: Engine) -> int:
    """At startup: reviews left queued/running by a server restart can never finish."""
    with Session(engine) as s:
        stuck = s.exec(select(Review).where(Review.status.in_(["queued", "running"]))).all()
        for r in stuck:
            r.status, r.stage, r.finished_at = "failed", "done", _now()
            r.errors = [{"section_id": None, "error": "server restarted during the review"}]
        s.commit()
        return len(stuck)
