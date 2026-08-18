# Closure of job `compaction-measured`: what was measured, at what n, and what is still open

**Dated 2026-08-18. U7 of job `compaction-measured`. Status: CLOSED AS A RECORD, NOTHING
FIXED.**

This unit records. It closes no finding, fixes no defect, re-runs no arm, re-tunes
nothing, and regenerates nothing. U5's **four Majors and four Lows are still open** and
they are written down here with a command and an attack direction each — including the
three Majors and four Lows that U5 filed with no command, for which the commands are
supplied here for the first time (§6, and RB-P52 in `../eval.md`).

Every figure below carries its **n**. Where two figures are not comparable they are not
put in one sentence. Where a figure could not be reproduced from committed evidence it
says so rather than being repeated.

---

## 0. The headline, per stratum, with n on every figure

**Never pooled.** The user's ruling, in their words: *"ห้าม pool เป็นเลขเดียว"*
(Amendment A).

### Stratum A — subagent sidechains

Corpus **n = 206**. Declared hash-order prefix sample **n = 50**. Of those 50, **26 have
zero boundaries in B1** and their B1 rows are bit-identical to B0 on **all 22 outcome
columns**, so the arms' informative width is **n = 24**.

| pair | conditionality | median Δ, **n = 24** | median Δ, **n = 50** | grain note |
|---|---|---|---|---|
| **B1 − B0** — `context_compact` | **UNCONDITIONAL** | **−40.1421%** of B0 | **+0.0000%** of B0 | both figures are required; neither may be quoted alone |
| B2 − B1 — trim *given* compaction | CONDITIONAL | −22.7575% of **B1** | — | never stated unconditionally |
| B3 − B2 — offload *given* compaction+trim | CONDITIONAL | −7.9204% of **B2** | — | never stated unconditionally |

The **n = 50** figure is exactly zero because 26 structural zeros own the middle of the
distribution. It is not "compaction does nothing"; it is "half this sample gave the
mechanism nothing to do". The **n = 24** figure is not the corpus either. **Both, with n
on each, or neither.**

**Without the declared fixed per-call constant**, over the same **n = 24**: B1 − B0
**−58.9356%**, B2 − B1 **−42.1513%** of B1, B3 − B2 **−19.5665%** of B2. U4 §1.2 promised
this column *"beside every with-constant one"* and never printed it for the arms; that
promise is **M-U5-1**, still open (§6), and the figures are printed here rather than
quietly supplied.

**All three pairs are TRADES. None is a reduction.** Bar §4 reserves "reduction" for a
delta at a retention within its floor with `anchors_lost_stable == 0`. Median anchor
retention on B1 − B0 is **0.0547955** at **n = 24** against a headline-grain floor of
**0.001472**, and **2,621** anchors were lost in all three repeats.

**The handed 80% target is REFUTED on stratum A, by arithmetic, before any arm ran.** R1's
zero-summary ceiling over the **n = 104** informative stratum-A transcripts is a median
**−42.6107%** with the declared constant and **−61.3963%** without it. Exactly **1 of 104**
transcripts has a *ceiling* that reaches −80% with the constant; **3 of 104** without it.
No summarizer beats a ceiling.

**The refutation survives every composition of reading A this bar's own sources permit**
(Amendment C(2)), each on its own reacher subset and each with the declared constant:
applied **−42.6107%** at n = 104; U3's recorded-peak counter **−44.2110%** at n = 94;
constant-out **−48.6465%** at n = 69; `nowPct = 85` **−49.1159%** at n = 65; the
mechanism's own `chars/4` counter **−64.1139%** at n = 15. Every one of the five reaches
−80% on exactly **1** transcript of its own subset.

### Stratum B — top-level sessions

**n = 1. UNINFORMATIVE-BY-N. No verdict is claimed and no floor is borrowed.**

Its **arms are UNMEASURED** — a different state from UNINFORMATIVE-BY-N, and kept
distinct. The declared prefix stops at rank 50 and stratum B sits at rank 51; the rule was
not amended after the fact to reach it. There is **no B1, B2 or B3 row for stratum B at
all** (all 600 arm rows are stratum A, verified).

Its R1 ceiling is **−88.9910%** with the constant and **−93.3403%** without, at **n = 1**.
That does not refute the target and is **not evidence for it**.

Its published boundary count of **12** is a **LOWER BOUND** (Amendment C(4)): 819,869 B of
content invisible to both byte counters sits in this one transcript, and the figure is
declared rather than recomputed because §9(5) forbids regenerating the row.

### The recall axis

