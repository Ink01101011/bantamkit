"""Agent-facing memory component: skill in the prompt, correctness in the store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool
from bantamkit.client import BantamError
from bantamkit.memory.layers import (
    MEMORY_DIR_ENV,
    PROJECT_STORE,
    StoreBinding,
    count_facts,
    load_grants,
    resolve_project_store,
)
from bantamkit.memory.store import (
    DEFAULT_INDEX_BUDGET,
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


def _profile_store() -> Path:
    """The last layer `layered` appends, named once so other code can recognise it.

    It was spelled inline in `layered` and nowhere else, which is how it came to be
    prescribed as a place to start a project store: nothing that wrote the advice
    could see that the directory it was recommending is also the machine-wide layer.
    """
    return Path.home() / ".bantamkit" / "memory"


def _layer_label(root: Path) -> str:
    if root.parent.name == ".bantamkit":
        return root.parent.parent.name
    return root.name


class Memory:
    def __init__(
        self,
        store: str | Path,
        k: int = 3,
        index_budget: int = DEFAULT_INDEX_BUDGET,
        binding: StoreBinding | None = None,
    ):
        self.store = MemoryStore(store, index_budget=index_budget, k=k)
        self.k = k
        self._layers: list[tuple[str, MemoryStore, bool]] = [("project", self.store, True)]
        self._show_layers = False
        # How this store came to be the store, captured once. It cannot be re-derived
        # later: `MemoryStore(create=True)` above has already made the directory, so a
        # store that was only DESIGNATED a moment ago is indistinguishable on disk from
        # one that was found empty. `None` means the caller named the path outright --
        # `Memory(store=...)` — and no resolution happened to report.
        self._binding = binding

    @classmethod
    def layered(
        cls,
        start: str | Path | None = None,
        k: int = 3,
        index_budget: int = DEFAULT_INDEX_BUDGET,
    ) -> Memory:
        """Project store (resolved) + configured read-only grants + profile store.

        `resolve_project_store` rather than `discover_project_store`: the path both
        return is the same path (`test_resolve_path_never_disagrees_with_discover`),
        but only the binding carries WHY it is that path and whether it holds
        anything — and `recall` cannot recover either fact afterwards, because
        constructing the store creates the directory.
        """
        binding = resolve_project_store(start)
        project_root = binding.path
        mem = cls(project_root, k=k, index_budget=index_budget, binding=binding)
        mem._show_layers = True
        for grant in load_grants(project_root):
            mem._layers.append(
                (f"extra:{_layer_label(grant)}", MemoryStore(grant, k=k, create=False), False)
            )
        mem._layers.append(("profile", MemoryStore(_profile_store(), k=k, create=False), False))
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
            # Two audiences, two remedies. The store's own text names `compact()`,
            # which is now true for host code (it was a guaranteed no-op in exactly
            # this state until it grew a headroom target). This reply goes to the
            # MODEL, which by design has no compaction tool — `docs/memory.md` keeps
            # lifecycle an operator decision — so it must name what the model can do
            # instead of a remedy it cannot reach.
            return (
                f"error: {e}. Nothing was saved and retrying will not help — shorten "
                f"the description, or save under the name of an existing memory to "
                f"replace it. Compacting the index to free room is an operator job, "
                f"not a tool you have."
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
            return self._nothing_to_report()
        return "\n\n".join(self._format(label, fact) for label, fact in picked)

    # ---- the empty answer, split into the answers it was hiding ----------------

    def _nothing_to_report(self) -> str:
        """An empty recall is at least three different situations; say which one.

        Until now all of them returned "no memories matched. Try different words",
        which tells a person to rephrase a question against a filing cabinet that may
        not exist. Measured 2026-08-22 in a sandbox rebuilt from the live topology of
        MCP server pid 34377 (cwd .../trader-platform, no store of its own, nearest
        ancestor store ~/.bantamkit/memory holding 0 facts, the operator's real facts
        in a SIBLING project): both pre-N1 and N1+N2 answered with that exact string.
        N1 and N2 made the distinction nameable; nothing yet said it out loud.

        The verdict is keyed on what could have been read RIGHT NOW, counted the way
        `MemoryStore._facts` reads (`facts/*.md`), not on the construction-time
        binding — a store that was empty at construction and has been saved to since
        really can answer, and must not be slandered as empty. The diagnosis is keyed
        on the binding, because `designated` (there was no store) stops being visible
        on disk the moment `MemoryStore` creates the directory.
        """
        if self._searchable_facts():
            verdict = "no memories matched. Try different words, or proceed without."
        elif unreadable := self._unreadable_layers():
            # A layer nobody could open is not a layer that held nothing. Saying
            # "nothing is saved" here is the same slander as calling an unreadable
            # store empty, one call further out.
            verdict = (
                "no memories matched, and that is not evidence there are none: "
                + ", ".join(str(root) for root in unreadable)
                + " could not be read."
            )
        else:
            verdict = "no memories to search: nothing is saved in any layer bound here."
        diagnosis = self._binding_diagnosis()
        return f"{verdict} {diagnosis}" if diagnosis else verdict

    @staticmethod
    def _fact_count(root: Path) -> int | None:
        """How many facts a store holds, or `None` when that cannot be established.

        Counted the way `MemoryStore._facts` reads (`facts/*.md`) and the way
        `resolve_project_store` counts, so a 0 here means recall had nothing to
        return rather than that two counters disagree. A store that cannot be listed
        answers `None` and never 0: "I could not read it" and "it holds nothing" are
        the two answers this whole unit exists to keep apart.

        Via `count_facts`, because the `glob` this used to call swallowed the
        `OSError` and returned 0 — which made the `except` below unreachable dead
        code and this paragraph a description of a branch that could not fire.
        """
        try:
            return count_facts(root)
        except OSError:
            return None

    def _unreadable_layers(self) -> list[Path]:
        """Roots of the layers that could not be listed at all — never counted as 0."""
        return [
            store.root for _, store, _ in self._layers if self._fact_count(store.root) is None
        ]

    def _searchable_facts(self) -> int:
        """Facts the layers actually consulted could have matched, counted live.

        An unreadable layer contributes nothing rather than counting as empty:
        `recall` above already skips it, and it must not become evidence that there
        was nothing to read.
        """
        return sum(n for _, store, _ in self._layers if (n := self._fact_count(store.root)))

    @staticmethod
    def _is_profile_store(root: Path) -> bool:
        """Is this store also the machine-wide profile layer `layered` appends?

        Resolved on both sides because the walk returns its store path unresolved
        while `Path.home()` may itself be a symlink; a comparison that missed on a
        symlink would put the harmful advice back exactly where it does damage.
        """
        try:
            return Path(root).resolve() == _profile_store().resolve()
        except (OSError, RuntimeError):
            return False

    def _walk_ascended(self) -> bool:
        """Did the walk actually leave the directory it started in?

        `origin == "walk"` says a walk ran, not that it climbed. A walk that
        terminates at step zero has bound `searched_from`'s OWN store, and the
        clause that reads well for an ancestor binding — "which has no store of its
        own" — is then simply false about the commonest case there is: a project
        whose store exists and is empty. That sentence is what sends an operator
        hunting a binding bug that is not there.
        """
        binding = self._binding
        if binding is None or binding.searched_from is None:
            return False
        return Path(binding.path) != Path(binding.searched_from) / PROJECT_STORE

    def _binding_diagnosis(self) -> str:
        """Why THIS store, when the project layer is the one that cannot answer.

        Silent while the project store holds facts: that is the case that already
        works, and it keeps its exact wording. The remedy names `MEMORY_DIR_ENV`
        from `layers`, never a literal, so the message and the resolver cannot drift
        onto two different variable names.
        """
        if self._fact_count(self.store.root) != 0:
            return ""  # it holds facts, or could not be read: either way, no claim
        root = self.store.root
        binding = self._binding
        if binding is None:
            where = f"The project store {root} is empty."
        elif binding.state == "designated":
            where = (
                f"No memory store existed at or above {binding.searched_from}, so the "
                f"empty {root} was created for this session."
            )
        elif binding.origin == "pin":
            where = f"The project store {root} is empty; {MEMORY_DIR_ENV} pinned it."
        elif self._walk_ascended():
            where = (
                f"The project store {root} is empty; it was bound by walking up from "
                f"{binding.searched_from}, which has no store of its own."
            )
        else:
            where = (
                f"The project store {root} is empty; it is {binding.searched_from}'s own "
                f"store, bound without the walk leaving that directory."
            )
        remedy = (
            f"That is a binding, not a search result — if your facts are in another "
            f"store, set {MEMORY_DIR_ENV} to its absolute path and restart"
        )
        if self._is_profile_store(root):
            # The store bound here IS the profile layer (`_profile_store`), which
            # every project with no store of its own also binds. "Save a memory to
            # start this one" would therefore start a store that answers for all of
            # them -- measured end to end by
            # `test_a_save_into_the_bound_store_answers_for_an_unrelated_project`.
            return (
                f"{where} {remedy}. Do NOT save here to start it: {root} is also the "
                f"profile layer, so a memory saved there answers for every project on "
                f"this machine that has no store of its own — give this project a store "
                f"of its own instead."
            )
        return f"{where} {remedy}; otherwise save a memory to start this one."

    def compact(self, reserve: int | None = None) -> str:
        """Free index headroom by archiving the stalest facts, and say what it cost.

        Only the writable project layer is compacted: a read-only grant is not this
        person's to evict, and the profile layer belongs to another store's budget.

        The reply names every archived fact with its description, because `archive/`
        is a directory the model calling this will never look in — if the return value
        does not carry what was lost, nothing does.
        """
        result = self.store.compact(reserve)
        if not result.archived:
            return (
                f"nothing archived: the index is {result.index_after} bytes against a "
                f"{result.budget}-byte budget, already at or under the "
                f"{result.target}-byte compaction target."
            )
        lost = "\n".join(
            f"- {fact.name} ({fact.type}) — {fact.description}" for fact in result.archived
        )
        return (
            f"archived {len(result.archived)} memories; the index went from "
            f"{result.index_before} to {result.index_after} bytes against a "
            f"{result.budget}-byte budget, leaving {result.headroom} bytes of headroom. "
            f"These moved to {result.archive_dir} and are NOT deleted — they can be "
            f"restored by name:\n{lost}"
        )

    # Back-compat aliases: the component's API predates the public names.
    _save = save
    _recall = recall

    def _format(self, label: str, fact: Fact) -> str:
        tag = f"[{label}] " if self._show_layers else ""
        return f"{tag}[{fact.name}] ({fact.type}) {fact.description}\n{fact.body}"
