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
free-text annotation space. A fact the *next* session needs that is not an
imperative, a question, or a prohibition goes in `handoff.notes` — one
optional free-form string (job50). It is declared precisely so the strictness
survives it: `handoff` itself stays closed, and a misspelled `next_action` is
refused exactly as before.

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
   is a first-class field, not prose buried in notes. The prose has its own
   field since job50: `handoff.notes`, a string, for the gate baseline or last
   commit or technique that is none of an action, a question, or a
   prohibition. It is a string and not a map because a map keyed by fact grows
   a key per session — the journal decision 1 bans, one level down. It is
   shallow-merged like the rest of `handoff`, so a note persists until a later
   session overwrites it (the empty string is a legal overwrite).
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
- **A declaration this code cannot READ is not a licence** — added 2026-09-11 by
  job47; every bullet above stands as written. A role the map *names* whose value
  is not a list of model identifiers allows no model, and the refusal is the same
  structured one taken in the same place: `unit <id> in role <role> cannot clock
  out: job.roles.<role> is not a list of model identifiers, so it allows no
  model`. That is the THIRD AS-2 refusal string, not the second. It exists
  because the value's shape is pinned by a SHARED asset, and a check whose safety
  rests on another layer's keyword fails open the day that keyword moves:
  measured under a pack with `additionalProperties: true` and `model: haiku`, a
  string, a dict, a number, a null and a bool all returned `{"result": "ok"}` on
  the Node runtime — status set, cursor advanced, accounting line written — while
  the Python runtime raised an uncaught `TypeError` out of `clock_out` on three of
  them and minced the checkpoint's own value into the sentence (`… does not
  allow: c, l, a, u, d, e, -, o, p, u, s, -, 5`) on the other two. The sentence
  names no type (a Python type name would not port) and renders no part of the
  unreadable value, and it is ONE sentence for both accounting shapes: which
  model was reported cannot matter when the declaration that would judge it is
  unreadable. `[]` is untouched by this — an empty list IS a list of model
  identifiers and keeps the bullet above.

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
| `job.roles[role]` present but not a list of model identifiers (job47) | Same refusal, same place, same three guarantees — an unreadable declaration allows no model |

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
[`bantamkit-mcp`](mcp.md#shift-work-tools) — `shiftwork_clock_in`,
`shiftwork_clock_out`, `shiftwork_status`; two more, `shiftwork_plan` and
`work_plan`, only report and are covered in
[The batch view](#the-batch-view-shiftwork_plan-and-work_plan) below — same checkpoint contract,
same schema validation, mirrored refusal semantics (structured
`escalate`/`success` results instead of exit codes 10/0).

The workflow, per unit:

1. Plan once into a schema-valid checkpoint — the planner role is the
   orchestrating session itself.
2. `shiftwork_clock_in(checkpoint)` → get `{unit, role, invariants,
   handoff, do_not, files}`. On `escalate`, stop and surface to the user;
   on `success`, the job is done. A `brief` answer also appends one
   `{"event": "brief", ts, unit, role}` line to `<checkpoint>.log.jsonl` —
   best-effort, and only on that branch; see *Clock-in writes too* below.
   Since job60 it also takes an optional `unit_id`, which must name a unit
   the graph says is ready — that is how a wave is dispatched; see
   [Spending the width](#spending-the-width-clock_inunit_id-job60) below.
3. Spawn the subagent with the returned brief verbatim, picking the model
   from the unit's `role`.
4. `shiftwork_clock_out(checkpoint, unit_id, status, handoff_patch,
   history_entry, accounting)` — `unit_id` must be the cursor unit or,
   since job60, a unit briefed since its own last clock-out, which is what
   lets a wave come back in any order. The whole mutated document is
   validated before any write; then one accounting line is appended to
   `<checkpoint>.log.jsonl` and the checkpoint is renamed into place, in
   that order (log-then-commit) — a partial failure can lose the commit
   but never the accounting, and a log line whose commit failed is
   detectable by re-reading the checkpoint.

Cursor advance was v1-linear until job60: clock-out moved the cursor to
the first non-terminal unit in plan order and ignored `depends_on`, so a
non-linear plan needed a planner unit to reorder `plan.units` first. That
is no longer true — `clock_out` now advances to `ready[0]` of the batch
view recomputed on the document it just mutated, which is the same answer
`shiftwork_plan` publishes for the same bytes. The executor is still ONE
cursor and the checkpoint still has no wave object; what changed is which
order the pointer walks, and that `clock_in` can be asked for a unit the
pointer is not on. See
[Spending the width](#spending-the-width-clock_inunit_id-job60) below.

**Log-line comparability with the driver.** The driver logs one JSONL
line per session; the MCP flavor logs one accounting line per clock-out
*and*, since job50, one brief line per clock-in (next section) — in
deliberately different shapes. The N-sessions experiment reads both logs
through this mapping, skipping the brief lines (`event` present, `status`
absent):

| driver `driver-log.jsonl` | MCP `<checkpoint>.log.jsonl` | note |
|---|---|---|
| `ts` | `ts` | same UTC `...Z` format |
| `cursor` | `unit` | the unit the session executed |
| `role` | `role` | identical |
| `exit` + `progressed` | `status` | the driver observes exit + hash delta; the MCP flavor records the reported unit status |
| `duration` | `duration_ms` | driver-measured vs orchestrator-reported; the MCP side is whole milliseconds, defined below |
| `seq` | — | driver-only session counter |
| — | `tokens`, `model`, `cache_read_tokens`, `tool_uses`, `note` | MCP-only orchestrator accounting — each defined below |
| — | `briefed` | MCP-only, written by the **runtime** off the ledger, never by the orchestrator — defined in the next section |

**Clock-in writes too (job50, F6).** `shiftwork_clock_in` is a writer:
when it answers `brief` — and only then; an `escalate`, `success` or
`error` issued no brief and records nothing — it appends one line
`{"event": "brief", "ts": …, "unit": …, "role": …}` to
`<checkpoint>.log.jsonl`. The ledger is therefore **no longer one line per
clock-out**. A reader tells the two shapes apart by `event`: a brief line
carries `event` and no `status`; an accounting line always carries
`status`. The write is **best-effort**: a ledger that cannot be written (a
read-only directory, a missing parent, a full disk) costs the orchestrator
the record and nothing else — the brief still returns, no error is raised,
no result changes. That is the eventlog's rule ("failing to log never fails
the tool") and job48's lesson, and it is the one place the record can go
missing silently: the accounting line of a unit whose brief line was lost
reads `briefed: false`, with no red anywhere.

Every accounting line carries `briefed`, a boolean the **runtime** writes
by reading the ledger back — after the orchestrator's keys are merged, so
a self-reported `briefed` is overwritten by the measured one, and on
`accounting: null` lines too. It means "a brief was issued for this unit
since its **last** clock-out", not "ever": brief → clock-out is `true`;
brief → clock-out(blocked) → clock-out is `true` then **`false`**, because
nobody was handed a brief for the second run — that inline re-run is
exactly the shape F6 exists to make visible, where the older ledgers could
only carry a self-report (`executed_by: orchestrator-inline`). Two briefs
before one clock-out (a relaunch after a crashed subagent) both count as
`true`. `clock_out` never refuses **on it**: a unit that was never clocked
in clocks out normally, with `briefed: false` — the field records, it does
not gate, because the recovery practice is to recover the accounting,
never to drop it.

**What an accounting line means (job50, F5).** Until this change
`accounting` had no properties at all — `additionalProperties: true` and
nothing else — and `clock_out` wrote whatever arrived. Measured on
2026-09-13 across every `.shiftwork/*.log.jsonl` on the machine that wrote
them (28 ledgers, 352 lines): 63 distinct key-sets, eight spellings of
duration (`duration_ms` 271, `duration_min` 49, `duration_s` 17, five
one-off suffixed variants), 24 lines whose `model` carries a parenthetical
note instead of an identifier, and 14 round-thousand `tokens` values with
no note saying they are estimates. The tool asset
(`assets/tools/shiftwork_clock_out.json`) now defines the keys, so that a
reader holding only the ledger can tell what a number counts, in which
unit, and which model produced it — without asking the session that wrote
it:

| key | type | meaning |
|---|---|---|
| `tokens` | integer ≥ 0, **required** | what the harness's subagent counter reports for the unit: every class it reports (input, output, cache creation) summed, **excluding cache reads**. Required because a unit whose cost is unknown cannot be compared with any other. A rounded self-estimate is allowed only if `note` says it is one |
| `cache_read_tokens` | integer ≥ 0, optional | tokens served from prompt cache, kept out of `tokens` because they dominate a real session's traffic and would swamp the work signal. Omit it when the harness reports no such figure; a written `0` means the unit read nothing from cache |
| `duration_ms` | integer ≥ 0, **required** | wall-clock from spawning the subagent to its final message, in whole milliseconds. The only duration key with a defined meaning |
| `model` | string | the exact identifier of the model the subagent actually ran on, and nothing else. Not required by the schema: where `job.roles` names the unit's role, `clock_out` already requires it and refuses a value off the list (the gate above, unchanged); where it does not, it stays optional |
| `tool_uses` | integer ≥ 0, optional | tool calls the subagent made, as the harness counts them — the denominator that makes `tokens` comparable across units of different size |
| `note` | string, optional | free text for what the fields cannot say: an estimate, a retry, a second scope under the same unit id. Anything that is not a model identifier goes here, not in `model` |

Any other key still passes through unchanged. Refusing unknown keys is
exactly the friction the `handoff.notes` change removed (F8), and the two
rules must not pull against each other. `accounting: null` stays legal on
the wire, as it always was, but a line with no numbers is not an audit
record — and where `job.roles` names the role, the missing `model` already
refuses it. What refuses an *object* that violates this definition is the
runtimes' change, landing with its own conformance gate; this section is
the definition that check enforces, not the check.

**Pre-schema lines.** The schema governs new writes only; nothing rewrites
the ledger. Validated against the definition above, 43 of the 211 lines in
this repository's own `.shiftwork/` ledgers do not conform (40 have no
`duration_ms`, 22 no `tokens`; some both), and 88 of the 352 machine-wide
(7 of those carry `tokens` as a string or null). Read a `duration_min` as
minutes and a `duration_s` as seconds, because that is what the session
that wrote them meant; the definition does not reach back to say
otherwise. A reader comparing across jobs should filter on the presence
of `duration_ms` rather than assume the history is clean. This job's own
ledger (`checkpoint-job50.json.log.jsonl`) conforms on every line, which
is the shape the definition was taken from, not a shape it imposed.

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

**`escalate` stays (user ruling 2026-09-12, J49-I6).** Measured over the
month before job49 (`.shiftwork/notes-job49/A3.md`): `shiftwork_clock_in`
answered `escalate` once in 459 calls, 52 s after the user had already
answered the question in chat, and that resolution is recorded nowhere in
the ledger. The user ruled the branch keeps its place; it is not retired
and neither runtime changes. Why it looks dead and is not: since
2026-08-18 the user's standing instruction overrides the "stop and
surface" in step 2 above — on `escalate` the orchestrator spawns an agent
to work the question, resolves it, and keeps cycling, so the resolution
lands in that agent's transcript rather than as a clock-out line (and the
brief ledger records nothing on that branch, see *Clock-in writes too*).
The one boundary that does not move: a question that is genuinely the
user's — scope, what ships, what is authorized — is still surfaced to them
at the next pause, never answered by a subagent.

No lock, deliberately: this topology has one orchestrator by
construction; `driver.lock` guards cross-process races the single-session
shape does not have, and clock-out re-validates before writing so a
concurrent driver run fails validation-visibly rather than corrupting.

### The batch view: `shiftwork_plan` and `work_plan`

**Both are READ-ONLY.** They answer one question — *which of these units does
the dependency graph permit to run at the same time?* — and then stop. Neither
opens the checkpoint for writing, and neither dispatches anything.

When they shipped (job59) that was the whole story, and this paragraph said so:
nothing about clock-in, clock-out or cursor advance moved, so the batch view was
an *instrument* — an orchestrator could see the false serialization it was
paying for, and re-order a plan by hand in response. **That stopped being the
whole story at job60**, which made the `width` reported here dispatchable
through `clock_in(unit_id)` and pointed cursor advance at `ready[0]`. The
division is still worth holding onto, because it is where the two halves meet:
these two tools compute and report, the answer they compute is now the answer
`clock_in` and `clock_out` are held to, and
[Spending the width](#spending-the-width-clock_inunit_id-job60) is where the
spending is described.

**`work_plan(nodes)` — any graph, no file.** `nodes` is a list of
`{id, depends_on, priority}`; `priority` defaults to `0`. The answer is

```json
{"result": "plan", "batches": [...], "sequence": [...], "width": N}
```

- **`batches`** — batch *k* holds every node whose dependencies all appear in
  batches below *k*.
- **`sequence`** — those batches flattened, in order.
- **`width`** — the largest batch length: the widest fan-out, which is the
  number an orchestrator needs in order to decide whether it can afford the
  batch.

Order **inside** a batch is contract, not an accident: priority descending,
then the order the nodes were given. Determinism inside a batch is what the two
implementations are held to, so both halves of that rule are gated.

It opens no file and takes no path — pure computation over the nodes it was
handed (Layer 1; see [architecture.md](architecture.md)).

**`shiftwork_plan(checkpoint)` — the same planner over a checkpoint.** It adds
`ready` and `cursor`:

```json
{"result": "plan", "batches": [...], "ready": [...], "sequence": [...], "width": N, "cursor": "<unit id>"}
```

- **`ready`** is `batches[0]`: the units whose dependencies are all satisfied.
  Since job60 a `ready` member beyond the cursor is clockable, but only in that
  order: `clock_in` briefs any unit in `ready` when `unit_id` names it, and
  `clock_out` then takes that unit back *because it was briefed*. An id that is
  neither the cursor nor briefed since its own last clock-out is still refused.
  See [Spending the width](#spending-the-width-clock_inunit_id-job60).
- **`cursor`** is echoed **unchanged** — deliberately, so the pointer and the
  batch view can be read side by side and any difference between them is
  visible rather than implied. The pointer is still one unit and only
  `clock_out` moves it; what job60 changed is that it is no longer the only
  unit `clock_in` will hand out.

**The tool's own description still says "the single-pointer contract"; this
document no longer does. Both halves are deliberate — do not "tidy" either.**
`assets/tools/shiftwork_plan.json` ends: *"It reports what the dependency graph
permits; it does not move the cursor, which is echoed unchanged so the
single-pointer contract and the batch view can be read side by side."* There the
phrase is **not false**: the cursor is still one pointer, echoed unchanged, and
an earlier sentence in the same description now states outright that *"a `ready`
member beyond the cursor is clockable, but only in that order"* — so nothing on
that asset claims the cursor is the only clockable unit. In the `cursor` bullet
above, the same phrase sat directly beside the `ready` bullet saying a briefed
non-cursor unit *is* clockable, and the two read as an argument, so job60
rewrote the prose (58c4280) and left the asset's
sentence standing. The asset was **rewritten, not cut**, and that is the part
worth remembering: clause (e) of `tools/conformance/suites/instructions.mjs`
takes the first sentence of the plan description containing both `ready` and a
clock word (its `sentenceWith(planDesc, …)` call) as the advertisement that
discloses a non-cursor `ready` unit's clockability. With no such sentence the
clause falls through to its undisclosed branch, which
requires every `ready` unit beyond the cursor to be accepted by a bare
`shiftwork_clock_out` — which a never-briefed unit correctly is **not**. Deleting
a sentence there instead of rewriting it makes the suite demand the wrong thing.
Editing that asset is not free either: it moves the pack's `assets_digest`, which
[porting.md](porting.md) quotes as a literal (`sha256:d47dcf4b…` over 87 files)
and `tools/conformance/suites/wire.mjs` compares across runtimes.

**The satisfied rule.** A unit whose status is `done` or `dropped` is
*satisfied*: it is removed from the graph, and every edge pointing at it is
treated as already resolved. `todo`, `in_progress` and `blocked` stay in the
graph. So the batch view narrows as a job progresses, which is what makes
`ready` mean "now" rather than "at the start".

Every unit has priority `0`, because the checkpoint schema has no priority
field — so order inside a batch is `plan.units` order.

**Three refusals, one sentence each, checked in this order.** They are the same
sentences on both tools and in both runtimes:

1. `duplicate node id <id>`
2. `node <id> depends on <dep>, which no node declares`
3. `the graph has a cycle: <a> -> <b> -> <a>`

`shiftwork_plan` additionally gives the same refusals `shiftwork_status` gives
for a checkpoint it cannot read.

**Empty input is an ANSWER, not a refusal**: no batches, no sequence, width 0.

**Worked example, measured 2026-09-19** by calling both tools over stdio against
both servers (`runtime-py` via `python -m bantamkit.mcpserver`, `runtime-ts` via
`dist/cli.js`) — the two answered byte-identical JSON on every line below:

```
work_plan, the 8 units of this page's own job:
  {"result":"plan","batches":[["W1","W2","W3"],["W4","W5"],["W6"],["W7"],["W8"]],
   "sequence":["W1",...,"W8"],"width":3}

work_plan, nodes []:              {"result":"plan","batches":[],"sequence":[],"width":0}
work_plan, a -> b -> a:           {"result":"error","reason":"the graph has a cycle: a -> b -> a"}
work_plan, a depends on ghost:    {"result":"error","reason":"node a depends on ghost, which no node declares"}
work_plan, two nodes called a:    {"result":"error","reason":"duplicate node id a"}

shiftwork_plan, .shiftwork/checkpoint-workplan.json with W1..W6 done:
  {"result":"plan","batches":[["W7"],["W8"]],"ready":["W7"],"sequence":["W7","W8"],
   "width":1,"cursor":"W7"}
```

That first line is also the honest self-assessment of this feature: the job that
built the planner was itself dispatched as eight serial units, because
`shiftwork_clock_in` only ever handed back the cursor unit. Its own planner says
three of those eight could have gone at once. That is the gap job60 closed, and
the next section is the closing of it.

**What the tools do NOT decide.** `depends_on` encodes *logical* order, not file
contention. A batch these tools call parallel may still hold two units that
write the same file. They report what the graph permits; an orchestrator stays
responsible for what it actually dispatches.

**Where the code lives.** The batcher itself is
`runtime-py/src/bantamkit/workplan.py` and `runtime-ts/src/workplan.ts` — Layer
1, hand-written on both sides against `ex-flow`'s semantics rather than taking
`ex-flow` as a dependency, for the reason in
[porting.md](porting.md#ex-flow-a-fifth-library-evaluated-and-rejected).
The checkpoint reader is `shiftwork.plan_batches` / `planBatches`, and the two
are compared by the `workplan` suite (`node tools/conformance/run.mjs --suite
workplan`).

### Spending the width: `clock_in(unit_id)` (job60)

The batch view shipped announcing a `width` the dispatch surface gave no way to
spend. `shiftwork_plan` answered `ready` from `depends_on`; `shiftwork_clock_in`
answered from `plan.cursor`, a pointer `clock_out` advanced in `plan.units`
order with `depends_on` ignored. Two surfaces reading one document in two
different orders, which cost two things: a two-wide batch could be *seen* and
not *dispatched*, and — the sharper one — the cursor could land on a unit whose
dependencies had not run, handing an agent work whose inputs did not exist yet,
with no refusal and no warning. Since job60 the two orders are one order.

**`clock_in` takes an optional `unit_id`.**

```
shiftwork_clock_in(checkpoint)            # unchanged, byte for byte: the cursor unit
shiftwork_clock_in(checkpoint, unit_id)   # that unit, IF the graph says it is ready
```

Omitting it is the whole prior contract, including its `escalate` when the
cursor names no unit; the order of judgements above the selection is unmoved, so
no existing refusal changed its place or its wording. Given, `unit_id` must name
a member of `ready` — the same list `shiftwork_plan` publishes for the same
bytes, recomputed on the document as read. **One** refusal covers both ways that
can fail, because they are one property — the unit is not ready — and a
`unit_id` that names no unit at all is the limiting case of it rather than a
second thing to spell:

```json
{"result": "error", "reason": "unit N3 is not ready; ready is N1, N2"}
```

`ready` is joined with `", "` in batch order, and it is in the sentence because
the caller's next move is to pick from it. It can never be empty there: the
all-terminal check above it has already answered `success` for a plan with no
non-terminal unit, so no sentence is written for a case that cannot be reached.
A refusal from the batch view *itself* — a cycle, an unknown dependency, an
unreadable file — passes through verbatim, in the three sentences listed above.

**A dangling `plan.cursor` is now escapable, and that is deliberate.** A pointer
naming no unit still `escalate`s on the default path, with the sentence it has
always had (`cursor <id> names no unit`) — that judgement sits above the
selection and job60 did not move it. But naming a ready unit proceeds anyway, on
the same bytes, because the graph is readable whatever the pointer says: a
broken pointer no longer stops a wave the graph permits. It is the one existing
refusal this job made conditional without changing a word of it, so it is pinned
by its own conformance session rather than left as a behaviour both runtimes
happen to share.

**`clock_in` still never writes `plan.cursor`.** A wave of N briefs leaves the
pointer exactly where it was; `clock_out` is the only thing that moves it. The
brief line records the unit actually briefed, so `briefed` keeps working per
unit with no change to how it is computed — which is what lets the clock-out
side widen with no new field anywhere, and why the checkpoint schema
(`assets/schemas/shiftwork-checkpoint.json`) is untouched by this job.

**`clock_out` accepts the cursor unit OR a unit briefed since its own last
clock-out.** That is the `briefed` value defined in *Clock-in writes too* above
— measured by the runtime off `<checkpoint>.log.jsonl` and never taken from the
caller, so the gate and the record cannot disagree about a unit. The widening is
what makes a wave spendable: N briefs are issued against one cursor, so if only
the cursor could clock out, the other N−1 results would have nowhere to go. A
unit that was never dispatched still cannot clock out.

**The refusal sentence still says "is not the cursor unit", and that is
deliberate:**

```json
{"result": "error", "reason": "unit N3 is not the cursor unit N1"}
```

It is kept byte for byte — widened meaning, unwidened wording — so that every
ruled case pinning it stays green, and this paragraph is where the fuller
meaning lives. Read it as *"N3 is neither the cursor unit nor a unit this
checkpoint's ledger says was briefed since its own last clock-out"*. The cursor
is the half named because it is the half a caller can see without reading the
ledger. (A `unit_id` naming no unit in the plan is still refused earlier and
separately, `unit N3 is not in the plan`, unchanged.)

**Cursor advance follows the graph.** After the status is applied, on the
document as just mutated, `clock_out` sets `plan.cursor` to:

1. `ready[0]` of the batch view recomputed on that document — the value
   `shiftwork_plan` would publish for the same bytes; else
2. the first remaining non-terminal unit in `plan.units` order. Reachable only
   when the graph cannot batch at all — a cycle, an unknown dependency — because
   `ready` is computed over exactly those remaining units. It exists so such a
   checkpoint can still be driven to its end: clock-out *records*, and a
   recording surface does not acquire a new way to refuse; else
3. `unit_id`, unchanged from before this job.

On a linear chain `ready[0]` is `remaining[0]`, so a plan whose units are
declared in dependency order — which is every plan written in this repository
before job60 — keeps every cursor value it had.

**A worked wave, measured 2026-09-20** by driving the same three-unit checkpoint
through **both** runtimes — `runtime-py`'s module and `runtime-ts/dist` — which
answered this line for line. `N1` and `N2` are independent, `N3` depends on
both, all three are `todo`, and the cursor is `N1`:

```
shiftwork_plan              -> {"result":"plan","batches":[["N1","N2"],["N3"]],
                                "ready":["N1","N2"],"width":2,"cursor":"N1"}
clock_in()                  -> brief N1                              cursor N1
clock_in(unit_id="N2")      -> brief N2                              cursor N1
clock_in(unit_id="N3")      -> error: unit N3 is not ready; ready is N1, N2
clock_in(unit_id="N9")      -> error: unit N9 is not ready; ready is N1, N2
   ... both agents run in parallel, N2 finishes first ...
clock_out("N2", done)       -> {"result":"ok","cursor":"N1"}         cursor N1
shiftwork_plan              -> ready ["N1"], width 1, cursor "N1"
clock_out("N3", done)       -> error: unit N3 is not the cursor unit N1
clock_out("N1", done)       -> {"result":"ok","cursor":"N3"}         cursor N3
clock_in()                  -> brief N3                              cursor N3
```

Four things in that trace are the point of the feature. The two `clock_in`s hand
out two different units. Neither moves the cursor. `N2` clocks out before `N1`
and is accepted although the cursor never pointed at it, because the ledger says
it was briefed — while `N3`, briefed to nobody, is refused by the same gate one
line later. And the last cursor is `N3` because the graph says so, not because
`N3` is next in `plan.units`.

**The workaround this retires.** Before job60 a two-wide wave could only be
dispatched by leaving the tools: clock the first unit out at `in_progress` as a
dispatch-only record, then edit `plan.cursor` to the second unit **by hand** in
the checkpoint file — because `clock_in` only ever returned the cursor unit and
`clock_out` advanced the cursor only on a terminal status. The alternative was
worse: declaring a running unit `done` falsifies the ledger. Its last use was
this job's own two runtime halves, dispatched together: the ledger line that
did the dispatching says so in its own words — *"Dispatch line, not a cost
line: U2 is still running, so tokens and `duration_ms` are written 0 and the
measured figures land on U2's terminal clock-out"* — and then `plan.cursor` was
edited by hand to the Node half. That ledger lives under `.shiftwork/`, which
this repository gitignores, so it is quoted here rather than cited: a path no
reader can open is not evidence. The same dispatch is now
`shiftwork_clock_in(checkpoint, unit_id="U3")`, and nothing edits the file.

**The gate.** Seven conformance sessions in
`tools/conformance/suites/shiftwork.mjs` compare the two runtimes over this
surface — the disagreement state, the wave, both refusals, the default path and
the dangling cursor. They are built on documents whose plan order and graph
order *disagree*, and the suite prints what they pin: 43 per-side cases over
those 7 sessions, on top of the differential rows, because the differential
alone is blind to a sentence paraphrased on both sides. The corpus gap that hid
the defect is worth naming, because it is the shape a future case must avoid:
every checkpoint already in the suite declares its units in dependency order, so
`cursor` equals `ready[0]` at every step, and `clock_in(unit_id)` could only
ever have been handed the unit `clock_in()` would have picked anyway. A case
that asserts each field against itself cannot see this class of bug; the one
that does asserts the two fields against *each other*.

```
node tools/conformance/run.mjs --suite shiftwork
PASS: 1697 cases, 1105 byte-identical, 0 exact-string, 592 structural, 1 ruled-different, 0 failures
```

Both runtimes agreed on every new case, so job60 adds no row to
[porting.md](porting.md)'s divergence table.

## Conventions and future work

Per-role prompt files (`.shiftwork/prompts/<role>.md`) and tunables
(`.shiftwork/profiles/*.yaml`) are conventions only in v1 — a retro patch is a
commit whose message cites its trigger. Not shipped: retro automation,
Windows support, notification transports beyond `notify_cmd`, and the
N-sessions experiment itself (the MCP flavor above ships its instrument:
the per-unit accounting log).
