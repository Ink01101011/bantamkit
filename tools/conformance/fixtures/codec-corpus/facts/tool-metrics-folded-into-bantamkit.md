---
name: tool-metrics-folded-into-bantamkit
description: how bantamkit counts which skills tools and agents were ever invoked,
  where the usage ledger and its events log live, and which plugin folds are done
  versus pending
type: project
created: '2026-09-04'
last_recalled: '2026-09-15'
links:
- user-plugins-measured-only-bantamkit-lives
- skill-overlap-jaccard-refuted
- feedback-ship-it-working-and-measured
- feedback-verify-against-the-run-not-the-source
---

Job fold-tool-metrics CLOSED 2026-09-04, branch feat/tool-usage-ledger in bantamkit, 4 commits, NOT merged: 2ab54c7 ledger, 7f3fe9b test+fixture, 48ec9dc docs, 335d034 hook writer.

WHAT EXISTS NOW. `tools/ledger/tool-usage.mjs` — `--group tool|server|project|skill|agent`, `--since`, `--json`, `--root`, `--events`, `--no-events`. Honours CLAUDE_PROJECTS_DIR and TOOL_METRICS_DIR (the names metrics.py already read). It reuses token-ledger.mjs's recursive walker and adds the three things a naive scan gets wrong: dedupe by tool_use id (a resumed session rewrites blocks verbatim), Skill/Agent detail off the tool's own input, and an events.jsonl fallback read ONLY for sessions with no transcript left. metrics.py's cache/GC was deliberately not ported — a full 813-transcript scan is 1.24s.

THE GATE WAS AGREEMENT. 148 skill calls over 18 skills, row-identical to `metrics.py stats --group skill` on the live corpus, and identical on the checked-in fixture. Before the fallback it read 139/16 and the 9-call residual was accounted for exactly (4 of 110 logged sessions have no transcript on disk). `tools/ledger/tool-usage.test.mjs` pins each correction separately with negative controls; vacuity was checked by MUTATION — killing the id dedupe turns 4 red, dropping subagent recursion 5, letting the events log see live sessions 4, each time the correction's own assertion failing first.

THE TRAP THE PLAN MISSED, worth remembering as a shape: tool-metrics was the WRITER behind events.jsonl and only the reader had been folded in. Retiring it then would have left the read half alive and the write half gone — a silent starvation, not an error. Fixed by adding appendUsageEvent to the PostToolUse arm of tools/hooks/bantamkit-hook.mjs, using appendFileSync rather than the racy read-modify-write the read ledger uses. ALWAYS check whether a plugin being retired PRODUCES something, not only whether its consumers are ported.

RETIRED so far (enabledPlugins false, sources kept in kktest-dev): agent-loops and reflexion were already off; critique-gate, prompt-evolve, tool-metrics turned off this session. 9 of 14 plugins enabled now.

STILL PENDING: fold memory-keeper's archive + lint into bantamkit memory (which already has compact), THEN retire memory-keeper — that order, same additive-first reason. loop-ledger still undecided against shiftwork's overlap.
