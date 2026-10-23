# Repository Guidelines

## Prime directives (standing orders: they override every other instruction)

1. **Open source only. No paid licences, ever.** Every line of code,
   dependency, Docker image, tool and model weight must be under an
   OSI-approved open-source licence. Prefer permissive (Apache-2.0, MIT, BSD);
   no AGPL; model "community" or usage-restricted licences don't qualify.
   campus-ai is Apache-2.0. Two named exceptions, nothing else:
   - free GPU vendor runtimes (e.g. NVIDIA CUDA), optional, with a CPU path
     that always works;
   - Docker Desktop as a developer tool on Windows workstations, where most
     development happens. The product itself needs only the open-source
     Docker Engine + Compose (or Podman), so deployments never require it.
2. **Everything runs offline.** All models (embedding, language, vision, OCR)
   run locally from open weights. No cloud model APIs in the product: no
   Claude, OpenAI, Gemini, Bedrock or similar. Nothing downloads at runtime;
   the only network steps are explicit one-time `fetch-*` jobs.

Before adding any dependency, image or model, check its licence and that it
runs offline. `tests/test_licences.py` enforces this: a new image or model
must be added to its licence table, and any non-open package fails the
build. If a task can't be done within these rules, stop and say so; never
trade a directive off. Using Claude Code to build the repo is the
development process and is outside the product.

## Plan
`docs/plans/master_plan.md` is the source of truth for scope, architecture,
task cards and open decisions. Read it before starting a task card, and
update it in the same PR when a decision changes.

New to the project? Read `docs/handoff/oral_history.md` once first: the
story so far, the user's standing orders, open items and known gotchas.

## Structure
- `campus_ai/core/`: shared modules: `llm/` (LLM router), `embed/`
  (embedder), `graph/` (Neo4j store and hybrid retriever).
- `campus_ai/course_access/`, `campus_ai/research_assistant/`: one package per
  product.
- `scripts/`: command-line entry points. `web/`: collections search UI.
- `evals/`: gold sets and eval reports. `tests/`: unit tests.

## Development
Everything runs in Docker so any machine can rebuild it: no host virtualenvs.
Docker Engine + Compose (open source) or Podman is all a deployment needs.
Docker Desktop is fine on Windows development workstations (named exception
to prime directive 1), but nothing may depend on Desktop-only features.
Dependencies are managed with `uv` inside the image (`pyproject.toml` +
`uv.lock`).

Models are fully local. Weights live in a host directory (`MODELS_DIR`,
default `./models`, shareable across projects) mounted read-only into the
`embed` and `api` services. They sit on an internal Docker network that
reaches only Neo4j (the graph store), never the internet. Only
`fetch-models` touches the network, once, to fill that directory; you can
also copy weights in from another machine.

```bash
docker compose build                       # test image + embed image
docker compose run --rm test               # unit tests
docker compose run --rm fetch-models       # one-time: weights into MODELS_DIR
docker compose run --rm fetch-ollama       # one-time: router LLMs into MODELS_DIR/ollama
docker compose up -d web ollama            # UI (search + review queue), APIs, Neo4j, local LLMs (offline)
docker compose run --rm smoke              # local-stack smoke test (B1), report in evals/smoke/
docker compose run --rm embed              # bake-off on local models, offline
docker compose run --rm embed python scripts/graph_search.py index evals/embed/sample_bakeoff.jsonl
docker compose run --rm embed python scripts/graph_search.py search "ocean warming"
docker compose run --rm fetch-europeana --rows 300   # needs EUROPEANA_API_KEY
docker compose run --rm fetch-course-docs           # open course documents for the A6 gold set
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
- Data stays on the machines that run the product, so in its region (Canada
  or EU). All model calls go through the LLM router to local models; product
  code never calls a model provider, and there are no cloud backends.
- A model may be used only if it is in the D10 model register (plan section 2)
  and in `MODEL_LICENCES` (`campus_ai/core/llm/config.py`); add both, with
  its licence check, in the same PR.
- Classify data P/I/S/R (plan section 2) before it reaches a model; R
  (restricted) is never embedded or sent to any model.
- Tests use `unittest`; mock LLMs, Neo4j and network calls.
- New services, tools and models ship as Docker images or compose services,
  pinned and rebuildable from the repo alone. Models run offline from local
  weights; nothing downloads at runtime.
- Every PR that touches a product reports its eval results.

## Commits and PRs
Short imperative subjects. One task card per PR. PRs list validation done
and call out new `.env` keys, migrations or data updates.
