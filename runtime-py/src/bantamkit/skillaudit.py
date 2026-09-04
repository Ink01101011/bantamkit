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

**Deterministic, because two runtimes have to agree about it.** This module reads `root` and
nothing else: no `~/.claude`, no transcripts, no clock. Call counts arrive in `usage` from the
caller. The duplicate tie-break is a BYTE-ORDER comparison of the version directory name and
deliberately not a semver comparison — `10.0.0` therefore loses to `9.0.0`, which is wrong and
is disclosed in the omission record rather than fixed, because a semver comparison is a second
thing the Python and Node halves would have to agree about character for character.

**Nothing is dropped in silence.** Counted skills plus omissions account for every `SKILL.md`
found. An omission is `{subject, count, size, what}` — the discipline `docread.Omission` set,
with only the fields these four subjects can fill: there is no column to name and no second
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

# The subjects an `Omission` can carry. Stable tokens, because a renderer switches on them
# and a caller filters on them.
OMIT_NOT_ENABLED = "plugin-not-enabled"
OMIT_DUPLICATE = "duplicate-skill"
OMIT_UNREADABLE = "unreadable-file"
OMIT_UNPARSED = "unparsed-frontmatter"

#: Reporting order for omissions. Fixed, so two runtimes emit the same document.
OMISSION_ORDER = (OMIT_NOT_ENABLED, OMIT_DUPLICATE, OMIT_UNREADABLE, OMIT_UNPARSED)

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
    raised: an audit that refuses because one of sixteen files is malformed has told the
    operator nothing about the other fifteen.
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
    def dedupe_key(self) -> tuple[str, str, str]:
        return (self.marketplace, self.plugin, self.directory)

    @property
    def bytes(self) -> int:
        return len(self.description.encode("utf-8"))


def _relative_parts(path: Path, root: Path) -> list[str]:
    return list(path.relative_to(root).parts)


def _walk(root: Path) -> list[Path]:
    """Every `SKILL.md` under `root`, in a fixed order.

    `os.walk` yields directory entries in whatever order the filesystem hands them over, and
    two machines hand them over differently. Sorting in place is what makes the scan order —
    and therefore the omission `what` lists and the duplicate tie-break's "last wins" — the
    same everywhere. `followlinks` stays off: a symlink loop is not a skill catalogue.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=None):
        dirnames.sort()
        if SKILL_FILE in filenames:
            found.append(Path(dirpath) / SKILL_FILE)
    found.sort(key=lambda p: p.parts)
    return found


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


def _apply_dedupe(found: list[_Skill]) -> None:
    """One skill per (marketplace, plugin, name); the LAST version directory in byte order wins.

    Byte order and deliberately not semver — see the module docstring. A skill outside a plugin
    has no version, so its key sorts on an empty string and scan order decides; two files
    claiming the same bare name are still a duplicate, and saying so is better than counting a
    personal skill twice.
    """
    winners: dict[tuple[str, str, str], _Skill] = {}
    for skill in found:
        if skill.omitted is not None:
            continue
        held = winners.get(skill.dedupe_key)
        if held is None:
            winners[skill.dedupe_key] = skill
            continue
        loser, winner = (held, skill) if skill.version >= held.version else (skill, held)
        loser.omitted = OMIT_DUPLICATE
        winners[skill.dedupe_key] = winner


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
) -> Audit:
    """Walk `root` and answer the whole audit.

    `usage` omitted is not the same as `usage` empty. An empty map is a measurement saying
    nothing was called; an absent map is no measurement at all, and reporting every skill as
    `never-invoked` on the strength of it would be an assertion about data this tool was never
    given. So `never-invoked` fires only when `usage` is supplied — the same discipline
    `catalogue-over-budget` follows for `budget`, and for the same reason.

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

    found = [_load(path, base) for path in _walk(base)]
    _apply_enabled(found, enabled)
    _apply_dedupe(found)
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
