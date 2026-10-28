import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals" / "research_assistant" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RerankFlagTests(unittest.TestCase):
    def test_backtest_flags(self):
        parse = load("backtest").parse
        args = parse(["--limit", "50", "--rerank"])
        self.assertEqual((args.limit, args.home, args.rerank), (50, "CA", True))
        self.assertFalse(parse([]).rerank)

    def test_backtest_signals(self):
        backtest = load("backtest")
        args = backtest.parse(["--signals", "projects,organisations,fused,fused:0.5", "--no-acronym"])
        self.assertTrue(args.no_acronym)
        runs = backtest.signal_runs(args.signals)
        self.assertEqual([name for name, _ in runs], ["projects", "organisations", "fused", "fused:0.5"])
        self.assertEqual(runs[2][1], {"signal": "fused", "organisation_weight": 1.0})
        self.assertEqual(runs[3][1], {"signal": "fused", "organisation_weight": 0.5})
        self.assertEqual(backtest.signal_runs(backtest.parse([]).signals), [("projects", {"signal": "projects", "organisation_weight": 1.0})])
        with self.assertRaises(SystemExit):
            backtest.signal_runs("rumour")
        project = {"acronym": "AIR", "text": "AIR: Air quality\nThe AIR project measures air (AIRS too)."}
        self.assertEqual(backtest.question(project, False), project["text"])
        self.assertEqual(backtest.question(project, True), "Air quality\nThe  project measures air (AIRS too).")
        self.assertEqual(backtest.question({"acronym": "", "text": "x"}, True), "x")

    def test_probe_flags(self):
        for name in ("expert_search", "partner_search"):
            parse = load(name).parse
            self.assertTrue(parse(["--rerank"]).rerank, name)
            self.assertFalse(parse([]).rerank, name)


if __name__ == "__main__":
    unittest.main()
