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

from campus_ai.core.eval import report
from campus_ai.course_access.audit import audit
from campus_ai.course_access.parser import Image, Table, parse

HERE = Path(__file__).parent


def build_report(rows: list[tuple], failures: list[tuple], when: datetime, sha: str | None = None) -> str:
    """rows: (path, licence, pages, blocks, images, tables, issue rules Counter, seconds); failures: (path, error)."""
    totals = Counter()
    for row in rows:
        totals.update(row[6])
    table = [(p, lic, pages if pages is not None else "-", blocks, img, tab, sum(rules.values()),
              ", ".join(f"{r} x{n}" if n > 1 else r for r, n in sorted(rules.items())), f"{s:.1f}")
             for p, lic, pages, blocks, img, tab, rules, s in rows]
    sections = [(None, report.table(["Document", "Licence", "Pages", "Blocks", "Images", "Tables", "Issues", "Rules", "Seconds"],
                                    table))]
    if failures:
        sections.append(("Failed to parse", [f"- `{p}`: {err}" for p, err in failures]))
    sections.append(("Issues by rule, all documents", report.table(["Rule", "Count"], totals.most_common())))
    return report.render(
        "Audit of the A6 corpus",
        f"{len(rows)} documents audited, {len(failures)} failed to parse. "
        "Issue counts are what the deterministic rules find; they are not yet checked against a specialist's labels.",
        when=when, sections=sections, sha=sha)


def main() -> int:
    root = Path(os.environ.get("DATA_DIR", "data")) / "course_access"
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        print(f"No corpus at {root}: run `docker compose run --rm fetch-course-docs` first")
        return 1
    records = {}
    for line in manifest.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            record = json.loads(line)
            records[record["path"]] = record  # the last record per path wins
    rows, failures = [], []
    for path, record in sorted(records.items()):
        start = time.perf_counter()
        try:
            document = parse(root / path)
            issues = audit(document)
        except Exception as exc:  # a failure is a finding too
            failures.append((path, f"{type(exc).__name__}: {exc}"))
            continue
        seconds = time.perf_counter() - start
        images = sum(isinstance(b, Image) for b in document.blocks)
        tables = sum(isinstance(b, Table) for b in document.blocks)
        rows.append((path, record["licence"], document.page_count, len(document.blocks), images, tables,
                     Counter(issue.rule for issue in issues), seconds))
    when = datetime.now(timezone.utc)
    report.save(build_report(rows, failures, when, report.git_sha(HERE)), "audit_corpus", HERE, when)
    return 0


if __name__ == "__main__":
    sys.exit(main())
