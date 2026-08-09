# Shift-Work Orchestrator Design (v1: schema + driver)

**Date:** 2026-08-10
**Status:** Approved (user-directed queue item, promoted from backlog
2026-08-10). Consolidates the two committed drafts — checkpoint contract
(`2026-08-10-shift-work-checkpoint-contract-draft.md`) and driver
(`2026-08-10-shift-work-driver-draft.md`) — whose open questions were all
resolved pre-cycle; this spec is the buildable subset for v1.

## 1. Problem

Big jobs burn context: one long session pays compaction, drift, and
re-derivation. The user's model: plan once into small units, then
clock-in/clock-out stateless sessions — read checkpoint → do one unit →
write checkpoint → exit (เข้างาน/เลิกงาน). Two artifacts make that real:
a **checkpoint contract** (lossless resume in one file read) and a
**dumb-by-construction driver** (spawns sessions, decides nothing).
The falsifiable claim behind it — N short sessions ≥ one long session on
score/tokens/wall-clock — is measured later with bantamkit's own
harness; v1 ships the mechanism, not the experiment.

## 2. What v1 ships

### 2.1 Checkpoint schema as an asset (Layer 2 data, dogfooding)

`assets/schemas/shiftwork-checkpoint.json` — JSON Schema (draft
2020-12) encoding checkpoint contract v1 exactly as drafted, including
the driver-forced deltas: `plan.units[].role` (planner | implementer |
reviewer), `state.external[].until_cmd` (machine-checkable wait), flat
`units` list, single `plan.cursor`, `handoff.open_questions` as the
autonomy switch, `handoff.do_not`, `history` ring, `retro` entries.
Required at every level per the draft's schema block; `version: 1`
const-pinned so readers can refuse unknown majors.

New asset kind ⇒ tiny loader `load_schema(name)` in `assets.py`
(mirrors `load_tool`/`load_skill`; returns the parsed dict). Sessions
validate checkpoints via the existing `schema_error` (SchemaGate's
engine) — the dogfooding decision: bantamkit validates the orchestration
layer that will drive bantamkit development.

### 2.2 The driver: `tools/shiftwork/driver.py` (repo tool, not wheel)

Single-file Python, stdlib only, per the driver draft's loop verbatim:

- Reads ONLY: `version`, `handoff.open_questions`, unit `status`
  fields, `state.external[].until_cmd`, `plan.cursor`, and (for
  dispatch) `plan.units[].role`. Everything else is opaque bytes.
- Loop: validate (minimal structural check, stdlib — full JSON-Schema
  validation belongs to sessions) → exits: ESCALATE (open_questions
  non-empty) / SUCCESS (all units done|dropped) / BUDGET (session or
  wall-clock caps) → wait on `until_cmd` with exponential backoff
  (30 s → 5 min cap) → spawn `claude -p "$CLOCK_IN_PROMPT"` with
  per-role model/allowed-tools from `driver.yaml` → progress = sha256
  delta of the checkpoint file → retries in `driver-state.json`
  (never in the checkpoint) → STALLED after MAX_RETRIES.
- `CLOCK_IN_PROMPT` is a constant string (draft wording), never
  templated per unit.
- `driver.yaml` config: role → {model, allowed_tools}, budgets,
  `notify_cmd` (default macOS `osascript`), per-external timeout.
  Permission posture: `--permission-mode acceptEdits` + per-role
  `--allowedTools`; `--dangerously-skip-permissions` only behind an
  explicit yaml opt-in.
- `driver.lock` (pid + start ts) against double drivers; clean-exit
  handling and the full failure table from the draft.
- The driver log (one line per session: ts, seq, cursor, role, exit,
  duration, progressed?) is the experiment's measurement instrument.

Since the driver spawns no sessions in CI, its unit tests fake
`subprocess.run`: exits, retry/stall accounting, lock behavior,
until_cmd waiting (with a fake clock), unparseable-checkpoint escalate,
hash-delta progress detection, budget exits. The driver is the one
deterministic component — it gets real tests (draft decision).

### 2.3 Example checkpoint + docs

- `tools/shiftwork/example-checkpoint.yaml` — the draft's own example,
  schema-valid (test-enforced against the asset schema via
  `jsonschema`).
- `docs/shiftwork.md` — what it is, the contract's 8 load-bearing
  decisions (from the draft), driver usage (`python tools/shiftwork/
  driver.py --checkpoint … --config driver.yaml`), the failure tables,
  and the honest status: **mechanism shipped, claim unmeasured** — the
  N-sessions-vs-one experiment is explicitly future work with the
  driver log + per-session accounting named as its instrument.

## 3. Testing

- Schema asset: valid example passes; mutations fail (wrong version,
  missing cursor, bad status enum, non-list open_questions) — via the
  session-side validator (`schema_error`).
- `load_schema`: happy path + AssetNotFound.
- Driver: the fake-subprocess suite per §2.2 (target: every exit path
  and every failure-table row asserted).
- Whole suite stays green (387 + new); ruff clean (driver included).

## 4. Success criteria

1. Schema asset + loader + driver + example + docs land; all tests
   green; CI green.
2. Example checkpoint validates against the shipped schema in CI.
3. v0.11.0 (new asset kind in the pack), tag, pinned install verified
   (`load_schema("shiftwork-checkpoint")` resolves from the wheel).
4. PR merged (pre-authorized).

## 5. Out of scope (v1)

- The MCP server flavor (clock_in/clock_out as MCP tools) — revisit
  after the driver has driven one real job.
- The N-short-sessions vs one-long-session experiment (needs a real
  job; the driver log is built for it).
- Retro automation beyond the schema fields; prompt/profile patch
  tooling (`.shiftwork/prompts|profiles` conventions documented only).
- Windows support; notification transports beyond `notify_cmd`.
- Driving THIS repo's remaining work with the driver (dogfood later,
  deliberately — the first run should be a watched one).
