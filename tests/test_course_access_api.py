import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image as PILImage

from campus_ai.core.llm import LLMResponse
from campus_ai.course_access import alt_text, model_answers, rebuild
from campus_ai.course_access.api import PREFIX, create_app
from campus_ai.course_access.parser import Document, Heading, Image, Link, Paragraph, parse


def png() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), "red").save(buf, "PNG")
    return buf.getvalue()


def sample_docx(folder: Path) -> Path:
    """A messy document: no title, a typed list, an image without alt text, a bare URL."""
    d = Document("docx", title=None, language="en", blocks=[
        Heading("Marine Biology 101", 1), Paragraph("- Boil water"), Image(png(), "png"),
        Paragraph("Reading: https://x.org/reading"), Link("https://x.org/reading", "https://x.org/reading")])
    path = folder / "week1.docx"
    rebuild.to_docx(d, path)
    return path


ALT_REPLY = LLMResponse(json.dumps({"kind": "photo", "decorative": False, "alt": "A red square.", "long_description": "",
                                    "confidence": 0.9}), "gemma4:12b", 1, 1, "stop")


class ReviewQueueApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "work"
        self.client = TestClient(create_app(self.root))
        self.docx = sample_docx(Path(self.tmp.name))
        for target in (model_answers, alt_text):
            patcher = mock.patch.object(target, "generate", return_value=ALT_REPLY)
            patcher.start()
            self.addCleanup(patcher.stop)

    def upload(self, path=None, **params):
        path = path or self.docx
        with open(path, "rb") as f:
            return self.client.post(f"{PREFIX}/jobs", files={"file": (path.name, f)}, params=params)

    def test_upload_lists_proposals_and_persists(self):
        created = self.upload(alt_text=1)
        self.assertEqual(created.status_code, 201, created.text)
        job_id = created.json()["id"]
        self.assertEqual(created.json()["name"], "week1.docx")
        self.assertGreaterEqual(created.json()["issues"], 3)
        self.assertEqual(self.client.get(f"{PREFIX}/jobs").json()[0]["id"], job_id)
        job = self.client.get(f"{PREFIX}/jobs/{job_id}").json()
        actions = {f["action"] for f in job["fixes"]}
        self.assertTrue({"convert-to-list", "set-title", "set-link-text"} <= actions, actions)
        self.assertEqual([a["alt"] for a in job["alt_texts"]], ["A red square."])
        self.assertFalse(job["alt_texts"][0]["needs_review"])
        self.assertIn("1.1.1", job["issues"]["by_criterion"])
        self.assertEqual(job["outputs"], ["week1.report.md"])
        # A fresh process sees the same job and re-parses the upload for its images.
        again = TestClient(create_app(self.root))
        self.assertEqual(again.get(f"{PREFIX}/jobs/{job_id}").json()["name"], "week1.docx")
        block = job["alt_texts"][0]["block"]
        image = again.get(f"{PREFIX}/jobs/{job_id}/images/{block}")
        self.assertEqual((image.status_code, image.headers["content-type"], image.content), (200, "image/png", png()))
        self.assertEqual(again.get(f"{PREFIX}/jobs/{job_id}/images/0").status_code, 404)
        self.assertEqual(self.client.get(f"{PREFIX}/health").json(), {"status": "ok", "jobs": 1})

    def test_decisions_drive_the_rebuild(self):
        job_id = self.upload(alt_text=1).json()["id"]
        job = self.client.get(f"{PREFIX}/jobs/{job_id}").json()
        by_action = {f["action"]: f for f in job["fixes"]}
        alt = job["alt_texts"][0]
        decided = self.client.post(f"{PREFIX}/jobs/{job_id}/decisions", json={
            "fixes": {str(by_action["convert-to-list"]["id"]): {"decision": "reject"},
                      str(by_action["set-title"]["id"]): {"decision": "approve", "value": "Marine Biology 101, week 1"}},
            "alt_texts": {str(alt["id"]): {"decision": "approve", "alt": "A red square used as a marker.", "decorative": False}},
        })
        self.assertEqual(decided.status_code, 200, decided.text)
        self.assertEqual(self.client.get(f"{PREFIX}/jobs/{job_id}").json()["summary"]["decided"], 3)

        built = self.client.post(f"{PREFIX}/jobs/{job_id}/rebuild").json()
        result = built["result"]
        self.assertLess(result["after"], result["before"])
        self.assertIn("fake-list", result["remaining"])  # rejected, so still there
        self.assertNotIn("image-missing-alt", result["remaining"])
        self.assertNotIn("document-no-title", result["remaining"])
        self.assertEqual(result["new"], {})
        self.assertEqual(sorted(built["outputs"]), sorted(["week1.docx", "week1.html", "week1.report.md", "week1.review.md", "week1.statement.md"]))

        out = self.client.get(f"{PREFIX}/jobs/{job_id}/files/week1.docx")
        self.assertEqual(out.status_code, 200)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "week1.docx"
            path.write_bytes(out.content)
            back = parse(path)
        self.assertEqual(back.title, "Marine Biology 101, week 1")
        self.assertEqual([b.alt for b in back.blocks if isinstance(b, Image)], ["A red square used as a marker."])
        self.assertTrue(any(isinstance(b, Paragraph) and b.text == "- Boil water" for b in back.blocks))
        statement = self.client.get(f"{PREFIX}/jobs/{job_id}/files/week1.statement.md").text
        self.assertIn("Proposals applied in this version: 3", statement)
        self.assertIn("Not checked automatically", statement)
        html = self.client.get(f"{PREFIX}/jobs/{job_id}/files/week1.html").text
        self.assertIn('alt="A red square used as a marker."', html)
        self.assertEqual(self.client.get(f"{PREFIX}/jobs/{job_id}/files/job.json").status_code, 404)
        self.assertEqual(self.client.get(f"{PREFIX}/jobs/{job_id}/files/../job.json").status_code, 404)

        # Changing a decision invalidates the result until the next rebuild.
        self.client.post(f"{PREFIX}/jobs/{job_id}/decisions", json={"fixes": {str(by_action["convert-to-list"]["id"]): {"decision": None}}})
        job = self.client.get(f"{PREFIX}/jobs/{job_id}").json()
        self.assertIsNone(job["result"])
        self.assertEqual(job["summary"]["decided"], 2)

    def test_validation(self):
        bad = Path(self.tmp.name) / "notes.txt"
        bad.write_text("hello", encoding="utf-8")
        self.assertEqual(self.upload(bad).status_code, 415)
        self.assertEqual(self.upload(data_class="R").status_code, 422)
        broken = Path(self.tmp.name) / "broken.docx"
        broken.write_bytes(b"not a docx")
        self.assertEqual(self.upload(broken).status_code, 422)
        self.assertEqual(list(self.root.iterdir()), [])  # nothing left behind
        self.assertEqual(self.client.get(f"{PREFIX}/jobs/nope").status_code, 404)
        self.assertEqual(self.client.get(f"{PREFIX}/jobs/0123456789ab").status_code, 404)
        job_id = self.upload().json()["id"]
        bad_decision = self.client.post(f"{PREFIX}/jobs/{job_id}/decisions", json={"fixes": {"0": {"decision": "maybe"}}})
        self.assertEqual(bad_decision.status_code, 422)
        missing = self.client.post(f"{PREFIX}/jobs/{job_id}/decisions", json={"fixes": {"999": {"decision": "approve"}}})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(self.client.delete(f"{PREFIX}/jobs/{job_id}").status_code, 204)
        self.assertEqual(self.client.get(f"{PREFIX}/jobs/{job_id}").status_code, 404)
        self.assertEqual(self.client.get(f"{PREFIX}/jobs").json(), [])


if __name__ == "__main__":
    unittest.main()
