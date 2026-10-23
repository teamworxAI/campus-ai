"""Call analyst (R4): what a Horizon Europe topic asks for, from its full text, every item quoted.

`analyse(call)` takes a CallTopic as `ResearchSearch.call` returns it (its
text holds the "Expected outcome:" and "Scope:" sections when the topic page
was fetched) and returns:
- the deterministic part, from the funding records: action type and the
  consortium rule it implies (the R5 rule in `consortium.eligibility`),
  whether a Canadian partner counts, deadlines, budget, cluster, keywords and
  the topic-specific conditions;
- the judgement part, from the local model (router task "reasoning"): the
  research topics, the expected outcomes and the partner profile (the kinds
  of organisation the call needs), each item with the span of the topic text
  it rests on.
A span check in code keeps an item only if its quoted span occurs in the
topic text (after whitespace normalisation); the rest are dropped and
counted, as `consortium.check_citations` does for the brief. A model that is
down or answers with something other than JSON leaves the deterministic part
standing, with `model_error` set; nothing here raises into the API.

`partner_query(analysis)` is the text partner search runs on: the topics and
the partner profile, so the shortlist follows what the call asks for rather
than its title.
"""

from __future__ import annotations

import json
import re
import time

from campus_ai.core.llm import generate
from campus_ai.research_assistant.consortium import eligibility

FIELDS = ("topics", "expected_outcomes", "partner_profile")
LIMITS = {"topics": 8, "expected_outcomes": 8, "partner_profile": 8}
MIN_SPAN = 8  # characters: a shorter quote proves nothing
QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})

SYSTEM = """You analyse a Horizon Europe call topic for a university research office. Read the topic text and answer with one JSON object only, no prose, no Markdown:
{"topics": [{"text": "...", "span": "..."}],
 "expected_outcomes": [{"text": "...", "span": "..."}],
 "partner_profile": [{"text": "...", "span": "..."}]}
- topics: 3 to 8 short phrases (2-6 words) in your own words naming the research and innovation subjects of the Expected outcome and Scope sections (not a copy of the keyword list).
- expected_outcomes: the outcomes the call expects, one per item, quoted or closely paraphrased from the text.
- partner_profile: the kinds of organisation or expertise a consortium for this call needs, e.g. "clinical partner", "SME for exploitation", "public authority as end user", "social sciences and humanities expertise".
- Every item, in every list, is an object with "text" and "span", never a bare string. span: copy word for word the passage of the topic text (at least a few words, at most one sentence) that supports the item. Never write a span that is not in the text; leave the item out instead.
Example item for a text saying "Proposals should involve hospitals and patient organisations in the pilots.":
{"text": "clinical partner", "span": "Proposals should involve hospitals and patient organisations in the pilots"}"""


def normalise(text: str) -> str:
    return " ".join((text or "").translate(QUOTES).split()).casefold()


def facts(call: dict) -> dict:
    """The deterministic part: everything that is read from the funding records rather than judged."""
    actions = call.get("actions") or []
    action = actions[0] if actions else (call.get("action_type") or "").split(" ")[0]
    parts = call.get("parts") or []
    pillar_ii = any(str(p).startswith("HORIZON.2") for p in parts)
    canada = ("associated country: a Canadian partner counts towards the consortium rule (Pillar II)" if pillar_ii
              else "third country: a Canadian partner can join but does not count towards the rule and may need its own funding")
    return {
        "id": call.get("id"), "identifier": call.get("identifier") or "", "title": call.get("title") or "",
        "call": call.get("call_title") or call.get("call") or "", "status": call.get("status") or "", "url": call.get("url") or "",
        "opening": call.get("opening") or "", "deadlines": call.get("deadlines") or [],
        "action": action, "action_type": call.get("action_type") or action,
        "consortium_rule": eligibility([], action, parts)["rule"],
        "rule_source": "Horizon Europe General Annexes, section B; the call's own conditions override it", "canada": canada,
        "budget": call.get("budget") or None, "expected_grants": call.get("expected_grants") or None,
        "clusters": [c for c in call.get("clusters") or [] if c], "parts": parts,
        "keywords": call.get("keywords") or [], "conditions": call.get("conditions") or "",
        "described": bool(call.get("expected_outcome") or call.get("scope")),
    }


def topic_text(call: dict) -> str:
    """The text the model reads and every span is checked against."""
    return call.get("text") or f"{call.get('identifier', '')}: {call.get('title', '')}"


def parse(answer: str) -> dict | None:
    """The JSON object in a model answer (code fences and stray prose around it tolerated), or None."""
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(answer[start:end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def check_spans(answer: dict, text: str) -> tuple[dict, list[dict]]:
    """Keep the items whose span occurs in `text`; return them by field and the dropped ones."""
    haystack = normalise(text)
    kept: dict[str, list] = {field: [] for field in FIELDS}
    dropped = []
    for field in FIELDS:
        items = answer.get(field) or []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, str):
                item = {"text": item, "span": ""}
            if not isinstance(item, dict):
                continue
            label = " ".join(str(item.get("text") or "").split())
            span = " ".join(str(item.get("span") or "").split()).strip("\"'.…,;:“”‘’ ")
            if label and len(span) >= MIN_SPAN and normalise(span) in haystack:
                if len(kept[field]) < LIMITS[field]:
                    kept[field].append({"text": label, "span": span})
            else:
                dropped.append({"field": field, "text": label, "span": span})
    return kept, dropped


def analyse(call: dict, data_class: str = "P") -> dict:
    """The call analysis: deterministic facts plus span-checked topics, outcomes and partner profile from the local model."""
    result = {**facts(call), **{field: [] for field in FIELDS}, "analysed_by": None, "dropped": 0, "dropped_items": [],
              "evidence": {"id": call.get("id"), "url": call.get("url") or ""}, "needs_review": True}
    text = topic_text(call)
    prompt = f"Topic text:\n{text}\n\nAnswer with the JSON object only."
    started = time.monotonic()
    try:
        response = generate([{"role": "user", "content": prompt}], task="reasoning", data_class=data_class, system=SYSTEM)
    except Exception as error:  # the model being down leaves the facts standing
        result["model_error"] = f"{type(error).__name__}: {str(error)[:200]}"
        return result
    result["seconds"] = round(time.monotonic() - started, 1)
    result["analysed_by"] = response.model
    answer = parse(response.text)
    if answer is None:
        result["model_error"] = "the model's answer was not a JSON object: " + " ".join(response.text.split())[:200]
        return result
    kept, dropped = check_spans(answer, text)
    result.update(kept, dropped=len(dropped), dropped_items=dropped)
    return result


def partner_query(analysis: dict) -> str:
    """The text partner search runs on: the call's topics and the partner profile, falling back to its title."""
    phrases = [item["text"] for field in ("topics", "partner_profile") for item in analysis.get(field) or [] if item.get("text")]
    if not phrases:
        return analysis.get("title") or analysis.get("identifier") or ""
    return "; ".join(dict.fromkeys(phrases))
