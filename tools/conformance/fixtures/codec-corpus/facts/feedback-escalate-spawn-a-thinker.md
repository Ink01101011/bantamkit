---
name: feedback-escalate-spawn-a-thinker
description: the user overrode the shiftwork stop-and-ask rule on escalate - spawn
  an agent to work the question and keep cycling instead of blocking
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-15'
links: []
---

Set by the user on 2026-08-18, in their words: *"ถ้าระหว่างทางเจอการ escalate
ให้นาย spawn agent ขึ้นมาช่วยคิดหาคำตอบ แล้วไปต่อเรื่อยๆ หา solution แก้ไปเรื่อยๆ
จนได้คำตอบ"*, together with *"ทำแทนฉันไป cycle ไปเรื่อยๆ จนกว่างานจะเสร็จ"*.

**This overrides the shift-work policy clause in both CLAUDE.md files** ("On
`result: escalate`, stop and ask the user"). A live user instruction supersedes
a standing one. On escalate: spawn an agent to work the question, resolve it,
keep cycling.

**Why:** blocking the whole program on a question an agent can answer wastes the
user's turn on a non-decision. This already happened once and was resolved
correctly without them — U4's F2 looked like a choice between two token counters
and was settled by re-reading bar §10.3, which declared the axis "with no room to
choose after the fact".

**The one boundary that does not move.** Resolve escalations that a *document or
a measurement* can settle. Do not invent a preference on questions that are
genuinely the user's — scope, corpus policy, what ships, what gets authorized.
Their own earlier escalation E-1 (stratify, never pool) was exactly that kind and
they answered it themselves. When an agent's conclusion is "this needs a value
judgement", record it in the checkpoint and the backlog, do the rest of the work,
and surface it at the next natural pause rather than blocking or guessing.

Also set the same day: **stop at 07:00** and resume only on "ทำต่อ".

See [[feedback-cycle-memory-clear-resume]], [[project-bantamkit-pending-user-decisions]],
[[feedback-real-probe-only]].
