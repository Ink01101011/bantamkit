---
name: exflow-as-shiftwork-dag-measured
description: can ex-flow (the user's npm DAG planner) become bantamkit agent/subagent
  tools — the measured parallelism, the four blockers, and the route B decision now
  specced as PR 101
type: project
created: '2026-09-18'
last_recalled: '2026-09-18'
links:
- worktree-traps-pytest-and-conformance-venv
- feedback-never-mutate-a-file-a-live-unit-holds
- differential-is-blind-to-symmetric-regression
- public-install-is-pure-node-by-ruling
---

Probed and specced 2026-09-18. Worktree .claude/worktrees/exflow-agent-tools, branch docs/workplan-dag-spec, cut from main 6666d8b. **PR 101 OPEN (spec only, not implemented).**

WHAT EX-FLOW IS: ex-flow@1.1.0 (npm, MIT, user-authored, dep `exsorted`) is a PLANNER ONLY — Kahn topological sort returning `batches` + `fullSequence`, priority/deadline/weight tie chain, cycle detection, concurrency+resource caps, fairness aging, throughput mode. Never executes or spawns. Loads on Node 25.2.1; CJS dist, named imports work from runtime-ts's ESM/NodeNext.

THE FIT: `assets/schemas/shiftwork-checkpoint.json` already stores `plan.units[].depends_on`; both runtimes ignore it deliberately (runtime-ts/src/shiftwork.ts:50, runtime-py/src/bantamkit/shiftwork.py:69). Advance is `cursor = remaining[0].id` (shiftwork.ts:643, shiftwork.py:490). No topological sort exists anywhere in the repo.

MEASURED (rerun: feed every .shiftwork/*.json plan.units into ExFlow as {id, dependsOn: depends_on}): 19 checkpoints, 215 units -> 119 batches, 96 serial steps saved (44.7%), 11/19 with parallelism, ZERO cycles, ZERO unknown deps. job46 32->5 (11,9,7,4,1); job44 21->5 (12,4,2,2,1); job41 9->3 (7,1,1).

THE RISK, ALSO MEASURED: job44's 12-wide batch 1 — 7 of the 12 units name runtime-ts/src/docread.ts in their briefs, 5 name docread.py, 3 name memory/store.ts. `depends_on` is logical order, not file contention.

USER RULING: **route B** — ex-flow is the SPECIFICATION, hand-write Kahn in both runtimes, take NO dependency. Rejected: (A) dep in runtime-ts + port to py, (C) Node-only divergence. Reason B wins: runtime-ts has exactly one runtime dep (@modelcontextprotocol/sdk) and docs/porting.md cites that rule as the live justification for REFUSING pdf/bzip2/lzma.

SHAPE (user picked "core + 2 surfaces"): Layer-1 `workplan.py`/`workplan.ts` `plan(nodes)->{batches,sequence,width}`; Layer-2 assets `work_plan.json` + `shiftwork_plan.json`; Layer-5 adapter `plan_batches`/`planBatches`. Both READ-ONLY; clock_in/clock_out/cursor/schema untouched. done|dropped units are satisfied; priority 0 for all (no schema change).

ARTEFACTS: spec `docs/superpowers/specs/2026-09-18-workplan-dag-design.md` (TRACKED — note `docs/specs/` does NOT exist, the tracked dir is `docs/superpowers/specs/`); plan `.shiftwork/checkpoint-workplan.json` + `.shiftwork/briefs-workplan/W1..W8.md` (GITIGNORED — `.gitignore:12` excludes all of `.shiftwork/`, so the unit table was put INTO the spec to stay reviewable). 8 units, widths 3,2,1,1,1.

See [[worktree-traps-pytest-and-conformance-venv]] for the two worktree gotchas measured here.
