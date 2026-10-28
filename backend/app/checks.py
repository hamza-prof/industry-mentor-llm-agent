"""Rule-based format checks (no LLM): numbering, references, figures/tables, empty and
overlong content, required sections. Every finding is a Comment with origin="rule"."""

import re

from app.config import Settings
from app.schemas import Category, Comment, ParsedDocument, Section, Severity

LONG_PARAGRAPH = 1500
_ARABIC = re.compile(r"^(\d+(?:\.\d+)*)(?:[.、]\s*|\s+)")
_ZH_NUM = re.compile(r"^(?:第)?([一二三四五六七八九十]+)(?:、|章|\s)")
_REFS_HEADING = re.compile(r"参考文献|引用文献|references|bibliography", re.I)
_CITE = re.compile(r"\[(\d+(?:\s*[-–,，、]\s*\d+)*)\]")
_REF_ENTRY = re.compile(r"^\s*\[?(\d+)[\].、)]")
_FIG = r"(?:图|Figure|Fig\.?)\s*(\d+(?:[-.]\d+)*)"
_TAB = r"(?:表|Table)\s*(\d+(?:[-.]\d+)*)"
_ZH_DIGITS = "一二三四五六七八九"


def _zh_int(s: str) -> int:
    if s == "十":
        return 10
    if "十" in s:
        tens, _, ones = s.partition("十")
        return (_ZH_DIGITS.index(tens) + 1 if tens else 1) * 10 + (
            _ZH_DIGITS.index(ones) + 1 if ones else 0
        )
    return _ZH_DIGITS.index(s) + 1


def _zh_str(n: int) -> str:
    if n <= 9:
        return _ZH_DIGITS[n - 1]
    tens, ones = divmod(n, 10)
    return (
        (_ZH_DIGITS[tens - 1] if tens > 1 else "") + "十" + (_ZH_DIGITS[ones - 1] if ones else "")
    )


class _Out:
    def __init__(self, zh: bool):
        self.zh, self.items = zh, []

    def add(
        self,
        category: Category,
        severity: Severity,
        zh: str,
        en: str,
        section_id: str | None = None,
        paragraph_id: str | None = None,
        sug_zh: str = "",
        sug_en: str = "",
    ) -> None:
        self.items.append(
            Comment(
                section_id=section_id,
                paragraph_id=paragraph_id,
                anchored=paragraph_id is not None,
                category=category,
                severity=severity,
                problem=zh if self.zh else en,
                suggestion=sug_zh if self.zh else sug_en,
                origin="rule",
            )
        )


def _numbering(sections: list[Section], out: _Out) -> None:
    last: dict[tuple, tuple[int, int]] = {}  # (style, parent numbers) → (level, last number)
    for s in sections:
        # a higher-level heading starts a new run below it ("一、 1. 2. 二、 1. 2.")
        last = {k: v for k, v in last.items() if v[0] <= s.level}
        if m := _ARABIC.match(s.heading):
            nums = tuple(int(x) for x in m[1].split("."))
            key, show = ("arabic", nums[:-1]), lambda n, p=nums[:-1]: ".".join(map(str, (*p, n)))
        elif m := _ZH_NUM.match(s.heading):
            nums = (_zh_int(m[1]),)
            key, show = ("zh", ()), lambda n: _zh_str(n)
        else:
            continue
        n, prev = nums[-1], last.get(key, (0, 0))[1]
        if n == prev:
            out.add(
                "format",
                "medium",
                f"标题编号重复：{show(n)}",
                f"Duplicate heading number: {show(n)}",
                s.id,
                sug_zh="检查并修正标题编号。",
                sug_en="Fix the heading numbering.",
            )
        elif n > prev + 1:
            missing = "、".join(show(k) for k in range(prev + 1, n))
            out.add(
                "format",
                "medium",
                f"标题编号跳号：缺少 {missing}（{s.heading}）",
                f"Heading numbering skips {missing} (before '{s.heading}')",
                s.id,
                sug_zh="补充缺失的小节或修正编号。",
                sug_en="Add the missing section or renumber.",
            )
        last[key] = (s.level, max(n, prev))


def _references(parsed: ParsedDocument, out: _Out) -> None:
    refs = next((s for s in parsed.sections if _REFS_HEADING.search(s.heading)), None)
    body = [
        (s, p) for s in parsed.sections if s is not refs for p in s.paragraphs if p.kind != "figure"
    ]
    cited: dict[int, str] = {}
    for _, p in body:
        for m in _CITE.finditer(p.text):
            for part in re.split(r"[,，、]", m[1]):
                lo, _, hi = part.replace("–", "-").replace(" ", "").partition("-")
                for k in range(int(lo), int(hi or lo) + 1):
                    cited.setdefault(k, p.id)
    if refs is None:
        if cited or parsed.doc_type != "technical":
            out.add(
                "citation",
                "medium",
                "缺少参考文献部分。",
                "There is no references section.",
                sug_zh="增加“参考文献”一节，列出正文引用的所有来源。",
                sug_en="Add a references section listing every source cited in the text.",
            )
        return
    entries: dict[int, str] = {}
    for i, p in enumerate(refs.paragraphs, 1):
        m = _REF_ENTRY.match(p.text)
        entries.setdefault(int(m[1]) if m else i, p.id)
    for k, pid in cited.items():
        if k not in entries:
            out.add(
                "citation",
                "high",
                f"引用 [{k}] 在参考文献中不存在。",
                f"Citation [{k}] is not in the reference list.",
                pid.split(".")[0],
                pid,
                sug_zh=f"在参考文献中补充第 {k} 条，或修正引用编号。",
                sug_en=f"Add reference {k} or fix the citation number.",
            )
    for k, pid in entries.items():
        if k not in cited:
            out.add(
                "citation",
                "low",
                f"参考文献 [{k}] 在正文中未被引用。",
                f"Reference [{k}] is never cited in the text.",
                refs.id,
                pid,
            )


