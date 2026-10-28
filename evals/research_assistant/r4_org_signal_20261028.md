# R4 follow-up: a direct per-organisation signal in partner search

October 28, 2026, full research graph (24k Horizon Europe projects, 36k organisations), EmbeddingGemma 2, fusion
only (no reranker), 100 most recent projects with a Canadian participant. Raw tables: `backtest_signals_20261028.md`
(question without the project's acronym) and `backtest_signals_acronym_20261028.md` (the project's text as is).

## Verdict

**The direct signal stays off: `partners(signal="projects")` remains the default.** Searching the Organization
nodes themselves reaches the hidden partner 5 times in 100 (8 with the acronym leak, below). Fused with the
project-derived order by reciprocal rank fusion it is at best level with projects alone on recall@10 (0.29 vs 0.28,
one project) and lower on MRR (0.109 vs 0.125); with equal weight it loses (0.22). The bar was a clear lift over
0.30; nothing came near it. The code stays behind `signal=organisations|fused` (and `organisation_weight`) on
`ResearchSearch.partners`, `/api/partners?signal=` and `backtest.py --signals`, so later changes to the organisation
text can be measured in one run. The API and the web page are unchanged by default.

Question without the project's acronym (the fair measurement, see below):

| Ranking | recall@10 | MRR |
|---|---|---|
| projects (today's: the matching projects' organisations, coordinators 1.25x) | 0.28 (28/100) | 0.125 |
| organisations (the Organization nodes matched directly) | 0.04 (4/100) | 0.035 |
| fused (RRF of the two orders, equal weight) | 0.22 (22/100) | 0.072 |
| fused:0.5 (the direct order at half weight) | 0.29 (29/100) | 0.109 |
| fused:2 (the direct order at double weight) | 0.05 (5/100) | 0.045 |

The project's text as is (comparable with the earlier reports, which asked this way):

| Ranking | recall@10 | MRR |
|---|---|---|
| projects | 0.32 (32/100) | 0.133 |
| organisations | 0.08 (8/100) | 0.040 |
| fused | 0.20 (20/100) | 0.063 |
| fused:0.5 | 0.28 (28/100) | 0.097 |

Projects alone at 0.32 on 100 projects agrees with the 0.30 on the first 50 (`backtest_rerank_weights_20261027.md`).

## Pool statistics: the direct signal does not reach what the projects miss

- Hidden partner took part in a project in the fused top 50: 73 of 100; in the top 30 that partner search uses:
  61 of 100 (62 with the acronym).
- Hidden partner's own node among the top 50 Organization hits: **5 of 100** (8 with the acronym); all 5 are in the
  top 30.
- Reachable by either signal within 30: 62 of 100 (65 with the acronym). The direct signal adds one project to the
  reachable set; the 38 projects whose partner no candidate reaches stay out of reach.

So fusion cannot help: there is almost nothing to fuse. What the direct order does is push its own top hits (large
organisations whose eight-term field lists happen to overlap the topic) into the top 10, which is why `fused` and
`fused:2` lose and `fused:0.5` only breaks even.

## Why the organisation text does not match a project description

An organisation's text is its name, country and type, up to eight EuroSciVoc terms from across all its projects, and
the acronyms of its four most recent projects (`cordis.py`). A project's question is a 1500-character objective. The
five direct hits show what does match:

- **Brain-MuSE** (Aix-Marseille), **BEST** (Toulouse), **QUA** (Paris I Panthéon-Sorbonne), **REACH-UPPA** (Pau):
  the project's objective names the city or university. Fulltext on the name, not meaning.
- **ELLE** (Cagliari, doctoral network on secure AI): a genuine fields match (machine learning; computer security),
  and the one case where the direct signal fixes a known miss: the project-derived order ties Cagliari with the 25
  other members of the top project (`b2_bakeoff_weights_20261027.md`), the direct order breaks the tie and `fused`
  ranks it 2nd.

The pattern is the ELLE case: a direct signal is the right tool to order the members of a large consortium, but
the eight-term profile is too thin and too mixed (a university's terms span oncology to internet of things) to put
the right member in the top 50 of 36k organisations on its own. A richer organisation text, e.g. the objectives of
its recent projects or a per-field profile, might change this; the `--signals` run is in place to measure it.

## The acronym leak

Every project's text starts with its acronym, and the hidden partner's own text lists that acronym in 40 of the 100
cases (it is among the organisation's four most recent projects, and the back-test takes the most recent projects).
Asking with the text as is lets fulltext find the organisation by the acronym: a back-test artefact, since a user
with a new idea has no acronym in the graph. `backtest.py --no-acronym` strips it (whole-word, case-sensitive) from
the question for every variant. Even with the leak the direct signal only reaches 8 of 100, so the conclusion does
not depend on it; the fair run is the one reported first.

## Cost

With the query embedding cached per project, a variant costs 0.1-0.4 s warm (two Neo4j searches for `fused`). The
`projects` column of the no-acronym run shows a 16.8 s warm mean because 8 of its 100 queries, the first in each
project and the ones that embed, ran while another job held the GPU; the as-is run shows the real 0.4 s.
