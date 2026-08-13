# K4B/C2 — two `--rubric` values sharing a LABEL, before and after

**Job:** `rbp31-rbp32-status-truth`, unit K4B. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure`. **Before** = `3981efd` (RB-P32 as closed by
K3). **After** = this unit's fix. **Measured:** 2026-08-13.

Re-run:

```sh
sh docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.sh "$PWD" /tmp/k4b-c2
# and for the BEFORE column:
git checkout 3981efd -- runtime-py/src/bantamkit/criticreplay.py
sh docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.sh "$PWD" /tmp/k4b-c2-before
git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
```

Statuses are `/bin/sh`'s own `$?`, with no `PYTEST_*` key in the child's environment. The
pre-fix tree was **asserted** before the before-run
(`grep -c rubric_label_collision_problem` = 0).

## What is being measured, and what RB-P32 said about it

`--rubric a=X --rubric a=Y` is decidable **from the typed strings alone**: a label is the
text left of the first `=`, so two of them collide on every machine, with no path resolved,
no file opened and no `git` run. That is RB-P32's own definition of an argument-SHAPE rule.
At `3981efd` it was nevertheless refused by `guarded_family` **inside `main`'s `try`** and
reported `1`.

It falsified three shipped sentences, verbatim:

- the module comment's `#   2` block — "since RB-P32 the answer is: **all of the
  argument-SHAPE ones and only those**";
- the same block's "A `1` is an argv that is well formed and names something **the world
  did not supply**" — here the world supplied everything;
- `docs/eval.md`'s RB-P32 amendment — "every one of them now goes through `parser.error`".

It also broke the module's own stated economy. `rubric_arg_shape_problem` rejects
`git:HEAD` on its face precisely because "letting them through would have spent a `git
show` to say so" — and `--rubric a=git:R:P --rubric a=git:R:P` spent **two** `git show`
subprocesses before anything noticed the duplicate.

## The matrix

The rig has a **real transcript cell** in it. That is not a detail: the first version of
this runner used an empty `--transcripts` directory, and every pre-fix case reported `1`
with `no transcripts with answers` on stderr — the run refused in `load_cases` and never
reached the duplicate-label rule at all. The number was right and the **attribution** was
wrong, which is the same mistake in miniature as the one C2 is about. The stderr column
below is what makes each row attributable. Cases run
`runtime-py/tests/cli_exit_status_probe.py` (the shipped `main()` with only the client
constructor replaced), because a populated rig means a case that PASSES the rule goes to
the wire, and a control whose number depends on the network is not a control.

| case | **before** | **after** | stdout B | `git show` before → after | stderr (before) |
|---|---|---|---|---|---|
| D1 two `--rubric` on disk sharing a label | **1** | **2** | 0 | 0 → 0 | `error: two variants share the label 'a' …` |
| D2 two `git:` `--rubric` sharing a label | **1** | **2** | 0 | **2 → 0** | `error: two variants share the label 'a' …` |
| D3 four `--rubric`, two labels shared | **1** | **2** | 0 | 0 → 0 | `error: two variants share the label 'a', 'b' …` |
| D4 CONTROL distinct labels, git + disk | 3 | 3 | 1015 | 1 → 1 | *(none — it ran)* |
| D5 CONTROL duplicate label, one malformed | 2 | 2 | 0 | 0 → 0 | `usage: …` |
| D6 CONTROL one `--rubric` not on disk | 1 | 1 | 0 | 0 → 0 | `error: rubric not found: …` |
| D7 CONTROL empty `--transcripts` | 1 | 1 | 0 | 0 → 0 | `error: no transcripts with answers …` |

Three cases moved `1` → `2`. Four controls did not move: a run with distinct labels still
measures and still prints its 1015-byte table, a shape error inside a duplicated pair is
still reported by the rule that owns it (D5, the precedence case), and both world-dependent
refusals keep the `1` that is correct for them. **D2's spend went from two `git show`
subprocesses to none.**

## The fix, and the argument for its shape

A new `rubric_label_collision_problem(specs)` above `main`'s `try`, reported through
`parser.error` — and **`guarded_family`'s check stays exactly where it is.**

That is not indecision. They are not the same check on the same input. An in-process caller
may pass a bare `Rubric`, whose label is its `name` and therefore came off a file on disk:
world-dependent, undecidable from any argv, and a `PerturbationError` inside the run is the
right answer for it. The argv form is decidable from the typed strings, so the CLI answers
it before it spends anything. Same verdict, two entitlements — and the module comment now
says so beside both.

Deleting the claim and leaving the behaviour was the other option and it was rejected: the
sentence "all of the argument-SHAPE ones and only those" is the whole content of RB-P32's
decision, and the case that falsified it is a case a CI job hits by copy-pasting a
`--rubric` line.

## What this measurement does NOT establish

- Nothing here says the `guarded_family` rule is *correct* for in-process callers; it says
  the CLI no longer needs it to be reached. The in-process path is covered by
  `test_two_variants_sharing_a_label_are_refused_rather_than_silently_collapsed`, which is
  an in-process node and not a field measurement.
- The `git show` count is a PATH shim's line count on this machine. It measures
  invocations, not cost.
- One platform, one Python. The suite is not evidence (RB-P28); the nodes that pin these
  cells are regression guards.
