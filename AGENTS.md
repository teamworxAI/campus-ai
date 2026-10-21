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
Everything runs in Docker so any machine can rebuild it: no host virtualenvs.
Dependencies are managed with `uv` inside the image (`pyproject.toml` +
`uv.lock`).

Models are fully local. Weights live in a host directory (`MODELS_DIR`,
default `./models`, shareable across projects) mounted read-only into the
`embed` service. That service sits on an internal Docker network that
reaches only Neo4j (the graph store), never the internet. Only
`fetch-models` touches the network, once, to fill that directory; you can
also copy weights in from another machine.

```bash
docker compose build                       # test image + embed image
docker compose run --rm test               # unit tests
docker compose run --rm fetch-models       # one-time: weights into MODELS_DIR
docker compose run --rm embed              # bake-off on local models, offline
docker compose run --rm embed python scripts/graph_search.py index evals/embed/sample_bakeoff.jsonl
docker compose run --rm embed python scripts/graph_search.py search "ocean warming"
docker compose run --rm fetch-europeana --rows 300   # needs EUROPEANA_API_KEY
docker compose run --rm embed python scripts/graph_search.py index data/europeana/salmon/items.jsonl
```

Harvested collections go in `DATA_DIR` (default `data/`, mounted read-only
into `embed` and `api`, never committed). `MODELS_DIR`, `DATA_DIR` and
`NEO4J_DATA` can point at another drive; see the build guide.

`embed` starts Neo4j on first use; its data persists in the `neo4j-data`
volume (`docker compose down -v` wipes it).

On machines with an NVIDIA GPU, add `compose.gpu.yaml` (e.g. set
`COMPOSE_FILE` in `.env`, see `.env.example`); models then run in bfloat16.

To change dependencies, run `uv add` / `uv lock` in a container, e.g.
`docker run --rm -v "$PWD":/app -w /app python:3.13-slim sh -c "pip install uv && uv lock"`.
In Claude Code cloud sessions add `-f compose.yaml -f .claude/compose.cloud.yaml`.

Copy `.env.example` to `.env` for local settings (compose reads it). Never
commit `.env`, model weights, caches or customer data.

## Rules
- Keep the codebase simple: add complexity only when strictly necessary.
- Deterministic code for anything checkable; LLM calls only for judgement.
- Every agent output cites its evidence; nothing is sent or published
  without human approval.
- Ingest only sources we have permission for. ArcaBC (arcabc.ca) is off limits
  until BC ELN agrees (task card R0b): no fetching, scraping or indexing.
- Data stays in its region (Canada or EU). Route through the LLM router,
  never call a model provider directly from product code.
- Tests use `unittest`; mock LLMs, Neo4j and network calls.
- New services, tools and models ship as Docker images or compose services,
  pinned and rebuildable from the repo alone. Models run offline from local
  weights; nothing downloads at runtime.
- Every PR that touches a product reports its eval results.

## Commits and PRs
Short imperative subjects. One task card per PR. PRs list validation done
and call out new `.env` keys, migrations or data updates.
