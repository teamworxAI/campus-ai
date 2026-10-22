import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from campus_ai.core import tracing
from campus_ai.core.data_classes import RestrictedDataError
from campus_ai.core.llm import LLMResponse, backends, config, generate

MESSAGES = [{"role": "user", "content": "Hello"}]
OPEN = re.compile(r"^(Apache-2\.0|MIT|BSD-[23]-Clause)$")


class OllamaRoutingTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(backends.urllib.request, "urlopen")
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        reply = {
            "model": "gemma4:12b",
            "message": {"role": "assistant", "content": "A cat."},
            "prompt_eval_count": 11,
            "eval_count": 3,
            "done_reason": "stop",
        }
        self.urlopen.return_value.__enter__.return_value = io.BytesIO(json.dumps(reply).encode())
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.traces = Path(tmp.name)
        patcher = mock.patch.object(tracing, "trace_dir", return_value=self.traces)
        patcher.start()
        self.addCleanup(patcher.stop)

    def trace_records(self):
        return [json.loads(line) for path in self.traces.glob("*.jsonl") for line in path.read_text().splitlines()]

    def sent_body(self):
        return json.loads(self.urlopen.call_args.args[0].data)

    def test_routes_to_ollama_host(self):
        env = {"OLLAMA_HOST": "http://inference-box:11434/"}
        with mock.patch.dict("os.environ", env, clear=True):
            result = generate(MESSAGES, task="reasoning", data_class="I", system="Sys")
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://inference-box:11434/api/chat")
        body = self.sent_body()
        self.assertEqual(body["model"], "gemma4:12b")
        self.assertFalse(body["stream"])
        self.assertEqual(body["options"]["num_predict"], 16000)
        self.assertEqual(
            body["messages"],
            [{"role": "system", "content": "Sys"}, {"role": "user", "content": "Hello"}],
        )
        self.assertEqual(result, LLMResponse("A cat.", "gemma4:12b", 11, 3, "stop"))

    def test_default_host_is_this_machine(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            generate(MESSAGES, task="classification", data_class="P")
        self.assertEqual(self.urlopen.call_args.args[0].full_url, "http://localhost:11434/api/chat")
        self.assertEqual(self.sent_body()["model"], "gemma4:e4b")

    def test_vision_blocks_converted_to_ollama_images(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
                {"type": "text", "text": "Describe this."},
            ],
        }]
        with mock.patch.dict("os.environ", {}, clear=True):
            generate(messages, task="vision", data_class="P")
        self.assertEqual(
            self.sent_body()["messages"],
            [{"role": "user", "content": "Describe this.", "images": ["AAAA"]}],
        )

    def test_model_override_must_be_open_licensed(self):
        with mock.patch.dict("os.environ", {"CAMPUS_AI_MODEL_VISION": "qwen3-vl:8b"}, clear=True):
            generate(MESSAGES, task="vision", data_class="P")
        self.assertEqual(self.sent_body()["model"], "qwen3-vl:8b")
        self.urlopen.reset_mock()
        for blocked in ("gemma3:12b", "llama3.2-vision:11b"):
            with self.subTest(model=blocked):
                with mock.patch.dict("os.environ", {"CAMPUS_AI_MODEL_VISION": blocked}, clear=True):
                    with self.assertRaisesRegex(ValueError, "prime directive 1"):
                        generate(MESSAGES, task="vision", data_class="P")
        self.urlopen.assert_not_called()

    def test_missing_ollama_names_the_fix(self):
        self.urlopen.side_effect = backends.urllib.error.URLError("Connection refused")
        with mock.patch.dict("os.environ", {"OLLAMA_HOST": "http://ollama:11434"}, clear=True):
            with self.assertRaisesRegex(ConnectionError, r"No Ollama at http://ollama:11434 .*docker compose up -d ollama"):
                generate(MESSAGES, task="reasoning", data_class="P")

    def test_missing_model_names_the_fix(self):
        self.urlopen.side_effect = backends.urllib.error.HTTPError(
            "http://ollama:11434/api/chat", 404, "Not Found", {}, io.BytesIO(b'{"error":"model not found"}'))
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, r"\(404\): .*model not found.*fetch-ollama"):
                generate(MESSAGES, task="reasoning", data_class="P")

    def test_call_writes_trace_without_content(self):
        env = {"OLLAMA_HOST": "http://inference-box:11434"}
        with mock.patch.dict("os.environ", env, clear=True):
            generate(MESSAGES, task="reasoning", data_class="S", system="Secret system prompt")
        [entry] = self.trace_records()
        self.assertEqual(entry["event"], "llm")
        self.assertEqual(
            {key: entry[key] for key in ("task", "model", "host", "data_class", "input_tokens", "output_tokens", "outcome")},
            {"task": "reasoning", "model": "gemma4:12b", "host": "http://inference-box:11434", "data_class": "S",
             "input_tokens": 11, "output_tokens": 3, "outcome": "ok"},
        )
        self.assertGreaterEqual(entry["latency_ms"], 0)
        text = json.dumps(entry)
        self.assertNotIn("Hello", text)
        self.assertNotIn("Secret", text)

    def test_restricted_data_refused_before_model_call(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RestrictedDataError):
                generate(MESSAGES, task="reasoning", data_class="R")
        self.urlopen.assert_not_called()
        [entry] = self.trace_records()
        self.assertEqual((entry["data_class"], entry["outcome"]), ("R", "refused"))
        self.assertNotIn("model", entry)
        self.assertNotIn("Hello", json.dumps(entry))

    def test_data_class_required_and_known(self):
        with self.assertRaises(TypeError):
            generate(MESSAGES, task="reasoning")
        with self.assertRaisesRegex(ValueError, "Unknown data class"):
            generate(MESSAGES, task="reasoning", data_class="public")
        self.urlopen.assert_not_called()

    def test_model_error_traced(self):
        self.urlopen.side_effect = OSError("connection refused")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(OSError):
                generate(MESSAGES, task="classification", data_class="P")
        [entry] = self.trace_records()
        self.assertEqual((entry["model"], entry["outcome"], entry["error"]), ("gemma4:e4b", "error", "OSError"))

    def test_unknown_task_rejected(self):
        with self.assertRaises(ValueError):
            generate(MESSAGES, task="poetry", data_class="P")
        self.urlopen.assert_not_called()


class ConfigTests(unittest.TestCase):
    def test_defaults_are_allowed_and_open(self):
        for task, name in config.DEFAULT_MODELS.items():
            self.assertIn(name, config.MODEL_LICENCES, task)
        for name, licence in config.MODEL_LICENCES.items():
            self.assertRegex(licence, OPEN, name)

    def test_no_cloud_backends(self):
        self.assertEqual([n for n in dir(backends) if not n.startswith("_") and callable(getattr(backends, n))
                          and n not in ("LLMResponse",)], ["ollama"])


if __name__ == "__main__":
    unittest.main()
