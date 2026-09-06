"""Bounded consolidation ACROSS the memory layers. Not a within-store deduper.

WHY THIS IS A CROSS-LAYER MERGE AND NOT THE INTRA-STORE DEDUPER ROADMAP ROW 5 ASKED FOR.
J45-1 measured the input population before a line of this was written
(`.shiftwork/notes-job45/J45-1-baseline.md`, re-runnable as
`PYTHONPATH=runtime-py/src .venv/bin/python .shiftwork/notes-job45/J45-1-baseline.py`):

  * **Zero duplicate pairs inside either live store**, at `DUPLICATE_JACCARD` 0.5 AND at
    a 0.35 floor. The highest-scoring pair anywhere in the 87-fact project store is 0.25
    and in the 20-fact profile store 0.216. The cause is mechanical rather than lucky:
    `MemoryStore.save` already REFUSES at 0.5, so a store built only through `save` is
    duplicate-free by construction and always will be. An intra-store deduper would have
    an empty input population on every store this runtime has ever written.
  * **14 name collisions ACROSS the project and profile stores**, 13 of them byte-identical
    facts — 25,962 fact bytes, 62.1 % of everything in the profile store.
  * **Zero cross-layer pairs above 0.35 that do not already share a NAME.** Every duplicate
    is an exact copy; not one is a paraphrase. Name equality finds all 14 before similarity
    is consulted at all.
  * The fourteenth collision has DIVERGED, and its two bodies score **0.333** — BELOW the
    0.5 this runtime calls a duplicate. A merge gated on `DUPLICATE_JACCARD` would find
    the 13 it did not need help finding and miss the only one that is hard.

So the key is the NAME, similarity is carried as a secondary signal that is reported and
never acted on (`DreamResult.similar_unmerged`), and the merge runs between two stores.

WHAT THIS DOES NOT BUY, said here because the docs must not claim otherwise: IT DOES NOT
SAVE MEANINGFUL TOKENS. The profile store has no `index.md` on disk and never has — its
index is derived by `index_text()` at read time and is not loaded from a file, so
deduplicating it frees approximately zero prompt bytes. What it buys is CORRECTNESS: one
copy of a user ruling instead of two that have already diverged, which the fourteenth
fact demonstrably has.

THE DIRECTION IS PROJECT-KEEPS, PROFILE-IS-CONSUMED, and the reason is that the project
layer is the only WRITABLE one. `Memory.save` writes there and nowhere else, so a survivor
parked in the read-only profile layer would be re-forked by the very next `memory_save`
under that name — the merge would undo itself. Archiving the profile copy also leaves
`Memory.recall_outcome`'s `source` at `project` for every one of those names, which is
what J45-1 measured (20/20) and what J45-4 re-asserts.

THE COST OF THAT DIRECTION, stated rather than hidden: the profile store is MACHINE-WIDE.
A fact archived out of it stops answering for every other project on this machine that has
no store of its own. That is why `dry_run` defaults to true and why every consumed name is
listed in the result with the archive directory it moved to — the move is reversible by
`MemoryStore.restore(name)` on the profile store.

TWO TRAPS J45-1 FOUND IN THE LAYOUT ON DISK, both honoured below:

1. **The profile store has no `index.md` and never has.** `_rebuild_if_present` rebuilds an
   index only where one is ALREADY on disk, so no dream creates a file in the user's home
   directory as a side effect of a merge. The rule is stated for BOTH stores rather than
   special-casing `~`, because "never create an index that was not there" is one testable
   sentence where "except under home" is a second thing to keep true.
2. **Archiving changes what a recall can reach.** Only the profile copy is archived, so the
   project layer — the one that answers first and spends the budget — is never made smaller
   by this pass.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from bantamkit.memory.store import (
    DUPLICATE_JACCARD,
    Fact,
    MemoryStore,
    _jaccard,
    _mtime_date,
    _tokens,
)

#: The two layer names this pass knows. A read-only GRANT is deliberately not one of them:
#: a grant is another operator's store, and consuming a fact out of it is not this person's
#: to do. Grants are neither merged nor scanned.
PROJECT_LAYER = "project"
PROFILE_LAYER = "profile"

#: The heading the union writes above claims a contradiction retired. Distinctive on
#: purpose: a body that already contains an ordinary `## superseded` section must not be
#: mistaken for one this pass wrote.
SUPERSEDED_HEADING = "## superseded by a dream merge"

#: Relative terms whose resolution is EXACT DAY ARITHMETIC against a date. Nothing vaguer
#: is in here: `recently` and `last month` are listed in `_UNRESOLVED` below and are
#: reported rather than rewritten, because substituting a day for them would invent a
#: precision the writer did not have. J45-1's warning, in its words: "Any absolutiser has
#: to say which date it substituted and why, or it invents history."
_RELATIVE = re.compile(
    r"\b(?P<simple>today|tonight|yesterday|tomorrow)\b"
    r"|\b(?P<now>right\s+now|just\s+now)\b"
    r"|\b(?P<count>\d+)\s+(?P<unit>days?|weeks?)\s+ago\b",
    re.IGNORECASE,
)

#: Relative terms this pass REFUSES to resolve. They are reported in
#: `DreamResult.unresolved` so a reader knows the body still carries an undated claim, and
#: the text is left exactly as the writer left it.
_UNRESOLVED = re.compile(
    r"\brecently\b"
    r"|\b(?:last|this|next)\s+(?:week|month|year|quarter|night|session|time)\b"
    r"|\b\d+\s+(?:months?|years?)\s+ago\b",
    re.IGNORECASE,
)

#: A date this pass has already stamped. Skipping a match that carries one is what makes
#: absolutisation IDEMPOTENT: a second dream over the same body writes nothing.
_STAMPED = re.compile(r"\s*\(\d{4}-\d{2}-\d{2}\)")

#: Blocks are paragraphs: runs of text separated by a blank line. Line endings are
#: normalised first so a CRLF body blocks identically to an LF one on every platform.
_BLOCK_SPLIT = re.compile(r"\n[ \t]*\n+")

#: A leading markdown bullet or heading marker, stripped before a block is read as a claim.
_BULLET = re.compile(r"^(?:[-*+]\s+|#+\s+)")

#: `Subject: value` on ONE line — the only shape this pass will read as a claim slot, and
#: deliberately narrow. `subject` may not contain a colon (the split would be ambiguous) or
#: a slash (`https://x` is a URL, not a claim), must start with a letter, and is capped at
#: 60 characters. A value beginning `//` is refused for the same reason. The narrowness is
#: the point: a contradiction rule that fires on ordinary prose would supersede claims
#: nobody contradicted, and this pass may never drop what a person wrote.
_SLOT = re.compile(r"^(?P<subject>[^:\n]{1,60}?)\s*:\s*(?P<value>\S.*)$")
_SUBJECT_OK = re.compile(r"^[A-Za-z][A-Za-z0-9 ._'()\[\]-]*$")


@dataclass(frozen=True)
class DateHit:
    """One relative term found in a body, and what — if anything — it resolved to.

    `resolved` is `""` for a term in `_UNRESOLVED`: the term was FOUND and REPORTED and the
    body was not touched. `basis` is always the ISO date the arithmetic ran against, which
    is the fact file's own mtime and never today's date — a fact written in August that
    says "today" means a day in August, and resolving it against the day the dream runs is
    how a consolidation pass invents history.
    """

    name: str
    layer: str
    term: str
    resolved: str
    basis: str


@dataclass(frozen=True)
class Superseded:
    """A claim that lost a contradiction, kept verbatim so nothing is silently dropped."""

    subject: str
    kept: str
    kept_layer: str
    kept_date: str
    lost: str
    lost_layer: str
    lost_date: str


@dataclass(frozen=True)
class DreamMerge:
    """One consolidated name: what it was, what it became, and where each half went."""

    name: str
    kind: str  # "identical" | "diverged"
    jaccard: float
    survivor_layer: str
    consumed_layer: str
    body_before: int
    body_after: int
    blocks_added: int
    superseded: tuple[Superseded, ...]


@dataclass(frozen=True)
class SimilarPair:
    """A cross-layer pair similarity would have merged and NAME EQUALITY DID NOT FIND.

    Reported, never acted on. J45-1 measured this population at ZERO on the live stores —
    every cross-layer duplicate there is an exact copy sharing a name. It is carried so a
    future store that grows a paraphrase is visible rather than silently unmerged, and so
    that the claim "similarity contributes nothing today" is a number a reader can check
    instead of a sentence they have to trust.
    """

    project_name: str
    profile_name: str
    jaccard: float


@dataclass(frozen=True)
class DreamResult:
    """The diff. Everything a caller needs to see what a dream did, or would do.

    `applied` is FALSE for a dry run and for a plan refused by the budget, and it is the
    only field that says whether anything on disk moved. The byte fields are projections
    computed the same way in both modes, so a preview and the run it previews report the
    same arithmetic rather than two numbers a reader has to reconcile.
    """

    applied: bool
    dry_run: bool
    merged: tuple[DreamMerge, ...]
    refused: tuple[tuple[str, str], ...]
    absolutised: tuple[DateHit, ...]
    unresolved: tuple[DateHit, ...]
    similar_unmerged: tuple[SimilarPair, ...]
    consumed: tuple[str, ...]
    rewritten: tuple[str, ...]
    archive_dir: str
    index_before: int
    index_after: int
    budget: int
    profile_index_before: int
    profile_index_after: int
    fact_bytes_before: int
    fact_bytes_after: int
    project_root: str
    profile_root: str

    @property
    def over_budget(self) -> bool:
        """Would the project index not fit after this merge? Then nothing is written."""
        return self.index_after > self.budget

    @property
    def changes(self) -> int:
        """Merges plus rewritten facts — the count that decides `nothing-to-consolidate`."""
        return len(self.merged) + len(self.rewritten)

    @property
    def superseded(self) -> tuple[Superseded, ...]:
        return tuple(record for merge in self.merged for record in merge.superseded)


# ---- the pure algorithm, spelled so `runtime-ts` can reproduce it exactly -------------


def collapse(text: str) -> str:
    """One line, single-spaced. The basis of every comparison key in this module."""
    return re.sub(r"\s+", " ", text).strip()


def block_key(text: str) -> str:
    """The identity of a block for set-union purposes: collapsed whitespace, lowercased.

    Punctuation is deliberately NOT stripped. A rule that ignored it would call two
    sentences the same because one ends in a question mark, and this pass is allowed to
    repeat a claim but never to drop one.
    """
    return collapse(text).lower()


def split_blocks(text: str) -> list[str]:
    """Paragraphs: non-empty runs separated by a blank line, each stripped.

    Line endings are normalised first, so the same body blocks identically whether it was
    written on Windows or on POSIX — the two runtimes must agree on the block list before
    they can agree on the union of two of them.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return [block.strip() for block in _BLOCK_SPLIT.split(normalised) if block.strip()]


