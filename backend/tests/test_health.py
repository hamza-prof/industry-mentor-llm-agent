def test_health_reports_llm_not_configured(make_client):
    with make_client(llm_api_key="") as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "llm_configured": False,
        "vision_configured": False,
        "kb_configured": False,
        "kb_needs_reindex": False,
    }


def test_health_reports_llm_configured(make_client):
    with make_client(llm_api_key="sk-test") as c:
        assert c.get("/api/health").json()["llm_configured"] is True


def test_cors_allows_vite_dev_origin(make_client):
    with make_client() as c:
        r = c.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_other_origins(make_client):
    with make_client() as c:
        r = c.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
