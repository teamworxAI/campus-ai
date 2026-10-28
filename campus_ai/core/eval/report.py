"""One Markdown report writer for every eval script (card P6).

A report is a title, a first paragraph that starts with the UTC time (and
the commit, embedder and model when known), metric bullets, then sections
(each optionally headed, holding lines such as a `table`). `save` prints it
and writes `<name>_<YYYYMMDD>.md` next to the eval script, so the dated
history in `evals/` stays comparable.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path


def git_sha(where: str | Path = ".") -> str | None:
    """The short commit of the code under test: `GIT_SHA` if set, else `git rev-parse`, else None."""
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"][:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=where, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):  # no git in the container
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def table(headers: Sequence[str], rows: Iterable[Sequence]) -> list[str]:
    """A Markdown table as lines."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def render(title: str, summary: str = "", *, when: datetime | None = None, bullets: Iterable[str] = (),
           sections: Iterable[tuple[str | None, Sequence[str]]] = (), model: str | None = None,
           embedder: str | None = None, sha: str | None = None) -> str:
    """The report text. `sections` are (heading or None, lines) in order."""
    when = when or datetime.now(timezone.utc)
    run = [f"commit {sha}"] if sha else []
    run += [f"embedder {embedder}"] if embedder else []
    run += [f"model {model}"] if model else []
    first = f"{when:%Y-%m-%d %H:%M} UTC" + (f" ({', '.join(run)})" if run else "") + "."
    lines = [f"# {title}", "", f"{first} {summary}".rstrip(), ""]
    bullets = list(bullets)
    if bullets:
        lines += [f"- {b}" for b in bullets] + [""]
    for heading, body in sections:
        if heading:
            lines += [f"## {heading}", ""]
        lines += list(body) + [""]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def save(text: str, name: str, here: str | Path, when: datetime | None = None) -> Path:
    """Print the report, write it as `<name>_<YYYYMMDD>.md` in `here` (the script's folder) and return the path."""
    when = when or datetime.now(timezone.utc)
    out = Path(here) / f"{name}_{when:%Y%m%d}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    try:
        shown = out.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        shown = out
    print(f"Report: {shown.as_posix()}")
    return out
