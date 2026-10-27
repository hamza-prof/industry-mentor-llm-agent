import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_without_env(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.llm_provider == "openai_compatible"
    assert s.llm_api_key == ""
    assert s.max_upload_mb == 20


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen-plus")
    monkeypatch.setenv("MAX_UPLOAD_MB", "5")
    s = Settings(_env_file=None)
    assert s.llm_model == "qwen-plus"
    assert s.max_upload_mb == 5


def test_invalid_provider_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_llm_configured_needs_api_key():
    assert not Settings(_env_file=None, llm_api_key="").llm_configured
    assert Settings(_env_file=None, llm_api_key="sk-x").llm_configured


def test_figure_settings_defaults():
    s = Settings(_env_file=None)
    assert s.vision_model == ""
    assert s.max_figures_per_doc == 40
