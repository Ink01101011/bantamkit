# Shift-work experimentation flavor: compare candidates in isolated worktrees, validate the exact SHA

Date: 2026-11-03. Status: proposed, design-level (open decisions marked). Chain: 8 of 8
(needs touches #257, budget #262, review independence #263). Borrowed from
`ex-workflow/experimentation`, as specification only (route B).

## The problem

When two approaches are both plausible, a job picks one by argument. Running both in parallel
needs isolated workspaces (worktrees, which have their own traps:), a frozen harness, validation by someone other
than the author at the exact commit submitted, and a deterministic pick. None of that is
recorded or checked today.

## Decisions

**D1 — the kind.** `job.kind: "experimentation"` with `job.experiment: {objective,
direction: "minimize"|"maximize", base_sha, harness, concurrency_cap, candidate_budget}`.
`base_sha` and `harness` are frozen: a clock-out that changes them is refused.

**D2 — candidates are units** with `candidate: {workspace, author_role}`. `touches` (#257)
does not apply between candidates (each has its own worktree); `concurrency_cap` bounds how
many are in flight, as `ready` does today.

**D3 — submit.** A candidate's clock-out reports `produced` items
`{kind: "commit", ref: <full sha>}` and `{kind: "score", ref: <number>}`; both required.

**D4 — validate.** A validation unit `reviews` (#263) one candidate, in another role, and
reports `{kind: "validated-sha", ref}` equal to the submitted sha, else refused.

**D5 — compare.** `shiftwork_plan` reports `ranking` over validated candidates: score in
`direction`, then candidate id. The pick is the ranking's first; none validated = no winner.

**D6 — budget.** `candidate_budget` applies per candidate through #262's accounting.

**Open decisions:** who creates and removes worktrees (the orchestrator, recorded, as
`ex-workflow` does — proposed); whether integration and its re-validation are units of this
job or a follow-up job.

## Surfaces

Layer 1: ranking (pure). Layer 2: schema. Layer 5: both `shiftwork` modules. Docs; a template.

## Gates

Conformance (shiftwork suite): ranking order and ties; each refusal per side as a literal; a
run with no validated candidate reports no winner.
