# Pre-registered bar: does a paged document reader buy anything a truncated paste cannot?

**Dated 2026-08-20. Status: PRE-REGISTERED. No arm has run. No model has been called by this
job at any point. No `ollama` generate/chat request has been issued. Every number below is a
property of an instrument, a declaration or a file on disk — none is an outcome of the question
this bar asks.**

This artifact is **amended, never rewritten** (RB-P50, J7 precedent). If something below turns
out wrong, a dated amendment goes in §12 and the original text stays exactly as it is.

X4 of job `job19-document-readers`. The mechanism this bar grades is the reader pair
`assets/tools/document_list.json` + `assets/tools/document_read.json` at commit `f92d5ad`, over
the `document_setup:` fixture generator at `b298de5` and the `docread` extraction at `3f971e9`.

---

## 0. Disclosure, before anything else

1. **Every figure handed to this unit was re-derived.** §11 lists what reproduced, what
   reproduced only under a different command than the obvious one, and the one figure in the
   brief that is a rounding of a different number. Two things the brief did **not** say are
   recorded there as findings, and one of them (§11.4) changes what the harness has to do
   before a single run is legal.
2. **`bare` is not this bar's control and is not reported as one.** §1.2 states what it *is*
   for, which is narrower and load-bearing.
3. **The axis is CAPABILITY, not token saving.** The reader costs tokens; it does not save
   them. §4 pre-registers the cost report anyway, and pre-registers that the two axes are
   reported together and never netted into a ratio (J6 died on a netted ratio; J7 §4 is the
   precedent for refusing to net).
4. **Video is out of scope, refuted by `.shiftwork/probes/J10-PREP-readers.md` Q2. PDF is out
   of scope, deferred by the same probe.** Nothing here measures either, and no result here may
   be cited about either.
5. **The corpus is GENERATED, and the probe's real-file corpus figures are unverified.** X1
   recorded that none of the six real `.xlsx`/`.docx` the probe named is locatable by a second
   party. This bar therefore plans nothing on them and claims nothing about them (§7).

---

## 1. The arms, and the defence of the arm set

### 1.1 The three arms

| arm | config name | corpus reaches the model by | reader tools |
|---|---|---|---|
| **reader** | `reader` | two paged tools, on demand | `document_list`, `document_read` |
| **paste** | `paste` | the head of the rendering, in the system prompt, capped at **PASTE_MAX_BYTES = 12,288 B**, cut on a row boundary | none |
| **floor** | `bare` | not at all | none |

`reader` exists at `f92d5ad` (`READER_CONFIGS = {"reader": "bare"}`, `evalrun.py:180`). `bare`
exists. **`paste` does not exist and landing it is a precondition of the run** — §10.2 states
its contract exactly, so that landing it is transcription and not design.

### 1.2 Why `bare` is in the set and why it is NOT the control

`bare` registers no reader and receives no corpus, so it **cannot open an `.xlsx` at all**. An
experiment whose only control is a floor can only discover that zero is less than something.
That is J4's shape and this bar refuses it.

What `bare` *is* here is a **contamination detector, and it is the only one available.** The
answer is a `(region, units)` pair drawn from 4 regions × 9,000 integers, so a run that has
never seen the corpus has a **1 in 36,000** chance of guessing it. **Any `bare` pass is
therefore evidence that the answer reached the model by some path other than the corpus**, and
§6 V-3 makes that finding VOID the task for every arm. A floor that can fire is worth keeping;
a floor reported as a comparison is not.

### 1.3 Why `paste` is the real comparison, and why the truncation is honest

J4's argument was *"paste the corpus into the prompt instead of offering a tool to search
it"*, and it killed the finder axis. That argument has a precondition the probe stated and J4
never did: **the corpus must fit.** `inventory.xlsx` extracts to 258,129 B ≈ 64,532 est. tokens
= **1.97× WORKER_NUM_CTX (32,768)** (§2), and at the served window this job actually runs
against (**8,192**, §10.1) it is **7.88×** over. So the paste that J4 would have run is
unconstructible, and the arm that replaces it is *as much of the rendering as fits* — which on
the large corpus is **incomplete by construction**.

This is the arm the reader competes with in the world. It is not a strawman: it is what a
practitioner with no reader tool actually does, and on the small corpus (§1.4) it is a
**complete** paste that the reader has to beat on level ground.

### 1.4 One paste rule, two corpora — and why that is the whole design

**PASTE_MAX_BYTES = 12,288 is one constant applied identically to both corpora.** It is not
tuned per corpus and there is no arm-specific special case:

| corpus | rendered bytes | paste keeps | paste is |
|---|---:|---|---|
| `inventory-small.xlsx` (400 data rows) | 8,621 (incl. newlines) | **all 401 rendered rows** | **COMPLETE** |
| `inventory.xlsx` (12,000 data rows) | 258,130 (incl. newlines) | rendered rows **0–570** = header + data rows **1–570**, 12,277 B | **TRUNCATED at 4.7579% of rows** |

Measured, not assumed: at a 12,288 B head cut on a row boundary the large corpus keeps **571
rendered rows / 12,001 = 4.7579%** and the first EXCLUDED rendered index is **571**, i.e. **data
row 570 is the last one inside**. The small corpus needs 8,621 B and so is kept whole.

The small corpus **shares the seed, the sheet name and the columns** with the large one and
differs only in row count, so it is a **literal prefix** of it — re-derived in §2. That gives
the design its sharpest cell: **`doc-small-137` and `doc-large-in-137` ask the identical
question and have the identical answer (`SKU-000137` → `east` / `7726`)**, and differ only in
whether the corpus is 0.07× or 1.97× the window. Any gap between those two cells is corpus size
and nothing else.

---

## 2. The corpus, re-derived at `f92d5ad` in this worktree

Command: `materialise_documents` from `runtime-py/src/bantamkit/evalrun.py` imported from this
worktree (`__file__` printed and inside the worktree), on the declarations committed in
`runtime-py/tests/test_document_setup.py`.

| fixture | file bytes | extracted | est. tokens (`bytes // 4`) | × 32,768 | rendered rows | sha256 |
|---|---:|---:|---:|---:|---:|---|
| `inventory.xlsx` | 1,883,561 | **258,129** | **64,532** | **1.9694×** | 12,001 | `1d97571e…` |
| `inventory-small.xlsx` | 62,436 | **8,620** | **2,155** | **0.0658×** | 401 | `3fcca5c0…` |

**Both reproduce.** The brief's `1.97×` and `0.07×` are roundings of `1.9694` and `0.0658`.

**The prefix claim reproduces**, by the check that actually tests it: the small corpus's
rendered text is a literal prefix of the large one's (`big_text.startswith(small_text)` → True;
8,620 B is the first 8,620 B of 258,129 B). A naive `big.rows[:401] == list(small.rows)`
returns **False** and means nothing — `Part.rows` is a tuple, so the comparison fails on type.
Recorded because the wrong check here would have silently retracted a true claim.

**The invariant holds: `inventory.xlsx` at 64,532 est. tokens EXCEEDS the 32,768 worker window
by 1.97×, and exceeds the 8,192 window this job is served at by 7.88×.** Six of the nine tasks
use it. If it did not, this job would have rebuilt J4 and would have to die the same way.

---

## 3. The tasks — LOOKUP, never aggregation, and every answer's position declared

Nine tasks, committed at `assets/evals/document/tasks/*.yaml`, family **`document-read`**.

**They live in their own directory, not in `assets/evals/tasks/`, and that is not a
preference.** `assets/evals/devteam/tasks/` is the committed precedent for a task set outside
the frozen suite. Adding to `assets/evals/tasks/` would turn two committed tests red — see
§11.5.

