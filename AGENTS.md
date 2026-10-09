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
Everything runs in Docker so any machine can rebuild it: no host virtualenvs
or host-installed models. Dependencies are managed with `uv` inside the image
(`pyproject.toml` + `uv.lock`).

```bash
docker compose build                  # test image + embed image (local models)
docker compose run --rm test          # unit tests
docker compose run --rm embed python scripts/embed_bakeoff.py evals/embed/sample_bakeoff.jsonl
```

To change dependencies, run `uv add` / `uv lock` in a container, e.g.
`docker run --rm -v "$PWD":/app -w /app python:3.13-slim sh -c "pip install uv && uv lock"`.
Model weights download into the `hf-cache` Docker volume on first use. In
Claude Code cloud sessions add `-f compose.yaml -f .claude/compose.cloud.yaml`.

Copy `.env.example` to `.env` for local secrets (compose reads it). Never
commit `.env`, model binaries, caches or customer data.

## Rules
- Keep the codebase simple: add complexity only when strictly necessary.
- Deterministic code for anything checkable; LLM calls only for judgement.
- Every agent output cites its evidence; nothing is sent or published
  without human approval.
- Data stays in its region (Canada or EU). Route through the LLM router,
  never call a model provider directly from product code.
- Tests use `unittest`; mock LLMs, Neo4j and network calls.
- New services, tools and models ship as Docker images or compose services,
  pinned and rebuildable from the repo alone.
- Every PR that touches a product reports its eval results.

## Commits and PRs
Short imperative subjects. One task card per PR. PRs list validation done
and call out new `.env` keys, migrations or data updates.
