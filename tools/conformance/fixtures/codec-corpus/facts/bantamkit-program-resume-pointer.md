---
name: bantamkit-program-resume-pointer
description: how to resume bantamkit program work after a cleared context, and why
  PR 32 is not merged
type: project
created: '2026-08-21'
last_recalled: '2026-09-18'
links:
- j2-compaction-predeclarations
---

Resume: read `.shiftwork/backlog.md`, then `shiftwork_status` on `.shiftwork/checkpoint.json`. Never resume from a summary of a summary.

J1 `devteam-workload-and-null-control`: all 8 units done and independently re-verified by the orchestrator. PR #32 is ready (MERGEABLE/CLEAN, no approval required) but NOT merged. BLOCKED because the user's merge authorization was given in a live turn, then only survived a `/compact` as a model-written summary — and the auto-mode classifier correctly refuses to treat that as approval. Unblock = the user restates it, or a Bash permission rule. `tag` was never authorized. When merging: squash (repo convention, linear main) and KEEP the branch, since squashing leaves the 40 MEASURED-BEFORE-WRITTEN commit bodies reachable only via the branch ref.

Result: `>60%` has no measurable surface; R1 arithmetic refutes it (ceiling 5.819%, k=7 needed), the RUN is UNINFORMATIVE under R3 (0 repeat reads, 8/8 tasks). Ladder medians 15920/15920/15920/27600 → +0.000%/+0.000%/+73.367%. Raw row sum gives +89.007% and that is NOT a contradiction — both central values are pre-registered at bar-preregistration.md:682. Ten findings RB-P36..RB-P45, none fixed.

Next: J2 `compaction-measured` under frozen pre-declarations (bantamkit transcripts only, numbers-only artifacts, qwen2.5:14b-instruct, recall mode still to pre-declare).

GOTCHA: two separate memory stores. This MCP store is repo-scoped — `memory/layers.py:11` sets `PROJECT_STORE = Path(".bantamkit")/"memory"`, a RELATIVE path — so a session whose cwd is elsewhere recalls a different, possibly empty store. An empty recall is NOT proof there is no prior work. The file-based store at `~/.claude/projects/<slug>/memory/` is the auto-loaded one.
