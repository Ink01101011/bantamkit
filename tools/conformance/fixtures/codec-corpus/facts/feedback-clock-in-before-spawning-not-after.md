---
name: feedback-clock-in-before-spawning-not-after
description: what to do after spawning shiftwork units without clocking them in -
  recover the accounting, never reconstruct the brief
type: feedback
created: '2026-08-21'
last_recalled: '2026-09-11'
links:
- feedback-hand-the-returned-brief-not-a-path
- project-bantamkit-program-backlog
---

Four parallel units on disjoint surfaces still counts as multi-unit
orchestration. On 2026-08-21 I spawned A/B/C/D straight from the Agent tool
because each felt like an independent one-off; it is not — the exemption is for
a SINGLE ad-hoc spawn with no plan behind it. Four units with a plan is a job.

**Why:** clock_in is what SYNTHESIZES the invariants array and hands the brief.
Skipping it means the units never see the checkpoint's constraints as a block,
and the job has no accounting trail.

**How to apply, when you notice mid-flight:**
1. Create the checkpoint anyway, late. The accounting (tokens, duration, model,
   per role) is still capturable and is most of the value.
2. clock_out is ORDERED — it refuses any unit that is not `plan.cursor`. Clock
   out in plan order, not in the order units finish.
3. NEVER write brief files after the fact. A reconstructed brief is a fabricated
   record. Write a PROVENANCE.md saying where the briefs actually are (the agent
   transcripts) and that the synthesis half stayed missing.
4. Record the failure in the register's "gets no number" section — a process
   failure, not a defect in the instrument.

Schema gotchas hit while creating one late: `plan.cursor` is a unit-id STRING
not an index; unit status is todo|in_progress|done|blocked|dropped (not
"pending"); `handoff.do_not` is REQUIRED.

Links: [[feedback-hand-the-returned-brief-not-a-path]],
[[project-bantamkit-program-backlog]].
