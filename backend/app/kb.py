"""Knowledge base for RAG: review standards, training-program requirements, exemplars.

Source files are parsed with the same parser as student documents, split into chunks
(each prefixed with its section heading) and stored in a local Chroma collection."""

import hashlib
from pathlib import Path
from typing import Literal

from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlmodel import Session, select

from app.config import Settings
from app.llm import get_embeddings
from app.models import KBSource
from app.parsing import SUPPORTED_EXTENSIONS, parse_file
from app.schemas import KBHit

Category = Literal["standard", "program_requirement", "exemplar"]
KBDocType = Literal["report", "proposal", "technical", "any"]
CATEGORIES: tuple[Category, ...] = ("standard", "program_requirement", "exemplar")
CHUNK_SIZE = 800
BATCH = 16  # some embedding APIs accept only 10–25 inputs per request

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""],
    keep_separator="end",
)


class DuplicateSource(Exception):
    def __init__(self, existing_id: int):
        super().__init__(f"Already in the knowledge base (source {existing_id}).")
        self.existing_id = existing_id


class KBNeedsReindex(Exception):
    pass


def get_store(settings: Settings, embeddings: Embeddings | None = None) -> Chroma:
    path = settings.data_dir / "chroma"
    return Chroma(
        collection_name="knowledge_base",  # Chroma needs ≥ 3 chars
        embedding_function=embeddings or get_embeddings(settings),
        persist_directory=str(path),
        client_settings=ChromaSettings(
            anonymized_telemetry=False, is_persistent=True, persist_directory=str(path)
        ),
    )


def split_texts(sections: list[tuple[str, str]]) -> list[str]:
    """(heading, body) pairs → chunks, each starting with its heading so it reads on its own."""
    return [
        f"{heading}\n{chunk.strip()}" if heading else chunk.strip()
        for heading, body in sections
        for chunk in _splitter.split_text(body)
        if chunk.strip()
    ]


def _chunks(path: Path, doc_type: KBDocType) -> list[str]:
    parsed = parse_file(path, "report" if doc_type == "any" else doc_type)
    return split_texts(
        [
            (s.heading if s.id != "S0" else "", "\n\n".join(p.text for p in s.paragraphs))
            for s in parsed.sections
            if any(p.kind != "figure" for p in s.paragraphs)
        ]
    )


def _index(store: Chroma, src: KBSource, chunks: list[str]) -> None:
    ids = [f"{src.id}:{i}" for i in range(len(chunks))]
    meta = {"source_id": src.id, "filename": src.filename, "category": src.category}
    try:
        for i in range(0, len(chunks), BATCH):
            store.add_texts(
                chunks[i : i + BATCH],
                metadatas=[
                    {**meta, "doc_type": src.doc_type, "chunk_id": c} for c in ids[i : i + BATCH]
                ],
                ids=ids[i : i + BATCH],
            )
    except Exception:
        store.delete(ids=ids)  # no half-indexed source
        raise


def add_source(
    session: Session,
    store: Chroma,
    settings: Settings,
    data: bytes,
    filename: str,
    category: Category,
    doc_type: KBDocType,
) -> KBSource:
    sha = hashlib.sha256(data).hexdigest()
    if existing := session.exec(select(KBSource).where(KBSource.sha256 == sha)).first():
        raise DuplicateSource(existing.id)
    kb_dir = settings.data_dir / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    stored = kb_dir / f"{sha}{Path(filename).suffix.lower()}"
    stored.write_bytes(data)
    try:
        chunks = _chunks(stored, doc_type)
        src = KBSource(
            filename=filename,
            sha256=sha,
            stored_name=stored.name,
            category=category,
            doc_type=doc_type,
            chunk_count=len(chunks),
            embedding_model=settings.embedding_model,
        )
        session.add(src)
        session.flush()  # assigns src.id for the chunk ids
        _index(store, src, chunks)
        session.commit()
    except Exception:
        session.rollback()
        stored.unlink(missing_ok=True)
        raise
    session.refresh(src)
    return src


def list_sources(session: Session) -> list[KBSource]:
    return list(session.exec(select(KBSource).order_by(KBSource.created_at.desc())).all())


def delete_source(session: Session, store: Chroma, settings: Settings, source_id: int) -> None:
    src = session.get(KBSource, source_id)
    if src is None:
        raise LookupError(source_id)
    store.delete(where={"source_id": source_id})
    (settings.data_dir / "kb" / src.stored_name).unlink(missing_ok=True)
    session.delete(src)
    session.commit()


def search(store: Chroma, query: str, category: str, doc_type: str, k: int = 4) -> list[KBHit]:
    if store._collection.count() == 0:
        return []
    where = {"$and": [{"category": category}, {"doc_type": {"$in": [doc_type, "any"]}}]}
    return [
        KBHit(
            chunk_id=d.metadata["chunk_id"],
            source_id=d.metadata["source_id"],
            filename=d.metadata["filename"],
            category=d.metadata["category"],
            text=d.page_content,
            score=score,
        )
        for d, score in store.similarity_search_with_score(query, k=k, filter=where)
    ]


def needs_reindex(session: Session, settings: Settings) -> bool:
    q = select(KBSource).where(KBSource.embedding_model != settings.embedding_model)
    return session.exec(q).first() is not None


def reindex(session: Session, store: Chroma, settings: Settings) -> int:
    """Re-embed every source with the current embedding model (vectors of another model,
    possibly of another dimension, can't be searched together)."""
    store.reset_collection()
    sources = list_sources(session)
    for src in sources:
        chunks = _chunks(settings.data_dir / "kb" / src.stored_name, src.doc_type)
        _index(store, src, chunks)
        src.chunk_count, src.embedding_model = len(chunks), settings.embedding_model
        session.add(src)
    session.commit()
    return len(sources)


def seed(session: Session, store: Chroma, settings: Settings, folder: Path) -> list[str]:
    """Add every .md/.txt/.docx/.pdf in folder; file name decides the category."""
    added = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        name = path.stem.lower()
        category: Category = (
            "program_requirement"
            if "program" in name or "培养" in name
            else "exemplar"
            if "exemplar" in name or "范例" in name
            else "standard"
        )
        try:
            add_source(session, store, settings, path.read_bytes(), path.name, category, "any")
            added.append(f"{path.name} → {category}")
        except DuplicateSource:
            added.append(f"{path.name} (already added)")
    return added


if __name__ == "__main__":  # uv run python -m app.kb seed ../docs/samples/kb
    import sys

    from sqlmodel import Session as S

    from app.config import get_settings
    from app.db import init_db, make_engine

    s = get_settings()
    engine = make_engine(s)
    init_db(engine)
    with S(engine) as session:
        for line in seed(session, get_store(s), s, Path(sys.argv[2])):
            print(line)
