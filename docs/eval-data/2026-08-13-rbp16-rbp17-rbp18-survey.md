# RB-P16 / RB-P17 / RB-P18 — the probe survey (L1, 2026-08-13)

Job `rbp16-rbp17-rbp18-evidence-grading`, unit L1. Branch
`feat/rbp16-inconclusive-effect-size` off `b496856` (v0.20.0). Layer: **Measurement**.

`docs/eval.md` calls RB-P16 "the instrument's **largest real gap**". That is an
adjective. This file replaces it with numbers, for **every cell of every committed
acceptance run**, so that the fix is designed against the distribution instead of
against the one cell the filing happened to quote.

**Nothing here is a fix.** No behaviour changed; `_separation`, `format_table` and
`parse_rubric_arg` are untouched; no committed evidence file was regenerated or
retro-edited. Three non-strict `xfail`s were added and three claims were added to
`tools/pinharness/contract-ledger.json`; the ledger's before-number is at the bottom.

Every table below is stdout of:

```
.venv/bin/python docs/eval-data/2026-08-13-rbp16-rbp17-rbp18-survey.py .
```

which reads only committed artifacts and this repo's git history. Re-run it rather
than trusting the prose.

---

## 0. How much committed record there actually is

Twelve `-summary.json` files under `docs/eval-data/` carry a `comparisons` block. Ten
of them are **single-variant** runs — `[A-asfiled]` or `[after]` — so their
`comparisons` lists are empty and §7's decision rule never fired in them at all.

**The entire committed record of §7 verdicts is 12 comparisons over 2 runs**, both on
`nav-prod-port` at 14b:

| run | variants | cells | comparisons |
|---|---|---|---|
| `2026-08-11-pb14-14b-nav-prod-port-perturbation-summary.json` | A, B, C | 3 | 9 |
| `2026-08-12-pb14-14b-nav-prod-port-replay3-summary.json` | A, B | 3 | 3 |
| the other ten summaries | one variant each | 182 | **0** |

`grep -c` on the whole of `docs/eval-data/` finds the words `inconclusive` /
`indistinguishable` in those two files and nowhere else; SA3's `verdict` fields and
the M1 catalogue's are pass/fail and attack verdicts, not §7 separations. No committed
comparison carries `guard_verdict` either — both pb14 runs predate RB-P19's block, so
the guard's copy of the same decision rule has **zero** committed instances.

---

## 1. The verdict survey (RB-P16)

| run | task | r | a vs b | verdict | a | b | F | Δn | Δrate | sign | attributable |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pb14 2026-08-11 | nav-prod-port | 0 | A-asfiled vs B-nonewline | inconclusive | 0/11 | 7/11 | 11 | −7 | −0.6364 | − | false |
| pb14 2026-08-11 | nav-prod-port | 0 | A-asfiled vs C-attempted | inconclusive | 1/12 | 11/12 | 12 | −10 | −0.8333 | − | false |
| pb14 2026-08-11 | nav-prod-port | 0 | B-nonewline vs C-attempted | inconclusive | 7/11 | 10/11 | 11 | −3 | −0.2727 | − | false |
| pb14 2026-08-11 | nav-prod-port | 1 | A-asfiled vs B-nonewline | inconclusive | 3/11 | 7/11 | 11 | −4 | −0.3636 | − | false |
| pb14 2026-08-11 | nav-prod-port | 1 | A-asfiled vs C-attempted | inconclusive | 4/12 | 8/12 | 12 | −4 | −0.3333 | − | false |
| pb14 2026-08-11 | nav-prod-port | 1 | B-nonewline vs C-attempted | **indistinguishable** | 7/11 | 7/11 | 11 | 0 | 0.0000 | 0 | false |
| pb14 2026-08-11 | nav-prod-port | 2 | A-asfiled vs B-nonewline | inconclusive | 2/11 | 7/11 | 11 | −5 | −0.4545 | − | false |
| pb14 2026-08-11 | nav-prod-port | 2 | A-asfiled vs C-attempted | inconclusive | 3/12 | 11/12 | 12 | −8 | −0.6667 | − | false |
| pb14 2026-08-11 | nav-prod-port | 2 | B-nonewline vs C-attempted | inconclusive | 7/11 | 10/11 | 11 | −3 | −0.2727 | − | false |
| replay3 2026-08-12 | nav-prod-port | 0 | A-asfiled vs B-nonewline | inconclusive | 0/11 | 7/11 | 11 | −7 | −0.6364 | − | false |
| replay3 2026-08-12 | nav-prod-port | 1 | A-asfiled vs B-nonewline | inconclusive | 3/11 | 7/11 | 11 | −4 | −0.3636 | − | false |
| replay3 2026-08-12 | nav-prod-port | 2 | A-asfiled vs B-nonewline | inconclusive | 2/11 | 7/11 | 11 | −5 | −0.4545 | − | false |

