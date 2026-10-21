"""Audit a course document (PDF, PPTX, DOCX) against WCAG 2.2 AA (A2).

Parses the file (A1), runs the deterministic checks and prints a report.
Fully offline; no model is used.

    docker compose run --rm -v "$PWD/samples:/samples:ro" test python scripts/audit_document.py /samples/lecture.pdf
    ... --json    machine-readable report
"""

from __future__ import annotations

import argparse
from pathlib import Path

from campus_ai.course_access.audit import audit, report_json, report_markdown
from campus_ai.course_access.parser import parse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    document = parse(args.path)
    issues = audit(document)
    render = report_json if args.json else report_markdown
    print(render(document, issues, args.path.name))


if __name__ == "__main__":
    main()
