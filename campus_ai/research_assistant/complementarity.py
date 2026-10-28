"""Complementarity scorer (R4): what each partner on a shortlist adds to a call, and a complementary set.

Given a call analysis (`call_analyst.analyse`) and a partner shortlist
(`ResearchSearch.partners`), `assess` says for each organisation:
- which of the call's needs its evidence projects cover: the analysis topics,
  the partner-profile items that name expertise rather than a kind of
  organisation, and the call's keywords. A project covers a need when the
  need's content words (matched by their first five letters) occur in the
  project's acronym, title, objective or EuroSciVoc terms; two words suffice
  for a long phrase;
- which roles of the partner profile it can fill, from its organisation type
  and name by the keyword table `ROLES` (an SME for exploitation, a public
  authority as end user, a clinical partner...);
- its country and its coordinator experience in Horizon Europe.
Then the set view: needs covered by nobody, roles unfilled, countries
represented. `complement` picks n partners greedily, each time the one that
adds the most new needs, roles and countries (ties go to the higher-ranked
partner on the shortlist). Every "adds" line cites the ids it rests on:
project ids for coverage and coordination, the organisation id for its type
and country. Deterministic: no model call (plan 4.3).
"""

from __future__ import annotations

import math
import re
from typing import Any

from campus_ai.core.graph.stopwords import STOPWORDS
from campus_ai.research_assistant.consortium import eligibility

STEM = 5  # letters a word is matched on: "resilience" and "resilient" agree
NEED_SHARE = 0.5  # a need is covered when this share of its content words occur (at least two, or its only word)
SHORT = {"ai", "sme", "ssh", "ict", "iot", "co2"}  # short words that still carry meaning
# Stems of words that say how, not what ("increasing", "enhanced", "related"): they would match almost any project.
GENERIC = {"incre", "enhan", "reduc", "imple", "impro", "suppo", "relat", "devel", "provi", "addre", "contr", "ensur", "deliv",
           "innov", "new", "novel", "based", "area", "benef", "activ", "appro", "measu", "level", "integ", "boost", "stren"}
SHOWN_NEEDS, SHOWN_IDS = 4, 2  # an "adds" line names at most this many needs, each with at most this many project ids

# role: (words in a partner-profile item that ask for it, organisation types that fill it, words in a name that fill it).
# A company fills "SME for exploitation" only when CORDIS flags it as an SME.
ROLES = {
    "SME for exploitation": (("sme", "smes", "small and medium", "start-up", "startup", "exploitation", "commerciali"), ("company",), ()),
    "industry partner": (("industr", "private entit", "private sector", "compan", "business", "enterprise", "manufactur"), ("company",), ()),
    "public authority as end user": (("public bod", "public authorit", "authorit", "municipal", "local government", "region", "policymaker",
                                      "policy maker", "ministr", "agency", "agencies", "public administration"), ("public body",), ()),
    "clinical partner": (("clinic", "hospital", "patient", "healthcare professional", "health care provider"), (),
                         ("hospital", "clinic", "klinik", "umc", "medical cent", "medical univ", "ziekenhuis", "hopital", "hôpital",
                          "ospedal", "sairaala", "charite", "charité", "health service")),
    "research organisation": (("research organisation", "research organization", "research institut", "research centre",
                               "research center", "laborator"), ("research organisation",), ()),
    "university": (("universit", "academi", "higher education"), ("higher education",), ()),
    "civil society": (("ngo", "civil society", "citizen", "non-governmental", "association", "foundation"), ("other",), ()),
}


def _has(text: str, cues: tuple[str, ...]) -> bool:
    return any(re.search(r"\b" + re.escape(cue), text) for cue in cues)


def roles_needed(analysis: dict) -> tuple[list[dict], list[dict]]:
    """Split the partner profile into roles (by `ROLES`) and expertise items (everything else), each with its span."""
    roles: dict[str, dict] = {}
    expertise = []
    for item in analysis.get("partner_profile") or []:
        text = f"{item.get('text', '')} {item.get('span', '')}".casefold()
        matched = [role for role, (cues, _, _) in ROLES.items() if _has(text, cues)]
        for role in matched:
            roles.setdefault(role, {"role": role, "asked_by": item.get("text", ""), "span": item.get("span", "")})
        if not matched:
            expertise.append(item)
    return list(roles.values()), expertise


def roles_filled(org: dict) -> list[str]:
    """The roles an organisation can fill, from its CORDIS type, SME flag and name."""
    activity, name = (org.get("activity") or "").casefold(), (org.get("name") or "").casefold()
    out = []
    for role, (_, types, names) in ROLES.items():
        if role == "SME for exploitation" and not org.get("sme"):
            continue
        if activity in types or (names and _has(name, names)):
            out.append(role)
    return out


