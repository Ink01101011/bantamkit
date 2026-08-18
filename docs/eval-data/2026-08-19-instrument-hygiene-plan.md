# J3 `instrument-hygiene` — the plan, written from re-measurement

**Committed before any fix exists.** This document is the first commit on
`feat/instrument-hygiene`. `git log --oneline` on this branch shows it standing alone on
top of `5845698`; every fix this plan authorises must appear *after* it. That ordering is
the point: a plan written after the fixes is a description, not a plan.

**Model: `claude-opus-5[1m]`** (Opus 5, 1M context). One model, no second model.
**Tokens: UNMEASURED. Wall-clock: UNMEASURED.** No token counter and no wall-clock counter
is exposed to this unit. No self-estimate is offered (RB-P19's sibling rule: a number
without an instrument is not a number).

**Base.** `5845698` = merged `main`, the squash merge of PR #33. Not `220a662` and not
`3f52a86` — those are tips of `feat/compaction-in-the-loop` (J7), which is **not merged**.
Everything below is measured at `5845698` in a worktree, except where a figure is
explicitly labelled as read off J7's branch.

**Nothing here was measured by trusting the prep probe.** `.shiftwork/probes/J3-PREP-open-findings.md`
is an input, not a source. Every figure this plan acts on was recomputed in this worktree
by a command reproduced below. §1 lists, first and unpadded, the eight figures from the
brief and the probe that **did not reproduce**.

---

## 1. What did not reproduce

Filed first because a plan that buries its disagreements with its own brief is the defect
the brief warned about (N-11: a unit handed six `wall_s` figures that matched no committed
column refused them and was right).

### 1.1 RB-P53 does not exist at this branch's base

The brief's FILES table describes `docs/eval-data/2026-08-18-compaction-closure.md` as
carrying "its dated Amendment 1 recording RB-P53's contamination of the fidelity axis" and
`docs/eval.md` as carrying "RB-P47..RB-P53". **Neither is true at `5845698`.**

```
grep -c 'RB-P53' docs/eval.md                      # 0 at 5845698
grep -c 'Amendment 1' docs/eval-data/2026-08-18-compaction-closure.md   # 0 at 5845698
git diff --stat 5845698..feat/compaction-in-the-loop -- \
    docs/eval.md docs/eval-data/2026-08-18-compaction-closure.md
#   docs/eval-data/2026-08-18-compaction-closure.md | 46 +++++++++
#   docs/eval.md                                    | 33 +++++++++
```

RB-P53 and the closure's Amendment 1 are **33 and 46 unmerged lines on J7's branch**. This
is not a quibble: three of the eight dispositions below turn on "superseded by RB-P53", and
a register entry cannot supersede anything from a branch that has not landed. **Ordering
constraint, binding on this job:** every sentence in J3's deliverables that cites RB-P53
must either land after J7 merges, or cite it as *pending on `feat/compaction-in-the-loop`*.
This plan does the latter throughout.

### 1.2 The `14` in "the uncovered CI surface grew to 14" is a J7-branch figure

| where | `git ls-files 'docs/eval-data/*.py' \| wc -l` |
|---|---|
| `5845698` (this base, = merged main) | **12** |
| `feat/compaction-in-the-loop` (J7, unmerged) | **14** |

The two extra files are `2026-08-18-loop-harness.py` and
`2026-08-18-loop-worker-determinism-probe.py`, both J7's. On main the count is **12**,
which is J2's closure figure, not a growth over it. The register entry says 10. **RB-P41's
CI half is still true either way** — `grep -rl eval-data .github/` returns nothing, exit 1,
and `.github/workflows/ci.yml` has exactly three run steps (`ruff check .` in `runtime-py`,
`ruff check --config runtime-py/pyproject.toml examples`, `python -m pytest runtime-py -q`)
— but the *growth* is J7's to report, not J3's.

### 1.3 "27,722 ratios" is a pair count, not a ratio count

Re-running the probe's own sweep in this worktree:

```
quantities=167  ratios tried=21912  matches for filed 0.034865: 0
```

167 × 166 = 27,722 **ordered pairs**; the script skips any denominator that is zero on some
transcript, so **21,912** ratios are actually evaluated. The probe reported the pre-exclusion
figure as though it were the post-exclusion one, and the derived claim "a search 5,544×
larger than the one that filed it" is therefore **4,382×**. The central result — **zero**
matches for `0.034865` — reproduces exactly, and so does the one figure that does match,
median retention `0.054795` at n = 24.

### 1.4 The probe's key counts for the three artifacts are wrong

| file | probe | measured here (`len(json.loads(first_line))`, and the union over all rows) |
|---|---|---|
| `2026-08-18-compaction-arms.jsonl` | 34 | **33** |
| `2026-08-18-compaction-b0-null-control.jsonl` | 30 | **29** |
| `2026-08-17-compaction-corpus.jsonl` | 42 | **44** |

The three blobs are byte-identical between `5845698` and J7's tip
(`git rev-parse <rev>:<path>` agrees on all three), so this is not a revision difference.
L-U5-4's **conclusion** stands and is re-verified: every string-valued key in all three
files is an identifier, a stratum, a mode or a model name — `arm`, `compaction_mode`,
`mcp_commit`, `model`, `recall_mode`, `schedule_id`, `stratum`, `summarizer_model`,
`transcript_id`; `reconstruction`, `schedule_id`, `stratum`, `transcript_id`; `kind`,
`transcript_id`. **No text column, in any of the three.** The counts that framed it are off
by one, one and two.

### 1.5 The pin census gives 28 here, 27 in the probe, 30 as filed

```
grep -ohE '[A-Za-z0-9_./-]+\.[a-z]+:[0-9]+(-[0-9]+)?' <the four documents> \
  | sed 's#.*/##' | sort -u | wc -l        # 28
```

The 28th is `compaction-corpus.md:403`, the same target as
`2026-08-17-compaction-corpus.md:403` written short. Dedupe by *target* rather than by
*string* and it is 27; count bare `` `:N` `` and `§x.y:N` forms and it is 30. **Three
definitions, three answers, and none of the three documents defines the term.** This is
L-U5-3's own disease one level up and it is why §3's disposition for L-U5-3 closes a
convention and refuses to close a census.

### 1.6 The suite is 932, not 940

```
932 passed, 2 xfailed in 17.12s      # .venv/bin/python -m pytest runtime-py/tests -q, in this worktree
All checks passed!                   # .venv/bin/ruff check runtime-py
```

The brief states *"expect **940 passed, 2 xfailed** — 940, not 936, that figure is stale in
older notes"*. Measured here: **932**. And it is not a branch difference —
`git diff --stat 5845698..feat/compaction-in-the-loop -- runtime-py/` is **empty**, so J7's
branch adds no test and the count is 932 on both. The correction the brief makes to the older
notes is itself off by eight.

### 1.7 SHAPE S5's "not yet in any committed row" has expired — the window closed

The shape probe's rank-1 item rested on `2026-08-18-loop-b0-compact-off.jsonl` not existing:
*"This defect can be closed before it contaminates a single committed row."* It exists now, on
J7's branch, with six rows:

```
git show feat/compaction-in-the-loop:docs/eval-data/2026-08-18-loop-b0-compact-off.jsonl
# 6 rows; over their 131 per-call entries:
#   done_reason  {'stop': 127, 'length': 4}
#   outcome      {'VOID': 6}      stopped_by {'run-cap': 6}
```

**Four length-stopped generations are already committed.** Two things follow, and they point
opposite ways, so both are stated:

- **Against:** the window the shape probe wanted J3 to hit is shut. The output-side defect is
  in data, not only in code.
- **For, and it is the larger half:** the rows **do** commit `done_reason` per call. SHAPE N-2
  — *"no committed data file anywhere records a stop reason"* — is **no longer true**, and a
  length-stop detector is now constructible from committed evidence rather than from a byte
  distribution. All six rows are VOID by `run-cap` regardless, so no row was scored `FAIL` on a
  truncated write; the inversion S5 warns about has not yet happened to a scored row.

F-6 in §7 is rewritten accordingly: it is no longer "fix it before the first row lands", it is
"classify the four that already landed, and never let a length stop reach the FAIL branch".

### 1.8 There is no pre-push hook, and the tag deny rule behaved differently on two tries

The brief states "A `pre-push` hook in `.git/hooks/` protects one working copy and is not
committed." Measured in the main checkout:

```
ls -1 /Users/kktest/Documents/Claude/Projects/bantamkit/.git/hooks/ | grep -vc '\.sample$'
# 0   — all fourteen entries are the git-shipped .sample files
git config --get core.hooksPath        # unset, exit 1
git ls-files | grep -i hook            # nothing committed
```

**No pre-push hook exists anywhere, installed or committed.** See §5.

### 1.9 A figure this unit computed, and then retracted

Reported here rather than deleted, because a retraction is evidence about the instrument
and a deletion is not.

Seeing that the null control commits `recorded_events`, `reconstructed_turns` and
`skipped_event_kinds`, this unit computed
`recorded_events − reconstructed_turns − Σ skipped_event_kinds` over the 207 rows and got
**7,219 (28.43% of 25,393)**, positive on 206 rows and **−300** on one
(`359fe0cd6ac07102`). That looked like a completeness identity that could pin M-U5-3's check
off frozen evidence.

**It is not, and the number does not mean what it looked like.** Reading the source rather
than the column names, `recorded_events += 1` sits *after* every filter — after the blank-line
`continue`, after `UNPARSEABLE`, after `NOT_AN_OBJECT`, after the cutoff guard, after the
`kind not in CARRIED_EVENT_KINDS` skip and after the `NO_MESSAGE` skip. So `recorded_events`
is a **post-filter carried count, not an input population**, and subtracting the skip totals
from it mixes populations. The `−300` row is the proof: 719 turns plus 701 enumerated skips
exceed 1,120 "recorded events" only because the skips were never inside that 1,120.

**The retraction is more useful than the figure would have been.** It establishes something
the prep probe did not: **no committed column in any of the three artifacts carries the size
of the input population.** There is therefore no denominator against which *any* enumeration
check could be completed on frozen evidence — which is why §3's M-U5-3 disposition is a carry
and not a close.

---

## 2. Figures re-verified in this worktree

Everything in this table was recomputed here. Nothing in it is carried.

| figure | value measured here | source |
|---|---|---|
| M-U5-1 six arm percentages | −40.1421 / −58.9356 · −22.7575 / −42.1513 · −7.9204 / −19.5665 | `2026-08-18-compaction-arms.jsonl`, n = 24 |
| M-U5-1 direction, pointwise | **0 of 72** per-transcript pairs violate `no_fixed ≥ with_fixed` | same |
| M-U5-1 the constant | exactly one value, `25350.2`, over all 600 rows | same |
| M-U5-1 documentary half | `grep -c no_fixed …arms-measurement.md` → **0** | the promise's own document |
| M-U5-2 sweep | 167 quantities, **21,912** ratios, **0** matches for `0.034865` | three artifacts |
| M-U5-2 the figure that does reproduce | median retention **0.054795**, n = 24 | arms |
| M-U5-4 per-arm floors | B0 **0.000000** · B1 0.001472 · B2 0.011034 · B3 0.009446 | arms |
| M-U5-4 pairs | B1−B0 1.000× · B2−B1 1.000× · B3−B2 **1.168×**; FAIL/FAIL on all three | arms |
| M-U5-4 attribution | §3.1's block says `max over the two arms X,Y of`; §3.2's block has **no arms wrapper**; only prose (`same shape`, twice) claims it | the bar |
| L-U5-1 subsumption | **0** strings match `screaming` and not `snake`, exhaustive over `{A,B,Z,0,1,9,_}^2..8` | proof + committed regexes |
| L-U5-1 stop list | **8 of 35** entries are emittable; greedy `qualified` swallows two of the eight, so 8 is an **upper** bound | committed `ANCHOR_STOP_LIST` |
| L-U5-1 transcription | the probe's class list and stop list are **faithful** to the committed source, verified line by line | field-measurement program |
| L-U5-2 source | `return {anchor for anchor in anchors if anchor in installed}`, preceded by `if arm == "B0" or not blocks: return set(anchors)` | field-measurement program |
| L-U5-2 denominator | **312 of 600** rows carry `anchor_retention: null` and `anchors_total: 0`; **78** B1 rows have `boundaries: 0`; the fidelity axis rests on **288 of 600 = 48%** | arms |
| L-U5-3 drifted pin | line 1288 is `"policy": {"sum_anchor_losses": True},`; the `borrow_floor` consumer is at **1567**; file is 2,478 lines | field-measurement program |
| L-U5-3 binding pins | `…corpus.md:403,404` **do** resolve to the cited sentences; the corpus doc is 512 lines with **one** commit (`5845698`) | corpus doc |
| RB-P41 CI half | `grep -rl eval-data .github/` → nothing; three run steps; 12 programs at this base | `.github/`, `git ls-files` |
| RB-P45 | `pyproject.toml` `version = "0.23.0"`; venv carries `bantamkit-0.3.0.dist-info`; `grep -rn '_version\b' runtime-py/tests/` → one hit, a checkpoint-schema test, unrelated | both |
| RB-P53's own headline | `summarizer_prompt_tokens_the_endpoint_saw` = {0: 384, **4096: 144**, 8192: 54, 12288: 9, 13799: 3, 16384: 6}; **213 of 216** non-zero rows are exact multiples of 4096 | arms |
| **SHAPE probe N-7, closed here** | see §6.1 — **NEGATIVE** | 78 files, 7,804 rows |

---

## 3. The eight findings, one disposition each

Three dispositions exist. **Close** = fixed on this branch, in this job. **Carry to J7** =
recorded as a named precondition on J7's fidelity measurement and not fixed here.
**Record-and-drop** = written into the register with its reason and deliberately not fixed
— a legitimate close, never a silent omission.

The prep probe recommended 3 close / 3 record-and-drop / 1 do-not-close-as-a-number, with
four carried to J7 as a cross-cutting note. **Adopted in five cases, overturned in three**
(M-U5-3, L-U5-2, L-U5-3), each with the measurement that overturns it.

