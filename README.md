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

## Docs

- [Install](docs/install.md) — requirements, editable install, pointing at an endpoint, `BANTAMKIT_ASSETS`
- [Usage](docs/usage.md) — the runbook: client, agent, tools, components, `structured()`, error types
- [Memory](docs/memory.md) — on-disk layout, the four ops, dedupe and budget, compact/archive
- [Eval](docs/eval.md) — running the suite, the config matrix, reading the report, adding tasks

Latest measured numbers (19-task sweep on `qwen3:4b-instruct`, 3 repeats) are
in [Eval → Current results](docs/eval.md#current-results): memory lifts 30/57 →
57/57, while the critique gate adds 41% more tokens for zero extra passes — and
per-run gate counters prove it never fired.

## Repo layout

| Path | What |
|---|---|
| `runtime-py/` | The Python runtime (`bantamkit` package) and its test suite |
| `assets/` | Language-agnostic asset pack: skills, rubrics, tool schemas, eval tasks |
| `docs/` | This runbook |

Design notes live in `docs/superpowers/specs/`.
