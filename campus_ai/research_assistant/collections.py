"""Collections search (R9): pictures and texts across indexed collections, with evidence.

Pictures and texts are ranked as separate lists: a text query always sits
closer to text than to an image, so a merged list would bury the pictures.
Every card carries what a citation needs: holder, creator, licence and the
source record's URL.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from campus_ai.core.graph import HybridRetriever

DATA_DIR = Path("data")
CANDIDATES = 50

LICENCES = (
    (r"publicdomain/zero/([\d.]+)", "CC0 {}"),
    (r"publicdomain/mark/", "Public domain"),
    (r"licenses/by-sa/([\d.]+)", "CC BY-SA {}"),
    (r"licenses/by/([\d.]+)", "CC BY {}"),
)

# Everything a card shows, for a list of item ids, in one query.
CARDS = """
UNWIND $ids AS id
MATCH (i:Item {id: id})
OPTIONAL MATCH (image:Image)-[:PART_OF]->(i)
OPTIONAL MATCH (i)-[:IN]->(c:Collection)
OPTIONAL MATCH (c)-[:HELD_BY]->(h:Institution)
OPTIONAL MATCH (i)-[:CREATED_BY]->(p:Creator)
RETURN i.id AS id, i.text AS text, i.url AS url, i.rights AS rights, i.type AS type, i.year AS year,
       i.source AS source, i.provider AS provider, head(collect(DISTINCT image.file)) AS file,
       head(collect(DISTINCT c.text)) AS collection, head(collect(DISTINCT h.text)) AS holder,
       collect(DISTINCT p.text) AS creators
"""


@dataclass
class Card:
    id: str
    title: str
    description: str
    source: str
    type: str
    year: str
    url: str
    rights: str
    licence: str
    holder: str
    collection: str
    creators: list[str]
    image: str | None
    file: str | None = field(default=None, repr=False)
    matched: str = ""

    def public(self) -> dict:
        data = asdict(self)
        data.pop("file")
        return data


def licence(rights: str) -> str:
    for pattern, label in LICENCES:
        match = re.search(pattern, rights or "")
        if match:
            return label.format(*match.groups())
    return "See source"


def media_url(file: str | None) -> str | None:
    """Public URL for a media file under DATA_DIR; None for anything outside it."""
    if not file:
        return None
    path = Path(file)
    if path.is_absolute() or ".." in path.parts or path.parts[: len(DATA_DIR.parts)] != DATA_DIR.parts:
        return None
    return "/media/" + "/".join(path.parts[len(DATA_DIR.parts):])


def card(row: dict) -> Card:
    lines = [line for line in (row.get("text") or "").split("\n") if line.strip()]
    return Card(
        id=row["id"],
        title=lines[0] if lines else row["id"],
        description="\n".join(lines[1:]),
        source=row.get("source") or "",
        type=row.get("type") or "",
        year=row.get("year") or "",
        url=row.get("url") or "",
        rights=row.get("rights") or "",
        licence=licence(row.get("rights") or ""),
        holder=row.get("holder") or row.get("provider") or "",
        collection=row.get("collection") or "",
        creators=[name for name in row.get("creators") or [] if name.lower() not in ("unknown", "okänd")],
        image=media_url(row.get("file")),
        file=row.get("file"),
    )


def matched(found_by: list[str], picture: bool) -> str:
    parts = (["picture"] if picture else ["meaning"] if "meaning" in found_by else []) + (
        ["words"] if "words" in found_by else []
    )
    return " and ".join(parts).capitalize() or "Related"


def citations(c: Card) -> dict[str, str]:
    """APA, Chicago and BibTeX strings; deterministic, from the record alone."""
    who = "; ".join(c.creators) or c.holder or "Unknown"
    year = c.year or "n.d."
    kind = {"IMAGE": "Image", "TEXT": "Text", "VIDEO": "Video", "SOUND": "Sound recording"}.get(c.type, "Item")
    via = c.source.capitalize() if c.source else "Online collection"
    key = re.sub(r"\W+", "", (c.creators[0].split(",")[0] if c.creators else c.holder or "item")).lower()[:20]
    return {
        "apa": f"{who}. ({year}). {c.title} [{kind}]. {c.holder}. {via}. {c.url}",
        "chicago": f"{who}. {c.title}. {kind}. {c.holder}. {via}. {c.url}. Licence: {c.licence}.",
        "bibtex": (
            f"@misc{{{key}{c.year or ''},\n  author = {{{who}}},\n  title = {{{c.title}}},\n"
            f"  year = {{{year}}},\n  howpublished = {{{via}, {c.holder}}},\n  url = {{{c.url}}},\n"
            f"  note = {{{c.licence}: {c.rights}}}\n}}"
        ),
    }


class CollectionsSearch:
    def __init__(self, driver: Any, embedder: Any, database: str | None = None):
        self.driver = driver
        self.retriever = HybridRetriever(driver, embedder, database, candidates=CANDIDATES)
        self.database = database

    def run(self, query: str, **params: Any) -> list[dict]:
        records, _, _ = self.driver.execute_query(query, params, database_=self.database)
        return [record.data() for record in records]

    def cards(self, ids: list[str]) -> dict[str, Card]:
        return {row["id"]: card(row) for row in self.run(CARDS, ids=ids)} if ids else {}

    def pictures(self, query: Any, k: int = 12, modality: str = "text", exclude: str | None = None) -> list[Card]:
        """Items whose picture best matches a text query or an example image (file path)."""
        hits = self.retriever.search(query, k + 1, modality, labels=["Image"], neighbors=0)
        parents = [hit.id.split("#")[0] for hit in hits if hit.id.split("#")[0] != exclude][:k]
        words: set[str] = set()
        if modality == "text":  # did the item's own text also match the words?
            words = {hit.id for hit in self.retriever.search(query, CANDIDATES, labels=["Item"], neighbors=0)
                     if "words" in hit.found_by}
        cards = self.cards(parents)
        out = []
        for id_ in parents:
            if id_ in cards:
                cards[id_].matched = matched(["words"] if id_ in words else [], picture=True)
                out.append(cards[id_])
        return out

    def texts(self, query: str, k: int = 8) -> list[Card]:
        """Items without a picture (books, reports, film, sound), ranked on their text."""
        hits = self.retriever.search(query, CANDIDATES, labels=["Item"], neighbors=0)
        cards = self.cards([hit.id for hit in hits])
        out = []
        for hit in hits:
            c = cards.get(hit.id)
            if c and not c.image:
                c.matched = matched(hit.found_by, picture=False)
                out.append(c)
        return out[:k]

    def item(self, id_: str) -> dict | None:
        found = self.cards([id_]).get(id_)
        if not found:
            return None
        similar = self.pictures(found.file, 4, "image", exclude=id_) if found.file else []
        return {**found.public(), "citations": citations(found), "similar": [c.public() for c in similar]}

    def count(self) -> int:
        return self.run("MATCH (i:Item) RETURN count(i) AS n")[0]["n"]
