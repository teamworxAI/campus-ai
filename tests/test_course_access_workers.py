import json
import unittest
from unittest import mock

from campus_ai.core.llm import LLMResponse
from campus_ai.course_access import model_answers, workers
from campus_ai.course_access.audit import STRUCTURE, TABLES, TEXT, audit
from campus_ai.course_access.parser import Document, Heading, Image, Link, ListItem, Paragraph, Table
from campus_ai.course_access.workers import Fix, propose_fixes, report_json, report_markdown


def doc(*blocks, fmt="docx", title="Week 1", language="en-CA", pages=None):
    return Document(source_format=fmt, title=title, language=language, page_count=pages, blocks=list(blocks))


def fixes_for(document, reply=None):
    """Run the workers; `reply` is what the (mocked) model answers, if it is asked."""
    response = LLMResponse(json.dumps(reply) if isinstance(reply, dict) else (reply or "{}"), "gemma4:12b", 50, 10, "stop")
    with mock.patch.object(model_answers, "generate", return_value=response) as gen:
        result = propose_fixes(document, data_class="I")
    return result, gen


class StructureWorkerTests(unittest.TestCase):
    def test_typed_lists_become_list_items(self):
        d = doc(Heading("Steps", 1), Paragraph("1. Boil water"), Paragraph("- stir"), Paragraph("a) sit"))
        fixes, _ = fixes_for(d)
        self.assertEqual([(f.action, f.value["text"], f.value["ordered"], f.needs_review) for f in fixes],
                         [("convert-to-list", "Boil water", True, False), ("convert-to-list", "stir", False, False),
                          ("convert-to-list", "sit", True, False)])
        self.assertEqual(fixes[0].worker, STRUCTURE)
        self.assertEqual((fixes[0].rule, fixes[0].block, fixes[0].confidence), ("fake-list", 1, 0.9))

    def test_skipped_heading_level_is_closed(self):
        fixes, _ = fixes_for(doc(Heading("A", 1), Heading("B", 3), Paragraph("x")))
        self.assertEqual([(f.action, f.value, f.block) for f in fixes], [("set-heading-level", 2, 1)])

    def test_duplicate_slide_titles_are_numbered(self):
        d = doc(Heading("Cells", 1, page=1), Paragraph("a", page=1), Heading("cells", 1, page=2), Paragraph("b", page=2),
                Heading("Energy", 1, page=3), Paragraph("c", page=3), fmt="pptx", pages=3)
        fixes, _ = fixes_for(d)
        self.assertEqual([(f.action, f.value, f.page) for f in fixes],
                         [("retitle-slide", "Cells (1 of 2)", 1), ("retitle-slide", "cells (2 of 2)", 2)])
        self.assertFalse(any(f.needs_review for f in fixes))

    def test_untitled_slide_gets_its_first_line_for_review(self):
        d = doc(Heading("Intro", 1, page=1), ListItem("Mitochondria make ATP", page=2), Paragraph("x", page=2),
                fmt="pptx", pages=3)
        fixes, _ = fixes_for(d)
        by_page = {f.page: f for f in fixes if f.action == "add-slide-title"}
        self.assertEqual((by_page[2].value, by_page[2].confidence, by_page[2].needs_review), ("Mitochondria make ATP", 0.6, True))
        self.assertIn("confirm", by_page[2].review_reason)
        self.assertEqual((by_page[3].value, by_page[3].needs_review), (None, True))
        self.assertIn("a person must supply", by_page[3].review_reason)

    def test_heading_candidates_in_a_document_without_headings(self):
        d = doc(Paragraph("Introduction"), Paragraph("Cells are the basic unit of life and they divide."),
                Paragraph("This is a full sentence that ends with a period."), Paragraph("Another long paragraph follows here."),
                Paragraph("Energy"), Paragraph("Mitochondria make ATP from glucose."))
        fixes, _ = fixes_for(d)
        promoted = [(f.block, f.value, f.needs_review) for f in fixes if f.action == "promote-to-heading"]
        self.assertEqual(promoted, [(0, {"level": 1}, True), (4, {"level": 1}, True)])
        self.assertEqual(promoted and fixes[0].rule, "no-headings")


