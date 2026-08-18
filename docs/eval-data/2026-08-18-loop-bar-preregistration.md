# Pre-registered bar: does compaction's measured fidelity loss cost the WORK?

**Dated 2026-08-18. Status: PRE-REGISTERED. No harness exists. No arm has run. No agent
has been driven. No goal task has been attempted by any model.**

This artifact is **amended, never rewritten**. If something below turns out wrong, a dated
amendment goes in §12 and the original text stays exactly as it is (RB-P50, and the
conservative reading that binds until J3 ships the record-vs-pointer checker).

U1 of job `compaction-in-the-loop`. The mechanism this bar grades is the `compaction-mcp`
server at commit `0a15cff65c5c847af07b43de3b67d726433a4ca3`. The **workload** is
`packnplan-mono` at commit `81ac1a10e2230661ce10745a3a64f4da1d3819f2` — a workload, never
the subject, never committed to, never pushed.

---

## 0. Disclosure, before anything else

1. **No arm has run and no goal task has been attempted.** The measurements below are of
   *instruments* — ollama's sampling behaviour, ollama's counters, vitest's output
   stability, the size of the workload in tokens. None of them is an outcome of the
   question this bar asks.
2. **Every number below was measured on this machine today, with a command.** Where a
   number could not be measured it says UNMEASURED and why. Nothing here is a
   self-estimate: token counts come from ollama's own `prompt_eval_count` / `eval_count`,
   durations from ollama's own nanosecond fields or from a monotonic clock around the HTTP
   call, byte counts from `wc -c`, exit codes from `$?`.
3. **J2's result is the prior, and it is a warning.** J2 measured that this mechanism is a
   **TRADE**: −40.1421% of B0's context tokens at the effective **n = 24**, +0.0000% at the
   nominal **n = 50**, against median anchor retention **0.0548** with **2,621 anchors lost
   in all three repeats**, and the handed 80% target **REFUTED by arithmetic under all five
   compositions**. This job installs, into a live loop, a mechanism already measured to
   destroy about 94.5% of the literal anchors the transcript itself proved later work
   needed. That is the thing being put in the loop. Nobody has ever measured whether that
   costs the work.
4. **This job's axis is not J2's and may not be reported as J2's.** J2 measured *tokens vs
   fidelity on recordings, by replay*. A replay cannot answer this question: it re-runs a
   trajectory that already happened, so the trajectory cannot respond to having been
   compacted. **This job's axis is the task outcome under a live loop.**
5. **The user's fence, inherited:** committed artifacts carry numbers, statistics and the
   workload paths this bar already names — no transcript excerpts, no prompt text, no
   other project's file contents.

---

## 1. The goal task, pre-registered before the harness exists

### 1.1 The workload, and the fence around it

`packnplan-mono` at `81ac1a10e2230661ce10745a3a64f4da1d3819f2`. Every run happens in a
**throwaway detached `git worktree`** cut from that commit and placed **outside** the
packnplan working tree. Nothing is committed, pushed or staged there; the repository's one
pre-existing untracked file under `docs/test-cases/` is never touched; the worktree is
removed at the end and `git worktree list` is shown clean.

`node_modules` is supplied to the worktree as two symlinks into the real checkout
(`node_modules` and `packages/shared/node_modules`). Consequence, declared: the tamper and
scope checks of §1.4 read **`git diff` against the pinned commit over tracked paths**, never
`git status`, because the symlinks show as untracked and would poison a `git status`-based
check.

**Why `packages/shared`.** It is the only place in this monorepo where a task can be scored
with **no database, no network, no browser and no emulator**: pure domain logic — expense
split, debt settlement, date formatting, opening hours, travel-mode inference. Its whole
oracle runs in **1.7 s** wall-clock.

### 1.2 The task

The worktree is prepared by applying **DEFECT-SET-5**: five one-line behavioural defects,
one per file, each a literal string replacement, each verified below to occur **exactly
once** in its file at the pinned commit.

| id | file (relative to `packages/shared/`) | from → to |
|---|---|---|
| **D1** | `src/expense/split/split.ts` | `/ 10000n;` → `/ 1000n;` |
| **D2** | `src/expense/settle/settle.ts` | `const pay = d.amt < c.amt ? d.amt : c.amt;` → `const pay = d.amt < c.amt ? c.amt : d.amt;` |
| **D3** | `src/date/date.ts` | `return value.slice(0, 10);` → `return value.slice(0, 8);` |
| **D4** | `src/trip/travelMode/travelMode.ts` | `distanceKm < 1.5` → `distanceKm <= 1.5` |
| **D5** | `src/place/openingHours/openingHours.ts` | `if (candidate >= openMinutes && candidate < closeMinutes) return true;` → `if (candidate > openMinutes && candidate < closeMinutes) return true;` |

The task handed to the agent is fixed now and does not change between arms:

> `packages/shared` has failing tests. Make the package's test suite pass. Do not edit any
> `*.test.ts` file.

**Why five defects in five files rather than one.** A one-file repair is finishable without
reading the package, which makes the context small, which makes the boundary count zero,
which makes the job UNINFORMATIVE by construction — the trap J2 measured (26 of 50
transcripts never reached a single boundary). Five defects in five directories force
search. §1.5 says how far that gets us, arithmetically, and it is not far enough to be
comfortable.

### 1.3 The oracle — packnplan's own tooling, an exit code, never a judgement

Run from the worktree's `packages/shared` directory:

```
ORACLE   ./node_modules/.bin/vitest run                 expected exit 0
GUARD-T  ../../node_modules/.bin/tsc --noEmit           expected exit 0
```

**Measured at the pinned commit, in a real throwaway worktree, today.**

| state | ORACLE exit | ORACLE result | GUARD-T exit |
|---|---|---|---|
| pristine `81ac1a1` | **0** | 10 test files passed, **141 tests passed** | **0** |
| DEFECT-SET-5 applied | **1** | 5 test files failed / 5 passed, **7 tests failed / 134 passed** | **0** |

So the ORACLE **discriminates**, and each defect was additionally verified to redden a
**named** test on its own, one at a time, with the other four reverted:

| defect | tests it reddens on its own | the test file that goes red |
|---|---|---|
| D1 | 2 | `src/expense/split/split.test.ts` |
| D2 | 1 | `src/expense/settle/settle.test.ts` |
| D3 | 2 | `src/date/date.test.ts` |
| D4 | 1 | `src/trip/travelMode/travelMode.test.ts` |
| D5 | 1 | `src/place/openingHours/openingHours.test.ts` |

