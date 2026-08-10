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
| `--config` | no | One of `bare`, `structured`, `critique`, `grounded`, `graph`, `memory`, `lean`, `full` (plus calibration-only `graph-annotate`, `graph-cache`, `budgeted` = `full` + `TokenBudget`). Repeatable. Default: the eight matrix configs |
| `--timeout` | no | Per-request timeout in seconds. Default: 60 |
| `--repeats` | no | Runs per (config, task) pair. Default: 1. Repeats narrow the run-to-run noise band and are how candidate tasks are calibrated |
| `--tasks` | no | Directory of task YAML files to run instead of the builtin suite |
| `--json` | no | Append one JSON line per finished run (all `TaskResult` fields) to this file as the sweep progresses — a killed sweep keeps its partial results |
| `--transcripts` | no | Dump one `<config>--<task>--r<repeat>.json` per finished run into this directory (created if missing): the run's verdict, final output and full message list. This is how a failure gets diagnosed after the sweep instead of by re-running it |
| `--eval-profile` | no | Run every component under a named profile from `assets/profiles/` (e.g. `patient`) instead of `default`. Calibration tool — headline results always use `default` |

Narrow it while iterating:

```bash
.venv/bin/python -m bantamkit.evalrun \
  --base-url http://localhost:11434/v1 --model qwen2.5:7b-instruct \
  --config bare --config full
```

Every task runs against a live model, so a full sweep is 8 configs × all tasks
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
| `grounded` | `GroundedCritiqueGate` only — the critic sees tool call/observation pairs; isolates the evidence effect vs `critique` |
| `graph` | `FileAccessGraph` on tasks with workspace file tools — repeat-read annotation, verify-on-repeat cache, `file_graph` query tool |
| `memory` | Tasks with `memory_setup` get a seeded `Memory` store attached |
| `lean` | memory + schema enforcement inside the agent loop — `full` without the critique gate |
| `full` | memory + schema + `GroundedCritiqueGate` (evidence-seeing critic), all inside the agent loop |

Since v0.9.0, `memory`, `lean` and `full` also attach `JsonAnswerGate` on
tasks scored `json_equal`: a fail-open post-hook that asks for exactly one
restatement when the final answer contains no extractable JSON at all
(the measured 7b failure mechanism — right fact, fluent prose, no JSON).
`bare` deliberately does not get it and stays the floor. This changes
what those three config names measure; sweeps before and after v0.9.0 are
not directly comparable on those cells.

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
- **Gate ordering.** `SchemaGate` is registered *ahead* of the critique gate
  (`GroundedCritiqueGate` in `full`), so
  malformed output is repaired before a critique call is spent on it. Reviewing
  the quality of unparseable JSON would burn tokens to reach the same verdict.

