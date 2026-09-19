---
name: memory-budget-precondition-discharged
description: whether the memory consolidation blocker still needs an MCP server restart,
  and the re-measured store sizes that replace the stale prep-probe numbers
type: project
created: '2026-08-22'
last_recalled: '2026-09-12'
links:
- project-memory-consolidation-ruling
- project-two-memory-stores-compete
- project-build-identity-describes-disk-not-process
---

DISCHARGED 2026-08-22 22:55, no restart needed. The 24000 default landed in 4c04281 (PR #63) at 10:55; this session's MCP server (pid 50829, parent = this claude process) started 17:27, i.e. AFTER. Proof it is live and not inferred from source: .bantamkit/memory/index.md is 13,020 bytes and was rewritten at 20:59 — a save at 13,020 B cannot happen under a 4096 budget. The "MCP server restart is the precondition" line in [[project-memory-consolidation-ruling]] is now satisfied; do not re-litigate it. Second server pid 34377 belongs to a DIFFERENT claude session (parent 34333) — never kill it when restarting.

RE-MEASURED INPUT STATE, replacing the prep probe's 20+24=44 facts / 8863 B, all of which are stale: bantamkit store 63 facts, index 13,020 B, archive EMPTY (0 files). Native store 60 files, MEMORY.md 11,197 B. Both denominators roughly tripled since the probe, so every merge arithmetic in the ruling must be recomputed before the conversion step runs.
