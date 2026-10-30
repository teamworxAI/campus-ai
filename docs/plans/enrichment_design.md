# Collections enrichment: accessibility and metadata (R11-R21)

Design for extending embedding and inference over the heritage collections
(Europeana now, Wikimedia Commons and others next, ArcaBC after R0b) so
every item carries accessibility content and richer, authority-linked
metadata in the graph. Agreed Oct 29, 2026; the task cards and decisions
are in `master_plan.md` (section 7, R11-R21; section 8, D12-D20).

The goal it serves: a local-first system on Google's open-weight models,
EmbeddingGemma 2 for embeddings and Gemma 4 for inference, both Apache-2.0.
Other models only where no Google open-weight model does the job, each
licence-checked (prime directive 1).

How it was made: a design panel on Oct 29. A reader mapped the current
pipeline; three architects wrote independent designs (graph-first on Sonnet,
model-pipeline-first on Fable, accessibility-first on Sonnet); Haiku
evaluated each against the prime directives and the repo; Opus judged,
corrected the evaluations against the repo and primary sources, and
synthesised this design from the pipeline-first winner with the best parts
of the other two. The user then replaced Tesseract with olmOCR 2 for
collections OCR (section 4, D20).

## 1. Principles

1. **Deterministic first.** Most of the gain is source metadata that
   `europeana.to_records` drops today (subjects, places, dates, languages,
   concept URIs). Models fill only what metadata cannot give.
2. **Proposals, not graph writes.** Model output goes to `proposals.jsonl`;
   a person approves or edits it; a deterministic apply step writes the
   file that is indexed. The graph holds only source data and approved
   output. Nothing is auto-applied (unlike the Course Access queue's
   `_approved`, which applies `needs_review=False` proposals).
3. **Authority ids, never names.** `Concept` and `Place` ids come from the
   authority URI, so later sources merge onto the same node. Nothing is
   merged on a name alone.
4. **No store or index change.** Everything goes through `props`,
   `Link.props` and `text`; the embedder stays pinned, so no rebuild.
5. **One resident model on the laptop.** `gemma4:e4b` does every Ollama
   task there. Larger models (`gemma4:12b`, olmOCR 2) run on the inference
   box.

## 2. Schema

All nodes are `:Entity:<Label>`; every node has `source`; every unit has
`rights` (and `access`, `tk_labels` where the source has them).

| Label | Id | `text` (embedded, fulltext) | New props |
|---|---|---|---|
| `Item` (existing) | `europeana:<recordId>` | title + description + `Subjects: …` + `Places: …` from source labels (2000-char cap) | `languages` (BCP-47, from `dcLanguage`/`language` via a static ISO 639 table); `date_from`, `date_to` (int years), `date_text`; `shown_at`, `shown_by` (query strings stripped); `content_tier`, `metadata_tier`; `access_mode`; `reading_lix`, `reading_band`; `a11y_features` (apply step only) |
| `Image` (existing) | `<item>#image` | approved alt + long description; empty until approved | `alt`, `long_description`, `alt_lang`, `alt_model`, `alt_prompt`, `alt_reviewed_by`, `alt_reviewed_at`, `alt_edited`; vector stays pixels |
| `Concept` (new) | `wd:Q…`, `aat:…` (identifier only), `europeana:concept:<id>`, else `europeana:concept:<slug>` | all labels the record carries, all languages | `uri` |
| `Place` (new) | `wd:Q…`, `geonames:<id>` (identifier only), `europeana:place:<id or slug>` | label | `uri`, `lat`, `lon` (only when the record has them) |
| `Creator` (existing) | unchanged | name | `uri`, only when one name pairs with exactly one URI |
| `Text` (R17) | `<item>#text-<n>` | OCR text, at most 8K tokens | `page`, `ocr_model`, `ocr_status` (`machine`/`reviewed`), `lang`, plus `rights`/`access`/`tk_labels` copied from the Item |
| `Audio`/`Video` (R18) | `<item>#audio-<n>` | approved transcript segment, else empty | `start`, `end`; windows of at most 300 s audio / 58 s video |