**Every task is a single-row LOOKUP.** The prompt is byte-identical across all nine except for
the SKU, and it says *"Do not compute anything and do not summarise the sheet; read the one
row."* An aggregation task would measure small-model arithmetic and report it as reader
quality (probe Q1, X1's finding). There is no sum, no count, no max and no filter anywhere in
this task set.

| task | corpus | data row | address | position vs the 12,288 B boundary | expected |
|---|---|---:|---|---|---|
| `doc-small-137` | small | 137 | `stock!C138` | **complete paste** (whole corpus in) | `east` / `7726` |
| `doc-small-261` | small | 261 | `stock!C262` | complete paste | `south` / `3788` |
| `doc-small-388` | small | 388 | `stock!C389` | complete paste | `east` / `5208` |
| `doc-large-in-137` | large | 137 | `stock!C138` | **INSIDE** (137 ≤ 570) | `east` / `7726` |
| `doc-large-in-372` | large | 372 | `stock!C373` | INSIDE | `south` / `7796` |
| `doc-large-in-529` | large | 529 | `stock!C530` | INSIDE, 41 rows from the cut | `west` / `6982` |
| `doc-large-out-4137` | large | 4137 | `stock!C4138` | **OUTSIDE** | `north` / `7508` |
| `doc-large-out-8022` | large | 8022 | `stock!C8023` | OUTSIDE | `south` / `8935` |
| `doc-large-out-11764` | large | 11764 | `stock!C11765` | OUTSIDE, 236 rows from the end | `south` / `7509` |

Scoring is **`json_equal`** on `{"region": <str>, "units": <int>}` for all nine — exact
structural equality, no judge, no substring.

### 3.1 How the answer's position was chosen — the rule, fixed before any result exists

**A proportional draw was considered and REJECTED, with its arithmetic.** If answer rows were
drawn uniformly from the corpus, P(inside) = the coverage fraction = **0.047579**. Over 6 large
tasks that is **0.29 tasks inside — i.e. zero**, and a design with zero IN cells is a design in
which the paste arm scores 0 by construction. That would have rebuilt the floor with extra
steps and would have made the run unable to refute anything.

**So the position is a STRATIFIED, BALANCED factor, not a sample:** on the large corpus,
**exactly 3 tasks INSIDE and exactly 3 tasks OUTSIDE**, and every result is reported **per
stratum**.

- The **OUT stratum** asks: does the reader recover what truncation lost? The paste arm's
  ceiling there is 0 by construction. This cell carries the job's claim.
- The **IN stratum** asks: where paste *can* answer, does the reader still match it? **This is
  the cell that can refute the reader** — if the reader loses on rows a paste can see, the tool
  costs competence rather than buying it. Without this stratum the experiment cannot lose.
- The **SMALL cell** asks: with a complete paste and a corpus that fits, is the model capable
  of the task at all? It is what separates *"the reader is useless"* from *"the model is"*.

**Any corpus-weighted single number is pre-registered here or it is not computed at all:**
weights **w_out = 0.952421, w_in = 0.047579**, i.e. the true coverage fraction from §1.4. It is
declared now so that nobody can pick it later, and §5 states that the per-stratum figures are
the headline and the weighted number is never reported alone.

Positions within a stratum were fixed by re-derivation before any arm existed and are not
adjustable: `137` because it is the one row that exists identically in both corpora; `529`
because it is deliberately near the cut (41 rows inside), so a boundary-effect failure has
somewhere to show; `11764` because it is deep and near the end, where a blind pager runs out of
turns.

---

## 4. The cost axis, pre-registered before it can be chosen

**The reported cost is `TaskResult.context_bytes_sent`** — the harness's own sum of
`request_wire_bytes(messages, tools)` over every request (`evalrun.py:297`), reported as the
**median per (tier, arm, stratum)**, in bytes.

**It is NOT the token column, and the reason is measured.** The eval client posts to the
OpenAI-compatible `/v1` route and sends `{model, messages, tools?, seed?, response_format?}`
with **no `num_ctx` and no `options`** (`client.py:243-249`). RB-P53 measured that on that
route `usage.prompt_tokens` is **clamped to the context window** and returns silently and
green. The paste arm is the one arm that runs near the window. **Its token column would
therefore be a reading of the window, not of the prompt** — so the token column is not this
bar's cost axis and no arm's cost is quoted in tokens from it.

**The comparison reported is exactly this, and no other:**

1. `context_bytes_sent`, median, per (tier, arm, stratum) — the whole axis.
2. The reader's roster share stated separately as **1,414 B/request × `model_calls`**
   (re-derived, §11.2), so the fixed cost of *offering* the pair is visible next to the
   variable cost of *using* it.
3. The paste's corpus share stated separately as **12,288 B × `model_calls`**, because the
   system prompt is re-sent on every request. That is the prefix-resend cost and it is the
   reason a paste is not "the corpus once".

**Pre-registered arithmetic that is not a result** (both measured off the tools at `f92d5ad`,
against `doc-large-out-4137`): one `document_list` observation is **217 B**; one
`document_read` page at the default limit is **1,487 B**. So an ideal two-call solve exposes
**1,704 B** of corpus, against **12,288 B** for one paste — **13.9%**. This is stated as the
mechanism's arithmetic, not as a prediction of what any model will do, and it is not a success
criterion.

**No ratio is netted.** The pass-rate axis and the byte axis are reported side by side. A
"tokens saved per point of pass rate" figure is refused in advance.

---

## 5. The success criterion and the falsifier, as inequalities with arm names in them

Let `P(arm, stratum)` be the pass rate over matched `(task, repeat)` cells, pooled over the
three compared tiers (4b/7b/14b — see §8), n = 36 per cell.

### 5.1 CONFIRMED — the reader buys something

**All three must hold:**

- **C1 (the claim).** `P(reader, large-OUT) − P(paste, large-OUT) ≥ 0.30`
  **and** McNemar exact two-sided **p < 0.05** on the matched cells.
- **C2 (no harm where paste can see).** `P(reader, large-IN) ≥ P(paste, large-IN) − 0.10`.
- **C3 (the mechanism, not luck).** `document_list` is called in **≥ 50%** of `reader`-arm
  runs in the large-OUT stratum (otherwise §6 U-2 fires first and the cell is UNINFORMATIVE
  rather than confirmed).

### 5.2 REFUTED — the reader buys nothing

**Any one of these is sufficient:**

- **R1.** `P(reader, large-OUT) − P(paste, large-OUT) < 0.10`.
- **R2.** McNemar exact two-sided **p ≥ 0.05** on large-OUT with a non-UNINFORMATIVE cell —
  the reader bought nothing detectable at this n, stated as that and not as "no difference".
- **R3 (the reader costs competence).** `P(reader, large-IN) < P(paste, large-IN) − 0.10`
  with McNemar **p < 0.05**. The tool made the model worse where the corpus was already
  visible.
- **R4 (it was never the corpus).** `P(reader, small) − P(reader, large-OUT) ≥ 0.50` **and**
  `P(paste, small) ≥ 0.50`. The model can do the task on a corpus that fits and the reader
  fails to carry it to one that does not — the paging, not the reading, is what failed, and
  the pair as shipped does not deliver the capability.

### 5.3 The band between them

`0.10 ≤ Δ < 0.30`, or `Δ ≥ 0.30` with `p ≥ 0.05`, is **NEITHER**: recorded as an effect too
small or too thin to carry a decision at this n, with the observed Δ and p printed. It does not
promote `reader` into `CONFIGS` and it does not retire the pair.

---

## 6. UNINFORMATIVE, VOID and UNMEASURED — the conditions, so that a run that cannot answer says so by itself

J7's run was UNINFORMATIVE at the measured scope and said so by its own pre-registered rule.
These are this job's, and **each is a computable predicate over the committed `.jsonl`, decided
by the rule and not by anybody's reading afterwards.**

### 6.1 UNINFORMATIVE — the cell measured something other than the question

Evaluated **per (tier, arm, stratum) cell**:

- **U-1 — the tool was never reached.** ≥ 50% of `reader`-arm runs in the cell have
  `outcome == "turns-exhausted"` or `tool_calls == 0`. The cell measured the 10-turn budget.
- **U-2 — the model never called `document_list`.** `document_list` appears in the transcript
  of < 50% of `reader`-arm runs in the cell. The manifest is what makes an offset computable
  rather than searchable (`contract.document_manifest`); a cell that skipped it measured blind
  paging, which is 240 pages against a 10-turn budget and is the tool's ergonomics reported as
  the model's competence.
- **U-3 — every arm at zero.** `P(reader) = P(paste) = P(bare) = 0` in the cell. A floor cannot
  be told from a ceiling there.
- **U-4 — format swamped the signal.** `outcome ∈ {malformed-output, schema-exhausted}` in
  > 30% of runs in the cell. The cell measured JSON emission.

### 6.2 The run-level rule

**The whole run is UNINFORMATIVE if the large-OUT stratum is UNINFORMATIVE for ≥ 2 of the 3
compared tiers**, because that stratum is the only one that carries the claim. No confirmation
and no refutation may be reported from a run in that state.

### 6.3 VOID — the row is not a measurement of anything

- **V-1 — window clamp (RB-P53).** For any `paste`-arm run at a tier, if the pre-run
  calibration of §10.3 measured the paste prompt at **≥ 0.85 × 8,192 = 6,963 tokens**, the
  `paste` arm is **VOID at that tier** and may not be compared. It is not silently shrunk: a
  smaller `PASTE_MAX_BYTES` is an amendment to this bar with its own date, never an adjustment.
- **V-2 — setup failure.** `DocumentSetupError` escapes `run_task` (by design, `evalrun.py`
  docstring): the corpus was never built, the run is VOID, and the suite must not be reported.
- **V-3 — contamination.** Any `bare`-arm pass in a cell VOIDs **that task for every arm**. At
  1 in 36,000 the answer reached the model by a path that is not the corpus, and the arms are
  no longer comparable on it.
- **V-4 — transport.** `outcome == "transport-error"`. Re-run permitted; the replacement row
  carries the same `(task, config, repeat)` key so the pairing survives.

### 6.4 UNMEASURED — named now so it cannot be quietly filled in later

- The **served window of `llama3.2:3b`**. Its Modelfile declares no `num_ctx` (§10.1), so it is
  served at whatever the daemon defaults to. The 3b is a **declared floor** (§8), so this costs
  nothing that this bar claims — but the 3b's `paste` arm is **UNMEASURED against a known
  window** and no 3b paste number may be compared to any other tier's.
- The **real bytes-per-token ratio of the rendering under each tier's tokenizer.** `bytes // 4`
  is the repo's estimator and this content is denser than 4 B/token. §10.3 makes measuring it
  the run's first act.

---

## 7. What is NOT claimed — written now, before the temptation exists

1. **Not claimed: the reader saves tokens.** It costs them: 1,414 B/request forever, plus every
   page. §4 reports the cost; no line of this bar promises a reduction.
2. **Not claimed: anything about `.docx`, `.pptx`, `.pdf` or video.** No task here uses any of
   them. Video is refuted by measurement; PDF is deferred; `.pptx` has no corpus.
3. **Not claimed: that the reader beats a FINDER.** The pair has no search argument and X3
   asserted its absence in a test. A result here is about *paged reading*, and says nothing
   about whether a `find`-shaped primitive would do better, worse or the same.
4. **Not claimed: anything about real spreadsheets.** The corpus is generated: one sheet, three
   columns, fixed row width, a key column that is a pure function of the row index. Real
   workbooks are none of those. The probe's real-file figures (137,861 / 690,945 / 8,247 B) are
   **single-sourced and unverified** — X1 could not locate any of the six named files — and are
   not used here.
5. **Not claimed: a tier comparison.** `run_seed` hashes the model name, so no two tiers share
   a seed; and as measured today they are not even served at the same window (§10.1). Every
   cross-tier statement in the result is **descriptive**.
6. **Not claimed: that `reader` belongs in `CONFIGS`.** It stays calibration-only in
   `CONFIG_CHOICES` until this bar's own criterion says otherwise. A CONFIRMED result is a
   *recommendation* to promote, ruled by the user, not an automatic promotion.
7. **Not claimed: generalisation past the declared budgets.** `max_turns = 10`,
   `observation_budget = 4096`, `DOCUMENT_PAGE_MAX_BYTES = 3072`,
   `DOCUMENT_PAGE_ROW_LIMIT = 50`. A different budget is a different experiment.
8. **Not claimed: that a 3b failure is a reader defect.** The 3b is a declared floor (§8).
9. **Not claimed: that `bare` is a baseline.** It is a contamination detector (§1.2). Its pass
   rate is reported and is expected to be 0; a non-zero value is a finding about the *harness*,
   not about the reader.
10. **Not claimed: that `PASTE_MAX_BYTES = 12,288` is the best paste.** It is *a* declared
    paste, sized in §10.2 to fit the served window with margin. A larger window would give a
    larger paste and a smaller Δ; that dependence is stated, not hidden.

---

## 8. The tiers, the repeats, and the total run count

**Tiers, and the model strings are declared exactly:**

| rung | model | served `num_ctx` (Modelfile, measured today) | role |
|---|---|---:|---|
| 4b | `bk-rbp27-qwen3-4b-instruct` | **8192** | compared |
| 7b | `bk-rbp27-qwen2.5-7b-instruct` | **8192** | compared |
| 14b | `bk-rbp27-qwen2.5-14b-instruct` | **8192** | compared |
| 3b | `llama3.2:3b` | **unset → daemon default** | **declared FLOOR, not a target** |

**The rbp27 trio is chosen over the stock tags for one reason and it is not convenience: all
three pin `num_ctx = 8192` in their Modelfile, so the paste arm is the SAME arm at all three
tiers.** A ceiling that floats with the model would make `paste` a different arm per rung and
the comparison would stop being between arms. The stock tags (`qwen3:4b-instruct`,
`qwen2.5:7b-instruct`, `qwen2.5:14b-instruct`, `llama3.2:3b`) declare **no** `num_ctx` at all —
measured today with `ollama show --modelfile` — which is exactly the RB-P53 hazard.

**The 3b is a declared floor**, and the ground is committed: `docs/eval.md:7147`, 528 rows per
tier, 3b **0.2557 (135/528)** against 4b 0.6648, 7b 0.6307, 14b 0.6458, with Fisher two-sided
3b-vs-7b **p < 0.0001** and 4b/7b/14b mutually **p ≥ 0.2734**. **Re-derived at its source and it
reproduces.** A 3b failure on this family is predicted here, in advance, and is not a reader
defect.

**The n, and it is a number this bar is held to:**

- 9 tasks × 3 arms × **R = 4 repeats** × 4 tiers = **432 runs**.
- Per (tier, arm, stratum) cell: 3 tasks × 4 repeats = **n = 12**.
- Pooled over the three compared tiers: **n = 36**.

---

## 9. The statistical test, pre-registered

**McNemar exact, two-sided, hand-rolled from `math.comb`.** `scipy` is not in `.venv`
(verified: `ModuleNotFoundError`), and the exact test is exact rather than asymptotic, which
matters at n = 12.

**The pairing key is `(task, repeat)` within a tier.** This is available and is not recovered
by inverting a hash: `run_seed(model, task_name, repeat)` **deliberately excludes `config`**
(`evalrun.py:966-977`), so every arm of a `(task, repeat)` shares one seed; and as of `8689ac6`
**`repeat` is a recorded column on `TaskResult`**, so nothing has to be inverted. The precedent
and the method are committed at `docs/eval.md:7263-7272`.

`p = min(1, 2 · Σ_{i=0..min(b,c)} C(b+c, i) / 2^(b+c))`, where `b` = cells where `reader`
passed and `paste` failed, `c` = the reverse. Concordant pairs are excluded, which is the
point of the test.

**The minimum detectable effect, computed before the run:**

| n discordant | split needed for p < 0.05 | p at that split |
|---|---|---|
| **12** (per tier) | **≥ 10 of 12 one way** | 0.0386 (9/12 → 0.1460, not significant) |
| **36** (pooled) | **≥ 25 of 36 one way** | 0.0288 (24/36 → 0.0652, not significant) |

**Pooling across 4b/7b/14b is pre-registered here and its warrant is the committed ladder:**
those three are one population at n = 528 (Fisher p ≥ 0.2734; paired McNemar p ≥ 0.0567). The
4b–7b paired p of **0.0567 is at the edge**, so the pooled figure is reported **alongside** the
three per-tier figures and **never instead of them**. The 3b is never pooled.

**Cross-tier comparisons get no test.** Different seeds and, today, different served windows.

---

## 10. The declared configuration, frozen now

### 10.1 Read at named commits, measured in this worktree

| thing | value | source |
|---|---|---|
| reader pair | `document_list` + `document_read` | `f92d5ad` |
| `document_setup:` generator | as committed | `b298de5` |
| extraction / paging | `docread.py` | `3f971e9` |
| `WORKER_NUM_CTX` | **32768** | `docs/eval-data/2026-08-18-loop-harness.py:91` |
| served window, the three compared tiers | **8192** | `ollama show --modelfile bk-rbp27-*`, measured 2026-08-19 |
| `max_turns` / `observation_budget` | **10 / 4096** | `profile_default`, default profile |
| `DOCUMENT_PAGE_ROW_LIMIT` / `MAX_ROWS` / `MAX_BYTES` | **50 / 200 / 3072** | `evalrun.py:778-785` |
| roster cost of the pair | **1,414 B/request = 353 tok = 3.406% of J7's 10,364-token median call** | re-derived, §11.2 |
| runtime dependencies | `httpx`, `jsonschema`, `pyyaml` — **three, unchanged** | `runtime-py/pyproject.toml` |

### 10.2 The `paste` arm's contract, so that landing it is transcription

`paste` mirrors `bare` exactly — no schema gate, no critic, no graph, no memory, and **no
reader tools** — plus one system message, and it is calibration-only in `CONFIG_CHOICES`,
never in `CONFIGS`, exactly as `reader` is.

1. It materialises the same `document_setup:` fixtures as every other arm (`run_task` already
   does this unconditionally, per config).
2. For each fixture, in declaration order, it renders each part as `header + rows` joined by
   `\n`, in `docread`'s own rendering — **the same bytes `document_read` would return**, so the
   two arms differ in *delivery*, not in *content*.
3. It takes the **head** of that text, adding whole rendered rows in order while the running
   total (each row plus its newline) stays **≤ PASTE_MAX_BYTES = 12,288**. **A row is never cut
   mid-row**: a half row is a value the model can misread as a whole one.
4. It states, in the same system message, the part name, the total row count, and **how many
   rows are shown** — so the model is told the paste is partial rather than left to infer it.
   A paste that lies about its own completeness is a different, worse arm.
5. It registers **no tools at all**. `tool_calls` on a `paste` row must be 0.

**Cut from the head, not the tail or the middle**, because a head cut is what every truncating
consumer does and it makes the boundary a single declared number rather than a policy.

### 10.3 The pre-run gates — run before the first live call, in this order

- **G-1 — the expected value is a slice of the corpus.** For each of the nine tasks, rebuild
  the fixture and assert `fixture.answers["expected_region"] == scoring.expected["region"]`,
  `int(fixture.answers["expected_units"]) == scoring.expected["units"]`, and
  `fixture.answers["question_sku"]` occurs in the prompt. **Landed as a checker, not left as a
  declaration**: `runtime-py/tests/test_document_tasks.py`, which also pins the stratum split,
  the truncation boundary, and one corpus per name. Run in this unit: **45 passed**, and **8 of
  8 mutants killed** rather than grepped (§11.7). It is still listed here because a gate a
  runner does not know about is a gate that stops being run the day the file is renamed.
- **G-2 — the served window.** `ollama show --modelfile` for each declared model; the three
  compared tiers must read `num_ctx 8192`. Any other value is an amendment, not an adjustment.
- **G-3 — the paste actually fits (RB-P53).** One `/api/generate` call per compared tier with
  the paste system message and `num_predict=1`, reading **`prompt_eval_count`** — the
  `/api/generate` counter, never `/v1`'s clamped `usage.prompt_tokens`. Record the measured
  bytes-per-token ratio. If any tier reads **≥ 6,963**, that tier's `paste` arm is VOID (§6
  V-1). **This is the run's first act and its three numbers are recorded whatever they say.**
