# The record-vs-pointer rule

**The rule and its checker landed in one commit.** That was the user's ratification —
*"เอาแบบนี้ ให้ J3 สร้าง checker แล้วเขียนกฎไปพร้อมกัน"* — and it is not a formality. A rule
without a mechanism is another intention for the next pin drift to step on; J1 and J2 both
shipped conventions that nothing enforced, and L-U5-3 is the finding that one of them
drifted. The mechanism is `tools/amendguard/amendguard.py`. Its specification is
[the J3 plan, §4](eval-data/2026-08-19-instrument-hygiene-plan.md).

Everything below is either a rule you can read or a branch the checker takes. Where the
two could drift apart, the checker is the one that decides, and the fixture that pins the
checker is synthetic — the checker builds it, and no expectation about it is an
expectation about this repository.

---

## 1. The three kinds

### RECORD — amend only

A **number**, a **verdict**, a **table**, a **verbatim block**, a **claim**.

A record is a statement about a moment that has passed. Changing it in place rewrites what
was *said*, not what is *true*, and the thing an evidence document is for is what was said.
Corrections are **dated amendments appended at the end**, in their own commit.

This is the default, and it is the default *by construction*: see §2.

### POINTER — correctable in place, in its own commit, correction stated in the body

A pointer is a statement about **where something is**. It can become false without anyone
lying — a file grows, a section is renumbered, a link target moves — so it does not carry
the amend-only obligation. It carries a different and stricter one: **the fix is its own
commit, touching nothing else, and the commit body says what was corrected.**

The classes are a **CLOSED LIST**. Four of them, and they live as data in
`POINTER_CLASSES`:

| # | class | matches | example |
|---|---|---|---|
| P1 | hyperlink or in-document anchor | a markdown link | `[Eval → Cross-model results](eval.md#cross-model-results)` |
| P2 | section citation | `§` and a dotted number | `bar §3.2` |
| P3 | `file:line` pin, in all three of its forms | a path pin, a bare backtick pin, a section pin | `…corpus.md:403` · `` `:1288` `` · `§10.2:718` |
| P4 | stale-state marker | a token that describes the present | `*(filled)*` · `TODO` · `pending` · `HEAD is <sha>` |

**Anything not on this list is a RECORD.** Widening the list is a commit that edits
`POINTER_CLASSES`, which is visible in a diff and reviewable as such — and
`test_every_pointer_class_on_the_closed_list_has_a_fixture_case` turns red if a fifth class
arrives without a calibration case, so the list cannot widen silently either.

**One exception, and it is the interesting one.** A `file:line` pin **inside a fenced
verbatim block** is a **RECORD**, not a pointer. A verbatim block is a record class and its
contents are *quoted*, not *cited* — correcting a pin inside a transcript would be
falsifying the transcript. This is the single input on which the syntactic reading and the
contextual reading disagree, and it exists on purpose: see §6.

### CO-MOVING COUNT — carries its derivation, and must equal it

> **Definition.** A figure whose correct value is a function of the body of the artifact
> that carries it, **at the same commit**.

"Ten findings filed", in the commit that files the eleventh. It is a number, so the closed
list calls it a record and forbids the edit — but leaving it says ten while the body shows
eleven, and amending it appends a correction whose only content is that the body below can
be counted. Both readings are defensible, which is exactly why the closed list cannot
decide it.

**The resolution is not a third amend-versus-edit ruling. It is a different property**, and
it makes the question disappear, because the number was never a claim about the past:

> **A co-moving count must carry its derivation, and must equal that derivation recomputed
> over the committed body at every commit.**

Written as a machine-readable marker immediately above the line that carries the number:

```
<!-- co-moving-count: findings = count(^### [ML]-U5-\d+$) -->
**Eleven findings filed.**
```

The marker governs the **next non-blank line**. The checker recomputes `count(...)` over
the committed body at every commit that touches the file and compares. Edit the number,
amend it, or rewrite the section — none of that matters, because the number is measured
against the body rather than against the history. A count that drifts is red **at the
commit that drifted it**, not discovered three jobs later.

**A marker inside a fenced verbatim block is QUOTED, NOT DECLARED** — the same rule the
fence already carries for pins. This one was not designed in; it was found by running the
checker over its own design document, which illustrates the marker in a fenced example and
was consequently reported `COUNT-STALE` against a count that document never claimed.
Calibration case `MARKER-QUOTED` holds it shut.

**Until a count carries the marker, the conservative reading binds: it is a record, amend,
do not edit.** That is the default, it is the safe direction, and it is what the checker
enforces on unmarked numbers by doing nothing about them at all.

---

## 2. CROSS-ARTIFACT CO-MOVING COUNT — not a fourth kind, and deliberately not