def claim_slot(block: str) -> tuple[str, str] | None:
    """`(subject key, value key)` when a block is a single-line `Subject: value`, else None.

    See `_SLOT` for why this is narrow. It exists only so that a genuine CONTRADICTION —
    the same slot given two different values — can be told apart from two claims that are
    merely different, which is the whole of what union already handles.
    """
    if "\n" in block:
        return None
    match = _SLOT.match(_BULLET.sub("", block.strip()))
    if match is None:
        return None
    subject = match.group("subject").strip().strip("*").strip()
    value = match.group("value").strip()
    if not subject or not _SUBJECT_OK.match(subject) or value.startswith("//"):
        return None
    return collapse(subject).lower(), collapse(value).lower()


def _resolve(match: re.Match[str], basis: str) -> str | None:
    """The day this term names, `""` where the arithmetic leaves the calendar, `None` for
    a basis that is not a date at all.

    THE `""` ARM IS A GUARD AND NOT AN OPTIMISATION. `\\d+` has no upper bound, so a body
    a person can legitimately write — `the run took 999999999999 days ago to notice` — used
    to raise `OverflowError` out of `dream()` and take the whole pass, preview included,
    with it. CPython has THREE such refusals and they are three different sentences:

      * `days=1000000000; must have magnitude <= 999999999` — `timedelta`'s own cap;
      * `Python int too large to convert to C int` — past `INT_MAX`, 2147483647, before
        `timedelta` gets to say anything at all;
      * `date value out of range` — a magnitude the cap allows whose RESULT is outside
        `date.min .. date.max`, which on any real mtime is anything at or past the basis's
        own ordinal (739865 days for a 2026-09-06 basis).

    Reproducing three sentences in two runtimes is a surface, and every one of them is a
    crash a user's own memory body can trigger. An unresolvable relative term already has a
    defined home in this pass — reported in `DreamResult.unresolved` with `resolved: ""`,
    and the body left exactly as the writer left it — so an out-of-range one goes there.
    `runtime-ts` guards at the same two boundaries, so neither runtime has a sentence to
    spell and the two agree on WHERE the arithmetic stops as well as on what happens then.
    """
    try:
        basis_date = date.fromisoformat(basis)
    except ValueError:  # pragma: no cover - basis is an mtime, always ISO
        return None
    if match.group("simple"):
        delta = {"today": 0, "tonight": 0, "yesterday": -1, "tomorrow": 1}[
            match.group("simple").lower()
        ]
    elif match.group("now"):
        delta = 0
    else:
        count = int(match.group("count"))
        delta = -count * (7 if match.group("unit").lower().startswith("week") else 1)
    try:
        return (basis_date + timedelta(days=delta)).isoformat()
    except OverflowError:
        return ""


