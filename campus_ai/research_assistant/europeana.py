"""Turn Europeana search results into graph records (R8).

Each openly licensed item becomes:

    (Item)-[:IN]->(Collection)-[:HELD_BY]->(Institution)
    (Item)-[:CREATED_BY]->(Creator)
    (Image)-[:PART_OF]->(Item)          when a thumbnail was downloaded

The Item carries the title and description as text; its Image is a
separate search unit embedded from the picture alone. Records use the JSONL
format of `scripts/graph_search.py`, so `index` loads them unchanged.
"""

from __future__ import annotations

import re
from typing import Any

SOURCE = "europeana"
MAX_TEXT = 2000

# Rights statements that allow reuse with at most attribution and share-alike.
OPEN_RIGHTS = (
    "creativecommons.org/publicdomain/zero/",
    "creativecommons.org/publicdomain/mark/",
    "creativecommons.org/licenses/by/",
    "creativecommons.org/licenses/by-sa/",
)


def is_open(rights: str) -> bool:
    return any(pattern in rights for pattern in OPEN_RIGHTS)


def first(item: dict, key: str) -> str:
    values = item.get(key) or [""]
    return str(values[0]).strip()


def unique(values: list[Any]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        text = re.sub(r"\s+", " ", str(value)).strip()
        if text and text.lower() not in (key.lower() for key in seen):
            seen[text] = None
    return list(seen)


def slug(value: str) -> str:
    return re.sub(r"[\W_]+", "-", value.lower()).strip("-")


def to_records(item: dict, image: str | None = None) -> list[dict]:
    """Graph records for one search result (profile=rich); [] unless openly licensed.

    `image` is the downloaded thumbnail's path relative to the JSONL file.
    """
    rights = first(item, "rights")
    if not is_open(rights):
        return []
    item_id = f"{SOURCE}:{item['id']}"
    text = "\n".join(unique(item.get("title", []) + item.get("dcDescription", [])))[:MAX_TEXT]
    props = {
        "source": SOURCE,
        # The API's guid carries tracking parameters, the API key among them: keep the bare page URL.
        "url": item.get("guid", f"https://www.europeana.eu/item{item['id']}").split("?")[0],
        "rights": rights,
        "type": item.get("type", ""),
        "provider": first(item, "provider"),
        "year": first(item, "year"),
        "language": first(item, "language"),
    }
    records = [{"id": item_id, "label": "Item", "modality": "text", "content": text, "props": props}]

    if image:
        records.append({"id": f"{item_id}#image", "label": "Image", "modality": "image", "content": image,
                        "props": {"source": SOURCE, "rights": rights}})
        records.append({"src": f"{item_id}#image", "type": "PART_OF", "dst": item_id})

    dataset, holder = first(item, "edmDatasetName"), first(item, "dataProvider")
    if dataset:
        collection_id = f"{SOURCE}:collection:{dataset}"
        records.append({"id": collection_id, "label": "Collection", "modality": "text", "content": dataset,
                        "props": {"source": SOURCE}})
        records.append({"src": item_id, "type": "IN", "dst": collection_id})
        if holder:
            holder_id = f"{SOURCE}:institution:{slug(holder)}"
            records.append({"id": holder_id, "label": "Institution", "modality": "text", "content": holder,
                            "props": {"source": SOURCE}})
            records.append({"src": collection_id, "type": "HELD_BY", "dst": holder_id})

    for creator in unique(item.get("dcCreator", [])):
        if creator.startswith("http"):  # vocabulary URIs; the name is listed alongside
            continue
        creator_id = f"{SOURCE}:creator:{slug(creator)}"
        records.append({"id": creator_id, "label": "Creator", "modality": "text", "content": creator,
                        "props": {"source": SOURCE}})
        records.append({"src": item_id, "type": "CREATED_BY", "dst": creator_id})
    return records