- **G-4 — the floor is a floor.** `bare` over all nine tasks at one tier, before the ladder. A
  pass here is V-3 and stops the run.

### 10.4 The command

```
python -m bantamkit.evalrun --base-url <ollama>/v1 --model <declared model> \
  --tasks assets/evals/document/tasks \
  --config bare --config paste --config reader \
  --repeats 4 --json <artifact>.jsonl --transcripts <dir>
```

One `.jsonl` per tier under `docs/eval-data/`, named for the date and the tier. Transcripts are
kept: U-2 is only decidable from them.

---

## 11. What of the brief and the prior units did NOT reproduce, or reproduced only under a different command

### 11.1 The corpus figures — reproduce (§2)

`1.97×` and `0.07×` are roundings of `1.9694` and `0.0658`. The prefix claim reproduces under
the text comparison and appears to FAIL under the obvious row-list comparison, for a type
reason (§2).

### 11.2 The roster price — reproduces, but NOT by the obvious command

The brief's **1,414 B = 353 tok = 3.41%** reproduces exactly: `request_wire_bytes([], pair) −
request_wire_bytes([], None)` = **1414**, `1414 // 4` = **353**, `353 / 10364` = **3.406%**.

**The obvious command gives a different number.** Summing `len(json.dumps(tool.to_wire()))`
over the two tools gives **1,399** (430 + 969) — it misses the `"tools"` key, the brackets and
the separator that the request actually carries. This is the same class of error the probe
already recorded for `file_graph` (265 B on disk vs 290 B on the wire) and that X3 found inside
a *correction* about number hygiene. **Anyone re-deriving 1,414 by summing tool objects will
get 1,399 and will think the figure moved.**

### 11.3 The 3b floor — reproduces at its source

`docs/eval.md:7147`: 3b **0.2557 (135/528)**, 528 rows, and the Fisher figures that make the
other three one population, are all present as the brief describes.

### 11.4 **FINDING — `answers:` is resolved, recorded, and consumed by NOTHING**

`materialise_documents` validates each answer address, reads the value **out of the document it
just built**, and stores it on `DocumentFixture.answers` (`evalrun.py:751-754`). **`run_task`
never reads it.** The only use of `document_fixtures` in `run_task` is the tool-registration
gate at `evalrun.py:1110`. Nothing substitutes an answer into the prompt and nothing
substitutes it into `scoring.expected`.

**Consequence:** a committed task's `expected` is a hand-written literal that the harness never
checks against the corpus — which is precisely the drift X2's design was built to make
impossible, reintroduced one layer up. The nine tasks here carry values **derived from the
generator and verified against it**, and that verification is now a committed checker
(`runtime-py/tests/test_document_tasks.py`), not a sentence in this file.

**The finding stands anyway, and is NOT closed by that checker.** The checker guards *these
nine* tasks. The harness still has no path from `DocumentFixture.answers` to a prompt or to
`scoring.expected`, so the next `document_setup:` task written by anybody re-enters the same
hole. Wiring substitution into `run_task` is a harness change, above this unit's layer, and is
left open.

### 11.5 **FINDING — the brief's "no enum to extend" is true of the harness and FALSE of the suite**

`family` is free-form in `evalrun.py` (missing → `EvalConfigError`, value never checked), and
`assets/evals/devteam/tasks/` ships `dev-repo-code` / `dev-repo-history`, neither of which is in
any enum. **But `assets/evals/tasks/` is guarded:** `test_conformance.py:18` pins
`FAMILIES = {structured-extraction, tool-use, memory-recall, file-nav}` and line 59 asserts
membership, and `test_criticreplay.py::test_the_frozen_suite_is_still_the_twenty_two_prompts_these_tables_cover`
asserts `len(_frozen_prompts()) == 22` over that same glob. **Putting these nine tasks in
`assets/evals/tasks/` would have turned both red** — the second one for a reason that has
nothing to do with families. They are in `assets/evals/document/tasks/`, following the devteam
precedent, and the frozen suite is untouched.

### 11.6 **FINDING — the stock tier tags declare no `num_ctx`, and the eval client sends none either**

Measured today: `qwen3:4b-instruct`, `qwen2.5:7b-instruct`, `qwen2.5:14b-instruct` and
`llama3.2:3b` all have **no `PARAMETER num_ctx`** in their Modelfile; only the `bk-rbp27-*`
trio (8192) and `bk-j7-*` (32768) pin one. And `OpenAICompatible` sends no `options` and no
`num_ctx` (`client.py:243-249`). Under RB-P53 that combination is a **silent, green clamp**,
and it is the reason §8 declares the rbp27 trio and §10.3 makes G-3 the run's first act.
`ollama show`'s "context length" (262144 / 131072 / 32768) is the **architecture maximum**, not
the served window, and must not be read as one.

### 11.7 The gate this unit landed, measured by mutation rather than by reading

`runtime-py/tests/test_document_tasks.py`: **45 nodes, all green at this commit.** Non-vacuity
was measured, not asserted — **8 of 8 mutants go red**:

| # | mutant | nodes red |
|---|---|---:|
| M1 | one committed `expected.units` flipped 7508 → 7509 | 1 |
| M2 | one task's `seed:` moved 4021 → 4022 | 1 |
| M3 | a `large-out` answer address moved inside the boundary (4138 → 138) | 3 |
| M4 | `answers:` addresses made to span two rows (`B4139` with `C4138`) | 2 |
| M5 | one task's corpus shrunk 12,000 → 11,000 rows | 1 |
| M6 | a lookup prompt turned into an aggregation | 1 |
| M7 | this bar file deleted | 1 |
| M8 | one column's `low:` moved 1000 → 1001 | 2 |

**Two of them were found by measuring, not by writing.** M5 originally **SURVIVED** — the
stratum still resolved, the boundary check found a 12,000-row task in another file, and the
corpus still exceeded the window — which is what added
`test_one_corpus_per_name_across_every_task_that_declares_it`. And the aggregation check was
first written as a substring test, which **reddened 9 of 9 tasks** on the word `sum` inside the
prompt's own instruction *"do not summarise the sheet"*; it is a word-boundary test now, and
the reason is in its docstring.

### 11.8 Nothing else failed to reproduce

`WORKER_NUM_CTX = 32768` at `docs/eval-data/2026-08-18-loop-harness.py:91`: reproduces. Three
runtime dependencies: unchanged. `run_seed` excludes `config`: confirmed in source. `repeat` is
a recorded column: confirmed at `8689ac6`.

---

## 12. Amendments

None. This section exists so that the first one has somewhere to go that is not this text.

## Amendment 1 — 2026-08-20

**Status: still PRE-REGISTERED. No graded arm has run.** X5 (`19ceffa`) landed `paste` and ran
the mandatory smoke pass; this amendment is written on what that pass MEASURED, before a single
row of the sweep exists. What is forbidden is amending after seeing a *result*; what is
required is not running a sweep that this document's own rules VOID. Everything above this
heading is the text as pre-registered and is not edited — where a number below supersedes one
above, both are readable and the older one is the one that was wrong.

Written by X5B. Every figure here was re-measured in the worktree at
`feat/document-readers`; §A.4 lists what of X5's report did not reproduce.

### A.1 The estimator is no longer UNMEASURED, and it was 2.83–2.91× wrong

