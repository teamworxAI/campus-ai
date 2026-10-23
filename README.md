# campus-ai

Agentic AI products for higher education in BC, Canada and the EU.

| Product | What it does |
|---|---|
| Course Access Agent | Audits course materials (PDF, PPTX, DOCX) against WCAG 2.2, fixes what it can, and sends the rest to a human reviewer |
| Research Assistant | AI layer over SFU's Research Expertise Engine and BC/EU collections (ArcaBC, Europeana): find experts and supervisors, EU partners and Horizon calls, and multimodal sources, with evidence for every answer |

## Prime directives

1. **Open source only. No paid licences, ever.** Code, dependencies, images,
   tools and model weights are all under OSI-approved licences, permissive
   preferred, no AGPL; campus-ai itself is [Apache-2.0](LICENSE). Two named
   exceptions: free GPU vendor runtimes (optional) and Docker Desktop as a
   developer tool on Windows workstations.
2. **Everything runs offline.** All models run locally from open weights. No
   cloud model APIs; nothing downloads at runtime.

Details and scope: [AGENTS.md](AGENTS.md#prime-directives-standing-orders-they-override-every-other-instruction).

## Documentation

| Document | For |
|---|---|
| [Build guide](docs/build_guide.md) | Setting up a fresh machine, step by step |
| [User guide](docs/user_guide.md) | Harvesting, indexing, searching and evaluating collections |
| [Architecture](docs/architecture.md) | Containers, networks, modules, data flow, key decisions |
| [Design](docs/design.md) | Module internals, file formats, testing, limitations, extending |
| [Master plan](docs/plans/master_plan.md) | Scope, roadmap, task cards and open decisions (source of truth) |
| [AGENTS.md](AGENTS.md) | Contributor and coding-agent rules |
| [Handoff history](docs/handoff/oral_history.md) | The story so far, standing orders, open items, gotchas (read once when joining) |

## Status

Built: offline multimodal embedder with EmbeddingGemma 2 (P7), Neo4j graph
core with hybrid retrieval (P5), Europeana loader (R8), collections search API
and web UI (R9), all for the Research Assistant. Course Access Agent: the
document parser (A1), the WCAG audit and report (A2) and the alt-text worker
(A3, local vision model), the structure, table and text workers (A4) and the
rebuild and verify step (A5) are built, so a course document goes in and an
accessible DOCX and HTML, a report and a statement come out, every proposal
carrying a confidence and a review flag, and the review queue (P3) where a person
approves, edits or rejects each one before the rebuild (see
[architecture](docs/architecture.md#11-course-access-agent)).
Also built: LLM router over local open-weight models on Ollama (P1), the
data-class gate and tracing (P1b, P2), Ollama as an offline compose service
(P9), the local-stack smoke test (B1, passed on the demo laptop) and the
licence guard (P8). Next: the other model bake-offs (B2-B5), the eval harness
(P6) and the MCP server template (P4); OCR for scanned PDFs (A7) is next phase.

## Quick start

```bash
cp .env.example .env
docker compose build
docker compose run --rm test
docker compose run --rm fetch-models     # one time, needs internet
docker compose run --rm embed python scripts/graph_search.py index evals/embed/sample_bakeoff.jsonl
docker compose run --rm embed python scripts/graph_search.py search "ocean warming"
docker compose up -d web                 # collections search on http://localhost:8080, review queue on /review/
docker compose run --rm fetch-ollama     # one time, needs internet: local LLMs for the router
docker compose up -d ollama
docker compose run --rm smoke            # local-stack smoke test, report in evals/smoke/
```
