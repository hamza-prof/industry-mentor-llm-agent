import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app import kb
from app.api import ApiError
from app.api.documents import read_upload
from app.db import get_session
from app.parsing import ParseError
from app.schemas import KBHit

router = APIRouter(prefix="/api/kb", tags=["knowledge base"])
SessionDep = Annotated[Session, Depends(get_session)]


class SourceOut(BaseModel):
    id: int
    filename: str
    category: str
    doc_type: str
    chunk_count: int
    embedding_model: str
    created_at: datetime


def kb_store(app):
    """The app's Chroma store, built on first use; None when embeddings aren't configured."""
    settings = app.state.settings
    if app.state.kb_store is None and settings.embeddings_configured:
        app.state.kb_store = kb.get_store(settings)
    return app.state.kb_store


def _store(request: Request):
    if (store := kb_store(request.app)) is None:
        raise ApiError(
            503,
            "KB_NOT_CONFIGURED",
            "Set EMBEDDING_MODEL and EMBEDDING_BASE_URL (or EMBEDDING_API_KEY) in backend/.env "
            "to use the knowledge base.",
        )
    return store


@router.post("/sources", status_code=201, response_model=SourceOut)
async def add_source(
    request: Request,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    category: Annotated[kb.Category, Form()],
    doc_type: Annotated[kb.KBDocType, Form()] = "any",
):
    settings = request.app.state.settings
    store = _store(request)
    filename, data = await read_upload(file, settings.max_upload_mb)
    try:
        return await asyncio.to_thread(
            kb.add_source, session, store, settings, data, filename, category, doc_type
        )
    except kb.DuplicateSource as e:
        raise ApiError(409, "DUPLICATE_SOURCE", str(e), existing_id=e.existing_id) from e
    except ParseError as e:
        raise ApiError(415 if e.code == "UNSUPPORTED_FILE_TYPE" else 422, e.code, e.detail) from e
    except Exception as e:  # embedding API errors: nothing was stored (add_source cleans up)
        raise ApiError(502, "EMBEDDING_FAILED", f"Could not embed the file: {e}"[:300]) from e


@router.get("/sources", response_model=list[SourceOut])
def list_sources(session: SessionDep):
    return kb.list_sources(session)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, request: Request, session: SessionDep):
    try:
        kb.delete_source(session, _store(request), request.app.state.settings, source_id)
    except LookupError as e:
        raise ApiError(404, "NOT_FOUND", f"Source {source_id} not found.") from e
    return Response(status_code=204)


@router.get("/search", response_model=list[KBHit])
async def search(
    request: Request,
    session: SessionDep,
    q: str,
    category: kb.Category,
    doc_type: kb.KBDocType = "any",
    k: int = 4,
):
    store = _store(request)
    if kb.needs_reindex(session, request.app.state.settings):
        raise ApiError(409, "KB_NEEDS_REINDEX", "The embedding model changed; re-index first.")
    return await asyncio.to_thread(kb.search, store, q, category, doc_type, min(max(k, 1), 20))


@router.post("/reindex")
async def reindex(request: Request, session: SessionDep) -> dict:
    store = _store(request)
    n = await asyncio.to_thread(kb.reindex, session, store, request.app.state.settings)
    return {"reindexed": n}
