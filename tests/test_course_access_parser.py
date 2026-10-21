import tempfile
import unittest
from pathlib import Path

import docx
import pymupdf
import pptx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE
from pptx.util import Inches

from campus_ai.course_access.parser import parse


def _png() -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False)
    pixmap.clear_with(200)
    return pixmap.tobytes("png")


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
        path = self.dir / "sample.pptx"
        p.save(path)
        return path

    def test_structure_and_order(self):
        document = parse(self._build())
        self.assertEqual(document.source_format, "pptx")
        self.assertEqual(document.title, "Lecture 2")
        self.assertEqual(document.page_count, 2)
        self.assertEqual(_kinds(document), [
            "Heading", "ListItem", "ListItem", "Image",
            "Heading", "Table", "Paragraph", "Link"])
        b = document.blocks
        self.assertEqual([x.page for x in b], [1, 1, 1, 1, 2, 2, 2, 2])
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
        pdf = pymupdf.open()
        pdf.set_metadata({"title": "Notes"})
        pdf.xref_set_key(pdf.pdf_catalog(), "Lang", "(fr-CA)")
        page = pdf.new_page()
        page.insert_text((72, 72), "Opening paragraph.")
        page.insert_image(pymupdf.Rect(72, 100, 144, 172),
                          filename=str(self.png))
        page.insert_text((72, 200), "Visit the site")
        page.insert_link({"kind": pymupdf.LINK_URI,
                          "from": pymupdf.Rect(70, 188, 160, 204),
                          "uri": "https://example.org/"})
        # A 2x2 ruled table.
        x, y, w, h = 72, 300, 100, 20
        for r in range(3):
            page.draw_line((x, y + r * h), (x + 2 * w, y + r * h))
        for c in range(3):
            page.draw_line((x + c * w, y), (x + c * w, y + 2 * h))
        for r, row in enumerate([["Term", "Hours"], ["Fall", "3"]]):
            for c, value in enumerate(row):
                page.insert_text((x + c * w + 5, y + r * h + 14), value)
        pdf.new_page().insert_text((72, 72), "Second page.")
        path = self.dir / "sample.pdf"
        pdf.save(path)
        pdf.close()
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
        self.assertIsNone(b[1].alt)
        self.assertEqual(b[1].nearby_text,
                         "Opening paragraph.\nVisit the site")
        self.assertEqual(b[3].rows, [["Term", "Hours"], ["Fall", "3"]])
        self.assertEqual((b[4].text, b[4].url),
                         ("Visit the site", "https://example.org/"))
        self.assertEqual(b[5].text, "Second page.")


class ParseTests(unittest.TestCase):
    def test_unsupported_type(self):
        with self.assertRaises(ValueError):
            parse("notes.txt")


if __name__ == "__main__":
    unittest.main()
