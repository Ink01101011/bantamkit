---
name: read-lever-refuted-floor-is-the-ceiling
description: whether bantamkit_read actually reduces tokens on real sessions, why
  the reader lever has no opportunity set in code work, and what the context floor
  caps every lever at
type: project
created: '2026-09-04'
last_recalled: '2026-09-15'
links:
- project-token-levers-measured-on-real-corpus
- reference-session-token-arithmetic-corrected
- compaction-ceiling-is-fixed-overhead
- tool-call-batching-is-already-spent
---

Measured 2026-09-04 over 2026-08-29..09-04 of this machine's Claude Code usage. Audited by unit R1 of job `readlever-audit`; R2/R3/R4 still open at time of writing.

**bantamkit_read is REFUTED as a token lever.** Simulating the real handler against the actual recorded tool_result bytes: **median -16.38%** (n=597 drift-free strict pairs), i.e. the reader costs ~16% MORE than what was paid. It is cheaper on **0 of 597 calls**; the single most favourable call in the whole corpus is -9.21%, under every friendlier counterfactual tried (limit=200, manifest not charged, only hunted slices, per size band). Amplification is **3.09x** — 1,842 reader calls to replace 597 shell calls — and 4.68x at the tool's advertised default limit=50. The extra round trips each re-send the whole prefix, and THAT, not the bytes, is the real cost.

**THE ORCHESTRATOR'S FIRST FIGURE, -77.27%, WAS WRONG — do not quote it.** Two artifacts, both biasing against the reader: (1) FILE DRIFT — the baseline is a week-old transcript byte count while the treatment re-extracts the file as it is today (2026-09-11); only 17.3% of pairs still describe the same bytes, median drift +26.46%. (2) CORPUS POLLUTION — a regex matching `head`/`tail` anywhere in a pipeline counted `grep -rn ... | head -60` as a file ingestion and scraped grep PATTERNS as paths, inflating 651 real single-file ingestions to 4,247. **Generalisable: any retrospective measurement that re-reads today (2026-09-11)'s file against a historical transcript byte count is measuring drift unless it proves the file is unchanged.**

**The load-bearing fact survived and got stronger: binary-document demand is ZERO.** Over all 7,969 W4 tool calls, 90 name a binary-document path and **86 of those are job43's own docread fixtures inside the bantamkit repo**. Zero Read calls on a binary document; zero calls of any kind invoking a content extractor. The 94.77% reader lever is real and its opportunity set in code sessions is empty. What actually enters context is .py, .md, .ts — already text, where `cat` is the optimal digest.

**The ingestion path is not the Read tool**: 177 Read calls that week against thousands of Bash file streams.

**THE FLOOR IS THE REAL CEILING.** Probed live with `claude -p` in trader-platform: call #1 costs **59,433 prompt tokens before any work**. Stripping every MCP server saves **882 tokens (1.5%)** — bantamkit's own schemas are not the cost, and removing them is not a lever. `--plugin-dir /dev/null` and `--allowedTools Bash Read` give 58,339; only replacing the system prompt moved it (54,788). Floor x 7,416 calls = 0.379 B = **28.7% of the week's 1.323 B**, immovable by compaction, so the ceiling on any context-side lever is **-71.3%**. (Under audit by R3.)

**A token-reduction % is NOT a cost-reduction %**: 97.58% of the week's prompt tokens are cache_read, priced differently from base input.

Instruments in the session scratchpad: week_review2.py, week_review3.py, traj.py, and R1's R1_extract/R1_measure/R1_drift/R1_binary/R1_handler_check.py. Findings: .shiftwork/briefs-readlever/R1-findings.md.

See [[project-token-levers-measured-on-real-corpus]], [[reference-session-token-arithmetic-corrected]], [[compaction-ceiling-is-fixed-overhead]], [[tool-call-batching-is-already-spent]].
