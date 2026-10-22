"""Shared handling of model answers for the Course Access workers.

Workers ask the local model for one JSON object and treat it as data: the
object is found even inside prose or a code fence, missing fields are
missing, and the confidence is clamped to 0-1. Anything below
CONFIDENCE_THRESHOLD goes to human review.
"""

from __future__ import annotations

import json
import re

from campus_ai.core.llm import generate

CONFIDENCE_THRESHOLD = 0.7
JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_json(text: str) -> dict | None:
    """The JSON object in a model's answer, or None."""
    match = JSON_OBJECT.search(text)
    if not match:
        return None
    try:
        answer = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return answer if isinstance(answer, dict) else None


def confidence(value) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def ask(task: str, prompt: str, system: str, data_class: str) -> tuple[dict | None, str]:
    """One model call for a JSON answer: (the object or None, the model that answered)."""
    response = generate([{"role": "user", "content": prompt}], task=task, data_class=data_class, system=system)
    return parse_json(response.text), response.model
