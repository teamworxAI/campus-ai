"""Model backend: Ollama, local or on the team's inference box. Only the router calls this.

Prime directive 2: there are no cloud backends.
"""

import json
import urllib.error
import urllib.request

from .response import LLMResponse


def _to_ollama(message: dict) -> dict:
    """Convert a message with text and base64 image blocks to Ollama's format."""
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
    try:
        with urllib.request.urlopen(request, timeout=600) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(
            f"Ollama at {host} rejected the request ({e.code}): {detail}. If the model is missing, "
            "download it once with `docker compose run --rm fetch-ollama <model>`."
        ) from e
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"No Ollama at {host} ({e.reason}). Start it with `docker compose up -d ollama`, "
            "or set OLLAMA_URL in .env to the team's inference box."
        ) from e
    return LLMResponse(
        text=data["message"]["content"],
        model=data["model"],
        input_tokens=data.get("prompt_eval_count", 0),
        output_tokens=data.get("eval_count", 0),
        stop_reason=data.get("done_reason"),
    )