def absolutise(
    body: str, basis: str, name: str, layer: str
) -> tuple[str, list[DateHit], list[DateHit]]:
    """`(body, resolved hits, unresolved hits)` — a relative date annotated with its day.

    THE TERM IS KEPT AND THE DATE IS ADDED: `today` becomes `today (2026-08-27)`. Deleting
    the word would rewrite the sentence a person wrote; appending the day says which date
    was substituted and leaves the reader able to disagree with it. A term already carrying
    a stamp is skipped, which is what makes a second dream over the same body a no-op.

    A term whose arithmetic leaves the calendar (see `_resolve`) is REPORTED as unresolved
    and the body is left alone — the same treatment `recently` and `last month` get, for the
    same reason: this pass may say which day it substituted, or say it could not, and never
    invent one. Those hits come FIRST in the unresolved list, in the order the relative scan
    met them, followed by the `_UNRESOLVED` matches in the order the second scan met them.
    """
    pieces: list[str] = []
    hits: list[DateHit] = []
    out_of_range: list[DateHit] = []
    position = 0
    for match in _RELATIVE.finditer(body):
        if _STAMPED.match(body[match.end() :]):
            continue
        resolved = _resolve(match, basis)
        if resolved is None:  # pragma: no cover - see `_resolve`
            continue
        if not resolved:
            out_of_range.append(
                DateHit(name=name, layer=layer, term=match.group(0), resolved="", basis=basis)
            )
            continue
        pieces.append(body[position : match.end()])
        pieces.append(f" ({resolved})")
        position = match.end()
        hits.append(DateHit(name=name, layer=layer, term=match.group(0), resolved=resolved,
                            basis=basis))
    pieces.append(body[position:])
    unresolved = out_of_range + [
        DateHit(name=name, layer=layer, term=match.group(0), resolved="", basis=basis)
        for match in _UNRESOLVED.finditer(body)
    ]
    return "".join(pieces), hits, unresolved


