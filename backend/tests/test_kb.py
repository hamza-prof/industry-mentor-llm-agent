import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from app import kb
from app.config import Settings
from app.models import KBSource

RUBRIC = """# Review rubric

## Evidence
Every claim must be supported by data, experiments or citations.

## Feasibility
The plan must fit the time and resources available.
"""

PROGRAM = """# 培养方案

## 实践要求
学生应完成不少于六个月的专业实践。实践报告应包含问题分析、技术方案和实践成果。
"""


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_model="fake-1")


@pytest.fixture
def store(settings):
    return kb.get_store(settings, DeterministicFakeEmbedding(size=16))


def add(session, store, settings, tmp_path, text, name, category, doc_type="any"):
    return kb.add_source(session, store, settings, text.encode(), name, category, doc_type)


def test_add_then_search_filters_by_category(session, store, settings, tmp_path):
    add(session, store, settings, tmp_path, RUBRIC, "rubric.md", "standard")
    add(session, store, settings, tmp_path, PROGRAM, "program.md", "program_requirement")
    hits = kb.search(store, "evidence", "standard", "report", k=10)
    assert hits and {h.category for h in hits} == {"standard"}
    assert all(h.filename == "rubric.md" for h in hits)
    assert kb.search(store, "实践", "exemplar", "report") == []


def test_doc_type_filter_includes_any(session, store, settings, tmp_path):
    add(session, store, settings, tmp_path, RUBRIC, "generic.md", "standard", "any")
    add(session, store, settings, tmp_path, PROGRAM, "prop.md", "standard", "proposal")
    names = lambda dt: {h.filename for h in kb.search(store, "x", "standard", dt, k=10)}  # noqa: E731
    assert names("proposal") == {"generic.md", "prop.md"}
    assert names("report") == {"generic.md"}


def test_chunks_carry_heading_and_metadata(session, store, settings, tmp_path):
    src = add(session, store, settings, tmp_path, RUBRIC, "rubric.md", "standard")
    assert src.chunk_count >= 2 and src.embedding_model == "fake-1"
    hits = kb.search(store, "plan", "standard", "any", k=10)
    feas = next(h for h in hits if "time and resources" in h.text)
    assert feas.text.startswith("Feasibility")
    assert feas.source_id == src.id and feas.chunk_id.startswith(f"{src.id}:")


def test_chinese_text_splits_on_full_stop():
    long = "。".join(f"第{i}条要求学生必须完成相应的实践内容并提交材料" for i in range(80)) + "。"
    chunks = kb.split_texts([("要求", long)])
    assert len(chunks) > 1
    assert all(c.startswith("要求\n") for c in chunks)
    assert all(c.rstrip().endswith("。") for c in chunks[:-1])
    assert max(len(c) for c in chunks) <= kb.CHUNK_SIZE + len("要求\n")


def test_duplicate_source_rejected(session, store, settings, tmp_path):
    first = add(session, store, settings, tmp_path, RUBRIC, "a.md", "standard")
    with pytest.raises(kb.DuplicateSource) as e:
        add(session, store, settings, tmp_path, RUBRIC, "b.md", "exemplar")
    assert e.value.existing_id == first.id


def test_delete_removes_all_chunks(session, store, settings, tmp_path):
    src = add(session, store, settings, tmp_path, RUBRIC, "a.md", "standard")
    add(session, store, settings, tmp_path, PROGRAM, "p.md", "standard")
    kb.delete_source(session, store, settings, src.id)
    assert session.get(KBSource, src.id) is None
    assert {h.filename for h in kb.search(store, "x", "standard", "any", k=20)} == {"p.md"}
    with pytest.raises(LookupError):
        kb.delete_source(session, store, settings, src.id)


def test_empty_kb_search_returns_empty(store):
    assert kb.search(store, "anything", "standard", "report") == []


class FlakyEmbedding(DeterministicFakeEmbedding):
    calls: int = 0

    def embed_documents(self, texts):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("embedding API down")
        return super().embed_documents(texts)


def test_embedding_failure_leaves_nothing_behind(session, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "BATCH", 1)
    store = kb.get_store(settings, FlakyEmbedding(size=16))
    with pytest.raises(RuntimeError):
        add(session, store, settings, tmp_path, RUBRIC, "a.md", "standard")
    assert kb.list_sources(session) == []
    assert store._collection.count() == 0


def test_batches_respect_api_limit(session, settings, tmp_path, monkeypatch):
    sizes = []

    class Recording(DeterministicFakeEmbedding):
        def embed_documents(self, texts):
            sizes.append(len(texts))
            return super().embed_documents(texts)

    monkeypatch.setattr(kb, "BATCH", 2)
    store = kb.get_store(settings, Recording(size=16))
    text = "\n\n".join(f"## H{i}\nRule {i} text." for i in range(5))
    add(session, store, settings, tmp_path, text, "many.md", "standard")
    assert sizes and max(sizes) <= 2 and sum(sizes) >= 5


def test_changed_embedding_model_needs_reindex(session, store, settings, tmp_path):
    add(session, store, settings, tmp_path, RUBRIC, "a.md", "standard")
    assert kb.needs_reindex(session, settings) is False
    new = settings.model_copy(update={"embedding_model": "fake-2"})
    assert kb.needs_reindex(session, new) is True

    store2 = kb.get_store(new, DeterministicFakeEmbedding(size=24))  # new dimension
    assert kb.reindex(session, store2, new) == 1
    assert kb.needs_reindex(session, new) is False
    assert kb.search(store2, "evidence", "standard", "any")