`access_mode`: IMAGE gives `visual`; SOUND `auditory`; VIDEO `visual,
auditory`; TEXT `textual` with a text layer, else `visual, textOnVisual`.
`a11y_features` (schema.org accessibilityFeature): `alternativeText`,
`longDescription`, `transcript`, `captions`, each only from approved
output. No `accessibilityHazard` is ever asserted.

Edges carry `basis`: `source` (with `field`) or `reviewed` (with `model`,
`proposal`, `reviewed_by`).

| Edge | From |
|---|---|
| `(Item)-[:ABOUT]->(Concept)` | concept URIs and labels, or approved proposals |
| `(Item)-[:SPATIAL]->(Place)` | the record's place fields (where it is about or from, not "depicts") |
| `(Item)-[:CREATED_BY {role}]->(Creator)` | `creator` or `contributor` |
| `(Text\|Audio\|Video)-[:PART_OF]->(Item)` | units |

Left out on purpose: a `Description` label (`pictures()` already finds
approved alt in `Image.text`); `Agent`, `Event`, `TimeSpan` nodes; range and
geo indexes until a filter needs them; `SAME_AS` to `Topic` (R20 builds the
bridge as reviewed proposals, since OpenAlex and CORDIS topic ids share no
key with Europeana concepts).

Reader: the `CARDS` Cypher returns `image.alt`, `image.long_description`,
`i.a11y_features`, `i.languages`, `i.date_text`, concepts and places; the UI
uses approved alt instead of `"Picture: " + title` and shows the long
description in a disclosure, so the collections UI itself gets more
accessible.

## 3. Pipeline

| # | Stage | Where | Det./model | Notes |
|---|---|---|---|---|
| 1 | Fetch | `fetch-europeana` (network, one-time) | D | Rotate the key first (D19). `raw.jsonl` beside `items.jsonl` for items passing `is_open`, with `link` dropped and `guid` query strings stripped (both carry the key). `--from-raw` remaps offline. R11 starts with a field-frequency dump; if the rich profile lacks a needed field, one Record API call per item in the same job |
| 2 | Map | `europeana.to_records` | D | Fields as in section 2 |
| 3 | Screen | `rights.screen` + classify | D | `rights.UNITS` grows to `{Item, Image, Text, Audio, Video}` before any new unit exists. Runs before any model; each node's own data class is passed, never a hard-coded "P" |
| 4 | Propose | new `enrich` compose service (test image, `graph` network, llm-env, `DATA_DIR` ro + `${DATA_DIR}/enrich` rw); `scripts/enrich.py propose` | M | Cache key: input sha + task + model digest + prompt version. Writes `DATA_DIR/enrich/<source>/<name>/proposals.jsonl` |
| 5 | Review | `api` with `${DATA_DIR}/enrich` rw; `web/static/review/collections/` | human | `decisions.jsonl`, append-only; every proposal needs an explicit decision |
| 6 | Apply | `scripts/enrich.py apply` | D | Mapped records + approved decisions give `enrich/<…>/items.jsonl`. An approved value is never replaced until a newer proposal is approved |
| 7 | Index | `graph_search.py index <enriched items.jsonl>` | D (EmbeddingGemma 2) | Unchanged command. Index the apply output, never the plain `items.jsonl`: `upsert` sets `n.text`, so the plain file would wipe approved alt text |

Proposal record: `{id, node, item, task, value, evidence: [{field} |
{span} | {pixels}], confidence, needs_review, review_reason, model,
model_digest, prompt, input_sha, created}`.

Model tasks:
- **Alt text and long description** (`vision`): refactor
  `alt_text.describe` into `describe_bytes(data, media_type, context,
  system, data_class)`; a collection prompt with the record's title,
  description, creator, date, place, holder and language. Describe what is
  visible; name people only if the metadata names them; never infer
  ethnicity, gender or disability; period terms only as quotes from the
  metadata. Reuse `_check`, `_clean`, `KINDS`, `ALWAYS_REVIEW`,
  `MAX_ALT_CHARS`. A deterministic unsupported-specifics check flags
  capitalised names and years in the draft that the metadata lacks.
  Measure seconds per image with thinking on and off (`THINK["vision"]` is
  on today) before sizing a batch.
- **Language tag**: deterministic mapping first; model fallback only when
  no tag exists (`workers.LANGUAGE_SYSTEM`, `classification`, thinking off).
