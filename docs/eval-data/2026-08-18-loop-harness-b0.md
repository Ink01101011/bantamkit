# The loop harness, and B0 — what the null control actually does

**Dated 2026-08-18. U2 of job `compaction-in-the-loop`.** The bar is
`docs/eval-data/2026-08-18-loop-bar-preregistration.md`, committed at **`c323664`** before
this harness existed. Nothing here amends it. Where a measurement contradicts it, the
contradiction is written down as an **escalation** and the bar's text is left exactly as it
is — §12 of the bar is the only place a correction may land, and it is not this unit's to
write.

This is a **record of a measurement**: amend it by a dated appendix, never by an edit.

Every number below came off a counter on this machine today. Token counts are ollama's own
`prompt_eval_count` / `eval_count` / `usage.prompt_tokens`, **with the route named beside
each** (invariant 14 as U1 corrected it). Durations are ollama's nanosecond fields or a
monotonic clock around the HTTP call. Exit codes are `$?`. Byte counts are `len(...encode())`.
Nothing is a self-estimate; where no counter exists it says **UNMEASURED**.

---

## 0. The verdict, first

**B0 ran to completion at R = 6. It cleared the boundary floor and it is still not usable as
an arm.** Both halves are measurements, and they are not in tension:

| | |
|---|---|
| bar §6 U-2's floor, `boundaries ≥ 1` in ≥ 4 of 6 | **cleared — 6 of 6**, first boundary at turn 17–18 of 40 |
| `outcome` | **VOID ×6**, `stopped_by = run-cap`, `wall_s` 1200.00x |
| D-1 | **holds** |
| D-2 | **fails — 6 distinct of 6**, and §3.2 measures the cause to be CANON-1, not compaction |
| is the arm "compaction off" as bar §3.1 defines it? | **no** — `worker_window_reached` is **true in 6 of 6** and `max_prompt_eval_count` is **exactly 32,768** in 6 of 6, so past turn ~19 the arm is compaction-off *plus the runtime's own FIFO truncation*, which is the confound bar §10.2 refused in advance |

**Status: ESCALATION-CLASS, on three independent grounds that a re-run reproduces. §3.6 states
it against the bar clause that decides it.** Nothing was re-run, no frozen constant was moved,
and the six rows were not regenerated.

### 0.1 The boundary count

**The loop does reach `T`, and it reaches it early — U1's arithmetic was right about the
numbers and wrong about the trajectory.**

Bar §1.5 computed, before any run, that an agent reading every implementation file once and
running the oracle once accumulates **0.74 × T** and *"never reaches a boundary at all"*, and
called the job BOUNDARY-THIN. That is arithmetic over **a trajectory this worker does not
produce.** The realised B0 trajectory is oracle-heavy — it re-runs the ORACLE far more often
than it reads a file — and §1.5's own second line is the one that binds: *"nine oracle runs
and no file read at all would reach `T`."*

