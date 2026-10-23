import json
import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from campus_ai.core.llm import LLMResponse
from campus_ai.research_assistant import api as api_module
from campus_ai.research_assistant import call_analyst
from campus_ai.research_assistant.api import create_app
from campus_ai.research_assistant.call_analyst import analyse, check_spans, parse, partner_query

ROOT = Path(__file__).resolve().parents[1]
TEXT = ("HORIZON-CL1-2026-05: Wildfire smoke and health. Call: Health 2026. Keywords: wildfire; air quality.\n"
        "Expected outcome: Projects are expected to contribute to:\n- Better exposure models for wildfire smoke.\n"
        "- Health systems prepared for smoke events.\n"
        "Scope: Proposals should bring together clinicians, atmospheric scientists and SMEs for the exploitation of results.")
CALL = {"id": "topic:HORIZON-CL1-2026-05", "identifier": "HORIZON-CL1-2026-05", "title": "Wildfire smoke and health",
        "call_title": "Health 2026", "status": "Forthcoming", "opening": "2026-05-12", "deadlines": ["2026-09-16"],
        "url": "https://ec.europa.eu/x/horizon-cl1-2026-05", "actions": ["HORIZON-RIA"], "parts": ["HORIZON.2.1"],
        "clusters": ["Health"], "keywords": ["wildfire", "air quality"], "text": TEXT, "scope": "Proposals...",
        "action_type": "HORIZON-RIA HORIZON Research and Innovation Actions", "budget": 9000000.0, "expected_grants": 3,
        "conditions": "Clinical partners must take part."}
GOOD = {"topics": [{"text": "wildfire smoke exposure", "span": "Better exposure models for wildfire smoke"},
                   {"text": "health system preparedness", "span": "Health systems  prepared for smoke events."}],
        "expected_outcomes": [{"text": "Better exposure models", "span": "“Better exposure models for wildfire smoke”"}],
        "partner_profile": [{"text": "clinical partner", "span": "bring together clinicians"},
                            {"text": "SME for exploitation", "span": "SMEs for the exploitation of results"}]}


def answer(text, model="gemma4:e2b"):
    return LLMResponse(text, model, 900, 300, "stop")


class FactsTests(unittest.TestCase):
    def test_deterministic_part(self):
        with mock.patch.object(call_analyst, "generate", side_effect=ConnectionError("No Ollama")):
            result = analyse(CALL)
        self.assertEqual(result["action"], "HORIZON-RIA")
        self.assertIn("at least three independent legal entities", result["consortium_rule"])
        self.assertTrue(result["canada"].startswith("associated country"))
        self.assertEqual((result["budget"], result["expected_grants"], result["deadlines"]), (9000000.0, 3, ["2026-09-16"]))
        self.assertEqual((result["clusters"], result["keywords"]), (["Health"], ["wildfire", "air quality"]))
        self.assertTrue(result["described"])
        self.assertEqual(result["evidence"], {"id": CALL["id"], "url": CALL["url"]})
        self.assertIn("ConnectionError", result["model_error"])
        self.assertEqual((result["topics"], result["analysed_by"]), ([], None))

    def test_single_entity_and_outside_pillar_ii(self):
        with mock.patch.object(call_analyst, "generate", side_effect=ConnectionError("down")):
            erc = analyse({"id": "topic:ERC", "identifier": "ERC-1", "title": "Starting grants", "actions": [],
                           "action_type": "HORIZON-ERC HORIZON ERC Grants", "parts": ["HORIZON.1.1"]})
        self.assertEqual(erc["action"], "HORIZON-ERC")
        self.assertEqual(erc["consortium_rule"], "one legal entity established in a member state or associated country")
        self.assertTrue(erc["canada"].startswith("third country"))
        self.assertFalse(erc["described"])


