"""Run the structure, table and text workers (A4) over the A6 corpus and tabulate the proposals.

What the workers propose on real documents before gold labels exist: how
many fixes per action, how many go to review, how often the model was
needed, and a sample of each kind to read. Needs the `ollama` service for the
language and link-text questions. Writes a Markdown report next to this
script.

    docker compose run --rm test python evals/course_access/propose_corpus.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.eval import report
from campus_ai.course_access.parser import parse
from campus_ai.course_access.workers import ACTIONS, propose_fixes

HERE = Path(__file__).parent
SAMPLES_PER_ACTION = 3


def build_report(results: list[tuple], when: datetime, sha: str | None = None) -> str:
    """results: (path, proposed fixes, seconds) per document."""
    actions, reviewed, by_model, samples, rows = Counter(), Counter(), Counter(), defaultdict(list), []
    models = set()
    for path, fixes, seconds in results:
        rows.append((path, len(fixes), sum(f.needs_review for f in fixes), sum(bool(f.model) for f in fixes), f"{seconds:.1f}"))
        for f in fixes:
            actions[f.action] += 1
            reviewed[f.action] += f.needs_review
            by_model[f.action] += bool(f.model)
            models.update([f.model] if f.model else [])
            if len(samples[f.action]) < SAMPLES_PER_ACTION:
                value = json.dumps(f.value, ensure_ascii=False) if not isinstance(f.value, str) else f.value
                samples[f.action].append(f"{path.split('/')[-1]}: {value[:100]} (confidence {f.confidence:.2f}"
                                         f"{', review: ' + f.review_reason if f.needs_review else ''})")
    total = sum(actions.values())
    reading = []
    for action in actions:
        reading += [f"**{action}**", ""] + [f"- {s}" for s in samples[action]] + [""]
    return report.render(
        "Worker proposals on the A6 corpus",
        f"{len(rows)} documents, {total} proposals, {sum(reviewed.values())} to review, "
        f"{sum(by_model.values())} from the model ({', '.join(sorted(models)) or 'none'}). "
        "Counts are what the rules produce; nothing is checked against labels yet.",
        when=when, sha=sha, sections=[
            (None, report.table(["Action", "Meaning", "Proposals", "To review", "From the model"],
                                [(a, ACTIONS.get(a, ""), n, reviewed[a], by_model[a]) for a, n in actions.most_common()])),
            (None, report.table(["Document", "Proposals", "To review", "From the model", "Seconds"], rows)),
            ("Samples to read", reading)])


def main() -> int:
    root = Path(os.environ.get("DATA_DIR", "data")) / "course_access"
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        print(f"No corpus at {root}: run `docker compose run --rm fetch-course-docs` first")
        return 1
    paths = sorted({json.loads(line)["path"] for line in manifest.read_text(encoding="utf-8").split("\n") if line.strip()})
    results = []
    for path in paths:
        start = time.perf_counter()
        fixes = propose_fixes(parse(root / path), data_class="P")
        results.append((path, fixes, time.perf_counter() - start))
    when = datetime.now(timezone.utc)
    report.save(build_report(results, when, report.git_sha(HERE)), "propose_corpus", HERE, when)
    return 0


if __name__ == "__main__":
    sys.exit(main())
