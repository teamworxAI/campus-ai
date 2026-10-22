import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_course_docs", ROOT / "scripts" / "fetch_course_docs.py")
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


def office(kind: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(f"{kind}/document.xml", "<x/>")
    return buf.getvalue()


PDF = b"%PDF-1.7 fake"
PPTX, DOCX = office("ppt"), office("word")


def archive(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


class SourceListTests(unittest.TestCase):
    def test_every_source_is_open_and_attributed(self):
        for entry in fetcher.SOURCES:
            with self.subTest(entry["title"]):
                self.assertIn(entry["licence"], fetcher.OPEN_LICENCES)
                self.assertNotRegex(entry["licence"], r"NC|ND")
                self.assertTrue(entry["url"].startswith("https://"))
                self.assertTrue(entry["page"].startswith("https://"))
                for key in ("source", "name", "title", "authors"):
                    self.assertTrue(entry[key], key)
        self.assertEqual(len({(e["source"], e["name"]) for e in fetcher.SOURCES}), len(fetcher.SOURCES))


class FormatTests(unittest.TestCase):
    def test_detects_from_bytes_not_names(self):
        self.assertEqual(fetcher.detect_format(PDF), "pdf")
        self.assertEqual(fetcher.detect_format(PPTX), "pptx")
        self.assertEqual(fetcher.detect_format(DOCX), "docx")
        self.assertEqual(fetcher.detect_format(archive({"a.txt": b"x"})), "zip")
        self.assertIsNone(fetcher.detect_format(b"<html>blocked</html>"))
        self.assertIsNone(fetcher.detect_format(b"PK not really a zip"))

    def test_unpack_keeps_documents_only(self):
        data = archive({"Slides/Week 1.pptx": PPTX, "Slides/notes.docx": DOCX, "__MACOSX/._Week 1.pptx": b"junk",
                        "readme.txt": b"hello", "video.mp4": b"\x00\x00", "Slides/.DS_Store": b"x"})
        self.assertEqual([(n, fetcher.detect_format(d)) for n, d in fetcher.unpack(data)],
                         [("Week 1.pptx", "pptx"), ("notes.docx", "docx")])


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "course_access"

    def run_main(self, replies: dict, argv=()):
        def fake_download(url):
            return replies[url]
        with mock.patch.object(fetcher, "download", side_effect=fake_download), \
             mock.patch.dict("os.environ", {"DATA_DIR": self.tmp.name}), \
             mock.patch.object(fetcher, "SOURCES", [
                 dict(source="uni-a", name="lecture-1", url="https://a/1", page="https://a", title="Lecture 1",
                      authors="A. Author", licence="CC-BY-4.0"),
                 dict(source="uni-a", name="slides", url="https://a/slides.zip", page="https://a", title="Slides",
                      authors="A. Author", licence="CC-BY-4.0"),
                 dict(source="uni-b", name="notes", url="https://b/notes", page="https://b", title="Notes",
                      authors="B. Author", licence="CC-BY-SA-4.0"),
             ]):
            return fetcher.main(list(argv))

    def manifest(self):
        return [json.loads(line) for line in (self.root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_downloads_unpacks_and_records(self):
        replies = {"https://a/1": PDF, "https://a/slides.zip": archive({"w1.pptx": PPTX, "w2.pptx": PPTX}),
                   "https://b/notes": DOCX}
        self.assertEqual(self.run_main(replies), 0)
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*.*") if p.suffix != ".jsonl"),
                         ["uni-a/lecture-1.pdf", "uni-a/slides-w1.pptx", "uni-a/slides-w2.pptx", "uni-b/notes.docx"])
        records = self.manifest()
        self.assertEqual(len(records), 4)
        notes = records[-1]
        self.assertEqual(notes["path"], "uni-b/notes.docx")
        self.assertEqual(notes["format"], "docx")
        self.assertEqual(notes["licence"], "CC-BY-SA-4.0")
        self.assertEqual(notes["licence_url"], "https://creativecommons.org/licenses/by-sa/4.0/")
        self.assertEqual(notes["bytes"], len(DOCX))
        self.assertEqual(len(notes["sha256"]), 64)
        for key in ("url", "page", "title", "authors", "fetched"):
            self.assertTrue(notes[key], key)
        # A second run keeps what is there and adds nothing to the manifest.
        self.assertEqual(self.run_main(replies), 0)
        self.assertEqual(len(self.manifest()), 4)
        self.assertEqual(self.run_main(replies, ["--force"]), 0)
        self.assertEqual(len(self.manifest()), 8)

    def test_bad_downloads_fail_that_source_only(self):
        replies = {"https://a/1": b"<html>sign in</html>", "https://a/slides.zip": archive({"readme.txt": b"x"}),
                   "https://b/notes": DOCX}
        self.assertEqual(self.run_main(replies), 1)
        self.assertEqual([r["path"] for r in self.manifest()], ["uni-b/notes.docx"])

    def test_only_filter(self):
        replies = {"https://b/notes": DOCX}
        self.assertEqual(self.run_main(replies, ["--only", "uni-b"]), 0)
        self.assertEqual([r["path"] for r in self.manifest()], ["uni-b/notes.docx"])

    def test_non_open_licence_refused(self):
        entry = dict(source="x", name="y", url="https://x/y", page="https://x", title="T", authors="A", licence="CC-BY-NC-4.0")
        with self.assertRaisesRegex(ValueError, "not an open content licence"):
            fetcher.fetch(entry, self.root, force=False)


if __name__ == "__main__":
    unittest.main()