2 + 1 + 2 + 1 + 1 = 7, which is the combined count. No defect is masked by another.

**GUARD-T is measured NON-VACUOUS, from the output side (RB-P48).** A guard that can never
fire independently is decoration. Changing `travelMode`'s parameter type from `number` to
`string` — a type-only defect — gives **ORACLE exit 0 and GUARD-T exit 2**, because vitest
transpiles without type-checking. GUARD-T therefore has a class of failure the ORACLE
cannot see, and it is not a second transcription of the ORACLE's rule (RB-P47: an input
that makes them disagree is named, and it was run).

**`tsc --noEmit` exits 2, not 1, on a type error.** Recorded because a bar that declares
"non-zero" where the real code is 2 has not declared an exit code.

### 1.4 The two guards against a gamed oracle, and their outcomes

A repair task's obvious exploit is deleting the test. Both guards are `git diff` against the
pinned commit, over tracked paths:

```
GUARD-TAMPER  git -C <wt> diff --name-only 81ac1a1 -- 'packages/shared/**/*.test.ts'
              must print NOTHING.
GUARD-SCOPE   git -C <wt> diff --name-only 81ac1a1
              recorded as a column; files outside DEFECT-SET-5's five paths are counted
              and printed. This one does NOT gate.
```

**The outcome of a run is one of six, and they are never pooled:**

| outcome | condition |
|---|---|
| `PASS` | ORACLE 0 **and** GUARD-T 0 **and** GUARD-TAMPER empty |
| `FAIL` | ORACLE non-zero, guards intact, agent stopped on its own |
| `FAIL-CAP` | the turn cap of §10.6 was reached with the ORACLE still non-zero |
| `FAIL-TYPE` | ORACLE 0 but GUARD-T non-zero |
| `FAIL-TAMPERED` | GUARD-TAMPER non-empty — **never counted as PASS, never pooled with FAIL** |
| `VOID` | a §6 instrument condition fired; the repeat is discarded and reported as discarded |

### 1.5 How many boundaries this task can reach — arithmetic, computed before the run

Measured with the **worker's own tokenizer** (`prompt_eval_count`, §10.3), on the pinned
commit's tree:

| what | bytes | tokens | as a multiple of `T` = 19,660 |
|---|---|---|---|
| all 32 `.ts` under `packages/shared/src` (22 impl + 10 test), concatenated with a one-line `=== <relpath>` header each | 80,548 | **23,647** | 1.20 × |
| the 22 implementation files only | 43,301 | **12,243** | 0.62 × |
| one FAILING ORACLE run, raw stdout | 6,560 | **2,253** | 0.115 × |

> **The consequence, stated before any run: this task is BOUNDARY-THIN.** An agent that
> reads every implementation file once and runs the oracle once accumulates **14,496
> tokens — 0.74 × T — and never reaches a boundary at all.** Reading every file including
> the tests plus one oracle run gives **25,900 tokens — 1.32 × T — exactly one boundary.**
> Nine oracle runs and no file read at all (8.7, rounded up) would reach `T`.

So the effect this job can measure is, at best, **the effect of one or two boundaries**,
and it is entirely possible that a competent agent finishes below `T` and the mechanism
never fires. §6's U-1 says what happens then, and §10.2 refuses in advance to lower `T`
afterwards.

---

## 2. Invariant 9, and why it cannot stand as written — the resolution, measured

The invariant handed to this job says:

> *"AN LLM-DRIVEN RUN IS STOCHASTIC. Repeats are declared before the first run, the null
> control's determinism is checked FIRST, and if the null control varies the harness is
> nondeterministic and every delta is contaminated. J2's B0 was exactly deterministic on
> all 22 outcome columns and that is what licensed every number it reported."*

Applied literally, that kills this job on contact: the null control here is an agent doing
work. **It is not ignored and it is not waved away. It was measured, and it is replaced by
a graded criterion whose cost is stated.** Four measurements do the replacing.

### 2.1 M1 — an LLM under ollama is NOT stochastic when you pin it. Measured.

`docs/eval-data/2026-08-18-loop-worker-determinism-probe.py`, ollama **0.18.0**, 4 repeats
per cell, `num_predict=220`, `num_ctx=8192`, one fixed neutral prompt (not the goal task).
Verdicts are over `sha256(response)` **and** `eval_count` jointly.

| condition | `qwen2.5:7b-instruct` | `qwen2.5:14b-instruct` |
|---|---|---|
| A temp = 0, no seed | **IDENTICAL** | **sha-only** — 2 distinct sha, 1 distinct `eval_count` |
| B temp = 0, seed = 7 | **IDENTICAL** | **IDENTICAL** |
| C temp = 0.2, seed = 7 | **IDENTICAL** | **IDENTICAL** |
| D temp = 0.2, **no seed** | **VARIES** — 4 distinct sha, 4 distinct `eval_count` | **sha-only** — 4 distinct sha |
| E temp = 0, seed = 7, model **unloaded between calls** | **IDENTICAL** | **IDENTICAL** |
| F temp = 0, seed = 7, **~8.1k-token prompt** | **IDENTICAL** | **IDENTICAL** |

**Condition D is the probe's own discriminator and it varied on both models**, so the
IDENTICAL verdicts are about the settings and not about a prompt too easy to distinguish
anything. The probe prints UNINFORMATIVE for any model whose D does not vary; neither
model triggered it.

**So the seed does pin output — and at temperature 0 it is already pinned without one.**
The blanket claim "an LLM-driven run is stochastic" is **false at the level of a single
call**, measured.

### 2.2 M2 — but pinning holds only WITHIN a load state, and that is invisible unless you look

`qwen2.5:14b-instruct` at temperature 0 with a fixed seed returns **two different byte
sequences with the same `eval_count` of 220**: `f61b18…` on a freshly-loaded model,
`71a6d9…` on a resident one. Condition E — which unloads the model before every call —
returned `f61b18…` **four times out of four**, and every warm call in conditions A and B
returned `71a6d9…`. Each regime is internally deterministic; the two regimes disagree
byte-for-byte.

