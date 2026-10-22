# campus-ai oral history and handoff

Written Oct 22, 2026 by the coordinating Claude Code session that started
the project, for the session that takes over. It tells the story so far, the
standing orders, how the multi-agent harness is run, where things are, and
what is open. Read it once in full, then work from
`docs/plans/master_plan.md` (source of truth for scope, decisions and task
cards) and `AGENTS.md` (rules every session follows).

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

**Oct 7-21: quiet, then the user's own sessions.** Check-ins found nothing for
a day and were stopped. Meanwhile the user drove a stack of sessions that
added P5 graph core (#5), R8 Europeana loader (#6), architecture/design/user/
build guides (#7), R9 collections search API + web UI (#8), P8 licence guard
(#9). On **Oct 21** the user set two **prime directives** (open source only;
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
4. **ArcaBC is off-limits** until BC ELN grants permission (card R0b): no
   code or session fetches, scrapes or indexes arcabc.ca. REE data likewise
   waits for RIO (R0); use public OpenAlex/ORCID meanwhile.
5. **No code from `sfu-aria/student-assistant`** in campus-ai (D1).
6. **Cultural data**: honour every item's rights statement; Indigenous
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
- **GitHub** via the GitHub MCP tools (no `gh` CLI). The app cannot create
  repositories; ask the user to create them.

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
| Docker | `Dockerfile`, `compose.yaml` (`test`, `embed`, `fetch-models`, `fetch-ollama`, Neo4j, Ollama, API, web, `smoke`), `compose.gpu.yaml`, `.claude/compose.cloud.yaml` |
| Cloud session hook | `.claude/hooks/session-start.sh` (starts Docker, builds `test` with `docker buildx bake`) |

Tests: `docker compose run --rm test` (the rule is Docker only, no host
virtualenvs). The coordinator has also used `uv run python -m unittest
discover -s tests` for quick checks inside its cloud container. On Oct 22,
82 tests pass, 4 skipped (PyAV or Neo4j needed). If the licence guard flags
`pymupdf`, that environment is stale: run `uv sync`.

## 6. Open items and next steps

**Waiting on people**
- Send the RIO (REE) and BC ELN (ArcaBC) emails (drafts in the appendix; the
  BC ELN address still needs finding). Until answered, R0, R1's REE part, R7
  stay blocked.
- Confirm Web Summit Lisbon dates and the demo slot.
- Get GPU quotes for Canadian and EU inference boxes (none found in research).
- Verify licences marked "(verify)" in the D10 register on the model pages.
- Pick a diarization approach: pyannote Community-1 is CC-BY-4.0 and fails D8.
- Answer: remove the early plan copy on `sfu-aria/student-assistant` branch
  `ccr-b486116f-phsbvu`?

**Next cards** (section 5 of the plan): B1 passed on the demo laptop on Oct 22
(`docker compose run --rm smoke`, 9/9 with `gemma4:e2b`, report in
`evals/smoke/`; the laptop's user environment exports `OLLAMA_HOST`, which is
why compose reads `OLLAMA_URL` instead); P6 eval harness; A6 gold set and
A3 alt-text worker with bake-off B3 (D9); B2 embedder + reranker bake-off on
the salmon pilot; R10 rights filter. Then A4/A4b/A5, R1/R2/R3.

## 7. Lessons and gotchas

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
