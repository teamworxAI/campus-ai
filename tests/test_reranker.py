import importlib.util
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from campus_ai.core.data_classes import RestrictedDataError
from campus_ai.core.embed.reranker import DEFAULT_RERANKER, PREFIX, RERANKERS, SUFFIX, Reranker, pair_text, yes_probability


class Batch(dict):
    def to(self, device):
        return self


class FakeTokenizer:
    """Word-level ids; "no" and "yes" are 0 and 1, padding is 2 (on the left, as the model needs)."""

    def __init__(self):
        self.vocab = {"no": 0, "yes": 1, "<pad>": 2}
        self.texts = []
        self.max_length = None

    def encode(self, text, add_special_tokens=True):
        return [self.vocab.setdefault(word, len(self.vocab)) for word in text.split()]

    def convert_tokens_to_ids(self, token):
        return self.vocab[token]

    def __call__(self, texts, add_special_tokens=True, truncation=False, max_length=None):
        self.texts, self.max_length = list(texts), max_length
        return {"input_ids": [self.encode(text)[:max_length] for text in texts]}

    def pad(self, encoded, padding=True, return_tensors=None):
        rows = encoded["input_ids"]
        width = max(len(row) for row in rows)
        return Batch(input_ids=np.array([[2] * (width - len(row)) + row for row in rows]))


class FakeModel:
    """Last-token logits: "no" 0, "yes" = how often "salmon" is in the sequence (minus 1)."""

    device = "cpu"

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.batches = []

    def __call__(self, input_ids):
        self.batches.append(input_ids)
        salmon = self.tokenizer.vocab.get("salmon", -1)
        logits = np.zeros((*input_ids.shape, len(self.tokenizer.vocab)), dtype=np.float32)
        logits[:, -1, 1] = (input_ids == salmon).sum(axis=1) - 1.0
        return SimpleNamespace(logits=logits)


def fake_reranker(**kwargs):
    tokenizer = FakeTokenizer()
    return Reranker(model=FakeModel(tokenizer), tokenizer=tokenizer, **kwargs)


class RerankerTests(unittest.TestCase):
    def test_default_is_the_small_model(self):
        self.assertEqual(RERANKERS[DEFAULT_RERANKER], "Qwen/Qwen3-Reranker-0.6B")
        self.assertIn("Qwen/Qwen3-Reranker-4B", RERANKERS.values())
        with self.assertRaises(ValueError):
            Reranker("bge-reranker")

    def test_prompt_format_follows_the_model_card(self):
        reranker = fake_reranker(instruction="Find projects", max_length=400)
        reranker.score("salmon rivers", ["a salmon study", "wildfire smoke"], data_class="P")
        tokenizer, model = reranker._tokenizer, reranker._model
        self.assertEqual(tokenizer.texts[0], "<Instruct>: Find projects\n<Query>: salmon rivers\n<Document>: a salmon study")
        self.assertEqual(pair_text("i", "q", "d"), "<Instruct>: i\n<Query>: q\n<Document>: d")
        prefix, suffix = tokenizer.encode(PREFIX), tokenizer.encode(SUFFIX)
        self.assertEqual(tokenizer.max_length, 400 - len(prefix) - len(suffix))  # the document is cut, never the frame
        for row in model.batches[0]:
            real = [t for t in row.tolist() if t != 2]
            self.assertEqual(real[:len(prefix)], prefix)
            self.assertEqual(real[-len(suffix):], suffix)
            self.assertEqual(row.tolist()[-len(suffix):], suffix)  # padded on the left

    def test_scores_are_yes_probabilities_in_input_order(self):
        reranker = fake_reranker(batch_size=2)
        docs = ["salmon salmon salmon in long rivers of the coast", "wildfire", "salmon"]
        scores = reranker.score("salmon", docs, data_class="P")
        # yes logits: 3, 0, 1 (query adds one "salmon", the fake subtracts one)
        np.testing.assert_allclose(scores, yes_probability(np.array([[0, 3], [0, 0], [0, 1]])))
        self.assertEqual(len(reranker._model.batches), 2)
        self.assertAlmostEqual(float(yes_probability(np.array([[0.0, 0.0]]))[0]), 0.5)
        self.assertAlmostEqual(float(yes_probability(np.array([[2.0, -1.0]]))[0]), 1 / (1 + np.exp(3)))

    def test_restricted_refused_before_the_model(self):
        reranker = fake_reranker()
        with self.assertRaises(RestrictedDataError):
            reranker.score("q", ["an access-limited item"], data_class="R")
        self.assertEqual((reranker._tokenizer.texts, reranker._model.batches), ([], []))
        with self.assertRaises(TypeError):
            reranker.score("q", ["no class declared"])

    def test_empty_documents_skip_the_model(self):
        reranker = Reranker()
        self.assertEqual(reranker.score("q", [], data_class="P"), [])
        self.assertIsNone(reranker._model)

    @unittest.skipUnless(importlib.util.find_spec("transformers"), "needs transformers: run in the embed image")
    def test_loads_only_from_local_models_dir(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"MODELS_DIR": tmp}):
            with self.assertRaisesRegex(FileNotFoundError, "fetch_models"):
                Reranker().score("q", ["d"], data_class="P")


if __name__ == "__main__":
    unittest.main()
