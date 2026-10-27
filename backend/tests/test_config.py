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


@pytest.mark.parametrize("provider", ["openai_compatible", "openrouter", "groq", "anthropic"])
def test_supported_llm_providers(provider):
    assert Settings(_env_file=None, llm_provider=provider).llm_provider == provider


def test_vision_and_structured_output_defaults():
    s = Settings(_env_file=None)
    assert s.vision_provider is None and s.vision_base_url == "" and s.vision_api_key == ""
    assert s.llm_structured_method == "function_calling"
    assert s.llm_base_url == ""  # each provider brings its own default URL


def test_empty_vision_provider_in_env_means_none(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "")
    assert Settings(_env_file=None).vision_provider is None


def test_env_example_loads():
    from pathlib import Path

    s = Settings(_env_file=Path(__file__).parents[1] / ".env.example")
    assert s.llm_provider == "openai_compatible" and s.vision_provider is None
