# Complementarity scorer and journey router (R4, third cut)

Run 2026-10-27 on the demo laptop (RTX 2050, 4 GB), code on branch
`r4-scorer-router`. Stack: Neo4j with the full Horizon Europe graph (23,954
projects, 35,625 organisations, 3,808 call topics, 2,226 SFU researchers),
Ollama with `gemma4:e2b` for every task, embedder embeddinggemma-2. Other
agents were using the same Ollama and GPU throughout, so the model timings
below are those of a shared, busy laptop.

## 1. What each partner adds: HORIZON-MISS-2027-03-OCEAN-01

*Increasing riparian and coastal areas resilience to climate change,
including in waterfront cities and islands* (HORIZON-IA, the three-entity
rule, Canada associated in Pillar II).

**Analysis** (`call_analyst.analyse`, called directly): 159 s, 0 dropped.
Topics: "Increasing coastal area resilience to climate change",
"Implementing ocean and water restoration mission", "Enhancing ecological
functions of areas", "Reducing climate change related risks", "Increasing
socio-economic benefits". Partner profile: "public bodies managing those
areas and their communities" and "public administrations, including
relevant island public authorities"; both map to one role, **public
authority as end user**. The call's 14 keywords are needs too, so the
scorer checks 19 needs.

**Shortlist** (`ResearchSearch.partners(partner_query, k=10)`), then the
scorer: one Cypher query for the evidence projects' text and EuroSciVoc
terms and each organisation's SME flag and coordinations (0.11 s warm,
3.7 s cold), scoring 0.06 s. The "adds" lines, as the page shows them:

1. (IE, higher education) UNIVERSITY OF GALWAY adds: covers "Increasing coastal area resilience to climate change" [cordis:101286863] [cordis:101093910]; covers "Implementing ocean and water restoration mission" [cordis:101286863] [cordis:101093910]; covers "Reducing climate change related risks" [cordis:101286863] [cordis:101057764]; covers "Increasing socio-economic benefits" [cordis:101286863] [cordis:101093910]; and 9 more need(s) [cordis:101057764] [cordis:101093910] [cordis:101286863]; brings country IE [cordis:org:999978045].
2. (PT, higher education) UNIVERSIDADE DE AVEIRO adds: covers "Increasing coastal area resilience to climate change" [cordis:101093956] [cordis:101056782]; covers "Implementing ocean and water restoration mission" [cordis:101093956]; covers "Reducing climate change related risks" [cordis:101093956] [cordis:101056782]; covers "Increasing socio-economic benefits" [cordis:101093956] [cordis:101056782]; and 5 more need(s) [cordis:101056782] [cordis:101093956] [cordis:101295922]; brings country PT [cordis:org:999865331]; coordinated [cordis:101093956] [cordis:101056782] (31 Horizon Europe projects coordinated in all).
3. (IT, research organisation) FONDAZIONE CENTRO EURO-MEDITERRANEOSUI CAMBIAMENTI CLIMATICI adds: covers "Increasing coastal area resilience to climate change" [cordis:101286863] [cordis:101057764]; covers "Implementing ocean and water restoration mission" [cordis:101286863] [cordis:101181159]; covers "Reducing climate change related risks" [cordis:101286863] [cordis:101057764]; covers "Increasing socio-economic benefits" [cordis:101286863] [cordis:101181159]; and 7 more need(s) [cordis:101057764] [cordis:101061083] [cordis:101286863]; brings country IT [cordis:org:999419422].
4. (DK, higher education) DANMARKS TEKNISKE UNIVERSITET adds: ... and 9 more need(s) ...; brings country DK [cordis:org:999990655].
5. (RO, higher education) UNIVERSITATEA DIN BUCURESTI adds: ... covers "Environmental sciences" [cordis:101081377] [cordis:101137255]; and 5 more need(s) [cordis:101056782] [cordis:101137255]; brings country RO [cordis:org:999603916].
6. (PT, research organisation) AIR CENTRE adds: ... brings country PT [cordis:org:902624480]; coordinated [cordis:101093962] (1 Horizon Europe projects coordinated in all).
7. (NO, research organisation) NORSK INSTITUTT FOR VANNFORSKNING adds: ... and 9 more need(s) ...; brings country NO [cordis:org:997826585].
8. (ES, research organisation) CSIC adds: ... and 9 more need(s) ...; brings country ES [cordis:org:999991722].
9. (DE, research organisation) ZMT adds: ... brings country DE [cordis:org:986128094]; coordinated [cordis:101286863] [cordis:101291488] (2 Horizon Europe projects coordinated in all).
10. (DK, higher education) AARHUS UNIVERSITET adds: ... covers "Environmental sciences" [cordis:101137255] [cordis:101093865]; and 5 more need(s) ...; brings country DK [cordis:org:999997736].

