---
name: feedback-hand-the-returned-brief-not-a-path
description: shiftwork clock_in synthesizes the invariants array - it is not in the
  checkpoint file, so a subagent told to read it there finds nothing
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-19'
links: []
---

`shiftwork_clock_in` returns a brief containing an `invariants` array. **That
array does not exist in the checkpoint JSON.** Verified 2026-08-18: neither
`.shiftwork/job13-compaction-measured/checkpoint.json` nor `.shiftwork/checkpoint.json`
has an `invariants` key at any depth — the top-level keys are `version, job,
plan, state, history, retro, handoff`.

I spawned a unit with "read its `invariants` array (20 items) from the
checkpoint". The unit found no such key, read `handoff.do_not` instead, treated
it as binding, and reported the gap rather than papering over it.

**Why:** the shift-work policy says to hand the spawned agent **the returned
brief verbatim**. Pointing at a file path is not that, and the failure is
silent — the unit proceeds bound by fewer invariants than intended.

**How to apply:** paste the `invariants` and `handoff.do_not` text into the
spawn prompt itself. A brief that only exists in a tool's return value cannot be
read by anyone but the caller.

See [[project-bantamkit-program-backlog]], [[project-j2-compaction-measured-result]].
