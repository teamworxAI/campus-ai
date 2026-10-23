import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from campus_ai.research_assistant.cordis import (MAX_DESCRIPTION, call_topic, date, description_sections, html_text, number,
                                                 to_records, topic_detail_props)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_cordis", ROOT / "scripts" / "fetch_cordis.py")
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)

PROJECTS = [
    {"id": "101", "acronym": "SMOKE", "title": "Wildfire smoke and health", "status": "SIGNED", "startDate": "2023-01-01",
     "endDate": "2026-12-31", "totalCost": "1234,50", "ecMaxContribution": "1000,00", "topics": "HORIZON-CL1-2022-01",
     "masterCall": "HORIZON-CL1-2022", "fundingScheme": "HORIZON-RIA", "objective": "We study   smoke.\nAnd health.", "grantDoi": "10.3030/101"},
    {"id": "102", "acronym": "FISH", "title": "Salmon rivers", "status": "SIGNED", "startDate": "2022-06-01", "endDate": "",
     "totalCost": "", "ecMaxContribution": "", "topics": "HORIZON-CL6-2021-02", "masterCall": "", "fundingScheme": "HORIZON-CSA",
     "objective": "x" * 2000, "grantDoi": ""},
    {"id": "103", "acronym": "", "title": "", "objective": "no title: skipped"},
]
ORGS = [
    {"projectID": "101", "organisationID": "1", "name": "SIMON FRASER UNIVERSITY", "shortName": "SFU", "SME": "false", "activityType": "HES",
     "country": "CA", "city": "BURNABY", "organizationURL": "https://sfu.ca", "role": "participant", "ecContribution": "0"},
    {"projectID": "101", "organisationID": "2", "name": "UNIVERSITAET WIEN", "shortName": "UNIVIE", "SME": "false", "activityType": "HES",
     "country": "AT", "city": "WIEN", "organizationURL": "", "role": "coordinator", "ecContribution": "500,50"},
    {"projectID": "102", "organisationID": "2", "name": "UNIVERSITAET WIEN", "shortName": "UNIVIE", "SME": "false", "activityType": "HES",
     "country": "AT", "city": "WIEN", "organizationURL": "", "role": "participant", "ecContribution": "10"},
    {"projectID": "103", "organisationID": "9", "name": "GHOST", "country": "XX", "role": "participant"},
]
ESV = [
    {"euroSciVocCode": "/1/2", "euroSciVocPath": "medical/public health", "euroSciVocTitle": "public health", "projectID": "101"},
    {"euroSciVocCode": "/1/3", "euroSciVocPath": "natural/ecology", "euroSciVocTitle": "ecology", "projectID": "102"},
    {"euroSciVocCode": "/1/3", "euroSciVocPath": "natural/ecology", "euroSciVocTitle": "ecology", "projectID": "101"},
    {"euroSciVocCode": "/9/9", "euroSciVocPath": "x", "euroSciVocTitle": "orphan", "projectID": "103"},
]
TOPICS = [{"topic": "HORIZON-CL1-2022-01", "title": "Smoke topic", "projectID": "101"},
          {"topic": "HORIZON-CL6-2021-02", "title": "Rivers topic", "projectID": "102"}]
LEGAL = [{"legalBasis": "HORIZON.2.1", "title": "Health", "uniqueProgrammePart": "true", "projectID": "101"},
         {"legalBasis": "HORIZON.2.6", "title": "Food, Bioeconomy", "uniqueProgrammePart": "true", "projectID": "102"},
         {"legalBasis": "HORIZON.2", "title": "Pillar II", "uniqueProgrammePart": "false", "projectID": "102"}]
