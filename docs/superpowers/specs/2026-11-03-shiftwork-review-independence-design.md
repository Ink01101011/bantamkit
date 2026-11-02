# Shift-work review independence: a reviewing unit cannot share a role with the work it reviews

Date: 2026-11-03. Status: proposed. Chain: 6 of 8 (small, independent; needed by
investigation, #264, and experimentation, #265). Borrowed from `ex-workflow`'s "independence
is by role id" (validator, replay worker and conclusion reviewer may not have done the work),
as specification only (route B).

## The problem

The code-fix template has a reviewer unit after the implementer, but nothing checks that it
is a different role, or that it runs after the work it reviews. A plan that names the
implementer as its own reviewer validates and runs.

## Decisions

**D1 — the field.** `plan.units[].reviews`: optional array of unit ids.

**D2 — the rule, checked where the graph is read** (`shiftwork_plan`, `clock_in`,
`clock_out` on the mutated document), first fault wins:
1. a reviewed id that no unit declares: `unit <id> reviews <r>, which no unit declares`;
2. a reviewed id not in the unit's `depends_on` (a review runs after the work):
   `unit <id> reviews <r> but does not depend on it`;
3. same role: `unit <id> reviews <r> in the same role <role>; a review needs another role`.

**D3 — with `job.roles` declared**, the reviewer's model is still checked by AS-2 as today; no
model-independence rule (a different role may use the same model).

## Surfaces

Layer 2: schema. Layer 5: both `shiftwork` modules (one shared check). Docs and the code-fix
template (`tools/shiftwork/example-codefix-checkpoint.json` gains `reviews`).

## Gates

Conformance (shiftwork suite): a valid reviewer plans as before; each D2 sentence per side as
a literal, from all three entry points; a `follow_ups` (#260) reviewer is checked too.
