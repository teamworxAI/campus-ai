"""Parse course documents (PDF, PPTX, DOCX) into one common structure.

The parser only reads: it keeps the reading order the file defines and does
not repair anything. Missing headings, alt text or language are reported as
absent (``None`` or no block) so the audit (A2) can flag them.

Reading order per format:
- DOCX: body order of paragraphs and tables.
- PPTX: slide order, then shape order on each slide (the order screen
  readers use).
- PDF: top to bottom, then left to right, on each page: text paragraphs,
  ruled tables and images. Untagged PDFs carry no heading or list semantics,
  so their text is paragraphs.

Each block records the 1-based page (PDF) or slide (PPTX) it came from. DOCX
has no fixed pages, so ``page`` is ``None``. Links are emitted right after
the block that contains them (PDF: at the end of their page).

All libraries are open source and permissively licensed (prime directive 1):
python-docx, python-pptx (MIT) and pdfplumber on pdfminer.six (MIT).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import docx
import pdfplumber
import pptx
from pdfminer.pdftypes import resolve1
from pdfminer.utils import decode_text
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER


@dataclass(kw_only=True)
class _Block:
    page: int | None = None


@dataclass
class Heading(_Block):
    text: str
    level: int  # 1 = top level


@dataclass
class Paragraph(_Block):
    text: str


@dataclass
class ListItem(_Block):
    text: str
    level: int = 1  # nesting depth, 1 = top level
    ordered: bool = False  # numbered rather than bulleted, where the file says so


@dataclass
class Table(_Block):
    rows: list[list[str]]  # cell text, row by row
    has_header_row: bool = False  # first row marked as header in the file


@dataclass
class Image(_Block):
    data: bytes
    format: str  # file extension, e.g. "png"
    alt: str | None = None  # existing alt text; None if the file has none
    decorative: bool = False  # marked decorative in the file
    nearby_text: str = ""  # text of the blocks just before and after


@dataclass
class Link(_Block):
    text: str
    url: str


Block = Heading | Paragraph | ListItem | Table | Image | Link


@dataclass
class Document:
    source_format: str  # "pdf", "pptx" or "docx"
    title: str | None = None
    language: str | None = None  # e.g. "en-CA"
    page_count: int | None = None  # pages or slides; None for DOCX
    blocks: list[Block] = field(default_factory=list)


def parse(path: str | Path) -> Document:
    """Parse a PDF, PPTX or DOCX file into a Document."""
    path = Path(path)
    parsers = {".pdf": _parse_pdf, ".pptx": _parse_pptx, ".docx": _parse_docx}
    suffix = path.suffix.lower()
    if suffix not in parsers:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    document = parsers[suffix](path)
    _fill_nearby_text(document.blocks)
    return document


def _fill_nearby_text(blocks: list[Block]) -> None:
    text_types = (Heading, Paragraph, ListItem)
    for i, block in enumerate(blocks):
        if not isinstance(block, Image):
            continue
        before = next(
            (b.text for b in reversed(blocks[:i])
             if isinstance(b, text_types) and b.page == block.page), "")
        after = next(
            (b.text for b in blocks[i + 1:]
             if isinstance(b, text_types) and b.page == block.page), "")
        block.nearby_text = "\n".join(t for t in (before, after) if t)


def _clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


def _is_decorative(element) -> bool:
    """True if a docPr/cNvPr element carries Office's decorative flag."""
    return any(
        el.tag.endswith("}decorative") and el.get("val") in ("1", "true")
        for el in element.iter()
    )


# --- PDF ------------------------------------------------------------------

IMAGE_DPI = 150  # resolution of the PNG made for each PDF image (for the alt-text worker)


def _parse_pdf(path: Path) -> Document:
    with pdfplumber.open(path) as pdf:
        document = Document(
            source_format="pdf",
            title=_clean(_pdf_text(pdf.metadata.get("Title"))),
            language=_clean(_pdf_text(resolve1(pdf.doc.catalog.get("Lang")))),
            page_count=len(pdf.pages),
        )
        for number, page in enumerate(pdf.pages, start=1):
            document.blocks.extend(_pdf_page_blocks(page, number))
    return document


def _pdf_text(value) -> str | None:
    """A PDF string (bytes in PDFDocEncoding or UTF-16) or an already decoded str."""
    if isinstance(value, bytes):
        return decode_text(value)
    return value if isinstance(value, str) else None


