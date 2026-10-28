"""OCR for scanned PDF pages (A7). The real Tesseract binary is used when present (the
Docker image has it); the TSV parsing and the decisions around it are also tested with
the program mocked, so they run anywhere."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from campus_ai.course_access import parser
from campus_ai.course_access.audit import OCR, NOT_CHECKED, audit
from campus_ai.course_access.parser import Image, Paragraph, parse
from campus_ai.course_access.rebuild import apply, to_html
from campus_ai.course_access.workers import propose_fixes

LINES = ["Introduction to Ocean Science", "Week one covers the water cycle and ocean currents.",
         "Students should read chapter two before the lecture."]
HAVE_TESSERACT = shutil.which("tesseract") is not None


def scanned_png(path: Path, lines=LINES, size=46) -> None:
    """A white page image with the lines of text drawn on it (a stand-in for a scan)."""
    page = PILImage.new("RGB", (1700, 2200), "white")  # letter paper at 200 dpi
    draw = ImageDraw.Draw(page)
    font = ImageFont.load_default(size=size)
    for i, line in enumerate(lines):
        draw.text((150, 200 + i * 80), line, fill="black", font=font)
    page.save(path)


def pdf_with(path: Path, pages: list) -> Path:
    """One page per entry: a PNG path is a full-page image, a string is born-digital text."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Scan")
    for page in pages:
        if isinstance(page, Path):
            c.drawImage(str(page), 0, 0, width=letter[0], height=letter[1])
        else:
            c.drawString(72, 700, page)
        c.showPage()
    c.save()
    return path


class TempDirCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)


@unittest.skipUnless(HAVE_TESSERACT, "tesseract is not installed (it is in the Docker image)")
class RealTesseractTests(TempDirCase):
    def setUp(self):
        super().setUp()
        png = self.dir / "page.png"
        scanned_png(png)
        self.pdf = pdf_with(self.dir / "scan.pdf", ["Born-digital page with a text layer.", png])

    def test_scanned_page_is_read_and_flagged(self):
        document = parse(self.pdf)
        self.assertEqual(document.ocr_pages, [2])
        self.assertTrue(document.ocr_engine.startswith("tesseract 5"), document.ocr_engine)
        ocr = [b for b in document.blocks if getattr(b, "ocr", False)]
        self.assertTrue(ocr)
        self.assertTrue(all(isinstance(b, Paragraph) and b.page == 2 for b in ocr))
        self.assertFalse(any(isinstance(b, Image) for b in document.blocks))  # the scan is the text
        text = " ".join(b.text for b in ocr).lower()
        for word in ("introduction", "ocean", "science", "currents", "chapter", "lecture"):
            self.assertIn(word, text)
        self.assertGreater(ocr[0].ocr_confidence, 0.8)
        self.assertLessEqual(ocr[0].ocr_confidence, 1.0)

    def test_born_digital_page_is_never_ocrd(self):
        document = parse(self.pdf)
        first = [b for b in document.blocks if b.page == 1]
        self.assertEqual([(type(b), b.text, b.ocr) for b in first],
                         [(Paragraph, "Born-digital page with a text layer.", False)])

    def test_audit_proposal_and_rebuild(self):
        document = parse(self.pdf)
        issues = [i for i in audit(document) if i.rule == "scanned-page"]
        self.assertEqual([(i.criterion, i.page, i.fix) for i in issues], [("1.4.5", 2, OCR)])
        self.assertIn("words", issues[0].message)
        fixes = propose_fixes(document, data_class="I", issues=issues)
        self.assertEqual(len(fixes), 1)
        fix = fixes[0]
        self.assertEqual((fix.action, fix.page), ("ocr", 2))
        self.assertGreater(fix.confidence, 0.8)
        self.assertIn("eng+fra", fix.evidence)  # no /Lang in the PDF: both languages
        self.assertIn("ocean", fix.value.lower())
        rebuilt = apply(document, fixes)
        self.assertEqual([b.text for b in rebuilt.blocks], [b.text for b in document.blocks])
        self.assertIn("Ocean", to_html(rebuilt))

    def test_declared_language_is_passed_to_the_engine(self):
        png = self.dir / "fr.png"
        scanned_png(png, ["Introduction aux sciences de l'ocean", "Les etudiants doivent lire le chapitre deux."])
        path = pdf_with(self.dir / "fr.pdf", [png])
        with mock.patch.object(parser, "_ocr_languages", wraps=parser._ocr_languages) as languages:
            document = parse(path)
        self.assertEqual(document.ocr_pages, [1])
        languages.assert_called_once_with(None)


