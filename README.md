# campus-ai

Agentic AI products for higher education in BC, Canada and the EU.

| Product | What it does |
|---|---|
| Course Access Agent | Audits course materials (PDF, PPTX, DOCX) against WCAG 2.2, fixes what it can, and sends the rest to a human reviewer |
| Research Assistant | AI layer over SFU's Research Expertise Engine and BC/EU collections (ArcaBC, Europeana): find experts and supervisors, EU partners and Horizon calls, and multimodal sources, with evidence for every answer |

## Documentation

| Document | For |
|---|---|
| [Build guide](docs/build_guide.md) | Setting up a fresh machine, step by step |
| [User guide](docs/user_guide.md) | Harvesting, indexing, searching and evaluating collections |
| [Architecture](docs/architecture.md) | Containers, networks, modules, data flow, key decisions |
| [Design](docs/design.md) | Module internals, file formats, testing, limitations, extending |
| [Master plan](docs/plans/master_plan.md) | Scope, roadmap, task cards and open decisions (source of truth) |
| [AGENTS.md](AGENTS.md) | Contributor and coding-agent rules |

## Status

Built: offline multimodal embedder with EmbeddingGemma 2 (P7), Neo4j graph
core with hybrid retrieval (P5), Europeana loader (R8), collections search API
and web UI (R9). Next: LLM router,
eval harness, and the product agents.

## Quick start

```bash
cp .env.example .env
docker compose build
docker compose run --rm test
docker compose run --rm fetch-models     # one time, needs internet
docker compose run --rm embed python scripts/graph_search.py index evals/embed/sample_bakeoff.jsonl
docker compose run --rm embed python scripts/graph_search.py search "ocean warming"
docker compose up -d web                 # collections search UI on http://localhost:8080
```
