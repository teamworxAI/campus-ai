# Design

Module-level design of the built parts: embedder (P7), graph core (P5),
Europeana loader (R8), collections search (R9), LLM router (P1) with its
data-class gate (P1b), tracing (P2) and the Course Access parser and audit
(A1, A2). The system view is in
[`architecture.md`](architecture.md).

## 1. Embedder: `campus_ai/core/embed/`

### 1.1 Interface

```python
from campus_ai.core.embed import get_embedder, truncate

embedder = get_embedder()                       # "embeddinggemma-2" (default) or "e5-small"
vectors = embedder.embed(["text"], modality="text", kind="document", data_class="P")   # (n, 768) float32, unit length
query = embedder.embed(["ocean warming"], kind="query", data_class="P")
small = truncate(vectors, 128)                  # Matryoshka prefix, re-normalized
```

| Attribute | Meaning |
|---|---|
| `name` | Backend name (`embeddinggemma-2`, `e5-small`) |
| `model_id` | Hugging Face ID; weights load from `$MODELS_DIR/<model_id>` |
| `dims` | Supported sizes, full size first: `(768, 512, 256, 128)` for EmbeddingGemma 2, `(384,)` for e5 |
| `modalities` | `text`, `image`, `audio`, `video` for EmbeddingGemma 2; `text` for e5 |
| `query_kwargs` / `document_kwargs` | Task prompts applied to text (`SearchQuery` / `Document`) |

```mermaid
classDiagram
    class Embedder {
        +name: str
        +model_id: str
        +dims: tuple
        +modalities: tuple
        +model: SentenceTransformer (lazy)
        +embed(inputs, modality, kind, dim, data_class) ndarray
    }
    class media {
        +load_audio(path) ndarray
        +load_video(path) dict
    }
    Embedder ..> media : decodes audio/video paths
    note for Embedder "get_embedder(name) picks a backend from BACKENDS"
```

### 1.2 Behaviour

- **Data class.** Every call declares `data_class` (P, I, S or R, keyword
  only, no default). Class R raises `RestrictedDataError` before the model
  loads or sees any input (P1b, section 11).
- **Lazy loading.** The model loads on first `embed`, from local files only.
  A missing directory raises `FileNotFoundError` with the fetch command.
- **Precision.** bfloat16 on GPUs that support it, else float32. Never
  float16, because EmbeddingGemma 2 overflows in it.
- **Inputs.** Text is passed as strings. Images are file paths or PIL images.
  Audio and video file paths are decoded with PyAV, which bundles FFmpeg:
  audio as mono 16 kHz, video at 1 frame per second.
- **Context.** 8,192 tokens per input: about 29 images, 58 s of video or
  327 s of audio. Split longer media before embedding.
- **Output.** Unit-length float32 vectors. `truncate` keeps a prefix and
  re-normalizes it, which is valid for Matryoshka-trained models.

### 1.3 Bake-off (decision D7)

`scripts/embed_bakeoff.py` embeds a JSONL set with each backend and reports
recall@k overall and per query language. Keep the e5 baseline if EmbeddingGemma 2
loses on the gold set.

## 2. Graph store: `campus_ai/core/graph/store.py`

### 2.1 Types

```python
@dataclass
class Node:
    id: str                  # globally unique, e.g. "europeana:/916105/bhm_photo_1"
    label: str               # domain label, e.g. "Item"; plain identifier only
    text: str = ""           # fulltext-indexed; caption or metadata for media
    modality: str = "text"
    content: Any = None      # what gets embedded; defaults to text; a file path for media
    props: dict = {}         # extra properties (rights, url, source, ...)
    data_class: str = "P"    # P/I/S/R; R is refused before embedding

@dataclass
class Link:
    src: str; type: str; dst: str; props: dict = {}
```

### 2.2 Operations

| Method | What it does |
|---|---|
| `ensure_schema()` | Creates the `entity_id` constraint, the 128-d `entity_vec` vector index (with `kind` as a filter property) and the `entity_text` fulltext index if they don't exist, then waits for them to come online. Refuses if an existing vector index has another size |
| `upsert(nodes)` | Groups nodes by `(label, modality, data_class)`, embeds each group once at full size, then `MERGE`s by `id` and sets the label, `kind`, props, `text`, `modality`, `file` (the media path; null for text), `vec_fast` (prefix) and `vec_full` |
| `link(links)` | Groups by type and `MERGE`s relationships between existing nodes. Links to unknown ids are skipped silently |

