"""Score the Research Assistant's searches against gold sets (card P6): recall@k, MRR and nDCG@k.

Each case's query goes to the search its `search` field names (`experts` or
`partners`, as the web app and API run them); the ranked ids are scored
against the case's `relevant` ids. `exclude` holds the project a back-test
query was taken from, left out of the partner candidates. The gold-set
format is in `campus_ai/core/eval/gold.py`. Runs in the `embed` service
(model + Neo4j) over whatever is indexed.

    docker compose run --rm embed python evals/research_assistant/gold_eval.py [gold.jsonl ...] [-k 10]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.embed import get_embedder
from campus_ai.core.eval import gold, metrics, report
from campus_ai.core.graph import connect
from campus_ai.research_assistant.matching import ResearchSearch

HERE = Path(__file__).parent
GOLD_SETS = [HERE / "gold_experts.jsonl", HERE / "gold_partners.jsonl"]
K = 10


def ranked_ids(search: ResearchSearch, case: dict, k: int) -> list[str]:
    exclude = case.get("exclude", [])
    if case.get("search") == "experts":
        return [r["id"] for r in search.experts(case["query"], k=k + len(exclude)) if r["id"] not in exclude][:k]
    if case.get("search") == "partners":
        if len(exclude) > 1:
            raise ValueError(f"{case['id']}: partner search leaves out one project, not {len(exclude)}")
        return [o["id"] for o in search.partners(case["query"], k=k, exclude_project=exclude[0] if exclude else None)]
    raise ValueError(f"{case['id']}: unknown search {case.get('search')!r}; expected 'experts' or 'partners'")


def build_report(results: list[tuple], k: int, embedder: str, when: datetime, sha: str | None = None) -> str:
    """results: (gold set name, provisional?, [(case, ranked ids, seconds)]) per gold set."""
    bullets, sections = [], []
    for name, provisional, scored in results:
        rows = []
        for case, ranked, seconds in scored:
            relevant = case["relevant"]
            found = len(set(relevant) & set(ranked[:k]))
            query = " ".join(case["query"].split())
            rows.append((case["id"], query[:70] + ("..." if len(query) > 70 else ""), f"{found}/{len(relevant)}",
                         metrics.first_rank(ranked, relevant) or "miss", f"{metrics.ndcg_at_k(ranked, relevant, k):.2f}",
                         f"{seconds:.1f}"))
        recall = metrics.mean(metrics.recall_at_k(r, c["relevant"], k) for c, r, _ in scored)
        mrr = metrics.mean(metrics.reciprocal_rank(r, c["relevant"]) for c, r, _ in scored)
        ndcg = metrics.mean(metrics.ndcg_at_k(r, c["relevant"], k) for c, r, _ in scored)
        bullets.append(f"**{name}** ({len(scored)} cases{', provisional labels' if provisional else ''}): "
                       f"recall@{k} {recall:.2f}, MRR {mrr:.2f}, nDCG@{k} {ndcg:.2f}")
        sections.append((name, report.table(["Case", "Query", f"Relevant in top {k}", "First hit", f"nDCG@{k}", "Seconds"], rows)))
    return report.render(
        f"Gold-set retrieval eval: {embedder}",
        f"Each case's query through its search (experts or partners), top {k} scored against the gold set's relevant "
        "ids. Provisional gold sets were labelled by the build session and wait for the research officers' labels (D6).",
        when=when, sha=sha, bullets=bullets, sections=sections)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gold_sets", nargs="*", type=Path, default=GOLD_SETS)
    parser.add_argument("-k", type=int, default=K)
    args = parser.parse_args(argv)
    sets = [(path, gold.load(path, kind="retrieval")) for path in args.gold_sets]
    embedder = get_embedder()
    results = []
    with connect() as driver:
        search = ResearchSearch(driver, embedder)
        for path, cases in sets:
            scored = []
            for case in cases:
                start = time.perf_counter()
                ranked = ranked_ids(search, case, args.k)
                scored.append((case, ranked, time.perf_counter() - start))
            results.append((path.stem, "provisional" in cases[0]["notes"].lower() if cases else False, scored))
    when = datetime.now(timezone.utc)
    report.save(build_report(results, args.k, embedder.name, when, report.git_sha(HERE)), "gold_eval", HERE, when)
    return 0


if __name__ == "__main__":
    sys.exit(main())
