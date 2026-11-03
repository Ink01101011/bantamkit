# Shift-work investigation flavor: hypotheses first, a replay by another role before a conclusion

Date: 2026-11-03. Status: implemented (#264, job76); open decisions settled below. Chain: 7 of 8
(needs unit results #259, follow-ups #260, review independence #263). Borrowed from
`ex-workflow/investigation`, as specification only (route B).

## The problem

The bugfix and code-trace jobs this repo runs are investigations, and the user's standing
rules for them are evidence rules: real probes only, prove a case red before claiming it
guards, recall before declaring a target refuted. None of them is checked; a job can conclude
"root cause found" on one run nobody repeated.

## Decisions

**D1 — the kind.** `job.kind: "investigation"` (absent = today's job). With it:
`job.question` (string), `job.hypotheses: [{id, claim, falsified_by}]`, at least two, or one
with `job.single_hypothesis_rationale`.

**D2 — runs are units.** A run unit declares `tests: [hypothesis ids]` and `procedure` (a
command or a brief path). Its clock-out must report `produced` (#259) with at least one
`{kind: "run-output"}` item, or it is refused:
`run <id> produced no run-output; record what it observed`.

**D3 — replay.** A unit with `replay_of: <run id>` must have a different role from that run
(#263 rule, reused) and the same `procedure`.

**D4 — conclusion.** `job.conclusion: {outcome: "resolved"|"inconclusive"|"stopped",
supported?, evidence: [refs]}` is set only through `clock_out` of a unit with
`concludes: true`. `resolved` is refused unless the supported hypothesis has a `done` run and
a `done` replay of it, and a reviewing unit (#263) in another role is `done`.
`inconclusive` and `stopped` are first-class: never refused.

**Open decisions (to settle before implementing):** whether `procedure` is compared as text
or by hash of the command; whether a refuted hypothesis needs a replay too; the exact
sentences for D4.

**Settled (user ruling 2026-11-03, job76):** `procedure` is compared as exact text; a
refuted hypothesis needs no replay (only `supported` is checked); the D4 sentences are
the orchestrator's and are pinned in the shiftwork conformance suite — listed in
`docs/shiftwork.md`, *Investigation flavor*.

## Surfaces

Layer 2: schema. Layer 5: both `shiftwork` modules. Docs; a second template
(`tools/shiftwork/example-investigation-checkpoint.json`).

## Gates

Conformance (shiftwork suite): a full resolved run; each refusal per side as a literal; an
`inconclusive` conclusion with no replay is accepted.