class AnalystTests(unittest.TestCase):
    def test_good_json_kept_with_spans(self):
        reply = "```json\n" + json.dumps(GOOD) + "\n```"
        with mock.patch.object(call_analyst, "generate", return_value=answer(reply)) as gen:
            result = analyse(CALL)
        self.assertEqual(gen.call_args.kwargs["task"], "reasoning")
        self.assertEqual(gen.call_args.kwargs["data_class"], "P")
        self.assertIn(TEXT, gen.call_args.args[0][0]["content"])
        self.assertEqual([t["text"] for t in result["topics"]], ["wildfire smoke exposure", "health system preparedness"])
        self.assertEqual(result["expected_outcomes"], [{"text": "Better exposure models", "span": "Better exposure models for wildfire smoke"}])
        self.assertEqual([p["text"] for p in result["partner_profile"]], ["clinical partner", "SME for exploitation"])
        self.assertEqual((result["dropped"], result["analysed_by"]), (0, "gemma4:e2b"))
        self.assertNotIn("model_error", result)
        self.assertTrue(result["needs_review"])

    def test_fabricated_span_is_dropped_and_counted(self):
        bad = {**GOOD, "partner_profile": GOOD["partner_profile"] + [{"text": "space agency", "span": "partners from the European Space Agency"},
                                                                    {"text": "no quote at all"}, {"text": "too short", "span": "SMEs"}]}
        with mock.patch.object(call_analyst, "generate", return_value=answer("Here you go: " + json.dumps(bad))):
            result = analyse(CALL)
        self.assertEqual([p["text"] for p in result["partner_profile"]], ["clinical partner", "SME for exploitation"])
        self.assertEqual(result["dropped"], 3)
        self.assertEqual([d["text"] for d in result["dropped_items"]], ["space agency", "no quote at all", "too short"])

    def test_garbage_answer_sets_model_error(self):
        with mock.patch.object(call_analyst, "generate", return_value=answer("I think the call is about smoke.")):
            result = analyse(CALL)
        self.assertIn("not a JSON object", result["model_error"])
        self.assertEqual((result["topics"], result["analysed_by"]), ([], "gemma4:e2b"))
        self.assertEqual(result["consortium_rule"][:8], "at least")
        self.assertIsNone(parse("[1, 2]"))
        self.assertIsNone(parse("{broken"))

    def test_check_spans_tolerates_odd_shapes(self):
        kept, dropped = check_spans({"topics": "not a list", "partner_profile": [42, "bare string"]}, TEXT)
        self.assertEqual(kept, {"topics": [], "expected_outcomes": [], "partner_profile": []})
        self.assertEqual(dropped, [{"field": "partner_profile", "text": "bare string", "span": ""}])

    def test_partner_query(self):
        with mock.patch.object(call_analyst, "generate", return_value=answer(json.dumps(GOOD))):
            result = analyse(CALL)
        self.assertEqual(partner_query(result),
                         "wildfire smoke exposure; health system preparedness; clinical partner; SME for exploitation")
        self.assertEqual(partner_query({"title": "Wildfire smoke and health", "topics": [], "partner_profile": []}), "Wildfire smoke and health")


class FakeResearch:
    def call(self, call_id):
        return dict(CALL) if call_id == CALL["id"] else None

    def counts(self):
        return {}


class EndpointTests(unittest.TestCase):
    def test_analysis_endpoint_is_cached_and_404s(self):
        client = TestClient(create_app(service=mock.Mock(count=lambda: 0), research=FakeResearch()))
        fake = {"id": CALL["id"], "title": CALL["title"], "topics": [{"text": "smoke", "span": "wildfire smoke"}],
                "partner_profile": [{"text": "clinical partner", "span": "clinicians"}], "dropped": 0}
        with mock.patch.object(api_module, "analyse", return_value=dict(fake)) as analysed:
            first = client.get("/api/calls/topic%3AHORIZON-CL1-2026-05/analysis").json()
            second = client.get(f"/api/calls/{CALL['id']}/analysis").json()
        self.assertEqual(analysed.call_count, 1)
        self.assertEqual(analysed.call_args.args[0]["text"], TEXT)
        self.assertEqual((first["cached"], second["cached"]), (False, True))
        self.assertEqual(first["partner_query"], "smoke; clinical partner")
        self.assertEqual(client.get("/api/calls/topic:nope/analysis").status_code, 404)
        with mock.patch.object(api_module, "analyse", return_value={**fake, "id": "x", "model_error": "down"}) as failed:
            client2 = TestClient(create_app(service=mock.Mock(count=lambda: 0), research=FakeResearch()))
            client2.get(f"/api/calls/{CALL['id']}/analysis")
            self.assertFalse(client2.get(f"/api/calls/{CALL['id']}/analysis").json()["cached"])  # failures are not cached
        self.assertEqual(failed.call_count, 2)

    def test_web_app_reads_the_fields_the_api_returns(self):
        """app.js has no test runner: check that every field the analysis page reads exists in a real analysis."""
        with mock.patch.object(call_analyst, "generate", return_value=answer(json.dumps(GOOD))):
            result = analyse(CALL)
        result["partner_query"] = partner_query(result)
        script = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
        body = script[script.index("async function renderAnalysis"):script.index("async function renderJourney")]
        used = set(re.findall(r"\ba\.([a-z_]+)", body))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(result) - {"model_error"}), [])  # model_error only when the model failed
        self.assertIn("/api/calls/${encodeURIComponent(callId)}/analysis", body)
        self.assertIn('"#/partners?q=" + encodeURIComponent(a.partner_query)', body)
        nginx = (ROOT / "web" / "nginx.conf").read_text(encoding="utf-8")
        self.assertRegex(nginx, r"location ~ \^/api/calls/\[\^/\]\+/analysis\$ \{\s*proxy_pass \$api;\s*proxy_read_timeout 900s;")


if __name__ == "__main__":
    unittest.main()
