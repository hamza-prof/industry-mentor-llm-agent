import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from app import kb

RUBRIC = (
    b"# Rubric\n\n## Evidence\nEvery claim needs data.\n\n## Feasibility\nPlans must fit the time."
)


@pytest.fixture
def kc(make_client):
    with make_client(embedding_base_url="http://local") as c:
        c.app.state.kb_store = kb.get_store(
            c.app.state.settings, DeterministicFakeEmbedding(size=16)
        )
        yield c


def add(c, data=RUBRIC, name="rubric.md", category="standard", doc_type="any"):
    return c.post(
        "/api/kb/sources",
        files={"file": (name, data)},
        data={"category": category, "doc_type": doc_type},
    )


def test_add_list_search_delete(kc):
    r = add(kc)
    assert r.status_code == 201
    src = r.json()
    assert src["chunk_count"] >= 2 and src["category"] == "standard"
    assert [s["id"] for s in kc.get("/api/kb/sources").json()] == [src["id"]]
    hits = kc.get("/api/kb/search", params={"q": "evidence", "category": "standard"}).json()
    assert hits and all(h["filename"] == "rubric.md" for h in hits)
    assert kc.delete(f"/api/kb/sources/{src['id']}").status_code == 204
    assert kc.get("/api/kb/sources").json() == []
    assert kc.delete(f"/api/kb/sources/{src['id']}").status_code == 404


def test_duplicate_409(kc):
    first = add(kc).json()
    r = add(kc, name="copy.md")
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_SOURCE"
    assert r.json()["existing_id"] == first["id"]


def test_bad_inputs(kc):
    assert add(kc, name="x.exe").status_code == 415
    assert add(kc, data=b"   ").status_code == 422
    assert add(kc, category="opinion").status_code == 422
    assert add(kc, doc_type="poem").status_code == 422


def test_not_configured_503(make_client):
    with make_client() as c:  # no EMBEDDING_BASE_URL / KEY
        r = add(c)
        assert r.status_code == 503 and r.json()["code"] == "KB_NOT_CONFIGURED"
        assert c.get("/api/health").json()["kb_configured"] is False


def test_reindex_after_model_change(kc):
    add(kc)
    settings = kc.app.state.settings
    kc.app.state.settings = settings.model_copy(update={"embedding_model": "other"})
    assert kc.get("/api/health").json()["kb_needs_reindex"] is True
    r = kc.get("/api/kb/search", params={"q": "x", "category": "standard"})
    assert r.status_code == 409 and r.json()["code"] == "KB_NEEDS_REINDEX"
    assert kc.post("/api/kb/reindex").json() == {"reindexed": 1}
    assert kc.get("/api/health").json()["kb_needs_reindex"] is False
