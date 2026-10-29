import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from campus_ai.research_assistant.openalex import abstract_text, to_records, trim

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_openalex", ROOT / "scripts" / "fetch_openalex.py")
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)

SFU = {"id": "https://openalex.org/I18014758", "display_name": "Simon Fraser University", "ror": "https://ror.org/0213rcc28", "country_code": "CA"}
UBC = {"id": "https://openalex.org/I141945490", "display_name": "University of British Columbia", "ror": "https://ror.org/03rmrcq20", "country_code": "CA"}


def author(n, insts, orcid=None):
    return {"author": {"id": f"https://openalex.org/A{n}", "display_name": f"Author {n}", "orcid": orcid},
            "author_position": "first" if n == 1 else "middle", "institutions": insts}


def work(n, authors, topics=(), sdgs=(), cited=10, year=2023, abstract=None):
    return {
        "id": f"https://openalex.org/W{n}", "doi": f"https://doi.org/10.1/{n}", "title": f"Work {n}", "publication_year": year,
        "type": "article", "language": "en", "cited_by_count": cited, "open_access": {"oa_status": "gold"},
        "authorships": authors,
        "topics": [{"id": f"https://openalex.org/T{t}", "display_name": f"Topic {t}", "score": 0.9,
                    "subfield": {"display_name": "Sub"}, "field": {"display_name": "Field"}} for t in topics],
        "sustainable_development_goals": [{"id": f"https://metadata.un.org/sdg/{s}", "display_name": f"Goal {s}", "score": 0.7} for s in sdgs],
        "abstract_inverted_index": abstract,
        "primary_location": {"landing_page_url": f"https://example.org/{n}"},
    }


class MappingTests(unittest.TestCase):
    def test_abstract_is_put_back_in_order(self):
        self.assertEqual(abstract_text({"smoke": [1], "Wildfire": [0], "and": [2], "health": [3]}), "Wildfire smoke and health")
        self.assertEqual(abstract_text(None), "")

    def test_trim_keeps_what_the_loader_needs(self):
        t = trim(work(1, [author(1, [SFU], "https://orcid.org/0000-0001-2345-6789")], topics=(5,), abstract={"B": [1], "A": [0]}))
        self.assertEqual(t["abstract"], "A B")
        self.assertEqual(t["url"], "https://doi.org/10.1/1")
        self.assertEqual(t["open_access"], "gold")
        self.assertEqual(t["authorships"][0]["author"]["orcid"], "https://orcid.org/0000-0001-2345-6789")
        self.assertEqual(t["authorships"][0]["institutions"][0]["ror"], "https://ror.org/0213rcc28")
        self.assertEqual(t["topics"][0]["subfield"], "Sub")
        self.assertNotIn("abstract_inverted_index", t)

    def test_records(self):
        works = [trim(w) for w in [
            work(1, [author(1, [SFU]), author(2, [SFU, UBC]), author(3, [UBC])], topics=(5, 6), sdgs=(14,), cited=50),
            work(2, [author(1, [SFU]), author(4, [SFU])], topics=(5,), cited=5, year=2021),
            work(3, [author(9, [SFU])] * 40, topics=(7,)),  # mega-collaboration: skipped
            {**work(4, [author(1, [SFU])]), "title": None},  # untitled: skipped
        ]]
        records = to_records(works, "0213rcc28")
        nodes = {r["id"]: r for r in records if "label" in r}
        links = [r for r in records if "src" in r]
        self.assertEqual(sorted(n["label"] for n in nodes.values()),
                         ["Institution", "Publication", "Publication", "Researcher", "Researcher", "Researcher", "SDG", "Topic", "Topic"])
        self.assertNotIn("openalex:A3", nodes)  # UBC only
        self.assertNotIn("openalex:A9", nodes)
        a1 = nodes["openalex:A1"]
        self.assertEqual(a1["content"], "Author 1. Simon Fraser University. Research topics: Topic 5; Topic 6. Publications: Work 1 | Work 2")
        self.assertEqual(a1["props"]["topics"], ["Topic 5", "Topic 6"])
        self.assertEqual(a1["props"]["sdgs"], ["Goal 14"])
        self.assertEqual((a1["props"]["works"], a1["props"]["institution"], a1["props"]["rights"]), (2, "Simon Fraser University", "CC0-1.0"))
        self.assertEqual(nodes["openalex:W1"]["content"], "Work 1")
        self.assertEqual(nodes["openalex:W1"]["props"]["cited_by_count"], 50)
        self.assertEqual(nodes["openalex:T5"]["content"], "Topic 5 (Sub, Field)")
        self.assertEqual(nodes["openalex:sdg:14"]["content"], "UN Sustainable Development Goal: Goal 14")
        self.assertEqual(nodes["https://ror.org/0213rcc28"]["props"]["country"], "CA")

        def of(kind):
            return sorted((l["src"], l["dst"], l.get("props", {})) for l in links if l["type"] == kind)
        self.assertEqual(of("AUTHORED"), [("openalex:A1", "openalex:W1", {"position": "first"}), ("openalex:A1", "openalex:W2", {"position": "first"}),
                                          ("openalex:A2", "openalex:W1", {"position": "middle"}), ("openalex:A4", "openalex:W2", {"position": "middle"})])
        self.assertEqual(of("ABOUT"), [("openalex:W1", "openalex:T5", {"score": 0.9}), ("openalex:W1", "openalex:T6", {"score": 0.9}), ("openalex:W2", "openalex:T5", {"score": 0.9})])
        self.assertEqual(of("SUPPORTS"), [("openalex:W1", "openalex:sdg:14", {"score": 0.7})])
        self.assertEqual(of("WORKS_ON")[:2], [("openalex:A1", "openalex:T5", {"count": 2}), ("openalex:A1", "openalex:T6", {"count": 1})])
        self.assertEqual(of("CONTRIBUTES_TO"), [("openalex:A1", "openalex:sdg:14", {"count": 1}), ("openalex:A2", "openalex:sdg:14", {"count": 1})])
        self.assertEqual(of("COAUTHORED_WITH"), [("openalex:A1", "openalex:A2", {"count": 1}), ("openalex:A1", "openalex:A4", {"count": 1})])
        self.assertEqual(len(of("AFFILIATED_WITH")), 3)
        # Every record is JSON and every link joins nodes that exist.
        for link in links:
            self.assertIn(link["src"], nodes, link)
            self.assertIn(link["dst"], nodes, link)
        json.dumps(records)


