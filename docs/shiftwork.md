# Shift-work

Big jobs burn context: one long session pays compaction, drift, and
re-derivation. Shift-work is the other shape — plan once into small units,
then run stateless clock-in/clock-out sessions: read the checkpoint, do one
unit, write the checkpoint, exit. Two artifacts make that real:

- a **checkpoint contract** — a bounded file that lets a fresh session resume
  losslessly in one read (`assets/schemas/shiftwork-checkpoint.json`);
- a **driver** — a loop that spawns sessions and decides nothing
  (`tools/shiftwork/driver.py`).

**Status: mechanism shipped, claim unmeasured.** The falsifiable claim behind
shift-work — N short sessions beat one long session on score, tokens, and
wall-clock — has *not* been run. It needs a real job, and the instrument is
already built: the driver log (one line per session) joined with session-side
token accounting on `seq`. Until that experiment runs, treat shift-work as
experimental plumbing, not a measured result.

## The checkpoint

The contract is YAML-shaped for humans, and the schema validates the parsed
document either way — but **the v1 driver reads JSON**, so sessions driven by
`driver.py` write a `.json` checkpoint (and the driver's own config is
`driver.json`). Reason: the driver is single-file and stdlib-only, and PyYAML
is not stdlib. See `tools/shiftwork/example-checkpoint.json` for a full,
schema-valid example.

Validate one from a session (this is the dogfooding path — bantamkit's own
SchemaGate engine validates the layer that will drive bantamkit development):

```python
import json
from bantamkit.assets import load_schema
from bantamkit.contract import schema_error

problem = schema_error(open(".shiftwork/checkpoint.json").read(),
                       load_schema("shiftwork-checkpoint"))
```

Shape, top level: `version` (const `1`), `job`, `plan`, `state`, `history`,
`retro`, `handoff`. The schema is strict — unknown keys are rejected
everywhere except inside `history[]`/`retro[]` entries, which are the
free-text annotation space.

### The eight load-bearing decisions

1. **Two-tier storage.** The checkpoint is an *index* (target ≤ 2 KB), not a
   journal; briefs, specs, and reports are files it points at. Clock-in cost
   stays O(1) as the job grows. Journaling into the checkpoint is what makes
   many short sessions cost more than one long one — banned by construction.
2. **Single cursor, planner-owned plan.** `plan.cursor` names THE next unit.
   The executor never chooses; it executes the cursor and moves it.
   Re-planning (reorder, split, drop) is the planner role's exclusive write.
3. **`verify` per unit.** Done-ness is a command, not a claim. A resuming
   session can re-run `verify` on a `done` unit to detect a stale checkpoint
   before trusting it.
4. **Staleness guards.** `state.repo.head_sha` + `dirty` must match the
   working tree at clock-in; a mismatch escalates, it never fixes forward.
5. **`state.external`.** Detached processes, PRs, CI — world-state git cannot
   witness. `until_cmd` makes each one machine-checkable (exit 0 = met), so
   the driver can wait on things it does not understand.
6. **`handoff.do_not`.** Negative space transfers worst across sessions, so it
   is a first-class field, not prose buried in notes.
7. **`handoff.open_questions` is the autonomy switch.** Empty = the driver
   keeps cycling. Non-empty = the driver stops and surfaces to the user. One
   field decides clock-out vs escalate.
8. **Atomic single-writer discipline.** Only the clocking-out session writes,
   via temp-file + rename. The reader validates `version` first and refuses
   unknown majors. No separate checkpoint lock is needed: `driver.lock`
   guarantees one driver, and sessions run sequentially.

`plan.units[].role` (planner | implementer | reviewer) exists purely so the
driver can pick a model without reading a brief. Re-planning needs no special
mode: a planner unit is just a unit.

### Checkpoint failure modes

| Failure | Behavior |
|---|---|
| Checkpoint missing/corrupt | Rebuild from git log + ledger; planner re-cuts remaining units |
| `head_sha` mismatch at clock-in | Stop; escalate with a diff summary — never fix forward silently |
| Cursor unit `blocked` | Write the reason into the unit, set `open_questions`, clock out |
| `verify` fails on a `done` unit | Distrust the checkpoint from that unit forward; planner re-plans |
| External `until_cmd` never met | Driver-level timeout, then escalation |