*(the per-repeat numbers and the verdict against bar §6 U-2's "≥1 boundary in at least 4 of
6" floor are in §3.1)*

**And the same arithmetic that gets the loop to `T` carries it past the worker's window.**
`T` = 19,660 is 60% of a 32,768-token budget served at a 32,768-token window, so a run that
passes `T` at all has only 13,108 tokens of headroom before the runtime starts truncating —
about four more oracle runs. Bar §10.2 chose `num_ctx = 32768` precisely so the task's
ceiling would fit and *"no truncation occurs"*; on the realised trajectory it does not fit.
Past that point the null control is the runtime's own FIFO truncation, which §10.2 named as
the thing that would stop B1 − B0 measuring compaction. **That is an escalation, and it is
§3.4.**

---

## 0.5 Disclosure: a pilot ran before the recorded arm, and what it changed

**One B0 repeat was run as a pilot before the recorded arm, with `--write` absent, and it
wrote nothing.** It was killed at turn 21. It is disclosed here rather than omitted, because
two things about the harness changed after it:

1. **The declared run cap was made enforceable.** Bar §10.6 declares a 20-minute wall-clock
   run cap whose breach is VOID. The loop checked it only *between* calls, and the pilot
   showed a single worker call past the window costs **235.9 s**, so the declared cap could
   never fire. The remaining budget is now the HTTP timeout. This enforces a cap the bar
   already declared; it does not add, remove or move one.
2. **`VOID` was made to outrank `FAIL-TAMPERED`** in the outcome ladder, because bar §6 U-5
   discards a VOID repeat entirely and a run that never terminated cannot also be scored on
   the tree it left behind. Committed separately at `220a662`.

**Nothing about the experiment moved.** `T` is 19,660 and was not lowered. DEFECT-SET-5 was
not re-cut. The task text, the oracle, the worker, the seed, the temperature, the turn cap,
the repeat count and the arm definition are exactly as bar §10.6 froze them. Both changes
are to the *instrument's fidelity to the bar*, and both are in the git history with their
reasons.

---

## 1. What was built

`docs/eval-data/2026-08-18-loop-harness.py` — one program, eight sub-commands, and the
**same driving route for every arm** (bar §7(1)): `POST /api/generate`, the whole
conversation rendered into one append-only prompt, one action per turn.

| sub-command | what it answers |
|---|---|
| `check-oracle` | bar §1.3's table, and bar §6 U-5(5)'s VOID condition |
| `canon` | bar §2.4's CANON-1 table, and rule (a)'s measured activity on source |
| `d1` | **D-1** — model determinism on the actual worker configuration |
| `window` | bar §6 U-6's clamp and the derived-tag fix, from the output side |
| `clamp` | both counters, one prompt, several windows — see §2.5 |
| `run` | one arm at R repeats; `--write` is required before anything is written |
| `d2` | **D-2** — B0's prompt-stream determinism over a committed rows file |
| `selfcheck` | the output-side falsifier for §3.5 — no network, no worktree, 15 cases |

**A bare invocation writes nothing and exits 2**: `error: the following arguments are
required: cmd`. RB-P49's two offenders overwrote their own committed `.jsonl` and exited 0;
here the read-only mode is the default and the destructive one is the flagged one.

The agent's tool roster is exactly bar §10.6's four — `LIST`, `READ`, `WRITE`, `ORACLE` —
plus `DONE` to terminate. A different roster is a different experiment.

---

## 2. The instrument checks, in the order the bar requires them

### 2.1 The oracle baseline — bar §1.3 reproduces exactly

```
docs/eval-data/2026-08-18-loop-harness.py check-oracle
```

```
  pristine  ORACLE exit=0  Test Files  10 passed (10) | Tests  141 passed (141)
  pristine  GUARD-T exit=0
  DEFECT-SET-5: all 5 patterns occurred exactly once
  defected  ORACLE exit=1  Test Files  5 failed | 5 passed (10) | Tests  7 failed | 134 passed (141)
  defected  GUARD-T exit=0
  GUARD-TAMPER: empty
  GUARD-SCOPE : 5 files
  VERDICT: baseline holds
```

Every cell of bar §1.3's table, and every one of the five patterns occurring exactly once.
The ORACLE **discriminates** and bar §6 U-5(5) does not fire.

### 2.2 D-1 · model determinism — **HOLDS**, on the configuration that will be run

```
docs/eval-data/2026-08-18-loop-harness.py d1 --repeats 6
```

`qwen2.5:7b-instruct`, temperature 0, seed 7, `num_ctx` 32768, route `/api/generate`,
6 repeats, on **the harness's own turn-1 prompt** rather than a neutral one — D-1 measured
off the axis that matters is D-1 measured on the wrong prompt.

```
    r0 sha=8822dc341a34 prompt_eval=233 eval=5 load_ns=4534026500 wall=5.317s
    r1 sha=8822dc341a34 prompt_eval=233 eval=5 load_ns=  64653459 wall=0.184s
    r2 sha=8822dc341a34 prompt_eval=233 eval=5 load_ns=  55321208 wall=0.173s
    r3 sha=8822dc341a34 prompt_eval=233 eval=5 load_ns=  56296459 wall=0.174s
    r4 sha=8822dc341a34 prompt_eval=233 eval=5 load_ns=  56795167 wall=0.168s
    r5 sha=8822dc341a34 prompt_eval=233 eval=5 load_ns=  56662792 wall=0.177s

  distinct response sha256 : 1
  distinct eval_count       : 1
  distinct prompt_eval_count: 1
  D-1: HOLDS
```

r0's `load_duration` is 4.53 s against 55–65 ms for r1–r5, so the six calls span **two load
states** and still returned one sha — which is bar §2.2's measured reason for choosing the
7B, re-observed here on the real configuration rather than cited.

### 2.3 CANON-1 — bar §2.4's table reproduces exactly

```
docs/eval-data/2026-08-18-loop-harness.py canon --repeats 3
```

```
  passing  raw 3 distinct of 3   CANON-1 1 distinct of 3
  failing  raw 3 distinct of 3   CANON-1 1 distinct of 3
  rule (a) on the 22 implementation files: 0 matches of all three patterns combined
```

> **This measurement does not survive a fourth repeat, and it is left standing here as the
> record of what was measured at 3.** `--repeats 4` gives `failing … CANON-1 2 distinct of 4`.
> The reading "CANON-1 collapses the failing output" is refuted in §3.2 and filed as **N-9**;
> the `passing` row still holds at 4. Three repeats was not enough to see it.

### 2.4 The window fix — proven **from the output side**

Bar §6 U-6 declares a derived tag at `PARAMETER num_ctx 32768` over the identical weight
blob, plus the output-side detector `usage.prompt_tokens == num_ctx ⇒ VOID`.

The tag built for this job is **`bk-j7-qwen2.5-14b-ctx32768`**, and
`ollama show --modelfile` reports its `FROM` as
`/Users/kktest/.ollama/models/blobs/sha256-2049f5674b1e92b4464e5729975c9689fcfbf0b0e4443ccf10b5339f370f9a54`
— the blob the bar names, byte-identical weights.

One fixed **92,569-byte** prompt, route `/v1/chat/completions`, `max_tokens 8`:

| model | served window | `usage.prompt_tokens` | == window? | detector |
|---|---|---|---|---|
| `qwen2.5:14b-instruct` (as shipped) | 4096 | **4096** | YES | **VOID-CLAMPED** |
| `bk-j7-qwen2.5-14b-ctx32768` | 32768 | **24138** | no | **OK** |

**That is the fix, from the output side: a prompt longer than the old window comes back with
a `prompt_tokens` that is not the window** — 24,138 against a 32,768 window, 5.89× what the
shipped configuration reported for the same bytes. `ollama ps` showed `CONTEXT 4096` for the
base tag and `CONTEXT 32768` for the derived one while each call was in flight.

### 2.5 …and the same clamp is on the route the bar called honest — **ESCALATION**

Bar §10.3 and invariant 14 both name `/api/generate`'s `prompt_eval_count` as the honest
counter, in contrast to `/v1`'s clamped `usage.prompt_tokens`. **That contrast is not the
real rule.** One fixed **72,169-byte** prompt — **20,538 tokens** where anything measures it honestly —
across five (route, model, window) cells:

| route | model | `num_ctx` | reported | == window? | verdict | wall |
|---|---|---|---|---|---|---|
| `/api/generate` | `qwen2.5:7b-instruct` | 2048 | **2048** | YES | VOID-CLAMPED | 7.9 s |
| `/api/generate` | `qwen2.5:7b-instruct` | 8192 | **8192** | YES | VOID-CLAMPED | 28.7 s |
| `/api/generate` | `qwen2.5:7b-instruct` | 32768 | **20538** | no | **OK** | 96.7 s |
| `/v1/chat/completions` | `qwen2.5:14b-instruct` | 4096 | **4096** | YES | VOID-CLAMPED | 45.4 s |
| `/v1/chat/completions` | `bk-j7-qwen2.5-14b-ctx32768` | 32768 | **20538** | no | **OK** | 217.1 s |

**The two routes agree to the token — 20538 and 20538 — the moment the prompt fits, on two
different models.** They disagree only where one of them is clamped. So the axis is the
window and the route is a red herring.

> **The rule is the WINDOW, not the ROUTE. `prompt_eval_count` is an honest total only while
> the prompt FITS; at or above `num_ctx` it reports exactly `num_ctx`, with no error and no
> warning — the identical failure that RB-P53 filed against `/v1`.** The output-side detector
> the bar declares for the summarizer therefore has to be applied to the **worker** as well,
> and this harness records `worker_window_reached` per run for exactly that reason.

The check is not a tautology (RB-P47): the disagreement input is **a window the prompt fits
inside**, where an honest counter must report the prompt and a clamped one cannot. That
window is in the table.

### 2.6 The D-2 checker, and the mutation that turns it red

The v0.21.0 pinning bar: a check counts only when a mutation that falsifies it turns red a
node the claim named. `d2` reads the committed rows and compares `canon_stream_sha256` across
repeats.

| input | output | exit |
|---|---|---|
| six repeats, one stream sha | `1 distinct of 6 -> D-2 HOLDS` | **0** |
| the same file with **repeat 3's** sha changed | `2 distinct of 6 -> D-2 FAILS -> VOID`, and it prints `repeats [3]` | **1** |

The mutation turns it red **and names the repeat**, so the check is not vacuous and its
failure is locatable.

---

## 3. B0 — the null control

`compact-off`: the full orchestration with `context_compact` never called (bar §3.1), not
the absence of orchestration. Rows:
`docs/eval-data/2026-08-18-loop-b0-compact-off.jsonl`, one JSON object per (arm, repeat),
written only because `--write` was given.

Command:

```
docs/eval-data/2026-08-18-loop-harness.py run --arm compact-off --repeats 6 \
  --write docs/eval-data/2026-08-18-loop-b0-compact-off.jsonl
```

Launched detached from this session's process group (macOS has no `setsid(1)`; a
double-`fork` + `os.setsid()` launcher does the same job) so a tool timeout could not reap a
multi-hour arm.

### 3.1 Per repeat — R = 6, every column read back off the committed rows

