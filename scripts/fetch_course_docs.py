"""Download openly licensed course documents for the Course Access gold set (A6).

The one network step for Course Access, like `fetch-europeana` for the
Research Assistant. SOURCES lists real lecture slides, lecture notes, course
outlines and readings published by universities under CC BY or CC BY-SA, with
their attribution. Each file lands in DATA_DIR/course_access/<source>/ and is
recorded in manifest.jsonl (URL, title, authors, licence, sha256, format), so
every document in the gold set can be traced to its source and licence.
Zip archives are opened and only PDF, PPTX and DOCX members are kept.

Only documents under OSI-style open content licences (CC BY, CC BY-SA, CC0,
public domain) are listed. Non-commercial (NC) and no-derivatives (ND) material
is left out; the decision to use any such set is the team's, not this script's.
Nothing is modified: the files are evaluation input, never training data.

    docker compose run --rm fetch-course-docs            # into DATA_DIR/course_access
    docker compose run --rm fetch-course-docs --force    # re-download files already there
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

OPEN_LICENCES = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "PDM-1.0": "https://creativecommons.org/publicdomain/mark/1.0/",
}
FORMATS = ("pdf", "pptx", "docx")
# Repositories behind a bot check (e.g. CUNY Academic Works) answer 403 whatever the agent;
# they are not listed. Their files can be downloaded by hand into DATA_DIR/course_access.
USER_AGENT = "campus-ai/0.1 fetch-course-docs (open educational resources for an accessibility evaluation set)"

ECO = "https://openlibrary-repo.ecampusontario.ca/jspui/bitstream/123456789"

# One entry per download. `source` is the folder; `name` the file name to save as
# (the format is detected from the bytes, so no extension is needed here).
SOURCES = [
    # eCampusOntario Open Library (DSpace), CC BY 4.0
    dict(source="ecampusontario-oer101", name="oer-101-module-1", url=f"{ECO}/2594/1/OER%20101%20Module%201.pdf",
         title="OER 101: Module 1", authors="Sarah Coysh, Stephanie Quail", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/2594"),
    dict(source="olds-profcomm-m1", name="foundations-lecture-notes",
         url=f"{ECO}/364/3/Foundations%20Lecture%20Notes.docx",
         title="Professional Communications OER, Module 1: Foundations, lecture notes",
         authors="Olds College OER Development Team", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/364"),
    dict(source="olds-profcomm-m1", name="foundations-etextbook", url=f"{ECO}/364/1/eTextbookPart1Foundations.pdf",
         title="Professional Communications OER, Module 1: Foundations, e-textbook",
         authors="Olds College OER Development Team", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/364"),
    dict(source="olds-profcomm-m1", name="foundations-slides", url=f"{ECO}/364/5/PowerPoint%20Slides.zip",
         title="Professional Communications OER, Module 1: Foundations, PowerPoint slides",
         authors="Olds College OER Development Team", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/364"),
    dict(source="olds-profcomm-m3", name="presentations-lecture-notes",
         url=f"{ECO}/367/2/Lecture%20Notes%20%28Presentations%29.docx",
         title="Professional Communications OER, Module 3: Presentations, lecture notes",
         authors="Olds College OER Development Team", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/367"),
    dict(source="olds-profcomm-m3", name="presentations-etextbook",
         url=f"{ECO}/367/1/eTextbookPart3Presentations.pdf",
         title="Professional Communications OER, Module 3: Presentations, e-textbook",
         authors="Olds College OER Development Team", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/367"),
    dict(source="olds-profcomm-m3", name="presentations-slides", url=f"{ECO}/367/4/Lecture%20Slides.zip",
         title="Professional Communications OER, Module 3: Presentations, lecture slides",
         authors="Olds College OER Development Team", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/367"),
    dict(source="ontariotech-edst3440u", name="week-02-slides",
         url=f"{ECO}/2178/10/Week-2-Slides---EDST-3440U-Managing-and-Developing-eLearning-Projects-4e921346-8bb4-4eeb-9af3-1a9961d59c69.pptx",
         title="EDST 3440U Managing and Developing eLearning Projects, week 2 slides",
         authors="Natalie Tremblay McDonnell, Brandon Carson, Diane Tepylo", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/2178"),
    dict(source="ontariotech-edst3440u", name="week-10-slides",
         url=f"{ECO}/2178/3/Week-10-Slides---EDST-3440U-Managing-and-Developing-eLearning-Projects-ccce5126-74bf-4ae2-a039-31e6f984d16a.pptx",
         title="EDST 3440U Managing and Developing eLearning Projects, week 10 slides",
         authors="Natalie Tremblay McDonnell, Brandon Carson, Diane Tepylo", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/2178"),
    dict(source="ontariotech-edst3440u", name="week-12-slides",
         url=f"{ECO}/2178/1/Week-12-Slides---EDST-3440U-Managing-and-Developing-eLearning-Projects-c3846c11-ec74-4cf4-b443-a00e837a3ff2.pptx",
         title="EDST 3440U Managing and Developing eLearning Projects, week 12 slides",
         authors="Natalie Tremblay McDonnell, Brandon Carson, Diane Tepylo", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/2178"),
    dict(source="ontariotech-edst3440u", name="course-outline",
         url=f"{ECO}/2178/11/Course-Outline---EDST-3440U-Managing-and-Developing-eLearning-Projects-a86b38b5-4f8b-4b0c-9701-cb32eb020b2d.docx",
         title="EDST 3440U Managing and Developing eLearning Projects, course outline",
         authors="Natalie Tremblay McDonnell, Brandon Carson, Diane Tepylo", licence="CC-BY-4.0",
         page="https://openlibrary-repo.ecampusontario.ca/jspui/handle/123456789/2178"),
    # UCL Open Education Repository, CC BY-SA 4.0
    dict(source="ucl-open-education", name="introduction-to-open-education",
         url="https://open-education-repository.ucl.ac.uk/id/document/1014",
         title="Introduction to Open Education, OER, and what UCL is doing",
         authors="June Hedges, C. Yogeswaran, Clive Young", licence="CC-BY-SA-4.0",
         page="https://open-education-repository.ucl.ac.uk/166"),
]


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "course_access"


def detect_format(data: bytes) -> str | None:
    """pdf, pptx, docx or zip from the bytes themselves; None for anything else."""
    if data.startswith(b"%PDF"):
        return "pdf"
    if not data.startswith(b"PK"):
        return None
    try:
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return None
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    if any(n.startswith("word/") for n in names):
        return "docx"
    return "zip"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as resp:
        return resp.read()


def unpack(data: bytes) -> list[tuple[str, bytes]]:
    """(member name, bytes) for the PDF, PPTX and DOCX members of a zip, folders flattened."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = Path(info.filename).name
            if info.is_dir() or name.startswith(".") or "__MACOSX" in info.filename:
                continue
            member = archive.read(info)
            if detect_format(member) in FORMATS:
                out.append((name, member))
    return out


