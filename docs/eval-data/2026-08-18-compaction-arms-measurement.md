# The arms: compact-off as the null control, then one flag at a time

**Dated 2026-08-18. U4 of job `compaction-measured`. Status: MEASURED.**

The bar is
[`2026-08-17-compaction-bar-preregistration.md`](2026-08-17-compaction-bar-preregistration.md),
committed at `f48335c` before any corpus was read, and **amended twice at `e94d960`
before the first arm ran** — `git log` carries that ordering rather than this document
claiming it. The corpus is
[`2026-08-17-compaction-corpus.jsonl`](2026-08-17-compaction-corpus.jsonl), committed by
U3. Neither is regenerated or retro-edited here.

Every number below is reproduced by
[`2026-08-18-compaction-arms-field-measurement.py`](2026-08-18-compaction-arms-field-measurement.py):

```
.venv/bin/python docs/eval-data/2026-08-18-compaction-arms-field-measurement.py --reconstruct
.venv/bin/python docs/eval-data/2026-08-18-compaction-arms-field-measurement.py --arms
.venv/bin/python docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
```

The third command is the acceptance: it reads the committed rows, recomputes the bar's
verdicts, and exits 0 only if every named check holds. **It exits 0 at this commit.** Its
exit codes are themselves declared, because an exit code that is the same on every
outcome is pinned to nothing:

| exit | meaning |
|---|---|
| `0` | every named check green **and** no escalation |
| `1` | at least one named check RED |
| `2` | a `--mutate` run whose mutation **failed to falsify** the check it names — a failure of the measurement, not of the mutation |
| `3` | every check green but the run **ESCALATED** (a verdict that differs between grains). An escalation printed by a program that then exits 0 is decorative |

Under `--mutate`, exit `1` is the correct outcome and it now means only one thing.

**The suite is not evidence (RB-P28)**; no pytest node was added by this unit, and none
may assert a fact about this corpus (RB-P14 Gate 2). Acceptance rests on that field
program and on its **fourteen** `--mutate` modes, each of which turns red the check the
mutated claim NAMES and nothing else.

---

## 0. The headline, in the only form this bar permits it

**Reported per stratum. Never pooled. The user's ruling, in their words:
*"ห้าม pool เป็นเลขเดียว"*.**

> **On stratum A — 206 subagent sidechains — the handed 80% target is REFUTED, and it is
> refuted by ARITHMETIC BEFORE ANY ARM RUNS.** The zero-summary ceiling (§3) — the world
> in which a boundary replaces every prior turn with literally nothing — is a median
> **−42.6107%** with the declared fixed per-call cost and **−61.3963%** without it. Both
> are short of −80%. **1 of 104** informative transcripts has a *ceiling* that reaches
> −80% with the constant; 3 of 104 without it. No summarizer can beat a ceiling.
>
> **And the arms, run on the declared sample of stratum A, measure a real token
> reduction that the bar does not permit to be called a reduction.** `context_compact`
> against the null control — the only unconditional rung — is a median
> **−2,041,683.4 tokens, −40.1421% of B0**, clearing its noise floor at **both** grains
> with the sign pointing the same way on **24 of 24** informative transcripts. It is
> reported as a **TRADE and not a reduction** (bar §4), because median anchor retention
> in the block the host would install is **0.0548** against a floor of **0.001472**, with
> **2,621 anchors lost in all three repeats**. Tokens down, and the literal strings the
> transcript itself proved the later work needed are mostly gone with them.
>
> **On stratum B — the single top-level session — NO VERDICT IS CLAIMED.** It is n=1 and
> **UNINFORMATIVE-BY-N** under Amendment A. Its R1 ceiling is −88.9910% / −93.3403%,
> which does *not* refute the target and is *not* evidence for it. Its **arms were never
> run**: the declared prefix sample contains no stratum-B transcript, so stratum B's arms
> are **UNMEASURED**, which is a different outcome from UNINFORMATIVE-BY-N and is kept
> distinct throughout (§5.4). It never borrows stratum A's floor, and it is not averaged
> with stratum A into anything.

The two strata point opposite ways on the one axis that needed no summarizer at all. That
is precisely why pooling was forbidden before either number existed: a pooled figure over
this corpus is one number in which a single n=1 transcript — the largest by every byte and
token column — outweighs 206 others.

---

## 1. What was measured, and what was declared before it was

### 1.1 The two amendments, committed before the first arm

Recorded in the bar's §12 at `e94d960`, with §0–§11 untouched.

