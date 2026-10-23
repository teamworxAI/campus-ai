"""Remediate every document in the A6 corpus and measure the result (plan 3.4 metrics).

For each document: audit, propose fixes (A4; alt text with --alt-text),
apply the proposals that need no review, rebuild a DOCX, audit it again.
Reports issues before and after, the share fixed, and issues introduced
(target 0). Needs the `ollama` service for the model-backed proposals.
Writes a Markdown report next to this script; the rebuilt files go to a
temporary folder.

    docker compose run --rm test python evals/course_access/remediate_corpus.py [--alt-text] [--approve-all]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.course_access.rebuild import compare

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("remediate", HERE.parents[1] / "scripts" / "remediate.py")
remediate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remediate)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--alt-text", action="store_true")
    parser.add_argument("--approve-all", action="store_true")
    args = parser.parse_args(argv)
    root = Path(os.environ.get("DATA_DIR", "data")) / "course_access"
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        print(f"No corpus at {root}: run `docker compose run --rm fetch-course-docs` first")
        return 1
    paths = sorted({json.loads(line)["path"] for line in manifest.read_text(encoding="utf-8").splitlines()})
    rows, failures, new_rules = [], [], Counter()
    totals = Counter()
    with tempfile.TemporaryDirectory() as tmp:
        for path in paths:
            start = time.perf_counter()
            try:
                result = remediate.remediate(root / path, Path(tmp) / Path(path).parent, data_class="P",
                                             with_alt_text=args.alt_text, approve_all=args.approve_all)
            except Exception as exc:  # a failure is a finding too
                failures.append((path, f"{type(exc).__name__}: {exc}"))
                continue
            seconds = time.perf_counter() - start
            c = compare(result["before"], result["after"])
            new = sum(c["new"].values())
            new_rules.update(c["new"])
            totals.update(before=c["before"], after=c["after"], applied=result["applied"], waiting=result["waiting"], new=new)
            rows.append((path, c["before"], result["applied"], result["waiting"], c["after"], new, len(result["notes"]), seconds))
    when = datetime.now(timezone.utc)
    fixed_share = (totals["before"] - totals["after"]) / totals["before"] if totals["before"] else 0
    mode = "all proposals with a value" if args.approve_all else "proposals needing no review"
    lines = [f"# Remediation of the A6 corpus", "",
             f"{when:%Y-%m-%d %H:%M} UTC. {len(rows)} documents rebuilt as DOCX and re-audited, {len(failures)} failed. "
             f"Applied: {mode}{', with alt text' if args.alt_text else ', without alt text'}.", "",
             f"- Issues before: {totals['before']}; after: {totals['after']} ({fixed_share:.0%} fewer)",
             f"- Proposals applied: {totals['applied']}; waiting for review: {totals['waiting']}",
             f"- Issues introduced by the rebuild (target 0): {totals['new']}"
             + (" (" + ", ".join(f"{r} +{n}" for r, n in new_rules.items()) + ")" if new_rules else ""),
             "", "| Document | Before | Applied | Waiting | After | Introduced | Notes | Seconds |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {p} | {b} | {ap} | {w} | {a} | {n} | {notes} | {s:.1f} |" for p, b, ap, w, a, n, notes, s in rows]
    if failures:
        lines += ["", "## Failed", ""] + [f"- `{p}`: {err}" for p, err in failures]
    report = "\n".join(lines) + "\n"
    print(report)
    out = HERE / f"remediate_corpus_{when:%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Report: {out.relative_to(HERE.parents[1])}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
