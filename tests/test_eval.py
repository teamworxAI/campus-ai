import importlib.util
import json
import math
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from campus_ai.core.eval import gold, judge, metrics, report
from campus_ai.core.llm import LLMResponse

ROOT = Path(__file__).resolve().parents[1]
WHEN = datetime(2026, 10, 23, 4, 30, tzinfo=timezone.utc)


def load_eval(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / "evals" / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetrievalMetricTests(unittest.TestCase):
    ranked = ["a", "x", "b", "y", "c"]
    relevant = {"a", "b", "z"}

    def test_recall_and_precision(self):
        self.assertAlmostEqual(metrics.recall_at_k(self.ranked, self.relevant, 3), 2 / 3)
        self.assertAlmostEqual(metrics.recall_at_k(self.ranked, self.relevant, 1), 1 / 3)
        self.assertAlmostEqual(metrics.precision_at_k(self.ranked, self.relevant, 3), 2 / 3)
        self.assertAlmostEqual(metrics.precision_at_k(["a"], self.relevant, 5), 1 / 5)  # a short list still divides by k
        self.assertEqual(metrics.recall_at_k(self.ranked, [], 3), 0.0)

    def test_ranks_and_mrr(self):
        self.assertEqual(metrics.first_rank(["x", "y", "b"], self.relevant), 3)
        self.assertIsNone(metrics.first_rank(["x", "y"], self.relevant))
        self.assertAlmostEqual(metrics.reciprocal_rank(["x", "b"], self.relevant), 0.5)
        self.assertEqual(metrics.reciprocal_rank(["x"], self.relevant), 0.0)
        mrr = metrics.mean([metrics.reciprocal_rank(r, {"a"}) for r in (["a"], ["x", "a"], ["x"])])
        self.assertAlmostEqual(mrr, (1 + 0.5 + 0) / 3)
        self.assertEqual(metrics.mean([]), 0.0)

    def test_ndcg(self):
        # hits at ranks 1 and 3; ideal puts 3 relevant at ranks 1-3
        dcg = 1 + 1 / math.log2(4)
        ideal = 1 + 1 / math.log2(3) + 1 / math.log2(4)
        self.assertAlmostEqual(metrics.ndcg_at_k(self.ranked, self.relevant, 5), dcg / ideal)
        self.assertAlmostEqual(metrics.ndcg_at_k(["a", "b"], {"a", "b"}, 10), 1.0)
        self.assertAlmostEqual(metrics.ndcg_at_k(["x", "a"], {"a"}, 10), 1 / math.log2(3))
        self.assertEqual(metrics.ndcg_at_k(["x"], {"a"}, 10), 0.0)
        self.assertAlmostEqual(metrics.ndcg_at_k(["a", "a"], {"a"}, 10), 1.0)  # a repeated id counts once


class CitationAndCourseMetricTests(unittest.TestCase):
    def test_citation_precision_uses_the_brief_syntax(self):
        text = ("ISGLOBAL leads exposure work [cordis:org:1]. OSLO MET coordinated AIR [cordis:102] [cordis:999].\n"
                "A sentence with no citation.")
        result = metrics.citation_precision(text, {"cordis:org:1", "cordis:102"})
        self.assertEqual((result["cited"], result["valid"]), (3, 2))
        self.assertAlmostEqual(result["precision"], 2 / 3)
        self.assertEqual((result["dropped"], result["uncited"]), (1, 1))
        self.assertIsNone(metrics.citation_precision("Nothing cited.", set())["precision"])

    def test_remediation_metrics(self):
        self.assertAlmostEqual(metrics.fixed_share(862, 360), 502 / 862)
        self.assertEqual(metrics.fixed_share(0, 0), 0.0)
        self.assertEqual(metrics.introduced({"new": {"no-headings": 1, "fake-list": 1}}), 2)
        self.assertAlmostEqual(metrics.review_share([True, False, False, True]), 0.5)
        self.assertIsNone(metrics.review_share([]))

    def test_count_agreement(self):
        result = metrics.count_agreement({"image-missing-alt": 3, "no-headings": 1}, {"image-missing-alt": 4, "fake-list": 1})
        self.assertEqual(result["matched"], 3)
        self.assertAlmostEqual(result["precision"], 3 / 5)
        self.assertAlmostEqual(result["recall"], 3 / 4)
        self.assertIsNone(metrics.count_agreement({}, {})["precision"])


GOOD = [
    {"id": "q1", "query": "salmon and climate", "relevant": ["openalex:A1"], "source": "test", "notes": "provisional",
     "search": "experts"},
    {"id": "d1", "document": "oer/a.pdf", "expected": {"image-missing-alt": 2}, "source": "test", "notes": "",
     "issues": [{"rule": "image-missing-alt", "page": 3}]},
]


def jsonl(cases) -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)


