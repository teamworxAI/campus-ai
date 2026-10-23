"""OpenAlex works to graph records (R1): researchers, publications, topics, SDGs.

OpenAlex (https://openalex.org) is open scholarly metadata under CC0: class P
data (plan section 2). `to_records` turns the works of one institution into
the JSONL records `scripts/graph_search.py index` reads, following the plan's
schema (4.2):

    (Researcher)-[:AFFILIATED_WITH]->(Institution)
    (Researcher)-[:AUTHORED]->(Publication)-[:ABOUT {score}]->(Topic)
    (Researcher)-[:WORKS_ON {count}]->(Topic)          aggregated from their publications
    (Publication)-[:SUPPORTS {score}]->(SDG)            OpenAlex's UN SDG tags, the bridge to REE's SDGs
    (Researcher)-[:CONTRIBUTES_TO {count}]->(SDG)
    (Researcher)-[:COAUTHORED_WITH {count}]->(Researcher)

Only authors affiliated with the harvested institution become Researcher
nodes (the EU co-author network comes with R2/R5). Every researcher's text,
what expert search embeds, is their name, institution, topics and recent
titles: public facts from their publications, nothing inferred about the
person (plan 4.4). The REE profile fields (research statement, accepting
students, SDG tags) are added once RIO agrees (R0).
"""

from __future__ import annotations

from collections import Counter, defaultdict

SOURCE = "openalex"
RIGHTS = "CC0-1.0"
MAX_ABSTRACT = 1200
MAX_AUTHORS = 30  # mega-collaboration papers say nothing about individual expertise
TOPICS_PER_RESEARCHER = 8
TITLES_PER_RESEARCHER = 3
WORK_FIELDS = ("id", "doi", "title", "publication_year", "type", "language", "cited_by_count", "open_access",
               "authorships", "topics", "sustainable_development_goals", "abstract_inverted_index", "primary_location")


def abstract_text(inverted: dict | None) -> str:
    """OpenAlex stores abstracts as word -> positions; put the words back in order."""
    if not inverted:
        return ""
    words = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    return " ".join(word for _, word in words)


def trim(work: dict) -> dict:
    """The fields the loader keeps from an API work record."""
    out = {k: work.get(k) for k in WORK_FIELDS}
    out["abstract"] = abstract_text(work.get("abstract_inverted_index"))[:MAX_ABSTRACT]
    out.pop("abstract_inverted_index")
    out["authorships"] = [{
        "author": {k: (a.get("author") or {}).get(k) for k in ("id", "display_name", "orcid")},
        "position": a.get("author_position"),
        "institutions": [{k: i.get(k) for k in ("id", "display_name", "ror", "country_code")} for i in a.get("institutions") or []],
    } for a in work.get("authorships") or []]
    out["topics"] = [{"id": t.get("id"), "display_name": t.get("display_name"), "score": t.get("score"),
                      "subfield": (t.get("subfield") or {}).get("display_name"), "field": (t.get("field") or {}).get("display_name")}
                     for t in work.get("topics") or []]
    out["sustainable_development_goals"] = [{"id": s.get("id"), "display_name": s.get("display_name"), "score": s.get("score")}
                                            for s in work.get("sustainable_development_goals") or []]
    out["open_access"] = (work.get("open_access") or {}).get("oa_status")
    out["url"] = work.get("doi") or ((work.get("primary_location") or {}).get("landing_page_url")) or work.get("id")
    out.pop("primary_location")
    return out


def sdg_id(url: str) -> str:
    return f"{SOURCE}:sdg:{url.rstrip('/').rsplit('/', 1)[-1]}"


