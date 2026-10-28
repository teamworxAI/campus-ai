import unittest
from unittest import mock

from fastapi.testclient import TestClient

from campus_ai.core.graph import Hit
from campus_ai.research_assistant.api import create_app
from campus_ai.research_assistant.matching import (ASSOCIATED, DEFAULT_SIGNAL, EU, RERANK_INSTRUCTION, SIGNALS, ResearchSearch,
                                                   research_reranker)


class Record(dict):
    def data(self):
        return dict(self)


class FakeDriver:
    """Answers the matching module's Cypher from canned rows, keyed by a phrase in the query."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def execute_query(self, query, params, database_=None):
        self.calls.append((query, params))
        for phrase, rows in self.answers.items():
            if phrase in query:
                rows = rows(params) if callable(rows) else rows
                return [Record(r) for r in rows], None, None
        return [], None, None


def hit(id_, score, found=("meaning",)):
    return Hit(id_, ["Entity"], "", score, found_by=list(found))


def search_with(driver, hits, signal="projects"):
    s = ResearchSearch(driver, embedder=None, signal=signal)
    s.retriever.search = lambda query, k, modality="text", labels=None, neighbors=5, data_class="P": hits.get(labels[0], [])[:k]
    return s


class ExpertTests(unittest.TestCase):
    def test_experts_carry_their_evidence(self):
        driver = FakeDriver({"AUTHORED": [
            {"id": "openalex:A1", "name": "Ryan Allen", "orcid": "", "url": "https://openalex.org/A1", "institution": "SFU",
             "topics": ["Air Quality and Health Impacts"], "sdgs": ["Good health"], "works": 6,
             "publications": [{"title": "Smoke and health", "year": 2023, "url": "https://doi.org/x", "id": "openalex:W1"}, {"title": None}]},
        ]})
        s = search_with(driver, {"Researcher": [hit("openalex:A1", 0.03, ("meaning", "words")), hit("openalex:A9", 0.01)]})
        out = s.experts("wildfire smoke", k=5)
        self.assertEqual(len(out), 1)  # A9 is not in the graph any more: dropped, not invented
        self.assertEqual(out[0]["name"], "Ryan Allen")
        self.assertEqual(out[0]["evidence"]["publications"], [{"title": "Smoke and health", "year": 2023, "url": "https://doi.org/x", "id": "openalex:W1"}])
        self.assertEqual(out[0]["found_by"], ["meaning", "words"])
        self.assertEqual(driver.calls[0][1]["ids"], ["openalex:A1", "openalex:A9"])

    def test_no_hits_no_queries(self):
        driver = FakeDriver({})
        self.assertEqual(search_with(driver, {"Researcher": []}).experts("x"), [])
        self.assertEqual(driver.calls, [])


class PartnerTests(unittest.TestCase):
    def rows(self, params):
        base = [
            {"id": "cordis:org:1", "name": "UNIVERSITAET WIEN", "country": "AT", "activity": "higher education", "city": "Wien", "url": "",
             "fields": ["public health"], "projects": 9, "role": "coordinator", "project": "cordis:101", "acronym": "SMOKE",
             "title": "Smoke and health", "project_url": "https://cordis.europa.eu/project/id/101", "start": "2023-01-01"},
            {"id": "cordis:org:2", "name": "SFU", "country": "CA", "activity": "higher education", "city": "", "url": "", "fields": [],
             "projects": 1, "role": "participant", "project": "cordis:101", "acronym": "SMOKE", "title": "Smoke and health",
             "project_url": "", "start": "2023-01-01"},
            {"id": "cordis:org:3", "name": "US LAB", "country": "US", "activity": "research organisation", "city": "", "url": "",
             "fields": [], "projects": 1, "role": "participant", "project": "cordis:102", "acronym": "AIR", "title": "Air", "project_url": "", "start": ""},
            {"id": "cordis:org:1", "name": "UNIVERSITAET WIEN", "country": "AT", "activity": "higher education", "city": "Wien", "url": "",
             "fields": ["public health"], "projects": 9, "role": "participant", "project": "cordis:102", "acronym": "AIR", "title": "Air",
             "project_url": "", "start": ""},
            {"id": "cordis:org:4", "name": "OSLO MET", "country": "NO", "activity": "higher education", "city": "Oslo", "url": "",
             "fields": ["air pollution"], "projects": 2, "role": "participant", "project": "cordis:102", "acronym": "AIR", "title": "Air",
             "project_url": "", "start": ""},
        ]
        return [r for r in base if r["project"] in params["ids"]]

    def test_partners_are_ranked_by_their_matching_projects(self):
        driver = FakeDriver({"PARTICIPATED_IN": self.rows})
        s = search_with(driver, {"Project": [hit("cordis:101", 0.04), hit("cordis:102", 0.02)]})
        out = s.partners("wildfire smoke and health", k=10)
        self.assertEqual([o["name"] for o in out], ["UNIVERSITAET WIEN", "OSLO MET"])  # CA and US are not eligible by default
        wien = out[0]
        self.assertAlmostEqual(wien["score"], 0.04 * 1.25 + 0.02)
        self.assertEqual([p["acronym"] for p in wien["evidence"]["projects"]], ["SMOKE", "AIR"])
        self.assertEqual(wien["evidence"]["projects"][0]["role"], "coordinator")
        self.assertEqual(wien["projects_total"], 9)

    def test_reranked_projects_weigh_by_rerank_score(self):
        driver = FakeDriver({"PARTICIPATED_IN": self.rows})
        smoke, air = hit("cordis:101", 0.04), hit("cordis:102", 0.02)
        smoke.rerank, air.rerank = 0.1, 0.9  # the reranker prefers AIR
        out = search_with(driver, {"Project": [air, smoke]}).partners("air quality", k=10)
        self.assertEqual([o["name"] for o in out], ["UNIVERSITAET WIEN", "OSLO MET"])
        self.assertAlmostEqual(out[0]["score"], 0.1 * 1.25 + 0.9)
        self.assertAlmostEqual(out[1]["score"], 0.9)
        self.assertEqual([p["acronym"] for p in out[0]["evidence"]["projects"]], ["AIR", "SMOKE"])

    def test_rank_and_rrf_weightings_do_not_saturate(self):
        driver = FakeDriver({"PARTICIPATED_IN": self.rows})
        smoke, air = hit("cordis:101", 0.04), hit("cordis:102", 0.02)
        smoke.rerank, air.rerank = 0.001, 0.999  # the reranker prefers AIR; fusion preferred SMOKE
        s = search_with(driver, {"Project": [air, smoke]})
        by_rank = s.partners("air quality", k=10, weighting="rank")
        self.assertAlmostEqual(by_rank[1]["score"], 1 / 61, places=4)  # OSLO MET: AIR only, reranked first
        self.assertAlmostEqual(by_rank[0]["score"], 1 / 61 + 1.25 / 62, places=4)
        by_rrf = s.partners("air quality", k=10, weighting="rrf")
        self.assertAlmostEqual(by_rrf[1]["score"], 1 / 61 + 1 / 62, places=4)  # AIR: reranked 1st, fused 2nd
        self.assertAlmostEqual(by_rrf[0]["score"], 2.25 * (1 / 61 + 1 / 62), places=4)
        self.assertAlmostEqual(by_rrf[0]["evidence"]["projects"][0]["score"], 1 / 62 + 1 / 61, places=4)

    def test_weightings_without_a_reranker_use_fusion_scores(self):
        from campus_ai.research_assistant.matching import project_weights
        hits = [hit("a", 0.04), hit("b", 0.02)]
        for weighting in ("probability", "rank", "rrf"):
            self.assertEqual(project_weights(hits, weighting), {"a": 0.04, "b": 0.02})
        with self.assertRaises(ValueError):
            project_weights(hits, "sum")
        with self.assertRaises(ValueError):
            ResearchSearch(FakeDriver({}), None, weighting="sum")

    def test_pool_reaches_the_retriever(self):
        s = ResearchSearch(FakeDriver({}), None, reranker=object(), pool=20)
        self.assertEqual((s.retriever.pool, s.retriever.candidates), (20, 50))
        self.assertEqual(ResearchSearch(FakeDriver({}), None).retriever.pool, 50)

    def test_reranker_reaches_the_retriever(self):
        reranker = object()
        self.assertIs(ResearchSearch(FakeDriver({}), None, reranker=reranker).retriever.reranker, reranker)
        self.assertIsNone(ResearchSearch(FakeDriver({}), None).retriever.reranker)
        self.assertEqual(research_reranker().instruction, RERANK_INSTRUCTION)

    def test_country_sets_and_exclusion(self):
        driver = FakeDriver({"PARTICIPATED_IN": self.rows})
        s = search_with(driver, {"Project": [hit("cordis:101", 0.04), hit("cordis:102", 0.02)]})
        self.assertEqual([o["country"] for o in s.partners("x", countries="eu")], ["AT"])
        self.assertEqual(sorted(o["country"] for o in s.partners("x", countries="all")), ["AT", "NO", "US"])  # home (CA) left out
        self.assertEqual(sorted(o["country"] for o in s.partners("x", countries="all", home="")), ["AT", "CA", "NO", "US"])
        only_air = s.partners("x", exclude_project="cordis:101")
        self.assertEqual([o["name"] for o in only_air], ["UNIVERSITAET WIEN", "OSLO MET"])
        self.assertEqual([p["acronym"] for p in only_air[0]["evidence"]["projects"]], ["AIR"])
        self.assertIn("CA", ASSOCIATED)
        self.assertNotIn("UK", EU)

    # --- the direct Organization signal and its fusion with the project-derived order ---

    def org_rows(self, params):
        recent = {"cordis:org:5": [{"id": "cordis:103", "acronym": "FISH", "title": "Fish", "url": "https://x/103", "role": "coordinator", "start": "2024-01-01"},
                                   {"id": "cordis:101", "acronym": "SMOKE", "title": "Smoke and health", "url": "", "role": "participant", "start": "2023-01-01"}],
                  "cordis:org:1": [{"id": "cordis:101", "acronym": "SMOKE", "title": "Smoke and health", "url": "", "role": "coordinator", "start": "2023-01-01"}],
                  "cordis:org:2": [{"id": None}]}
        base = [
            {"id": "cordis:org:5", "name": "AARHUS", "country": "DK", "activity": "higher education", "city": "Aarhus", "url": "", "fields": ["fisheries"], "projects": 2},
            {"id": "cordis:org:2", "name": "SFU", "country": "CA", "activity": "higher education", "city": "", "url": "", "fields": [], "projects": 1},
            {"id": "cordis:org:1", "name": "UNIVERSITAET WIEN", "country": "AT", "activity": "higher education", "city": "Wien", "url": "", "fields": ["public health"], "projects": 9},
        ]
        return [{**r, "recent": recent[r["id"]]} for r in base if r["id"] in params["ids"]]

    def both_signals(self):
        driver = FakeDriver({"AS recent": self.org_rows, "PARTICIPATED_IN": self.rows})  # the organisation query also says PARTICIPATED_IN
        direct = [hit("cordis:org:5", 0.05, ("meaning", "words")), hit("cordis:org:2", 0.04), hit("cordis:org:1", 0.03)]
        return driver, {"Project": [hit("cordis:101", 0.04), hit("cordis:102", 0.02)], "Organization": direct}

    def test_organisations_signal_ranks_their_own_nodes(self):
        driver, hits = self.both_signals()
        out = search_with(driver, hits, signal="organisations").partners("fisheries", k=10)
        self.assertEqual([o["name"] for o in out], ["AARHUS", "UNIVERSITAET WIEN"])  # SFU (CA, home) left out
        self.assertEqual(out[0]["score"], 0.05)
        self.assertEqual(out[0]["evidence"]["organisation"], {"id": "cordis:org:5", "found_by": ["meaning", "words"], "score": 0.05, "similarity": 0.0})
        # No matching project to cite: its most recent ones are the evidence, scored 0
        self.assertEqual([(p["acronym"], p["score"]) for p in out[0]["evidence"]["projects"]], [("FISH", 0.0), ("SMOKE", 0.0)])
        self.assertEqual([p["acronym"] for p in out[1]["evidence"]["projects"]], ["SMOKE"])
        self.assertTrue(all("PARTICIPATED_IN]->(p:Entity) WHERE p.id" not in q for q, _ in driver.calls))  # no project search
        hidden = search_with(driver, hits, signal="organisations").partners("fisheries", exclude_project="cordis:101")
        self.assertEqual([p["acronym"] for p in hidden[0]["evidence"]["projects"]], ["FISH"])

    def test_fused_signal_adds_reciprocal_ranks(self):
        driver, hits = self.both_signals()
        out = search_with(driver, hits, signal="fused").partners("fisheries and smoke", k=10)
        self.assertEqual([o["name"] for o in out], ["UNIVERSITAET WIEN", "AARHUS", "OSLO MET"])
        self.assertAlmostEqual(out[0]["score"], 1 / 61 + 1 / 62, places=4)  # first by projects, second directly
        self.assertAlmostEqual(out[1]["score"], 1 / 61, places=4)  # directly only
        self.assertAlmostEqual(out[2]["score"], 1 / 62, places=4)  # by projects only
        self.assertEqual([p["acronym"] for p in out[0]["evidence"]["projects"]], ["SMOKE", "AIR"])  # matching projects stay the evidence
        self.assertEqual(out[0]["evidence"]["organisation"]["found_by"], ["meaning"])
        self.assertNotIn("organisation", out[2]["evidence"])
        self.assertEqual([p["acronym"] for p in out[1]["evidence"]["projects"]], ["FISH", "SMOKE"])
        half = search_with(driver, hits, signal="fused").partners("fisheries and smoke", k=10, organisation_weight=0.5)
        self.assertEqual([o["name"] for o in half], ["UNIVERSITAET WIEN", "OSLO MET", "AARHUS"])
        self.assertAlmostEqual(half[2]["score"], 0.5 / 61, places=4)
        self.assertEqual([o["name"] for o in search_with(driver, hits, signal="projects").partners("x", signal="fused", k=1)], ["UNIVERSITAET WIEN"])

    def test_fused_filters_both_signals_by_country(self):
        driver, hits = self.both_signals()
        s = search_with(driver, hits, signal="fused")
        self.assertEqual([o["name"] for o in s.partners("x", countries="eu")], ["UNIVERSITAET WIEN", "AARHUS"])
        self.assertEqual([o["name"] for o in s.partners("x", countries="all", home="")], ["UNIVERSITAET WIEN", "SFU", "AARHUS", "US LAB", "OSLO MET"])
        self.assertEqual(s.partners("x", countries="all", home="")[1]["evidence"]["projects"][0]["acronym"], "SMOKE")  # from the pool

    def test_signals_are_checked(self):
        self.assertIn(DEFAULT_SIGNAL, SIGNALS)
        with self.assertRaises(ValueError):
            ResearchSearch(FakeDriver({}), None, signal="rumour")
        driver, hits = self.both_signals()
        with self.assertRaises(ValueError):
            search_with(driver, hits).partners("x", signal="rumour")
        self.assertEqual(search_with(driver, {}, signal="fused").partners("x"), [])
        self.assertEqual(driver.calls, [])


class CallTests(unittest.TestCase):
    def test_calls_filter_by_status_and_keep_order(self):
        topics = {
            "topic:A": {"id": "topic:A", "identifier": "HORIZON-CL1-2026-01", "title": "Smoke", "call": "C", "call_title": "Health",
                        "status": "Open", "opening": "2026-01-01", "deadlines": ["2026-04-01"], "url": "https://x/a", "actions": ["HORIZON-RIA"], "clusters": ["Health"]},
            "topic:B": {"id": "topic:B", "identifier": "HORIZON-CL1-2022-01", "title": "Old", "call": "", "call_title": "", "status": "Closed",
                        "opening": "", "deadlines": [], "url": "", "actions": [], "clusters": []},
            "topic:C": {"id": "topic:C", "identifier": "HORIZON-CL1-2027-01", "title": "Soon", "call": "", "call_title": "", "status": "Forthcoming",
                        "opening": "", "deadlines": [], "url": "", "actions": [], "clusters": []},
        }
        driver = FakeDriver({"PART_OF": lambda params: [t for i, t in topics.items() if i in params["ids"] and t["status"] in params["status"]],
                             "r.text AS text": [{"name": "Ryan Allen", "text": "Ryan Allen. SFU. Research topics: air quality"}]})
        s = search_with(driver, {"CallTopic": [hit("topic:B", 0.05), hit("topic:A", 0.04), hit("topic:C", 0.03)]})
        self.assertEqual([c["identifier"] for c in s.calls("smoke")], ["HORIZON-CL1-2026-01", "HORIZON-CL1-2027-01"])
        self.assertEqual([c["identifier"] for c in s.calls("smoke", status="forthcoming")], ["HORIZON-CL1-2027-01"])
        self.assertEqual([c["identifier"] for c in s.calls("smoke", status="all")], ["HORIZON-CL1-2022-01", "HORIZON-CL1-2026-01", "HORIZON-CL1-2027-01"])
        self.assertEqual(s.calls("smoke")[0]["clusters"], ["Health"])
        for_allen = s.calls_for("openalex:A1")
        self.assertEqual(for_allen["researcher"]["name"], "Ryan Allen")
        self.assertEqual(len(for_allen["calls"]), 2)
        self.assertEqual(s.calls_for("openalex:nobody") if not driver.answers.pop("r.text AS text") else None, None)


class FakeResearch:
    def experts(self, query, k=10):
        return [{"id": "openalex:A1", "name": "Ryan Allen", "score": 0.03, "evidence": {"topics": ["air"], "publications": []}, "q": query, "k": k}]

    def partners(self, query, k=10, countries="associated", exclude_project=None, candidates=30, home="CA", signal=None):
        return [{"id": "cordis:org:1", "name": "WIEN", "country": "AT", "countries": countries, "signal": signal, "score": 0.05,
                 "evidence": {"projects": []}}]

    def calls(self, query, k=10, status="open"):
        return [{"id": "topic:A", "identifier": "HORIZON-X", "status": status, "score": 0.04}]

    def calls_for(self, researcher_id, k=10, status="open"):
        return {"researcher": {"id": researcher_id, "name": "Ryan Allen"} if researcher_id == "openalex:A1" else None, "calls": self.calls("", k, status)}

    def call(self, call_id):
        return {"id": call_id, "identifier": "HORIZON-X", "title": "Smoke", "call_title": "Health", "status": "Open", "deadlines": [],
                "actions": ["HORIZON-RIA"], "parts": ["HORIZON.2.1"]} if call_id == "topic:A" else None

    def counts(self):
        return {"Researcher": 1}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(service=mock.Mock(count=lambda: 0), research=FakeResearch()))

    def test_endpoints(self):
        r = self.client.get("/api/experts", params={"q": "wildfire smoke", "k": 3}).json()
        self.assertEqual((r["query"], r["experts"][0]["name"], r["experts"][0]["k"]), ("wildfire smoke", "Ryan Allen", 3))
        r = self.client.get("/api/partners", params={"q": "smoke", "countries": "eu"}).json()
        self.assertEqual((r["partners"][0]["countries"], r["partners"][0]["signal"], r["signal"]), ("eu", None, DEFAULT_SIGNAL))
        r = self.client.get("/api/partners", params={"q": "smoke", "signal": "projects"}).json()
        self.assertEqual((r["partners"][0]["signal"], r["signal"]), ("projects", "projects"))
        self.assertEqual(self.client.get("/api/partners", params={"q": "smoke", "countries": "mars"}).status_code, 422)
        self.assertEqual(self.client.get("/api/partners", params={"q": "smoke", "signal": "rumour"}).status_code, 422)
        r = self.client.get("/api/calls", params={"q": "smoke", "status": "forthcoming"}).json()
        self.assertEqual(r["calls"][0]["status"], "forthcoming")
        self.assertEqual(self.client.get("/api/calls", params={"q": "smoke", "status": "yesterday"}).status_code, 422)
        self.assertEqual(self.client.get("/api/calls/for/openalex:A1").json()["researcher"]["name"], "Ryan Allen")
        self.assertEqual(self.client.get("/api/calls/for/openalex:nobody").status_code, 404)
        self.assertEqual(self.client.get("/api/experts", params={"q": ""}).status_code, 422)
        self.assertEqual(self.client.get("/api/health").json()["graph"], {"Researcher": 1})

    def test_brief_endpoint(self):
        from campus_ai.core.llm import LLMResponse
        from campus_ai.research_assistant import consortium

        answer = LLMResponse("## Fit to the call\nFits [topic:A].\n## Proposed partners\nWIEN [cordis:org:1]. Ghost [cordis:org:9].\n"
                             "## Gaps and next steps\nMore partners.", "m", 1, 1, "stop")
        with mock.patch.object(consortium, "generate", return_value=answer):
            r = self.client.post("/api/brief", json={"call_id": "topic:A"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["query"], "Smoke. Health")
        self.assertEqual([p["name"] for p in body["partners"]], ["WIEN"])
        self.assertEqual(body["eligibility"]["action"], "HORIZON-RIA")
        self.assertFalse(body["eligibility"]["ok"])  # AT + CA only: two countries
        self.assertIn("only 2 different eligible countries", body["eligibility"]["problems"][0])
        self.assertNotIn("cordis:org:9", body["brief"]["brief"])
        self.assertIn("WIEN [cordis:org:1].", body["brief"]["brief"])
        self.assertTrue(body["brief"]["needs_review"])
        self.assertEqual(self.client.post("/api/brief", json={"call_id": "topic:nope"}).status_code, 404)
        self.assertEqual(self.client.post("/api/brief", json={}).status_code, 422)
        with mock.patch.object(consortium, "generate", side_effect=ConnectionError("No Ollama")):
            down = self.client.post("/api/brief", json={"query": "smoke"}).json()
        self.assertIn("ConnectionError", down["brief"]["error"])
        self.assertEqual([p["name"] for p in down["partners"]], ["WIEN"])


if __name__ == "__main__":
    unittest.main()
