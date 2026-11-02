# Shift-work `touches`: one batch never holds two units that write the same file

Date: 2026-11-03. Status: proposed. Chain: 1 of 8 (first: nothing before it). Borrowed from: `ex-flow`'s resource caps and
`ex-workflow`'s Kanban `skipped` (reason `resource-cap`), as specification only — route B
stands (no runtime dependency; both runtimes hand-write it; conformance proves they agree).

## The problem, measured

`workplan.plan` batches units by `depends_on` alone. `depends_on` is logical order, not file
contention, so a wide batch routinely hands two parallel units the same file. That is how a
sibling's commit swallowed another unit's staged hunks (the shared git index race), and why
job44's 12-wide first batch had 7 units naming `runtime-ts/src/docread.ts`.

Prep probe (2026-11-03, every `.shiftwork/*.json` in this repo, batched by `workplan.plan`
itself, a unit's files = tracked paths under `runtime-py/src`, `runtime-ts/src`, `tools/`,
`assets/` that its brief names):

| | |
|---|---|
| checkpoints / units | 36 / 425 |
| batches (dependency graph only) | 244 (181 serial steps saved over a straight line) |
| batches wider than 1 | 77 |
| of those, two units naming one file | **22 (29 %)**, in 11 of 36 checkpoints |
| serial steps a one-writer-per-file rule adds | **37** (244 → 281) |
| width kept | 144 of 181 saved steps (**80 %**) |

Bounds on the estimate: 40 of 425 briefs are gone from disk (undercount); a brief that names
a file it only reads is counted as a writer (overcount). This is why the field below is
declared by the planner and never inferred from brief text.

## Decisions

**D1 — the field.** `plan.units[].touches`: optional array of repo-relative POSIX paths the
unit will WRITE. Absent or `[]` means "claims nothing", so every existing checkpoint plans
exactly as before. Schema: optional; items are strings. No globs, no directories in v1 — a
path is compared as an exact string.

**D2 — the rule lives in Layer 1.** `plan(nodes)` takes an optional `touches` per node. The
level sweep is unchanged; inside one level, nodes are admitted in the existing contract order
(priority descending, then insertion order), and a node whose `touches` intersects a node
already admitted to THIS batch is held for the next batch instead (it is still ready; it is
not reordered against its own dependents, which wait on it as before). The rule is greedy and
order-driven, so both runtimes produce the same batches by construction. `batches`,
`sequence`, `width` and, in the adapter, `ready` all follow from it — so `clock_in(unit_id)`'s
existing readiness test and `clock_out`'s `ready[0]` cursor advance pick the rule up with no
change of their own.

**D3 — the answer says why.** When any node declares `touches`, the answer carries
`held: [{"id", "batch", "by", "path"}]` — the unit, the batch it was held out of, the unit
that holds the file there, and the first shared path in that unit's `touches` order. When no
node declares `touches`, the key is absent, so today's answers stay byte-identical.

**D4 — in flight.** The planner sees the checkpoint, not the briefs. A unit briefed and not
yet clocked out stays in the graph (it is not `done`), so it claims its files in batch 0 like
any other — but only if it sorts first. Order alone cannot promise that, so `clock_in` gets
one new refusal, checked after readiness: a unit whose `touches` intersects a unit briefed
since its own last clock-out (the set job60 already measures off `<checkpoint>.log.jsonl`)
is refused, before any brief is issued:

    unit <id> touches <path>, which <other> holds until its clock-out

Same sentence, same refusal shape, both runtimes.

**D5 — shape refusals.** `touches` that is not a list of strings, or holds a path that is
empty, absolute (`/` or a drive letter), contains `\`, or has a `.`/`..`/empty segment, is
refused by the existing shape check, in the existing check order (shape first):

    node <id> touches <repr>, which is not a plain relative path

`work_plan` refuses it as a node shape; `shiftwork_plan` and `clock_in` refuse the checkpoint
through the schema/shape path they already use.

**D6 — out of scope.** Inferring `touches` from briefs or diffs; read locks; globs; a
per-batch width cap; priorities in the schema. `shiftwork_draft` (#226) may fill `touches`
later — that is its job, not this one.

## Surfaces (each lands in BOTH runtimes, same job)

| Layer | Python | Node | What |
|---|---|---|---|
| 1 | `workplan.py` | `workplan.ts` | `touches` on nodes, D2 hold rule, D3 `held`, D5 refusal |
| 2 | `assets/schemas/shiftwork-checkpoint.json`, `assets/tools/work_plan.json`, `assets/tools/shiftwork_plan.json` | (shared assets) | optional field; tool descriptions name `touches` and `held` |
| 5 | `shiftwork.py` | `shiftwork.ts` | pass `touches` through; D4 clock-in refusal |
| docs | `docs/shiftwork.md` batch view + Spending the width | | |

## Gates

Conformance (`node tools/conformance/run.mjs --all`), new cases in the workplan and
shiftwork suites, each proven RED against the pre-change side before it is claimed:

1. no node declares `touches` → answers byte-identical to today (no `held` key);
2. two ready units sharing one path → second held to the next batch, `held` names both and
   the path; a third unit with a disjoint path stays in batch 0;
3. priority decides which of two contenders stays (higher priority keeps the batch);
4. a held unit's dependents still wait for it (batch index shifts by one);
5. each D5 refusal, per side, as a literal sentence;
6. `clock_in(unit_id)` on a unit contending with an in-flight one → D4 sentence, checkpoint
   and log byte-unchanged; after the holder clocks out the same call briefs;
7. literals per side for 2, 5 and 6, since a differential stays green when both sides
   regress together.

Plus pytest and `npm test` for the Layer-1 cases, and the prep probe re-run as
`tools/eval/` script reporting the table above from the repo's own checkpoints.

## Not changed

`depends_on` semantics, cursor storage, clock-out acceptance (job60), the accounting log, the
`job.roles` check, every existing refusal sentence.