## The driver

```bash
python tools/shiftwork/driver.py \
    --checkpoint .shiftwork/checkpoint.json \
    --config tools/shiftwork/driver.json
```

It writes `driver-state.json`, `driver.lock`, and `driver-log.jsonl` beside
the checkpoint (override with `--state`, `--lock`, `--log`).

The driver is **dumb by construction**: it never reads `job.goal`, never opens
a brief, never interprets prose. It reads `version`,
`handoff.open_questions`, unit `status`, `plan.cursor`, `plan.units[].role`,
and `state.external[].until_cmd` — everything else is opaque bytes. All
intelligence lives inside sessions; if a proposed feature needs judgment, it
belongs in a session.

Each iteration: refuse an unknown major version → escalate on open questions →
succeed when every unit is `done`/`dropped` → stop on budget → wait while any
running external's `until_cmd` fails (poll with exponential backoff, 30 s
doubling to a 5-minute cap, per-external timeout) → spawn one session → diff
the checkpoint's sha256 → log a line.

**Progress is the hash delta and nothing else.** A session that crashes
mid-unit never lands its atomic clock-out write, so the hash is unchanged and
the same cursor is retried; `max_retries` exhausted ends in STALLED. Retry
counters live in `driver-state.json` — never in the checkpoint, which stays a
work artifact.

The clock-in prompt is a **constant string** (only the checkpoint path is
substituted, once per job — never per unit). That keeps it prompt-cacheable
and testable, and means the driver cannot smuggle state past the checkpoint.

### Exits

| Code | Exit | Meaning |
|---|---|---|
| 0 | SUCCESS | Every unit `done` or `dropped` |
| 10 | ESCALATE | `open_questions` non-empty, unusable checkpoint, dangling cursor, unknown role, or an external wait that timed out |
| 20 | BUDGET | Session cap or wall-clock cap hit |
| 30 | STALLED | `max_retries` sessions on one cursor with no hash delta |
| 40 | (refusal) | Another live driver holds `driver.lock` — not a loop outcome |

All four loop exits are terminal and notify: the driver never "handles" a
problem, it stops and tells you. Notification is `notify_cmd` in the config
(default: an `osascript` banner on macOS; the message is passed as the last
argv entry and on stdin, so pipe-style notifiers work too). An empty
`notify_cmd` disables it.

### Config

`driver.json` carries role → `{model, allowed_tools, max_turns}`, the budgets
(`max_sessions`, `max_wall_clock_seconds`, `max_retries`,
`session_timeout_seconds`, `external_timeout_seconds`), `notify_cmd`, and
`dangerously_skip_permissions`. This is Layer-4 profile data living with the
driver: **sessions never pick their own model.** The permission posture is
`--permission-mode acceptEdits` plus a per-role `--allowedTools` whitelist —
implementer gets Edit/Write/Bash, reviewer is read-only, planner reads and
writes the checkpoint. `--dangerously-skip-permissions` is never the default;
it exists only behind the explicit config opt-in, for sandboxed environments.

### Driver failure modes

| Failure | Behavior |
|---|---|
| Checkpoint unparseable / unknown major version | ESCALATE immediately, never overwrite |
| Session exits non-zero but checkpoint advanced | Trust the checkpoint; log the anomaly |
| Session exits zero but checkpoint unchanged | Count as a retry — a clean exit without clock-out is still no progress |
| `until_cmd` never succeeds | Per-external timeout, then ESCALATE |
| Driver itself killed | `driver-state.json` + checkpoint both survive; rerunning resumes cleanly |
| Two drivers on one checkpoint | `driver.lock` (pid + start ts); the second refuses to start. A lock whose pid is dead is taken over |

## Conventions and future work

Per-role prompt files (`.shiftwork/prompts/<role>.md`) and tunables
(`.shiftwork/profiles/*.yaml`) are conventions only in v1 — a retro patch is a
commit whose message cites its trigger. Not shipped: the MCP flavor
(`clock_in`/`clock_out` as MCP tools), retro automation, Windows support,
notification transports beyond `notify_cmd`, and the N-sessions experiment
itself.
