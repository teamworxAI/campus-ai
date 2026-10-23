"""CORDIS and Funding & Tenders open data to graph records (R2): the EU side of the research graph.

Inputs are the Publications Office's Horizon Europe project bundle (CORDIS,
CC BY 4.0: project.csv, organization.csv, euroSciVoc.csv, topics.csv,
legalBasis.csv) and the Funding & Tenders portal's grants reference file
(every call topic with status, deadlines and tags). Class P data. Records
follow the plan's schema (4.2):

    (Organization)-[:PARTICIPATED_IN {role, ec_contribution}]->(Project)
    (Project)-[:ABOUT]->(Topic)               EuroSciVoc subject terms
    (Project)-[:UNDER_TOPIC]->(CallTopic)     the call topic it was funded under
    (Project)-[:FUNDED_UNDER]->(Cluster)      Horizon Europe programme part (legal basis)
    (CallTopic)-[:PART_OF]->(Cluster)

An organisation's text is its name, country, type and the subject terms of
its projects; a project's is its acronym, title and objective; a call
topic's is its identifier, title, call and tags: all public facts from the
funding records, nothing inferred.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

SOURCE = "cordis"
RIGHTS = "CC-BY-4.0"
MAX_OBJECTIVE = 1500
TERMS_PER_ORG = 8
PROJECTS_PER_ORG = 4
ACTIVITY = {"HES": "higher education", "REC": "research organisation", "PRC": "company", "PUB": "public body", "OTH": "other"}
PORTAL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"


def number(value: str | None) -> float:
    """CORDIS writes amounts with a decimal comma."""
    try:
        return float((value or "").replace(",", "."))
    except ValueError:
        return 0.0


def date(epoch_ms) -> str:
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def call_topic(item: dict) -> dict | None:
    """One CallTopic node from a Funding & Tenders grants record, or None if it is not a Horizon Europe topic."""
    if (item.get("frameworkProgramme") or {}).get("abbreviation") != "HORIZON" or item.get("type") != 1:
        return None
    identifier = item.get("identifier") or ""
    if not identifier:
        return None
    parts = [d.get("abbreviation") for d in item.get("programmeDivision") or [] if d.get("abbreviation")]
    status = (item.get("status") or {}).get("abbreviation") or ""
    deadlines = [date(d) for d in item.get("deadlineDatesLong") or []]
    tags = [t for t in (item.get("tags") or []) if t][:12]
    keywords = [k for k in (item.get("keywords") or []) if k][:12]
    text = f"{identifier}: {item.get('title') or ''}. Call: {item.get('callTitle') or item.get('callIdentifier') or ''}."
    if keywords or tags:
        text += " Keywords: " + "; ".join(keywords + tags) + "."
    actions = [a.get("abbreviation") for a in item.get("topicActions") or [] if a.get("abbreviation")]
    return {"id": f"topic:{identifier}", "label": "CallTopic", "modality": "text", "content": text, "props": {
        "source": "funding-tenders", "rights": RIGHTS, "identifier": identifier, "title": item.get("title") or "",
        "call": item.get("callIdentifier") or "", "call_title": item.get("callTitle") or "", "status": status,
        "opening": date(item.get("plannedOpeningDateLong")), "deadlines": deadlines, "parts": parts, "actions": actions,
        "url": PORTAL + identifier.lower()}}


def to_records(projects: list[dict], organizations: list[dict], euroscivoc: list[dict], topics: list[dict],
               legal_basis: list[dict], grants: list[dict]) -> list[dict]:
    """Graph records (nodes then links) for the Horizon Europe bundle plus the call topics."""
    nodes, links = [], []
    keep = {p["id"] for p in projects if p.get("id") and p.get("title")}

    clusters = {}
    project_cluster = {}
    for row in legal_basis:
        if row.get("uniqueProgrammePart") == "true" and row.get("legalBasis"):
            clusters.setdefault(row["legalBasis"], row.get("title") or row["legalBasis"])
            project_cluster[row["projectID"]] = row["legalBasis"]
    for code, title in clusters.items():
        nodes.append({"id": f"horizon:{code}", "label": "Cluster", "modality": "text", "content": f"Horizon Europe {code}: {title}",
                      "props": {"source": SOURCE, "code": code, "name": title}})

    terms, project_terms = {}, defaultdict(list)
    for row in euroscivoc:
        code = row.get("euroSciVocCode")
        if not code or row.get("projectID") not in keep:
            continue
        terms.setdefault(code, {"title": row.get("euroSciVocTitle") or code, "path": row.get("euroSciVocPath") or ""})
        project_terms[row["projectID"]].append(code)
    for code, term in terms.items():
        nodes.append({"id": f"esv:{code}", "label": "Topic", "modality": "text",
                      "content": term["title"] + (f" ({term['path']})" if term["path"] else ""),
                      "props": {"source": "euroscivoc", "name": term["title"], "path": term["path"]}})

    call_topics = {}
    for item in grants:
        node = call_topic(item)
        if node:
            call_topics[node["props"]["identifier"]] = node
    topic_titles = {row["topic"]: row.get("title") or "" for row in topics if row.get("topic")}
    project_topic = {row["projectID"]: row["topic"] for row in topics if row.get("topic") and row.get("projectID") in keep}
    for identifier in set(project_topic.values()) - set(call_topics):
        call_topics[identifier] = {"id": f"topic:{identifier}", "label": "CallTopic", "modality": "text",
                                   "content": f"{identifier}: {topic_titles.get(identifier, '')}",
                                   "props": {"source": SOURCE, "rights": RIGHTS, "identifier": identifier,
                                             "title": topic_titles.get(identifier, ""), "status": "", "url": PORTAL + identifier.lower()}}
    nodes += list(call_topics.values())
    for node in call_topics.values():
        for part in node["props"].get("parts", []):
            if part in clusters:
                links.append({"src": node["id"], "type": "PART_OF", "dst": f"horizon:{part}"})

    participants = defaultdict(list)
    for row in organizations:
        if row.get("projectID") in keep and row.get("organisationID"):
            participants[row["projectID"]].append(row)

    orgs: dict[str, dict] = {}
    org_terms: Counter = Counter()
    org_projects: defaultdict[str, list] = defaultdict(list)
    for project in projects:
        pid = project.get("id")
        if pid not in keep:
            continue
        objective = " ".join((project.get("objective") or "").split())[:MAX_OBJECTIVE]
        countries = sorted({r.get("country") for r in participants[pid] if r.get("country")})
        text = f"{project.get('acronym') or ''}: {project['title']}" + (f"\n{objective}" if objective else "")
        nodes.append({"id": f"{SOURCE}:{pid}", "label": "Project", "modality": "text", "content": text, "props": {
            "source": SOURCE, "rights": RIGHTS, "acronym": project.get("acronym") or "", "title": project["title"],
            "status": project.get("status") or "", "start": project.get("startDate") or "", "end": project.get("endDate") or "",
            "total_cost": number(project.get("totalCost")), "ec_contribution": number(project.get("ecMaxContribution")),
            "funding_scheme": project.get("fundingScheme") or "", "call": project.get("masterCall") or "",
            "topic": project_topic.get(pid, ""), "countries": countries, "participants": len(participants[pid]),
            "url": f"https://cordis.europa.eu/project/id/{pid}", "doi": project.get("grantDoi") or ""}})
        for code in dict.fromkeys(project_terms.get(pid, [])):
            links.append({"src": f"{SOURCE}:{pid}", "type": "ABOUT", "dst": f"esv:{code}"})
        if pid in project_topic:
            links.append({"src": f"{SOURCE}:{pid}", "type": "UNDER_TOPIC", "dst": f"topic:{project_topic[pid]}"})
        if pid in project_cluster:
            links.append({"src": f"{SOURCE}:{pid}", "type": "FUNDED_UNDER", "dst": f"horizon:{project_cluster[pid]}"})
        for row in participants[pid]:
            oid = f"{SOURCE}:org:{row['organisationID']}"
            orgs.setdefault(oid, row)
            org_projects[oid].append((project.get("startDate") or "", project.get("acronym") or project["title"]))
            for code in project_terms.get(pid, []):
                org_terms[(oid, code)] += 1
            links.append({"src": oid, "type": "PARTICIPATED_IN", "dst": f"{SOURCE}:{pid}", "props": {
                "role": row.get("role") or "", "ec_contribution": number(row.get("ecContribution"))}})

    for oid, row in orgs.items():
        top = sorted(((n, code) for (o, code), n in org_terms.items() if o == oid), reverse=True)[:TERMS_PER_ORG]
        fields = [terms[code]["title"] for _, code in top if code in terms]
        recent = [acronym for _, acronym in sorted(org_projects[oid], reverse=True)[:PROJECTS_PER_ORG]]
        kind = ACTIVITY.get(row.get("activityType") or "", row.get("activityType") or "")
        text = f"{row.get('name') or ''} ({row.get('country') or '?'}{', ' + kind if kind else ''})."
        if fields:
            text += " Fields: " + "; ".join(fields) + "."
        if recent:
            text += " Horizon Europe projects: " + ", ".join(recent) + "."
        nodes.append({"id": oid, "label": "Organization", "modality": "text", "content": text, "props": {
            "source": SOURCE, "rights": RIGHTS, "name": row.get("name") or "", "short_name": row.get("shortName") or "",
            "country": row.get("country") or "", "city": row.get("city") or "", "activity": kind,
            "sme": row.get("SME") == "true", "url": row.get("organizationURL") or "", "projects": len(org_projects[oid]),
            "fields": fields}})
    return nodes + links