A pytest total. A ruff result. A file count. **It is a co-moving count by the definition
above** — its correct value is a function of a body a commit can change — but its
derivation lives *outside the document*, and that is a different animal.

**The marker cannot reach it, for three reasons, and they are reasons the mechanism fails
rather than reasons the case is unimportant.**

1. **The marker's derivation is a pure function of committed bytes; this one is not.**
   `count(^### F-\d+$)` is a regex run over a blob the checker already has. A pass count
   requires **executing the repository**. A checker that verified it would be asserting a
   fact about the world (RB-P14 Gate 2), and its verdict would depend on an interpreter and
   an installed environment — and a local interpreter is measurably not enough to stand in
   for the real target: `ast.parse(feature_version=(3,11))` reported this repo clean while
   CI's 3.11 leg rejected a module outright, because PEP 701 changed the **tokenizer** and
   not the AST.
2. **The scope is unbounded.** The same-body derivation reads one file. This one reads the
   whole tree plus its dependencies. There is no body for the checker to bound, so there is
   no recomputation for it to perform.
3. **It is cross-TREE, not merely cross-file.** The pytest total was **932** at one commit
   and **940** at another, and *both were correct*. There is no commit at which the number
   and its derivation are simultaneously true, so "equal to its derivation recomputed over
   the committed body at this commit" **has no referent**. The property is not merely hard
   to check here; it is not well-formed here.

**The ruling.** A cross-artifact co-moving count is **NOT** a fourth kind and does **NOT**
get the marker. It falls back to **RECORD — amend only** with one added obligation:

> **A cross-artifact co-moving count must carry a PROVENANCE STAMP: the value, the commit
> it was measured at, and the command that measured it.** Not the command alone. **The
> commit beside the number.**

```
<!-- provenance: value=932 passed, 2 xfailed; commit=5458059; command=.venv/bin/python -m pytest runtime-py/tests -q -->
932 passed, 2 xfailed
```

The stamp may sit on the number's own line or within the eight lines above it, which is
what lets one stamp cover a fenced block of gate output.

**This is strictly weaker than what the marker does for a same-body count, and saying so is
the point of the ruling.** The marker *verifies*: recompute, compare, go red. The stamp
verifies nothing — **the checker never learns whether 932 is correct.** It enforces
**falsifiability, not correctness**: that a reader is handed the commit and the command
needed to find out.

**THE GAP IS REAL AND IT STAYS OPEN.** Nothing in this design detects a cross-artifact
count that is stamped, plausible, and wrong. Closing it would need the checker to execute
the tree, which reasons 1 and 3 forbid. It is recorded as open rather than papered over by
broadening the definition in the same breath that discovered the case.

**Why the stamp would nonetheless have caught the one that started this.** The J3 plan's
§1.6 named its command and reported `932 passed, 2 xfailed in 17.12s` — **with no commit
beside the number** — and then generalised it to "both branches". A stamp binds a number to
exactly one commit, and that generalisation is not writable in stamped form.

---

## 3. The checker

```
python tools/amendguard/amendguard.py calibrate
python tools/amendguard/amendguard.py check <repo> <rev-range> <ledger.json> [--out FILE]
```

Both the subcommand and all three positionals of `check` are **required**, so a bare
invocation exits **2** from argparse. There is no `repo_root` defaulting to `'.'`, no
implicit write, and no path on which the program overwrites a committed artifact and exits
0 — which is exactly what two committed programs under `docs/eval-data/` do today (RB-P49).
`--out` is the only write it performs and it is explicit.

`tools/` is outside the five product layers and outside both ruff gates, so the checker is
one change in one place ([architecture](architecture.md)).

### The ledger

`tools/amendguard/ledger.json` names the **amend-only set** of this repository as path
patterns. A path not listed is not judged. **This document is not in it** — a convention
page is a living document, not an evidence artifact, and putting it under an amend-only
rule would make correcting a typo an amendment.

### The four verdict fields

| field | values | meaning |
|---|---|---|
| `classify` | `record` · `pointer:P1..P4` · `co-moving-count` · `append` · `insert` · `new-file` · `deleted` | what the changed hunks were decided to be, worst-first |
| `isolation` | `sole` · `mixed` | is this commit a pointer-only fix touching exactly one path |
| `derivation` | `ok` · `stale` · `absent` | for marked co-moving counts, does the number equal its recomputation over this commit's body |
| `verdict` | `OK` · `RECORD-EDITED` · `POINTER-NOT-ISOLATED` · `COUNT-STALE` · `STAMP-MISSING` · `BROKEN` | the gate |

`STAMP-MISSING` is §2's addition; the other five are the plan's. `append` and `insert` are
classifications for hunks that **add** text — an addition destroys no record, and appending
is how an amendment is written — but they are named separately because an insertion in the
body shifts every line number below it, which is the hazard the `file:line` convention
exists for.

