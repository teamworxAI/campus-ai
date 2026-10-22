import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from campus_ai.core.graph import Link, Node
from campus_ai.research_assistant.europeana import to_records
from campus_ai.research_assistant.rights import classify, screen

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "evals" / "rights" / "sample_records.jsonl"
CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"


def load_script():
    spec = importlib.util.spec_from_file_location("graph_search", ROOT / "scripts" / "graph_search.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClassifyTests(unittest.TestCase):
    def test_open_europeana_rights_are_public(self):
        for rights in (
            CC0,
            "http://creativecommons.org/publicdomain/mark/1.0/",
            "http://creativecommons.org/licenses/by/4.0/",
            "http://creativecommons.org/licenses/by-sa/3.0/",
        ):
            self.assertEqual(classify({"source": "europeana", "rights": rights}), ("P", ""))

    def test_closed_or_unknown_rights_are_restricted(self):
        for rights, reason in (
            ("http://creativecommons.org/licenses/by-nc/4.0/", "rights not open"),
            ("http://rightsstatements.org/vocab/InC/1.0/", "rights not open"),
            ("", "rights unknown"),
        ):
            self.assertEqual(classify({"source": "europeana", "rights": rights}), ("R", reason))
        self.assertEqual(classify({"source": "europeana"}), ("R", "rights unknown"))

    def test_access_limits_and_tk_labels_are_restricted(self):
        props = {"source": "arcabc", "rights": CC0}
        self.assertEqual(classify({**props, "access": "open"}), ("P", ""))
        self.assertEqual(classify({**props, "access": "Campus only"}), ("R", "access limit"))
        self.assertEqual(classify({**props, "tk_labels": ["TK Attribution"]})[0], "R")
        self.assertEqual(classify({**props, "rights": "https://localcontexts.org/label/tk-a/"})[0], "R")
        # Markers apply to metadata nodes and fixtures too.
        self.assertEqual(classify({"access": "embargoed"}, unit=False)[0], "R")

    def test_fixtures_and_metadata_need_no_rights_statement(self):
        self.assertEqual(classify({}), ("P", ""))
        self.assertEqual(classify({"source": "europeana"}, unit=False), ("P", ""))


class ScreenTests(unittest.TestCase):
    def test_restricted_item_takes_its_image_and_only_linked_metadata(self):
        nodes = [
            Node("open", "Item", "a", props={"source": "europeana", "rights": CC0}),
            Node("closed", "Item", "b", props={"source": "europeana", "rights": "InC"}),
            Node("closed#image", "Image", modality="image", content="b.jpg", props={"source": "europeana", "rights": CC0}),
            Node("shared", "Collection", "c", props={"source": "europeana"}),
            Node("holder", "Institution", "h", props={"source": "europeana"}),
            Node("only-closed", "Creator", "p", props={"source": "europeana"}),
        ]
        links = [
            Link("closed#image", "PART_OF", "closed"),
            Link("open", "IN", "shared"),
            Link("closed", "IN", "shared"),
            Link("shared", "HELD_BY", "holder"),
            Link("closed", "CREATED_BY", "only-closed"),
            Link("open", "ABOUT", "indexed-earlier"),
        ]
        result = screen(nodes, links)
        self.assertEqual([n.id for n in result.nodes], ["open", "shared", "holder"])
        self.assertEqual(
            [(l.src, l.dst) for l in result.links],
            [("open", "shared"), ("shared", "holder"), ("open", "indexed-earlier")],
        )
        self.assertEqual(
            {n.id: reason for n, reason in result.excluded},
            {"closed": "rights not open", "closed#image": "part of a restricted item",
             "only-closed": "only linked to restricted items"},
        )

    def test_europeana_records_pass(self):
        item = {"id": "/1/x", "title": ["Salmon"], "rights": [CC0], "edmDatasetName": ["d"],
                "dataProvider": ["Museum"], "dcCreator": ["Someone"]}
        records = to_records(item, "media/x.jpg")
        nodes = [Node(r["id"], r["label"], r["content"], props=r["props"]) for r in records if "id" in r]
        links = [Link(r["src"], r["type"], r["dst"]) for r in records if "src" in r]
        result = screen(nodes, links)
        self.assertEqual((len(result.nodes), len(result.links), result.excluded), (len(nodes), len(links), []))

    def test_sample_counts(self):
        nodes, links, _ = load_script().load(SAMPLE)
        result = screen(nodes, links)
        self.assertEqual(
            sorted(n.id for n in result.nodes if n.label == "Item"),
            ["arcabc:example/open", "europeana:/example/by", "europeana:/example/by-sa",
             "europeana:/example/cc0", "europeana:/example/pdm"],
        )
        self.assertEqual((len(result.nodes), len(result.excluded)), (8, 7))
        self.assertTrue(result.report().startswith("rights filter: kept 5 items (8 nodes), excluded 5 items (7 nodes)"))

    def test_bakeoff_fixture_is_kept(self):
        nodes, links, _ = load_script().load(ROOT / "evals" / "embed" / "sample_bakeoff.jsonl")
        self.assertEqual(len(screen(nodes, links).nodes), 6)


class IndexTests(unittest.TestCase):
    def test_index_never_embeds_class_r(self):
        module = load_script()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in (
                {"id": "open", "content": "salmon", "props": {"source": "europeana", "rights": CC0}},
                {"id": "closed", "content": "secret", "props": {"source": "arcabc", "rights": CC0, "tk_labels": ["TK"]}},
            )), encoding="utf-8")
            store = mock.Mock()
            with mock.patch.object(module, "GraphStore", return_value=store), \
                    mock.patch.object(module, "get_embedder", return_value=mock.Mock(name="e")), \
                    mock.patch.object(module, "connect", return_value=mock.MagicMock()), \
                    mock.patch("sys.argv", ["graph_search.py", "index", str(path)]), \
                    redirect_stdout(io.StringIO()) as out:
                module.main()
        (written,), _ = store.upsert.call_args
        self.assertEqual([node.id for node in written], ["open"])
        self.assertIn("excluded 1 items (1 nodes) as class R", out.getvalue())

    def test_rights_command_needs_no_embedder_or_neo4j(self):
        module = load_script()
        with mock.patch.object(module, "get_embedder") as embedder, mock.patch.object(module, "connect") as connect, \
                mock.patch("sys.argv", ["graph_search.py", "rights", str(SAMPLE)]), \
                redirect_stdout(io.StringIO()) as out:
            module.main()
        embedder.assert_not_called()
        connect.assert_not_called()
        self.assertIn("excluded europeana:/example/inc (rights not open) https://www.europeana.eu/item/example/inc",
                      out.getvalue())


if __name__ == "__main__":
    unittest.main()
