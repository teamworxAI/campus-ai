import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import numpy as np

from campus_ai.core.embed import BACKENDS, embedder as embedder_module, get_embedder, truncate

ROOT = Path(__file__).resolve().parents[1]


def load_bakeoff():
    spec = importlib.util.spec_from_file_location("embed_bakeoff", ROOT / "scripts" / "embed_bakeoff.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeServer:
    """A local OpenAI-compatible /v1/embeddings endpoint that records requests.

    `vector(text)` decides each embedding. Rows come back in reverse order to
    check the client sorts by index.
    """

    def __init__(self, vector):
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests.append((self.path, body))
                data = [{"index": i, "embedding": vector(text)} for i, text in enumerate(body["input"])]
                payload = json.dumps({"data": data[::-1]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TruncateTests(unittest.TestCase):
    def test_keeps_prefix_and_renormalizes(self):
        vectors = np.array([[3.0, 4.0, 12.0], [0.0, 0.0, 1.0]])
        out = truncate(vectors, 2)
        np.testing.assert_allclose(out[0], [0.6, 0.8])
        np.testing.assert_allclose(out[1], [0.0, 0.0])  # zero prefix stays zero, no NaN


class EmbedderTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer(lambda text: [float(len(text))] + [1.0] * 767)
        self.addCleanup(self.server.close)

    def test_gemma_query_prefix_and_matryoshka_dim(self):
        out = get_embedder(base_url=self.server.base_url).embed(["smoke", "salmon rivers"], kind="query", dim=128)
        self.assertEqual(out.shape, (2, 128))
        np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, rtol=1e-6)
        path, body = self.server.requests[0]
        self.assertEqual(path, "/v1/embeddings")
        self.assertEqual(body["model"], "embeddinggemma-2")
        self.assertEqual(
            body["input"], ["task: search result | query: smoke", "task: search result | query: salmon rivers"]
        )
        # Rows are matched to inputs by index, not response order.
        self.assertLess(out[0, 0], out[1, 0])

    def test_document_prefixes(self):
        get_embedder(base_url=self.server.base_url).embed(["a"])
        get_embedder("e5-small", base_url=self.server.base_url).embed(["b"], kind="query")
        get_embedder("e5-small", base_url=self.server.base_url).embed(["c"])
        inputs = [body["input"] for _, body in self.server.requests]
        self.assertEqual(inputs, [["title: none | text: a"], ["query: b"], ["passage: c"]])

    def test_batches_large_inputs(self):
        with mock.patch.object(embedder_module, "BATCH_SIZE", 2):
            out = get_embedder(base_url=self.server.base_url).embed(["a", "b", "c"])
        self.assertEqual(out.shape, (3, 768))
        self.assertEqual([len(body["input"]) for _, body in self.server.requests], [2, 1])

    def test_base_url_from_environment(self):
        with mock.patch.dict("os.environ", {"EMBED_BASE_URL": "http://gpu-box:8000/v1/"}):
            self.assertEqual(get_embedder().base_url, "http://gpu-box:8000/v1")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_embedder().base_url, "http://host.docker.internal:11434/v1")

    def test_rejects_unsupported_dim_modality_and_kind(self):
        embedder = get_embedder(base_url=self.server.base_url)
        with self.assertRaises(ValueError):
            embedder.embed(["a"], dim=100)
        with self.assertRaises(NotImplementedError):
            embedder.embed(["img.png"], modality="image")
        with self.assertRaises(ValueError):
            embedder.embed(["a"], kind="passage")
        with self.assertRaises(ValueError):
            get_embedder("nope")
        self.assertEqual(self.server.requests, [])

    def test_empty_input_skips_server(self):
        out = get_embedder(base_url=self.server.base_url).embed([], dim=256)
        self.assertEqual(out.shape, (0, 256))
        self.assertEqual(self.server.requests, [])
        self.assertEqual(set(BACKENDS), {"embeddinggemma-2", "e5-small"})


class BakeoffTests(unittest.TestCase):
    def test_recall_at_k(self):
        bakeoff = load_bakeoff()
        vocab = ["smoke", "salmon", "saumon", "photo"]
        # Bag-of-words vectors so the ranking is predictable.
        server = FakeServer(lambda text: [float(word in text.lower()) for word in vocab] + [0.01] * 380)
        self.addCleanup(server.close)
        embedder = bakeoff.get_embedder("e5-small", base_url=server.base_url)

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
