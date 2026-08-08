# Eval

← [README](../README.md) · [Install](install.md) · [Usage](usage.md) · [Memory](memory.md) · [MCP](mcp.md)

The point of the eval harness is one number: does the toolkit actually lift this
model, and at what token cost? It runs the same task suite under several
harness configurations against the same endpoint.

## Run it

```bash
.venv/bin/python -m bantamkit.evalrun \
  --base-url http://localhost:11434/v1 \
  --model qwen2.5:7b-instruct
```

| Flag | Required | Meaning |
|---|---|---|
| `--base-url` | yes | OpenAI-compatible endpoint, including the path prefix |
| `--model` | yes | Model name as the endpoint knows it |
| `--config` | no | One of `bare`, `structured`, `critique`, `memory`, `lean`, `full`. Repeatable. Default: all six |
| `--timeout` | no | Per-request timeout in seconds. Default: 60 |
| `--repeats` | no | Runs per (config, task) pair. Default: 1. Repeats narrow the run-to-run noise band and are how candidate tasks are calibrated |
| `--tasks` | no | Directory of task YAML files to run instead of the builtin suite |
| `--json` | no | Append one JSON line per finished run (all `TaskResult` fields) to this file as the sweep progresses — a killed sweep keeps its partial results |

Narrow it while iterating:

```bash
.venv/bin/python -m bantamkit.evalrun \
  --base-url http://localhost:11434/v1 --model qwen2.5:7b-instruct \
  --config bare --config full
```

Every task runs against a live model, so a full sweep is 6 configs × all tasks
× `--repeats` runs. Start with `--config bare --config full`, and pass `--json`
on long sweeps so partial results survive an interrupted run.

You can also drive it from Python:

```python
from bantamkit import OpenAICompatible, format_report, run_suite

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")
results = run_suite(client, configs=["bare", "full"])
print(format_report(results))
for r in results:
    print(r.config, r.task, r.passed, r.tokens, r.error)
```

## The config matrix

Each config is the same tasks with a different harness wrapped around them.

| Config | What is enabled |
|---|---|
| `bare` | The agent loop and the task's tools only — the control |
| `structured` | Tasks with a `schema` bypass the loop and go through `structured()` |
| `critique` | A `CritiqueGate` on the `task-completion` rubric scores each answer |
| `memory` | Tasks with `memory_setup` get a seeded `Memory` store attached |
| `lean` | memory + schema enforcement inside the agent loop — `full` without the critique gate |
| `full` | critique + memory + schema enforcement, all inside the agent loop |

A component only engages where the task gives it something to work with: no
`schema`, no schema enforcement; no `memory_setup`, no memory store. So a
component is measured against `bare` on its own task family, and the off-family
tasks should come out roughly unchanged.

`structured` and `full` handle schemas differently, and the difference matters
when you read the numbers:

- **`structured`** hands the task to `structured()`, which runs its own
  validate-and-retry loop. That loop has no agent transcript, so tools and
  memory are not available to those tasks — it isolates the structured-output
  primitive. A task combining `schema` with `tool_trace` scoring is unscoreable
  here and raises `EvalConfigError`, reported as an explicit failure rather than
  silently scored zero.
- **`full`** keeps the agent in charge. The schema instruction is appended to the
  system prompt and a `SchemaGate` post-hook is registered, so the agent runs its
  normal loop with memory and the critique gate active. When the final answer
  violates the schema the gate does **not** score it as a loss — it feeds back a
  pointed validation error (`JSON does not match schema at '<path>': ...`) and
  the agent gets a revision round, exactly as `structured()` does.

Two details make that comparison fair rather than flattering:

- **Comparable budgets.** `SchemaGate` allows 3 attempts, matching
  `structured()`'s `max_retries=3`, so neither config is handed an obviously
  larger retry allowance. The counting is not identical, though:
  `structured()` gets 3 attempts *in total*, while `SchemaGate` counts 3
  *consecutive* violations and resets its counter on any schema-valid answer
  (`evalrun.py`). Since a critique revision round can follow a valid answer,
  `full` can spend more schema retries across a whole task than `structured`
  can. Read the comparison as close, not exact. Exhausting the budget raises
  `StructuredOutputError`, which lands under explicit failures rather than
  crashing the sweep.
- **Gate ordering.** `SchemaGate` is registered *ahead* of `CritiqueGate`, so
  malformed output is repaired before a critique call is spent on it. Reviewing
  the quality of unparseable JSON would burn tokens to reach the same verdict.

So `full` stacks all three primitives on one run — see
[Current results](#current-results) for whether that stack earns its bill
(on the current suite, `lean` does the same work for 29% fewer tokens).

`lean` exists to answer one question: how much of `full`'s token bill is the
critique gate? `lean` runs the same agent loop with memory and `SchemaGate`
but no critic, so `full − lean` isolates critique's cost and uplift.

Memory stores are seeded fresh per task per config in a temp directory, so runs
do not contaminate each other.

## Reading the report

A report looks like this (numbers illustrative; for measured ones see
[Current results](#current-results)):

```
| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 3/6 | 4821 | 0.62 |
| full | 5/6 | 9137 | 0.55 |

Per family (score · tokens):
| config | memory-recall | structured-extraction | tool-use |
|---|---|---|---|
| bare | 1/2 · 721 tok | 1/2 · 1200 tok | 1/2 · 2900 tok |
| full | 2/2 · 2500 tok | 2/2 · 2015 tok | 1/2 · 4622 tok |

Failure outcomes:
- bare: malformed-output ×1, wrong-answer ×2
- full: critique-exhausted ×1

Discriminating tasks: 2/6
| task | bare | full |
|---|---|---|
| extract-order | 0/1 | 1/1 |
| shop-total | 0/1 | 0/1 |
| recall-deploy | 0/1 | 1/1 |

Explicit failures:
- full/shop-total: CritiqueExhausted: below threshold 7 after 3 rounds; last feedback: ...
```

- **score** — tasks passed / tasks run for that config.
- **tokens** — prompt + completion tokens across every model call the config
  made, including critique-scoring calls and structured-output retries.
- **score/1k tok** — passes per 1000 tokens: the efficiency column. A harness
  that buys +2 passes for 2× the tokens shows up here honestly. Rising `score`
  with falling `score/1k tok` is a real trade, not a bug — decide whether the
  extra correctness is worth the spend.
- **Explicit failures** lists only tasks that raised a `BantamError`. A task that
  simply produced a wrong answer counts against `score` without appearing here.
  The three you are most likely to see: `StructuredOutputError` (schema retry
  budget exhausted, in `structured` or `full`), `CritiqueExhausted` (stayed below
  the rubric threshold), and `EvalConfigError` (`bantamkit.evalrun`) — the task
  and the config cannot be scored together, currently only `schema` +
  `tool_trace` under `structured`. `EvalConfigError` means fix the task file,
  not the model.

Three further sections appear when the results give them something to say:

- **Per family** — score and tokens per (config, family). This is where
  saturation shows: a family scoring identically under every config is not
  measuring the primitives.
- **Failure outcomes** — non-pass runs classified: `wrong-answer` (content
  wrong), `malformed-output` (a `json_equal` task whose output was not
  parseable JSON), `schema-exhausted` / `critique-exhausted` (a gate spent its
  budget), `config-error`, `transport-error`. Content-wrong and format-broken
  have opposite remedies, so they are never lumped together.
- **Discriminating tasks** — a pass-fraction grid over tasks that at least one
  run failed. A task counts as *discriminating* when at least one config passed
  all its runs and at least one passed none: those are the tasks that separate
  configs, and the `N/total` headline is the suite-quality number. Per-run gate
  counters (`schema_retries`, `critique_rounds` in the `--json` output) tell
  you whether a gate ever objected on a task — both count revision feedbacks
  handed back to the agent — or just billed tokens.

Tokens are read from the endpoint's `usage` field. Servers that omit it report
`0`, which makes `score/1k tok` read `0.00` — check the column is non-zero
before drawing conclusions.

Scores move between runs unless the endpoint is deterministic (temperature 0,
fixed seed). Compare configs within one sweep, not across sweeps.

## Current results

Reference sweep on the hardened suite — `qwen3:4b-instruct` (4B class,
non-thinking) served by Ollama, all six configs over the 19-task suite at
`--repeats 3`: 6 × 19 × 3 = 342 runs. The suite is 5 structured-extraction,
5 tool-use and 9 memory-recall tasks. Every per-run row, including the
`schema_retries` and `critique_rounds` counters the analysis below leans on,
is in `docs/eval-data/2026-08-07-reference-sweep.jsonl`; the calibration
sweeps that selected the new tasks sit beside it in the same directory.

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 30/57 | 12325 | 2.43 |
| structured | 30/57 | 13396 | 2.24 |
| critique | 30/57 | 65906 | 0.46 |
| memory | 57/57 | 43917 | 1.30 |
| lean | 57/57 | 44716 | 1.27 |
| full | 57/57 | 63085 | 0.90 |

Per family (score · tokens):

| config | memory-recall | structured-extraction | tool-use |
|---|---|---|---|
| bare | 0/27 · 4030 tok | 15/15 · 1059 tok | 15/15 · 7236 tok |
| structured | 0/27 · 4331 tok | 15/15 · 1840 tok | 15/15 · 7225 tok |
| critique | 0/27 · 47640 tok | 15/15 · 6135 tok | 15/15 · 12131 tok |
| memory | 27/27 · 35576 tok | 15/15 · 1053 tok | 15/15 · 7288 tok |
| lean | 27/27 · 35635 tok | 15/15 · 1835 tok | 15/15 · 7246 tok |
| full | 27/27 · 44162 tok | 15/15 · 6846 tok | 15/15 · 12077 tok |

```
Failure outcomes:
- bare: wrong-answer ×27
- structured: wrong-answer ×27
- critique: critique-exhausted ×11, wrong-answer ×16
```

Discriminating tasks: 9/19

| task | bare | structured | critique | memory | lean | full |
|---|---|---|---|---|---|---|
| recall-audit-retention | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-cache-ttl | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-db-port | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-deploy | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-env-endpoint | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall-rotation | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-org-quota | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-owner | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |

```
Explicit failures:
- critique/recall-cache-ttl: CritiqueExhausted: below threshold 7 after 3
  rounds; last feedback: The task asks for the cache TTL in seconds, but the
  answer states it cannot retrieve the value and provides "0" as a response.
  The required content is absent and incorrect because the cache TTL is not
  actually known or accessible, and providing a value of 0 without
  justification or correct information violates the requirement to give the
  correct number of seconds.
- critique/recall-cache-ttl: CritiqueExhausted: below threshold 7 after 3
  rounds; last feedback: The task requires the actual current cache TTL in
  seconds, but the answer does not provide this number. Instead, it explains
  the inability to retrieve it, which means the required factual content is
  absent.
  (9 more `critique-exhausted` entries of the same shape — see the JSONL)
```

The per-run gate counters are this sweep's headline, because they say what the
token columns alone cannot — whether a gate did work or only billed for it:

- **No schema gate in the sweep ever fired.** `schema_retries == 0` in all 342
  runs: the model did not violate a schema once, not inside `structured()` and
  not through `SchemaGate` under `lean`/`full`. The schema machinery repaired
  nothing. That makes `structured`'s extra cost over `bare` on extraction
  (1840 vs 1059 tokens for the same 15/15) *measured pure instruction tax* —
  the price of carrying the schema in the prompt, with no repair loop behind it.
- **The critic inside `full` never objected.** `critique_rounds == 0` in all 57
  `full` runs. `full − lean` is +18369 tokens (+41%) for +0 passes, and the
  counters show the whole delta is scoring-call overhead: not one revision
  round was bought with it.
- **Only the standalone `critique` config ever objected:** 27 revision rounds
  across 15 runs (`critique_rounds` counts revisions handed back to the agent,
  not scoring calls — an exhausted run records 2, not 3), every one on a
  memory-recall task, where that config has no store to answer from. Eleven of
  those runs ended `critique-exhausted` — the critic *correctly* refusing a
  fabricated or absent answer, as the feedback above shows — while the other
  16 memory failures were wrong answers the critic ultimately accepted (12 on
  first pass, 4 after buying a revision round or two).
- **Zero repeat variance.** Every one of the 114 (task, config) cells came out
  0/3 or 3/3: 87 at 3/3, 27 at 0/3, none split. At 3 repeats there is no noise
  band in this sweep for a difference to hide in.
- **Nine of 19 tasks discriminate, and all nine are memory-recall** — the five
  original recall tasks plus the four multi-hop/distractor tasks promoted this
  cycle. Extraction and tool-use are saturated: identical under every config.

Against spec §7, without spin:

- **"Full toolkit scores measurably higher than bare": met.** `full`, `lean`
  and `memory` all score 57/57 vs `bare` 30/57. But read the family table
  before celebrating: all 27 gained runs are memory-recall, and `memory` alone
  reaches 57/57 for fewer tokens than either `lean` or `full`. On this suite
  the uplift *is* the memory primitive; nothing else moves a task.
- **Does `lean` beat `bare` on score? Yes — 57/57 vs 30/57, +27 runs.**
- **Is `lean`'s score/1k near `bare`'s? No — 1.27 vs 2.43, about 52% of it.**
  The §7 "on par" bar is not met, and the gap is the same cheap-failure
  artifact as before: `bare` disposes of 27 recall runs for 4030 tokens total
  and banks zero passes, while `lean` spends 35635 tokens injecting the store
  index and wins all 27. On the 30 runs both configs pass, the gap nearly
  closes — `bare` 3.62 (30 passes / 8295 tok), `lean` 3.30 (30 / 9081),
  `memory` 3.60 (30 / 8341). The residual `bare` → `lean` gap is the schema
  instruction, and the counter data now shows that instruction repaired
  nothing. A config that skips work it would fail will always look efficient.
- **`full − lean` — critique's marginal cost and uplift: +18369 tokens (+41%)
  for +0 passes**, with `critique_rounds == 0` proving the critic never fired.
  Score/1k falls 1.27 → 0.90. `lean` is what you would ship; `full` is worth
  its bill only if your tasks have failure modes this suite does not contain.
- **Can structured output or critique be made to pay on this model? Measured,
  and the answer is no.** That was this cycle's goal, and the hardened suite
  answers it negatively with evidence rather than by omission. Extraction
  saturates at `bare` — the model simply does not emit malformed JSON here, so
  there is no repair for a schema gate to perform. The tool-use failures that
  *would* need a critic are unrescuable by the critic we have: the model does
  its lookups correctly and then botches the arithmetic or comparison, and
  `CritiqueGate` has no tool access, so it cannot check a tool-derived number
  and accepts the wrong one every time. The primitive this data motivates is
  **grounded critique** — a critic with access to the tool results and the
  transcript, able to recompute a claim instead of judging its prose.
- **Stretch ("competitive with a bare model one size class up"): still not
  re-measured.** The 7B comparison below is on the retired 6-task suite and is
  not comparable to these numbers.

### How the suite was hardened

The four promoted recall tasks came out of a calibration pass, not authoring
taste. Twelve candidate tasks were written to deliberately target the
structured and critique weaknesses above — 4 hard-extraction, 4 tool-use, 4
memory-recall — and each was run at 3 repeats across 5 configs
(`docs/eval-data/2026-08-07-calibration.jsonl`, 180 runs). The promotion bar
was: `bare` scores ≤1/3 **and** some config scores ≥2/3, i.e. the task must be
hard for the control and rescuable by a primitive.

All four hard-extraction candidates and two of the four tool-use candidates
saturated — 3/3 under every config, including `bare` — so they measure nothing
and were dropped. The remaining two tool-use candidates (multi-item basket
arithmetic, largest-shortfall comparison) failed 0/3 under *every* config, and
stayed 0/3 after a tuning pass
(`docs/eval-data/2026-08-07-calibration-tuned-rerun.jsonl`, 30 runs). Live
probes showed why: the model performs the tool lookups correctly and then gets
the arithmetic or the comparison wrong, and the critic signs off on the wrong
number — zero `critique-exhausted` outcomes on those runs, because
`CritiqueGate` cannot see tool ground truth. Unrescuable by any current
primitive, so they were not promoted. Only the four memory-recall candidates
cleared the bar, which is why the hardened suite is 9 recall tasks and still
5 + 5 elsewhere.

This misses the cycle's own promotion goal of new discriminating tasks in at
least two families — the calibration data is the evidence for why no other
family could clear the bar on this model: extraction saturates bare, and
tool-arithmetic failures have no rescuer while the critic cannot see tool
results.

### Prior baselines

Not comparable to the sweep above, and kept only for the before/after.

Pre-hardening 15-task sweep — the same model and the same six configs on the
**15-task suite at a single repeat**, before the four recall tasks were
promoted:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 10/15 | 3468 | 2.88 |
| structured | 10/15 | 3545 | 2.82 |
| critique | 10/15 | 16034 | 0.62 |
| memory | 15/15 | 9233 | 1.62 |
| lean | 15/15 | 9500 | 1.58 |
| full | 15/15 | 14350 | 1.05 |

| config | extraction | tool-use | memory-recall |
|---|---|---|---|
| bare | 5/5 · 351 tok | 5/5 · 2415 tok | 0/5 · 702 tok |
| structured | 5/5 · 615 tok | 5/5 · 2403 tok | 0/5 · 527 tok |
| critique | 5/5 · 2037 tok | 5/5 · 4030 tok | 0/5 · 9967 tok |
| memory | 5/5 · 351 tok | 5/5 · 2408 tok | 5/5 · 6474 tok |
| lean | 5/5 · 615 tok | 5/5 · 2421 tok | 5/5 · 6464 tok |
| full | 5/5 · 2272 tok | 5/5 · 4042 tok | 5/5 · 8036 tok |

Pre-cycle baseline — the same model on the **old 6-task suite with the old
rubric**:

| config | score | score/1k tok |
|---|---|---|
| bare | 3/6 | 2.27 |
| structured | 3/6 | 2.09 |
| critique | 3/6 | 0.47 |
| memory | 5/6 | 1.43 |
| full | 4/6 | 0.38 |

Do not read the 15-task and 6-task headline tables as a controlled
comparison. Three things changed
between them: the suite grew 6 → 15 tasks with a different family balance, the
`task-completion` rubric was retuned to judge content rather than format, and
`lean` did not exist. The `critique` and `full` rows in particular are **not**
apples-to-apples — their improvement is partly a better critic and partly an
easier-to-satisfy scoring path. The `bare` row is the honest anchor: it moved
3/6 → 10/15 (50% → 67%) purely because the expanded suite added families this
model handles well. The retuned rubric is also what turned `critique` from
score-negative into score-neutral: in the 6-task baseline adding the critic
*destroyed* a pass (`full` 4/6 under `memory` 5/6, rejecting correct answers
over formatting), whereas in the sweep above every `CritiqueExhausted` is the
critic refusing an answer that really was absent or fabricated.

Earlier sweep on the larger `qwen2.5:7b-instruct`, also on the old 6-task
suite, for comparison:

| config | score | score/1k tok |
|---|---|---|
| bare | 3/6 | 1.22 |
| structured | 3/6 | 1.62 |
| critique | 3/6 | 0.32 |
| memory | 5/6 | 1.36 |
| full | 5/6 | 0.33 |

On the 7B, `memory` beat bare on *both* columns (the shape spec §2.4 asks
for), and `structured` bought efficiency at equal score.

A note on thinking models (also measured on the old 6-task suite): the thinking
variant `qwen3:4b` emits hundreds of reasoning tokens per call (counted in
`tokens` — they are real cost). Its
partial sweep (`bare` 3/6 @ 0.29, `structured` 3/6 @ 0.58, `memory` 5/6 @
0.47) shows the same score shape at several times the token cost; the
critique/full configs were impractical to measure — calls exceed the
adapter's default 60s timeout. Use `--timeout` to increase the limit for
slow models. Prefer instruct variants for this suite.

Caveats: the reference sweep runs 3 repeats per (config, task), and observed
variance within it was zero — all 114 cells came out 0/3 or 3/3, none split.
That is a much stronger footing than the single-repeat baselines above, whose
±1-task run-to-run wobble made a 1-task difference between configs noise. It
is still a non-deterministic endpoint, though: zero observed variance at 3
repeats is not a guarantee of determinism, and nothing here is reproducible
run-for-run on another day or another server. Compare configs within one
sweep, not across sweeps.

## Add a task

Drop a YAML file in `assets/evals/tasks/`. The filename stem must equal `name`;
the suite globs the directory, so no registration step.

```yaml
name: extract-invoice          # must match the filename stem
family: structured-extraction  # structured-extraction | tool-use | memory-recall
prompt: |
  Extract the invoice as JSON with keys "number" and "total".
  Text: "Invoice INV-42, total 199 USD."
schema:                        # optional; enables the structured/full configs
  type: object
  required: [number, total]
  properties:
    number: {type: string}
    total: {type: integer}
scoring:
  kind: json_equal
  expected: {number: "INV-42", total: 199}
```

Fields:

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Matches the filename stem |
| `family` | yes | `structured-extraction`, `tool-use`, or `memory-recall` |
| `prompt` | yes | Non-empty; sent as the user message |
| `scoring.kind` | yes | `json_equal`, `contains`, or `tool_trace` |
| `scoring.expected` | yes | Shape depends on `kind`, below |
| `tools` | no | Names from the builtin fixtures: `price_lookup`, `stock_lookup` |
| `schema` | no | Valid JSON Schema; engages `structured`/`lean`/`full` |
| `memory_setup` | no | List of facts (`type`, `name`, `description`, `body`) seeded before the run; engages `memory`/`lean`/`full` |

Scoring kinds:

- **`json_equal`** — `expected` is a mapping. The output is parsed with
  `extract_json` and must compare exactly equal. Unparseable output fails.
- **`contains`** — `expected` is a non-empty list of strings; every one must
  appear in the output, case-insensitively and on a word boundary (no word
  character on either side of the match). So `100` does not match inside
  `1000`, and `atlas` does not match inside `atlassian`. Comma-grouped digits
  do not match either, so `200` does not match inside `1,200`. Use this when
  only a fact matters, not the phrasing.
- **`tool_trace`** — `expected` is a non-empty list of tool names that must
  appear as an **ordered subsequence** of the actual tool calls. Extra calls in
  between are allowed; wrong order is not. This scores the transcript, so do
  **not** combine it with a `schema`: the `structured` config has no transcript
  to score and reports such a task as an explicit failure.

The builtin tools read `assets/evals/fixtures/catalog.json` (`widget`,
`gadget`, `doohickey`, `sprocket`, each with `price` and `stock`), so tool-use
tasks stay deterministic on the harness side.

`runtime-py/tests/test_conformance.py` enforces the contract above and requires
at least 19 tasks with all three families present, at least 2 each. Run it after
adding a task:

```bash
.venv/bin/python -m pytest runtime-py/tests/test_conformance.py
```

Back to the [README](../README.md).
