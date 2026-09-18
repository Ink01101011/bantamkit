# Work-plan DAG: turning `depends_on` into batches

**Date:** 2026-09-18
**Status:** design approved; implemented on the branch below (W1–W6), documented by W7
**Branch:** `docs/workplan-dag-spec` (cut from `main` at `6666d8b`). *Corrected by W7,
2026-09-19: this line and the job checkpoint's constraint both named
`worktree-exflow-agent-tools`, a branch that was never created — `git branch --list
'*exflow*'` is empty. The worktree directory is named `exflow-agent-tools`; the branch
checked out in it is not.*

## The problem, measured

`assets/schemas/shiftwork-checkpoint.json` has carried `plan.units[].depends_on`
since the contract was written. Both runtimes store it and neither reads it:

- `runtime-ts/src/shiftwork.ts:50` — "WHAT IS NOT PORTED, DELIBERATELY. The
  `depends_on` field is ignored on cursor advance (v1-linear, the Python module's
  own ruling)"
- `runtime-py/src/bantamkit/shiftwork.py:69` — "Cursor advance is v1-linear: it
  moves to the first non-terminal unit in plan order and ignores `depends_on`"

Cursor advance is `plan.cursor = remaining[0].id` in both
(`shiftwork.ts:643`, `shiftwork.py:490`). So every job this repo has ever run was
executed as a straight line, whatever its dependency graph said.

**How much that costs, measured 2026-09-18** by running a Kahn planner over
`plan.units` of all 19 checkpoints in `.shiftwork/`:

| checkpoint | units | batches | batch widths |
|---|---|---|---|
| `checkpoint-job46.json` | 32 | 5 | 11, 9, 7, 4, 1 |
| `checkpoint-job50.json` | 32 | 12 | 5,4,3,5,2,3,1,3,1,2,2,1 |
| `checkpoint-job44.json` | 21 | 5 | 12, 4, 2, 2, 1 |
| `checkpoint-job51.json` | 17 | 13 | 2,3,2,1,1,1,1,1,1,1,1,1,1 |
| `checkpoint-job43.json` | 16 | 16 | all 1 |
| `checkpoint-job45.json` | 13 | 6 | 3, 3, 3, 2, 1, 1 |
| `checkpoint-job47.json` | 10 | 5 | 2, 2, 3, 2, 1 |
| `checkpoint-job41.json` | 9 | 3 | 7, 1, 1 |
| `checkpoint-job1-archived.json` | 8 | 8 | all 1 |
| `checkpoint-job52.json` | 8 | 8 | all 1 |
| `checkpoint-job54.json` | 7 | 5 | 3, 1, 1, 1, 1 |
| `checkpoint-readlever.json` | 7 | 2 | 6, 1 |
| `checkpoint-skill-audit.json` | 7 | 7 | all 1 |
| `checkpoint-job48.json` | 6 | 5 | 1, 1, 1, 1, 2 |
| `checkpoint-job42.json` | 5 | 5 | all 1 |
| `checkpoint-job53.json` | 5 | 5 | all 1 |
| `checkpoint-job49.json` | 4 | 1 | 4 |
| `checkpoint-memory-keeper.json` | 4 | 4 | all 1 |
| `checkpoint.json` | 4 | 4 | all 1 |

**215 units collapse to 119 batches — 96 serial steps (44.7 %) are false
serialization.** 11 of 19 checkpoints have some parallelism. Zero cycles and zero
unknown dependency ids across all 19, so the `depends_on` written over a month of
real jobs is structurally sound even though nothing has ever read it.

The 11 root units of `checkpoint-job46.json` were spot-checked by hand and are
genuinely distinct subjects (roadmap row 12, the AS-6 audit, a red gate on main,
a porting-register defect, the roles map, offline install, the dream trigger, a
threshold, the event stream, discovery precision, the help output). The data is
plausible, not noise.

## Where this came from, and what is NOT being used

The user's own npm package `ex-flow@1.1.0` (MIT, Kahn's algorithm with
priority-aware batching) is what made this measurable — every number above was
produced by running it over the real checkpoints. It is **not** becoming a
dependency.