def _figures_and_tables(parsed: ParsedDocument, out: _Out) -> None:
    paras = [(s, p) for s in parsed.sections for p in s.paragraphs]
    for kind_zh, kind_en, pattern, is_fig in (
        ("图", "Figure", _FIG, True),
        ("表", "Table", _TAB, False),
    ):
        caption_re = re.compile(r"^\s*" + pattern, re.I)
        captions: list[tuple[str, str, str]] = []  # (number, section_id, paragraph_id)
        refs: dict[str, str] = {}
        for s, p in paras:
            if is_fig and p.kind == "figure":
                cap = p.figure.caption if p.figure else None
                if m := caption_re.match(cap or ""):
                    captions.append((m[1], s.id, p.id))
                else:
                    out.add(
                        "format",
                        "low",
                        "图片缺少图注（如“图1 …”）。",
                        "Figure has no caption.",
                        s.id,
                        p.id,
                        sug_zh="为图片添加编号和图注。",
                        sug_en="Add a numbered caption, e.g. 'Figure 1 …'.",
                    )
                if p.figure and not p.figure.analysable:
                    out.add(
                        "format",
                        "low",
                        "该图片格式无法自动分析，请人工查看。",
                        "This figure's format can't be analysed automatically; check it by eye.",
                        s.id,
                        p.id,
                    )
                continue
            if not is_fig and (m := caption_re.match(p.text)):
                captions.append((m[1], s.id, p.id))
            for m in re.finditer(pattern, p.text, re.I):
                refs.setdefault(m[1], p.id)
        seen: dict[str, str] = {}
        for num, sid, pid in captions:
            if num in seen:
                out.add(
                    "format",
                    "medium",
                    f"{kind_zh}{num} 编号重复。",
                    f"{kind_en} {num} is numbered twice.",
                    sid,
                    pid,
                )
            seen.setdefault(num, pid)
        ints = sorted(int(n) for n in seen if n.isdigit())
        for k in sorted(set(range(1, ints[-1] + 1)) - set(ints)) if ints else []:
            out.add(
                "format",
                "low",
                f"{kind_zh}编号不连续：缺少{kind_zh}{k}。",
                f"{kind_en} numbering skips {kind_en} {k}.",
                captions[0][1],
            )
        for num, pid in refs.items():
            if num not in seen:
                out.add(
                    "format",
                    "medium",
                    f"正文引用了{kind_zh}{num}，但文中没有该{kind_zh}。",
                    f"The text refers to {kind_en} {num}, but there is no such {kind_en.lower()}.",
                    pid.split(".")[0],
                    pid,
                )
        if is_fig:
            for num, sid, pid in captions:
                if num not in refs and seen.get(num) == pid:
                    out.add(
                        "format",
                        "low",
                        f"{kind_zh}{num} 在正文中未被提及。",
                        f"{kind_en} {num} is never referred to in the text.",
                        sid,
                        pid,
                        sug_zh=f"在正文中说明{kind_zh}{num}支持的结论。",
                        sug_en=f"Explain in the text what {kind_en} {num} shows.",
                    )


def _empty_and_long(parsed: ParsedDocument, out: _Out) -> None:
    secs = parsed.sections
    for i, s in enumerate(secs):
        has_children = i + 1 < len(secs) and secs[i + 1].level > s.level
        if not s.paragraphs and not has_children:
            out.add(
                "completeness",
                "medium",
                f"“{s.heading}”一节没有内容。",
                f"Section '{s.heading}' is empty.",
                s.id,
            )
        for p in s.paragraphs:
            if p.kind == "text" and len(p.text) > LONG_PARAGRAPH:
                out.add(
                    "clarity",
                    "low",
                    f"段落过长（{len(p.text)} 字），建议拆分。",
                    f"Very long paragraph ({len(p.text)} characters); consider splitting it.",
                    s.id,
                    p.id,
                )


def _required(parsed: ParsedDocument, required: dict[str, list[list[str]]], out: _Out) -> None:
    headings = " ".join(s.heading for s in parsed.sections).lower()
    for alternatives in required.get(parsed.doc_type, []):
        if not any(a.lower() in headings for a in alternatives):
            zh = next((a for a in alternatives if not a.isascii()), alternatives[0])
            en = next((a for a in alternatives if a.isascii()), alternatives[0])
            out.add(
                "completeness",
                "high",
                f"缺少必需部分：{zh}。",
                f"Required section missing: {en}.",
                sug_zh=f"增加“{zh}”相关章节。",
                sug_en=f"Add a section on {en}.",
            )


def format_checks(
    parsed: ParsedDocument, required_sections: dict[str, list[list[str]]] | None = None
) -> list[Comment]:
    if required_sections is None:
        required_sections = Settings.model_fields["required_sections"].default
    out = _Out(parsed.language == "zh")
    _numbering(parsed.sections, out)
    _references(parsed, out)
    _figures_and_tables(parsed, out)
    _empty_and_long(parsed, out)
    _required(parsed, required_sections, out)
    return out.items
