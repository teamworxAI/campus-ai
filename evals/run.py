"""Run the evals and list their reports (card P6).

By default runs only what needs no live stack: the A6 corpus audit (the
corpus in DATA_DIR, no model). `--ollama` adds the Course Access evals that
call the local model (alt-text probes, worker proposals, remediation);
`--graph` adds the Research Assistant evals over the indexed graph (expert
and partner probes, the R6 back-test, the gold sets); the graph ones need
the `embed` image. Each eval writes its dated report next to itself; this
prints the report paths and exits non-zero if any eval failed.

    docker compose run --rm test python evals/run.py [--ollama]
    docker compose run --rm embed python evals/run.py --graph [--limit 100]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
OFFLINE = [["course_access/audit_corpus.py"]]
OLLAMA = [["course_access/alt_text_probes.py"], ["course_access/propose_corpus.py"], ["course_access/remediate_corpus.py"]]
GRAPH = [["research_assistant/expert_search.py"], ["research_assistant/partner_search.py"],
         ["research_assistant/backtest.py", "--limit", "{limit}"], ["research_assistant/gold_eval.py"]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ollama", action="store_true", help="also run the Course Access evals that call the local model")
    parser.add_argument("--graph", action="store_true", help="also run the Research Assistant evals over the graph")
    parser.add_argument("--no-offline", action="store_true", help="skip the evals that need no stack")
    parser.add_argument("--limit", type=int, default=100, help="projects for the back-test")
    args = parser.parse_args(argv)
    plan = ([] if args.no_offline else OFFLINE) + (OLLAMA if args.ollama else []) + (GRAPH if args.graph else [])
    reports, failed = [], []
    for script, *extra in plan:
        command = [sys.executable, str(HERE / script)] + [a.format(limit=args.limit) for a in extra]
        print(f"== {script}", flush=True)
        done = subprocess.run(command, capture_output=True, text=True)
        found = [line.removeprefix("Report: ") for line in done.stdout.split("\n") if line.startswith("Report: ")]
        reports += found
        if done.returncode:
            failed.append(script)
            print(done.stdout[-2000:] + done.stderr[-2000:])
        print(f"   {'failed' if done.returncode else 'ok'}: {', '.join(found) or 'no report'}", flush=True)
    print("\nReports:\n" + "\n".join(f"- {r}" for r in reports) if reports else "\nNo reports written.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