This is the `sha-only` case, and it is exactly the disagreement input the probe's docstring
named **in advance** as the reason `sha256` and `eval_count` are not two transcriptions of
one rule (RB-P47). It was named before it was seen, and then it happened.

**`qwen2.5:7b-instruct` did not do this**: `3b37f76277d8` on warm-no-seed, warm-seeded and
cold-seeded alike. The 7B is load-state **insensitive**; the 14B is not. That is a measured
selection criterion, recorded here because it is one of the two reasons §10.5 makes the 7B
the worker, and because it cannot be result-informed — no arm has run.

### 2.3 M3 — the mechanism's summarizer cannot be pinned at all through the shipped route

`compaction-mcp` at `0a15cff`, `src/summarizer.ts`, `DirectSummarizer.summarize` sends
`temperature: 0.2` and **no seed** — the request body is
`{model, messages, max_tokens, temperature: 0.2, stream: false}` and there is no seed field
anywhere in the file. That configuration is **condition D** of §2.1, the one cell that
varied on both models. The mechanism supplies its own unpinnable component, and it does so
by construction rather than by oversight.

**Consequence, pre-registered: B0 has no unpinnable component and B1 does. The asymmetry is
structural and cannot be removed without modifying the mechanism under measurement.**

### 2.4 M4 — and the null control varies for a reason that has nothing to do with any LLM

The ORACLE is packnplan's own tooling, which invariant 3 requires. Its **stdout is not
reproducible**, measured in the throwaway worktree:

| state | 3 runs, raw `sha256` | after scrubbing timestamps and durations | after scrub **+ sorting lines** |
|---|---|---|---|
| passing (141 pass) | **3 distinct of 3** | **3 distinct of 3** | 1 distinct |
| failing (7 fail) | **3 distinct of 3** | **3 distinct of 3** | 1 distinct |

Two runs of the failing state differ on **116 of 174 lines**. The variance has three
independent sources — test-file **completion order** under parallel workers, per-file
**durations**, and a wall-clock `Start at` **timestamp** — and *scrubbing the clock does not
fix it*, which is the fix everybody reaches for first. `--no-file-parallelism` does not fix
it either: it removes the file-order variance and leaves the **failure-block order**
varying (2 distinct of 3 after scrubbing).

> **So the null control's transcript can never be byte-identical across repeats, for
> reasons upstream of the model, upstream of compaction, and not removable at the source.**
> Invariant 9's "if the null control varies, every delta is contaminated" would condemn this
> harness before the first token is generated, on the strength of a `Duration 384ms` line.

**CANON-1 recovers it.** A canonicalizer with three rules — (a) replace every duration,
`HH:MM:SS` timestamp and `[k/N]` failure index with a fixed token; (b) sort the lines
preceding the first ` FAIL ` header; (c) split the remainder into blocks at each ` FAIL `
header and sort the blocks by their header line — gives **1 distinct sha of 3 on the
passing state and 1 distinct of 3 on the failing state**. CANON-1 is declared here, applied
identically to every arm, and is part of the instrument, not part of any arm.

### 2.5 The replacement, in this bar's own words

> **Invariant 9's clause 1 — repeats declared before the first run — is UPHELD unchanged
> (§3.3). Its clause 2 — "if the null control varies the harness is nondeterministic and
> every delta is contaminated" — is REPLACED by three graded criteria, because it was
> measured to be unsatisfiable here for reasons that are not evidence of a broken harness.**
>
> **D-1 · MODEL DETERMINISM. Required. Failure is VOID.** Identical prompt bytes, identical
> sampling options and identical load state must give identical completion bytes. This is
> the part of invariant 9 that survives intact, and §2.1 measured that it holds. U2
> re-checks it FIRST, on the actual worker configuration at the declared repeat count,
> before any arm. If D-1 fails, the harness is nondeterministic in the sense invariant 9
> meant, and the run is VOID.
>
> **D-2 · PROMPT-STREAM DETERMINISM OF THE NULL CONTROL. Required of B0 only. Failure is
> VOID.** B0's turn sequence, with every tool output passed through CANON-1, must be
> byte-identical across B0's R repeats. This is the honest survivor of "check the null
> control first": it asserts that the harness feeds the same thing twice, which is a
> property of the harness and is checkable. **B1–B3 are explicitly NOT required to satisfy
> D-2**, because the summarizer's output is part of their prompt stream and §2.3 measured
> that it cannot be pinned.
>
> **D-3 · OUTCOME DETERMINISM. NOT required. Measured, and it IS the noise floor.** Where
> an arm's outcome varies across its repeats, that spread is the floor for the statistic it
> gates, at that statistic's own grain (§3).

**What the replacement costs, stated plainly and before any number exists.** J2's licence —
*"B0 was exactly deterministic on all 22 outcome columns, therefore any non-zero delta is
real"* — is **gone, and cannot be recovered by any configuration this bar is willing to
declare.** Three specific losses:

1. **No delta in this job is ever EXACT** in the sense of J2's bar §3.1. B1's summarizer is
   unpinnable (§2.3), so B1 is a stochastic arm and every B1 − B0 comparison is
   **DEGENERATE-BY-CONSTRUCTION** in that rule's vocabulary. This bar says so now rather
   than discovering it in a report.
2. **The summarizer's variance and compaction's effect are not separable by any measurement
   this job performs.** They enter the same column. Only repeats bound them jointly.
3. **The primary outcome is a binary at n = R, so its resolution is 1/R and no smaller
   effect exists to be found.** §3.3 turns that into an explicit minimum detectable effect
   rather than leaving it implicit.

**One secondary arm could buy some of that back, and it is declared here rather than
invented later.** `COMPACTION_LLM_BASE_URL` is a configuration variable (config.ts, read at
`0a15cff`: `baseUrl: process.env.COMPACTION_LLM_BASE_URL || "http://localhost:11434/v1"`),
so a **declared pass-through shim that injects `"seed": 7` into the summarizer's request
body** would make B1 deterministic without touching the mechanism's logic. If it is run, it
is **arm S1, reported separately under its own heading and never merged into the
headline**, and its value is exactly one thing: if S1 is reproducible across repeats while
B1 is not, then all of B1's spread is attributable to the summarizer. That decomposition is
available no other way. **If U2 does not build it, S1 is reported UNMEASURED with that
reason** — a run that was not attempted is not a run that found nothing (RB-P51).

---

## 3. The arms, the statistics, and the repeats

