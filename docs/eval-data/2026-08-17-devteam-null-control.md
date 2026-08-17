# The null control, measured: `graph-off` vs `bare`, outside pytest

M3 of job `devteam-workload-and-null-control`, dated **2026-08-17**.

`graph-off` already shipped, at `8ccd084`. This unit does not design it. It turns
the argument that it **preserves meaning** from prose plus two in-process tests
into a field measurement, and states what would show it false.

The bar this is graded against was committed **first**, at `51ccb69`:
[`2026-08-17-devteam-bar-preregistration.md`](2026-08-17-devteam-bar-preregistration.md).
The workload is [`2026-08-17-devteam-workload.md`](2026-08-17-devteam-workload.md).
Every table below is stdout of
[`2026-08-17-devteam-null-control-field-measurement.py`](2026-08-17-devteam-null-control-field-measurement.py).

**No arm delta is reported here, in either direction.** The one contrast this unit
measures is `bare` vs `graph-off`. Δ%(A1−A0), Δ%(A2−A1), Δ%(A3−A2) and every
`graph`-vs-anything figure belong to M4 and appear nowhere below. §6 is the fence.

Line references are verified against HEAD (`bf0ed03`), each read before it was
pinned — not shifted by arithmetic. A2 of the bar records what re-pinning by
arithmetic cost the last unit.

---

## Verdict, up front

