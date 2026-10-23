"""Hybrid search over the graph: vector + fulltext candidates, reranked, then expanded.

1. Candidates: nearest `vec_fast` neighbours (vector index) and, for text
   queries, the best fulltext matches on `text`.
2. Rerank every candidate by cosine similarity on `vec_full`.
3. Fuse the full-size vector ranking with the fulltext ranking by reciprocal
   rank fusion, so exact names and words count as well as meaning.
4. Optional (B2): a cross-encoder `reranker` scores the top `candidates` of
   the fused list against the query (text queries only) and orders them by
   that score, fusion score breaking ties.
5. Attach each hit's direct neighbours (graph expansion) as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from campus_ai.core.embed import Embedder, truncate
from campus_ai.core.graph.stopwords import STOPWORDS
from campus_ai.core.graph.store import LABEL, TEXT_INDEX, VECTOR_INDEX, dims, name

RRF_K = 60  # standard reciprocal rank fusion constant


@dataclass
class Hit:
    id: str
    labels: list[str]
    text: str
    score: float
    neighbors: list[dict] = field(default_factory=list)
    found_by: list[str] = field(default_factory=list)  # "meaning" (vector index), "words" (fulltext)
    similarity: float = 0.0  # cosine similarity to the query at full size, -1..1
    rerank: float | None = None  # cross-encoder score 0..1, None without a reranker

    @property
    def weight(self) -> float:
        """The score that ordered this hit: the reranker's when there is one, else the fusion score."""
        return self.score if self.rerank is None else self.rerank


def fulltext_query(text: str) -> str:
    """Content words OR-ed together, lower-cased so user input can't use Lucene syntax.

    Drops function words and one-letter fragments ("d" from "d'archives"),
    which would otherwise match nearly every document in that language.
    """
    words = [word for word in re.findall(r"\w+", text.lower()) if len(word) > 1 and word not in STOPWORDS]
    return " ".join(words)


def fuse(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal rank fusion: each list adds 1 / (k + rank) to the ids it contains."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, id_ in enumerate(ranking, start=1):
            scores[id_] = scores.get(id_, 0.0) + 1.0 / (k + rank)
    return scores


class HybridRetriever:
    def __init__(self, driver: Any, embedder: Embedder, database: str | None = None, candidates: int = 50,
                 reranker: Any = None):
        self.driver = driver
        self.embedder = embedder
        self.database = database
        self.candidates = candidates
        self.reranker = reranker  # e.g. campus_ai.core.embed.reranker.Reranker; None skips the step

    def run(self, query: str, **params: Any) -> list[dict]:
        records, _, _ = self.driver.execute_query(query, params, database_=self.database)
        return [record.data() for record in records]

    def search(
        self,
        query: Any,
        k: int = 10,
        modality: str = "text",
        labels: Sequence[str] | None = None,
        neighbors: int = 5,
        data_class: str = "P",
    ) -> list[Hit]:
        """Top `k` nodes for a query (text, or a media path with `modality`).

        `labels` keeps only nodes with one of those labels; `neighbors` caps
        the linked nodes attached to each hit (0 to skip expansion).
        `data_class` is the query's class (P/I/S; R is refused before embedding).
        """
        fast, _ = dims(self.embedder)
        full = self.embedder.embed([query], modality=modality, kind="query", data_class=data_class)[0]
        wanted = [name(label) for label in labels or []]
        # Vector search filters inside the index, so a rare label still gets n candidates;
        # fulltext filters its top n afterwards.
        within = "WHERE node.kind IN $labels " if wanted else ""
        where = "WHERE node.kind IN $labels" if wanted else ""
        returns = "RETURN node.id AS id, labels(node) AS labels, node.text AS text, node.vec_full AS vec, score"

        rows = self.run(
            f"MATCH (node:{LABEL}) SEARCH node IN (VECTOR INDEX {VECTOR_INDEX} FOR $vector {within}LIMIT $n) "
            f"SCORE AS score {returns}",
            n=self.candidates,
            vector=truncate(full[None], fast)[0].tolist(),
            labels=wanted,
        )
        words = fulltext_query(query) if modality == "text" else ""
        text_rows = []
        if words:
            text_rows = self.run(
                f"CALL db.index.fulltext.queryNodes('{TEXT_INDEX}', $q, {{limit: $n}}) YIELD node, score "
                f"{where} {returns}",
                q=words,
                n=self.candidates,
                labels=wanted,
            )

        found = {row["id"]: row for row in rows + text_rows}
        if not found:
            return []
        ids = list(found)
        similarity = np.asarray([found[id_]["vec"] for id_ in ids], dtype=np.float32) @ full
        by_vector = [ids[i] for i in np.argsort(-similarity, kind="stable")]
        by_text = [row["id"] for row in text_rows]
        scores = fuse([by_vector, by_text])
        fused = sorted(scores, key=lambda id_: -scores[id_])
        rerank: dict[str, float] = {}
        if self.reranker is not None and modality == "text":
            pool = fused[:max(k, self.candidates)]
            rerank = dict(zip(pool, self.reranker.score(query, [found[id_]["text"] or "" for id_ in pool],
                                                        data_class=data_class)))
            fused = sorted(pool, key=lambda id_: (-rerank[id_], -scores[id_]))
        top = fused[:k]

        by_meaning = {row["id"] for row in rows}
        found_by = {id_: [name for name, ids in (("meaning", by_meaning), ("words", set(by_text))) if id_ in ids]
                    for id_ in top}
        cosine = dict(zip(ids, similarity.tolist()))
        hits = [Hit(id_, found[id_]["labels"], found[id_]["text"], scores[id_], found_by=found_by[id_],
                    similarity=cosine[id_], rerank=rerank.get(id_)) for id_ in top]
        if neighbors and hits:
            linked = self.run(
                f"UNWIND $ids AS id MATCH (n:{LABEL} {{id: id}}) RETURN id, COLLECT {{ "
                f"MATCH (n)-[r]-(m:{LABEL}) RETURN {{type: type(r), outgoing: startNode(r) = n, "
                "id: m.id, labels: labels(m), text: m.text} LIMIT $limit } AS neighbors",
                ids=top,
                limit=neighbors,
            )
            by_id = {row["id"]: row["neighbors"] for row in linked}
            for hit in hits:
                hit.neighbors = by_id.get(hit.id, [])
        return hits
