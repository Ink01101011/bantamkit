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

# ---- the precision gate (roadmap #6) ---------------------------------------------
#
# `recall` keeps a fact whose score is at least `min_ratio` of the BEST score in the
# same recall. WHY THIS NUMBER IS 0.0, and what will replace it:
#
# 0.0 IS A DELIBERATE NO-OP, not a tuned value. `score >= 0.0 * best` is true for every
# fact `recall` was ever going to return — the scoring loop keeps only `score > 0` — so
# shipping this gate at its default changes not one recall, not one injected header, and
# not one byte of any reply. That is the whole point. The threshold that would actually
# cut something has to come from `tools/ledger/injection-precision.mjs`, and on the day
# that tool shipped (2026-09-06) it REFUSED to report a rate: 491 injection records, 3 of
# them carrying names+scores+session, 2 distinct sessions, and no control arm, against a
# floor of 100 joinable injections across 5 sessions. There is no retroactive baseline —
# the 488 older records carry `hits` and `bytes` and nothing joinable — so a number chosen
# today would be a number chosen off three rows, shipped as a silent suppressor of memory
# injection. The mechanism lands now; the number lands when that tool answers instead of
# refusing.
#
# WHY A RATIO AND NOT A COUNT. `score` is an unnormalised intersection size,
# `len(_tokens(name + " " + description) & _tokens(query))`, so it scales with how long
# the QUERY is. Measured on the three instrumented records: the same two-fact shape scored
# 2 and 2 on a 452-character prompt, 4 and 4 on a 453-character prompt, and 22 and 21 on a
# 7855-character one. An absolute cut of, say, 5 would gate out both short prompts
# entirely and admit everything on the long one, which is a rule about prompt length
# wearing a relevance costume. Within ONE recall the query is fixed, so dividing by the
# best score in that same recall cancels the length term exactly: those three records
# become (1.0, 1.0), (1.0, 1.0) and (1.0, 0.9545…) — the near-tie reads as a near-tie at
# both prompt lengths. Jaccard was the other candidate and was rejected for the mirror-
# image bias: `len(a & b) / len(a | b)` puts the query's own token count in the
# denominator, so it would gate out LONG prompts instead of short ones.
#
# WHAT THE RATIO DOES NOT FIX, and must be read alongside it: `_tokens` is
# `re.findall(r"[a-z0-9]+", text.lower())`, ASCII-only. A wholly non-Latin prompt tokenises
# to the empty set and scores 0 against every fact, so it never reaches this gate at all —
# it is already an empty recall. This store's operator writes Thai; a threshold tuned on
# English prompts would be tuned on a population that structurally excludes theirs, and
# the first thing a non-zero cut suppresses is memory for the language the tokenizer
# cannot see. That is a documented consequence of the tokenizer, not of this gate, and it
# is a reason the replacement number must come from a control-armed measurement rather
# than from a feel for what "looks relevant".
#
# The number lives HERE and only here. Both runtimes spell it `RECALL_MIN_SCORE_RATIO`
# and hold the same float; `Memory.recall_outcome` and the `UserPromptSubmit` hook that
# calls it inherit it rather than restating it, so the day it changes it changes once per
# runtime and everything downstream moves with it.
RECALL_MIN_SCORE_RATIO = 0.0

# Spelled once because both runtimes raise it verbatim. The offending value is NOT
# interpolated: Python renders `2.0` as `2.0` and JavaScript renders it as `2`, so a
# sentence carrying the number would be a divergence manufactured by float formatting.
_MIN_RATIO_RANGE = "recall min-score ratio must be between 0.0 and 1.0"

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

