# campus-ai oral history and handoff

Written Oct 22, 2026 by the coordinating Claude Code session that started
the project, for the session that takes over. It tells the story so far, the
standing orders, how the multi-agent harness is run, where things are, and
what is open. Read it once in full, then work from
`docs/plans/master_plan.md` (source of truth for scope, decisions and task
cards) and `AGENTS.md` (rules every session follows).

Section 2b and the laptop, key-incident and build notes in sections 3-7 were
added the same day by the build session (P7 through A2), which ran in the
cloud and then on the user's Windows laptop.

If anything here conflicts with `AGENTS.md`, the plan, or a newer message
from the user, those win. Update this file when the story moves on.

---

## 1. Who and what

- **The user** is the founder of Teamworx (GitHub org `teamworxAI`, personal
  account `adamsalah13`). Use they/them. They work largely from a phone, so
  keep chat replies short and give links. An earlier Teamworx HR assistant
  was a hit at Web Summit Vancouver; Teamworx is now taking work to **Web
  Summit Lisbon (early to mid November 2026; confirm exact dates)**.
- **The product repo** is `teamworxAI/campus-ai` (private, Apache-2.0). Two
  products for higher education in BC/Canada and the EU:
  1. **Course Access Agent**: makes course materials (PDF, PPTX, DOCX)
     accessible (WCAG 2.2 AA, Accessible BC Act, EU Web Accessibility
     Directive / EN 301 549): parse, deterministic audit, fix workers,
     rebuild, verify loop, human review.
  2. **Research Assistant**: an AI layer over SFU's Research Expertise Engine
     (REE) for expert and supervisor search, EU partner and Horizon Europe
     call matching, plus multimodal collections search over ArcaBC (BC) and
     Europeana (EU).
- **The other repo** is `sfu-aria/student-assistant`: an SFU graph-RAG
  academic advisor prototype (Neo4j, Ollama, RAGAS). campus-ai copies **no
  code** from it (decision D1, IP reasons); it only reuses the patterns.

## 2. How we got here (timeline)

**Oct 2: ideation.** The user asked for five ideas to build in four weeks
with Max-subscription agents, for an EU-collaboration panel rooted in BC and
Canadian markets. First pass misread the brief (built *about* EU
collaboration). Corrected: EU/BC/Canada is the lens for picking products.
Second pass gave five cross-market products (pay transparency, accessibility,
multilingual frontline workforce, supplier sustainability questionnaires,
privacy and AI governance). The user then zoomed in on **higher education**;
five higher-ed ideas followed (academic advisor, credit transfer, international
student journey, accessible course materials, research partnership matcher).
The user picked the **last two**.

**Oct 2: master plan.** First drafted in the SFU repo (branch
`ccr-b486116f-phsbvu`, file `docs/plans/higher_ed_master_plan.md`; still there,
the user was offered its removal and has not answered). Decisions then:
D1 new repo `teamworxAI/campus-ai`, clean build; D2 (later reversed) Claude
via in-region cloud.

