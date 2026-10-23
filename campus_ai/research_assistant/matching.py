"""Expert, partner and call matching over the research graph (R4, first cut).

Three questions, one retriever:
- experts(query): SFU researchers for a plain-language topic (journey 4),
  each with the topics and publications that put them there;
- partners(query): EU organisations for a call or project idea (journey 1),
  reached through the Horizon Europe projects that match the topic, so
  every partner comes with the projects that are the evidence;
- calls(query): open and forthcoming Horizon Europe topics for a researcher
  or a lab's text (journey 2), with deadlines and the portal link.

Deterministic throughout: hybrid retrieval, graph expansion and arithmetic.
No model writes anything here; every result carries the node ids and URLs
of its evidence (plan 4.3: every claim cites an ID). Ranking is by fit to
the question only, never by any attribute of a person (plan 4.4).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from campus_ai.core.embed.reranker import Reranker
from campus_ai.core.graph import HybridRetriever

CANDIDATES = 50
COORDINATOR_WEIGHT = 1.25  # a coordinator of a matching project is a stronger lead than a participant

# Horizon Europe eligibility by country, as of 2026 (check before relying on it: associations change).
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "EL", "HU", "IE", "IT", "LV", "LT", "LU", "MT",
      "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
ASSOCIATED = {"AL", "AM", "BA", "CA", "CH", "EG", "FO", "GE", "IS", "IL", "KR", "MD", "ME", "MK", "NO", "NZ", "RS", "TN",
              "TR", "UA", "UK", "XK"}
COUNTRY_SETS = {"eu": EU, "associated": EU | ASSOCIATED, "all": None}
# Task instruction for the cross-encoder (B2): the query is a topic, project idea or researcher's text.
RERANK_INSTRUCTION = ("Given a research topic or project description, retrieve research projects, researcher profiles "
                      "or funding call topics on the same research subject")


def research_reranker() -> Reranker:
    """The default reranker with the research instruction; loads its weights on first use."""
    return Reranker(instruction=RERANK_INSTRUCTION)


class ResearchSearch:
    """`reranker` (e.g. `research_reranker()`) adds the cross-encoder step to every search; None leaves it off."""

    def __init__(self, driver: Any, embedder: Any, database: str | None = None, reranker: Any = None):
        self.driver = driver
        self.retriever = HybridRetriever(driver, embedder, database, candidates=CANDIDATES, reranker=reranker)
        self.database = database

    def run(self, query: str, **params: Any) -> list[dict]:
        records, _, _ = self.driver.execute_query(query, params, database_=self.database)
        return [record.data() for record in records]

    # --- journey 4: experts ---------------------------------------------------

    def experts(self, query: str, k: int = 10) -> list[dict]:
        hits = self.retriever.search(query, k, labels=["Researcher"], neighbors=0)
        if not hits:
            return []
        rows = self.run(
            "MATCH (r:Entity) WHERE r.id IN $ids "
            "OPTIONAL MATCH (r)-[:AUTHORED]->(p:Entity) WITH r, p ORDER BY p.cited_by_count DESC "
            "RETURN r.id AS id, r.name AS name, r.orcid AS orcid, r.url AS url, r.institution AS institution, "
            "r.topics AS topics, r.sdgs AS sdgs, r.works AS works, "
            "collect({title: p.title, year: p.year, url: p.url, id: p.id})[0..3] AS publications",
            ids=[hit.id for hit in hits])
        detail = {row["id"]: row for row in rows}
        out = []
        for hit in hits:
            row = detail.get(hit.id)
            if not row:
                continue
            out.append({
                "id": hit.id, "name": row["name"], "institution": row.get("institution") or "", "orcid": row.get("orcid") or "",
                "url": row.get("url") or "", "score": round(hit.weight, 4), "found_by": hit.found_by,
                "evidence": {"topics": row.get("topics") or [], "sdgs": row.get("sdgs") or [],
                             "publications": [p for p in row.get("publications") or [] if p.get("title")],
                             "works": row.get("works") or 0},
            })
        return out

    # --- journey 1: partners --------------------------------------------------

    def partners(self, query: str, k: int = 10, countries: str = "associated", exclude_project: str | None = None,
                 candidates: int = 30, home: str = "CA") -> list[dict]:
        """EU organisations ranked by the matching projects they took part in; `home` (the asking side) is left out."""
        hits = self.retriever.search(query, candidates + 1, labels=["Project"], neighbors=0)
        hits = [h for h in hits if h.id != exclude_project][:candidates]
        if not hits:
            return []
        allowed = COUNTRY_SETS.get(countries, EU | ASSOCIATED)
        rows = self.run(
            "MATCH (o:Entity)-[r:PARTICIPATED_IN]->(p:Entity) WHERE p.id IN $ids "
            "RETURN o.id AS id, o.name AS name, o.country AS country, o.activity AS activity, o.city AS city, "
            "o.url AS url, o.fields AS fields, o.projects AS projects, r.role AS role, "
            "p.id AS project, p.acronym AS acronym, p.title AS title, p.url AS project_url, p.start AS start",
            ids=[hit.id for hit in hits])
        score_of = {hit.id: hit.weight for hit in hits}
        orgs: dict[str, dict] = {}
        total: defaultdict[str, float] = defaultdict(float)
        for row in rows:
            country = row.get("country") or ""
            if (allowed is not None and country not in allowed) or (home and country == home):
                continue
            org = orgs.setdefault(row["id"], {
                "id": row["id"], "name": row["name"], "country": row.get("country") or "", "activity": row.get("activity") or "",
                "city": row.get("city") or "", "url": row.get("url") or "", "fields": row.get("fields") or [],
                "projects_total": row.get("projects") or 0, "evidence": {"projects": []}})
            weight = COORDINATOR_WEIGHT if row.get("role") == "coordinator" else 1.0
            total[row["id"]] += score_of.get(row["project"], 0.0) * weight
            org["evidence"]["projects"].append({"id": row["project"], "acronym": row.get("acronym") or "", "title": row.get("title") or "",
                                                "url": row.get("project_url") or "", "role": row.get("role") or "",
                                                "start": row.get("start") or "", "score": round(score_of.get(row["project"], 0.0), 4)})
        ranked = sorted(orgs.values(), key=lambda o: -total[o["id"]])[:k]
        for org in ranked:
            org["score"] = round(total[org["id"]], 4)
            org["evidence"]["projects"].sort(key=lambda p: -p["score"])
        return ranked

    # --- journey 2: calls -----------------------------------------------------

    def calls(self, query: str, k: int = 10, status: str = "open") -> list[dict]:
        """Horizon Europe call topics for a topic or a researcher's text; `status` open, forthcoming or all."""
        hits = self.retriever.search(query, CANDIDATES, labels=["CallTopic"], neighbors=0)
        if not hits:
            return []
        wanted = {"open": ["Open"], "forthcoming": ["Forthcoming"], "all": ["Open", "Forthcoming", "Closed", ""]}.get(status, ["Open"])
        if status == "open":
            wanted = ["Open", "Forthcoming"]  # a researcher planning a proposal wants both
        rows = self.run(
            "MATCH (t:Entity) WHERE t.id IN $ids AND coalesce(t.status, '') IN $status "
            "OPTIONAL MATCH (t)-[:PART_OF]->(c:Entity) "
            "RETURN t.id AS id, t.identifier AS identifier, t.title AS title, t.call AS call, t.call_title AS call_title, "
            "t.status AS status, t.opening AS opening, t.deadlines AS deadlines, t.url AS url, t.actions AS actions, "
            "collect(c.name) AS clusters",
            ids=[hit.id for hit in hits], status=wanted)
        detail = {row["id"]: row for row in rows}
        out = []
        for hit in hits:
            row = detail.get(hit.id)
            if row:
                out.append({**row, "score": round(hit.weight, 4), "found_by": hit.found_by})
            if len(out) >= k:
                break
        return out

    def call(self, call_id: str) -> dict | None:
        rows = self.run(
            "MATCH (t:Entity {id: $id}) OPTIONAL MATCH (t)-[:PART_OF]->(c:Entity) "
            "RETURN t.id AS id, t.identifier AS identifier, t.title AS title, t.call AS call, t.call_title AS call_title, "
            "t.status AS status, t.opening AS opening, t.deadlines AS deadlines, t.url AS url, t.actions AS actions, "
            "t.parts AS parts, collect(c.name) AS clusters", id=call_id)
        return rows[0] if rows and rows[0].get("identifier") else None

    def calls_for(self, researcher_id: str, k: int = 10, status: str = "open") -> dict:
        rows = self.run("MATCH (r:Entity {id: $id}) RETURN r.name AS name, r.text AS text", id=researcher_id)
        if not rows:
            return {"researcher": None, "calls": []}
        return {"researcher": {"id": researcher_id, "name": rows[0]["name"]}, "calls": self.calls(rows[0]["text"], k, status)}

    def counts(self) -> dict:
        rows = self.run("MATCH (n:Entity) WHERE n.kind IN ['Researcher', 'Project', 'Organization', 'CallTopic'] "
                        "RETURN n.kind AS kind, count(n) AS n")
        return {row["kind"]: row["n"] for row in rows}
