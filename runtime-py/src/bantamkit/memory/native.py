"""Claude Code's auto-memory directory as a read-only recall layer, tagged `[native]` (#199).

User ruling 2026-10-15 ("A + B"): J68-0 measured that 35 of the 48 facts agents actually used
live only in the host's auto-memory, `<dir>/*.md`, which recall never read. This layer reads
it. It joins `Memory.recall_outcome`'s pooled candidates AFTER every bantamkit layer, so a tie
goes to bantamkit (`layer_order`), and it is READ-ONLY in every sense the storage spec's tier 3
asks (#204, S2): nothing is ever written into the directory -- no stamp, no read-repair, no
save, no compaction, no dream -- and a directory that is not there is a layer holding nothing,
silently. Its hits are recorded in the usage ledger by name like any other hit; that ledger
lives under `~/.bantamkit`, never here.

WHERE THE DIRECTORY COMES FROM is never computed here (RULING Q1.2): the caller hands in the
directory `hookadapter._resolve_native_memory` found -- the hook with all three branches, the
MCP server with the first two only (`native_memory_dir`). No slug is ever derived.

FORMAT. Every `*.md` but `MEMORY.md`, read by `divergence.parse_fact`: YAML frontmatter with
`name`, `description`, and a type at `type` or `metadata.type`. A file that does not parse is
SKIPPED and named in `skipped` exactly as a bad fact file is in every other layer, never
fatal. Two files claiming one name keep the first in listing order, as the native hot index
does, and the second is skipped with the index's own `duplicate name` sentence.

THE HOT INDEX ANSWERS (`HotIndex(dir, "native", ...)`, #204), kept under `~/.bantamkit/index`
like every other layer's: the hook scores on it without parsing a fact, and only a hit's file
is read. The files answer only when a hit's file no longer says what the index said.

DEDUPE (`pool(..., shadow=...)`): bantamkit's own native export (`hookadapter._export_to_native`)
writes a copy of bantamkit facts into this directory, so a name some bantamkit layer holds is
dropped from this layer BEFORE it is scored -- the bantamkit fact wins outright, and the copy
counts in no BM25 statistic.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from bantamkit.client import BantamError

from .store import _NOT_ONE_LINE, Fact, MemoryStore, Pool, pool_of, pool_without

#: The label the layer's hits carry: `[native] [name] (type) description`.
NATIVE_LAYER = "native"
#: The host's own index file, which is not a fact.
NATIVE_INDEX = "MEMORY.md"


class NativeStore:
    """A read-only layer over `directory`: the methods `Memory` calls on a layer, and no write."""

    def __init__(self, directory: str | Path):
        self.root = Path(directory)
        self._index: Any = None

    # ------------------------------------------------------------------ the index

    def index(self) -> Any:
        """The native hot index, under `INDEX_DIR_ENV` or `~/.bantamkit/index/`; never here."""
        if self._index is None:
            from bantamkit.storage.hotindex import INDEX_DIR_ENV, HotIndex

            override = os.environ.get(INDEX_DIR_ENV) or None
            self._index = HotIndex(self.root, "native", Path.home(), index_dir=override)
        return self._index

    def _indexed(self) -> Any:
        """The index, refreshed; `None` when the directory is not there (a layer of nothing)."""
        if not self.root.is_dir():
            return None
        idx = self.index()
        idx.refresh("fast")
        return idx

    # ------------------------------------------------------------------ the files

    def _listing(self) -> list[Path]:
        """The host's fact files in code-point order, `MEMORY.md` excepted: the index's listing."""
        try:
            names = sorted(
                e.name
                for e in os.scandir(self.root)
                if e.name.endswith(".md") and e.name != NATIVE_INDEX and e.is_file()
            )
        except (FileNotFoundError, NotADirectoryError):
            return []  # not there is a layer of nothing, silently (#204 S2, tier 3)
        return [self.root / n for n in names]

    def _read(self, path: Path) -> Fact:
        """One host file as a `Fact`; raises the `malformed fact file <path>: ...` sentence.

        The description is read as one line, as `MemoryStore._read_fact` reads its own (#155):
        a header printed from it must not become two lines.
        """
        from .divergence import parse_fact

        stored = parse_fact(path)
        return Fact(
            name=stored.name,
            description=_NOT_ONE_LINE.sub(" ", stored.description),
            type=stored.type,
            body=stored.body,
            links=[],
            last_recalled=None,
            source=path,
        )

    def candidates(
        self, skipped: list[dict[str, str]] | None = None, shadow: Any = frozenset()
    ) -> list[Fact]:
        """Every fact the files hold, in listing order, the shadowed names left out.

        A file that does not parse, and the second file claiming a name, go to `skipped` with
        the sentences the native index records for them, so the files and the index report
        one thing.
        """
        from bantamkit.storage.hotindex import DUPLICATE

        out: list[Fact] = []
        held: dict[str, str] = {}
        for path in self._listing():
            try:
                fact = self._read(path)
            except (BantamError, OSError) as e:
                if skipped is not None:
                    skipped.append({"file": path.name, "reason": str(e)})
                continue
            first = held.get(fact.name)
            if first is not None:
                if skipped is not None:
                    reason = f"{DUPLICATE} '{fact.name}': {first} holds it"
                    skipped.append({"file": path.name, "reason": reason})
                continue
            held[fact.name] = path.name
            if fact.name not in shadow:
                out.append(fact)
        return out

    def count(self) -> int:
        """How many fact files the directory lists; 0 when it is not there."""
        return len(self._listing())

    # ------------------------------------------------------------------ the recall surface

    def pool(
        self,
        q: list[str],
        skipped: list[dict[str, str]] | None = None,
        shadow: Any = frozenset(),
    ) -> Pool:
        """This layer's share of a pooled recall, the `shadow` names taken out before scoring."""
        idx = self._indexed()
        if idx is None:
            return pool_of([], q)
        if skipped is not None:
            skipped.extend(
                {"file": f, "reason": r} for f, r in sorted(idx.skipped.items())
            )
        got = MemoryStore._pool_indexed(idx, q)
        if got is not None:
            return pool_without(got, shadow)
        return pool_of(self.candidates(None, shadow), q)

    def resolve(self, pool: Pool, row: int) -> Fact | None:
        """The fact a row stands for; `None` when its file no longer says what the index said."""
        if pool.facts is not None:
            return pool.facts[row]
        assert pool.files is not None
        name = pool.names[row]
        return self._named(pool.files[row] or f"{name}.md", name)

    def _named(self, file: str, name: str) -> Fact | None:
        try:
            fact = self._read(self.root / file)
        except (BantamError, OSError):
            return None
        return fact if fact.name == name else None

    def lookup(
        self, name: str, stamp: bool = False, skipped: list[dict[str, str]] | None = None
    ) -> Fact | None:
        """The fact named exactly `name`, or `None`. `stamp` is accepted and never writes."""
        idx = self._indexed()
        if idx is None:
            return None
        if skipped is not None:
            skipped.extend(
                {"file": f, "reason": r} for f, r in sorted(idx.skipped.items())
            )
        if name not in idx.names():
            return None
        file = idx.file_of(name)
        hit = None if file is None else self._named(file, name)
        if hit is not None:
            return hit
        return next((f for f in self.candidates() if f.name == name), None)

    def archived_recall(self, query: str, k: int, exclude: Any = ()) -> list[Fact]:
        """The host keeps no archive this layer reads."""
        return []

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Nothing to pin: nothing here is ever written by bantamkit."""
        yield
