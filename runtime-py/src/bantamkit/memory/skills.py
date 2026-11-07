"""bantamkit's own learned skills as a read-only recall layer, tagged `[skill]` (#206, X8).

A skill bantamkit installed is a directory `<root>/<name>/SKILL.md` in the Agent Skills format
(`bantamkit.skillfile`). This layer offers each one to #199's scorer and gate exactly as the
`native` layer offers a host fact: the prompt is matched against the skill's name, its
`description` and the comma-separated `metadata.bantamkit-keywords` (plan reading R9), one header
line `[skill] [<name>] (skill) <description>` is injected, and the body is read through
`memory_recall` by name. It costs nothing until a prompt matches it.

ROOTS, in order: `<project top>/.bantamkit/skills` (the project store's parent's `skills`,
only when that parent is a `.bantamkit` directory), then `~/.bantamkit/skills`. One directory
is one root. A name both roots hold keeps the first, and the second is skipped with the hot
index's own `duplicate name` sentence.

LEFT OUT, silently: a skill `skills-state.json` records as promoted (its native link carries
it, and injecting it too would pay for it twice), and a directory entry that is not a skill
directory: a hidden one, a build or set-aside directory `skillfile` makes
(`<name>.tmp-<pid>-<n>`, `<name>.old-<pid>-<n>`), or one with no `SKILL.md` file.
LEFT OUT, and named in `skipped`: a `SKILL.md` that is not UTF-8, cannot be read, does not
parse, or breaks any `skillfile.validate` rule (directory name included).

READ-ONLY in every sense `native` is: no stamp, no read-repair, no save, no compaction, no
dream ever writes a skills directory. A use is recorded in the usage ledger by name (R10),
which lives under `~/.bantamkit/usage`, never here.

NO HOT INDEX. The plan named one; `HotIndex` lists a flat directory of `*.md` files and a skill
is a directory, and `validate` has to read the whole `SKILL.md` (body line count, `## Steps`)
before a skill may be offered at all, so every pool parses every skill either way. A skills
root holds a handful of directories (the installer caps automatic installs at five live), so
the files answer every recall. Nothing is written anywhere, the index directory included.
"""

from __future__ import annotations

import os
import re
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from bantamkit.client import BantamError
from bantamkit.skillinstall import TRIGGERS_ENV, TRIGGERS_KEY

from .store import _NOT_ONE_LINE, Fact, Pool, pool_of

#: The label the layer's hits carry: `[skill] [name] (skill) description`.
SKILL_LAYER = "skill"
#: The type every skill fact carries; absent from `retrieval.W_TYPE`, so it weighs `W_TYPE_OTHER`.
SKILL_TYPE = "skill"
#: The metadata key whose comma-separated value is the fact's `keywords` (R9).
KEYWORDS_KEY = "bantamkit-keywords"
# #301: `TRIGGERS_KEY` is the metadata key whose `|`-separated value is the skill's trigger
# phrases (the one the installer stamps); `TRIGGERS_ENV` is the switch for firing on one, read
# with the `BANTAMKIT_SKILL_AUTO` parse. Both live in `skillinstall` (see `TRIGGERS_ENV` there).
#: Set by the #301 ship-bar measurement (plan Task 8): True iff precision@inject passed.
TRIGGERS_DEFAULT = False
_ON = ("on", "1", "true", "yes")

# What `skillfile._temp` names a directory it is building or has set aside.
_NOT_A_SKILL_DIR = re.compile(r".+\.(?:tmp|old)-[0-9]+-[0-9]+")


def skill_roots(project_store: Path | str, home: Path | str) -> list[Path]:
    """The layer's roots for a project store: its `.bantamkit/skills`, then the user's."""
    from bantamkit.skillfile import skills_root

    store = Path(project_store)
    roots: list[Path] = []
    if store.parent.name == ".bantamkit":
        roots.append(store.parent / "skills")
    user = skills_root(home)
    if not any(_same(user, r) for r in roots):
        roots.append(user)
    return roots


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except OSError:
        return a.absolute() == b.absolute()