| rep | worker calls | first boundary turn | `boundaries` | max `prompt_eval_count` | `context_tokens_sent` | `eval_tokens_total` | ORACLE exit | GUARD-T exit | tamper files | wall s | outcome |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 21 | 17 | 6 | **32768** | 293,003 | 7,067 | 1 | 2 | 2 | 1200.004 | **VOID** |
| 1 | 23 | 18 | 7 | **32768** | 334,702 | 8,271 | 1 | 2 | 1 | 1200.005 | **VOID** |
| 2 | 22 | 17 | 7 | **32768** | 313,944 | 6,807 | 1 | 2 | 1 | 1200.005 | **VOID** |
| 3 | 22 | 17 | 7 | **32768** | 314,650 | 9,505 | 1 | 2 | 3 | 1200.005 | **VOID** |
| 4 | 22 | 18 | 6 | **32768** | 301,914 | 7,882 | 1 | 2 | 1 | 1200.004 | **VOID** |
| 5 | 21 | 17 | 6 | **32768** | 303,163 | 8,213 | 1 | 2 | 2 | 1200.005 | **VOID** |

Route `/api/generate` on every token figure; `worker_num_ctx` 32,768; seed 7;
temperature 0.0; `trigger_id` `T=19660/prompt_eval_count/preceding-call`;
`canon_id` `CANON-1/oracle-full+read-rule-a`; `workload_commit` `81ac1a1…`;
`compaction_mode` `off` on all six.

**Against bar §6 U-2's floor — "UNINFORMATIVE unless ≥1 boundary in at least 4 of the 6
repeats" — the floor is cleared: `boundaries ≥ 1` in 6 of 6, and `first_boundary_turn` is
17 or 18 of a 40-turn cap.** So the job is **not** UNINFORMATIVE for want of boundaries, and
bar §1.5's BOUNDARY-THIN prediction (§0, N-7) is refuted by the run rather than argued with.
Read `boundaries` with §6 item 4: in B0 it is a **dwell count**, not an event count.

**But every one of the six is VOID, so no repeat contributes an outcome.** The floor that
decides UNINFORMATIVE is cleared and the arm still measures nothing about repair, for the two
instrument reasons in §3.4 and §3.5. `boundaries ≥ 1` is a statement about the *instrument
reaching its trigger*; it is not a statement about the *task being scorable*.

#### 3.1.1 Where the growth came from — measured, not assumed

Bar §1.5 modelled the trajectory as **implementation read once (12,243) + one failing oracle
(2,253) = 0.74 × T**. The mechanism that actually gets the run to 32,768 is neither of those
terms. Each consecutive `prompt_eval_count` delta is charged to the turn whose action and
result produced it, and the ORACLE turns are identified by the fact that **the identical
5-token action text is re-emitted 8 or 9 times per run** (`response_sha256` repeats):

| rep | ORACLE appends | tokens from ORACLE | other appends | tokens from everything else | ORACLE share |
|---|---|---|---|---|---|
| 0 | **8** | **27,668** | 10 | 4,867 | **85.0 %** |
| 1 | **9** | **26,145** | 11 | 6,390 | **80.4 %** |
| 2 | **9** | **26,666** | 10 | 5,869 | **82.0 %** |
| 3 | **8** | **26,556** | 11 | 5,979 | **81.6 %** |
| 4 | **9** | **26,149** | 11 | 6,386 | **80.4 %** |
| 5 | **8** | **27,055** | 10 | 5,480 | **83.2 %** |

> **Four fifths of the context is one tool's output, re-appended eight or nine times.**
> "Everything else" — the LIST, every file READ, and the worker's own WRITE bodies echoed
> back as history — never exceeds **6,390** tokens in any repeat, against the bar's 12,243
> for reading the implementation. **The run never read the implementation.** It reached the
> window on oracle output.

Two independent errors in the pre-run arithmetic, in **opposite** directions, and the second
is the larger:

1. **The oracle's per-append cost was right for the first append and wrong afterwards.** In
   repeat 0 the first ORACLE result costs **2,231 tokens** — within 1 % of bar §1.5's 2,253,
   so the bar's *measurement* reproduces. It then grows to **3,687** and stays there
   (deltas 2,231 → 3,350 → 3,671 → 3,722 → 3,682 → 3,682 → 3,682 → 3,608), because the
   worker's own edits lengthen the failure output. **1.64 × the modelled figure at steady
   state.**
2. **The repeat count was modelled as 1 and is 8–9.** This is the whole of the discrepancy
   in order of magnitude: 8 × 3,687 = 29,496, which is 1.50 × T on oracle output alone.

So the pre-run arithmetic under-predicted growth because it modelled an **optimal**
trajectory — read each file once, run the oracle once, stop. The realised loop is a
**retry** trajectory: it re-emits the identical ORACLE action, gets a nearly identical
result, appends it, and does it again. Bar §1.5's own second line is the one that describes
it: *"nine oracle runs and no file read at all would reach `T`."* **That is measured to be
almost exactly what happens — 8 or 9 oracle runs, and the implementation never read.**

### 3.2 D-2 · prompt-stream determinism — **FAILS, and the cause is the ORACLE, not the model**

```
docs/eval-data/2026-08-18-loop-harness.py d2 \
  --rows docs/eval-data/2026-08-18-loop-b0-compact-off.jsonl
```

`canon_stream_sha256` is **6 distinct of 6** → **D-2 FAILS**. The whole-run sha is a blunt
instrument, so the per-turn `prompt_sha256` and `response_sha256` in each row's `calls`
sub-array locate the divergence:

| rep | calls | first turn whose **prompt** differs from rep 0 | first turn whose **response** differs |
|---|---|---|---|
| 0 | 21 | — | — |
| 1 | 23 | **4** | 6 |
| 2 | 22 | **4** | 6 |
| 3 | 22 | 12 | 12 |
| 4 | 22 | **4** | 6 |
| 5 | 21 | **4** | 8 |

**In four of the five comparisons the prompt diverges at turn 4 while the worker's own
output is still byte-identical through turn 5.** A prompt can only differ from a tool
result, and turn 3 is the first ORACLE in every repeat. `tool_list` sorts, the ERROR string
is a constant, and D-1 is separately measured to hold (§2.2) — so **the divergence enters
through the canonicalised oracle output**, on an identical tree, at the first oracle call.

**§2.3's "failing → CANON-1 1 distinct of 3" does not hold at 4 repeats. Re-measured today,
same worktree, same command with `--repeats 4`:**

```
  passing  raw 4 distinct of 4   CANON-1 1 distinct of 4
  failing  raw 4 distinct of 4   CANON-1 2 distinct of 4
```

> **CANON-1 collapses the *passing* oracle output and does not collapse the *failing* one.**
> Bar §2.4's table records 1-of-3 for both, and at 3 repeats that reproduced; at 4 it does
> not. **The failing output is the one every arm actually reads** — the run is a repair task,
> so the oracle fails on almost every call — which makes this the residual that propagates.
> It is a defect in CANON-1's specification, not in this harness's application of it, and it
> is **N-9**.