§6.4 named `bytes // 4` as UNMEASURED. It is measured now. Command (G-3's own instrument —
`/api/generate`, `num_predict=1`, reading `prompt_eval_count`, never `/v1`'s clamped
`usage.prompt_tokens`), one call per (tier, corpus, reading):

```
POST http://localhost:11434/api/generate
{"model": <tier>, "prompt": <the paste system message>, "stream": false,
 "options": {"num_predict": 1}}   -> response["prompt_eval_count"]
```

At the **pre-registered** `PASTE_MAX_BYTES = 12,288`, on the paste system message alone:

| tier | corpus | prompt B | `bytes // 4` | measured `prompt_eval_count` | V-1 (≥ 6,963) |
|---|---|---:|---:|---:|---|
| 4b | large | 12,672 | 3,168 | **8,192** | **VOID** |
| 7b | large | 12,672 | 3,168 | **8,192** | **VOID** |
| 14b | large | 12,672 | 3,168 | **8,192** | **VOID** |
| 4b | small | 8,962 | 2,240 | 6,511 | ok |
| 7b / 14b | small | 8,962 | 2,240 | 6,532 | ok |

Every large reading is **exactly 8,192 on both counters — clamped**. The true prompt therefore
EXCEEDS the served window: the `paste` arm was already being truncated server-side, silently
and green, which is RB-P53's failure mode. **V-1 fires at all three compared tiers, `paste` is
uncomparable, and C1, C2, R1 and R3 are uncomputable. A sweep run in that state measures
nothing.** That is the whole warrant for this amendment.

**The measured ratio, off the unclamped readings only:** **1.372–1.379 B/token** for the paste
system message and **1.408–1.415 B/token** for the message plus the task prompt. So `bytes // 4`
under-counts this content by **2.83–2.91×** (4 ÷ 1.415 … 4 ÷ 1.372). No token figure in this bar
may be computed from `bytes // 4` again; §2's `est. tokens` column stays as the *file property*
it always was and is not a claim about any tokenizer.

### A.2 V-1's scope, resolved: per **(tier, corpus)**, and G-3 is six calls, not three

X5 recorded the ambiguity and correctly refused to resolve it. Resolved here, before it can be
chosen to save a cell: **a paste is a per-corpus object** — two corpora produce two different
system messages, of different sizes, saying different things about their own completeness — so
the predicate is evaluated per (tier, corpus) and **VOIDs the `paste` arm only for the strata
drawn from that corpus at that tier** (`small` for `inventory-small.xlsx`; `large-IN` and
`large-OUT` for `inventory.xlsx`).

**G-3 is amended to six calls**: each compared tier × each corpus. And the calibrated prompt is
the **system message plus the task prompt** (361 B for all nine tasks; they are byte-identical
but for the SKU), because that is what the request actually carries — measuring the system
message alone understates the prompt by 91 tokens. Both readings are recorded below; the
**request** reading is the one V-1 is evaluated on, which is the stricter of the two.

This resolution is deliberately not load-bearing for the run it precedes: at the amended
constant **both corpora pass at all three tiers** (§A.3), so no cell survives *because of* the
reading chosen here.

### A.3 `PASTE_MAX_BYTES = 8,621`, and why that number and not another

The constant is re-sized on the measured ratio. The three constraints of §1.4 and §10.2 are
unchanged and all three are binding:

1. **one constant over both corpora**, cut on a row boundary — unchanged;
2. **the small corpus stays whole** — it needs 8,621 B (401 rendered rows), so the constant
   **cannot go below 8,621**;
3. the large paste's **measured** `prompt_eval_count` must sit under the served window with a
   stated margin — which is what caps it from above.

Measured, at the amended constant, in the worktree:

| tier | corpus | rows kept | row B | system B | system `prompt_eval` | +task B | **request `prompt_eval`** |
|---|---|---:|---:|---:|---:|---:|---:|
| 4b | large | 401 | 8,621 | 9,016 | 6,536 | 9,379 | **6,627** |
| 7b | large | 401 | 8,621 | 9,016 | 6,557 | 9,379 | **6,648** |
| 14b | large | 401 | 8,621 | 9,016 | 6,557 | 9,379 | **6,648** |
| 4b | small | 401 | 8,621 | 8,962 | 6,511 | 9,325 | **6,602** |
| 7b | small | 401 | 8,621 | 8,962 | 6,532 | 9,325 | **6,623** |
| 14b | small | 401 | 8,621 | 8,962 | 6,532 | 9,325 | **6,623** |

**The margin, stated as a number.** Worst reading over all six cells: **6,648 tokens**
(large, 7b and 14b, request reading).

- against the served window 8,192: **1,544 tokens of headroom, 18.85%**;
- against V-1's threshold 6,963: **315 tokens, 4.52%**.

**Why not larger.** Measured, not argued: at a cap of **9,088 B** (422 rows) the large paste
reads **6,963** on the 4b and **6,984** on the 7b — exactly at and over the V-1 threshold. The
feasible band is roughly 8,621–9,050 B, and every byte of it buys the large paste ~1 row at the
cost of the margin V-1 exists to protect. **Why not smaller.** Constraint 2: below 8,621 the
small paste stops being COMPLETE and §1.4's level-ground cell — the one that separates *"the
reader is useless"* from *"the model is"* — stops existing.

**A consequence worth stating rather than discovering later:** the small corpus is a literal
prefix of the large one (§2), so at 8,621 B **both pastes carry the identical 401 rendered
rows**. `doc-small-137` and `doc-large-in-137` now differ in *nothing* but the corpus behind
them and what the paste says about its own completeness — §1.4's sharpest cell is sharper than
it was pre-registration, not weaker.

### A.4 The boundary moves, and §1.4's and §3.1's numbers move with it

Re-derived at the amended constant on the built corpus:

| | pre-registered | **Amendment 1** |
|---|---:|---:|
| `PASTE_MAX_BYTES` | 12,288 | **8,621** |
| rendered rows kept, large | 571 | **401** |
| bytes kept, large | 12,277 | **8,621** |
| **last data row INSIDE** | 570 | **400** |
| first rendered index OUTSIDE | 571 | **401** |
| coverage of the large corpus | 4.7579% | **3.3414%** |
| §3.1 `w_in` / `w_out` | 0.047579 / 0.952421 | **0.033414 / 0.966586** |

The §3.1 weights are the true coverage fraction by construction, so they move with it; they are
re-declared here, still before any result, and the rule that the per-stratum figures are the
headline and the weighted number is never reported alone is unchanged.

§4's pre-registered arithmetic moves too, and is re-derived here rather than rescaled: one
`document_list` observation is **217 B** (reproduces) and one `document_read` page at the
default limit is **1,486 B** (the pre-registered figure says 1,487 — see §A.7). So an ideal
two-call solve exposes **1,703 B** against **8,621 B** for one paste — **19.75%**, where §4 said
13.9% against the larger paste. The paste's corpus share in §4 becomes **8,621 B × `model_calls`**.
The roster share is untouched and reproduces exactly: **1,414 B/request = 353 tok = 3.406%**.

### A.5 The task set: one file changed, and the 3/3/3 design is re-established, not patched

At the new boundary `doc-large-in-529` (data row 529 > 400) falls **OUTSIDE**, which would have
left the design 2 IN / 4 OUT. `doc-large-in-137` (137) and `doc-large-in-372` (372) are both
still inside and are **unchanged**.

**`doc-large-in-529` is replaced by `doc-large-in-359`.** §3 chose 529 as the near-the-cut IN
row *because* it sat 41 rows inside the cut, so that a boundary effect would have somewhere to
show; 359 is the same design element re-derived at the new cut (400 − 359 = 41, the identical
offset). Corpus, seed, columns, prompt shape and scoring kind are byte-identical to the row it
replaces; the answer (`south` / `1187`) was read out of the built document by the generator and
G-1's checker rebuilds it. The other eight task files change only in their header comment, which
named the old boundary.

The design after the amendment, unchanged in shape: **3 IN / 3 OUT / 3 small**, `doc-small-137`
and `doc-large-in-137` still the identical question over the two corpora, still nine tasks,
still `assets/evals/document/tasks/`, still `n = 432`.

| task | data row | stratum, pre-registered | **stratum now** |
|---|---:|---|---|
| `doc-small-137` / `-261` / `-388` | 137 / 261 / 388 | small, COMPLETE paste | **small, COMPLETE paste** |
| `doc-large-in-137` | 137 | IN | **IN** |
| `doc-large-in-372` | 372 | IN | **IN** |
| `doc-large-in-529` | 529 | IN, 41 rows from the cut | **withdrawn — now outside** |
| **`doc-large-in-359`** | 359 | — | **IN, 41 rows from the cut** |
| `doc-large-out-4137` / `-8022` / `-11764` | 4137 / 8022 / 11764 | OUT | **OUT** |

### A.6 The reader pair could not be called, and that was a defect in the mechanism

X5 measured that **5 of 5 seeds on the 4b** (and 0 of 5 on the 7b) called `document_list` — a
tool whose schema declares **no properties** — with a spurious `document` argument. The handler
raised `TypeError`; the dispatcher formatted its own sentence and interpolated the exception, so
the model was handed
`error: document_list failed: _document_tools.<locals>.list_documents() got an unexpected
keyword argument 'document'`. Three of four smoke repeats then answered *"I'm unable to access
the workbook"* and scored 0.

**This bar grades whether a paged reader helps. A reader whose describe call cannot be invoked
is not the thing being graded**, and the reading it would have produced — that the 4b cannot use
the pair — would have been a reading of a handler signature. Two defects, fixed in the layer
each belongs to:

1. **Robustness — Layer 1 (`agent.py`).** `select_declared_arguments` drops arguments a tool's
   schema does not declare, before the handler is called; `handler_accepts` binds the handler's
   signature without calling it, so an argument-shaped mismatch never becomes a raised
   `TypeError`. Ignoring an undeclared key rather than lecturing about it is deliberate: the
   tool has no way to act on it, and the alternative spends one of ten turns saying so.
2. **The leak — Layer 2 (`contract.py` + `assets/contracts/default.yaml`).** The dispatcher's
   two model-facing sentences were owned by no contract asset and pinned by no golden.
   `tool_failed` (byte-identical to the wording it replaces) and `tool_arguments` /
   `tool_arguments_none` now live in the asset with goldens in `test_layers.py`, and the
   argument-shaped failures are settled before the handler runs — so a `{detail}` reaching the
   model is a handler's own sentence and not a signature fragment.

**§6's U-2 does not catch this**, because `document_list` *is* in the transcript; it just fails.
Amended, so that the next run cannot mistake a crashing tool for a model that chose not to call
it:

- **U-2 (amended).** *The model never SUCCESSFULLY called `document_list`.* A `document_list`
  entry whose observation begins with `error:` does not count as a call. Threshold unchanged:
  < 50% of `reader`-arm runs in the cell.
- **U-5 (new) — the tool crashed rather than answered.** A tool observation ending in
  `fix the arguments and retry.` (the dispatcher's own sentence, and the only observation in
  the harness that ends that way — a reader's own errors are `document_unknown` and friends and
  do not) in **> 10%** of `reader`-arm runs in a cell makes that cell **UNINFORMATIVE**, and the
  defect is reported as a defect. A tool that crashed is not a model that declined.

### A.7 What of X5's report did NOT reproduce

1. **The G-3 prompt bytes.** X5 reports 13,035 B (large) and 9,325 B (small); the paste system
   message alone measures **12,672 B** and **8,962 B**. The difference is 363 B, and it is the
   task prompt: X5 calibrated the system message **plus the task prompt**, which §10.3's wording
   ("the paste system message") does not say. Not an error in either direction — the readings
   are of two different things — and §A.2 resolves which one G-3 means from here.
