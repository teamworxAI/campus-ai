"""Partner back-test (R6): hide one partner of a past project with a Canadian participant and look for it.

For every indexed Horizon Europe project with a Canadian participant and at
least one other eligible partner, the project's own text is the question,
the project itself is excluded from the candidates, and partner search must
bring the hidden partner (the coordinator, or else the first eligible
participant) back among the top 10 organisations. Reports recall@10 and the
mean reciprocal rank, with the misses listed. Runs in the `embed` service
over whatever is indexed (plan 4.5).

    docker compose run --rm embed python evals/research_assistant/backtest.py [--limit 100] [--rerank]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import get_embedder
from campus_ai.core.graph import connect
from campus_ai.research_assistant.matching import ASSOCIATED, EU, ResearchSearch, research_reranker

HERE = Path(__file__).parent
K = 10


def parse(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=100, help="projects to test (most recent first)")
    parser.add_argument("--home", default="CA", help="the home country whose projects are tested")
    parser.add_argument("--rerank", action="store_true", help="add the cross-encoder reranker step (B2)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse(argv)
    embedder = get_embedder()
    reranker = research_reranker() if args.rerank else None
    model = embedder.name + (f" + {reranker.name}" if reranker else "")
    with connect() as driver:
        search = ResearchSearch(driver, embedder, reranker=reranker)
        projects = search.run(
            "MATCH (home:Entity)-[:PARTICIPATED_IN]->(p:Entity) WHERE home.country = $home AND p.kind = 'Project' "
            "MATCH (o:Entity)-[r:PARTICIPATED_IN]->(p) WHERE o.country IN $eligible AND o.country <> $home "
            "WITH p, collect({id: o.id, name: o.name, country: o.country, role: r.role}) AS partners "
            "WHERE size(partners) >= 1 RETURN p.id AS id, p.acronym AS acronym, p.text AS text, partners "
            "ORDER BY p.start DESC LIMIT $limit",
            home=args.home, eligible=sorted(EU | ASSOCIATED), limit=args.limit)
        results = []
        times = []
        for n, project in enumerate(projects, start=1):
            start = time.perf_counter()
            hidden = next((x for x in project["partners"] if x["role"] == "coordinator"), project["partners"][0])
            ranked = search.partners(project["text"], k=K, exclude_project=project["id"])
            rank = next((i + 1 for i, org in enumerate(ranked) if org["id"] == hidden["id"]), None)
            results.append((project["acronym"], hidden["name"], hidden["country"], rank))
            times.append(time.perf_counter() - start)
            print(f"{n}/{len(projects)} {project['acronym']}: rank {rank or 'miss'}, {times[-1]:.1f} s", flush=True)
        # The first query loads the models; the warm mean is the cost per query in use.
        warm = times[1:] or times
    if not results:
        print(f"No indexed projects with a {args.home} participant: index data/cordis/horizon/records.jsonl first")
        return 1
    found = [r for r in results if r[3]]
    recall = len(found) / len(results)
    mrr = sum(1 / r[3] for r in found) / len(results)
    when = datetime.now(timezone.utc)
    lines = [f"# Partner back-test (R6): {model}", "",
             f"{when:%Y-%m-%d %H:%M} UTC. {len(results)} projects with a {args.home} participant; the hidden partner is the "
             f"coordinator or the first eligible participant; the project itself is excluded from the candidates. "
             f"{sum(warm) / len(warm):.1f} s per project with the models loaded (first, with loading: {times[0]:.1f} s).", "",
             f"- **recall@{K}: {recall:.2f}** ({len(found)} of {len(results)})", f"- MRR: {mrr:.2f}",
             "", "| Project | Hidden partner | Country | Rank |", "|---|---|---|---|"]
    lines += [f"| {a} | {n} | {c} | {r if r else 'miss'} |" for a, n, c, r in results]
    report = "\n".join(lines) + "\n"
    print(report)
    out = HERE / f"backtest_{'rerank_' if reranker else ''}{when:%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Report: {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
