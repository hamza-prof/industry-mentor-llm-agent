from typing import Literal

from pydantic import BaseModel, computed_field

DocType = Literal["report", "proposal", "technical"]


class Figure(BaseModel):
    image_id: str  # sha256[:32] of the original bytes → same image = same file
    file: str | None = None  # PNG name inside the document's figures/ dir
    width: int = 0
    height: int = 0
    source: Literal["embedded", "docx_chart", "pdf_vector"]
    caption: str | None = None
    alt_text: str | None = None
    chart_data: str | None = None  # chart values (DOCX charts) or text found inside the figure
    analysable: bool = True


class Paragraph(BaseModel):
    id: str  # "S3.P2"
    text: str
    page: int | None = None
    kind: Literal["text", "table", "list", "figure"] = "text"
    figure: Figure | None = None


class Section(BaseModel):
    id: str  # "S3"; "S0" = front matter
    heading: str
    level: int
    paragraphs: list[Paragraph] = []


class ParsedDocument(BaseModel):
    filename: str
    doc_type: DocType
    language: Literal["zh", "en"]
    title: str | None = None
    sections: list[Section]
    warnings: list[str] = []

    def _paragraphs(self):
        return (p for s in self.sections for p in s.paragraphs)

    def paragraph(self, pid: str) -> Paragraph | None:
        return next((p for p in self._paragraphs() if p.id == pid), None)

    def all_paragraph_ids(self) -> list[str]:
        return [p.id for p in self._paragraphs()]

    def figures(self) -> list[Paragraph]:
        return [p for p in self._paragraphs() if p.kind == "figure"]

    @computed_field
    @property
    def figure_count(self) -> int:
        return len(self.figures())

    @computed_field
    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self._paragraphs() if p.kind != "figure")


# ---- structured summary (feature 1) -------------------------------------------


class SummaryField(BaseModel):
    """One summary item. If the material doesn't contain it: text=null, not_found=true."""

    text: str | None = None
    not_found: bool = False
    source_ids: list[str] = []  # paragraph labels it is based on, e.g. ["S3.P2"]


class OutlineItem(BaseModel):
    section_id: str  # "S3"
    heading: str
    one_line: str = ""  # one-sentence summary of the section


class SummaryOutput(BaseModel):
    """What the model fills in (with_structured_output)."""

    research_problem: SummaryField
    objectives: SummaryField
    technical_approach: SummaryField
    main_conclusions: SummaryField
    innovations: SummaryField
    limitations: SummaryField
    outline: list[OutlineItem] = []


class StructuredSummary(SummaryOutput):
    title: str | None = None
    doc_type: DocType
    warnings: list[str] = []


# ---- review (features 2 + 3) ---------------------------------------------------

Category = Literal[
    "evidence",
    "feasibility",
    "logic",
    "format",
    "completeness",
    "clarity",
    "innovation",
    "citation",
]
Severity = Literal["high", "medium", "low"]
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


class FigureDescription(BaseModel):
    """What the vision model sees in one figure."""

    kind: Literal["chart", "diagram", "table_image", "screenshot", "photo", "formula", "other"]
    summary: str
    key_data: list[str] = []  # values read off the figure, e.g. "2023: 280 orders"
    readable: bool = True
    issues: list[str] = []  # e.g. "y-axis has no unit"; empty if the figure is fine


class RawComment(BaseModel):
    """One problem found by the model in a section."""

    paragraph_id: str | None = None  # label like "S3.P2"; null = about the whole section
    quote: str | None = None  # exact words from that paragraph
    category: Category
    severity: Severity
    problem: str
    suggestion: str
    revision_steps: list[str] = []
    standard_refs: list[str] = []  # labels like "K2" of the standard excerpts it relies on


class SectionReview(BaseModel):
    comments: list[RawComment] = []


class Comment(BaseModel):
    """A validated comment, ready to save: the anchor points at real text."""

    section_id: str | None = None  # None = about the whole document
    paragraph_id: str | None = None
    quote: str | None = None
    anchored: bool = False
    category: Category
    severity: Severity
    problem: str
    suggestion: str = ""
    revision_steps: list[str] = []
    standard_refs: list[str] = []
    origin: Literal["ai", "rule", "mentor"] = "ai"


class KBHit(BaseModel):
    """One knowledge-base chunk returned by search."""

    chunk_id: str  # "{source_id}:{n}"
    source_id: int
    filename: str
    category: str
    text: str
    score: float
