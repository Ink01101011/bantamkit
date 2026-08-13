# RB-P17's own defect, inside the fix that closes RB-P17

**Measured 2026-08-14 (L6).** Runner:
`docs/eval-data/2026-08-14-rbp17-provenance-resolution-v2.sh`, a **successor**
beside the v1 runner, which stays exactly as it was because it produced a
committed record. Layer: Measurement.

RB-P28 is open, so the suite is not the evidence for this: statuses below are
`/bin/sh`'s own `$?` with no `PYTEST_*` key in the child's environment, and the
checker imports `json`, `hashlib`, `subprocess` and `yaml` and never imports
`bantamkit`.

## What was wrong

The `derive:` form is `derive:<manifest-path>:<rule-id>:git:<ref>:<path>`. Its
**base** segment was refused a working-tree path from the day it shipped, with an
explicit argument: a derived variant has no file of its own, so nothing but the
immutability of every segment makes its record resolvable.

**The manifest segment got no such rule.** Three consequences, all measured:

1. `derive:/private/tmp/<session>/scratchpad/m.yaml:W1-trailing-newline:git:…`
   was **accepted** and recorded verbatim in `rubric_ref`, with
   `rubric_sha256` empty — the exact absolute-scratchpad shape RB-P17 was filed
   about, one segment over.
2. The manifest is a **working-tree** file and nothing recorded its bytes, so the
   same recorded ref could resolve to a different rubric silently.
3. **Both resolvers had the same hole they were checking for.** `repo / ref`
   refused an absolute path in its last branch and nowhere else, and
   `Path(repo) / "/private/tmp/x"` is `/private/tmp/x` — pathlib drops the left
   side — so the fresh-run pin and the committed field checker both read the
   scratchpad file off this machine and called the ref **resolved**.

## Before / after, same runner, same cases

| case | status | variants | resolved | names_rubric | names_manifest | recorded `rubric_ref` |
|---|---|---|---|---|---|---|
| **BEFORE** (`3070d9c`) | | | | | | |
| E1-git-and-derive | 3 | 2 | 2/2 | 2/2 | **0** | `git:d2f78b7:…` , `derive:assets/…` |
| E2-derive-alone | 3 | 1 | 1/1 | 1/1 | **0** | `derive:assets/…` |
| B0-CONTROL-materialized-file | 3 | 2 | 1/2 | 2/2 | 0 | `git:…` , `/private/tmp/…/b-nonewline.yaml` |
| C1-CONTROL-derive-of-a-derive | 2 | 0 | – | – | 0 | refused on its face |
| C2-CONTROL-rule-not-in-manifest | 1 | 0 | – | – | 0 | refused |
| **D1-absolute-manifest-segment** | **3** | **2** | 1/2 | 2/2 | 0 | **`derive:/private/tmp/…/outside-manifest.yaml:…`** |
| **AFTER** (this fix) | | | | | | |
| E1-git-and-derive | 3 | 2 | 2/2 | 2/2 | **1** | unchanged |
| E2-derive-alone | 3 | 1 | 1/1 | 1/1 | **1** | unchanged |
| B0-CONTROL-materialized-file | 3 | 2 | 1/2 | 2/2 | 0 | unchanged — the control still says no |
| C1-CONTROL-derive-of-a-derive | 2 | 0 | – | – | 0 | unchanged |
| C2-CONTROL-rule-not-in-manifest | 1 | 0 | – | – | 0 | unchanged |
| **D1-absolute-manifest-segment** | **2** | **0** | – | – | 0 | **refused, zero spend** |

D1 moves from `3` (a run happened, and its record points at this machine) to `2`
(the argv can never work on any machine, no run attempted). The manifest file
under `$WORK` **exists** and is a byte copy of the frozen manifest, so the
refusal is about the FORM of the string and not the state of the disk — which is
what entitles it to be a shape rule and report `2` at all (RB-P32).

Neither E1 nor E2 nor any control moved. The fix is additive.

## The substitution, executed

One recorded ref, two manifests at one repo-relative path, in a throwaway git
repo so this one's tree is untouched:

| manifest | rubric template sha | `derive_manifest_sha256` | recorded ref |
|---|---|---|---|
| **before** | | | |
| `m-strip` | `d1f32ad2947b` | – | `derive:m.yaml:W1-trailing-newline:git:HEAD:r.yaml` |
| `m-append` | `447e5be27613` | – | *the same string, byte for byte* |
| **after** | | | |
| `m-strip` | `d1f32ad2947b` | `340ce4dbf1c9` | `derive:m.yaml:W1-trailing-newline:git:HEAD:r.yaml` |
| `m-append` | `447e5be27613` | `b42d9cece6f2` | *the same string, byte for byte* |

`d1f32ad2947b → 447e5be27613` reproduces L5's measurement exactly. Before the
fix the two runs are **indistinguishable in the record**. After it they are not.

**`derive_manifest_sha256` does not make the manifest immutable and does not
claim to.** It makes a substitution *detectable*, which is the most a record can
do about an input the reader has to fetch. That is a weaker claim than the one
`docs/eval.md` shipped, and the amendment there says so.

## What is filed and not fixed

- **The manifest segment is still mutable.** A reader who fetches it and gets a
  different sha knows the ref no longer names what it named — they do not get the
  original bytes back. Attack direction: allow a `git:` manifest segment, which
  needs a spec grammar where two `git:` triples can be told apart without
  escaping. The current `split(":", 3)` cannot express it, so this is a form
  change and not a patch.
- **`rubric_sha256` is still empty on a derived variant**, and the reason lives
  in a docstring rather than in the artifact — the same defect
  `payload_sha256_recipes` was shipped to fix, one field over. That is L5's I5
  and it is still open.
