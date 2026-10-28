# Call analyst (R4, second cut): three real Horizon Europe topics

Run 2026-10-23, one call re-run 2026-10-26 (below). Demo laptop (RTX 2050,
4 GB). Local model `gemma4:e2b` on the stack's Ollama (router task
"reasoning"); embedder embeddinggemma-2; the full Horizon Europe graph
(23,954 projects, 35,625 organisations, 3,808 call topics). The three
analyses of Oct 23 ran through the app (`create_app()` with FastAPI's test
client) on the live Neo4j and Ollama, with the code on branch
`r4-call-analyst`.

## Re-run, 2026-10-26, over HTTP

After the last graph update (records rebuilt from the cached pages,
`index --label CallTopic`: 3,808 nodes, 27,949 links; graph total still
71,942 nodes), a temporary API container from the branch (port 8091 on the
laptop, joined to `campus-ai_graph`) served
`GET /api/calls/topic:HORIZON-MISS-2027-03-OCEAN-01/analysis`: **HTTP 200 in
337 s** (model 349 s by its own clock, which includes the request); the
second request came from the cache in 0.008 s. `/api/calls?q=climate
adaptation of coastal communities` through nginx on :8080 (the stack's api)
returned the same topic first. Result: action HORIZON-IA, the three-entity
rule, Canada associated (Pillar II), EUR 35.7 million for about 4 grants,
deadline 2027-09-21, no topic-specific conditions; 5 topics, 5 expected
outcomes and 2 partner-profile items ("Relevant public bodies managing those
areas and their communities", "Stakeholders and local competent authorities
managing riparian and coastal areas"), **0 dropped**. With the same model
and prompt the wording differs a little from Oct 23 (section 3): the model
is not deterministic, but every kept item is quoted from the text.

Partner shortlist through nginx (`/api/partners`, k=8) on `partner_query`:
Universidade de Aveiro (PT; RESTORE4Cs, COAST-SCAPES), CSIC (ES), CMCC (IT;
BEACONSplus, RIVIERADE), Universitatea din Bucuresti (RO; RESTORE4Cs, ROWER),
UPC (ES), CNRS (FR; OCEAN CITIZEN, RIVIERADE), EPISKY (EL; DaWetRest), Tartu
Ülikool (EE). On the title alone it is the Oct 23 "before" list (NTNU, CNR,
ICLEI, Obshtina Burgas, ZMT in place of the restoration and riparian
projects).

Topic-specific conditions as stored, for comparison: TOOL-08 carries the
strategic-autonomy participation restriction; CL6-2027-01-CIRCBIO-10
"participation of at least one research institution or relevant public
authority from Ukraine in the consortium is mandatory"; SOIL-04 and OCEAN-01
have none beyond the General Annexes (empty).

## Data

- `fetch-cordis` (default `--topics current`): **365 topic pages** (90 open,
  275 forthcoming) fetched from the Funding & Tenders topicDetails JSON,
  sequentially with a 0.5 s pause, in **458 s, 0 failures**; cached in
  `DATA_DIR/cordis/horizon/topics/`.
- records.jsonl: 3,808 CallTopic nodes, **355 with "Expected outcome" and
  "Scope" sections** (the other 10 pages have a description without those
  headings). Median description 4,417 characters; 118 were capped at 4,000.
- Graph update: `graph_search.py index records.jsonl --label CallTopic`, 3,808
  nodes and 27,949 links (PART_OF, UNDER_TOPIC) MERGEd by id in 213 s on the
  GPU; the rest of the graph was not touched.

## Summary

| Call | Action | Topics | Outcomes | Partner profile | Dropped | Model time |
|---|---|---|---|---|---|---|
| HORIZON-MISS-2027-05-SOIL-04-two-stage | RIA | 5 | 3 | 3 | 1 | 203 s |
| HORIZON-HLTH-2027-03-TOOL-08 | CSA | 6 | 3 | 6 | 0 | 338 s |
| HORIZON-MISS-2027-03-OCEAN-01 | IA | 6 | 4 | 3 | 0 | 426 s |

A second request for the same call is served from the per-process cache in
under 0.05 s. Every kept item's span was found in the topic text; the one
dropped item had a quote that differs from the text ("polluted or
potentially polluted" against the text's "polluted (or potentially
polluted)").

A first run with the earlier prompt dropped all 11 partner-profile items
over two calls: the model answered them as bare strings with no span. Adding
"every item is an object with text and span" and a worked example to the
system prompt fixed it (above). The topics also stopped echoing the keyword
list once the prompt asked for subjects of the Expected outcome and Scope
sections in the model's own words.

## 1. HORIZON-MISS-2027-05-SOIL-04-two-stage

*Participatory research on the health of communities in contact with polluted
soils.* Found by `/api/calls?q=wildfire smoke and public health` (first hit).
Forthcoming, deadlines 2027-04-08 and 2027-09-14; HORIZON-RIA; EUR 11 million
for about 2 grants; Food, Bioeconomy, Natural Resources, Agriculture and
Environment.

- Rule (from the records): at least three independent legal entities in three
  different member states or associated countries, at least one in a member
  state. Canada: associated country (Pillar II), counts towards the rule.
- Topics:
  - Participatory research on community health: "Participatory research on the health of communities in contact with polluted soils"
  - Mapping disease and health outcomes: "identify and map human diseases and health outcomes driven by soil pollution"
  - Soil pollution risk management: "manage, adapt to, and mitigate risks"
  - Policy enforcement of soil solutions: "policymakers enforce the implementation of long-term, sustainable solutions that enhance soil health, restore the environment, and protect public health"
  - Identifying disease drivers: "explore direct (e.g., skin contact with soils) and indirect (e.g., consumption of contaminated food, psychological impact of living near contaminated sites) soi[l ...]"
- Expected outcomes:
  - improved citizen awareness on the connection between soil pollution and human health and how to manage, adapt to, and mitigate risks
  - increased public access to FAIR data and knowledge on soil pollution and the emergence of human diseases and other health outcomes
  - policymakers enforce the implementation of long-term, sustainable solutions that enhance soil health, restore the environment, and protect public health
- Partner profile:
  - experts on land and soil contamination: "experts on land and soil contamination"
  - epidemiology and SSH disciplines: "epidemiology and in social-science and humanities (SSH) disciplines in particular sociology and anthropology"
  - private entities with industrial operations: "engage private entities with industrial operations in polluted sites and which work with potential pollutants (including substances of concern)"
- Dropped: 1 (partner profile "populations living or working in polluted sites", quote not in the text).

Partner shortlist (top 8, associated countries) before, on the call's title
and call name, and after, on `partner_query`:

| Before (title) | After (topics + partner profile) |
|---|---|
| WAGENINGEN UNIVERSITY (NL): SOILSTICE, SoilTribes, Path4Med | WAGENINGEN UNIVERSITY (NL): PLANET4HEALTH, BENCHMARKS, InBestSoil |
| INRAE (FR): PSOILICY, PREPSOIL, DeepHorizon | FiBL (CH): DeepHorizon, BENCHMARKS, NBSoil |
| AARHUS UNIVERSITET (DK): PSOILICY, SoilTribes, PREPSOIL | UNIVERSIDAD DE VIGO (ES): DeepHorizon, SOB4ES, InBestSoil |
| SVERIGES LANTBRUKSUNIVERSITET (SE): PSOILICY, PREPSOIL, iCOSHELLs | ARISTOTELIO PANEPISTIMIO THESSALONIKIS (EL): LandPrint, DeepHorizon, SOB4ES |
| ICLEI EUROPEAN SECRETARIAT (DE): SOLO, PSOILICY, SOILSTICE | TECHNISCHE UNIVERSITAET MUENCHEN (DE): LandPrint, ProPollSoil, BIOservicES |
| STICHTING WAGENINGEN RESEARCH (NL): PSOILICY, PREPSOIL, SOILCRATES | INSTYTUT UPRAWY NAWOZENIA I GLEBOZNAWSTWA (PL): DeepHorizon, NBSoil, ISLANDR |
| LUONNONVARAKESKUS (FI): SOLO, SUS-SOIL, MultiSoil | INRAE (FR): DeepHorizon, SOB4ES, BENCHMARKS |
| FUNDECYT-PCTEX (ES): HuMUS, PSOILICY, PREPSOIL | UNIVERSIDADE NOVA DE LISBOA (PT): PLANET4HEALTH, ISLANDR, EXPOSIM |

The title query finds the soil-mission policy projects (PSOILICY, PREPSOIL);
the analysed query moves towards pollution and health (ProPollSoil,
PLANET4HEALTH, EXPOSIM), which is what the call asks for.

## 2. HORIZON-HLTH-2027-03-TOOL-08

*Towards the next generation of frontier Artificial Intelligence models for
healthcare.* Found by `/api/calls?q=artificial intelligence for clinical
decision support` (first hit). Forthcoming, deadline 2027-09-16; HORIZON-CSA;
EUR 2.9 million for 1 grant; Health.

- Rule: one legal entity established in a member state or associated country
  (the R5 rule for a CSA). Canada: associated country (Pillar II).
- Topics: Next generation frontier AI models; Leveraging foundation models
  ("how to combine and expand the capabilities of existing foundation models
  towards inclusive and personalised medicine"); Multimodal health data
  analysis; AI Factories and infrastructure ("how to leverage AI Factories");
  Trustworthy artificial intelligence; Roadmap creation.
- Expected outcomes (all three quoted whole from the text): researchers and
  innovators understand how to develop and use frontier AI models for
  healthcare, including AI Factories and foundation models; how to leverage
  heterogeneous, multimodal health data across anatomical scales;
  multidisciplinary stakeholders have a collaboratively created roadmap.
- Partner profile: healthcare professionals; patients; biomedical
  scientists; AI developers; data engineers; ethics experts. Each span is the
  phrase itself, which the text lists among the stakeholders to involve:
  they pass the check but are thin evidence (a short span proves less).
- Dropped: 0.

| Before (title) | After (topics + partner profile) |
|---|---|
| KU LEUVEN (BE): JustHealth, AIRIS, PHASE IV AI | TUM KLINIKUM (DE): NextGen, COMFORT, WISDOM |
| ARISTOTELIO PANEPISTIMIO THESSALONIKIS (EL): ESCORT, TWIN-X, ClimAIr | UNIVERSITY OF OXFORD (UK): euroFMX, TwinRISE, HealthIntelAct |
| KAROLINSKA INSTITUTET (SE): NextGen, ESCORT, OperA | KU LEUVEN (BE): AIRIS, euroFMX, TRUSTroke |
| TALLINNA TEHNIKAÜLIKOOL (EE): ENERGETIC, DTRIP4H | POLITECNICO DI MILANO (IT): euroFMX, TRUSTroke, BETTER |
| RADBOUD UMC (NL): JustHealth, TWIN-X, ODELIA | FRAUNHOFER (DE): euroFMX, COMFORT, AIPD |
| TIMELEX (BE): AIRIS, AI4LUNGS, FLUTE | ETHNIKO KENTRO EREVNAS KAI TECHNOLOGIKIS ANAPTYXIS (EL): euroFMX, ELLIOT, vera.ai |
| ACCELER8 (MT): OMICS-STRATA | FORSCHUNGSZENTRUM JULICH (DE): AIRIS, TwinRISE, ELLIOT |
| TUM KLINIKUM (DE): NextGen, TWIN-X | UNIVERSITEIT VAN AMSTERDAM (NL): AIRIS, HealthIntelAct, ELLIOT |

After the analysis the shortlist is led by foundation-model projects
(euroFMX, ELLIOT) and AI-infrastructure partners (Fraunhofer, Jülich), which
match the call's "foundation models" and "AI Factories" better than the
title's generic AI-in-health hits.

## 3. HORIZON-MISS-2027-03-OCEAN-01

*Increasing riparian and coastal areas resilience to climate change,
including in waterfront cities and islands.* Found by `/api/calls?q=climate
adaptation of coastal communities`. Forthcoming, deadline 2027-09-21;
HORIZON-IA; EUR 35.7 million for about 4 grants; Food, Bioeconomy, Natural
Resources, Agriculture and Environment.

- Rule: three entities in three member or associated states, one in a member
  state. Canada: associated country (Pillar II).
- Topics: Increasing riparian and coastal areas resilience to climate change;
  Coastal and waterfront resilience solutions; Enhancing ecological
  functions; Reducing climate risks and vulnerability; Nature based solutions
  implementation (span "nature based soutions", the text's own typo); Water
  quality and erosion control.
- Expected outcomes: cost-effective, innovative solutions for riparian and
  coastal resilience; enhanced ecological functions of riparian and coastal
  areas; reduced vulnerability to climate-related risks; increased
  socio-economic benefits from protecting and restoring these areas.
- Partner profile:
  - public bodies managing those areas and their communities: "The participation of relevant public bodies managing those areas and their communities as partners of the consortium is strongly encouraged"
  - local competent authorities managing riparian and coastal areas: "Stakeholders and local competent authorities managing riparian and coastal areas, including in waterfront cities and islands"
  - island public authorities: "including relevant island public authorities"
- Dropped: 0.

| Before (title) | After (topics + partner profile) |
|---|---|
| UNIVERSIDADE DE AVEIRO (PT): COAST-SCAPES, REWRITE, JUST-COAST | UNIVERSIDADE DE AVEIRO (PT): COAST-SCAPES, HARCCA, JUST-COAST |
| CSIC (ES): COAST-SCAPES, REWRITE, m-CONNECT | CSIC (ES): COAST-SCAPES, m-CONNECT, POSIDONIArXiv |
| NTNU (NO): CO-WATERS, CLIMAREST, REMEDIES 5.0 | CMCC (IT): COAST-SCAPES, BEACONSplus, BlueAdapt |
| CNR (IT): Isla Bonita, REMEDIES 5.0, ROWER | UNIVERSITAT POLITECNICA DE CATALUNYA (ES): COAST-SCAPES, HARCCA, REHUBS |
| CNRS (FR): REWRITE, RESET, OCEAN CITIZEN | TARTU ULIKOOL (EE): ROWER, BIRGEJUPMI, SPHERE |
| ICLEI EUROPEAN SECRETARIAT (DE): CO-WATERS, Re-Value, CORRAL | ZMT (DE): m-CONNECT, BEACONSplus, SeaStrong |
| OBSHTINA BURGAS (BG, public body): CO-WATERS, JUST-COAST, Re-Value | DANUBE DELTA BIOSPHERE RESERVE AUTHORITY (RO, public body): JUST-COAST, ROWER, DaWetRest |
| ZMT (DE): BEACONSplus, SeaStrong, m-CONNECT | DANUBE DELTA NATIONAL INSTITUTE (RO): JUST-COAST, ROWER, DaWetRest |

Both lists are on topic; the analysed one adds climate-adaptation projects
(BlueAdapt, HARCCA) and wetland and riparian partners (Danube Delta), the
"riparian" half of the call that the title-only query underweights.

## Reading

- The span check works as meant: items whose quote is not in the text are
  dropped and counted, and the format failure of the first run showed up as
  dropped items rather than as unsupported claims.
- `gemma4:e2b` takes 3 to 7 minutes per call on the laptop while sharing the
  GPU; the nginx timeout for the route is 900 s and the result is cached per
  process. The 12B default model on the inference box should be faster and
  give longer spans for the partner profile.
- Short spans (single words such as "patients") pass the check but carry
  little evidence; a minimum of several words would be stricter but would
  also drop real one-word mentions. Left as is; revisit with B5's judge.
- The consortium rule is R5's two-way vocabulary (RIA/IA three entities,
  everything else one entity); actions outside it, such as COFUND, get the
  one-entity rule, and the page says the call's own conditions override it.