- **Amendment A (the user's ruling).** Stratified corpus: stratum A = 206 sidechains,
  stratum B = 1 session. Every headline, floor and verdict per stratum; pooling forbidden
  including as an aside; stratum B UNINFORMATIVE-BY-N and never borrowing stratum A's
  floor. The pre-declared `n=8` was a wrong **premise** — Claude Code keys the project
  directory by **launch** cwd — not a wrong value.
- **Amendment B (the orchestrator's ruling on U3's E-2).** `T` is **reading A**,
  live-window occupancy. **The direction of the cost is stated**: reading A is the
  expensive reading and `T` is not lowered to recover what it costs.

**Amendment B's stated cost is `105 of 207`, and the counter this bar declares in §10.3
produces `100 of 207`. Both are measured; they are not the same measurement, and neither
is edited.** See §4.3 — this is a finding of this unit, not a reconciliation of it.

### 1.2 Declarations this unit had to make, all frozen at the program's first commit

`581f6b6` is the program's first commit. Everything in this table is in it, and U5's diff
of that commit against the last is the check that none of it moved.

| declared | value | why this value and not another |
|---|---|---|
| fixed per-call cost | **DECLARED as a constant, 25,350.2 tokens** | U3 measured it two independent ways agreeing to 4.6%. **Its direction is against the mechanism**: an irreducible constant in the denominator makes every percentage saving smaller. Omitting it would flatter the result, so it is declared and the without-constant figure is printed beside every with-constant one. |
| bytes→tokens | 1.8284 B/token | U3's measured median OLS slope. Never `chars/4`, which under-counts prompt tokens 2.19× here. |
| trim schedule | after **every** ingested model call, `dropToolOutputOlderThanTurns=10` | the tool's own shipped default. Invoking trim only at boundaries would give it exactly zero measurable effect, because `context_compact` collapses every unpinned turn anyway — an arm with no possible effect is not an arm. |
| offload rule | **every** tool-role turn, no size threshold | a threshold is a knob this measurement could tune after seeing a result, and the mechanism's source contains no principled value for one. The cost is stated: a digest can be larger than the small output it replaces, so B3's byte columns can go **positive**, and they are signed and unclamped so that shows up as a cost. It did: §5.5. |
| block installation | the new block **REPLACES** the previous one | the mechanism's own host contract ("install the returned compacted context block as the new ground truth, then discard pre-boundary history"). **Direction of the bias, stated**: replacing is generous to the mechanism on tokens and harsh on fidelity. The running `block_bytes` total is committed so a reader can recompute the accumulating convention without re-running anything. |
| anchor class list + stop-list | committed as data in the program | deliberately generic: nothing in either list names a bantamkit identifier, a path in this repo, or a token this corpus contains. **Byte-identical between `581f6b6` and this commit** — §7.1. |
| sample | the longest **prefix of the committed hash order** fitting 420 summarizer calls | bar §7.1 of the corpus artifact pre-authorises exactly this shape. Hash order cannot be result-informed and neither can a prefix of it. The budget is a wall-clock budget at a **measured** 26.7 s median per call, fixed before any boundary count was known. The prefix is **50 transcripts** and it spends **315** of the 420 calls. |
| percentile convention | **nearest-rank**, declared in the program | the two conventions `statistics.quantiles` ships disagree in the third significant figure on this corpus. A spread printed without its convention is not a reproducible number. |

---

## 2. The null control was shown NOT to remove information — this is the load-bearing check

Bar §1.2: if the replay's reconstruction silently discards content, B0's prefix is already
small, the headroom is already gone, and **every saving B1 shows is an artifact of the
control**. That is J1's rigged-workload Critical (RB-P37) relocated one level over, and it
is the single failure this unit was most exposed to.

It is a **check**, not an assurance, and it passed on every transcript:

| | |
|---|---|
| transcripts reconstructed | **207 of 207** |
| `recorded_content_bytes` | **29,776,563** |
| `reconstructed_content_bytes` | **29,776,563** |
| transcripts with a non-zero byte delta | **0** |
| `recorded_events` | 25,393 |
| `reconstructed_turns` | 17,051 |
| `anchors_total` | 11,616 |

All seven figures are printed by the acceptance command itself, under
`--- THE NULL CONTROL ---`, so §2 is reproducible without re-running the reconstruction
pass over the transcripts.

**Two independent corroborations that this is not the instrument agreeing with itself.**

1. `29,776,563` is exactly U3's committed `message content bytes` Σ, computed by a
   different program from a different pass — `2026-08-17-compaction-corpus.md:255`, read
   at HEAD.
2. `model_calls`, derived here from scratch, agrees with U3's committed `model_calls` on
   **all 207 transcripts**. It did not at first: the first draft counted **4** host error
   notices across 3 transcripts as model calls. U3 had already measured the rule —
   `message.model == "<synthetic>"`, no `requestId`, all-zero usage — and adopting it
   closed the gap exactly. **The checker was fixed; no artifact was regenerated to make it
   green.**

**Every skipped event kind, enumerated with its count**, because bar §1.2 makes an
unenumerated skip a failed check rather than a rounding error:

| kind | count | | kind | count |
|---|---|---|---|---|
| `attachment` | 837 | | `queue-operation` | 74 |
| `pr-link` | 146 | | `file-history-delta` | 22 |
| `system` | 44 | | | |

25,393 carried events + 1,123 skipped = 26,516 lines under the cutoff, which is U3's
committed total (`2026-08-17-compaction-corpus.md:252`, read at HEAD).

**`attachment` is the largest skipped kind and its exclusion is a declared consequence of
U3's measurement, not a convenience.** U3 fitted the token factor with and without
attachment bytes and found the two slopes agree to four decimal places at the median
(1.8284 against 1.8289) while the **entire** difference lands in the intercept
(`2026-08-17-compaction-corpus.md:203-212`, read at HEAD). Attachments are therefore a
near-constant offset — injected once, not re-sent — so they belong in the fixed per-call
cost and not in a re-send trace. The constant this unit declares is the **messages-only**
intercept, which is the one that matches the byte definition the reconstruction actually
produces. Taking the payload intercept instead would have been an inconsistent pairing: it
goes negative (U3's median −5,239.1).

**And the null control was driven through the real mechanism as well as computed.** The
arithmetic B0 trace is used on all 207 transcripts; the mechanism-driven B0 — the actual
`compaction-mcp` server over stdio, ingesting every turn through `turn_add` — was run on
the whole sample at R=3. They agree **exactly**, byte for byte, on **50 of 50** sampled
transcripts (`CHK-B0-ROUTE-AGREES`), and B0's three repeats are byte-identical on every
measured column (`CHK-B0-DETERMINISTIC`, 0 of 50 with a non-zero spread), so the harness is
deterministic and bar §1.2's VOID condition does not fire.

**What this check does NOT establish, stated because U5 is commissioned to attack this
seam.** Byte-exactness proves the reconstruction carried every byte of every *carried*
event kind. It does not prove that the five *skipped* kinds were rightly skipped, and it
does not prove that a turn's byte content is the whole of what a live session would have
re-sent. Both are arguments about the definition of the prefix, and neither is closed by a
byte comparison. The definition is committed in the program's `reconstruct()` and the
skipped kinds are enumerated above so that the argument can be had against a number.

---

## 3. R1: the zero-summary ceiling. Arithmetic, and it settles the target on stratum A

Bar §5 R1 needs no summarizer and no arm: the **maximum** achievable reduction in
cumulative re-send is the one where every boundary replaces all prior turns with **zero
bytes**. It is computable exactly from the recorded turn sizes and the declared schedule,
so it is computed on **all 207 transcripts** rather than on the sample.

**Its population is the bar's own informative set (§5.4): boundaries > 0 AND not U-1.**
An earlier draft of this program used `boundaries > 0` alone, which carried the 2 U-1
transcripts — declared UNINFORMATIVE by the bar — into a refutation statistic. Both counts
are printed. The verdict is identical either way and the correction is recorded rather
than absorbed (§7.2).

| stratum | n informative | median ceiling, **with** the declared fixed cost | median ceiling, without it | pooled **within** stratum |
|---|---|---|---|---|
| **A** — sidechains | 104 | **−42.6107%** | −61.3963% | **−52.7398%** |
| **B** — sessions | 1 | −88.9910% | −93.3403% | −88.9910% |

Stratum A's full spread (nearest-rank), with the constant: min −80.2648%, p25 −53.5527%,
median −42.6107%, p75 −33.3894%, max −3.5091%. Without it: min −89.1174%, p25 −70.3287%,
median −61.3963%, p75 −51.7983%, max −6.5826%.

> **R1 FIRES ON STRATUM A. The handed 80% target is REFUTED for this mechanism on this
> stratum at this schedule, before any arm runs.** Exactly **1 of 104** informative
> stratum-A transcripts has a ceiling that reaches −80% with the constant declared, and 3
> of 104 without it.

R1's two assumptions travel with it wherever it is quoted: the prefix is the billed
quantity, and the schedule is held at §10.2. It refutes a claim about *this mechanism on
this stratum at this schedule* and says nothing about a mechanism that also reduces turn
count — which this job cannot measure at all (§8).

**R1 does not fire on stratum B, and that is not evidence for the target.** n=1 supports
no verdict. It is reported because Amendment A requires stratum B's columns printed in
full, and withheld from any conclusion for the same reason.

**Why the two readings of the fixed cost are both printed.** The constant is the same on
every arm, so it cancels in the numerator of a delta and not in the denominator of a
percentage. It moves stratum A's median ceiling from −61.3963% to −42.6107% — an
18.8-point swing, larger than most effects this job could have measured. A reader who
rejects the constant gets the other column without recomputing anything, and neither
column reaches −80% at the median.

---

## 4. The boundary schedule, and what reading A cost

Under Amendment B, boundary *k* falls at the first call whose **live-window occupancy**
reaches `k · T`, `T = 76,800` tokens.

| | stratum A | stratum B |
|---|---|---|
| n | 206 | 1 |
| **UNINFORMATIVE U-2** (never reached `T`) | **100** | 0 |
| **UNINFORMATIVE U-1** (boundary on the last call) | 2 | 0 |
| informative | **104** | 1 |
| boundaries | 146 | 12 |
| U-4, host-precompacted | 0 | **1** |

Over the 104 informative stratum-A transcripts (nearest-rank): **boundaries** min 1, p25 1,
median 1, p75 2, max 4; **`peak/T`** min 1.024535, p25 1.229369, median 1.614193, p75
2.198567, max 4.542966; **post-boundary calls** min 1, p25 8, median 20, p75 34, max 90.
All three lines are printed by the acceptance command.

**The standing refusal held.** 100 transcripts came out UNINFORMATIVE because the
expensive reading was chosen, and `T` was not lowered. That is what §10.2's refusal is
for, and this is the run in which it bit.

### 4.1 U-4 is grain-dependent exactly as U3's §7.4 predicted

`host_precompacted_boundaries` is non-zero on **1** transcript, so U-4 as written does not
fire — but that transcript is the whole of stratum B. Under Amendment A the two strata are
never pooled, so the grain dependence **dissolves**: it is 0/206 in stratum A and 1/1 in
stratum B, and each is reported where it belongs. The stratification the user ruled for on
other grounds closed this escalation as a side effect.

### 4.2 The corpus contains the job measuring it, and the exclusion is DECLARED

U3's E-5. The single stratum-B transcript is this job's own session. It is **not excluded**
from the corpus, because excluding a transcript to make a number nicer is the defect this
program exists to avoid; it is instead quarantined by Amendment A's stratification, which
was ruled for on independent grounds. Its arms were never run (§5.4), so no anchor was
extracted from this job's own text into any arm figure. The only figures it contributes
are its own per-transcript columns and its R1 ceiling, both printed under stratum B and
both carrying "no verdict claimed". **That is the declared choice, and it is declared
here rather than left silent.**

### 4.3 FINDING: two measured counters disagree about how many transcripts reach `T`

The bar's Amendment B states that reading A "leaves **105 of 207** UNINFORMATIVE under U-2
before any arm runs", citing U3 (`2026-08-17-compaction-corpus.md:403`, read at HEAD,
which reports **102 of 207** reaching `T`). This program measures **100 of 207**
UNINFORMATIVE and **107 of 207** reaching `T`. Neither number is an estimate and neither
is edited.

**They are two different counters applied to the same threshold.**

- U3's survey uses `recorded_prompt_tokens_peak` — the prompt-token figure the endpoint
  itself billed, `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`,
  maximum over calls. Reproduce: `…-compaction-corpus-survey.py --check`, which prints
  `transcripts whose PEAK recorded prompt reaches T  102 of 207`.
- This program uses the counter the bar **declares** in §10.3(2): reconstructed prefix
  **bytes** converted at the measured 1.8284 B/token, plus the declared fixed per-call
  constant. §10.2 says `T` is "measured by the counter of §10.3", so this is the counter
  the schedule is required to use, and it is the one every arm ran under.

**The disagreement is not 5 transcripts; it is 17.** The two sets differ symmetrically:
6 transcripts reach `T` under U3's counter and not under the declared one, and 11 reach it
under the declared one and not under U3's. The net is −5, which is why the totals look
like a small drift. Reproduce:

```
.venv/bin/python - <<'PY'
import json
from pathlib import Path
D = Path("docs/eval-data")
c = {r["transcript_id"]: r for r in map(json.loads,
     (D / "2026-08-17-compaction-corpus.jsonl").read_text().splitlines())}
b = {r["transcript_id"]: r for r in map(json.loads,
     (D / "2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines())}
u3 = {t for t, r in c.items() if r["recorded_prompt_tokens_peak"] >= 76800}
u4 = {t for t, r in b.items() if r["boundaries"] > 0}
print(len(u3), len(u4), len(u3 - u4), len(u4 - u3))
PY
```
→ `102 107 6 11`.

**Nothing is re-tuned and nothing is amended on the strength of this.** The declared
counter stands, because it was declared before any of this was known and because §10.2
names it. The bar's `105` stands as written, because the bar is amended and never edited
and because it is a true statement about U3's counter. What this finding costs is
recorded instead: **the identity of the informative set is counter-dependent**, so
"informative" is a property of the schedule's counter and not of the transcript, and any
later run that changes the counter changes the population before it changes a single
delta. That belongs in the register, and it is escalated to the orchestrator rather than
resolved here — resolving it would mean choosing a counter after seeing what each one
costs, which is the defect this whole program is built against.

---

## 5. THE ARMS

**Stratum A only.** The declared prefix sample is **50 transcripts**; **26 of 50** are
UNINFORMATIVE under U-1/U-2 and are excluded from every headline, floor and sign count, so
every figure below is **n = 24**. 600 committed rows = 50 transcripts × 4 arms × 3
repeats, with no ragged cell (`CHK-COMMITTED-KEY-SET`: 0 rows whose ordered key tuple
differs from the first).

### 5.1 The token axis, per adjacent rung. Only the first is unconditional

| pair | Δ tokens, median, SIGNED | Δ% of the **lower rung** (bar §2.3) | pooled sum **within** stratum A (§2.4) | floor, HEADLINE grain | floor, PER-TRANSCRIPT grain | sign |
|---|---|---|---|---|---|---|
| **B1 − B0** — UNCONDITIONAL | **−2,041,683.4** | **−40.1421%** of B0 | −83,275,100.1 (−52.3591% of Σ B0) | 6,462.2 `[MEASURED]` → **CLEARS** | 24/24 clear their own → **CLEARS** | directional |
| **B2 − B1** — CONDITIONAL, trim *given* compaction | −773,022.3 | −22.7575% of **B1** | −18,420,925.4 (−24.3113% of Σ B1) | 6,844.5 `[MEASURED]` → CLEARS | 24/24 → CLEARS | directional |
| **B3 − B2** — CONDITIONAL, offload *given* compaction+trim | −162,142.9 | −7.9204% of **B2** | −4,267,851.7 (−7.4417% of Σ B2) | 8,249.8 `[MEASURED]` → CLEARS | 23/24 → CLEARS | directional |

**The denominator is the lower rung, not the null control.** Bar §2.3 defines
`Δ%(t, Y−X) = Δ(t, Y−X) / CTX(t, X)`. For B1−B0 the lower rung *is* the null control and
the two readings coincide; for B2−B1 and B3−B2 they do not, and reading −22.7575% as "of
the null control" would overstate trim's marginal contribution by roughly 1.9×. The
program printed exactly that wrong label until this commit (§7.3).

**No all-on-versus-all-off number appears anywhere, in any column.** B3 against B0 is not
a reported pair, cannot be added by a flag, and the `--mutate all-on-vs-all-off` mode
exists to prove that the prohibition is enforced rather than merely intended.

**Grains agree on every pair**, so nothing is escalated on the token axis. Had they
disagreed the run would have stopped: `CHK-GRAIN-NOT-PICKED` counts the disagreements and
an escalation now carries exit code 3.

### 5.2 The fidelity axis, and its floor at its own grain

| pair | median anchor retention | floor, HEADLINE grain | non-inferior? | PER-TRANSCRIPT grain | `anchors_lost_stable` | `anchors_lost_unstable` |
|---|---|---|---|---|---|---|
| B1 − B0 | **0.0547955** | 0.001472 | needs ≥ 0.998528 → **NO** | 0/24 non-inferior → NO | **2,621** | 155 |
| B2 − B1 | 0.0526960 | 0.011034 | needs ≥ 0.988966 → NO | 1/24 → NO | 2,643 | 168 |
| B3 − B2 | 0.0612905 | 0.009446 | needs ≥ 0.990554 → NO | 0/24 → NO | 2,636 | 188 |

`anchors_lost_stable` and `anchors_lost_unstable` are **never summed** into one loss
count (bar §3.2, `CHK-LOSSES-NEVER-SUMMED`, and `--mutate sum-anchor-losses`).

**The floor is the spread of the figure it gates, and getting this wrong was worth
0.776.** The headline floor is the spread, across repeat sets, of the **median across
transcripts** — 0.001472 for B1−B0. The program originally gated that same median with the
**maximum per-transcript** spread, 0.777778, which is J1's C1 defect verbatim (a
suite-level statistic gated by a per-task maximum, measured 3.506× too permissive there).
At 0.777778 the non-inferiority bar drops from 0.9985 to 0.2222, which would certify a
retention of 0.23 as "within its floor". **The verdict does not change** — 0.0548 is below
both bars, at both grains, on all three pairs — which is why this is a corrected
instrument and not an escalation. `--mutate fidelity-floor-wrong-grain` restores the wrong
shape and turns `CHK-FIDELITY-FLOOR-AT-ITS-OWN-GRAIN` red.

