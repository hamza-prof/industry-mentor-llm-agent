from sqlalchemy import inspect, text
from sqlmodel import create_engine

from app.db import init_db


def test_init_db_adds_columns_missing_from_an_older_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:  # a review table from before overall_feedback existed
        c.execute(text("CREATE TABLE review (id INTEGER PRIMARY KEY, document_id INTEGER)"))
        c.execute(text("INSERT INTO review (id, document_id) VALUES (1, 1)"))
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("review")}
    assert "overall_feedback" in cols
    with engine.connect() as c:
        assert c.execute(text("SELECT overall_feedback FROM review")).scalar() is None
