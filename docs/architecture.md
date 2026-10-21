# Architecture

This document describes how campus-ai is put together: the runtime, the
modules, how data flows, and the decisions behind them. For the product scope
and roadmap see [`plans/master_plan.md`](plans/master_plan.md); for module
internals see [`design.md`](design.md).

**Status (October 2026).** Research Assistant: built the embedder (P7), the
graph core (P5), the Europeana loader (R8) and collections search with its
web UI (R9). Course Access Agent: the document parser (A1) is built on its own
branch; the rest is planned (section 11). Shared and still planned: eval
harness, tracing, review UI, MCP servers; the LLM router (P1) is on an
unmerged branch. Diagrams mark planned parts with dashed lines.

## 1. System context

campus-ai is two products on one shared core:

- **Course Access Agent**: makes course materials accessible (WCAG 2.2).
- **Research Assistant**: finds experts, EU partners, Horizon calls and
  sources across BC (ArcaBC) and EU (Europeana) collections.

```mermaid
flowchart LR
    subgraph users[People]
        R[Researchers, students, librarians]
        I[Instructors, accessibility staff]
        O[Research officers]
    end
    subgraph campus[campus-ai]
        RA[Research Assistant]
        CA[Course Access Agent]
        CORE[Shared core: embedder, graph, LLM router, eval]
    end
    subgraph sources[External sources, harvested once]
        EU[Europeana API]
        ARCA[ArcaBC arcabc.ca, BC ELN<br/>no access until R0b]
        REE[SFU REE, OpenAlex, CORDIS]
        HF[Hugging Face: model weights]
    end
    R --> RA
    O --> RA
    I --> CA
    RA --> CORE
    CA --> CORE
    EU -. fetch-europeana .-> campus
    HF -. fetch-models .-> campus
    ARCA -. planned: fetch-arcabc, blocked .-> campus
    REE -. planned .-> campus
```

Every external source is reached only by a dedicated **fetch** step that
writes to local disk. Everything that processes data afterwards runs offline.

