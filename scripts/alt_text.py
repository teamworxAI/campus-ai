"""Propose alt text for the images in a course document (A3).

Parses the file (A1), finds the images the audit (A2) flags, asks the local
vision model through the LLM router and prints a review sheet. Nothing is
written back: the proposals are for a person to approve.

    docker compose run --rm -v "$PWD/samples:/samples:ro" test python scripts/alt_text.py /samples/lecture.pptx
    ... --json              machine-readable proposals
    ... --data-class P      the document's data class (default I, institutional; R is refused)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from campus_ai.course_access.alt_text import propose, report_json, report_markdown
from campus_ai.course_access.parser import parse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="print the proposals as JSON")
    parser.add_argument("--data-class", default="I", help="P, I or S (R is never sent to a model)")
    args = parser.parse_args()
    proposals = propose(parse(args.path), data_class=args.data_class)
    print(report_json(proposals) if args.json else report_markdown(proposals, args.path.name))


if __name__ == "__main__":
    main()
