---
name: claude-md-rules-chain-is-42-percent-of-the-floor
description: the largest token lever the user can pull without any code change - their
  own CLAUDE.md import chain, measured and bisected
type: project
created: '2026-09-04'
last_recalled: '2026-09-15'
links:
- read-lever-refuted-floor-is-the-ceiling
- project-token-levers-measured-on-real-corpus
- reference-session-token-arithmetic-corrected
---

Measured 2026-09-04 (unit R3 of the read-lever job) on the real transcript corpus.

The per-call context floor is NOT mostly system prompt. In `~/Documents/Claude/Projects/trader-platform` — the project that is 82.3% of the week's spend — the floor is 59,219 tokens, but the SAME probe in an empty temp dir pays only 25,960. So 56.2% of that floor is DIRECTORY-DEPENDENT, and R3 bisected 24,859 tokens of it to `CLAUDE.md` line 9 `@RULES.md`, which pulls in 17 further `@RULES/NN-*.md` imports. Reconstructing that chain alone in an empty dir gives 50,819.

That is 42% of the floor, in markdown the user wrote, re-sent on EVERY call.

Levers, measured against the week:
- trim the trader-platform @RULES chain  →  -10.47% of week tokens / -8.65% of spend
- cut every project to its bare-dir floor →  -14.80% / -12.22%

Probe calibration passed: `--append-system-prompt` of 5,000 and 10,000 " apple" tokens moved the counter +10,011 and +20,011 (ratio 1.9989, exactly linear). Two probe arms are REFUTED as zero-effect: `--plugin-dir /dev/null` and `--allowedTools Bash Read` both returned cache_read=59,217 cache_creation=0, a complete cache hit on a byte-identical prefix. Stripping every MCP server saves only 882 tokens, then 293 more — bantamkit's schemas are NOT the cost.

Artifacts: .shiftwork/briefs-readlever/R3-findings.md and scratchpad/r3/{floor_audit,cost_audit,price_solve,price_solve2,strata,final}.py + probe.sh.
