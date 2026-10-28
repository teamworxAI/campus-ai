import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from campus_ai.core.llm import LLMResponse
from campus_ai.research_assistant import router
from campus_ai.research_assistant.api import create_app
from campus_ai.research_assistant.router import answer, route

ROOT = Path(__file__).resolve().parents[1]


def reply(text):
    return LLMResponse(text, "gemma4:e2b", 120, 1, "stop")


class RuleTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(router, "generate", side_effect=AssertionError("a rule should have fired"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, text, journey, rule, query=None):
        routed = route(text)
        self.assertEqual(routed["journey"], journey, text)
        self.assertEqual(routed["why"], f"rule: {rule}")
        if query is not None:
            self.assertEqual(routed["query"], query)

    def test_journey_1_partners_for_a_call(self):
        self.check("Find partners for HORIZON-MISS-2027-03-OCEAN-01", 1, "Horizon topic identifier", "HORIZON-MISS-2027-03-OCEAN-01")
        self.check("We need a partner for the coastal resilience call", 1, "call and partner")

    def test_journey_2_calls(self):
        self.check("Which calls fit our soil microbiome lab?", 2, "which calls or funding", "Which calls fit our soil microbiome lab")
        self.check("EU funding for wildfire smoke research", 2, "which calls or funding")

    def test_journey_3_consortium(self):
        self.check("Draft a consortium for HORIZON-MISS-2027-05-SOIL-04-two-stage", 3, "consortium or brief",
                   "HORIZON-MISS-2027-05-SOIL-04-two-stage")

    def test_journey_4_experts(self):
        self.check("Who at SFU works on wildfire smoke and health?", 4, "expert, supervisor or who works on")
        self.check("I need a supervisor in marine ecology", 4, "expert, supervisor or who works on", "supervisor in marine ecology")

    def test_journey_5_collections(self):
        self.check("historical images of salmon fishing", 5, "sources, images or collections")


class ModelTests(unittest.TestCase):
    def test_ambiguous_goes_to_the_model(self):
        with mock.patch.object(router, "generate", return_value=reply("2")) as gen:
            routed = route("salmon habitat restoration in British Columbia")
        self.assertEqual(routed["journey"], 2)
        self.assertEqual(routed["why"], "no rule fired; model gemma4:e2b")
        self.assertEqual(gen.call_args.kwargs["task"], "classification")
        self.assertEqual(gen.call_args.kwargs["data_class"], "I")
        self.assertIn("one digit from 1 to 5", gen.call_args.kwargs["system"])

    def test_garbage_and_errors_fall_back(self):
        for answer_text in ("I think 3 or 4", "", "7", "journey: three"):
            with mock.patch.object(router, "generate", return_value=reply(answer_text)):
                routed = route("salmon habitat restoration")
            self.assertEqual(routed["journey"], router.DEFAULT, answer_text)
            self.assertIn("model answer not a journey", routed["why"])
            self.assertIn("default journey 4", routed["why"])
        with mock.patch.object(router, "generate", return_value=reply(" 5.\n")):
            self.assertEqual(route("salmon habitat restoration")["journey"], 5)
        with mock.patch.object(router, "generate", side_effect=ConnectionError("no Ollama")):
            routed = route("salmon habitat restoration")
        self.assertEqual(routed["journey"], 4)
        self.assertIn("model unavailable (ConnectionError)", routed["why"])


class FakeResearch:
    CALL = {"id": "topic:HORIZON-MISS-2027-03-OCEAN-01", "identifier": "HORIZON-MISS-2027-03-OCEAN-01", "title": "Coastal resilience",
            "call_title": "Ocean mission 2027", "status": "Forthcoming", "deadlines": ["2027-09-21"], "url": "https://ec.europa.eu/x"}

    def __init__(self):
        self.asked = []

    def call(self, call_id):
        return dict(self.CALL) if call_id == self.CALL["id"] else None

    def partners(self, query, k=10, countries="associated", **kw):
        self.asked.append(("partners", query))
        return [{"id": "cordis:org:1", "name": "AVEIRO"}]

    def calls(self, query, k=10, status="open"):
        self.asked.append(("calls", query))
        return [{"id": self.CALL["id"]}]

    def experts(self, query, k=10):
        self.asked.append(("experts", query))
        return [{"id": "openalex:A1", "name": "Ryan Allen"}]

    def counts(self):
        return {}


class Card:
    def __init__(self, id_):
        self.id = id_

    def public(self):
        return {"id": self.id}


class FakeCollections:
    def pictures(self, query, k):
        return [Card("europeana:1")]

    def texts(self, query, k):
        return [Card("europeana:2")]

    def count(self):
        return 2


class AnswerTests(unittest.TestCase):
    def test_answer_runs_the_journey_search(self):
        research = FakeResearch()
        with mock.patch.object(router, "generate", side_effect=AssertionError("no model")):
            one = answer("partners for HORIZON-MISS-2027-03-OCEAN-01", research)
            unknown = answer("partners for HORIZON-CL9-2099-01", research)
            two = answer("Which calls fit wildfire smoke research?", research)
            four = answer("Who works on salmon genomics?", research)
            five = answer("archive photos of canneries", research, FakeCollections())
        self.assertEqual((one["journey"], one["call"]["id"], one["search"]), (1, FakeResearch.CALL["id"], "Coastal resilience. Ocean mission 2027"))
        self.assertEqual(one["partners"][0]["id"], "cordis:org:1")
        self.assertEqual((unknown["search"], "call" in unknown), ("partners for HORIZON-CL9-2099-01", False))
        self.assertEqual((two["journey"], two["calls"][0]["id"]), (2, FakeResearch.CALL["id"]))
        self.assertEqual(four["experts"][0]["name"], "Ryan Allen")
        self.assertEqual((five["journey"], five["pictures"], five["texts"]), (5, [{"id": "europeana:1"}], [{"id": "europeana:2"}]))
        self.assertEqual(research.asked[2], ("calls", "Which calls fit wildfire smoke research"))


class EndpointTests(unittest.TestCase):
    def test_ask_endpoint_and_web_app_fields(self):
        client = TestClient(create_app(service=FakeCollections(), research=FakeResearch()))
        with mock.patch.object(router, "generate", return_value=reply("4")):
            data = client.get("/api/ask", params={"q": "salmon habitat restoration"}).json()
            consortium = client.get("/api/ask", params={"q": "draft a consortium for HORIZON-MISS-2027-03-OCEAN-01"}).json()
        self.assertEqual((data["journey"], data["why"]), (4, "no rule fired; model gemma4:e2b"))
        self.assertEqual(data["experts"][0]["id"], "openalex:A1")
        self.assertEqual((consortium["journey"], consortium["call"]["id"]), (3, FakeResearch.CALL["id"]))
        self.assertEqual(client.get("/api/ask").status_code, 422)
        script = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
        body = script[script.index("async function renderAsk"):script.index("function setNav")]
        self.assertIn('api("/api/ask?q=" + encodeURIComponent(q))', body)
        used = set(re.findall(r"\bd\.([a-z_]+)", body))
        self.assertEqual(sorted(used - set(data) - set(consortium) - {"pictures", "texts"}), [])  # pictures and texts on journey 5
        self.assertIn("Routed to: journey ${d.journey}", body)
        self.assertIn("#/ask", (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