So `full` stacks all three primitives on one run — see
[Current results](#current-results) for whether that stack earns its bill
(on the current suite, `full` is the only 66/66 config on the 4b
reference — [Cross-model results](#cross-model-results) for where that
does and does not transfer; `lean` reaches 57/66 for 50% fewer tokens).

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
  budget), `turns-exhausted` (the agent loop hit `max_turns` without producing
  a final answer — agent behaviour, not infrastructure), `config-error`,
  `transport-error`. Content-wrong and format-broken
  have opposite remedies, so they are never lumped together. `turns-exhausted`
  was split out of `transport-error` after v0.8.0; sweeps recorded before that
  file turn exhaustion under `transport-error`, and their JSONLs are not
  rewritten.
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

### Seeds

Each run sends a deterministic sampling seed, `run_seed(model, task, repeat)` —
a truncated SHA-256 of those three, so it is stable across processes and
machines — and records it as `seed` in the `--json` row and the transcript.

- **What is pinned:** the seed, per (model, task, repeat). **Config is
  deliberately excluded**, so `bare` and `graph` sample identically on the same
  (task, repeat) and an off-family no-op check is exact-equality-falsifiable
  again rather than a similarity argument.
- **What is not:** temperature. Pinning it would change what the suite
  measures — the harness is evaluated at the server's own sampling settings.
- **The honesty bound:** llama.cpp and Ollama under concurrent load are not
  bit-deterministic even with a seed. The invariant is *replayable modulo
  server nondeterminism*: hold exact equality where it holds, and investigate a
  divergence rather than waving it through as noise.
- `seed` is `null` for clients that do not accept one, and absent from JSONLs
  written before v0.8.1. A seed the server ignored is not recorded as applied.

## Current results

Reference sweep on the 22-task suite — `qwen3:4b-instruct` (4B class,
non-thinking) served by Ollama, all eight configs at `--repeats 3`:
8 × 22 × 3 = 528 runs. The suite is 5 structured-extraction, 6 tool-use,
9 memory-recall and 2 file-nav tasks. This sweep follows the file-access
graph cycle: the new `file-nav` family (workspace file tools, pointer-chain
prompts) and the `graph` config (`bare` + `FileAccessGraph`) join the
matrix. Every per-run row is in
`docs/eval-data/2026-08-09-filegraph-sweep.jsonl`; the 120-run calibration
that selected the family sits beside it
(`2026-08-09-filegraph-calibration.jsonl` and `-tuned.jsonl`).

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 30/66 | 18380 | 1.63 |
| structured | 30/66 | 19601 | 1.53 |
| critique | 36/66 | 47366 | 0.76 |
| grounded | 38/66 | 96698 | 0.39 |
| graph | 36/66 | 23200 | 1.55 |
| memory | 57/66 | 54254 | 1.05 |
| lean | 57/66 | 54543 | 1.05 |
| full | 66/66 | 109243 | 0.60 |

Per family (score · tokens):

| config | file-nav | memory-recall | structured-extraction | tool-use |
|---|---|---|---|---|
| bare | 0/6 · 6928 tok | 0/27 · 1544 tok | 15/15 · 1059 tok | 15/18 · 8849 tok |
| structured | 0/6 · 7408 tok | 0/27 · 1523 tok | 15/15 · 1830 tok | 15/18 · 8840 tok |
| critique | 6/6 · 15396 tok | 0/27 · 11228 tok | 15/15 · 6111 tok | 15/18 · 14631 tok |
| grounded | 5/6 · 20078 tok | 0/27 · 43511 tok | 15/15 · 10501 tok | 18/18 · 22608 tok |
| graph | 6/6 · 11776 tok | 0/27 · 1521 tok | 15/15 · 1065 tok | 15/18 · 8838 tok |
| memory | 0/6 · 8338 tok | 27/27 · 36026 tok | 15/15 · 1053 tok | 15/18 · 8837 tok |
| lean | 0/6 · 7868 tok | 27/27 · 36033 tok | 15/15 · 1835 tok | 15/18 · 8807 tok |
| full | 6/6 · 22839 tok | 27/27 · 52784 tok | 15/15 · 11150 tok | 18/18 · 22470 tok |

```
Failure outcomes:
- bare: wrong-answer ×30, malformed-output ×6
- structured: wrong-answer ×31, malformed-output ×5
- critique: wrong-answer ×30
- grounded: wrong-answer ×19, critique-exhausted ×8, malformed-output ×1
- graph: wrong-answer ×30
- memory: malformed-output ×6, wrong-answer ×3
- lean: malformed-output ×5, wrong-answer ×4
- full: none
```

Discriminating tasks: 12/22

| task | bare | structured | critique | grounded | graph | memory | lean | full |
|---|---|---|---|---|---|---|---|---|
| nav-prod-port | 0/3 | 0/3 | 3/3 | 2/3 | 3/3 | 0/3 | 0/3 | 3/3 |
| nav-release-bundle | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 | 0/3 | 0/3 | 3/3 |
| recall-audit-retention | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-cache-ttl | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-db-port | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-deploy | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-env-endpoint | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall-rotation | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-org-quota | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-owner | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| shop-basket-total | 0/3 | 0/3 | 0/3 | 3/3 | 0/3 | 0/3 | 0/3 | 3/3 |

What the sweep says:

- **The promoted cells hold, and the no-op check passes exactly.** Both
  file-nav tasks stay `bare` 0/3 vs `graph` 3/3, reproducing the
  calibration. Off-family, `graph` matches `bare` on every single cell —
  identical scores everywhere, 11424 vs 11452 total tokens (0.2%) — the
  spec's falsifiable prediction that the component is a true no-op where
  no task gives it file tools.
- **The honest attribution: file-nav's rescue channel is not unique to
  the graph.** `bare` fails file-nav as `malformed-output` — after
  exploring, the model narrates instead of emitting the exact JSON.
  Everything that adds a revision loop fixes that: blind `critique` 6/6,
  `grounded` 5/6, `full` 6/6 — and `graph` 6/6. What distinguishes
  `graph` is cost: 11776 file-nav tokens vs `critique`'s 15396,
  `grounded`'s 20078 and `full`'s 22839, with no gate calls at all. The
  calibration ablations sharpen this: annotate-only and cache+annotate
  (query off) fail
  exactly like `bare`, so within the graph the rescue is the query
  mechanism (the `file_graph` tool + its system snippet) — and the data
  cannot separate "the ledger helped" from "any task-relevant system
  snippet would have re-anchored the JSON format." Recorded as measured,
  not assumed.
- **`memory` and `lean` are no longer near-perfect on the grown suite:
  57/66.** Their six new misses are all file-nav (no store to attach, so
  they run as `bare` there and inherit its malformed-output failures) plus
  the standing shop-basket-total arithmetic. **`full` is the only perfect
  config again: 66/66** — the grounded gate covers file-nav too, at 0.60/1k.
- **Blind `critique` posts its first standalone uplift on this suite:
  30 → 36.** Every one of the six is file-nav format repair (7 revision
  rounds total). The gate that measured as pure overhead for five cycles
  finally has a failure mode it can fix — worth knowing, but `graph` buys
  the same six passes at half `critique`'s total bill (23200 vs 47366).
- **The dropped candidate is the cycle's sharpest negative.**
  `nav-retry-budget` plants an obsolete config next to the live one;
  calibration measured `bare` 3/3 but `graph` 0/3 — ledger-guided runs
  consistently surfaced the stale value. A file-access ledger is not a
  relevance oracle: it tells the model what it read, not which read to
  trust. Dropped per the bar. The other two drops saturated after the
  tuning pass — nav-owner-team and nav-quota-endpoint both measured
  bare 3/3 vs graph 3/3, with graph *costing more* tokens (3918 vs 2631
  and 6072 vs 4356), clearing neither bar. All numbers in the tuned
  calibration JSONL.
- **Repeat variance: one split cell in 176** (nav-prod-port `grounded`
  2/3). `schema_retries` is 0 in all 528 runs — the
  structured-instruction-tax negative stands through its sixth sweep.
- **Ship guidance updates**: `lean` remains the efficiency pick for
  memory-driven agents (57/66 · 1.05/1k), `graph` is the cheap attach for
  file-reading agents (its whole uplift costs +26% tokens over `bare`),
  and `full` is what perfection costs: 0.60/1k, double `lean`'s bill.

### Previous sweep (2026-08-09, seven configs, 20 tasks)

The sweep below predates the file-nav family and the `graph` config: 20
tasks, seven configs, 420 runs. Totals are /60 and are not comparable to
the /66 table above. Kept because it is the recall-conversion reference
measurement (json_equal recall scoring landed there).

Reference sweep on the 20-task suite — `qwen3:4b-instruct` (4B class,
non-thinking) served by Ollama, all seven configs at `--repeats 3`:
7 × 20 × 3 = 420 runs. The suite is 5 structured-extraction, 6 tool-use and
9 memory-recall tasks. This sweep follows the recall scoring conversion: all
nine memory-recall tasks now demand an exact JSON answer and score
`json_equal` instead of `contains`, so an agent that recalls correctly but
dumps the whole store no longer passes. Every per-run row is in
`docs/eval-data/2026-08-09-recall-json-sweep.jsonl`; the 81-run calibration
that gated the conversion sits beside it
(`2026-08-09-recall-json-calibration.jsonl`).

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 30/60 | 11434 | 2.62 |
| structured | 30/60 | 12192 | 2.46 |
| critique | 30/60 | 32068 | 0.94 |
| grounded | 33/60 | 75157 | 0.44 |
| memory | 57/60 | 46767 | 1.22 |
| lean | 57/60 | 46668 | 1.22 |
| full | 60/60 | 86500 | 0.69 |

Per family (score · tokens):

| config | memory-recall | structured-extraction | tool-use |
|---|---|---|---|
| bare | 0/27 · 1543 tok | 15/15 · 1053 tok | 15/18 · 8838 tok |
| structured | 0/27 · 1522 tok | 15/15 · 1840 tok | 15/18 · 8830 tok |
| critique | 0/27 · 11293 tok | 15/15 · 6111 tok | 15/18 · 14664 tok |
| grounded | 0/27 · 42186 tok | 15/15 · 10359 tok | 18/18 · 22612 tok |
| memory | 27/27 · 36867 tok | 15/15 · 1065 tok | 15/18 · 8835 tok |
| lean | 27/27 · 36004 tok | 15/15 · 1840 tok | 15/18 · 8824 tok |
| full | 27/27 · 52850 tok | 15/15 · 11133 tok | 18/18 · 22517 tok |

```
Failure outcomes:
- bare: wrong-answer ×30
- structured: wrong-answer ×30
- critique: wrong-answer ×30
- grounded: wrong-answer ×19, critique-exhausted ×8
- memory: wrong-answer ×3
- lean: wrong-answer ×3
- full: none
```

Discriminating tasks: 10/20

| task | bare | structured | critique | grounded | memory | lean | full |
|---|---|---|---|---|---|---|---|
| recall-audit-retention | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-cache-ttl | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-db-port | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-deploy | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-env-endpoint | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall-rotation | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-org-quota | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-owner | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| shop-basket-total | 0/3 | 0/3 | 0/3 | 3/3 | 0/3 | 0/3 | 3/3 |

What the sweep says:

- **The conversion held its falsifiable prediction.** Every `memory`,
  `lean` and `full` recall cell stayed 3/3 under the stricter scoring, and
  every storeless config stayed 0/27 — the same separation as before, now
  proven against exact-answer extraction instead of substring luck. The
  calibration that gated promotion (bare 0/27, memory 27/27, lean 27/27,
  all nine candidates) predicted exactly this.
- **Zero split cells.** All 140 (task, config) cells are 0/3 or 3/3 — the
  first sweep with no repeat variance at all (the previous sweep had 3
  split cells). The stricter scoring added no noise, and `lean`'s
  shop-stock-total flake did not recur this sweep, so `memory` and `lean`
  tie at 57/60 · 1.22/1k.
- **`contains` was hiding a lucky pass and a chatter tax.** Blind
  `critique` loses its 1/27 recall pass (recall-db-port 1/3 — a verbose
  near-miss that substring matching rewarded); `json_equal` kills it, and
  30/60 puts `critique` exactly at `bare`'s score. Meanwhile the
  answer-with-only-this-JSON instruction collapses storeless recall
  chatter: `bare`'s recall spend drops 4239 → 1543 tokens and blind
  `critique`'s 53973 → 11293, which is why the storeless rows' totals look
  cheaper than the previous sweep's.
- **`grounded` exhausts honestly rather than passing falsely.** 8 of its
  27 recall failures end `critique-exhausted` (up from 4) — with an exact
  JSON object demanded, the grounded critic refuses to sign off fabricated
  facts more often. It still scores 0/27 there: a critic cannot conjure
  facts, only reject them. Its tool-use 18/18 and shop-basket-total 3/3
  (one revision round per run) are unchanged.
- **`full` stays 60/60 — now measured inside one sweep.** No provenance
  footnote needed anymore: 86500 tokens, 0.69/1k, three critique rounds
  total (the three shop-basket-total repairs). `lean` delivers 57/60 for
  46% fewer tokens and remains the efficiency ship config.
- **Standing negatives stand.** `schema_retries` is 0 in all 420 runs
  (structured remains pure instruction tax on this model), and
  shop-basket-total is still rescued only by evidence-sighted critique —
  `memory`/`lean`'s three failures are exactly its arithmetic.

### Previous sweep (2026-08-09, seven configs, contains-scored recall)

The sweep below ran the same 20-task suite and config list but predates the
recall scoring conversion: its nine memory-recall tasks scored `contains`,
so recall rows — scores and tokens — are not comparable to the table above
(storeless configs wrote longer prose answers, and substring matching could
reward near-misses). Kept because its narrative documents the
grounded-critique measurements that motivated v0.5.

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 30/60 | 14125 | 2.12 |
| structured | 30/60 | 14193 | 2.11 |
| critique | 31/60 | 74724 | 0.41 |
| grounded | 33/60 | 80494 | 0.41 |
| memory | 57/60 | 45447 | 1.25 |
| lean | 56/60 | 46344 | 1.21 |
| full | 60/60* | 86162 | 0.70 |

Per family (score · tokens):

| config | memory-recall | structured-extraction | tool-use |
|---|---|---|---|
| bare | 0/27 · 4239 tok | 15/15 · 1059 tok | 15/18 · 8827 tok |
| structured | 0/27 · 3527 tok | 15/15 · 1835 tok | 15/18 · 8831 tok |
| critique | 1/27 · 53973 tok | 15/15 · 6111 tok | 15/18 · 14640 tok |
| grounded | 0/27 · 46303 tok | 15/15 · 10460 tok | 18/18 · 23731 tok |
| memory | 27/27 · 35557 tok | 15/15 · 1059 tok | 15/18 · 8831 tok |
| lean | 27/27 · 35690 tok | 15/15 · 1830 tok | 14/18 · 8824 tok |
| full | 27/27 · 52544 tok* | 15/15 · 11155 tok* | 18/18 · 22463 tok* |

```
Failure outcomes:
- bare: wrong-answer ×30
- structured: wrong-answer ×30
- critique: critique-exhausted ×8, wrong-answer ×21
- grounded: critique-exhausted ×4, wrong-answer ×23
- memory: wrong-answer ×3
- lean: wrong-answer ×4
- full: none*
```

\* `full` rows re-measured 2026-08-09 after v0.5 swapped its blind
`CritiqueGate` for `GroundedCritiqueGate` (60 runs,
`docs/eval-data/2026-08-09-full-grounded-rerun.jsonl`); every other row is
the original 420-run sweep, which the swap does not touch.

Discriminating tasks: 11/20

| task | bare | structured | critique | grounded | memory | lean | full |
|---|---|---|---|---|---|---|---|
| recall-audit-retention | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-cache-ttl | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-db-port | 0/3 | 0/3 | 1/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-deploy | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3* |
| recall-env-endpoint | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-oncall-rotation | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-org-quota | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| recall-owner | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| shop-basket-total | 0/3 | 0/3 | 0/3 | 3/3 | 0/3 | 0/3 | 3/3* |
| shop-stock-total | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 |

What the sweep says:

- **The headline: `shop-basket-total` — `grounded` 3/3, every other config
  0/3, including `full`.** The model does its price lookups correctly and
  then botches the three-item arithmetic; a critic that can see
  `price_lookup({"item": "widget"}) -> widget price: 25` recomputes the
  total, rejects the wrong one, and the model repairs it in one round
  (rounds per run: 1, 2, 1). The blind critic in `critique` and `full`
  (the blind-critic `full` of that sweep — since swapped, see below)
  accepted the wrong total in all six of their runs. That makes
  shop-basket-total the suite's first non-memory discriminator — **two
  families now discriminate** (9 memory-recall, 2 tool-use), meeting the
  suite-hardening criterion (≥2 families) that the previous cycle conceded.
- **`critique` vs `grounded` isolates the evidence effect.** Same gate
  position, same threshold, same rounds budget; the only difference is
  whether the critic sees tool evidence. Tool-use: 15/18 vs 18/18.
  Score/1k ties at 0.41 — the evidence does not cost efficiency, it
  relocates the same critique spend onto failures it can actually fix.
- **What `grounded` is not: a general ship config.** On memory-recall
  without a store it scores 0/27 like every other storeless config — a
  critic cannot conjure facts, though it exhausts honestly (4
  `critique-exhausted`, 3 of them refusing fabricated retention policies).
  On saturated extraction its reasoning-field scoring costs more than the
  blind critic's (10460 vs 6111 tokens for the same 15/15). Attach it when
  answers derive from tool output; attach `Memory` when answers derive
  from the past.
- **`full` adopted the grounded gate in v0.5 and re-measured 60/60 — the
  suite's first perfect config.** The blind-critic `full` of the original
  sweep failed shop-basket-total 0/3 and flaked recall-deploy 2/3; the
  grounded `full` passes everything, spending 3 revision rounds and +27%
  tokens over its blind self (86162 vs 68070). Score/1k is 0.70 vs `lean`'s
  1.21 — `lean` remains the efficiency ship config; grounded `full` is what
  you run when tool-derived correctness is worth the bill.
- **The gates fire on this suite now.** Previous sweep: `critique_rounds
  == 0` in every `full` run. This sweep: 23 revision rounds under
  `critique`, 25 under `grounded`, 2 under `full`, and 13 runs ending
  `critique-exhausted`. `schema_retries` is still 0 in all 420 runs — the
  structured-instruction-tax negative stands unchanged.
- **The dropped candidate is a recorded negative, not a silent one.**
  `shop-restock` needs a two-step derivation (20 − stock per item, then a
  comparison). After a single rubric tune (a schema-forced `reasoning`
  field making the critic derive the answer from evidence before scoring),
  the grounded critic flags the wrong answer in 3/3 calibration runs — but
  the model cannot repair it even with pointed feedback. Rescue requires a
  better base model, not a better critic; dropped per the
  tune-once-then-drop rule. Evidence in both calibration JSONLs.
- **Repeat variance exists this sweep but stays off the headline.** 3 of
  140 (task, config) cells split (recall-db-port `critique` 1/3,
  recall-deploy `full` 2/3, shop-stock-total `lean` 2/3); every
  shop-basket-total and every `memory`/`lean` recall cell is 0/3 or 3/3.
- **The ship recommendation is unchanged**: `memory` 57/60 at 1.25/1k
  (`lean` 56/60 at 1.21 — its one extra failure is the shop-stock-total
  flake). `grounded` joins as the targeted gate for tool-heavy agents, not
  as part of the default stack.

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

### Previous sweep (2026-08-07, six configs, 19 tasks)

The sweep below predates `GroundedCritiqueGate`, the `grounded` config and
the promotion of `shop-basket-total`; its numbers are not comparable to the
table above (different suite size and config list). Kept because the
narrative documents the two measured negatives that motivated the
grounded-critique cycle.

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

## Cross-model results

The reference sweep above is one model. This section re-runs the **frozen
v0.7.0 suite** — same 22 tasks, same rubrics, same prompts, same eight
configs, 3 repeats, 528 runs per model — on three more models, and re-scopes
every Recommended-defaults claim to the models it actually holds on
(spec: `docs/superpowers/specs/2026-08-09-cross-model-sweep-design.md`).
The suite was frozen before measuring: a model that fails a task or rubric
is a data point, not a bug, and nothing was tuned per model.

| model | class | evidence |
|---|---|---|
| `llama3.2:3b` | cross-family, small end | `docs/eval-data/2026-08-09-crossmodel-llama32-3b.jsonl` |
| `qwen3:4b-instruct` | reference (reused, not re-run) | `docs/eval-data/2026-08-09-filegraph-sweep.jsonl` |
| `qwen2.5:7b-instruct` | size up, near-family | `docs/eval-data/2026-08-09-crossmodel-qwen25-7b.jsonl` |
| `qwen2.5:14b-instruct` | ceiling reference, outside the 1–8B target band | `docs/eval-data/2026-08-09-crossmodel-qwen25-14b.jsonl` |

### Per-model summaries

`llama3.2:3b` — everything is hard for this model, and the critique-family
configs are actively harmful:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 14/66 | 24145 | 0.58 |
| structured | 18/66 | 37080 | 0.49 |
| critique | 17/66 | 83382 | 0.20 |
| grounded | 13/66 | 168109 | 0.08 |
| graph | 19/66 | 40360 | 0.47 |
| memory | 24/66 | 52949 | 0.45 |
| lean | 24/66 | 68791 | 0.35 |
| full | 15/66 | 214698 | 0.07 |

`memory` is still the best config (24/66), but recall with a store reaches
only 6/27. `full` collapses: 214,698 tokens — 8.9× `bare`'s bill — for one
more pass than `bare`, with `schema-exhausted` ×22 (the critic's verdict
contract failing, not the tasks). `grounded` lands *below* `bare` (13 vs
14). See P2/P3 in Measured problems.

`qwen2.5:7b-instruct` — competent baseline, but the answer-format contract
starts costing real passes:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 35/66 | 34059 | 1.03 |
| structured | 33/66 | 25980 | 1.27 |
| critique | 36/66 | 68272 | 0.53 |
| grounded | 24/66 | 93854 | 0.26 |
| graph | 31/66 | 37360 | 0.83 |
| memory | 44/66 | 139385 | 0.32 |
| lean | 44/66 | 141207 | 0.31 |
| full | 36/66 | 205402 | 0.18 |

`memory`/`lean` lead at 44/66, but recall with a store is only 9–12/27,
and `memory`/`lean`/`full` each lose 13–16 runs to `malformed-output` —
the "answer with ONLY this JSON" convention that 4b obeys is a measurable
tax on 7b (P4). `grounded` is strongly net-negative (24 vs bare 35;
`schema-exhausted` ×10). `structured` is the efficiency winner (1.27/1k).

`qwen2.5:14b-instruct` — the ceiling reference mostly saturates the
non-recall families:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 34/66 | 32426 | 1.05 |
| structured | 36/66 | 25958 | 1.39 |
| critique | 34/66 | 69501 | 0.49 |
| grounded | 34/66 | 93029 | 0.37 |
| graph | 36/66 | 25443 | 1.42 |
| memory | 59/66 | 73130 | 0.81 |
| lean | 55/66 | 79353 | 0.69 |
| full | 59/66 | 129772 | 0.46 |

`memory` and `full` tie at 59/66 — `full`'s critique layer buys nothing
here for +77% tokens over `memory`. Recall with a store reaches 23/27.
Both critique configs price in at 2–2.9× `bare` for exactly `bare`'s
score. `graph` and `structured` are the efficiency winners (~1.4/1k).

### The recall story across models

The project's core claim — recall goes ~0/27 without a store to ~27/27
with one — turns out to **vary sharply by model** rather than transfer
flat (and not monotonically with size — 7b lands below the smaller 4b):

| | 3b | 4b (ref) | 7b | 14b |
|---|---|---|---|---|
| memory-recall, storeless (`bare`) | 0/27 | 0/27 | 0/27 | 0/27 |
| memory-recall, with store (`memory`) | 6/27 | 27/27 | 9/27 | 23/27 |

The floor is universal (no model passes recall without a store — the tasks
measure what they claim). The rescue is not: 3b retrieves but answers
wrong (P1), and 7b loses most of its gap to `malformed-output` on the
exact-JSON answer convention (P4), scoring *below* the smaller 4b. The
numbers say the store mechanism works everywhere and the surrounding
contract wording is what's 4b-calibrated.

### Claims-transfer table

Every README Recommended-defaults bullet, against every model. "Holds" =
the guidance as written is what you should do on that model.

| claim | 3b | 4b (ref) | 7b | 14b |
|---|---|---|---|---|
| Always attach `Memory` | **holds** — biggest mover, +10 (14→24), but recall only 6/27 | **holds** (+27, 30→57) | **holds** — biggest mover, +9 (35→44), recall 9/27 | **holds** (+25, 34→59, recall 23/27) |
| Attach `FileAccessGraph` for file work | **does not hold** — file-nav 1/6→2/6, nothing rescues it | **holds** (0/6→6/6, +26% tokens) | **does not hold** — bare already 5/6 (saturated) | **does not hold** — bare already 5/6 (saturated) |
| `structured()` is free when the model complies | **holds** — `schema_retries=0` | **holds** — `schema_retries=0` | **holds** — 0 retries, best score/1k (1.27) | **holds** — 0 retries, 2nd-best score/1k (1.39) |
| Skip the blind `CritiqueGate` | **holds** — +3 at 3.5× tokens | **holds** — +6 at 2.6× tokens | **holds** — +1 at 2.0× tokens | **holds** — ±0 at 2.1× tokens |
| `full` measures 66/66 | **does not hold** — 15/66 at 8.9× bare tokens | **holds** (66/66) | **does not hold** — 36/66 | **does not hold** — 59/66, ties `memory` at +77% tokens |
| Prefer `GroundedCritiqueGate` with tools | **does not hold** — 13/66 < bare 14/66 | **holds** — rescued shop-basket-total 0/3→3/3 | **does not hold** — 24/66 < bare 35/66 | **does not hold** — 34/66 = bare at 2.9× tokens |

Two claims survive all four models unqualified (`Memory` as the biggest
single mover; skip the blind critic — now *stronger* cross-model). One
survives as exactly-as-written on all four (`structured()`: zero schema
retries in 2,112 runs across four models). Three are 4b-scoped:
`FileAccessGraph`'s value window is the ~4B class (below it the model
can't use the ledger, above it the tasks saturate — spec prediction 3
confirmed for file-nav), and both critique-dependent claims (`full`,
grounded) are blocked cross-model by the verdict-contract failure (P2).

