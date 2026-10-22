"""Audit every document in DATA_DIR/course_access (the A6 corpus) and tabulate the findings.

The first numbers the parser (A1) and audit (A2) produce on real course
documents, before the gold labels exist: what each file is, what the audit
finds and where it or the parser fails. Writes a Markdown report next to this
script. Fully offline; no model.

    docker compose run --rm test python evals/course_access/audit_corpus.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.course_access.audit import audit
from campus_ai.course_access.parser import Image, Table, parse

HERE = Path(__file__).parent


def main() -> int:
    root = Path(os.environ.get("DATA_DIR", "data")) / "course_access"
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        print(f"No corpus at {root}: run `docker compose run --rm fetch-course-docs` first")
        return 1
    records = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        records[record["path"]] = record  # the last record per path wins
    rows, totals, failures = [], Counter(), []
    for path, record in sorted(records.items()):
        start = time.perf_counter()
        try:
            document = parse(root / path)
            issues = audit(document)
        except Exception as exc:  # a failure is a finding too
            failures.append((path, f"{type(exc).__name__}: {exc}"))
            continue
        seconds = time.perf_counter() - start
        rules = Counter(issue.rule for issue in issues)
        totals.update(rules)
        images = sum(isinstance(b, Image) for b in document.blocks)
        tables = sum(isinstance(b, Table) for b in document.blocks)
        rows.append((path, record["licence"], document.page_count, len(document.blocks), images, tables,
                     len(issues), ", ".join(f"{r} x{n}" if n > 1 else r for r, n in sorted(rules.items())), seconds))
    when = datetime.now(timezone.utc)
    lines = [f"# Audit of the A6 corpus", "",
             f"{when:%Y-%m-%d %H:%M} UTC. {len(rows)} documents audited, {len(failures)} failed to parse. "
             "Issue counts are what the deterministic rules find; they are not yet checked against a specialist's labels.",
             "", "| Document | Licence | Pages | Blocks | Images | Tables | Issues | Rules | Seconds |",
             "|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| {p} | {lic} | {pages if pages is not None else '-'} | {blocks} | {img} | {tab} | {n} | {rules} | {s:.1f} |"
              for p, lic, pages, blocks, img, tab, n, rules, s in rows]
    if failures:
        lines += ["", "## Failed to parse", ""] + [f"- `{p}`: {err}" for p, err in failures]
    lines += ["", "## Issues by rule, all documents", "", "| Rule | Count |", "|---|---|"]
    lines += [f"| {rule} | {n} |" for rule, n in totals.most_common()]
    report = "\n".join(lines) + "\n"
    print(report)
    out = HERE / f"audit_corpus_{when:%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Report: {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
