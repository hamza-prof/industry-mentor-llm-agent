"""Feature 1: structured summary. One call if the document fits, else map (notes per section)
then reduce. The model only fills SummaryOutput; ids, outline and warnings are fixed up here."""

import asyncio
from collections.abc import Iterator

from langchain_core.language_models import BaseChatModel
from sqlmodel import Session

from app import prompts
from app.config import Settings
from app.llm import count_tokens, get_chat_model
from app.schemas import (
    OutlineItem,
    Paragraph,
    ParsedDocument,
    Section,
    StructuredSummary,
    SummaryField,
    SummaryOutput,
)

LANGUAGES = {"zh": "Chinese (简体中文)", "en": "English"}
SHORT_DOC_CHARS = 200
MAP_CONCURRENCY = 3
BUDGET_SHARE = 0.6  # of LLM_CONTEXT_TOKENS; the rest is prompt + answer
FIELDS = [n for n, f in SummaryOutput.model_fields.items() if f.annotation is SummaryField]


def section_text(section: Section, paragraphs: list[Paragraph] | None = None) -> str:
    lines = [f"[{p.id}] {p.text}" for p in paragraphs or section.paragraphs]
    return "\n".join([f"[{section.id}] {section.heading}", *lines])


def windows(section: Section, budget: int) -> Iterator[list[Paragraph]]:
    # ponytail: a single paragraph over budget is sent whole; split sentences if that happens
    chunk, size = [], 0
    for p in section.paragraphs:
        tokens = count_tokens(p.text) + 4
        if chunk and size + tokens > budget:
            yield chunk
            chunk, size = [], 0
        chunk.append(p)
        size += tokens
    if chunk:
        yield chunk


async def _map(model, session, sections, budget, common, warnings) -> str:
    jobs = [(s, c) for s in sections for c in windows(s, budget)]
    msgs = [
        prompts.render(session, "summary_map", section=section_text(s, c), **common)
        for s, c in jobs
    ]
    sem = asyncio.Semaphore(MAP_CONCURRENCY)

    async def note(m) -> str | Exception:
        async with sem:
            for attempt in range(2):  # retry once; transport retries live in the model client
                try:
                    return (await model.ainvoke(m)).text
                except Exception as e:  # noqa: BLE001 — one bad section must not sink the summary
                    if attempt:
                        return e

    notes = await asyncio.gather(*(note(m) for m in msgs))
    pairs = [(s, n) for (s, _), n in zip(jobs, notes, strict=True)]
    done = [(s, n) for s, n in pairs if not isinstance(n, Exception)]
    failed = list(dict.fromkeys(s.id for s, n in pairs if isinstance(n, Exception)))
    if not done:
        raise next(n for n in notes if isinstance(n, Exception))
    if failed:
        warnings.append(f"SUMMARY_SECTION_FAILED: {', '.join(failed)} could not be summarised")
    # ponytail: notes assumed to fit the reduce call; reduce in rounds if huge docs overflow
    return "\n\n".join(f"[{s.id}] {s.heading}\n{n}" for s, n in done)


def _clean(out: SummaryOutput, parsed: ParsedDocument, warnings: list[str]) -> StructuredSummary:
    ids = set(parsed.all_paragraph_ids())
    fields = {}
    for name in FIELDS:
        f: SummaryField = getattr(out, name)
        text = (f.text or "").strip()
        fields[name] = (
            SummaryField(text=text, source_ids=[i for i in dict.fromkeys(f.source_ids) if i in ids])
            if text and not f.not_found
            else SummaryField(not_found=True)
        )
    lines = {o.section_id: o.one_line for o in out.outline}
    outline = [
        OutlineItem(section_id=s.id, heading=s.heading, one_line=lines.get(s.id, ""))
        for s in parsed.sections
    ]
    return StructuredSummary(
        **fields, outline=outline, title=parsed.title, doc_type=parsed.doc_type, warnings=warnings
    )


async def summarize_document(
    parsed: ParsedDocument,
    session: Session,
    settings: Settings,
    model: BaseChatModel | None = None,
) -> StructuredSummary:
    model = model or get_chat_model(settings)
    lang = parsed.language if settings.output_language == "auto" else settings.output_language
    common = {"doc_type": parsed.doc_type, "title": parsed.title or "", "language": LANGUAGES[lang]}
    warnings = ["DOCUMENT_TOO_SHORT"] if parsed.char_count < SHORT_DOC_CHARS else []

    sections = [s for s in parsed.sections if s.paragraphs]
    document = "\n\n".join(section_text(s) for s in sections)
    budget = int(BUDGET_SHARE * settings.llm_context_tokens)
    if count_tokens(document) > budget:
        document = await _map(model, session, sections, budget, common, warnings)

    structured = model.with_structured_output(SummaryOutput, method=settings.llm_structured_method)
    msgs = prompts.render(session, "summary_reduce", document=document, **common)
    for _ in range(2):  # models sometimes skip the tool call; one more try, like review
        if (out := await structured.ainvoke(msgs)) is not None:
            return _clean(out, parsed, warnings)
    raise ValueError("the model returned no structured summary")
