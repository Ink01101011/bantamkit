"""The B summaries (#200, E1-B): one short line about what was edited, read off the touch log.

- At SessionStart (`startup`, `resume`, `clear`): `last_session_line`, the PREVIOUS session in
  this repo -- the files it edited, the commits made while it ran (from `git log`), and how many
  files are uncommitted now.
- At SessionStart with `source == "compact"`: `compact_line`, the files THIS session edited
  before the compaction. PreCompact already lists the reads, so this lists edits only.

Reads are never listed. Silence is the empty string: no edits and no commits say nothing. Every
line is cut by `cap_bytes(line, SUMMARY_MAX)`, 600 BYTES of UTF-8, never inside a character.
The bytes do not count against SessionStart's 3000-byte memory blocks; the line is its own part.

Rules both runtimes hold (`touch-summary` compares them):

- the rows considered are touch rows, `op` in `read`/`edit`/`write`, with a ledger stamp `ts`
  (`YYYY-MM-DDTHH:MM:SSZ`); `folded` and `use` rows, and a row with any other `ts`, are skipped;
- "edited" is the distinct paths with `op` `edit` or `write` (bash-turn included), most
  recently touched first: by `seq` descending, a tie (or a missing `seq`) by later log position;
- `previous_session` is the session, other than `current` and other than `""`, whose latest
  touch `ts` is greatest; a tie on that `ts` goes to the smaller session id by code point;
- the age is `now` minus the session's latest touch `ts`, floored, never negative.

`runtime-ts/src/touch/summary.ts` is the port; `touch-summary` compares the two.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from bantamkit.memory.usage import _parse as _parse_ts

from .graph import _seq

SUMMARY_MAX = 600
SUMMARY_COMMIT_GRACE_S = 1800
SUMMARY_FILES = 3
SUMMARY_COMMITS = 3
SUMMARY_SUBJECT_MAX = 60
COMPACT_FILES = 10
_TOUCH = ("read", "edit", "write")
_EDIT = ("edit", "write")
_HEAD = "[bantamkit touch]"


def cap_bytes(text: str, max_bytes: int) -> str:
    """At most `max_bytes` BYTES of UTF-8, never split inside a character.

    A copy of `hookadapter._cap_bytes`' semantics: importing it from here would make the core
    package depend on the hook adapter, the wrong layer direction.
    """
    raw = str(text).encode("utf-8")
    if len(raw) <= max_bytes:
        return str(text)
    end = max_bytes
    while end > 0 and (raw[end] & 0xC0) == 0x80:  # back off a continuation byte
        end -= 1
    return raw[:end].decode("utf-8")


def age_text(seconds: float) -> str:
    s = max(0.0, float(seconds))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 172800:
        return f"{int(s // 3600)} h ago"
    return f"{int(s // 86400)} d ago"


def shift_ts(ts: str, seconds: int) -> str:
    """The ledger stamp `seconds` after `ts` (same `YYYY-MM-DDTHH:MM:SSZ` shape)."""
    t = _parse_ts(ts) + seconds
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamped(ts: Any) -> bool:
    if not isinstance(ts, str):
        return False
    try:
        _parse_ts(ts)
    except ValueError:
        return False
    return True


def _touches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if isinstance(r, dict)
        and r.get("op") in _TOUCH
        and isinstance(r.get("path"), str)
        and isinstance(r.get("session"), str)
        and _stamped(r.get("ts"))
    ]


def _edited(rows: list[dict[str, Any]]) -> list[str]:
    """Distinct edited paths, most recently touched first (seq desc, then later log position)."""
    keyed: list[tuple[int, int, str]] = []
    for i, r in enumerate(rows):
        if r.get("op") in _EDIT:
            seq = _seq(r.get("seq"))
            keyed.append((-1 if seq is None else seq, i, r["path"]))
    out: list[str] = []
    for _, _, path in sorted(keyed, key=lambda k: (-k[0], -k[1])):
        if path not in out:
            out.append(path)
    return out


def _files(n: int) -> str:
    return f"{n} file" if n == 1 else f"{n} files"


def _more(k: int) -> str:
    return f" (+{k})" if k > 0 else ""


def previous_session(
    rows: list[dict[str, Any]], current: str
) -> tuple[str, list[dict[str, Any]]] | None:
    latest: dict[str, str] = {}
    mine: dict[str, list[dict[str, Any]]] = {}
    for r in _touches(rows):
        sid = r["session"]
        if sid == "" or sid == current:
            continue
        mine.setdefault(sid, []).append(r)
        if sid not in latest or r["ts"] > latest[sid]:
            latest[sid] = r["ts"]
    best: str | None = None
    for sid in sorted(latest):  # ascending by code point, so a tie keeps the smaller id
        if best is None or latest[sid] > latest[best]:
            best = sid
    return None if best is None else (best, mine[best])


def last_session_line(
    rows: list[dict[str, Any]],
    now: str,
    display: Callable[[str], str],
    commits: list[str],
    uncommitted: int,
) -> str:
    touches = _touches(rows)
    edited = _edited(touches)
    if not edited and not commits:
        return ""
    last = max((r["ts"] for r in touches), default=None)
    if last is None:  # commits but no stamped touch row: there is no session to date
        return ""
    age = age_text(_parse_ts(now) - _parse_ts(last))
    head = f"{_HEAD} last session here ({last[:10]}, {age}): "
    if edited:
        names = ", ".join(display(p) for p in edited[:SUMMARY_FILES])
        body = f"edited {_files(len(edited))} — {names}{_more(len(edited) - SUMMARY_FILES)}"
    else:
        body = "edited no files"
    if commits:
        subjects = "; ".join(cap_bytes(s, SUMMARY_SUBJECT_MAX) for s in commits[:SUMMARY_COMMITS])
        body += f"; commits: {subjects}{_more(len(commits) - SUMMARY_COMMITS)}"
    if uncommitted > 0:
        body += f"; uncommitted: {_files(uncommitted)}"
    return cap_bytes(head + body, SUMMARY_MAX)


def compact_line(rows: list[dict[str, Any]], session: str, display: Callable[[str], str]) -> str:
    edited = _edited([r for r in _touches(rows) if r["session"] == session])
    if not edited:
        return ""
    names = ", ".join(display(p) for p in edited[:COMPACT_FILES])
    line = f"{_HEAD} edited in this session before compaction: {names}"
    return cap_bytes(line + _more(len(edited) - COMPACT_FILES), SUMMARY_MAX)


def uncommitted_count(status: str) -> int:
    """Entries in `git status --porcelain=v1 -z -uall` output.

    Each entry is `XY <path>`; a rename or copy (`X` or `Y` is `R`/`C`) is followed by its
    source path as a field of its own, which is skipped rather than counted.
    """
    fields = status.split("\0")
    n = 0
    i = 0
    while i < len(fields):
        e = fields[i]
        if len(e) >= 4 and e[2] == " ":
            n += 1
            if "R" in e[:2] or "C" in e[:2]:
                i += 1
        i += 1
    return n
