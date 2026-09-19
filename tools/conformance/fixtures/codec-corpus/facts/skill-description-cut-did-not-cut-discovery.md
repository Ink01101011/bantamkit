---
name: skill-description-cut-did-not-cut-discovery
description: did the 2026-09-05 skill description trim hurt discovery - roadmap-toolbox
  row 12 measured 2026-09-10 and the verdict is holding
type: project
created: '2026-09-10'
last_recalled: '2026-09-10'
links:
- job45-closed-awaiting-publish
- project-goal-clear-roadmap-toolbox
- feedback-orchestrator-numbers-from-recall
---

Roadmap-toolbox row 12's date gate has PASSED and the answer is measured, but the
row still reads "STILL OPEN and still DATE-GATED" on disk — strike it with these
numbers in the next PR.

Run 2026-09-10: `node tools/ledger/skill-discovery-check.mjs`, before-window 32 days,
after-window 6 days. The two skills with enough before-calls to judge both hold:
`plan-decompose-orchestrate` 0.50 -> 0.50 calls/day, `user-profile` 1.00 -> 2.33.
The other five answer "too few calls before to judge" and always will. So the cut
from 34 skills / 13,949 B to 22 / 3,396 B did NOT stop the model matching a
description, and the row's feared signal (a fall to zero) did not appear.

Rates keep moving — re-run and date whatever you write, per
[[feedback-orchestrator-numbers-from-recall]].

State the same day: main 6e506ca, tree clean, 0 open PRs, 0 open issues, every unit
in all ten `.shiftwork/checkpoint*.json` done. Remaining work is roadmap-toolbox
rows 5 (dream trigger) and 6 (threshold), the seven AS-1..AS-7 tasks in
docs/roadmap-agent-stack.md (none started), and the porting register.
