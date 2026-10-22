"""Index items into the graph and search them with the hybrid retriever.

JSONL input: the bake-off format, plus optional labels, captions and links.

    {"id": "d1", "label": "Item", "modality": "text", "content": "..."}
    {"id": "d2", "modality": "image", "content": "media/photo.jpg", "text": "caption"}
    {"src": "d2", "type": "IN", "dst": "c1"}
    {"query": "...", "lang": "fr", "relevant": ["d1"]}

Media paths are relative to the JSONL file. `index` first runs the rights
filter (R10, `campus_ai/research_assistant/rights.py`): class-R records are
never embedded, and the counts kept and excluded are printed; `rights` prints
the same report without embedding or Neo4j. Run in the embed service, which
reaches Neo4j over an internal network only:

    docker compose run --rm embed python scripts/graph_search.py rights evals/rights/sample_records.jsonl
    docker compose run --rm embed python scripts/graph_search.py index evals/embed/sample_bakeoff.jsonl
    docker compose run --rm embed python scripts/graph_search.py search "salmon and ocean warming"
    docker compose run --rm embed python scripts/graph_search.py eval evals/embed/sample_bakeoff.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from campus_ai.core.embed import BACKENDS, DEFAULT_BACKEND, get_embedder
from campus_ai.core.graph import GraphStore, HybridRetriever, Link, Node, connect
from campus_ai.research_assistant.rights import Screened, screen


def load(path: Path) -> tuple[list[Node], list[Link], list[dict]]:
    nodes, links, queries = [], [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if "query" in record:
            queries.append(record)
        elif "src" in record:
            links.append(Link(record["src"], record["type"], record["dst"], record.get("props", {})))
        else:
            modality, content = record.get("modality", "text"), record["content"]
            if modality == "text":
                text = record.get("text") or content
            else:  # media: index only a real caption, never the file path
                text, content = record.get("text", ""), str(path.parent / content)
            # A record may carry its data class (P/I/S/R); class R is refused before embedding.
            data_class = record.get("data_class", "P")
            nodes.append(
                Node(record["id"], record.get("label", "Item"), text, modality, content, record.get("props", {}), data_class)
            )
    return nodes, links, queries


def line(text: str | None, width: int) -> str:
    return " ".join((text or "").split())[:width]


def screened(path: Path) -> Screened:
    """The file's nodes and links with class-R records removed; prints what was excluded."""
    nodes, links, _ = load(path)
    result = screen(nodes, links)
    for node, reason in result.excluded:
        print(f"  excluded {node.id} ({reason}) {node.props.get('url', '')}".rstrip())
    print(result.report())
    return result


def show(hits) -> None:
    for rank, hit in enumerate(hits, start=1):
        label = next((label for label in hit.labels if label != "Entity"), "Entity")
        print(f"{rank:2}. {hit.id} [{label}] {hit.score:.4f}  {line(hit.text, 100) or '(no caption)'}")
        for neighbor in hit.neighbors:
            arrow = "->" if neighbor["outgoing"] else "<-"
            print(f"      {arrow} {neighbor['type']} {neighbor['id']}  {line(neighbor['text'], 80)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", default=DEFAULT_BACKEND, choices=list(BACKENDS))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index", help="embed and write items and links").add_argument("path", type=Path)
    commands.add_parser("rights", help="rights filter report only, nothing embedded").add_argument("path", type=Path)
    search = commands.add_parser("search", help="hybrid search")
    search.add_argument("query")
    search.add_argument("--modality", default="text", help="for a media query, pass its file path as the query")
    search.add_argument("--label", action="append", dest="labels", help="keep only nodes with this label")
    search.add_argument("-k", type=int, default=10)
    evaluate = commands.add_parser("eval", help="recall@k for the file's queries over the indexed graph")
    evaluate.add_argument("path", type=Path)
    evaluate.add_argument("-k", type=int, default=10)
    args = parser.parse_args()
    if args.command == "rights":
        screened(args.path)
        return

    embedder = get_embedder(args.backend)
    with connect() as driver:
        if args.command == "index":
            result = screened(args.path)
            store = GraphStore(driver, embedder)
            store.ensure_schema()
            store.upsert(result.nodes)
            store.link(result.links)
            print(f"indexed {len(result.nodes)} nodes and {len(result.links)} links with {embedder.name}")
        elif args.command == "search":
            show(HybridRetriever(driver, embedder).search(args.query, args.k, args.modality, args.labels))
        else:
            _, _, queries = load(args.path)
            retriever = HybridRetriever(driver, embedder)
            scores = defaultdict(list)
            for query in queries:
                found = {hit.id for hit in retriever.search(query["query"], args.k, neighbors=0)}
                score = len(found & set(query["relevant"])) / len(query["relevant"])
                scores["all"].append(score)
                scores[query.get("lang", "?")].append(score)
            detail = ", ".join(f"{lang}={sum(v) / len(v):.3f}" for lang, v in sorted(scores.items()))
            print(f"{embedder.name} hybrid: recall@{args.k} {detail} ({len(queries)} queries)")


if __name__ == "__main__":
    main()
