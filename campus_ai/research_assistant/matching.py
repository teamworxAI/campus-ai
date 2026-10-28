"""Expert, partner and call matching over the research graph (R4, first cut).

Three questions, one retriever:
- experts(query): SFU researchers for a plain-language topic (journey 4),
  each with the topics and publications that put them there;
- partners(query): EU organisations for a call or project idea (journey 1),
  reached through the Horizon Europe projects that match the topic, so
  every partner comes with the projects that are the evidence; optionally
  (`signal`) also through their own Organization nodes, fused by RRF;
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
from campus_ai.core.graph.retriever import RRF_K

CANDIDATES = 50
WEIGHTINGS = ("probability", "rank", "rrf")  # how reranked projects count towards their organisations (B2 follow-up)
# What ranks a partner: the matching projects it took part in, its own Organization node, or both fused by RRF.
SIGNALS = ("projects", "organisations", "fused")
# The direct signal reaches the hidden partner 5 times in 100 on the back-test and fusing it lowers MRR, so it stays off
# (evals/research_assistant/r4_org_signal_20261028.md).
DEFAULT_SIGNAL = "projects"
ORGANISATION_WEIGHT = 1.0  # the direct signal's share in `fused`: its reciprocal ranks count this many times
RECENT_PROJECTS = 3  # projects cited for an organisation found directly, when none of its projects matched
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


def project_weights(hits: list, weighting: str = "probability") -> dict[str, float]:
    """What each matching project counts for when its organisations are scored.

    Hits arrive in the order the search ranked them. Without a reranker every
    weighting is the fusion score. With one: `probability` is the reranker's
    score (it saturates near 0 or 1, so a few projects dominate), `rank` is
    1 / (k + reranked rank), and `rrf` adds the fusion rank's 1 / (k + rank),
    the same reciprocal rank fusion the retriever uses.
    """
    if weighting not in WEIGHTINGS:
        raise ValueError(f"weighting must be one of {WEIGHTINGS}")
    if not hits or any(h.rerank is None for h in hits) or weighting == "probability":
        return {h.id: h.weight for h in hits}
    by_rerank = sorted(hits, key=lambda h: -h.rerank)  # stable: the order the retriever gave breaks ties
    weights = {h.id: 1.0 / (RRF_K + rank) for rank, h in enumerate(by_rerank, start=1)}
    if weighting == "rrf":
        for rank, h in enumerate(sorted(hits, key=lambda h: -h.score), start=1):
            weights[h.id] += 1.0 / (RRF_K + rank)
    return weights


class ResearchSearch:
    """`reranker` (e.g. `research_reranker()`) adds the cross-encoder step to every search; None leaves it off."""

    def __init__(self, driver: Any, embedder: Any, database: str | None = None, reranker: Any = None,
                 pool: int | None = None, weighting: str = "probability", signal: str = DEFAULT_SIGNAL):
        if weighting not in WEIGHTINGS:
            raise ValueError(f"weighting must be one of {WEIGHTINGS}")
        if signal not in SIGNALS:
            raise ValueError(f"signal must be one of {SIGNALS}")
        self.driver = driver
        self.weighting = weighting
        self.signal = signal
        self.retriever = HybridRetriever(driver, embedder, database, candidates=CANDIDATES, reranker=reranker, pool=pool)
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
                 candidates: int = 30, home: str = "CA", weighting: str | None = None, signal: str | None = None,
                 organisation_weight: float = ORGANISATION_WEIGHT) -> list[dict]:
        """EU organisations for a topic; `home` (the asking side) and ineligible countries are left out.

        `signal` (default the search's) picks what ranks them: `projects`, the
        matching projects they took part in (each project's weight, coordinators
        counting more); `organisations`, their own nodes matched directly; or
        `fused`, reciprocal rank fusion of the two orders, the direct order
        counting `organisation_weight` times. Every organisation cites its
        matching projects (or, found directly with none, its most recent ones)
        and, when its own node matched, how (`evidence.organisation`).
        `weighting` overrides the search's default (see `project_weights`).
        """
        weighting, signal = weighting or self.weighting, signal or self.signal
        if signal not in SIGNALS:
            raise ValueError(f"signal must be one of {SIGNALS}")
        allowed = COUNTRY_SETS.get(countries, EU | ASSOCIATED)

        def eligible(country: str) -> bool:
            return not ((allowed is not None and country not in allowed) or (home and country == home))

        def record(row: dict) -> dict:
            return {"id": row["id"], "name": row["name"], "country": row.get("country") or "", "activity": row.get("activity") or "",
                    "city": row.get("city") or "", "url": row.get("url") or "", "fields": row.get("fields") or [],
                    "projects_total": row.get("projects") or 0, "evidence": {"projects": []}}

        orgs: dict[str, dict] = {}
        by_projects: list[str] = []
        total: defaultdict[str, float] = defaultdict(float)
        if signal != "organisations":
            # With a reranker, take its whole pool: the combined weightings need the fusion ranks of all of it.
            want = max(candidates + 1, self.retriever.pool) if self.retriever.reranker is not None else candidates + 1
            hits = [h for h in self.retriever.search(query, want, labels=["Project"], neighbors=0) if h.id != exclude_project]
            score_of = project_weights(hits, weighting)
            if weighting == "rrf":
                hits.sort(key=lambda h: -score_of[h.id])
            hits = hits[:candidates]
            rows = self.run(
                "MATCH (o:Entity)-[r:PARTICIPATED_IN]->(p:Entity) WHERE p.id IN $ids "
                "RETURN o.id AS id, o.name AS name, o.country AS country, o.activity AS activity, o.city AS city, "
                "o.url AS url, o.fields AS fields, o.projects AS projects, r.role AS role, "
                "p.id AS project, p.acronym AS acronym, p.title AS title, p.url AS project_url, p.start AS start",
                ids=[hit.id for hit in hits]) if hits else []
            for row in rows:
                if not eligible(row.get("country") or ""):
                    continue
                org = orgs.setdefault(row["id"], record(row))
                weight = COORDINATOR_WEIGHT if row.get("role") == "coordinator" else 1.0
                total[row["id"]] += score_of.get(row["project"], 0.0) * weight
                org["evidence"]["projects"].append({"id": row["project"], "acronym": row.get("acronym") or "", "title": row.get("title") or "",
                                                    "url": row.get("project_url") or "", "role": row.get("role") or "",
                                                    "start": row.get("start") or "", "score": round(score_of.get(row["project"], 0.0), 4)})
            by_projects = sorted(orgs, key=lambda id_: -total[id_])

        direct: list[str] = []
        direct_score: dict[str, float] = {}
        if signal != "projects":
            hits = self.retriever.search(query, CANDIDATES, labels=["Organization"], neighbors=0)
            rows = self.run(
                "MATCH (o:Entity) WHERE o.id IN $ids OPTIONAL MATCH (o)-[r:PARTICIPATED_IN]->(p:Entity) "
                "WITH o, r, p ORDER BY p.start DESC "
                "RETURN o.id AS id, o.name AS name, o.country AS country, o.activity AS activity, o.city AS city, "
                "o.url AS url, o.fields AS fields, o.projects AS projects, collect({id: p.id, acronym: p.acronym, title: p.title, "
                f"url: p.url, role: r.role, start: p.start}})[0..{RECENT_PROJECTS}] AS recent",
                ids=[hit.id for hit in hits]) if hits else []
            detail = {row["id"]: row for row in rows}
            for hit in hits:
                row = detail.get(hit.id)
                if not row or not eligible(row.get("country") or ""):
                    continue
                org = orgs.setdefault(hit.id, record(row))
                org["evidence"]["organisation"] = {"id": hit.id, "found_by": hit.found_by, "score": round(hit.weight, 4),
                                                   "similarity": round(hit.similarity, 3)}
                if not org["evidence"]["projects"]:  # nothing of its matched: cite what it did most recently
                    org["evidence"]["projects"] = [{"id": p["id"], "acronym": p.get("acronym") or "", "title": p.get("title") or "",
                                                    "url": p.get("url") or "", "role": p.get("role") or "", "start": p.get("start") or "",
                                                    "score": 0.0} for p in row.get("recent") or [] if p.get("id") and p["id"] != exclude_project]
                direct.append(hit.id)
                direct_score[hit.id] = hit.weight
                if len(direct) >= candidates:
                    break

        if signal == "projects":
            score = dict(total)
        elif signal == "organisations":
            score = direct_score
        else:
            score = defaultdict(float)
            for rank, id_ in enumerate(by_projects, start=1):
                score[id_] += 1.0 / (RRF_K + rank)
            for rank, id_ in enumerate(direct, start=1):
                score[id_] += organisation_weight / (RRF_K + rank)
        ranked = sorted((o for o in orgs.values() if o["id"] in score), key=lambda o: -score[o["id"]])[:k]
        for org in ranked:
            org["score"] = round(score[org["id"]], 4)
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
            "t.parts AS parts, t.keywords AS keywords, t.text AS text, t.expected_outcome AS expected_outcome, t.scope AS scope, "
            "t.action_type AS action_type, t.budget AS budget, t.expected_grants AS expected_grants, t.conditions AS conditions, "
            "collect(c.name) AS clusters", id=call_id)
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