def stems(text: str) -> list[str]:
    """Content words cut to their first `STEM` letters, a plural s dropped first ("soils" and "soil" agree)."""
    out = []
    for word in re.findall(r"[^\W\d_]{2,}", (text or "").casefold()):
        if (len(word) < 4 or word in STOPWORDS) and word not in SHORT:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if word[:STEM] not in GENERIC:
            out.append(word[:STEM])
    return list(dict.fromkeys(out))


def needs(analysis: dict) -> list[dict]:
    """What the call asks the consortium to cover: analysis topics, expertise items of the profile, the call's keywords."""
    _, expertise = roles_needed(analysis)
    out, seen = [], set()
    for source, items in (("topic", analysis.get("topics") or []), ("expertise", expertise),
                          ("keyword", [{"text": k} for k in analysis.get("keywords") or []])):
        for item in items:
            text = " ".join(str(item.get("text") or "").split())
            words = stems(text)
            if text and words and text.casefold() not in seen:
                seen.add(text.casefold())
                out.append({"text": text, "source": source, "stems": words})
    return out


def covers(need: dict, project_words: set[str]) -> bool:
    found = sum(1 for w in need["stems"] if w in project_words)
    return found >= min(len(need["stems"]), max(2, math.ceil(NEED_SHARE * len(need["stems"]))))


def details(research: Any, shortlist: list[dict]) -> dict:
    """One Cypher query: each evidence project's text and EuroSciVoc terms, each organisation's SME flag and coordinations."""
    orgs = [p["id"] for p in shortlist]
    projects = sorted({x["id"] for p in shortlist for x in p.get("evidence", {}).get("projects", [])})
    if not orgs:
        return {"projects": {}, "orgs": {}}
    rows = research.run(
        "MATCH (o:Entity) WHERE o.id IN $orgs "
        "OPTIONAL MATCH (o)-[:PARTICIPATED_IN]->(p:Entity) WHERE p.id IN $projects "
        "OPTIONAL MATCH (p)-[:ABOUT]->(t:Entity) "
        "WITH o, p, collect(t.name) AS terms "
        "RETURN o.id AS org, o.sme AS sme, "
        "size([(o)-[r:PARTICIPATED_IN]->() WHERE r.role = 'coordinator' | 1]) AS coordinated, "
        "p.id AS project, p.text AS text, terms",
        orgs=orgs, projects=projects)
    out: dict = {"projects": {}, "orgs": {}}
    for row in rows:
        out["orgs"][row["org"]] = {"sme": bool(row.get("sme")), "coordinated": row.get("coordinated") or 0}
        if row.get("project"):
            out["projects"][row["project"]] = {"text": row.get("text") or "", "terms": [t for t in row.get("terms") or [] if t]}
    return out


def _cite(ids: list[str]) -> str:
    return " ".join(f"[{i}]" for i in ids)


def adds_line(partner: dict, need_ids: dict[str, list[str]], roles: list[str], country: bool) -> str:
    """A one-line summary built from facts only, each clause citing the ids it rests on."""
    shown = list(need_ids.items())[:SHOWN_NEEDS]
    clauses = [f"covers \"{text}\" {_cite(ids[:SHOWN_IDS])}" for text, ids in shown]
    if len(need_ids) > len(shown):
        rest = list(need_ids.items())[len(shown):]
        clauses.append(f"and {len(rest)} more need(s) {_cite(sorted({ids[0] for _, ids in rest}))}")
    if roles:
        clauses.append(f"can act as {', '.join(roles)} ({partner.get('activity') or 'type not recorded'}) [{partner['id']}]")
    if country and partner.get("country"):
        clauses.append(f"brings country {partner['country']} [{partner['id']}]")
    if partner.get("coordinator_of"):
        clauses.append(f"coordinated {_cite(partner['coordinator_of'])}"
                       + (f" ({partner['coordinated']} Horizon Europe projects coordinated in all)" if partner.get("coordinated") else ""))
    return f"{partner['name']} adds: " + ("; ".join(clauses) if clauses else "nothing new to this set") + "."


