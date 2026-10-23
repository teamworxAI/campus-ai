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

from campus_ai.course_access import alt_text, audit as audit_module, rebuild, workers
from campus_ai.course_access.parser import parse


def remediate(path: Path, out_dir: Path, *, data_class: str, with_alt_text: bool, approve_all: bool) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    document = parse(path)
    issues = audit_module.audit(document)
    fixes = workers.propose_fixes(document, data_class=data_class, issues=issues)
    alts = alt_text.propose(document, data_class=data_class) if with_alt_text else []
    ok = (lambda p: p.needs_review is False) if not approve_all else (lambda p: True)
    approved_fixes = [f for f in fixes if f.value is not None and ok(f)]
    approved_alts = [a for a in alts if ok(a) and (a.alt or a.decorative)]
    waiting_fixes = [f for f in fixes if f not in approved_fixes]
    waiting_alts = [a for a in alts if a not in approved_alts]

    rebuilt = rebuild.apply(document, approved_fixes, approved_alts)
    docx_path, html_path = out_dir / f"{stem}.docx", out_dir / f"{stem}.html"
    notes = rebuild.to_docx(rebuilt, docx_path)
    html_path.write_text(rebuild.to_html(rebuilt), encoding="utf-8")
    _, after = rebuild.verify(docx_path)

    (out_dir / f"{stem}-report.md").write_text(audit_module.report_markdown(document, issues, path.name), encoding="utf-8")
    review = workers.report_markdown(waiting_fixes, path.name)
    if alts:
        review += "\n" + alt_text.report_markdown(waiting_alts, path.name)
    (out_dir / f"{stem}-review.md").write_text(review, encoding="utf-8")
    applied, waiting = len(approved_fixes) + len(approved_alts), len(waiting_fixes) + len(waiting_alts)
    (out_dir / f"{stem}-statement.md").write_text(
        rebuild.statement(path.name, issues, after, applied, waiting, notes), encoding="utf-8")
    return {"before": issues, "after": after, "applied": applied, "waiting": waiting, "notes": notes,
            "files": [docx_path, html_path]}


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