### Prediction scorecard (spec §2.3, written before measuring)

1. **Memory transfers** — *partially confirmed.* The mover claim holds on
   all four models; the ~27/27 magnitude claim is refuted (6/27 on 3b,
   9/27 on 7b, 23/27 on 14b). Re-scoped into problems P1 and P4, not into
   a smaller claim.
2. **Structured tax holds** — *confirmed, and on 3b too.*
   `schema_retries = 0` in all 2,112 runs; SchemaGate's retry loop has
   still never fired on any model.
3. **Saturation on the big end** — *confirmed for file-nav* (7b/14b pass
   5/6 under `bare`). shop-basket-total saturates on 7b (`bare` 3/3) but
   stays flaky on 14b (`bare` 1/3) with no config rescuing it there.
4. **Critique risk on the small end** — *confirmed, worse than predicted.*
   3b `full` is a score *collapse* (15/66 at 214k tokens), and `grounded`
   lands below `bare` on both 3b and 7b.
5. **Graph no-op check is structural** — *reframed.* Off-family, `graph`
   diverged from `bare` in 8/20 cells (3b), 3/20 (7b) and 4/20 (14b),
   with zero on 4b. This is **sampling variance, not leakage**: the
   harness pins no temperature or seed (verified — neither `client.py`
   nor `evalrun.py` sends either), and the off-family code path is
   provably identical (`FileAccessGraph` only attaches workspace tools
   when the task lists them; per-cell diffs go in both
   directions). The prediction's exact-equality framing over-assumed
   determinism; 4b's 0/20 was a peaked output distribution, i.e. luck.
   The honest form of the check is code-level wiring plus statistical
   similarity — until P9 (seed pinning) restores exact equality's teeth.

