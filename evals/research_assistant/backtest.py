"""Partner back-test (R6): hide one partner of a past project with a Canadian participant and look for it.

For every indexed Horizon Europe project with a Canadian participant and at
least one other eligible partner, the project's own text is the question,
the project itself is excluded from the candidates, and partner search must
bring the hidden partner (the coordinator, or else the first eligible
participant) back among the top 10 organisations. Reports recall@10 and the
mean reciprocal rank, with the misses listed. Runs in the `embed` service
over whatever is indexed (plan 4.5).

    docker compose run --rm embed python evals/research_assistant/backtest.py [--limit 100] [--rerank] [--backend e5-small]

With `--rerank --weightings probability,rank,rrf` one pass scores every project's
pool once (the scores are cached per query and document) and reports recall@10
and MRR for fusion only and for each way of weighting the reranked projects
(B2 follow-up), and how often the hidden partner is in the pool at all.
`--pool N` reranks only the top N fused candidates; `--report NAME` names the report.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import BACKENDS, DEFAULT_BACKEND, get_embedder
from campus_ai.core.graph import connect
from campus_ai.research_assistant.matching import ASSOCIATED, CANDIDATES, EU, WEIGHTINGS, ResearchSearch, research_reranker

HERE = Path(__file__).parent
K = 10


def parse(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=100, help="projects to test (most recent first)")
    parser.add_argument("--home", default="CA", help="the home country whose projects are tested")
    parser.add_argument("--rerank", action="store_true", help="add the cross-encoder reranker step (B2)")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, choices=list(BACKENDS),
                        help="embedder to query with (the graph must be indexed with the same one; B2)")
    parser.add_argument("--weightings", default="probability",
                        help=f"with --rerank, comma-separated project weightings to compare: {', '.join(WEIGHTINGS)}")
    parser.add_argument("--pool", type=int, default=None, help="with --rerank, rerank only the top N fused candidates")
    parser.add_argument("--report", default=None, help="report file name stem (default backtest[_rerank]_<date>)")
    return parser.parse_args(argv)


class CachedReranker:
    """Scores each (query, document) pair once, so several weightings of one pool cost one rerank."""

    def __init__(self, reranker):
        self.reranker = reranker
        self.name = reranker.name
        self.seen: dict[tuple[str, str], float] = {}

    def score(self, query, documents, data_class="P"):
        todo = [d for d in dict.fromkeys(documents) if (query, d) not in self.seen]
        if todo:
            self.seen.update(zip(((query, d) for d in todo), self.reranker.score(query, todo, data_class=data_class)))
        return [self.seen[(query, d)] for d in documents]


class CachedEmbedder:
    """Embeds each query once however many rankings are computed for it (the back-test asks 4-5 times per project)."""

    def __init__(self, embedder):
        self.embedder = embedder
        self.seen: dict = {}

    def __getattr__(self, name):
        return getattr(self.embedder, name)

    def embed(self, inputs, modality="text", kind="document", dim=None, **kwargs):
        if len(inputs) != 1 or modality != "text" or kind != "query":
            return self.embedder.embed(inputs, modality=modality, kind=kind, dim=dim, **kwargs)
        key = (inputs[0], dim, tuple(sorted(kwargs.items())))
        if key not in self.seen:
            self.seen[key] = self.embedder.embed(inputs, modality=modality, kind=kind, dim=dim, **kwargs)
        return self.seen[key]


def pool_rank(search: ResearchSearch, text: str, project: str, org: str) -> int | None:
    """Fusion rank (1-based) of the best project in the fused top 50 that the hidden organisation took part in."""
    hits = [h for h in search.retriever.search(text, CANDIDATES, labels=["Project"], neighbors=0) if h.id != project]
    rows = search.run("MATCH (o:Entity {id: $org})-[:PARTICIPATED_IN]->(p:Entity) WHERE p.id IN $ids RETURN p.id AS id",
                      org=org, ids=[h.id for h in hits])
    ids = {row["id"] for row in rows}
    return next((i for i, h in enumerate(hits, start=1) if h.id in ids), None)


def score(ranks: list) -> tuple[float, float]:
    found = [r for r in ranks if r]
    return len(found) / len(ranks), sum(1 / r for r in found) / len(ranks)


def main(argv=None) -> int:
    args = parse(argv)
    embedder = CachedEmbedder(get_embedder(args.backend))
    reranker = CachedReranker(research_reranker()) if args.rerank else None
    model = embedder.name + (f" + {reranker.name}" if reranker else "")
    variants = [w for w in args.weightings.split(",") if w] if reranker else []
    with connect() as driver:
        plain = ResearchSearch(driver, embedder)
        search = ResearchSearch(driver, embedder, reranker=reranker, pool=args.pool) if reranker else plain
        projects = search.run(
            "MATCH (home:Entity)-[:PARTICIPATED_IN]->(p:Entity) WHERE home.country = $home AND p.kind = 'Project' "
            "MATCH (o:Entity)-[r:PARTICIPATED_IN]->(p) WHERE o.country IN $eligible AND o.country <> $home "
            "WITH p, collect({id: o.id, name: o.name, country: o.country, role: r.role}) AS partners "
            "WHERE size(partners) >= 1 RETURN p.id AS id, p.acronym AS acronym, p.text AS text, partners "
            "ORDER BY p.start DESC LIMIT $limit",
            home=args.home, eligible=sorted(EU | ASSOCIATED), limit=args.limit)
        results = []  # (acronym, hidden name, country, {variant: rank}, pool rank)
        times: dict[str, list[float]] = {}
        for n, project in enumerate(projects, start=1):
            hidden = next((x for x in project["partners"] if x["role"] == "coordinator"), project["partners"][0])
            ranks, line = {}, []
            runs = [("fusion", plain, None)] if variants else []
            runs += [(w, search, w) for w in variants] or [("fusion" if not reranker else "probability", search, None)]
            for name, engine, weighting in runs:
                start = time.perf_counter()
                ranked = engine.partners(project["text"], k=K, exclude_project=project["id"], weighting=weighting)
                times.setdefault(name, []).append(time.perf_counter() - start)
                ranks[name] = next((i + 1 for i, org in enumerate(ranked) if org["id"] == hidden["id"]), None)
                line.append(f"{name} {ranks[name] or 'miss'} ({times[name][-1]:.1f} s)")
            in_pool = pool_rank(plain, project["text"], project["id"], hidden["id"]) if variants else None
            results.append((project["acronym"], hidden["name"], hidden["country"], ranks, in_pool))
            print(f"{n}/{len(projects)} {project['acronym']}: {', '.join(line)}; hidden partner in pool: "
                  f"{'fused rank ' + str(in_pool) if in_pool else 'no'}", flush=True)
    if not results:
        print(f"No indexed projects with a {args.home} participant: index data/cordis/horizon/records.jsonl first")
        return 1
    names = list(results[0][3])
    when = datetime.now(timezone.utc)
    # The first query loads the models; the warm mean is the cost per query in use.
    warm = {name: (t[1:] or t) for name, t in times.items()}
    lines = [f"# Partner back-test (R6): {model}", "",
             f"{when:%Y-%m-%d %H:%M} UTC. {len(results)} projects with a {args.home} participant; the hidden partner is the "
             f"coordinator or the first eligible participant; the project itself is excluded from the candidates."
             + (f" Rerank pool {args.pool or CANDIDATES}." if reranker else ""), ""]
    if len(names) == 1:
        recall, mrr = score([r[3][names[0]] for r in results])
        lines += [f"{sum(warm[names[0]]) / len(warm[names[0]]):.1f} s per project with the models loaded "
                  f"(first, with loading: {times[names[0]][0]:.1f} s).", "",
                  f"- **recall@{K}: {recall:.2f}** ({round(recall * len(results))} of {len(results)})", f"- MRR: {mrr:.2f}"]
    else:
        lines += [f"| Ranking | recall@{K} | MRR | s per query (warm, cached scores after the first variant) |", "|---|---|---|---|"]
        for name in names:
            recall, mrr = score([r[3][name] for r in results])
            lines.append(f"| {name} | {recall:.2f} ({round(recall * len(results))}/{len(results)}) | {mrr:.3f} | "
                         f"{sum(warm[name]) / len(warm[name]):.1f} |")
    pooled = [r[4] for r in results if r[4]]
    if variants:
        top30 = [p for p in pooled if p <= 30]
        lines += ["", f"Hidden partner took part in a project in the fused top {CANDIDATES}: {len(pooled)} of {len(results)} "
                      f"({len(pooled) / len(results):.0%}); in the top 30 (the projects partner search uses): {len(top30)} of {len(results)} "
                      f"({len(top30) / len(results):.0%})."]
    head = "| Project | Hidden partner | Country | " + " | ".join(names) + " |" + (" In pool (fused rank) |" if variants else "")
    lines += ["", head, "|" + "---|" * (3 + len(names) + (1 if variants else 0))]
    for a, nm, c, ranks, in_pool in results:
        cells = " | ".join(str(ranks[x] or "miss") for x in names)
        lines.append(f"| {a} | {nm} | {c} | {cells} |" + (f" {in_pool or 'no'} |" if variants else ""))
    report = "\n".join(lines) + "\n"
    print(report)
    tag = "" if args.backend == DEFAULT_BACKEND else f"{args.backend}_"
    stem = args.report or f"backtest_{'rerank_' if reranker else ''}{tag}{when:%Y%m%d}"
    out = HERE / f"{stem}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Report: {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