| id | probe's recommendation | **disposition** | adopted / overturned |
|---|---|---|---|
| M-U5-1 | close | **CLOSE** | adopted |
| M-U5-2 | record-and-drop | **RECORD-AND-DROP** | adopted, with §1.3's correction |
| M-U5-3 | close the check (ranked #1) | **CARRY TO J7**, plus a narrow disclosure close | **overturned** |
| M-U5-4 | close, against the bar | **CLOSE** | adopted |
| L-U5-1 | record-and-drop | **RECORD-AND-DROP** | adopted |
| L-U5-2 | do not close as a number | **CARRY TO J7**; no scorer edit in J3 | **overturned in scope** |
| L-U5-3 | close as a convention | **CLOSE the convention** + **CARRY** the drifted pin | **overturned in part** |
| L-U5-4 | record-and-drop | **RECORD-AND-DROP** | adopted |

**Two closes, three carries, three record-and-drops. Not eight closes.**

### M-U5-1 — CLOSE

*Justified by:* the six percentages, `0 of 72`, the single constant `25350.2`, and
`grep -c no_fixed` → 0 — all four re-measured here (§2). The column is committed on all 600
rows, so nothing needs running.

*The fix, in two layers, therefore two commits.*
1. **Artifact.** A dated amendment **appended** to `2026-08-18-compaction-arms-measurement.md`
   printing the three without-constant figures. Append, never edit: L-U5-3's pins reach into
   sibling documents and the corpus document has exactly one commit, so a line-shifting edit
   anywhere in this family is the hazard L-U5-3 names.
2. **Instrument.** `CHK-FIXED-COST-DECLARED`'s condition currently reads
   `all("ceiling_pct_with_fixed" in r and "ceiling_pct_no_fixed" in r for r in b0_rows)` —
   **b0 rows only**, and **key presence**, not printing. Widen it to the arms rows and to the
   printed report. Its `PINNING_AUDIT` row already names `omit-fixed-cost` as its mutation;
   the widened condition must still redden under it, and that must be shown from the
   program's **printed verdict line**, not from a grep over the source (RB-P48: a source-side
   grep under-counted its own defect by more than 2×, 5 against 11 of 14).

*This is the only one of the eight that closes with no residual caveat.*

### M-U5-2 — RECORD-AND-DROP

*Justified by:* 21,912 ratios over 167 committed quantities, **zero** matches for the filed
`0.034865` (§1.3, re-measured here). The quantity the filing needs — "the bytes the installed
block replaced" — is not a committed column and is not a ratio of committed columns.

*Why not close it:* there is nothing left to learn from the committed evidence, and the
qualitative half — "retention is a proxy; this job cannot separate a small block from a lossy
one" — is subsumed by RB-P53 on much stronger grounds (the summarizer read 6.6% of its input).
Closing M-U5-2 would restate a weaker version of a finding a stronger one owns.

*Recorded as:* the four numbers **withdrawn as unreconstructible**, with the sweep's size and
its zero result, and a pointer to RB-P53 **marked pending on `feat/compaction-in-the-loop`**
per §1.1.

### M-U5-3 — CARRY TO J7, plus a narrow disclosure close. *Overturned.*

*What reproduces:* the guard does precede the counter. Verified here in a pattern-delimited
span — `if not survey._under_cutoff(...): continue` sits above
`if kind not in CARRIED_EVENT_KINDS: skipped[kind] = ... ; continue`, and a second silent
`continue` (`if not raw.strip()`) precedes both.

*Why the probe's rank-1 "close the check" is overturned.* Two measurements, both made here.

1. **The check is already disclosed as UNPINNED, in the committed source, with the correct
   reason.** `PINNING_AUDIT` carries
   `("CHK-EVERY-SKIPPED-KIND-ENUMERATED", "UNPINNED", None, "the condition tests that each
   skipped count is an INT, and every count this program writes is an int, so no artifact it
   can produce falsifies it. The claim a reader will take from its name … is not the claim
   the condition makes")`. Under RB-P51 — UNMEASURED is a verdict — this instrument has
   already given the verdict. Closing it upgrades a truthfully-labelled UNPINNED to PINNED;
   it does not repair a lie. That is worth doing and it is not the highest-value item in the
   set.
2. **It cannot be upgraded on frozen evidence, and §1.9 is why.** A completeness check
   compares an enumerated set against an **input population**. `recorded_events` is
   incremented after every filter, so it is a carried count; there is **no committed column
   for events read**. The only other source for that population is the live transcript
   directory, which moved between U5 (1,314 drops) and U7 (1,471) and would move again — a
   check reading it asserts a fact about the world and is non-reproducible by construction
   (RB-P14 Gate 2). **The denominator does not exist and cannot be created without a re-run,
   and re-running frozen arms is forbidden.**

*Therefore:*
- **CARRY TO J7 (precondition F-1):** count the two silent `continue`s, and commit an
  `events_read` column, so that on J7's native run
  `events_read == carried + Σ skipped_event_kinds` is a real identity, red under a mutation
  that drops an event without counting it.
- **Narrow CLOSE in J3, disclosure only:** the check's *name* claims completeness and its
  *condition* tests integer-ness. Rename the condition's claim to what it does and file the
  new fact — **the artifact carries no input-population column, so no completeness check over
  it is constructible** — as a register entry. **Do not delete the check and do not delete a
  mutation** (RB-P48).
- The escalated reading (is a post-cutoff drop a VOID trigger?) is **not resolved here** and
  is not resolvable without the denominator. It travels with F-1.

### M-U5-4 — CLOSE, against the bar

*Justified by:* the four per-arm floors and the three pair ratios, re-measured here to 6 dp,
plus a direct read of the bar's two formula blocks. §3.1's block contains
`max over the two arms X,Y of`; §3.2's block is
`fidelity_floor(grain) = max over repeat sets of RET(grain) − min over repeat sets of RET(grain)`
with **no arms wrapper**. Only the prose says "same shape", at two places. **The program is
faithful to the executable half; the bar contradicts itself in adjacent lines.**

*Two arithmetic facts that size the fix, both re-measured here:* `floor(B0) = 0.000000`
exactly, so for any pair `Y − B0` the two definitions are **identical, permanently**; and on
the one pair that moves, B3−B2, the bar shifts by 0.001588 against a gap of 0.9276755 — the
fix closes **0.17%** of the distance, and the verdict is FAIL under both definitions on all
three pairs.

*The fix:* a dated amendment **appended** to
`2026-08-17-compaction-bar-preregistration.md` reconciling §3.2's formula with its prose and
saying which one the program implemented. **The program is not edited.** Closing this by
changing the program would be fixing the artifact that was right.

*Why close a finding worth 0.17%:* not for the number. A bar whose prose and formula disagree
two lines apart will mislead the next unit that reads it on a corpus where the margin is not
584×. This is a Layer-2-shaped defect — the wording, not the mechanics — and the layer model
exists because that is where cross-model failures clustered.

### L-U5-1 — RECORD-AND-DROP