### 5.3 The three axes together, never netted (bar §4)

| pair | ρ* = \|Δcontext_tokens\| / summarizer tokens | the mechanism's own added turns | verdict |
|---|---|---|---|
| B1 − B0 | **37.4630** | B1 adds **+35** summarizer boundary calls across the 24 informative transcripts | **TRADE**, not a reduction |
| B2 − B1 | 14.0370 | B2 adds +35 | TRADE |
| B3 − B2 | 5.8283 | B3 adds +35 | TRADE |

ρ* is the **break-even price ratio** and it is a quotient of two measured columns with no
price assumed: compaction is a net token win exactly when the summarizer's price per token
is below ρ* times the agent's. `ρ* = 37.46` on the unconditional rung, so **R4 does not
fire** — at equal price the mechanism is not a net loss, and it would take a summarizer
more than 37× the agent's price per token to make it one.

The added turns are reported as each arm's **own** added boundary calls rather than as
`Δcalls(B3 − B0)`, because that shape is an all-on-versus-all-off comparison and §1.5
forbids one in any column. For B1 the two coincide (B0 adds none), which is the form
§3.3(2) states. The agent's own call count is identical across all four arms on 50 of 50
transcripts (`CHK-TURNS-WITNESS`), so no part of any token delta is turns the flag caused.

