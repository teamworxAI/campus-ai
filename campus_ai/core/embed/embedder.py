"""Embed inputs into vectors behind one interface.

Models are served on the host by vLLM or Ollama and shared across projects;
this module only calls their OpenAI-compatible `/v1/embeddings` endpoint at
`EMBED_BASE_URL`. Task prefixes and Matryoshka truncation are applied here,
so results are the same whichever server is used.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Sequence

import numpy as np

MODALITIES = ("text", "image", "audio", "video")
KINDS = ("query", "document")
DEFAULT_BASE_URL = "http://host.docker.internal:11434/v1"  # Ollama on the Docker host
BATCH_SIZE = 64


def truncate(vectors: np.ndarray, dim: int) -> np.ndarray:
    """Keep the first `dim` components (Matryoshka) and re-normalize to unit length."""
    cut = np.asarray(vectors, dtype=np.float32)[:, :dim]
    norms = np.linalg.norm(cut, axis=1, keepdims=True)
    return cut / np.where(norms == 0, 1.0, norms)


class Embedder:
    """A model served behind an OpenAI-compatible embeddings endpoint.

    `model` is the name the server exposes. `dims` lists the vector sizes the
    model was trained to support; the first is the full size. The prefixes
    are the model's text task instructions for queries and documents.
    """

    def __init__(
        self,
        name: str,
        model: str,
        dims: Sequence[int],
        query_prefix: str = "",
        document_prefix: str = "",
        modalities: Sequence[str] = ("text",),
        base_url: str | None = None,
        timeout: float = 120.0,
    ):
        self.name = name
        self.model = model
        self.dims = tuple(dims)
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self.modalities = tuple(modalities)
        self.base_url = (base_url or os.environ.get("EMBED_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    def embed(
        self,
        inputs: Sequence[str],
        modality: str = "text",
        kind: str = "document",
        dim: int | None = None,
    ) -> np.ndarray:
        """Return one unit-length row per input, with `dim` columns (default: full size)."""
        if modality not in self.modalities:
            raise NotImplementedError(f"{self.name} does not support {modality!r} inputs yet")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        dim = dim or self.dims[0]
        if dim not in self.dims:
            raise ValueError(f"{self.name} supports dims {self.dims}, got {dim}")
        if not inputs:
            return np.zeros((0, dim), dtype=np.float32)
        prefix = self.query_prefix if kind == "query" else self.document_prefix
        texts = [prefix + text for text in inputs]
        rows = []
        for start in range(0, len(texts), BATCH_SIZE):
            rows += self._post(texts[start : start + BATCH_SIZE])
        return truncate(np.array(rows), dim)

    def _post(self, texts: list[str]) -> list[list[float]]:
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.model, "input": texts}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)["data"]
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]


def embeddinggemma2(base_url: str | None = None) -> Embedder:
    """Google EmbeddingGemma 2 (Apache 2.0), the default backend (decision D7).

    Prefixes are the model's `SearchQuery` / `Document` prompts. Image, audio
    and video wait on server support (vLLM PR #60254; Ollama lists images).
    """
    return Embedder(
        name="embeddinggemma-2",
        model="embeddinggemma-2",
        dims=(768, 512, 256, 128),
        query_prefix="task: search result | query: ",
        document_prefix="title: none | text: ",
        base_url=base_url,
    )


def e5_small(base_url: str | None = None) -> Embedder:
    """Text-only multilingual baseline for the D7 bake-off (MIT licence, 384 dims)."""
    return Embedder(
        name="e5-small",
        model="e5-small",
        dims=(384,),
        query_prefix="query: ",
        document_prefix="passage: ",
        base_url=base_url,
    )


BACKENDS = {"embeddinggemma-2": embeddinggemma2, "e5-small": e5_small}
DEFAULT_BACKEND = "embeddinggemma-2"


def get_embedder(name: str = DEFAULT_BACKEND, base_url: str | None = None) -> Embedder:
    if name not in BACKENDS:
        raise ValueError(f"unknown embedder {name!r}; choose from {sorted(BACKENDS)}")
    return BACKENDS[name](base_url=base_url)