def ocr_fix(document):
    """The ocr proposal (other rules, such as the missing language, would ask a model: not here)."""
    issues = [i for i in audit(document) if i.rule == "scanned-page"]
    return propose_fixes(document, data_class="I", issues=issues)[0]


def tsv(words):
    """Tesseract TSV text for (block, par, line, left, top, text, conf) tuples, header included."""
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = ["1\t1\t0\t0\t0\t0\t0\t0\t1700\t2200\t-1\t"]  # a page-level row: ignored
    for n, (block, par, line, left, top, text, conf) in enumerate(words, start=1):
        rows.append(f"5\t1\t{block}\t{par}\t{line}\t{n}\t{left}\t{top}\t100\t40\t{conf}\t{text}")
    return "\n".join([header, *rows]) + "\n"


class TsvTests(unittest.TestCase):
    def test_words_become_lines_and_paragraphs_with_mean_confidence(self):
        words = [(1, 1, 1, 100, 100, "Ocean", 96), (1, 1, 1, 250, 100, "warming", 90),
                 (1, 1, 2, 100, 150, "is", 94), (1, 1, 2, 160, 150, "rising.", 80),
                 (1, 2, 1, 100, 400, "Second", 100), (1, 2, 1, 250, 400, "paragraph", 100),
                 (1, 2, 1, 400, 400, "noise", -1), (2, 1, 1, 900, 100, "Column", 50)]
        paragraphs, confidence = parser._tsv_paragraphs(tsv(words))
        self.assertEqual(paragraphs, ["Ocean warming is rising.", "Second paragraph", "Column"])
        self.assertAlmostEqual(confidence, (96 + 90 + 94 + 80 + 100 + 100 + 50) / 7 / 100)

    def test_empty_output(self):
        self.assertEqual(parser._tsv_paragraphs(tsv([])), ([], 0.0))

    def test_languages(self):
        cases = {"en-CA": "eng", "fr": "fra", "FR_ca": "fra", None: "eng+fra", "de": "eng+fra", "": "eng+fra"}
        for tag, expected in cases.items():
            self.assertEqual(parser._ocr_languages(tag), expected, tag)

    def test_huge_pages_are_rendered_smaller(self):
        self.assertEqual(parser._ocr_resolution(mock.Mock(width=612, height=792)), 300)
        self.assertLess(parser._ocr_resolution(mock.Mock(width=612 * 5, height=792 * 5)), 300)


