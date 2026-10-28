from datetime import UTC, datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class Document(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str
    sha256: str = Field(index=True, unique=True)
    stored_name: str  # "{uuid}{ext}" inside DATA_DIR/uploads; figures in "{uuid}/figures/"
    doc_type: str
    parsed: dict = Field(sa_column=Column(JSON, nullable=False))  # ParsedDocument JSON
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromptTemplate(SQLModel, table=True):
    key: str = Field(primary_key=True)  # summary_map | summary_reduce | section_review | …
    active_version: int


class PromptVersion(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("key", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    version: int
    system: str
    user: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KBSource(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str
    sha256: str = Field(index=True, unique=True)
    stored_name: str  # "{sha256}{ext}" inside DATA_DIR/kb, kept so the KB can be re-indexed
    category: str  # standard | program_requirement | exemplar
    doc_type: str  # report | proposal | technical | any
    chunk_count: int = 0
    embedding_model: str  # model the vectors were made with; mismatch → re-index
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FigureCache(SQLModel, table=True):
    key: str = Field(primary_key=True)  # "{image_id}:{figure_describe prompt version}"
    data: dict = Field(sa_column=Column(JSON, nullable=False))  # FigureDescription JSON


class Review(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    status: str = "queued"  # queued | running | done | partial | failed
    stage: str = ""  # figures | summary | format | sections k/n | done
    model: str = ""
    prompt_versions: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    errors: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    warnings: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    summary: dict | None = Field(default=None, sa_column=Column(JSON))  # StructuredSummary
    figures_analysed: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ReviewComment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="review.id", index=True)
    section_id: str | None = None
    paragraph_id: str | None = None
    quote: str | None = None
    anchored: bool = False
    category: str
    severity: str
    problem: str
    suggestion: str = ""
    revision_steps: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    standard_refs: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    origin: str = "ai"  # ai | rule | mentor
    status: str = "pending"  # pending | accepted | edited | rejected
    mentor_text: str | None = None
