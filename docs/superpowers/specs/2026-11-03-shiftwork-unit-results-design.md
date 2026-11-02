# Shift-work unit results: a brief carries what its dependencies produced and its own earlier attempts

Date: 2026-11-03. Status: proposed. Chain: 2 of 8 (after `touches`, #257). Borrowed from
`ex-workflow`'s brief `upstream` / `priorHandoffs`, as specification only (route B: no
dependency, both runtimes hand-write it, conformance proves they agree).

## The problem

`clock_in` returns `{unit, role, invariants, handoff, do_not, files}`. Nothing in it says what
the units this one `depends_on` actually produced, nor what an earlier attempt at this same
unit found. The orchestrator re-derives both by hand and pastes them into the spawn, which is
the re-derivation the brief exists to remove (an orchestrator that hand-edits a brief drops what the runtime synthesized).
The only place results land today is `history`, a 5-entry ring: in a 32-unit job the result of
unit 3 is gone long before unit 20, which depends on it, is briefed.

## Decisions

**D1 — durable per-unit record.** `plan.units[].attempts`: optional array, newest last, at most
`ATTEMPTS_KEPT = 3` entries per unit. `clock_out` appends one entry built from what it already
receives: `{status, outcome, notes?, produced?}` — `status` is the clock-out status, `outcome`
and `notes` are `history_entry`'s, `produced` is `history_entry.produced` when present
(`[{kind, ref}]`, both non-empty strings; `history_entry` already passes extra keys through).
No new `clock_out` parameter. The ring stays as it is.

**D2 — the brief.** `clock_in` adds two keys:
- `upstream`: one item per `depends_on` id, in `depends_on` order: `{unit, title, status,
  last}` where `last` is that unit's newest attempt, or `null` when it has none;
- `prior_attempts`: this unit's `attempts`, oldest first (empty list when none).
Both keys are always present, so a brief's shape does not depend on the plan.

**D3 — size.** `notes` in an attempt is capped at `ATTEMPT_NOTES_MAX = 2000` code points; a
longer string is refused by `clock_out` before anything is written:
`history_entry notes are <n> code points; an attempt keeps at most 2000`.
(Counted in code points so both runtimes agree on non-ASCII text.)

**D4 — compatibility.** A checkpoint without `attempts` validates and briefs as before plus
`upstream` (with `last: null`) and `prior_attempts: []`.

## Surfaces (both runtimes, same job)

Layer 2: schema (`attempts`, `produced` shape), `shiftwork_clock_in.json` output schema,
`shiftwork_clock_out.json` (`history_entry.produced`). Layer 5: `shiftwork.py` / `shiftwork.ts`
(append on clock-out, D3 refusal, brief keys). Docs: `docs/shiftwork.md`.

## Gates

Conformance (shiftwork suite), each new case proven red first: attempts appended and capped at
3 (oldest dropped); `upstream` order and `last: null`; `prior_attempts` after a `todo`
clock-out (rework); the D3 sentence per side, checkpoint and log byte-unchanged; a checkpoint
with no `attempts` briefs with the two empty keys. Literals per side for the cap and the D3
sentence.
