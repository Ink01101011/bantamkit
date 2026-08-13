# Every committed runner in this job, re-run at the commit the PR ships

**Job:** `rbp31-rbp32-status-truth`, unit K5. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure` at `d1951bb`.
**Measured:** 2026-08-13. **Machine:** Darwin 25.5.0, APFS, CPython 3.12.13 from `.venv`.

## Why this file exists

K2 measured RB-P31 at `1c73b94`, K3 measured RB-P32 at `3981efd`, K4B measured C1 and C2
at `b0d4cce`. **None of them measured the tree this PR ships**, and each later unit
changed the same function. A closure that cites a matrix taken three commits ago is a
claim about a tree nobody is merging, so every runner was re-run here, unchanged, at the
commit the PR points at. RB-P28 is open: the suite is a regression guard for these
numbers, never the evidence for them, and every status below is `/bin/sh`'s own `$?` in
an environment built with `env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION`.

## The four runners, and what they read at `d1951bb`

```sh
sh docs/eval-data/2026-08-13-rbp31-render-failure-matrix.sh      "$PWD" /tmp/k5-rbp31
sh docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.sh    "$PWD" /tmp/k5-c1
sh docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.sh "$PWD" /tmp/k5-rbp32
sh docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.sh    "$PWD" /tmp/k5-c2
```

| runner | cells | what it read at `d1951bb` | matches the committed record |
|---|---|---|---|
| RB-P31 render-failure matrix | 45 | 27 render-failure cells (`ebadf-file`, `ebadf-devnull`, `closed` × 3 sizes × 3 earned) all **`5`**; 9 `epipe` cells still **`0`/`3`/`4`**; 9 `live` cells still `0`/`3`/`4` | yes |
| K4B/C1 codec matrix | 18 | 12 `latin-1`/`ascii` cells **`5`** with 0 stdout bytes, no traceback, the report ASCII as written; 6 `utf-8` controls still `3`/`0`/`4` | yes |
| RB-P32 argument matrix | 23 | **15 → `2`**, **8 → `1`**, and **0 of 23 wrote a single byte to stdout** | yes |
| K4B/C2 duplicate label | 7 | D1–D3 **`2`** with **0 `git show` subprocesses**; D4 control still `3` with 1015 stdout bytes; D5 `2`, D6 `1`, D7 `1` | yes |

Byte identity, from the RB-P31 runner's own `cmp` columns: `jsonl_identical` is `yes` in
**all 45** cells and `summary_identical` is `yes` (or `both-absent`, where the rig makes
the `--summary` directory unwritable on purpose) in **all 45**. A run whose report was
never rendered leaves the same artifacts as the same argv with a live reader — which is
the sentence the `5` block makes, measured rather than asserted.

The fifth runner, `2026-08-13-rbp33-fd1-after-main.sh`, is new in this unit and is the
in-process half; its own record is `2026-08-13-rbp33-fd1-after-main.md`.

## What this does not settle

- **It is a reconfirmation, not an independent measurement.** Same runners, same machine,
  same shell. It rules out "the later commits moved a number the earlier units measured";
  it adds no platform and no second observer.
- **ENOSPC is still absent from every cell above.** macOS has no `/dev/full`; the class is
  handled in the arm and simulated in-process, and no full device was measured here.
- One platform, one filesystem, one CPython.
