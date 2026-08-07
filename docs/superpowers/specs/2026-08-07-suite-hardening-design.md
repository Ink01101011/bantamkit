# Suite Hardening Design

**Date:** 2026-08-07
**Status:** Executed — shipped on feat/suite-hardening; §5 criterion 1 unmet as written (see docs/eval.md "How the suite was hardened")
**Depends on:** eval-quality cycle (PR #3, `633c287`)

## 1. Problem

The reference sweep (qwen3:4b-instruct, 6 configs × 15 tasks) showed the score
column is decided entirely by the memory-recall family: extraction and tool-use
saturate at 10/10 across every config, so the `structured` and `critique`
primitives have zero tasks on which they can show value. And the harness records
too little per run to say *why* a config passed or failed, or what a gate
actually did — `TaskResult` is only `(task, config, passed, tokens, error)`.

Two consequences:

1. We cannot measure the marginal value of `structured` or `critique` at all.
2. Even where numbers differ, we can only see *that* they differ, not the
   mechanism — no failure taxonomy, no gate-activity counts, no per-family
   breakdown without hand-computing it from raw results.

## 2. Goal

Make the suite discriminate and make the harness explain. Two parts:

- **Part 1 — Measurement dimensions:** extend `TaskResult`, the gates, and the
  report so every run records what happened (outcome class, gate activity,
  call counts) and the report surfaces where configs differ and why.
- **Part 2 — Calibrated hard tasks:** author candidate tasks aimed at known
  small-model weaknesses, then *measure* their difficulty against the reference
  model and promote only those that are (a) hard bare and (b) rescued by at
  least one primitive. No task enters the suite on intuition alone — that is
  exactly how the current saturated tasks got in.

Part 1 ships first because Part 2's calibration runs on it.

## 3. Part 1 — Measurement dimensions

### 3.1 `TaskResult` extension

```python
@dataclass
class TaskResult:
    task: str
    config: str
    family: str            # copied from the task file
    passed: bool
    tokens: int
    outcome: str           # taxonomy below
    model_calls: int       # chat() calls made (TrackingClient counts)
    tool_calls: int        # tool invocations in the transcript (0 for structured())
    schema_retries: int    # schema-violation feedback rounds actually spent
    critique_rounds: int   # critique revision feedbacks actually issued
    error: str | None      # unchanged: message when a BantamError was raised
```

### 3.2 Outcome taxonomy

Derived deterministically in `run_task`, one value per run:

| outcome | meaning |
|---|---|
| `pass` | scored true |
| `wrong-answer` | scored false; output parsed/matched mechanics fine, content wrong |
| `malformed-output` | `json_equal` task whose output failed `extract_json` |
| `schema-exhausted` | `StructuredOutputError` raised (retry budget spent) |
| `critique-exhausted` | `CritiqueExhausted` raised |
| `config-error` | `EvalConfigError` raised |
| `transport-error` | any other `BantamError` (timeouts, API errors) |

This splits today's undifferentiated "failed" into *couldn't produce the
format* vs *produced the wrong content* vs *a gate gave up* — the three have
opposite remedies, and the split is what tells us which primitive to improve.

### 3.3 Gate activity counters

- `SchemaGate` gains a public `retries_used` counter: incremented every time it
  issues violation feedback, cumulative across the run (unlike the existing
  consecutive-violation `_attempts`, which keeps its reset-on-valid semantics
  for budget enforcement). Reset in `setup()`.
- `CritiqueGate` gains the same: `rounds_used`, incremented per revision
  feedback issued, reset in `setup()`. The consecutive `_rounds` budget logic
  is untouched. This also closes the ledger backlog item "gate-counter
  per-run reset" — counters now demonstrably start at zero per attach.
- `TrackingClient` counts `chat()` calls (`calls` attribute) alongside usage.
- For the `structured` config (no gates attached), `schema_retries` is derived
  as `model_calls - 1` — `structured()` makes exactly one call per attempt and
  nothing else runs on that path.
- A gate that shows `retries_used == 0` / `rounds_used == 0` across the sweep
  is pure token tax on that task — this is the number that makes "critique
  buys nothing here" a measurement instead of an inference from totals.

### 3.4 CLI

| Flag | Default | Meaning |
|---|---|---|
| `--repeats N` | 1 | Run each (config, task) N times. Fresh memory store and agent per repeat. |
| `--tasks DIR` | builtin assets | Load tasks from DIR instead — the calibration hook. |
| `--json PATH` | off | Append one JSON line per `TaskResult` as each run completes (streaming, so a killed sweep keeps its partial results). |

`--repeats` is both the error-bar tool (±1 task noise on a 15-task suite is
±7%; 3 repeats narrows the load-bearing comparisons) and the calibration
mechanism for Part 2.

### 3.5 Report

`format_report` grows three sections beyond the existing config table:

1. **Per-family table** — score and tokens per (config, family), the table we
   currently hand-compute for docs. With repeats, scores are shown as
   `passed/run` totals (e.g. `12/15` for 5 tasks × 3 repeats).
2. **Outcome histogram** — per config, counts of non-pass outcomes
   (e.g. `bare: wrong-answer ×4, malformed-output ×1`).
3. **Rescue matrix** — rows are *discriminating tasks only* (tasks not passed
   by every config), columns are configs, cells are pass fractions. Headline
   line above it: `discriminating tasks: N/<total>`. This is the suite-quality
   metric Part 2 moves.

The existing top table keeps its exact shape (score, tokens, score/1k tok) so
old and new reports stay comparable; with repeats, `score` shows total passes
over total runs and tokens are summed across repeats.

## 4. Part 2 — Calibrated hard tasks

### 4.1 Calibration protocol

1. Author ~12–15 candidates in `assets/evals/candidates/` (not globbed by
   `load_tasks`, so the shipping suite is untouched while calibrating).
2. Run `evalrun --tasks .../candidates --repeats 3` on qwen3:4b-instruct for
   `bare` plus each candidate's target configs.
3. **Promotion bar** — a candidate moves into `assets/evals/tasks/` iff:
   - bare passes ≤ 1/3 repeats (hard bare), **and**
   - at least one primitive config passes ≥ 2/3 repeats (rescuable — a task
     everything fails measures nothing, same as one everything passes).
4. Candidates failing the bar are tuned once and re-calibrated, or dropped.
   The `candidates/` directory is deleted at cycle end.

### 4.2 Candidate directions (per family)

- **structured-extraction:** nested objects and arrays under `json_equal`;
  type-coercion traps ("199 USD" → integer `199`, string-vs-number keys);
  distractor-laden source text (multiple invoices, only one matching the
  filter); optional-key discipline (schema forbids extras via
  `additionalProperties: false`). Failure mode targeted: bare emits prose or
  mistyped JSON; `structured`/`SchemaGate` feedback repairs it.
- **tool-use:** arithmetic chains over 3+ lookups (total cost of a basket,
  cheapest-per-unit with quantity math) scored by `json_equal` on the computed
  number; longer ordered `tool_trace` sequences. Requires expanding
  `fixtures/catalog.json` with more items (and a third lookup tool only if a
  candidate genuinely needs a new field). Failure mode targeted: bare does the
  arithmetic wrong or skips lookups; `critique` can catch self-inconsistent
  totals.
- **memory-recall:** multi-hop recall (answer combines two seeded facts);
  distractor stores where Jaccard-near facts must be disambiguated. These keep
  the memory family from saturating as models improve, and multi-hop is where
  `full` might finally beat `memory`.

All scoring stays deterministic (spec §4.6): `json_equal`, `contains`,
`tool_trace` only. No new scoring kinds.

### 4.3 Conformance updates

- Task-count floor raised from 15 to the shipped post-promotion count.
- Catalog invariants extended for new items (prices positive, names distinct).
- Memory-seeding Jaccard test and seeded-fact counter updated for new
  `memory_setup` blocks.
- If a third tool is added: registered in `BUILTIN_TOOLS`, listed in
  `docs/eval.md`, covered by conformance.

### 4.4 Final deliverable

Reference sweep on the hardened suite, all six configs, `--repeats 3`,
qwen3:4b-instruct. `docs/eval.md` Current results rewritten around the new
dimensions (family table and rescue matrix now come straight from the report),
including an honest re-answer of spec §7 and an explicit statement of what
`structured` and `critique` measurably buy — even if the answer is "nothing on
this model," it will now be a *measured* nothing with gate counters behind it.

## 5. Success criteria

1. ≥ 4 newly promoted discriminating tasks spanning ≥ 2 families.
2. `structured` or `lean` differs from `bare` on score beyond the repeat noise
   band on the hardened suite.
3. The report emits the family table, outcome histogram, and rescue matrix;
   `--json` produces one valid JSON line per run.
4. Gate counters answer "did the gate fire?" per run; every non-pass run has a
   non-`pass` outcome class.
5. Full test suite + ruff clean; conformance enforces the enlarged suite.

## 6. Out of scope

- Measuring on a smaller model (approach C) — possible follow-up, not this cycle.
- New scoring kinds, LLM-as-judge scoring, or rubric changes.
- Retiring or rewriting existing 15 tasks (they stay as the easy band —
  a suite of only hard tasks loses the floor signal).
- Changing the config list or gate retry budgets.
- TS runtime port.

## 7. Risks

- **Calibration is live-model work:** ~15 candidates × 3 repeats × ~3 configs
  ≈ 130–180 calls. Mitigated by `--json` streaming (killed runs keep partial
  data) and the Bash-timeout patterns from the last sweep.
- **The model may resist authored difficulty** (as the current 9 adversarial
  tasks proved). The calibration loop is the answer: tune-once-then-drop keeps
  the cycle bounded instead of chasing difficulty forever.
- **Repeats triple sweep cost.** Reference sweep becomes 6 × ~20 × 3 ≈ 360
  runs; the JSONL sweep script pattern already handles multi-hour runs.
