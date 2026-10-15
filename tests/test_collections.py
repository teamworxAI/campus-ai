import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from campus_ai.core.graph import Hit
from campus_ai.research_assistant import collections
from campus_ai.research_assistant.api import create_app
from campus_ai.research_assistant.collections import CollectionsSearch, card, citations, licence, matched, media_url

ROW = {
    "id": "europeana:/1/a",
    "text": "Salmon Fishing\nLaxfiske\nLohenpyynti",
    "url": "https://www.europeana.eu/item/1/a",
    "rights": "http://creativecommons.org/publicdomain/zero/1.0/",
    "type": "IMAGE",
    "year": "",
    "source": "europeana",
    "provider": "National Library of Finland",
    "file": "data/europeana/salmon/media/a.jpg",
    "collection": "2021012_FINDL",
    "holder": "Finnish National Gallery",
    "creators": ["Berndtson, Gunnar", "okänd"],
}
BOOK = {**ROW, "id": "europeana:/2/b", "text": "Salmon-fishing in Canada", "type": "TEXT", "year": "1860", "file": None,
        "rights": "http://creativecommons.org/publicdomain/mark/1.0/", "creators": []}


class Record(dict):
    def data(self):
        return dict(self)


class FakeDriver:
    def __init__(self, rows):
        self.rows = {row["id"]: row for row in rows}

    def execute_query(self, query, params, database_=None):
        if "count(i)" in query:
            return [Record(n=len(self.rows))], None, None
        return [Record(self.rows[id_]) for id_ in params["ids"] if id_ in self.rows], None, None


def service(rows, hits):
    """A CollectionsSearch whose retriever returns `hits[label]` for each label filter."""
    search = CollectionsSearch(FakeDriver(rows), embedder=None)
    search.retriever.search = lambda query, k, modality="text", labels=None, neighbors=5: hits[labels[0]][:k]
    return search


class CardTests(unittest.TestCase):
    def test_licence_labels(self):
        self.assertEqual(licence("http://creativecommons.org/publicdomain/zero/1.0/"), "CC0 1.0")
        self.assertEqual(licence("http://creativecommons.org/publicdomain/mark/1.0/"), "Public domain")
        self.assertEqual(licence("http://creativecommons.org/licenses/by/4.0/"), "CC BY 4.0")
        self.assertEqual(licence("http://creativecommons.org/licenses/by-sa/3.0/"), "CC BY-SA 3.0")
        self.assertEqual(licence(""), "See source")

    def test_media_url_only_inside_data(self):
        self.assertEqual(media_url("data/europeana/salmon/media/a.jpg"), "/media/europeana/salmon/media/a.jpg")
        self.assertIsNone(media_url("/etc/passwd"))
        self.assertIsNone(media_url("data/../.env"))
        self.assertIsNone(media_url("models/x.jpg"))
        self.assertIsNone(media_url(None))

    def test_card_splits_title_and_drops_unknown_creators(self):
        c = card(ROW)
        self.assertEqual((c.title, c.description), ("Salmon Fishing", "Laxfiske\nLohenpyynti"))
        self.assertEqual(c.creators, ["Berndtson, Gunnar"])
        self.assertEqual(c.image, "/media/europeana/salmon/media/a.jpg")
        self.assertNotIn("file", c.public())

    def test_matched_labels(self):
        self.assertEqual(matched(["words"], picture=True), "Picture and words")
        self.assertEqual(matched([], picture=True), "Picture")
        self.assertEqual(matched(["meaning", "words"], picture=False), "Meaning and words")
        self.assertEqual(matched(["words"], picture=False), "Words")

    def test_citations_name_source_licence_and_url(self):
        cites = citations(card(BOOK))
        self.assertIn("(1860). Salmon-fishing in Canada [Text].", cites["apa"])
        self.assertIn("Licence: Public domain.", cites["chicago"])
        self.assertIn("url = {https://www.europeana.eu/item/1/a}", cites["bibtex"])
        self.assertIn("@misc{", cites["bibtex"])


class SearchTests(unittest.TestCase):
    def test_pictures_map_images_to_items_and_mark_word_matches(self):
        hits = {
            "Image": [Hit("europeana:/1/a#image", ["Entity", "Image"], "", 0.03)],
            "Item": [Hit("europeana:/1/a", ["Entity", "Item"], "", 0.03, found_by=["meaning", "words"])],
        }
        (picture,) = service([ROW, BOOK], hits).pictures("salmon")
        self.assertEqual((picture.id, picture.matched), ("europeana:/1/a", "Picture and words"))

    def test_texts_skip_items_with_pictures(self):
        hits = {"Item": [Hit("europeana:/1/a", [], "", 0.03, found_by=["meaning"]),
                         Hit("europeana:/2/b", [], "", 0.02, found_by=["meaning"])]}
        texts = service([ROW, BOOK], hits).texts("salmon")
        self.assertEqual([(c.id, c.matched) for c in texts], [("europeana:/2/b", "Meaning")])

    def test_item_has_citations_and_similar_pictures_without_itself(self):
        hits = {"Image": [Hit("europeana:/1/a#image", [], "", 0.03), Hit("europeana:/3/c#image", [], "", 0.02)]}
        other = {**ROW, "id": "europeana:/3/c"}
        item = service([ROW, other], hits).item("europeana:/1/a")
        self.assertEqual([c["id"] for c in item["similar"]], ["europeana:/3/c"])
        self.assertIn("apa", item["citations"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        hits = {"Image": [Hit("europeana:/1/a#image", [], "", 0.03)],
                "Item": [Hit("europeana:/2/b", [], "", 0.02, found_by=["words"])]}
        self.service = service([ROW, BOOK], hits)
        self.client = TestClient(create_app(self.service))

    def test_search_returns_pictures_and_texts(self):
        body = self.client.get("/api/search", params={"q": "salmon"}).json()
        self.assertEqual([c["id"] for c in body["pictures"]], ["europeana:/1/a"])
        self.assertEqual([c["id"] for c in body["texts"]], ["europeana:/2/b"])
        self.assertEqual(self.client.get("/api/search", params={"q": ""}).status_code, 422)

    def test_item_ids_with_slashes_and_missing_items(self):
        self.assertEqual(self.client.get("/api/items/europeana:%2F2%2Fb").json()["title"], "Salmon-fishing in Canada")
        self.assertEqual(self.client.get("/api/items/nope").status_code, 404)

    def test_image_upload_checks_type(self):
        response = self.client.post("/api/search/image", files={"file": ("a.txt", b"hello", "text/plain")})
        self.assertEqual(response.status_code, 415)

    def test_media_serves_only_images_in_media_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "set" / "media").mkdir(parents=True)
            (root / "set" / "media" / "a.jpg").write_bytes(b"jpg")
            (root / "set" / "items.jsonl").write_text("{}")
            (root / "private").mkdir()
            (root / "private" / "b.jpg").write_bytes(b"jpg")
            with mock.patch.object(collections, "DATA_DIR", root):
                self.assertEqual(self.client.get("/media/set/media/a.jpg").content, b"jpg")
                self.assertEqual(self.client.get("/media/set/items.jsonl").status_code, 404)
                self.assertEqual(self.client.get("/media/private/b.jpg").status_code, 404)
                self.assertEqual(self.client.get("/media/set/media/../../private/b.jpg").status_code, 404)


if __name__ == "__main__":
    unittest.main()
