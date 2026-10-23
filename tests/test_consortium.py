import unittest
from unittest import mock

from campus_ai.core.llm import LLMResponse
from campus_ai.research_assistant import consortium
from campus_ai.research_assistant.consortium import brief, check_citations, eligibility, evidence_ids

CALL = {"id": "topic:HORIZON-CL1-2026-01", "identifier": "HORIZON-CL1-2026-01", "title": "Smoke and health", "call_title": "Health 2026",
        "status": "Open", "deadlines": ["2026-04-01"]}
PARTNERS = [
    {"id": "cordis:org:1", "name": "ISGLOBAL", "country": "ES", "activity": "research organisation", "fields": ["public health"],
     "evidence": {"projects": [{"id": "cordis:101", "acronym": "SIRENE", "title": "Exposure", "role": "participant"}]}},
    {"id": "cordis:org:2", "name": "OSLO MET", "country": "NO", "activity": "higher education", "fields": [],
     "evidence": {"projects": [{"id": "cordis:102", "acronym": "AIR", "title": "Air", "role": "coordinator"}]}},
]
HOME = {"name": "Simon Fraser University", "country": "CA"}


class EligibilityTests(unittest.TestCase):
    def test_ria_needs_three_countries_and_a_member_state(self):
        ok = eligibility([{"country": "ES"}, {"country": "NO"}, {"country": "DE"}], "HORIZON-RIA")
        self.assertTrue(ok["ok"])
        self.assertEqual((ok["member_states"], ok["eligible_countries"]), (["DE", "ES"], ["DE", "ES", "NO"]))
        short = eligibility([{"country": "ES"}, {"country": "ES"}, {"country": "NO"}], "HORIZON-IA")
        self.assertFalse(short["ok"])
        self.assertIn("only 2 different eligible countries", short["problems"][0])
        no_ms = eligibility([{"country": "NO"}, {"country": "CH"}, {"country": "UK"}], "HORIZON-RIA")
        self.assertIn("no member of an EU member state", no_ms["problems"])

    def test_canada_counts_in_pillar_ii_only(self):
        cluster = eligibility([{"country": "CA"}, {"country": "ES"}, {"country": "DE"}], "HORIZON-RIA", parts=["HORIZON.2.1"])
        self.assertTrue(cluster["ok"])
        self.assertIn(("CA", "associated country"), cluster["countries"])
        erc = eligibility([{"country": "CA"}, {"country": "ES"}, {"country": "DE"}], "HORIZON-RIA", parts=["HORIZON.3"])
        self.assertFalse(erc["ok"])
        self.assertIn(("CA", "third country (associated to Pillar II only)"), erc["countries"])
        self.assertTrue(any("do not count" in p for p in erc["problems"]))

    def test_single_entity_actions(self):
        self.assertTrue(eligibility([{"country": "DE"}], "HORIZON-CSA")["ok"])
        self.assertTrue(eligibility([{"country": "NO"}], "HORIZON-ERC")["ok"])
        alone = eligibility([{"country": "US"}], "HORIZON-CSA")
        self.assertFalse(alone["ok"])
        self.assertIn("no member in a member state or associated country", alone["problems"])


class CitationTests(unittest.TestCase):
    def test_sentences_with_unknown_ids_are_dropped(self):
        allowed = evidence_ids(CALL, PARTNERS)
        self.assertEqual(allowed, {"topic:HORIZON-CL1-2026-01", "cordis:org:1", "cordis:org:2", "cordis:101", "cordis:102"})
        text = ("## Proposed partners\nISGlobal fits through SIRENE [cordis:org:1] [cordis:101]. "
                "The Max Planck Institute is a leader [cordis:org:999]. Oslo Met coordinated AIR [cordis:org:2] [cordis:102].\n\n"
                "## Gaps and next steps\nA German partner is still needed.")
        result = check_citations(text, allowed)
        self.assertEqual(result["text"], "## Proposed partners\nISGlobal fits through SIRENE [cordis:org:1] [cordis:101]. "
                                         "Oslo Met coordinated AIR [cordis:org:2] [cordis:102].\n\n## Gaps and next steps\nA German partner is still needed.")
        self.assertEqual(result["dropped"], [{"sentence": "The Max Planck Institute is a leader [cordis:org:999].", "unknown": ["cordis:org:999"]}])
        self.assertEqual(result["uncited"], ["A German partner is still needed."])
        self.assertEqual(result["citations"], ["cordis:101", "cordis:102", "cordis:org:1", "cordis:org:2"])


class BriefTests(unittest.TestCase):
    def test_brief_prompt_holds_the_evidence_and_the_answer_is_checked(self):
        answer = LLMResponse("## Fit to the call\nThe topic matches [topic:HORIZON-CL1-2026-01].\n## Proposed partners\n"
                             "ISGlobal [cordis:org:1] via SIRENE [cordis:101]. Imaginary Lab [cordis:org:77] too.\n## Gaps and next steps\nFind a German partner.",
                             "gemma4:12b", 500, 120, "stop")
        with mock.patch.object(consortium, "generate", return_value=answer) as gen:
            result = brief(CALL, PARTNERS, HOME)
        prompt = gen.call_args.args[0][0]["content"]
        self.assertEqual(gen.call_args.kwargs["task"], "reasoning")
        self.assertEqual(gen.call_args.kwargs["data_class"], "P")
        self.assertIn("[topic:HORIZON-CL1-2026-01] HORIZON-CL1-2026-01: Smoke and health", prompt)
        self.assertIn("[cordis:org:2] OSLO MET (NO, higher education)", prompt)
        self.assertIn("[cordis:102] AIR (coordinator)", prompt)
        self.assertIn("Simon Fraser University (CA)", prompt)
        self.assertNotIn("cordis:org:77", result["brief"])
        self.assertIn("ISGlobal [cordis:org:1] via SIRENE [cordis:101].", result["brief"])
        self.assertEqual(result["dropped"][0]["unknown"], ["cordis:org:77"])
        self.assertEqual(result["uncited"], ["Find a German partner."])
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["model"], "gemma4:12b")


if __name__ == "__main__":
    unittest.main()
