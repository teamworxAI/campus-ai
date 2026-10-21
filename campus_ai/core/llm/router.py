"""LLM router: the single entry point product code uses to call a model."""

from . import backends, config
from .response import LLMResponse


def generate(messages, task, region, system=None) -> LLMResponse:
    """Run `messages` (Anthropic message format) on the model for `task`,
    keeping data in `region`: `ca` and `eu` use Claude on in-region Bedrock,
    `local` uses Ollama."""
    if task not in config.TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {config.TASKS}")
    if region not in config.REGIONS:
        raise ValueError(f"Unknown region {region!r}; expected one of {config.REGIONS}")
    max_tokens = config.MAX_TOKENS[task]
    if region == "local":
        return backends.ollama(
            messages, config.OLLAMA_MODELS[task], max_tokens, config.ollama_host(), system
        )
    return backends.claude(
        messages, config.CLAUDE_MODELS[task], max_tokens, config.bedrock_region(region), system
    )
