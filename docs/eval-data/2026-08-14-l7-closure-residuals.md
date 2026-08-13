# L7 closure — the residuals this job measured and did not fix

**Measured 2026-08-14 (L7).** Runner:
`docs/eval-data/2026-08-14-l7-closure-residuals.sh`, re-runnable:

```sh
sh docs/eval-data/2026-08-14-l7-closure-residuals.sh "$PWD"
```

Layer: Measurement. RB-P28 is **open**, so a green suite is not the evidence for
anything here. Cases A and B run outside pytest with no `PYTEST_*` key in the
child's environment; case C uses the suite the only way a suite may be used as
evidence — as the thing a mutation is supposed to turn red, with the count of
**survivors** as the measurement.

Run at `6b22889`, on this machine (CPython 3.12.13, APFS/Darwin 25.5.0).

---

## A — RB-P17's residual: the `derive:` form resolves against the **process CWD**

`parse_rubric_arg`'s docstring says a reader "who has ONLY this repository and one
row can recover the exact bytes the critic read … **No argv, no machine, no
`/private/tmp`**". Measured, that sentence is **stronger than the code**: the
reader also has to be *standing in the repo root*, and nothing in the record says
so.

| case | cwd | spec | result |
|---|---|---|---|
| A1 | repo root | `derive:assets/evals/perturbations/task-completion.yaml:W1-trailing-newline:git:d2f78b7:assets/rubrics/task-completion.yaml` | **RESOLVED** `d1f32ad2947b…` |
| A2 | `/` | *the identical string* | **RAISED** `PerturbationError: perturbation manifest not found: assets/evals/perturbations/task-completion.yaml` |
| A3 | repo root | `git:d2f78b7:assets/rubrics/task-completion.yaml` | **RESOLVED** `e018854368c1…` |
| A4 | `/` | *the identical string* | **RAISED** `PerturbationError: cannot read git:d2f78b7:… : 'git show …' returned non-zero exit status 128` |

**Wider than L5 filed it.** L5's M3 named the manifest segment. A3/A4 show the
**base** segment has the same property for the same reason: `_git_show` shells out
to `git show` in the process CWD, so a `git:` ref is resolvable only from inside a
checkout of this repository. Both segments are repo-*relative* strings resolved
against something that is not the repo.

**C3's `_repo_relative` fix did NOT close this, and was never going to.**
`_not_repo_relative` is an argument-**shape** rule — a function of the typed string
and of nothing else, which is what entitles it to report `USAGE_EXIT` above `main`'s
`try` (RB-P32). It refuses `~`, an absolute path, and a `..` that walks out. It does
not resolve a path and it does not open a file, so it cannot bear on where a
relative path is resolved **from**. The two are complementary and the second is
missing.

**Attack.** Resolve both segments against a discovered repository root rather than
the CWD — `assets_root()` already does exactly this discovery for the asset pack,
env override first and packaged/parents fallback after — and pin it with a node that
calls the resolver from a CWD **outside** the tree. That node is the one thing the
present suite cannot contain: every existing pin runs with the repo as CWD, so the
CWD dependence is invisible to all of them. Until that lands, the docstring sentence
above is the overclaim and this record is the measurement it should be read against.

## B — L5's M1, **fixed** by this unit: the RB-P18 reader in the published surface

