from app.prompts import DEFAULT_PROMPTS


def test_list_prompts(client):
    body = client.get("/api/prompts").json()
    assert {p["key"] for p in body} == set(DEFAULT_PROMPTS)
    sr = next(p for p in body if p["key"] == "section_review")
    assert sr["active_version"] == 1
    assert "section" in sr["required"] and "summary" in sr["optional"]
    assert sr["description"]


def test_get_one_and_unknown(client):
    body = client.get("/api/prompts/summary_map").json()
    assert body["user"] == DEFAULT_PROMPTS["summary_map"].user
    r = client.get("/api/prompts/nope")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_put_valid_creates_version(client):
    r = client.put("/api/prompts/summary_map", json={"system": "S", "user": "Sum {section}"})
    assert r.status_code == 200 and r.json()["active_version"] == 2
    assert client.get("/api/prompts/summary_map").json()["user"] == "Sum {section}"


def test_put_invalid_returns_details(client):
    r = client.put("/api/prompts/section_review", json={"system": "", "user": "{section} {oops}"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "PROMPT_INVALID"
    assert body["missing"] == ["exemplars", "requirements", "standards"]
    assert body["unknown"] == ["oops"]
    assert "{standards}" in body["detail"] and "{oops}" in body["detail"]


def test_reset_and_versions(client):
    client.put("/api/prompts/summary_map", json={"system": "S", "user": "Sum {section}"})
    assert client.post("/api/prompts/summary_map/reset").json()["active_version"] == 3
    versions = client.get("/api/prompts/summary_map/versions").json()
    assert [v["version"] for v in versions] == [3, 2, 1]


def test_activate_version(client):
    client.put("/api/prompts/summary_map", json={"system": "S", "user": "Sum {section}"})
    r = client.post("/api/prompts/summary_map/activate/1")
    assert r.status_code == 200 and r.json()["active_version"] == 1
    assert client.post("/api/prompts/summary_map/activate/9").status_code == 404


def test_health_reports_vision(make_client):
    with make_client(llm_api_key="k", vision_model="v") as c:
        assert c.get("/api/health").json() == {
            "status": "ok",
            "llm_configured": True,
            "vision_configured": True,
        }
