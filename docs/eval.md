# Eval

← [README](../README.md) · [Install](install.md) · [Usage](usage.md) · [Memory](memory.md)

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
(on the current suite, `lean` does the same work for a third fewer tokens).

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
  you whether a gate actually fired on a task or just billed tokens.

Tokens are read from the endpoint's `usage` field. Servers that omit it report
`0`, which makes `score/1k tok` read `0.00` — check the column is non-zero
before drawing conclusions.

Scores move between runs unless the endpoint is deterministic (temperature 0,
fixed seed). Compare configs within one sweep, not across sweeps.

## Current results

Reference sweep per spec §7 — `qwen3:4b-instruct` (4B class, non-thinking)
served by Ollama, all six configs over the 15-task suite (5 tasks each of
structured-extraction, tool-use, memory-recall):

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 10/15 | 3468 | 2.88 |
| structured | 10/15 | 3545 | 2.82 |
| critique | 10/15 | 16034 | 0.62 |
| memory | 15/15 | 9233 | 1.62 |
| lean | 15/15 | 9500 | 1.58 |
| full | 15/15 | 14350 | 1.05 |

```
Explicit failures:
- critique/recall-cache-ttl: CritiqueExhausted: below threshold 7 after 3 rounds;
  last feedback: The answer provides a number (0) but it is not valid or accurate
  as a cache TTL in real-world systems. ...
```

The other 14 failures are plain wrong answers, not raised errors: `bare`,
`structured` and `critique` have no memory store, so all five memory-recall
tasks are unanswerable under them.

The score column is entirely decided by the memory-recall family. Broken out
by family, every config passes 10/10 on extraction and tool-use:

| config | extraction | tool-use | memory-recall |
|---|---|---|---|
| bare | 5/5 · 351 tok | 5/5 · 2415 tok | 0/5 · 702 tok |
| structured | 5/5 · 615 tok | 5/5 · 2403 tok | 0/5 · 527 tok |
| critique | 5/5 · 2037 tok | 5/5 · 4030 tok | 0/5 · 9967 tok |
| memory | 5/5 · 351 tok | 5/5 · 2408 tok | 5/5 · 6474 tok |
| lean | 5/5 · 615 tok | 5/5 · 2421 tok | 5/5 · 6464 tok |
| full | 5/5 · 2272 tok | 5/5 · 4042 tok | 5/5 · 8036 tok |

Against spec §7, without spin:

- **"Full toolkit scores measurably higher than bare": met.** `full` 15/15 vs
  `bare` 10/15. But read the family table before celebrating: all five gained
  tasks are memory-recall, and `memory` alone gets the same 15/15 for 36% fewer
  tokens. On this suite the uplift *is* the memory primitive; nothing else
  moves a task.
- **Does `lean` beat `bare` on score? Yes — 15/15 vs 10/15, +5 tasks.**
- **Is `lean`'s score/1k near `bare`'s? No — 1.58 vs 2.88, about 55% of it.**
  The §7 "on par" bar is not met, but the gap is an artifact of how cheaply
  `bare` fails: it disposes of the five recall tasks for 702 tokens total and
  banks zero passes, while `lean` spends 6464 tokens injecting the store index
  and wins all five. On the 10 tasks both configs pass, the efficiency gap
  nearly closes (`bare` 3.62, `lean` 3.29) — and that residual 9% is the
  schema instruction, not memory: `memory` matches `bare` at 3.62 to two decimals.
  A config that skips work it would fail will always look efficient.
- **`full − lean` — critique's marginal cost and uplift: +4850 tokens (+51%)
  for +0 passes.** Same 15/15, score/1k falls 1.58 → 1.05. On this model and
  suite the critique gate buys nothing it can be measured buying, so `lean` is
  what you would ship; `full` is worth its bill only if your tasks have failure
  modes this suite does not contain.
- **Did the retuned rubric stop `critique` being net-negative? On score, yes.**
  In the pre-cycle baseline below, adding the critic *destroyed* a pass —
  `full` 4/6 sat under `memory` 5/6, and its `CritiqueExhausted` failures were
  the critic rejecting correct answers over formatting. Now `full` 15/15
  matches `memory` and `lean`, and the single `CritiqueExhausted` left is the
  critic correctly refusing a fabricated answer (the `critique` config has no
  memory, so the model invented a TTL of `0`). The rubric now fails content,
  not format. On efficiency it is still net-negative: 0.62 standalone, and
  −34% score/1k when stacked into `full`.
- **Stretch ("competitive with a bare model one size class up"): not
  re-measured.** The 7B comparison below is on the retired 6-task suite and is
  not comparable to these numbers.

Pre-cycle baseline — the same model on the **old 6-task suite with the old
rubric**, kept for the before/after:

| config | score | score/1k tok |
|---|---|---|
| bare | 3/6 | 2.27 |
| structured | 3/6 | 2.09 |
| critique | 3/6 | 0.47 |
| memory | 5/6 | 1.43 |
| full | 4/6 | 0.38 |

Do not read the two tables as a controlled comparison. Three things changed
between them: the suite grew 6 → 15 tasks with a different family balance, the
`task-completion` rubric was retuned to judge content rather than format, and
`lean` did not exist. The `critique` and `full` rows in particular are **not**
apples-to-apples — their improvement is partly a better critic and partly an
easier-to-satisfy scoring path. The `bare` row is the honest anchor: it moved
3/6 → 10/15 (50% → 67%) purely because the expanded suite added families this
model handles well.

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

Caveats: single sweeps against a non-deterministic endpoint. Run-to-run
variance is roughly ±1 task per config, which on the 15-task suite is about
±7% — narrower than the retired 6-task suite's ±17%, but still wide enough
that a 1-task difference between configs is noise. The differences load-bearing
above are 5 tasks (memory families) and 0 tasks (`full − lean`), both well
clear of that band; the token columns are not subject to it in the same way.

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
  `1000`, and `atlas` does not match inside `atlassian`. Use this when only a
  fact matters, not the phrasing.
- **`tool_trace`** — `expected` is a non-empty list of tool names that must
  appear as an **ordered subsequence** of the actual tool calls. Extra calls in
  between are allowed; wrong order is not. This scores the transcript, so do
  **not** combine it with a `schema`: the `structured` config has no transcript
  to score and reports such a task as an explicit failure.

The builtin tools read `assets/evals/fixtures/catalog.json` (`widget`, `gadget`, `doohickey`, `sprocket`,
each with `price` and `stock`), so tool-use tasks stay deterministic on the
harness side.

`runtime-py/tests/test_conformance.py` enforces the contract above and requires
at least 19 tasks with all three families present, at least 2 each. Run it after
adding a task:

```bash
.venv/bin/python -m pytest runtime-py/tests/test_conformance.py
```

Back to the [README](../README.md).
