"""`memory_recall({file})` (#200, E1-C): the facts linked to a tracked file, and its last touch.

The six sentences below are the tool's whole vocabulary for this mode and are byte-identical in
`runtime-ts/src/touch/recallfile.ts`; `wire.mjs`'s `memory-recall-file` session compares the two
servers and pins `FILE_UNKNOWN` and `RECALL_NEEDS_QUERY_OR_FILE` per side.

- `RECALL_NEEDS_QUERY_OR_FILE` is a tool ERROR (`MemoryValidationError`), raised by the handler
  when neither argument was given; the other five are replies.
- `QUERY_IGNORED` is the reply's second line whenever `query` came with `file` (plan Q5: the
  query is ignored and the reply says so; filtering by it is not in the spec).

The reply's first line is `history_line`: `[file] <suffix> — last touched <YYYY-MM-DD> (<op>)`,
`last touched never` when the touch log holds no row for the path, then `; last commit <sha7>
<subject>` when `git log -1` names one. The linked facts follow in `linked_names` order: strong
edges in the graph's order, then weak edges by decayed co-use weight (the usage half-life, as
`touch.context.context_weights` decays them) descending, then by name.
"""

from __future__ import annotations

from typing import Any

from bantamkit.memory.usage import USAGE_HALF_LIFE_DAYS
from bantamkit.memory.usage import _parse as _parse_ts

from .refs import FileSet, shortest_suffix
from .repo import Repo, git

RECALL_NEEDS_QUERY_OR_FILE = "memory_recall needs a query or a file."
FILE_NOT_IN_REPO = (
    "memory_recall file needs a git repository; the server's working directory is not inside one."
)
FILE_UNKNOWN = 'No tracked file in this repository matches "{file}".'
FILE_AMBIGUOUS = '"{file}" matches {n} tracked files: {names}. Pass a longer suffix.'
FILE_NO_FACTS = "No memory is linked to {suffix}."
QUERY_IGNORED = "(query ignored: file was given)"
AMBIGUOUS_SHOWN = 5
_TOUCH = ("read", "edit", "write", "folded")


def normalize_file(file: str) -> str:
    """The argument as `FileSet.matches` takes it: stripped, `\\` read as `/` (a Windows path)."""
    return file.strip().replace("\\", "/")


def ambiguous(file: str, matches: list[str], fs: FileSet) -> str:
    """`FILE_AMBIGUOUS`: the matches' shortest suffixes by code point, the first five, `(+k)`."""
    names = sorted(shortest_suffix(m, fs) for m in matches)
    shown = ", ".join(names[:AMBIGUOUS_SHOWN])
    if len(names) > AMBIGUOUS_SHOWN:
        shown += f" (+{len(names) - AMBIGUOUS_SHOWN})"
    return FILE_AMBIGUOUS.format(file=file, n=len(matches), names=shown)


def last_touch(rows: list[dict[str, Any]], path: str) -> tuple[str, str] | None:
    """`(ts, op)` of the newest touch row of `path`; a tie keeps the later line."""
    best: tuple[str, str] | None = None
    for r in rows:
        ts, op = r.get("ts"), r.get("op")
        if r.get("path") != path or op not in _TOUCH or not isinstance(ts, str):
            continue
        if best is None or ts >= best[0]:
            best = (ts, str(op))
    return best


def history_line(repo: Repo, path: str, rows: list[dict[str, Any]], display: str) -> str:
    touched = last_touch(rows, path)
    line = f"[file] {display} — last touched "
    line += "never" if touched is None else f"{touched[0][:10]} ({touched[1]})"
    out = git(repo, ["log", "-1", "--format=%h%x00%s", "--", path])
    if out:
        sha, _, subject = out.rstrip("\n").partition("\0")
        if sha:
            line += f"; last commit {sha[:7]} {subject}"
    return line


def linked_names(graph: dict[str, Any], path: str, now: str) -> list[str]:
    """Strong-edge facts in graph order, then weak-only ones by decayed weight desc, then name."""
    out: list[str] = []
    for edge in graph.get("strong", {}).get(path, []) or []:
        if isinstance(edge, list) and edge and isinstance(edge[0], str) and edge[0] not in out:
            out.append(edge[0])
    t_now = _parse_ts(now)
    weak: list[tuple[float, str]] = []
    for fact, stamps in (graph.get("weak", {}).get(path, {}) or {}).items():
        if fact in out or not isinstance(stamps, list):
            continue
        w = 0.0
        for ts in stamps:
            try:
                t = _parse_ts(ts)
            except (TypeError, ValueError):
                continue  # not a ledger stamp: no use
            w += 0.5 ** (max(0.0, (t_now - t) / 86400.0) / USAGE_HALF_LIFE_DAYS)
        weak.append((w, fact))
    out.extend(f for _, f in sorted(weak, key=lambda x: (-x[0], x[1])))
    return out
