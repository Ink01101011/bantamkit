"""Agent-facing memory component: skill in the prompt, correctness in the store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
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


def normalize_name(name: str) -> str:
    """The model's spelling adapted to the store's contract: lowercase, `_`/space → `-`.

    The store's pattern `^[a-z0-9][a-z0-9-]*$` does not move; the component
    bends the argument to it, the same direction as tool-argument coercion.
    Measured cause: 5 of the 7b probe runs burned their whole turn budget
    retrying `memory_save` with the snake_case names the model invents.
    Non-strings are handed on untouched so store validation still speaks.
    """
    if not isinstance(name, str):
        return name
    return name.strip().lower().replace("_", "-").replace(" ", "-")


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
        agent.add_batch_scope(self.batch)
        agent.add_system(load_skill("memory"))

    @contextmanager
    def batch(self) -> Iterator[None]:
        """One assistant turn's recalls read the store as it was before the turn.

        Measured cause (RB-P1, seed 2418578173): the model dispatched recall / save /
        recall in a single turn, the speculative save updated `payments-api-owner`
        between the two reads, and it then answered `finance-team` off its own
        fabrication instead of the seeded `Atlas`. Nothing was wrong with the write —
        `save` is doing its documented job — the defect is that a batch the model
        composed from one view of memory got answered from another.

        Only writable layers are pinned. A read-only grant cannot be written by
        `save`, so it cannot be poisoned, and pinning it would move a corrupt-layer
        error from `recall` (where it is caught and the layer skipped) to the batch
        boundary (where it would take down the run).
        """
        with ExitStack() as stack:
            for _, store, writable in self._layers:
                if writable:
                    stack.enter_context(store.snapshot())
            yield

    def save(
        self, type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> str:
        name = normalize_name(name)
        links = [normalize_name(link) for link in links or []]
        try:
            result = self.store.save(type, name, description, body, tuple(links))
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
        """`k` is the model asking for *more*, never for less than the store's default.

        Measured cause (RB-P1, qwen2.5:14b-instruct): 57 of 60 `memory_recall` calls
        across 12 seeded runs sent `k: 1`, and honouring it truncated recall to the
        single best-scoring fact. Every two-fact task then answered from half its
        evidence — `recall-org-quota` never once saw `org-seat-count`, which was on
        disk the whole time. Same direction as `normalize_name` above: the component
        bends the model's argument to the store's contract, and `MemoryStore.recall`
        stays honest about returning exactly the `k` it was told.

        The floor is the operator's configured default, not a constant, so a consumer
        who really wants top-1 says so once at construction (`Memory(store, k=1)`).
        """
        budget = self.k if k is None else max(k, self.k)
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
