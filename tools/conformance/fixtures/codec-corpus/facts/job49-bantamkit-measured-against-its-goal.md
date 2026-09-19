---
name: job49-bantamkit-measured-against-its-goal
description: what a month of real bantamkit use actually produced - the 0.14 percent
  injection follow rate, the one automatic lever that works, and the 12 bugs job49
  filed
type: project
created: '2026-09-12'
last_recalled: '2026-09-19'
links:
- project-goal-clear-roadmap-toolbox
- project-two-memory-stores-compete
- feedback-orchestrator-numbers-from-recall
- shiftwork-unit-cost-is-linear-in-tool-calls
---

CLOSED 2026-09-12. job49-bantamkit-usage-audit, 4 fable units, notes in
.shiftwork/notes-job49/A{1,2,3,4}.md (119 KB), register appended to
.shiftwork/backlog.md as J49-B1..B12 / F1..F10 / I1..I6.

THE VERDICT. bantamkit is 1,280 of 51,407 tool calls (2.49%) over 71 sessions and
7 project dirs. docs/roadmap-toolbox.md's goal — "cheaper and smarter WITHOUT
ANYONE TRIGGERING IT" — is NOT MET on either axis. Bill is measured: 695 prompt
tokens per request for registration (four-arm `claude -p` probe in an empty dir,
20,867 vs 20,172 on the same cache_read prefix) plus 930,544 B of injections in
15.8 days, together ~35-42 M tokens = 0.75-0.9% of prompt tokens since the hook.
Return is ZERO measured. Axis 1 is UNMEASURABLE without a paired hook-on/off run
over fixed content; the -4.9% in median prompt tokens across the hook date is
confounded (trader-platform went 1 -> 165 sessions).

THE NUMBER THAT DECIDES MEMORY: 2 of 1,453. The hook's injection header carries
92.6% of every recall event the store has ever produced and is followed by the
memory_recall it asks for 0.14% of the time. Root cause is STORE BINDING, not
ranking: three of four projects have no store, so discoverProjectStore walks up to
~/.bantamkit/memory while the server wrote their saves into the bantamkit repo
store until 2026-09-11 — 39 facts unreachable from the cwd that wrote them.

THE ONE AUTOMATIC LEVER THAT WORKS: the Stop nudge. 57 nudges -> 61 memory_save
in 45 sessions = 46% of all post-hook saves. It asks for an action at a moment the
agent is already stopping. Worth porting (J49-I4).

TOOL MORTALITY: 4 of 14 never called. memory_compact and memory_dream are dead BY
SUCCESS (the hook does their job: 58 dream + 79 dream-skip + 4 auto-compact vs 0
manual). repo_map and token_ledger lost to Bash — and so did the builtin Grep and
Glob, which have 0 calls in all 51,407 blocks because auto-mode routes everything
through Bash (43,381). validate_json is the only genuine abandonment.

SHIFT-WORK: the failure mode is INVERTED from the obvious one. 373 of 379 briefs
got a clock_out, but 98 of 471 clock_outs (20.8%) had NO BRIEF — clock_out never
checks. 125 refusals, ZERO false, but 65% friction. The ledger's `tokens` column
excludes cache reads (97.7% of tokens): ledger 49.3 M vs real 2,462 M, while
duration_ms and tool_uses are exact. One proven cross-session resume in the whole
history (M2, 82.6 h later, handoff byte-identical).

LIVE DATA LOSS, unfixed at close: the dream self-merge archived all 20 profile
facts on 2026-09-10; 14 are still in ~/.bantamkit/memory/archive/ and SessionStart
injects 6 instead of 20. Roadmap row 13 fixed the mechanism, not the damage.
J49-F1 is the first thing to do.
