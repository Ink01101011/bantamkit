"""Memory correctness layer: the agent never writes files directly — only these ops."""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from bantamkit.client import BantamError

VALID_TYPES = {"user", "feedback", "project", "reference"}
# The types whose worth does NOT decay with time-since-last-recall, and which `compact`
# therefore archives only after every other candidate is exhausted (`_eviction_key`).
# A TUPLE and not a set: this is compared against a value that came out of YAML uncast, and
# `in` on a tuple is `==` per element where `in` on a set hashes and can raise.
DURABLE_TYPES = ("feedback", "user")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DUPLICATE_JACCARD = 0.5

# The index is loaded into the prompt every session, so this is a context bill, not a
# disk limit. It was 4096 and that number was never measured against a real store.
# Measured 2026-08-21 against the live 20-fact project store: index 3943 bytes, median
# index line 199 bytes, so 4096 left 153 bytes of headroom and 19 of the 20 lines were
# individually larger than that. Replaying 25 fresh saves onto a copy of that store at
# 4096 evicted 18 facts and the FIRST save already triggered one — the store was not
# near its budget, it was on a treadmill, archiving a fact for nearly every fact it
# learned. The same 25 saves at 24000 evicted none. 24000 is also what the sibling
# `memory-keeper` store on this machine has defaulted to in production for the same
# always-loaded index (scripts/memctl.py: DEFAULT_BUDGET = 24_000), so this aligns with
# a number that has run rather than inventing a fresh guess. Callers that want the old
# ceiling pass `index_budget=4096`; nothing about the budget mechanism changed.
DEFAULT_INDEX_BUDGET = 24_000

