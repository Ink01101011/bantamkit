# bantamkit

Layer discipline is strict: a change lives in exactly one layer
(docs/architecture.md). Run the suite from the repo venv:
`.venv/bin/python -m pytest runtime-py/tests -q` and keep
`.venv/bin/ruff check runtime-py tools` clean.

## Two runtimes, one surface — a feature lands in BOTH or it does not land

`runtime-py/` and `runtime-ts/` are two implementations of the same product. They
share a memory store on disk, so a surface that exists in one and not the other is
not a gap in coverage — it is a way for the two to disagree about a user's data.

**Any new feature, flag, tool, error message, or behaviour MUST be implemented in
both `runtime-py/` and `runtime-ts/` in the same job.** Not "Python first, Node
later". Not "the port will catch up". Neither runtime is allowed to grow a surface
the other lacks.

This applies to all of it:

- a new CLI flag  →  both parsers, and it appears in both `-h` outputs
- a new MCP tool  →  both servers, same name, same input schema, same output shape
- a new error     →  both raise it, with the same sentence and the same exit code
- a new default   →  the same number on both sides, and the help text that prints it
- a bug fix that changes observable behaviour  →  fixed in both, not just where it was found

**A deliberate difference is allowed, and it costs three things:** a written reason
in `docs/porting.md`'s divergence table, a `ruling:` conformance case that pins the
wording, and — where the difference is a refusal rather than a spelling — a second
non-ruled case comparing the refusal bit, because a ruling only proves the two sides
still DIFFER, never that both still refuse.

**The gate is a conformance case, not a promise.** A feature is not ported because
someone wrote it twice; it is ported when `node tools/conformance/run.mjs --all`
compares the two answers and they match. Add the case in the same change as the
feature. Without one, the parity is a claim nobody can rerun.

Layer discipline still applies on top of this: the Python half and the Node half are
separate layers, so they are separate units of work — but they belong to the SAME
job, and that job is not done when only one of them has landed.

The rule exists because it was broken: `--assets-root` shipped in `runtime-ts` with
no Python counterpart, so a byte-identical `-h` would have had to leave a working
flag undocumented. Nothing failed, because nothing compared the two CLIs at all.

## Shift-work orchestration policy

Any multi-unit orchestration — ≥2 planned units, or any
spec→plan→implement / bugfix / code-trace job that fans out agents — MUST
run its agent spawns through the shiftwork MCP tools:

1. Plan once into a schema-valid checkpoint (convention:
   `.shiftwork/checkpoint.json`; template:
   `tools/shiftwork/example-codefix-checkpoint.json`).
2. Per unit: `shiftwork_clock_in` → spawn the subagent with the returned
   brief verbatim → `shiftwork_clock_out` with status, handoff patch,
   history entry, and accounting (tokens, duration, and the model actually
   used — the model choice is yours per role, never random, always logged).
3. On `result: escalate`, stop and ask the user. On `result: success`, the
   job is done.

**Amendment 2026-09-11 (job46, AS-2).** The clause above stands as written: the
model is per role, never random, always logged. As of this job it is also
CHECKED. `job.roles` in the checkpoint contract
(`assets/schemas/shiftwork-checkpoint.json`) maps a unit role to the model
identifiers that role may report; when it names a unit's role,
`shiftwork_clock_out` refuses an accounting entry whose `model` is not on that
list — and refuses one that reports no model at all — before anything is
written: no accounting line, no cursor advance, the checkpoint byte-unchanged.
Models compare exactly (`claude-opus-5[1m]` is not `claude-opus-5`). Declaring
nothing keeps exactly the behaviour the clause describes, so a checkpoint
written before this job is unaffected. Enforced in both runtimes and gated by
38 per-side cases in `node tools/conformance/run.mjs --suite shiftwork`; see
`docs/shiftwork.md`.

**Amendment 2026-09-20 (job60, waves).** Step 2 above reads as a strictly
sequential loop, and until this job it was one: `shiftwork_clock_in` only ever
returned `plan.cursor`, so dispatching two units at once meant leaving the tools
— a dispatch-only clock-out at `in_progress` and then editing `plan.cursor` by
hand in the checkpoint file. As of this job the step is still per unit, but a
whole wave may run through it at once. `shiftwork_clock_in` takes an optional
`unit_id`; a unit named there must be one `shiftwork_plan` reports as `ready`,
and anything else is refused with `unit <id> is not ready; ready is <list>`
before any brief is issued. Clock-in still never writes `plan.cursor`, so N
briefs leave the pointer where it was. `shiftwork_clock_out` now takes back the
cursor unit **or** any unit briefed since its own last clock-out — measured by
the runtime off `<checkpoint>.log.jsonl`, never reported by the orchestrator —
so a wave clocks out in whatever order it finishes; a unit that was never
dispatched is still refused, and that refusal keeps its existing sentence
(`unit <id> is not the cursor unit <cursor>`) byte for byte so every case
pinning it stays green. And `plan.cursor` now advances to `ready[0]` of the
graph recomputed on the mutated document, so the pointer can no longer land on a
unit whose dependencies have not run; the `plan.units` fallback is reachable only
when the graph cannot batch at all. A caller that never passes `unit_id` is
unaffected, and no checkpoint field was added. Enforced in both runtimes and
gated by 36 per-side cases over 6 sessions in `node tools/conformance/run.mjs
--suite shiftwork` (PASS 1678 cases, 0 failures); see `docs/shiftwork.md`,
*Spending the width*.

Exempt: one-off ad-hoc spawns (a single search or review with no plan
behind it) — no unit to clock.