Labels and relationship types can't be Cypher parameters, so `name()` accepts
only plain identifiers (`[A-Za-z_][A-Za-z0-9_]*`). This prevents injection.

Upserts are idempotent: re-indexing a file replaces each node's vectors and
text, and leaves its links in place.

## 3. Hybrid retriever: `campus_ai/core/graph/retriever.py`

```mermaid
sequenceDiagram
    participant C as Caller
    participant R as HybridRetriever
    participant E as Embedder
    participant N as Neo4j
    C->>R: search(query, k=10, modality, labels, neighbors=5)
    R->>E: embed([query], kind="query")  (768-d)
    R->>N: SEARCH ... VECTOR INDEX entity_vec FOR vec[:128] WHERE kind IN labels LIMIT 50
    alt text query with content words
        R->>N: db.index.fulltext.queryNodes(entity_text, words, limit 50)
    end
    R->>R: cosine(query, vec_full) for every candidate, sort
    R->>R: RRF over [vector order, fulltext order]
    R->>N: neighbours of top k (COLLECT subquery, LIMIT neighbors)
    R-->>C: [Hit(id, labels, text, score, neighbors)]
```

**Scoring.** Each list contributes `1 / (60 + rank)`. A node first in both
lists scores 2/61 ≈ 0.0328; first in one list only, 1/61 ≈ 0.0164. Scores
order the results but aren't probabilities.

**Fulltext query building** (`fulltext_query`):
1. Lower-case, so `AND`, `OR` and `NOT` lose their Lucene meaning.
2. Keep word characters only. Quotes, wildcards, brackets and field prefixes
   are dropped.
3. Drop one-letter fragments (`d` from `d'archives`) and stop words in seven
   languages (`stopwords.py`: en, fr, de, es, it, pt, nl).

Media queries (`modality="image"` etc.) use only the vector side.

**Label filter.** Every node stores its label as `kind`, and the vector index
includes `kind` as a filter property, so `SEARCH … WHERE node.kind IN $labels`
returns the 50 nearest nodes *with* those labels. (An earlier version filtered
after the index's top 50; on a mixed graph, text items filled every slot and
`--label Image` came back empty.) Fulltext still filters after its top 50,
which matters little because media nodes have no text. `ensure_schema`
migrates graphs indexed before this change in place, without re-embedding.

**Hit.**

```python
Hit(id="europeana:/…", labels=["Entity", "Item"], text="…", score=0.0328,
    neighbors=[{"type": "IN", "outgoing": True, "id": "europeana:collection:…",
                "labels": [...], "text": "…"}],
    found_by=["meaning", "words"],   # vector index, fulltext index
    similarity=0.61)                 # cosine to the query at 768-d
```

Planned: a reranker step (Qwen3-Reranker-4B, card R3, bake-off B2).

## 4. Europeana loader (R8)

### 4.1 Fetch: `scripts/fetch_europeana.py`

```mermaid
flowchart TD
    A[Start: query, qf filters, rows] --> K{EUROPEANA_API_KEY set?}
    K -->|no| X[Exit with message]
    K -->|yes| S[search.json page: reusability=open, media=true, profile=rich, rows≤100, cursor]
    S --> I{for each item}
    I --> O{rights open?}
    O -->|no| I
    O -->|yes| T{IMAGE with api.europeana.eu thumbnail?}
    T -->|yes| D{media/hash.jpg exists?}
    D -->|no| G[GET thumbnail size=w400; keep only image/*]
    D -->|yes| R
    G --> R[to_records item, image path]
    T -->|no| R
    R --> M[Merge into record map by id or src,type,dst]
    M --> I
    I -->|page done| N{nextCursor and seen < rows?}
    N -->|yes| S
    N -->|no| W[Write items.jsonl]
```

- The API key goes in the `X-Api-Key` header, never in the URL.
- A failed thumbnail download is logged and the item is kept as text only.
- Re-runs reuse thumbnails already on disk, named by a hash of the item id.
- Shared nodes (collections, institutions, creators) are de-duplicated.

### 4.2 Mapping: `campus_ai/research_assistant/europeana.py`