2. **The bytes-per-token range.** X5's `1.41–1.59 B/token`: the 1.41 end reproduces exactly
   (9,325 / 6,602). **The 1.59 end is not a measurement** — it is 12,672 (or 13,035) ÷ 8,192,
   and 8,192 is the *clamped* counter, so it is a lower bound on the token count and therefore
   an upper bound on the ratio that no observation supports. The measured range is
   **1.372–1.415**, and the estimator error is **2.83–2.91×**, not 2.3–2.8×.
3. **`document_read`'s page size.** §4 pre-registers 1,487 B for one page at the default limit;
   re-derived at this commit against `doc-large-out-4137` it is **1,486 B**, so the two-call
   solve is 1,703 B and not 1,704 B. One byte; recorded because §11 recorded the same class of
   discrepancy for the roster price and the next re-deriver should not think the figure moved.
4. Everything else reproduced: the two corpus hashes and sizes, 12,001 / 401 rendered rows, the
   571-row / 12,277 B / 4.7579% cut at the pre-registered constant, the clamp at all three
   tiers, `document_list` = 217 B, the roster at 1,414 B = 353 tok = 3.406%, and the 4b's
   spurious `document` argument.

### A.8 What this amendment does NOT change

The arms and their contracts (§1, §10.2 clauses 1–5); the LOOKUP-only rule and the nine tasks'
prompts; the scorer; **the criterion and the falsifier as inequalities** (§5's C1/C2/C3 and
R1–R4, thresholds included); the tiers, the repeats and `n = 432` (§8); the test (§9); every
line of §7's *not claimed* list; and V-2, V-3, V-4. §7.10 is reaffirmed and now has a measured
number behind it: this is *a* declared paste, and a larger served window would give a larger
paste and a smaller Δ.

## Amendment 2 — 2026-08-20

**Status: the run has been scored.** X6's 432 rows are committed and §V of `docs/eval.md`
published a verdict from them. This amendment is therefore written under the tighter of the two
rules a pre-registered record can be held to: **it changes no threshold, flips no clause, and
does not edit one character above this heading.** Where a pre-registered sentence turns out to
carry two readings, this amendment states both, states what each one yields, and only then
states which one the pre-registered text compels — argued from that text as it stood before any
arm ran and from nothing the rows showed afterwards. The drafting rule in §B.4 binds the *next*
bar; it does not re-score this one.

Written by the `RB-P88` unit. Every figure below was re-derived in this worktree from the
committed `.jsonl`; the four run files landed at `39f7aaf` and have not changed since, and no
row was regenerated to produce any number here.

### B.0 The defect, in one sentence

**§6.1's `U-4` is the only UNINFORMATIVE predicate in this bar that does not name its own
denominator, and the single compared cell where the two available denominators disagree is the
cell that supplies R3's significance.**

This is a defect in one predicate, not a property of the section. The other four are
denominator-stable under either reading of the word *"cell"*, because each carries its scope
inside its own sentence:

| predicate | the scope its own sentence carries | denominator under either reading |
|---|---|---|
| `U-1` | *"≥ 50% **of `reader`-arm runs in the cell**"* | 12 |
| `U-2` (amended, §A.6) | *"< 50% **of `reader`-arm runs in the cell**"* | 12 |
| `U-3` | *"`P(reader) = P(paste) = P(bare) = 0`"* — names all three arms | the `(tier, stratum)` block |
| **`U-4`** | *"in **> 30% of runs in the cell**"* — **names no arm** | **12 or 36** |
| `U-5` (new, §A.6) | *"in **> 10% of `reader`-arm runs in a cell**"* | 12 |

U-4 carries nothing, so it inherits whatever *"cell"* means — and this bar uses *"cell"* with
**three different referents**, two of them inside one sentence of §5:

1. §5 — *"the pass rate over matched `(task, repeat)` **cells**"*: a cell is one matched
   `(tier, task, repeat)` unit.
2. §5, eleven words later — *"**n = 36 per cell**"*: a cell is an `(arm, stratum)` pool over the
   three compared tiers.
3. §6.1 and §8 — *"per `(tier, arm, stratum)` **cell**"*; *"Per `(tier, arm, stratum)` cell:
   3 tasks × 4 repeats = **n = 12**"*.

### B.1 Both readings, re-derived from the committed rows — the numbers, before the argument

**Reading A** — *"cell"* is the `(tier, arm, stratum)` cell that §6.1's opening sentence and §8
both name; U-4's denominator is that cell's **12** runs.
**Reading B** — *"cell"* is the `(tier, stratum)` block spanning all three arms, which is the
scope U-3's `P(reader) = P(paste) = P(bare)` needs; U-4's denominator is **36**.

<!-- provenance: value=7b/reader/large-IN is 4 bad-outcome runs; 4/12=0.3333 fires U-4, 4/36=0.1111 does not; commit=1a8e382 (rows unchanged since 39f7aaf); command=python3 -c "import json; R=[json.loads(l) for l in open('docs/eval-data/2026-08-20-document-read-7b.jsonl')]; B=[r for r in R if r['task'].startswith('doc-large-in')]; bad=lambda S:sum(1 for r in S if r['outcome'] in ('malformed-output','schema-exhausted')); A=[r for r in B if r['config']=='reader']; print('reader-arm %d/%d=%.4f  block %d/%d=%.4f'%(bad(A),len(A),bad(A)/len(A),bad(B),len(B),bad(B)/len(B)))" -->

    reader-arm 4/12=0.3333    block 4/36=0.1111

**The numerator is 4 under both readings, and that is measured rather than assumed.** The four
bad-outcome runs at `7b`/large-IN are all `outcome == "malformed-output"` in the `reader` arm;
`bare` and `paste` contribute **zero** there, so widening the denominator to 36 widens nothing
else. `0.3333 > 0.30` is true and `0.1111 > 0.30` is false: **U-4 fires under Reading A and does
not fire under Reading B.** The margin under Reading A is **0.4 of one run** — 3 of 12 would be
25.00% and would not fire.

U-4 over all twelve blocks, both readings:

<!-- provenance: value="the twelve-block U-4 table below"; commit=1a8e382; command=python3 -c "import json;P='docs/eval-data/2026-08-20-document-read-%s.jsonl';st=lambda t:'small' if t.startswith('doc-small') else 'large-IN' if t.startswith('doc-large-in') else 'large-OUT';bad=lambda r: r['outcome'] in ('malformed-output','schema-exhausted');[print('%-4s %-9s bare=%d paste=%d reader=%d | A:%d/12 | B:%d/36'%(t,s,n['bare'],n['paste'],n['reader'],n['reader'],sum(n.values()))) for t in ['4b','7b','14b','3b'] for R in [[json.loads(l) for l in open(P%t)]] for s in ['small','large-IN','large-OUT'] for B in [[r for r in R if st(r['task'])==s]] for n in [{a:sum(1 for r in B if r['config']==a and bad(r)) for a in ('bare','paste','reader')}]]" -->

| tier | stratum | bad rows `bare` / `paste` / `reader` | Reading A (n=12) | Reading B (n=36) |
|---|---|---|---|---|
| 4b | small / large-IN / large-OUT | 0/0/0 · 0/0/0 · 0/0/0 | 0.0000 · 0.0000 · 0.0000 | 0.0000 · 0.0000 · 0.0000 |
| 7b | small | 0 / 0 / 1 | 0.0833 | 0.0278 |
| 7b | **large-IN** | 0 / 0 / **4** | **0.3333 — FIRES** | 0.1111 — silent |
| 7b | large-OUT | 0 / 0 / 3 | 0.2500 | 0.0833 |
| 14b | small | 2 / 0 / 0 | 0.0000 | 0.0556 |
| 14b | large-IN | 1 / 0 / 1 | 0.0833 | 0.0556 |
| 14b | large-OUT | 2 / 0 / 3 | 0.2500 | 0.1389 |
| 3b | small | 7 / 0 / 2 | 0.1667 | 0.2500 |
| 3b | large-IN | 6 / 0 / 5 | 0.4167 — FIRES | 0.3056 — FIRES |
| 3b | large-OUT | 7 / 0 / 7 | 0.5833 — FIRES | 0.3889 — FIRES |

**The disagreement touches exactly one compared cell in the whole run.** Both 3b blocks fire
U-4 under both readings, and the 3b is a declared floor (§8) that is never pooled, so they cost
nothing this bar claims — recorded here so they are not discovered later. Every other compared
cell is silent under both. `7b`/`reader`/large-IN is the entire disagreement.

### B.2 What each reading costs the verdict, as arithmetic and not as reassurance

R3 (§5.2) reads `P(reader, large-IN)` against `P(paste, large-IN)`, both pooled over 4b/7b/14b
at the n = 36 §5 fixes. If `7b`/`reader`/large-IN is UNINFORMATIVE **and an UNINFORMATIVE cell
is excluded from that pool**, the pool is the 4b and the 14b at n = 24.

<!-- provenance: value=large-IN pooled McNemar with 7b in (n=36, 32/36 vs 22/36, b=1 c=11, p=0.006348) and with 7b out (n=24, 24/24 vs 19/24, b=0 c=5, p=0.0625); commit=1a8e382 (rows unchanged since 39f7aaf); command=python3 -c "import json,math;P='docs/eval-data/2026-08-20-document-read-%s.jsonl';L=lambda t:[json.loads(l) for l in open(P%t)];G=lambda ts:{(t,r['task'],r['repeat'],r['config']):r['passed'] for t in ts for r in L(t) if r['task'].startswith('doc-large-in')};M=lambda b,c:min(1.0,2*sum(math.comb(b+c,i) for i in range(min(b,c)+1))/2**(b+c));print('\n'.join('%-12s n=%d paste=%d reader=%d b=%d c=%d p=%.6f'%('+'.join(ts),len(k),sum(d[(*x,'paste')] for x in k),sum(d[(*x,'reader')] for x in k),b,c,M(b,c)) for ts in (['4b','7b','14b'],['4b','14b']) for d in [G(ts)] for k in [sorted({x[:3] for x in d})] for b in [sum(1 for x in k if d[(*x,'reader')] and not d[(*x,'paste')])] for c in [sum(1 for x in k if d[(*x,'paste')] and not d[(*x,'reader')])]))" -->

    4b+7b+14b    n=36 paste=32 reader=22 b=1 c=11 p=0.006348
    4b+14b       n=24 paste=24 reader=19 b=0 c=5 p=0.062500

| | Reading A + exclusion | Reading A + admission | Reading B |
|---|---|---|---|
| U-4 on `7b`/`reader`/large-IN | fires (4/12) | fires (4/12) | silent (4/36) |
| R3's pool | 4b + 14b, n = 24 | 4b + 7b + 14b, n = 36 | 4b + 7b + 14b, n = 36 |
| `P(paste)` / `P(reader)` | 1.0000 / 0.7917 | 0.8889 / 0.6111 | 0.8889 / 0.6111 |
| R3's inequality `P(reader) < P(paste) − 0.10` | holds (0.7917 < 0.9000) | holds (0.6111 < 0.7889) | holds |
| McNemar exact two-sided | **p = 0.062500** | **p = 0.006348** | **p = 0.006348** |
| R3 fires? | **no** (p ≥ 0.05) | **yes** | **yes** |
| verdict | §5.3 **NEITHER** | §5.2 **REFUTED** | §5.2 **REFUTED** |

R1, R2 and R4 are silent in every column — on large-OUT, Δ = +0.4167 at p = 0.000061 with the
7b in and Δ = +0.5833 at p = 0.000122 with it out, and `P(reader, small) − P(reader, large-OUT)`
is 0.0556 — so R3 is the only clause that can carry a refutation here and the NEITHER column is
what is left when it does not fire.

**Note which two things have to be true together for the verdict to move: U-4 must fire *and*
R3 must exclude the cell it fires on.** Those are two separate questions about two separate
sentences, and §B.3 answers them separately.

