"""Where the skill audit's host facts come from (#205, K3).

`skillaudit` reads nothing from the machine, on purpose, so two runtimes can be compared
(docs/skill-audit.md). This module is the layer that reads: an ADAPTER answers `Gathered` —
the skill roots, the switched-on plugins, the served version directories and the call
counts. Adding a host is adding one adapter; the audit does not change. Read-only: nothing
here writes, and nothing here ever writes under `~/.claude`.

TWO SHAPES OF A CALL (Amendment A2). A skill the model invokes is a `Skill` `tool_use` block
whose `input.skill` names it. A skill the USER invokes by typing `/<name>` leaves no such
block: Claude Code writes a `type: "user"` record whose string content carries
`<command-name>/<name></command-name>`, then an `isMeta` record holding the expanded text.
Both are one call each. Built-in commands (`/clear`, `/compact`, ...) use the same record, so
a command counts only when its name is a skill the roots actually hold (`known_skills`). The
record shape is not a documented contract; it was measured on real transcripts (job73 A2).

`runtime-ts/src/skillhost.ts` is the port; `tools/conformance/suites/skill-host.mjs` compares
them.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bantamkit.storage.retention import parse_now
from bantamkit.storage.tiers import settings_paths

HOST_CLAUDE_CODE = "claude-code"
HOST_NONE = "none"
USAGE_DAYS = 30
DAY_MS = 86_400_000
SKILL_TOOL = "Skill"
SKILL_FILE = "SKILL.md"
#: `<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md`: the path shape `skillaudit`
#: reads a plugin skill from, and so the shape its `id` (`<plugin>:<skill>`) comes from.
PLUGIN_PATH_SEGMENTS = 6
SKILLS_SEGMENT = "skills"
_NEEDLE = b'"Skill"'
_TOOL_USE = b'"tool_use"'
_COMMAND = b"<command-name>"
_COMMAND_NAME = re.compile(r"<command-name>/([^<]*)</command-name>")
_SEP = re.compile(r"[\\/]")


def _refuse(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _loads(text: str) -> Any:
    """`JSON.parse`'s rules: `NaN`/`Infinity` refused, a leading U+FEFF refused."""
    return json.loads(text, parse_constant=_refuse)


def _read_json(p: Path) -> Any:
    """Strict UTF-8 and `_loads`. None on any failure."""
    try:
        return _loads(p.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _real(p: str | Path) -> str:
    return os.path.realpath(p)


@dataclass(frozen=True)
class UsageScan:
    counts: dict[str, int]
    span_days: int
    transcripts: int
    unreadable: int
    skipped_lines: int

    def summary(self) -> dict[str, Any]:
        return {
            "calls": sum(self.counts.values()),
            "counts": dict(sorted(self.counts.items())),
            "span_days": self.span_days,
            "transcripts": self.transcripts,
            "unreadable": self.unreadable,
            "skipped_lines": self.skipped_lines,
        }


@dataclass(frozen=True)
class Gathered:
    host: str
    roots: tuple[tuple[str, str], ...] = ()
    enabled: tuple[str, ...] = ()
    versions: dict[str, str] | None = None
    sources: dict[str, str] = field(default_factory=dict)
    usage: UsageScan | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": list(self.enabled),
            "host": self.host,
            "roots": [list(r) for r in self.roots],
            "sources": dict(sorted(self.sources.items())),
            "usage": None if self.usage is None else self.usage.summary(),
            "versions": None if self.versions is None else dict(sorted(self.versions.items())),
        }


