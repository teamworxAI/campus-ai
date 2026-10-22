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

from campus_ai.course_access.parser import parse
from campus_ai.course_access.workers import ACTIONS, propose_fixes

HERE = Path(__file__).parent
SAMPLES_PER_ACTION = 3


def main() -> int:
    root = Path(os.environ.get("DATA_DIR", "data")) / "course_access"
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        print(f"No corpus at {root}: run `docker compose run --rm fetch-course-docs` first")
        return 1
    paths = sorted({json.loads(line)["path"] for line in manifest.read_text(encoding="utf-8").splitlines()})
    actions, reviewed, by_model, samples, rows = Counter(), Counter(), Counter(), defaultdict(list), []
    models = set()
    for path in paths:
        start = time.perf_counter()
        fixes = propose_fixes(parse(root / path), data_class="P")
        seconds = time.perf_counter() - start
        rows.append((path, len(fixes), sum(f.needs_review for f in fixes), sum(bool(f.model) for f in fixes), seconds))
        for f in fixes:
            actions[f.action] += 1
            reviewed[f.action] += f.needs_review
            by_model[f.action] += bool(f.model)
            models.update([f.model] if f.model else [])
            if len(samples[f.action]) < SAMPLES_PER_ACTION:
                value = json.dumps(f.value, ensure_ascii=False) if not isinstance(f.value, str) else f.value
                samples[f.action].append(f"{path.split('/')[-1]}: {value[:100]} (confidence {f.confidence:.2f}"
                                         f"{', review: ' + f.review_reason if f.needs_review else ''})")
    when = datetime.now(timezone.utc)
    total = sum(actions.values())
    lines = [f"# Worker proposals on the A6 corpus", "",
             f"{when:%Y-%m-%d %H:%M} UTC. {len(rows)} documents, {total} proposals, "
             f"{sum(reviewed.values())} to review, {sum(by_model.values())} from the model ({', '.join(sorted(models)) or 'none'}). "
             "Counts are what the rules produce; nothing is checked against labels yet.", "",
             "| Action | Meaning | Proposals | To review | From the model |", "|---|---|---|---|---|"]
    lines += [f"| {a} | {ACTIONS[a]} | {n} | {reviewed[a]} | {by_model[a]} |" for a, n in actions.most_common()]
    lines += ["", "| Document | Proposals | To review | From the model | Seconds |", "|---|---|---|---|---|"]
    lines += [f"| {p} | {n} | {r} | {m} | {s:.1f} |" for p, n, r, m, s in rows]
    lines += ["", "## Samples to read", ""]
    for action in actions:
        lines += [f"**{action}**", ""] + [f"- {s}" for s in samples[action]] + [""]
    report = "\n".join(lines)
    print(report)
    out = HERE / f"propose_corpus_{when:%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"\nReport: {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
