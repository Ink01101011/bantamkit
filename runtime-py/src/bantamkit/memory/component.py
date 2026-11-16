"""Agent-facing memory component: skill in the prompt, correctness in the store.

**Generated, not hand-written (#316 G3 U4, J89-6).** Every rule is
`bantamkit/_generated/component.py`, compiled from `runtime-ts/src/memory/component.ts` by
`tools/ts2py` (`docs/porting.md`, *Generated modules*; do not edit it, regenerate it), so the two
runtimes run one source and every sentence an agent reads off its memory is spelled once. The
modules component.ts calls that are not compiled yet are the hand-written ones, reached through
adapter rows (`tools/ts2py/src/adapters.rs`): the
skill layer (`skills.SkillStore`, `skill_roots`, `triggers_enabled`, `SkillStore.fire` over
`replynative.frame` and `skillmine.tokenize_label`), the touch modules (`touch.context`'s via
admission, `recall_file`'s repository half), `assets.load_skill` and `str.lower()`.

This module is the SHIM: the Python surface the hand-written component had, converted at every
crossing (`docs/porting.md`, *The component's shim*):

- `Memory` keeps its snake_case methods and the private names callers reach (`_layers`,
  `_show_layers`, `_pooled`, `_binding_diagnosis`, `_searchable_facts`, `_unreadable_layers`,
  `_walk_ascended`, `_is_profile_store`); `SaveOutcome`, `RecallOutcome`, `CompactOutcome` and
  `DreamOutcome` stay frozen dataclasses of Python values, facts cross as `Fact`s (the store shim's
  `_fact_in` / `_fact_out`), and a store as the `MemoryStore` / `NativeStore` / `SkillStore` a
  Python caller holds (the generated component holds their cores).
- `_layers` is a list a caller may append to, as before: the layer it is handed is bound into the
  generated component's own list.
- `setup()` and `batch()` stay Python-only and hand-written here (J89-6 ruling 1): their only
  consumer is `agent.py`, a Python-only library, and component.ts deliberately omits them. `batch()`
  is built on the stores' `snapshot()`, which pins the cores the generated component reads.
- `RECALL_MIN_SCORE_RATIO` and `_profile_store`, which the eval harness and a test rebind on this
  module, are forwarded to the generated module, as `retrieval`'s weights are.
"""

from __future__ import annotations

import functools
import sys
import types
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from bantamkit._generated import _ts2py_adapters as _adapters
from bantamkit._generated import component as _g
from bantamkit._generated import native as _gnative
from bantamkit._generated._ts2py_runtime import _JsTypeError
from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool
from bantamkit.memory import queries as _queries
from bantamkit.memory import usage as _usage
from bantamkit.memory.dream import DreamResult
from bantamkit.memory.dream import _result as _dream_result
from bantamkit.memory.layers import StoreBinding, _binding_out
from bantamkit.memory.native import NativeStore
from bantamkit.memory.skills import SkillStore
from bantamkit.memory.store import (
    DEFAULT_INDEX_BUDGET,
    MIN_RATIO_RANGE,  # noqa: F401 -- importable from here, as before
    RECALL_MIN_SCORE_RATIO,
    Fact,
    MemoryStore,
    _Core,
    _fact_out,
    _read_map,
)
from bantamkit.memory.usage import UsageLedger

# The generated component builds its layers through these names: the store shim's core (so every
# layer is one a Python caller can be handed back), and a usage ledger configured as the usage
# shim configures one (its fold and rotate thresholds read at call time).
_g.MemoryStore = _Core


def _ledger(home: Any, root: Any, *_: Any) -> Any:
    return _usage.UsageLedger(home, root)._now()


_g.UsageLedger = _ledger

_F = TypeVar("_F", bound=Callable[..., Any])


def _bare(fn: _F) -> _F:
    """A JS `TypeError` the generated component throws reaches a caller as the bare `TypeError`."""

    @functools.wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except _JsTypeError as e:
            raise TypeError(str(e)) from None

    return call  # type: ignore[return-value]