### Measured problems → attack plan

Frozen-suite rules mean none of this was patched mid-sweep. Each negative
becomes a problem with an owner-fix, ordered; the layer names refer to the
5-layer model (core / contract / transport / policy / composition) that
the next cycle makes physical:

- **P8 — no post-hoc transcripts.** `evalrun` discards transcripts, so
  failures like P1 can't be probed after the fact. Fix: `--transcripts
  DIR`. (Measurement. First, because every other diagnosis needs it.)
- **P7 — MaxTurnsExceeded counted as `transport-error`.** The 3b sweep's
  transport-error column mixes real timeouts with turn exhaustion.
  Deliberately left frozen mid-sweep for JSONL consistency; fix is a
  taxonomy split. (Measurement.)
- **P9 — no temperature/seed pinning.** Cause of the no-op check reframe
  above. Fix: deterministic seed = stable hash(model, task, repeat) —
  config deliberately excluded — passed as client options, recorded in
  the JSONL; all configs of a (task, repeat) share the seed, so
  `bare`-vs-`graph` exact equality becomes meaningful again. Limit: llama.cpp under concurrency is not bit-deterministic —
  "replayable modulo server nondeterminism". (Transport + Measurement.)
- **P2 — the critic's verdict contract is 4b-calibrated.** Verdict
  parsing (`reasoning`-first JSON) dies cross-model: `schema-exhausted`
  ×22/×17 on 3b `full`/`grounded`, ×15/×10 on 7b. Every critique-family
  negative above routes through this. Fix: tiered contract — decode-level
  constrained decoding where the server supports `format` (capability
  detection in transport), else prompt+parse, else repair-retry — instead
  of per-model prompt forks. (Contract + Transport; the headline fix
  candidate of the restructure cycle.) **Fixed in v0.9.0** — `structured()`
  sends `response_format: json_schema` when the server accepts it
  (detected by a cached 400-fallback, no probe request): `schema-exhausted`
  went ×17 → **0** on 3b `grounded` and ×10 → **0** on 7b, at −38% / −24%
  tokens and +1 / **+9** score (see the calibration table below).
- **P1 — 3b recalls but answers wrong.** Store content reaches the
  context; the answer still fails. Needs P8 transcripts to split
  retrieval failure from synthesis failure before choosing a fix.
  (Contract, probably.) **Diagnosed and reframed in v0.9.0** — the first
  `--transcripts` probe (27 seeded runs, 3b `memory` on the recall tasks,
  `2026-08-10-p1-probe-3b-memory.jsonl`) showed the hypothesis was wrong:
  18/27 failures never searched the store at all — `memory_recall`
  crashed on argument types (17× the model sent `k` as the JSON string
  `"10"`; 1× it dropped `query`); 6/27 emitted pseudo-tool-calls as
  prose; only 3/27 were genuine synthesis failures, and retrieval was
  first-hit perfect whenever a recall actually executed. The fix is
  Layer 1, not contract wording: `Agent` now coerces string-typed
  integer/number/boolean arguments against the tool's declared schema
  before dispatch (plus `Memory.save` normalizes model-invented
  snake_case names to the store's kebab contract). Bar: convertible
  argument crashes 17 → **0**; passes 0/27 → 5/27 on the probe cell.
  Residual, honestly: one uncoercible crash (`k: "staging-db-port"` —
  semantic garbage no coercion should guess at), `memory_save`
  signature misuse burning turns, the 6 prose pseudo-calls, and the 3
  synthesis failures — the cell's ceiling on this model is far below
  27/27 and says so here.
- **P4 — exact-JSON answer compliance tax on 7b.** `malformed-output`
  ×13–16 in `memory`/`lean`/`full`. Fix candidate: answer-side repair
  tier (same ladder as P2). (Contract.) **Diagnosed and fixed in
  v0.9.0** — the 7b probe (`2026-08-10-p4-probe-7b-memory.jsonl`)
  refined the mechanism: 7b does not write broken JSON, it *abandons*
  JSON — 11/16 failures had the correct fact in a fluent prose final
  answer with no `{` anywhere, after spurious `memory_save` narration
  displaced the one-turn-old "ONLY this JSON" instruction. Extractor
  leniency cannot help (there is nothing to extract). Fix:
  `JsonAnswerGate` — a fail-open post-hook that asks for exactly one
  restatement when the final answer has no extractable JSON, attached in
  `memory`/`lean`/`full` for `json_equal`-scored tasks (`bare` stays the
  floor). Bar: malformed finals 11 → **3**, passes 11/27 → **19/27** on
  the probe cell.
- **P6 — 3b file-nav dies on turn budget.** `max_turns=10` is itself a
  4b-calibrated constant. Fix: per-profile turn budgets. (Policy.)
  **Measured in v0.10.0 — hypothesis refuted.** Profiles are now
  selectable (`--eval-profile`, `patient` profile with `max_turns: 16`),
  and the measurement says more turns convert nothing: 3b `graph` under
  `patient` still loses two of three `nav-release-bundle` repeats to
  `turns-exhausted` (the third fails as wrong-answer — 0/3 pass), and
  7b recall under `patient` converts 3
  turn-exhaustions to 2 at the same 19/27 score for **+19% tokens**
  (171k vs 144k). The residue is the model *looping*, not budget
  starvation — the 4b-calibrated 10 was not the binding constraint.
  Attack plan for the residue: loop detection (repeated identical tool
  calls/answers), a future primitive; blind turn-budget raises are now
  measured waste.

  **Outcome (2026-08-10, LoopGuard cycle, v0.12.0):** the residue was
  attacked with transcript evidence first. A 12-run probe (3b `graph`
  nav + 7b `memory` recall, both under `patient`) showed looping is a
  *tool-observation* phenomenon: looping runs burn 6–16-call tails of
  byte-identical observations, every passing run's maximum
  observation-repeat streak is 2, prose repetition never occurs, and
  args-identity is blind to 7b's paraphrase churn. Critically, both 7b
  turn-exhausted runs already **held the correct answer** while
  looping. `LoopGuard` (Layer 1, `loopguard.py`) wraps tool handlers,
  hashes observations, and on a per-tool consecutive-identity streak
  of 3 prepends the `loop_note` contract template ("this exact result
  {count} times; it will not change…"); at 5 the harder `loop_warn`
  ("STOP calling tools…"). Injection-only — it never stops the loop.
  Prepended, not appended: head-keeping observation truncation would
  eat an appended note on exactly the oversized no-info tails it
  targets (review-caught). Calibration bars, seeded, probes as the
  before (`2026-08-10-lg-*.jsonl`):

  - **7b `memory-guarded`** (the two held-answer tasks ×3): **2/6 →
    4/6 at −37.7% tokens** (73,979 → 46,059). Both held-answer loops
    converted — `turns-exhausted` 22,947 → **pass** 8,211 and 22,700 →
    **pass** 9,515 — and the note demonstrably fired in both
    transcripts. Stable cells byte-identical. Honest negative: the
    cell that was already failing short (`wrong-answer` 15,195) fired
    through note and warn and still failed (`malformed-output`,
    15,196) — injection converts held-answer loops, not absent-answer
    ones.
  - **3b `graph-guarded`** (nav probe cells ×3): score unchanged 1/6 —
    the spec's hedge ("3b's flail may resist wording") measured true —
    but `turns-exhausted` 2 → 0 and tokens **−21.1%** (48,245 →
    38,074): injected runs stop looping and answer (wrongly) instead
    of burning to the turn cap.
  - **4b `memory-guarded`** (full suite ×3, no-regression):
    **byte-identical on all 66 rows** to the seeded 59/66 @ 55,525
    memory cell — the guard was silent everywhere, exactly as the
    probe predicted (4b max streak ≤ 2), and a fired injection would
    itself have been a finding.

  v1 limitations, documented and pinned by tests: observations from
  raising handlers and unknown tools cannot streak (the wrapper resets
  on a raise — no false "identical" claim the transcript contradicts);
  under `graph-guarded`, collapsed repeat reads embed the graph's
  `read #N` marker and so never streak — the guard fires via the other
  tools, and it hashes what the model sees (graph markers included).
  LoopGuard stays out of the headline configs pending a cross-model
  sweep.
- **P3 — no global token ceiling.** 3b `full`: 214,698 tokens for 15/66 —
  every gate has a local cap but composition multiplies them. Fix:
  `TokenBudget` primitive — soft degradation ladder + hard ceiling that
  still emits a scored best-effort answer. (Core mechanics + Policy
  numbers; attack after P2/P4 so the remaining real blowup is measured,
  not the contract-retry waste.) **Shipped in v0.10.0, measured as a
  tail-cutter.** First, the attack order paid off: the seeded 3b `full`
  baseline is now 21/66 at 148k tokens — the P1/P2/P4 fixes compound to
  +6 score and −31% tokens vs the pre-fix 15/66 at 215k
  (`schema-exhausted` 22 → 1), so the blowup TokenBudget was drafted
  against largely no longer exists. Against that baseline, `budgeted`
  (= `full` + TokenBudget, ceiling 6000 / optional-cutoff 0.75) scores
  the same 21/66 and truncated exactly one tail run
  (`budget-exhausted` ×1 — a run that burned 7.5k unbounded, cut at
  6.5k), but total
  tokens came out +0.75% (149,335 vs 148,215) — the strictly-below bar
  **missed**: the governor sees only agent-loop spend (critic calls are
  invisible to it — first-class debt in the spec; attack: budget-aware
  client wrapping), and on this suite's distribution the default
  ceiling only catches the extreme tail. On 4b, `budgeted` is an exact
  no-op: **byte-equal** to the seeded `full` cell (64/66, 111,382
  tokens — incidentally a 66-run replay-determinism demonstration).
  Cell replay: 2/3 repeats byte-identical, 1 diverged (llama.cpp server
  nondeterminism — the documented P9 bound). Verdict: safety net
  verified, economizer not yet — that claim waits on critic-spend
  visibility, and TokenBudget stays out of the headline configs.

  **Outcome (2026-08-10, budget-visibility cycle, v0.11.1):** the debt
  is paid mechanically — `TokenBudget.setup` wraps the agent's client,
  so the governor now books every call including critic spend
  (`2026-08-10-bv-*.jsonl`). Measured against the same seeds:

  - **4b `budgeted`: 64/66 at 109,201 tokens (was 111,382).** 64 of 66
    rows byte-identical to the blind-governor cell; the two
    `nav-release-bundle` marginal failures each had their third critic
    call denied at the now-visible cutoff (mc 10 → 9,
    `critique-exhausted` → `wrong-answer`, −2,181 tokens, −2.0%).
    Score unchanged. This is the visibility fix doing exactly its job.
  - **3b `budgeted`: 21/66 at 161,736 tokens — the strictly-below-148,215
    bar MISSED**, and the miss is a measurement lesson, not a code
    defect. 53/66 rows are byte-identical to the blind cell. The gap is
    six marginal cells whose critic verdict flipped reject-ward vs the
    baseline sweep, extending their runs; the governor capped four of
    them at the ceiling (the other two ended uncapped — `wrong-answer`
    at 5,484 and `turns-exhausted` at 6,003), and the sweep's
    `budget-exhausted` ×6 (at 6.1–6.6k) comprises those four plus two
    non-flip trajectory divergences. Two independent checks
    exonerate the code: (1) an offline invariant test pins that a
    never-denying governor leaves the request stream byte-identical to
    no governor at all (the budget can only cut, never alter); (2) a
    back-to-back ×2 rerun of the four budget-capped flip cells on
    identical code
    (`bv-flip-probe-1/2`) diverged from *itself* on 5/12 rows,
    reproducing both the short and the long trajectory byte-for-byte in
    different sweeps — llama.cpp server nondeterminism on
    marginal-verdict cells, the documented P9 bound. Where trajectories
    did match, visibility cut spend exactly as designed: a critique
    round denied at the cutoff (`recall-oncall` mc 9 → 8, −779 and
    −1,034) and a hard-ceiling stop (`shop-basket-total` 7,209 → 6,128).
  - **Measurement lesson (recorded as method, like the P3 bar
    correction before it):** on a server with verdict-flip
    nondeterminism, a suite-total bar across reruns conflates the
    governor's effect (±1–3%) with trajectory variance (a single flip
    swings a run ±3–4k tokens). The honest instrument is the paired
    per-seed comparison on trajectory-stable rows — which is how both
    cells above are reported. Scores are unchanged on both models;
    the economizer claim is now *measurable* and measured small on this
    suite (critic spend is only worth denying near the cutoff), and the
    flip-prone long tails are LoopGuard's target, not the governor's.