GRANTS = [
    {"type": 1, "identifier": "HORIZON-CL1-2022-01", "title": "Smoke topic", "callIdentifier": "HORIZON-CL1-2022", "callTitle": "Health call",
     "deadlineDatesLong": [1650000000000], "plannedOpeningDateLong": 1640000000000, "frameworkProgramme": {"abbreviation": "HORIZON"},
     "programmeDivision": [{"abbreviation": "HORIZON"}, {"abbreviation": "HORIZON.2.1"}], "status": {"abbreviation": "Closed"},
     "topicActions": [{"abbreviation": "HORIZON-RIA"}], "tags": ["air quality"], "keywords": ["wildfire"]},
    {"type": 1, "identifier": "HORIZON-CL1-2026-05", "title": "Future smoke", "callIdentifier": "HORIZON-CL1-2026", "callTitle": "Health 2026",
     "deadlineDatesLong": [1780000000000], "frameworkProgramme": {"abbreviation": "HORIZON"},
     "programmeDivision": [{"abbreviation": "HORIZON.2.1"}], "status": {"abbreviation": "Forthcoming"}, "tags": [], "keywords": []},
    {"type": 1, "identifier": "ERASMUS-X", "title": "Not Horizon", "frameworkProgramme": {"abbreviation": "ERASMUS2027"}, "status": {"abbreviation": "Open"}},
    {"type": 2, "identifier": "HORIZON-TENDER", "title": "A tender", "frameworkProgramme": {"abbreviation": "HORIZON"}, "status": {"abbreviation": "Open"}},
]


class MappingTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(number("2073781,25"), 2073781.25)
        self.assertEqual(number(""), 0.0)
        self.assertEqual(date(1650000000000), "2022-04-15")
        self.assertEqual(date(None), "")
        self.assertIsNone(call_topic(GRANTS[2]))
        self.assertIsNone(call_topic(GRANTS[3]))
        topic = call_topic(GRANTS[0])
        self.assertEqual(topic["id"], "topic:HORIZON-CL1-2022-01")
        self.assertEqual(topic["content"], "HORIZON-CL1-2022-01: Smoke topic. Call: Health call. Keywords: wildfire; air quality.")
        self.assertEqual(topic["props"]["deadlines"], ["2022-04-15"])
        self.assertEqual(topic["props"]["url"], "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/horizon-cl1-2022-01")

    def test_records(self):
        records = to_records(PROJECTS, ORGS, ESV, TOPICS, LEGAL, GRANTS)
        nodes = {r["id"]: r for r in records if "label" in r}
        links = [r for r in records if "src" in r]
        self.assertEqual(sorted(n["label"] for n in nodes.values()),
                         ["CallTopic", "CallTopic", "CallTopic", "Cluster", "Cluster", "Organization", "Organization", "Project", "Project", "Topic", "Topic"])
        self.assertNotIn("cordis:103", nodes)  # untitled: skipped, with its organisation and term
        self.assertNotIn("cordis:org:9", nodes)
        self.assertNotIn("esv:/9/9", nodes)
        smoke = nodes["cordis:101"]
        self.assertEqual(smoke["content"], "SMOKE: Wildfire smoke and health\nWe study smoke. And health.")
        self.assertEqual((smoke["props"]["total_cost"], smoke["props"]["ec_contribution"]), (1234.5, 1000.0))
        self.assertEqual(smoke["props"]["countries"], ["AT", "CA"])
        self.assertEqual((smoke["props"]["participants"], smoke["props"]["topic"], smoke["props"]["url"]),
                         (2, "HORIZON-CL1-2022-01", "https://cordis.europa.eu/project/id/101"))
        self.assertEqual(len(nodes["cordis:102"]["content"]), len("FISH: Salmon rivers\n") + 1500)
        wien = nodes["cordis:org:2"]
        self.assertEqual(wien["content"], "UNIVERSITAET WIEN (AT, higher education). Fields: ecology; public health. Horizon Europe projects: SMOKE, FISH.")
        self.assertEqual((wien["props"]["projects"], wien["props"]["fields"], wien["props"]["sme"]), (2, ["ecology", "public health"], False))
        self.assertEqual(nodes["cordis:org:1"]["props"]["country"], "CA")
        self.assertEqual(nodes["esv:/1/2"]["content"], "public health (medical/public health)")
        self.assertEqual(nodes["horizon:HORIZON.2.1"]["content"], "Horizon Europe HORIZON.2.1: Health")
        self.assertEqual(nodes["topic:HORIZON-CL6-2021-02"]["content"], "HORIZON-CL6-2021-02: Rivers topic")  # from topics.csv, not in the grants file
        self.assertEqual(nodes["topic:HORIZON-CL1-2026-05"]["props"]["status"], "Forthcoming")

        def of(kind):
            return sorted((l["src"], l["dst"], l.get("props", {})) for l in links if l["type"] == kind)
        self.assertEqual(of("PARTICIPATED_IN"), [
            ("cordis:org:1", "cordis:101", {"role": "participant", "ec_contribution": 0.0}),
            ("cordis:org:2", "cordis:101", {"role": "coordinator", "ec_contribution": 500.5}),
            ("cordis:org:2", "cordis:102", {"role": "participant", "ec_contribution": 10.0})])
        self.assertEqual(of("ABOUT"), [("cordis:101", "esv:/1/2", {}), ("cordis:101", "esv:/1/3", {}), ("cordis:102", "esv:/1/3", {})])
        self.assertEqual(of("UNDER_TOPIC"), [("cordis:101", "topic:HORIZON-CL1-2022-01", {}), ("cordis:102", "topic:HORIZON-CL6-2021-02", {})])
        self.assertEqual(of("FUNDED_UNDER"), [("cordis:101", "horizon:HORIZON.2.1", {}), ("cordis:102", "horizon:HORIZON.2.6", {})])
        self.assertEqual(of("PART_OF"), [("topic:HORIZON-CL1-2022-01", "horizon:HORIZON.2.1", {}), ("topic:HORIZON-CL1-2026-05", "horizon:HORIZON.2.1", {})])
        for link in links:
            self.assertIn(link["src"], nodes, link)
            self.assertIn(link["dst"], nodes, link)
        json.dumps(records)


