import io
import tempfile
import unittest
from pathlib import Path

import docx
import pptx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE
from PIL import Image as PILImage
from pptx.util import Inches
from pypdf import PdfWriter
from pypdf.generic import NameObject, TextStringObject
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from campus_ai.course_access.parser import parse


def _png() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (4, 4), (200, 200, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def _kinds(document):
    return [type(b).__name__ for b in document.blocks]


class ParserTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.png = self.dir / "pixel.png"
        self.png.write_bytes(_png())


class DocxParserTests(ParserTestCase):
    def _build(self) -> Path:
        d = docx.Document()
        d.core_properties.title = "Week 1"
        d.core_properties.language = "en-CA"
        d.add_heading("Introduction", level=1)
        d.add_paragraph("Before the figure.")
        d.add_picture(str(self.png))
        d.add_paragraph("After the figure.")
        d.add_paragraph("First point", style="List Bullet")
        d.add_heading("Data", level=2)
        table = d.add_table(rows=2, cols=2)
        for r, row in enumerate([["Name", "Score"], ["Ada", "9"]]):
            for c, value in enumerate(row):
                table.cell(r, c).text = value
        table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        self._add_link(d.add_paragraph("See "), "the syllabus",
                       "https://example.org/syllabus")
        path = self.dir / "sample.docx"
        d.save(path)
        return path

    @staticmethod
    def _add_link(paragraph, text, url):
        rel_id = paragraph.part.relate_to(
            url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), rel_id)
        run = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = text
        run.append(t)
        link.append(run)
        paragraph._p.append(link)

    def test_structure_and_order(self):
        document = parse(self._build())
        self.assertEqual(document.source_format, "docx")
        self.assertEqual(document.title, "Week 1")
        self.assertEqual(document.language, "en-CA")
        self.assertIsNone(document.page_count)
        self.assertEqual(_kinds(document), [
            "Heading", "Paragraph", "Image", "Paragraph", "ListItem",
            "Heading", "Table", "Paragraph", "Link"])
        b = document.blocks
        self.assertEqual((b[0].text, b[0].level), ("Introduction", 1))
        self.assertEqual(b[5].level, 2)
        self.assertEqual(b[4].text, "First point")
        self.assertEqual(b[6].rows, [["Name", "Score"], ["Ada", "9"]])
        self.assertTrue(b[6].has_header_row)
        self.assertEqual((b[8].text, b[8].url),
                         ("the syllabus", "https://example.org/syllabus"))
        self.assertTrue(all(block.page is None for block in b))

    def test_image(self):
        image = parse(self._build()).blocks[2]
        self.assertEqual(image.format, "png")
        self.assertEqual(image.data, self.png.read_bytes())
        self.assertIsNone(image.alt)
        self.assertFalse(image.decorative)
        self.assertEqual(image.nearby_text,
                         "Before the figure.\nAfter the figure.")

    def test_existing_alt_text(self):
        d = docx.Document()
        d.add_picture(str(self.png))
        doc_pr = next(d.element.body.iter(qn("wp:docPr")))
        doc_pr.set("descr", "A bar chart")
        path = self.dir / "alt.docx"
        d.save(path)
        self.assertEqual(parse(path).blocks[0].alt, "A bar chart")


class PptxParserTests(ParserTestCase):
    def _build(self) -> Path:
        p = pptx.Presentation()
        p.core_properties.title = "Lecture 2"
        slide = p.slides.add_slide(p.slide_layouts[1])  # title and content
        slide.shapes.title.text = "Cells"
        body = slide.placeholders[1].text_frame
        body.text = "Nucleus"
        sub = body.add_paragraph()
        sub.text = "DNA"
        sub.level = 1
        picture = slide.shapes.add_picture(str(self.png), Inches(1), Inches(1))
        picture._element._nvXxPr.cNvPr.set("descr", "Cell diagram")

        slide = p.slides.add_slide(p.slide_layouts[5])  # title only
        slide.shapes.title.text = "Results"
        rows = slide.shapes.add_table(
            2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
        for r, row in enumerate([["Week", "Mark"], ["1", "80"]]):
            for c, value in enumerate(row):
                rows.cell(r, c).text = value
        box = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(4), Inches(1))
        run = box.text_frame.paragraphs[0].add_run()
        run.text = "Course page"
        run.hyperlink.address = "https://example.org/course"

        slide = p.slides.add_slide(p.slide_layouts[5])  # a title box with two lines typed in
        slide.shapes.title.text_frame.text = "Week 3"
        slide.shapes.title.text_frame.add_paragraph().text = "EDST 101"
        path = self.dir / "sample.pptx"
        p.save(path)
        return path

    def test_structure_and_order(self):
        document = parse(self._build())
        self.assertEqual(document.source_format, "pptx")
        self.assertEqual(document.title, "Lecture 2")
        self.assertEqual(document.page_count, 3)
        self.assertEqual(_kinds(document), [
            "Heading", "ListItem", "ListItem", "Image",
            "Heading", "Table", "Paragraph", "Link", "Heading"])
        b = document.blocks
        self.assertEqual([x.page for x in b], [1, 1, 1, 1, 2, 2, 2, 2, 3])
        self.assertEqual(b[8].text, "Week 3 EDST 101")  # one title placeholder, one heading
        self.assertEqual((b[1].text, b[1].level), ("Nucleus", 1))
        self.assertEqual((b[2].text, b[2].level), ("DNA", 2))
        self.assertEqual(b[3].alt, "Cell diagram")
        self.assertEqual(b[3].data, self.png.read_bytes())
        self.assertEqual(b[3].nearby_text, "DNA")
        self.assertEqual(b[5].rows, [["Week", "Mark"], ["1", "80"]])
        self.assertTrue(b[5].has_header_row)
        self.assertEqual((b[7].text, b[7].url),
                         ("Course page", "https://example.org/course"))


