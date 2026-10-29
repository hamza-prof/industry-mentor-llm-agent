import copy

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlmodel import Session

from app import kb
from app.models import Review
from app.runner import ReviewModels
from tests.test_runner import FakeChat

DOC = """# Report

## 1 Approach
We moved the order system to microservices. The system is much better now.

## 2 Results
Deploys take 6 minutes. Users are happier.
"""


def upload(client, text=DOC, name="r.md", doc_type="report"):
    r = client.post(
        "/api/documents", files={"file": (name, text.encode())}, data={"doc_type": doc_type}
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


@pytest.fixture
def app_client(make_client):
    with make_client(llm_api_key="k") as c:
        c.app.state.review_models = ReviewModels(chat=FakeChat())
        yield c


def test_create_runs_review_and_returns_comments(app_client):
    doc_id = upload(app_client)
    r = app_client.post("/api/reviews", json={"document_id": doc_id})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert set(r.json()["prompt_versions"]) == {
        "summary_map",
        "summary_reduce",
        "section_review",
        "overall_feedback",
        "figure_describe",
    }
    got = app_client.get(f"/api/reviews/{r.json()['id']}").json()  # background task already ran
    assert got["status"] == "done" and got["summary"]["research_problem"]["text"]
    ids = [c["paragraph_id"] for c in got["comments"] if c["origin"] == "ai"]
    assert ids == ["S1.P1", "S2.P1"]  # document order
    assert all(c["status"] == "pending" and c["id"] for c in got["comments"])
    assert any(w.startswith("KB_UNAVAILABLE") for w in got["warnings"])


def test_list_reviews_of_document(app_client):
    doc_id = upload(app_client)
    app_client.post("/api/reviews", json={"document_id": doc_id})
    body = app_client.get(f"/api/documents/{doc_id}/reviews").json()
    assert len(body) == 1 and body[0]["comments"] is None and body[0]["comment_count"] >= 2
    assert app_client.get("/api/documents/999/reviews").status_code == 404


def test_unknown_document_404(app_client):
    r = app_client.post("/api/reviews", json={"document_id": 999})
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_llm_not_configured_503(make_client):
    with make_client(llm_api_key="") as c:
        doc_id = upload(c)
        r = c.post("/api/reviews", json={"document_id": doc_id})
        assert r.status_code == 503 and r.json()["code"] == "LLM_NOT_CONFIGURED"


def set_status(client, review_id, status, errors=None):
    with Session(client.app.state.engine) as s:
        r = s.get(Review, review_id)
        r.status = status
        if errors is not None:
            r.errors = errors
        s.commit()


def test_second_review_while_running_409(app_client):
    doc_id = upload(app_client)
    rid = app_client.post("/api/reviews", json={"document_id": doc_id}).json()["id"]
    set_status(app_client, rid, "running")
    r = app_client.post("/api/reviews", json={"document_id": doc_id})
    assert (
        r.status_code == 409
        and r.json()["code"] == "REVIEW_RUNNING"
        and r.json()["review_id"] == rid
    )


def test_retry_rules(app_client):
    doc_id = upload(app_client)
    rid = app_client.post("/api/reviews", json={"document_id": doc_id}).json()["id"]
    r = app_client.post(f"/api/reviews/{rid}/retry")
    assert r.status_code == 409 and r.json()["code"] == "NOTHING_TO_RETRY"
    set_status(app_client, rid, "running")
    assert app_client.post(f"/api/reviews/{rid}/retry").json()["code"] == "REVIEW_RUNNING"
    assert app_client.post("/api/reviews/999/retry").status_code == 404


def test_retry_partial_reruns_failed_sections(app_client):
    doc_id = upload(app_client)
    app_client.app.state.review_models = ReviewModels(chat=FakeChat(fail_sections={"S2"}))
    rid = app_client.post("/api/reviews", json={"document_id": doc_id}).json()["id"]
    assert app_client.get(f"/api/reviews/{rid}").json()["status"] == "partial"
    chat = FakeChat()
    app_client.app.state.review_models = ReviewModels(chat=chat)
    assert app_client.post(f"/api/reviews/{rid}/retry").status_code == 202
    got = app_client.get(f"/api/reviews/{rid}").json()
    assert got["status"] == "done" and chat.reviewed == ["S2"]


def test_retry_failed_reruns_everything(app_client):
    doc_id = upload(app_client)
    app_client.app.state.review_models = ReviewModels(chat=FakeChat(fail_summary=True))
    rid = app_client.post("/api/reviews", json={"document_id": doc_id}).json()["id"]
    assert app_client.get(f"/api/reviews/{rid}").json()["status"] == "failed"
    app_client.app.state.review_models = ReviewModels(chat=FakeChat())
    app_client.post(f"/api/reviews/{rid}/retry")
    assert app_client.get(f"/api/reviews/{rid}").json()["status"] == "done"


def test_deleting_document_removes_reviews(app_client):
    doc_id = upload(app_client)
    rid = app_client.post("/api/reviews", json={"document_id": doc_id}).json()["id"]
    assert app_client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert app_client.get(f"/api/reviews/{rid}").status_code == 404


def test_startup_marks_stuck_reviews_failed(make_client):
    with make_client(llm_api_key="k") as c:
        c.app.state.review_models = ReviewModels(chat=FakeChat())
        rid = c.post("/api/reviews", json={"document_id": upload(c)}).json()["id"]
        set_status(c, rid, "running")
    with make_client(llm_api_key="k") as c:  # same data dir → "restart"
        got = c.get(f"/api/reviews/{rid}").json()
        assert got["status"] == "failed" and "restarted" in got["errors"][0]["error"]


def test_review_uses_kb(app_client, tmp_path):
    settings = app_client.app.state.settings
    app_client.app.state.kb_store = store = kb.get_store(
        settings, DeterministicFakeEmbedding(size=16)
    )
    app_client.app.state.review_models = ReviewModels(chat=FakeChat(), store=store)
    r = app_client.post(
        "/api/kb/sources",
        files={"file": ("rubric.md", b"# Rubric\n\n## Evidence\nEvery claim needs data.")},
        data={"category": "standard"},
    )
    assert r.status_code == 201
    rid = app_client.post("/api/reviews", json={"document_id": upload(app_client)}).json()["id"]
    got = app_client.get(f"/api/reviews/{rid}").json()
    assert got["status"] == "done" and not any(w.startswith("KB_") for w in got["warnings"])


def test_document_list_shows_latest_review(app_client):
    doc_id = upload(app_client)
    [d] = app_client.get("/api/documents").json()
    assert d["latest_review"] is None
    rid = app_client.post("/api/reviews", json={"document_id": doc_id}).json()["id"]
    [d] = app_client.get("/api/documents").json()
    assert d["latest_review"]["id"] == rid and d["latest_review"]["status"] == "done"


def test_review_returns_figure_descriptions_from_cache(app_client):
    from app.models import FigureCache

    rid = app_client.post("/api/reviews", json={"document_id": upload(app_client)}).json()["id"]
    with Session(app_client.app.state.engine) as s:
        version = s.get(Review, rid).prompt_versions["figure_describe"]
        s.add(FigureCache(key=f"{'a' * 32}:{version}", data={"kind": "chart", "summary": "Bars"}))
        s.commit()
    got = app_client.get(f"/api/reviews/{rid}").json()
    assert got["figures"] == {}  # the document has no figure with that id
    with Session(app_client.app.state.engine) as s:
        doc = s.get(Review, rid).document_id
        from app.models import Document

        d = s.get(Document, doc)
        parsed = copy.deepcopy(d.parsed)  # in-place edits of the JSON are not detected
        fig = {"image_id": "a" * 32, "source": "embedded", "caption": "Fig 1"}
        parsed["sections"][0]["paragraphs"].append(
            {"id": "S1.P9", "text": "[Figure] Fig 1", "kind": "figure", "figure": fig}
        )
        d.parsed = parsed
        s.add(d)
        s.commit()
    got = app_client.get(f"/api/reviews/{rid}").json()
    assert got["figures"]["a" * 32]["summary"] == "Bars"
