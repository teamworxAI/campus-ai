import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from campus_ai.core.llm import LLMResponse, config

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location("smoke_test", ROOT / "scripts" / "smoke_test.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load_script()

MODELS = sorted({config.model(task) for task in config.TASKS})
OLLAMA = {
    "/api/version": {"version": "0.40.8"},
    "/api/tags": {"models": [{"name": m} for m in MODELS]},
    "/api/ps": {"models": [{"name": MODELS[0], "size": 8 * 1024**3, "size_vram": 6 * 1024**3}]},
}


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fake_urlopen(ollama=OLLAMA, down=()):
    def urlopen(url, timeout):
        if any(url.startswith(prefix) for prefix in down):
            raise OSError("connection refused")
        for path, body in ollama.items():
            if url.endswith(path):
                return FakeResponse(json.dumps(body).encode())
        return FakeResponse(b"<html></html>")
    return urlopen


def reply(messages, task, data_class):
    assert data_class == "P", data_class  # the smoke prompt is public
    return LLMResponse(text="OK\n", model=config.model(task), input_tokens=12, output_tokens=2)


class SmokeTestTests(unittest.TestCase):
    def run_checks(self, urlopen=None, connect=OSError("unreachable"), generate=reply):
        with mock.patch.object(smoke.urllib.request, "urlopen", urlopen or fake_urlopen()), \
             mock.patch.object(smoke.socket, "create_connection", side_effect=connect), \
             mock.patch.object(smoke, "generate", autospec=True, side_effect=generate), \
             mock.patch.dict("os.environ", {"OLLAMA_HOST": "http://ollama:11434"}):
            return {r["check"]: r for r in smoke.run()}

    def test_all_pass(self):
        results = self.run_checks()
        self.assertTrue(all(r["ok"] for r in results.values()), results)
        self.assertEqual(set(results), {"neo4j", "api", "web", "offline", "ollama", "loaded"}
                         | {f"router:{t}" for t in config.TASKS})
        self.assertIn("0.40.8", results["ollama"]["detail"])
        self.assertIn("'OK'", results["router:classification"]["detail"])
        self.assertIn("6.0 GiB on GPU", results["loaded"]["detail"])
        for r in results.values():
            self.assertIsInstance(r["seconds"], float)

    def test_service_down_fails_only_that_check(self):
        results = self.run_checks(urlopen=fake_urlopen(down=("http://api:8000",)))
        self.assertFalse(results["api"]["ok"])
        self.assertIn("connection refused", results["api"]["detail"])
        self.assertTrue(results["web"]["ok"])

    def test_internet_reachable_fails(self):
        results = self.run_checks(connect=None)  # create_connection returns a mock socket
        self.assertFalse(results["offline"]["ok"])
        self.assertIn("not offline", results["offline"]["detail"])

    def test_missing_model_fails(self):
        ollama = dict(OLLAMA, **{"/api/tags": {"models": [{"name": MODELS[0]}]}})
        results = self.run_checks(urlopen=fake_urlopen(ollama=ollama))
        self.assertFalse(results["ollama"]["ok"])
        self.assertIn("fetch-ollama", results["ollama"]["detail"])

    def test_router_error_fails(self):
        results = self.run_checks(generate=TimeoutError("timed out"))
        self.assertFalse(results["router:reasoning"]["ok"])
        self.assertIn("TimeoutError", results["router:reasoning"]["detail"])

    def test_main_writes_report_and_exit_code(self):
        results = [{"check": "api", "ok": True, "seconds": 0.1, "detail": "HTTP 200"},
                   {"check": "router:vision", "ok": False, "seconds": 2.5, "detail": "a | b"}]
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(smoke, "REPORTS", Path(tmp) / "evals" / "smoke"), \
             mock.patch.object(smoke, "run", return_value=results), \
             mock.patch("builtins.print"):
            code = smoke.main(["--label", "demo laptop"])
            (path,) = (Path(tmp) / "evals" / "smoke").glob("*.md")
            text = path.read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertTrue(path.name.endswith("-demo-laptop.md"))
        self.assertIn("1/2 checks passed", text)
        self.assertIn("| router:vision | FAIL | 2.5 | a \\| b |", text)


class ComposeTests(unittest.TestCase):
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    def service(self, name):
        match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S)", self.compose, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_fetch_ollama_pulls_the_default_models(self):
        args = re.search(r"command: \[(.*)\]", self.service("fetch-ollama")).group(1)
        models = set(re.findall(r'"([^"]+)"', args))
        self.assertEqual(models, set(config.DEFAULT_MODELS.values()))
        self.assertTrue(models <= set(config.MODEL_LICENCES))

    def test_ollama_is_offline_and_read_only(self):
        ollama = self.service("ollama")
        self.assertIn("networks: [graph]", ollama)
        self.assertIn(":/models:ro", ollama)
        self.assertIn('OLLAMA_NO_CLOUD: "1"', ollama)
        self.assertRegex(self.compose, r"graph:\n\s+internal: true")
        self.assertRegex(ollama, r"image: ollama/ollama:\d+\.\d+\.\d+\n")

    def test_router_callers_get_ollama_host(self):
        for name in ("embed", "api", "smoke"):
            self.assertIn("*llm-env", self.service(name), name)


if __name__ == "__main__":
    unittest.main()