**The refutation clauses, each stated with whether it fired:**

- **R1 — FIRES** on stratum A (§3). The target is refuted arithmetically.
- **R2 — DOES NOT FIRE, and its preconditions are the reason.** R2 requires
  `HEADLINE(B1−B0) > −80%` *at retention within its floor with `anchors_lost_stable == 0`*.
  The magnitude condition holds (−40.14% > −80%); the fidelity condition does not
  (retention 0.0548 against a floor of 0.001472, 2,621 stable losses). **So the empirical
  route to refuting 80% is unavailable on this data, and the target is refuted by R1
  alone.** Reporting R2 as firing would be reading a clause with its conditions stripped.
- **R3 — DOES NOT FIRE.** R3 needs `Δcontext_tokens(B1−B0) ≥ 0` on a majority of
  informative transcripts. The delta is negative on 24 of 24. The mechanism **does** reduce
  cumulative context re-send in `store` mode on this stratum.
- **R4 — DOES NOT FIRE.** ρ* = 37.4630 ≥ 1.
- **Confirmation (bar §6) — NOT met**, and it fails on three of its five conditions at
  once: the headline is −40.14% and not ≤ −80%, retention is not within its floor, and
  `anchors_lost_stable` is 2,621 and not 0. Only the floor conditions and the sign
  condition are satisfied.

