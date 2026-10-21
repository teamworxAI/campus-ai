import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from campus_ai.core.llm import LLMResponse, backends, generate

MESSAGES = [{"role": "user", "content": "Hello"}]


def fake_claude_message(model):
    return SimpleNamespace(
        model=model,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Hi there"),
        ],
        usage=SimpleNamespace(input_tokens=5, output_tokens=7),
        stop_reason="end_turn",
    )


class ClaudeRoutingTests(unittest.TestCase):
    def setUp(self):
        backends._bedrock_client.cache_clear()
        patcher = mock.patch.object(backends, "AnthropicBedrockMantle")
        self.client_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(backends._bedrock_client.cache_clear)
        self.create = self.client_cls.return_value.messages.create
        self.create.side_effect = lambda **kw: fake_claude_message(kw["model"])

    def test_ca_reasoning_uses_canadian_region(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            result = generate(MESSAGES, task="reasoning", region="ca")
        self.client_cls.assert_called_once_with(aws_region="ca-central-1")
        kwargs = self.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "anthropic.claude-opus-5-5")
        self.assertEqual(kwargs["messages"], MESSAGES)
        self.assertNotIn("system", kwargs)
        self.assertEqual(
            result,
            LLMResponse("Hi there", "anthropic.claude-opus-5-5", 5, 7, "end_turn"),
        )

    def test_eu_classification_uses_cheap_model_and_region_override(self):
        env = {"CAMPUS_AI_BEDROCK_REGION_EU": "eu-west-3"}
        with mock.patch.dict("os.environ", env, clear=True):
            generate(MESSAGES, task="classification", region="eu", system="Be brief.")
        self.client_cls.assert_called_once_with(aws_region="eu-west-3")
        kwargs = self.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "anthropic.claude-haiku-4-5")
        self.assertEqual(kwargs["system"], "Be brief.")

    def test_unknown_task_or_region_rejected(self):
        with self.assertRaises(ValueError):
            generate(MESSAGES, task="poetry", region="ca")
        with self.assertRaises(ValueError):
            generate(MESSAGES, task="reasoning", region="us")
        self.create.assert_not_called()


class OllamaRoutingTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(backends.urllib.request, "urlopen")
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        reply = {
            "model": "gemma3:12b",
            "message": {"role": "assistant", "content": "A cat."},
            "prompt_eval_count": 11,
            "eval_count": 3,
            "done_reason": "stop",
        }
        self.urlopen.return_value.__enter__.return_value = io.BytesIO(
            json.dumps(reply).encode()
        )

    def sent_body(self):
        return json.loads(self.urlopen.call_args.args[0].data)

    def test_local_routes_to_ollama(self):
        env = {"OLLAMA_HOST": "http://ollama:11434/"}
        with mock.patch.dict("os.environ", env, clear=True):
            result = generate(MESSAGES, task="reasoning", region="local", system="Sys")
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://ollama:11434/api/chat")
        body = self.sent_body()
        self.assertEqual(body["model"], "gemma3:12b")
        self.assertFalse(body["stream"])
        self.assertEqual(
            body["messages"],
            [{"role": "system", "content": "Sys"}, {"role": "user", "content": "Hello"}],
        )
        self.assertEqual(result, LLMResponse("A cat.", "gemma3:12b", 11, 3, "stop"))

    def test_vision_blocks_converted_to_ollama_images(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": "AAAA"}},
                {"type": "text", "text": "Describe this."},
            ],
        }]
        generate(messages, task="vision", region="local")
        self.assertEqual(
            self.sent_body()["messages"],
            [{"role": "user", "content": "Describe this.", "images": ["AAAA"]}],
        )


if __name__ == "__main__":
    unittest.main()