`inconclusive` **11**, `indistinguishable` **1**, `distinguishable` **0**,
`attributable` **0**.

**Which of §7's rules decided `attributable`, per cell: rule 1, on 12 of 12.** Rule 1
(separation) has never fired in the committed record, so rule 2 (fragility voids the
cell) and RB-P19's third rule (the separation must survive the guard drop) have never
been the thing that decided anything — they are downstream of a rule that has never
been reached. Every cell is void because `F/F` versus `0/F` did not happen, and every
committed family is *also* fragile, which is a second reason nothing would have been
credited even if it had.

### 1a. The band's spread — how big the gap actually is

|Δrate| over the eleven `inconclusive` cells, sorted:

```
3/11  3/11  1/3  4/11  4/11  5/11  5/11  7/11  7/11  2/3  5/6
0.2727 0.2727 0.3333 0.3636 0.3636 0.4545 0.4545 0.6364 0.6364 0.6667 0.8333
```

|Δn|: `3 3 4 4 4 5 5 7 7 8 10`.

**The filing quotes the mild end of its own band.** RB-P16's example — `B-nonewline`
7/11 vs `C-attempted` 10/11, twice — is |Δ| = 3/11 = 0.2727, the **smallest** gap in
the band. The worst is `A-asfiled` **1/12 vs `C-attempted` 11/12** on r0: |Δ| = 5/6 =
0.8333, ten of twelve points flipped, **one point short of `0/F` versus `F/F` on each
side** — and it wears the same word. So the answer to "is 7/11-vs-10/11 the worst case
in the committed record" is **no, by a factor of 3.06 in |Δrate| and 3.33 in |Δn|**.

### 1b. Is the band's *report* a function of the effect size? No.

Two cells of the **same pair**, the **same family size**, the **same committed run**:

| cell | a | b | \|Δ\| |
|---|---|---|---|
| r0 | 1/12 | 11/12 | 5/6 ≈ 0.8333 |
| r1 | 4/12 | 8/12 | 1/3 ≈ 0.3333 |

Remove the two pass-rate fractions and the two reports are **byte-identical**:

```json
{"a": "A-asfiled", "attributable": false, "b": "C-attempted", "dropped_rules": [],
 "family_size": 12, "fragile": ["A-asfiled", "C-attempted"], "verdict": "inconclusive"}
```

Re-derived with today's `_compare` over the committed rows, the same holds and
`guard_verdict` is `"inconclusive"` too — the guard's copy of the rule inherits the
gap whole.

> **Does not reproduce as filed.** RB-P16 says "§7's decision rule gives the band no
> reporting duty **beyond the word**." That is stronger than what is true. Both pass
> rates are on every comparison dict and `format_table` prints them on the Pairwise
> line (`- nav-prod-port r0: A-asfiled 0/11 vs B-nonewline 7/11 -> inconclusive
> (F=11)`). What is missing is the **difference**, the **sign**, and any statement
> across cells — the reader is handed the arithmetic, not denied the inputs. This
> narrows what a fix has to add.

### 1c. Sign agreement — the rule the filing proposes has no instance

