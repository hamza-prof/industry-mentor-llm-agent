"""PDF → blocks: text by font size, running headers removed, raster images, vector charts."""

import hashlib
import re
from pathlib import Path

from app.parsing.core import Block, FigureStore, ParseError, join_lines

# ---- pdf --------------------------------------------------------------------

_PAGE_NUMBER = re.compile(r"^([-–—\s]*\d+[-–—\s]*|第\s*\d+\s*页.*|page\s+\d+(\s+of\s+\d+)?)$", re.I)
_MARGIN = 0.08  # top/bottom share of the page where running headers/footers live
_VECTOR_TOL = 12  # pt; drawings closer than this belong to the same figure


def _parse_pdf(path: Path, store: FigureStore) -> list[Block]:
    import pymupdf

    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        raise ParseError("CORRUPT_FILE", "The PDF file is damaged.") from e
    if doc.needs_pass:
        raise ParseError(
            "ENCRYPTED_PDF", "The PDF is password-protected. Remove the password and upload again."
        )
    if doc.page_count == 0:
        raise ParseError("CORRUPT_FILE", "The PDF file is damaged.")

    pages = [_read_pdf_page(page, store) for page in doc]
    n = len(pages)
    if sum(p["scanned"] for p in pages) > n / 2:
        raise ParseError(
            "SCANNED_PDF",
            "This PDF looks scanned (images of pages). OCR is not supported; "
            "upload DOCX or a text PDF.",
        )

    # Running headers/footers and logos: the same thing on at least half the pages.
    def repeated(keys_per_page):
        counts: dict = {}
        for keys in keys_per_page:
            for k in set(keys):
                counts[k] = counts.get(k, 0) + 1
        return {k for k, c in counts.items() if n >= 3 and c >= n / 2}

    margin_lines = repeated([[t["norm"] for t in p["texts"] if t["margin"]] for p in pages])
    logos = repeated([[i["sha"] for i in p["images"]] for p in pages])

    sizes: dict[float, int] = {}
    for p in pages:
        for t in p["texts"]:
            sizes[t["size"]] = sizes.get(t["size"], 0) + len(t["text"])
    body = max(sizes, key=sizes.get) if sizes else 0
    heading_sizes = sorted({s for s in sizes if s >= body * 1.15}, reverse=True)

    blocks: list[Block] = []
    for pno, p in enumerate(pages, 1):
        items = []
        for t in p["texts"]:
            if (t["margin"] and t["norm"] in margin_lines) or _PAGE_NUMBER.match(t["text"]):
                continue
            is_heading = t["size"] in heading_sizes and len(t["text"]) <= 60 and t["lines"] <= 2
            level = min(heading_sizes.index(t["size"]) + 1, 3) if is_heading else None
            items.append((t["y"], Block(t["text"], level=level, page=pno)))
        for img in p["images"]:
            if img["sha"] in logos:
                store.skipped += 1
            elif fig := store.add(img["blob"], alt=img["inner_text"]):
                items.append((img["y"], store.block(fig, page=pno)))
        for vec in p["vectors"]:
            if fig := store.add(vec["blob"], source="pdf_vector"):
                fig.chart_data = vec["inner_text"]
                items.append((vec["y"], store.block(fig, page=pno)))
        blocks.extend(b for _, b in sorted(items, key=lambda it: it[0]))
    return blocks


def _read_pdf_page(page, store: FigureStore) -> dict:
    import pymupdf

    page_area = page.rect.width * page.rect.height
    h = page.rect.height
    texts, images = [], []
    for b in page.get_text("dict", sort=True)["blocks"]:
        if b["type"] == 0:
            lines, sizes = [], []
            for ln in b["lines"]:
                s = "".join(sp["text"] for sp in ln["spans"]).replace("　", " ").strip()
                if s:
                    lines.append(s)
                    sizes += [round(sp["size"] * 2) / 2 for sp in ln["spans"] if sp["text"].strip()]
            if lines:
                x0, y0, x1, y1 = b["bbox"]
                txt = join_lines(lines)
                texts.append(
                    dict(
                        text=txt,
                        norm=re.sub(r"\d+", "#", txt),
                        size=max(sizes),
                        lines=len(lines),
                        y=y0,
                        rect=pymupdf.Rect(b["bbox"]),
                        margin=y0 < h * _MARGIN or y1 > h * (1 - _MARGIN),
                    )
                )
        elif b["type"] == 1:
            images.append(
                dict(
                    blob=b["image"],
                    sha=hashlib.sha256(b["image"]).hexdigest(),
                    y=b["bbox"][1],
                    rect=pymupdf.Rect(b["bbox"]),
                )
            )

    text_chars = sum(len(t["text"]) for t in texts)
    scanned = text_chars < 20 and any(i["rect"].get_area() >= 0.8 * page_area for i in images)

    vectors = []
    for rect in _vector_regions(page, page_area):
        pix = page.get_pixmap(clip=rect + (-4, -4, 4, 4), dpi=150)
        vectors.append(dict(blob=pix.tobytes("png"), y=rect.y0, rect=rect))

    # Text drawn inside a figure (axis labels, legends) belongs to the figure, not the body.
    for fig in images + vectors:
        area = fig["rect"] + (-2, -2, 2, 2)
        inside = [
            t for t in texts if area.contains(t["rect"].tl + (t["rect"].br - t["rect"].tl) * 0.5)
        ]
        fig["inner_text"] = " ".join(t["text"] for t in inside) or None
        texts = [t for t in texts if t not in inside]
    return dict(texts=texts, images=images, vectors=vectors, scanned=scanned)


def _vector_regions(page, page_area: float) -> list:
    """Areas of vector drawings that look like charts/diagrams (not table grids or rules)."""
    import pymupdf

    drawings = page.get_drawings()
    if len(drawings) < 5:
        return []
    # ponytail: O(n²) rectangle merge; fine for normal pages, use an R-tree if pages have 10k+ paths
    groups: list[list] = []
    for d in drawings:
        r = pymupdf.Rect(d["rect"])
        grown = r + (-_VECTOR_TOL, -_VECTOR_TOL, _VECTOR_TOL, _VECTOR_TOL)
        hits = [g for g in groups if g[0].intersects(grown)]
        merged = [r | grown, [d]]
        for g in hits:
            merged[0] |= g[0]
            merged[1] += g[1]
            groups.remove(g)
        groups.append(merged)

    regions = []
    for _, members in groups:
        # min/max by hand: Rect "|" ignores zero-width/height rects, i.e. axis lines
        rs = [d["rect"] for d in members]
        rect = pymupdf.Rect(
            min(r.x0 for r in rs),
            min(r.y0 for r in rs),
            max(r.x1 for r in rs),
            max(r.y1 for r in rs),
        )
        # ponytail: "chart-like" = ≥3 filled shapes, curves or diagonal lines;
        # shaded tables can false-positive — add a fill-colour-variety check if that bites
        chartish = sum(
            1
            for d in members
            if d.get("fill") is not None
            or any(
                it[0] == "c" or (it[0] == "l" and it[1].x != it[2].x and it[1].y != it[2].y)
                for it in d["items"]
            )
        )
        if chartish >= 3 and rect.get_area() >= 0.05 * page_area:
            regions.append(rect)
    return regions