class FetchTests(unittest.TestCase):
    def test_pages_until_done_and_writes_both_files(self):
        pages = {
            "*": {"results": [work(1, [author(1, [SFU])], topics=(5,))], "meta": {"next_cursor": "c2"}},
            "c2": {"results": [work(2, [author(1, [SFU])], topics=(5,))], "meta": {"next_cursor": None}},
        }
        calls = []

        def fake_get(path, params):
            calls.append((path, params))
            if path.startswith("institutions/"):
                return {"display_name": "Simon Fraser University", "country_code": "CA", "works_count": 99}
            return pages[params["cursor"]]

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetcher, "get", side_effect=fake_get), \
             mock.patch.dict("os.environ", {"DATA_DIR": tmp}), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(fetcher.main(["--per-year", "10", "--since", "2022", "--until", "2022"]), 0)
            folder = Path(tmp) / "openalex" / "sfu"
            works = [json.loads(l) for l in (folder / "works.jsonl").read_text(encoding="utf-8").splitlines()]
            records = [json.loads(l) for l in (folder / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([w["id"] for w in works], ["https://openalex.org/W1", "https://openalex.org/W2"])
        self.assertEqual(calls[0][0], "institutions/ror:0213rcc28")
        self.assertIn("publication_year:2022", calls[1][1]["filter"])
        self.assertIn("authors_count:<31", calls[1][1]["filter"])
        self.assertEqual(calls[1][1]["sort"], "cited_by_count:desc")
        self.assertEqual(sum("label" in r for r in records), 5)  # 2 publications, 1 researcher, 1 topic, 1 institution...
        self.assertIn("2 works 2022-2022", out.getvalue())

    def test_takes_the_most_cited_of_each_year(self):
        years = []

        def fake_get(path, params):
            if path.startswith("institutions/"):
                return {"display_name": "Simon Fraser University", "country_code": "CA"}
            year = int(params["filter"].split("publication_year:")[1].split(",")[0])
            years.append((year, params["per-page"]))
            return {"results": [work(year * 10 + n, [author(1, [SFU])]) for n in range(3)], "meta": {"next_cursor": "more"}}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetcher, "get", side_effect=fake_get), \
             mock.patch.dict("os.environ", {"DATA_DIR": tmp}), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(fetcher.main(["--per-year", "2", "--since", "2024", "--until", "2026"]), 0)
            works = (Path(tmp) / "openalex" / "sfu" / "works.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(years, [(2024, 2), (2025, 2), (2026, 2)])  # one page each: the quota is filled from the first
        self.assertEqual(len(works), 6)
        self.assertIn("2025: 2 works", out.getvalue())

    def test_stops_at_max_works(self):
        big = {"results": [work(n, [author(1, [SFU])]) for n in range(1, 201)], "meta": {"next_cursor": "more"}}
        with mock.patch.object(fetcher, "get", return_value=big):
            got = list(fetcher.works("0213rcc28", 2021, 150, 30))
        self.assertEqual(len(got), 150)

    def test_api_key_only_when_set(self):
        captured = {}

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return Resp(b"{}")
        with mock.patch.object(fetcher.urllib.request, "urlopen", side_effect=fake_urlopen):
            with mock.patch.dict("os.environ", {}, clear=True):
                fetcher.get("works", {"per-page": 1})
                self.assertNotIn("api_key", captured["url"])
            with mock.patch.dict("os.environ", {"OPENALEX_API_KEY": "k123"}, clear=True):
                fetcher.get("works", {"per-page": 1})
                self.assertIn("api_key=k123", captured["url"])

    def test_budget_exhausted_keeps_what_was_collected(self):
        from urllib.error import HTTPError

        def fake_get(path, params):
            if path.startswith("institutions/"):
                return {"display_name": "Simon Fraser University", "country_code": "CA", "works_count": 99}
            if params["cursor"] == "*":
                return {"results": [work(1, [author(1, [SFU])], topics=(5,))], "meta": {"next_cursor": "c2"}}
            raise HTTPError("https://api.openalex.org/works", 401, "Unauthorized", {}, io.BytesIO(b"{}"))

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetcher, "get", side_effect=fake_get), \
             mock.patch.dict("os.environ", {"DATA_DIR": tmp}), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(fetcher.main(["--per-year", "10"]), 1)
            records = [json.loads(l) for l in (Path(tmp) / "openalex" / "sfu" / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn("openalex:W1", {r.get("id") for r in records})
        self.assertIn("HTTP 401 from OpenAlex after 1 works", out.getvalue())
        self.assertIn("OPENALEX_API_KEY", out.getvalue())


if __name__ == "__main__":
    unittest.main()