| run | pair | signs | agree |
|---|---|---|---|
| pb14 2026-08-11 | A-asfiled vs B-nonewline | −1, −1, −1 | yes |
| pb14 2026-08-11 | A-asfiled vs C-attempted | −1, −1, −1 | yes |
| pb14 2026-08-11 | B-nonewline vs C-attempted | −1, **0**, −1 | the 0 is the `indistinguishable` cell |
| replay3 2026-08-12 | A-asfiled vs B-nonewline | −1, −1, −1 | yes |

**Every `inconclusive` cell in the committed record has sign −1.** There is no run in
which two `inconclusive` cells of one pair point in opposite directions. The only
non-negative sign anywhere is the exact tie that already reads `indistinguishable`.

> **A rule with no instance in the record is a rule nobody has tested.** RB-P16's
> "require the sign to agree across cells before an `inconclusive` may be described as
> directional" would change **nothing** on any committed cell. It is a guard against a
> case the project has never seen. That is not an argument against building it — it is
> an argument that building it cannot be justified by the committed evidence, and that
> whoever builds it owes a constructed case, not a citation.

### 1d. Does another verdict word have the same problem? Yes — `indistinguishable`.

`_separation` returns `indistinguishable` on **equal pass counts**. Equal counts is
not agreement. Point-level, from the committed rows of the 2026-08-11 run:

| cell | F | B passes | C passes | passed by both | B-only | C-only |
|---|---|---|---|---|---|---|
| r0 | 11 | 7 | 10 | 7 | — | O1-swap-format-refusal, W2-double-trailing, W5-blank-line-before-bands |
| **r1** | 11 | **7** | **7** | **6** | **P2-asks-requests** | **W2-double-trailing** |
| r2 | 11 | 7 | 10 | 7 | — | O1-swap-format-refusal, W2-double-trailing, W5-blank-line-before-bands |

The one committed `indistinguishable` cell is a cell on which the two variants
**disagree on 2 of 11 points**. The word claims an identity the measurement does not
support, and — exactly like `inconclusive` — there is no reporting duty attached to it.
This is unfiled. It is the same defect in the same function, one branch up.

---

## 2. The provenance survey (RB-P17)

Five distinct `rubric_ref` values across all twelve committed summaries.

| `rubric_ref` | labels | `rubric_sha256` | runs | classification |
|---|---|---|---|---|
| `assets/rubrics/task-completion.yaml` | A-asfiled, after | `55f700e09bab` | 10 | **resolvable today** (repo-relative; re-hashes to the recorded sha) |
| `d2f78b7` | A-asfiled | `55f700e09bab` | 2 | **a bare git ref**: the commit resolves, the **path does not exist in the record** |
| `e57f1a6` | C-attempted | `8d145b7ee01d` | 1 | same |
| `/private/tmp/…/scratchpad/b-nonewline.yaml` | B-nonewline | `59b0fe81ecf3` | 1 | **a path this repo cannot resolve** |
| `/private/tmp/…/scratchpad/n5-b-nonewline.yaml` | B-nonewline | `29f299707fd6` | 1 | same |

Three things the filing does not say:

1. **Two scratchpad paths, not one** — `b-nonewline.yaml` in the 2026-08-11 run and
   `n5-b-nonewline.yaml` in the 2026-08-12 replay3 run.
2. **They record different `rubric_sha256` for the same rubric under test.**
   `59b0fe81…` and `29f29970…` are different *file* bytes; both parse to a `prompt`
   template whose sha is `d1f32ad2947b…`. `rubric_sha256` is the **file**, not the
   rubric the critic read. A reader comparing the two runs on it concludes they used
   different rubrics. They did not.
3. **The `git:` form's recorded ref drops the path.** `parse_rubric_arg` sets
   `source = ref` on the git branch and stores it as `RubricVariant.ref`; `spec` — the
   only field that holds `git:<ref>:<path>` — is never written to a row or a summary.
   So `d2f78b7` names a commit and not a file, and `rubric_sha256` cannot be
   re-derived from it without guessing the path. That is the same defect on the form
   the filing calls the good one.

