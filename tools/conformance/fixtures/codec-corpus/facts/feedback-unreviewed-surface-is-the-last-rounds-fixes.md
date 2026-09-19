---
name: feedback-unreviewed-surface-is-the-last-rounds-fixes
description: how to scope a late review round on a branch that already had several
  - the never-reviewed surface is the previous round's fix commits, not the whole
  PR, and it is usually 4x smaller
type: feedback
created: '2026-09-04'
last_recalled: '2026-09-18'
links: []
---

When a branch has been through N review rounds and someone still owes round N+1, do NOT scope it as "re-read the whole PR". Rounds review incrementally: round 2 reads round 1's fixes, round 3 reads round 2's fixes. So the strictly-never-reviewed surface is **the last round's fix commits plus anything merged since**, and nothing else.

Measured on job43b 2026-09-04: PR #81 was 10,035 insertions and the full unreviewed-looking range `39c5a74..main` was 10,691. The surface that no reviewer had ever read was `47d1c12..main` — 2,711 insertions / 163 deletions / 33 files. **A 4x reduction, and the smaller number is the honest one.**

The command that finds it: identify the last conformance/fix commit of the previous round from `git log`, then `git diff <that>..main --numstat` bucketed by layer.

**Why:** scoping round 4 as the whole PR would have burned three opus reviewers on 8,000 lines that two prior rounds already read, and diluted attention away from the part nobody has ever seen — which on this job was `tools/hooks/bantamkit-hook.mjs`, code that runs on every compaction and reached main with no PR at all.

**How to apply:** before planning any late review round, run the diff-range probe and report the two numbers side by side. Fold never-reviewed post-merge commits into the same job rather than deferring them — they are the highest-risk slice, not a follow-up. Related: [[feedback-prep-probe-before-planning]], [[job43b-review-round4-started]].
