---
name: feedback-agents-die-mid-wait
description: a subagent that waits on a long run dies on API errors and takes the
  wait with it - launch detached, write incrementally, and never sit in a bash sleep
  loop
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-15'
links: []
---

Measured twice, in J2 and again in J7 on 2026-08-18/19.

**The failure mode.** A unit launches a long run, then waits for it. The wait is
where it dies:
- **J2's U4** used `until [ "$(wc -l < …)" -ge 300 ]; do sleep 90; done` in Bash.
  Every retry hit the **10-minute tool timeout** and re-sent a **254,042-token**
  prefix. It died at 54 minutes on a ConnectionRefused.
- **J7's U2** died on an **API 529** with its last words *"I'll wait for the arm's
  per-repeat events now."*
- The same outage killed **two of three sibling probes**, and blocked the
  orchestrator's own `Bash` **and** `Agent` tools for a sustained period, because
  the safety classifier was unavailable. **Read and Write kept working throughout.**

**Why:** waiting inside an agent turn converts a cheap background wait into an
expensive, retry-prone foreground one, and puts the whole unit's context at the
mercy of the API for the duration.

**How to apply:**
1. **Launch long work detached** so it survives its launcher — in J2 a detached run
   kept working for hours with PPID 1 after both its agent and the session were
   gone. Write rows **incrementally** so partial progress is readable.
2. **Report how to read progress instead of waiting.** As orchestrator, arm a
   `Monitor` rather than respawning a waiting agent — that turned dozens of
   expensive retries into 4 notifications over ~5 hours.
3. **When resuming, establish state first.** Ask specifically whether a detached
   process is still alive; if it is, **do not start a second**.
4. **During an outage, keep authoring.** Briefs, amendments, memory and plans need
   only Write. Do not burn spawns that will die at their first Bash call — and say
   plainly that you are pausing spawns rather than idling.
5. **Never restate another unit's number as your own** when you could not run the
   measurement. Mark it **UNMEASURED BY THIS UNIT**.

See [[feedback-cycle-memory-clear-resume]], [[project-j7-compaction-in-the-loop]],
[[feedback-real-probe-only]].
