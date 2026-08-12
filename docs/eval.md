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

Two of the review's findings were fixed in this cycle rather than filed:
`requests` counted JSONL rows while `Verdict.calls` was dropped from the row
schema, so a `structured()` retry could have inflated `tokens_total` with
nothing in the report to show for it — rows now carry `calls` and the summary
carries `wire_calls` beside `requests` (`9a2312e`). And the spec's token
estimates ran 32% low on the acceptance run and 11% low on the routine profile,
against exact request counts; the spec now carries the measured numbers and the
reason (`C-attempted` costs ~580 tokens/request against `A-asfiled`'s 384, so
per-*variant* estimates cannot be scaled from one variant).

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
