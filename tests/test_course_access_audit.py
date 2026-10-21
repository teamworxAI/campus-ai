import json
import tempfile
import unittest
from pathlib import Path

import docx

from campus_ai.course_access.audit import CRITERIA, NOT_CHECKED, audit, report_json, report_markdown
from campus_ai.course_access.parser import Document, Heading, Image, Link, ListItem, Paragraph, Table, parse


def doc(*blocks, fmt="docx", title="Week 1", language="en-CA", pages=None):
    return Document(source_format=fmt, title=title, language=language, page_count=pages, blocks=list(blocks))


def rules(document):
    return [issue.rule for issue in audit(document)]


class DocumentChecks(unittest.TestCase):
    def test_clean_document_has_no_issues(self):
        self.assertEqual(rules(doc(Heading("Intro", 1), Paragraph("Text."))), [])

    def test_title_and_language(self):
        issues = audit(doc(title=None, language=None))
        self.assertEqual([(i.rule, i.criterion, i.level) for i in issues],
                         [("document-no-title", "2.4.2", "A"), ("document-no-language", "3.1.1", "A")])
        self.assertEqual(rules(doc(language="english please")), ["document-bad-language"])
        for good in ("en", "fr-CA", "en-US", "zh-Hant-TW"):
            self.assertEqual(rules(doc(language=good)), [], good)


class HeadingChecks(unittest.TestCase):
    def test_long_document_without_headings(self):
        five = [Paragraph(f"Paragraph {n}.") for n in range(5)]
        self.assertEqual(rules(doc(*five)), ["no-headings"])
        self.assertEqual(rules(doc(*five[:4])), [])  # short documents may not need headings
        pdf = audit(doc(*five, fmt="pdf"))
        self.assertIn("PDF text has no heading markup", pdf[0].message)

    def test_skipped_heading_level(self):
        issues = audit(doc(Heading("A", 1), Heading("B", 3), Heading("C", 2), Heading("D", 3)))
        self.assertEqual([(i.rule, i.block) for i in issues], [("heading-level-skipped", 1)])

    def test_slides_need_unique_titles(self):
        deck = doc(Heading("Cells", 1, page=1), Heading("Cells", 1, page=2), Paragraph("x", page=3),
                   fmt="pptx", pages=3)
        self.assertEqual(sorted(rules(deck)), ["slide-no-title", "slide-title-duplicate", "slide-title-duplicate"])


class BlockChecks(unittest.TestCase):
    def test_images(self):
        cases = {
            None: ["image-missing-alt"],
            "IMG_2041.JPG": ["image-placeholder-alt"],
            "Picture": ["image-placeholder-alt"],
            "Bar chart of enrolment by year, rising from 120 to 310.": [],
        }
        for alt, expected in cases.items():
            self.assertEqual(rules(doc(Image(b"", "png", alt=alt))), expected, alt)
        self.assertEqual(rules(doc(Image(b"", "png", decorative=True))), [])
        issue = audit(doc(Paragraph("x", page=2), Image(b"", "png", page=2), fmt="pdf"))[0]
        self.assertEqual((issue.criterion, issue.page, issue.block, issue.fix), ("1.1.1", 2, 1, "alt-text worker"))

    def test_tables(self):
        rows = [["Week", "Topic"], ["1", "Cells"]]
        self.assertEqual(rules(doc(Table(rows))), ["table-no-header-row"])
        self.assertEqual(rules(doc(Table(rows, has_header_row=True))), [])
        self.assertEqual(rules(doc(Table([["Only row"]]))), [])  # a single row has nothing to relate

    def test_links(self):
        cases = {
            "Click here": ["link-vague-text"],
            "here.": ["link-vague-text"],
            "https://example.org/syllabus": ["link-bare-url"],
            "": ["link-no-text"],
            "Course syllabus (PDF)": [],
        }
        for text, expected in cases.items():
            self.assertEqual(rules(doc(Link(text, "https://example.org/syllabus"))), expected, text)

    def test_fake_lists(self):
        for text in ("- first point", "• first point", "1. First step", "a) option one", "(2) second"):
            self.assertEqual(rules(doc(Paragraph(text))), ["fake-list"], text)
        for text in ("e.g. a cell", "2024 was a good year.", "Results - mostly positive"):
            self.assertEqual(rules(doc(Paragraph(text))), [], text)
        self.assertEqual(rules(doc(ListItem("first point"))), [])

    def test_image_only_pdf_page(self):
        scanned = doc(Paragraph("Text", page=1), Image(b"", "png", alt="Scan", page=2), fmt="pdf", pages=2)
        issues = audit(scanned)
        self.assertEqual([(i.rule, i.criterion, i.page, i.fix) for i in issues],
                         [("page-image-only", "1.4.5", 2, "person")])


class Reports(unittest.TestCase):
    def setUp(self):
        self.document = doc(Image(b"", "png"), Link("here", "https://x.org"), title=None)
        self.issues = audit(self.document)

    def test_json(self):
        data = json.loads(report_json(self.document, self.issues, "week1.docx"))
        self.assertEqual(data["issue_count"], 3)
        self.assertEqual(data["by_criterion"]["1.1.1"], {"name": "Non-text Content", "level": "A", "count": 1})
        self.assertEqual(data["issues"][0]["criterion_name"], "Page Titled")
        self.assertEqual(data["not_checked"], NOT_CHECKED)

    def test_markdown_lists_issues_and_what_was_not_checked(self):
        text = report_markdown(self.document, self.issues, "week1.docx")
        self.assertIn("**3 issue(s) found.**", text)
        self.assertIn("| 2.4.4 Link Purpose (In Context) | A | 1 |", text)
        self.assertIn("## Not checked automatically", text)
        self.assertIn("1.4.3 Contrast (Minimum)", text)
        clean = report_markdown(doc(), [], "ok.docx")
        self.assertIn("No issues found by the automatic checks.", clean)
        self.assertIn("does not mean the document conforms", clean)

    def test_every_rule_maps_to_a_known_criterion(self):
        self.assertTrue(all(i.criterion in CRITERIA for i in self.issues))


class EndToEnd(unittest.TestCase):
    def test_parsed_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "week.docx"
            d = docx.Document()
            d.add_heading("Week 3", level=1)
            d.add_heading("Readings", level=3)
            d.add_paragraph("- read chapter 2")
            d.save(path)
            document = parse(path)
        # python-docx's template sets en-US in its styles, and leaves the title empty.
        self.assertEqual(document.language, "en-US")
        self.assertEqual(rules(document), ["document-no-title", "heading-level-skipped", "fake-list"])


if __name__ == "__main__":
    unittest.main()