### 5.4 Stratum B's arms are UNMEASURED, which is not UNINFORMATIVE-BY-N

The sample rule is a declared prefix of the committed hash order, declared before it was
computed, and the hash order does not put the single stratum-B transcript inside the first
50. **The rule is not amended after the fact to reach it.** So:

- stratum B is **UNINFORMATIVE-BY-N** for anything computed from its R1 ceiling — n=1
  supports no floor and no verdict (Amendment A);
- stratum B's **arms are UNMEASURED** — no B1, B2 or B3 row for it exists at all.

These are different states and collapsing them would let "we did not run it" read as "we
ran it and learned nothing". A stratum-B arm run is the obvious next declared sample; it
costs 12 boundaries × 9 summarizer-bearing replays = **108** calls.

### 5.5 The signed §8 cost columns — and B3's digest costs more than it saves nothing

Median over repeats per transcript, then summed within stratum A over the 24 informative
transcripts. **Signed and unclamped; `0` means measured zero, not absent.**

| arm | summary | rehydrated | block | trim removed | offload digest | offload body |
|---|---|---|---|---|---|---|
| B1 | +97,837 B | +0 B | +97,907 B | +0 B | +0 B | +0 B |
| B2 | +92,094 B | +0 B | +92,164 B | **−2,194,945 B** | +0 B | +0 B |
| B3 | +85,149 B | +0 B | +85,219 B | −1,067,817 B | **+1,373,214 B** | +3,591,770 B |

