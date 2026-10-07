"""Compare embedder backends on a query/relevant-item JSONL file (decision D7).

Each line is either an item or a query:

    {"id": "d1", "modality": "text", "content": "..."}
    {"query": "...", "lang": "fr", "relevant": ["d1"]}

Reports recall@k (default 10) per backend, overall and per query language.

    uv sync --extra embed
    uv run python scripts/embed_bakeoff.py evals/embed/sample_bakeoff.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from campus_ai.core.embed import BACKENDS, Embedder, get_embedder


def load(path: Path) -> tuple[list[dict], list[dict]]:
    items, queries = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            (queries if "query" in record else items).append(record)
    return items, queries


def recall_at_k(embedder: Embedder, items: list[dict], queries: list[dict], k: int = 10) -> dict[str, float]:
    """Mean share of each query's relevant items found in its top k, overall and by language."""
    ids, vectors = [], []
    for modality in sorted({item.get("modality", "text") for item in items}):
        group = [item for item in items if item.get("modality", "text") == modality]
        if modality not in embedder.modalities:
            print(f"{embedder.name}: skipping {len(group)} {modality} items (unsupported)")
            continue
        ids += [item["id"] for item in group]
        vectors.append(embedder.embed([item["content"] for item in group], modality=modality))
    corpus = np.vstack(vectors)
    query_vectors = embedder.embed([q["query"] for q in queries], kind="query")
    top = np.argsort(-(query_vectors @ corpus.T), axis=1)[:, :k]

    scores = defaultdict(list)
    for query, row in zip(queries, top):
        found = {ids[i] for i in row}
        score = len(found & set(query["relevant"])) / len(query["relevant"])
        scores["all"].append(score)
        scores[query.get("lang", "?")].append(score)
    return {lang: float(np.mean(values)) for lang, values in scores.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--backends", nargs="+", default=list(BACKENDS), choices=list(BACKENDS))
    parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args()

    items, queries = load(args.path)
    print(f"{len(items)} items, {len(queries)} queries")
    for name in args.backends:
        scores = recall_at_k(get_embedder(name), items, queries, args.k)
        detail = ", ".join(f"{lang}={value:.3f}" for lang, value in sorted(scores.items()))
        print(f"{name}: recall@{args.k} {detail}")


if __name__ == "__main__":
    main()
