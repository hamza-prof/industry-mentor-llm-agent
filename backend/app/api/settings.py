import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api import ApiError
from app.config import Provider, Settings, save_settings
from app.llm import PROVIDER_URLS, get_chat_model, get_embeddings, get_vision_model

router = APIRouter(prefix="/api/settings", tags=["settings"])
KEYS = ("llm_api_key", "vision_api_key", "embedding_api_key")
TEST_TIMEOUT_S = 45


class SettingsOut(BaseModel):
    llm_provider: str
    llm_base_url: str
    llm_model: str
    vision_provider: str | None
    vision_base_url: str
    vision_model: str
    embedding_provider: str
    embedding_base_url: str
    embedding_model: str
    llm_api_key_set: bool
    llm_api_key_hint: str
    vision_api_key_set: bool
    vision_api_key_hint: str
    embedding_api_key_set: bool
    embedding_api_key_hint: str
    default_urls: dict[str, str]


class SettingsIn(BaseModel):
    """Omitted field = unchanged. For API keys: omitted = keep, "" = remove."""

    llm_provider: Provider | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    vision_provider: Provider | Literal[""] | None = None
    vision_base_url: str | None = None
    vision_model: str | None = None
    vision_api_key: str | None = None
    embedding_provider: Literal["openai_compatible", "huggingface"] | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None


class TestIn(BaseModel):
    target: Literal["llm", "vision", "embeddings"]


def _out(s: Settings) -> SettingsOut:
    keys = {}
    for k in KEYS:
        v = getattr(s, k)
        keys[f"{k}_set"] = bool(v)
        keys[f"{k}_hint"] = v[-4:] if len(v) >= 12 else ""  # never the key itself
    return SettingsOut(
        **s.model_dump(include=set(SettingsOut.model_fields)), **keys, default_urls=PROVIDER_URLS
    )


@router.get("", response_model=SettingsOut)
def read(request: Request):
    return _out(request.app.state.settings)


@router.put("", response_model=SettingsOut)
def update(body: SettingsIn, request: Request):
    changes = body.model_dump(exclude_unset=True)
    changes = {k: v.strip() if isinstance(v, str) else v for k, v in changes.items()}
    if changes.get("vision_provider") == "":
        changes["vision_provider"] = None
    for k in ("llm_provider", "llm_model", "embedding_provider", "embedding_model"):
        if k in changes and not changes[k]:
            changes.pop(k)  # these have no "empty" meaning; keep the current value
    app = request.app
    app.state.settings = save_settings(app.state.settings, changes)
    app.state.kb_store = None  # rebuilt with the new embeddings on next use
    return _out(app.state.settings)


@router.post("/test")
async def test_connection(body: TestIn, request: Request):
    s: Settings = request.app.state.settings
    if body.target == "embeddings":
        if not s.embeddings_configured:
            raise ApiError(409, "NOT_CONFIGURED", "Set the embeddings URL or API key first.")
        call = asyncio.to_thread(get_embeddings(s).embed_query, "connection test")
    else:
        model = get_chat_model(s) if s.llm_configured and body.target == "llm" else None
        if body.target == "vision":
            model = get_vision_model(s)
        if model is None:
            raise ApiError(409, "NOT_CONFIGURED", "Add a model and API key first.")
        call = model.ainvoke("Reply with the single word OK.")
    try:
        await asyncio.wait_for(call, TEST_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - any provider error is the answer the mentor needs
        detail = str(e).strip() or type(e).__name__
        raise ApiError(502, "TEST_FAILED", f"The connection failed: {detail[:300]}") from e
    return {"ok": True}
