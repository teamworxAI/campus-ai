"""Local-stack smoke test (bake-off B1): is the whole stack up, offline, and fast enough?

Runs inside the internal `graph` network and checks that every service answers,
that the network has no route to the internet, that Ollama holds the router's
models, and that the LLM router answers a short prompt for each task. Writes a
report with timings to evals/smoke/ and exits non-zero if any check fails.

    docker compose up -d web ollama
    docker compose run --rm smoke --label demo-laptop
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.llm import config, generate

SERVICES = {
    "neo4j": "http://neo4j:7474",
    "api": "http://api:8000/api/health",
    "web": "http://web/",
}
# A public address that must be unreachable: the graph network is internal.
INTERNET = ("1.1.1.1", 443)
PROMPT = "Reply with the single word OK."
REPORTS = Path(__file__).resolve().parents[1] / "evals" / "smoke"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.load(resp)


def up(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return f"HTTP {resp.status} from {url}"


def timed(name: str, fn) -> dict:
    """Run `fn`; record whether it passed, how long it took and what it returned."""
    start = time.perf_counter()
    try:
        detail, ok = fn(), True
    except Exception as exc:  # any failure is a result, not a crash
        detail, ok = f"{type(exc).__name__}: {exc}", False
    return {"check": name, "ok": ok, "seconds": round(time.perf_counter() - start, 2), "detail": detail}


def offline() -> str:
    try:
        socket.create_connection(INTERNET, timeout=3).close()
    except OSError:
        return f"no route to {INTERNET[0]}"
    raise RuntimeError(f"reached {INTERNET[0]}:{INTERNET[1]}: the network is not offline")


def ollama_models() -> str:
    host = config.ollama_host()
    version = get_json(f"{host}/api/version").get("version", "?")
    have = {m["name"] for m in get_json(f"{host}/api/tags").get("models", [])}
    need = {config.model(task) for task in config.TASKS}
    missing = sorted(need - have)
    if missing:
        raise RuntimeError(f"not in Ollama, run fetch-ollama: {', '.join(missing)}")
    return f"Ollama {version} at {host}; has {', '.join(sorted(need))}"


def ask(task: str) -> str:
    reply = generate([{"role": "user", "content": PROMPT}], task, data_class="P")  # fixed public prompt
    return f"{reply.model}, {reply.output_tokens} tokens: {reply.text.strip()[:40]!r}"


def loaded() -> str:
    """Models Ollama has in memory, and how much of each sits in GPU memory."""
    models = get_json(f"{config.ollama_host()}/api/ps").get("models", [])
    gib = 1024**3
    return "; ".join(
        f"{m['name']} {m.get('size', 0) / gib:.1f} GiB, {m.get('size_vram', 0) / gib:.1f} GiB on GPU"
        for m in models
    ) or "none"


def run() -> list[dict]:
    results = [timed(name, lambda url=url: up(url)) for name, url in SERVICES.items()]
    results.append(timed("offline", offline))
    results.append(timed("ollama", ollama_models))
    results += [timed(f"router:{task}", lambda task=task: ask(task)) for task in config.TASKS]
    results.append(timed("loaded", loaded))
    return results


def report(results: list[dict], label: str, when: datetime) -> str:
    passed = sum(r["ok"] for r in results)
    lines = [
        f"# Local-stack smoke test (B1): {label}",
        "",
        f"{when:%Y-%m-%d %H:%M} UTC. {platform.machine()}, {os.cpu_count()} CPUs. "
        f"{passed}/{len(results)} checks passed. Router calls run in order, so the "
        "first call per model includes loading it.",
        "",
        "| Check | Result | Seconds | Detail |",
        "|---|---|---|---|",
    ]
    for r in results:
        detail = str(r["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['check']} | {'pass' if r['ok'] else 'FAIL'} | {r['seconds']} | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="local", help="machine name for the report, e.g. demo-laptop")
    args = parser.parse_args(argv)
    label = re.sub(r"[^\w.-]+", "-", args.label)

    when = datetime.now(timezone.utc)
    results = run()
    text = report(results, label, when)
    print(text)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{when:%Y%m%d-%H%M}-{label}.md"
    path.write_text(text, encoding="utf-8")
    print(f"Report: {path.relative_to(REPORTS.parents[1])}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
