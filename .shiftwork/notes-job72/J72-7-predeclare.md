# J72-7 predeclaration — #207 round four, policy search on the judge-labelled DEV set

Written and committed BEFORE any dev number of this unit is computed (the dev labels J72-6-labels.q1..q4 have not been
read for scoring; only their row count). Nothing below changes after the first dev number exists; a change would be a new
predeclaration, committed and named in the note. Orchestrator ruling for this round: selection is on DEV (judge-labelled,
disjoint from gold and silver), never on gold. Silver is not used.

## Data, frozen
- Dev: `dev-prompts.jsonl` (60 prompts, ids 1001..1060), rows `cache/dev-rows.json` (J72-5, product `_pooled` walk),
  dev query vectors `cache/dev-<model>.queries.npz`, fact vectors `cache/<model>.facts.npz` (J72-1).
- Dev labels: the concatenation of `J72-6-labels.q1..q4.jsonl` (`{id, positives}`), one row per dev prompt; a missing
  or duplicated row is an error.
- Dev judged set per prompt: every name in `dev-candidates-provenance.jsonl` `proposed_by` (the union of the top 5 of B
  and of the three dense engines below). An injected name outside it is UNJUDGED: scored negative, and counted.
- Engines (the only ones with dev query vectors, and the ones the judged pool was built from):
  B = shipped BM25F view B; E1 = bge-m3 T0 Q0; E2 = qwen3-embedding:0.6b T1 Q3; E3 = snowflake-arctic-embed2 T0 Q4.
  Text/query variants are not searched this round.
- Metrics: J72-1 `lib.metrics` (precision over every injected pair; recall@3 over prompts with >= 1 positive, per-prompt
  |top3 ∩ pos| / |pos|; Thai recall@3 the same over Thai prompts). Inject cap 3 and display fixed; #199 constants untuned.

## Policy families (every family is evaluated with each of E1, E2, E3 as its dense side `c`)
Notation: `s` BM25F score, `w` layer/type weight, `ordered(x, mask)` = J72-1 `lib.ordered` (x*w desc, id), `take` = dedupe
by name, first 3. `Bl` = ordered(s, s > 0) (view B's list). `Dn(thr)` = DENSE-ONLY facts: ordered(c, (c > 0) & (s == 0) &
(c >= thr)). A threshold `thr` is one of: `abs a` (c >= a); `med m` (c >= median(c over the prompt's pool) + m);
`top r` (c >= r * max(c)). Grids: ABS = 0.30..0.80 step 0.025, MED = 0.00..0.40 step 0.025, TOP = 0.80..0.99 step 0.01;
THR = ABS ∪ MED ∪ TOP (69 thresholds).
- J72-1 families, unchanged, `lib.grid()` verbatim: BASE-E, 1a, 1b, 1c, 1d, 2a, 2b, 2c, 2d (392 points).
- (a) `Bu` B ∪ dense-high, capped: take(Dn(thr)[:k] + Bl); k in {1, 2, 3}, thr in THR.
- (b) `Bf` dense fill into B's empty slots: take(Bl + Dn(thr)); thr in THR.
- (c) `IL` rank interleave: B side = Bl filtered by a veto (none, or c >= v with v in abs 0.30..0.65 step 0.05 or
  med 0.00..0.30 step 0.05); D side = Dn(h) with h in abs 0.45..0.80 step 0.05, med 0.05..0.40 step 0.05,
  top 0.85..0.99 step 0.02; alternate one from each side, starting side in {B, D}; take 3.
- (d) `VF` veto + fill (2d with dense-only fill and relative gates): take(Bl filtered c >= v + Dn(h)); v in abs 0.30..0.65
  step 0.025 ∪ med 0.00..0.30 step 0.025; h in abs 0.45..0.80 step 0.05 ∪ med 0.05..0.40 step 0.05 ∪ top 0.85..0.99 step
  0.02. J72-1's 2d counts as this same family for the fallback rule.
- (e) `AG` per-prompt agreement: A = names in both B's top K and the dense engine's top K (K in {3, 5}; dense top K =
  ordered(c, c > 0)[:K]) with c >= lo (lo in {0, 0.30, 0.40, 0.50}), in Bl order; then Dn(h) (h in abs 0.50..0.80
  step 0.05, or none); then the rest of Bl with c >= v (v in abs 0.40..0.65 step 0.05, or `all` = no veto, or `drop` =
  none of them); take 3.

## Dev objective (mirrors the bar), with pB, rB = dev BASE-B precision@inject and recall@3
1. Feasible: dev r@3 >= rB + 0.01 AND dev p@inject >= pB + 0.05 AND injected >= 10 AND Thai r@3 > 0 AND
   unjudged <= 5% of injected. Winner = feasible point with the highest dev p@inject.
2. If none is feasible: among points with p >= pB + 0.05, injected >= 10 and the unjudged cap, the highest r@3 is the
   winner (reported as clause 2, not feasible).
3. If that is empty too: no winner, and NO gold look is spent.
Tie rule at every step: higher r@3 (clause 1) or higher p (clause 2), then fewer unjudged, then fewer injected, then the
simpler point: family order BASE-E, 1a, 1b, 1c, 1d, 2a, 2b, 2c, 2d, a, b, c, d, e; engine E1 < E2 < E3; then first in
grid order as written above.

## Gold looks (at most two; 4 spent before this unit; each logged in `gold-looks.jsonl` BEFORE it is scored)
- Gold set: 50 gold prompts; relevant = gold positives ∪ `notes-job72/pool-labels-merged.jsonl` (J72-3 included);
  judged = gold candidates ∪ `notes-job72/pool-targets-merged.jsonl`. B on gold = the shipped view B lists
  (`notes-job71/pool-injections-embed.json` `B_shipped`). Unjudged injected pairs give bounds: lower = all negative,
  upper = all positive (and added to B's relevant set for B's numbers under that bound).
- Look W = the dev winner (clause 1 or 2).
- Look F (fallback) = the best dev point by the same objective whose family differs from W's family. It is looked at
  ONLY if W does not pass the bar (p >= B + 0.05 and r@3 >= B) at its LOWER bound.
- No other policy is scored on gold. Unjudged gold pairs go to `J72-7-unjudged.jsonl` and to blind targets
  `J72-8-judge-targets.jsonl` (J72-2's targets rule, seed random.Random(20261021)). All gold numbers are UNVALIDATED.
