"""Harvest one institution's recent works from OpenAlex into DATA_DIR/openalex/<name>/ (R1).

The one network step for the Research Assistant's researcher data (public,
CC0). Writes works.jsonl (the trimmed API records) and records.jsonl (graph
records for `graph_search.py index`: researchers, publications, topics,
SDGs, institution and their links). Papers with more than --max-authors
authors are left out: they say nothing about individual expertise.

Works are taken year by year, the --per-year most cited of each: ranked
over all years at once, older papers (more time to be cited) crowd out
recent ones and the researchers who only have recent ones.

    docker compose run --rm fetch-openalex                       # SFU, 2021 to this year, 1200 most-cited a year
    docker compose run --rm fetch-openalex --ror 03rmrcq20 --name ubc --per-year 100
    docker compose run --rm embed python scripts/graph_search.py index data/openalex/sfu/records.jsonl

OpenAlex meters its API: without a key, one small daily budget is shared by
everyone behind your IP address (about one page of 200 works); a free key
(https://openalex.org/settings/api) has its own. OPENALEX_API_KEY (.env) is
sent only to api.openalex.org. When the budget runs out mid-harvest, the
works collected so far are kept and mapped, and the exit code is 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from campus_ai.research_assistant.openalex import to_records, trim

API = "https://api.openalex.org"
SFU_ROR = "0213rcc28"
PAGE = 200
USER_AGENT = "campus-ai/0.1 fetch-openalex (https://github.com/teamworxAI/campus-ai)"


def get(path: str, params: dict) -> dict:
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        params = {**params, "api_key": key}
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def works(ror: str, year: int, max_works: int, max_authors: int):
    """The institution's works published in `year`, most cited first, trimmed; stops at max_works."""
    filters = f"authorships.institutions.ror:{ror},publication_year:{year},authors_count:<{max_authors + 1}"
    cursor, seen = "*", 0
    while cursor and seen < max_works:
        page = get("works", {"filter": filters, "sort": "cited_by_count:desc", "per-page": min(PAGE, max_works - seen),
                             "cursor": cursor, "select": ",".join(trim.__globals__["WORK_FIELDS"])})
        for work in page.get("results", []):
            yield trim(work)
            seen += 1
            if seen >= max_works:
                return
        cursor = (page.get("meta") or {}).get("next_cursor")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ror", default=SFU_ROR, help="the institution's ROR id (default: Simon Fraser University)")
    parser.add_argument("--name", default="sfu", help="folder name under DATA_DIR/openalex")
    parser.add_argument("--since", type=int, default=2021, help="first publication year")
    parser.add_argument("--until", type=int, default=date.today().year, help="last publication year (default: this year)")
    parser.add_argument("--per-year", type=int, default=1200, help="most-cited works taken from each year")
    parser.add_argument("--max-authors", type=int, default=30)
    args = parser.parse_args(argv)
    out = Path(os.environ.get("DATA_DIR", "data")) / "openalex" / args.name
    out.mkdir(parents=True, exist_ok=True)
    institution = get(f"institutions/ror:{args.ror}", {"select": "id,display_name,country_code"})
    print(f"{institution.get('display_name', args.ror)} ({institution.get('country_code', '?')})")
    collected, interrupted = [], None
    with (out / "works.jsonl").open("w", encoding="utf-8") as f:
        try:
            for year in range(args.since, args.until + 1):
                before = len(collected)
                for work in works(args.ror, year, args.per_year, args.max_authors):
                    f.write(json.dumps(work, ensure_ascii=False) + "\n")
                    collected.append(work)
                print(f"  {year}: {len(collected) - before} works")
        except urllib.error.HTTPError as error:  # the daily budget ran out, or the key was refused
            interrupted = f"HTTP {error.code} from OpenAlex after {len(collected)} works"
            if error.code in (401, 403, 429):
                interrupted += (": the free budget is used up or the key was refused; set OPENALEX_API_KEY in .env "
                                "(a free key at https://openalex.org/settings/api) or try again tomorrow")
            print(interrupted)
    records = to_records(collected, args.ror, args.max_authors)
    with (out / "records.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    labels = {}
    for r in records:
        if "label" in r:
            labels[r["label"]] = labels.get(r["label"], 0) + 1
    print(f"{len(collected)} works {args.since}-{args.until} ->{out / 'records.jsonl'}: "
          + ", ".join(f"{n} {label}" for label, n in sorted(labels.items())) + f", {sum('src' in r for r in records)} links")
    return 1 if interrupted else 0


if __name__ == "__main__":
    sys.exit(main())