(Lines 4-10 shortened here, with long organisation names abbreviated
(AIR CENTRE, NIVA, CSIC, ZMT); their named needs are the same topics as
above. Every clause in every line cites a project or organisation id; the
unit tests check that for each clause.)

**Set view.** 8 countries (IE, PT x2, IT, DK x2, RO, NO, ES, DE). Covered by
nobody: "Enhancing ecological functions of areas", "Water resources",
"nature based soutions", "riparian areas", "water erosion". Role unfilled:
**public authority as end user**: no public body is on the shortlist,
although the call "strongly encourages" them.

**Complementary set of 3** (greedy, home institution CA counted as a
member for the rule):

- rank 1, gain 14: UNIVERSITY OF GALWAY adds: covers "Increasing coastal area resilience to climate change" [cordis:101286863] [cordis:101093910]; covers "Implementing ocean and water restoration mission" [cordis:101286863] [cordis:101093910]; covers "Reducing climate change related risks" [cordis:101286863] [cordis:101057764]; covers "Increasing socio-economic benefits" [cordis:101286863] [cordis:101093910]; and 9 more need(s) [cordis:101057764] [cordis:101093910] [cordis:101286863]; brings country IE [cordis:org:999978045].
- rank 2, gain 2: UNIVERSIDADE DE AVEIRO adds: covers "flooding" [cordis:101056782] [cordis:101295922]; brings country PT [cordis:org:999865331]; coordinated [cordis:101093956] [cordis:101056782] (31 Horizon Europe projects coordinated in all).
- rank 3, gain 1: FONDAZIONE CENTRO EURO-MEDITERRANEOSUI CAMBIAMENTI CLIMATICI adds: brings country IT [cordis:org:999419422].

Consortium rule (HORIZON-IA): met, IE, PT and IT member states plus CA
associated. Still uncovered by the set: the five needs above; role still
open: public authority as end user.

### Through the API

`GET /api/partners/complement?call=topic:HORIZON-MISS-2027-03-OCEAN-01&n=3`
on a temporary API container from the branch (joined to `campus-ai_graph`;
the network is internal, so the container was called from inside the
network, not through a published port):

- First request (k=10): **HTTP 200 in 557 s**, but the analysis call to the
  model hit the backend's 600 s timeout on the shared Ollama
  (`model_error: "TimeoutError: timed out"`). The endpoint degraded as
  designed: it searched on the call's title, scored on the call's keywords,
  listed no roles, and said why. The failed analysis was not cached.
- Second request (k=20): the analysis ran again, **HTTP 200 in 362 s**,
  `model_error` null; the model's wording differed a little ("Reducing
  vulnerability to climate risks", "Socio-economic benefits from
  restoration"). 20 partners from 13 countries; uncovered "Enhancing
  ecological functions of areas", "nature based soutions", "water erosion";
  role unfilled: public authority as end user. Complementary set: UNIVERSITY
  OF GALWAY (rank 5, gain 14), UNIVERSITATEA DIN BUCURESTI (rank 3, gain 3:
  covers "flooding" [cordis:101056782], "riparian areas" [cordis:101294308],
  country RO), WAGENINGEN UNIVERSITY (rank 1, gain 1: country NL); rule met
  (IE, NL, RO, CA).
- Third request (k=10, analysis cached): **HTTP 200 in 0.8 s**, the same
  pick and the same open role.

## 2. Journey router: ten requests

Five that hit a rule and five that need the model, through
`GET /api/ask?q=` on the same temporary API (seconds are the whole HTTP
request, search included):