| Europeana field (search, `profile=rich`) | Graph |
|---|---|
| `id` | `Item.id = "europeana:" + id` |
| `title` + `dcDescription` (de-duplicated, whitespace-normalized, ≤ 2,000 chars) | `Item.text` (embedded and fulltext-indexed) |
| `rights[0]` | `Item.rights`, `Image.rights`; item dropped unless open |
| `guid` (query string dropped: it carries tracking parameters and the API key) | `Item.url` |
| `type`, `provider`, `year`, `language` | `Item` props |
| thumbnail of `edmPreview` | `Image` node (`id` = item id + `#image`, `modality=image`, no text, `file` = thumbnail path), `PART_OF` its Item |
| `edmDatasetName[0]` | `Collection`, linked by `IN` |
| `dataProvider[0]` | `Institution`, linked from the Collection by `HELD_BY` |
| `dcCreator` (names only; URIs skipped) | `Creator`, linked by `CREATED_BY` |

Open rights: `creativecommons.org/publicdomain/zero/`, `/publicdomain/mark/`,
`/licenses/by/`, `/licenses/by-sa/`. NC and ND licences and
rightsstatements.org statements are excluded. This is the loader's own
filter; the shared rights filter (R10, below) checks again at indexing.

**Why a separate Image node.** An Item's vector encodes its metadata text;
the Image's vector encodes the picture alone. A text query can then match a
photo on what it shows, even when the caption is in another language or
says nothing useful. Graph expansion links each Image hit back to its Item
for citation.

### 4.3 Collections search (R9): `collections.py`, `api.py`

`CollectionsSearch` wraps `HybridRetriever` (50 candidates) and returns
`Card`s with title, description, source, type, year, URL, rights, licence
label, collection, holder, creators and image:

- `pictures(query, k, modality)` searches `Image` nodes only, maps each hit
  to its Item (`id` before `#`), and marks items whose own text also matched
  the words.
- `texts(query, k)` searches `Item` nodes and keeps those without a picture.
- `item(id)` returns one card with APA, Chicago and BibTeX citations and up
  to 4 similar pictures.
- Image queries label each card "Same picture" (cosine ≥ 0.98), "Similar"
  (≥ 0.76) or "Not close"; the API's `match` field applies the same
  thresholds to the best hit. Thresholds were calibrated on the salmon pilot.

`api.py` exposes these as `GET /api/health`, `GET /api/search`,
`POST /api/search/image`, `GET /api/items/{id}` and `GET /media/{path}`
(architecture section 5.3). One lock serialises embedding; uploads are
checked for type (JPEG, PNG, WebP, GIF) and size (10 MB) and kept only in a
temporary file for the search.

### 4.4 Rights filter (R10): `campus_ai/research_assistant/rights.py`

`graph_search.py index` passes every file through `screen(nodes, links)`
before embedding; `graph_search.py rights <file>` prints the same report
without embedding or Neo4j. Deterministic, no model involved.

| Record | Class R when |
|---|---|
| Any | `access` is set and not `open`; `tk_labels` is non-empty; `rights` points at localcontexts.org |
| Item or Image with a `source` | `rights` is missing or not CC0, PDM, CC BY or CC BY-SA |
| Part of a class-R item (`PART_OF`) | always |
| Collection, Institution, Creator with a `source` | not linked, directly or through other metadata, to a kept node |

Class-R records and the links touching them are never written to the graph,
so they are never embedded, searched or shown to a model. They stay only in
the harvested JSONL, as a metadata link (id and source URL) printed in the
index report. Records without a `source` are the repo's own fixtures (the
bake-off set) and need no rights statement. Eval:
`evals/rights/sample_records.jsonl` keeps 5 of 10 items (8 of 15 nodes).

## 5. File formats

One JSONL format feeds the indexer from any source, one record per line:

```json
{"id": "d1", "label": "Item", "modality": "text", "content": "Text to embed", "props": {"rights": "..."}}
{"id": "d2", "label": "Image", "modality": "image", "content": "media/photo.jpg", "text": "optional caption"}
{"src": "d2", "type": "PART_OF", "dst": "d1"}
{"query": "salmon fishing", "lang": "en", "relevant": ["d1", "d2"]}
```

- `label` defaults to `Item` and `modality` to `text`.
- Media `content` paths are relative to the JSONL file. Media `text` is a
  real caption or empty, never the file path.