# The second half of the "unreadable" sentence, one per directory this store lists.
# They are separate strings because the two failures do different damage, and an error
# that names the wrong damage sends the reader to the wrong place. Both are spelled
# once, here, so a caller's docstring and the message a caller actually emits cannot
# drift apart.
_FACTS_UNREADABLE = (
    "a store whose facts could not be listed is not a store with no facts, and "
    "answering 'empty' here is what rewrites index.md from nothing"
)
_ARCHIVE_UNREADABLE = (
    "an archive that could not be listed is not an empty archive, and answering "
    "'nothing is archived' here is what makes compaction look like deletion — the "
    "facts compact() moved are still on disk under this path"
)
# The same distinction one syscall down, for `restore`, which stats one named path
# instead of listing (see `archived()` for why). A refused stat is not an absent file,
# and each side of the move needs its own half of the sentence for the same reason the
# two listings above do.
_ARCHIVE_UNREACHABLE = (
    "an archived fact that could not be stat'd is not an archived fact that is not "
    "there, and answering 'no archived fact' here sends the operator looking for a "
    "file that is still on disk under this path"
)
_FACTS_UNREACHABLE = (
    "a destination that could not be stat'd is not a name that is already taken, and "
    "nothing has moved: the fact is still in archive/"
)
# The same two distinctions again for `archive`, which walks the move in the opposite
# direction. They cannot reuse the pair above: each sentence names the side the fact is
# STILL on when the stat is refused, and that side is the other one here.
_FACT_UNREACHABLE = (
    "a fact that could not be stat'd is not a fact that is not there, and answering "
    "'no fact' here sends the operator looking for a file that is still on disk under "
    "this path"
)
_ARCHIVE_DESTINATION_UNREACHABLE = (
    "a destination that could not be stat'd is not a name that is already archived, "
    "and nothing has moved: the fact is still in facts/"
)


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
        index_budget: int = DEFAULT_INDEX_BUDGET,
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

        AN UNREADABLE STORE, at each of the three moments it can become one — the
        `except` below swallows on purpose, and these are what it buys. WAS: all three
        answered from an empty listing without a word. NOW, measured 2026-08-23:

        - ALREADY UNREADABLE AT ENTRY. Nothing is pinned (`_snapshot` stays `None`) and
          `recall` raises out of `_facts` on its own, which is why the raise is
          swallowed here rather than turned into a scope-entry failure: `batch()` opens
          this scope around a whole assistant turn, and failing at the boundary would
          take down a turn whose very first op is going to report the same fault with a
          better sentence attached to the op that wanted it.
        - BROKE INSIDE THE SCOPE. The pin holds and it is the point: `recall(...,
          stamp=False)` still answers from the facts as of entry. `recall()` with the
          default `stamp=True` raises out of `_stamp`, which lists the live store —
          AFTER the hits were computed, so the answer is discarded. That is the one
          non-obvious outcome in this whole scope and it is pinned by
          `test_a_recall_pinned_before_the_store_broke_answers_but_never_dates_it`; the
          raise is kept because a store that stops being readable mid-turn is news, and
          no fact is left half-dated (`_stamp` lists before it writes).
        - REPAIRED INSIDE THE SCOPE. Entry pinned nothing, so reads go live and see the
          repair. A scope that pinned nothing has nothing to protect.
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
        # THE FIRST OF TWO READS, AND THE ONE THAT MAKES THIS OP SAFE. WAS: a blind
        # listing made this check pass vacuously and the save went on to have
        # `_rebuild_index` rewrite `index.md` from the same nothing. NOW: an unreadable
        # store raises `MemoryValidationError` from here, before `_write_fact` — so the
        # save fails whole instead of half-way, and there is no state to roll back.
        # Nothing below this line runs. Measured, not assumed:
        # `test_a_listing_that_fails_stops_save_before_it_writes_anything`.
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
        existed = path.read_text(encoding="utf-8") if path.exists() else None
        self._write_fact(fact)
        try:
            self._check_index_budget()
        except MemoryBudgetExceeded:
            if existed is None:
                path.unlink()
            else:
                path.write_text(existed, encoding="utf-8")
            self._rebuild_index()
            raise
        self._rebuild_index()
        return SaveResult(status="saved", name=name)

    def recall(self, query: str, k: int | None = None, stamp: bool = True) -> list[Fact]:
        """Top-`k` facts whose name+description share tokens with `query`.

        WAS: an unreadable store scored zero facts and returned `[]` — the same answer
        as a real miss, and `component.Memory` turned it into "no memories matched. Try
        different words", telling a person to rephrase a question at a filing cabinet
        nobody could open. NOW: `_facts` raises `MemoryValidationError` and this returns
        nothing at all.

        This is the caller that matters most to a person, so the two halves have to
        compose into one sentence rather than two. They do, and by two different
        routes, both measured 2026-08-23:

        - The PROJECT layer is writable, so `Memory.recall` re-raises this deliberately
          ("the project layer failing is a real error") and the person sees this
          message, which names the path and the OS reason. `Memory.save` catches the
          same error and returns it as `error: ...` text. Neither one now reaches
          `_nothing_to_report`, and neither should: that function's job is to explain an
          EMPTY answer, and there is no answer here to explain.
        - A read-only GRANT or PROFILE layer is caught and skipped by `Memory.recall`,
          and `_nothing_to_report` then names it out loud — "no memories matched, and
          that is not evidence there are none: <root> could not be read." Verified end
          to end against a grant at 0o311.

        One shape still composes wrongly and it is not this layer's to fix: a `facts/`
        that is a DANGLING SYMLINK raises here but counts 0 in `layers.count_facts`, so
        a grant in that state is skipped by `recall` and then described by
        `_nothing_to_report` as "nothing is saved in any layer bound here". Deferred to
        the binding layer with the failing node that proves it —
        `test_memory_layers.py::test_a_dangling_facts_symlink_is_unreadable_to_both_layers`.
        """
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
        """Every fact parses and carries a valid type, and the index fits its budget.

        WAS: an unreadable store linted CLEAN — zero facts, zero bytes, nothing to
        object to, and `python -m bantamkit.memory lint` printed `lint: ok — 0 facts`.
        A checker that passes hardest on the store it could not open is the one caller
        here whose old answer was actively dangerous. NOW: `MemoryValidationError`, and
        `_cmd_lint` already routes that to `lint: FAIL — ...` on stderr with exit 1
        (verified by running it), so the operator surface needed no change.
        """
        for fact in self._facts():  # raises MemoryValidationError: unreadable, or malformed
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

        WAS: an unreadable store compacted to `CompactResult(archived=[])`, and the CLI
        printed "nothing to archive — the index is already at or below the target"
        about a store whose size it had failed to measure. NOW: the first statement
        below raises `MemoryValidationError`, before any `rename`, so no fact is moved
        on the strength of a listing that failed. The ordering costs nothing here, the
        same way it costs nothing in `save`: the listing is already the first thing
        this op does, so there is no half-compacted archive to reason about.

        THE MOVE IS `os.replace` AND NOT `os.rename`, and the difference is a platform.
        `Path.rename` silently replaces an existing destination on POSIX and raises
        `FileExistsError` on Windows; `Path.replace` replaces on both. The only state
        that tells them apart is an `archive/<name>.md` that already exists when this
        loop moves the live fact over it -- an earlier compaction's copy of a fact that
        was restored and then went stale again. `restore` cannot produce it, because it
        moves the archived copy OUT, which is why nothing in this repository had reached
        the state until a test went looking for it. `runtime-ts` has always used
        `os.replace` here (`pyReplace` in `src/memory/store.ts`), so before this the two
        runtimes agreed on POSIX and disagreed on Windows.

        THE ORDER IS `_eviction_key`, NOT `_staleness_key`, and the difference is a whole
        class of fact. `feedback` is a standing instruction from the user: it holds until
        revoked, and its worth does not decay with time-since-last-recall, so a purely
        temporal key ranks that class exactly backwards -- the better an instruction is
        internalised the less anything recalls it, the staler it looks, and the sooner it is
        archived out of the index that is loaded at session start. Measured on the real
        project store (index 21698 of a 24000-byte budget): ONE auto-compaction archived 15
        facts and 6 of them were `feedback`, three of those loaded into that same session's
        profile. Every non-feedback candidate is now exhausted first. It is a PRIORITY and
        not a veto -- the budget still wins, so once nothing else is left, feedback is
        archived by staleness and this loop still lands at or below `target`.
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
        for fact in sorted(facts, key=self._eviction_key):
            if size <= target:
                break
            path = self._fact_path(fact.name)
            # `os.replace`, not `os.rename`: the two agree on POSIX and differ on Windows,
            # where `rename` raises `FileExistsError` over an `archive/<name>.md` that is
            # already there. `runtime-ts` uses `pyReplace` here; this is the same call.
            path.replace(self.root / "archive" / path.name)
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
        """Names of the facts sitting in `archive/` — everything `compact` moved out.

        WAS: `glob("*.md")`, which is the same defect W1 removed from the fact read,
        one directory over. NOW: raises `MemoryValidationError` naming `archive/` when
        the directory is there but cannot be listed; still `[]` for a store that has
        never compacted.

        This is the worst place in the module to answer "empty" wrongly, because
        `compact()` has already MOVED the operator's facts here. Measured 2026-08-23
        on a store built for the probe: compact archived `fact-0`, `archive/fact-0.md`
        was on disk, `chmod(archive, 0o311)`, and then `python -m bantamkit.memory
        status` printed `archived: 0` and `... archived` printed `archived facts: 0`,
        both exiting 0. The fact had left `facts/`, and the only tool that says where
        it went said nowhere. An operator reading that has been told their memory was
        deleted; the file was intact the whole time.

        `restore()` is the other half and is deliberately NOT routed through here: it
        stats one named path rather than listing, so an unlistable-but-traversable
        `archive/` still restores (measured 2026-08-23 on a throwaway store: 0o311
        restores fine). Making it list first would refuse a recovery the filesystem was
        still willing to perform, which is the wrong direction for the door back.

        At 0o000 nothing moves, but the raise does NOT come from `rename` as this
        paragraph used to claim — it comes from `Path.exists()` three lines earlier,
        which does not swallow EACCES: measured, `PermissionError: [Errno 13]
        Permission denied: '.../archive/put-away.md'` straight out of `os.stat`. That
        was a raw traceback until W4 gave the stat the same sentence as the listing
        (`_reachable`, `_ARCHIVE_UNREACHABLE`).
        """
        archive = self.root / "archive"
        return sorted(Path(name).stem for name in self._listing(archive, _ARCHIVE_UNREADABLE))

    def archive(self, name: str) -> None:
        """Move one named fact out of `facts/` and into `archive/`.

        The door out, taken deliberately. `compact` already moves facts out, but it
        chooses them by eviction rank and stops as soon as the index fits the budget, so
        it can neither be asked for a PARTICULAR fact nor be used at all when the store
        is already under budget. `restore` has taken a name since it was written; until
        this method the store could bring a named fact back but not send one away, and an
        operator who knew exactly which fact had gone stale had no way to say so.

        THE NAME IS CHECKED AGAINST `NAME_RE` BEFORE ANY SYSCALL. `save` was the only op
        that enforced it, and `save` is not the only op that CREATES a filename: this one
        builds `archive/<name>.md` out of whatever it is handed. Measured 2026-09-05 on
        macOS, before the check existed: `archive ALPHA` against a live `facts/alpha.md`
        exited 0 and left `archive/ALPHA.md` holding a fact whose frontmatter says
        `name: alpha` — the case-insensitive filesystem matched the source, and nothing
        asked the store's own naming rule about the destination it was about to write. On
        a case-sensitive filesystem the same command refuses with "no fact". An archive
        entry the store can never name again is worse than a refusal, and a command that
        means two things on two filesystems is worse than either. `restore` is
        deliberately NOT changed: its name has been unvalidated since it was written, and
        narrowing a shipped command's input is a product decision rather than this fix's.
        Traversal was never the hole — `..`, an absolute path and `sub/alpha` all refused
        identically on both runtimes before this, because `facts/<name>.md` simply is not
        there; the check makes them refuse EARLIER and with the reason named.

        THE PROMISE IS THE SAME ONE `restore` MAKES: a failed archive leaves the store
        exactly as it found it. One of its three guards carries over unchanged in shape
        and two drop out:

        - Both stats are `_reachable`, not `exists()`, for the reason spelled at
          `_ARCHIVE_UNREACHABLE`: a refused stat is not an absent file, and reporting
          "no fact" for an EACCES sends the operator looking for a file that is there.
          The two sentences are their own constants because each names the side the fact
          is still on, and that side is the mirror of restore's.
        - NO `_facts()` PARSE BEFORE THE MOVE, and the asymmetry with `restore` is the
          point rather than an oversight. In restore's direction the pre-read is
          load-bearing: it stops a shape the rollback of the day got wrong. Here it did
          the opposite of its job. The parse reads EVERY fact, so ONE malformed file in
          `facts/` refused every archive in the store INCLUDING ITS OWN — measured
          2026-09-05, `archive bad` against a `facts/bad.md` with no frontmatter answered
          `malformed fact file bad.md: not enough values to unpack (expected 3, got 1)` —
          and no other command removes a fact by name, so the one file the store calls
          broken was the one file no CLI route could get rid of. That is the exact
          opposite of what the paragraph above says this method is for. Without the parse
          the same command SUCCEEDS, and it succeeds for a reason rather than by luck:
          the move takes the bad file out of `facts/` first, so the `_rebuild_index`
          below parses a directory that no longer holds it. A DIFFERENT fact being
          malformed still fails, at that rebuild, and the rollback below puts the moved
          fact back — which is the case the old docstring said the parse was protecting
          and the rollback was already covering.
        - NO budget check. Archiving removes an index line, so the index can only shrink;
          `_check_index_budget` is restore's guard, in restore's direction, and running
          it here would be a check that cannot fail.

        THE MOVE IS `Path.replace` AND NOT `Path.rename`, for the reason `d239480` gives
        at `compact`: `os.rename` replaces an existing destination silently on POSIX and
        raises `FileExistsError` on Windows, `os.replace` replaces on both, and
        `runtime-ts` calls `pyReplace` here. The state that reaches it is NOT one guard 2
        refuses. `_reachable` is `Path.exists()`, which FOLLOWS symlinks, so a DANGLING
        symlink at `archive/<name>.md` is an occupied directory entry the guard cannot
        see: measured 2026-09-05, `os.path.lexists` True and `Path.exists` False, the
        guard passed, and the move landed on top of the link. On POSIX both calls replace
        it; on Windows `rename` would have raised where the port's `replace` does not.
        THE ROLLBACK BELOW IS STILL `rename`, on the terms `d239480` used to leave
        restore's alone: it moves back onto a path the forward move has just emptied, so
        it cannot meet an occupied destination and there is no red to demonstrate for it.

        The rollback stays, keyed on "the rebuild after the move failed" rather than on a
        list of exception types, because the failure it exists for is not a `Memory*`
        error at all. THE ROUTE THAT REACHES IT IS `index.md` BEING A DIRECTORY: the move
        succeeds, `_rebuild_index` writes and raises `IsADirectoryError`, and the fact is
        put back — measured 2026-09-05, `facts/` held `alpha.md` again and `archive/` was
        empty afterwards. WHAT THIS PARAGRAPH USED TO SAY was that the route is "the
        destination in `archive/` being a directory", copied out of restore without
        re-deriving the direction, and that one is unreachable here: guard 2 stats that
        exact path, so a directory at `archive/<name>.md` is refused with "already
        archived" before anything moves (measured the same day, both runtimes).
        """
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
        source = self._fact_path(name)
        if not self._reachable(source, self.root / "facts", _FACT_UNREACHABLE):
            raise MemoryValidationError(
                f"no fact '{name}' under {self.root / 'facts'}"
            )
        destination = self.root / "archive" / f"{name}.md"
        if self._reachable(destination, self.root / "archive", _ARCHIVE_DESTINATION_UNREACHABLE):
            raise MemoryValidationError(
                f"fact '{name}' is already archived; refusing to overwrite it"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `Path.replace`, not `Path.rename`: the two agree on POSIX and differ on Windows,
        # where `rename` raises `FileExistsError` over an occupied `archive/<name>.md`. A
        # dangling symlink there is exactly that and passes the guard above, which follows
        # links. `runtime-ts` calls `pyReplace` here; this is the same call. See `d239480`.
        source.replace(destination)
        try:
            self._rebuild_index()
        except Exception:
            destination.rename(source)
            self._rebuild_index()
            raise

    def restore(self, name: str) -> None:
        """Move an archived fact back into `facts/`; refuse if it would blow the budget.

        Compaction is a move, not a delete, and this is the door back. THE PROMISE IS
        THAT A FAILED RESTORE LEAVES THE STORE EXACTLY AS IT FOUND IT, and it takes
        both halves below to keep it: a read that runs before the `rename`, and a
        rollback for the failures no read before the `rename` can see.

        WAS: nothing read `facts/` until after the rename. W1 put a LISTING there,
        which was not enough, because `_fact_paths` lists and `_check_index_budget`
        parses. Two failures measured on throwaway stores, byte-identical at `533229c`
        and after W1:

        - `facts/` unlistable (0o311, or any scan that fails): W1's read stops it.
        - `facts/broken.md` malformed: the listing passed it, `_check_index_budget`
          raised `MemoryValidationError` AFTER the rename, the rollback below caught
          `MemoryBudgetExceeded` only, and the fact ended up out of `archive/`, in
          `facts/`, with `index.md` never rebuilt.

        NOW the pre-read is `_facts()`, which parses. That refuses no restore that
        would otherwise have succeeded: every parse it can fail on is one
        `_check_index_budget` re-runs three lines later, so with a malformed fact on
        disk the restore fails either way — all that changes is whether it fails before
        the move or after it. `save` is immune to the same shape only by luck of
        ordering (its duplicate check lists before `_write_fact`), and a read that
        makes the move never happen is strictly better than a rollback that has to undo
        one.

        The rollback still has to widen, for the failure no pre-read can reach: when
        the ARCHIVED file is the bad one, it is not a fact until after the `rename`.
        Measured, both shapes: a malformed `archive/put-away.md` raised
        `MemoryValidationError` and an `archive/put-away.md` that is a DIRECTORY raised
        `IsADirectoryError` (POSIX) or `PermissionError` (Windows) — an `OSError`, not
        a `Memory*` error at all. So the clause below is keyed on "the op after the
        move failed", not on a list of exception types: the promise is about the state
        of the store, and it is not a promise about which exception was raised.
        """
        source = self.root / "archive" / f"{name}.md"
        if not self._reachable(source, self.root / "archive", _ARCHIVE_UNREACHABLE):
            raise MemoryValidationError(
                f"no archived fact '{name}' under {self.root / 'archive'}"
            )
        destination = self._fact_path(name)
        if self._reachable(destination, self.root / "facts", _FACTS_UNREACHABLE):
            raise MemoryValidationError(
                f"fact '{name}' is already live; refusing to overwrite it from archive"
            )
        self._facts()  # parse BEFORE the move, not after it — see the docstring
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        try:
            self._check_index_budget()
        except Exception:
            destination.rename(source)
            self._rebuild_index()
            raise
        self._rebuild_index()

    def _reachable(self, path: Path, directory: Path, consequence: str) -> bool:
        """`path.exists()`, except that "I was not allowed to look" is never "it is not there".

        The same invariant as `_listing`, one syscall down. `Path.exists()` swallows
        exactly `pathlib._IGNORED_ERRNOS` — ENOENT, ENOTDIR, EBADF, ELOOP, the answers
        that really do mean "nothing is there" — and re-raises the rest, so EACCES
        arrives as a bare `PermissionError`. Measured before this existed, with
        `archive/` at 0o000: `python -m bantamkit.memory restore` printed a stack trace
        ending in `PermissionError: [Errno 13] Permission denied`, while `_cmd_restore`
        had a sentence ready for `MemoryValidationError` and never saw one. Converted
        here rather than in the CLI because both of `restore`'s probes had it and the
        distinction is the store's to make, not one command's.
        """
        try:
            return path.exists()
        except OSError as e:
            raise self._unreadable(directory, e, consequence, f"stat of {path.name}") from e

    def index_text(self) -> str:
        """The index as it should be on disk, derived from `facts/` and nothing else.

        WAS: `""` for an unreadable store — the input `_rebuild_index` wrote over
        `index.md` and the number `_check_index_budget` measured. NOW:
        `MemoryValidationError`. Everything downstream of this inherits it, which is
        the whole shape of the original defect and is why the raise lives in the read
        rather than in a guard on the write (see `_rebuild_index`).
        """
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

    def _eviction_key(self, fact: Fact) -> tuple[int, str, str]:
        """`compact`'s order: class first, then staleness. Nothing else reads it.

        A `feedback` fact is the user's own correction, and its value does NOT decay with
        time-since-last-recall -- it holds until the user revokes it. The temporal key is
        inverted for exactly that kind of fact, which is why this rank exists and why it
        sorts LAST: an instruction internalised well enough that nothing needs to look it up
        again reads as maximally stale, and archiving moves it out of the index loaded at
        session start, so the user's own correction silently stops being surfaced. That is
        the failure this store exists to prevent, and it was measured happening -- on the
        real project store one auto-compaction archived 15 facts, 6 of them `feedback`.

        `DURABLE_TYPES` AND NOT `"feedback"` ALONE, because that reason is a property of the
        class and not of the word. Review round 4 (M12) read it back against this repo's own
        instructions to the model -- `assets/skills/memory.md`, "A durable fact about the
        user -> `user`" -- and a durable fact does not become less true because nothing
        looked it up. Measured before the change, on four facts one per type where nothing
        has ever been recalled: one slot to free and `compact` archived `ausr`, a
        never-recalled `user` fact, ahead of a `project` note created seven months later.
        The change is MONOTONE -- the protected set only grows -- so no existing store loses
        a fact this rank kept for it before.

        The two protected types share ONE rank rather than being ordered against each other:
        the reason for protecting them is identical, so any order between them would be an
        invention, and a tied rank leaves `_staleness_key` to answer, which is what it is for.

        Within a class the order is `_staleness_key` unchanged, and `sorted` is stable, so a
        tied rank leaves the staleness answer exactly as it was.

        A PRIORITY AND NOT A VETO, and deliberately UNCAPPED. Nothing bounds how much of the
        index the protected class may hold, and that cannot make `compact` fail: once every
        decaying fact is archived the loop keeps going through the protected ones by
        staleness, so the budget still wins. Capping the class instead -- protecting only the
        first N bytes of it -- would archive a fact that today's rank keeps, which is exactly
        what a live user store must not be made to do by a review round. The crowding that a
        cap would address is not live either: on the real store at `952586e` the protected
        classes hold 5634 of 20241 index bytes.

        `in` against a TUPLE and never a `set` or `is`: `type` comes out of YAML with no
        cast, so a hand-edited `type: 2026` really does put a `date` in that field and
        `type: [a, b]` a `list`. `in` on a tuple is `==` per element -- False across types,
        never raising -- where a `set` would hash the value and take `compact`, the operator's
        only way back under budget, down with a `TypeError`. `runtime-ts` spells the same
        comparison as one `pyEqualValue` per entry.
        """
        return (1 if fact.type in DURABLE_TYPES else 0, *self._staleness_key(fact))

    def _listing(self, directory: Path, consequence: str) -> list[str]:
        """The `*.md` names in one of this store's two directories, or a raise. Never a lie.

        `Path.glob` is unusable here and that is the whole reason this function exists:
        it suppresses the `OSError` raised by its own directory scan and yields nothing.
        `_facts` is read TWICE by `save` — once for the duplicate check and once by
        `_rebuild_index` — so a blind listing does not merely under-report, it
        overwrites. Measured 2026-08-23 on a copy of the live 65-fact store with
        `facts/` at 0o311 (writable and traversable, not listable): `save` returned
        `status='saved'`, a 66th fact file landed, and `index.md` went from 13,472
        bytes / 65 lines to 0 / 0 while every fact file sat there unharmed.

        `os.scandir` raises instead. Three decisions, and each one has a reason:

        - THE RAISE IS CONVERTED HERE, not left to callers. This is the one deliberate
          difference from `layers.count_facts`, which propagates the `OSError` for
          `_count_into_binding` to phrase: that function has callers wanting different
          sentences, whereas this store has one reader per directory and `save`,
          `recall`, `lint`, `compact`, `index_text`, `restore` and `archived` all reach
          the disk through here. Converting at the read is what makes "no path out of
          this module reports an unreadable directory as an empty one" a property of
          one place instead of seven.
        - THE COUNTED SET DOES NOT CHANGE. `fnmatch.fnmatch` is the match `pathlib`
          performs — dotfiles and directories included, case-sensitive off Windows and
          case-insensitive on it — and both callers sort exactly as `sorted(glob(...))`
          did. A raise bought by quietly redefining which files are facts would be a
          worse defect than the one it fixes
          (`test_a_readable_store_lists_exactly_what_glob_listed`,
          `test_a_readable_archive_lists_exactly_what_glob_listed`).
        - AN ABSENT DIRECTORY IS `[]`, NOT AN ERROR. That is a first run, and
          `_ensure_dirs`, `create=False` and the designate path all depend on it — for
          `archive/` as much as for `facts/`, because a `create=False` store never makes
          either one and `archived()` has always answered `[]` for a store that has
          simply never compacted.

        The last one is keyed on whether anything is AT the path rather than on the
        errno, and that is the second, smaller difference from `count_facts`. A
        `FileNotFoundError` raised while something is still there is a failed listing
        wearing the absent answer's clothes: POSIX reports ENOTDIR for a scan of a
        regular file, but a Windows directory scan of a non-directory reports the path
        as not found, and a dangling symlink reports ENOENT everywhere. `count_facts`
        answers 0 for a `facts/` that is a regular file — its review measured that as
        its one genuine disagreement with `glob` — while this layer answers
        "unreadable", which is the ruling `test_memory_divergence` already made for a
        file or a dangling symlink where a store belongs, and which makes the answer
        identical on all four CI jobs instead of turning on an errno.

        `consequence` is the caller's half of the sentence, because the two directories
        fail differently and one wording cannot be true of both: an unlistable `facts/`
        is what rewrites `index.md` from nothing, while an unlistable `archive/` is what
        makes a compaction look like a deletion. An error naming the wrong consequence
        sends the reader to the wrong place, which is this module's defect in a new
        shape rather than a fix for it.
        """
        try:
            with os.scandir(directory) as entries:
                return [e.name for e in entries if fnmatch.fnmatch(e.name, "*.md")]
        except FileNotFoundError as e:
            if os.path.lexists(directory):
                raise self._unreadable(directory, e, consequence, "a path exists there") from e
            return []
        except OSError as e:
            raise self._unreadable(directory, e, consequence) from e

    def _fact_paths(self) -> list[Path]:
        """Every `facts/*.md`, listed so that "I could not read it" is never "it is empty".

        The mechanism is `_listing` above, shared with `archived()`; what is local to
        `facts/` is the consequence the error names. This is the read behind `save`,
        `recall`, `lint`, `compact`, `index_text`, `restore`, `_stamp` and `snapshot`,
        and each of those says in its own words what it does when this raises — a
        reader of any one of them should not have to come here to find out.
        """
        facts = self.root / "facts"
        return sorted(facts / name for name in self._listing(facts, _FACTS_UNREADABLE))

    @staticmethod
    def _unreadable(
        directory: Path, error: OSError, consequence: str, detail: str = ""
    ) -> MemoryValidationError:
        """One sentence for a directory that could not be listed, and it never says "empty"."""
        because = f"{error.strerror}{f' ({detail})' if detail else ''}"
        return MemoryValidationError(
            f"memory store is unreadable: {directory}: {because}; {consequence}"
        )

    def _facts(self) -> list[Fact]:
        facts = []
        for path in self._fact_paths():
            text = path.read_text(encoding="utf-8")
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

        WAS: an unreadable store made `self._facts()` below return `[]`, so `live` was
        `None` and every stamp was quietly skipped — a recall inside a scope silently
        stopped recording that it happened. NOW: `MemoryValidationError` out of the
        listing. This is the ONLY caller that can raise after `recall` already has its
        answer, which is why `snapshot()` documents it as its non-obvious case.

        No fact is left half-dated: the listing runs before any `_write_fact`, and it
        raises on the first hit, so a `recall` that raises here has written nothing.
        (`fact.last_recalled` is set on the in-memory `Fact` first and that mutation
        survives on the pinned copy; nothing reads it but `_staleness_key` (through
        `_eviction_key`), and the
        pinned list dies with the scope.)
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
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def _rebuild_index(self) -> None:
        """Write `index.md` from the facts on disk. THE OP THE ORIGINAL DEFECT DESTROYED.

        WAS: `index_text()` answered `""` for a store it could not list and this wrote
        that over a 13,472-byte index. NOW: `index_text()` raises and the `write_text`
        is never reached, so the file on disk is left exactly as it was.

        Note what is deliberately NOT here: a guard refusing to shrink the index. That
        would be a heuristic over a symptom — it cannot tell a wipe from a legitimate
        `compact()`, and it would leave `recall`, `lint` and `archived` still being lied
        to. The read is what was wrong and the read is where it is fixed.
        """
        (self.root / "index.md").write_text(self.index_text(), encoding="utf-8")

    def _check_index_budget(self) -> None:
        """Raise `MemoryBudgetExceeded` if the index would not fit.

        WAS: an unreadable store measured 0 bytes and always fitted. NOW:
        `index_text()` raises `MemoryValidationError` first — a DIFFERENT exception
        from `MemoryBudgetExceeded`, and every caller that rolls back on the budget has
        to decide about it too. `restore` reads ahead of its `rename` AND catches both
        (see its docstring); `save`'s rollback is unaffected, because its listing
        already ran, and failed, before `_write_fact`.

        Note that this is a PARSE, not a listing: `index_text` -> `_facts` reads every
        fact file. A caller that pre-reads with `_fact_paths` has not pre-read what
        this raises on.
        """
        size = len(self.index_text().encode())
        if size > self.index_budget:
            raise MemoryBudgetExceeded(
                f"memory index is {size} bytes, budget is {self.index_budget}: "
                f"run compact() or tersen descriptions"
            )