**The residual, isolated.** Five failing-oracle runs on the identical defected tree,
canonicalised, diffed against the first:

```
  run 0: exit=1 canon_bytes=6168      run 1 DIFFERS from run 0 -- 9 diff lines
  run 1: exit=1 canon_bytes=6168      run 2 == run 0
  run 2: exit=1 canon_bytes=6168      run 3 DIFFERS from run 0 -- 9 diff lines
  run 3: exit=1 canon_bytes=6168      run 4 == run 0
  run 4: exit=1 canon_bytes=6168
```

```
@@ -105,2 +105,3 @@
 
+
  FAIL  src/expense/split/split.test.ts > splitByPercent > splits by percentage, …
@@ -174,2 +175 @@
 
-
```

**Every run is 6,168 bytes. The difference is one blank line that moves from line 175 to
line 106.** CANON-1's rule (b) sorts the lines *before* the first ` FAIL ` header and rule
(c) sorts the ` FAIL ` *blocks* by their header line — **neither rule says anything about
blank lines**, so a blank line that vitest emits at the tail of one block instead of the head
of the next migrates between two blocks and both rules preserve it where it landed. Same
bytes, different string, different sha.

The committed rows carry the same signature independently, which is the confirmation:

| | turn-4 `prompt_bytes` | turn-4 `prompt_eval_count` | turn-4 `prompt_sha256` |
|---|---|---|---|
| rep 0 | 8,603 | 2,790 | `bccd6d9bbd50` |
| rep 1 | 8,603 | 2,790 | `7d4388440a12` |
| rep 2 | 8,603 | 2,790 | `7d4388440a12` |
| rep 3 | 8,603 | 2,790 | `bccd6d9bbd50` |
| rep 4 | 8,603 | 2,790 | `7d4388440a12` |
| rep 5 | 8,603 | 2,790 | `0c30895cc459` |

> **Identical byte count, identical token count, three distinct sha.** A divergence that
> preserves length exactly is a **permutation**, not a content difference — which is the
> blank line, and rules out every hypothesis in which the model, the tree or the tool
> arguments differ. `prompt_eval_count` is 2,790 in all six, so the *measurement* axis the job
> cares about is unaffected; only the **identity** axis D-2 tests is.

The narrow fix is a CANON-1 rule (d) — drop or collapse blank lines before rules (b) and (c)
— and it is one line. **It is not applied here**, because CANON-1 is pre-registered in bar
§2.4 and §10.4 and adding a rule to it changes what every arm reads. Escalation, not edit.

**Consequence for the bar's own reasoning.** Bar §2.5 makes D-2 a *required* invariant whose
failure is VOID, and it fails here for a reason that has nothing to do with compaction: the
instrument's own canonicalisation is incomplete. D-2 cannot discriminate "compaction
perturbed the stream" from "the oracle perturbed the stream" until CANON-1 closes over the
failing output. **This is escalation-class and is not fixed here** — completing CANON-1 is an
edit to a pre-registered canonicalisation rule, which is the bar's, not this unit's.

### 3.3 D-3 · outcome determinism — observed, NOT required

Bar §2.5 is explicit: **D-3 is not required, it is measured, and it IS the noise floor.**
This unit's own `verify` string in the checkpoint says the null control must be "deterministic
on every outcome column", which is D-3. **The bar wins.** Outcome variation, where it exists,
is the floor for the statistic it gates, at that statistic's own grain — it is not a defect.

**Observed.** On the columns the bar would score:

| column | distinct values over 6 repeats | values |
|---|---|---|
| `outcome` | **1** | VOID ×6 |
| `oracle_exit` | **1** | 1 ×6 |
| `guard_type_exit` | **1** | 2 ×6 |
| `max_prompt_eval_count` | **1** | 32,768 ×6 |
| `worker_window_reached` | **1** | true ×6 |
| `stopped_by` | **1** | `run-cap` ×6 |
| `boundaries` | **2** | 6, 7, 7, 7, 6, 6 |
| `first_boundary_turn` | **2** | 17, 18, 17, 17, 18, 17 |
| `worker_calls` | **3** | 21, 23, 22, 22, 22, 21 |
| `guard_tamper_files` (count) | **3** | 2, 1, 1, 3, 1, 2 |
| `context_tokens_sent` | **6** | 293,003 … 334,702 |
| `canon_stream_sha256` | **6** | all distinct |

D-3 is **not** required, so none of this is a verdict. Reported because the spread *is* the
noise floor for anything U3 computes at this grain: `worker_calls` varies by **±1 turn**,
`context_tokens_sent` by **14 %** (334,702 / 293,003), and `guard_tamper_files` by **3×**.
Any B1 − B0 effect smaller than that spread is not measurable with R = 6.

**And the outcome columns are unanimous for a reason that removes their information.** Six
identical VOIDs is not "the null control is stable", it is "the null control failed the same
way six times". The columns that *would* have carried a repair signal — `oracle_exit`,
`guard_type_exit` — are pinned at 1 and 2 because no repeat ever finished.

---

## 3.5 The two instrument defects closed in this write-up's own harness

Both were found in the harness **after** the six rows existed, so neither could be closed for
free. Each is closed for future arms, and each is quantified against the committed rows.

### 3.5.1 `stopped_by` conflated "the cap was exceeded" with "the endpoint raised"

The loop's exception clause was:

```
except (TimeoutError, urllib.error.URLError, OSError) as exc:
    stopped_by = "run-cap"
    timeout_exc = f"{type(exc).__name__}: {exc}"
```

and the row's reason was `f"run-cap ({RUN_CAP_S}s) {timeout_exc}"`. **Any** failure the
endpoint could raise — a refused connection, a reset socket, a DNS error, at any elapsed time
— was therefore reported as the declared 1,200-second cap. A run of thirty seconds would
have reported `run-cap (1200s)`, with the VOID real and **the reason fabricated by the
label**.

**On these six rows the label happens to be substantively correct, and the artifact proves
it from a second counter.** `wall_s` is **1200.004–1200.005 on all six**, and the runs are
internally consistent with that: `prompt_eval_duration_ns` + `eval_duration_ns` alone is
554–790 s + 221–329 s per repeat, before the oracle subprocesses. The cap really was reached,
and it bound **through** the HTTP timeout, because `generate`'s timeout is set to the
remaining budget — which is the design the harness documents. **So the six rows are not
mislabelled; the instrument that produced them could not have told you if they were.**

Closed:

- the exception clause now decides from the measured elapsed time —
  `stopped_by = "run-cap" if elapsed >= RUN_CAP_S - CAP_TOL_S else "endpoint-error"`, with
  `CAP_TOL_S = 1.0` s of scheduling slop;
- `endpoint-error` is its own `stopped_by` value and both still map to `VOID`, because both
  are instrument verdicts — **they are just not the same instrument verdict**;
- `void_reason` now carries **the measured elapsed time inside the string**
  (`run-cap (1200s) exceeded at wall 1200.004s`, or
  `endpoint-error at wall 29.994s, well inside the 1200s run cap: …`), so a reader can check
  the claim against `wall_s` without trusting the label;
