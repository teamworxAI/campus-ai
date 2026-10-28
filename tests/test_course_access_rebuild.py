import io
import tempfile
import unittest
from pathlib import Path

import docx
from PIL import Image as PILImage

from campus_ai.course_access.alt_text import AltText
from campus_ai.course_access.audit import STRUCTURE, TABLES, TEXT, audit
from campus_ai.course_access.parser import Document, Equation, Heading, Image, Link, ListItem, Paragraph, Table, parse
from campus_ai.course_access.rebuild import apply, compare, statement, to_docx, to_html, verify
from campus_ai.course_access.workers import Fix
from test_course_access_mathml import QUADRATIC, SUM, add_equation as _add_equation, display


def png() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), "red").save(buf, "PNG")
    return buf.getvalue()


def doc(*blocks, fmt="docx", title="Week 1", language="en-CA", pages=None):
    return Document(source_format=fmt, title=title, language=language, page_count=pages, blocks=list(blocks))


def fix(rule, worker, action, value, block=None, page=None):
    return Fix(rule, worker, action, value, 0.9, False, "", "test", page, block)


class ApplyTests(unittest.TestCase):
    def test_every_action_changes_the_right_thing(self):
        d = doc(Paragraph("1. Boil water"), Heading("Deep", 3), Paragraph("Intro"), Table([["a", ""], ["", "b"]]),
                Table([["Week", "Mark"], ["1", "80"]]), Link("https://x.org/t", "https://x.org/t"), Image(png(), "png"),
                Image(png(), "png"), title=None, language=None)
        fixes = [
            fix("fake-list", STRUCTURE, "convert-to-list", {"text": "Boil water", "ordered": True, "level": 1}, block=0),
            fix("heading-level-skipped", STRUCTURE, "set-heading-level", 1, block=1),
            fix("no-headings", STRUCTURE, "promote-to-heading", {"level": 2}, block=2),
            fix("table-no-header-row", TABLES, "treat-as-layout", True, block=3),
            fix("table-no-header-row", TABLES, "mark-header-row", True, block=4),
            fix("link-bare-url", TEXT, "set-link-text", "Timeline template", block=5),
            fix("document-no-title", TEXT, "set-title", "Marine Biology 101"),
            fix("document-no-language", TEXT, "set-language", "en"),
            Fix("document-no-title", TEXT, "set-title", None, 0, True, "no value", "x"),  # unfilled: ignored
        ]
        alts = [AltText(6, None, "photo", False, "A sockeye salmon.", "", 0.9, False, "", "m"),
                AltText(7, None, "decorative", True, "", "", 0.9, True, "decorative", "m")]
        out = apply(d, fixes, alts)
        self.assertEqual((out.title, out.language), ("Marine Biology 101", "en"))
        self.assertEqual([type(b).__name__ for b in out.blocks],
                         ["ListItem", "Heading", "Heading", "Paragraph", "Paragraph", "Table", "Link", "Image", "Image"])
        self.assertEqual((out.blocks[0].text, out.blocks[0].ordered), ("Boil water", True))
        self.assertEqual(out.blocks[1].level, 1)
        self.assertEqual((out.blocks[2].text, out.blocks[2].level), ("Intro", 2))
        self.assertEqual([b.text for b in out.blocks[3:5]], ["a", "b"])  # the layout table became its text
        self.assertTrue(out.blocks[5].has_header_row)
        self.assertEqual(out.blocks[6].text, "Timeline template")
        self.assertEqual((out.blocks[7].alt, out.blocks[7].decorative), ("A sockeye salmon.", False))
        self.assertEqual((out.blocks[8].alt, out.blocks[8].decorative), ("", True))
        # The original is untouched.
        self.assertIsNone(d.title)
        self.assertIsInstance(d.blocks[0], Paragraph)
        self.assertIsNone(d.blocks[6].alt)

    def test_layout_table_bullets_become_list_items(self):
        d = doc(Table([["Agenda\n• Welcome\n• Plan", ""], ["", "1. First step"]]))
        out = apply(d, [fix("table-no-header-row", TABLES, "treat-as-layout", True, block=0)])
        self.assertEqual([(type(b).__name__, b.text, getattr(b, "ordered", None)) for b in out.blocks],
                         [("Paragraph", "Agenda", None), ("ListItem", "Welcome", False), ("ListItem", "Plan", False),
                          ("ListItem", "First step", True)])
        self.assertEqual([i.rule for i in audit(out)], [])

    def test_slide_titles(self):
        d = doc(Heading("Cells", 1, page=1), Paragraph("a", page=1), Heading("Cells", 1, page=2), Paragraph("b", page=2),
                ListItem("Mitochondria make ATP", page=3), Paragraph("c", page=3), Image(png(), "png", page=4), fmt="pptx", pages=4)
        fixes = [fix("slide-title-duplicate", STRUCTURE, "retitle-slide", "Cells (1 of 2)", block=0, page=1),
                 fix("slide-title-duplicate", STRUCTURE, "retitle-slide", "Cells (2 of 2)", block=2, page=2),
                 fix("slide-no-title", STRUCTURE, "add-slide-title", "Mitochondria make ATP", page=3),
                 fix("slide-no-title", STRUCTURE, "add-slide-title", "Figure", page=4)]
        out = apply(d, fixes)
        self.assertEqual([(b.page, b.text) for b in out.blocks if isinstance(b, Heading)],
                         [(1, "Cells (1 of 2)"), (2, "Cells (2 of 2)"), (3, "Mitochondria make ATP"), (4, "Figure")])
        self.assertEqual(sum(isinstance(b, ListItem) for b in out.blocks), 0)  # the first line became the title
        self.assertEqual([r.rule for r in audit(out) if r.rule.startswith("slide")], [])


