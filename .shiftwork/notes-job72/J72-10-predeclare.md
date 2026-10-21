# J72-10 predeclaration — #207 round 4b, re-search on the fully judged DEV set, at most one gold look

Written and committed BEFORE any dev number of this unit is computed. Only counts of the merged label file have been read
(60 rows, 100 positives, 929 judged pairs; the J72-8 merge helper re-run to a scratch file is byte-identical to
`dev-labels-merged.jsonl`). Nothing below changes after the first dev number exists. Selection is on DEV only; gold is
never used to choose anything; silver is not used.

## Data, frozen
- Everything in `J72-7-predeclare.md` "Data, frozen", except the labels: rel = `dev-labels-merged.jsonl` `positives`,
  judged = `dev-labels-merged.jsonl` `judged` (J72-8 helper output). An injected pair outside `judged` is UNJUDGED:
  scored negative, and counted.
- Grid: J72-7's `pol.grid()` x engines E1/E2/E3, unchanged (2,576 policies x 3 = 7,728 points). Metrics: J72-1
  `lib.metrics`. #199 constants untuned; inject cap 3.
- The "before" table is recomputed with J72-7's inputs (J72-6 labels, provenance judged) by the same script, and must equal
  J72-7's table.

## Objective: J72-7's clause 1, unchanged
With pB, rB = dev BASE-B p@inject and r@3 on the merged labels: a point is FEASIBLE iff dev r@3 >= rB + 0.01 AND dev
p@inject >= pB + 0.05 AND injected >= 10 AND Thai r@3 > 0 AND unjudged <= 5% of injected (the cap is kept).
There is NO clause 2 and NO clause 3 this round: no feasible-and-robust point means MISS.

## Robustness rule (against selection optimism), applied before any gold look
- Five bootstrap resamples of the 60 dev prompts, drawn once before scoring: `rng = random.Random(20261023)`;
  `ids = sorted(dev ids)`; resample b (b = 1..5, in order) = `rng.choices(ids, k=60)` (with replacement; multiplicity kept).
- On a resample, metrics are J72-1's with multiplicity: p = sum of hits / sum of injected over the sampled prompts;
  r@3 = mean of per-prompt |top3 ∩ pos| / |pos| over sampled prompts with >= 1 positive. B is rescored on the same
  resample. Unjudged pairs are negative, as on full dev.
- A point passes resample b iff p_b >= pB_b + 0.05 AND r@3_b >= rB_b + 0.01 (1e-12 tolerance, as J72-7).
- ROBUST = feasible on full dev AND passes >= 4 of the 5 resamples.
- Winner = the robust point with the highest full-dev p@inject; tie rule J72-7 clause 1 (higher r@3, fewer unjudged,
  fewer injected, family order, engine order, grid order).
- If no point is robust: report MISS on dev and spend NO gold look.

## Gold look: exactly ONE, the robust winner, no fallback
- Procedure = J72-7 `goldlook.py` (relevant = gold positives ∪ `pool-labels-merged.jsonl`; judged = gold candidates ∪
  `pool-targets-merged.jsonl`; B = `notes-job71/pool-injections-embed.json` `B_shipped`; lower/upper bounds over
  unjudged pairs). Run through a variant `J72-10-scripts/goldlook10.py` that differs only in labelling: unit `J72-10`,
  tag `W10`, outputs `J72-10-gold-inject-W10.json` and `J72-10-unjudged.jsonl`. It logs look-start to
  `gold-looks.jsonl` before scoring.
- The bar: PASS iff p >= B + 0.05 AND r@3 >= B (reported at lower and upper bound; all gold numbers UNVALIDATED).
- Its unjudged gold pairs become blind judge targets `J72-11-judge-targets*.jsonl` by J72-7-rescore.py's `targets` rule
  (J72-2 copies, drop already-judged, sorted then shuffled per prompt by random.Random(20261024)).
- No other policy is scored on gold. `tools/eval/recall/bar.json` is not touched.
