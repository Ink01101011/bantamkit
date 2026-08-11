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
  you whether a gate ever objected on a task — or just billed tokens.
  `schema_retries` counts revision feedbacks handed back to the agent.
  `critique_rounds` counts **critique rounds that judged the answer below
  threshold, including the round that raises** — so a `critique-exhausted`
  row records `max_rounds`. That changed on 2026-08-11 (`51c6594`); see
  [Reporting-semantics changes](#reporting-semantics-changes-2026-08-11-v0140)
  for what the older JSONLs mean.

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

### Reporting-semantics changes (2026-08-11, v0.14.0)

Round 1 of the RB-P attack queue moved four things about what a row *means*.
None of them is a scoring change; all of them break pre/post comparability on
some subset of cells, and every comparison in this document that spans one of
them is labelled **directional**. Committed evidence under `docs/eval-data/`
is deliberately **not** retro-edited — each file stays as it was measured, on
the semantics in force that day.

1. **`critique_rounds` counts the round that raises** (`51c6594`, Core). The
   column now means "critique rounds that judged the answer below threshold,
   including the one that raised". `critique-exhausted` rows read `max_rounds`
   where they used to read `max_rounds - 1` — with the default `max_rounds: 3`
   a known-exhausted row now reads 3, not 2, and under `max_rounds: 1` it reads
   1, not 0. Rows that never exhausted are unchanged, and a round whose verdict
   *clears* threshold is still not counted, so the column remains a count of
   objections rather than of critic calls. Per-round token attribution computed
   off the old column was wrong by a third on every exhausted run.
2. **`lean` and `full` constrain the first decode on schema-carrying tasks**
   (`2782af3`, Composition). `schema_retries`, `model_calls`, `tokens` and
   `outcome` all shift on any cell where the model previously needed
   `SchemaGate` to reach compliance, so pre/post numbers for those two configs
   on schema tasks are **not comparable**. On a server that enforces
   `json_schema`, `lean` now converges to `structured` on schema tasks *by
   construction*. Schemaless tasks and every other config are unaffected
   (pinned by test). One trap when reading a `full` token delta on a schema
   task: it mixes two effects, because a run that no longer dies in the schema
   gate goes on to reach the grounded critique it never previously got to.
3. **`grounded` no longer attaches its critic to storeless `memory_setup`
   tasks** (`f3b2d07`, Composition). `grounded` × memory-recall cells before
   and after this commit measure **different compositions** and are not
   comparable on score, tokens, `critique_rounds` or outcome mix;
   `critique-exhausted` cannot occur in those cells any more. Every other
   `grounded` cell and every `full` cell is unmoved — under `full` a
   `memory_setup` task always gets its store, so the guard never trips there.
4. **`schema-exhausted` and `critique-exhausted` rows carry a transcript**
   (`4a8b816`, `670d8ca`, Core). Both exceptions now carry the run transcript,
   so those runs write a non-empty `messages` array where they previously wrote
   `[]`. Recording only — the exceptions propagate unchanged, so no score can
   move. One gap remains and is deliberate: the `structured` config drives its
   own loop with no agent, so *its* `schema-exhausted` transcripts still record
   `messages: []` (pinned by
   `test_gate_raised_transcript_stays_empty_without_an_agent_loop`).

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
  across 15 runs (`critique_rounds` as recorded then counted revisions handed
  back to the agent, not scoring calls — an exhausted run recorded 2, not 3;
  since `51c6594` the raising round is counted too, so the same runs would
  record 3 today and this total would read higher — see
  [Reporting-semantics changes](#reporting-semantics-changes-2026-08-11-v0140)),
  every one on a
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

The reference sweep above is one model. This section runs the **frozen
v0.7.0 suite** — same 22 tasks, same rubrics, same prompts, same eight
configs, 3 repeats, 528 runs per model — across four models, and re-scopes
every Recommended-defaults claim to the models it actually holds on
(spec: `docs/superpowers/specs/2026-08-09-cross-model-sweep-design.md`).
The suite was frozen before measuring: a model that fails a task or rubric
is a data point, not a bug, and nothing was tuned per model.

**Provenance — re-baselined 2026-08-10 against v0.13.0.** Every number
below is recomputed from one re-baseline sweep run after the whole P-queue
had landed (P1/P2/P4 contract fixes, P7/P8/P9 measurement work, P3/P6
policy work, LoopGuard): four models × eight configs × 22 tasks × 3
repeats = **2,112 runs**, 528 per model. All of them are **seeded (P9)** —
66 seeds per model, one per (task, repeat), shared by all eight configs of
that pair — so every comparison *within* this sweep is paired rather than
sampled, and `bare`-vs-`graph` exact equality has its teeth back
(prediction 5 below). These numbers replace the 2026-08-09 sweep's; the
older evidence files stay in `docs/eval-data/`, and the claims that broke
are stated as broken rather than re-scoped.

**This sweep is a v0.13.0 measurement and v0.14.0 is not comparable to it
cell-for-cell.** Round 1 of the RB-P attack queue (2026-08-11) shipped
four reporting-semantics changes and several behaviour fixes on top of the
code that produced these numbers. The sweep is not re-run here — the
round's bars are seeded cell-level before/afters, and the attack outcomes
are recorded against each RB-P bullet below. Before quoting any number in
this section against v0.14.0 code, read
[Reporting-semantics changes](#reporting-semantics-changes-2026-08-11-v0140)
and check whether the cell is one of the ones that moved.

**Caveat — the v0.9.0 semantics break on `memory`/`lean`/`full`.** v0.9.0
attached `JsonAnswerGate` to those three configs for `json_equal`-scored
tasks (P4 below). They are therefore **not the same measurement** they
were on 2026-08-09: any pre→post delta on a `memory`, `lean` or `full`
cell is labelled **post-break** and is never reported here as an
"improvement" or a "regression" — the gate changed what the config *is*.
The five storeless configs (`bare`, `structured`, `critique`, `grounded`,
`graph`) are comparable in code semantics, but the 2026-08-09 sweep was
**unseeded**, so those deltas are directional only; the size of that
sampling bar is itself a measured problem (RB-P9). The only exact
comparisons available are against the *seeded* 2026-08-10 cells, and those
are reported separately under "Reproduction" below.

| model | class | evidence (2026-08-10 re-baseline) | previous sweep (2026-08-09, unseeded) |
|---|---|---|---|
| `llama3.2:3b` | cross-family, small end | `docs/eval-data/2026-08-10-rebaseline-3b.jsonl` | `…/2026-08-09-crossmodel-llama32-3b.jsonl` |
| `qwen3:4b-instruct` | reference (re-run, not reused) | `docs/eval-data/2026-08-10-rebaseline-4b.jsonl` | `…/2026-08-09-filegraph-sweep.jsonl` |
| `qwen2.5:7b-instruct` | size up, near-family | `docs/eval-data/2026-08-10-rebaseline-7b.jsonl` | `…/2026-08-09-crossmodel-qwen25-7b.jsonl` |
| `qwen2.5:14b-instruct` | ceiling reference, outside the 1–8B target band | `docs/eval-data/2026-08-10-rebaseline-14b.jsonl` | `…/2026-08-09-crossmodel-qwen25-14b.jsonl` |

### Per-model summaries

`llama3.2:3b` — everything is still hard for this model, but the
critique-family collapse is gone: the P2 constrained-decoding tier and the
P1 argument coercion turned `full` from the sweep's worst config into a
tied-best one:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 13/66 | 31,229 | 0.42 |
| structured | 17/66 | 30,564 | 0.56 |
| critique | 14/66 | 64,857 | 0.22 |
| grounded | 14/66 | 104,629 | 0.13 |
| graph | 14/66 | 45,296 | 0.31 |
| memory | 21/66 | 71,693 | 0.29 |
| lean | 21/66 | 70,320 | 0.30 |
| full | 21/66 | 154,474 | 0.14 |

Best score is a three-way tie at 21/66 (`memory`/`lean`/`full`), and
`lean` is the cheapest of the three at 70,320 tokens — `full` pays 2.2×
`lean`'s bill for exactly the same score. Efficiency winner: `structured`
(0.56/1k). Recall with a store reaches only 5/27 (6/27 under `full`) —
the P1-banked ceiling, unchanged and re-confirmed at sweep scale
(RB-P7) — and this is the only model in the sweep whose `SchemaGate`
retry loop fires at all (RB-P3).

`qwen3:4b-instruct` — the reference model, re-run rather than reused:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 30/66 | 18,809 | 1.59 |
| structured | 30/66 | 19,573 | 1.53 |
| critique | 35/66 | 47,435 | 0.74 |
| grounded | 38/66 | 102,656 | 0.37 |
| graph | 36/66 | 23,182 | 1.55 |
| memory | 59/66 | 55,525 | 1.06 |
| lean | 59/66 | 56,289 | 1.05 |
| full | **64/66** | 111,382 | 0.57 |

`full` leads at 64/66; the two misses are the same marginal
`nav-release-bundle` `critique-exhausted` pair the v0.9.0 no-regression
bar recorded as a watch item — it stayed red (RB-P5). This is the only
model where the store rescue is at ceiling (27/27). Efficiency winner:
`bare` (1.59/1k), with `graph` (1.55) and `structured` (1.53) inside a
hair. `grounded` buys +8 over `bare` and the only clean tool-use sweep
outside `full` (18/18), but it burns 11 `critique-exhausted` runs on
storeless recall tasks that cannot produce evidence (RB-P8).

`qwen2.5:7b-instruct` — the P2/P4 fixes land hardest here, and so does the
token bill:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 31/66 | 24,693 | 1.26 |
| structured | 33/66 | 24,823 | 1.33 |
| critique | 33/66 | 55,783 | 0.59 |
| grounded | 33/66 | 71,653 | 0.46 |
| graph | 32/66 | 28,381 | 1.13 |
| memory | 56/66 | 169,452 | 0.33 |
| lean | 57/66 | 169,319 | 0.34 |
| full | **58/66** | 222,105 | 0.26 |

`full` leads at 58/66 and the answer-format tax that used to cost 7b whole
cells is mostly paid off: the three store configs lose 3 runs each to
`malformed-output`, down from 16 / 15 / 13 — post-break, and
`JsonAnswerGate` is exactly the mechanism, so this is the semantics change
showing up rather than the model improving. What replaces it is cost:
`memory`/`lean` spend **3.0×** the 4b bill for a lower score, and `full`
spends 2.0× — with 10 of the model's 11 `turns-exhausted` runs sitting in
store-config recall at 10.4–11.6k tokens each (RB-P6). Efficiency winner:
`structured` (1.33/1k).

`qwen2.5:14b-instruct` — the ceiling reference saturates the non-recall
families and is the model where two claims broke:

| config | score | tokens | score/1k tok |
|---|---|---|---|
| bare | 36/66 | 26,824 | 1.34 |
| structured | 36/66 | 26,942 | 1.34 |
| critique | 35/66 | 68,496 | 0.51 |
| grounded | 36/66 | 90,626 | 0.40 |
| graph | 36/66 | 31,825 | 1.13 |
| memory | 52/66 | 93,192 | 0.56 |
| lean | 52/66 | 93,310 | 0.56 |
| full | **58/66** | 159,290 | 0.36 |

`full` now clearly beats `memory` (+6) at +71% tokens — and unlike the
previous sweep, the gap is *earned*: tool-use goes 13/18 → 18/18 under the
grounded critic, plus one recall task. The blind `critique` config is the
sweep's only negative single-attach (−1 at 2.6× tokens), and it does it by
destroying a solved cell: `nav-prod-port` 3/3 under `bare` → 0/3
`critique-exhausted` on pure format nitpicking (RB-P4). Storeless recall is
no longer 0/27 here (2/27 — the model *guesses* one task's answer, RB-P2),
and store-config recall sits at 18/27 with concentrated named failures
(RB-P1). Efficiency winners: `bare`/`structured` (1.34/1k).

### Outcome taxonomy (528 rows per model)

| outcome | 3b | 4b | 7b | 14b |
|---|---|---|---|---|
| pass | 135 | 351 | 333 | 341 |
| wrong-answer | 306 | 154 | 149 | 166 |
| malformed-output | 57 | 10 | 35 | 14 |
| turns-exhausted | 16 | 0 | 11 | 0 |
| critique-exhausted | 12 | 13 | 0 | 7 |
| schema-exhausted | 2 | 0 | 0 | 0 |

The P7 taxonomy split is visible working: 3b's 16 `MaxTurnsExceeded` runs
are labelled `turns-exhausted` with no `transport-error` conflation, and
no run in the sweep is a transport failure. `budget-exhausted` cannot
appear — `budgeted` is not a headline config. The concentrations are
where the problems are: 7b's 11 `turns-exhausted` (RB-P6), 4b's 13
`critique-exhausted` (11 in `grounded` — RB-P8 — plus the 2 known `full`
nav rows, RB-P5), 14b's 7 (3 of them the `nav-prod-port` format kills,
RB-P4), and the 2 `schema-exhausted` (RB-P3 — and note these are
`SchemaGate` *answer-schema* exhaustions with `schema_retries` 2 apiece,
a different mechanism from the 2026-08-09 sweep's `schema-exhausted`
rows, which were verdict-contract failures at `schema_retries` 0 and
were what P2 fixed).

Sweep totals for the two retry counters: **4 `schema_retries` in 2,112
runs** (all four on 3b, in the two `schema-exhausted` rows) and
`critique_rounds` 64 / 60 / 9 / 47 on 3b / 4b / 7b / 14b. 7b's 9 rounds
say its critic accepts almost everything first-pass — consistent with
`critique` buying it only +2. (These `critique_rounds` totals are on the
**old** semantics: this sweep predates `51c6594`, so every
`critique-exhausted` row here undercounts by one and the totals would read
higher if re-measured today. See
[Reporting-semantics changes](#reporting-semantics-changes-2026-08-11-v0140).
The JSONLs are not retro-edited.)

### Reproduction: the seeded overlap cells

Seven (model, config) cells in this sweep have a *seeded* 2026-08-10
baseline from the P-queue's calibration bars — same code semantics, same
seeds, so these are exact comparisons rather than directional ones.
Row-identical = `passed`, `tokens`, `outcome`, `model_calls` and
`tool_calls` all equal for the same (task, seed); seed overlap was
verified 100% before pairing.

| cell | baseline | n | score | tokens | row-identical | pass-flips |
|---|---|---|---|---|---|---|
| 3b `full` | `pb-3b-full-baseline` | 66 | 21 → 21 | 148,215 → 154,474 | 58/66 | 0 |
| 3b `grounded` | `bar-p2-3b-grounded` | 66 | 14 → 14 | 104,701 → 104,629 | 65/66 | 0 |
| 7b `grounded` | `bar-p2-7b-grounded` | 66 | 33 → 33 | 71,660 → 71,653 | 65/66 | 0 |
| 4b `full` | `bar-noreg-4b-full` | 66 | 64 → 64 | 111,382 → 111,382 | **66/66** | 0 |
| 4b `memory` | `bar-noreg-4b-memory` | 66 | 59 → 59 | 55,525 → 55,525 | **66/66** | 0 |
| 3b `memory` (recall subset) | `bar-p1-3b-memory` | 27 | 5 → 5 | 41,071 → 41,071 | **27/27** | 0 |
| 7b `memory` (recall subset) | `bar-p4-7b-memory` | 27 | 19 → 19 | 144,391 → 144,391 | **27/27** | 0 |

**Zero pass-flips across all seven cells — 384 paired rows.** Four cells
are field-identical on every row (P9 replay determinism at cell scale);
the ten non-identical rows (8 on 3b `full`, 1 on each grounded cell) are
token/trajectory divergences with unchanged pass/fail — the documented
llama.cpp nondeterminism bound. Where a seeded baseline exists, the
re-baseline reproduces it exactly at the score level.

Against the *unseeded* 2026-08-09 sweep the biggest movers are 7b `full`
36→58, 7b `lean` 44→57 and 7b `memory` 44→56 (all **post-break**), 7b
`grounded` 24→33 at −24% tokens and 3b `grounded` 13→14 at −38% tokens
(the P2 fix, comparable semantics), and 3b `full` 15→21 at −28% tokens
(post-break, P1+P2+P4 compounding). The biggest negative mover is 14b
`memory` 59→52 (post-break, and a real problem regardless — RB-P1). 4b
moves by at most one task on every storeless config (`bare` 30→30,
`structured` 30→30, `critique` 36→35, `grounded` 38→38, `graph` 36→36) —
the no-regression story holding at sweep scale.

### The recall story across models

The project's core claim — recall goes ~0/27 without a store to ~27/27
with one — **varies sharply by model, and its floor half now has a hole**:

| memory-recall (n=27) | 3b | 4b (ref) | 7b | 14b |
|---|---|---|---|---|
| storeless (`bare`) | 0/27 | 0/27 | 0/27 | **2/27** |
| `memory` | 5/27 | **27/27** | 19/27 | 18/27 |
| `lean` | 5/27 | 27/27 | 19/27 | 18/27 |
| `full` | 6/27 | 27/27 | 19/27 | 19/27 |

**The universal-floor claim BROKE on 14b.** Two of its 27 storeless runs
pass — both `recall-db-port`, at 75 tokens, with no store and no tools;
`structured` and `graph` pass the same task on the same two seeds at the
same 75 tokens, and `critique` passes it too. The model is *guessing* a
plausible port, which makes that task a rubric leak rather than a recall
measurement (RB-P2). The floor holds on the other three models and on
every other recall task.

The rescue half remains model-dependent and non-monotonic in size: 4b is
the only model at ceiling; 7b holds its post-P4 19/27 (seeded-identical to
the bar-p4 cell); 3b holds its post-P1 5/27 (seeded-identical to bar-p1);
and 14b — the biggest model — sits *below* 7b at 18/27, with all nine
misses landing as `wrong-answer` on four named tasks (RB-P1).

### Claims-transfer table

Single-attach deltas vs `bare`, all four models (composition configs
`lean`/`full` shown for context):

| model | structured | critique | grounded | graph | memory | (lean) | (full) |
|---|---|---|---|---|---|---|---|
| 3b | +4 | +1 | +1 | +1 | **+8** | +8 | +8 |
| 4b | 0 | +5 | +8 | +6 | **+29** | +29 | +34 |
| 7b | +2 | +2 | +2 | +1 | **+25** | +26 | +27 |
| 14b | 0 | −1 | 0 | 0 | **+16** | +16 | +22 |

Every README Recommended-defaults bullet, against every model. "Holds" =
the guidance as written is what you should do on that model.

| claim | 3b | 4b (ref) | 7b | 14b |
|---|---|---|---|---|
| Always attach `Memory` | **holds** — biggest single mover, +8 (13→21), but recall only 5/27 | **holds** (+29, 30→59, recall 27/27) | **holds** — biggest single mover, +25 (31→56), recall 19/27 | **holds** (+16, 36→52, recall 18/27) |
| Attach `FileAccessGraph` for file work | **does not hold** — file-nav 0/6→1/6, the ledger is unusable here | **holds** — file-nav 0/6→**6/6** at +23% tokens | **marginal** — 5/6→6/6, +1 inside repeat noise | **does not hold** — `bare` already 6/6 (saturated) |
| `structured()` is free when the model complies | **config-level holds** (0 retries in 66 runs, +4) — but SchemaGate *exhausted* twice inside `lean`/`full` (RB-P3) | **holds** — 0 retries in 528 runs | **holds** — 0 retries in 528 runs, best score/1k (1.33) | **holds** — 0 retries in 528 runs, joint-best score/1k (1.34) |
| Skip the blind `CritiqueGate` | **holds** — +1 at 2.1× tokens | **holds** — +5 at 2.5× tokens | **holds** — +2 at 2.3× tokens | **holds, hardest** — **−1** at 2.6× tokens (kills a solved cell, RB-P4) |
| `full` measures 66/66 | **does not hold** — 21/66 (though tied best) | **does not hold** — 64/66; the watch-item cell stayed red (RB-P5) | **does not hold** — 58/66 (top config) | **does not hold** — 58/66 (top config) |
| Prefer `GroundedCritiqueGate` with tools | **does not hold as value** — no longer *harmful* (+1 vs bare) but +1 at 3.4× tokens | **holds** — +8, tool-use 18/18 | **does not hold as value** — no longer harmful, +2 at 2.9× tokens | **does not hold standalone** — ±0 at 3.4×; its value here appears only inside `full` (+6) |

Two claims survive all four models unqualified: `Memory` as the biggest
single mover, and skipping the blind critic (now *stronger* — on 14b the
blind critic is measurably negative). `structured()` survives as written
at the config level on all four, but the sweep-level phrasing it used to
carry ("the retry loop has never fired on any model") is **false as of
this sweep** — see prediction 2. `FileAccessGraph` is confirmed ~4B-scoped
with the window exactly where it was: below it the model can't use the
ledger (3b 1/6), above it the tasks saturate (14b `bare` 6/6). `full`'s
66/66 breaks everywhere, but its *standing* improved — top config on 4b,
7b and 14b, tied top on 3b. Grounded critique is no longer harmful
anywhere (the P2 fix held), yet standalone it still only pays on 4b.

**Two cells in this table have moved since it was measured (2026-08-11,
round 1 of the RB-P queue). The table itself is left as measured — it is
the 2026-08-10 record — and the moves are noted here instead:** the 3b
`structured()` qualifier (`SchemaGate` exhausted twice inside
`lean`/`full`) is **fixed** — the gate never fired because the constrained
decode never engaged there, and RB-P3's fix converts both rows; and 4b's
`full` watch-item cell is **no longer red** — RB-P5's contract fix takes
`nav-release-bundle` 1/3 → 3/3. The 14b blind-critic row stands: RB-P4 is
confirmed, its attempted fix measured harmful, and the cell is still 0/3.
Neither move has been re-measured at sweep scale, so this table is not
rewritten off two cell bars.

### Prediction scorecard (spec §2.3, written before measuring)

1. **Memory transfers** — *partially confirmed, unchanged verdict.* The
   mover claim holds on all four models (+8 / +29 / +25 / +16); the
   ~27/27 magnitude claim is refuted on three of four (5/27 on 3b, 19/27
   on 7b, 18/27 on 14b). Carried as problems RB-P1 and RB-P7, not as a
   smaller claim.
2. **Structured tax holds** — *broken as stated.* The config-level claim
   survives (0 `schema_retries` in all 264 `structured` runs, and 0 in
   all 528 runs on each of 4b, 7b and 14b), but the sweep-level wording
   "SchemaGate's retry loop has still never fired on any model" is now
   false: on 3b it fired **4 times** — `lean` and `full`, both on
   `extract-order`, seed 4084933696, 2 retries each, both ending
   `schema-exhausted` on `'item' is a required property`. Honest total:
   **4 retries in 2,112 runs**, not 0 — and the `full` firing was already
   sitting in a seeded cell from the previous cycle, so the claim had
   been stale before this sweep measured it. RB-P3.
3. **Saturation on the big end** — *confirmed for file-nav, refuted for
   tool-use.* File-nav under `bare` is 5/6 on 7b and now **6/6** on 14b —
   fully saturated, which is why `graph` can buy nothing there.
   `shop-basket-total` saturates nowhere storeless (`bare` 0/3 on 3b, 4b
   and 14b; 1/3 on 7b) and needs a whole config to rescue it: `grounded`
   3/3 on 4b, `memory` 3/3 on 7b, `full` 3/3 on 14b.
4. **Critique risk on the small end** — *no longer holds in its measured
   form.* 3b `full` is not a collapse any more (21/66 at 154k, tied for
   best, vs 15/66 at 215k pre-queue) and `grounded` no longer lands below
   `bare` on either 3b or 7b. What survives is narrower and moved up the
   size range: the **blind** critic is worthless-to-harmful everywhere
   (+1 / +5 / +2 / −1), and its one destructive cell is on the *largest*
   model, not the smallest (RB-P4).
5. **Graph no-op check is structural** — *now confirmed exactly, as P9
   promised.* With seeds pinned, `bare` and `graph` are field-identical
   (`passed`, `tokens`, `outcome`, `model_calls`, `tool_calls`) on **all
   60 off-family cells on all four models — 240/240**, zero divergence.
   The 2026-08-09 reframe was right: the earlier 8/20, 3/20 and 4/20
   divergences were sampling variance under an unpinned endpoint, not
   leakage, and exact equality is a usable check again.

### Measured problems (re-baseline 2026-08-10) → attack plan

Same rule as the P1–P9 block below: nothing measured negative is
re-scoped into a smaller claim. Each negative from the re-baseline becomes
a problem with an owner-direction, and the layer names refer to the
5-layer model (core / contract / transport / policy / composition).

- **RB-P1 — 14b store-config recall sits at 18/27 with concentrated,
  named failures.** Under `memory`: `recall-env-endpoint` 0/3,
  `recall-org-quota` 0/3, `recall-owner` 1/3, `recall-cache-ttl` 2/3 —
  nine misses, **all of them `wrong-answer`**, none malformed. `lean` is
  identical task-for-task; `full` rescues one `recall-owner` repeat
  (19/27). Pre-P-queue the same model measured 23/27 (misses:
  `recall-org-quota` ×3, `recall-oncall` ×1), so the post-break label
  applies — but `recall-env-endpoint` going 3/3 → 0/3 and `recall-owner`
  3/3 → 1/3 on the *ceiling* model is a measured negative regardless of
  comparability, and it puts the largest model below the 7b. Because
  every miss is `wrong-answer`, `JsonAnswerGate` is not obviously the
  mechanism — but it is the main code delta on this path. **Attack:**
  seeded `--transcripts` probe of 14b `memory` on
  env-endpoint / owner / org-quota (the P1/P4 playbook, 27 runs), and
  split store-retrieval damage from synthesis damage from
  gate-restatement damage *before* touching any layer.

  **Outcome (2026-08-11, RP3 probe + RP4c fix — mechanism CONFIRMED and
  FIXED, attribution CORRECTED, the framing above PARTLY REFUTED):**

  The three-way split the attack asked for came back
  **retrieval 6 / synthesis 2 / gate-restatement 0** across the eight
  misses on the three probed tasks (per-task pass counts in
  `2026-08-11-rp4c-14b-memory-recall-before.jsonl`; the attribution itself
  is read off the probe transcripts, which are not committed, so no other
  number from them appears here). **`JsonAnswerGate` is exonerated.** It
  fired in one of the eight misses, and there it restated a wrong *prose*
  answer into a wrong *JSON* answer — it never turned a right answer
  wrong. Its only real effect on this family is taxonomy, and it is
  precisely *why* "every miss is `wrong-answer`, none malformed" held. The
  bullet above named it as "the main code delta on this path"; that was a
  proximity argument and the probe killed it.

  Root cause, 6 of 8: **the 14b sends `k: 1` and `Memory.recall` obeyed
  it.** Every two-fact recall task then answered from half its evidence.
  The store was never defective — offline, `k=3` returns both facts for
  every query string those transcripts actually used. The other 2 of 8 are
  **same-turn write-back poisoning**: one assistant turn dispatches
  recall / save / recall, the speculative save moves the fact between the
  two reads, and the model answers off its own fabrication.

  Fixes, both Core: `4761109` floors the model-supplied `k` at the store's
  configured default, and `2dbe162` gives `Agent` a batch scope so reads
  are served from the facts as of batch entry while writes stay live from
  the next batch on.

  Bar, `qwen2.5:14b-instruct --config memory --repeats 3`, seeded per
  `run_seed(model, task, repeat)`, before-arm run from a clean tree at
  `2782af3` so RP4a/RP4b sit in both arms — **18/27 → 23/27, no task
  down**, tool calls 139 → 63, tokens 67,160 → 49,506:

  | task | before | after |
  |---|---|---|
  | `recall-env-endpoint` | 0/3 | 1/3 |
  | `recall-org-quota` | 0/3 | 2/3 |
  | `recall-owner` | 1/3 | **3/3** |
  | `recall-cache-ttl` | 2/3 | 2/3 |
  | the other five recall tasks | 3/3 | 3/3 |

  The model's habit did not change and was never expected to: 40 of 42
  `memory_recall` calls in the after-arm still carry `k: 1` and 15 batches
  still mix a save with a recall — the component floors the one and the
  scope isolates the other. Evidence:
  `2026-08-11-rp4c-14b-memory-recall-{before,after}.jsonl`.

  **The residue is honest, and it is a different residue.** All four
  remaining misses now *receive* both seeded facts and lose them
  afterwards — **retrieval misses: zero**. Two are synthesis errors on
  `recall-env-endpoint` (`/v3` and `/reports/v3` for `/v3/reports`), one
  is an arithmetic error on `recall-org-quota` (20480 for 40×5), and one
  is a `recall-cache-ttl` run that calls no tool at all and answers in
  Thai, byte-identical before and after.

  **What is refuted in the framing above.** Three corrections, and they
  matter because the bullet was written as if a code delta explained the
  drop:
  - `git diff 3728a70 HEAD -- assets/evals/tasks assets/skills assets/tools`
    is **empty**. The model-facing surface is byte-identical across the
    whole P-queue, so nothing in it can explain the *first* assistant
    message, which is where `k: 1` is decided. The `k: 1` habit is the
    model's, not something the queue taught it.
  - `recall-owner` 3/3 → 1/3 does not survive re-sampling: an unseeded
    repeat probe did not reproduce the drop. Those probe rows were not
    committed as evidence, so no number for them is quoted here — but the
    claim that this task regressed is retired.
  - `recall-env-endpoint` 3/3 → 0/3 **is** real and reproducible, and its
    mechanism (`k: 1` truncation) pre-existed the P-queue.
  - The headline "23/27 → 18/27" mixes a code delta with a
    **sampling-regime delta**: the pre-queue 23/27 was measured
    *unseeded*. It is therefore **directional**, not a measurement of
    damage done by the queue. The 18/27 → 23/27 bar above is not — both
    arms are seeded and paired.
- **RB-P2 — `recall-db-port` is guessable storeless: a rubric leak.** 14b
  passes it 2/3 under `bare`, `structured` and `graph` — same two seeds,
  75 tokens each, no store, no tools — and 2/3 under `critique` at ~400
  tokens. The recall family's floor claim ("no model passes recall without
  a store, so the tasks measure what they claim") now has a measured hole
  on exactly one task. **Attack:** change the stored fact to a
  non-default, non-guessable value (eval task data). Frozen-suite rules
  mean this lands in the *next* suite version with the break documented,
  not as a mid-flight patch.

  **Status after round 1 (2026-08-11): UNTOUCHED.** Out of scope by the
  job's own frozen-suite constraint, so nothing was probed, measured or
  changed. The problem stands exactly as written above.
- **RB-P3 — `SchemaGate` exhausts on 3b `lean`/`full` `extract-order`,
  and the sweep-level "never fired" claim is dead.** Seed 4084933696, 2
  retries each, both ending `schema-exhausted` (`JSON does not match
  schema at 'root': 'item' is a required property`). Two corrections to
  how this could be reported: it is **not** the first firing in project
  history — the `full` row is field-identical to the seeded 3b `full`
  cell from the policy/budget cycle
  (`2026-08-10-pb-3b-full-baseline.jsonl`, and it reproduces again in
  `pb-3b-budgeted` / `bv-3b-budgeted`), so this sweep *reproduces* a
  firing that was already on disk and adds one new composition (`lean`);
  and it is not the first `schema-exhausted` **outcome** either — the
  2026-08-09 sweep had 41 / 25 / 1 such rows on 3b / 7b / 14b, but those
  carried `schema_retries` 0 because they were verdict-contract failures
  (the P2 path), a different mechanism. What is genuinely new is that a
  full cross-model sweep now records nonzero `schema_retries` at all, so
  the claim this doc carried — "the retry loop has still never fired on
  any model" — is false and is retired here. v0.9.0's P2 fix wired
  `response_format:
  json_schema` into `structured()`, and constrained decoding should make a
  missing *required* key impossible while it is active. **Attack:**
  transcript the cell and verify the constrained-decoding path actually
  engages for `SchemaGate` inside the `lean`/`full` composition rather
  than silently falling back to the prompt+parse tier; if it does engage,
  this is a llama.cpp `json_schema` enforcement gap and belongs in a
  pinned test. (Contract + Transport.)

  **Outcome (2026-08-11, RP1 probe + RP4b fix — CONFIRMED and FIXED, and
  the server is exonerated):** the probe took the first of the two forks,
  not the second. **Constrained decoding never engaged on the `lean`/`full`
  path at all.** Wire capture of the failing cell showed its three POSTs
  carrying only `{model, messages, seed}` — no `response_format`
  parameter of any kind. `structured()` was called only when the resolved
  config was `structured`; `lean` and `full` fell through to `agent.run()`,
  whose single model call had no way to ask for a constrained decode. The
  tier was alive in-process the whole time — `GroundedCritiqueGate` sends
  it at `critique.py:115` — but with the *verdict* schema, never the task
  schema. So the doc's own hypothesis ("silently falling back to the
  prompt+parse tier") was right in substance and understated in degree:
  there was no fallback, there was no tier.

  **Not a llama.cpp / Ollama enforcement gap.** Ollama 0.18.0 does enforce
  `json_schema`: a one-shot with the task schema returned bare
  schema-valid objects 3/3 where the unconstrained call returned 0/3. The
  pinned test the attack asked for is therefore a *wiring* test, and it
  landed as one.

  Fix in two commits, one layer each: `f7918ab` (Core) gives `Agent` an
  optional `response_format` forwarded to its own model call behind the
  same duck-typed capability memo `structured()` already used, re-checked
  per turn so a 400 drops the tier mid-run; `2782af3` (Composition) sets
  it from `task["schema"]` at the one place the schema gate is registered.
  Deliberately *not* inside `SchemaGate`: the gate reacts to a violation
  that already exists, and the decode worth constraining is the first one.

  Bar, `llama3.2:3b` / `extract-order`, seeds 1729841256 / 2166512753 /
  4084933696, before-arm reproducing `2026-08-10-rebaseline-3b.jsonl`
  row for row:

  | config | seed | before | after |
  |---|---|---|---|
  | `lean` | 4084933696 | `schema-exhausted`, 2 retries, 3 calls, 674 tok | **pass**, 0 retries, 1 call, 119 tok |
  | `full` | 4084933696 | `schema-exhausted`, 2 retries, 3 calls, 524 tok | **pass**, 0 retries, 2 calls, 681 tok |
  | `lean`/`full` | 1729841256, 2166512753 | — | byte-identical to before |
  | `structured` (control) | all three | — | unmoved |

  `schema-exhausted` is gone from the cell. **One prediction corrected:**
  RP1 expected the win to convert to a clean `wrong-answer`, because 3b
  answers `"Widgets"` where the suite expects `"widget"`. That defect
  belongs to a *different* seed — 1729841256, which is `wrong-answer`
  before and after — and on 4084933696 the constrained decode passes
  outright. Evidence:
  `2026-08-11-rbp3-3b-extract-order-lean-full.jsonl`,
  `2026-08-11-rbp3-3b-extract-order-structured.jsonl`.

  **Semantics moved** — see change 2 in
  [Reporting-semantics changes](#reporting-semantics-changes-2026-08-11-v0140).
  `lean`/`full` numbers on schema-carrying tasks are not comparable across
  `2782af3`.
- **RB-P4 — the blind critic kills a solved cell on 14b, on format
  nitpicks.** `nav-prod-port` is 3/3 under `bare` and 0/3 under
  `critique`, all three `critique-exhausted`. The recorded feedback demands
  a JSON shape the rubric does not require, and two of the three verdicts
  say so outright — "Required content present but incorrectly formatted"
  and "Correct answer format wasn't followed but required content was
  identified correctly". ~~Same failure family as RB-P5.~~ **RETIRED
  2026-08-11 — this claim is false.** RP2's probe refuted it and RP4d's
  arms confirmed the refutation: RB-P5 is a *correct* verdict followed by
  an unactionable retry verb, RB-P4 is a critic scoring a correct answer
  wrong, and the RB-P5 contract fix left the RB-P4 cell bit-for-bit where
  it was (`2026-08-11-rp4d-14b-nav-prod-port-{before,after}.jsonl`, last
  feedback byte-identical on all three seeds). **Attack (as written at the
  time):** critic rubric wording (Layer 2 / contract) — score content, not
  format, unless the task's rubric is itself format-scored; one wording
  change, then re-run the two nav cells seeded.

  **Outcome (2026-08-11, RP2 probe + RP4d attempt — CONFIRMED, then the
  fix MEASURED HARMFUL and REVERTED). This is a measured negative, not a
  deferral.**

  Confirmed in the strongest available form: on all three seeds the
  pre-critique answer was `{"port": 9443}` — byte-identical to what `bare`
  passes with — and the critic scored it down purely on format, once
  self-refutingly. The committed row for seed 634446002 carries the
  verdict verbatim: *"Answer should be in format `{"port": <number>}`, not
  `{"port": 9443}` without JSON structure. Correct answer format wasn't
  followed but required content was identified correctly."* The answer it
  is describing as lacking JSON structure **is** `{"port": 9443}`. It is
  literal-matching the placeholder token copied out of the task prompt.

  **The rubric rewording was written once, measured, and reverted.** It
  named the placeholder conflict, stated that a literal value substituted
  for a placeholder satisfies the template, used a neutral `{"key": 42}`
  example that leaks no port, and was placed after `{output}` for recency.
  It was not re-tuned against the bar. Four arms, 14b / `nav-prod-port` /
  `--config critique`, seeds 2331795949 / 4094558621 / 634446002:

  | arm | score | tokens | evidence |
  |---|---|---|---|
  | before (`9f614ad`) | 0/3 | 12,390 | `...-before.jsonl` |
  | rubric only | 1/3 | 12,692 | `...-reverted-rubric-only.jsonl` |
  | rubric + RB-P5 contract | 0/3 | 15,257 | `...-reverted-rubric-and-contract.jsonl` |
  | **shipped** (contract only, rubric reverted) | 0/3 | 12,885 | `...-after.jsonl` |

  Per-round critic scores, read off the run transcripts (those are not
  committed — the JSONLs carry only the last feedback string, so this one
  number has weaker provenance than the rest of this section and is
  labelled as such): **5,5 before → 0,0 under either rubric arm → 5,5
  shipped**. The rewording drove the score on a byte-identical,
  byte-*correct* answer from 5/10 to 0/10 on all three seeds, and made the
  critic invent a new non-content requirement — its committed feedback on
  seed 4094558621 adds *"Additionally, no explanation or listing of steps
  taken to find the port in workspace files was provided as per task
  instructions."* The lone `rubric only` pass was **not the fix working**: the
  critic still scored 0/10 on format and the *answerer* appeased it by
  re-emitting the same `{"port": 9443}` pretty-printed across three lines,
  which then scored ≥ 7. Under the RB-P5 contract wording that same seed
  re-read `config/prod.yaml` instead of reformatting, answered
  identically, and exhausted — which is how a 1/3 became a 0/3.

  `assets/rubrics/task-completion.yaml` is byte-identical to `main` on
  this branch (verified independently by the reviewer). Both reverted arms
  are committed as the evidence for the negative result.

  **Mechanism now believed** (and it is not the one the bullet assumed):
  the blind `critique` critic sees no tool evidence and exactly one
  content token, and that token is already correct — so its score is not a
  content measure at all. Compact `{"port": 9443}` scores 0–5 and the same
  value pretty-printed scores ≥ 7. It compares literal strings. More
  prohibition prose cannot fix that, and naming the placeholder is
  actively counterproductive because it puts the template in front of the
  judge a second time.

  **Attack direction — structural, not lexical, and not attempted:** give
  `task-completion` the `reasoning` field `grounded-completion` already
  has, and require the critic to state the fact the task asks for and the
  answer's value for it *before* scoring. The grounded critic, forced to
  derive first, judged content correctly on the 4b cell throughout —
  including on the answer it had to fail. (Contract, Layer 2.) The
  problem stays open.

  **Outcome (2026-08-11, SA1 — the structural attack WORKED. RB-P4 is
  CLOSED.)** `task-completion` gained the `reasoning` field, required and
  listed first, plus one step before scoring: name the fact the task asks
  for, quote the value the answer supplies for it, then judge. The blind
  critic is explicitly *not* asked to derive the correct answer — it has
  no evidence, and for `nav-prod-port` no way whatsoever to know the port
  is 9443, so deriving would mean guessing. Extract-and-compare is the
  blind analogue of the grounded critic's derive-first step.

  Four arms, `--config critique --repeats 3` over the frozen 22-task
  suite, before-arms from a pristine worktree at `d2f78b7`. The bar was
  pre-registered in writing before any arm finished.

  | arm | model | suite | `nav-prod-port` | tokens |
  |---|---|---|---|---|
  | before | 14b | 35/66 | **0/3** (`critique-exhausted`) | 67,312 |
  | after | 14b | **38/66** | **3/3** | 76,399 (+13.5%) |
  | before | 7b | 33/66 | 3/3 | 56,066 |
  | after | 7b | 33/66 | 3/3 | 64,888 (+15.7%) |

  All three 14b gains are the target cell; **no other cell moved in
  either direction on either model**, no 3/3 task fell, and no critique
  round hit `StructuredOutputError` on the new required field.

  **The critic changed its verdict; the answerer did not change its
  answer** — the round-1 appeasement pattern is excluded on the evidence,
  not assumed. On all three seeds the answerer emitted exactly
  `{"port": 9443}`, byte-identical to the before-arm's first answer, and
  all three passes carry `critique_rounds == 0`: zero feedback was ever
  injected, so there was nothing for the answerer to appease. A
  deterministic replay of the critic alone on that byte-identical answer,
  at the same pinned seeds, scores **5,5,5 → 7,10,10**. Seed 634446002 —
  whose before-verdict was the self-refuting one quoted above — now
  reasons: *"Find the production port of billing-svc from the workspace
  files; {"port": 9443}. The answer provides a port number, which matches
  the fact requested."* Having written the fact and the value down, it no
  longer reaches for the format.

  **Residual risk, recorded not smoothed:** seed 2331795949 scores
  exactly 7 against a threshold of 7 — a zero-margin pass. Its reasoning
  hedges honestly about what a blind critic cannot check (*"correctness
  cannot be verified due to lack of documentation and workspace
  files"*), which is the right epistemic move and also the one that costs
  it points. The blind critic's ceiling on evidence-dependent tasks is
  now that hedge, not the format confusion. Evidence:
  `2026-08-11-sa1-{14b,7b}-critique-suite-{before,after}.jsonl`.
- **RB-P5 — the 4b `full` watch item stayed red.** The two
  `nav-release-bundle` `critique-exhausted` rows (seeds 3590861830 and
  2248991587) reappear field-identical to the seeded bar-noreg cell. The
  trigger recorded in the contract-robustness calibration below — "if the
  cell stays red, the attack is rubric feedback wording (Layer 2), not
  gate mechanics" — has now fired. **Attack:** as written there, ~~jointly
  with RB-P4~~ — **the "jointly with RB-P4" half is RETIRED 2026-08-11**,
  see the retirement note in the RB-P4 bullet above; the two are separate
  defects and the fix below moved this one alone.

  **Outcome (2026-08-11, RP2 probe + RP4d fix — the original hypothesis
  REFUTED, a different defect found and FIXED):**

  This was never a format-conflict case, so the "same family as RB-P4"
  framing that routed it here was wrong twice over. What the transcripts
  show: `qwen3:4b-instruct` answered `imgproc-cli-0.1.0.tar.gz` (expected
  `2.9.1`) **having never called `read_file(VERSION)`** — a hallucination,
  and the grounded critic caught it *correctly* at 4/10 with untruncated
  429-byte evidence. The critic was right. The defect was that the retry
  made the answer **worse**: told the version is not present in the
  evidence, the model edited its own string to `imgproc-cli-*.tar.gz` and
  then `imgproc-cli-<version>.tar.gz`, generalising away the gap instead
  of closing it, and burned all three rounds.

  Two controls pin the diagnosis to the retry verb rather than the
  critic: the control seed 4264928414 responded to the same feedback
  *class* by issuing `read_file(VERSION)` and passing; and the same model
  and seed under non-grounded `critique` passes at round 1, because there
  the feedback says the answer is "missing the required content entirely"
  rather than pointing at the string.

  Fix: `1cf5210` (Contract, `assets/contracts/default.yaml`, the
  `critique_feedback` tail only). "Revise and answer again." — a verb that
  points the answerer at the string it just wrote — becomes an instruction
  that names the missing-evidence case and its remedy: if a value is
  missing, unverified, or absent from the evidence, that is a fact you
  never looked up; call your tools and read the source, and do not reword,
  generalise or hedge around it. `grounded-completion.yaml` was
  deliberately left untouched so the critic's round-1 verdict stays
  byte-stable across the arms and the retry wrapper is the only variable.

  Bar, `qwen3:4b-instruct` / `nav-release-bundle` / `--config full
  --repeats 3`, before-arm from a clean tree at `9f614ad` so
  RP4a/RP4b/RP4c sit in both arms — **1/3 → 3/3, control held**:

  | seed | before | after |
  |---|---|---|
  | 3590861830 | `critique-exhausted`, 3 rounds, 6,267 tok | **pass**, 1 round, 4,834 tok |
  | 2248991587 | `critique-exhausted`, 3 rounds, 6,416 tok | **pass**, 1 round, 5,041 tok |
  | 4264928414 (control) | pass, 1 round, 4,768 tok | pass, 1 round, 4,878 tok |

  All three after-transcripts show the identical repair path: hallucinated
  `0.1.0` → verdict → `read_file(VERSION)` → `2.9.1` → correct bundle
  name. Blast-radius check on the 14b `critique` cell: unmoved, 0/3, last
  feedback byte-identical per seed, at a cost of +165 tokens per run — the
  length of the added wording. `test_layers.py::GOLDEN_CRITIQUE` was
  updated deliberately with the reason recorded in the file. Evidence:
  `2026-08-11-rp4d-4b-nav-release-bundle-{before,after}.jsonl`.
- **RB-P6 — 7b's store-config token bill is 3× the 4b bill for a lower
  score.** `memory` 169,452 and `lean` 169,319 against 4b's 55,525 /
  56,289 (3.0×) at 56–57/66 vs 59/66; `full` 222,105 vs 111,382 (2.0×).
  Ten of the model's eleven `turns-exhausted` runs are store-config recall
  at 10.4–11.6k tokens each, with `recall-org-quota` exhausting twice in
  every store config. This is the LoopGuard target population, and the
  lg-* calibration already measured held-answer loop conversion at −38%
  tokens on exactly this model and task family. **Attack:** LoopGuard's
  pending cross-model promotion sweep — this re-baseline is the "before"
  it was waiting for. (Policy + composition.)

  **Outcome (2026-08-11, RP6 — promotion HELD, scoped to 7b and 3b):**
  the paired sweep ran, and `memory-guarded` stays calibration-only. 4b
  and 14b were not run, so nothing below is a claim about them.

  The before-arm is *not* the re-baseline row above: this branch already
  carries RP4c's recall `k`-floor and batch isolation, which attack the
  same population, so `--config memory` was re-measured at branch head
  against the same server and the same seeds
  (`2026-08-11-rbp6-{7b,3b}-memory-before.jsonl`). Staleness measured:
  7b `memory` moved 169,452 → **164,624** at 56 → **57**/66, and all
  three `turns-exhausted` rows came back *field-identical* to the
  re-baseline. RP4c did not touch this loop population on 7b — so the
  headroom question is answered by the guard's own arms, below. A
  control matters here: a second identical `memory` arm reproduced the
  first **byte-identically on all 66 rows**, so the noise floor is zero
  and every changed row below is the guard, not sampling.

  | model | score | tokens | turns-exhausted | rows changed |
  |---|---|---|---|---|
  | 7b `memory` → `memory-guarded` | 57/66 → **59/66** | 164,624 → 162,593 (**−1.2%**) | 3 → **1** | 8/66 |
  | 3b `memory` → `memory-guarded` | 22/66 → 22/66 | 70,581 → 69,398 (−1.7%) | 1 → 1 | 3/66 |

  Flips, paired per seed, both directions: 7b **+2 / −0** —
  `recall-audit-retention` (seed 775726587) `turns-exhausted` 11,106 →
  **pass** 8,211 and `recall-org-quota` (seed 1883253963)
  `turns-exhausted` 11,063 → **pass** 9,515. 3b: **zero flips either
  way**; its three changed rows are `nav-prod-port` ×2 and
  `shop-compare`, all `wrong-answer` before and after, ~−1.2k tokens.
  No row anywhere flipped to failing under the guard.

  The bar was written before the numbers were read: no score regression
  on either model; suite tokens **−10% or better on at least one** model
  with the other no worse than +5%; `turns-exhausted` not up; and no
  pass→fail flip outnumbering the fail→pass flips. Score, exhaustion and
  flip discipline all cleared. **The token bar missed by roughly 8×** —
  −1.2% and −1.7% against −10%. That is the finding: the v0.12.0
  −37.7% was measured on a *two-task probe cell*, and it does not
  survive dilution to a 66-row suite, because the guard only ever
  touches the 8 rows (7b) and 3 rows (3b) that actually loop. The
  per-row conversion replicated exactly; the suite-level economics did
  not, and quoting −38% as a sweep number would have been wrong.

  Honest negative, and the reason the third exhaustion survives:
  `recall-org-quota` (seed 2178735184) stays `turns-exhausted`, and a
  transcript repro shows the note **does** fire at streak 3 and the run
  exhausts anyway. It is an *absent*-answer loop — the model never
  recalls the seeded fact, it re-`memory_save`s its own invention under
  drifting names — which is exactly the v0.12.0 limitation ("injection
  converts held-answer loops, not absent-answer ones") reproducing at
  sweep scale. Its own drifting names also break the identity streak,
  so the guard fires late and only once.

  **Trigger conditions to revisit (numeric, either route is sufficient):**
  - *Promote `memory-guarded` as a 9th headline config* — it must earn
    a permanent extra suite pass per model. Requires ≥ **−10%** suite
    tokens versus `memory` at equal seeds on at least one model, no
    model worse than +5%, and no score regression. Measured this round:
    7b −2,031 tokens; the trigger needs ≥ **16,462** on 7b.
  - *Fold LoopGuard into the `memory` headline config instead* — the
    cheaper change, and the one the +2/−0 flip record actually
    supports; it buys the score with no new column. Requires the paired
    arms on the two models this unit was scoped out of: **4b** and
    **14b**, each with score after ≥ before and **zero** pass→fail
    flips, plus 7b's +2 replicating. 4b was byte-identical under the
    guard in v0.12.0 (a no-op, so cost-free); **14b is unmeasured and
    is the real gate**. Folding also changes the meaning of an existing
    headline cell, so it needs its own before/after on record.

  Evidence: `2026-08-11-rbp6-{7b,3b}-memory-{before,guarded}.jsonl`,
  seeded by `run_seed(model, task, repeat)` and therefore paired
  cell-for-cell across configs.
- **RB-P7 — 3b's store rescue ceiling is unchanged at 5–6/27.** The
  `memory` recall cell splits 5 pass / 19 `wrong-answer` / 2
  `malformed-output` / 1 `turns-exhausted`, field-identical on all 27 rows
  to the seeded bar-p1 cell. Not a new problem — the point is that it
  re-confirms at sweep scale: the P1 coercion fix is fully banked and the
  remaining ceiling is prose pseudo-calls plus synthesis failure.
  **Attack:** unchanged from the P1 residue list below; this sweep adds no
  evidence that would reprioritize it.

  **Status after round 1 (2026-08-11): UNTOUCHED.** Not in the job's
  scope; nothing was probed, measured or changed on 3b's rescue ceiling.
  Note that RP4c's `k`-floor (RB-P1) is a Core change on the recall path
  and *could* move this cell — it was not re-measured on 3b, so the
  5–6/27 figure above is now a pre-`4761109` number and any re-quote of
  it is **directional** until the cell is re-run.
- **RB-P8 — 4b `grounded` burns 11 `critique-exhausted` runs on tasks that
  cannot produce evidence.** Ten of the eleven are storeless
  `memory-recall` (`recall-env-endpoint` ×3, `recall-audit-retention` ×2,
  `recall-cache-ttl` ×2, plus deploy / db-port / org-quota), where the
  critic *correctly* refuses to bless an evidence-free answer — honest
  verdicts, pure token waste, and a visible part of `grounded`'s 102,656
  tokens. **Attack:** composition policy — don't attach an
  evidence-demanding critic to tasks whose config provides no evidence
  path. Cheap guard, measurable as token savings at unchanged score.

  **Outcome (2026-08-11, RP4e — FIXED at Composition):** the guard
  landed as `f3b2d07`. A `memory_setup` task keeps its answer in a store;
  `grounded` attaches no store and no tools; so `source_withheld` is true
  and the gate is simply not attached. `full` never trips it, because a
  `memory_setup` task under `full` always gets its store.

  **Composition was chosen over Library, deliberately.** The cheaper-looking
  fix — degrade `GroundedCritiqueGate` to pass through on an empty evidence
  set — would make every consumer's grounded gate defeatable by calling no
  tools, which is precisely the thing it is attached to prevent. The critic
  is behaving correctly here; the *recipe* that pairs a source-checking
  critic with a task whose source it withheld is what is wrong, so the
  recipe is what changed.

  Bar, 4b `grounded` × memory-recall, 27 runs — **−97.2% tokens at
  unchanged score**:

  | | before | after |
  |---|---|---|
  | tokens | 53,929 | **1,520** |
  | model calls | 132 | 27 |
  | critique rounds | 55 | 0 |
  | score | 0/27 | 0/27 |
  | outcomes | `critique-exhausted` ×16 + `wrong-answer` ×11 | `wrong-answer` ×27 |

  **Note the exhausted count: 16, not the 11/10 recorded in this bullet.**
  The bullet's figure came from the 2026-08-10 re-baseline
  (`2026-08-10-rebaseline-4b.jsonl`: 10 exhausted in this family, 46,293
  tokens); the before-arm above is branch head `625cfe5`, where RP4c and
  RP4d are already in, and the population had grown. The problem was
  bigger than it was written down as.

  Controls, both byte-identical across the arms: 4b `grounded`+`full` on
  structured-extraction, 30 runs, 15/15 each at 21,478 tokens; 4b
  `grounded` on file-nav, 6 runs, 6/6 at 23,846 tokens with
  `critique_rounds == 1` on every run — the critic objects once, the
  answer changes, the run is rescued. Evidence:
  `2026-08-11-rp4e-4b-memory-recall-grounded-{before,after}.jsonl`,
  `2026-08-11-rp4e-4b-{extract,file-nav-grounded}-control-{before,after}.jsonl`.

  **Semantics change, not a bugfix in the numbers** — see change 3 in
  [Reporting-semantics changes](#reporting-semantics-changes-2026-08-11-v0140).

  **Deliberate scoping, recorded so it is not mistaken for coverage:**
  toolless `structured-extraction` tasks also reach the critic with an
  empty evidence set and they **keep** the gate. Their source is the task
  prompt, they burn zero exhausted runs, and no confirmed finding said to
  touch them, so extending the guard there would have been a speculative
  semantics break. The same structural mismatch is nonetheless present and
  may bite on a model whose critic is less lenient about "(no tool calls
  were made)". **Attack if it ever does:** widen the guard from "source
  withheld" to "no evidence path at all", with a measured before/after on
  the extraction family. Related: `source_withheld` keys on `memory_setup`
  alone, so a future task combining `memory_setup` with workspace tools
  under `grounded` would drop the critic despite having real evidence. No
  such task exists today.
- **RB-P9 (measurement note) — 3b's storeless configs drift −1 to −5
  against the unseeded 2026-08-09 sweep on identical task code**
  (`graph` 19→14, `critique` 17→14, `structured` 18→17, `bare` 14→13).
  Unseeded-versus-seeded means this is *not* interpretable as a
  regression: it is the size of the sampling-variance bar the old 3b
  numbers silently carried, measured. From this re-baseline forward all
  four models have seeded baselines, so this class of ambiguity ends
  here — which is also why every pre→post comparison above is labelled
  directional.

  **Status after round 1 (2026-08-11): UNTOUCHED.** Nothing was probed,
  measured or changed. It is a standing measurement note rather than a
  defect, and round 1 leaned on it twice — the RB-P1 headline and the
  pre-queue 23/27 it rests on are exactly this ambiguity, and are labelled
  directional for exactly this reason.

#### New measured problems from round 1 (2026-08-11)

Found while attacking the block above; none of them is fixed, and each
carries an attack direction rather than a re-scoped claim.

- **RB-P10 — `memory_save` without a `name` leaks a raw Python
  `TypeError` into a model-facing observation.** The model sees
  `Memory.save() missing 1 required positional argument: 'name'` — an
  implementation detail of the handler's signature, in the place where a
  schema-shaped error belongs. Observed burning turns in both of the 14b
  failures that survive RP4c (`recall-env-endpoint` and
  `recall-org-quota`; transcript evidence, and the rows themselves are in
  `2026-08-11-rp4c-14b-memory-recall-after.jsonl`). **Attack:** the
  argument-boundary layer that already owns `coerce_arguments` should
  reject a call missing a `required` property with a message that names
  the field, instead of letting the handler's signature speak. (Contract,
  Layer 2, plus the Core boundary that calls it.)
- **RB-P11 — no task in the suite carries both a `schema` and `tools`, so
  the tools-plus-`response_format` combination is unit-tested but has
  never been measured against a real server.** RB-P3's fix makes this
  reachable in `lean` and `full` for the first time. Unit tests pin that
  tools still travel alongside a constrained call; nothing measures
  whether a server honours both at once. **Attack:** a probe cell before
  any schema task gains tools. Frozen-suite rules put the task change in
  the next suite version. (Transport + Measurement.)
- **RB-P12 — the `structured` config's `schema-exhausted` transcripts
  still record `messages: []`.** Change 4 in
  [Reporting-semantics changes](#reporting-semantics-changes-2026-08-11-v0140)
  fixed this everywhere an agent loop owns the transcript;
  `structured` drives its own loop with no agent, so it is the one
  remaining blind spot. Deliberately left — no probe finding asked for it —
  and pinned by
  `test_gate_raised_transcript_stays_empty_without_an_agent_loop` so it
  cannot rot silently. **Attack:** give the one-shot loop a transcript of
  its own shape, or route it through the agent. (Core.)
- **RB-P13 (ledger honesty, not a product defect) — two intermediate
  commits on `feat/rbp-round-1` are red in isolation and two commit
  bodies misdescribe their tests.** `4a8b816` fails 3 tests and
  `670d8ca` fails 4 when checked out alone, because `4a8b816`'s
  `test_evalrun.py` edits assert behaviour of both later commits and
  `670d8ca` lands `51c6594`'s counting tests a commit early; `51c6594`'s
  body then calls a test "(new)" in a commit that touches only
  `critique.py`. Everything from `51c6594` onward is green and the branch
  head is unaffected, but bisectability is broken across those two
  commits and the "failing before / passing after" lists in those bodies
  are not accurate as committed. History was **not** rewritten — in a
  project whose method is claims-verified-by-evidence, an inaccurate
  evidence list is worth recording rather than editing away. **Attack:**
  none needed beyond the discipline itself — land tests in the commit
  whose behaviour they assert.

### Measured problems → attack plan (P1–P9, previous sweep)

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
    transcripts. Stable cells identical in every field but the config
    label. Honest negative: the
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
    **identical in every field but the config label on all 66 rows**
    vs the seeded 59/66 @ 55,525 memory cell — the guard was silent
    everywhere, exactly as the probe predicted (4b max streak ≤ 2),
    and a fired injection would itself have been a finding.

  v1 limitations, documented and pinned by tests: observations from
  raising handlers and unknown tools cannot streak (the wrapper resets
  on a raise — no false "identical" claim the transcript contradicts);
  under `graph-guarded`, collapsed repeat reads embed the graph's
  `read #N` marker and so never streak — the guard fires via the other
  tools, and it hashes what the model sees (graph markers included).
  LoopGuard stays out of the headline configs pending a cross-model
  sweep. **That sweep ran (RP6, 2026-08-11) on 7b and 3b and the hold
  stands** — the per-row conversion replicated, the −37.7% did not
  survive dilution to the full suite (−1.2% / −1.7%). Numbers, bar and
  trigger conditions under RB-P6 above; these probe-cell percentages
  are not suite percentages and must not be quoted as such.
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