**UNMEASURED, not "no benefit".** `rehydrated_bytes` is **0 on all 600 rows** and the
recall mode was pre-declared `lexical` before any arm ran. The path never fired. A column
of zeros from a path that never executed is not a measurement of that path.

---

## 1. The scope, stated in BOTH directions

The user's fence, frozen before any number existed: *"เฉพาะ bantamkit + ตัวเลขล้วน"*.

**What is IN.** 207 transcripts, selected by **recorded `cwd` inside the bantamkit repo**,
not by the project directory's name. Claude Code keys that directory by **launch** cwd, so
selecting by name would have taken 12 files and discarded 199 of the 211 that carry a
bantamkit cwd.

**What is OUT, and what that costs.**

| | count today | count committed by U3 | |
|---|---|---|---|
| universe (files with ≥1 `cwd`-bearing line under the cutoff) | **636** | **712** | **LIVE — see below** |
| E1 — no bantamkit `cwd` at all | **426** | **502** | out of scope by the fence |
| E2 — `cwd` spans bantamkit **and** four other project roots | **3** | **3** | the fence again; a replay would rebuild a prefix carrying other projects' file contents |
| E3 — pure but zero model calls under the cutoff | 0 | 0 | unreplayable |
| **corpus** | **207** | **207** | |

**The excluded side of the fence is live and the included side is not, and that was
measured rather than assumed.** Re-running the survey today gives a universe of 636 where
U3 committed 712 — **76 fewer files**, all of them on the E1 side — while the 207 committed
rows still reproduce on every named non-live column. That is exactly what the cutoff buys:
it does not freeze the directory, it freezes the *rows*.

```
.venv/bin/python docs/eval-data/2026-08-17-compaction-corpus-survey.py . --check
```
→ exit **0**, `OK — 2026-08-17-compaction-corpus.jsonl reproduces on every named column
that is not declared live, 207 rows.` The census block in the same output prints
`files_in_universe 636` against the committed table's 712.

**E2's cost is stated, not hidden.** The three excluded files are 93.0% bantamkit by line
and are the only long, human-driven, multi-day sessions in the universe. The user was shown
the exclusion and its cost and did not lift it.

**The corpus contains the job measuring it.** The single stratum-B transcript is this job's
own session. It is **not** excluded — excluding a transcript to make a number nicer is the
defect this program exists to avoid — it is quarantined by a stratification ruled for on
independent grounds, and its arms were never run, so no anchor from this job's own text
reaches any arm figure.

---

## 2. The dependence structure, which appears in no artifact but the review

Stratum A's 206 transcripts are **4 parent clusters sized 138 / 31 / 27 / 10**, the largest
**67.0%** of the stratum. Kish `n_eff` at ρ = 1 is **2.04** on the corpus, **2.01** on the
50-transcript sample, and **3.56** on the **24-transcript set that carries every arm
figure**.

**ρ = 1 is a pessimistic bound, not an estimate.** The true design effect is somewhere
between `n_eff` and n, and nothing in this job measured where.

**No committed artifact states any of this.** Verified at HEAD: none of
`2026-08-17-compaction-corpus.jsonl`, `2026-08-18-compaction-b0-null-control.jsonl` or
`2026-08-18-compaction-arms.jsonl` carries a parent, session or cluster column, and neither
the bar, the corpus document nor the arms measurement mentions clustering, `n_eff` or a
design effect. The only place the structure exists is
[`2026-08-18-compaction-review.md`](2026-08-18-compaction-review.md) §5.

```
.venv/bin/python - <<'PY'
import json
from pathlib import Path
for f in ("2026-08-17-compaction-corpus.jsonl",
          "2026-08-18-compaction-b0-null-control.jsonl",
          "2026-08-18-compaction-arms.jsonl"):
    r = json.loads(Path("docs/eval-data", f).read_text().splitlines()[0])
    print(f, [k for k in r if "parent" in k or "session" in k or "cluster" in k] or "NONE")
PY
grep -l "n_eff\|Kish\|design effect" docs/eval-data/2026-08-1*compaction*.md
```
→ `NONE` three times, and one filename: the review.

**The reason it is not committed is the fence, and the fence is right.** A parent-session
identifier is a filename-derived value from a live directory that also holds other
projects' sessions. Recording it would put a cross-project join key into an artifact that
is permitted numbers and statistics only. So the structure is **recorded here in prose and
not committed as a column**, and the gap is declared rather than closed.

---

## 3. The instrument, counted honestly

The acceptance run prints this about itself, and it is the deliverable:

| state | n | meaning |
|---|---|---|
| **MEASURED** | 7 | the condition reads committed measured data |
| **PINNED** | 9 | the condition reads a policy flag whose consumer moves a printed number |
| **UNMEASURED** | 1 | the instrument exists; this evidence cannot feed it |
| **UNPINNED** | 4 | nothing this program can produce turns the check red |
| **INTERNAL** | 1 | a consistency check on the audit table itself |

**PINNED 16 of 22 named checks. 1 UNMEASURED. 4 UNPINNED.**

**A closure that reported only "22 named checks, 0 red" would be the exact overclaim this
program exists to prevent**, and the number that makes it an overclaim is the 4.

**Fifteen mutations, all exit 1, and twelve move a printed figure.** The three that move
nothing but their own check line and the run's two-line banner are exactly the three
UNPINNED checks that have a mutation at all — `borrow-floor`, `pick-a-grain`,
`zero-floor-always-valid`. The fourth UNPINNED check has no mutation: its condition tests
that a skipped count is an integer, which no artifact this program writes can falsify.

```
P=docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
.venv/bin/python $P > /tmp/base.txt
for m in void-reconstruction unmodelled-content-block delete-a-committed-key \
         retune-threshold omit-fixed-cost pool-strata borrow-floor clamp-byte-columns \
         sum-anchor-losses net-summarizer-tokens all-on-vs-all-off upper-bound-as-saving \
         pick-a-grain zero-floor-always-valid fidelity-floor-wrong-grain; do
  .venv/bin/python $P --mutate $m > /tmp/m.txt; rc=$?
  n=$(diff <(grep -v '^  \[' /tmp/base.txt) <(grep -v '^  \[' /tmp/m.txt) | grep -c '^[<>]')
  echo "$m rc=$rc non-check lines differ=$n"
done
```
→ `rc=1` on all fifteen. `n=2` (the banner only) on `borrow-floor`, `pick-a-grain` and
`zero-floor-always-valid`; `n≥3` on the other twelve, up to `n=21` for `omit-fixed-cost`.

---

## 4. Gates, re-run at this HEAD rather than cited

| gate | result |
|---|---|
| `.venv/bin/python -m pytest runtime-py/tests -q` | **932 passed, 2 xfailed** |
| `.venv/bin/ruff check runtime-py tools/pinharness tools/devteam docs/eval-data` | clean |
| `cd runtime-py && ruff check .` | clean |
| `ruff check --config runtime-py/pyproject.toml examples` | clean |
| `.venv/bin/python tools/devteam/build_tasks.py check` | OK — 8 tasks |
| acceptance, no flags | **exit 0** — 22 named checks, 0 red, 1 UNMEASURED, 0 escalations |
| all 15 `--mutate` modes | **exit 1** on every one |
| corpus survey `--check` | **exit 0**, 207 rows |
| CI, at run level, on this branch | **NOT CONFIRMED — see §4.2** |

### 4.1 "All field programs exit 0" — the criterion as handed does not reproduce as a sweep

The closure criterion handed to this unit says *all field programs exit 0*. **Run as a
bare-invocation sweep over the twelve committed programs, that criterion is false, and
running it would itself mutate committed evidence.** Each program was therefore verified by
an invocation appropriate to it.

| program | appropriate invocation | rc | bare invocation |
|---|---|---|---|
| `2026-08-13-rbp16-rbp17-rbp18-survey.py` | `. ` | **0** | same |
| `2026-08-14-devteam-surface-survey.py` | `. ` | **0** | same |
| `2026-08-14-rbp28-fix-nothing-patch.py` | `"$PWD" HEAD <scratch>` | **0** | **1** — `IndexError` on `sys.argv[1]` |
| `2026-08-17-compaction-corpus-survey.py` | `. --check` | **0** | **0 — AND IT REWRITES A COMMITTED ARTIFACT** |
| `2026-08-17-devteam-accounting-grain-field-measurement.py` | `. ` | **0** | same |
| `2026-08-17-devteam-critical-closure-field-measurement.py` | `. ` | **0** | same |
| `2026-08-17-devteam-instrument-validation-run.py` | `. --check` | **0** | **0 — AND IT REWRITES A COMMITTED ARTIFACT** |
| `2026-08-17-devteam-ladder-field-measurement.py` | `. ` | **0** | **2** — argparse, required positional |
| `2026-08-17-devteam-null-control-field-measurement.py` | `. ` | **0** | same |
| `2026-08-17-devteam-review-probe.py` | `. ` | **0** | **2** — argparse, required positional |
| `2026-08-17-devteam-workload-measurements.py` | `. ` | **0** | same |
| `2026-08-18-compaction-arms-field-measurement.py` | no flags (acceptance) | **0** | same |

