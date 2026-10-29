import base64
import os

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import Settings
from app.llm import (
    LLMNotConfigured,
    count_tokens,
    get_chat_model,
    get_embeddings,
    get_vision_model,
    image_message,
)


def settings(**kw) -> Settings:
    base = dict(_env_file=None, llm_api_key="sk-test", llm_model="m1")
    return Settings(**{**base, **kw})


@pytest.mark.parametrize(
    "provider,url",
    [
        ("openrouter", "https://openrouter.ai/api/v1"),
        ("groq", "https://api.groq.com/openai/v1"),
    ],
)
def test_openai_compatible_presets_fill_base_url(provider, url):
    m = get_chat_model(settings(llm_provider=provider))
    assert isinstance(m, ChatOpenAI)
    assert m.openai_api_base == url


def test_explicit_base_url_overrides_preset():
    m = get_chat_model(settings(llm_provider="groq", llm_base_url="http://proxy.local/v1"))
    assert m.openai_api_base == "http://proxy.local/v1"


def test_openai_compatible_passes_settings_through():
    m = get_chat_model(
        settings(llm_base_url="https://api.deepseek.com", llm_temperature=0.1, llm_max_retries=4)
    )
    assert isinstance(m, ChatOpenAI)
    assert (m.model_name, m.openai_api_base) == ("m1", "https://api.deepseek.com")
    assert m.temperature == 0.1 and m.max_retries == 4
    assert m.request_timeout == 120
    assert m.openai_api_key.get_secret_value() == "sk-test"


def test_openrouter_sends_app_attribution_headers():
    m = get_chat_model(settings(llm_provider="openrouter"))
    assert m.default_headers["X-Title"] == "Industry Mentor Review Assistant"


def test_anthropic_provider():
    m = get_chat_model(settings(llm_provider="anthropic", llm_model="claude-sonnet-5-5"))
    assert isinstance(m, ChatAnthropic) and m.model == "claude-sonnet-5-5"


def test_missing_key_raises():
    with pytest.raises(LLMNotConfigured):
        get_chat_model(settings(llm_api_key=""))


def test_vision_disabled_without_model():
    assert get_vision_model(settings(vision_model="")) is None


def test_vision_inherits_llm_connection():
    m = get_vision_model(settings(llm_provider="openrouter", vision_model="qwen/qwen2.5-vl-72b"))
    assert isinstance(m, ChatOpenAI)
    assert m.model_name == "qwen/qwen2.5-vl-72b"
    assert m.openai_api_base == "https://openrouter.ai/api/v1"
    assert m.openai_api_key.get_secret_value() == "sk-test"


def test_vision_can_use_its_own_provider():
    m = get_vision_model(
        settings(
            llm_provider="groq",
            vision_provider="anthropic",
            vision_api_key="sk-ant",
            vision_model="claude-sonnet-5-5",
        )
    )
    assert isinstance(m, ChatAnthropic)


def test_vision_is_deterministic():
    assert get_vision_model(settings(vision_model="v", llm_temperature=0.7)).temperature == 0


def test_embeddings_use_own_connection():
    e = get_embeddings(
        settings(embedding_base_url="https://dashscope.example/v1", embedding_api_key="sk-e")
    )
    assert isinstance(e, OpenAIEmbeddings)
    assert e.openai_api_base == "https://dashscope.example/v1"
    assert e.check_embedding_ctx_length is False  # non-OpenAI endpoints reject token arrays


def test_image_message_is_a_data_url_block():
    msg = image_message(b"\x89PNG-bytes", "Describe this chart")
    text, image = msg.content
    assert text == {"type": "text", "text": "Describe this chart"}
    url = image["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNG-bytes"


def test_count_tokens_is_rough_but_language_aware():
    assert count_tokens("") == 0
    assert 3 <= count_tokens("这是一个测试句子") <= 8
    assert 2 <= count_tokens("hello world, this is") <= 8
    assert count_tokens("中" * 1000) > count_tokens("a" * 1000)


live = pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call a real LLM")


@pytest.mark.live
@live
def test_live_chat_returns_text():
    from app.config import Settings as S

    reply = get_chat_model(S()).invoke("Reply with the single word: ok")
    assert reply.content.strip()


@pytest.mark.live
@live
def test_live_vision_describes_a_chart():
    from app.config import Settings as S
    from tests.helpers import make_png

    model = get_vision_model(S())
    if model is None:
        pytest.skip("VISION_MODEL not set")
    reply = model.invoke([image_message(make_png(300, 200), "What colours do you see?")])
    assert reply.content.strip()


def test_fake_provider_needs_no_key_and_answers_deterministically():
    import asyncio

    from langchain_core.messages import HumanMessage, SystemMessage

    from app.schemas import SectionReview, SummaryOutput

    s = Settings(_env_file=None, llm_provider="fake")
    assert s.llm_configured and get_vision_model(s) is None
    model = get_chat_model(s)
    msgs = [
        SystemMessage("Labels look like [S3.P2]."),
        HumanMessage(
            "<document>\n[S2] 2 Results\n[S2.P1] Users are much happier now.\n</document>"
        ),
    ]
    review = asyncio.run(model.with_structured_output(SectionReview).ainvoke(msgs))
    [c] = review.comments
    assert c.paragraph_id == "S2.P1" and c.quote in "Users are much happier now."
    summary = asyncio.run(model.with_structured_output(SummaryOutput).ainvoke(msgs))
    assert summary.research_problem.source_ids == ["S2.P1"]
    assert asyncio.run(model.ainvoke(msgs)).text


def test_each_llm_call_logs_model_tokens_and_time_but_no_text(caplog):
    import logging
    import uuid

    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    from app.llm import UsageLog

    log, run = UsageLog(), uuid.uuid4()
    caplog.set_level(logging.INFO, logger="app.llm")
    log.on_chat_model_start({"kwargs": {"model_name": "deepseek-chat"}}, [[]], run_id=run)
    msg = AIMessage(
        "STUDENT SECRET TEXT",
        usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    )
    log.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=run)
    [line] = caplog.messages
    assert "deepseek-chat" in line and "in=120" in line and "out=30" in line and "ms=" in line
    assert "SECRET" not in line


def test_built_models_carry_the_usage_logger():
    from app.llm import UsageLog

    model = get_chat_model(Settings(_env_file=None, llm_api_key="k"))
    assert any(isinstance(cb, UsageLog) for cb in model.callbacks)