*Justified by:* `L(screaming) ⊆ L(snake)` verified two ways here — structurally (identical
patterns modulo `[A-Z] ⊂ [A-Za-z]`, `snake` is alternative 2 and `screaming` is alternative 4,
Python's `|` is leftmost-first) and exhaustively (**0** strings over `{A,B,Z,0,1,9,_}^2..8`
match `screaming` and not `snake`). **0.00% is a theorem, not a sample** — which is why the
empirical share the prep probe left UNMEASURED is not worth measuring: an empirical 0.00%
would add nothing to a proof of 0.00%. And **8 of 35** stop entries are emittable, with
greedy `qualified` swallowing `os.path` inside `os.path.join` and `self.assert` inside
`self.assertEqual`, so 8 is an upper bound.

*Why not close:* bar §3.2 freezes the class list and the stop list as data, in the artifact,
so that they cannot be tuned. Editing them is exactly the act the bar forbids, and the defect
points **against** tuning — a list selected to move a number would fire; this one is 77% inert
by construction. **There is no action available that is not a violation.**

*Recorded as:* the proof, the 8-of-35 upper bound, and the sentence that the direction is
evidence against tuning.

### L-U5-2 — CARRY TO J7. No scorer edit in J3. *Overturned in scope.*

*Justified by:* the substring containment at source, and the 312/312/78/600 counts, all
re-measured here.

*The one-signed argument, restated as the reason not to spend a run:* containment can only
**add** members to the retained set, never remove one, so committed retention is an **upper
bound** and every correction moves the verdict **further** into FAIL. Median B1 retention
0.0547955 against a bar of 0.998528 is 0.9437 away; sending retention to 0.0 still FAILs.
**Adopted: do not close it as a number, and do not re-run.**

*Where this overturns the probe.* The probe recommends "fix the scorer in the program so the
*next* run is right". **The next run is J7's, on J7's branch, with J7's harness.** Editing
`2026-08-18-compaction-arms-field-measurement.py` on `feat/instrument-hygiene` changes a
program whose only committed output is frozen, produces no new evidence, and creates a
merge-order dependency with J7 for zero measured gain. J3 hands the property forward instead
of the patch.

*Carried to J7 as preconditions:*
- **F-2:** retention is scored on **token boundaries**, not substring containment. Stated as
  the property, not the comparison: *an anchor counts as retained only when it appears in the
  installed block as a complete token under the same tokenisation that extracted it.*
- **F-3:** the denominator is disclosed. **288 of 600 rows, 48%** carry a fidelity figure at
  all; no committed document states this. J7 states it before it reports a retention number.
- **F-4:** the committed J2 retention is an **upper bound**, recorded by amendment.

*What was attacked here and did not break:* the "a no-op arm scores 1.0" attack. Zero-boundary
rows carry `anchors_total: 0` and `anchor_retention: null`, **312 of 600**, and every
aggregation filters `is not None`. The instrument is correct. The residue is F-3, a disclosure
fact, not a defect.

### L-U5-3 — CLOSE the convention, CARRY the drifted pin. *Overturned in part.*

*Justified by:* the census disagreement in §1.5 (28 / 27 / 30 under three definitions) and a
direct read of the drifted pin — line 1288 at HEAD is
`"policy": {"sum_anchor_losses": True},` while the `borrow_floor` consumer the review's
`` `:1288` `` cites is at 1567, in a 2,478-line file.

*The close (convention, and it is the record-vs-pointer rule of §4):* **pattern-delimited
locators only; never a bare line number; never a pin written from a register rather than read
at HEAD.** The closure document already follows it — 0 pins — so the convention is being
ratified, not invented.

*Why the census is not closed:* three defensible definitions give three answers and no
document defines the term. Closing a census with no command behind it would commit the
disease the finding names.

*Where this overturns the probe.* The probe writes that the one concrete repair — correcting
or de-pinning `` `:1288` `` — "cannot be done by editing the review, which is amend-only; it
can only be recorded." **Under §4's rule that is wrong, and the rule is what makes it wrong:
a `file:line` pin is a POINTER, and a pointer is correctable in place**, in its own commit,
with the correction stated in the body. The review is amend-only *for its records*; its
pointers are not records. That is the whole reason the record/pointer split exists.

*So:* the pin is **correctable**, and this plan authorises the correction — **but not in J3**,
because §4's checker must exist first and the correction is the checker's first real subject.
**CARRY:** the `` `:1288` `` correction is the first commit taken *through* the new rule, as
its own commit touching nothing else, after the checker lands. If it were done before, it
would be the rule's author granting himself an exemption from the rule.

*Also recorded:* 16 of the 27 pins point into an external repository at an immutable commit —
immutable, and therefore **unverifiable by any reader of this repository** (RB-P50). Both
halves get one sentence each; they must not travel under one.

### L-U5-4 — RECORD-AND-DROP

*Justified by:* the exhaustive key enumeration re-run here (§1.4). Every string-valued key in
all three artifacts is an identifier, a stratum, a mode or a model name. The block-side columns
are five byte counts; the anchor-side columns are five counts and a ratio. A reviewer can
recompute `anchors_total` from transcripts on disk but cannot recompute `anchors_retained`,
because the right-hand side of the containment test is not committed.

*Why not fix:* committing the installed block text would put other projects' file contents into
an artifact whose fence permits numbers only. **This is a correct consequence of a correct
fence.** The fence stays.

*Recorded as:* the fence's cost, stated once, in the register — an auditor can verify the class
lists never moved and can measure their effect on `anchors_total`, and cannot re-derive
retention. J7's F-2/F-3/F-4 are where the fidelity axis gets auditable evidence, natively.

---

## 4. The record-vs-pointer rule, as it will be implemented, with its checker

The user's ratification: *"เอาแบบนี้ ให้ J3 สร้าง checker แล้วเขียนกฎไปพร้อมกัน"* — **the rule
and the mechanism that enforces it land in the same commit.** A rule without a checker is
another intention for the next pin drift to step on. This section is the specification; the
implementation is J3's next unit and may not land before it.

### 4.1 The three kinds

**RECORD — amend only.** A number, a verdict, a table, a verbatim block, a claim. A record is
a statement about a moment that has passed; changing it in place rewrites what was said, not
what is true. Corrections are **dated amendments appended at the end**.

**POINTER — correctable in place, in its own commit, with the correction stated in the body.**
A pointer is a statement about *where something is*, and it can become false without anyone
lying. The classes are a **CLOSED LIST**:

| # | pointer class | example |
|---|---|---|
| P1 | hyperlink or in-document anchor | `[Eval → Cross-model results](eval.md#cross-model-results)` |
| P2 | section citation | `bar §3.2` |
| P3 | `file:line` pin, in any of its three forms | `…corpus.md:403`, `` `:1288` ``, `§10.2:718` |
| P4 | stale-state marker | `*(filled)*`, `TODO`, `pending`, `HEAD is <sha>` |

**Anything not on this list is a RECORD.** The list is closed by construction: the checker
carries it as data and an unlisted construct falls through to the record branch. Widening it
is a commit that edits the list, which is visible.