`runtime-ts/package.json` declares exactly one runtime dependency,
`@modelcontextprotocol/sdk@1.30.0`, and `docs/porting.md` (rows "pdf, doc and rtf
on Node", "bzip2 and lzma zip members on Node") uses *"no runtime dependency is
allowed into `runtime-ts`"* as the live justification for the port **refusing**
PDF, bzip2 and lzma today. Taking `ex-flow` (plus its `exsorted` dependency)
would collapse the argument holding up three divergence rows, to save roughly a
hundred lines of graph code. `runtime-py` could not import it in any case, and
CLAUDE.md's rule is that a feature lands in both runtimes or it does not land.

**So `ex-flow` is the SPECIFICATION and not the implementation.** The semantics
below are its documented defaults, written out so two hand-written
implementations can be held to them.

## Design

### Layer placement

`docs/architecture.md`: *"a change lives in exactly one layer. If a diff touches
two layers, split it."* `shiftwork.py` is Layer 5 (Composition) — "the shift-work
adapter surface". A deterministic graph planner with no I/O is Layer 1 (Core).
They cannot share a file, which is why this is several units and not one.

| piece | layer | lives in |
|---|---|---|
| planner core | 1 — Core | `runtime-py/src/bantamkit/workplan.py`, `runtime-ts/src/workplan.ts` |
| tool schemas | 2 — Contract | `assets/tools/work_plan.json`, `assets/tools/shiftwork_plan.json` |
| shiftwork adapter | 5 — Composition | `runtime-py/src/bantamkit/shiftwork.py`, `runtime-ts/src/shiftwork.ts` |
| MCP registration | 5 — Composition | `runtime-py/src/bantamkit/mcpserver.py`, `runtime-ts/src/mcp/server.ts` + `mcp/pyargs.ts` |

### 1. The core

```
plan(nodes) -> {"batches": [[id, ...], ...], "sequence": [id, ...]}

node = {"id": str, "depends_on": [str], "priority": int}   # priority defaults to 0
```

Pure function. No filesystem, no clock, no `mcp` import. Level-synchronous
Kahn: batch *k* holds every node whose dependencies all appear in batches
< *k*.

**Ordering inside a batch — priority descending, then insertion order.** These
are `ex-flow`'s defaults (`priorityAscending: false`,
`tieFallbackPolicy: "insertion"`), and insertion order means the order the nodes
were given, which for the shiftwork adapter is `plan.units` order. Determinism
here is not a nicety: it is what the conformance gate compares.

**What of `ex-flow` is deliberately left out:** `deadlineStrategy`,
`weightStrategy`, `fairnessPolicy`/`maxDeferralRounds` aging, `schedulerMode:
"throughput"`, `concurrencyCap`, `resourceCaps`, the clone modes, and the config
builder. Nothing in the 19 measured checkpoints supplies a deadline, a weight or
a resource class, so every one of them would be untested surface. `sequence` is
`ex-flow`'s `fullSequence` under a shorter name.

**Empty input is not an error.** `plan([])` is `{"batches": [], "sequence": [],
"width": 0}`. A plan with nothing left to do is the answer, not a refusal — the
same reasoning `shiftwork.clock_in` already applies when it runs its all-terminal
test before the cursor lookup so an empty plan reports success rather than
escalating on a dangling cursor (`shiftwork.ts:325`).

**Three refusals, one sentence each, identical in both runtimes.** These are
`{"result": "error", "reason": "<sentence>"}`, which is the shape
`shiftwork.py` already returns, so nothing new is invented for it. The sentences
are pinned here because CLAUDE.md treats wording as the part of a port that
carries the risk, and because the differential cannot see a change made to both
sides at once — they get per-side literal tests like the AS-2 refusals did:

| condition | sentence |
|---|---|
| the same `id` appears twice | `duplicate node id <id>` |
| a `depends_on` names an id no node declares | `node <id> depends on <dep>, which no node declares` |
| the graph has a cycle | `the graph has a cycle: <a> -> <b> -> <a>` |

The cycle sentence's path is rendered as ids joined by ` -> `, closing on the
repeated id, so a self-dependency reads `the graph has a cycle: a -> a`.

