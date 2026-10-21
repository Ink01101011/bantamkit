# J72-1 predeclaration — #207 round three, offline strategy search

Written and committed BEFORE any silver (or gold) number of this unit is computed. Nothing below
may change after the first silver number exists; a change would be a new predeclaration, committed
and named in the note.

## Data, frozen
- Silver: `.shiftwork/notes-job68/silver.jsonl` (n=70), view B only (bantamkit layers + the row's own
  project's auto-memory copy, via `session-slug.json`), stores = rsync copies of `notes-job68/stores/`.
- Gold: the 50 prompts of `notes-job68/gold-labels.jsonl`; native copy picked through the silver row
  with the same prompt text (inject_embed.py's rule). Relevant = gold positives ∪ merged pool positives
  (`notes-job71/pool-labels-merged.jsonl`); judged = gold candidates ∪ merged pool targets.
- Extraction reads gold PROMPTS (id, prompt, thai) only, to precompute vectors and candidate rows.
  Gold labels are read only by the gold-look script, only for the policies named below.
- Per row of each view's layered memory (the product's own `_pooled` walk, dense full pools): name,
  layer order, BM25F score (the shipped constants), weight (type/stale; usage ledger empty, sandbox
  HOME), and a cosine per (model, fact text, query rule). Every policy is then pure Python.

## Policy = an inject rule producing an ordered list of <= 3 names (deduped by name, first wins)
recall@3 is measured on that list, exactly as `score_pooled.py` measures it.
- BASE-B: shipped BM25 view B (admit s_b > 0, order round(s_b*w) desc, id). The reference.
- BASE-E: J71-5's point: admit c > 0 and c >= 0.6, order c*w. The embedding baseline.
- F1 relative / adaptive dense gates (order c*w):
  1a c >= median(c) + m, m in 0.05..0.40 step 0.025
  1b c >= r * max(c), r in 0.80..0.99 step 0.01
  1c z-score within the prompt (c-mean)/sd >= z, z in 1.0..6.0 step 0.25
  1d c >= max(g, r*max(c)), g in 0.40..0.60 step 0.05, r in 0.85..0.98 step 0.01
- F2 hybrid inject rules (no score fusion):
  2a BM25-admitted hits (s_b > 0) with c >= g, re-ordered by c*w; g in {0, 0.30..0.65 step 0.025}
  2b BM25 list ∪ dense-only hits with c >= h; h in 0.50..0.80 step 0.025; two orders:
     dense-high first then BM25 order ("D>B"), or BM25 order then dense-high ("B>D")
  2c cosine veto on BM25: BM25 order, drop hits with c < v (v in 0.30..0.65 step 0.025), or with
     c < median(c) + m (m in 0.0..0.30 step 0.025)
  2d veto + fill: 2c's absolute veto v, then remaining slots filled by dense-only c >= h, grid v x h
- F3 fact text: T0 = name(hyphens->spaces) + ": " + description + " " + keywords (shipped);
  T1 = T0 + " " + body[:200]; T2 = T0 + " " + body[:500]; T3 = description alone; T4 = name + ": " + description.
- F4 query: Q0 = prompt[:2000] (shipped); Q1 = last 500 chars; Q2 = last 1000 chars; Q3 = first 500;
  Q4 = chunks: the first 4000 chars split on newlines/sentence ends, packed into chunks of <= 400 chars,
  at most 8 chunks, cosine = max over chunks.
- F5 model: bge-m3 (shipped), nomic-embed-text (prefixes `search_query: ` / `search_document: `),
  and, if the pull succeeds, qwen3-embedding:0.6b (query prefix `Instruct: Given a user's prompt to a
  coding assistant, retrieve the memory notes relevant to it\nQuery: `) and snowflake-arctic-embed2
  (query prefix `query: `). A model whose warm Q0 query p50 on the silver prompts exceeds 100 ms is out.
- F6 (inject cap 3, display, #199 constants): not tuned.
Every F1/F2 rule is evaluated over every (model, text, query) cell; the family tables report each
family's silver-best point.

## Selection objective (silver only), mirroring the bar's shape
Constants from `notes-job68/tuning.json` `current.B` (the shipped BM25 view B on silver):
R_B = 0.16785714285714284 (recall@3), P_B = 0.09183673469387756 (precision@inject).
1. feasible = silver view-B recall@3 >= R_B AND Thai recall@3 > 0 AND injected >= 10.
   Winner = feasible point with the highest precision@inject.
2. If nothing is feasible: winner = highest recall@3 among points with precision@inject >= P_B + 0.05*P_B/0.4317
   (the bar's +0.05 margin scaled to silver's precision level, = P_B + 0.01064); if empty, report "no point".
3. Ties at every step: higher recall@3, then fewer injected, then the simpler point in this order:
   BASE < F1 < F2; model bge-m3 < nomic < qwen3 < arctic; T0 < T1..T4; Q0 < Q1..Q4; then grid value
   nearest the shipped one.
Silver precision is reported alongside its margin over P_B.

## Gold looks (rationed; each logged as one line in gold-looks.jsonl BEFORE it is read)
At most three policies, all fixed by rule now:
- G1 = the silver winner.
- G2 = the best point by the same objective whose policy family (F1 vs F2, BASE counted as F1)
  differs from the winner's.
- G3 = the best point by the same objective on the shipped inputs (bge-m3, T0, Q0) if the winner
  does not use all three; otherwise the best point on a different model.
For each: precision@inject, recall@3, Thai recall@3, injected, against BASE-B on the same pool;
unjudged injected names give bounds (lower = all negative, upper = all positive, the upper also
added to the relevant set for recall of BOTH the policy and BASE-B). Unjudged names go to
`J72-1-unjudged.jsonl` (prompt id, fact name only). They are not judged here. All gold numbers UNVALIDATED.
