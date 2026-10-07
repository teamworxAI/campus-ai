import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from campus_ai.core.embed import BACKENDS, get_embedder, truncate

ROOT = Path(__file__).resolve().parents[1]


def load_bakeoff():
    spec = importlib.util.spec_from_file_location("embed_bakeoff", ROOT / "scripts" / "embed_bakeoff.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_model(dim):
    model = mock.Mock()
    model.encode.side_effect = lambda inputs, **kwargs: np.arange(len(inputs) * dim, dtype=np.float32).reshape(
        len(inputs), dim
    ) + 1
    return model


class TruncateTests(unittest.TestCase):
    def test_keeps_prefix_and_renormalizes(self):
        vectors = np.array([[3.0, 4.0, 12.0], [0.0, 0.0, 1.0]])
        out = truncate(vectors, 2)
        np.testing.assert_allclose(out[0], [0.6, 0.8])
        np.testing.assert_allclose(out[1], [0.0, 0.0])  # zero prefix stays zero, no NaN


class EmbedderTests(unittest.TestCase):
    def test_gemma_query_prompt_and_matryoshka_dim(self):
        model = fake_model(768)
        embedder = get_embedder("embeddinggemma-2", model=model)
        out = embedder.embed(["wildfire smoke"], kind="query", dim=128)
        self.assertEqual(out.shape, (1, 128))
        np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, rtol=1e-6)
        model.encode.assert_called_once_with(["wildfire smoke"], convert_to_numpy=True, prompt_name="SearchQuery")

    def test_gemma_document_prompt_full_dim(self):
        model = fake_model(768)
        out = get_embedder(model=model).embed(["a", "b"])
        self.assertEqual(out.shape, (2, 768))
        self.assertEqual(model.encode.call_args.kwargs["prompt_name"], "Document")

    def test_baseline_prompts(self):
        model = fake_model(384)
        embedder = get_embedder("e5-small", model=model)
        embedder.embed(["q"], kind="query")
        self.assertEqual(model.encode.call_args.kwargs["prompt"], "query: ")
        embedder.embed(["d"])
        self.assertEqual(model.encode.call_args.kwargs["prompt"], "passage: ")

    def test_rejects_unsupported_dim_modality_and_kind(self):
        embedder = get_embedder(model=fake_model(768))
        with self.assertRaises(ValueError):
            embedder.embed(["a"], dim=100)
        with self.assertRaises(NotImplementedError):
            embedder.embed(["img.png"], modality="image")
        with self.assertRaises(ValueError):
            embedder.embed(["a"], kind="passage")
        with self.assertRaises(ValueError):
            get_embedder("nope")

    def test_empty_input_skips_model(self):
        model = fake_model(768)
        out = get_embedder(model=model).embed([], dim=256)
        self.assertEqual(out.shape, (0, 256))
        model.encode.assert_not_called()

    def test_model_loads_lazily(self):
        embedder = get_embedder("e5-small")
        self.assertIsNone(embedder._model)
        self.assertEqual(set(BACKENDS), {"embeddinggemma-2", "e5-small"})


class BakeoffTests(unittest.TestCase):
    def test_recall_at_k(self):
        bakeoff = load_bakeoff()
        vocab = ["smoke", "salmon", "saumon", "photo"]

        def encode(inputs, **kwargs):
            # Bag-of-words vectors so the ranking is predictable.
            return np.array([[float(word in text.lower()) for word in vocab] + [0.01] for text in inputs])

        model = mock.Mock()
        model.encode.side_effect = encode
        embedder = bakeoff.get_embedder("e5-small", model=model)
        embedder.dims = (5,)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "set.jsonl"
            path.write_text(
                '{"id": "d1", "content": "wildfire smoke"}\n'
                '{"id": "d2", "content": "saumon and salmon rivers"}\n'
                '{"id": "d3", "modality": "image", "content": "x.png"}\n'
                "\n"
                '{"query": "smoke", "lang": "en", "relevant": ["d1"]}\n'
                '{"query": "saumon", "lang": "fr", "relevant": ["d2"]}\n'
                '{"query": "photo", "lang": "en", "relevant": ["d3"]}\n',
                encoding="utf-8",
            )
            items, queries = bakeoff.load(path)
            self.assertEqual((len(items), len(queries)), (3, 3))
            with mock.patch("builtins.print"):
                scores = bakeoff.recall_at_k(embedder, items, queries, k=1)

        # The image item is skipped (text-only backend), so "photo" never finds d3.
        self.assertEqual(scores, {"all": 2 / 3, "en": 0.5, "fr": 1.0})

    def test_sample_file_is_valid(self):
        bakeoff = load_bakeoff()
        items, queries = bakeoff.load(ROOT / "evals" / "embed" / "sample_bakeoff.jsonl")
        ids = {item["id"] for item in items}
        self.assertTrue(5 <= len(items) <= 10)
        self.assertEqual({q["lang"] for q in queries}, {"en", "fr"})
        for query in queries:
            self.assertTrue(set(query["relevant"]) <= ids)


if __name__ == "__main__":
    unittest.main()
