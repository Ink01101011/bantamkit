# RB-P17 — whether a run's recorded provenance resolves, before and after

**Job:** `rbp16-rbp17-rbp18-evidence-grading`, unit L3. **Layer:** Measurement.
**Tree:** `feat/rbp16-inconclusive-effect-size`. **Before** = `32773f9` (L2's last commit,
RB-P17 untouched). **After** = `fccc637` (this unit's fix), **re-measured at `0337c66`**
(the exit-contract disclosure, which touches prose only) and identical row for row.
**Measured:** 2026-08-14.

Re-run:

```sh
sh docs/eval-data/2026-08-14-rbp17-provenance-resolution.sh "$PWD" /tmp/rbp17
# and for the BEFORE column:
git checkout 32773f9 -- runtime-py/src/bantamkit/criticreplay.py
sh docs/eval-data/2026-08-14-rbp17-provenance-resolution.sh "$PWD" /tmp/rbp17-before
git checkout fccc637 -- runtime-py/src/bantamkit/criticreplay.py   # by SHA, not HEAD
```

Statuses are `/bin/sh`'s own `$?`, with no `PYTEST_*` key in the child's environment. The
pre-fix tree was **asserted** before the before-run (`grep -c 'derive:'` = **0**,
`grep -c 'rubric_template_sha256'` = **0**, `grep -c 'source = ref'` = **1**), and the
restore was asserted afterwards to be byte-exact (`git diff HEAD --exit-code` clean).
RB-P28 is open and its residual has been demonstrated twice, so **the suite is not the
evidence for this claim** — the nodes in `test_criticreplay.py` are regression guards and
this file is the measurement.

## The fact the whole fix rests on, re-derived

Printed by the runner itself, from `git show` and the frozen manifest, on every
invocation — so it is a command in the record and not a number quoted into it:

```
A-asfiled   file sha256   = 55f700e09bab
A-asfiled   template      = e018854368c1   manifest base_sha256 = e018854368c1
minus one trailing \n     = d1f32ad2947b   manifest base_sha256 = d1f32ad2947b   (B-nonewline)
W1 applicable to A        = True -> d1f32ad2947b
W1 applicable to B        = False   (its own fixed point: the rule names no variant here)
```

So `B-nonewline` **is** `A-asfiled`'s rubric minus one trailing newline, that edit **is**
the frozen manifest's `W1-trailing-newline`, and the manifest already records both
results. The `derive:` form does not invent a recipe; it makes the committed one
executable. Identical in both columns — it reads `assets/` and `git`, not the module.

`file sha256` (`55f700e09bab`) and `template` (`e018854368c1`) being different values for
one file is the second defect in one line: the column a row carried was the left one, and
the question provenance answers is the right one.

## What is being measured, and how the checker stays independent

The runner runs the shipped `main()` in a real process
(`runtime-py/tests/rbp16_effect_probe.py` — L2's harness reused unchanged: the CLI with
only the client constructor replaced, by a critic scoring `sha256(prompt|seed) % 11`).
The variants are the two the committed acceptance run used; `assets/` is not touched.

**The checker never imports `bantamkit`.** It takes each `rubric_ref` the run recorded and
tries to recover the rubric from this repository: `git show` for a `git:` spec, and for a
`derive:` spec it reads the manifest as YAML and re-implements the declared `op` from the
manifest's own words. Then it hashes what it recovered and compares against the
`rubric_template_sha256` the run recorded. `resolved` is a comparison between two
derivations; asking the module to resolve a ref the module wrote would be the run agreeing
with itself.

## The matrix

| case | status before | status after | variants | `resolved` | `names_rubric` | recorded `rubric_ref` |
|---|---|---|---|---|---|---|
| E1 `git:` + `derive:` | 1 | **3** | 0 → 2 | **0/0 → 2/2** | **0/0 → 2/2** | `git:d2f78b7:…`, `derive:assets/…` |
| E2 `derive:` alone | 1 | **3** | 0 → 1 | **0/0 → 1/1** | **0/0 → 1/1** | `derive:assets/…` |
| B0 CONTROL materialized file | 3 | 3 | 2 → 2 | **0/2 → 1/2** | **0/2 → 2/2** | `git:d2f78b7:…`, `/tmp/…/b-nonewline.yaml` |
| C1 CONTROL derive-of-a-derive | 1 | **2** | 0 → 0 | — | — | refused |
| C2 CONTROL rule not in manifest | 1 | 1 | 0 → 0 | — | — | refused |

Three cases change number: `E1` and `E2` because before the fix the argv could not run at
all, and `C1` because a derive of a derive is now wrong on its face rather than a path
that is not there. The `rubric_ref` column is the AFTER value; the BEFORE values are in
the `B0` row's discussion below, and for `E1`/`E2` there was no run to record one.

`resolved = n/m`: of the `m` variants the run recorded, `n` have a `rubric_ref` that this
repository can turn back into exactly the rubric the row says was read.
`names_rubric = n/m`: how many rows can state *which rubric* at all, as distinct from
which file.

### Reading the rows

**E1, E2 — the null control now has a form.** Before, `--rubric B-nonewline=derive:…` was
not a spec: the string fell through to the path branch and the run died with
`rubric not found: derive:assets/evals/p…` and status **1**, having spent nothing. After,
both runs complete (status 3 is the earned exit for a run whose comparison is
`distinguishable`, not an error) and **every** recorded ref resolves.

**B0 is the control that proves the checker can say no**, and it is the committed record's
own shape: the null control materialized to a loose file, exactly as
`2026-08-11-pb14-…-summary.json` and `2026-08-12-pb14-…-replay3-summary.json` recorded it.
It stays **1/2** after the fix and that is correct — a loose path is still a loose path,
and a checker that resolved it would be measuring nothing. What *did* move in B0 is the
`git:` half and the `names_rubric` column:

- Before, `A-asfiled`'s ref was recorded as `d2f78b7` — a bare commit. `git show d2f78b7`
  is not a file, so the row named no rubric and resolved to nothing: **0/2**.
- After, it is `git:d2f78b7:assets/rubrics/task-completion.yaml` and resolves: **1/2**.
- `names_rubric` goes **0/2 → 2/2** in the same row: even the unresolvable scratchpad
  variant can now state *which rubric* was read (`d1f32ad2947b…`), which is what makes two
  runs on the same rubric comparable without either being resolvable.

**C1 changes status, not verdict, and the change is the point.** A derive-of-a-derive is
wrong on every machine, so after the fix it is refused by `rubric_arg_shape_problem` above
`main`'s `try` — **status 2**, `USAGE_EXIT`, no `git show` spent (RB-P32's rule). Before it
was a **1** for an unrelated reason (the whole string looked like a missing path). This is
also what makes the load order acyclic: the cycle is unrepresentable rather than detected.

