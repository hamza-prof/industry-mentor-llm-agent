"""Features 2 + 3: review one section against the knowledge base, then pin every comment to
real text (anchor_comments) and drop duplicates (dedupe_comments)."""

import re
from difflib import SequenceMatcher

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from sqlmodel import Session

from app import prompts
from app.config import Settings
from app.llm import count_tokens
from app.schemas import (
    SEVERITY_RANK,
    Comment,
    KBHit,
    ParsedDocument,
    RawComment,
    Section,
    SectionReview,
    StructuredSummary,
)
from app.summarize import BUDGET_SHARE, LANGUAGES, section_text, windows

FUZZY = 0.85
DUPLICATE = 0.8
CONTEXT_SHARE = 0.1  # of LLM_CONTEXT_TOKENS, per KB category
NONE_PROVIDED = "(none provided)"
_PARA_ID = re.compile(r"S\d+\.P\d+")
_REF_ID = re.compile(r"K\d+")
_REF_IN_TEXT = re.compile(r"\[?\b(K\d+)\b\]?")
_NOISE = re.compile(r"[\s\W_]+", re.UNICODE)  # whitespace + punctuation, for loose matching
_PLACEHOLDER = {
    "standard": "standards",
    "program_requirement": "requirements",
    "exemplar": "exemplars",
}


class SectionReviewFailed(Exception):
    def __init__(self, section_id: str, reason: str):
        super().__init__(f"{section_id}: {reason}")
        self.section_id, self.reason = section_id, reason


# ---- anchoring ------------------------------------------------------------------


def _loose(text: str) -> tuple[str, list[int]]:
    """Text without whitespace/punctuation, lower-cased, plus each kept char's original index."""
    kept = [(c.lower(), i) for i, c in enumerate(text) if not _NOISE.fullmatch(c)]
    return "".join(c for c, _ in kept), [i for _, i in kept]


def match_quote(quote: str | None, text: str) -> str | None:
    """The real words in `text` the quote refers to, or None if it isn't there."""
    q = (quote or "").strip()
    if not q or not text:
        return None
    if q in text:
        return q
    lq, _ = _loose(q)
    lt, idx = _loose(text)
    if not lq:
        return None
    if len(lq) >= len(lt):  # quote longer than the paragraph: does it contain the paragraph?
        return text.strip() if lt and (lt in lq or _ratio(lt, lq[: len(lt)]) >= FUZZY) else None
    # ponytail: O(len(text)) windows × SequenceMatcher; fine for paragraphs ≤ a few thousand chars
    best, start = 0.0, -1
    for i in range(len(lt) - len(lq) + 1):
        r = _ratio(lq, lt[i : i + len(lq)])
        if r > best:
            best, start = r, i
            if r == 1:
                break
    if best < FUZZY:
        return None
    return text[idx[start] : idx[start + len(lq) - 1] + 1]


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def anchor_comments(
    raw: list[RawComment], parsed: ParsedDocument, section_id: str, refs: dict[str, str]
) -> list[Comment]:
    """Never trust the model's anchor: the paragraph must exist and the quote must be in it."""
    in_section = [p for s in parsed.sections if s.id == section_id for p in s.paragraphs]
    elsewhere = [p for s in parsed.sections if s.id != section_id for p in s.paragraphs]
    out = []
    for r in raw:
        pid = _PARA_ID.search(r.paragraph_id or "")  # models write "S3.P2", "[S3.P2]", …
        para = parsed.paragraph(pid[0]) if pid else None
        quote = match_quote(r.quote, para.text) if para else None
        if para is None and r.quote:  # wrong id: find the quoted words instead
            for p in in_section + elsewhere:
                if quote := match_quote(r.quote, p.text):
                    para = p
                    break
        out.append(
            Comment(
                section_id=para.id.split(".")[0] if para else section_id,
                paragraph_id=para.id if para else None,
                quote=quote,
                anchored=para is not None,
                category=r.category,
                severity=r.severity,
                problem=_readable(r.problem, refs),
                suggestion=_readable(r.suggestion, refs),
                revision_steps=[_readable(x, refs) for x in r.revision_steps],
                standard_refs=_refs(r.standard_refs, refs),
                origin="ai",
            )
        )
    return out