**The cycle path must be extracted deterministically**, or the two runtimes will
name two different (equally correct) cycles in the same graph and the conformance
suite will go red for a reason that is not a defect. The rule: scan the nodes
that Kahn could not emit **in input order**, walk `depends_on` **in declared
order**, and the first repeated id closes the cycle. First node scanned, first
edge walked, first repeat wins.

### 2. Surface one — `work_plan`

A general tool, not coupled to shiftwork: an agent hands it any task list and
gets back the batches it could run in parallel.

```
in : {"nodes": [{"id": "a", "depends_on": [], "priority": 0}, ...]}
out: {"result": "plan", "batches": [["a", "b"], ["c"]], "sequence": ["a","b","c"], "width": 2}
   | {"result": "error", "reason": "<one of the three sentences>"}
```

`width` is `max(len(batch))` — the widest fan-out in the plan, which is the
number an orchestrator needs to decide whether it can afford the batch.

### 3. Surface two — `shiftwork_plan`

Same shape as the existing `shiftwork.status()` (`shiftwork_status.json`):
takes a checkpoint path, reuses the existing `_read_valid()` so schema refusals
keep their current wording, and **never mutates**.

```
in : {"checkpoint": "/path/to/checkpoint.json"}
out: {"result": "plan",
      "batches":  [[...], ...],
      "ready":    [...],        # == batches[0]; dispatchable right now
      "sequence": [...],
      "width":    N,            # same meaning as work_plan's
      "cursor":   "<plan.cursor, unchanged>"}
```

- Units with status `done` or `dropped` are **satisfied**: dropped from the graph,
  and edges pointing at them are treated as already resolved.
- Units with status `todo`, `in_progress` or `blocked` stay in the graph.
- Every unit gets `priority: 0`, because the checkpoint schema has no priority
  field and **this design does not add one**. Order inside a batch is therefore
  `plan.units` order.
- `cursor` is echoed so a caller can see the single-pointer contract and the batch
  view side by side. It is read, never written.

### What does not change

`clock_in`, `clock_out`, cursor advance, the log-then-commit ordering, the
`{"result": "ok" | "escalate" | "error"}` vocabulary, the AS-2 role/model gate and
the "no lock — one orchestrator by construction" assumption are all untouched,
byte for byte. `assets/schemas/shiftwork-checkpoint.json` is not edited. Both new
surfaces are read-only, so the existing shiftwork conformance sessions — which
assert on checkpoint bytes after every call — must stay green without being
modified. That is itself a check on this claim.

## The gate

Per CLAUDE.md: *"a feature is not ported because someone wrote it twice; it is
ported when `node tools/conformance/run.mjs --all` compares the two answers and
they match. Add the case in the same change as the feature."*

**`tools/conformance/suites/workplan.mjs`** with
`tools/conformance/ref/workplan_ref.py` for the reference side. Suites are
discovered by directory listing, so no registry edit is needed.

Corpus:

1. The unit graph of every `.shiftwork/*.json` checkpoint — 19 graphs, 215 nodes,
   already proven to parse with no cycle and no dangling id. **These are read as
   a corpus of graphs, not as live files**: the graphs are extracted and written
   into the suite as literal data. `tools/conformance/suites/shiftwork.mjs`
   already documents why reading a live checkpoint from a suite is a defect — it
   mutates while a job runs, and `.gitignore` can make it absent on a runner,
   which took three suites down on CI once.
2. The three refusals, each with the id set that triggers it.
3. Priority ties, empty input, a single node, and a node depending on itself
   (which is a cycle of length one).
4. `shiftwork_plan` over `tools/shiftwork/example-codefix-checkpoint.json` — the
   tracked template, for the same reason that suite gives.

### The differential alone is not enough

`differential-is-blind-to-symmetric-regression`: the conformance harness compares
Python against Node. Two implementations that are wrong in the *same* way compare
equal and the suite is green. This repo has already lost three parity bugs to
exactly that.

So the gate has a second half: **per-side tests pinning real answers as
literals** — `runtime-py/tests/test_workplan.py` and
`runtime-ts/test/workplan.test.mjs`. `checkpoint-job46.json`'s graph must produce
batch widths `[11, 9, 7, 4, 1]` written in the test as those five numbers, not
computed at run time from the input. A planner that degenerated to one-node-per-
batch on both sides would still pass the differential; it fails this.

