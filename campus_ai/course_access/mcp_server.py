"""Course Access as an MCP server (card P4): thin wrappers over the A1-A5 functions.

    python -m campus_ai.course_access.mcp_server            # stdio, for MCP clients
    python -m campus_ai.course_access.mcp_server --http 8000

Paths are files on the machine running the server; course documents (class I)
never leave it. Needs the local router models for proposals (see the build guide).
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from campus_ai.core.mcp import build_server, serve
from campus_ai.course_access import alt_text, audit as audit_module, rebuild, workers
from campus_ai.course_access.parser import parse
from campus_ai.course_access.remediate import remediate as run_remediate


def audit_document(path: str, data_class: str = "I") -> dict:
    """Audit a course document (DOCX, PPTX or PDF) against WCAG 2.2 AA and return the report: counts by criterion and every issue with its page and block."""
    document = parse(Path(path))
    return audit_module.report_dict(document, audit_module.audit(document), Path(path).name)


def propose_fixes(path: str, with_alt_text: bool = False, data_class: str = "I") -> dict:
    """Propose fixes for a document's accessibility issues. Each proposal has a confidence, a needs_review flag and its evidence; nothing is applied. with_alt_text also drafts image descriptions with the local vision model (slower)."""
    document = parse(Path(path))
    fixes = workers.propose_fixes(document, data_class=data_class, issues=audit_module.audit(document))
    alts = alt_text.propose(document, data_class=data_class) if with_alt_text else []
    return {"fixes": [asdict(f) for f in fixes], "alt_text": [asdict(a) for a in alts]}


def remediate(path: str, out_dir: str, approve_all: bool = False, with_alt_text: bool = False, data_class: str = "I") -> dict:
    """Make an accessible version of a document: apply the proposals that need no review (all with approve_all, for demos only), write the accessible DOCX and HTML, the audit report, the review sheet and an accessibility statement to out_dir, re-audit the DOCX, and return the file paths and the before/after issue counts."""
    result = run_remediate(Path(path), Path(out_dir), data_class=data_class, with_alt_text=with_alt_text,
                           approve_all=approve_all)
    stem = Path(path).stem
    counts = rebuild.compare(result["before"], result["after"])
    extra = [Path(out_dir) / f"{stem}-{part}.md" for part in ("report", "review", "statement")]
    return {"files": [str(p) for p in result["files"] + extra], "before": counts["before"], "after": counts["after"],
            "fixed": counts["fixed"], "introduced": counts["new"], "remaining": counts["remaining"],
            "applied": result["applied"], "waiting_for_review": result["waiting"], "notes": result["notes"]}


TOOLS = [audit_document, propose_fixes, remediate]


def create_server() -> MCPServer:
    return build_server("campus-ai-course-access", TOOLS,
                        "Audit course documents for WCAG 2.2 AA, propose fixes and build accessible versions. Offline, local models.")


if __name__ == "__main__":
    serve(create_server())