### B.3 Which reading the pre-registered text compels

#### B.3.1 The denominator is 12: `(tier, arm, stratum)`, Reading A

Three grounds, in descending strength, all from text written before any arm ran:

1. **§6.1 states its own evaluation unit in its own opening sentence, and that sentence names
   `arm`.** *"Evaluated **per (tier, arm, stratum) cell**"* is the only sentence in §6.1 that
   fixes what a cell is, and it governs all of U-1 … U-5. A predicate in that subsection that
   adds no scope of its own takes that one. Reading B does not narrow U-4; it requires §6.1's
   scoping sentence to be **wrong**, because a `(tier, stratum)` block is not a
   `(tier, arm, stratum)` cell.
2. **§8 fixes the same unit independently and gives it a number.** *"Per `(tier, arm, stratum)`
   cell: 3 tasks × 4 repeats = **n = 12**."* Two sections written at pre-registration, in
   different chapters and for different purposes, define *"cell"* the same way and never define
   it as a block spanning arms. Reading B has no sentence anywhere in the bar that states it.
3. **Reading B defeats U-4's own stated purpose, by arithmetic on the rule.** U-4 exists because
   *"the cell measured JSON emission"*. The `paste` arm produced **zero** bad-outcome rows in
   all twelve blocks and the `bare` arm produced 5 of its 108 across the compared tiers, so
   under Reading B the reader's rate is divided by three and diluted by two arms that
   essentially cannot contribute. A `reader` arm malformed on **10 of its own 12 runs — 83.3%,
   with clean `bare` and `paste`** — is 10/36 = 27.78% and **does not fire U-4**. A predicate
   that cannot void a cell which is 83% format failure is not doing the thing its own sentence
   says it does. Reading A's threshold, on the same arithmetic, means "4 or more of 12", which
   is a rule about a cell.

**The case for Reading B, and why it loses.** It is real and it is the one the register entry
raises: U-3 is written as `P(reader) = P(paste) = P(bare) = 0` *"in the cell"*, which needs
three arms' pass rates to have a referent, and U-1/U-2/U-5's *"of `reader`-arm runs"* is
redundant if *"cell"* already fixes the arm. Both observations are correct. Neither is strong
enough:

- U-3 is repaired without moving *"cell"*: the predicate is still **evaluated per
  `(tier, arm, stratum)` cell** and reads its sibling cells of the same `(tier, stratum)` for
  the other two arms' rates — which is how §V.4 in fact reports it (*"U-3 fires once, at
  `3b`/large-OUT (all three arms at zero)"*, naming a tier and a stratum). Reading a phrase as
  reaching sibling cells costs less than reading an express definitional sentence out of the
  document.
- The redundancy in U-1/U-2/U-5 is not surplusage. Those three are predicates **about tool
  use**, and only the `reader` arm has a tool; naming the arm is what keeps them well-formed
  rather than vacuous when §6.1 is read against a `paste` or `bare` cell. U-4 is about output
  format, which every arm has, so it had nothing to name and named nothing — which is exactly
  the drafting hole §B.4 closes.

**Conclusion: `U-4` fires on `7b`/`reader`/large-IN. That cell is UNINFORMATIVE.** §V.5's
reading of the denominator was right, and it is now argued rather than asserted.

#### B.3.2 R3 admits that cell, and the ground is an express number

The second question is not about §6.1 at all. Does an UNINFORMATIVE cell leave R3's pool?

**The pre-registered text says no, and it says it four ways:**

1. **§5 fixes the n.** *"pooled over the three compared tiers (4b/7b/14b — see §8), **n = 36 per
   cell**."* Excluding the 7b makes it 24. To exclude, you must overwrite a number §5 states;
   to admit, you overwrite nothing. **That asymmetry is the whole argument** — a pre-registered
   number is not something a later reading gets to reduce.
2. **The bar has an exclusion mechanism and it belongs to VOID, not to UNINFORMATIVE.** §6.3 is
   titled *"VOID — **the row is not a measurement of anything**"* and V-1 says the arm *"**may
   not be compared**"*. §6.1 is titled *"UNINFORMATIVE — the cell measured something other than
   the question"* and no clause of §6 says an UNINFORMATIVE cell may not be compared. A
   three-way taxonomy that gives one term an express "may not be compared" and withholds it
   from another has decided the question.
3. **The bar wrote the proviso in exactly the clauses it wanted it in.** §5.2's **R2**:
   *"McNemar exact two-sided p ≥ 0.05 on large-OUT **with a non-UNINFORMATIVE cell**"*. §5.1's
   **C3**: *"otherwise §6 U-2 fires first and **the cell is UNINFORMATIVE rather than
   confirmed**"*. Two of §5's seven clauses name UNINFORMATIVE; five — C1, C2, R1, **R3**, R4 —
   do not. That is a drafter who knew the words and placed them.
4. **§6.2 is the only escalation and it is conditioned on a different stratum.** *"The whole run
   is UNINFORMATIVE if the **large-OUT** stratum is UNINFORMATIVE for ≥ 2 of the 3 compared
   tiers, **because that stratum is the only one that carries the claim**."* An UNINFORMATIVE
   large-**IN** cell has, in the pre-registered text, no run-level consequence at all. §6.2 is
   also the one place that says *"no confirmation and no refutation may be reported"* — and it
   does not reach here: large-OUT is UNINFORMATIVE at 1 of 3 compared tiers (`7b`, U-1 at 8/12),
   and §6.2 needs 2.

**And the published run already applied this rule to itself, in the other direction.** §V.3's
honesty item 3 records `7b`/large-OUT as UNINFORMATIVE under U-1 — a firing whose denominator
is *not* ambiguous — and still pooled that cell into C1's Δ = +0.4167 at p = 0.000061, reporting
the exclusion only as a sensitivity. A rule that admits an UNINFORMATIVE cell into the pool that
supports the claim, and excludes one from the pool that supports the falsifier, is not a rule.

**This ground is constructional, not stipulated: the bar never wrote the general sentence.** It
is strong — it rests on an express number in §5 and on three placed provisos — but it is the
weaker of the two determinations in this amendment, and §B.4 is why no successor bar should ever
need it.

#### B.3.3 J10's verdict under the compelled reading

**REFUTED. The published verdict stands, unchanged, and `reader` does not enter `CONFIGS`.**

R3 fires: `P(reader, large-IN) = 22/36 = 0.6111 < 0.8889 − 0.10 = 0.7889` with McNemar exact
two-sided **p = 0.006348**, on the pool of n = 36 that §5 pre-registers, including the
`7b`/`reader`/large-IN cell that U-4 makes UNINFORMATIVE and that no clause of §5.2 R3 excludes.

**Stated in the plainest terms available, because a program whose verdict rests on a reading
needs to hear it as one sentence: the verdict did not move, but it was one unwritten sentence
away from moving.** Had §5.2's R3 carried R2's proviso — six words, *"with a non-UNINFORMATIVE
cell"* — this run would be §5.3 **NEITHER** at p = 0.0625 and not REFUTED. The bar's falsifier
survived on the absence of a clause, not on the presence of one. That is the defect `RB-P88`
records, and it is recorded even though the answer came out where the run already stood.

### B.4 The forward rule — binding on the next bar, not on this run

**Two rules, and they are not optional for any bar written after this date:**

- **D-1 — a predicate that can void a cell names its own denominator in its own sentence.** The
  numerator's population and the denominator's population are both written out, with the arm
  named where an arm is meant, so that no predicate depends on what a scoping sentence elsewhere
  meant by *"cell"*. The bare word *"cell"* is not used in a predicate without its factors.
- **D-2 — a criterion clause that reads a cell states whether it admits an UNINFORMATIVE one.**
  Every clause of every CONFIRMED/REFUTED/NEITHER criterion carries the answer explicitly; the
  bar states, once and in general, what an UNINFORMATIVE cell does to a pool. Silence is not a
  default, because it took this section to work out which default silence meant.

**Applied to this bar's own text as an explicit restatement, forward-effect only.** These
restatements are what the compelled reading of §B.3 already says; they change no threshold, flip
no clause and re-score no row. They exist so that a re-deriver of this document never has to
repeat §B.3.

- **`U-4` (restated).** *`outcome ∈ {malformed-output, schema-exhausted}` in > 30% of the **12
  runs of the `(tier, arm, stratum)` cell being evaluated** — the same arm's runs, not the
  block's 36.* Firings under the restatement, at `1a8e382`: `7b`/`reader`/large-IN (4/12),
  `3b`/`reader`/large-IN (5/12), `3b`/`reader`/large-OUT (7/12), and no other cell of the 36.
- **`U-1`, `U-2`, `U-5` (restated).** Denominator is the **12 `reader`-arm runs of the
  `(tier, arm, stratum)` cell**. Unchanged in substance — each already said so.
- **`U-3` (restated).** Evaluated per `(tier, arm, stratum)` cell; its three `P(·)` terms are
  the pass rates of the three arms of that cell's **`(tier, stratum)` block**, and a firing
  makes **all three** cells of that block UNINFORMATIVE.
- **§5's clauses (restated).** `C1`, `C2`, `R1`, `R3`, `R4` are computed on **§5's pooled
  n = 36, UNINFORMATIVE cells included** — the reading §B.3.2 derives and the one §V applied to
  both C1 and R3. `C3` and `R2` keep the UNINFORMATIVE conditions they were pre-registered with.
  Where a criterion is computed on a pool containing an UNINFORMATIVE cell, **the exclusion
  sensitivity is reported alongside it** — which §V.3 and §V.5 already did for both strata, and
  which is now required rather than voluntary.

### B.5 What this amendment does NOT change

No threshold, no arm, no task, no scorer, no tier, no repeat count, no `n`, and no row. §5's
C1/C2/C3 and R1–R4 keep their inequalities and their numbers. §6.1's U-1 … U-5 keep their
thresholds. §6.2, §6.3 and §6.4 are untouched. **§V's verdict of REFUTED is unchanged**, and the
run is not re-scored: §B.3 concludes that the text as pre-registered compels the reading §V
applied. Nothing above the *"Amendment 2"* heading is edited.

### B.6 What of `RB-P88`'s own claims did not reproduce

The register entry is a claim and was re-derived rather than transcribed. **Everything in it
reproduces**: `4/12 = 33.3%` and `4/36 = 11.1%`; `p = 0.006348` with the 7b in and
`p = 0.0625` with it out; REFUTED versus §5.3 NEITHER; U-1's and U-2's *"of `reader`-arm runs in
the cell"*; V-3's *"that task for every arm"*; §6.1's opening sentence; R2's *"with a
non-UNINFORMATIVE cell"* and R3's lack of one. Three things it did not state, found here:

1. **The numerator does not move between the readings.** `bare` and `paste` contribute **zero**
   bad-outcome rows at `7b`/large-IN, so Reading B's fraction is `4/36` and not something
   larger. The entry asserted 11.1% without that check; the check passes.
2. **U-5 belongs in the entry's stable-denominator list.** Amendment 1 added it *after* the
   entry's evidence was gathered and it names its arm, so §6.1 contains **four** unambiguous
   predicates against one ambiguous one, not three against one.
3. **The ambiguity in *"cell"* is not confined to §6.1.** §5 uses the word with two further
   referents, one of them in the same sentence as the other (§B.0). The entry's narrower claim
   — that the *denominator* defect is single rather than systemic — still holds, and D-1 is
   scoped to predicates for that reason.

## Amendment 3 — 2026-08-20

**Status: the run has been scored.** This amendment is held to the same rule as Amendment 2:
**it changes no threshold, flips no clause, re-scores no row, and does not edit one character
above this heading.** It records a defect in a *guard* — a predicate that was written to catch a
truncated prompt and cannot catch one at the tier where it happened. The forward rules in §C.5
bind the *next* bar; they do not re-score this one.

