"""Probe expert search (journey 4) over the OpenAlex graph: who works on what, with evidence.

Runs a few plain-language questions through the hybrid retriever restricted
to Researcher nodes and prints the top researchers with the topics and
titles that put them there. Not the R6 back-test: a readable check that the
R1 graph answers the kind of question the demo asks. Needs the graph
indexed (`graph_search.py index data/openalex/<name>/records.jsonl`) and
runs in the `embed` service (model + Neo4j).

    docker compose run --rm embed python evals/research_assistant/expert_search.py [--rerank]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import get_embedder
from campus_ai.core.graph import HybridRetriever, connect
from campus_ai.research_assistant.matching import research_reranker

HERE = Path(__file__).parent
QUERIES = [
    "who works on wildfire smoke and public health",
    "salmon populations and climate change in rivers",
    "machine learning for medical imaging",
    "Indigenous language revitalization",
    "quantum materials and superconductivity",
    "urban housing affordability policy in Canada",
]
K = 5


def parse(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rerank", action="store_true", help="add the cross-encoder reranker step (B2)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse(argv)
    embedder = get_embedder()
    reranker = research_reranker() if args.rerank else None
    model = embedder.name + (f" + {reranker.name}" if reranker else "")
    lines = [f"# Expert search probes over the OpenAlex graph ({model})", "",
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Top {K} researchers per question, hybrid retrieval "
             "restricted to Researcher nodes, with the topics and titles that put them there. Read the names and "
             "topics: a plausible expert for every question is the bar.", ""]
    with connect() as driver:
        retriever = HybridRetriever(driver, embedder, reranker=reranker)
        for query in QUERIES:
            start = time.perf_counter()
            hits = retriever.search(query, K, labels=["Researcher"], neighbors=0)
            seconds = time.perf_counter() - start
            lines += [f"## {query}", "", f"{seconds:.1f} s", ""]
            if not hits:
                lines += ["- (no researchers found)", ""]
                continue
            rows = retriever.run("MATCH (n:Entity) WHERE n.id IN $ids RETURN n.id AS id, n.name AS name, n.topics AS topics, "
                                 "n.works AS works", ids=[hit.id for hit in hits])
            props = {row["id"]: row for row in rows}
            for hit in hits:
                row = props.get(hit.id, {})
                topics = "; ".join((row.get("topics") or [])[:4]) or "(no topics)"
                lines.append(f"- **{row.get('name') or hit.id}** ({row.get('works') or '?'} works, score {hit.weight:.3f}, "
                             f"found by {'+'.join(hit.found_by) or '?'}): {topics}")
            lines.append("")
    report = "\n".join(lines)
    print(report)
    out = HERE / f"expert_search_{'rerank_' if reranker else ''}{datetime.now(timezone.utc):%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Report: {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
