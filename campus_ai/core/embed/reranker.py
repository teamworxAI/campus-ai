"""Rerank (query, document) pairs with a local cross-encoder (bake-off B2, card R3).

Qwen3-Reranker is a causal language model asked "does this Document meet the
Query?"; the score is the probability of "yes" over "no" at the last token,
in the prompt format its model card prescribes. Weights are read only from
the local models directory (`MODELS_DIR`), like the embedder's; fill it once
with `scripts/fetch_models.py`. Runs in the `embed` image (PyTorch,
transformers): bfloat16 on GPUs that support it, float32 elsewhere.
"""

from __future__ import annotations

import contextlib
from typing import Any, Sequence

import numpy as np

from campus_ai.core import data_classes
from campus_ai.core.embed.embedder import model_path

# Default 0.6B fits the 4 GB demo laptop; 4B is the option for the team's inference box (D10).
RERANKERS = {"qwen3-reranker-0.6b": "Qwen/Qwen3-Reranker-0.6B", "qwen3-reranker-4b": "Qwen/Qwen3-Reranker-4B"}
DEFAULT_RERANKER = "qwen3-reranker-0.6b"
INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"  # the model card's default

PREFIX = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct "
          'provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def pair_text(instruction: str, query: str, document: str) -> str:
    return f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {document}"


def yes_probability(logits: np.ndarray) -> np.ndarray:
    """P(yes) from last-token [no, yes] logits: softmax over the two, as the model card computes it."""
    no, yes = np.asarray(logits, dtype=np.float64).T
    return 1.0 / (1.0 + np.exp(no - yes))


class Reranker:
    """Scores documents against a query, 0..1 (higher is a better match).

    `max_length` caps each prompt in tokens (the document is cut, never the
    prompt's frame); `batch_size` pairs go through the model at once.
    """

    def __init__(self, name: str = DEFAULT_RERANKER, instruction: str = INSTRUCTION, batch_size: int = 8,
                 max_length: int = 1024, model: Any = None, tokenizer: Any = None):
        if name not in RERANKERS:
            raise ValueError(f"unknown reranker {name!r}; choose from {sorted(RERANKERS)}")
        self.name = name
        self.model_id = RERANKERS[name]
        self.instruction = instruction
        self.batch_size = batch_size
        self.max_length = max_length
        self._model = model
        self._tokenizer = tokenizer

    def load(self) -> tuple[Any, Any]:
        if self._model is None:
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
            except ImportError as error:
                raise ImportError("the reranker runs in the embed image: `docker compose build embed`") from error
            path = model_path(self.model_id)
            if not path.is_dir():
                raise FileNotFoundError(f"{path} not found; fetch it once with scripts/fetch_models.py")
            gpu = torch.cuda.is_available()
            dtype = torch.bfloat16 if gpu and torch.cuda.is_bf16_supported() else torch.float32
            self._tokenizer = AutoTokenizer.from_pretrained(str(path), padding_side="left", local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(str(path), dtype=dtype, local_files_only=True)
            self._model = model.to("cuda" if gpu else "cpu").eval()
        return self._model, self._tokenizer

    def score(self, query: str, documents: Sequence[str], *, data_class: str) -> list[float]:
        """One score per document. `data_class` (P, I, S or R) covers query and documents; R is refused."""
        data_classes.check(data_class)
        if not documents:
            return []
        model, tokenizer = self.load()
        prefix = tokenizer.encode(PREFIX, add_special_tokens=False)
        suffix = tokenizer.encode(SUFFIX, add_special_tokens=False)
        no, yes = tokenizer.convert_tokens_to_ids("no"), tokenizer.convert_tokens_to_ids("yes")
        bodies = tokenizer([pair_text(self.instruction, query, doc) for doc in documents], add_special_tokens=False,
                           truncation=True, max_length=self.max_length - len(prefix) - len(suffix))["input_ids"]
        ids = [prefix + body + suffix for body in bodies]
        order = sorted(range(len(ids)), key=lambda i: len(ids[i]))  # similar lengths per batch: less padding
        scores = np.zeros(len(ids))
        try:
            import torch

            no_grad = torch.no_grad()
        except ImportError:  # fake models in the test image
            no_grad = contextlib.nullcontext()
        with no_grad:
            for start in range(0, len(order), self.batch_size):
                chunk = order[start:start + self.batch_size]
                batch = tokenizer.pad({"input_ids": [ids[i] for i in chunk]}, padding=True, return_tensors="pt")
                last = model(**batch.to(model.device)).logits[:, -1, :]  # left padding: the last token is real
                pair = last[:, [no, yes]]
                pair = pair.float().cpu().numpy() if hasattr(pair, "cpu") else np.asarray(pair)
                scores[chunk] = yes_probability(pair)
        return scores.tolist()