- **The summary ADDS bytes to save bytes** and that is what the positive `summary` and
  `block` columns are. They are never netted into the saving.
- **`rehydrated_bytes` is `+0` on every arm** — a measured zero under `lexical` recall on
  this corpus, not an absent column. Bar §1.3 already declares recall's benefit
  unmeasurable on a replay; this is the byte-level record of that.
- **B3's offload digest is a real cost that the sign convention made visible.** The digests
  it wrote total **+1,373,214 B** against **+3,591,770 B** of tool-output bodies replaced —
  a 38.2% residue, on an offload rule with no size threshold, exactly as §1.2 warned when
  it declared the rule. A clamped byte column would have shown this as a clean saving.

**And the summarizer's own consumption, which is where §6's finding lives:**

| arm | prompt bytes sent | tokens asked for | tokens the endpoint actually read |
|---|---|---|---|
| B1 | 3,966,447 B | 2,169,356 | **143,360 (6.6%)** |
| B2 | 2,307,341 B | 1,261,944 | 143,360 (11.4%) |
| B3 | 1,253,717 B | 685,693 | 140,775 (20.5%) |

143,360 = 35 boundaries × 4,096. See §6.

---

## 6. The instrument finding that arrived before the arms did

**Measured, twice, at two different prompt sizes, against the declared endpoint, before
the sample was declared:**