1. **Measured, out of process, on all 8 workload tasks: `graph-off` and `bare`
   send byte-identical requests.** Not just the tool observations — the whole
   serialized request payload, the tool roster and the system prompt, on every one
   of the **44 model calls** — 106 observation slots, **59,671 observation bytes**,
   re-send weighted. 8/8 on every column ([Table A](#table-a)).
2. **The ledger is populated while they are.** 33 reads, 30 distinct, **3 realised
   repeats**, captured off the `FileAccessGraph` the harness builds and discards
   ([Table B](#table-b)). That is what `bare` cannot do and the whole reason A0
   exists.
3. **The token half of the null-control claim is now PINNED**, by route (a): a new
   node whose red depends on the token quantity. The falsifying mutation was run
   three ways and the failing line is the token assertion itself
   ([§4](#4-the-unpinned-token-half-which-route-and-the-mutation)). Bar §9/A1's
   finding about the old node reproduces unchanged.
4. **The refutation condition for the null control is written as a condition and
   each observable was checked.** Six hold under measurement; **two are explicitly
   UNCHECKED** and named, not glossed ([§5](#5-r-nc--what-would-show-the-null-control-is-not-meaning-preserving)).
5. **A finding for M3.5, from A0's own ledger: at the verified reference walk,
   6 of the 8 tasks realise ZERO repeat reads.** Under bar §5 R3 those six tasks
   are **UNINFORMATIVE**, not refutations. The ledger that says so is reachable
   today only by wrapping the constructor from outside
   ([§7](#7-findings-handed-forward-to-m35)).

---

## 1. What makes this a field measurement rather than a test

RB-P28 is **OPEN**. Job 11's C1 measured the failure mode directly: all three
acceptance pins had run in-process, and a patch keyed on `pytest in sys.modules`
printed an affirmatively false report under a fully green suite. So the evidence
here is a standalone program, and the suite is the regression guard.

**The invocation:**

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py .
```

**The entry point:** `bantamkit.evalrun.run_task` — the same function
`evalrun.main` calls once per (task, config, repeat), reached through the same
`evalrun.load_tasks` the `--tasks` flag uses (`evalrun.py:736-738`). The program:

- runs in a **fresh interpreter**, imports nothing from `runtime-py/tests`,
  defines no fixture and declares no node;
- **asserts `pytest not in sys.modules`** and prints the result as the first line
  of its report — it exits `2` if pytest is present, so the C1 patch could not
  make this file lie;
- **exits non-zero** when any check fails, so a red run cannot be read as a pass.

Report header, as printed:

```
==============================================================================
FIELD MEASUREMENT — the `graph-off` null control vs `bare`, outside pytest
==============================================================================
pytest in sys.modules: False   (must be False)
entry point:           bantamkit.evalrun.run_task  (…/runtime-py/src/bantamkit/evalrun.py)
tasks loaded via:      evalrun.load_tasks(assets/evals/devteam/tasks)  n=8
client:                walk-client/deterministic (scripted; usage = ceil(payload bytes/4))
arms:                  bare vs graph-off
graph-off flags:       {'annotate': False, 'cache': False, 'query': False}
graph-off is calibration-only: in CONFIG_CHOICES=True, in CONFIGS=False
```

### 1.1 The client, and exactly what it can and cannot make real

The model client is a **deterministic scripted walker**, `WalkClient` — the same
device M1 and M2 used, and no model is called. It replays the manifest's verified
reference walk, using the *identical* rule
`2026-08-17-devteam-workload-measurements.py:154-164` states: one `list_files`
first iff the prompt names it or a hop reads its pointer out of the listing, then
one `read_file` per hop in order. So this run walks the trajectory Table 3
verified and Table 5 priced.

| quantity | real here? | why |
|---|---|---|
| observation bytes | **yes** | produced by the harness's own `read_file` over the committed surface |
| tool roster | **yes** | the `Tool` list the agent actually passes to `chat` |
| system prompt | **yes** | `Agent.run` puts it in the message list (`agent.py:175-176`) |
| serialized request payload | **yes** | built exactly as `OpenAICompatible.chat` does (`client.py:155-161`) |
| score | **yes** | `score_output`'s real `json_equal` verdict (`evalrun.py:233-247`) |
| read ledger | **yes** | the real `FileAccessGraph` instance `run_task` constructs (`evalrun.py:537`) |
| **tokens** | **NO — a surrogate** | `ceil(bytes/4)` over that payload. No endpoint was called; `Usage` normally comes from the server |
| **trajectory** | **NO — held fixed** | a scripted walk, not a model's choice |

**The token figures are a payload-derived surrogate and are labelled as one every
time they appear.** The assumption is the one Table 5b already states and this doc
inherits rather than re-argues: **tokens monotone in bytes.** What the surrogate
buys is the property `conftest.FakeClient`'s fixed `Usage` lacks — it is a
*function of the observations*, so it moves when they move. That is what makes
§4's mutation a pin rather than a gesture.

---

## 2. Table A — byte identity across all 8 workload tasks

<a id="table-a"></a>

```
==============================================================================
TABLE A — byte identity, all 8 workload tasks (bare vs graph-off)
==============================================================================
task                     calls  obs  obs B  obs=  payload=  roster=  system=  marker?
-------------------------------------------------------------------------------------
dt-error-contract            6   15   6207   yes       yes      yes      yes     none
dt-handler-map               5   10   3696   yes       yes      yes      yes     none
dt-patch-before-after        4    6   5366   yes       yes      yes      yes     none
dt-retry-attempts            5   10   5045   yes       yes      yes      yes     none
dt-settlement-config         7   21  14187   yes       yes      yes      yes     none
dt-symbol-home               5   10   5335   yes       yes      yes      yes     none
dt-trace-blame               4    6   4818   yes       yes      yes      yes     none
dt-unread-key                8   28  15017   yes       yes      yes      yes     none
-------------------------------------------------------------------------------------
TOTAL                       44  106  59671   8/8       8/8      8/8      8/8      8/8
```

**As numbers: 8/8 tasks, 44/44 model calls, 106/106 observation slots, 59,671
observation bytes, zero differing bytes.**

The counting rule matters, so it is stated rather than left to be inferred. The
transcript is re-sent whole on every call, so one file read appears in every
later request. `obs` therefore counts **observation slots** — each observation
once per request it is re-sent in — and `obs B` is those slots' bytes, re-send
weighted, the same weighting Table 5b uses. Underneath the 106 slots are **36
distinct tool observations** (44 calls minus the 8 answer turns), of which 33 are
`read_file` results and 3 are `list_files` listings. Every slot in every request
of both arms was compared; the comparison is over positions, so a *reordering*
would fail it too.

Four things are compared, and the fourth subsumes the first three:

- **`obs=`** — the `role: tool` contents, position by position.
- **`roster=`** — the tool names in the request. `file_graph` appears in neither
  arm (`filegraph.py:51-52` registers it only when `query` is True).
- **`system=`** — the system message. The `file-graph` skill is absent from both
  (`filegraph.py:53`, same guard).
- **`payload=`** — the whole `json.dumps` of the request. This is the strong form:
  anything `graph-off` added anywhere in the request would show here even if the
  three columns above had missed it.

`marker?` reports **`none`**: the string `[file-graph]` occurs nowhere in
`graph-off`'s observations — including on `dt-error-contract` and
`dt-settlement-config`, the two tasks that *do* re-read a hub file, where the
collapse and the annotation both have something to act on.

---

## 3. Table B — score, tokens, and the ledger that is kept

<a id="table-b"></a>

```
==============================================================================
TABLE B — score and tokens at a fixed trajectory, and the ledger that is kept
==============================================================================
task                     passed b/o  tok bare  tok off  Δtok  reads distinct repeats
------------------------------------------------------------------------------------
dt-error-contract               1/1      4255     4255     0      5        4       1
dt-handler-map                  1/1      2743     2743     0      4        4       0
dt-patch-before-after           1/1      2717     2717     0      3        3       0
dt-retry-attempts               1/1      2950     2950     0      3        3       0
dt-settlement-config            1/1      6861     6861     0      6        4       2
dt-symbol-home                  1/1      3046     3046     0      3        3       0
dt-trace-blame                  1/1      2568     2568     0      3        3       0
dt-unread-key                   1/1      7296     7296     0      6        6       0
------------------------------------------------------------------------------------
WORKLOAD                        8/8     32436    32436     0     33       30       3
```

**Score: 8/8 in both arms, identical task by task.** At a trajectory held fixed
this is the strongest form of §4's non-inferiority precondition — `delta_passed`
is 0 and there are no disagreeing points, because the two arms answered from
identical bytes.

**Tokens: Δ = 0 on every task and 0 workload-wide, on the surrogate counter.**
32,436 in both arms. Not an endpoint measurement — see §1.1 — and **not a ladder
delta of any kind**.

**The ledger: 33 reads, 30 distinct, 3 realised repeats.** Two notes it would be
dishonest to leave out:

- **This is not independent confirmation of Table 4.** Table 4 derived 33 reads
  and 3 repeats from the walks; this run *executes* those same walks, so agreeing
  to the read is a check that the harness realises what the walk declares — not
  evidence about what a model would do. Table 4 remains an **upper bound**, and
  M4 still has to measure the realised count under a real trajectory.
- **The numbers are reachable only because the script wrapped the constructor.**
  `run_task` never returns the graph and `save()` (`filegraph.py:102`) is never
  called by the harness — bar §7.2. The capture is a subclass whose `__init__`
  appends `self` to a list and returns; it adds no counter, no `TaskResult` field
  and no JSONL column, and the field script verifies the capture pass is
  byte-identical to the measured run before it reads the ledger. **This is not
  M3.5's accounting grain and does not substitute for it** — see §6 and §7.

---

## 4. The unpinned token half: which route, and the mutation

Bar **§9/A1** recorded, by measurement rather than assertion, that `8ccd084`'s
commit body named two pinning nodes and only one was a pin:
`::test_graph_off_token_count_matches_bare` cannot fail on a token difference
because `conftest.FakeClient` returns a fixed `Usage`. The brief for this unit
offered three routes to close it. **Route taken: (a) — a node whose red actually
depends on the quantity**, with route (c)'s caveat stated rather than skipped.

**The node:**
`runtime-py/tests/test_evalrun.py::test_graph_off_token_count_is_pinned_by_a_payload_sensitive_client`,
added at `bf0ed03`. It runs `bare` and `graph-off` against
`_PayloadSensitiveClient`, whose `prompt_tokens` is `ceil(bytes/4)` over the
payload `OpenAICompatible.chat` serializes (`client.py:155-161`) — so
`TaskResult.tokens` (`evalrun.py:586`) becomes a function of the observations, the
tool roster and the system prompt.

**It asserts the instrument before it asserts the claim** (RB-P14 Gate 2: an
acceptance criterion tests the instrument, it does not assert a fact about the
world). The per-call token figures must be all-distinct and strictly increasing;
a client that stopped responding to its payload therefore fails the node instead
of quietly making it vacuous — which is exactly how the old node became inert.

**The mutation, run three ways.** Each flag in `GRAPH_CONFIGS["graph-off"]`
(`evalrun.py:142`) was flipped `True` **in the source file**, the three named
nodes were run, and the file was restored with `git checkout --`:

| mutation | `…observations_are_identical_to_bare` | `…token_count_matches_bare` | **`…is_pinned_by_a_payload_sensitive_client`** |
|---|---|---|---|
| `cache: True` | **RED** | green | **RED** |
| `annotate: True` | **RED** | green | **RED** |
| `query: True` | **RED** | green | **RED** |

The failing line under all three is `assert off_result.tokens ==
bare_result.tokens` — verified by reading the pytest assertion output, not
inferred. The red is on the token quantity, not on a collateral assertion in the
same node.

**The same three mutations were also run through the field measurement**, which is
where the pin actually counts, via `--mutate {cache,annotate,query}`:

| mutation | field exit | tasks failing | which observables broke |
|---|---|---|---|
| `cache: True` | **1** | 2/8 | observations, payload, marker, **tokens** |
| `annotate: True` | **1** | 2/8 | observations, payload, marker, **tokens** |
| `query: True` | **1** | 8/8 | payload, roster, system prompt, **tokens** |

Two shapes worth naming. `cache` and `annotate` break only the **2 tasks that
re-read a hub file** — the other six have no repeat for either to act on, which is
Table 4's 2/8 showing up as the mutation's own blast radius. `query` breaks all
**8**, because it adds a tool and a skill to every request regardless of whether
any file is read twice.

**What is still NOT pinned, stated plainly (route (c)'s residue).** No node and no
run in this repo pins the token half against a **real endpoint's `Usage`**. Both
the node and the field program use a byte-derived surrogate. Closing that needs
what the repo does not have: a live endpoint in the measurement path, or a local
tokenizer. Until then the token equality is pinned *under the assumption tokens
are monotone in bytes*, and **that caveat travels with the number.**

**`pins` is author-chosen.** The observables in §5 are the ones this author
thought of. A meaning-preserving failure nobody listed is not excluded by 8/8 on a
list, and that caveat travels with the number too.

---

## 5. R-NC — what would show the null control is NOT meaning-preserving

Written as a condition, not a reassurance. The standing invariant is the user's
own ratified rule: **a mechanism-off arm that also removes information the task
needs measures the information, not the mechanism.** So the condition names
observables, and every one of them was checked or is marked unchecked.

> **R-NC: `graph-off` is NOT a meaning-preserving null control if, on any workload
> task at a fixed trajectory, ANY of the following differs from `bare` — the tool
> observations byte-for-byte; the serialized request payload; the tool roster; the
> system prompt; the score; or the token count on a counter that responds to the
> payload. Any single one of the six refutes it. It is not a matter of degree.**

| # | observable | status | evidence |
|---|---|---|---|
| **O1** | a byte difference in any tool observation | **HOLDS** | Table A `obs=` 8/8, 106/106 observation slots, 59,671 B |
| **O2** | a changed tool roster (`file_graph` appearing) | **HOLDS** | Table A `roster=` 8/8; guard at `filegraph.py:51-52` |
| **O3** | a skill that still loads (system prompt grows) | **HOLDS** | Table A `system=` 8/8; guard at `filegraph.py:53` |
| **O4** | a `[file-graph]` marker reaching the model | **HOLDS** | Table A `marker?` = `none`, 8/8, including both re-read tasks |
| **O5** | a scoring difference at a fixed trajectory | **HOLDS** | Table B `passed` 8/8 vs 8/8, task by task |
| **O6** | any difference anywhere in the request payload | **HOLDS** | Table A `payload=` 8/8 over all 44 calls — the strong form of O1-O3 |
| **O7** | a token difference on a payload-responsive counter | **HOLDS, under one assumption** | Table B Δtok = 0 on all 8; surrogate counter, tokens-monotone-in-bytes (§1.1) |
| **U1** | a difference in an endpoint's **real** `Usage` | **UNCHECKED** | No endpoint was called and the repo has no local tokenizer. Not checkable with the client that exists |
| **U2** | a **trajectory** divergence caused by attaching the ledger | **UNCHECKED** | The scripted walker fixes the trajectory by construction. O1-O6 make a *causal* divergence impossible — identical request bytes cannot produce a different next action from a deterministic decoder — but a sampling model could still diverge, and that is not excluded here |

**U2 deserves its own sentence, because it is the honest limit of the whole
design.** This measurement shows that at a fixed trajectory the two arms are
indistinguishable to the model. It does not show that a real model's trajectory
under `graph-off` matches its trajectory under `bare`; it shows there is nothing
in the request for a divergence to be *caused by*. That is the same assumption
Table 5b names as "trajectory held fixed", and it is why bar §5 R2 exists as an
empirical check.

**Not part of R-NC, on purpose:** the ledger's *contents*. A wrong count would be
an accounting defect (M3.5), not a meaning-preservation defect — `graph-off`
changes nothing the model sees whether the ledger is right or wrong. §7 records
one such defect rather than folding it in here.

---

## 6. Scope fence — what this unit did not measure, and would not

- **No ladder delta.** Δ%(A1−A0), Δ%(A2−A1), Δ%(A3−A2) and every `graph`-vs-
  anything comparison are **M4's**, and no number here is one. The `Δtok` column
  of Table B is `bare` minus `graph-off` — the null control against itself — and
  it reads 0.
- **The mutation deltas in §4 are not savings.** The field run under
  `--mutate cache` prints a non-zero workload token difference. **That figure is
  not `cache`'s effect and must not be read as one**, for three independent
  reasons: `graph-off` + `cache` is not the `graph-cache` arm (which also has
  `annotate: True`); the counter is a byte surrogate, not endpoint `Usage`; and
  the trajectory is scripted. It is reported for one purpose only — to show the
  pinned quantity *moved*, which is what makes O7 a pin. It is deliberately not
  tabulated as a magnitude in this doc.
- **No accounting column.** Bar §8's seven columns are **M3.5's**. Nothing here
  adds a field to `TaskResult`, a column to a JSONL row or a counter to
  `FileAccessGraph`. The field script reads the ledger through an
  observation-only subclass in its own process, and the harness at HEAD still
  discards it — which is the point of §7.
- **No frozen asset touched.** `assets/evals/tasks/` and
  `assets/evals/perturbations/` are read-only and were not read for this unit at
  all; `tools/devteam/build_tasks.py check` reports OK, so
  `assets/evals/devteam/` is unchanged.
- **No committed evidence regenerated or retro-edited.** The bar gains one dated
  amendment, **A3**, appended to §9; nothing above it is edited, including the
  stale `evalrun.py:418` in L70 that A2 deliberately left standing.
  `git diff --numstat` for this unit reads **62 / 0** on the bar — 0 deletions —
  and the workload doc is **not touched at all**: its Table 4 figures are
  reproduced by this run rather than corrected by it, and §4's "M3 is unblocked"
  paragraph still reads true.

---

## 7. Findings handed forward to M3.5

Three, all measured or read at HEAD, none of them acted on here.

### 7.1 At the reference walk, 6 of 8 tasks are UNINFORMATIVE under bar §5 R3

Table B's `repeats` column reads **0 on six tasks**. Bar §5 R3: *a task whose
realised repeat-read count under A0 is 0 is UNINFORMATIVE — its Δ% neither refutes
nor confirms, because the mechanism had no opportunity to act.* So on the
reference trajectory the informative subset of this workload is
**`dt-error-contract` (1 repeat) and `dt-settlement-config` (2 repeats)**, and the
other six contribute nothing either way.

This is what A0 was built to be able to say, and it is the first time the ledger
has actually been read to say it. It also sharpens M4's problem: a suite-wide
Δ%(A2−A1) averaged over 8 tasks is 6 tasks of structural zero diluting 2 tasks of
signal, and the bar's unit of record is the suite. **That is a question for M4's
brief, not a number for this doc.**

### 7.2 The ledger cannot be read from a run — only from inside the process

`FileAccessGraph.reads` holds the count (`FileRead.count`, `filegraph.py:20`), and
`run_task` builds the graph at `evalrun.py:537` and never returns it. There is no
CLI flag, no JSONL column and no `save()` call anywhere in the harness
(`filegraph.py:102` is dead from the harness's point of view). The consequence
measured here: **this field program could only get the numbers in Table B by
subclassing `FileAccessGraph` and monkey-patching the name in the `evalrun`
module.** A measurement that needs to patch the module it measures is exactly the
instrument gap bar §8.1 argued was load-bearing, and the patch is not a substitute
for the column: it cannot be done from the `--tasks`/`--json` CLI path at all, so
no committed JSONL can carry the number.

### 7.3 The ledger silently omits failed reads — a fidelity limit on the COUNT

`_wrap`'s handler returns early, **without recording**, when the observation starts
with `error:` (`filegraph.py:66-67`) — the harness-wide failure convention that
`Agent._dispatch` also emits, and the same string `_workspace_tools`' `read_file`
returns for an unknown path (`evalrun.py:98-99`). So `reader_calls` and
`repeat_reader_calls` as bar §8 columns 1-2 would count **successful** reads only,
and a run that repeatedly asks for a path that does not exist records zero reads
while making many. It changes nothing about meaning preservation — `graph-off`
returns the observation unmodified on that path too — but it is a real caveat on
the denominator M3.5 is being asked to build.

**Not measured here.** No task in this workload reads a nonexistent path, so this
is read off the source with pins, not demonstrated by a run. Marked UNCHECKED
rather than reported as measured.

---

## 8. Things that do not reproduce

Reported per the standing duty. M1 overturned four things and M2 overturned the
checkpoint's own artifact note; both times the job got better. This unit found
**one precision defect and no substantive contradiction** — which is itself worth
stating plainly, because "everything reproduced" is the answer a unit gives when
it did not check.

| Claim | Status | Evidence |
|---|---|---|
| Bar §1.1 and `8ccd084`'s commit body: "`_record` returns the observation unmodified on **every path** when `cache` and `annotate` are both False (`filegraph.py:83-92`)." | **The claim REPRODUCES; the pin is IMPRECISE.** There are **three** return paths that hand back an unmodified observation, and the cited range contains only one of them: the `error:` early return at **`filegraph.py:66-67`** (before `_record` is even called), the first-read return at **`filegraph.py:75-77`**, and the both-flags-off return at **`filegraph.py:92`**. `83-92` covers the repeat-read paths only. The substantive claim is unaffected and is now measured directly — Table A, 106/106 observations identical — but a reader following the pin to justify "every path" lands on two thirds of it. The honest range is **`filegraph.py:61-92`**, the whole of `handler` plus `_record`. | `filegraph.py:66-67`, `75-77`, `92`, each read at HEAD `bf0ed03`. |
| Bar §9/A1: the two falsifying mutations turn `::test_graph_off_observations_are_identical_to_bare` red and leave `::test_graph_off_token_count_matches_bare` green. | **REPRODUCES exactly, and extends.** A1 ran two mutations (`cache`, `query`); this unit ran **three**, adding `annotate: True`, which A1 did not test. Same split on all three: observations red, token count green. A1's conclusion holds and is now measured on the full flag set. | §4's mutation table. |
| The brief: "`bare` was ALREADY a clean rung zero … `graph-annotate`'s `effective` resolves to itself (`evalrun.py:432`)"; "`graph-off` is calibration-only: in `CONFIG_CHOICES`, not in `CONFIGS`"; "`setup` registers no tool and adds no skill when `query` is False (`filegraph.py:51-53`)". | **ALL REPRODUCE.** `evalrun.py:432` is `effective = GUARD_CONFIGS.get(config, BUDGET_CONFIGS.get(config, config))`, HEAD-exact. The calibration-only status is printed by the field program (`CONFIG_CHOICES=True, CONFIGS=False`). The `query` guard is measured, not just read: Table A's `roster=` and `system=` columns are 8/8. | Field program header; `evalrun.py:432`; `filegraph.py:51-53`. |
| Bar §8 column 1-2's implied denominator, "`reader_calls` … per run". | **INCOMPLETE as specified**, see §7.3: it would count successful reads only. Not a contradiction of the bar — the column does not exist yet — but the spec as written would produce a denominator that silently drops failed reads. | `filegraph.py:66-67`; `evalrun.py:98-99`. |

---

## Reproduction

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py .
                                                        # exit 0 — the measurement
.venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py . --mutate cache
.venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py . --mutate annotate
.venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py . --mutate query
                                                        # exit 1 each — the pin
.venv/bin/python -m pytest runtime-py/tests -q           # 808 passed, 2 xfailed
.venv/bin/ruff check runtime-py tools/pinharness tools/devteam   # All checks passed!
.venv/bin/python tools/devteam/build_tasks.py check      # OK — 8 task(s) match the manifest
```

`--mutate` patches `evalrun.GRAPH_CONFIGS["graph-off"]` in the field program's own
process, so the mutation is reproducible without editing a file. §4's pytest
column was produced the other way — by editing `evalrun.py:142` in place and
restoring it with `git checkout --` — because a node has to be run against the
mutated source to be a pin.

Frozen assets untouched. No committed evidence file regenerated or retro-edited.
**Tokens and wall-clock for this unit: UNMEASURED** — no counter is exposed for
either, and a self-estimate is not a measurement.