class HtmlTests(unittest.TestCase):
    def test_structure(self):
        d = doc(Heading("Cells", 1), Paragraph("Text & more"), ListItem("one"), ListItem("one.a", level=2),
                ListItem("two"), ListItem("first", ordered=True), Table([["Week", "Mark"], ["1", "80"]], has_header_row=True),
                Image(png(), "png", alt='Red "square"'), Image(png(), "png", decorative=True), Image(png(), "png"),
                Paragraph("See the Course page for details."), Link("Course page", "https://x.org/?a=1&b=2"),
                Link("", "https://x.org/alone"), language="fr", title="Semaine <1>")
        page = to_html(d)
        self.assertIn('<html lang="fr">', page)
        self.assertIn("<title>Semaine &lt;1&gt;</title>", page)
        self.assertIn("<h1>Cells</h1>", page)
        self.assertIn("<p>Text &amp; more</p>", page)
        self.assertIn("<ul>\n<li>one</li>\n<ul>\n<li>one.a</li>\n</ul>\n<li>two</li>\n</ul>\n<ol>\n<li>first</li>\n</ol>", page)
        self.assertIn('<thead><tr><th scope="col">Week</th><th scope="col">Mark</th></tr></thead>', page)
        self.assertIn('alt="Red &quot;square&quot;"', page)
        self.assertIn('alt="" role="presentation"', page)
        self.assertEqual(page.count("<img"), 3)
        self.assertEqual(page.count("alt="), 2)  # the undescribed image keeps no alt, for checkers to see
        self.assertIn('<p>See the <a href="https://x.org/?a=1&amp;b=2">Course page</a> for details.</p>', page)
        self.assertIn('<p><a href="https://x.org/alone">https://x.org/alone</a></p>', page)  # not in the text: its own line

    def test_slides_become_sections(self):
        d = doc(Heading("A", 1, page=1), Paragraph("a", page=1), Heading("B", 1, page=2), fmt="pptx", pages=2)
        page = to_html(d)
        self.assertEqual(page.count('<section aria-label="Slide'), 2)
        self.assertIn('<section aria-label="Slide 2">\n<h1>B</h1>\n</section>', page)


class DocxRoundTripTests(unittest.TestCase):
    def test_rebuilt_docx_parses_back_and_audits_clean(self):
        d = doc(Heading("Cells", 1), Paragraph("Intro."), ListItem("one"), ListItem("deeper", level=2),
                ListItem("step", ordered=True), Table([["Week", "Mark"], ["1", "80"]], has_header_row=True),
                Image(png(), "png", alt="A red square."), Image(png(), "png", decorative=True),
                Paragraph("See the Course page."), Link("Course page", "https://example.org/course"),
                Image(b"\x01", "emf", alt="An EMF drawing"), Paragraph("Soft\x0bbreak\x00here"),
                language="fr-CA", title="Semaine 1")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.docx"
            notes = to_docx(d, path)
            back, issues = verify(path)
        self.assertEqual(len(notes), 1)
        self.assertIn("EMF", notes[0])
        self.assertEqual((back.title, back.language), ("Semaine 1", "fr-CA"))
        self.assertEqual([type(b).__name__ for b in back.blocks],
                         ["Heading", "Paragraph", "ListItem", "ListItem", "ListItem", "Table", "Image", "Image",
                          "Paragraph", "Link", "Paragraph", "Paragraph"])
        self.assertEqual((back.blocks[0].text, back.blocks[0].level), ("Cells", 1))
        self.assertEqual([(b.text, b.level) for b in back.blocks[2:5]], [("one", 1), ("deeper", 2), ("step", 1)])
        self.assertEqual(back.blocks[5].rows, [["Week", "Mark"], ["1", "80"]])
        self.assertTrue(back.blocks[5].has_header_row)
        self.assertEqual(back.blocks[6].alt, "A red square.")
        self.assertTrue(back.blocks[7].decorative)
        self.assertEqual(back.blocks[8].text, "See the Course page.")  # the link sits inside its paragraph
        self.assertEqual((back.blocks[9].text, back.blocks[9].url), ("Course page", "https://example.org/course"))
        self.assertEqual(back.blocks[10].text, "[An EMF drawing]")
        self.assertEqual(back.blocks[11].text, "Soft break here")  # control characters can't go into XML
        self.assertEqual([i.rule for i in issues], [])


