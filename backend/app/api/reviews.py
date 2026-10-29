from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app import prompts
from app.api import ApiError
from app.api.kb import kb_store
from app.db import get_session
from app.export import exported, final_text, to_docx, to_markdown
from app.llm import get_chat_model, get_vision_model
from app.models import Document, FigureCache, Review, ReviewComment
from app.review import summary_text
from app.runner import ReviewModels, run_review
from app.schemas import Comment, FigureDescription, ParsedDocument, StructuredSummary
from app.summarize import LANGUAGES

router = APIRouter(prefix="/api", tags=["reviews"])
SessionDep = Annotated[Session, Depends(get_session)]
ACTIVE = ("queued", "running")


class CreateReview(BaseModel):
    document_id: int


class OverallText(BaseModel):
    text: str


class CommentOut(Comment):
    id: int
    status: str
    mentor_text: str | None = None


class ReviewOut(BaseModel):
    id: int
    document_id: int
    status: str
    stage: str
    model: str
    prompt_versions: dict
    errors: list
    warnings: list
    summary: StructuredSummary | None = None
    figures_analysed: int
    overall_feedback: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    comment_count: int = 0
    comments: list[CommentOut] | None = None  # only on GET /reviews/{id}
    figures: dict[str, FigureDescription] | None = None  # image_id → vision description, ditto


def _models(request: Request) -> ReviewModels:
    app = request.app
    if app.state.review_models is not None:  # tests inject fakes here
        return app.state.review_models
    s = app.state.settings
    return ReviewModels(chat=get_chat_model(s), vision=get_vision_model(s), store=kb_store(app))


def _get(session: Session, review_id: int) -> Review:
    if (r := session.get(Review, review_id)) is None:
        raise ApiError(404, "NOT_FOUND", f"Review {review_id} not found.")
    return r


def _comments(session: Session, r: Review) -> list[ReviewComment]:
    q = select(ReviewComment).where(ReviewComment.review_id == r.id)
    return list(session.exec(q).all())


def _out(session: Session, r: Review, with_comments: bool = False) -> ReviewOut:
    cs = _comments(session, r)
    out = ReviewOut(**r.model_dump(exclude={"summary"}), summary=r.summary, comment_count=len(cs))
    if with_comments:
        doc = session.get(Document, r.document_id)
        parsed = ParsedDocument(**doc.parsed)
        sec = {s.id: i for i, s in enumerate(parsed.sections)}
        para = {pid: i for i, pid in enumerate(parsed.all_paragraph_ids())}
        cs.sort(key=lambda c: (sec.get(c.section_id, -1), para.get(c.paragraph_id, 10**9), c.id))
        out.comments = [CommentOut.model_validate(c, from_attributes=True) for c in cs]
        version = r.prompt_versions.get("figure_describe")
        out.figures = {
            p.figure.image_id: FigureDescription(**hit.data)
            for p in parsed.figures()
            if (hit := session.get(FigureCache, f"{p.figure.image_id}:{version}"))
        }
    return out


def _start(request, tasks: BackgroundTasks, r: Review, only: list[str] | None = None) -> None:
    app = request.app
    tasks.add_task(run_review, r.id, app.state.engine, app.state.settings, _models(request), only)


@router.post("/reviews", status_code=202, response_model=ReviewOut)
def create_review(
    body: CreateReview, request: Request, session: SessionDep, tasks: BackgroundTasks
):
    settings = request.app.state.settings
    if session.get(Document, body.document_id) is None:
        raise ApiError(404, "NOT_FOUND", f"Document {body.document_id} not found.")
    if not settings.llm_configured and request.app.state.review_models is None:
        raise ApiError(
            503,
            "LLM_NOT_CONFIGURED",
            "Add a language model and API key on the Settings page first.",
        )
    q = select(Review).where(Review.document_id == body.document_id, Review.status.in_(ACTIVE))
    if running := session.exec(q).first():
        raise ApiError(
            409,
            "REVIEW_RUNNING",
            "A review of this document is already running.",
            review_id=running.id,
        )
    r = Review(
        document_id=body.document_id,
        model=settings.llm_model,
        prompt_versions={
            k: prompts.get_active(session, k).version for k in prompts.DEFAULT_PROMPTS
        },
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    _start(request, tasks, r)
    return _out(session, r)


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: int, session: SessionDep):
    return _out(session, _get(session, review_id), with_comments=True)