- new column **`endpoint_error`** holds the exception text on its own.

### 3.5.2 S5 — `done_reason` was compared to nothing, and a truncated WRITE was silently complete

`SHAPE-silent-truncation` §S5. `generate()` stored `done_reason` and the string `"length"`
did not occur anywhere in the file, while `parse_action()` fell back to
`e = len(rest[s + 1:])` when the `>>>` terminator never arrived — so a WRITE cut off by
`NUM_PREDICT = 2048` was handed to `tool_write`, written to disk and reported as
`OK: wrote N bytes`. The task text says a WRITE replaces the whole file, so a cut completion
is a truncated file: the repair fails the oracle and scores **`FAIL` — an outcome** — where an
instrument event should score **VOID**. That inverts the rule commit `220a662` exists to
enforce.

**What it did to these six rows — the census, off the committed `calls` sub-arrays:**

| rep | worker calls | `done_reason: stop` | `done_reason: length` | the length-stopped turns |
|---|---|---|---|---|
| 0 | 21 | 21 | **0** | — |
| 1 | 23 | 23 | **0** | — |
| 2 | 22 | 22 | **0** | — |
| 3 | 22 | 20 | **2** | 21, 22 |
| 4 | 22 | 21 | **1** | 22 |
| 5 | 21 | 20 | **1** | 20 |
| **all** | **131** | **127** | **4** | |

**The defect fired: 4 of 131 worker calls stopped on the output cap, in 3 of the 6 repeats.**
All four are bounded in the same way, and the bound is what makes the damage assessable:

- all four have `eval_count` exactly **2048** — `NUM_PREDICT`, so they are cap cuts and not
  a model that chose to stop;
- all four have `prompt_eval_count` exactly **32768** — they occur *after* the window was
  already saturated;
- all four have `boundary_before_this_call: true`;
- all four are at **turn 20, 21 or 22** — the last one or two turns before the run VOIDs.

**What it does to B0's status: nothing, and that is a measured statement rather than a
convenient one.** Every one of the six repeats is already `VOID` for `run-cap`, and `run-cap`
outranks `VOID-TRUNCATED` in the ladder, so no row's `outcome` would change under the fixed
harness. Re-derived through the new `classify_outcome` with each row's own
(`stopped_by`, tamper, `oracle_exit`, `guard_t`) and its measured truncations, all six return
`VOID` — the same value the committed rows carry. **The committed artifact is not
retro-actively wrong.**

What it *does* mean:

1. **Repeats 3, 4 and 5 contain a worker output the runtime cut in half, and their trees
   contain whatever that cut produced.** Their `canon_stream_sha256` and their
   `guard_tamper_files` (3 files in repeat 3, the largest of the six) are downstream of a
   truncated completion. Those three rows may not be cited for anything about *what the model
   did*; only for what the instrument did.
2. **Had the run cap not fired first, `FAIL` is what these three would have scored** — which
   is exactly the inversion S5 named. The rows are evidence that the defect was live, not
   theoretical.
3. The artifact is **not regenerated to make it clean.** It records what the instrument did on
   2026-08-18.

Closed, from the output side:

- `parse_action()` returns a fourth element naming how the body failed to arrive —
  `missing-close-fence` (the `>>>` never came) or `missing-open-fence` (no `<<<` at all, so
  the file would be replaced with nothing). Both were previously indistinguishable from a
  complete body;
- `length_stop_turns(calls)` reads `done_reason` back off the endpoint's own field;
- new columns **`length_stops`** (the turns) and **`truncated_writes`** (turn, path, which
  fence was missing, `done_reason`, `eval_count`) so a reader can count it;
- `classify_outcome()` is a pure function with a new **`VOID-TRUNCATED`** rung placed
  **above `FAIL` and `FAIL-CAP`** and **below `PASS`** — above FAIL because a cut completion
  is an instrument event, below PASS because the oracle is the authority on success and
  discarding a green repeat for a harmless truncation would throw away a real measurement;
- **the tool's semantics are deliberately unchanged.** The truncated body is still written and
  still reported as `OK: wrote N bytes`, so the prompt stream a post-fix arm produces is
  comparable to the pre-fix rows on the trajectory axis. What changed is that the run can no
  longer be **reported as an outcome**. Repairing the tool as well would have made these six
  rows incomparable to everything U3 runs.

### 3.5.3 The falsifier — `selfcheck`, and four mutants that redden it

Per RB-P48 a check counts only when a mutation that falsifies it turns red a case the claim
named, **and the mutation must be applied to the data the check reads** — the action text the
model emitted, the `done_reason` the endpoint returned, the oracle's exit code — never to a
flag the harness sets for itself.

```
docs/eval-data/2026-08-18-loop-harness.py selfcheck
```

15 cases, each run on the true input (must be green) and on a mutated input (must be red);
exit 0 only if every case behaved as declared. Four mutants, each a one-line reversion of the
fix written to a scratch copy of the harness — **not** to the committed file:

| mutant | the line reverted | cases that redden | exit |
|---|---|---|---|
| `nofence` | `incomplete = "missing-close-fence"` → `""` | **1** — `M1 RED: >>> stripped from the output` | **1** |
| `donereason` | `length_stop_turns` returns `[]` | **1** — `M2 RED: one done_reason flipped to length` | **1** |
| `ladder` | the `if truncated_writes:` rung disabled | **2** — both `M3 RED` cases | **1** |
| `label` | the `endpoint-error` branch removed and the elapsed time dropped from the reason | **3** — all three `M4` cases | **1** |
| *(unmutated)* | — | **0** | **0** |

Each mutant reddens **exactly its own cases and no others**, so the four checks are
independent and none of them is a transcription of another. The reddening comes from
`parse_action`'s return value, from a `done_reason` string, from `classify_outcome`'s return
value and from the `void_reason` text — all outputs, none a private flag.

The two cases that matter most are worth naming, because they are the ones that would have
been vacuous if written the easy way:

- `M1 note: mutant body is non-empty, so it WAS written — 50 bytes`. The mutant does not
  produce an empty body that anything would notice; it produces **a plausible 50-byte file**.
  That is why the old code could not detect it.
- `M4 RED: and must not contain the string 'run-cap' — absent`. The check asserts the
  30-second reason string does **not** contain `run-cap`, which is the exact text the old
  harness emitted. The mutant restores that text and the case goes red.

### 3.4 ESCALATION · the null control runs out of window before it runs out of turns

Stated as arithmetic, from the bar's own frozen constants and this arm's own counters:

| quantity | value | where it comes from |
|---|---|---|
| `COMPACTION_TOKEN_BUDGET` | 32,768 | bar §10.6, frozen |
| `T` = 60% of it | **19,660** | bar §10.2, frozen |
| worker `num_ctx` | **32,768** | bar §10.5, frozen |
| headroom above `T` before truncation | **13,108** | 32,768 − 19,660 |
| one ORACLE result, measured on this arm | **3,687 tokens** | consecutive `prompt_eval_count` deltas, 21,781 -> 25,468 -> 29,155 |
| **oracle runs of headroom** | **3.6** | 13,108 / 3,687 |
| turn cap | **40** | bar §10.6, frozen |

