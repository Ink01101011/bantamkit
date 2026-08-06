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
| `--config` | no | One of `bare`, `structured`, `critique`, `memory`, `full`. Repeatable. Default: all five |

Narrow it while iterating:

```bash
.venv/bin/python -m bantamkit.evalrun \
  --base-url http://localhost:11434/v1 --model qwen2.5:7b-instruct \
  --config bare --config full
```

Every task runs against a live model, so a full sweep is 5 configs × 6 tasks =
30 runs. Start with `--config bare --config full`.

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

- **Budget parity.** `SchemaGate` allows 3 attempts — deliberately the same
  budget `structured()` gets. Neither config gets more shots at schema
  compliance than the other, so the difference between them measures the
  components, not the retry allowance. Exhausting the budget raises
  `StructuredOutputError`, which lands under explicit failures rather than
  crashing the sweep.
- **Gate ordering.** `SchemaGate` is registered *ahead* of `CritiqueGate`, so
  malformed output is repaired before a critique call is spent on it. Reviewing
  the quality of unparseable JSON would burn tokens to reach the same verdict.

So `full` is the headline number: it is the only config where all three
primitives are stacked on the same run, which is also what you would ship.

Memory stores are seeded fresh per task per config in a temp directory, so runs
do not contaminate each other.

## Reading the report

```
| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 3/6 | 4821 | 0.62 |
| full | 5/6 | 9137 | 0.55 |

Explicit failures:
- full/extract-order: StructuredOutputError: no valid output after 3 attempts; last error: ...
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

Tokens are read from the endpoint's `usage` field. Servers that omit it report
`0`, which makes `score/1k tok` read `0.00` — check the column is non-zero
before drawing conclusions.

Scores move between runs unless the endpoint is deterministic (temperature 0,
fixed seed). Compare configs within one sweep, not across sweeps.

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
| `schema` | no | Valid JSON Schema; engages `structured`/`full` |
| `memory_setup` | no | List of facts (`type`, `name`, `description`, `body`) seeded before the run; engages `memory`/`full` |

Scoring kinds:

- **`json_equal`** — `expected` is a mapping. The output is parsed with
  `extract_json` and must compare exactly equal. Unparseable output fails.
- **`contains`** — `expected` is a non-empty list of strings; every one must
  appear in the output, case-insensitively. Use this when only a fact matters,
  not the phrasing.
- **`tool_trace`** — `expected` is a non-empty list of tool names that must
  appear as an **ordered subsequence** of the actual tool calls. Extra calls in
  between are allowed; wrong order is not. This scores the transcript, so do
  **not** combine it with a `schema`: the `structured` config has no transcript
  to score and reports such a task as an explicit failure.

The builtin tools read `assets/evals/fixtures/catalog.json` (`widget`, `gadget`,
each with `price` and `stock`), so tool-use tasks stay deterministic on the
harness side.

`runtime-py/tests/test_conformance.py` enforces the contract above and requires
at least 6 tasks with all three families present, at least 2 each. Run it after
adding a task:

```bash
.venv/bin/python -m pytest runtime-py/tests/test_conformance.py
```

Back to the [README](../README.md).
