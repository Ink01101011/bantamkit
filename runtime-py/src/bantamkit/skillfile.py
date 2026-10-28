"""The Agent Skills file (#206, X9): parse, validate, hash, render, atomic write, undo.

A skill bantamkit writes is a directory in the open Agent Skills format from its first
byte, so a later promotion to a native link needs no conversion:

    <name>/
    ├── SKILL.md            frontmatter `name`, `description`, `metadata` (strings only)
    └── references/
        ├── evidence.md
        └── history/v<n>.md every earlier SKILL.md (`history_add`)

Everything here is a pure function of its arguments, plus the directory writes, which are
build-in-temp-then-rename so a crash never leaves half a skill at its final path. Time
enters only as the `now` stamp a caller passes (`storage.retention.parse_now`'s format).
`runtime-ts/src/skillfile.ts` is the port; `tools/conformance/suites/skill-file.mjs`
compares the two byte for byte.

THE HASH (plan reading R8). `metadata.bantamkit-sha256` is SHA-256 over the SKILL.md text
with the value of every `bantamkit-sha256:` line inside the frontmatter replaced by `""`.
A recomputed hash that differs from the stored one means a person edited the file, and an
edited skill is never changed automatically again. CRLF is read as LF before hashing, so a
checkout that converts line endings is not an edit.

THE FRONTMATTER READER is the memory store's (`yaml.safe_load` + `well_formed_frontmatter`
here, `parseFrontmatter` in the port). Any frontmatter either reader cannot take as a
mapping is refused with ONE sentence on both sides, because the two readers' own error
texts differ (registered in `runtime-ts/src/memory/factfile.ts`).
What the port's reader refuses wherever it stands (a flow mapping such as `metadata: {}`, an
anchor, an alias, a tag, a directive) is refused here too, from PyYAML's own tokens (job73 C8).
One shape is RULED different (`docs/porting.md`, row `skillfile`): a `metadata:` value nested
below one level is read here and named by `validate`, and refused by the port's reader (#120).
Both refuse the skill.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from bantamkit.memory.store import well_formed, well_formed_frontmatter
from bantamkit.storage.lock import exclusive
from bantamkit.storage.retention import parse_now

NAME_MAX = 64
DESC_MAX = 1024
BODY_MAX_LINES = 500
GENERIC_NAMES = ("helper", "helpers", "util", "utils")
HASH_KEY = "bantamkit-sha256"
KEY_PREFIX = "bantamkit-"
SKILL_FILE = "SKILL.md"
ABSENT_MARKER = ".bantamkit-absent"
STATE_NAME = "skills-state.json"
STATE_VERSION = 1

_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# A plain YAML key the port's reader takes (`factfile.ts` `parseFrontmatter`).
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
# PyYAML resolves these plain words to a bool or null, so a name spelled so is quoted.
_PLAIN_WORDS = ("yes", "no", "on", "off", "true", "false", "null")
_HASH_LINE = re.compile(r"[ \t]*bantamkit-sha256:")
_HEADING_BREAK = re.compile(r"#{1,2}(?:[ \t]|$)")
_BACKUP_NAME = re.compile(r"(\d{8}T\d{6}\.\d{3}Z)(?:-(\d+))?")
#: The YAML the port's frontmatter reader (#120) refuses wherever it stands: a flow mapping,
#: an anchor, an alias, a tag, a directive. PyYAML reads every one, so a SKILL.md holding one
#: would pass `validate` here and be refused there (`metadata: {}` is the shape a model
#: writes). Refused here too, with the same sentence, by the scanner's own tokens: a `{`
#: inside a quoted or plain scalar is no token and is read as text on both sides.
_PORT_REFUSES = (
    yaml.FlowMappingStartToken,
    yaml.AnchorToken,
    yaml.AliasToken,
    yaml.TagToken,
    yaml.DirectiveToken,
)

#: One counter per process: a temp name is `<target>.<kind>-<pid>-<n>`, never random, so a
#: retry is reproducible and two writers in one process never share a temp.
_counter = itertools.count(1)


class SkillFileError(ValueError):
    """A skill file or directory is not what it must be; the message is the sentence."""


@dataclass
class SkillDoc:
    name: str
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)
    body: str = ""


# ---------------------------------------------------------------------------- parse


def parse_skill(text: str) -> SkillDoc:
    """A `SkillDoc` from SKILL.md text; `SkillFileError` when it has no X9 shape at all.

    `validate` judges the rules; this only refuses what cannot be a skill file: no
    frontmatter, a frontmatter that is not a mapping, a name or description that is not a
    string, a metadata that is not a mapping.
    """
    text = _lf(text)
    if text.startswith("﻿"):
        text = text[1:]
    parts = text.split("---\n", 2)
    if len(parts) != 3 or parts[0] != "":
        raise SkillFileError("SKILL.md has no frontmatter at the top of the file")
    front = parts[1]
    try:
        if any(isinstance(t, _PORT_REFUSES) for t in yaml.scan(front, Loader=yaml.SafeLoader)):
            raise SkillFileError("SKILL.md frontmatter is not a readable mapping")
        meta = well_formed_frontmatter(front, yaml.safe_load(front))
    except yaml.YAMLError as e:
        raise SkillFileError("SKILL.md frontmatter is not a readable mapping") from e
    if meta is None:
        meta = {}
    if not isinstance(meta, dict) or not all(isinstance(k, str) for k in meta):
        raise SkillFileError("SKILL.md frontmatter is not a readable mapping")
    name = meta.get("name")
    if not isinstance(name, str):
        raise SkillFileError("SKILL.md has no string name")
    description = meta.get("description")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise SkillFileError("SKILL.md description is not a string")
    metadata = meta.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict) or not all(isinstance(k, str) for k in metadata):
        raise SkillFileError("SKILL.md metadata is not a mapping")
    return SkillDoc(
        name=name, description=description, metadata=dict(metadata), body=parts[2].strip()
    )


def body_lines(body: str) -> int:
    """Lines in a (stripped) body; an empty body has none."""
    return 0 if body == "" else body.count("\n") + 1


def has_steps(body: str) -> bool:
    """A `## Steps` heading followed by at least one non-blank line before the next `#`/`##`."""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.rstrip(" \t") != "## Steps":
            continue
        for nxt in lines[i + 1 :]:
            if _HEADING_BREAK.match(nxt):
                return False
            if nxt.strip(" \t"):
                return True
        return False
    return False


def validate(doc: SkillDoc, dirname: str | None = None) -> list[str]:
    """Every broken X9 rule, in a fixed order, one fixed sentence each; `[]` is valid."""
    out: list[str] = []
    name = doc.name
    if len(name) > NAME_MAX or _NAME_RE.fullmatch(name) is None:
        out.append(
            f"name {name!r} must be 1-{NAME_MAX} characters of a-z, 0-9 and single inner hyphens"
        )
    elif name in GENERIC_NAMES:
        out.append(f"name {name!r} is a generic word; name the action instead")
    if dirname is not None and dirname != name:
        out.append(f"name {name!r} does not match its directory {dirname!r}")
    if len(doc.description) > DESC_MAX:
        out.append(f"description is {len(doc.description)} characters; at most {DESC_MAX}")
    n = body_lines(doc.body)
    if n > BODY_MAX_LINES:
        out.append(f"body is {n} lines; at most {BODY_MAX_LINES}")
    for key in sorted(doc.metadata):
        if not isinstance(doc.metadata[key], str):
            out.append(f"metadata {key} must be a string")
    if not has_steps(doc.body):
        out.append("## Steps is missing or empty")
    return out


# ----------------------------------------------------------------------------- hash


def canonical_hash(text: str) -> str:
    """SHA-256 hex over `text` with every frontmatter `bantamkit-sha256:` value blanked (R8)."""
    text = well_formed(_lf(text))
    parts = text.split("---\n", 2)
    if len(parts) == 3 and parts[0] in ("", "﻿"):
        lines = parts[1].split("\n")
        for i, line in enumerate(lines):
            m = _HASH_LINE.match(line)
            if m is not None:
                lines[i] = m.group(0) + ' ""'
        text = parts[0] + "---\n" + "\n".join(lines) + "---\n" + parts[2]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_edited(text: str) -> bool:
    """True when the stored hash is missing or differs from the recomputed one."""
    try:
        stored = parse_skill(text).metadata.get(HASH_KEY)
    except SkillFileError:
        return True
    return not isinstance(stored, str) or stored != canonical_hash(text)


def stamp(text: str, metadata_updates: dict[str, str]) -> str:
    """`text` re-rendered with `metadata_updates` set, then its hash restamped.

    The result is the X9 shape `render` writes: top-level keys other than `name`,
    `description` and `metadata` are not carried (bantamkit stamps only what it wrote).
    """
    doc = parse_skill(text)
    for key in sorted(metadata_updates):
        if not key.startswith(KEY_PREFIX):
            raise SkillFileError(f"metadata key {key!r} is not a {KEY_PREFIX} key")
        if not isinstance(metadata_updates[key], str):
            raise SkillFileError(f"metadata {key} must be a string")
    metadata = {**doc.metadata, **metadata_updates, HASH_KEY: ""}
    draft = SkillDoc(doc.name, doc.description, metadata, doc.body)
    metadata[HASH_KEY] = canonical_hash(render(draft))
    return render(draft)


# --------------------------------------------------------------------------- render


def yaml_quote(s: str) -> str:
    """A YAML double-quoted scalar on one line that PyYAML and the port both read back as `s`.

    JSON's escapes plus `\\uXXXX` for every character PyYAML's reader refuses or folds raw
    (DEL, C1 including NEL, U+2028/U+2029, U+FEFF, U+FFFE/U+FFFF, a lone surrogate).
    """
    out = ['"']
    for ch in s:
        o = ord(ch)
        esc = _ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif o < 0x20 or 0x7F <= o <= 0x9F or o in _ESCAPED or 0xD800 <= o <= 0xDFFF:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\n": "\\n",
    "\t": "\\t",
    "\r": "\\r",
    "\b": "\\b",
    "\f": "\\f",
}
_ESCAPED = frozenset((0x2028, 0x2029, 0xFEFF, 0xFFFE, 0xFFFF))


def _name_scalar(name: str) -> str:
    plain = (
        _NAME_RE.fullmatch(name) is not None and "a" <= name[0] <= "z" and name not in _PLAIN_WORDS
    )
    return name if plain else yaml_quote(name)


def render(doc: SkillDoc) -> str:
    """SKILL.md text: `name`, `description`, `metadata` (keys sorted, values double-quoted),
    one blank line, the body, a trailing newline."""
    lines = [
        "---",
        f"name: {_name_scalar(doc.name)}",
        f"description: {yaml_quote(doc.description)}",
    ]
    if doc.metadata:
        lines.append("metadata:")
        for key in sorted(doc.metadata):
            value = doc.metadata[key]
            if _KEY_RE.fullmatch(key) is None:
                raise SkillFileError(f"metadata key {key!r} cannot be written")
            if not isinstance(value, str):
                raise SkillFileError(f"metadata {key} must be a string")
            lines.append(f"  {key}: {yaml_quote(value)}")
    lines += ["---", ""]
    return "\n".join(lines) + "\n" + doc.body + "\n"


# ------------------------------------------------------------------------ the writes
# Seams: tests and the conformance reference replace these to inject a failure at a step.


def _fsync(fd: int) -> None:
    os.fsync(fd)


def _write(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        _fsync(fd)
    finally:
        os.close(fd)


def _rename(src: str, dst: str) -> None:
    # Match Node's fs.renameSync: existing files are replaced on Windows too.
    os.replace(src, dst)


def _temp(target: Path | str, kind: str) -> str:
    return f"{target}.{kind}-{os.getpid()}-{next(_counter)}"


def _check_rel(rel: str) -> list[str]:
    parts = rel.split("/")
    if (
        not rel
        or "\\" in rel
        or rel.startswith("/")
        or any(p in ("", ".", "..") for p in parts)
        or ":" in parts[0]
    ):
        raise SkillFileError(f"file path {rel!r} is not a plain relative path")
    return parts


def _build(target: Path, files: dict[str, bytes]) -> str:
    """Every file written and fsynced under a fresh temp dir beside `target`; its path."""
    rels = sorted(files)
    for rel in rels:
        _check_rel(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temp(target, "tmp")
    os.mkdir(tmp)
    try:
        for rel in rels:
            path = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write(path, bytes(files[rel]))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp


def write_dir_atomic(target: Path | str, files: dict[str, bytes]) -> None:
    """A new skill directory at `target`, or nothing at all.

    Refuses an existing target. On any failure the temp dir is removed and nothing is left
    at `target`; the failure propagates.
    """
    target = Path(target)
    if os.path.lexists(target):
        raise SkillFileError(f"a skill already exists at {target}")
    tmp = _build(target, files)
    try:
        _rename(tmp, str(target))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _copy_tree(src: Path, dst: str) -> None:
    """Directories and regular files, bytes as they are; a symlink is not followed or copied."""
    os.mkdir(dst)
    for entry in sorted(os.listdir(src)):
        s = src / entry
        d = os.path.join(dst, entry)
        if s.is_symlink():
            continue
        if s.is_dir():
            _copy_tree(s, d)
        elif s.is_file():
            _write(d, s.read_bytes())


def _swap_in(tmp: str, target: Path) -> None:
    """`tmp` renamed to `target`, the old `target` (if any) aside first and back on failure."""
    if not os.path.lexists(target):
        _rename(tmp, str(target))
        return
    old = _temp(target, "old")
    _rename(str(target), old)
    try:
        _rename(tmp, str(target))
    except BaseException:
        _rename(old, str(target))
        raise
    shutil.rmtree(old, ignore_errors=True)


def backup_stamp(now: str) -> str:
    """`2026-10-27T12:00:00.500Z` -> `20261027T120000.500Z`: a directory name on every platform."""
    try:
        ms = parse_now(now)
    except ValueError as e:
        raise SkillFileError(f"not a timestamp: {now!r}") from e
    t = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
    return (
        f"{t.year:04d}{t.month:02d}{t.day:02d}T{t.hour:02d}{t.minute:02d}{t.second:02d}"
        f".{t.microsecond // 1000:03d}Z"
    )


def _new_backup(backup_root: Path | str, name: str, now: str, fill: Callable[[str], None]) -> Path:
    base = backup_stamp(now)
    home = Path(backup_root) / name
    home.mkdir(parents=True, exist_ok=True)
    final = home / base
    n = 1
    while os.path.lexists(final):
        n += 1
        final = home / f"{base}-{n}"
    tmp = _temp(final, "tmp")
    try:
        fill(tmp)
        _rename(tmp, str(final))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def backup_absent(backup_root: Path | str, name: str, now: str) -> Path:
    """A backup saying "nothing was here", taken before an install; `undo` then removes."""

    def fill(tmp: str) -> None:
        os.mkdir(tmp)
        _write(os.path.join(tmp, ABSENT_MARKER), b"")

    return _new_backup(backup_root, name, now, fill)


def backup_dir(backup_root: Path | str, target: Path | str, now: str) -> Path:
    """A copy of the live skill dir under `<backup_root>/<name>/<stamp>/`."""
    target = Path(target)
    return _new_backup(backup_root, target.name, now, lambda tmp: _copy_tree(target, tmp))


def replace_dir_atomic(
    target: Path | str, files: dict[str, bytes], backup_root: Path | str, now: str
) -> Path:
    """The live skill backed up, then replaced by `files` in one rename; the backup's path.

    On a failure the old directory is back in place and the backup just taken is removed.
    """
    target = Path(target)
    if not target.is_dir() or target.is_symlink():
        raise SkillFileError(f"no skill at {target}")
    backup = backup_dir(backup_root, target, now)
    try:
        tmp = _build(target, files)
        try:
            _swap_in(tmp, target)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    except BaseException:
        shutil.rmtree(backup, ignore_errors=True)
        raise
    return backup


def _backups(backup_root: Path | str, name: str) -> list[tuple[tuple[str, int], str]]:
    home = Path(backup_root) / name
    try:
        entries = os.listdir(home)
    except OSError:
        return []
    out = []
    for entry in entries:
        m = _BACKUP_NAME.fullmatch(entry)
        if m is not None and (home / entry).is_dir():
            out.append(((m.group(1), int(m.group(2) or 1)), entry))
    return sorted(out)


def undo(backup_root: Path | str, name: str, target: Path | str) -> str:
    """Put back the newest backup of `name` at `target` and spend it; one sentence."""
    target = Path(target)
    found = _backups(backup_root, name)
    if not found:
        raise SkillFileError(f"no backup of {name} to undo")
    entry = found[-1][1]
    backup = Path(backup_root) / name / entry
    if (backup / ABSENT_MARKER).is_file():
        if os.path.lexists(target):
            old = _temp(target, "old")
            _rename(str(target), old)
            shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        return f"removed {name}; it did not exist before {entry}"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temp(target, "tmp")
    try:
        _copy_tree(backup, tmp)
        _swap_in(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(backup, ignore_errors=True)
    return f"restored {name} from its backup of {entry}"


def history_add(skill_dir: Path | str, version: int) -> None:
    """The live SKILL.md copied to `references/history/v<version>.md`, before a change."""
    skill_dir = Path(skill_dir)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SkillFileError(f"version must be a whole number from 1, not {version}")
    data = (skill_dir / SKILL_FILE).read_bytes()
    dst = skill_dir / "references" / "history" / f"v{version}.md"
    if os.path.lexists(dst):
        raise SkillFileError(f"history already holds v{version} of {skill_dir.name}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _write_file_atomic(dst, data)


def _write_file_atomic(path: Path, data: bytes) -> None:
    tmp = _temp(path, "tmp")
    try:
        _write(tmp, data)
        _rename(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------- paths


def skills_root(home: Path | str) -> Path:
    return Path(home) / ".bantamkit" / "skills"


def project_skills_root(top: Path | str) -> Path:
    return Path(top) / ".bantamkit" / "skills"


def backup_root(home: Path | str) -> Path:
    return Path(home) / ".bantamkit" / "skill-backups"


def state_path(home: Path | str) -> Path:
    return Path(home) / ".bantamkit" / STATE_NAME


def _empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "skills": {}}


def read_state(home: Path | str) -> dict[str, Any]:
    """`skills-state.json`, or an empty version-1 state when there is none.

    A file that exists and is not a version-1 state is REFUSED, never treated as empty: an
    empty state written back would forget every skill's probation and versions.
    """
    try:
        raw = state_path(home).read_bytes()
    except FileNotFoundError:
        return _empty_state()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise SkillFileError(f"{STATE_NAME} is not readable JSON") from e
    version = doc.get("version") if isinstance(doc, dict) else None
    if (
        type(version) is not int
        or version != STATE_VERSION
        or not isinstance(doc.get("skills"), dict)
    ):
        raise SkillFileError(f"{STATE_NAME} is not a version {STATE_VERSION} skills state")
    return doc


def state_bytes(state: dict[str, Any]) -> bytes:
    doc = {**state, "version": STATE_VERSION}
    return (json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_state(home: Path | str, state: dict[str, Any]) -> None:
    """The state written temp-then-rename under the storage lock; `version` forced to 1."""
    path = state_path(home)
    data = state_bytes(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(path):
        _write_file_atomic(path, data)


def update_state(
    home: Path | str, change: Callable[[dict[str, Any]], dict[str, Any] | None]
) -> dict[str, Any]:
    """Read, change and write the state under ONE hold of the lock; the state written."""
    path = state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(path):
        state = read_state(home)
        changed = change(state)
        state = state if changed is None else changed
        _write_file_atomic(path, state_bytes(state))
    return {**state, "version": STATE_VERSION}


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")