**C2 stays 1, and must.** "`W9-nope` is not a point in
`assets/evals/perturbations/task-completion.yaml`" needs the manifest read to know, so it
is a `REFUSAL_EXIT` inside `main`'s `try` — the same argv works on a machine whose
manifest has that point.

## Contract-claim pinning, measured not cited

`.venv/bin/python tools/pinharness/pinned.py . <ref> <ledger>`, both ends re-measured
rather than one cited:

| | ref | ledger | behaviour | prose | overall |
|---|---|---|---|---|---|
| BEFORE | `32773f9` | that commit's 27-claim ledger | PIN_B_BEHAVIOUR | PIN_B_PROSE | **PIN_B_OVERALL** |
| AFTER | `fccc637` | this commit's 29-claim ledger | PIN_A_BEHAVIOUR | PIN_A_PROSE | **PIN_A_OVERALL** |

PIN_NARRATIVE

## What did not close, in the terms it was filed in

**L1's `xfail` did not go green, and it cannot.**
`test_every_rubric_ref_in_a_committed_summary_resolves_from_this_repo` reads committed
summaries. Committed evidence is never regenerated, so the four unresolvable refs
(`/private/tmp/…/b-nonewline.yaml`, `/private/tmp/…/n5-b-nonewline.yaml`, `d2f78b7`,
`e57f1a6`) are frozen into the record, and only a retro-edit could clear them. That node
therefore measures the **history**: it can go neither red nor green under any change to
this module, so it pins nothing in either direction — the same structural finding L1 made
about `N02`, holding after the fix as well as before it. It stays `xfail`, permanently,
with a dated note saying so.

**The committed rows keep their scratchpad paths.** Nothing here rewrites them. What a
reader gains is that the recipe is now executable rather than prose: the manifest's
`base_sha256` for `B-nonewline` equals the template sha of
`derive:assets/evals/perturbations/task-completion.yaml:W1-trailing-newline:git:d2f78b7:assets/rubrics/task-completion.yaml`,
verified in the block at the top of this file. **Attack:** write a *new* summary beside
the old ones, from a re-run of the acceptance cells under the `derive:` spec, so the
record holds at least one artifact whose every `rubric_ref` resolves. That needs the qwen
arms, which this unit was told not to re-run.

**RB-P17's filing states a fact that is still false.** "A session temp path **that no
longer exists**" — re-measured 2026-08-14, both scratchpad rubrics still exist on this
machine and still hash to their recorded `rubric_sha256` (`59b0fe81ecf3…` and
`29f299707fd6…`). The claim shipped here needs no such fact: a scratchpad path is
unresolvable on any other machine *today*, which the B0 control measures directly.
