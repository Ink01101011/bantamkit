"""Memory correctness layer: the agent never writes files directly — only these ops."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from bantamkit.client import BantamError

VALID_TYPES = {"user", "feedback", "project", "reference"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DUPLICATE_JACCARD = 0.5


class MemoryValidationError(BantamError):
    pass


class MemoryBudgetExceeded(BantamError):
    pass


@dataclass
class Fact:
    name: str
    description: str
    type: str
    body: str
    links: list[str]
    last_recalled: str | None
    # ISO date the fact first landed. `None` only on a Fact built in memory before its
    # first write; every Fact read off disk carries one (see `_facts`).
    created: str | None = None


@dataclass
class SaveResult:
    status: str  # "saved" | "duplicate"
    name: str
    similar: str | None = None


@dataclass
class ArchivedFact:
    """What one archived fact was, kept after its file has left `facts/`."""

    name: str
    type: str
    description: str
    index_bytes: int
    last_recalled: str | None
    created: str | None


@dataclass
class CompactResult:
    """Everything the caller needs to understand what compaction cost.

    Archiving is a one-way *move*, not a delete: the file is still readable under
    `archive/` and `restore()` brings it back. This carries the description of each
    fact that left so a caller that never looks in `archive/` can still say what it
    lost, and the byte arithmetic so it can see the headroom it bought.
    """

    archived: list[ArchivedFact]
    index_before: int
    index_after: int
    budget: int
    target: int
    reserve: int
    archive_dir: str

    @property
    def names(self) -> list[str]:
        return [fact.name for fact in self.archived]

    @property
    def headroom(self) -> int:
        return self.budget - self.index_after


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mtime_date(path: Path) -> str:
    """Migration for a fact written before `created` existed: use the file's own mtime.

    Every store already on disk — the 20 live facts included — has no `created` in its
    frontmatter, and defaulting those to `""` would make the whole pre-existing store
    maximally stale and evict it first. The filesystem already records when the fact was
    last written, which is exactly the fallback the sort key wants, and it needs no
    migration pass over anyone's store. It is only a fallback: the next write of that
    fact persists the date into the frontmatter and the mtime is never consulted again.
    """
    return date.fromtimestamp(path.stat().st_mtime).isoformat()


class MemoryStore:
    def __init__(
        self,
        root: str | Path,
        index_budget: int = 4096,
        k: int = 3,
        today: Callable[[], str] | None = None,
        create: bool = True,
    ):
        self.root = Path(root)
        self.index_budget = index_budget
        self.k = k
        self._today = today or (lambda: date.today().isoformat())
        self._snapshot: list[Fact] | None = None
        if create:
            self._ensure_dirs()

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Reads inside this scope see the facts as of scope entry; writes stay live.

        Measured cause (RB-P1, seed 2418578173): one assistant turn dispatched
        recall / save / recall, the speculative save updated the ground-truth fact
        between the two reads, and the model answered from its own fabrication.
        Pinning the read set makes a write speculative *for the scope only* — `save`
        still reads and writes live state, so same-name-is-update is untouched, and
        the next scope reads the write.

        Nesting keeps the outermost pin: a scope entered twice is still one turn.
        A store that cannot be read is simply not pinned, so an unreadable store
        still raises out of `recall`, exactly where it always did.
        """
        previous = self._snapshot
        if previous is None:
            try:
                self._snapshot = self._facts()
            except (BantamError, OSError, UnicodeDecodeError):
                self._snapshot = None
        try:
            yield
        finally:
            self._snapshot = previous

    def _ensure_dirs(self) -> None:
        (self.root / "facts").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)

    # ---- ops ----

    def save(
        self, type: str, name: str, description: str, body: str, links: tuple[str, ...] = ()
    ) -> SaveResult:
        self._ensure_dirs()
        if type not in VALID_TYPES:
            raise MemoryValidationError(
                f"invalid type '{type}'; must be one of {sorted(VALID_TYPES)}"
            )
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
        if not (description or "").strip():
            raise MemoryValidationError("description must be a non-empty line")

        new_tokens = _tokens(f"{name} {description}")
        existing = None
        for fact in self._facts():
            if fact.name == name:
                existing = fact
                continue  # same name = update, not duplicate
            if (
                _jaccard(new_tokens, _tokens(f"{fact.name} {fact.description}"))
                >= DUPLICATE_JACCARD
            ):
                return SaveResult(status="duplicate", name=name, similar=fact.name)

        fact = Fact(
            name=name,
            description=description.strip(),
            type=type,
            body=body,
            links=list(links),
            last_recalled=None,
            # An update keeps the date the fact first landed — rewriting a fact is not
            # the same event as creating it, and resetting this would let a re-save
            # launder a stale fact into a fresh one.
            created=existing.created if existing is not None else self._today(),
        )
        path = self._fact_path(name)
        existed = path.read_text() if path.exists() else None
        self._write_fact(fact)
        try:
            self._check_index_budget()
        except MemoryBudgetExceeded:
            if existed is None:
                path.unlink()
            else:
                path.write_text(existed)
            self._rebuild_index()
            raise
        self._rebuild_index()
        return SaveResult(status="saved", name=name)

    def recall(self, query: str, k: int | None = None, stamp: bool = True) -> list[Fact]:
        k = k if k is not None else self.k
        q = _tokens(query)
        scored = []
        for fact in self._snapshot if self._snapshot is not None else self._facts():
            score = len(q & _tokens(f"{fact.name} {fact.description}"))
            if score > 0:
                scored.append((score, fact))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        hits = [fact for _, fact in scored[:k]]
        if stamp:
            for fact in hits:
                self._stamp(fact)
        return hits

    def lint(self) -> None:
        for fact in self._facts():  # raises MemoryValidationError on malformed frontmatter
            if fact.type not in VALID_TYPES:
                raise MemoryValidationError(f"fact '{fact.name}' has invalid type '{fact.type}'")
        self._check_index_budget()

    def compact(self, reserve: int | None = None) -> CompactResult:
        """Archive the stalest facts until the index sits at `budget - reserve` or below.

        Two measured defects live here, and both are about *when* this is reachable.

        `save` rolls the offending fact back before it raises, so by the time a caller
        can act on "run compact()" the index is under budget again. The old loop tested
        `_check_index_budget()` first and broke on the first iteration: at the only
        moment the remedy is ever named, it archived nothing and returned `[]`. On a real
        20-fact store (index 3943, budget 4096) three consecutive over-budget saves each
        got `compact() -> []` and left `archive/` empty. Compacting to a *target below the
        budget* is what makes the remedy true — and compacting to merely-fits would not,
        because the very next save is over again and the caller loops forever.

        The default `reserve` is the largest index line the store currently holds, so the
        headroom bought is exactly "a fact as big as the biggest one you keep will fit" —
        a number that scales with this store's own data instead of a guessed constant. It
        is capped at half the budget: no store surrenders more than half its index to
        headroom however long one description grows. `reserve` is recomputed from the
        survivors, so a second call archives nothing and `compact()` is idempotent.
        """
        facts = self._facts()
        sizes = {fact.name: len(self._index_line(fact).encode()) for fact in facts}
        if reserve is None:
            reserve = max(sizes.values(), default=0)
        reserve = max(0, min(reserve, self.index_budget // 2))
        target = self.index_budget - reserve

        size = sum(sizes.values())
        before = size
        archived: list[ArchivedFact] = []
        for fact in sorted(facts, key=self._staleness_key):
            if size <= target:
                break
            path = self._fact_path(fact.name)
            path.rename(self.root / "archive" / path.name)
            size -= sizes[fact.name]
            archived.append(
                ArchivedFact(
                    name=fact.name,
                    type=fact.type,
                    description=fact.description,
                    index_bytes=sizes[fact.name],
                    last_recalled=fact.last_recalled,
                    created=fact.created,
                )
            )
        self._rebuild_index()
        return CompactResult(
            archived=archived,
            index_before=before,
            index_after=size,
            budget=self.index_budget,
            target=target,
            reserve=reserve,
            archive_dir=str(self.root / "archive"),
        )

    def archived(self) -> list[str]:
        """Names of the facts sitting in `archive/` — everything `compact` moved out."""
        return sorted(path.stem for path in (self.root / "archive").glob("*.md"))

    def restore(self, name: str) -> None:
        """Move an archived fact back into `facts/`; refuse if it would blow the budget.

        Compaction is a move, not a delete, and this is the door back. Symmetrical with
        `save`: an over-budget restore is undone and raises, so a failed restore leaves
        the store exactly as it found it.
        """
        source = self.root / "archive" / f"{name}.md"
        if not source.exists():
            raise MemoryValidationError(
                f"no archived fact '{name}' under {self.root / 'archive'}"
            )
        destination = self._fact_path(name)
        if destination.exists():
            raise MemoryValidationError(
                f"fact '{name}' is already live; refusing to overwrite it from archive"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        try:
            self._check_index_budget()
        except MemoryBudgetExceeded:
            destination.rename(source)
            self._rebuild_index()
            raise
        self._rebuild_index()

    def index_text(self) -> str:
        return "".join(self._index_line(fact) for fact in self._facts())

    # ---- internals ----

    def _fact_path(self, name: str) -> Path:
        return self.root / "facts" / f"{name}.md"

    def _index_line(self, fact: Fact) -> str:
        return f"- [[{fact.name}]] ({fact.type}) — {fact.description}\n"

    def _staleness_key(self, fact: Fact) -> tuple[str, str]:
        """Order by the last evidence anyone wanted this fact — never by its absence.

        `last_recalled` alone conflated two opposite facts: one written seconds ago and
        one nobody has asked for in a year both read as `None`, and `None or ""` sorts
        before every real ISO date, so the *newest* fact was the first evicted (measured:
        three facts stamped 2026-01-05 plus one saved today, one slot to free, archived
        `['zulu-newest']`). Falling back to `created` makes absence of evidence mean
        "as stale as it is old" instead of "maximally stale". Ties break on name only
        after the dates are equal, so the alphabet can no longer decide a live question.
        """
        return (fact.last_recalled or fact.created or "", fact.name)

    def _facts(self) -> list[Fact]:
        facts = []
        for path in sorted((self.root / "facts").glob("*.md")):
            text = path.read_text()
            try:
                _, front, body = text.split("---\n", 2)
                meta = yaml.safe_load(front)
                if not isinstance(meta, dict):
                    raise MemoryValidationError(
                        f"malformed fact file {path.name}: frontmatter is not a mapping"
                    )
                facts.append(
                    Fact(
                        name=meta["name"],
                        description=meta["description"],
                        type=meta["type"],
                        body=body.strip(),
                        links=list(meta.get("links") or []),
                        last_recalled=meta.get("last_recalled"),
                        created=meta.get("created") or _mtime_date(path),
                    )
                )
            except (ValueError, KeyError, yaml.YAMLError) as e:
                raise MemoryValidationError(f"malformed fact file {path.name}: {e}") from e
        return facts

    def _stamp(self, fact: Fact) -> None:
        """Date the recall without ever writing pinned content back.

        Inside `snapshot()` a hit is a pre-scope copy of the file, so writing it
        verbatim would silently revert a `save` made in the same scope — the same
        poisoning, in reverse. The date therefore lands on whatever is on disk now,
        and a fact that is no longer there is left alone rather than resurrected.
        """
        fact.last_recalled = self._today()
        if self._snapshot is None:
            self._write_fact(fact)
            return
        live = next((f for f in self._facts() if f.name == fact.name), None)
        if live is None:
            return
        live.last_recalled = fact.last_recalled
        self._write_fact(live)

    def _write_fact(self, fact: Fact) -> None:
        meta = {
            "name": fact.name,
            "description": fact.description,
            "type": fact.type,
            "created": fact.created,
            "last_recalled": fact.last_recalled,
            "links": fact.links,
        }
        text = (
            "---\n"
            + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
            + "---\n\n"
            + fact.body.strip()
            + "\n"
        )
        path = self._fact_path(fact.name)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text)
        tmp.replace(path)

    def _rebuild_index(self) -> None:
        (self.root / "index.md").write_text(self.index_text())

    def _check_index_budget(self) -> None:
        size = len(self.index_text().encode())
        if size > self.index_budget:
            raise MemoryBudgetExceeded(
                f"memory index is {size} bytes, budget is {self.index_budget}: "
                f"run compact() or tersen descriptions"
            )