| prompt bytes sent by the mechanism's own request body | `prompt_tokens` the endpoint reported |
|---|---|
| 720,500 | **4,096** |
| 202,720 | **4,096** |

`qwen2.5:14b-instruct` reports `qwen2.context_length = 32768` and carries no `num_ctx`
parameter in its model card, so the endpoint's default 4,096-token window applies.
`src/summarizer.ts:30-36` at `0a15cff` sends exactly `model`, `messages`, `max_tokens`,
`temperature` and `stream` — **no context-length option — and `src/summarizer.ts:41-44`
reads back only `choices[0].message.content`, never the returned `prompt_tokens`.** So the
transcript is silently truncated to 4,096 tokens, 12.5% of what this model could have read.
Both pins re-read at `0a15cff` by this unit.

**The truncation keeps the TAIL.** `buildSummarizePrompt` puts its instructions at the
head and `<transcript>` last, so what survives truncation is the end of the transcript and
**not the mechanism's own summarization instructions**. A control probe confirms the
direction: a marker placed at the very top of a 720 KB prompt was not recoverable, and the
model answered from the tail.

**It is measured across the whole run, not inferred from two probes.** §5.5's last table
is the same defect at scale: on B1 the mechanism asked the endpoint to read 2,169,356
tokens and the endpoint read 143,360 of them — **6.6%**.

**How this was handled, and why.**

- The arms were run **AS SHIPPED** — the mechanism's own request body, unmodified, no
  `num_ctx` injected. `num_ctx` is **not** in the bar's §10.6 declared configuration; it
  is an undeclared knob, and choosing a value for it after discovering the defect would be
  picking a setting that flatters a result. This is the same refusal as §10.2's, one knob
  over.
- It is **not** a VOID condition. It does not touch the byte or token axis: the mechanism
  collapses turns regardless of what its summarizer saw, so the saving is unaffected. It
  falls entirely on the **fidelity** axis, which the bar already routes through §3.2 and
  §4's TRADE clause — and §5.2's retention of 0.0548 is a composite of "what the
  summarizer was shown" and "what it kept", which this instrument cannot separate.
- The magnitude is deployment-conditioned; the **defect** is not. A mechanism that sends
  an unbounded prompt to an OpenAI-compatible endpoint, sets no context length, and does
  not read back `prompt_tokens`, has no way to know it was truncated on **any** endpoint.

---

## 7. What this unit changed in the instrument after `581f6b6`, and why

Every item here is a **defect in the measuring program**, found by this unit against the
committed rows. **No committed artifact was regenerated and no arm was re-run.** The
arms `.jsonl` is the record.

### 7.1 What did NOT change: the anchor class list and the stop-list

Frozen at `581f6b6` as data, per bar §3.2 and the unit's fence. Verified two independent
ways, both reproducible, and **neither of them a line-number pin** — see the correction
below for why that matters.

```
# 1. the span from the declared minimum length through the compiled class regex,
#    which contains both lists and everything between them. Pattern-delimited, so it
#    survives any edit elsewhere in the file.
P=docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
for REV in 581f6b6 HEAD; do
  git show $REV:$P | sed -n '/^ANCHOR_MIN_LENGTH/,/^_ANCHOR_RE/p' | shasum -a 256
done
```

Both revisions give
`810d9ade35046be0745975bff0957b23debc642308cff3fba6f5f2ceb727056a` over **26,428 bytes**.
The tighter span `'/^ANCHOR_MIN_LENGTH/,/^)$/p'` — the two literals and nothing else —
gives `0d3f314a76a2b3fbb44eec891a6a514cd0a38a4ed60ea9093b6be4c795b60a60` on both.

Second route: import both revisions as modules and compare the objects rather than the
text. `ANCHOR_CLASSES` (6 classes), `ANCHOR_STOP_LIST` (35 entries) and
`ANCHOR_MIN_LENGTH` (6) compare **equal** between `581f6b6` and HEAD.

