"""Embed text, image, audio and video into vectors behind one interface.

Backends load open models through sentence-transformers, in the `embed`
Docker image (`docker compose build embed`). Weights are read only from the
local models directory (`MODELS_DIR`, mounted at /models); nothing is
downloaded at runtime. Fill it once with `scripts/fetch_models.py`.

Inputs per modality: text as strings; images as file paths or PIL images;
audio and video as file paths (decoded with `media`), or already-decoded
{"array": ..., "sampling_rate": ...} audio and {"array": ...} video.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from campus_ai.core.embed import media

MODALITIES = ("text", "image", "audio", "video")
KINDS = ("query", "document")


def truncate(vectors: np.ndarray, dim: int) -> np.ndarray:
    """Keep the first `dim` components (Matryoshka) and re-normalize to unit length."""
    cut = np.asarray(vectors, dtype=np.float32)[:, :dim]
    norms = np.linalg.norm(cut, axis=1, keepdims=True)
    return cut / np.where(norms == 0, 1.0, norms)


class Embedder:
    """A sentence-transformers model with a fixed set of modalities and dims.

    `dims` lists the vector sizes the model was trained to support; the first
    is the full size. `query_kwargs` / `document_kwargs` are passed to
    `encode` for text, to add the model's task prompts.
    """

    def __init__(
        self,
        name: str,
        model_id: str,
        dims: Sequence[int],
        modalities: Sequence[str] = ("text",),
        query_kwargs: dict[str, Any] | None = None,
        document_kwargs: dict[str, Any] | None = None,
        model: Any = None,
    ):
        self.name = name
        self.model_id = model_id
        self.dims = tuple(dims)
        self.modalities = tuple(modalities)
        self.query_kwargs = query_kwargs or {}
        self.document_kwargs = document_kwargs or {}
        self._model = model

    @property
    def model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise ImportError("embedding models run in the embed image: `docker compose build embed`") from error
            import torch

            # bfloat16 on GPUs that support it, float32 elsewhere; never float16 (EmbeddingGemma 2 overflows).
            dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32
            path = model_path(self.model_id)
            if not path.is_dir():
                raise FileNotFoundError(f"{path} not found; fetch it once with scripts/fetch_models.py")
            self._model = SentenceTransformer(str(path), local_files_only=True, model_kwargs={"dtype": dtype})
        return self._model

    def embed(
        self,
        inputs: Sequence[Any],
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
        if modality == "text":
            inputs, kwargs = list(inputs), self.query_kwargs if kind == "query" else self.document_kwargs
        else:
            # Task prompts apply to text only; media goes in bare, keyed by modality.
            inputs, kwargs = [{modality: prepare(value, modality)} for value in inputs], {}
        vectors = self.model.encode(inputs, convert_to_numpy=True, **kwargs)
        return truncate(vectors, dim)


def model_path(model_id: str) -> Path:
    """Local directory for a model: $MODELS_DIR/<org>/<name>, mirroring the Hugging Face ID."""
    return Path(os.environ.get("MODELS_DIR", "/models")) / model_id


def prepare(value: Any, modality: str) -> Any:
    """Decode audio and video file paths; pass everything else through."""
    if isinstance(value, (str, Path)):
        if modality == "audio":
            return {"array": media.load_audio(value), "sampling_rate": media.AUDIO_RATE}
        if modality == "video":
            return media.load_video(value)
        return str(value)
    return value


def embeddinggemma2(model: Any = None) -> Embedder:
    """Google EmbeddingGemma 2 (Apache 2.0), the default backend (decision D7).

    Text, images, audio and video share one 768-d space. Context is 8,192
    tokens per input: about 29 images, 58 video frames (58 s at 1 fps) or
    327 s of audio, so split longer media before embedding.
    """
    return Embedder(
        name="embeddinggemma-2",
        model_id="google/embeddinggemma-2",
        dims=(768, 512, 256, 128),
        modalities=MODALITIES,
        query_kwargs={"prompt_name": "SearchQuery"},
        document_kwargs={"prompt_name": "Document"},
        model=model,
    )


def e5_small(model: Any = None) -> Embedder:
    """Text-only multilingual baseline for the D7 bake-off (MIT licence, 384 dims)."""
    return Embedder(
        name="e5-small",
        model_id="intfloat/multilingual-e5-small",
        dims=(384,),
        query_kwargs={"prompt": "query: "},
        document_kwargs={"prompt": "passage: "},
        model=model,
    )


BACKENDS = {"embeddinggemma-2": embeddinggemma2, "e5-small": e5_small}
DEFAULT_BACKEND = "embeddinggemma-2"


def get_embedder(name: str = DEFAULT_BACKEND, model: Any = None) -> Embedder:
    if name not in BACKENDS:
        raise ValueError(f"unknown embedder {name!r}; choose from {sorted(BACKENDS)}")
    return BACKENDS[name](model=model)