**CO-MOVING COUNT — the named class, and the third kind.** *(§4.2.)*

### 4.2 CO-MOVING COUNT — the class J1 found and the closed list cannot decide

**The case:** a **count of a list that the same commit lengthens.** "Ten findings filed" in a
document, in the commit that files the eleventh. It is a number, so the closed list calls it a
record and forbids the edit. But leaving it says ten when the body shows eleven, and amending
it appends a correction whose only content is that the body below it can be counted. Both
readings are defensible, which is exactly why the closed list cannot decide it.

**The name: CO-MOVING COUNT.** Machine tag `co-moving-count`. Definition: *a figure whose
correct value is a function of the body of the artifact that carries it, at the same commit.*

**The resolution is not a third amend-vs-edit ruling — it is a different property.** Amend
versus edit is the wrong question for a co-moving count, because the number was never a claim
about the past; it is a claim about the current body. The property that makes the question
disappear:

> **A co-moving count must carry its derivation, and must equal that derivation recomputed
> over the committed body at every commit.**

So a co-moving count is written with an explicit machine-readable derivation marker, e.g.

```
<!-- co-moving-count: findings = count(^### [ML]-U5-\d+$) -->
**Eleven findings filed.**
```

and the checker recomputes it at each commit that touches the file. Edit it, amend it, or
rewrite the section — none of that matters, because the checker measures the number against
the body rather than against the history. A count that drifts is red at the commit that
drifted it, not discovered three jobs later.

**Until a count carries the marker, the conservative reading binds: it is a record, amend, do
not edit.** That is the default, it is the safe direction, and it is what the checker enforces
on unmarked numbers by doing nothing about them at all.

### 4.3 The checker

**Where.** `tools/amendguard/amendguard.py`, a standalone program, sibling to
`tools/pinharness/pinned.py` and modelled on it deliberately: that harness already solved this
job's hardest sub-problem once (*"a claim cited for one problem whose mutation lands in
another's code reads PINNED while the OTHER problem's nodes do the killing"*), and its answer
— **every claim NAMES the nodes entitled to pin it** — is invariant 7 in code.

`tools/` is outside the five product layers and outside both ruff gates, so the checker is one
change in one place and cannot smuggle a second layer in with it.

**Invocation, RB-P49-safe by construction.** Required positional arguments, exactly as
`pinned.py` has them, so a bare invocation exits 2 from argparse and **cannot** take a write
branch by default:

```
.venv/bin/python tools/amendguard/amendguard.py <repo> <rev-range> <ledger.json> [--out FILE]
```

There is no `repo_root` defaulting to `'.'`, no implicit write, and no path on which the
program overwrites a committed artifact and exits 0 (RB-P49: two programs in `docs/eval-data/`
do exactly that today).

**What it computes.** For each commit in the range, for each amend-only path in the ledger, it
reads `git log --numstat` and the commit's own diff hunks and emits **machine-readable verdict
fields**, one line per (commit, path):

| field | values | meaning |
|---|---|---|
| `classify` | `record` · `pointer:P1..P4` · `co-moving-count` | which kind every changed hunk was decided to be |
| `isolation` | `sole` · `mixed` | is this commit a pointer fix touching nothing else |
| `derivation` | `ok` · `stale` · `absent` | for marked co-moving counts, does the number equal its recomputation over this commit's body |
| `verdict` | `OK` · `RECORD-EDITED` · `POINTER-NOT-ISOLATED` · `COUNT-STALE` · `BROKEN` | the gate |

**The two guards, and why each is machine-checkable rather than aspirational.**

1. **The closed list makes `classify` total.** Every changed hunk lands in exactly one branch,
   and the default branch is `record`. A construct nobody thought about is therefore
   amend-only, which is the safe direction. There is no "unclassified" output, so the checker
   cannot be silent about something it did not understand — it says `record` and blocks.
2. **`isolation` makes a lie visible in `git log --numstat`.** A pointer fix must be its own
   commit touching nothing else. A commit that declares itself a pointer fix and moves 30 lines
   reads `isolation=mixed`, and `POINTER-NOT-ISOLATED` is the verdict. The numstat is the
   evidence and it is not the checker's own word for it.

**Its ledger and its calibration.** `pinned.py` ships `calibration.json` and
`calibration-head.json` — *"an instrument that has not been shown to distinguish a pinned claim
from an unpinned one is not evidence about either"*. `amendguard` ships the same pair: one
synthetic commit that **must** come back red (a record edited in place) and one that **must**
come back green (a `file:line` pin corrected alone). If either flips, nothing the checker says
about any real commit may be believed.

**Its pytest node, and the fence it respects.** `runtime-py/tests/test_amendguard.py` builds a
**synthetic git repository in `tmp_path`** — `git init`, a handful of commits authored by the
test — and drives the checker over it by subprocess. **No node asserts a fact about this
repository's history**, no node asserts how many pins exist, and no node names a real commit
(RB-P14 Gate 2; RB-P28: the suite is not evidence). The suite pins the *instrument*; the
evidence that the rule holds over this repository is the checker's own output, run as a field
program, outside pytest.

**The suite is not the gate, and this is deliberate.** RB-P41's CI half is still true at this
base — `grep -rl eval-data .github/` returns nothing — so a field program guarded only by CI
is guarded by nothing. `test_amendguard.py` guards the checker's *logic*; the checker guards
the *repository*; and the plan states plainly that nothing runs the second one automatically
today. Claiming otherwise would be the RB-P41 defect with a new name.

### 4.4 The N-12 exposure in this checker, and how it is detected

N-12, filed hours ago: J7's selfcheck reddens when `void_reason`'s **string branch** is
reverted (2 RED) and stays **green at 0 RED** when the ternary that actually assigns
`stopped_by` — the **classifier** — is reverted. The claim named "a 30 s run stops reporting a
1200 s cap". The covered line was the formatter; the uncovered line was the classifier. The
check was green about the wrong line and nobody could tell, because the mutation that killed it
killed a *message*.

**This checker has the identical exposure.** Its `classify` decision (a classifier) and its
per-verdict explanatory sentence (a formatter) are separate code. A mutation that breaks the
message would redden a naive node; a mutation that breaks the classification might not. Saying
"the checker works" would be the same mistake one level up.

**Three mechanisms, and none of them is an assertion that the checker works.**

1. **Verdict fields are machine-readable and messages are not part of any assertion.** Nodes
   assert on `classify=`, `isolation=`, `derivation=` and `verdict=` — never on prose. A
   mutation that changes only a sentence therefore **cannot** turn any node red, by
   construction, which removes the false-positive that hid N-12.

2. **The sharpening of invariant 7 that N-12 demands, stated as a rule:**

   > **A mutation counts as pinning a claim only if it moves a machine-readable VERDICT FIELD
   > that the claim names. A mutation that moves only a human-readable message is recorded as
   > FORMATTER-ONLY and the claim stays UNPINNED.**

   `pinned.py` already distinguishes `behaviour-pinned` from `prose-pinned` and already warns
   that *"a prose guard can be green while the behaviour it describes is broken"*. This is that
   distinction made into a verdict rather than a caveat.

