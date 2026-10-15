import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from campus_ai.research_assistant.europeana import is_open, to_records

ROOT = Path(__file__).resolve().parents[1]

ITEM = {
    "id": "/916105/bhm_photo_1",
    "guid": "https://www.europeana.eu/item/916105/bhm_photo_1",
    "type": "IMAGE",
    "title": ["Fartyg på varvet", "Shipyard", "shipyard "],
    "dcDescription": ["Norse Lady,  Nov 1961."],
    "rights": ["http://creativecommons.org/publicdomain/mark/1.0/"],
    "edmPreview": ["https://api.europeana.eu/thumbnail/v2/url.json?uri=x&type=IMAGE"],
    "edmDatasetName": ["916105_bhm_photo"],
    "dataProvider": ["Bohuslän Museum"],
    "provider": ["Swedish Open Cultural Heritage"],
    "dcCreator": ["Andersson, Arne", "http://data.europeana.eu/agent/1"],
    "language": ["sv"],
}


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_europeana", ROOT / "scripts" / "fetch_europeana.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordTests(unittest.TestCase):
    def test_open_rights_only(self):
        self.assertTrue(is_open("http://creativecommons.org/licenses/by-sa/4.0/"))
        self.assertTrue(is_open("http://creativecommons.org/publicdomain/zero/1.0/"))
        self.assertFalse(is_open("http://creativecommons.org/licenses/by-nc/4.0/"))
        self.assertFalse(is_open("http://rightsstatements.org/vocab/InC/1.0/"))
        self.assertEqual(to_records({**ITEM, "rights": ["http://rightsstatements.org/vocab/InC/1.0/"]}), [])

    def test_item_with_image_collection_and_creator(self):
        records = to_records(ITEM, "media/a.jpg")
        nodes = {r["id"]: r for r in records if "id" in r}
        links = {(r["src"], r["type"], r["dst"]) for r in records if "src" in r}
        item = nodes["europeana:/916105/bhm_photo_1"]
        self.assertEqual(item["content"], "Fartyg på varvet\nShipyard\nNorse Lady, Nov 1961.")
        self.assertEqual(item["props"]["rights"], ITEM["rights"][0])
        self.assertEqual(item["props"]["url"], ITEM["guid"])
        self.assertEqual(nodes["europeana:/916105/bhm_photo_1#image"]["content"], "media/a.jpg")
        self.assertEqual(
            links,
            {
                ("europeana:/916105/bhm_photo_1#image", "PART_OF", "europeana:/916105/bhm_photo_1"),
                ("europeana:/916105/bhm_photo_1", "IN", "europeana:collection:916105_bhm_photo"),
                ("europeana:collection:916105_bhm_photo", "HELD_BY", "europeana:institution:bohuslän-museum"),
                ("europeana:/916105/bhm_photo_1", "CREATED_BY", "europeana:creator:andersson-arne"),
            },
        )

    def test_records_load_into_graph_search(self):
        spec = importlib.util.spec_from_file_location("graph_search", ROOT / "scripts" / "graph_search.py")
        graph_search = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(graph_search)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in to_records(ITEM, "media/a.jpg")), encoding="utf-8")
            nodes, links, _ = graph_search.load(path)
        image = next(node for node in nodes if node.label == "Image")
        self.assertEqual((image.modality, image.text, image.content), ("image", "", str(Path(tmp) / "media/a.jpg")))
        self.assertEqual(len(nodes), 5)
        self.assertEqual(len(links), 4)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.module = load_script()

    def test_search_follows_cursor_and_sends_key_in_header(self):
        pages = [{"items": [{"id": "/1"}, {"id": "/2"}], "nextCursor": "c2"}, {"items": [{"id": "/3"}]}]
        calls = []

        def get(url, key=None):
            calls.append((url, key))
            return "application/json", json.dumps(pages[len(calls) - 1]).encode()

        with mock.patch.object(self.module, "get", get):
            items = list(self.module.search("secret", "salmon", 5, ["TYPE:IMAGE"]))
        self.assertEqual([item["id"] for item in items], ["/1", "/2", "/3"])
        self.assertIn("cursor=c2", calls[1][0])
        self.assertIn("qf=TYPE%3AIMAGE", calls[0][0])
        self.assertTrue(all(key == "secret" and "secret" not in url for url, key in calls))

    def test_thumbnail_downloads_once_and_skips_non_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            get = mock.Mock(return_value=("image/jpeg", b"jpg"))
            with mock.patch.object(self.module, "get", get):
                path = self.module.thumbnail(ITEM, Path(tmp))
                self.assertEqual(self.module.thumbnail(ITEM, Path(tmp)), path)
                self.assertIsNone(self.module.thumbnail({**ITEM, "type": "TEXT"}, Path(tmp)))
            self.assertEqual(path.read_bytes(), b"jpg")
            get.assert_called_once_with(ITEM["edmPreview"][0] + "&size=w400")


if __name__ == "__main__":
    unittest.main()
