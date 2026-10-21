"""Routing table for the LLM router: the one place models and regions are set.

Claude model availability per Bedrock region must be confirmed (plan D2).
"""

import os

TASKS = ("reasoning", "vision", "classification")
REGIONS = ("ca", "eu", "local")

# Claude on AWS Bedrock (Mantle endpoint), per task.
CLAUDE_MODELS = {
    "reasoning": "anthropic.claude-opus-5-5",
    "vision": "anthropic.claude-opus-5-5",
    "classification": "anthropic.claude-haiku-4-5",
}

# Ollama models for the local fallback, per task.
OLLAMA_MODELS = {
    "reasoning": "gemma3:12b",
    "vision": "gemma3:12b",
    "classification": "gemma3:4b",
}

MAX_TOKENS = {
    "reasoning": 16000,
    "vision": 16000,
    "classification": 1024,
}


def bedrock_region(region: str) -> str:
    """AWS region that keeps `ca` or `eu` data in its jurisdiction."""
    if region == "ca":
        return os.environ.get("CAMPUS_AI_BEDROCK_REGION_CA", "ca-central-1")
    if region == "eu":
        return os.environ.get("CAMPUS_AI_BEDROCK_REGION_EU", "eu-central-1")
    raise ValueError(f"No Bedrock region for {region!r}")


def ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")
