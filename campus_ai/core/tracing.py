"""Per-run JSONL trace of model and tool calls (card P2).

Each run writes one file, `<CAMPUS_AI_TRACE_DIR>/<run id>.jsonl` (default
`./traces`), one JSON object per call: time, run, event, and metadata such as
tool, task, model, host, data class, tokens, latency and outcome.

Records hold metadata only, never inputs or outputs, so no raw content (and
no restricted content) can reach a trace: `record` refuses any other field,
and errors are logged by exception type, not message.
"""

import contextvars
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from campus_ai.core.data_classes import RestrictedDataError

FIELDS = (
    "tool", "task", "model", "host", "data_class",
    "input_tokens", "output_tokens", "latency_ms", "outcome", "error",
)


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


_run = contextvars.ContextVar("campus_ai_trace_run", default=None)
_process_run = f"{_stamp()}-{os.getpid()}"
_lock = threading.Lock()


def trace_dir() -> Path:
    return Path(os.environ.get("CAMPUS_AI_TRACE_DIR") or "traces")


def run_id() -> str:
    """The current run: the innermost `run()` block, else one per process."""
    return _run.get() or _process_run


@contextmanager
def run(name: str):
    """Trace everything inside this block to its own run file; yields the run id."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "run"
    token = _run.set(f"{_stamp()}-{safe}-{secrets.token_hex(3)}")
    try:
        yield _run.get()
    finally:
        _run.reset(token)


def record(event: str, **fields) -> dict:
    """Append one record to the current run's file and return it."""
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"Trace fields must be metadata only; not allowed: {sorted(unknown)}")
    entry = {"time": datetime.now(timezone.utc).isoformat(), "run": run_id(), "event": event, **fields}
    path = trace_dir() / f"{entry['run']}.jsonl"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry) + "\n")
    return entry


@contextmanager
def span(event: str, **fields):
    """Time the block and record it once, with outcome ok, refused (class R) or error.

    Yields the fields dict, so the block can add model and token counts.
    """
    start = time.perf_counter()
    try:
        yield fields
    except Exception as error:
        outcome = "refused" if isinstance(error, RestrictedDataError) else "error"
        fields.update(outcome=outcome, error=type(error).__name__)
        raise
    else:
        fields.setdefault("outcome", "ok")
    finally:
        fields["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        record(event, **fields)
