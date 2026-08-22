"""Do two memory stores hold the same facts? A read-only instrument, owning no writer.

This machine keeps the same knowledge in two stores with two layouts, and neither
writer knows about the other. `MemoryStore` cannot read across the gap: pointed at
the native root it finds 0 facts (it globs `facts/*.md` and the native store is
flat), and a single native-shaped file placed under `facts/` makes `_facts()` raise
`MemoryValidationError` store-wide on `meta["type"]` — one bad file costs all the
others. Both measured 2026-08-22. So the comparison needs its own parser, and this
module is it: additive, read-only, and it does not touch `_facts()` or
`_write_fact()`.

Shapes measured 2026-08-22 over the two live stores (64 bantamkit facts, 59 native
facts plus `MEMORY.md`):

                bantamkit                     native
    root        <repo>/.bantamkit/memory      ~/.claude/projects/<slug>/memory
    facts       facts/*.md                    flat *.md
    index       index.md                      MEMORY.md
    type        top level, 64/64              metadata.type, 57/59
    extras      created 17/64,                metadata.node_type 11,
                last_recalled 32/64,          metadata.originSessionId 11,
                links 32/64                   metadata.modified 11, links 21

The two native files with a top-level `type` are `feedback-gate-counts-are-co-moving`
and `feedback-prep-probe-before-planning`. That drift is the input, not a bug to fix
here, which is why shape is decided per file and never per directory.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bantamkit.memory.layers import MEMORY_DIR_ENV, resolve_project_store
from bantamkit.memory.store import MemoryValidationError

# Both stores keep a generated roll-up beside the facts. It is derived from them, so
# comparing it would report the same drift twice, and it carries no frontmatter, so
# leaving it in would make every clean store report one unparseable file.
#
# MS4 measured what filtering it by NAME costs. `MemoryStore`'s fact-name regex
# `^[a-z0-9][a-z0-9-]*$` accepts `index` and `memory`, so a fact legitimately called
# either one was dropped from BOTH stores' scans -- `save('index')` writes
# `facts/index.md`, and `compare_stores()` then saw nothing -- and a store holding two
# such facts compared CLEAN against an empty store. Zero of the 65 live facts hit it, so
# it was latent, but the direction is false green, which is the one direction this module
# exists to prevent.
#
# So the names below are only CANDIDATES now, and IDENTITY decides: a candidate is the
# store's own index only if it does not parse as a fact. See `_is_generated_index`.
INDEX_CANDIDATE_NAMES = {"index.md", "memory.md"}

# Claude Code names a project directory by rewriting its absolute path. Measured
# against all 26 slugs under ~/.claude/projects on 2026-08-22: every character outside
# [A-Za-z0-9] becomes `-`, not just the separator. The witness is
# `.../packnplan-mono/.claude/worktrees/feat-render-deploy-followups`, stored as
# `...-packnplan-mono--claude-worktrees-feat-render-deploy-followups` — the `.` of
# `.claude` collapsed exactly like the `/` in front of it. No slug on this machine
# contains a character outside the class.
_SLUG_RE = re.compile(r"[^A-Za-z0-9]")

# The native root is keyed on the *session's launch cwd*, which no file in the repo
# records: five of the six bantamkit-ish slugs on this machine came from scratchpad
# probe cwds, not from the repo. The default below reconstructs it from the canonical
# checkout, which is right for a session launched in the repo or in one of its
# worktrees; anything else has to say so, and this is how.
NATIVE_ROOT_ENV = "BANTAMKIT_NATIVE_MEMORY"


@dataclass(frozen=True)
class StoredFact:
    """One fact as it sits on disk, with the shape it was found in recorded."""

    name: str
    description: str
    type: str
    body: str
    shape: str  # "bantamkit" | "native" — which frontmatter this file carried
    path: str


@dataclass(frozen=True)
class UnparseableFact:
    """A file that claimed to be a fact and is not. Reported, never skipped silently."""

    path: str
    reason: str


@dataclass(frozen=True)
class BodyDiff:
    """One name both stores hold, disagreeing about the text under the frontmatter."""

    name: str
    a_path: str
    b_path: str
    a_bytes: int
    b_bytes: int


@dataclass(frozen=True)
class DescriptionDiff:
    """One name both stores hold, agreeing about the body and disagreeing about the
    line that gets it recalled.

    This category exists because MS2 hit it and this instrument was blind to it: four
    facts had byte-identical bodies and different `description:` values, so the two
    indexes described the same knowledge differently while `compare_stores()` reported
    clean. It is kept apart from `BodyDiff` because the remedy is different and much
    cheaper -- the knowledge already agrees, only the recall key does -- and because a
    description-only drift is the one class where reading the two bodies tells you
    nothing.

    `description` is compared even though the rest of the frontmatter is not, and the
    reason is that it is the only other field BOTH shapes carry at the top level and
    that recall actually matches on. Measured over the real pair on 2026-08-22:
    65 of 65 bantamkit facts and 64 of 64 native facts carry a non-empty top-level
    `description`, so comparing it can never fire merely because one shape omits it.
    """

    name: str
    a_path: str
    b_path: str
    a_description: str
    b_description: str


# NOT compared, and looked at rather than overlooked: `type`. It is the other field both
# shapes carry (top level in one, under `metadata:` in the other -- it is what shape
# detection keys on), and over the 64 names the real pair shares it drifted 0 times when
# measured on 2026-08-22. Left out to keep this unit's extension to the single class MS2
# actually hit; it is a two-line addition for whoever measures a nonzero there. Rerun:
#   PYTHONPATH=runtime-py/src .venv/bin/python -c "from bantamkit.memory.divergence \
#     import read_store, bantamkit_store_root, native_store_root; \
#     A={f.name:f for f in read_store(bantamkit_store_root())[0]}; \
#     B={f.name:f for f in read_store(native_store_root())[0]}; \
#     print([n for n in A.keys()&B.keys() if A[n].type!=B[n].type])"


# ---- can this store be read at all? ----
#
# Three answers, not two, and the third is the whole point. A store that is ABSENT means
# this machine is not the one the real-pair tripwire is for -- a CI runner has neither
# root, because `.bantamkit/memory/` is gitignored (0 files tracked) and `~/.claude/` is
# not checked out at all. A store that is present but UNREADABLE is a finding: something
# put a file, a dangling symlink, or an unlistable directory where a store belongs, and
# reporting that as "absent" would let a real breakage buy itself a green skip.
PRESENT = "present"
ABSENT = "absent"
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class StoreAvailability:
    """Whether a store root can be read, and -- when it cannot -- which kind of cannot."""

    root: str
    state: str  # PRESENT | ABSENT | UNREADABLE
    reason: str

    @property
    def present(self) -> bool:
        return self.state == PRESENT


def store_availability(root: str | Path) -> StoreAvailability:
    """Probe a store root without reading a single fact out of it.

    Separated from `read_store` on purpose: `read_store` raises on a missing root, and a
    caller that has to tell "not this machine" from "broken on this machine" cannot get
    that out of an exception it must catch to survive.
    """
    root = Path(root)
    try:
        exists = root.exists()
    except OSError as e:  # pragma: no cover - a stat that raises needs a hostile fs
        return StoreAvailability(str(root), UNREADABLE, f"cannot stat {root}: {e}")
    if not exists:
        if os.path.lexists(root):
            return StoreAvailability(
                str(root),
                UNREADABLE,
                f"a symlink at {root} points at nothing -- a store was expected here",
            )
        return StoreAvailability(str(root), ABSENT, f"no directory at {root}")
    if not root.is_dir():
        return StoreAvailability(
            str(root), UNREADABLE, f"{root} exists but is not a directory"
        )
    try:
        next(iter(root.iterdir()), None)
    except OSError as e:
        return StoreAvailability(
            str(root), UNREADABLE, f"{root} is a directory that cannot be listed: {e}"
        )
    return StoreAvailability(str(root), PRESENT, "")


@dataclass
class DivergenceReport:
    """The five ways two stores can disagree, named separately.

    They are separate because the remedies differ: copy A->B, copy B->A, resolve the
    body by hand, reconcile the recall key, and go look at the file. Collapsing them
    into one count would hide which.

    `description_differs` was added by MS3 after MS2 reconciled four of them BY HAND
    that this report called clean. See `DescriptionDiff`.
    """

    a_root: str
    b_root: str
    a_count: int
    b_count: int
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)
    body_differs: list[BodyDiff] = field(default_factory=list)
    description_differs: list[DescriptionDiff] = field(default_factory=list)
    unparseable: list[UnparseableFact] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (
            self.only_in_a
            or self.only_in_b
            or self.body_differs
            or self.description_differs
            or self.unparseable
        )

    def summary(self) -> str:
        return (
            f"A {self.a_root} ({self.a_count} facts) vs B {self.b_root} "
            f"({self.b_count} facts): only_in_a={len(self.only_in_a)} "
            f"only_in_b={len(self.only_in_b)} body_differs={len(self.body_differs)} "
            f"description_differs={len(self.description_differs)} "
            f"unparseable={len(self.unparseable)} clean={self.clean}"
        )

    def explain(self) -> str:
        """Every diverging fact BY NAME, with the path to each side of it.

        A gate that reports "2 facts differ" has told the reader only that there is an
        investigation to do, and they then do the same search this function already did.
        So the counts are the headline and the names are the body, and every name is
        printed -- there is no elision at N, because the one line that got elided is the
        one nobody goes and looks up.
        """
        lines = [
            self.summary(),
            f"  A = {self.a_root}",
            f"  B = {self.b_root}",
        ]
        if self.clean:
            lines.append("  no divergence.")
            return "\n".join(lines)

        if self.only_in_a:
            lines.append(f"  only in A ({len(self.only_in_a)}) -- B is owed a copy:")
            lines.extend(f"    {name}" for name in self.only_in_a)
        if self.only_in_b:
            lines.append(f"  only in B ({len(self.only_in_b)}) -- A is owed a copy:")
            lines.extend(f"    {name}" for name in self.only_in_b)
        if self.body_differs:
            lines.append(
                f"  body differs ({len(self.body_differs)}) -- resolve by hand, never by "
                f"mtime; recall() rewrites the stamps:"
            )
            for d in self.body_differs:
                lines.append(f"    {d.name}  ({d.a_bytes} B vs {d.b_bytes} B)")
                lines.append(f"      A: {d.a_path}")
                lines.append(f"      B: {d.b_path}")
        if self.description_differs:
            lines.append(
                f"  description differs ({len(self.description_differs)}) -- same body, "
                f"different recall key:"
            )
            for d in self.description_differs:
                lines.append(f"    {d.name}")
                lines.append(f"      A: {d.a_description!r}")
                lines.append(f"      B: {d.b_description!r}")
        if self.unparseable:
            lines.append(f"  unparseable ({len(self.unparseable)}) -- go look at the file:")
            for u in self.unparseable:
                lines.append(f"    {u.path}")
                lines.append(f"      {u.reason}")
        return "\n".join(lines)


# ---- the writer's levers on WHERE the bantamkit store is ----
#
# THE FAILURE THIS SECTION EXISTS FOR, measured by MS4 on the merged tree and reproduced
# on this one 2026-08-23: with `BANTAMKIT_MEMORY_DIR` live, the writer saved a fact into
# the pinned store, `bantamkit_store_root()` returned `<repo>/.bantamkit/memory`, and the
# real-pair tripwire reported `clean=True`. 1829 passed, fully green, while the store
# actually in use drifted unwatched. A gate that goes green by reading the wrong file is
# worse than no gate.
#
# It was worse than "this resolver ignores the pin". It ignored the pin WHEN THE ANCHOR
# EXISTED and honoured it WHEN THE ANCHOR DID NOT -- the old fallback to
# `discover_project_store()` reads the pin -- so one function held two precedences and
# which one you got depended on whether `<repo>/.bantamkit/memory` happened to be there.
# Measured 2026-08-23 on this tree, before the fix:
#     anchor EXISTS  -> <repo>/.bantamkit/memory      (pin ignored)
#     anchor ABSENT  -> <the pin>                     (pin honoured)
#     relative pin, anchor ABSENT -> MemoryValidationError
#     missing pin,  anchor EXISTS -> no raise at all
#
# THE FIX IS DELEGATION, NOT IMITATION. `bantamkit_store_root()` now asks the writer's own
# resolver where it would write and takes its answer whenever that answer came from a pin
# (`origin == "pin"`). It does not read the environment, does not spell the variable's
# name, and does not restate the writer's three rulings about a pin (a blank value is not
# a pin, a relative pin raises, a missing pin raises). A SECOND, DIVERGENT COPY of the
# writer's precedence would be the same false green in a new costume, and nothing would
# catch it drifting; there is now exactly one copy and this module imports it.
#
# THE REGISTER BELOW IS THE SECOND LINE, for the lever that has not been invented yet.
# Delegation fixes the pin because the pin is expressed through `StoreBinding.origin`; a
# FUTURE lever need not be. So the population of `BANTAMKIT_*` names the writer's modules
# wire to anything is registered here, in the pattern this repo already uses for
# `_WINDOWS_ONLY_SKIPS`, and two CI-reachable nodes in `tests/test_memory_divergence.py`
# hold it shut from opposite sides:
#
#   * every name the writer wires must appear in this register -- so a branch that adds
#     one turns the suite red ON ARRIVAL, in the merge commit, and not on some later day
#     when a store has already drifted unwatched;
#   * every name IN this register must MEASURABLY move `bantamkit_store_root()` -- so the
#     register cannot be silenced by editing it. Adding a name without teaching the
#     resolver swaps one red for another.
#
# The one name in it today is imported, never retyped, so the register and the writer
# cannot come to be talking about different variables.
ACCOUNTED_WRITER_ENV: frozenset[str] = frozenset({MEMORY_DIR_ENV})

_ENV_NAME_RE = re.compile(r"BANTAMKIT_[A-Z0-9_]+")


def writer_source_files() -> list[Path]:
    """Every module in this package that could be part of the writer's store resolution.

    Globbed rather than listed, so a module added tomorrow is scanned without anybody
    remembering to add it. This module is excluded: `NATIVE_ROOT_ENV` is the INSTRUMENT's
    own knob, not the writer's, and registering it against itself would prove nothing.
    """
    here = Path(__file__).resolve()
    return sorted(p for p in here.parent.glob("*.py") if p.name != here.name)


def env_names_in_source(source: str) -> frozenset[str]:
    """Every `BANTAMKIT_*` env name a module NAMES IN CODE. Docstrings do not count.

    Parsed, not grepped, and the difference is load-bearing. On the sibling branch
    `layers.py` mentions `BANTAMKIT_MEMORY_DIR` in a comment and in a docstring as well as
    in the one assignment that wires it, and mentions `BANTAMKIT_ASSETS` in prose only --
    a text scan hands the merger two names to chase, one of which is nothing to do with
    the memory store. The AST reports the one name that is actually attached to code.
    """
    tree = ast.parse(source)
    prose = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return frozenset(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and node not in prose
        and isinstance(node.value, str)
        and _ENV_NAME_RE.fullmatch(node.value)
    )


def writer_store_env_names() -> frozenset[str]:
    """The population: every env name the writer's modules wire to anything, right now."""
    names: set[str] = set()
    for path in writer_source_files():
        names |= env_names_in_source(path.read_text(encoding="utf-8"))
    return frozenset(names)


