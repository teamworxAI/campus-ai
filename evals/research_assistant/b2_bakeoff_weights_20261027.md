# Bake-off B2 follow-up: how reranked projects are weighted in partner search (card R3)

October 27-28, 2026, same 50 projects as `b2_bakeoff_20261026.md`, full research graph, EmbeddingGemma 2 +
Qwen3-Reranker-0.6B, pool 50. Raw table: `backtest_rerank_weights_20261027.md`.

## Verdict

**The reranker stays off by default for partner search.** The best variant, reciprocal rank fusion of the
reranked order with the fusion order (`rrf`), reaches recall@10 0.32 against 0.30 for fusion only: +0.02, under
the +0.05 bar (one more project out of 50). Weighting by the reranker's probability (the B2 baseline) loses
(0.24); weighting by reranked rank alone ties it on recall (0.24) but lifts MRR a little. The default weighting in
`partners` stays `probability`, used only when a reranker is passed; the `rank` and `rrf` switches stay in the code
for the 4B model and for later runs. No change to the R3 or D10 rows beyond this follow-up being noted in R3.

| Ranking | recall@10 | MRR |
|---|---|---|
| Fusion only | 0.30 (15/50) | 0.150 |
| Reranked, probability sum (B2 baseline) | 0.24 (12/50) | 0.129 |
| Reranked, rank weight 1/(60+rank) | 0.24 (12/50) | 0.157 |
| Reranked, RRF with the fusion order | 0.32 (16/50) | 0.155 |

The probability row is 0.24 here against 0.26 in the B2 report because partner search now takes the whole pool of
50 and cuts to 30 projects after weighting; it is the same method otherwise. Differences of one or two projects out
of 50 are within noise, so the honest reading is: weighting fixes the damage the probabilities did, but the
reranker adds nothing measurable on top of fusion here.

Not run: variant 3 (pool 20). Pool 50 took about 500 s per project on the loaded CPU; a pool-20 pass over the
winner would only be worth it if rrf had cleared the bar. The `--pool` switch exists (`backtest.py --pool 20`).

## What bounds reranking: the hidden partner is often not in the pool

The hidden partner took part in a project in the fused top 50 for **38 of 50 (76%)**, and in the fused top 30
(the projects partner search uses) for **31 of 50 (62%)**. In 12 projects (24%) no reranker could help, since the
organisation is in none of the 50 candidates; the pool or the embedding is the limit. Even a perfect reranker would
be capped near 0.76 recall, and the measured gap between fusion (0.30) and that cap is mostly not about ordering.

## Five misses by hand

Top fused projects (the hidden partner's project is in the fused top 50 where stated). I did not re-run the
reranker on these five (about 500 s each on CPU); the table above shows no variant finds any of them.

- **REPROCIT** (citizenship and reproductive law; hidden: European University Institute): not in the pool. The
  fused list is on topic (REPRO-NETS, REPRO-SCAPES, DIVREP, POSTCOLCIT) but the partners are other institutes.
- **PHENOS** (single-cell microfluidics and optics; hidden: Tor Vergata): not in the pool. On topic imaging
  projects (PLAST_CELL, NanoSCAN, VisioWell) with small consortia that do not include it.
- **SUSTAIN** (workforce wellbeing; hidden: Syddansk Universitet): in the pool only at fused rank 47. The top
  projects (INTERCAMBIO, PROSPERH) are workplace mental health, a nearby topic; a reranker at pool 50 can lift
  rank 47 but none of the variants did.
- **ELLE** (doctoral network on secure and safe AI; hidden: Cagliari): its project is at fused rank 1 and still a
  miss in every ranking. The top project (ELSA) has 26 organisations, the next ones 23, 17 and 22. Each
  organisation in a big consortium gets the same weight from the same project, so the hidden partner ties with
  about 25 others and the top 10 is a lottery.
- **MaGyQ** (geometry and quantum for machine learning; hidden: Piemonte Orientale): same pattern, top project
  CaLIGOLA with 33 organisations.

Two of the five are bounded by the pool, one by pool depth, and two by consortium size: a top project with 26-33
partners cannot rank its own members, whatever scores the projects get. Taking only the hidden partner's rank among
organisations of one project needs a per-organisation signal (the organisation's own text, its role, how many
matching projects it joined), not a better project score. That is a better next step than another reranker
weighting.

## Cost per query

- **CPU (loaded laptop, shared with other jobs, reranker in float32):** about 500 to 570 s per project to rerank a
  pool of 50 (mean 190 s per variant in the table because the cached variants cost only 3 s). The rank and rrf
  variants cost 3.2-3.4 s when the scores are cached, which is query embedding and the graph query. These are CPU
  timings under contention and must not be compared with the GPU figures.
- **GPU (B2 report, RTX 2050, GPU to itself):** 8-10 s per partner query with the reranker, about 1.7 s without
  it (mean 10.8 s with the first query's loading excluded).

The cost is the same for every weighting: the weights are arithmetic on one rerank. So no variant makes the
reranker cheaper, and none clears the bar that would justify the 5-6x slower query.

## Next

1. A per-organisation signal for partner search (see above), measured on this back-test.
2. Try the 4B reranker on the inference box with `--weightings rrf`.
3. Keep the reranker for expert search, where the probes improved and a query costs about 2 s.