- `query` lines are used by `eval` and by the bake-off, and ignored by `index`.
- Governance props, read by the rights filter (R10) before anything is
  embedded: `source` (the harvested collection), `rights` (rights statement
  URI), `access` (ArcaBC access limit; empty or `open` means none) and
  `tk_labels` (TK/BC Labels, Local Contexts Notices or other community
  protocol markers). See section 4.4.

## 6. Testing strategy

| Suite | Covers | External services |
|---|---|---|
| `tests/test_embed*.py` | Backends, truncation, media decoding, bake-off | Model replaced by a deterministic fake |
| `tests/test_graph.py` | Schema, upsert grouping, linking, fusion, fulltext query building, retriever flow, JSONL loading | `FakeDriver` records Cypher; a bag-of-words fake model. Integration tests run against a real Neo4j when `NEO4J_URI` is set and the embed image is used |
| `tests/test_licences.py` | Prime directive 1: every installed package under an OSI licence (AGPL and proprietary fail; NVIDIA GPU runtimes are the named exception), every compose/Dockerfile image, every embedder model and every LLM router model (`MODEL_LICENCES`, defaults included) listed with an open licence | None; reads package metadata and repo files. Run in the `embed` image too, to cover PyTorch and CUDA |
| `tests/test_europeana.py` | Rights filter, mapping, de-duplication, cursor paging, key in header, thumbnail caching | HTTP `get` mocked |
| `tests/test_collections.py` | Cards, licence labels, citations, picture-match thresholds, search service, API endpoints and `/media` restrictions | `FakeDriver` and a fake retriever |
| `tests/test_llm_router.py` | Routing to `OLLAMA_HOST`, image blocks, open-licence allowlist, no cloud backends, data-class gate, one trace record per call | Ollama HTTP call mocked; traces in a temp directory |
| `tests/test_tracing.py` | Run files, metadata-only records, span outcomes and latency, data-class checks | None; traces in a temp directory |
| `tests/test_course_access_parser.py`, `tests/test_course_access_audit.py` | A1 parsing per format; A2 rules and reports | None; small documents built in the tests |
| `tests/test_package.py` | Every package imports | None |

`docker compose run --rm test` runs everything that needs no models (4
tests skip: 2 need PyAV, 2 need Neo4j). `docker compose run --rm embed
python -m unittest discover -s tests` also runs those.

## 7. Known limitations

- **Thumbnails only** for Europeana images. Full-size media, audio and video
  need each provider's host (and network allowlisting). VIDEO and SOUND
  items are indexed as text.
- **Mixed-modality ranking.** A text query scores text nodes higher than
  images, so search pictures and texts as separate lists (`labels`).
- **Item text mixes languages** when Europeana returns translated titles.
  This is fine for the multilingual embedder, but noisy for fulltext.
- **Fulltext label filter after top-n** (section 3) can drop keyword matches
  for a rare label; vector candidates are unaffected.
- **No Europeana gold set yet.** Recall on collections search waits for the
  labelled queries in master plan section 4.5.
- **Re-index on model change.** The vector index has one fixed size.
- **Links to missing nodes are skipped silently.** Index nodes before
  their links; one JSONL file does this automatically.

## 8. Extending

**Add a source loader.**
1. Write a pure mapping function (source record → JSONL records) in the
   product package, like `europeana.to_records`, and unit-test it.
2. Write a `scripts/fetch_<source>.py` that only fetches and writes
   `data/<source>/<name>/items.jsonl` plus media.
3. Add a `fetch-<source>` compose service with `profiles: [fetch]`, mounting
   `./data`. Add any new key to `.env.example`.
4. Index with `graph_search.py index`. No graph or model code is needed.

**Add an embedder backend.** Add a factory to `BACKENDS` in
`campus_ai/core/embed/embedder.py`, then fetch its weights. Run the bake-off.
Switching the graph to it needs a fresh graph (`docker compose down -v`).

## 9. Course Access Agent