> **A run that reaches the boundary at all has 3.6 oracle runs of window left, and the bar
> gives the agent forty turns.** So on any trajectory that triggers the mechanism, B0 spends most
> of its remaining turns above `num_ctx`, where the runtime truncates the prompt and
> `prompt_eval_count` reports exactly the window (§2.5). Bar §10.2 rejected a smaller window
> for exactly this reason — *"the runtime would truncate the prompt and the 'null control'
> would be the runtime's own FIFO truncation policy, not 'compaction off'"* — and the same
> objection lands on 32,768 once the trajectory is measured rather than assumed.

Three consequences, none of which this unit may fix:

1. **`context_tokens_sent` (S-2) is not summable across a run that crossed the window.** Its
   later terms are the window, not the prompt. The row carries `worker_window_reached` so a
   consumer can tell.
2. **The comparison the job wants — "LLM summary versus no summary" — becomes "LLM summary
   versus FIFO truncation" past the crossing point**, which is the confound bar §10.2 refused
   in advance.
3. **The declared 20-minute run cap becomes the binding constraint, not the 40-turn cap**,
   because a single call above the window costs minutes (235.9 s measured on the pilot,
   against 26.4 s for the call just below it — bar §4.2's KV-cache axis, arriving through
   truncation rather than through compaction).

**What this unit did NOT do about it, deliberately:** it did not lower `T`, did not raise
`num_ctx`, did not shorten the turn cap, did not re-cut DEFECT-SET-5 and did not touch the
bar. Bar §10.2's standing refusal covers the first of those and the rest are the same move in
different clothes. The disposition is the orchestrator's.

#### 3.4.1 The arithmetic §10.2 used to justify 32,768 is refuted by the run

§10.2's justification is quoted in full because the refutation is a comparison of two
numbers, not a reading:

> the ceiling (25,900 + the task prompt, ≈ 27k) fits, so no truncation occurs

| | tokens | route |
|---|---|---|
| §10.2's predicted ceiling | **≈ 27,000** | not recorded (N-8) |
| `worker_num_ctx` | 32,768 | — |
| **realised `max_prompt_eval_count`, all six repeats** | **32,768** | `/api/generate` |
| `worker_window_reached` | **true, 6 of 6** | `/api/generate` |

**The predicted ceiling is 5,768 tokens below the window and the realised one is exactly
equal to it, in every repeat.** §2.5 measured that `prompt_eval_count` equal to `num_ctx` is
the clamp, not a token count — so 32,768 is not "the prompt was 32,768 tokens", it is "the
prompt was at least 32,768 tokens and the runtime truncated it". Truncation **did** occur, in
6 of 6.

The mechanism is §3.1.1: §10.2's ceiling is the same optimal-trajectory arithmetic as §1.5's,
and the realised trajectory appends the oracle output 8–9 times. Turn 19 of repeat 0 is where
the window closes, and the run has 21 more turns of its 40-turn cap left when it does.

---

## 3.6 The null-control status — **ESCALATION-CLASS. B0 is not usable as an arm.**

The bar governs this, not convenience, so the clause is quoted before the verdict.

**The clause that decides it is bar §10.2's own rejection of a smaller window:**

> the runtime would truncate the prompt and the "null control" would be the runtime's own
> FIFO truncation policy, not "compaction off"

§10.2 wrote that as the reason a smaller window was refused. It is a **conditional**: *if the
runtime truncates, the arm is not "compaction off".* §10.2 then discharged the condition by
arithmetic — 27k fits inside 32,768 — and chose 32,768 on that basis. **§3.4.1 measures the
condition to hold anyway: `worker_window_reached` is true in 6 of 6 and
`max_prompt_eval_count` is exactly `num_ctx` in 6 of 6.** The antecedent is satisfied, so the
consequent is the bar's own conclusion applied to its own chosen window: **past the crossing
point, B0 measures the runtime's FIFO truncation policy, not "compaction off".**

That is the whole argument. It uses no clause the bar does not contain and no judgement of
this unit's. The bar refused this configuration in advance and did not know it had.

**Verdict, in the bar's own vocabulary:**

| question | answer | on what |
|---|---|---|
| Is B0 **UNINFORMATIVE** for want of boundaries (§6 U-2)? | **No.** `boundaries ≥ 1` in **6 of 6**, floor is 4 of 6 | §3.1 |
| Are the six repeats **VOID as an arm** (§6 U-5)? | **Yes, all six.** `stopped_by = run-cap`, `wall_s` 1200.00x | §3.1 |
| Does **D-1** hold? | **Yes** | §2.2 |
| Does **D-2** hold, as §2.5 requires? | **No — 6 distinct of 6**, and the cause is CANON-1, not compaction | §3.2 |
| Is the arm **"compaction off"** as §3.1 defines it? | **No.** It is compaction-off *plus* runtime FIFO truncation from turn ~19 | §3.4.1 |
| So: is B0 usable? | **No, on three independent grounds** | |

**The three grounds are independent, which is why this is escalation and not a re-run.** A
re-run fixes none of them:

1. **VOID ×6 on the run cap.** 6 of 6 exhausted 1,200 s at turn 21–23 of a 40-turn cap. This
   is not variance; a single worker call above the window costs minutes (§3.4 item 3), so the
   cap is reached by construction on any trajectory that crosses the window. Re-running
   reproduces it.
2. **D-2 fails for an instrument reason.** CANON-1 does not close over the failing oracle
   output (§3.2, N-9). Re-running reproduces it; the fix is one line **in the bar's
   pre-registered canonicalisation**.
3. **The arm is not the arm the bar defined.** §3.4.1. Re-running reproduces it; every fix —
   raise `num_ctx`, lower `T`, shorten the turn cap, shrink the oracle output — is a change to
   a frozen constant.

**Ground 3 is the one that matters, because it is not a defect in the instrument.** Grounds 1
and 2 are things a harness can be made to do better. Ground 3 says the *experiment as
pre-registered* puts a 40-turn agent with an 8-oracle-append trajectory inside a
32,768-token window, and the window closes at turn 19. **No harness fixes that.**

**What this unit is therefore NOT doing, and the reason for each:**

| the tempting fix | why not |
|---|---|
| re-run B0 | reproduces all three grounds; §3.6 items 1–3 |
| raise `worker_num_ctx` above 32,768 | `num_ctx` is frozen in bar §10.5, and it is also the `COMPACTION_TOKEN_BUDGET` that defines `T` — raising one moves the other |
| raise the run cap above 1,200 s | frozen in bar §10.6; and it buys turns *above* the window, which is more FIFO truncation, not less |
| lower `T` | bar §10.2's standing refusal, and the exact move it exists to refuse |
| shorten the turn cap | changes the task |
| truncate or summarise the ORACLE output before it enters context | that **is** compaction, applied to B0 |

