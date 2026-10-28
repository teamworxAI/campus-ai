<!--
Sample pack for the Web Summit Lisbon demo: what to use and why. Checked
against the demo laptop's running stack on Oct 27, 2026 (main's code; PRs
#35 to #39 not merged). Timings were taken while other jobs were using the
laptop. Results are read, not only counted: names and titles below are what
the API returned.
-->

# Sample pack

Used by [`demo_script.md`](demo_script.md). Everything here is public or
openly licensed; nothing is private data.

## 1. Course Access: documents

Source: the A6 corpus, 20 CC BY / CC BY-SA documents on the laptop at
`D:\campus-ai\data\course_access\` (names and licences in `manifest.jsonl`).
Numbers from `evals/course_access/remediate_corpus_20261023.md` (rules only,
no alt text, proposals that need no review applied). **Copy the chosen files to
`C:\demo\` before the show** so the file picker is quick.

| Use | File | Before | After | Seconds in the corpus run | Why |
|---|---|---|---|---|---|
| **Main demo** | `olds-profcomm-m3\presentations-lecture-notes.docx` | 12 | 0 | 17.8 | Reads as a real lecturer's notes (282 paragraphs). Hand-typed lists, no title, bare URLs, one image. Goes to zero. Short enough for two minutes even with alt text on (one image) |
| **Quick fallback, visual** | `olds-profcomm-m3\presentations-slides-Your Presentation Style Slide Deck.pptx` | 19 | 8 | 0.2 | 20 slides, hand-typed lists and repeated slide titles fixed instantly. The 8 left are images needing descriptions: "these wait for a person". Do not tick alt text (9 images, about 3 minutes) |
| Small, clean win | `ontariotech-edst3440u\course-outline.docx` | 7 | 0 | 34.4 | A course outline, 17 layout tables treated as layout, bare URLs fixed. Good for the regulator or the office-of-the-registrar audience |
| Small, clean win | `olds-profcomm-m1\foundations-lecture-notes.docx` | 3 | 0 | 19.5 | Tiny; use if the main one misbehaves |
| Slides, mostly fixed | `ontariotech-edst3440u\week-12-slides.pptx` | 7 | 1 | 0.1 | Repeated titles fixed; 1 image left |
| Show a long one pre-built | `ecampusontario-oer101\oer-101-module-1.pdf` | 87 | 50 | 108 | 26 pages, 49 images, 25 tables. **Do not run live.** Run it the evening before and keep the job in the queue to open and click through |

**Corpus totals (honest version):** 862 issues before, 360 after (58% fewer);
476 proposals applied, 51 waiting for a person; **2 issues introduced** (both
in one PDF, `foundations-etextbook.pdf`). The 360 left are mostly images that
need descriptions, which that run left alone on purpose. Not yet compared to a
specialist's labels.

**Known weak spots (avoid on stage):**

- Long PDFs: minutes, not seconds (e-textbooks 330 to 390 s).
- Slide decks with many images: only the images' alt text is left, and
  proposing it costs about 15 to 20 s per image on `gemma4:e2b` (alt-text
  probe, Oct 22).
- The small model reports confidence 1.0 for almost everything (handoff
  note). Don't say "high confidence" about a number; say "rules route what
  needs a person".
- `foundations-slides-Channels` and `-Visuals` decks: 17 issues, 14 left
  (15 images each): a poor "after".
- PDF output is a rebuilt DOCX/HTML, not a re-tagged PDF (scope decision).
- Existing alt text, colour contrast and reading order are listed under "Not
  checked automatically" on the job page: point at it, it builds trust.

## 2. Research Assistant: expert queries

From `evals/research_assistant/expert_search_20261023.md`, re-run live Oct 27.
Type the question exactly as shown.

| Query | Top results (live) | Use |
|---|---|---|
| **`who at SFU works on wildfire smoke and health?`** | Sophie Wilkinson (2024: "The 2023 wildfires in British Columbia, Canada: impacts, drivers, and transformations to coexist with wildfire"), Seyed Hamid Delbari (PM2.5 sources), **Ryan W. Allen** (2021: "Can Public Spaces Effectively Be Used as Cleaner Indoor Air Shelters during Extreme Smoke Events?"), Brendan P. Murphy, Maya S. Montalvo | The opener. 0.6 s. The question the plan names. Point at Allen |
| `salmon populations and climate change in rivers` | Kara J. Pitman ("Glacier retreat creating new Pacific salmon habitat"), Shawn Chartrand (river geomorphology), **John D. Reynolds**, **David A. Patterson** ("Exceptionally high mortality of adult female salmon"), Jonathan W. Moore | Links to the salmon collections pilot: "who at SFU works on this today?". Chartrand is a river-science person, not fish: say "rivers" |
| `machine learning for medical imaging` | Weina Jin (explainable AI in medical image analysis), Hanene Ben Yedder (deep learning for biomedical image reconstruction), Da Ma (retinal imaging, OCT) | Clean, all plausible |
| `urban housing affordability policy in Canada` | Andrey D. Pavlov ("Foreign buyer taxes and housing affordability"), Kendra Strauss, Yushu Zhu ("disparities in access to affordable housing in urban Canada") | Clean, and a non-science example |
| `quantum materials and superconductivity` | S. R. Dunsiger (superconductivity and magnetism), then four quantum-device people | Fine; first result clearly right |

**Weak spots:** `wildfire smoke and health` (short form) puts Jaclyn Parks
(maternal smoking, tobacco) first: use the full question. `Indigenous
language revitalization` returns education and Indigenous-studies people, not
language specialists: skip. Results are from 3,000 recent, highly cited works,
so a real SFU expert can be missing: never say "all of SFU". Scores (about
0.03) only order results; don't present them as a percentage.

## 3. Research Assistant: calls and partner shortlists

`GET /api/calls` returns open **and forthcoming** topics. Calls listed as
"Open" with deadline **5 Nov 2026** (the CL3 disaster-resilience calls) close
before Lisbon: avoid them. The ones below are open or opening by then.

Three (plus one) verified with `curl`; partners queried with the call title
plus the call group title, as the brief does:

| Call (id) | Opens / deadline | Partner shortlist (top, with the projects as evidence) | Pair with expert |
|---|---|---|---|
| **`HORIZON-HLTH-2027-01-ENVHLTH-02`**, exposome and climate, RIA, Health | opens 29 Oct 2026 / 17 Feb 2027 | INSERM (FR; HEAT-UP coordinator, healthRiskADAPT, SIRENE), CNR (IT), ISGlobal Barcelona (ES; CATALYSE coordinator), Finnish Meteorological Institute (FI; ClimAIr, healthRiskADAPT), Univ. of Cyprus, Max Planck. 5.5 s | Ryan W. Allen (it is on his "Calls for this researcher" list) |
| **`HORIZON-CL6-2027-01-ZEROPOLLUTION-02`**, air quality planning, RIA | opens 20 Apr 2027 / 22 Sep 2027 (forthcoming) | TU Delft (UrbanAIR coordinator), VITO (VISIONAIR coordinator, UrbanAIR), DTU, KU Leuven, KTH, Fondazione ICONS. 2.4 s. In the brief: VITO, Helsinki, Barcelona Supercomputing Center, ICONS, UP Madrid, Delft; consortium rule **met** (BE, FI, ES, IT, NL + CA) | Ryan W. Allen (also on his list), Seyed Hamid Delbari |
| **`HORIZON-HLTH-2027-02-TOOL-01-two-stage`**, AI predictive biomarkers, RIA | opens 29 Oct 2026 / 17 Feb and 16 Sep 2027 | Erasmus MC Rotterdam (PRECISE, U-Tube coordinator), Charite Berlin (CLAIMS, PROTO coordinator), Fundacio Clinic Barcelona, Linkoping, Malaga, King's College London (associated). 2.7 s | Weina Jin, Da Ma |
| `HORIZON-MISS-2027-03-OCEAN-02`, seafood supply chain circularity, IA | opens 9 Feb 2027 / 21 Sep 2027 | CSIC (ES), DTU, CNR, SINTEF Ocean, HCMR (EL), CPMR. 5.3 s | John D. Reynolds, David A. Patterson (salmon link) |

Call search queries that return a useful list (live): `climate change
adaptation and health` (3 calls: health adaptation tools, the exposome call,
maladaptation), `air quality and health effects of wildfire smoke exposure` (3
calls, ZEROPOLLUTION-02 first), `medical imaging machine learning` (2 calls).

**Weak spots:**

- `wildfire smoke exposure and public health in cities` on the **EU partners**
  page returned national funding agencies (FCT, NKFIH, Innovationsfonden...),
  not research groups (`partner_search_20261023.md`). Paste a call's title
  instead.
- The open-call pool is small and results are cut after ranking: broad
  queries like `artificial intelligence` or `ocean and fisheries` return
  only one call each. `artificial intelligence` returned the EIC GenAI4EU
  topic with 2024 to 2025 dates, still marked forthcoming: the status is
  taken from the portal file and can be stale. Don't pick it.
- One CL3 call title contains a garbled character (a dash): avoid reading
  that title aloud.
- Back-test: recall@10 **0.32** (63 of 200; MRR 0.13). A third of the time
  the hidden real partner is in the top ten. Say it as a baseline, not a
  success rate. Lists skew to large organisations that appear in many
  projects (Delft, CNR, INSERM).
- The brief: "about two minutes" per the handoff, but 540 to 558 s on Oct 27
  (two of three runs timed out at the model). Always have it pre-run (script, B5).

## 4. Collections search: salmon pilot (151 items, Europeana, open licences)

Pictures are listed first, books and reports second. Read the picture list
aloud only after the first run in the hotel.

| Query | Pictures (top) | Texts (top) | Why it works |
|---|---|---|---|
| **`men netting fish from a boat`** | Laxfiske Multra (Vasternorrlands museum), four "Fischer beim Lachsfang bei Gauernitz" photos (Deutsche Fotothek) | Zalmvisserij, Salmon fishing (1920, 1907) | No "salmon" and no German in the query: meaning across languages and pictures. 1.9 s |
| `salmon fishing on rivers` | Salmon Fishing (Finnish National Gallery, CC0), Zalmvisserij (Rijksmuseum, 1671, public domain), Lohenpyynti (Finnish Heritage Agency), Laxfiske (1933, Society of Swedish Literature) | Salmon fishing (1920, 1907), Salmon-fishing in Canada (1860), Salmon-fishing on the grand Cascapedia (1904) | The guide's own example, strong in both lists. Cards badge "Picture and words" |
| `salmon in Canada` | (mixed) | Salmon-fishing in Canada (1860 and "by a resident"), Moose-hunting, salmon-fishing and other sketches of sport (1902) | The BC link: Canadian texts first. Pictures are weak (Swedish stamp), so talk about the texts |
| `fish traps and weirs in a river` | Laxfiske i Forsmo, Laxgard (Kalmar County Museum, a fixed salmon trap), Salmon Fishing, Pesca del salmon (Galiciana) | Observations on a salmon river, Days and nights of salmon fishing in the River Tweed | Concept (a trap), not the word "salmon" |
| `saumon pêche` (French) | Laxfiske (1933), an illustration of two salmon fishers, Salmon Fishing | The habits of the salmon (1889), Salmon fishing (1920, 1907) | Shows French finding Swedish and English items. Top picture is "wild pacific salmon in tin" (a canned-salmon photo, CC BY-SA): fine for a joke, off topic otherwise |

**By image:** use `D:\campus-ai\data\europeana\salmon\media\002e1d5a6cb0d9e9.jpg`
(a postcard of net fishing in the Indalsalven). Live: "same picture"
(similarity 1.0), then four related postcards at 0.87 to 0.89, 6.4 s. Any
file in that folder gives the "in the collection" answer. For "has no close
match" use an unrelated screenshot; for "similar pictures" you need a salmon
photo from outside the index, which cannot be fetched offline: bring one on a
USB stick if you want that case.

**Weak spots:** `Lachsfang` (German) gives good pictures but its text list is
unrelated German archive charters. Items are mostly Nordic and Dutch; there is
no BC material (ArcaBC is off limits until BC ELN agrees, and the page says
so). Don't claim cultural coverage beyond 151 items.

## 5. Quick pre-flight queries (copy and run)

```bash
curl -s localhost:8080/api/health
curl -s -G localhost:8080/api/experts --data-urlencode "q=who at SFU works on wildfire smoke and health?" -d k=5 -o /dev/null -w "%{time_total}s\n"
curl -s -G localhost:8080/api/calls --data-urlencode "q=climate change adaptation and health" -o /dev/null -w "%{time_total}s\n"
curl -s -G localhost:8080/api/partners --data-urlencode "q=Integrating climate-related exposures into the human exposome" -o /dev/null -w "%{time_total}s\n"
curl -s -G localhost:8080/api/search --data-urlencode "q=men netting fish from a boat" -o /dev/null -w "%{time_total}s\n"
```
