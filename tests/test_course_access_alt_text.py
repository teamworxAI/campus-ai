import base64
import json
import unittest
from unittest import mock

from campus_ai.core.llm import LLMResponse
from campus_ai.course_access import alt_text
from campus_ai.course_access.alt_text import (
    AltText, CONFIDENCE_THRESHOLD, describe, images_needing_alt, propose, report_json, report_markdown,
)
from campus_ai.course_access.parser import Document, Heading, Image, Paragraph

PNG = b"\x89PNG fake bytes"


def doc(*blocks, fmt="pptx", title="Week 4: Salmon ecology"):
    return Document(source_format=fmt, title=title, language="en-CA", page_count=3, blocks=list(blocks))


def answer(**fields):
    body = {"kind": "photo", "decorative": False, "alt": "A sockeye salmon leaping a waterfall.",
            "long_description": "", "confidence": 0.9, **fields}
    return LLMResponse(json.dumps(body), "gemma4:12b", 100, 40, "stop")


class SelectionTests(unittest.TestCase):
    def test_only_images_the_audit_flags(self):
        d = doc(Image(PNG, "png"), Image(PNG, "png", alt="Diagram of the salmon life cycle, egg to spawner."),
                Image(PNG, "png", decorative=True), Image(PNG, "jpg", alt="IMG_2041.JPG"), Paragraph("x"))
        self.assertEqual(images_needing_alt(d), [0, 3])

    def test_describe_needs_an_image(self):
        with self.assertRaises(TypeError):
            describe(doc(Paragraph("x")), 0, data_class="I")


class PromptTests(unittest.TestCase):
    def test_model_sees_image_and_context(self):
        d = doc(Heading("Spawning runs", 1, page=2),
                Image(PNG, "jpg", alt="Picture", page=2, nearby_text="Spawning runs\nAdults return in autumn."))
        with mock.patch.object(alt_text, "generate", return_value=answer()) as gen:
            propose(d, data_class="I")
        _, kwargs = gen.call_args
        messages = gen.call_args.args[0]
        self.assertEqual(kwargs["task"], "vision")
        self.assertEqual(kwargs["data_class"], "I")
        self.assertIn('"kind"', kwargs["system"])
        text, image = messages[0]["content"]
        self.assertIn("Week 4: Salmon ecology (PPTX). Slide 2.", text["text"])
        self.assertIn("Adults return in autumn.", text["text"])
        self.assertIn("placeholder to replace: 'Picture'", text["text"])
        self.assertEqual(image["source"]["media_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(image["source"]["data"]), PNG)

    def test_page_label_per_format(self):
        d = doc(Image(PNG, "png", page=3), fmt="pdf")
        with mock.patch.object(alt_text, "generate", return_value=answer()) as gen:
            propose(d, data_class="P")
        self.assertIn("(PDF). Page 3.", gen.call_args.args[0][0]["content"][0]["text"])


class CheckTests(unittest.TestCase):
    def proposal(self, reply, image=None):
        d = doc(image or Image(PNG, "png", page=1))
        with mock.patch.object(alt_text, "generate", return_value=reply):
            return describe(d, 0, data_class="I")

    def test_confident_photo_is_applied_without_review(self):
        p = self.proposal(answer(alt="an image of a sockeye salmon leaping a waterfall."))
        self.assertEqual(p, AltText(0, 1, "photo", False, "A sockeye salmon leaping a waterfall.", "", 0.9,
                                    False, "", "gemma4:12b"))

    def test_charts_diagrams_equations_and_text_always_reviewed(self):
        self.assertEqual(self.proposal(answer(kind="text")).review_reason, "images of text always go to review")
        for kind in ("chart", "diagram", "equation", "text"):
            p = self.proposal(answer(kind=kind, confidence=0.99, long_description="Returns by year: 2019 1.2M ..."))
            self.assertTrue(p.needs_review, kind)
            self.assertIn("always go to review", p.review_reason)
            self.assertEqual(p.long_description, "Returns by year: 2019 1.2M ...")

    def test_low_confidence_reviewed(self):
        p = self.proposal(answer(confidence=0.4))
        self.assertTrue(p.needs_review)
        self.assertIn(f"below {CONFIDENCE_THRESHOLD}", p.review_reason)
        self.assertFalse(self.proposal(answer(confidence=CONFIDENCE_THRESHOLD)).needs_review)

    def test_decorative_has_no_alt_and_is_reviewed(self):
        p = self.proposal(answer(decorative=True, alt="A thin grey line.", confidence=0.95))
        self.assertTrue(p.decorative)
        self.assertEqual(p.alt, "")
        self.assertIn("hides it from screen readers", p.review_reason)
        self.assertTrue(self.proposal(answer(kind="decorative")).decorative)

    def test_bad_answers_go_to_review(self):
        cases = {
            "Sorry, I cannot see the image.": "not JSON",
            '{"kind": "photo", "alt": "x"': "not JSON",
            '["not", "an", "object"]': "not JSON",
            '{"kind": "photo", "alt": "", "confidence": 0.9}': "no description",
            '{"kind": "photo", "alt": "' + "x" * 201 + '", "confidence": 0.9}': "over 200 characters",
            '{"kind": "sculpture", "alt": "A bronze fish.", "confidence": "high"}': "confidence 0.00",
        }
        for text, reason in cases.items():
            p = self.proposal(LLMResponse(text, "m", 1, 1, "stop"))
            self.assertTrue(p.needs_review, text)
            self.assertIn(reason, p.review_reason, text)
        self.assertEqual(self.proposal(LLMResponse(list(cases)[-1], "m", 1, 1, "stop")).kind, "other")

    def test_json_in_a_code_fence_and_clamped_confidence(self):
        text = 'Here you go:\n```json\n{"kind": "illustration", "alt": "a map of the Fraser River.", "confidence": 1.7}\n```'
        p = self.proposal(LLMResponse(text, "m", 1, 1, "stop"))
        self.assertEqual((p.kind, p.alt, p.confidence, p.needs_review), ("illustration", "A map of the Fraser River.", 1.0, False))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.proposals = [
            AltText(0, 1, "photo", False, "A sockeye salmon.", "", 0.9, False, "", "m"),
            AltText(2, 2, "chart", False, "Bar chart of returns by year.", "2019: 1.2M; 2020: 0.8M.", 0.8,
                    True, "charts always go to review", "m"),
            AltText(4, None, "decorative", True, "", "", 0.95, True, "marking an image decorative hides it from screen readers", "m"),
        ]

    def test_markdown_review_sheet(self):
        text = report_markdown(self.proposals, "week4.pptx")
        self.assertIn("3 images need alt text; 2 need review, 1 can be applied as proposed", text)
        self.assertIn("## Image at block 0 (page 1): photo, confidence 0.90", text)
        self.assertIn("- **Alt:** A sockeye salmon.", text)
        self.assertIn("- **Long description:** 2019: 1.2M; 2020: 0.8M.", text)
        self.assertIn("- **Review:** charts always go to review", text)
        self.assertIn("## Image at block 4: decorative", text)
        self.assertIn("**Decorative:** no alt text", text)

    def test_json(self):
        data = json.loads(report_json(self.proposals))
        self.assertEqual([d["block"] for d in data], [0, 2, 4])
        self.assertEqual(data[1]["review_reason"], "charts always go to review")


if __name__ == "__main__":
    unittest.main()
