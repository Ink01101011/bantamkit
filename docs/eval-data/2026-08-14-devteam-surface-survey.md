# Dev-team workload surface: what exists, what it can attribute, and what it cannot

M1 of job `devteam-workload-and-null-control`. **Probe only** — this cycle builds no
workload, no graph, and no feature. It answers one question: *is the >60% token-reduction
claim measurable on anything that exists in this repo today?*

Every table below is stdout of
[`2026-08-14-devteam-surface-survey.py`](2026-08-14-devteam-surface-survey.py):

```
.venv/bin/python docs/eval-data/2026-08-14-devteam-surface-survey.py .
```

The script reads only committed sources (the frozen task YAMLs and the runtime
package). It calls no model, writes nothing, and touches no frozen asset.

Line references are against `3741ac5` (main, v0.21.0).

---

## Verdict, up front

**The >60% token-reduction claim cannot be measured on anything that exists today.**
Not "is unmeasured" — *cannot be*, for three independent reasons, any one of which is
sufficient:

1. **No mechanism in the repo reduces tokens.** Every component measured to date costs
   tokens; the one with a plausible reduction route (`FileAccessGraph`'s verify-on-repeat
   collapse) has already been isolated on its own ablation ladder and measured at
   **−0.05% and +4.9%** — the second with the wrong sign. See [Survey 2](#survey-2).
2. **The accounting cannot attribute a reduction to a mechanism.** The finest grain in
   the harness is **one scalar per (task, config, repeat)**. Nothing separates a
   mechanism's own token cost from tokens it saves downstream except differencing two
   whole-run totals across configs. See [Survey 1](#survey-1).
3. **There is no dev-team surface to reduce tokens over.** 20 of 22 frozen tasks touch
   no file at all; the 2 that do share **12 fixture files, 0 of which are code**, and
   the suite contains zero diffs, zero symbols, zero imports, zero stack traces, zero
   tests, and zero git history. See [Survey 3](#survey-3).

The smallest honest instrument is stated in [§5](#5-the-smallest-honest-instrument).

---

## Things in the brief and the orchestrator's reading that do not reproduce

Reported first, per the probe unit's standing duty.

| Claim | Status | Evidence |
|---|---|---|
| "22 frozen tasks (extract 5, nav 2, **recall 8**, shop 6)" | **DOES NOT REPRODUCE.** recall is **9**, not 8. 5+2+9+6 = 22. | Table 1. `ls assets/evals/tasks/ \| grep -c '^recall-'` → 9. `docs/eval.md:667-668` also says 9. |
| Headline "**full = lean's score at +51% tokens**" | **DOES NOT REPRODUCE — no part of it.** `grep -rn '51%'` over the whole repo returns **0 hits**. The nearest committed claim is `+41%`, it pairs `full` against `lean` on the **retired 19-task suite**, and at HEAD on the frozen 22-task suite `full` does **not** equal `lean`'s score. | `docs/eval.md:1113,1152` (+18369 tok, +41%, on the 19-task suite where both score 57/57, `docs/eval.md:1047-1052`). At HEAD: `lean` 57/66 @ 54543 tok, `full` 66/66 @ 109243 tok — **+54,700 tok (+100.3%) for +9 passes** (`docs/eval.md:678-685`). |
| `TokenBudget` is "**blind to critic spend** (recorded debt)" | **DOES NOT REPRODUCE AT HEAD.** The governor sees critic spend. The docstring states the fix in the past tense. | `budget.py:57-64`, quoted in [Survey 1](#survey-1). Confirmed live by `critique.py:172` and `evalrun.py:436-444`. |
| `TokenBudget` is a "**tail-cutter only**" | **REPRODUCES**, and is stronger than stated — see below. | `budget.py:66-68`; only two `allow()` call sites exist in the whole package. |
| `filegraph.py` is "a ledger of file reads — which paths, via which tool, whether they changed — with verify-on-repeat collapsing, **not a search or mapping graph**" | **REPRODUCES**, verbatim — it is the module's own first line. Two precisions added below. | `filegraph.py:1`, `filegraph.py:15-21`. |
| Verify-on-repeat collapsing "**avoids re-reading**" | **DOES NOT REPRODUCE** — and the correction is to the brief, not to the repo, which already documents it. The inner reader is called *every* time; what is collapsed is the observation handed back to the model. | `filegraph.py:62` — `observation = str(inner(**kwargs))` runs before any ledger logic. `docs/filegraph.md:34-38` states it independently: "the real handler runs on *every* call … What is saved is model tokens, not disk I/O". |
| "The `nav` family and the `graph` config use per-task `workspace:` file tools — so 'zero touch a file surface' may be too strong" | **CORRECT, and the brief was right to hedge.** 2/22 tasks touch a file surface. But "zero touch a **repo, a diff, a symbol, or code**" is exactly right: **0/22**. | Tables 2, 3, 4. |

---

## Survey 1

### Token accounting: what is counted, at what grain, and what it can attribute

**Command:** `.venv/bin/python docs/eval-data/2026-08-14-devteam-surface-survey.py .` (Table 5)

| Site | `file:line` | Kind |
|---|---|---|
| `TrackingClient.chat` accumulates `Usage` | `evalrun.py:194` | record |
| `TrackingClient.calls` counter | `evalrun.py:195` | record |
| `TaskResult.tokens = tracking.usage.total` | `evalrun.py:572` | **attribute — the only one** |
| `_BudgetedClient.chat` books usage | `budget.py:28` | record |
| `TokenBudget.record` adds `usage.total` | `budget.py:100` | record |
| `Agent.run` asks `allow("required")` | `agent.py:182` | decide |
| Critique gate asks `allow("optional")` | `critique.py:183` | decide |
| `score/1k = passed / (tokens/1000)` | `evalrun.py:638` | derive |

**Granularity: one integer per (task, config, repeat).** `TaskResult` (`evalrun.py:150-165`)
carries exactly one token column — `tokens` — and it is the endpoint's `usage.total`
summed over every call the run made, gates included.

**What it can attribute:**

| Question | Answerable? | How |
|---|---|---|
| tokens per run | **yes** | `TaskResult.tokens` |
| tokens per task | **yes** | one row per (task, config, repeat) |
| tokens per config | **yes** | summed at report time, `evalrun.py:637` |
| tokens per family | **yes** | `evalrun.py:645-653` |
| tokens per **model call** | **no** | `TrackingClient.chat` (`evalrun.py:194`) adds into a single running `Usage`; the per-call figure is discarded |
| tokens per **tool call** | **no** | `tool_calls` (`evalrun.py:159`) is a count of events, not tokens |
| tokens per **gate / mechanism** | **no** | see below |
| a mechanism's **own cost** vs the tokens it **saves downstream** | **no** | see below |

**Nothing separates a mechanism's own token cost from the tokens it saves downstream.**
The only instrument that comes close is *differencing two whole-run totals across two
configs that differ by one component* — the ablation ladder, e.g. `GRAPH_CONFIGS`
(`evalrun.py:125-129`), `BUDGET_CONFIGS` (`evalrun.py:134`), `GUARD_CONFIGS`
(`evalrun.py:139`). That difference is a **net**: it cannot tell a mechanism that costs
1000 and saves 1000 from a mechanism that does nothing. The four event counters
(`model_calls`, `tool_calls`, `schema_retries`, `critique_rounds`, `evalrun.py:158-161`)
are the only sub-run resolution that exists, and none of them is denominated in tokens.

`score/1k tok` is **not** a token-reduction measure. It is a ratio whose numerator is the
score, so it moves when correctness moves; `docs/eval.md:162-165` says so directly.

### Is `TokenBudget` still a tail-cutter blind to critic spend?

**Blind to critic spend: NO — that was fixed and the docstring records it in the past
tense.** `budget.py:57-64`:

> Spend is booked at the client boundary: `setup` wraps `agent.client` in a
> `_BudgetedClient`, so every call made through the agent's client moves
> `spent` — the agent's own turns *and* the critic calls the gates issue
> through `structured()` on that same client. That is the point: the critique
> rounds are the dominant optional spend the cutoff exists to govern, and
> **while `Agent.run` was the only recording point they were invisible to the
> governor.**

Corroborated live: `critique.py:172` (`self.budget = getattr(agent, "budget", None)`)
and the ordering comment at `evalrun.py:436-439` ("Before every gate … a budget attached
after it would be a governor nothing ever asks").

**Tail-cutter only: YES, and structurally so.** `budget.py:66-68`:

> `structured()` is still not budgeted as a *loop*: it never asks `allow()`
> between its own retries, which stay bounded by `max_retries`. What changed
> is visibility, not control.

There are exactly **two** `allow()` call sites in the entire package — `agent.py:182`
(top of each agent turn) and `critique.py:183` (before each critique round). The governor
therefore has one lever and one only: **refuse future work**. `allow()` returns a bool
(`budget.py:102-114`); it cannot shrink a prompt, compress an observation, or change what
a permitted call sends.

**Consequence for this job, stated as a scoping fact and not a design:** `TokenBudget`'s
only route to fewer tokens is *doing less of the task*. Any reduction it produces is
bought by degrading the run (`budget.py:42-46`: optional work skipped, then the loop
stops and returns "the last assistant content as a best-effort result"). Under this job's
standing invariant that **the null control must preserve meaning**, a truncation arm's
token delta is not comparable to a baseline that finished the work. M2 must know this
before it counts `budgeted` as one of the five arms.

### "full = lean's score at +51% tokens" — what is it a result about?

**The pairing and the number both fail to reproduce** (see the table above). Taking the
substance of the question rather than its arithmetic:

**Confirmed: it is a configuration choice, not a token-reduction mechanism.** `lean` and
`full` are two different feature sets — `docs/eval.md:120-122`: "`lean` runs the same
agent loop with memory and `SchemaGate` but no critic, so `full − lean` isolates
critique's cost and uplift." The delta is a **feature bill**: what the grounded critic
costs and what it buys. Read in the reduction direction it says "turning a gate off saves
tokens", which is trivially true of any feature and true of removing any capability.

**What it would take for it to bear on a >60% claim — and why it cannot.** A token-reduction
claim needs two arms that produce **the same work product at different token cost**: same
tasks, same score, and ideally the same tool trace, with the difference confined to how
many tokens crossed the wire. `lean` vs `full` fails this on every count at HEAD — 57/66 vs
66/66, and `full` additionally spends the tool-use family differently (`grounded` rescues
the tool-use family, 15/18 → 18/18, `docs/eval.md:697-698`). Even on the retired 19-task suite where scores
*were* equal (57/57 both), the equality is an artifact of a saturated suite, not of two
arms doing equivalent work: `critique_rounds == 0` in all 57 `full` runs
(`docs/eval.md:1112-1115`) — the critic never fired, so the +41% was pure scoring-call
overhead on top of an unchanged answer.

**Plainly: this headline cannot be made to bear on a >60% token-reduction claim, in
either direction.** It is the price of a capability, and no rescaling turns the cost of
adding a critic into evidence that a mechanism compressed anything. That is the finding.

---

## Survey 2

### What `filegraph.py` actually is

110 lines. **The orchestrator's reading reproduces** — it is the module's own docstring
(`filegraph.py:1`): "Deterministic ledger of file reads: which paths, via which tool, and
whether they changed." The record is `FileRead(path, tool, digest, count, changed)`
(`filegraph.py:15-21`) and nothing else.

Two precisions, both sharpening rather than overturning:

**1. It is not a graph. There are no edges.** `self.reads` is a flat `dict[str, FileRead]`
keyed by path (`filegraph.py:40`). No field relates one path to another; `render()`
(`filegraph.py:94-100`) emits one independent line per path. The word "graph" in the class
name and in the `file_graph` tool describes an aspiration, not the data structure. A
consumer can ask exactly one question — "list every path I have read, with its count and
whether it changed" — and `render()` takes no arguments, so there is no narrower query.

**2. Verify-on-repeat collapsing does not avoid re-reading.** `filegraph.py:62` runs
`observation = str(inner(**kwargs))` *before* any ledger logic; the underlying reader is
invoked on every call. What the collapse suppresses is the **re-injection of the content
into the model's context** (`filegraph.py:83-88`), replacing it with a ~90-byte marker.
For the in-memory workspace dict these coincide token-wise, but against a real file tool
the distinction matters: the ledger never prevents work, only prevents re-narration.
`docs/filegraph.md:34-38` already says exactly this — "the real handler runs on *every*
call … What is saved is model tokens, not disk I/O" — so this is a correction to the
brief's phrasing, not a defect in the repo.

### Mechanism by mechanism, and the token route of each

**Command:** survey script, Table 6.

| Mechanism | `filegraph.py:line` | Flag | Token route |
|---|---|---|---|
| Record a read (path, tool, sha256, count, changed) | 72-81 | always on | **0** — write path never involves a model (`filegraph.py:26-27`) |
| Annotate a repeat read | 89-91 | `annotate` | **ADDS** — prepends a marker line *in front of the full observation* |
| Collapse an unchanged repeat | 83-88 | `cache` | **SAVES** — replaces the observation with a marker |
| Expose `file_graph` query tool + skill | 51-53 | `query` | **ADDS** — a tool schema and a system skill in every prompt, plus the model's calls to it |
| `render()` the ledger | 94-100 | `query` | **ADDS** — the tool's output is an observation |
| `save()` / `load()` the ledger | 102-110 | always | **0** — disk only |

**The only token-reduction route in the module is `cache`.** Its ceiling is the bytes of
the byte-identical repeat reads a run would otherwise have made — **zero if the agent
never re-reads a file**. Nothing in the class measures the bytes it saves: `size` at
`filegraph.py:84` is interpolated into the marker string and discarded.

### Is that saving measurable from outside?

**In principle yes; under the shipped config no; and the isolating measurement has already
been run and says it is ~0%.**

- Not under `graph`: the headline config sets `annotate`, `cache` and `query` all `True`
  (`evalrun.py:126`), and two of the three push the other way.
- The isolation exists as a calibration ladder — `graph-annotate` `{annotate:T, cache:F,
  query:F}` vs `graph-cache` `{annotate:T, cache:T, query:F}` (`evalrun.py:127-128`).
  Their difference is the collapse mechanism and nothing else.
- **That ladder was run on 2026-08-09** and both JSONLs are committed. Re-derived here
  (15 runs per config: 5 candidate nav tasks × 3 repeats; only 2 of the 5 survived into
  the frozen suite):

| Sweep | `graph-annotate` | `graph-cache` | **cache in isolation** | score |
|---|---|---|---|---|
| `2026-08-09-filegraph-calibration.jsonl` | 10,439 tok | 10,434 tok | **−5 tok (−0.05%)** | 3/15 both |
| `2026-08-09-filegraph-calibration-tuned.jsonl` | 19,127 tok | 20,069 tok | **+942 tok (+4.9%)** | 8/15 both |

**The one mechanism in this repo with a token-reduction route has been isolated and
measured at −0.05% and +4.9%.** Against a >60% target that is not a shortfall, it is a
different category of result: on this workload the agent does not re-read files often
enough for the collapse to have anything to collapse.

The shipped `graph` config's net effect is a token **increase** that buys score:
suite-wide `bare` 18,380 → `graph` 23,200 (**+26%**); on its own family 6,928 → 11,776
(**+70%**) for 0/6 → 6/6 (`docs/eval.md:678-685`, `691`/`695`). It is a correctness mechanism with a
token cost, not a token mechanism.

### What it would have to gain to be a search/mapping graph

Scoped as a gap, not a design. It would need:

1. **Edges.** Nothing today relates path A to path B (`filegraph.py:40`).
2. **A content index.** The only thing retained per path is a sha256 (`filegraph.py:73`),
   which is deliberately unsearchable.
3. **Symbol/identifier extraction.** No parse step of any kind exists.
4. **A query surface narrower than "everything".** `render()` takes no arguments
   (`filegraph.py:94`); `file_graph` is a zero-argument tool.
5. **Coverage of unread files.** The ledger is written only by the wrapper on a declared
   reader (`filegraph.py:43,55-70`), so a path the agent never read does not exist to it.
   A search graph must answer about files nobody opened; this one cannot, by construction.
6. **A live change signal.** `FileRead.changed` (`filegraph.py:21`) can only ever be
   `False` in this suite — see [Survey 4](#survey-4) gap 2.

---

## Survey 3

### The workload-surface census — all 22 frozen tasks

**Command:** survey script, Tables 1-4.

| Family | n | Prefix | Tools | Any file surface? |
|---|---|---|---|---|
| `structured-extraction` | 5 | `extract-` | none | **no** — prompt-only |
| `file-nav` | **2** | `nav-` | `read_file`, `list_files` | **yes** — `workspace:` |
| `memory-recall` | **9** | `recall-` | none | **no** — `memory_setup:` store |
| `tool-use` | 6 | `shop-` | `price_lookup`, `stock_lookup` | **no** — JSON catalog lookup |
| **TOTAL** | **22** | | | **2 yes / 20 no** |

(recall is 9, not the 8 the brief states.)

**What the workspaces actually contain** — 12 files across the 2 nav tasks:

| Kind | Files | Examples |
|---|---|---|
| prose (`.md`, `VERSION`) | **9** | `README.md`, `docs/deploy.md`, `docs/release.md`, `style.md`, `ci.md`, `VERSION` |
| config (`.yaml`, `.cfg`) | **3** | `config/prod.yaml`, `config/staging.yaml`, `package.cfg` |
| **code** | **0** | — |

Largest file: 881 bytes (`ci.md`). Both workspaces are dict literals inlined in the task
YAML, materialised per task by `_workspace_tools` (`evalrun.py:93-122`) into two
read-only closures over that dict.

**Dev-team surface markers across all 22 tasks (prompt + workspace):**

| Marker | Tasks hit |
|---|---|
| git history (commit / sha / branch / ref) | **0** * |
| a diff or patch hunk | **0** |
| a symbol definition (`def`/`class`/`func`/…) | **0** |
| an import / require / include | **0** |
| a stack trace or exception | **0** |
| a test or assertion | **0** |

\* The regex reports 2, and both are the same false positive: the English verb in
"never commit tokens" inside the two `ci.md` fixtures. Grepped and read; no ref, sha,
or history exists anywhere in the suite.

**So the brief's hedge was right and the orchestrator's phrasing was too strong.** "Zero
tasks touch a file surface" is **false** — 2 do. "Zero tasks touch a repo, a diff, a
symbol, or code" is **exactly true** — 0/22. The nav workspaces are a *pointer-chase over
prose*, which is what they were built to be: the task is "follow each pointer the files
give you" (`nav-prod-port` prompt), and the answer is a port number sitting in a YAML.

**This decides M2's question.** The `workspace:` mechanism is a real, working file surface
with a read tool, a list tool, and a graph that already attaches to it — but it holds no
code and cannot hold a repo. M2 extends a *mechanism* that exists; it starts clean on
*content*.

One scoping number for M2: `FileAccessGraph` attaches only when a task declares a
workspace tool (`evalrun.py:521`), so the graph's entire measurable surface in the frozen
suite is **2 tasks × 3 repeats = 6 runs per config**.

---

## Survey 4

### What a dev-team task would need that nothing here provides

Scoped as *what the harness would have to be able to do*. M2 designs; this unit measures.

| # | Gap | What exists today | What the harness would have to be able to do |
|---|---|---|---|
| 1 | **A repo, not a fixture dict** | `workspace:` is a dict literal inside each frozen task YAML, materialised per task (`evalrun.py:93-104`). No two tasks can share one. | Present a file surface that outlives a single task and is addressed by path, not inlined per task. |
| 2 | **Mutation** | `_workspace_tools` exposes `read_file` and `list_files` only (`evalrun.py:105-122`). There is no write tool anywhere in `BUILTIN_TOOLS` or `WORKSPACE_TOOLS` (`evalrun.py:79-84`). | Let a run change a file. Until then `FileRead.changed` (`filegraph.py:21`) is dead code in the suite — it can only ever be `False`, and the "CHANGED since your last read" branch (`filegraph.py:90`) is unreachable. |
| 3 | **A diff as a first-class object** | Nothing represents one, and nothing scores one. `score_output` supports exactly three kinds — `json_equal`, `contains`, `tool_trace` (`evalrun.py:219-233`). | Represent a patch/hunk as input, and score "did the run produce the right edit" — a fourth scoring kind at minimum. |
| 4 | **Symbol resolution across files** | The only per-file content record is a sha256 (`filegraph.py:73`). No parse, no index, no identifier table. | Extract identifiers from file content and answer "where is X defined". |
| 5 | **Cross-file references** | No edges anywhere (`filegraph.py:40`). | Relate one path to another (imports, callers, ownership) and answer a reachability question. |
| 6 | **Git history** | 0 markers in 22 tasks (Table 4). | Address content by revision, and answer "what changed and when". |
| 7 | **Per-mechanism token attribution** | One scalar per run (`evalrun.py:572`); the only separation instrument is differencing two whole-run totals (Survey 1). | Attribute tokens to a mechanism finely enough that a claim about *that mechanism* can be falsified — see below. |

---

## 5. The smallest honest instrument

Stated as a requirement, not a design, and deliberately not pre-registering a bar.

A >60% token-reduction claim about a mechanism is falsifiable only if all four hold:

1. **A workload with re-read pressure.** The reduction route that exists (collapse) pays
   only when the agent reads the same path twice. The current nav tasks are pointer
   chases with almost no re-reading, which is exactly why the isolated cache measured
   −0.05%. The workload must make re-reading the *natural* strategy, not an accident;
   otherwise the mechanism has nothing to act on and a 0% result says nothing about it.
2. **A meaning-preserving null control.** The comparison arm must complete the same work
   to the same score — not the same run with a feature switched off, and never a
   truncation arm. `budgeted` cannot serve here: `TokenBudget`'s only lever is refusing
   work (Survey 1), so its token delta is bought by not finishing.
3. **A one-mechanism ablation ladder, which already exists in form.** `GRAPH_CONFIGS`
   (`evalrun.py:125-129`) is the working precedent: `graph-cache` − `graph-annotate`
   isolates one flag. Any new mechanism needs the same shape, or its whole-run delta is a
   net that cannot distinguish "saves 1000 and costs 1000" from "does nothing".
4. **Score held fixed, and reported.** A token delta at a different score is a trade, not
   a reduction; `score/1k tok` deliberately mixes the two (`docs/eval.md:162-165`) and
   cannot substitute.

Anything less measures a configuration choice, which is what every token headline in this
repo currently is.

---

## Reproduction

```
.venv/bin/python docs/eval-data/2026-08-14-devteam-surface-survey.py .
.venv/bin/python -m pytest runtime-py/tests -q        # 800 passed, 2 xfailed
.venv/bin/ruff check runtime-py tools/pinharness      # All checks passed!
```

Frozen assets read, none edited. No committed evidence file regenerated or retro-edited.
Tokens and wall-clock for this unit: **UNMEASURED**.
