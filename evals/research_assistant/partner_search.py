"""Probe partner search (journey 1) over the CORDIS graph: which EU organisations and projects fit a topic.

Runs a few call-like questions through the hybrid retriever, once restricted
to Organization nodes and once to Project nodes, and prints the top hits
with country, type and fields as evidence. Not the R6 back-test: a readable
check that the R2 graph answers the kind of question the demo asks. Needs
the graph indexed (`graph_search.py index data/cordis/horizon/records.jsonl`)
and runs in the `embed` service.

    docker compose run --rm embed python evals/research_assistant/partner_search.py [--rerank] [--backend e5-small]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import BACKENDS, DEFAULT_BACKEND, get_embedder
from campus_ai.core.eval import report
from campus_ai.core.graph import HybridRetriever, connect
from campus_ai.research_assistant.matching import research_reranker

HERE = Path(__file__).parent
QUERIES = [
    "wildfire smoke exposure and public health in cities",
    "salmon and freshwater ecosystems under climate change",
    "AI for medical imaging and diagnosis",
    "Indigenous knowledge and cultural heritage digitisation",
    "quantum materials and superconducting devices",
    "affordable housing and urban policy",
]
LABELS = ("Organization", "Project")
K = 5


def build_report(probes: list[tuple], model: str, when: datetime, sha: str | None = None) -> str:
    """probes: (query, [(label, seconds, node property dicts in rank order)]) per question."""
    sections = []
    for query, by_label in probes:
        lines = []
        for label, seconds, nodes in by_label:
            lines += [f"**{label}s** ({seconds:.1f} s)", ""]
            for p in nodes:
                if label == "Organization":
                    lines.append(f"- {p.get('name')} ({p.get('country')}, {p.get('activity')}): {'; '.join((p.get('fields') or [])[:4])}")
                else:
                    lines.append(f"- {p.get('acronym')}: {p.get('title')} ({p.get('start') or '?'}; {', '.join(p.get('countries') or [])})")
            lines.append("")
        sections.append((query, lines[:-1]))
    return report.render(
        f"Partner search probes over the CORDIS graph ({model})",
        f"Top {K} organisations and projects per question, hybrid retrieval by label. Read the names: an "
        "organisation whose fields and projects fit the question is the bar.",
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
        retriever = HybridRetriever(driver, embedder, reranker=reranker)
        for query in QUERIES:
            by_label = []
            for label in LABELS:
                start = time.perf_counter()
                hits = retriever.search(query, K, labels=[label], neighbors=0)
                seconds = time.perf_counter() - start
                rows = retriever.run("MATCH (n:Entity) WHERE n.id IN $ids RETURN n.id AS id, n.name AS name, n.country AS country, "
                                     "n.activity AS activity, n.fields AS fields, n.acronym AS acronym, n.title AS title, "
                                     "n.countries AS countries, n.start AS start", ids=[h.id for h in hits])
                props = {r["id"]: r for r in rows}
                by_label.append((label, seconds, [props.get(hit.id, {}) for hit in hits]))
            probes.append((query, by_label))
    when = datetime.now(timezone.utc)
    name = ("partner_search_rerank" if reranker else "partner_search") + ("" if args.backend == DEFAULT_BACKEND else f"_{args.backend}")
    report.save(build_report(probes, model, when, report.git_sha(HERE)), name, HERE, when)
    return 0


if __name__ == "__main__":
    sys.exit(main())
