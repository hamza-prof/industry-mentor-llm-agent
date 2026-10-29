"""The only place that builds LangChain chat / vision / embedding models."""

import base64
import logging
import re
import time

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from app.config import Settings

# OpenAI-compatible providers: same client, different default URL.
# openai_compatible with no URL = OpenAI itself; set LLM_BASE_URL for DeepSeek, Qwen, Ollama…
PROVIDER_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}
APP_NAME = "Industry Mentor Review Assistant"


log = logging.getLogger(__name__)


class LLMNotConfigured(Exception):
    pass


class UsageLog(BaseCallbackHandler):
    """One log line per model call: model, tokens, time. Never the student's text."""

    def __init__(self):
        self.started: dict = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        model = (serialized or {}).get("kwargs", {}).get("model_name") or (serialized or {}).get(
            "kwargs", {}
        ).get("model", "?")
        self.started[run_id] = (model, time.perf_counter())

    def on_llm_end(self, response, *, run_id, **kw):
        model, t0 = self.started.pop(run_id, ("?", time.perf_counter()))
        usage = {}
        for gens in response.generations:
            for g in gens:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None) or usage
        log.info(
            "llm model=%s in=%s out=%s ms=%d",
            model,
            usage.get("input_tokens", "?"),
            usage.get("output_tokens", "?"),
            (time.perf_counter() - t0) * 1000,
        )

    def on_llm_error(self, error, *, run_id, **kw):
        model, t0 = self.started.pop(run_id, ("?", time.perf_counter()))
        ms = (time.perf_counter() - t0) * 1000
        log.warning("llm model=%s failed=%s ms=%d", model, type(error).__name__, ms)


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
            callbacks=[UsageLog()],
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
        callbacks=[UsageLog()],
    )


class FakeChatModel:
    """LLM_PROVIDER=fake: canned, deterministic answers so browser E2E tests run free."""

    _PARA = re.compile(r"\[(S\d+\.P\d+)\] (.+)")

    def _first(self, msgs: list[BaseMessage]) -> tuple[str, str]:
        text = "\n".join(m.text for m in msgs if m.type == "human")
        m = self._PARA.search(text)
        return (m[1], m[2]) if m else ("S1.P1", "")

    async def ainvoke(self, msgs: list[BaseMessage], *_, **__) -> AIMessage:
        return AIMessage("The material is clear; strengthen the evidence behind its results.")

    def with_structured_output(self, schema, **_):
        from app.schemas import RawComment, SectionReview, SummaryField, SummaryOutput

        def answer(msgs):
            pid, text = self._first(msgs)
            if schema is SectionReview:
                quote = text[:30]
                problem = f"This claim needs supporting data: “{quote}”"
                return SectionReview(
                    comments=[
                        RawComment(
                            paragraph_id=pid,
                            quote=quote,
                            category="evidence",
                            severity="high",
                            problem=problem,
                            suggestion="Add the measurement that supports it.",
                            revision_steps=["Find the data", "Cite it next to the claim"],
                        )
                    ]
                )
            if schema is SummaryOutput:
                field = SummaryField(text=text or "Not stated.", source_ids=[pid])
                names = SummaryOutput.model_fields.keys() - {"outline"}
                return SummaryOutput(**{name: field for name in names})
            raise NotImplementedError(schema)

        async def run(msgs):
            return answer(msgs)

        return RunnableLambda(run)


def get_chat_model(s: Settings) -> BaseChatModel:
    if s.llm_provider == "fake":
        return FakeChatModel()  # type: ignore[return-value]
    if not s.llm_configured:
        raise LLMNotConfigured("Set LLM_API_KEY (and LLM_MODEL) in backend/.env")
    return _build(s.llm_provider, s.llm_model, s.llm_api_key, s.llm_base_url, s.llm_temperature, s)


def get_vision_model(s: Settings) -> BaseChatModel | None:
    """None when VISION_MODEL is empty → figures fall back to caption / alt text / chart data."""
    if not s.vision_model or s.llm_provider == "fake":
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