def assess(shortlist: list[dict], analysis: dict, info: dict | None = None) -> dict:
    """Per-partner coverage, roles, country and coordination, and the set view over the whole shortlist."""
    info = info or {"projects": {}, "orgs": {}}
    wanted = needs(analysis)
    asked, _ = roles_needed(analysis)
    asked_roles = [r["role"] for r in asked]
    partners = []
    for org in shortlist:
        extra = info["orgs"].get(org["id"], {})
        evidence = org.get("evidence", {}).get("projects", [])
        covered: dict[str, list[str]] = {}
        for project in evidence:
            known = info["projects"].get(project["id"], {})
            text = " ".join([project.get("acronym") or "", project.get("title") or "", known.get("text") or "", *known.get("terms", [])])
            words = set(stems(text))
            for need in wanted:
                if covers(need, words):
                    covered.setdefault(need["text"], []).append(project["id"])
        covered = {n["text"]: covered[n["text"]] for n in wanted if n["text"] in covered}  # topics first, keywords last
        partner = {
            "id": org["id"], "name": org["name"], "country": org.get("country") or "", "activity": org.get("activity") or "",
            "sme": extra.get("sme", bool(org.get("sme"))), "score": org.get("score"),
            "covers": [{"text": t, "source": next(n["source"] for n in wanted if n["text"] == t), "projects": ids} for t, ids in covered.items()],
            "coordinator_of": [p["id"] for p in evidence if p.get("role") == "coordinator"],
            "coordinated": extra.get("coordinated", 0),
        }
        partner["roles"] = [r for r in roles_filled({**org, "sme": partner["sme"]}) if r in asked_roles]
        partner["other_roles"] = [r for r in roles_filled({**org, "sme": partner["sme"]}) if r not in asked_roles]
        partner["adds"] = adds_line(partner, covered, partner["roles"], True)
        partner["cites"] = sorted({org["id"], *(i for ids in covered.values() for i in ids), *partner["coordinator_of"]})
        partners.append(partner)
    return {"needs": [{k: n[k] for k in ("text", "source")} for n in wanted], "roles_needed": asked,
            "partners": partners, "set": set_view(partners, wanted, asked_roles)}


def set_view(partners: list[dict], wanted: list[dict], asked_roles: list[str]) -> dict:
    """Needs covered and by whom, needs covered by nobody, roles filled and unfilled, countries represented."""
    by_need = {n["text"]: [p["id"] for p in partners if any(c["text"] == n["text"] for c in p["covers"])] for n in wanted}
    by_role = {r: [p["id"] for p in partners if r in p["roles"]] for r in asked_roles}
    countries: dict[str, list[str]] = {}
    for p in partners:
        if p["country"]:
            countries.setdefault(p["country"], []).append(p["id"])
    return {"covered": [{"text": t, "by": ids} for t, ids in by_need.items() if ids],
            "uncovered": [t for t, ids in by_need.items() if not ids],
            "roles_filled": [{"role": r, "by": ids} for r, ids in by_role.items() if ids],
            "roles_unfilled": [r for r, ids in by_role.items() if not ids],
            "countries": countries}


def complement(shortlist: list[dict], analysis: dict, n: int = 3, info: dict | None = None,
               home_country: str = "CA") -> dict:
    """Greedy pick of n partners maximising new coverage: needs, roles and countries; ties to the higher-ranked one."""
    assessed = assess(shortlist, analysis, info)
    asked_roles = [r["role"] for r in assessed["roles_needed"]]
    have_needs: set[str] = set()
    have_roles: set[str] = set()
    have_countries: set[str] = {home_country} if home_country else set()

    def new(partner: dict) -> tuple[dict, list[str], bool]:
        new_needs = {c["text"]: c["projects"] for c in partner["covers"] if c["text"] not in have_needs}
        new_roles = [r for r in partner["roles"] if r not in have_roles]
        return new_needs, new_roles, bool(partner["country"]) and partner["country"] not in have_countries

    pool = list(enumerate(assessed["partners"]))  # shortlist rank, partner
    picked, chosen = [], []
    while pool and len(picked) < n:
        def gain(entry: tuple[int, dict]) -> tuple[int, int]:
            new_needs, new_roles, new_country = new(entry[1])
            return len(new_needs) + len(new_roles) + int(new_country), -entry[0]  # ties: the higher-ranked partner
        rank, best = max(pool, key=gain)
        pool.remove((rank, best))
        new_needs, new_roles, new_country = new(best)
        picked.append({"id": best["id"], "name": best["name"], "country": best["country"], "activity": best["activity"],
                       "rank": rank + 1, "gain": len(new_needs) + len(new_roles) + int(new_country),
                       "adds": adds_line(best, new_needs, new_roles, new_country),
                       "cites": sorted({best["id"], *(i for ids in new_needs.values() for i in ids), *best["coordinator_of"]})})
        chosen.append(best)
        have_needs |= set(new_needs)
        have_roles |= set(new_roles)
        if best["country"]:
            have_countries.add(best["country"])
    view = set_view(chosen, needs(analysis), asked_roles)
    members = chosen + ([{"country": home_country}] if home_country else [])
    return {"picked": picked, "set": view,
            "eligibility": eligibility(members, analysis.get("action") or "", analysis.get("parts") or [])}
