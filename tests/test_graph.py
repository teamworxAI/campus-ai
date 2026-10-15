import importlib.util
import os
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import numpy as np

from campus_ai.core.embed import get_embedder
from campus_ai.core.graph import GraphStore, HybridRetriever, Link, Node
from campus_ai.core.graph.retriever import fulltext_query, fuse
from campus_ai.core.graph.store import name

ROOT = Path(__file__).resolve().parents[1]


class Record(dict):
    def data(self):
        return dict(self)


class FakeDriver:
    """Records each query; `answer(query, params)` returns the rows for it."""

    def __init__(self, answer=lambda query, params: []):
        self.calls = []
        self.answer = answer

    def execute_query(self, query, params, database_=None):
        self.calls.append((query, params))
        return [Record(row) for row in self.answer(query, params)], None, None


def bag_of_words_model():
    """Deterministic stand-in for a 768-d model: hashed word counts in the first 128 dims."""

    def encode(inputs, **kwargs):
        out = np.zeros((len(inputs), 768), dtype=np.float32)
        for row, text in enumerate(inputs):
            for word in str(text).lower().split():
                out[row, zlib.crc32(word.encode()) % 128] += 1
            out[row, 767] = 0.01  # never all zero
        return out

    model = mock.Mock()
    model.encode.side_effect = encode
    return model


def gemma():
    return get_embedder("embeddinggemma-2", model=bag_of_words_model())


class HelperTests(unittest.TestCase):
    def test_name_rejects_injection(self):
        self.assertEqual(name("Researcher"), "Researcher")
        for bad in ("Item) DETACH DELETE (n", "a-b", "", "1x"):
            with self.assertRaises(ValueError):
                name(bad)

    def test_fulltext_query_strips_lucene_syntax(self):
        self.assertEqual(fulltext_query('salmon AND "ocean" (temp*) OR fr:été'), "salmon ocean temp fr été")

    def test_fulltext_query_drops_function_words(self):
        self.assertEqual(fulltext_query("incendies de forêt et santé"), "incendies forêt santé")
        self.assertEqual(fulltext_query("Photographies d'archives of the BC coast"), "photographies archives bc coast")
        self.assertEqual(fulltext_query("de la"), "")

    def test_fuse_rewards_agreement(self):
        scores = fuse([["a", "b", "c"], ["b"]])
        self.assertEqual(max(scores, key=scores.get), "b")
        self.assertAlmostEqual(scores["a"], 1 / 61)


class StoreTests(unittest.TestCase):
    def test_upsert_embeds_once_per_group_and_writes_both_sizes(self):
        driver = FakeDriver()
        embedder = gemma()
        store = GraphStore(driver, embedder)
        store.upsert(
            [
                Node("r1", "Researcher", "salmon ecology"),
                Node("r2", "Researcher", "wildfire smoke"),
                Node("i1", "Item", "a photo", "image", "/media/p.jpg"),
            ]
        )
        self.assertEqual(len(driver.calls), 2)  # (Researcher, text) and (Item, image)
        query, params = driver.calls[0]
        self.assertIn("SET n:Researcher", query)
        row = params["rows"][0]
        self.assertEqual((len(row["fast"]), len(row["full"])), (128, 768))
        self.assertIsNone(row["file"])
        self.assertEqual(driver.calls[1][1]["rows"][0]["file"], "/media/p.jpg")
        self.assertAlmostEqual(float(np.linalg.norm(row["fast"])), 1.0, places=5)
        self.assertEqual(embedder._model.encode.call_args_list[0].args[0], ["salmon ecology", "wildfire smoke"])
        self.assertEqual(driver.calls[1][1]["rows"][0]["text"], "a photo")

    def test_link_groups_by_type(self):
        driver = FakeDriver()
        GraphStore(driver, gemma()).link([Link("a", "IN", "c"), Link("b", "IN", "c"), Link("a", "AUTHORED", "p")])
        self.assertEqual(len(driver.calls), 2)
        self.assertIn("MERGE (a)-[r:IN]->(b)", driver.calls[0][0])
        self.assertEqual(len(driver.calls[0][1]["rows"]), 2)

    def test_ensure_schema_refuses_other_vector_size(self):
        options = {"indexConfig": {"vector.dimensions": 384}}
        driver = FakeDriver(lambda query, params: [{"options": options, "properties": ["vec_fast", "kind"]}] if "SHOW" in query else [])
        with self.assertRaisesRegex(RuntimeError, "rebuild the graph"):
            GraphStore(driver, gemma()).ensure_schema()

    def test_ensure_schema_creates_indexes_for_fast_size(self):
        driver = FakeDriver()
        GraphStore(driver, gemma()).ensure_schema()
        vector = next(params for query, params in driver.calls if "VECTOR INDEX" in query and "CREATE" in query)
        self.assertEqual(vector["size"], 128)
        self.assertTrue(any("WITH [n.kind]" in query for query, _ in driver.calls))
        self.assertTrue(any("FULLTEXT INDEX" in query for query, _ in driver.calls))

    def test_ensure_schema_adds_kind_to_older_graphs(self):
        options = {"indexConfig": {"vector.dimensions": 128}}
        driver = FakeDriver(lambda query, params: [{"options": options, "properties": ["vec_fast"]}] if "SHOW" in query else [])
        GraphStore(driver, gemma()).ensure_schema()
        queries = [query for query, _ in driver.calls]
        self.assertTrue(any("SET n.kind" in query for query in queries))
        self.assertLess(queries.index(f"DROP INDEX entity_vec"), next(i for i, q in enumerate(queries) if "CREATE VECTOR" in q))