class GoldTests(unittest.TestCase):
    def test_good_records_load_and_blank_lines_and_crlf_are_ignored(self):
        cases = gold.parse(jsonl(GOOD).replace("\n", "\r\n") + "\n\n")
        self.assertEqual([c["id"] for c in cases], ["q1", "d1"])
        self.assertEqual(len(gold.parse(jsonl(GOOD[:1]), kind="retrieval")), 1)
        with self.assertRaisesRegex(gold.GoldError, "line 2: a course_access case in a retrieval gold set"):
            gold.parse(jsonl(GOOD), kind="retrieval")

    def test_missing_and_bad_fields_name_the_line(self):
        bad = [
            ({"id": "q", "query": "x", "source": "s", "notes": ""}, "missing field\\(s\\): relevant"),
            ({"id": "q", "query": "x", "relevant": [], "source": "s", "notes": ""}, "non-empty list"),
            ({"id": "q", "query": "x", "relevant": ["a"], "source": "s", "notes": "", "relevent": []}, "unknown field"),
            ({"id": "q", "query": "x", "document": "d", "source": "s", "notes": ""}, "exactly one of"),
            ({"id": "d", "document": "a.pdf", "expected": {"r": -1}, "source": "s", "notes": ""}, "counts"),
            ({"id": "d", "document": "a.pdf", "expected": {}, "issues": [{"page": 1}], "source": "s", "notes": ""}, "'rule'"),
        ]
        for case, message in bad:
            with self.subTest(case=case), self.assertRaisesRegex(gold.GoldError, "line 2: .*" + message):
                gold.parse(jsonl([GOOD[0], case]))
        with self.assertRaisesRegex(gold.GoldError, "duplicate id"):
            gold.parse(jsonl([GOOD[0], GOOD[0]]))
        with self.assertRaisesRegex(gold.GoldError, "line 1: not JSON"):
            gold.parse("{not json\n")

    def test_u2028_inside_a_field_stays_in_the_record(self):
        case = dict(GOOD[0], query="salmon rivers", notes="a b\x85c")
        text = json.dumps(case, ensure_ascii=False) + "\n"
        self.assertGreater(len(text.splitlines()), 1)  # the trap the loader avoids
        self.assertEqual(gold.parse(text)[0]["query"], "salmon rivers")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(gold.load(path)[0]["notes"], "a b\x85c")
            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(gold.GoldError, "g.jsonl: line 1"):
                gold.load(path)

    def test_committed_gold_sets_are_valid_and_marked_provisional(self):
        for name, count in (("gold_experts.jsonl", 6), ("gold_partners.jsonl", 20)):
            cases = gold.load(ROOT / "evals" / "research_assistant" / name, kind="retrieval")
            self.assertEqual(len(cases), count)
            self.assertIn("PROVISIONAL", cases[0]["notes"])
            self.assertTrue(all(c.get("search") in ("experts", "partners") for c in cases))


def answer(text: str):
    return LLMResponse(text=text, model="gemma4:e2b", input_tokens=10, output_tokens=5)


class JudgeTests(unittest.TestCase):
    def test_good_answer(self):
        with mock.patch.object(judge, "generate", return_value=answer('{"score": 4, "reason": "Supported\\n  mostly."}')) as gen:
            verdict = judge.faithfulness("Allen studies smoke.", "Allen: Public Health Messaging for Wildfire Smoke", "P")
        self.assertEqual((verdict.score, verdict.reason, verdict.model), (4, "Supported mostly.", "gemma4:e2b"))
        _, kwargs = gen.call_args
        self.assertEqual((kwargs["task"], kwargs["data_class"]), ("classification", "P"))
        self.assertIn("Allen: Public Health", gen.call_args[0][0][0]["content"])

    def test_fenced_answer_and_alt_text(self):
        with mock.patch.object(judge, "generate", return_value=answer('```json\n{"score": 2, "reason": "Vague."}\n```')) as gen:
            verdict = judge.alt_text_quality("A chart.", "Bar chart of sockeye returns 2018-2022", "I", task="reasoning")
        self.assertEqual(verdict.score, 2)
        self.assertEqual(gen.call_args[1]["task"], "reasoning")

    def test_bad_and_unparsable_answers_give_none(self):
        for text in ("I'd say 5 out of 5, clearly supported.", '{"score": 7, "reason": "x"}', '{"score": "4", "reason": "x"}',
                     '{"score": true, "reason": "x"}', '{"score": 4}', 'Sure! {"score": 4, "reason": "x"}', "[4]", ""):
            with self.subTest(text=text), mock.patch.object(judge, "generate", return_value=answer(text)):
                verdict = judge.faithfulness("t", "e", "P")
                self.assertIsNone(verdict.score)
                self.assertEqual((verdict.reason, verdict.raw_chars), ("", len(text)))

    def test_restricted_data_never_reaches_a_model(self):
        with mock.patch("campus_ai.core.llm.backends.ollama") as backend, \
                self.assertRaises(PermissionError):
            judge.faithfulness("t", "e", "R")
        backend.assert_not_called()


