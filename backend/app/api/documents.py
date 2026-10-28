import hashlib
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import Session, select

from app.api import ApiError
from app.db import get_session
from app.models import Document, Review, ReviewComment
from app.parsing import SUPPORTED_EXTENSIONS, ParseError, parse_file
from app.schemas import DocType, ParsedDocument

router = APIRouter(prefix="/api/documents", tags=["documents"])
SessionDep = Annotated[Session, Depends(get_session)]
_IMAGE_ID = re.compile(r"^[0-9a-f]{32}$")
_CHUNK = 1024 * 1024


class DocumentOut(ParsedDocument):
    id: int
    created_at: datetime
    duplicate: bool = False


class DocumentSummary(BaseModel):
    id: int
    filename: str
    doc_type: str
    language: str
    created_at: datetime
    section_count: int
    figure_count: int


def _out(doc: Document, duplicate: bool = False) -> DocumentOut:
    fields = {**doc.parsed, "filename": doc.filename}  # parsed.filename is the UUID name on disk
    return DocumentOut(**fields, id=doc.id, created_at=doc.created_at, duplicate=duplicate)


def _uploads(request: Request) -> Path:
    return request.app.state.settings.data_dir / "uploads"


def _get(session: Session, doc_id: int) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise ApiError(404, "NOT_FOUND", f"Document {doc_id} not found.")
    return doc


def _check_magic(ext: str, head: bytes) -> None:
    ok = {
        ".docx": head.startswith(b"PK\x03\x04"),
        ".pdf": b"%PDF" in head[:1024],
        ".txt": b"\x00" not in head,
        ".md": b"\x00" not in head,
    }[ext]
    if not ok:
        raise ApiError(415, "FILE_TYPE_MISMATCH", f"The file content is not a valid {ext} file.")


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while chunk := await file.read(_CHUNK):
        data += chunk
        if len(data) > max_bytes:
            raise ApiError(413, "FILE_TOO_LARGE", f"File is larger than {max_bytes // _CHUNK} MB.")
    return bytes(data)


async def read_upload(file: UploadFile, max_mb: int) -> tuple[str, bytes]:
    """Safe filename + bytes, or ApiError (415 type, 413 size, 422 empty)."""
    # Browsers may send Windows paths; never trust the client's path.
    filename = PureWindowsPath(PurePosixPath(file.filename or "upload").name).name
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ApiError(
            415,
            "UNSUPPORTED_FILE_TYPE",
            f"'{ext or filename}' is not supported. Use {', '.join(SUPPORTED_EXTENSIONS)}.",
        )
    data = await _read_limited(file, max_mb * _CHUNK)
    if not data.strip():
        raise ApiError(422, "EMPTY_DOCUMENT", "The file is empty.")
    _check_magic(ext, data[:8192])
    return filename, data


@router.post("", status_code=201, response_model=DocumentOut)
async def upload_document(
    request: Request,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[DocType, Form()],
):
    settings = request.app.state.settings
    filename, data = await read_upload(file, settings.max_upload_mb)
    ext = Path(filename).suffix.lower()

    sha = hashlib.sha256(data).hexdigest()
    if existing := session.exec(select(Document).where(Document.sha256 == sha)).first():
        return JSONResponse(_out(existing, duplicate=True).model_dump(mode="json"), status_code=200)

    uploads = _uploads(request)
    uploads.mkdir(parents=True, exist_ok=True)
    key = uuid.uuid4().hex
    stored = uploads / f"{key}{ext}"
    stored.write_bytes(data)
    try:
        parsed = parse_file(
            stored,
            doc_type=doc_type,
            figures_dir=uploads / key / "figures",
            max_figures=settings.max_figures_per_doc,
            allow_figures_only=bool(settings.vision_model),
        )
    except ParseError as e:
        stored.unlink(missing_ok=True)
        shutil.rmtree(uploads / key, ignore_errors=True)
        status = 415 if e.code == "UNSUPPORTED_FILE_TYPE" else 422
        raise ApiError(status, e.code, e.detail) from e

    doc = Document(
        filename=filename,
        sha256=sha,
        stored_name=stored.name,
        doc_type=doc_type,
        parsed=parsed.model_dump(mode="json", exclude={"figure_count", "char_count"}),
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return _out(doc)


@router.get("", response_model=list[DocumentSummary])
def list_documents(session: SessionDep):
    docs = session.exec(select(Document).order_by(Document.created_at.desc())).all()
    out = []
    for d in docs:
        parsed = ParsedDocument(**d.parsed)
        out.append(
            DocumentSummary(
                id=d.id,
                filename=d.filename,
                doc_type=d.doc_type,
                language=parsed.language,
                created_at=d.created_at,
                section_count=len(parsed.sections),
                figure_count=parsed.figure_count,
            )
        )
    return out


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, session: SessionDep):
    return _out(_get(session, doc_id))


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, request: Request, session: SessionDep):
    doc = _get(session, doc_id)
    uploads = _uploads(request)
    (uploads / doc.stored_name).unlink(missing_ok=True)
    shutil.rmtree(uploads / Path(doc.stored_name).stem, ignore_errors=True)
    review_ids = select(Review.id).where(Review.document_id == doc_id)
    session.execute(delete(ReviewComment).where(ReviewComment.review_id.in_(review_ids)))
    session.execute(delete(Review).where(Review.document_id == doc_id))
    session.delete(doc)
    session.commit()
    return Response(status_code=204)


@router.get("/{doc_id}/figures/{image_id}")
def get_figure(doc_id: int, image_id: str, request: Request, session: SessionDep):
    doc = _get(session, doc_id)
    path = _uploads(request) / Path(doc.stored_name).stem / "figures" / f"{image_id}.png"
    if not _IMAGE_ID.match(image_id) or not path.is_file():
        raise ApiError(404, "NOT_FOUND", "Figure not found.")
    return FileResponse(path, media_type="image/png")
