"""Rebuild an accessible document from approved proposals, and verify it (A5).

`apply` takes the parsed Document, the approved fixes (A4) and alt texts
(A3) and returns a new Document with them applied: structure, markup,
titles, link text and image descriptions change; the words of the course do
not. `to_html` and `to_docx` write the accessible versions. `verify`
parses and audits the rebuilt DOCX again, so the result is measured by the
same checks as the original, and `statement` writes what was found, fixed,
left and not checked, so the output is never mistaken for full conformance.

Nothing here decides what is approved: the caller passes the proposals a
person (or, for rule-based ones, the confidence threshold) has approved.
"""

from __future__ import annotations

import base64
import copy
import html
import re
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import docx
from docx.oxml import parse_xml
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

from campus_ai.course_access.alt_text import AltText
from campus_ai.course_access.audit import NOT_CHECKED, Issue, audit
from campus_ai.course_access.parser import Block, Document, Equation, Heading, Image, Link, ListItem, Paragraph, Table, parse
from campus_ai.course_access.workers import Fix, list_item_from

DOCX_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"}
# Control characters that XML (so DOCX) refuses. PPTX soft line breaks arrive as \x0b.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(text: str) -> str:
    """Text safe for XML and HTML: control characters become spaces (a soft line break is a space)."""
    return CONTROL.sub(" ", text or "")
DECORATIVE_EXT_URI = "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"
ADEC_NS = "http://schemas.microsoft.com/office/drawing/2017/decorative"


# --- Applying proposals ------------------------------------------------------

def apply(document: Document, fixes: list[Fix] = (), alt_texts: list[AltText] = ()) -> Document:
    """A new Document with the given (approved) proposals applied; the input is untouched."""
    out = copy.deepcopy(document)
    blocks: list[Block | list[Block] | None] = list(out.blocks)  # a slot may become several blocks, or none
    for alt in alt_texts:
        image = blocks[alt.block]
        if isinstance(image, Image):
            image.decorative = alt.decorative
            image.alt = "" if alt.decorative else (alt.alt or image.alt)
    inserts: list[tuple[int, Heading]] = []
    for fix in fixes:
        if fix.value is None or fix.action == "ocr":  # ocr: the recognised text is already in the blocks
            continue
        if fix.action == "set-title":
            out.title = str(fix.value)
        elif fix.action == "set-language":
            out.language = str(fix.value)
        elif fix.action == "add-slide-title":
            _add_slide_title(blocks, fix, inserts)
        elif fix.block is None:
            continue
        else:
            blocks[fix.block] = _apply_to_block(blocks[fix.block], fix)
    for index, heading in sorted(inserts, reverse=True):
        blocks.insert(index, heading)
    out.blocks = [b for slot in blocks for b in (slot if isinstance(slot, list) else [slot]) if b is not None]
    return out


def _apply_to_block(block, fix: Fix):
    if isinstance(block, list):  # already replaced by an earlier fix
        return block
    if fix.action == "convert-to-list" and isinstance(block, Paragraph):
        v = fix.value
        return ListItem(text=v["text"], level=int(v.get("level", 1)), ordered=bool(v.get("ordered")), page=block.page)
    if fix.action == "set-heading-level" and isinstance(block, Heading):
        block.level = int(fix.value)
    elif fix.action == "retitle-slide" and isinstance(block, Heading):
        block.text = str(fix.value)
    elif fix.action == "promote-to-heading" and isinstance(block, Paragraph):
        return Heading(text=block.text, level=int(fix.value.get("level", 1)), page=block.page)
    elif fix.action == "mark-header-row" and isinstance(block, Table):
        block.has_header_row = True
    elif fix.action == "treat-as-layout" and isinstance(block, Table):
        return [_layout_line(line.strip(), block.page)
                for row in block.rows for cell in row for line in cell.split("\n") if line.strip()]
    elif fix.action == "set-link-text" and isinstance(block, Link):
        block.text = str(fix.value)
    return block


