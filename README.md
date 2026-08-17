# bantamkit

> bantamweight tooling — small models, heavyweight punch.

bantamkit is a library-first toolkit of harness primitives that lift small-model
agents (~1B–8B, served over any OpenAI-compatible endpoint). Failure modes a
harness can absorb — malformed output, unreviewed answers, forgotten context,
runaway loops — are absorbed by code rather than by asking the model to try
harder. A bundled eval suite quantifies the uplift: bare model vs model +
toolkit on the same task suite, with token accounting.

## Minimal composition

```python
from bantamkit import Agent, CritiqueGate, Memory, OpenAICompatible, Tool, ToolDef

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

price_lookup = ToolDef(
    tool=Tool(
        name="price_lookup",
        description="Get the unit price of an item",
        parameters={
            "type": "object",
            "required": ["item"],
            "properties": {"item": {"type": "string"}},
        },
    ),
    handler=lambda item: f"{item} price: 25",
)

agent = Agent(client=client, tools=[price_lookup]).use(
    Memory(store="./.bantam-memory"),
    CritiqueGate("task-completion"),
)

result = agent.run("What does a widget cost? Remember it for next time.")
print(result.output, result.usage.total)
```

## Recommended defaults

Measured on the bundled 22-task suite across **four models** —
`llama3.2:3b`, `qwen3:4b-instruct` (reference), `qwen2.5:7b-instruct`,
`qwen2.5:14b-instruct`; 528 runs each, frozen suite — full tables and the
per-claim transfer table in
[Eval → Cross-model results](docs/eval.md#cross-model-results):

- **Always attach `Memory`** — the biggest single mover on every model
  measured (e.g. 30/66 → 57/66 on the 4b reference, 34/66 → 59/66 on
  14b). How *much* of the recall family it rescues varies sharply by
  model (6/27 on 3b, 9/27 on 7b, 23/27 on 14b, 27/27 on 4b — 7b scores
  below the smaller 4b); the gap is contract wording, not the store —
  tracked as problems P1/P4 in the eval docs.
- **Skip the blind `CritiqueGate` on small instruct models** — on all
  four models it buys ≤6 passes at 2–3.5× bare's tokens. Attach a
  critique gate only with a rubric that catches failures you have
  actually observed, and prefer instruct over thinking variants. And
  expect it to deduct for *format* on answers that already comply, even
  when the rubric forbids exactly that: on the one cell measured in
  depth, 25 of 25 of the critic's sub-threshold complaints were about
  format and none disputed the content —
  [Eval → the non-fragile screen](docs/eval.md#the-non-fragile-screen-and-the-standing-anchor-set-2026-08-12).
- **Don't credit a rubric edit without a bar.** A verdict on one cell is
  not a measurement: a deleted trailing newline reproduced a whole pass
  signature once already. Before/after runs on a cell whose perturbation
  family straddles the threshold say nothing, and the standing
  no-regression floor is
  [`2026-08-12-nonfragile-anchor-set.json`](docs/eval-data/2026-08-12-nonfragile-anchor-set.json)
  — 12 cells that are stable under meaning-preserving rewordings of the
  critic's own prompt. Passing it is necessary, not sufficient.
- **Use `structured()` when you need schema'd output** — enforcement
  costs nothing when the model complies: zero schema retries in 2,112
  runs across all four models; on 7b it is the most token-efficient
  config in the matrix, on 14b second only to `graph`.
- **Attach `FileAccessGraph` when the agent reads files — on ~4B-class
  models** — it rescued both file-nav tasks 0/3 → 3/3 at +26% tokens on
  the reference. Scope measured honestly: below that class the model
  can't exploit the ledger (3b: 1/6 → 2/6), above it the tasks saturate
  under `bare` (7b/14b: 5/6). Off-family it is a code-level no-op; exact
  score equality additionally requires seed pinning (problem P9).
  **The scope is narrower than "reads files", measured: on a
  dev-repo-shaped surface, expect the `query` tool and nothing else.** On
  an 8-task repo workload at the same model class (2026-08-17) the model
  realised **zero** byte-identical repeat reads on 8 of 8 tasks, so
  `graph-off`, `graph-annotate` and `graph-cache` came out **identical on
  every one of 16 columns across all 24 rows**. `cache` can only collapse
  a repeat and `annotate` can only prefix one, so with no repeats neither
  has anything to act on. That is structural rather than a small model's
  mistake — a collapsible repeat is by definition a redundant read, so a
  larger model should realise *fewer*, not more. What is left on such a
  surface is the `query` tool, and there it **cost `+73.367%` tokens**
  against `graph-cache` while trading pass-set points in both directions:
  a trade to make deliberately, not a saving. **The two percentages in
  this bullet are not comparable and must never be subtracted.** The
  first is `graph` against `bare` on the frozen suite; the second is
  `graph` against `graph-cache` on the dev-team surface — different
  baseline, different surface, different client. Neither figure is a
  token saving, and none is claimed anywhere:
  [Eval → M](docs/eval.md#m-2026-08-17-v0220--the-dev-team-workload-surface-and-what-it-could-not-show).
- **`full` (memory + schema + grounded critique) is a 4b-reference
  result** — 66/66 there, the only perfect config. It does not transfer
  yet: 15/66 at 8.9× bare's tokens on 3b, 36/66 on 7b, and on 14b it ties
  plain `memory` at +77% tokens. The blocker is one measured defect — the
  critic's verdict contract is 4b-calibrated (P2) — with a planned fix
  (tiered contract + constrained decoding), not a fundamental limit.
- **Prefer `GroundedCritiqueGate` over `CritiqueGate` when the agent has
  tools — same 4b scope** — the critic sees tool call/observation pairs
  and rescued the tool-arithmetic task 3/3 that every config without a
  grounded critic failed 0/3. Cross-model it is gated on the same P2 fix.

Copy-paste start: [`examples/`](examples/).

Agent outside Python (Claude Code, Codex, …)? The same memory and validation
ship as an [MCP server](docs/mcp.md).

## Docs

- [Install](docs/install.md) — requirements, editable install, pointing at an endpoint, `BANTAMKIT_ASSETS`
- [Architecture](docs/architecture.md) — the 5-layer model: what lives where, the no-mixing rule, what the TS port shares
- [Usage](docs/usage.md) — the runbook: client, agent, tools, components, `structured()`, error types
- [Memory](docs/memory.md) — on-disk layout, the four ops, dedupe and budget, compact/archive
- [File-access graph](docs/filegraph.md) — the read ledger: repeat annotation, verify-on-repeat cache, `file_graph` query tool
- [Eval](docs/eval.md) — running the suite, the config matrix, reading the report, adding tasks
- [MCP](docs/mcp.md) — `bantamkit-mcp`: memory + validation for external agents (Claude Code, Codex, any MCP client)
- [Shift-work](docs/shiftwork.md) — checkpoint contract + driver for clock-in/clock-out session cycling (experimental)

The full measured tables behind the defaults above are in
[Eval → Current results](docs/eval.md#current-results).

## Repo layout

| Path | What |
|---|---|
| `runtime-py/` | The Python runtime (`bantamkit` package) and its test suite |
| `assets/` | Language-agnostic asset pack: skills, rubrics, tool schemas, eval tasks |
| `examples/` | Runnable starter scripts (quickstart, structured output, layered memory) |
| `tools/` | Repo tools that ship outside the wheel (e.g. the shift-work driver) |
| `docs/` | This runbook |

Design notes live in `docs/superpowers/specs/`.