def _pdf_page_blocks(page, page_no: int) -> list[Block]:
    """Paragraphs, tables and images ordered top to bottom, then left to right;
    then the page's links."""
    tables = page.find_tables()
    placed: list[tuple[float, float, Block]] = [
        (t.bbox[1], t.bbox[0], _pdf_table(t, page_no)) for t in tables]
    placed += [(im["top"], im["x0"], _pdf_image(page, im, page_no))
               for im in page.images]
    # Text inside a table is emitted once, as the table itself.
    lines = [line for line in page.extract_text_lines()
             if not any(_inside(line, t.bbox) for t in tables)]
    placed += [(top, x0, Paragraph(text=text, page=page_no))
               for top, x0, text in _paragraphs(lines, placed)]
    blocks = [block for _, _, block in sorted(placed, key=lambda p: (round(p[0]), p[1]))]
    for link in page.hyperlinks:
        if link.get("uri"):
            box = _clip((link["x0"], link["top"], link["x1"], link["bottom"]), page.bbox)
            text = (page.crop(box).extract_text() or "").strip() if box else ""
            blocks.append(Link(text=text, url=link["uri"], page=page_no))
    return blocks


def _paragraphs(lines: list[dict], others: list) -> list[tuple[float, float, str]]:
    """Join consecutive text lines into paragraphs. A line starts a new
    paragraph after a gap taller than a line, or when a table or image sits
    between it and the previous line."""
    paragraphs: list[list] = []  # [top, x0, bottom, height, [texts]]
    for line in sorted(lines, key=lambda l: (round(l["top"]), l["x0"])):
        height = line["bottom"] - line["top"]
        last = paragraphs[-1] if paragraphs else None
        between = last and any(last[2] <= top < line["top"] for top, _, _ in others)
        if last and not between and line["top"] - last[2] <= max(height, last[3]):
            last[2] = line["bottom"]
            last[4].append(line["text"].strip())
        else:
            paragraphs.append([line["top"], line["x0"], line["bottom"], height,
                               [line["text"].strip()]])
    return [(top, x0, " ".join(t for t in texts if t))
            for top, x0, _, _, texts in paragraphs if any(texts)]


def _inside(obj: dict, bbox) -> bool:
    x = (obj["x0"] + obj["x1"]) / 2
    y = (obj["top"] + obj["bottom"]) / 2
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def _clip(box, page_box):
    """`box` cut to the page, or None if nothing is left."""
    x0, top = max(box[0], page_box[0]), max(box[1], page_box[1])
    x1, bottom = min(box[2], page_box[2]), min(box[3], page_box[3])
    return (x0, top, x1, bottom) if x1 > x0 and bottom > top else None


def _pdf_image(page, image: dict, page_no: int) -> Image:
    """The image as a PNG of its area on the page: what a reader sees there,
    whatever the image's internal encoding."""
    box = _clip((image["x0"], image["top"], image["x1"], image["bottom"]), page.bbox)
    buffer = io.BytesIO()
    if box:
        page.crop(box).to_image(resolution=IMAGE_DPI).original.save(buffer, "PNG")
    return Image(data=buffer.getvalue(), format="png", page=page_no)


def _pdf_table(table, page_no: int) -> Table:
    rows = [[(cell or "").strip() for cell in row] for row in table.extract()]
    return Table(rows=rows, page=page_no)


# --- DOCX -----------------------------------------------------------------

def _parse_docx(path: Path) -> Document:
    source = docx.Document(str(path))
    props = source.core_properties
    document = Document(
        source_format="docx",
        title=_clean(props.title),
        language=_clean(props.language) or _docx_default_language(source),
    )
    for item in source.iter_inner_content():
        if isinstance(item, DocxTable):
            document.blocks.append(_docx_table(item))
        else:
            document.blocks.extend(_docx_paragraph(item, source))
    return document


def _docx_default_language(source) -> str | None:
    lang = source.styles.element.find(
        f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}/{qn('w:lang')}")
    return _clean(lang.get(qn("w:val"))) if lang is not None else None