### The two guards, and why each is machine-checkable rather than aspirational

1. **The closed list makes `classify` total.** Every changed hunk lands in exactly one
   branch and the default branch is `record`. A construct nobody thought about is therefore
   amend-only, which is the safe direction. There is **no "unclassified" output**, so the
   checker cannot be silent about something it did not understand — it says `record` and
   blocks.
   *Named node:* `test_an_unlisted_construct_falls_through_to_record`.
2. **`isolation` makes a lie visible in `git log --numstat`.** A commit that declares itself
   a pointer fix and moves thirty lines reads `isolation=mixed` and the verdict is
   `POINTER-NOT-ISOLATED`. The numstat is the evidence; it is not the checker's own word for
   it.
   *Named node:* `test_a_pointer_fix_bundled_with_anything_else_is_pointer_not_isolated`.

### UNMEASURED is a verdict

A ledger whose patterns matched no changed path prints `unmeasured=1` and exits **3**. It
does not exit 0 and it does not print a pass (RB-P51).

---

## 4. What is NOT guarded

Stated here rather than left to be discovered, because a guard described as wider than it
is is the failure this whole job is about.

- **Nothing runs the checker automatically.** RB-P41's CI half still holds:
  `grep -rl eval-data .github/` returns nothing, and `.github/workflows/ci.yml` has three
  run steps, none of which is this program. `runtime-py/tests/test_amendguard.py` guards
  the checker's **logic**; the checker guards the **repository**, by hand.
- **A stamped, plausible, wrong cross-artifact count.** §2. Open.
- **A pointer correction that is wrong.** The checker sees that a pin changed and that the
  commit touched nothing else. It does not resolve the pin. A pointer corrected from one
  wrong line to another reads `OK`.
- **Prose that changes meaning without changing a classified construct.** Rewriting a
  sentence is `record` and is caught; rewriting a sentence *inside an appended amendment in
  the same commit that appends it* is an addition and is not.
- **Merge commits.** A combined diff is not a hunk this rule can read, so no row is emitted
  and the run says so in a `merges=` field rather than passing quietly.

---

## 5. Calibration, and the rule that decides what counts as a mutation

`tools/amendguard/calibration.json` is **not a measurement**. It is the expected verdict for
every commit of a synthetic repository the checker builds itself, written from this document
and then compared against the run — never the other way round. It carries both pairs:

| must come back RED | must come back GREEN |
|---|---|
| `RECORD-EDITED` — a number rewritten in place | `POINTER-P3-SOLE` — a `file:line` pin corrected alone |
| `BARE-GATE` — a gate expectation with neither marker nor stamp | `STAMPED-GATE` — the same number, fully stamped |
| `VERBATIM-PIN` — a pin corrected inside a fenced block | `APPEND-OK` — a dated amendment appended |
| `COUNT-STALE` — a marked count the body outgrew | `COUNT-BUMPED` — the same count edited to match |
| `POINTER-P3-MIXED` — a pin fix bundled with another file | `MARKER-QUOTED` — a marker shown in a fenced example |

**An instrument that has not been shown to distinguish an edited record from a corrected
pointer is not evidence about either.** If any row flips, nothing the checker says about any
real commit may be believed.

### N-12, and why no assertion here is on a sentence

On 2026-08-19 a selfcheck in J7's harness reddened when a `void_reason` **string** branch
was reverted (2 RED) and stayed **green at 0 RED** when the ternary that actually **assigns**
the classification in the live loop was reverted. The claim named the classifier; the covered
line was the formatter. This checker has the identical exposure — `classify` is a classifier
and the `#` note lines are a formatter. So:

> **A mutation counts as pinning a branch only if it moves a machine-readable VERDICT FIELD.
> A mutation that moves only a human-readable message is recorded as FORMATTER-ONLY and the
> branch stays UNPINNED.**

Machine-readable output is exactly the lines beginning `VERDICT ` and `SUMMARY `. Everything
else is prose and nothing may assert on it.

`MUTATIONS` in the checker is keyed by **decision branch**, not by check name — one per
pointer class, one for the record default, one for the fence override, one for `isolation`,
one for `derivation`, one for the stamp, one for `append` — and each names the pytest node
entitled to pin it, exactly as `tools/pinharness/pinned.py` makes every claim name its
nodes. Coverage is counted **from the checker's printed verdict fields**, never from a grep
over its source: RB-P48 measured a source-side grep under-counting its own defect 5 against
11 of 14.

`MUT-NOTE-PROSE` is in the catalogue **on purpose and is not deleted to improve the number**
(RB-P48). It rewrites one sentence, moves no field, and is reported `FORMATTER-ONLY` with its
branch named. It is the demonstration that the rule above is enforced rather than described.

