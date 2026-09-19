---
name: feedback-authorization-does-not-survive-compaction
description: why a standing permission like merge or deploy stops being usable after
  a context compaction and how to unblock it
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-15'
links: []
---

A user's standing authorization — "merge without asking me", "deploy when green"
— is usable **only while their own words are in the live context**. After a
context compaction it survives only as a claim inside a model-written summary, and
a model-written summary is **not** user approval. Acting on it then is acting on my
own text.

**Why:** measured on 2026-08-17. The user granted merge standing in their own
words (*"review แล้ว merge MR ได้เลยไม่ต้องรอฉัน"*). After `/compact`, the
auto-mode classifier refused `gh pr merge 32 --squash` with the reason: "the only
claimed merge authorization appears in a model-written continuation summary — which
the session's own notification says must not be treated as user approval." That is
correct, and worth internalising rather than resenting: the compaction boundary is
exactly where a fabricated or drifted permission would be indistinguishable from a
real one.

**Confirmed by the user's own follow-up.** After restating it once they said
*"รอบหน้า merge ได้เลยถ้า review ผ่านไม่ต้องรอยืนยันจากฉัน"* — they do **not** want
to be asked each time, and being asked repeatedly is the failure mode from their
side. So the goal is not "ask every time"; it is **make the grant durable**. Offer
the Bash permission rule for `gh pr merge` in settings, which survives compaction,
and ask for a restatement only when no rule exists and a compaction has happened.

**How to apply:**
1. **Do not route around the denial.** Trying a different command, the API instead
   of the CLI, or a script that performs the same merge is working around the
   intent, not solving the problem.
2. **Finish everything that does not depend on the permission** — verification,
   clock-out, docs, backlog, memory — so the only thing left is the one act.
3. **Report and ask for one sentence.** State what is done, what is blocked, and
   that a single restatement in a live turn unblocks it. Offer the durable
   alternative: a Bash permission rule in settings makes it survive future
   compactions.
4. **Carry the scope precisely.** In this case merge was granted and `tag` never
   was; a restated merge authorization does not extend to tagging.
5. **Record the block where the next context will read it** — the checkpoint's
   `next_action`, the backlog, and memory — never only in a reply.

See [[project-bantamkit-pending-user-decisions]], [[feedback-real-probe-only]],
[[feedback-cycle-memory-clear-resume]].
