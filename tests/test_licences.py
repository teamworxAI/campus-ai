"""Licence guard (P8): prime directive 1, open source only, no paid licences.

Fails when anything in the stack is not under an OSI-approved open-source
licence: an installed Python package, a Docker image in compose.yaml or the
Dockerfile, or a model the embedder can load. AGPL always fails. The only
named exceptions (AGENTS.md) are free GPU vendor runtimes, listed below.
Docker Desktop, the other exception, is a developer tool and not in the stack.

Runs in both images: `test` (base packages) and `embed` (adds PyTorch, CUDA).
"""

import importlib.metadata
import re
import unittest
from pathlib import Path

from campus_ai.core.embed import BACKENDS

ROOT = Path(__file__).resolve().parents[1]

# Words that identify an OSI-approved licence in package metadata (SPDX
# expressions, trove classifiers or free-text License fields).
OPEN = re.compile(
    r"\b(MIT|MIT-CMU|BSD|0BSD|Apache|ISC|PSF|Python|CNRI-Python|MPL|Mozilla|LGPL|GPL|Zlib|"
    r"CC0|BSL-1\.0|LLVM-exception|Unlicense|Public Domain)\b",
    re.IGNORECASE,
)
# Closed or network-copyleft terms that always fail, even next to an open term.
FORBIDDEN = re.compile(r"proprietary|LicenseRef-|commercial|\bAGPL|Affero|SSPL|BUSL|Elastic", re.IGNORECASE)

# Named exception (AGENTS.md): free GPU vendor runtimes, optional; the CPU path works without them.
GPU_RUNTIME = re.compile(r"^(nvidia-.+|cuda-toolkit)$")

# Docker images, by repository name: SPDX licence of the software they run.
IMAGES = {
    "python": "PSF-2.0",  # python:*-slim, Debian base
    "neo4j": "GPL-3.0-only",  # Community edition only; Enterprise is commercial
    "nginx": "BSD-2-Clause",
}
# Model weights, by Hugging Face id: licence from the model card.
MODELS = {
    "google/embeddinggemma-2": "Apache-2.0",
    "intfloat/multilingual-e5-small": "MIT",
}


def licence_text(dist: importlib.metadata.Distribution) -> str:
    """What the package declares as its licence: SPDX expression, trove classifiers and
    the first line of the free-text License field. Not the rest of that field, which
    often holds full licence texts of bundled code (wording like "commercial use" there
    is not a licence declaration)."""
    md = dist.metadata
    classifiers = [c for c in (md.get_all("Classifier") or []) if c.startswith("License ::")]
    first_line = (md.get("License") or "").strip().split("\n")[0][:200]
    return " | ".join(filter(None, [md.get("License-Expression"), *classifiers, first_line]))


def is_open(text: str) -> bool:
    return bool(OPEN.search(text)) and not FORBIDDEN.search(text)


class LicenceGuardTests(unittest.TestCase):
    def test_classifier(self):
        for text in ("MIT", "Apache-2.0 AND Python-2.0", "License :: OSI Approved :: BSD License",
                     "LGPL-2.1-or-later", "MPL-2.0 AND MIT"):
            self.assertTrue(is_open(text), text)
        for text in ("", "AGPL-3.0-only", "GNU Affero General Public License v3",
                     "LicenseRef-NVIDIA-Proprietary", "Other/Proprietary License", "Commercial", "SSPL-1.0"):
            self.assertFalse(is_open(text), text)

    def test_python_packages_are_open_source(self):
        closed = []
        for dist in importlib.metadata.distributions():
            name = dist.metadata["Name"]
            if name == "campus-ai" or GPU_RUNTIME.match(name):
                continue
            text = licence_text(dist)
            if not is_open(text):
                closed.append(f"{name}: {text or 'no licence metadata'}")
        self.assertEqual(closed, [], "not open source (prime directive 1): " + "; ".join(closed))

    def test_campus_ai_is_apache(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('license = "Apache-2.0"', pyproject)
        self.assertIn("Apache License", (ROOT / "LICENSE").read_text(encoding="utf-8"))

    def test_docker_images_are_listed_and_open(self):
        text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        refs = re.findall(r"^\s+image:\s*(\S+)", text, re.MULTILINE)
        refs += re.findall(r"^FROM\s+(\S+)", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE)
        missing = []
        for ref in refs:
            repo = ref.split(":")[0].split("/")[-1]
            if repo == "campus-ai":  # our own images: their contents are checked above
                continue
            if repo not in IMAGES:
                missing.append(ref)
            else:
                self.assertTrue(is_open(IMAGES[repo]), ref)
            self.assertNotIn("enterprise", ref, f"{ref}: use open-source editions only")
        self.assertEqual(missing, [], "add these images and their licences to IMAGES")

    def test_models_are_listed_and_open(self):
        for name, make in BACKENDS.items():
            model_id = make().model_id
            self.assertIn(model_id, MODELS, f"add {model_id} and its weight licence to MODELS")
            self.assertTrue(is_open(MODELS[model_id]), model_id)

    def test_llm_router_models_are_open(self):
        from campus_ai.core.llm import config

        for model, licence in config.MODEL_LICENCES.items():
            self.assertTrue(is_open(licence), f"{model}: {licence}")
        for task, model in config.DEFAULT_MODELS.items():
            self.assertIn(model, config.MODEL_LICENCES, task)

    def test_every_allowed_model_is_in_the_plan_register(self):
        """D10: the router's allow-list and the embedder's models must appear in the
        master plan's model register, so the two can't drift apart."""
        from campus_ai.core.llm import config

        plan = (ROOT / "docs" / "plans" / "master_plan.md").read_text(encoding="utf-8")
        register = plan[plan.index("### D10 model register"):plan.index("Week-1 bake-offs")]
        missing = [m for m in [*config.MODEL_LICENCES, *MODELS] if f"`{m}`" not in register
                   and m.split("/")[-1].lower() not in register.lower()]
        self.assertEqual(missing, [], "add these models to the D10 register in docs/plans/master_plan.md")


if __name__ == "__main__":
    unittest.main()