def _layout_line(text: str, page) -> Paragraph | ListItem:
    """A line from a layout table: a typed bullet becomes a real list item, as the fake-list rule would propose."""
    item = list_item_from(text)
    if item:
        return ListItem(text=item["text"], level=item["level"], ordered=item["ordered"], page=page)
    return Paragraph(text=text, page=page)


def _add_slide_title(blocks, fix: Fix, inserts):
    """The slide's first line becomes its title; a new heading if the title came from elsewhere."""
    for i, block in enumerate(blocks):
        if isinstance(block, (Paragraph, ListItem)) and block.page == fix.page and block.text.strip() == str(fix.value):
            blocks[i] = Heading(text=block.text.strip(), level=1, page=block.page)
            return
    first = next((i for i, b in enumerate(blocks) if b is not None and not isinstance(b, list) and b.page == fix.page),
                 len(blocks))
    inserts.append((first, Heading(text=str(fix.value), level=1, page=fix.page)))


# --- HTML -------------------------------------------------------------------

def to_html(document: Document) -> str:
    """One accessible HTML page: language, title, headings, real lists, header cells, alt text."""
    lang = html.escape(document.language or "")
    title = html.escape(document.title or "Untitled document")
    out = [f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n<title>{title}</title>\n</head>\n<body>\n<main>']
    slides = document.source_format == "pptx"
    page = None
    lists: list[tuple[int, str]] = []  # open lists: (level, tag)

    def close_lists(to_level=0):
        while lists and lists[-1][0] > to_level:
            out.append(f"</{lists.pop()[1]}>")

    for block, links in _group_links(document.blocks):
        if slides and block.page != page:
            close_lists()
            if page is not None:
                out.append("</section>")
            page = block.page
            out.append(f'<section aria-label="Slide {page}">')
        if isinstance(block, (Heading, Paragraph, ListItem)):
            segments, leftover = _segments(clean(block.text), links)
            inner = "".join(html.escape(s) if isinstance(s, str) else _html_link(s) for s in segments)
        else:
            inner, leftover = "", links
        if isinstance(block, ListItem):
            tag = "ol" if block.ordered else "ul"
            close_lists(block.level)
            if lists and lists[-1][0] == block.level and lists[-1][1] != tag:
                out.append(f"</{lists.pop()[1]}>")
            while len(lists) < block.level:
                lists.append((len(lists) + 1, tag))
                out.append(f"<{tag}>")
            out.append(f"<li>{inner}</li>")
        else:
            close_lists()
            if isinstance(block, Heading):
                level = min(max(block.level, 1), 6)
                out.append(f"<h{level}>{inner}</h{level}>")
            elif isinstance(block, Paragraph):
                out.append(f"<p>{inner}</p>")
            elif isinstance(block, Table):
                out.append(_html_table(block))
            elif isinstance(block, Image):
                out.append(_html_image(block))
            elif isinstance(block, Link):
                out.append(f"<p>{_html_link(block)}</p>")
            elif isinstance(block, Equation):
                out.append(_html_equation(block))
        out += [f"<p>{_html_link(link)}</p>" for link in leftover]
    close_lists()
    if slides and page is not None:
        out.append("</section>")
    out.append("</main>\n</body>\n</html>\n")
    return "\n".join(out)


def _group_links(blocks):
    """(block, links): the parser puts the links of a text block right after it; give them back to it."""
    i = 0
    while i < len(blocks):
        block, links = blocks[i], []
        i += 1
        if isinstance(block, (Heading, Paragraph, ListItem)):
            while i < len(blocks) and isinstance(blocks[i], Link):
                links.append(blocks[i])
                i += 1
        yield block, links


def _segments(text: str, links: list[Link]):
    """Split `text` around the link texts it contains, in order: strings and Links; the rest of the links stand alone."""
    segments: list = [text]
    leftover = []
    for link in links:
        last = segments[-1]
        if link.text and isinstance(last, str) and link.text in last:
            before, after = last.split(link.text, 1)
            segments[-1:] = [before, link, after]
        else:
            leftover.append(link)
    return [s for s in segments if s != ""], leftover


def _html_link(link: Link) -> str:
    return f'<a href="{html.escape(link.url, quote=True)}">{html.escape(link.text or link.url)}</a>'


def _html_table(table: Table) -> str:
    rows = [[html.escape(c) for c in row] for row in table.rows]
    parts = ["<table>"]
    body = rows
    if table.has_header_row and rows:
        parts.append("<thead><tr>" + "".join(f'<th scope="col">{c}</th>' for c in rows[0]) + "</tr></thead>")
        body = rows[1:]
    parts.append("<tbody>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in body) + "</tbody>")
    parts.append("</table>")
    return "".join(parts)


def _html_equation(equation: Equation) -> str:
    """The equation as MathML (its alttext is the linearised text); plain text if there is no MathML."""
    if equation.mathml:
        return equation.mathml
    return f"<p>{html.escape(clean(equation.text))}</p>"


def _html_image(image: Image) -> str:
    media = {"jpg": "jpeg", "tif": "tiff"}.get(image.format.lower(), image.format.lower())
    src = f"data:image/{media};base64,{base64.b64encode(image.data).decode()}"
    if image.decorative:
        return f'<img src="{src}" alt="" role="presentation">'
    if image.alt:
        return f'<img src="{src}" alt="{html.escape(image.alt, quote=True)}">'
    return f'<img src="{src}">'  # no alt text yet: left visible to checkers, never faked


# --- DOCX -------------------------------------------------------------------

def to_docx(document: Document, path: str | Path) -> list[str]:
    """Write an accessible DOCX; returns notes about what could not be carried over."""
    out = docx.Document()
    out.core_properties.title = clean(document.title)
    if document.language:
        out.core_properties.language = document.language
        _set_default_language(out, document.language)
    notes = []
    for block, links in _group_links(document.blocks):
        leftover = links
        if isinstance(block, Heading):
            paragraph = out.add_heading("", level=min(max(block.level, 1), 9))
            leftover = _docx_runs(paragraph, block.text, links)
        elif isinstance(block, Paragraph):
            leftover = _docx_runs(out.add_paragraph(), block.text, links)
        elif isinstance(block, ListItem):
            style = "List Number" if block.ordered else "List Bullet"
            paragraph = out.add_paragraph(style=style)
            _docx_list_level(out, paragraph, style, block.level)
            leftover = _docx_runs(paragraph, block.text, links)
        elif isinstance(block, Table):
            _docx_table(out, block)
        elif isinstance(block, Image):
            note = _docx_image(out, block)
            if note:
                notes.append(note)
        elif isinstance(block, Link):
            _docx_runs(out.add_paragraph(), "", [block])
        elif isinstance(block, Equation):
            _docx_equation(out.add_paragraph(), block)
        for link in leftover:
            _docx_runs(out.add_paragraph(), "", [link])
    out.save(str(path))
    return notes


def _docx_equation(paragraph, equation: Equation) -> None:
    """Write the original OMML back so Word keeps a real equation; the text if the XML is missing or unreadable."""
    if equation.omml:
        try:
            paragraph._p.append(parse_xml(equation.omml))
            return
        except Exception:  # not well-formed XML: fall back to the text
            pass
    paragraph.add_run(clean(equation.text))


def _docx_list_level(out, paragraph, style: str, level: int) -> None:
    """Put the list style's numbering on the paragraph with the nesting level (ilvl), so Word indents it
    and readers that look at the paragraph rather than the style (our own parser among them) see the level."""
    ppr = out.styles[style].element.pPr
    if ppr is None or ppr.numPr is None:
        return
    num_pr = copy.deepcopy(ppr.numPr)
    num_pr.get_or_add_ilvl().val = max(level, 1) - 1
    paragraph._p.get_or_add_pPr().append(num_pr)


def _docx_runs(paragraph, text: str, links: list[Link]) -> list[Link]:
    """Fill a paragraph with `text`, its links as hyperlink runs; returns the links that stand alone."""
    segments, leftover = _segments(clean(text), links)
    if not text and links:  # a link on its own line
        segments, leftover = [links[0]], links[1:]
    for segment in segments:
        if isinstance(segment, str):
            paragraph.add_run(segment)
        else:
            _docx_link(paragraph, segment)
    return leftover


def _set_default_language(out, tag: str) -> None:
    rpr = out.styles.element.find(f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}")
    if rpr is None:
        return
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), tag)


