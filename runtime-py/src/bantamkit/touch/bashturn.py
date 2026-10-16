"""Writes made by Bash, once per turn (#200, E5): `git status` at UserPromptSubmit against `git
status` at Stop. A path already dirty before the turn is caught by its stat moving.

`snapshot` reads `git status --porcelain=v1 -z -uall` into `path -> [xy, mtime_ns, size]`
(`mtime_ns` a decimal string, past 2**53; `"-"` and `-1` when the path cannot be statted, a
deletion). A rename or copy entry `R  new\\0old` keys on `new`; the source path is skipped.
`changed` is every path added, removed or whose triple moved, in code-point order. The turn
is kept in `<hooks>/ledger-<session>.turn.json` (the ledger file-name rule), so Retention's
7-day ledger rule prunes it and PostCompact's unlink of `ledger-<session>.json` leaves it.

The hook arms are `hookadapter._turn_open` / `_turn_close`. `runtime-ts/src/touch/bashturn.ts`
is the port; `touch-turn` compares the two.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .repo import Repo, git

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")  # the ledger file-name rule, `hookadapter._LEDGER_UNSAFE`


def snapshot(repo: Repo) -> dict[str, list[Any]] | None:
    out = git(repo, ["status", "--porcelain=v1", "-z", "-uall"])
    if out is None:
        return None
    fields = out.split("\0")
    snap: dict[str, list[Any]] = {}
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if xy[0] in "RC":
            i += 1  # the source path follows; the entry keys on the destination
        try:
            st = os.stat(os.path.join(repo.top, *path.split("/")))
            snap[path] = [xy, str(st.st_mtime_ns), st.st_size]
        except (OSError, ValueError):
            snap[path] = [xy, "-", -1]
    return snap


def changed(before: dict[str, list[Any]], after: dict[str, list[Any]]) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def _turn_path(state_dir: str, session: str) -> str:
    return os.path.join(state_dir, f"ledger-{_UNSAFE.sub('_', session or 'nosession')}.turn.json")


def save_turn(state_dir: str, session: str, snap: dict[str, list[Any]], seq: int) -> None:
    """`{"seq", "status"}`, keys sorted, temp then rename. Raises `OSError` when unwritable."""
    p = _turn_path(state_dir, session)
    os.makedirs(state_dir, exist_ok=True)
    tmp = f"{p}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    body = json.dumps(
        {"seq": seq, "status": snap}, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    try:
        with open(tmp, "wb") as f:
            f.write(body.encode("utf-8"))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_turn(state_dir: str, session: str) -> tuple[int, dict[str, list[Any]]] | None:
    try:
        with open(_turn_path(state_dir, session), "rb") as f:
            d = json.loads(f.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    seq, status = d.get("seq"), d.get("status")
    if isinstance(seq, float) and seq.is_integer():
        seq = int(seq)  # `JSON.parse` cannot tell `7.0` from `7`
    if not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(status, dict):
        return None
    return seq, status
