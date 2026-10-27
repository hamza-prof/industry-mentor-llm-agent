"""DOCX → blocks: paragraphs, headings by style, tables, pictures, native charts."""

import hashlib
import re
from pathlib import Path

from app.parsing.core import Block, FigureStore, ParseError
from app.schemas import Figure

# ---- docx -------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_V = "{urn:schemas-microsoft-com:vml}"
_HEADING_STYLE = re.compile(r"^(?:Heading|标题)\s*(\d)$", re.I)


def _parse_docx(path: Path, store: FigureStore) -> list[Block]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph as DocxParagraph

    try:
        doc = Document(str(path))
    except Exception as e:  # bad zip, missing parts, OLE .doc renamed …
        raise ParseError("CORRUPT_FILE", "The DOCX file is damaged or not a real .docx.") from e

    blocks: list[Block] = []
    for el in doc.element.body.iterchildren():
        if el.tag == f"{_W}p":
            blocks.extend(_docx_paragraph(DocxParagraph(el, doc), doc, store))
        elif el.tag == f"{_W}tbl":
            table = Table(el, doc)
            rows = []
            for row in table.rows:
                seen, cells = set(), []
                for cell in row.cells:  # merged cells repeat — keep once
                    if id(cell._tc) not in seen:
                        seen.add(id(cell._tc))
                        cells.append(cell.text.strip())
                rows.append(" | ".join(cells))
            if any(r.strip(" |") for r in rows):
                blocks.append(Block("\n".join(rows), kind="table"))
            blocks.extend(_docx_figures(el, doc, store))  # pictures inside cells
    return blocks


def _docx_paragraph(p, doc, store: FigureStore) -> list[Block]:
    out: list[Block] = []
    text = p.text.replace("　", " ").strip()
    if text:
        style = (p.style.name if p.style is not None else "") or ""
        if style in ("Title", "标题"):
            out.append(Block(text, kind="title"))
        elif m := _HEADING_STYLE.match(style):
            out.append(Block(text, level=int(m.group(1))))
        elif style.startswith("List") or p._p.find(f"{_W}pPr/{_W}numPr") is not None:
            out.append(Block(text, kind="list"))
        else:
            out.append(Block(text))
    out.extend(_docx_figures(p._p, doc, store))
    return out


def _docx_figures(el, doc, store: FigureStore) -> list[Block]:
    parts = doc.part.related_parts
    out: list[Block] = []
    for drawing in [*el.iter(f"{_W}drawing"), *el.iter(f"{_W}pict")]:
        doc_pr = drawing.find(f".//{_WP}docPr")
        alt = (doc_pr.get("descr") or None) if doc_pr is not None else None
        fig = None
        if (chart := drawing.find(f".//{_C}chart")) is not None:
            part = parts.get(chart.get(f"{_R}id"))
            if part is not None:
                fig = Figure(
                    image_id=hashlib.sha256(part.blob).hexdigest()[:32],
                    source="docx_chart",
                    alt_text=alt,
                    chart_data=chart_data(part.blob),
                )
        else:
            blip = drawing.find(f".//{_A}blip")
            rid = blip.get(f"{_R}embed") if blip is not None else None
            if rid is None and (vml := drawing.find(f".//{_V}imagedata")) is not None:
                rid = vml.get(f"{_R}id")
            part = parts.get(rid) if rid else None
            if part is not None:
                fig = store.add(part.blob, content_type=part.content_type, alt=alt)
        if fig:
            out.append(store.block(fig))
    return out


def chart_data(xml: bytes) -> str:
    """Native Word/Excel chart → small text table of its real numbers."""
    from lxml import etree

    root = etree.fromstring(xml)
    title = "".join(root.xpath(".//c:chart/c:title//a:t/text()", namespaces=_XNS)).strip()
    plot = root.find(f".//{_C}plotArea")
    kinds = (
        [c.tag.removeprefix(_C) for c in plot if c.tag.endswith("Chart")]
        if plot is not None
        else []
    )
    lines = [f"Chart ({', '.join(kinds) or 'unknown'})" + (f": {title}" if title else "")]
    cats_done = False
    for ser in root.iter(f"{_C}ser"):
        name = "".join(ser.xpath("c:tx//c:v/text()", namespaces=_XNS)) or "series"
        cats = ser.xpath("(c:cat|c:xVal)//c:pt/c:v/text()", namespaces=_XNS)
        vals = ser.xpath("(c:val|c:yVal)//c:pt/c:v/text()", namespaces=_XNS)
        if cats and not cats_done:
            lines.append("categories: " + ", ".join(cats))
            cats_done = True
        lines.append(f"{name}: " + ", ".join(vals))
    return "\n".join(lines)


_XNS = {"c": _C[1:-1], "a": _A[1:-1]}
