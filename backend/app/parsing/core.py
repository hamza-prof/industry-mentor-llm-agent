"""Shared parsing pieces: blocks, figure store, captions, sectionizer, text/markdown parser."""

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.schemas import Figure, Paragraph, Section

SUPPORTED_EXTENSIONS = (".docx", ".pdf", ".txt", ".md")
MIN_FIGURE_PX = 64  # smaller = icon/bullet/decoration
MAX_FIGURE_PX = 1600  # long side of stored PNG; vision models downscale anyway


class ParseError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class Block:
    """One unit of reading-order content, before sectionizing."""

    text: str
    level: int | None = None  # set when the source format says it's a heading
    kind: str = "text"  # text | table | list | figure | title
    page: int | None = None
    figure: Figure | None = None


# ---- helpers ----------------------------------------------------------------


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "　" <= ch <= "〿" or "＀" <= ch <= "￯"


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines: no space between CJK, a space between Latin words, undo hyphenation."""
    out = ""
    for line in (ln for ln in lines if ln):
        if not out:
            out = line
        elif out.endswith("-") and line[0].islower():
            out = out[:-1] + line
        elif _is_cjk(out[-1]) or _is_cjk(line[0]):
            out += line
        else:
            out += " " + line
    return out


def detect_language(text: str) -> str:
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return "zh" if cjk and cjk / (cjk + latin) > 0.3 else "en"


def figure_text(fig: Figure) -> str:
    return "[Figure] " + (fig.caption or fig.alt_text or fig.chart_data or "(no caption)")


# ---- figures ----------------------------------------------------------------


class FigureStore:
    """Normalises image bytes into stored PNGs + Figure records; collects figure warnings."""

    def __init__(self, figures_dir: Path | None):
        self.dir = figures_dir
        self.warnings: list[str] = []
        self.skipped = 0

    def add(
        self, blob: bytes, source: str = "embedded", content_type: str = "", alt: str | None = None
    ):
        image_id = hashlib.sha256(blob).hexdigest()[:32]
        if any(x in content_type for x in ("emf", "wmf")):
            self.warnings.append("FIGURE_FORMAT_UNSUPPORTED")
            return Figure(image_id=image_id, source=source, alt_text=alt, analysable=False)
        try:
            img = Image.open(io.BytesIO(blob))
            img.load()
        except Exception:  # corrupt bytes, unknown format, decompression bomb
            self.warnings.append("FIGURE_UNREADABLE")
            return None
        if min(img.size) < MIN_FIGURE_PX:
            self.skipped += 1
            return None
        img = _to_rgb(img)
        img.thumbnail((MAX_FIGURE_PX, MAX_FIGURE_PX))
        file = None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
            file = f"{image_id}.png"
            if not (self.dir / file).exists():
                img.save(self.dir / file, "PNG")
        return Figure(
            image_id=image_id,
            file=file,
            width=img.width,
            height=img.height,
            source=source,
            alt_text=alt,
        )

    def block(self, fig: Figure, page: int | None = None) -> Block:
        return Block(figure_text(fig), kind="figure", page=page, figure=fig)


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


_FIG_CAPTION = re.compile(r"^(图|Figure|Fig\.?)\s*[\d一二三四五六七八九十]+([.\-－–]\d+)*", re.I)
_ANY_CAPTION = re.compile(
    r"^(图|Figure|Fig\.?|表|Table)\s*[\d一二三四五六七八九十]+([.\-－–]\d+)*", re.I
)


def _caption(b: Block | None, pattern: re.Pattern) -> str | None:
    if b and b.kind == "text" and len(b.text) <= 80 and not b.text.endswith(_SENTENCE_END):
        if pattern.match(b.text):
            return b.text
    return None


def attach_captions(blocks: list[Block]) -> list[Block]:
    """Merge the caption line after (or else before) each figure into the figure.

    After: only 图/Figure captions — a 表/Table line after a figure usually belongs to the next
    table.
    """
    out: list[Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind == "figure" and b.figure.caption is None:
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if cap := _caption(nxt, _FIG_CAPTION):
                i += 1
            elif cap := _caption(out[-1] if out else None, _ANY_CAPTION):
                out.pop()
            if cap:
                b.figure.caption = cap
                b.text = figure_text(b.figure)
        out.append(b)
        i += 1
    return out


def _cap_figures(blocks: list[Block], max_figures: int) -> list[str]:
    analysable = [b.figure for b in blocks if b.kind == "figure" and b.figure.analysable]
    for fig in analysable[max_figures:]:
        fig.analysable = False
    extra = len(analysable) - max_figures
    return (
        [f"TOO_MANY_FIGURES: {extra} beyond the limit of {max_figures} not analysed"]
        if extra > 0
        else []
    )


# ---- sectionizer ------------------------------------------------------------

_CN_NUM = "一二三四五六七八九十百"
_HEADING_PATTERNS = [
    (re.compile(rf"^第[{_CN_NUM}\d]+章"), lambda m: 1),
    (re.compile(rf"^第[{_CN_NUM}\d]+节"), lambda m: 2),
    (re.compile(rf"^[{_CN_NUM}]+、"), lambda m: 1),
    (re.compile(rf"^[（(][{_CN_NUM}]+[）)]"), lambda m: 2),
    (re.compile(r"^(\d+(?:\.\d+)*)(?:[.、]?\s+|、)"), lambda m: m.group(1).count(".") + 1),
]
_SENTENCE_END = tuple("。．.!！?？;；,，:：")
_TOC_TITLES = {"目录", "contents", "tableofcontents"}
_TOC_LINE = re.compile(r"(\.{3,}|…{2,}|·{3,}|\t)\s*\d+\s*$")
_PSEUDO_SECTION_CHARS = 800


def heading_level(text: str) -> int | None:
    """Level of a numbered heading line ("1.2 背景" → 2), or None if it reads like a sentence."""
    if len(text) > 60 or text.endswith(_SENTENCE_END):
        return None
    for pattern, level in _HEADING_PATTERNS:
        if m := pattern.match(text):
            return level(m)
    return None


def build_sections(blocks: list[Block]) -> tuple[list[Section], list[str]]:
    blocks = [
        b
        for b in blocks
        if not (b.kind == "text" and _TOC_LINE.search(b.text))
        and re.sub(r"\s", "", b.text).lower() not in _TOC_TITLES
    ]
    sections: list[Section] = []
    current: Section | None = None
    warnings: list[str] = []

    for b in blocks:
        level = (
            b.level
            if b.level is not None
            else (heading_level(b.text) if b.kind == "text" else None)
        )
        if level is not None:
            current = Section(
                id=f"S{len([s for s in sections if s.id != 'S0']) + 1}", heading=b.text, level=level
            )
            sections.append(current)
            continue
        if current is None:
            current = Section(id="S0", heading="Front matter", level=0)
            sections.append(current)
        current.paragraphs.append(_paragraph(current, b))

    if sections and all(s.id == "S0" for s in sections):
        sections = _pseudo_sections(sections[0].paragraphs)
        warnings.append("NO_HEADINGS_DETECTED")
    return sections, warnings


def _paragraph(section: Section, b: Block) -> Paragraph:
    return Paragraph(
        id=f"{section.id}.P{len(section.paragraphs) + 1}",
        text=b.text,
        page=b.page,
        kind=b.kind if b.kind in ("table", "list", "figure") else "text",
        figure=b.figure,
    )


def _pseudo_sections(paragraphs: list[Paragraph]) -> list[Section]:
    sections: list[Section] = []
    size = _PSEUDO_SECTION_CHARS
    for p in paragraphs:
        if size >= _PSEUDO_SECTION_CHARS:
            sections.append(
                Section(id=f"S{len(sections) + 1}", heading=f"Part {len(sections) + 1}", level=1)
            )
            size = 0
        sec = sections[-1]
        sec.paragraphs.append(p.model_copy(update={"id": f"{sec.id}.P{len(sec.paragraphs) + 1}"}))
        size += len(p.text)
    return sections


# ---- text / markdown ----------------------------------------------------------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_MD_LIST = re.compile(r"^([-*+]|\d+[.)])\s+")
_MD_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)]*)\)$")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("UNSUPPORTED_ENCODING", "File is not UTF-8 or GBK/GB18030 text.")


def _parse_text(path: Path) -> list[Block]:
    text = _decode(path.read_bytes())
    blocks: list[Block] = []
    pending: list[str] = []

    def flush():
        if pending:
            blocks.append(Block(join_lines(pending)))
            pending.clear()

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.replace("　", " ").strip()
        if not line:
            flush()
        elif m := _MD_HEADING.match(line):
            flush()
            blocks.append(Block(m.group(2), level=len(m.group(1))))
        elif m := _MD_IMAGE.match(line):
            flush()
            ref = m.group(2).encode()
            fig = Figure(
                image_id=hashlib.sha256(ref).hexdigest()[:32],
                source="embedded",
                alt_text=m.group(1) or None,
                analysable=False,  # linked file isn't part of the upload
            )
            blocks.append(Block(figure_text(fig), kind="figure", figure=fig))
        elif _MD_LIST.match(line):
            flush()
            blocks.append(Block(line, kind="list"))
        else:
            pending.append(line)
    flush()

    # A single "# X" that opens the file and is directly followed by another heading is the
    # document title, not section 1 ("# Intro" followed by body text stays a section).
    h1 = [b for b in blocks if b.level == 1]
    if len(h1) == 1 and blocks[0] is h1[0] and len(blocks) > 1 and blocks[1].level:
        blocks[0].kind, blocks[0].level = "title", None
    return blocks
