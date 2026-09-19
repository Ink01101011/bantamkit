---
name: feedback-finding-is-not-the-deliverable
description: what the user wants after a measurement finds a problem - fix every finding,
  review, merge, redeploy, never stop at the report
type: feedback
created: '2026-09-04'
last_recalled: '2026-09-15'
links:
- feedback-ship-it-working-and-measured
- feedback-real-probe-only
- merge-authorized-standing-tag-withheld
- reference-two-bantamkit-mcp-builds
---

Stated 2026-09-04, twice in one job, in the user's own words: *"ถ้าไม่ได้ถึง 60% ลองหาวิธีหน่อยว่ามีไหม ถ้ามีให้แก้ รีวิว แล้ว merge หน่อย เอาลืมอัพเดตให้ mcp เป็นล่าสุดนะ"* and then *"เจอ finding แล้วให้แก้ให้ครบ แล้ว redeploy / remigrate อื่นๆ"*.

**Why:** a measurement that ends in a verdict is half a job to this user. When a probe refutes something, the expected next move is not to hand back the number and wait — it is to go find whether a working alternative exists, implement it, review it, merge it, and put the running deployment on the new build. Reporting "X is refuted, here are the numbers" and stopping reads as leaving the work unfinished.

**How to apply:**
1. Treat "fix + review + merge + redeploy" as the done_definition of any measurement job that finds a defect, and write it into the checkpoint's done_definition at plan time rather than discovering it later.
2. When the answer is a refutation, immediately spend a unit on "does any alternative clear the bar" — do not wait to be asked.
3. Redeploy means the running endpoint, not the commit. Verify with `build_identity` / `bantamkit_status` that `build_id` actually CHANGED after the rebuild; a merged commit with a stale `runtime-ts/dist` is not deployed. Check which launcher is actually registered — `claude mcp list` showed `tools/bantamkit-mcp-node` while `.mcp.json` pointed at `tools/bantamkit-mcp`, so the two can disagree ([[reference-two-bantamkit-mcp-builds]]).
4. Carry it to the end even when the honest verdict is "no lever reaches the bar" — then the deliverable is the written statement that none exists, plus whatever partial fixes the findings did justify.

See [[feedback-ship-it-working-and-measured]], [[feedback-real-probe-only]], [[merge-authorized-standing-tag-withheld]].
