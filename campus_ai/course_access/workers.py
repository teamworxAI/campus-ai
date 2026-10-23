"""Structure, table and text workers (A4): proposed fixes for the audit's issues.

Each worker turns an audit issue into a Fix: what to change, the new value,
how sure the code is and whether a person must look first. Rules in code make
every proposal that the document itself gives away (a typed list becomes a
list, a skipped heading level is closed, duplicate slide titles are numbered,
a header row is marked, the first heading becomes the title, the text before
a bare URL becomes its link text). The LLM router is asked only for
judgement: the document's language, and link text when the surrounding text
does not say where a link goes (short answers, so the classification task's
small model). Nothing is written back; the rebuild step
(A5) applies approved fixes. Academic content is never changed: structure,
markup and wording of links and titles only (master plan 3.2).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from json import dumps

from campus_ai.course_access.audit import BARE_URL, FAKE_LIST, LANGUAGE_TAG, VAGUE_LINKS, STRUCTURE, TABLES, TEXT, audit
from campus_ai.course_access.model_answers import CONFIDENCE_THRESHOLD, ask, confidence
from campus_ai.course_access.parser import Document, Heading, Link, ListItem, Paragraph, Table

MAX_LINK_TEXT = 100
MAX_HEADING_CANDIDATE = 60  # characters: a short paragraph without a final period may be a heading
LANGUAGE_SAMPLE = 600  # characters of text the language question is asked about
LANGUAGE_NAMES = {"english": "en", "french": "fr", "german": "de", "spanish": "es", "portuguese": "pt", "italian": "it",
                  "dutch": "nl", "français": "fr", "deutsch": "de", "español": "es", "português": "pt"}

LANGUAGE_SYSTEM = """You identify the language of a text from a university course document.
Answer with one JSON object and nothing else: {"language": "<lowercase ISO 639-1 code such as en or fr, with a region only if the text makes it clear, e.g. en-CA, pt-BR>", "confidence": <0.0 to 1.0>}
If the text mixes languages, give the main one."""

LINK_SYSTEM = """You write link text for a hyperlink in a university course document, for students who use a screen reader.
Answer with one JSON object and nothing else: {"text": "<link text>", "confidence": <0.0 to 1.0>}
Rules: the text says what the link points to (a page, a document, a video, an organisation), in at most 8 words.
Use the surrounding text and the URL; never invent a title you cannot infer from them.
Not "click here", "link", "website" or the URL itself."""


@dataclass
class Fix:
    rule: str  # the audit rule it answers
    worker: str  # structure worker, table worker or text worker (audit.py names)
    action: str  # what to change; see ACTIONS
    value: object  # the proposed new value; None when a person must supply it
    confidence: float  # 0 to 1: rules give fixed values, the model its own estimate
    needs_review: bool
    review_reason: str  # "" when the fix can be applied as proposed
    evidence: str  # what the proposal rests on
    page: int | None = None
    block: int | None = None  # index into Document.blocks
    model: str = ""  # the model asked, if any


ACTIONS = {
    "convert-to-list": "make the paragraph a real list item",
    "set-heading-level": "change the heading's level",
    "retitle-slide": "number a repeated slide title",
    "add-slide-title": "give the slide a title",
    "promote-to-heading": "make the paragraph a heading",
    "mark-header-row": "mark the first row as the header row",
    "treat-as-layout": "the table is layout, not data: read its text as paragraphs",
    "set-title": "set the document title",
    "set-language": "set the document language",
    "set-link-text": "replace the link text",
}


def propose_fixes(document: Document, *, data_class: str, issues=None) -> list[Fix]:
    """One or more Fix proposals per structure, table and text issue the audit found."""
    issues = audit(document) if issues is None else issues
    fixes: list[Fix] = []
    for issue in issues:
        handler = HANDLERS.get(issue.rule)
        if handler:
            fixes.extend(handler(document, issue, data_class))
    return fixes


def _fix(issue, action, value, conf, evidence, worker=None, reason="", model="") -> Fix:
    reasons = [reason] if reason else []
    if value is None:
        reasons.append("no value could be derived; a person must supply one")
    elif conf < CONFIDENCE_THRESHOLD:
        reasons.append(f"confidence {conf:.2f} is below {CONFIDENCE_THRESHOLD}")
    return Fix(issue.rule, worker or issue.fix, action, value, conf, bool(reasons), "; ".join(reasons), evidence,
               issue.page, issue.block, model)


# --- Structure worker -------------------------------------------------------

def list_item_from(text: str) -> dict | None:
    """The list item a typed list line stands for ({text, ordered, level}), or None if it is not one."""
    match = FAKE_LIST.match(text)
    if not match:
        return None
    marker = match.group(1)
    return {"text": text[match.end(1):].strip(), "ordered": any(ch.isalnum() for ch in marker), "level": 1}


def fake_list(document, issue, data_class):
    text = document.blocks[issue.block].text
    item = list_item_from(text)
    return [_fix(issue, "convert-to-list", item, 0.9,
                 f"the paragraph starts with the list marker {FAKE_LIST.match(text).group(1)!r}")]


def heading_level_skipped(document, issue, data_class):
    previous = next((b.level for b in reversed(document.blocks[:issue.block]) if isinstance(b, Heading)), 0)
    return [_fix(issue, "set-heading-level", previous + 1, 0.8,
                 f"the previous heading is level {previous}, so the next level down is {previous + 1}")]


def slide_title_duplicate(document, issue, data_class):
    heading = document.blocks[issue.block]
    key = heading.text.strip().lower()
    same = [i for i, b in enumerate(document.blocks)
            if isinstance(b, Heading) and b.level == 1 and b.text.strip().lower() == key]
    n, m = same.index(issue.block) + 1, len(same)
    return [_fix(issue, "retitle-slide", f"{heading.text.strip()} ({n} of {m})", 0.9,
                 f"the same title is on {m} slides; numbering them tells them apart (WCAG 2.4.6)")]


def slide_no_title(document, issue, data_class):
    first = next((b for b in document.blocks if b.page == issue.page and isinstance(b, (Paragraph, ListItem))
                  and b.text.strip()), None)
    if first is None:
        return [_fix(issue, "add-slide-title", None, 0.0, "the slide has no text to take a title from")]
    return [_fix(issue, "add-slide-title", first.text.strip()[:80], 0.6,
                 "the first text on the slide", reason="a person should confirm it names the slide's subject")]


def no_headings(document, issue, data_class):
    fixes = []
    blocks = document.blocks
    for i, block in enumerate(blocks[:-1]):
        nxt = blocks[i + 1]
        if (isinstance(block, Paragraph) and isinstance(nxt, (Paragraph, ListItem))
                and len(block.text) <= MAX_HEADING_CANDIDATE and not block.text.rstrip().endswith((".", ":", ";", ","))
                and len(nxt.text) > len(block.text)):
            fix = _fix(issue, "promote-to-heading", {"level": 1}, 0.5,
                       "a short line without a final period, followed by a longer paragraph")
            fix.page, fix.block = block.page, i
            fixes.append(fix)
    return fixes


# --- Table worker -----------------------------------------------------------

def table_no_header_row(document, issue, data_class):
    table: Table = document.blocks[issue.block]
    cells = [c for row in table.rows for c in row]
    empty = sum(not c.strip() for c in cells) / max(len(cells), 1)
    width = max(len(row) for row in table.rows)
    multiline = any("\n" in c for c in cells)
    if width == 1 or empty >= 0.4 or (len(table.rows) <= 2 and multiline):
        why = ("one column" if width == 1 else f"{empty:.0%} of the cells are empty" if empty >= 0.4
               else "two rows of multi-line text")
        return [_fix(issue, "treat-as-layout", True, 0.75, f"{why}: this is page layout, not a data table")]
    first = [c.strip() for c in table.rows[0]]
    header_like = (all(first) and all(len(c) <= 40 for c in first) and len(set(first)) == len(first)
                   and not any(re.fullmatch(r"[\d.,%$€£\s-]+", c) for c in first))
    if header_like:
        return [_fix(issue, "mark-header-row", True, 0.85, "every cell in the first row is short, distinct, non-numeric text")]
    return [_fix(issue, "mark-header-row", True, 0.5, "the first row has empty, long or numeric cells",
                 reason="the first row may not be column headings")]


# --- Text worker ------------------------------------------------------------

def document_no_title(document, issue, data_class):
    heading = next((b for b in document.blocks if isinstance(b, Heading) and b.level == 1), None)
    if heading:
        return [_fix(issue, "set-title", heading.text.strip(), 0.85, "the document's first top-level heading")]
    paragraph = next((b for b in document.blocks if isinstance(b, Paragraph) and len(b.text) <= 100), None)
    if paragraph:
        return [_fix(issue, "set-title", paragraph.text.strip(), 0.5, "the first short paragraph",
                     reason="no heading to take a title from")]
    return [_fix(issue, "set-title", None, 0.0, "no heading or short paragraph to take a title from")]


def document_language(document, issue, data_class):
    sample = ""
    for block in document.blocks:
        if isinstance(block, (Heading, Paragraph, ListItem)):
            sample += block.text.strip() + "\n"
        elif isinstance(block, Table):  # PDF text often arrives inside layout "tables"
            sample += " ".join(c.strip() for row in block.rows for c in row if c.strip()) + "\n"
        if len(sample) >= LANGUAGE_SAMPLE:
            break
    if not sample.strip():
        return [_fix(issue, "set-language", None, 0.0, "the document has no text to judge the language from")]
    try:
        answer, model = ask("classification", f"Text:\n{sample[:LANGUAGE_SAMPLE]}", LANGUAGE_SYSTEM, data_class)
    except Exception as exc:  # the model being down or slow is a finding, not a crash
        return [_fix(issue, "set-language", None, 0.0, f"the model call failed: {type(exc).__name__}: {str(exc)[:120]}")]
    tag = str((answer or {}).get("language", "")).strip().strip("\"'.")
    tag = LANGUAGE_NAMES.get(tag.lower(), tag)  # the model sometimes answers with a name
    if not LANGUAGE_TAG.match(tag):
        return [_fix(issue, "set-language", None, 0.0, f"the model's answer was not a language tag: {tag!r}", model=model)]
    return [_fix(issue, "set-language", tag, confidence(answer.get("confidence")),
                 f"the model's judgement of the first {len(sample[:LANGUAGE_SAMPLE])} characters", model=model)]


def link_text(document, issue, data_class):
    link: Link = document.blocks[issue.block]
    before = next((b for b in reversed(document.blocks[:issue.block])
                   if isinstance(b, (Paragraph, ListItem, Heading)) and b.page == link.page), None)
    context = before.text.strip() if before else ""
    # The paragraph that holds a bare URL often names it first: "Timeline template: https://..."
    for url in {link.url, link.text.strip()}:
        if url and url in context:
            lead = context.split(url, 1)[0].strip().rstrip(":-–— ").strip()
            lead = lead.rsplit(". ", 1)[-1].strip() if len(lead) > MAX_LINK_TEXT else lead
            if 3 <= len(lead) <= MAX_LINK_TEXT and not BARE_URL.match(lead):
                return [_fix(issue, "set-link-text", lead, 0.85, "the text before the URL in the same paragraph")]
    prompt = (f"Document: {document.title or 'untitled'}\nCurrent link text: {link.text.strip()!r}\nURL: {link.url}\n"
              f"Text around the link:\n{context[:600] or '(none)'}")
    try:  # the classification task: a short answer from the small, fast model
        answer, model = ask("classification", prompt, LINK_SYSTEM, data_class)
    except Exception as exc:
        return [_fix(issue, "set-link-text", None, 0.0, f"the model call failed: {type(exc).__name__}: {str(exc)[:120]}")]
    text = " ".join(str((answer or {}).get("text", "")).split())
    if not text or len(text) > MAX_LINK_TEXT or BARE_URL.match(text) or text.lower().rstrip(".:!") in VAGUE_LINKS:
        return [_fix(issue, "set-link-text", None, 0.0, f"the model's answer was unusable: {text[:60]!r}", model=model)]
    return [_fix(issue, "set-link-text", text, confidence(answer.get("confidence")),
                 "the model's reading of the URL and the surrounding text", model=model)]


HANDLERS = {
    "fake-list": fake_list,
    "heading-level-skipped": heading_level_skipped,
    "slide-title-duplicate": slide_title_duplicate,
    "slide-no-title": slide_no_title,
    "no-headings": no_headings,
    "table-no-header-row": table_no_header_row,
    "document-no-title": document_no_title,
    "document-no-language": document_language,
    "document-bad-language": document_language,
    "link-bare-url": link_text,
    "link-no-text": link_text,
    "link-vague-text": link_text,
}
assert set(f.__name__ for f in HANDLERS.values()) and all(w in (STRUCTURE, TABLES, TEXT) for w in (STRUCTURE, TABLES, TEXT))


# --- Reports ----------------------------------------------------------------

def report_json(fixes: list[Fix]) -> str:
    return dumps([asdict(f) for f in fixes], indent=2, ensure_ascii=False)


def report_markdown(fixes: list[Fix], name: str = "") -> str:
    """A review sheet: every proposed fix, grouped by worker, with what to check."""
    review = sum(f.needs_review for f in fixes)
    lines = [f"# Proposed fixes{': ' + name if name else ''}", "",
             f"{len(fixes)} proposals; {review} need review, {len(fixes) - review} can be applied as proposed. "
             "Nothing is changed until approved.", ""]
    for worker in (STRUCTURE, TABLES, TEXT):
        own = [f for f in fixes if f.worker == worker]
        if not own:
            continue
        lines += [f"## {worker.capitalize()} ({len(own)})", "", "| Where | Rule | Action | Proposed value | Confidence | Review | Evidence |",
                  "|---|---|---|---|---|---|---|"]
        for f in own:
            where = f"page {f.page}" if f.page else ("document" if f.block is None else f"block {f.block}")
            value = "(none)" if f.value is None else (dumps(f.value, ensure_ascii=False) if isinstance(f.value, (dict, list, bool)) else str(f.value))
            value = value.replace("|", "\\|")[:120]
            review = f.review_reason.replace("|", "\\|") if f.needs_review else "no"
            lines.append(f"| {where} | {f.rule} | {f.action} | {value} | {f.confidence:.2f} | {review} | {f.evidence.replace('|', chr(92) + '|')} |")
        lines.append("")
    return "\n".join(lines)