def merge_descriptions(base: str, other: str) -> str:
    """Both descriptions, `; `-joined, unless they are the same line of text.

    The description is what `recall` SCORES against, so dropping one side's would cost the
    survivor the query vocabulary that half of the pair used to answer. Equality is on the
    collapsed, lowercased key — the same key every other comparison here uses — and nothing
    cleverer: a containment or similarity rule would be a second thing `runtime-ts` has to
    reproduce byte-for-byte, and the index budget already bounds the cost of being literal.
    """
    if block_key(base) == block_key(other):
        return base.strip()
    return f"{base.strip()}; {other.strip()}"


def merge_links(base: list[str], other: list[str]) -> list[str]:
    """Ordered set union, base first, exact string identity. Order is the port's contract."""
    out = list(dict.fromkeys(link for link in base if link))
    for link in other:
        if link and link not in out:
            out.append(link)
    return out


def merge_bodies(
    base_body: str,
    other_body: str,
    base_layer: str,
    other_layer: str,
    base_date: str,
    other_date: str,
) -> tuple[str, int, tuple[Superseded, ...]]:
    """UNION, never a winner. `(body, blocks taken from other, superseded records)`.

    THE ALGORITHM, stated as the contract `runtime-ts` must reproduce exactly:

    1. Split both bodies into blocks (`split_blocks`).
    2. Find CONTRADICTIONS: a `claim_slot` subject present on both sides with two different
       value keys. The side whose FACT FILE has the later mtime wins; a tie goes to `base`,
       which is the writable project layer. The loser is removed from the body sequence and
       recorded in a `Superseded` entry — never dropped.
    3. Emit every surviving BASE block in source order, skipping any whose `block_key` has
       already been emitted.
    4. Emit every surviving OTHER block in source order, skipping any whose `block_key` has
       already been emitted.
    5. If anything was superseded, append one block: `SUPERSEDED_HEADING`, a blank line, and
       one `- from <layer> (<date>): <collapsed text>` line per record, sorted by subject.
    6. Join with a blank line.

    WHY MTIME AND NOT `created` DECIDES A CONTRADICTION. J45-1 measured all three of the
    obvious clocks on the real diverged pair and every one of them picks wrong: newest
    `created` and longest body each pick the profile copy and lose the project copy's
    amended paragraph, project-layer-wins drops ~1.7 kB of the profile copy, and
    `last_recalled` is the same date on both and separates nothing. `created` is
    FIRST-LANDING and the older-created fact there holds the NEWER content, so it is
    actively backwards. The file's mtime is the only clock on disk that records when the
    text was last written, and it is the same clock `absolutise` resolves dates against.

    WHY UNION MAY REPEAT A CLAIM. Two paragraphs that say the same thing in different words
    have different `block_key`s and both survive. That is the deliberate direction of the
    error: a repeated claim is something the user can delete in one edit, and a dropped
    ruling is not recoverable from the merged fact at all.
    """
    base_blocks = split_blocks(base_body)
    other_blocks = split_blocks(other_body)

    base_slots: dict[str, tuple[int, str]] = {}
    for index, block in enumerate(base_blocks):
        slot = claim_slot(block)
        if slot is not None and slot[0] not in base_slots:
            base_slots[slot[0]] = (index, slot[1])
    other_slots: dict[str, tuple[int, str]] = {}
    for index, block in enumerate(other_blocks):
        slot = claim_slot(block)
        if slot is not None and slot[0] not in other_slots:
            other_slots[slot[0]] = (index, slot[1])

    superseded: list[Superseded] = []
    drop_base: set[int] = set()
    drop_other: set[int] = set()
    for subject in sorted(set(base_slots) & set(other_slots)):
        base_index, base_value = base_slots[subject]
        other_index, other_value = other_slots[subject]
        if base_value == other_value:
            continue
        if other_date > base_date:
            drop_base.add(base_index)
            superseded.append(
                Superseded(
                    subject=subject,
                    kept=collapse(other_blocks[other_index]),
                    kept_layer=other_layer,
                    kept_date=other_date,
                    lost=collapse(base_blocks[base_index]),
                    lost_layer=base_layer,
                    lost_date=base_date,
                )
            )
        else:
            drop_other.add(other_index)
            superseded.append(
                Superseded(
                    subject=subject,
                    kept=collapse(base_blocks[base_index]),
                    kept_layer=base_layer,
                    kept_date=base_date,
                    lost=collapse(other_blocks[other_index]),
                    lost_layer=other_layer,
                    lost_date=other_date,
                )
            )

    seen: set[str] = set()
    out: list[str] = []
    for index, block in enumerate(base_blocks):
        if index in drop_base:
            continue
        key = block_key(block)
        if key in seen:
            continue
        seen.add(key)
        out.append(block)
    added = 0
    for index, block in enumerate(other_blocks):
        if index in drop_other:
            continue
        key = block_key(block)
        if key in seen:
            continue
        seen.add(key)
        out.append(block)
        added += 1

    if superseded:
        lines = [SUPERSEDED_HEADING, ""]
        lines += [
            f"- from {record.lost_layer} ({record.lost_date}): {record.lost}"
            for record in superseded
        ]
        out.append("\n".join(lines))
    return "\n\n".join(out), added, tuple(superseded)