def save(entry: dict, name: str, data: bytes, fmt: str, root: Path, force: bool) -> dict | None:
    folder = root / entry["source"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{Path(name).stem}.{fmt}"
    if path.exists() and not force:
        print(f"  kept {path.relative_to(root)}")
        return None
    path.write_bytes(data)
    print(f"  saved {path.relative_to(root)} ({len(data) / 1e6:.1f} MB)")
    return {
        "path": path.relative_to(root).as_posix(), "format": fmt, "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "url": entry["url"], "page": entry["page"],
        "title": entry["title"], "authors": entry["authors"], "licence": entry["licence"],
        "licence_url": OPEN_LICENCES[entry["licence"]], "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def fetch(entry: dict, root: Path, force: bool) -> list[dict]:
    if entry["licence"] not in OPEN_LICENCES:
        raise ValueError(f"{entry['title']}: licence {entry['licence']} is not an open content licence")
    print(f"{entry['title']} [{entry['licence']}]")
    data = download(entry["url"])
    fmt = detect_format(data)
    if fmt == "zip":
        members = unpack(data)
        if not members:
            raise ValueError(f"{entry['url']}: no PDF, PPTX or DOCX inside the archive")
        records = [save(entry, f"{entry['name']}-{name}", member, detect_format(member), root, force)
                   for name, member in members]
    elif fmt in FORMATS:
        records = [save(entry, entry["name"], data, fmt, root, force)]
    else:
        raise ValueError(f"{entry['url']}: not a PDF, PPTX, DOCX or zip (starts with {data[:8]!r})")
    return [r for r in records if r]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-download files that are already there")
    parser.add_argument("--only", help="fetch only sources whose folder name contains this text")
    args = parser.parse_args(argv)
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    records, failures = [], []
    for entry in SOURCES:
        if args.only and args.only not in entry["source"]:
            continue
        try:
            records += fetch(entry, root, args.force)
        except Exception as exc:  # one bad source must not stop the rest
            failures.append(f"{entry['title']}: {type(exc).__name__}: {exc}")
            print(f"  FAILED: {exc}")
    if records:
        with (root / "manifest.jsonl").open("a", encoding="utf-8") as out:
            for record in records:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\n{len(records)} new files in {root}; manifest.jsonl records every file, its source and licence.")
    for failure in failures:
        print("FAILED", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
