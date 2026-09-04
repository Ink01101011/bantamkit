"""Price the skill catalogue a session pays for, and name the collisions in it.

A skill's `description:` frontmatter is loaded into the agent's context in EVERY session;
its body is read only when the skill is invoked. So the descriptions are the standing bill,
and the two questions an operator can actually act on are "what does the bill come to" and
"which two skills are competing for the same request". This module answers both from nothing
but a directory of `SKILL.md` files and what the caller hands in.

**The collision metric is EXACT match on literal quoted phrases, and a similarity score was
measured and refuted.** Jaccard over description tokens was run across 820 real pairs
(2026-09-04): the maximum score any pair reached was 0.239, and the two collisions a person
would call real ranked 118th and 791st of 820 — a metric whose top of the ranking is noise
cannot be thresholded into a finding. Exact phrases, on the same 41-skill corpus, found four
shared phrases and every one of them was a genuine ambiguity. So there is no score here at
all, and adding one back is a regression however plausible it reads.

**The apostrophe is the whole difficulty.** `'race condition'` is a quoted phrase and `don't`
is a contraction, and a reader that treats every `'` as a delimiter reports the junk between
two contractions as a shared phrase — measured on the fixture tree, where the text between
`don'` and `'t catch` is byte-identical in two skills that share no phrase at all. So a `'`
delimits only when it is NOT flanked by letters on both sides. `"` has no such problem and is
always a delimiter.

**A whole-value quoted scalar is YAML's quoting, not the author's.** `description: "Use when
..."` writes the WHOLE value as a quoted YAML scalar: the host's parser strips those two quotes
before the description ever reaches a session, so they are not bytes anyone pays for and the
text between them is not a trigger phrase. A reader that takes them literally answers two bytes
too many and turns the entire description into one giant phrase, which hides any real quoted
phrase inside it. Measured 2026-09-05 over this machine's own plugin cache: 17 of the 31 enabled
skills are written that way — the majority shape, not an edge case. So a value is unwrapped
before it is counted or scanned, and only quotes INSIDE the value delimit a phrase.

Unwrapping is deliberately narrow, because the eager version loses more than the literal one.
A value is a whole-value scalar only when it opens with a quote AND that quote's own closing
quote is the value's last character — `"a" and "b"` opens and ends with `"` and is NOT one
scalar, and stripping it would destroy both real phrases in it. Closing is judged by YAML's two
escape rules and no others: inside `"` a backslash escapes the next character, inside `'` a
doubled `''` is one apostrophe. A value that OPENS with a quote and never closes is a LITERAL,
not an unwrap and not a new finding — there is no end point to unwrap to, guessing one would
delete a byte the reader cannot prove is YAML's, and `frontmatter-malformed` names failures of
the BLOCK, not of one value. The unpaired quote then opens no phrase, which is already the rule.

**A router quotes its siblings by design.** A skill whose frontmatter carries `router: true`
routes a request to whichever sibling owns it, so it necessarily quotes their phrases; left in
the index it collides with every skill it routes to and the finding floods. It is dropped from
the phrase index ENTIRELY — it neither raises a finding nor joins one — and it is still
COUNTED, because its description is in every session's bill like any other. The mechanism is a
declaration and not a heuristic on purpose: a name pattern (`*-router`) or a phrase-count
threshold would exempt an ordinary skill by accident.

**Count over what the host has switched on, never over the cache directory.** The plugin cache
holds disabled plugins and stale version directories, and both look exactly like live skills on
disk. Measured 2026-09-04 on this machine: scanning the cache answered 41 skills / 19,065 B
against a true 34 / 14,515 — every headline number inflated, in the direction that makes the
tool look useful. `enabled` is therefore the caller's, read from the host's settings, and a
plugin absent from it is an omission carrying the bytes enabling it would cost.

**One version per plugin, resolved BEFORE anything is counted.** A plugin cache holds every
version directory a plugin has ever been installed at, and the host serves exactly one of them.
So the resolution is per (marketplace, plugin) and it happens FIRST: one version directory wins,
its skills are the plugin's skills, and every `SKILL.md` under any other version directory of
that plugin is omitted. Deduping by the (marketplace, plugin, name) TRIPLE instead — which is
what this module did until 2026-09-05 — merges versions rather than choosing between them: a
name present in both versions is displaced correctly, but a name the winning version DROPPED
has nothing to displace it and is counted anyway. Measured that day on this machine's own
cache, where `kkskills-essentials` holds `0.4.0` (14 skills) and `0.5.0` (5, because nine were
moved out to another plugin): the triple rule answered 31 skills / 9,280 bytes where the host
serves 22 / 3,796. A skill deleted in the newer release was resurrected by its own audit.

**The version that wins is the directory name that sorts LAST in BYTE ORDER, and that is still
not a semver comparison.** The order has to be TOTAL and computed identically by two runtimes,
and it has to work on names that are not versions at all: this machine's cache spells
`frontend-design`'s nine directories as content hashes (`0120fb83da5d` … `ed404106fcd8`) plus
the literal `unknown`, where semver has nothing to compare. Byte order is total over every one
of those, free, and already ported. What it gets wrong is stated rather than hidden: `10.0.0`
loses to `9.0.0`, and among names that are not versions the winner is arbitrary — deterministic
and arbitrary, not correct. Both losers are named in an omission record, so an operator can
always see which directory was read.

**…and byte order is the FALLBACK, because the caller can just say.** The host records the
directory it serves as `installPath` in `installed_plugins.json`, the same file `enabled` is
read out of. `versions` carries that in — `{"<plugin>@<marketplace>": "<version directory>"}`
— and where it names a plugin, the guess is not made. It is the same class of argument
`enabled` is and it exists for the same reason: the caller is the authority on its own host,
and this module still reads `root` and nothing else. Measured 2026-09-05: byte order picks
`unknown` for `frontend-design` on this machine where the host serves `1dd995193ba2`, so the
installed directory is thrown away as a duplicate — harmless only because all nine copies
happen to carry a byte-identical description, which is a fact about that plugin and not about
the rule.

**A version directory exists on disk, not in the skills that survived reading.** The
candidates are the directories spelled `<marketplace>/<plugin>/<version>/skills`, whatever is
under them. Choosing among the skills that came through `_load` and `_apply_enabled` instead
makes an EMPTY newer version invisible — it contributes no skill, so it is not a candidate,
and an older directory wins in silence with nothing in the document to say so. Measured
2026-09-05, both runtimes did exactly that and both agreed, which is why the differential
could not see it.

**A version directory that did not win yields two kinds of omission, and they are two subjects.**
A file whose name IS in the resolved version is a `duplicate-skill`: the operator is looking at
the right copy and the record says which stale one was skipped. A file whose name is NOT in the
resolved version is a `stale-version`: it exists on disk, it is not in any session's bill, and
nothing else in the document would say so. Folding the second into the first would inflate the
duplicate count by every skill a release removed and make the resurrection defect invisible —
which is exactly how it survived. `size` differs in meaning between them too: a duplicate's
bytes are already paid by the copy that stands in for it, a `stale-version`'s are paid by
nobody.

**Deterministic, because two runtimes have to agree about it.** This module reads `root` and
nothing else: no `~/.claude`, no transcripts, no clock. Call counts arrive in `usage` from the
caller, the switched-on plugins in `enabled`, and the served version directories in
`versions` — three facts about the host that a directory of files cannot answer.

**Nothing is dropped in silence.** Counted skills plus omissions account for every `SKILL.md`
found. An omission is `{subject, count, size, what}` — the discipline `docread.Omission` set,
with only the fields these five subjects can fill: there is no column to name and no second
count to carry, and inventing empty slots for them would make the record harder to read, not
more uniform. `size` is the description bytes the omission cost the catalogue, `0` where that
is not knowable (a file that would not decode, a block that would not parse).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from bantamkit.client import BantamError

# The file a skill IS. Case-sensitive: the host loads this name and so does this reader.
SKILL_FILE = "SKILL.md"

# The literal segment a plugin's skills live under. Part of the path shape below, spelled
# once so the shape check and the docstring cannot drift.
SKILLS_SEGMENT = "skills"

# `<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md` — six segments relative to the
# root. Any other shape is a skill outside a plugin.
PLUGIN_PATH_SEGMENTS = 6

# `<marketplace>/<plugin>/<version>/skills` — the first four of those segments, and the
# DIRECTORY that declares a version directory exists. Version resolution is over these, not
# over the files under them: a version directory that holds no readable `SKILL.md` still
# exists, and the host still serves it. See `_resolve_versions`.
VERSION_PATH_SEGMENTS = 4

# The subjects an `Omission` can carry. Stable tokens, because a renderer switches on them
# and a caller filters on them.
OMIT_NOT_ENABLED = "plugin-not-enabled"
OMIT_DUPLICATE = "duplicate-skill"
OMIT_STALE_VERSION = "stale-version"
OMIT_UNREADABLE = "unreadable-file"
OMIT_UNPARSED = "unparsed-frontmatter"

#: Reporting order for omissions. Fixed, so two runtimes emit the same document. The two
#: version subjects are adjacent because they are the two halves of one rule.
OMISSION_ORDER = (
    OMIT_NOT_ENABLED,
    OMIT_DUPLICATE,
    OMIT_STALE_VERSION,
    OMIT_UNREADABLE,
    OMIT_UNPARSED,
)

# The finding kinds. Severity is fixed per kind and is NOT an argument: a severity a caller
# can set is a severity that means something different in every report that carries it.
KIND_SHARED_PHRASE = "shared-trigger-phrase"
KIND_OVER_BUDGET = "catalogue-over-budget"
KIND_NEVER_INVOKED = "never-invoked"
KIND_FRONTMATTER = "frontmatter-malformed"
KIND_NAME_MISMATCH = "name-mismatch"

SEVERITY = {
    KIND_SHARED_PHRASE: "high",
    KIND_OVER_BUDGET: "high",
    KIND_NEVER_INVOKED: "low",
    KIND_FRONTMATTER: "medium",
    KIND_NAME_MISMATCH: "medium",
}

#: Reporting order for findings, and the order the contract lists them in.
FINDING_ORDER = (
    KIND_SHARED_PHRASE,
    KIND_OVER_BUDGET,
    KIND_NEVER_INVOKED,
    KIND_FRONTMATTER,
    KIND_NAME_MISMATCH,
)

#: `check` selects a FAMILY, not a kind: an operator asking about the bill wants both the
#: overage and the skills nobody ever called, and one asking about frontmatter wants both the
#: block that will not parse and the name that does not match its directory. Five kinds in
#: three families plus `all`, which is the default.
CHECK_FAMILIES = {
    "all": frozenset(FINDING_ORDER),
    "phrase": frozenset({KIND_SHARED_PHRASE}),
    "budget": frozenset({KIND_OVER_BUDGET, KIND_NEVER_INVOKED}),
    "frontmatter": frozenset({KIND_FRONTMATTER, KIND_NAME_MISMATCH}),
}

# The three ways frontmatter is malformed, as tokens rather than sentences. The first two
# also cost the skill its place in the count; the third does not.
BAD_NO_BLOCK = "no-frontmatter"
BAD_UNTERMINATED = "unterminated-frontmatter"
BAD_NO_DESCRIPTION = "no-description"

# The frontmatter delimiter, and the keys this reader consults. Every other key is parsed and
# ignored — parsing it is what makes `router: true` findable without a YAML dependency.
FRONTMATTER_FENCE = "---"
KEY_NAME = "name"
KEY_DESCRIPTION = "description"
KEY_ROUTER = "router"

# The values YAML spells `true` with. A `router:` carrying anything else is not a router.
TRUE_VALUES = frozenset({"true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"})

# The two characters a YAML scalar can be wrapped in whole. Order is the order a value is
# tested in and cannot matter: a value opens with at most one of them.
SCALAR_QUOTES = ('"', "'")

# The escape character inside a DOUBLE-quoted scalar, and the only two sequences this reader
# resolves — `\"` for a quote and `\\` for a backslash. Every other `\x` is left as written,
# because inventing YAML's full escape table is a second thing two runtimes would have to
# agree about character for character, and no `SKILL.md` frontmatter uses one.
BACKSLASH = "\\"
DOUBLE_ESCAPES = frozenset({'"', BACKSLASH})


class SkillAuditError(BantamError):
    """The audit could not be run at all: the message names what was seen at `root`.

    Reserved for a failure of the SCAN. A file that will not decode, a block that will not
    parse and a plugin that is switched off are all recorded as omissions and counted, never
    raised: an audit that refuses because one of twenty-six files is malformed has told the
    operator nothing about the other twenty-five.
    """


@dataclass(frozen=True)
class Omission:
    """A `SKILL.md` that was found and not counted, as a COUNT and the fact behind it.

    - `subject` — one of the `OMIT_*` tokens above.
    - `count` — how many files. Never an estimate.
    - `size` — the UTF-8 description bytes those files would have added to the catalogue;
      `0` when that is not knowable, which is exactly the two cases where the description
      could not be read at all.
    - `what` — the paths, relative to the root, in scan order. What a caller needs to act on
      the omission rather than merely be told it happened.
    """

    subject: str
    count: int
    size: int = 0
    what: str = ""

    def as_dict(self) -> dict:
        return {"subject": self.subject, "count": self.count, "size": self.size, "what": self.what}


@dataclass(frozen=True)
class Finding:
    """One thing wrong with the catalogue.

    `severity` is not stored independently — it is `SEVERITY[kind]`, fixed per kind. `detail`
    is a machine fact and not a sentence: the phrase that collided, the arithmetic of the
    overage, the token naming which of three frontmatter failures it was, the frontmatter
    name that does not match. Wording for a person is Layer 2's job, not this module's.
    """

    kind: str
    skills: tuple[str, ...]
    detail: str

    @property
    def severity(self) -> str:
        return SEVERITY[self.kind]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "skills": list(self.skills),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Audit:
    """The whole answer. `skills` plus every omission's `count` is every `SKILL.md` found."""

    roots: tuple[str, ...]
    skills: int
    catalogue_bytes: int
    findings: tuple[Finding, ...] = ()
    omissions: tuple[Omission, ...] = ()

    def as_dict(self) -> dict:
        return {
            "roots": list(self.roots),
            "skills": self.skills,
            "catalogue_bytes": self.catalogue_bytes,
            "findings": [f.as_dict() for f in self.findings],
            "omissions": [o.as_dict() for o in self.omissions],
        }

    def as_json(self) -> str:
        """Two-space indent and no ASCII escaping, so `JSON.stringify(doc, null, 2)` in the
        Node port produces the same bytes and a conformance case can compare them."""
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)