**ArcaBC** (https://arcabc.ca) is BC ELN's collection site, the BC counterpart
of Europeana: one aggregated source, not many repositories. Its loader (R7)
will mirror the Europeana loader, a single `fetch-arcabc` step writing the same
JSONL records, so indexing, search and the UI need no changes for it. Until BC
ELN grants permission (R0b), nothing in this repo may fetch, scrape or index
arcabc.ca.

## 2. Principles that shape the architecture

| Principle | Consequence in the code |
|---|---|
| Portable: rebuilds from the repo on any machine | Everything runs in Docker Compose; dependencies are locked in `uv.lock`; images and Neo4j are pinned |
| Offline models | Weights live in a host directory (`MODELS_DIR`) mounted read-only; `HF_HUB_OFFLINE=1`; nothing downloads at runtime |
| Network isolation | Model containers sit on an `internal` Docker network that reaches only Neo4j |
| Fetch and process are separate | `fetch-models` and `fetch-europeana` are the only services with internet access; they write files, never the graph |
| Simple codebase | Small modules in `campus_ai/core/`; one JSONL format feeds the indexer from any source |
| Evidence for every answer | The retriever returns each hit with its linked nodes (collection, holder, creator) and every item keeps its rights statement and source URL |
| Data rights | Only openly licensed Europeana items are kept; harvested data is never committed or baked into images |

## 3. Runtime: containers and networks

```mermaid
flowchart TB
    HF[huggingface.co]
    API[api.europeana.eu]
    subgraph host[Host machine]
        MD[(MODELS_DIR<br/>model weights)]
        DD[(./data<br/>harvested collections)]
        ENV[.env<br/>keys and settings]
        subgraph internet_ok[Default network: internet access]
            FM[fetch-models<br/>image campus-ai:embed]
            FE[fetch-europeana<br/>image campus-ai:test]
        end
        subgraph graphnet["graph network (internal: no internet)"]
            EMB[embed<br/>image campus-ai:embed<br/>EmbeddingGemma 2]
            APIS[api<br/>image campus-ai:embed<br/>FastAPI + model]
            NEO[(neo4j<br/>2026.09.0-community)]
        end
        WEB[web<br/>nginx 1.30.6<br/>UI + proxy]
        TEST[test<br/>image campus-ai:test<br/>no network needed]
        VOL[(volume neo4j-data)]
    end
    HF --> FM
    API --> FE
    FM -- writes --> MD
    FE -- writes --> DD
    MD -- read-only --> EMB
    DD -- read-only --> EMB
    EMB -- bolt 7687 --> NEO
    APIS -- bolt 7687 --> NEO
    MD -- read-only --> APIS
    DD -- read-only --> APIS
    WEB -- "/api, /media" --> APIS
    NEO --- VOL
    ENV -. compose reads .-> FE
    ENV -. compose reads .-> NEO
    BR[Browser] -- "127.0.0.1:8080 (edge network)" --> WEB
```

| Service | Image | Network | Mounts | Purpose |
|---|---|---|---|---|
| `test` | `campus-ai:test` (base deps only) | default | none | Unit tests; models, Neo4j and HTTP are mocked |
| `embed` | `campus-ai:embed` (adds PyTorch, sentence-transformers, PyAV) | `graph` (internal) | `MODELS_DIR:/models:ro`, `./data:/app/data:ro` | Bake-off, indexing, search, eval |
| `neo4j` | `neo4j:2026.09.0-community` | `graph` (internal) | volume `neo4j-data` | Graph, vector and fulltext indexes |
| `fetch-models` | `campus-ai:embed` | default | `MODELS_DIR:/models` (rw) | One-time weight download (profile `fetch`) |
| `fetch-europeana` | `campus-ai:test` | default | `./data:/app/data` (rw) | Harvest Europeana items and thumbnails (profile `fetch`) |
| `api` | `campus-ai:embed` | `graph` (internal) | `MODELS_DIR:/models:ro`, `./data:/app/data:ro` | Collections search API (FastAPI, port 8000 inside the network only) |
| `web` | `nginx:1.30.6-alpine` | `graph` + `edge` | `web/static`, `web/nginx.conf` (ro) | Serves the UI and proxies `/api` and `/media` to `api`; the only published port, `127.0.0.1:${WEB_PORT:-8080}` |

`web` joins the ordinary `edge` network because a container on an internal
network can't publish a port. It runs only nginx, with no model, key or data,
so the services that hold them stay without internet access.

Overlay files:
- `compose.gpu.yaml` gives `embed` the host's NVIDIA GPUs (opt in per machine).
- `.claude/compose.cloud.yaml` routes builds and fetches through the TLS
  proxy of Claude Code cloud sessions. Use it only there.

Neo4j publishes no ports, so it is reachable only from containers on the
`graph` network. Use `docker compose exec neo4j cypher-shell` to inspect it.

## 4. Code structure

```text
campus_ai/
  core/
    embed/        Embedder interface, EmbeddingGemma 2 + e5 baseline, media decoding   (P7)
    graph/        GraphStore (writer + indexes), HybridRetriever, stop words            (P5)
  research_assistant/
    europeana.py  Europeana record -> graph records                                     (R8)
    collections.py  search service: cards, citations, similar pictures                  (R9)
    api.py        FastAPI app for collections search                                    (R9)
web/
  static/         UI: index.html, app.js, styles.css (no build step)                    (R9)
  nginx.conf      static files + proxy to api                                           (R9)
  course_access/  (planned)
scripts/
  fetch_models.py      download weights into MODELS_DIR
  embed_bakeoff.py     recall@k per embedder on a JSONL set (decision D7)
  graph_search.py      index / search / eval against Neo4j
  fetch_europeana.py   harvest Europeana into data/europeana/<name>/
evals/embed/      sample bake-off set
tests/            unittest suites, external services mocked
```

```mermaid
flowchart LR
    subgraph scripts
        FMs[fetch_models.py]
        EB[embed_bakeoff.py]
        GS[graph_search.py]
        FEs[fetch_europeana.py]
    end
    subgraph core[campus_ai.core]
        E[embed: Embedder, get_embedder, truncate]
        G[graph: GraphStore, HybridRetriever, connect]
    end
    subgraph ra[campus_ai.research_assistant]
        EU[europeana: to_records, is_open]
    end
    FMs --> E
    EB --> E
    GS --> E
    GS --> G
    G --> E
    FEs --> EU
    FEs -. writes JSONL read by .-> GS
```

Dependencies point inwards: scripts and products use `core`; `core` never
imports a product. The Europeana loader doesn't import the graph at all.
It writes JSONL, which keeps the networked fetch step free of model and
database code.

## 5. Data flow

### 5.1 Ingest

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant FE as fetch-europeana
    participant API as api.europeana.eu
    participant Disk as ./data/europeana/name
    participant EMB as embed (offline)
    participant NEO as Neo4j

    Op->>FE: --rows 300 (default: salmon pilot query)
    loop pages of 100 (cursor)
        FE->>API: search.json (X-Api-Key header, reusability=open, media=true)
        API-->>FE: items (profile=rich)
        FE->>FE: keep CC0, PDM, CC BY, CC BY-SA only
        FE->>API: thumbnail (400 px) for image items
        FE->>Disk: media/<hash>.jpg
    end
    FE->>Disk: items.jsonl (Item, Image, Collection, Institution, Creator + links)
    Op->>EMB: graph_search.py index data/europeana/salmon/items.jsonl
    EMB->>NEO: ensure_schema (constraint, vector + fulltext indexes)
    EMB->>EMB: embed per (label, modality) group at 768-d
    EMB->>NEO: MERGE nodes (text, props, vec_fast 128-d, vec_full 768-d)
    EMB->>NEO: MERGE links
```

### 5.2 Query

```mermaid
flowchart TD
    Q[Query: text, or a media file path] --> EQ[Embed at 768-d with the query prompt]
    EQ --> T[Truncate to 128-d]
    T --> V[Vector index entity_vec: top 50]
    Q --> FT{Text query?}
    FT -->|yes| W[Drop stop words and Lucene syntax]
    W --> F[Fulltext index entity_text: top 50]
    V --> U[Union of candidates]
    F --> U
    U --> RR[Rerank by cosine on vec_full 768-d]
    RR --> RRF[Reciprocal rank fusion: vector rank + fulltext rank]
    F --> RRF
    RRF --> K[Top k]
    K --> X[Graph expansion: up to 5 linked nodes per hit]
    X --> OUT[Hits with evidence]
```

## 6. Graph model

All searchable nodes share one label, `Entity`, which carries the unique `id`
constraint and both indexes. Each node also has a domain label, copied to its
`kind` property so vector search can filter by it inside the index.

```mermaid
erDiagram
    Item ||--o{ Image : "PART_OF (Image to Item)"
    Item }o--|| Collection : IN
    Collection }o--o{ Institution : HELD_BY
    Item }o--o{ Creator : CREATED_BY
    Item {
        string id "europeana:/dataset/record"
        string text "titles + descriptions"
        string kind "Item"
        string modality "text"
        string rights "rights statement URL"
        string url "europeana.eu item page"
        string source "europeana"
        string type "IMAGE, TEXT, VIDEO, SOUND"
        string provider
        string year
        string language
        list vec_fast "128-d, indexed"
        list vec_full "768-d, reranking"
    }
    Image {
        string id "item id + #image"
        string modality "image"
        string rights
    }
```

| Index | Type | On | Used for |
|---|---|---|---|
| `entity_id` | uniqueness constraint | `Entity.id` | MERGE on re-index |
| `entity_vec` | vector, cosine, 128-d, filterable by `kind` | `Entity.vec_fast` | Candidate search, optionally within labels |
| `entity_text` | fulltext (Lucene) | `Entity.text` | Keyword candidates |

The planned research graph (section 4.2 of the master plan: Researcher,
Publication, Project, Call, Topic) uses the same `Entity` convention, so one
retriever searches people, projects and collections together.

## 7. Key decisions

| Decision | Choice | Why | Alternatives considered |
|---|---|---|---|
| Embedder (D7) | EmbeddingGemma 2, local weights | One space for text, image, audio, video; Apache 2.0; Matryoshka sizes; multilingual | vLLM and Ollama don't serve it yet; e5-small kept as text baseline |
| Vector sizes | 128-d indexed, 768-d stored | Small index for fast candidates, full precision for the final order | Index at 768-d: larger, slower; 128-d only: less accurate |
| Fusion | Reciprocal rank fusion, k=60 | No score calibration between cosine and Lucene; robust | Weighted score sum needs tuning per corpus |
| Fulltext analyzer | Language-neutral, stop words removed at query time | Corpus is multilingual; Lucene's analyzer holds one language's stop words | Per-language indexes: more schema for little gain at this size |
| Graph store | Neo4j Community in compose | Vector, fulltext and graph traversal in one store; matches the plan's graph-RAG pattern | Separate vector DB + graph: two stores to keep in sync |
| Isolation | Internal Docker network | Models and data can't reach the internet even if code tries | Disabling all networking would also cut off Neo4j |
| Loader output | JSONL files, then index | Fetch needs no model; harvests are reproducible and inspectable; one indexer for all sources | Writing to Neo4j during fetch would put models on an internet-connected container |
| Europeana media | 400 px thumbnails via `api.europeana.eu` | One host, stable, enough for image embeddings; full-size media is spread over hundreds of provider hosts | Full-size downloads: later, per provider |
| Secrets | `.env` (gitignored); API key sent only as a header | Keeps keys out of git, URLs and logs | — |

## 8. Security, privacy and rights

- **Secrets.** `EUROPEANA_API_KEY`, `HF_TOKEN` and `NEO4J_PASSWORD` live in
  `.env`, which git ignores. The Europeana key travels only in the
  `X-Api-Key` header to `api.europeana.eu`.
- **Network.** Only the two `fetch-*` services and the `web` proxy reach a
  non-internal network. `embed`, `api` and `neo4j` are internal only; Neo4j
  has no published ports, and `web` publishes on localhost only.
- **Web.** The UI sets a strict Content-Security-Policy (same-origin scripts,
  styles and images only), renders record text with `textContent` only, and
  loads no fonts or scripts from CDNs. `/media` serves only image files in a
  harvest's `media/` folder, never JSONL or other data. Image uploads are
  limited to 10 MB and to JPEG, PNG, WebP and GIF, and are deleted after the
  search.
- **Rights.** The loader keeps only CC0, Public Domain Mark, CC BY and
  CC BY-SA items, and stores each item's rights URL and source page on the
  node so answers can attribute them.
- **Data at rest.** Harvested data (`data/europeana/`), weights (`models/`)
  and `.env` are excluded from git and from Docker build contexts.
- **Planned.** GDPR handling for EU researcher data, OCAP® for Indigenous
  materials, and in-region LLM routing (master plan, sections 4.4 and 2).

## 9. Resilience

- `neo4j`, `api` and `web` have `restart: unless-stopped`: they come back
  after a crash and when Docker starts (e.g. after a reboot, if Docker Desktop
  starts with Windows), until you stop them with `docker compose stop`.
- Health checks on all three. `api` is restarted by Compose when Neo4j is, and
  its database driver also reconnects on its own.
- nginx looks up `api` through Docker's DNS on every request (cached 10 s), so
  a recreated `api` container with a new address is found without restarting
  `web`.
- Each image is built by one service only (`test`, `embed`); `api`,
  `fetch-models` and `fetch-europeana` reuse the image with
  `pull_policy: never`. Building one image from two services in parallel
  corrupted it, so run `docker compose build` before `up`.
- Measured: a crashed `api` serves again in about 25 s (model reload); after a
  Neo4j restart, search works again within seconds.

## 10. Scaling and limits

- Indexing is CPU-bound without a GPU. Add `compose.gpu.yaml` on NVIDIA
  machines; models then run in bfloat16.
- Neo4j Community is single-instance. That's fine for the pilot scale, which
  is thousands of nodes.
- Changing the embedder or its vector sizes means rebuilding the graph;
  `ensure_schema` refuses a mismatched index.
- See [`design.md`](design.md) section 7 for known limitations.

## 11. Course Access Agent

The second product. It takes a course document (PDF, PPTX or DOCX), finds
what fails WCAG 2.2 AA, fixes what it safely can, and sends the rest to a
person. Output: an accessible DOCX or HTML version, an issue report mapped to
WCAG success criteria, and a short conformance statement (master plan,
section 3). It shares the LLM router, review queue, eval harness and tracing
with the Research Assistant, but not the graph: course materials are never
indexed into the shared graph.

### 11.1 Status

| Card | What | State |
|---|---|---|
| A1 | Document parser: PDF/PPTX/DOCX into one structure | Built on branch `a1-document-parser` (PR #4, 7 tests). **Not merged** into this line yet |
| A2 | Deterministic audit + WCAG-mapped report | Planned |
| A3 | Alt-text worker (vision model, confidence score) | Planned; needs the LLM router (P1, PR #2, not merged) |
| A4 | Structure, table and text workers | Planned |
| A5 | Rebuild accessible DOCX/HTML + verify loop | Planned |
| A6 | Gold set (40 documents) and eval metrics | Planned; needs P6 and the documents |
| P3 | Review queue (approve / edit / reject) | Planned |

### 11.2 Pipeline

Solid boxes exist; dashed boxes are planned.

```mermaid
flowchart TD
    U[Upload: PDF, PPTX, DOCX] --> P[A1 Parse<br/>Document: headings, paragraphs,<br/>lists, tables, images, links]
    P --> A[A2 Audit<br/>deterministic checks, WCAG-mapped]
    A --> R{Route by issue type}
    R --> W1[A3 Alt text<br/>vision model via LLM router]
    R --> W2[A4 Structure: headings,<br/>lists, reading order]
    R --> W3[A4 Tables: header rows, captions]
    R --> W4[A4 Text: link text, language]
    W1 & W2 & W3 & W4 --> B[A5 Rebuild DOCX / HTML]
    B --> V[A5 Verify: re-run audit,<br/>max 2 loops]
    V -->|issues remain| R
    V --> H[P3 Review queue<br/>diagrams, charts, equations,<br/>low-confidence fixes]
    H --> O[Accessible file + WCAG report<br/>+ conformance statement]
    classDef planned stroke-dasharray: 5 5
    class A,R,W1,W2,W3,W4,B,V,H,O planned
```

Principles specific to this product (master plan 3.2):
- **Never change academic content**, only structure and descriptions.
- **Checkable things are checked by code** (A2), and every fix is re-checked
  by the same checker that found the issue (A5). LLMs are used only for
  judgement: alt text, reading order, link wording.
- **People approve meaning.** Every chart, diagram and equation, and every
  fix below the confidence threshold, goes to the review queue; nothing is
  published automatically.

### 11.3 Runtime (planned)

Following the rules in section 2, Course Access will be one more compose
service in its own image. Parsing, auditing and rebuilding are local and
deterministic. The only model calls are alt text and other judgement steps,
and they go through the LLM router (P1): Claude in the customer's region
(Canada for BC, EU for EU institutions) or a local model for sensitive
material. Documents are processed and returned; the service keeps no copy
beyond what the review queue needs, and nothing enters the search graph.

### 11.4 Open items

| Item | Why it matters |
|---|---|
| **PyMuPDF licence** | A1 reads PDFs with PyMuPDF, which is AGPL-3.0 or a paid Artifex licence. For a product sold to institutions this needs a decision: buy the licence, keep the service unexposed to AGPL obligations after legal review, or switch PDF libraries |
| Scanned PDFs | A1 reads text layers only; image-only scans give no text. OCR is not in the plan yet |
| Untagged PDFs | Carry no heading or list semantics, so A1 returns them as paragraphs; A4 must infer structure |
| Checkers | The plan names axe-core (via Playwright) and veraPDF (Java). Both add large runtimes to the image; confirm before A2 |
| Vision model and region | Depends on D2 and on which Claude models are available in-region (master plan section 2) |
| Gold set | 40 real course documents labelled by an accessibility specialist (D6); none collected yet |

Module details for A1 are in [`design.md`](design.md#9-course-access-agent).
