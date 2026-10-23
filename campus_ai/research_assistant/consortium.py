"""Consortium check and brief (R5, journey 3): eligibility rules in code, a brief from the local model, every claim checked.

Given a call topic and a partner shortlist (R4), `eligibility` applies the
Horizon Europe consortium rules deterministically, `brief` asks the local
model for a short consortium brief that cites its evidence by id, and
`check_citations` drops every sentence that cites an id not in the evidence
and flags sentences that cite nothing (plan 4.3: every claim cites an ID;
unsupported claims are dropped before anyone reads them). Nothing here
sends anything: the brief is a draft for the research office (plan 4.4).

Rules (Horizon Europe General Annexes, section B; the call's own conditions
override them, so the result always says which rule it applied):
- RIA and IA: at least three independent legal entities, each established in
  a different member state or associated country, at least one in a member
  state;
- CSA and single-beneficiary actions (ERC, MSCA fellowships, EIC Accelerator):
  one legal entity in a member state or associated country.
Canada's association covers Pillar II (the clusters, HORIZON.2.*): a Canadian
member counts as associated there and as a third-country participant
elsewhere.
"""

from __future__ import annotations

import re

from campus_ai.core.llm import generate
from campus_ai.research_assistant.matching import ASSOCIATED, EU

MULTI_PARTNER = ("HORIZON-RIA", "HORIZON-IA", "HORIZON-JU-RIA", "HORIZON-JU-IA")
PILLAR_II_ONLY = {"CA"}  # associated to Pillar II only
CITATION = re.compile(r"\[([a-z]+:[^\]\s]+)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")

BRIEF_SYSTEM = """You draft a short consortium brief for a university research office preparing a Horizon Europe proposal.
Write in plain English, at most 300 words, in Markdown with three headings: "Fit to the call", "Proposed partners" and "Gaps and next steps".
Every factual claim about a partner or a project must cite its id in square brackets, e.g. [cordis:org:123] or [cordis:101456], using only the ids given in the evidence. Never invent partners, projects, numbers or contacts. If the evidence is thin, say so."""


def eligibility(members: list[dict], action: str = "", parts: list[str] | None = None) -> dict:
    """Apply the consortium rule for `action` (e.g. HORIZON-RIA) to members with a `country` each."""
    pillar_ii = any(str(p).startswith("HORIZON.2") for p in parts or [])
    countries = []
    for m in members:
        c = (m.get("country") or "").upper()
        if c in EU:
            countries.append((c, "member state"))
        elif c in ASSOCIATED and (c not in PILLAR_II_ONLY or pillar_ii):
            countries.append((c, "associated country"))
        elif c in PILLAR_II_ONLY:
            countries.append((c, "third country (associated to Pillar II only)"))
        else:
            countries.append((c, "third country"))
    distinct = {c for c, kind in countries if kind in ("member state", "associated country")}
    member_states = {c for c, kind in countries if kind == "member state"}
    problems = []
    if any(a in (action or "") for a in MULTI_PARTNER):
        rule = "at least three independent legal entities in three different member states or associated countries, at least one in a member state"
        if len(distinct) < 3:
            problems.append(f"only {len(distinct)} different eligible countries ({', '.join(sorted(distinct)) or 'none'}); three are needed")
        if not member_states:
            problems.append("no member of an EU member state")
    else:
        rule = "one legal entity established in a member state or associated country"
        if not distinct:
            problems.append("no member in a member state or associated country")
    third = [c for c, kind in countries if kind.startswith("third")]
    if third:
        problems.append("third-country members do not count towards the minimum and may need their own funding: " + ", ".join(sorted(set(third))))
    return {"action": action or "", "rule": rule, "ok": not [p for p in problems if "do not count" not in p],
            "problems": problems, "countries": countries, "member_states": sorted(member_states), "eligible_countries": sorted(distinct)}


def evidence_ids(call: dict | None, partners: list[dict]) -> set[str]:
    ids = set()
    if call and call.get("id"):
        ids.add(call["id"])
    for p in partners:
        ids.add(p["id"])
        ids.update(x["id"] for x in p.get("evidence", {}).get("projects", []) if x.get("id"))
    return ids


def check_citations(text: str, allowed: set[str]) -> dict:
    """Keep only sentences whose citations all exist; report what was dropped and what cites nothing."""
    kept, dropped, uncited = [], [], []
    for block in text.split("\n"):
        if not block.strip() or block.lstrip().startswith("#"):
            kept.append(block)
            continue
        sentences = SENTENCE.split(block.strip())
        good = []
        for sentence in sentences:
            cited = CITATION.findall(sentence)
            unknown = [c for c in cited if c not in allowed]
            if unknown:
                dropped.append({"sentence": sentence, "unknown": unknown})
            else:
                if not cited:
                    uncited.append(sentence)
                good.append(sentence)
        if good:
            kept.append(" ".join(good))
    return {"text": "\n".join(kept).strip(), "citations": sorted({c for c in CITATION.findall(text) if c in allowed}),
            "dropped": dropped, "uncited": uncited}


def brief(call: dict | None, partners: list[dict], home: dict, data_class: str = "P") -> dict:
    """A consortium brief from the local model, citation-checked; always for a person to review."""
    lines = ["Call topic:"]
    if call:
        lines.append(f"- [{call['id']}] {call.get('identifier', '')}: {call.get('title', '')} ({call.get('call_title') or call.get('call', '')}; "
                     f"status {call.get('status', '')}; deadlines {', '.join(call.get('deadlines') or []) or 'n/a'})")
    else:
        lines.append("- (described by the user, no call record)")
    lines += ["", f"Home institution: {home.get('name', '')} ({home.get('country', '')})", "", "Candidate partners, best fit first:"]
    for p in partners:
        projects = "; ".join(f"[{x['id']}] {x.get('acronym') or x.get('title')}" + (f" ({x['role']})" if x.get("role") else "")
                             for x in p.get("evidence", {}).get("projects", [])[:4])
        lines.append(f"- [{p['id']}] {p['name']} ({p.get('country', '')}, {p.get('activity', '')}); fields: "
                     f"{'; '.join(p.get('fields', [])[:5]) or 'n/a'}; projects: {projects or 'n/a'}")
    prompt = "\n".join(lines)
    response = generate([{"role": "user", "content": prompt}], task="reasoning", data_class=data_class, system=BRIEF_SYSTEM)
    checked = check_citations(response.text, evidence_ids(call, partners))
    return {"brief": checked["text"], "model": response.model, "citations": checked["citations"], "dropped": checked["dropped"],
            "uncited": checked["uncited"], "needs_review": True,
            "review_reason": "a draft from the local model; the research office approves before any outreach"}
