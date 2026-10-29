"""Probe expert search (journey 4) over the OpenAlex graph: who works on what, with evidence.

Runs a few plain-language questions through expert search as the app runs
it (hybrid retrieval over Researcher nodes, one-paper authors after the
established) and prints the top researchers with the topics and
titles that put them there. Not the R6 back-test: a readable check that the
R1 graph answers the kind of question the demo asks. Needs the graph
indexed (`graph_search.py index data/openalex/<name>/records.jsonl`) and
runs in the `embed` service (model + Neo4j). The scored version of these
questions is `gold_eval.py` over `gold_experts.jsonl`.

    docker compose run --rm embed python evals/research_assistant/expert_search.py [--rerank] [--backend e5-small]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import BACKENDS, DEFAULT_BACKEND, get_embedder
from campus_ai.core.eval import report
from campus_ai.core.graph import connect
from campus_ai.research_assistant.matching import ResearchSearch, research_reranker

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


def build_report(probes: list[tuple], model: str, when: datetime, sha: str | None = None) -> str:
    """probes: (query, seconds, hits) with each hit a dict of id, name, works, score, found_by, topics."""
    sections = []
    for query, seconds, hits in probes:
        lines = [f"{seconds:.1f} s", ""]
        if not hits:
            lines.append("- (no researchers found)")
        for hit in hits:
            topics = "; ".join((hit.get("topics") or [])[:4]) or "(no topics)"
            lines.append(f"- **{hit.get('name') or hit['id']}** ({hit.get('works') or '?'} indexed publications, score {hit['score']:.3f}, "
                         f"found by {'+'.join(hit['found_by']) or '?'}): {topics}")
        sections.append((query, lines))
    return report.render(
        f"Expert search probes over the OpenAlex graph ({model})",
        f"Top {K} researchers per question from expert search (researchers with one indexed publication after the rest), with the topics and "
        "titles that put them there. Read the names and topics: a plausible expert for every question is the bar.",
        when=when, sha=sha, sections=sections)


def parse(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rerank", action="store_true", help="add the cross-encoder reranker step (B2)")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, choices=list(BACKENDS),
                        help="embedder to query with (the graph must be indexed with the same one; B2)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse(argv)
    embedder = get_embedder(args.backend)
    reranker = research_reranker() if args.rerank else None
    model = embedder.name + (f" + {reranker.name}" if reranker else "")
    probes = []
    with connect() as driver:
        search = ResearchSearch(driver, embedder, reranker=reranker)  # the ranking the web app and API run
        for query in QUERIES:
            start = time.perf_counter()
            found = search.experts(query, K)
            seconds = time.perf_counter() - start
            probes.append((query, seconds, [{"id": r["id"], "name": r["name"], "topics": r["evidence"]["topics"],
                                             "works": r["evidence"]["works"], "score": r["score"], "found_by": r["found_by"]}
                                            for r in found]))
    when = datetime.now(timezone.utc)
    name = ("expert_search_rerank" if reranker else "expert_search") + ("" if args.backend == DEFAULT_BACKEND else f"_{args.backend}")
    report.save(build_report(probes, model, when, report.git_sha(HERE)), name, HERE, when)
    return 0


if __name__ == "__main__":
    sys.exit(main())