| ref | `__all__` | `payload_shas_recorded` present |
|---|---|---|
| `6c27ebe` (L6's HEAD) | 43 entries | **False** |
| `6b22889` (this unit) | 44 entries | **True** |

`docs/eval.md` presents `payload_shas_recorded` as what RB-P18 ships for a reader
who has the JSONL and **not** this tree. That reader is out-of-tree by construction,
so the export list is the only surface they have, and the function was not on it.
`guard_table` has carried `assert "guard_table" in criticreplay.__all__` since it
shipped, on exactly this argument. Ledger `N14`, added in the same commit as the fix.

## C — RB-P34, **new and not fixed**: the contract's status VALUES are not pinned

`GUARD_VIOLATION_EXIT` `3` → `7`, applied to the **real** tree (L6's hazard: a
scratch copy of `runtime-py/src` is invisible to the `OUTSIDE_pytest` nodes, because
`_child_env` hardcodes `PYTHONPATH` to the repo's `src`), anchor asserted to occur
exactly once, restored by an explicit sha with `git diff HEAD --exit-code` asserted.

| step | result |
|---|---|
| C0 baseline | `800 passed, 2 xfailed` |
| C1 `3 → 7` | `2 failed, **798 passed**, 2 xfailed` |
| C2 killers | `test_OUTSIDE_pytest_a_fresh_runs_verdict_carries_its_effect_size`, `test_OUTSIDE_pytest_a_fresh_runs_rubric_ref_resolves_from_this_repo` |
| C3 restore | tree byte-exact at `6b22889` |

**798 of 800 nodes do not notice that the contract's number changed.** The mechanism
is not an oversight in any one node: every node that tests exit status **names the
constant**, so the mutation moves the code and the expectation together and the
assertion is as true afterwards as before. The only two that notice were written for
a different purpose — L6's `OUTSIDE_pytest` probes, which read `$?` off a real child
and happen to assert a literal `3`.

Filed as **RB-P34**. See `docs/eval.md` for the attack direction.

## D — the ledger and its calibration at this unit's HEAD

Not part of the runner above: it applies 35 mutations and runs the suite after each,
so it is minutes, not seconds. Run separately, at `6b22889`:

```sh
.venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/contract-ledger.json --out /tmp/ledger.md
.venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/calibration-head.json
```

Baseline `800 passed, 2 xfailed`. **PINNED 35 · UNPINNED 0 · FALSE-PINNED 0 ·
BROKEN 0** — behaviour 30/30, prose 5/5. `N14` reads PINNED at **1/1** named
killers: the mutation that deletes its export line turns exactly one node red, and
that node is the one the claim names.

Calibration at HEAD, which is what licenses reading any of the above:
`CAL-HEAD-RED` **PINNED** and `CAL-HEAD-GREEN` **UNPINNED**, both known answers,
both returned. An instrument with only a positive control cannot distinguish
"everything is pinned" from "the detector is stuck on".

**`of which NAMED` re-reproduces at this HEAD, unchanged from L6's sweep:**

| claim | named / total killers |
|---|---|
| `N01` | 1 / 8 |
| `N02` | 1 / 3 |
| `N03` | 1 / 4 |
| `B10` | 1 / 6 |

**The denominator grew by one because a defect was fixed, not because the counter
got looser.** `34/34` at `8cd6078` stands exactly as L6 measured it and is not
restated by this sweep; the caveat that travels with it — `pins` is author-chosen,
and `B16` is a documented instance of the discipline being applied after the
measurement — travels with `35/35` unchanged, because nothing here changed how
`pins` is chosen.

**Also measured, and filed as a loophole rather than reported as a feature:** of the
**67** pins across the 35 claims, exactly **one** is a family PREFIX —
`B01`'s `test_closed_pipe_`, which `assert_pins_exist` matches with `pin in node`
and which covers **5** nodes. Deliberate where the family is one claim; a loophole
where it is not.

## E — RB-P35, added after the first CI run of this branch

The PR's first CI run failed on **both** 3.11 and 3.12, on a node that had nothing
to do with this job's levers:

```
FAILED test_help_with_no_reader_on_stdout_is_still_the_interpreters_number
E  assert 0 == 120
```

`--help` with no reader on stdout was asserted to exit `120`, in the node and in
two shipped sentences (the `--help` epilog and the module comment). **No behaviour
of this module changed.** What changed is the size of the help text, measured here:

| ref | `--help` bytes | `ubuntu-latest` | macOS |
|---|---|---|---|
| `b496856` (v0.20.0, CI green) | **7488** | `120` | — |
| `6c27ebe` (L6's HEAD) | **8227** | — | `120` |
| `837527b` (this branch, first CI run) | **8227** | **`0`** | `120` |

```sh
git worktree add -q --detach /tmp/wt b496856 && \
  PYTHONPATH=/tmp/wt/runtime-py/src BANTAMKIT_ASSETS=/tmp/wt/assets \
  .venv/bin/python -m bantamkit.criticreplay --help | wc -c
```

The growth is **docstrings**, added by this job's own RB-P16/17/18 fixes. The
status turns on whether the doomed bytes are still in `sys.stdout`'s
`BufferedWriter` when the interpreter exits — the same buffer-size mechanism the
module's own comment already spells out for the run path, never applied to itself.
macOS reads `120` at both sizes, which is why five units and every local suite run
missed it, and why the CI matrix is the instrument that found it.

**Re-aimed, not re-scoped.** The node now asserts that the module's status equals
what a **bare interpreter writing the identical help bytes to the identical broken
pipe** reads — argparse formats the whole help and emits it in a single
`file.write`, so the control is byte-for-byte and write-for-write the same thing
with `bantamkit` off the path. Measured on macOS at 8459 bytes (the corrected
epilog): module `120`, control `120`. The equality is platform-independent, cannot
go stale with the epilog's length, and still goes red the moment this module starts
choosing that status — which is the change the contract sentence promises to be
corrected for.

Filed as **RB-P35** in `docs/eval.md`, including the two halves that are **not**
fixed: the twin stderr node still asserts a literal `120` and is green for the same
accidental reason, and the corrected sentence is prose, so reversing it turns no
node red.
