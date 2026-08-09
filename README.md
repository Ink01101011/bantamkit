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
  14b). How *much* of the recall family it rescues scales with model size
  (6/27 on 3b → 27/27 on 4b); the gap is contract wording, not the store
  — tracked as problems P1/P4 in the eval docs.
- **Skip the blind `CritiqueGate` on small instruct models** — on all
  four models it buys ≤6 passes at 2–3.5× bare's tokens. Attach a
  critique gate only with a rubric that catches failures you have
  actually observed, and prefer instruct over thinking variants.
- **Use `structured()` when you need schema'd output** — enforcement
  costs nothing when the model complies: zero schema retries in 2,112
  runs across all four models, and on 7b/14b it is the *most*
  token-efficient config in the matrix.
- **Attach `FileAccessGraph` when the agent reads files — on ~4B-class
  models** — it rescued both file-nav tasks 0/3 → 3/3 at +26% tokens on
  the reference. Scope measured honestly: below that class the model
  can't exploit the ledger (3b: 1/6 → 2/6), above it the tasks saturate
  under `bare` (7b/14b: 5/6). Off-family it is a code-level no-op; exact
  score equality additionally requires seed pinning (problem P9).
- **`full` (memory + schema + grounded critique) is a 4b-reference
  result** — 66/66 there, the only perfect config. It does not transfer
  yet: 15/66 at 8.9× bare's tokens on 3b, 36/66 on 7b, and on 14b it ties
  plain `memory` at +77% tokens. The blocker is one measured defect — the
  critic's verdict contract is 4b-calibrated (P2) — with a planned fix
  (tiered contract + constrained decoding), not a fundamental limit.
- **Prefer `GroundedCritiqueGate` over `CritiqueGate` when the agent has
  tools — same 4b scope** — the critic sees tool call/observation pairs
  and rescued the tool-arithmetic task 3/3 that every other config failed
  0/3. Cross-model it is gated on the same P2 fix.

Copy-paste start: [`examples/`](examples/).

Agent outside Python (Claude Code, Codex, …)? The same memory and validation
ship as an [MCP server](docs/mcp.md).

## Docs

- [Install](docs/install.md) — requirements, editable install, pointing at an endpoint, `BANTAMKIT_ASSETS`
- [Usage](docs/usage.md) — the runbook: client, agent, tools, components, `structured()`, error types
- [Memory](docs/memory.md) — on-disk layout, the four ops, dedupe and budget, compact/archive
- [File-access graph](docs/filegraph.md) — the read ledger: repeat annotation, verify-on-repeat cache, `file_graph` query tool
- [Eval](docs/eval.md) — running the suite, the config matrix, reading the report, adding tasks
- [MCP](docs/mcp.md) — `bantamkit-mcp`: memory + validation for external agents (Claude Code, Codex, any MCP client)

The full measured tables behind the defaults above are in
[Eval → Current results](docs/eval.md#current-results).

## Repo layout

| Path | What |
|---|---|
| `runtime-py/` | The Python runtime (`bantamkit` package) and its test suite |
| `assets/` | Language-agnostic asset pack: skills, rubrics, tool schemas, eval tasks |
| `examples/` | Runnable starter scripts (quickstart, structured output, layered memory) |
| `docs/` | This runbook |

Design notes live in `docs/superpowers/specs/`.