# ---- the pass over two stores ---------------------------------------------------------


def _rebuild_if_present(store: MemoryStore) -> None:
    """Rebuild `index.md` ONLY where one is already on disk. Trap 1, in one function.

    The profile store has never had an `index.md`: its index is derived by `index_text()`
    and `_rebuild_index` — the only writer — is never reached, because `Memory.layered`
    mounts that store read-only. A merge that quietly created one would put a new file in
    the user's home directory as a side effect, and that has to be a decision somebody
    makes rather than a consequence of tidying two copies of a fact into one.

    `os.path.lexists` and not `Path.exists()`: an `index.md` that is a dangling symlink is
    an entry that is THERE, and rebuilding through it is the behaviour `save` already has.
    """
    if os.path.lexists(store.root / "index.md"):
        store._rebuild_index()


def _consume(store: MemoryStore, name: str) -> None:
    """Move one fact into this store's `archive/` WITHOUT touching its index.

    `MemoryStore.archive` cannot be used here and the difference is exactly trap 1: it ends
    in `_rebuild_index()` unconditionally, so archiving out of the profile store through it
    would create the `index.md` that store has never had. The move itself is the same call
    `archive` and `compact` make — `Path.replace`, which replaces an occupied destination on
    Windows as well as POSIX, where `Path.rename` raises there and not here.

    The destination is checked by the caller, which refuses the whole pair rather than
    overwriting an earlier archived copy.
    """
    destination = store.root / "archive" / f"{name}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    store._fact_path(name).replace(destination)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # pragma: no cover - the fact was listed a moment ago
        return 0


