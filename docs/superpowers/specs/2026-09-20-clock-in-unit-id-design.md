# Clocking in a unit the graph says is ready

**Job 60.** Branch `fix/job60-clock-in-unit-id`, worktree
`.claude/worktrees/shiftwork-cursor-contradiction`, cut from main `208a0f4`.

## The contradiction this closes

`shiftwork_plan` (job 59's read-only batch view) answers `width` and `ready` from the
`depends_on` graph. `shiftwork_clock_in` answers from `plan.cursor`, a single pointer
`clock_out` advances in **`plan.units` order with `depends_on` ignored**
(`runtime-py/src/bantamkit/shiftwork.py:493`, `runtime-ts/src/shiftwork.ts:650`). The two
surfaces therefore disagree, and both halves of the disagreement were measured
2026-09-20 against the live MCP (`build_identity`: node, 0.35.2) and the Python module:

**Shape 1 — the width cannot be spent.** Units `N1`, `N2` independent, `N3` on both:

```
shiftwork_plan  -> {"batches":[["N1","N2"],["N3"]],"ready":["N1","N2"],"width":2,"cursor":"N1"}
clock_in x3     -> N1, N1, N1        (the third with N1 already in_progress)
clock_out N2    -> {"result":"error","reason":"unit N2 is not the cursor unit N1"}
```

There is no argument that asks for `N2`, and `clock_out` advances the cursor only on a
terminal status — so the only route to `N2`'s brief is editing `plan.cursor` by hand,
which is leaving the tool, or declaring a running unit `done`, which is falsifying the
ledger.

**Shape 2 — the cursor can land on a unit whose dependencies are unmet.** Units
`[A, C(depends_on B), B]`, cursor `A`:

```
clock_out A done -> {"cursor":"C"}
shiftwork_plan   -> ready: ["B"]
clock_in         -> brief for C, depends_on ["B"] not run. No refusal, no warning.
```

Plan order and graph order are different orders; cursor advance uses the first and
`ready` uses the second. Shape 2 is the sharper one: shape 1 costs parallelism, shape 2
hands an agent work whose inputs do not exist yet.

**Neither is a coding defect.** `plan_batches`' own docstring says the cursor is
"ECHOED, never written … Advisory, in one direction only", and
`docs/superpowers/specs/2026-09-18-workplan-dag-design.md` § *What does not change*
declares `clock_in`, `clock_out` and cursor advance untouched byte for byte. The
advisory surface shipped announcing a number the dispatch surface gives no way to spend.
This job is the other half of that design, not a repair of it.

**Why no gate caught it.** Every `plan_batches` test
(`runtime-py/tests/test_shiftwork.py:1570-1650`) picks a checkpoint where
`cursor == ready[0]`, including the two-wide case — nothing compares the two fields.
Conformance is blind to it because both runtimes are identical here, which is the
`differential-is-blind-to-symmetric-regression` shape.

## The change

### D1 — `clock_in` takes an optional `unit_id`

```
shiftwork_clock_in(checkpoint)            # unchanged, byte for byte: the cursor unit
shiftwork_clock_in(checkpoint, unit_id)   # that unit, IF the graph says it is ready
```

Order of judgements, unchanged at the top so no existing refusal moves:

1. read + schema-validate → `result: error` on failure
2. `handoff.open_questions` non-empty → `result: escalate`
3. every unit `done`/`dropped` → `result: success`
4. **unit selection** — `unit_id` omitted → `plan.cursor` exactly as today; `unit_id`
   given → it must appear in the batch view's `ready`

A `unit_id` that is not ready, including one that names no unit at all, is one refusal:

```
{"result": "error", "reason": "unit C is not ready; ready is B"}
```

`ready` is joined with `", "` in batch order. The list is included because the caller's
next move is to pick from it. If the batch view itself refuses — cycle, unknown
dependency, unreadable file — that refusal passes through **verbatim**, in both
directions, exactly as `plan_batches` already passes `_read_valid`'s.

`ready` cannot be empty at step 4: step 3 has already answered `success` for a plan with
no non-terminal unit. No sentence is written for a case that cannot be reached.

The brief log line records the unit actually briefed, so `clock_out`'s `briefed` flag
keeps working per unit with no change to how it is computed.

**`clock_in` still never writes `plan.cursor`.** A wave of N briefs leaves the pointer
where it was; it is `clock_out` that moves it, and D3 changes where to.

### D2 — `clock_out` accepts a unit it briefed

Today `unit_id` must equal `plan.cursor`. After this job it must be **the cursor unit
OR a unit briefed since its own last clock-out** — the `briefed` value the runtime
already computes from `<checkpoint>.log.jsonl` and already refuses to take from the
caller. A unit that was never dispatched still cannot be clocked out, and the refusal
keeps its existing sentence, unchanged in both runtimes:

```
{"result": "error", "reason": "unit N2 is not the cursor unit N1"}
```

The sentence is kept rather than widened so that every ruled case pinning it stays
green; `docs/shiftwork.md` carries the fuller meaning.

### D3 — cursor advance follows the graph

After the status is applied, on the mutated document:

1. `ready` non-empty → `plan.cursor = ready[0]`
2. else remaining non-terminal units in `plan.units` order non-empty → `remaining[0].id`
   (only reachable when the graph cannot batch at all — cycle or unknown dependency —
   because `ready` is computed over exactly those remaining units)
3. else → `unit_id`, unchanged from today

For a linear chain, `ready[0] == remaining[0]`, so every existing case holds its value.
Step 2 exists so a checkpoint whose graph cannot batch can still be driven to the end;
`clock_out` records, and a recording surface does not acquire a new way to refuse.

### D4 — the two adapters and the asset

`assets/tools/shiftwork_clock_in.json` gains the optional `unit_id` property (and
nothing becomes required). Both MCP servers pass it through. Same name, same schema,
same output shape, per CLAUDE.md.

## What does not change

`handoff_patch` merge, the history ring, the log-then-commit ordering, the AS-2
role/model gate, the `{"result": "ok" | "escalate" | "error" | "success"}` vocabulary,
`shiftwork_status`, `shiftwork_plan`, `work_plan`, and
`assets/schemas/shiftwork-checkpoint.json`, which is not edited — this job adds no field
to the checkpoint. A caller that never passes `unit_id` sees byte-identical behaviour on
every surface except a cursor value that differed only in a plan whose units are
declared out of graph order.

## Out of scope

- **No concurrency cap and no file-contention check.** The 2026-09-18 spec measured a
  12-wide batch in which 7 units name one file; `depends_on` is logical order, not write
  contention. The orchestrator stays responsible for what it dispatches. Unchanged.
- **No lock.** "One orchestrator by construction" still holds; two orchestrators
  clocking the same checkpoint is still undefined.
- **No `dispatched` status and no wave object.** The status enum is untouched.
- **No priority field.**

## The gate

A feature is ported when `node tools/conformance/run.mjs --all` compares the two answers
and they match, and the case lands in the same change. New cases in
`tools/conformance/suites/shiftwork.mjs`:

1. **cursor ≠ ready[0]** — the shape-2 checkpoint, driven to the disagreement, then
   `clock_in` with and without `unit_id`. This is the case whose absence hid the bug:
   it asserts the two fields against each other, not each against itself.
2. **a wave** — `clock_in(unit_id=N2)` on a two-wide ready batch, then `clock_out N2`
   before `N1`, then the cursor value.
3. **the not-ready refusal sentence**, including a `unit_id` naming no unit.
4. **the never-briefed refusal**, pinning that `clock_out` did not become permissive.
5. **the default path** — `clock_in` with no `unit_id` on the codefix template, byte
   for byte what it answers today.

Gates for the job: `PYTHONPATH=<worktree>/runtime-py/src .venv/bin/python -m pytest
runtime-py/tests -q`, `.venv/bin/ruff check runtime-py tools`, `npm test` in
`runtime-ts`, and `node tools/conformance/run.mjs --all`.

**Worktree baseline at `208a0f4`, before any change:** pytest `6 failed, 2908 passed, 57
skipped, 2 deselected, 3 xfailed`. Four failures are
`test_conformance_harness_resilience.py` (the rig hardcodes `REPO/.venv`, which a
worktree has not) and two are `test_served_tool_count_records.py` before
`runtime-ts/dist` exists; after `npm install && npm run build` in the worktree the
latter two pass. None is a product defect — see the `worktree-traps-pytest-and-
conformance-venv` memory. A unit reporting a pytest number from this worktree must name
its `PYTHONPATH`.