class RetrieverTests(unittest.TestCase):
    def test_reranks_on_full_vectors_fuses_fulltext_and_expands(self):
        embedder = gemma()
        query_vector = embedder.embed(["salmon ocean"], kind="query")[0]
        close, far = query_vector.tolist(), (-query_vector).tolist()

        def answer(query, params):
            if "VECTOR INDEX" in query:  # fast index ranks the far node first
                return [
                    {"id": "far", "labels": ["Entity", "Item"], "text": "far", "vec": far, "score": 0.9},
                    {"id": "close", "labels": ["Entity", "Item"], "text": "close", "vec": close, "score": 0.8},
                ]
            if "fulltext.queryNodes" in query:
                return [{"id": "word", "labels": ["Entity", "Item"], "text": "salmon", "vec": far, "score": 3.0}]
            if "COLLECT" in query:
                return [{"id": "close", "neighbors": [{"type": "IN", "outgoing": True, "id": "c1"}]}]
            return []

        driver = FakeDriver(answer)
        hits = HybridRetriever(driver, embedder).search("salmon ocean", k=2, labels=["Item"])
        # "word" is in both rankings so fusion puts it first; the full-size rerank lifts "close" above "far".
        self.assertEqual([hit.id for hit in hits], ["word", "close"])
        self.assertEqual([hit.found_by for hit in hits], [["words"], ["meaning"]])
        self.assertEqual(hits[1].neighbors[0]["id"], "c1")
        self.assertEqual(driver.calls[0][1]["labels"], ["Item"])
        self.assertEqual(len(driver.calls[0][1]["vector"]), 128)

    def test_media_query_skips_fulltext(self):
        driver = FakeDriver()
        embedder = gemma()
        with mock.patch("campus_ai.core.embed.embedder.prepare", side_effect=lambda value, modality: value):
            self.assertEqual(HybridRetriever(driver, embedder).search("/q.jpg", modality="image"), [])
        self.assertFalse(any("fulltext" in query for query, _ in driver.calls))


class ScriptTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("graph_search", ROOT / "scripts" / "graph_search.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_load_items_links_and_queries(self):
        path = ROOT / "evals" / "embed" / "sample_bakeoff.jsonl"
        nodes, links, queries = self.module.load(path)
        self.assertEqual((len(nodes), len(links), len(queries)), (6, 0, 5))
        self.assertTrue(all(node.label == "Item" and node.text for node in nodes))

    def test_media_text_is_caption_not_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            path.write_text('{"id": "p", "modality": "image", "content": "red.png"}\n', encoding="utf-8")
            (node,), _, _ = self.module.load(path)
        self.assertEqual((node.text, node.content), ("", str(Path(tmp) / "red.png")))


@unittest.skipUnless(os.environ.get("NEO4J_URI"), "needs Neo4j: run in the embed service")
class Neo4jTests(unittest.TestCase):
    """Real Neo4j with a stand-in embedder; writes ids prefixed test: and deletes them after."""

    def setUp(self):
        from campus_ai.core.graph import connect

        self.driver = connect()
        self.embedder = gemma()
        self.store = GraphStore(self.driver, self.embedder)
        self.store.ensure_schema()
        self.addCleanup(self.driver.close)
        self.addCleanup(self.driver.execute_query, "MATCH (n:Entity) WHERE n.id STARTS WITH 'test:' DETACH DELETE n")

    def test_index_search_and_expand(self):
        self.store.upsert(
            [
                Node("test:salmon", "TestItem", "salmon populations and ocean temperature"),
                Node("test:fire", "TestItem", "wildfire smoke and respiratory health"),
                Node("test:coll", "TestCollection", "North Pacific fisheries collection"),
            ]
        )
        self.store.link([Link("test:salmon", "IN", "test:coll")])
        self.driver.execute_query("CALL db.awaitIndexes(60)")
        retriever = HybridRetriever(self.driver, self.embedder)
        hits = retriever.search("ocean salmon", k=2, labels=["TestItem"])
        self.assertEqual(hits[0].id, "test:salmon")
        self.assertEqual(hits[0].neighbors, [
            {"type": "IN", "outgoing": True, "id": "test:coll", "labels": ["Entity", "TestCollection"],
             "text": "North Pacific fisheries collection"}
        ])
        self.assertTrue(all("TestItem" in hit.labels for hit in hits))

    def test_rare_label_is_found_past_many_closer_nodes(self):
        crowd = [Node(f"test:item{i}", "TestItem", f"ocean salmon note {i}") for i in range(60)]
        self.store.upsert(crowd + [Node("test:pic", "TestPicture", "harbour photograph")])
        self.driver.execute_query("CALL db.awaitIndexes(60)")
        hits = HybridRetriever(self.driver, self.embedder).search("ocean salmon", k=3, labels=["TestPicture"])
        self.assertEqual([hit.id for hit in hits], ["test:pic"])


if __name__ == "__main__":
    unittest.main()