> **Does not reproduce as filed.** RB-P17 says the summary "records `rubric_ref` as a
> session temp path **that no longer exists**". Measured 2026-08-13: **both** paths
> still exist on this machine, and both still hash to their recorded `rubric_sha256`.
> The defect is real and the substance ("one cleanup away") stands — but the stated
> fact is false today, and a filing whose stated fact is false is a filing a later
> reader will check and disbelieve.

### 2a. Re-verifying the claim the filing rests on

```
git show d2f78b7:assets/rubrics/task-completion.yaml
```

| what | sha256 |
|---|---|
| the file bytes | `55f700e09bab0cfac01cb18d4cfb54666ff942598035697e0383726fe82c2868` |
| its `prompt` template (A-asfiled base) | `e018854368c1b675e7cff5109a3dce715d59c86d871cd3d1d83b9083188a065e` |
| the same, minus one trailing newline (B-nonewline base) | `d1f32ad2947b4d6f6079833847eae96c79fddeb2683ceda322940bdc8cbf13a6` |

The manifest records `materialized_variants.B-nonewline.base_sha256` =
`d1f32ad2947b4d6f6079833847eae96c79fddeb2683ceda322940bdc8cbf13a6`. **Reproduces
exactly.** The filing's `d1f32ad2…` claim holds, and both scratchpad files parse to
that same template.

### 2b. The spec forms `--rubric LABEL=SPEC` admits today

`rubric_arg_shape_problem` + `parse_rubric_arg`, in order:

1. `LABEL=` must be non-empty and `SPEC` must be non-empty, or `USAGE_EXIT`.
2. `SPEC` starting `git:` must be `git:<ref>:<path>` with both segments non-empty
   (RB-P32); `git show <ref>:<path>` supplies the bytes; **recorded ref = `<ref>`**.
3. Anything else is a filesystem path, `is_file()` or `REFUSAL_EXIT`; **recorded ref =
   the spec string**, absolute or not.

There is no third form. `derive:A-asfiled:W1-trailing-newline` passes the shape check
(it does not start `git:`), falls through to the path branch, and raises
`PerturbationError: rubric not found: derive:A-asfiled:W1-trailing-newline`.

### 2c. What `derive:<label>:<rule-id>` would have to resolve against

The rule ids live in the **frozen** manifest
`assets/evals/perturbations/task-completion.yaml`, twelve of them, each with a
`rule` and a per-variant materialized sha:

| point id | rule | A-asfiled → | applicable to B-nonewline |
|---|---|---|---|
| `identity` | identity | `e018854368c1` | yes |
| **`W1-trailing-newline`** | strip-trailing-newline | **`d1f32ad2947b`** | **no** |
| `W2-double-trailing` | append-trailing-newline | `447e5be27613` | yes |
| `W3-unwrap-opening` | unwrap-hard-wrapped-run | `0a41447a57d8` | yes |
| `W4-double-space` | double-space-after-period | `4c54e4d49cf7` | yes |
| `W5-blank-line-before-bands` | extra-blank-line-before-anchor | `f55493678f7d` | yes |
| `O1-swap-format-refusal` | swap-sentences | `b6a0693eacbd` | yes |
| `O2-bands-ascending` | reorder-list-items | `740cbc7c7289` | yes |
| `O3-swap-judge-only` | swap-sentences | `70511e553532` | yes |
| `P1-reviewer-relative` | reword-frame-clause | `0db59b358d4f` | yes |
| `P2-asks-requests` | reword-verb | `018859a1c9b1` | yes |
| `P3-right-correct` | reword-adjective | `24ea0c22c888` | yes |

**The recipe is already mechanically confirmed by the frozen manifest.** Applying
`W1-trailing-newline` to `A-asfiled` gives `d1f32ad2947b…` — B-nonewline's
`base_sha256`, exactly. And `W1` is **not applicable** to `B-nonewline` (the anchor is
already gone), so the derived variant is a fixed point of its own rule and there is no
load-order cycle through `_check_materialization`. `W2-double-trailing` on
`B-nonewline` gives back `e018854368c1…` = A's template, which is the same fact from
the other side.

