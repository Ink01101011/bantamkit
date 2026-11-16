"""Capability tiers and the storage lines `bantamkit_status` prints (#204, S2; job69 J69-7).

**Generated, not hand-written (#316 G4, J90-3).** Every rule is `bantamkit/_generated/tiers.py`,
compiled from `runtime-ts/src/storage/tiers.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*); the TypeScript carries the contract: THREE TIERS (core always on; hook when a host
settings file carries one of bantamkit's own hooks, `hostinstall.has_bantamkit_hooks`; host data
when the native resolver answers a directory, `hookadapter.native_memory_dir`), each probe silent,
and the status lines:

    storage: core on; hooks on|off; host data on|off
    index facts <layer>: <n> doc(s), <bytes> bytes, persisted|in-memory
    logs: hook-log <bytes> (<n> rotated, <n> skipped)
    logs: usage/* <n> file(s) <bytes> (<n> rotated, <n> skipped)     (or one line per log with
    logs: touch/* <n> file(s) <bytes> (<n> rotated, <n> skipped)      `detail`; or `logs: none`)
    touch: none | <n> missed write(s) (hook log)
    retention: [off; ]last ran <iso>|never; refused <n>

This module is the SHIM: the Python surface the hand-written module had (`Path` arguments as
strings, `settings_paths` as `Path`s, a `Memory` handed over as the generated one it wraps).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bantamkit._generated import tiers as _g


def _cwd_text(p: Path | str | None) -> str | None:
    return None if p is None else os.fspath(p)


def _generated_memory(memory: Any) -> Any:
    """The generated `Memory` a `bantamkit.memory.Memory` shim wraps (`_core`), or the value."""
    return getattr(memory, "_core", memory)


def settings_paths(home: Path | str, cwd: Path | str | None) -> list[Path]:
    """The settings files a hook can be registered in: user scope, then the project's two."""
    return [Path(p) for p in _g.settings_paths(os.fspath(home), _cwd_text(cwd))]


def current_cwd() -> str | None:
    """`os.getcwd()`, or None when the working directory is gone. Never raises."""
    return _g.current_cwd()


def hook_tier(home: Path | str, cwd: Path | str | None) -> bool:
    return bool(_g.hook_tier(os.fspath(home), _cwd_text(cwd)))


def host_data_tier(home: Path | str) -> bool:
    return bool(_g.host_data_tier(os.fspath(home)))


def tiers(home: Path | str, cwd: Path | str | None) -> dict[str, bool]:
    """`{"core": True, "hook": bool, "host_data": bool}`. Never raises."""
    return _g.tiers(os.fspath(home), _cwd_text(cwd))


def tier_line(found: dict[str, bool]) -> str:
    return _g.tier_line(found)


def index_lines(memory: Any) -> list[str]:
    """One line per memory layer whose `facts/` is a directory, refreshed as recall would."""
    return _g.index_lines(_generated_memory(memory))


def log_lines(home: Path | str, detail: bool = False) -> list[str]:
    """The `logs:` lines: per family by default, per log with `detail`."""
    return _g.log_lines(os.fspath(home), detail)


def touch_line(home: Path | str) -> str:
    """`touch: none`, or how many touch-log writes the hook log records as missed (#200)."""
    return _g.touch_line(os.fspath(home))


def retention_line(home: Path | str) -> str:
    return _g.retention_line(os.fspath(home))


def status_lines(
    memory: Any, home: Path | str, cwd: Path | str | None, *, detail: bool = False
) -> list[str]:
    """Every storage line of `bantamkit_status`, in order. Never raises. `detail` is the tool's
    argument: one `logs:` line per log instead of per family."""
    return _g.status_lines(_generated_memory(memory), os.fspath(home), _cwd_text(cwd), detail)
