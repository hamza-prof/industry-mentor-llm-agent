"""Let the review "see" figures: a vision model describes each chart/diagram/screenshot, the
description replaces the figure's paragraph text, and the figure problems become comments."""

import asyncio
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel
from sqlmodel import Session

from app import prompts
from app.config import Settings
from app.llm import image_message
from app.models import FigureCache
from app.schemas import Comment, FigureDescription, Paragraph, ParsedDocument
from app.summarize import LANGUAGES

CONCURRENCY = 3


class FigureResult(BaseModel):
    parsed: ParsedDocument  # copy with figure paragraphs rewritten
    comments: list[Comment] = []
    warnings: list[str] = []
    analysed: int = 0


def _label(p: Paragraph) -> str:
    return f"[Figure: {p.figure.caption or p.figure.alt_text or 'no caption'}]"


def _context(parsed: ParsedDocument, pid: str) -> str:
    """Text paragraphs just before and after the figure (what the text claims about it)."""
    for s in parsed.sections:
        ids = [p.id for p in s.paragraphs]
        if pid in ids:
            i = ids.index(pid)
            near = s.paragraphs[max(i - 1, 0) : i] + s.paragraphs[i + 1 : i + 2]
            return "\n".join(p.text for p in near if p.kind != "figure")
    return ""


async def describe_figures(
    parsed: ParsedDocument,
    figures_dir: Path,
    session: Session,
    settings: Settings,
    model: BaseChatModel | None,
) -> FigureResult:
    parsed = parsed.model_copy(deep=True)
    res = FigureResult(parsed=parsed)
    todo = []
    for p in parsed.figures():
        f = p.figure
        if f.source == "docx_chart" and f.chart_data:
            p.text = f"{_label(p)} {f.chart_data}"  # numbers already read from the chart XML
        elif f.analysable and f.file and (figures_dir / f.file).is_file():
            todo.append(p)
    if not todo:
        return res
    if model is None:
        res.warnings.append(
            f"FIGURES_NOT_ANALYSED: {len(todo)} figure(s) not analysed (set VISION_MODEL)"
        )
        return res

    version = prompts.get_active(session, "figure_describe").version
    lang = parsed.language if settings.output_language == "auto" else settings.output_language
    structured = model.with_structured_output(
        FigureDescription, method=settings.llm_structured_method
    )
    sem = asyncio.Semaphore(CONCURRENCY)

    async def describe(p: Paragraph) -> FigureDescription | None:
        msgs = prompts.render(
            session,
            "figure_describe",
            caption=p.figure.caption or p.figure.alt_text or "(no caption)",
            context=_context(parsed, p.id),
            doc_type=parsed.doc_type,
            language=LANGUAGES[lang],
        )
        msgs[-1] = image_message((figures_dir / p.figure.file).read_bytes(), msgs[-1].content)
        async with sem:
            for _ in range(2):  # retry once
                try:
                    if (out := await structured.ainvoke(msgs)) is not None:
                        return out
                except Exception:  # noqa: BLE001 — e.g. provider rejects the image
                    pass
        return None

    cached = {p.id: session.get(FigureCache, f"{p.figure.image_id}:{version}") for p in todo}
    missing = [p for p in todo if cached[p.id] is None]
    fresh = dict(
        zip([p.id for p in missing], await asyncio.gather(*map(describe, missing)), strict=True)
    )

    failed = []
    for p in todo:
        hit = cached[p.id]
        desc = FigureDescription(**hit.data) if hit else fresh[p.id]
        if desc is None:
            failed.append(p.id)
            continue
        if hit is None:
            key = f"{p.figure.image_id}:{version}"
            session.merge(FigureCache(key=key, data=desc.model_dump()))
        res.analysed += 1
        data = f"; data: {', '.join(desc.key_data)}" if desc.key_data else ""
        p.text = f"{_label(p)} {desc.summary}{data}"
        sid = p.id.split(".")[0]
        res.comments += [
            Comment(
                section_id=sid,
                paragraph_id=p.id,
                anchored=True,
                category="format",
                severity="low" if desc.readable else "medium",
                problem=issue,
                origin="ai",
            )
            for issue in desc.issues
        ]
    session.commit()
    if failed:
        res.warnings.append(f"FIGURE_DESCRIBE_FAILED: {', '.join(failed)} kept caption only")
    return res