(P5 — tool-use uplift on non-4b models — is not separately actionable: it
is P2's shadow. Grounded critique can't rescue tool tasks on a model
whose verdicts it can't parse.)

### Contract-robustness calibration (v0.9.0)

Targeted before/after bars for the P1/P2/P4 fixes — seeded runs (P9),
evidence JSONLs beside this file (`2026-08-10-*.jsonl`). "Before" for
the recall cells is the same-seed diagnostic probe; "before" for
`grounded` is the unseeded cross-model sweep cell:

| bar | cell | before | after | verdict |
|---|---|---|---|---|
| P1a/P1b | 3b `memory`, 9 recall tasks ×3 | 0/27; 18 arg-crash failures | 5/27; convertible crashes **0** | met |
| P4 | 7b `memory`, 9 recall tasks ×3 | 11/27; 11 JSON-less finals | **19/27**; 3 JSON-less | met |
| P2 | 3b `grounded`, full suite ×3 | 13/66; schema-exhausted ×17; 168k tok | 14/66; **×0**; 105k tok | met |
| P2 | 7b `grounded`, full suite ×3 | 24/66; schema-exhausted ×10; 94k tok | **33/66**; **×0**; 72k tok | met |
| no-regression | 4b `memory`, full suite ×3 | 57/66 (unseeded sweep) | **59/66** | met |
| no-regression | 4b `full`, full suite ×3 | 66/66 (unseeded sweep) | **64/66** | **missed — investigated** |

The missed bar, mechanically: both misses are `nav-release-bundle`,
outcome `critique-exhausted` — the agent answered with a wildcard
version without reading `VERSION`, and the grounded critic *correctly*
refused to bless a fabricated filename. Replay with the same seeds
reproduces the same two failures with near-identical critic feedback
(`2026-08-10-replay-4b-nav.jsonl` — P9 replayability working as
designed); the same cell on pre-cycle code with the same seeds gives
2/3 (`…-replay-4b-nav-main.jsonl`), so at most one run of the gap
traces to this cycle (constrained verdict decoding words the critic's
feedback differently, and one borderline recovery trajectory did not
converge inside the turn budget). The historical 66/66 was an unseeded
draw on a cell that is genuinely marginal: under pinned seeds the agent
sometimes skips the second hop, and no critic can rescue an answer the
agent never derived. Recorded as a watch item for the next full
re-baseline — if the cell stays red, the attack is rubric feedback
wording (Layer 2), not gate mechanics.

### What this means for the architecture

The cross-model failures cluster in one place: **wording and parsing that
talk to the model** (verdict contract, exact-JSON answer convention,
schema instruction) — all of it currently inlined inside core files and
all of it implicitly 4b-calibrated. The mechanics underneath (store,
gates' control flow, ledger, accounting) transfer fine — the recall floor
table above is the cleanest evidence. That is the case for the layer
split (core / contract / transport / policy / composition) becoming
physical structure: contract code moves out of core so it can be improved
per the P2/P4 ladder without touching proven mechanics, and tunables like
`max_turns` become profile data. The restructure is the next cycle;
P1–P9 land after it, into the separated layers.

Caveat, as for every sweep here: non-deterministic endpoint, no seed
pinning yet (P9), 3 repeats. Compare configs within one sweep, not across
sweeps; treat single-cell differences as noise unless they repeat across
models.

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
at least 20 tasks with all three families present, at least 2 each. Run it after
adding a task:

```bash
.venv/bin/python -m pytest runtime-py/tests/test_conformance.py
```

Back to the [README](../README.md).
