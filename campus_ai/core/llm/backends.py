"""Provider backends. Only the router calls these."""

import json
import urllib.request
from functools import lru_cache

from anthropic import AnthropicBedrockMantle

from .response import LLMResponse


@lru_cache(maxsize=None)
def _bedrock_client(aws_region: str) -> AnthropicBedrockMantle:
    return AnthropicBedrockMantle(aws_region=aws_region)


def claude(messages, model, max_tokens, aws_region, system=None) -> LLMResponse:
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    response = _bedrock_client(aws_region).messages.create(**kwargs)
    text = "".join(b.text for b in response.content if b.type == "text")
    return LLMResponse(
        text=text,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        stop_reason=response.stop_reason,
    )


def _to_ollama(message: dict) -> dict:
    """Convert an Anthropic-style message (text and base64 image blocks)."""
    content = message["content"]
    if isinstance(content, str):
        return {"role": message["role"], "content": content}
    texts, images = [], []
    for block in content:
        if block["type"] == "text":
            texts.append(block["text"])
        elif block["type"] == "image" and block["source"]["type"] == "base64":
            images.append(block["source"]["data"])
        else:
            raise ValueError(f"Unsupported block for Ollama: {block['type']}")
    out = {"role": message["role"], "content": "\n".join(texts)}
    if images:
        out["images"] = images
    return out


def ollama(messages, model, max_tokens, host, system=None) -> LLMResponse:
    chat = [{"role": "system", "content": system}] if system else []
    chat += [_to_ollama(m) for m in messages]
    body = {
        "model": model,
        "messages": chat,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=600) as resp:
        data = json.load(resp)
    return LLMResponse(
        text=data["message"]["content"],
        model=data["model"],
        input_tokens=data.get("prompt_eval_count", 0),
        output_tokens=data.get("eval_count", 0),
        stop_reason=data.get("done_reason"),
    )
