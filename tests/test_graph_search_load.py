import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JsonlLoadTests(unittest.TestCase):
    def test_records_with_unicode_line_separators_stay_whole(self):
        """CORDIS objectives contain U+2028 and NEL; str.splitlines() would cut a JSON line there."""
        records = [
            {"id": "a", "label": "Project", "content": "Line one line two \x85 and   three"},
            {"src": "a", "type": "ABOUT", "dst": "b"},
            {"query": "q", "relevant": ["a"]},
            {"id": "b", "label": "Topic", "content": "plain"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n\n", encoding="utf-8")
            nodes, links, queries = load_module("graph_search").load(path)
        self.assertEqual([n.id for n in nodes], ["a", "b"])
        self.assertIn(" ", nodes[0].text)
        self.assertEqual([(l.src, l.dst) for l in links], [("a", "b")])
        self.assertEqual(queries, [{"query": "q", "relevant": ["a"]}])

    def test_label_filter_keeps_those_nodes_and_their_links(self):
        from unittest import mock

        from campus_ai.core.graph import Link, Node
        from campus_ai.research_assistant.rights import Screened

        graph_search = load_module("graph_search")
        result = Screened([Node("t", "CallTopic", "x"), Node("p", "Project", "y"), Node("c", "Cluster", "z")],
                          [Link("t", "PART_OF", "c"), Link("p", "UNDER_TOPIC", "t"), Link("p", "FUNDED_UNDER", "c")])
        with mock.patch("sys.stdout"):
            kept = graph_search.only(result, ["CallTopic"])
        self.assertEqual([n.id for n in kept.nodes], ["t"])
        self.assertEqual([l.type for l in kept.links], ["PART_OF", "UNDER_TOPIC"])
        self.assertIs(graph_search.only(result, None), result)


if __name__ == "__main__":
    unittest.main()
