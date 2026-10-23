"""Deterministic accessibility audit of a parsed course document (A2).

Code checks what can be checked from the Document the parser (A1) returns.
Every issue names the WCAG 2.2 success criterion it fails, where it is, and
which step can fix it: a worker (A3 alt text, A4 structure, tables, text) or a
person. No model is involved here (AGENTS.md: deterministic code for anything
checkable).

The audit cannot see everything (colour contrast, whether alt text is
accurate, whether reading order makes sense). Those are listed in NOT_CHECKED
and printed in every report, so a short issue list is never mistaken for
conformance.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass

from campus_ai.course_access.parser import Document, Equation, Heading, Image, Link, ListItem, Paragraph, Table

# WCAG 2.2 success criteria used by the rules: number -> (name, level).
CRITERIA = {
    "1.1.1": ("Non-text Content", "A"),
    "1.3.1": ("Info and Relationships", "A"),
    "1.4.5": ("Images of Text", "AA"),
    "2.4.2": ("Page Titled", "A"),
    "2.4.4": ("Link Purpose (In Context)", "A"),
    "2.4.6": ("Headings and Labels", "AA"),
    "3.1.1": ("Language of Page", "A"),
}

NOT_CHECKED = [
    "1.4.3 Contrast (Minimum): text and background colours are not extracted yet",
    "1.1.1 Non-text Content: whether existing alt text is accurate (needs a person or the A3 judge)",
    "1.3.2 Meaningful Sequence: whether the reading order makes sense",
    "1.3.1 Info and Relationships: PDF structure tags (the parser reads untagged text)",
    "3.1.2 Language of Parts: passages in another language",
    "Equations that are images, charts and diagrams: always sent to human review",
    "Native equations are preserved as MathML (OMML in DOCX/PPTX), but whether their reading is right needs a person",
]

# Fixers, matching the agent design (master plan 3.2).
ALT_TEXT, STRUCTURE, TABLES, TEXT, PERSON = "alt-text worker", "structure worker", "table worker", "text worker", "person"

GENERIC_ALT = {"image", "picture", "photo", "graphic", "figure", "img", "chart", "diagram", "logo", "icon",
               "untitled", "placeholder", "screenshot", "image1", "picture1"}
FILENAME_ALT = re.compile(r"^[\w\-. ]+\.(png|jpe?g|gif|bmp|tiff?|svg|webp|emf|wmf)$", re.IGNORECASE)
VAGUE_LINKS = {"click here", "here", "click", "more", "read more", "learn more", "link", "this link", "this",
               "details", "more info", "info", "go", "page", "website", "download"}
BARE_URL = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
FAKE_LIST = re.compile(r"^\s*([-•▪◦*–·]|\(?\d{1,2}[.)]|\(?[a-z][.)])\s+\S")
LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$")
MIN_PARAGRAPHS_FOR_HEADINGS = 5


@dataclass
class Issue:
    rule: str  # stable rule id, e.g. "image-missing-alt"
    criterion: str  # WCAG success criterion, e.g. "1.1.1"
    message: str
    fix: str  # who or what can fix it
    page: int | None = None
    block: int | None = None  # index into Document.blocks

    @property
    def level(self) -> str:
        return CRITERIA[self.criterion][1]


def audit(document: Document) -> list[Issue]:
    """All issues found, in document order (document-level issues first)."""
    issues = _document_checks(document)
    issues += _heading_checks(document)
    blocks = document.blocks
    for i, block in enumerate(blocks):
        where = {"page": block.page, "block": i}
        if isinstance(block, Image):
            issues += [Issue(**x, **where) for x in _image_checks(block)]
        elif isinstance(block, Table) and not block.has_header_row and len(block.rows) > 1:
            issues.append(Issue("table-no-header-row", "1.3.1",
                                "Table has no header row, so cells can't be related to their column headings.",
                                TABLES, **where))
        elif isinstance(block, Link):
            issues += [Issue(**x, **where) for x in _link_checks(block)]
        elif isinstance(block, Equation) and not block.text.strip():
            issues.append(Issue("equation-empty", "1.1.1",
                                "Equation has no readable content, so a screen reader has nothing to speak.",
                                PERSON, **where))
        elif isinstance(block, Paragraph) and FAKE_LIST.match(block.text):
            issues.append(Issue("fake-list", "1.3.1",
                                f"Text looks like a list item but isn't marked up as one: {block.text[:60]!r}",
                                STRUCTURE, **where))
    issues += _image_only_pages(document)
    return issues


def _document_checks(document: Document) -> list[Issue]:
    issues = []
    if not document.title:
        issues.append(Issue("document-no-title", "2.4.2", "Document has no title in its properties.", TEXT))
    if not document.language:
        issues.append(Issue("document-no-language", "3.1.1",
                            "Document language is not set, so screen readers may use the wrong voice.", TEXT))
    elif not LANGUAGE_TAG.match(document.language):
        issues.append(Issue("document-bad-language", "3.1.1",
                            f"Document language {document.language!r} is not a valid language tag.", TEXT))
    return issues


def _heading_checks(document: Document) -> list[Issue]:
    issues = []
    headings = [(i, b) for i, b in enumerate(document.blocks) if isinstance(b, Heading)]
    paragraphs = sum(isinstance(b, (Paragraph, ListItem)) for b in document.blocks)
    if not headings and paragraphs >= MIN_PARAGRAPHS_FOR_HEADINGS:
        where = "PDF text has no heading markup" if document.source_format == "pdf" else "no headings are marked up"
        issues.append(Issue("no-headings", "1.3.1",
                            f"{paragraphs} paragraphs but {where}, so the document can't be navigated by heading.",
                            STRUCTURE))
    previous = 0
    for i, heading in headings:
        if previous and heading.level > previous + 1:
            issues.append(Issue("heading-level-skipped", "1.3.1",
                                f"Heading level jumps from {previous} to {heading.level}: {heading.text[:60]!r}",
                                STRUCTURE, heading.page, i))
        previous = heading.level
    if document.source_format == "pptx":
        titled = {h.page for _, h in headings}
        for page in range(1, (document.page_count or 0) + 1):
            if page not in titled:
                issues.append(Issue("slide-no-title", "2.4.6", f"Slide {page} has no title.", STRUCTURE, page))
        counts = Counter(h.text.strip().lower() for _, h in headings if h.level == 1)
        for i, heading in headings:
            if heading.level == 1 and counts[heading.text.strip().lower()] > 1:
                issues.append(Issue("slide-title-duplicate", "2.4.6",
                                    f"Slide title {heading.text[:60]!r} is used on more than one slide.",
                                    STRUCTURE, heading.page, i))
    return issues


def _image_checks(image: Image) -> list[dict]:
    if image.decorative:
        return []
    if image.alt is None:
        return [dict(rule="image-missing-alt", criterion="1.1.1",
                     message="Image has no alt text and is not marked decorative.", fix=ALT_TEXT)]
    alt = image.alt.strip()
    if FILENAME_ALT.match(alt) or alt.lower() in GENERIC_ALT:
        return [dict(rule="image-placeholder-alt", criterion="1.1.1",
                     message=f"Alt text {alt!r} is a file name or placeholder, not a description.", fix=ALT_TEXT)]
    return []


def _link_checks(link: Link) -> list[dict]:
    text = link.text.strip()
    if not text:
        return [dict(rule="link-no-text", criterion="2.4.4",
                     message=f"Link to {link.url} has no text.", fix=TEXT)]
    if text.lower().rstrip(".:!") in VAGUE_LINKS:
        return [dict(rule="link-vague-text", criterion="2.4.4",
                     message=f"Link text {text!r} doesn't say where it goes ({link.url}).", fix=TEXT)]
    if BARE_URL.match(text):
        return [dict(rule="link-bare-url", criterion="2.4.4",
                     message=f"Link text is a raw URL: {text[:60]!r}.", fix=TEXT)]
    return []


def _image_only_pages(document: Document) -> list[Issue]:
    """PDF pages with images and no text: likely scanned, so text is an image."""
    if document.source_format != "pdf":
        return []
    text_pages = {b.page for b in document.blocks if isinstance(b, (Heading, Paragraph, ListItem, Table))}
    image_pages = sorted({b.page for b in document.blocks if isinstance(b, Image)} - text_pages)
    return [Issue("page-image-only", "1.4.5",
                  f"Page {page} has images but no text: it may be scanned. OCR is next phase (A7); a person must "
                  "check it until then.", PERSON, page) for page in image_pages]


# --- Reports ----------------------------------------------------------------

def report_dict(document: Document, issues: list[Issue], name: str = "") -> dict:
    by_criterion = Counter(issue.criterion for issue in issues)
    return {
        "document": name,
        "format": document.source_format,
        "title": document.title,
        "language": document.language,
        "pages": document.page_count,
        "standard": "WCAG 2.2 AA",
        "issue_count": len(issues),
        "by_criterion": {
            c: {"name": CRITERIA[c][0], "level": CRITERIA[c][1], "count": by_criterion[c]}
            for c in sorted(by_criterion)
        },
        "issues": [{**asdict(issue), "level": issue.level, "criterion_name": CRITERIA[issue.criterion][0]}
                   for issue in issues],
        "not_checked": NOT_CHECKED,
    }


def report_json(document: Document, issues: list[Issue], name: str = "") -> str:
    return json.dumps(report_dict(document, issues, name), ensure_ascii=False, indent=2)


def report_markdown(document: Document, issues: list[Issue], name: str = "") -> str:
    lines = [f"# Accessibility audit: {name or document.title or 'document'}", "",
             f"Checked against WCAG 2.2 AA. Format: {document.source_format.upper()}"
             + (f", {document.page_count} pages" if document.page_count else "") + ".", ""]
    if issues:
        lines += [f"**{len(issues)} issue(s) found.**", "", "| Criterion | Level | Issues |", "|---|---|---|"]
        for c, n in sorted(Counter(i.criterion for i in issues).items()):
            lines.append(f"| {c} {CRITERIA[c][0]} | {CRITERIA[c][1]} | {n} |")
        lines += ["", "## Issues", "", "| # | Where | Criterion | Problem | Fixed by |", "|---|---|---|---|---|"]
        for n, issue in enumerate(issues, start=1):
            where = f"page {issue.page}" if issue.page else ("document" if issue.block is None else "body")
            message = issue.message.replace("|", "\\|")
            lines.append(f"| {n} | {where} | {issue.criterion} | {message} | {issue.fix} |")
    else:
        lines += ["No issues found by the automatic checks."]
    lines += ["", "## Not checked automatically", "",
              "A short list above does not mean the document conforms. These need other checks or a person:", ""]
    lines += [f"- {item}" for item in NOT_CHECKED]
    return "\n".join(lines) + "\n"