Teeth must be demonstrated, not asserted: land a deliberate mutation (emit nodes
in reverse input order), record which named cases go red, revert it, and record
that the suite is green. `feedback-verify-against-the-run-not-the-source` — the
evidence is the printed output of the run, not a reading of the diff.

## Risks and what is left open

**`depends_on` encodes logical order, not file contention — and this is not
hypothetical.** Nothing in the checkpoint says which files a unit writes.
Measured 2026-09-18 on `checkpoint-job44.json`, whose first batch is 12 units
wide, by extracting the source paths each unit's brief in
`.shiftwork/briefs-job44/` names:

| file | units in batch 1 naming it |
|---|---|
| `runtime-ts/src/docread.ts` | 7 — U1, U2, U8, U12, U14, U18, F1 |
| `runtime-py/src/bantamkit/docread.py` | 5 — U1, U2, U14, U18, F1 |
| `runtime-ts/src/memory/store.ts` | 3 — U2, U8, F4 |

**The graph says those 12 units may run in parallel; 7 of them would be writing
one file.** An orchestrator that dispatches a whole batch blindly produces
exactly the collision `feedback-never-mutate-a-file-a-live-unit-holds` was
written about. This design does not solve that and does not pretend to:
`shiftwork_plan` reports what the graph permits, and the orchestrator remains
responsible for what it actually dispatches — which is why both surfaces are
advisory and read-only rather than a change to cursor advance. A `writes:` field
on a unit is the obvious next step and is deliberately not in this scope.

**The dependency data has never been load-bearing.** It has been written for a
month with nothing reading it, so nobody has ever been wrong about it in a way
that cost anything. The first job planned against these batches should be treated
as the first real test of the data, not of the planner.

**No concurrency cap in v1.** The widest measured batch is 12. If an orchestrator
cannot afford that, it slices `ready` itself. A cap is a parameter both runtimes
would have to agree on and more cases to gate, for a number the caller already
knows better than the tool does.

## The plan

The implementation plan is `.shiftwork/checkpoint-workplan.json` and the eight briefs in
`.shiftwork/briefs-workplan/`, not a document under `docs/superpowers/plans/`. CLAUDE.md
requires any multi-unit job to run through the shift-work MCP tools against a schema-valid
checkpoint, so the briefs are what an executing session actually reads; a second copy of the
same steps in a plan document would be the drift this repo already has a rule against.

Eight units, cut along the layer rule — which is why the Python and Node halves of the same
surface are separate units:

| unit | role | layer | depends on |
|---|---|---|---|
| W1 core planner, runtime-py | implementer | 1 | — |
| W2 core planner, runtime-ts | implementer | 1 | — |
| W3 the two tool assets | implementer | 2 | — |
| W4 adapter + registration, runtime-py | implementer | 5 | W1, W3 |
| W5 adapter + registration, runtime-ts | implementer | 5 | W2, W3 |
| W6 the conformance suite | implementer | harness | W4, W5 |
| W7 docs | implementer | docs | W6 |
| W8 review, teeth, gates | reviewer | — | W7 |

Which is itself a five-batch plan of widths `3, 2, 1, 1, 1` — and, unlike
`checkpoint-job44`'s twelve-wide first batch, its three root units touch three disjoint
file sets (`runtime-py/`, `runtime-ts/`, `assets/`), so this one really is safe to fan out.
W1 and W2 are deliberately forbidden from reading each other: the conformance suite exists
to prove two independent implementations agreed, and that proof is worth nothing if they
were copied.

## Where this sits

`docs/roadmap-agent-stack.md` row 1 ("Agent orchestration — **HAVE**") describes
`shiftwork.py`/`shiftwork.ts` and its three served MCP tools
(`shiftwork_clock_in`, `shiftwork_clock_out`, `shiftwork_status`).
`shiftwork_plan` is a fourth on that surface and `work_plan` is a new general one
beside it. The row's verdict does not change, and updating that row belongs to
the unit that lands the tools, not to this spec.