class TableWorkerTests(unittest.TestCase):
    def one(self, rows):
        fixes, _ = fixes_for(doc(Table(rows)))
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0].worker, TABLES)
        return fixes[0]

    def test_header_like_first_row_is_marked(self):
        f = self.one([["Week", "Topic", "Reading"], ["1", "Cells", "Ch. 1"], ["2", "Energy", "Ch. 2"]])
        self.assertEqual((f.action, f.value, f.confidence, f.needs_review), ("mark-header-row", True, 0.85, False))

    def test_doubtful_first_row_goes_to_review(self):
        f = self.one([["1", "80"], ["2", "75"]])
        self.assertEqual((f.action, f.confidence, f.needs_review), ("mark-header-row", 0.5, True))
        self.assertIn("may not be column headings", f.review_reason)

    def test_layout_tables_are_not_data(self):
        for rows, why in (([["Title"], ["By someone"], ["2024"]], "one column"),
                          ([["a", "", ""], ["", "", "b"]], "67% of the cells are empty"),
                          ([["Module 1:\nOER 101\nAuthors", "x"], ["y", "z"]], "two rows of multi-line text")):
            with self.subTest(why):
                f = self.one(rows)
                self.assertEqual((f.action, f.value, f.needs_review), ("treat-as-layout", True, False))
                self.assertIn(why, f.evidence)


class TextWorkerTests(unittest.TestCase):
    def test_title_from_first_heading_or_paragraph(self):
        fixes, _ = fixes_for(doc(Paragraph("Preface."), Heading("Marine Biology 101", 1), title=None))
        self.assertEqual([(f.action, f.value, f.needs_review) for f in fixes], [("set-title", "Marine Biology 101", False)])
        fixes, _ = fixes_for(doc(Paragraph("Course notes, week 1"), title=None))
        self.assertEqual((fixes[0].value, fixes[0].needs_review), ("Course notes, week 1", True))
        fixes, _ = fixes_for(doc(Image(b"", "png", alt="A cell."), title=None))
        self.assertEqual((fixes[0].value, fixes[0].needs_review), (None, True))

    def test_language_asked_of_the_model(self):
        d = doc(Heading("Bienvenue", 1), Paragraph("Ce cours présente la biologie marine."), language=None)
        fixes, gen = fixes_for(d, {"language": "fr", "confidence": 0.95})
        self.assertEqual([(f.action, f.value, f.confidence, f.needs_review, f.model) for f in fixes],
                         [("set-language", "fr", 0.95, False, "gemma4:12b")])
        self.assertEqual(gen.call_args.kwargs["task"], "classification")
        self.assertEqual(gen.call_args.kwargs["data_class"], "I")
        self.assertIn("Ce cours présente", gen.call_args.args[0][0]["content"])
        fixes, _ = fixes_for(doc(Paragraph("x"), language="english please"), {"language": "English (US)", "confidence": 1})
        self.assertEqual((fixes[0].rule, fixes[0].value, fixes[0].needs_review), ("document-bad-language", None, True))
        fixes, gen = fixes_for(doc(Table([["Semaine", "Sujet"], ["1", "Les cellules"]]), language=None),
                               {"language": "French", "confidence": 0.9})
        self.assertEqual((fixes[0].value, fixes[0].needs_review), ("fr", False))  # a name is mapped to its tag
        self.assertIn("Semaine Sujet 1 Les cellules", gen.call_args.args[0][0]["content"])  # table text counts
        fixes, _ = fixes_for(doc(Paragraph("x"), language=None), {"language": "en", "confidence": 0.4})
        self.assertTrue(fixes[0].needs_review)
        self.assertIn("below 0.7", fixes[0].review_reason)

    def test_link_text_from_the_paragraph_before(self):
        url = "https://example.org/timeline-template"
        d = doc(Paragraph(f"Free project timeline template: {url}"), Link(url, url))
        fixes, gen = fixes_for(d)
        self.assertEqual([(f.action, f.value, f.confidence, f.needs_review) for f in fixes],
                         [("set-link-text", "Free project timeline template", 0.85, False)])
        self.assertEqual(fixes[0].worker, TEXT)
        gen.assert_not_called()

    def test_link_text_from_the_model_when_context_is_silent(self):
        url = "https://www.youtube.com/watch?v=abc"
        d = doc(Paragraph("As you watch this video clip, think about the questions."), Link("", url))
        fixes, gen = fixes_for(d, {"text": "Video: watch before class", "confidence": 0.8})
        self.assertEqual([(f.rule, f.action, f.value, f.needs_review) for f in fixes],
                         [("link-no-text", "set-link-text", "Video: watch before class", False)])
        self.assertEqual(gen.call_args.kwargs["task"], "classification")
        prompt = gen.call_args.args[0][0]["content"]
        self.assertIn(url, prompt)
        self.assertIn("think about the questions", prompt)
        for bad in ({"text": "click here", "confidence": 0.9}, {"text": url, "confidence": 0.9}, "not json at all"):
            with self.subTest(bad):
                fixes, _ = fixes_for(doc(Paragraph("Read this."), Link("here", url)), bad)
                self.assertEqual((fixes[0].rule, fixes[0].value, fixes[0].needs_review), ("link-vague-text", None, True))


    def test_model_failure_is_a_finding_not_a_crash(self):
        d = doc(Paragraph("Read this."), Link("here", "https://example.org/x"), language=None)
        with mock.patch.object(model_answers, "generate", side_effect=ConnectionError("No Ollama at http://ollama:11434")):
            fixes = propose_fixes(d, data_class="I")
        self.assertEqual([(f.action, f.value, f.needs_review) for f in fixes],
                         [("set-language", None, True), ("set-link-text", None, True)])
        self.assertIn("ConnectionError: No Ollama", fixes[0].evidence)