#: Percent of the index budget that has to be SPENT before the store is called degraded.
#:
#: 90 and not 100 because the useful moment is before the refusal, not after it: at 100%
#: the next `memory_save` has already failed and the operator has already seen the error.
#: An INTEGER percent, compared by cross-multiplication where it is read, so the two
#: runtimes cannot land on opposite sides of the line through a float they rounded
#: differently.
#:
#: AMENDMENT (job46, J46-4). It used to live in `mcpserver.py`, next to the only thing that
#: read it, and that is exactly what `docs/porting.md`'s register item 7 is about: the
#: report warned at THIS line while the remedy it named — `compact` — aimed at a different
#: one, so between the two the command exited 0 having archived nothing. `compact` has to
#: know where the warning is to be able to clear it, and `mcpserver` is above this layer,
#: so the number moved DOWN to the layer both readers can reach. Same name, same value,
#: same integer comparison; `mcpserver` imports it rather than spelling a second 90.
INDEX_PRESSURE_PERCENT = 90


def undegraded_index_ceiling(budget: int) -> int:
    """The largest index size `INDEX_PRESSURE_PERCENT` does NOT call degraded, in bytes.

    Integer arithmetic only, and the identity it holds is
    `size > undegraded_index_ceiling(b)` exactly when `size * 100 >= PERCENT * b` — the
    cross-multiplied comparison `mcpserver._index_pressure_condition` writes. The two
    spellings are pinned against each other by a boundary sweep in
    `tests/test_status_surface.py`, because they are two spellings and a test is the only
    thing that can keep them one line.
    """
    return (INDEX_PRESSURE_PERCENT * budget - 1) // 100


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


# The exact bytes written into a `.bantamkit/.gitignore` the first time such a directory
# is brought into existence (user ruling 2026-09-15, `.shiftwork/notes-job51/P0-probes.md`).
# Both runtimes hold this text byte-for-byte -- a conformance case pins it against this
# literal -- so it is spelled once, here, rather than re-typed at each call site.
BANTAMKIT_GITIGNORE_TEXT = (
    "# Created by bantamkit: this directory is local state. Delete this file to commit it.\n"
    "*\n"
)


def ensure_bantamkit_gitignore(directory: Path, *, created: bool) -> None:
    """Best-effort, idempotent: give `directory` a self-ignoring `.gitignore` if it is
    literally named `.bantamkit` AND `created` says THIS CALLER'S OWN mkdir is what just
    brought it into existence.

    USER RULING #2 (2026-09-15, after J51-8 measured the fallout of the first rule): the
    ignore file is written only when bantamkit itself creates the `.bantamkit` directory.
    An existing `.bantamkit` -- made by an earlier bantamkit, by hand, or checked out from
    git; with or without a `.gitignore` already in it -- is never given one. That is why
    `created` is the caller's job, not this function's: only the caller knows whether
    `.bantamkit` existed immediately before ITS mkdir, because by the time this function
    runs the directory unconditionally exists either way. (Was: written whenever the
    ignore file itself was absent, regardless of whether `.bantamkit` predated the call --
    which meant deleting the file never stuck, and a store a team already commits would
    silently start ignoring new fact files after an upgrade. `P0-probes.md` ruling 4.)

    THE PROPERTY, not the mechanism: whenever a `.bantamkit` directory is brought into
    existence -- by `MemoryStore._ensure_dirs`, or by anything else in this runtime that
    creates one, such as `EventLog._append`'s own `mkdir` when the event log is on and
    the project store was never saved to -- this is the one place that decides whether it
    gets ignored. A second creator that skipped this call, or that got `created` wrong,
    would leave a `.bantamkit` that git can see (or ignore one it should not), which is
    the whole bug this closes.

    THE CREATORS, ENUMERATED (J54-3), because "anything else" is how one got missed: in
    THIS runtime there are exactly two -- `MemoryStore._ensure_dirs` and `EventLog._append`
    -- and both now ask `bantamkit_dir_for` which directory the decision is about, rather
    than assuming the root's parent is it. `runtime-ts` has a THIRD, `hostinstall`'s
    `thisCommand`, where npm creates `~/.bantamkit/mcp` for `--install`; there is no npm
    install path in this runtime (the offline install is Node-only by user ruling), which
    is why that creator has no counterpart here. `docs/porting.md` carries the row.

    NEVER REWRITES. A `.gitignore` that already exists -- whatever its bytes -- is left
    exactly as it is, kept as a second guard even when `created` is `True`: an operator
    who deleted it to commit the directory keeps that decision, and this never diffs its
    own output against what is on disk.

    NEVER RAISES. Failing to write the ignore file must never be why a fact does not get
    saved -- the parent write (`save`, `compact`, an event record) still has to succeed
    exactly as it does today. A missing ignore file is not worth a lost fact, so an
    unwritable filesystem, a permissions error, or the directory disappearing under this
    call are all swallowed the same way `EventLog.record` already swallows its own
    `OSError`.

    NEVER CREATES `directory` ITSELF. `write_text` fails into a missing parent exactly
    like any other `OSError` here, so calling this before `directory` exists is a no-op,
    not a way to bring `.bantamkit` into existence early.
    """
    if directory.name != ".bantamkit" or not created:
        return
    gitignore = directory / ".gitignore"
    if gitignore.exists():
        return
    try:
        gitignore.write_text(BANTAMKIT_GITIGNORE_TEXT, encoding="utf-8")
    except OSError:
        pass


