"""The touch graph (#200): file -> facts, a #204 derived index; delete it and a load rebuilds it.

`~/.bantamkit/graph/<repo-id>.json` holds two halves, each with its own print:

- `strong`: `path -> [[fact, symbol | None], ...]`, from the facts' `refs` (the hot index's
  slot, filled by `storage.hotindex`) resolved against `git ls-files` and the renames. Its print
  is `sha16(dumps([GRAPH_VERSION, repo.head_print, [layer index print, ...]]))`, so a commit, a
  `git add` or a fact write moves it, and a tool call does not.
- `weak`: `path -> fact -> [ts, ...]`, a fact used (`use` row) in the same session within
  `WEAK_SPAN` tool calls of a touch, or inside a bash turn (`from < use.seq <= seq`). Its
  print is the touch log's live size and segment count, so a tool call moves only it.

`load` rebuilds a half only when its print moved, and writes temp-then-rename under the O_EXCL
lock. The bytes are `hotindex.dumps`, so either runtime reads the other's file. ANY failure
returns `None`: the graph is an enhancement, and "no graph" means `w_context` is 0 (spec, Error
handling). A read-only layer that cannot be read contributes no edges; the writable one failing
fails the strong half, as it fails `Memory._pooled`.

`runtime-ts/src/touch/graph.ts` is the port; `touch-graph` compares the two.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from bantamkit.storage.hotindex import dumps
from bantamkit.storage.lock import exclusive

from .log import TouchLog
from .refs import FileSet, resolve_ref
from .repo import Repo, head_print, ls_files, renames

GRAPH_VERSION = 1
WEAK_SPAN = 20
WEAK_TS_MAX = 32
_KEYS = {"version", "strong_print", "weak_print", "files", "strong", "weak"}
_TOUCH = ("read", "edit", "write")
_Row = tuple[int, dict[str, Any]]


def sha16_text(text: str) -> str:
    """sha16 of a STRING (`hotindex.sha16` hashes a realpath, so it cannot be reused here)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_strong(
    layer_refs: list[dict[str, list[str]]], fs: FileSet, ren: dict[str, str], top: str
) -> dict[str, list[list[Any]]]:
    """`path -> [[fact, symbol | None], ...]`: first layer first, then name order, one per pair."""
    out: dict[str, list[list[Any]]] = {}
    for refs in layer_refs:
        for name in sorted(refs):
            for raw in refs[name]:
                hit = resolve_ref(raw, fs, ren, top)
                if hit is None:
                    continue
                edge = [name, hit[1]]
                bucket = out.setdefault(hit[0], [])
                if edge not in bucket:
                    bucket.append(edge)
    return out


def _seq(v: Any) -> int | None:
    """An ordinal as `JSON.parse` would read it: an integral float is that integer."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def build_weak(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """`path -> fact -> [ts, ...]`, the newest `WEAK_TS_MAX` distinct use timestamps, ascending."""
    by_session: dict[str, tuple[list[_Row], list[_Row]]] = {}
    for r in rows:
        s, seq = r.get("session"), _seq(r.get("seq"))
        if not isinstance(s, str) or seq is None or not isinstance(r.get("ts"), str):
            continue
        touches, uses = by_session.setdefault(s, ([], []))
        if r.get("op") == "use" and isinstance(r.get("fact"), str):
            uses.append((seq, r))
        elif r.get("op") in _TOUCH and isinstance(r.get("path"), str):
            touches.append((seq, r))
    out: dict[str, dict[str, list[str]]] = {}
    for touches, uses in by_session.values():
        for tseq, t in touches:
            frm = _seq(t.get("from"))
            turn = t.get("via") == "bash-turn" and frm is not None
            for useq, u in uses:
                hit = (frm < useq <= tseq) if turn else abs(useq - tseq) <= WEAK_SPAN  # type: ignore[operator]
                if hit:
                    out.setdefault(t["path"], {}).setdefault(u["fact"], []).append(u["ts"])
    for facts in out.values():
        for f in facts:
            facts[f] = sorted(set(facts[f]))[-WEAK_TS_MAX:]
    return out


def _layer(entry: tuple[Any, ...], i: int) -> tuple[Any, bool]:
    """`(store, writable)` of a `(label, store)` or `Memory._layers` `(label, store, writable)`."""
    return entry[1], (bool(entry[2]) if len(entry) > 2 else i == 0)


def _present(idx: Any) -> bool:
    try:
        return os.path.isdir(idx.dir)
    except (OSError, ValueError):
        return False


class TouchGraph:
    def __init__(self, home: Path | str, repo: Repo) -> None:
        self.home = Path(home)
        self.repo = repo
        self.path = self.home / ".bantamkit" / "graph" / f"{repo.id}.json"
        self.log = TouchLog(self.home, repo.id)

    def weak_print(self) -> str:
        try:
            size = os.stat(self.log.path).st_size
        except OSError:
            size = -1
        return f"{size}:{len(self.log._seg().segments())}"

    def strong_print(self, layers: list[tuple[Any, ...]]) -> str:
        prints: list[str] = []
        for i, entry in enumerate(layers):
            store, _ = _layer(entry, i)
            try:
                idx = store.index()
                if not _present(idx):
                    prints.append("-")
                    continue
                idx.refresh("fast")
                prints.append(idx.head_print())
            except Exception:  # noqa: BLE001 - an unreadable layer prints as "-"
                prints.append("-")
        return sha16_text(dumps([GRAPH_VERSION, head_print(self.repo), prints]))

    def _refs(self, layers: list[tuple[Any, ...]]) -> list[dict[str, list[str]]]:
        out: list[dict[str, list[str]]] = []
        for i, entry in enumerate(layers):
            store, writable = _layer(entry, i)
            try:
                idx = store.index()
                docs = idx.docs() if _present(idx) else {}
                out.append({n: list(d.get("refs") or []) for n, d in docs.items()})
            except Exception:
                if writable:
                    raise  # the project layer failing fails the strong half: no graph
                out.append({})
        return out

    def load(self, layers: list[tuple[Any, ...]]) -> dict[str, Any] | None:
        try:
            old = self._read()
            sp, wp = self.strong_print(layers), self.weak_print()
            if old is not None and old["strong_print"] == sp and old["weak_print"] == wp:
                return old
            data: dict[str, Any] = dict(old) if old is not None else {
                "version": GRAPH_VERSION, "files": [], "strong": {}, "weak": {},
                "strong_print": "", "weak_print": "",
            }
            if data["strong_print"] != sp:
                files = ls_files(self.repo)
                ren = renames(self.repo)
                if files is None or ren is None:
                    return None
                strong = build_strong(self._refs(layers), FileSet(files), ren, self.repo.top)
                data.update(files=files, strong=strong, strong_print=sp)
            if data["weak_print"] != wp:
                data.update(weak=build_weak(self.log.read()), weak_print=wp)
            self._write(data)
            return data
        except Exception:  # noqa: BLE001 - "Graph build fails: w_context is 0" (spec)
            return None

    def _read(self) -> dict[str, Any] | None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not (isinstance(d, dict) and set(d) == _KEYS and _seq(d["version"]) == GRAPH_VERSION):
            return None
        shaped = (
            isinstance(d["strong_print"], str)
            and isinstance(d["weak_print"], str)
            and isinstance(d["files"], list)
            and isinstance(d["strong"], dict)
            and isinstance(d["weak"], dict)
        )
        return d if shaped else None

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(self.path):
            tmp = f"{self.path}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write(dumps(data) + "\n")
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