The system view and status are in [`architecture.md`](architecture.md#11-course-access-agent).
A1 (parser) and A2 (audit) exist; A3-A7 are planned. A1 reads files with open-source, permissively licensed libraries only: python-docx and python-pptx (MIT) and pdfplumber on pdfminer.six (MIT). The first version (PR #4) used PyMuPDF, which is AGPL and was replaced under prime directive 1. Everything
here is bound by the prime directives (`AGENTS.md`): open-source libraries only,
and any model (alt text, OCR) runs locally from open weights.

### 9.1 Document parser (A1): `campus_ai/course_access/parser.py`

```python
from campus_ai.course_access.parser import parse

doc = parse("lecture-03.pptx")      # .pdf, .pptx or .docx; anything else raises ValueError
doc.source_format, doc.title, doc.language, doc.page_count
for block in doc.blocks:            # in reading order
    ...
```

The parser **only reads**. It never repairs: missing headings, alt text or
language come back as `None` or as no block, so the audit (A2) can flag them.

```mermaid
classDiagram
    class Document {
        source_format: pdf | pptx | docx
        title: str | None
        language: str | None
        page_count: int | None
        blocks: list~Block~
    }
    class Heading { text; level }
    class Paragraph { text }
    class ListItem { text; level }
    class Table { rows; has_header_row }
    class Image { data; format; alt; decorative; nearby_text }
    class Link { text; url }
    Document --> Heading
    Document --> Paragraph
    Document --> ListItem
    Document --> Table
    Document --> Image
    Document --> Link
    note for Document "every block also carries page: 1-based page (PDF) or slide (PPTX); None for DOCX"
```

**Reading order per format** (the order a screen reader follows):

| Format | Order | Headings and lists | Images | Document language |
|---|---|---|---|---|
| DOCX | Body order of paragraphs and tables | From `Heading N` styles; lists from numbering or `List` styles, with nesting level | Inline drawings, with `descr` alt text and Office's decorative flag | Core properties, else the default style's language |
| PPTX | Slide order, then shape order on each slide; groups flattened | Title placeholders become level-1 headings; body placeholders are bullets unless `buNone` | Pictures, with `descr` alt text and decorative flag | Core properties, else the first text run's language |
| PDF (pdfplumber) | Per page, top to bottom then left to right: paragraphs (consecutive lines joined until a gap taller than a line, or a table or image in between), ruled tables, images | None: untagged PDFs carry no semantics, so text is paragraphs | Each image as a 150 dpi PNG of its area on the page (what a reader sees), with no alt text (not read from tags) | The catalog's `/Lang` |

Other rules:
- **Tables**: DOCX marks a header row with `tblHeader`; PPTX with the
  table's *first row* setting; PDF tables (ruled tables found by pdfplumber) never have one.
  Text inside a PDF table is emitted once, as the table.
- **Links** follow the block that contains them; PDF links come at the end
  of their page.
- **Images** get `nearby_text`: the text block just before and just after on
  the same page, the context the alt-text worker (A3) needs.

### 9.2 Audit (A2): `campus_ai/course_access/audit.py`

`audit(document)` returns `Issue`s in document order; `report_markdown` and
`report_json` render them. Deterministic only: no model.

| Rule | WCAG 2.2 | Level | Finds | Fixed by |
|---|---|---|---|---|
| `document-no-title` | 2.4.2 Page Titled | A | No title in the document properties | text worker |
| `document-no-language`, `document-bad-language` | 3.1.1 Language of Page | A | Language missing, or not a language tag | text worker |
| `no-headings` | 1.3.1 Info and Relationships | A | 5+ paragraphs and no headings (for PDFs: no heading markup) | structure worker |
| `heading-level-skipped` | 1.3.1 | A | A heading more than one level deeper than the previous one | structure worker |
| `slide-no-title`, `slide-title-duplicate` | 2.4.6 Headings and Labels | AA | PPTX slides without a title, or sharing one | structure worker |
| `image-missing-alt` | 1.1.1 Non-text Content | A | Image with no alt text and not marked decorative | alt-text worker |
| `image-placeholder-alt` | 1.1.1 | A | Alt text that is a file name or a word like "image" | alt-text worker |
| `table-no-header-row` | 1.3.1 | A | Table of 2+ rows without a marked header row | table worker |
| `link-no-text`, `link-vague-text`, `link-bare-url` | 2.4.4 Link Purpose (In Context) | A | Empty, "click here"-style or raw-URL link text | text worker |
| `fake-list` | 1.3.1 | A | Paragraphs typed as lists ("- ", "1. ", "a) ") instead of real list markup | structure worker |
| `scanned-page` | 1.4.5 Images of Text | AA | PDF page that was an image of text, read by OCR (A7); lists words recovered and mean confidence | OCR, human review |
| `page-image-only` | 1.4.5 | AA | PDF page with images and no text that OCR could not read (no Tesseract, or no words found) | person |

Every report ends with what the audit cannot check (contrast, accuracy of
existing alt text, meaningful sequence, PDF tags, language of parts,
equations and charts), so a short list is never read as conformance.

Run it:

```bash
docker compose run --rm -v "$PWD/samples:/samples:ro" test python scripts/audit_document.py /samples/lecture.pdf
docker compose run --rm -v "$PWD/samples:/samples:ro" test python scripts/audit_document.py /samples/lecture.pdf --json
```

### 9.3 Alt-text worker (A3): `campus_ai/course_access/alt_text.py`

```python
from campus_ai.course_access.alt_text import propose, report_markdown

proposals = propose(doc, data_class="I")   # one AltText per image the audit flags
print(report_markdown(proposals, "lecture-03.pptx"))
```

The worker is the first caller of the LLM router. Code decides everything
that can be decided without judgement; the model only describes.

| Step | Who | What |
|---|---|---|
| Which images | code | The audit's `image-missing-alt` and `image-placeholder-alt` issues (`images_needing_alt`); decorative images and good alt text are left alone |
| What the model sees | code | The image (base64), the document title and format, the page or slide, the text just before and after (`Image.nearby_text`) and any placeholder alt to replace |
| The answer | model | One JSON object: `kind` (photo, illustration, chart, diagram, equation, text, decorative, other), `decorative`, `alt` (one sentence), `long_description` (axes and values for a chart, parts for a diagram, the equation, the text of an image of text) and `confidence` 0-1. Task `vision` on the router, so D9 and `CAMPUS_AI_MODEL_VISION` choose the model |
| Checks | code | JSON found even inside prose or a code fence, else the proposal is sent to review as unparsed; unknown kinds become `other`; confidence clamped to 0-1; a leading "image of" or "picture of" is removed; decorative means empty alt |
| Review routing | code | Always: charts, diagrams, equations, images of text, proposals to mark an image decorative, unparsed answers. Also: confidence below 0.7, empty alt, alt over 200 characters. `AltText.needs_review` and `review_reason` say which |

`report_markdown` is the review sheet (one section per image with alt, long
description, review reason and model); `report_json` is for the review queue
(P3) and the rebuild step (A5), which applies approved proposals. Nothing is
written to the document here.

The confidence is the model's own estimate. In the probe run with
`gemma4:e2b` it was 1.00 for every image, so it carries no signal on that
model; the deterministic routing above, not the threshold, is what keeps
wrong descriptions from going out, and bake-off B3 must calibrate confidence
(or replace it with a judge) on the A6 gold set.

`evals/course_access/alt_text_probes.py` draws six images with known kinds
(bar chart, flow diagram, equation, text slide, divider, shapes), runs the
worker on them and writes a report next to itself: a shape check for the
configured model, not the bake-off. Card A3b (charts: extract the data as a
table first, then check every claim against it) is not built.

### 9.4 Structure, table and text workers (A4): `campus_ai/course_access/workers.py`

```python
from campus_ai.course_access.workers import propose_fixes, report_markdown

fixes = propose_fixes(doc, data_class="I")   # one or more Fix per structure, table or text issue
print(report_markdown(fixes, "lecture-03.pptx"))
```

`propose_fixes` routes the audit's issues by rule to a handler; alt-text
issues are A3's. Every `Fix` carries the rule, the worker, an `action` from
`ACTIONS`, the proposed `value` (`None` when a person must supply it), a
confidence, `needs_review` with its reason, the evidence, and the model if
one was asked. Rules in code make every proposal the document gives away;
the model is asked only where judgement is needed, and its answer is parsed
and checked like A3's (`model_answers.py`).

| Rule | Action | How | Confidence, review |
|---|---|---|---|
| `fake-list` | `convert-to-list` | Strip the typed marker; ordered if it is a number or letter | 0.9, applied |
| `heading-level-skipped` | `set-heading-level` | One level below the previous heading | 0.8, applied |
| `slide-title-duplicate` | `retitle-slide` | "Title (n of m)" over the slides that share it (WCAG 2.4.6) | 0.9, applied |
| `slide-no-title` | `add-slide-title` | The slide's first line of text; none if the slide has no text | 0.6, review (0, review) |
| `no-headings` | `promote-to-heading` | Each short line without a final period that a longer paragraph follows | 0.5, review |
| `table-no-header-row` | `treat-as-layout` | One column, 40%+ empty cells, or two rows of multi-line text: page layout, not data (most PDF "tables") | 0.75, applied |
| `table-no-header-row` | `mark-header-row` | First row all short, distinct, non-numeric text; otherwise doubtful | 0.85 applied; 0.5 review |
| `document-no-title` | `set-title` | First level-1 heading; else the first short paragraph; else none | 0.85 applied; 0.5 or 0, review |
| `document-no-language`, `-bad-language` | `set-language` | The model (task `classification`) names a BCP 47 tag for the first 600 characters; checked against the audit's tag pattern | model's, review below 0.7 |
| `link-bare-url`, `link-no-text`, `link-vague-text` | `set-link-text` | The text before the URL in the same paragraph if it has one ("Timeline template: https://..."); otherwise the model (task `reasoning`) from the URL and surrounding text, rejected if vague, a URL or over 100 characters | 0.85 applied; model's, review below 0.7 |

`scripts/propose_fixes.py` prints the review sheet for a document (and, with
`--alt-text`, A3's proposals too). `evals/course_access/propose_corpus.py`
runs the workers over the A6 corpus and tabulates proposals, review share and
model use per action, with samples to read. Reading order, captions and
colour contrast are not handled yet (the plan's W2-W4 also name them): the
parser does not yet give the workers what they need for those.

### 9.5 Rebuild and verify (A5): `campus_ai/course_access/rebuild.py`

```python
from campus_ai.course_access import rebuild

fixed = rebuild.apply(doc, approved_fixes, approved_alt_texts)   # a new Document; the input is untouched
notes = rebuild.to_docx(fixed, "lecture-03.docx")
html = rebuild.to_html(fixed)
rebuilt, remaining = rebuild.verify("lecture-03.docx")           # parse + audit the output again
print(rebuild.statement("lecture-03.pptx", issues, remaining, applied=len(approved_fixes), waiting=3, notes=notes))
```

`apply` changes only what a proposal names: a paragraph becomes a list item
or a heading, a heading changes level or text, a table gets its header row
or becomes the paragraphs of its cells, a link gets its text, an image its
alt text or decorative flag, the document its title and language; an
untitled slide gets its first line as title. Proposals without a value are
ignored. Nothing here decides what is approved: the caller passes what a
person, or the confidence threshold for rule-based proposals, approved.

| Output | What it carries |
|---|---|
| HTML (`to_html`) | `lang` and `<title>`; `h1`-`h6`; nested `ul`/`ol` from list levels; `<th scope="col">` header rows; images as data URIs with `alt`, or `alt="" role="presentation"` when decorative, or no `alt` at all when still undescribed (left for checkers to see, never faked); links inline in their paragraph where the text contains them, else on their own line; one `<section aria-label="Slide n">` per slide for PPTX |
| DOCX (`to_docx`) | Title and language in the core properties and the default run language; `Heading N` styles; `List Bullet`/`List Number` with the numbering level on the paragraph; `Table Grid` tables with `tblHeader` on the header row; pictures with `descr` alt text or Office's decorative flag; real hyperlinks (`w:hyperlink`) inline or on their own line. EMF/WMF pictures can't be embedded: their description is written as text and reported in the notes |

`verify` parses and audits the DOCX with the same A1 and A2 code as the
original, so before and after are measured alike; `compare` gives fixed,
remaining and introduced issues by rule. `statement` is the short
accessibility statement: found, applied, waiting for review, remaining,
introduced, the rebuild notes and the audit's "not checked" list, so the
output is never read as full conformance. The verify loop of the agent
design (re-route remaining issues, at most twice) is the review cycle: the
remaining issues are exactly those whose proposals wait for a person.

`scripts/remediate.py <file> --out <dir>` runs A1 to A5 end to end and writes
the DOCX, the HTML, the audit report, the review sheet of waiting proposals
and the statement; by default only proposals that need no review are
applied, `--approve-all` applies everything with a value (demos, evals).
`evals/course_access/remediate_corpus.py` does that for the A6 corpus and
reports issues before and after and issues introduced (plan 3.4 metrics).
PDF output (PDF/UA tagging) is post-Lisbon (plan 3.1); the accessible
version of a PDF is the DOCX and HTML.

### 9.6 Limits that the next cards must handle

| Limit | Handled by |
|---|---|
| No OCR: image-only (scanned) PDFs produce images and no text | Next phase: card A7, open-source offline OCR |
| Untagged PDF: no headings or lists; existing PDF tags and alt text are not read | A4 proposes heading candidates for review (`promote-to-heading`); A2 reports `no-headings` and lists PDF tags under "not checked". PDF alt text and table headers from tags would cut the inflated counts on tagged PDFs |
| Reading order is the file's, which may be wrong (e.g. a PPTX text box added last) | A2 lists reading order (1.3.2) under "not checked"; planned: A4 proposes a fix for review |
| Equations, charts and SmartArt come through as images or plain text | A3 describes them and always routes them to review (master plan 3.2); A3b adds the chart data check |
| Reading order on complex PDF layouts (columns, sidebars) follows position, not the author's intent | Planned: A4 proposes an order for review (A2 has no column check yet) |

## 10. LLM router (P1): `campus_ai/core/llm/`

```python
from campus_ai.core.llm import generate

reply = generate([{"role": "user", "content": "..."}], task="vision", data_class="I", system=None)
reply.text, reply.model, reply.input_tokens, reply.output_tokens, reply.stop_reason
```

- **Tasks** (`config.TASKS`): `reasoning` and `vision` (default
  `gemma4:12b`, 16,000 output tokens), `classification` (`gemma4:e4b`,
  1,024). Override per task with `CAMPUS_AI_MODEL_<TASK>`.
- **Allowlist.** `config.model()` refuses any model not in `MODEL_LICENCES`
  (Gemma 4, Qwen 3, Qwen3-VL, Granite 3.3, Mistral Small 3.2, OLMo 2; all
  Apache-2.0). Gemma 3 is excluded: its Gemma Terms of Use are not an open
  licence. Adding a model needs a licence check and a D10 register row.
- **Backend.** `backends.ollama` posts to `$OLLAMA_HOST/api/chat`
  (default `http://localhost:11434`) with streaming off; text and base64
  image blocks become Ollama's `content` and `images`. There is no other
  backend.
- **Data class and trace.** Every call declares the class of its messages
  (section 11); class R is refused before any model call. Each call, refused
  or not, writes one `llm` trace record (section 12).
- **Runtime.** No compose service calls the router yet; Ollama in compose
  is card P9 (planned).

## 11. Data-class gate (P1b): `campus_ai/core/data_classes.py`

```python
from campus_ai.core.data_classes import DATA_CLASSES, RestrictedDataError, check

check("I")   # returns "I"; "R" raises RestrictedDataError, anything else ValueError
```

The classes are those of plan section 2: P public, I institutional, S
sensitive, R restricted. The two model entry points call `check` first:
`llm.generate(..., data_class=...)` and `Embedder.embed(..., data_class=...)`.
Both arguments are required, so no call can skip the gate. Above them,
`Node.data_class` and `HybridRetriever.search(data_class=...)` default to P,
which is what the graph holds today (open Europeana items);
`graph_search.py index` reads an optional `data_class` per JSONL record. The
rights filter (R10) drops class-R records before indexing; the gate is the
backstop, so an R node that reaches `upsert` is refused, not embedded.

## 12. Tracing (P2): `campus_ai/core/tracing.py`

```python
from campus_ai.core import tracing

with tracing.run("audit-lecture-3"):              # one file per run
    with tracing.span("tool", tool="alt_text", data_class="I") as trace:
        trace["model"] = "gemma4:12b"             # add what the block learns
    tracing.record("tool", tool="rebuild", outcome="ok")
```

- **Where.** `$CAMPUS_AI_TRACE_DIR/<run id>.jsonl`, default `./traces`
  (git-ignored). Run ids are `<UTC timestamp>-<name>-<6 hex>`, e.g.
  `20261022T181500Z-audit-lecture-3-a1b2c3`; outside a `run()` block, calls
  share one id per process (`<UTC timestamp>-<pid>`).
- **Records.** One JSON object per line: `time` (UTC ISO), `run`, `event`,
  and only these metadata fields: `tool`, `task`, `model`, `host`,
  `data_class`, `input_tokens`, `output_tokens`, `latency_ms`, `outcome`
  (`ok`, `refused` for class R, `error`), `error` (exception type only).
  `record` refuses any other field, so prompts, documents and outputs (and
  so restricted content) never reach a trace.
- **Standard library only**; a lock keeps lines whole across threads.
