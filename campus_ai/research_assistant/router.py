"""Journey router (R4): one question in, one of the five journeys out (plan 4.1, 4.3).

    1 partners for a call       2 calls for a researcher or lab    3 draft a consortium
    4 an expert or supervisor   5 sources in the collections

`route(text)` tries rules first, in a fixed order; the first that fires
decides, and `why` names it. Only when no rule fires does the local model
(router task "classification") choose, with a strict one-digit answer; on
any failure (model down, slower than `MODEL_SECONDS`, an answer that is not
one digit from 1 to 5) the
default journey, expert search, is kept and `why` says so. `answer(text,
research, collections)` routes and runs the matching search, returning the
same shapes as the existing endpoints.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from campus_ai.core.llm import generate

JOURNEYS = {1: "partners for a call", 2: "calls for a researcher or lab", 3: "draft a consortium",
            4: "an expert or supervisor", 5: "sources in the collections"}
DEFAULT = 4  # plain-language expert search is the general case (plan 4.1)
MODEL_SECONDS = 90  # how long the model may take to pick a journey before the default is used
TOPIC_ID = re.compile(r"\bHORIZON-[A-Z0-9][A-Z0-9-]*[A-Z0-9]\b", re.IGNORECASE)

# (journey, rule name, pattern), tried in order: a consortium request names a call and partners too, so it goes first.
RULES = [
    (3, "consortium or brief", re.compile(r"\b(consortium|consortia|brief)\b", re.I)),
    (1, "Horizon topic identifier", TOPIC_ID),
    (1, "call and partner", re.compile(r"(?=.*\bcalls?\b)(?=.*\bpartner)", re.I | re.S)),
    (2, "which calls or funding", re.compile(r"\b(which|what|any|open)\s+(\w+\s+)?calls?\b|\bfunding\b|\bgrants?\b|\bcalls? for\b", re.I)),
    (4, "expert, supervisor or who works on", re.compile(r"\bwho\b.*\b(works?|working|research(es|ing)?|studies|studying)\b|"
                                                           r"\b(experts?|expertise|supervisors?|professors?|faculty)\b", re.I | re.S)),
    (5, "sources, images or collections", re.compile(r"\b(sources?|images?|pictures?|photos?|photographs?|archives?|archival|"
                                                      r"collections?|historical|museum|manuscripts?)\b", re.I)),
]

SYSTEM = """You route a request to a university research assistant. Journeys:
1 = find EU partner organisations for a Horizon Europe call or project idea
2 = find open funding calls that fit a researcher, lab or research topic
3 = draft a consortium or a proposal brief for a call
4 = find an SFU expert, researcher or graduate supervisor for a topic
5 = find sources, images, archives or documents in library and museum collections
Answer with one digit from 1 to 5 and nothing else."""

# Lead-ins that say which journey but are not what to search for.
LEAD = re.compile(r"^\s*(please\s+)?((can|could) you\s+)?(find|show( me)?|search( for)?|look for|i need|i want|we need|get|list|give me)?\s*"
                  r"(me\s+)?((some|any|the|an?)\s+)?", re.I)


def classify(text: str, data_class: str = "I") -> tuple[int | None, str]:
    """The local model's journey for `text`, or None with the reason it could not be used.

    The model gets `MODEL_SECONDS`; a busy laptop GPU can take ten minutes, and a router that slow is no router.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(generate, [{"role": "user", "content": f"Request: {text}\nJourney:"}], task="classification",
                         data_class=data_class, system=SYSTEM)
    pool.shutdown(wait=False)  # a late answer is dropped, not waited for
    try:
        response = future.result(timeout=MODEL_SECONDS)
    except FutureTimeout:
        return None, f"model took over {MODEL_SECONDS} s"
    except Exception as error:  # the model being down is a fallback, not a failure
        return None, f"model unavailable ({type(error).__name__})"
    answer = response.text.strip().strip(".*`\"' ")
    if re.fullmatch(r"[1-5]", answer):
        return int(answer), f"model {response.model}"
    return None, f"model answer not a journey: {' '.join(response.text.split())[:40]!r}"


def route(text: str) -> dict:
    """{"journey": 1-5, "name", "query", "why", "seconds"}: rules first, then the local model, then the default."""
    started = time.monotonic()
    text = " ".join((text or "").split())
    for journey, name, pattern in RULES:
        if pattern.search(text):
            why = f"rule: {name}"
            break
    else:
        journey, why = classify(text)
        if journey is None:
            journey, why = DEFAULT, f"no rule fired; {why}; default journey {DEFAULT}"
        else:
            why = f"no rule fired; {why}"
    found = TOPIC_ID.search(text)
    query = found.group(0) if journey in (1, 3) and found else (LEAD.sub("", text).rstrip("?. ") or text)
    return {"journey": journey, "name": JOURNEYS[journey], "query": query, "why": why,
            "seconds": round(time.monotonic() - started, 2)}


def call_for(research: Any, identifier: str) -> dict | None:
    """A CallTopic by its Horizon identifier, as written or in capitals (suffixes such as "-two-stage" are lower case)."""
    return research.call(f"topic:{identifier}") or research.call(f"topic:{identifier.upper()}")


def answer(text: str, research: Any, collections: Any = None, k: int = 10, routed: dict | None = None) -> dict:
    """Route `text` (unless `routed` is given) and run the journey's search; results in the shapes of /api/partners,
    /api/calls, /api/experts and /api/search."""
    routed = routed or route(text)
    journey, query = routed["journey"], routed["query"]
    out: dict = {**routed, "question": text}
    call = call_for(research, query) if TOPIC_ID.fullmatch(query) else None
    if call:
        out["call"] = {key: call.get(key) for key in ("id", "identifier", "title", "call_title", "status", "deadlines", "url")}
        query = f"{call['title']}. {call.get('call_title') or ''}".strip()
    elif TOPIC_ID.fullmatch(query):  # an identifier the graph does not hold: search on the words around it
        query = text
    if journey in (1, 3):  # a consortium starts from the same shortlist; the brief itself is drafted on its own page
        out["partners"] = research.partners(query, k)
    elif journey == 2:
        out["calls"] = research.calls(query, k)
    elif journey == 4:
        out["experts"] = research.experts(query, k)
    elif collections is not None:
        out["pictures"] = [c.public() for c in collections.pictures(query, k)]
        out["texts"] = [c.public() for c in collections.texts(query, max(4, k // 2))]
    out["search"] = query
    return out