class EquationRebuildTests(unittest.TestCase):
    def _document(self):
        d = docx.Document()
        d.core_properties.title = "Maths"
        d.core_properties.language = "en-CA"
        d.add_heading("Algebra", level=1)
        _add_equation(d.add_paragraph("Solve it:"), display(QUADRATIC))
        _add_equation(d.add_paragraph("The total is "), SUM)
        return d

    def test_html_has_math_with_alttext(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "maths.docx"
            self._document().save(path)
            page = to_html(parse(path))
        self.assertIn('<math xmlns="http://www.w3.org/1998/Math/MathML" display="block" alttext="x = (-b', page)
        self.assertIn("<mfrac>", page)
        self.assertIn("<munderover>", page)
        self.assertEqual(page.count("<math "), 2)
        self.assertEqual(page.count('display="block"'), 1)  # the inline one is not display
        self.assertIn("<p>Solve it:</p>", page)

    def test_docx_round_trip_keeps_real_equations(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, rebuilt = Path(tmp) / "maths.docx", Path(tmp) / "out.docx"
            self._document().save(source)
            original = parse(source)
            to_docx(original, rebuilt)
            again = parse(rebuilt)
            xml = docx.Document(str(rebuilt)).element.xml
        equations = [b for b in again.blocks if isinstance(b, Equation)]
        self.assertEqual([(e.text, e.display) for e in equations],
                         [(b.text, b.display) for b in original.blocks if isinstance(b, Equation)])
        self.assertEqual(equations[0].mathml, [b for b in original.blocks if isinstance(b, Equation)][0].mathml)
        self.assertIn("<m:nary>", xml)  # a real Word equation, not text

    def test_docx_falls_back_to_text_without_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.docx"
            to_docx(doc(Equation(mathml="<math/>", text="x = 1")), path)
            again = parse(path)
        self.assertEqual([type(b).__name__ for b in again.blocks], ["Paragraph"])
        self.assertEqual(again.blocks[0].text, "x = 1")

    def test_html_without_mathml_falls_back_to_text(self):
        self.assertIn("<p>x &lt; 1</p>", to_html(doc(Equation(mathml="", text="x < 1"))))

    def test_empty_equation_is_flagged(self):
        issues = audit(doc(Equation(mathml="<math/>", text="")))
        self.assertEqual([(i.rule, i.criterion) for i in issues], [("equation-empty", "1.1.1")])
        self.assertEqual(audit(doc(Equation(mathml="<math/>", text="x"))), [])


class StatementTests(unittest.TestCase):
    def test_compare_and_statement(self):
        before = audit(doc(Paragraph("- a"), Image(png(), "png"), Table([["1", "2"], ["3", "4"]]), title=None))
        after = audit(doc(ListItem("a"), Image(png(), "png"), Table([["1", "2"], ["3", "4"]], has_header_row=True),
                          Heading("A", 3), Heading("B", 1), Heading("C", 3), title="T"))
        result = compare(before, after)
        self.assertEqual((result["before"], result["after"], result["fixed"]), (4, 2, 3))
        self.assertEqual(result["new"], {"heading-level-skipped": 1})
        text = statement("week1.docx", before, after, applied=3, waiting=1, notes=["an EMF image was written as text"])
        self.assertIn("Issues found by the automatic audit of the original: 4", text)
        self.assertIn("Proposals applied in this version: 3", text)
        self.assertIn("waiting for a person's review (not applied): 1", text)
        self.assertIn("Issues introduced by the rebuild: 1", text)
        self.assertIn("heading-level-skipped (+1)", text)
        self.assertIn("- image-missing-alt: 1", text)
        self.assertIn("an EMF image was written as text", text)
        self.assertIn("Not checked automatically", text)
        self.assertIn("the course content itself was not edited", text)


if __name__ == "__main__":
    unittest.main()