### 3.1 The ladder — one flag per rung, null control as rung zero

| arm | name | what is ON | the one flag this rung adds | required? |
|---|---|---|---|---|
| **B0** | `compact-off` | the full orchestration; the MCP server is connected and `context_compact` is never called | — **the null control** | **yes** |
| **B1** | `compact-on` | + `context_compact` at the §10.2 trigger | **`context_compact`** | **yes** |
| B2 | `compact-trim` | + `context_trim` | `context_trim` | budget-permitting |
| B3 | `compact-trim-offload` | + tool-output offloading | offload | budget-permitting |
| S1 | `compact-on-seeded` | B1 with the §2.5 seed shim | — *not a rung*; a determinism decomposition | optional |

**The headline is Δ(B1 − B0): `context_compact` in isolation, adjacent to the null control,
UNCONDITIONAL.** B2 and B3 are **CONDITIONAL** rungs — "trim *given* compaction", "offload
*given* compaction and trim" — and may never be stated unconditionally. **No all-on
versus all-off number is produced, ever.**

**The null control is the same orchestration with compaction off, not the absence of
orchestration.** B0 connects the same MCP server, exposes the same tool roster, runs the
same worker at the same sampling settings against the same worktree. The only difference at
B1 is that the boundary fires.

**If the wall-clock budget of §10.6 is exhausted after B0 and B1, B2 and B3 are reported
`UNMEASURED-BUDGET` with their repeat count at zero.** They are not reported as null.

### 3.2 Where J2's method does NOT transfer, and what replaces it

