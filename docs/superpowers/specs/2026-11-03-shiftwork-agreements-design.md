# Shift-work agreements: a lesson adopted once rides on every later brief

Date: 2026-11-03. Status: proposed. Chain: 4 of 8 (needs unit results, #259; follow-ups,
#260, share the clock-out shape). Borrowed from `ex-workflow`'s `retro` (lessons → working
agreements carried by every brief, `retire` by exact text), as specification only (route B).

## The problem

`docs/shiftwork.md` lists "retro automation" as not shipped. `retro[]` exists in the schema
(`{trigger, patch_applied_to}`), but nothing reads it back into a brief, so a lesson learned
in unit 4 reaches unit 9 only if the orchestrator remembers to paste it.
`handoff.do_not` is the nearest thing, but it is one shared list overwritten by
`handoff_patch`, with no record of who added what or why.

## Decisions

**D1 — the list.** `job.agreements`: optional array of non-empty strings, at most
`AGREEMENTS_MAX = 20`. Every brief carries `agreements` (always present; `[]` when none).

**D2 — changed only through clock-out.** `clock_out` takes an optional
`agreements: {adopt?: [string], retire?: [string]}`. `retire` removes by exact text, then
`adopt` appends (an exact duplicate is not added twice). Refusals, nothing written:
- retiring text not on the list: `no agreement reads <repr>`;
- the result over 20: `agreements would number <n>; retire one first (at most 20)`.

**D3 — the record.** Every applied change appends one `retro[]` entry:
`{trigger: <unit id>, patch_applied_to: "job.agreements"}` plus `adopted` / `retired` lists.

**D4 — scope.** No automatic lesson mining, no DoD policies, no skill notes. bantamkit's skill
miner is the place for cross-job lessons; this is per-job.

## Surfaces

Layer 2: schema (`job.agreements`, `retro[]` extra keys), clock_in output, clock_out input.
Layer 5: both `shiftwork` modules. Docs (replace "retro automation" in Not shipped).

## Gates

Conformance (shiftwork suite): adopt then brief shows it; retire by exact text; duplicate
adopt is a no-op; both refusals per side as literals with checkpoint + log byte-unchanged;
`retro[]` entry shape.