**Are the ids stable enough to be a provenance record?** They are `id` fields in a
frozen asset whose whole-file sha is stamped into every row as `manifest_sha256`, so a
rename is a visible manifest diff and a re-derivation would fail
`_check_materialization`. That is as stable as anything in this repo. **But the ref as
the filing spells it is not self-contained**: `A-asfiled` is a run-local `--rubric`
label. `derive:A-asfiled:W1-trailing-newline` is resolvable only from the same argv
that defined `A-asfiled`, and the manifest it indexes is named nowhere in the ref. For
the recorded `rubric_ref` to be provenance rather than a pointer into a vanished
process, the recorded form has to expand the label to the underlying
`git:<ref>:<path>` and name the manifest. **That is a defect in the attack as filed,
not in the idea.**

---

## 3. The payload-field survey (RB-P18)

### 3a. Every sha-shaped field in this repo, and what it serializes

| field | computed at | serializes |
|---|---|---|
| `prompt_sha256` | `replay_verdicts`, `criticreplay.py:1178` | the rendered critic prompt, `sha256_text(prompt)` |
| `payload_sha256` | `_payload_sha`, `criticreplay.py:1116-1130` | `json.dumps({"model", "messages", "seed"?, "response_format"?}, ensure_ascii=False)` — **insertion order**, captured off the request `structured()` actually sends |
| `rubric_sha256` | `parse_rubric_arg`, `:975` | the rubric **file** bytes |
| `manifest_sha256` | `load_manifest`, `:594` | the manifest **file** bytes |
| manifest point `sha256`, `base_sha256` | `materialize_manifest`, `:857` | the perturbed **template** string |

`_payload_sha` is the **only** `payload_sha256` computation anywhere in this
repository. `grep -rn hashlib runtime-py/src runtime-ts tools` finds no second one.
The other recipe exists **only** in the committed SA3 artifact and in its
`how_to_reproduce` prose ("scratchpad scripts `sa3_one.py` and `sa3_ws.py`"), which
are in no tree.

Committed artifacts carrying `payload_sha256`: every perturbation-bar JSONL
(`2026-08-11-pb14-…`, `2026-08-12-pb14-replay3-…`, `2026-08-12-m1-…`,
`2026-08-12-rbp19*-…`) under the bar's recipe, and
`2026-08-11-sa3-14b-nav-prod-port-critic-replay.json` under the other one.

### 3b. Re-measured, not repeated — and the recipe recovered

Both recipes re-derived from `git show` at test time and checked against the committed
values, on **all six** (variant, seed) cells:

| variant | ref | r | seed | prompt sha | bar `payload_sha256` | SA3 `payload_sha256` | matches committed bar row | matches committed SA3 |
|---|---|---|---|---|---|---|---|---|
| A-asfiled | d2f78b7 | 0 | 2331795949 | `8fb6c98412f1` | `a17fc774681a` | `4eb56220e883` | yes | yes |
| A-asfiled | d2f78b7 | 1 | 4094558621 | `8fb6c98412f1` | `31dfc635d063` | `8faa7b09cf93` | yes | yes |
| A-asfiled | d2f78b7 | 2 | 634446002 | `8fb6c98412f1` | `10aead1cfe12` | `0deaa1885fe6` | yes | yes |
| C-attempted | e57f1a6 | 0 | 2331795949 | `37562002f423` | `dec8f90e5277` | `f21d86882f8c` | yes | yes |
| C-attempted | e57f1a6 | 1 | 4094558621 | `37562002f423` | `600d13d7ceb7` | `7593740dc678` | yes | yes |
| C-attempted | e57f1a6 | 2 | 634446002 | `37562002f423` | `8ba8643c3174` | `4e8a67012b59` | yes | yes |

