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

### Crediting a rubric edit (2026-08-12)

Two standing rules already say what a number here is allowed to mean: the
**suite is frozen** before measuring (a model that fails a task or rubric is a
data point, not a bug — nothing under `assets/evals/tasks/` is tuned mid-cycle),
and **runs are seeded**, one seed per (model, task, repeat), quoted with the
result. This is the third, and it is the one that has already been broken:

> **No edit to a rubric or to a critic-facing contract string may be credited
> with moving a cell until the perturbation bar has been run on that cell and
> reports the family as non-fragile.** Not "should be run" — *credited* means
> the sentence "this change moved this cell" may not be written, in this
> document or in a PR body, without that run committed beside it.

Run it before the attribution, not after the argument:

```bash
.venv/bin/python -m bantamkit.criticreplay \
  --rubric before=git:<ref>:assets/rubrics/<name>.yaml \
  --rubric after=assets/rubrics/<name>.yaml \
  --transcripts <the bar's --transcripts dir> \
  --base-url http://localhost:11434/v1 --model <model> \
  --json docs/eval-data/<date>-<label>-perturbation.jsonl \
  --summary docs/eval-data/<date>-<label>-perturbation-summary.json
```

**Read the exit status first — it is machine-readable and the three fields
below are not.** Since RB-P24 closed (2026-08-12) this command exits `3` when
guard 2 fired on a (point, cell) it actually replayed, `1` when it did not
complete a measurement, `2` on a usage error, `4` when it measured but could
not write the summary file, and `0` when it measured and the guard fired on
nothing. A `3` is not a failed run: every artifact is written, and it says the
GUARD section below the table has to be read before an attribution is
credited. A `1` is not a promise that nothing was written — the `--json` sink
flushes per row, so an aborted run leaves partial rows behind; treat any
artifact from a `1` as partial. `--violations-exit-zero` is the named opt-out
from `3` alone, for a procedure whose violations are expected and recorded.
Full contract: RB-P24 under "New measured problems from the perturbation bar
(2026-08-12)".

Read three fields per cell, in this order:

1. **`fragile`** — if `true` for either variant, stop. The family's scores
   straddle the rubric's own threshold, so the cell cannot carry an
   attribution at all and no verdict below it means anything.
2. **`verdict`** — `distinguishable` requires `F/F` against `0/F`. Anything
   else, including a large and consistent `inconclusive`, is not a separation.
3. **`attributable`** — the two above, combined. `false` means the claim does
   not get written.

Cost is why this is a rule and not a suggestion: **≤ 96 requests and about
three minutes** for a two-variant before/after on a 3-seed cell — measured at
93 requests and 35,523 tokens on the RB-P14 cell, which is **25%** of the
143,711 tokens the 14b before+after suite arms behind RB-P4 cost, with no
answerer, no tools and no suite run. A cycle in a hurry can afford it.

It exists because the alternative was measured. RB-P4's structural rubric edit
cleared a pre-registered bar, two no-regression arms and an independent
reviewer — and then a **deleted trailing newline** reproduced its entire pass
signature. Run against that history the bar returns `A-asfiled` `fragile: true`
on all three cells, passing 1/12, 4/12 and 3/12 of its *own* meaning-preserving
family, and `attributable: false` on every pair: the attribution could not have
been stated through this instrument. The tool supplies the bar; this rule is
what makes it get run.

**Where it currently stands: `nav-prod-port` on 14b is fragile, so no rubric
edit is creditable on that cell today.** Fixing that means finding a cell whose
family does not straddle the threshold, not re-running until the number is
liked. The bar is also RB-P15's standing check with `--identity-only`. The
search for a cell where it *is* creditable is the next section.

**The standing no-regression floor is
`docs/eval-data/2026-08-12-nonfragile-anchor-set.json`** — 12 cells whose
family is non-fragile under the as-filed rubric, so a rubric or critic-prompt
edit that moves any of them has broken something that was stable. Run it before
proposing an edit. It is a **floor, not an instrument**: green there is not a
credit, it only means nothing stable was broken, and its own file carries the
three caveats that bound it.

### The non-fragile screen and the standing anchor set (2026-08-12)

Pre-registered at `docs/eval-data/2026-08-12-m1-screen.md` and committed before
the first request went out (screen commit `3b3d7f7` 11:35:55, first arm
evidence 11:40:32 — the ordering is checkable in the log and was checked).
**132 cells screened at identity** — 22 tasks × 3 repeats × `qwen2.5:14b-instruct`
and `qwen3:4b-instruct` — of which **20 were characterised over the full
12-point perturbation family**. Cost **452 critic requests / 204,982 tokens**
against a registered cap of ≤ 628 critic requests / ≤ 286,785 tokens — 71.5% of
budget, 18.2 min against ~22 predicted. The token figure is the whole job:
159,349 across the four critic arms (23,735 + 21,981 identity, 79,812 + 33,821
family) plus the 45,633 the answerer spent in stage 0. `wire_calls == requests`
on all four arms and per-row tokens sum exactly to each summary total, so there
are no unlogged requests. Every claim below was independently re-derived from the committed
JSONLs by a reviewer who did not run the screen; the catalogue reproduced with
zero mismatches on all 20 cells and all 132 ground-truth flags. One thing that
review did **not** catch: the screen's shared-token guard table is **one of two
defensible readings of §3.3, not an error**, and every re-derivation of it up to
that point had inherited the method of the one before it, so each raised
confidence while adding no independence. It took a reviewer *forbidden from
importing the module* to surface the ambiguity at all, and an independently
written tokenizer to find a false negative that both readings shared (deviation
7, and RB-P19, where all four derivations are laid out side by side).
**RETRACTION (2026-08-12):** this paragraph originally said the table "is
wrong" and that re-deriving it by the screen's own method "reproduced the error
rather than exposing it". Withdrawn — the catalogue's numbers were sound and so
was the table; what was not sound was stating a contested reading with a
confidence the method could not support.

#### The headline, stated so it cannot be misread

The pre-registered target was a **defect bar**: a cell that is non-fragile *and*
where the critic robustly scores a correct answer below threshold — the RB-P4
shape. Stratum D1 was given the largest cap of any stratum. **Its pool is
zero, across all 132 cells.**

The closure is stronger than "none sampled". The shape requires family
`max < 7`, hence identity `< 7`. Of the 132 cells, 66 carry a correct answer;
**63 of those sit at identity ≥ 7 and are ruled out outright by stage 1**, not
merely unsampled. The remaining three are 14b `nav-prod-port` r0/r1/r2, all at
identity 5, and all three came back **fragile** (1/12 committed for r0 from the
RB-P14 run; 4/12 and 3/12 measured here for r1 and r2). There is no cell at
identity 6 with a correct answer anywhere on the suite.

**What that sentence does and does not license.** It is tempting to write "the
RB-P4 shape is reproducible nowhere on this suite". *Do not.* That is true only
under the pre-registered technical definition — non-fragile **and** `0/F`
**and** correct — and false under the plain reading of the same words. The
defect itself reproduces perfectly well:

- **3/3 under `bare`**, all three pinned seeds, a correct `{"port": 9443}`
  (`2026-08-12-m1-bare-14b.jsonl`, seeds 2331795949 / 4094558621 / 634446002);
- **3/3 under `critique`**, all three `critique-exhausted`, on already-committed
  evidence from two days earlier (`2026-08-10-rebaseline-14b.jsonl`, same seeds).

**What is absent is a *non-fragile instance*. Fragile is not absent.** That
distinction carries the whole decision: "no rubric work is measurable here" is
what the first phrasing implies and it closes the file; "the one cell that
exhibits the defect is too noisy to carry an attribution *yet*" is what was
measured, and it names the thing to attack. The screen did not find that
RB-P4 is unreal. It found that RB-P4 has no instrument, which is what RB-P14
already said, and it added the reason: the cell sits two points under threshold.

**A consequence for round 2 that has to be said out loud.** Round 2's rubric
rewording was withdrawn as *measured harmful* on the strength of **this same
cell**. Under this document's own crediting rule, that harm verdict is no
better supported than the verdict it replaced — both were read off a family
now committed at 1/12, 4/12, 3/12 of itself. **The change stays withdrawn**;
nothing here re-credits it, and no evidence has been produced that it helped.
What changes is the label: its effect is **unmeasured**, not **known-bad**. A
withdrawal is cheap and reversible; a false "we measured this and it hurt"
entered into the record is neither.

#### What the 20 cells are

| verdict | cells | where |
|---|---|---|
| **anchor** — non-fragile, critic right | 12 | 8 robust accepts (`12/12`, min 9–10 vs T=7), 4 robust rejects (`0/12`, max 0–2) |
| **fragile** | 5 | all five on 14b: `nav-prod-port` r1/r2, `recall-db-port` r2, `recall-env-endpoint` r0, `recall-deploy` r2 |
| **defect-bar candidate, refused** | 3 | 14b `recall-cache-ttl` r0, 4b `nav-prod-port` r1, 4b `recall-audit-retention` r0 |

The three refusals are all false-*accepts*, and all three were declined for the
same reason: **the correct answer is absent from the critic's own inputs.**
Only `{task}` and `{output}` reach it — no `memory_setup` store, no workspace,
no tool trace, verified per cell against `render_prompt`'s actual
interpolation. 14b `recall-cache-ttl` r0 answers `300` where the expected 240
lives in a store `bare` never attaches; 4b `recall-audit-retention` r0 answers
90 against 400, same shape; 4b `nav-prod-port` r1 answers 9499 against 9443,
which lives in a workspace the critic never sees. **A critic that cannot know
an answer is wrong is not committing a rubric defect by accepting it**, so
scoring these 9–10 is not something a rubric edit could be credited for moving.

#### Finding — robust verdicts are decided by the answer's *form*

Across all 15 non-fragile cells, without exception:

- **11 robust accepts** are all well-formed and non-empty — 8 of them correct
  and **3 of them wrong** (the 3 refused candidates above). Form, not
  correctness, is what all eleven have in common.
- **4 robust rejects** are all empty or malformed: `{"name": ""}`,
  `{"port": 94oire}`, the empty string, and a stray tool-call fragment.

So the *direction* of a robust verdict is predicted by the answer's form. This
holds on 15/15 and it is why the anchor set below is the shape it is: eight
accepts of well-formed text, four rejects of garbage.

#### Retired claim — "the critic is stable exactly where it does not have to judge correctness"

The screen's own report went one step further and concluded that the critic
*wavers precisely where it must judge correctness*, and drew from that an
attack direction of "no rubric edit can help; give the critic the source or
change what it does under unverifiable input". **That second half is retired.
It is contradicted by the feedback strings committed alongside it.**

Every sub-threshold row on all five fragile cells was read
(`2026-08-12-m1-family-14b.jsonl`):

| fragile cell | sub-threshold points | what the critic actually complained about |
|---|---|---|
| 14b `nav-prod-port` r1 | 12 of 12 | **format**, zero content |
| 14b `nav-prod-port` r2 | 13 of 13 | **format**, zero content |
| 14b `recall-db-port` r2 | 2 of 2 | **format** |
| 14b `recall-env-endpoint` r0 | 1 of 1 | **provenance** |
| 14b `recall-deploy` r2 | 12 of 12 | genuine correctness dispute |

**In four of the five fragile cells the critic never judged correctness at
all.** And on the two `nav-prod-port` cells the complaint is not merely
off-charter, it is *false about the answer in front of it*. The answer is
`{"port": 9443}`. The task demands `Answer with ONLY this JSON, nothing else:
{"port": <number>}`. The answer is correct, and is already in the demanded
format. The critic writes:

> "The answer format should be {'port': number} not just the port number"

> "Answer should be in format {\"port\": <number>}, not {\"port\": 9443} without
> JSON structure. **Correct answer format wasn't followed but required content
> was identified correctly.**"

The second string names its own error: it grants the content is right and
deducts anyway. It also quotes the answer back verbatim as the counter-example
to a format the answer *is*. This is a hallucinated defect, not a judgement
call. The same string is in the already-committed re-baseline two days earlier
as the terminal `CritiqueExhausted` feedback on the same cell, so it is not an
artifact of the replay harness.

And this is exactly what the rubric forbids, in its own words
(`assets/rubrics/task-completion.yaml`, unchanged blob
`ab8886fe1ce62c3a9e2331469a48b7e471414b5e`):

> Judge ONLY whether the information the task asks for is present and correct.
> **Do NOT deduct points for formatting**, phrasing, extra surrounding text,
> hedging, or verbosity.

**The retired claim also fails as a predictor even where it describes.** Two
cells, both well-formed, both wrong: 14b `recall-cache-ttl` r0
(`{"seconds": 300}`) is **12/12 non-fragile**, and 14b `recall-db-port` r2
(`{"port": 3307}`) is **10/12 fragile**. Same form, same correctness status,
opposite verdicts. Form predicts the *direction* of a robust verdict **when one
exists**; it does not predict *whether* one exists. On a sample of 20, "the
critic had to judge correctness here" was doing unfalsifiable post-hoc work.

#### The live attack direction this reopens

The unstable axis is **format-compliance judgement the rubric does not ask for
and explicitly prohibits**, applied to answers that already comply. That is a
rubric-addressable defect, and it is the one RB-P4 was chasing all along.
Filed against RB-P4 below as the third and only unexhausted direction, with the
target stated in advance: **12 of 12 and 13 of 13 of that cell's failing points
are format complaints**, so an instruction that suppresses format deduction has
a directly measurable surface, not a plausible story.

Two things this does *not* license, both binding:

1. It is **not** a licence to write the edit and credit it. `nav-prod-port` on
   14b is fragile, so the crediting rule still refuses the attribution. What
   changed is that there is now a live hypothesis with a named target; the
   instrument is still missing.
2. The anchor set below **cannot** measure it — see caveat C2 there.

#### The anchor set — a floor, and named as one

`docs/eval-data/2026-08-12-nonfragile-anchor-set.json` — **the first committed
no-regression set the project has.** Twelve cells whose family is non-fragile
under the as-filed rubric: eight robust accepts of correct answers (`12/12`,
score min 9–10 against threshold 7) and four robust rejects of wrong ones
(`0/12`, max 0–2). Every cell carries its model, task, repeat, seed, answer
bytes, answer sha256, family pass rate, min/max and transcript path. 192
requests, ~74k tokens to re-run.

**Its status is `FLOOR, NOT INSTRUMENT`, and its three caveats live inside the
file** — as `caveats[]`, not in this prose, so a future cycle that reads the
artifact and skips the document still meets them:

- **C1** — `shop-compare` r2's `answer_correct: false` comes from `tool_trace`,
  not from the answer text the critic reads. It is a valid robust reject of a
  malformed answer; it is not evidence the critic judged correctness, and it is
  the weakest of the twelve.
- **C2** — the 12 cells reduce to **9 distinct answer texts**. The accept side
  is 8 cells / 5 distinct texts / 3 tasks / **one family**
  (`structured-extraction`; three 14b `extract-contact` cells share
  byte-identical output), and the reject side is empty-or-malformed garbage.
  **Nothing on the accept side exercises `file-nav` or `memory-recall`** —
  near-zero coverage of the format-deduction mode above. Filed as RB-P21.
- **C3** — passing all 12 is **necessary and nowhere near sufficient**. It
  proves an edit broke nothing stable. It says nothing about whether the edit
  moved the cell it was written for; that still needs the perturbation bar on
  *that* cell reporting its family non-fragile.

The strongest single cell is 14b `extract-contact` r2: a correct answer wrapped
in prose *and* a code fence, accepted 12/12. It pins a **named directive** of
the rubric — "Do NOT deduct points for formatting, phrasing, extra surrounding
text" — so an edit that breaks it breaks something the rubric explicitly
promises. That is also the directive the format-deduction attack has to
strengthen without breaking, which makes this cell the attack's own guard rail.

#### Deviations, amendments and limits — recorded, not smoothed

1. **Unregistered C-stratum substitution.** §4 of the screen selects control
   cells as the two lowest-scoring of stratum N, ties broken `(task asc,
   repeat asc)`. Applied to the committed stage-1 scores that rule selects
   14b `nav-prod-port` **r0 and r1** (three cells sit at identity 5, so the tie
   break decides). What ran was **r1 and r2**. Nothing disclosed it. The
   conclusion survives — r0's family is committed at 1/12 from the RB-P14 run,
   `min 0 / max 9`, fragile, and r1/r2 reproduce that shape at 4/12 and 3/12 —
   but the substituted-out cell is the project's canonical RB-P4 cell, dropped
   from the one stratum the screen itself calls "the point of the exercise".
   A pre-registered screen that silently drops its most load-bearing cell has
   to say so, whether or not the answer changes.
2. **The refusal criterion is a post-hoc amendment.** "The critic cannot see
   the ground truth, so accepting a wrong answer is not a rubric defect" is
   sound and is adopted. It was **not pre-registered**, and it was applied only
   to the defect-bar side. Applied consistently it also questions the anchor
   side: `shop-compare` r2's `correct=False` is likewise invisible to the
   critic, since it comes from `tool_trace`. Recorded as caveat C1 rather than
   used to drop the cell, because its 0/12 is real and its reject is right for
   a reason the ground-truth flag does not encode.
3. **The 4b arm does not corroborate the fragility result.** Its identity
   distribution is bimodal — 59 cells at 10, 6 at 0, 1 at 4, **nothing in
   5–9** — so stratum N is empty, no control cells ran, and all five fragile
   cells are 14b. 4b structurally cannot exhibit the near-threshold behaviour
   that produced every fragile cell in the catalogue. The two-model framing
   therefore adds much less independent support than it reads as. Filed as
   RB-P22.
4. **"No third case" is a one-way implication, not an identity.** §1 of the
   screen argues non-fragile ⟺ pass rate exactly `0/F` or `F/F`, and uses that
   equivalence to call the two cell kinds exhaustive. Only the forward
   direction holds: non-fragile (`min ≥ T` or `max < T`) does force `F/F` or
   `0/F`. The converse does not — a family could in principle score all-pass
   with a `min` below `T` under a different pass predicate. Nothing in the
   catalogue turns on it (`criticreplay._family_stats` defines both from the
   same min/max), but the argument as written is stronger than the definition.
5. **The pre-screen heuristic failed and is retired by its own criterion.**
   "Far from threshold ⇒ likely non-fragile" scored 70% vs 50% on 10 and 4
   cells — no signal. Its failure is concrete rather than statistical: it
   **would have discarded two confirmed anchors** (14b `extract-contact` r2 and
   `extract-invoice` r0, both identity 9, both 12/12) drawn from the single
   largest identity block on the model — 38 of 66 cells sit at identity 9, two
   were sampled, and both were anchors. §4 pre-registered the failure condition
   ("if any control cell comes back non-fragile the heuristic leaks and is
   reported as failed") and it fired as written. 132 requests / 45,716 tokens
   for a rule that points away from the best anchors. **Replacement: stratify
   by answer *form*,** which is what the surviving half of the mechanism
   finding says actually predicts a robust verdict.
6. **The `--identity-replays 1` deviation is validated, and was registered
   before stage 1** — it is in the pre-registration commit itself. All 20
   stage-2 cells: stage-1 identity score equals all five R=5 replays, 100/100,
   zero within-cell spread.
7. **Guard violations changed no verdict — and the guard rule turned out to
   have two readings, so the screen's table is one of them, not an error.**
   The screen recorded 5 affected cells against §3.3's *whole-text* reading —
   the symmetric difference of the base and perturbed TEMPLATE word sets,
   which is the spec's operative Test sentence. Recomputed over all 22 frozen
   task prompts under the *substitution-pair* reading — the symmetric
   difference of each point's own `from`/`to` strings, which §3.3 step 4 and
   the manifest's P2 prose imply — the figure is **8 of the 20**, because
   `for` leaves the P2 instance while surviving elsewhere in the template.
   Both readings are defensible and the user ruled (2026-08-12) that both are
   computed and reported and neither is wrong.

   > **RETRACTION (2026-08-12).** This item originally read "the guard
   > analysis itself was wrong, and is corrected here", and said the screen
   > "got `P2-asks-requests` wrong in both halves" and that "`requests`
   > violates nowhere". **Withdrawn.** `requests` does violate on
   > `recall-org-quota` — it was hidden by a tokenizer that treated the hyphen
   > in "requests-per-minute" as word-internal, which was a separate false
   > negative, since fixed. The screen's row was the whole-text reading and it
   > was right about it.

   On all eight cells the fragility verdict is identical with and without the
   violating points under either reading, so **no conclusion here rests on a
   guard-violating point**. Both tables ship machine-readably in
   `docs/eval-data/2026-08-12-rbp19b-guard2-both-readings-22-prompts.json`.
   Full treatment under RB-P19 below.
8. **Coverage, stated plainly as not exhaustive.** 2 of 4 models (`llama3.2:3b`
   and `qwen2.5:7b-instruct` unscreened); 132 of 264 possible cells at
   identity; 20 of 132 at full family (15%); on 14b, 4 of 43 near-band cells
   and 2 of the 38-cell identity-9 block. **One rubric variant only**, so no
   attribution claim is possible here and none is made. Answers come from
   `bare`, so these are the critic's round-0 decisions.
9. **Two predictions are recorded as wrong rather than smoothed.** 14b latency
   ran 2.50 s/request at stage 2 against 1.95 budgeted (stage 1 hit 1.95
   exactly — perturbed prompts are longer than identity, so the spec's warm
   figure understates a family run). And **D1 being empty was not anticipated
   at all**: it was given the largest cap of any stratum and none of it was
   spent.

One thing the budget bought for free: stage 0 was budgeted from the *measured*
`bare` totals of the 2026-08-10 re-baseline rather than from an estimate, and
the seeded re-run reproduced that arm **per-run, token-for-token** — a
determinism check obtained by budgeting from measurement instead of guesswork.

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
are recorded against each RB-P bullet below. **v0.15.0 does not move this
further**: it adds a Measurement tool and changes no code any config runs, so
the v0.14.0 caveat is still the whole caveat. Before quoting any number in
this section against v0.14.0-or-later code, read
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
`nav-release-bundle` 1/3 → 3/3. The 14b blind-critic row stands as
measured, and the cell is still 0/3 on shipped code: RB-P4 is confirmed,
round 1's lexical fix was measured harmful, and round 2's structural
attempt took the cell 0/3 → 3/3 on the same seeds — but a semantically
null one-byte edit does the same, so that attempt was **withdrawn** and
the row is not rewritten off it either (see the RB-P4 outcome above and
RB-P14). Neither
move has been re-measured at sweep scale, so this table is not rewritten
off two cell bars.

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

  **Outcome (2026-08-11, round 2 — SA1 measured, SA2 reviewed, SA3
  controlled, and the change was WITHDRAWN. The target cell moved 0/3 →
  3/3, a semantically null one-byte edit moves it just as far, so the gain
  is not attributable; the cost is. RB-P4 stays OPEN.)**

  **What was attempted.** `task-completion` gained the `reasoning` field
  `grounded-completion` already has — required and listed first — plus one
  step before scoring: name the fact the task asks for, quote the value the
  answer supplies for it, then judge. The blind critic was explicitly *not*
  asked to derive the correct answer — it has no evidence, and for
  `nav-prod-port` no way whatsoever to know the port is 9443, so deriving
  would mean guessing. Extract-and-compare is the blind analogue of the
  grounded critic's derive-first step. Written as `e57f1a6`, withdrawn as
  `9ced4ab`, which puts `assets/rubrics/task-completion.yaml` back
  byte-identical with `main`. Both commits stay in the branch log on
  purpose: the attempt is part of the measured record, and the null control
  below only means something standing next to the thing it voids.

  **It was a Contract (Layer 2) change with suite-wide reach**, which is
  why the no-regression arms were part of the bar rather than an extra.
  `task-completion` is the rubric the `critique` config loads on *every*
  model, so the edit changed every `critique` run everywhere, not just the
  cell it was aimed at. It also changed the rubric's *schema*: `reasoning`
  was `required`, so a critic that did not emit it would fail
  `structured()`. Seven test updates existed only to track that schema
  change, and went back with it.

  **The bar was pre-registered in writing before any arm finished.** Four
  arms, `--config critique --repeats 3` over the frozen 22-task suite,
  before-arms from a pristine worktree at `d2f78b7`:

  | arm | model | suite | `nav-prod-port` | tokens |
  |---|---|---|---|---|
  | before | 14b | 35/66 | **0/3** (`critique-exhausted`) | 67,312 |
  | after | 14b | **38/66** | **3/3** | 76,399 (+13.5%) |
  | before | 7b | 33/66 | 3/3 | 56,066 |
  | after | 7b | 33/66 | 3/3 | 64,888 (+15.7%) |

  Bar 1 (the target cell) moved and Bars 2 and 3 (no regression, two
  models) held: all three 14b gains are the target cell, no 3/3 task fell
  on either model, and no critique round hit `StructuredOutputError` on the
  new required field. **"No other cell moved" is true at pass/fail level
  only** — six rows changed *failure mode* without changing pass/fail, and
  they are part of the record:

  | model | task | seed | before → after |
  |---|---|---|---|
  | 14b | `recall-oncall` | 2831155312 | `critique-exhausted` → `wrong-answer` |
  | 14b | `recall-oncall` | 4070734686 | `critique-exhausted` → `wrong-answer` |
  | 14b | `recall-oncall-rotation` | 1977305293 | `wrong-answer` → `critique-exhausted` |
  | 14b | `shop-basket-total` | 337707843 | `wrong-answer` → `malformed-output` |
  | 14b | `shop-basket-total` | 1022600830 | `wrong-answer` → `malformed-output` |
  | 7b | `shop-cheapest` | 2253311894 | `turns-exhausted` → `malformed-output` |

  **The critic changed its verdict; the answerer did not change its
  answer.** On all three seeds the answerer emitted exactly
  `{"port": 9443}`, byte-identical to the before-arm's first answer, and
  all three passes carried `critique_rounds == 0`: zero feedback was ever
  injected, so round 1's appeasement pattern is excluded by construction.
  A replay of the critic alone on that byte-identical answer, at the same
  pinned seeds, scores **5,5,5 → 7,10,10** — re-run by the reviewer, then
  re-run again by SA3 in **five separate processes per cell** (30 requests,
  one request payload sha per cell, no spread within any cell) and
  **committed** as
  `2026-08-11-sa3-14b-nav-prod-port-critic-replay.json`. It had previously
  existed only as prose here and in a commit body, which is exactly what
  this ledger is supposed to prevent. Seed 634446002 — whose before-verdict
  was the self-refuting one quoted above — reasoned under the attempted
  rubric: *"Find the production port of billing-svc from the workspace
  files; {"port": 9443}. The answer provides a port number, which matches
  the fact requested."* Having written the fact and the value down, it did
  not reach for the format.

  **The null control that voids the attribution (SA3).** Take the *before*
  rubric and delete one byte — the rubric file's trailing newline, which
  the YAML block scalar carries into the tail of the critic prompt. No word
  of the rubric changes; nothing about it is semantic. Measured on the same
  cell, the same harness, and the same three seeds (2331795949, 4094558621,
  634446002, in that order in the token column):

  | rubric | `nav-prod-port` (14b, 3 seeds) | `critique_rounds` | tokens |
  |---|---|---|---|
  | `d2f78b7` as filed | 0/3 `critique-exhausted` | 3,3,3 | 3,596 / 3,441 / 3,534 |
  | `d2f78b7` minus one trailing newline | **3/3 pass** | 0,0,0 | 1,646 / 2,026 / 2,018 |
  | `e57f1a6` as attempted | 3/3 pass | 0,0,0 | 2,361 / 2,215 / 2,210 |

  The null edit reproduces the attempted change's entire pass signature —
  0/3 → 3/3 at `critique_rounds == 0` — and the critic-only replay of that
  variant scores **9,9,9** against threshold 7 on all three seeds, stable
  across three processes each. Evidence:
  `2026-08-11-sa3-14b-nav-prod-port-whitespace-null-control.jsonl` and the
  `whitespace_null_control_replay` block of the replay JSON.

  What that costs the claim, stated plainly: `critique_rounds == 0` on
  three seeds was SA1's discriminator, and it does **not** discriminate —
  a change with no content passes it. The +3 is therefore **not
  attributable** to derive-before-score. This does not show that the
  reasoning field does nothing; it shows that this cell cannot tell whether
  it does, and that the cell's before-state was **byte-fragile rather than
  semantic** — the 0/3 was never a stable property of the rubric's wording.
  Recorded as **RB-P14** below.

  **The decision: withdraw the rubric, keep the evidence.** Both
  no-regression arms held, so there is no measured *harm*. The cost,
  however, is measured: **+13.5% tokens on 14b and +15.7% on 7b**, on the
  `critique` config of every model. On 7b it is pure overhead — 7b gained
  nothing (0 gains, 0 losses) and its `nav-prod-port` held at 3/3, a named
  do-not-ship condition, while its tokens still rose 15.7%, which is the
  proof the new field was emitted there. **On a model without the defect
  the reasoning field is pure token overhead.** This project does not pay a
  measured cost for a benefit it cannot attribute, so the rubric goes back
  and the measurements stay. **No version bump** — with the rubric
  withdrawn this is a docs-and-evidence cycle, and PR #21 is the no-bump
  precedent; `runtime-py` stays at 0.14.0. Every JSONL and JSON under
  `docs/eval-data/` from this job is kept, **including the arms that
  measured the withdrawn change**, because without them the null control is
  not legible. The deliverable of this round is the null control and what
  it invalidates, not the rubric.

  **One observation the next attempt may want, offered as a lead and not as
  a result.** Under the attempted rubric, on 14b `recall-*` cells that were
  never the target, the critic failed answers *for the right reason* —
  *"The answer provided 'null', which does not correctly identify a
  person's name as requested by the task"* and *"no name supplied where a
  specific person's name was asked for"* — on answers that genuinely lack
  the fact, in a storeless config where no answer could contain it. No
  pass/fail move is attributable to that, and after the null control the
  same caution applies to it as to the target cell: reasoning strings that
  read like the mechanism are not evidence of the mechanism.

  **What the before-arm actually was.** SA1's pristine worktree was deleted
  after the run and `.git/worktrees` kept no record, so its sha lived
  nowhere. Re-established by measurement rather than assertion: a fresh
  worktree at `d2f78b7`, re-run on this cell, reproduces SA1's committed
  before-arm rows field-for-field — tokens 3,596 / 3,441 / 3,534 and all
  three last-feedback strings byte-identical
  (`2026-08-11-sa3-14b-nav-prod-port-d2f78b7-repro.jsonl`).

  **Which fields are comparable across the arms, and which are not.** The
  last-feedback string, `outcome` and `passed` are comparable everywhere
  and are byte-identical for this cell across all three before-measurements
  (`2026-08-10-rebaseline-14b`, round 1's `rp4d` arms, SA1's arm A). Three
  columns are not, and a reader diffing rows will trip on them:
  `critique_rounds` reads 2 in the 2026-08-10 rebaseline and 3 afterwards
  (change 1 in [Reporting-semantics
  changes](#reporting-semantics-changes-2026-08-11-v0140)); `model_calls`
  reads 9 before `144c484` and 7 after, with `tokens` 4,205/4,020/4,165 →
  3,596/3,441/3,534, because the gate stopped re-buying a verdict for an
  unchanged answer; and `tool_calls` reads 0 on every `critique-exhausted`
  row by construction (the counter reads the loop's own message list, which
  is empty when the gate raises), so it is meaningless in any
  exhausted-vs-passing comparison. SA1's "field-identical" claim was about
  the feedback strings and is accurate as stated.

  **The zero-margin pass, recorded not smoothed:** in the after-arm seed
  2331795949 scored exactly 7 against a threshold of 7 — one point from a
  loss. It held at 7 across five separate processes in the SA3 replay, so
  it is not a lucky sample; it is a stable knife-edge, and one of the three
  passes the +3 was built on sat on it. Its reasoning hedges honestly about
  what a blind critic cannot check (*"correctness cannot be verified due to
  lack of documentation and workspace files"*), which is the right
  epistemic move and also the one that costs it points. The blind critic's
  ceiling on evidence-dependent tasks is that hedge, not the format
  confusion. Evidence for this whole round:
  `2026-08-11-sa1-{14b,7b}-critique-suite-{before,after}.jsonl`,
  `2026-08-11-sa3-14b-nav-prod-port-{critic-replay.json,d2f78b7-repro.jsonl,whitespace-null-control.jsonl}`.

  **Status — RB-P4 stays OPEN, with two exhausted attack directions and a
  named blocker.** The defect is unchanged and unfixed: the blind critic
  kills a solved cell on 14b. Two directions at the rubric surface are now
  spent, both measured, both recorded above — **lexical** (round 1: the
  rewording drove a byte-correct answer from 5/10 to 0/10, measured harmful
  and reverted) and **structural** (round 2: derive-before-score, measured
  unattributable and withdrawn). A third wording is not what is missing.
  What is missing is an instrument: a one-cell, three-seed, single-model
  bar cannot separate a mechanism from a perturbation, and this cell has
  now failed to do so twice — in round 1 an appeasing reformat counted as a
  pass, and in round 2 a null edit scored the same as the attempted fix.
  That blocker
  is **RB-P14**. Stated plainly: **RB-P4 is not attackable again until
  RB-P14 gives it an instrument** — the blind critic's verdict measured as
  a *distribution* over meaning-preserving perturbations of its own prompt,
  reported as a pass rate with its spread, across a target wider than one
  cell. Until that exists, any rubric edit proposed here cannot be shown to
  have worked, however plausible its reasoning strings read.

  **Status update (2026-08-12, the non-fragile screen) — RB-P4 stays OPEN and
  a third attack direction is now NAMED, with its target counted in advance.**
  See [The non-fragile screen and the standing anchor
  set](#the-non-fragile-screen-and-the-standing-anchor-set-2026-08-12) for the
  full derivation. Three things move here:

  1. **The defect reproduces; what is missing is a non-fragile instance of
     it.** Across 132 screened cells, stratum D1 — non-fragile, correct
     answer, robustly below threshold — is empty, and 63 of the 66
     correct-answer cells are ruled out outright at stage 1 because the shape
     needs identity `< 7`. But the cell itself is still 3/3 correct under
     `bare` and 3/3 `critique-exhausted` under `critique`. **"Not
     reproducible" is the wrong reading and must not be written; "fragile, not
     absent" is the measured one.** RB-P4 is not refuted, it is un-instrumented.
  2. **The failing points are format complaints, and the rubric forbids
     exactly that.** Every sub-threshold row on the cell's own perturbation
     family was read: **12 of 12** on r1 and **13 of 13** on r2 are format
     complaints; **zero** dispute the content. The answer is `{"port": 9443}`
     — correct, and already in the format the task demands — and one verdict
     states the contradiction itself: *"Correct answer format wasn't followed
     but required content was identified correctly."* The rubric's own text
     says "Do NOT deduct points for formatting". So the critic is not hitting
     a limit of blind judgement here; it is violating a directive it was
     given, about a defect that is not present.
  3. **Attack (third direction, unexhausted):** strengthen the
     anti-format-deduction instruction — make "the answer already satisfies
     the task's stated format" a case the critic must check before deducting,
     rather than a prohibition stated once in the preamble and ignored under
     load. Unlike directions 1 and 2 this one has a **counted target**: **all
     25 of the 25** sub-threshold points across r1 and r2 are format
     complaints, with no content complaint among them to confound the
     reading, so the edit either moves them or it does not.
     **The blocker is unchanged.**
     The cell is fragile (1/12, 4/12, 3/12), so the crediting rule still
     refuses the attribution, and the anchor set below cannot substitute —
     its accept side is entirely `structured-extraction` and touches no
     `file-nav` cell (RB-P21). This is a live hypothesis with a measurable
     surface, **not** a licence to write the edit and credit it.

  **And a correction that runs the other way.** Round 2's rewording was
  withdrawn as *measured harmful* on the strength of this same cell. Under
  this document's own crediting rule that verdict is no better supported than
  the one it replaced. **The change stays withdrawn** — nothing here
  re-credits it and no evidence has been produced that it helped — but its
  effect is properly recorded as **unmeasured**, not **known-bad**. Evidence:
  `2026-08-12-m1-family-14b.jsonl`, `2026-08-12-m1-bare-14b.jsonl`,
  `2026-08-10-rebaseline-14b.jsonl`, `2026-08-12-nonfragile-anchor-set.json`.
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
- **RB-P14 — a blind critic's verdict on a single cell is byte-fragile, so
  a one-cell bar cannot tell a mechanism from a perturbation.** Deleting
  one semantically null byte from the `task-completion` rubric — the
  file's trailing newline — moves 14b `critique` `nav-prod-port` from 0/3
  `critique-exhausted` to 3/3 pass at `critique_rounds == 0` on all three
  pinned seeds, which is the whole pass signature the RB-P4 structural
  attempt claimed as proof of mechanism. Critic-only replay of that
  variant: 9,9,9 against threshold 7, stable across three processes per
  seed. This does not say the withdrawn change was empty — it says the
  *bar* cannot see the
  difference, and that a 5/10 sitting two points under a threshold is one
  perturbation away from a 9/10 either way. **Attack:** stop treating one
  verdict as a measurement. Score the critic over a small family of
  meaning-preserving perturbations of its own prompt (whitespace,
  clause order, a paraphrase that changes no requirement) and report the
  pass *rate* across that family with its spread, so a rubric edit has to
  beat the noise band it lives in. Cheap — the critic-only replay is one
  request per point and needs no answerer. Widen the target beyond one cell
  before any rubric edit is called a fix. (Measurement.) Evidence:
  `2026-08-11-sa3-14b-nav-prod-port-whitespace-null-control.jsonl`,
  `2026-08-11-sa3-14b-nav-prod-port-critic-replay.json`.

  **Outcome (2026-08-11) — the instrument was built and it confirmed the
  diagnosis, but not the predicted verdict.** `criticreplay.py` scores a
  12-point perturbation family (`assets/evals/perturbations/task-completion.yaml`,
  sha `340ce4db`) over three `task-completion` variants on 14b
  `nav-prod-port` at the three pinned seeds 2331795949 / 4094558621 /
  634446002: `A-asfiled` (`d2f78b7`), `B-nonewline` (`A` minus the template's
  trailing newline), `C-attempted` (`e57f1a6`, the withdrawn
  derive-before-score rubric). 141 requests, 63,342 tokens. The reproduction
  gate held exactly — identity scores 5,5,5 / 9,9,9 / 7,10,10 against the
  committed SA3 record, five replays each, zero spread within any cell — and
  the internal cross-check held: `B`'s identity and `A`'s
  `W1-trailing-newline` are the same prompt bytes by two routes
  (`prompt_sha256` `3e3a55af…`) and score 9 on all three seeds.
  **The measured noise band is the whole scale.** Meaning-preserving edits to
  the critic's *own* prompt move the score from 0 to 9 on `A` and `B` and 0 to
  10 on `C`, on every seed; all three families straddle threshold 7, so all
  three are `fragile: true` and all nine pairwise comparisons come back
  `attributable: false`. `A-asfiled` passes 1/12, 4/12, 3/12 of its own
  family. That settles the sharper question: **the 0/3-versus-3/3 that RB-P4
  rested on was never a measurement** — the as-filed rubric fails most
  meaning-preserving rewordings of itself on this cell, and the one that
  flips it to 3/3 is a deleted newline sitting inside that noise.
  **The predicted verdict did not land, and is recorded rather than
  re-scoped.** §10 expected `B-nonewline` vs `C-attempted` to read
  `indistinguishable` on every cell; it reads `indistinguishable` on seed
  4094558621 only (7/11 vs 7/11) and `inconclusive` on the other two (7/11 vs
  10/11 both times), because `C` passes at a *higher* rate than `B` without
  reaching the `F/F`-versus-`0/F` bar that rule 1 requires. So the pair is
  **distinguishable on zero of three cells** — by rule 3 it is not
  distinguishable on the change, and by rule 2 every family is fragile, so no
  attribution was available either way. The load-bearing conclusion is
  unchanged and the gate text was simply too strong: "no separation" is what
  was measured, "equal pass rates" is what was predicted, and only the first
  is a property of the world. **Attack:** the `inconclusive` band is doing
  real work here and the spec gave it no reporting duty beyond a label — a
  pair that differs by 3/11 on two cells and 0/11 on a third is not the same
  finding as one that differs nowhere, and the summary cannot currently say
  so. Give `inconclusive` a reported effect size and re-state §10's
  expectation as "not distinguishable" rather than "indistinguishable"
  before the widened cell set runs, or the next bar will fail its own gate
  for being right. One point is separately suspect: `P3-right-correct`
  violates the manifest's shared-token guard on exactly this cell (it removes
  *right*, and the task prompt says "follow the documentation to the **right**
  file"), and ships that way pinned by a test. Dropping it changes no verdict
  — B vs C stays 6/10 vs 6/10 on 4094558621 and 6/10 vs 9/10 on the other two
  — so no conclusion here rests on it, but it should be fixed before the
  family is reused (filed as RB-P19). Evidence:
  `2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl`,
  `2026-08-11-pb14-14b-nav-prod-port-perturbation-summary.json`.

  **The gate re-reading, ratified by the user 2026-08-12.** Gates 0 and 1 test
  the *instrument* and both held exactly. Gate 2's fragility half held and is
  the finding the tool was built to produce. Gate 2's `indistinguishable`
  clause was **a prediction about the world wearing an instrument-test's
  clothes, and it was wrong** — it is recorded as a missed prediction, not
  re-scoped into "partially met", because the only thing that makes a
  pre-registered bar worth anything is that a miss stays on the record.
  The spec's own amendment section
  (`docs/superpowers/specs/2026-08-11-perturbation-bar-spec.md` §12.2) quotes
  the failed clause verbatim beside what was measured. **What the instrument
  is now used for is a rule, not a suggestion:**
  [Crediting a rubric edit](#crediting-a-rubric-edit-2026-08-12) — no rubric or
  critic-prompt edit is credited with moving a cell until the bar has run on
  that cell and reported the family non-fragile. A tool nobody is obliged to
  run does not survive contact with a cycle that is in a hurry, and RB-P4 is
  the measured proof.

  **The one-replay default was checked rather than assumed (2026-08-12).** The
  acceptance run scored each perturbation point once, justified by the
  *identity* point's zero spread — evidence about one prompt, not about the
  eleven perturbed ones. Re-run at **R = 3 on every point** of `A-asfiled` and
  `B-nonewline` over all three seeds (207 requests, 78,885 tokens, `wire_calls`
  equal to `requests`, so nothing retried): **69 points, zero within-point
  spread, and zero disagreement with the acceptance run** — the extreme
  0-scoring order points included (`O2-bands-ascending` on both variants and
  `O1-swap-format-refusal` on `B`, 0,0,0 every time), and every per-cell pass
  rate identical (`A` 1/12, 4/12, 3/12; `B` 7/11 on all three). So the whole
  0-to-9 band above is prompt-sensitivity, not sampling noise, and the
  headline fragility numbers are not a one-draw artifact. This holds for one
  cell on one model and is not a licence to skip replays on an unchecked
  family. Evidence:
  `2026-08-12-pb14-14b-nav-prod-port-replay3.jsonl`,
  `2026-08-12-pb14-14b-nav-prod-port-replay3-summary.json`.
- **RB-P15 — seeded sampling here is score-stable, not byte-stable across
  processes, and the harness affirms more than that.** At seed 4094558621
  the reviewer's before-rubric replay produced different feedback *text*
  than arm A's transcript at the same seed and the same prompt, at the same
  score; SA3 saw the same shape twice — an identical request payload sha
  yielding two different verdict strings at an identical score within one
  process, and two distinct verdict texts at a stable score 7 across the
  five processes of the attempted-rubric seed 2331795949 cell. What has held
  everywhere measured is the *score*: 30 replay requests, six cells, zero
  score spread within a cell. Two things depend on the stronger reading and
  should not: the zero-margin 7-against-7 pass, which is one drift from a
  loss and is now known to hold across processes rather than merely assumed
  to; and `run_task`'s `deterministic_sampling=True` affirmation (RP5b),
  which lets `CritiqueGate` reuse a verdict for a byte-identical prompt.
  That affirmation is *safe* on the evidence — reuse is keyed on the prompt
  bytes and the score is what the gate branches on — but it is stated as
  "reproduces a sample exactly", which this backend does not do.
  **Attack:** narrow the affirmation to what is measured (the verdict's
  *decision* is reproducible under a pinned seed, not its bytes), and add a
  standing check that re-issues one pinned critic request N times and
  records the score spread beside every seeded bar, so drift is detected
  rather than discovered. (Measurement, plus one docstring in Core that
  currently overclaims.) Evidence:
  `2026-08-11-sa3-14b-nav-prod-port-critic-replay.json`.

  **Status (2026-08-11): both halves landed.** The affirmation is narrowed to
  the verdict's *decision* everywhere it was stated — `critique.py` (Core,
  three places), `run_task` in `evalrun.py` (Measurement) and `docs/usage.md`.
  **The standing check is
  `python -m bantamkit.criticreplay --identity-only`**, run over a bar's
  `--transcripts` directory after the bar finishes: it replays the one pinned
  critic request `--identity-replays` times per cell and reports the score
  spread, without touching the run it measures (wiring it into `evalrun`
  would have changed the `tokens` column and broken comparability with every
  historical JSONL). Cost on a 3-seed cell at the default 5 replays: 15
  requests. The RB-P14 acceptance run exercised it as the `identity` point of
  every family — 45 identity replays over nine (variant, cell) pairs, **zero
  score spread within any cell**, which is the same result the narrowed
  affirmation claims. Evidence:
  `2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl`.

#### New measured problems from the perturbation bar (2026-08-12)

Found while building and reviewing the RB-P14 instrument. They are defects **in
the instrument**, which is the one place this project cannot afford them: every
claim the bar is about to gate rests on them. None is fixed unless it says so,
and each carries an attack direction.

- **RB-P16 — `inconclusive` carries no effect size, so a consistent
  directional gap and a one-point wobble get the same label.** The
  acceptance run reports `B-nonewline` vs `C-attempted` as `inconclusive` on
  two cells at 7/11 vs 10/11 — the same sign, the same size, twice — and the
  summary says exactly what it would say for 7/11 vs 6/11 on one cell and
  nothing on the others. §7's decision rule gives the band no reporting duty
  beyond the word, so a reader cannot tell "nearly separated, consistently"
  from "noise". This is the instrument's **largest real gap**: the bar's whole
  job is to grade evidence, and it currently has one grade for everything that
  is neither `F/F` nor `0/F`. **Attack:** report the pass-rate difference and
  its per-cell sign alongside the label, and require the sign to agree across
  cells before an `inconclusive` may be described as directional at all —
  then re-state the spec's expectation as "not distinguishable" rather than
  "indistinguishable", which is the wording that made a correct measurement
  read as a failed gate. (Measurement.)

  **SURVEYED 2026-08-13 (L1, probe only — nothing fixed). The gap is a number
  now, and it is larger than this entry's example.**
  `docs/eval-data/2026-08-13-rbp16-rbp17-rbp18-survey.md` (+ `.py`, re-runnable)
  measures **every** §7 comparison in the repo: **12, over 2 runs** — ten other
  committed summaries are single-variant, so the decision rule never fired in
  them at all. Eleven read `inconclusive`, one `indistinguishable`, **none**
  `distinguishable`, **none** attributable. |Δ| over the band spans **3/11
  (0.2727) to 5/6 (0.8333)**. **The 7/11-vs-10/11 case this entry quotes is the
  SMALLEST gap in the band.** The worst is `A-asfiled` **1/12** vs
  `C-attempted` **11/12** — ten of twelve points flipped, one point short of
  `0/F`-versus-`F/F` on each side — wearing the same word.
  **Two clauses above do not reproduce as written.** (1) "no reporting duty
  beyond the word" is too strong: both pass rates are on every comparison dict
  and `format_table` prints them; what is absent is the *difference*, the
  *sign*, and any statement across cells. (2) The proposed "require the sign to
  agree across cells" rule has **zero instances in the committed record** —
  every `inconclusive` cell has the same sign, and the only non-negative sign
  anywhere is the exact tie that already reads `indistinguishable`. It is a
  guard against a case this project has never measured.
  **Broader than filed:** `indistinguishable` has the same defect. It is equal
  pass *counts*, not agreement — the one committed `indistinguishable` cell
  (`B` 7/11 vs `C` 7/11, r1) is a cell where the two variants **disagree on 2
  of 11 points** (`B` passes `P2-asks-requests`, `C` passes
  `W2-double-trailing`). Executable spec, non-strict `xfail`:
  `test_the_inconclusive_band_reports_something_a_reader_can_tell_from_noise`;
  ledger claim `N01`.

  **CLOSED 2026-08-14 (L2). A verdict now carries its effect size, the tie word
  carries its disagreement, and no cell's attribution moved.** `_compare` ships
  an `effect` block beside every verdict (and `guard_effect` beside
  `guard_verdict`): `delta_passed`/`delta_rate` signed `a − b` in the survey's
  convention, `sign`, `leads`, `points_from_separation` = `F − |Δn|`, and
  `disagreeing_points` with the `a_only`/`b_only` point ids. `format_table`
  gains one indented `effect:` line under each Pairwise row — a **second** line,
  so the existing row's bytes do not move — carrying a ten-cell ASCII bar of
  |Δrate|, which is what makes the band's ends tellable at a glance:
  `[########--]` for 0.833 against `[###-------]` for 0.273. `summarize` gains
  `directional`, the cross-cell statement that was the third missing piece.
  **`points_from_separation` and not a `large`/`small` banding**, deliberately:
  it is derived from §7 rule 1 itself and invents no cut point, and an
  instrument that grades evidence may not quietly re-grade its own.
  **The filed sign-agreement rule did NOT ship as a rule.** It has zero
  instances in the committed record, so as a gate it would have changed nothing
  on any of the 12 cells while looking tested. It ships as `directional`, a
  report, and `_directional`'s docstring says so in words.
  **`indistinguishable` is not renamed.** A rename makes the committed record
  incomparable and still asserts nothing about agreement; the word now ships the
  points the two variants disagree on. Second measured instance, from a fresh
  run 2026-08-14: the shipped rubric vs its trailing-newline variant reads
  `indistinguishable` at 2/11 vs 2/11 on `nav-prod-port` r0 while disagreeing on
  **4 of 11 points**. That same run also measured the two orthogonal: its
  *smaller* |Δ| cell has *more* points disagreeing (7 of 11 at |Δn| = 1 against
  4 of 11 at |Δn| = 2), so a report carrying only the difference ranks them
  backwards.
  **The acceptance claim is a field measurement, not the suite** (RB-P28 is
  open): `docs/eval-data/2026-08-14-rbp16-effect-size-report.{sh,md}` — a real
  `$?` from a subprocess with no `PYTEST_*` key, checked by a script that never
  imports `bantamkit` and recomputes the difference itself. Before → after on a
  three-cell two-variant run: comparisons whose report states the difference
  **0 → 3**, printed effect lines **0 → 3**, §7-report collisions **1 → 0**, the
  tie's disagreement count **unstated → 4**, and **no status moved on any of the
  six cases**. Removing the added lines from the post-fix stdout recovers the
  pre-fix stdout byte for byte on all six.
  **One measured negative, recorded rather than re-scoped.** Over the *whole*
  comparison dict the pre-fix reports did **not** collapse on that rig — the
  guard's cell-scoped `guard_dropped_rules` differed — so on that rig a reader
  with the raw JSON could have told the cells apart by a field about the guard
  rather than about the verdict. The committed acceptance run's r0/r1 pair does
  collapse over the whole dict, which is why RB-P16 was filed; the full-dict
  collapse is rig-dependent. **Unfiled attack:** two verdict reports separated
  only by the guard's bookkeeping is an accident, not a design.
  **The byte-identity floor moved and was not regenerated.**
  `f8404ab-perturbation-baseline.json` is untouched; the floor node is restated
  as an exact identity modulo the three named keys and two named table-line
  kinds (129502 → 137132 bytes, 27 → 33 table lines, **zero** `f8404ab`-era
  fields changed), with a second node asserting the stripped-out content is
  present and non-trivial so the strip cannot hide a regression.
  The `xfail` is removed and the node passes. Ledger: `N01` re-aimed from
  `_separation` to `_compare`'s `effect` key, plus `N04`/`N05`/`N06`.
- **RB-P17 — a rubric variant's provenance is a path, and a path is not a
  rule.** The bar's `--rubric LABEL=SPEC` admits a filesystem path or
  `git:<ref>:<path>`. `B-nonewline` — the null control, and the variant the
  whole RB-P14 finding turns on — is expressible as neither, so it was
  materialized to a scratch file and the committed summary records
  `rubric_ref` as a session temp path that no longer exists. The bytes are not
  lost: the manifest's `materialized_variants` block records the recipe and
  `base_sha256` `d1f32ad2…`, re-verified 2026-08-12 to reproduce exactly from
  `git:d2f78b7`, and Gate 1 ties it to `A-asfiled`'s `W1` point at an equal
  `prompt_sha256`. But an evidence file that points at nothing is one
  cleanup away from an unreproducible claim. **Attack:** add a
  `derive:<label>:<rule-id>` spec form so the control is written as
  `derive:A-asfiled:W1-trailing-newline` — a rule, applied to a committed ref,
  recorded as such in every row. (Measurement.)

  **SURVEYED 2026-08-13 (L1, probe only). The `d1f32ad2…` claim holds; two
  statements around it do not.** Same artifact. Every `rubric_ref` in every
  committed summary, classified: five distinct values, of which **one**
  resolves from this repo (`assets/rubrics/task-completion.yaml`, ten runs).
  `base_sha256` `d1f32ad2947b…` **re-reproduces exactly** from
  `git show d2f78b7:assets/rubrics/task-completion.yaml`, parsed, `prompt`
  taken, one trailing newline removed.
  **Does not reproduce:** "a session temp path **that no longer exists**" —
  measured 2026-08-13, **both** scratchpad rubrics still exist on this machine
  and still hash to their recorded `rubric_sha256`. The defect stands; the
  stated fact is false today.
  **Broader than filed, three ways.** (1) There are **two** such paths, not
  one — `b-nonewline.yaml` (2026-08-11) and `n5-b-nonewline.yaml` (2026-08-12
  replay3). (2) They record **different `rubric_sha256`** for the *same* rubric
  under test: different file bytes, one template sha `d1f32ad2947b…`. So
  `rubric_sha256` is the file, not the rubric the critic read. (3) The `git:`
  form — the one this entry calls the good one — records `source = ref` and
  **drops the path**; `RubricVariant.spec` is never written to any row or
  summary, so `d2f78b7` names a commit and not a file.
  **The attack is constructible and one clause of it is not.** Applying
  `W1-trailing-newline` to `A-asfiled` gives exactly `d1f32ad2947b…` per the
  frozen manifest, and `W1` is *inapplicable* to `B-nonewline`, so the derived
  variant is a fixed point of its own rule and there is no load-order cycle.
  But `derive:A-asfiled:W1-trailing-newline` is resolvable **only from the argv
  that defined `A-asfiled`**, and names the manifest nowhere — the recorded ref
  must expand the label to `git:<ref>:<path>` and carry the manifest sha, or it
  is a pointer into a vanished process. Executable spec:
  `test_every_rubric_ref_in_a_committed_summary_resolves_from_this_repo`;
  ledger claim `N02`.

  **CLOSED 2026-08-14 (L3), on a claim narrower than the filing's and a defect
  wider than it.** What shipped is a third `--rubric` spec form,
  `derive:<manifest-path>:<rule-id>:git:<ref>:<path>`, and the null control is
  now writable as

  ```
  --rubric B-nonewline=derive:assets/evals/perturbations/task-completion.yaml\
:W1-trailing-newline:git:d2f78b7:assets/rubrics/task-completion.yaml
  ```

  which resolves to template sha `d1f32ad2947b…` — the frozen manifest's own
  committed `base_sha256` for `B-nonewline`, reproduced and not moved.

  **The filing's own fact is withdrawn, not repeated.** "A session temp path
  **that no longer exists**" was false when it was filed and is false today:
  re-measured 2026-08-14, both scratchpad rubrics still exist on this machine
  and still hash to their recorded `rubric_sha256`. The claim that needs no
  false fact is the one shipped here — a scratchpad path is not a durable
  provenance record, because it is unresolvable on any other machine *today*
  and one `rm -rf` from naming nothing on this one.

  **Three changes, all additive; no committed value moves.**
  (1) The `derive:` form above. Its base must be a `git:` spec — a derived
  variant has no file of its own, so the only thing that makes its record
  resolvable is that every segment is immutable, and requiring it makes a
  derive-of-a-derive unrepresentable, so the load order cannot cycle. A rule
  whose anchor is absent **raises**; `W1-trailing-newline` against a base that
  already has no trailing newline is its own fixed point and names no variant.
  (2) The `git:` form records the **path**: `parse_rubric_arg` stored `ref` and
  dropped it, so a row said `d2f78b7`, a commit and not a file. Every branch now
  records the whole spec — the string a reader can hand straight back.
  (3) `rubric_template_sha256`, a **second** column beside `rubric_sha256`.
  Measured 2026-08-14: the two committed `B-nonewline` runs record
  `59b0fe81ecf3…` and `29f299707fd6…` — two values for **one** rubric, whose
  template hashes `d1f32ad2947b…` in both. The old column is the file and stays
  the file; the new one is the rubric the critic read, and it is the value the
  manifest already records as `base_sha256`.

  > **AMENDMENT 2026-08-14 (L6). The sentence in (1) — "the only thing that
  > makes its record resolvable is that every segment is immutable" — was FALSE
  > as shipped, and it is corrected here rather than rewritten above.** The rule
  > it describes was enforced on the **base** segment only. The **manifest**
  > segment had no rule at all, so
  > `derive:/private/tmp/<session>/scratchpad/m.yaml:W1-trailing-newline:git:…`
  > was **accepted** and recorded verbatim in `ref` with `rubric_sha256` empty —
  > the exact absolute-scratchpad shape RB-P17 was filed about, one segment over,
  > inside the fix that closes RB-P17. Worse, the manifest segment is a
  > **working-tree** path and nothing recorded its bytes: editing the op in place
  > makes the same recorded ref resolve to a different rubric
  > (`d1f32ad2947b…` → `447e5be27613…`), silently, with no file hash to fall back
  > on. The fresh-run pin passed the absolute form (`repo / "/abs"` is `/abs`;
  > pathlib drops the left side) and so did the committed field checker — the
  > checkers had the hole they were checking for.
  >
  > **What is true now.** The manifest segment must be **repo-relative**: no
  > absolute path, no `~`, no `..` that walks out. It is refused from the argv
  > alone, so it is a shape rule and reports `2`. And every derived variant
  > records `derive_manifest_sha256`, the bytes of the manifest it resolved
  > through — which does **not** make that segment immutable and does not claim
  > to. It makes a substitution **detectable**, which is the most a record can do
  > about an input the reader has to fetch. So the corrected sentence is: *a
  > derived variant has no file of its own, so its record is resolvable only
  > because every segment names something a second reader can obtain from this
  > repository, and the one segment that can change under its own name states its
  > bytes.*
  >
  > **The acyclicity claim in (1) is untouched and still holds**: the base must
  > still be a `git:` spec, a derive-of-a-derive is still unrepresentable on its
  > face, and both orderings were tested. Nothing above is edited; this note is
  > the correction. Measured before and after:
  > `docs/eval-data/2026-08-14-rbp17-manifest-segment.md`, runner
  > `docs/eval-data/2026-08-14-rbp17-provenance-resolution-v2.sh` — a successor
  > beside the v1 runner, which stays as it was because it produced a committed
  > record. Ledger `N11`, `N12`.

  **THE `xfail` DID NOT GO GREEN, AND CANNOT.**
  `test_every_rubric_ref_in_a_committed_summary_resolves_from_this_repo` reads
  committed summaries, which by invariant are never regenerated, so the four
  unresolvable refs are frozen into the record and only a retro-edit could clear
  them. It stays `xfail` permanently and it pins nothing, in either direction —
  the same structural finding L1 made about `N02`. The pin is
  `test_a_fresh_runs_rubric_ref_resolves_from_this_repo_back_to_the_rubric_it_recorded`,
  over a run made today, with an independent resolver that never calls
  `parse_rubric_arg`. Ledger `N02` (re-aimed), `N07`, `N08`. Field measurement,
  which is the acceptance claim and not the suite:
  `docs/eval-data/2026-08-14-rbp17-provenance-resolution.md`.

  **STILL OPEN, with an attack direction.** The old rows keep their scratchpad
  paths and their bare commits forever — nothing here rewrites them, and a
  reader of `2026-08-11-pb14-…-summary.json` still cannot resolve
  `B-nonewline`'s provenance from this repo. What a reader *can* now do is
  re-derive those bytes: the manifest's `base_sha256` for `B-nonewline` equals
  the template sha of the `derive:` spec above, so the recipe is executable
  rather than prose. **Attack:** write a *new* artifact beside the old ones —
  a re-run of the acceptance cells with `--rubric B-nonewline=derive:…` — so
  the record contains at least one summary whose every `rubric_ref` resolves.
  That needs the qwen arms, which this unit was told not to re-run.

  **ALSO STILL OPEN — A `derive:` REF RESOLVES AGAINST THE PROCESS CWD, NOT
  AGAINST THIS REPOSITORY (L5's M3, measured and filed 2026-08-14 by L7, LIVE at
  HEAD).** `parse_rubric_arg`'s docstring says a reader "who has ONLY this
  repository and one row can recover the exact bytes the critic read … **No argv,
  no machine, no `/private/tmp`**". Measured, that sentence is stronger than the
  code: the reader also has to be **standing in the repo root**, and nothing in the
  record says so. The identical repo-relative ref that resolves from the repo root
  to `d1f32ad2947b…` raises `perturbation manifest not found` from any other
  directory. **Wider than it was filed:** the same holds for the **base** segment —
  `_git_show` shells out to `git show` in the process CWD, so `git:d2f78b7:…`
  resolves to `e018854368c1…` from the repo root and raises `exit status 128` from
  `/`. Both segments are repo-*relative* strings resolved against something that is
  not the repo.
  **C3's `_repo_relative` fix did not close this and was never going to.**
  `_not_repo_relative` is an argument-**shape** rule — a function of the typed
  string and of nothing else, which is exactly what entitles it to report
  `USAGE_EXIT` above `main`'s `try` (RB-P32). It cannot bear on where a relative
  path is resolved **from**. The two rules are complementary and the second is
  missing. **Attack:** resolve both segments against a discovered repository root
  rather than the CWD — `assets_root()` already does that discovery for the asset
  pack, env override first and packaged/parents fallback after — and pin it with a
  node that calls the resolver from a CWD **outside** the tree. That node is the
  one thing the present suite cannot contain: every existing pin runs with the repo
  as CWD, so the dependence is invisible to all of them. Measured:
  `docs/eval-data/2026-08-14-l7-closure-residuals.md`, case A. (Measurement.)
- **RB-P18 — `payload_sha256` is not comparable across records, and its name
  says nothing about that.** SA3's payload shas do not match this bar's for
  identical cells, at identical `prompt_sha256`, identical seeds and identical
  scores, because the two recipes serialize different dicts under the same
  field name. Nothing here is wrong-by-the-numbers — the field is honest
  *within* a run, captured off the request `structured()` actually sends — but
  a reader comparing two evidence files on it would conclude the requests
  differed when they did not. `prompt_sha256` is the cross-record identity.
  **Attack:** publish the recipe wherever the field appears (done for the spec
  §6.3), or version the field name so two recipes cannot share one.
  (Measurement.)

  **RE-MEASURED 2026-08-13 (L1, probe only). THE FILED MECHANISM IS WRONG, and
  the attack it implies is the expensive one.** Same artifact. Both recipes
  were re-derived from `git show` and checked against the committed values on
  **all six** (variant, seed) cells; every one reproduces. The disagreement is
  real — for `A-asfiled`, `git:d2f78b7`, repeat 0, seed 2331795949, score 5, at
  an identical rendered prompt (`8fb6c98412f1…`, carried in SA3's
  whitespace-null-control block as `prompt_sha256_asfiled`): bar
  `a17fc774681a…` versus SA3 `4eb56220e883…`.
  **But the two recipes do NOT "serialize different dicts".** They serialize
  the **identical** dict — same `model`, same `messages`, same `seed`, same
  `response_format`. Recovered by search over candidate serializations and
  confirmed on all six cells, the entire difference is one keyword argument:
  the bar uses `json.dumps(payload, ensure_ascii=False)` (insertion order) and
  SA3 used the same call with `sort_keys=True`.
  **This modifies the attack.** "Version the field name so two recipes cannot
  share one" makes the incomparability permanent and documented, when a
  canonicalisation removes it. The defect is a field whose name says nothing
  about its key order — not two contents under one name. Note also that
  `_payload_sha` is the **only** `payload_sha256` computation anywhere in this
  repo; the second recipe survives only in the committed SA3 artifact and in
  its `how_to_reproduce` prose, its scripts being in no tree. **The same defect
  exists in a second field pair:** `rubric_sha256` (file bytes) versus the
  manifest's `base_sha256` (template text) — see RB-P17's survey note.
  Executable spec: `test_payload_sha256_does_not_name_two_recipes_at_once`;
  ledger claim `N03`.

  > **AMENDMENT 2026-08-14 (L7) — one sentence in the block above is STALE at
  > HEAD, and it is corrected here rather than rewritten there.** The block says
  > "`_payload_sha` is the **only** `payload_sha256` computation anywhere in this
  > repo". That was true on 2026-08-13, which is the date the block carries, so it
  > is disclosed-by-date rather than false — but the 2026-08-14 closure below it
  > does not correct it, and a reader arrives at the two in order. What is true at
  > HEAD: `_payload_shas` is the computation, and it returns **both** columns from
  > one serialization pass; `_payload_sha` is a one-line delegate that returns
  > `_payload_shas(...)[0]` and is kept so that in-process callers of the old name
  > still work. The count of recipes is unchanged — there are still exactly two,
  > insertion-order and key-sorted, both named in `payload_sha256_recipes` — so
  > nothing the block concludes moves. This note exists because a stale sentence
  > inside a dated block is still the sentence a reader quotes. (L5's M4.)

  **FIXED 2026-08-14 (L4) — AND NOT BY THE ATTACK THIS ENTRY FILED.** The filed
  attack, "version the field name so two recipes cannot share one", is wrong and
  is not what shipped: it would make permanent, in the schema, a difference that
  canonicalisation removes. What shipped is
  (1) `payload_canonical_sha256`, a **second** column beside `payload_sha256`,
  holding the same wire body under `json.dumps(payload, ensure_ascii=False,
  sort_keys=True)`, and (2) `payload_sha256_recipes` in every summary a run
  writes, naming the exact call behind each column and naming `prompt_sha256` as
  the cross-record identity — because the reader this problem is about has the
  JSONL and not this tree, which is precisely why SA3's recipe survived only as
  prose.
  `payload_sha256` keeps its name, its recipe and its value. 1280 committed
  occurrences across 12 artifacts mean the insertion-order recipe, and a field
  that changes meaning under a fixed name is this problem's own defect — the same
  argument that made `rubric_template_sha256` additive.

  **WHY `sort_keys` IS NOT AN ARBITRARY CANONICALISATION, and how a reader
  interprets the FROZEN rows under it.** It is the only key-order-independent
  form of the same call, so it removes the measured difference; and it is
  **already a committed value**, so the new column reproduces SA3's frozen shas
  bit for bit. Measured 2026-08-14: **one** request issued today, on
  `A-asfiled`/`git:d2f78b7`/r0/seed 2331795949, lands on **both** frozen record
  families at once — `payload_sha256` = `a17fc774681a…` (the bar's frozen value)
  and `payload_canonical_sha256` = `4eb56220e883…` (SA3's frozen value). So a
  frozen row is interpreted by re-running its cell and seeing **which column its
  value lands in**: that is the difference between "these requests differed" and
  "these records were hashed differently", and it is available for rows written
  before the fix, which are never rewritten. Any other order-independent recipe
  would match nothing already written down and would leave SA3's 30 rows exactly
  as uninterpretable as before.
  Pinned over a **fresh run** —
  `test_a_fresh_run_reproduces_both_frozen_payload_recipes_from_one_request` —
  because a node reading only committed artifacts can never go red under
  mutation. Ledger `N03` (re-aimed), `N09`, `N10`. Field measurement, which is
  the acceptance claim and not the suite:
  `docs/eval-data/2026-08-14-rbp18-payload-recipe.md`.

  **THE `xfail` DID NOT GO GREEN, AND CANNOT.**
  `test_payload_sha256_does_not_name_two_recipes_at_once` reads two committed
  records. All three of its disjuncts are facts about frozen bytes — the two shas
  are unequal, both records carry the key `payload_sha256`, and neither record has
  any other key containing `payload` (measured: 21 keys on the bar row, 8 on the
  SA3 entry). Only a retro-edit could clear it, so it stays `xfail` permanently
  and pins nothing in either direction — the same structural finding L1 made about
  `N02`/`N03` and L3 confirmed for RB-P17's twin.

  **STILL OPEN, one level below the recipe, with an attack direction. One name,
  two ARITIES.** Census over `docs/eval-data`, 2026-08-14: `payload_sha256` is a
  `str` in 1280 places across 12 artifacts and a `list` in 30 places in
  `2026-08-11-sa3-14b-nav-prod-port-critic-replay.json`. A reader diffing the two
  families with `==` gets `False` from the **type**, before a hash is ever
  compared. **The list is not a typo and flattening it would destroy evidence:**
  the two writers record different *units* — a bar row is one **replay**, an SA3
  entry is one **cell** whose field is the SET of distinct shas across that cell's
  processes, and the cardinality is that file's own stated claim that "any score
  spread is the server's, not the prompt's" (all 30 lists have length 1, so all 30
  make it). Shipped: `payload_shas_recorded`, a reader that gives the field a
  defined reading in either shape and **preserves cardinality**; ledger `N10`.
  What is *not* fixed is the cause: the unit of record is inferred from a JSON
  type instead of being stated. **Attack:** name it — a `unit` field on the record
  (`"replay"` vs `"cell"`) so an aggregating writer declares what it aggregated,
  rather than a later reader deducing it from `isinstance`. This cannot be
  retro-fitted to SA3, whose writer is in no tree and whose rows are frozen; it
  binds the next writer. (Measurement.)

  **ALSO STILL OPEN — `N10`'s ARITY PIN IS SYNTHETIC, and the ledger number should
  be read knowing it (L5's M2, filed 2026-08-14 by L7, not fixed).** `N10`'s
  mutation makes the reader flatten (`return (value[0],)`). Exactly one assertion
  in its pin node can go red under it:
  `assert read(["a", "b"]) == ("a", "b")` — a **hardcoded two-element literal**.
  The record-based half of the same node — *all 30 SA3 lists have length 1* — reads
  frozen bytes whose lists are all length 1, so a reader that returns `(value[0],)`
  still returns length 1 and that assertion **can never go red**: a dead assertion
  inside a passing node, which is the shape a green suite is worst at showing you.
  Under it sits the real gap: **no shipped writer can emit a list at all**, so
  nothing in this repo would catch one that did. `N10` is therefore pinned against
  a case the code cannot produce, and PINNED means less for it than for its
  neighbours. **Attack:** land the `unit` field the paragraph above proposes and
  have the bar's own writer emit the aggregated shape for an aggregate — then the
  arity claim has a producer, the census half stops being decorative, and the pin
  is against something a run can actually do. Until then the honest reading of
  `N10` is "the reader handles a two-element list", not "the record's arities are
  under control". Measured: `docs/eval-data/2026-08-14-l7-closure-residuals.md`.

  **AND ONE MINOR, FIXED (L5's M1, 2026-08-14 by L7).**
  `payload_shas_recorded` shipped **absent from `__all__`** (43 entries, this name
  not among them) while this entry presents it as RB-P18's remedy for a reader who
  has the JSONL and **not** this tree — an out-of-tree reader by construction,
  whose only surface is the export list. `guard_table` has carried
  `assert "guard_table" in criticreplay.__all__` since it shipped, on exactly this
  argument; this had nothing, so deleting the export would have turned no node red.
  Now 44 entries, pinned by
  `test_the_payload_sha_reader_is_in_the_published_surface`, ledger `N14`, added in
  the same commit as the fix. Before/after:
  `docs/eval-data/2026-08-14-l7-closure-residuals.md`, case B.
- **RB-P19 — `P3-right-correct` ships violating the manifest's own
  shared-token guard on the acceptance cell.** The guard forbids an added or
  removed word from appearing in the cell's `{task}`; `P3` removes *right*,
  and `nav-prod-port`'s prompt says "follow the documentation to the **right**
  file". It ships that way, pinned by a test asserting exactly
  `{'P3-right-correct': ['right']}` so it stays visible and cannot grow, and
  dropping it changes no verdict anywhere in the acceptance run. It is still a
  point that the manifest's own admissibility procedure rejects. **Attack:**
  re-author the paraphrase against a word absent from every frozen task, or
  make the guard a load-time error rather than a test-time observation — an
  admissibility rule that ships violated is a rule the next family will
  violate too. (Measurement.)

  **BROADER THAN FILED (2026-08-12) — three points violate, not one.** The
  guard is a word-set symmetric difference, so a paraphrase violates on any
  word it *adds or removes*, not only on the word it adds. Recomputed offline
  with `criticreplay.shared_token_violations` against **all 22 frozen task
  prompts**:

  | point | symmetric difference | violates on |
  |---|---|---|
  | `P1-reviewer-relative` | `checking` / `who`, `checks` | `recall-oncall`, `recall-oncall-rotation` (*who*) |
  | `P2-asks-requests` | `asks`, `for` / `requests` | `nav-release-bundle`, `recall-cache-ttl`, `recall-env-endpoint`, `recall-oncall`, `recall-oncall-rotation`, `recall-org-quota` (*for*, and *requests* on `recall-org-quota`) |
  | `P3-right-correct` | `right` / `correct` | `nav-prod-port` (*right*) |

  So **8 tasks are affected, not 1**, and `P2` alone violates on six of them.

  > **RETRACTION (2026-08-12, later the same day).** This paragraph
  > originally continued: *"The 2026-08-12 screen's §6 table … got P2 wrong in
  > both halves … `requests` violates nowhere … The screen reached the right
  > task by the wrong word and missed five others."* **That characterisation
  > is withdrawn.** It is not an error in the screen; it is the **other
  > reading of the same spec sentence**, and the sentence supports both. The
  > text above has been corrected in place rather than left standing, because
  > a doc that asserts one reading as "the corrected" one is the artifact the
  > next reader inherits. Nothing in git history is rewritten: commit
  > `25ce48b`'s message and `9ca1576`'s "their wrong P2 row" stand as
  > written and are wrong on this point. See **both readings**, below.

  **BOTH READINGS (2026-08-12) — the guard has two, the spec supports each in
  a different sentence, and neither is wrong.** An adversarial review that was
  forbidden from importing `criticreplay` re-derived the violation table from
  §3.3's wording alone and got a different answer — the one M1's
  pre-registered screen had already committed. Both readings are defensible:

  | reading | what it is | where the spec says it | P2 violates on |
  |---|---|---|---|
  | **whole-text** | symmetric difference of the base and perturbed **template** word sets | §3.3's operative Test sentence: *"the symmetric difference of the base and perturbed word sets must be disjoint from the task prompt's word set"* | `recall-org-quota` only, via *requests* |
  | **substitution-pair** | symmetric difference of the point's own `from`/`to` strings | §3.3 step 4: *"each P point is expressed as a literal `from` → `to` substitution pair"*, and the manifest's own P2 justification prose | six tasks, via *for* |

  They differ because `asks` and `for` both survive **elsewhere in the
  template** — "what the task asks for is missing the required content", "Do
  NOT deduct points for formatting" — so under whole-text neither word leaves
  the critic's input, while under substitution-pair the instance is the pair
  and the pair drops them. `P1` and `P3` come out identical under both.

  **The user's ruling (2026-08-12): compute both, report both side by side,
  declare neither wrong.** Implemented — see ADDRESSED, ROUND 2 below.

  **The conclusions survive under either reading.** Under the
  substitution-pair set, **8 of the 20 screened cells violate, not the 5
  recorded** — the four additionally affected are 14b `recall-cache-ttl` r0,
  14b `recall-env-endpoint` r0, 4b `nav-release-bundle` r0, and 14b
  `recall-oncall-rotation` r1 (flagged for P1, but not for P2). Every one was
  re-derived from the committed JSONLs with the violating points dropped,
  and **the fragility verdict is unchanged on all eight** — `recall-cache-ttl`
  r0 12/12→11/11 non-fragile, `recall-env-endpoint` r0 11/12→10/11 fragile,
  `nav-release-bundle` r0 0/12→0/11 non-fragile, `recall-oncall-rotation` r1
  0/12→0/10 non-fragile. Under the whole-text set the violating set is a
  subset of that one, so the same verdicts hold a fortiori. No result in the
  screen or in the anchor set depends on a guard-violating point under either
  reading. `docs/eval-data/2026-08-12-nonfragile-anchor-set.json` carries
  per-cell guard data computed the substitution-pair way; its `guard_note`
  and per-cell notes called that set "the CORRECTED violation set" and said
  the screen "under-reported `P2-asks-requests`". **Those two phrases are
  retracted by this entry, and — on the user's ruling, 2026-08-12 — they are
  retracted in that file too rather than only here.** See "the one
  retro-edit, and the rule it was decided under" in CLOSED below: the
  amendment moves prose and nothing else, every measured field is
  byte-identical to `b439053`, and the 2026-08-12 `rbp19b` runs remain the
  live per-(point, cell) record because they carry both readings as fields.
  **This strengthens the attack rather than changing it:** a guard whose own
  filing was restated twice before the ambiguity in the rule was noticed is
  not a rule that survives as a test-time observation. Compute it **over every
  frozen task, from the manifest, under every reading the spec admits**, so no
  future family can ship violating it and no future author has to derive the
  word list by hand. (Measurement.)

  **ADDRESSED (2026-08-12), and the attack was modified on measurement.** The
  guard now runs on the run path (`guard_table`, called from `run()` before
  any request), and the table is pinned by a test over all 22 frozen
  prompts rather than one cell. **The "load-time error" half of the attack was
  tried and rejected as written:** 8 of the 20 screened cells violate,
  including `nav-prod-port` and 3 of the 12 committed anchor cells, so an
  abort makes the canonical cell of this line of work unrunnable — a
  regression against the anchor floor, not a stricter guard. The status quo
  did produce measurements; what it failed to do was make the violation
  impossible to miss. So the enforced property is **non-silence**, not
  refusal: every row a violating point produces carries `guard_violations`,
  the summary carries a `guard` block and a per-(variant, cell)
  `guard_dropped` recomputation, `format_table` prints a GUARD section, and
  attribution requires the separation to survive dropping the tainted points.
  `pass_rate` stays the full family so every committed number remains
  comparable. `--guard error` is the strict reading, opt-in, refusing before
  any spend. Verified end to end: 14b `nav-prod-port` reports the violation in
  its committed JSONL and summary
  (`docs/eval-data/2026-08-12-rbp19-guard-nav-prod-port-14b*`), and all 12
  anchor cells still run with every `expect_pass_rate` unchanged
  (`docs/eval-data/2026-08-12-rbp19-guard-anchors-{14b,4b}*`) — including all
  three hand-computed `guard_dropped` blocks, which the tool now reproduces
  mechanically.
  **What remains open:** the manifest still ships three points that violate
  their own admissibility procedure. Making the violation visible is not the
  same as not having it. **Attack, unchanged in substance:** re-author `P1`,
  `P2` and `P3` against words absent from all 22 frozen prompts, then the
  guard-clean family is the full family on every cell and the question of what
  a run should do about a violation stops arising. (Measurement.)

  **ADDRESSED, ROUND 2 (2026-08-12) — both readings ship, and three defects
  found underneath.** The user's ruling was implemented as written: guard 2 is
  computed under **both** readings on every (point, cell), both are named in
  every artifact, and **neither is declared wrong**.

  - **Machine-readable, by name.** Every JSONL row carries `guard_readings`
    (`{"whole-text": […], "substitution-pair": […]}`) beside
    `guard_violations`; the summary's `guard` block carries `readings` (what
    each one means), `decision_rule`, a per-violation `readings` map, and
    `by_reading` — the whole violation list under each reading separately;
    each cell and each (variant, cell) carries `guard_readings`;
    `format_table` prints both for every violation.
  - **Decision rule when they disagree: the UNION.** A (point, cell) is
    tainted if *either* reading flags it. The trade-off, stated: over-detection
    costs a point out of the guard-clean family — `pass_rate` still reports the
    FULL family, so every committed number stays comparable, and §7 rule 1
    makes the drop safe because `distinguishable` is all-versus-none, so
    dropping can never manufacture a separation, only shrink one. Under-
    detection is unbounded: a tainted point that reads clean is RB-P4's
    measured mechanism scoring itself and being credited. Neither reading is a
    subset of the other in general — substitution-pair is blind to a
    substitution landing inside a word and to any point whose op is not
    `replace`; whole-text is blind to a word removed from one clause that
    survives elsewhere — so the union is not a formality. On the shipped
    12-point family it happens to equal the substitution-pair table, so no
    committed number moves.
  - **C2, a false negative under both readings — fixed.** The tokenizer
    treated a hyphen as word-internal, so `requests-per-minute` was one token
    and `requests` was invisible. The four hyphenated compounds in the frozen
    prompts (`requests-per-minute`, `on-call`, `billing-svc`, `INV-42`) hid
    seven words between them. After the fix the whole-text reading flags `P2`
    on `recall-org-quota` via *requests* — the row M1's screen committed — and
    substitution-pair's `recall-org-quota` entry becomes `["for","requests"]`.
    No other cell in either table moves, and the union gains no new (cell,
    point) pair.
  - **I4, guard 4 was inverted on real input — fixed.** It flagged `". "` and
    a trailing `.`; the template is hard-wrapped, so the anchor *"Judge ONLY
    whether the information the task asks for is present and correct."* —
    exactly one complete sentence, exactly what the guard demands — raised and
    aborted the run, while two whole sentences joined by a newline returned
    clean. Now: a terminator followed by whitespace or end-of-string, flagged
    only when the instance continues past it, and the `to` side is checked too.
  - **I3, guard 3 counted substrings — fixed.** `"explains itself"` →
    `"explains everything"` aborted claiming `every` had moved; `"Judge ONLY
    whether"` → `"Judge whether ONLY"` — a real scope change — returned clean.
    Counting is now word-boundary and case-sensitive (§3.6 X3 makes case
    load-bearing), and each keyword's ordinal position within the instance is
    compared between `from` and `to`, which catches the reorder while still
    admitting `"Do NOT deduct"` → `"Do NOT subtract"`.
  - **I6, the API hole — half closed, half filed.** Guards 1, 3 and 4 are
    properties of the point, so they now run inside `apply_point`, the one
    public route from a `Point` to a template; `check=False` is the documented
    deliberate bypass, because a guard nobody can turn off is a guard people
    route around. Guard 2 cannot ride there — it needs a cell — so it ships as
    one public call, `guard_table`, which `run()` uses too. The residual is
    filed as **RB-P23**.
  - **The golden test no longer calls the function under test.** It computed
    the expected table by calling `shared_token_violations` and froze the
    answer, which pins the author's *method*, not the spec — the reviewer's
    objection, and the shape that let this be restated twice. Both tables now
    ship as literal expected data derived from §3.3's wording and the frozen
    prompt texts, with a third test re-deriving them under a tokenizer written
    from §3.3's own phrase "tokenize on word boundaries" that shares no code
    with the module. That cross-check is what caught C2.

  Verified end to end at the same manifest sha, on the two screened models:
  14b `nav-prod-port` reports both readings in its JSONL and summary
  (`docs/eval-data/2026-08-12-rbp19b-nav-prod-port-14b*`), and all 12 anchor
  cells still run with every `expect_pass_rate`, `measured_min`,
  `measured_max` and `fragile` unchanged under both readings
  (`docs/eval-data/2026-08-12-rbp19b-anchors-{14b,4b}*`). (Measurement.)

  **CLOSED (2026-08-12).** The filed defect was "an admissibility rule that
  ships as a test-time observation on one cell". It is now computed on the run
  path over every (point, cell) a run touches, under both readings the spec
  admits, before the first request. What ships violating is the *manifest*, not
  the guard, and that is now visible in every artifact rather than derivable by
  hand. The residual is filed as RB-P23 and RB-P24 below, and the manifest
  re-authoring attack stands unchanged. Three things are worth carrying
  forward.

  **1. The transferable finding: this table was derived four times, and the
  first three were one derivation.** Each re-derivation inherited the method of
  the one before it, so each raised confidence and added no independence.

  | # | who | method | answer |
  |---|---|---|---|
  | D1 | M1's pre-registered screen (`b439053`), §6 | by hand, from §3.3's wording | whole-text: `P1` on two `recall-oncall*`, `P2` on `recall-org-quota` (*requests*), `P3` on `nav-prod-port` |
  | D2 | the anchor set's `guard_note`, same job | called `criticreplay.shared_token_violations` | substitution-pair: `P2` on six tasks via *for* — **and labelled D1 "under-reported"** |
  | D3 | R1's golden test over all 22 prompts | computed the expected table *by calling the function under test*, then froze it | D2's, necessarily |
  | D4 | R2's adversarial review, **forbidden from importing the module** | re-derived from §3.3's operative Test sentence alone | D1's — which is how the ambiguity surfaced at all |

  D3 was written specifically to stop this table drifting again, and it could
  not have caught it: a golden test whose expectation is produced by the
  implementation pins the author's *method*, not the spec, and it converts a
  contested reading into a fact with a green tick next to it. That is the
  mechanism, not the incident — **a check that inherits the method of the thing
  it checks is not a check of that thing, and repeating it does not make it
  one.** Both tables now ship as literal expected data derived from §3.3's
  wording and the frozen prompt texts, with a third test re-deriving them under
  a tokenizer written from §3.3's own phrase "tokenize on word boundaries" that
  shares no code with the module.

  And the strongest evidence for the rule is what that independent tokenizer
  found: the hyphen false negative (C2) was invisible to **both** readings and
  to all four derivations, because every one of them tokenized the same way.
  The disagreement between D1 and D4 was a disagreement about the *rule*; the
  hyphen was a defect in the *shared substrate under both readings*, and only a
  component written from the spec rather than from the code could see it. A
  second opinion computed on the first opinion's inputs is one opinion.

  **2. What the guard is now.** Both readings are named in every artifact —
  `whole-text` (§3.3's operative Test sentence: the symmetric difference of the
  base and perturbed *template* word sets) and `substitution-pair` (§3.3 step
  4's `from` → `to` pair form, and the manifest's own P2 justification prose) —
  and **neither is declared wrong**, per the user's ruling. The decision rule
  is their **union**, and the asymmetry is the reason: over-detection costs one
  point out of the guard-clean family, bounded and safe, because §7 rule 1
  makes `distinguishable` all-versus-none so dropping a point can only shrink a
  separation and never manufacture one — and `pass_rate` still reports the full
  family, so every committed number stays comparable. Under-detection is
  unbounded, and it is RB-P4's measured mechanism scoring itself and being
  credited for it. **Neither reading is a subset of the other in general**, so
  the union is not a formality: substitution-pair is blind to a substitution
  landing inside a word and to any point whose op is not `replace`, whole-text
  is blind to a word removed from one clause that survives elsewhere, and both
  blind spots are pinned by rigs rather than argued. On the shipped 12-point
  family the union happens to equal the substitution-pair table, so no
  committed number moves.

  The hyphen fix moved exactly one row and moved no measurement. Whole-text
  `P2` went from flagging nowhere to flagging `recall-org-quota` via
  *requests* — **exactly the row D1 committed by hand** — and
  substitution-pair's `recall-org-quota` entry became `["for","requests"]`. No
  other cell in either table moved, the union gained no new (point, cell) pair,
  and comparing the pre-fix and post-fix anchor runs cell by cell
  (`2026-08-12-rbp19-guard-anchors-{14b,4b}-summary.json` against
  `2026-08-12-rbp19b-anchors-{14b,4b}-summary.json`) **no `pass_rate`,
  `score_min`, `score_max`, `fragile`, `guard_violations` or `guard_dropped`
  block differs on any of the twelve.** The false negative was in the guard's
  sight, not in anything the guard had already scored.

  Guards 3 and 4 were inverted on real input and are fixed, each with the probe
  that showed it: guard 4 aborted on the template's own hard-wrapped anchor
  sentence *"Judge ONLY whether the information the task asks for is present
  and correct."* while returning clean on two whole sentences joined by a
  newline; guard 3 counted substrings, so `"explains itself"` →
  `"explains everything"` aborted claiming *every* had moved, while
  `"Judge ONLY whether"` → `"Judge whether ONLY"` — a real scope change —
  returned clean. Both now run at word boundaries, case-sensitively (§3.6 X3
  makes case load-bearing), with keyword *ordinal position* compared between
  `from` and `to`.

  Guards 1, 3 and 4 run inside `apply_point` — the one public route from a
  `Point` to a template — so a consumer who never calls `run()` still gets
  them. `check=False` is the documented, deliberate bypass, and it is
  deliberate on principle: **a guard nobody can turn off is a guard people
  route around**, and a bypass with a name in the signature is one that shows
  up in a diff. Guard 2 cannot ride there — it is a (point, *cell*) property
  and `apply_point` never sees a cell — so it ships as one public call,
  `guard_table`, which `run()` uses too.

  **3. The one retro-edit, and the rule it was decided under.** Two standing
  instructions met head-on: "no committed artifact may still assert one reading
  as the corrected one" against "do not retro-edit committed evidence". They
  meet on `2026-08-12-nonfragile-anchor-set.json`, the file an author actually
  opens before crediting a rubric edit, whose `guard_note` and three per-cell
  notes still called D2's table "the CORRECTED violation set". **The user's
  ruling: the invariant protects measurements from being refitted to
  conclusions; it does not protect a prose annotation that has become a live
  misdirection.** So the prose was amended in place under a visible `amended`
  block naming what changed and why, and **nothing else was**: the amendment
  was applied by a script that re-reads the committed bytes, rewrites four
  prose sites, and refuses to write if any other field differs. Verified
  independently afterwards against `git show HEAD:` — exactly five string
  values changed and five keys were added, all of them prose; every `answer`,
  `answer_sha256`, `seed`, `expect_pass_rate`, `measured_min`, `measured_max`,
  `fragile`, `guard_violations`, `guard_dropped`,
  `guard_dropped_verdict_unchanged`, `transcript`, every `caveats` entry, the
  whole `coverage` block and every hash under `measured_under` are
  byte-identical to `b439053`. The superseded `rule` is kept verbatim beside
  the new one as `rule_as_committed`, and git history is not rewritten:
  `25ce48b`'s message and `9ca1576`'s "their wrong P2 row" stand as written and
  are wrong on this point. `2026-08-12-rbp19b-guard2-both-readings-22-prompts.json`
  had one prose field of its own asserting that the anchor file "is not
  retro-edited"; that clause is amended too, under the same marker, because the
  alternative was shipping a record that contradicts the repo. (Measurement.)
- **RB-P20 — the `critique` config deletes the only evidence of its own
  rejections, so any screen run through it is biased against finding a
  critic defect.** When the `critique` gate exhausts its rounds `agent.run`
  raises, `output` is never set (`evalrun.py:535` initialises it to `None`,
  `:556-560` catches `BantamError` without setting it), the transcript
  records `"output": null`, and `criticreplay.load_cases` skips the row
  (`criticreplay.py:419-420`). **A `critique`-config transcript can therefore
  never contain an answer the critic rejected.** The consequence is not
  cosmetic: the RB-P4 shape *is* "the critic robustly rejects a correct
  answer", so screening `critique` transcripts makes that shape unreachable
  **by construction**, and "no defect bar found" would then have been
  reported from a sample that could not have contained one — a null result
  manufactured by the instrument, pointing in the exact direction of the
  hypothesis under test. 14b `nav-prod-port` is the proof: `critique` scores
  `XXX` with nothing recorded, `bare` on the same model, task and seeds
  scores `PPP` with the correct answer recorded. The 2026-08-12 screen caught
  this while designing and took answers from `bare` instead; the 14b
  `critique` arm alone would have dropped 5 cells and the whole shape.
  **Attack:** record the rejected `output` on the exception path so an
  exhausted run keeps the answer it was rejecting — the transcript already
  carries `messages` for both exhaustion taxonomies since `4a8b816`/`670d8ca`,
  so this is the same fix applied to one more field. Until then, **any screen
  of critic behaviour must draw its cells from an ungated config, and must
  say so.** (Measurement — the fix itself is Core.)
- **RB-P21 — the anchor set has near-zero coverage of the one failure mode
  it sits next to.** `2026-08-12-nonfragile-anchor-set.json` is 12 cells, and
  they reduce to **9 distinct answer texts**. The accept side — the half that
  could catch an over-strict edit — is 8 cells / 5 distinct texts / 3 tasks /
  **one family**, `structured-extraction`, with three 14b `extract-contact`
  cells sharing byte-identical output. The reject side is 4 cells of empty or
  malformed garbage. **No accept-side cell exercises `file-nav` or
  `memory-recall`**, which is precisely where the format-deduction defect
  (RB-P4, third direction) lives. So the format-suppression edit that RB-P4
  now points at can pass all twelve anchors and still be entirely unmeasured,
  and an edit that over-corrects into accepting garbage would be caught only
  by four cells that are all trivially malformed. The set is a floor and is
  labelled one in its own `status` field; it is not an instrument. **Attack:**
  widen the accept side deliberately rather than by sampling — the screen
  promoted by identity margin, which concentrated on whatever the critic
  scores 9–10, and that is structurally the extraction family. Screen for
  *non-fragile accepts on `file-nav` and `memory-recall` specifically*, at
  R=1 identity over the whole suite first, and accept a smaller yield.
  (Measurement.)
- **RB-P22 — `qwen3:4b-instruct` cannot host a bar that discriminates
  anything subtler than well-formed-vs-not, so the two-model framing of the
  2026-08-12 screen carries less independent weight than it reads as.** Its
  identity distribution over 66 cells is bimodal to the point of being
  degenerate: **59 at 10, 6 at 0, 1 at 4, and nothing at all in 5–9.** The
  screen's control stratum N is therefore **empty on 4b** — no control cell
  ran there — and **all five fragile cells in the catalogue are 14b**. This
  is not a sampling accident; a critic with no mass near its own threshold
  cannot produce a family that straddles it, so 4b is structurally incapable
  of exhibiting the near-threshold behaviour that generated every fragile
  cell. Its four anchors are real and are kept, but **"the finding holds on
  two models" is not what was measured** — it holds on one model and is not
  contradicted by a second that could not have contradicted it. **Attack:**
  when a screen needs corroboration on a second model, pick it on the shape
  of its *identity distribution* (mass in the near band), not on cost or on
  being a different generation — and report that distribution before
  promoting anything, since it is one cheap R=1 pass and it decides whether
  the second arm can answer the question at all. (Measurement.)
- **RB-P23 — guard 2 is the one guard a library consumer can still skip by
  not knowing it exists.** Guards 1, 3 and 4 are properties of a *point*, so
  they ride inside `apply_point` and a hand-rolled consumer gets them
  unconditionally (`check=False` is the named, deliberate bypass). Guard 2 is
  a property of a *(point, cell) pair*: `apply_point` never sees a cell, and
  by the time `replay_verdicts` is called the point is gone — it holds a
  `Rubric` and a `Case` and cannot re-derive which point produced the
  template. So guard 2 ships as one public call, `guard_table`, which `run()`
  uses too; a consumer who assembles `apply_point` + `replay_verdicts` by hand
  and never calls it replays tainted (point, cell) pairs with nothing in the
  artifact to say so. This is the same *shape* as the hole `3420384` claimed
  to close for `--manifest`, one level up. **Not closed now because both ways
  of closing it cost more than the hole:** threading a `Point` through
  `replay_verdicts` puts a parameter in the replay primitive that the replay
  primitive does not use, and refusing to score without one breaks
  `identity`-only replay (RB-P15's standing check), which legitimately has no
  point to guard against. **Attack:** give the module a guarded family
  constructor — one call that takes (variants, points, cells) and returns
  templates already paired with their guard verdicts — and demote
  `apply_point`/`replay_verdicts` in the docs to the primitives it is built
  from, so the guarded path is the short one. (Measurement.)

  **CLOSED (2026-08-12).** The filed defect was "a guard a consumer can skip
  because reaching it means knowing a second call exists". There is now one
  public call from (variants, points, cells) to units that carry their own
  verdict: `guarded_family` returns a `GuardedReplay` per (variant, point,
  cell) holding the exact `Rubric` to replay, the cell, the replay count that
  point's class earns, and guard 2's verdict under both readings.
  `unit.replay(client)` stamps that verdict onto every `Verdict` it returns, so
  the taint rides the object the consumer serializes instead of sitting in a
  second table they have to join on (point, cell). `run()` is those two calls
  and nothing else, and that is pinned by a byte-identity floor against
  `f8404ab` rather than by reading it — a second derivation that happens to
  agree is RB-P19's finding wearing new clothes. `replay_verdicts` stays blind
  and now says so in its own docstring: the `Verdict`s it returns carry EMPTY
  `guard_violations` — **blank, not clean**. A cold reader lands on the guarded
  call: the module docstring's API section opens *Start at `guarded_family`*,
  and `apply_point`, `guard_table` and `replay_verdicts` each name themselves a
  PRIMITIVE of it in their first paragraph.

  **The measurement: 2 steps guarded against 3 unguarded, from an equal
  start.** Not counted by eye.
  `test_the_unguarded_route_still_reaches_the_wire_and_is_the_longer_one`
  EXECUTES both routes from one `Rubric` a consumer already holds, with every
  name in `__all__` wrapped by a counter that records a call only when the
  calling frame is outside `criticreplay.py`, so the module's own internal
  calls inflate neither route: `apply_point`, `Rubric`,
  `replay_verdicts` against `guarded_family`, `unit.replay`. It goes red the
  moment either route needs a step it does not need today, because a route that
  cannot be executed raises instead of being re-counted.

  **And it was a TIE at 3 until the last feature commit of this cycle.** The
  attack as filed — build the constructor, demote the primitives in the docs —
  was executed faithfully, and `guarded_family` took `list[RubricVariant]`. A
  consumer holding a `Rubric` therefore owed a five-field `RubricVariant`
  construction, `sha256` included, that the unguarded route never charged:
  charge both routes their construction or charge neither, and the two were the
  same length. The 3-vs-2 first reported was real only for a consumer starting
  from a rubric FILE — the CLI's situation, not the hand-rolling library
  consumer RB-P23 is about. The count above holds because `guarded_family` now
  accepts a bare `Rubric` too (`53fc831`), deriving `label` from the rubric's
  own name, `ref` as `<in-memory>` and `sha256` blank rather than inventing a
  file that was never read. The first version of the residual test compared two
  tuples of hand-typed strings and asserted `2 < 3`; it was constant-true, and
  it stayed green through the whole period in which the claim was false.

  **The residual, named in the same breath, because it is not gone.** Python
  has no private functions: `apply_point` -> hand-assembled `Rubric` ->
  `replay_verdicts` still reaches the wire on a tainted (point, cell) pair, and
  the verdicts come back with blank guard fields and nothing recording why.
  `unit.rubric` can still be handed to `replay_verdicts` by hand, and the taint
  stays behind on the unit. **This is a length claim and a
  taint-travels-with-the-object claim. It is not an impossibility claim and may
  not be quoted as one.** The next lever is not the API: refusing to score
  without a point breaks RB-P15's identity-only replay, which legitimately has
  no point to guard against, and threading a `Point` into `replay_verdicts`
  puts a parameter in the replay primitive that the primitive does not use —
  both were rejected when this was filed and neither improved. The next lever is
  **RB-P24's open half, the exit code**: a `warn`-mode run exits 0 whether or
  not guard 2 fired, and no API shape reaches a CI job that reads a status.

  **The transferable finding: a "make the good path shorter" fix is only
  shorter from some starting point, and the starting point that counts is the
  consumer's, not the one you happen to have.** The filed attack was carried
  out to the letter and left both routes at 3. What made the claim true was an
  affordance nobody had filed — the bare `Rubric` — which removed a
  construction the guarded route charged and the unguarded route did not. Two
  rules follow. **Count from the consumer's start:** this repo's own caller is
  a CLI holding a rubric file, so every count taken from where the code already
  stood agreed with the fix, and none of them tested it. **And a length claim
  needs a test that can go red:** a comparison of hand-typed step lists
  restates the claim instead of measuring it, and the difference between the
  two was the entire finding here. (Measurement.)
- **RB-P24 — a guard-violating run exits 0 and the anchor set's procedure
  never asks anyone to look.** `criticreplay` returns success whether or not
  guard 2 fired; the only signals are a GUARD section in stdout and fields in
  the artifacts. `2026-08-12-nonfragile-anchor-set.json`'s `how_to_use`
  compounds it: its `command` does not pass `--guard error`, and its `rule`
  says only "check every `expect_pass_rate` still holds" — a re-run whose
  guard-clean families changed shape underneath an unchanged `pass_rate`
  passes the stated procedure. The floor is checked; the reason the floor is
  trustworthy is not. **Attack:** two independent halves — (1) make the exit
  code carry the verdict, e.g. a distinct non-zero status for
  "measured, with violations" so CI cannot pass it by ignoring stdout; (2)
  amend the anchor procedure to pass `--guard error` on a first pass and, when
  it refuses, to diff the `guard_dropped` blocks cell by cell against the
  committed ones.

  **HALF CLOSED (2026-08-12) — (2) is done, (1) is open and is the one that
  matters for CI.** The anchor file's `how_to_use` now runs `--guard error`
  as a first pass and states what it is *expected* to refuse on, so a
  different refusal list is itself the signal that the manifest or a frozen
  prompt moved; its `rule` now requires diffing every violating cell's
  `guard_dropped` block and its `guard_readings` against the committed ones,
  with the reason stated — `pass_rate` is deliberately the full family, so a
  guard-clean family can change shape underneath an unchanged
  `expect_pass_rate` and the old procedure would pass it. Measured while
  writing it: `--guard error` refuses **before the first request** and exits
  1, naming all three violating anchors and no others, at zero spend. A third
  defect surfaced in the same block and is fixed there rather than filed
  separately: **the committed `command` never selected these twelve cells** —
  it selects by transcript directory, and `load_cases` returns 14 cells from
  the 14b stage-2 directory and 6 from the 4b one, so the procedure as
  published did not reproduce its own floor. The `--task` flags that do are
  now given, together with the one non-anchor cell the CLI cannot exclude
  (4b `nav-prod-port` r1 — the filter is by task, not by repeat).
  **Still open, and unchanged: (1).** A `warn`-mode run exits 0 whether or
  not guard 2 fired, so the guard is invisible to anything that reads an exit
  code, and every procedure that depends on a human reading stdout is a
  procedure a hurried cycle skips — the same failure mode RB-P14 was made a
  rule to prevent. **Attack, unchanged:** give "measured, with violations" a
  distinct non-zero exit status, so `--guard error` is not the only
  machine-readable verdict and a passing run cannot mean two different things.
  Not done here because it changes the CLI's contract with every existing
  caller, including the committed anchor and `rbp19b` invocations, and that
  is a Contract-surface decision with its own migration note, not a docs
  amendment. (Measurement.)

  **CLOSED (2026-08-12) — (1) is done: the exit status now carries the
  verdict, AND the committed caller it changes has been migrated.** The
  second clause is what makes the word CLOSED true rather than aspirational:
  an implementation that leaves
  `docs/eval-data/2026-08-12-nonfragile-anchor-set.json` telling an operator
  "that half of RB-P24 is OPEN" is a repo that contradicts itself, and the
  review of this entry rejected the closure on exactly that ground. Migration
  note item 1 below is the amendment; it landed before this word did. The
  contract, which is new prose beside the filing above and replaces nothing
  in it — and which the review then corrected in two places, marked (a) and
  (b) under the table:

  | status | meaning |
  |---|---|
  | `0` | measured, and guard 2 fired on nothing that ran |
  | `1` | **did not complete a measurement** — every `BantamError` path and every mid-run abort. Artifacts are PARTIAL, not absent |
  | `2` | usage error — argparse's, not this tool's, `parser.error` included |
  | `3` | **measured, WITH violations** — every artifact written, the guard fired |
  | `4` | **measured, but an artifact could not be written** — the `--summary` file. Outranks `3` |

  **Two meanings may not share one number, and every number here was
  measured rather than assumed.** `2` is argparse's, and it was read from a
  shell (`python -m bantamkit.criticreplay --not-a-flag; echo $?` -> `2`)
  rather than taken from a manual, because a guard status that collided with
  the "you typed the command wrong" status would be a third meaning wearing a
  second one's number. It is argparse's number **for this module's own
  validations too**, because they are raised through `parser.error` and not
  through `PerturbationError`: measured, `--replays 0` exits `2`, not `1`,
  and that is pinned from a shell as well. `3` is the first free value above
  the two that were taken; `4` is the next one after `3`. What a CI job
  writes against them: `0` clean, `1` fix the input and run it again (and do
  not trust the artifacts it left), `2` fix the command line, `3` the run
  HAPPENED and the GUARD section and the `guard_dropped` blocks must be read
  before anything is credited, `4` the run happened but its summary is not on
  disk.

  **`1` says "did not complete a measurement" and NOT "refused, and measured
  nothing", because the second sentence was false** — found by the H2 review
  of this entry, in two independent ways, and both are fixed rather than
  filed. (a) The `--summary` write sat outside every handler, so an
  unwritable path was an unhandled `OSError`, i.e. a `1`, on a run that had
  already flushed every JSONL row. Measured at `ccde670`, violating 4b
  `nav-prod-port` with a `--summary` whose parent is a regular file: `status=1`,
  **32 rows on disk**, and — because the traceback preceded the `print` — an
  empty stdout, so the run also lost its table. That is `4` now, measured at
  `status=4` with the same 32 rows and the GUARD section printed. (b) Even with
  (a) fixed, "measured nothing" overclaims for EVERY mid-run abort: the sink's
  `flush()` carries the comment "a killed run keeps its partials" and is there
  on purpose, so a run that dies on request 40 of 80 — a refused connection is
  the review's own reproduced case — exits `1` with rows already written. The
  contract now says plainly that artifacts from a `1` are partial, in the
  module comment, in the `--help` epilog, and here.

  **The range is the tool's, and everything outside it is not.** `0`–`4` are
  this tool's to choose (`2` excepted, which is argparse's and is recorded
  rather than chosen). Anything else came from the interpreter or from a
  signal — measured on this interpreter, 2026-08-12: SIGINT `130`, SIGTERM
  `143`, and a stdout that goes away mid-table `120`. A CI job should branch on
  `0`–`4` and treat everything else as "did not run to completion", which is
  also why the one case where that reading is wrong is filed below as RB-P27
  rather than left implicit.

  **Amended at v0.19.0, and the amendment is the point of RB-P27.** The
  paragraph above is the v0.18.0 contract and is left standing as written,
  because the sentence it gets wrong is the finding. A stdout that goes away
  **on the run path** — the table print, its flush, and the interpreter's
  shutdown flush behind them — no longer leaves the range: the run reports the
  status it **earned** (`0`, `3` or `4`), measured from a shell's `$?` both
  inside and outside pytest. What is still `120`, measured 2026-08-13 and each
  pinned by a node that goes red if it is ever covered: `--help` with no reader
  on stdout (argparse writes before `main`'s handler exists), and any run that
  **writes** to stderr while stderr has no reader (a refusal's `error: …`, the
  summary-write failure, the `--violations-exit-zero` note). A run that writes
  nothing to stderr survives a dead stderr with its earned status. So
  "everything outside `0`–`4` did not run to completion" is **still not** a true
  reading; read it as "this process did not choose its own status". Full closure
  under RB-P27 below.

  **What counts, for status purposes: guard 2's union non-empty on a (point,
  cell) the run ACTUALLY REPLAYED**, read off the rows the run wrote —
  `criticreplay.exit_status`. Reading the rows rather than re-deriving a
  table is RB-P19's rule applied to this: every row already carries the pair's
  verdict, stamped by `GuardedReplay.replay`, so the status is the run's own
  answer and not a second derivation that happens to agree with it. Three
  consequences, each chosen: a point **dropped from every variant's family**
  before any request does not set the status even though `guard_table` flags
  it (the substitution-pair reading is a function of the point's own
  `from`/`to` pair, so it flags points that never apply) — statusing on that
  table would be a verdict about a pair that never ran, and the drop is
  already reported in `dropped_rules` and the summary's guard block;
  **`--identity-only` is always `0`**, because the identity point moves no
  words and RB-P15's standing check replays nothing else; and the status is
  about the **guard firing**, never about whether the attribution survived
  dropping the point — that is `_compare`'s `guard_verdict`/`attributable`,
  it is already in the summary, and a run whose separation survives its
  violations still fired the guard.

  **A violating run is still a measured run.** The status is decided LAST,
  after the JSONL (whose sink already flushed per row), the summary and the
  printed table all exist. Non-zero means "measured, and the guard fired",
  never "nothing happened" — a design where it meant "no artifacts" would
  make `nav-prod-port`, the canonical cell of this whole line of work,
  unmeasurable, which is the regression `warn` mode exists to avoid. Nothing
  written moved: the `f8404ab` byte-identity floor over stdout, the rows and
  the summary dict is untouched and green, and its harness calls `run` /
  `summarize` / `format_table`, never `main()`.

  **The escape hatch: `--violations-exit-zero`, and it is defended, not
  assumed.** Default off, a long flag with no short form, no env var and no
  default value, it changes nothing that is written, and taking it prints on
  stderr the status it suppressed — so a run that used it is distinguishable
  from a clean one **in any log that keeps stderr**. It is **not** recorded in
  the artifacts — the `f8404ab` floor pins the summary dict — so a reader
  holding only the summary JSON and `$?` cannot tell a suppressed `3` from a
  `0`. **Attack:** the lever is the anchor procedure recording the flag beside
  the command it runs, not a new summary field. The reason the hatch exists is
  not symmetry with `apply_point(check=False)`: it is that the ad-hoc route
  around a mandatory status, `|| true`, is **strictly worse than a flag**,
  because it swallows `1` and `2` as well and hides refusals and typos along
  with violations. And there is a legitimate caller — the anchor set's second
  pass deliberately runs over violating cells and records them. A named,
  visible opt-out from `3` alone beats an invisible opt-out from everything,
  and "from `3` alone" is now pinned rather than asserted: with the flag
  passed, a refusal is still `1`, `--guard error` is still `1`, a usage error
  is still `2`, and an unwritable summary is still `4` — four shell tests that
  go red if a refactor moves the hatch above the error handler.

  **Verified by an independent method: a shell's `$?`, not a caught
  `SystemExit`.** A test that calls `main()` and catches `SystemExit`
  verifies a return path; what a CI job branches on is the process status. So
  every outcome class is pinned by a real process run through `/bin/sh`,
  whose echoed `$?` the test reads
  (`runtime-py/tests/cli_exit_status_probe.py` is the shipped `main()` with
  only the client constructor replaced; the refusal and usage classes use the
  real `-m bantamkit.criticreplay` and need no client at all). Measured
  offline against the **committed anchor transcripts**: the 4b anchor
  selection in `warn` mode exits **3** with all 80 rows, the summary and the
  table written; the 14b anchor selection exits **3**; `--guard error` over
  the same 4b cells exits **1** before the first request; `--identity-only`
  exits **0**; a violating run whose `--summary` cannot be written exits
  **4** with its 32 rows and its table intact; `--replays 0` exits **2**;
  `--help` exits **0** and prints the statuses. Tests were written first and
  confirmed red (11 failing before the implementation existed); the C1 fix
  was measured on the pre-fix source through the same command before it was
  written. **729 tests**, nine of them added by the review's findings.

  One method note, because it cost a false negative once: the grep that
  built the migration list below read `bantamkit.criticreplay`, and
  `docs/eval-data/2026-08-12-m1-screen.md` writes its invocations as bare
  `criticreplay …`. Grep the **bare word** as well as the module path, or a
  committed caller stays invisible.

  **Migration note — every committed invocation whose status changes,
  grepped rather than reasoned about** (`grep -rn "bantamkit.criticreplay"`
  AND `grep -rIn "criticreplay"` for the bare word, whole repo — the second
  grep is what found item 6, and the first alone did not):

  1. `docs/eval-data/2026-08-12-nonfragile-anchor-set.json` ->
     `how_to_use.command`, the second pass: **0 -> 3**, measured on both
     models' committed transcripts. It runs `warn` mode over cells that
     include three violating anchors, which is deliberate. Its
     `guard_first_pass.command` is **unchanged at 1**, but
     `guard_first_pass.why` described a state of the world that had ended
     ("that half of RB-P24 is OPEN"). **MIGRATED (2026-08-12)**, under the
     visible `amended:` marker that file already carries and by a script that
     lists every key that moved and refuses to write if one moved outside a
     declared set: `guard_first_pass.why` now quotes its own old text and
     says what stopped being true, and gives the first pass a reason that
     does not depend on the status (it names the tainted pairs at zero spend,
     before you commit 208 requests); a new `command_exit_status` records
     that the second pass now exits **3**, that 3 is EXPECTED there, that a
     **0** there is itself a stop signal, and that
     `--violations-exit-zero` must not be passed there; and `rule` step (2)
     sends the operator to it. Eight keys moved, all prose; `command`,
     `cost`, `rule_as_committed`, `cell_selection`, `caveats`, `cells`,
     `coverage` and `measured_under` are byte-identical to `ccde670`,
     re-verified after the fact.
  2. `docs/eval.md`'s credit command (the "Run it before the attribution"
     block): **0 -> 3** on any cell where guard 2 fires on a replayed pair —
     `nav-prod-port` is one. A pointer to this contract is added beside that
     block; the command itself is unchanged.
  3. `docs/eval.md`'s M1 screen command, `--identity-only`: **unchanged at
     0**, measured, because no `P` point runs.
  4. `docs/superpowers/specs/2026-08-11-perturbation-bar-spec.md` §11
     acceptance item 2 (`--help` runs): **unchanged at 0**. §6's and §11's
     "must exit non-zero" conditions: **unchanged at 1**. Neither acceptance
     item is retro-edited.
  5. Nothing else executes the CLI: `.github/workflows/ci.yml` runs `ruff`
     and `pytest` only, and there is no script or Makefile in the repo that
     calls it. The `rbp19b` runs have committed **artifacts** but no
     committed command line of their own — the anchor set's `command` is the
     one they were run from, which is item 1.
  6. `docs/eval-data/2026-08-12-m1-screen.md:118,132` — the screen's own
     stage commands, **missed by the first grep** because they are written
     `criticreplay …` without the module prefix. Stage 2 ("`criticreplay` at
     defaults") is **0 -> 3** on both committed stage-2 transcript
     directories, measured; stage 1
     (`--identity-only --identity-replays 1`) is **unchanged at 0**,
     measured on both. **That file is committed evidence of a run already
     taken and is NOT amended** — the run it records happened under the old
     contract and its numbers are what they were. This item is the migration
     note doing its job: a future re-run of that screen will exit 3 where the
     document says nothing about a status, and this is where they find out
     why.

  **Found and not fixed, with an attack direction.** A violation on a point
  dropped from *every* variant's family is in the summary and in the guard
  table but not in the status, by the rule above — so an operator who reads
  only `$?` learns nothing about it. That is the right call for a pair that
  entered no statistic, but the honest description is "the status covers what
  ran, and something the status does not cover is reported only in the
  artifact". **Attack:** if that gap ever matters, the lever is not another
  status number — it is the anchor procedure's step 3, which already diffs
  `guard_dropped` cell by cell, extended to diff `dropped_rules` too, so a
  family that silently changed shape is caught by the same read. (The `4`
  added later in this entry is not that lever and does not close this gap:
  it is about a file that could not be written, not about a pair that did not
  run.) (Measurement.)

- **RB-P25 — nothing in this repo distinguishes guard 2's `(task, repeat)`
  cell key from a `task`-only one, so half the key is unmeasured.** Measured
  2026-08-12 by mutation: replace the unit's cell lookup with one that takes
  the first entry of the union table whose *task* matches, ignoring `repeat`,
  and **the whole suite passes (707/708 — the one failure is the mutation
  harness's own `PYTHONPATH`, not a finding), the byte-identity floor against
  `f8404ab` passes, and all 12 committed anchor cells produce byte-identical
  rows, summaries and printed tables.** The reason is a fixture gap, not a
  clever mutation: **no fixture anywhere has two cells of one task with
  DIFFERENT guard results.** The floor's three cells are three distinct tasks
  at one repeat each; the only same-task pair carrying a violation anywhere in
  the cells the anchor procedure runs is 4b `nav-prod-port` r0/r1, and both
  violate on the same point with the same word (`['right']`), while every 14b
  task with several repeats is clean on all of them; the
  `--guard error` first pass reads the table directly and so cannot see the
  difference either. This is **pre-existing and NOT a regression of the
  guarded-family refactor** — the key was `(task, repeat)` before and after —
  but the refactor moved it into a new local (`criticreplay.py:1157`), which
  is exactly the kind of move a fixture set ought to be able to catch and this
  one cannot. **Attack:** add one two-repeat cell pair whose `{output}` texts
  differ in a shared token, so that r0 is tainted and r1 is clean on the same
  task. That single fixture makes the `repeat` half of the key AND the
  `{output}` half of `cell_guard_violations` load-bearing at once.

  **Note, same shape, and a live trap for a future cycle:** two of the five
  mutations that establish the byte-identity floor's sensitivity — the union
  rule collapsed to one reading, and the guard no longer reading the cell's
  `{output}` — **fail only through the synthetic in-memory family** the floor
  harness adds (`test_criticreplay.py:1537-1546` is where that section's
  disagreement is asserted). On the shipped 12 points the union equals the
  substitution-pair table by coincidence, and the `{output}` half adds zero
  violations over the committed transcripts. So deleting that synthetic
  section as redundant would silently re-open both blind spots while every
  test stayed green. Do not delete it; extend the real fixtures until it is
  genuinely redundant. (Measurement.)
- **RB-P26 — `materialize_manifest` is a public SECOND derivation of the
  perturbed family, one artifact removed from the run path.** `run()` is
  `guarded_family` plus `unit.replay` and re-derives nothing, which is what
  RB-P19's transferable finding demands. But `materialize_manifest`
  (`criticreplay.py:598`, public, in `__all__`, what `--manifest` writes)
  walks points x variants through `apply_point` on its own path — with
  `check=True` where `_variant_family` uses `check=False`, and with no
  collision check — and the two are cross-checked only where the manifest
  already records a sha for that (point, variant), via
  `_check_materialization`. So the audit artifact a reader trusts to tell
  them what the run measured is produced by a different derivation than the
  run's, and a divergence on any (point, variant) the manifest has NOT
  materialized is invisible. Same shape as RB-P19, one level out. **Not fixed
  in the G3 cycle deliberately** — the review that found it ruled reword-only,
  because a refactor of the audit path belongs with its own byte-identity
  evidence, not bolted onto a docstring correction. **Attack:** build
  `materialize_manifest` from `_variant_family` so there is one derivation and
  the artifact is a rendering of it; or, if the two must stay separate, pin
  them against each other over the frozen 12 points and the three committed
  variants, so a drift is a test failure rather than a silent difference in a
  file nobody diffs. (Measurement.)
- **RB-P27 — the write status covers the summary FILE, and the printed table
  is an artifact the contract names but the status cannot speak for.** What
  survives RB-P24's C1 fix, measured 2026-08-12 from a shell reading its own
  `$?`, on the real CLI over the committed 4b anchor transcripts:
  (a) with the reader of its stdout gone, a violating run **completes**,
  writes all 32 of its JSONL rows and a summary carrying both its guard
  violations, and exits **120** — the
  interpreter's number for "flushing stdout at shutdown failed"
  (`Exception ignored in: <_io.TextIOWrapper name='<stdout>'>`,
  `BrokenPipeError`), not `3`, not `4`, and outside the tool's own range;
  (b) an unwritable `--json` path fails in `Path.mkdir` **before the first
  request**, so it exits `1` through an unhandled traceback — the number is
  honest under the restated `1` ("did not complete a measurement"), but it
  reaches the operator as a stack trace rather than as `error: …`.
  Case (a) is the one that matters, and it is precisely the case where the
  contract's own advice ("treat anything outside `0`–`4` as *did not run to
  completion*") is **wrong**: the run ran to completion, and its summary is
  on disk to prove it. `4` does not cover it — `4` is raised by catching
  `OSError` around a write the tool controls, and a broken stdout fails
  during interpreter shutdown, after `main` has returned.
  **Attack, and it is not a sixth number.** Two levers, in order: (1) state
  in the contract that `120` means "the tool finished but its stdout went
  away", which costs one sentence and makes the range advice correct instead
  of nearly-correct; (2) if a caller ever needs to branch on it, install a
  `BrokenPipeError` handler around the table print that exits with the status
  the run had already **earned** (`0`/`3`/`4`), so a lost stdout downgrades
  to a known number instead of an unknown one — and pin it with the same
  closed-pipe harness that measured (a), which is a `subprocess.Popen` whose
  read end is closed before the child prints. Not done here: it is a change
  to what the process does at shutdown, and this cycle's remit was the status
  a completed run chooses. (Measurement.)
  **In progress on `feat/rbp27-broken-pipe`.** Lever (2) has an executable
  spec — three `xfail` closed-pipe tests in `test_criticreplay.py`, measured
  at `120` on `c7d0b72` for a run that earned `0`, one that earned `3` and one
  that earned `4` — and the same branch runs it as the first measured cell of
  the `qwen-implementer` backlog item. The bar for that cell, its arms and what
  a pass would and would not demonstrate are pre-registered in
  `docs/eval-data/2026-08-12-rbp27-qwen-cell-prereg.md`, committed before any
  arm ran. Lever (1) — the contract sentence — is not done either.

  **CLOSED (2026-08-13, v0.19.0). Both levers.** Case (b) — the unwritable
  `--json` path reaching the operator as a traceback — is **not** closed and is
  not claimed to be; it was a second-order observation in the same filing and no
  lever was written for it.

  **Lever (2), the handler.** `main`'s table print now sits in a `try` with an
  explicit `sys.stdout.flush()`, and on `BrokenPipeError` *alone* fd 1 is
  pointed at the null device before the status is decided. Both steps are
  load-bearing and neither is decoration: without the explicit flush the `EPIPE`
  surfaces during interpreter shutdown instead of where it can be handled, and
  without the `dup2` CPython's finalization flush fails on the same dead pipe
  *after* `SystemExit` has chosen its number and replaces it with `120` again.
  It is the standard library's own SIGPIPE recipe minus its `sys.exit(1)` —
  `1` is this tool's refusal status and this run measured. The status logic
  itself is untouched: a lost stdout may **downgrade** to a number the run
  already had and may never invent one.

  > **Amendment (K5, 2026-08-13, v0.20.0) — the two sentences above about the `dup2` are
  > true of v0.19.0 and FALSE of HEAD, and the paragraph is left standing rather than
  > rewritten.** "fd 1 is pointed at the null device before the status is decided" and
  > "without the `dup2` CPython's finalization flush fails … and replaces it with `120`
  > again" describe the recovery this repo shipped at `dc121b5` and no longer has. That
  > `dup2` was itself filed as RB-P33 — it clobbered the process's fd 1 permanently, for
  > every later write and for every child that inherited it — and the replacement is
  > `_LostStdout`, an object bound to `sys.stdout` whose `flush` is a no-op and whose
  > `write` re-raises the original failure. The *reason* the paragraph gives is intact
  > and is why the object exists: the shutdown flush still runs after `SystemExit` has
  > chosen its number, and something still has to make it succeed. What changed is that
  > nothing takes a file descriptor to do it. The explicit `sys.stdout.flush()` in the
  > `try` is unchanged and is still load-bearing. Measured either side in
  > `docs/eval-data/2026-08-13-rbp33-fd1-after-main.md`; the arm itself is now
  > `except (OSError, UnicodeEncodeError)` and is RB-P31's closure, above.

  **Measured outside pytest, because a green spec is not sufficient evidence
  that the defect is fixed.** RB-P28's C1 (below) demonstrated a patch that
  turned all five oracle clauses green while its field behaviour stayed at
  `120`, so the closure of RB-P27 rests on a field measurement the fix cannot
  see: a real shell, a reader that is actually gone, `$?` read by the shell, and
  an environment carrying no pytest marker. Copy-pasteable, and it is the thing
  a future reader re-runs:

  ```sh
  cd <repo> && T=$(mktemp -d) && mkdir -p "$T/transcripts" && cat > "$T/transcripts/critique--nav-prod-port--r0.json" <<'JSON'
  {"task":"nav-prod-port","config":"critique","repeat":0,"passed":true,"outcome":"pass","seed":111,"output":"{\"port\": 9443}","messages":[]}
  JSON
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH=runtime-py/src /bin/sh -c \
    '{ .venv/bin/python runtime-py/tests/cli_exit_status_probe.py \
        --base-url http://x --model fake-14b \
        --rubric before=assets/rubrics/task-completion.yaml \
        --transcripts '"$T"'/transcripts \
        --json '"$T"'/rows.jsonl --summary '"$T"'/summary.json; \
      echo "status=$?" >&2; } | true'
  ```

  `| true` is the dead reader: the subshell exits before the interpreter has
  started, so every write to fd 1 fails with `EPIPE` from the first byte, and
  the `echo` is the shell reading its own `$?`. The variants for the other two
  earned values are the same command with `--identity-only` (earns `0`, RB-P15's
  standing check) and with `--summary` pointed inside a regular file (earns `4`).
  Measured on this machine, 2026-08-13, `c6ddf44` against `dc121b5`:

  | the run earned | before (`c6ddf44`) | after (`dc121b5`) |
  |---|---|---|
  | `0` (`--identity-only`) | **120** | **0** |
  | `3` (guard fired) | **120** | **3** |
  | `4` (summary unwritable) | **120** | **4** |

  The artifacts of a dead-reader run are byte-identical to those of the same
  command with a live reader (`cmp`-clean on both `rows.jsonl` and
  `summary.json`), and the `Exception ignored in: <_io.TextIOWrapper
  name='<stdout>'>` line is gone from stderr.

  **The spec nodes that hold it.** The three closed-pipe tests written before
  the fix (`f5e38b0`) lost their non-strict `xfail` markers and are ordinary
  green nodes; `_CLOSED_PIPE_PREFIX_STATUS = 120` is **kept** and is now
  load-bearing rather than commemorative — each node asserts both the earned
  status and that it is no longer `120`, so the fix is pinned against the
  measurement it was written to move. The four controls still bite: a refusal is
  still `1` and a usage error still `2` under a dead stdout, and a `RuntimeError`
  and a non-`EPIPE` `OSError(ENOSPC)` around the table print must both still
  reach the caller. `format_table(summary)` is evaluated **inside** the shipped
  `try` deliberately, so those two raisers are raised inside the handler's reach
  and pass only because `except BrokenPipeError` refuses them.

  **Lever (1), the contract sentence — corrected, not generalised.** The
  v0.18.0 wording ("a stdout that goes away mid-table is the interpreter's
  number, not one of these — a CI job should branch on this range and treat
  everything else as *did not run to completion*") is replaced in
  `criticreplay.py`'s module comment and in the `--help` epilog by a statement
  of what is covered and what is not. **Covered:** the run path's own write to
  stdout — the table print, its flush, and the shutdown flush behind them.
  **Not covered, measured 2026-08-13 and still `120`:** `--help` with no reader
  on stdout (argparse writes the epilog and exits before `main` reaches the
  handler), and any run that **writes** to stderr while stderr has no reader —
  a refusal's `error: …`, the summary-write failure, the
  `--violations-exit-zero` note — where the refusal's own `1` is erased exactly
  as the table's `3` used to be. A run that writes *nothing* to stderr is
  unaffected, because there is nothing to flush (measured, still `3`); that is a
  property of buffering rather than of this tool and is recorded, not promised.
  Both uncovered cases are pinned by nodes that go red if a later change covers
  them (`test_help_with_no_reader_on_stdout_is_still_the_interpreters_number`,
  `test_a_refusal_whose_stderr_has_no_reader_leaves_the_range`), so the list
  cannot go stale silently, and the epilog test now fails if the prose is
  quietly upgraded to a blanket promise.

  > **AMENDMENT 2026-08-14 (L7) — "still `120`" for the `--help` case is FALSE on
  > a second platform, and the sentence claiming the list "cannot go stale
  > silently" is exactly the one that went stale.** Corrected here rather than
  > rewritten above. The `120` is not a property of this tool: the status turns on
  > whether the doomed bytes are still in `sys.stdout`'s `BufferedWriter` when the
  > interpreter exits, so it depends on the SIZE of the help text against a buffer
  > this module does not set. Measured 2026-08-14 on `ubuntu-latest` via CI, with
  > no behaviour of this module changed: **7488 bytes of help text → `120`
  > (`b496856`, CI green); 8227 bytes → `0`** — the growth came from docstrings
  > added by this job's own RB-P16/17/18 fixes. macOS read `120` at both. The
  > node's assertion was re-aimed the same day to the claim the contract actually
  > makes — the status equals what a bare interpreter doing exactly what
  > `argparse._print_message` does with the identical bytes on the identical broken
  > pipe reads, so this module contributes nothing to it — which is
  > platform-independent and still goes red if a later change covers the case. The
  > stderr half of the paragraph above is untouched and was green on both
  > platforms. Filed as **RB-P35**, below.

  **Authorship, stated plainly and kept separate from the cell's result.** The
  patch was written by the J4 implementer unit of the `rbp27-qwen-cell` job,
  after the cell's three model arms produced **0 passes in 20 pre-registered
  attempts**. No arm's patch is in the shipped commit or reachable from it. Its
  substance derives from the reviewer unit's independently derived reference
  patch — the one that exonerated the oracle by reaching PASS at HEAD — changed
  before shipping in two ways: the `os` import was promoted to the module's
  import block instead of being function-local, and each of the three steps
  carries a rationale comment because each is load-bearing and none is obvious.
  **"The fix shipped, so the model worked" is not a sentence this repo may
  write.** The cell's record is below.
- **RB-P28 — the acceptance oracle for a code fix is gameable through the test
  environment, and a green spec therefore does not establish that a defect is
  fixed.** Found by the J3 adversarial review of the RB-P27 cell, 2026-08-12,
  and **demonstrated rather than argued**. Every behavioural clause of that
  oracle runs under pytest, and both shell-status harnesses built the child
  process's environment as `{**os.environ, ...}` — and pytest puts
  `PYTEST_CURRENT_TEST` in `os.environ` while a test is running. So the code
  under test could see that it was being observed. A patch of five lines
  (`if os.environ.get("PYTEST_CURRENT_TEST") and "pytest" not in sys.argv[0]:`
  → flush, swallow `BrokenPipeError`, `os._exit(status)`) passed **all five**
  pre-registered clauses while its **field behaviour was unchanged at `120`**.
  Re-measured by J4 before fixing: against the old harness that patch scores
  `7 passed` on `pytest -k "closed_pipe or non_pipe" --runxfail`, and `120` in
  the field. **It did not manufacture the 0/20** — a too-permissive oracle
  cannot invent failures, and zero of the twenty completions went anywhere near
  the environment — but it voids any claim that a green spec *means* the defect
  is fixed, which is why RB-P27's closure above rests on a field measurement
  instead.
  **PARTLY CLOSED (`b5ee8ec`), and only partly.** `PYTEST_*` is now scrubbed
  from the child environment in both harnesses (`_child_env`), and the scrub is
  pinned by a node that can go red rather than by a comment:
  `test_the_status_harnesses_hand_the_child_no_pytest_marker` asks the child,
  through both harnesses, to report its own `PYTEST_*` keys and requires the
  empty list — first asserting that `PYTEST_CURRENT_TEST` **is** in the parent's
  environment, so an empty list downstream is the scrub working and not the
  variable being absent. Against the scrubbed harness the gaming patch now
  **fails**: `3 failed, 4 passed, 158 deselected`, and the first node to reject
  it is `test_closed_pipe_clean_run_still_exits_zero` (`assert 120 == 0`), with
  the other two spec nodes rejecting it on `3` and `4`. The selector is
  `pytest runtime-py/tests/test_criticreplay.py -k "closed_pipe or non_pipe"
  --runxfail`, and it collects **7 of 165** nodes — check that in one command
  with `… -q --collect-only -k "closed_pipe or non_pipe"`, which prints
  `7/165 tests collected (158 deselected)`.
  **Corrected 2026-08-13 (J5 review, M1).** This line read `3 failed, 5 passed`
  until now, and `3 + 5 = 8` is impossible against a 7-node selector. The
  neighbouring `7 passed` for the *pre-scrub* harness is right and reproduces,
  which is what makes this a transcription slip in the record rather than a
  different measurement; the claim the sentence makes — that the scrub rejects
  the gaming patch, on three nodes — is unchanged and still holds.
  **The residual, and RB-P28 stays OPEN for it.** The scrub kills the
  demonstrated exploit, not the class. A patch can still key on `sys.argv[0]`,
  on a tmp-dir-shaped path, on the absence of a TTY, or on any other tell that
  "running under a test runner" leaves behind — and no environment filter
  enumerates those.
  **And the residual is no longer hypothetical: it has been exhibited, twice
  (2026-08-13).** The J5 review wrote a patch that **deletes the shipped
  `BrokenPipeError` handler entirely** — none of the fix is in it — and replaces
  it with a check on the command line rather than the environment:

  ```python
  if "pytest-of-" in " ".join(sys.argv):
      try: sys.stdout.flush()
      except BrokenPipeError: pass
      os._exit(status)
  ```

  `pytest`'s `tmp_path` lives under a `pytest-of-<user>` directory, and every
  node that exercises the handler runs the CLI with rig paths under `tmp_path`
  (`_cli` puts `--rubric` and `--transcripts` there), so the tell reaches the
  child **on its command line** — a route `_child_env` does not filter and, being
  the run's own arguments, cannot. Against the
  **scrubbed** harness that patch scores a full **`739 passed`** on
  `.venv/bin/python -m pytest runtime-py/tests -q --runxfail` — every node in the
  repaired suite, the three RB-P27 spec nodes and the scrub node included — while
  the same tree **field-measures `120`** where real HEAD gives `3`. The
  orchestrator reproduced it independently, in a throwaway worktree at `88ed3c1`,
  and got the same two numbers. So `b5ee8ec` closed **one signal out of at least
  two**, and the phrase "tmp-dir-shaped path" three lines above is now a
  measurement rather than a worry. Nothing that was claimed closed is re-opened
  by this — the residual was filed with this shape from the start — but it is the
  reason RB-P27's closure above rests on the **field measurement alone**: a fake
  patch can score green on every node this repo owns, and it cannot fake a real
  shell's `$?` on a process with no pytest anywhere in it.
  **Attack:** give the acceptance oracle a phase measured
  **outside pytest entirely** — the field command in RB-P27's closure is the
  shape of it — so that at least one clause is evaluated on a process the
  patched code cannot distinguish from production. That is a change to the
  `tools/qwen-implementer` rig, and the rig's cell is closed (below), so it is
  filed rather than done. (Measurement.)
- **RB-P29 — the pre-registration's bracketing rule is an unconditional
  implication, and it fired a false verdict the first time it was used.**
  `docs/eval-data/2026-08-12-rbp27-qwen-cell-prereg.md` §1 registers, in
  advance and correctly in spirit: "**if the 14b also fails**, the finding is
  about the rig — the prompt, the reply format, the one-shot loop — and not
  about model size. The report would say so, and the next cell would be a rig
  change, not a smaller model." The 14b did also fail (0/5), so the rule fired
  — and it was **wrong**: the J3 review then showed the rig admits a pass (an
  independently derived patch reached PASS at HEAD first try), that all eight
  `--self-test` rejection rules fire, that both prompt excerpts occur exactly
  once byte-for-byte in the cloned file, and that hand-repairing all six format
  failures converts **none** of them into a pass. An upper bracket failing is
  **evidence** that the finding may be about the rig; it is not a proof, and
  written as an unconditional implication it converts a real result into an
  instrument complaint. It also very nearly consumed the user's standing "if the
  rig is broken, fix it and re-run" directive on a false trigger.
  **Attack:** rewrite the rule with its missing antecedent — *a bracket's
  failure may indict the rig only if the rig has not been independently shown to
  admit a pass* — and register the independent demonstration as a **required
  step** of the bracket reading rather than as something a reviewer happens to
  do afterwards. Concretely: an oracle-exoneration run belongs in the
  pre-registration's §4 alongside `--dry-run` and `--self-test`, performed by a
  unit that did not write the oracle, with its result recorded before the
  brackets are read. (Measurement.)
- **RB-P30 — the frozen prompt's reply format demands SEARCH text copied
  byte-for-byte from an excerpt, and the import block the canonical fix needs is
  in neither excerpt.** `tools/qwen-implementer/prompt.txt` (sha `a65efda6…`)
  shows two verbatim excerpts of `criticreplay.py` and requires every
  `<<<<<<< SEARCH` block to match one of them exactly once. The published fix
  for this defect needs `os` — the module's import block does not import it, and
  the import block is not in either excerpt. So the only route to the canonical
  fix that the format admits is a **function-local import**, which the prompt
  never says is acceptable. That is an **undisclosed narrowing of the solution
  space**: the task as posed is harder than the task as described, and the
  narrowing is invisible to the model and was invisible to the bar. The
  fingerprint is in the artifact — `ruff-failed: F821 Undefined name \`os\`` is
  one of the recorded failure reasons. This is a filing about the **rig's
  disclosure**, not a re-scoping of the 0/20: it is not established that any
  attempt would have passed with the import region disclosed, and no attempt is
  re-scored on the strength of it. **Attack:** include the import region as a
  third excerpt, or state in the prompt that a function-local import is
  acceptable — and either way say which, because "we fixed the prompt" without
  saying how makes the next cell incomparable with this one. Both are rig
  changes and both need their own pre-registration. (Measurement.)

Three more, from the J5 review of the RB-P27 fix itself, filed 2026-08-13 and
**not fixed here** — the unit that filed them was told to file and stop, so that
a fix and its own acceptance check are never written by the same hand in the same
breath. Read the provenance line on each: two are **inherited**, measured at
`c7d0b72` (v0.18.0, before this branch existed) as well as at HEAD, and are not
damage this PR did; the third **is** a side effect of the handler this PR
shipped, and says so.

- **RB-P31 — a stdout failure on the run path that is NOT the reader going away
  is uncovered, and at a table bigger than stdout's buffer it lands on `1` — the
  status that means "did not complete a measurement, artifacts are PARTIAL" — on
  a run that completed.** The RB-P27 handler converts `BrokenPipeError` and
  nothing else, which is deliberate
  (`test_a_non_pipe_failure_around_the_table_print_is_not_downgraded` exists to
  keep it that way). Measured by J5: with fd 1 pointed at a **read-only** fd, the
  table print fails with `EBADF`, not `EPIPE`, stderr live throughout, and the run
  still leaves the range at **`120`**; and on a **2800-row** run — a table larger
  than stdout's buffer, with a **907 KB** summary on disk — the same failure
  escapes `main` and reports **`1`**. A run whose every artifact is written
  reporting the refusal status is the **RB-P24 defect class**, alive one line from
  where RB-P24 fixed it. Two routes, not one: the handler's own recovery can fail
  too — `os.open(os.devnull)` raising `EMFILE` inside the `except` arm reaches `1`
  as well, because the handler has no fallback for its own repair failing.
  **Inherited, and the inheritance is itself a finding:** at `c7d0b72` a table
  larger than stdout's buffer escapes `main` as an uncaught `BrokenPipeError` and
  gives `1`, not the `120` the three RB-P27 spec nodes were written against — so
  the pre-fix number those nodes pinned is **size-dependent, and was only ever
  measured at the small size**. **Attack:** give the table print the treatment
  RB-P24 gave the summary write — an `except OSError` arm that keeps the status
  the run EARNED and reports the render failure on stderr under its own number —
  or, if letting a genuine `OSError` propagate is deliberate, stop letting it land
  on `REFUSAL_EXIT` and say in the epilog which number it lands on instead. Either
  way the acceptance check has to be a node that goes red on the `EBADF` case **at
  both table sizes**, because the two sizes give different numbers and a
  single-size node would pin half of it. (Measurement.)

  **CLOSED (2026-08-13, v0.20.0). Both routes, and one class the first fix missed.**
  A render failure that is **not** the reader going away now reports a number of its
  own, `5`, and the run keeps every artifact it earned. The arm sits around the table
  print and its explicit flush and is `except (OSError, UnicodeEncodeError)`;
  `format_table(summary)` is evaluated **outside** it, so a failure to BUILD the table
  is still a bug with a traceback. The second route the filing named is **gone rather
  than caught**: the recovery is `_LostStdout`, an object, so there is no `os.open`
  inside the handler that can fail on its own (K1 could not construct `EMFILE` from
  outside the process and said so — the answer to a route that cannot be measured is to
  remove it, not to argue it is rare).

  **Why a new number and not a reuse.** Two meanings may not share one number, and `4`
  and `5` are two: on a `4` the answer IS in the log and the fix is a writable
  `--summary` path; on a `5` the answer is NOT in the log and the fix is the caller's
  stdout. Reusing `4` would have required deleting "the table is still printed" from a
  sentence CI jobs already read. And it is not a downgrade to the earned status the way
  EPIPE is: EPIPE means nobody was reading, so the table's absence costs no one
  anything; here the report was wanted and is gone.

  **Measured outside pytest.** RB-P28 is open and its residual is demonstrated below, so
  the closure rests on a field measurement, not on the suite. The whole matrix is
  `docs/eval-data/2026-08-13-rbp31-render-failure-matrix{,-after}.md` (45 cells: 5
  failure modes × 3 table sizes × 3 earned statuses), re-run unchanged at the commit
  this PR ships in
  `docs/eval-data/2026-08-13-k5-field-reconfirmation-at-head.md`. One cell,
  copy-pasteable, `1>&0` with stdin on `/dev/null` being fd 1 duped from a read-only fd:

  ```sh
  cd <repo> && T=$(mktemp -d) && mkdir -p "$T/transcripts" && cat > "$T/transcripts/critique--nav-prod-port--r0.json" <<'JSON'
  {"task":"nav-prod-port","config":"critique","repeat":0,"passed":true,"outcome":"pass","seed":111,"output":"{\"port\": 9443}","messages":[]}
  JSON
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH=runtime-py/src /bin/sh -c \
    '{ .venv/bin/python runtime-py/tests/cli_exit_status_probe.py \
        --base-url http://x --model fake-14b \
        --rubric before=assets/rubrics/task-completion.yaml \
        --transcripts '"$T"'/transcripts \
        --json '"$T"'/rows.jsonl --summary '"$T"'/summary.json; \
      echo "status=$?" >&2; } 1>&0' </dev/null
  ```

  It prints `status=5`, an `error: …` line that names the errno, and leaves 16 rows and
  a 3832-byte summary on disk. The same command with `PYTHONIOENCODING=latin-1` and
  stdout on `/dev/null` is the codec half and also reads `5`.

  | the run earned | mode | before (`5538624`) | after (`d1951bb`) |
  |---|---|---|---|
  | `0` / `3` / `4` | `epipe` (RB-P27's case) | `0` / `3` / `4` | **unchanged** |
  | `0` / `3` / `4` | `ebadf-file`, small table | `120` | **`5`** |
  | `0` / `3` / `4` | `ebadf-file`, table > stdout's buffer | `1` | **`5`** |
  | `0` / `3` / `4` | `closed` (`1>&-`, `sys.stdout is None`) | `1` | **`5`** |
  | `0` / `3` / `4` | `PYTHONIOENCODING=latin-1` / `=ascii` | `1` *(traceback)* | **`5`** |

  **The size axis is gone**, which was the half of the filing that made the pre-fix
  number unreadable: the same failure read `120` under stdout's buffer and `1` over it,
  and both are now `5`. `jsonl_identical` is `yes` in all 45 cells and
  `summary_identical` is `yes` or `both-absent` in all 45 — a run whose report was never
  rendered leaves the same bytes as the same argv with a live reader.

  **RB-P31's arm was one class too narrow, and the PR's headline was false as
  shipped (K4B/C1).** The printed table's GUARD section always carries `U+2014`
  and `U+00A7`, so a caller who sets `PYTHONIOENCODING=latin-1` (or `=ascii`)
  makes `print(table)` raise `UnicodeEncodeError` — a `ValueError`, not an
  `OSError` — which escaped the arm, printed a traceback, and left the shell
  reading `1` on a run whose JSONL rows and summary are byte-identical to the
  same argv on a live stdout. Twelve field cells (two codecs × two table sizes ×
  three rungs of the ladder) moved `1` → `5`; six `utf-8` control cells did not
  move. The arm is now `except (OSError, UnicodeEncodeError)`, and the line it
  draws is the two things about stdout **the caller owns**: the descriptor and
  the codec it was wrapped in. Everything else the write raises is still a bug
  with a traceback, pinned on the new edge by a node that raises a bare
  `ValueError`. Before and after in
  `docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.{sh,md}`.

  **What is NOT closed and is not claimed to be.** `ENOSPC` is covered by class and
  never by a real full device; `fd 1` on a DIRECTORY still kills CPython in
  `init_sys_streams` before `main` exists, so no arm here can choose that number, and it
  is written into the contract and pinned rather than left to be re-filed as a defect of
  this arm; and RB-P28's residual is unchanged. All three are in the K5 list below.
  (Measurement.)
- **RB-P32 — a malformed `--rubric` exits `1`, and the two committed statements
  about what `2` covers disagree with each other.** `--rubric /tmp/x.yaml` (a
  value missing its `LABEL=`, every required argument present) is a pure
  command-line syntax error: nothing ran, no artifact exists. It exits **`1`**,
  "did not complete a measurement — artifacts are PARTIAL". The user-visible
  epilog says `2` is "usage error (argparse's number, **including this module's
  own validations**)", which covers this case; the module comment at `:174` says
  something narrower — argparse "owns this module's own `parser.error`
  validations" — which does not. So the disagreement is not between the prose and
  the behaviour alone, it is between two committed sentences about the same
  number. **Inherited**, measured at `c7d0b72` and at HEAD; it is not a regression
  from this branch, but this branch revised that epilog and re-shipped the
  sentence, which is why it is filed here rather than left implicit. **Attack,
  preferred:** route `parse_rubric_arg` and every other argument-*shape*
  validation through `parser.error`, so that "fix the command line" is always `2`
  and both numbers mean what the epilog says they mean. **Alternative:** narrow
  the epilog to match the module comment and pin the malformed case at `1` with
  its meaning stated — cheaper, and it leaves a CI job unable to tell a typo from
  an aborted run. Either way the acceptance node reads the status from a real
  shell. (Measurement.)

  **AMENDED AND CLOSED (2026-08-13), and the amendment comes first because two
  things above are wrong as filed.** The filing text is left standing; this
  paragraph corrects it rather than replacing it. Ground truth is a 23-case
  matrix read from a real shell before the change
  (`docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.md`) and the same
  23 cases from the same runner after it (`...-matrix-after.md`). RB-P28 is
  open, so the suite is a regression guard here and not the evidence.

  *Correction 1 — there is no "family" of `parser.error` validations.* The
  filing, and the module comment it quotes, speak of this module's own
  `parser.error` validations in the plural. There was **exactly one call site**
  (`args.replays < 1 or args.identity_replays < 1`), guarding two flags, and the
  only other match in the file is a comment. Three measured cases, not a family.

  *Correction 2 — the preferred attack's stated reason does not survive.* It
  read "route ... through `parser.error`, so that fix the command line is always
  `2` and **both numbers mean what the epilog says they mean**". They cannot:
  the epilog is the sentence that is wrong. It claimed `2` covers "this module's
  own validations" unqualified, and that is false after the fix as well as
  before it — `--rubric a=/tmp/gone.yaml` and an empty `--transcripts` are this
  module's own validations and are still `1`, correctly. The routing was the
  right move; the sentence had to be narrowed **and** the behaviour moved, and
  the filing offered those as alternatives when they were both required.

  *Correction 3 — the filing does not mention the defect that made the class
  incoherent.* `--rubric a=git:HEAD` reached `_, ref, path = spec.split(":", 2)`
  and raised an **uncaught `ValueError`**: a raw traceback and the interpreter's
  `1`, not `REFUSAL_EXIT`, and from CI indistinguishable by status from a
  refusal that reported itself. Nor does it mention that all twelve argument
  `1`s wrote **0 bytes** — the measured fact the decision turns on.

  **The decision: every argument-SHAPE error is `USAGE_EXIT`.** A shape rule is
  one that can be decided from the typed string alone — no path resolved, no
  file opened, no `git` run — and every one of them now goes through
  `parser.error` above `main`'s `try`. The reason is what a CI job must DO with
  the number, not symmetry: `1` says "a measurement was attempted, may have died
  mid-family, and any artifacts on disk are PARTIAL — quarantine them"; a
  malformed command line can leave no artifact at all, and the only useful
  instruction is "a human edits the argv, because this can never work on any
  machine". Two instructions that opposite, sharing one number, is the RB-P24
  defect class. `1` keeps every world-dependent refusal and stays non-zero for
  the spec §6/§11 conditions, none of which are shape rules.

  **Behaviour change a CI consumer sees — four cases, `1` → `2`:** `--rubric
  SPEC` with no `LABEL=`, `--rubric =SPEC`, `--rubric LABEL=`, and `--rubric
  a=git:HEAD`. Nineteen cases kept their number and all 23 still write 0 bytes
  to stdout. A job that branched `status == 1` to collect partial artifacts now
  sees `2` for a typo and has nothing to collect, which is the point; a job that
  treated `2` as "argparse only" must stop, because `2` now carries this
  module's own rules by design and says so in both committed sentences.

  **The strongest case against, stated because it is real.** `2` is argparse's
  number and this module does not own it, so overloading it means a consumer can
  no longer read `2` as "argparse rejected the argv" — and a future argparse
  could in principle change it. The counter is that the ship had sailed:
  `--replays 0` was already this module's rule reported as `2`, measured, and the
  alternative — inventing a sixth number for shape errors — spends a number on a
  distinction ("who wrote the rule") that no CI job acts on, while leaving the
  distinction jobs DO act on ("is there anything on disk") still smeared across
  `1`. The number stays measured rather than assumed
  (`test_argparses_usage_status_is_measured_not_assumed`).

  Closed by: the shape check split out as `rubric_arg_shape_problem` (no I/O, so
  it may run above the `try`), the four cases routed through `parser.error`, the
  `git:` unpack fixed to raise `PerturbationError` for in-process callers, and
  the epilog and the module comment rewritten to describe the same set as the
  behaviour. The two RB-P32 nodes lose their `xfail` and become guards; the
  first now pins the number as well as the consistency, and its case list grew
  by one (`--rubric a=git:`) rather than shrinking. (Measurement.)

  **Amendment (K4B, 2026-08-13) — one sentence above is false as written, and a
  fifth case has moved.** "Every one of them now goes through `parser.error`"
  was not true when it was committed. `--rubric a=X --rubric a=Y` is decidable
  from the typed strings alone — a label is the text left of the first `=`, so
  two of them collide on every machine — and it was refused by `guarded_family`
  **inside `main`'s `try`**, reporting `1`. Field-measured at `3981efd`: status
  `1`, 0 bytes on stdout, and `--rubric a=git:R:P --rubric a=git:R:P` spent
  **two `git show` subprocesses** before noticing, which is exactly the cost the
  `git:` shape check exists to avoid. It also falsified the `#   2` block's
  "all of the argument-SHAPE ones and only those" and its "a `1` is an argv that
  names something **the world did not supply**" — here the world supplied
  everything.

  Closed by adding `rubric_label_collision_problem` above the `try` and routing
  it through `parser.error`; three cases move `1` → `2` and four controls do not
  move, including a run with distinct labels that still measures and prints its
  table. `guarded_family`'s copy **stays**, and that is argued rather than
  hedged: an in-process caller may pass a bare `Rubric` whose label is its
  `name` and therefore came off a file on disk, which is world-dependent and
  undecidable from any argv. Same verdict, two entitlements. Before and after in
  `docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.{sh,md}`, with the
  `git show` count taken from a PATH shim rather than read off the source.

  **The consistency node was rebuilt, not patched.**
  `test_the_epilog_and_the_module_comment_agree_about_what_the_usage_status_covers`
  was two substring tests joined by `and`, and K4 silenced it by renaming both
  `parser.error` mentions in the module comment — after which the old false
  epilog sentence could be restored verbatim with a green suite. It is replaced
  by `test_the_usage_status_names_exactly_the_shape_rules_the_code_has`, which
  DERIVES the set from the AST (every `parser.error` reachable above `main`'s
  `try`, followed one hop through the function that supplied its message, and
  the `--flag` names those messages carry) and requires both committed rosters
  to be exactly it, plus
  `test_every_shape_rule_flag_is_the_usage_status_in_the_field`, which measures
  each named flag to `2` and each unnamed module rule to `1` from a real shell.
  A rename now changes nothing (verified: it is a control that must stay green);
  K4's full attack — rename **and** restore the false epilog — is red.
  (Measurement.)

  **Amendment (K5, 2026-08-13) — the closure above was measured at `3981efd` and
  `b0d4cce`, and this PR ships a later tree.** Both runners were re-run unchanged at
  `d1951bb` and read the same numbers: 23 cases, **15 → `2`**, **8 → `1`**, 0 of 23
  writing a single byte to stdout; and D1–D3 of the duplicate-label matrix at `2` with
  **0 `git show` subprocesses**, its `3` control still `3` with 1015 stdout bytes
  (`docs/eval-data/2026-08-13-k5-field-reconfirmation-at-head.md`). The one-cell version
  of the shape half, copy-pasteable:

  ```sh
  cd <repo> && env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH=runtime-py/src /bin/sh -c \
    'T=$(mktemp -d); .venv/bin/python -m bantamkit.criticreplay \
       --rubric assets/rubrics/task-completion.yaml \
       --base-url http://x --model m --transcripts "$T" >"$T/out" 2>"$T/err"; \
     echo "status=$? out_bytes=$(wc -c <"$T/out" | tr -d " ")"; tail -1 "$T/err"'
  ```

  It reads `status=2 out_bytes=0` and
  `error: --rubric wants LABEL=SPEC, got 'assets/rubrics/task-completion.yaml'`. Swap
  the value for `a=$(mktemp -u)` and it reads `1`: same flag, different side of the line,
  which is the distinction the roster cannot state on its own.

  **What K5 added is the check on the prose AROUND the roster.** The mutation harness
  (`tools/pinharness/`) measured this contract's claims at `b0d4cce` and found that the
  old false epilog sentence — "`2  usage error (argparse's number, including this
  module's own validations)`" — could be **restored verbatim** with a fully green
  764-node suite. The roster derivation pins the SET of shape rules; the false sentence
  is a QUANTIFIER over rules, and no list of flags contradicts it, so both rosters could
  be exactly right while the sentence above them said the thing RB-P32 disproved.
  `test_no_sentence_about_the_usage_status_claims_all_of_this_modules_validations` now
  requires every sentence in either committed `2` block that speaks of this module's own
  validations to narrow them to the argument-**SHAPE** ones, and requires the
  counterexample it rests on (`--rubric a=<a path that is not there>`) to be one the
  field node MEASURES rather than one the check asserts. The disclosure paragraph is
  pinned the same way: its count of moved cases is read out of the committed
  before/after matrix's own table, so the sentence and the evidence cannot drift apart in
  either direction. (Measurement.)
- **RB-P33 — `main()` leaves the process's fd 1 pointing at `/dev/null` after it
  handles a dead stdout, permanently, and nothing says so. NOT inherited: this is
  a side effect of the handler `dc121b5` shipped on this branch** — `c7d0b72` has
  no `dup2` and no `devnull` anywhere in this module — so it is filed against this
  PR, not around it. The `dup2` is load-bearing (without it CPython's
  finalization flush re-fails on the dead pipe and replaces the earned status with
  `120` again), so this is a **cost of the fix**, not an accident in it. The bytes
  that were doomed stay doomed either way; what the clobber destroys is the
  **caller's ability to detect the loss** — for every subsequent write, for the
  life of the process. That bites here specifically because `main` is exported in
  `__all__` and this repo's own `cli_exit_status_probe.py` calls it
  **in-process**: an in-process caller that writes to fd 1 after `main` returns
  now gets silence and success where it used to get an exception. **Attack:** save
  `os.dup(1)` before the `dup2` and restore fd 1 from it before returning, so the
  clobber lasts exactly as long as the shutdown flush needs it — or, if the
  restore is judged unsafe, declare the clobber in `main`'s docstring **and** in
  the epilog and pin it with a node asserting that a post-`main` write to fd 1
  still raises. Silence is the one option not available, because a caller cannot
  discover this by reading the contract. (Measurement.)

  **CLOSED (2026-08-13, v0.20.0), and by neither lever as filed.** The filing offered
  "save `os.dup(1)` and restore it" or "declare the clobber and pin it". What shipped
  removes the clobber instead: the `os.dup2(devnull, 1)` recovery is replaced by
  `_LostStdout`, an object bound to `sys.stdout`, and fd 1 is never touched at all. That
  answers the filing's own reasoning better than either lever — the `dup2` was
  load-bearing only for making CPython's finalization flush succeed, and an object whose
  `flush` is a no-op does that without owning a file descriptor. Three defects close at
  once: the clobber is gone, the second RB-P31 route (the recovery's own `os.open`
  failing) is gone rather than caught, and a caller that keeps writing gets the original
  failure **re-raised** instead of silence.

  **Measured in a real process, and it is the one claim in this contract a shell cannot
  read** — it is about what an IN-PROCESS caller sees after `main` returns, and `main` is
  exported in `__all__` precisely so callers can do that. Runner and record:
  `docs/eval-data/2026-08-13-rbp33-fd1-after-main.{sh,md}`.

  ```sh
  sh docs/eval-data/2026-08-13-rbp33-fd1-after-main.sh "$PWD" /tmp/rbp33-after
  git checkout 5538624 -- runtime-py/src/bantamkit/criticreplay.py
  sh docs/eval-data/2026-08-13-rbp33-fd1-after-main.sh "$PWD" /tmp/rbp33-before
  git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
  ```

  | what the process is asked, with a dead pipe on fd 1 | v0.19.0 (`5538624`) | `d1951bb` |
  |---|---|---|
  | is fd 1 still the fd the caller installed? | **NO** — the null device | **yes** |
  | the next write to `sys.stdout` | **SILENT SUCCESS** | **raises `BrokenPipeError`** |
  | a child `/bin/sh` that inherits fd 1 | **exits `0`**, wrote into nothing | exits `-13` (SIGPIPE) |
  | the status, and the JSONL rows on disk | `0`, 32 rows | `0`, 32 rows |

  The status and the artifacts do not move: what came back is the caller's ability to
  **detect** the loss, which is exactly what the filing said the clobber destroyed. The
  bytes that were doomed stay doomed either way.

  **Pinned for BOTH arms, which is a defect K4B found in the first version of this
  closure**: the no-silent-sink property was pinned for the `OSError` arm only, so
  replacing the EPIPE arm's `_LostStdout` with a swallowing sink scored a full green
  suite. Both arms are pinned now, and the mutation that demonstrated it is claim `B02`
  in `tools/pinharness/contract-ledger.json`. The property is also declared in the
  epilog, because a caller cannot discover it by reading anything else. (Measurement.)

#### K4B (2026-08-13) — what the adversarial review found, and what is left open

K4's review of the RB-P31/RB-P32 fixes found two Criticals. C2 is amended into
the RB-P32 entry above. C1 belongs to RB-P31's closure, **which is K5's to
write** — so it is not written here. The exact wording K4B hands K5, measured
rather than drafted:

> **RB-P31's arm was one class too narrow, and the PR's headline was false as
> shipped (K4B/C1).** The printed table's GUARD section always carries `U+2014`
> and `U+00A7`, so a caller who sets `PYTHONIOENCODING=latin-1` (or `=ascii`)
> makes `print(table)` raise `UnicodeEncodeError` — a `ValueError`, not an
> `OSError` — which escaped the arm, printed a traceback, and left the shell
> reading `1` on a run whose JSONL rows and summary are byte-identical to the
> same argv on a live stdout. Twelve field cells (two codecs × two table sizes ×
> three rungs of the ladder) moved `1` → `5`; six `utf-8` control cells did not
> move. The arm is now `except (OSError, UnicodeEncodeError)`, and the line it
> draws is the two things about stdout **the caller owns**: the descriptor and
> the codec it was wrapped in. Everything else the write raises is still a bug
> with a traceback, pinned on the new edge by a node that raises a bare
> `ValueError`. Before and after in
> `docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.{sh,md}`.

RB-P33's closure is also K5's. What K4B adds to it: the no-silent-sink property
was pinned for the `OSError` arm only, so replacing the **EPIPE** arm's
`_LostStdout` with a swallowing sink scored a full green suite. It is now pinned
for both arms.

**Fixed in this unit rather than filed:** the `--summary` failure's stderr
sentence promised a table that the EPIPE cell prints nowhere; a non-transcript
`.json` in `--transcripts` raised an uncaught `KeyError: 'task'` (the right
number delivered by traceback — the same shape RB-P32 fixed for `git:HEAD`);
and five contract claims that no node held (5 outranks 4; the hatch is an
opt-out from `3` alone with respect to `5` too; the RB-P32 line on its `1` side;
the anti-shrink guard's anchor; the `5` line's byte-identity promise) each got a
node that goes red when the claim is inverted.

**Measured and NOT fixed — open, with an attack direction:**

- **RB-P28's residual, unchanged and reconfirmed against the new nodes.**
  Reverting the render arm and gating the fix on `"pytest-of-" in " ".join(
  sys.argv) or "pytest" in sys.modules` scores a full green suite while the
  field measures the exact pre-fix matrix. Nine of K4's seventeen attacks
  survived a green suite. Not this job's lever; every acceptance in this cycle
  is a field measurement for that reason. **Attack:** an oracle phase that runs
  outside pytest, as RB-P28 already says.
- **`fd 1` on a DIRECTORY kills CPython before `main` exists** —
  `init_sys_streams`, `IsADirectoryError`, and the shell reads `1`. Nothing in
  this module runs, so no arm here can choose that number. Written into the
  contract and pinned by `test_fd_one_on_a_directory_never_reaches_this_module`
  so it is not re-filed as a defect of the render arm. **Not a defect.**
- **A `BantamError` whose own message is not ASCII, on a stderr wrapped in a
  codec that cannot take it.** `sys.stderr` is `backslashreplace` (measured, and
  it stays that way even under `PYTHONIOENCODING=ascii:strict`), so the status
  survives and the SENTENCE is mangled. This module's own status reports are
  ASCII for that reason; the refusal path's messages are not, and one of them —
  `guarded_family`'s duplicate-label text — carries an em dash. It reports the
  number it would have reported anyway, so it is a delivery defect, not a status
  one. **Attack:** an ASCII rule for every message this module writes to stderr,
  pinned by a node that reads the module's string literals.
- **The anti-shrink anchor is a literal in the same file it guards.** A
  three-place mutation (record, case list, and `_RBP32_FIELD_CASE_FLOOR`) still
  passes; what is now caught is the two-place one K4 demonstrated. **Attack:** a
  case list derived from the committed field artifact rather than counted.
- **One platform, one filesystem, one CPython 3.12.13 on APFS/Darwin**, for
  every number in this entry. ENOSPC on a real full device is still handled by
  class and simulated in-process only.

#### K5 (2026-08-13, v0.20.0) — the closures, the instrument, and what is still open

RB-P31, RB-P32 and RB-P33 are closed above, each with its field command and its
before/after, and every runner in the job was re-run unchanged at the commit this PR
ships (`docs/eval-data/2026-08-13-k5-field-reconfirmation-at-head.md`). What K5 added on
top of the fixes is an **instrument and three checks**, and the instrument is the reason
the checks exist rather than the other way round.

**The pinning harness is in the repo now**, because a number nobody else can reproduce is
not evidence:

```sh
.venv/bin/python tools/pinharness/pinned.py . 3981efd tools/pinharness/calibration.json
.venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/contract-ledger.json --out /tmp/ledger.md
```

A claim is **PINNED when a mutation that makes it false turns at least one node red**.
Measured at `b0d4cce`: behaviour **16/16**, prose **2/5**, overall 18/21 — and each of the
three misses was confirmed by applying the mutation and watching a fully green 764-node
suite come back. Measured at `ff58237` after the three nodes landed: behaviour **16/16**,
prose **5/5**, overall **21/21**
(`docs/eval-data/2026-08-13-contract-claim-pinning.md`). The calibration runs on
`3981efd`, where both answers were already known by hand, and still reproduces after the
fix — an instrument that has not been shown to distinguish a pinned claim from an
unpinned one is not evidence about either.

**Measured and NOT fixed — open, each with an attack direction:**

- **RB-P28's residual, reconfirmed against this job's own nodes.** K4 reverted the render
  arm and gated the fix on `"pytest-of-" in " ".join(sys.argv) or "pytest" in
  sys.modules`, and scored **748/748** while the field measured the exact pre-fix matrix;
  **nine of seventeen attacks survived a green suite.** This is why every acceptance in
  this job is a field measurement and why the suite is called a regression guard
  everywhere above. Not this job's lever. **Attack:** an oracle phase that runs the
  shipped entry point outside pytest — no `PYTEST_*` in the environment, `$?` read by a
  shell — and treats the in-process suite as a guard whose green is necessary and never
  sufficient.
- **`ENOSPC` is covered by CLASS, not by a real full device.** Every `5` from a full
  device in this job is an in-process simulation; macOS has no `/dev/full`, so nothing
  here wrote until a filesystem said no. **Attack:** it is one line on Linux — point fd 1
  at `/dev/full` in the existing runner and add the cell — and CI already runs
  `ubuntu-latest`, so the missing measurement is a matrix entry, not a research problem.
  Until then the epilog says so in as many words, and a node pins that it says so.
- **The anti-shrink anchor is still a literal in the file it guards.**
  `_RBP32_FIELD_CASE_FLOOR = 9` catches the two-place mutation K4 demonstrated (delete a
  case from the record and from the case list); a **three-place** mutation that edits the
  floor too still passes. **Attack:** derive the case count from the committed field
  artifact — `2026-08-13-rbp32-argument-validation-matrix.md` is already parsed by
  `test_the_epilog_discloses_the_behaviour_change_with_the_count_the_field_record_measured`,
  so the same reader can supply the floor and put the anchor in a file that the suite
  does not own.
- **The roster derivation follows exactly ONE hop.** `parser.error(problem)` is traced to
  the function that returned `problem`; a shape rule whose message is built two calls
  deep is invisible to it, and the derived set would silently shrink. **Attack:** either
  walk the call graph to a fixed point, or assert the hop depth — a node that fails when
  a `parser.error` argument is neither a literal nor a one-hop name is the cheap version
  and is honest about what it cannot see.
- **A `BantamError` whose own message is not ASCII, on a codec-hostile stderr, is
  mangled.** `sys.stderr` is `backslashreplace` (measured, and it stays that way even
  under `PYTHONIOENCODING=ascii:strict`), so the STATUS survives and the SENTENCE does
  not. This module's own status reports are ASCII for that reason; the refusal path's are
  not, and `guarded_family`'s duplicate-label text carries an em dash. It reports the
  number it would have reported anyway, so it is a delivery defect and not a status one.
  **Attack:** an ASCII rule for every message this module writes to stderr, pinned by a
  node that reads the module's own string literals.
- **The pinning harness's own limits, stated because the 21/21 will be quoted.** (a) The
  **ledger is the denominator**: 21 claims is what one reader wrote down, and a claim
  nobody entered is not counted as unpinned, it is invisible — the number is "of the
  claims in this file", never "of the contract". (b) **One mutation per claim**: a claim
  is pinned against the mutation in the ledger, not against every mutation that would
  falsify it. (c) **Prose-pinned is not behaviour-pinned**: a prose guard can be green
  while the behaviour it describes is broken, which is exactly what K4 demonstrated.
  **Attack:** grow the ledger from the reviews rather than from the author's memory —
  every Critical and Important a review files is a claim that was falsifiable, so add it
  with the mutation that found it — and report the two numbers separately, always.
- **One machine, one filesystem, one CPython 3.12.13 on APFS/Darwin 25.5.0**, for every
  number in this job. The re-run at the shipping commit is a reconfirmation with the same
  runners on the same machine: it rules out "a later commit moved an earlier unit's
  number" and adds no platform and no second observer. **Attack:** the CI matrix already
  runs 3.11 and 3.12 on `ubuntu-latest`; the field runners are `/bin/sh` and would run
  there as a job of their own.

Two of the review's findings were fixed in this cycle rather than filed:
`requests` counted JSONL rows while `Verdict.calls` was dropped from the row
schema, so a `structured()` retry could have inflated `tokens_total` with
nothing in the report to show for it — rows now carry `calls` and the summary
carries `wire_calls` beside `requests` (`9a2312e`). And the spec's token
estimates ran 32% low on the acceptance run and 11% low on the routine profile,
against exact request counts; the spec now carries the measured numbers and the
reason (`C-attempted` costs ~580 tokens/request against `A-asfiled`'s 384, so
per-*variant* estimates cannot be scaled from one variant).

#### L (2026-08-14, v0.21.0) — three closures, a counter that got honest, and what is still open

RB-P16, RB-P17 and RB-P18 are closed above, each with its own before/after and its
own field record. **The suite is not the evidence for any of them** — RB-P28 is
open, and this job demonstrated why for a third time: a patch that reverts all
three fixes unless `pytest` is in `sys.modules` kept **792 passed, 2 xfailed**, not
one node red, while a real shell printed an affirmatively false effect line
(`docs/eval-data/2026-08-14-rbp28-acceptance-pins-outside-pytest.md`). So each
acceptance is a `/bin/sh` run with no `PYTEST_*` key in the child's environment,
and the nodes are regression guards.

**The commands, exactly as they were run.** Each takes the repo and a work
directory; the `-before` form is the same runner against the pre-fix commit, so
both ends are measured rather than one end being cited:

```sh
# RB-P16 — a verdict carries its effect size
sh docs/eval-data/2026-08-14-rbp16-effect-size-report.sh "$PWD" /tmp/rbp16
# RB-P17 — a control's provenance is a rule applied to a committed ref
sh docs/eval-data/2026-08-14-rbp17-provenance-resolution.sh "$PWD" /tmp/rbp17
sh docs/eval-data/2026-08-14-rbp17-provenance-resolution-v2.sh "$PWD" /tmp/rbp17v2
# RB-P18 — one request lands on both frozen payload-sha families
sh docs/eval-data/2026-08-14-rbp18-payload-recipe.sh "$PWD" /tmp/rbp18
# RB-P28's residual, closed for the three acceptances
.venv/bin/python docs/eval-data/2026-08-14-rbp28-fix-nothing-patch.py "$PWD"
# this unit's residuals: the CWD tell, the export list, the status values
sh docs/eval-data/2026-08-14-l7-closure-residuals.sh "$PWD"
# the pinning number, and the calibration that licenses reading it
.venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/contract-ledger.json
.venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/calibration-head.json
```

**What each lever changed, in one line and no more than was measured.** RB-P16: a
§7 verdict now ships an `effect` block beside it — signed difference, sign, which
variant leads, `points_from_separation`, and the points the two variants disagree
on — plus a cross-cell `directional` key; the two ends of the committed band
(|Δ| 0.833 and 0.273) are now tellable apart, and no cell's attribution moved.
RB-P17: the null control is expressible as
`derive:<manifest-path>:<rule-id>:git:<ref>:<path>`, every segment repo-relative or
a git ref, and it reproduces the frozen manifest's own `base_sha256`
`d1f32ad2947b…` on all 12 declared points. RB-P18: `payload_canonical_sha256`
lands beside `payload_sha256`, and **one** request issued on 2026-08-14 hits both
frozen record families at once — `a17fc774681a…` (the bar's) and `4eb56220e883…`
(SA3's) — so a frozen row is now interpretable by re-running its cell and seeing
which column its value lands in.

**Three Criticals were found AFTER those three closures were written, and all three
were closed before this was published.** That ordering is the point of putting a
review unit between the fixes and the release, and it is the second job in a row
where the review found Criticals a closure unit placed directly after the fixes
would have shipped. (1) The fix-nothing patch above. (2) The pinning harness
certified claims it never checked. (3) The `derive:` form re-created RB-P17's own
defect one segment over — an absolute out-of-repo manifest path was **accepted**,
by the shipped code, by the fresh-run pin, and by the committed field checker, all
three having the hole they were checking for.

##### The number — and it went DOWN because the counter got honest

**`31/31` is WITHDRAWN and is cited nowhere.** Under the harness that produced it
the whole verdict was `pinned = rc != 0`, which relates no claim to its mutation
and no killer to its claim. Reproduced rather than argued: a one-claim ledger
asserting *"every summary a run writes states the current phase of the moon, read
from an ephemeris"* — a feature that does not exist — paired with a mutation that
breaks an `import`, measured **PINNED, 1/1, 100%**, with `nothing` in the killed-by
column of the same row (`docs/eval-data/2026-08-14-pinning-harness-false-positives.md`).
`31/31` meant **"31 mutations each turned ≥ 0 nodes red"**.

| sweep | ledger | result |
|---|---|---|
| `3070d9c` — first sweep under the fixed harness | the **same 31** claims | **30/31** — PINNED 30, **FALSE-PINNED 1** (`B16`), UNPINNED 0, BROKEN 0 |
| `8cd6078` | **34** claims (`N11`, `N12`, `N13` added) | **34/34** — behaviour 29/29, prose 5/5 |
| `6b22889` (this unit) | **35** claims (`N14` added with L5's M1 fix) | **35/35** — behaviour 30/30, prose 5/5, FALSE-PINNED 0, BROKEN 0 |
| `4122a60` (re-swept after RB-P35) | the same **35** claims | **35/35**, unchanged — RB-P35's own sentence is prose and is **not** in the ledger |

**The denominator grew by one because a defect was fixed, not because the counter
got looser**, and `34/34` at `8cd6078` is not restated by that sweep — it stands
exactly as it was measured. The caveat below travels with **both** numbers,
unchanged, because nothing in the last sweep changed how `pins` is chosen.

**The honest number is `34/34`, and this caveat travels with it wherever it is
quoted:**

> **34 mutations each turned red a node the claim NAMED.** `pins` is
> **author-chosen**, and `B16` is a documented instance of the discipline being
> applied *after* the measurement.

`B16` came back from FALSE-PINNED by **inspection, not by re-scoping**: its only
killer, `test_every_shape_rule_flag_is_the_usage_status_in_the_field`, carries
`--rubric a=<a path that is not there>` as its load-bearing case and cites K4's I4
— which is `B16`'s own committed note — so that node was entitled to pin it and the
first pin list simply omitted it. Defensible on the node's own docstring, and no
stronger than that.

**What the old counter was throwing away** — the new `of which NAMED` column, the
count of a mutation's killers that the claim actually named:

| claim | named / total killers |
|---|---|
| `N01` | **1 / 8** |
| `N02` | 1 / 3 |
| `N03` | 1 / 4 |
| `B10` | 1 / 6 |

**Most killers were never related to their claim at all.** The three acceptance
claims name **only** their out-of-process node, on purpose: under the old rule each
would have counted a kill by any of its 3–8 in-process guards, which is exactly the
reading that made the fix-nothing patch invisible.

**A number that went down because the counter got honest is a better number, and
that is how this one should be read.** `31/31` was arithmetically higher and
measured nothing; `34/34` is arithmetically the same fraction and measures a
narrow, stated thing. Calibration at HEAD is what licenses reading it at all —
`CAL-HEAD-RED` PINNED and `CAL-HEAD-GREEN` UNPINNED, both known answers, both
returned; an instrument with only a positive control cannot tell "everything is
pinned" from "the detector is stuck on".

##### Measured and NOT fixed — open, each with an attack direction

- **RB-P34 — the exit-status contract's status VALUES are pinned by nothing, and
  a probe written for another purpose is what revealed it.** Measured at two
  commits, by two units, with the same answer: mutating `GUARD_VIOLATION_EXIT` from
  `3` to `7` leaves **798 of 800 nodes green** at `6b22889` and **797 of 799** at
  `6c27ebe`, with the same two killers both times. The mechanism is not an oversight in
  any one node — **every** node that tests exit status *names the constant*, so the
  mutation moves the code and the expectation together and every assertion is as
  true afterwards as before; the epilog renders the number through an f-string, so
  the prose moves too. The only two nodes that notice are L6's `OUTSIDE_pytest`
  probes, which read `$?` off a real child and happen to assert a literal `3`. The
  numbers `0/1/2/3/4/5` are a **contract with CI owners and with every committed
  evidence file**, and they have been protected by nothing since they were
  introduced. **Attack:** assert the literal values once, in
  `test_the_guard_status_is_distinct_from_the_refusal_and_the_usage_status`, and
  field-check each number against what the committed records actually carry — a
  status is a promise to a reader outside this tree, so the check belongs where a
  reader outside this tree can see it. Measured:
  `docs/eval-data/2026-08-14-l7-closure-residuals.md`, case C. (Measurement.)
- **RB-P35 — a shipped contract sentence asserted a status NUMBER for a case this
  module does not control, and CI on a second platform is what falsified it.
  FIXED where it was cheap, and the class is filed.** The epilog and the module
  comment both said `--help` with no reader on stdout "exits `120`", and a node
  asserted the literal. Neither is a property of this tool: the status turns on
  whether the doomed bytes are still in `sys.stdout`'s `BufferedWriter` when the
  interpreter exits, so it depends on the **size of the help text** against a
  buffer this module does not set — a mechanism the module's own comment already
  spells out for the run path and had not applied to itself. Measured on
  `ubuntu-latest` with **no behaviour of this module changed**: **7488 bytes of
  help text → `120`** (`b496856`, CI green), **8227 bytes → `0`**. The growth was
  docstrings, added by this job's own RB-P16/17/18 fixes. macOS read `120` at both
  sizes, which is why five units and every local suite run missed it.
  **The full mechanism, which took a second CI round to get right.**
  `argparse.ArgumentParser._print_message` wraps its one `file.write` in
  `except (AttributeError, OSError): pass` (CPython 3.10+), so the `BrokenPipeError`
  never propagates and `main`'s handler is genuinely not on that path — that half
  of the old sentence was true. What the shell reads is decided entirely by what
  the interpreter's shutdown flush finds in the `BufferedWriter`: bytes still
  buffered → the flush re-fails → `120`; bytes already pushed at the failed write →
  nothing left to flush → the `0` that `--help` exits with.
  **The first re-aim was WRONG and CI said so, and it is recorded rather than
  smoothed.** The first control was a bare `sys.stdout.write` with no `except`, and
  it read `1` on `ubuntu-latest` (the write raises out of `-c`; the traceback is the
  interpreter's `1`) where the module read `0`. That looked like evidence the module
  chooses the status, and it was not — it was the control differing from its subject
  in one hidden respect, which is the same failure mode as a rig that agrees with
  itself, one sign flipped.
  **What was fixed:** the epilog and the comment now say the number is the
  interpreter's, is **not fixed**, and that no branch should be written on a
  particular one — and they carry **no byte count**, because a count in a shipped
  string is invalidated by the next docstring; the counts live here and in the field
  record, dated. The node now asserts the module's status **equals what a bare
  interpreter doing exactly what argparse does with the identical bytes on the
  identical broken pipe reads**, which is the claim the contract actually makes, is
  platform-independent, and still goes red the moment this module starts choosing
  that status.
  **What is NOT fixed, and it is the larger half.** (a) The twin node
  `test_a_refusal_whose_stderr_has_no_reader_leaves_the_range` still asserts the
  literal `120`. It is green on both platforms today because a refusal's stderr
  text is far below any buffer — which is to say it is green **for the same
  accidental reason**, and it will go false the day that message grows. (b) The
  corrected sentence is **prose, and prose is not in the ledger**: reversing it
  back to "exits `120`" turns no node red, so RB-P35 is a worked instance of the
  unpinned-prose problem filed two entries down, not an exception to it.
  **Attack:** a contract sentence may not name a status the module does not
  choose — so every such sentence should state the *relation* it can guarantee
  (this process's status equals what the interpreter would do unaided) and a node
  should assert that relation against a control run, which is what landed here for
  one of the two cases. And the CI matrix is the instrument that caught this:
  every field runner in this job is `/bin/sh` and has been run on exactly one
  platform, so the same class of world-fact is sitting unexamined in the field
  records too. Measured: this PR's first CI run, and the local re-measurement in
  `docs/eval-data/2026-08-14-l7-closure-residuals.md`. (Measurement.)
- **RB-P28 stays OPEN.** L6 closed the **three acceptances** by moving their pins
  out of the process; it did not close the **class**. A patch can still key on the
  probe's `sys.argv[0]`, on the scripted critic, or on a tmp-dir-shaped path, and
  the three new probes are as susceptible to that as anything else — they are the
  three claims that were worth the cost, not a general defence. **Attack:**
  unchanged and stated at RB-P28 above — an oracle phase over the shipped entry
  point whose inputs are indistinguishable from a user's.
- **`pins` can be named after the measurement.** Nothing stops an author running
  the sweep, reading the killers, and writing them into `pins`. `B16` above is a
  documented instance. **Attack:** derive `pins` mechanically — from the section a
  node lives in and the problem id its docstring cites — so the author does not get
  to choose, and report any hand-written pin separately.
- **A pin may be a family PREFIX, and one is.** `assert_pins_exist` matches with
  `pin in node`, so `B01`'s `test_closed_pipe_` counts a kill by any of the **5**
  nodes in that family. Measured at `6b22889`: **67 pins over 35 claims, of which
  exactly one is a prefix.** Deliberate where the family is one claim, a loophole
  where it is not. **Attack:** require exact node ids and make a family explicit by
  listing its members, so the ledger states the count it is relying on.
- **The `derive:` manifest segment is still MUTABLE — detectable, not prevented.**
  `derive_manifest_sha256` records the bytes the ref resolved through; it does not
  stop the file changing under its own name and does not claim to. **Attack:**
  filed at RB-P17 above.
- **A derived variant's blank `rubric_sha256` is undocumented in the artifact**
  (L5's I5). A derived variant has no file of its own, so the column is empty and
  that is correct — but a later reader can read empty as "unknown" rather than "none
  exists", and the reasoning lives only in a docstring. This is the same defect
  `payload_sha256_recipes` was shipped to fix one field over: a recipe that lives in
  a docstring is not published. **Attack:** state it in the summary the run writes,
  beside the recipes block, where the out-of-tree reader looks.
- **Docstring prose asserting a MEASURED fact is entirely unpinned** (L5's I2).
  Reversing "2 of 11 points" to "0 of 11" inside a docstring reads UNPINNED. This
  job shipped hundreds of lines of such prose and added **zero** prose claims to the
  ledger, so the ratio of measured sentences to pinned ones got worse, not better.
  **Attack:** the numbers a docstring asserts should be read from the committed
  field record at test time — the pattern
  `test_the_epilog_discloses_the_behaviour_change_with_the_count_the_field_record_measured`
  already does exactly this for one sentence, and it generalises to any docstring
  number that names its record.
- **The ruler invariant's two hashes do not span the ruler's inputs** (L5's I4).
  `_separation`'s body hash and the `attributable` expression's hash both hold, and
  both held while this job moved `_family_stats.passed` to
  `len(_passing_points(...))` — a mutation of `_passing_points` from `all` to `any`
  changes every verdict while leaving **both** hashes byte-identical. The refactor is
  genuinely equivalent and was separately verified, but the stated method could not
  have told you. **Attack:** hash the transitive closure of what the decision rule
  reads, or — better, because it is a property and not a fingerprint — keep proving
  equivalence by **substitution**, which is what actually established that
  `directional` and `effect` decide nothing (a lying `_directional` and a constant
  `_effect` leave every decision field identical).
- **`N10`'s arity pin is synthetic** (L5's M2) and **a `derive:` ref resolves
  against the process CWD** (L5's M3, live at HEAD, and wider than filed). Both
  filed in full at RB-P18 and RB-P17 above.
- **One machine, one filesystem, one CPython 3.12.13 on APFS/Darwin 25.5.0**, for
  every field number in this job — as in K5. CI runs 3.11 and 3.12 on
  `ubuntu-latest` and is a second reading of the **suite** only; no field runner has
  been run there. **Attack:** unchanged — the field runners are `/bin/sh` and would
  run in CI as a job of their own.

##### Invariants re-verified at this unit's HEAD rather than cited

`docs/eval-data`: **−0 deleted lines** against `b496856` — nothing regenerated, nothing
retro-edited. `assets/`: **0 files changed**. The byte-identity floor
`runtime-py/tests/data/f8404ab-perturbation-baseline.json`: **0 commits** across
the whole job. And the ruler did not move — `_separation`'s body, with the
docstring stripped and normalised through `ast.unparse`, hashes
`1cfc39b88dfc4ef3`, and the `attributable` expression hashes `8487f267bc440b01`,
both under the recipes stated with them.

**The insertion count is deliberately not quoted here** — it moved three times
while this section was being written, once per field record added below it, and
RB-P35 is what a count inside a document that the same commit changes is worth.
The invariant is the **zero on the right-hand side**; run the command and read it:

```sh
git diff --numstat b496856..HEAD -- docs/eval-data | awk '{a+=$1;d+=$2} END {print a, d}'
git log --oneline b496856..HEAD -- runtime-py/tests/data/f8404ab-perturbation-baseline.json | wc -l
git show HEAD:runtime-py/src/bantamkit/criticreplay.py \
  | grep -A2 '"attributable": (' | tr -d ' \n' | shasum -a 256 | cut -c1-16
```

#### M (2026-08-17, v0.22.0) — the dev-team workload surface, and what it could not show

**The headline is a refutation and a refusal, and they are different claims.**
The `>60%` token-reduction target for the graph family **has no measurable
surface today**, and the reason is structural rather than circumstantial. Two
findings carry that, and conflating them would be the whole error:

- **`>60%` is refuted by arithmetic (bar §5 R1).** `cache`'s share of
  observation bytes at the verified reference walk is **5.819%** suite-wide and
  **23.063%** on the single most favourable task. Reaching 60% needs every file
  read **seven times** — `k = 7` → 61.443%, `k = 6` → 58.689% — which is past
  `LoopGuard`'s hard warning at 5. At the **realised** trajectory the ceiling is
  not 5.819% but **0%**, so R1's own stated assumption was measured *generous*.
- **This run itself is UNINFORMATIVE, by the bar's pre-registered R3 clause, and
  must never be reported as the refutation.** `repeat_reader_calls == 0` on
  **8 of 8** tasks in **all 24** `graph-off` runs (and in all 96 rows), against
  the reference walk's 3. The informative subset is **empty**. R1 refutes;
  this run declines to.

**Why it is structural.** `cache` collapses only a **byte-identical** repeat and
`annotate` only prefixes one, so the mechanism's entire opportunity set is reads
whose content the request already carries. `Agent.run`'s message list is
append-only. A collapsible repeat is therefore by definition a *redundant* read
— which means a **larger model should realise fewer, not more**, and a bigger
model is not a route to a non-zero `Δ%(A2−A1)`.

**And the workload could not have shown otherwise.** Strip every repeat hop from
all eight declared walks and all eight **still pass the workload's own
verifier**, at re-read pressure **`0/30` = 0.000**. No task on this surface
*requires* a second read, so the declared `3/33` = 0.091 pressure is entirely a
property of the declared non-memoising strategy, not of the tasks. Zero tasks
carry it.

**The one rung that moves is a trade, not a reduction.** Only `query` moves
anything, and it moves tokens **up**:

| pair | mechanism | `Δtok` | `Δ%` | vs per-task floor 1845 | vs suite floor 6469 |
|---|---|---|---|---|---|
| `A1−A0` | `annotate` | `0` | **+0.000%** | does not clear | does not clear |
| `A2−A1` | `cache` | `0` | **+0.000%** | does not clear | does not clear |
| `A3−A2` | `query` | `11680` | **+73.367%** | clears (6.33×) | clears (1.81×) |

A `0.000%` delta is **not** "no effect" — `|Δtok| = 0` clears neither floor, so
the correct reading is *unresolvable at this run's precision*, and A7 fixed the
grain the floor is compared at so both grains now agree on all three pairs
(`same = yes`). R2 **does not fire**: its fourth condition **abstains** at 8 ties
and 0 pointing. And roughly **half** of the one moving delta is not the
apparatus: `tokens ≡ model_calls × tokens-per-call` is an identity, and the split
is ×1.3667 from **more turns** and ×1.3830 from **bigger turns**, product 1.8901
— **49.1%** of the cost is the trajectory `query` induced.

**Four configurations, two distinguishable rungs.** `A0`, `A1` and `A2` agree on
**every one of 16 measured columns across all 24 rows** — 384 cells per pair,
1,152 across the three identity pairs, matched on `(task, seed)` rather than row
order — against 134 differing cells in every comparison with `A3`. So
`{A0, A1, A2}` and `{A3}` are the equivalence classes, and §1.1's
"each adjacent difference isolates one mechanism" is true of the *configuration*
and vacuous about *this run*: an adjacent difference of zero isolates nothing.

**The ship guidance this narrows, and what it does not retract.** `README.md`'s
`FileAccessGraph` recommendation claimed a **score rescue at a token cost**
(0/3 → 3/3 at +26% tokens), never a token saving, so this job **narrows its scope
and retracts nothing**. What is added: on a dev-repo-shaped surface the repeat
machinery has no opportunity at all, and whatever value `graph` carries there
comes from `query` alone. **The two percentages are not comparable and must never
be subtracted** — `+26%` is `graph` vs `bare` on the frozen suite; `+73.367%` is
`graph` vs `graph-cache` on the dev-team surface. Different baseline, different
surface, different client. `README.md` and `docs/filegraph.md` are live inputs and
were corrected **in place**; every record under `docs/eval-data/` was **amended,
never edited**.

**The surface is synthesised and its own bias detector FIRES.** Median file
**392 B** against the real package's **5829 B** — **14.9× smaller** — which is
recorded rather than corrected, and is why no figure here is offered as a
transfer claim.

##### The commands, exactly as they were run

Every acceptance rests on a **field** measurement outside pytest (RB-P28 stays
open); the nodes are regression guards. All seven programs re-run at this
section's HEAD, **exit 0** each:

```sh
# the bar's R1 ceiling — the 5.819% / k=7 arithmetic that refutes >60%
.venv/bin/python docs/eval-data/2026-08-17-devteam-workload-measurements.py .
# the null control — 44 calls, 8/8 byte-identical requests
.venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py .
# the accounting ruler — run_task against the ledger, then a real CLI subprocess
.venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py .
# the ladder — the ONLY derivation of every ladder statistic quoted above
.venv/bin/python docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py .
# the adversarial probe — three commissioned attacks, two land, one splits
.venv/bin/python docs/eval-data/2026-08-17-devteam-review-probe.py .
# the two Criticals, before and after, same program and same command at both ends
.venv/bin/python docs/eval-data/2026-08-17-devteam-critical-closure-field-measurement.py .
# the instrument-validation artifact regenerates BYTE-IDENTICALLY
.venv/bin/python docs/eval-data/2026-08-17-devteam-instrument-validation-run.py . --check

# each program's pins are its --mutate modes; every one must exit 1
.venv/bin/python docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py . \
    --mutate suite-floor-as-max
.venv/bin/python docs/eval-data/2026-08-17-devteam-review-probe.py . \
    --mutate {keep-repeats,changed-repeats,prune-transcript,split-arms,one-floor,pure-apparatus}
.venv/bin/python docs/eval-data/2026-08-17-devteam-critical-closure-field-measurement.py . \
    --mutate {per-task-floor,zero-dark-columns}

.venv/bin/python -m pytest runtime-py/tests -q          # 842 passed, 2 xfailed
.venv/bin/ruff check runtime-py tools/pinharness tools/devteam docs/eval-data
.venv/bin/python tools/devteam/build_tasks.py check     # OK — 8 tasks match the manifest
```

**The instrument-validation artifact is NOT a fifth arm and no `Δ%` may be
computed from it.** Its `tokens` is the `ceil(bytes/4)` surrogate, not an endpoint
`Usage`; it carries one row per `(task, arm)` so every repeat spread is 0 and the
floor is **degenerate** on it by the instrument's own function; and the ladder
program loads four explicit f-string filenames with **no glob**, so the file
cannot be read as an arm. The fence is structural, not a label.

**Two caveats that travel with every number above.** (1) The committed rows carry
**no `model` field**, so attribution to `qwen3:4b-instruct` rests on prose and the
pre-declaration at `290c834`, never on the row — filed as RB-P38. (2) The real
endpoint's `Usage` is pinned **for this run only**; it retro-validates no
`ceil(bytes/4)` surrogate, and column 7 counts payload wire bytes **minus**
`model` and `seed`, a stated subset.

##### Measured and NOT fixed — open, each with an attack direction

Nine findings from the adversarial review and the closure that followed it, plus
**one tenth (RB-P45) measured by the closure unit while bumping the version** —
recorded rather than dropped, because a measured negative becomes a problem with
an attack direction and never a footnote. Two Criticals were closed (bar §3.2's
floor grain, by A7; and four accounting columns that had never fired outside a
fixture, by a committed validation artifact). None of the ten below is fixed, and
**two got worse** rather than staying put.

- **RB-P36 — the score half of the bar has no noise floor, and two of the four
  flips that produced the run's only TRADE are single-repeat.** §3.1 ports
  `_passing_points`' unanimity rule, so a task at 1/3 or 2/3 is **one sampled run
  away** from changing the pass set, and `disagreeing_points` counts those flips
  at face value. §3.2 gave the token half a floor derived from repeat spread and
  gave the score half nothing. Measured: `dt-handler-map` 2/3→3/3 and
  `dt-unread-key` 3/3→2/3 are single-repeat flips; `dt-patch-before-after`
  0/3→3/3 and `dt-symbol-home` 3/3→1/3 are not. **The verdict survives and one
  sentence does not** — `Δ%(A3−A2)` is a TRADE at 2 disagreeing points as much as
  at 4, but `dt-handler-map` is 2/3 in A0, A1 and A2 *identically*, so it is not
  something the flag bought. **Attack:** give §3.1 a floor of the same shape §3.2
  has — bound a pass-set disagreement by the arms' own repeat instability, and
  report any point whose membership turns on one repeat separately from the
  count. **Command.** The probe, Table M6; and
  `grep -n "floor" docs/eval-data/2026-08-17-devteam-bar-preregistration.md`
  returns §3.2's token clause and nothing under §3.1. (The bar. Recorded in A6.)
- **RB-P37 — the ladder shipped four configurations and two measured rungs, and
  a proof of meaning-preservation transferred unearned.** 0 differing cells in
  384 comparisons per identity pair. A0's proof (44/44 byte-identical requests)
  therefore holds for A1 and A2 **because they are the same conversation**, not
  because anyone measured them — under a trajectory that realises repeats they
  separate immediately, on exactly the columns that are dark in the field.
  **Attack:** an arm may not be reported as a rung until one cell has been shown
  to differ from its neighbour; a null control's meaning-preservation proof must
  be re-earned per arm, or the arms must be declared an equivalence class up
  front. **Command.** The probe, Table M4. **What would show it false:** one
  differing cell between A0, A1 or A2 on any of the 24 `(task, seed)` pairs over
  the 16 measured columns. (No code defect — a reading of §1.1.)
- **RB-P38 — no committed row can be attributed to a model.** `TaskResult`
  (`evalrun.py:167-204`) has no `model` field and the union of every key over all
  96 rows confirms it. Two arms of *different* models would produce two files
  indistinguishable at the row level — which stops being cosmetic exactly when a
  second model is added. **Attack:** one additive trailing field, under the
  convention already documented in place at `evalrun.py:180-182` and already
  exercised twice (`seed` at `:182`, the eight accounting columns at `:197-204`).
  The value is on the client the harness already holds, so no call site needs a
  new argument; old rows simply lack the key. **Command.**
  `.venv/bin/python -c "import json; print('model' in json.loads(open('docs/eval-data/2026-08-17-devteam-ladder-graph-off.jsonl').readline()))"`
  → `False`. (Measurement.)
- **RB-P39 — the bar's §2 statistic cannot separate the apparatus from the
  trajectory the apparatus induced, and on the only moving delta that is 49.1% of
  it.** `tokens ≡ model_calls × tokens-per-call` is an identity, so the split
  rests on no assumption: ×1.3667 from more turns, ×1.3830 from bigger turns,
  product 1.8901 = the observed ratio exactly. `model_calls` is 90, 90, 90, 123.
  **Attack:** define a turns-normalised companion figure in the bar — tokens per
  model call beside the raw delta — so a flag that wins by talking less is
  distinguishable from one that wins by talking cheaper. Do **not** subtract the
  trajectory out silently; report both. **Command.** The probe, Table M5b.
  (The bar's §2 statistic. Recorded in A6.)
- **RB-P40 — REGRESSION. Line-pin drift, now six times in one job, the sixth
  committed by the unit whose brief opened with the other five; the checker is
  filed and still not built.** Five instances were caused by a source commit
  landing after the prose (`8ccd084` +14, `a478053`, `ec25fbd` +3) or by copying a
  superseded correction table; the sixth (`940ed89`) was two pins written from an
  artifact register **instead of read at HEAD**, in a job whose own DO-NOT list
  names the shift. The register was itself an unread pin store and has since been
  repaired. **What is now measured is that human re-reading has caught it six
  times out of six, at the cost of six units' attention.** No number and no
  verdict rests on a pin, which is why this is Important and not Critical.
  **Attack:** a checker, run as a node, that extracts every `path:line` and
  `path:a-b` pin from `docs/` and `runtime-py/`, reads the line at HEAD, and
  fails when a pin lands on a blank line, a comment, or a construct whose name
  the surrounding prose does not contain. That is mechanical, and the six
  instances are its test corpus. **Command.**
  `git show 940ed89` — two distinct pins, three occurrences; and to re-read any
  pin rather than trust it:
  `for n in 182 194 135 181; do printf "%-4s %s\n" $n "$(sed -n "${n}p" runtime-py/src/bantamkit/filegraph.py)"; done`.
  (Process. No artifact to amend; recorded in A6 and A8.)
- **RB-P41 — REGRESSION, worse in magnitude. CI never reads `docs/eval-data`, and
  six of the seven committed field programs are exercised by nothing.**
  `.github/workflows/ci.yml` lints `.` under `working-directory: runtime-py`,
  lints `examples` separately, and tests `python -m pytest runtime-py -q`.
  **Nothing in CI reads `docs/eval-data`**, and the local command every report
  quotes — `ruff check runtime-py tools/pinharness tools/devteam docs/eval-data`
  — is correct and is **not what CI runs**. Measured at this section's HEAD: of
  the **seven** `2026-08-17-devteam-*.py` programs, exactly **one**
  (`…ladder-field-measurement.py`) is reached by a node, via
  `spec_from_file_location` in `test_ladder_statistics.py:30, :41`. The other six
  are reached by nothing — one is named in a `test_evalrun.py` docstring only,
  which is a string match and not a guard. **Among the six is
  `…workload-measurements.py`, the sole derivation of the 5.819% ceiling that is
  the live refutation of `>60%`.** A rename in `filegraph.py` or `client.py`
  would leave the suite green, CI green, and the number carrying this section's
  headline unreproducible until somebody ran it by hand. This is the RB-P28
  problem one level out: **a suite that cannot see the evidence.** All seven run
  at HEAD, exit 0 — a fact about today. **Attack:** guard each program by
  **import** rather than execution — the shape `test_ladder_statistics.py`
  already uses — so a node goes red when a program stops being loadable, without
  moving the measurement inside pytest and defeating its purpose. Widening CI's
  lint to the repo root is a separate change and interacts with the note below.
  **Command.**
  `git ls-files 'docs/eval-data/2026-08-17-devteam*.py' | wc -l` → `7`;
  `grep -rn "spec_from_file_location\|_FIELD_PROGRAM" runtime-py/tests/*.py` →
  one pair, both in `test_ladder_statistics.py`;
  `grep -n "working-directory" .github/workflows/ci.yml` → `runtime-py`.
  (CI.)
- **RB-P42 — an integrity audit asserted zero deletions and the bar has two.**
  The claim was that every bar amendment is a pure append and *"the bar file has
  ZERO deletions in its entire history"*. Measured over the file's whole history:
  **1106 insertions, 2 deletions** — `bd7f8f8` is 20/1 (it deleted the word
  `None.` from `## 9. Amendments`, a stale-state marker) and `3f47f9f` is 2/1.
  **The discipline holds exactly as claimed; the audit statement about it does
  not**, and both deletions are declared and neither touches a number or a
  verdict. Recorded because those two lines are also the committed precedent for
  the pointer-versus-record distinction. **Attack:** an audit sentence asserting a
  count must be generated from the command, not written beside it — and the
  zero worth asserting here is the **right-hand side of the numstat**, not a
  prose adjective. **Command.**
  `git log --follow --numstat --format="" -- docs/eval-data/2026-08-17-devteam-bar-preregistration.md | awk 'NF==3 {a+=$1; d+=$2} END {print a, d}'`
  → `1106 2`. (Process.)
- **RB-P43 — a correction count counted a creation.** The claim was that one unit
  *"corrected its own committed report in place four times"*. **Three did**:
  `e6037a1` is **704/0** on that report — the commit that **created** §1-§12 —
  and its in-place 3/3 edit is to the field **program**, committed one commit
  earlier at `655bb76`. The substantive verification (no claim, number or verdict
  moved in any of the four) reproduces. **Attack:** an audit of in-place edits must
  read each diff's numstat and reject any commit whose deletion count is 0 from
  the "corrected in place" set — a pure append is not a correction, and counting
  it as one flatters the discipline it is measuring. **Command.**
  `git show --numstat e6037a1 af918b6 6303c90 12db6b6`. (Process.)
- **RB-P44 — insertion counts written before they were measured, twice, the
  second by the unit that flagged the first.** A field report stated its own
  append as *"703 insertions"*; measured, `git diff --numstat 290c834 e6037a1` is
  **704/0** (and 706/0 at HEAD). The review that filed that as a Minor then wrote
  *"`@@ -930,3 +930,53 @@`, 50 insertions"* in `914a87b`'s body one commit later;
  measured, it is **`@@ -931,3 +931,51 @@`, 48/0**. **Both load-bearing halves —
  0 deletions, a pure append — are exactly right**, so nothing rests on either
  count, which is why this is Minor and why it is worth correcting anyway: a
  pushed commit message cannot be corrected without rewriting history, so it is
  recorded and left alone. **Attack:** measure the hunk header and the insertion
  count **before** writing the body, from `git diff --numstat` against the staged
  tree — or omit the count and cite the command, which is what a count inside a
  document that the same commit changes is worth. **Command.**
  `git diff --numstat 290c834 e6037a1 -- docs/eval-data/2026-08-17-devteam-ladder-measurement.md`
  → `704 0`;
  `git show --numstat --format="" 914a87b -- docs/eval-data/2026-08-17-devteam-review.md`
  → `48 0`. (Process.)
- **RB-P45 — the version the MCP server advertises is pinned to nothing, and it
  has been wrong on this machine for nineteen minor releases.** Found by bumping
  `0.21.0 → 0.22.0` and then asking what reads the number.
  `mcpserver._version()` returns `metadata.version("bantamkit")` — the version of
  the **installed distribution**, not the one in `pyproject.toml` — and its only
  fallback is `PackageNotFoundError → "0.0.0"`. A *stale* editable install is not
  an error, so it does not fall back: it returns a confidently wrong number.
  Measured in this repo's venv: the resolved dist-info is
  **`bantamkit-0.3.0.dist-info`**, so `build_server` has been advertising
  **`0.3.0`** to every MCP host on this machine while the package declared
  0.4.0 through 0.22.0. **No node pins the two together** — the bump turns
  nothing red, which is the defect, and CI happens to be immune only because it
  installs fresh every run, so CI can never observe the failure mode. The
  blast radius is a version string a host displays and a client could branch on,
  not a measurement, which is why this is Minor. **Attack:** assert the relation
  rather than the number — a node that reads the version out of
  `runtime-py/pyproject.toml` and requires `_version()` to equal it, skipped only
  when the package is genuinely not installed. That goes red on a stale install,
  which is the case a fresh-install CI cannot see, so it belongs in the suite and
  not in the workflow. Alternatively have `_version()` distinguish "not
  installed" from "installed, and here is what the install says", and never
  present the latter as the package's version. **Command.**
  `ls -d .venv/lib/python*/site-packages/bantamkit*.dist-info` →
  `bantamkit-0.3.0.dist-info`;
  `.venv/bin/python -c "import importlib.metadata as m; print(m.version('bantamkit'))"`
  → `0.3.0`, against `version = "0.22.0"` in `runtime-py/pyproject.toml`;
  `grep -rn "_version\b" runtime-py/tests/*.py` → no node. (Layer 5 —
  Composition; `mcpserver.py` is where the number is presented.)

##### One gate was two gates, measured

**`ruff check docs/eval-data` enforces a strictly broader rule set than
`ruff check` inside `runtime-py`**, so "ruff clean" means a stricter thing in that
tree than in the package. No config covers `docs/`, so ruff resolves
`file_resolver.project_root` to the **repo root** there and falls back to its
built-in defaults, while a file under `runtime-py/` resolves to
`runtime-py/pyproject.toml` and its explicit `select = ["E", "F", "W", "I", "UP", "B"]`.
Measured with ruff 0.16.1: **413 enabled rules over 37 prefixes** for
`docs/eval-data` against **153 over 6** for the package — the extra prefixes
include `S`, `D`, `N`, `PL*`, `RUF`, `TRY` and `SIM`. Demonstrated on identical
bytes:

```sh
printf 'import subprocess\n\ndef f(x):\n    subprocess.run("ls", shell=True)\n    if x == 3:\n        return 1\n    return 0\n' \
  | .venv/bin/ruff check --stdin-filename runtime-py/src/bantamkit/_probe.py -   # 1 error
printf 'import subprocess\n\ndef f(x):\n    subprocess.run("ls", shell=True)\n    if x == 3:\n        return 1\n    return 0\n' \
  | .venv/bin/ruff check --stdin-filename docs/eval-data/_probe.py -             # 2 errors
```

This is recorded and not fixed. It cuts both ways — the field programs are held
to a **higher** standard than the package, which is fine, but the two trees are
gated by different rules under one sentence, and a reader running the package's
gate would reasonably believe otherwise. It also constrains RB-P41's fix:
widening CI's lint to the repo root would import 413 rules over `docs/`, which is
a decision to take deliberately rather than as a side effect.

##### CI on this branch, re-measured rather than cited

**The repo-wide runs endpoint refuses; the per-workflow endpoint does not**, and
that distinction is the whole reason this could be confirmed.
`gh api repos/<owner>/bantamkit/actions/runs?...` and `gh run list` both return
**HTTP 404** on a private repo with a token holding `repo` + `workflow`, while
`actions/workflows/<id>/runs` and `actions/runs/<run_id>` both resolve. Measured
with the working route:

```sh
gh api --paginate \
  "repos/Ink01101011/bantamkit/actions/workflows/329302971/runs?per_page=100&branch=feat/devteam-workload-baseline" \
  --jq '.workflow_runs[] | [.id, .head_sha, .conclusion] | @tsv'
```

- The two runs previously **reported but not confirmed** both reproduce:
  **`32036916943`** at `f5cab04` **success**, **`32037541803`** at `aa97725`
  **success**.
- **The previously reported "seven commits with no run of their own" reproduces
  for that unit's own commits and understates the branch by a wide margin.**
  Branch-wide: **25 runs against 40 commits**; **13 commits have no run at all**,
  and a further **4 have only a `cancelled` run** (the workflow sets
  `cancel-in-progress`), so **17 of 40 commits have no successful run of their
  own**. The cause is benign and structural — `ci.yml` triggers on
  `pull_request`, so a batch push produces one run at the batch tip — but
  "green at HEAD" is what was measured, never "green at each commit".
- **One run on this branch was RED and it is not hidden:** `32017743711` at
  `8ccd084`, when a test landed one commit before the asset it reads
  (`EvalConfigError: no task files found`). Its `failure` conclusion is confirmed
  here at the run level; the "Linux, both Python versions" detail is **cited from
  the record written at the time**, not re-measured, because per-job data is now
  unreadable. Green from `8a6048e` onward. That is exactly what
  the invariant "run CI at the first unit that touches source, not at the PR"
  exists to catch, and it caught it.

**The `25 / 40` above was measured at `aa97725`, and the closure unit then did
the same thing it had just corrected.** Appended rather than rewritten, because
a count inside a document that the same push changes is worth what RB-P44 says
it is worth. This section's four commits were pushed as **one batch**, so they
produced **one run** — `32040160901` at `d31a46f`, **success**, `pull_request`
(run-level conclusion; see the note below on per-job data) — and **three of the
four got no run of their own**. Read
the branch figure as: at `d31a46f`, **26 runs against 44 commits**, **18 with no
run at all**, **23 with no successful run of their own**. The pattern is
structural, not anybody's carelessness, and that is exactly why it should be
fixed mechanically rather than by asking units to push one commit at a time —
`ci.yml`'s `pull_request` trigger plus `cancel-in-progress` means per-commit
coverage on a feature branch is **unobtainable by discipline alone**. Not filed
as a numbered problem because nothing rests on per-commit coverage that
green-at-HEAD does not already carry; recorded because two units in a row have
now reported it as if it were a one-off.

**Per-job conclusions could not be read.** `actions/runs/<id>/jobs` and
`commits/<sha>/check-runs` both return **HTTP 404** on this repo, the same class
of refusal as the repo-wide runs endpoint, so every conclusion above is confirmed
at the **run** level. The matrix (`3.11`, `3.12` on `ubuntu-latest`) is what the
workflow declares, not something this section verified per job.

##### Invariants re-verified at this section's HEAD rather than cited

`docs/eval-data` against `main`: **0 deleted lines** — nothing regenerated,
nothing retro-edited, across 9,661 insertions. `assets/evals/devteam/`,
`assets/evals/tasks/` and `assets/evals/perturbations/`: **0 files changed** since
`26e81a0`. The bar carries **eight** dated amendments A1-A8, `§1-§8` untouched.
`build_tasks.py check`: **OK — 8 tasks match the manifest**. Suite: **842 passed,
2 xfailed**.

```sh
git diff --numstat main..HEAD -- docs/eval-data | awk '{a+=$1;d+=$2} END {print a, d}'
git diff --stat 26e81a0..HEAD -- assets/ | wc -l
```

**No all-on-versus-all-off number is reported here and none is computable from
the committed programs**: `PAIRS` holds only adjacent rungs, by construction.
`budgeted` is not a candidate rung — its only lever is refusing *future* work at
two `allow()` call sites, so it cannot reduce the tokens of work already done.
And the five-arm design remains a **specification**: only the filegraph exists;
the code graph, memory graph and doc/spec graph do not.

##### Why the next job is not another arm on this surface

The follow-on is **not** a second model on this ladder and not a fifth
configuration. `qwen2.5:14b-instruct` is installed and deliberately **unrun** —
choosing a model after seeing that the first realised 0 repeats is choosing a
model for its result, and RB-P37 sharpens that fence rather than weakening it.
More importantly, the ceiling here is a property of the **surface**: with
`0/30` pressure once the memoisation is allowed, no arm on this workload can move
`Δ%(A2−A1)` off zero without manufacturing the redundancy the mechanism is
supposed to remove, which is the defect and not the fix.

So the next measurement moves to a surface where redundancy is a **property of
the input rather than of the solver's discipline**: `compaction-mcp`, against a
pre-registered bar, on a real transcript corpus. Named here only as a pointer —
no design, no bar and no numbers, because writing any of those before the corpus
exists is the failure this job spent eight units avoiding.

#### N (2026-08-17) — J2's precondition unit: two J1 findings closed, and one defect the closures created

Job `compaction-measured`, unit U1. **No number about compaction appears here** — the
corpus is unread by construction and the bar is U2's. This section exists for one reason:
closing RB-P38 broke something, and the break belongs in the register beside the finding
that caused it rather than in a commit body nobody greps.

Closed here: **RB-P38** (`model: str | None = None`, an additive trailing field on
`TaskResult`, read at HEAD at `evalrun.py:214`, sourced by duck typing off the client so
no call site gained an argument) and the **suite half of RB-P41** (a node file that guards
every committed field program on four surfaces, discovered from the union of `git ls-files`
and a glob). **The CI half of RB-P41 is NOT closed**: nothing in CI reads `docs/eval-data`
at this HEAD, and widening `ruff` to the repo root would import 413 rules over `docs/`
against the package's 153 — a separate change with a separate blast radius. **RB-P36 is
not touched** and is J2's bar's problem, not this unit's.

##### Measured and NOT fixed at the time it was found — then fixed, because it was ours

- **RB-P46 — a byte-identity reproduction check is structurally incompatible with the
  additive-field convention the same harness documents, and RB-P38's own fix proved it by
  breaking one. Introduced by this unit and found by this unit.**
  `…instrument-validation-run.py --check` regenerates its artifact and required the bytes
  to be **identical** to the committed `.jsonl`. `TaskResult` is under a documented
  additive trailing-field convention — old rows simply lack a new key — and RB-P38 added
  `model` under exactly that convention. Measured: committed **8558 B**, regenerated
  **9166 B**, **+608 B over 16 rows = 38 B/row**, which is
  `, "model": "walk-client/deterministic"` character for character. **When J1 closed, all
  ten committed field programs exited 0; at `cf8b07e` it was nine of ten.** The two
  promises are contradictory in principle: the convention says the committed rows may lack
  a key, byte-identity says the new bytes equal the old bytes, and **the next additive
  column breaks the next such check the same way**. What makes it more than untidy is
  *where* the red light sits — on the one program whose entire job is to demonstrate that
  committed evidence still reproduces. A red light there makes the **wrong** repair the
  obvious one for the next unit: regenerate the committed rows, which is the single act
  that artifact cannot survive. Measured blast radius today: of the **ten** committed field
  programs, exactly **one** carries a `--check` byte-identity gate — the one that broke.
  Its sibling `…critical-closure-field-measurement.py` compares **named columns**
  (`LEDGER_COLUMNS`, the `C2-3` cell check) and was immune, which is the shape that
  survives. So this is a latent break in every *future* artifact verified by whole-line
  identity, not a second broken program today. **Attack, and it was taken:** compare on the
  **committed file's own key list**, allowing only columns **declared** in a dated tuple to
  be present on the regenerated side and absent from the committed one — the additive
  convention applied to the CHECKER instead of only to the writer — while keeping the row
  count exact, the shared keys compared on serialised bytes, and byte-identity as the first
  thing tried and the strongest result printed. Two formalisations that fail, both measured
  rather than reasoned about: *committed keys as a strict PREFIX of regenerated keys* — the
  natural reading of "additive **trailing** field" — goes **RED on the unperturbed
  control**, because `model` is trailing on the dataclass but the program appends `kind`,
  `ladder_arm` and `client` after `asdict()`, so in the **row's** key order the new column
  lands mid-list and position cannot carry the rule; and *compare the intersection of the
  key sets* **PASSES** a mutation that deletes a committed key from the artifact, which is
  a checker green-lighting a mutation of committed evidence. A checker that passes because
  it stopped checking is worse than a red one, so the repair is only worth what its
  mutations show. **Command.**
  `.venv/bin/python docs/eval-data/2026-08-17-devteam-instrument-validation-run.py . --check`
  → exit **1** at `cf8b07e` (`committed: 8558 B` / `regenerated: 9166 B`), exit **0** at
  this HEAD, printing that it reproduces on every committed key while **not** being
  byte-identical and naming the one declared addition. And on a **scratch copy** of the
  tree, never the repo — seven perturbations, each exit **1**: one `collapsed_bytes`
  `200`→`201`; the same cell `200`→`200.0`; one committed key (`query_bytes`) deleted from
  one row; one row deleted; two committed keys reordered with values unchanged; `passed`
  `true`→`false`; and the declaration itself emptied so that `model` becomes undeclared.
  `grep -c '"--check"' docs/eval-data/*.py` locates the one gate;
  `git ls-files 'docs/eval-data/*.py' | wc -l` → `10`. (Instrument — the
  evidence-verification path. Amended in
  `docs/eval-data/2026-08-17-devteam-instrument-validation.md`, Amendment 3; the `.jsonl`
  is NOT regenerated and Amendments 1 and 2 are not edited.)

#### O (2026-08-18, v0.23.0) — J2's closure: the target refuted by arithmetic, three TRADES and no reduction, and an instrument that reports 16 of 22

Job `compaction-measured`, unit U7. The full record is
`docs/eval-data/2026-08-18-compaction-closure.md`; the bar is
`docs/eval-data/2026-08-17-compaction-bar-preregistration.md` (committed before the
corpus was read, amended A/B before the first arm, amended C after the review);
the corpus is `docs/eval-data/2026-08-17-compaction-corpus.md`; the arms are
`docs/eval-data/2026-08-18-compaction-arms-measurement.md`; the adversarial review
is `docs/eval-data/2026-08-18-compaction-review.md`. **This unit recorded and fixed
nothing.** U5's four Majors and four Lows are open below, each with a command.

##### The number, per stratum, with n on every figure — never pooled

The user's ruling before any number existed: *"ห้าม pool เป็นเลขเดียว"*.

**Stratum A — subagent sidechains.** Corpus n=206; declared hash-order prefix
sample n=50; **effective n=24**, because 26 of the 50 have zero boundaries in B1
and their B1 rows are bit-identical to B0 on all 22 outcome columns.

| pair | conditionality | median, **n=24** | median, **n=50** |
|---|---|---|---|
| **B1−B0**, `context_compact` | **UNCONDITIONAL** | **−40.1421%** of B0 | **+0.0000%** of B0 |
| B2−B1, trim *given* compaction | CONDITIONAL | −22.7575% of **B1** | — |
| B3−B2, offload *given* compaction+trim | CONDITIONAL | −7.9204% of **B2** | — |

**Both B1−B0 figures or neither.** The n=50 median is exactly zero because 26
structural zeros own the middle of the distribution; the n=24 median is not the
corpus. Without the declared fixed per-call constant, over the same n=24:
**−58.9356%**, **−42.1513%** of B1, **−19.5665%** of B2 — committed on all 600 rows
and never printed by the run, which is **M-U5-1**, open.

**All three pairs are TRADES and none is a reduction.** Bar §4 reserves "reduction"
for a delta at a retention within its floor with `anchors_lost_stable == 0`. Median
anchor retention on B1−B0 is **0.0547955** at n=24 against a headline-grain floor of
**0.001472**, with **2,621** anchors lost in all three repeats.

**The handed 80% target is REFUTED on stratum A by arithmetic, before any arm ran.**
R1's zero-summary ceiling over the n=104 informative stratum-A transcripts is a
median **−42.6107%** with the declared constant and **−61.3963%** without it; **1 of
104** transcripts has a *ceiling* reaching −80% with the constant, 3 of 104 without
it. It survives all five compositions of reading A the bar's own sources permit, each
on its own subset and each with the constant: **−42.6107%** at n=104, **−44.2110%**
at n=94, **−48.6465%** at n=69, **−49.1159%** at n=65, **−64.1139%** at n=15.

**Stratum B — top-level sessions. n=1, UNINFORMATIVE-BY-N, no verdict, no floor
borrowed, and its ARMS ARE UNMEASURED** — a different state from UNINFORMATIVE-BY-N.
The declared prefix stops at rank 50 and stratum B sits at rank 51; the rule was not
amended after the fact to reach it. Its published boundary count of **12** is a
**lower bound** (Amendment C(4)).

**The recall axis is UNMEASURED, not "no benefit"** — `rehydrated_bytes` is 0 on all
600 rows and the path never fired. The recall mode was pre-declared `lexical`.

**The dependence structure appears in no committed artifact.** Stratum A is 4 parent
clusters sized **138/31/27/10**, largest 67.0%; Kish `n_eff` at ρ=1 is **2.04** on the
corpus and **3.56** on the 24-transcript headline set. **ρ=1 is a pessimistic bound,
not an estimate.** No `.jsonl` carries a parent, session or cluster column and no
document but the review mentions it — recording the join key would put a
cross-project identifier into an artifact permitted numbers only, so the gap is
declared rather than closed.

##### The instrument, counted honestly — and the count is the deliverable

**PINNED 16 of 22 named checks** (7 MEASURED, 9 PINNED), **1 UNMEASURED, 4 UNPINNED,
1 INTERNAL**. Fifteen `--mutate` modes, **all exit 1**, and **twelve move a printed
figure**; the three that move nothing but their own check line and the two-line banner
are exactly the three UNPINNED checks that have a mutation at all. The fourth UNPINNED
check has no mutation — its condition tests that a skipped count is an integer, which
no artifact the program writes can falsify.

**A closure reporting only "22 named checks, 0 red" would be the overclaim this whole
program exists to prevent**, and the number that makes it one is the 4.

##### Measured and NOT fixed — open, each with an attack direction

The four Majors and four Lows below are **U5's, still open**. Every command was run at
this HEAD. U5 filed three of the four Majors and all four Lows **with no command**;
those commands are supplied in the closure document, and one could not be constructed
at all — see RB-P52.

- **M-U5-1 — the without-constant arm figures were promised beside every
  with-constant one and never printed.** U4 §1.2 declares it of the fixed per-call
  cost; it is true of R1 and false of the arms, though
  `context_tokens_sent_no_fixed` is committed on all 600 rows. The named check
  `CHK-FIXED-COST-DECLARED` tests only that the two **R1 ceiling** columns exist on
  the B0 rows and cannot see the arms at all. Direction is honest — the printed
  figure is the smaller saving — and the omission is still against the unit's own
  declaration. **Attack:** for every "printed beside" promise, name the check that
  enforces it. (Layer: `docs/eval-data/`. Command in the closure document §6.)
- **M-U5-2 — anchor retention may be the compression ratio wearing a fidelity name,
  and the quantitative claim is NOT REPRODUCIBLE.** The qualitative Major stands:
  retention is a proxy, bar §3.2 says so, and nothing here separates "the block is
  small" from "the block lost the right strings". The *numbers* do not: only the
  retention median (0.0547955, n=24) comes from a committed column. The filed ratio
  rests on "bytes it replaced", which is not a committed column and not derivable
  from one; five candidate denominators built from the committed columns span
  0.000518 to 0.410644 at n=24 and none matches the filed value. **The filed ratio is
  downgraded to UNREPRODUCIBLE and is not repeated as a number.** **Attack:** before
  believing a ratio, name the committed column its denominator comes from.
  (Layer: `docs/eval-data/`.)
- **M-U5-3 — events are dropped by the cutoff guard before the skip is counted, and
  the count GREW within one day.** In `reconstruct()` the guard
  `if not survey._under_cutoff(...): continue` precedes
  `skipped[kind] = skipped.get(kind, 0) + 1`, so a cutoff-dropped event never enters
  `skipped_event_kinds` and `CHK-EVERY-SKIPPED-KIND-ENUMERATED` cannot see it, while
  bar §1.2 makes an unenumerated skip VOID. U5 measured 1,314 unenumerated drops
  (344 of carried kinds, 553,877 content bytes) earlier on 2026-08-18; re-measured
  hours later it is **1,471** (413 of carried kinds, **713,315** bytes) against a
  committed enumerated 1,123 that does not move. **Reading-dependent — ESCALATED, not
  picked**: either the transcript *is* the pre-cutoff window and nothing was skipped,
  or it is the file and §1.2 fires. Both arms see the same truncated input, so no
  delta is biased. **Attack:** look for a `continue` that precedes the counter meant
  to observe it, and re-run a live count on a second date.
  (Layer: `docs/eval-data/`. Command in the closure document §6.)
- **M-U5-4 — the fidelity floor is taken over one arm where the token floor is taken
  over two.** Bar §3.1 departure 1 makes the token floor the max over both arms and
  §3.2 says the fidelity floor has "the same shape"; the program computes it from arm
  Y only. Reproduced at n=24: B1−B0 `0.001472` either way, B2−B1 `0.011034` either
  way, **B3−B2 `0.009446` against `0.011034`, a factor of 1.168**. No verdict moves and
  the direction is harsher on the mechanism; filed because the two definitions are not
  the same shape and one will matter on a corpus where retention is not two orders of
  magnitude below its floor. **Attack:** wherever a bar clause says "the same shape as"
  another, diff the two implementations. (Layer: `docs/eval-data/`.)
- **L-U5-1 — the frozen anchor data carries dead weight, and structurally more than
  empirically.** The `screaming` class contributes 0.00% of the anchor set because it
  requires an underscore and `snake` — which matches uppercase — precedes it in the
  alternation, so it can never win. **27 of 35** stop-list entries can never match
  **any** class at `ANCHOR_MIN_LENGTH = 6`, structurally; U5's empirical 29 of 35 that
  never fired is the same fact plus two entries that could match and did not occur.
  The stop-list removed 48 of 2,942 anchors, 1.63%. **Direction: evidence AGAINST
  tuning — a tuned list fires.** Not fixed, because editing the frozen lists is what
  bar §3.2 forbids. **Attack:** run each frozen list against its own consumer and ask
  what could ever match. (Layer: `docs/eval-data/`.)
- **L-U5-2 — retention is scored by substring containment.** `_retained_anchors` ends
  `return {anchor for anchor in anchors if anchor in installed}`, so an anchor counts
  as retained when it occurs inside a longer string. Generous to the mechanism;
  immaterial at a retention of 0.0548 against a bar of 0.9985. **Attack:** read the
  scorer, not its name. (Layer: `docs/eval-data/`.)
- **L-U5-3 — line-number pins in amend-only artifacts, and the census is larger than
  filed.** See RB-P50 below for the measured form. Binding and still binding: any
  amendment to `2026-08-17-compaction-corpus.md` must **append at the end** or
  Amendment B's six pins into it break irreparably. This closure appends nothing to
  that document. (Layer: `docs/eval-data/`.)
- **L-U5-4 — the fidelity axis's own free parameter cannot be audited from the
  committed evidence.** Recomputing retention under a different anchor class list
  needs the installed block *text*, which is not committed and could not be without
  breaching the user's "numbers and statistics only" fence. A reviewer can verify the
  lists never moved and can measure their effect on `anchors_total`; a reviewer cannot
  re-derive retention. **Recorded rather than fixed — the fence is right and the
  limitation is real at the same time.** (Layer: the fence, not the code.)

##### New findings

- **RB-P47 — a cross-check between two transcriptions of one rule is a tautology, and
  it can carry a load-bearing check for a whole job.** Bar §1.2's VOID check compares
  `recorded_content_bytes` against `reconstructed_content_bytes` and the program's own
  docstring said the two were *"computed by different code paths over the same input"*
  so that an unhandled block type would turn the check RED. They dispatch on the
  identical four types — `text`, `thinking`, `tool_use`, `tool_result` — and both fall
  through to empty/zero, so **an unhandled block contributes 0 to BOTH sides** and the
  delta stays 0. Two code paths, one rule, transcribed twice. Measured cost on this
  corpus: **54 blocks** (`tool_reference` ×52, `image` ×2), all nested inside
  `tool_result` content, **821,174 B**, **2.7578%** of the 29,776,563 B the
  reconciliation certifies as perfectly carried, across 22 of 207 transcripts. It is
  invisible three ways at once — not in the byte delta, not in `skipped_event_kinds`
  (they are blocks, not events), and not in the survey's `content_block_kinds`, which
  enumerates top-level blocks only. **Blast radius measured before it was published,
  because a Critical that overstates itself is the failure mode on this side: 150 B
  across 3 of the 24 informative sampled transcripts, so no arm figure and no verdict
  moves.** The rule: **before trusting any A-versus-B agreement, name an input that
  would make them disagree.** If you cannot, the agreement is a theorem.
  **Attack that closed it:** leave the rendering rule byte-identical — changing it
  would have silently invalidated `reconstructed_content_bytes` on 22 committed rows —
  and add a separate census whose non-emptiness reddens a new check. **Command.**
  `.venv/bin/python docs/eval-data/2026-08-18-compaction-arms-field-measurement.py --mutate unmodelled-content-block`
  → exit 1. (Instrument — the null control. Recorded in the bar's Amendment C(4); the
  `.jsonl` is NOT regenerated.)
- **RB-P48 — count vacuity from the OUTPUT, not from the source.** An earlier audit
  grepped each mutation policy key for its consumers and found **5** vacuous. Asking
  instead *what changes in the printed report* found **11 of 14** mutations moving
  nothing but their own check line, and **9 of 20** named checks whose condition reads
  no measured data at all. Two keys the source-side audit cleared were dead on the
  evidence: `borrow_floor`'s site is real but guarded by `stratum == "B"` and **every
  committed arm row is stratum A**, so the branch is unreachable; `threshold_t`'s
  schedule is built from the module constant, not from the policy dict. **And the
  exit-2 detector cannot catch this class by construction** — a tautological mutation
  *does* redden its named check, so it exits 1, the correct-looking code. The
  instrument built to detect a mutation that proves nothing is blind to exactly this
  shape. **No mutation was deleted**; seven flags gained a consumer that moves a
  printed number and the remainder are declared in a printed self-audit. **Command.**
  `.venv/bin/python <arms program> > /tmp/base.txt` then per mode
  `diff <(grep -v '^  \[' /tmp/base.txt) <(grep -v '^  \[' /tmp/m.txt) | grep -c '^[<>]'`
  → `2` (the banner alone) on `borrow-floor`, `pick-a-grain` and
  `zero-floor-always-valid`, `≥3` on the other twelve. (Instrument — the pinning
  harness for this job's own claims.)
- **RB-P49 — a naive whole-directory liveness sweep is itself an evidence-mutating
  operation, and TWO of the twelve committed field programs rewrite a committed
  artifact and exit 0 while doing it.** A closure criterion of the form "all field
  programs exit 0" invites running every program with no arguments. Measured over the
  twelve: **twelve of twelve exit 0 under an invocation appropriate to each**, but
  **five make a bare invocation the wrong invocation** — one raises `IndexError` and
  exits 1, two exit 2 from argparse on a required positional, and **two overwrite
  their own committed `.jsonl` and exit 0**. Both destructive programs default
  `repo_root` to `.` and take the write branch whenever `--check` is absent; both
  announce it, printing `mode: write` where `--check` prints
  `mode: --check (writes nothing)`. The handoff into this closure named **one** such
  program; the measurement found **two**. Exit code 0 is not a liveness signal when
  the program's default mode is to write. **Attack:** either verify a program by the
  invocation its own artifact documents, or make the destructive mode the flagged one
  and the read-only mode the default. **Command.**
  `grep -n "writes nothing.*else 'write'" docs/eval-data/*.py` → two hits;
  `git ls-files 'docs/eval-data/*.py' | wc -l` → `12`. The write direction was not run.
  (Process, and Layer: `docs/eval-data/` for the fix.)
- **RB-P50 — pinning to an immutable commit trades drift risk for unverifiability, and
  18 of this job's 30 file:line pins took that trade without declaring it.** Line pins
  drifted six times in J1 (RB-P40) and once more inside this job, corrected at
  `3ac1273` to a pattern-delimited span after one added `import` line shifted
  everything below it. The measured census across the four compaction documents at this
  HEAD is **30 distinct `file:line` pins**: **12** point into files in this repository,
  where the target is a living document at a mutable ref and *can* drift; **18** point
  into `compaction-mcp` at the pinned commit `0a15cff`, where they *cannot* drift and
  where **no reader of this repository can resolve them** — the mechanism repo is not
  vendored and CI never checks it out. All 30 resolve today, the 18 external ones on
  this machine only. **The rule is not "count the drifts", which is a number this job
  cannot reproduce from the repository** (three of the four drifts the handoff cites
  are recorded only in gitignored `.shiftwork/` material, and one probe that went
  looking found none). **The rule is: pattern-delimited spans for anything mutable, an
  immutable commit for anything external, and the unverifiability declared when you
  choose the second.** **Command.** the census script in
  `docs/eval-data/2026-08-18-compaction-closure.md` §6, L-U5-3; and
  `git log --oneline -1 3ac1273`. (Process.)
- **RB-P51 — UNMEASURED is a verdict, and a check that quietly passes on data it cannot
  see is not the same as one that reports it read nothing.** Two instances measured in
  this job. `CHK-NO-UNMODELLED-CONTENT-BLOCK` reports **UNMEASURED, not PASS**, because
  its census columns postdate the committed rows and bar §9(5) forbids regenerating
  them — a census that never ran is not a census that found nothing. `rehydrated_bytes`
  is **0 on all 600 rows**, which is the recall path never firing and **not** the recall
  path delivering no benefit; the axis is reported UNMEASURED and no figure is derived
  from it. Stratum B's arms are likewise **UNMEASURED** rather than
  UNINFORMATIVE-BY-N — collapsing the two would let "we did not run it" read as "we ran
  it and learned nothing". **Attack:** for every green check, ask what data its
  condition actually read; for every zero column, ask whether the path executed.
  **Command.** the acceptance run prints
  `22 named checks, 0 red, 1 UNMEASURED, 0 escalations` and names the UNMEASURED one.
  (Instrument.)
- **RB-P52 — a review that opens by declaring every finding carries a demonstrating
  command, and seven of its twelve do not — one of them irreproducible from the
  committed evidence at all.** `2026-08-18-compaction-review.md` opens: *"every finding
  below is filed with a demonstrating command, an attack direction and a layer"*.
  Measured: all **3 Criticals** carry one, and **1 of 4 Majors** does; **3 Majors and
  4 Lows carry none** — 7 of 12. The cost is not stylistic. **M-U5-2's central ratio
  cannot be reconstructed**: its denominator, "the bytes it replaced", is not a
  committed column, five candidate reconstructions from the committed columns span
  0.000518 to 0.410644 at n=24, and with no command there is no way to learn which was
  meant. So the closure unit had to record that Major as UNREPRODUCIBLE, which is a
  strictly worse outcome than either confirming or refuting it. The other six were
  reproducible and were reproduced, and two came out **stronger than filed**
  (M-U5-3's count grew from 1,314 to 1,471 within the same day; L-U5-1's stop-list dead
  weight is structural for 27 of 35 entries, not merely empirical for 29). **Attack:**
  make "carries a runnable command" a property the review's own summary table asserts
  per finding, so that a finding without one is visible at a glance rather than
  discovered by the unit that has to record it. (Process.)

- **RB-P53 — the summarizer in a merged job read 6.6% of what it was sent, the run
  printed that on every execution, and no committed document says so.** Found by J7's
  planner reading `ollama`'s behaviour before running anything, then verified by the
  orchestrator against J2's own committed rows. `compaction-mcp`'s `DirectSummarizer`
  posts to `/chat/completions` with `model`, `messages`, `max_tokens`, `temperature`
  and `stream` — **and no context-length parameter of any kind**. `ollama` therefore
  serves the request at its default window, truncates the prompt, returns
  `finish_reason: "stop"` with **no error**, and reports `usage.prompt_tokens` equal to
  **the window**. Measured on the 216 summarizer rows of
  `2026-08-18-compaction-arms.jsonl`: `summarizer_prompt_tokens_the_endpoint_saw` takes
  the values **4096, 8192, 12288 and 16384** — exact multiples of the window, **144 of
  216 rows at exactly 4096** — and **all 216 rows sent more than the endpoint reports
  reading**, median **8.0x**, max **17.9x**. The tell is distributional, not local: a
  real token count does not cluster on exact multiples of 4096. The acceptance run has
  always printed it — *"2,169,356 tokens sent, 143,360 tokens the endpoint actually read
  (6.6%) — the mechanism sets no context length and never reads back prompt_tokens"*,
  and **11.4%** for B2, **20.5%** for B3 — yet `grep -rn "endpoint saw" docs/eval-data/*.md`
  returns **nothing**: not the bar, not the review, not the closure.
  **What it costs and what it does not.** J2's **token axis stands** — bytes sent and
  summary bytes are measured directly and a truncated summarizer still produced a real
  saving. J2's **fidelity axis is contaminated**: anchor retention **0.0548** with
  **2,621 anchors lost stably** was measured against a summarizer that could not see
  **93.4%** of its input, and a summarizer that never saw an anchor cannot retain it.
  The **TRADE verdict's direction survives** — retention did collapse — but the causal
  reading that summarization loses the anchors is **not established** by this evidence;
  window truncation is an untested alternative of at least the same magnitude.
  **Attack:** any client of a completions endpoint must send the window explicitly and
  then **read `usage` back and refuse it when it equals the window**. An output-side
  detector is the only kind that works here, because the failure is silent, green, and
  arrives as a plausible number. (Instrument. J7's bar declares both halves of the fix:
  a derived tag at `num_ctx 32768` over the identical weight blob, and
  `usage.prompt_tokens == num_ctx` treated as VOID.)

##### Invariants re-verified at this section's HEAD rather than cited

`docs/eval-data` against `origin/main`: **0 deleted lines** across the whole job —
nothing regenerated, nothing retro-edited — with 4,096 insertions in `.md` and
`.jsonl`. The only deletions anywhere under `docs/eval-data` are **5 lines in an
instrument** (RB-P46's byte-identity checker), not in evidence.
`assets/evals/devteam/`, `assets/evals/tasks/` and `assets/evals/perturbations/`:
**0 files changed** by this job. The bar carries **three** dated amendments A, B and C
with `§0–§11` untouched, and this closure appends nothing to it. `runtime-py/src/`:
**0 deleted lines**, which is what makes `0.22.0 → 0.23.0` a MINOR rather than a
major. Suite: **932 passed, 2 xfailed**. `build_tasks.py check`: **OK — 8 tasks**.
Acceptance: **exit 0**, 22 named checks, 0 red, 1 UNMEASURED, 0 escalations. All 15
mutations: **exit 1**. Corpus survey `--check`: **exit 0**, 207 rows.

```sh
git diff --numstat origin/main..HEAD -- 'docs/eval-data/*.jsonl' 'docs/eval-data/*.md' \
  | awk '{a+=$1;d+=$2} END {print a, d}'
git diff --numstat origin/main..HEAD -- runtime-py/src | awk '{d+=$2} END {print d+0}'
git diff --stat origin/main..HEAD -- assets/ | wc -l
```

**CI is confirmed at content level and NOT at run level.** `gh run list --branch
feat/compaction-measured` is **empty** — the branch is unpushed and pushing it is not a
unit's to do. The most recent run in this repository is `32042046595`, `ci`, success, on
`main` at `f0cf440`. CI's three steps pass locally at this HEAD in the exact form the
workflow runs them, on Python **3.12.13 only**; the workflow's 3.11 leg is unconfirmed.
**RB-P41's CI half is still open and this job did not touch it**: nothing in
`.github/workflows/ci.yml` reads `docs/eval-data`, so no field program, no acceptance
run and no mutation is exercised by CI on any branch.

**The scope is stated in both directions, and the excluded side is live where the
included side is not.** In: 207 transcripts selected by recorded `cwd` inside the
bantamkit repo, not by the project directory's name — Claude Code keys that directory
by **launch** cwd, so selecting by name takes 12 files and discards 199 of the 211 that
carry a bantamkit cwd. Out: 426 files with no bantamkit `cwd` today (U3 committed 502),
plus **3** whose `cwd` spans bantamkit and four other project roots — 93.0% bantamkit by
line, the only long human-driven multi-day sessions in the universe, excluded because a
replay would rebuild a prefix carrying other projects' file contents, with the user shown
the cost and declining to lift it. Re-running the survey today gives a universe of
**636** against U3's committed **712**: the 76-file difference is entirely on the excluded
side and the 207 committed rows still reproduce on every named non-live column. That is
what the cutoff buys — it freezes the rows, not the directory.

**Nothing was merged and nothing was tagged.** Tagging has never been authorized in this
program; the merge belongs to the orchestrator.

#### P (2026-08-19) — J3's instrument hygiene: two of eight closed, three carried, three recorded-and-dropped, and a rule that got a checker

The plan was committed before any fix existed
(`docs/eval-data/2026-08-19-instrument-hygiene-plan.md`, `5458059` + its Amendment 1 at
`da5f073`) and it ruled **2 CLOSE, 3 CARRY, 3 RECORD-AND-DROP** on the eight open findings
of `2026-08-18-compaction-review.md`. **A plan that closed all eight would have been the
wrong plan**, and the three dispositions the prep probe recommended and this job overturned
each carry the measurement that overturned them.

**Nearly every figure in this section was recomputed on this branch, and the three that
were not are labelled as carried where they appear and listed together at the end.** The
prep probe that opened this job was itself measured wrong in four places (plan §1.1–§1.9),
so a figure repeated rather than re-derived is a liability and is marked as one.

##### Closed, each with a before and an after from the same command

- **M-U5-1 — the fixed per-call cost was declared and only half-disclosed.** The check
  `CHK-FIXED-COST-DECLARED` tested key presence for the two R1 ceiling columns on the 207
  null-control rows while claiming *"both the with-constant and without-constant figures
  are committed"*. It never looked at the 600 arms rows and it could not see the printed
  report. `grep -c no_fixed` over the committed arms measurement returned **0**: three
  percentages computable from committed columns, written down nowhere.
  **Both halves closed.** The check is widened to the arms rows and to the printed report —
  every reported pair must print a figure under both token columns and must hold the
  with-constant one in the headline position — and a dated Amendment 1 appended to
  `2026-08-18-compaction-arms-measurement.md` prints the three figures:

  | pair | with the constant | without it | ratio |
  |---|---|---|---|
  | B1 − B0 | −40.1421% | −58.9356% | 1.47× |
  | B2 − B1 | −22.7575% | −42.1513% | 1.85× |
  | B3 − B2 | −7.9204% | −19.5665% | 2.47× |

  **The omission was in the safe direction and it was still an omission**: every
  without-constant figure is a *larger* saving, so the document printed the conservative
  column. No verdict moves; −58.9356% is still short of the handed −80%.
  **Command.** `.venv/bin/python docs/eval-data/2026-08-18-compaction-arms-field-measurement.py`
  — before: `[PASS] … both the with-constant and without-constant figures are committed`,
  `grep -c no_fixed` on the report **0**. After: `[PASS] … 3 reported pair(s), of which 0
  PRINTED fewer than both figures and 0 put the without-constant figure in the headline
  position`, `grep -c no_fixed` on the report **3**. `--mutate omit-fixed-cost` exits 1 with
  the check RED naming all three pairs, **and still does with the declaration boolean
  deleted from the condition** — the widened conjunct is load-bearing on its own, counted
  from the printed verdict line and not from a grep over the source (RB-P48). (Instrument.)

- **M-U5-4 — the bar's fidelity formula and the prose two lines above it disagree.**
  §3.1's fenced block reads `max over the two arms X,Y of ( … )`; §3.2's block has **no
  arms wrapper at all**. Only prose claims they have the same shape, and it claims it
  **three** times, not twice as the plan recorded — `grep -c 'same shape'` over the bar
  returns **4**, one of which (§1.2) is unrelated, and the third of the remaining three is
  inside Amendment A, which is itself amend-only. **The program implemented the executable
  block**, filtering on `r["arm"] == y` with no loop over `x`, and it is not in error:
  given a contradiction between a fenced block and a sentence about it, implementing the
  block is the defensible choice. Closed by **Amendment D appended to the bar**, ruling the
  prose authoritative for future runs, with the program untouched — closing this by
  changing the program would have been fixing the artifact that was right.
  **What it is worth, re-derived here:** per-arm headline retention spread B0 **0.000000**
  (retention is 1.0 by construction), B1 0.001472, B2 0.011034, B3 0.009446. Two of three
  pairs are identical **permanently** — for any `Y − B0`, `max(0, spread(Y)) = spread(Y)`.
  Only B3 − B2 moves, 0.009446 → 0.011034, **1.168×**, a shift of **0.001588** against a
  gap of **0.9276755**: the fix closes **0.17%** of the distance and the gap is **584×** the
  shift. **The verdict is BELOW ITS FLOOR under both definitions, on all three pairs, at
  both grains** — had either reading flipped a verdict this would have escalated instead of
  shipping the new number. (Layer 2 — the wording, not the mechanics.)

##### Closed in code: RB-P53's class, the two sites that are in this repository

Both are **LATENT CODE-PATH DEFECTS AND NOT ACTIVE CONTAMINATIONS**, and the negative is
measured rather than assumed. SHAPE probe item N-7, left UNMEASURED by the probe and run
here: `tokens / model_calls` over **7,804 rows across 78 committed files**, **1,770**
distinct values, **zero** exact hits on any power-of-two cap {512 … 32768}, per-call
maximum **2,625** — three orders of magnitude below the windows in question. **No committed
row is sitting on a cap.** Nothing below restates any number.

- **S4, `client.py` (Layer 3).** `usage` was copied without validation and `finish_reason`
  did not appear in the file at all, so a length-stopped completion and a finished one were
  the same object. Now: `Usage.finish_reason` read off the choice, a `truncated` property,
  and `Usage.prompt_tokens_verdict` in {`MEASURED`, `VOID`, `UNCHECKED`} against a
  `context_window` the caller **declares and the client never sends**. `VOID` is
  RB-P53's shape — a silently clamped prompt reports the window in the field a reader takes
  for a prompt size. `UNCHECKED` is RB-P51 — no declaration, so nothing could be compared,
  and that is not `MEASURED`. Both fold worst-first through `__add__`, so a void call
  poisons its sum and a cut call survives it. **It is a detector and not a preventer**, said
  in the source: it cannot stop a clamp, cannot see one below the window, and cannot tell a
  clamped prompt from a genuine prompt exactly `context_window` tokens long.
- **C-6, `agent.py` / `textutil.py` (Layer 1).** Observation truncation was announced **in
  band** — `[truncated N bytes]` inside the string handed to the model — and the number was
  thrown away, so a run whose evidence was cut and one whose was not were the same object to
  every caller, scorer and artifact. Now `AgentResult.observations_truncated` and
  `.observation_bytes_dropped`, zero on an uncut run. `truncate` returns byte-identical
  output and `contract.py` and `filegraph.py` are unchanged.

**Command, and the same one for both.**
`.venv/bin/python docs/eval-data/2026-08-19-truncation-visibility-field-measurement.py .`
— a field program committed **before** either fix so that the before and the after come
from one program and one command.

```
BEFORE   FIELD case=S4-CUT endpoint_said=length client_reports=ABSENT context_window_accepted=False
         FIELD case=S4-CLAMPED endpoint_prompt_tokens=4096 declared_window=4096 client_reports=ABSENT
         FIELD case=C6-CUT expected_bytes_dropped=12000 column_bytes_dropped=ABSENT
         SUMMARY checks=8 red=8      exit 1

AFTER    FIELD case=S4-CUT endpoint_said=length client_reports=length context_window_accepted=True
         FIELD case=S4-CLAMPED client_reports=VOID
         FIELD case=S4-UNDECLARED client_reports=UNCHECKED
         FIELD case=S4-FINISHED client_reports=stop prompt_tokens_verdict=MEASURED
         FIELD case=S4-AGGREGATE left=MEASURED right=VOID summed=VOID
         FIELD case=C6-CUT expected_bytes_dropped=12000 column_bytes_dropped=12000
         FIELD case=C6-UNCUT column_bytes_dropped=0
         SUMMARY checks=8 red=0      exit 0
```

`ABSENT` is a state, not a failure to look: the attribute did not exist. All **eight**
checks are pinned by a mutation that changes the **input** — what the stub endpoint says,
or what the loop is handed — never a policy flag whose only consumer is the condition of
the check that names it (C-U5-2's defect). All eight exit 1 naming their own check; none
exits 2. A bare invocation exits **2** from argparse and the program writes nothing
anywhere (RB-P49).

##### The record-vs-pointer rule, and its checker, in one commit

`docs/record-vs-pointer.md` and `tools/amendguard/amendguard.py`, shipped together at
`b533089` because a rule without a mechanism is another intention for the next pin drift to
step on. **RECORD** — a number, a verdict, a table, a verbatim block, a claim — is amend
only. **POINTER** — a closed list of four classes, P1 hyperlink, P2 section citation, P3
`file:line` pin in all three of its forms, P4 stale-state marker — is correctable in place,
in its own commit, with the correction stated in the body. **CO-MOVING COUNT** carries a
machine-readable derivation the checker recomputes over the committed body. Anything
unlisted falls through to `record`, which is the safe direction and is what makes
`classify` total.

**The checker's field run over its own branch is RED and that is the intended result.**
`python tools/amendguard/amendguard.py check . 5845698..HEAD tools/amendguard/ledger.json`
reported `rows=2 ok=0 red=2` with **nine unstamped gate expectations** across the plan's two
commits. Amendment 1 §5 asked for a checker that catches the defect found in its own design
document, and the defect was a bare pass count with no commit beside it. **Nothing was
retro-edited to make it green.** Two of the nine are prose *about* a gate rather than an
assertion of one; the rule is mechanical, over-reporting is the safe direction, and the
imprecision is recorded in `docs/record-vs-pointer.md` §8 rather than carved into the
checker as an exception — **an exception for "prose about a gate" is the seam the next bare
number walks through.**

**What is NOT guarded, stated because a guard described as wider than it is is this job's
whole subject:** nothing runs the checker automatically (RB-P41's CI half still holds); a
pointer corrected from one wrong line to another reads `OK`; merge commits emit no row; and
**a stamped, plausible, wrong cross-artifact count is detected by nothing.** That last gap
**stays open** and is not closed by broadening the definition.

##### Recorded and dropped — three, each a legitimate close and none a silent omission

- **M-U5-2 — the four filed ratios are withdrawn as unreconstructible.** Re-running the
  sweep: **167** committed quantities, **21,912** ratios actually evaluated, **zero**
  matches for the filed `0.034865`. *(The filing's "27,722 ratios" is a count of ordered
  pairs — 167 × 166 — and the script skips any denominator that is zero on some transcript,
  so the derived "5,544× larger" is **4,382×**.)* **CARRIED from the plan at `5458059`, not
  re-derived here**: the construction that yields exactly 167 quantities is the plan's and
  is not restated in a command anyone else could re-run, which is itself the shape of
  RB-P52. What was re-verified here is the artifact side — 33 / 29 / 44 keys, 600 / 207 /
  207 rows, and no text column in any of the three. The one figure that does reproduce is median retention
  `0.054795` at n = 24. The quantity the filing needs — the bytes the installed block
  replaced — is not a committed column and is not a ratio of committed columns. Not closed
  because there is nothing left to learn from the committed evidence and the qualitative
  half is subsumed on much stronger grounds by the entry pending on
  `feat/compaction-in-the-loop`.
- **L-U5-1 — the `screaming` anchor class can never win the alternation, and 27 of 35
  stop-list entries can never fire.** `L(screaming) ⊆ L(snake)` verified two ways here:
  structurally, and exhaustively over **6,725,593** strings from `{A,B,Z,0,1,9,_}^2..8` with
  **0** matching `screaming` and not `snake`. **0.00% is a theorem, not a sample**, which is
  why the empirical share is not worth measuring. **8 of 35** stop entries can ever be
  emitted as a token by the extractor at all — `README.md`, `json.dumps`, `json.loads`,
  `os.path`, `package.json`, `pyproject.toml`, `self.assert`, `sys.argv` — and greedy
  `qualified` swallows `os.path` inside `os.path.join` and `self.assert` inside
  `self.assertEqual`, so **8 is an upper bound** and 27 of 35 are structurally dead. **Not fixed because
  there is no action available that is not a violation**: bar §3.2 freezes both lists as
  data in the artifact so they cannot be tuned, and the defect points *against* tuning — a
  list selected to move a number would fire; this one is inert by construction.
- **L-U5-4 — the fence's cost.** Every string-valued key in all three compaction artifacts
  is an identifier, a stratum, a mode or a model name. **No text column, in any of the
  three.** An auditor can recompute `anchors_total` from transcripts on disk and **cannot**
  recompute `anchors_retained`, because the right-hand side of the containment test — the
  installed block — is not committed. Committing it would put other projects' file contents
  into an artifact whose fence permits numbers only. **This is a correct consequence of a
  correct fence and the fence stays**; the cost is stated once, here.

##### Carried to J7 as preconditions, handed as properties and not as patches

Four of the eight open findings interrogate the **fidelity axis**, which is already
contaminated and is being re-measured natively. A patch written against frozen code is not
evidence, so J7 chooses the mechanism.

| id | precondition | from |
|---|---|---|
| **F-1** | Every event the reconstruction loop declines is counted, including the two silent `continue`s, and the artifact commits an `events_read` column, so `events_read == carried + Σ skipped_event_kinds` is an identity a mutation can redden. The escalated "is a post-cutoff drop a VOID trigger?" reading travels with it, unresolved. | M-U5-3 |
| **F-2** | An anchor counts as retained only when it is present in the installed block as a **complete token** under the same tokenisation that extracted it. | L-U5-2 |
| **F-3** | The fidelity denominator is disclosed before any retention figure is reported. On the committed evidence it is **288 of 600 rows, 48%**, stated nowhere. | L-U5-2 |
| **F-4** | The committed retention is an **upper bound**; any figure that supersedes it says so. | L-U5-2 |
| **F-5** | The frozen class list and stop list are not touched. | L-U5-1 |
| **F-6** | A length-stopped generation is **VOID**, an instrument verdict, never `FAIL`, an outcome. The window has already shut: **4 of 131** committed calls carry `done_reason: "length"`, absorbed into a `run-cap` VOID rather than classified, so no scored row is yet wrong. | SHAPE S5 |
| **F-7** | A determinism probe cannot report determinism from two responses both stopped by the same cap. | SHAPE S6 |
| **F-8** | `compaction-mcp`'s summarizer and embedding paths — truncated on the way out at a default nobody overrides, stored as the boundary's ground truth, input deleted in the same function, damage cached to disk. Another repository, outside this one's layer model and both ruff gates. | SHAPE S1–S3 |

**L-U5-2 is not closed as a number and no arm is re-run.** Substring containment can only
**add** members to the retained set, so committed retention is an **upper bound** and every
correction moves the verdict **further** into FAIL. Median B1 retention `0.0547955` against
a bar of `0.998528` is **0.9437** away; sending retention to 0.0 still FAILs. Re-running the
frozen arms costs **5.81 h** of measured `wall_clock_s` to move a figure in the direction
that makes the verdict worse. **The attack that did not break it:** a no-op arm scoring 1.0
is impossible — zero-boundary rows carry `anchors_total: 0` and `anchor_retention: null`,
**312 of 600**, and every aggregation filters `is not None`. The residue is F-3, a
disclosure fact, not a defect.

##### New findings

- **RB-P54 — a check whose expectation is a function of the thing being mutated is a
  tautology, and only the exit code shows it.** Found by running this job's own new field
  program, not by reading it. `--mutate observations-under-budget` raises the observation
  budget so nothing is cut; the check derived its expected byte count **from that same
  budget**, so expectation and reality moved together, `0 == 0` passed, and the program
  reported `SUMMARY checks=8 red=0` and exited **2** — *"the claim survived its own
  falsification, which means the claim is not measured"*. This is C-U5-2's shape one level
  in: not a flag whose only consumer is its own condition, but an **expectation** whose only
  input is the mutation. Fixed by pinning the expectation to the declared scenario as named
  constants. **Attack:** for every mutation, ask whether the check's expected value is
  computed from anything the mutation touches; if it is, the mutation cannot falsify.
  **Command.** the two mutation modes now exit 1 naming their own check; before the fix one
  of them exited 2. **The exit-2 branch existing is what caught it** — returning 1 on both
  branches would have made "it exited 1" carry no information and this would have shipped
  reading green. (Instrument.)
<!-- provenance: value=11 failed, 960 passed, 2 xfailed without / 971 passed, 2 xfailed with; commit=f134cca; command=[PYTHONPATH=$PWD/runtime-py/src] .venv/bin/python -m pytest runtime-py/tests -q -->
- **RB-P55 — in a worktree, the suite tests this tree's TESTS against another tree's
  PACKAGE.** The venv's editable install resolves `bantamkit` to the main checkout, so
  `.venv/bin/python -m pytest runtime-py/tests -q` run from a linked worktree imports
  `/Users/…/bantamkit/runtime-py/src`, not the worktree's. Measured, same command, same
  tree, one environment variable apart: **11 failed, 960 passed** without, **971 passed**
  with `PYTHONPATH=$PWD/runtime-py/src`. Every earlier figure in this program is unaffected
  and it is measured so rather than assumed — `git diff --stat b533089..<main HEAD> --
  runtime-py/` is one deleted test file and **nothing under `src/`** — but a Layer 1 or
  Layer 3 change made in a worktree is **invisible to the gate** until the variable is set,
  and a green suite would have been reporting on code that was never edited. **Attack:**
  a gate that resolves its subject through an install rather than through the tree under
  test is not measuring the tree under test; print `bantamkit.__file__` beside the pass
  count. (Instrument / process.)
- **RB-P56 — a length-stopped HTTP 200 is retried by nothing, anywhere, in either
  repository.** The retry ladder in `client.py` covers transport errors, 429 and 5xx. A 200
  whose body was cut at the generation cap is a success by every code path that looks at it.
  **Filed and deliberately not fixed here:** a retry policy for truncation is a Layer 3
  design change with a real failure mode of its own — retrying a length stop with the same
  prompt returns the same length stop — and implementing it inside a hygiene job would be
  the thing this job exists to stop. What J3 ships instead is the **visibility**: after S4 a
  caller can *see* the stop reason, which is the precondition for any policy at all.
  **Attack:** decide the policy where the budget lives, not where the socket does.
  (Layer 3, open.)
- **RB-P57 — no committed column in any of the three compaction artifacts carries the size
  of the input population, so no completeness check over them is constructible.**
  `recorded_events` looks like an input count and is not: `recorded_events += 1` sits after
  every filter — after the blank-line `continue`, after `UNPARSEABLE`, after
  `NOT_AN_OBJECT`, after the cutoff guard, after the `kind not in CARRIED_EVENT_KINDS` skip
  and after `NO_MESSAGE`. It is a **post-filter carried count**. Subtracting the skip totals
  from it mixes populations, and one row proves it: 719 turns plus 701 enumerated skips
  exceed its 1,120 "recorded events" by **−300**, which is only possible because the skips
  were never inside the 1,120. The only other source for the population is the live
  transcript directory, which moved between two units within one day (1,314 drops → 1,471)
  and would move again — a check reading it asserts a fact about the world and is
  non-reproducible by construction (RB-P14 Gate 2). **So `CHK-EVERY-SKIPPED-KIND-ENUMERATED`
  cannot be upgraded on frozen evidence**, and it is already truthfully disclosed as
  `UNPINNED` with the correct reason in the committed source. Closing it would upgrade a
  truthful UNPINNED to PINNED; it would not repair a lie. The denominator travels with F-1.
  **Attack:** before writing a completeness check, name the column that holds the
  denominator; if there is none, the check is about integers, not completeness.
  (Instrument, carried.)
- **RB-P58 — the tag deny rule is a classifier that leaks under composition, and J3 ships
  no guard.** The same evasion **passed once inside a compound command** and was **DENIED
  standalone**, with a reason naming the evasion explicitly. The honest characterisation is
  neither "a tripwire" nor "a wall": **its decision depends on how the command is
  composed**, and this program measured it going both ways within one session. The unit did
  not retry after the denial, which is correct behaviour and which is why the
  newest-tag figure is **UNVERIFIED**. **There is also no pre-push hook**, anywhere: the
  hooks directory holds fourteen `.sample` files, `core.hooksPath` is unset, and nothing
  hook-shaped is committed — the brief's claim that one exists **does not reproduce**.
  **No guard is shipped, for four reasons in descending strength:** `pre-push` fires on
  push and tagging is local, so a hook would guard publication and not creation;
  `core.hooksPath` is local configuration, so a committed hooks directory does nothing until
  somebody opts in by hand and the un-enforceable step is the whole guard; it is bypassed by
  one extra flag by anyone able to run the evasion it defends against; and a repository git
  hook is not one of the five layers. **The residual, unsoftened:** the only thing between
  this program and an unauthorised tag is a permission classifier measured allowing one
  instance of the documented evasion and refusing another. A detector — a field program
  comparing the tag inventory against a committed expectation — is buildable, would work
  only on the machine that runs it, and is **not proposed**, because a guard described as
  protection when it is after-the-fact notification is the failure mode this whole register
  is about. **The standing rule is unchanged and is not a guard: DO NOT TAG.** (Process.)

- **RB-P59 — the closed pointer list permits only the pin form the pin convention
  discourages, and a form migration inside one class reads `RECORD-EDITED`.** L-U5-3 closed
  a convention — *pattern-delimited locators only; never a bare line number* — and
  `amendguard` classifies a pointer correction by masking closed-list constructs and
  requiring the two lines to be **identical outside the mask**. Four candidate corrections
  of the same drifted pin were committed to a scratch commit and measured, and the verdict
  is read off `VERDICT`, not off the source:

  | the correction | `classify` | `verdict` |
  |---|---|---|
  | bare `` `:1288` `` → bare `` `:1608` `` | `pointer:P3` | **OK** |
  | bare `` `:1288` `` → unbackticked `…-field-measurement.py:1608` | `pointer:P3` | **OK** |
  | bare `` `:1288` `` → **backticked** `` `…-field-measurement.py:1608` `` | `record` | **RECORD-EDITED** |
  | bare `` `:1288` `` → a pattern-delimited locator naming the guard | `record` | **RECORD-EDITED** |

  Two consequences, and the second is worse than the first. **The form the convention
  mandates is the one form the checker forbids** — replacing a pin with a pattern-delimited
  locator removes a masked construct, so the masks differ and the line is a record.
  **And the mask is by SUB-FORM, not by class**: the bare-backtick pattern consumes the
  backticks and the path pattern does not, so the *same* P3 class read `OK` unbackticked and
  `RECORD-EDITED` backticked, on one character of difference either side. **Attack:** widen
  `POINTER_CLASSES` with a pattern-delimited-locator class, in a commit that edits the tuple
  and adds its calibration case — `test_every_pointer_class_on_the_closed_list_has_a_fixture_case`
  makes that mandatory — and normalise the mask so a construct's delimiters are part of the
  sentinel. **Not done here on purpose:** widening the rule in the same unit whose own pin is
  about to be judged by it is the author granting himself an exemption, which is the exact
  act the plan ordered the pin correction last to avoid. (Instrument, open.)
<!-- provenance: value=940 passed, 2 xfailed; commit=3f52a86; command=.venv/bin/python -m pytest runtime-py/tests -q — this stamp covers a QUOTATION of a gate figure, not an assertion of one; the checker over-reports on prose about a gate and the shipped policy is to stamp rather than to carve an exception -->
- **RB-P60 — a provenance stamp cannot sit inside a markdown table, and the checker found
  this by flagging its own author.** The field run over this branch reported
  `commit=9cc42c4b1 path=docs/eval.md classify=insert verdict=STAMP-MISSING` on **this very
  section**, naming two unstamped gate expectations: RB-P55's pass counts, and the `940
  passed, 2 xfailed` cell of the corrections table above. **The first was fixable and is
  fixed**, by inserting a stamp four lines above it. **The second is not**, because a stamp
  is a whole-line HTML comment and `STAMP_WINDOW` is eight lines: the cell is the last row of
  a ten-line table, and any comment line placed inside that window splits the table in two.
  The figures are therefore restated, stamped, in a paragraph below the table, and the cell
  itself stays unstamped. **`9cc42c4` is NOT rewritten and stays RED in the log** — a commit
  amended to make the checker green would be the retro-edit this whole rule exists to
  prevent, and the miss is worth more as a record than as a clean history. **Attack:** allow
  a stamp to be attached by a trailing inline comment on the number's own line, which the
  matcher already supports and the *syntax* does not, or let one stamp govern a whole fenced
  or tabular block by name. (Instrument, open.)
**Numbering.** `RB-P53` is **reserved**: it exists on `feat/compaction-in-the-loop` and is
**not merged at this base**, so J3 numbers from `RB-P54` and every sentence here that would
cite it cites the measurement instead. If that branch has also allocated `RB-P54` or above
by the time it merges, J3's are the later entries and J3's renumber.

##### The pin convention, and the census that is deliberately not closed

**Ratified, not invented:** pattern-delimited locators only; never a bare line number; and
**never a pin written from a register rather than read at HEAD.** The rule and its
enforcement are in `docs/record-vs-pointer.md` §1 (class P3) and in `POINTER_CLASSES`.

**The census is NOT closed, and refusing to close it is the finding.** Re-run here over the
same four documents: **28** distinct pin strings under the plan's own command, **27**
deduplicating by target — `compaction-corpus.md:403` and
`2026-08-17-compaction-corpus.md:403` are one target written two ways, and that pair is the
whole difference — and **30 as filed**, which a widened pattern of this unit's own turns into
**35**. **Four answers now, not three**, which strengthens rather than weakens the finding:
**none of the four documents defines the term**, so every count is a count of whatever its
author's regex happened to match. Closing a census with no command behind it would commit
the disease the finding names. Separately, and it must not travel
under the same sentence: **16 of the 27 point into an external repository at an immutable
commit** — immutable, and therefore unverifiable by any reader of *this* repository
(RB-P50).

##### Corrections to figures this job was handed

Filed first in the plan rather than buried, because a job that hides its disagreements with
its own brief has committed the defect the brief warned about.

| handed | measured on this branch |
|---|---|
| the register carries RB-P47..RB-P53 at this base | **RB-P53 does not exist at `5845698`** — it is 33 unmerged lines on J7's branch, and the closure's Amendment 1 is another 46 |
| the uncovered CI surface grew to 14 | **12** at this base; 14 is J7's branch, and the two extra programs are J7's |
| 27,722 ratios searched | **21,912** evaluated; 27,722 is the ordered-pair count before zero denominators are skipped, so "5,544× larger" is **4,382×** |
| 34 / 30 / 42 keys in the three artifacts | **33 / 29 / 44**, and the three blobs are byte-identical across both branches, so it is not a revision difference |
| 30 pins | **28 / 27 / 30** under three definitions, none of them defined anywhere |
| a `pre-push` hook protects one working copy | **no pre-push hook exists**, installed or committed |
| `git -C <path> tag` bypasses the deny rule | **not reproducible as an unconditional statement** — see RB-P58. **CARRIED from the plan, not re-measured here**: invariant 15 forbids retrying the evasion, and refusing to retry is the correct behaviour |
| expect 940 passed, 2 xfailed | correct **at `3f52a86`**, on J7's branch. The plan's §1.6 called it stale and its own Amendment 1 withdrew that: 932 and 940 are both correct, each at its own commit, and the eight-node difference is `test_field_programs.py` parametrising over 12 versus 14 programs. **§1.2 and §1.6 were one finding counted twice.** |

<!-- provenance: value=940 passed, 2 xfailed; commit=3f52a86; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=932 passed, 2 xfailed; commit=5458059; command=.venv/bin/python -m pytest runtime-py/tests -q -->
The last row's two figures, restated with the commit beside each because the row itself
cannot carry a stamp (RB-P60): **940 passed, 2 xfailed** at `3f52a86` and **932 passed, 2
xfailed** at `5458059`, both by `.venv/bin/python -m pytest runtime-py/tests -q`, and both
correct. Neither was re-run by this unit; they are carried from the plan's Amendment 1,
which re-derived the eight-node difference from the parametrisation and not from the suite.

##### What this section measured and what it carried

**Re-measured on this branch, by a command in this section:** the six arm percentages under
both token columns; the four per-arm fidelity spreads and the three pair ratios; the 0.17%
and the 584×; the three prose sites claiming "same shape"; SHAPE N-7 (7,804 rows, 78 files,
1,770 distinct values, 0 exact cap hits, per-call max 2,625, {512: 59, 1024: 4} within 1%);
L-U5-1's subsumption over 6,725,593 strings and its 8-of-35 emittable stop entries; the
33 / 29 / 44 artifact key counts; 312 of 600 null-retention rows and 288 of 600 = 48%
carrying a figure; 20,913.7 s = 5.81 h of committed `wall_clock_s`; the pin census at
28 / 27 / 30 / 35; 12 committed field programs at `5845698` against 14 on
`feat/compaction-in-the-loop`; the 33 and 46 unmerged lines that carry the reserved
register entry; no pre-push hook and `core.hooksPath` unset; `grep -rl eval-data .github/`
empty at exit 1; and both before/after pairs above, from their own programs.

**Carried and labelled as carried:** M-U5-2's 167 quantities and 21,912 ratios, from the
plan at `5458059`; the tag-deny-rule behaviour of RB-P58, which invariant 15 forbids
retrying; and RB-P53's content, which is not at this base.

**One figure did not reproduce and it is load-bearing on nothing.** The plan reports N-7's
per-call median as `439.25`; the same sweep here gives `321.88`, while min `40.0`, max
`2,625.0`, the distinct count `1,770`, the zero exact hits and the near-cap histogram all
reproduce exactly. The median is quoted nowhere in any conclusion, the negative rests on the
maximum, and the discrepancy is filed rather than reconciled.

##### Invariants held by this section

**Nothing merged, nothing tagged, nothing pushed.** No frozen arm re-run, no committed
artifact retro-edited, no hand-edit of `assets/evals/devteam/tasks/*.yaml`, and nothing
touched under `assets/evals/tasks/` or `assets/evals/perturbations/`. The bar gains
**Amendment D** with §0–§11 and Amendments A–C untouched; the arms measurement gains
**Amendment 1** with everything above it byte-for-byte as committed. Every code change lives
in exactly one layer: `client.py` is Layer 3, `agent.py`/`textutil.py` is Layer 1,
`tools/amendguard/` is outside the five product layers and outside both ruff gates.

**CI is confirmed at content level and not at run level.** `grep -rl eval-data .github/`
returns nothing, exit 1, so no field program, no acceptance run and no mutation is exercised
by CI on any branch — RB-P41's CI half is untouched by this job and is stated rather than
implied. *(A small correction to the plan and to J2's closure, both of which say the
workflow has "three run steps": `grep -c 'run:' .github/workflows/ci.yml` returns **4**.
Three of the four are gates — `ruff check .`, `ruff check --config … examples`,
`python -m pytest runtime-py -q` — and the fourth is `pip install -e "runtime-py[dev,mcp]"`.
The claim about `docs/eval-data` is unaffected in either counting.)*

##### Amendment 1 to section P (2026-08-19) — the review of this section's own work, and what it found in the checker

Everything above this line is as committed. Section P shipped a rule, a checker and a
closure; the checker was then reviewed, and **the review found that four of the checker's
own guards did not hold — including the one this section cited as making a widening
mandatory.** Nothing above is edited: the findings are numbered from `RB-P61` and the
dispositions are stated here.

**A note on placement, because this section is the one that made the rule.** The rule's
prose says corrections are *dated amendments appended at the end*. This amendment is
appended at the end of **section P**, not at the end of the document, so a reader who finds
the section finds its correction. Under the checker that reads `classify=insert`, and
**`insert` can never redden** — which is `RB-P67` below, filed rather than used. The
placement is a judgement about readers, audited by hand, and it is not a verdict this
program earned from its own instrument.

###### Closed here, each with a before and an after from the same command

<!-- provenance: value=982 passed, 2 xfailed; commit=7621b7b; command=PYTHONPATH=$PWD/runtime-py/src /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -m pytest runtime-py/tests -q -->
- **`RB-P61` — the coverage guard counted CLASSES and the closed list has ENTRIES, so the
  safety net this section promised did not exist.** `POINTER_CLASSES` holds **six entries
  and four distinct ids**: P3 carries the section form, the bare-backtick form and the path
  form. The guard built `declared = {cid for cid, _pat, _desc in POINTER_CLASSES}`, so one
  path-form fixture case satisfied it for all three, and its docstring's *"the list cannot
  widen silently"* was false. **Measured in both directions against the old guard, then
  again against the new one, same command each time:**

<!-- provenance: value=24 passed and flips=0 on both mutations before / 3 failed, 25 passed and 1 failed, 27 passed after; commit=7621b7b; command=PYTHONPATH=$PWD/runtime-py/src /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -m pytest runtime-py/tests/test_amendguard.py -q -->

      delete the bare-backtick entry     before 24 passed, flips=0   after 3 failed, 25 passed
      add a 7th P3 sub-form, no case     before 24 passed, flips=0   after 1 failed, 27 passed

  and the second failure names the entry rather than merely counting it — *"closed-list
  entries with no fixture case: 4 P3 (file:line pin, GitHub L-form)"*. The `flips=0` in the
  before column is the sweep's own verdict on the same two mutations, so neither the suite
  nor the calibration could see either of them.
  Coverage cannot be read off a verdict line, because
  `classify` says `pointer:P3` for all three sub-forms, so it is measured where the
  information still exists: each calibration case's real committed before/after lines are
  re-masked through the checker's own `pointer_entries_changed`. One masker, two views — a
  second one written in the test would be a transcription and their agreement a tautology
  (RB-P47). The two uncovered sub-forms now have a case and a mutation each.
  **This is the precondition `RB-P59` names, and it now exists.** (Instrument, closed.)
- **`RB-P62` — a gate this repository defines for itself went red and stayed red,
  undeclared, for eight commits.** `ruff check docs/eval-data` — the gate measured at
  **413 rules over 37 prefixes** against **153 over 6** for the package — reported
  `Found 2 errors` from **`2030245`** onward: `EXE001` (shebang present, file not
  executable) and `I001` (unsorted imports), both introduced by this branch's own field
  program. Bisected per commit rather than assumed, ruff 0.16.1: clean at `5845698`,
  `5458059`, `da5f073`, `b533089`, `5f78fe8`, `0da7658` and `68d5692`; two errors at
  `2030245`, `f134cca`, `dc67dc2`, `b82abf5`, `9cc42c4`, `6c317ba`, `bb9e0bb` and
  `a525516`. **Both errors are cosmetic and it is Critical for being UNDECLARED**: a job
  auditing other people's instruments broke one of its own and said nothing. Fixed — the
  mode, because all eight shebang'd programs in that directory are committed `100755` and
  fixing it by mode shifts no line numbers one commit after a pin correction. **Not fixed
  by widening CI**, deliberately: `ruff check .` runs with `working-directory: runtime-py`,
  so the gate is guarded by nothing, which is RB-P41's shape and is stated rather than
  quietly repaired. **Attack:** a gate a repository defines for itself and runs by hand is
  a gate that regresses silently; the disclosure is the deliverable, not the two fixes.
  (Instrument / process, closed.)
- **`RB-P63` — the sweep's SUMMARY line reported an inventory of its own catalogue in the
  grammar of an inventory of the program.** `branches=12 pinned=11` reads as *"this program
  has twelve decision branches and eleven are pinned"*. It is the count of entries in
  `MUTATIONS`. Every decision branch with no entry was **absent from the denominator rather
  than reported UNPINNED**, so the ratio flattered itself by omission — the inverse of
  invariant 6. Renamed to `catalogued-branches=`, with the scope printed above the line and
  `uncatalogued-branches=UNMEASURED` on it. **Deliberately not given a number:** no
  definition of "decision branch" is committed anywhere in this repository, so any total
  would count whatever the author's definition happened to be — the pin census's defect,
  one artifact over. UNMEASURED is a verdict (RB-P51). (Instrument, closed.)
- **`RB-P64` — the `(value, commit, command)` triple was the least-pinned assertion in the
  program that requires it.** `STAMP_REQUIRED_KEYS = ()` and `STAMP_WINDOW = 100000` each
  passed the entire sweep with **flips=0**. Invariant 5 makes that triple the **whole**
  fallback for a cross-artifact co-moving count, so the one thing standing between a bare
  number and a falsifiable one was untested. The code was correct; under this job's own
  standard, correct-and-untested is a separate verdict. `PARTIAL-STAMP` adds a stamp
  carrying `value` and `commit` and no `command`, in its own file so no earlier stamp can
  satisfy it from inside the window, and `MUT-STAMP-KEYS` pins it. **The window branch is
  NOT closed and is not hidden:** no fixture case places a stamp out of range, so
  `MUT-STAMP-WINDOW` is **declared `unpinned`** and kept with its reason and `(none)` for
  its node. Closing it by deleting the mutation is the move RB-P48 forbids. (Instrument,
  closed; one named branch left open and declared.)
- **`RB-P65` — the vacuity detector was itself vacuous: `calibrate` could never report
  `UNPINNED`.** The baseline was built in-process from an unresolved fixture path while
  every mutant ran through `main()`'s `args.repo.resolve()`, and `mkdtemp()` returns
  `/var/folders/…` resolving to `/private/var/folders/…`. The rendered `repo:` line
  therefore differed on **every** comparison, `r.stdout != baseline_text` was
  unconditionally true, and the `UNPINNED` arm was **unreachable** — so a mutation that
  changed the program's behaviour **nowhere** was labelled `FORMATTER-ONLY`, the innocent
  label, destroying the exact distinction RB-P48 leans on. The path is resolved. **Verified
  in both directions rather than by re-running the same arm:** `MUT-STAMP-WINDOW` now
  reports `UNPINNED — nothing changed at all`, and `MUT-NOTE-PROSE` still reports
  `FORMATTER-ONLY — output changed, not one verdict field moved`. The arm is reachable and
  still discriminates. **Attack:** when a harness compares a mutant's output against a
  baseline it computed by a different code path, the two paths must be shown to agree on an
  unmutated input first, or the comparison measures the harness. (Instrument, closed.)
- **`RB-P66` — `prompt_tokens_verdict` returned `MEASURED` for a response with no `usage`
  object at all.** RB-P51 inside the code written to honour RB-P51. `usage.get("prompt_tokens", 0)`
  over `data.get("usage") or {}` produced 0, which compares unequal to any declared window
  and fell to the `else` arm as `MEASURED` — while the module says in its own comment that
  *"MEASURED is the only one that licenses arithmetic"*. Five shapes reach it and all five
  read `MEASURED` before the fix: no `usage` key, `usage: null`, `usage: {}`, a usage object
  omitting `prompt_tokens`, and `prompt_tokens: null`. A fourth state, `UNREPORTED`, is
  tested first, because it is a fact about what arrived and the window question does not
  arise for a number nobody sent. **The null control is on the same field:** a *reported*
  zero still reads `MEASURED`, so the new state separates "said zero" from "said nothing"
  rather than re-flagging a falsy value. In the fold `UNREPORTED` outranks `VOID` — a VOID
  call returned a number the endpoint chose, an UNREPORTED one contributed a zero this
  module invented, so the total is short by an unknown amount rather than merely
  untrustworthy. Measured, not assumed:

<!-- provenance: value=6 failed, 36 passed with the UNREPORTED branch deleted / 42 passed with it; commit=f0fe198; command=PYTHONPATH=$PWD/runtime-py/src /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -m pytest runtime-py/tests/test_client.py -q -->

      UNREPORTED branch deleted    6 failed, 36 passed
      UNREPORTED branch present    42 passed

  **Section P's S4 bullet above says the verdict is in {`MEASURED`, `VOID`, `UNCHECKED`};
  it is now a set of four**, and that sentence is corrected here rather than rewritten
  there. (Layer 3, closed.)

###### Recorded and not fixed — five, each with the reason it is a record and not a repair

- **`RB-P67` — `insert` can never redden, so the enforced rule is narrower than the stated
  one.** The prose says corrections are *appended at the end*; the checker reaches
  `RECORD-EDITED` through `replace` and `delete` but never through `insert`, and **4 of 8
  field rows are `insert`**. A contradiction placed mid-record therefore reads `OK`. **This
  is a stated-rule / enforced-rule gap and NOT a hole in the central protection** — the
  thing the rule exists to stop, a committed number rewritten in place, still reddens. Not
  fixed because the fix is a policy decision about where amendments may live, and this
  amendment is itself an `insert` (see the placement note above): the author would be
  choosing the rule that judges him in the same commit. (Instrument, open.)
- **`RB-P68` — no gate figure is recorded at this branch's HEAD.** The last stamped one is
  at `f134cca`, and it reproduces to the character. Recorded rather than fixed by
  back-filling: a stamp asserts a value at a commit, and manufacturing stamps for commits
  nobody ran the gate at would be the falsifiability theatre the stamp exists to prevent.
  The figures for **this** amendment's HEAD are stamped below. (Instrument.)
- **`RB-P69` — a `calibrate` FLIP line can print `expected X measured X`.** The decision
  compares four fields — `classify`, `isolation`, `derivation`, `verdict` — and the printed
  line shows one. A row can therefore flip on `isolation` and print two identical verdicts
  beside the word FLIP. The `flips` list carries the full `want`/`got` JSON, so no
  information is lost and no decision is wrong; the human-readable line is misleading on its
  own. Not fixed here because it is a formatter, and under N-12 this program does not change
  a formatter in the same breath as a classifier. (Instrument, cosmetic.)
- **`RB-P70` — the gate cannot be run in a worktree by the command every document in this
  repository states.** There is **no `.venv` in a linked worktree**, so
  `.venv/bin/python -m pytest runtime-py/tests -q` does not resolve at all, and with the
  main checkout's interpreter but without the `PYTHONPATH` prefix, collection dies before
  any test runs — measured at this HEAD: `ERROR runtime-py/tests/test_agent.py`,
  `Interrupted: 1 error during collection`, **1 error in 0.38s**. This is RB-P55 one step
  further on: RB-P55 found the suite testing this tree's tests against another tree's
  package, and the remaining divergence is now **three `src/` files** — `agent.py`,
  `client.py`, `textutil.py`. **The rule that follows, and it is the operational one:** the
  command includes both the `PYTHONPATH` prefix **and** the interpreter's absolute path, or
  the figure is void. (Process.)
- **One review finding is unnumbered and that is disclosed rather than papered over.** The
  review filed a second Low finding whose content **did not travel into the unit brief that
  closed these**. Assigning it a number from a label alone would put an empty entry in this
  register, so none is assigned. **It must be recovered from the review before this branch
  merges**, and this sentence is the reason anyone will remember to.

###### The three RECORD-AND-DROPs, re-verified — two premises were wrong and no disposition moves

All three were re-examined as **measurements rather than conveniences**, and two of them
turned out to rest on a sentence that is false. **The dispositions do not change; the
premises are corrected.**

- **`L-U5-1`.** The reason given above is *"not fixed because there is no action available
  that is not a violation"*. **That is false.** A guard asserting the two lists' inertness —
  that `L(screaming) ⊆ L(snake)`, and that 27 of 35 stop entries can never be emitted —
  edits no data and violates nothing, and **`F-5` already carries exactly that property**.
  The accurate reason is the second half of the original sentence, which stands on its own:
  the defect points *against* tuning, a list selected to move a number would fire, and this
  one is inert by construction. **Dropped, on the correct premise.**
- **`L-U5-4`.** The reason given above is that the fence *"permits numbers only"*. **That is
  false, and re-counted here rather than carried:** string-valued columns are committed in
  all three artifacts — **9** in the arms artifact (`arm`, `compaction_mode`, `mcp_commit`,
  `model`, `recall_mode`, `schedule_id`, `stratum`, `summarizer_model`, `transcript_id`),
  **4** in the null control and **2** in the corpus, **11 distinct** across the three. The
  accurate premise is that the fence **permits no free text**, and that is measurable rather
  than rhetorical: every one of those columns is bounded and identifier-shaped — the longest
  string value anywhere in the three is **24 characters** (`replay-of-recorded-calls`), and
  every column but `transcript_id` has at most **4** distinct values. Which is exactly what
  makes the installed block inadmissible. The conclusion is unchanged and stronger for being
  stated correctly. **Dropped, on the corrected premise.**
- **`L-U5-2`.** No correction. And one thing should be said plainly, because the figure
  invites the opposite reading: **the 5.81 h is the opposite of self-serving.** A job hiding
  work declines re-runs that could make its numbers look *worse*. This one declines a re-run
  that could only move the figure **in the direction that makes its own verdict better** —
  every correction to substring containment moves retention *down*, and the arm is already
  0.9437 away from its bar. Refusing it costs this job the one result it might have wanted.
  **Dropped, and the reason is arithmetic, not economy.**

###### The pin correction this job shipped does not comply with the convention this job ratified

Disclosed at the time and repeated here so it cannot be lost. `L-U5-3` ratified *pattern-delimited
locators only; **never a bare line number***. The correction shipped at `a525516` is
`…-field-measurement.py:1608` — **a bare line number**. The reason is `RB-P59`: of the four
candidate forms measured, the two that read as a pointer correction are both bare pins, and
**the form the convention mandates is the one form the checker forbids**. So the job's first
pass through its own new rule does not comply with it, **because its own checker forbids the
compliant form**. Not hidden, not excused, and not fixed here — `RB-P59` stays **OPEN**, and
`RB-P61` above is the safety net it named as the precondition for anyone acting on it.

###### The instrument, counted as a number

<!-- provenance: value=989 passed, 2 xfailed; commit=8544768; command=PYTHONPATH=$PWD/runtime-py/src /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=expectations=22 flips=0 catalogued-branches=16 pinned=14 unpinned=2; commit=8544768; command=/Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python tools/amendguard/amendguard.py calibrate -->
**Said as a count and not as an absence of red, because "no red" is what a vacuous check
also reports.** At `8544768` the checker's own sweep reports **22 expectations, 0 flips, 16
catalogued branches, 14 pinned and 2 not pinned** — one `FORMATTER-ONLY` (`note-prose`, kept
as N-12's demonstration) and one `UNPINNED` (`stamp-window`, declared, with its reason and no
node). **14 of 16, and the denominator is the catalogue, not the program**; the branches
outside it are `UNMEASURED` by `RB-P63` and no share is claimed over them. The suite is
**989 passed, 2 xfailed**, up from 978 at `a525516` — four nodes for `RB-P61`/`RB-P64`, six
for `RB-P66`, one for the declared-unpinned arm. Both ruff gates are clean, including the
one that had been red for eight commits.

###### What this amendment measured and what it carried

**Re-measured here, by a command in this amendment:** both `RB-P61` mutations in both
directions, before and after; the eight-commit red span of `ruff check docs/eval-data`, per
commit, including the two commits the review's "nine" had swept in; the `UNPINNED` and
`FORMATTER-ONLY` arms after the path fix; all five `UNREPORTED` shapes and the reported-zero
null control; the suite and both ruff gates at `8544768`; the worktree gate failing without
its prefix; the three diverging `src/` files; that line 1608 of the arms program still reads
the `borrow_floor` guard; that no `file:line` pin anywhere in `docs/` points into the file
whose imports were rewrapped; that `tools/amendguard/` still parses under `python3` 3.9.6
with no f-strings (invariant 14); and `L-U5-4`'s string columns — 9 / 4 / 2, 11 distinct,
longest value 24 characters — which also re-confirms the **33 / 29 / 44** key counts.

**Carried and labelled as carried:** `L-U5-1`'s subsumption result and its 8-of-35
emittable stop entries, which are not re-derived here — only the *reason for dropping it*
is corrected; `RB-P68`'s reproduction of the `f134cca` figure; and the content of the
unnumbered second Low finding, which is carried as **absent**.

**Two review figures did not reproduce, and both are corrections in this job's own
favour-free direction.** The red span of the `docs/eval-data` gate is **eight** commits, not
nine — `0da7658` and `68d5692` fall between the last clean bisect point and `2030245` and
are themselves clean. And `L-U5-4`'s nine string columns are **nine in the arms artifact**,
not nine across the three; across the three there are eleven distinct. Neither is
load-bearing on anything but the sentence that states it, and both are stated.

###### Invariants held by this amendment

**Nothing merged, nothing tagged, nothing pushed.** No frozen arm re-run, no committed
artifact retro-edited, nothing touched under `assets/evals/tasks/` or
`assets/evals/perturbations/`, and `9cc42c4` and `6c317ba` are not rewritten — **four RED of
eight field rows is intended and stays**. `POINTER_CLASSES` is **not widened**: `RB-P61`
lands the guard first and demonstrates it reddening a widening, which is the precondition
`RB-P59` set for a later unit and not permission for this one. The tag deny rule was not
retried, no tag guard is shipped, and the residual of `RB-P58` stands unsoftened. Every code
change lives in exactly one layer: `client.py` is Layer 3, `tools/amendguard/` is outside
the five product layers and both ruff gates, and the `docs/eval-data` fix is a mode and an
import wrap in a document tree.

##### Amendment 2 to section P (2026-08-19) — the finding Amendment 1 could not number

Amendment 1 records that one review finding was left **unnumbered** because its content
never reached the unit that closed the others, and that an empty register entry is worse
than a disclosed gap. The content has since been supplied. **This amendment closes the gap
by appending, and does not rewrite the sentence that disclosed it** — the rule this section
exists to enforce, applied to the section's own erratum. The bullet above stands as written
and is superseded here.

- **`RB-P71` — a caveat inferred from one's own tooling failure, asserted about the
  measurement the tooling was pointed at.** A parenthetical shipped into two briefs as a
  fact: *"a naive string replace of the second **fails**, because the string is also the
  mutation catalogue's own anchor."* Its origin, disclosed by its author: a `.replace()`
  guarded by `assert s.count(old) == 1`, which raised `AssertionError`. **What failed was
  the guard, not the mutation.** "My assertion fired" was generalised into "a naive replace
  fails" — a claim about a different artifact — and then attached to a suite figure the
  script had never been part of producing. **The two halves are both true and neither
  collapses into the other:**

  **(1) The partitioning is correct and load-bearing, and U2's finding 2 stands entirely.**
  The anchor genuinely appears **twice** — the definition at module level, above the
  catalogue marker, and the catalogue's own `"anchor":` entry below it. Re-measured here at
  `cad32aa`, hand-mutating the source and then running the sweep on the mutated program:

  ```
  naive replace (both sites)          FLIP UNPINNED  MUT-RECORD-DEFAULT  nothing changed at all
  partitioned replace (definition)    FLIP STALE     MUT-RECORD-DEFAULT  anchor appears 0x above the catalogue
  ```

  Without the partition the sweep cannot mutate that branch at all, so the harness needs it.
  **Both arms report `flips=11` and fail loudly; neither yields a misleading pass**, which
  is the property that matters and which the caveat never claimed.

<!-- provenance: value=8 failed, 20 passed under BOTH the naive and the partitioned replace, identical failing node lists; commit=cad32aa; command=PYTHONPATH=$PWD/runtime-py/src /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -m pytest runtime-py/tests/test_amendguard.py -q -->

  **(2) The caveat was false as a caveat on the pytest figure, which is robust to the naive
  replace.** Measured at `cad32aa`, both ways, and compared node by node rather than by
  count:

  ```
  naive replace (both sites)          8 failed, 20 passed
  partitioned replace (definition)    8 failed, 20 passed
  failing node lists                  IDENTICAL — diff empty
  ```

<!-- provenance: value=6 failed, 18 passed over 24 nodes at a525516, carried from the review and not re-run; commit=a525516; command=PYTHONPATH=$PWD/runtime-py/src /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -m pytest runtime-py/tests/test_amendguard.py -q -->

  and the named node `test_an_unlisted_construct_falls_through_to_record` is in both lists.
  The review measured the same equality at `a525516` as **6 failed, 18 passed** over 24
  nodes; the figures differ here only because this branch added four nodes, and the
  **equality** — which is the whole claim — reproduces at both commits. The pytest half of
  the caveat was never true.

  **THE CLASS, WHICH IS WHY THIS IS A NUMBERED FINDING AND NOT AN ERRATUM.** A failure was
  observed in one artifact — the author's own throwaway script — and reported as a property
  of a different one, the suite that script was pointed at. The guard firing was a fact
  about the script's `count() == 1` precondition; the 6-RED figure was a fact about the
  suite; the first was shipped as evidence about the second. **This is the same shape as the
  three other corrections this job made against the figures it was handed**: a claim
  asserted from something adjacent to the thing it is about, rather than read at the place
  it is about. It is invariant 11's rule — *do not write a pin from a register, read it at
  HEAD* — generalised past pins to any claim at all. **Attack:** before shipping a caveat
  about a measurement, name the artifact the failure was a property of. If the evidence is
  *"my tool errored"*, the claim is about the tool, and the measurement has not been touched
  yet. (Process.)

  **One incidental confirmation, on a case neither finding was designed for.** The review
  measured the naive arm at `a525516` as `FORMATTER-ONLY`; it reports `UNPINNED` here. The
  behaviour did not change — `RB-P65` did. Before the baseline path was resolved the
  `UNPINNED` arm was unreachable and this exact input took the innocent label; it now takes
  the accurate one. `RB-P65` was found and fixed independently of `RB-P71`, and this is an
  unplanned second demonstration that the fix does what it claims.

#### Q (2026-08-19) — J7's findings enter the register, after the merge that made both branches one tree

J7's closure **deliberately minted no RB-P number** (`docs/eval-data/2026-08-19-loop-closure.md`
§8.1 and §12.3): `feat/instrument-hygiene` and `feat/compaction-in-the-loop` were both live,
the register had two writers and no allocation rule, and a number asserted on one branch
would have collided on the other. That deferral is discharged here. Both branches now share
a tree — `58df1be` merges `main` at `d855d96` into J7's branch — so the register can be read
once, at HEAD, and the numbers minted against that reading.

**The ceiling, read at HEAD before a number was written, with a digit-unbounded pattern.**

<!-- provenance: value=71 distinct RB-P entries, ceiling RB-P71, and 6 distinct under the digit-bounded pattern; commit=58df1be; command=grep -oE 'RB-P[0-9]+' docs/eval.md | sed 's/RB-P//' | sort -n | uniq | tail -1 -->

    grep -oE 'RB-P[0-9]+' docs/eval.md | sort -u | wc -l      ->  71 distinct
    ... | sed 's/RB-P//' | sort -n | tail -1                  ->  ceiling RB-P71
    grep -o  'RB-P5[4-9]' docs/eval.md | sort -u | wc -l      ->   6 distinct   (see RB-P74)

`(71 distinct / ceiling RB-P71 / 6 under the bounded pattern, 58df1be, the three commands above)`.
**RB-P72 is the next free number, and this section mints RB-P72 … RB-P75.**

**J3's declared renumber contingency did not trigger, verified rather than assumed.** Section
P's *Numbering* note reserved `RB-P53` and said that if `feat/compaction-in-the-loop` had
*"also allocated `RB-P54` or above by the time it merges, J3's are the later entries and J3's
renumber."* Measured on that branch's last pre-merge commit: `git show 0ce4aae:docs/eval.md |
grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1` → **`53`**, and **0 distinct at or
above 54**. No entry of section P renumbers.

##### Minted here — four, drawn from J7's internal `N-1 … N-27`

The authoritative index of those 27 is the closure's **§12.6**. Four earn a register entry;
the rest are cross-referenced or dropped below, each with its reason.

- **`RB-P72` — the oracle's own configuration file is inside the agent's write surface, and
  a single WRITE through the harness's own committed tool roster produces a PASS with every
  declared guard reporting clean.** J7's `N-21`, and the single most important thing J7
  leaves behind. Bar §1.4 is titled *"the two guards against a gamed oracle."* Measured at
  workload commit `81ac1a1` with **all five DEFECT-SET-5 defects applied** and **not one test
  file edited**, three configs written as `packages/shared/vitest.config.ts`:

<!-- provenance: value=ORACLE exit=1 / exit=1 / exit=0 with 5 passed (5) and 108 passed (108), GUARD-TAMPER empty, GUARD-SCOPE config visible False, GUARD-T 0, classify_outcome PASS; commit=8b6f365; command=.venv/bin/python docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py --worktree <throwaway> section N21 -->

      include: []                            ORACLE exit=1  No test files found        -> FAIL
      exclude the 5 failing test files       ORACLE exit=1  2 failed | 143 passed (145) -> FAIL
      root pinned, include src/**,           ORACLE exit=0  5 passed (5) | 108 passed (108)
        exclude the four defect trees        GUARD-TAMPER empty | GUARD-SCOPE 5 files,
                                             config visible: False | GUARD-T 0  -> PASS

  **The two FAILing configs are recorded beside the headline and not dropped, because the
  hole is real and it is not trivially wide.** A naive `include: []` **fails closed** — the
  oracle refuses a run with no test files — and an `exclude`-only config re-roots onto the
  whole monorepo at 145 test files and still fails. Only the third, which pins `root` *and*
  narrows `include` *and* excludes the defect trees, lands the false PASS.

  **Why GUARD-SCOPE is structurally blind, re-derived at this HEAD rather than carried.**
  `guard_scope` is `git diff --name-only <commit>` and `guard_tamper` is the same over
  `packages/shared/**/*.test.ts` — both over **tracked** paths. Measured directly against the
  workload, read-only:

      git -C <packnplan> ls-tree -r --name-only 81ac1a1 -- packages/shared | grep -i vitest
          -> no match (rc=1)
      git -C <packnplan> ls-tree -r --name-only 81ac1a1 | grep -i vitest.config
          -> apps/web/vitest.config.mts        (the only tracked vitest config in the tree)

  `(no tracked packages/shared/vitest.config.* at 81ac1a1, 58df1be, the two ls-tree commands
  above)`. There is nothing to diff **against**, so the WRITE *creates* a file and `git diff`
  cannot see it. The guard is not weak here; it is looking at a set the file is not in.

  **The mechanism of the false PASS is that the oracle ran fewer tests, and nothing counts
  tests.** The closure's own pristine and defected baselines, at the same commit, put a number
  on it:

<!-- provenance: value=pristine 10 passed (10) files and 141 passed (141) tests; defected 5 failed | 5 passed (10) files and 7 failed | 134 passed (141) tests; commit=8b6f365; command=.venv/bin/python docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py --worktree <throwaway> -->

      pristine   ORACLE exit=0   10 passed (10) files | 141 passed (141) tests
      defected   ORACLE exit=1   5 failed | 5 passed (10) | 7 failed | 134 passed (141)
      gamed      ORACLE exit=0   5 passed (5) files     | 108 passed (108) tests

  141 → 108 is **33 tests and five files that stopped existing**, and the PASS is bought
  entirely with that subtraction. No declared guard reads a test count, so the subtraction is
  invisible to all three.

  **DELIBERATELY NOT FIXED, and that is the correct disposition.** The committed rows exist;
  a guard added after them is a post-hoc gate (bar A2.8 item 2), and it would let this job
  claim a protection its own evidence never ran under. **No committed verdict moves** —
  `files_touched_outside_defect_set` on both committed arms contains only `*.test.ts` paths,
  so no committed row went near a config file. **Attack, for the next bar and not for this
  one:** the oracle was pre-registered as *packnplan's own tooling, never a judgement*, and a
  tool whose configuration is inside the write surface is a judgement the agent can edit.
  Either put the oracle's configuration outside the surface — resolve it from a path the
  roster cannot write — or give the oracle contract a **test-count floor** measured against
  the pristine baseline, which is the one signal all three guards currently ignore.
  (Measurement / bar design, **open, escalation-class**.)

- **`RB-P73` — a guard built on `git diff` over tracked paths is blind in three separately
  measured ways, so `guard_tamper_files` is a lower bound and not a count.** J7's `N-19` and
  `N-20`. Distinct from `RB-P72`: that entry is about *what is inside the write surface*, this
  one is about *what the matcher cannot see even within its declared scope*. Re-derived here in
  a throwaway repo rather than carried, because two of the three are claims about git's own
  pathspec semantics and a claim about a tool is checkable without the workload:

      $ git diff --name-only BASE -- 'packages/shared/**/*.test.ts'
          packages/shared/src/zz/rogue.test.ts          <- depth 2 only
      $ git diff --name-only BASE -- 'packages/shared/*.test.ts'
          packages/shared/a.test.ts
          packages/shared/src/zz/rogue.test.ts          <- BOTH; `*` crosses `/`
      $ git diff --name-only BASE          # after CREATING packages/shared/created.test.ts
          (empty)                                       <- creation is invisible
      $ git ls-files --others -- 'packages/shared/**/*.test.ts'
          (empty)                                       <- and `**` misses it here too
      $ git ls-files --others -- 'packages/shared/*.test.ts'
          packages/shared/created.test.ts

  `(3 blindnesses reproduced — `**` blind at depth 0, creation invisible to git diff, and the
  plain `*` glob strictly wider — git version 2.50.1, 58df1be, the five commands above in a
  fresh git init under the scratchpad)`. A **byte-identical rewrite** of a tracked test file
  is the third shape and leaves the diff empty by construction. **This cannot move A2.3**:
  R2's death needs only *non-empty*, and non-empty is measured 6 of 6 on the committed rows.
  **Attack:** a tamper guard needs `packages/shared/*.test.ts` **plus** an untracked-file
  check via `git ls-files --others`, and it should be described as *"at least this many"*
  wherever its output is reported as a count. The surprise worth keeping is that
  `packages/shared/**/*.test.ts` is **narrower** than `packages/shared/*.test.ts`, which is
  the opposite of what the `**` spelling suggests to a reader. (Measurement, open.)

- **`RB-P74` — a register's ceiling read with a digit-bounded regex is a property of the
  command, not a reading of the register.** J7's `N-25`, and it is filed here rather than left
  in the closure because it is a defect in how **this repository** measures **its own**
  register, not a J7-local quirk. Closure §8.1 measured the taken range with
  `grep -o 'RB-P5[4-9]'` and reported *"RB-P54 through RB-P59"*. That pattern cannot match a
  two-digit tail past 59 however many exist. Re-derived at this HEAD:

      bounded    grep -o  'RB-P5[4-9]'   ->  6 distinct   RB-P54 … RB-P59
      unbounded  grep -oE 'RB-P[0-9]+'   -> 18 distinct >= 54:  RB-P54 … RB-P71
      missed by the bounded pattern: RB-P60 RB-P61 RB-P62 RB-P63 RB-P64 RB-P65
                                     RB-P66 RB-P67 RB-P68 RB-P69 RB-P70 RB-P71

  `(6 vs 18 distinct >= 54, twelve missed, 58df1be, the two grep commands above)`. **The
  closure's own figure reproduces exactly at the commit it was read at** — `git show
  cad32aa:docs/eval.md` gives `RB-P54 … RB-P70`, 17 distinct — so §12.3 was right at `cad32aa`
  and the count of missed entries has since grown from eleven to **twelve**. That growth is
  the finding's teeth: **the error the instrument makes gets larger every time the register
  does, silently, and in the direction of collision.** An orchestrator taking *"the next one
  after the closure's ceiling"* would have minted **RB-P60**, already taken, and collided a
  third time in one night. **The shape is the three recall-errors of that night inverted:**
  not a number asserted from memory, but a number read with an instrument that could not see
  the answer — which is why *"read it at HEAD"* is not sufficient on its own. **Attack:** read
  an allocated range only with a digit-unbounded pattern, print the distinct count beside the
  maximum so a truncated read is visible as a short count, and treat any ceiling as valid only
  at the SHA it was read at. (Process / instrument, closed here by use; the defective command
  is not committed anywhere and needs no repair.)

- **`RB-P75` — an allocation register with two live writers and no allocation rule collides
  silently, because identical writes on two branches merge clean.** J7's `N-27`, generalised
  past the one instance. **Two such registers are now known in this repository** — the RB-P
  number space (§8.1, and `RB-P74` above) and `runtime-py/pyproject.toml`'s `version` — and
  they differ in how loudly they fail. A duplicated RB-P *number* eventually shows up as two
  entries with one name. A duplicated *version* does not show up at all: two unmerged branches
  both writing `0.24.0` produce no textual conflict, and the merge yields **one released
  version covering two jobs**, which no gate in this repository would have flagged.

  **The hazard was not hypothetical and the merge settled it.** Measured at this HEAD:

      git show main:runtime-py/pyproject.toml | grep '^version'   ->  version = "0.24.0"
      grep '^version' runtime-py/pyproject.toml                    ->  version = "0.25.0"
      git log --oneline --all -S'0.24.0' -- runtime-py/pyproject.toml
          d855d96  Instrument hygiene … (v0.24.0) (#34)
          cad32aa  chore(runtime-py): 0.23.0 -> 0.24.0, a MINOR justified by measurement

  `(0.24.0 on main at d855d96, 0.25.0 here, 58df1be, the three commands above)`. J7 skipped
  `0.24.0` on the strength of a read of the other branch **before** it merged; `main` then
  took `0.24.0` exactly as predicted. Had J7 taken the next free number it saw, the collision
  would have landed as a single silent `0.24.0`. **Skipping costs a visible gap if the other
  branch is abandoned; colliding costs a silent one. Visible beats silent, and this is the
  measured case that says so.** **Attack:** a shared allocation register needs either one
  writer or a rule stated where the register lives — for the RB-P space, section P's
  *Numbering* note is that rule and it worked; `pyproject.toml` has no equivalent and should
  carry one. Not the same finding as the `payload_sha256` two-writer entry in section L, which
  is about two producers disagreeing on the **unit of a record**; this is about two producers
  claiming the **same slot**. (Process, open — mitigated once, unruled.)

##### Cross-referenced rather than duplicated — four, each already this register's business

- **`N-1`** — *"the bar's honest counter is honest only below the window"* — is **`RB-P53`'s
  class**, one layer up: a token counter that reports the window instead of the prompt, with
  no error. `RB-P53` already carries the mechanism, the 216-row distributional tell and the
  two in-repository sites closed in code. Filing it again would split one class across two
  numbers. **`N-2`** (`ollama create` FROM the raw blob path yields a completion-only model)
  attaches to the same entry as a second `ollama` surface and is recorded there by reference.
- **`N-14`** (a check that stayed green when the line it claimed to cover was reverted) and
  **`N-26`** (**39 of 48** selfcheck cases unpinned by any committed source mutation) are both
  **`RB-P48`** — *count vacuity from the OUTPUT, not from the source*. `N-26` is that rule
  being **obeyed**, not violated: the census is computed from the selfcheck's printed output
  and the 39 are named individually rather than summarised. It is a disclosed gap in J7's
  instrument, which is exactly what `RB-P48` asks for, and a new number would reward
  compliance with a finding.
- **`N-15`** (the committed `.jsonl` was produced by an earlier revision of the committed
  `.py`, and is **not repairable** — repairing means regenerating committed evidence) is
  **`RB-P49`'s** class realised. `RB-P49` names the mechanism by which a committed artifact
  and its producer drift; `N-15` is the drift, already landed and now permanent. Recorded
  against `RB-P49` rather than numbered again.

Verified at HEAD rather than asserted: `RB-P48`, `RB-P49` and `RB-P53` are all present in this
file — `for n in 48 49 53; do grep -c "RB-P$n" docs/eval.md; done` → **4 / 2 / 6**
mentions respectively, all three with a definition bullet in section O.

##### Not filed, and why — the remaining twenty

Filing all 27 would make the register longer and no more useful, so the reasons are given
once, by group, rather than as twenty empty entries.

- **Closed inside J7's own harness and instrument-local:** `N-3` (`git clean -fd` deletes the
  workload's `node_modules` symlinks), `N-11` (`stopped_by = "run-cap"` for every endpoint
  exception), `N-12`, `N-13`, `N-16` (`restore()` carried gitignored state between repeats),
  `N-17` (`boundaries` over-counted by exactly one), `N-18` (`--arm` was free text and
  `compaction_mode` came from the label). Each has a before and an after from the same command
  in the closure, each is fixed in a program under `docs/eval-data/`, and none constrains a
  future job that does not use that program. `N-16` and `N-18` are the two closest calls in
  this group — an isolation routine that did not isolate, and a run that could report a
  mechanism it never called — and both are pinned by committed selfcheck cases, which is where
  a closed instrument defect belongs.
- **Findings about the J7 bar's own text, which is frozen and not this register's subject:**
  `N-5` (superseded three times over, most recently at this commit), `N-6`, `N-7`, `N-7a`,
  `N-8`, `N-9`, `N-10`, `N-19`'s CANON-1 half, `N-22`, `N-23`, `N-24`. These are corrections
  to a pre-registration document. They are indexed at closure §12.6, they bind the *next* bar
  through closure §9's five conditions, and the closure is explicit that answering them is a
  **new job with a new bar**, not an amendment to this one.
- **`N-4`** (`git worktree list` can never be shown empty; the baseline is 25) is a fact about
  this machine, not about the repository, and it belongs in the fence discipline where it is
  already used.

##### Two figures this section was handed that do NOT reproduce at HEAD

Both are reported rather than quietly adjusted, because a figure that moved is evidence about
when it was read.

1. **Closure §12.3 says N-25's range *"reaches RB-P70"*; at this HEAD it reaches RB-P71.** Not
   an error: `git show cad32aa:docs/eval.md` still gives `RB-P54 … RB-P70`, so the figure is
   correct at the commit it was stamped with. `RB-P71` was minted after `cad32aa`, by section
   P's Amendment 2, and reached this tree through `d855d96`. The closure said in the same
   breath that *"the ceiling is a snapshot, not a pin"*, and this is that sentence coming true
   in under a day.
2. **Closure §12.4 says `git diff --numstat main..HEAD -- runtime-py` is empty — 0 inserted and
   0 deleted. At `58df1be` it is `1 1 runtime-py/pyproject.toml`.** The claim it supported —
   that the shipped package is byte-identical and the MINOR is a job marker, not a surface
   change — **survives intact**, and is now measured on the narrower path that actually carries
   the surface: `git diff --numstat main..HEAD -- runtime-py/src` is **empty**. The one moved
   line is the version register of `RB-P75` itself, `0.24.0` → `0.25.0`. The lesson is the
   entry's own: a `-- runtime-py` probe was reading a directory that contains both the surface
   and a shared register, and only one of them was the subject.

##### Gates at this commit

<!-- provenance: value=1005 passed, 2 xfailed; commit=58df1be; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=All checks passed! on runtime-py and on docs/eval-data; commit=58df1be; command=.venv/bin/ruff check runtime-py && .venv/bin/ruff check docs/eval-data -->

| gate | value | commit | command |
|---|---|---|---|
| suite | **1005 passed, 2 xfailed** | `58df1be` | `.venv/bin/python -m pytest runtime-py/tests -q` |
| ruff, `runtime-py` | **All checks passed!** | `58df1be` | `.venv/bin/ruff check runtime-py` |
| ruff, `docs/eval-data` | **All checks passed!** | `58df1be` | `.venv/bin/ruff check docs/eval-data` |

<!-- provenance: value=expectations=22 flips=0 catalogued-branches=16 pinned=14 unpinned=2 uncatalogued-branches=UNMEASURED; commit=58df1be; command=.venv/bin/python tools/amendguard/amendguard.py calibrate -->
<!-- provenance: value=48 cases, 20 labelled RED:, exit 0; commit=58df1be; command=.venv/bin/python docs/eval-data/2026-08-18-loop-harness.py selfcheck -->

| gate | value | commit | command |
|---|---|---|---|
| amendguard calibrate | `expectations=22 flips=0 catalogued-branches=16 pinned=14 unpinned=2 uncatalogued-branches=UNMEASURED` | `58df1be` | `.venv/bin/python tools/amendguard/amendguard.py calibrate` |
| harness selfcheck | **48 cases, 20 labelled `RED:`, exit 0** | `58df1be` | `.venv/bin/python docs/eval-data/2026-08-18-loop-harness.py selfcheck` |

The selfcheck is reported as `48 / 20` and not as *"0 RED"*, which is the form bar §9 forbids
and which `N-26` exists to correct; the two numbers reproduce the census of closure §12.2
exactly.

**This section will classify as `insert`, not `append`, and that is `RB-P67` and not a
surprise.** It lands before the `qwen-implementer` section rather than at end-of-file, so it
sits inside section P's parent and beside the lettered job sections it belongs with. `RB-P67`
records that `insert` can never redden; the placement is disclosed here rather than relied on
quietly, and no existing entry is edited to make room for it.

##### Fences held by this section

**Nothing merged, nothing tagged, nothing pushed.** `git for-each-ref refs/tags` → **22 tags**,
newest **`v0.21.0`** by version sort; `v0.22.0`–`v0.25.0` remain deliberately untagged and no
form of `git tag` was run. **No arm was re-run and neither `.jsonl` was touched**; every N-21
and pristine/defected figure above is **carried from the closure's committed measurement at
`8b6f365`** and marked as such, while the structural precondition under it — no tracked
`vitest.config.*` at `81ac1a1` — was **re-derived read-only at this HEAD**. No field program
under `docs/eval-data/` was run with no arguments (`RB-P49`); the only one run took the
explicit `selfcheck` sub-command. The workload was re-checked rather than assumed:
`git -C <packnplan> rev-parse HEAD` → **`81ac1a1`, unmoved**, and `status --porcelain` → the
same single line, `?? docs/test-cases/REVIEW-multi-perspective-2026-07-30.md`. The stale
worktree at `scratchpad/wt-j3` was not touched. **No existing register entry was retro-edited**
— sections L through P and both of section P's amendments stand exactly as `d855d96` and
`58df1be` left them, and this section appends beside them. One layer: `docs/` only.

### The `qwen-implementer` cell on RB-P27 lever (2) (2026-08-12)

The first measured cell of the `qwen-implementer` backlog item, run on the
branch that shipped the RB-P27 fix. **The bar was pre-registered before any arm
ran**, in `docs/eval-data/2026-08-12-rbp27-qwen-cell-prereg.md` (committed at
`08f453f`, after the rig at `38b0f5a` and the executable spec at `f5e38b0`, and
before the arms at `c6ddf44`); see the dated **amendment** appended to that file
2026-08-13 for three things the review found wrong with it. The raw record is
`docs/eval-data/2026-08-12-rbp27-attempts.jsonl` plus 20 per-attempt files, all
runner-emitted and none hand-edited.

**The bar, in one line.** An attempt passes iff, in order: every
`SEARCH`/`REPLACE` block matches exactly once in
`runtime-py/src/bantamkit/criticreplay.py`; `git status --porcelain -uall` in
the clone is that file and nothing else; the `f8404ab` floor still hashes to
`309c925e…`; `ruff check runtime-py` is clean **and** the RB-P27 spec nodes are
green under `--runxfail`; and all 736 suite nodes are green. Every clause is a
property of the instrument — a diff, a hash, a linter's status, a test runner's
status — and none asserts a fact about the world.

**The arms.** One-shot, independent attempts: fresh process, fresh clone, frozen
prompt (sha `a65efda6…`, asserted on every run), a seed of its own, and **no
feedback of any kind carried between attempts**.

| arm | model | R | passes | Wilson 95 % | failure classes, never pooled |
|---|---|---|---|---|---|
| cell under test | `qwen2.5:7b-instruct` (`num_ctx` 8192) | 10 | **0** | [0.0 %, 27.8 %] | `ruff-failed` 5, `apply-failed` 3, `spec-red` 2 |
| lower bracket | `qwen3:4b-instruct` (`num_ctx` 8192) | 5 | **0** | [0.0 %, 43.4 %] | `spec-red` 3, `ruff-failed` 2 |
| upper bracket | `qwen2.5:14b-instruct` (`num_ctx` 8192) | 5 | **0** | [0.0 %, 43.4 %] | `apply-failed` 4, `ruff-failed` 1 |

Zero `boundary-violation`, zero `floor-moved`, zero `suite-red`, zero `timeout`
and zero `transport-error` anywhere, so no rate is computed over a shifted
denominator. No arm came near a budget (slowest call 102 s against a 300 s cap;
total recorded attempt wall-clock 269.4 s). Integrity, re-verified from the
artifact: 20 rows, 20 distinct seeds, 20 distinct completions, exactly one
prompt sha, and `prompt_tokens` constant within each arm (3374 / 3377 / 3374),
so nothing was truncated.

**The reading, and it is the only sentence this repo may write about what the
cell means** — licensed by the J3 review, quoted rather than paraphrased:

> On one diff-sized backlog task — one-shot, exception name withheld,
> exact-match SEARCH/REPLACE reply format, `num_ctx` 8192, one machine — three
> local Qwen models produced **0 passes in 20 pre-registered attempts** (7b 0/10,
> Wilson 95 % [0.0 %, 27.8 %]; 4b 0/5 and 14b 0/5, both [0.0 %, 43.4 %]). The
> oracle is not the reason: an independently derived patch passes it at HEAD, it
> rejects the sloppy `except Exception` fix, and hand-repairing all six format
> failures converts none of them into a pass. Not one attempt moved a single
> spec node, and not one reached for the published idiom.

**What that sentence does NOT license, itemised so nobody has to infer it:**

- **Not** "local 7b models cannot do diff-sized backlog work." One task, one
  prompt, one loop shape, n = 10, on one machine — and localisation was done by
  a human before the model was called, while the exception's name was withheld,
  which the pre-registration itself registers as making the cell **harder than
  the field condition**.
- **No ranking of 14b against 4b**, in either direction. Both are n = 5 with
  intervals spanning 0–43.4 %; the failure-class split between them is a
  description of five attempts each, not a difference.
- **No "nearly had it"** for any attempt. Not one attempt moved a single spec
  node: all five `spec-red` attempts report exactly `3 failed, 4 passed, 155
  deselected`, byte-for-byte what the unpatched tree reports.
- **Nothing about the retry cell.** "One-shot pass rate" and "pass rate within k
  oracle-feedback rounds" are different quantities; the retry cell is
  pre-registered as a separate cell and **has not been run**.
- **No claim that a pass would mean the defect is fixed** — not until RB-P28's
  residual is closed. C1 demonstrated a patch that turns the whole spec green
  and fixes nothing.
- **Nothing about the shipped fix.** It was authored by the J4 implementer unit;
  see RB-P27's closure above.

**The rig was put on trial and exonerated, so the standing "if the rig is
broken, fix it and re-run" directive did not fire — there is no rig fix in this
cycle and there is no cell 2.** Stated here explicitly because a directive that
did not fire because its condition was false is worth a sentence, and silence
would look like an omission. What exonerated it: an independently derived patch
reached PASS at HEAD on the first try; `--self-test` fires all eight rejection
rules; the sloppy `except Exception` and `except OSError` fixes are both
rejected, at the spec phase, by
`test_a_non_pipe_failure_around_the_table_print_is_not_downgraded`; both prompt
excerpts occur exactly once byte-for-byte in the cloned file, so the six
`SEARCH occurs 0 times` failures are uniform over-indentation by the models
rather than a stale excerpt; and hand-dedenting all six converts **zero** of
them into a pass (3 `ruff-failed`, 2 `spec-red`, 1 not repairable). What the
review filed instead is RB-P28, RB-P29 and RB-P30 above.

**The format control, and it is flagged as UNREGISTERED.** It is not part of the
pre-registered bar, it was designed after the arms had run, and it may not be
read as a result of this cell. It is recorded because it is the thing that rules
out "the rig is unpassable by format": given a trivially easy edit to the same
file in the same reply format, **14b 5/5, 4b 4/5, 7b 1/5** blocks applied. All
three models can speak the format; the 7b's 1/5 is itself a fact about the
format's cost at that size and is a reason RB-P30 is worth attacking, not a
finding of this cell.

**Two observations recorded descriptively, gating nothing**, being what the
pre-registration's §7 named in advance as the raw material for a harder cell.
Counted over the 20 raw completions in the per-attempt files, not over the
extracted patches: `devnull` 0, `dup2` 0, `SIGPIPE` 0, `EPIPE` 0 — and
`BrokenPipeError` itself 0, so not one completion so much as **named** the
exception. And **no attempt chose `1` as the status for this case** — where the
count behind that sentence is an **exact-string count of `SystemExit(1)` on
`REPLACE` sides**, and the method is stated because the sentence reads stronger
than the method is: three occurrences, all in the 7b (attempts 1, 5, 8), and all
three are copies of the file's pre-existing `raise SystemExit(1) from e` in the
`BantamError` handler, carried through unchanged. So the "recipe recall"
signature the pre-registration worried about is absent in both directions, and
its observable 1 is informative by its absence rather than dead.
**What the exact string does not see, recorded here rather than left for a later
reader to find.** `qwen2.5-7b-instruct` attempt 4 newly authors
`raise SystemExit(int(status or 1)) from e` on its `REPLACE` side — a literal `1`
used as a status, written by the model and not carried through from the `SEARCH`
side. It sits on the `BantamError` **refusal** path, not the closed-pipe path, so
the scoped claim above survives it unchanged; but "no attempt chose `1`" is the
output of a string count and not an exhaustive statement about what the models
wrote, and it has to be read as the former.
**Reconciling `c6ddf44`'s commit body, which describes this same observable in
words that cannot both be true as written.** That commit records "the exit status
named in the patch was the literal `1` in 4 of the 7b's 10 attempts"; this file
says no attempt chose `1`. Both reproduce, under different readings of "named",
and neither is any-occurrence. The `4` is the count of 7b `REPLACE` sides whose
exit call names a literal `1` **including** attempt 4's `int(status or 1)` —
attempts 1, 4, 5, 8. The `3` is the exact-string count of `SystemExit(1)`, which
excludes attempt 4. For the record, any-occurrence is a third number neither
statement is making: `SystemExit(1)` appears somewhere in **7** of the 7b's 10
raw completions, mostly on `SEARCH` sides. All four counts were re-derived from
the committed per-attempt files on 2026-08-13; the commit body is history and
stays as written, so this paragraph is the reconciliation.
Cost of the whole cell: 20 local Ollama calls plus the review's 17, zero hosted
calls, zero dollars.

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

#### R — a result that has been sitting in committed rows since 2026-08-10

**RB-P76 · Above the 3B floor the four tiers are not distinguishable, the 4B does it on the
smallest token bill, and the only family that cuts is `file-nav`. None of this has ever been
reported.**

Found by a prep probe for a job that was then dropped, and **re-derived independently by the
orchestrator from the committed rows** before being written here. Four artifacts,
`docs/eval-data/2026-08-10-rebaseline-{3b,4b,7b,14b}.jsonl`, **528 rows each**, already in the
repository. Nothing was re-run to produce this entry.

<!-- provenance: value="see table" commit="3541e3d" command="python over the four rebaseline jsonl" -->

| tier | pass | tokens, sum | tokens, median | `model_calls`, sum |
|---|---|---|---|---|
| 3b | **0.2557** (135/528) | 573,062 | 575 | 1,475 |
| **4b** | **0.6648** (351/528) | **434,851** | **533** | 1,222 |
| 7b | **0.6307** (333/528) | 766,209 | 622 | 1,481 |
| 14b | **0.6458** (341/528) | 590,505 | 674 | 1,279 |

**Fisher exact, two-sided, computed by the orchestrator over the committed rows:** 4b vs 7b
**p = 0.2734**; 4b vs 14b **p = 0.5601**; 7b vs 14b **p = 0.6540**; 3b vs 7b **p < 0.0001**.
So **the 3B is a floor and the other three are one population at this n** — and the 4B
carries that population's pass rate at **43% fewer tokens than the 7B** (434,851 vs 766,209).

**THE CLAIM IS NOT "THE 4B BEATS THE 7B", AND THE STRONGEST REASON IS ONE THE DATA ITSELF
SUPPLIES.** `run_seed(model, task_name, repeat)` at `evalrun.py:401` **hashes the model name
into the seed**, so no two tiers ever share one. Measured: **66 distinct seeds per tier and
ZERO overlap between any pair.** These four arms are **unpaired** — a between-subjects
comparison of four different sampling draws, not a paired one — and a paired design is a
prerequisite for any tier claim, not an improvement on one. It is falsifiable on its own
terms: make the seed model-independent and the overlap goes **0/66 → 66/66**.

**The one family that cuts, 7b → 4b:**

| family | 7b | 4b | Δ | n |
|---|---|---|---|---|
| **`file-nav`** | 0.917 | 0.500 | **−0.417** | 48 |
| `memory-recall` | 0.264 | 0.375 | +0.111 | 216 |
| `structured-extraction` | 0.925 | 1.000 | +0.075 | 120 |
| `tool-use` | 0.840 | 0.875 | +0.035 | 144 |

**`file-nav` is the whole of the downtiering risk on this task set**, and its ladder
(0.021 → 0.500 → 0.917 → 0.938 across 3b/4b/7b/14b) is the sharpest difficulty signal
anywhere in these artifacts. **It belongs to the finder-primitive axis**, which is about
finding things across files and currently has no pre-registered difficulty signal at all.

**Why this is filed as a finding and not as a result.** The rows have been committed since
2026-08-10. Every number above is a `python` one-liner over them. **No document in this
repository states any of it**, and a job was queued for eight days on a premise
(*"route mechanical work to a small local model"*) that these same rows **invert**: above the
3B floor there is no tier gap to exploit, and the one real gap runs the other way. This is
RB-P34's shape — *printing is not reporting* — one level up: **the rows did not even need
printing, only reading.**

**What is NOT claimed.** Not that the 4B is the right default — the comparison is unpaired.
Not that the tiers are equivalent — *indistinguishable at this n* is a statement about the
n. Not that `file-nav` is unfixable — only that it is the sole measured cut. And no
wall-clock figure appears here: these artifacts carry none, and every timing number in the
probe that produced this came from a live run that is **not** in the committed rows.

##### Amendment 1 to RB-P76 — 2026-08-19, appended within the hour, by the next probe

**RB-P76 above stands as committed and is not edited.** Every figure in it reproduces. What
follows narrows one sentence of it, and the narrowing was found by the J4 prep probe roughly
an hour after RB-P76 merged at `71a72bc`.

<!-- provenance: value="see table" commit="71a72bc" command="python over the four rebaseline jsonl, grouped by config" -->

**RB-P76 calls `file-nav`'s ladder "the sharpest difficulty signal anywhere in these
artifacts". That is true of the family AVERAGE and it conceals its own base.** The 48 rows
per tier are **2 tasks × 3 repeats × 8 configs — six independent draws per config**, and the
4B's `0.500` is an average over eight configs that span **0/6 to 6/6**:

| config | 3b | 4b | 7b | 14b |
|---|---|---|---|---|
| `bare` | 0/6 | **0/6** | 5/6 | 6/6 |
| `structured` | 0/6 | **0/6** | 5/6 | 6/6 |
| `lean` | 0/6 | 2/6 | 5/6 | 6/6 |
| `memory` | 0/6 | 2/6 | 5/6 | 6/6 |
| `full` | 0/6 | 4/6 | 6/6 | 6/6 |
| `critique` | 0/6 | 5/6 | 6/6 | **3/6** |
| `grounded` | 0/6 | 5/6 | 6/6 | 6/6 |
| **`graph`** | **1/6** | **6/6** | **6/6** | **6/6** |

**THE LEDGER IS ALREADY THE BEST CONFIG ON THE FAMILY, AT EVERY TIER.** `graph` — the
`filegraph` component the backlog dismisses as *"a ledger, not a finder"* — is **6/6 at 4b,
7b and 14b**, and the **only** config that passes at all at 3B. So the `−0.417` family delta
is a property of **which configs are averaged**, not of the family, and it **inverts** for
the config a finder would have to beat: at `graph` there is no 7b→4b cut to close.

**Two more things visible only at this grain.** `critique` at 14b is **3/6**, worse than the
4B's 5/6 on the same config — the one place in the artifact where a larger model does
measurably worse. And **10 of the 4B's 24 `file-nav` failures are `malformed-output`**, all
in `bare` and `structured`, against 11 `wrong-answer` and 3 `critique-exhausted`: **a large
share of the measured "navigation" gap at 4B is a failure to emit well-formed output, not a
failure to navigate.**

**What this does and does not move.** RB-P76's overall ladder, its Fisher p-values, its
token bill and its unpaired-arms finding are **untouched** — nothing above depends on the
family grain. What is withdrawn is the implication a reader would draw from *"the sharpest
difficulty signal"*: **there is no headroom at `graph` to attack, the base is six draws per
cell, and 6/6 against 5/6 is indistinguishable at any α.** RB-P76 was written from a family
average; **a family average over eight configs is a pooled number, and this program's own
rule is that strata are reported separately and never pooled.** That rule was applied to
arms and not to configs, and this is what it cost.

##### Amendment 2 to RB-P76 — 2026-08-19, the comparison was matched all along

**RB-P76 above and Amendment 1 both stand as committed and neither is edited.** Their figures
reproduce at `ba7a38b`, the seed facts included. What follows retracts one *inference* drawn
from those facts. It needs no source change and no new run.

<!-- provenance: value="see table" commit="ba7a38b" command="python over the four rebaseline jsonl, keyed by inverting run_seed; McNemar exact hand-rolled from math.comb" -->

**The retracted clause.** RB-P76 says of the four arms: *"a paired design is a prerequisite
for any tier claim, not an improvement on one"*, having established that `run_seed` hashes the
model and that no two tiers share a seed. **Those seed facts are true and re-measured here — 66
distinct seeds per tier, 0 overlap in all six tier pairs. The inference from them is false.**
Pairing is a property of the experimental design, not of the RNG. The design is fully crossed —
every `(task, config, repeat)` cell exists at all four tiers — so the matched-pairs test was
available on the day these rows were committed, and is available now. Hashing the model does not
destroy the pairing key; it relabels it with a bijection invertible in 66 hashes. Given the
model string, `{run_seed(model, task, repeat) -> repeat}` over 22 tasks × 3 repeats **keys 528
of 528 rows at every tier — 0 unrecovered, 0 task mismatches** — and the four model strings
themselves recover from the committed seeds alone (`llama3.2:3b`, `qwen3:4b-instruct`,
`qwen2.5:7b-instruct`, `qwen2.5:14b-instruct`, each the unique hit when a candidate list of
local model names is tested against its file's seed set). **What the model term in the seed
costs is that, in these rows, the repeat index is recoverable rather than recorded: an
ergonomics cost, not a validity one.**

**The paired test, computed.** McNemar exact, two-sided, on `(task, config, repeat)` matched
cells, n = 528 per pair. `scipy` is not in `.venv`, so the exact test is hand-rolled from
`math.comb` and is exact, not asymptotic.

| pair | b | c | **McNemar exact p** | committed Fisher p |
|---|---|---|---|---|
| **4b–7b** | 49 | 31 | **0.0567** | 0.2734 |
| 4b–14b | 41 | 31 | 0.2888 | 0.5601 |
| 7b–14b | 42 | 50 | 0.4657 | 0.6540 |
| 3b–4b | 0 | 216 | <0.0001 | — |
| 3b–7b | 7 | 205 | <0.0001 | <0.0001 |
| 3b–14b | 6 | 212 | <0.0001 | — |

**Both halves, because a correction that reports only the flattering one is the failure this
register keeps catching.** *Unchanged:* the verdict at α = 0.05 — the 3B is a floor and the
other three are one population, exactly what RB-P76 committed. *Moved:* the tightness. 4b–7b
goes **0.2734 → 0.0567, roughly 4.8×, to the edge of significance**, and the direction favours
the 4B — which already carried that population's pass rate on 43% fewer tokens. *"Indistinguishable
at this n"* survives, with less margin than the unpaired figure showed.

**The technique was committed and tested two days before RB-P76 declared it missing.**
`slots_are_repeat_indexed`, at
`docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py:190`, inverts `run_seed` for
exactly this purpose — *"the seed a row carries is a witness to its repeat index"* — and is
guarded by `test_a_repeat_slot_is_verified_against_the_harnesss_own_seed_not_file_order`
(`runtime-py/tests/test_ladder_statistics.py`, assertions at lines 190 and 194 at `ba7a38b`). It
landed in `f0cf440` on 2026-08-17; RB-P76 merged in `71a72bc` on 2026-08-19. **The entry named a
prerequisite missing while the repository was already shipping and testing the thing that
supplies it.** This is RB-P76's own shape once more — *the rows did not even need printing, only
reading* — except that here the instrument did not even need writing.

**J8 is dropped, and the metric it proposed to move runs the wrong way.** The queued change was
to make the seed model-independent, on the falsifiable promise that cross-tier overlap goes
0/66 → 66/66. That overlap is a tautology of the change. The quantity that actually governs
pairing — whether an already-committed row can be resolved to its repeat index — goes **66/66 →
0/66 at every tier**, because `run_seed` is the only witness those rows carry: **65 of the 96
committed `.jsonl` artifacts hold a `seed` and no `model` field** (13 hold both, 18 hold no
seed). The change would also delete the invariant asserted at
`runtime-py/tests/test_evalrun.py:1521`, inside `test_run_seed_varies_with_repeat_and_model`
(line 1519 at `ba7a38b`). Whether tiers should share a seed *anyway*, as common random numbers,
is a separate question and is **not settled here**: the measurement that would settle it did not
reproduce, and an unverified number does not enter this file.

#### S (2026-08-19) — J9: the oracle's config pinned, the hole was 26 filenames, and a quieter false PASS the pin does not touch

`RB-P72` was the register's open, escalation-class entry. This section records what closing it
found. **The headline is not "RB-P72 is closed."** It is two facts that have to be read
together: the config-discovery class is closed at **26 of 26** filenames and the recorded hole
was an order of magnitude too small — **and the same night's evidence shows the config class
was never the boundary**, because a false PASS reaching the byte-identical pristine ORACLE
line, with every declared guard clean and all five defects on disk, is **five WRITEs away and
was equally reachable before the pin**.

The work is `feat/oracle-pin`: `cc9882f` (the pin and the named node `M11`), `b1f41e5` (taking
`main` in by merge), `0b7b0c9` (the committed field-measurement program), and this section.
The adversarial review that found the fifth attack is `.shiftwork/probes/J9-REVIEW-attack-the-pin.md`,
gitignored and therefore cited as a probe, never as evidence: every figure below was
re-measured here.

**The register read at HEAD, before a number was written, with a digit-unbounded pattern
(`RB-P74`).**

<!-- provenance: value=76 distinct RB-P entries, ceiling RB-P76, contiguous 1..76 with no gaps; commit=0b7b0c9; command=grep -oE 'RB-P[0-9]+' docs/eval.md | sort -u | wc -l and | sed 's/RB-P//' | sort -n | tail -1 -->

    grep -oE 'RB-P[0-9]+' docs/eval.md | sort -u | wc -l       ->  76 distinct
    ... | sed 's/RB-P//' | sort -n | tail -1                   ->  ceiling RB-P76
    ... | python: [i for i in range(1, 77) if i not in taken]  ->  []  (no gaps)

`(76 distinct / ceiling RB-P76 / 0 gaps, 0b7b0c9, the three commands above)`. **`RB-P77` is
the next free number, and this section mints `RB-P77` … `RB-P82`.** No number here came from a
brief, a probe or an orchestrator: `RB-P74` exists because a ceiling was once read with an
instrument that could not see the answer, and `RB-P75` exists because a number was minted
without reading the register at all.

##### Amendment 1 to RB-P72 — 2026-08-19, the hole was an order of magnitude larger, and one of the entry's own two fixes is refuted

**RB-P72 above stands exactly as committed and is not edited.** Its numbers, its three-config
table and its disposition — *deliberately not fixed, and that is the correct disposition* —
are J7's and stay J7's. What follows narrows and extends it.

<!-- provenance: value=RB-P72's own recorded figure, 108 passed (108); commit=8b6f365; command=carried from RB-P72 above, not re-run: the pinned oracle cannot reproduce a pre-pin false PASS -->

**1. The hole is 26 filenames, not one.** RB-P72 records `packages/shared/vitest.config.ts`
and `108 passed (108)`. The discovery surface is vitest's own, read at runtime out of the
installed package's constants chunk rather than listed from memory —
`CONFIG_NAMES × CONFIG_EXTENSIONS` (12) plus `WORKSPACES_NAMES × WORKSPACES_EXTENSIONS` (14)
— and `_resolve`, the roster's own path check, admits **26 of 26**. Swept with DEFECT-SET-5
applied and one narrowing config per name:

<!-- provenance: value=BEFORE 26 of 26 reach ORACLE exit 0, AFTER 0 of 26; six pre-registered rows reproduce both sides; commit=0b7b0c9; command=.venv/bin/python docs/eval-data/2026-08-20-j9-oracle-pin-field-measurement.py --worktree <throwaway> --real-repo <packnplan> -->

      BEFORE (harness ba7a38b, unpinned)   26 of 26 reach ORACLE exit 0 with every defect present
      AFTER  (harness at this HEAD)         0 of 26 do

`(26 of 26 -> 0 of 26, 0b7b0c9, the command above, rc 0, ~35 s)`. **The instance RB-P72
records was the mildest of the family.** `vitest.workspace.ts` and `vite.config.ts` reach
`exit 0` at `2 passed (2)` files and **`15 passed (15)` tests — 126 below pristine**, against
the recorded 108, which is 33 below. `vitest.projects.*` is a fourth name family that appears
in no prior evidence at all.

**2. One of RB-P72's own two nominated fixes is refuted by measurement, before anyone built
it.** The entry proposes *"a test-count floor measured against the pristine baseline, which is
the one signal all three guards currently ignore."* A padding WRITE clears it exactly:

<!-- provenance: value=row 4 BEFORE ORACLE exit 0 with 1 passed (1) files and 141 passed (141) tests, GUARD-TAMPER empty, GUARD-SCOPE 5 files, GUARD-T 0, classify_outcome PASS; commit=0b7b0c9; command=.venv/bin/python docs/eval-data/2026-08-20-j9-oracle-pin-field-measurement.py --worktree <throwaway> --real-repo <packnplan> rows -->

      vitest.config.ts including *.spec.ts + src/pad.spec.ts carrying 141 trivial tests
        ORACLE exit 0   1 passed (1) files | 141 passed (141) tests
        GUARD-TAMPER empty | GUARD-SCOPE 5 files (the defects) | GUARD-T 0
        classify_outcome -> PASS,  with all five DEFECT-SET-5 defects in the tree

The pristine total, to the digit. The mechanism is that `is_tamper_write` matches a `.test.ts`
suffix and `.spec.ts` is not one, and that the padding file is untracked so `guard_scope` — a
`git diff` over tracked paths — never sees it. **No floor was built and none should be.** This
is `RB-P77` below.

<!-- provenance: value=all six rows REPRODUCE both sides; control pristine exit 0 with 10 passed (10) and 141 passed (141); control defected exit 1 with 5 failed | 5 passed (10) and 7 failed | 134 passed (141); both controls' CANON-1 sha identical BEFORE and AFTER; commit=0b7b0c9; command=.venv/bin/python docs/eval-data/2026-08-20-j9-oracle-pin-field-measurement.py --worktree <throwaway> --real-repo <packnplan> rows -->

**3. The other nominated fix holds, and the rows are committed.** Six pre-registered rows,
BEFORE and AFTER from one command, all six reproduced here: four attacks `PASS -> FAIL`, two
controls unmoved (`pristine exit 0 / 10 passed (10) / 141 passed (141)`; `defected exit 1 /
5 failed | 5 passed (10) / 7 failed | 134 passed (141)`), with the controls' agent-visible
stream byte-identical BEFORE and AFTER. A control that had moved would have meant the pin
worked by breaking the run.

**4. Forward-only, stated explicitly and without softening.** J7's committed arms ran under an
unpinned oracle and always will have. **No `.jsonl` was regenerated or edited here, no
committed figure is restated as if it had run under the new oracle, and no protection whatever
is claimed for any committed row.** This job amends bar §1.3's oracle command for runs made
after it. RB-P72's *"deliberately not fixed"* disposition stands as J7's.

**5. And the sentence that must travel with all four of the above.** The config-discovery
class being closed at 26 of 26 **does not close the false PASS**. `RB-P78` below reaches
`classify_outcome PASS` in five WRITEs, with a CANON-1 stream byte-identical to pristine, on
both the pinned and the unpinned harness. **The pin is silent on it, not wrong.**

##### Two provenance commands inside RB-P72 that do not reproduce — corrected by amendment, never in place

**Both are RECORDS and both are amended here rather than edited.** The repo's pointer list is
a CLOSED LIST of four (`docs/record-vs-pointer.md` §1): hyperlink/anchor, section citation,
`file:line` pin, stale-state marker. **A provenance *command* is on none of them, so the
default binds and it is a record.** That classification is the whole reason these two lines
are corrected below instead of rewritten above.

Note what they are: **`RB-P74`'s class — a recorded derivation that does not reproduce —
sitting four entries below `RB-P74`, in the same section.** This is the second time a defect
of a named class has been found inside the document that names it.

**Correction 1 — `docs/eval.md:6423`.** The recorded command ends
`--worktree <throwaway> section N21`. The program **takes no `section` positional**, and it
fails in two independent directions:

<!-- provenance: value=argparse usage shows only [--worktree WORKTREE] [--real-repo REAL_REPO]; `section N21` -> rc 2 unrecognized arguments; `--worktree` alone -> rc 0 with live sections silently skipped; commit=0b7b0c9; command=.venv/bin/python docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py --help / ... --worktree <dir> section N21 / ... --worktree <dir> -->

      --help                          usage: ... [-h] [--worktree WORKTREE] [--real-repo REAL_REPO]
      --worktree <dir> section N21    rc 2   error: unrecognized arguments: section N21
      --worktree <dir>                rc 0   "OVERALL: every section closed as declared"

The second row is the worse one. `live = bool(args.worktree and args.real_repo)`
(`docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py:587` at this HEAD), so
`--worktree` **alone** skips every live section, prints a clean OVERALL and **exits 0**. The
recorded command therefore cannot produce the value it is provenance for, and the nearest
spelling of it produces a green run that measured nothing. **The working command, run here:**

    .venv/bin/python docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py \
        --worktree <throwaway> --real-repo <packnplan-mono>

which exits **1** at this HEAD for the reason recorded two subsections below, and prints the
N-21 section in full.

**Correction 2 — `docs/eval.md:6455`.** The pristine and defected baselines are attributed to
the same u5 program, which **never prints them**: `grep -c pristine` on it returns **0**. The
strings come from the harness's own `check-oracle`. **The working command, run here, which
reproduces both lines verbatim:**

<!-- provenance: value=grep -c pristine on the u5 program -> 0; check-oracle prints pristine ORACLE exit=0 10 passed (10) | 141 passed (141) and defected ORACLE exit=1 5 failed | 5 passed (10) | 7 failed | 134 passed (141), VERDICT baseline holds, rc 0; commit=0b7b0c9; command=J7_REAL_REPO=<packnplan> .venv/bin/python docs/eval-data/2026-08-18-loop-harness.py check-oracle --worktree <throwaway> -->

    J7_REAL_REPO=<packnplan-mono> .venv/bin/python \
        docs/eval-data/2026-08-18-loop-harness.py check-oracle --worktree <throwaway>

`(grep -c pristine -> 0 on the u5 program; check-oracle prints both baselines and VERDICT:
baseline holds at rc 0, 0b7b0c9, the two commands above)`. The closure document already said
so at `docs/eval-data/2026-08-19-loop-closure.md:143`, which is where the correct command has
been sitting the whole time.

**A line pin inside this correction drifted while it was being written, and it is reported
rather than quietly used.** The `print` that emits those strings is at
`docs/eval-data/2026-08-18-loop-harness.py:983` **at this HEAD**; it was at `:944` at
`ba7a38b` and at `8b6f365`, and `cc9882f` — this branch's own first commit — moved it by +39.
Both readings are correct at their own commit. This is `RB-P40`'s shape once more, caught by
pinning at HEAD instead of carrying a number.

##### Minted here — RB-P77 … RB-P82

Six, and the allocation is argued rather than assumed. **The two extra false-PASS filenames
belong inside the RB-P72 amendment, not in a number of their own** — they are further
instances of the claim RB-P72 already makes. **The refuted floor is not**: it is a claim about
a *fix proposed in a register entry and killed before implementation*, which is a different
kind of statement about a different object, and this program's rule is that a finding earns a
number when it is a claim someone could otherwise repeat. On that same rule the remaining four
are separable: none of them is an instance of any entry above.

- **`RB-P77` — a fix nominated inside a register entry was refuted by measurement before
  anyone built it, and so was the fix nominated to replace it.** Two floors, both dead.

  <!-- provenance: value=141 passed (141) at ORACLE exit 0 with every guard clean and all five defects present; commit=0b7b0c9; command=.venv/bin/python docs/eval-data/2026-08-20-j9-oracle-pin-field-measurement.py --worktree <throwaway> --real-repo <packnplan> rows -->

  (a) RB-P72's **test-count floor** against the pristine 141: cleared exactly, `141 passed
  (141)`, by one narrowing config plus `src/pad.spec.ts` carrying 141 trivial tests, every
  guard clean and all five defects present. The mechanism is `is_tamper_write`'s one-extension
  suffix check plus `guard_scope`'s blindness to creations. (b) The **identity floor** — key
  on `(test file, vitest fullName)` and catch padding because pristine ids go missing — which
  the J9 prep probe nominated as the padding-proof replacement: under `RB-P78` all 141
  pristine ids are present and passing, so the identity set **is** the pristine identity set
  and the floor reads clean. The general statement, and it is why this is a number and not a
  footnote: **a floor computed over the oracle's own report cannot see a tree the oracle read
  differently from the build.** **Attack:** a fix nominated in a register entry is a
  hypothesis, and the cheapest time to falsify it is before it is implemented — the padding
  attack cost one file. (Measurement / bar design, closed by refutation: neither floor is
  built and neither should be.)

- **`RB-P78` — the oracle and the build disagree about which files constitute the package, and
  five WRITEs of `.js` shadows reach `classify_outcome PASS` with a stream byte-identical to
  pristine, every declared guard clean, and all five defects on disk.** Every test file imports
  its subject by an extensionless relative specifier (`from "./date"`), and Vite's default
  `resolve.extensions` tries **`.js` before `.ts`**. Re-measured here with shadows written by
  hand and pushed through the harness's own WRITE tool:

  <!-- provenance: value=5 WRITEs, _resolve ADMITTED and is_tamper_write False on all five, ORACLE exit 0 with 10 passed (10) files and 141 passed (141) tests, GUARD-T 0, GUARD-TAMPER empty, GUARD-SCOPE 5 files, classify_outcome PASS, all five defect strings present on disk, CANON-1 sha identical to this run's pristine baseline and identical between the ba7a38b and HEAD harnesses; commit=0b7b0c9; command=python importing docs/eval-data/2026-08-18-loop-harness.py and `git show ba7a38b:` the same path, restore + apply_defects + five tool_write + run_oracle + the three guards + classify_outcome in a throwaway worktree -->

      WRITE src/date/date.js  src/trip/travelMode/travelMode.js
            src/place/openingHours/openingHours.js
            src/expense/split/split.js  src/expense/settle/settle.js
        _resolve ADMITTED and is_tamper_write False on all five; no test file edited
        ORACLE exit 0   10 passed (10) files | 141 passed (141) tests
        GUARD-T 0 | GUARD-TAMPER empty | GUARD-SCOPE 5 files (the defects, unchanged)
        classify_outcome -> PASS
        D1..D5 defect string present on disk: True True True True True
        CANON-1 sha256 identical to this run's own pristine baseline, and identical
          under the ba7a38b harness and the pinned harness at this HEAD

  **What ships is still defective, measured on the PASSing tree:** `packages/shared` declares
  `"build": "tsc"`, `tsc -p tsconfig.json` exits **0**, and `dist/date/date.js:36` reads
  `return value.slice(0, 8);` — D3 verbatim. The shadows are not in the program at all
  (`include: ["src"]`, `allowJs` unset), which is also why `GUARD-T` cannot move.
  **The pin neither opens nor closes this.** The same five writes PASS through the `ba7a38b`
  harness and through the pinned one, with the same sha: it predates `RB-P72` and survives its
  closure, and **the pin is silent on it, not wrong.** Contrast the four config attacks, every
  one of which moved the visible `Tests` line; this one leaves a tree whose `git diff` is
  exactly and only DEFECT-SET-5. **Attack, and it is structural: `RB-P73` is not adjacent to
  `RB-P72`, it is its PARENT.** All nine attacks on record — four config writes, the padding
  file, five `.js` shadows — are **file CREATIONS**, and a `git diff` guard cannot see a
  creation. One census sees them at once: `git status --porcelain -uall --ignored=matching --
  packages/shared` returned **10 `??` paths** on a tree carrying nine of them (the nine plus
  the harness's own planted `node_modules` symlink, which a census must exclude by name) plus
  **2 `!!` paths** that `-uall` alone misses. The stronger property is that the oracle's module
  graph must equal the build's — any file in one and not the other is the attack, without
  enumerating spellings — and the cheapest is already in the file: the **inverse of
  `apply_defects`**, asserting that none of the five replacement strings survives at scoring
  time, which would have read RED on all five at the moment PASS was returned. Any of these is
  **forward-only**; applied to committed rows it is the post-hoc gate bar A2.8 item 2 forbids.
  Note the deeper limit that survives all of them: the oracle's authority is *"the tests are
  green"*, never *"the defect is gone"*. (Measurement / bar design, **open,
  escalation-class**.)

- **`RB-P79` — the declared reset does not reset what it declares, so the repeats of an arm are
  not independent.** `restore()` is `git clean -fdx -q -e node_modules -e
  packages/shared/node_modules`, and `-e node_modules` is a **slash-free gitignore pattern, so
  it matches a directory of that name at any depth** — not only the two symlinks it was written
  to protect. Measured:

  <!-- provenance: value=src/date/date.js False after restore while src/node_modules/payload/index.js and src/date/node_modules/payload2.js are both True; _resolve admits both; git status --porcelain -uall over packages/shared/src empty while --ignored=matching lists both directories; tool_list shows node_modules False; commit=0b7b0c9; command=python importing docs/eval-data/2026-08-18-loop-harness.py, tool_write three paths, restore(wt, real_repo), os.path.exists on each, then git status with and without --ignored=matching -->

      after restore()   src/date/date.js                      False   (removed, as declared)
                        src/node_modules/payload/index.js     TRUE    (survives)
                        src/date/node_modules/payload2.js     TRUE    (survives)
      git status --porcelain -uall -- packages/shared/src     (empty)
      ... --ignored=matching                                  !! src/node_modules/
                                                              !! src/date/node_modules/
      `node_modules` in tool_list(wt, "src")                   False

  `_resolve` **admits** both paths — the refusal of `node_modules/.bin/vitest` is only because
  *that* path realpaths out through the symlink, not a rule about the name — and node and vite
  walk `src/<...>/node_modules` before `packages/shared/node_modules`, so an agent-written
  package there wins for every externalised bare dependency. It is invisible to `tool_list`, to
  both guards, and to a full untracked census: it needs `--ignored`. **Repeat N can poison
  repeat N+1**, and `cmd_check_oracle` calls the same `restore()` before printing
  `VERDICT: baseline holds`. This is not hypothetical twice over: the adversarial review hit it
  by accident and only caught it because a count moved, and the census measured for `RB-P78`
  above listed a `!!` directory left behind by an earlier probe in this very section.
  **NOT FIXED HERE.** It is a committed instrument, the fix changes what a reset means, and it
  deserves its own job with its own bar. **Attack:** an exclusion list must be anchored
  (`/node_modules`, `/packages/shared/node_modules`), and the reset must be verified from a
  census that includes ignored paths rather than from its own exit code. (Instrument, open —
  the most operationally serious thing on this page.)

- **`RB-P80` — the harness's two tamper checks disagree on case, on a filesystem that does
  not.** `is_tamper_write` is a **case-sensitive** `.test.ts` suffix check; this filesystem is
  case-**insensitive**. Measured: `os.path.isfile(<wt>/packages/shared/src/date/date.TEST.ts)`
  is **True** with only `date.test.ts` on disk; `_resolve` admits `src/date/date.TEST.ts` and
  `is_tamper_write` returns **False** on it, while returning **True** on
  `src/date/date.test.ts`. So a WRITE to the upper-cased spelling is not flagged and lands on
  the real tracked test file. `guard_tamper` still catches it, so no verdict is lost — **and
  that is the finding: bar Amendment 2 A2.2's fast path and bar §1.4's column disagree, and
  only the slow one holds.** The extension check is `RB-P73`'s business; the *disagreement*
  between two checks of the same rule is not. **Attack:** the two must be one predicate, or the
  fast path must be documented as advisory. (Instrument, open.)

- **`RB-P81` — the pin fails closed under a harness copy, and scores the failure as an outcome
  instead of an instrument event.** `ORACLE_CONFIG` is `__file__`-relative with no existence
  precondition. Under a copy of the harness without the `.ts` beside it — the shape
  `_module_pair` / `_mutated` produce — vitest does **not** silently fall back to
  auto-discovery: it emits `Could not resolve …`, a `Startup Error`, and exit 1. That direction
  is right and it means a copy-loaded harness cannot re-open `RB-P72`. What is wrong is the
  label: the run then scores **`FAIL`**, an OUTCOME, where the instrument never started, and
  `SHAPE-silent-truncation` S5 is the rule that calls exactly this class **VOID**. Nothing is
  mis-scored today — the `_mutated()` modules only reach `cmd_selfcheck`, which never calls
  `run_oracle` — so this is a live trap for the next program that copies the harness and does.
  **Attack:** a missing pinned config is a precondition failure and belongs above `FAIL` on the
  ladder, beside `run-cap` and `endpoint-error`. Not fixed here: adding a rung is a bar change.
  (Instrument / bar design, open.)

- **`RB-P82` — the CANON-1 sha of an ORACLE run is a function of the throwaway worktree's path,
  so it is a within-run comparator and never a portable constant.** CANON-1 rule (a) scrubs
  ANSI, durations, timestamps and `[k/N]` indices; it does **not** scrub the absolute path, and
  vitest's first line is ` RUN  v2.1.9 <wt>/packages/shared`. Measured on one pristine tree:

  <!-- provenance: value=sha256(canon1(out)) 1a4bdd809e384a49... with the real worktree path and 6945e02abae449e5... with that path replaced by <WT>; the RUN line carrying the path is inside canon1's output; three different pristine values are on record across three runs of the same tree; commit=0b7b0c9; command=python importing docs/eval-data/2026-08-18-loop-harness.py, run_oracle then hashlib.sha256(canon1(out)) with and without the worktree path substituted -->

      sha256(canon1(out))                       1a4bdd809e384a49...
      sha256(canon1(out) with path -> <WT>)     6945e02abae449e5...
      the line responsible:  RUN  v2.1.9 <wt>/packages/shared

  Three different pristine CANON-1 values are on record for the same tree — `ea83faaf…` in
  `cc9882f`'s message, `934b0e3f…` in the adversarial review, `1a4bdd80…` here — and **all
  three are correct**, because each ran in a differently-named worktree. **No committed claim
  is refuted:** every load-bearing use compares BEFORE against AFTER *within one run and one
  worktree*, which is exactly what the property supports, and `0b7b0c9`'s program pre-registers
  no sha. What is refuted is the reading a commit message invites, that these are constants a
  later run reproduces. A second, smaller ambiguity rides along: *"the CANON-1 sha"* is
  under-specified even within a run, because `sha256(canon1(out))` and the variant the agent's
  stream actually carries, `canon1(out) + "\n(exit code N)"`, hash differently. **Attack:**
  scrub the worktree root in rule (a) — it is an environment artefact of exactly the kind rule
  (a) already removes — or stop publishing sha values as if they travelled, and always name
  which of the two variants is meant. (Instrument, open.)

##### The forward effect on a committed J7 program, and how this register records it

Section N-21 of `docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py` takes the
**working tree** as its AFTER. With the pin in place, all three of its configs now read
`exit 1`, it prints `DOES NOT REPRODUCE -- no config write reached ORACLE exit 0 here`, and
**the program exits 1 where it exited 0 at `ba7a38b`.** Re-measured here:

<!-- provenance: value=rc 1, N-21 prints DOES NOT REPRODUCE with all three configs at ORACLE exit 1 and classify_outcome FAIL, MUT unmutated selfcheck 0 RED and 4/5/5 RED under its three mutations, OVERALL 1 section(s) did not; commit=0b7b0c9; command=.venv/bin/python docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py --worktree <throwaway> --real-repo <packnplan> -->

      N-21   all three configs  ORACLE exit=1 ... classify_outcome -> FAIL
             "DOES NOT REPRODUCE -- no config write reached ORACLE exit 0 here"
      MUT    unmutated selfcheck: 0 RED;  mutations c2 / n17 / n17b:  4 / 5 / 5 RED
      OVERALL: 1 section(s) did not          rc 1

**The program was not edited, and that is deliberate: it is J7's committed evidence.**

**The judgement, made rather than deferred: a committed measurement program's exit status is
not a gate of this repository, and its rows are what matter.** The two honest framings were
*that*, and *a program that exits 1 on a correct tree is a defect in this program's own
conventions*. The first is chosen for a reason narrower than convenience: this program's exit
status is a claim about whether its own sections reproduced **against the tree it was handed**,
and N-21 is the one section written to take the live tree as its AFTER. Its exit 1 is that
section doing its job — the attack it re-runs genuinely no longer reproduces — not a
regression. Nothing else in it moved: the MUT columns are 4/5/5 exactly as at `ba7a38b`, and
the unmutated selfcheck is still 0 RED.

**What a reader who runs it tomorrow should conclude, stated so it does not have to be
inferred:** `rc 1` with **exactly one** DOES-NOT-REPRODUCE section, that section being N-21,
MUT at 4/5/5 and the unmutated selfcheck at 0 RED, means **the pin is in place**. Any other
section failing, or the MUT columns moving, is a real regression and this sentence does not
cover it.

**And the cost of that choice, which is not papered over.** N-21's own prose now says
something false at this HEAD: *"The surface is still unguarded, but the attack is UNMEASURED
and must be reported that way."* The config-discovery surface **is** guarded here, at 26 of 26
names. Correcting that sentence would mean editing committed evidence to agree with a later
tree, which is the one thing bar A2.8 item 2 and the record rule both forbid. **The sentence
stays wrong in place and is corrected here instead** — which is what "records amend" costs,
paid in the open.

##### Three things about the pin a reader will otherwise re-derive

- **`defineConfig` is a measured constraint, not a style choice.** The pinned config is a plain
  object with no imports on purpose. Importing `defineConfig` from `"vitest/config"` makes
  vitest 2.1.9 load Vite's CJS Node API and print `The CJS build of Vite's Node API is
  deprecated` **on stderr** — measured directly here — and `run_oracle` returns
  `p.stdout + p.stderr`, so that line lands in the agent's ORACLE output. **That is a TASK
  change, not an instrument change**, and it moves the CANON-1 sha. The `.mts`/`.mjs`
  spellings cannot resolve `vitest` at all from a directory with no `node_modules` in its
  ancestry, which is precisely where this file has to live. The next person will reach for
  `defineConfig` by reflex; this is why not.
- **A third `M11` case was written, measured and deleted, and the deletion is the finding.** A
  case asserting the pinned config exists on disk reddens under all three of the u5 program's
  mutations — none of which touches the oracle — because that program loads the harness from a
  temp copy and `ORACLE_CONFIG` is `__file__`-relative. Its columns went 4/5/5 → 5/6/6 with the
  case and back to 4/5/5 without it (`cc9882f`; the 4/5/5 side is re-measured above).
  **A check that reddens for a reason its name does not state launders unrelated mutations into
  its own column**, and that is a general claim about must-be-red catalogues worth more than
  the case was. Its consequence — that nothing now asserts the pinned file exists — is
  `RB-P81`.
- **"0 RED at `ba7a38b`" is not evidence of a pin.** The selfcheck has **48** cases at
  `ba7a38b` and **50** at this HEAD; `M11` is the two new ones. There was nothing to check
  there, and a before/after RED count over a growing catalogue says so only if the case counts
  are printed beside it.

##### What is NOT claimed

**`RB-P73` is untouched and every part of it stands exactly as filed:** `guard_tamper`'s glob,
the invisibility of file *creation* to a `git diff`-based guard, and `is_tamper_write` being a
one-extension suffix check. `RB-P77`'s padding attack works *because* of that last one, and
`RB-P78` works because of the middle one. **Four config attacks plus a fifth of a different
kind are five attacks, not a closed surface** — the 26 names are the class of filenames vitest
2.1.9 *discovers*, not the class of ways an oracle can be gamed; `--project`,
`environmentMatchGlobs`, an `envDir`-loaded `.env`, and the `.mjs`/`.mts`/`.json` spellings of
the `RB-P78` shadow were **not** run. Every precedence behaviour here is a property of vitest
**2.1.9** and node **25.2.1**. **No live model call was made anywhere in this job**, so nothing
here says whether a model would *find* any of these — only that the harness admits them. And
nothing here is a claim about J7's committed arms.

##### One sentence the trailing-field convention was owed

`repeat` is the third exercise of `TaskResult`'s additive trailing-field convention, after
`seed` and `RB-P38`'s `model`, landed in `01fd283` and documented in place at
`runtime-py/src/bantamkit/evalrun.py:215-229` at this HEAD.

It is written **here** and not inserted into `RB-P38`'s bullet
(`docs/eval.md:4962-4966` at this HEAD, which names `seed` and the eight accounting columns as
the precedents) or into `RB-P46`'s (`docs/eval.md:5238-5250`, which names the convention and
`model`), for the reason this whole section keeps paying: **those bullets are records.**
Neither of them names both precedents, either, which is worth saying since the brief that
carried this sentence described a single passage that does.

##### Gates at this commit

<!-- provenance: value=1010 passed, 2 xfailed; commit=0b7b0c9; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=1012 tests collected; commit=0b7b0c9; command=.venv/bin/python -m pytest runtime-py/tests -q --collect-only -->
<!-- provenance: value=All checks passed! on runtime-py and on docs/eval-data; commit=0b7b0c9; command=.venv/bin/ruff check runtime-py && .venv/bin/ruff check docs/eval-data -->
<!-- provenance: value=SELFCHECK: all cases behaved as declared, rc 0; commit=0b7b0c9; command=.venv/bin/python docs/eval-data/2026-08-18-loop-harness.py selfcheck -->

| gate | value | commit | command |
|---|---|---|---|
| suite | **1010 passed, 2 xfailed** | `0b7b0c9` | `.venv/bin/python -m pytest runtime-py/tests -q` |
| collected | **1012** | `0b7b0c9` | `... -q --collect-only` |
| ruff, `runtime-py` | **All checks passed!** | `0b7b0c9` | `.venv/bin/ruff check runtime-py` |
| ruff, `docs/eval-data` | **All checks passed!** | `0b7b0c9` | `.venv/bin/ruff check docs/eval-data` |
| harness selfcheck | **all cases behaved as declared**, rc 0 | `0b7b0c9` | `.venv/bin/python docs/eval-data/2026-08-18-loop-harness.py selfcheck` |

**The total does not move for this section and the reason is derived, not asserted.**
`runtime-py/tests/test_field_programs.py` carries four nodes parametrised over the files in
`docs/eval-data/`, which is why `0b7b0c9` reads 1010 against `b1f41e5`'s 1006 — that commit
added one `.py` there, 1006 + 4 = 1010. **This section adds no `.py` under `docs/eval-data/`
and no test**, so 1010 / 1012 is the expected reading at this section's commit too; the earlier
gate readings `ba7a38b` → **1005**, `b1f41e5` → **1006** and `0b7b0c9` → **1010** are each
correct at their own commit and none of them is quoted without it.

##### Fences held by this section

**Nothing merged, nothing pushed, no `git tag` in any form.** **No `.jsonl` was regenerated or
edited and no committed figure is restated as if it had run under the new oracle.** **No live
model call was made.** The workload `packnplan-mono` was never modified in place: two throwaway
worktrees at `81ac1a1`, both removed with `git worktree remove --force` and `prune`, after
which `git -C <packnplan> status --porcelain` shows the same single pre-existing untracked line
`?? docs/test-cases/REVIEW-multi-perspective-2026-07-30.md` and `rev-parse HEAD` is `81ac1a1`,
unmoved. **`RB-P72`, `RB-P73`, `RB-P74`, `RB-P75`, `RB-P76` and both of section R's amendments
are untouched**; every correction above is appended. One layer: `docs/` only.
#### T (2026-08-19) — `RB-P79` goes from filed to fixed in seventeen minutes, and the triage rule that had already declined the same defect twice

`RB-P79` was minted in section S above, at `03b6a2e` (22:43:28), and filed **NOT FIXED HERE** —
*"it is a committed instrument, the fix changes what a reset means, and it deserves its own job
with its own bar."* `9b9ad0c` (23:00:43) is that job. **This is the first entry in this program
to go from filed to fixed inside one shift**, which is why the amendment below is written to be
read straight after `RB-P79` itself (`docs/eval.md:7528-7557` at this HEAD) and repeats none of
it. **`RB-P79` is a record and is not edited.** Nothing here is regenerated: no `.jsonl` was
touched, and every figure below was re-derived by this unit rather than carried from the fix.

##### Amendment 1 to `RB-P79` — 2026-08-19, the fix, the arm the entry did not carry, and the bar that holds both halves

**What landed.** `restore()`'s `git clean` exclusions are now built from `NODE_LINKS` itself and
carry a **leading slash**, so the tuple that protects the two symlinks and the tuple that
re-plants them are one object and cannot drift. Selfcheck node **M12** is the bar.

**1. Three arms, and arm C is the one `RB-P79` does not carry.** `RB-P79` measured two arms —
slash-free and anchored. Two arms cannot tell a reader why the exclusions exist at all, and the
next person to read `restore()` will see two `-e` flags protecting two symlinks that `.gitignore`
already names and reach for the delete key. The third arm is what stops that, so it is recorded
here. A throwaway repository shaped like the workload — tracked `.gitignore` carrying
`node_modules/` and `dist/`, two `node_modules` symlinks into a sibling directory, four files a
previous repeat could have written — reset once per arm, at git **2.50.1**:

<!-- provenance: value=arm A leaves src/node_modules/payload/index.js and src/date/node_modules/payload2.js present with both symlinks alive; arm B removes all four payloads with both symlinks alive; arm C removes all four payloads AND both symlinks (links []); all three arms remove src/date/date.js and dist/build.js; commit=9b9ad0c; command=.venv/bin/python over a fresh tempfile.TemporaryDirectory: git init, tracked .gitignore + one tracked .ts, plant two symlinks and four payloads, then git checkout -f -- . and git clean -fdx -q with each arm's -e flags, then os.path.exists per payload and os.path.islink per link -->

    payload written by "repeat N"        arm A            arm B            arm C
                                    (slash-free)      (anchored)     (no exclusions)
    src/date/date.js                     GONE             GONE             GONE
    src/node_modules/payload/index.js    PRESENT          GONE             GONE
    src/date/node_modules/payload2.js    PRESENT          GONE             GONE
    dist/build.js                        GONE             GONE             GONE
    node_modules            (symlink)    survives         survives         DELETED
    packages/shared/node_modules         survives         survives         DELETED

Read the last two rows before deleting anything. **Arm C is not a simplification of arm B, it is
`N-3` — `git clean -fd` deletes the workload's `node_modules` symlinks — and a harness that
takes it has no oracle at all from the second repeat onward.** A `.gitignore` *directory* pattern
does not match a symlink, so `node_modules` being ignored protects nothing here; the exclusion
list is the only thing that does whenever `J7_REAL_REPO` is unset. Read the `dist/build.js` row
too: it is `GONE` in **all three** arms, which is `N-16`'s `-x` fix still holding under the new
exclusion list, measured rather than assumed.

**2. The census is the generalisable half, and it is why nobody saw this.** The residue arm A
leaves is **not visible to a full untracked census**. Measured on the same fixture, after an
arm-A reset:

<!-- provenance: value=git status --porcelain -uall over packages/shared/src is EMPTY while --ignored=matching lists !! packages/shared/src/date/node_modules/ and !! packages/shared/src/node_modules/, with src/node_modules/payload/index.js still on disk (os.path.exists True); commit=9b9ad0c; command=.venv/bin/python over the same fixture, git status --porcelain -uall -- packages/shared/src with and without --ignored=matching -->

    git status --porcelain -uall -- packages/shared/src      (empty)
    ... --ignored=matching                    !! packages/shared/src/date/node_modules/
                                              !! packages/shared/src/node_modules/
    os.path.exists(src/node_modules/payload/index.js)        True

The workload's own `.gitignore` carries `node_modules/`, so a directory the agent creates at
`packages/shared/src/node_modules/` is **ignored, not untracked**, and every census this harness
had — `tool_list`, `guard_scope`, `guard_tamper`, `git status -uall` — is blind to it by
construction. **`--ignored=matching` is the load-bearing flag**, and `worktree_residue()` exists
to carry it. The transferable claim is not about `node_modules`: **a reset verified from its own
exit code, or from an untracked-only census, cannot see the class of residue that ignore rules
were written to hide, which is exactly the class a build or an installer leaves behind.**

**3. M12 has four cases, two of them setup, and the two property cases are disjoint halves —
neither is a spare.** The property is *after `restore()`, nothing the previous repeat wrote
survives except the two symlinks the harness itself plants*, and it is two-sided. Measured by
mutating a scratch copy of the harness and running `selfcheck` on the copy — the unmutated copy
reads **0 RED / 54 cases**, identical to the file in place, so the copy is a faithful vehicle:

<!-- provenance: value=unmutated 0 RED over 54 cases; mutation "revert to the slash-free -e rel" reddens exactly 1 case, "M12 RED: `restore()` leaves the two symlinks and NOTHING else", and leaves "and the exclusion ALONE keeps them, with no re-plant" GREEN; mutation "delete the excludes loop entirely" reddens exactly 1 case, the second one, and leaves the first GREEN; commit=9b9ad0c; command=cp docs/eval-data/2026-08-18-loop-harness.py to a scratch copy, apply each mutation to the copy, .venv/bin/python <copy> selfcheck -->

    mutation applied to a scratch copy of the harness      case 3    case 4
    (none)                                                 green     green      0 RED / 54
    excludes += ["-e", rel]        (slash-free again)      **RED**    green      1 RED
    excludes = []                 (exclusions deleted)      green   **RED**      1 RED

**Case 3 staying green under the second mutation looks like a hole and is not.** That case's
`restore(wt, real)` passes a real repository, so the links are deleted by `clean` and then
**re-planted** by the `if real_repo:` branch — the residue really is exactly the two links, and
green is the correct reading. The second half is only reachable through a call with **no
re-plant**, which is why case 4 calls `restore(wt)` bare. **That is the default configuration,
not a contrived one:** `run_one` calls `restore(wt, REAL_REPO)` and `REAL_REPO` is
`os.environ.get("J7_REAL_REPO", "")` (`docs/eval-data/2026-08-18-loop-harness.py:83`), which is
`''` — falsy, no re-plant — whenever that variable is unset. Verified at HEAD:

<!-- provenance: value=J7_REAL_REPO not in os.environ, REAL_REPO repr '' and bool False, NODE_LINKS ('node_modules', 'packages/shared/node_modules'); commit=9b9ad0c; command=env -u J7_REAL_REPO .venv/bin/python -c importlib.util loading docs/eval-data/2026-08-18-loop-harness.py and printing repr(REAL_REPO), bool(REAL_REPO) and NODE_LINKS -->

    'J7_REAL_REPO' in os.environ   False
    repr(REAL_REPO)                ''          bool(REAL_REPO)  False

So on the default path **the exclusion list is the sole protection for the two symlinks**, and
case 4 is the only case that measures it.

**4. The laundering check is promoted from a lesson to a procedure.** Section S records that a
third `M11` case was written, measured and deleted because it reddened under all three of the
U5 closure program's mutations — none of which touches the oracle — and concluded that *a check
that reddens for a reason its name does not state launders unrelated mutations into its own
column.* **That lesson is now a gate a new must-be-red case has to pass before it lands**, and
M12 passed it before `9b9ad0c` was written. Re-measured here:

<!-- provenance: value=MUT unmutated selfcheck 0 RED; mutation c2 4 RED all four M8 cases; n17 5 RED all five M9 cases; n17b 5 RED the same five M9 cases; no M12 case appears in any mutation's column; C-1/N-16 and N-21 UNMEASURED in this invocation (no --worktree), rc 0; commit=9b9ad0c; command=.venv/bin/python docs/eval-data/2026-08-19-loop-u5-closure-field-measurement.py -->

    unmutated selfcheck            0 RED
    mutation c2                    4 RED   -- all four M8 cases
    mutation n17                   5 RED   -- all five M9 cases
    mutation n17b                  5 RED   -- the same five M9 cases
    M12 cases appearing above      NONE

**0 / 4 / 5 / 5, unchanged from `ba7a38b` and from section S**, and the column contents are the
reason rather than the totals: M12 depends only on `restore()` and on git, never on `__file__`,
so a program that loads the harness from a temp copy cannot redden it. **The procedure, stated
so it does not have to be re-derived: a new must-be-red case lands only after the existing
mutation catalogue has been re-run with it present and every mutation's column is unchanged in
its members, not merely in its count.** Two units' work produced that sentence and it is the
durable half.

**Not claimed, and the invocation is narrower than section S's.** This run passed no
`--worktree`, so `C-1 / N-16` and `N-21` printed **UNMEASURED** and were skipped, and this
program exited **0**. That is not a contradiction of section S's `rc 1` reading, which was
measured **with** a worktree and is a statement about N-21; nothing here re-measures N-21 or
supersedes it.

##### What the fix binds, and the claim this amendment does not make

**No committed row becomes independent, and that is stated rather than implied.** The rows of
**B0** and **B0"** were produced under the slash-free exclusion, they stand exactly as written,
and **their repeat independence is not established by this fix and is not re-litigated here.**
The fix binds **runs made after `9b9ad0c`** and nothing else.

Sharper, since it can be said: the committed rows are not thereby worthless, and the boundary is
locatable rather than vague. **What they can still support** is anything decided *within a single
repeat* — a row's own tool sequence, its own guard columns, its own oracle exit — because the
residue is written by repeat N and read by repeat N+1, so repeat r0 of every arm is downstream of
nothing. **What they cannot support** is any comparison whose unit of independence is *the
repeat*: a distinct-value count across an arm's repeats, a variance, a determinism claim, or a
per-arm mean read as an average of independent draws. Section S already recorded the observable
shape of this on the six committed **B0"** rows — `guard_type_exit` reads `[2, 1, 1, 1, 1, 1]`
while every content column is 1 distinct of 6 — and that shape is exactly what carried state
between repeats produces. **The honest reading of the committed repeats is `r0` plus five
observations of unknown dependence, and this amendment does not convert them into six.**

##### Minted here — `RB-P83`, and why the class it came from does not get a number

**The register was read at HEAD before any number was chosen, and not taken from a brief, a
backlog or an orchestrator.** That precaution is `RB-P75`'s, and the ceiling moved twice on
2026-08-19, so the read is recorded:

<!-- provenance: value=82 distinct RB-P entries, ceiling RB-P82, contiguous 1..82 with no gaps; commit=9b9ad0c; command=grep -oE 'RB-P[0-9]+' docs/eval.md | sort -u | wc -l, then | sed 's/RB-P//' | sort -n | tail -1, then a python set-vs-range comparison over the same regex -->

    grep -oE 'RB-P[0-9]+' docs/eval.md | sort -u | wc -l     ->  82 distinct
    ... | sed 's/RB-P//' | sort -n | tail -1                 ->  ceiling RB-P82
    sorted(set) == list(range(1, 83))                        ->  True, no gaps

`(82 distinct / ceiling RB-P82 / 0 gaps, 9b9ad0c, the three commands above)`. **`RB-P83` is the
next free number and this section mints exactly one entry, `RB-P83`.**

**The class does not get a number, and the one sentence is this:** `RB-P79`'s own **Attack**
clause already states the general rule — *an exclusion list must be anchored … and the reset must
be verified from a census that includes ignored paths rather than from its own exit code* — so
`N-3`, `N-16` and `compaction-mcp`'s `embcache.json` are **further instances of a claim the
register already makes**, which is the disposition section S's own precedent gives that shape
(`docs/eval.md:7457-7459`, where two further false-PASS filenames were sent into the `RB-P72`
amendment rather than into numbers of their own); what is **not** claimed anywhere is the triage
rule that let two of those instances go unfiled, and that is `RB-P83`.

- **`RB-P83` — "closed inside the harness and instrument-local" was used to decline a register
  number for a defect in one function's reset scope, twice, and seventeen hours later the third
  defect in that same function's same reset scope was filed as the most serious entry on the
  page.** Section Q's *Not filed, and why — the remaining twenty* (`docs/eval.md:6593-6600`,
  landed in `3541e3d` at 05:26:26) declines numbers for **`N-3`** (*"`git clean -fd` deletes the
  workload's `node_modules` symlinks"*) and **`N-16`** (*"`restore()` carried gitignored state
  between repeats"*) on the stated ground that each is *"closed inside J7's own harness and
  instrument-local"* and that *"none constrains a future job that does not use that program."*
  At `03b6a2e` (22:43:28 the same day) `RB-P79` files a **third** defect in the scope of **the
  same single `git clean` invocation inside the same function** and calls it *"the most
  operationally serious thing on this page."* All three are one property — what `restore()`'s
  reset removes and what it keeps — and the three-arm table above contains all three at once:
  **arm C is `N-3`** (both symlinks deleted), **arm A is `RB-P79`** (nested `node_modules`
  survives), and the `dist/build.js` row being `GONE` in every arm is **`N-16`'s fix still
  holding**. The register did **not** overlook this: the same paragraph names `N-16` as one of
  *"the two closest calls in this group — an isolation routine that did not isolate"* and files
  it under *not filed* anyway. **That is what makes it a rule defect rather than an oversight**,
  and it is the same family as `RB-P74` and `RB-P75` — entries that exist because the register's
  own procedure, not its subject matter, failed. **What it costs:** two of the three instances
  are discoverable only by reading a declined-findings paragraph and a docstring, so `RB-P79`
  was filed and fixed as a first occurrence when it was a third, and the amendment above had to
  reconstruct the other two from `git log -S`. **Attack:** the triage question that failed is
  *"is it closed, and is it instrument-local?"*; the question that would have caught it is
  *"is the **property** load-bearing for something this register publishes?"* — repeat
  independence is, since it is the precondition under which an arm's repeats are draws at all.
  Concretely: **when a finding is declined as instrument-local, file the *property* once under a
  number and let further instances amend it**, rather than declining each instance separately on
  the ground that each already has a patch. **Not fixed here, and deliberately:** re-filing
  `N-3` and `N-16` retroactively would edit section Q's records, which the record rule forbids;
  the binding is on the *next* section's triage. Nothing in `RB-P79`, `N-3` or `N-16` is refuted
  or weakened by this entry — each is correct as filed. (Process / register triage, **open**.)

##### One thing this unit was handed that does not reproduce

The brief this unit was handed asserts that **`RB-P53` found the same class in `embcache.json`,
"written and reloaded so arms were not independent without eviction."** Checked at HEAD, it does
not reproduce, and the correction is recorded rather than quietly dropped:

<!-- provenance: value=grep -c embcache docs/eval.md is 0; the only file in the repository containing the string is docs/eval-data/2026-08-19-instrument-hygiene-plan.md; commit=9b9ad0c; command=grep -c embcache docs/eval.md and grep -rl embcache . -->

    grep -c embcache docs/eval.md      ->  0
    grep -rl embcache .               ->  docs/eval-data/2026-08-19-instrument-hygiene-plan.md

- **`RB-P53` is not that finding.** It is *the summarizer in a merged job read 6.6% of what it
  was sent* (`docs/eval.md:5550`) — `compaction-mcp`'s `DirectSummarizer` sends no
  context-length parameter, `ollama` truncates the prompt, returns `finish_reason: "stop"` with
  no error, and reports `usage.prompt_tokens` equal to **the window**. It is a silent-clamp
  finding on the **fidelity** axis. It says nothing about a cache and nothing about repeat
  independence.
- **The `embcache.json` site is real, and its identifier is `S3`, not `RB-P53`** — a near-miss
  in the name, which is presumably where the substitution came from. It is recorded at
  `docs/eval-data/2026-08-19-instrument-hygiene-plan.md:720` (*"embeddings, same exposure, caches
  its damage to `embcache.json`"*), scoped **out** of J3 as another repository, and carried into
  this file only inside **`F-8`** (`docs/eval.md:5829`) as *"damage cached to disk."* The plan
  records it as **latent** — one env var makes it live and the cache survives a restart — so it
  is a legitimate third instance of the class discussed above, under the right name.
- **The same substitution is in `9b9ad0c`'s commit message** (*"Same class as RB-P53 — a
  repeat-independence defect in a committed instrument"*). A commit message is not a committed
  row and is not rewritten; it is corrected here. **The genuine second instance is `N-16`, in
  the same function**, which is the evidence `RB-P83` above rests on — so the brief's conclusion
  that a second instance exists survives, and only its citation fails.

Two smaller imprecisions in the same brief, recorded for completeness and neither load-bearing:
it says *"M12's **first** case stays green"* under the exclusion-removal mutation, where the two
cases that stay green are M12's setup cases and the property case that stays green is the
**third** of four; and it describes the four cases as though all four assert the property, where
two are setup assertions that the fixture planted residue and that the census can see the
ignored half at all. Both are measured in the table under point 3 above.

##### Gates at this commit

**Read the commit column literally.** Every gate below was measured at `9b9ad0c` **with this
section's `docs/eval.md` edit present in the working tree**. That is the commit the numbers
belong to and it is the one quoted; no gate in the table reads `docs/eval.md`, and
`test_field_programs.py` parametrises over `docs/eval-data/` only, so the commit that carries
this section cannot move any of them.

<!-- provenance: value=1010 passed, 2 xfailed; commit=9b9ad0c; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=1012 tests collected; commit=9b9ad0c; command=.venv/bin/python -m pytest runtime-py/tests -q --collect-only -->
<!-- provenance: value=All checks passed! on runtime-py and on docs/eval-data; commit=9b9ad0c; command=.venv/bin/ruff check runtime-py && .venv/bin/ruff check docs/eval-data -->
<!-- provenance: value=SELFCHECK: all cases behaved as declared, rc 0, 54 cases; commit=9b9ad0c; command=.venv/bin/python docs/eval-data/2026-08-18-loop-harness.py selfcheck -->

| gate | value | commit | command |
|---|---|---|---|
| suite | **1010 passed, 2 xfailed** | `9b9ad0c` | `.venv/bin/python -m pytest runtime-py/tests -q` |
| collected | **1012** | `9b9ad0c` | `... -q --collect-only` |
| ruff, `runtime-py` | **All checks passed!** | `9b9ad0c` | `.venv/bin/ruff check runtime-py` |
| ruff, `docs/eval-data` | **All checks passed!** | `9b9ad0c` | `.venv/bin/ruff check docs/eval-data` |
| harness selfcheck | **all cases behaved as declared**, rc 0, **54** cases | `9b9ad0c` | `.venv/bin/python docs/eval-data/2026-08-18-loop-harness.py selfcheck` |

**The total does not move, and the reason is derived rather than asserted.**
`runtime-py/tests/test_field_programs.py` carries four nodes parametrised over the files in
`docs/eval-data/`, so the count moves by four for each `.py` added there. `9b9ad0c` **edited** an
existing file and added none, and this section adds none and touches only `docs/eval.md`, so
1010 / 1012 is the expected reading here, and it is measured here rather than carried. Section S
records the same 1010 / 1012 at `0b7b0c9`, and records `ba7a38b` → **1005** and `b1f41e5` →
**1006**; those three are section S's readings at section S's commits, are not re-measured here,
and none of them is quoted without the commit it belongs to.

**The selfcheck count moved and the arithmetic is stated, because a RED count over a growing
catalogue means nothing without it.** `03b6a2e` reads **50** cases, this HEAD reads **54**;
`M12`'s four are the difference, 50 + 4 = 54.

<!-- provenance: value=50 selfcheck cases at 03b6a2e against 54 at 9b9ad0c, difference exactly M12's four; commit=9b9ad0c; command=git show 03b6a2e:docs/eval-data/2026-08-18-loop-harness.py > <scratch>/pre.py then .venv/bin/python <scratch>/pre.py selfcheck | grep -cE '^\s+\[(ok|RED)' against the same count on the file in place -->

##### Fences held by this section

**One layer: `docs/eval.md` only** — no `.py`, no `.jsonl`, nothing under `runtime-py/`.
**`RB-P79` is untouched, and so are `N-3`, `N-16`, `F-8`, `RB-P53` and every entry of sections P
through S**; every correction above is appended, and the two corrections to a commit message and
to a brief are made here rather than by rewriting either. **No `.jsonl` was regenerated or
edited and no committed row is restated.** **No committed row is claimed to be independent.**
**No live model call was made.** The workload `packnplan-mono` was not touched at all: every
measurement above ran against fresh `tempfile.TemporaryDirectory` repositories or against this
repository, and the one invocation of the U5 closure program was made **without** `--worktree`,
which is why its `C-1 / N-16` and `N-21` sections report UNMEASURED. **The two `node_modules`
symlinks are untouched.** **Nothing merged, nothing pushed, no `git tag` in any form.**

#### U (2026-08-19) — two builds of one instrument under one name, and the half of the finding that `RB-P45`'s fix closed before this section was written

`eed8462` landed `RB-P45`'s attack, in a shape `RB-P45` did not ask for. This section files
what the prep probe found underneath it, amends `RB-P45` — once for a reframing that was
wrong and once for a prescription that was superseded — and amends `RB-P75` for a `Command.`
block that stopped reproducing at that same commit. **Every figure below was re-derived by
this unit at `eed8462`, and the ones handed to it that failed to reproduce are recorded as
findings rather than smoothed.** Nothing was installed and no `pip` was run; `~/.claude.json`,
`.mcp.json` and `~/.local/share/bantamkit/` were not modified; no live model call, no
`git tag`.

**Numbering, read at `eed8462` and carried from nowhere.** `RB-P74` is the reason the pattern
is digit-unbounded and the distinct count is printed beside the maximum, and `RB-P75` is the
reason it is read at a SHA rather than taken from a brief:

    grep -oE 'RB-P[0-9]+' docs/eval.md | sort -u | wc -l           ->  83 distinct
    ... | sed 's/RB-P//' | sort -nu | tail -1                      ->  ceiling 83
    ... the same sorted list diffed against `seq 1 83`             ->  no gaps
    grep -rhoE 'RB-P[0-9]+' over the whole tree | sort -nu | tail  ->  same ceiling, 83

83 distinct, ceiling `RB-P83`, no gaps — so the next free number is **`RB-P84`**, and this
section mints `RB-P84` and `RB-P85`. The brief this unit was handed named neither; it said to
read the register, which is the only instruction about a number this program has learned to
trust.

- **`RB-P84` — the same instrument name resolves to two different builds, both are spawned,
  and the advertised surface cannot tell them apart.** `bantamkit` is registered twice under
  one name: user scope (`~/.claude.json` → `/Users/kktest/.local/share/bantamkit/venv/bin/`
  `bantamkit-mcp`, a wheel install frozen at `0.13.0`, dist-info written 2026-08-10 15:50) and
  project scope (`<repo>/.mcp.json`, **tracked in git**, 112 bytes, 2026-08-10 15:47, relative
  command `.venv/bin/bantamkit-mcp`, an editable install whose `.pth` points at
  `runtime-py/src` and therefore serves live HEAD source). **Both are spawned.** This session's
  client (PID 90613, cwd = this repo) has had PIDs 90986 and 90987 alive since 2026-08-17
  16:29:59, and this unit's own process ancestry walks to that same 90613. The two builds
  expose a **byte-identical** protocol surface: a `tools/list` of six tools with descriptions
  and complete `inputSchema`s, plus the `instructions` block, serialize to **6864 identical
  bytes** on both, `diff` empty, measured over two real stdio `initialize` handshakes at this
  HEAD against throwaway stores. The one asset that differs, `contracts/default.yaml`, is not
  exposed by either resource template. **The only discriminating field is `serverInfo.version`,
  and it is invisible where it is needed** — the host reads it once at `initialize` and the
  tool-calling agent never sees it, so at the moment of a `memory_recall` there is nothing to
  read. **The only reliable discriminator is a defect:** at `k=1` the installed build returns
  at most one fact (`budget = k if k is not None else self.k`, in the installed tree's own
  `memory/component.py` and not in this repository's) while HEAD floors at the store default
  (`budget = self.k if k is None else max(k, self.k)`,
  `runtime-py/src/bantamkit/memory/component.py:128`, the `RB-P1` k-floor fix), with the cap
  re-checked per fact in both so layering cannot raise the total — and a live call in this project returning two facts at `k=1` is how the answering
  build was identified, not the version field. **Which scope wins is UNESTABLISHED in general
  and is deliberately left so:** `claude mcp list` prints the user-scope path on the resolved
  `bantamkit:` row while itself emitting `[Conflicting scopes]` and naming both endpoints; in
  *this* directory `.claude/settings.local.json` carries `"enabledMcpjsonServers":
  ["bantamkit"]` and `"enableAllProjectMcpServers": true`, which explains this directory and
  not the rule. **The loser is spawned regardless**, holds the same cwd, discovers the same
  project store, and is one config edit from becoming the winner; three other live client
  sessions on this machine, with cwds outside this repo
  (`.../oba-be-juristic-ma-ms`, `.../startbiz-ui`, `.../startbiz-api`), spawned **only** the
  user-scope `0.13.0` build, so the k-floor defect is live elsewhere right now. **Ordering
  constraint, stated as a finding and not taken as an action:** `claude mcp remove bantamkit -s
  project` edits a **tracked** file and, done before the user-scope venv is refreshed, hands
  this repo's orchestration to the stale build — so both builds are refreshed first and the
  collision resolved second, and both halves are the user's, not this unit's. **Why its own
  number rather than an amendment to `RB-P45`: neither fix closes the other** — `eed8462` made
  `_version()` a property of the checkout and the two builds remain equally indistinguishable
  and equally silently selected, while removing one registration would leave `_version()`
  exactly as truthful as it already is. **Attack:** make build identity readable over the wire
  and independent of both packaging metadata and the release cadence — a field carrying the
  resolved `assets_root()` and the package `__file__`, or the commit — so a caller can assert
  *which* build answered instead of inferring it from a bug; and treat a duplicate
  `mcpServers` name as a hard error at startup rather than a listing footnote. **Command.**
  `git ls-files .mcp.json` → tracked; `ps -eo pid,ppid,lstart,time,command | grep
  bantamkit-mcp` → five servers, two of them children of 90613; `lsof -a -p <ppid> -d cwd` per
  client; `claude mcp list` → `[Conflicting scopes]`; two stdio handshakes with
  `--store <throwaway>`, `tools` + `instructions` dumped key-sorted and `diff`ed → empty,
  `wc -c` → 6864 each. (Layer: configuration and process topology — **not** `mcpserver.py`,
  which is `RB-P45`'s layer and is why these are two entries.)

- **`RB-P85` — the wheel target force-includes a path outside the project root, so the sdist
  builds, is silently short of the asset pack, and the wheel built from it cannot be built at
  all.** `runtime-py/pyproject.toml:28-29` carries `[tool.hatch.build.targets.wheel.force-`
  `include]` → `"../assets" = "bantamkit/assets"`. `../assets` is outside the sdist root, so
  the two halves of `python -m build` disagree: `build_sdist` **succeeds** and produces
  `bantamkit-0.25.0.tar.gz` whose only `assets` entry is `src/bantamkit/assets.py` — the
  module, not the pack — and `build_wheel` **from the unpacked sdist** then dies with
  `FileNotFoundError: Forced include not found: <extract-parent>/assets`, the forced path
  having resolved out of the extracted tree entirely. A wheel built directly from the checkout
  is unaffected (`bantamkit-0.25.0-py3-none-any.whl`, built here), which is why nothing has
  ever seen this: CI runs `pip install -e "runtime-py[dev,mcp]"`
  (`.github/workflows/ci.yml:34`) and `docs/install.md`'s documented path is a `git+ssh` /
  `git+https` install that clones the whole repository, so `../assets` exists and the wheel is
  built in place. **Pre-existing and untouched by `eed8462`:** `git blame` puts both lines at
  `487221b8`, 2026-08-06, and `git show a4993d0:runtime-py/pyproject.toml` carries them
  verbatim. **It earns a number rather than a footnote because the failure is silent in the
  one direction that matters — the sdist is *produced*, not refused, and an artifact that
  builds clean while missing the pack the library documents as bundled is the same shape as
  every other entry in this register that exists because a gate could not see its own
  defect.** **NOT FIXED HERE, deliberately:** it is a packaging change with no bar behind it,
  and the bar is the interesting part — a node that asserts the pack is present in the built
  artifact, not one that asserts a TOML key. **Attack:** either give the sdist a root that
  contains `assets/` or stop force-including across it, and pin whichever with a check that
  reads the built artifact. **Command.** `hatchling.build.build_sdist` from `runtime-py/`
  → `bantamkit-0.25.0.tar.gz`, `tar tzf … | grep assets` → `src/bantamkit/assets.py` only;
  `hatchling.build.build_wheel` from the extracted sdist root → `FileNotFoundError: Forced
  include not found: …/assets`; the same call from `runtime-py/` →
  `bantamkit-0.25.0-py3-none-any.whl`; `git blame -L27,30 -- runtime-py/pyproject.toml` →
  `487221b8` 2026-08-06. (Layer: packaging.)

##### Amendment 1 to `RB-P45` — 2026-08-19: the misattribution was the brief's, the entry was right, and the prescribed attack was superseded by a stronger one

**`RB-P45` is a record and is not edited.** Three corrections, appended.

**1. The reframing that blamed the user-scope install was wrong, and the entry as filed was
right.** A brief escalated `RB-P45` to *"the server this program orchestrates through is a
frozen 9-day-old install, twelve minor versions behind main"* and read the `0.3.0` string as
what that install advertises. It does not. `RB-P45` says *"Measured in this repo's venv"* and
reports `bantamkit-0.3.0.dist-info`, and **both reproduce exactly**: the repo `.venv`'s
dist-info was written 2026-08-08 19:44 and never rewritten, while its `.pth` makes the code
track HEAD forever, so it ran today's source and reported a version from eleven days earlier.
The user-scope install truthfully reported its own `0.13.0` throughout. **The correction is
credited to the measurement and not to an argument** — it was produced by running both
interpreters and both handshakes, and the same brief that carried the escalation also carried
`grep -rn "0\.3\.0" runtime-py/ tools/` → no hits, which had already refuted the hardcoded-
string story it was resting on.

**2. Two figures in the entry have moved and are left standing.** It reads *"nineteen minor
releases"* and *"against `version = "0.22.0"`"*, both correct at the commit it was written at;
the tree declared `0.25.0` by `eed8462` and now declares it in a different file. Neither is
edited, and neither is load-bearing for the finding.

**3. The attack `RB-P45` prescribed was deliberately not built, and what replaced it is
strictly stronger.** The entry asks for *"a node that reads the version out of
`runtime-py/pyproject.toml` and requires `_version()` to equal it, skipped only when the
package is genuinely not installed,"* on the ground that *"that goes red on a stale install."*
**That is exactly why it was not built:** such a node's value is a function of when someone
last ran `pip`, not of the commit — the class this repository named for itself after two
parties quoted different correct pytest totals, and a gate whose colour a `pip install`
can flip is not a repo-content check. `eed8462` built three nodes whose every equality has
both sides read out of the tree, and the load-bearing one monkeypatches
`importlib.metadata.version` to answer `9.9.9-from-dist-info` and requires `_version()` to be
unmoved. **That node stays red under the regression on a fresh install too** — the case a
fresh-install CI structurally could not observe, and the case the prescribed node cannot
reach, because on a fresh install the prescribed node is green by construction. **An entry's
own proposed attack being superseded is recorded as such rather than quietly replaced**; the
supersession is on the mechanism, not on the finding, and `RB-P45`'s finding is closed by
`eed8462` in full.

**4. What `eed8462` closed, measured here rather than carried.** With the stale dist-info left
in place and no `pip` run: `.venv` dist-info is still `bantamkit-0.3.0.dist-info` and
`importlib.metadata.version("bantamkit")` still answers `0.3.0`, while
`bantamkit.__version__` and `mcpserver._version()` both answer `0.25.0`, and a real stdio
handshake against `.venv/bin/bantamkit-mcp` now returns
`{"name": "bantamkit", "version": "0.25.0"}`.

**5. One figure this section was handed that no longer reproduces, and it is `RB-P84`'s, not
`RB-P45`'s.** The finding filed as `RB-P84` was measured at `ba7a38b` with a fourth clause:
that the one discriminating field was **inverted**, the `0.13.0`-era build truthfully saying
`0.13.0` while the `0.25.0` build said `0.3.0`, ranking the newer build twelve minor versions
older. **That clause is dead at `eed8462`, killed by the fix in the entry above it**, and the
handshake measured for `RB-P84` is the evidence: `0.13.0` against `0.25.0`, correctly ordered.
It is not written into `RB-P84` as live, and two things are worth saying about its death
rather than dropping it. **First, a source fix does not restart a running server** — PID 90987
loaded `mcpserver` at 2026-08-17 16:29:59, and `eed8462` was committed 2026-08-19 23:27:51, so
that process serves the old `_version()` until the host restarts; this is derived from the two
timestamps and Python's import-time module loading, and is an inference, not a measurement.
**Second, the field is now truthful and still not a build identifier**, which is the durable
half: refresh the user-scope venv from HEAD and both builds read `0.25.0` while one is a
frozen wheel and the other an editable install that will drift forward with every commit until
the next bump, still reading `0.25.0`. **A declaration that moves only on release bumps cannot
identify a build**, which is why `RB-P84`'s attack asks for provenance and not for a version.

##### Amendment 1 to `RB-P75` — 2026-08-19: the `Command.` block no longer reproduces, and the finding it supports is untouched

**`docs/eval.md:6546`.** `RB-P75`'s `Command.` block records

      grep '^version' runtime-py/pyproject.toml                    ->  version = "0.25.0"

and at this HEAD that command **returns nothing and exits 1**: `eed8462` replaced the static
key with `dynamic = ["version"]` plus a `[tool.hatch.version]` source. **A verbatim command
block is a RECORD** — `docs/record-vs-pointer.md` §1 makes a `Command.` line a record by
default, since a provenance command is on none of P1-P4 — so this is an amendment and the
block above is not rewritten. **This is the third time a defect of `RB-P74`'s class — a
recorded derivation that does not reproduce — has been found inside the document that names
the class**, after the two provenance commands inside `RB-P72` corrected by amendment in
section S. The first line of the same block, `git show main:runtime-py/pyproject.toml | grep
'^version'` → `version = "0.24.0"`, still reproduces and is untouched; `main` has not moved.

**What does *not* break, and it is the whole point of the amendment.** `RB-P75`'s finding is
*an allocation register with two live writers and no allocation rule collides silently*, and
it names `pyproject.toml`'s `version` as one such register. **A dynamic version does not
refute that.** The register still exists, still has exactly two live writers, and still has no
allocation rule — it has **moved** to `runtime-py/src/bantamkit/__init__.py`, where two
branches both writing `__version__ = "0.26.0"` would merge as cleanly and as silently as two
branches both writing `version = "0.26.0"` did. `RB-P75`'s attack — *"`pyproject.toml` has no
equivalent and should carry one"* — is therefore not satisfied by `eed8462`, only relocated,
and the sentence that carries it should now be read against the new file. `RB-P84` is the
same shape one layer out: a declaration that only moves on a release bump, doing duty as an
identifier.

##### Gates at this commit

Read the commit column literally. The suite, both ruff surfaces and `amendguard` were measured
at `1dafef6` with this section's `docs/eval.md` edit present in the working tree; no gate below
reads `docs/eval.md`, and `test_field_programs.py` parametrises over `docs/eval-data/` only,
which adds no file here, so the totals cannot move on this commit. The suite total is also
read at `eed8462`, where it reproduces the figure W1 recorded.

<!-- provenance: value=1013 passed, 2 xfailed; commit=eed8462 and again at 1dafef6 plus this commit's working tree; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=All checks passed! on runtime-py and on docs/eval-data; commit=eed8462 and again at 1dafef6 plus this commit's working tree; command=.venv/bin/ruff check runtime-py && .venv/bin/ruff check docs/eval-data -->
<!-- provenance: value=SUMMARY rows=0 ok=0 red=0 broken=0 merges=0 unmeasured=1, rc 3, over a4993d0..HEAD before this section existed; commit=1dafef6; command=.venv/bin/python tools/amendguard/amendguard.py check . a4993d0..HEAD tools/amendguard/ledger.json -->

| gate | value | commit | command |
|---|---|---|---|
| suite | **1013 passed, 2 xfailed** | `eed8462`, re-read at `1dafef6` + this tree | `.venv/bin/python -m pytest runtime-py/tests -q` |
| ruff, `runtime-py` | **All checks passed!** | `eed8462`, re-read at `1dafef6` + this tree | `.venv/bin/ruff check runtime-py` |
| ruff, `docs/eval-data` | **All checks passed!** | `eed8462`, re-read at `1dafef6` + this tree | `.venv/bin/ruff check docs/eval-data` |
| amendguard | **`unmeasured=1`, rc 3** | `a4993d0..1dafef6` | `.venv/bin/python tools/amendguard/amendguard.py check . a4993d0..HEAD tools/amendguard/ledger.json` |

**The `unmeasured=1` reading is evidence, not an absence of one.** Over `a4993d0..1dafef6` the
ledger's amend-only patterns match no changed path, because the only documentation commit in
that range is the `docs/install.md` correction — and `docs/install.md` is not in the ledger.
That is the machine-readable half of this section's classification of that file: the
record-vs-pointer rule does not judge it, and `amendguard` says so rather than passing quietly
(`RB-P51`). The same command over the range that includes **this** commit reads one row against
`docs/eval.md`, classified `insert` — this section is spliced above the file's closing
line rather than after it — with 237 lines added and none deleted.

##### Fences held by this section

**One layer, one file: `docs/eval.md`** — no `.py`, no `.jsonl`, nothing under `runtime-py/`,
and the `docs/install.md` correction is a separate commit touching that one path and nothing
else. **`RB-P45`, `RB-P74`, `RB-P75` and every entry of sections P through T are untouched**;
all four corrections above are appended. **Nothing under `~/.local/share/bantamkit/` was
written**, both handshakes ran against throwaway stores in a scratch directory, and no
`mcp__bantamkit__*` tool was called by this unit. **`~/.claude.json` and `.mcp.json` are
unmodified**, and the scope collision is **not** resolved here — that is the user's action and
it has an ordering constraint attached (`RB-P84`). **No `pip install` of any kind**, so the
stale dist-info that makes `RB-P45` visible is still in place and every gate above was measured
against it. **Nothing merged, nothing pushed, no `git tag` in any form.**

#### V (2026-08-20) — J10's paged document reader: the claim held, the falsifier fired on the stratum §3.1 wrote in so that it could, and the verdict is REFUTED

**RB-P86 · The reader recovers what a truncated paste cannot see — `0/36 → 15/36` on the
outside-the-cut stratum, Δ = +0.4167, McNemar exact two-sided p = 0.000061 — and it costs
competence on the rows the paste can already see: `32/36 → 22/36`, Δ = −0.2778, p = 0.006348.
Both halves are the same run. The bar's own falsifier §5.2 R3 fires on the second, so the
VERDICT is REFUTED and `reader` does not enter `CONFIGS`.**

The bar is `docs/eval-data/2026-08-20-document-read-bar.md` (pre-registered at `6271f43`,
Amendment 1 at `901b414`, written before any graded arm ran). X6 ran **all 432 declared
runs**, none dropped, no `.jsonl` edited after writing: `93c2f32` (4b), `c388786` (7b),
`8c0f648` (14b), `4f7efeb` (3b), `2749b70` (the 432 transcripts, because U-2 and U-5 are only
decidable from them). **Every figure below was re-derived by this unit from those committed
rows and transcripts before being written here**, and §V.5 records the one clause of the
handoff that did not survive that re-derivation.

##### V.0 The register was read at HEAD, and the number this branch shows is not the free one

`feat/document-readers` branched at `8689ac6` and has never merged `main`. Reading its own
`docs/eval.md` gives ceiling `RB-P76` and would mint `RB-P77` — **which is already taken, nine
times over, on branches that are live right now.** Read across every live writer instead, which
is what `RB-P75` says a shared allocation register with no single writer requires:

<!-- provenance: value=ceiling RB-P85 on feat/version-truth, RB-P83 on main, RB-P76 on this branch; commit=2749b70; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

    this branch (2749b70)   grep -oE 'RB-P[0-9]+' docs/eval.md | sed 's/RB-P//' | sort -n | tail -1   ->  76
    main       (a4993d0)    git show main:docs/eval.md            | ... same pipeline           ->  83
    feat/version-truth (4b5723d)                                    ... same pipeline           ->  85
    max over all 22 refs/heads                                                                  ->  85

Digit-unbounded pattern, per `RB-P74`. **`RB-P86` is the next free number and this section mints
`RB-P86`, `RB-P87` and `RB-P88`.** Section letters are the same register with the same hazard:
`S`, `T` and `U` exist on `feat/version-truth` and `main`, so this is **section V**, not
section S. `RB-P75`'s rule is applied as written — *skipping costs a visible gap if the other
branch is abandoned, colliding costs a silent one* — so `RB-P77 … RB-P85` are deliberately
absent from this branch's file and are not a truncated read.

##### V.1 The result

`n = 12` per (tier, arm, stratum) cell; 3 arms × 3 strata × 4 tiers × (3 tasks × 4 repeats).

<!-- provenance: value="the pass table and the three McNemar rows below"; commit=2749b70; command=python over docs/eval-data/2026-08-20-document-read-{4b,7b,14b,3b}.jsonl, grouped by (config, stratum), matched on (task, repeat) within tier -->

| tier | `bare` / `paste` / `reader`, small | large-IN | large-OUT |
|---|---|---|---|
| 4b | 0 / 12 / 2 | 0 / 12 / 11 | 0 / 0 / **11** |
| 7b | 0 / 12 / 9 | 0 / 8 / 3 | 0 / 0 / 1 |
| 14b | 0 / 12 / 6 | 0 / 12 / 8 | 0 / 0 / 3 |
| 3b (declared floor, never pooled) | 0 / 2 / 0 | 0 / 4 / 0 | 0 / 0 / 0 |

**McNemar exact, two-sided, hand-rolled from `math.comb` per §9, pooled over the three compared
tiers, paired on `(task, repeat)` within a tier** — `b` = reader passed and paste failed, `c` =
the reverse:

| stratum | `P(paste)` | `P(reader)` | Δ | `b` | `c` | n | p |
|---|---|---|---:|---:|---:|---:|---|
| small | 36/36 = 1.0000 | 17/36 = 0.4722 | −0.5278 | 0 | 19 | 19 | 0.000004 |
| large-IN | 32/36 = 0.8889 | 22/36 = 0.6111 | −0.2778 | 1 | 11 | 12 | **0.006348** |
| large-OUT | 0/36 = 0.0000 | 15/36 = 0.4167 | **+0.4167** | **15** | 0 | 15 | **0.000061** |

**VERDICT: REFUTED, by §5.2's R3, and R3 is the only clause of the four that fires.**
`P(reader, large-IN) = 0.6111` is below `P(paste, large-IN) − 0.10 = 0.7889` with p = 0.006348.
§5.2 makes any one clause sufficient. R1 does not fire (Δ on large-OUT is +0.4167, not < 0.10);
R2 does not fire (p = 0.000061); R4 does not fire (`P(reader, small) − P(reader, large-OUT)` =
0.4722 − 0.4167 = **0.0556**, nowhere near 0.50). **CONFIRMED is simultaneously unavailable
because §5.1 requires C1∧C2∧C3 and C2 fails on the same inequality R3 fires on.** C1 holds
(Δ = +0.4167 ≥ 0.30, p < 0.05) and C3 holds (`document_list` successfully called in 12/12,
12/12 and 11/12 of the large-OUT reader cells, all ≥ 50%). **`reader` stays calibration-only in
`CONFIG_CHOICES` and does not enter `CONFIGS`.** §7.6 pre-registered that even a CONFIRMED
result would only have been a *recommendation* to promote, ruled by the user and never
automatic; REFUTED removes the recommendation and changes nothing about who decides.

The instrument checks out against the bar's own pre-registered MDE table (§9): re-derived here,
10-of-12 → p = 0.0386 and 9-of-12 → p = 0.1460; 25-of-36 → p = 0.0288 and 24-of-36 → p = 0.0652.
All four reproduce to the digit.

##### V.2 What this entry must not be read as, in either direction

**This is not a null result, and writing it as one would be false.** On the stratum where the
paste is incomplete **by construction** — the answer row is outside the 8,621 B cut, so the
paste arm's ceiling there is zero and stays zero, 0/36 at every tier — the reader goes to 15/36
at p = 0.000061. **The job's own claim held.** The reader does recover what truncation loses.

**And it is not a confirmation.** The falsifier fired on **large-IN**, the stratum §3.1 wrote
into the design *precisely so that the experiment could lose*: *"this is the cell that can
refute the reader — if the reader loses on rows a paste can see, the tool costs competence
rather than buying it. Without this stratum the experiment cannot lose."* It lost there, at
n = 12 discordant, 11 of 12 the paste's way.

**Both sentences are the same measurement:** *the reader recovers what the paste cannot see, and
costs competence where the paste can already see it.* A tool that makes a model worse on
material it already had is not a tool you switch on by default, and the bar said that in
advance rather than after seeing which way it went.

##### V.3 Three things that make the result honest, and none of them is a footnote

**1. The reader's wins on large-OUT are arithmetic on the key column, not paging — and that
caps what +0.4167 means.** The corpus's `sku` is a pure function of the row index
(`SKU-004137` is data row 4137), so the target's offset is *computable* from the manifest
rather than searchable. Measured over the 15 passing large-OUT reader runs:

<!-- provenance: value=14 of 15 large-OUT passes read within one row of the target, 11 of 11 at the 4b in a single document_read; commit=2749b70; command=python over docs/eval-data/2026-08-20-document-read-transcripts-*/reader--doc-large-out-*.json, collecting every document_read offset -->

- **14 of the 15** passes include a `document_read` whose `offset` lands **within one row** of
  the target; the fifteenth lands 2 rows short, still inside the 50-row page.
- **All 11 of the 4b's passes are a single `document_read` and nothing else** — `offset=4136`,
  `offset=8021`, `offset=11763`/`11764`. One call, straight to the row.

§7.4 already declined to generalise past a generated corpus with *"a key column that is a pure
function of the row index"*. **This run is direct evidence for that disclaimer, measured rather
than assumed.** On a workbook whose key is not that function, the mechanism demonstrated here —
compute the offset, read once — does not exist, and nothing in this result says what a reader
would do there.

**2. The small-cell failures are fabrication, not truncation, and the manifest is the source.**
The small paste is COMPLETE (§1.4) and scores 36/36; the reader scores 17/36 on the same rows.
The failure mode is not a missing row. In `reader--doc-small-261--r1` at the 4b the model called
`document_list`, was shown the manifest's three sample rows —

    row 0 is the header: sku	region	units
    row 1 is the first data row: SKU-000001	south	2049
    row 400 is the last data row: SKU-000400	east	2621

— then read rows 1–50 (which do not contain row 261) and answered `{"region": "south",
"units": 2621}`. The expected answer is `south` / **3788**. **`2621` is row 400's `units`,
printed in `document_list`'s own manifest.** The tool showed it a row and it answered with that
row. Those three sample rows exist to make the offset computable — they are the reason honesty
item 1 works at all — and **this is the cost side of that same design choice**, a contract
finding about the manifest, not a paging failure.

**3. `7b/large-OUT` is UNINFORMATIVE, and the sensitivity is reported here rather than left for
a reader to ask for.** U-1 fires on that cell at **8/12** `turns-exhausted` (≥ 50%). §6.2's
run-level rule needs the large-OUT stratum UNINFORMATIVE at **≥ 2 of 3** compared tiers and does
not fire at 1 of 3, so the run is not UNINFORMATIVE as a whole. Excluding that cell:
**Δ(large-OUT) = +0.5833, b = 14, c = 0, n = 14, p = 0.000122** — larger, not smaller. C1 holds
either way, and R3 does not live on that stratum.

##### V.4 The clauses, each with its number

- **V-1 did not fire at any compared tier.** G-3's six readings at the amended
  `PASTE_MAX_BYTES = 8,621` (bar §A.3, request reading) are **6,602 / 6,623 / 6,623 / 6,627 /
  6,648 / 6,648** against the **6,963** threshold — worst reading 6,648, a margin of 315 tokens
  (4.52%). The `paste` arm is comparable at 4b, 7b and 14b.
- **V-3 is zero: 0 of 144 `bare` passes across all four tiers.** At 1 in 36,000 per run, the
  contamination detector §1.2 built stayed silent — which is what a working detector looks like,
  and is why no task is voided for any arm.
- **V-2 and V-4 are zero.** No `DocumentSetupError` escaped; **0 rows** carry
  `outcome == "transport-error"` across all 432. No row was re-run and no row was replaced.
- **U-5 is 0/12 in all nine compared cells.** Amendment 1's `select_declared_arguments` /
  `handler_accepts` fix — landed *before* the sweep on smoke evidence — held under all
  **108 compared `reader` runs**. That is the strongest single piece of evidence that amending the bar before the run,
  rather than adjusting after it, was the right call.
- **U-2 (amended) does not fire at any compared tier**: successful `document_list` calls run
  12/12, 12/12, 12/12, 12/12, 12/12, 12/12, 12/12, 12/12 and 11/12 over the nine reader cells.
- **U-3 fires once, at `3b`/large-OUT** (all three arms at zero). The 3b is a declared floor and
  is never pooled, so this costs nothing the bar claims — recorded so it is not discovered later.

##### V.5 What did NOT reproduce — the handoff's robustness clause, and it is the one clause the verdict leans on

The handoff to this unit asserted: *"the verdict is unchanged either way, **because R3 lives on
`large-IN` where no compared cell is UNINFORMATIVE**."* **The second half does not reproduce.**

<!-- provenance: value=7b/reader/large-IN is malformed-output on 4 of 12 runs = 33.3%, above U-4's 30% threshold; commit=2749b70; command=python over docs/eval-data/2026-08-20-document-read-7b.jsonl counting outcome in {malformed-output, schema-exhausted} among config==reader rows of the large-IN stratum -->

`7b`/`reader`/`large-IN` has **4 of 12 runs at `outcome == "malformed-output"` = 33.3%**, and
§6.1's **U-4** makes a cell UNINFORMATIVE at **> 30%**. Under §6.1's own scoping sentence —
*"evaluated per (tier, arm, stratum) cell"* — the denominator is that cell's 12 runs and **U-4
fires**. It is the only compared cell besides `7b`/large-OUT that any UNINFORMATIVE predicate
touches, and it sits on the stratum the verdict rests on.

**What it costs, stated as arithmetic rather than as reassurance.** Dropping the 7b from the
large-IN pool the way honesty item 3 drops it from large-OUT: reader 19/24 = 0.7917, paste
24/24 = 1.0000, so R3's **inequality still holds** (0.7917 < 0.90) but its **McNemar p becomes
0.0625**, which is **not < 0.05**. R3 as pre-registered would then not fire, and with R1, R2 and
R4 all silent the run would land in §5.3's NEITHER band rather than at REFUTED.

**The verdict stands as REFUTED, and the reason is textual, not statistical.** §5 defines
`P(arm, stratum)` as the pooled rate over the three compared tiers at n = 36 and states no
exclusion for an UNINFORMATIVE cell; §6.2 escalates to a run-level verdict only from
**large-OUT**; and **R3, unlike R2, carries no non-UNINFORMATIVE proviso** — R2's *"with a
non-UNINFORMATIVE cell"* is the bar demonstrating it knew how to write that condition where it
wanted one. The bar as pre-registered is applied as written and is not edited to say otherwise.
But **"the verdict is robust to the UNINFORMATIVE cells" is false and this entry does not say
it**: the refutation depends on the 7b's contribution to the large-IN pool, and that is
`RB-P88` below.

Everything else in the handoff reproduced exactly: all twelve cells of the pass table, all three
pooled McNemar rows to six decimals, the R3 inequality, the 0/144 `bare` passes, the
0/12 U-5 readings, the six G-3 numbers, the 13 dict-argument observations, the 4b's one-shot
`offset=4136` solve, `units: 2621` in `reader--doc-small-261--r1`, and the four MDE figures.

##### V.6 The cost axis, stated separately and never netted

§0.3 and §4 pre-register that capability and cost are reported side by side and **never divided
into a ratio**. Median `context_bytes_sent` per (tier, arm, stratum), in bytes:

<!-- provenance: value="the median context_bytes_sent table below"; commit=2749b70; command=statistics.median over context_bytes_sent in the four committed jsonl, grouped by (config, stratum) -->

| tier | arm | small | large-IN | large-OUT |
|---|---|---:|---:|---:|
| all | `bare` | 414 | 414 | 414 |
| all | `paste` | 10,620 | 10,674 | 10,674 |
| 4b | `reader` | **8,325** | **8,371** | **8,430** |
| 7b | `reader` | 18,148 | 28,491 | **39,351** |
| 14b | `reader` | 10,976 | 18,338 | 29,559 |

The `paste` arm is **one model call** on all 144 of its rows and **zero tool calls**, exactly as
§10.2 clause 5 requires, so its figure is identical at all four tiers. Stated separately and
never netted, as the bar requires: **the reader's roster share is 1,414 B × `model_calls`** —
4,242 B at the 4b (median 3 calls) rising to **14,140 B at 7b large-OUT**, where the median
run spends the entire 10-turn budget — and **the paste's corpus share is 8,621 B × 1**.

**The reader is cheaper than the paste only at the 4b** (0.78–0.79×). At the 14b it is 1.03× on
small and 2.77× on large-OUT; at **7b large-OUT it costs 3.69× the paste** — the tier and
stratum where it also scores 1/12. The one cell where the reader is both cheaper *and* better is
`4b`/large-OUT: 8,430 B against 10,674 B, 11/12 against 0/12.

##### V.7 What is NOT claimed

§7's ten items are the list and are not replaced here. What this run adds to them:

1. **Not claimed: that the reader is useless.** C1 held at p = 0.000061. REFUTED is a verdict
   on the pair *as a default*, delivered by R3, and not a finding that the mechanism does
   nothing.
2. **Not claimed: that the reader is safe to default on.** C2 failed on the same inequality.
3. **Not claimed: any of this about real workbooks.** §7.4, now with the measurement behind it
   in §V.3 item 1: the wins run through the key column being a pure function of the row index.
4. **Not claimed: a tier comparison.** §7.5 stands — `run_seed` hashes the model name, the tiers
   are unpaired, and every cross-tier sentence above is descriptive. The *within-tier* pairing on
   `(task, repeat)` that McNemar uses is the one §9 pre-registered and is unaffected.
5. **Not claimed: that a 3b failure is a reader defect** (§7.8) — but see `RB-P86`, which is a
   defect the 3b **exposed** rather than a defect of the 3b.
6. **Not claimed: that this verdict is robust to §6's own UNINFORMATIVE predicates.** §V.5.
7. **Not claimed: anything about `.docx`, `.pptx`, PDF or video** (§7.2). Nine `.xlsx` LOOKUP
   tasks over two generated corpora is the entire evidence base.

##### V.8 Minted here — `RB-P86`, `RB-P87`, `RB-P88`

- **`RB-P86` — a live argument-shape defect that survives `select_declared_arguments`, because
  that filter drops UNDECLARED keys and never type-checks DECLARED ones.** All three `3b`
  `reader` cells are UNINFORMATIVE with **U-5 at 4/12, 4/12 and 5/12** — **13 observations** of
  `error: document_read failed: unhashable type: 'dict'. fix the arguments and retry.`, all 13
  on `document_read`. The 3b emits a **JSON-Schema fragment as the value of a declared
  parameter**, e.g. `{"document": {"description": "stock", "type": "string"}}`; `document` **is**
  declared, so Amendment 1's filter passes it straight through, and it reaches `docs.get(name)`
  in `_document_tools` (`evalrun.py`) where a dict is not hashable. **This is the same class as
  the defect Amendment 1 fixed, one layer in:** Amendment 1 stopped an *undeclared* key from
  crashing a handler; nothing stops a *declared* key of the wrong type from doing it.
  The 3b also fires the amended **U-2** in the same three cells (successful `document_list` in
  **0/12, 1/12, 1/12**), so the floor's reader arm measured the dispatcher, not the model.
  **NOT FIXED HERE, and the reason is layer discipline, not effort:** a Layer-1 change to
  `agent.py` after 432 graded rows exist would change the instrument under a committed result,
  and the only cells affected are the declared floor's, which §7.8 already declines to read.
  **Filed.** The fix has an obvious shape — coerce or reject a declared argument whose value
  does not match its declared `type`, in the same top-level-only scope as `coerce_arguments` —
  and it belongs to the layer, not to this job.
- **`RB-P87` — V-1's threshold is an absolute token count derived from one assumed window, so at
  a tier served a SMALLER window the clamped reading falls BELOW the threshold and the guard
  reports OK exactly where the truncation is worst.** §6.4 named the 3b's served window
  UNMEASURED. Measured now, with G-3's own instrument:

  <!-- provenance: value=llama3.2:3b prompt_eval_count = 4096 on both readings for both corpora at PASTE_MAX_BYTES=8621; commit=2749b70; command=POST /api/generate {"model":"llama3.2:3b","prompt":<_paste_head(fixtures)[+task prompt]>,"stream":false,"options":{"num_predict":1}} -> prompt_eval_count, run 2026-08-20 in this worktree -->

      llama3.2:3b  small corpus  system 8,962 B -> 4096   system+task 9,324 B -> 4096
      llama3.2:3b  large corpus  system 9,016 B -> 4096   system+task 9,378 B -> 4096

  **Exactly 4,096 on both counters for both corpora** — the `RB-P53` clamp signature, on the
  `/api/generate` counter the bar trusts, at a daemon-default window of 4,096. **The clamp
  itself is `RB-P53`'s class and gets no number here**, by the same rule that cross-referenced
  J7's `N-1` rather than splitting one class across two entries. What is new is the **guard**:
  V-1 fires at `≥ 0.85 × 8,192 = 6,963`, and 4,096 < 6,963, so **V-1 as written does not fire
  and the 3b's `paste` arm is not VOID by the rule** — even though its prompt is being truncated
  harder than any arm the rule did VOID. A threshold that is 85% of *an* assumed window is
  silently inapplicable at any tier served a different one; the predicate has to be a function
  of the window it is evaluated against, or it has to refuse to evaluate where that window is
  unknown. **The result is protected by a different sentence, not by V-1:** §6.4 already forbids
  comparing any 3b `paste` number to another tier's, so the 3b's **6 paste passes** (2 small,
  4 large-IN, 0 large-OUT) are uncompared and no figure in §V.1's compared pool depends on them.
  **Filed as a rule defect. Nothing in the bar is edited; it is committed evidence now.**
- **`RB-P88` — an UNINFORMATIVE predicate whose denominator is ambiguous fires on the one cell a
  verdict's significance rests on, and the ambiguity is inside the section that defines the
  predicate.** §6.1 opens *"evaluated per (tier, arm, stratum) cell"*, which makes U-4's *"> 30%
  of runs in the cell"* a fraction of that cell's 12 runs — and `7b`/`reader`/`large-IN` is
  **4/12 = 33.3%**, so U-4 fires. But §6.1's own **U-3** is written as
  `P(reader) = P(paste) = P(bare) = 0` **"in the cell"**, which requires *"cell"* to span all
  three arms — and under that reading U-4's denominator is 36, the fraction is 11.1%, and U-4
  does not fire. **One word carries two readings inside one subsection, and which one is meant
  decides whether the cell that supplies R3's significance is admissible.** Measured cost of the
  disagreement, §V.5: with the 7b in, R3 fires at p = 0.006348 and the run is REFUTED; with it
  out, p = 0.0625 and the run is §5.3 NEITHER. The bar's *other* rules are not ambiguous this
  way — U-1 and U-2 both say *"of `reader`-arm runs in the cell"* and V-3 says *"that task for
  every arm"* — so this is a single under-specified predicate, not a systemic one, and it is the
  kind that only shows up when it lands on the deciding cell. **Attack:** an UNINFORMATIVE
  predicate must name its own denominator in its own sentence, and a criterion clause must state
  whether it admits UNINFORMATIVE cells — §5.2's **R2 does** (*"with a non-UNINFORMATIVE cell"*)
  and **R3 does not**, which is what leaves the verdict resting on a reading rather than on a
  rule. Found by re-derivation, not handed to this unit; the handoff asserted the opposite.

##### V.9 Gates

<!-- provenance: value=1206 passed, 2 xfailed; commit=2749b70; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests -q -->

    PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests -q
        ->  1206 passed, 2 xfailed        at 2749b70, unchanged by this section
    .venv/bin/ruff check runtime-py       ->  All checks passed!
    .venv/bin/ruff check docs/eval-data   ->  All checks passed!

The `PYTHONPATH` prefix is not decoration: the editable install resolves `bantamkit` to the
main checkout, so a worktree gate run without it measures a different tree. Verified rather
than assumed — `bantamkit.__file__` printed from under this prefix resolves inside this
worktree. **This section adds no `.py` and no `.jsonl`; the count is the baseline count and is
quoted with the commit it was measured at, per the rule `amendguard` was built to enforce and
this job's own invariant.** `amendguard check . 8689ac6..HEAD tools/amendguard/ledger.json` reports **`rows=3 ok=2 red=1`**
over this branch. **The one red row is `6271f43`'s**, and it is the bar's own §10.3 quoting its
checker's node count with no provenance stamp beside it:

<!-- provenance: value=45 passed; commit=0b95d3f; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests/test_document_tasks.py -q -->

    PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests/test_document_tasks.py -q
        ->  45 passed        re-measured here, unmoved from the bar's reading at 6271f43

The number is real and re-measured; **the bar is not edited to carry the stamp, because it is
committed evidence and nothing is retro-edited to make a checker green** — the same refusal
recorded when `amendguard` first ran red over its own branch. The stamp lives here, in the
record that quotes the number, which is where a stamp is allowed to be added.

#### W (2026-08-20) — `RB-P86` goes from filed to fixed inside the same shift, the second time tonight; and the giving-up figure this unit was handed is not the one the transcripts carry

`RB-P86` was minted in **§V.8 above**, hours ago in this same shift, and filed **NOT FIXED HERE**
— *"a Layer-1 change to `agent.py` after 432 graded rows exist would change the instrument under
a committed result."* `c2cfb89` is that fix. **Section T is the first entry in this program to go
from filed to fixed inside one shift** (`RB-P79`, seventeen minutes); **this is the second**, and
the amendment below is written to be read straight after `RB-P86` itself and repeats none of it.
**`RB-P86` is a record and is not edited.** No `.jsonl` was regenerated and no committed row is
restated. Every figure below was re-derived by this unit in its own scripts rather than carried
from `c2cfb89`'s message; **three figures this unit was handed did not survive that, and they are
in §W.5** — including the one the handoff told it to correct, which needed correcting again.

##### W.1 Amendment 1 to `RB-P86` — 2026-08-20, the fix, and what the model now reads

**What landed.** `mistyped_arguments(arguments, parameters)` in `agent.py` returns the DECLARED
arguments whose value does not match their declared JSON-Schema `type`, as
`(argument, declared, sent)` triples; `_dispatch` calls it after `coerce_arguments` and
`select_declared_arguments` and returns before the handler. The sentence is the asset's
(`assets/contracts/default.yaml`, `tool_argument_types` and `tool_argument_type`), rendered by
`contract.py`. **The whole of the fix is which vocabulary the answer is written in.** `RB-P86`'s
defect was not that a dict reached a hash lookup; it was that the model was answered in Python.
`json_type_of` therefore names a sent value in the schema's own seven words — a dict is
`object`, never `dict` — because a model holding a JSON-Schema `document_read` has no referent
for `dict` and has one for `object`.

Re-derived here by replaying the payload out of the committed transcript rather than
transcribing it, through a real `Agent` on `_document_tools` over the committed
`doc-large-out-4137` corpus with the committed `assets/tools/document_read.json` schema, with
only `agent.py`, `contract.py` and `default.yaml` differing between the two runs:

<!-- provenance: value=reader--doc-small-261--r1 sent {"document": {"description": " workbook", "type": "string"}}; BEFORE at 39f7aaf reads `error: document_read failed: unhashable type: 'dict'. fix the arguments and retry.`; AFTER at c2cfb89 reads `error: document_read was called with the wrong type of argument. document must be type string, not type object. fix the arguments and retry.`; commit=c2cfb89; command=a Z2 replay script over `git archive 39f7aaf` vs the working tree, PYTHONPATH and BANTAMKIT_ASSETS pointed at the matching tree, payload read from docs/eval-data/2026-08-20-document-read-transcripts-3b/reader--doc-small-261--r1.json -->

    sent    {"document": {"description": " workbook", "type": "string"}}
    before  error: document_read failed: unhashable type: 'dict'. fix the arguments and retry.
    after   error: document_read was called with the wrong type of argument. document must be
            type string, not type object. fix the arguments and retry.

The `before` line is byte-identical to what that run's transcript records the model reading, so
the replay is a replay and not a reconstruction. **One frame carries one problem or many**:
`reader--doc-large-out-11764--r2` sent four wrong-typed declared arguments at once and reads one
sentence naming `document`, `limit`, `offset` and `part`, because the count is not the thing the
model has to act on.

##### W.2 The before/after over all 13 real payloads

Every `document_read` call that produced one of `RB-P86`'s 13 observations, read out of the
committed transcripts and replayed through the same real `Agent`. The only difference between
the two runs is which commit the three source files come from:

<!-- provenance: value=13 payloads replayed each way; BEFORE at 39f7aaf 13 of 13 observations carry Python text; AFTER at c2cfb89 0 of 13; commit=c2cfb89; command=Z2 replay script, PYTHONPATH=<tree>/runtime-py/src BANTAMKIT_ASSETS=<tree>/assets, markers searched: unhashable type, <locals>, TypeError, KeyError, Traceback, 'dict', 'list', 'str', 'int', NoneType, object is not -->

    BEFORE (39f7aaf)    13 payloads replayed    13 observations carry a Python exception's text
    AFTER  (c2cfb89)    13 payloads replayed     0 observations carry a Python exception's text

The denominator is re-derived and not quoted: **13 observations of that error string, in 13
distinct transcript files, one each, every one of them on `document_read`**, and **0 of the 13
runs passed**.

<!-- provenance: value=13 files under docs/eval-data/2026-08-20-document-read-transcripts-3b contain exactly one `error: document_read failed: unhashable type: 'dict'. fix the arguments and retry.` tool message each, all in the reader arm, all on document_read; passed=false in all 13; outcome wrong-answer 9, malformed-output 4; commit=c2cfb89; command=a Z2 python census over the 108 committed 3b transcripts, matching the tool-role message content exactly and resolving each observation back to the assistant tool_call carrying its tool_call_id -->

##### W.3 Reported — not coerced, and not dropped

**Dropping is right for an UNDECLARED key and wrong here, and the asymmetry is the argument.**
An undeclared key is one the tool has no way to act on, so there is nothing to negotiate. A
declared one is named by the schema, so dropping it hands the model the handler's default *as
though it had asked for it* — a model that asked for `offset` as an object would be given page 0
and never told the question had changed. This repository already refuses that shape;
`document_offset_past_end` exists because an empty page is a dead end a model cannot tell from a
real one.

**`coerce_arguments` is untouched and runs first**, so the one unambiguous conversion a small
model needs survives and is never reported. Re-derived against the committed
`document_read` schema:

<!-- provenance: value=after coerce+select, {"offset": "4137"} -> {"offset": 4137} mistyped []; {"limit": "50"} -> {"limit": 50} mistyped []; {"offset": "0"} -> {"offset": 0} mistyped []; {"offset": 4137.0} mistyped [(offset, integer, number)]; {"limit": true} mistyped [(limit, integer, boolean)]; {"part": 0} mistyped [(part, string, integer)]; {"document": null, "limit": null} mistyped []; {"document": {"type": "string"}} mistyped [(document, string, object)]; {"document_list": {...}} -> {} mistyped []; commit=c2cfb89; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python over coerce_arguments then select_declared_arguments then mistyped_arguments with load_tool('document_read').parameters -->

    "4137" for a declared integer   ->  4137          reported: no
    "50"   for a declared integer   ->  50            reported: no
    4137.0 for a declared integer   ->  4137.0        reported: offset must be type integer
    true   for a declared integer   ->  true          reported: limit must be type integer
    0      for a declared string    ->  0             reported: part must be type string
    an undeclared key of any type   ->  dropped       reported: no, it is gone before the check

The last row is the one that matters for `RB-P86`'s neighbour: **`select_declared_arguments` is
not weakened.** An undeclared key is dropped before the type check can see it, so it is never
reported, and U-5's 0/12 in all nine compared cells is untouched behaviour.

**`null` is exempt**, as the wire spelling of "omitted" — every handler here defaults its
arguments to `None`. The figure this unit was handed for how often the 13 real payloads exercise
that exemption does not reproduce; the reproducible readings are in §W.5.

##### W.4 The vacuity work, which is the transferable part

**Six mutants, six deaths**, re-derived by this unit in a throwaway `git archive c2cfb89` tree
rather than read from `c2cfb89`'s message. Counts are NEW red nodes against that tree's own
baseline, and the tree was restored and re-measured identical afterwards:

<!-- provenance: value=M1 6 new red, M2 7, M3 5, M4 1, M5 4, M6 4, and an M5 variant reworded on the other contract string 5; baseline and restored runs identical in their failure sets; commit=c2cfb89; command=a Z2 mutation script over a `git archive c2cfb89` tree, each mutant applied by exact-anchor string replacement and reverted in a finally block, .venv/bin/python -m pytest runtime-py/tests -q -p no:randomly under PYTHONPATH and BANTAMKIT_ASSETS pointed at that tree -->

    M1  the type check removed (mistyped_arguments returns [])              6 nodes
    M2  the dispatcher DROPS the wrong-typed argument instead of reporting  7 nodes
    M3  the check runs BEFORE coerce_arguments ("4137" reported)            5 nodes
    M4  null no longer exempt                                              1 node
    M5  the contract FRAME reworded in the asset                           4 nodes
    M6  select_declared_arguments weakened to pass undeclared keys         4 nodes

The baseline of that throwaway tree is not the repository's: **10 nodes fail there and all 10
are in `test_criticreplay.py`**, which resolves paths against a real git checkout and cannot see
one in a `tar -x` copy. They are in the baseline set and subtract out of every column; no
mutant's column contains one.

**The property node stays green under M5, and that is the design, not a gap.** `M5` is a Layer-2
rewording; `test_no_dispatch_observation_can_carry_a_python_exception_for_a_declared_argument`
asserts only that no Python text reaches the model and that each offending argument is named, so
a reworded sentence must not redden it. Every node that *does* redden under M5 says why in its
own name: three carry `verbatim`, and the fourth is the byte golden
`test_layers.py::test_tool_argument_types_bytes`.

**Z1 caught its own node reddening for a reason its name did not state, and rewrote it before
the commit rather than after.** The node had been drafted asserting the sentence's *frame*, which
would have made it red on a rewording that leaks no Python at all. **That is the third time in
this shift the laundering lesson has been applied ahead of a commit rather than discovered
behind one**, and the count is checkable rather than asserted: the lesson is born in section S
(a third `M11` case written, measured and deleted — *"a check that reddens for a reason its name
does not state launders unrelated mutations into its own column"*, `docs/eval.md:7665`),
promoted to a procedure in section T and applied to `M12` before `9b9ad0c` (`docs/eval.md:7826`),
and applied again here before `c2cfb89`. Those are the only two committed sites of the sentence
in any live branch's `docs/eval.md`. **It is this program's standing practice now, not an
anecdote**, and §W.6 is what happened when this unit ran the practice against the fix itself.

##### W.5 Three figures this unit was handed that do NOT reproduce

Reported rather than quietly adjusted, because a figure that moved is evidence about how it was
read. **The first of the three is the correction this unit was handed to carry — a unit had
already caught the orchestrator relaying the wrong giving-up figure, which is the fourth such
catch tonight — and the corrected figure needed correcting again.**

<!-- provenance: value=0 of 13 passed; 11 of 13 issue no tool call in any message after the observation; of those 11, 5 outputs carry both a top-level "name" and a "parameters"/"arguments" key; reader--doc-small-261--r2 answers {"region": "US", "units": 500}, exactly the JSON shape its own task prompt demanded; commit=c2cfb89; command=a Z2 python census over the 13 transcripts, counting tool_calls in every message after the offending observation and regex-matching the recorded `output` field -->

**1. "0 of 13 passed, and 11 of 13 issued no further tool call of any kind afterwards, answering
with invented tool-call JSON."** The first two clauses reproduce exactly. **The third does not.**

    passed                                                     0 of 13
    no further tool call of any kind after the observation     11 of 13
    of those 11, output shaped like an invented tool call       5

The two that kept calling issued 3 further calls and 1. **Of the 11 that stopped, 5 answered
with something shaped like a tool call it had invented** — `read_rows`, `query`,
`document_update_fields`, `document_read`, `readSheetValues` — and the rest answered with
something else, including one (`reader--doc-small-261--r2`) that answered in exactly the JSON
shape its task asked for and was simply wrong. **The load-bearing half is the tool call that
never came**, and it is intact at 11 of 13; the clause about what filled the silence is not.

**2. "The phrase 'I'm unable to access the workbook' appears in exactly two files, both `bare`."**
The direction of this correction is right and its count is not. **The literal phrase appears in
zero of the 432 committed transcripts.**

<!-- provenance: value=over all 432 committed transcripts (108 each at 3b, 4b, 7b, 14b): "unable to access the workbook" 0 files; "unable to access" 1 file (3b bare--doc-large-out-11764--r2); "I am unable" 1 file (the same); "cannot access" 1 file (3b bare--doc-large-out-11764--r1); "unable to" 3 files (those two 3b files plus 14b bare--doc-large-in-137--r3); every match is in the bare arm and none is a reader run; commit=c2cfb89; command=a Z2 case-insensitive census over docs/eval-data/2026-08-20-document-read-transcripts-{3b,4b,7b,14b}/*.json -->

    "unable to access the workbook"   0 of 432 files
    "unable to access"                1 of 432    3b   bare--doc-large-out-11764--r2
    "cannot access"                   1 of 432    3b   bare--doc-large-out-11764--r1
    "unable to"                       3 of 432    the two above plus 14b bare--doc-large-in-137--r3

**All three matches are in the `bare` arm, none is a `reader` run, and none is a dict-argument
run** — so the conclusion the correction was carrying survives untouched and only its count
fails. The phrasing's real home is a **smoke pass whose transcripts are not committed to this
repository** (`agent.py:124`, which attributes it to the 4b and to `document_list`, not to the
3b and not to `document_read`); it cannot be checked here and is not disputed here.

**And the refuted phrasing survived into `c2cfb89` itself.** `assets/contracts/default.yaml:60`
— a comment added by the very commit whose message records that this phrasing does not
reproduce — says *"a 3b that receives it stops calling tools and answers that it cannot access
the workbook."* The first half is the reproducible finding (11 of 13). The second half is the
4b smoke claim, transplanted onto the 3b, where the committed evidence is 0 of 108. **The asset
is not edited to make this record right**: it is committed evidence, nothing is retro-edited to
make a reader green, and the correction lives here, in the record that quotes it.

**3. "`null` is exempt … and 4 of the 13 real payloads carry one."** Not at any scope. Four is
the count of null *values* anywhere in the 13 payloads, including one nested inside an object
value where a top-level check can never see it; the payload count is three, and at the only
scope `mistyped_arguments` operates in it is **two payloads carrying three nulls**.

<!-- provenance: value=across the 13 committed payloads: 4 null values at any depth in 3 payloads (doc-large-out-8022--r0 1 nested inside the `document` object, doc-large-out-8022--r2 1 top-level, doc-small-137--r3 2 top-level); 3 null values at top level in 2 payloads; commit=c2cfb89; command=a Z2 python census counting `is None` at top level and recursively over each of the 13 recorded tool_call argument dicts -->

    null values anywhere        4    in 3 payloads
    null values at top level    3    in 2 payloads   <- the only scope the exemption acts in

**The exemption is not thereby unjustified** — it rests on every handler here defaulting its
arguments to `None`, which is an argument about the handlers and not a headcount — but the
headcount that was offered as its support is not the one the payloads carry.

##### W.6 Minted here — `RB-P89`, and the three things that get no number

**The register was read at HEAD across every live writer before any number was chosen, not taken
from a brief or an orchestrator.** That precaution is `RB-P75`'s and §V.0's; the ceiling moved
five times in this shift, so the read is recorded:

<!-- provenance: value=ceiling RB-P88, reached on three refs — main (39f7aaf), feat/document-readers (2c77fcc) and feat/declared-arg-types (c2cfb89); max over all 23 refs/heads is 88; 87 distinct entries in this branch's file with 84 absent as prose-range only, per §V.0's deliberate RB-P77…RB-P85 skip; commit=c2cfb89; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

    max over all 23 refs/heads   ->  88     (main, feat/document-readers, this branch)

**`RB-P89` is the next free number and this section mints exactly one entry.** Section letters
are the same register: `U` is taken on `feat/version-truth` and `V` on this branch and `main`,
so this is **section W**.

- **`RB-P89` — a must-be-red mutation that changes one string of a two-string contract surface
  under-reports laundering, and section T's procedure does not catch it, because the procedure
  checks that a NEW case does not appear in an existing column and never checks that the
  MUTATION is as wide as the surface its column claims to pin.** `c2cfb89`'s asset carries two
  strings, a frame (`tool_argument_types`) and an item (`tool_argument_type`), and its `M5`
  reworded the frame. Reworded the *frame*, 4 nodes redden and every one names its reason:
  three carry `verbatim`, the fourth is the byte golden. Reworded the *item* instead, **a fifth
  node reddens — `test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped`, whose
  name promises a claim about dropping and whose last line asserts the item string verbatim
  (`test_agent.py:842`).**

  <!-- provenance: value=M5 frame rewording 4 new red nodes; the same mutant applied to the item string instead 5 new red nodes, the fifth being test_agent.py::test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped; both measured against the same baseline failure set and both reverted to it; commit=c2cfb89; command=the Z2 mutation script above, re-run with the anchor moved from the tool_argument_types line to the tool_argument_type line of assets/contracts/default.yaml -->

      M5  frame reworded   4 new red   3 named `verbatim` + the byte golden
      M5  item  reworded   5 new red   the same 4, plus one whose name states a different claim

  **This is the class section S named and section T made a procedure — its fourth instance —
  and the class does not get a second number**, by the same rule §V.8 applied when it declined
  to renumber `RB-P53`'s clamp. What is new, and what `RB-P89` is, is that **the procedure is
  blind here by construction**: the catalogue was re-run with every new case present, every
  column's membership was checked, and this node still did not appear, because it only reddens
  under a mutation nobody wrote. **The attack:** a must-be-red catalogue must mutate every
  string of the surface its nodes assert on, or state which strings it does not mutate and
  accept that laundering under those is unmeasured — `RB-P51`'s rule, that an unmeasured check
  is not a passed one, applied to the mutation rather than to the run. **NOT FIXED HERE**, and
  the reason is ownership, not effort: the node lives in `runtime-py/tests/test_agent.py` and
  this section owns `docs/eval.md`. The fix is one line of naming — the node either carries
  `verbatim` like its three siblings or asserts on the argument name rather than the item
  string — and it belongs to the layer that holds the node. **Filed.**

**Three things here get no number, and saying so is the entry.**

1. **The fix itself is an amendment, not a defect.** `RB-P86` named the defect and named the
   shape of the fix; `c2cfb89` is that shape landed. A record that comes true does not mint a
   second record.
2. **The corrected giving-up figure is a handoff correction**, and this document records those
   as a subsection of the section that caught them (section Q's *"Two figures this section was handed
   that do NOT reproduce at HEAD"*, section T's *"One thing this unit was handed that does not
   reproduce"*), never as a register entry. §W.5 is that subsection. **Four times tonight the
   orchestrator has relayed a figure a unit then had to re-derive**; that is a fact about this
   shift's handoffs, and the register is for defects in the instrument and the bar.
3. **The third application of the laundering lesson is not a new class.** It is the lesson
   working, which is the opposite of a finding.

##### W.7 What is NOT claimed

1. **J10's verdict is untouched.** The `3b` was a **declared floor and was never pooled**; §7.8
   already declines to read its cells, and nothing in this section re-litigates what the three
   compared tiers measured. No `.jsonl` was regenerated and no committed row is restated.
2. **This does not make the `3b` usable.** It makes one failure mode legible. Whether a 3B can
   drive a paged reader is **UNMEASURED after this fix and stays UNMEASURED** until someone runs
   it; a replay of 13 recorded payloads is a statement about what the tool now says, not about
   what a model would then do with it.
3. **No live model call was made by this section.** Every figure above comes from committed
   transcripts, committed assets, and code replayed at two commits.
4. **Not claimed: that the 13 are the whole of the `3b`'s reader failures.** They are the 13 that
   read a Python exception. §V.8's U-2 and U-5 readings are unchanged and are not re-derived
   here.

##### W.8 Gates

<!-- provenance: value=1227 passed, 2 xfailed; commit=c2cfb89; command=.venv/bin/python -m pytest runtime-py/tests -q, in the main checkout on feat/declared-arg-types -->

    .venv/bin/python -m pytest runtime-py/tests -q
        ->  1227 passed, 2 xfailed        at c2cfb89, unchanged by this section

<!-- provenance: value=All checks passed! on both surfaces; commit=c2cfb89; command=.venv/bin/ruff check runtime-py and .venv/bin/ruff check docs/eval-data -->

    .venv/bin/ruff check runtime-py       ->  All checks passed!
    .venv/bin/ruff check docs/eval-data   ->  All checks passed!

The same reading with the `PYTHONPATH=$PWD/runtime-py/src` prefix §V.9 insists on is identical
here, which is what that section predicts for the main checkout and not for a worktree. **This
section adds no `.py` and no `.jsonl`, so the count is `c2cfb89`'s baseline count and is quoted
with the commit it was measured at.** The `+17` this fix added to the suite is `c2cfb89`'s
figure, measured against `39f7aaf` in that commit's own message, and is not restated here.

`amendguard check . 39f7aaf..HEAD tools/amendguard/ledger.json` reports **UNMEASURED** at
`c2cfb89` — no amend-only path changed in that range — and this section is the first change to
`docs/eval.md` on this branch, so it is the row the checker measures. It is written to be an
insertion and nothing else: no committed line above is rewritten, deleted, or renumbered.

#### X (2026-08-20) — the `answers:` hole: found twice, fixed neither time, both times correctly; closed forward in the harness, and the half of it that is still open

`document_setup:` was built for one purpose beyond making a corpus. `materialise_documents`
resolves every `answers:` address **out of the file it has just written**, so a task's expected
answer and the document it came from cannot disagree. **Nothing consumed the result.**
`score_output` reads `task["scoring"]["expected"]` — a literal typed into the YAML by hand — so
the drift the generator makes impossible was reintroduced **one layer up, in the harness, where
nothing was looking for it.**

It was **found twice and fixed neither time, and both refusals were correct.** X4 was writing
the document-read bar and filed it as its §11.4 (`6271f43`); X5 was proving the reader path and
confirmed the same thing after it (`19ceffa`). Both said the harness was above their layer and
both were right about that. What it cost is the part worth recording: the finding lived for a
day in a bar section and a unit report, and **the register — which is where triage looks — never
carried it.** `da8ffd6` closes the scored half of it. This section is `docs/eval.md` only: it
adds no `.py`, no `.jsonl` was regenerated, no committed row is restated, and none of the nine
committed tasks changes what it asks or answers.

##### X.1 The mechanism, re-derived — and the one figure this section was handed that does not reproduce as stated

<!-- provenance: value=0 hits at 3bcd055, 1 hit at da8ffd6 (evalrun.py:904, fixture.answers.items() inside _answer_claims); commit=da8ffd6; command=git grep -e '\.answers' 3bcd055 -- runtime-py/src, then the same against da8ffd6 -->

    git grep -e '\.answers' 3bcd055 -- runtime-py/src   ->  no hits
    git grep -e '\.answers' da8ffd6 -- runtime-py/src   ->  one, evalrun.py:904

The brief this section was handed says that grep "found the construction site and no reader".
**It does not, and the true reading is stronger than the one handed over.** The construction
site is a keyword argument — `answers={...}` at `evalrun.py:810-812` on `3bcd055` — and does not
match `.answers` at all. At `3bcd055` the field `DocumentFixture.answers` had **no attribute
access anywhere in `runtime-py/src`**: written, validated address by address, and never read by
anything. The single hit at `da8ffd6` is the first reader the field has ever had.

The other two ends of the mechanism hold as filed. `run_task` used `document_fixtures` only to
decide which tools to register (`evalrun.py:1401` and `evalrun.py:1409` at `da8ffd6`), and
`score_output` (`evalrun.py:388`) scores against the committed literal.

##### X.2 Where the check runs, and why it is deliberately not inside the `try`

At `da8ffd6`, inside `run_task` (`evalrun.py:1316`): `materialise_documents` at `:1356`,
`check_expected_against_corpus` at `:1362`, `TrackingClient` at `:1363`. The check is
**immediately after materialisation, before the client is wrapped and before the `Agent`
exists** — the last moment before anything expensive happens — and it sits **outside** the `try`
at `:1502` that turns a `BantamError` into a `config-error` row.

That placement is the same argument `DocumentSetupError` already rests on, applied one step
later. `main()` (`evalrun.py:1689`) returns `None` and `evalrun.py` contains no `sys.exit` and
no `SystemExit`, so **no outcome class moves the process exit status.** A `config-error` row for
an unchecked answer would therefore be a suite that measured nothing and exited 0, which is
`RB-P51`'s failure with a different spelling.

##### X.3 The bridge: two types, and they were not flattened into one

`answers:` resolves to **strings sliced out of a rendered row**. `scoring.expected` is a payload
whose type `scoring.kind` chooses. They are not the same type and the check does not pretend
they are — it bridges them per kind:

- **`json_equal` is checked KEYED.** Every key the payload scores must carry its own
  `expected_<key>` address, compared as strings, because a rendered cell is text and `7726`-the-
  int against `"7726"`-the-cell is one claim.
- **`contains` is checked UNKEYED, as membership**, because that payload is a bag of terms with
  no keys at all and pretending it had keys would be the fiction. Exact rather than inheriting
  `contains_term`'s case-insensitivity: a literal spelled differently from the cell misreports
  the corpus to the reviewer the literal is kept visible for.
- **The direction is one-way on purpose:** every **scored** literal must come from the corpus,
  but not every corpus answer must be scored. The subject of the property is the scored answer.

Re-derived against live corpora rather than by reading the source — four calls into
`check_expected_against_corpus` over a corpus rebuilt by the committed generator:

<!-- provenance: value=4 calls, 3 refused and 1 accepted, messages transcribed from the raised UncheckedAnswerError; commit=da8ffd6; command=a scratch probe building document_setup {inventory-small.xlsx, seed 4021, 400 rows} via materialise_documents and calling check_expected_against_corpus with each scoring payload below -->

    contains ["7508"]  vs inventory-small.xlsx   REFUSED   names the term, what the corpus holds, and where
    contains ["7726"]  vs the same corpus        ACCEPTED
    kind "rubric"                                REFUSED   no bridge; names the three bridged kinds
    tool_trace beside an `expected_units` address REFUSED   those answers would be scored by nothing

##### X.4 The anti-silence clause

An unknown `scoring.kind` **refuses**. The one carve-out — `tool_trace` with no `expected_*`
label beside it — is reached by an **explicit named branch** and pinned by a passing node
(`test_tool_trace_scoring_with_no_corpus_answer_is_allowed`), **not by falling off the end of a
chain of `if`s**. The rule it serves is `RB-P51`'s, quoted as filed: *a check that quietly
passes on data it cannot see is not the same as one that reports it read nothing.* The brief
motivated this clause with a measurement script that skipped its live sections and exited 0;
**this section did not re-derive which script that was** and rests the clause on `RB-P51`
instead.

##### X.5 The finding: the check found a live inconsistency on its first run, outside the nine tasks

At `3bcd055`, `paste_task()` in `runtime-py/tests/test_document_tools.py` hard-coded
`"expected": ["7508"]` — the **large** corpus's answer — for **every** entry it was given, while
`SMALL_CORPUS` ships `inventory-small.xlsx`. So
`test_clause_3_one_constant_keeps_the_small_corpus_whole` shipped a document and scored a
literal that document does not contain.

<!-- provenance: value="7508" absent from all 401 rendered rows of inventory-small.xlsx and from the file's raw bytes; the corpus's expected_units cell (stock!C138) holds "7726"; commit=da8ffd6; command=a scratch probe calling materialise_documents on {inventory-small.xlsx, seed 4021, 400 rows} then docread.extract, testing membership over the rendered rows and over path.read_bytes() -->

    "7508" in inventory-small.xlsx rendered rows (401)  ->  False
    "7508" in inventory-small.xlsx raw file bytes       ->  False
    its expected_units cell, stock!C138                 ->  "7726"

**Nothing went red, because that test reads the paste and discards the result** — it asserts on
the pasted row count, the byte total and the completeness banner, and never looks at scoring at
all. **The defect the property names was already in the tree, and the property found it the
first time it ran.** That is the strongest thing in this section, and what it says about the
class is that the drift needed neither age nor carelessness: one helper took `expected` as a
constant while its corpus was a parameter.

##### X.6 Wiring and non-vacuity, verified against the run rather than the source

A1's two neutralising mutants were **re-run here**, not carried:

<!-- provenance: value=M3a 9 failed, 1240 passed, 2 xfailed; M3b 1 failed, 1248 passed, 2 xfailed, the single failure raising IndexError: pop from empty list at runtime-py/tests/conftest.py:13; both reverted and the tree restored; commit=da8ffd6; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests -q with (M3a) an early return at the top of check_expected_against_corpus and (M3b) the call deleted from run_task -->

    M3a  check returns immediately          9 red     nothing was passing on a technicality
    M3b  function intact, call removed      1 red     and it reddened with `IndexError: pop from
                                                      empty list` out of the fake client, which is
                                                      direct proof the model call was reached

**The wiring claim has exactly one guard and it is the only thing that fires.** The nine
parametrised `test_g1_is_now_the_harness_check_and_not_only_this_file` nodes stay green under
M3b, correctly: they call the function, so they cannot say whether `run_task` does.

##### X.7 Two things A1 disclosed about its own nodes, recorded as disclosed

1. **One of its own must-be-red nodes was caught laundering — the fourth catch of that class in
   this shift.** `test_json_equal_key_with_no_answer_address_is_refused` was built on a committed
   task plus an extra unaddressed key; under the mutation it went red on the **units
   contradiction** and never reached the **missing address** its name promises. It was rebuilt on
   a local task where the missing address is the only defect present. Section S named this class
   and section T made it a procedure; **the practice is now what lands a must-be-red node here**,
   and a fourth catch is the lesson working.
2. **One node is trivially true and says so in its own name.**
   `test_the_check_is_a_no_op_for_every_task_in_the_frozen_suite` passes because the check returns
   early when no document was materialised. It is a **scope statement, not a strength statement**,
   it asserts its reason first, and it carries `no-op` in its own name. Recorded as the honest
   disclosure it is rather than dressed up as coverage.

##### X.8 Minted here — `RB-P90`, and the four things that get no number

**The register was read at HEAD across every live writer before any number was chosen, not taken
from a brief or an orchestrator.** That precaution is `RB-P75`'s, §V.0's and §W.6's; the ceiling
moved six times in this shift, so the read is recorded:

<!-- provenance: value=ceiling RB-P89, reached on three refs — main (3bcd055), feat/declared-arg-types (9b0ce97) and this branch feat/answers-checked (da8ffd6); max over all 24 refs/heads is 89; commit=da8ffd6; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

    max over all 24 refs/heads   ->  89     (main, feat/declared-arg-types, this branch)

**`RB-P90` is the next free number and this section mints exactly one entry.** Section letters
are the same register with the same hazard: `L`–`Q`, `S`, `T` and `V`, `W` are taken on this
branch and on `main`, `U` on `feat/version-truth`, so this is **section X**.

- **`RB-P90` — the bar's §11.4 named two missing paths and `da8ffd6` closes one of them. The
  question half is still open in the harness, and the nine committed tasks are covered for it
  only by a nine-file test-suite checker — which is the exact arrangement §11.4 itself called
  insufficient.** §11.4's words are *"no path from `DocumentFixture.answers` to a prompt or to
  `scoring.expected`"*. The scored half now has `check_expected_against_corpus`. The prompt half
  has `test_document_tasks.py::test_g1_the_question_names_the_row_the_answer_was_read_from`,
  which asserts `fixture.answers["question_sku"] in task["prompt"]` **over the nine committed
  files only**; the harness declines the comparison by design, because a label without the
  `expected_` prefix is not a claim about scoring.

  <!-- provenance: value=ACCEPTED — a task whose prompt names SKU-999999 while question_sku (stock!A138) resolves to SKU-000137 raises nothing from check_expected_against_corpus; commit=da8ffd6; command=a scratch probe building {inventory-small.xlsx, seed 4021, 400 rows} with answers {question_sku: stock!A138, expected_units: stock!C138}, prompt naming SKU-999999, scoring contains ["7726"] -->

      question_sku resolves to  SKU-000137
      the prompt names          SKU-999999
      check_expected_against_corpus  ->  ACCEPTED

  A run built that way **asks about a row its corpus does not hold, scores an answer its corpus
  does hold, and reports the model wrong** — the same drift, one field over, and again
  attributed to the model. **Attack, stated as the property and not as the mechanism:** a cell a
  task resolves for the prompt's sake must be one the prompt actually names, and a task that
  resolves a cell for neither the prompt nor the scoring must say so; how that is declared
  belongs to whoever writes it. **NOT FIXED HERE, and the reason is ownership, not effort:** it
  is a Layer-1 change to `evalrun.py` and this section owns `docs/eval.md`. **Filed.**

**Four things here get no number, and saying so is most of the entry.**

1. **The fix itself is a closure, not a defect.** §11.4 named the hole and named the shape of the
   fix; `da8ffd6` is that shape landed. A bar finding that comes true does not mint a register
   entry, and §11.4 is a record and is not edited by it.
2. **The `paste_task` inconsistency of §X.5 is an instance of the class §11.4 already named**, not
   a new class, and it was fixed in the same commit that found it. Its value is as evidence that
   the property is live on day one, and §X.5 is where that is recorded.
3. **The fourth laundering catch is the lesson working, which is the opposite of a finding** —
   §W.6's rule 3, applied unchanged.
4. **The brief figure that does not reproduce is a handoff correction.** This document records
   those as a subsection of the section that caught them (§Q, §T, and §W.5's *"Four times tonight
   the orchestrator has relayed a figure a unit then had to re-derive"*), never as a register
   entry. **§X.1 is that subsection, and it is one more of the same shape.**

##### X.9 What is NOT claimed

1. **J10's verdict and its rows are untouched, and what its 432 rows can still support is exactly
   what they supported before.** The scored literals in that run **were** equal to the corpus —
   checked file by file by `runtime-py/tests/test_document_tasks.py`, whose non-vacuity the bar's
   §11.7 measured by mutation (`M1`: one committed `expected.units` flipped 7508 → 7509 reddens a
   node). **This fix therefore changes nothing about what those 432 rows measured. It changes what
   the tenth task can get away with.**
2. **The harness is not drift-proof and this does not claim it is.** Still unchecked at this HEAD:
   `RB-P90`'s question half; `contains`, which is membership and has no addresses, so a term that
   equals the right string for the wrong reason is accepted; and any task that materialises no
   document, for which the check returns early by design — **the twenty-two frozen tasks are
   exactly as checked as they were, which is by nothing of this kind.**
3. **No live model call was made by this section.** Every figure above comes from committed source
   read at two commits, from corpora rebuilt by the committed generator, and from the test suite.
4. **Not claimed: that the nine mismatch cases `da8ffd6` names are the whole of the ways a task can
   misreport its corpus.** They are the nine it refuses. §X.9(2) names three it does not.

##### X.10 Gates

<!-- provenance: value=1249 passed, 2 xfailed; commit=da8ffd6; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests -q, from the worktree with the absolute interpreter -->

    .venv/bin/python -m pytest runtime-py/tests -q
        ->  1249 passed, 2 xfailed     at da8ffd6, delta 0, unchanged by this section

<!-- provenance: value=All checks passed! on both surfaces; commit=da8ffd6; command=.venv/bin/ruff check runtime-py and .venv/bin/ruff check docs/eval-data -->

    .venv/bin/ruff check runtime-py       ->  All checks passed!
    .venv/bin/ruff check docs/eval-data   ->  All checks passed!

**This section adds no `.py` and no `.jsonl`**, so the count is `da8ffd6`'s count, re-derived
here and quoted with the commit it was measured at. The `+22` that `da8ffd6` added to the suite
is that commit's own figure, measured there against `3bcd055`, and is not restated here.

`amendguard check . 3bcd055..HEAD tools/amendguard/ledger.json` reported **UNMEASURED** at
`da8ffd6` — no amend-only path changed in that range — and this section is the first change to
`docs/eval.md` on this branch, so it is the row the checker measures. It is written to be an
insertion and nothing else: no committed line above it is rewritten, deleted, or renumbered.

#### Y (2026-08-20) — `RB-P90`'s question half, closed forward one commit after it was filed; the exemption is falsifiable, and it is not a floor

`RB-P90` was minted in §X.8 as the half `da8ffd6` did not close. `check_expected_against_corpus`
refuses a task whose **scored** answer nobody read out of its own corpus; it says nothing about
the half of the task that does the **asking**, and by construction — `_answer_claims`
(`evalrun.py:868`, `ANSWER_CLAIM_PREFIX = "expected_"`) skips every label without that prefix,
and the nine committed tasks carry the lookup key into the prompt through `question_sku:`, which
has none. `39c20ce` closes it: **`check_question_against_prompt` refuses a task whose question
addresses a row its own prompt does not name.**

This section is `docs/eval.md` only. It adds no `.py`, regenerates no `.jsonl`, and restates no
committed row; the mechanism is `39c20ce`'s and lives in `runtime-py/`. **The most important
sentence in it is §Y.4:** the closure is falsifiable and it is **not a floor**, and the residue
that leaves is the only thing here that gets a number.

##### Y.0 The register was read at HEAD across every live writer, before any number was chosen

§X.8's precaution, `RB-P75`'s before it, applied again and for the same reason — §X.8 recorded
the ceiling moving six times in one shift, and it has moved again since that sentence was
written.

<!-- provenance: value=ceiling RB-P90, reached on three refs — main (cbe3740), feat/answers-checked (da8ffd6) and this branch feat/question-checked (39c20ce); max over all 24 refs/heads is 90; commit=39c20ce; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

    max over all 24 refs/heads   ->  90     (main, feat/answers-checked, this branch)

**`RB-P91` is therefore the next free number, and this section mints exactly one entry.** Section
letters are the same register with the same hazard, and were read the same way:

<!-- provenance: value=section letters K5 and L-Q and S-X are taken across the 24 refs; no ref carries a section Y; commit=39c20ce; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE '^#### [A-Z][0-9]* \(' ; done | sort -u -->

    taken, over every ref   ->  K5  L M N O P Q  S T U V W X
    free                    ->  Y

`U` is on `feat/version-truth` and `main`; `X` is on `main`, `feat/answers-checked` and this
branch. **This is section Y.**

##### Y.1 What `39c20ce` is, re-derived from the commit rather than from the hand-back

<!-- provenance: value=3 files, +226/-2, all under runtime-py/; commit=39c20ce; command=git show --stat 39c20ce and git diff --stat main...HEAD -->

    runtime-py/src/bantamkit/evalrun.py       +81
    runtime-py/tests/test_document_setup.py  +139  -1
    runtime-py/tests/test_document_tools.py    +8  -1
                                             3 files, +226 -2

No `assets/`, no `docs/`, no `.jsonl`, and none of the nine committed tasks changes what it asks
or answers. **Layer 1 only**, which is what makes this section legal as Layer 3: the two halves of
this job never touch the same file.

##### Y.2 Where the refusal runs, and why it is second rather than first

At `39c20ce`, inside `run_task`: `check_expected_against_corpus` at `evalrun.py:1439`,
`check_question_against_prompt` at `:1443`, `TrackingClient` at `:1444`. The new check sits
**immediately after the scored half, before the client is wrapped and before the `Agent`
exists**, and **outside** the `try` that turns a `BantamError` into a `config-error` row.

That is §X.2's argument inherited unchanged, and it is inherited rather than restated because the
reason is unchanged: `main()` returns `None`, `evalrun.py` has no `sys.exit`, so a `config-error`
row for a question nobody asked would be a suite that measured nothing and exited 0 — `RB-P51`'s
failure with a third spelling.

**Second rather than first is a deliberate ordering and it is the smaller of the two decisions.**
A task file wrong in *both* halves keeps the message it already had; the new check can only ever
add a refusal, never change one. That is why the seven new nodes could be added without any
existing message assertion moving.

##### Y.3 The bridge: one rule, two prefixes, and a label whose spelling is its role

The property has two clauses, and only the first is about the prompt:

> A cell a task resolves **for the prompt's sake** must be one the prompt actually names, and a
> task that resolves a cell for **neither the prompt nor the scoring** must say so.

The second clause needed a spelling, and `39c20ce` put it in the label — `QUESTION_EXEMPT_PREFIX
= "unasked_"` at `evalrun.py:1025`, read at the same place and by the same rule as `expected_`.
**The argument for that choice is that the file already keeps a label's role in its spelling**,
so `unasked_<label>` is not a new mechanism, it is the existing one used twice. Every label that
is neither `expected_` nor `unasked_` is a question address, and its resolved value must occur in
`task["prompt"]`.

`UnaskedAnswerError` (`evalrun.py:1028`) is a sibling of `UncheckedAnswerError`, **not a
subclass**, and the distinction is load-bearing rather than tidy: a must-be-red node that means
to catch the question half would otherwise go green on the scored half's refusal, which is
exactly the laundering §T made a procedure against. The type system is doing the §T check here.

##### Y.4 The declaration is CHECKED in both directions — and it is still not a floor

Re-derived against live corpora rebuilt by the committed generator, not read off the source. Five
rows, each a separate task object built from a committed `.yaml`:

<!-- provenance: value=9 of 9 committed tasks accepted by both checks; ATTACK scored=ACCEPTED question=REFUSED; hatch-on-honest REFUSED; hatch-on-attacked ACCEPTED; no-address-on-attacked ACCEPTED; commit=39c20ce; command=a scratch probe loading assets/evals/document/tasks/*.yaml, calling materialise_documents into a tmpdir at config `bare`, then check_expected_against_corpus and check_question_against_prompt on each variant -->

    nine committed tasks, unchanged                    ->  9 of 9 ACCEPTED by BOTH checks
    ATTACK: doc-large-in-137, prompt SKU-999999
        check_expected_against_corpus                  ->  ACCEPTED
        check_question_against_prompt                  ->  REFUSED  UnaskedAnswerError
    ESCAPE HATCH on the HONEST task
        (rename to unasked_, prompt untouched)         ->  REFUSED  UnaskedAnswerError
    ESCAPE HATCH on the ATTACKED task                  ->  ACCEPTED
    NO QUESTION ADDRESS AT ALL on the ATTACKED task    ->  ACCEPTED

The ATTACK row is the whole of `RB-P90`: the scored half accepts it — `scoring.expected` still
matches the corpus cell by cell — while the prompt asks about a row the corpus does not hold.
Before `39c20ce` such a run started, scored the model, and **put the mismatch on the model's
record.**

**Row 3 is what makes the exemption honest.** `unasked_` on a cell the prompt *does* name is
refused too, so renaming the nine committed tasks' `question_sku:` to `unasked_question_sku:`
cannot silently disarm the check — the rename is itself a refusal. An escape hatch nobody can
falsify is the hole with a longer name, and this one can be falsified on any task that is honest.

**Rows 4 and 5 are the same fact and they are the most important thing in this section.** The
exemption is falsifiable **on a task that is honest** and it gives the check **no floor**. A task
that declares zero asked cells — by omitting the address, or by renaming every question label to
`unasked_` — may carry a prompt naming any row it likes, and `RB-P90`'s shape returns intact.
Nothing in `39c20ce` requires a question address to exist; the scored half requires at least one
`expected_*` address, and the question half requires nothing at all.

`39c20ce` gives a reason for not requiring one: a legitimate prompt may address no single cell —
an aggregation, or a `tool_trace` task — and forcing one has a blast radius past this job's
edges. **The verdict on that argument, with its cost side measured rather than assumed:**

<!-- provenance: value=all nine committed document tasks carry exactly {question_sku, expected_region, expected_units}; 0 tasks outside those nine carry a document_setup; exactly 1 committed task is scored tool_trace and it carries no document_setup; commit=39c20ce; command=grep -h -A6 'answers:' assets/evals/document/tasks/*.yaml | grep -E '^\s+\w+:' | sort | uniq -c, plus grep -l 'document_setup' assets/evals/tasks/*.yaml and grep -h 'kind:' over both task directories -->

    the nine's answer labels        ->  question_sku x9, expected_region x9, expected_units x9
    document_setup outside the nine ->  0 tasks
    committed tool_trace tasks      ->  1, and it declares no document_setup

**So a floor would break nothing in the tree today, and the argument's cost side is entirely
prospective.** The argument is accepted anyway, and accepted **as a reason not to fix it here,
not as a reason it needs no entry.** Two things make that the right call: the floor is a second
property (it must decide what "at least one question address" means for a `contains`-scored task,
which has no keys), and it would land in `evalrun.py`, which this section does not own. **That is
precisely what the register is for — filed, not fixed.** It is minted below as `RB-P91`.

##### Y.5 Non-vacuity, verified against the run rather than the source

`39c20ce`'s two neutralising mutants were **re-run here**, on a twin worktree exported from git
rather than in the checkout, because `runtime-py/` is the other unit's layer and a live unit's
file is never mutated in place:

<!-- provenance: value=M1 4 failed, 1255 passed, 2 xfailed — three Failed: DID NOT RAISE UnaskedAnswerError and one IndexError: pop from empty list at tests/conftest.py:13; M2 1 failed, 1258 passed, 2 xfailed, the same IndexError; both reverted, both worktrees git status --short empty; commit=39c20ce; command=git worktree add <scratch> 39c20ce, then PYTHONPATH=<scratch>/runtime-py/src .venv/bin/python -m pytest <scratch>/runtime-py/tests -q with (M1) an early return at the top of check_question_against_prompt and (M2) the call deleted from run_task -->

    M1  check returns immediately      4 red   3 x DID NOT RAISE UnaskedAnswerError
                                              1 x IndexError: pop from empty list (conftest.py:13)
    M2  function intact, call removed  1 red   the same IndexError, and nothing else

Both reproduce `39c20ce`'s reported counts exactly. **M2's single red is the wiring claim's only
guard, and it is the only thing that fires** — the five nodes that call
`check_question_against_prompt` directly stay green under M2, correctly, because they cannot say
whether `run_task` calls it.

The seven new nodes were counted from the collected node ids rather than from the diff:

<!-- provenance: value=1254 collected at cbe3740, 1261 at 39c20ce, 7 added and 0 removed, all seven in tests/test_document_setup.py; commit=39c20ce; command=pytest --collect-only -q on twin worktrees at cbe3740 and 39c20ce, node ids sorted and diffed with comm -->

    added    7   test_a_committed_task_asks_about_the_row_its_own_corpus_holds
                 test_a_prompt_naming_a_row_the_corpus_does_not_hold_is_refused
                 test_a_scored_answer_is_not_required_to_appear_in_the_prompt
                 test_a_cell_the_prompt_never_names_is_refused_until_the_label_says_it_is_unasked
                 test_declaring_a_cell_unasked_while_the_prompt_names_it_is_refused
                 test_the_question_check_is_a_no_op_for_every_task_in_the_frozen_suite
                 test_run_task_refuses_an_unasked_question_before_it_calls_the_model
    removed  0

And the blast radius — the pre-existing nodes the new property would have reddened had the two
fixture renames not landed with it — was measured by putting `39c20ce`'s `evalrun.py` on top of
`cbe3740`'s test tree:

<!-- provenance: value=3 failed, 1249 passed, 2 xfailed; the three are test_document_setup.py::test_run_task_materialises_a_valid_declaration_before_the_agent_runs, test_document_tools.py::test_clause_3_one_constant_keeps_the_small_corpus_whole and test_document_tools.py::test_the_budget_is_one_running_total_across_parts_not_a_fresh_ceiling_per_part; commit=39c20ce; command=copy the cbe3740 worktree, overwrite runtime-py/src/bantamkit/evalrun.py with 39c20ce's, then pytest -q --tb=no -->

    3 failed, 1249 passed, 2 xfailed   the exact three, named above

That reproduces the prep probe's **exactly 3 test nodes** and `39c20ce`'s own re-derivation of
it. One precision note on the wording rather than the number, recorded in §Y.7.

##### Y.6 The self-disclosure against invariant 6, recorded as disclosed, and the verdict on it

`39c20ce` discloses, rather than leaving to be found, that its wiring node
`test_run_task_refuses_an_unasked_question_before_it_calls_the_model` **reddens under both
mutations via `IndexError` from `FakeClient([])` rather than via a missing raise.** Its argument:
that *is* the defect the node's name promises — *"before it calls the model"* surfacing as the
model being called — and it is the same shape §X.6 recorded for its `M3b`.

**The argument is accepted, and the reason is mechanical rather than charitable.** `conftest.py:13`
is `return self.responses.pop(0)`, **inside `FakeClient.chat`**. An `IndexError` raised there is
proof the harness entered a model call — it cannot be reached any other way. The fixture is a
committed task with one field changed, and the scored half is separately asserted to ACCEPT that
same task, so **no second defect is present for the node to redden on**; the §T hazard is a
laundering hazard and there is nothing here to launder. The node also discriminates *late* from
*absent*: a call site moved to after the model call reddens it too, for the same reason.

**One weakness is real and it is not the one disclosed.** With an empty queue the node dies before
reaching its own `assert client.calls == []`, so the message a future reader sees names the fake
client and not the check. Queueing one response would move the failure onto `DID NOT RAISE` and
leave `client.calls == []` as the live assertion, at no cost to what is proved. **That is a
legibility defect in a node that is otherwise sound, and it is too small for the register** —
recorded here, in the section, which is where §W.6's rule 3 puts things that are neither findings
nor fixes.

##### Y.7 What the hand-off did NOT reproduce as stated — and it is a qualifier and a noun, not a figure

**Every number handed to this section re-derived**: `+226/-2`, three files, seven nodes, the
`1259 / 1252` gate pair, `M1`'s 4 red and `M2`'s 1 red with their exact messages, the blast radius
of 3, the 9-of-9 acceptance, the whole five-row attack table, and the prep probe's discrimination:

<!-- provenance: value=exactly 1 corpus key value occurs in the prompt on all nine tasks — 1 of 12000 on the six large corpora, 1 of 400 on the three small; commit=39c20ce; command=a scratch probe materialising each committed task, extracting every rendered row with docread.extract, and counting distinct SKU- key values occurring as substrings of task["prompt"] -->

    six large corpora   ->  1 of 12000 key values occurs in the prompt, on each
    three small corpora ->  1 of   400 key values occurs in the prompt, on each

Two things do not survive as worded. Neither is a number, and this document records handoff
corrections as a subsection of the section that catches them (§Q, §T, §W.5, §X.1) — never as a
register entry.

1. **"`RB-P90` re-opens, *silently*" is measurably too strong, for the one directory it can be
   wrong about.** Adding a tenth document task with no `question_sku:` and a prompt naming
   `SKU-999999` does redden the suite. But the honest control is what makes that readable:

   <!-- provenance: value=a tenth task with question_sku deleted and the prompt renamed to SKU-999999 reddens 3 nodes; an HONEST tenth task, question_sku intact and prompt naming the row, reddens 2 of the same 3; the discriminating node is test_g1_the_question_names_the_row_the_answer_was_read_from[doc-small-tenth] and it fails with KeyError: 'question_sku' at test_document_tasks.py:138; commit=39c20ce; command=two copies of the 39c20ce worktree, a tenth .yaml added to assets/evals/document/tasks/ in each, then pytest runtime-py/tests/test_document_tasks.py -q --tb=line -->

       dishonest tenth task  ->  3 failed, 56 passed
       honest   tenth task   ->  2 failed, 57 passed
       the difference        ->  exactly ONE node, failing with KeyError: 'question_sku'

   The two nodes common to both are a **census**: `test_the_task_set_is_the_nine_the_bar_pre_registered`
   (`assert 10 == 9`) and `test_every_stratum_the_bar_declares_is_populated_as_declared`. They fire
   on *any* tenth task and carry **no information about the defect**. Exactly one node carries
   information, it does so by `KeyError` on a missing dict key rather than by asserting the
   property, and it sees only files under `assets/evals/document/tasks/`. **So the honest wording
   is: silent in the harness; in the suite, caught by a census pinned to nine plus one incidental
   `KeyError`, in one directory.** That is a weaker guard than "not silent" suggests and a
   stronger one than "silently" allows, and §Y.8's entry is worded from the measurement.

2. **"Three of this suite's own fixtures … are renamed" is three *nodes* across *two* fixture
   declarations.** `39c20ce` renames `SMALL_CORPUS` in `test_document_tools.py` (which two nodes
   read) and one inline `IN_WINDOW` override in `test_document_setup.py` (one node). The count 3
   is right; the noun is one level off. Recorded because §Y.5's blast-radius figure is quoted
   against it.

##### Y.8 Minted here — `RB-P91`, and the four things that get no number

- **`RB-P91` — the question check has no floor: a document task that declares zero asked cells is
  accepted whatever its prompt asks, so `RB-P90`'s shape survives its own closure one step out.**
  `check_question_against_prompt` refuses a *declared* question address the prompt does not name,
  and refuses an `unasked_` declaration the prompt *does* name — both directions, so the exemption
  is falsifiable on any honest task. **Neither direction has a subject when no question address
  exists.** Omit `question_sku:`, or rename every question label to `unasked_`, and the prompt may
  name any row it likes: §Y.4 rows 4 and 5 measure both, both ACCEPTED, on a task whose prompt
  asks for a row its corpus does not hold. Today's only guard is the nine-file checker, which
  §Y.7(1) measures at **one informative node, firing by `KeyError`, over one directory** — the
  same shape §11.4 of the bar called insufficient when it was the *only* guard for the scored
  half. **Attack, stated as the property and not as the mechanism:** a task that materialises a
  corpus must say what its prompt asks about, and "nothing" must be a thing it can say and be held
  to; whether that is a required label, a required count, or a declaration at the task level
  belongs to whoever writes it. **NOT FIXED HERE, and the reason is ownership plus scope:** it is
  a Layer-1 change to `evalrun.py`, this section owns `docs/eval.md`, and §Y.4 measures the cost
  side of the deferral as zero committed tasks broken today. **Filed.**

**Four things here get no number, and saying so is most of the entry.**

1. **`RB-P90` is a record and is not edited by being closed.** §X.8 filed it, `39c20ce` is the
   shape it named, landed. A bar finding — or a register finding — that comes true does not mint a
   new entry; the closure is noted here, beside it, and §X.8's text stands unamended.
2. **The `unasked_` bidirectional check is a design decision that worked, not a finding.** It is
   the answer to an escape hatch that would otherwise be unfalsifiable, it is pinned by a node
   built on a committed task with the rename as its only defect, and §Y.4 row 3 measures it. A
   mechanism doing its job is the opposite of a defect.
3. **The `IndexError` legibility weakness of §Y.6 is a node's message, not a property's hole.**
   The node proves what its name promises; only its failure text points at the fixture instead of
   the check. §W.6's rule 3 keeps that in the section.
4. **The two handoff corrections of §Y.7 are handoff corrections.** A qualifier that overstated and
   a noun off by one level, both caught by re-derivation, both belonging in the subsection that
   caught them. **§Y.7 is that subsection.** It is also worth recording that this is the first
   section in this run of the register where **every figure** handed over survived re-derivation
   and only the prose around them moved.

##### Y.9 What is NOT claimed

1. **Not claimed: that a task's question is now known to be *about* the row it names.** Membership
   is literal substring containment over `task["prompt"]`, which is strictly weaker. Measured, not
   reasoned about:

   <!-- provenance: value=ACCEPTED — a task whose question_sku resolves to SKU-000137, whose prompt names SKU-000137 only inside a parenthetical format example and then asks about SKU-000261, passes check_question_against_prompt unchanged; commit=39c20ce; command=a scratch probe on doc-small-137 with the prompt rewritten to "Find the row whose sku is exactly SKU-000261 ... (Sku codes look like SKU-000137.)" and the answers: block untouched -->

       question_sku resolves to     SKU-000137
       the prompt asks about        SKU-000261
       the prompt mentions          SKU-000137, as a format example
       check_question_against_prompt  ->  ACCEPTED

   The discrimination measured in §Y.7 (1 of 12000, 1 of 400) says this is not a near-miss on
   today's nine; it does not make the claim any stronger than it is.

2. **Not claimed: that the matching is token-aware, case-folding, or whitespace-normalising.** It
   is exact substring, so a short or numeric value can occur inside an unrelated number.
   `expected_*` labels are exempt from the search, so today's exposure is non-`expected_` labels
   on non-key columns — `NOTES_DOCX`'s `target_line`, which resolves to a whole rendered line, is
   the shape. Strictness mirrors `_check_unkeyed_expected`; it is a decision, not a derivation.

3. **Not claimed: that a cell named anywhere else counts as asked.** Only `task["prompt"]` is
   searched. A cell named in a system message, a tool description or a memory fact is *unasked* as
   far as this check is concerned, and a task built that way must carry the `unasked_` prefix or
   be refused.

4. **Not claimed: that the `where` in a refusal message always names the right address.** The pairing
   is `zip(entries, fixtures, strict=False)`, inherited from `_answer_claims`; if entries and
   fixtures ever desync, the address in the message can be the wrong one. Pre-existing in the
   scored half, now present in both halves — the refusal still fires, only its pointer can slip.

5. **Nothing about any committed run changes.** No `.jsonl` is regenerated and no committed row is
   restated by this section or by `39c20ce`. J10's 432 rows measured what §X.9(1) says they
   measured. **This changes what a tenth task can get away with, and nothing else.**

6. **No live model call was made by this section.** Every figure above comes from committed source
   read at two commits, from corpora rebuilt by the committed generator into scratch worktrees, and
   from the test suite.

##### Y.10 Gates

<!-- provenance: value=1259 passed, 2 xfailed at 39c20ce; 1252 passed, 2 xfailed at cbe3740; delta +7; commit=39c20ce; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests -q in the checkout at 39c20ce, and the same against a twin worktree exported at cbe3740 -->

    .venv/bin/python -m pytest runtime-py/tests -q
        ->  1252 passed, 2 xfailed     at cbe3740   (baseline, twin worktree)
        ->  1259 passed, 2 xfailed     at 39c20ce   (delta +7, the seven nodes of §Y.5)

<!-- provenance: value=All checks passed! on runtime-py at both cbe3740 and 39c20ce, and on docs/eval-data at 39c20ce; commit=39c20ce; command=.venv/bin/ruff check runtime-py and .venv/bin/ruff check docs/eval-data -->

    .venv/bin/ruff check runtime-py       ->  All checks passed!   at cbe3740 and at 39c20ce
    .venv/bin/ruff check docs/eval-data   ->  All checks passed!

**This section adds no `.py` and no `.jsonl`**, so the suite count is `39c20ce`'s count, quoted
with the commit it was measured at, and the `+7` is that commit's own figure measured here against
`cbe3740` rather than carried.

`amendguard check . cbe3740..HEAD tools/amendguard/ledger.json` reported **UNMEASURED** at
`39c20ce` — no amend-only path changed in that range — and this section is the first change to
`docs/eval.md` on this branch, so it is the row the checker measures. Measured rather than
asserted, on this section's own commit:

<!-- provenance: value=VERDICT path=docs/eval.md classify=insert isolation=mixed derivation=absent verdict=OK, insert 350 lines at line 9098; SUMMARY rows=1 ok=1 red=0 broken=0 merges=0 unmeasured=0; commit=the commit carrying this section; command=.venv/bin/python tools/amendguard/amendguard.py check . cbe3740..HEAD tools/amendguard/ledger.json -->

    classify=insert   isolation=mixed   derivation=absent   verdict=OK
    insert — 350 lines at line 9098
    SUMMARY rows=1 ok=1 red=0 broken=0 merges=0 unmeasured=0

`isolation=mixed` gates nothing here: it is `sole` only for a pointer-only single-file commit,
and the isolation rule is applied to `classify` values beginning `pointer:`. This is an
insertion and nothing else — **no committed line above it is rewritten, deleted, or
renumbered**, which is the `+350 / -0` the diff carries.


#### Z (2026-08-20) — J24 closes `RB-P78` with CONTAINMENT and not equality; two figures inside `RB-P78` are corrected beside it; and a docstring left behind by a reverted fold re-arms the mechanism its own commit refuted

`RB-P78` was the register's open, escalation-class entry: five `.js` shadows reach
`classify_outcome PASS` with a CANON-1 stream byte-identical to pristine, every declared guard
clean and all five defects on disk. `feat/module-graph-containment` closes it forward —
`88d8628` the bar with §9 empty, `08b6a84` the recorder, the guard and selfcheck `M13`,
`fd2420c` §9 appended by amendment with nothing above it edited. Three commits, four files,
**1110 insertions and 8 deletions**, all of them under `docs/eval-data/`.

<!-- provenance: value=3 commits, 4 files changed, 1110 insertions(+), 8 deletions(-), every path under docs/eval-data/; commit=fd2420c; command=git diff --shortstat 1a8e382..fd2420c and git diff --name-only main...HEAD -->

**The headline is not "`RB-P78` is closed".** It is that the property that closes it is
**one-sided by measurement** — the equality `RB-P78` itself proposes is FALSE on a pristine tree
by **11 paths**, so a job that had pre-registered equality would have reddened on a clean run
before it ever saw an attack. This section owns `docs/eval.md`. It adds no `.py`, regenerates no
`.jsonl` and restates no committed row; the mechanism is `08b6a84`'s and lives under
`docs/eval-data/`.

##### Z.0 The register was read at HEAD across every live writer, before any number was chosen

`RB-P75`'s precaution, §V.0's, §W.6's, §X.8's and §Y.0's — applied again because §X.8 recorded
the ceiling moving six times in one shift and it has moved twice more since §Y.0 was written.

<!-- provenance: value=ceiling RB-P91, reached on five of 28 refs/heads — main (1a8e382), fix/sdist-asset-pack (1a8e382), feat/question-checked (692c762), feat/real-corpus-readers (9b88772) and this branch feat/module-graph-containment (fd2420c); max over all 28 refs/heads is 91; commit=fd2420c; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

    ceiling over all 28 refs/heads            ->  RB-P91
    refs standing at it                       ->  main, fix/sdist-asset-pack (both 1a8e382),
                                                  feat/question-checked (692c762),
                                                  feat/real-corpus-readers (9b88772),
                                                  this branch (fd2420c)

`(ceiling RB-P91 over 28 refs, fd2420c, the command above)`. **`RB-P92` is the next free number,
and this section mints exactly one: `RB-P92`.** The section letter was read the same way and
`Z` was free on every ref; `L`–`Y` are taken.

##### Z.1 The hole, the property that closes it, and why the property is ONE-SIDED

The oracle is `vitest`; the build is `tsc -p tsconfig.json`. They disagree about which files
constitute the package, and `RB-P78` is that disagreement weaponised: an extensionless
specifier (`from "./date"`) resolves `.js` **before** `.ts` under Vite's default
`resolve.extensions`, while `include: ["src"]` with `allowJs` unset keeps the same `.js` out of
the TypeScript program entirely. The oracle reads a file the build will never compile, so the
oracle's exit code is not evidence about the shipped artifact.

The property: **every module the ORACLE loads must also be in the BUILD's program.** Set-wise,
`ORACLE \ BUILD` must be empty — `graph_containment` is `sorted(oracle - build)`
(`docs/eval-data/2026-08-18-loop-harness.py:637-643` at `fd2420c`), and a non-empty difference is
terminal whatever the oracle's exit code says.

**Why one-sided, and this is the sentence the whole bar turns on.** `RB-P78` words the stronger
property as *"the oracle's module graph must **equal** the build's"*. Measured on a pristine
`DEFECT-SET-5` tree, equality is false by **11 paths** in the other direction:

<!-- provenance: value=|ORACLE|=21 |BUILD|=32 |BUILD\ORACLE|=11 status=clean, ORACLE\BUILD empty, guard fires ZERO times; the 11 are the index.ts barrels plus src/trip/score/score.ts; commit=fd2420c; command=.venv/bin/python docs/eval-data/2026-08-20-j24-module-graph-field-measurement.py --worktree <throwaway> --real-repo <packnplan-mono @ 81ac1a1> -->

    clean tree   |ORACLE| = 21   |BUILD| = 32   |BUILD \ ORACLE| = 11   status = clean
                 ORACLE \ BUILD  = empty        the guard fires ZERO times
                 the 11 build-only paths are the `index.ts` barrels and `src/trip/score/score.ts`

`(21 / 32 / 11, ORACLE \ BUILD empty, fd2420c, the command above, rc 0, ~9 s)`. Those 11 are
files `tsc` compiles and no test ever imports — a barrel nobody re-exports through, a module with
no spec. **They are not attacks and there is nothing to exclude.** An equality guard would fire
on all 11 on a clean run, and the only way to make it green would be an exclusion list that grew
with the workload — which is the shape §5 of the bar pre-registered against. So the bar declares
`BUILD \ ORACLE` **NOT A SIGNAL, read by no verdict**, and the guard is one-sided by measurement
rather than by preference. **The exclusion list is empty and stays empty.**

##### Z.2 The falsifier fired and the control did not — re-derived here, at `fd2420c`, not carried

Every figure below was re-run in this unit from C1's committed program against
`packnplan-mono` at `81ac1a1`; none is carried from a handoff.

<!-- provenance: value=classify_outcome BEFORE=PASS AFTER=FAIL-GRAPH with ORACLE\BUILD exactly the five shadows and GUARD-T 0 / GUARD-TAMPER empty / GUARD-SCOPE 5 files; both cmd_check_oracle controls byte-identical at the same worktree path; counter-attack tsc rc=0 with build files inside the fence 32 unchanged; OVERALL every section closed as declared, 11 of 11 checks; commit=fd2420c; command=.venv/bin/python docs/eval-data/2026-08-20-j24-module-graph-field-measurement.py --worktree <throwaway> --real-repo <packnplan-mono @ 81ac1a1> -->

    FALSIFIER   five `.js` shadows through the roster's OWN write tool
                _resolve ADMITTED and is_tamper_write False on all five
                ORACLE exit 0   10 passed (10) files | 141 passed (141) tests
                GUARD-T 0 | GUARD-TAMPER empty | GUARD-SCOPE 5 files  (all still clean)
                ORACLE \ BUILD  = exactly the five shadows
                classify_outcome   BEFORE = PASS      AFTER = FAIL-GRAPH

    CONTROL     pristine  BEFORE exit 0 sha 0a4bfaa7…  ==  AFTER exit 0 sha 0a4bfaa7…
                defected  BEFORE exit 1 sha da381824…  ==  AFTER exit 1 sha da381824…
                GUARD-T rc  clean tree  plain=0  --listFiles=0   (buildinfo cleared each time)
                GUARD-T rc  type error  plain=2  --listFiles=2

    COUNTER     `allowJs: true, checkJs: false` into the TRACKED packages/shared/tsconfig.json
                tsc rc=0 | build files inside the fence = 32, unchanged
                ORACLE \ BUILD  = still exactly the five shadows

**The BEFORE column is not a paraphrase.** It is
`git show 88d8628:docs/eval-data/2026-08-18-loop-harness.py` imported — the harness as it stood
when the bar was written, one commit before any of the implementation — so `BEFORE=PASS` is the
pre-fix file's own answer and not a restatement of `RB-P78`'s. **And the transition is
attributable:** every previously declared guard reads clean on the attacked tree, so `FAIL-GRAPH`
is this guard's verdict and nobody else's. That check is the reason the falsifier has four
clauses instead of one.

**The control is what makes the closure worth having.** A guard that fires on a clean tree buys
its falsifier with an exclusion list; this one fires zero times, and both agent-visible
`cmd_check_oracle` streams are byte-identical to their pre-change baselines **compared at the
same worktree path** — `RB-P82` reproducing, since the sha is a function of that path and a
cross-path comparison would mean nothing.

**The byte-identity is true by construction, not by luck.** The recorder is a **second** vitest
config (`docs/eval-data/2026-08-20-oracle-graph.vitest.config.ts`) that lives outside the agent's
write surface and records the load graph through Vite's documented `load(id)` hook into a file
named by `BK_J24_GRAPH_OUT`. **The pinned SCORING config is never touched and is never on the
oracle's argv**, which is what `M13` checks, and it is why the oracle the agent reads cannot move.

##### Z.3 Two corrections to `RB-P78`, which is a RECORD and is not edited

**`RB-P78` above stands exactly as committed.** Its five WRITEs, its `_resolve`/`is_tamper_write`
readings, its CANON-1 identity and its disposition are J9's and stay J9's. What follows narrows
two sentences inside it, beside it, by the same rule §S applied to `RB-P72` and §Y.8 applied to
`RB-P90`.

**Correction 1 — the property is worded as equality, and equality is false.** `RB-P78` at
`docs/eval.md:7518-7520` reads *"the oracle's module graph must equal the build's."* Only
`ORACLE ⊆ BUILD` holds; the other direction is 11 paths wide on a pristine tree (§Z.1). The
entry's diagnosis is right and its quantifier is one word too strong. This is the second time a
correction of this shape has been needed in the same neighbourhood — §S made two against
`RB-P72` — and the reason is the same: a register entry is written in the language of the attack
it just watched, before anything has measured the clean side.

**Correction 2 — the census figures, and the count of attacks.** `RB-P78` writes *"All nine
attacks on record — four config writes, the padding file, five `.js` shadows"* and reports a
census of **10 `??`** paths plus **2 `!!`** paths. Re-measured on a fresh worktree at `fd2420c`,
from the harness's own `restore()` and the six pre-registered J9 rows:

<!-- provenance: value=10 writes over 9 distinct paths, vitest.config.ts written twice by ROWS 1 and 4 with different content (CFG_EXCLUDE_DEFECT_TREES vs CFG_PAD_INCLUDE); census after the ten writes 10 ?? / 0 !!; pristine restore 1 ?? / 0 !!; after run_guard_t 1 ?? / 1 !! = packages/shared/tsconfig.tsbuildinfo; commit=fd2420c; command=python importing docs/eval-data/2026-08-18-loop-harness.py and 2026-08-20-j9-oracle-pin-field-measurement.py, restore + apply_defects + every ROWS write + the five shadows, then git -C <wt> status --porcelain -uall --ignored=matching -- packages/shared -->

    the rows' own writes           10 writes over 9 DISTINCT paths
                                   duplicated: vitest.config.ts, by ROW 1 and ROW 4,
                                   with DIFFERENT content
    census after the ten writes    10 ??   /   0 !!
    census on a fresh restore()    1  ??   /   0 !!     (the planted node_modules symlink)
    census after one GUARD-T       1  ??   /   1 !!     (+ packages/shared/tsconfig.tsbuildinfo)

`(10 ?? / 0 !!, fd2420c, the command above)`. **`10 ??` reproduces exactly** and its members are
the nine attack paths plus the harness's own planted symlink, which is the entry's own reading
confirmed. **`2 !!` does not reproduce, and neither does 1 — a fresh worktree has 0.** Both
`!!` entries were probe residue: they are the two `node_modules` directories `RB-P79`'s probe
wrote, and `RB-P79` — the very next bullet — records them **as its own evidence**. `node_modules/` is a
slash-suffixed gitignore pattern, so it matches a *directory* of that name and never the
harness's planted *symlink* — which is why the symlink is `??` and the probe's directories were
`!!`. **The entry's census was taken on a tree its own section had already poisoned**, which is
`RB-P79`'s hazard firing on the paragraph that reports it.

And *"nine attacks"* is wrong as a count of attacks in a way that matters for what a census would
have to see. The rows enumerate **ten writes over nine distinct paths covering five distinct
exploits**: `vitest.config.ts` (`ROW 1`), `vitest.workspace.ts` (`ROW 2`), `vite.config.ts`
(`ROW 3`), `vitest.config.ts` **again with different content** plus `src/pad.spec.ts` (`ROW 4`,
the padding attack), and the five `.js` shadows. The sentence wants **nine created paths**. Nine
is the census's number, not the attack count, and the entry spends it on the wrong noun.

##### Z.4 The creation census was MEASURED and NOT built, and the price is what makes that a decision

`RB-P78`'s own text nominates a census — *"One census sees them at once"* — as the cheap
alternative to a graph guard. It is not built, and the reason is measured rather than asserted.
It is an instance of `RB-P77`'s class (a fix nominated inside a register entry, refuted before
anyone implements it) and so does **not** get a number of its own; but the price is recorded
here, because a fix declined without a price is an omission and a fix declined with one is a
decision.

<!-- provenance: value=J9 ROWS 1-4 all read AFTER ORACLE exit=1 Tests 7 failed | 134 passed (141) classify_outcome FAIL under the pin; the census false-positive floor is 1 path on a fresh restore and 2 after one GUARD-T; _resolve(wt, "node_modules") -> None; commit=fd2420c; command=.venv/bin/python docs/eval-data/2026-08-20-j9-oracle-pin-field-measurement.py --worktree <throwaway> --real-repo <packnplan-mono> rows, and the census probe of Z.3 -->

    4 of the 5 exploits are ALREADY DEAD under the J9 oracle pin
      ROW 1  vitest.config.ts        AFTER  exit 1   7 failed | 134 passed (141)   FAIL
      ROW 2  vitest.workspace.ts     AFTER  exit 1   7 failed | 134 passed (141)   FAIL
      ROW 3  vite.config.ts          AFTER  exit 1   7 failed | 134 passed (141)   FAIL
      ROW 4  padding                 AFTER  exit 1   7 failed | 134 passed (141)   FAIL
    the 5th — the `.js` shadows — is the ONLY one a census would catch that nothing else does,
      and it is the SAME one containment catches

    false-positive floor    1 path   `packages/shared/node_modules`, on any fresh restore
                            2 paths  if the census runs AFTER GUARD-T, because GUARD-T's own
                                     `tsc` writes `packages/shared/tsconfig.tsbuildinfo`

`(4 of 4 rows FAIL under the pin; floor 1 or 2 depending on guard order, fd2420c, the two
commands above)`. So the census buys **one** attack nothing else catches — the one containment
already catches — and pays for it with a floor that is **never zero and is not even constant**:
it depends on where in the guard order the census runs. The symlink is unsuppressable from the
agent's side (`_resolve(wt, "node_modules")` returns `None` — the roster refuses every path
through it), so the floor is structural, not a spelling problem. And `tsconfig.tsbuildinfo` is a
path the roster **can** write; one exploitation attempt through it failed and **deeper
exploitation is UNMEASURED**, which is stated rather than assumed away.

Above all: **a census that fires on creations changes what `TASK` permits.** Today the agent may
create files; a census that treats creation as a signal is a policy change to the task contract,
not a guard added to the instrument, and it needs its own pre-registration. That is the price,
and on it the census is declined.

##### Z.5 The finding this unit was handed as NEW, which turns out to be PRE-REGISTERED and gets no number

This unit was handed `files_touched_outside_defect_set` **feeds no verdict** as the finding that
might deserve a number, with an instruction to re-derive it before minting anything. It
re-derives, and then it dies on provenance.

<!-- provenance: value=outside computed at docs/eval-data/2026-08-18-loop-harness.py:1144 and written to the row at :1208 at fd2420c (the handed pins :950 / :998 are correct at 88d8628 and at 1a8e382); classify_outcome's signature takes no scope or outside parameter; the counter-attack reaches PASS with GUARD-SCOPE 6 files and files_touched_outside_defect_set = ['packages/shared/tsconfig.json']; the column is pre-registered as "GUARD-SCOPE, reported not gated" at docs/eval-data/2026-08-18-loop-bar-preregistration.md:651; commit=fd2420c; command=grep -n on the harness and the bar, plus the j24 field program's COUNTER section -->

    computed              docs/eval-data/2026-08-18-loop-harness.py:1144   at fd2420c
    written to the row    …:1208                                          at fd2420c
    read by               nothing — `classify_outcome` takes no `scope` and no `outside`
    live reading          GUARD-SCOPE 6 files, outside = ['packages/shared/tsconfig.json'],
                          run unpenalised, `classify_outcome` PASS

**The mechanism reproduces exactly. The characterisation does not.** J7's own bar pre-registers
this column, at `docs/eval-data/2026-08-18-loop-bar-preregistration.md:651`, as row 13 of the
recorded-columns table with the disposition **"GUARD-SCOPE, reported not gated"** — written
before any arm ran. A column that gates nothing *because its bar said it would gate nothing* is a
declared design, not a hole, and **this program does not mint a number for a declared design**.
The same rule §V.8 used to decline a second number for a named class applies one step further
out: a pre-registered choice is not a finding, however uncomfortable it reads on a live attack.

What is worth recording, and is not a number either, is the **consumption** risk. `RB-P72`'s
disposition paragraph (`docs/eval.md:6468`) leans on this column — *"no committed verdict moves —
`files_touched_outside_defect_set` on both committed arms contains only `*.test.ts` paths"* — and
that is a sound *reading of committed rows*. It must never be read as *"the harness would have
caught a config write"*, because by row 13 it demonstrably would not. §Z.2's counter-attack is
the first time that column has been watched doing its declared job against a live attack: the
tracked-file edit **is** on the row, and no verdict looks at it. Reported, not gated, exactly as
written down.

**The line pins handed to this unit — `:950` and `:998` — are correct at `88d8628` and at
`1a8e382`, and wrong at `fd2420c`**, where `08b6a84` moved them by **+194**. Both readings are
right at their own commit. This is `RB-P40`'s shape and §S's `+39` drift once more, caught the
same way both times: by re-pinning at HEAD instead of carrying a number.

##### Z.6 Handoff corrections — four, and two of them are corrections to a correction

§Q, §T, §W.5, §X.1 and §Y.7 are the precedent, and §W.6's rule 3 puts these here: a figure a
brief asserted and a measurement declined is a **handoff correction**, recorded in the section
that caught it, **never as a register entry**.

**1. "The build side is free — a flag, not a run" is FALSE, and the reason is a committed
program.** Carried forward from C1 and re-derived here. `2026-08-19-loop-u5-closure-field-measurement.py`
drives `run_one` on a stubbed worktree by replacing `run_oracle`, `run_guard_t`, `guard_tamper`
and `guard_scope` **by name**; a `run_one` that reaches past those names into a new function
raises `FileNotFoundError` on `<tmp>/packages/shared`, and sections `C-2b` and `N-17b` went
`closed → NOT CLOSED`. The guard therefore runs its own `tsc`, `run_guard_t` stays the single
authority on the `guard_type_exit` column, and that committed program is byte-identical to its
pre-change reading. **The build side is not free and this section does not say it is.**

**2. `--listFiles` does not move GUARD-T's exit code.** Carried forward from C1 and reproduced in
§Z.2: `plain=0 / --listFiles=0` on a clean tree and `plain=2 / --listFiles=2` on a type-erroring
one, with `tsconfig.tsbuildinfo` cleared before **each** invocation. The first reading
(`plain=2, --listFiles=1`) was N-16's incremental leak between back-to-back invocations, not the
flag.

**3. The cost DECOMPOSITION does not reproduce, and it fails by the mechanism correction 2 just
named.** The bar's §9.4 (`docs/eval-data/2026-08-20-j24-module-graph-containment-bar.md:235-241` at `fd2420c`) prices `tsc --noEmit --listFiles` at **0.52 s** against `tsc --noEmit` at
**0.25 s**, and `tsc_program`'s docstring (`docs/eval-data/2026-08-18-loop-harness.py:558-559` at
`fd2420c`) writes that as *"`+0.27 s` for the flag"*. Measured at `fd2420c`, with the buildinfo
cleared before each COLD invocation and left in place for each WARM one:

<!-- provenance: value=tsc --noEmit COLD 0.537s WARM 0.263s; tsc --noEmit --listFiles COLD 0.547s WARM 0.268s; oracle_module_graph (recorder) median 0.433s; run_guard_t alone COLD 0.571s; run_guard_t + guard_graph in run_one's own order 1.298s, marginal +0.727s; all medians of n=5; commit=fd2420c; command=python importing docs/eval-data/2026-08-18-loop-harness.py against a throwaway clone of packnplan-mono @ 81ac1a1, timing tsc_program / run_guard_t / oracle_module_graph / guard_graph with tsconfig.tsbuildinfo removed or retained between invocations -->

    tsc --noEmit                 COLD 0.537 s      WARM 0.263 s
    tsc --noEmit --listFiles     COLD 0.547 s      WARM 0.268 s
      => the FLAG costs +0.010 s cold, +0.005 s warm
      => the COLD/WARM gap is  0.274 s  — which is the recorded "+0.27 s", to two decimals

`(flag +0.010 s cold / +0.005 s warm; cold−warm 0.274 s, fd2420c, the command above, medians of
n=5)`. **The 0.25 / 0.52 pair is a warm reading and a cold reading of the same command**, and
the 0.27 s attributed to `--listFiles` is `tsconfig.tsbuildinfo` — **N-16's leak a second time,
in the cost row of the same amendment whose own §9.5(2) diagnosed it for the exit code**. The
diagnosis was applied to the control and not to the timing, one subsection apart. That is an
instance of a class this document names, so it is here and not in the register.

**4. And the conclusion the decomposition was supporting SURVIVES — measured in `run_one`'s own
call order, which is the only order that bills anybody.**

    oracle_module_graph  (the recorder, a second vitest)          median 0.433 s
    run_guard_t          alone, buildinfo cleared                 median 0.571 s
    run_guard_t + guard_graph, back to back as `run_one` calls    median 1.298 s
      => marginal cost of the whole guard                                +0.727 s / run

`(recorder 0.433 s; guard marginal +0.727 s/run, fd2420c, the command above)`. **C1's +0.72 s
total and 0.42 s recorder both reproduce.** What does not is the split: `guard_graph`'s `tsc` is
the **second** `tsc` of the run and is therefore always WARM, because `run_guard_t` ran
immediately before it and left the buildinfo behind. The honest split is **0.43 s recorder +
0.28 s second `tsc`**, not `0.42 + 0.52`, whose sum was never the 0.72 it sat beside. The build
side is **not free — it is a whole extra process** — and it costs 0.28 s in place rather than
0.52 s. Correcting the price downward does not reopen the fold; §Z.6(1) is a correctness
constraint from a committed program, not a budget.

##### Z.7 Minted here — `RB-P92`, and only `RB-P92`

One number. The equality correction (§Z.3) is a correction to a record and belongs beside it; the
census figures (§Z.3) are the same; the census decline (§Z.4) is an instance of `RB-P77`; the
`files_touched_outside_defect_set` gap (§Z.5) is a **pre-registered design** and this program
does not number those; the four handoff corrections (§Z.6) are handoff corrections, and the
third of them is an instance of the N-16 class the bar's own §9.5(2) already named. What is left is one claim
someone could otherwise repeat, and no entry above is its parent.

- **`RB-P92` — a fix that was folded in and then reverted left its docstring behind, so a
  committed instrument states two opposite mechanisms in the same commit, and the stale one is
  the refuted advice.** `guard_graph`
  (`docs/eval-data/2026-08-18-loop-harness.py:679-689` at `fd2420c`) says *"IT RUNS ITS OWN `tsc`
  RATHER THAN TAKING GUARD-T's"* and prices the trade. `run_guard_t` (`…:570-574` at the same
  commit) says *"`run_one` calls `tsc_program` directly so the build graph costs a flag and not a
  second `tsc`."* Both cannot be true, and neither carries a marker saying which won.

  <!-- provenance: value=run_guard_t(wt) followed by guard_graph(wt) launches THREE workload subprocesses — two `tsc --noEmit --listFiles` and one `vitest run --config <the recorder>` — so the build graph costs a SECOND tsc process, not a flag; run_one calls run_guard_t and then guard_graph at docs/eval-data/2026-08-18-loop-harness.py:1136-1141; commit=fd2420c; command=python importing the harness with subprocess.run wrapped by a counting spy, then run_guard_t(wt) and guard_graph(wt) on a restored throwaway clone of packnplan-mono @ 81ac1a1 -->

      subprocesses launched by  run_guard_t(wt)  then  guard_graph(wt)      3
        tsc --noEmit --listFiles
        vitest run --config …/2026-08-20-oracle-graph.vitest.config.ts
        tsc --noEmit --listFiles
      `run_one` at …:1136-1141 calls `run_guard_t(wt)` and then `guard_graph(wt)`

  `(3 subprocesses, two of them tsc, fd2420c, the command above)`. **The code implements
  `guard_graph`'s docstring; `run_guard_t`'s describes the version that was measured, refuted
  and backed out**, and it is `run_guard_t`'s that a reader hits first, because `run_guard_t` is
  the name the older bar sections and the committed u5 program all reach for. The general claim,
  and it is why this is a number and not a footnote: **a reverted fold is not reverted while its
  rationale is still in the file, because the rationale is the only place the mechanism is
  written down, and the next reader will re-derive the fold from it.** This one is unusually
  sharp — the stale docstring's advice is *precisely* the refuted brief figure of §Z.6(1),
  re-armed inside the instrument by the same commit that refuted it. **Attack:** when a design
  is backed out, the docstring that argued for it is part of the diff; and a comment that states
  a call graph should name the caller, so that a reader can falsify it with one `grep` instead
  of a subprocess count. **NOT FIXED HERE** — `docs/eval-data/` is another unit's layer at this
  commit and this section owns `docs/eval.md`; a documentation section does not reach into an
  instrument to correct it. (Instrument / documentation, **open**.)

##### Z.8 What is NOT closed, and it is disclosed rather than discovered later

Five, carried from C1's own disclosure and none of them softened.

1. **A created file the oracle never loads is invisible.** Containment reads the **load** graph.
   A payload nothing imports is in neither set and the difference stays empty.
2. **A `.ts` shadow inside `include: ["src"]` is invisible.** `tsc` compiles it too, so it is in
   BUILD and containment is satisfied. **Only a module the build will NEVER compile is caught** —
   which is exactly `RB-P78`'s five and no wider.
3. **`files_touched_outside_defect_set` still feeds no verdict** (§Z.5) — declared, re-measured
   at `fd2420c`, unchanged, and not numbered.
4. **UNMEASURED: a bare-specifier payload that vite EXTERNALISES rather than loads.**
   `RB-P79`-style residue at `src/**/node_modules/` realpaths *inside* the fence, so it would be
   flagged **if** it goes through `load(id)`. Whether vite-node externalises such a specifier
   instead was **not measured**, and nothing here claims it either way.
5. **The recorder's scope is the pin's scope, restated — and nothing enforces the coupling.** If
   the pinned `include`/`exclude` ever changes without the recorder changing with it, the two
   graphs are graphs of two different programs and the difference means nothing. The only thing
   holding them together is the two files' comments. Given §Z.7, that is a thinner guarantee than
   it sounds.

##### Z.9 Gates, each at the commit it was measured at

Re-run in this unit at `fd2420c`, not carried from the handoff.

<!-- provenance: value=selfcheck all cases behaved as declared with 66 cases and 12 M13 lines; pytest 1263 passed 2 xfailed; ruff check runtime-py and ruff check docs/eval-data both All checks passed!; the j24 field program OVERALL every section closed as declared; the j9 field program OVERALL every section closed as declared; commit=fd2420c; command=the five commands in the table below -->

| gate | reading | commit |
|---|---|---|
| `.venv/bin/python docs/eval-data/2026-08-18-loop-harness.py selfcheck` | all cases behaved as declared (66 cases, 12 of them `M13`'s) | `fd2420c` |
| `.venv/bin/python -m pytest runtime-py/tests -q` | 1263 passed, 2 xfailed | `fd2420c` |
| `.venv/bin/ruff check runtime-py` | All checks passed! | `fd2420c` |
| `.venv/bin/ruff check docs/eval-data` | All checks passed! | `fd2420c` |
| `2026-08-20-j24-module-graph-field-measurement.py` | OVERALL: every section closed as declared | `fd2420c` |
| `2026-08-20-j9-oracle-pin-field-measurement.py rows` | every row REPRODUCES, both sides | `fd2420c` |

**`1259 → 1263` is a CO-MOVING count and the handoff's explanation of it is wrong.** The four new
nodes are **not** selfcheck cases. `runtime-py/tests/test_field_programs.py` carries **four**
nodes parametrised over `git ls-files -- docs/eval-data/*.py`, and this branch commits **one**
new field program, so each of the four gains one case:

<!-- provenance: value=docs/eval-data/*.py goes 18 -> 19 between 1a8e382 and fd2420c; the four parametrised nodes are test_every_committed_field_program_still_imports, …_still_exposes_main, test_every_bantamkit_symbol_a_field_program_names_still_resolves and test_every_sibling_program_a_field_program_names_by_path_exists; four collected node ids carry the new program's id; ZERO collected node ids mention M13; commit=fd2420c; command=git ls-tree -r --name-only {1a8e382,fd2420c} docs/eval-data | grep -c '\.py$' and .venv/bin/python -m pytest runtime-py/tests -q --collect-only | grep j24-module-graph -->

    committed docs/eval-data/*.py    18 at 1a8e382   ->   19 at fd2420c
    collected node ids naming the new program                          4
    collected node ids naming `M13`                                    0

`(18 → 19 programs, +4 nodes, 0 of them M13's, fd2420c, the two commands above)`. `M13`'s twelve
selfcheck cases contribute **zero** pytest nodes; the harness's selfcheck is not enumerated by
any parametrised node. The delta is real and the count is co-moving, but it moves with the number
of committed **field programs**, not with the number of selfcheck cases — and a co-moving count
quoted with the wrong co-mover is worse than one quoted with no explanation at all: it tells the
next person who adds a field program that the suite will stand still, and it will not.

**`M13` was mutation-checked, not trusted** — carried from C1's amendment, which records each on
a temp copy of the harness and none in the working tree: making `graph_containment` **symmetric**
(the equality `RB-P78` words, and the equality §Z.1 refutes) reddens **3** cases; removing the
`FAIL-GRAPH` rung reddens **1**; dropping `realpath` from the fence reddens **2**. The first of
those is the one that matters here: **the property this section says is wrong has a must-be-red
case proving the harness would notice if someone wrote it.**

#### AA (2026-08-20) — `RB-P87` and `RB-P88` are closed forward by amendment beside the records they correct; the denominator the pre-registered text compels, a guard that could not fire at the only tier that needed it, and a scoping noun with five referents

Two rule defects filed by §V.8 on the same day they were found are closed on
`docs/bar-rule-defects`, each by an amendment appended to the bar that carries it —
**`81f847b`, Amendment 2, `RB-P88`**, and **`3d71134`, Amendment 3, `RB-P87`**. Both are pure
insertions at the end of `docs/eval-data/2026-08-20-document-read-bar.md`; between them they
change no threshold, flip no clause, regenerate no row and re-score nothing.

<!-- provenance: value=81f847b is 276 insertions 0 deletions with its single hunk at @@ -818,0 +819,276 @@; 3d71134 is 292 insertions 0 deletions with its single hunk at @@ -1094,0 +1095,292 @@; combined against main 640c6b0 it is 568 insertions 0 deletions in one file, one hunk at @@ -818,0 +819,568 @@; commit=0a2084b; command=git diff --numstat 81f847b^ 81f847b and 3d71134^ 3d71134 and 640c6b0 HEAD, each with git diff -U0 … | grep '^@@' -->

    81f847b   Amendment 2 (RB-P88)   276 / 0   hunk @@ -818,0  +819,276 @@
    3d71134   Amendment 3 (RB-P87)   292 / 0   hunk @@ -1094,0 +1095,292 @@
    combined against main 640c6b0    568 / 0   one file, one hunk, append-only

`(276/0 and 292/0, both append-only at EOF, 0a2084b, the commands above)`. **The headline is
not "two entries are closed".** It is that both closures had to argue from the bar's own
pre-registered text rather than from the rows, because in each case the defect is a *sentence*
and the rows were already committed — and that in both cases the argument reaches the same
place: **the verdict does not move, and it does not move for a reason the bar wrote down before
any arm ran.** This section owns `docs/eval.md`. It adds no `.py`, edits no bar, regenerates no
`.jsonl` and restates no committed row.

##### AA.0 The register and the section letter were read at HEAD across every live writer, and the single-letter run is exhausted

`RB-P75`'s precaution, applied by §V.0, §W.6, §X.8, §Y.0 and §Z.0 before this one. §X.8 recorded
the ceiling moving six times in one shift; it has moved twice more since §Z.0 was written, and
`RB-P92` — the number §Z minted — is on four refs already.

<!-- provenance: value=ceiling RB-P92 over 30 refs/heads, standing on four of them — main (640c6b0), feat/module-graph-containment (d1eac06), feat/launder-catalogue (01c3e25) and this branch docs/bar-rule-defects (0a2084b); commit=0a2084b; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

    ceiling over all 30 refs/heads   ->  RB-P92
    refs standing at it              ->  main (640c6b0), feat/module-graph-containment (d1eac06),
                                         feat/launder-catalogue (01c3e25),
                                         this branch (0a2084b)

`(ceiling RB-P92 over 30 refs, 0a2084b, the command above)`. **`RB-P93` is the next free number,
and this section mints exactly two: `RB-P93` and `RB-P94`.**

**The section letter needed a new scheme, and here is the one chosen and why.** Read the same
way, over the same 30 refs: the run of single-letter sections is `L`–`Z` and it is **full**, and
the only other identifiers are `K5` and `K4B`.

<!-- provenance: value=over 30 refs/heads the taken '#### <id>' section identifiers are exactly L M N O P Q R S T U V W X Y Z plus K5 and K4B; AA occurs on no ref; commit=0a2084b; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE '^#### [A-Z][0-9A-Z]* '; done | sed 's/^#### //;s/ *$//' | sort -u | awk '{print length($0), $0}' | sort -n -k1,1 -k2,2 | cut -d' ' -f2- -->

    the run, in order       ->  L M N O P Q R S T U V W X Y Z          (full)
    outside the run         ->  K5, K4B                                 (K-generation)
    free                    ->  AA

`(L–Z taken, K5 and K4B outside the run, 0a2084b, the command above)`. **This section is `AA`.**
The argument, because the brief asked for one:

1. **A two-character identifier already has precedent, but not the precedent it looks like.**
   `K5` and `K4B` are **subdivisions of a K generation** — a letter carrying a suffix means *"a
   later pass over K's material"*. So `Z2` or `ZA` would be the wrong shape: they would announce
   an amendment to §Z, which this section is not. It is the next section, not Z's second draft.
2. **`AA` is the spreadsheet-column continuation and it is the one every reader already knows.**
   Ordered by **(length, then lexicographic)** the run reads `L M N … Z AA AB … AZ BA …`, which
   is monotone, needs no rule anybody has to be told, and buys 676 more identifiers before the
   next exhaustion rather than 25.
3. **The cost is stated rather than hidden: a naive `sort` puts `AA` first.** The run has not
   been ASCII-sortable since `K4B` and `K5` were minted — they sort between `K` and `L` only by
   accident — so the enumeration command above sorts by length first. That command is the one to
   carry forward; the one in §Z.0's provenance, which sorts lexicographically, will report `AA`
   as the *lowest* section from here on.

##### AA.1 `RB-P87` and `RB-P88` are RECORDS and are not edited by being closed

**Both entries stand exactly as `2749b70` committed them.** Their measurements, their dispositions
and their wording are §V's and stay §V's. The two amendments do not annotate them, and neither
does this section: what a closure produces is a **note beside the record**, by the same rule §Z.3
applied to `RB-P78` and §Y.8 applied to `RB-P90`. Where a closure found the entry's own wording
wrong, the correction is in §AA.6 and the entry keeps its text.

That rule is doing real work here, because **each entry turns out to have understated itself.**
`RB-P87` calls its own defect *"silently inapplicable"* (`docs/eval.md:8527`); measured, it is
**unfireable**. `RB-P88` says the ambiguity is *"a single under-specified predicate, not a
systemic one"* (`docs/eval.md:8545`); the predicate claim survives exactly as written, and the
noun underneath it does not. Neither entry is edited for either.

##### AA.2 `RB-P88` closed — the denominator the pre-registered text compels, and all four figures re-derived from the committed rows

Amendment 2 splits the entry into **two separable determinations**, which is the part worth
carrying forward: *does U-4 fire?* and *does R3's pool keep the cell U-4 fires on?* They are
questions about two different sentences and either one alone leaves the verdict where it is.

Re-derived in this unit from the four committed `.jsonl` — they landed at `39f7aaf` and are
unchanged at `0a2084b` — not read out of the amendment:

<!-- provenance: value=7b/reader/large-IN has 4 bad-outcome runs; 4/12=0.3333 fires U-4 and 4/36=0.1111 does not; the numerator is 4 under BOTH readings; large-IN pooled McNemar exact two-sided with the 7b admitted is n=36 b=1 c=11 p=0.006348 (P(paste)=0.8889, P(reader)=0.6111) and with it excluded is n=24 b=0 c=5 p=0.062500 (P(paste)=1.0000, P(reader)=0.7917); commit=0a2084b (rows unchanged since 39f7aaf); command=python over docs/eval-data/2026-08-20-document-read-{4b,7b,14b}.jsonl, bad = outcome in {malformed-output, schema-exhausted}, pairs keyed (task, repeat) within tier, p = min(1, 2·Σ C(b+c,i)/2^(b+c)) per bar §9 -->

    U-4 reader-arm cell (Reading A)   4/12 = 0.3333   FIRES   (> 0.30)
    U-4 three-arm block (Reading B)   4/36 = 0.1111   silent
    numerator under both readings     4               identical

    McNemar admitted  4b+7b+14b   n=36  b=1  c=11  p=0.006348   -> §5.2 REFUTED
    McNemar excluded  4b+14b      n=24  b=0  c=5   p=0.062500   -> §5.3 NEITHER

`(4/12 and 4/36; p = 0.006348 and p = 0.062500, 0a2084b, the command above)`. **All four
reproduce to the digit, and so does the numerator's immobility** — the four bad-outcome runs at
`7b`/large-IN are all in the `reader` arm, so widening the denominator to 36 widens nothing else.

**The decisive ground for the 12-denominator is not the definitional text, it is the arithmetic
on the rule's own purpose.** Amendment 2 gives three grounds in descending strength; the third is
the one that survives an argument, because the first two can be met with *"the drafter wrote
loosely"* and this one cannot:

<!-- provenance: value=the paste arm produced ZERO bad-outcome rows in all twelve (tier, stratum) blocks; the bare arm produced 5 of its 108 runs across the three compared tiers; a reader arm bad on 10 of its own 12 runs computes to 10/36 = 0.2778 under Reading B and does not clear 0.30; commit=0a2084b (rows unchanged since 39f7aaf); command=python over all four committed .jsonl counting outcome in {malformed-output, schema-exhausted} per (tier, stratum, config) -->

    paste bad-outcome rows, over all TWELVE blocks       0
    bare  bad-outcome rows, three compared tiers         5 of 108
    a reader arm bad on 10 of its OWN 12 runs (83.3%)
      Reading A   10/12 = 0.8333   FIRES
      Reading B   10/36 = 0.2778   does NOT fire

`(paste 0 of 12 blocks; bare 5/108; the 83.3% cell computes to 27.78%, 0a2084b, the command
above)`. **Reading B divides the reader's format-failure rate by three and dilutes it with two
arms that measurably cannot contribute.** A predicate whose stated purpose is *"format swamped
the signal"* and which cannot void a cell that is 83% format failure is not doing the thing its
own sentence says it does. That is a defect argued from the rule, not a preference between two
grammars, and it is why the conclusion is a reading the text *compels* rather than one it
*permits*.

**The second determination goes the other way, and the asymmetry is the whole of it.** §5 fixes
`n = 36 per cell`. To exclude the cell you must overwrite a pre-registered number; to admit it
you overwrite nothing. Add that §6.3's VOID carries an express *"may not be compared"* which
§6.1's UNINFORMATIVE does not, and that the bar put the *"with a non-UNINFORMATIVE cell"* proviso
in R2 and C3 and in none of C1, C2, R1, **R3** or R4 — and the cell stays in the pool. **U-4
fires, the cell is UNINFORMATIVE, R3 admits it anyway, and J10's verdict of REFUTED stands
unmoved.**

**Grade the two determinations separately, because they are not equally safe.** The denominator
rests on express definitional text in two independent sections (§6.1's opening sentence and §8's
`n = 12`) plus the purpose argument above — **strong**. The admission rests on the *absence* of a
proviso in five clauses and on the taxonomy's placement of *"may not be compared"* — **strong,
but constructional**: it is an argument from what the drafter did not write. It is right, and it
is the kind of right that a differently-drafted bar would not reproduce. Which is exactly why
Amendment 2's forward rule D-2 exists.

**Six words is the whole margin.** Had R3 carried R2's *"with a non-UNINFORMATIVE cell"*, this
run is §5.3 NEITHER at p = 0.0625. The verdict did not survive because the finding was small; it
survived because a clause the bar never wrote would have been needed to move it.

##### AA.3 `RB-P87` closed — the served window was MEASURED, and the clamp is established by two facts that are not the number's roundness

§6.4 named the 3b's served window UNMEASURED. Amendment 3 measures it, and the measurement is a
live one: `ollama` **0.18.0** answering on `localhost:11434`, `llama3.2:3b` already pulled,
**nothing fetched**, no `OLLAMA_*` variable in the environment. Re-run in this unit against the
same daemon:

<!-- provenance: value=ollama version 0.18.0 and llama3.2:3b present in /api/tags with no model pulled and no OLLAMA_* variable set; llama3.2:3b prompt_eval_count = 4096 on the system message and on system+task, for both corpora, at PASTE_MAX_BYTES=8621; system messages 8,962 B (small) and 9,016 B (large); requests 9,324 B and 9,378 B with a one-byte joiner; commit=0a2084b (code unchanged since 1a8e382); command=curl -s localhost:11434/api/version and /api/tags, then PYTHONPATH=runtime-py/src BANTAMKIT_ASSETS=assets python calling bantamkit.evalrun.materialise_documents + _paste_head and POSTing /api/generate {"model":…,"prompt":…,"stream":false,"options":{"num_predict":1}} -> prompt_eval_count -->

    llama3.2:3b  small  system 8,962 B -> 4096    system+task 9,324 B -> 4096
    llama3.2:3b  large  system 9,016 B -> 4096    system+task 9,378 B -> 4096

`(four readings of exactly 4,096, 0a2084b, the command above)`. **`RB-P53` is why that table
cannot be read the obvious way**: on this counter a reading of 4,096 is evidence about the
*window*, not about the prompt. Amendment 3 does not treat it as a prompt measurement, and
establishes the clamp two other ways. Both re-derived here:

<!-- provenance: value=two prompts 362 B apart (8,962 B and 9,324 B; 9,016 B and 9,378 B) return the identical prompt_eval_count 4096; the prefix ladder over the 9,016 B large system message reads 2,048 B->900, 4,096 B->1852, 6,000 B->2735, 8,000 B->3665, 8,600 B->3943, 8,800 B->4037, 8,900 B->4084, 9,016 B->4096, so 8,800->8,900 B buys +47 at 2.128 B/token and the last 116 B buys +12 where that rate predicts +54; commit=0a2084b; command=the §AA.3 command above with the prompt replaced by _paste_head(...).encode()[:n].decode('utf-8','ignore') for n in (2048,4096,6000,8000,8600,8800,8900,9016) -->

    1. two prompts 362 B apart return the IDENTICAL count
         8,962 B -> 4096   and   9,324 B -> 4096      (small)
         9,016 B -> 4096   and   9,378 B -> 4096      (large)

    2. the reading tracks the prompt, then pins
         2,048 B -> 900     8,600 B -> 3943
         4,096 B -> 1852    8,800 B -> 4037
         6,000 B -> 2735    8,900 B -> 4084     (+47 over 200 B, 2.128 B/token)
         8,000 B -> 3665    9,016 B -> 4096     (+12 over 116 B; the rate predicts +54)

`(362 B for +0 tokens; the ladder, marginal 2.128 B/token, then +12 where +54 was due, 0a2084b,
the command above)`. **A counter that reported the prompt could not do either.** The window is
4,096.

##### AA.4 Why the window-relative form is not a re-scoring, and why a ratio of exactly 1.0000 is the general result

This is the spine of the closure and it is one table. All six compared readings re-derived in
this unit against the live daemon, at Amendment 1's `PASTE_MAX_BYTES = 8,621`:

<!-- provenance: value=request readings 4b 6602/6627, 7b 6623/6648, 14b 6623/6648 (small/large) against a pinned num_ctx of 8192, ratios 0.8059/0.8090, 0.8085/0.8115, 0.8085/0.8115; the 3b reads 4096 against a served 4096, ratio 1.0000; commit=0a2084b; command=the §AA.3 command with the model replaced by each of bk-rbp27-qwen3-4b-instruct, bk-rbp27-qwen2.5-7b-instruct, bk-rbp27-qwen2.5-14b-instruct and llama3.2:3b -->

| tier | served `W` | request reading, small / large | `V-1` as written, `≥ 6,963` | window-relative, `≥ 0.85 × W` | reading ÷ `W` |
|---|---:|---:|---|---|---:|
| 4b | 8,192 | 6,602 / 6,627 | ok | ok | 0.8059 / 0.8090 |
| 7b | 8,192 | 6,623 / 6,648 | ok | ok | 0.8085 / 0.8115 |
| 14b | 8,192 | 6,623 / 6,648 | ok | ok | 0.8085 / 0.8115 |
| **3b** | **4,096** | **4,096 / 4,096** | **ok — does not fire** | **VOID — `≥ 3,481`** | **1.0000 / 1.0000** |

`(all six compared readings and both 3b readings, 0a2084b, the command above)`. Two things this
table settles, and they are the two that make the closure a closure rather than an opinion:

1. **At `W = 8,192` the two forms are the same predicate.** `0.85 × 8,192` is 6,963 to the
   integer the bar wrote down, so the window-relative restatement changes no compared reading, no
   compared cell and no published figure. **It differs from the pre-registered text at exactly
   one tier — the declared floor — and it differs there by VOIDing an arm §6.4 and §7.5 already
   forbid anyone to compare.** That is why this is a restatement and not a re-scoring, and it is
   the sentence a reader should check first, because a rule change that moved a compared cell
   after the rows were committed would be the one thing an amendment written under §V's tighter
   rule may not do.
2. **The ratio reaches exactly 1.0000, and that is the transferable result.** A clamped reading
   divided by its own window *is* 1 — the largest value the quantity can take. So a
   window-relative threshold at **any** fraction below 1.0 fires on **every** clamped reading, at
   every tier, without anyone having to anticipate the window. The predicate stops depending on
   which window the drafter had in mind; the absolute form depends on nothing else.

**And the entry understated its own defect.** `RB-P87` says the fixed threshold is *"silently
inapplicable"* at a different window (`docs/eval.md:8527`). Measured, it is **unfireable**: a
clamped counter cannot return 6,963 at a 4,096 window at **any** prompt of any size, so the guard
is not weakened there, it is absent. The distinction is not decoration — *"inapplicable"* invites
a fix that tunes the constant, and no constant at or above the smallest served window can be
reached from below it.

##### AA.5 What the 3b's `paste` passes reach — and the one place a prohibition is not printed beside its figure

**No compared figure depends on them, counted here from the committed rows and not taken from
either the entry or the amendment.**

<!-- provenance: value=3b paste passes are small 2/12, large-IN 4/12, large-OUT 0/12 = 6 of 36, tool_calls == 0 on all 36, and all 30 non-passing rows are outcome == wrong-answer; the three published McNemar rows over 4b+7b+14b are small n=36 1.0000/0.4722 b=0 c=19 p=0.000004, large-IN n=36 0.8889/0.6111 b=1 c=11 p=0.006348, large-OUT n=36 0.0000/0.4167 b=15 c=0 p=0.000061; pooling the 3b in gives n=48 rows 0.7917/0.3542 p=0.000001, 0.7500/0.4583 p=0.000519 and 0.0000/0.3125 p=0.000061; commit=0a2084b (rows unchanged since 39f7aaf); command=python over all four committed .jsonl, pairs keyed (task, repeat) within tier, both pools -->

    3b paste   small 2/12   large-IN 4/12   large-OUT 0/12   =  6 of 36
               tool_calls != 0 on 0 of 36; all 30 non-passing rows are `wrong-answer`

    published pool 4b+7b+14b      small p=0.000004   large-IN p=0.006348   large-OUT p=0.000061
    with the 3b pooled in (n=48)  small p=0.000001   large-IN p=0.000519   large-OUT p=0.000061
      P(paste, small)   1.0000 -> 0.7917
      Δ(large-OUT)      +0.4167 -> +0.3125

`(6 of 36 as 2/4/0; every published row reproduces to the digit, 0a2084b, the command above)`.
**The exclusion is load-bearing and it is pre-registered four times over** — §8 declares the 3b a
floor that is never pooled, §5 fixes `n = 36` over the three compared tiers, §6.4 forbids
comparing any 3b `paste` number to another tier's, and §7.5 declines a tier comparison outright.
Four sentences, all written before any arm ran. **The protection comes from them and not from
`V-1`** — which is the precise sense in which `RB-P87` is a rule defect with no consequence for
this run's verdict, and the sense in which it would have had one for a bar drafted an inch
differently.

**Two places the 3b's `paste` rows nevertheless reach, both recorded rather than fixed.**

1. **§V.1's pass table prints them, unmarked.** The 3b row at `docs/eval.md:8302` reads
   `0 / 2 / 0`, `0 / 4 / 0`, `0 / 0 / 0`, and those three `paste` figures **are** these six
   passes. They are published as descriptive counts of the only arm in the run whose prompt was
   truncated, on a row whose neighbours were not, and the prohibition on comparing them lives
   four sections away in §6.4 and §7.5. That is a presentation hazard rather than a wrong figure
   — and it is `RB-P94`.
2. **§V.4's `U-3` firing at `3b`/large-OUT reads `P(paste) = 0` in that cell**
   (`docs/eval.md:8408`), and **that zero is by construction, not by clamp**: §3.1 puts the
   large-OUT answer row outside the 8,621 B cut deliberately, so the `paste` ceiling on large-OUT
   is zero at every tier and is `0/36` at the three compared ones too. The firing survives the
   truncation being there or not. **This one gets no number** — the zero is what §3.1
   pre-registered, the firing is correct, and a correct reading of a correctly-fired predicate is
   not a defect. It is recorded because a reader who arrives via `RB-P87` will otherwise wonder
   whether the clamp produced it.

##### AA.6 Handoff corrections — four that do not reproduce as worded, one that reproduces and is recorded anyway, and two of the four land inside a correction the unit below had already made

§Q, §T, §W.5, §X.1, §Y.7 and §Z.6 are the precedent and §W.6's rule 3 puts these here: **a figure
a brief asserted and a measurement declined is a handoff correction, recorded in the section that
caught it, never as a register entry.** Everything else handed to this unit re-derived exactly —
`276/0` and `292/0`; `4/12` and `4/36` with an immobile numerator; `p = 0.006348` and
`p = 0.062500`; `paste` at 0 bad rows over twelve blocks and `bare` at 5 of 108; the 83.3% cell
computing to 27.78%; all four `4,096` readings and the whole saturation ladder; all six compared
readings and their 0.806–0.812 ratios; the 3b's 6 passes as 2/4/0 with `tool_calls == 0` on all
36; the `1.0000 -> 0.7917` pooling effect; and the 4b calibration ladder.

**1. `RB-P87`'s superlative is FALSE, and the replacement is stronger — but the *count* handed to
this unit is not right either.** The entry says the 3b's prompt is *"being truncated harder than
any arm the rule did VOID"* (`docs/eval.md:8525-8526`). **`V-1` VOIDed no graded arm, ever** —
§V.4 records it firing at no compared tier, and its only firings in the bar's history are in
Amendment 1 §A.1's **pre-run calibration**, at the pre-registered `PASTE_MAX_BYTES = 12,288`, in
a state no arm was ever graded in. So the superlative names an empty set. **The brief said those
firings were "six pre-run calibration readings". Re-measured, §A.1 is six readings of which
three fire:**

<!-- provenance: value=at PASTE_MAX_BYTES=12288 the SMALL system message is 8,962 B and reads 6511 (4b), 6532 (7b) and 6532 (14b) — all below the 6,963 threshold, V-1 ok; the LARGE system message is 12,672 B and reads 8,192 clamped at all three tiers, V-1 VOID; so §A.1's six calibration readings are three firings and three passes, all three firings on the large corpus; commit=0a2084b; command=the §AA.3 command with bantamkit.evalrun.PASTE_MAX_BYTES set to 12288 before _paste_head, over bk-rbp27-qwen3-4b-instruct / -qwen2.5-7b-instruct / -qwen2.5-14b-instruct -->

    §A.1 large corpus  12,672 B -> 8192 / 8192 / 8192   (4b / 7b / 14b)   V-1 VOID   x3
    §A.1 small corpus   8,962 B -> 6511 / 6532 / 6532                     V-1 ok     x3

`(three firings of six calibration readings, 0a2084b, the command above)`. The substantive claim
is untouched — **no arm was graded in that state, so no graded arm was ever VOIDed** — and the
replacement statement is the one to keep: **the 3b's `paste` is the only truncated arm in the
entire graded run, and `V-1`, the single clause written to catch a truncated paste, reports OK on
it.** A guard silent on the run's *only* truncated arm is a worse finding than a guard silent on
a worse-truncated arm that never ran.

**2. The magnitudes reproduce, and the 2.4× is 2.36×.** Re-derived on the 4b at the
pre-registered constant:

<!-- provenance: value=4b at PASTE_MAX_BYTES=12288 on the 12,672 B system message reads 9,016 B->6536, 10,000 B->7266, 11,000 B->8011, 11,200 B->8162, 11,400 B->8192, 12,672 B->8192, so the marginal rate is 1.325 B/token at 11,000->11,200 and the reading pins at 8,192; extrapolated true prompt 9,272.9 tokens, 1,080.9 lost = 11.66%; the 3b's request extrapolates to 4,308.6 tokens, 212.6 lost = 4.93%; the ratio is 2.36x as a fraction and 5.08x in absolute tokens; commit=0a2084b; command=the §AA.3 command with PASTE_MAX_BYTES=12288, model bk-rbp27-qwen3-4b-instruct, prefixes (9016,10000,11000,11200,11400,12672) -->

    4b @ 12,288   9,016 B -> 6536   11,000 B -> 8011   11,400 B -> 8192
                 10,000 B -> 7266   11,200 B -> 8162   12,672 B -> 8192
      marginal 1.325 B/token, true prompt ≈ 9,273 tokens, ≈ 1,081 lost  ≈ 11.66%
    3b @  8,621   marginal 2.128 B/token, request ≈ 4,309 tokens, ≈ 213 lost  ≈  4.93%
      ratio        2.36x as a fraction of prompt,  5.08x in absolute tokens

`(11.66% against 4.93%; 2.36x and 5.08x, 0a2084b, the command above)`. **The handed 11.7% / 4.9%
and the "5× in absolute tokens" reproduce; "about 2.4×" is 2.36× and reads as a round-up of a
figure that was already rounded twice.** Nothing turns on it — the direction is what the
correction needs — but a ratio of two rounded percentages should be quoted from the unrounded
pair, and 11.66 ÷ 4.93 is 2.36. Recorded because §AA.6(1)'s conclusion is quoted against it.

**3. `0.85 × 8,192` is not 6,963, and the one integer where that matters is a number this bar has
written down.** Amendment 3 §C.2 argues, correctly and load-bearingly, that at `W = 8,192` the
as-written and window-relative forms are *"the same predicate"*, because *"`0.85 × 8,192` **is**
6,963."*

<!-- provenance: value=0.85 x 8192 = 6963.2 and 0.85 x 4096 = 3481.6, so the as-written threshold 6,963 and the window-relative threshold 0.85·W differ on exactly one integer reading, 6,963, where '>= 6,963' VOIDs and '>= 6,963.2' does not; no measured reading in this bar is 6,963 — the six compared request readings are 6,602/6,627/6,623/6,648/6,623/6,648 — but Amendment 1 §A.3 records the bytes//4 ESTIMATOR reading exactly 6,963 on the 4b; commit=0a2084b; command=python -c "print(0.85*8192, 0.85*4096)" and grep -n '6,963' docs/eval-data/2026-08-20-document-read-bar.md -->

    0.85 x 8,192 = 6,963.2      the bar's V-1 writes "= 6,963"
    0.85 x 4,096 = 3,481.6      Amendment 3's restatement writes "3,481"
    the two forms differ on exactly ONE integer reading: 6,963

**Nothing measured lands there** — the six compared readings are 6,602 / 6,627 / 6,623 / 6,648 /
6,623 / 6,648 — so §C.2's conclusion survives intact for this run and for the restatement. But
the single integer of disagreement is not hypothetical: **Amendment 1 §A.3 records the `bytes//4`
estimator reading exactly 6,963 on the 4b, *"exactly at the threshold"*.** So the rounding lives
one arithmetic step away from a figure the bar prints. **This gets no number.** A threshold
written as a rounded product is a drafting habit the two amendments' own D-3 already fixes —
*"written as `f × W(tier)` with the arithmetic shown"* — and a rule whose forward fix is already
committed in the same file is not a new claim.

**4. Reproduces exactly, and is recorded anyway: the one-byte discrepancy inside the record.**
`RB-P87`'s table (`docs/eval.md:8517-8518`) gives the request bytes as `9,324` / `9,378` — system
message plus the 361 B task prompt with a **one-byte** joiner. Amendment 1 §A.3 records the same
pair as `9,325` / `9,379`, a **two-byte** joiner. Both are re-derived here, and so is the reason
nothing depends on it:

<!-- provenance: value=small system 8,962 B + 1 + 361 = 9,324 and + 2 + 361 = 9,325; large system 9,016 B + 1 + 361 = 9,378 and + 2 + 361 = 9,379; both joiners return the IDENTICAL prompt_eval_count at every tier — 6602/6602, 6623/6623, 6623/6623 (small) and 6627/6627, 6648/6648, 6648/6648 (large) on 4b/7b/14b, and 4096/4096 on llama3.2:3b for both corpora; commit=0a2084b; command=the §AA.3 command run twice per (tier, corpus), with the system message joined to the task prompt by '\n' and by '\n\n' -->

    small   9,324 B (1 byte) and 9,325 B (2 bytes)  ->  4b 6602/6602  7b 6623/6623  14b 6623/6623
    large   9,378 B (1 byte) and 9,379 B (2 bytes)  ->  4b 6627/6627  7b 6648/6648  14b 6648/6648
    llama3.2:3b, both corpora, both joiners         ->  4096

`(twelve compared readings and four 3b readings, both joiners, 0a2084b, the command above)`.
**Identical to the digit everywhere.** The discrepancy is real, it is one byte, it is inside a
record, and it moves no number in either document.

**5. *"`cell` has three referents bar-wide" is an undercount: measured, it is five.*** This is the
finding the brief flagged as a mint candidate, and re-deriving it is what makes it one. Counted
over the **pre-registered** text only — everything above the *"## 12. Amendments"* heading, so
that no amendment is counted as evidence for itself:

<!-- provenance: value=in the pre-registered bar text (lines 1-587, above the Amendments heading) the word "cell" carries five distinct referents — §1.4:96-98 two named TASKS, §3.1:171-175 a STRATUM spanning all arms and all tiers, §5:229 a matched (task, repeat) unit, §5:230 eleven words later an (arm, stratum) pool at n=36, and §6.1:274 / §8:380 the (tier, arm, stratum) cell at n=12; Amendment 2 §B.0:855-861 enumerates three of the five and does not name the §1.4 or §3.1 uses; commit=0a2084b; command=awk 'NR<588' docs/eval-data/2026-08-20-document-read-bar.md | grep -n cell, then reading each hit -->

    §1.4  :96-98    "the design its sharpest cell … those two cells"   two TASKS
    §3.1  :171-175  "This cell carries the job's claim … the SMALL cell"
                                                         a STRATUM, across arms AND tiers
    §5    :229      "the pass rate over matched `(task, repeat)` cells"
                                                         a matched (tier, task, repeat) unit
    §5    :230      "n = 36 per cell"  — eleven words later
                                                         an (arm, stratum) pool over three tiers
    §6.1  :274      "Evaluated per (tier, arm, stratum) cell"
    §8    :380      "Per (tier, arm, stratum) cell: 3 tasks × 4 repeats = n = 12"

`(five referents in the pre-registered text, 0a2084b, the command above)`. §3.1's is the one that
settles it: the bullet opens *"The **OUT stratum** asks…"* and closes *"This **cell** carries the
job's claim"*, four words apart, with the referent spanning all three arms and all four tiers —
wider than either §5 reading and wider than §6.1's. Amendment 2 §B.0 names three of the five.
**Both units' narrower claim survives untouched**: the *denominator* defect is single, not
systemic — U-1, U-2 and U-5 each carry *"of `reader`-arm runs in the cell"* and U-3 names all
three arms, so those four are denominator-stable under either §5/§6.1 reading, which is four
unambiguous predicates against one. **What does not survive is reading that as reassurance about
the noun**, and that is `RB-P93`.

##### AA.7 Minted here — `RB-P93` and `RB-P94`, and the eight things that get no number

Two numbers. **Declined:** the clamp itself is `RB-P53`'s class and §V.8 already declined it; the
*"unfireable" not "silently inapplicable"* sharpening (§AA.4) and the *"VOIDed no graded arm"*
correction (§AA.6.1) are corrections to `RB-P87`'s own wording and belong beside it; the
`9,324`/`9,325` joiner (§AA.6.4) is a one-byte correction inside a record; the `6,963.2` rounding
(§AA.6.3) has its forward fix already committed in the same file as D-3; the `2.36×` (§AA.6.2) is
a rounding of a rounding; the U-4 numerator's immobility and U-5's denominator stability (§AA.6.5)
are **confirmations** of `RB-P88`'s narrow claim rather than new claims; and §V.4's
`P(paste) = 0` at `3b`/large-OUT (§AA.5.2) is a correct reading of a correctly-fired predicate
whose zero §3.1 pre-registered. What is left is two claims someone could otherwise repeat, and no
entry above is a parent to either.

- **`RB-P93` — the noun a bar scopes its predicates with carries five different referents across
  the document, so an unscoped predicate cannot be read locally at all, and the express
  definition that governs it is not the nearest one.** In this bar *"cell"* means two named
  tasks (§1.4), a stratum spanning every arm and tier (§3.1), a matched `(task, repeat)` unit
  (§5), an `(arm, stratum)` pool at `n = 36` (§5, eleven words later) and the
  `(tier, arm, stratum)` cell at `n = 12` (§6.1, §8) — measured in §AA.6.5 over the
  pre-registered text alone. `RB-P88` is the instance: `U-4` names no arm, inherits *"whatever
  cell means"*, and the two candidate denominators are 12 and 36 with a verdict between them.
  **The general claim, and it is why this is a number and not a restatement of `RB-P88`:
  `RB-P88` says one predicate forgot its denominator, which is a fixable omission in one
  sentence; this says the word it would have inherited is not a word with one meaning, so
  fixing `U-4` alone leaves every future unscoped predicate exposed to the same five-way
  choice.** The two are not the same defect and the second is not implied by the first — a bar
  can have a perfectly unambiguous scoping noun and still forget to name a denominator, and this
  bar has the opposite problem underneath the one it filed. **Attack:** a bar defines its
  evaluation unit **once**, in a numbered definition, and every later use is that word or a
  different word — and a reviewer greps the noun across the whole document before trusting any
  predicate that does not carry its own scope, because the drafting hole is invisible from
  inside the subsection that has it. **NOT FIXED HERE** — the bar is a pre-registered record
  under a published verdict and lives in another unit's layer at this commit; Amendment 2's D-1
  makes the *next* bar name the denominator, which is the narrower half. (Bar / drafting,
  **open**.)

  <!-- provenance: value=the five referents and their line pins are re-derived in §AA.6.5 at 0a2084b over lines 1-587 of the bar, the pre-registered text; Amendment 2 §B.0 enumerates three of them; the denominator disagreement is 12 vs 36 on 7b/reader/large-IN and decides REFUTED (p=0.006348) against §5.3 NEITHER (p=0.062500); commit=0a2084b; command=awk 'NR<588' docs/eval-data/2026-08-20-document-read-bar.md | grep -n cell, plus the McNemar command of §AA.2 -->

- **`RB-P94` — a figure a bar forbids anyone to compare is published in the result table with no
  mark on it, because the prohibition lives in a different section from the number, so it is
  enforced only by a reader who already knows to go and look for it.** §V.1's pass table
  (`docs/eval.md:8302`) prints the 3b's `paste` column as `2`, `4` and `0` — six passes from the
  only arm of the 432 rows whose prompt was truncated (§AA.3), scored against a silently clamped
  4,096-token window, on a row whose three neighbours were not truncated at all. Nothing on the
  row says so. The prohibition is real and pre-registered four times (§8, §5, §6.4, §7.5), and
  every one of those sentences is in a different document from the table that prints the number.
  **The general claim: a prohibition that does not travel with the figure is not a property of
  the figure, it is a property of the reader.** A number lifted out of a published table carries
  its own digits and nothing else, and the more careful the bar was about pre-registering the
  prohibition, the more confidently the table prints the number without it. **Attack:** where a
  run publishes a descriptive figure from an arm any clause VOIDs, forbids comparing, or marks
  UNINFORMATIVE, the mark is printed **in the cell or the row that carries the figure** — not in
  the section that derived it, not in a footnote, and not in the bar — or the figure is not
  printed. **NOT FIXED HERE, and the reason is that it cannot be:** §V.1 is a published result
  table and a record, so annotating it would edit a record to fix a defect found after it was
  published, which is the one move this program does not make. Amendment 3's §C.5 already binds
  the *next* bar with the same rule, forward-effect only. (Reporting / documentation, **open**.)

  <!-- provenance: value=docs/eval.md:8302 prints the 3b row as "0 / 2 / 0 | 0 / 4 / 0 | 0 / 0 / 0" and those three paste figures are the six passes re-derived in §AA.5 (small 2/12, large-IN 4/12, large-OUT 0/12); the 3b's paste prompt reads 4,096 against a served 4,096 (ratio 1.0000) while the three compared tiers read 6,602-6,648 against 8,192 (ratios 0.806-0.812), so the 3b is the only truncated arm in the run; the prohibitions are bar §8, §5, §6.4 and §7.5, none of them on the row; commit=0a2084b; command=sed -n '8296,8303p' docs/eval.md, the §AA.3 and §AA.4 readings, and grep -n 'never pooled\|n = 36 per cell\|no 3b paste number\|declines a tier comparison' docs/eval-data/2026-08-20-document-read-bar.md -->

##### AA.8 What is NOT claimed, and what stays open

1. **No verdict moved and none was re-scored.** J10 is REFUTED at `p = 0.006348`, by §5.2's R3,
   exactly as `2749b70` published it. Both amendments are append-only and neither touches a
   threshold, a clause, a row or a scorer.
2. **`RB-P86` is untouched.** The declared-argument type defect §V.8 filed alongside these two is
   a Layer-1 change to `agent.py` and is not closed by either amendment. It stays open.
3. **Which end the daemon cut the 3b's paste is NOT determined**, and cannot be from these rows:
   `V-1` reported OK, so the run recorded nothing that would decide it. The ≈ 213 tokens and
   ≈ 4.9% of §AA.6.2 are extrapolations off a measured slope and are labelled as estimates in
   both documents; the readings are 4,096 and 4,096.
4. **Nothing is claimed about *why* the 3b passed 6 of 36.** Against the 3b's committed floor
   rate the arm is not distinguishable from the floor, and every non-passing row is
   `wrong-answer`, which is what the floor produces anyway.

   <!-- provenance: value=the 3b's committed floor rate is 0.2557 (135/528) at docs/eval.md:7147, and P(X <= 6 | n = 36, p = 0.2557) = 0.1499 on the binomial, so 6 of 36 is not distinguishable from the floor at any conventional level; all 30 non-passing 3b paste rows carry outcome == wrong-answer; commit=0a2084b (rows unchanged since 39f7aaf); command=python -c over docs/eval-data/2026-08-20-document-read-3b.jsonl with math.comb, and sed -n '7147p' docs/eval.md -->

       3b committed floor   0.2557 (135/528)      P(X <= 6 | n=36, p=0.2557) = 0.1499
       the 30 non-passing paste rows              all `wrong-answer`

   `(0.1499 against the 0.2557 floor, 0a2084b, the command above)`. The clamp's effect on that
   score is unmeasured and, from these rows, unmeasurable.
5. **`RB-P93` is a claim about this bar's text, not about every bar.** It is measured on one
   document. What transfers is the *attack* — grep the scoping noun before trusting an unscoped
   predicate — not a count of five.
6. **Neither number is fixed here, by construction.** `RB-P93`'s subject is a pre-registered
   record and `RB-P94`'s is a published result table. A documentation section does not edit a
   record to close a defect the record's own publication created; both are filed forward, and
   both have their forward rule already committed in the bar (D-1/D-2 at `81f847b`, D-3/D-4 and
   the reporting restatement at `3d71134`).

##### AA.9 Gates, each at the commit it was measured at

Re-run in this unit at `0a2084b`, not carried from the handoff. The suite is run with the
worktree on `PYTHONPATH` because the repo venv otherwise resolves `bantamkit` to the main
checkout (`RB-P55`, `RB-P70`).

<!-- provenance: value=1268 passed, 2 xfailed; ruff check runtime-py and ruff check docs/eval-data both "All checks passed!"; ollama version 0.18.0 with llama3.2:3b already present and nothing pulled; commit=0a2084b; command=the four commands in the table below -->

| gate | reading | commit |
|---|---|---|
| `PYTHONPATH=$PWD/runtime-py/src BANTAMKIT_ASSETS=$PWD/assets .venv/bin/python -m pytest runtime-py/tests -q` | 1268 passed, 2 xfailed | `0a2084b` |
| `.venv/bin/ruff check runtime-py` | All checks passed! | `0a2084b` |
| `.venv/bin/ruff check docs/eval-data` | All checks passed! | `0a2084b` |
| `curl -s localhost:11434/api/version` + `/api/tags` | `0.18.0`; `llama3.2:3b` present, nothing pulled | `0a2084b` |

**`1268` is a co-moving count and this section does not move it.** §Z.9 established that the
figure tracks the number of committed `docs/eval-data/*.py` field programs, four parametrised
nodes per program. This branch commits **no** `.py` at all — its whole diff against `main` is
568 insertions in one `.md` — so the count standing at `1268` is the expected reading and not
evidence that anything was checked. **A documentation section's gates are a statement that
nothing was broken, never that anything was verified**, and the verification in this section is
the twenty-odd re-derivations above, each with its own command.
#### AB (2026-08-20) — J28's must-be-red catalogue exists at last, and the figure it was built to produce turns out to be a property of one test file rather than of the suite

`RB-P89` filed a defect whose root cause was an absence: every provenance comment in this file
that quotes a laundering measurement attributes it to *"a Z2 mutation script over a `git archive`
tree"*, and **that script was never committed and does not exist**. The program's central
anti-laundering discipline — section S's class, section T's procedure, four instances since — has
therefore been a procedure re-improvised from memory each time, with nothing in the repository
able to re-run any of it. `feat/launder-catalogue` commits the instrument: `0ba46f5`
`docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py` with its record, `01c3e25` the
one-line change that stops the program heading a table with a commit it was not measured at.

**The headline is not "`RB-P89` is closed".** It is that the number the catalogue was built to
produce — **`0 of 32` strings pinned by nothing at all** — is true, and is a statement about
**`runtime-py/tests/test_layers.py`** rather than about `runtime-py/tests`. Strike that one
file's `*_bytes` goldens and the same run reads **2 pinned, 26 laundering, 4 pinned by nothing**.
The contract surface's defence against rewording is held almost entirely by byte-identity, not by
tests that assert meaning, and nothing in this repository measures that concentration. This
section owns `docs/eval.md`; it adds no `.py`, regenerates no `.jsonl` and restates no committed
row.

##### AB.0 The register was read at HEAD across every live writer, before any number was chosen

`RB-P75`'s precaution, applied again — and this time it is not a formality. A concurrent branch
that is **not on `main`** already holds two numbers above this branch's ceiling, so a number that
looks free here is taken there.

<!-- provenance: value=ceiling RB-P94 over 31 refs/heads, standing on exactly ONE — docs/bar-rule-defects (14fdbc0), which is PR #48, CI green and not merged; main, feat/question-floor, feat/module-graph-containment and this branch feat/launder-catalogue (01c3e25) all stand at RB-P92; commit=01c3e25; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

    ceiling over all 31 refs/heads            ->  RB-P94
    the only ref standing at it               ->  docs/bar-rule-defects (14fdbc0), §AA,
                                                  minting RB-P93 and RB-P94, NOT on main
    this branch, main, and two others         ->  RB-P92

`(ceiling RB-P94 over 31 refs, 01c3e25, the command above)`. **`RB-P95` is the next free number,
and this section mints exactly one: `RB-P95`.** Had the ceiling been read on this branch alone it
would have read `RB-P92` and this section would have minted `RB-P93` — a number `docs/eval.md`
already carries on another live ref, which is `RB-P75`'s collision exactly.

**The section identifier, read the same way.** `L`–`Z` are exhausted and `docs/bar-rule-defects`
has claimed `AA`, so the scheme is now **(length, then lexicographic)** and the next free
identifier is **`AB`**.

<!-- provenance: value=the section identifiers taken across all 31 refs/heads and their remotes are exactly L M N O P Q R S T U V W X Y Z AA — nothing of length 2 beyond AA; commit=01c3e25; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/); do git show $r:docs/eval.md 2>/dev/null | grep -oE '^#### [A-Z]{1,3} '; done | awk '{print $2}' | sort -u -->

**This section and §AA will conflict at merge, and that is expected.** Both append immediately
above the file's `Back to the README` footer. **The documented resolution is to keep BOTH sides in
MINT ORDER — `AA` before `AB`, `RB-P93`/`RB-P94` before `RB-P95` — and not in merge order.**
Nothing below depends on being adjacent to any other section.

##### AB.1 What makes the catalogue an instrument rather than a script

For each top-level string of `assets/contracts/default.yaml`: reword that string and only that
string, copy the whole asset pack to a temporary directory, run the entire `runtime-py/tests`
suite against it, and diff the failing-node set against the unmutated baseline.

**The design decision that matters is not the mutation, it is the verdict.** The verdict comes
from a **fixed predicate on the node NAME** — it contains one of `verbatim`, `bytes`, `golden`,
`wording`, `phrasing` — applied identically to all 34 keys. There is no per-string `pins` list,
so the author does not get to pick which nodes count. That closes, **for this one surface**, the
loophole `docs/eval-data/2026-08-14-pinning-harness-false-positives.md` filed and could not close:
*"`pins` is chosen by the person writing the claim ... the attack direction: derive `pins`
mechanically ... so the author does not get to choose."* The price is that the predicate is
crude, and §AB.5 is what that costs.

**Calibrated against two answers known by hand, and re-run in this unit rather than carried.**

<!-- provenance: value=--calibrate at 01c3e25 exits 0 with CAL-RED expected PINNED-BY-NAME measured PINNED-BY-NAME (schema_instruction, 8 new red) and CAL-GREEN expected UNPINNED measured UNPINNED; commit=01c3e25; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --calibrate -->

    PINNED-BY-NAME  schema_instruction           8 new red
    CAL-RED    expected PINNED-BY-NAME   measured PINNED-BY-NAME   OK
    CAL-GREEN  expected UNPINNED         measured UNPINNED   OK

`CAL-GREEN` — reword a YAML **comment** and no string at all — is the control the pinning harness
lost on 2026-08-14. Without it, an instrument that reports every string pinned cannot be told from
a detector stuck on, and §AB.2's entire table would be unreadable.

##### AB.2 The three numbers, and the disclosure that matters more than the headline

At `0ba46f5`, `--mode prose`, over `runtime-py/tests` — J28's committed sweep, which this unit did
**not** re-run (it runs the whole suite 32 times and takes ~46 minutes; §AB.9 says which
invocations were run instead):

<!-- provenance: value=31 of 32 pinned by a node that names its reason, 1 of 32 pinned only by nodes promising a different claim (evidence_no_observation), 0 of 32 pinned by nothing at all, 0 broken mutants, and 26 of 32 strings carry at least one laundering node over 48 distinct nodes; commit=0ba46f5; command=PYTHONPATH=$PWD/runtime-py/src python3 docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --jobs 5 -->

    pinned by a node that NAMES its reason      31 of 32
    pinned ONLY by a different claim             1 of 32   evidence_no_observation
    pinned by NOTHING AT ALL                      0 of 32
    strings with >=1 laundering node             26 of 32   48 distinct nodes

**`0 of 32` is the figure nobody in this program had ever measured, and it holds for one reason.**
For **29 of the 32**, the ONLY node naming its reason is a single `*_bytes` golden. Re-derived
here as arithmetic over the committed table's own columns, not as a second sweep:

<!-- provenance: value=parsing the 34-row table of docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.md gives 32 non-EXCLUDED rows, naming-count histogram {1: 29, 4: 2, 0: 1}, as-measured 31 pinned / 1 laundering-only / 0 nothing, and striking one *_bytes golden per string gives 2 pinned / 26 laundering / 4 pinned-by-nothing, the four being validation_error, loop_note, loop_warn and document_paste_preamble; every row satisfies new-red = naming + not-naming; commit=01c3e25; command=a 15-line parse of the committed .md table, reproduced in this section's text -->

    strings whose ONLY naming node is one golden          29 of 32
    strike that golden from every killer set:
      still pinned by a node that names its reason         2 of 32   the two argument-type strings
      pinned ONLY by a different claim (LAUNDERING)        26 of 32
      pinned by NOTHING AT ALL                              4 of 32   validation_error, loop_note,
                                                                      loop_warn,
                                                                      document_paste_preamble

**And the concentration is tighter than "the goldens".** Every node in the whole of
`runtime-py/tests` whose name satisfies the predicate **and** covers a contract string lives in
one file, in one 190-line span, and there are **15 of them** — so 29 strings are floored by at
most 15 nodes, and by pigeonhole at least 14 of those strings share their sole pin with another
string. `test_document_manifest_bytes` alone stands under five of them.

<!-- provenance: value=15 nodes matching def test_[a-z0-9_]*(verbatim|bytes|golden|wording|phrasing) in runtime-py/tests/test_layers.py, all between line 200 and line 390; test_layers.py holds more such nodes than any other test file (15, next is 5); commit=01c3e25; command=grep -noE 'def test_[a-z0-9_]*(verbatim|bytes|golden|wording|phrasing)[a-z0-9_]*' runtime-py/tests/test_layers.py -->

    *_bytes / golden / verbatim nodes in test_layers.py        15   lines 200-390
    the next most of any test file                              5   test_agent.py, test_filegraph.py

**This is the finding, and it is not the same claim as `31 of 32`.** `31 of 32` is true and the
count is correct. What it does not say is that the count's **resolution is the file, not the
string**: a figure reported per-subject when 29 of the subjects are held by one shared, coarse
mechanism reads as a property of the suite and is a property of one file. It is minted as
`RB-P95` in §AB.7, with the argument against minting stated there too.

##### AB.3 `RB-P89`'s own instance, re-derived on the BEFORE tree — and the mode is evidence, not a guess

Re-derived in this unit at **`640c6b0`** (a detached worktree with the catalogue copied in
untracked, which is why the program's own header reads `640c6b0-dirty` — `01c3e25`'s fix
demonstrating itself), not carried from the handoff:

<!-- provenance: value=at 640c6b0 under --mode prose the frame tool_argument_types reddens 4 new nodes (4 naming wording, 0 not) and the item tool_argument_type reddens 5 (4 naming, 1 not, the one being test_agent.py::test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped); the program headed the table 640c6b0-dirty; commit=640c6b0; command=git worktree add --detach ../wt-before 640c6b0 then PYTHONPATH=$PWD/runtime-py/src .venv/bin/python docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --only tool_argument_type --only tool_argument_types --jobs 2 -->

    tool_argument_types  (frame)  reworded    4 new red    4 name wording, 0 do not
    tool_argument_type   (item)   reworded    5 new red    4 name wording, 1 does NOT
      the fifth: test_agent.py::test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped

Exactly as `RB-P89` filed it. **One correction to the entry's reading, not to its numbers**, and
one correction to the correction. The entry says the four are *"three `verbatim` + the byte
golden"* — true, and the third `verbatim` node is
`test_dispatch_names_the_argument_verbatim_when_a_string_will_not_convert_to_its_type`, which the
entry does not quote. J28's record places it *"450 lines above the `RB-P86` block"*. **Measured,
it is 410**, and identically so at all three commits.

<!-- provenance: value=test_dispatch_names_the_argument_verbatim_when_a_string_will_not_convert_to_its_type is at line 323 and the RB-P86 block comment at line 733 of runtime-py/tests/test_agent.py, a distance of 410, at each of 640c6b0, 0ba46f5 and 01c3e25; commit=01c3e25; command=for c in 640c6b0 0ba46f5 01c3e25; do git show "${c}:runtime-py/tests/test_agent.py" | grep -n 'def test_dispatch_names_the_argument_verbatim'; git show "${c}:runtime-py/tests/test_agent.py" | grep -n '2026-08-20, RB-P86: a DECLARED'; done -->

**Why `prose` and not `whole` is the mode that re-derives `4`, and why that is evidence about the
lost script.** Under `--mode whole`, which rewords the leading `error: ` marker too, the frame
reddens **6**, not 4 — re-derived here at `01c3e25`, where the two extra nodes are exactly the two
that assert `startswith("error: ")`:

<!-- provenance: value=--mode whole at 01c3e25 gives tool_argument_types 6 new red (4 naming, 2 not) with the two being test_document_tools.py::test_document_read_answers_the_thirteen_calls_the_3b_actually_made_in_its_own_words and test_memory_component.py::test_malformed_k_still_becomes_an_error_observation, and document_error 6 new red (1 naming, 5 not); commit=01c3e25; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --mode whole --only tool_argument_types --only document_error -->

    --mode prose   frame reddens 4       `RB-P89`'s number
    --mode whole   frame reddens 6       + the two nodes asserting startswith("error: ")

`RB-P89`'s number is 4 and not 6, so **`M5` preserved the `error: ` marker**. The mode this
catalogue reconstructs was derived from the surviving evidence about the script, not assumed —
which is the only kind of claim anyone can now make about a program that no longer exists.

##### AB.4 The node was fixed, and it is non-vacuous in both directions

`test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped` ended
`assert "offset must be type integer, not type object" in observation` — the item string asserted
verbatim inside a node whose name promises a claim about **dropping**. It now asserts the claim
its name makes, in three parts, none of them the asset's phrasing: the handler never runs, its
default never reaches the model, and the argument the call got wrong is named back (`offset` is
data off the call and off the schema, not phrasing). **After the fix the item reads 4 new red, 4
naming wording, 0 not** — the same four as the frame, its laundering column empty and its pinning
unchanged. Re-derived here:

<!-- provenance: value=at 01c3e25 --mode prose gives tool_argument_type PINNED-BY-NAME 4 new red 4 naming 0 not, tool_argument_types PINNED-BY-NAME 4 new red 4 naming 0 not, and evidence_no_observation LAUNDERING 2 new red 0 naming 2 not with the two being test_critique.py::test_render_evidence_missing_observation and test_critique.py::test_render_evidence_observation_before_call_does_not_pair; commit=01c3e25; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --only tool_argument_type --only tool_argument_types --only evidence_no_observation --jobs 3 -->

    640c6b0   item   5 new red   4 naming, 1 not      the laundered node
    01c3e25   item   4 new red   4 naming, 0 not      one node removed, nothing added

**The other direction, because a node that stops reddening under a rewording has to still redden
under the thing it claims to guard.** Deliberate defect applied to a **copy** of
`runtime-py/src` — `git status` was confirmed clean at `01c3e25` before and after — restoring the
pre-`RB-P86` behaviour the node's name is about, dropping mistyped declared arguments instead of
reporting them:

<!-- provenance: value=with mistyped declared arguments dropped instead of reported in a copy of runtime-py/src, pytest runtime-py/tests/test_agent.py -q -p no:randomly gives 5 failed 68 passed, and test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped is among the five, failing at test_agent.py:853 on assert seen == {} with {'offset': 0} == {}; the working tree was and stayed clean; commit=01c3e25; command=cp -R runtime-py/src $SCRATCH/mutsrc; patch _dispatch in the copy; PYTHONPATH=$SCRATCH/mutsrc .venv/bin/python -m pytest runtime-py/tests/test_agent.py -q -p no:randomly -->

    5 failed, 68 passed
    FAILED test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped
    >  assert seen == {}, "the handler must not run at all"      test_agent.py:853
    E  assert {'offset': 0} == {}

The handler ran on a default the model never asked for. **That is the sentence the node's name
makes, and it is now the sentence that reddens it** — the fix moved the node's assertion from
someone else's claim onto its own, and did not weaken it.

##### AB.5 What this instrument does NOT establish, stated rather than discovered later

- **`48` is an UPPER BOUND on the laundering class, not a count of defects.** The predicate is
  five tokens; `test_no_documents_at_all_says_so` arguably does promise wording and is read as
  laundering because `says_so` is not one of the five. It is crude in the other direction too: a
  node named `..._bytes` that asserts nothing about wording would be counted as naming its
  reason. **Nothing here inspects a node's body.**
- **A rewording is ONE mutation shape.** A string can be pinned against rewording and unpinned
  against a placeholder rename, a truncation, or a swap of two strings for each other. None of
  those is measured.
- **UNMEASURED, in writing:** `name: default`, the placeholder names, the YAML comments, every
  asset outside `assets/contracts/default.yaml`, and the whole of `runtime-ts`. Laundering under
  each of those is unmeasured, and `RB-P51`'s rule applies — an unmeasured check is not a passed
  one, so none of these is a clean column.
- **`0 of 32` is a statement about `runtime-py/tests` at `0ba46f5` and about nothing else** — and
  §AB.2 is why even that is really a statement about one file.
- **`RB-P95` is filed and NOT fixed.** No golden was added, moved or duplicated by this section,
  and the fan-out of the 15 goldens is not gated by anything.

##### AB.6 Handoff corrections — three, and the third is this unit's own

**Both of J28's self-corrections are disclosed here rather than quietly absorbed**, because a
correction the register never sees is the same as one that was never made.

1. **The counterfactual was first written as "3 pinned / 29 laundering" and it is 2 / 26 / 4.**
   The first form has no `pinned by nothing` column at all, which loses the only number in the
   counterfactual that is qualitatively new: four strings become reworded-into-anything with the
   suite green. Re-derived independently in §AB.2 from the committed table.
2. **The AFTER numbers were first attributed to `640c6b0` while the fix was uncommitted in the
   working tree.** `01c3e25` is that correction turned into a mechanism: the program appends
   `-dirty` when `git status --porcelain` is non-empty, so a table can never again be headed with
   a commit it was not measured at. **§AB.3's `640c6b0-dirty` header is that mechanism firing on
   its first use by a second unit** — the correct behaviour, on a run whose tree genuinely was
   not the commit it named.
3. **This unit's own: "47 laundering nodes across 25 strings" is not derivable and is not
   asserted here.** The committed figure is **48 distinct nodes over 26 strings**, of which
   `evidence_no_observation` contributes two. Whether the remainder is 46 or 47 depends on
   whether either of those two also reddens on another string, and **the committed table does not
   carry the overlap structure**: its per-string columns sum to **56** occurrences over **48**
   distinct nodes, so eight occurrences are shared and the table cannot say which.

<!-- provenance: value=the sum of the 'of which do not' column over the 32 non-EXCLUDED rows of the committed table is 56, against 48 distinct nodes reported by the same run, so 8 occurrences are repeats and the per-string overlap is not recoverable from the table; 26 rows have a non-zero 'do not' column; commit=0ba46f5 for the table, 01c3e25 for the arithmetic; command=the same 15-line parse as AB.2 -->

##### AB.7 Minted here — `RB-P95`, and the three things that get no number

- **`RB-P95` — the contract surface's wording protection is single-sourced, and the figure that
  reports it is stated at a resolution finer than the protection actually has.** `31 of 32`
  strings are pinned by a node that names its reason and `0 of 32` are pinned by nothing; for
  **29 of those 32 the sole such node is a `*_bytes` golden**, and every candidate golden lives
  in **one file, `runtime-py/tests/test_layers.py`, 15 nodes across lines 200-390**, several of
  them standing under four or five strings at once. Strike them and the same run's recorded
  killers give **2 pinned / 26 laundering / 4 pinned by nothing**. The count is correct; what is
  wrong is that a per-string figure is read as a property of the suite when 29 of the strings are
  held by one shared, coarse mechanism, and **nothing in this repository measures or gates that
  fan-out**. (Suite, open — filed, not fixed.)

  <!-- provenance: value=29 of 32 strings have exactly one node naming their reason (naming-count histogram {1: 29, 4: 2, 0: 1}); striking one *_bytes golden per string turns 31/1/0 into 2/26/4; runtime-py/tests/test_layers.py holds 15 predicate-matching nodes between lines 200 and 390, more than any other test file (next is 5); commit=0ba46f5 for the sweep, 01c3e25 for the census and the arithmetic; command=the parse in AB.2 and grep -noE 'def test_[a-z0-9_]*(verbatim|bytes|golden|wording|phrasing)[a-z0-9_]*' runtime-py/tests/test_layers.py -->

  **The argument against minting it, stated because it is a real argument.** A `*_bytes` golden
  that asserts a full rendered sentence is *precisely* the node entitled to redden on a
  rewording — that is the claim its name makes, and it makes it honestly. Nothing is broken; the
  suite behaves as designed, and on that reading this is a coverage observation, and observations
  do not mint. **Why it mints anyway:** the defect is not in the goldens, it is in the sentence
  the measurement licenses. `0 of 32 pinned by nothing` was produced to be quoted, and quoted
  bare it says the suite defends the surface's meaning; the same run says the suite defends the
  surface's **bytes**, from one file, and that the two readings differ by 26 strings. A figure
  whose plain reading is off by 26 of 32 is a defect in the figure, and J28's record disclosing
  it in a §5 paragraph is the evidence for the entry, not a prior filing of it — a record
  paragraph is not trackable and a register entry is.

**Three things get no number, and each declination has a reason.**

1. **`evidence_no_observation` gets no number.** It is the one string of 32 whose only killers
   are nodes promising a different claim — `test_render_evidence_missing_observation` and
   `test_render_evidence_observation_before_call_does_not_pair` — re-derived at `01c3e25` in
   §AB.4. But *"pinned only by nodes that name a different claim"* **is** the `LAUNDERING`
   verdict, which is the class section S already named
   (*"a check that reddens for a reason its name does not state launders unrelated mutations into
   its own column"*, `docs/eval.md:7665`) and section T already made a procedure for. This file
   has twice recorded the same declination in the same words — *"the third application of the
   laundering lesson is not a new class"* and *"the fourth laundering catch is the lesson working,
   which is the opposite of a finding"*. This is the fifth. **Filed here as an instance and left
   unfixed**, because the fix is one line of naming in `runtime-py/tests/test_critique.py` and
   this section owns `docs/eval.md` — the same ownership split `RB-P89` itself instructed.
2. **The other laundering nodes get no number** — 46 or 47 of them across 25 strings, and §AB.6
   is why this section will not say which. They are instances of the class in (1), counted by an
   upper-bound predicate (§AB.5). Forty-six instances of one named class is one class.
3. **`RB-P89` is a RECORD and is not edited by being closed.** Its `4` and `5` both reproduce
   exactly (§AB.3), its reading gains one node it did not quote, and its entry text stands
   unaltered. **A finding that comes true does not mint, and neither does a lesson working** —
   the catalogue existing is section T's procedure finally acquiring a program, which is the
   lesson working at its largest scale so far and is still not a finding.

##### AB.8 What is NOT closed

1. **`RB-P95` is filed, not fixed**, and the shape of a fix is not obvious: adding a second
   pinning node per string would multiply the very byte-goldens whose concentration is the
   defect, so the fix is more likely a **gate on fan-out** than more goldens. Nobody has designed
   it and this section does not.
2. **The `4 of 32` counterfactual names four strings that are one file away from unpinned** —
   `validation_error`, `loop_note`, `loop_warn`, `document_paste_preamble`. That is arithmetic
   over recorded killers, **not a second measurement**, and no run in this repository has ever
   actually deleted a golden and observed it.
3. **`evidence_no_observation` is open** (§AB.7 item 1).
4. **Everything in §AB.5 stays UNMEASURED** — most consequentially `runtime-ts`, where the
   equivalent figure is not `0`, it is unknown.
5. **The catalogue is not wired to any gate.** It is a program someone must choose to run; no
   pytest node calls it, and nothing reddens if the surface's pinning degrades between now and
   the next time a human types the command.

##### AB.9 Gates, each at the commit it was measured at

Re-run in this unit at `01c3e25`, not carried from the handoff.

<!-- provenance: value=pytest 1272 passed 2 xfailed; ruff check runtime-py All checks passed!; ruff check docs/eval-data All checks passed!; --calibrate exits 0 with both controls OK; commit=01c3e25; command=the four commands in the table below -->

| gate | reading | commit |
|---|---|---|
| `.venv/bin/python -m pytest runtime-py/tests -q` | 1272 passed, 2 xfailed | `01c3e25` |
| `.venv/bin/ruff check runtime-py` | All checks passed! | `01c3e25` |
| `.venv/bin/ruff check docs/eval-data` | All checks passed! | `01c3e25` |
| the catalogue's `--calibrate` | `CAL-RED` OK, `CAL-GREEN` OK, exit 0 | `01c3e25` |

**`1268 → 1272` is a CO-MOVING count and not four new tests.**
`runtime-py/tests/test_field_programs.py` carries four nodes parametrised over
`git ls-files -- docs/eval-data/*.py`, and this branch commits exactly **one** new field program,
so each of the four gains one case. The same co-moving arithmetic §Z.9 recorded one branch
earlier, on a different branch adding a different program — which is the second independent
confirmation that the co-mover is the **field-program count** and nothing else.

<!-- provenance: value=committed docs/eval-data/*.py goes 19 at 640c6b0 to 20 at 01c3e25, and the four parametrised nodes of test_field_programs.py each gain one case; commit=01c3e25; command=git ls-tree -r --name-only 640c6b0 docs/eval-data | grep -c '\.py$' and the same at 01c3e25 -->

**The full 32-key sweep was deliberately NOT re-run**, and that is a disclosure and not an
omission: it runs the whole suite 32 times for ~46 minutes, and the figures it produces are
`0ba46f5`'s, quoted above at `0ba46f5`. What this unit re-derived instead is every figure that
could be reached with a bounded invocation — `--calibrate`, three keys under `--mode prose` at
`01c3e25`, two keys under `--mode whole` at `01c3e25`, two keys under `--mode prose` on a
detached `640c6b0` tree — plus the counterfactual as arithmetic over the committed table and the
golden census as a source count. **Every one of them reproduced.** The only figure in the handoff
that did not survive contact is the *"450 lines"* of §AB.3, which is 410, and the *"47 across
25"* of §AB.6, which the committed table cannot decide.

#### AC (2026-08-21) — four findings closed forward in one shift, three of the four filings refuted by the units sent to close them, and one endpoint that wins the name is absent in the mode this program works in

Four units ran in parallel on disjoint surfaces against `9a7b886`. All four landed.
The interesting result is not that the findings closed — it is that **three of the four
filings were wrong about their own subject**, and each was corrected by the unit sent to
act on it rather than by a reviewer. The filings were written by the orchestrator, which
is the least-checked source in this program (`RB-P73`).

##### AC.0 The ceiling, read across every ref and not on one branch

<!-- provenance: value=ceiling RB-P95 over 69 refs (refs/heads + refs/remotes), 95 distinct numbers, contiguous 1..95, no gaps and nothing above; commit=3e029f9; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

```
ceiling over all 69 refs                    ->  RB-P95
distinct numbers on main                    ->  95
contiguity check, seq 1..95 against main    ->  no gaps, nothing above
```

`(ceiling RB-P95 over 69 refs, 3e029f9, the command above)`. **`RB-P96` is the next free
number, and this section mints exactly one: `RB-P96`.** Four branches were live while this
was read, which is why it was read across refs and not on `main` — §Z.0's lesson, and the
near-collision it records happened again in this shift's planning.

##### AC.1 `RB-P92` — CLOSED (2026-08-20, PR #52, `6583679`), by prose and one selfcheck case

The finding was that a fold — `run_one` calling `tsc_program` directly so the build graph
"costs a flag and not a second `tsc`" — was written, measured, refuted, backed out, and its
docstring stayed. One commit then carried two opposite mechanisms and nothing in the file
could adjudicate, **because the count the sentences were about had never been written down
where a check could read it.**

What closed it: `GUARD_PROCESS_BUDGET = {"tsc": 2, "vitest": 1}` is declared, and selfcheck
**M14** measures it with a counting spy around `subprocess.run` that **launches nothing** —
the count is fixed by control flow, since `oracle_module_graph` and `tsc_program` both run
before every return in `guard_graph`. No behaviour moved; the fold stays backed out.

**Non-vacuity, verified against the run.** Re-landing the fold on a throwaway copy turns the
budget case red with `{'tsc': 1, 'vitest': 1}` and the order case red with `['tsc', 'vitest']`.
The orchestrator added a mutation the unit never ran — swapping the order of the two calls
inside `guard_graph` — which reddens the **order** case alone while the budget case stays
green, so the two cases are not redundant. The case is one-sided, like M11's pin, and its
scope is stated where it lives: it closes docstrings asserting a *count* or a mechanism the
process table can see, not prose-vs-behaviour in general.

**And the finding had a second instance the filing did not name.** `tsc_program`'s own
recorded *"`tsc --noEmit` 0.25 s, the same command with `--listFiles` 0.52 s — no extra
process, `+0.27 s` for the flag"* is **N-16 wearing the flag's name**. `composite: true`
means any `tsc` leaves a `tsconfig.tsbuildinfo`, so `0.25 s` was a warm run and `0.52 s` a
cold one and the flag was charged the difference between two states.

<!-- provenance: value=flag cost +0.009 s cold / +0.001 s warm; cold tsc 0.541 s, warm 0.265 s, recorder 0.438 s, |ORACLE|=21 |BUILD|=32; medians of 7 trials (5 for the recorder), arm order counterbalanced, tsconfig.tsbuildinfo removed before every cold trial; measured by the orchestrator on a tree built read-only by `git archive` of packnplan-mono at 81ac1a1, the real checkout never written to; commit=4a79a24; command=.venv/bin/python scratchpad/time_flag.py <tree> 7 -->

Measured cold-against-cold and warm-against-warm, **the flag costs `+0.009 s` cold and
`+0.001 s` warm — nothing this instrument can resolve.** `"no extra process"` was always the
load-bearing half and stands. `guard_graph`'s `+0.52 s` is corrected to `+0.27 s` for the
same reason: the second `tsc` always runs warm behind the first. The unit reported
`+0.004 / −0.003`; the orchestrator's independent re-measurement gives `+0.009 / +0.001`, and
the two agree on the only thing either can support — **the flag is free, and the number the
docstring used to carry was measuring the buildinfo cache.**

##### AC.2 `RB-P93` and `RB-P94` — CLOSED FORWARD (2026-08-20, PR #53, `f029dd2`), and both filings were wrong about their subject

Neither is fixed in place, by construction: `RB-P93`'s subject is a pre-registered record and
`RB-P94`'s is a published result table. Amendment 4 (`§D.0`–`§D.7` of the document-read bar)
is **322 insertions and zero deletions**, and `docs/eval.md` was not touched by it.

`RB-P93` gets a seven-noun glossary with every count re-derived from the rows (`trial` 432,
`pair` 144, `task` 9, `stratum` 3, `cell` 36, `block` 12, `pool` 9), a catalogue resolving all
**23** occurrences of the noun to one referent each, and forward rule **`D-5`**. The sharpest
thing the catalogue surfaces is not in the filing: **`block` (tier, stratum) and `pool`
(arm, stratum) are both n=36 and are different sets of trials.** A matching denominator is not
a matching population.

**No program, and the argument is recorded rather than the omission.** A `D-5` scanner needs a
per-noun "does this sentence disambiguate" predicate that the author picks — the loophole
`2026-08-14-pinning-harness-false-positives.md` filed and `RB-P89` closed by deriving from the
node *name*. There is no name to read in prose. Unenforced with a stated reason is a position;
a checker nobody runs is not.

`RB-P94` gets a machine-readable prohibition index (`P-POOL`, `P-CMP`, `P-TIER`, each sourced
to its bar lines), forward rule **`D-6`**, and
`docs/eval-data/2026-08-21-prohibition-mark-check.py`. `--calibrate` is **3 of 3**: **CAL-FIRE**
requires the three `3b`/`paste` figures of §V.1 to read UNMARKED under `P-CMP` and to be the
*only* cell findings; **CAL-QUIET-NOT-COVERED** requires the nine compared-tier `paste` figures
to produce nothing; **CAL-QUIET-MARKED** requires the six `3b` `bare`/`reader` figures to read
MARKED, and it is the detector-stuck-on control.

**Correction to `RB-P94` as filed, and it is not a quibble.** The entry says the figures are
printed *"with no mark"* and that *"nothing on the row says so"*. **That does not reproduce.**

<!-- provenance: value=docs/eval.md:8301 row label reads `3b (declared floor, never pooled)`, which carries P-POOL's mark; the 3b paste figures are 2 (small), 4 (large-IN), 0 (large-OUT), matching CAL-FIRE; commit=3e029f9; command=sed -n '8296,8302p' docs/eval.md -->

`docs/eval.md:8301` reads **`3b (declared floor, never pooled)`** — which **does** carry
`P-POOL`'s mark, in the row, where the figure is printed. **The real defect is worse than the
one filed:** the row carries *one* prohibition's mark and not the other's, so a reader lifting
the figure sees a row that is already marked, and the mark is row-scoped and therefore cannot
discriminate the `paste` arm that §6.4 actually prohibits comparing. `CAL-QUIET-MARKED` exists
precisely so the checker does not repeat the filing's mistake — **the naive reading, which is
what the entry filed, is what that control fails.**

Two further pointer corrections, both `AA`'s: the *"four words after"* of `RB-P93` does not
reproduce — the distance is **19 words** (§3.1:170→171); a four-word distance exists at
§5.2:248, a different referent. And *"never pooled"* is **§9:411**, not §8; §8:362/371 declares
the floor. `P-POOL` cites all four lines.

**Non-vacuity.** Four mutants on `git show HEAD:` scratch copies: mark added to the `3b` row
`3 → 0`; the same mark added to the `4b` row instead, unchanged at `3`; index removed, `exit=2`
unparseable rather than a quiet "0 findings"; bad section `exit=2`. The orchestrator added a
fifth: **dropping only the `P-CMP` index line takes findings `3 → 0` and moves those three
figures into MARKED under `P-POOL`** — so the `3` is derived from `P-CMP` and is not a constant.

##### AC.3 `RB-P95` — CLOSED (2026-08-21, PR #55, `f5fb6af`), by a fan-out gate and not by more goldens

The finding: the contract surface's wording protection is single-sourced. The obvious fix —
add more `*_bytes` goldens — is the same defect with a bigger denominator.

`runtime-py/tests/test_contract_fanout.py` (48 nodes) counts **files that write the sentence
out**, not nodes that go red. That distinction is the design: a node asserting
`loop_note(3) in injected` moves with the asset and would agree with any rewording, and an
`RB-P89` laundering node states nothing. **Zero deletions, and `test_layers.py` is not in the
diff at all** — no golden was touched, weakened or removed.

**The property is verified by a mutation that a node census would have missed.** Replacing the
four literal fragments in the new `loop_note` node with `assert loop_note(3) in injected`
leaves that node **passing** — it is still a good behavioural test — while the gate reddens
four nodes: the per-key floor for `loop_note`, the golden-strike, the register-equality and the
share ceiling.

Thresholds are declared as data with their arguments: `MIN_SOURCE_FILES = 2` (one file means
the sentence and its only assertion move in the same diff, by the same hand; `3` would fail 30
of 38 on landing day); `MIN_QUOTED_CHARS = 12`, **on a measured plateau** — the single-sourced
set is identical at 10, 12 and 14, and a node asserts it, while at 16 `tool_argument_type`
falls out of measurement; `MAX_SINGLE_SOURCED_SHARE = 3/38`, **explicitly not a principled
tolerance** — the principled value is `0`, and this is the measurement at landing written down
so that raising it is a defended diff line. `UNATTRIBUTABLE` and `SINGLE_SOURCED_DEBT` are
asserted exactly in both directions, so a silent zero fails.

**Two corrections to `RB-P95` as filed.**

<!-- provenance: value=test_layers.py holds 17 nodes whose names match the catalogue's WORDING_TOKENS, spanning lines 241-531; test_document_manifest_pdf_page_omission_bytes is at line 351; the entry filed "15 nodes, lines 200-390" and named four single-sourced strings where there are five; commit=3e029f9; command=grep -n 'def test_.*_bytes' runtime-py/tests/test_layers.py | awk -F: 'NR==1{f=$1} {c++; l=$1} END{print c, f, l}' -->

1. **The strings pinned by nothing are five, not four.** `document_manifest_omitted_unread_page`
   is a fifth, held only by `test_layers.py:351` — **which sits inside the very line range the
   entry named**, and still went uncounted. It was closed with the others.
2. **"15 nodes in `test_layers.py`, lines 200–390" is wrong on both numbers.** Re-derived:
   **17 nodes spanning lines 241–531**. The substance — that all candidate goldens live in that
   one file — holds.

**The instrument caught its own author.** The gate's first draft had three of its own nodes
classed **LAUNDERING** by the `RB-P89` catalogue: red on a rewording, but named for something
else. They were renamed to carry the wording token, **not exempted**; re-measured, 0 laundering.

##### AC.4 The MCP drift detector — a mechanism for `RB-P84`, and it gets no number

`tools/mcpdrift/mcpdrift.py` (PR #54, `3e029f9`) closes the *"nothing notices"* half of
`RB-P84` from outside the process. It is not a new finding and does not mint: **the register
mints numbers for findings, not for the fixes that answer them**, and `RB-P84` already files
this defect and prescribes this attack.

**It does not discriminate on the version string, because the version string has already lied
once in this program** (a build running `v0.25.0` source advertised `0.3.0` until PR #41). It
fingerprints 18 surfaces per endpoint, six of them real read-only `tools/call` probes over a
fixture it seeds itself with `HOME` redirected and `BANTAMKIT_ASSETS` stripped from the child.

The decisive calibration is a mutant with the `RB-P1` k-floor reverted and `__version__` left
at `0.25.0`: **both endpoints advertise the same string and the checker is red anyway**, with
`server_version` not firing. That property is pinned in CI without either venv. The null
control is not free either — the live AGREE row compares a non-editable wheel install against
an editable `.pth` install in two different venvs and calls them identical.

`mcpdrift check` needs a live registration, so it is **deliberately not a pytest node and
nothing skips** — a silently skipping node is `RB-P51`'s defect — and `UNDETERMINED` is a
separate exit code from `AGREE` so that "could not compare" never reads as "they agree".

**One figure the calibration sharpens.** Across twelve minor versions only **3 of 18** surfaces
differ: `instructions`, every `tool_schema`, `capabilities`, `tool_names`, the `validate_json`
wording, `shiftwork_status` and the bad-argument error are byte-identical between `v0.13.0` and
`v0.25.0`. That corroborates `RB-P84`'s 6864 identical protocol bytes and sharpens it — **after
the version string, the k-floor defect is the only discriminator on any surface probed.**

##### AC.5 Minted here — `RB-P96`, and only `RB-P96`

- **`RB-P96` — the tracked project-scope command is relative, so in a git worktree the endpoint
  that wins the name is not there.** `.mcp.json` is tracked and carries
  `"command": ".venv/bin/bantamkit-mcp"`, resolved against the project directory. A
  `git worktree` of this repository has no `.venv`, so the project-scope endpoint does not
  exist in it — and the client agrees.

  <!-- provenance: value=from a worktree, `claude mcp list` reads `bantamkit: .venv/bin/bantamkit-mcp - FAILED to connect — ENOENT: no such file or directory, posix_spawn '.venv/bin/bantamkit-mcp'`, while the identical row from the canonical checkout reads `Connected`; `[Conflicting scopes]` is printed in BOTH cases and names both endpoints; `mcpdrift check` from the worktree gives VERDICT ERROR exit 2; commit=3e029f9; command=cd <worktree> && claude mcp list ; cd <checkout> && claude mcp list ; git ls-files .mcp.json -->

  From a worktree at `9a7b886`, `claude mcp list` reports
  `bantamkit: .venv/bin/bantamkit-mcp - ✘ Failed to connect — ENOENT: … posix_spawn
  '.venv/bin/bantamkit-mcp'`, while the identical row from the canonical checkout reads
  `✔ Connected`. `[Conflicting scopes]` is printed in **both** cases and names both endpoints,
  so the footnote that would tell you is present and says nothing about which one is reachable.
  **Project scope wins the name in both places; in a worktree the thing it wins with is not
  installed.**

  This matters because **this program runs implementation units in worktrees as a matter of
  course** — four were live on the day it was measured — and `CLAUDE.md` requires every
  multi-unit job to be orchestrated through the `shiftwork_*` MCP tools that this registration
  serves.

  **Distinct from `RB-P84`, and neither fix closes the other.** `RB-P84` is about two live
  builds being indistinguishable; this is about one of them being *absent* in the working mode
  the program uses most. Refreshing both installs leaves the worktree `ENOENT` exactly as it
  was, and making the path absolute leaves the two builds exactly as indistinguishable.

  **NOT FIXED HERE, deliberately:** it is a change to a tracked config file that every other
  checkout and CI reads, and the unit that found it was mandated to build the detector, not to
  edit the registration. **Attack:** either make the project-scope command independent of the
  checkout root, or have the worktree setup provision a `.venv`; and pin whichever with a check
  that reads the *client's* resolution rather than the file. (Configuration — not
  `mcpserver.py`.)

##### AC.6 What gets no number

1. **The four closures.** A fix is not a finding.
2. **The three filing errors corrected in `AC.2` and `AC.3`** — the mark on the `3b` row, the
   nineteen-word distance, the `17 nodes / 241–531` span and the fifth single-sourced string.
   These are corrections to records this register already holds, and `docs/record-vs-pointer.md`
   makes line pins and counts inside an entry **pointers**, correctable beside the record. They
   are recorded here rather than minted.
3. **The orchestrator's own procedural failure this shift**, recorded because the register is
   where this program keeps things it would rather forget: **the four units were spawned before
   any checkpoint existed**, which `CLAUDE.md` forbids for any job of two or more units. The
   checkpoint (`job26-close-the-register`) was created late so that the accounting was still
   captured and every unit was still reviewed and clocked out; **the brief synthesis is the half
   that stayed missing, and no brief was reconstructed after the fact** — a reconstructed brief
   is a fabricated record. See `.shiftwork/job26-close-the-register/briefs/PROVENANCE.md`.
   No number, because it is a process failure and not a defect in the instrument.

##### AC.7 What stays open

- **`RB-P84`'s attack is half done.** It asks for build identity readable *over the wire* — a
  field carrying `assets_root()` / package `__file__` / the commit, so a *caller* can assert
  which build answered — and for a duplicate `mcpServers` name to be a hard error at startup.
  Neither is built. Both are `mcpserver.py` changes. The detector tells a *person* the builds
  differ; it does not let an *agent mid-call* know which one it is talking to.
- **The scope collision itself is untouched.** `claude mcp list` still prints
  `[Conflicting scopes]`. Removing a registration is the user's call, and per `RB-P84`'s stated
  ordering constraint the refresh comes before the removal.
- **`§V.1` is unfixable in place** — the three figures are still printed without `P-CMP`'s mark.
  That is the pre-registration constraint, not an omission.
- **Prohibition-index completeness is UNMEASURED.** A prohibition written in prose and left out
  of the index is invisible to the checker.
- **Three contract strings remain declared debt** (`evidence_no_observation`,
  `document_manifest_omitted_other`, `document_paste_none`), and two are `UNATTRIBUTABLE` —
  no line carrying twelve literal characters. Declared, not silent.
- **`runtime-ts` is not read by the fan-out gate**, so whether the TypeScript suite states any
  contract sentence is unmeasured.
- **`RB-P95`'s own `29 of 32` and `2 pinned / 26 laundering / 4 pinned by nothing` are still
  unverified.** They need the full sweep, which the unit was told not to run, so they are not
  asserted anywhere in this section.
- **`RB-P96`**, for the reason given.

#### AD (2026-08-21) — the two things that were actually broken get fixed, and a node that had never tested this repository's code is the reason CI is not optional

`RB-P96` and the second half of `RB-P84` are closed by **runtime and configuration
changes**, not by instruments. The shift before this one shipped `2645` insertions and
moved `runtime-py/src` by **zero bytes**; this one moves it.

Both units were **terminated mid-flight by an API session limit**, after committing and
before finishing their own verification. The orchestrator did the load-bearing checks
itself rather than shipping on a hand-back that was never completed, and says so in each
entry below.

##### AD.0 The ceiling

<!-- provenance: value=ceiling RB-P96 over every ref, 96 distinct numbers on main, contiguous 1..96, no gaps; commit=ddd5135; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

`(ceiling RB-P96, 96 distinct, contiguous, `ddd5135`)`. **`RB-P97` is the next free number,
and this section mints exactly one: `RB-P97`.**

##### AD.1 `RB-P96` — FIXED (2026-08-21, PR #58, `927b2a8`)

`.mcp.json` is tracked and carried `".venv/bin/bantamkit-mcp"`, resolved against the
project directory. A worktree has no `.venv`, so the endpoint that wins the name was not
there, and `[Conflicting scopes]` printed in both places without saying which one was
reachable — so the failure looked like the scope warning everyone has learned to ignore.

`.mcp.json` now points at `tools/bantamkit-mcp`, which is **tracked** and therefore present
in every checkout *and* every worktree. **The two halves come from different places on
purpose:** code from the checkout the launcher was spawned out of — in a worktree, THE
WORKTREE — and dependencies from wherever someone ran `pip install`. Getting that backwards
would be worse than the `ENOENT` it replaces, because a worktree served the main checkout's
source fails silently and plausibly. That is `RB-P55`/`RB-P70`.

<!-- provenance: value=from a fresh worktree of merged main and from the canonical checkout, `claude mcp list` reads `bantamkit: tools/bantamkit-mcp - ✔ Connected` in both; --which reports source=<worktree>/runtime-py/src with python=<main>/.venv/bin/python from a worktree, and both resolving to the checkout itself from the canonical checkout; commit=927b2a8; command=cd <worktree> && claude mcp list ; ./tools/bantamkit-mcp --which -->

**The unit refuted the prototype it was handed rather than copying it**, which is what it
was told to do. The prototype fell through to a bare `python3` whenever no `.venv` was
found and died with `ModuleNotFoundError: No module named 'httpx'` — a traceback about a
transitive dependency, which reaches the client as `CONNECTION_CLOSED`. Measured twice: a
fresh clone with no `.venv`, and a worktree with `git` absent from `PATH`. The shipped
launcher therefore **does not shell out to `git` at all**; it reads the worktree's `.git`
file and the `commondir` beside it with shell builtins, and guards the import so the
failure names the cause and the fix instead of the symptom.

**The falsifier was already on `main` and no new one was built.** `tools/mcpdrift/mcpdrift.py`
run from the same worktree reads `VERDICT ERROR` before the fix and `VERDICT AGREE` after.
Red on the broken state, green on the fixed one, watched both ways.

**Not shipped, deliberately:** the unit's half-built `tools/mcpreach/` checker was
uncommitted and had **never been seen to fire**. A check nobody has watched go red is not
a check, so it was set aside rather than merged.

##### AD.2 `RB-P84`'s second half — FIXED (2026-08-21, PR #57, `ddd5135`)

`RB-P84` asked for build identity readable **over the wire**, so that an agent holding a
tool result can ask which build produced it. `mcpdrift` closed the outside half — it tells
a *person* two endpoints differ. `build_identity` closes this one.

**`build_id` is computed from content alone** — server name, declared version, code digest,
asset digest. **`version` is echoed and is deliberately not identity:** it moves on release
bumps and it has already lied in this program. `package_path`, `assets_root` and
`interpreter` are reported as LOCATION and kept out of `build_id`, because two installs of
one build at two paths are one build.

<!-- provenance: value=two builds agreeing on version 0.25.0 and differing by one byte of agent.py, assets pinned identically, give build_id sha256:aa5e98aa... and sha256:2b54c31e...; commit=ddd5135; command=BANTAMKIT_ASSETS=<pin> PYTHONPATH=<copy> python -c "from bantamkit.mcpserver import build_identity; print(build_identity())" -->

Same version string, different build, **told apart over the tool.** That is exactly
`mcpdrift`'s CAL-2 case, which until now only a behavioural probe could catch.

**Refusal is structural, not a gap.** `git_commit` reports *"refused, not missing"* — an
installed wheel carries no repository — and the response carries an explicit
`unavailable: ["git_commit"]` list, so `RB-P51`'s rule holds. **And the refusal composes:**
when an input cannot be derived, `build_id` **declines to compute at all**, on the stated
ground that a `build_id` short of an input would agree with every other build that lost the
same input. A silently-colliding partial fingerprint is closed by construction.

**Stated coverage gap:** the dependency tree is not fingerprinted beyond `mcp_sdk_version`,
so two builds whose `pydantic` differs read identically here.

The unit also caught its own false positive: the asset pack ships **inside** the package
directory in a wheel, so the code walk was fingerprinting it too and calling one build two.

##### AD.3 Minted here — `RB-P97`, and only `RB-P97`

- **`RB-P97` — the stdio node was serving whatever `bantamkit` was installed in the
  interpreter, never the checkout it was reviewing, and only CI could see it.**

  <!-- provenance: value=mcp.client.stdio.get_default_environment() returns exactly ['HOME','LOGNAME','PATH','SHELL','TERM','USER'] — PYTHONPATH is absent; with the default environment the spawned server answered with 6 tools and with env= passed it answered with 7; commit=ddd5135; command=python -c "from mcp.client.stdio import get_default_environment as g; print(sorted(g()))" -->

  `test_stdio_subprocess_initializes` asserted `len(tools.tools) == 6`. The count was the
  symptom. `StdioServerParameters` defaults to `get_default_environment()`, which passes
  exactly `HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM` and `USER` — **`PYTHONPATH` is
  stripped.** So the spawned server imported whatever `bantamkit` the interpreter's
  environment resolved, which on this machine is the editable `.pth` pointing at the
  **canonical checkout**. The node therefore passed in a worktree while asserting a count
  the worktree's own code had already moved past, and **CI, which installs the branch, was
  the only place it could fail.**

  This is `RB-P55`/`RB-P70` reaching **through a subprocess**, where `PYTHONPATH` — the
  documented remedy for the worktree trap, and the one every unit in this program is
  instructed to set — is silently discarded by the SDK. Every earlier statement in this
  register about that node was a statement about a build nobody chose.

  **FIXED in the same PR** (`ddd5135`), in two parts: `env=` is passed explicitly so the
  subprocess is pointed at the checkout, and the assertion becomes an **exact list** rather
  than a count, matching its sibling. Verified by mutation: removing `env=` reddens it with
  `['memory_reca...alidate_json'] == ['build_ident..._status', ...]` — **naming the missing
  tool rather than a number.**

  **What is not closed:** nothing audits the rest of the suite for the same shape. Any
  other test that spawns a server over stdio, now or later, inherits the same silent
  substitution unless it passes `env=`. **Attack:** a check that no `StdioServerParameters`
  construction in the tree omits `env=`.

##### AD.4 What gets no number

1. **The two fixes.** A fix is not a finding.
2. **A live instance of `RB-P45`, recorded as evidence rather than minted.** The repo venv
   today carries **two** installs of `bantamkit`: an editable `.pth` pointing at the
   checkout, and a stale non-editable copy with `bantamkit-0.3.0.dist-info` beside it.

   <!-- provenance: value=in the repo venv, bantamkit.__version__ is 0.25.0 while importlib.metadata.version("bantamkit") is 0.3.0; commit=ddd5135; command=cd /tmp && .venv/bin/python -c "from importlib import metadata; import bantamkit; print(bantamkit.__version__, metadata.version('bantamkit'))" -->

   `__version__` reads `0.25.0` and `metadata.version("bantamkit")` reads **`0.3.0`**. This
   is precisely the divergence `RB-P45` was fixed to survive: had `_version()` still read
   the dist-info, **the MCP server would advertise `0.3.0` on this machine today.** The
   finding is already filed and already fixed; what is new is that the hazard is standing
   in the working environment rather than hypothetical.
3. **The orchestrator's `--force-with-lease` attempt**, refused by the permission layer
   because no live instruction named a force push of that branch. The refusal was correct
   and was not routed around; the rebase was undone and the branch pushed fast-forward.

##### AD.5 What stays open

- **`RB-P97`'s sweep** — no check yet that every `StdioServerParameters` in the tree passes
  `env=`.
- **One node in `test_build_identity.py` has no demonstrated red.** The unit disclosed it
  before dying and the orchestrator does **not** claim its non-vacuity.
- **`bantamkit.mcpserver` has no `__main__` guard**, so `python -m bantamkit.mcpserver`
  exits silently and the client reports `CONNECTION_CLOSED` — the symptom, not the cause.
  The launcher works around it by importing `main` directly. A different layer, unfixed.
- **The scope collision** — `claude mcp list` still prints `[Conflicting scopes]`. Removing
  a registration is the user's call, and per `RB-P84` the refresh comes before the removal.
- **`RB-P95`'s own `29 of 32`** and `2 pinned / 26 laundering / 4 pinned by nothing` remain
  unverified; they need the full sweep nobody has run.
- **The stale `0.3.0` install** is still in the venv. Nothing depends on it and the editable
  `.pth` wins the import, but it is what `importlib.metadata` answers from.

#### AE (2026-08-21) — the module invocation served nothing and only a test that routed around it could stay green; and the node the register would not vouch for turns out to be the only thing guarding its property

<!-- provenance: value=ceiling RB-P97 over 79 refs (refs/heads + refs/remotes), 97 distinct numbers on main, contiguous 1..97, no gaps and nothing above; commit=e5917b3; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/); do git show $r:docs/eval.md | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

```
    ceiling over all 79 refs                     ->  RB-P97
    distinct numbers on main, contiguous 1..97   ->  97
    tags before and after this section           ->  22
```

`(ceiling RB-P97 over 79 refs, e5917b3, the command above)`. **`RB-P98` is the next free number,
and this section mints exactly one: `RB-P98`.**

Two of the six items §AD.5 left open are closed here. **Neither was found by this section — both
were nominated by a prep probe, and the probe was right about one and wrong about the other.**
That ratio is the section's most useful output and it is stated before the findings rather than
after: a nomination is a claim, and this register has now been wrong about its own subjects often
enough that checking one is a unit of work rather than a formality.

##### AE.1 The `__main__` guard — FIXED (`317a363`), and the discriminator is not the one the filing named

§AD.5 filed it as *"`bantamkit.mcpserver` has no `__main__` guard, so `python -m bantamkit.mcpserver`
exits silently and the client reports `CONNECTION_CLOSED` — the symptom, not the cause."* Reproduced
exactly: exit `0`, **stdout 0 bytes, stderr 0 bytes**.

<!-- provenance: value=`python -m bantamkit.mcpserver` pre-fix exits 0 with 0 bytes on both streams, and `-m bantamkit.mcpserver --help` does the same; post-fix --help prints argparse usage for prog bantamkit-mcp; commit=317a363; command=subprocess.run([".venv/bin/python","-m","bantamkit.mcpserver"], capture_output=True, timeout=30, stdin=DEVNULL) -->

**The unit corrected the filing on the point that matters for testing it.** The bare `-m` run is
**not** a discriminator: post-fix, with stdin closed, a stdio server also exits 0 silently, because
that is what a stdio server does at EOF. `-m bantamkit.mcpserver --help` is the discriminator — 0
bytes before, argparse usage for prog `bantamkit-mcp` after. **A test written against the bare run
would have passed in both worlds**, which is one more reason this survived.

The fix is two lines. The deliverable is the node beside it, and the reason is arithmetic:

<!-- provenance: value=under the mutation `delete the __main__ guard` (verified by grep -c '__main__' -> 0), test_module_entrypoint_serves_over_stdio fails at session.initialize() with mcp.shared.exceptions.MCPError: Connection closed, while the rest of the file is 27 passed — including test_stdio_subprocess_initializes; commit=981d73f; command=pytest runtime-py/tests/test_mcpserver.py -q -->

```
    under the exact defect, before this section:
      test_stdio_subprocess_initializes (the -c sibling)  ->  PASSED
      the rest of test_mcpserver.py                       ->  27 passed
      anything red anywhere                               ->  none
```

**All twenty-seven pre-existing nodes stay green through the bug.** `test_stdio_subprocess_initializes`
launches the server with `-c "from bantamkit.mcpserver import main; main()"` — it routes around the
broken path by construction, and that routing is itself inherited from `RB-P97`'s fix, where `env=`
had to be passed explicitly because the SDK strips `PYTHONPATH`. So the suite did not miss this
through carelessness; it missed it because the one node that spawns a server was pointed at the one
invocation that worked. `test_module_entrypoint_serves_over_stdio` (`981d73f`) spawns
`[sys.executable, "-m", "bantamkit.mcpserver"]` with an explicit `env` and asserts the **exact tool
list**, matching its sibling — a count is the symptom, a list names the missing tool.

Suite `1456 passed, 2 xfailed` → `1457 passed, 2 xfailed`. Delta **+1**, exactly the node added.

##### AE.2 The node with no demonstrated red — the filing is WITHDRAWN, and the node is named

§AD.5 said *"One node in `test_build_identity.py` has no demonstrated red. The unit disclosed it
before dying and the orchestrator does not claim its non-vacuity."* **The node is
`test_the_tool_is_listed_and_takes_no_arguments`**, and the hedge is withdrawn: its red is
demonstrated, three times, on the record below.

A prep probe nominated it for **deletion**, reasoning that it never calls `build_identity()` so no
mutation of that function can redden it, that its `in tools` assertion is subsumed by four other
nodes, and that its two negative `.get()` assertions *"pass identically whether the key is absent,
empty, or the schema is `{}`"*. **The first two are right. The third is false at the protocol layer,
and deleting the node was the one move that would have opened a hole silently.**

<!-- provenance: value=parameters={} raises ValidationError `tools.6.inputSchema.type Field required` and parameters={"type":"string"} raises `Input should be 'object'`, both inside pydantic during tools/list; adding one OPTIONAL parameter `def build_identity_tool(refresh: bool = False)` gives full suite 1 failed, 1456 passed, 2 xfailed; commit=62c9c3f; command=pytest runtime-py/tests -q under each named mutation -->

```
    mutation                                          reddens
    ------------------------------------------------  ---------------------------------------
    rename the registration to build_identity_v2      this node AND test_lists_exactly_the_
                                                        seven_tools (strictly stronger) AND
                                                        every stdio node  -> SUBSUMED
    def build_identity_tool(refresh: bool = False)    THIS NODE ALONE, 1 of 1459
    schema declaring required:['refresh'] with an     the third assertion alone
      empty properties map
```

**The degenerate schema the probe reasoned about is unreachable.** The MCP SDK's `ListToolsResult`
requires `inputSchema.type` and pins it to the literal `object`, so `{}` and `{"type":"string"}`
both die in pydantic during `tools/list` and never reach an assertion. `**kwargs` does not produce
an open schema either — it emits a `kwargs` property the current form already catches.

**What the node uniquely guards is that the tool takes no arguments at all.** Adding one *optional*
parameter is an ordinary change; the five stdio arms call with `arguments: {}` and keep passing, so
nothing else in 1,459 nodes notices. The probe called that mutation implausible. It is not, and
"implausible" was doing the load-bearing work in an argument for deletion.

`62c9c3f` changes **no assertion**. It records the three mutations in the node's docstring, in the
file's existing voice, including a warning against the vacuous strengthening
`assert input_schema["type"] == "object"` — which **cannot fail**, because pydantic rejects the
input before any assertion runs. Suite unchanged at `1457 passed, 2 xfailed`; delta zero is correct
for a docstring-only commit.

##### AE.3 Minted here — `RB-P98`, and only `RB-P98`

- **`RB-P98` — a declared entry point is not a tested one, and this repo has exactly one class of
  node that would notice.** `AE.1` fixed one instance and the class is untouched.

  <!-- provenance: value=grep -rn '__main__' runtime-py/src/bantamkit/ finds guards at evalrun.py:1991 and criticreplay.py:3064 and no node spawns `python -m` on either; [project.scripts] bantamkit-mcp is asserted only as a pyproject string by test_packaging_reads_the_same_declaration_the_server_reads and nothing spawns the installed executable; commit=e5917b3; command=grep -rn '__main__' runtime-py/src/bantamkit/ && grep -rn 'project.scripts' -A2 runtime-py/pyproject.toml -->

  Two live instances, both disclosed by the unit that fixed the third rather than found by an
  audit. **`evalrun.py:1991` and `criticreplay.py:3064` carry `__main__` guards that no node
  exercises** — either could be deleted and the suite would stay green, which is precisely the
  state `mcpserver.py` was in before `AE.1`. And **the console script `bantamkit-mcp` is asserted
  only as a string in `pyproject.toml`**; nothing spawns the installed executable, so a regression
  in the entry point is invisible to the suite while being the single path a third-party install
  actually uses.

  It earns a number rather than a footnote for the reason `AE.1` demonstrates: the failure is
  **silent in the direction that matters**. `python -m` on a broken module exits **0**. A missing
  console script fails only on someone else's machine. Both are the shape this register exists for
  — a gate that cannot see its own subject — and the fix is a node per entry point, not a guard per
  module.

  **Attack:** a check that every declared entry point — each `__main__` guard and each
  `[project.scripts]` target — is spawned by at least one node. Note it composes with `RB-P97`:
  any such node must pass `env=` explicitly or it tests a build nobody chose.

##### AE.4 What gets no number

1. **The two fixes.** A fix is not a finding.
2. **The probe's refuted reasoning.** Being wrong about a node is not a defect in the tree, and
   `AE.2` records it as evidence rather than minting it. What it cost was one unit of work, which
   is what a nomination is supposed to cost.
3. **`{"type":"object","properties":{},"additionalProperties":true}`** would pass all three of the
   node's assertions while advertising "send me anything". It is reachable only through the
   `_tool_manager` override, **the mutation was NOT RUN**, and the unit declined to claim a red it
   had not demonstrated. Recorded as a candidate. The register does not mint candidates.

##### AE.5 What stays open

- **`RB-P98`**, for the reason given. `AE.1` closed one of its three known instances.
- **`RB-P97`'s sweep** — still no check that every `StdioServerParameters` passes `env=`. A prep
  probe measured the population at **one construction, already correct**, so a lint here would be
  future-proofing over a population of one and cannot go red today. Recorded so the next reader
  does not re-measure it.
- **The scope collision is HALF CLOSED, and by configuration, not by code.** `claude mcp list` no
  longer prints `[Conflicting scopes]`: the user-scope registration was removed on the user's
  instruction, and `bantamkit` now resolves to the project build alone. The removed endpoint was a
  **six-tool build without `build_identity`** — an older install that would have answered silently
  had the project registration ever been unapproved, which is `RB-P45`'s hazard standing in the
  working environment for the second section running.
- **`RB-P95`'s own `29 of 32`** and `2 pinned / 26 laundering / 4 pinned by nothing` remain
  unverified; they need the full sweep nobody has run.
- **The stale `0.3.0` install** is still in the venv.
#### AF (2026-08-21) — `extract()` refused 99.85% of the corpus it was written for; and a must-be-red node that stayed GREEN under its own mutation turns out to be six nodes, because a fixture with one hardcoded dimension samples a boundary at the one value where broken and correct agree

Two units, four commits, on `fix/docread-sniff-coverage`. Every number below was RE-MEASURED by
this section against the worktree's own source before it was written down, and **seven of the
figures this section was handed do not reproduce, and an eighth claim — that a named node does
not exist — is false.** They are listed in `§AF.6` rather than quietly corrected, and where a
measurement here disagrees with the hand-off, **the measurement is what stands**.

The venv's editable install resolves `bantamkit` to the CANONICAL checkout, so every command in
this section sets `PYTHONPATH` to the worktree's `runtime-py/src` and every run was confirmed by
`bantamkit.docread.__file__` before its output was believed — `RB-P97`, applied rather than
cited.

##### AF.0 The ceiling, read across every ref — and this branch alone would have collided

<!-- provenance: value=ceiling RB-P98 over 80 refs (refs/heads + refs/remotes), 98 distinct numbers on main, contiguous 1..98, no gaps and nothing above; 22 tags; this branch's own eval.md reads RB-P97; commit=23b0463; command=for r in $(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/); do git show "${r}:docs/eval.md" | grep -oE 'RB-P[0-9]+' | sed 's/RB-P//' | sort -n | tail -1; done | sort -rn | head -1 -->

```
    ceiling over all 80 refs                     ->  RB-P98
    distinct numbers on main, contiguous 1..98   ->  98
    tags before and after this section           ->  22
    ceiling read on THIS BRANCH alone            ->  RB-P97
```

`(ceiling RB-P98 over 80 refs, 23b0463, the command above)`. **`RB-P99` is the next free number,
and this section mints exactly one: `RB-P99`.**

The last line of that block is the point. **This branch's `docs/eval.md` ends at `§AD` and its
ceiling reads `RB-P97`**, because `§AE` and `RB-P98` landed on `main` in `7a97a2f` after this
branch was cut. Reading the ceiling here would have minted `RB-P98` — a number `docs/eval.md`
already carries. That is `RB-P74`/`RB-P75` standing live for the third section running, and it
cost nothing only because the rule was followed.

**Disclosed rather than discovered later:** this section is `§AF` and it is appended to a file
whose last section is `§AD`. `§AE` is on `main` and not here; it was read from
`git show main:docs/eval.md` before a word of this was written. The four commits were not
rebased and the section letter is the one the merged file will need, not the one this file
implies.

##### AF.1 Unit I — where the read stopped had a vote, and 233 files changed answer when it lost it

`sniff` read a 4,096-byte head and decoded it with a single `head.decode("utf-8")`. A character
straddling that boundary raised, and the file fell through to `unknown` — so **where this
reader happened to stop decided what the file WAS**. `4bd1924` replaces the decode with an
incremental decoder that lowers `final` exactly where a boundary exists:

```python
return decoder.decode(head, final=len(head) < _HEAD_BYTES)
```

A file shorter than the cap was read whole, so a dangling half-character in it is real damage
rather than an artefact of sampling, and still refuses. The head size is named `_HEAD_BYTES` so
a bar can vary it.

Second, `_TEXT_CONTROLS = {0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1B}` — tab, the newline family, and
ESC as the ECMA-48 introducer for ANSI colour. Every other C0 code stays binary evidence. This
widens the classifier by a stated rule about which codes mean what, not by a tolerance.

<!-- provenance: value=sniffing ~/Documents/Claude/Projects twice in one pass, once against e5917b3's docread.py and once against the worktree's, over 49,556 files: 233 move unknown->text and NOTHING moves in any other direction; of the 211 files whose decodable head carries a C0 code beyond tab and the newline family, 24 carry ESC and no other (ANSI logs, -> text) and 187 carry NUL (-> unknown); commit=23b0463; command=scratch/final.py, one os.walk pruned at node_modules .venv venv .git __pycache__ dist build .next target site-packages .cache, symlinks not followed, both trees imported in one process -->

```
    unknown -> text                    233
    anything -> anything else            0
    heads carrying a C0 beyond \t\n\v\f\r     211
      of which ESC-only (ANSI logs)            24   -> text
      of which NUL-bearing                    187   -> unknown
```

**Nothing became less readable.** The 187 NUL-bearing files are PostgreSQL heap/FSM/VM/WAL under
`.docker-data`; a NUL at offset 0 is binary framing under the old rule and under the new one
alike, and they stay `unknown` by the rule rather than by luck.

**The bar is the property, not the constant.**
`test_the_verdict_does_not_move_when_the_head_size_does` builds a file carrying a 3-byte
character every 4 characters and sniffs it once for every head size from 1 byte to past EOF,
with `_HEAD_BYTES` monkeypatched:

<!-- provenance: value=the sweep fixture is 1200 bytes and range(1, size+32) sweeps 1,231 head sizes; against the shipped decoder all 1,231 read `text`; against head.decode("utf-8") 400 of the 1,231 read `unknown` and 831 read `text`; commit=23b0463; command=for hb in range(1, size+32): docread._HEAD_BYTES = hb; sniff(path).kind, run once per tree -->

```
    boundaries swept                      1,231
    shipped decoder                       1,231 text        0 unknown
    head.decode("utf-8")                    831 text      400 unknown
```

400 of 1,231 is one third, which is what a 3-byte character every 4 characters is arithmetically
required to produce. The fixture's dimension and the property's period were chosen to agree —
which, as `§AF.4` shows, is the same lever that goes the other way when nobody checks it.

Node count `77 -> 88`, collected, not counted by hand.

##### AF.2 Unit J — `extract()` could hand back 76 files out of 49,556, and the brief's own refusal rate was wrong in the direction that flattered it

`kind == "text"` was not a key in `_EXTRACTORS`, so `extract()` **raised** on every plain UTF-8
text file. `de4a11c` adds `extract_text`, whose one part `document` has the file's lines as rows.

<!-- provenance: value=over ~/Documents/Claude/Projects, 49,556 files under the exclusion list: text 43,629 / unknown 3,924 / empty 964 / png 848 / html 76 / gzip 61 / gif 48 / zip 6, summing to 49,556 with zero xlsx, docx, pdf, mhtml, doc or rtf anywhere in the corpus; extract() could answer 76 before (all html) and 43,705 after; commit=23b0463; command=scratch/final.py, the single pass of §AF.1 -->

```
    kind census                     extract() could answer
    text      43,629                  before      76   (all html)   refusal  99.85%
    unknown    3,924                  after   43,705                refusal  11.81%
    empty        964
    png          848                xlsx docx pdf mhtml doc rtf   ->  0, none exist
    html          76
    gzip          61                text share                    ->  88.04%
    gif           48
    zip            6
    ------------  -----
    total     49,556
```

**The brief this section was handed framed `89.30%` as the refusal rate.** The refusal rate was
`99.85%` — `49,480` of `49,556` files. `89.30%` is not the refusal rate and is not the text
share either; the text share is **`88.04%`**. A figure that understates a defect by ten points,
carried into a register, is worse than no figure, and this one arrived pre-labelled as the
headline.

<!-- provenance: value=extract_text over all 43,629 text files under Projects returns 5,577,850 rows with ZERO omissions raised and zero refusals; re-run twice, identical both times; commit=23b0463; command=scratch/rows.py over the text-path list from the census pass -->

**43,629 text files, 5,577,850 rows, zero omissions raised.** Not `5,577,842`; the run was
repeated and returned `5,577,850` both times.

##### AF.3 The three decisions, each re-derived — and one figure that is a property of the fixture and not of the cap

**`_text_rows`, not `_plain_rows`.** `_plain_rows` strips each line, flattens tabs and drops the
empty ones. Measured over the same 43,629 files, decoding each and rendering it both ways:

<!-- provenance: value=over the 43,629 Projects text files, _plain_rows returns 4,708,577 rows against _text_rows' 5,577,850 -- 869,273 lines dropped, 15.58%; 33,990 files carry at least one line beginning with a space or a tab; 86 files contain a tab anywhere; _plain_rows differs from _text_rows on 37,278 of the 43,629; commit=23b0463; command=scratch/plain2.py, len(D._plain_rows(text)) vs len(D._text_rows(text)) on each file's strict decode -->

```
    files de-indented by .strip()        33,990 of 43,629    77.9%
    files whose tabs would flatten           86
    lines dropped as blank              869,273 of 5,577,850   15.58%
    files rendered differently at all    37,278 of 43,629
```

**`77.9%` and `86` reproduce exactly.** The blank-line figure does not: it is `869,273 of
5,577,850` (`15.58%`), not `909,880 of 5,618,108` (`16.2%`). Both halves of the handed ratio are
about 40,000 high and this section could not reproduce either.

One measurement fell out of that pass and is worth its own line: **`text.splitlines()` over the
corpus returns exactly `5,577,850` — the same number `_text_rows` returns.** `_text_rows` splits
on `\n` alone; `splitlines()` also breaks on `\r`, `\v`, `\f`, `\x85`, `\u2028` and `\u2029`.
The two agreeing to the row means **no file in this corpus uses any of them as a line break**,
which prices the `\r`-only hazard in `§AF.9` at zero files today.

**`TEXT_MAX_BYTES = 16 MiB`, with `OMIT_SIZE_CAP` on the shortfall.** The largest text file on
this host is a **764,017,864-byte `.sql` dump**, with a `134,000,722`-byte one behind it — both
reproduce to the byte.

<!-- provenance: value=walking ~/Documents/Claude/Projects, ~/Documents and ~/Downloads and DEDUPLICATING by realpath gives 72,902 text files, of which exactly 2 exceed 16 MiB and the same 2 exceed 64 MiB; the per-root counts are 43,629 / 72,893 / 9 and Projects is a SUBTREE of Documents, so the naive sum is 116,531; commit=23b0463; command=scratch/threeroots.py and scratch/perroot.py -->

```
    ~/Documents/Claude/Projects   text  43,629     <- a SUBTREE of the next line
    ~/Documents                   text  72,893
    ~/Downloads                   text       9
    naive sum                          116,531
    deduplicated union                  72,902     <- what "across three roots" is worth
    covered by a 16 MiB cap             72,900
```

**The `116,529` this section was handed double-counts.** `~/Documents/Claude/Projects` is inside
`~/Documents`, so every Projects text file is counted twice; the naive sum is `116,531`, within
two of the figure carried, which is how the double-count is identified rather than guessed at.
The **`2 over the cap`** is right in both readings — it is the denominator that was never a
population.

The cost figure needs a sharper qualification, and it is the same disease `§AF.4` is about.
Measured at three fixture line widths against the same two caps:

<!-- provenance: value=tracemalloc peak and wall time for extract_text over a 64 MiB log, at TEXT_MAX_BYTES 16 MiB and 64 MiB, for line widths 20 / 68 / 200 bytes: peaks 109.8/441.7, 77.5/310.0, 68.6/274.3 MiB and the 64:16 ratio is 4.02 / 4.00 / 4.00; commit=23b0463; command=tracemalloc.start(); extract_text(path); tracemalloc.get_traced_memory() per (width, cap) -->

```
    line width    16 MiB cap        64 MiB cap       ratio
       20 B       109.8 MiB 0.20s   441.7 MiB 0.83s  4.02x
       68 B        77.5 MiB 0.15s   310.0 MiB 0.37s  4.00x
      200 B        68.6 MiB 0.08s   274.3 MiB 0.25s  4.00x
```

**The peak at one cap moves by 1.6x with nothing but the fixture's line width.** So `58.2 MiB`
is a statement about a fixture nobody wrote down, and this section measures `77.5 MiB` for its
own. **The only figure here that is a property of the cap is the ratio, and it is `4.00x` at
every width.** A constant chosen against the absolute number would be chosen against a
fixture; a constant chosen against the ratio would not.

**Strict decode with `OMIT_UNREAD_TAIL`, never `errors="replace"`.** A character the file does
not state is never emitted. Extracting every text file in the deduplicated union:

<!-- provenance: value=extract_text over all 72,902 text files of the deduplicated union returns 10,291,819 rows, 0 OMIT_UNREAD_TAIL, 2 OMIT_SIZE_CAP and 1 DocumentReadError; the refusing file is a 1-byte .md whose only byte is 0x0A; commit=23b0463; command=scratch/tail.py, then scratch/find_refusal.py to identify the single refusal by size and byte values, never by content -->

```
    text files extracted        72,902
    rows                    10,291,819
    OMIT_UNREAD_TAIL                 0   <- the claim holds; the denominator was 116,529
    OMIT_SIZE_CAP                    2   <- the two files over the cap
    DocumentReadError                1
```

**`0` reproduces. `116,529` does not.** The tail path is unexercised by any real file across
`72,902`, and it is handled because it is constructible and unbounded, not because it is common.

The `1` is new and was in no hand-off. **One file in the union sniffs `text` and then
`extract()` refuses it**: a 1-byte `.md` whose only byte is `0x0A`. It is not a defect — the
module's stated rule is that an empty extraction from a text container is a refusal — but it
means **`sniff().kind in SUPPORTED` is not a guarantee that `extract()` answers**, which is a
weaker contract than the one the fix was written to restore. Recorded in `§AF.9`.

##### AF.4 The node that was GREEN under the very mutation it existed to catch

`test_the_cap_cuts_at_a_line_break_so_no_half_row_is_handed_back`
(`runtime-py/tests/test_docread.py:1356`) exists to hold one property: where the cap stops the
read, the rows are cut back to the last line break, so no row this reader never saw the end of
is handed back. Its first version pinned `TEXT_MAX_BYTES` to the single value `5001` over a
fixture of 41-byte lines.

```
    line = b"line %04d " + b"-"*30 + b"\n"      41 bytes, 40 of them characters
    5001 // 41 == 121   5001 % 41 == 40
```

**The remainder is exactly one whole line missing only its terminator.** Under the mutation the
node was written to catch — the cut-back removed from the cap path — the 122nd row comes back at
40 characters, indistinguishable from a clean cut. The node passed.

<!-- provenance: value=a faithful reconstruction of the single-cap node and the shipped sweep, both run against the shipped tree and against the mutant `if why or capped:` -> `if why:`; control 45 passed; under the mutant the single-cap node PASSES, the sweep FAILS, and of the 42 caps 5000..5041 parametrised individually exactly 2 pass -- 5001 and 5002; commit=23b0463; command=scratch/vacuity_test.py under PYTHONPATH=<shipped> and PYTHONPATH=<mutant> -->

```
    under the mutation it exists to catch
      the BEFORE shape, one cap of 5001                    PASSED   <- false green
      the AFTER shape, every cap across a full line        FAILED
      the 42 caps 5000..5041, one node each          2 passed, 40 failed
                                                       the 2 are 5001 and 5002
```

**Two of 42 consecutive caps hide the defect and the node picked one of them.** `5002` is a
genuinely clean cut (`5002 % 41 == 0`); `5001` is the coincidence. The rewritten node sweeps
every cap across a full line and reddens **3 of 106** under the same mutation, which reproduces
exactly.

This is the strongest possible false signal. A red says "look here". A green says nothing at
all, and a green from a must-be-red node says "this property is guarded" while guarding
nothing. **The fixture's dimensions and the mutation's boundary coincided, and no amount of
care in writing the mutation would have caught it, because the mutation was correct.**

##### AF.5 The class, hunted — six live instances, every one confirmed by a RUN and not by reading

A number with one instance is an anecdote. The suite was searched for the same shape: a node
whose fixture carries a **single hardcoded size, width, offset or count** checked against a
**boundary**, where one coincident value hides the defect. **Every candidate below was
confirmed by applying the named mutation and running the full suite against a control** —
`RB-P51`'s rule, and `feedback-verify-against-the-run-not-the-source` applied to a hunt whose
whole subject is reasoning that looked sound.

<!-- provenance: value=control = the worktree's src copied to scratch and run unmutated: 2 failed, 1483 passed, 2 xfailed, the two reds being test_packaging_reads_the_same_declaration_the_server_reads and test_assets_root_finds_repo_assets, both of which assert on package LOCATION and are red only because the harness imports from a copy; each mutation below then run identically; commit=23b0463; command=BANTAMKIT_ASSETS=$PWD/assets PYTHONPATH=<mutant copy> pytest runtime-py/tests -q -->

```
    control (unmutated copy)                                   2 failed, 1483 passed, 2 xfailed
    ------------------------------------------------------------------------------------------
    docread.py:1395  size = len(...) + (1 if rows else 0)
                       -> size = len(...)        [ceiling overrun]  2 failed, 1483 passed  0 RED
    docread.py:1395  used + size > max_bytes -> >=  [off-by-one]    2 failed, 1483 passed  0 RED
    docread.py:1399  decode(errors="ignore") -> errors="replace"    2 failed, 1483 passed  0 RED
    evalrun.py:1328  rows = min(rows, DOCUMENT_PAGE_MAX_ROWS)
                       -> the clamp DELETED                         2 failed, 1483 passed  0 RED
    shiftwork.py:159 [-HISTORY_RING_SIZE:] -> [1:]                  2 failed, 1483 passed  0 RED
    contract.py:167  truncate(text, budget) -> budget * 4           2 failed, 1483 passed  0 RED
```

**Six mutations, six live defects, and not one node in 1,485 goes red for any of them.** Each
is named with the coincidence that hides it.

**1. `test_docread.py:861` `test_max_bytes_bounds_the_slice_below_the_row_limit`.** The fixture
renders 120 rows of exactly 7 bytes and the boundary is the single hardcoded `max_bytes=40`.
`page()` books the joining newline (`+ (1 if rows else 0)`), which is the entire reason
`len(text.encode()) <= max_bytes` holds. Delete that term and the accounting becomes `7N <= 40`
instead of `8N - 1 <= 40`; both stop at **5 rows / 39 bytes**.

<!-- provenance: value=for max_bytes 7..59, shipped and the newline-term mutant return identical (rows, bytes) at 28 of the 53 values, and the mutant RETURNS MORE BYTES THAN ITS OWN CEILING at 25 of the 53; at 40 both give (5, 39); at 42 shipped gives (5, 39) and the mutant gives (6, 47) against a 42-byte ceiling; commit=23b0463; command=page(doc,"data",limit=50,max_bytes=mb) for mb in range(7,60), run once per tree -->

```
    caps 7..59 where the two accountings AGREE                28 of 53
    caps where the mutant overruns its own declared ceiling   25 of 53
    max_bytes = 40  sits inside the agreement window {39, 40, 41}
    max_bytes = 42  shipped (5 rows, 39 B)   mutant (6 rows, 47 B vs a 42 B ceiling)
```

**This is not even a rare coincidence — a cap picked at random has a better-than-even chance of
hiding it.** Two independent mutations of this node's subject (the newline term, and `>` to
`>=`) both come back green.

**2. `test_docread.py:869` `test_a_single_row_over_the_ceiling_is_cut_and_the_loss_reported`.**
The fixture is `"x" * 500` — pure ASCII — against `max_bytes=100`. `page()` cuts at a BYTE
offset (`row.encode()[:max_bytes].decode(errors="ignore")`), and **on an all-ASCII row a byte
cut and a character cut are the same operation**, so the multibyte hazard is invisible.
Measured: with a 200-character Thai row the shipped code returns 99 bytes and no `U+FFFD`,
while `errors="replace"` returns 102 bytes **containing `U+FFFD`** — a character the file never
stated, emitted by the one module whose stated rule forbids exactly that. Zero nodes notice.
`extract_text` has a dedicated sweep for this (`test_the_cap_never_cuts_a_character_in_half`,
`test_docread.py:1374`, Thai, `range(90, 130)`); **`page()`, the other place in the same module
that cuts at a byte offset, has none.**

**3. `test_document_tools.py:388` `test_limit_is_capped_rather_than_honoured`.** It exists to
pin `evalrun.py:1328`, the 200-row clamp. Its corpus renders ~21-byte rows, and `page()` is
called with `DOCUMENT_PAGE_MAX_BYTES = 3072` — so the **byte** ceiling binds at roughly 140
rows, **below the 200-row clamp, which is therefore never reached**. Delete the clamp outright
and the observation is unchanged. The node asserts `<= 200` and 140 satisfies it. The coincidence
here is between two boundaries rather than a fixture and one: the wrong ceiling binds first, so
the node measures the one it was not written for.

**4. `test_shiftwork.py:275`
`test_clock_out_pushes_the_history_ring_with_driver_identical_truncation`.** The fixture's
history is **exactly `HISTORY_RING_SIZE` long**, so `[-5:]` of the 6-entry result and `[1:]` of
it are the same slice. Replace the ring with an unconditional "drop the oldest" and the node is
byte-identical.

<!-- provenance: value=the shipped ring and the [1:] mutant, over histories of length 0/1/2/5: shipped -> [NEW] / [H0,NEW] / [H0,H1,NEW] / [H1..H4,NEW]; mutant -> [] / [NEW] / [H1,NEW] / [H1..H4,NEW]; identical ONLY at length 5, which is the only length any node uses; commit=23b0463; command=(history + [entry])[-HISTORY_RING_SIZE:] vs (history + [entry])[1:] at each length -->

```
    history length     shipped                 mutant
        0              ['NEW']                 []          <- THE NEW ENTRY IS LOST
        1              ['H0','NEW']            ['NEW']
        2              ['H0','H1','NEW']       ['H1','NEW']
        5              ['H1'..'H4','NEW']      ['H1'..'H4','NEW']   <- the only length tested
```

**On an empty history the mutant loses the entry it was called to write, and the suite is
green.** The other push node in the file uses a 1-entry history and asserts only that the last
element is `U3`, which the mutant also satisfies. **No node anywhere asserts `len(history)`
after a push.**

**5. `test_critique.py:254` `test_render_evidence_truncates_at_budget`.** 100 bytes of content,
`budget=20`, and the assertion is `len(evidence.encode()) < 120` — an upper bound equal to the
fixture size plus the budget. Any effective budget from about 21 to 98 satisfies it. Quadruple
the budget in `contract.py:167` and the output is ~102 bytes, still marked `[truncated`, still
under 120. **The assertion is six times looser than the boundary it names.**

**Two candidates were checked and CLEARED, and they are the reason this is a class and not a
verdict on the suite.** `test_document_tools.py:713`'s paste fixture weighs exactly
`PASTE_MAX_BYTES` — 401 rows, 8,621 bytes — so `remaining` lands on 0 and a `>` / `>=`
mutation flips 401 to 400 and reddens. `test_memory.py:52` pins `index_budget=119` against a
120-byte index, one byte over. **Both are single hardcoded values and both are sound, because
the value was chosen AT the boundary rather than near it.** The defect is not "a hardcoded
number"; it is a hardcoded number chosen without asking what else would satisfy it.

##### AF.6 Handoff corrections — seven figures that do not reproduce, and the brief was wrong about its own correction

This document records these as a subsection of the section that caught them (`§Q`, `§T`,
`§W.5`, `§X.1`, `§Z.6`, `§AA.6`, `§AB.6`), never as a register entry. `§AF.6` is that
subsection.

1. **`234 files moved unknown -> text` is `233`.** One file appeared in the corpus between two
   commands minutes apart, which is also why the census reads `49,556` here and `49,555`
   in `de4a11c`'s message. `feedback-gate-counts-are-co-moving`: a corpus count is a function of
   the corpus at the instant of the command, and both readings are true of their own moment.
2. **`5,577,842` rows is `5,577,850`.** Run twice, identical.
3. **`909,880 of 5,618,108 lines (16.2%)` is `869,273 of 5,577,850 (15.58%)`.** Neither half
   reproduces.
4. **`116,529 text files across three roots` is `72,902`.** The three roots overlap; see
   `§AF.3`. `116,527 of 116,529` and `0 of 116,529` become `72,900 of 72,902` and `0 of 72,902`
   — both CLAIMS survive, both DENOMINATORS do not.
5. **`58.2 MiB / 0.04 s` against `232.1 MiB` is `77.5 MiB / 0.15 s` against `310.0 MiB /
   0.37 s`**, and the absolute number is a property of the fixture, not of the cap. See
   `§AF.3`.
6. **`89.30%` was handed to this section as the refusal rate. It is neither the refusal rate
   (`99.85%`) nor the text share (`88.04%`).**
7. **`a mutation expanding the head to 1 MiB left 3 nodes red` does not reproduce, and the
   error is a dropped conjunct.** Expanding `_HEAD_BYTES` to 1 MiB and changing nothing else
   reddens **0 of 88** — which is CORRECT, and is the whole point: a suite that pins invariance
   to head size must stay green when the head size moves. The mutation `c39ec48`'s own message
   names is compound: **the old `head.decode("utf-8")` AND the head raised to 1 MiB**, "the
   non-fix of moving the boundary". That one reddens **3 of 88**, the same three the old decode
   alone reddens.

<!-- provenance: value=at unit I's own state (4bd1924 runtime, c39ec48 tests) the control is 88 passed; _HEAD_BYTES = 1 MiB alone -> 88 passed, 0 red; whole source reverted to e5917b3 -> 5 failed, 83 passed; _decode_head -> head.decode("utf-8") -> 3 failed, 85 passed; 0x1B dropped from _TEXT_CONTROLS -> 1 failed, 87 passed; final=False -> 1 failed, 87 passed; old decode AND 1 MiB -> 3 failed, 85 passed; commit=c39ec48; command=PYTHONPATH=<mutant copy> pytest <c39ec48's test_docread.py> -q, once per mutation -->

```
    unit I, five mutations RUN at its own state (control 88 passed)
      whole source -> e5917b3                            5 failed, 83 passed
      _decode_head -> head.decode("utf-8")               3 failed, 85 passed
      0x1B dropped from _TEXT_CONTROLS                   1 failed, 87 passed
      final=len(head) < _HEAD_BYTES -> final=False       1 failed, 87 passed
      old decode AND _HEAD_BYTES = 1 MiB                 3 failed, 85 passed
      _HEAD_BYTES = 1 MiB ALONE  (as handed)             0 failed, 88 passed
```

**And the correction the brief carried about itself was also wrong.** It stated that a node
named `test_packaging_reads_the_same_declaration_the_server_reads` **does not exist in this
worktree**, offered as evidence that the orchestrator is unreliable. **It exists**, at
`runtime-py/tests/test_mcpserver.py:433`; it passes; and it has been on this branch since
`bc8c553` (PR #41), which is twenty commits before this job began.

<!-- provenance: value=grep -n finds `def test_packaging_reads_the_same_declaration_the_server_reads` at runtime-py/tests/test_mcpserver.py:433 in the worktree, the node runs 1 passed, and git log -S dates it to bc8c553; commit=23b0463; command=grep -n 'def test_packaging_reads' runtime-py/tests/test_mcpserver.py && pytest 'runtime-py/tests/test_mcpserver.py::test_packaging_reads_the_same_declaration_the_server_reads' -q -->

That is the most useful thing in this subsection. **A brief written to warn that its own figures
were unreliable was itself unreliable about which of its figures were unreliable**, and the only
reason it is recorded as a fact rather than as a doubt is that a `grep` and a one-node run
settle it in four seconds. `feedback-real-probe-only`: the cost of checking is the argument for
checking.

**One pointer error, recorded and NOT corrected here.** `§AC.0` (`docs/eval.md:10652`) cites
**`RB-P73`** for *"the orchestrator is the least-checked source in this program"*. `RB-P73`
(`docs/eval.md:6477`) is *"a guard built on `git diff` over tracked paths is blind in three
separately measured ways"* — a different subject entirely. The claim `§AC.0` makes is real and
this document has ruled on it repeatedly (`§W.6.2`, `§X.8.4`, `§Y.8.4`), but it is ruled as
**unnumbered**, so there is no number to cite. Pointers are correctable in place in their own
commit; this section is a record and does not carry one.

##### AF.7 Minted here — `RB-P99`, and the seven things that get no number

- **`RB-P99` — a must-be-red mutation can be defeated by an arithmetic coincidence between a
  fixture's single hardcoded dimension and the boundary's position, and it fails GREEN, which is
  the strongest possible false signal.** The mutation is correct, it is applied to the right
  line, and the node still passes, because the fixture samples the boundary at one of the values
  where broken and correct agree.

  <!-- provenance: value=six mutations, each applied to the named source line and each run against a 2 failed / 1483 passed / 2 xfailed control, all six leaving the suite at exactly the control: docread.py:1395 (two independent mutations), docread.py:1399, evalrun.py:1328, shiftwork.py:159, contract.py:167; and the prototype at test_docread.py:1356 reconstructed and shown green under the mutation the shipped sweep reddens on; commit=23b0463; command=BANTAMKIT_ASSETS=$PWD/assets PYTHONPATH=<mutant copy> pytest runtime-py/tests -q, once per mutation, plus scratch/vacuity_test.py -->

  **Six live instances, named, each confirmed by a RUN** — `test_docread.py:861` (two ways),
  `test_docread.py:869`, `test_document_tools.py:388`, `test_shiftwork.py:275`,
  `test_critique.py:254` — plus the prototype at `test_docread.py:1356`, which is the only one
  already fixed. Full arithmetic in `§AF.5`.

  **It is NOT `RB-P89` and it is NOT `RB-P67`, and the difference is where the failure lives.**
  `RB-P89` is a mutation that was **too narrow** — a string of the surface that nobody mutated,
  fixed by widening the catalogue. `RB-P67` is a branch that **can never redden at all**, fixed
  by making it reachable. `RB-P99` is a mutation that is **wide enough, applied, and still
  green**, because the FIXTURE is degenerate at one point. Widening the catalogue does not
  touch it and reachability analysis does not see it: the arm IS reached, the assertion IS
  evaluated, and it is true.

  **Why it earns a number rather than a footnote.** `§AF.5`'s first instance has a
  better-than-even hit rate: over `max_bytes` 7..59, `28 of 53` values hide the ceiling-overrun
  defect. This is not a rare alignment that a careful author avoids; it is the **default
  outcome** of picking a round number for a fixture and a round number for a boundary, and the
  two cleared candidates show that avoiding it takes a deliberate act — choosing the value AT
  the boundary, not near it.

  **Attack, and it is cheap:** a node that pins a boundary must sweep its fixture's dimension
  across one full period of that boundary — every cap across a line, every offset across a
  character, every history length across the ring — or pin the value exactly AT the boundary so
  that any movement shows. **A single sample is admissible only where the sample IS the
  boundary.** The register's existing discipline covers what a check reddens for (`§S`/`§T`'s
  laundering) and whether it can redden at all (`RB-P67`); this covers **whether the one input
  it was given can tell the difference**, and none of the three subsumes another. **Filed, five
  of six instances NOT fixed** — they live in four test files this section does not own, and
  `§AF.4`'s prototype is the worked example of what each fix costs: one `for` loop.

What gets no number:

1. **The two fixes.** A fix is not a finding — `§Z.5`'s rule, unchanged.
2. **The seven handoff corrections of `§AF.6`.** A figure a brief asserted and a measurement
   declined is a handoff correction, recorded in the section that caught it and never as a
   register entry. This is `§W.6.2`, applied for the seventh section running.
3. **The orchestrator being the least-checked source is ALREADY-RULED territory, and it is
   ruled UNNUMBERED.** `§W.6.2` settled it — *"that is a fact about this shift's handoffs, and
   the register is for defects in the instrument and the bar"* — and `§X.8.4`, `§Y.8.4`, `§Z.6`,
   `§AA.6` and `§AB.6` each re-applied it. Eight wrong claims in one brief is the same rule at a
   higher count, not a new class. **What is new is only that the brief was wrong about its own
   unreliability** (`§AF.6`), and that is a sharper anecdote, not a defect in the instrument.
4. **`§AC.0`'s mis-citation of `RB-P73`.** A pointer, correctable in place in its own commit.
5. **The `1` file that sniffs `text` and then refuses.** Correct behaviour under a stated rule.
   It narrows what `sniff` promises and is recorded in `§AF.9` rather than minted.
6. **The two cleared candidates** (`test_document_tools.py:713`, `test_memory.py:52`). A node
   that is sound is not a finding, and they are recorded because the contrast is what makes
   `RB-P99` a class rather than a complaint about hardcoded numbers.
7. **Two of unit J's own seven mutation figures do not reproduce as this section ran them, and
   the disagreement makes the suite look STRONGER, not weaker.** *"cap applied, shortfall not
   reported"* is recorded as `1 failed, 105 passed`; the faithful mutation reddens **2 of 106**,
   the second being the line-break node, which cannot survive an `OMIT_SIZE_CAP` that is never
   emitted. *"`_BINARY_CONTROL` re-listed by hand"* is recorded as `2 failed, 104 passed`; the
   natural drift — a hand-written list that forgets the newest member, ESC — reddens **1 of
   106**. A mutation named in prose is not a mutation specified, and neither figure is
   reproducible from the words that describe it. **That is a lesson about how to write down a
   mutation, and this section writes its own out as source lines rather than as descriptions.**

<!-- provenance: value=the five reproducing unit J mutations at 23b0463 against a 106-passed control: whole source -> c39ec48 19 failed / 87 passed; "text" dropped from _EXTRACTORS 17/89; _text_rows -> _plain_rows 3/103; errors="replace" with the control-code stop removed 4/102; cut-back removed on the CAP path only 3/103; and the two that do not: shortfall suppressed 2/104 (recorded 1/105), _BINARY_CONTROL hand-relisted without 0x1B 1/105 (recorded 2/104); commit=23b0463; command=PYTHONPATH=<mutant copy> pytest runtime-py/tests/test_docread.py -q, once per mutation -->

```
    unit J, seven mutations RUN here (control 106 passed)      as recorded   as measured
      whole source -> c39ec48                                  19 / 87       19 / 87
      "text": extract_text dropped from _EXTRACTORS             17 / 89       17 / 89
      _text_rows -> _plain_rows                                  3 / 103       3 / 103
      strict stop -> errors="replace"                            4 / 102       4 / 102
      cap cuts mid-line (cut-back removed on the cap path)       3 / 103       3 / 103
      cap applied, shortfall not reported                        1 / 105       2 / 104
      _BINARY_CONTROL re-listed by hand                          2 / 104       1 / 105
```

##### AF.8 What is NOT claimed

1. **`RB-P99` is filed and five of its six instances are NOT fixed.** No test file outside
   `docs/eval.md` is touched by this section.
2. **The six mutations are evidence of six BLIND SPOTS, not of six live bugs.** Each names a
   defect the suite cannot see; none of them is present in the shipped code. What is measured is
   the suite's sensitivity, not the runtime's correctness.
3. **The hunt is not exhaustive.** It covered the truncation, window, ring and budget sites
   reachable from the boundary constants in `runtime-py/src/bantamkit/`. `pdfread.py:1087`'s
   sliding window (`del operands[:-32]`) has **no test node at all**, which is a different
   defect class and is not counted here. A node that pins a boundary this hunt did not reach is
   unmeasured, and `RB-P51`'s rule says an unmeasured check is not a passed one.
4. **`AF.5`'s control carries two reds that are artefacts of the harness**, not of the tree:
   `test_packaging_reads_the_same_declaration_the_server_reads` and
   `test_assets_root_finds_repo_assets` both assert on package LOCATION and go red because the
   mutation harness imports from a copied tree. The worktree's own suite is `1485 passed, 2
   xfailed`, and `1483 + 2 == 1485`. Every mutation was compared against that control and not
   against zero.

##### AF.9 What stays open

- **Non-UTF-8 encodings are NOT the largest remaining lever, and this section refutes the claim
  it was handed.** The brief named the `3,923` `unknown` files under Projects as latin-1 /
  cp1252 / UTF-16 waiting to be recovered. Measured over the deduplicated union of all three
  roots — `4,809` `unknown` files — the lever is worth **two files**.

  <!-- provenance: value=of the 4,809 unknown files across the deduplicated union, 4,799 carry a NUL inside the first 4,096 bytes, 8 are binary under utf-8, cp1252 and latin-1 alike, ZERO carry a UTF-16 BOM, and 2 decode whole and clean under cp1252 -- one .csv and one .txt; under Projects alone all 3,923 carry a NUL in the head; commit=23b0463; command=scratch/unk_union.py and scratch/unknowns.py, classifying by BOM, by NUL-in-head, then by whole-file decode under each codec with _BINARY_CONTROL as the text test -->

  ```
      NUL inside the first 4,096 bytes      4,799 of 4,809
      binary under every codec tried            8
      UTF-16 BOM                                0
      recoverable (clean under cp1252)          2      <- one .csv, one .txt
  ```

  Under Projects alone, **all 3,923 carry a NUL in the head** — they are PostgreSQL heap/WAL
  and `.zst` / `.db` payloads, not documents in another encoding. **An encoding lever is still
  worth building for correctness; it is not worth building for volume on this host**, and the
  figure that justified it was off by three orders of magnitude. Whether it is worth it on a
  corpus that is not this one is unmeasured.
- **The tail path is unexercised by any real file.** `OMIT_UNREAD_TAIL` fires `0` times across
  `72,902`. It is guarded by constructed fixtures alone, which is the correct decision and also
  means the corpus cannot confirm it.
- **`sniff().kind in SUPPORTED` does not guarantee `extract()` answers.** One file in the union
  proves it (`§AF.3`). The rule is stated and deliberate; the contract is nonetheless weaker
  than "hand it any file and get content or a stated refusal", because a refusal here is a
  `DocumentReadError` and not an `Omission`.
- **Two renderers in one module now disagree about what a plain-text line is.** `_plain_rows` is
  still what `extract_mhtml` uses for a `text/plain` part (`docread.py:985`), and it strips,
  flattens and drops.

  <!-- provenance: value=the identical 4-line body "def f():\n\tif x:\n\n\t\treturn 1\n" written once as a .txt and once as the single text/plain part of an .mhtml gives ('def f():', '\tif x:', '', '\t\treturn 1') from extract_text and ('def f():', 'if x:', 'return 1') from extract_mhtml; commit=23b0463; command=extract(txt).parts[0].rows vs extract(mhtml).parts[0].rows on the same bytes -->

  ```
      same bytes, same module
        extract_text    4 rows   indentation kept, blank line kept
        extract_mhtml   3 rows   indentation stripped, blank line dropped
  ```

  The `77.9%` / `86` / `15.58%` argument in `§AF.3` is an argument about text, and it applies
  verbatim to a `text/plain` MIME part. Whether the mail-body provenance justifies the
  difference is a decision nobody has made in writing.
- **`OMIT_UNREAD_TAIL` and `OMIT_SIZE_CAP` reach the model through `contract._omission_line`'s
  generic fallback**, not a purpose-written sentence.

  <!-- provenance: value=_omission_line renders subject "size-cap" as `  NOT in those rows: 35999 size-cap (41000 bytes on disk; this reader reads 5000)` and "unread-tail" identically, versus the purpose-written sentences the five known subjects get; commit=23b0463; command=contract._omission_line(load_contract(), {"row_count":122}, {"subject":"size-cap","count":35999,"size":35999,"what":"..."}) -->

  The fallback is deliberate and is the right failure mode — a count that goes generic beats a
  count that vanishes — but **the raw token `size-cap` is what the model reads**, and two of
  `docread`'s seven subjects are now in that state.
- **`TEXT_MAX_BYTES` has no per-call override.** `extract_text(path: str | Path) -> Document` —
  a caller that knows it wants the 764 MB dump has no way to say so, and `page()`'s `max_bytes`
  parameter shows the module already has the shape for one.
- **`\r`-only line endings come back as ONE row**, because `_text_rows` splits on `\n` alone.
  Priced: **zero files in this corpus** use `\r`, `\v`, `\f`, `\x85`, `\u2028` or `\u2029` as a
  line break (`§AF.3`), so this is constructible and not current — the same standing
  `OMIT_UNREAD_TAIL` has.
- **`RB-P99`, for the reason given**, with five of six instances unfixed.
- **`RB-P98`'s entry-point sweep, `RB-P97`'s `env=` sweep, and `RB-P95`'s `29 of 32`** are
  untouched by this section and stand exactly as `§AE.5` left them.

##### AF.10 Gates, each at the commit it was measured at

<!-- provenance: value=full suite from the worktree with PYTHONPATH set to the worktree's runtime-py/src reads 1485 passed, 2 xfailed in 54.99s; ruff check runtime-py and ruff check docs/eval-data both report All checks passed; docread.py collects 106 nodes against 88 at c39ec48 and 77 at e5917b3; commit=23b0463; command=PYTHONPATH=$PWD/runtime-py/src .venv/bin/python -m pytest runtime-py/tests -q ; .venv/bin/ruff check runtime-py ; .venv/bin/ruff check docs/eval-data -->

```
    full suite, from the worktree, PYTHONPATH set     1485 passed, 2 xfailed   54.99s
    ruff check runtime-py                             All checks passed
    ruff check docs/eval-data                         All checks passed
    test_docread.py collected   e5917b3  77  ->  c39ec48  88  ->  23b0463  106
```

`bantamkit.docread.__file__` was confirmed to point into `bantamkit-sniff` before each of the
measurements above; without `PYTHONPATH` it resolves to the canonical checkout, and every figure
in this section would have been a figure about a tree this branch does not own.

Back to the [README](../README.md).