def bantamkit_dir_for(path: Path) -> Path | None:
    """The `.bantamkit` directory a `mkdir(parents=True)` of `path` would create or fill,
    or `None` when there is none: `path` itself if it is named `.bantamkit`, otherwise its
    nearest ancestor that is.

    WHY A WALK AND NOT `path.parent` (J54-3). Every creator has to hand
    `ensure_bantamkit_gitignore` the directory the decision is ABOUT, and `parent` is the
    right answer for exactly one shape of path, `<x>/.bantamkit/memory`. A store rooted AT
    the `.bantamkit` directory (`--store ~/.bantamkit`) or nested deeper under it
    (`<x>/.bantamkit/memory/extra`) creates a `.bantamkit` whose gitignore decision was
    taken about the wrong directory -- so no decision was taken at all, and git could see
    the whole tree. MEASURED, not hypothetical: `~/.bantamkit` on the machine this was
    found on holds an empty `facts/` and `archive/` beside `memory/`, left by a store once
    rooted at it, and no `.gitignore`.

    NEAREST AND NOT OUTERMOST, which is the choice `EventLog._append` already made and this
    function now carries for both creators: under a `<x>/.bantamkit/y/.bantamkit/z` the
    directory a reader would expect to be ignored is the one the store is actually in.

    READ-ONLY. It looks at names, never at the filesystem, so it is equally valid before or
    after the mkdir -- but `created` is answered by checking THIS path's existence BEFORE.
    """
    for candidate in (path, *path.parents):
        if candidate.name == ".bantamkit":
            return candidate
    return None


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
        """Bring the store's directories into existence, or refuse the write that needs them.

        THE PROPERTY: a store that cannot be brought into existence cannot be written to,
        and the refusal names which directory and why. It is a refusal and not a crash
        because the only callers are the two WRITES (`save`, `compact`); every read is
        already defined over an absent directory -- `_facts`' own docstring rules it, "AN
        ABSENT DIRECTORY IS `[]`, NOT AN ERROR" -- which is what makes a lazily-built
        project layer legal at all.

        THE PREDICATE IS THE OUTCOME AND NEVER AN ERRNO, and that is measured rather than
        tidy. One cwd, `/`, gives CPython EROFS(30) at `/.bantamkit` and Node ENOENT(-2) at
        `/.bantamkit/memory/facts`, because Node's recursive mkdir does not pass EROFS
        through and stats the missing path instead; a `chmod 555` directory gives EACCES(13)
        on both; and on Linux `/` is a writable root owned by root, so the same cwd gives
        EACCES there. Three platforms, three numbers, one fact -- the directory could not be
        made -- so the `except` is the whole of `OSError` and the sentence carries no errno.
        A fix keyed on the number would have been green on Linux CI and wrong on the machine
        the bug was reported from.

        THE SENTENCE NAMES `self.root` AND NOTHING DEEPER, for the same reason. The two
        runtimes fail at different components of the same path (`/.bantamkit` against
        `/.bantamkit/memory/facts`) and report different strerrors for it, so a sentence
        carrying the failing leaf, or that strerror, would be a divergence manufactured by
        mkdir's internals. `self.root` is the path the caller named and both sides agree on
        it, which is what lets one conformance case pin this line byte for byte.
        """
        # Checked BEFORE the mkdir, per user ruling #2: this is the one moment that can
        # tell whether `.bantamkit` already existed. After the mkdir it unconditionally
        # exists either way, so the answer has to be captured now or not at all.
        #
        # J54-3: `bantamkit_dir_for`, not `self.root.parent`. The mkdir below is
        # `parents=True`, so it creates every missing component of `self.root` -- a root
        # that IS the `.bantamkit` directory, or one nested deeper under it, brought a
        # `.bantamkit` into existence while the decision was being taken about some other
        # directory, which meant no decision at all.
        bantamkit_dir = bantamkit_dir_for(self.root)
        bantamkit_dir_existed_before = (
            bantamkit_dir is not None and bantamkit_dir.exists()
        )
        try:
            (self.root / "facts").mkdir(parents=True, exist_ok=True)
            (self.root / "archive").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise MemoryValidationError(
                f"memory store could not be created: {self.root}; the directory is not"
                " there and this filesystem would not make it, so nothing was written"
            ) from e
        if bantamkit_dir is not None:
            ensure_bantamkit_gitignore(
                bantamkit_dir, created=not bantamkit_dir_existed_before
            )

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

    def recall(
        self,
        query: str,
        k: int | None = None,
        stamp: bool = True,
        min_ratio: float = RECALL_MIN_SCORE_RATIO,
    ) -> list[Fact]:
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

        `min_ratio` is roadmap #6's precision gate: keep a fact only if its score is at
        least that fraction of the BEST score in this same recall. The default is
        `RECALL_MIN_SCORE_RATIO`, which is 0.0 and gates nothing — see the paragraph at
        that constant for why the number is a no-op today and what has to be measured
        before it stops being one. The comparison is relative to this store's own best
        because that is the only quantity in reach here that cancels query length; a
        layered `Memory` therefore applies the gate once per layer, against each layer's
        own top hit, and never across layers.

        THE RANGE CHECK RUNS BEFORE ANY FILE IS READ. A ratio outside `[0.0, 1.0]` — and
        NaN, which fails the same comparison chain — is a caller's bug, and reporting it
        as "your store has no matches" would send someone to look at their memories for
        a defect that is in the argument.
        """
        if not 0.0 <= min_ratio <= 1.0:
            raise MemoryValidationError(_MIN_RATIO_RANGE)
        k = k if k is not None else self.k
        q = _tokens(query)
        scored = []
        for fact in self._snapshot if self._snapshot is not None else self._facts():
            score = len(q & _tokens(f"{fact.name} {fact.description}"))
            if score > 0:
                scored.append((score, fact))
        if scored:
            # No `if min_ratio > 0` shortcut on purpose: at 0.0 this line still runs and
            # still keeps everything, so "the default gates nothing" is a fact about the
            # arithmetic rather than about a branch that could be edited away.
            floor = min_ratio * max(score for score, _ in scored)
            scored = [pair for pair in scored if pair[0] >= floor]
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

        AMENDMENT (job46, J46-4), and it supersedes the sentence above about where that
        reserve is measured FROM. WAS: `budget - largest index line`. NOW: that same
        largest line plus the headroom `INDEX_PRESSURE_PERCENT` demands, so the target is
        `undegraded_index_ceiling(budget) - largest index line`. THE REASON IS THE THIRD
        DEFECT OF THIS METHOD and it is `docs/porting.md`'s register item 7: the degraded
        report warns at 90% of the budget and names THIS command, while the old target sat
        at `budget - largest line`, so on any store whose biggest line is under a tenth of
        its budget the command the operator was told to run archived nothing and the
        warning stayed up. MEASURED on a read-only copy of this machine's project store
        (101 facts, index.md 21819 bytes of 24000 = 90.91%, largest index line 361 bytes,
        so the old target was 23639 = 98.50%): `compact()` answered `archived=[]` and
        `index-budget-low` was still firing afterwards. The two paragraphs above are why
        the fix is a substitution and not a new number -- "compacting to merely-fits leaves
        the caller looping" is the same argument one line lower down, so the reserve is
        measured from the line the WARNING draws instead of the one the REFUSAL draws.

        WHAT THIS DOES NOT CHANGE, deliberately: the eviction ORDER (`_eviction_key`), the
        half-the-budget cap, and an EXPLICIT `reserve`. A caller that passes one gets the
        arithmetic it always got, byte for byte -- every eviction-order node in
        `tests/test_memory.py` passes one for exactly that reason, and so may any caller
        that needs the old default back.

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
        # SECOND, NOT FIRST, and the order is the paragraph above kept intact: the listing
        # still refuses an unreadable store before anything here moves a file. What this
        # line adds is the other half of the same stance -- this method WRITES (every
        # `replace` below lands in `archive/`, and `_rebuild_index` writes `index.md` into
        # the root whether or not a single fact was archived), so a root that does not
        # exist and cannot be made is refused here, by name, instead of surfacing as a
        # `FileNotFoundError` out of the final write. `exist_ok=True` makes it free for
        # every store that is already there.
        self._ensure_dirs()
        sizes = {fact.name: len(self._index_line(fact).encode()) for fact in facts}
        if reserve is None:
            # The default reserve is measured from the WARNING LINE, not from the budget.
            # One substitution, and it is the whole of `docs/porting.md` item 7: the
            # sentence that names this command fires at `INDEX_PRESSURE_PERCENT`, so a
            # remedy that only reaches `budget - largest line` is a no-op everywhere
            # between them. `undegraded_index_ceiling` is that line; `+ largest line`
            # keeps this method's own promise on the other side of it, unchanged in
            # words: "a fact as big as the biggest one you keep will fit" -- before the
            # index is degraded AGAIN, rather than before it is over budget.
            reserve = (self.index_budget - undegraded_index_ceiling(self.index_budget)) + max(
                sizes.values(), default=0
            )
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

        THE NAME IS CHECKED AGAINST `NAME_RE` BEFORE ANY SYSCALL, matching `archive`'s
        check (`roadmap-toolbox.md` row 8, (z)): this op has built `facts/<name>.md` out
        of whatever it was handed since it was written, and `facts/` is exactly the
        directory a bad name can plant a file in that no other command can name back out.

        THE FORWARD MOVE IS `Path.replace` AND NOT `Path.rename`, for the reason
        `d239480` gives at `compact` and the reason review round 5 applied to `archive`:
        `os.rename` raises `FileExistsError` on Windows over an occupied destination
        where `os.replace` replaces on both platforms, and `runtime-ts` has always
        called `pyReplace` here. THE ROLLBACK STAYS `rename`, on the same terms
        `d239480` left it: it moves back onto the path the forward move just emptied,
        so no state tells the two calls apart there.

        BOTH `_check_index_budget()` AND THE FINAL `_rebuild_index()` NOW SHARE ONE
        `try`. They did not: the last `_rebuild_index()` used to run after this method's
        only `try/except` had already exited clean, so a failure THERE — `index.md`
        being a directory — raised with the fact already moved out of `archive/` and
        into `facts/`, and nothing put it back. Measured at HEAD before this fix, on a
        store with `index.md` replaced by a directory: `facts/` held the restored fact,
        `archive/` was empty, and the promise this docstring opens with did not hold for
        that one shape — `archive`'s mirror of this rollback was already wrapped and
        never had the gap. Found while porting (z), not asked for by it: printing "the
        filesystem refused this; nothing changed" from the CLI would otherwise be a lie
        for exactly this shape.

        THE DESTINATION GUARD ALSO CHECKS `os.path.lexists`, one line below
        `_reachable`'s `Path.exists()`, and this is a SECOND finding from working (z),
        made after `runtime-py` shipped as this job's reference and `runtime-ts` had
        already answered a parity check against it. `_reachable(destination, ...)`
        follows symlinks, so a DANGLING symlink at `facts/<name>.md` reports absent —
        the predicted blind spot — but the state that reaches next on `runtime-py` is
        NOT the move: it is `_facts()`, three lines below, which lists the same
        directory the guard just cleared and calls `read_text()` on that same entry,
        raising a bare `FileNotFoundError` before `source.replace(destination)` is ever
        reached. Measured before this line existed: `restore` on that fixture raised
        `FileNotFoundError`, uncaught by anything keyed on `Memory*`, and the CLI's (y)
        fix dressed it up as "a filesystem error stopped the move" — true about nothing
        having changed, false about a move having been attempted at all. `runtime-ts`
        took the other branch, catching the same state at ITS guard and answering "is
        already live" — also false, of a link that resolves to nothing. Neither
        sentence named what was actually there, so this line does, once, and both
        runtimes now say it the same way: `facts/<name>.md` is occupied by something
        `restore` cannot read as a fact, and that is refused before either the pre-read
        or the move runs, on the same terms `archive`'s own second guard already
        refuses an occupied `archive/<name>.md` — the one difference being that
        `archive`'s occupied-destination guard was never blind to a symlink in the
        first place, because ITS check is on the side `compact` also writes to, and
        this one guards the side `_facts()` reads whole. `archive` is UNCHANGED: its
        `Path.replace` over a dangling symlink still replaces it, on the terms
        `d239480` and review round 5 set, and nothing here touches that path.
        """
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
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
        if os.path.lexists(destination):
            # `_reachable` above already proved `Path.exists()` returned `False` without
            # raising, so this cannot newly surface an EACCES `_reachable` would have
            # caught: what is left is exactly the blind spot named in the docstring, a
            # directory entry `exists()` cannot resolve — a dangling or circular
            # symlink. Caught HERE, before `_facts()`'s pre-read reaches the same entry
            # by a worse door.
            raise MemoryValidationError(
                f"facts/{name}.md already exists but cannot be read as a fact; "
                "refusing to restore over it"
            )
        self._facts()  # parse BEFORE the move, not after it — see the docstring
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `Path.replace`, not `Path.rename`: see "THE FORWARD MOVE" above.
        source.replace(destination)
        try:
            self._check_index_budget()
            self._rebuild_index()
        except Exception:
            destination.rename(source)
            self._rebuild_index()
            raise

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

    def _fact_text(self, fact: Fact) -> str:
        """The exact bytes `_write_fact` would put on disk, without writing them.

        SPLIT OUT OF `_write_fact` AND NOT A SECOND COPY OF IT: `_write_fact` calls this,
        so the serialisation a caller MEASURES and the serialisation the store WRITES
        cannot drift apart. `dream()` is the caller — it reports the byte size of a
        consolidated store before it has written one, and a private renderer of its own
        would be a second frontmatter format to keep equal to this one.
        """
        meta = {
            "name": fact.name,
            "description": fact.description,
            "type": fact.type,
            "created": fact.created,
            "last_recalled": fact.last_recalled,
            "links": fact.links,
        }
        return (
            "---\n"
            + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
            + "---\n\n"
            + fact.body.strip()
            + "\n"
        )

    def _write_fact(self, fact: Fact) -> None:
        text = self._fact_text(fact)
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