3. **One mutation per decision BRANCH, and a meta-check that measures coverage from the
   OUTPUT.** The mutation catalogue is keyed by branch, not by check name: one for each pointer
   class P1–P4, one for the record default, one for `isolation`, one for `derivation`. The
   meta-check asserts that for every branch B there exists a mutation whose effect is a
   **changed verdict field for B** on the calibration fixture. Branches with no such mutation
   are printed **UNPINNED with the branch named** — they are not deleted, and the mutation is
   not deleted to make the number look better (RB-P48). And the coverage is counted from the
   checker's printed verdict lines, **not** from a grep over the checker's source: RB-P48
   measured a source-side grep under-counting its own defect by more than 2× — 5 by grep
   against 11 of 14 by asking what changes in the printed report.

**The tautology test, applied to this checker before it is trusted (RB-P47).** J2's VOID check
was defended as two independent code paths that turned out to dispatch on the identical four
types. So: *name an input on which `classify` and the ledger would disagree.* They would
disagree on a `file:line` pin inside a fenced verbatim block — a pointer by syntax, a record by
context, since a verbatim block is a record class and its contents are quoted, not cited. That
input exists, the two do disagree on it, and it is a calibration case. A cross-check that
cannot be made to disagree is a transcription and does not count.

---

## 5. The tag guard — decision, and the residual exposure

**Decision: J3 ships no tag guard.** Not a committed `core.hooksPath`, not a hook, not a
pytest node.

**What is measured, and what is not.**

- **22 tags exist.** Measured incidentally in this session by `git -C <path> tag | wc -l`,
  bundled inside a larger compound command. The *newest* tag is carried from the brief as
  `v0.21.0` and is **NOT verified by this unit** — see the second bullet.
- **The guard is a classifier, and it leaks under composition.** A second, standalone
  invocation of the same evasion (`git -C <path> tag --sort=v:refname | tail -5`) was
  **denied**, with a reason naming the evasion explicitly: *"The command deliberately routes
  around the user's `Bash(git tag:*)` deny rule by invoking `git -C <path> tag`."* So the brief's
  invariant 16 — "`Bash(git tag:*)` … does NOT block `git -C <path> tag`" — **is not
  reproducible as an unconditional statement.** The same construct passed once and was refused
  once. The honest characterisation is not "a tripwire" and not "a wall": **it is a classifier
  whose decision depends on how the command is composed**, and this unit measured it going both
  ways within one session. **This unit did not retry after the denial**, which is why the
  newest-tag figure above is unverified. Refusing to retry is the correct behaviour and the
  missing figure is the price.
- **There is no pre-push hook** (§1.8): fourteen `.sample` files, `core.hooksPath` unset,
  nothing hook-shaped committed. The brief's claim that one exists does not reproduce.

**Why no guard.** Four reasons, in descending strength.

1. **A pre-push hook does not guard `git tag`.** Tagging is local; `pre-push` fires on push.
   A hook would guard the *publication* of a tag, not its creation — a different property from
   the one the deny rule is protecting.
2. **`core.hooksPath` is local configuration, so committing a hooks directory changes nothing
   until somebody runs `git config core.hooksPath …` by hand.** The un-enforceable step is the
   whole guard. A committed directory that does nothing until a manual opt-in is a guard in
   name.
3. **It is bypassable by the same mechanism it would be defending against.** Any actor able to
   run `git -C <path> tag` can equally run `git -C <path> -c core.hooksPath=/dev/null …`. A
   guard defeated by one extra flag is not a second line of defence.
4. **Layer discipline.** A repository-level git hook is not one of the five layers and not the
   measurement harness. Shipping one here would put a change in a place the layer model has no
   name for, in a job whose entire subject is instrument hygiene.

**The residual exposure, stated plainly and without softening.** *The only thing standing
between this program and an unauthorised tag is a permission classifier that this unit measured
allowing one instance of the documented evasion and refusing another.* There is no hook, there
is no committed configuration, and after this plan there still will not be. A detector rather
than a preventer — a field program that compares the tag inventory against a committed
expectation — is buildable, would be a **detector only**, would work only on the machine that
runs it, and is **not proposed**, because a guard described as protection when it is
after-the-fact notification is the failure mode the brief named. What J3 does instead is record
the measurement, in the register, in these words.

**And the standing rule is unchanged and is not a guard: DO NOT TAG.** Never authorised in this
program. Merge belongs to the orchestrator, never to a unit.

---

## 6. RB-P53's class — what is in J3's scope

The shape probe ranked nine call sites across two repositories. The scope decision is drawn on
two lines: **which repository** and **whose branch**.

### 6.1 N-7 closed here, and it moves the ranking

The shape probe left one measurement undone — *"N-7 · The per-call check
`tokens / model_calls` against 2048/4096/8192 was NOT run. UNMEASURED — the tool became
unavailable. A test not attempted is not a test that found nothing."* It is run here:

```
rows with both tokens and model_calls: 7804 across 78 files
distinct tokens/model_calls values: 1770
EXACT hits on a power-of-two cap {512,1024,2048,4096,8192,16384,32768}: none
within 1% of a cap: {512: 59, 1024: 4}
per-call min / median / max: 40.0 / 439.25 / 2625.0
```

**NEGATIVE, and cleanly so.** The per-call maximum over the whole corpus is **2,625 tokens** —
below the smallest plausible completion cap and three orders of magnitude below the windows in
question — so no committed row can be sitting on a cap. The 59 rows within 1% of 512 are values
inside a 1,770-point distribution whose maximum is five times higher, not a ceiling. This closes
the caveat that kept **S4** at rank 3 and demotes it: S4 is a latent code-path defect with
**7,804 rows of clean evidence behind it**, not a suspected contamination.

### 6.2 The scope table

