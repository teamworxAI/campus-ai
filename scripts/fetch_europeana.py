"""Download openly licensed Europeana items and thumbnails for the graph (R8).

Needs the network and EUROPEANA_API_KEY, like `fetch-models`; indexing then
runs offline in the embed service:

    docker compose run --rm fetch-europeana --query salmon --rows 300
    docker compose run --rm embed python scripts/graph_search.py index data/europeana/salmon/items.jsonl

Writes data/europeana/<name>/items.jsonl and media/ (thumbnails, 400 px wide,
served by api.europeana.eu). Re-running skips thumbnails already on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from campus_ai.research_assistant.europeana import is_open, slug, to_records

SEARCH = "https://api.europeana.eu/record/v2/search.json"
PAGE = 100  # the API's maximum


def get(url: str, key: str | None = None) -> tuple[str, bytes]:
    # The key goes in a header, never the URL, so it stays out of logs.
    request = urllib.request.Request(url, headers={"X-Api-Key": key} if key else {})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.headers.get_content_type(), response.read()


def search(key: str, query: str, rows: int, filters: list[str]):
    """Yield up to `rows` openly reusable items with media, following the cursor."""
    cursor, seen = "*", 0
    while cursor and seen < rows:
        params = [("query", query), ("reusability", "open"), ("media", "true"), ("profile", "rich"),
                  ("rows", min(PAGE, rows - seen)), ("cursor", cursor)] + [("qf", f) for f in filters]
        _, body = get(f"{SEARCH}?{urllib.parse.urlencode(params)}", key)
        page = json.loads(body)
        for item in page.get("items", []):
            seen += 1
            yield item
        cursor = page.get("nextCursor")


def thumbnail(item: dict, media: Path) -> Path | None:
    """The item's thumbnail on disk, downloading it if needed; None if unavailable."""
    preview = (item.get("edmPreview") or [""])[0]
    if not preview.startswith("https://api.europeana.eu/thumbnail/") or item.get("type") != "IMAGE":
        return None
    path = media / f"{hashlib.sha1(item['id'].encode()).hexdigest()[:16]}.jpg"
    if not path.exists():
        try:
            kind, body = get(preview + "&size=w400")
        except OSError as error:
            print(f"  no thumbnail for {item['id']}: {error}")
            return None
        if not kind.startswith("image/"):
            return None
        path.write_bytes(body)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--query", default="salmon")
    parser.add_argument("--qf", action="append", default=[], help="extra filter, e.g. TYPE:IMAGE")
    parser.add_argument("--rows", type=int, default=300)
    parser.add_argument("--name", help="output folder under data/europeana (default: from the query)")
    parser.add_argument("--out", type=Path, default=Path("data/europeana"))
    args = parser.parse_args()
    key = os.environ.get("EUROPEANA_API_KEY")
    if not key:
        raise SystemExit("set EUROPEANA_API_KEY in .env")

    folder = args.out / (args.name or slug(args.query))
    media = folder / "media"
    media.mkdir(parents=True, exist_ok=True)
    records, items, images = {}, 0, 0
    for item in search(key, args.query, args.rows, args.qf):
        if not is_open((item.get("rights") or [""])[0]):
            continue
        image = thumbnail(item, media)
        for record in to_records(item, image and str(image.relative_to(folder))):
            # Shared nodes (collections, institutions, creators) appear once.
            records[record.get("id") or (record["src"], record["type"], record["dst"])] = record
        items, images = items + 1, images + bool(image)
    with open(folder / "items.jsonl", "w", encoding="utf-8") as out:
        for record in records.values():
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"{items} items ({images} with thumbnails) -> {folder / 'items.jsonl'}")


if __name__ == "__main__":
    main()
