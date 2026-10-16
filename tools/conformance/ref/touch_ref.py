"""Reference side of the `touch-*` conformance suites (#200).

Imports `bantamkit.touch` rather than copying it, for the reason `usage_ref.py` gives: a hand
copy would be a third implementation that agrees by construction. One request names its
`suite`; each suite's section below answers it. Sections are owned per unit (job70): a unit
adds its own `run_<x>` and one `SUITES` entry and never edits another section.

touch-log (T200-1) — `{"suite": "touch-log", "beds": [{"root", "home", "state", "repo_id",
"ops": [...]}]}` -> `{"beds": [[result, ...], ...]}`, one result per op:

    {"op": "append_touch", "session", "seq", "kind", "path", "via"?, "from"?, "ts"} -> bool
    {"op": "append_use", "session", "seq", "fact", "kind", "ts"}  -> bool
    {"op": "raw", "b64"}                     -> null  (bytes appended to the log verbatim)
    {"op": "read"} / {"op": "tail", "session", "after"} -> rows
    {"op": "skipped"}                        -> int   (after the previous read or tail)
    {"op": "bytes"}                          -> b64 | null (the live log)
    {"op": "next_seq", "session"}            -> int | "error"
    {"op": "current_seq", "session"}         -> int
    {"op": "seqfile", "name"}                -> b64 | null (a file in the state dir)
    {"op": "seqraw", "name", "b64"}          -> null  (a file in the state dir, overwritten)
    {"op": "statelist"}                      -> sorted names in the state dir | null
    {"op": "use_names", "tool", "input", "response"} -> [[fact, kind], ...]
    {"op": "reduce", "rows"}                 -> rows
    {"op": "find_repo", "cwd"}               -> {"top_rel", "gitdir_rel", "id_len"} | null
    {"op": "relpath", "top", "path"}         -> str | null
    {"op": "status"}                         -> the `logs: touch/` lines and the `touch:` line
    {"op": "retention", "now"}               -> {"folded": [...], "rotated": [...]} (home-relative)
    {"op": "listdir", "dir"}                 -> sorted names | null (relative to home)

touch-refs (T200-2) — one request, `run_refs`; its shape is in that section's header.

touch-turn (T200-3) — one request, `run_turn`; its shape is in that section's header.

touch-graph (T200-4) — one request, `run_graph`; its shape is in that section's header.

touch-context (T200-5) — one request, `run_context`; its shape is in that section's header.

touch-summary (T200-6) — one request, `run_summary`; its shape is in that section's header.

touch-bound (T200-10) — one request, `run_bound`; its shape is in that section's header.

Every relative path is relative to the bed `root`; `cwd`/`top`/`path` may be absolute. `HOME`
is the bed's own, set by the harness; no real `~/.bantamkit` is ever opened.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

# ------------------------------------------------------------------- touch-log (T200-1)

from bantamkit.storage import retention as _retention
from bantamkit.storage.tiers import log_lines, touch_line
from bantamkit.touch.log import (
    TouchLog,
    current_seq,
    next_seq,
    touch_reducer,
    use_names,
)
from bantamkit.touch.repo import find_repo, relpath


def _b64(p: Path) -> str | None:
    try:
        return base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return None


def _rel(root: Path, p: str) -> str:
    return Path(os.path.relpath(p, root)).as_posix()


def _abs(root: Path, p: str) -> str:
    return p if os.path.isabs(p) else str(root / p)


def _log_bed(bed: dict[str, Any]) -> list[Any]:
    root = Path(bed["root"])
    home = Path(bed["home"])
    state = bed["state"]
    log = TouchLog(home, bed["repo_id"])
    out: list[Any] = []
    for op in bed["ops"]:
        kind = op["op"]
        if kind == "append_touch":
            out.append(
                log.append_touch(
                    op["session"], op["seq"], op["kind"], op["path"],
                    via=op.get("via"), frm=op.get("from"), ts=op["ts"],
                )
            )
        elif kind == "append_use":
            out.append(log.append_use(op["session"], op["seq"], op["fact"], op["kind"], ts=op["ts"]))
        elif kind == "raw":
            log.path.parent.mkdir(parents=True, exist_ok=True)
            with open(log.path, "ab") as f:
                f.write(base64.b64decode(op["b64"]))
            out.append(None)
        elif kind == "read":
            out.append(log.read())
        elif kind == "tail":
            out.append(log.tail(op["session"], op["after"]))
        elif kind == "skipped":
            out.append(log.skipped)
        elif kind == "bytes":
            out.append(_b64(log.path))
        elif kind == "next_seq":
            try:
                out.append(next_seq(state, op["session"]))
            except OSError:
                out.append("error")
        elif kind == "current_seq":
            out.append(current_seq(state, op["session"]))
        elif kind == "seqfile":
            out.append(_b64(Path(state) / op["name"]))
        elif kind == "seqraw":
            (Path(state) / op["name"]).write_bytes(base64.b64decode(op["b64"]))
            out.append(None)
        elif kind == "statelist":
            try:
                out.append(sorted(os.listdir(state)))
            except OSError:
                out.append(None)
        elif kind == "use_names":
            out.append([list(p) for p in use_names(op["tool"], op["input"], op["response"])])
        elif kind == "reduce":
            out.append(touch_reducer(op["rows"]))
        elif kind == "find_repo":
            r = find_repo(_abs(root, op["cwd"]))
            out.append(
                None
                if r is None
                else {"top_rel": _rel(root, r.top), "gitdir_rel": _rel(root, r.gitdir), "id_len": len(r.id)}
            )
        elif kind == "relpath":
            r = find_repo(_abs(root, op["top"]))
            out.append(None if r is None else relpath(r, _abs(root, op["path"])))
        elif kind == "status":
            out.append([ln for ln in log_lines(home) if ln.startswith("logs: touch/")] + [touch_line(home)])
        elif kind == "retention":
            saved = os.environ.pop(_retention.RETENTION_ENV, None)
            try:
                rep = _retention.run_retention(home, [], op["now"])
            finally:
                if saved is not None:
                    os.environ[_retention.RETENTION_ENV] = saved
            out.append({k: [_rel(home, p) for p in rep[k]] for k in ("folded", "rotated")})
        elif kind == "listdir":
            try:
                out.append(sorted(os.listdir(home / op["dir"])))
            except OSError:
                out.append(None)
        else:
            raise SystemExit(f"touch_ref: unknown touch-log op {kind!r}")
    return out


def run_log(req: dict[str, Any]) -> dict[str, Any]:
    return {"beds": [_log_bed(b) for b in req.get("beds", [])]}


# ------------------------------------------------------------------ touch-refs (T200-2, Task 2)
#
#   {"suite": "touch-refs",
#    "texts": [str, ...], "fields": [{"description", "keywords", "body"}, ...],
#    "files": [str, ...], "renames": {old: new}, "top": str, "resolve": [raw, ...],
#    "probes": [str, ...], "repo": path | null, "repo_resolve": [raw, ...]}
#   -> {"extract": [[raw, ...], ...], "fact_refs": [[raw, ...], ...],
#       "resolve": [[path, sym] | null, ...], "suffix": [[suffix, matches], ...],
#       "matches": [[f, ...], ...],
#       "repo": {"ls_files", "renames": [[old, new], ...] (git's order), "resolve": [...],
#                "head_print"} | null}


def _refs_resolved(r: tuple[str, str | None] | None) -> list[Any] | None:
    return None if r is None else [r[0], r[1]]


def run_refs(req: dict[str, Any]) -> dict[str, Any]:
    from bantamkit.touch.refs import FileSet, extract_refs, fact_refs, resolve_ref, shortest_suffix
    from bantamkit.touch.repo import find_repo, head_print, ls_files, renames

    fs = FileSet(req["files"])
    out: dict[str, Any] = {
        "extract": [extract_refs(t) for t in req["texts"]],
        "fact_refs": [fact_refs(f["description"], f["keywords"], f["body"]) for f in req["fields"]],
        "resolve": [_refs_resolved(resolve_ref(r, fs, req["renames"], req["top"])) for r in req["resolve"]],
        "suffix": [[shortest_suffix(f, fs), fs.matches(shortest_suffix(f, fs))] for f in req["files"]],
        "matches": [fs.matches(p) for p in req["probes"]],
        "repo": None,
    }
    if req.get("repo"):
        repo = find_repo(req["repo"])
        if repo is not None:
            files = ls_files(repo)
            moved = renames(repo)
            rfs = FileSet(files or [])
            out["repo"] = {
                "ls_files": files,
                "renames": None if moved is None else [[k, v] for k, v in moved.items()],
                "resolve": [_refs_resolved(resolve_ref(r, rfs, moved or {}, repo.top)) for r in req["repo_resolve"]],
                "head_print": head_print(repo),
            }
    return out


# ------------------------------------------------------------------ touch-turn (T200-3, Task 3)
#
# `{"suite": "touch-turn", "beds": [{"root", "state", "ops": [...]}]}` -> `{"beds": [[...]]}`.
# The repo is `<root>/repo`, built by the harness; a snapshot is kept under its `as` name.
#
#     {"op": "write", "path", "text"} / {"op": "rm", "path"} / {"op": "git", "args"} -> null
#     {"op": "snapshot", "as"}            -> {path: [xy, "<ns>" | "-", size]} | null
#     {"op": "snapshot_at", "dir"}        -> the same, `find_repo(<root>/<dir>)`
#     {"op": "changed", "a", "b"}         -> [path, ...]
#     {"op": "save_turn", "session", "snap", "seq"} -> null | "error"
#     {"op": "load_turn", "session"}      -> [seq, masked status] | null
#     {"op": "turnfile", "name"}          -> b64 | null (a file in the state dir)
#     {"op": "turnraw", "name", "b64"}    -> null

import subprocess  # noqa: E402

from bantamkit.touch.bashturn import changed, load_turn, save_turn, snapshot  # noqa: E402


def _mask(snap: dict[str, list[Any]] | None) -> dict[str, list[Any]] | None:
    if snap is None:
        return None
    return {p: [e[0], "-" if e[1] == "-" else "<ns>", e[2]] for p, e in snap.items()}


def _turn_bed(bed: dict[str, Any]) -> list[Any]:
    root = Path(bed["root"])
    repo_dir = root / "repo"
    state = bed["state"]
    snaps: dict[str, Any] = {}
    out: list[Any] = []
    for op in bed["ops"]:
        kind = op["op"]
        if kind == "write":
            p = repo_dir / op["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(op["text"].encode("utf-8"))
            out.append(None)
        elif kind == "rm":
            (repo_dir / op["path"]).unlink()
            out.append(None)
        elif kind == "git":
            subprocess.run(["git", "-C", str(repo_dir), *op["args"]], check=True, capture_output=True)
            out.append(None)
        elif kind in ("snapshot", "snapshot_at"):
            r = find_repo(str(root / op.get("dir", "repo")))
            snap = None if r is None else snapshot(r)
            snaps[op.get("as", "")] = snap
            out.append(_mask(snap))
        elif kind == "changed":
            out.append(changed(snaps[op["a"]], snaps[op["b"]]))
        elif kind == "save_turn":
            try:
                save_turn(state, op["session"], snaps[op["snap"]], op["seq"])
                out.append(None)
            except OSError:
                out.append("error")
        elif kind == "load_turn":
            t = load_turn(state, op["session"])
            out.append(None if t is None else [t[0], _mask(t[1])])
        elif kind == "turnfile":
            out.append(_b64(Path(state) / op["name"]))
        elif kind == "turnraw":
            Path(state, op["name"]).write_bytes(base64.b64decode(op["b64"]))
            out.append(None)
        else:
            raise SystemExit(f"touch_ref: unknown touch-turn op {kind!r}")
    return out


def run_turn(req: dict[str, Any]) -> dict[str, Any]:
    return {"beds": [_turn_bed(b) for b in req["beds"]]}


# ----------------------------------------------------------------- touch-graph (T200-4, Task 4)
#
#   {"suite": "touch-graph",
#    "strong": [{"layers": [{fact: [raw, ...]}, ...], "files", "renames", "top"}, ...],
#    "weak": [[row, ...], ...],
#    "beds": [{"home", "index", "repo", "layers": [[label, store, writable], ...],
#              "steps": [...]}, ...]}
#   -> {"strong": [dumps, ...], "weak": [dumps, ...], "beds": [[result, ...], ...]}
#
# `strong`/`weak` answers are `hotindex.dumps` strings, so key order is compared as the file
# writes it. A bed runs with HOME, USERPROFILE and BANTAMKIT_INDEX_DIR at its own; its steps:
#
#     {"op": "load"} / {"op": "load_nogit"}   -> {"data", "file", "rewritten", "moved"}
#         `data` and `file` with the strong print masked (it holds mtime_ns); `rewritten`: the
#         graph file's mtime_ns moved; `moved`: [strong, weak] print moved since the previous
#         load. `load_nogit` runs with PATH empty, so a strong rebuild cannot run git.
#     {"op": "touch", "session", "seq", "kind", "path", "via"?, "from"?, "ts"} -> null
#     {"op": "use", "session", "seq", "fact", "ts"} -> null
#     {"op": "fact", "store", "name", "description", "body"} -> null  (temp-then-rename)
#     {"op": "commit", "path", "text"}      -> null  (write, `git add`, `git commit`)
#     {"op": "corrupt", "text"}             -> null  (the graph file overwritten)

import re as _re  # noqa: E402

_PRINT = _re.compile(r'"strong_print":"[0-9a-f]{16}"')


def _masked(text: str) -> str:
    return _PRINT.sub('"strong_print":"<print>"', text)


def _fact_file(store: str, name: str, desc: str, body: str) -> None:
    d = Path(store) / "facts"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.tmp"
    tmp.write_bytes(
        (
            f"---\nname: {name}\ndescription: {desc}\ntype: project\ncreated: '2026-10-15'\n"
            f"last_recalled: null\nlinks: []\n---\n\n{body}\n"
        ).encode()
    )
    os.replace(tmp, d / f"{name}.md")


def _graph_bed(bed: dict[str, Any]) -> list[Any]:
    import subprocess

    from bantamkit.memory.store import MemoryStore
    from bantamkit.storage.hotindex import dumps
    from bantamkit.touch.graph import TouchGraph

    saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "BANTAMKIT_INDEX_DIR", "PATH")}
    os.environ.update(HOME=bed["home"], USERPROFILE=bed["home"], BANTAMKIT_INDEX_DIR=bed["index"])
    try:
        repo = find_repo(bed["repo"])
        assert repo is not None, bed["repo"]
        layers = [(lab, MemoryStore(p), w) for lab, p, w in bed["layers"]]
        g = TouchGraph(bed["home"], repo)
        log = TouchLog(bed["home"], repo.id)
        prev: dict[str, Any] | None = None
        out: list[Any] = []

        def mtime() -> int | None:
            try:
                return os.stat(g.path).st_mtime_ns
            except OSError:
                return None

        for st in bed["steps"]:
            kind = st["op"]
            if kind in ("load", "load_nogit"):
                before = mtime()
                if kind == "load_nogit":
                    os.environ["PATH"] = ""
                try:
                    data = g.load(layers)
                finally:
                    if saved["PATH"] is not None:
                        os.environ["PATH"] = saved["PATH"]
                try:
                    file = _masked(g.path.read_text(encoding="utf-8"))
                except OSError:
                    file = None
                moved = None
                if data is not None and prev is not None:
                    moved = [data["strong_print"] != prev["strong_print"],
                             data["weak_print"] != prev["weak_print"]]
                if data is not None:
                    prev = data
                out.append({
                    "data": None if data is None else _masked(dumps(data)),
                    "file": file,
                    "rewritten": mtime() != before,
                    "moved": moved,
                })
            elif kind == "touch":
                log.append_touch(st["session"], st["seq"], st["kind"], st["path"],
                                 via=st.get("via"), frm=st.get("from"), ts=st["ts"])
                out.append(None)
            elif kind == "use":
                log.append_use(st["session"], st["seq"], st["fact"], "recall_hit", ts=st["ts"])
                out.append(None)
            elif kind == "fact":
                _fact_file(st["store"], st["name"], st["description"], st["body"])
                out.append(None)
            elif kind == "commit":
                p = Path(bed["repo"]) / st["path"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(st["text"].encode("utf-8"))
                for args in (["add", "-A"], ["commit", "-qm", st["path"]]):
                    subprocess.run(
                        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c",
                         "commit.gpgsign=false", "-C", bed["repo"], *args],
                        check=True, capture_output=True,
                        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
                    )
                out.append(None)
            elif kind == "corrupt":
                g.path.write_bytes(st["text"].encode("utf-8"))
                out.append(None)
            else:
                raise SystemExit(f"touch_ref: unknown touch-graph op {kind!r}")
        return out
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run_graph(req: dict[str, Any]) -> dict[str, Any]:
    from bantamkit.storage.hotindex import dumps
    from bantamkit.touch.graph import build_strong, build_weak
    from bantamkit.touch.refs import FileSet

    return {
        "strong": [
            dumps(build_strong(c["layers"], FileSet(c["files"]), c["renames"], c["top"]))
            for c in req["strong"]
        ],
        "weak": [dumps(build_weak(rows)) for rows in req["weak"]],
        "beds": [_graph_bed(b) for b in req.get("beds", [])],
    }


# --------------------------------------------------------------- touch-context (T200-5)
#
# `{"suite": "touch-context", "windows": [[rows, seq_now], ...],
#   "weights": [[graph, paths, now], ...], "picks": [[graph, paths, exclude, {fact: w}], ...],
#   "labels": [[path, graph], ...], "weight_of": {"w_context", "cases": [[type, stale, u, ctx]]},
#   "switch": [[env | null, via_on], ...]}`
# -> `{"windows": [[path, ...]], "weights": [[[fact, w], ...] sorted], "picks": [[fact, path] | null],
#      "labels": [str], "weight_of": [float], "switch": [bool]}`
# A `ctx`/`u` of "nan" is float("nan"). `weight_of` runs with `retrieval.W_CONTEXT` assigned
# in-process (the Node side calls `setContextWeight`), then restored.


def _num(v: Any) -> float:
    return float("nan") if v == "nan" else float(v)


def run_context(req: dict[str, Any]) -> dict[str, Any]:
    from bantamkit.memory import retrieval
    from bantamkit.touch import context as tc

    w_old = retrieval.W_CONTEXT
    retrieval.W_CONTEXT = _num(req["weight_of"]["w_context"])
    try:
        weighed = [
            retrieval.weight_of(t, bool(st), _num(u), _num(c))
            for t, st, u, c in req["weight_of"]["cases"]
        ]
    finally:
        retrieval.W_CONTEXT = w_old
    switch: list[bool] = []
    env_old, on_old = os.environ.get(tc.VIA_ENV), tc.VIA_ON
    try:
        for env, on in req["switch"]:
            if env is None:
                os.environ.pop(tc.VIA_ENV, None)
            else:
                os.environ[tc.VIA_ENV] = env
            tc.VIA_ON = bool(on)
            switch.append(tc.via_enabled())
    finally:
        tc.VIA_ON = on_old
        if env_old is None:
            os.environ.pop(tc.VIA_ENV, None)
        else:
            os.environ[tc.VIA_ENV] = env_old
    picks = []
    for g, paths, exclude, table in req["picks"]:
        got = tc.via_pick(g, paths, set(exclude), lambda n, t=table: t.get(n))
        picks.append(None if got is None else list(got))
    return {
        "windows": [tc.window(rows, seq) for rows, seq in req["windows"]],
        "weights": [
            sorted([k, v] for k, v in tc.context_weights(g, paths, now).items())
            for g, paths, now in req["weights"]
        ],
        "picks": picks,
        "labels": [tc.via_label(p, g) for p, g in req["labels"]],
        "weight_of": weighed,
        "switch": switch,
    }


# --------------------------------------------------------------- touch-summary (T200-6)
#
# `{"suite": "touch-summary", "ages": [seconds, ...], "prev": [[rows, current], ...],
#   "lines": [[rows, now, table, commits, uncommitted], ...], "compact": [[rows, session, table], ...],
#   "uncommitted": [status, ...], "shift": [[ts, seconds], ...]}`
# -> `{"ages": [str], "prev": [[sid, rows] | null], "lines": [str], "compact": [str],
#      "uncommitted": [int], "shift": [str]}`
# `display` is the fixed `table` (`{path: name}`), a path it does not name shown as itself.

import bantamkit.touch.summary as tsum  # noqa: E402


def run_summary(req: dict[str, Any]) -> dict[str, Any]:
    def show(table: dict[str, str]) -> Any:
        return lambda p: table.get(p, p)

    prev = [tsum.previous_session(rows, cur) for rows, cur in req["prev"]]
    return {
        "ages": [tsum.age_text(s) for s in req["ages"]],
        "prev": [None if p is None else [p[0], p[1]] for p in prev],
        "lines": [
            tsum.last_session_line(rows, now, show(t), commits, u)
            for rows, now, t, commits, u in req["lines"]
        ],
        "compact": [tsum.compact_line(rows, sid, show(t)) for rows, sid, t in req["compact"]],
        "uncommitted": [tsum.uncommitted_count(st) for st in req["uncommitted"]],
        "shift": [tsum.shift_ts(ts, n) for ts, n in req["shift"]],
    }


# ------------------------------------------------------------- touch-bound (T200-10)
# `{"suite": "touch-bound", "git": [[path, pathext, windows], ...], "cutoffs": [b64, ...],
#   "beds": [<a touch-log bed>, ...]}` -> `{"git": [bool, ...], "cutoffs": [str | null, ...],
#   "beds": [[result, ...], ...]}`. `git` asks `git_on_path` with the PATH/PATHEXT given (a
#   simulated Windows when `windows`); `cutoffs` asks `fold_cutoff` of each byte string; a bed
#   runs `_log_bed`'s ops, where an append over `TOUCH_LOG_CAP_BYTES` folds.

#
# T200-11 adds `"bodies": [b64, ...]` -> `"bodies": [b64, ...]` (`bound_body` of each) and
# `"held": [<bed>, ...]` -> `"held": [[result, ...], ...]`, a bed of its own ops:
#
#     {"op": "raw", "b64"} -> null          {"op": "bytes"} -> b64 | null
#     {"op": "append_touch", ...} -> bool   {"op": "bound"} -> bool | "threw"
#     {"op": "lock"} / {"op": "unlock"} -> null  (`<log>.lock` created fresh / removed)
#     {"op": "logdir"} -> null              (the log path made a directory)

from bantamkit.touch.log import bound_body, fold_cutoff  # noqa: E402
from bantamkit.touch.repo import git_on_path  # noqa: E402


def _held_bed(bed: dict[str, Any]) -> list[Any]:
    log = TouchLog(Path(bed["home"]), bed["repo_id"])
    lock = Path(f"{log.path}.lock")
    out: list[Any] = []
    for op in bed["ops"]:
        kind = op["op"]
        if kind in ("raw", "bytes", "append_touch"):
            out += _log_bed({**bed, "ops": [op]})
            continue
        if kind == "bound":
            try:
                out.append(log.bound())
            except Exception:  # noqa: BLE001 - the case is that nothing escapes
                out.append("threw")
            continue
        log.path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "lock":
            lock.write_bytes(b"")
        elif kind == "unlock":
            lock.unlink(missing_ok=True)
        elif kind == "logdir":
            log.path.mkdir()
        else:
            raise ValueError(f"touch-bound: unknown op {kind}")
        out.append(None)
    return out


def run_bound(req: dict[str, Any]) -> dict[str, Any]:
    return {
        "git": [git_on_path(p, e, w) for p, e, w in req.get("git", [])],
        "cutoffs": [fold_cutoff(base64.b64decode(b)) for b in req.get("cutoffs", [])],
        "beds": [_log_bed(bed) for bed in req.get("beds", [])],
        "bodies": [
            base64.b64encode(bound_body(base64.b64decode(b))).decode("ascii")
            for b in req.get("bodies", [])
        ],
        "held": [_held_bed(bed) for bed in req.get("held", [])],
    }


# -------------------------------------------------------------------------- dispatch

SUITES = {
    "touch-log": run_log,
    "touch-refs": run_refs,
    "touch-turn": run_turn,
    "touch-graph": run_graph,
    "touch-context": run_context,
    "touch-summary": run_summary,
    "touch-bound": run_bound,
}


def main() -> None:
    req = json.loads(sys.stdin.read())
    suite = req.get("suite")
    if suite not in SUITES:
        raise SystemExit(f"touch_ref: unknown suite {suite!r}")
    json.dump(SUITES[suite](req), sys.stdout)


if __name__ == "__main__":
    main()
