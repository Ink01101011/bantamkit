"""Capability tiers and the storage lines `bantamkit_status` prints (#204, S2; job69 J69-7).

THREE TIERS. (1) **core** needs only an MCP client: indexes, logs, retention and every tool.
It is always on. (2) **hook** is on when the host's settings carry one of bantamkit's own hooks,
read the way `hostinstall` reads them: the user's `~/.claude/settings.json`, plus the project's
`.claude/settings.json` and `.claude/settings.local.json` under `cwd`, where Claude Code also
registers hooks. (3) **host data** is on when the native resolver (`hookadapter`'s RULING Q1.2,
without the transcript branch only a hook receives) answers a directory. Tiers 2 and 3 may be
absent SILENTLY: every probe here answers False rather than raising, and none of them runs on a
tool's hot path -- `bantamkit_status` asks, on demand, and nothing else does.

THE STATUS LINES, appended after the update line so every earlier line keeps its number:

    storage: core on; hooks on|off; host data on|off
    index facts <layer>: <n> doc(s), <bytes> bytes, persisted|in-memory   (one per memory layer
                                                                             whose facts/ exists)
    logs: <name> <bytes> (<n> rotated, <n> skipped)                       (one per log; or
                                                                             `logs: none`)
    retention: [off; ]last ran <iso>|never; refused <n>

`<layer>` is the layer's KIND (`project`, `extra`, `profile`), never a grant's name -- the rule
`unreadable_layer_condition` keeps. `in-memory` is the spec's "index directory unwritable" row:
recall scores from an index built per call, and this is where that is reported. `bytes` is what
the index holds on disk (head plus every shard file present). A log's `bytes` is its live file
plus its rotated segments; `skipped` is what `LogSegment.read` could not parse.

`runtime-ts/src/storage/tiers.ts` is the port; `tools/conformance/suites/storage-tiers.mjs`
compares the two over an MCP-only host profile (no hook, no native directory).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .hotindex import FAMILIES, SHARDS
from .logsegment import LogSegment


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def settings_paths(home: Path | str, cwd: Path | str | None) -> list[Path]:
    """The settings files a hook can be registered in: user scope, then the project's two.

    `cwd` is None when the process has none (a deleted working directory, job48): then only
    the user scope is read.
    """
    paths = [Path(home) / ".claude" / "settings.json"]
    if cwd is not None:
        project = Path(cwd) / ".claude"
        paths += [project / "settings.json", project / "settings.local.json"]
    return paths


def current_cwd() -> str | None:
    """`os.getcwd()`, or None when the working directory is gone. Never raises."""
    try:
        return os.getcwd()
    except OSError:
        return None


def hook_tier(home: Path | str, cwd: Path | str | None) -> bool:
    from bantamkit.hostinstall import has_bantamkit_hooks

    return any(has_bantamkit_hooks(p) for p in settings_paths(home, cwd))


def host_data_tier(home: Path | str) -> bool:
    from bantamkit.hookadapter import native_memory_dir

    try:
        return native_memory_dir(str(home)) is not None
    except Exception:  # noqa: BLE001 - a tier that cannot be probed is a tier that is off
        return False


def tiers(home: Path | str, cwd: Path | str | None) -> dict[str, bool]:
    """`{"core": True, "hook": bool, "host_data": bool}`. Never raises."""
    return {"core": True, "hook": hook_tier(home, cwd), "host_data": host_data_tier(home)}


def _on(flag: bool) -> str:
    return "on" if flag else "off"


def tier_line(found: dict[str, bool]) -> str:
    return (
        f"storage: core {_on(found['core'])}; hooks {_on(found['hook'])}; "
        f"host data {_on(found['host_data'])}"
    )


def _kind(p: Path) -> str:
    """`dir`, `file`, or `` -- `Path.is_dir()` raises on EACCES; a report never does."""
    try:
        mode = os.stat(p).st_mode
    except OSError:
        return ""
    return "dir" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else ""


def _size(p: Path) -> int:
    try:
        return os.stat(p).st_size
    except OSError:
        return 0


def index_lines(memory: Any) -> list[str]:
    """One line per memory layer whose `facts/` is a directory, refreshed as recall would."""
    out: list[str] = []
    for label, store, _writable in memory._layers:
        if _kind(Path(store.root) / "facts") != "dir":
            continue
        kind = label.split(":")[0]
        try:
            idx = store.index()
            idx.refresh("fast")
            docs = len(idx.names())
        except Exception:  # noqa: BLE001 - a report never raises; the layer condition says why
            out.append(f"index facts {kind}: unreadable")
            continue
        files = [idx.path] + [idx.shard_path(f, i) for f in FAMILIES for i in range(SHARDS)]
        held = sum(_size(p) for p in files)
        where = "persisted" if idx.persisted else "in-memory"
        out.append(f"index facts {kind}: {_plural(docs, 'doc')}, {held} bytes, {where}")
    return out


def _logs(base: Path) -> list[tuple[str, Path]]:
    found = [("hook-log", base / "hooks" / "hook-log.jsonl")]
    try:
        names = sorted(os.listdir(base / "usage"))
    except OSError:
        names = []
    found += [
        (f"usage/{n[: -len('.jsonl')]}", base / "usage" / n) for n in names if n.endswith(".jsonl")
    ]
    try:
        touched = sorted(os.listdir(base / "touch"))
    except OSError:
        touched = []
    found += [(f"touch/{n[:-6]}", base / "touch" / n) for n in touched if n.endswith(".jsonl")]
    return found


def log_lines(home: Path | str) -> list[str]:
    out: list[str] = []
    for name, path in _logs(Path(home) / ".bantamkit"):
        seg = LogSegment(path)
        segments = seg.segments()
        if _kind(path) != "file" and not segments:
            continue
        held = _size(path) + sum(_size(s) for s in segments)
        seg.read()
        out.append(f"logs: {name} {held} ({len(segments)} rotated, {seg.skipped} skipped)")
    return out or ["logs: none"]


def touch_line(home: Path | str) -> str:
    """`touch: none`, or how many touch-log writes the hook log records as missed (#200).

    `none` only when there is no touch directory AND no miss: a miss is most often exactly a
    touch directory that could not be made, and `none` would hide it.
    """
    base = Path(home) / ".bantamkit"
    rows = LogSegment(base / "hooks" / "hook-log.jsonl").read()
    misses = sum(1 for r in rows if r.get("touch") == "miss")
    if misses == 0 and _kind(base / "touch") != "dir":
        return "touch: none"
    return f"touch: {_plural(misses, 'missed write')} (hook log)"


def retention_line(home: Path | str) -> str:
    from .retention import enabled, state_path

    ran = "never"
    refused = 0
    try:
        data = json.loads(state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        if isinstance(data.get("ran_at"), str):
            ran = data["ran_at"]
        report = data.get("report")
        if isinstance(report, dict) and isinstance(report.get("refused"), list):
            refused = len(report["refused"])
    prefix = "" if enabled() else "off; "
    return f"retention: {prefix}last ran {ran}; refused {refused}"


def status_lines(memory: Any, home: Path | str, cwd: Path | str | None) -> list[str]:
    """Every storage line of `bantamkit_status`, in order. Never raises."""
    return [
        tier_line(tiers(home, cwd)),
        *index_lines(memory),
        *log_lines(home),
        touch_line(home),
        retention_line(home),
    ]
