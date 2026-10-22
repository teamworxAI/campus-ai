"""The compose stack wires the LLM router to an offline Ollama service (P9).

Checked from the compose files' text (no PyYAML in the base image): the
`ollama` service serves local weights read-only on the internal network, only
`fetch-ollama` can download, and every service that may call the router gets
the router's settings.
"""

import re
import unittest
from pathlib import Path

from campus_ai.core.llm import config

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8").replace("\r\n", "\n")


def service(name: str) -> str:
    """The text of one service block in compose.yaml."""
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", COMPOSE, re.MULTILINE | re.DOTALL)
    assert match, f"no service {name!r} in compose.yaml"
    return match.group(1)


class OllamaServiceTests(unittest.TestCase):
    def test_serves_local_weights_offline(self):
        ollama = service("ollama")
        self.assertIn("networks: [graph]", ollama)  # internal network: no way out
        self.assertNotIn("profiles", ollama)
        self.assertRegex(ollama, r"\$\{MODELS_DIR:-\./models\}/ollama:/root/\.ollama/models:ro")
        self.assertIn("healthcheck", ollama)
        self.assertIn('OLLAMA_NO_CLOUD: "true"', ollama)
        self.assertIn("internal: true", COMPOSE[COMPOSE.index("networks:\n  graph:"):])

    def test_fetch_is_the_only_networked_ollama(self):
        fetch = service("fetch-ollama")
        self.assertIn("profiles: [fetch]", fetch)
        self.assertNotIn("networks", fetch)  # default network: the one step that downloads
        self.assertRegex(fetch, r"\$\{MODELS_DIR:-\./models\}/ollama:/root/\.ollama/models\n")
        images = set(re.findall(r"image: (ollama/ollama:\S+)", COMPOSE))
        self.assertEqual(len(images), 1, "pin one Ollama version for both services")
        self.assertNotIn("latest", images.pop())

    def test_default_pull_is_the_router_defaults(self):
        pulled = re.search(r"\$\{OLLAMA_PULL:-([^}]+)\}", service("fetch-ollama")).group(1).split()
        self.assertEqual(sorted(pulled), sorted(set(config.DEFAULT_MODELS.values())))
        for model in pulled:
            self.assertIn(model, config.MODEL_LICENCES)

    def test_router_env_reaches_every_caller(self):
        self.assertIn("OLLAMA_HOST: ${OLLAMA_URL:-http://ollama:11434}", COMPOSE)
        for task in config.TASKS:
            key = f"CAMPUS_AI_MODEL_{task.upper()}"
            self.assertIn(f"{key}: ${{{key}:-}}", COMPOSE)
        for name in ("test", "embed", "api"):
            with self.subTest(service=name):
                self.assertIn("*router-env", service(name))
                self.assertIn("networks: [graph]", service(name))

    def test_gpu_overlay_covers_ollama(self):
        gpu = (ROOT / "compose.gpu.yaml").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("ollama:\n    gpus: all", gpu)


if __name__ == "__main__":
    unittest.main()
