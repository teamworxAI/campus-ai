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
Python 3.11+ with `uv`.

```bash
uv sync
uv run python -m unittest discover -s tests -v
```

Copy `.env.example` to `.env` for local secrets. Never commit `.env`,
model binaries, caches or customer data.

## Rules
- Keep the codebase simple: add complexity only when strictly necessary.
- Deterministic code for anything checkable; LLM calls only for judgement.
- Every agent output cites its evidence; nothing is sent or published
  without human approval.
- Data stays in its region (Canada or EU). Route through the LLM router,
  never call a model provider directly from product code.
- Tests use `unittest`; mock LLMs, Neo4j and network calls.
- Every PR that touches a product reports its eval results.

## Commits and PRs
Short imperative subjects. One task card per PR. PRs list validation done
and call out new `.env` keys, migrations or data updates.