# ------------------------------------------------------------------------- the outcome shapes


@dataclass(frozen=True)
class SaveOutcome:
    """What `save` DECIDED, beside the sentence it says about it.

    THE POINT OF THIS TYPE IS THAT `status` IS NOT DERIVED FROM `reply`. `status` is one of
    `saved`, `duplicate`, `refused-validation`, `refused-budget`, read off a decision the code had
    already made; `reply` is the unchanged string `save()` has always returned. component.ts's
    `SaveOutcome` documents it in full."""

    reply: str
    status: str


@dataclass(frozen=True)
class RecallOutcome:
    """What `recall` DID, beside the facts it formatted: the walk as numbers rather than prose.

    `status` is `answered` or one of `empty-no-match` / `empty-unreadable-layer` /
    `empty-nothing-saved` (or `none` from `recall_file`); `source` the KIND of the layer that
    answered first; `lookup` what the exact-name walk decided; `skipped` every unreadable fact file
    as `{layer, file, reason}`; `headers` each fact's header line built from the parsed fields;
    `via` / `fired` the names a via edge or a skill trigger admitted. component.ts's
    `RecallOutcome` documents every field."""

    reply: str
    status: str
    budget: int
    layers: int
    reached: int
    returned: int
    candidates: int
    source: str | None = None
    unreadable: int = 0
    lookup: str | None = None
    skipped: tuple[dict[str, str], ...] = ()
    headers: tuple[str, ...] = ()
    via: str | None = None
    fired: str | None = None


@dataclass(frozen=True)
class CompactOutcome:
    """What `compact` DID, beside the sentence it says about it: `archived` or `nothing-archived`,
    and the count that survives only here as a number."""

    reply: str
    status: str
    archived: int
    index_before: int
    index_after: int
    budget: int


@dataclass(frozen=True)
class DreamOutcome:
    """What `dream` DID, beside the sentence it says about it: `consolidated`, `previewed`,
    `nothing-to-consolidate`, `refused-budget` or `no-profile-layer`, and the whole diff."""

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


# ------------------------------------------------------------------------- conversions


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _recall_out(d: Any) -> RecallOutcome:
    return RecallOutcome(
        reply=d["reply"],
        status=d["status"],
        budget=int(d["budget"]),
        layers=int(d["layers"]),
        reached=int(d["reached"]),
        returned=int(d["returned"]),
        candidates=int(d["candidates"]),
        source=d["source"],
        unreadable=int(d["unreadable"]),
        lookup=d["lookup"],
        skipped=tuple(dict(s) for s in d["skipped"]),
        headers=tuple(d["headers"]),
        via=d["via"],
        fired=d.get("fired"),
    )


def _store_out(core: Any) -> Any:
    """The store a Python caller holds for a layer the generated component holds."""
    if isinstance(core, _adapters.SkillStore):
        return core._js_skill
    shim = core.__dict__.get("_bk_shim")
    if shim is not None:
        return shim
    if isinstance(core, _gnative.NativeStore):
        # Built by the generated component (`addNative`): its Python face, made once.
        shim = NativeStore.__new__(NativeStore)
        shim.root = Path(core.root)
        shim._core = core
        object.__setattr__(core, "_bk_shim", shim)
        return shim
    raise TypeError(f"not a memory layer: {core!r}")


def _store_in(store: Any) -> Any:
    """The core the generated component holds for a store a Python caller hands it."""
    if isinstance(store, MemoryStore):
        return store._core
    if isinstance(store, NativeStore):
        object.__setattr__(store._core, "_bk_shim", store)
        return store._core
    if isinstance(store, SkillStore):
        return _adapters.SkillStore._of(store)
    raise TypeError(f"not a memory layer: {store!r}")


def _python_layers(layers: Any) -> list[tuple[str, Any, bool]]:
    """Generated `[label, store, writable]` layers as the reference's `(label, store, writable)`."""
    return [(layer[0], _store_out(layer[1]), bool(layer[2])) for layer in layers]