Written by the `RB-P87` unit. Every figure below was re-derived in this worktree at `81f847b`:
the token readings by running G-3's own instrument against the live daemon, the pass counts by
reading the committed `.jsonl`. No row was regenerated, no model was pulled — `llama3.2:3b` was
already resident — and the `PASTE_MAX_BYTES` in the code this unit called is Amendment 1's
**8,621**.

### C.0 The defect, in one sentence

**`V-1`'s threshold is an absolute token count — `0.85 × 8,192 = 6,963` — derived from *one*
tier's window, and the counter it reads cannot return more than the window it is served, so at
any tier served a window below 6,963 the predicate is not merely unlikely to fire: it is
UNFIREABLE, at any prompt of any size, and it reports OK most confidently where the truncation
is deepest.**

That last clause is the part that makes it a rule defect rather than a tuning miss. A clamped
counter returns the window. The smaller the served window, the smaller every reading from that
tier, the further every reading sits below a fixed threshold — so a guard written this way gets
*quieter* as the thing it guards against gets *worse*. It fails safe-looking.

| served window `W` | largest reading the counter can ever return | `V-1`'s threshold | can `V-1` fire, at any prompt? |
|---:|---:|---:|---|
| 8,192 — the three compared tiers, pinned in the Modelfile (§8) | 8,192 | 6,963 | yes |
| **4,096 — `llama3.2:3b`, measured in §C.1** | **4,096** | 6,963 | **no** |
| any `W` < 6,963 | `W` | 6,963 | **no** |

### C.1 The 3b's served window, measured — and what a clamped reading is *not* evidence of

§6.4 named the served window of `llama3.2:3b` UNMEASURED. It is measured here, with G-3's own
instrument: `/api/generate`, `num_predict=1`, reading `prompt_eval_count`, never `/v1`'s
`usage.prompt_tokens`. Daemon: `ollama version 0.18.0`, no `OLLAMA_*` variable set in the
environment; G-2 re-derived at the same time — `ollama show --modelfile llama3.2:3b` declares
**no `num_ctx`**, and the three `bk-rbp27-*` tags each declare `PARAMETER num_ctx 8192`.

<!-- provenance: value=llama3.2:3b prompt_eval_count = 4096 on the system reading and the system+task reading, for both corpora, at PASTE_MAX_BYTES=8621; commit=81f847b (worktree, code unchanged since 1a8e382); command=PYTHONPATH=runtime-py/src BANTAMKIT_ASSETS=assets python3 -c "import json,tempfile,urllib.request,yaml;from pathlib import Path;from bantamkit.evalrun import materialise_documents,_paste_head;g=lambda m,p:json.loads(urllib.request.urlopen(urllib.request.Request('http://localhost:11434/api/generate',data=json.dumps({'model':m,'prompt':p,'stream':False,'options':{'num_predict':1}}).encode(),headers={'Content-Type':'application/json'}),timeout=900).read())['prompt_eval_count'];[print(c,len(s.encode()),g('llama3.2:3b',s)) for c,t in (('small','doc-small-137'),('large','doc-large-in-137')) for k in [yaml.safe_load(open('assets/evals/document/tasks/%s.yaml'%t).read())] for d in [tempfile.mkdtemp()] for f in [materialise_documents(k,Path(d)/t,'paste')] for h in [_paste_head(f)] for s in (h,h+'\n'+k['prompt'])]" -->

    llama3.2:3b  small corpus  system 8,962 B -> 4096   system+task 9,324 B -> 4096
    llama3.2:3b  large corpus  system 9,016 B -> 4096   system+task 9,378 B -> 4096

**`RB-P53` is the reason this table cannot be read the obvious way.** A reading of 4,096 is
**not** a measurement that the prompt is 4,096 tokens; it is evidence that the *window* is
4,096 and that the counter has been pinned to it. Two independent facts establish the clamp,
and neither is an inference from the number's roundness:

1. **Two prompts of different sizes return the identical count.** The system message and the
   system message plus the 361 B task prompt differ by 362 B — about 168 tokens at this
   content's measured rate — and both read exactly 4,096, at both corpora. A counter that
   reported the prompt could not do that.
2. **The reading saturates, and the saturation is visible.** Prefixes of the 9,016 B large-corpus
   system message, same instrument, same model:

<!-- provenance: value="the 3b saturation ladder below"; commit=81f847b; command=the §C.1 command above with the prompt replaced by _paste_head(...).encode()[:n].decode('utf-8','ignore') for n in (2048,4096,6000,8000,8600,8800,8900,9016) -->

    prefix  2,048 B -> 900     prefix  8,600 B -> 3943
    prefix  4,096 B -> 1852    prefix  8,800 B -> 4037
    prefix  6,000 B -> 2735    prefix  8,900 B -> 4084
    prefix  8,000 B -> 3665    prefix  9,016 B -> 4096

   The reading tracks the prompt all the way up — `8,800 → 8,900 B` buys **+47** tokens, a
   marginal **2.128 B/token** — and then the last 116 B buys **+12**, where the same rate
   predicts +54. It stops at 4,096 and does not move again for another 362 B. **That is where
   the window is.**

**How much is being lost, stated as an estimate and labelled as one.** Extrapolating the
measured marginal rate of 2.128 B/token past the saturation point, the true prompt is **≈ 4,139
tokens** for the system message and **≈ 4,309** for the request the run actually sends. Against
a 4,096 window that is **≈ 213 tokens, ≈ 4.9% of the request**, that never reached the model —
about **21 of the paste's 401 rendered rows**, at the corpus's 21.50 B/row. These four numbers
are estimates off a measured slope, not readings; the two readings are 4,096 and 4,096.

**Which end the daemon cut is not determined here, and the run recorded nothing that would
determine it.** §10.2 spends a whole clause on never cutting a row in half, because *"half a row
is a value the model can misread as a whole one"*; the daemon's clamp is under no such
discipline and announces nothing. **That absence is part of the defect, not a gap in this
amendment:** `V-1` existed to make exactly this decidable before the run, it reported OK, so the
432 committed rows carry no record of what was removed from the 3b's paste.

### C.2 What `V-1` catches as written, and what it would catch window-relatively

All six compared readings re-derived in this worktree, and all six reproduce Amendment 1 §A.3
and §V.4 to the digit.

<!-- provenance: value="the six compared-tier request readings 6,602 / 6,627 / 6,623 / 6,648 / 6,623 / 6,648, re-derived"; commit=81f847b; command=the §C.1 command with 'llama3.2:3b' replaced by each of bk-rbp27-qwen3-4b-instruct, bk-rbp27-qwen2.5-7b-instruct, bk-rbp27-qwen2.5-14b-instruct -->

| tier | served `W` (G-2) | request reading (G-3), small / large | clamped? | `V-1` as written, `≥ 6,963` | window-relative, `≥ 0.85 × W` | reading ÷ `W` |
|---|---:|---:|---|---|---|---:|
| 4b | 8,192 | 6,602 / 6,627 | no | ok | ok — `≥ 6,963` | 0.806 / 0.809 |
| 7b | 8,192 | 6,623 / 6,648 | no | ok | ok — `≥ 6,963` | 0.808 / 0.812 |
| 14b | 8,192 | 6,623 / 6,648 | no | ok | ok — `≥ 6,963` | 0.808 / 0.812 |
| **3b** | **4,096** | **4,096 / 4,096** | **yes** | **ok — does not fire** | **VOID — `≥ 3,481`** | **1.0000 / 1.0000** |

**Three things this table settles, and the first one is why the window-relative form is not a
re-scoring.**

1. **At the three compared tiers the two forms are the same predicate.** `0.85 × 8,192` *is*
   6,963. The window-relative form changes no compared reading, no compared cell, and no figure
   in §V. It differs from the pre-registered text at **exactly one tier**, the declared floor,
   and it differs there by VOIDing an arm the bar already forbids anyone to compare (§6.4).
2. **The ratio column reaches exactly 1.0000, and that is the general result.** A clamped
   reading divided by its own window is 1 — the largest value the quantity can take. So a
   window-relative threshold at *any* fraction below 1.0 fires on *every* clamped reading,
   automatically, at every tier, forever. The predicate stops depending on which window the
   drafter had in mind.
3. **The refusal form is cheaper still and needs no instrument.** §6.4 had already written down
   that this tier's window was UNMEASURED. A clause that refuses to evaluate where the window is
   unknown would have VOIDed the 3b's `paste` arm **on the strength of §6.4 alone**, before G-3
   was called at all and before anybody knew the number was 4,096. The information needed to
   protect the run was in the document at pre-registration; what was missing was a sentence that
   made the absence of a measurement do something.

### C.3 What the entry's superlative claims, and what actually reproduces

The register entry says the 3b's prompt is *"being truncated harder than any arm the rule did
VOID."* **That does not reproduce**, and the statement that replaces it is sharper.

1. **`V-1` VOIDed no graded arm, in this run or ever.** §V.4 records *"V-1 did not fire at any
   compared tier"*, and this unit re-derived all six readings (§C.2). `V-1`'s only firings in
   the bar's whole history are Amendment 1 §A.1's six **pre-run calibration** readings at the
   pre-registered `PASTE_MAX_BYTES = 12,288` — and no arm was ever graded in that state, because
   the constant was amended instead. *"Any arm the rule did VOID"* names an empty set.
2. **Measured against those calibration readings, the 3b is truncated LESS, not more.**
   Re-derived on the 4b at the pre-registered constant: the 12,672 B system message reads
   **8,192 — clamped**, saturating from about 11,300 B, at a measured marginal **1.325 B/token**;
   extrapolated, the true prompt is **≈ 9,273 tokens**, so **≈ 1,081 tokens ≈ 11.7%** did not
   reach the model. The 3b's 4.9% is about **2.4× smaller as a fraction and 5× smaller in
   absolute tokens**.

<!-- provenance: value=4b at PASTE_MAX_BYTES=12288 reads 8,192 on the 12,672 B system message, saturating between 11,200 B (8,162) and 11,400 B (8,192); commit=81f847b; command=the §C.1 command with bantamkit.evalrun.PASTE_MAX_BYTES set to 12288 before _paste_head, model bk-rbp27-qwen3-4b-instruct, prefixes (9016,10000,11000,11200,11400,12672) -->

    4b @ 12,288  prefix  9,016 B -> 6536   11,000 B -> 8011   11,400 B -> 8192
                 prefix 10,000 B -> 7266   11,200 B -> 8162   12,672 B -> 8192

3. **The claim that does reproduce is the one worth making.** In the graded run, **the 3b's
   `paste` arm is the only arm of the 432 rows whose prompt was truncated at all** — every
   compared cell sat 1,544 tokens under its window, a 18.85% margin (§A.3) — **and `V-1`, the
   single clause in this bar written to catch a truncated paste, reports OK on it.** A guard
   silent on the run's *only* truncated arm is a worse finding than a guard silent on a
   worse-truncated arm that never ran.

### C.4 Whether any published figure depends on the 3b's `paste` passes

**Counted here from the committed rows, not taken from the entry.** The four run files landed at
`39f7aaf` and are unchanged at `81f847b`.

<!-- provenance: value=3b paste passes 2 (small), 4 (large-IN), 0 (large-OUT) = 6 of 36, and tool_calls == 0 on every paste row; commit=81f847b (rows unchanged since 39f7aaf); command=python3 -c "import json;R=[json.loads(l) for l in open('docs/eval-data/2026-08-20-document-read-3b.jsonl')];st=lambda t:'small' if t.startswith('doc-small') else 'large-IN' if t.startswith('doc-large-in') else 'large-OUT';P=[r for r in R if r['config']=='paste'];[print(s,sum(1 for r in P if st(r['task'])==s and r['passed']),'/',sum(1 for r in P if st(r['task'])==s)) for s in ('small','large-IN','large-OUT')];print('tool_calls nonzero:',sum(1 for r in P if r.get('tool_calls')))" -->

    small 2/12    large-IN 4/12    large-OUT 0/12    total 6/36    tool_calls nonzero: 0