**Oct 2-7: scope grows.** The user pointed to **SFU REE**
(sfu.ca/research/researcher-resources/resources/research-expertise-engine.html),
which they had planned to AI-enable: it became the Research Assistant's pilot
(REE is run by SFU's Research Intelligence team, RIO, rio@sfu.ca). Then
**ArcaBC** (arcabc.ca, run by BC ELN) and multimodal content, and Google's
**EmbeddingGemma 2** (released Oct 6, 2026; 740M, Apache-2.0, text, image,
audio and video in one space, Matryoshka 768 to 128 dims). Research Bridge was
renamed **Research Assistant**; Europeana added as the EU counterpart.

**Oct 7: repo and first cards.** The Claude GitHub App cannot create repos in
the org (403), so the user created `campus-ai` by hand and installed the app.
The coordinator pushed the plan, built P0 (skeleton + SessionStart hook,
PR #1) and spawned three cloud sessions in parallel: P1 LLM router (#2), P7
embedder (#3), A1 parser (#4). The A1 session refused to open its PR on a
cross-session request (correctly: it was not user input); the coordinator,
holding the user's approval, opened #4 itself.

**Oct 7: deep research.** The user asked for research on models similar to
EmbeddingGemma 2 and a fit-for-purpose multi-model workflow. Five research
subagents + one writer produced `docs/research/multimodal_model_stack.md`.
Key finding: **no Claude option keeps processing inside Canada** (Anthropic
API only global/us; Bedrock `ca-central-1` only Global/US profiles). Many
figures came from search snippets because the cloud proxy blocked Hugging
Face, arXiv and several vendor sites; the report flags them.

**Oct 7-21: quiet for the coordinator, busy for the build session.** Check-ins
found nothing for a day and were stopped. Meanwhile the P7 session kept going
with the user and became the main build session (its own account is in
section 2b): it built P5 graph core (#5), R8 Europeana loader (#6), the
architecture/design/user/build guides (#7), R9 collections search API + web
UI (#8) and P8 licence guard (#9), first in the cloud and then on the user's
Windows laptop, where the app now runs. On **Oct 21** the user set two **prime directives** (open source only;
everything offline, no cloud model APIs) and acted on them: #10 made the
router local-only on Ollama with a licence allow-list (Claude/Bedrock
removed); #11 rebuilt A1 on pdfplumber because PyMuPDF is AGPL; #12 merged the
stack and enforced the directives; #13 added the A2 WCAG audit.

**Oct 21-22: merges and plan update.** The coordinator resolved dependency
conflicts on #4 twice (merge commits, relocking without upgrading packages),
then opened #14: the research report plus plan edits adapted to the
directives (data classes P/I/S/R, model register D10, bake-offs B1-B6, cards
P1b, A1b, A3b, A4b, R10). #14 conflicted with #12/#13; resolved by keeping
main's decisions and adding only new material. All of #1-#14 are merged.
Data-agreement emails to RIO and BC ELN were drafted (appendix) for the user
to send. Oct 22: docs refresh and this handoff.

## 2b. The build session's account (Oct 7-22)

Written by the session that built P7 through A2 (it began as the P7 cloud
session, `session_011pDwrLJtoRT9pGzLDkr5wA`, and continued on the user's
Windows laptop). It covers what the summary above can't: why things are the
way they are.

**P7 embedder: from "use Hugging Face" to "everything offline in Docker".**
- The cloud proxy blocked Hugging Face, so the first PR was text-only and
  flagged as unverified. Once the user allowed the domain, the model card
  confirmed the API: prompts `SearchQuery`/`Document`, Matryoshka
  768/512/256/128, media passed without prompts, never float16.
- The user then set the first standing order: **everything in Docker,
  portable, no host virtualenvs** (Oct 8). A host venv and model cache were
  deleted.
- A detour: the user asked for models "on metal" via vLLM/Ollama on their box.
  The embedder was rewritten as an HTTP client, but vLLM 0.31.0 lacks
  `EmbeddingGemma2Model` and Ollama on Windows lacks the needed multimodal
  support, so the user reversed it ("if ollama is not supported keep the
  docker images"). The embedder runs in the `embed` image from a read-only
  `MODELS_DIR`; only `fetch-models` downloads.
- The user's "DGX box" turned out to be a misunderstanding: that session ran
  in an Anthropic cloud container, not on their hardware. Lesson: say plainly
  where a session runs.

**P5 graph core.** Neo4j Community on an `internal` Docker network shared
with the model container (models can reach Neo4j, never the internet).
- Every searchable node is `Entity` + its own label, a 128-d vector (indexed)
  and a 768-d vector (rerank). Vector and fulltext rankings fuse by RRF k=60.
- Two bugs found on real data, both fixed: French queries matched every
  French document on "de"/"et" (fix: stop words in 7 languages, applied at
  query time), and label filtering ran after the index's top 50, so
  `--label Image` came back empty (fix: label stored as `kind`, filtered
  inside the vector index; `ensure_schema` migrates old graphs).

**R8 Europeana.** The user gave an API key in chat. Harvest query precision
was measured by reading every title: plain `salmon` was about half noise
(people named Salmon, salmon-coloured fashion, herbarium sheets named after
botanist C.E. Salmon, specimen photos). The final query (species subjects +
"salmon fishing" phrases in 7 languages, no specimens) gives 151 items, about
95% on topic. Only CC0, PDM, CC BY, CC BY-SA kept; 400 px thumbnails.

**The key incident (still open).** Europeana's `guid` URLs carry the API key
in `utm_campaign`. The harvest file was committed by mistake on the P5 branch
(that branch's `.gitignore` predated the rule) and pushed. The loader now
strips URL parameters and the folder is untracked, but the commits remain:
commit `88a56e9` is in `main`'s history via #12. The user chose not to
rewrite history. **The key must be rotated** (see section 6).

**R9 collections search.** FastAPI `api` service (model + Neo4j, internal
network) behind nginx `web`, the only published port (`127.0.0.1:8080`).
- Pictures and texts are ranked as separate lists: a text query always sits
  closer to text than to images, so a merged list buried the pictures.
- Image search always returns the nearest pictures, so an unrelated upload (a
  Greek newspaper the user tried) got unrelated results with no warning.
  Calibrated on 10 probes: unrelated images peak at cosine 0.68-0.72,
  salmon/fishing images from outside the index 0.80-0.86, indexed images 1.00.
  Thresholds: same picture >= 0.98, similar >= 0.76, else "no close match",
  shown with the uploaded picture.
- Resilience after the user asked for it: `restart: unless-stopped` and
  health checks; nginx re-resolves `api` per request; each image built by one
  service only. Tested: api recreated on a new IP, api crash (back in ~24 s),
  Neo4j restart (search back in ~3 s).

**Windows laptop deployment (Oct 20-21).** The user moved the work to their
laptop (Windows 11, Docker Desktop, NVIDIA RTX 2050 4 GB, C: small, D: 545 GB
free). Large files live on D: (`MODELS_DIR=D:/models`,
`DATA_DIR=D:/campus-ai/data`); `C:\models` kept for other projects. Indexing
the pilot: 17 min on 4 CPU cores in the cloud, **80 s on the RTX 2050**.
Other projects run on this Docker (e.g. `sfu-site`): never restart Docker
Desktop or prune globally without asking.

**Prime directives (Oct 21).** Triggered when the session suggested a
PyMuPDF commercial licence and Claude as the vision model. The user's answers
to the follow-up questions: free GPU vendor runtimes allowed (CUDA is 16
proprietary packages in the `embed` image); PyMuPDF replaced, not licensed;
Apache-2.0 for the repo; Docker Desktop allowed on Windows dev workstations
(first ruled out, then made an exception by the user). Ollama is the model
server: **local on the laptop now, a dedicated inference box in the team
environment later** (`OLLAMA_HOST`). Gemma 3 was dropped as a default (Gemma
Terms of Use); Gemma 4 is Apache-2.0 per its Ollama registry licence layer.

**The stacking mistake.** P5-R9 were opened as stacked PRs (each on the one
below). The user merged each into its base branch, so the work stopped at
`p8-licence-guard`, while #4 (PyMuPDF A1) and #2 (Bedrock router) went into
`main`. #10 and #12 repaired it. Rule since then: PRs go against `main`; if
one depends on an unmerged PR, open it as a draft against `main` and say so.

**A1 and A2.** A1 rebuilt on pdfplumber (MIT): PDF order is now by position
on the page, images are PNGs of their page area, lines join into paragraphs.
A2: 15 rules over 7 WCAG 2.2 criteria, each naming its fixer; every report
lists what the checks can't judge. A messy sample handout with 7 planted
problems: all 7 found, no false positives. Neither has met real course
documents yet.

## 2c. The laptop session (Oct 22-23)

Written by the session that ran on the user's laptop after the handoff,
from "read the plan and iterate". Fourteen PRs in a day; the user merged in
bursts and said "proceed" or "continue". What was built, in merge order:

- **P9 Ollama in compose** landed through #19 (a parallel cloud session got
  there first; this session's #20 was closed and its laptop fixes folded into
  #19): the `ollama` service on the internal network, `fetch-ollama`, the
  B1 smoke test passing 9/9 on the laptop. Lesson: check `gh pr list` before
  starting a card; sessions run in parallel.
- **A3 alt text** (#21), **A6 corpus** (#22: 20 CC BY documents from Canadian
  and UK OER repositories via `fetch-course-docs`), **A1 fix** (#23), **A4
  workers** (#24), **A5 rebuild and verify** (#25): the Course Access pipeline
  runs end to end; on the corpus 862 audit issues became 360 with rule-based
  fixes alone and 0 introduced. Every proposal carries a confidence, a review
  flag and its evidence; the small model reports confidence 1.0 for almost
  everything, so the deterministic routing is the real guard until B3.
- **P3 review queue** (#26): a FastAPI service and a static page at
  `/review/`, not Streamlit (decision: no new dependency, same stack as R9).
- **R1 OpenAlex** (#27), **R2 CORDIS and calls** (#28), **R4 expert, partner
  and call search** (#29), **R5 consortium rule and citation-checked brief**
  (#30): the Research Assistant's Experts, EU partners, Horizon calls and
  Draft-a-consortium pages work on the laptop over 3000 SFU works and the
  full Horizon Europe bundle (24k projects, 36k organisations, 3808 call
  topics). The R6 back-test gives recall@10 0.32 on the full graph.
- Two core fixes found by indexing the full bundle, independent PRs: #31
  (JSONL loaders split on newlines only; CORDIS objectives contain U+2028)
  and #32 (the R10 rights screen dropped every node of a graph without
  collection items).

The user gave an OpenAlex API key in chat on Oct 23; it is in the laptop's
`.env` only. It is also in that session's transcript, so rotate it if the
transcript is ever shared.

All of it (#19 to #33) was merged by the end of Oct 23; `main` has 186
unit tests passing. The user asked, after the first PR cited a report they
could not find locally, that everything cited in a PR be committed in the
repo: eval reports are, data under `DATA_DIR` and `.env` are not, by the
rules in `AGENTS.md`.

## 3. Standing orders

These carry over to any session working for this user on campus-ai.

**From the user**
1. **Never egress sensitive information without asking first.** Nothing about
   people, institutions or private data goes to an outside service (web
   search, APIs, other repos) without the user's OK. Public facts are fine.
2. **Prime directives** (master plan, top; they override everything):
   - **Open source only, no paid licences.** OSI-approved licences for all
     code, dependencies, images, tools and model weights; permissive
     preferred; no AGPL; "community" model licences do not qualify. Two named
     exceptions: free GPU vendor runtimes (optional, CPU path always works)
     and Docker Desktop as a Windows developer tool. Enforced by
     `tests/test_licences.py` (P8) and the router's `MODEL_LICENCES`.
   - **Everything runs offline.** Models run locally from open weights; no
     cloud model APIs (no Claude, OpenAI, Gemini, Bedrock) in the product;
     nothing downloads at runtime; only explicit one-time `fetch-*` jobs touch
     the network. Building with Claude Code is the dev process, not the
     product.
3. **Keep it simple** (`AGENTS.md`): every change should make the codebase
   simpler; add complexity only when strictly necessary.
4. **Everything in Docker, portable, rebuildable on another box** (Oct 8):
   no host virtualenvs or host-installed models; add dependencies with `uv`
   inside a container. On the user's laptop, big files go on D:.
5. **Model servers:** Ollama for language and vision models (laptop now,
   dedicated inference box in the team environment); the embedder runs in the
   `embed` container because no server supports EmbeddingGemma 2's media.
6. **ArcaBC is off-limits** until BC ELN grants permission (card R0b): no
   code or session fetches, scrapes or indexes arcabc.ca. REE data likewise
   waits for RIO (R0); use public OpenAlex/ORCID meanwhile.
7. **No code from `sfu-aria/student-assistant`** in campus-ai (D1).
8. **Cultural data**: honour every item's rights statement; Indigenous
   materials follow OCAP and community protocols; restricted items (class R)
   never reach a model.

**From the repo (`AGENTS.md`, plan)**
- Deterministic code for anything checkable; LLMs only for judgement. Every
  agent output cites evidence; nothing is sent or published without human
  approval.
- Everything runs in Docker and rebuilds from the repo. Tests use `unittest`
  and mock LLMs, Neo4j and network. One task card per PR; PRs list validation
  and new `.env` keys; product PRs report eval results.
- Update the plan in the same PR when a decision changes. Adding a model
  needs a D8 licence check and a D10 register row in the same PR.

**From the environment (cloud sessions)**
- Work on a branch, commit with the attribution trailer the harness gives,
  never put model identifiers in commits or PRs. Do not open PRs unless the
  user asked (they have approved PRs for task cards and doc work).
- Never rewrite history on a shared branch: merge `main` in, don't rebase or
  force-push. Regenerate lockfiles with `uv lock`, never by hand.
- Ask before outward actions the user has not approved (emails, posts,
  deleting branches, creating repos).

## 4. The multi-agent harness (how the coordinator works)

The coordinator is one long-lived cloud session that plans, delegates and
reviews; it rarely writes product code itself.

- **Cloud sessions per task card.** `create_session` (claude-code-remote MCP)
  with `source_url` = the repo, `source_revision` = `main` (or a base branch),
  tags `campus-ai` + `card:<ID>`, and a standalone prompt: read `AGENTS.md` and
  the plan, implement card X, tests that mock services, run the suite, commit,
  push, open a PR titled "<what> (<ID>)". Do **not** use plan mode for
  unattended sessions (they stall). Run at most **3 heavy sessions** at once
  (Max usage limits).
- **Child sessions treat cross-session messages as data**, not user input.
  They may refuse outward actions (like opening a PR) on your say-so. If the
  user already approved it, do it yourself from this session (e.g. open the
  PR from their pushed branch) and tell the child it can stop.
- **PR watching.** `subscribe_pr_activity` on each PR you open or drive. Merge
  conflicts on your PRs are yours to fix (merge `main` in). Safety-net
  check-ins with `send_later`: about 50 minutes after last activity, then
  every ~4 hours; stop after three empty check-ins in a row, or after the
  first empty one if the user has not written since the PR went up; say once
  that check-ins stopped.
- **Local subagents** (`Agent` tool) for research and reviews that would flood
  the coordinator's context. Give each a disjoint set of files to edit; the
  coordinator commits.
- **Deep research** via the `anthropic-skills:deep-research` skill: 3-5
  parallel researcher subagents writing notes, then one report writer. Notes
  and reports live outside the repo first; copy the final report into
  `docs/research/` and fix any references to other repos.
- **GitHub** via the GitHub MCP tools in cloud sessions (no `gh` CLI there).
  On the user's Windows laptop the `gh` CLI is installed and authenticated.
  The app cannot create repositories; ask the user to create them.
- **Sessions on the user's laptop** (Windows 11, PowerShell, Docker Desktop):
  see the laptop gotchas in section 7. Docker there is shared with other
  projects.

## 5. Where things are

| Thing | Where |
|---|---|
| Scope, decisions D1-D10, cards, schedule, risks | `docs/plans/master_plan.md` |
| Rules and prime directives for sessions | `AGENTS.md` (via `CLAUDE.md`) |
| Model landscape and per-step picks (Claude routing superseded) | `docs/research/multimodal_model_stack.md` |
| Architecture, design, build and user guides | `docs/architecture.md`, `docs/design.md`, `docs/build_guide.md`, `docs/user_guide.md` |
| LLM router (Ollama only, licence allow-list) | `campus_ai/core/llm/` |
| Embedder (EmbeddingGemma 2 + e5 baseline) | `campus_ai/core/embed/`, `scripts/embed_bakeoff.py`, `scripts/fetch_models.py` |
| Graph core (Neo4j store, hybrid retriever) | `campus_ai/core/graph/`, `scripts/graph_search.py` |
| Course Access parser and audit | `campus_ai/course_access/`, `scripts/audit_document.py` |
| Europeana loader, collections search API, web UI | `campus_ai/research_assistant/`, `scripts/fetch_europeana.py`, `web/` |
| Licence guard | `tests/test_licences.py` |
| Course Access workers, rebuild, review queue | `campus_ai/course_access/{alt_text,workers,rebuild,api}.py`, `scripts/{alt_text,propose_fixes,remediate}.py`, `web/static/review/` |
| Research Assistant loaders and journeys | `campus_ai/research_assistant/{openalex,cordis,matching,consortium}.py`, `scripts/fetch_{openalex,cordis}.py` |
| Eval runs and reports (dated) | `evals/course_access/`, `evals/research_assistant/`, `evals/smoke/` |
| Docker | `Dockerfile`, `compose.yaml` (`test`, `embed`, `fetch-models`, `fetch-ollama`, Neo4j, Ollama, API, web, `smoke`), `compose.gpu.yaml`, `.claude/compose.cloud.yaml` |
| Cloud session hook | `.claude/hooks/session-start.sh` (starts Docker, builds `test` with `docker buildx bake`) |

**The running app on the user's laptop** (`C:\Repos\campus-ai`): Neo4j,
`api`, `course-access`, `ollama` and `web` with `restart: unless-stopped`;
http://localhost:8080 serves collections search over the 151-item salmon
pilot, the Experts, EU partners, Horizon calls and Draft-a-consortium pages
over 3000 SFU works (2226 researchers) and the full Horizon Europe bundle
(24k projects, 36k organisations, 3808 call topics; 71k nodes in the Neo4j
volume), and the Course Access review queue at `/review/`. Harvests live in
`D:/campus-ai/data/{europeana,course_access,openalex,cordis}`; Ollama's
weights in `D:/models/ollama` (`gemma4:e2b` only; `.env` points the three
router tasks at it). `.env` there sets `MODELS_DIR=D:/models`,
`DATA_DIR=D:/campus-ai/data`, `COMPOSE_FILE=compose.yaml;compose.gpu.yaml`,
`CAMPUS_AI_MODEL_*=gemma4:e2b`, `OPENALEX_API_KEY` and `EUROPEANA_API_KEY`
(the leaked one, until rotated). After pulling `main`, run `docker compose
build` and `docker compose up -d web ollama`, then `docker compose exec web
nginx -s reload` if the `web` container was not recreated; the graph in the
Neo4j volume needs no re-index unless the loaders change. Docker Desktop's disk
image is still on C:; the user can move it (Settings > Resources > Advanced)
when it suits them, since that restarts Docker and their other projects.
Bring the app back with `docker compose up -d web`.

Tests: `docker compose run --rm test` (the rule is Docker only, no host
virtualenvs). The coordinator has also used `uv run python -m unittest
discover -s tests` for quick checks inside its cloud container. On Oct 22,
82 tests pass, 4 skipped (PyAV or Neo4j needed). If the licence guard flags
`pymupdf`, that environment is stale: run `uv sync`.

## 6. Open items and next steps

**Waiting on people**
- **Rotate the Europeana API key** (urgent): it is in `main`'s history in
  harvest URLs (section 2b). Put the new key only in `.env`.
- Delete stale branches once the user agrees: `p5-graph-core`,
  `r8-europeana`, `docs-architecture`, `r9-collections-search`,
  `p8-licence-guard`, `a1-document-parser`, `a1-document-parser-open`,
  `p1-local-only`, `integrate-stack`, `a2-audit`, and from Oct 22-23
  `p9-ollama-compose`, `a3-alt-text`, `a6-course-corpus`,
  `a1-pptx-title-paragraphs`, `a4-workers`, `a5-rebuild`, `p3-review-queue`,
  `r1-openalex`, `r2-cordis`, `r4-matching`, `r5-consortium`,
  `fix-jsonl-line-separators`, `fix-rights-screen-research-graph`,
  `docs-handoff-oct23` (all merged).
- Models on the laptop: only `gemma4:e2b` is downloaded (via `fetch-ollama`,
  Oct 22). `gemma4:e4b` (7 GB) would improve alt text and the brief; the
  12B model belongs on the inference box (4 GB GPU here).
- Decide on NC-licensed course material for the A6 corpus (KPU Discrete Math
  slides, MIT OCW, LOUIS biology slides were found and left out); CUNY's CC BY
  lectures sit behind a bot check and need downloading by hand.
- Rotate the OpenAlex API key if the Oct 23 session transcript is shared.
- Gold-set labels (D6): 20 openly licensed course documents are harvested by
  `fetch-course-docs` (Oct 22) and audited (`evals/course_access/`); a
  specialist still has to label them. More CC BY documents welcome; NC-licensed
  sets (KPU Discrete Math slides, MIT OCW, LOUIS biology slides) were found but
  left out until the team decides on NC material.
- Send the RIO (REE) and BC ELN (ArcaBC) emails (drafts in the appendix; the
  BC ELN address still needs finding). Until answered, R0, R1's REE part, R7
  stay blocked.
- Confirm Web Summit Lisbon dates and the demo slot.
- Get GPU quotes for Canadian and EU inference boxes (none found in research).
- Verify licences marked "(verify)" in the D10 register on the model pages.
- Pick a diarization approach: pyannote Community-1 is CC-BY-4.0 and fails D8.
- Answer: remove the early plan copy on `sfu-aria/student-assistant` branch
  `ccr-b486116f-phsbvu`?

**Next cards** (section 5 of the plan, after the Oct 22-23 session; all of
that session's PRs are merged): P6 eval harness (the eval scripts under
`evals/` are the raw material); B2 embedder + reranker
bake-off (R3; the back-test script measures it); B3 alt-text bake-off once a
specialist labels the A6 corpus; R5's network worker once EU-side
researchers are in the graph; the call analyst over full topic descriptions
(the grants file has titles and keywords only); A4b OMML to MathML; A7 OCR.
Demo prep: the dry run on the laptop with everything indexed.

## 7. Lessons and gotchas

**From the Oct 22-23 laptop session**
- The `embed` image is only rebuilt when you ask. Core changes merged on
  `main` (R10's rights screen, for one) do not reach `docker compose run embed`
  until `docker compose build embed`; research-graph indexing "worked" for a
  day on a stale image. Rebuild `embed` after merging anything under `core/`
  or `research_assistant/`.
- Git Bash mangles container paths in `-v` mounts (`/app/x` becomes
  `C:/Program Files/Git/app/x`) and creates stray folders like
  `evals/course_access;C`. Use `MSYS_NO_PATHCONV=1` or PowerShell.
- A "reasoning" call to `gemma4:e2b` can think for over ten minutes on a
  trivial question; short answers go through the classification task. The
  brief (R5) uses reasoning and takes about two minutes on the laptop.
- OpenAlex meters its API: one small daily budget per IP without a key.
  CUNY Academic Works and some Pressbooks sites answer 403 to scripts.
- `str.splitlines()` cuts on U+2028 and NEL; JSONL must split on newlines.
- The harness's permission classifier blocked `gh pr comment` and
  `gh pr close` once; `gh pr create` and `gh pr edit` work.

**Earlier**

- The cloud proxy blocks huggingface.co, arxiv.org, sfu.ca, blog.google and
  others for web fetch; search snippets get through. Mark such facts
  unverified.
- `uv lock` after a conflict can silently upgrade packages (pymupdf 2.0 broke
  a table test once). Relock from the branch you trust and pin with
  `uv lock --upgrade-package 'name==version'`.
- The org's GitHub name is `teamworxAI` (case-insensitive).
- Research notes from Oct 7 live untracked in the SFU repo clone
  (`research_notes/`, `reports/`, excluded via `.git/info/exclude`); the
  final report is in campus-ai. Nothing else of campus-ai lives in the SFU
  repo except the early plan copy above.
- The user often reviews and merges in bursts and drives their own sessions;
  expect `main` to move under you. Fetch before every change.
- Don't stack PRs: the user merges each PR into its base branch, so stacked
  work never reaches `main` (section 2b). Target `main`; mark dependent PRs as
  drafts.
- Two compose services building the same image tag in parallel corrupts it
  ("failed to extract layer"). Each image now has one builder (`test`,
  `embed`); keep it that way.
- The `embed` image is about 10 GB (CUDA PyTorch). In the cloud container the
  disk filled three times; clear old images and build cache before rebuilding.
- `git add -A` once committed a harvest folder with an API key. Stage named
  paths and check that nothing under `data/` is staged.
- Measure retrieval quality by reading the results, not by the recall number
  alone: the salmon recall looked fine while half the items were off topic.

**On the user's Windows laptop**
- PowerShell runs in Constrained Language Mode: .NET method calls such as
  `.Substring()`, `.Contains()` on objects, and `[regex]::...` fail with
  "Method invocation is supported only on core types". Use operators
  (`-replace`, `-match`), cmdlets, or run Python in a container.
- Files are checked out with CRLF line endings: string replacements that
  assume `\n` silently miss. Use the Edit tool or `\r?\n` patterns, and check
  the result.
- PowerShell treats `;` as a command separator, so
  `echo COMPOSE_FILE=a;b >> .env` writes nothing useful; quote it.
- Docker Desktop runs other projects' containers (`sfu-site`): never prune all
  images or volumes, restart Docker, or reuse their ports without asking.

---

## Appendix: email drafts (not sent; the user sends them)

**To RIO (rio@sfu.ca): Research Expertise Engine, proposed AI search pilot.**
Proposes a natural-language layer on top of REE (expert search, supervisors
accepting students, EU partner and Horizon call matching), shown at Web
Summit Lisbon. Commitments: complement REE, respect profile choices, models
run locally in Canada with no profile data sent to external AI services,
every result cites its REE source, no outreach without human approval,
public OpenAlex/ORCID data only until an agreement. Asks for a call on
fields, access method and refresh, and SFU consent/privacy steps.

**To BC ELN (Arca contact to be found): proposed pilot for one collection.**
Proposes multimodal search over one openly licensed ArcaBC collection,
linked to researchers and Europeana, shown at Lisbon. Commitments: harvest
only through approved interfaces, store each item's rights statement,
exclude restricted items, TK-Labelled and community-protocol materials,
local open-source processing in Canada, results link back to ArcaBC,
generated descriptions only offered to librarians for approval. Asks for a
call on the pilot collection, harvesting method and terms, and institutional
approvals.
