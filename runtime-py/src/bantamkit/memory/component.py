"""Agent-facing memory component: skill in the prompt, correctness in the store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SaveOutcome:
    """What `save` DECIDED, beside the sentence it says about it.

    THE POINT OF THIS TYPE IS THAT `status` IS NOT DERIVED FROM `reply`. `Memory.save`
    has four outcomes — stored, deduped, refused by validation, refused by the budget —
    and all four leave the process as one string that the MCP host records as
    "completed successfully in Nms". Anything downstream that wanted to tell them apart
    had exactly one route: match the reply text. That route is a re-derivation which
    breaks silently the day the wording improves, and it is why this field exists.

    `status` is one of `saved`, `duplicate`, `refused-validation`, `refused-budget`, and
    every one of them is read off a decision the code had already made — `SaveResult`'s
    own `status`, or which `except` clause caught. `reply` is the unchanged string
    `save()` has always returned; nothing reads it.
    """

    reply: str
    status: str


@dataclass(frozen=True)
class RecallOutcome:
    """What `recall` DID, beside the facts it formatted.

    `recall` walks the layers in order, stops the moment the budget is spent, dedupes by
    name, and — when nothing matched — picks one of three different verdicts about WHY
    (see `_nothing_to_report`). None of that survived into the reply the host times: an
    empty recall and a three-fact recall are the same log line to it, and the three
    empties are indistinguishable from each other even to a reader of the reply, because
    telling them apart means matching prose.

    `status` is `answered` or one of `empty-no-match` / `empty-unreadable-layer` /
    `empty-nothing-saved`, keyed on the same branch that chooses the verdict sentence
    rather than on the sentence. `source` is the KIND of the layer that answered first —
    `project`, `extra` or `profile` — deliberately not the layer's full label, because
    `extra:<name>` carries a directory name off the operator's disk and the log this
    feeds is metadata-only.
    """

    reply: str
    status: str
    budget: int
    layers: int
    reached: int
    returned: int
    candidates: int
    source: str | None = None
    unreadable: int = 0


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
        """The reply the model reads. Unchanged, and still the tool's advertised return."""
        return self.save_outcome(type, name, description, body, links).reply

    def save_outcome(
        self, type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> SaveOutcome:
        """`save`, with the branch it took carried out alongside the sentence it wrote.

        Same body, same order, same four exits: the only change is that each exit now
        NAMES itself. That is the whole of the narrow seam the MCP server needs to log
        an outcome without matching text, and it moves no wording and no return type —
        `save()` above still answers `str`, and `assets/tools/memory_save.json` still
        advertises `str`.
        """
        name = normalize_name(name)
        links = [normalize_name(link) for link in links or []]
        try:
            result = self.store.save(type, name, description, body, tuple(links))
        except MemoryValidationError as e:
            return SaveOutcome(reply=f"error: {e}", status="refused-validation")
        except MemoryBudgetExceeded as e:
            # Not an argument problem: retrying the same call cannot fit the index.
            # Two audiences, two remedies. The store's own text names `compact()`,
            # which is now true for host code (it was a guaranteed no-op in exactly
            # this state until it grew a headroom target). This reply goes to the
            # MODEL, which by design has no compaction tool — `docs/memory.md` keeps
            # lifecycle an operator decision — so it must name what the model can do
            # instead of a remedy it cannot reach.
            return SaveOutcome(
                reply=(
                    f"error: {e}. Nothing was saved and retrying will not help — shorten "
                    f"the description, or save under the name of an existing memory to "
                    f"replace it. Compacting the index to free room is an operator job, "
                    f"not a tool you have."
                ),
                status="refused-budget",
            )
        if result.status == "duplicate":
            return SaveOutcome(
                reply=(
                    f"similar memory '{result.similar}' already exists — save under that "
                    f"SAME name to update it, or skip. Do not rename to force a copy."
                ),
                status="duplicate",
            )
        return SaveOutcome(reply=f"saved '{result.name}'", status="saved")

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
        return self.recall_outcome(query, k).reply

    def recall_outcome(self, query: str, k: int | None = None) -> RecallOutcome:
        """`recall`, carrying the walk it performed as numbers rather than as prose.

        The reply is byte-for-byte what `recall` has always returned; every field beside
        it is counted here because it CANNOT be recovered afterwards. How far down the
        layer list the budget got, how many of the layers reached were readable, how
        many facts those layers held against how many came back, and which of the three
        empty verdicts fired — all of it is gone by the time the string exists, and the
        host's log records only that a `memory_recall` "completed successfully".

        `candidates` counts `facts/*.md` in the layers actually READ, via `count_facts`
        — the same filter `MemoryStore.recall` scores over, so the ratio to `returned`
        is between two counts of one population and not between two different ones. A
        layer whose directory refuses to list contributes nothing and raises the
        `unreadable` count instead of being scored as empty; that distinction is the
        whole subject of `_nothing_to_report` below and must not be undone here.
        """
        budget = self.k if k is None else max(k, self.k)
        picked: list[tuple[str, Fact]] = []
        seen: set[str] = set()
        reached = 0
        unreadable = 0
        candidates = 0
        for label, store, writable in self._layers:
            if len(picked) >= budget:
                break  # budget spent: later (read-only) layers are never even read
            reached += 1
            try:
                facts = store.recall(query, budget, stamp=writable)
            except (BantamError, OSError, UnicodeDecodeError):
                if writable:
                    raise  # the project layer failing is a real error, as in v1
                unreadable += 1
                continue  # a corrupt grant/profile layer must not take down recall
            try:
                candidates += count_facts(store.root)
            except OSError:
                # It scored a moment ago, so it is readable; a race that unlists it now
                # must not turn a successful recall into a failed one for a log field.
                pass
            for fact in facts:
                if fact.name in seen or len(picked) >= budget:
                    continue
                seen.add(fact.name)
                picked.append((label, fact))
        counts = {
            "budget": budget,
            "layers": len(self._layers),
            "reached": reached,
            "returned": len(picked),
            "candidates": candidates,
            "unreadable": unreadable,
        }
        if not picked:
            status, reply = self._nothing_to_report()
            return RecallOutcome(reply=reply, status=status, **counts)
        return RecallOutcome(
            reply="\n\n".join(self._format(label, fact) for label, fact in picked),
            status="answered",
            source=picked[0][0].split(":", 1)[0],
            **counts,
        )

    def index_accounting(self) -> tuple[int | None, int]:
        """`(index bytes, budget)` for the writable project store; bytes may be `None`.

        Measured exactly the way `MemoryStore._check_index_budget` measures — the UTF-8
        length of `index_text()` — so the number a log records and the number a refusal
        was decided against are one number and not two that can drift apart.

        `None` means the store could not be read, and it is never 0: an unreadable store
        reporting an empty index is the same slander this module spends
        `_nothing_to_report` refusing to commit, and it would read as infinite headroom
        at exactly the moment there is none. The cost is a full parse of `facts/`, which
        is why nothing calls this on the tool path unless a log is actually enabled.
        """
        try:
            return len(self.store.index_text().encode("utf-8")), self.store.index_budget
        except (BantamError, OSError, UnicodeDecodeError):
            return None, self.store.index_budget

    # ---- the empty answer, split into the answers it was hiding ----------------

    def _nothing_to_report(self) -> tuple[str, str]:
        """An empty recall is at least three different situations; say which one.

        Answers `(status, text)`. The status is the SAME BRANCH that picks the sentence,
        handed out rather than re-derived: a caller that needs to tell the three empties
        apart — the MCP event log does — would otherwise have to match the prose this
        docstring exists to say is allowed to improve.

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
            status = "empty-no-match"
            verdict = "no memories matched. Try different words, or proceed without."
        elif unreadable := self._unreadable_layers():
            # A layer nobody could open is not a layer that held nothing. Saying
            # "nothing is saved" here is the same slander as calling an unreadable
            # store empty, one call further out.
            status = "empty-unreadable-layer"
            verdict = (
                "no memories matched, and that is not evidence there are none: "
                + ", ".join(str(root) for root in unreadable)
                + " could not be read."
            )
        else:
            status = "empty-nothing-saved"
            verdict = "no memories to search: nothing is saved in any layer bound here."
        diagnosis = self._binding_diagnosis()
        return status, (f"{verdict} {diagnosis}" if diagnosis else verdict)

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