def promoted_names(home: Path | str) -> frozenset[str]:
    """Names `skills-state.json` records as promoted: an entry whose `promoted` is set.

    Set means present, not `null` and not `false`. A state file that cannot be read excludes
    nothing: the layer keeps answering, and the worst case is a promoted skill offered twice.
    """
    from bantamkit.skillfile import SkillFileError, read_state

    try:
        skills = read_state(home)["skills"]
    except (SkillFileError, OSError):
        return frozenset()
    out = set()
    for name, entry in skills.items():
        if isinstance(entry, dict) and "promoted" in entry:
            value = entry["promoted"]
            if value is not None and value is not False:
                out.add(name)
    return frozenset(out)


def keywords_of(value: Any) -> list[str]:
    """`metadata.bantamkit-keywords` split on `,`, each stripped, the empty ones dropped."""
    if not isinstance(value, str):
        return []
    return [k for k in (part.strip() for part in value.split(",")) if k]


def triggers_enabled() -> bool:
    """`BANTAMKIT_SKILL_TRIGGERS`: unset or blank is `TRIGGERS_DEFAULT`; else on iff in `_ON`."""
    raw = os.environ.get(TRIGGERS_ENV, "").strip().lower()
    return TRIGGERS_DEFAULT if raw == "" else raw in _ON


def triggers_of(value: Any) -> list[tuple[str, ...]]:
    """`metadata.bantamkit-triggers` split on `|`, each phrase split on spaces; empties dropped.

    A phrase of fewer than two tokens is dropped: the miner never writes one (#301).
    """
    if not isinstance(value, str):
        return []
    out = []
    for part in value.split("|"):
        toks = tuple(t for t in part.split(" ") if t)
        if len(toks) >= 2:
            out.append(toks)
    return out


