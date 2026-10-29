import json
import stat

from app.config import Settings, apply_saved


def test_get_settings_never_returns_api_keys(make_client):
    with make_client(llm_api_key="sk-secret-abcdefgh1234", llm_model="deepseek-chat") as c:
        body = c.get("/api/settings").json()
    assert "sk-secret" not in json.dumps(body)
    assert body["llm_model"] == "deepseek-chat"
    assert body["llm_api_key_set"] is True
    assert body["llm_api_key_hint"] == "1234"
    assert body["vision_api_key_set"] is False
    assert body["default_urls"]["groq"].startswith("https://")


def test_short_key_gets_no_hint(make_client):
    with make_client(llm_api_key="short") as c:
        assert c.get("/api/settings").json()["llm_api_key_hint"] == ""


def test_save_applies_without_restart(make_client):
    with make_client(llm_api_key="") as c:
        assert c.get("/api/health").json()["llm_configured"] is False
        r = c.put(
            "/api/settings",
            json={"llm_provider": "groq", "llm_model": "llama-3.3-70b", "llm_api_key": "gsk-1"},
        )
        assert r.status_code == 200
        assert r.json()["llm_provider"] == "groq"
        assert c.get("/api/health").json()["llm_configured"] is True


def test_omitted_key_is_kept_and_empty_key_clears_it(make_client):
    with make_client(llm_api_key="sk-keep-me-0000") as c:
        assert c.put("/api/settings", json={"llm_model": "m2"}).json()["llm_api_key_set"] is True
        assert c.put("/api/settings", json={"llm_api_key": ""}).json()["llm_api_key_set"] is False


def test_saved_settings_survive_restart_and_file_is_private(make_client, tmp_path):
    with make_client() as c:
        c.put("/api/settings", json={"llm_model": "qwen-plus", "llm_api_key": "sk-x"})
    path = tmp_path / "data" / "settings.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with make_client() as c:
        body = c.get("/api/settings").json()
    assert body["llm_model"] == "qwen-plus"
    assert body["llm_api_key_set"] is True


def test_unknown_provider_rejected(make_client):
    with make_client() as c:
        assert c.put("/api/settings", json={"llm_provider": "nope"}).status_code == 422


def test_empty_vision_provider_means_same_as_llm(make_client):
    with make_client() as c:
        r = c.put("/api/settings", json={"vision_provider": ""})
    assert r.json()["vision_provider"] is None


def test_changing_embeddings_drops_the_cached_store(make_client):
    with make_client() as c:
        c.app.state.kb_store = object()
        c.put("/api/settings", json={"embedding_model": "bge-m3"})
        assert c.app.state.kb_store is None


def test_apply_saved_ignores_a_broken_file(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path, llm_model="a")
    (tmp_path / "settings.json").write_text("{not json")
    assert apply_saved(s).llm_model == "a"


def test_connection_test_ok_with_fake_model(make_client):
    with make_client(llm_provider="fake") as c:
        r = c.post("/api/settings/test", json={"target": "llm"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_connection_test_reports_failure(make_client):
    with make_client(
        llm_api_key="sk-x", llm_base_url="http://127.0.0.1:9/v1", llm_max_retries=0
    ) as c:
        r = c.post("/api/settings/test", json={"target": "llm"})
    assert r.status_code == 502
    assert r.json()["code"] == "TEST_FAILED"


def test_connection_test_needs_configuration(make_client):
    with make_client(llm_api_key="") as c:
        r = c.post("/api/settings/test", json={"target": "vision"})
    assert r.status_code == 409
    assert r.json()["code"] == "NOT_CONFIGURED"
