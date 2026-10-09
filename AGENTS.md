# Repository Guidelines

## Plan
`docs/plans/master_plan.md` is the source of truth for scope, architecture,
task cards and open decisions. Read it before starting a task card, and
update it in the same PR when a decision changes.

## Structure
- `campus_ai/core/`: shared modules (LLM router, graph, eval, tracing,
  review UI, region config).
- `campus_ai/course_access/`, `campus_ai/research_assistant/`: one package per
  product.
- `evals/`: gold sets and eval reports. `tests/`: unit tests.

## Development
App code runs in Docker so any machine can rebuild it: no host virtualenvs.
Dependencies are managed with `uv` inside the image (`pyproject.toml` +
`uv.lock`).

Models run on the host ("on metal"), served by vLLM or Ollama and shared with
other projects. App containers call them over HTTP (OpenAI-compatible API);
never bake model weights into an image or load them in-process.

```bash
docker compose build
docker compose run --rm app           # unit tests
docker compose run --rm app python scripts/embed_bakeoff.py evals/embed/sample_bakeoff.jsonl
```

`EMBED_BASE_URL` selects the embeddings server (default: Ollama on the host,
`http://host.docker.internal:11434/v1`; on Linux, start Ollama with
`OLLAMA_HOST=0.0.0.0` so containers can reach it). Serve models under the
names in `campus_ai/core/embed/embedder.py`, e.g.
`ollama pull embeddinggemma-2`, or
`vllm serve google/embeddinggemma-2 --runner pooling --served-model-name embeddinggemma-2`.

To change dependencies, run `uv add` / `uv lock` in a container, e.g.
`docker run --rm -v "$PWD":/app -w /app python:3.13-slim sh -c "pip install uv && uv lock"`.
In Claude Code cloud sessions add `-f compose.yaml -f .claude/compose.cloud.yaml`.

Copy `.env.example` to `.env` for local settings (compose reads it). Never
commit `.env`, model binaries, caches or customer data.

## Rules
- Keep the codebase simple: add complexity only when strictly necessary.
- Deterministic code for anything checkable; LLM calls only for judgement.
- Every agent output cites its evidence; nothing is sent or published
  without human approval.
- Data stays in its region (Canada or EU). Route through the LLM router,
  never call a model provider directly from product code.
- Tests use `unittest`; mock LLMs, Neo4j and network calls.
- New services and tools ship as Docker images or compose services, pinned
  and rebuildable from the repo alone. Models are the exception: they are
  served on the host and reached by URL.
- Every PR that touches a product reports its eval results.

## Commits and PRs
Short imperative subjects. One task card per PR. PRs list validation done
and call out new `.env` keys, migrations or data updates.
