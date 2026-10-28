import importlib.util
import os
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import numpy as np

from campus_ai.core.data_classes import RestrictedDataError
from campus_ai.core.embed import get_embedder
from campus_ai.core.graph import GraphStore, HybridRetriever, Link, Node
from campus_ai.core.graph.retriever import fulltext_query, fuse
from campus_ai.core.graph.store import check_embedder, name

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

    def test_restricted_node_never_embedded_or_written(self):
        driver = FakeDriver()
        embedder = gemma()
        with self.assertRaises(RestrictedDataError):
            GraphStore(driver, embedder).upsert([Node("a1", "Item", "access-limited item", data_class="R")])
        embedder._model.encode.assert_not_called()
        self.assertEqual(driver.calls, [])

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


class IndexMetaTests(unittest.TestCase):
    @staticmethod
    def driver(stored):
        """A fake graph whose :IndexMeta node holds `stored` (None: no node)."""
        return FakeDriver(lambda query, params: ([{"embedder": stored}] if stored else []) if "RETURN m.embedder" in query else [])

    @staticmethod
    def writes(driver):
        return [params for query, params in driver.calls if "SET m.embedder" in query]

    def test_first_use_writes_embedder_and_dimensions(self):
        driver = self.driver(None)
        GraphStore(driver, gemma()).ensure_schema()
        self.assertEqual(self.writes(driver), [{"name": "entity_vec", "embedder": "embeddinggemma-2", "size": 128}])

    def test_matching_embedder_passes_without_writing(self):
        driver = self.driver("embeddinggemma-2")
        GraphStore(driver, gemma()).ensure_schema()
        self.assertEqual(self.writes(driver), [])

    def test_other_embedder_raises_naming_both(self):
        driver = self.driver("e5-small")
        with self.assertRaisesRegex(RuntimeError, "e5-small.*embeddinggemma-2.*rebuild the graph"):
            GraphStore(driver, gemma()).ensure_schema()
        self.assertEqual(self.writes(driver), [])
        self.assertFalse(any("CREATE" in query for query, _ in driver.calls))

    def test_older_graph_is_backfilled_with_a_message(self):
        driver = self.driver(None)
        with mock.patch("builtins.print") as printed:
            check_embedder(GraphStore(driver, gemma()).run, gemma())
        self.assertEqual(len(self.writes(driver)), 1)
        self.assertIn("assuming embeddinggemma-2", printed.call_args.args[0])

    def test_search_checks_once_and_refuses_other_embedder(self):
        driver = self.driver("e5-small")
        with self.assertRaisesRegex(RuntimeError, "rebuild the graph"):
            HybridRetriever(driver, gemma()).search("q")
        driver = self.driver("embeddinggemma-2")
        retriever = HybridRetriever(driver, gemma())
        retriever.search("q", neighbors=0)
        retriever.search("q", neighbors=0)
        self.assertEqual(sum("RETURN m.embedder" in query for query, _ in driver.calls), 1)


class RetrieverTests(unittest.TestCase):
    def test_reranks_on_full_vectors_fuses_fulltext_and_expands(self):
        embedder = gemma()
        query_vector = embedder.embed(["salmon ocean"], kind="query", data_class="P")[0]
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
        self.assertAlmostEqual(hits[1].similarity, 1.0, places=5)  # "close" is the query vector itself
        self.assertEqual(hits[1].neighbors[0]["id"], "c1")
        vector_call = next(params for query, params in driver.calls if "VECTOR INDEX" in query)
        self.assertEqual(vector_call["labels"], ["Item"])
        self.assertEqual(len(vector_call["vector"]), 128)

    def test_reranker_orders_the_fused_pool_with_fusion_as_tie_break(self):
        embedder = gemma()
        query_vector = embedder.embed(["salmon ocean"], kind="query", data_class="P")[0].tolist()
        rows = [{"id": f"n{i}", "labels": ["Entity", "Item"], "text": f"text {i}", "vec": query_vector, "score": 1.0}
                for i in range(5)]
        driver = FakeDriver(lambda query, params: rows if "VECTOR INDEX" in query else [])
        reranker = mock.Mock()
        # fused order is n0..n4 (vector rank); the reranker prefers n3, then ties n1 and n2, then n0
        reranker.score.side_effect = lambda query, docs, data_class: [{"text 3": 0.9, "text 1": 0.5, "text 2": 0.5}.get(d, 0.1)
                                                                      for d in docs]
        hits = HybridRetriever(driver, embedder, candidates=4, reranker=reranker).search("salmon ocean", k=3, neighbors=0)
        self.assertEqual([hit.id for hit in hits], ["n3", "n1", "n2"])  # n1 before n2: higher fusion score
        self.assertEqual([hit.rerank for hit in hits], [0.9, 0.5, 0.5])
        self.assertEqual(hits[0].weight, 0.9)
        self.assertGreater(hits[1].score, hits[2].score)
        self.assertEqual([hit.found_by for hit in hits], [["meaning"]] * 3)
        query, docs = reranker.score.call_args.args
        self.assertEqual((query, docs), ("salmon ocean", ["text 0", "text 1", "text 2", "text 3"]))  # top `candidates` only
        self.assertEqual(reranker.score.call_args.kwargs, {"data_class": "P"})

    def test_without_reranker_rerank_is_none(self):
        embedder = gemma()
        vector = embedder.embed(["q"], kind="query", data_class="P")[0].tolist()
        driver = FakeDriver(lambda query, params: [{"id": "a", "labels": ["Entity"], "text": "a", "vec": vector, "score": 1.0}]
                            if "VECTOR INDEX" in query else [])
        (hit,) = HybridRetriever(driver, embedder).search("q", neighbors=0)
        self.assertIsNone(hit.rerank)
        self.assertEqual(hit.weight, hit.score)

    def test_restricted_query_never_reaches_the_reranker(self):
        reranker = mock.Mock()
        with self.assertRaises(RestrictedDataError):
            HybridRetriever(FakeDriver(), gemma(), reranker=reranker).search("restricted", data_class="R")
        reranker.score.assert_not_called()

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
        self.assertTrue(all(node.label == "Item" and node.text and node.data_class == "P" for node in nodes))

    def test_media_text_is_caption_not_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            path.write_text('{"id": "p", "modality": "image", "content": "red.png"}\n', encoding="utf-8")
            (node,), _, _ = self.module.load(path)
        self.assertEqual((node.text, node.content), ("", str(Path(tmp) / "red.png")))

    def test_rerank_flag(self):
        args = self.module.parse(["search", "salmon", "--rerank", "--label", "Project"])
        self.assertTrue(args.rerank)
        self.assertEqual(args.labels, ["Project"])
        self.assertFalse(self.module.parse(["search", "salmon"]).rerank)
        self.assertTrue(self.module.parse(["eval", "x.jsonl", "--rerank"]).rerank)

    def test_record_data_class_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            path.write_text('{"id": "r", "content": "access-limited", "data_class": "R"}\n', encoding="utf-8")
            (node,), _, _ = self.module.load(path)
        self.assertEqual(node.data_class, "R")


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
