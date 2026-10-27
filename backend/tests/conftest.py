import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import prompts
from app.config import Settings
from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    def _make(**overrides) -> TestClient:
        settings = Settings(_env_file=None, data_dir=tmp_path / "data", **overrides)
        return TestClient(create_app(settings))

    return _make


@pytest.fixture
def client(make_client):
    with make_client() as c:  # "with" runs the lifespan (DB init)
        yield c


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        prompts.seed_defaults(s)
        yield s
