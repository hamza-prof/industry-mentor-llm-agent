from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["openai_compatible", "openrouter", "groq", "anthropic"]


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

    @field_validator("vision_provider", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return v or None  # "VISION_PROVIDER=" in .env means "same as LLM_PROVIDER"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
