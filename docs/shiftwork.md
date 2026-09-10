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
   the driver can wait on things it does not understand. Only `status:
   running` entries are waited on, so a session must move an external off
   `running` (or drop it) once it stops gating work — a finished process left
   marked `running` stalls the loop until the wait times out and escalates.
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

### `job.roles` — the declaration that makes the role checkable

**Added in 0.30.x (job46, AS-2). Optional, and omitting it changes nothing.**

`job.roles` is a map from unit role to the model identifiers a session in that
role may report — spelled exactly as the accounting line logs them:

```json
"job": {
  "roles": {
    "implementer": ["claude-sonnet-5", "claude-opus-5"],
    "reviewer": ["claude-opus-5"]
  }
}
```

Until this existed, the model a unit ran on was *recorded* and never *compared*:
it lived in `history[]`/`retro[]`, the only two objects in the contract that
allow extra keys, so nothing could hold a role to a list. With the map declared,
`shiftwork_clock_out` refuses an accounting entry whose `model` is not on the
named role's list — and refuses one that reports **no** model at all, because a
rule you can escape by omitting a field is enforced only against the honest.

Four properties worth knowing before you declare one:

- **The refusal is total, and it happens first.** It is taken before any
  mutation and before the log-then-commit pair, so a rejected clock-out leaves
  the checkpoint byte-unchanged, writes no accounting line, and does not move
  the cursor. There is no orphan log line claiming a model that was refused.
- **Omitting the map keeps the old behaviour exactly.** So does naming only some
  roles: a role the map does not list is unconstrained, and declaring one role
  forbids nothing about the others. A checkpoint written before this feature
  clocks out unchanged, model and all.
- **Models compare EXACTLY.** No normalisation, no prefix match, no
  strip-the-brackets rule — `claude-opus-5[1m]` is not `claude-opus-5`, and both
  runtimes pin that case as a refusal so that any future attempt at a fuzzy
  compare turns red. The map's whole value is that it is the literal list of the
  spellings a session logs; a spelling you have not seen before is a finding to
  rule on, not a string to massage.
- **A list must be non-empty**, and the two layers agree about that rather than
  one relying on the other: the schema refuses `"implementer": []` outright
  (`minItems: 1` — a role allowed no model is a typo, not a policy), and the
  check itself treats a role it is *given* with an empty list as allowing
  nothing. Keys are the `plan.units[].role` enum, so a key that is not a role is
  refused rather than quietly ignored.

Note that `job` is a closed object, so an older bantamkit does not skip the key
— it refuses the whole file. That is deliberate: opening `job` so an old reader
could ignore `roles` is exactly what would make this check bypassable by running
an older server.

### Checkpoint failure modes

| Failure | Behavior |
|---|---|
| Checkpoint missing/corrupt | Rebuild from git log + ledger; planner re-cuts remaining units |
| `head_sha` mismatch at clock-in | Stop; escalate with a diff summary — never fix forward silently |
| Cursor unit `blocked` | Write the reason into the unit, set `open_questions`, clock out |
| `verify` fails on a `done` unit | Distrust the checkpoint from that unit forward; planner re-plans |
| External `until_cmd` never met | Driver-level timeout, then escalation |
| Reported model not on `job.roles[role]` (or absent) | Clock-out refuses before writing: no accounting line, no cursor advance, checkpoint byte-unchanged |

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
| 30 | STALLED | `max_retries` + 1 sessions on one cursor with no hash delta (the first try, then every retry) |
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

## Orchestrator flavor

