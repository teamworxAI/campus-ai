"""Probe partner search (journey 1) over the CORDIS graph: which EU organisations and projects fit a topic.

Runs a few call-like questions through the hybrid retriever, once restricted
to Organization nodes and once to Project nodes, and prints the top hits
with country, type and fields as evidence. Not the R6 back-test: a readable
check that the R2 graph answers the kind of question the demo asks. Needs
the graph indexed (`graph_search.py index data/cordis/horizon/records.jsonl`)
and runs in the `embed` service.

    docker compose run --rm embed python evals/research_assistant/partner_search.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import get_embedder
from campus_ai.core.graph import HybridRetriever, connect

HERE = Path(__file__).parent
QUERIES = [
    "wildfire smoke exposure and public health in cities",
    "salmon and freshwater ecosystems under climate change",
    "AI for medical imaging and diagnosis",
    "Indigenous knowledge and cultural heritage digitisation",
    "quantum materials and superconducting devices",
    "affordable housing and urban policy",
]
K = 5


def main() -> int:
    embedder = get_embedder()
    lines = [f"# Partner search probes over the CORDIS graph ({embedder.name})", "",
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Top {K} organisations and projects per question, hybrid "
             "retrieval by label. Read the names: an organisation whose fields and projects fit the question is the bar.", ""]
    with connect() as driver:
        retriever = HybridRetriever(driver, embedder)
        for query in QUERIES:
            lines += [f"## {query}", ""]
            for label in ("Organization", "Project"):
                start = time.perf_counter()
                hits = retriever.search(query, K, labels=[label], neighbors=0)
                seconds = time.perf_counter() - start
                rows = retriever.run("MATCH (n:Entity) WHERE n.id IN $ids RETURN n.id AS id, n.name AS name, n.country AS country, "
                                     "n.activity AS activity, n.fields AS fields, n.acronym AS acronym, n.title AS title, "
                                     "n.countries AS countries, n.start AS start", ids=[h.id for h in hits])
                props = {r["id"]: r for r in rows}
                lines += [f"**{label}s** ({seconds:.1f} s)", ""]
                for hit in hits:
                    p = props.get(hit.id, {})
                    if label == "Organization":
                        lines.append(f"- {p.get('name')} ({p.get('country')}, {p.get('activity')}): {'; '.join((p.get('fields') or [])[:4])}")
                    else:
                        lines.append(f"- {p.get('acronym')}: {p.get('title')} ({p.get('start') or '?'}; {', '.join(p.get('countries') or [])})")
                lines.append("")
    report = "\n".join(lines)
    print(report)
    out = HERE / f"partner_search_{datetime.now(timezone.utc):%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Report: {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