def dream(
    project: MemoryStore,
    profile: MemoryStore,
    dry_run: bool = True,
) -> DreamResult:
    """Consolidate the facts the two layers hold under the same NAME. Reversible, bounded.

    `dry_run` defaults to TRUE because this pass writes into the user's home directory and
    a destructive consolidation nobody can preview is not shippable. A dry run performs
    every read, every merge and every projection and writes nothing.

    THE BUDGET IS `compact()`'s BUDGET AND NOT A SECOND CAP. The only index this pass can
    grow is the project one, and it can grow it only by the bytes a unioned DESCRIPTION
    adds — every merged name is already a line in that index, so no line is ever added. The
    projected index is measured exactly the way `MemoryStore._check_index_budget` measures
    it, and a plan that would not fit is returned unapplied with `over_budget` set, for the
    caller to report. It is not raised: a preview whose answer is an exception has told the
    operator nothing about the plan they asked to see.

    WRITE ORDER IS SURVIVORS FIRST, CONSUMPTION SECOND, and it is chosen for the direction
    of its failure. If the process dies between the two, the survivor holds everything and
    the profile copy is still live — a duplicate that the next dream consolidates. The
    other order would leave a window in which the profile copy is archived and the union
    has not landed.
    """
    project_facts = project._facts()
    profile_facts = profile._facts()
    by_project = {fact.name: fact for fact in project_facts}
    by_profile = {fact.name: fact for fact in profile_facts}

    planned: dict[str, Fact] = {}
    merged: list[DreamMerge] = []
    refused: list[tuple[str, str]] = []
    hits: list[DateHit] = []
    unresolved: list[DateHit] = []
    consumed: list[str] = []

    for name in sorted(set(by_project) & set(by_profile)):
        here, there = by_project[name], by_profile[name]
        destination = profile.root / "archive" / f"{name}.md"
        if os.path.lexists(destination):
            refused.append(
                (
                    name,
                    f"{destination} already exists; refusing to overwrite an earlier "
                    f"archived copy — restore or remove it and run again",
                )
            )
            continue
        here_date = _mtime_date(project._fact_path(name))
        there_date = _mtime_date(profile._fact_path(name))
        identical = (
            here.body.strip() == there.body.strip()
            and here.description.strip() == there.description.strip()
            and here.type == there.type
            and list(here.links) == list(there.links)
        )
        body, resolved_hits, unresolved_hits = absolutise(here.body, here_date, name,
                                                          PROJECT_LAYER)
        hits += resolved_hits
        unresolved += unresolved_hits
        if identical:
            # The profile copy is byte-identical, so it carries no claim the survivor does
            # not already hold and no date the survivor's own absolutisation did not reach.
            # Scanning it would report the same relative date twice for one edit.
            description, links, added, records = here.description, list(here.links), 0, ()
            kind = "identical"
        else:
            other_body, other_resolved, other_unresolved = absolutise(
                there.body, there_date, name, PROFILE_LAYER
            )
            hits += other_resolved
            unresolved += other_unresolved
            body, added, records = merge_bodies(
                body, other_body, PROJECT_LAYER, PROFILE_LAYER, here_date, there_date
            )
            description = merge_descriptions(here.description, there.description)
            links = merge_links(list(here.links), list(there.links))
            kind = "diverged"
        survivor = replace(
            here,
            description=description,
            body=body,
            links=links,
            # `created` is FIRST-LANDING (see `MemoryStore.save`), so the union of two
            # copies landed first on the earlier of the two dates. `last_recalled` is the
            # opposite question — the most recent evidence anyone wanted this — so it takes
            # the later. Neither is a tie-break for content; both are facts about the pair.
            created=min(d for d in (here.created, there.created) if d) if (
                here.created or there.created
            ) else None,
            last_recalled=max(
                (d for d in (here.last_recalled, there.last_recalled) if d), default=None
            ),
        )
        planned[name] = survivor
        consumed.append(name)
        merged.append(
            DreamMerge(
                name=name,
                kind=kind,
                jaccard=_jaccard(
                    _tokens(f"{here.name} {here.description}"),
                    _tokens(f"{there.name} {there.description}"),
                ),
                survivor_layer=PROJECT_LAYER,
                consumed_layer=PROFILE_LAYER,
                body_before=len(here.body.encode("utf-8")),
                body_after=len(body.encode("utf-8")),
                blocks_added=added,
                superseded=records,
            )
        )

    # Facts only the project layer holds: nothing to merge, but their relative dates are
    # this pass's to resolve. A PROFILE-ONLY fact is deliberately left alone — it is not
    # consumed by any merge, so editing it would be a write into the user's home directory
    # that buys nothing this pass promised.
    for name in sorted(set(by_project) - set(by_profile)):
        fact = by_project[name]
        basis = _mtime_date(project._fact_path(name))
        body, resolved_hits, unresolved_hits = absolutise(fact.body, basis, name, PROJECT_LAYER)
        hits += resolved_hits
        unresolved += unresolved_hits
        if body != fact.body:
            planned[name] = replace(fact, body=body)

    similar = []
    for here in project_facts:
        for there in profile_facts:
            if here.name == there.name:
                continue
            score = _jaccard(
                _tokens(f"{here.name} {here.description}"),
                _tokens(f"{there.name} {there.description}"),
            )
            if score >= DUPLICATE_JACCARD:
                similar.append(SimilarPair(here.name, there.name, score))
    similar.sort(key=lambda pair: (-pair.jaccard, pair.project_name, pair.profile_name))

    index_before = len(
        "".join(project._index_line(fact) for fact in project_facts).encode("utf-8")
    )
    index_after = len(
        "".join(
            project._index_line(planned.get(fact.name, fact)) for fact in project_facts
        ).encode("utf-8")
    )
    profile_index_before = len(
        "".join(profile._index_line(fact) for fact in profile_facts).encode("utf-8")
    )
    profile_index_after = len(
        "".join(
            profile._index_line(fact)
            for fact in profile_facts
            if fact.name not in set(consumed)
        ).encode("utf-8")
    )

    project_sizes = {fact.name: _size(project._fact_path(fact.name)) for fact in project_facts}
    profile_sizes = {fact.name: _size(profile._fact_path(fact.name)) for fact in profile_facts}
    fact_bytes_before = sum(project_sizes.values()) + sum(profile_sizes.values())
    fact_bytes_after = fact_bytes_before - sum(profile_sizes[name] for name in consumed)
    for name, fact in planned.items():
        fact_bytes_after += len(project._fact_text(fact).encode("utf-8")) - project_sizes[name]

    result = DreamResult(
        applied=False,
        dry_run=dry_run,
        merged=tuple(merged),
        refused=tuple(refused),
        absolutised=tuple(hits),
        unresolved=tuple(unresolved),
        similar_unmerged=tuple(similar),
        consumed=tuple(consumed),
        rewritten=tuple(sorted(planned)),
        archive_dir=str(profile.root / "archive"),
        index_before=index_before,
        index_after=index_after,
        budget=project.index_budget,
        profile_index_before=profile_index_before,
        profile_index_after=profile_index_after,
        fact_bytes_before=fact_bytes_before,
        fact_bytes_after=fact_bytes_after,
        project_root=str(project.root),
        profile_root=str(profile.root),
    )
    if dry_run or result.over_budget or not result.changes:
        return result

    for fact in planned.values():
        project._write_fact(fact)
    for name in consumed:
        _consume(profile, name)
    _rebuild_if_present(project)
    _rebuild_if_present(profile)
    return replace(result, applied=True)
