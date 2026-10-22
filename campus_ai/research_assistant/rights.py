"""Rights and governance filter ahead of collections indexing (R10).

Every harvested record gets a data class (plan section 2) before anything is
embedded: P (public) when it is openly licensed and carries no access limit
or Indigenous-protocol marker, R (restricted) otherwise. Class R is never
embedded or sent to any model; its record stays only in the harvested JSONL,
as a metadata link back to the source.

Fields read from a record's `props` (the shared JSONL format):

- `source`: the collection it was harvested from (`europeana`, later
  `arcabc`). Records without one are the repo's own fixtures, not harvested
  content, so they need no rights statement; the markers below still apply.
- `rights`: the item's rights statement URI (Europeana `edm:rights`). Open
  means CC0, Public Domain Mark, CC BY or CC BY-SA, as in R8; anything else,
  missing included, is class R.
- `access`: an access limit (ArcaBC); anything but empty or "open" is class R.
- `tk_labels`: Traditional Knowledge or Biocultural Labels and Notices (Local
  Contexts) or any other community-protocol marker; any value is class R.

Only content units (Item and Image) need an open rights statement. Units
that are PART_OF a restricted item are restricted with it, and metadata nodes
(collections, institutions, creators) are kept only when linked to something
kept, so nothing about a restricted item reaches the index.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from campus_ai.core.graph import Link, Node

# Rights statements that allow reuse with at most attribution and share-alike.
OPEN_RIGHTS = (
    "creativecommons.org/publicdomain/zero/",
    "creativecommons.org/publicdomain/mark/",
    "creativecommons.org/licenses/by/",
    "creativecommons.org/licenses/by-sa/",
)
UNITS = {"Item", "Image"}
OPEN_ACCESS = {"", "open"}


def is_open(rights: str) -> bool:
    return any(pattern in rights for pattern in OPEN_RIGHTS)


def classify(props: dict[str, Any], unit: bool = True) -> tuple[str, str]:
    """("P", "") or ("R", reason) for one record's props."""
    access = str(props.get("access") or "").strip().lower()
    if access not in OPEN_ACCESS:
        return "R", "access limit"
    rights = str(props.get("rights") or "")
    if props.get("tk_labels") or "localcontexts.org" in rights:
        return "R", "TK Label or community protocol"
    if unit and props.get("source") and not is_open(rights):
        return "R", "rights not open" if rights else "rights unknown"
    return "P", ""


@dataclass
class Screened:
    nodes: list[Node]
    links: list[Link]
    excluded: list[tuple[Node, str]] = field(default_factory=list)  # class R, with the reason

    def report(self) -> str:
        reasons = Counter(reason for _, reason in self.excluded)
        detail = "".join(f"; {n} {reason}" for reason, n in sorted(reasons.items()))
        items = sum(node.label == "Item" for node in self.nodes)
        excluded = sum(node.label == "Item" for node, _ in self.excluded)
        return (
            f"rights filter: kept {items} items ({len(self.nodes)} nodes), "
            f"excluded {excluded} items ({len(self.excluded)} nodes) as class R{detail}"
        )


def screen(nodes: list[Node], links: list[Link]) -> Screened:
    """Drop class-R records, and links touching them, before indexing."""
    reasons = {}
    for node in nodes:
        data_class, reason = classify(node.props, unit=node.label in UNITS)
        if data_class == "R":
            reasons[node.id] = reason
    for link in links:  # images and other parts of a restricted item
        if link.type == "PART_OF" and link.dst in reasons and link.src not in reasons:
            reasons[link.src] = "part of a restricted item"

    # Metadata nodes stay only when linked, directly or through other metadata, to a kept unit.
    by_id = {node.id: node for node in nodes}
    metadata = {node.id for node in nodes if node.label not in UNITS and node.props.get("source")}
    kept = {node.id for node in nodes if node.id not in reasons and node.id not in metadata}
    grew = True
    while grew:
        grew = False
        for link in links:
            for a, b in ((link.src, link.dst), (link.dst, link.src)):
                if a in kept and b in metadata and b not in kept and b not in reasons:
                    kept.add(b)
                    grew = True
    for id_ in metadata - kept:
        reasons.setdefault(id_, "only linked to restricted items")

    return Screened(
        nodes=[node for node in nodes if node.id in kept],
        links=[link for link in links if link.src not in reasons and link.dst not in reasons],
        excluded=[(by_id[id_], reason) for id_, reason in reasons.items() if id_ in by_id],
    )