- **Subjects, places, people from free text**: only for descriptions over
  200 characters with no source concept or place; JSON with spans,
  `call_analyst.check_spans` drops unsupported items; links to an existing
  `Concept`/`Place` only on an exact normalised same-language label match;
  all reviewed.
- **Reading level**: LIX, our own few lines, labelled indicative.
- **OCR** (R17): section 4.

## 4. Models

| Task | Model | Licence | Register | Laptop (RTX 2050, 4 GB) / inference box |
|---|---|---|---|---|
| Embeddings, all modalities | `google/embeddinggemma-2` | Apache-2.0 | D7, `MODELS` | both; unchanged |
| Alt text, long description | `gemma4:e4b` (`CAMPUS_AI_MODEL_VISION`) | Apache-2.0 | `MODEL_LICENCES`; add to the D10 vision row | both. `e2b` is the floor in R16; `12b` on the box only if `e4b` scores under 3.5/5 |
| Language fallback, entity spans | `gemma4:e4b` (`classification`, thinking off) | Apache-2.0 | yes | both |
| OCR, collections (printed, tables, hard pages, handwriting) | `allenai/olmOCR-2-7B-1025` (FP8 variant where the GPU supports it), fine-tuned from `Qwen/Qwen2.5-VL-7B-Instruct` | Apache-2.0 (model card metadata; base model Apache-2.0; checked Oct 29) | **New:** D10 row, `MODELS` row, router task in R17 | box only (8B; needs an NVIDIA GPU). Served by a pinned vLLM service (`vllm/vllm-openai`, Apache-2.0) on the internal network, weights from `MODELS_DIR`, called through the router's `ocr` task with its data-class gate and trace. olmOCR-Bench 82.4 (FP8) |
| OCR, laptop and CPU path | `gemma4:e4b` (`vision`) reading the page image | Apache-2.0 | yes | both. Every page goes to review, labelled machine-read |
| Transcripts, captions (R18, stretch) | `google/gemma-4-E4B-it` audio via transformers in the `embed` image, 30 s chunks | Apache-2.0 | **New:** D10 + `MODELS` rows | GPU preferred. Ollama's gemma4 accepts text and image only |
| ASR fallback (only if Gemma fails the WER bar) | `openai/whisper-large-v3-turbo` + faster-whisper + CTranslate2 | MIT (confirm each) | rows only if used | either |
| Eval judge | `qwen3:8b` against the specialist's reference; `qwen3-vl:8b` where there is no reference | Apache-2.0 | allow-listed, D10 judge row | box preferred; trusted after kappa ≥ 0.6 (B5) |

**Why olmOCR 2 and not a Google model for OCR:** no Gemma 4 OCR variant
exists under Apache-2.0, and a document-OCR model trained for it reads
tables, equations, multi-column pages and handwriting better than a
general vision model. R17 runs a bake-off (olmOCR 2 against `gemma4:12b`
and `gemma4:e4b`, character error rate on the R12 OCR pages) so the choice
is measured, not assumed. Tesseract stays in the image for Course Access
(A7) until that bake-off says whether A7 should move too.

**Never used:** Chandra OCR 2 (weights under a modified OpenRAIL-M licence
with a revenue threshold and a no-competition clause; code Apache-2.0, weights
not open source), Gemma 1-3, Gemma 3n, EmbeddingGemma v1, PaliGemma,
ShieldGemma (all Gemma Terms of Use), MedGemma, TranslateGemma, Ollama
`-cloud` tags (already refused by `OLLAMA_NO_CLOUD=1` and `MODEL_LICENCES`),
pyannote, fastText language-ID weights.

The EmbeddingGemma 2 and Gemma 4 cards ask deployments to follow Google's
Prohibited Use Policy; olmOCR 2's card points to Ai2's Responsible Use
Guidelines. Both are usage notes, not licence terms: the licence is plain
Apache-2.0. The register records the wording so a future change is
noticed.

Pinning: record each Ollama tag's digest (`ollama show`) and each Hugging
Face revision in the eval report and D10.

## 5. Sources

