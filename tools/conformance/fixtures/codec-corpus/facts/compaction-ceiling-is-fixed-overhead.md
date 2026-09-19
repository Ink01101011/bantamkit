---
name: compaction-ceiling-is-fixed-overhead
description: how far compaction can actually be pushed - 66.62 percent of total tokens,
  84.53 percent of the movable part, and the 21.2 percent fixed overhead is what makes
  80 percent impossible
type: project
created: '2026-08-22'
last_recalled: '2026-09-15'
links:
- project-j2-compaction-measured-result
- project-token-levers-measured-on-real-corpus
- recall-before-declaring-a-target-refuted
---

Re-derived 2026-08-22 from the raw J2 rows (docs/eval-data/2026-08-18-compaction-arms.jsonl, 600 rows, stratum A, median over 3 repeats). ANSWERS "how far can compaction be pushed", which the earlier note did not. Effective set = the 24 of 50 transcripts with >=1 boundary under B1 (distribution: 26 transcripts have 0 boundaries, 16 have 1, 6 have 2, 1 has 3, 1 has 4). Per arm, effective n=24, ratio of sums: B1 compaction -52.36% of TOTAL tokens and -66.43% of the MOVABLE part; B2 +trim -63.94% / -81.13%; B3 +offload -66.62% / -84.53%. THE STRUCTURAL ANSWER: B0 with fixed = 159,046,155 tokens, no fixed = 125,355,739, so the FIXED OVERHEAD IS 33,690,416 TOKENS = 21.2 PERCENT OF B0 AND NO ARM CAN MOVE IT. That sets a HARD CEILING of -78.8 percent on total tokens even if the movable part went to exactly zero, so >80 percent is arithmetically impossible for compaction ALONE regardless of summarizer quality. On the movable part alone, 80 percent IS exceeded: B2 -81.13%, B3 -84.53%. THE PRICE, and it is not small: anchor retention 0.0548 / 0.0527 / 0.0613 for B1/B2/B3, i.e. 2,824 of 2,894 anchors lost at B3 - 97.6 percent destroyed. RECONCILIATION with the earlier -40.14% figure, which was right about itself and answered a different question: -40.14% is the MEDIAN OF PER-TRANSCRIPT RATIOS on with_fixed over the effective 24; the ratio of sums on the same field and set is -52.36%. Both are honest, they are different estimators, and the aggregation must be named every time. WHERE THE REMAINING 21.2 PERCENT MUST COME FROM: the fixed part is system prompt plus tool schemas. Deferred tool loading attacks exactly that and compaction cannot.
