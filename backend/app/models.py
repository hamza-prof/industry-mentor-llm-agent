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