**The disposition is the orchestrator's.** The one thing this unit will say about it: the
cheapest change that discharges ground 3 without touching a frozen constant is to make the
oracle's output smaller *by configuration of the oracle itself* — `vitest --reporter=dot` or
equivalent — because §3.1.1 measures that 80–85 % of the context is oracle output. That is a
change to bar §1.3's oracle command, which is pre-registered, so it is still an amendment and
still not this unit's. It is noted so the escalation arrives with an option attached rather
than only a refusal.

---

## 4. What did not reproduce, or is wrong

Numbered so they can be cited. Each carries the command that shows it.

**N-1 · The bar's honest counter is honest only below the window.** §2.5. Escalation-class:
bar §10.3's contrast between the two routes is a contrast between two *windows*, and the
detector bar §6 U-6 declares for the summarizer belongs on the worker too.
`… clamp --lines 1200 --windows 2048 8192 32768`

**N-2 · `ollama create` FROM the raw blob path produces a completion-only model.** The bar
names the fix as "a derived model tag with `PARAMETER num_ctx 32768` over the identical
weight blob … the blob `qwen2.5:14b-instruct` itself resolves to". Built literally from the
blob **path**, the result carries no `TEMPLATE` and `ollama show` lists `Capabilities:
completion` only — it cannot serve `/v1/chat/completions` as a chat model at all. Built
`FROM qwen2.5:14b-instruct` it resolves to the **same blob** and keeps the template and the
`tools` capability. Same weights either way; only one of the two is usable.
`ollama show --modelfile bk-j7-qwen2.5-14b-ctx32768 | grep -cE 'im_start'` → `8`.

