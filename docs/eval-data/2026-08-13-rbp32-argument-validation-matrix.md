# RB-P32 — every argument validation, and the number a real shell reads

**Job:** `rbp31-status-on-render-failure`, unit K1. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure` off `5538624` (main, v0.19.0).
**Measured:** 2026-08-13. **K1 decides nothing here.** RB-P32 has two admissible attacks
and **K3 picks one**; this file is the enumeration K3 picks from.

Re-run:

```sh
sh docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.sh "$PWD" /tmp/rbp32
```

Statuses are `/bin/sh`'s own `$?`, with `env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION`.
No probe and no scripted critic is involved: not one case here reaches a client, so this
is the shipped `python -m bantamkit.criticreplay` end to end. Every case wrote **0 bytes
to stdout** and left no artifact.

## 1. The matrix

`--base-url http://x --model m --transcripts <empty dir>` are present in every case
except where the case is about their absence.

### A. argparse's own parsing — 8 cases, all `2`

| case | argv fragment | `$?` | stderr |
|---|---|---|---|
| A1 | `--not-a-flag` | **2** | `usage: ...` |
| A2 | required `--base-url` omitted | **2** | `usage: ...` |
| A3 | required `--rubric` omitted | **2** | `usage: ...` |
| A4 | `--replays abc` (`type=int`) | **2** | `usage: ...` |
| A5 | `--timeout abc` (`type=float`) | **2** | `usage: ...` |
| A6 | `--identity-replays abc` | **2** | `usage: ...` |
| A7 | `--guard nope` (`choices=`) | **2** | `usage: ...` |
| A8 | `--model` with no value | **2** | `usage: ...` |

### B. this module's own validation, via `parser.error` — 3 cases, all `2`

There is exactly **one** `parser.error` call site in the module, `criticreplay.py:1897`,
and it guards two flags:

```python
args = parser.parse_args(argv)
if args.replays < 1 or args.identity_replays < 1:
    parser.error("--replays and --identity-replays must be >= 1")
```

| case | argv fragment | `$?` | stderr |
|---|---|---|---|
| B1 | `--replays 0` | **2** | `usage: ...` + `--replays and --identity-replays must be >= 1` |
| B2 | `--replays -3` | **2** | same |
| B3 | `--identity-replays 0` | **2** | same |

### C. this module's own validation, inside `main`'s `try` — 12 cases, all `1`

| case | argv fragment | `$?` | raised by | stderr's first line |
|---|---|---|---|---|
| C1 | `--rubric <spec, no LABEL=>` | **1** | `parse_rubric_arg` :735 | `error: --rubric wants LABEL=SPEC, got '...'` |
| C2 | `--rubric =<spec>` | **1** | `parse_rubric_arg` :735 | same |
| C3 | `--rubric a=` | **1** | `parse_rubric_arg` :735 | `error: --rubric wants LABEL=SPEC, got 'a='` |
| C4 | `--rubric a=git:HEAD` | **1** | *nothing* — see §3 | `Traceback (most recent call last):` |
| C5 | `--rubric a=<missing file>` | **1** | `parse_rubric_arg` :743 | `error: rubric not found: ...` |
| C6 | `--rubric a=<not a rubric>` | **1** | `_parse_rubric` :770 | `error: ... is not a rubric: ...` |
| C7 | `--rubric a=<no {task}/{output}>` | **1** | `_parse_rubric` :773 | `error: ... prompt missing placeholder(s): ...` |
| C8 | `--rubric a=git:<bad ref>:x` | **1** | `_git_show` :757 | `error: cannot read git:...` |
| C9 | `--manifest <missing>` | **1** | `load_manifest` :418 | `error: perturbation manifest not found: ...` |
| C10 | `--transcripts <missing dir>` | **1** | `main` :1905 | `error: no transcripts with answers in ...` |
| C11 | `--transcripts <empty dir>` | **1** | `main` :1905 | same |
| C12 | `--task <no such task>` | **1** | `main` :1905 | same |

**Counts.** `2`: **11** measured cases, from **1** module call site plus argparse's own
structure (`required=`, `type=`, `choices=`, unknown/valueless flags). `1`: **12**
measured cases, from **8** distinct `raise PerturbationError` sites reachable before any
request (`:735 :743 :757 :770 :773`, `load_manifest` `:414 :418 :424 :439`, `main :1905`)
plus one site that raises nothing at all (§3).

## 2. Where the line actually falls — recorded, not decided

Split the same cases by whether the string the user typed is malformed **on its face**,
with no path resolved and no file opened. That is the "pure command-line syntax error"
RB-P32 is about:

| pure typo — nothing on disk consulted | `$?` | reached via |
|---|---|---|
| `--replays 0` | **2** | `parser.error` |
| `--identity-replays 0` | **2** | `parser.error` |
| `--guard nope`, `--replays abc`, `--timeout abc` | **2** | argparse |
| `--rubric <spec, no LABEL=>` | **1** | `PerturbationError` |
| `--rubric =<spec>` | **1** | `PerturbationError` |
| `--rubric a=` | **1** | `PerturbationError` |
| `--rubric a=git:HEAD` | **1** | uncaught `ValueError` |

**Three candidate principles, and what the data does to each.** Stated so K3 can reject
them on evidence rather than on taste; K1 asserts none of them.

* *"`2` is argparse's, `1` is ours."* True by construction and therefore says nothing:
  `--replays 0` is this module's own rule and it is `2`, so the line is not ownership.
* *"`2` is decided before parsing finishes, `1` after."* False. The `parser.error` call
  is **after** `parse_args` returns (`:1896-1897`), one statement above the `try` whose
  handler produces every `1`. Both families run after argparse has finished.
* *"`1` is for things that need the world, `2` for things that do not."* False in one
  direction and vacuous in the other: `--rubric /tmp/x.yaml` consults nothing and is `1`,
  and no case that needs the filesystem is `2`.

What is left is the observation the brief asked for and stops at: **the split follows
exactly which function the author reached for.** `parser.error` above the `try` is `2`;
`raise PerturbationError` inside it is `1`; and the `try` opens on the line after the
`parser.error` call. Whether that is the right line is K3's call.

## 3. Two things the filing does not mention

**(a) `--rubric a=git:HEAD` is not a `BantamError` at all.** The git form is split with
`_, ref, path = spec.split(":", 2)` (`:737`), so a `git:` spec with fewer than three
segments raises an uncaught `ValueError` and the user gets a raw traceback:

```
File ".../criticreplay.py", line 737, in parse_rubric_arg
    _, ref, path = spec.split(":", 2)
ValueError: not enough values to unpack (expected 3, got 2)
```

It exits `1` — but that `1` is the interpreter's status for an uncaught exception, not
`REFUSAL_EXIT`. Two different meanings arriving at the same number, and the only way to
tell them apart from a CI job is that one prints `error: ...` and the other prints
`Traceback`. Any route that makes argument-shape errors consistent has to pass through
this line too.

**(b) `1` here is not the `1` the contract describes.** The module comment says a `1`
"does NOT promise that nothing was written ... treat any artifact from a 1 as partial."
Every case in §1.C wrote **nothing**: 0 bytes on stdout, no JSONL, no summary. So the
same number covers "your typo, nothing happened" and "the run died on request 40 of 80
with 39 rows on disk", and the contract's own advice for `1` — *check the artifacts* —
is the only way to tell.

## 4. The disagreement, quoted

The two committed statements about what `2` covers, verbatim.

**The `--help` epilog** (`_EXIT_CONTRACT`, `criticreplay.py:1819`), user-visible:

> `2  usage error (argparse's number, including this module's own validations)`

**The module comment** (`criticreplay.py:170-174`):

> `2  usage error. Not this module's to choose: it is argparse's, and it is recorded`
> `here as a MEASURED number (--not-a-flag exits 2), pinned from a shell by`
> `test_argparses_usage_status_is_measured_not_assumed, so that the statuses this`
> `module does choose cannot silently collide with it. argparse also owns this`
> `module's own parser.error validations (--replays 0 exits 2, measured).`

The epilog claims "this module's own validations" **without qualification**. The comment
claims only "this module's own **`parser.error`** validations". The measured behaviour
matches the comment: 12 of this module's own validations exit `1`, and 3 exit `2`.

The epilog is the sentence a user reads. It is the one that is wrong.

## 5. What the executable spec pins, and what it does not

`runtime-py/tests/test_criticreplay.py`, two non-strict `xfail` nodes:

* `test_every_argument_shape_error_reports_the_same_number` — runs seven pure typos from
  a real shell and asserts `len(set(statuses)) == 1`. Today: `{1, 2}`. It asserts nothing
  about **which** number, and each case also asserts 0 bytes on stdout.
* `test_the_epilog_and_the_module_comment_agree_about_what_the_usage_status_covers` —
  extracts the `2` line from `_EXIT_CONTRACT` and the `#   2` block from the module
  source and fails while the epilog makes the unqualified claim **and** the comment
  restricts it to `parser.error`. Goes green under RB-P32's preferred attack (route
  everything through `parser.error`; the comment's qualifier stops being a restriction
  and comes out) **and** under its alternative (narrow the epilog; the unqualified claim
  disappears). It is a consistency pin, not a choice.

Neither node pins a number, and neither pins §3(a) — a fix that makes every shape error
report one status while `git:HEAD` still prints a traceback would pass the first node
only if that traceback's `1` happened to be the chosen number. §3(a) is recorded here as
a finding for K3, not as a spec clause.