def _binding_in(binding: StoreBinding | None) -> Any:
    if binding is None:
        return None
    searched = binding.searched_from
    return {
        "path": str(binding.path),
        "state": binding.state,
        "factCount": binding.fact_count,
        "searchedFrom": None if searched is None else str(searched),
        "origin": binding.origin,
    }


def _context_in(context: Any) -> Any:
    """A `touch.context.TouchContext` as component.ts reads one (`weights`, `strongWindow`,
    `graph`): the weights as the read-only Map the ranker takes, the graph the hook built."""
    if context is None:
        return None
    return {
        "weights": _read_map(context.weights),
        "strongWindow": list(context.strong_window),
        "graph": context.graph,
    }


def _opt_str(value: Any) -> Any:
    return None if value is None else str(value)


def _list_or_none(values: Any) -> Any:
    return None if values is None else list(values)


class _Layers(list):  # type: ignore[type-arg]
    """`Memory._layers`: `(label, store, writable)` per layer, the reference's list. A caller that
    appends or inserts a layer (the eval harness, the dream and queries tests) binds it into the
    generated component's own list, so the next call reads it."""

    def __init__(self, memory: Memory) -> None:
        super().__init__(_python_layers(memory._core.layers))
        self._memory = memory

    def _sync(self) -> None:
        held = self._memory._core.layers
        held[:] = [[label, _store_in(store), bool(writable)] for label, store, writable in self]

    def append(self, layer: Any) -> None:
        super().append(tuple(layer))
        self._sync()

    def insert(self, index: Any, layer: Any) -> None:
        super().insert(index, tuple(layer))
        self._sync()

    def extend(self, layers: Any) -> None:
        super().extend(tuple(layer) for layer in layers)
        self._sync()


# ------------------------------------------------------------------------- module functions


@_bare
def normalize_name(name: Any) -> Any:
    """The model's spelling adapted to the store's contract: lowercase, `_`/space -> `-`.
    Non-strings are handed on untouched so store validation still speaks."""
    return _g.normalize_name(name)


def _profile_store() -> Path:
    """The last layer `layered` appends, named once so other code can recognise it."""
    return Path(_g.profile_store())


_PROFILE_STORE = _profile_store
_GENERATED_PROFILE_STORE = _g.profile_store


@_bare
def _same_directory(a: Path, b: Path) -> bool:
    """Whether two paths name ONE directory, symlinks and `/var` vs `/private/var` included."""
    return bool(_g._same_directory(str(a), str(b)))


@_bare
def _layer_label(root: Path) -> str:
    """The name a layer answers under: the PROJECT directory, not the store directory."""
    return _g.layer_label(str(root))


# ------------------------------------------------------------------------- the component