def _docx_table(out, table: Table) -> None:
    width = max((len(r) for r in table.rows), default=0)
    if not table.rows or not width:
        return
    t = out.add_table(rows=len(table.rows), cols=width)
    t.style = "Table Grid"
    for r, row in enumerate(table.rows):
        for c, text in enumerate(row):
            t.cell(r, c).text = clean(text)
    if table.has_header_row:
        tr_pr = t.rows[0]._tr.get_or_add_trPr()
        tr_pr.append(OxmlElement("w:tblHeader"))


def _docx_image(out, image: Image) -> str | None:
    fmt = image.format.lower()
    if fmt not in DOCX_IMAGE_FORMATS:
        alt = image.alt or "image"
        out.add_paragraph(f"[{alt}]")
        return f"a {fmt.upper()} image can't be embedded in DOCX; its description was written as text"
    shape = out.add_picture(BytesIO(image.data), width=Inches(5))
    doc_pr = shape._inline.docPr
    if image.decorative:
        doc_pr.set("descr", "")
        ext_lst = OxmlElement("a:extLst")
        ext = OxmlElement("a:ext")
        ext.set("uri", DECORATIVE_EXT_URI)
        decorative = ext.makeelement(f"{{{ADEC_NS}}}decorative", {"val": "1"})
        ext.append(decorative)
        ext_lst.append(ext)
        doc_pr.append(ext_lst)
    elif image.alt:
        doc_pr.set("descr", clean(image.alt))
    return None


