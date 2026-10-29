import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal[
    "openai_compatible", "openrouter", "groq", "anthropic", "fake"
]  # fake: E2E tests


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Provider = "openai_compatible"
    llm_base_url: str = ""  # empty = the provider's default URL (see llm.PROVIDER_URLS)
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_timeout_s: int = 120
    llm_max_retries: int = 2
    llm_context_tokens: int = 32000
    llm_structured_method: Literal["function_calling", "json_mode", "json_schema"] = (
        "function_calling"
    )

    embedding_provider: Literal["openai_compatible", "huggingface"] = "openai_compatible"
    embedding_model: str = "text-embedding-v3"
    embedding_base_url: str = ""
    embedding_api_key: str = ""

    data_dir: Path = Path("./data")
    max_upload_mb: int = 20
    output_language: Literal["auto", "zh", "en"] = "auto"
    cors_origins: list[str] = ["http://localhost:5173"]

    vision_model: str = ""  # empty = figures are not analysed by a vision model
    vision_provider: Provider | None = None  # None/empty fields = reuse the LLM_* connection
    vision_base_url: str = ""
    vision_api_key: str = ""
    max_figures_per_doc: int = 40

    # Sections each doc type must have (format check). Each inner list = alternative keywords.
    required_sections: dict[str, list[list[str]]] = {
        "proposal": [
            ["背景", "background", "introduction", "引言"],
            ["目标", "objective", "aim", "goal"],
            ["方案", "approach", "method", "技术路线"],
            ["可行性", "feasibility"],
            ["计划", "plan", "schedule", "进度"],
            ["风险", "risk"],
        ],
        "report": [
            ["背景", "引言", "introduction", "background"],
            ["方法", "方案", "approach", "method"],
            ["结果", "成果", "result"],
            ["结论", "总结", "conclusion"],
        ],
        "technical": [],
    }

    @field_validator("vision_provider", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return v or None  # "VISION_PROVIDER=" in .env means "same as LLM_PROVIDER"

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider == "fake" or bool(self.llm_api_key)

    @property
    def embeddings_configured(self) -> bool:
        # without its own URL or key the OpenAI-compatible client would call OpenAI with LLM_API_KEY
        return self.embedding_provider == "huggingface" or bool(
            self.embedding_base_url or self.embedding_api_key
        )


# Fields the Settings page may change. Saved values win over .env.
EDITABLE = (
    "llm_provider", "llm_base_url", "llm_model", "llm_api_key",
    "vision_provider", "vision_base_url", "vision_model", "vision_api_key",
    "embedding_provider", "embedding_base_url", "embedding_model", "embedding_api_key",
)  # fmt: skip
SAVED_FILE = "settings.json"


def apply_saved(s: Settings) -> Settings:
    """Overlay what the Settings page saved in DATA_DIR/settings.json; a broken file is ignored."""
    try:
        saved = json.loads((s.data_dir / SAVED_FILE).read_text("utf-8"))
        return Settings.model_validate(
            {**s.model_dump(), **{k: saved[k] for k in EDITABLE if k in saved}}
        )
    except FileNotFoundError:
        return s
    except Exception as e:  # noqa: BLE001 - never let a bad file stop the server
        logging.getLogger(__name__).warning("ignoring %s: %s", SAVED_FILE, type(e).__name__)
        return s


def save_settings(s: Settings, changes: dict) -> Settings:
    """Validate, write (owner-only file) and return the new Settings."""
    new = Settings.model_validate({**s.model_dump(), **changes})
    # ponytail: keys stored in plain text like .env, owner-only file; OS keyring if multi-user
    path = s.data_dir / SAVED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({k: getattr(new, k) for k in EDITABLE}, f, ensure_ascii=False, indent=1)
    os.chmod(path, 0o600)  # O_CREAT mode does not apply to an existing file
    return new


@lru_cache
def get_settings() -> Settings:
    return Settings()