**Nothing was added because a number looked wrong.** No stop-word was wanted and none was
added.

> **Correction, 2026-08-18, same day, recorded rather than rewritten.** The first
> committed version of this subsection pinned the span as `sed -n '135,727p'` and quoted
> `83d925d8…` over 26,405 bytes. That hash was true of `581f6b6` and **false of HEAD** —
> not because either list moved, but because this unit added one `import` line near the
> top of the file and every line number below it shifted by one. The lists are
> byte-identical; **the pin drifted.** That is the seventh measured pin drift in this
> program, and it was committed by the unit whose own document quotes the rule. The
> commands above are pattern-delimited so the next edit cannot repeat it.

### 7.2 R1's population was the wrong set (fixed, verdict unchanged)

`boundaries > 0` carried the 2 U-1 transcripts into a refutation statistic the bar
declares them UNINFORMATIVE for. Corrected to the bar's §5.4 informative set; both counts
are now printed. Median moved from −42.5777% to −42.6107%; the −80% count is 1 either way;
**R1 fires either way.**

### 7.3 "% of the null control" was the wrong label (fixed)

The program computed §2.3's ratio correctly against the lower rung and printed it labelled
as the null control. True for B1−B0, false for B2−B1 and B3−B2 by a factor of about 1.9.
Relabelled; the arithmetic never moved.

### 7.4 The fidelity floor gated the headline at the wrong grain (fixed, verdict unchanged)

§5.2. J1's C1 one axis over. Now has its own named check and its own mutation.

### 7.5 Bar clauses the program did not implement (now implemented)

- **§2.4** — "the pooled sum is reported in the same table as the median, **always**".
  It was computed for ρ* and never printed. Now printed on every pair, pooled **within**
  the stratum only.
- **§3.3(2)** — the mechanism's own added turns, signed, as a cost. Was not reported.
- **§1.2's own table** — the null control's byte reconciliation, event counts and skipped
  kinds were in this document but not printed by the acceptance command, so the
  load-bearing section was the one section not reproducible from the program. Now printed.

### 7.6 A mutation that failed to falsify exited 1, the same as one that succeeded

`cmd_report` returned 1 on both branches, so "the mutation run exited 1" carried no
information. Now: 1 means the named check went red, 2 means the mutation falsified
nothing. Proved on a scratch copy outside the repo tree with a deliberately inert
mutation → exit 2, and with a synthetic escalation → exit 3.

### 7.7 An escalation exited 0

Bar §3.1 says a grain disagreement **stops the run**. The program printed
`[ESCALATE]` lines and then exited 0. Now exit 3. There are 0 escalations at this commit,
so the acceptance is unaffected — but the property is now pinned instead of intended.

---

## 8. Limitations, recorded rather than buried

1. **This job measures one of the two cost factors.** `tokens = calls × tokens_per_call`;
   a replay holds `calls` fixed at what the recording did. Everything here is a
   `tokens_per_call` result, and **no composite with an unmeasured turn reduction is
   reported** (bar §1.3, §11(1)).
2. **The sample is a declared prefix, and it contains no stratum-B transcript.** The rule
   was declared before it was computed and it is not amended after the fact. Stratum B's
   arms are therefore **UNMEASURED**, which is a different thing from UNINFORMATIVE-BY-N,
   and the distinction is kept (§5.4).
3. **The informative set is counter-dependent** (§4.3). Two measured counters disagree on
   17 transcripts about which sessions ever reach `T`. "Informative" is a property of the
   schedule's declared counter, not of the transcript.
4. **Anchor retention is a proxy, biased in both directions**, and it is not called
   fidelity (bar §3.2). Under §6's truncation it is measuring the composite of "what the
   summarizer was shown" and "what it kept", and those two cannot be separated by this
   instrument.
5. **The arms are not byte-reproducible** — hard-coded `temperature: 0.2`, no seed. The
   committed rows are the record; the reproduction route is the verdict recomputation, not
   a re-run (bar §7(2), §9(2)).
6. **Independence is weaker than n suggests.** U3's §6(3): sidechains under one parent
   share that parent's project state and often its brief template. And n=24 informative of
   50 sampled of 206 in the stratum is the real width of every arm figure here.
7. **One corpus, one summarizer, one schedule, one mode, one endpoint configuration.**
8. **Measured cost of the run, from the committed `wall_clock_s` column**: 20,913.7 s
   (5.81 h) across 600 rows — B0 10.7 s, B1 7,332.1 s, B2 7,004.9 s, B3 6,566.0 s — over
   315 summarizer calls, against a declared budget of 420.
