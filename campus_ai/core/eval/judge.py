"""A small local-model judge for what only judgement can score (card P6, decision D11).

Faithfulness of a text (a brief, an alt text) to its evidence, and alt-text
quality, each on a 1-5 scale with a one-line reason. Calls go through the LLM
router (local models only, data class checked) on the fast "classification"
task by default. The answer is parsed strictly: one JSON object
{"score": 1-5, "reason": "..."}, optionally in a code fence, and nothing
else. Anything that is not exactly that gives score None (with the answer's
length recorded), never an exception and never a score guessed from prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from campus_ai.core.llm import generate

ANSWER_FORMAT = ('Answer with one JSON object and nothing else: {"score": <integer 1-5>, "reason": "<one sentence>"}.')

FAITHFULNESS_SYSTEM = (
    "You check whether a text is supported by its evidence. Judge only against the evidence given, not "
    "against what you know. 5: every statement is supported by the evidence. 4: all main statements are "
    "supported, a minor detail is not. 3: some statements are unsupported. 2: most statements are unsupported. "
    "1: the text contradicts the evidence or has nothing to do with it. " + ANSWER_FORMAT)

ALT_TEXT_SYSTEM = (
    "You rate alt text for an image in a course document, following WCAG 2.2: it should convey the image's "
    "purpose and content in context, be concise, not start with 'image of', and give the data or point of a "
    "chart or diagram. 5: a screen-reader user loses nothing. 4: good, a small gap. 3: usable but vague or "
    "too long. 2: misses the point. 1: wrong or empty. " + ANSWER_FORMAT)

FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True)
class Verdict:
    score: int | None  # 1-5, None when the answer could not be parsed
    reason: str  # one line; "" when unparsable
    model: str
    raw_chars: int  # length of the model's answer, kept for unparsable ones


def parse(text: str) -> tuple[int | None, str]:
    """(score, reason) from a judge's answer, or (None, "") unless it is exactly the expected JSON."""
    body = text.strip()
    fenced = FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        answer = json.loads(body)
    except json.JSONDecodeError:
        return None, ""
    if not isinstance(answer, dict):
        return None, ""
    score, reason = answer.get("score"), answer.get("reason")
    if type(score) is not int or not 1 <= score <= 5 or not isinstance(reason, str):
        return None, ""
    return score, " ".join(reason.split())[:300]


def _ask(system: str, prompt: str, data_class: str, task: str) -> Verdict:
    response = generate([{"role": "user", "content": prompt}], task=task, data_class=data_class, system=system)
    score, reason = parse(response.text)
    return Verdict(score, reason, response.model, len(response.text))


def faithfulness(text: str, evidence: str, data_class: str, task: str = "classification") -> Verdict:
    """How well `text` is supported by `evidence` (1-5). `data_class` is the class of both (P/I/S)."""
    return _ask(FAITHFULNESS_SYSTEM, f"Evidence:\n{evidence}\n\nText to check:\n{text}", data_class, task)


def alt_text_quality(alt_text: str, context: str, data_class: str, task: str = "classification") -> Verdict:
    """Quality of `alt_text` (1-5) given what the image shows and the text around it (`context`)."""
    return _ask(ALT_TEXT_SYSTEM, f"What the image shows and the text around it:\n{context}\n\nAlt text:\n{alt_text}",
                data_class, task)
