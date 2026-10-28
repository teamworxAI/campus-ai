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

    def test_probe_flags(self):
        for name in ("expert_search", "partner_search"):
            parse = load(name).parse
            self.assertTrue(parse(["--rerank"]).rerank, name)
            self.assertFalse(parse([]).rerank, name)


if __name__ == "__main__":
    unittest.main()