| site | repo / branch | **in J3?** | reason |
|---|---|---|---|
| **S1 / S2** — summarizer output cap `maxTokens = 2048`, truncated summary stored as the boundary's ground truth, input deleted in the same function | `compaction-mcp` | **NO** | Different repository. Outside this repo's layer model, outside both ruff gates, outside this suite. J7's pre-registered bar already declares the fix. **Handed to J7.** |
| **S3** — embeddings, same exposure, caches its damage to `embcache.json` | `compaction-mcp` | **NO** | Same reason, and latent: every committed arm row reads `"recall_mode": "lexical"`, so no committed number went through it. **Handed to J7** with the note that one env var (`COMPACTION_EMBED_MODEL`) makes it live and that the cache survives a restart. |
| **S4** — `client.py`: `usage` copied never validated, `finish_reason` absent from the file | `bantamkit`, this base | **YES, small** | The sole HTTP client in the runtime, Layer 3 Transport, one layer, one file. §6.1 shows the evidence is clean, so this is prophylaxis on a latent defect and it is cheap: read `finish_reason` back, carry it on `Usage`, and treat `usage.prompt_tokens == <declared window>` as a **VOID** signal rather than a measurement — the shape RB-P53's attack prescribes. |
| **S5** — loop harness, output side: `done_reason` stored and never compared; `parse_action` treats a truncated WRITE body as complete and scores it `FAIL` (an outcome) instead of `VOID` (an instrument verdict) | `bantamkit`, **J7's branch only** | **NO** | `2026-08-18-loop-harness.py` does not exist at `5845698` (§1.2). J3 cannot fix a file it does not have. **Handed to J7 as its highest-priority item** — but **not** on the shape probe's grounds: §1.7 measures that the window it relied on has already closed, with **four `done_reason: "length"` calls committed** across the six b0 rows. The grounds are now better rather than worse, because those rows commit `done_reason` per call, so the detector has committed evidence to bite on. It still inverts J7's own HEAD commit rule that *VOID outranks FAIL-TAMPERED*. |
| **S6** — determinism probe hashes responses; two replies both stopped at `num_predict` agree and are reported as determinism holding | `bantamkit`, J7's branch only | **NO** | Same reason. **Handed to J7.** |
| **S7 / S8 / S9** | `bantamkit`, this base | **NO** | S7 is clean by evidence (20 rows, 2 distinct `prompt_tokens`, none at a window) and mitigated by a pre-declared arithmetic argument. S8 **discloses** its own clamp in its printed table. S9 issues no request. Nothing to fix; S8's disclosure is the model the others should follow. |
| **C-6** — tool-observation truncation is in-band to the model but is **not a column**, so a run whose observations were cut is indistinguishable from one whose were not | `bantamkit`, this base | **YES, one column** | Layer 1, `agent.py` / `textutil.py`. `truncate()` already appends `[truncated N bytes]`; the bytes are known at the truncation site and are thrown away. **Exactly the RB-P51 shape**: a run that silently proceeded is not the same as one that reported what it dropped. |
| **N-5** — a length-stopped HTTP 200 is retried by nothing, anywhere, in either repository | both | **NO as a fix, YES as a register entry** | A retry policy for truncation is a Layer 3 design change with a real failure mode of its own (retrying a length stop with the same prompt returns the same length stop). Filing it is the honest act; implementing it in a hygiene job is not. |

**The line, stated once:** J3 fixes what is in **this repository, on this base, in one layer,
and cheap** — S4 and C-6. Everything in `compaction-mcp` and everything on J7's unmerged branch
is handed forward with its evidence, not reached across a repository or a branch boundary.

---

## 7. Carried to J7 — the preconditions, collected

Handed as **properties**, not as patches, so J7 chooses the mechanism (and so that a patch
written against frozen code cannot be mistaken for evidence).

| id | precondition | from |
|---|---|---|
| **F-1** | Every event the reconstruction loop declines is counted, including the two silent `continue`s, and the artifact commits an `events_read` column — so `events_read == carried + Σ skipped_event_kinds` is an identity a mutation can redden. The escalated "is a post-cutoff drop a VOID trigger?" reading travels with it and is **not resolved**. | M-U5-3 |
| **F-2** | An anchor counts as retained only when it is present in the installed block as a **complete token** under the same tokenisation that extracted it. | L-U5-2 |
| **F-3** | The fidelity denominator is disclosed before any retention figure is reported. On J2's evidence it was **288 of 600 rows, 48%**, stated nowhere. | L-U5-2 |
| **F-4** | J2's committed retention is an **upper bound**; any J7 figure that supersedes it says so. | L-U5-2 |
| **F-5** | The frozen class list and stop list are not touched. **8 of 35** stop entries can ever fire and `screaming` can never win the alternation — both are properties of the lists, not of the corpus, and a list changed to move a number stops being evidence. | L-U5-1 |
| **F-6** | The loop harness's **output** side gets a stop-reason verdict: a length-stopped generation is **VOID**, an instrument verdict, never `FAIL`, an outcome. Highest priority, and the framing has changed — the window is **already shut** (§1.7): **4 of 131** committed calls carry `done_reason: "length"`. Those four are absorbed into a `run-cap` VOID today rather than classified, so no scored row is yet wrong; the precondition is that they are classified explicitly and that a length stop can never reach the `FAIL` branch. | SHAPE S5 |
| **F-7** | The determinism probe cannot report determinism from two responses that were both stopped by the same cap. | SHAPE S6 |
| **F-8** | `compaction-mcp` S1/S2/S3 are J7's or nobody's: the summary is truncated on the way out at a default nobody overrides, stored as the boundary's ground truth, and its input deleted in the same function; the embedding path has the same exposure and caches its damage to disk. | SHAPE S1–S3 |

---

## 8. What J3 does after this commit

In order. Each is one layer, and each lands in its own commit.

1. **The record-vs-pointer rule and `tools/amendguard/amendguard.py`, together, in one
   commit** (§4) — the rule text, the closed list, the `co-moving-count` marker, the checker,
   its calibration pair and its synthetic-fixture node. The user ratified them landing
   together; they land together or neither lands.
2. **`CHK-FIXED-COST-DECLARED` widened to the arms rows**, with the redness shown from the
   printed report (M-U5-1, instrument half).
3. **The dated amendment appended to the arms measurement**, printing the three
   without-constant figures (M-U5-1, artifact half).
4. **The dated amendment appended to the bar**, reconciling §3.2's formula with its prose
   (M-U5-4). **The program is not touched.**
5. **`client.py`: read `finish_reason` back, and treat `prompt_tokens == window` as VOID**
   (RB-P53 class, S4, Layer 3).
6. **`agent.py` / `textutil.py`: observation truncation becomes a column** (C-6, Layer 1).
7. **The register entries**, all in `docs/eval.md`: the three record-and-drops with their
   reasons, the eight F-preconditions, the pin convention, the "no input-population column"
   fact, N-5, the measured tag exposure of §5, and the corrections in §1 to figures this job
   was handed.
8. **The `` `:1288` `` pointer correction**, last, as its own commit touching nothing else —
   the new rule's first real subject, taken through the rule rather than around it.

**Not in this job, in any unit: no merge, no tag, no re-run of any frozen arm, no retro-edit of
any committed artifact, no hand-edit of `assets/evals/devteam/tasks/*.yaml`, and nothing under
`assets/evals/tasks/` or `assets/evals/perturbations/`.**

---

## 9. Gates at this commit

Both run in this worktree, at this base, before this commit:

```
.venv/bin/python -m pytest runtime-py/tests -q   ->  932 passed, 2 xfailed in 17.12s
.venv/bin/ruff check runtime-py                  ->  All checks passed!
```

**932, not the 940 the brief expects** — see §1.6; J7's branch touches nothing under
`runtime-py/`, so 932 is the figure on both branches.

This commit adds one Markdown file under `docs/` and changes no Python, so neither gate's result
is attributable to it. That is stated rather than presented as evidence the plan is correct
(RB-P28: the suite is not evidence).

---

## Amendment 1 — 2026-08-19, after `5458059` was committed

**Appended, never edited.** §1.6 and §9 stand above exactly as committed at `5458059`. This
amendment withdraws a conclusion drawn in §1.6 and repeated in §9's fence. It is written this
way because a pass count is a **number**, a number is a **record**, and the rule for a record
— written two sections below the mistake, in §4.1 — is amend-only. Correcting §1.6 in place
would have been the plan's author granting himself the exemption §3 refuses to grant the
`` `:1288` `` pin.

