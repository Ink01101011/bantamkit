---
name: seven-tools-audited-by-running-them
description: which bantamkit tools actually work when you run them - three were silently
  broken, one saw 38 percent of memory, and the local-model implementer is 0 for 20
  on real repo work
type: project
created: '2026-08-22'
last_recalled: '2026-09-19'
links:
- shiftwork-unit-cost-is-linear-in-tool-calls
- project-mcpdrift-hangs-on-a-mute-endpoint
---

Audited 2026-08-22 by RUNNING each of the seven programs under tools/, not by reading them. Root cause shared by three of the failures: grep -n "tools/" .github/workflows/ci.yml returns NOTHING for all seven, so no field program is invoked by anything that runs on a push - RB-P41 one step worse than the shape it names. WORKS AND IS USED, proven this session: shiftwork (16 units clocked; its accounting log is the only reason 2,514 tokens/tool-call could be measured at all) and amendguard (rejected the FIRST register draft of both W11 and U2 with STAMP-MISSING). WAS SILENTLY BROKEN, now fixed and gated in PR #67 (merged cdbfeca): pinharness had been unable to run since #64 because W13 moved the code B01/B02 anchor on, so anchors matched 0x and assert_anchors_apply refused every sweep - found only by running it by hand a day later; mcpdrift's _Session.request looped on readline() with NO deadline (--timeout was applied in close() only) so a server that launched and went quiet hung forever on every platform, fixed with a watchdog thread rather than select because select does not work on pipes on Windows; devteam's build_tasks.py check works and NOTHING called it, although its own docstring says it exists to stop a hand-edited task silently decoupling from the manifest. HALF-BLIND: memory_recall could see only 21 of 55 facts after the first merge, because the merge ran one direction (bantamkit -> native) and the tool reads the OTHER store; now 59 = 59 both ways. WORKS BUT THE CAPABILITY DOES NOT EXIST: qwen-implementer's rig is sound - smoke answers in 43s, 3374+136 tokens, search/replace blocks parse - but the recorded RB-P27 attempts are 20 FAIL out of 20 across qwen2.5-7b (10), qwen3-4b (5) and qwen2.5-14b (5): 7 apply-failed where the SEARCH text matched 0 or 19 times instead of exactly 1, 8 ruff-failed on syntax errors and undefined names, 5 spec-red where the patch applied and linted but left 3 tests failing. On the SYNTHETIC eval workload the same family passes 347 of 528 = 65.7 percent, which is a different task set and must not be quoted as if it were repo work. CONSEQUENCE: do NOT plan to offload real implementation to a local model as a token strategy - it is measured at 0 for 20. The instrument is worth keeping as a measurement, not as a worker.
