"""Routing table for the LLM router: the one place models are set.

Prime directive 2 (AGENTS.md): every model runs locally, served by Ollama on
hardware we control: the developer's machine, or the team's inference box
(`OLLAMA_HOST`). No cloud model APIs.

Prime directive 1: every model's weights must be under an OSI-approved
licence. A model can only be used if it is listed in MODEL_LICENCES, with the
licence its Ollama registry entry declares; the router refuses anything else.
"""

import os

TASKS = ("reasoning", "vision", "classification")

# Default model per task; override with CAMPUS_AI_MODEL_<TASK> (e.g. CAMPUS_AI_MODEL_VISION).
DEFAULT_MODELS = {
    "reasoning": "gemma4:12b",
    "vision": "gemma4:12b",
    "classification": "gemma4:e4b",
}

# Ollama models allowed, with the licence of their weights (checked in each
# model's registry licence layer, Oct 2026). Gemma 3 is not here: its weights
# use the "Gemma Terms of Use", which is not an open-source licence.
MODEL_LICENCES = {
    "gemma4:e2b": "Apache-2.0",
    "gemma4:e4b": "Apache-2.0",
    "gemma4:12b": "Apache-2.0",
    "qwen3:4b": "Apache-2.0",
    "qwen3:8b": "Apache-2.0",
    "qwen3-vl:4b": "Apache-2.0",
    "qwen3-vl:8b": "Apache-2.0",
    "granite3.3:8b": "Apache-2.0",
    "mistral-small3.2:24b": "Apache-2.0",
    "olmo2:7b": "Apache-2.0",
}

MAX_TOKENS = {
    "reasoning": 16000,
    "vision": 16000,
    "classification": 1024,
}


def model(task: str) -> str:
    """The configured model for `task`; must be in MODEL_LICENCES."""
    name = os.environ.get(f"CAMPUS_AI_MODEL_{task.upper()}") or DEFAULT_MODELS[task]
    if name not in MODEL_LICENCES:
        raise ValueError(
            f"Model {name!r} is not in MODEL_LICENCES. Only models with open-source weights "
            "may be used (prime directive 1): check its licence and add it there first."
        )
    return name


def ollama_host() -> str:
    """Ollama on this machine by default; the team's inference box in shared environments."""
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")
