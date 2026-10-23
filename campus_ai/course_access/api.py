"""HTTP API for the Course Access review queue (P3). Runs in the `course-access` service, offline:

    docker compose up -d web        # then open http://localhost:8080/review/

    GET    /api/course-access/health
    POST   /api/course-access/jobs?alt_text=0&data_class=I   upload a PDF, PPTX or DOCX: parse, audit, propose
    GET    /api/course-access/jobs                           the queue
    GET    /api/course-access/jobs/{id}                      issues, proposals, decisions, outputs
    GET    /api/course-access/jobs/{id}/images/{block}       the image behind an alt-text proposal
    POST   /api/course-access/jobs/{id}/decisions            approve, edit or reject proposals
    POST   /api/course-access/jobs/{id}/rebuild              apply what is approved, write DOCX/HTML/statement
    GET    /api/course-access/jobs/{id}/files/{name}         download an output
    DELETE /api/course-access/jobs/{id}

A job is a folder under the work directory (WORK_DIR, default ./work): the
uploaded file, job.json (proposals and decisions) and the outputs. Uploaded
course materials are class I data: they stay in that folder on this machine
and go to no model but the local one, through the router.

What gets applied at rebuild: every proposal a person approved (with their
edits), plus the rule-based proposals that need no review unless a person
rejected them. Rejected proposals and proposals waiting for review are never
applied. Nothing is published from here.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from campus_ai.course_access import alt_text, rebuild, workers
from campus_ai.course_access.alt_text import AltText
from campus_ai.course_access.audit import audit, report_dict, report_markdown
from campus_ai.course_access.parser import Document, Image, parse
from campus_ai.course_access.workers import Fix

PREFIX = "/api/course-access"
MAX_UPLOAD = 50 * 1024 * 1024
SUFFIXES = {".pdf", ".pptx", ".docx"}
DATA_CLASSES = {"P", "I", "S"}  # R never reaches a model (P1b), so it is not accepted here
OUTPUTS = ("docx", "html", "report.md", "review.md", "statement.md")
JOB_ID = re.compile(r"^[a-z0-9]{12}$")
MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "bmp": "image/bmp",
               "tif": "image/tiff", "tiff": "image/tiff", "emf": "image/emf", "wmf": "image/wmf"}


def work_dir() -> Path:
    return Path(os.environ.get("WORK_DIR", "work"))


def create_app(root: Path | None = None) -> FastAPI:
    root = root or work_dir()
    root.mkdir(parents=True, exist_ok=True)
    documents: dict[str, Document] = {}  # parsed documents, by job id (re-parsed from the upload after a restart)
    lock = threading.Lock()  # one model-backed step at a time
    app = FastAPI(title="campus-ai course access review queue")

    def job_dir(job_id: str) -> Path:
        if not JOB_ID.match(job_id) or not (root / job_id / "job.json").is_file():
            raise HTTPException(404, "no such job")
        return root / job_id

    def load(job_id: str) -> dict:
        return json.loads((job_dir(job_id) / "job.json").read_text(encoding="utf-8"))

    def save(job: dict) -> None:
        (root / job["id"] / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")

    def document(job: dict) -> Document:
        if job["id"] not in documents:
            documents[job["id"]] = parse(root / job["id"] / job["source"])
        return documents[job["id"]]

    def summary(job: dict) -> dict:
        decided = job["decisions"]
        return {
            "id": job["id"], "name": job["name"], "format": job["format"], "created": job["created"],
            "data_class": job["data_class"], "issues": len(job["issues"]["issues"]),
            "proposals": len(job["fixes"]) + len(job["alt_texts"]),
            "to_review": sum(p["needs_review"] for p in job["fixes"] + job["alt_texts"]),
            "decided": len(decided["fixes"]) + len(decided["alt_texts"]),
            "rebuilt": job.get("result") is not None,
        }

    @app.get(f"{PREFIX}/health")
    def health() -> dict:
        return {"status": "ok", "jobs": sum(1 for p in root.iterdir() if (p / "job.json").is_file())}

    @app.post(f"{PREFIX}/jobs", status_code=201)
    def create_job(file: UploadFile, alt_text_too: bool = Query(False, alias="alt_text"),
                   data_class: str = Query("I")) -> dict:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUFFIXES:
            raise HTTPException(415, "upload a PDF, PPTX or DOCX file")
        if data_class not in DATA_CLASSES:
            raise HTTPException(422, "data_class must be P, I or S")
        data = file.file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "files up to 50 MB")
        job_id = secrets.token_hex(6)
        folder = root / job_id
        folder.mkdir()
        source = f"source{suffix}"
        (folder / source).write_bytes(data)
        try:
            doc = parse(folder / source)
        except Exception as error:
            for p in folder.iterdir():
                p.unlink()
            folder.rmdir()
            raise HTTPException(422, f"could not read that file: {type(error).__name__}") from error
        documents[job_id] = doc
        issues = audit(doc)
        with lock:
            fixes = workers.propose_fixes(doc, data_class=data_class, issues=issues)
            alts = alt_text.propose(doc, data_class=data_class) if alt_text_too else []
        job = {
            "id": job_id, "name": Path(file.filename or f"document{suffix}").name, "format": doc.source_format,
            "source": source, "data_class": data_class, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "issues": report_dict(doc, issues, file.filename or ""),
            "fixes": [{"id": i, **asdict(f)} for i, f in enumerate(fixes)],
            "alt_texts": [{"id": i, **asdict(a)} for i, a in enumerate(alts)],
            "decisions": {"fixes": {}, "alt_texts": {}},
            "result": None,
        }
        (folder / f"{Path(job['name']).stem}.report.md").write_text(report_markdown(doc, issues, job["name"]), encoding="utf-8")
        save(job)
        return summary(job)

    @app.get(f"{PREFIX}/jobs")
    def list_jobs() -> list[dict]:
        jobs = [json.loads(p.read_text(encoding="utf-8")) for p in root.glob("*/job.json")]
        return [summary(j) for j in sorted(jobs, key=lambda j: j["created"], reverse=True)]

    @app.get(f"{PREFIX}/jobs/{{job_id}}")
    def get_job(job_id: str) -> dict:
        job = load(job_id)
        return {**job, "summary": summary(job), "outputs": _outputs(root / job_id, job["name"])}

    @app.get(f"{PREFIX}/jobs/{{job_id}}/images/{{block}}")
    def image(job_id: str, block: int) -> Response:
        doc = document(load(job_id))
        if not 0 <= block < len(doc.blocks) or not isinstance(doc.blocks[block], Image):
            raise HTTPException(404, "no image at that block")
        img = doc.blocks[block]
        media = MEDIA_TYPES.get(img.format.lower(), "application/octet-stream")
        return Response(img.data, media_type=media, headers={"Cache-Control": "private, max-age=3600"})

    @app.post(f"{PREFIX}/jobs/{{job_id}}/decisions")
    def decide(job_id: str, body: dict) -> dict:
        job = load(job_id)
        for kind in ("fixes", "alt_texts"):
            for key, decision in (body.get(kind) or {}).items():
                if not (isinstance(decision, dict) and decision.get("decision") in ("approve", "reject", None)):
                    raise HTTPException(422, "a decision is approve, reject or null")
                if not str(key).isdigit() or int(key) >= len(job[kind]):
                    raise HTTPException(422, f"no proposal {key} in {kind}")
                if decision.get("decision") is None:
                    job["decisions"][kind].pop(str(key), None)
                else:
                    job["decisions"][kind][str(key)] = {k: v for k, v in decision.items() if k in ("decision", "value", "alt", "decorative")}
        job["result"] = None  # decisions changed: the last rebuild no longer reflects them
        save(job)
        return {"decisions": job["decisions"]}

    @app.post(f"{PREFIX}/jobs/{{job_id}}/rebuild")
    def rebuild_job(job_id: str) -> dict:
        job = load(job_id)
        doc = document(job)
        fixes, alts = _approved(job)
        folder, stem = root / job_id, Path(job["name"]).stem
        fixed = rebuild.apply(doc, fixes, alts)
        notes = rebuild.to_docx(fixed, folder / f"{stem}.docx")
        (folder / f"{stem}.html").write_text(rebuild.to_html(fixed), encoding="utf-8")
        _, after = rebuild.verify(folder / f"{stem}.docx")
        before = [_issue(i) for i in job["issues"]["issues"]]
        waiting = [Fix(**_strip(p)) for p in job["fixes"] if _waiting(job, "fixes", p)]
        waiting_alts = [AltText(**_strip(p)) for p in job["alt_texts"] if _waiting(job, "alt_texts", p)]
        review = workers.report_markdown(waiting, job["name"])
        if job["alt_texts"]:
            review += "\n" + alt_text.report_markdown(waiting_alts, job["name"])
        (folder / f"{stem}.review.md").write_text(review, encoding="utf-8")
        applied, waiting_n = len(fixes) + len(alts), len(waiting) + len(waiting_alts)
        (folder / f"{stem}.statement.md").write_text(
            rebuild.statement(job["name"], before, after, applied, waiting_n, notes), encoding="utf-8")
        result = {**rebuild.compare(before, after), "applied": applied, "waiting": waiting_n, "notes": notes,
                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        job["result"] = result
        save(job)
        return {"result": result, "outputs": _outputs(folder, job["name"])}

    @app.get(f"{PREFIX}/jobs/{{job_id}}/files/{{name}}")
    def download(job_id: str, name: str) -> FileResponse:
        folder = job_dir(job_id)
        stem = Path(load(job_id)["name"]).stem
        if name not in {f"{stem}.{ext}" for ext in OUTPUTS} or not (folder / name).is_file():
            raise HTTPException(404, "no such output")
        return FileResponse(folder / name, filename=name)

    @app.delete(f"{PREFIX}/jobs/{{job_id}}", status_code=204)
    def delete_job(job_id: str) -> Response:
        folder = job_dir(job_id)
        for p in folder.iterdir():
            p.unlink()
        folder.rmdir()
        documents.pop(job_id, None)
        return Response(status_code=204)

    return app


def _strip(proposal: dict) -> dict:
    return {k: v for k, v in proposal.items() if k != "id"}


def _issue(data: dict):
    from campus_ai.course_access.audit import Issue

    return Issue(**{k: data[k] for k in ("rule", "criterion", "message", "fix", "page", "block")})


def _waiting(job: dict, kind: str, proposal: dict) -> bool:
    decision = job["decisions"][kind].get(str(proposal["id"]), {}).get("decision")
    return decision is None and proposal["needs_review"]


def _approved(job: dict) -> tuple[list[Fix], list[AltText]]:
    """What a rebuild applies: approvals (with edits) and undisputed rule-based proposals."""
    fixes, alts = [], []
    for p in job["fixes"]:
        d = job["decisions"]["fixes"].get(str(p["id"]), {})
        if d.get("decision") == "reject" or (d.get("decision") is None and p["needs_review"]):
            continue
        fix = Fix(**_strip(p))
        if d.get("decision") == "approve" and "value" in d:
            fix.value = d["value"]
        if fix.value is not None:
            fixes.append(fix)
    for p in job["alt_texts"]:
        d = job["decisions"]["alt_texts"].get(str(p["id"]), {})
        if d.get("decision") == "reject" or (d.get("decision") is None and p["needs_review"]):
            continue
        alt = AltText(**_strip(p))
        if d.get("decision") == "approve":
            if "decorative" in d:
                alt.decorative = bool(d["decorative"])
            if "alt" in d:
                alt.alt = "" if alt.decorative else str(d["alt"])
        if alt.alt or alt.decorative:
            alts.append(alt)
    return fixes, alts


def _outputs(folder: Path, name: str) -> list[str]:
    stem = Path(name).stem
    return [f"{stem}.{ext}" for ext in OUTPUTS if (folder / f"{stem}.{ext}").is_file()]


app = create_app()
