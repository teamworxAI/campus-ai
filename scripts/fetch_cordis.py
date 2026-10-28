"""Download Horizon Europe projects (CORDIS) and call topics (Funding & Tenders) into DATA_DIR/cordis/horizon/ (R2).

Two bulk files, no key: the Publications Office's CORDIS project bundle
(about 40 MB, monthly) and the portal's grants reference file (about 130 MB,
daily). Both are EU open data (CC BY 4.0). Then the details page of each open
and forthcoming topic (description with expected outcome and scope,
conditions, budget) from the portal's topicDetails JSON, one small request at
a time, cached in topics/<identifier>.json for the call analyst (R4). Writes
records.jsonl for `graph_search.py index`: projects, organisations,
EuroSciVoc topics, programme parts and call topics with their links.

    docker compose run --rm fetch-cordis                      # everything (24k projects, 36k organisations)
    docker compose run --rm fetch-cordis --max-projects 2000  # the most recent 2000 projects, for a quick graph
    docker compose run --rm fetch-cordis --topics none        # skip the topic pages
    docker compose run --rm embed python scripts/graph_search.py index data/cordis/horizon/records.jsonl
    docker compose run --rm embed python scripts/graph_search.py index data/cordis/horizon/records.jsonl --label CallTopic

Downloaded files are kept; --force fetches them again.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from campus_ai.research_assistant.cordis import horizon_topic, to_records

PROJECTS_URL = "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip"
GRANTS_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json"
TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/{}.json"
USER_AGENT = "campus-ai/0.1 fetch-cordis (https://github.com/teamworxAI/campus-ai)"
TABLES = ("project.csv", "organization.csv", "euroSciVoc.csv", "topics.csv", "legalBasis.csv")
# Whose topic pages to fetch: "current" (open and forthcoming, a few hundred) is the default; "all" adds closed ones.
TOPIC_STATUS = {"current": {"Open", "Forthcoming"}, "open": {"Open"}, "forthcoming": {"Forthcoming"}, "all": None, "none": set()}
PAUSE = 0.5  # seconds between topic requests: sequential and polite


def download(url: str, target: Path, force: bool) -> None:
    if target.exists() and not force:
        print(f"  kept {target.name} ({target.stat().st_size / 1e6:.0f} MB)")
        return
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=600) as response, target.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    print(f"  downloaded {target.name} ({target.stat().st_size / 1e6:.0f} MB)")


def tables(bundle: Path) -> dict[str, list[dict]]:
    """The CSV tables of the CORDIS bundle as lists of rows (semicolon separated, UTF-8)."""
    out = {}
    with zipfile.ZipFile(bundle) as z:
        for name in TABLES:
            text = z.read(name).decode("utf-8", "replace")
            out[name] = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    return out


def grants(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)["fundingData"]["GrantTenderObj"]


def fetch_topics(items: list[dict], folder: Path, statuses: set | None, force: bool = False) -> dict:
    """Cache the topicDetails JSON of each Horizon topic whose status is in `statuses` (None: every status)."""
    folder.mkdir(parents=True, exist_ok=True)
    counts = {"fetched": 0, "kept": 0, "failed": 0}
    wanted = [item["identifier"] for item in items if horizon_topic(item)
              and (statuses is None or (item.get("status") or {}).get("abbreviation") in statuses)]
    for identifier in dict.fromkeys(wanted):
        target = folder / f"{identifier}.json"
        if target.exists() and not force:
            counts["kept"] += 1
            continue
        if counts["fetched"] or counts["failed"]:
            time.sleep(PAUSE)
        request = urllib.request.Request(TOPIC_URL.format(identifier.lower()), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get("TopicDetails"), dict):
                raise ValueError("no TopicDetails in the answer")
        except Exception as error:  # one missing page never stops the run
            counts["failed"] += 1
            print(f"  skipped {identifier}: {type(error).__name__}: {str(error)[:120]}")
            continue
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        counts["fetched"] += 1
    print(f"  topic details: {counts['fetched']} fetched, {counts['kept']} kept, {counts['failed']} failed")
    return counts


def topic_details(folder: Path) -> dict[str, dict]:
    """The cached TopicDetails objects by identifier; unreadable files are skipped."""
    out = {}
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            detail = json.loads(path.read_text(encoding="utf-8")).get("TopicDetails")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(detail, dict):
            out[detail.get("identifier") or path.stem] = detail
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-projects", type=int, default=0, help="keep only the N most recently started projects (0: all)")
    parser.add_argument("--topics", choices=list(TOPIC_STATUS), default="current",
                        help="whose topic pages to fetch: current (open and forthcoming, the default), open, forthcoming, all or none")
    parser.add_argument("--force", action="store_true", help="download the files again")
    args = parser.parse_args(argv)
    out = Path(os.environ.get("DATA_DIR", "data")) / "cordis" / "horizon"
    out.mkdir(parents=True, exist_ok=True)
    download(PROJECTS_URL, out / "cordis-HORIZONprojects-csv.zip", args.force)
    download(GRANTS_URL, out / "grantsTenders.json", args.force)
    calls = grants(out / "grantsTenders.json")
    if args.topics != "none":
        started = time.monotonic()
        fetch_topics(calls, out / "topics", TOPIC_STATUS[args.topics], args.force)
        print(f"  topic pages took {time.monotonic() - started:.0f} s")
    data = tables(out / "cordis-HORIZONprojects-csv.zip")
    projects = data["project.csv"]
    if args.max_projects:
        projects = sorted(projects, key=lambda p: p.get("startDate") or "", reverse=True)[:args.max_projects]
    records = to_records(projects, data["organization.csv"], data["euroSciVoc.csv"], data["topics.csv"],
                         data["legalBasis.csv"], calls, topic_details(out / "topics"))
    with (out / "records.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    labels = {}
    for r in records:
        if "label" in r:
            labels[r["label"]] = labels.get(r["label"], 0) + 1
    described = sum(1 for r in records if r.get("label") == "CallTopic" and r["props"].get("scope"))
    print(f"{len(projects)} projects -> {out / 'records.jsonl'}: "
          + ", ".join(f"{n} {label}" for label, n in sorted(labels.items())) + f", {sum('src' in r for r in records)} links"
          + f"; {described} call topics with a description")
    return 0


if __name__ == "__main__":
    sys.exit(main())
