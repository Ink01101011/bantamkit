"""Quickstart: an agent with one tool and persistent memory.

This is the measured recommended shape ("lean"): Memory attached, no critique
gate. On the bundled suite it scores 57/57 where the bare model gets 30/57.
"""

import os

from bantamkit import Agent, Memory, OpenAICompatible, Tool, ToolDef

client = OpenAICompatible(
    base_url=os.environ.get("BANTAMKIT_BASE_URL", "http://localhost:11434/v1"),
    model=os.environ.get("BANTAMKIT_MODEL", "qwen3:4b-instruct"),
)

CATALOG = {"widget": 25, "gadget": 60}


def price_lookup(item: str) -> str:
    price = CATALOG.get(item.lower())
    if price is None:
        return f"error: unknown item '{item}'. known items: {sorted(CATALOG)}"
    return f"{item.lower()} price: {price}"


agent = Agent(
    client=client,
    tools=[
        ToolDef(
            tool=Tool(
                name="price_lookup",
                description="Get the unit price of an item",
                parameters={
                    "type": "object",
                    "required": ["item"],
                    "properties": {"item": {"type": "string"}},
                },
            ),
            handler=price_lookup,
        )
    ],
).use(Memory(store="./.bantam-memory"))

result = agent.run("What does a widget cost? Remember the price for next time.")
print(result.output)
print(f"tokens: {result.usage.total}")