| Source | When | Rule |
|---|---|---|
| Europeana | now | `reusability=open`, `is_open`, R10. Full-size media (`shown_by`) only when the web resource's rights, or else the item's, are open; size cap (R17) |
| Wikimedia Commons | R19, after R14 | Per-file licence filter; structured data CC0, descriptions CC BY-SA. `depicts` (P180) Wikidata ids merge onto `wd:` Concepts |
| DPLA, Internet Archive | later, one card each | per-item open rights only |
| Canadiana, SFU Summit, other institutional repositories | only after a permission note in the plan | no code before that |
| **ArcaBC** | **blocked on R0b, then R7, then R21** | No code, fetch or index touches arcabc.ca before BC ELN signs, and nothing above depends on it. R7 writes `source`, `rights`, `access`, `tk_labels`; R21 only configures enrichment. Class R (access limits, TK Labels) is never described. Whether OCAP needs community review is for BC ELN |

Authority files: only the URIs found in Europeana's CC0 metadata are
stored (Wikidata, AAT, GeoNames as identifiers). No AAT, GeoNames or VIAF
data is loaded (D18).

## 6. Human review

Always an explicit approve or edit, never auto-applied: alt text and long
descriptions, model language tags, model subject/place/person links, all
model OCR pages (olmOCR 2 and Gemma), transcripts and captions, decorative
calls.

No review: mapped source fields (provenance shown; audited by the R12
link-precision sample), LIX, `access_mode`.

Machine-read OCR text may be indexed for search before review (D13),
shown as "machine-read, unreviewed", never counted as an accessibility
feature, never exported.

Queue order (sorting only; everything is reviewed): failed deterministic
checks, `ALWAYS_REVIEW` kinds, low confidence, the rest. Per D6 the
accessibility specialist reviews alt text and descriptions, the librarian
reviews facts, links and sensitive images (which always carry a content
note). The review page meets WCAG 2.2 (keyboard, labels, no colour-only
status). The reviewer's name is stored with each decision; the app is a
local single-machine tool with no logins.

## 7. Evaluation (`evals/collections/`, `core/eval`, dated reports)

Gold sets are provisional until the D6 labels exist (D15).

- **Retrieval:** 50 librarian queries (at least 10 lay-language or
  description-style); recall@10 and MRR per language on today's mapping,
  R11's mapping, and R11 plus approved alt text. Bar: +0.05 recall@10 with
  no language falling.
- **Alt text:** 50 open Europeana images, stratified (photo, print or
  drawing, map, document scan, object), specialist reference and 1-5 rubric.
  Reviewer mean (pass 3.5/5), accepted unedited, edit distance,
  unsupported-specifics rate, seconds per image (thinking on/off), judge
  score. Experiment: does the EmbeddingGemma 2 image-to-alt cosine predict
  rejections?
- **Metadata:** 50 items with languages, date range, concepts and places
  with URIs. Deterministic mapping first (expect near 1.0), then entity
  proposals: precision, recall, span-drop rate. Bar: D14. Includes a hand
  audit of Europeana's own concept links.
- **OCR:** character error rate on about 20 pages (provider fulltext where
  it exists, else hand transcription), for olmOCR 2, `gemma4:12b` and
  `gemma4:e4b`; seconds per page on the box and the laptop.
- **ASR:** word error rate on about 20 clips per supported language; skip
  rate.
- **Coverage, every run:** % Images with approved alt; % Items with a
  concept, a place, a date range and a language; % Items with any
  `a11y_features`; queue size and minutes per reviewed item.

## 8. Fix before the cards that touch them

Found by the judge; no design or evaluator raised them.

1. The Europeana API key would leak into `raw.jsonl` (`guid`, `link`):
   drop `link`, strip `guid`, rotate the key (D19).
2. Reusing the Course Access queue would auto-apply `needs_review=False`
   proposals: collections need an explicit decision for every output.
3. Re-indexing the plain `items.jsonl` wipes approved alt text: index the
   apply output.
4. `DATA_DIR` is read-only in `test`, `embed` and `api`: proposals and
   decisions need the writable `${DATA_DIR}/enrich` mount.
5. `rights.UNITS` must include `Text`, `Audio`, `Video` before any such
   node exists, or they pass as metadata without an open-rights check.
6. The rights screen runs before any model call, with each node's own data
   class.
7. `THINK["vision"]` is on: measure alt-text and OCR throughput with
   thinking on and off before sizing batches.