def to_records(works: list[dict], institution_ror: str, max_authors: int = MAX_AUTHORS) -> list[dict]:
    """Graph records (nodes then links) for trimmed works of one institution."""
    ror = institution_ror if institution_ror.startswith("http") else f"https://ror.org/{institution_ror}"
    researchers: dict[str, dict] = {}
    institution: dict | None = None
    topics: dict[str, dict] = {}
    sdgs: dict[str, str] = {}
    works_on: Counter = Counter()
    contributes: Counter = Counter()
    coauthors: Counter = Counter()
    titles: defaultdict[str, list] = defaultdict(list)
    nodes, links = [], []

    for work in works:
        if not work.get("title") or len(work.get("authorships") or []) > max_authors or not work.get("id"):
            continue
        wid = f"{SOURCE}:{work['id'].rsplit('/', 1)[-1]}"
        text = work["title"] + (f"\n{work['abstract']}" if work.get("abstract") else "")
        nodes.append({"id": wid, "label": "Publication", "modality": "text", "content": text, "props": {
            "source": SOURCE, "rights": RIGHTS, "title": work["title"], "year": work.get("publication_year"),
            "url": work.get("url"), "cited_by_count": work.get("cited_by_count") or 0, "type": work.get("type") or "",
            "open_access": work.get("open_access") or "", "language": work.get("language") or ""}})
        for topic in work.get("topics") or []:
            if not topic.get("id"):
                continue
            tid = f"{SOURCE}:{topic['id'].rsplit('/', 1)[-1]}"
            topics.setdefault(tid, topic)
            links.append({"src": wid, "type": "ABOUT", "dst": tid, "props": {"score": round(topic.get("score") or 0, 3)}})
        for sdg in work.get("sustainable_development_goals") or []:
            if not sdg.get("id"):
                continue
            sid = sdg_id(sdg["id"])
            sdgs.setdefault(sid, sdg.get("display_name") or sid)
            links.append({"src": wid, "type": "SUPPORTS", "dst": sid, "props": {"score": round(sdg.get("score") or 0, 3)}})
        here = []
        for authorship in work.get("authorships") or []:
            author = authorship.get("author") or {}
            insts = authorship.get("institutions") or []
            mine = next((i for i in insts if (i.get("ror") or "") == ror), None)
            if not author.get("id") or mine is None:
                continue
            aid = f"{SOURCE}:{author['id'].rsplit('/', 1)[-1]}"
            institution = institution or mine
            researchers.setdefault(aid, {"name": author.get("display_name") or aid, "orcid": author.get("orcid") or "",
                                         "url": author["id"]})
            here.append(aid)
            links.append({"src": aid, "type": "AUTHORED", "dst": wid, "props": {"position": authorship.get("position") or ""}})
            titles[aid].append((work.get("cited_by_count") or 0, work.get("publication_year") or 0, work["title"]))
            for topic in work.get("topics") or []:
                if topic.get("id"):
                    works_on[(aid, f"{SOURCE}:{topic['id'].rsplit('/', 1)[-1]}")] += 1
            for sdg in work.get("sustainable_development_goals") or []:
                if sdg.get("id"):
                    contributes[(aid, sdg_id(sdg["id"]))] += 1
        for a in here:
            for b in here:
                if a < b:
                    coauthors[(a, b)] += 1

    inst_id = ror
    if institution:
        nodes.append({"id": inst_id, "label": "Institution", "modality": "text", "content": institution.get("display_name") or ror,
                      "props": {"source": SOURCE, "name": institution.get("display_name") or "", "country": institution.get("country_code") or "",
                                "url": ror}})
    for tid, topic in topics.items():
        detail = ", ".join(x for x in (topic.get("subfield"), topic.get("field")) if x)
        nodes.append({"id": tid, "label": "Topic", "modality": "text",
                      "content": topic["display_name"] + (f" ({detail})" if detail else ""),
                      "props": {"source": SOURCE, "name": topic["display_name"], "subfield": topic.get("subfield") or "",
                                "field": topic.get("field") or ""}})
    for sid, name in sdgs.items():
        nodes.append({"id": sid, "label": "SDG", "modality": "text", "content": f"UN Sustainable Development Goal: {name}",
                      "props": {"source": SOURCE, "name": name}})
    topic_names = {tid: t["display_name"] for tid, t in topics.items()}
    for aid, who in researchers.items():
        top = sorted(((n, tid) for (a, tid), n in works_on.items() if a == aid), reverse=True)[:TOPICS_PER_RESEARCHER]
        top_names = [topic_names[tid] for _, tid in top]
        goals = sorted(((n, sid) for (a, sid), n in contributes.items() if a == aid), reverse=True)
        recent = [t for _, _, t in sorted(titles[aid], reverse=True)[:TITLES_PER_RESEARCHER]]
        inst_name = (institution or {}).get("display_name") or ""
        text = f"{who['name']}. {inst_name}.".strip()
        if top_names:
            text += " Research topics: " + "; ".join(top_names) + "."
        if recent:
            text += " Publications: " + " | ".join(recent)
        nodes.append({"id": aid, "label": "Researcher", "modality": "text", "content": text, "props": {
            "source": SOURCE, "rights": RIGHTS, "name": who["name"], "orcid": who["orcid"], "url": who["url"],
            "institution": inst_name, "topics": top_names, "sdgs": [sdgs[sid] for _, sid in goals][:5],
            "works": len(titles[aid])}})
        if institution:
            links.append({"src": aid, "type": "AFFILIATED_WITH", "dst": inst_id})
        links += [{"src": aid, "type": "WORKS_ON", "dst": tid, "props": {"count": n}} for n, tid in top]
        links += [{"src": aid, "type": "CONTRIBUTES_TO", "dst": sid, "props": {"count": n}} for n, sid in goals]
    links += [{"src": a, "type": "COAUTHORED_WITH", "dst": b, "props": {"count": n}} for (a, b), n in coauthors.items()]
    return nodes + links
