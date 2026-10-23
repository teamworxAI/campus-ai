import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from campus_ai.research_assistant.cordis import call_topic, date, number, to_records

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


def csv_text(rows, columns):
    out = io.StringIO()
    out.write(";".join(columns) + "\n")
    for row in rows:
        out.write(";".join('"' + str(row.get(c, "")).replace('"', '""') + '"' for c in columns) + "\n")
    return out.getvalue()


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
                self.assertEqual(fetcher.main(["--max-projects", "1"]), 0)
            urlopen.assert_not_called()  # the files were there
            records = [json.loads(l) for l in (folder / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        ids = {r.get("id") for r in records if "label" in r}
        self.assertIn("cordis:101", ids)  # the most recently started project
        self.assertNotIn("cordis:102", ids)
        self.assertIn("kept cordis-HORIZONprojects-csv.zip", out.getvalue())
        self.assertIn("1 projects ->", out.getvalue())

    def test_download_streams_to_disk(self):
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetcher.urllib.request, "urlopen", return_value=Resp(b"PK..." * 10)), \
             mock.patch("sys.stdout", io.StringIO()):
            target = Path(tmp) / "bundle.zip"
            fetcher.download("https://example.org/bundle.zip", target, force=False)
            self.assertEqual(target.read_bytes(), b"PK..." * 10)


if __name__ == "__main__":
    unittest.main()
