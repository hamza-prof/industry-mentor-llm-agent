"""Uploaded file → ParsedDocument: sections → paragraphs (incl. figures) with stable IDs."""

from pathlib import Path

from app.parsing.core import (
    SUPPORTED_EXTENSIONS,
    Block,
    FigureStore,
    ParseError,
    _cap_figures,
    _parse_text,
    attach_captions,
    build_sections,
    detect_language,
    heading_level,
)
from app.parsing.docx import _parse_docx, chart_data
from app.parsing.pdf import _parse_pdf
from app.schemas import DocType, ParsedDocument

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "Block",
    "ParseError",
    "build_sections",
    "chart_data",
    "detect_language",
    "heading_level",
    "parse_file",
]


# ---- entry point ------------------------------------------------------------


def parse_file(
    path: Path,
    doc_type: DocType,
    figures_dir: Path | None = None,
    max_figures: int = 40,
    allow_figures_only: bool = False,
) -> ParsedDocument:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ParseError(
            "UNSUPPORTED_FILE_TYPE",
            f"'{ext or path.name}' is not supported. "
            f"Upload one of: {', '.join(SUPPORTED_EXTENSIONS)}.",
        )
    store = FigureStore(figures_dir)
    parser = {".docx": _parse_docx, ".pdf": _parse_pdf}.get(ext)
    blocks = parser(path, store) if parser else _parse_text(path)
    title = next((b.text for b in blocks if b.kind == "title"), None)
    blocks = attach_captions([b for b in blocks if b.kind != "title"])
    fig_warnings = list(dict.fromkeys(store.warnings)) + _cap_figures(blocks, max_figures)
    if store.skipped:
        fig_warnings.append(f"FIGURES_SKIPPED: {store.skipped} decorative image(s) ignored")

    text_blocks = [b for b in blocks if b.kind != "figure" and b.text.strip()]
    if not text_blocks:
        has_figures = any(b.kind == "figure" for b in blocks)
        if not (has_figures and allow_figures_only):
            hint = (
                " It contains only images; configure VISION_MODEL to analyse them."
                if has_figures
                else ""
            )
            raise ParseError("EMPTY_DOCUMENT", "No text found in the document." + hint)

    sections, warnings = build_sections(blocks)
    return ParsedDocument(
        filename=path.name,
        doc_type=doc_type,
        language=detect_language(" ".join(b.text for b in text_blocks)),
        title=title,
        sections=sections,
        warnings=warnings + fig_warnings,
    )
