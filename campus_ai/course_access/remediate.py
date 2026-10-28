"""The end-to-end run behind scripts/remediate.py and the MCP server (A1-A5 chained)."""

from __future__ import annotations

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
