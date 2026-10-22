import io
import json
import re
import unittest
from unittest import mock

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

    def sent_body(self):
        return json.loads(self.urlopen.call_args.args[0].data)

    def test_routes_to_ollama_host(self):
        env = {"OLLAMA_HOST": "http://inference-box:11434/"}
        with mock.patch.dict("os.environ", env, clear=True):
            result = generate(MESSAGES, task="reasoning", system="Sys")
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
            generate(MESSAGES, task="classification")
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
            generate(messages, task="vision")
        self.assertEqual(
            self.sent_body()["messages"],
            [{"role": "user", "content": "Describe this.", "images": ["AAAA"]}],
        )

    def test_model_override_must_be_open_licensed(self):
        with mock.patch.dict("os.environ", {"CAMPUS_AI_MODEL_VISION": "qwen3-vl:8b"}, clear=True):
            generate(MESSAGES, task="vision")
        self.assertEqual(self.sent_body()["model"], "qwen3-vl:8b")
        self.urlopen.reset_mock()
        for blocked in ("gemma3:12b", "llama3.2-vision:11b"):
            with self.subTest(model=blocked):
                with mock.patch.dict("os.environ", {"CAMPUS_AI_MODEL_VISION": blocked}, clear=True):
                    with self.assertRaisesRegex(ValueError, "prime directive 1"):
                        generate(MESSAGES, task="vision")
        self.urlopen.assert_not_called()

    def test_unknown_task_rejected(self):
        with self.assertRaises(ValueError):
            generate(MESSAGES, task="poetry")
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