DETAIL = {
    "identifier": "HORIZON-CL1-2026-05", "title": "Future smoke",
    "description": ('<p class="topicdescriptionkind">Expected Outcome:</p><p>Projects are expected to contribute to:</p>'
                    '<ul><li data-list="bullet"><span class="ql-ui"></span>Better <strong>exposure</strong> models &amp; data.</li>'
                    '<li>Health systems ready for smoke.</li></ul>'
                    '<p class="topicdescriptionkind">Scope:</p><p>Proposals should   bring clinicians and SMEs together.</p>'
                    '<p class="topicdescriptionkind">null</p><div><p>The budget is EUR 9 million.</p></div>'),
    "actions": [{"types": [{"typeOfAction": "HORIZON-RIA HORIZON Research and Innovation Actions"}]}],
    "budgetOverviewJSONItem": {"budgetTopicActionMap": {"1": [
        {"action": "HORIZON-CL1-2026-05 - HORIZON-RIA HORIZON Research and Innovation Actions", "budgetYearMap": {"2026": "6000000", "2027": "3000000"},
         "expectedGrants": 3},
        {"action": "HORIZON-CL1-2026-99 - another topic of the call", "budgetYearMap": {"2026": "1"}, "expectedGrants": 9}]}},
    "conditions": ('<div><h4>General conditions</h4><div><h4>1. Admissibility Conditions</h4><p>described in Annex A</p></div>'
                   '<div><h4>2. Eligible Countries</h4><p>described in Annex B of the Work Programme General Annexes.</p></div>'
                   '<div><h4>3. Other Eligible Conditions</h4><p>Clinical partners from at least two countries must take part.</p>'
                   '<p>If projects use satellite-based earth observation, beneficiaries must make use of Copernicus.</p></div>'
                   '<div><h4>5a. Evaluation and award</h4><p>Award criteria are in the annexes.</p></div></div>'),
}