@router.get("/documents/{doc_id}/reviews", response_model=list[ReviewOut])
def list_reviews(doc_id: int, session: SessionDep):
    if session.get(Document, doc_id) is None:
        raise ApiError(404, "NOT_FOUND", f"Document {doc_id} not found.")
    q = select(Review).where(Review.document_id == doc_id).order_by(Review.created_at.desc())
    return [_out(session, r) for r in session.exec(q).all()]


@router.post("/reviews/{review_id}/retry", status_code=202, response_model=ReviewOut)
def retry_review(review_id: int, request: Request, session: SessionDep, tasks: BackgroundTasks):
    r = _get(session, review_id)
    if r.status in ACTIVE:
        raise ApiError(409, "REVIEW_RUNNING", "This review is still running.")
    if r.status == "done":
        raise ApiError(409, "NOTHING_TO_RETRY", "This review finished without errors.")
    only = (
        [e["section_id"] for e in r.errors if e.get("section_id")]
        if r.status == "partial"
        else None
    )
    r.status, r.stage = "queued", ""
    session.commit()
    session.refresh(r)
    _start(request, tasks, r, only or None)
    return _out(session, r)


def _finished(session: Session, review_id: int) -> Review:
    r = _get(session, review_id)
    if r.status in ACTIVE:
        raise ApiError(409, "REVIEW_RUNNING", "Wait for the review to finish.")
    return r


@router.post("/reviews/{review_id}/overall", response_model=ReviewOut)
async def generate_overall(review_id: int, request: Request, session: SessionDep):
    r = _finished(session, review_id)
    cs = exported(_comments(session, r))
    if not cs:
        raise ApiError(409, "NO_CONFIRMED_COMMENTS", "Accept or edit some comments first.")
    settings = request.app.state.settings
    if not settings.llm_configured and request.app.state.review_models is None:
        raise ApiError(
            503,
            "LLM_NOT_CONFIGURED",
            "Add a language model and API key on the Settings page first.",
        )
    parsed = ParsedDocument(**session.get(Document, r.document_id).parsed)
    lang = parsed.language if settings.output_language == "auto" else settings.output_language
    heading = {sec.id: sec.heading for sec in parsed.sections}  # the student sees headings, not IDs
    listing = "\n".join(
        f"- [{c.severity}/{c.category}] {heading.get(c.section_id, 'whole document')}: "
        f"{final_text(c, lang)}"
        for c in cs
    )
    summary = StructuredSummary(**r.summary) if r.summary else None
    msgs = prompts.render(
        session,
        "overall_feedback",
        comments=listing,
        summary=summary_text(summary),
        doc_type=parsed.doc_type,
        language=LANGUAGES[lang],
    )
    try:
        reply = await _models(request).chat.ainvoke(msgs)
    except Exception as e:
        raise ApiError(502, "LLM_FAILED", f"The model call failed: {e}") from e
    r.overall_feedback = str(reply.content).strip()
    session.commit()
    session.refresh(r)
    return _out(session, r)


@router.put("/reviews/{review_id}/overall", response_model=ReviewOut)
def save_overall(review_id: int, body: OverallText, session: SessionDep):
    r = _get(session, review_id)
    r.overall_feedback = body.text.strip() or None
    session.commit()
    session.refresh(r)
    return _out(session, r)


@router.get("/reviews/{review_id}/export")
def export_review(
    review_id: int, request: Request, session: SessionDep, format: Literal["md", "docx"] = "md"
):
    r = _finished(session, review_id)
    doc = session.get(Document, r.document_id)
    parsed = ParsedDocument(**doc.parsed)
    cs = _comments(session, r)
    name = f"{Path(doc.filename).stem}-review.{format}"
    if format == "md":
        body = to_markdown(r, doc.filename, parsed, cs).encode()
        media = "text/markdown; charset=utf-8"
    else:
        uploads = request.app.state.settings.data_dir / "uploads"
        original = uploads / doc.stored_name
        body = to_docx(
            r,
            doc.filename,
            parsed,
            cs,
            original=original if original.suffix == ".docx" and original.exists() else None,
            figures_dir=uploads / Path(doc.stored_name).stem / "figures",
        )
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    disposition = f"attachment; filename=\"review.{format}\"; filename*=UTF-8''{quote(name)}"
    return Response(body, media_type=media, headers={"Content-Disposition": disposition})