def _docx_link(paragraph, link: Link) -> None:
    rel_id = paragraph.part.relate_to(link.url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = clean(link.text) or link.url
    text.set(qn("xml:space"), "preserve")
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


# --- Verify and state ---------------------------------------------------------

def verify(path: str | Path) -> tuple[Document, list[Issue]]:
    """Parse and audit the rebuilt file with the same checks as the original."""
    document = parse(path)
    return document, audit(document)


def compare(before: list[Issue], after: list[Issue]) -> dict:
    """Issues fixed, remaining and newly introduced, by rule."""
    b, a = Counter(i.rule for i in before), Counter(i.rule for i in after)
    return {
        "before": len(before), "after": len(after),
        "fixed": sum(max(b[r] - a[r], 0) for r in b),
        "new": {r: a[r] - b[r] for r in a if a[r] > b[r]},
        "remaining": dict(a),
    }


def statement(name: str, before: list[Issue], after: list[Issue], applied: int, waiting: int,
              notes: list[str] = (), when: datetime | None = None) -> str:
    """A short, honest accessibility statement for the rebuilt document."""
    when = when or datetime.now(timezone.utc)
    result = compare(before, after)
    lines = [f"# Accessibility statement: {name}", "",
             f"Prepared {when:%Y-%m-%d} by the campus-ai Course Access Agent against WCAG 2.2 AA. "
             "Only structure, markup, titles, link text and image descriptions were changed; "
             "the course content itself was not edited.", "",
             f"- Issues found by the automatic audit of the original: {result['before']}",
             f"- Proposals applied in this version: {applied}",
             f"- Proposals waiting for a person's review (not applied): {waiting}",
             f"- Issues the audit still finds in this version: {result['after']}",
             f"- Issues introduced by the rebuild: {sum(result['new'].values())}"]
    if result["new"]:
        lines += ["  - " + ", ".join(f"{r} (+{n})" for r, n in result["new"].items())]
    if result["remaining"]:
        lines += ["", "## Still to fix", ""] + [f"- {rule}: {n}" for rule, n in sorted(result["remaining"].items())]
    if notes:
        lines += ["", "## Notes from the rebuild", ""] + [f"- {n}" for n in notes]
    lines += ["", "## Not checked automatically", "",
              "This statement covers the automatic checks only. These need other tools or a person:", ""]
    lines += [f"- {item}" for item in NOT_CHECKED]
    return "\n".join(lines) + "\n"
