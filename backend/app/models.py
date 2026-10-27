from datetime import UTC, datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class Document(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str
    sha256: str = Field(index=True, unique=True)
    stored_name: str  # "{uuid}{ext}" inside DATA_DIR/uploads; figures in "{uuid}/figures/"
    doc_type: str
    parsed: dict = Field(sa_column=Column(JSON, nullable=False))  # ParsedDocument JSON
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
