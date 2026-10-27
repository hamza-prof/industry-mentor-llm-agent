"""The only place that builds LangChain chat / vision / embedding models."""

import base64

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.config import Settings

# OpenAI-compatible providers: same client, different default URL.
# openai_compatible with no URL = OpenAI itself; set LLM_BASE_URL for DeepSeek, Qwen, Ollama…
PROVIDER_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}
APP_NAME = "Industry Mentor Review Assistant"


class LLMNotConfigured(Exception):
    pass


def _build(provider: str, model: str, api_key: str, base_url: str, temperature: float, s: Settings):
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            temperature=temperature,
            timeout=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )
    from langchain_openai import ChatOpenAI

    headers = {"X-Title": APP_NAME} if provider == "openrouter" else None  # OpenRouter app ranking
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url or PROVIDER_URLS.get(provider),
        temperature=temperature,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
        default_headers=headers,
    )


def get_chat_model(s: Settings) -> BaseChatModel:
    if not s.llm_configured:
        raise LLMNotConfigured("Set LLM_API_KEY (and LLM_MODEL) in backend/.env")
    return _build(s.llm_provider, s.llm_model, s.llm_api_key, s.llm_base_url, s.llm_temperature, s)


def get_vision_model(s: Settings) -> BaseChatModel | None:
    """None when VISION_MODEL is empty → figures fall back to caption / alt text / chart data."""
    if not s.vision_model:
        return None
    provider = s.vision_provider or s.llm_provider
    same_provider = provider == s.llm_provider
    api_key = s.vision_api_key or (s.llm_api_key if same_provider else "")
    base_url = s.vision_base_url or (s.llm_base_url if same_provider else "")
    if not api_key:
        return None
    return _build(provider, s.vision_model, api_key, base_url, 0, s)


def get_embeddings(s: Settings) -> Embeddings:
    if s.embedding_provider == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as e:
            raise LLMNotConfigured("Install langchain-huggingface for local embeddings") from e
        return HuggingFaceEmbeddings(model_name=s.embedding_model)
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=s.embedding_model,
        base_url=s.embedding_base_url or None,
        api_key=s.embedding_api_key or s.llm_api_key,
        check_embedding_ctx_length=False,  # non-OpenAI endpoints reject pre-tokenised input
    )


def image_message(png: bytes, text: str) -> HumanMessage:
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    return HumanMessage(
        content=[{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]
    )


def count_tokens(text: str) -> int:
    # ponytail: ~1 token per CJK char, ~4 Latin chars per token; use tiktoken if budgets prove off
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    return round(cjk + (len(text) - cjk) / 4)