def _walk(root: Path) -> Iterator[tuple[str, list[str], list[str]]]:
    """`os.walk` in a fixed order, never through a symlinked directory, errors skipped."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        yield dirpath, dirnames, filenames


def _jsonl_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, _, filenames in _walk(root):
        out.extend(Path(dirpath) / n for n in filenames if n.endswith(".jsonl"))
    return out


def known_skills(roots: Collection[str | Path]) -> frozenset[str]:
    """Every skill id the roots hold, spelled as `skillaudit` spells `_Skill.id`.

    `<plugin>:<directory>` for a `SKILL.md` at the plugin path shape, the bare directory name
    otherwise (the root's own name for a `SKILL.md` directly in it). Only names are needed —
    which command names are skills rather than built-ins — so no file is opened.
    """
    out: set[str] = set()
    for root in roots:
        base = Path(root)
        for dirpath, _, filenames in _walk(base):
            if SKILL_FILE not in filenames:
                continue
            parts = list(Path(dirpath, SKILL_FILE).relative_to(base).parts)
            directory = parts[-2] if len(parts) > 1 else base.name
            if len(parts) == PLUGIN_PATH_SEGMENTS and parts[3] == SKILLS_SEGMENT:
                out.add(f"{parts[1]}:{directory}")
            else:
                out.add(directory)
    return frozenset(out)


def _candidate_lines(data: bytes) -> Iterator[bytes]:
    """Each line that can hold a call, once: `"Skill"` with `"tool_use"`, or `<command-name>`."""
    i = 0
    a = data.find(_NEEDLE)
    b = data.find(_COMMAND)
    while True:
        if 0 <= a < i:
            a = data.find(_NEEDLE, i)
        if 0 <= b < i:
            b = data.find(_COMMAND, i)
        if a < 0 and b < 0:
            return
        j = b if a < 0 else a if b < 0 else min(a, b)
        start = data.rfind(b"\n", 0, j) + 1
        end = data.find(b"\n", j)
        end = len(data) if end < 0 else end
        line = data[start:end]
        if _COMMAND in line or (_NEEDLE in line and _TOOL_USE in line):
            yield line
        i = end + 1


def _ts_ms(value: Any) -> int | None:
    try:
        return parse_now(value)
    except ValueError:
        return None


def _command(rec: dict[str, Any], known: Collection[str]) -> str | None:
    """The skill a typed `/<name>` invoked, or None. Only a non-meta user record whose content
    is a string counts: the same tag inside a tool result, a tool input or a request copy is
    text ABOUT a command, not a command."""
    if rec.get("type") != "user" or rec.get("isMeta") is True:
        return None
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        return None
    m = _COMMAND_NAME.search(content)
    if m is None or m.group(1) not in known:
        return None
    return m.group(1)


def count_skill_usage(
    projects: Path | str,
    now_ms: int,
    days: int = USAGE_DAYS,
    known: Collection[str] | None = None,
) -> UsageScan:
    """`tool-usage.mjs --group skill --since <days>d --no-events`, ported, and fast enough.

    The two corrections that script makes are kept: a `tool_use` id is counted once (a resumed
    session rewrites it verbatim), and subagent transcripts under `<session>/subagents/` are
    walked. A file last written before the cutoff holds no line after it, so it is not read;
    its mtime still proves how far back the transcripts reach (`span_days`).

    `known` is the set of skill ids a typed command may name (Amendment A2). With None, only
    `Skill` tool_use blocks are counted. A command record is deduped by its `uuid`, as a block
    is by its `id`.
    """
    cutoff = now_ms - days * DAY_MS
    counts: dict[str, int] = {}
    seen: set[str] = set()
    seen_commands: set[str] = set()
    oldest: int | None = None
    transcripts = unreadable = skipped = 0

    def bump(skill: str) -> None:
        counts[skill] = counts.get(skill, 0) + 1

    for path in _jsonl_files(Path(projects)):
        try:
            mtime_ms = os.stat(path).st_mtime_ns // 1_000_000
        except OSError:
            unreadable += 1
            continue
        if mtime_ms < cutoff:
            oldest = mtime_ms if oldest is None else min(oldest, mtime_ms)
            continue
        try:
            data = path.read_bytes()
        except OSError:
            unreadable += 1
            continue
        transcripts += 1
        for line in _candidate_lines(data):
            try:
                rec = _loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                skipped += 1
                continue
            if not isinstance(rec, dict):
                continue
            ts = _ts_ms(rec.get("timestamp"))
            if ts is not None:
                oldest = ts if oldest is None else min(oldest, ts)
                if ts < cutoff:
                    continue
            if known is not None:
                typed = _command(rec, known)
                if typed is not None:
                    uid = rec.get("uuid")
                    if not (isinstance(uid, str) and uid):
                        bump(typed)
                    elif uid not in seen_commands:
                        seen_commands.add(uid)
                        bump(typed)
            message = rec.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use" or block.get("name") != SKILL_TOOL:
                    continue
                bid = block.get("id")
                if isinstance(bid, str) and bid:
                    if bid in seen:
                        continue
                    seen.add(bid)
                given = block.get("input")
                skill = given.get("skill") if isinstance(given, dict) else None
                if isinstance(skill, str) and skill:
                    bump(skill)
    span = 0 if oldest is None else max(0, min(days, (now_ms - oldest) // DAY_MS))
    return UsageScan(counts, span, transcripts, unreadable, skipped)


def _enabled(home: Path, cwd: str | None) -> tuple[tuple[str, ...], dict[str, str]]:
    won: dict[str, tuple[bool, str]] = {}
    for f in settings_paths(home, cwd):
        doc = _read_json(f)
        plugins = doc.get("enabledPlugins") if isinstance(doc, dict) else None
        if not isinstance(plugins, dict):
            continue
        for pid, on in plugins.items():
            if isinstance(on, bool):
                won[pid] = (on, str(f))
    on = {pid: f for pid, (v, f) in won.items() if v}
    return tuple(sorted(on)), dict(sorted(on.items()))


def _versions(home: Path, cwd: str | None) -> dict[str, str] | None:
    doc = _read_json(home / ".claude" / "plugins" / "installed_plugins.json")
    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    if not isinstance(plugins, dict):
        return None
    here = _real(cwd) if cwd is not None else None
    out: dict[str, str] = {}
    for pid, entries in plugins.items():
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        project: str | None = None
        other: str | None = None
        for e in entries:
            if not isinstance(e, dict) or not isinstance(e.get("installPath"), str):
                continue
            if e.get("scope") == "project":
                where = e.get("projectPath")
                if (
                    project is None
                    and here is not None
                    and isinstance(where, str)
                    and _real(where) == here
                ):
                    project = e["installPath"]
            elif other is None:
                other = e["installPath"]
        chosen = project or other
        name = _SEP.split(chosen.rstrip("\\/"))[-1] if chosen else ""
        if name:
            out[pid] = name
    return dict(sorted(out.items()))


class NullAdapter:
    host = HOST_NONE

    def gather(self, home: Path | str, cwd: str | None, now_ms: int) -> Gathered:
        return Gathered(HOST_NONE)


class ClaudeCodeAdapter:
    host = HOST_CLAUDE_CODE

    def gather(self, home: Path | str, cwd: str | None, now_ms: int) -> Gathered:
        """Roots in the order `plugins, project, user`: the audit's dedupe lets the LATER root
        win a bare-name tie, and Claude Code serves the personal copy (Amendment A1)."""
        home = Path(home)
        claude = home / ".claude"
        user = claude / "skills"
        candidates = [("plugins", claude / "plugins" / "cache")]
        if cwd is not None:
            project = Path(cwd) / ".claude" / "skills"
            if _real(project) != _real(user):
                candidates.append(("project", project))
        candidates.append(("user", user))
        roots = tuple((label, str(p)) for label, p in candidates if p.is_dir())
        enabled, sources = _enabled(home, cwd)
        known = known_skills([p for _, p in roots])
        return Gathered(
            HOST_CLAUDE_CODE,
            roots,
            enabled,
            _versions(home, cwd),
            sources,
            count_skill_usage(claude / "projects", now_ms, known=known),
        )


def select_adapter(home: Path | str) -> ClaudeCodeAdapter | NullAdapter:
    return ClaudeCodeAdapter() if (Path(home) / ".claude").is_dir() else NullAdapter()