class TopicDetailTests(unittest.TestCase):
    def test_html_text(self):
        self.assertEqual(html_text("<p>One &amp; <b>two</b></p><ul><li>a</li><li>b</li></ul><p>﻿</p>"), "One & two\n- a\n- b")
        self.assertEqual(html_text(None), "")

    def test_sections_and_props(self):
        sections = description_sections(DETAIL["description"])
        self.assertEqual(sections["Expected outcome"], "Projects are expected to contribute to:\n- Better exposure models & data.\n- Health systems ready for smoke.")
        self.assertEqual(sections["Scope"], "Proposals should bring clinicians and SMEs together.")
        self.assertNotIn("null", sections)
        self.assertEqual(description_sections("<p>No headings at all.</p>"), {"Scope": "No headings at all."})
        props = topic_detail_props(DETAIL)
        self.assertEqual((props["budget"], props["expected_grants"]), (9000000.0, 3))  # the other topic's line is not counted
        self.assertEqual(props["action_type"], "HORIZON-RIA HORIZON Research and Innovation Actions")
        self.assertEqual(props["conditions"], "Clinical partners from at least two countries must take part.")
        # Keys are always written, so re-indexing clears values a topic page no longer has.
        self.assertEqual(topic_detail_props({"identifier": "X", "actions": [{"types": [{"typeOfAction": "HORIZON-RIA HORIZON  Research"}]}]}),
                         {"expected_outcome": "", "scope": "", "action_type": "HORIZON-RIA HORIZON Research", "budget": 0.0,
                          "expected_grants": 0, "conditions": ""})

    def test_call_topic_with_and_without_details(self):
        plain = call_topic(GRANTS[1])
        self.assertEqual(plain["content"], "HORIZON-CL1-2026-05: Future smoke. Call: Health 2026.")
        self.assertNotIn("scope", plain["props"])
        rich = call_topic(GRANTS[1], DETAIL)
        self.assertEqual(rich["content"], "HORIZON-CL1-2026-05: Future smoke. Call: Health 2026.\n"
                                          "Expected outcome: Projects are expected to contribute to:\n- Better exposure models & data.\n"
                                          "- Health systems ready for smoke.\nScope: Proposals should bring clinicians and SMEs together.")
        self.assertEqual(rich["props"]["scope"], "Proposals should bring clinicians and SMEs together.")
        self.assertEqual(call_topic(GRANTS[0])["props"]["keywords"], ["wildfire", "air quality"])
        records = to_records(PROJECTS, ORGS, ESV, TOPICS, LEGAL, GRANTS, {"HORIZON-CL1-2026-05": DETAIL})
        topic = next(r for r in records if r.get("id") == "topic:HORIZON-CL1-2026-05")
        self.assertIn("Scope: Proposals should", topic["content"])
        json.dumps(records)

    def test_description_is_capped(self):
        long = {**DETAIL, "description": '<p class="topicdescriptionkind">Expected Outcome:</p><p>' + "word " * 2000 + "</p>"
                                         '<p class="topicdescriptionkind">Scope:</p><p>' + "scope " * 2000 + "</p>"}
        node = call_topic(GRANTS[1], long)
        head = "HORIZON-CL1-2026-05: Future smoke. Call: Health 2026.\n"
        self.assertEqual(len(node["content"]), len(head) + MAX_DESCRIPTION)
        self.assertLessEqual(len(node["props"]["scope"]), MAX_DESCRIPTION)


