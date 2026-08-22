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

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bantamkit.memory.layers import discover_project_store
from bantamkit.memory.store import MemoryValidationError

# Both stores keep a generated roll-up beside the facts. It is derived from them, so
# comparing it would report the same drift twice, and it carries no frontmatter, so
# leaving it in would make every clean store report one unparseable file.
INDEX_NAMES = {"index.md", "memory.md"}

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


@dataclass
class DivergenceReport:
    """The four ways two stores can disagree, named separately.

    They are separate because the remedies differ: copy A->B, copy B->A, resolve by
    hand, and go look at the file. Collapsing them into one count would hide which.
    """

    a_root: str
    b_root: str
    a_count: int
    b_count: int
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)
    body_differs: list[BodyDiff] = field(default_factory=list)
    unparseable: list[UnparseableFact] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.only_in_a or self.only_in_b or self.body_differs or self.unparseable)

    def summary(self) -> str:
        return (
            f"A {self.a_root} ({self.a_count} facts) vs B {self.b_root} "
            f"({self.b_count} facts): only_in_a={len(self.only_in_a)} "
            f"only_in_b={len(self.only_in_b)} body_differs={len(self.body_differs)} "
            f"unparseable={len(self.unparseable)} clean={self.clean}"
        )


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
    """
    anchored = _canonical_repo_root(start) / ".bantamkit" / "memory"
    if anchored.is_dir():
        return anchored
    discovered = discover_project_store(start)
    if discovered.is_dir():
        return discovered
    return anchored


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
    """
    flat = sorted(p for p in root.glob("*.md") if p.name.lower() not in INDEX_NAMES)
    nested = sorted(p for p in (root / "facts").glob("*.md") if p.name.lower() not in INDEX_NAMES)
    return flat + nested


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

    Frontmatter beyond the name is also not compared: the two shapes disagree about it
    by construction (`metadata.originSessionId` has no bantamkit counterpart), so a
    field-by-field diff would report dozens of divergences that mean nothing.
    """
    a_root = Path(a) if a is not None else bantamkit_store_root(start)
    b_root = Path(b) if b is not None else native_store_root(start)

    a_facts, a_bad = read_store(a_root)
    b_facts, b_bad = read_store(b_root)
    a_by_name = {f.name: f for f in a_facts}
    b_by_name = {f.name: f for f in b_facts}

    body_differs = []
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

    return DivergenceReport(
        a_root=str(a_root),
        b_root=str(b_root),
        a_count=len(a_facts),
        b_count=len(b_facts),
        only_in_a=sorted(a_by_name.keys() - b_by_name.keys()),
        only_in_b=sorted(b_by_name.keys() - a_by_name.keys()),
        body_differs=body_differs,
        unparseable=a_bad + b_bad,
    )
