"""Agent-facing memory component: skill in the prompt, correctness in the store."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool
from bantamkit.client import BantamError
from bantamkit.memory.dream import SUPERSEDED_HEADING, DreamResult
from bantamkit.memory.dream import dream as _dream
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
    RECALL_MIN_SCORE_RATIO,
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


@dataclass(frozen=True)
class CompactOutcome:
    """What `compact` DID, beside the sentence it says about it.

    Same seam as `SaveOutcome` and `RecallOutcome`: `status` is read off a decision the
    store already made — whether `CompactResult.archived` is empty — and never off the
    reply. `archived` (**not** deleted, see `MemoryStore.compact`) is the ONLY place the
    count survives as a number, because the reply spells it out in prose and the host
    records only that a `memory_compact` "completed successfully".

    `status` is `archived` or `nothing-archived`. `reply` is the unchanged string
    `compact()` has always returned; nothing reads it.
    """

    reply: str
    status: str
    archived: int
    index_before: int
    index_after: int
    budget: int


@dataclass(frozen=True)
class DreamOutcome:
    """What `dream` DID, beside the sentence it says about it.

    The same seam as `SaveOutcome`, `RecallOutcome` and `CompactOutcome`: `status` is read
    off a decision the pass already made — `DreamResult.applied`, `.over_budget`,
    `.changes` — and never off the reply. `result` carries the whole diff for a caller that
    wants the numbers rather than the prose.

    `status` is one of `consolidated`, `previewed`, `nothing-to-consolidate`,
    `refused-budget`, `no-profile-layer`.
    """

    reply: str
    status: str
    dry_run: bool
    merged: int
    consumed: int
    absolutised: int
    superseded: int
    index_before: int
    index_after: int
    budget: int
    result: DreamResult | None = None


def _profile_store() -> Path:
    """The last layer `layered` appends, named once so other code can recognise it.

    It was spelled inline in `layered` and nowhere else, which is how it came to be
    prescribed as a place to start a project store: nothing that wrote the advice
    could see that the directory it was recommending is also the machine-wide layer.
    """
    return Path.home() / ".bantamkit" / "memory"


def _same_directory(a: Path, b: Path) -> bool:
    """Whether two paths name ONE directory, symlinks and `/var` vs `/private/var` included.

    Realpath, not string equality, and that distinction is measured rather than tidy: on
    macOS the walk up from a cwd under `/var` returns `/private/var/...` while `Path.home()`
    returns `/var/...`, so two spellings of one directory compare unequal as strings. The
    Stop hook already compares the same two roots the same way and for the same reason
    (`tools/hooks/bantamkit-hook.mjs`). When the resolution itself fails, an absolute-path
    comparison is the honest fallback: it can only under-report a match, never invent one.
    """
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except OSError:
        return a.absolute() == b.absolute()


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
        # `create=False`, AND IT IS THE WHOLE OF THE cwd-`/` FIX. This was the last eager
        # layer -- grants and the profile store have always been lazy -- so a cwd that no
        # directory can be created under was a STARTUP CRASH: every GUI MCP host launches
        # its child with cwd `/`, measured live on this machine (`lsof -p <pid> -a -d cwd`
        # on Claude Desktop and all four of its `bantamkit-mcp` children returns `/`), and
        # the client saw only CONNECTION_CLOSED. Refusing at startup with a sentence was the
        # other candidate and it is REFUTED by measurement: it leaves those same four
        # processes dead, which is strictly worse than today. Built lazily, the server
        # starts from `/`, binds `['project', 'profile']`, and answers out of the profile
        # layer. The sentence still exists -- it is what `MemoryStore.save`/`compact` say
        # when a write actually needs the directory (`store._ensure_dirs`).
        #
        # It is legal because every READ is already defined over an absent directory:
        # `recall() -> []`, `archived() -> []`, `index_text() -> ''`. `_facts`' docstring
        # says so outright, and `create=False` is one of the three callers it names.
        #
        # THE PRICE, stated rather than discovered: a bare server start in a perfectly good
        # cwd no longer scatters `.bantamkit/memory/{facts,archive}` there before anything
        # is saved. That moves TOWARD a stance this file already holds -- see the binding
        # comment below, and `mcpserver.main`'s bare-TTY guard.
        self.store = MemoryStore(store, index_budget=index_budget, k=k, create=False)
        self.k = k
        self._layers: list[tuple[str, MemoryStore, bool]] = [("project", self.store, True)]
        self._show_layers = False
        # How this store came to be the store, captured once. It is still captured here and
        # not re-derived later, but the reason has changed with the line above and the old
        # one is recorded rather than deleted: it WAS that `MemoryStore(create=True)` had
        # already made the directory, so a store that was only DESIGNATED a moment ago was
        # indistinguishable on disk from one that was found empty. That complaint is now
        # discharged -- nothing is created -- and the binding is kept because it also
        # carries WHY this path (`origin`, `searched_from`), which no amount of looking at
        # the disk recovers. `None` means the caller named the path outright --
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
        anything — and `recall` cannot recover either fact afterwards.

        AMENDMENT 2026-09-12 (job48, J48-1), correcting the reason the clause above used
        to give and not the clause itself. WAS: "because constructing the store creates
        the directory." NOW that is false -- the project layer is built `create=False`
        (see `__init__`) and constructing it creates nothing. The binding is still the
        only carrier of WHY, because `origin` and `searched_from` were never on the disk
        to begin with; what the disk has stopped being able to answer is merely "was this
        empty or brand new", which it now answers correctly for the first time.
        """
        binding = resolve_project_store(start)
        project_root = binding.path
        mem = cls(project_root, k=k, index_budget=index_budget, binding=binding)
        mem._show_layers = True
        for grant in load_grants(project_root):
            mem._layers.append(
                (f"extra:{_layer_label(grant)}", MemoryStore(grant, k=k, create=False), False)
            )
        # ONE DIRECTORY IS ONE LAYER. The walk above starts at the cwd and climbs, so a
        # session with no `.bantamkit` anywhere above it resolves `~/.bantamkit/memory` —
        # the profile store — as its PROJECT store. Binding that directory a second time
        # gave `dream` the same store twice: every fact collided with itself, was merged
        # into itself, and the "profile copy" that was archived was the same file. It
        # archived 20 of 20 of the user's real facts on 2026-09-10. Such a session has one
        # layer, and `dream_outcome` already has a true thing to say about that.
        profile_root = _profile_store()
        if not _same_directory(profile_root, project_root):
            mem._layers.append(("profile", MemoryStore(profile_root, k=k, create=False), False))
        return mem

    def setup(self, agent: Agent) -> None:
        agent.register_tool(ToolDef(tool=load_tool("memory_save"), handler=self.save))
        agent.register_tool(ToolDef(tool=load_tool("memory_recall"), handler=self.recall))
        # Bound here so the refused-budget reply below is TRUE on this surface too: it
        # tells the model to call `memory_compact`, and until 2026-08-28 the eval agent
        # had no such tool (`memory_compact.json` claimed `mcp` alone).
        agent.register_tool(ToolDef(tool=load_tool("memory_compact"), handler=self.compact))
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
            # MODEL, and since job42 the model HAS a compaction tool — `memory_compact`
            # (`docs/memory.md`: the user ruled compaction automatic on 2026-08-24; the
            # hook covers the 90 % band, the tool covers this refusal) — so the last
            # sentence names it. Everything before that sentence is byte-identical to
            # what it was when compaction was operator-only.
            return SaveOutcome(
                reply=(
                    f"error: {e}. Nothing was saved and retrying will not help — shorten "
                    f"the description, or save under the name of an existing memory to "
                    f"replace it. Or call `memory_compact` to archive the stalest facts "
                    f"and free room — nothing is deleted."
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

    def recall(
        self,
        query: str,
        k: int | None = None,
        min_ratio: float = RECALL_MIN_SCORE_RATIO,
    ) -> str:
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
        return self.recall_outcome(query, k, min_ratio).reply

    def recall_outcome(
        self,
        query: str,
        k: int | None = None,
        min_ratio: float = RECALL_MIN_SCORE_RATIO,
        *,
        stamp: bool = True,
    ) -> RecallOutcome:
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

        `min_ratio` (roadmap #6) rides through to every layer's `MemoryStore.recall`
        unchanged, so the gate is measured against EACH LAYER's own best score and never
        across layers: a profile fact does not have to out-score the project store's top
        hit to be admitted, because the two stores are answering as two stores. Its
        default is `RECALL_MIN_SCORE_RATIO` = 0.0, which keeps every fact `recall` was
        going to return, and nothing on the tool path passes anything else today. A ratio
        outside `[0.0, 1.0]` raises out of the FIRST layer, which is the writable project
        store, so it surfaces as the error it is rather than as an `unreadable` count —
        the read-only-layer `except` below would otherwise file a caller's bad argument as
        a corrupt grant.

        `stamp` (job64, J64-1) is whether a hit in the WRITABLE layer gets its
        `last_recalled` dated. It defaults to True, which is what every explicit recall —
        the `memory_recall` tool, the memory CLI, `Memory.recall` — has always done, and
        those callers do not pass it. The one caller that passes False is the hook's
        `UserPromptSubmit` arm: an automatic injection is not the model asking for a fact,
        and dating it as one was measured (2026-09-25) to stamp 25 of 42 facts in one
        store as "recalled today", so every rule keyed on `last_recalled` — compaction's
        stalest-first, SessionStart's drop rule — was reading injection traffic instead of
        model demand. Read-only layers are never stamped whatever this says.
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
                facts = store.recall(query, budget, stamp=writable and stamp, min_ratio=min_ratio)
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
            # AMENDED 2026-09-12 (job48, J48-1) because the sentence became FALSE, not
            # because it read badly. WAS: "No memory store existed at or above <from>, so
            # the empty <root> was created for this session." Under a lazily-built project
            # layer nothing is created -- the path is designated and stays absent until a
            # save needs it -- so the old sentence told an operator to go look for a
            # directory that is not there. The new one borrows the pin's own closing
            # clause, "nothing was created", because it is the same claim about the same
            # thing, and it reuses the binding's existing `designated` vocabulary rather
            # than minting a word for it. The remedy that follows -- "otherwise save a
            # memory to start this one" -- is now literally true: the save is what brings
            # the directory into existence.
            where = (
                f"No memory store existed at or above {binding.searched_from}, so {root} "
                f"was designated for this session; nothing was created there."
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
        return self.compact_outcome(reserve).reply

    def compact_outcome(self, reserve: int | None = None) -> CompactOutcome:
        """`compact`, with the decision it took carried beside the sentence it wrote.

        `self.store` is the writable project layer and nothing else: `layered` appends
        grants and the profile store to `_layers` only, never to `self.store`, so this
        cannot reach either (`test_memory_compact_tool.py` pins a profile fact through
        a compaction). The reply is byte-for-byte what `compact` has always returned.
        """
        result = self.store.compact(reserve)
        if not result.archived:
            reply = (
                f"nothing archived: the index is {result.index_after} bytes against a "
                f"{result.budget}-byte budget, already at or under the "
                f"{result.target}-byte compaction target."
            )
            status = "nothing-archived"
        else:
            lost = "\n".join(
                f"- {fact.name} ({fact.type}) — {fact.description}" for fact in result.archived
            )
            reply = (
                f"archived {len(result.archived)} memories; the index went from "
                f"{result.index_before} to {result.index_after} bytes against a "
                f"{result.budget}-byte budget, leaving {result.headroom} bytes of headroom. "
                f"These moved to {result.archive_dir} and are NOT deleted — they can be "
                f"restored by name:\n{lost}"
            )
            status = "archived"
        return CompactOutcome(
            reply=reply,
            status=status,
            archived=len(result.archived),
            index_before=result.index_before,
            index_after=result.index_after,
            budget=result.budget,
        )

    def dream(self, dry_run: bool = True) -> str:
        """Consolidate what the project and profile layers hold under the same name."""
        return self.dream_outcome(dry_run).reply

    def dream_outcome(self, dry_run: bool = True) -> DreamOutcome:
        """`dream`, with the decision it took carried beside the sentence it wrote.

        ONLY THE PROFILE LAYER IS CONSUMED. `_layers` also carries read-only GRANTS, and a
        grant is another operator's store: consolidating a fact out of one is not this
        person's move to make, so `dream` never looks at them. The label is matched exactly
        (`profile`), never by prefix, because a grant is labelled `extra:<name>` and a
        prefix match on a directory called `profile-something` would reach one.

        A `Memory` constructed directly — not through `layered` — has no profile layer at
        all, and that is `no-profile-layer` rather than an error: there is nothing to
        consolidate ACROSS when only one layer is bound.

        `dry_run` DEFAULTS TO TRUE. This is the only op in this component that writes into
        the user's home directory, and it is the only one whose effect is machine-wide: a
        fact archived out of the profile store stops answering for every other project on
        this machine that has no store of its own. A destructive consolidation nobody can
        preview is not shippable, so the safe call is the short one.
        """
        profile = next((store for label, store, _ in self._layers if label == "profile"), None)
        if profile is None:
            return DreamOutcome(
                reply=(
                    "nothing to consolidate: no profile layer is bound, so the project "
                    f"store {self.store.root} is the only layer there is."
                ),
                status="no-profile-layer",
                dry_run=dry_run,
                merged=0,
                consumed=0,
                absolutised=0,
                superseded=0,
                index_before=0,
                index_after=0,
                budget=self.store.index_budget,
            )
        result = _dream(self.store, profile, dry_run)
        if result.over_budget:
            status = "refused-budget"
        elif not result.changes:
            status = "nothing-to-consolidate"
        elif result.applied:
            status = "consolidated"
        else:
            status = "previewed"
        return DreamOutcome(
            reply=self._dream_reply(status, result),
            status=status,
            dry_run=result.dry_run,
            merged=len(result.merged),
            consumed=len(result.consumed),
            absolutised=len(result.absolutised),
            superseded=len(result.superseded),
            index_before=result.index_before,
            index_after=result.index_after,
            budget=result.budget,
            result=result,
        )

    @staticmethod
    def _dream_reply(status: str, result: DreamResult) -> str:
        """The whole diff as prose: what merged, what was dated, what moved, what it cost.

        THE HONESTY SENTENCE AT THE END IS NOT DECORATION. Row 5 was planned as a token
        saving and J45-1 measured that it is not one: the profile store has no `index.md`
        on disk, its index is derived at read time, and nothing loads it into a prompt — so
        deduplicating it frees approximately zero prompt bytes. The value is that one
        ruling now has one copy instead of two that can disagree, and the reply says which
        of those two things the operator just bought.
        """
        lines: list[str] = []
        if status == "nothing-to-consolidate":
            lines.append(
                f"nothing to consolidate: {result.project_root} and {result.profile_root} "
                f"hold no fact under the same name, and no project fact carries a relative "
                f"date this pass will resolve."
            )
        else:
            identical = sum(1 for merge in result.merged if merge.kind == "identical")
            diverged = len(result.merged) - identical
            verb = {
                "consolidated": "consolidated",
                "previewed": "would consolidate",
                "refused-budget": "would consolidate",
            }[status]
            lines.append(
                f"{verb} {len(result.merged)} cross-layer name collision(s) — {identical} "
                f"byte-identical, {diverged} diverged and unioned — and rewrote "
                f"{len(result.rewritten)} project fact(s). The survivor stays in the "
                f"project layer; the profile copy moves to {result.archive_dir} and is NOT "
                f"deleted: restore it by name."
            )
        for merge in result.merged:
            lines.append(
                f"- {merge.name} ({merge.kind}, name+description similarity "
                f"{merge.jaccard:.3f}) — body {merge.body_before} -> {merge.body_after} "
                f"bytes, {merge.blocks_added} block(s) kept from the {merge.consumed_layer} "
                f"copy, survivor in {merge.survivor_layer}"
            )
        for record in result.superseded:
            lines.append(
                f"- superseded '{record.subject}': the {record.lost_layer} copy "
                f"({record.lost_date}) lost to the {record.kept_layer} copy "
                f"({record.kept_date}); the older claim is kept verbatim under "
                f"'{SUPERSEDED_HEADING}'"
            )
        for hit in result.absolutised:
            lines.append(
                f"- dated {hit.name} ({hit.layer}): '{hit.term}' -> {hit.resolved}, "
                f"resolved against that fact's own mtime {hit.basis}, not today"
            )
        for hit in result.unresolved:
            lines.append(
                f"- left alone in {hit.name} ({hit.layer}): '{hit.term}' — no exact day "
                f"follows from an mtime, so nothing was substituted"
            )
        for name, reason in result.refused:
            lines.append(f"- refused {name}: {reason}")
        for pair in result.similar_unmerged:
            lines.append(
                f"- similar but NOT merged: {pair.project_name} (project) and "
                f"{pair.profile_name} (profile) score {pair.jaccard:.3f}; this pass merges "
                f"on name equality only, so nothing was done about it"
            )
        lines.append(
            f"project index {result.index_before} -> {result.index_after} bytes against a "
            f"{result.budget}-byte budget; the profile index (derived, no file on disk) "
            f"{result.profile_index_before} -> {result.profile_index_after}; fact bytes "
            f"across both layers {result.fact_bytes_before} -> {result.fact_bytes_after}."
        )
        if status == "refused-budget":
            lines.append(
                f"NOTHING WAS WRITTEN: the merged index would be {result.index_after} bytes "
                f"against a {result.budget}-byte budget. Call `memory_compact` to archive "
                f"the stalest facts, then run this again."
            )
        elif result.dry_run:
            lines.append(
                "DRY RUN: nothing was written. Re-run with dry_run false to apply it."
            )
        lines.append(
            "This is a correctness pass, not a token saving: the profile index is derived "
            "at read time and is not loaded from a file, so consolidating it frees "
            "approximately no prompt bytes. What it buys is one copy of a ruling instead "
            "of two that can diverge."
        )
        return "\n".join(lines)

    # Back-compat aliases: the component's API predates the public names.
    _save = save
    _recall = recall

    def _format(self, label: str, fact: Fact) -> str:
        tag = f"[{label}] " if self._show_layers else ""
        return f"{tag}[{fact.name}] ({fact.type}) {fact.description}\n{fact.body}"