The driver spawns sessions from outside; the MCP flavor serves the inverse
topology: an already-running Claude session orchestrates subagents and
keeps clock-in/clock-out discipline through three tools on
[`bantamkit-mcp`](mcp.md#shift-work-tools) — same checkpoint contract,
same schema validation, mirrored refusal semantics (structured
`escalate`/`success` results instead of exit codes 10/0).

The workflow, per unit:

1. Plan once into a schema-valid checkpoint — the planner role is the
   orchestrating session itself.
2. `shiftwork_clock_in(checkpoint)` → get `{unit, role, invariants,
   handoff, do_not, files}`. On `escalate`, stop and surface to the user;
   on `success`, the job is done.
3. Spawn the subagent with the returned brief verbatim, picking the model
   from the unit's `role`.
4. `shiftwork_clock_out(checkpoint, unit_id, status, handoff_patch,
   history_entry, accounting)` — `unit_id` must be the cursor unit
   (execute-the-cursor, driver parity). The whole mutated document is
   validated before any write; then one accounting line is appended to
   `<checkpoint>.log.jsonl` and the checkpoint is renamed into place, in
   that order (log-then-commit) — a partial failure can lose the commit
   but never the accounting, and a log line whose commit failed is
   detectable by re-reading the checkpoint.

Cursor advance is v1-linear: clock-out moves the cursor to the first
non-terminal unit in plan order and ignores `depends_on` — a non-linear
plan needs a planner unit to reorder `plan.units` first.

**Log-line comparability with the driver.** Both flavors log one JSONL
line per session, in deliberately different shapes; the N-sessions
experiment reads both logs through this mapping:

| driver `driver-log.jsonl` | MCP `<checkpoint>.log.jsonl` | note |
|---|---|---|
| `ts` | `ts` | same UTC `...Z` format |
| `cursor` | `unit` | the unit the session executed |
| `role` | `role` | identical |
| `exit` + `progressed` | `status` | the driver observes exit + hash delta; the MCP flavor records the reported unit status |
| `duration` | `accounting.duration` | driver-measured vs orchestrator-reported |
| `seq` | — | driver-only session counter |
| — | `tokens`, `model` | MCP-only orchestrator accounting |

**Role → model mapping — never random, never silently inherited.** The
orchestrator maps role to model when spawning. Recommendation: planner =
the session's own model; implementer = the cheapest tier the brief
supports (a brief with complete code is transcription); reviewer =
mid-tier floor, judgment-heavy review = the session model. Whatever you
choose, `clock_out`'s accounting line records the **model actually used**
per unit, so every run is auditable after the fact. This mirrors the
driver's explicit `driver.json` role dispatch — the MCP flavor moves the
decision into the orchestrator but keeps it explicit and logged.

**Amendment 2026-09-11 (job46, AS-2).** The paragraph above stands as
written and describes what the MCP flavor did until this release: the
model was *logged*, and auditing it meant reading the log afterwards. As
of 0.30.x it can also be **checked at the moment it is reported** — see
[`job.roles`](#jobroles--the-declaration-that-makes-the-role-checkable).
Declare the map and `clock_out` refuses a model the role is not allowed,
and refuses a unit in that role that reports no model at all, before
anything is written. Declaring nothing keeps exactly the behaviour above.
So "auditable after the fact" is now the floor rather than the ceiling:
the recommendation for *which* model to pick is unchanged, and what is
new is that the choice can be written into the checkpoint and enforced
instead of remembered.

**Code-fix template.** `tools/shiftwork/example-codefix-checkpoint.json`
is a schema-valid starting point for the classic fix-a-bug job: units
reproduce → locate → fix → verify, where the fix lands under an
implementer and is gated by the reviewer unit (verify reviews the diff
against the constraints and runs the full suite). Copy it to
`.shiftwork/checkpoint.json` in the target repo, fill in `job`,
`state.repo`, and the briefs, and clock in. The template targets the MCP
flavor; under the driver, CF4's `pytest -q` verify step needs a role
whose `allowed_tools` includes Bash (the stock reviewer whitelist is
read-only).

**Standing policy** (committed in this repo's `CLAUDE.md`; the same
block gets installed user-level in `~/.claude/CLAUDE.md` as part of the
post-merge live smoke — copy it into any other machine or project):

> Any multi-unit orchestration — ≥2 planned units, or any
> spec→plan→implement / bugfix / code-trace job that fans out agents —
> MUST run its agent spawns through the shiftwork MCP tools:
> `shiftwork_clock_in` → spawn the subagent with the returned brief
> verbatim → `shiftwork_clock_out` with status, handoff patch, history
> entry, and accounting (tokens, duration, and the model actually used).
> Exempt: one-off ad-hoc spawns (a single search or review with no plan
> behind it) — no unit to clock.

No lock, deliberately: this topology has one orchestrator by
construction; `driver.lock` guards cross-process races the single-session
shape does not have, and clock-out re-validates before writing so a
concurrent driver run fails validation-visibly rather than corrupting.

## Conventions and future work

Per-role prompt files (`.shiftwork/prompts/<role>.md`) and tunables
(`.shiftwork/profiles/*.yaml`) are conventions only in v1 — a retro patch is a
commit whose message cites its trigger. Not shipped: retro automation,
Windows support, notification transports beyond `notify_cmd`, and the
N-sessions experiment itself (the MCP flavor above ships its instrument:
the per-unit accounting log).
