"""Partner back-test (R6): hide one partner of a past project with a Canadian participant and look for it.

For every indexed Horizon Europe project with a Canadian participant and at
least one other eligible partner, the project's own text is the question,
the project itself is excluded from the candidates, and partner search must
bring the hidden partner (the coordinator, or else the first eligible
participant) back among the top 10 organisations. Reports recall@10 and the
mean reciprocal rank, with the misses listed. Runs in the `embed` service
over whatever is indexed (plan 4.5).

    docker compose run --rm embed python evals/research_assistant/backtest.py [--limit 100]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import get_embedder
from campus_ai.core.eval import metrics, report
from campus_ai.core.graph import connect
from campus_ai.research_assistant.matching import ASSOCIATED, EU, ResearchSearch

HERE = Path(__file__).parent
K = 10


def build_report(results: list[tuple], embedder: str, home: str, seconds: float, when: datetime,
                 sha: str | None = None) -> str:
    """results: (acronym, hidden partner name, its country, its id, ranked organisation ids) per project."""
    ranks = [metrics.first_rank(ranked[:K], [hidden]) for _, _, _, hidden, ranked in results]
    found = sum(r is not None for r in ranks)
    recall = metrics.mean(metrics.recall_at_k(ranked, [hidden], K) for _, _, _, hidden, ranked in results)
    mrr = metrics.mean(metrics.reciprocal_rank(ranked[:K], [hidden]) for _, _, _, hidden, ranked in results)
    rows = [(a, n, c, r or "miss") for (a, n, c, _, _), r in zip(results, ranks)]
    return report.render(
        f"Partner back-test (R6): {embedder}",
        f"{len(results)} projects with a {home} participant; the hidden partner is the coordinator or the first "
        f"eligible participant; the project itself is excluded from the candidates. "
        f"{seconds / len(results):.1f} s per project.",
        when=when, sha=sha,
        bullets=[f"**recall@{K}: {recall:.2f}** ({found} of {len(results)})", f"MRR: {mrr:.2f}"],
        sections=[(None, report.table(["Project", "Hidden partner", "Country", "Rank"], rows))])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=100, help="projects to test (most recent first)")
    parser.add_argument("--home", default="CA", help="the home country whose projects are tested")
    args = parser.parse_args(argv)
    embedder = get_embedder()
    with connect() as driver:
        search = ResearchSearch(driver, embedder)
        projects = search.run(
            "MATCH (home:Entity)-[:PARTICIPATED_IN]->(p:Entity) WHERE home.country = $home AND p.kind = 'Project' "
            "MATCH (o:Entity)-[r:PARTICIPATED_IN]->(p) WHERE o.country IN $eligible AND o.country <> $home "
            "WITH p, collect({id: o.id, name: o.name, country: o.country, role: r.role}) AS partners "
            "WHERE size(partners) >= 1 RETURN p.id AS id, p.acronym AS acronym, p.text AS text, partners "
            "ORDER BY p.start DESC LIMIT $limit",
            home=args.home, eligible=sorted(EU | ASSOCIATED), limit=args.limit)
        results = []
        start = time.perf_counter()
        for project in projects:
            hidden = next((x for x in project["partners"] if x["role"] == "coordinator"), project["partners"][0])
            ranked = search.partners(project["text"], k=K, exclude_project=project["id"])
            results.append((project["acronym"], hidden["name"], hidden["country"], hidden["id"], [org["id"] for org in ranked]))
        seconds = time.perf_counter() - start
    if not results:
        print(f"No indexed projects with a {args.home} participant: index data/cordis/horizon/records.jsonl first")
        return 1
    when = datetime.now(timezone.utc)
    report.save(build_report(results, embedder.name, args.home, seconds, when, report.git_sha(HERE)), "backtest", HERE, when)
    return 0


if __name__ == "__main__":
    sys.exit(main())
