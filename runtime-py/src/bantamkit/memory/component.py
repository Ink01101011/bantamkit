"""Agent-facing memory component: skill in the prompt, correctness in the store."""

from __future__ import annotations

from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool
from bantamkit.memory.store import MemoryBudgetExceeded, MemoryStore, MemoryValidationError


class Memory:
    def __init__(self, store: str | Path, k: int = 3, index_budget: int = 4096):
        self.store = MemoryStore(store, index_budget=index_budget, k=k)

    def setup(self, agent: Agent) -> None:
        agent.register_tool(ToolDef(tool=load_tool("memory_save"), handler=self._save))
        agent.register_tool(ToolDef(tool=load_tool("memory_recall"), handler=self._recall))
        agent.add_system(load_skill("memory"))

    def _save(
        self, type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> str:
        try:
            result = self.store.save(type, name, description, body, tuple(links or ()))
        except MemoryValidationError as e:
            return f"error: {e}"
        except MemoryBudgetExceeded as e:
            # Not an argument problem: retrying the same call cannot fit the index.
            return (
                f"error: {e}. Nothing was saved and retrying will not help — "
                f"compact or archive existing memories first, then save again."
            )
        if result.status == "duplicate":
            return (
                f"similar memory '{result.similar}' already exists — save under that SAME "
                f"name to update it, or skip. Do not rename to force a copy."
            )
        return f"saved '{result.name}'"

    def _recall(self, query: str, k: int | None = None) -> str:
        facts = self.store.recall(query, k)
        if not facts:
            return "no memories matched. Try different words, or proceed without."
        return "\n\n".join(f"[{f.name}] ({f.type}) {f.description}\n{f.body}" for f in facts)
