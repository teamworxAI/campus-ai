"""Make an accessible version of a course document (A1-A5 end to end).

Parses the file, audits it, runs the workers, applies the approved proposals
and writes: an accessible DOCX and HTML, the audit report of the original,
the review sheet of proposals still waiting for a person, and an
accessibility statement with the before/after numbers from re-auditing the
rebuilt DOCX.

By default only proposals that need no review are applied (rules with a
confidence of 0.7 or more). A person approves the rest in the review queue
(P3, planned). --approve-all applies everything that has a value, for demos
and evaluation only.

    docker compose run --rm -v "$PWD/samples:/samples" test python scripts/remediate.py /samples/week4.pptx --out /samples/out
    ... --alt-text       also propose and apply alt text (vision model)
    ... --approve-all    apply every proposal with a value, review or not
    ... --data-class P   the document's data class (default I; R is refused)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from campus_ai.course_access import rebuild
from campus_ai.course_access.remediate import remediate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="folder for the outputs")
    parser.add_argument("--alt-text", action="store_true", help="also run the alt-text worker (vision model)")
    parser.add_argument("--approve-all", action="store_true", help="apply every proposal with a value (demos, evals)")
    parser.add_argument("--data-class", default="I", help="P, I or S (R is never sent to a model)")
    args = parser.parse_args()
    result = remediate(args.path, args.out, data_class=args.data_class, with_alt_text=args.alt_text,
                       approve_all=args.approve_all)
    summary = rebuild.compare(result["before"], result["after"])
    print(f"{args.path.name}: {summary['before']} issues before, {summary['after']} after; "
          f"{result['applied']} proposals applied, {result['waiting']} waiting for review; "
          f"{sum(summary['new'].values())} issues introduced.")
    for note in result["notes"]:
        print("note:", note)
    print("Written to", args.out)


if __name__ == "__main__":
    main()
