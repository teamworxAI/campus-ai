import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from campus_ai.research_assistant import api as api_module
from campus_ai.research_assistant.api import create_app
from campus_ai.research_assistant.call_analyst import partner_query
from campus_ai.research_assistant.complementarity import assess, complement, details, needs, roles_filled, roles_needed, stems

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = {
    "id": "topic:HORIZON-MISS-2027-03-OCEAN-01", "identifier": "HORIZON-MISS-2027-03-OCEAN-01", "title": "Coastal resilience",
    "url": "https://ec.europa.eu/x", "action": "HORIZON-IA", "parts": ["HORIZON.2.6"], "keywords": ["wetlands"],
    "topics": [{"text": "Coastal resilience solutions", "span": "solutions for coastal resilience"},
               {"text": "Nature based solutions", "span": "nature based soutions"}],
    "partner_profile": [{"text": "public authority managing coastal areas", "span": "relevant public authorities managing those areas"},
                        {"text": "SME for exploitation", "span": "SMEs to exploit the results"},
                        {"text": "marine biodiversity monitoring", "span": "monitoring of marine biodiversity"}],
}


def org(id_, name, country, activity, projects, score):
    return {"id": id_, "name": name, "country": country, "activity": activity, "city": "", "url": "", "fields": [],
            "projects_total": 4, "score": score, "evidence": {"projects": projects}}


def proj(id_, acronym, title, role="participant"):
    return {"id": id_, "acronym": acronym, "title": title, "url": "", "role": role, "start": "", "score": 0.1}


SHORTLIST = [
    org("cordis:org:1", "UNIVERSIDADE DE AVEIRO", "PT", "higher education", [proj("cordis:1", "COAST", "Coastal ports", "coordinator")], 0.9),
    org("cordis:org:2", "UNIVERSIDADE DO PORTO", "PT", "higher education", [proj("cordis:1", "COAST", "Coastal ports")], 0.8),
    org("cordis:org:3", "OBSHTINA BURGAS", "BG", "public body", [proj("cordis:2", "NBS", "Nature-based solutions in cities")], 0.7),
    org("cordis:org:4", "SEASENSE SL", "ES", "company", [proj("cordis:3", "MARMON", "Sensors at sea")], 0.6),
    org("cordis:org:5", "BIG MARINE AG", "DE", "company", [proj("cordis:3", "MARMON", "Sensors at sea")], 0.5),
]
INFO = {"projects": {"cordis:1": {"text": "COAST: Coastal ports\nResilience solutions for harbours.", "terms": ["coastal engineering"]},
                     "cordis:2": {"text": "NBS: Nature-based solutions in cities", "terms": ["wetlands"]},
                     "cordis:3": {"text": "MARMON: Sensors at sea\nMonitoring marine biodiversity.", "terms": []}},
        "orgs": {"cordis:org:1": {"sme": False, "coordinated": 7}, "cordis:org:4": {"sme": True, "coordinated": 0}}}


class Record(dict):
    def data(self):
        return dict(self)


