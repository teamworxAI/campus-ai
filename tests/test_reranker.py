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
        self.seen = []

    def encode(self, text, add_special_tokens=True):
        self.seen.append(text)
        return [self.vocab.setdefault(word, len(self.vocab)) for word in text.split()]

    def convert_tokens_to_ids(self, token):
        return self.vocab[token]

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

    def __call__(self, input_ids, logits_to_keep=0):
        assert logits_to_keep == 1, "only the last token's logits are needed"
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
        reranker = fake_reranker(instruction="Find projects")
        docs = ["a salmon study", "wildfire smoke"]
        reranker.score("salmon rivers", docs, data_class="P")
        tokenizer, (batch,) = reranker._tokenizer, reranker._model.batches
        self.assertEqual(pair_text("i", "q", "d"), "<Instruct>: i\n<Query>: q\n<Document>: d")
        # as the model card builds it: prefix tokens + pair tokens + suffix tokens
        expected = [tokenizer.encode(PREFIX) + tokenizer.encode(pair_text("Find projects", "salmon rivers", doc))
                    + tokenizer.encode(SUFFIX) for doc in docs]
        rows = [[t for t in row.tolist() if t != 2] for row in batch]
        self.assertEqual(sorted(rows, key=len), sorted(expected, key=len))
        suffix = tokenizer.encode(SUFFIX)
        self.assertTrue(all(row.tolist()[-len(suffix):] == suffix for row in batch))  # padded on the left

    def test_long_query_and_documents_are_cut_never_the_frame(self):
        reranker = fake_reranker(max_length=150)
        reranker.score(" ".join(f"q{i}" for i in range(200)), [" ".join(f"d{i}" for i in range(200))], data_class="P")
        tokenizer, ((row,),) = reranker._tokenizer, reranker._model.batches
        words = {v: k for k, v in tokenizer.vocab.items()}
        text = [words[t] for t in row.tolist()]
        self.assertEqual(len(text), 150)  # the document fills what the query leaves
        self.assertEqual(sum(w.startswith("q") and w[1:].isdigit() for w in text), 49)  # a third of 150, less the newline
        self.assertEqual(text[-len(tokenizer.encode(SUFFIX)):], SUFFIX.split())
        self.assertIn("d0", text)

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
        self.assertEqual((reranker._tokenizer.seen, reranker._model.batches), ([], []))
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
