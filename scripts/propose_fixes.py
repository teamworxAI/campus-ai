"""Propose fixes for the accessibility issues in a course document (A4, with A3).

Parses the file (A1), audits it (A2) and runs the structure, table and text
workers over the issues; with --alt-text, the alt-text worker too (needs the
vision model, slower). Prints a review sheet. Nothing is written back.

    docker compose run --rm -v "$PWD/samples:/samples:ro" test python scripts/propose_fixes.py /samples/week4.docx
    ... --alt-text          also propose alt text for the flagged images
    ... --json              machine-readable proposals
    ... --data-class P      the document's data class (default I; R is refused)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from campus_ai.course_access import alt_text, workers
from campus_ai.course_access.audit import audit
from campus_ai.course_access.parser import parse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--alt-text", action="store_true", help="also run the alt-text worker (vision model)")
    parser.add_argument("--json", action="store_true", help="print the proposals as JSON")
    parser.add_argument("--data-class", default="I", help="P, I or S (R is never sent to a model)")
    args = parser.parse_args()
    document = parse(args.path)
    issues = audit(document)
    fixes = workers.propose_fixes(document, data_class=args.data_class, issues=issues)
    alts = alt_text.propose(document, data_class=args.data_class) if args.alt_text else []
    if args.json:
        print(json.dumps({"fixes": [asdict(f) for f in fixes], "alt_text": [asdict(a) for a in alts]},
                         indent=2, ensure_ascii=False))
        return
    print(workers.report_markdown(fixes, args.path.name))
    if args.alt_text:
        print(alt_text.report_markdown(alts, args.path.name))


if __name__ == "__main__":
    main()