---

## 6. The tautology test, passed before any of this was trusted

RB-P47: **a cross-check between two transcriptions of one rule is a tautology.** J2's VOID
check was defended as two independent code paths that turned out to dispatch on the identical
four types.

So, before trusting that `classify` and the closed list agree, name an input on which they
**disagree**:

> A **`file:line` pin inside a fenced verbatim block.** A pointer by syntax — P3 matches it
> exactly. A record by context — a verbatim block is a record class and its contents are
> quoted, not cited.

That input exists, the two readings do disagree on it, the fence wins, and it is calibration
case `VERBATIM-PIN`, which must come back `RECORD-EDITED`. A cross-check that cannot be made
to disagree is a transcription and does not count.

Note what the fence does **not** exempt: a **gate expectation** inside a fence still needs a
provenance stamp. That is deliberate — the number that started §2 was sitting in a fence.

---

## 7. Measured, at the commit that shipped this

<!-- provenance: value=956 passed, 2 xfailed; commit=da5f073 plus this commit's working tree; command=.venv/bin/python -m pytest runtime-py/tests -q -->
- Suite: **956 passed, 2 xfailed** — `.venv/bin/python -m pytest runtime-py/tests -q`, at
  this commit's tree. The base `da5f073` measured **932 passed, 2 xfailed** by the same
  command; the delta is the 24 nodes of `test_amendguard.py` and nothing else.

<!-- provenance: value=All checks passed!; commit=da5f073 plus this commit's working tree; command=.venv/bin/ruff check runtime-py -->
- Lint: **All checks passed!** — `.venv/bin/ruff check runtime-py`.

<!-- provenance: value=19 expectations, 0 flips, 12 branches, 11 pinned, 1 formatter-only; commit=da5f073 plus this commit's working tree; command=python tools/amendguard/amendguard.py calibrate -->
- Calibration: **19 expectations, 0 flips; 12 branches, 11 PINNED, 1 FORMATTER-ONLY** —
  `python tools/amendguard/amendguard.py calibrate`.

The one FORMATTER-ONLY branch is `note-prose`, and it is supposed to be.

### The two guards, demonstrated rather than asserted

Each mutation was applied to the classifier half of `amendguard.py`, the named node was run,
and the RED set was read **out of pytest's output** — not out of a grep over the source
(RB-P48).

<!-- provenance: value=6 failed, 17 passed; commit=da5f073 plus this commit's working tree; command=mutate DEFAULT_KIND to pointer:P3, then .venv/bin/python -m pytest runtime-py/tests/test_amendguard.py -q -->
| mutation | branch | RED | the named node among them |
|---|---|---|---|
| `DEFAULT_KIND = "record"` → `"pointer:P3"` | closed list | 6 | **`test_an_unlisted_construct_falls_through_to_record`** |
| `isolation = "sole" if (…) else "mixed"` → `"sole"` | its-own-commit | 2 | **`test_a_pointer_fix_bundled_with_anything_else_is_pointer_not_isolated`** |
| `"rewritten in place at line "` → `"CLOBBERED IN PLACE at line "` | note prose | **0** | — |

The third row is the one that matters as much as the first two. It rewrites a message, it
changes the checker's printed output, and **it turns nothing red** — which is what N-12's
rule requires and what a suite that asserted on prose would have counted as coverage.

---

## 8. The first field run, and what it found

`python tools/amendguard/amendguard.py check . 5845698..HEAD tools/amendguard/ledger.json`
over `feat/instrument-hygiene`, at the commit that ships this document:

```
VERDICT commit=545805980 path=docs/eval-data/2026-08-19-instrument-hygiene-plan.md classify=new-file isolation=mixed derivation=absent verdict=STAMP-MISSING
VERDICT commit=da5f07321 path=docs/eval-data/2026-08-19-instrument-hygiene-plan.md classify=append isolation=mixed derivation=absent verdict=STAMP-MISSING
SUMMARY rows=2 ok=0 red=2 broken=0 merges=0 unmeasured=0
```

**Nine unstamped gate expectations across the two commits**, and this is the intended
result rather than a surprise: Amendment 1 §5 asked for a checker that catches the defect
found in its own design document, and the defect was a bare `932 passed, 2 xfailed` with no
commit beside it. **Nothing is retro-edited to make this go green.** The plan is amend-only
and it is not this document's business to amend it.

Two of the nine are quotations discussing the defect rather than asserting a gate result
(one quotes the brief, one quotes §1.6 in the act of withdrawing it). The rule is mechanical
and flags them anyway; the safe direction is to over-report, and the imprecision is recorded
here rather than special-cased in the checker.