def csv_text(rows, columns):
    out = io.StringIO()
    out.write(";".join(columns) + "\n")
    for row in rows:
        out.write(";".join('"' + str(row.get(c, "")).replace('"', '""') + '"' for c in columns) + "\n")
    return out.getvalue()


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FetchTests(unittest.TestCase):
    def test_reads_the_bundle_and_writes_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "cordis" / "horizon"
            folder.mkdir(parents=True)
            with zipfile.ZipFile(folder / "cordis-HORIZONprojects-csv.zip", "w") as z:
                z.writestr("project.csv", csv_text(PROJECTS, ["id", "acronym", "title", "status", "startDate", "endDate", "totalCost",
                                                              "ecMaxContribution", "topics", "masterCall", "fundingScheme", "objective", "grantDoi"]))
                z.writestr("organization.csv", csv_text(ORGS, ["projectID", "organisationID", "name", "shortName", "SME", "activityType",
                                                               "country", "city", "organizationURL", "role", "ecContribution"]))
                z.writestr("euroSciVoc.csv", csv_text(ESV, ["euroSciVocCode", "euroSciVocPath", "euroSciVocTitle", "projectID"]))
                z.writestr("topics.csv", csv_text(TOPICS, ["topic", "title", "projectID"]))
                z.writestr("legalBasis.csv", csv_text(LEGAL, ["legalBasis", "title", "uniqueProgrammePart", "projectID"]))
            (folder / "grantsTenders.json").write_text(json.dumps({"fundingData": {"GrantTenderObj": GRANTS}}), encoding="utf-8")
            with mock.patch.object(fetcher.urllib.request, "urlopen") as urlopen, \
                 mock.patch.dict("os.environ", {"DATA_DIR": tmp}), mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(fetcher.main(["--max-projects", "1", "--topics", "none"]), 0)
            urlopen.assert_not_called()  # the files were there
            records = [json.loads(l) for l in (folder / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        ids = {r.get("id") for r in records if "label" in r}
        self.assertIn("cordis:101", ids)  # the most recently started project
        self.assertNotIn("cordis:102", ids)
        self.assertIn("kept cordis-HORIZONprojects-csv.zip", out.getvalue())
        self.assertIn("1 projects ->", out.getvalue())

    def test_topic_pages_are_fetched_cached_and_failures_skipped(self):
        items = GRANTS + [{**GRANTS[1], "identifier": "HORIZON-CL1-2026-06", "status": {"abbreviation": "Open"}},
                          {**GRANTS[1], "identifier": "HORIZON-CL1-2026-07", "status": {"abbreviation": "Open"}}]
        pages = {"horizon-cl1-2026-05": {"TopicDetails": DETAIL}, "horizon-cl1-2026-06": {"TopicDetails": {**DETAIL, "identifier": "HORIZON-CL1-2026-06"}}}

        def urlopen(request, timeout=None):
            self.assertEqual(request.get_header("User-agent"), fetcher.USER_AGENT)
            key = request.full_url.rsplit("/", 1)[1][:-5]
            if key not in pages:
                raise fetcher.urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            return Resp(json.dumps(pages[key]).encode())

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetcher.urllib.request, "urlopen", side_effect=urlopen) as opened, \
             mock.patch.object(fetcher.time, "sleep") as sleep, mock.patch("sys.stdout", io.StringIO()) as out:
            folder = Path(tmp) / "topics"
            counts = fetcher.fetch_topics(items, folder, fetcher.TOPIC_STATUS["current"])
            self.assertEqual(counts, {"fetched": 2, "kept": 0, "failed": 1})
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["HORIZON-CL1-2026-05.json", "HORIZON-CL1-2026-06.json"])
            self.assertEqual(opened.call_count, 3)  # the closed topic, the other programme and the tender are not asked for
            self.assertEqual(sleep.call_count, 2)  # sequential, with a pause between requests
            self.assertIn("skipped HORIZON-CL1-2026-07: HTTPError", out.getvalue())
            again = fetcher.fetch_topics(items, folder, fetcher.TOPIC_STATUS["open"])  # cache hit for 06; 07 tried again
            self.assertEqual(again, {"fetched": 0, "kept": 1, "failed": 1})
            (folder / "BROKEN.json").write_text("{not json", encoding="utf-8")
            details = fetcher.topic_details(folder)
        self.assertEqual(sorted(details), ["HORIZON-CL1-2026-05", "HORIZON-CL1-2026-06"])
        self.assertEqual(fetcher.topic_details(Path(tmp) / "missing"), {})

    def test_download_streams_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetcher.urllib.request, "urlopen", return_value=Resp(b"PK..." * 10)), \
             mock.patch("sys.stdout", io.StringIO()):
            target = Path(tmp) / "bundle.zip"
            fetcher.download("https://example.org/bundle.zip", target, force=False)
            self.assertEqual(target.read_bytes(), b"PK..." * 10)


if __name__ == "__main__":
    unittest.main()
