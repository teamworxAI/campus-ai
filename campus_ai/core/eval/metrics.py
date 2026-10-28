"""Deterministic eval metrics as pure functions (card P6).

Retrieval metrics take `ranked` (result ids, best first) and `relevant` (the
gold set's ids; binary relevance). Course Access metrics work on
`rebuild.compare` results and proposal review flags. Nothing here calls a
model: what only judgement can score is in `judge.py`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


# --- retrieval ----------------------------------------------------------------

def first_rank(ranked: Sequence[str], relevant: Iterable[str]) -> int | None:
    """1-based rank of the first relevant result, or None if none is ranked."""
    relevant = set(relevant)
    return next((i + 1 for i, item in enumerate(ranked) if item in relevant), None)


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Share of the relevant ids found in the top k."""
    relevant = set(relevant)
    return len(relevant & set(ranked[:k])) / len(relevant) if relevant else 0.0


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Share of the top k that is relevant (a short list still divides by k)."""
    relevant = set(relevant)
    return sum(item in relevant for item in ranked[:k]) / k if k else 0.0


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """1 / rank of the first relevant result, 0 if none; averaged over queries it is MRR."""
    rank = first_rank(ranked, relevant)
    return 1 / rank if rank else 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Normalised discounted cumulative gain over the top k, binary relevance."""
    relevant = set(relevant)
    seen, dcg = set(), 0.0
    for i, item in enumerate(ranked[:k]):
        if item in relevant and item not in seen:
            dcg += 1 / math.log2(i + 2)
            seen.add(item)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


# --- citations ----------------------------------------------------------------

def citation_precision(text: str, allowed: set[str]) -> dict:
    """Share of the ids cited in `text` that are in `allowed` (None when nothing is cited).

    Parsing is the Research Assistant brief's own (`consortium.CITATION` and
    `check_citations`), so the metric and the product read citations the same
    way; `dropped` counts claims citing an unknown id, `uncited` claims with none.
    """
    from campus_ai.research_assistant.consortium import CITATION, check_citations  # one definition of the syntax

    cited = CITATION.findall(text)
    valid = sum(c in allowed for c in cited)
    checked = check_citations(text, allowed)
    return {"cited": len(cited), "valid": valid, "precision": valid / len(cited) if cited else None,
            "dropped": len(checked["dropped"]), "uncited": len(checked["uncited"])}


# --- Course Access --------------------------------------------------------------

def fixed_share(before: int, after: int) -> float:
    """Net share of audit issues gone after remediation (0 when there were none)."""
    return (before - after) / before if before else 0.0


def introduced(comparison: Mapping) -> int:
    """Issues the rebuild introduced, from a `rebuild.compare` result (target 0)."""
    return sum(comparison["new"].values())


def review_share(needs_review: Iterable[bool]) -> float | None:
    """Share of proposals sent to human review (None when there are none)."""
    flags = list(needs_review)
    return sum(map(bool, flags)) / len(flags) if flags else None


def count_agreement(expected: Mapping[str, int], found: Mapping[str, int]) -> dict:
    """Audit counts against a specialist's expected counts per rule.

    Per rule, min(expected, found) issues count as matched; precision is
    matched / found, recall matched / expected (None when the side is empty).
    """
    matched = sum(min(n, found.get(rule, 0)) for rule, n in expected.items())
    total_found, total_expected = sum(found.values()), sum(expected.values())
    return {"matched": matched,
            "precision": matched / total_found if total_found else None,
            "recall": matched / total_expected if total_expected else None}
