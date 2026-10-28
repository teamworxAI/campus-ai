<!--
Web Summit Lisbon demo script. Working product names (decision D4: Teamworx
branding still to decide). Written Oct 27, 2026 from live checks against the
demo laptop's stack (main's code). Steps marked AFTER MERGE describe open PRs
(#35 to #39) and were NOT verified live.
-->

# Demo script: Course Access Agent and Research Assistant

For the presenter, on the demo laptop (Windows 11, Docker Desktop, RTX 2050
4 GB), **with no venue Wi-Fi**. Everything below runs from the laptop alone:
that is part of the story. Documents, queries and calls are in
[`sample_pack.md`](sample_pack.md).

Two lines to be able to say at any point:

- **"Open source, no paid licences, and every model runs on this laptop, with
  the network off."** (Prime directives. Only one-time `fetch-*` jobs ever
  touch the internet, and they were run before the trip.)
- **"It proposes; a person approves. Nothing is sent or published by itself."**

Total: Course Access under 2 minutes; Research Assistant about 6 minutes plus
the brief (start it early, see B5).

---

## 0. Pre-flight (do this at the hotel, then 10 minutes before the slot)

Run from `C:\Repos\campus-ai` unless noted. Checks are read-only except where
stated.

| # | Check | Command or action | Good looks like |
|---|---|---|---|
| 1 | Docker Desktop is running, stack is up | `docker ps` | `campus-ai-web-1`, `-api-1`, `-course-access-1`, `-ollama-1`, `-neo4j-1` all `healthy` |
| 2 | **Reload the web proxy** (needed after the stack was last created before the review queue's proxy rule; verified Oct 27: without it every Course Access call returned 404) | `docker compose exec web nginx -s reload` | no error |
| 3 | Research API and graph | `curl -s localhost:8080/api/health` | `{"status":"ok","items":151,"graph":{"Researcher":2226,"CallTopic":3808,"Project":23954,"Organization":35625}}` |
| 4 | Course Access API through the proxy | `curl -s localhost:8080/api/course-access/health` | `{"status":"ok","jobs":0}` (if you see `{"detail":"Not Found"}` repeat step 2) |
| 5 | Model is downloaded | `docker exec campus-ai-ollama-1 ollama list` | `gemma4:e2b` |
| 6 | **Warm the language model.** Ollama unloads an idle model after 5 minutes, and the first call pays the load time | `docker exec campus-ai-ollama-1 ollama run gemma4:e2b "Say ok"` | an answer within about 20 s |
| 7 | **Warm the embedding model and the graph.** The first search after idle took 23 s on Oct 27 (later ones under 2 s) | Run one expert, one call, one partner and one collections search (section B), or the four `curl`s in sample_pack.md | each answers in seconds |
| 8 | Quiet laptop | Close other Docker projects' heavy jobs (on Oct 27 other containers on this machine used all the CPU and slowed everything 3 to 5 times). Power plugged in, sleep disabled | |
| 9 | **Start the brief now** (see B5) so the result is ready | | |
| 10 | Stage the sample files in a folder you can find in a file picker, e.g. `C:\demo\` (see sample_pack.md) | copy from `D:\campus-ai\data\course_access\...` | |
| 11 | Browser tabs, in this order, all at `localhost:8080` | 1: `/#/experts` 2: `/#/calls` 3: `/#/partners` 4: `/#/` (Collections) 5: `/review/index.html` | each loads. **Use the full address `/review/index.html` for tab 5:** on Oct 27 `/review/` and the "Course Access" link in the top bar both showed the Collections page instead |
| 12 | Wi-Fi off. Reload each tab once to prove nothing needs the network | | everything still loads |

---

## A. Course Access Agent (under 2 minutes)

**Setup:** tab 5 (`/review/index.html`), queue empty ("No documents yet").
Document: `presentations-lecture-notes.docx` (Professional Communications OER,
CC BY 4.0). 282 paragraphs, no document title, 8 lists typed by hand with
bullet characters, 2 bare web addresses as link text, 1 image with no
description. The audit finds 12 issues (corpus run, Oct 22).

| Time | Do | What appears | Say | If slow or broken |
|---|---|---|---|---|
| 0:00 | Say the problem. Click **Choose file**, pick the DOCX, tick **Also propose alt text (vision model)**, leave class **I**, click **Audit and propose** | A notice "Reading the document and proposing fixes (the alt-text model takes about 20 s per image)" | "A lecturer's lecture notes. Twelve accessibility problems under WCAG 2.2 AA, which is what the Accessible BC Act and the EU's EN 301 549 point to. Everything you see runs on this laptop, offline." | Expect about 30 to 60 s: the corpus run took 32 s for this file's proposals plus about 15 to 20 s for the one image. Fill the wait with the regulatory sentence. If more than 90 s, switch to the fallback below |
| 0:45 | The job page opens: counts for issues found, proposals, need a person, decided | **12 issues found**, grouped proposals: Structure, Tables, Text, and one **Alt text** card with the image next to it | "Each fix has a confidence and its evidence. Rules do what can be checked. The model is used only for judgement, like describing this picture." | |
| 1:00 | Open one **Structure** card (typed list to real list) and one **Text** card (link text). Click **Approve** on the link text | The card shows the evidence and confidence; button turns to "Approved" | "Anything the system is unsure about waits for a person. Charts, diagrams and equations always do." | Skip the second card |
| 1:20 | On the **Alt text** card read the proposal, edit a word if you like, click **Approve** | Alt text in the box beside the image | "I approve the meaning; the system never decides that alone." | If the model gave nothing, click **Reject**: the story is the same |
| 1:30 | Click **Build the accessible version** | Numbers: issues before, after, applied, still waiting, newly visible | "The result is audited again with the same checker. Twelve before, around zero after on the corpus run." | Do not promise exact numbers on this live run; read what is on screen. Rebuild took about 18 s in the corpus run |
| 1:50 | Click the download buttons: the `.docx`, the `.html` and the `-statement.md` | Files named `presentations-lecture-notes.docx`, `.html`, `-report.md`, `-review.md`, `-statement.md` | "An accessible DOCX and HTML, the report by WCAG criterion, and a short conformance statement: what was found, applied, left, and what no tool can check." | Open the statement in a text viewer, not Word, to avoid Word's own startup |

**Fallback if the upload is slow, or the model hangs:** upload without the
alt-text box ticked (rules only, a few seconds), or use a slide deck:
`presentations-slides-Your Presentation Style Slide Deck.pptx` (20 slides,
19 issues, rebuild in under a second; the corpus run applied 10 and left 8,
all images that need descriptions, which is a good talking point: "these wait
for a person"). **Do not tick alt text on a deck with many images**: about
20 s each, 9 images is 3 minutes. **Do not demo a long PDF live**: the
corpus run took 108 s for a 26-page PDF and 330 to 390 s for the two
e-textbooks.

**Not verified live:** the whole Course Access flow was not run (the
instructions for this document were: do not run remediation). What was checked
on Oct 27: the `course-access` service is healthy (`{"status":"ok","jobs":0}`
from inside its container), the page files are served, and the proxy rule was
found stale (pre-flight step 2). Do one full rehearsal on the laptop, and
watch for the "newly visible issues" number: the corpus report shows 2 issues
introduced across 862 (both in one PDF), so the honest line is "target zero".

---

## B. Research Assistant (about 6 minutes plus the brief)

Data behind it, say once: **public OpenAlex records for SFU authors stand in
for SFU's Research Expertise Engine** (2,226 researchers, 3,000 recent works),
the EU's open **CORDIS** data (24,000 Horizon Europe projects, 36,000
organisations) and the portal's **3,808 call topics**, plus a 151-item
**Europeana salmon** pilot. **ArcaBC** is shown as "pending permission": no
data from it exists here.

Timings are what the API answered on Oct 27 *while other jobs were using the
laptop*; expect the same or better on a quiet machine.

### B1. Expert search (0:00)

**Do:** tab 1 (`/#/experts`). Type exactly `who at SFU works on wildfire smoke and health?`, press **Search**.
**Verified:** 0.6 s (first query after idle: 23 s, hence pre-flight 7).
**Appears:** ranked researchers, each with topics and publication titles:

1. Sophie Wilkinson: "The 2023 wildfires in British Columbia, Canada: impacts, drivers, and transformations to coexist with wildfire"
2. Seyed Hamid Delbari: PM2.5 sources in a Canadian port city
3. **Ryan W. Allen**: "Can Public Spaces Effectively Be Used as Cleaner Indoor Air Shelters during Extreme Smoke Events?" (2021)
4. Brendan P. Murphy: wildfire regimes and fauna
5. Maya S. Montalvo: fire effects on soil and water

**Say:** "Plain language in, researchers out, and each one comes with the
publications that put them there. This is public OpenAlex data standing in for
SFU's own directory, which we are waiting on an agreement for. Ranked by fit to
the topic, never by anything personal." Point at Ryan Allen (smoke and health).
**Don't** type the shorter `wildfire smoke and health`: rank 1 becomes a
researcher on maternal smoking (tobacco). Read the results aloud only if they
are on point.
**If slow:** wait; it is a one-off model load. **If it fails:** `docker compose restart api` (see recovery).

### B2. A call for this researcher (0:45)

**Do:** on Ryan W. Allen's card click **Calls for this researcher**.
**Verified:** 3.4 s. **Appears:** two calls:

- `HORIZON-CL6-2027-01-ZEROPOLLUTION-02`, air quality planning strategies, RIA, forthcoming, deadline 22 Sep 2027
- `HORIZON-HLTH-2027-01-ENVHLTH-02`, **Integrating climate-related exposures into the human exposome and characterising its changes in response to climate change**, RIA, Cluster 1 Health, **opens 29 Oct 2026, deadline 17 Feb 2027** (so it is open by the time you are in Lisbon)

**Say:** "Open and forthcoming Horizon Europe topics, with deadlines and a link
to the official portal page."
**If the page is empty:** go to tab 2, type `climate change adaptation and health`.

### B3. EU partners and the shortlist (1:30)

**Do:** the Draft a consortium page shows the shortlist, the rule check and
the brief together, and only after the brief finishes. So show the partner
list on its own first: tab 3 (`/#/partners`), paste `Integrating climate-related exposures into the human exposome and characterising its changes in response to climate change. Cluster 1 - Health (Single stage - 2027/1)`.
**Verified:** 5.5 s under load. **Appears (top 6):**

1. INSERM (FR): projects CliCBrain, healthRiskADAPT, SIRENE, EIRENE IMP, HEAT-UP (coordinator)
2. CNR (IT): TRIGGER, healthRiskADAPT, SIRENE, EIRENE IMP
3. ISGlobal Barcelona (ES): CATALYSE (coordinator), SIRENE, LIVER-X
4. Finnish Meteorological Institute (FI): CATALYSE, healthRiskADAPT, ClimAIr
5. University of Cyprus (CY): TRIGGER, ISMED-CLIM (coordinator)
6. Max Planck Society (DE): CliCBrain, CATALYSE

**Say:** "Partners are found through the Horizon projects that match, so
every organisation arrives with the projects as evidence. Coordinators count
more. Only EU member and associated countries are listed."

### B4. Consortium check (3:00)

On the Draft a consortium page the "Consortium rule" panel reads, for an RIA
call: **"at least three independent legal entities in three different member
states or associated countries, at least one in a member state"**, with the
countries of the shortlist plus Canada listed (the API marks CA as an associated
country). **Verified on another call** (air quality
ZEROPOLLUTION-02): rule met, countries BE, FI, ES, IT, ES, NL and CA.
**Say:** "That check is plain code, not a model. If SFU plus two partners
fail the rule, it says so."

### B5. The brief (start early)

The brief is the only slow step: it is written by the local model.
**Start it in the pre-flight**: open
`http://localhost:8080/#/brief?call=topic%3AHORIZON-HLTH-2027-01-ENVHLTH-02`
in its own tab fifteen minutes before and leave it open (the page waits; the
proxy allows 15 minutes). When you reach this step, switch to that tab.
**Timing:** the handoff note says "about two minutes". **That was not
reproduced on Oct 27:** three attempts (the laptop was shared with other
containers using the CPU) took 558 s and 555 s, both ending with **"The model
did not answer: TimeoutError: timed out"** (the router waits 10 minutes), and
540 s, which succeeded (model generating at 4 to 5 tokens a second). The
shortlist and rule check were shown every time. So: **start the brief at
least 15 minutes before you need it**, on a quiet laptop, and treat a
timeout as normal, not a failure.
**Appears:** the "Brief for review" panel: a short draft that cites partner
and project ids, a note of how many sentences were dropped for citing
something outside the evidence, how many cite nothing ("check them"), and
"Nothing is sent: this is a draft for the research office."
**Read the "Gaps and next steps" section aloud**: the draft is honest that evidence is thin (it also overreaches a little, e.g. "across multiple continents"; call it a draft). **Say:** "Any sentence that cites something not in the evidence is thrown away
before you see it. The research office approves; nothing is sent."
**Fallback:** if the model has not answered, show the shortlist and the rule
check and say "the draft is the slow step on a laptop; on a dedicated box it
is seconds". Never wait on stage.

### B6. Collections search, text and picture (4:30)

**Do:** tab 4 (`/#/`). Type `men netting fish from a boat`, **Search**.
**Verified:** 1.9 s. **Appears:** two lists, **pictures** first: Laxfiske Multra (Vasternorrlands museum), then four "Fischer beim Lachsfang bei Gauernitz" photos (Deutsche Fotothek); **books, reports and film** second: Zalmvisserij (sound archive), Salmon fishing (1920, 1907).
**Say:** "I did not say salmon or use any German. It found pictures by what
they show, in another language, and every card shows its source and licence.
Pictures and texts are separate lists because a text query always sits closer
to text."
**Then:** click **Cite** on one card (APA, Chicago, BibTeX built from the record).
**Then (picture):** switch to **By image** and drop in
`002e1d5a6cb0d9e9.jpg` (copied to `C:\demo\`, a Swedish salmon-fishing postcard).
**Verified:** 6.4 s; answer "same picture" (similarity 1.0), then four other
Indalsalven salmon-fishing postcards at 0.87 to 0.89.
**Say:** "It tells you whether the picture is in the collection, similar, or
has no close match, rather than pretending."
**Point at the two grey panels** on the page: "BC collections (ArcaBC): permission in progress" and "SFU experts (REE): waiting on the integration". **Say:** "We show what is pending as pending."
**Weak spots to avoid:** see sample_pack.md ("Lachsfang" returns unrelated
German archive charters among the texts).

---

## C. Recovery

| Symptom | Fix |
|---|---|
| Any page shows "Search failed" or the API is silent | `curl -s localhost:8080/api/health`. If down: `docker compose restart api` (back in about 25 s, per the Oct 22 resilience test), then repeat pre-flight 7 |
| Course Access calls return `{"detail":"Not Found"}` | `docker compose exec web nginx -s reload`; open `/review/index.html` |
| `/review/` or the "Course Access" link shows the Collections page | Type `localhost:8080/review/index.html` |
| Neo4j restarted | Search returns after about 3 s (Oct 22 test). Check `docker ps` |
| Ollama slow or unresponsive | `docker exec campus-ai-ollama-1 ollama ps` (is `gemma4:e2b` loaded?); re-warm with `ollama run gemma4:e2b "Say ok"`. If it stays stuck: `docker compose restart ollama` and re-warm. A "reasoning" call can think for ten minutes: never wait on one on stage |
| Brief times out | Show shortlist and rule check; the page already says "The model did not answer" |
| Whole Docker Desktop is stuck | Last resort: restart Docker Desktop, then `docker compose up -d web ollama` (it restarts other projects' containers on this laptop too) |
| Picture upload rejected | Use a `.jpg` from `D:\campus-ai\data\europeana\salmon\media\` (limit 10 MB) |

---

## D. AFTER MERGE (not verified live)

These belong to open PRs; do not use them in the live script until merged and
the images rebuilt (`docker compose build`, then `up -d`, then re-run the
pre-flight).

- **#38 call analyst:** `/api/calls/{id}/analysis` (expected outcomes and
  consortium rules from a call's topic text). Add a step after B2: open a
  call, show the analysis. Verify with `curl localhost:8080/api/calls/<id>/analysis`.
- **#35 equations (A4b):** OMML equations in DOCX/PPTX converted to MathML.
  Use a document with equations in section A.
- **#37 OCR (A7):** scanned PDFs. Do not demo a scanned PDF before this lands
  and has been timed.
- **#39 reranker (B2):** off by default. If switched on, re-check B1 to B3
  results and timings before relying on them.
- **#36 eval harness (P6):** not a demo item; use it to refresh the numbers on
  the one-pagers.

---

## Appendix: what was checked on Oct 27 (laptop under heavy load from other jobs)

| Call | Time |
|---|---|
| `/api/health` | instant |
| `/api/experts` first query after idle | 23.1 s; later 0.6 to 1.7 s |
| `/api/calls` | 0.5 to 2.8 s |
| `/api/calls/for/openalex:A5039444427` | 3.4 s |
| `/api/partners` | 2.4 to 5.5 s |
| `/api/search` | first 13.3 s; later 1.9 to 4.6 s |
| `/api/search/image` | 6.4 s |
| `/api/brief` (air quality call) | 557.7 s, model `TimeoutError`; shortlist and check returned |
| `/api/brief` (exposome call), 2 runs | 555 s `TimeoutError`; then 540 s, brief returned (7 partners incl. Simon Fraser as home, a "Gaps and next steps" section) |
| `/api/course-access/health` through the proxy | 404 (stale proxy config) |
