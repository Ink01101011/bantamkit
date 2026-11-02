# Shift-work follow-ups: a unit can add the work it discovered, without the orchestrator editing the checkpoint

Date: 2026-11-03. Status: proposed. Chain: 3 of 8 (needs unit results, #259). Borrowed from
`ex-workflow`'s handoff `follow_ups` and `rework` verdict, as specification only (route B).

## The problem

A unit that finds more work than it was given has two options today: stuff it into
`handoff.notes`, or stop so the orchestrator can hand-edit `plan.units` — the same out-of-tool
edit job60 removed for `plan.cursor`. A hand edit skips every check clock-out makes.

## Decisions

**D1 — `follow_ups` on clock-out.** `clock_out` takes an optional
`follow_ups: [{id, title, role, brief_path, depends_on?, verify?, touches?}]`. Each becomes a
`todo` unit appended to `plan.units` in the given order. `depends_on` defaults to
`[<clocking-out unit>]`.

**D2 — checked whole, before anything is written.** In this order, first fault wins, nothing
written, checkpoint and log byte-unchanged:
1. an id already in `plan.units` or twice in the list: `follow-up <id> is already a unit`;
2. `brief_path` that is not a file relative to the checkpoint's repo:
   `follow-up <id> names brief <path>, which is not a file`;
3. a `depends_on` id that no unit (old or new) declares — the planner's own sentence;
4. the mutated graph has a cycle — the planner's own sentence;
5. `role` not in `job.roles` when `job.roles` is declared:
   `follow-up <id> has role <r>, which job.roles does not declare`.
Then the whole mutated document is schema-validated as today.

**D3 — rework is a status, stated.** No new verdict enum. A unit clocked out `todo` with an
attempt recorded (#259) IS a rework: its next brief carries `prior_attempts`. `docs/shiftwork.md`
says so; the existing behaviour is unchanged.

**D4 — escalation stays human.** `open_questions` non-empty still means stop and ask the user
(ruling 2026-09-12, J49-I6). No question units.

**D5 — width.** Follow-ups enter the graph on the same write, so `ready` and the `ready[0]`
cursor advance (job60) already account for them; `touches` (#257) applies to them.

## Surfaces

Layer 2: `shiftwork_clock_out.json` (`follow_ups` schema). Layer 5: `shiftwork.py` /
`shiftwork.ts`. Docs.

## Gates

Conformance (shiftwork suite): two follow-ups appended in order, default `depends_on`, both in
`ready` after the clock-out; each D2 refusal per side as a literal with checkpoint + log
byte-unchanged; a follow-up that makes a cycle; `todo` clock-out re-briefs with
`prior_attempts`.