@dataclass
class _Skill:
    """One `SKILL.md` as it was found, before anything has been decided about it."""

    relpath: str
    directory: str
    marketplace: str = ""
    plugin: str = ""
    version: str = ""
    description: str = ""
    name: str = ""
    router: bool = False
    #: `None` while the file is still a candidate; one of the `OMIT_*` tokens once it is not.
    omitted: str | None = None
    #: `BAD_*` when the frontmatter is malformed, `None` when it is not.
    malformed: str | None = None
    phrases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def in_plugin(self) -> bool:
        return bool(self.plugin)

    @property
    def id(self) -> str:
        """`<plugin>:<name>` — the spelling the host uses and the key `usage` is looked up by.

        `<name>` alone for a skill outside a plugin. The name is always the DIRECTORY's, never
        the frontmatter's: the host loads by directory, so a frontmatter `name:` that disagrees
        is the thing that is wrong (`name-mismatch`) rather than a second identity.
        """
        return f"{self.plugin}:{self.directory}" if self.in_plugin else self.directory

    @property
    def plugin_id(self) -> str:
        """`<plugin>@<marketplace>`, the way settings.json spells an enabled plugin."""
        return f"{self.plugin}@{self.marketplace}"

    @property
    def plugin_key(self) -> tuple[str, str]:
        """The unit ONE version directory is resolved for. A skill outside a plugin keys on
        two empty strings, so every such skill shares one group whose resolved version is the
        empty string — which keeps them all, because none of them has a version at all."""
        return (self.marketplace, self.plugin)

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        return (self.marketplace, self.plugin, self.directory)

    @property
    def bytes(self) -> int:
        return len(self.description.encode("utf-8"))


