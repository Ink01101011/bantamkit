"""Layered memory: a discovered project store plus your personal profile store.

Each teammate runs their own stores — nothing here is shared. The project
layer (./.bantamkit/memory, discovered by walking up from cwd) is writable;
the profile layer (~/.bantamkit/memory) and any grants listed in
.bantamkit/config.yaml are read-only and simply skipped if absent.

The mkdir below anchors the project store to the directory you run this from;
without it, discovery walking up from cwd could land on an ancestor store —
even your profile store, if you run this from under your home directory.
"""

import os
from pathlib import Path

from bantamkit import Agent, Memory, OpenAICompatible

Path(".bantamkit/memory").mkdir(parents=True, exist_ok=True)

client = OpenAICompatible(
    base_url=os.environ.get("BANTAMKIT_BASE_URL", "http://localhost:11434/v1"),
    model=os.environ.get("BANTAMKIT_MODEL", "qwen3:4b-instruct"),
)

agent = Agent(client=client).use(Memory.layered())

print(
    agent.run(
        "Save this fact to memory with the memory_save tool: "
        "the payments API is owned by the billing team."
    ).output
)
print(agent.run("Which team owns the payments API? Check memory first.").output)
