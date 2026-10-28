from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings


def make_engine(settings: Settings) -> Engine:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{settings.data_dir / 'app.db'}", connect_args={"check_same_thread": False}
    )


def init_db(engine: Engine) -> None:
    import app.models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """New nullable columns on an existing database (create_all only creates missing tables)."""
    # ponytail: add-column only; renames/drops/NOT NULL columns would need Alembic
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    kind = col.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {kind}'))


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
