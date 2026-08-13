# RB-P18 — whether two records' payload shas can be compared, before and after

**Job:** `rbp16-rbp17-rbp18-evidence-grading`, unit L4. **Layer:** Measurement.
**Tree:** `feat/rbp16-inconclusive-effect-size`. **Before** = `9ed1886` (L3's last commit,
RB-P18 untouched). **After** = `6b82c5d` (this unit's fix). **Measured:** 2026-08-14.

Re-run:

```sh
sh docs/eval-data/2026-08-14-rbp18-payload-recipe.sh "$PWD" /tmp/rbp18
# and for the BEFORE column:
git checkout 9ed1886 -- runtime-py/src/bantamkit/criticreplay.py
sh docs/eval-data/2026-08-14-rbp18-payload-recipe.sh "$PWD" /tmp/rbp18-before
git checkout 6b82c5d -- runtime-py/src/bantamkit/criticreplay.py   # by SHA, not HEAD
git diff HEAD --exit-code                                          # tree byte-exact
```

Statuses are `/bin/sh`'s own `$?`, with no `PYTEST_*` key in the child's environment and
`PYTHONPATH` pinned to `runtime-py/src`. The pre-fix tree was **asserted** before the
before-run — in `runtime-py/src/bantamkit/criticreplay.py`,
`grep -c payload_canonical_sha256` = **0**, `grep -c payload_sha256_recipes` = **0**,
`grep -c sort_keys` = **0**, `grep -c payload_shas_recorded` = **0**, `grep -c '_payload_sha('`
= **2** — and the restore was asserted afterwards to be byte-exact
(`git diff HEAD --exit-code` → **0**). RB-P28 is open and its residual has been
demonstrated twice, so **the suite is not the evidence for this claim** — the nodes in
`test_criticreplay.py` are regression guards and this file is the measurement.

## The fact the whole fix rests on, re-derived

Printed by the runner itself on every invocation, from `git show` and the two committed
artifacts, so it is a command in the record and not a number quoted into it. Identical in
both columns — it re-derives the *committed* record, which no fix touches:

```
variant      r        seed prompt        ensure_ascii  +sort_keys    ==bar ==SA3
A-asfiled    0  2331795949 8fb6c98412f1  a17fc774681a  4eb56220e883  True  True
A-asfiled    1  4094558621 8fb6c98412f1  31dfc635d063  8faa7b09cf93  True  True
A-asfiled    2   634446002 8fb6c98412f1  10aead1cfe12  0deaa1885fe6  True  True
C-attempted  0  2331795949 37562002f423  dec8f90e5277  f21d86882f8c  True  True
C-attempted  1  4094558621 37562002f423  600d13d7ceb7  7593740dc678  True  True
C-attempted  2   634446002 37562002f423  8ba8643c3174  4e8a67012b59  True  True
all six cells reproduce, prompt_sha256 included: True
```

So on all six committed (variant, seed) cells: **one dict**, hashed two ways.
`json.dumps(payload, ensure_ascii=False)` reproduces the perturbation bar's committed
`payload_sha256`; the same call plus `sort_keys=True` reproduces SA3's. **The whole
cross-record incomparability is one keyword argument** — which is *not* what RB-P18 filed.

The `prompt_sha256` column is the anchor and the runner asserts it too (`allok` includes
`row["prompt_sha256"] == h(prompt)`): the rebuilt prompt hashes to the committed
`8fb6c98412f1…`, a field the reconstruction did not choose, so the payload being hashed
really is the one those records describe.

### The census, also a command in the record

```
list     30 occurrences in  1 artifact(s)
str    1280 occurrences in 12 artifact(s)
distinct shapes under ONE field name: 2
```

## What is being measured, and how the checker stays independent

The runner runs the shipped `main()` in a real process
(`runtime-py/tests/rbp16_effect_probe.py` — L2's harness reused unchanged: the CLI with
only the client constructor replaced, by a critic scoring `sha256(prompt|seed) % 11`). A
payload sha does not depend on the response, so the critic cannot influence what is
measured; it is used because it is the shipped CLI. The cells are the committed acceptance
cells — rubrics `git:d2f78b7` and `git:e57f1a6`, the frozen task asset, SA3's own
`answer_replayed` and `model`, the committed seeds. `assets/` is not touched.

**The question is not "are the two frozen values equal".** They are frozen and they are
not. It is **"can a reader holding both decide whether the requests differed"**, and that
is measured as: *how many of the two frozen record families does a single run made today
reproduce?* One family means the other family's value corresponds to nothing this tool can
produce, and the reader is guessing. Two means every frozen value can be placed in a named
column.

**The checker never imports `bantamkit`.** It reads the frozen values out of the committed
artifacts, reads the fresh run's `--json` rows and `--summary`, and compares — and it
normalizes the two frozen *shapes* (`str`, `list`) itself rather than calling the module's
new reader, so the arity finding is not the module agreeing with itself.

The one place the re-derivation block *does* import the module is prompt rendering and the
schema instruction, because those **are** the request and cannot be rebuilt without them.
What it does not do is trust the module's hashing: it calls `json.dumps` and `hashlib`
itself, twice, and never calls `_payload_sha` or `_payload_shas`.

## The matrix

| case | status before | status after | cells | reproduces bar-frozen | reproduces SA3-frozen | recipes named | identity named |
|---|---|---|---|---|---|---|---|
| E1 the spec cell (`A-asfiled` r0) | 3 | 3 | 1 | 1/1 → 1/1 | **0/1 → 1/1** | **0 → 2** | **0 → 1** |
| E2 both variants (r0) | 3 | 3 | 2 | 2/2 → 2/2 | **0/2 → 2/2** | **0 → 2** | **0 → 1** |
| C1 CONTROL `r1` scored against r1 | 3 | 3 | 1 | 1/1 → 1/1 | **0/1 → 1/1** | **0 → 2** | **0 → 1** |
| C2 CONTROL `r1` scored against **r0** | — | — | 1 | **0 of 2** | **0 of 2** | — | — |

`reproduces bar-frozen = n/m`: of the `m` identity cells the run produced, `n` have a
`payload_sha256` equal to the value the committed perturbation bar froze for that cell.
`reproduces SA3-frozen = n/m`: the same against SA3's frozen value, read through the
canonical column. `recipes named` is how many `json.dumps` calls the summary states;
`identity named` is whether it states `prompt_sha256` as the cross-record identity.

**No status changes, and that is correct.** This is not a defect that could ever have
shown up as an exit status — a run that records an incomparable sha is a run that
*succeeded*, which is exactly why RB-P18 needed a record and not a status. What moves is
what the artifacts let a second reader conclude.

### Reading the rows

**E1 and E2 are the whole claim.** Before, a run made today reproduced **one** of the two
frozen families: the bar's, because that is the recipe it has. SA3's 30 frozen shas
corresponded to nothing this tool could emit, so a reader holding a bar row and an SA3 row
had two unequal hashes and no way to tell a different request from a different `json.dumps`
call. After, **one request lands on both** — `payload_sha256` = `a17fc774681a…` and
`payload_canonical_sha256` = `4eb56220e883…`, from the same `structured()` call, at one
seed, on one dict. E2 shows it is not one lucky cell: `C-attempted` reproduces its own
frozen pair in the same run, and that variant differs from `A-asfiled` in the rubric
*schema*, so its `response_format` differs on the wire too.

**How a reader interprets the FROZEN rows under this.** Nothing here rewrites them, and
nothing can. What changes is that a frozen value is now interpretable by **re-running its
cell and seeing which column it lands in** — the recipe is executable rather than prose,
which is the same move L3 made for `rubric_ref`. That is only available because the second
column was chosen to be a recipe that *is already a committed value*: `sort_keys=True` is
the only key-order-independent form of the same call **and** the one SA3 used. Any other
order-independent canonicalisation (`ensure_ascii=True`, different `separators`) would be
equally order-free and would match nothing already written down, leaving SA3's 30 rows
exactly as uninterpretable as they were.

**`recipes named` 0 → 2 and `identity named` 0 → 1 are the other half of the fix**, and
they are read off the *artifact*, not off this repository. The reader RB-P18 is about has
the JSONL and not the tree — which is precisely how SA3's recipe came to survive only as
prose in its own `how_to_reproduce`, its scripts being in no tree. So every summary a run
writes now carries `payload_sha256_recipes`: the exact call behind each column, plus
`cross_record_identity: "prompt_sha256"` and `comparable_column:
"payload_canonical_sha256"`.

**C1 and C2 are the control that proves the checker can say no.** C1 runs the `r1` cell and
scores it against `r1`'s frozen pair: 1/1 and 1/1. C2 scores **the same run** against
`r0`'s frozen pair: **0 of 2**. A checker that reported "reproduced" for any run would be
measuring nothing; a seed that differs must not reproduce another seed's cell, and it does
not — before or after.

## Contract-claim pinning, measured not cited

`.venv/bin/python tools/pinharness/pinned.py . <ref> <ledger>`, both ends re-measured
rather than one cited:

| | ref | ledger | nodes | behaviour | prose | overall |
|---|---|---|---|---|---|---|
| BEFORE | `9ed1886` | that commit's 29-claim ledger | 788 passed, 2 xfailed | 23/24 (96%) | 5/5 (100%) | **28/29** |
| AFTER | `6b82c5d` | this unit's 31-claim ledger | 792 passed, 2 xfailed | 26/26 (100%) | 5/5 (100%) | **31/31** |

The BEFORE was re-measured rather than cited, and reads `28/29` — exactly the number
`9ed1886` committed. **Per claim**, because a total hides a swap: **`N03` moved UNPINNED →
PINNED**, `N09` and `N10` landed PINNED, and **every one of the 29 pre-existing claims is
still PINNED — `B01`–`B16`, `P01`–`P05`, `N01`, `N02`, `N04`–`N08`.** `P04` in particular
was re-read deliberately: L3's regression was a *second* prose disclosure silently
unpinning a first, and this unit added a disclosure to `docs/eval.md` but none to the
epilog's `USAGE_EXIT` block, which is the only block `P04` reads. It is PINNED at both
ends.

There is no longer an UNPINNED claim in the ledger.

**`N03` could only have moved by being re-aimed.** L1's node reads two committed records;
committed evidence is never regenerated, so no mutation of this module can turn it red. The
node that pins the claim is
`test_a_fresh_run_reproduces_both_frozen_payload_recipes_from_one_request`, which issues a
request today; under `N03`'s mutation (drop `sort_keys=True`) the canonical column collapses
onto the insertion-order one and stops being SA3's value.

## What did not close, in the terms it was filed in

**RB-P18's filed MECHANISM does not reproduce, and its filed ATTACK is not what shipped.**
The filing says the two recipes "serialize different dicts". Re-measured independently at
this HEAD on all six cells: they serialize the identical dict. The attack that follows from
the filing — "version the field name so two recipes cannot share one" — would make
permanent, in the schema, a difference canonicalisation removes, so it was not shipped and
should not be.

**L1's `xfail` did not go green, and it cannot.**
`test_payload_sha256_does_not_name_two_recipes_at_once` reads two committed records, and
all three of its disjuncts are facts about frozen bytes: the two shas are unequal, both
records carry the key `payload_sha256`, and neither record has any other key containing
`payload` (measured: 21 keys on the bar row, 8 on the SA3 entry). Only a retro-edit could
clear it. It can go neither red nor green under any change to this module, so **it pins
nothing in either direction** and stays `xfail` permanently with a dated note saying so —
the same structural finding L1 made about `N02`/`N03` and L3 confirmed for RB-P17's twin.
Confirmed under `--runxfail`: it still fails, on the frozen pair, at the frozen prompt sha.

**STILL OPEN, one level below the recipe: one name, two ARITIES.** Measured above and
unchanged by this fix — `payload_sha256` is a `str` in 1280 places and a `list` in 30, and
the naive cross-family `==` is `False` before and after. Shipped: `payload_shas_recorded`,
a reader that gives the field a defined reading in either shape and **preserves
cardinality**, because SA3's list is not a typo — a bar row is one *replay*, an SA3 entry
is one *cell* whose field is the SET of distinct shas across that cell's processes, and
cardinality 1 is that file's own stated claim that "any score spread is the server's, not
the prompt's" (all 30 lists have length 1, so all 30 make it). What is **not** fixed is the
cause: the unit of record is inferred from a JSON type instead of being stated.
**Attack:** name it — a `unit` field (`"replay"` vs `"cell"`) so an aggregating writer
declares what it aggregated, rather than a later reader deducing it from `isinstance`. It
cannot be retro-fitted to SA3, whose writer is in no tree and whose rows are frozen; it
binds the next writer.