def _docx_paragraph(paragraph, source) -> list[Block]:
    blocks: list[Block] = []
    text = paragraph.text.strip()
    style = paragraph.style.name if paragraph.style is not None else ""
    ppr = paragraph._p.pPr
    numbering = ppr.numPr if ppr is not None else None
    if text:
        if style.startswith("Heading ") and style[8:].isdigit():
            blocks.append(Heading(text=text, level=int(style[8:])))
        elif numbering is not None or style.startswith("List"):
            level = 1
            if numbering is not None and numbering.ilvl is not None:
                level = numbering.ilvl.val + 1
            blocks.append(ListItem(text=text, level=level))
        else:
            blocks.append(Paragraph(text=text))
    for drawing in paragraph._p.iter(qn("w:drawing")):
        image = _docx_image(drawing, source)
        if image is not None:
            blocks.append(image)
    for link in paragraph.hyperlinks:
        if link.url:
            blocks.append(Link(text=link.text.strip(), url=link.url))
    return blocks


def _docx_image(drawing, source) -> Image | None:
    blip = next(drawing.iter(qn("a:blip")), None)
    rel_id = blip.get(qn("r:embed")) if blip is not None else None
    if rel_id is None:
        return None
    part = source.part.related_parts[rel_id]
    doc_pr = next(drawing.iter(qn("wp:docPr")), None)
    return Image(
        data=part.blob,
        format=Path(part.partname).suffix.lstrip("."),
        alt=_clean(doc_pr.get("descr")) if doc_pr is not None else None,
        decorative=doc_pr is not None and _is_decorative(doc_pr),
    )


def _docx_table(table: DocxTable) -> Table:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    header = False
    if table.rows:
        tr_pr = table.rows[0]._tr.trPr
        header = tr_pr is not None and tr_pr.find(qn("w:tblHeader")) is not None
    return Table(rows=rows, has_header_row=header)


# --- PPTX -----------------------------------------------------------------

_TITLE_TYPES = (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
_BULLET_TYPES = (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT)


def _parse_pptx(path: Path) -> Document:
    source = pptx.Presentation(str(path))
    props = source.core_properties
    document = Document(
        source_format="pptx",
        title=_clean(props.title),
        language=_clean(props.language),
        page_count=len(source.slides),
    )
    for number, slide in enumerate(source.slides, start=1):
        for shape in slide.shapes:
            document.blocks.extend(_pptx_shape(shape, number))
    if document.language is None:
        document.language = _pptx_first_run_language(source)
    return document


def _pptx_first_run_language(source) -> str | None:
    for slide in source.slides:
        for el in slide.shapes._spTree.iter(qn("a:rPr")):
            if el.get("lang"):
                return el.get("lang")
    return None


def _pptx_shape(shape, page: int) -> list[Block]:
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return [b for child in shape.shapes for b in _pptx_shape(child, page)]
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        c_nv_pr = shape._element._nvXxPr.cNvPr
        return [Image(
            data=shape.image.blob,
            format=shape.image.ext,
            alt=_clean(c_nv_pr.get("descr")),
            decorative=_is_decorative(c_nv_pr),
            page=page,
        )]
    if shape.has_table:
        table = shape.table
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        return [Table(rows=rows, has_header_row=table.first_row, page=page)]
    if not shape.has_text_frame:
        return []

    placeholder = (shape.placeholder_format.type
                   if shape.is_placeholder else None)
    blocks: list[Block] = []
    if placeholder in _TITLE_TYPES:
        # One title placeholder is one slide title, however many lines it holds
        # (a second line is usually a subtitle or course name typed into the box).
        lines = [p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()]
        if lines:
            blocks.append(Heading(text=" ".join(lines), level=1, page=page))
        return blocks + _pptx_links(shape, page)
    for paragraph in shape.text_frame.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if _pptx_is_bullet(paragraph, placeholder in _BULLET_TYPES):
            blocks.append(ListItem(text=text, level=paragraph.level + 1,
                                   page=page))
        else:
            blocks.append(Paragraph(text=text, page=page))
        for run in paragraph.runs:
            if run.hyperlink.address:
                blocks.append(Link(text=run.text.strip(),
                                   url=run.hyperlink.address, page=page))
    return blocks


def _pptx_links(shape, page: int) -> list[Link]:
    return [Link(text=run.text.strip(), url=run.hyperlink.address, page=page)
            for paragraph in shape.text_frame.paragraphs for run in paragraph.runs if run.hyperlink.address]


def _pptx_is_bullet(paragraph, default: bool) -> bool:
    """Body placeholders bullet by default; other shapes only if set."""
    ppr = paragraph._p.pPr
    if ppr is not None:
        if ppr.find(qn("a:buNone")) is not None:
            return False
        if (ppr.find(qn("a:buChar")) is not None
                or ppr.find(qn("a:buAutoNum")) is not None):
            return True
    return default