**The entry's count reproduces exactly: 2, 4, 0.**

**No compared figure reads them.** §V.1's three McNemar rows and every `P(paste)` / `P(reader)`
in them are pooled over 4b/7b/14b at the `n = 36` §5 fixes. Re-derived on both pools:

<!-- provenance: value="the two-pool table below"; commit=81f847b (rows unchanged since 39f7aaf); command=python3 -c "import json,math;P='docs/eval-data/2026-08-20-document-read-%s.jsonl';L=lambda t:[json.loads(l) for l in open(P%t)];st=lambda t:'small' if t.startswith('doc-small') else 'large-IN' if t.startswith('doc-large-in') else 'large-OUT';M=lambda b,c:min(1.0,2*sum(math.comb(b+c,i) for i in range(min(b,c)+1))/2**(b+c));[print(pool,s,'n=%d paste=%d reader=%d b=%d c=%d p=%.6f'%(len(k),sum(d[(*x,'paste')] for x in k),sum(d[(*x,'reader')] for x in k),b,c,M(b,c))) for pool in (['4b','7b','14b'],['4b','7b','14b','3b']) for s in ('small','large-IN','large-OUT') for d in [{(t,r['task'],r['repeat'],r['config']):r['passed'] for t in pool for r in L(t) if st(r['task'])==s}] for k in [sorted({x[:3] for x in d})] for b in [sum(1 for x in k if d[(*x,'reader')] and not d[(*x,'paste')])] for c in [sum(1 for x in k if d[(*x,'paste')] and not d[(*x,'reader')])]]" -->

| stratum | pool | `n` | `P(paste)` | `P(reader)` | Δ | `b` | `c` | `p` |
|---|---|---:|---:|---:|---:|---:|---:|---|
| small | 4b+7b+14b — **as published** | 36 | 1.0000 | 0.4722 | −0.5278 | 0 | 19 | 0.000004 |
| small | with the 3b pooled in | 48 | 0.7917 | 0.3542 | −0.4375 | 0 | 21 | 0.000001 |
| large-IN | 4b+7b+14b — **as published** | 36 | 0.8889 | 0.6111 | −0.2778 | 1 | 11 | **0.006348** |
| large-IN | with the 3b pooled in | 48 | 0.7500 | 0.4583 | −0.2917 | 1 | 15 | 0.000519 |
| large-OUT | 4b+7b+14b — **as published** | 36 | 0.0000 | 0.4167 | +0.4167 | 15 | 0 | 0.000061 |
| large-OUT | with the 3b pooled in | 48 | 0.0000 | 0.3125 | +0.3125 | 15 | 0 | 0.000061 |

Every published row is the 4b+7b+14b row, to the digit. **The exclusion is load-bearing — pooling
the 3b in would move `P(paste, small)` from 1.0000 to 0.7917 and Δ(large-OUT) from +0.4167 to
+0.3125 — and it is pre-registered rather than chosen after the fact:** §8 declares the 3b a
floor that is never pooled, §5 fixes `n = 36` over the three compared tiers, §6.4 forbids
comparing any 3b `paste` number to another tier's, and §7.5 declines a tier comparison outright,
naming the unequal windows as one reason. **Four sentences, all written before any arm ran, and
the protection comes from them and not from `V-1`.**

**What the 3b's `paste` rows DO reach, recorded so it is not discovered later.** Two things,
neither of them compared:

1. **§V.1's pass table prints them.** The 3b row reads `0 / 2 / 0`, `0 / 4 / 0`, `0 / 0 / 0` —
   those three `paste` figures **are** these passes. They are published as descriptive counts of
   an arm whose prompt was silently truncated, on a row of a table whose other rows were not,
   and the prohibition on comparing them lives in §6.4 and §7.5 rather than beside the number.
   That is a presentation hazard, not a wrong figure, and §C.5's restatement is where it is
   closed for the next bar.
2. **§V.4's `U-3` firing at `3b`/large-OUT reads `P(paste) = 0` in that cell.** That zero does
   not depend on the clamp: §3.1 puts the large-OUT answer row outside the 8,621 B cut by
   construction, so the `paste` ceiling there is zero at every tier and is 0/36 at the three
   compared ones too. The firing survives the truncation being there or not.

**And nothing can be inferred from the 6 in either direction.** Against the 3b's committed floor
rate of **0.2557 (135/528, `docs/eval.md:7147`, re-derived by §8)**, 6 of 36 gives
`P(X ≤ 6) = 0.1499` on the binomial — the arm is **not distinguishable from the declared floor**.
Per task the passes are `doc-large-in-359` 4/4 and `doc-small-388` 2/4, with the other seven
tasks 0/4; every compared tier scores 4/4 on `doc-small-137` and `doc-large-in-137` where the 3b
scores 0/4. **No causal reading of that pattern is offered here and none is available**: all 30
non-passing rows are `outcome == "wrong-answer"`, which is what the floor produces anyway, and
§C.1 could not establish which end the daemon cut. **The clamp's effect on the 3b's `paste`
score is unmeasured and, from these rows, unmeasurable.**

### C.5 The forward rule — binding on the next bar, not on this run

**Two rules, in the shape of §B.4's D-1 and D-2, and they are not optional for any bar written
after this date:**

- **D-3 — a predicate that compares a measurement to a window is a function of the window it is
  evaluated against.** Its threshold is written as a fraction of `W(tier)`, the served window of
  the tier the predicate is being evaluated at, with `W(tier)` named and sourced to the gate that
  reads it. A bare constant is admissible only where the bar has *pinned* the same window for
  every tier the predicate ranges over, and even then it is written as `f × W(tier)` with the
  arithmetic shown, so that adding a tier cannot silently disarm it. **Corollary, because it is
  the mechanism that made this fail quietly: a counter that can clamp is read against its own
  ceiling.** A reading equal to the served window is a clamp, never a prompt size; the bar
  records the reading, the window, and their ratio, and never the reading alone.
- **D-4 — where the window is unknown, the predicate refuses to evaluate and the arm is VOID.**
  A bar that names a served window UNMEASURED has already said its window predicate cannot be
  evaluated at that tier; the consequence is **VOID — the row is not a measurement of anything**,
  not *"uncompared but reported"*. **Silence from a guard is not a pass.** A guard that cannot
  reach its own threshold must say so at the moment it is evaluated, not leave a reader to infer
  it from a number that looks fine.

**Applied to this bar's own text as an explicit restatement, forward-effect only.** These change
no threshold, flip no clause, re-score no row, and annotate no published table; they exist so a
re-deriver never has to repeat §C.1–§C.3.

- **`V-1` (restated).** *For any `paste`-arm run at a tier, if the pre-run calibration of §10.3
  measured the paste request at **`≥ 0.85 × W(tier)`**, where `W(tier)` is the served `num_ctx`
  of that tier as read by G-2, the `paste` arm is **VOID at that tier** and may not be compared.*
  Firings under the restatement, at `81f847b`: **the 3b's `paste` arm, both corpora
  (4,096 ≥ 3,481, i.e. `0.85 × 4,096`)**, and **no compared cell** — at `W = 8,192`, `0.85 × W`
  is 6,963 and the restatement is the pre-registered sentence, unchanged, arithmetic and all.
- **`V-1` (restated) — the refusal limb.** *Where G-2 cannot read a tier's `num_ctx`, the `paste`
  arm at that tier is VOID without a G-3 call.* Under the restatement the 3b's `paste` arm was
  VOID at pre-registration, on §6.4's own admission, before any number existed.
- **§6.4 (restated).** An UNMEASURED served window makes the `paste` arm at that tier **VOID**,
  not merely uncompared. *"No number may be compared"* and *"the row is a measurement"* cannot
  both be true of the same row.
- **§10.3's G-2 and G-3 (restated).** G-2 runs for **every declared model, the floor included**,
  and its reading is what G-3's predicate is evaluated against. G-3 records, per (tier, corpus),
  the reading, the window, and the ratio — three numbers, not one — and **a ratio of exactly
  1.0000 is reported as a clamp on its face.**
- **Reporting (restated).** Where a run publishes a descriptive figure from an arm that any
  clause VOIDs or forbids comparing, the figure carries that mark **in the table that prints it**.
  This is forward-effect only and does not annotate §V; what it requires of the next bar is that
  such a cell is printed with its mark or not printed at all.

### C.6 What this amendment does NOT change

No threshold, no arm, no task, no scorer, no tier, no repeat count, no `n`, and no row. `V-1`'s
6,963 stands as pre-registered and as applied. §5's C1/C2/C3 and R1–R4 keep their inequalities
and their numbers; §6.1's U-1 … U-5 keep their thresholds; §6.2, §6.3 and §6.4 are untouched.
**§V's verdict of REFUTED is unchanged, and it never depended on the 3b's `paste` arm** — §C.4
re-derives that from the committed rows. `PASTE_MAX_BYTES` stays at Amendment 1's 8,621. Nothing
above the *"Amendment 3"* heading is edited.

### C.7 What of `RB-P87`'s own claims did not reproduce

The register entry is a claim and was re-derived rather than transcribed.

**Reproduces:** all four `4,096` readings, on both counters for both corpora; the 8,962 B and
9,016 B system messages; `V-1`'s `0.85 × 8,192 = 6,963`; `4,096 < 6,963`, so `V-1` as written
does not fire and the 3b's `paste` arm is not VOID by the rule; §6.4's naming of the served
window as UNMEASURED and its prohibition on comparing a 3b `paste` number; **the 6 paste passes,
2 small / 4 large-IN / 0 large-OUT**; and that no figure in §V.1's compared pool depends on them.

**Four things it did not state, or stated differently, found here:**

1. **Does not reproduce — *"truncated harder than any arm the rule did VOID."*** `V-1` VOIDed no
   graded arm in this bar's history, and measured against the pre-run calibration readings it
   *did* fire on, the 3b is truncated **≈ 2.4× less** as a fraction of prompt (4.9% against
   11.7%) and ≈ 5× less in absolute tokens. §C.3 states what replaces it: the 3b's `paste` is the
   **only** truncated arm in the graded run, and `V-1` reports OK on it.
2. **The entry understates the failure.** It says a fixed-fraction threshold is *"silently
   inapplicable"* at a different window. Measured, it is **unfireable**: no prompt of any size
   can make a clamped counter return 6,963 at a 4,096 window, so the guard is not weakened
   there — it is absent. And because `4,096 ÷ 4,096 = 1.0000` exactly, **any** window-relative
   threshold below 1.0 catches this clamp automatically (§C.2).
3. **A one-byte discrepancy inside the record, which changes nothing and is recorded anyway.**
   The entry's `9,324` / `9,378` are the system message joined to the 361 B task prompt by a
   **single** newline; Amendment 1 §A.3 records the same pair as `9,325` / `9,379`, a two-byte
   joiner. Both readings return the **identical** `prompt_eval_count` at every tier measured
   here — 6,602 / 6,627 / 6,623 / 6,648 / 6,623 / 6,648 on the compared tiers and 4,096 on the
   3b — so no number in either document depends on it.
4. **How much is lost, and what is not knowable about it.** The entry gives no magnitude. It is
   ≈ 213 tokens, ≈ 4.9% of the request, ≈ 21 of 401 rendered rows (§C.1, extrapolated off a
   measured slope and labelled as an estimate) — and **which end the daemon cut is not
   determined, because `V-1` reported OK and so the run recorded nothing that would determine
   it.**