class ScorerTests(unittest.TestCase):
    def test_stems_and_needs(self):
        self.assertEqual(stems("Soils and the soil; Nature-based AI"), ["soil", "natur", "ai"])
        self.assertEqual([(n["text"], n["source"]) for n in needs(ANALYSIS)],
                         [("Coastal resilience solutions", "topic"), ("Nature based solutions", "topic"),
                          ("marine biodiversity monitoring", "expertise"), ("wetlands", "keyword")])

    def test_roles(self):
        asked, expertise = roles_needed(ANALYSIS)
        self.assertEqual([r["role"] for r in asked], ["public authority as end user", "SME for exploitation"])
        self.assertEqual([e["text"] for e in expertise], ["marine biodiversity monitoring"])
        self.assertEqual(roles_filled({"activity": "company", "sme": True}), ["SME for exploitation", "industry partner"])
        self.assertEqual(roles_filled({"activity": "company"}), ["industry partner"])
        self.assertEqual(roles_filled({"activity": "higher education", "name": "Charité Universitätsmedizin"}), ["clinical partner", "university"])
        self.assertEqual(roles_filled({"activity": "public body", "name": "Obshtina Burgas"}), ["public authority as end user"])

    def test_assess_coverage_roles_countries(self):
        out = assess(SHORTLIST, ANALYSIS, INFO)
        by = {p["id"]: p for p in out["partners"]}
        self.assertEqual(by["cordis:org:1"]["covers"], [{"text": "Coastal resilience solutions", "source": "topic", "projects": ["cordis:1"]}])
        self.assertEqual([c["text"] for c in by["cordis:org:3"]["covers"]], ["Nature based solutions", "wetlands"])
        self.assertEqual(by["cordis:org:3"]["roles"], ["public authority as end user"])
        self.assertEqual(by["cordis:org:4"]["roles"], ["SME for exploitation"])
        self.assertEqual((by["cordis:org:5"]["roles"], by["cordis:org:5"]["other_roles"]), ([], ["industry partner"]))
        self.assertEqual((by["cordis:org:1"]["coordinator_of"], by["cordis:org:1"]["coordinated"]), (["cordis:1"], 7))
        self.assertEqual(out["set"]["uncovered"], [])
        self.assertEqual(out["set"]["roles_unfilled"], [])
        self.assertEqual(out["set"]["countries"], {"PT": ["cordis:org:1", "cordis:org:2"], "BG": ["cordis:org:3"],
                                                   "ES": ["cordis:org:4"], "DE": ["cordis:org:5"]})
        self.assertEqual(by["cordis:org:1"]["adds"],
                         'UNIVERSIDADE DE AVEIRO adds: covers "Coastal resilience solutions" [cordis:1]; brings country PT [cordis:org:1]; '
                         "coordinated [cordis:1] (7 Horizon Europe projects coordinated in all).")

    def test_uncovered_and_unfilled(self):
        out = assess(SHORTLIST[:2], ANALYSIS, INFO)
        self.assertEqual(out["set"]["uncovered"], ["Nature based solutions", "marine biodiversity monitoring", "wetlands"])
        self.assertEqual(out["set"]["roles_unfilled"], ["public authority as end user", "SME for exploitation"])

    def test_every_adds_clause_cites_an_id(self):
        out = assess(SHORTLIST, ANALYSIS, INFO)
        picked = complement(SHORTLIST, ANALYSIS, 3, INFO)["picked"]
        for line in [p["adds"] for p in out["partners"]] + [p["adds"] for p in picked]:
            body = line.split(" adds: ", 1)[1]
            for clause in body.rstrip(".").split("; "):
                self.assertRegex(clause, r"\[cordis:[^\]]+\]", line)
        for p in out["partners"] + picked:
            for cited in re.findall(r"\[([^\]]+)\]", p["adds"]):
                self.assertIn(cited, p["cites"])

    def test_long_lines_are_capped_but_still_cite(self):
        wide = {**ANALYSIS, "keywords": ["coastal ports", "harbours", "coastal engineering", "resilience solutions"]}
        partner = assess(SHORTLIST[:1], wide, INFO)["partners"][0]
        self.assertEqual(len(partner["covers"]), 5)
        self.assertEqual(partner["covers"][0]["text"], "Coastal resilience solutions")  # analysis topics before keywords
        self.assertIn('; and 1 more need(s) [cordis:1];', partner["adds"])

    def test_greedy_pick_and_tie_break(self):
        result = complement(SHORTLIST, ANALYSIS, 3, INFO)
        picked = result["picked"]
        # Burgas adds two needs, a role and a country; SeaSense a need, a role and a country; then Aveiro and Porto tie
        # (one need and PT each) and the higher-ranked Aveiro wins.
        self.assertEqual([(p["id"], p["rank"], p["gain"]) for p in picked],
                         [("cordis:org:3", 3, 4), ("cordis:org:4", 4, 3), ("cordis:org:1", 1, 2)])
        self.assertEqual(result["set"]["uncovered"], [])
        self.assertEqual(result["set"]["roles_unfilled"], [])
        self.assertTrue(result["eligibility"]["ok"])
        self.assertEqual(result["eligibility"]["eligible_countries"], ["BG", "CA", "ES", "PT"])
        # Once a need is covered, the next partner's line says only what is new.
        later = complement(SHORTLIST[:2], ANALYSIS, 2, INFO)["picked"]
        self.assertEqual([p["id"] for p in later], ["cordis:org:1", "cordis:org:2"])
        self.assertEqual(later[1]["adds"], "UNIVERSIDADE DO PORTO adds: nothing new to this set.")

    def test_details_is_one_query(self):
        calls = []

        class Research:
            def run(self, query, **params):
                calls.append((query, params))
                return [Record(org="cordis:org:4", sme=True, coordinated=2, project="cordis:3", text="MARMON", terms=["oceanography", None]),
                        Record(org="cordis:org:9", sme=None, coordinated=0, project=None, text=None, terms=[])]

        info = details(Research(), SHORTLIST[3:4])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {"orgs": ["cordis:org:4"], "projects": ["cordis:3"]})
        self.assertEqual(info, {"projects": {"cordis:3": {"text": "MARMON", "terms": ["oceanography"]}},
                                "orgs": {"cordis:org:4": {"sme": True, "coordinated": 2}, "cordis:org:9": {"sme": False, "coordinated": 0}}})
        self.assertEqual(details(Research(), []), {"projects": {}, "orgs": {}})