class PdfParserTests(ParserTestCase):
    def _build(self) -> Path:
        # Coordinates below are from the top of the page, as the parser
        # reports them; reportlab measures from the bottom, hence `up`.
        path = self.dir / "sample.pdf"
        height = letter[1]
        up = lambda y: height - y  # noqa: E731
        c = canvas.Canvas(str(path), pagesize=letter)
        c.setTitle("Notes")
        c.drawString(72, up(72), "Opening paragraph.")
        c.drawImage(str(self.png), 72, up(172), width=72, height=72)
        c.drawString(72, up(200), "Visit the site")
        c.linkURL("https://example.org/", (70, up(204), 160, up(188)), relative=0)
        # A 2x2 ruled table.
        x, y, w, h = 72, 300, 100, 20
        for r in range(3):
            c.line(x, up(y + r * h), x + 2 * w, up(y + r * h))
        for col in range(3):
            c.line(x + col * w, up(y), x + col * w, up(y + 2 * h))
        for r, row in enumerate([["Term", "Hours"], ["Fall", "3"]]):
            for col, value in enumerate(row):
                c.drawString(x + col * w + 5, up(y + r * h + 14), value)
        c.showPage()
        c.drawString(72, up(72), "Second page.")
        c.save()
        # reportlab can't set the document language; add /Lang to the catalog.
        writer = PdfWriter(clone_from=str(path))
        writer._root_object[NameObject("/Lang")] = TextStringObject("fr-CA")
        writer.write(str(path))
        return path

    def test_structure_and_order(self):
        document = parse(self._build())
        self.assertEqual(document.source_format, "pdf")
        self.assertEqual(document.title, "Notes")
        self.assertEqual(document.language, "fr-CA")
        self.assertEqual(document.page_count, 2)
        self.assertEqual(_kinds(document), [
            "Paragraph", "Image", "Paragraph", "Table", "Link", "Paragraph"])
        b = document.blocks
        self.assertEqual([x.page for x in b], [1, 1, 1, 1, 1, 2])
        self.assertEqual(b[1].format, "png")
        self.assertTrue(b[1].data.startswith(b"\x89PNG"))
        self.assertEqual(PILImage.open(io.BytesIO(b[1].data)).size, (150, 150))  # 1 inch at 150 dpi
        self.assertIsNone(b[1].alt)
        self.assertEqual(b[1].nearby_text,
                         "Opening paragraph.\nVisit the site")
        self.assertEqual(b[3].rows, [["Term", "Hours"], ["Fall", "3"]])
        self.assertEqual((b[4].text, b[4].url),
                         ("Visit the site", "https://example.org/"))
        self.assertEqual(b[5].text, "Second page.")


class PdfParagraphTests(ParserTestCase):
    def test_lines_join_into_paragraphs_until_a_gap(self):
        path = self.dir / "lines.pdf"
        c = canvas.Canvas(str(path), pagesize=letter)
        c.setTitle("")  # reportlab writes "untitled" by default
        top = letter[1]
        for y, text in ((72, "First line of a paragraph"), (86, "and its second line."),
                        (160, "A new paragraph after a gap.")):
            c.drawString(72, top - y, text)
        c.save()
        document = parse(path)
        self.assertEqual([b.text for b in document.blocks],
                         ["First line of a paragraph and its second line.",
                          "A new paragraph after a gap."])
        self.assertIsNone(document.language)  # no /Lang: reported as absent for the audit
        self.assertIsNone(document.title)


class ParseTests(unittest.TestCase):
    def test_unsupported_type(self):
        with self.assertRaises(ValueError):
            parse("notes.txt")


if __name__ == "__main__":
    unittest.main()
