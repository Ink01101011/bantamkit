---
name: job45-repomap-gate-refuted-built-anyway
description: 'job45 ships roadmap #5 dream, #6 precision gate, #10 repo map then 0.30.0
  — and why #10 was built after its own gate was refuted at 0.114 percent'
type: project
created: '2026-09-06'
last_recalled: '2026-09-19'
links:
- project-goal-clear-roadmap-toolbox
- public-install-is-pure-node-by-ruling
- feedback-prep-probe-before-planning
- merge-authorized-standing-tag-withheld
---

job45 (branch feat/job45-dream-precision-repomap, checkpoint .shiftwork/checkpoint-job45.json, 13 units) ships roadmap-toolbox #5/#6/#10 then 0.30.0 to npm+PyPI.

Roadmap row 10 gated itself: "build only after #4 shows discovery tokens dominate." Measured 2026-09-06 over 30 days on this project: discovery (Read/Grep/Glob + locating Bash) is 4,266.6k est tok = 33.8 percent of tool-result bytes but only **0.114 percent of the 3,739,207.9k REAL prompt tokens sent**, because 97.8 percent of everything sent is cache_read. That 0.114 is the CEILING on a perfect repo map. The gate is refuted.

The user was shown the number and ruled "build it anyway, full spec". So #10 ships as a PRECISION feature with the ceiling recorded in docs/repomap.md — never as a token-saving claim. Do not re-open this argument; the ruling is on the record.

Two more facts that cost probe time:
- The hook log records injected `hits` and `bytes` but NOT which facts or at what score, so none of the 604 UserPromptSubmit records can answer "was the injected name later used?". #6 has no retroactive baseline; hit-rate history starts the day the J45-5 instrument ships.
- #10 cannot vendor tree-sitter (native prebuilds vs the pure-node ruling), so the def extractor is hand-rolled in the existing pyyaml.ts/pyjson.ts idiom. PageRank params must be pinned (fixed iterations, fixed tie-break, fixed rounding) or the two runtimes cannot be compared at all.

Gates at 3f9bb55 before any unit: pytest 2430 passed/4 skipped/3 xfailed, ruff clean, node 608 tests 606 pass, conformance 6724 cases 0 failures.