class FakeResearch:
    def __init__(self):
        self.asked = []

    def call(self, call_id):
        return {"id": call_id, "identifier": call_id.split(":", 1)[1], "title": "Coastal resilience"} if call_id == ANALYSIS["id"] else None

    def partners(self, query, k=10, countries="associated", **kw):
        self.asked.append((query, k, countries))
        return [dict(p) for p in SHORTLIST][:k]

    def run(self, query, **params):
        return [Record(org=o, project=None, sme=v["sme"], coordinated=v["coordinated"], text=None, terms=[]) for o, v in INFO["orgs"].items()] + \
            [Record(org="cordis:org:1", sme=False, coordinated=7, project=p, text=v["text"], terms=v["terms"]) for p, v in INFO["projects"].items()]

    def counts(self):
        return {}


class EndpointTests(unittest.TestCase):
    def client(self, research):
        return TestClient(create_app(service=mock.Mock(count=lambda: 0), research=research))

    def test_complement_endpoint(self):
        research = FakeResearch()
        client = self.client(research)
        with mock.patch.object(api_module, "analyse", return_value=dict(ANALYSIS)) as analysed:
            data = client.get("/api/partners/complement", params={"call": ANALYSIS["id"], "n": 2}).json()
            again = client.get("/api/partners/complement", params={"call": ANALYSIS["id"], "q": "my own words"}).json()
        self.assertEqual(analysed.call_count, 1)  # the analysis is cached per process
        self.assertEqual((data["analysis_cached"], again["analysis_cached"]), (False, True))
        self.assertEqual(research.asked[0], (partner_query(ANALYSIS), 10, "associated"))  # the analysis's own partner query
        self.assertEqual(research.asked[1][0], "my own words")
        self.assertEqual(data["call"]["identifier"], ANALYSIS["identifier"])
        self.assertEqual(len(data["partners"]), 5)
        self.assertEqual([p["id"] for p in data["complementary"]["picked"]], ["cordis:org:3", "cordis:org:4"])
        self.assertIn("eligibility", data["complementary"])
        self.assertEqual(client.get("/api/partners/complement", params={"call": "topic:nope"}).status_code, 404)
        self.assertEqual(client.get("/api/partners/complement", params={"call": ANALYSIS["id"], "countries": "mars"}).status_code, 422)

    def test_web_app_reads_the_fields_the_endpoint_returns(self):
        client = self.client(FakeResearch())
        with mock.patch.object(api_module, "analyse", return_value=dict(ANALYSIS)):
            data = client.get("/api/partners/complement", params={"call": ANALYSIS["id"]}).json()
        script = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
        body = script[script.index("async function whatEachAdds"):script.index("// One Ask box")]
        self.assertIn("/api/partners/complement?call=${encodeURIComponent(callId)}", body)
        self.assertEqual(sorted(set(re.findall(r"\bc\.([a-z_]+)", body)) - set(data)), [])
        self.assertEqual(sorted(set(re.findall(r"\bc\.complementary\.([a-z_]+)", body)) - set(data["complementary"])), [])
        self.assertEqual(sorted(set(re.findall(r"\bs\.([a-z_]+)", body)) - set(data["set"])), [])
        self.assertEqual(sorted(set(re.findall(r"\bel\.([a-z_]+)", body)) - set(data["complementary"]["eligibility"])), [])
        self.assertEqual(sorted(set(re.findall(r"\bp\.([a-z_]+)", body)) - set(data["partners"][0]) - set(data["complementary"]["picked"][0])), [])
        nginx = (ROOT / "web" / "nginx.conf").read_text(encoding="utf-8")
        self.assertRegex(nginx, r"location /api/partners/complement \{\s*proxy_pass \$api;\s*proxy_read_timeout 900s;")


if __name__ == "__main__":
    unittest.main()