**Twelve of twelve exit 0 under an appropriate invocation. Five of twelve make a bare
invocation the wrong invocation, and two of those five are destructive.** The handoff this
unit received named **one** destructive program. Measured, it is **two**: both
`…compaction-corpus-survey.py` and `…devteam-instrument-validation-run.py` default
`repo_root` to `.`, take the write branch whenever `--check` is absent, overwrite their
committed `.jsonl`, and exit **0**. They announce it in their own output.

```
grep -n "writes nothing.*else 'write'" docs/eval-data/*.py
```
→ two hits, one per program: `mode: --check (writes nothing)` when the flag is present and
`mode: write` when it is not. Neither line was run in the write direction by this unit.

**This program's own no-flag path is safe, and that is a property of this program only.**
`write_rows` has exactly two call sites and both are inside a mode function:

```
awk 'NR<=1130 && /^def /{d=$0} NR==980||NR==1125{print NR": "d}' \
  docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
```
→ `980: def cmd_reconstruct()` and `1125: def cmd_arms(limit)`, reachable only from
`--reconstruct` and `--arms`.

**The repository was clean before and after every command in this document**
(`git status --porcelain` empty), including after the `2026-08-14-rbp28-fix-nothing-patch.py`
run, whose scratch `git worktree` was created under `/private/tmp` and removed.

**`…rbp28-fix-nothing-patch.py` is also the one program whose interesting output is not its
exit code.** It exits 0 while reporting `3 failed, 929 passed, 2 xfailed` inside the mutated
worktree — the three `test_OUTSIDE_pytest_*` nodes that RB-P28's closure added. The
fix-nothing patch is still caught, re-measured at this HEAD rather than cited.

### 4.2 CI is confirmed at content level and NOT at run level

**There is no CI run for `feat/compaction-measured` because the branch is unpushed, and
pushing it is not this unit's to do.** Reported as UNCONFIRMED rather than inferred from a
green local suite.