| # | Request | Journey | Why | s | Top results |
|---|---|---|---|---|---|
| 1 | Find EU partners for HORIZON-MISS-2027-03-OCEAN-01 | 1 | rule: Horizon topic identifier | 0.7 | call found; searched on its title: Universidade de Aveiro, CSIC, NTNU |
| 2 | Which calls fit a lab working on soil microbiomes and carbon storage? | 2 | rule: which calls or funding | 0.4 | HORIZON-MISS-2027-05-SOIL-01-two-stage |
| 3 | Draft a consortium brief for HORIZON-HLTH-2027-03-TOOL-08 | 3 | rule: consortium or brief | 0.6 | call found; shortlist KU Leuven, Aristotle Univ. Thessaloniki, Karolinska (page links to the brief) |
| 4 | Who at SFU works on wildfire smoke and respiratory health? | 4 | rule: expert, supervisor or who works on | 0.3 | Seyed Hamid Delbari, Stephanie E. Cleland, Ryan W. Allen |
| 5 | Historical photographs of salmon canneries on the Fraser River | 5 | rule: sources, images or collections | 0.9 | 10 pictures (Europeana salmon pilot: "Laxfiske i Forsmo", ...) |
| 6 | salmon habitat restoration in British Columbia | 4 | no rule; model took over 90 s; default | 84 | Jayda Wilson, Hua Zhang, Thomas C.A. Royle |
| 7 | I'm a prospective master's student interested in machine learning for medical imaging | 4 | no rule; model took over 90 s; default | 86 | Weina Jin, Da Ma, Hanene Ben Yedder |
| 8 | European universities doing research on coastal flooding and nature-based solutions | 4 | no rule; model took over 90 s; default | 84 | (SFU researchers; journey 1 was meant) |
| 9 | quantum computing | 4 | no rule; model took over 90 s; default | 84 | Keelan Watkins, Hoi-Kwan Lau, M. H. S. Amin |
| 10 | Our biology department wants to apply for money for a coral reef monitoring project | 4 | no rule; model took over 90 s; default | 85 | (SFU researchers; journey 2 was meant) |

The HTTP time of the model cases (84-86 s) is a little under the router's
90 s budget although the router reports the budget as exceeded; the two
clocks are in different containers on WSL2 and drift. The budget works as
meant: no request waited longer than about 90 s.

**The model without the budget.** The same five model cases through
`router.classify` with the budget lifted to 600 s, one after another, after
the temporary API was stopped (other agents still on the GPU):

| Request | Model's journey | s | Right? |
|---|---|---|---|
| 6 salmon habitat restoration in British Columbia | 4 | 130.2 | yes (5 would also do) |
| 7 prospective master's student, ML for medical imaging | 4 | 99.5 | yes (supervisor) |
| 8 European universities ... coastal flooding and NbS | 1 | 35.1 | yes |
| 9 quantum computing | 2 | 155.9 | arguable (4 is the natural reading) |
| 10 biology department ... apply for money ... coral reef | 2 | 73.8 | yes |

Every answer was a clean single digit (no parse failures); 4 of 5 are
right, median 100 s. An earlier run of case 6, while the call analyst was
also running, took 585 s and answered 5; the model is not deterministic and
its latency on this laptop is set by whatever else the GPU is doing.

## Reading

- **The scorer's strongest signal is the gaps, not the coverage.** A
  shortlist that partner search ranked on the call's own text covers the
  call's main topics almost entirely (every partner covers 3 to 4 of the 5
  topics), so "adds" lines differ mostly in country, coordination and the
  odd specific need ("flooding", "riparian areas"). What the research office
  learns is what nobody brings: here a public authority, which the call
  explicitly asks for, and the riparian and erosion side. The next step for
  the demo is to search for that role (public bodies only) and offer it as
  the fourth member; not built.
- **Keywords dominate the greedy gain.** The call's 14 keywords count as
  needs alongside the 5 topics, so the first pick is whoever covers the most
  broad keywords ("Ocean", "Climate change"). Weighting topics above
  keywords, or dropping the portal's field keywords, would make the pick
  follow the call's substance more; left equal for now (simple, and the
  tie-break on rank keeps the result explainable).
- **Word matching is literal.** The call's keyword "nature based soutions"
  (the portal's own typo) is covered by nobody because "soutions" matches
  no project; "Enhancing ecological functions" needs both "ecological" and
  "functions" in one project. Generic words ("increasing", "related",
  "areas", "based"...) are ignored so they do not match everything.
- **Roles come from a small keyword table** over CORDIS organisation type,
  SME flag and name (clinical partners by hospital, clinic, UMC... in the
  name). "Communities" in the OCEAN-01 profile is not mapped to civil
  society on purpose: the table maps only kinds of organisation.
- **The router's rules carry it.** All five rule cases routed correctly in
  under a second, search included. With the model at the router's 90 s
  budget, on a laptop whose one Ollama was serving other agents, all five
  model cases fell back to expert search; two of them (8, 10) were meant
  for other journeys, and the model, given time, gets both right. The
  budget (`MODEL_SECONDS`, 90 s) is a trade between a slow answer and a
  wrong default; 160 s would have let every answer above through. Two
  cheap fixes, not made here: rules for "European
  universities/partners" (journey 1) and "apply for/money" (journey 2), and
  the classification task without thinking (`gemma4` thinks by default;
  the router asks for one digit but waits for hundreds of thinking tokens).
  The latter is a change to the core LLM backend (an Ollama `think: false`
  option for the classification task), card P1.
- A late model answer is dropped, but the request keeps running on Ollama
  until it finishes, so a burst of unroutable questions queues work behind
  it. The budget protects the user, not the GPU.