def unaccounted_writer_env() -> frozenset[str]:
    """Names the writer honours that this resolver has not been taught. Must stay empty."""
    return writer_store_env_names() - ACCOUNTED_WRITER_ENV


def resolver_honours_env(name: str, target: str | Path) -> bool:
    """Does `bantamkit_store_root()` actually bind to `target` when `name` names it?

    RUN, not read. The register's second node exists because a name can be added to
    `ACCOUNTED_WRITER_ENV` in one line while the resolver still ignores it, and a
    register that can be silenced by editing the register is decoration. Nothing short of
    calling the resolver answers this.

    The variable is set and restored around the single call, including the case where it
    was not set before. This is the only place in this read-only module that writes
    anything at all, and what it writes is one process-local environment slot.
    """
    target = Path(target)
    previous = os.environ.get(name)
    os.environ[name] = str(target)
    try:
        return bantamkit_store_root().resolve() == target.resolve()
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


# ---- roots ----


def _canonical_repo_root(start: str | Path | None = None) -> Path:
    """The main checkout, even when called from one of its worktrees.

    A linked worktree's `.git` is a *file* reading `gitdir: <main>/.git/worktrees/<n>`
    — measured in this worktree on 2026-08-22, alongside
    `git rev-parse --git-common-dir == <main>/.git`. Following that pointer in pure
    Python keeps the module free of a `git` subprocess, which also keeps it honest on
    a CI runner that has no git on PATH.
    """
    base = (Path(start) if start is not None else Path.cwd()).resolve()
    for directory in (base, *base.parents):
        marker = directory / ".git"
        if marker.is_dir():
            return directory
        if marker.is_file():
            text = marker.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir:"):
                return directory
            gitdir = Path(text.split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = (directory / gitdir).resolve()
            for parent in (gitdir, *gitdir.parents):
                if parent.name == ".git":
                    return parent.parent
            return directory
    return base


def bantamkit_store_root(start: str | Path | None = None) -> Path:
    """`<repo>/.bantamkit/memory`, anchored on the repo — never hardcoded, never guessed.

    The obvious implementation — defer to `discover_project_store`, which already owns
    an ancestor walk for exactly this — is WRONG here, and running it is how that was
    found. From this worktree on 2026-08-22 it returned `/Users/kktest/.bantamkit/memory`:
    a linked worktree has no `.bantamkit/` of its own, so the walk climbed past the repo
    to an EMPTY store sitting in `$HOME`, and `compare_stores()` cheerfully reported
    `0 facts vs 59, only_in_b=59`. A wrong store that exists is worse than no store,
    because it answers.

    So the repo's own store wins whenever it exists. The ancestor walk is kept only as
    the fallback for a checkout with no `.git` marker (a tarball, a vendored copy),
    where anchoring has nothing to anchor to.

    A PIN OUTRANKS BOTH, and the answer to whether one is set comes from the writer
    rather than from this module's own reading of the environment. `origin == "pin"` is
    the writer saying "I did not walk anywhere; the operator named this store", and that
    is the store a comparison has to be about. See the section note above for what the
    two-precedence version of this function measured.

    RAISES `MemoryValidationError`, propagated from the writer, when a pin is set and
    unusable (relative, missing, not a directory). Deliberately not caught here: this
    function's contract is "the store the writer would use", and when the writer has no
    usable answer, inventing one is how a gate comes to read the wrong file. Callers that
    must survive it use `bantamkit_store_availability()`, which turns the raise into the
    UNREADABLE finding it is.
    """
    binding = resolve_project_store(start)
    if binding.origin == "pin":
        return binding.path
    anchored = _canonical_repo_root(start) / ".bantamkit" / "memory"
    if anchored.is_dir():
        return anchored
    # Same walk the old fallback ran, already done: `binding.path` for a walk binding is
    # what `discover_project_store()` returns, and "designated" is its way of saying the
    # walk found nothing anywhere up the tree.
    if binding.state != "designated":
        return binding.path
    return anchored


def bantamkit_store_availability(start: str | Path | None = None) -> StoreAvailability:
    """`store_availability()` for the bantamkit store, with the pin's raise folded in.

    A pinned store that is relative, missing, or not a directory makes
    `bantamkit_store_root()` raise, and a raise reaching pytest collection is a crash
    where this package already has a vocabulary for the situation: something is named as
    a store and cannot be read, which is UNREADABLE, which `_precondition()` turns into a
    hard fail rather than a skip. A typo'd pin is a finding, not an absence -- exactly the
    distinction the three-state probe was built to make -- and routing it anywhere else
    would let a broken pin buy itself a green skip.
    """
    try:
        root = bantamkit_store_root(start)
    except MemoryValidationError as e:
        raw = os.environ.get(MEMORY_DIR_ENV) or ""
        return StoreAvailability(
            raw or "<the writer's store>",
            UNREADABLE,
            f"the store the writer is bound to cannot be resolved: {e}",
        )
    return store_availability(root)


def native_store_root(start: str | Path | None = None) -> Path:
    """`~/.claude/projects/<slug>/memory`, from the canonical checkout or the env.

    See NATIVE_ROOT_ENV: the slug encodes the session's launch cwd, which the repo does
    not record, so the reconstruction is a good default and not a derivation.
    """
    override = os.environ.get(NATIVE_ROOT_ENV)
    if override:
        return Path(override)
    slug = _SLUG_RE.sub("-", str(_canonical_repo_root(start)))
    return Path.home() / ".claude" / "projects" / slug / "memory"


# ---- parsing ----


def parse_fact(path: str | Path) -> StoredFact:
    """Read one fact file, deciding its shape from its own frontmatter.

    Raises `MemoryValidationError` — this package's existing error for "this file is
    not what it claims to be". Callers that must survive one bad file use `read_store`,
    which turns the raise into a reported row.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise MemoryValidationError(f"unreadable fact file {path}: {e}") from e

    try:
        head, front, body = text.split("---\n", 2)
    except ValueError as e:
        raise MemoryValidationError(f"malformed fact file {path}: no frontmatter fences") from e
    if head.strip():
        raise MemoryValidationError(
            f"malformed fact file {path}: frontmatter is not at the top of the file"
        )
    try:
        meta = yaml.safe_load(front)
    except yaml.YAMLError as e:
        raise MemoryValidationError(f"malformed fact file {path}: {e}") from e
    if not isinstance(meta, dict):
        raise MemoryValidationError(f"malformed fact file {path}: frontmatter is not a mapping")

    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MemoryValidationError(f"malformed fact file {path}: no usable 'name'")

    # Shape is read off the file, not off the directory it was found in. A store that
    # has drifted must still be readable, and two of the 59 native facts already have.
    # A top-level `type` wins if a file somehow carries both, because that is the shape
    # `MemoryStore` would itself honour.
    metadata = meta.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if isinstance(meta.get("type"), str):
        shape, type_ = "bantamkit", meta["type"]
    elif isinstance(metadata.get("type"), str):
        shape, type_ = "native", metadata["type"]
    else:
        raise MemoryValidationError(
            f"malformed fact file {path}: no 'type' at the top level and none under "
            f"'metadata:' — this file matches neither store's shape"
        )

    description = meta.get("description")
    return StoredFact(
        name=name.strip(),
        description=description if isinstance(description, str) else "",
        type=type_,
        # `.strip()` mirrors `MemoryStore._facts()`, so a fact round-tripped through
        # that writer compares equal to the one it was copied from.
        body=body.strip(),
        shape=shape,
        path=str(path),
    )


def _fact_files(root: Path) -> list[Path]:
    """Every candidate fact file in a store, in both layouts.

    `archive/` is excluded and not by accident: it is where `compact()` *moves* a fact
    to, so a fact one store retired and the other never had is not a live divergence,
    and counting it would put every archived fact in `only_in_*`. Scanning only the
    root and `facts/` leaves it out by construction.

    Flat files come first so that a name held in both layouts keeps the flat copy and
    reports the nested one, rather than the answer depending on glob order.

    Nothing under `facts/` is filtered, and that is the first half of the `index` fix:
    NEITHER store puts its roll-up there. `MemoryStore` writes `index.md` beside
    `facts/`, and the native store writes `MEMORY.md` beside its flat files, so a
    `facts/index.md` is always a fact and excluding it only ever hid one.
    """
    flat = sorted(
        p
        for p in root.glob("*.md")
        if p.name.lower() not in INDEX_CANDIDATE_NAMES or not _is_generated_index(p)
    )
    nested = sorted((root / "facts").glob("*.md"))
    return flat + nested


def _is_generated_index(path: Path) -> bool:
    """Is this the store's own roll-up, or a fact that happens to be called `index`?

    Decided by reading the file, never by its name. Both live indexes were measured
    2026-08-22: `<repo>/.bantamkit/memory/index.md` opens on a `- [[...]]` list item and
    `~/.claude/projects/<slug>/memory/MEMORY.md` opens on a `# Memory index` heading.
    Neither carries frontmatter, so neither parses as a fact, while a fact named `index`
    does -- its writer put frontmatter there. That is the discriminator, and it needs no
    knowledge of which layout the root is in, which matters because on a case-insensitive
    filesystem a native fact named `memory` and the native index `MEMORY.md` ARE THE SAME
    PATH and only the contents can separate them.

    The residue, stated instead of hidden: a fact named `index` or `memory` whose file is
    CORRUPT parses as neither, so it is dropped here rather than reported unparseable.
    That is one file, in the one store that holds it, and it is the only case this rule
    gets wrong -- the rule it replaces got every WELL-FORMED one wrong, in both stores.
    """
    try:
        parse_fact(path)
    except MemoryValidationError:
        return True
    return False


def read_store(root: str | Path) -> tuple[list[StoredFact], list[UnparseableFact]]:
    """Every fact in a store, plus every file that looked like one and was not.

    A store that cannot be *opened* still raises: an empty result and a missing
    directory are opposite facts, and returning `[]` for a typo'd path would let a
    later `clean=True` mean "the stores agree" when it meant "I read neither".
    """
    root = Path(root)
    if not root.is_dir():
        raise MemoryValidationError(f"memory store directory does not exist: {root}")

    facts: dict[str, StoredFact] = {}
    unparseable: list[UnparseableFact] = []
    for path in _fact_files(root):
        try:
            fact = parse_fact(path)
        except MemoryValidationError as e:
            # One unreadable file must not cost the other sixty-three.
            unparseable.append(UnparseableFact(path=str(path), reason=str(e)))
            continue
        if fact.name in facts:
            unparseable.append(
                UnparseableFact(
                    path=str(path),
                    reason=(
                        f"duplicate fact name '{fact.name}' inside one store; "
                        f"already read from {facts[fact.name].path}"
                    ),
                )
            )
            continue
        facts[fact.name] = fact
    return [facts[name] for name in sorted(facts)], unparseable


# ---- comparison ----


def compare_stores(
    a: str | Path | None = None,
    b: str | Path | None = None,
    *,
    start: str | Path | None = None,
) -> DivergenceReport:
    """Compare two stores by fact NAME, then by BODY. With no arguments, the real two.

    Deliberately *not* compared: `last_recalled`, `created`, and the file mtime.
    `recall()` stamps `last_recalled` on every hit and `_stamp` writes the file to do
    it, so all three record who READ a fact, never who wrote it — the store an agent
    happens to recall from would otherwise look uniformly "newer" than the one it does
    not. Which body wins is a hand judgement; this instrument only says where one is
    owed.

    Frontmatter beyond the name and the description is also not compared: the two shapes
    disagree about the rest by construction (`metadata.originSessionId` has no bantamkit
    counterpart), so a field-by-field diff would report dozens of divergences that mean
    nothing. `description` is the exception because both shapes carry it at the top level
    in 129 of 129 real facts and because it is what recall matches on -- see
    `DescriptionDiff` for the four this instrument used to miss.
    """
    a_root = Path(a) if a is not None else bantamkit_store_root(start)
    b_root = Path(b) if b is not None else native_store_root(start)

    a_facts, a_bad = read_store(a_root)
    b_facts, b_bad = read_store(b_root)
    a_by_name = {f.name: f for f in a_facts}
    b_by_name = {f.name: f for f in b_facts}

    body_differs = []
    description_differs = []
    for name in sorted(a_by_name.keys() & b_by_name.keys()):
        left, right = a_by_name[name], b_by_name[name]
        if left.body != right.body:
            body_differs.append(
                BodyDiff(
                    name=name,
                    a_path=left.path,
                    b_path=right.path,
                    a_bytes=len(left.body.encode("utf-8")),
                    b_bytes=len(right.body.encode("utf-8")),
                )
            )
        # `.strip()` because one writer hard-wraps the YAML scalar and the other does
        # not, so the two carry the same sentence with different trailing whitespace.
        # A drift that is only whitespace is not a drift a human is owed a look at.
        if left.description.strip() != right.description.strip():
            description_differs.append(
                DescriptionDiff(
                    name=name,
                    a_path=left.path,
                    b_path=right.path,
                    a_description=left.description.strip(),
                    b_description=right.description.strip(),
                )
            )

    return DivergenceReport(
        a_root=str(a_root),
        b_root=str(b_root),
        a_count=len(a_facts),
        b_count=len(b_facts),
        only_in_a=sorted(a_by_name.keys() - b_by_name.keys()),
        only_in_b=sorted(b_by_name.keys() - a_by_name.keys()),
        body_differs=body_differs,
        description_differs=description_differs,
        unparseable=a_bad + b_bad,
    )
