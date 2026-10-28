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
topic's is its identifier, title, call and tags, plus, when its details page
was fetched (topicDetails JSON, R4), its description as "Expected outcome:"
and "Scope:" sections: all public facts from the funding records, nothing
inferred.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser

SOURCE = "cordis"
RIGHTS = "CC-BY-4.0"
MAX_OBJECTIVE = 1500
TERMS_PER_ORG = 8
PROJECTS_PER_ORG = 4
ACTIVITY = {"HES": "higher education", "REC": "research organisation", "PRC": "company", "PUB": "public body", "OTH": "other"}
PORTAL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"
MAX_DESCRIPTION = 4000  # characters of a topic's description kept in its text
MAX_CONDITIONS = 1000
SECTION = re.compile(r'<p[^>]*class="topicdescriptionkind"[^>]*>(.*?)</p>', re.S | re.I)
SECTION_NAMES = {"expected outcome": "Expected outcome", "expected outcomes": "Expected outcome", "scope": "Scope"}
CONDITION_HEADING = re.compile(r"<h4[^>]*>(.*?)</h4>", re.S | re.I)
ELIGIBILITY = re.compile(r"eligible countries|other eligib|specific conditions", re.I)
# Lines in nearly every topic's conditions: pointers to the General Annexes and standard clauses.
BOILERPLATE = re.compile(r"described in|^A number of non-EU/non-Associated|^Not applicable|^If projects use satellite-based", re.I)
BLOCKS = {"p", "div", "li", "ul", "ol", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section"}


class _Text(HTMLParser):
    """Text of an HTML fragment: blocks become lines, list items get a dash."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in BLOCKS:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):
        if tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_text(html: str | None) -> str:
    """Plain text of portal HTML (standard library parser); blank lines and runs of spaces collapsed."""
    parser = _Text()
    parser.feed(html or "")
    parser.close()
    lines = (" ".join(line.replace("﻿", "").split()) for line in "".join(parser.parts).split("\n"))
    return "\n".join(line for line in lines if line and line != "-")


def description_sections(html: str | None) -> dict[str, str]:
    """A topic description's sections by name ("Expected outcome", "Scope", ...); text before any heading is "Scope"."""
    pieces = SECTION.split(html or "")
    out: dict[str, str] = {}
    lead = html_text(pieces[0])
    if lead:
        out["Scope"] = lead
    for heading, body in zip(pieces[1::2], pieces[2::2]):
        name = html_text(heading).rstrip(":").strip()
        text = html_text(body)
        if not text or name.lower() in ("", "null"):
            continue
        name = SECTION_NAMES.get(name.lower(), name)
        out[name] = (out[name] + "\n" + text) if name in out else text
    return out


def conditions_text(html: str | None) -> str:
    """The topic-specific eligibility conditions: the eligibility sections without the lines every topic repeats."""
    pieces = CONDITION_HEADING.split(html or "")
    keep = []
    for heading, body in zip(pieces[1::2], pieces[2::2]):
        if ELIGIBILITY.search(html_text(heading)):
            keep += [line for line in html_text(body).split("\n") if not BOILERPLATE.search(line)]
    return "\n".join(dict.fromkeys(keep))[:MAX_CONDITIONS]


def topic_detail_props(detail: dict) -> dict:
    """Props from a topicDetails record: description sections, action type, budget and conditions.

    Every key is always present (empty or 0 when unknown): the graph store merges props into an existing
    node, so a key left out would keep a stale value from an earlier index run."""
    sections = description_sections(detail.get("description"))
    types = [" ".join(t["typeOfAction"].split()) for a in detail.get("actions") or [] for t in a.get("types") or [] if t.get("typeOfAction")]
    budget, grants = 0.0, 0
    for actions in ((detail.get("budgetOverviewJSONItem") or {}).get("budgetTopicActionMap") or {}).values():
        for action in actions:
            if not str(action.get("action") or "").startswith(detail.get("identifier") or "\0"):
                continue
            budget += sum(number(str(v)) for v in (action.get("budgetYearMap") or {}).values())
            grants += int(action.get("expectedGrants") or 0)
    return {"expected_outcome": sections.get("Expected outcome", "")[:MAX_DESCRIPTION], "scope": sections.get("Scope", "")[:MAX_DESCRIPTION],
            "action_type": types[0] if types else "", "budget": budget, "expected_grants": grants,
            "conditions": conditions_text(detail.get("conditions"))}


def description(props: dict) -> str:
    """The description part of a call topic's text, capped at MAX_DESCRIPTION characters."""
    text = "\n".join(f"{name}: {props[key]}" for name, key in (("Expected outcome", "expected_outcome"), ("Scope", "scope"))
                     if props.get(key))
    return text[:MAX_DESCRIPTION]


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


def horizon_topic(item: dict) -> bool:
    """Whether a grants record is a Horizon Europe call topic (not a tender, not another programme)."""
    return ((item.get("frameworkProgramme") or {}).get("abbreviation") == "HORIZON" and item.get("type") == 1
            and bool(item.get("identifier")))


def call_topic(item: dict, detail: dict | None = None) -> dict | None:
    """One CallTopic node from a Funding & Tenders grants record and its details page if fetched; None if not Horizon Europe."""
    if not horizon_topic(item):
        return None
    identifier = item["identifier"]
    parts = [d.get("abbreviation") for d in item.get("programmeDivision") or [] if d.get("abbreviation")]
    status = (item.get("status") or {}).get("abbreviation") or ""
    deadlines = [date(d) for d in item.get("deadlineDatesLong") or []]
    tags = [t for t in (item.get("tags") or []) if t][:12]
    keywords = [k for k in (item.get("keywords") or []) if k][:12]
    text = f"{identifier}: {item.get('title') or ''}. Call: {item.get('callTitle') or item.get('callIdentifier') or ''}."
    if keywords or tags:
        text += " Keywords: " + "; ".join(keywords + tags) + "."
    actions = [a.get("abbreviation") for a in item.get("topicActions") or [] if a.get("abbreviation")]
    props = {"source": "funding-tenders", "rights": RIGHTS, "identifier": identifier, "title": item.get("title") or "",
             "call": item.get("callIdentifier") or "", "call_title": item.get("callTitle") or "", "status": status,
             "opening": date(item.get("plannedOpeningDateLong")), "deadlines": deadlines, "parts": parts, "actions": actions,
             "keywords": keywords + [t for t in tags if t not in keywords], "url": PORTAL + identifier.lower()}
    if detail:
        props.update(topic_detail_props(detail))
        if props.get("expected_outcome") or props.get("scope"):
            text += "\n" + description(props)
    return {"id": f"topic:{identifier}", "label": "CallTopic", "modality": "text", "content": text, "props": props}


def to_records(projects: list[dict], organizations: list[dict], euroscivoc: list[dict], topics: list[dict],
               legal_basis: list[dict], grants: list[dict], details: dict[str, dict] | None = None) -> list[dict]:
    """Graph records (nodes then links) for the Horizon Europe bundle plus the call topics (with their details pages if given)."""
    details = details or {}
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
        node = call_topic(item, details.get(item.get("identifier") or ""))
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