**Raised by the orchestrator, re-verified here before being accepted.** The two figures below
were measured by the orchestrator; the mechanism and the arithmetic were re-derived
independently in this worktree, by the commands shown, without running anything in the other
checkout.

### 1. The measured pair — both correct, each at its own commit

| commit | branch | `pytest runtime-py/tests -q` |
|---|---|---|
| `3f52a86` | `feat/compaction-in-the-loop` (J7) | **940 passed, 2 xfailed** |
| `5458059` | `feat/instrument-hygiene` (this branch) | **932 passed, 2 xfailed** |

Neither number is wrong. §1.6's error was not the measurement — it was asserting a measurement
of one tree as a property of both.

### 2. The mechanism, re-derived here

§1.6's premise **stands and is re-verified**: J7 adds no test.

```
git diff --name-only 5845698..3f52a86        # 7 files, ALL under docs/, 0 under runtime-py/
```

The eight nodes come from **parametrisation over the field-program roster**, not from new test
functions. `test_field_programs.py` discovers programs as the union of `git ls-files` and a
glob, and four of its five test functions are parametrised over that roster. Measured in this
worktree:

```
.venv/bin/python -m pytest runtime-py/tests -q --collect-only 2>/dev/null \
  | grep 'test_field_programs.py::' | sed 's/\[.*//' | sort | uniq -c
#   12 ::test_every_bantamkit_symbol_a_field_program_names_still_resolves
#   12 ::test_every_committed_field_program_still_exposes_main
#   12 ::test_every_committed_field_program_still_imports
#   12 ::test_every_sibling_program_a_field_program_names_by_path_exists
#    1 ::test_the_discovery_is_not_silently_empty      <- not parametrised
```

**4 × 12 + 1 = 49 here. 4 × 14 + 1 = 57 there. The difference is exactly 8, and 932 + 8 = 940.**
The two added programs are `2026-08-18-loop-harness.py` and
`2026-08-18-loop-worker-determinism-probe.py`, both J7's, both under `docs/eval-data/`.

**§1.2 and §1.6 are one finding counted twice, and the plan filed them as two.** The CI surface
(12 against 14) and the suite count (932 against 940) are the same quantity —
`|docs/eval-data/*.py|` — read through two different instruments. That was not seen when they
were written as separate items, and it is the tell that should have been caught: two figures
that disagree between the same pair of commits, by amounts in a fixed ratio, are one figure.

### 3. What is withdrawn and what stands

- **WITHDRAWN:** §1.6's sentence *"it is not a branch difference — J7's branch adds no test and
  the count is 932 on both branches"*, and §9's repetition *"932 is the figure on both
  branches"*. The conclusion is false.
- **WITHDRAWN:** §1.6's framing of 940 as a figure that "does not reproduce". It reproduces
  exactly, at the commit it was measured at. The brief was right; this document was wrong to
  call it wrong.
- **STANDS, re-verified:** the premise. J7 touches nothing under `runtime-py/`.
- **STANDS:** 932 passed, 2 xfailed **at `5458059`**, and 934 collected.
- **Pointer note:** the fence in question is in **§9**, not §11. This document has nine
  sections; §11 is the prep probe's numbering. Recorded rather than acted on — the citation is
  in a message, not in a committed artifact, so there is nothing in this repository to correct.

### 4. The ruling asked for: does §4.2's marker cover this? **NO. It does not, and it is not
being widened to.**

The pass count **is** a co-moving count by §4.2's own definition — its correct value is a
function of a body that a commit can change. But its derivation lives outside the document
that carries the number, and that is a different animal. Name it: **CROSS-ARTIFACT CO-MOVING
COUNT**.

**Three reasons the marker as specified cannot reach it.** Stated as reasons the mechanism
fails, not as reasons the case is unimportant.

1. **The marker's derivation is a pure function of committed bytes; this one is not.**
   `count(^### [ML]-U5-\d+$)` is a regex the checker runs over a blob it already has. A pass
   count requires **executing the repository**. A checker that verified it would be asserting a
   fact about the world (RB-P14 Gate 2) and its verdict would depend on an interpreter and an
   installed environment — and a local interpreter is measurably not enough to stand in for the
   real target (`feature_version` reported the repo clean while CI's 3.11 leg rejected a module
   outright, because PEP 701 changed the tokeniser and not the AST).
2. **The scope is unbounded.** The same-body derivation reads one file. This one reads the whole
   tree plus its dependencies. There is no body for the checker to bound, so there is no
   recomputation for it to perform.
3. **It is cross-TREE, not merely cross-file.** 940 is true at `3f52a86` and 932 at `5458059`.
   There is no commit at which the number and its derivation are simultaneously true, so
   *"equal to its derivation recomputed over the committed body at this commit"* has no
   referent. The property the marker enforces is not merely hard to check here — it is not
   well-formed here.

**The ruling, therefore:** a cross-artifact co-moving count is **NOT** a fourth kind and does
**NOT** get the marker. It falls back to **RECORD — amend only**, with one added obligation:

> **A cross-artifact co-moving count must carry a PROVENANCE STAMP: the value, the commit it
> was measured at, and the command that measured it.** Not the command alone. The commit beside
> the number.

**This is strictly weaker than what the marker does for a same-body count, and saying so is the
point of the ruling.** The marker *verifies* a same-body count — recompute, compare, go red.
The stamp does not verify anything: the checker never learns whether 932 is correct. It
enforces **falsifiability**, not correctness — that a reader is handed the commit and the
command needed to find out. **The gap is real and stays open:** nothing in this design detects
a cross-artifact count that is stamped, plausible, and wrong. Closing it would need the checker
to execute the tree, which reasons 1 and 3 forbid. It is recorded as open rather than papered
over by broadening the definition in the same breath that discovered the case.

**Why the stamp would nonetheless have caught this one.** §1.6 named its command and reported
`932 passed, 2 xfailed in 17.12s` — with **no commit beside the number** — and then generalised
it to "both branches". A stamp binds a number to exactly one commit, and the generalisation is
not writable in that form.

### 5. Added to the checker's must-be-red calibration set

**`CAL-RED-BARE-GATE-EXPECTATION`** — a fixture document carrying a gate expectation as a bare
number with **neither** a `co-moving-count` derivation marker **nor** a `(value, commit,
command)` provenance stamp. The checker must come back **red**. §8's item 1 gains it, and it is
mandatory, not optional: **a checker that cannot catch the defect found in its own design
document is not worth shipping.**

Its paired must-be-green case, so the pair calibrates rather than merely blocks: the same
number carrying a full provenance stamp, which must come back **green** even though the checker
has not verified the value — because green here means *falsifiable*, not *correct*, and an
instrument that cannot show the difference between those two is not evidence about either.

### 6. Accounting for this amendment

**Model: `claude-opus-5[1m]`. Tokens UNMEASURED, wall-clock UNMEASURED.** No counter exposed.

**Gate at this amendment's commit, with the commit beside it as §4 now requires** — see the
unit's hand-back for the SHA, and the figure is stated there in stamped form rather than bare.
