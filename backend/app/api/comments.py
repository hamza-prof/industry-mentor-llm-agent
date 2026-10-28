from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api import ApiError
from app.api.reviews import CommentOut, _get
from app.db import get_session
from app.models import Document, ReviewComment
from app.review import match_quote
from app.schemas import Category, ParsedDocument, Severity

router = APIRouter(prefix="/api", tags=["comments"])
SessionDep = Annotated[Session, Depends(get_session)]
Status = Literal["pending", "accepted", "edited", "rejected"]


class CommentPatch(BaseModel):
    status: Status | None = None
    mentor_text: str | None = None
    severity: Severity | None = None
    category: Category | None = None


class NewComment(BaseModel):
    section_id: str | None = None  # neither section nor paragraph = about the whole document
    paragraph_id: str | None = None
    quote: str | None = None
    category: Category = "clarity"
    severity: Severity = "medium"
    problem: str = Field(min_length=1)
    suggestion: str = ""
    revision_steps: list[str] = []


class Bulk(BaseModel):
    ids: list[int]
    status: Literal["pending", "accepted", "rejected"]  # "edited" needs text per comment


def _comment(session: Session, cid: int) -> ReviewComment:
    if (c := session.get(ReviewComment, cid)) is None:
        raise ApiError(404, "NOT_FOUND", f"Comment {cid} not found.")
    return c


def _out(c: ReviewComment) -> CommentOut:
    return CommentOut.model_validate(c, from_attributes=True)


@router.patch("/comments/{cid}", response_model=CommentOut)
def update_comment(cid: int, body: CommentPatch, session: SessionDep):
    c = _comment(session, cid)
    changes = body.model_dump(exclude_unset=True)
    if "mentor_text" in changes:
        changes["mentor_text"] = (changes["mentor_text"] or "").strip() or None
    status = changes.get("status", c.status)
    if status == "edited" and not changes.get("mentor_text", c.mentor_text):
        raise ApiError(422, "EMPTY_EDIT", "An edited comment needs the mentor's text.")
    for k, v in changes.items():
        setattr(c, k, v)
    session.commit()
    session.refresh(c)
    return _out(c)


@router.post("/reviews/{review_id}/comments", status_code=201, response_model=CommentOut)
def add_comment(review_id: int, body: NewComment, session: SessionDep):
    r = _get(session, review_id)
    parsed = ParsedDocument(**session.get(Document, r.document_id).parsed)
    section_id, quote = body.section_id, None
    if body.paragraph_id:
        if (p := parsed.paragraph(body.paragraph_id)) is None:
            raise ApiError(
                422, "BAD_ANCHOR", f"Paragraph {body.paragraph_id} is not in this document."
            )
        section_id = body.paragraph_id.split(".")[0]
        if body.quote and (quote := match_quote(body.quote, p.text)) is None:
            raise ApiError(422, "BAD_QUOTE", "The quoted text is not in that paragraph.")
    elif section_id and section_id not in {s.id for s in parsed.sections}:
        raise ApiError(422, "BAD_ANCHOR", f"Section {section_id} is not in this document.")
    c = ReviewComment(
        **body.model_dump(exclude={"section_id", "quote"}),
        review_id=review_id,
        section_id=section_id,
        quote=quote,
        anchored=body.paragraph_id is not None,
        origin="mentor",
        status="accepted",
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return _out(c)


@router.delete("/comments/{cid}", status_code=204)
def delete_comment(cid: int, session: SessionDep):
    c = _comment(session, cid)
    if c.origin != "mentor":
        raise ApiError(403, "NOT_DELETABLE", "Only your own comments can be deleted; reject it.")
    session.delete(c)
    session.commit()
    return Response(status_code=204)


@router.post("/reviews/{review_id}/comments/bulk", response_model=list[CommentOut])
def bulk_status(review_id: int, body: Bulk, session: SessionDep):
    _get(session, review_id)
    q = select(ReviewComment).where(
        ReviewComment.review_id == review_id, ReviewComment.id.in_(body.ids)
    )
    cs = list(session.exec(q).all())
    if missing := sorted(set(body.ids) - {c.id for c in cs}):
        raise ApiError(422, "UNKNOWN_COMMENTS", "Not comments of this review.", ids=missing)
    for c in cs:
        c.status = body.status
    session.commit()
    return [_out(c) for c in cs]