```
gh run list --branch feat/compaction-measured --limit 5
```
→ empty. The most recent run in this repository is `32042046595`, `ci`, **success**, on
`main` at `f0cf440` (J1's merge), 2026-08-17.

What *is* confirmed is that CI's three steps pass locally at this HEAD, run in the exact
form the workflow runs them — `ruff check .` from `runtime-py`,
`ruff check --config runtime-py/pyproject.toml examples`, and `python -m pytest runtime-py -q`
(note: `runtime-py`, not `runtime-py/tests`) → **932 passed, 2 xfailed**. The workflow's
matrix is Python 3.11 and 3.12; this machine's venv is **3.12.13 only**, so the 3.11 leg is
also unconfirmed.

**RB-P41's CI half remains open and this job did not touch it**: nothing in
`.github/workflows/ci.yml` reads `docs/eval-data`, so none of the twelve field programs, the
acceptance run or the fifteen mutations is exercised by CI on any branch.

---

## 5. What is NOT claimed

1. **No all-on-versus-all-off number appears anywhere in this job**, in any column, and
   none is computable from the committed programs: the pair list holds adjacent rungs only,
   and `--mutate all-on-vs-all-off` exists to prove the prohibition is enforced rather than
   intended.
2. **`(N−1)/(N+1)` is an upper bound on the addressable share and never a saving.** At
   stratum A's median of 26 model calls it is **92.593%**; at stratum B's 326 it is
   **99.388%**. Neither is a measured saving and neither is comparable to any percentage
   in §0.
3. **This job measures one of two cost factors.** `tokens = calls × tokens_per_call`, and a
   replay holds `calls` fixed at what the recording did. Every figure here is a
   `tokens_per_call` figure. No composite with an unmeasured turn reduction is reported.
4. **The informative set is counter-dependent.** Two measured counters disagree on 17
   transcripts about which sessions reach `T`. "Informative" is a property of the schedule's
   declared counter, not of the transcript.
5. **The summarizer is not the model under measurement**, and the arms ran **as shipped**:
   the mechanism sends an unbounded prompt, sets no context length, and never reads back
   `prompt_tokens`, so the endpoint read **6.6%** of what B1 asked it to read. `num_ctx` is
   not in the bar's declared configuration and was not injected after the defect was found.
6. **One corpus, one summarizer, one schedule, one mode, one endpoint configuration,
   one machine.**

---

## 6. STILL OPEN — recorded, not closed

**U6 closed the Criticals and only the Criticals.** The four Majors and four Lows below are
**open**. Each carries the command this unit ran and the direction to attack it from. U5
filed three of the four Majors and all four Lows **with no command**; those commands are
supplied here for the first time and one of them **could not be constructed at all** —
which is itself recorded, as RB-P52.

### M-U5-1 — the without-constant arm figures were promised beside every with-constant one and never printed

**OPEN.** Layer: `docs/eval-data/`. **Attack:** ask of every declared "printed beside"
promise which check enforces it. Here the named check, `CHK-FIXED-COST-DECLARED`, tests
only that the two **R1 ceiling** columns exist on the B0 rows; it cannot see the arms.

Reproduced at this HEAD, **n = 24** on every figure:

| pair | printed by the run | committed but never printed |
|---|---|---|
| B1 − B0 | −40.1421% | **−58.9356%** |
| B2 − B1 | −22.7575% of B1 | −42.1513% of B1 |
| B3 − B2 | −7.9204% of B2 | −19.5665% of B2 |

```
.venv/bin/python - <<'PY'
import json, statistics, collections
from pathlib import Path
D = Path("docs/eval-data")
rows = [json.loads(l) for l in (D / "2026-08-18-compaction-arms.jsonl").read_text().splitlines()]
b0 = [json.loads(l) for l in (D / "2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines()]
inf = {r["transcript_id"] for r in b0 if r.get("reconstruction") == "OK"
       and not r["uninformative_u2"] and not r["uninformative_u1"]}
per = collections.defaultdict(lambda: collections.defaultdict(list))
for r in rows:
    if r["transcript_id"] in inf:
        per[r["transcript_id"]][r["arm"]].append(r)
for y, x in (("B1", "B0"), ("B2", "B1"), ("B3", "B2")):
    for col, tag in (("context_tokens_sent_with_fixed", "with"),
                     ("context_tokens_sent_no_fixed", "no  ")):
        p = [100.0 * (statistics.median([r[col] for r in a[y]])
                      - statistics.median([r[col] for r in a[x]]))
             / statistics.median([r[col] for r in a[x]]) for a in per.values()]
        print(f"{y}-{x} {tag}-constant: median {statistics.median(p):9.4f}%  n={len(p)}")
PY
```

The direction is honest — the printed figure is the *smaller* saving — but the omission is
against the unit's own declaration. **Not fixed here.**

### M-U5-2 — anchor retention may be the compression ratio wearing a fidelity name, and the claim is NOT REPRODUCIBLE from committed evidence

**OPEN, and weaker than filed.** Layer: `docs/eval-data/`. **Attack:** A4 — ask whether the
fidelity axis carries any information the token axis does not.

U5 filed: median installed-block bytes ÷ bytes it replaced **0.034865**, median retention
**0.054795**, median per-transcript quotient **1.213×**, retention in the
low-compression-ratio half **0.018591** and the high half **0.064120**.

**Only the retention figure reproduces.** `0.054795` at **n = 24** is a median of the
committed `anchor_retention` column. The other four rest on "bytes it replaced", which is
**not a committed column and not derivable from one**. Five candidate denominators
constructed from the committed columns give medians of `0.000518`, `0.000779`, `0.011647`,
`0.017846` and `0.410644` at n = 24 — none of them `0.034865` — and U5 filed the finding
with no command, so there is no way to learn which quantity was meant.

```
.venv/bin/python - <<'PY'
import json, statistics, collections
from pathlib import Path
D = Path("docs/eval-data")
rows = [json.loads(l) for l in (D/"2026-08-18-compaction-arms.jsonl").read_text().splitlines()]
b0 = [json.loads(l) for l in (D/"2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines()]
B = {r["transcript_id"]: r for r in b0}
inf = {r["transcript_id"] for r in b0 if r.get("reconstruction") == "OK"
       and not r["uninformative_u2"] and not r["uninformative_u1"]}
per = collections.defaultdict(lambda: collections.defaultdict(list))
for r in rows:
    if r["transcript_id"] in inf: per[r["transcript_id"]][r["arm"]].append(r)
med = lambda a, arm, c: statistics.median([r[c] for r in a[arm]])
print("retention (reproduces):", round(statistics.median(
    [med(a, "B1", "anchor_retention") for a in per.values()]), 6), "n =", len(per))
for name, f in (
    ("block/prefix_bytes_total",      lambda t, a: med(a,"B1","block_bytes")/B[t]["prefix_bytes_total"]),
    ("block/(ctxB0-ctxB1) bytes",     lambda t, a: med(a,"B1","block_bytes")/(med(a,"B0","context_bytes_sent")-med(a,"B1","context_bytes_sent"))),
    ("block/boundary / recorded/call",lambda t, a: (med(a,"B1","block_bytes")/max(1,med(a,"B1","boundaries")))/(B[t]["recorded_content_bytes"]/max(1,B[t]["model_calls"]))),
    ("block/recorded_content_bytes",  lambda t, a: med(a,"B1","block_bytes")/B[t]["recorded_content_bytes"]),
    ("ctxB1/ctxB0 bytes",             lambda t, a: med(a,"B1","context_bytes_sent")/med(a,"B0","context_bytes_sent")),
):
    print(f"  {name:32s} median {statistics.median([f(t,a) for t,a in per.items()]):.6f}")
PY
```

**What survives is the qualitative Major and it stays open**: retention is a proxy, bar §3.2
says so, and nothing in this job separates "the block is small" from "the block lost the
right strings". **The quantitative claim is downgraded to UNREPRODUCIBLE and is not
repeated as a number anywhere in this closure.** It is not fixed, and it is not quietly
dropped either.

### M-U5-3 — events dropped by the cutoff guard before the skip bookkeeping, and the count GREW within one day

**OPEN, and larger than filed.** Layer: `docs/eval-data/`. **Attack:** A3 — read the
reconstruction loop for a `continue` that precedes the counter that is supposed to see it.
**Reading-dependent: ESCALATED, not picked.**

At source, in a pattern-delimited span rather than a line number: inside `reconstruct()`,
the guard

```
if not survey._under_cutoff(stamp if isinstance(stamp, str) else None):
    continue
```

runs **before** `skipped[kind] = skipped.get(kind, 0) + 1`, so an event past the cutoff
never enters `skipped_event_kinds` and `CHK-EVERY-SKIPPED-KIND-ENUMERATED` cannot see it.
Bar §1.2 says *"if any skipped kind is unenumerated, the run is VOID"*.

| | U5, earlier on 2026-08-18 | U7, later the same day |
|---|---|---|
| events dropped by the cutoff guard, unenumerated | 1,314 | **1,471** |
| of which carried kinds (`user` / `assistant`) | 126 / 218 = 344 | **152 / 261 = 413** |
| content bytes inside them | 553,877 | **713,315** |
| enumerated skips, for comparison | 1,123 | 1,123 (committed, unchanged) |

**The finding is live and this is the direct measurement of it.** The committed `1,123`
does not move because it is a committed row; the unenumerated count grows every time a
session is appended to the directory, and it grew by **157 events and 159,438 bytes in
hours**. That is precisely the property U3's live-column exemption exists to make loud, and
here it is silent.

```
.venv/bin/python - <<'PY'
import importlib.util, sys, json, hashlib, collections
from pathlib import Path
D = Path("docs/eval-data")
def load(n, m):
    s = importlib.util.spec_from_file_location(m, D / n)
    mod = importlib.util.module_from_spec(s); sys.modules[m] = mod; s.loader.exec_module(mod)
    return mod
survey = load("2026-08-17-compaction-corpus-survey.py", "_s")
arms = load("2026-08-18-compaction-arms-field-measurement.py", "_a")
root = survey.DEFAULT_TRANSCRIPT_ROOT.resolve()
ids = {json.loads(l)["transcript_id"] for l in
       (D / "2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines()}
paths = {}
for path, here, other, _ in survey.classify_tree(root)[0]:
    if here and not other:
        tid = hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:16]
        if tid in ids: paths[tid] = path
dropped = 0; kinds = collections.Counter(); content = 0
for p in paths.values():
    with p.open("r", encoding="utf-8", errors="replace") as h:
        for raw in h:
            if not raw.strip(): continue
            try: ev = json.loads(raw)
            except json.JSONDecodeError: continue
            if not isinstance(ev, dict): continue
            st = ev.get("timestamp")
            if survey._under_cutoff(st if isinstance(st, str) else None): continue
            dropped += 1
            k = str(ev.get("type", "MISSING_TYPE")); kinds[k] += 1
            if k in arms.CARRIED_EVENT_KINDS and isinstance(ev.get("message"), dict):
                content += survey._content_bytes(ev["message"].get("content"))
print("transcripts located:", len(paths), "of", len(ids))
print("dropped, unenumerated:", dropped)
print("carried kinds:", {k: v for k, v in kinds.items() if k in arms.CARRIED_EVENT_KINDS})
print("content bytes:", content)
PY
```

**Two honest readings, and the escalation stands.** Either the transcript *is* the
pre-cutoff window — U3's declared corpus rule, under which nothing was skipped — or the
transcript is the file, under which §1.2 fires. Both arms see the same truncated input, so
**no delta is biased either way**. **Not picked. Not fixed.**

### M-U5-4 — the fidelity floor is taken over one arm where the token floor is taken over two

**OPEN.** Layer: `docs/eval-data/`. **Attack:** read a bar clause that says "the same
shape" as another clause and check that the implementation agrees.

Bar §3.1 departure 1 makes the token floor the **max over both arms**; §3.2 says the
fidelity floor has "the same shape"; the program computes it from arm **Y only**.
Reproduced exactly at this HEAD, **n = 24**:

| pair | floor as computed (Y only) | max over both arms | ratio |
|---|---|---|---|
| B1 − B0 | 0.001472 | 0.001472 | 1.000× |
| B2 − B1 | 0.011034 | 0.011034 | 1.000× |
| B3 − B2 | **0.009446** | **0.011034** | **1.168×** |

```
.venv/bin/python - <<'PY'
import json, statistics, collections
from pathlib import Path
D = Path("docs/eval-data")
rows = [json.loads(l) for l in (D/"2026-08-18-compaction-arms.jsonl").read_text().splitlines()]
b0 = [json.loads(l) for l in (D/"2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines()]
inf = {r["transcript_id"] for r in b0 if r.get("reconstruction") == "OK"
       and not r["uninformative_u2"] and not r["uninformative_u1"]}
by = collections.defaultdict(dict)
for r in rows:
    if r["transcript_id"] in inf: by[(r["arm"], r["repeat"])][r["transcript_id"]] = r["anchor_retention"]
def floor(arm):
    meds = [statistics.median(by[(arm, rep)].values()) for rep in sorted({k[1] for k in by if k[0] == arm})]
    return max(meds) - min(meds)
for y, x in (("B1", "B0"), ("B2", "B1"), ("B3", "B2")):
    fy, fx = floor(y), floor(x)
    print(f"{y}-{x}: Y-only {fy:.6f} | max over both {max(fy, fx):.6f} | ratio {max(fy, fx)/fy:.3f}x")
PY
```

**Only B3 − B2 moves and no verdict changes** — retention 0.0612905 against a
non-inferiority bar of 0.990554 either way — and the direction is harsher on the mechanism.
Filed because the bar's two floor definitions are **not** the same shape, and one of them
will matter on a corpus where retention is not two orders of magnitude below its floor.
**Not fixed.**

### L-U5-1 — the frozen anchor data carries dead weight, structurally and empirically

**OPEN.** **Attack:** run each frozen list against its own consumer and ask what could ever
match. Two strengths, and they are different claims:

- **Structural, and stronger than filed.** The `screaming` class can *never* win the
  alternation: it requires an underscore, and `snake` — `[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+`,
  which matches uppercase — precedes it. And **27 of the 35** stop-list entries can never
  match **any** class at the declared `ANCHOR_MIN_LENGTH = 6`: the bare words carry no
  underscore, dot, slash or digit, and `UTF_8` is five characters. Only **8** are capable of
  matching: `README.md`, `json.dumps`, `json.loads`, `os.path`, `package.json`,
  `pyproject.toml`, `self.assert`, `sys.argv`.
- **Empirical, as U5 filed it.** 29 of 35 never fired on this corpus; the stop-list removed
  **48 of 2,942** anchors, **1.63%**.

```
.venv/bin/python - <<'PY'
import importlib.util, sys, re
from pathlib import Path
s = importlib.util.spec_from_file_location(
    "_a", Path("docs/eval-data/2026-08-18-compaction-arms-field-measurement.py"))
m = importlib.util.module_from_spec(s); sys.modules["_a"] = m; s.loader.exec_module(m)
print("class order:", [c for c, _ in m.ANCHOR_CLASSES], "min length:", m.ANCHOR_MIN_LENGTH)
snake, scream = (dict(m.ANCHOR_CLASSES)[k] for k in ("snake", "screaming"))
print("every screaming token is also a snake token:",
      all(re.fullmatch(snake, t) and re.fullmatch(scream, t)
          for t in ("FOO_BAR", "HTTP_2_OK", "ERROR_CODE_9")))
alive = [w for w in sorted(m.ANCHOR_STOP_LIST)
         if len(w) >= m.ANCHOR_MIN_LENGTH
         and any(re.fullmatch(p, w) for _, p in m.ANCHOR_CLASSES)]
print(f"stop-list entries that CAN match: {len(alive)} of {len(m.ANCHOR_STOP_LIST)} -> {alive}")
PY
```

**Direction: this is evidence AGAINST tuning, not for it.** A tuned list fires. **Not
fixed** — editing the frozen lists is the one thing bar §3.2 forbids.

### L-U5-2 — retention is scored by substring containment

**OPEN.** **Attack:** read the scorer, not its name. `_retained_anchors` ends
`return {anchor for anchor in anchors if anchor in installed}`, so an anchor counts as
retained whenever it occurs *inside* a longer string.

```
sed -n '/^def _retained_anchors/,/^$/p' docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
```

**Direction: generous to the mechanism**, and immaterial at a retention of 0.0548 against
a bar of 0.9985. **Not fixed.**

### L-U5-3 — line-number pins in amend-only artifacts, and the true census is larger than filed

**OPEN, and broader than filed.** **Attack:** count every `file:line` pin in the job's
documents and ask, per pin, whether the target is mutable and whether a reader of *this*
repository can resolve it.

U5 filed two pins (Amendment B's `:403` and `:404`). Measured across the four compaction
documents at HEAD there are **30 distinct `file:line` pins**:

| | n | can it drift? | can a reader of this repo check it? |
|---|---|---|---|
| into files in **this** repository | **12** | **yes** — the target is a living document at a mutable ref | yes |
| into `compaction-mcp` at the pinned commit `0a15cff` | **18** | **no** — an immutable commit | **no** — the repository is not here and CI never checks it out |

**All 30 resolve today**, the 12 in-repo ones in range at HEAD, the 18 external ones in
range at `0a15cff` **on this machine only**. Amendment B's six pins into
`2026-08-17-compaction-corpus.md` — `:139`, `:337-340`, `:371-376`, `:388-411`, `:403`,
`:404` — were each read at HEAD and each resolves to the content cited.

**Binding, and still binding after this unit:** any amendment to the corpus document must
**append at the end**, or those six pins break irreparably, because an amend-only artifact
cannot repair a pin by editing it. This closure appends nothing to that document.

**The sharper form of the finding, which is new here:** pinning to an immutable commit
removes the drift risk and replaces it with an *unverifiability* risk, and **18 of 30 pins
in this job took that trade without declaring it**. **Not fixed.**

### L-U5-4 — the fidelity axis's free parameter cannot be audited from the committed evidence

**OPEN, and it is a property of the fence rather than a defect.** **Attack:** ask what a
reviewer would need to recompute the headline fidelity figure and check whether the fence
permits committing it.

Recomputing retention under a different anchor class list needs the **installed block
text**, which is not committed and could not be without breaching *"numbers and statistics
only"*. A reviewer **can** verify the lists never moved (byte-identical across all five
commits of the program) and **can** measure their effect on `anchors_total`; a reviewer
**cannot** re-derive retention. **Recorded, not fixed** — the fence is right and the
limitation is real at the same time.

---

## 7. What this unit changed

**Three files, and no evidence among them.** This document; `../eval.md` (the findings
register, RB-P47 through RB-P52); and `runtime-py/pyproject.toml` (the version).

**No committed `.jsonl` was regenerated, no committed document was retro-edited, no arm was
re-run, no threshold was re-tuned, and Amendment C was not modified** — anything further
appends after it, and this closure appends nothing to the bar at all.

```
git diff --numstat origin/main..HEAD -- 'docs/eval-data/*.jsonl' 'docs/eval-data/*.md' \
  | awk '{a+=$1; d+=$2} END {print "added", a, "deleted", d}'
```
→ `deleted 0` across the whole job.

**The version bump is `0.22.0 → 0.23.0`, a MINOR, and the reason is measured rather than
asserted:** `git diff origin/main..HEAD -- runtime-py/src/` has **zero deleted lines**, so
no public signature was removed or changed; the branch is additive on the package surface
and everything else it carries is documentation and evidence.

**RB-P45 is not closed by this bump and this unit did not touch it.** The version the MCP
server advertises still comes from the *installed distribution*
(`bantamkit-0.3.0.dist-info` in this venv), no node pins the two together, and this bump
turns nothing red — which is exactly what RB-P45 says.

---

## 8. Accounting

**Tokens: UNMEASURED. Wall-clock: UNMEASURED.** No token counter and no wall-clock counter
is exposed to this unit. A self-estimate is forbidden and reporting one because earlier
units had real counters would be worse than reporting nothing.

**Model: `claude-opus-5[1m]`.** One model. No arm re-run, no second model, no summarizer
call.