def _relative_parts(path: Path, root: Path) -> list[str]:
    return list(path.relative_to(root).parts)


def _scan_tree(root: Path) -> tuple[list[Path], list[tuple[str, str, str]]]:
    """One walk, two answers: every `SKILL.md` under `root`, and every VERSION DIRECTORY.

    `os.walk` yields directory entries in whatever order the filesystem hands them over, and
    two machines hand them over differently. Sorting is what makes the scan order — and
    therefore the omission `what` lists and the duplicate tie-break's "last wins" — the same
    everywhere. `followlinks` stays off: a symlink loop is not a skill catalogue.

    THE SECOND ANSWER IS WHY THIS FUNCTION IS NOT JUST A FILE LIST. A version directory
    declares itself by holding a `skills/` directory — `<marketplace>/<plugin>/<version>/
    skills`, the first four segments of the path shape a skill has — and it declares itself
    whether or not anything under it can be read. Resolving over the files instead makes an
    EMPTY newer version invisible, so an older directory wins in silence; see
    `_resolve_versions`. A directory reached by following a symlink is not walked into on
    either runtime, so it declares nothing on either.
    """
    found: list[Path] = []
    versions: list[tuple[str, str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=None):
        dirnames.sort()
        parts = _relative_parts(Path(dirpath), root)
        if len(parts) == VERSION_PATH_SEGMENTS and parts[3] == SKILLS_SEGMENT:
            versions.append((parts[0], parts[1], parts[2]))
        if SKILL_FILE in filenames:
            found.append(Path(dirpath) / SKILL_FILE)
    found.sort(key=lambda p: p.parts)
    versions.sort()
    return found, versions


def _walk(root: Path) -> list[Path]:
    """Every `SKILL.md` under `root`, in a fixed order. `_scan_tree`'s first answer."""
    return _scan_tree(root)[0]


def _scalar_close(value: str, quote: str) -> int:
    """Index of the quote that CLOSES a scalar opened at index 0, or `-1` when none does.

    YAML has exactly two escape rules for this and this reader implements exactly two: inside a
    `"` scalar a backslash escapes whatever follows it, so `\\"` does not close; inside a `'`
    scalar a doubled `''` is one literal apostrophe, so it does not close either. A quote that
    is never closed returns `-1`, which is what makes an unterminated value a literal.
    """
    index = 1
    while index < len(value):
        char = value[index]
        if quote == '"' and char == BACKSLASH:
            index += 2
            continue
        if char == quote:
            if quote == "'" and value[index + 1 : index + 2] == quote:
                index += 2
                continue
            return index
        index += 1
    return -1


def _unescape(content: str, quote: str) -> str:
    """The content of a quoted scalar as the host's parser would hand it over.

    Only the escapes `_scalar_close` honours are resolved, so the two functions cannot disagree
    about what was inside the scalar and what closed it.
    """
    if quote == "'":
        return content.replace("''", "'")
    out: list[str] = []
    index = 0
    while index < len(content):
        char = content[index]
        if char == BACKSLASH and content[index + 1 : index + 2] in DOUBLE_ESCAPES:
            out.append(content[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def unwrap_scalar(value: str) -> str:
    """A whole-value quoted YAML scalar without its quotes; every other value unchanged.

    `"Use when a test is \\"flaky in prod\\""` is one scalar and unwraps. `"a" and "b"` opens
    and ends with `"` and is NOT one — its first quote closes at index 2 — so it is left alone
    and both of its phrases survive. `"never closed` never closes and is left alone too.
    """
    for quote in SCALAR_QUOTES:
        if len(value) < 2 or not value.startswith(quote):
            continue
        if _scalar_close(value, quote) == len(value) - 1:
            return _unescape(value[1:-1], quote)
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str | None]:
    """The `---` block as a flat mapping, or `None` and the token saying why not.

    A deliberately small subset of YAML, and the smallness is the point: the alternative is a
    parser dependency that the Node half would have to match bug for bug. What is supported is
    what a `SKILL.md` frontmatter actually uses — top-level `key: value` pairs, and a value
    FOLDED over following indented lines, which is joined with single spaces the way YAML's
    folded scalar is. A line that is neither ends the fold and is skipped.

    A leading BOM is stripped before the first line is examined: an editor that writes one has
    not thereby made the file's frontmatter malformed.

    Every value is unwrapped once the block closes, AFTER the fold and never during it: a
    scalar quoted whole may be folded over several lines, so its closing quote is not known
    until the last of them has been joined on. Unwrapping happens here rather than at
    `description:` alone because it is a fact about YAML scalars — `name: "s"` is the name `s`
    and `router: "true"` is a router — and one rule in one place is one rule for the Node half
    to port.
    """
    if text.startswith("﻿"):
        text = text[1:]
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return None, BAD_NO_BLOCK
    fields: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_FENCE:
            return {key: unwrap_scalar(value) for key, value in fields.items()}, None
        if not line.strip():
            current = None
            continue
        if line[:1].isspace():
            if current is not None:
                joined = f"{fields[current]} {line.strip()}".strip()
                fields[current] = joined
            continue
        key, sep, value = line.partition(":")
        if not sep or not key or key.strip() != key:
            current = None
            continue
        current = key
        fields[key] = value.strip()
    return None, BAD_UNTERMINATED


def _is_letter(text: str, index: int) -> bool:
    return 0 <= index < len(text) and text[index].isalpha()


def _delimiters(text: str, quote: str) -> list[int]:
    """The positions where `quote` opens or closes a phrase.

    `"` always delimits. `'` delimits only where it is not flanked by letters on BOTH sides,
    which is what separates `'race condition'` from `don't`. Measured on the fixture tree: the
    naive rule reports a third `shared-trigger-phrase` over the junk string between two
    contractions, so this is the one line that separates a correct reader from a plausible one.
    """
    positions = []
    for index, char in enumerate(text):
        if char != quote:
            continue
        if quote == "'" and _is_letter(text, index - 1) and _is_letter(text, index + 1):
            continue
        positions.append(index)
    return positions


def _has_content(phrase: str) -> bool:
    """A phrase with no letter and no digit in it is not a trigger phrase.

    `" - "` between two quoted phrases is punctuation; reporting two skills that both use a
    dash as a collision is the metric failing, not a finding.
    """
    return any(ch.isalnum() for ch in phrase)


def phrases(text: str) -> tuple[str, ...]:
    """Every literal quoted phrase in `text`, in order, deduplicated.

    Delimiters are paired sequentially — first with second, third with fourth — per quote
    character, and an unpaired trailing delimiter opens nothing.
    """
    found: list[str] = []
    for quote in ('"', "'"):
        positions = _delimiters(text, quote)
        for i in range(0, len(positions) - 1, 2):
            phrase = text[positions[i] + 1 : positions[i + 1]]
            if _has_content(phrase) and phrase not in found:
                found.append(phrase)
    return tuple(found)


def _load(path: Path, root: Path) -> _Skill:
    """One file read, decoded and parsed. Every failure lands in a field, none of them raise."""
    parts = _relative_parts(path, root)
    relpath = "/".join(parts)
    skill = _Skill(relpath=relpath, directory=parts[-2] if len(parts) > 1 else path.parent.name)
    if len(parts) == PLUGIN_PATH_SEGMENTS and parts[3] == SKILLS_SEGMENT:
        skill.marketplace, skill.plugin, skill.version = parts[0], parts[1], parts[2]
    try:
        text = path.read_bytes().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        # A byte no strict decoder accepts. NOT repaired with `U+FFFD` and not skipped in
        # silence: what the catalogue would have paid for it is unknowable, so `size` is 0 and
        # the path is the record.
        skill.omitted = OMIT_UNREADABLE
        return skill
    fields, bad = _parse_frontmatter(text)
    if fields is None:
        skill.omitted = OMIT_UNPARSED
        skill.malformed = bad
        return skill
    skill.name = fields.get(KEY_NAME, "")
    skill.router = fields.get(KEY_ROUTER, "") in TRUE_VALUES
    if KEY_DESCRIPTION not in fields:
        # The block parses and carries no description. This one IS a skill — the host loads
        # nothing from it per session, so it costs zero bytes — and the operator is still told.
        skill.malformed = BAD_NO_DESCRIPTION
        return skill
    skill.description = fields[KEY_DESCRIPTION]
    skill.phrases = phrases(skill.description)
    return skill


def _apply_enabled(found: list[_Skill], enabled: list[str] | None) -> None:
    """Switch off every skill under a plugin the host does not have enabled.

    `enabled` omitted means every skill counts; `enabled` given and EMPTY means no plugin is
    on, which is a real state and not the same thing. A skill outside a plugin is never
    excluded here: a plugin list cannot speak to a skill that belongs to no plugin, and
    dropping one would under-report a personal skills directory by every file in it.
    """
    if enabled is None:
        return
    allowed = frozenset(enabled)
    for skill in found:
        if skill.omitted is None and skill.in_plugin and skill.plugin_id not in allowed:
            skill.omitted = OMIT_NOT_ENABLED


def _resolve_versions(
    found: list[_Skill],
    version_dirs: list[tuple[str, str, str]],
    versions: dict[str, str] | None = None,
) -> None:
    """Resolve ONE version directory per (marketplace, plugin), and omit every other one.

    This runs BEFORE `_apply_dedupe` and it is the whole fix for the resurrection defect: the
    winning version's skills are the plugin's skills, and a name absent from it is absent. It
    is never merged in from another directory, however many versions of the plugin the cache
    still holds. See the module docstring for the measurement that forced this.

    The winner is the version directory name that sorts LAST in byte order. The loser's
    subject depends on whether the resolved version has a skill of the same name to stand in
    for it — `duplicate-skill` when it does, `stale-version` when it does not.

    **THE CANDIDATES ARE DIRECTORIES ON DISK, NOT SURVIVING SKILLS.** This function used to
    choose the winner from the skills that had already come through `_load` and
    `_apply_enabled`, which is the resurrection defect arriving through the other door: a
    version directory holding no `SKILL.md` at all, or only files that would not decode or
    would not parse, contributed no skill, so it was never a candidate and an OLDER directory
    won in silence — no omission, no finding, and no mention anywhere in the document of the
    directory the host is actually serving. Measured 2026-09-05 with `mk/kit/2.0.0/skills/`
    empty beside a populated `1.0.0`: both runtimes answered from `1.0.0` and said nothing.
    They agreed, so the differential could not see it either. `version_dirs` comes from
    `_scan_tree` and names every directory that exists, whatever is under it.

    The losing case is then visible where every other skipped file already is: each skill
    under a directory that did not win gets an omission record, and when the winner serves
    nothing at all every one of them is a `stale-version` — which is the honest reading. They
    are on disk, they are in nobody's bill, and the plugin's counted skills are zero.

    **`versions` IS HOST TRUTH AND IT OVERRIDES THE BYTE ORDER.** Byte order is total, free
    and identical on two runtimes, and it is still a GUESS — `10.0.0` loses to `9.0.0`, and
    among names that are not versions the winner is arbitrary. The host does not guess: it
    records the directory it serves as `installPath` in `installed_plugins.json`, in the same
    file the caller already reads `enabled` out of. So a caller that knows may say so, keyed
    the way `enabled` is keyed, and this function stops guessing for that plugin. Measured
    2026-09-05 on this machine: byte order picks `unknown` for `frontend-design` where the
    host serves `1dd995193ba2`, and the installed directory is discarded as a duplicate —
    harmless only because all nine copies carry a byte-identical description.

    An entry naming a plugin with no version directory under `root` does nothing: there is
    nothing to resolve. An entry naming a directory that is not there resolves to it anyway
    and every directory that IS there loses, which is the honest answer — the host serves a
    directory this root does not hold, so this root serves none of that plugin's skills, and
    every file it does hold is named in a `stale-version` record. Neither is a refusal, for
    the reason `enabled` does not refuse an unknown plugin id either: the caller is the
    authority on its own host, and this tool reads `root` and nothing else.

    A skill outside a plugin keys on `("", "")` with an empty version, so every one of them is
    in the resolved version by construction and none is ever omitted here. No real path can
    produce that key — every path segment is non-empty — so it is seeded rather than found,
    and it is skipped by the override loop because it names no plugin.
    """
    resolved: dict[tuple[str, str], str] = {("", ""): ""}
    for marketplace, plugin, version in version_dirs:
        held = resolved.get((marketplace, plugin))
        if held is None or version > held:
            resolved[(marketplace, plugin)] = version
    named = versions or {}
    for marketplace, plugin in list(resolved):
        if not plugin:
            continue
        told = named.get(f"{plugin}@{marketplace}")
        if told is not None:
            resolved[(marketplace, plugin)] = told
    # The names the resolved version actually SERVES, which is a different question from
    # which directory won: a winner whose files were all unreadable, unparsable or switched
    # off serves nothing and is in no entry here. `.get(..., set())` below is that case, and
    # it is the one this function used to be unable to reach at all.
    kept: dict[tuple[str, str], set[str]] = {}
    for skill in found:
        if skill.omitted is None and skill.version == resolved[skill.plugin_key]:
            kept.setdefault(skill.plugin_key, set()).add(skill.directory)
    for skill in found:
        if skill.omitted is not None or skill.version == resolved[skill.plugin_key]:
            continue
        stands_in = skill.directory in kept.get(skill.plugin_key, set())
        skill.omitted = OMIT_DUPLICATE if stands_in else OMIT_STALE_VERSION


def _apply_dedupe(found: list[_Skill]) -> None:
    """One skill per (marketplace, plugin, name) INSIDE the resolved version; last one wins.

    Only reachable for skills outside a plugin: inside one version directory a name is a
    directory name and the filesystem has already made it unique. Two files claiming the same
    bare name are still a duplicate, and saying so is better than counting a personal skill
    twice. Scan order decides, which is path order and therefore the same on both runtimes.
    """
    winners: dict[tuple[str, str, str], _Skill] = {}
    for skill in found:
        if skill.omitted is not None:
            continue
        held = winners.get(skill.dedupe_key)
        if held is not None:
            held.omitted = OMIT_DUPLICATE
        winners[skill.dedupe_key] = skill


def _scan(
    root: str | Path,
    enabled: list[str] | None = None,
    versions: dict[str, str] | None = None,
) -> list[_Skill]:
    """The scan, decided but not yet reported: every `SKILL.md` found, with `enabled`, the
    version resolution and the dedupe already applied.

    One seam rather than four calls in a fixed order, because the order IS the rule — the
    version resolution has to run after `enabled` and before the dedupe — and a caller that
    reproduces it by hand can get it wrong, or can miss an argument the four grow later.
    `runtime-ts/src/skillaudit.ts` exports the same seam under the same name for the same
    reason: the per-skill byte table is the only oracle that separates a headline that is
    right from one that is right for two cancelling reasons.
    """
    base = Path(root)
    files, version_dirs = _scan_tree(base)
    found = [_load(path, base) for path in files]
    _apply_enabled(found, enabled)
    _resolve_versions(found, version_dirs, versions)
    _apply_dedupe(found)
    return found


def _shared_phrase_findings(counted: list[_Skill]) -> list[Finding]:
    """Phrases held by two or more skills. Routers are not in this index at all."""
    index: dict[str, list[str]] = {}
    for skill in counted:
        if skill.router:
            continue
        for phrase in skill.phrases:
            holders = index.setdefault(phrase, [])
            if skill.id not in holders:
                holders.append(skill.id)
    return [
        Finding(KIND_SHARED_PHRASE, tuple(sorted(holders)), phrase)
        for phrase, holders in sorted(index.items())
        if len(holders) > 1
    ]


def _omission_records(found: list[_Skill]) -> list[Omission]:
    """One record per subject, carrying the count, the bytes and the paths."""
    records = []
    for subject in OMISSION_ORDER:
        members = [s for s in found if s.omitted == subject]
        if not members:
            continue
        records.append(
            Omission(
                subject=subject,
                count=len(members),
                size=sum(s.bytes for s in members),
                what=", ".join(s.relpath for s in members),
            )
        )
    return records


def audit(
    root: str | Path,
    enabled: list[str] | None = None,
    usage: dict[str, int] | None = None,
    check: str = "all",
    budget: int | None = None,
    versions: dict[str, str] | None = None,
) -> Audit:
    """Walk `root` and answer the whole audit.

    `usage` omitted is not the same as `usage` empty. An empty map is a measurement saying
    nothing was called; an absent map is no measurement at all, and reporting every skill as
    `never-invoked` on the strength of it would be an assertion about data this tool was never
    given. So `never-invoked` fires only when `usage` is supplied — the same discipline
    `catalogue-over-budget` follows for `budget`, and for the same reason.

    `versions` is the same kind of argument `enabled` is: HOST TRUTH the caller supplies
    rather than a fact this tool can read off `root`. It names, per `<plugin>@<marketplace>`,
    the version directory the host actually serves; a plugin absent from it falls back to the
    byte order, which is deterministic and — among names that are not versions — arbitrary.
    See `_resolve_versions`.

    `skills`, `catalogue_bytes` and `omissions` are reported whatever `check` says: they are
    the measurement, and `check` selects which family of FINDINGS is worth reporting on top
    of it.
    """
    if check not in CHECK_FAMILIES:
        raise SkillAuditError(
            f"unknown check {check!r}; this tool checks: {', '.join(sorted(CHECK_FAMILIES))}"
        )
    if budget is not None and budget < 0:
        raise SkillAuditError(f"budget must not be negative; got {budget}")
    base = Path(root)
    if not base.exists():
        raise SkillAuditError(f"no such directory: {root}")
    if not base.is_dir():
        raise SkillAuditError(f"{root} is a file, not a directory of skills")

    found = _scan(base, enabled, versions)
    counted = [s for s in found if s.omitted is None]
    catalogue_bytes = sum(s.bytes for s in counted)

    wanted = CHECK_FAMILIES[check]
    findings: list[Finding] = []
    if KIND_SHARED_PHRASE in wanted:
        findings.extend(_shared_phrase_findings(counted))
    if KIND_OVER_BUDGET in wanted and budget is not None and catalogue_bytes > budget:
        over = catalogue_bytes - budget
        detail = f"{catalogue_bytes} > {budget}, over by {over}"
        findings.append(Finding(KIND_OVER_BUDGET, (), detail))
    if KIND_NEVER_INVOKED in wanted and usage is not None:
        findings.extend(
            Finding(KIND_NEVER_INVOKED, (skill.id,), "0 calls")
            for skill in sorted(counted, key=lambda s: s.id)
            if usage.get(skill.id, 0) == 0
        )
    if KIND_FRONTMATTER in wanted:
        findings.extend(
            Finding(KIND_FRONTMATTER, (skill.id,), skill.malformed)
            for skill in sorted(found, key=lambda s: s.id)
            if skill.malformed is not None
        )
    if KIND_NAME_MISMATCH in wanted:
        findings.extend(
            Finding(KIND_NAME_MISMATCH, (skill.id,), skill.name)
            for skill in sorted(counted, key=lambda s: s.id)
            if skill.name and skill.name != skill.directory
        )
    findings.sort(key=lambda f: FINDING_ORDER.index(f.kind))

    return Audit(
        roots=(str(root),),
        skills=len(counted),
        catalogue_bytes=catalogue_bytes,
        findings=tuple(findings),
        omissions=tuple(_omission_records(found)),
    )
