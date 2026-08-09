# Driver Script — DRAFT (companion to checkpoint contract v1)

**Status:** draft, 2026-08-10, pre-brainstorming. Pairs with
`2026-08-10-shift-work-checkpoint-contract-draft.md`. Untracked on
purpose; commit when the shift-work-orchestrator cycle opens.

## Prime directive

The driver is **dumb by construction**. It contains zero work knowledge:
it never reads `job.goal`, never opens a brief, never interprets prose.
It reads exactly four machine-checkable things from the checkpoint —
`version`, `handoff.open_questions`, unit `status` fields, and
`state.external[].until_cmd` — and everything else is opaque bytes. All
intelligence lives inside sessions. If a proposed driver feature needs
judgment, it belongs in a session, not the driver.

## Loop (pseudocode)

```
loop:
  ckpt = read_yaml(CHECKPOINT)                # refuse unknown major version
  if ckpt.handoff.open_questions:  notify(user); exit ESCALATE
  if all units done|dropped:       notify(user); exit SUCCESS
  if budget exceeded (sessions or wall-clock): notify(user); exit BUDGET

  unit = ckpt.plan.units[ckpt.plan.cursor]
  for ext in ckpt.state.external where status == running:
    if unit blocked-on ext and sh(ext.until_cmd) != 0:
      sleep POLL_INTERVAL; continue loop      # waiting, not working

  model = ROLE_MODEL[unit.role]               # driver.yaml: role -> model/effort
  before = sha256(CHECKPOINT)
  run: claude -p "$CLOCK_IN_PROMPT" --model $model \
        --permission-mode acceptEdits --max-turns N --timeout SESSION_TIMEOUT
  after = sha256(CHECKPOINT)

  log_line(ts, seq, cursor, role, exit_code, duration, before != after)

  if before == after:                         # session died or spun
    retries[cursor] += 1                      # driver-state.json, NOT the checkpoint
    if retries[cursor] > MAX_RETRIES: notify(user); exit STALLED
  else:
    retries[cursor] = 0
```

`CLOCK_IN_PROMPT` is a **constant string** — never templated per unit:

> "Clock in. Read the checkpoint at `<path>` and the artifacts it lists.
> Execute ONLY the unit at `plan.cursor` per its brief. Run its `verify`.
> Update the checkpoint (atomic temp-file + rename), set `next_action`,
> and clock out. If blocked, set the unit blocked with a reason and fill
> `open_questions` instead of improvising."

Constant prompt ⇒ prompt-cacheable, testable, and the checkpoint remains
the single source of truth — the driver cannot smuggle state in via the
prompt.

## Load-bearing decisions

1. **Progress = checkpoint hash delta.** The only signal the driver
   trusts. Session crashed mid-unit ⇒ atomic clock-out write never
   happened ⇒ hash unchanged ⇒ retry same cursor; cap ⇒ STALLED
   escalation. This is loop-ledger's patience rule, dumbed down to bytes.
2. **Driver state stays out of the checkpoint.** Retry counters, session
   seq, timestamps live in `driver-state.json` beside the driver.
   Checkpoint stays a work artifact; driver internals never leak into
   what sessions read.
3. **`until_cmd` = condition as shell command** (exit 0 = met), e.g.
   `grep -q 'ALL SWEEPS DONE' $LOG`. Lets the driver wait on detached
   processes without understanding them. (Schema delta #2 below.)
4. **Role → model mapping is driver config** (`driver.yaml`:
   `planner: {model: opus}`, `implementer: {model: haiku}`,
   `reviewer: {model: sonnet}`). This is Layer-4 profile data living
   with the driver — sessions never pick their own model. (Schema delta
   #1: units need a `role` field.)
5. **Four exit codes, all terminal:** SUCCESS / ESCALATE (open_questions)
   / STALLED / BUDGET. The driver never "handles" problems — it stops
   and notifies. Notification = `osascript` banner + log tail on macOS;
   pluggable.
6. **The driver log is the experiment's measurement.** One line per
   session (seq, cursor, role, exit, duration, progressed?) — exactly the
   data the N-short-sessions vs one-long-session comparison needs.
   Tokens-per-session come from session-side accounting joined on seq.

## Schema deltas discovered by this design

Designing the driver forces two additions to checkpoint contract v1:

1. `plan.units[].role: planner | implementer | reviewer` — driver needs
   it for model dispatch without reading briefs.
2. `state.external[].until_cmd: <shell command>` (replaces prose
   `until`) — machine-checkable wait condition.
3. (soft) `plan.cursor` may point at a **planner unit** — re-planning is
   itself a unit (e.g. `U9: re-cut remaining units after QA failures`),
   so the driver needs no special re-plan mode. One loop shape covers
   plan/execute/QA/retro: they are just units with different roles.

## Failure modes → driver behavior

| Failure | Behavior |
|---|---|
| Checkpoint unparseable / wrong major version | ESCALATE immediately, never overwrite |
| Session exits non-zero but checkpoint advanced | Trust the checkpoint (progress happened); log anomaly |
| Session exits zero but checkpoint unchanged | Count as retry — "clean exit" without clock-out is still no progress |
| `until_cmd` never succeeds | Per-external timeout in driver.yaml ⇒ ESCALATE |
| Driver itself killed | driver-state.json + checkpoint both survive; rerun resumes cleanly (driver is stateless between iterations by design) |
| Two drivers started on one checkpoint | Lock file `driver.lock` (pid + start ts); second driver refuses to start |

## Resolved decisions (2026-08-10, pre-cycle; brainstorming may overturn)

1. **Permission posture:** `--permission-mode acceptEdits` plus a
   per-role `--allowedTools` whitelist carried in a settings profile —
   implementer gets Edit/Write/Bash, reviewer runs read-only, planner
   read + checkpoint write. `--dangerously-skip-permissions` is never
   the default; it exists only behind an explicit driver.yaml opt-in for
   fully sandboxed environments.
2. **Language: Python.** Single file, stdlib only, unit-tested — the
   driver is the one deterministic component in the system, so it is the
   one that gets real tests. Bash loses on driver.yaml parsing, atomic
   state handling, and testability.
3. **Waiting: poll with exponential backoff** (30 s → 5 min cap) in v1.
   Cron-style scheduled resume is deferred until a measured job shows
   polling cost matters — the driver sleeps between polls, so the cost
   is near zero anyway.
4. **Notifications: `notify_cmd` in driver.yaml** — driver pipes a
   one-line message to whatever command is configured. Default on macOS:
   `osascript` banner. ntfy/webhook/Slack become one-line config
   changes, not driver features.
