"""LLM router: the single entry point product code uses to call a model.

Every call goes to a local open-weight model on Ollama (prime directive 2).
"""

from . import backends, config
from .response import LLMResponse


def generate(messages, task, system=None) -> LLMResponse:
    """Run `messages` (text and base64 image blocks) on the local model for `task`."""
    if task not in config.TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {config.TASKS}")
    return backends.ollama(
        messages, config.model(task), config.MAX_TOKENS[task], config.ollama_host(), system
    )
