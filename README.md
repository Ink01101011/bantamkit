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

Measured on the bundled 20-task suite (`qwen3:4b-instruct`, 3 repeats — full
tables in [Eval → Current results](docs/eval.md#current-results)):

- **Always attach `Memory`** — the one primitive that moves the score on this
  suite (30/60 → 57/60).
- **Use `structured()` when you need schema'd output** — enforcement costs
  nothing extra when the model complies; on this model it never needed a retry.
- **Skip `CritiqueGate` on small instruct models** — measured +47% tokens on
  `full` vs `lean` for no extra passes. Attach it only with a rubric that
  catches failures you have actually observed, and prefer instruct over
  thinking model variants when you do.
- **Prefer `GroundedCritiqueGate` over `CritiqueGate` when the agent has
  tools** — the critic sees tool call/observation pairs, letting it verify
  facts the agent got from tools. Measured: it rescued the tool-arithmetic
  task 3/3 that every other config — the blind critic included — failed 0/3
  (see [Eval](docs/eval.md)).

Copy-paste start: [`examples/`](examples/).

Agent outside Python (Claude Code, Codex, …)? The same memory and validation
ship as an [MCP server](docs/mcp.md).

## Docs

- [Install](docs/install.md) — requirements, editable install, pointing at an endpoint, `BANTAMKIT_ASSETS`
- [Usage](docs/usage.md) — the runbook: client, agent, tools, components, `structured()`, error types
- [Memory](docs/memory.md) — on-disk layout, the four ops, dedupe and budget, compact/archive
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
