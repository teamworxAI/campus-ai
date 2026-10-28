"""Gold sets: one JSONL format for both products (card P6). This docstring is the spec.

A gold set is a UTF-8 JSONL file, one case per line; blank lines are
ignored. Lines are split on "\\n" only, never `str.splitlines`, which also
cuts on U+2028 and other separators that may sit inside a JSON string.
Every case has:

- `id` (string, unique in the file)
- `source` (string): where the case and its labels come from
- `notes` (string, may be empty): who labelled it and anything a reader
  needs; a provisional set says so in its first case's notes

Retrieval case (Research Assistant: experts, partners, collections):

- `query` (string): the question as a user would type it
- `relevant` (non-empty list of node ids): every result a careful reader
  accepts as relevant; ranked results are scored against this set
- `search` (optional string): which search answers it, e.g. "experts" or
  "partners"
- `exclude` (optional list of node ids): candidates to leave out, e.g. the
  project a back-test query was taken from
- `language` (optional string): the query's language code

Course Access case (one labelled document):

- `document` (string): the document's path under `DATA_DIR/course_access`
- `expected` (object): the issue count a specialist expects per audit rule,
  e.g. {"image-alt": 3, "heading-order": 1}
- `issues` (optional list of objects): labelled issues, each with a `rule`
  (string) and optionally `page` (int), `block` (int) and `note` (string)

A case is one kind or the other: it has `query` or `document`, not both.
Unknown fields are rejected so a typo cannot pass silently.
"""

from __future__ import annotations

import json
from pathlib import Path

COMMON = {"id", "source", "notes"}
RETRIEVAL = COMMON | {"query", "relevant"}
RETRIEVAL_OPTIONAL = {"search", "exclude", "language"}
COURSE = COMMON | {"document", "expected"}
COURSE_OPTIONAL = {"issues"}
ISSUE_FIELDS = {"rule", "page", "block", "note"}


class GoldError(ValueError):
    """A gold set that does not follow the format; the message names the line."""


def _strings(value, allow_empty_list=False) -> bool:
    return (isinstance(value, list) and (allow_empty_list or bool(value))
            and all(isinstance(v, str) and v for v in value))


def validate(case) -> str:
    """The case's kind ("retrieval" or "course_access"); raises GoldError if it breaks the format."""
    if not isinstance(case, dict):
        raise GoldError("a case must be a JSON object")
    if ("query" in case) == ("document" in case):
        raise GoldError("a case needs exactly one of 'query' (retrieval) or 'document' (Course Access)")
    kind, required, optional = (("retrieval", RETRIEVAL, RETRIEVAL_OPTIONAL) if "query" in case
                                else ("course_access", COURSE, COURSE_OPTIONAL))
    missing = sorted(required - case.keys())
    if missing:
        raise GoldError(f"missing field(s): {', '.join(missing)}")
    unknown = sorted(case.keys() - required - optional)
    if unknown:
        raise GoldError(f"unknown field(s): {', '.join(unknown)}")
    for field in ("id", "source"):
        if not isinstance(case[field], str) or not case[field].strip():
            raise GoldError(f"'{field}' must be a non-empty string")
    if not isinstance(case["notes"], str):
        raise GoldError("'notes' must be a string")
    if kind == "retrieval":
        if not isinstance(case["query"], str) or not case["query"].strip():
            raise GoldError("'query' must be a non-empty string")
        if not _strings(case["relevant"]):
            raise GoldError("'relevant' must be a non-empty list of node ids")
        if "exclude" in case and not _strings(case["exclude"], allow_empty_list=True):
            raise GoldError("'exclude' must be a list of node ids")
        for field in ("search", "language"):
            if field in case and (not isinstance(case[field], str) or not case[field]):
                raise GoldError(f"'{field}' must be a non-empty string")
        return kind
    if not isinstance(case["document"], str) or not case["document"].strip():
        raise GoldError("'document' must be a non-empty path")
    expected = case["expected"]
    if not isinstance(expected, dict) or not all(
            isinstance(r, str) and r and type(n) is int and n >= 0 for r, n in expected.items()):
        raise GoldError("'expected' must map rule names to counts (integers >= 0)")
    issues = case.get("issues", [])
    if not isinstance(issues, list):
        raise GoldError("'issues' must be a list")
    for issue in issues:
        if not isinstance(issue, dict) or not isinstance(issue.get("rule"), str) or not issue["rule"] \
                or set(issue) - ISSUE_FIELDS:
            raise GoldError(f"each labelled issue needs a 'rule' and only the fields {sorted(ISSUE_FIELDS)}")
    return kind


def parse(text: str, kind: str | None = None) -> list[dict]:
    """The cases in a gold set's text; `kind` ("retrieval" or "course_access") requires every case to be that kind."""
    cases, seen = [], set()
    for number, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
            found = validate(case)
        except json.JSONDecodeError as exc:
            raise GoldError(f"line {number}: not JSON ({exc.msg})") from None
        except GoldError as exc:
            raise GoldError(f"line {number}: {exc}") from None
        if kind and found != kind:
            raise GoldError(f"line {number}: a {found} case in a {kind} gold set")
        if case["id"] in seen:
            raise GoldError(f"line {number}: duplicate id {case['id']!r}")
        seen.add(case["id"])
        cases.append(case)
    return cases


def load(path: str | Path, kind: str | None = None) -> list[dict]:
    """The validated cases of the gold set at `path` (see the module docstring for the format)."""
    try:
        return parse(Path(path).read_text(encoding="utf-8"), kind)
    except GoldError as exc:
        raise GoldError(f"{path}: {exc}") from None
