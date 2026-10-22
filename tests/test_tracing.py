import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from campus_ai.core import data_classes, tracing


class TracingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.dict("os.environ", {"CAMPUS_AI_TRACE_DIR": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def lines(self, run):
        return [json.loads(line) for line in (self.dir / f"{run}.jsonl").read_text().splitlines()]

    def test_default_dir(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(tracing.trace_dir(), Path("traces"))

    def test_run_gets_its_own_file(self):
        outside = tracing.run_id()
        with tracing.run("alt text / doc 1") as run:
            self.assertRegex(run, r"^\d{8}T\d{6}Z-alt-text-doc-1-[0-9a-f]{6}$")
            tracing.record("tool", tool="parse", data_class="I", outcome="ok")
            tracing.record("tool", tool="audit", data_class="I", outcome="ok")
        self.assertEqual(tracing.run_id(), outside)
        entries = self.lines(run)
        self.assertEqual([entry["tool"] for entry in entries], ["parse", "audit"])
        self.assertEqual({entry["run"] for entry in entries}, {run})
        self.assertTrue(all(entry["time"].endswith("+00:00") for entry in entries))

    def test_record_refuses_content_fields(self):
        with self.assertRaisesRegex(ValueError, "metadata only"):
            tracing.record("llm", prompt="student accommodation request")
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_span_records_outcome_and_latency(self):
        with tracing.run("span") as run:
            with tracing.span("tool", tool="ok") as fields:
                fields["model"] = "gemma4:e4b"
            with self.assertRaises(KeyError):
                with tracing.span("tool", tool="broken"):
                    raise KeyError("raw text that must not be logged")
            with self.assertRaises(data_classes.RestrictedDataError):
                with tracing.span("tool", tool="restricted", data_class="R"):
                    data_classes.check("R")
        ok, broken, restricted = self.lines(run)
        self.assertEqual((ok["outcome"], ok["model"]), ("ok", "gemma4:e4b"))
        self.assertGreaterEqual(ok["latency_ms"], 0)
        self.assertEqual((broken["outcome"], broken["error"]), ("error", "KeyError"))
        self.assertNotIn("raw text", json.dumps(broken))
        self.assertEqual((restricted["outcome"], restricted["error"]), ("refused", "RestrictedDataError"))


class DataClassTests(unittest.TestCase):
    def test_check(self):
        for allowed in ("P", "I", "S"):
            self.assertEqual(data_classes.check(allowed), allowed)
        with self.assertRaises(data_classes.RestrictedDataError):
            data_classes.check("R")
        for unknown in ("p", "", None, "public"):
            with self.subTest(data_class=unknown), self.assertRaisesRegex(ValueError, "Unknown data class"):
                data_classes.check(unknown)


if __name__ == "__main__":
    unittest.main()