The concrete cell the spec pins: **A-asfiled, `git:d2f78b7`, repeat 0, seed
2331795949, score 5**, prompt sha `8fb6c98412f1…` in both records (SA3 carries it as
`prompt_sha256_asfiled` in its whitespace-null-control block) —

```
bar  payload_sha256 = a17fc774681ad0fec7376abbf3c3b3ba387f70ea67450b7ed4812580bb8edc4e
SA3  payload_sha256 = 4eb56220e883d5718bd816b5b00106d1abc127a8a5f72a7d305f8db9fafef906
```

> **Does not reproduce as filed, and this is the largest correction in this survey.**
> RB-P18 says the two disagree "**because the two recipes serialize different dicts**
> under the same field name". They do not. Recovered by search over candidate
> serializations and then confirmed on all six cells: **both recipes serialize the
> identical dict** — same `model`, same `messages`, same `seed`, same
> `response_format`. The only difference is
>
> ```
> bar   json.dumps(payload, ensure_ascii=False)                    # insertion order
> SA3   json.dumps(payload, ensure_ascii=False, sort_keys=True)    # sorted keys
> ```
>
> **The whole cross-record incomparability is one keyword argument.** The filed attack
> — "version the field name so two recipes cannot share one" — would make the
> incomparability permanent and documented, when a canonicalisation makes it go away.
> A field whose name says nothing about its key order is the defect; two names for one
> content is not the fix L2 should reach for first.

Also worth L2's attention: `rubric_sha256` (file bytes) versus the manifest's
`base_sha256` (template text) is **the same defect in a second field pair** — §2's
point 2 is the measured instance, two committed runs recording different
`rubric_sha256` for one rubric under test.

---

## 4. The three executable specs

All three are non-strict `xfail` in `runtime-py/tests/test_criticreplay.py`, each
preceded by a **non-`xfail` fixture guard**
(`test_the_committed_acceptance_artifacts_are_the_ones_these_three_specs_aim_at`)
which asserts the committed evidence still says what L1 measured and that re-deriving
a cell with today's `_compare` reproduces the committed comparison field for field. An
`xfail` that fails on a fixture mistake pins nothing.

| node | pins | fails today because |
|---|---|---|
| `test_the_inconclusive_band_reports_something_a_reader_can_tell_from_noise` | a band verdict a reader can tell from noise — the **duty**, no field named | r0 (1/12 vs 11/12) and r1 (4/12 vs 8/12) report identically once the fractions are removed |
| `test_every_rubric_ref_in_a_committed_summary_resolves_from_this_repo` | every `rubric_ref` resolves back to its `rubric_sha256` from this repo alone | 4 of 5 refs do not: 2 scratchpad paths, 2 bare git refs |
| `test_payload_sha256_does_not_name_two_recipes_at_once` | one name, one recipe — or the recipe named beside it | the two records disagree at identical prompt, seed, model and score, and neither names its serialization |

Failures under `--runxfail`, verbatim, are in section 6 of the handoff.

### The pinning bar, and where it does not reach

`tools/pinharness/contract-ledger.json` gains **N01 (RB-P16)**, **N02 (RB-P17)** and
**N03 (RB-P18)**, each with the mutation that would falsify it.

```
.venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/contract-ledger.json
```

**Before number, measured at `b496856` on the 21-claim ledger: behaviour-pinned 16/16
(100%), prose-pinned 5/5 (100%), overall 21/21.** With N01/N02/N03 added the ledger is
21/24; the three new ones read **UNPINNED**, which is correct — they are claims about
problems that are still open — and it is the number L2/L3/L4 have to move.

**A structural finding L3 has to act on.** N02 and N03 can never be pinned by the
nodes L1 wrote, no matter what the fix does: those nodes read **committed artifacts**,
which by invariant are never regenerated, so no mutation of the source can turn them
red. N01's node re-derives with today's `_compare` over the committed rows and **is**
mutation-sensitive. Pinning N02 and N03 requires a node over a **fresh** run's recorded
fields. This is named in each ledger entry's `note` rather than left for the harness to
discover.