J2 computed its boundary schedule once from B0's trace and **injected it identically** into
every arm, so the arms could not differ in boundary count (RB-P39's confound). **That is
impossible here and the reason is structural: this is a live loop.** The instant B1's first
boundary fires, B1's agent sees a different context and takes a different action, so a
turn-index schedule computed on B0 has no referent in B1 after turn *k*.

> **So B1–B3 are PRESSURE-TRIGGERED on their own occupancy (§10.2), and the RB-P39 confound
> is therefore PRESENT and is declared rather than eliminated: a B1 − B0 delta mixes "what a
> boundary does" with "how many boundaries happened". `boundaries` is printed beside every
> single figure this job reports, and no figure may be quoted without it.**

This is a real weakening relative to J2 and it is forced by the axis, not chosen.

### 3.3 The repeat count: **R = 6**, and the minimum detectable effect that follows

The primary outcome is **binary per (arm, repeat)** on **one** task, so the unit of the
verdict is a 2 × 2 table with R per arm and the exact test is **Fisher's exact, two-sided,
α = 0.05**. Computed before the run:

| R | p for **total separation** (B0 all PASS, B1 all FAIL) | C(2R, R) |
|---|---|---|
| 3 | 0.1000 | 20 |
| **4** | **0.0286** | 70 |
| 5 | 0.0079 | 252 |
| **6** | **0.0022** | 924 |
| 8 | 0.0002 | 12,870 |

**R = 4 is the arithmetic minimum at which any verdict is reachable at all**: at R = 3 even
a perfect wipe-out gives p = 0.10. **R = 6 is declared**, for three reasons that are not
taste:

1. R = 4 has **zero margin** — one VOIDed repeat drops the arm to R = 3, where no result
   exists. R = 6 survives two VOIDs and still clears (R = 4 → p = 0.0286).
2. R = 6 is the smallest R that can separate anything **short of** total: at R = 6, B1 at
   1 / 6 gives p = 0.0152. At R = 4 only 0 / 4 clears.
3. R = 6 keeps the required ladder inside the wall-clock budget of §10.6 (12 runs).

**The minimum detectable effect, declared now.** At R = 6 with B0 at 6/6:

| B1 passes | p | verdict at α = 0.05 |
|---|---|---|
| 0 / 6 | 0.0022 | separable |
| 1 / 6 | 0.0152 | separable |
| 2 / 6 | 0.0606 | **not separable** |
| 3 / 6 | 0.1818 | not separable |

> **So this job is powered to detect "compaction destroys at least five runs in six" and
> nothing weaker.** A 50-percentage-point cost — B1 at 3/6 against B0 at 6/6 — is **NOT
> detectable at R = 6**; that would need **R = 10** (p = 0.0325). And a **single-repeat
> flip** (B0 R/R against B1 (R−1)/R) is **never** separable at any R below 60. This job is
> **pre-declared underpowered for anything but a catastrophic outcome effect**, and that is
> written here rather than discovered in the report. It is also why §4 gives the continuous
> axes equal standing: they are where a small effect would actually be visible.

### 3.4 The statistics, and a floor for each at its own grain

Invariant 8 binds: a floor and the statistic it gates share a grain. **Where a verdict
differs between grains, the run STOPS and the question is ESCALATED to the user — a grain
is never picked.**

| # | statistic | grain | its floor |
|---|---|---|---|
| S-1 | `oracle_outcome` → pass rate | per arm over R | Fisher exact p < 0.05 (§3.3). The 1/R = 0.1667 resolution is printed beside it. |
| S-2 | `context_tokens_sent` = Σ `prompt_eval_count` over the run's worker calls | per (arm, repeat), and the median over repeats | `max − min` of **B0's own** per-run totals over its R repeats, **and** the same computed on B1, **floor = max of the two** (J2's A7: gating on the lower rung alone was measured 3.506× more lenient than itself) |
| S-3 | `prompt_eval_duration` total — **the KV-cache axis, §4.2** | same as S-2 | same rule as S-2 |
| S-4 | `worker_calls` to termination | same as S-2 | same rule as S-2 |
| S-5 | `boundaries` | per (arm, repeat) | **reported, never gated** — it is the confound of §3.2, not a result |
| S-6 | `summarizer_input_tokens` / `summarizer_output_tokens` | per boundary and summed | reported in their own signed columns, **never summed with worker tokens** |

**Every byte and token column is SIGNED and never clamped at zero.** A boundary *adds* a
summary while removing turns; clamping would bias the total in the mechanism's favour.
Aggregation happens **before** any absolute value or floor is applied.

---

## 4. The axes are reported together and never netted

### 4.1 The three-way report

Every figure this job reports carries, in the same row: **the oracle outcome**, **the token
cost**, and **the boundary count**. A token saving at a lower pass rate is a **TRADE** and is
reported as a trade. Only a saving at an outcome within its floor may be called a
**reduction** — the same reservation J2's bar §4 makes, one axis over.

The mechanism's own consumption is never netted into the saving: `summarizer_input_tokens`
and `summarizer_output_tokens` are separate signed columns on a **different model at a
different price**, and the only composite permitted is the price-free break-even ratio

```
rho* = |Δ context_tokens_sent (B1 − B0)| / (summarizer_input_tokens + summarizer_output_tokens)
```

A single blended "net saving" number is **forbidden**.

### 4.2 A cost axis nobody has priced: a boundary invalidates the KV cache

Measured today, `qwen2.5:7b-instruct`, `/api/generate`, same 4,124-token prompt sent twice:

| call | `prompt_eval_count` | `prompt_eval_duration` |
|---|---|---|
| first (cold cache) | 4,124 | **13,615 ms** |
| second (identical prompt) | 4,124 | **36 ms** |

**378× on wall-clock for the same token count.** And the count is unaffected by the cache —
a growing prefix reports 4,124 → 4,128 → 4,132 for +1 and +2 appended lines, i.e. the exact
total, not a marginal count (§10.3).

> **Consequence, pre-registered: an append-only agent loop pays almost nothing to re-send
> its prefix, because the runtime caches it. Compaction REWRITES the prefix, which
> invalidates that cache, so every boundary buys a token reduction at the price of a full
> prompt re-evaluation.** This bar therefore reports `prompt_eval_duration` (S-3) **beside**
> `prompt_eval_count` (S-2) on every row, and **never** nets them. It is entirely possible
> for this job to measure a token saving and a wall-clock loss simultaneously; that outcome
> is named here so it cannot later be presented as a surprise or quietly dropped.

**This is not a prediction and must not be read as one.** It is a declaration that the axis
exists, that it is measurable with counters ollama already exposes, and that it will be
reported whichever way it comes out.

---

## 5. What would REFUTE, and what would CONFIRM

The claim under test, stated so it can fail: **"installing `context_compact` in a live agent
loop does not cost the task outcome."**

**R1 — the outcome refutation.** B1's pass rate is below B0's at Fisher exact p < 0.05
(§3.3). Reported with both arms' full per-repeat outcome vectors and both boundary counts.

**R2 — the tamper refutation.** B1 produces `FAIL-TAMPERED` runs that B0 does not. An agent
that has lost the instruction "do not edit any test file" to a summary, and then deletes a
test, is compaction costing the work in the most direct way available — and it is
detectable by GUARD-TAMPER without any judgement.

**R3 — the net refutation.** `rho* < 1`: the summarizer consumed more tokens than the
context saving, at equal price.

**R4 — the wall-clock refutation.** S-3 rises at B1 against B0 by more than its floor: the
mechanism costs more time than it saves, on the runtime it was measured on (§4.2).

**What would CONFIRM, and what confirmation would still not license.** Confirmation requires
**all six**: `B0 >= 4/6` on S-1, so the task is demonstrably reachable and §6 U-3 has not
fired; **B1's pass count not below B0's**; a token saving on S-2 that **exceeds its floor**;
**zero** `FAIL-TAMPERED` runs in any arm; `rho* >= 1`; and `boundaries >= 1` in at least 4 of
the 6 B1 repeats (§6 U-2). Even then the licensed sentence
is scoped to *(this task, this defect set, this worker, this summarizer, this trigger, this
repeat count)* and says only: "on the DEFECT-SET-5 repair task in `packages/shared` at
`81ac1a1`, `context_compact` at the §10.2 trigger removed N context tokens per run at an
unchanged oracle pass rate of k/6, having itself consumed S summarizer tokens." **It would
not license a claim about any other task, about a hosted model, or about compaction being
free.**

**What would NOT count as a refutation.** A tie at 6/6 vs 6/6 (that is §6 U-3, a null at a
declared minimum detectable effect, and it is NOT "compaction is free"). A single repeat's
flip (§3.3: never separable). A B2 or B3 figure quoted unconditionally. Any figure derived
from the mechanism's own `estimateTokens` (§10.3). A figure quoted without its boundary
count (§3.2).

---

## 6. The outcomes that are not refutations — UNINFORMATIVE, VOID, UNMEASURED

**UNMEASURED is a verdict (RB-P51). A check that quietly passes on data it cannot see is
not the same as one that reports it read nothing.**

**U-1 · UNINFORMATIVE-NO-BOUNDARY.** `boundaries == 0` in every B1 repeat. The mechanism
never acted; every arm is the same run and the delta is structurally zero. §1.5 says this
is a live risk, not a formality.

**U-2 · UNINFORMATIVE-THIN-BOUNDARY — the declared boundary floor.**

> **This job is declared UNINFORMATIVE unless at least 4 of the 6 B1 repeats reach
> `boundaries >= 1`.** The threshold is 4 and not a rounder number because it is tied to
> §3.3's arithmetic: below 4 informative repeats the arm falls under R = 4, the smallest R
> at which any Fisher verdict exists, so a verdict computed on 3 or fewer boundary-reaching
> repeats would be a verdict the design cannot support. The per-repeat boundary counts are
> printed either way.

**And `T` is NOT lowered afterwards.** §10.2 carries the standing refusal. Re-tuning a
pre-registered trigger after seeing that nothing fired manufactures an opportunity, which
is RB-P4 wearing a threshold's clothes.

**U-3 · UNINFORMATIVE-UNREACHABLE (floor effect).** B0 passes **0 / 6**. The task is beyond
the worker; every arm ties at zero for a reason that has nothing to do with compaction.
Reported as UNINFORMATIVE, explicitly not as "compaction does no harm".

**U-4 · NULL-AT-DECLARED-POWER (ceiling effect).** B0 and B1 both pass 6 / 6. Reported as
*"no measured outcome cost at n = 6, minimum detectable effect = 5 of 6 runs lost"* — with
the continuous axes S-2, S-3, S-4 still reported, because that is where a smaller effect
would be visible. **It is never reported as "compaction is free."**

**U-5 · VOID.** The arms are discarded and nothing is reported from them. VOID fires on any
of:

1. **D-1 fails** — the worker is not byte-deterministic on its declared configuration at
   fixed load state (§2.5).
2. **D-2 fails** — B0's CANON-1 turn stream is not byte-identical across its R repeats.
3. **Load-state drift.** Every ollama response's `load_duration` is recorded. A run in which
   the worker's load state changed mid-arm is VOID, because §2.2 measured that load state
   can change output bytes at identical token counts.
4. **Summarizer clamp.** See U-6 — the single most dangerous instrument failure this job
   faces.
5. **Oracle baseline drift.** The pristine worktree does not give ORACLE exit 0, or
   DEFECT-SET-5 applied does not give ORACLE exit 1 with 7 failing tests, or any of the five
   patterns does not occur exactly once.
6. **Worktree contamination.** `git -C <packnplan> status --short` shows anything other than
   the one pre-existing untracked file, or `git worktree list` is not clean at the end.

**U-6 · The summarizer-clamp VOID, measured today and named because it would otherwise be
silent.**

`DirectSummarizer` calls `/v1/chat/completions` and sends **no context-window parameter**.
Measured, on this machine, today:

- ollama serves `/v1/chat/completions` at **CONTEXT = 4096** by default (`ollama ps`).
- A **78,855-byte** prompt sent to that endpoint returns `usage: {prompt_tokens: 4096,
  completion_tokens: 8, total_tokens: 4104}` with `finish_reason: "stop"` — **no error, no
  warning, and the reported prompt-token count is exactly the window size.**

> **So `usage.prompt_tokens` from this endpoint is a CLAMPED count, not a prompt size. As
> shipped, a boundary would hand the summarizer ~19,660 tokens, the summarizer would see
> 4,096 of them, and both the mechanism and any harness reading `usage` would report a
> perfectly healthy call.** A harness that trusted that number would under-report the
> summarizer's consumption *and* would never learn that the summary was built from a fifth
> of the transcript. That is precisely RB-P51's shape: a check passing on data it cannot
> see.

Two declarations follow, both fixed now:

1. **The summarizer is served through a derived model tag with `PARAMETER num_ctx 32768`
   over the identical weight blob** (`sha256-2049f5674b1e92b4464e5729975c9689fcfbf0b0e4443ccf10b5339f370f9a54`,
   the blob `qwen2.5:14b-instruct` itself resolves to). Same weights, raised window; the
   blob sha is the identity check and U2 prints it. This is a **configuration** choice —
   `COMPACTION_LLM_MODEL` is an environment variable of the mechanism — not a modification
   of the mechanism.
2. **The clamp detector, from the output side.** For every summarizer call, if
   `usage.prompt_tokens == num_ctx` **exactly**, the input was clamped: that boundary is
   VOID and its repeat is VOID. This is cheap, it is exact, and it fires on the failure it
   is named for.

**U-7 · UNMEASURED-BUDGET.** B2, B3 or S1 not run within §10.6's wall-clock budget.
Reported with repeat count 0 and this reason, never as a null.

---

## 7. What this bar cannot read off the instruments that exist

1. **There is no harness.** Nothing in bantamkit drives an agent loop over ollama against a
   foreign worktree. U2 builds it, and **the same driving route must serve every arm** — one
   flag differs between rungs, not the route.
2. **The summarizer cannot be seeded through the shipped route** (§2.3), so B1's rows are
   not byte-reproducible and the committed rows **are** the record. A reproduction check may
   not re-run an arm and compare (§9).
3. **The mechanism has no tokenizer**: `src/session.ts` at `0a15cff` computes
   `return Math.ceil(text.length / 4);`, over UTF-16 code units. **It is never this job's
   axis** — it is the instrument grading itself. §10.3 declares a real one instead.
4. **`COMPACTION_PROACTIVE_PCT` is advisory in this mechanism, not a trigger.** The only
   automatic trigger is `nowPct`, default 85 (`src/config.ts` at `0a15cff`:
   `nowPct: envInt("COMPACTION_NOW_PCT", 85)`). The 60% figure is a *threshold this bar
   pins*, exactly as J2's bar pinned it — not the mechanism firing on its own. Stated so
   nobody reads §10.2 as "the mechanism's behaviour".
5. **`COMPACTION_TOKEN_BUDGET`, `COMPACTION_PROACTIVE_PCT`, `COMPACTION_NOW_PCT` and
   `COMPACTION_LIMIT_PCT` are invisible to the obvious `grep 'process\.env\.'`** — they are
   read through `envInt(name, fallback)` which indexes `process.env[name]`. Inherited from
   J2's bar §7(5) and **re-verified at `0a15cff` for this bar rather than cited**.
6. **The 18 pins into `compaction-mcp` cannot be resolved by any reader of this
   repository** — the mechanism repo is not vendored and CI never checks it out. RB-P50's
   trade, taken deliberately and declared: an immutable commit for the external thing, a
   pattern-delimited span for anything mutable, and the unverifiability said out loud. Every
   `compaction-mcp` reference in this bar quotes the **matched text**, not a line number, so
   it is checkable by search rather than by offset.
7. **Truncation direction is UNMEASURED.** §6 U-6 measured *that* the endpoint clamps and
   *that* it reports the clamped count as the prompt size. Which end of the prompt survives
   was **not** isolated — the probe's answer was inferable from the prompt's own pattern, so
   it is not evidence, and no claim about direction is made.

---

## 8. The accounting grain: named columns, signed

| # | column | grain | signed | for |
|---|---|---|---|---|
| 1 | `arm`, `repeat`, `worker_model`, `summarizer_model`, `summarizer_num_ctx`, `worker_num_ctx`, `temperature`, `seed`, `compaction_mode`, `recall_mode`, `mcp_commit`, `workload_commit`, `defect_set_id`, `trigger_id`, `canon_id` | every row | — | the declared configuration; a row without it is not evidence |
| 2 | `oracle_exit`, `guard_type_exit`, `guard_tamper_files`, `outcome` | per (arm, repeat) | — | §1.3, §1.4 — the six outcomes |
| 3 | `prompt_eval_count` | per worker call | signed | S-2, by the tokenizer of §10.3 |
| 4 | `eval_count` | per worker call | signed | the generation half, never summed with 3 |
| 5 | `prompt_eval_duration_ns`, `eval_duration_ns`, `load_duration_ns`, `total_duration_ns` | per call | — | S-3, and the load-state VOID check of §6 U-5(3) |
| 6 | `context_tokens_sent` | per (arm, repeat) | signed | Σ of 3 |
| 7 | `worker_calls` | per (arm, repeat) | — | S-4, and the turn cap |
| 8 | `boundaries` | per (arm, repeat) | — | **§3.2's confound; printed beside every figure** |
| 9 | `summarizer_input_tokens`, `summarizer_output_tokens` | per boundary and summed | signed | §4.1, `rho*` — **never summed with 3 or 4** |
| 10 | `summarizer_clamped` | per boundary | — | §6 U-6's detector: `usage.prompt_tokens == num_ctx` |
| 11 | `summary_chars`, `block_chars` | per boundary | signed | what the boundary **adds** |
| 12 | `canon_stream_sha256` | per (arm, repeat) | — | D-2's check |
| 13 | `files_touched_outside_defect_set` | per (arm, repeat) | — | GUARD-SCOPE, reported not gated |
| 14 | `void_reason` | per (arm, repeat) | — | empty is a measurement; a VOID row is never silently dropped |

**A column that reads 0 must be distinguishable from a column that is absent.** Zero is a
measurement; absent is the additive-field convention. A consumer that cannot tell them apart
reads an un-run arm as a null effect.

---

## 9. The reproduction check — over NAMED COLUMNS, never over bytes

Binding on U3 and U6, inherited in its closed form from J2's bar §9 (RB-P46):

1. The check compares **named columns** and the row count exactly. Never a whole-line byte
   identity.
2. **It does not re-run an arm.** §7(2) makes that not a preference: B1 is not
   byte-reproducible, so a re-run comparison could only ever fail.
3. Every key present on the regenerated side and absent from the committed side must appear
   in a **dated declaration**, and the residual key list must equal the committed list **in
   order**.
4. Two formalisations are forbidden by name, both measured to fail: *"ignore keys the
   committed file lacks"* passes an attacker who **deletes** a key, and *"a new trailing key
   is fine"* goes red on the honest case, because position cannot carry the rule.
5. **Committed evidence is never regenerated or retro-edited.** Corrections go in §12 as
   dated amendments.

**And the pinning discipline for this job's own claims (the v0.21.0 bar).** Every check the
closure rests on must have a **mutation that turns it red**, and **vacuity is counted from
the OUTPUT, not from the source** — J2 measured that a source-side grep under-counted its
own defect by more than 2× (RB-P48). The field program reports its own pinned-vs-unpinned
count as a number, not as "no red".

**No pytest node may assert a fact about this run** (RB-P14 Gate 2). Nodes assert a
*relation* between a column and the ledger that produced it, or that a column *moves* when
its input moves. **The suite is not evidence.**

---

## 10. The declared configuration — frozen now

### 10.1 Read at named commits

- **`compaction-mcp` at `0a15cff65c5c847af07b43de3b67d726433a4ca3`.** Verified before
  writing: `git diff --stat 0a15cff -- src SPEC.md` is **empty** in that working tree, so
  every quoted string below is the text at that commit. Quoted by **matched text**, not by
  line number (§7(6)):
  `return Math.ceil(text.length / 4);` · `temperature: 0.2,` (and no seed anywhere in
  `src/summarizer.ts`) · `defaultTokenBudget: envInt("COMPACTION_TOKEN_BUDGET", 128_000),` ·
  `proactivePct: envInt("COMPACTION_PROACTIVE_PCT", 60),` ·
  `nowPct: envInt("COMPACTION_NOW_PCT", 85),` ·
  `const mode = (process.env.COMPACTION_MODE as IntegrationMode) || "passthrough";` ·
  `baseUrl: process.env.COMPACTION_LLM_BASE_URL || "http://localhost:11434/v1",` ·
  `model: process.env.COMPACTION_LLM_MODEL || "qwen2.5-coder:14b",`
- **`packnplan-mono` at `81ac1a10e2230661ce10745a3a64f4da1d3819f2`**, with DEFECT-SET-5's
  five patterns each verified to occur exactly once (§1.2).
- **ollama 0.18.0**; `qwen2.5:7b-instruct` and `qwen2.5:14b-instruct` both report
  `context length 32768` under `ollama show`.

### 10.2 The trigger, and the standing refusal to tune it

> **A boundary fires on the first worker call at which the run's live context, measured by
> `prompt_eval_count` on the immediately preceding call, reaches `T`.**
>
> **`T = COMPACTION_PROACTIVE_PCT` (60, the mechanism's shipped default) ×
> `COMPACTION_TOKEN_BUDGET` (32,768) = 19,660 tokens.**

**`COMPACTION_AUTO=false`.** The mechanism's own automatic trigger is excluded for J2's
reason: it computes the trigger from the instrument's own `chars/4` estimate, which is
RB-P4 relocated into the trigger. **The harness triggers, using a real tokenizer.**

**Why the budget is 32,768 and not the mechanism's shipped 128,000, and why that is not
tuning.** 128,000 is larger than the worker's entire architectural context window, so it is
not merely untuned — it is **unreachable by construction** and would guarantee zero
boundaries. The budget is set to the window the worker is actually served at, which is the
only coherent reading of "the host's context budget", and that window is set to the model's
own architectural maximum measured by `ollama show`. Neither ground is a result.

**And why NOT a smaller window, which would fire more boundaries.** At `num_ctx = 8192`
(ollama's own serving default is 4096, measured) the task's ~25,900-token ceiling exceeds
the window, so **the runtime would truncate the prompt and the "null control" would be the
runtime's own FIFO truncation policy, not "compaction off"**. Invariant 5 requires the null
control to be *the same orchestration with compaction off*; at any window below the task's
ceiling it would not be, and B1 − B0 would measure "LLM summary versus FIFO truncation".
At 32,768 the ceiling (25,900 + the task prompt, ≈ 27k) fits, so no truncation occurs. That
is arithmetic, computed in §1.5 before the run.

> **THE STANDING REFUSAL. If the run comes out UNINFORMATIVE under §6 U-1 or U-2, `T` is NOT
> lowered, the budget is NOT lowered, and DEFECT-SET-5 is NOT enlarged.** That outcome is
> accepted and reported. A different `T` is a **new arm with a dated declaration**, reported
> separately, never as a re-run of this one.

### 10.3 The token counter — a real tokenizer, and why no fallback is needed

**`prompt_eval_count` from ollama's own response is the token axis.** It is the worker's own
tokenizer, and it was measured today to be a **total**, not a marginal count, and to be
**unaffected by KV caching**:

| probe | `prompt_eval_count` | `prompt_eval_duration` |
|---|---|---|
| a 4,124-token prompt, first send | 4,124 | 13,615 ms |
| the identical prompt, second send | **4,124** | **36 ms** |
| the same prompt + 1 appended line | **4,128** | 137 ms |
| the same prompt + 2 appended lines | **4,132** | 136 ms |
| an unrelated prompt of the same length | 4,124 | 13,253 ms |

So the count tracks the prompt exactly (+4 tokens per appended line) while the cache shows
up **only** in the duration. **J2's `UNMEASURED-IN-TOKENS` fallback is therefore not needed
by this job, and this bar declares no bytes-per-token divisor at all.** The mechanism's own
`estimateTokens` is never the axis (§7(3)).

**The one place `prompt_eval_count`'s sibling must NOT be trusted**: the OpenAI-compatible
`/v1` route's `usage.prompt_tokens` is clamped to the window (§6 U-6). The two are different
counters on different routes and this bar treats them differently.

### 10.4 CANON-1, the tool-output canonicalizer

Declared in §2.4, applied identically to every arm, to every tool output before it enters the
agent's context. Three rules, in order: scrub durations, `HH:MM:SS` timestamps and `[k/N]`
indices; sort the lines before the first ` FAIL ` header; sort the ` FAIL ` blocks by their
header. **Measured to take both the passing and the failing oracle output from 3 distinct
sha in 3 runs to 1.** `canon_id` rides on every row so a row can never be compared against a
row canonicalized by a different rule.

### 10.5 The models — both declared, neither under measurement

**WORKER: `qwen2.5:7b-instruct`, temperature 0, seed 7, `num_ctx = 32768`.** Two measured
reasons, both fixed before any arm: it is the model §2.2 measured to be **load-state
insensitive** (identical bytes warm-unseeded, warm-seeded and cold-seeded), and it is
**~3.1× faster** than the 14B on the same prompt (3.07 s vs 9.48 s warm, 220 predicted
tokens), which is what puts R = 6 × 2 arms inside the budget of §10.6.

**SUMMARIZER: `qwen2.5:14b-instruct`**, via `COMPACTION_SUMMARIZER=direct`, served through a
derived tag carrying `PARAMETER num_ctx 32768` over the identical weight blob
`sha256-2049f5674b1e92b4464e5729975c9689fcfbf0b0e4443ccf10b5339f370f9a54` (§6 U-6). Its
sampling is the mechanism's hard-coded `temperature: 0.2` with **no seed**, and it is
therefore the run's unpinnable component (§2.3). It is the same summarizer J2 used, which
keeps the two jobs' instruments comparable.

**Neither is the model under measurement.** The worker is the subject of the *task*; the
mechanism is the subject of the *measurement*.

`nomic-embed-text` is installed and is **not** used: `COMPACTION_RECALL_MODE=lexical`, for
J2's reasons — `auto` is a runtime branch and not a pre-declarable configuration, `embed`
caches by content hash and so depends on run order, and it would put a third model inside
the instrument.

### 10.6 The full declared configuration, and the budgets

```
COMPACTION_MODE=store                     # passthrough is additive by construction
COMPACTION_AUTO=false                     # §10.2 — the harness triggers, not the estimate
COMPACTION_SUMMARIZER=direct
COMPACTION_LLM_MODEL=<derived 14b tag, num_ctx 32768, blob sha256-2049f567...>
COMPACTION_RECALL_MODE=lexical
COMPACTION_HOOKS_ENABLED=false            # hooks inject arbitrary shell output — unmeasured input
COMPACTION_TOKEN_BUDGET=32768             # §10.2
COMPACTION_PROACTIVE_PCT=60               # shipped default, untuned

worker      qwen2.5:7b-instruct   temperature 0   seed 7   num_ctx 32768
summarizer  qwen2.5:14b-instruct  temperature 0.2 (hard-coded)  no seed  num_ctx 32768
repeats     R = 6 per arm
turn cap    40 worker calls per run   -> exceeding it is FAIL-CAP, not FAIL
run cap     20 minutes wall-clock per run -> exceeding it is VOID (harness fault, not agent)
job budget  the required ladder is B0 and B1 at R = 6 = 12 runs. B2, B3 and S1 are
            UNMEASURED-BUDGET if not reached.
tool roster the agent gets exactly: read a file, write a file, list files, run the ORACLE.
            A different roster is a different experiment and gets its own declaration.
```

---

## 11. Limitations, recorded rather than buried

1. **One task, one defect set.** n = 1 on the task axis. Nothing here generalises to another
   task, and the per-repeat outcome vector is printed beside every rate.
2. **Pre-declared underpowered.** At R = 6 the minimum detectable outcome effect is "5 of 6
   runs lost" (§3.3). A 50-point cost is invisible; it would need R = 10. A single-repeat
   flip is never separable at any R below 60.
3. **BOUNDARY-THIN by arithmetic** (§1.5): one or two boundaries at best, and a competent
   agent may reach zero. §6 U-2 declares the floor at 4 of 6 repeats.
4. **RB-P39's confound is present, not eliminated** (§3.2): live arms cannot share an
   injected schedule, so boundary counts differ between arms and every figure carries its
   boundary count.
5. **B1 is not byte-reproducible** and cannot be made so without modifying the mechanism
   (§2.3). The committed rows are the record.
6. **The summarizer's variance and compaction's effect enter the same column** and are not
   separable except by the optional S1 decomposition (§2.5).
7. **The KV-cache axis (§4.2) is a property of this runtime**, not of compaction in general.
   A hosted endpoint bills tokens and this one bills time; the two axes are reported
   separately for that reason and are never netted.
8. **`packages/shared` is pure domain logic with no I/O.** It is the only part of this
   monorepo scoreable without a database, and it is therefore *not* representative of the
   monorepo. Nothing here generalises to `apps/api` or `apps/web`.
9. **A measured negative, an UNINFORMATIVE run, or a VOID run closes this job as
   legitimately as a saving.** None of them licenses re-tuning anything in §10.2.
10. **This bar is a rule set, not a result.** Any of it may be wrong; the response is an
    amendment in §12, never an edit above.

---

## 12. Amendments

Amendments are appended here, dated, with §0–§11 left untouched.

*(none yet)*
