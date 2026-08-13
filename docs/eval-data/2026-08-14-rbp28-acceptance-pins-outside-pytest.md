# RB-P28 — the three acceptance pins never left the pytest process

**Measured 2026-08-14 (L6).** Runner:
`docs/eval-data/2026-08-14-rbp28-fix-nothing-patch.py`, committed beside this file.
Layer: Measurement.

**This is not a suite result. It is a measurement of what the suite is worth**
about the three claims this job closed — RB-P16, RB-P17 and RB-P18 — and the
answer before `1ef62dc` was: nothing.

## The attack

One patch, three edits to `criticreplay.py`, each reverting one acceptance to its
pre-fix behaviour **unless `pytest` is in `sys.modules`**:

| # | claim | edit |
|---|---|---|
| 0 | RB-P16 | `_effect` returns a CONSTANT — valid shape, no crash, content stops varying |
| 1 | RB-P17 | `parse_rubric_arg` records the bare commit again, not the whole spec |
| 2 | RB-P18 | the canonical payload column stops being canonical (`sort_keys` off) |

It fixes nothing. Every pin ran the shipped code **in-process under pytest**, so
this one tell reached all three at once and `_child_env`'s scrub never ran —
no child was ever started for it to scrub.

## Result

| tree | suite | field: the three `effect:` lines a real shell printed |
|---|---|---|
| `5f75267` (L5's HEAD), patched | **792 passed, 2 xfailed — rc 0** | `d= 0/11`, `d= 0/11`, `d= 0/11`; `0/11 points disagree` on all three |
| `5f75267`, unpatched (field) | — | `d= 0/11`, `d=-1/11`, `d=-2/11`; `4`, `7`, `4` of 11 points disagree |
| `1ef62dc` (this fix), patched | **3 failed**, 792 passed, 2 xfailed — rc 1 | unchanged: the patch still lies to the field |

Both field runs exit 3 from `/bin/sh`'s own `$?`, with every `PYTEST_*` key
stripped from the child's environment.

**That is not a no-op — it is an affirmatively false report with a green suite.**
The two variants genuinely disagree on 4, 7 and 4 of 11 points on those three
cells; the patched tree reports `neither leads` and `0/11 points disagree` on
all three, and no node in 794 objects.

It is also worse than job 10's residual, where at least one signal had to cross
into a child process to be believed. Here nothing had to.

## The three nodes that now kill it, and each kills only its own

Re-run of the same patch at `1ef62dc`, one edit at a time:

| edit | nodes red | which |
|---|---|---|
| 0 alone (RB-P16) | 1 | `test_OUTSIDE_pytest_a_fresh_runs_verdict_carries_its_effect_size` |
| 1 alone (RB-P17) | 1 | `test_OUTSIDE_pytest_a_fresh_runs_rubric_ref_resolves_from_this_repo` |
| 2 alone (RB-P18) | 1 | `test_OUTSIDE_pytest_a_fresh_run_reproduces_both_frozen_payload_recipes` |
| all three | 3 | the three above, and nothing else |

Each pin is aimed at its own claim: no node catches a revert it is not about, and
no revert escapes. The 792 in-process nodes are unmoved by any of them, which is
the finding restated as an inventory.

## What this does NOT close

RB-P28 stays **OPEN**. The class is "the code under test can see it is being
observed", and only one signal is closed here. A patch can still key on the
probe's `sys.argv[0]`, on the scripted critic's presence, on a `tmp_path`-shaped
argument, or on the absence of a TTY — exactly as `_child_env`'s docstring has
said since 2026-08-13. What is closed is the specific hole this job had: **one
in-process tell reaching every acceptance at once.**

The remaining attack direction, filed rather than fixed: the probes are started
with an argv that names a file called `..._probe.py` under a pytest tmp
directory. A patch keying on either is unaffected by anything here. Closing that
needs the probe's inputs and invocation to be indistinguishable from a
production run, which is a rig this job did not build.

## Hazards checked, because a run that failed looks like a run that measured

- `git worktree` does **not** isolate this suite (`bantamkit` is installed
  editable against the main repo). `PYTHONPATH` pinned to the worktree's `src`;
  the resolved module `__file__` printed and asserted to be inside the worktree.
- Every anchor asserted to appear **exactly once**, and the resolved module text
  asserted equal to the mutated text byte for byte.
- `BANTAMKIT_ASSETS` set, stderr printed rather than dropped. The orchestrator
  hit the other way on 2026-08-14: a copied tree with no `assets/` died at exit 1
  with stderr redirected to `/dev/null`, and the empty output read as a *stronger*
  result than the real one.