class RoutingAndReportTests(unittest.TestCase):
    def test_alt_text_issues_are_left_to_the_alt_text_worker(self):
        d = doc(Heading("A", 1), Image(b"", "png"))
        fixes, gen = fixes_for(d)
        self.assertEqual(fixes, [])
        gen.assert_not_called()

    def test_issues_can_be_passed_in(self):
        d = doc(Heading("A", 1), Paragraph("- item"), Paragraph("- other"))
        issues = audit(d)[:1]
        fixes, _ = fixes_for(d) if False else (propose_fixes(d, data_class="P", issues=issues), None)
        self.assertEqual(len(fixes), 1)

    def test_reports(self):
        fixes = [
            Fix("fake-list", STRUCTURE, "convert-to-list", {"text": "stir", "ordered": False, "level": 1}, 0.9, False, "", "marker '-'", None, 3),
            Fix("table-no-header-row", TABLES, "mark-header-row", True, 0.5, True, "the first row may not be column headings", "numeric cells", 2, 7),
            Fix("document-no-language", TEXT, "set-language", "fr", 0.95, False, "", "the model's judgement", None, None, "gemma4:12b"),
        ]
        text = report_markdown(fixes, "notes.docx")
        self.assertIn("3 proposals; 1 need review, 2 can be applied as proposed", text)
        self.assertIn("## Structure worker (1)", text)
        self.assertIn('| block 3 | fake-list | convert-to-list | {"text": "stir", "ordered": false, "level": 1} | 0.90 | no |', text)
        self.assertIn("| page 2 | table-no-header-row | mark-header-row | true | 0.50 | the first row may not be column headings |", text)
        self.assertIn("| document | document-no-language | set-language | fr | 0.95 | no |", text)
        data = json.loads(report_json(fixes))
        self.assertEqual([d["action"] for d in data], ["convert-to-list", "mark-header-row", "set-language"])
        self.assertEqual(data[2]["model"], "gemma4:12b")


if __name__ == "__main__":
    unittest.main()