def _readable(text: str, shown: dict[str, str]) -> str:
    """ "violates [K6]" → "violates [program_requirements.md]" — labels mean nothing to a mentor."""

    def name(m: re.Match) -> str:
        return f"[{shown[m[1]].split(':')[0]}]" if m[1] in shown else m[0]

    return _REF_IN_TEXT.sub(name, text)


def _refs(given: list[str], shown: dict[str, str]) -> list[str]:
    """Models write "K1", "[K1] Evidence" or "K1: <quoted rule>": keep only labels we showed."""
    labels = [m for g in given for m in _REF_ID.findall(g)]
    return [shown[k] for k in dict.fromkeys(labels) if k in shown]


def dedupe_comments(comments: list[Comment]) -> list[Comment]:
    """Same place + same category + similar problem → keep one (rule first, then severity)."""
    kept: list[Comment] = []
    for c in comments:
        twin = next(
            (
                k
                for k in kept
                if (k.paragraph_id, k.section_id, k.category)
                == (c.paragraph_id, c.section_id, c.category)
                and _ratio(k.problem.lower(), c.problem.lower()) > DUPLICATE
            ),
            None,
        )
        if twin is None:
            kept.append(c)
        elif _rank(c) > _rank(twin):
            kept[kept.index(twin)] = c
    return kept


def _rank(c: Comment) -> tuple[int, int]:
    return (c.origin == "rule", SEVERITY_RANK[c.severity])


# ---- one section ------------------------------------------------------------------


def summary_text(s: StructuredSummary | None) -> str:
    if s is None:
        return ""
    names = {
        "research_problem": "Research problem",
        "objectives": "Objectives",
        "technical_approach": "Technical approach",
        "main_conclusions": "Main conclusions",
        "innovations": "Innovations",
        "limitations": "Limitations",
    }
    return "\n".join(f"{label}: {getattr(s, f).text or 'not found'}" for f, label in names.items())


def _context(hits: dict[str, list[KBHit]], budget: int) -> tuple[dict[str, str], dict[str, str]]:
    """KB hits → prompt text per placeholder, labelled [K1]…, and label → reference string."""
    texts, refs, n = {}, {}, 0
    for category, placeholder in _PLACEHOLDER.items():
        lines, used = [], 0
        for h in hits.get(category, []):
            cost = count_tokens(h.text)
            if lines and used + cost > budget:
                break
            n += 1
            label = f"K{n}"
            lines.append(f"[{label}] ({h.filename}) {h.text}")
            refs[label] = f"{h.filename}: {h.text[:120]}"
            used += cost
        texts[placeholder] = "\n\n".join(lines) or NONE_PROVIDED
    return texts, refs


async def review_section(
    parsed: ParsedDocument,
    section: Section,
    hits: dict[str, list[KBHit]],
    summary: str,
    session: Session,
    settings: Settings,
    model: BaseChatModel,
) -> list[Comment]:
    ctx_budget = int(CONTEXT_SHARE * settings.llm_context_tokens)
    context, refs = _context(hits, ctx_budget)
    lang = parsed.language if settings.output_language == "auto" else settings.output_language
    budget = max(int(BUDGET_SHARE * settings.llm_context_tokens) - 3 * ctx_budget, 200)
    structured = model.with_structured_output(SectionReview, method=settings.llm_structured_method)

    comments: list[Comment] = []
    for window in windows(section, budget):
        msgs = prompts.render(
            session,
            "section_review",
            section=section_text(section, window),
            summary=summary,
            doc_type=parsed.doc_type,
            language=LANGUAGES[lang],
            **context,
        )
        for attempt in range(2):
            try:
                out = await structured.ainvoke(msgs)
                if out is None:
                    raise ValueError("the model returned no structured output")
                break
            except Exception as e:  # noqa: BLE001 — invalid output gets one retry with the error
                if attempt:
                    raise SectionReviewFailed(section.id, str(e)[:300]) from e
                msgs = [
                    *msgs,
                    HumanMessage(
                        f"Your previous answer was invalid ({str(e)[:300]}). "
                        "Answer again using exactly the required output format."
                    ),
                ]
        comments += anchor_comments(out.comments, parsed, section.id, refs)
    return dedupe_comments(comments)
