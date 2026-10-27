from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def client(**overrides) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, **overrides)))


def test_health_reports_llm_not_configured():
    r = client(llm_api_key="").get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "llm_configured": False}


def test_health_reports_llm_configured():
    r = client(llm_api_key="sk-test").get("/api/health")
    assert r.json()["llm_configured"] is True


def test_cors_allows_vite_dev_origin():
    r = client().get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_other_origins():
    r = client().get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