class SkillStore:
    """A read-only layer over `roots`: the methods `Memory` calls on a layer, and no write."""

    def __init__(self, roots: Sequence[Path | str], home: Path | str | None = None):
        self.roots = [Path(r) for r in roots]
        # The store's identity for the queries sidecar and the unreadable-layer report.
        self.root = self.roots[0]
        self._home = None if home is None else Path(home)
        # Each offered skill's trigger phrases, by name, as the last `candidates` walk kept them;
        # `_read` leaves the phrases of the file it just read in `_last_triggers`.
        self._triggers: dict[str, list[tuple[str, ...]]] = {}
        self._last_triggers: list[tuple[str, ...]] = []

    def _state_home(self) -> Path:
        return self._home if self._home is not None else Path.home()

    def index(self) -> Any:
        """This layer keeps no hot index (see the module docstring)."""
        raise BantamError("the skill layer keeps no hot index")

    # ------------------------------------------------------------------ the files

    def _listing(self) -> list[Path]:
        """Every `<root>/<dir>/SKILL.md`, roots in order, directories in code-point order."""
        from bantamkit.skillfile import SKILL_FILE

        out: list[Path] = []
        for root in self.roots:
            try:
                names = sorted(
                    e.name
                    for e in os.scandir(root)
                    if not e.name.startswith(".")
                    and _NOT_A_SKILL_DIR.fullmatch(e.name) is None
                    and e.is_dir()
                )
            except (FileNotFoundError, NotADirectoryError):
                continue  # not there is a root of nothing, silently
            out += [root / n / SKILL_FILE for n in names if (root / n / SKILL_FILE).is_file()]
        return out

    def _read(self, path: Path) -> Fact:
        """One `SKILL.md` as a `Fact`; raises `BantamError` with the `malformed skill` sentence."""
        from bantamkit.skillfile import SkillFileError, parse_skill, validate

        try:
            raw = path.read_bytes()
        except OSError as e:
            raise BantamError(f"malformed skill {path}: SKILL.md could not be read") from e
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise BantamError(f"malformed skill {path}: SKILL.md is not UTF-8") from e
        try:
            doc = parse_skill(text)
        except SkillFileError as e:
            raise BantamError(f"malformed skill {path}: {e}") from e
        broken = validate(doc, path.parent.name)
        if broken:
            raise BantamError(f"malformed skill {path}: {'; '.join(broken)}")
        self._last_triggers = triggers_of(doc.metadata.get(TRIGGERS_KEY))
        return Fact(
            name=doc.name,
            description=_NOT_ONE_LINE.sub(" ", doc.description),
            type=SKILL_TYPE,
            body=doc.body,
            links=[],
            last_recalled=None,
            source=path,
            keywords=keywords_of(doc.metadata.get(KEYWORDS_KEY)),
        )

    def candidates(
        self, skipped: list[dict[str, str]] | None = None, shadow: Any = frozenset()
    ) -> list[Fact]:
        """Every offered skill, in listing order; the promoted and the shadowed left out.

        A skill that cannot be offered, and the second one claiming a name, go to `skipped`.
        """
        from bantamkit.storage.hotindex import DUPLICATE

        promoted = promoted_names(self._state_home())
        out: list[Fact] = []
        held: dict[str, Path] = {}
        # Only the copy that holds a name lends it triggers, never a skipped duplicate (#301).
        triggers: dict[str, list[tuple[str, ...]]] = {}
        for path in self._listing():
            file = f"{path.parent.name}/{path.name}"
            try:
                fact = self._read(path)
            except BantamError as e:
                if skipped is not None:
                    skipped.append({"file": file, "reason": str(e)})
                continue
            first = held.get(fact.name)
            if first is not None:
                if skipped is not None:
                    reason = f"{DUPLICATE} '{fact.name}': {first} holds it"
                    skipped.append({"file": file, "reason": reason})
                continue
            held[fact.name] = path
            triggers[fact.name] = self._last_triggers
            if fact.name not in shadow and fact.name not in promoted:
                out.append(fact)
        self._triggers = triggers
        return out

    def fire(
        self, tokens: Sequence[str], shown: Collection[str], shadow: Any = frozenset()
    ) -> Fact | None:
        """The one skill a trigger phrase names in `tokens`: longest match, then name (#301).

        A trigger fires when it occurs as a contiguous run of `tokens`. A skill in `shown` never
        fires, nor a promoted or a shadowed one (`candidates` leaves those out, as for `pool`).
        """
        best: tuple[int, str, Fact] | None = None
        toks = list(tokens)
        for fact in self.candidates(None, shadow):
            if fact.name in shown:
                continue
            for ph in self._triggers.get(fact.name, ()):
                k = len(ph)
                if any(tuple(toks[i : i + k]) == ph for i in range(len(toks) - k + 1)):
                    if best is None or (-k, fact.name) < (-best[0], best[1]):
                        best = (k, fact.name, fact)
        return None if best is None else best[2]

    def count(self) -> int:
        """How many skill directories the roots list; 0 when none is there."""
        return len(self._listing())

    # ------------------------------------------------------------------ the recall surface

    def pool(
        self,
        q: list[str],
        skipped: list[dict[str, str]] | None = None,
        shadow: Any = frozenset(),
        every_row: bool = False,
    ) -> Pool:
        """This layer's share of a pooled recall, the `shadow` names taken out before scoring."""
        return pool_of(self.candidates(skipped, shadow), q, every_row)

    def resolve(self, pool: Pool, row: int) -> Fact | None:
        """The fact a row stands for: the files answered, so the pool holds it."""
        assert pool.facts is not None
        return pool.facts[row]

    def lookup(
        self, name: str, stamp: bool = False, skipped: list[dict[str, str]] | None = None
    ) -> Fact | None:
        """The offered skill named exactly `name`, or `None`. `stamp` never writes."""
        return next((f for f in self.candidates(skipped) if f.name == name), None)

    def archived_recall(self, query: str, k: int, exclude: Any = ()) -> list[Fact]:
        """A skill has no archive this layer reads."""
        return []

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Nothing to pin: nothing here is ever written by recall."""
        yield