class MockedTesseractTests(TempDirCase):
    """The scanned-page path with the program mocked: runs without the binary."""

    def parse_with(self, words):
        png = self.dir / "p.png"
        scanned_png(png)
        path = pdf_with(self.dir / "scan.pdf", [png])

        def run(command, **kwargs):
            if "--version" in command:
                return subprocess.CompletedProcess(command, 0, b"tesseract 5.3.0\n leptonica", b"")
            self.assertIn("tsv", command)
            self.assertEqual(command[command.index("-l") + 1], "eng+fra")
            self.assertTrue(kwargs["input"].startswith(b"\x89PNG"))
            return subprocess.CompletedProcess(command, 0, tsv(words).encode(), b"")

        with mock.patch.object(parser.shutil, "which", return_value="/usr/bin/tesseract"), \
                mock.patch.object(parser.subprocess, "run", side_effect=run):
            return parse(path)

    def test_scanned_page_becomes_flagged_paragraphs(self):
        words = [(1, 1, 1, 100, 100, "Hello", 90), (1, 1, 1, 250, 100, "world", 70)]
        document = self.parse_with(words)
        self.assertEqual(document.ocr_pages, [1])
        self.assertEqual(document.ocr_engine, "tesseract 5.3.0 (eng+fra)")
        self.assertEqual([(b.text, b.ocr, b.page) for b in document.blocks], [("Hello world", True, 1)])
        self.assertAlmostEqual(document.blocks[0].ocr_confidence, 0.8)
        rules = [i.rule for i in audit(document)]
        scanned = [i for i in audit(document) if i.rule == "scanned-page"]
        self.assertEqual(len(scanned), 1)
        self.assertIn("2 words", scanned[0].message)
        self.assertIn("0.80", scanned[0].message)
        self.assertNotIn("page-image-only", rules)
        self.assertNotIn("image-missing-alt", rules)  # no Image block to describe
        self.assertTrue(any("OCR" in line for line in NOT_CHECKED))

    def test_low_confidence_or_few_words_need_review(self):
        fix = ocr_fix(self.parse_with([(1, 1, 1, 100, 100, "Hello", 99)]))
        self.assertTrue(fix.needs_review)
        self.assertIn("only 1 words", fix.review_reason)
        words = [(1, 1, 1, 100 + 120 * i, 100, f"word{i}", 70) for i in range(20)]
        poor = ocr_fix(self.parse_with(words))
        self.assertTrue(poor.needs_review)
        self.assertIn("below 0.85", poor.review_reason)
        self.assertAlmostEqual(poor.confidence, 0.7)
        self.assertIn("20 words", poor.evidence)
        self.assertIn("tesseract", poor.evidence)
        good = [(1, 1, 1, 100 + 120 * i, 100, f"word{i}", 95) for i in range(20)]
        fix = ocr_fix(self.parse_with(good))
        self.assertFalse(fix.needs_review)
        self.assertEqual(fix.review_reason, "")

    def test_no_words_or_no_binary_leaves_an_image_for_a_person(self):
        document = self.parse_with([])
        self.assertEqual(document.ocr_pages, [])
        self.assertEqual([i.rule for i in audit(document) if i.criterion == "1.4.5"], ["page-image-only"])
        png = self.dir / "q.png"
        scanned_png(png)
        with mock.patch.object(parser.shutil, "which", return_value=None):
            document = parse(pdf_with(self.dir / "nobinary.pdf", [png]))
        self.assertEqual(document.ocr_pages, [])
        self.assertTrue(any(isinstance(b, Image) for b in document.blocks))

    def test_tesseract_failure_is_not_a_crash(self):
        png = self.dir / "r.png"
        scanned_png(png)
        path = pdf_with(self.dir / "broken.pdf", [png])
        with mock.patch.object(parser.shutil, "which", return_value="/usr/bin/tesseract"), \
                mock.patch.object(parser.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "tesseract")):
            document = parse(path)
        self.assertEqual(document.ocr_pages, [])

    def test_born_digital_page_does_not_call_tesseract(self):
        path = pdf_with(self.dir / "text.pdf", ["Plain text page."])
        with mock.patch.object(parser.shutil, "which", return_value="/usr/bin/tesseract"), \
                mock.patch.object(parser.subprocess, "run") as run:
            document = parse(path)
        run.assert_not_called()
        self.assertEqual(document.ocr_pages, [])
        self.assertFalse(document.blocks[0].ocr)

    def test_small_image_on_a_page_is_not_a_scan(self):
        png = self.dir / "small.png"
        PILImage.new("RGB", (100, 100), "red").save(png)
        c = canvas.Canvas(str(self.dir / "small.pdf"), pagesize=letter)
        c.drawImage(str(png), 72, 600, width=72, height=72)  # no text, but a tiny share of the page
        c.save()
        with mock.patch.object(parser.shutil, "which", return_value="/usr/bin/tesseract"), \
                mock.patch.object(parser.subprocess, "run") as run:
            document = parse(self.dir / "small.pdf")
        run.assert_not_called()
        self.assertEqual(document.ocr_pages, [])


if __name__ == "__main__":
    unittest.main()