**N-3 · `git clean -fd` deletes the worktree's `node_modules` symlinks.** The bar's §1.1
supplies `node_modules` to the worktree as two symlinks and warns that they poison a
`git status`-based check. They also poison `git clean`: a `.gitignore` **directory** pattern
(`node_modules/`, line 2 of the workload's `.gitignore`) does not match a **symlink**, so
`clean -fd` — without `-x`, on a path everybody assumes is ignored — removes them. Measured
here as `FileNotFoundError: …/packages/shared/node_modules/.bin/vitest` on the very next
oracle. Any harness that resets between repeats and does not exclude them by name has **no
oracle from repeat 1 onward**, and it fails loudly rather than silently, which is the only
good news in it.

**N-4 · `git worktree list` can never be shown "clean" in the sense of empty.** The workload
checkout has **25** pre-existing worktree entries of its own. The check that means anything
is *"back to the recorded 25-line baseline, with this job's throwaway gone"*, and that is
the check §5 performs.

**N-5 · The gate is 940, not 936.** `.venv/bin/python -m pytest runtime-py/tests -q` at
`3ddf5db` → **940 passed, 2 xfailed**. The handoff's do-not list corrected 932 to 936; 936 is
also stale. This unit adds no node, so 940 is HEAD's own count.

**N-6 · CANON-1 cannot be applied "to every tool output" as bar §10.4 words it.** Rule (b)
sorts "the lines preceding the first ` FAIL ` header". A source file read has no such header,
so the literal reading sorts the file's lines and the repair task becomes unreachable for an
instrument reason — every arm would tie at 0/6 under bar §6 U-3, which is not a measurement
of anything. The other reading, *"no header, nothing to sort"*, contradicts bar §2.4's own
measured row: the **passing** oracle output has no ` FAIL ` header either, and it is recorded
as going from 3 distinct sha to 1 under CANON-1. The two readings cannot both hold.
This harness records the scope it used in `canon_id` —
`CANON-1/oracle-full+read-rule-a` — applies all three rules to ORACLE output and rule (a)
only to READ/LIST, and **measured** that rule (a) is a no-op there: 0 matches of all three
patterns across all 22 implementation files. Escalation-class; not resolved here.

**N-7 · Bar §1.5's "impl + one oracle = 0.74 × T, reaches NO boundary" describes a trajectory
this worker does not produce.** See §3. The arithmetic is not wrong; the trajectory it
assumes — every implementation file read once, the oracle run once — is not the one that
happens, and §1.5's own alternative line ("nine oracle runs and no file read at all would
reach `T`") is much closer to what the worker actually does.

**N-7a · …and §1.5 is wrong in the opposite direction on the term it was most confident
about.** The bar's largest slice is "implementation only, 12,243 tokens". §3.1.1 measures that
**everything that is not oracle output — the LIST, every READ, and the worker's own WRITE
bodies echoed back — never exceeds 6,390 tokens in any repeat.** The run never read the
implementation. So the pre-run arithmetic over-counted the source term by ≥ 1.9× *and*
under-counted the oracle term by 8–9× repeats × 1.64× per append. The two errors do not
cancel; the oracle one is an order of magnitude larger.

**N-8 · The bar's own §1.5 figures carry no window.** 23,647 tokens for all 32 `.ts` files is
above several plausible `num_ctx` values, and §2.5 shows a count measured at a window below
the prompt returns the window. The figures are consistent with a window ≥ their own value,
but the bar does not record which window was served, so they cannot be checked from the
document alone. Recorded as a **verification item**, not as an error.

**N-9 · CANON-1 does not collapse the FAILING oracle output, and bar §2.4's table says it
does.** §3.2. `canon --repeats 4` gives `failing … CANON-1 2 distinct of 4` where §2.4 records
1 distinct of 3 — at 3 repeats it happened to collapse. The residual is **one blank line that
moves between two ` FAIL ` blocks**, isolated over five runs that are all 6,168 bytes, and
confirmed independently in the committed rows by turn 4 having **identical `prompt_bytes`
(8,603) and identical `prompt_eval_count` (2,790) across all six repeats with three distinct
`prompt_sha256`** — a length-preserving permutation. Rules (b) and (c) sort lines and blocks;
neither says anything about blank lines. **This is the whole of B0's D-2 failure, and it has
nothing to do with compaction.** Escalation-class: the fix is a CANON-1 rule (d), and CANON-1
is pre-registered.
`… canon --repeats 4`

**N-10 · §10.2's arithmetic for choosing `num_ctx = 32768` is refuted by the run.** §3.4.1.
The predicted ceiling is ≈ 27k; the realised `max_prompt_eval_count` is **32,768 — exactly the
window — in 6 of 6**, and §2.5 measured that equality *is* the clamp. §10.2 refused a smaller
window on the grounds that truncation would make the null control "the runtime's own FIFO
truncation policy, not 'compaction off'"; the condition it discharged by arithmetic holds at
32,768 as well. **This is the escalation of §3.6 and it decides the arm.**

**N-11 · `stopped_by = "run-cap"` was set for every endpoint exception, at any elapsed
time.** §3.5.1. Closed. On these six rows the label is substantively correct —
`wall_s` = 1200.004–1200.005 on all six, corroborated by
`prompt_eval_duration_ns` + `eval_duration_ns` — but the instrument that produced them could
not have told a reader if it were not. **The orchestrator's resume brief reported `wall_s` as
29.99 / 33.81 / 37.61 / 243.09 / 277.98 / 268.79 and that does not reproduce: the committed
column is 1200.00x six times.** The defect is real and latent; the evidence offered for it was
not.

**N-12 · S5's Critical had already fired when it was found.** §3.5.2. 4 of 131 worker calls
carry `done_reason: "length"`, in repeats 3, 4 and 5. Closed for future arms, and re-deriving
all six outcomes through the fixed ladder returns `VOID` six times — the same value the
committed rows carry — because `run-cap` outranks `VOID-TRUNCATED`. **The committed artifact
is not retro-actively wrong and was not regenerated.**

**N-13 · The `d2` sub-command has no `--mutate` flag** and §2.6's table describes a mutation
applied to a **copy of the rows file**, not a harness option. Same for the four mutants in
§3.5.3, which are one-line reversions written to scratch copies of the harness. Recorded so a
reader does not go looking for a flag. The new `selfcheck` sub-command needs neither a network
nor a worktree and is the one falsifier that runs from a bare checkout.


---

## 5. The workload, and the fence around it

`packnplan-mono` is the **workload, never the subject**. Everything happened in a detached
throwaway worktree cut from `81ac1a10e2230661ce10745a3a64f4da1d3819f2` and placed **outside**
the packnplan tree, with `node_modules` supplied as two symlinks into the real checkout.

Nothing was committed, staged, pushed or tagged there. The harness resets between repeats
with `git checkout -f -- .` and `git clean -fd` (with the two symlinks excluded by name, per
N-3) — neither writes an object nor moves a ref.

Recorded at the start and checked at the end:

| check | baseline | at the end |
|---|---|---|
| `git -C <packnplan> status --short` | one line, `?? docs/test-cases/REVIEW-multi-perspective-2026-07-30.md` | *(§5.1)* |
| `git -C <packnplan> worktree list \| wc -l` | **25** | *(§5.1)* |

The pre-existing untracked file was never opened, never staged and never touched. The
tamper and scope checks read `git diff` against the pinned commit over tracked paths, never
`git status`, exactly as bar §1.1 requires — the symlinks are untracked and would poison a
`git status`-based check.

### 5.1 The worktree at the end — accounted for, not merely asserted

The throwaway worktree lived at
`…/scratchpad/wt-j7`, **outside** the packnplan tree, detached at
`81ac1a1`. Immediately before removal its own `git status --porcelain` was the two
`node_modules` symlinks and nothing else — no modified tracked file survived the last
`restore()`:

```
?? node_modules
?? packages/shared/node_modules
```

Removed with
`git -C <packnplan> worktree remove --force <scratchpad>/wt-j7` → `REMOVED`.

| check | baseline | at the end |
|---|---|---|
| `git -C <packnplan> log --oneline -1` | `81ac1a1` | **`81ac1a1`** — unmoved |
| `git -C <packnplan> status --porcelain` | one line, `?? docs/test-cases/REVIEW-multi-perspective-2026-07-30.md` | **the same one line, unchanged** |
| `git -C <packnplan> worktree list \| wc -l` | **26** (25 pre-existing + this job's throwaway) | **25** |
| of which `.claude/worktrees/…` | 24 | **24** — all pre-existing, none this job's |
| bantamkit `git tag \| wc -l` | **22** | **22** — nothing tagged |

Nothing was committed, staged, pushed or tagged in packnplan-mono. The pre-existing untracked
file was never opened, never staged and never touched. **N-4 stands**: "clean" for
`worktree list` can only mean *back to the recorded baseline with this job's throwaway gone*,
and that is what the table shows.

**U3 will need to re-cut the worktree.** It was removed because both briefs require this unit
to leave none behind, and because §3.6 escalates rather than continuing to the ladder. The
recipe is bar §1.1 plus N-3: a detached `git worktree add` outside the packnplan tree at
`81ac1a1`, `node_modules` and `packages/shared/node_modules` supplied as symlinks into the
real checkout, and **`git clean -fd` must exclude those two by name** or every repeat after the
first has no oracle.

---

## 6. What U3 needs from this unit

1. **The route and its window travel together.** Every token figure carries `worker_route`
   and `worker_num_ctx` on the row, and `worker_window_reached` says whether that run's
   counter can be trusted at all (§2.5). A `context_tokens_sent` summed across calls that
   include a clamped one is **not** a token count.
2. **The summarizer tag is `bk-j7-qwen2.5-14b-ctx32768`** and the clamp detector is
   `clamp_verdict(usage.prompt_tokens, num_ctx)`. `COMPACTION_LLM_MODEL` is what carries it
   into the mechanism; it is a configuration variable, not a modification.
3. **S1 (the seed shim of bar §2.5) is UNMEASURED — not run, not attempted.** This unit
   built B0, and a run that was not attempted is not a run that found nothing (RB-P51).
4. **`boundaries` in B0 is a monotone tail, not an event count.** Nothing in B0 removes
   context, so once `prompt_eval_count` reaches `T` every later call satisfies the trigger
   too. The informative statistics are `boundaries >= 1` (bar §6 U-2's floor) and
   `first_boundary_turn`, both of which are on the row. In B1 a boundary *reduces* the
   context, so B1's count is an event count and B0's is not — **they are not the same
   column even though they share a name.**
5. **The reset between repeats must exclude the two `node_modules` symlinks by name** (N-3),
   or every repeat after the first has no oracle.
6. **Do not run the ladder until §3.6 is dispositioned.** B0 is not "compaction off" past the
   window crossing, so B1 − B0 is not "summary versus no summary" — it is "summary versus
   FIFO truncation" for the majority of every run's turns. A ladder run before the escalation
   closes produces rows that cannot answer the job's question, at 20 minutes per repeat.
7. **`outcome` gained a rung and two columns gained meaning.** `VOID-TRUNCATED` sits above
   `FAIL`/`FAIL-CAP` and below `PASS`; `length_stops` and `truncated_writes` say whether the
   output cap cut a completion, and `endpoint_error` separates an endpoint failure from the
   run cap. A row with `stopped_by = "endpoint-error"` is VOID for an infrastructure reason and
   should be re-run; a row with `stopped_by = "run-cap"` is VOID for a *trajectory* reason and
   re-running it reproduces it (§3.6 item 1).
8. **The committed six rows predate the §3.5 fixes and lack the three new columns.** They are
   still comparable on the trajectory axis, because §3.5.2 deliberately left the tools'
   semantics alone — the prompt stream a post-fix arm builds is byte-for-byte what a pre-fix
   arm would have built. What changed is only how a run is *reported*. Any comparison must
   still say so, and re-deriving the six outcomes through the new ladder returns the same six
   VOIDs (§3.5.2).
9. **`context_tokens_sent` is not a token count on any of the six rows.** All six have
   `worker_window_reached: true`, so later terms in the sum are the window, not the prompt
   (§2.5). The honest per-run figures are `max_prompt_eval_count` — which is the clamp — and
   `eval_tokens_total`, which is output and is not clamped.
10. **D-2 will keep failing until CANON-1 gains a blank-line rule** (N-9). Until then a D-2
    failure carries no information about compaction, so gating an arm on it VOIDs every arm
    for the same instrument reason. `selfcheck` is the falsifier that does not depend on it.
