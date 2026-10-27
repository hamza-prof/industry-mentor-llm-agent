from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_timeout_s: int = 120
    llm_max_retries: int = 2
    llm_context_tokens: int = 32000

    embedding_provider: Literal["openai_compatible", "huggingface"] = "openai_compatible"
    embedding_model: str = "text-embedding-v3"
    embedding_base_url: str = ""
    embedding_api_key: str = ""

    data_dir: Path = Path("./data")
    max_upload_mb: int = 20
    output_language: Literal["auto", "zh", "en"] = "auto"
    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
