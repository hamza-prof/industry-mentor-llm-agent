from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app import prompts
from app.api import ApiError
from app.api.kb import kb_store
from app.db import get_session
from app.llm import get_chat_model, get_vision_model
from app.models import Document, Review, ReviewComment
from app.runner import ReviewModels, run_review
from app.schemas import Comment, ParsedDocument, StructuredSummary

router = APIRouter(prefix="/api", tags=["reviews"])
SessionDep = Annotated[Session, Depends(get_session)]
ACTIVE = ("queued", "running")


class CreateReview(BaseModel):
    document_id: int


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
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    comment_count: int = 0
    comments: list[CommentOut] | None = None  # only on GET /reviews/{id}


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
        raise ApiError(503, "LLM_NOT_CONFIGURED", "Set LLM_API_KEY in backend/.env first.")
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
