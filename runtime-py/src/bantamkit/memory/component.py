"""Agent-facing memory component: skill in the prompt, correctness in the store."""

from __future__ import annotations

from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool
from bantamkit.client import BantamError
from bantamkit.memory.layers import discover_project_store, load_grants
from bantamkit.memory.store import (
    Fact,
    MemoryBudgetExceeded,
    MemoryStore,
    MemoryValidationError,
)


def _layer_label(root: Path) -> str:
    if root.parent.name == ".bantamkit":
        return root.parent.parent.name
    return root.name


class Memory:
    def __init__(self, store: str | Path, k: int = 3, index_budget: int = 4096):
        self.store = MemoryStore(store, index_budget=index_budget, k=k)
        self.k = k
        self._layers: list[tuple[str, MemoryStore, bool]] = [("project", self.store, True)]
        self._show_layers = False

    @classmethod
    def layered(
        cls, start: str | Path | None = None, k: int = 3, index_budget: int = 4096
    ) -> Memory:
        """Project store (discovered) + configured read-only grants + profile store."""
        project_root = discover_project_store(start)
        mem = cls(project_root, k=k, index_budget=index_budget)
        mem._show_layers = True
        for grant in load_grants(project_root):
            mem._layers.append(
                (f"extra:{_layer_label(grant)}", MemoryStore(grant, k=k, create=False), False)
            )
        profile = Path.home() / ".bantamkit" / "memory"
        mem._layers.append(("profile", MemoryStore(profile, k=k, create=False), False))
        return mem

    def setup(self, agent: Agent) -> None:
        agent.register_tool(ToolDef(tool=load_tool("memory_save"), handler=self.save))
        agent.register_tool(ToolDef(tool=load_tool("memory_recall"), handler=self.recall))
        agent.add_system(load_skill("memory"))

    def save(
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

    def recall(self, query: str, k: int | None = None) -> str:
        budget = k if k is not None else self.k
        picked: list[tuple[str, Fact]] = []
        seen: set[str] = set()
        for label, store, writable in self._layers:
            if len(picked) >= budget:
                break  # budget spent: later (read-only) layers are never even read
            try:
                facts = store.recall(query, budget, stamp=writable)
            except (BantamError, OSError, UnicodeDecodeError):
                if writable:
                    raise  # the project layer failing is a real error, as in v1
                continue  # a corrupt grant/profile layer must not take down recall
            for fact in facts:
                if fact.name in seen or len(picked) >= budget:
                    continue
                seen.add(fact.name)
                picked.append((label, fact))
        if not picked:
            return "no memories matched. Try different words, or proceed without."
        return "\n\n".join(self._format(label, fact) for label, fact in picked)

    # Back-compat aliases: the component's API predates the public names.
    _save = save
    _recall = recall

    def _format(self, label: str, fact: Fact) -> str:
        tag = f"[{label}] " if self._show_layers else ""
        return f"{tag}[{fact.name}] ({fact.type}) {fact.description}\n{fact.body}"