class ReportTests(unittest.TestCase):
    def test_render_shape(self):
        text = report.render("Partner back-test (R6): e5", "3 projects.", when=WHEN, sha="abc1234", embedder="e5",
                             bullets=["**recall@10: 0.33** (1 of 3)", "MRR: 0.11"],
                             sections=[(None, report.table(["Project", "Rank"], [("A", 1), ("B", "miss")])),
                                       ("Failed", ["- `x`: boom"])])
        self.assertEqual(text, "\n".join([
            "# Partner back-test (R6): e5", "",
            "2026-10-23 04:30 UTC (commit abc1234, embedder e5). 3 projects.", "",
            "- **recall@10: 0.33** (1 of 3)", "- MRR: 0.11", "",
            "| Project | Rank |", "|---|---|", "| A | 1 |", "| B | miss |", "",
            "## Failed", "", "- `x`: boom"]) + "\n")
        self.assertTrue(report.render("T", when=WHEN).startswith("# T\n\n2026-10-23 04:30 UTC.\n"))

    def test_save_writes_dated_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("builtins.print"):
            path = report.save("# T\n", "backtest", tmp, WHEN)
            self.assertEqual(path, Path(tmp) / "backtest_20261023.md")
            self.assertEqual(path.read_text(encoding="utf-8"), "# T\n")

    def test_git_sha(self):
        with mock.patch.dict("os.environ", {"GIT_SHA": "0123456789abcdef"}):
            self.assertEqual(report.git_sha(), "0123456789ab")
        with mock.patch.dict("os.environ", {"GIT_SHA": ""}), \
                mock.patch.object(report.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertIsNone(report.git_sha())


def issue(rule):
    return SimpleNamespace(rule=rule)


class EvalScriptReportTests(unittest.TestCase):
    """Each refactored eval builds its report from fixture rows, without a stack."""

    def test_backtest(self):
        module = load_eval("research_assistant/backtest.py")
        results = [("BRAVA", "UB", "ES", "o1", ["o1", "o2"]), ("KiTE", "CAU", "DE", "o3", ["o9", "o8", "o3"]),
                   ("ELLE", "UNICA", "IT", "o5", ["o9"])]
        text = module.build_report(results, "embeddinggemma-2", "CA", 1.8, WHEN)
        self.assertIn("# Partner back-test (R6): embeddinggemma-2", text)
        self.assertIn("3 projects with a CA participant", text)
        self.assertIn("0.6 s per project", text)
        self.assertIn("- **recall@10: 0.67** (2 of 3)", text)
        self.assertIn("- MRR: 0.44", text)
        self.assertIn("| KiTE | CAU | DE | 3 |", text)
        self.assertIn("| ELLE | UNICA | IT | miss |", text)

    def test_expert_and_partner_probes(self):
        experts = load_eval("research_assistant/expert_search.py")
        text = experts.build_report([("salmon", 0.4, [{"id": "openalex:A1", "name": "J. Moore", "works": 18, "score": 0.031,
                                                       "found_by": ["meaning", "words"], "topics": ["Fish", "Rivers"]}]),
                                     ("nothing", 0.1, [])], "embeddinggemma-2", WHEN)
        self.assertIn("## salmon\n\n0.4 s\n\n- **J. Moore** (18 works, score 0.031, found by meaning+words): Fish; Rivers\n", text)
        self.assertIn("## nothing\n\n0.1 s\n\n- (no researchers found)", text)
        partners = load_eval("research_assistant/partner_search.py")
        text = partners.build_report([("housing", [
            ("Organization", 0.2, [{"name": "TU Delft", "country": "NL", "activity": "HES", "fields": ["urban"]}]),
            ("Project", 0.3, [{"acronym": "HOME", "title": "Homes", "start": "2024", "countries": ["NL", "CA"]}])])],
            "e5", WHEN)
        self.assertIn("**Organizations** (0.2 s)\n\n- TU Delft (NL, HES): urban\n\n**Projects** (0.3 s)\n\n- HOME: Homes (2024; NL, CA)\n",
                      text)

    def test_gold_eval(self):
        module = load_eval("research_assistant/gold_eval.py")
        cases = [dict(GOOD[0], id="e1", relevant=["a", "b"]), dict(GOOD[0], id="e2", relevant=["c"])]
        text = module.build_report([("gold_experts", True, [(cases[0], ["a", "x", "b"], 0.2), (cases[1], ["x"], 0.1)])],
                                   10, "e5", WHEN)
        self.assertIn("- **gold_experts** (2 cases, provisional labels): recall@10 0.50, MRR 0.50", text)
        self.assertIn("| e1 | salmon and climate | 2/2 | 1 |", text)
        self.assertIn("| e2 | salmon and climate | 0/1 | miss | 0.00 |", text)

    def test_gold_eval_routes_cases_to_their_search(self):
        module = load_eval("research_assistant/gold_eval.py")
        search = mock.Mock()
        search.experts.return_value = [{"id": "p"}, {"id": "a"}]
        search.partners.return_value = [{"id": "o1"}]
        self.assertEqual(module.ranked_ids(search, dict(GOOD[0], exclude=["p"]), 1), ["a"])
        case = dict(GOOD[0], search="partners", exclude=["cordis:1"])
        self.assertEqual(module.ranked_ids(search, case, 10), ["o1"])
        search.partners.assert_called_once_with(case["query"], k=10, exclude_project="cordis:1")
        with self.assertRaisesRegex(ValueError, "unknown search"):
            module.ranked_ids(search, dict(GOOD[0], search="calls"), 10)

    def test_audit_corpus(self):
        module = load_eval("course_access/audit_corpus.py")
        rows = [("oer/a.pdf", "CC-BY-4.0", 26, 213, 49, 32, Counter({"image-missing-alt": 2, "no-headings": 1}), 6.31),
                ("oer/b.docx", "CC-BY-SA-4.0", None, 10, 0, 0, Counter(), 0.2)]
        text = module.build_report(rows, [("oer/c.pdf", "ValueError: bad")], WHEN)
        self.assertIn("2026-10-23 04:30 UTC. 2 documents audited, 1 failed to parse.", text)
        self.assertIn("| oer/a.pdf | CC-BY-4.0 | 26 | 213 | 49 | 32 | 3 | image-missing-alt x2, no-headings | 6.3 |", text)
        self.assertIn("| oer/b.docx | CC-BY-SA-4.0 | - | 10 | 0 | 0 | 0 |  | 0.2 |", text)
        self.assertIn("## Failed to parse\n\n- `oer/c.pdf`: ValueError: bad", text)
        self.assertIn("## Issues by rule, all documents\n\n| Rule | Count |\n|---|---|\n| image-missing-alt | 2 |", text)

    def test_propose_corpus(self):
        module = load_eval("course_access/propose_corpus.py")
        fixes = [SimpleNamespace(action="set-link-text", needs_review=False, model="gemma4:e2b", value="Course outline",
                                 confidence=0.9, review_reason=""),
                 SimpleNamespace(action="set-language", needs_review=True, model="", value={"lang": "en"},
                                 confidence=0.5, review_reason="low confidence")]
        text = module.build_report([("oer/a.pdf", fixes, 2.0)], WHEN)
        self.assertIn("1 documents, 2 proposals, 1 to review, 1 from the model (gemma4:e2b).", text)
        self.assertIn("| oer/a.pdf | 2 | 1 | 1 | 2.0 |", text)
        self.assertIn('- a.pdf: {"lang": "en"} (confidence 0.50, review: low confidence)', text)

    def test_remediate_corpus(self):
        module = load_eval("course_access/remediate_corpus.py")
        result = {"before": [issue("fake-list"), issue("image-missing-alt"), issue("image-missing-alt"), issue("no-title")],
                  "after": [issue("image-missing-alt"), issue("no-headings")], "applied": 3, "waiting": 1, "notes": ["n"]}
        text = module.build_report([("oer/a.pdf", result, 5.0)], [], WHEN)
        self.assertIn("Applied: proposals needing no review, without alt text.", text)
        self.assertIn("- Issues before: 4; after: 2 (50% fewer)", text)
        self.assertIn("- Proposals applied: 3; waiting for review: 1", text)
        self.assertIn("- Issues introduced by the rebuild (target 0): 1 (no-headings +1)", text)
        self.assertIn("| oer/a.pdf | 4 | 3 | 1 | 2 | 1 | 1 | 5.0 |", text)

    def test_alt_text_probes(self):
        module = load_eval("course_access/alt_text_probes.py")
        proposal = SimpleNamespace(block=1, page=1, kind="chart", decorative=False, alt="Bars", long_description="",
                                   confidence=0.8, needs_review=True, review_reason="chart", model="gemma4:e2b")
        rows = [("bar chart", ["chart"], "chart", True, True, 3.2), ("divider line", ["decorative"], "photo", False, True, 0.4)]
        text = module.build_report(rows, [proposal, proposal], WHEN)
        self.assertIn("# Alt-text probe run: gemma4:e2b", text)
        self.assertIn("Kind right for 1/2; review routing right for 2/2", text)
        self.assertIn("| divider line | decorative | photo | NO | yes | 0.4 |", text)
        self.assertIn("# Alt text proposals: probe deck", text)


if __name__ == "__main__":
    unittest.main()
