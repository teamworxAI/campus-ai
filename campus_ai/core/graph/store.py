"""Write embedded nodes and links to Neo4j, and keep the search indexes.

Every node the store writes gets the `Entity` label plus its own label, a
unique `id`, a `text` (indexed for fulltext search) and two vectors from the
embedder: `vec_fast` (smallest Matryoshka size, vector-indexed, for candidate
search) and `vec_full` (full size, for reranking). The embedding is computed
once at full size; `vec_fast` is its truncated prefix.

Changing the embedder or its sizes means rebuilding the graph: the vector
index is created for one size, and `ensure_schema` refuses a mismatch.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Sequence

from campus_ai.core.embed import Embedder, truncate

LABEL = "Entity"
VECTOR_INDEX = "entity_vec"
TEXT_INDEX = "entity_text"
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class Node:
    """One graph node. `content` is what gets embedded (default: `text`);
    for media it is a file path, with `text` holding its caption or metadata."""

    id: str
    label: str
    text: str = ""
    modality: str = "text"
    content: Any = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Link:
    src: str
    type: str
    dst: str
    props: dict[str, Any] = field(default_factory=dict)


def connect() -> Any:
    """A Neo4j driver from NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD."""
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])
    return GraphDatabase.driver(uri, auth=auth)


def name(value: str) -> str:
    """Labels and relationship types can't be query parameters; allow plain names only."""
    if not _NAME.match(value):
        raise ValueError(f"invalid label or relationship type: {value!r}")
    return value


def dims(embedder: Embedder) -> tuple[int, int]:
    """(fast, full) vector sizes: the smallest and largest the embedder supports."""
    return min(embedder.dims), embedder.dims[0]


class GraphStore:
    def __init__(self, driver: Any, embedder: Embedder, database: str | None = None):
        self.driver = driver
        self.embedder = embedder
        self.database = database

    def run(self, query: str, **params: Any) -> list[dict]:
        records, _, _ = self.driver.execute_query(query, params, database_=self.database)
        return [record.data() for record in records]

    def ensure_schema(self) -> None:
        fast, _ = dims(self.embedder)
        existing = self.run(
            "SHOW VECTOR INDEXES YIELD name, options WHERE name = $name RETURN options", name=VECTOR_INDEX
        )
        if existing:
            size = existing[0]["options"]["indexConfig"]["vector.dimensions"]
            if size != fast:
                raise RuntimeError(
                    f"{VECTOR_INDEX} holds {size}-d vectors but {self.embedder.name} gives {fast}-d; rebuild the graph"
                )
        self.run(f"CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:{LABEL}) REQUIRE n.id IS UNIQUE")
        self.run(
            f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (n:{LABEL}) ON n.vec_fast "
            "OPTIONS {indexConfig: {`vector.dimensions`: $size, `vector.similarity_function`: 'cosine'}}",
            size=fast,
        )
        self.run(f"CREATE FULLTEXT INDEX {TEXT_INDEX} IF NOT EXISTS FOR (n:{LABEL}) ON EACH [n.text]")
        self.run("CALL db.awaitIndexes(300)")

    def upsert(self, nodes: Sequence[Node]) -> None:
        """Embed and write nodes, replacing the vectors and text of existing ids."""
        fast, _ = dims(self.embedder)
        groups: dict[tuple[str, str], list[Node]] = defaultdict(list)
        for node in nodes:
            groups[(name(node.label), node.modality)].append(node)
        for (label, modality), group in groups.items():
            full = self.embedder.embed(
                [node.text if node.content is None else node.content for node in group], modality=modality
            )
            rows = [
                {
                    "id": node.id,
                    "text": node.text,
                    "modality": node.modality,
                    "props": node.props,
                    "fast": truncate(vector[None], fast)[0].tolist(),
                    "full": vector.tolist(),
                }
                for node, vector in zip(group, full)
            ]
            self.run(
                f"UNWIND $rows AS row MERGE (n:{LABEL} {{id: row.id}}) SET n:{label}, n += row.props, "
                "n.text = row.text, n.modality = row.modality, n.vec_fast = row.fast, n.vec_full = row.full",
                rows=rows,
            )

    def link(self, links: Sequence[Link]) -> None:
        """Create or update relationships between existing nodes; unknown ids are skipped."""
        groups: dict[str, list[Link]] = defaultdict(list)
        for link in links:
            groups[name(link.type)].append(link)
        for type_, group in groups.items():
            self.run(
                f"UNWIND $rows AS row MATCH (a:{LABEL} {{id: row.src}}), (b:{LABEL} {{id: row.dst}}) "
                f"MERGE (a)-[r:{type_}]->(b) SET r += row.props",
                rows=[{"src": link.src, "dst": link.dst, "props": link.props} for link in group],
            )
