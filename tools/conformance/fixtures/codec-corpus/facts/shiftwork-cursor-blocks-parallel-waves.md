---
name: shiftwork-cursor-blocks-parallel-waves
description: how to clock a parallel wave of shiftwork units when the cursor only
  advances on done, and the two enums clock_out rejects
type: project
created: '2026-09-04'
last_recalled: '2026-09-15'
links:
- feedback-clock-in-before-spawning-not-after
- feedback-hand-the-returned-brief-not-a-path
- shiftwork-unit-cost-is-linear-in-tool-calls
---

Hit 2026-09-04 dispatching four independent audit units at once.

**The tools are built for a SEQUENTIAL cursor.** `shiftwork_clock_in` always returns the unit at `plan.cursor`, and `shiftwork_clock_out` advances that cursor **only when the unit's status is terminal**. Clocking out `in_progress` writes the ledger line and leaves the cursor where it was — so a second `clock_in` hands back the SAME brief. There is no way to obtain briefs for N parallel units through the tools alone.

**What works:** per unit — `clock_in` → spawn → `clock_out` with `status: "in_progress"` and the dispatch accounting → then set `plan.cursor` to the next unit id directly in the checkpoint file → `clock_in` again. Every unit still gets exactly one real clock_in and one clock_out, the brief is never reconstructed ([[feedback-hand-the-returned-brief-not-a-path]]), and the real tokens/duration are recorded on a later terminal clock_out when the unit returns. Record the manual cursor move in a history entry so the deviation is visible in the log.

**Two enums that are NOT in the example checkpoint and cost a round trip each:**
- `plan.units[].role` accepts only `planner`, `implementer`, `reviewer`. `auditor` and `researcher` are refused at clock_in with a schema error.
- `status` accepts only `todo`, `in_progress`, `done`, `blocked`, `dropped`. `dispatched` is refused at clock_out — and the refusal writes nothing, which is the validate-before-write behaviour working correctly.

**Worth considering as a product change:** a wave/parallel concept, or a `clock_in(unit_id=...)` argument, would remove the manual cursor edit entirely. Today (2026-09-11) the policy ("run every spawn through the shiftwork tools") and parallel fan-out are in tension, and the tension is resolved outside the tool.

See [[feedback-clock-in-before-spawning-not-after]], [[shiftwork-unit-cost-is-linear-in-tool-calls]].