class Memory:
    def __init__(
        self,
        store: str | Path,
        k: int = 3,
        index_budget: int = DEFAULT_INDEX_BUDGET,
        binding: StoreBinding | None = None,
    ):
        self._core = _bare(_g.Memory)(
            str(store), {"k": k, "indexBudget": index_budget}, _binding_in(binding)
        )

    @classmethod
    def _of(cls, core: Any) -> Memory:
        mem = cls.__new__(cls)
        mem._core = core
        return mem

    # -- the state callers and tests read and set, held by the generated component

    @property
    def store(self) -> MemoryStore:
        return _store_out(self._core.store)

    @property
    def k(self) -> int:
        return self._core.k

    @k.setter
    def k(self, value: int) -> None:
        self._core.k = value

    @property
    def repaired(self) -> int:
        return int(self._core.repaired)

    @repaired.setter
    def repaired(self, value: int) -> None:
        self._core.repaired = value

    @property
    def _layers(self) -> _Layers:
        return _Layers(self)

    @property
    def _show_layers(self) -> bool:
        return bool(self._core.showLayers)

    @_show_layers.setter
    def _show_layers(self, value: bool) -> None:
        self._core.showLayers = bool(value)

    @property
    def _binding(self) -> StoreBinding | None:
        held = self._core.binding
        return None if held is None else _binding_out(held)

    # -- construction

    @classmethod
    def layered(
        cls,
        start: str | Path | None = None,
        k: int = 3,
        index_budget: int = DEFAULT_INDEX_BUDGET,
        native: str | Path | None = None,
    ) -> Memory:
        """Project store (resolved) + configured read-only grants + profile store + skills +
        `native` (the caller's resolved auto-memory directory, or `None`)."""
        options = {"k": k, "indexBudget": index_budget, "native": _opt_str(native)}
        return cls._of(_bare(_g.Memory.layered)(_opt_str(start), options))

    @classmethod
    def layered_for_eval(
        cls,
        project: str | Path,
        profile: str | Path,
        engine: str = "v2",
        native: str | Path | None = None,
        skills: Sequence[str | Path] | None = None,
    ) -> Memory:
        """A project + profile memory over two COPIES, for `tools/eval/recall/score.py`."""
        if engine != "v2":
            # The reference's refusal, kept at the boundary (component.ts throws a JS Error with
            # the engine JSON-quoted; this Python-only harness API answers as it always did).
            raise ValueError(f"unknown engine: {engine!r}")
        roots = None if skills is None else [str(r) for r in skills]
        core = _bare(_g.Memory.layeredForEval)(
            str(project), str(profile), engine, _opt_str(native), roots
        )
        return cls._of(core)

    # -- Python only: the eval agent's tool table and its batch scope (J89-6 ruling 1)

    def setup(self, agent: Agent) -> None:
        """PYTHON ONLY, hand-written in the shim: `agent.py`'s tool table. component.ts omits it."""
        agent.register_tool(ToolDef(tool=load_tool("memory_save"), handler=self.save))
        agent.register_tool(ToolDef(tool=load_tool("memory_recall"), handler=self.recall))
        # Bound here so the refused-budget reply is TRUE on this surface too: it tells the model to
        # call `memory_compact`, and until 2026-08-28 the eval agent had no such tool.
        agent.register_tool(ToolDef(tool=load_tool("memory_compact"), handler=self.compact))
        agent.add_batch_scope(self.batch)
        agent.add_system(load_skill("memory"))

    @contextmanager
    def batch(self) -> Iterator[None]:
        """One assistant turn's recalls read the store as it was before the turn.

        PYTHON ONLY, hand-written in the shim (component.ts omits it; `agent.py` is its consumer).
        Measured cause (RB-P1, seed 2418578173): the model dispatched recall / save / recall in a
        single turn, the speculative save updated `payments-api-owner` between the two reads, and
        it then answered off its own fabrication. Only writable layers are pinned: a read-only
        grant cannot be written by `save`, and pinning it would move a corrupt-layer error from
        `recall` (where it is caught and the layer skipped) to the batch boundary. The pin is each
        store's `snapshot()`, which holds the core the generated component reads.
        """
        with ExitStack() as stack:
            for _, store, writable in self._layers:
                if writable:
                    stack.enter_context(store.snapshot())
            yield

    # -- save

    def save(
        self,
        type: str,
        name: str,
        description: str,
        body: str,
        links: list[str] | None = None,
        keywords: list[str] | None = None,
        queries: list[str] | None = None,
        outcome: str | None = None,
        status: str | None = None,
    ) -> str:
        """The reply the model reads. Unchanged, and still the tool's advertised return."""
        return self.save_outcome(
            type, name, description, body, links, keywords, queries, outcome=outcome, status=status
        ).reply

    @_bare
    def save_outcome(
        self,
        type: str,
        name: str,
        description: str,
        body: str,
        links: list[str] | None = None,
        keywords: list[str] | None = None,
        queries: list[str] | None = None,
        outcome: str | None = None,
        status: str | None = None,
    ) -> SaveOutcome:
        """`save`, with the branch it took carried out alongside the sentence it wrote."""
        got = self._core.saveOutcome(
            type,
            name,
            description,
            body,
            _list_or_none(links),
            _list_or_none(keywords),
            _list_or_none(queries),
            outcome,
            status,
        )
        return SaveOutcome(reply=got["reply"], status=got["status"])

    # -- recall

    @_bare
    def recall(
        self,
        query: str | None = None,
        k: int | None = None,
        min_ratio: float = RECALL_MIN_SCORE_RATIO,
        include_archived: bool | None = None,
        file: str | None = None,
        outcome: str | None = None,
    ) -> str:
        """`k` is the model asking for *more*, never for less than the store's default."""
        archived = None if include_archived is None else bool(include_archived)
        return self._core.recall(query, k, min_ratio, archived, file, outcome)

    @_bare
    def recall_outcome(
        self,
        query: str,
        k: int | None = None,
        min_ratio: float = RECALL_MIN_SCORE_RATIO,
        *,
        stamp: bool = True,
        include_archived: bool = False,
        context: Any = None,
        head: str | None = None,
        outcome: str | None = None,
    ) -> RecallOutcome:
        """`recall`, carrying the walk it performed as numbers rather than as prose."""
        got = self._core.recallOutcome(
            query,
            k,
            min_ratio,
            bool(stamp),
            bool(include_archived),
            _context_in(context),
            head,
            outcome,
        )
        return _recall_out(got)

    @_bare
    def recall_file(
        self, file: str, k: int | None = None, query: str | None = None
    ) -> RecallOutcome:
        """`memory_recall({file})` (#200, E1-C): the facts linked to one tracked file."""
        return _recall_out(self._core.recallFile(file, k, query))

    def layer_stores(self) -> list[tuple[str, Any, bool]]:
        """`(label, store, writable)` per layer, in precedence order (the touch graph's input)."""
        return _python_layers(self._core.layerStores())

    @_bare
    def _pooled(
        self,
        query: str,
        budget: int,
        min_ratio: float,
        context: Any = None,
        head: str | None = None,
        outcome: str | None = None,
    ) -> tuple[list[tuple[str, Fact]], int, int, int, list[dict[str, str]]]:
        """The scoring walk (#199 D3): every layer's facts pooled, scored ONCE, gated, ranked."""
        got = self._core.pooled(query, budget, min_ratio, _context_in(context), head, outcome)
        picked = [(label, _fact_out(fact)) for label, fact in got["picked"]]
        return (
            picked,
            int(got["reached"]),
            int(got["unreadable"]),
            int(got["candidates"]),
            [dict(s) for s in got["skipped"]],
        )

    @_bare
    def inject_candidates(self, prompt: str, head: str | None = None) -> list[Fact]:
        """What the `UserPromptSubmit` hook would inject for `prompt`, before its byte cap."""
        return [_fact_out(f) for f in self._core.injectCandidates(prompt, head)]

    @_bare
    def rank_all(self, prompt: str, depth: int = 50, head: str | None = None) -> list[Fact]:
        """The ranking past the gate, `depth` deep: what recall@3 is measured on."""
        return [_fact_out(f) for f in self._core.rankAll(prompt, depth, head)]

    # -- usage (#199 D5)

    def usage(self) -> UsageLedger:
        """The usage ledger this memory reads and writes: keyed on the FIRST layer's root."""
        return UsageLedger(Path.home(), self._core.layers[0][1].root)

    @_bare
    def usage_census(self) -> tuple[str, int, int]:
        """`(path, lines, skipped)` of this memory's usage ledger, for `bantamkit_status`."""
        path, lines, skipped = self._core.usageCensus()
        return str(path), int(lines), int(skipped)

    # -- likely-prompt queries (#207 amendment 3)

    @_bare
    def queries_coverage(self) -> tuple[int, int]:
        """`(n, m)`: of the `m` distinct fact names across the readable layers, `n` have queries."""
        n, m = self._core.queriesCoverage()
        return int(n), int(m)

    @_bare
    def queries_missing(self, limit: int = _queries.LIST_LIMIT) -> dict[str, Any]:
        """`memory_queries {}` (Q6): up to `limit` facts with no queries, and how to write them."""
        got = self._core.queriesMissing(limit)
        return {**got, "facts": [dict(f) for f in got["facts"]], "remaining": int(got["remaining"])}

    @_bare
    def queries_write(self, facts: list[Any]) -> dict[str, Any]:
        """`memory_queries {"facts": [...]}` (Q6): checked whole, then one write per sidecar."""
        got = self._core.queriesWrite(facts)
        out = dict(got)
        for key in ("written", "remaining"):
            if key in out:
                out[key] = int(out[key])
        return out

    # -- accounting and the empty answer's diagnosis

    @_bare
    def index_accounting(self) -> tuple[int | None, int]:
        """`(index bytes, budget)` for the writable project store; bytes are `None` unreadable."""
        size, budget = self._core.indexAccounting()
        return _opt_int(size), int(budget)

    @staticmethod
    @_bare
    def _fact_count(root: Path) -> int | None:
        """How many facts a store holds, or `None` when that cannot be established (`mcpserver`'s
        status line reads it through this private name)."""
        return _opt_int(_g.Memory.factCount(str(root)))

    @_bare
    def _unreadable_layers(self) -> list[Path]:
        """Roots of the layers that could not be listed at all — never counted as 0."""
        return [Path(r) for r in self._core.unreadableLayers()]

    @_bare
    def _searchable_facts(self) -> int:
        """Facts the layers actually consulted could have matched, counted live."""
        return int(self._core.searchableFacts())

    @staticmethod
    @_bare
    def _is_profile_store(root: Path) -> bool:
        """Is this store also the machine-wide profile layer `layered` appends?"""
        return bool(_g.Memory.isProfileStore(str(root)))

    @_bare
    def _walk_ascended(self) -> bool:
        """Did the walk actually leave the directory it started in?"""
        return bool(self._core.walkAscended())

    @_bare
    def _binding_diagnosis(self) -> str:
        """Why THIS store, when the project layer is the one that cannot answer."""
        return self._core.bindingDiagnosis()

    # -- compaction and consolidation

    def compact(self, reserve: int | None = None) -> str:
        """Archive the stalest facts until a fact as large as the biggest one kept will fit."""
        return self.compact_outcome(reserve).reply

    @_bare
    def compact_outcome(self, reserve: int | None = None) -> CompactOutcome:
        """`compact`, with the decision it took carried beside the sentence it wrote."""
        got = self._core.compactOutcome(reserve)
        return CompactOutcome(
            reply=got["reply"],
            status=got["status"],
            archived=int(got["archived"]),
            index_before=int(got["indexBefore"]),
            index_after=int(got["indexAfter"]),
            budget=int(got["budget"]),
        )

    # Back-compat aliases: the component's API predates the public names.
    _save = save
    _recall = recall

    def dream(self, dry_run: bool = True) -> str:
        """Consolidate what the project and profile layers hold under the same name."""
        return self.dream_outcome(dry_run).reply

    @_bare
    def dream_outcome(self, dry_run: bool = True) -> DreamOutcome:
        """`dream`, with the decision it took carried beside the sentence it wrote."""
        got = self._core.dreamOutcome(dry_run)
        result = got["result"]
        return DreamOutcome(
            reply=got["reply"],
            status=got["status"],
            dry_run=bool(got["dryRun"]),
            merged=int(got["merged"]),
            consumed=int(got["consumed"]),
            absolutised=int(got["absolutised"]),
            superseded=int(got["superseded"]),
            index_before=int(got["indexBefore"]),
            index_after=int(got["indexAfter"]),
            budget=int(got["budget"]),
            result=None if result is None else _dream_result(result),
        )


# ------------------------------------------------------------------------- rebinding


class _Module(types.ModuleType):
    """`RECALL_MIN_SCORE_RATIO` and `_profile_store` rebound on this module (the eval harness's
    grid, a test's profile) reach the generated component, which reads them at call time."""

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "RECALL_MIN_SCORE_RATIO":
            _g.RECALL_MIN_SCORE_RATIO = value
        elif name == "_profile_store":
            if value is _PROFILE_STORE:
                _g.profile_store = _GENERATED_PROFILE_STORE
            else:
                _g.profile_store = lambda *_: str(value())
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Module
