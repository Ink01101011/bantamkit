"""Reference side of the `storage-*` conformance suites — the storage layer (#204).

Imports `bantamkit.storage` rather than copying it, for the reason `recall_gate_ref.py`
gives: a hand copy would be a third implementation that agrees by construction.

One file serves every storage suite. The request names its suite; each suite adds one
entry to `SUITES` (a function from the request to the answer) and documents its op table
below. Shared by job69 units: append a section, do not reorder the ones above it.

------------------------------------------------------------------------- storage-log

    {"suite": "storage-log", "beds": [{"path", "ops": [...]}, ...]}
      -> {"beds": [[result, ...], ...]}

    {"op": "append", "obj"}                    -> bool
    {"op": "raw", "b64"}                       -> null    (bytes appended to the live file verbatim)
    {"op": "rawfile", "name", "b64"}           -> null    (a file beside the log, written verbatim)
    {"op": "read"}                             -> [row, ...]
    {"op": "skipped"}                          -> int     (after the previous read)
    {"op": "rotate", "max_bytes"}              -> bool
    {"op": "fold", "older_than", "reducer"}    -> null    (reducer named from REDUCERS)
    {"op": "bytes"}                            -> b64 | null   (the live file)
    {"op": "gz", "n"}                          -> b64 | null   (segment n, DECOMPRESSED)
    {"op": "gzraw", "n"}                       -> b64 | null   (segment n as on disk)
    {"op": "listdir"}                          -> sorted names in the log's directory | null
    {"op": "size"}                             -> int     (`.size` after the last append)
    {"op": "fold_lines", "older_than", "reducer"} -> null (older_than may be null; LINE_REDUCERS)
    {"op": "append_numbers"}                   -> bool    (a float and an integer-like key,
                                                           built in code on each side)
    {"op": "ev", "cap"}                        -> bool    (one EventLog record at `<dir>/mcp.jsonl`,
                                                           clock 0; answers `write_failed`)
    {"op": "file", "name"}                     -> b64 | null   (a file beside the log)
    {"op": "bytesruled"}                       -> b64 | null   (`bytes`; the J69-4 caller numbers, a literal per side)

J88-1 (#316 G2) added, after every op above so none of them moves:

    {"op": "append_nonfinite"}                 -> [bool, bool, bool]  (NaN, Infinity, -Infinity)
    {"op": "segments"}                         -> [basename, ...]
    {"op": "mkdir", "name"}                    -> null    (a directory beside the log)
    {"op": "mode", "name"}                     -> int | null  (permission bits of a file beside the log)
    {"op": "write_over", "name", "b64"}        -> null | {"errno": code name}  (beside the log)
    {"op": "rewrite_held", "build"}            -> bool | {"errno": code name}  (build: none|upper|empty)
    {"op": "fold_raises", "reducer"}           -> {"raised": bool}  (reducer: throws|nonjson)

and ANY op that raises answers `{"raises": <type name>}` instead of ending the process, so an
input that makes one runtime raise is a red case rather than a dead harness. The request's
answer also carries `ROTATE_BYTES`.

The Node half of `storage-log.mjs` runs the same ops against `dist/storage/index.js`
with an interpreter written to the same table, and the same reducers.

`storage-lock` (#208) has its op table beside its section, at the end of this file.

----------------------------------------------------------------------- storage-index

    {"suite": "storage-index", "beds": [{"root", "source", "kind", "home", "ops"}, ...],
     "sha16": [path, ...]}
      -> {"beds": [[result, ...], ...], "sha16": [str, ...]}

    {"op": "write", "rel", "b64", "mtime", "dir_mtime"?}  -> null  (bytes at root/rel; utime
                                                       the file, then its directory, in seconds)
    {"op": "unlink", "rel", "dir_mtime"?}              -> null
    {"op": "refresh", "mode"}                          -> "fresh" | "rebuilt" | "patched"
    {"op": "docs"}                                     -> [[name, doc], ...] in code-point order
    {"op": "postings"} / {"op": "df"} / {"op": "skipped"}  -> [[key, value], ...], same order
    {"op": "avgdl"}                                    -> repr(float)
    {"op": "persisted"}                                -> bool
    {"op": "bytes"}                                    -> b64 | null   (the index file)
    {"op": "set", "key", "value"}                      -> null  (one top-level key, re-dumped)
    {"op": "corrupt", "text"}                          -> null  (the index file's whole text)
    {"op": "tree"}                                     -> [[rel, sha256, mtime_ns], ...] under root
    {"op": "shardbytes"}                               -> [[file suffix, text | null], ...] for
                                                          postings-00..15 then words-00..15
    {"op": "query", "terms"} / {"op": "query_words", "words"} -> [[term, value], ...]
    {"op": "segments", "terms"}                        -> [[term, segments], ...]  (undecoded, v4)
    {"op": "corrupt_tail", "text"}                     -> null  (the head's second line replaced)
    {"op": "loose"}                                    -> [file, ...]
    {"op": "corrupt_shard", "family", "i", "text"}     -> null  (one shard file's whole text)
    {"op": "rm_shard", "family", "i"}                  -> null
    {"op": "recall", "query", "k"?, "min_ratio"?}      -> {"fast", "slow", "indexed"}: the names
                                                          `MemoryStore.recall` answers (stamp off)
                                                          as shipped and with `_indexed` forced to
                                                          None (the files), and whether the index
                                                          was eligible; a raise is {"error": text}
    {"op": "lookup", "name"}                           -> {"fast", "slow", "indexed"}, the same way
    {"op": "save", "name", "description", "keywords"?} -> the save's status (today = 2026-10-15)
    {"op": "stamp_lookup", "name"}                     -> the name `lookup(name)` answered, stamped
    {"op": "reopen"}                                   -> null  (a new HotIndex: nothing held)
    {"op": "chmod", "rel", "mode"}                     -> null
    {"op": "envindex", "query"}                        -> {"files", "heads"}: what <home>/envidx
                                                          holds after a recall by a fresh store
                                                          with `INDEX_DIR_ENV` = <home>/envidx

`MemoryStore` ops run over the bed's own `HotIndex` (`store._index = hi`), so every op in a
bed sees one index. Requests also carry "shard_of": [term, ...] -> [int, ...], and
"yaml_skipped": [store root, ...] -> the `skipped` list a recall names there (libyaml, J69-3).

Each side's bed is its own copy at its own path; the harness replaces the bed's realpath and
`full_at` with markers before it compares.

------------------------------------------------------------------------ storage-cold

    {"suite": "storage-cold", "beds": [{"home", "root", "index_dir", "ops"}, ...]}
      -> {"beds": [[result, ...], ...]}

A bed's `ColdIndex("t", home)` serves the direct ops; `root` is a store whose cold index lives
under `index_dir` (set as `INDEX_DIR_ENV` for the bed) and serves the `mem*` ops.

    {"op": "add", "docs": {name: doc}}         -> segment id
    {"op": "query", "terms"}                   -> [[name, segment_id, tf_sum], ...] | {"error": class}
    {"op": "opens", "terms"}                   -> [shard file names the query opened, in order]
    {"op": "docs"}                             -> [[name, doc], ...] code-point order
    {"op": "compact"}                          -> segment id | null
    {"op": "reset"}                            -> null
    {"op": "files"}                            -> [[file, b64], ...] every file in the index dir
                                                  except `*.lock`, sorted
    {"op": "corrupt", "file", "text"}          -> null  (one file of the index dir, whole text)
    {"op": "write", "rel", "b64", "mtime"}     -> null  (bytes at root/rel, mtime in seconds)
    {"op": "archive", "name"} / {"op": "restore", "name"} -> null | {"error": class}
    {"op": "mem", "query", "flag", "k"?}       -> the reply of `Memory(root).recall_outcome`
                                                  with `include_archived=flag`, and its status
                                                  and `returned`
    {"op": "memfiles"}                         -> `files`, for the store's own cold index

------------------------------------------------------------------- storage-retention

    {"suite": "storage-retention", "beds": [{"base", "home", "roots", "index_dir", "ops"}, ...]}
      -> {"beds": [[result, ...], ...]}

    {"op": "env", "off"}                 -> null   (BANTAMKIT_RETENTION=off, or unset)
    {"op": "run", "now"}                 -> report (paths as printed; the suite masks the bed)
    {"op": "tree"}                       -> [[rel, sha256], ...] under base, code-point order
                                            (`idx/` and `*.lock` left out)
    {"op": "file", "rel", "gz"?}         -> b64 | null   (decompressed when `gz`)
    {"op": "cold"}                       -> [[name, text], ...] of roots[0]'s job cold index
    {"op": "search", "rel", "q"}         -> `shiftwork.status(base/rel, search=q)`
    {"op": "child", "now"}               -> retention.json as JSON | null, after
                                            `child_main([roots[0], home], now)`
    {"op": "due", "now"}                 -> bool
    {"op": "ghost"}                      -> null   (a doc `ghost` whose archive file is absent, added)
    {"op": "reducer", "rows"}            -> `hook_log_reducer(rows)`
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit._generated._ts2py_runtime import _js_json_parse
from bantamkit.storage import LogSegment


def _sum_n(older_than: str):
    def reduce(old: list[dict]) -> list[dict]:
        total = sum(r["n"] for r in old if isinstance(r.get("n"), int) and not isinstance(r.get("n"), bool))
        return [{"ts": older_than, "kind": "folded", "lines": len(old), "sum": total}]

    return reduce


REDUCERS = {
    "sum_n": _sum_n,
    "drop": lambda older_than: (lambda old: []),
    "identity": lambda older_than: (lambda old: list(old)),
}

# J69-4: `fold_lines` reducers get `(row, line as read)` pairs and return lines.
LINE_REDUCERS = {
    "lines_reversed": lambda pairs: [line for _, line in reversed(pairs)],
    "lines_none": lambda pairs: [],
}


def _b64(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode("ascii")


def _read_or_none(p: Path) -> bytes | None:
    try:
        return p.read_bytes()
    except OSError:
        return None


def _errno_of(exc: OSError) -> dict:
    import errno as _errno

    return {"errno": _errno.errorcode.get(exc.errno or 0, str(exc.errno))}


BUILDS = {
    "none": lambda data: None,
    "upper": lambda data: data.upper(),
    "empty": lambda data: b"",
}


def _log_bed(bed: dict) -> list:
    seg = LogSegment(Path(bed["path"]))
    out: list = []
    for op in bed["ops"]:
        try:
            _log_op(seg, op, out)
        except Exception as exc:  # noqa: BLE001 - J88-1: a raise is an answer here
            out.append({"raises": type(exc).__name__})
    return out


def _log_op(seg: LogSegment, op: dict, out: list) -> None:
    kind = op["op"]
    if kind == "append":
        out.append(seg.append(op["obj"]))
    elif kind == "raw":
        with open(seg.path, "ab") as f:
            f.write(base64.b64decode(op["b64"]))
        out.append(None)
    elif kind == "rawfile":
        (seg.path.parent / op["name"]).write_bytes(base64.b64decode(op["b64"]))
        out.append(None)
    elif kind == "read":
        out.append(seg.read())
    elif kind == "skipped":
        out.append(seg.skipped)
    elif kind == "rotate":
        out.append(seg.rotate(op["max_bytes"]))
    elif kind == "fold":
        seg.fold(op["older_than"], REDUCERS[op["reducer"]](op["older_than"]))
        out.append(None)
    elif kind in ("bytes", "bytesruled"):
        out.append(_b64(_read_or_none(seg.path)))
    elif kind in ("gz", "gzraw"):
        raw = _read_or_none(Path(f"{seg.path}.{op['n']}.gz"))
        out.append(_b64(gzip.decompress(raw) if raw is not None and kind == "gz" else raw))
    elif kind == "listdir":
        try:
            out.append(sorted(os.listdir(seg.path.parent)))
        except OSError:
            out.append(None)
    elif kind == "size":
        out.append(seg.size)
    elif kind == "fold_lines":
        seg.fold_lines(op["older_than"], LINE_REDUCERS[op["reducer"]])
        out.append(None)
    elif kind == "append_numbers":
        out.append(seg.append({"b": 1, "1": 2, "f": 1.0, "e": 1e-7, "ts": "n"}))
    elif kind == "ev":
        from bantamkit.eventlog import EventLog

        log = EventLog(seg.path.parent / "mcp.jsonl", cap_bytes=op["cap"], clock=lambda: 0)
        log.record("memory_save", "saved", {"z": 1, "a": True})
        out.append(log.write_failed)
    elif kind == "file":
        out.append(_b64(_read_or_none(seg.path.parent / op["name"])))
    elif kind == "append_nonfinite":
        out.append([seg.append({"x": v}) for v in (float("nan"), float("inf"), float("-inf"))])
    elif kind == "segments":
        out.append([p.name for p in seg.segments()])
    elif kind == "mode":
        try:
            out.append(os.stat(seg.path.parent / op["name"]).st_mode & 0o777)
        except OSError:
            out.append(None)
    elif kind == "mkdir":
        (seg.path.parent / op["name"]).mkdir()
        out.append(None)
    elif kind == "write_over":
        from bantamkit.storage import write_over

        try:
            write_over(seg.path.parent / op["name"], base64.b64decode(op["b64"]))
            out.append(None)
        except OSError as exc:
            out.append(_errno_of(exc))
    elif kind == "rewrite_held":
        from bantamkit.storage import rewrite_held

        try:
            out.append(rewrite_held(seg.path, BUILDS[op["build"]]))
        except OSError as exc:
            out.append(_errno_of(exc))
    elif kind == "fold_raises":
        def throws(old):
            raise KeyError("x")

        reducer = throws if op["reducer"] == "throws" else (lambda old: [{"x": float("nan")}])
        try:
            seg.fold("~", reducer)
            out.append({"raised": False})
        except Exception:  # noqa: BLE001
            out.append({"raised": True})
    else:
        raise SystemExit(f"storage_ref: unknown storage-log op {kind!r}")


def storage_log(req: dict) -> dict:
    from bantamkit.storage import ROTATE_BYTES

    return {"beds": [_log_bed(b) for b in req.get("beds", [])], "ROTATE_BYTES": ROTATE_BYTES}


# ------------------------------------------------------------------------- storage-index


def _names(facts) -> list:
    return [str(f.name) for f in facts]


def _name_or_none(fact) -> str | None:
    return None if fact is None else str(fact.name)


def _both(store, call):
    """`call(store)` as shipped, then with the index refused (the files), and the eligibility."""
    seen: list[bool] = []
    shipped = store._indexed

    def spy():
        got = shipped()
        seen.append(got is not None)
        return got

    def run():
        try:
            return call(store)
        except Exception as e:  # noqa: BLE001 -- a raise is an answer here
            return {"error": f"{type(e).__name__}: {e}"}

    store._indexed = spy
    fast = run()
    store._indexed = lambda: None
    slow = run()
    del store._indexed
    return {"fast": fast, "slow": slow, "indexed": bool(seen and seen[0])}


def _index_bed(bed: dict) -> list:
    import hashlib

    from bantamkit.memory.store import MemoryStore
    from bantamkit.storage import HotIndex
    from bantamkit.storage.hotindex import FAMILIES, INDEX_DIR_ENV, SHARDS, dumps

    root = Path(bed["root"])
    hi = HotIndex(Path(bed["source"]), bed["kind"], Path(bed["home"]))
    store = None
    if bed["kind"] == "facts":
        store = MemoryStore(Path(bed["source"]), create=False, today=lambda: "2026-10-15")
        store._index = hi

    def utime(p: Path, t: int | None) -> None:
        if t is not None:
            os.utime(p, (t, t))

    def pairs(d: dict) -> list:
        return [[k, d[k]] for k in sorted(d)]

    out: list = []
    for op in bed["ops"]:
        kind = op["op"]
        if kind == "write":
            p = root / op["rel"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(base64.b64decode(op["b64"]))
            utime(p, op["mtime"])
            utime(p.parent, op.get("dir_mtime"))
            out.append(None)
        elif kind == "unlink":
            p = root / op["rel"]
            p.unlink()
            utime(p.parent, op.get("dir_mtime"))
            out.append(None)
        elif kind == "refresh":
            out.append(hi.refresh(op["mode"]))
        elif kind == "docs":
            out.append(pairs(hi.docs()))
        elif kind == "postings":
            out.append(pairs(hi.postings()))
        elif kind == "df":
            out.append(pairs(hi.df()))
        elif kind == "skipped":
            out.append(pairs(hi.skipped))
        elif kind == "avgdl":
            out.append(repr(hi.avgdl()))
        elif kind == "persisted":
            out.append(hi.persisted)
        elif kind == "bytes":
            out.append(_b64(_read_or_none(hi.path)))
        elif kind == "set":
            data = json.loads(hi.path.read_text(encoding="utf-8"))
            data[op["key"]] = op["value"]
            hi.path.write_text(dumps(data), encoding="utf-8")
            out.append(None)
        elif kind == "corrupt":
            hi.path.write_text(op["text"], encoding="utf-8")
            out.append(None)
        elif kind == "tree":
            rows = []
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames.sort()
                for name in sorted(filenames):
                    p = Path(dirpath) / name
                    rel = p.relative_to(root).as_posix()
                    rows.append([rel, hashlib.sha256(p.read_bytes()).hexdigest(), str(os.stat(p).st_mtime_ns)])
            out.append(sorted(rows))
        elif kind == "shardbytes":
            rows = []
            for family in FAMILIES:
                for i in range(SHARDS):
                    sp = hi.shard_path(family, i)
                    raw = _read_or_none(sp)
                    rows.append([sp.name[len(hi.path.stem) :], None if raw is None else raw.decode()])
            out.append(rows)
        elif kind == "query":
            out.append(pairs(hi.query(op["terms"])))
        elif kind == "segments":
            out.append(pairs(hi.segments(op["terms"])))
        elif kind == "corrupt_tail":
            raw = hi.path.read_bytes()
            hi.path.write_bytes(raw[: raw.index(b"\n") + 1] + op["text"].encode("utf-8"))
            out.append(None)
        elif kind == "query_words":
            out.append(pairs(hi.query_words(op["words"])))
        elif kind == "loose":
            out.append(hi.loose)
        elif kind == "chmod":
            os.chmod(root / op["rel"], op["mode"])
            out.append(None)
        elif kind == "reopen":
            hi = HotIndex(Path(bed["source"]), bed["kind"], Path(bed["home"]))
            if store is not None:
                store._index = hi
            out.append(None)
        elif kind == "corrupt_shard":
            hi.shard_path(op["family"], op["i"]).write_text(op["text"], encoding="utf-8")
            out.append(None)
        elif kind == "rm_shard":
            hi.shard_path(op["family"], op["i"]).unlink()
            out.append(None)
        elif kind == "recall":
            out.append(
                _both(
                    store,
                    lambda st, op=op: _names(
                        st.recall(op["query"], op.get("k"), stamp=False, min_ratio=op.get("min_ratio", 0.0))
                    ),
                )
            )
        elif kind == "lookup":
            out.append(
                _both(
                    store,
                    lambda st, op=op: _name_or_none(st.lookup(op["name"], stamp=False)),
                )
            )
        elif kind == "save":
            res = store.save("project", op["name"], op["description"], "body", keywords=tuple(op.get("keywords", ())))
            out.append(res.status)
        elif kind == "stamp_lookup":
            got = store.lookup(op["name"])
            out.append(None if got is None else str(got.name))
        elif kind == "envindex":
            env_dir = Path(bed["home"]) / "envidx"
            previous = os.environ.get(INDEX_DIR_ENV)
            os.environ[INDEX_DIR_ENV] = str(env_dir)
            try:
                MemoryStore(Path(bed["source"]), create=False).recall(op["query"], stamp=False)
            finally:
                if previous is None:
                    del os.environ[INDEX_DIR_ENV]
                else:
                    os.environ[INDEX_DIR_ENV] = previous
            names = os.listdir(env_dir) if env_dir.is_dir() else None
            out.append(
                None
                if names is None
                else {
                    "files": len(names),
                    "heads": sum(1 for n in names if re.fullmatch(r"[0-9a-f]{16}\.json", n)),
                }
            )
        else:
            raise SystemExit(f"storage_ref: unknown storage-index op {kind!r}")
    return out


def storage_index(req: dict) -> dict:
    from bantamkit.memory.store import MemoryStore
    from bantamkit.storage.hotindex import sha16, shard_of

    def skipped_by(root: str) -> list:
        out: list = []
        MemoryStore(Path(root), create=False).recall("x", stamp=False, skipped=out)
        return out

    return {
        "beds": [_index_bed(b) for b in req.get("beds", [])],
        "sha16": [sha16(p) for p in req.get("sha16", [])],
        "shard_of": [shard_of(t) for t in req.get("shard_of", [])],
        "yaml_skipped": [skipped_by(r) for r in req.get("yaml_skipped", [])],
    }


def _cold_files(d: Path) -> list:
    try:
        names = sorted(n for n in os.listdir(d) if not n.endswith(".lock"))
    except OSError:
        return []
    return [[n, _b64((d / n).read_bytes())] for n in names]


def _cold_bed(bed: dict) -> list:
    import builtins

    from bantamkit.memory.component import Memory
    from bantamkit.memory.store import MemoryStore
    from bantamkit.storage import ColdIndex, ColdIndexError
    from bantamkit.storage.hotindex import INDEX_DIR_ENV

    os.environ[INDEX_DIR_ENV] = bed["index_dir"]
    cold = ColdIndex("t", Path(bed["home"]))
    root = Path(bed["root"])
    out: list = []
    for op in bed["ops"]:
        kind = op["op"]
        if kind == "add":
            out.append(cold.add(op["docs"]))
        elif kind == "query":
            try:
                out.append([list(r) for r in cold.query(op["terms"])])
            except ColdIndexError as e:
                out.append({"error": type(e).__name__})
        elif kind == "opens":
            opened: list = []
            real = builtins.open

            def spy(path, *a, _opened=opened, _real=real, **kw):
                name = os.path.basename(str(path))
                if name.startswith("shard-"):
                    _opened.append(name)
                return _real(path, *a, **kw)

            builtins.open = spy
            try:
                cold.query(op["terms"])
            finally:
                builtins.open = real
            out.append(opened)
        elif kind == "docs":
            d = cold.docs()
            out.append([[k, d[k]] for k in sorted(d)])
        elif kind == "compact":
            out.append(cold.compact())
        elif kind == "reset":
            cold.reset()
            out.append(None)
        elif kind == "files":
            out.append(_cold_files(cold.dir))
        elif kind == "corrupt":
            (cold.dir / op["file"]).write_text(op["text"], encoding="utf-8")
            out.append(None)
        elif kind == "write":
            p = root / op["rel"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(base64.b64decode(op["b64"]))
            os.utime(p, (op["mtime"], op["mtime"]))
            out.append(None)
        elif kind in ("archive", "restore"):
            store = MemoryStore(root, create=False, today=lambda: "2026-10-15")
            try:
                getattr(store, kind)(op["name"])
                out.append(None)
            except Exception as e:  # noqa: BLE001 - the class is the answer
                out.append({"error": type(e).__name__})
        elif kind == "mem":
            m = Memory(root)
            o = m.recall_outcome(
                op["query"], op.get("k"), include_archived=op["flag"], stamp=False
            )
            out.append({"reply": o.reply, "status": o.status, "returned": o.returned})
        elif kind == "memfiles":
            out.append(_cold_files(MemoryStore(root, create=False).cold().dir))
        else:
            raise ValueError(f"unknown op: {kind}")
    return out


def storage_cold(req: dict) -> dict:
    return {"beds": [_cold_bed(b) for b in req.get("beds", [])]}


def _retention_bed(bed: dict) -> list:
    import hashlib

    from bantamkit import shiftwork
    from bantamkit.storage import retention
    from bantamkit.storage.hotindex import INDEX_DIR_ENV

    os.environ[INDEX_DIR_ENV] = bed["index_dir"]
    base = Path(bed["base"])
    home = Path(bed["home"])
    roots = [Path(r) for r in bed["roots"]]
    out: list = []
    for op in bed["ops"]:
        kind = op["op"]
        if kind == "env":
            if op["off"]:
                os.environ[retention.RETENTION_ENV] = "off"
            else:
                os.environ.pop(retention.RETENTION_ENV, None)
            out.append(None)
        elif kind == "run":
            out.append(retention.run_retention(home, roots, op["now"]))
        elif kind == "tree":
            rows = []
            for dirpath, dirs, files in os.walk(base):
                # A link is listed as `<link>` and never descended (os.walk does not follow
                # one); `treeOf` on the Node side does the same (J69-8's link scenario).
                for d in dirs:
                    if (Path(dirpath) / d).is_symlink():
                        rows.append([(Path(dirpath) / d).relative_to(base).as_posix(), "<link>"])
                for f in files:
                    p = Path(dirpath) / f
                    r = p.relative_to(base).as_posix()
                    if r.startswith("idx/") or f.endswith(".lock"):
                        continue
                    data = p.read_bytes()
                    if f.endswith(".gz"):
                        # compared AFTER decompression: zlib builds differ (storage-log's ruling)
                        try:
                            data = gzip.decompress(data)
                        except (OSError, EOFError):
                            pass
                    # retention.json prints this bed's paths: its content is the `child` op's
                    digest = hashlib.sha256(data).hexdigest()
                    rows.append([r, "<state>" if r.endswith("/retention.json") else digest])
            out.append(sorted(rows))
        elif kind == "file":
            data = _read_or_none(base / op["rel"])
            if data is not None and op.get("gz"):
                data = gzip.decompress(data)
            out.append(_b64(data))
        elif kind == "cold":
            d = retention.shiftwork_cold(home, roots[0]).dir
            try:
                names = sorted(n for n in os.listdir(d) if not n.endswith(".lock"))
            except OSError:
                names = []
            out.append([[n, (d / n).read_text(encoding="utf-8")] for n in names])
        elif kind == "search":
            out.append(shiftwork.status(str(base / op["rel"]), search=op["q"]))
        elif kind == "child":
            retention.child_main([str(roots[0]), str(home)], now=op["now"])
            data = _read_or_none(retention.state_path(home))
            out.append(None if data is None else json.loads(data))
        elif kind == "due":
            out.append(retention.due(home, op["now"]))
        elif kind == "ghost":
            cold = retention.shiftwork_cold(home, roots[0])
            doc = {
                "file": ".shiftwork/archive/ghost.json.gz",
                "name": "ghost",
                "description": "gone",
                "type": "shiftwork",
                "keywords": ["ghost"],
                "links": [],
                "tags": [],
                "refs": [],
                "mtime_ns": "0",
                "size": 1,
            }
            cold.add({"ghost": doc})
            out.append(None)
        elif kind == "reducer":
            out.append(retention.hook_log_reducer(op["rows"]))
        else:
            raise ValueError(f"unknown op: {kind}")
    os.environ.pop(retention.RETENTION_ENV, None)
    return out


def storage_retention(req: dict) -> dict:
    return {"beds": [_retention_bed(b) for b in req.get("beds", [])]}


# -------------------------------------------------------------------------- storage-lock (#208)
#
#     {"suite": "storage-lock", "node": <node executable>, "beds": [{"home", "ops"}, ...]}
#       -> {"beds": [[result, ...], ...]}
#
# The log is `<home>/.bantamkit/touch/0123456789abcdef.jsonl`, so `bound` reaches it as a
# `TouchLog`; every other op goes through `LogSegment`.
#
#     {"op": "raw", "b64"}                         -> null  (bytes appended verbatim)
#     {"op": "lock"} / {"op": "unlock"}            -> null  (`<log>.lock` made / removed)
#     {"op": "fold", "older_than", "wait_ms"?}     -> null  (reducer: one row `{"ts", "n"}`)
#     {"op": "fold_lines", "wait_ms"?}             -> null  (the whole file to nothing)
#     {"op": "rotate", "max_bytes", "wait_ms"?}    -> bool
#     {"op": "bound"}                              -> bool  (`TouchLog.bound`)
#     {"op": "append", "obj", "wait_ms"?}          -> bool
#     {"op": "inflight", "chunks": [b64, ...]}     -> null  (marker `<log>.1.ab.writing` made,
#                                                  `inflight_appender.cjs` started on it)
#     {"op": "join"}                               -> null  (that appender has exited)
#     {"op": "bytes"} / {"op": "gz", "n"}          -> b64 | null (`gz` decompressed)
#     {"op": "listdir"}                            -> sorted names beside the log | null
#     {"op": "ro"} / {"op": "rw"}                  -> null  (chmod 555 / 755 the log's dir)
#     {"op": "timed_lock"}                         -> [held, under 500 ms] (default wait)
#     {"op": "timed_append", "obj", "name"?}       -> [ok, under 500 ms]  (default wait; `name`
#                                                  another file in the same dir)


def _count_reducer(older_than: str):
    return lambda old: [{"ts": "2026-10-01T00:00:00Z", "n": len(old)}]


def _lock_bed(node: str, bed: dict) -> list:
    import subprocess
    import time

    from bantamkit.storage import exclusive
    from bantamkit.touch.log import TouchLog

    log = TouchLog(Path(bed["home"]), "0123456789abcdef")
    p = log.path
    p.parent.mkdir(parents=True, exist_ok=True)
    child = None
    out: list = []

    def seg(op: dict) -> LogSegment:
        return LogSegment(p, wait_ms=op["wait_ms"]) if "wait_ms" in op else LogSegment(p)

    for op in bed["ops"]:
        kind = op["op"]
        if kind == "raw":
            with open(p, "ab") as f:
                f.write(base64.b64decode(op["b64"]))
            out.append(None)
        elif kind == "lock":
            Path(f"{p}.lock").write_bytes(b"")
            out.append(None)
        elif kind == "unlock":
            os.unlink(f"{p}.lock")
            out.append(None)
        elif kind == "fold":
            seg(op).fold(op["older_than"], _count_reducer(op["older_than"]))
            out.append(None)
        elif kind == "fold_lines":
            seg(op).fold_lines(None, lambda pairs: [])
            out.append(None)
        elif kind == "rotate":
            out.append(seg(op).rotate(op["max_bytes"]))
        elif kind == "bound":
            out.append(log.bound())
        elif kind == "append":
            out.append(seg(op).append(op["obj"]))
        elif kind == "inflight":
            mark = f"{p}.1.ab.writing"
            Path(mark).write_bytes(b"")
            helper = str(Path(__file__).resolve().parent / "inflight_appender.cjs")
            child = subprocess.Popen([node, helper, str(p), mark, *op["chunks"]])
            out.append(None)
        elif kind == "join":
            child.wait()
            out.append(None)
        elif kind == "bytes":
            out.append(_b64(_read_or_none(p)))
        elif kind == "gz":
            raw = _read_or_none(Path(f"{p}.{op['n']}.gz"))
            out.append(_b64(gzip.decompress(raw) if raw is not None else None))
        elif kind == "listdir":
            try:
                out.append(sorted(os.listdir(p.parent)))
            except OSError:
                out.append(None)
        elif kind in ("ro", "rw"):
            p.parent.chmod(0o555 if kind == "ro" else 0o755)
            out.append(None)
        elif kind == "timed_lock":
            t0 = time.monotonic()
            with exclusive(p) as held:
                pass
            out.append([held, time.monotonic() - t0 < 0.5])
        elif kind == "timed_append":
            target = p.parent / op["name"] if "name" in op else p
            t0 = time.monotonic()
            ok = LogSegment(target).append(op["obj"])
            out.append([ok, time.monotonic() - t0 < 0.5])
        else:
            raise SystemExit(f"storage_ref: unknown storage-lock op {kind!r}")
    return out


def storage_lock(req: dict) -> dict:
    return {"beds": [_lock_bed(req["node"], b) for b in req.get("beds", [])]}


# ----------------------------------------------------------------- storage-j90 (#316 G4 prep)
#
# J90-1 (#316 G4 prep): coverage the four G4 suites lacked, and the inputs on which the
# hand-written runtimes disagree. One entry, sectioned by the suite that owns the cases:
#
#     {"suite": "storage-j90", "section": "index"|"cold"|"retention"|"lock", "dir": <scratch>}
#       -> {name: answer, ...}
#
# Every answer is built here and in `lib/storage_j90.mjs` the same way; a raise is the answer
# `{"raised": <class>, "msg": <sentence>}`, so the suite decides which of the two it compares.
# Mirrored op for op by `lib/storage_j90.mjs`: change one, change both.

_J90_T = 1_700_000_000
_J90_FACT = (
    "---\nname: {n}\ndescription: {d}\ntype: project\ncreated: '2026-08-01'\n"
    "last_recalled: null\nlinks: []\n---\n\nbody [[{n}-link]] see src/{n}.py\n"
)


_DECODE_JSON = [
    "[-0,1,1,0,0]", "[0,1,2.0,0,0]", "[0,1,1.5,0,0]", "[9007199254740993,1,1,0,0]", '[0,"1",1,0,0]',
    "[0,1,null,0,0]", "[0,1,1,0]", "[0,4,1,0,0]", "[1e400,1,1,0,0]", "[0,1,1,0,0,1,1,0,0,2]",
    "[0,1,true,0,0]", "[-1,1,1,0,0]", "[0,0,1,0,0]", "[0,3,1,-1,2,1,2,0,0,5]", '"x"', "{}", "[]",
]


def _j90_try(f):
    try:
        return f()
    except Exception as e:  # noqa: BLE001 -- a raise is an answer here
        return {"raised": type(e).__name__, "msg": str(e)}


def _j90_pin(d: Path) -> None:
    for p in d.iterdir():
        os.utime(p, (_J90_T, _J90_T))
    os.utime(d, (_J90_T, _J90_T))


def _j90_plant_temps(d: Path, entries: list) -> None:
    """J90-3F: `[name, "old" | "fresh" | "olddir"]` planted in `d`; an old one dated `_J90_T`."""
    for name, age in entries:
        p = d / name
        if age == "olddir":
            p.mkdir()
        else:
            p.write_bytes(b"partial")
        if age != "fresh":
            os.utime(p, (_J90_T, _J90_T))


_J90_COLD_TEMPS = [
    ["shard-03.json.4242.tmp", "old"], ["seg-000009.json.17.tmp", "old"], ["manifest.json.4243.tmp", "fresh"],
    ["notes.txt.4242.tmp", "old"], ["shard-03.json.x1.tmp", "old"], ["shard-03.json.tmp", "old"],
    ["manifest.json.99.tmp", "olddir"],
]


def _j90_mangle(raw: bytes, mode: str) -> bytes:
    import re

    if mode == "lens_total_float":
        return re.sub(rb'"lens_total":\[(\d+)', rb'"lens_total":[\1.0', raw, count=1)
    if mode == "full_at_lower":
        return re.sub(rb'"full_at":"([0-9-]{10})T([0-9:]{8})Z"', rb'"full_at":"\1t\2z"', raw, count=1)
    if mode == "shard_invalid_utf8":
        return raw.replace(b'"alpha":', b'"alph\xff":', 1)
    if mode == "shard_seg_float":
        return re.sub(rb'"alpha":\[(\d+),1,', rb'"alpha":[\1,1.0,', raw, count=1)
    if mode == "head_invalid_utf8":  # the first `"beta"` is a name in `cols`, on the first line
        return raw.replace(b'"beta"', b'"bet\xff"', 1)
    if mode == "tail_invalid_utf8":  # a doc's description, on the second line
        return raw.replace(b'"beta alpha words', b'"bet\xff alpha words', 1)
    raise ValueError(mode)


def _j90_index(d: Path) -> dict:
    from bantamkit.storage import hotindex as h

    out: dict = {}

    def bed(name: str, kind: str, files: list) -> tuple[Path, Path]:
        root = d / name
        src = root / "facts" if kind == "facts" else root
        src.mkdir(parents=True)
        for rel, text in files:
            (src / rel).write_text(text, encoding="utf-8", newline="\n")
        _j90_pin(src)
        return root, d / f"{name}-home"

    facts = [
        ["alpha.md", _J90_FACT.format(n="alpha", d="alpha word")],
        ["beta.md", _J90_FACT.format(n="beta", d="beta alpha words, stale? no")],
        ["other-file.md", _J90_FACT.format(n="gamma", d="gamma in another file")],
        ["loose.md", "---\nname: 7\ndescription: loose\ntype: project\n---\n\nb\n"],
    ]
    # 1. The public read API over one clean facts index (each was reached only through recall).
    root, home = bed("reads", "facts", facts)
    hi = h.HotIndex(root, "facts", home)
    hi.refresh("fast")
    doc = hi.doc("alpha")
    out["reads"] = {
        "names": list(hi.names()),
        "doc": doc,
        "doc_missing": hi.doc("nope"),
        "cols": hi.cols(),
        "file_of": [hi.file_of(n) for n in ("alpha", "gamma", "nope")],
        "lens": [hi.lens(n) for n in ("alpha", "beta", "nope")],
        "lens_total": hi.lens_total(),
        "size": hi.size(),
        "exists": hi.exists(),
        "head_print": json.loads(hi.head_print())["shards"],
        "unchecked": sorted(hi.docs_unchecked()),
        "parse_file": list(hi.parse_file(root / "facts" / "beta.md", "5", 9)),
        "parse_file_loose": list(hi.parse_file(root / "facts" / "loose.md", "5", 9)),
        "parse_file_gone": list(hi.parse_file(root / "facts" / "gone.md", "5", 9)),
    }
    hi.invalidate()
    out["reads"]["after_invalidate"] = [hi.exists(), hi.size()]
    out["units"] = {
        "decode": h.decode(["a", "b", "c"], [0, 2, 1, 0, 3, 2, 1, 0, 0, 1]),
        "decode_bad": _j90_try(lambda: h.decode(["a"], [0, 2, 1, 0, 0])),
        # J90-P3: as storage_j90.mjs's DECODE_JSON, each text read as the runtime reads a shard.
        "decode_json": [_j90_try(lambda t=t: h.decode(["a", "b", "c"], _js_json_parse(t)))
                        for t in _DECODE_JSON],
        "encode": h.encode([(0, 1, 0, 0), (1, 1, 0, 0), (2, 0, 2, 0), (4, 0, 2, 0)]),
        "head_text": h.head_text({k: k for k in h.HEAD_KEYS + h.TAIL_KEYS}),
        "constants": [h.INDEX_VERSION, h.FULL_REFRESH_EVERY_S, h.SHARDS, list(h.FAMILIES),
                      list(h.HEAD_KEYS), list(h.TAIL_KEYS), h.SEG, h.DUPLICATE, h.INDEX_DIR_ENV],
    }
    # 2. A head or shard in a shape neither runtime writes, read by a fresh instance.
    for mode in ("lens_total_float", "full_at_lower", "shard_invalid_utf8", "shard_seg_float",
                 "head_invalid_utf8", "tail_invalid_utf8"):
        root, home = bed(mode, "facts", facts[:2])
        hi = h.HotIndex(root, "facts", home)
        hi.refresh("fast")
        p = hi.shard_path("postings", h.shard_of("alpha")) if mode.startswith("shard") else hi.path
        p.write_bytes(_j90_mangle(p.read_bytes(), mode))
        hi = h.HotIndex(root, "facts", home)
        res = {
            "refresh": _j90_try(lambda hi=hi: hi.refresh("fast")),
            "query": _j90_try(lambda hi=hi: sorted(hi.query(["alpha"]).items())),
            "names": _j90_try(lambda hi=hi: list(hi.names())),
            "beta": _j90_try(lambda hi=hi: (hi.doc("beta") or {}).get("description")),
        }
        stamp = json.loads(hi.path.read_text(encoding="utf-8").split("\n", 1)[0][:-1] + "}")["full_at"]
        res["full_at_sep"] = stamp[10:11]
        out[mode] = res
    # 3. Native frontmatter only PyYAML reads: a flow mapping under `metadata:`.
    native = [
        ["flow.md", "---\nname: flow\ndescription: flow meta\nmetadata: {type: user}\n---\n\nb\n"],
        ["plain.md", "---\nname: plain\ndescription: ok\nmetadata:\n  type: reference\n---\n\nb\n"],
    ]
    root, home = bed("native", "native", native)
    hi = h.HotIndex(root, "native", home)
    hi.refresh("fast")
    out["native_flow"] = {"docs": sorted(hi.docs()), "skipped": sorted(hi.skipped)}
    # J90-3F: a persist removes its own index's stale temps and no other index's (lib/storage_j90.mjs).
    root, home = bed("temps", "facts", facts[:2])
    hi = h.HotIndex(root, "facts", home)
    hi.refresh("fast")
    tdir, head = hi.path.parent, hi.path.name
    sha = head[:-5]
    _j90_plant_temps(tdir, [
        [f"{head}.31.tmp", "old"], [f"{sha}.postings-00.json.32.tmp", "old"], [f"{head}.33.tmp", "fresh"],
        ["0000000000000000.json.34.tmp", "old"], [f"{sha}.txt.35.tmp", "old"],
    ])
    (root / "facts" / "gamma.md").write_text(_J90_FACT.format(n="gamma", d="gamma word"), encoding="utf-8", newline="\n")
    again = h.HotIndex(root, "facts", home)
    again.refresh("full")
    out["temps"] = {
        "left": sorted(n.replace(sha, "<sha>") for n in os.listdir(tdir) if n.endswith(".tmp")),
        "names": list(again.names()),
    }
    # J90-P7B: the second line a write reuses only when this process wrote it (lib/storage_j90.mjs).
    root, home = bed("tail", "facts", facts[:2])
    hi = h.HotIndex(root, "facts", home)
    hi.refresh("fast")

    def line2() -> str:
        return hi.path.read_text(encoding="utf-8").split("\n")[1]

    def full():
        x = h.HotIndex(root, "facts", home)
        x.refresh("full")
        return x

    canon = line2()
    full()
    again = line2() == canon
    raw = hi.path.read_text(encoding="utf-8")
    cut = raw.index("\n") + 1
    hi.path.write_text(raw[:cut] + raw[cut:].replace('"df":{', '"df": {', 1), encoding="utf-8", newline="\n")
    spaced = line2() != canon
    full()
    respelled = line2() == canon
    (root / "facts" / "beta.md").write_text(_J90_FACT.format(n="beta", d="beta words moved"), encoding="utf-8", newline="\n")
    moved = full()
    beta = moved.doc("beta")
    out["tail"] = {"again": again, "spaced": spaced, "respelled": respelled, "patched": line2() != canon,
                   "beta": beta["description"] if beta else None}
    # J90-RF (F1): the reuse is keyed on the text this process wrote, not the path (lib/storage_j90.mjs).
    import subprocess

    root, home = bed("stale", "facts", facts[:2])
    opened = f"from bantamkit.storage import hotindex as h; x = h.HotIndex({str(root)!r}, 'facts', {str(home)!r})"

    # J90-RF2: the child imports THIS checkout's package, as the Node side imports this checkout's
    # dist by absolute URL. With no path set it imported whatever `sys.executable` had installed:
    # nothing on a bare `--python` (the suite died "reference script failed (exit 1)"), and another
    # checkout's source from a worktree that borrows that checkout's venv.
    child_env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "runtime-py" / "src")}

    def other(body: str) -> str:
        return subprocess.run([sys.executable, "-c", f"{opened}\n{body}"], check=True, capture_output=True,
                              text=True, encoding="utf-8", env=child_env).stdout.strip()

    h.HotIndex(root, "facts", home).refresh("full")
    (root / "facts" / "beta.md").write_text(_J90_FACT.format(n="beta", d="beta words another process wrote"),
                                           encoding="utf-8", newline="\n")
    other("x.refresh('full')")
    a = h.HotIndex(root, "facts", home)
    a_refresh = a.refresh("full")
    reader = json.loads(other(
        "import json\nd = lambda: (x.doc('beta') or {}).get('description')\nbefore = d()\n"
        "r = x.refresh('fast')\nprint(json.dumps([before, r, d()]))"
    ))
    a_beta = a.doc("beta")
    out["stale"] = {"a_refresh": a_refresh, "a_beta": a_beta["description"] if a_beta else None, "reader": reader}
    # J90-RF (F3): a head doc holding an integer past 2^53, written back by a patch (lib/storage_j90.mjs).
    root, home = bed("unsafe", "facts", facts[:2])
    first = h.HotIndex(root, "facts", home)
    first.refresh("fast")
    raw = first.path.read_bytes()
    first.path.write_bytes(re.sub(rb'("beta":\{[^}]*?"size":)(\d+)', rb"\g<1>9007199254740993", raw, count=1))
    (root / "facts" / "gamma.md").write_text(_J90_FACT.format(n="gamma", d="gamma word"), encoding="utf-8", newline="\n")
    x = h.HotIndex(root, "facts", home)
    refresh = x.refresh("full")
    m = re.search(r'"beta":\{[^}]*?"size":([^,}]+)', x.path.read_text(encoding="utf-8").split("\n")[1])
    out["unsafe"] = {"refresh": refresh, "written": m.group(1) if m else None, "names": list(x.names())}
    # J90-2: a source through a dangling symlink and one through a live symlink (lib/storage_j90.mjs).
    (d / "links" / "real").mkdir(parents=True)
    os.symlink("missing-target", d / "links" / "dangle")
    os.symlink("real", d / "links" / "live")

    def named(link: str, target: str) -> list:
        p = d / "links" / link
        real = h.HotIndex(p, "facts", d / "links-home").real
        return [real.rsplit("/", 1)[-1], h.sha16(p) == h.sha16(d / "links" / target)]

    out["symlinks"] = {
        "dangle": named("dangle", "missing-target"),
        "live": named("live", "real"),
        "below": named("dangle/sub", "missing-target/sub"),
        "cased": named("REAL", "real"),
        "folds": (d / "links" / "REAL").exists(),
    }
    return out


def _j90_cold(d: Path) -> dict:
    from bantamkit.storage import coldindex as c

    out: dict = {}

    def doc(name: str, desc: str, file: str | None = None) -> dict:
        return {"file": file or f"{name}.md", "name": name, "description": desc, "type": "project",
                "keywords": ["kw"], "links": [], "tags": [], "refs": [], "mtime_ns": "1", "size": 1}

    def fresh(name: str):
        ci = c.ColdIndex("t", d / name)
        ci.add({"alpha": doc("alpha", "word one"), "beta": doc("beta", "word two")})
        ci.add({"alpha": doc("alpha", "word newer")})
        return ci

    ci = fresh("reads")
    out["reads"] = {
        "owners": sorted(ci.owners().items()),
        "all_docs": [x["description"] for x in ci.all_docs()],
        "docs": sorted((k, v["description"]) for k, v in ci.docs().items()),
        "doc": ci.doc("alpha"),
        "doc_missing": ci.doc("nope"),
        "manifest_ids": [s["id"] for s in ci.manifest()["segments"]],
        "constants": [c.COLD_VERSION],
    }
    out["bad_name"] = [_j90_try(lambda n=n: c.ColdIndex(n, d)) for n in ("a/b", "..", "")]

    def sub(p: Path, a: bytes, b: bytes) -> None:
        p.write_bytes(p.read_bytes().replace(a, b, 1))

    def run(name: str, mutate) -> dict:
        ci = fresh(name)
        mutate(ci)
        def q():
            try:
                return [list(r) for r in ci.query(["word"])]
            except c.ColdIndexError:
                return {"ColdIndexError": True}

        def one():
            try:
                return ci.doc("beta")
            except c.ColdIndexError:
                return {"ColdIndexError": True}
        return {"query": q(), "doc": one()}

    def tf_float(ci):
        for i in range(16):
            p = ci.shard_path(i)
            if b'"word"' in p.read_bytes():
                sub(p, b'"description",1]', b'"description",1.0]')

    out["tf_float"] = run("tf_float", tf_float)
    # J90-RF (F5, migration entry 2): tf rows summed past 2^53 (lib/storage_j90.mjs).
    ci = fresh("tf_big")
    for i in range(16):
        p = ci.shard_path(i)
        raw = p.read_bytes()
        if b'"two"' in raw:
            p.write_bytes(raw.replace(b'"two":[["beta","000001","description",1]]',
                                      b'"two":[["beta","000001","description",9007199254740993]]'))
    out["tf_big"] = [[n, seg, str(int(score))] for n, seg, score in ci.query(["word", "two"])]
    out["version_true"] = run("version_true", lambda ci: sub(ci.manifest_path, b'"version":1', b'"version":true'))
    out["id_newline"] = run("id_newline", lambda ci: sub(ci.manifest_path, b'"id":"000002"', b'"id":"000002\\n"'))
    out["seg_invalid_utf8"] = run("seg_invalid_utf8", lambda ci: sub(ci.segment_path("000001"), b'"word two"', b'"word tw\xff"'))
    # J90-3: the sentence a ColdIndexError quotes for a read that failed (lib/storage_j90.mjs).
    ci = fresh("msg_syntax")
    ci.manifest_path.write_bytes(b"{not json")
    syntax = _j90_try(ci.manifest)
    ci = fresh("msg_utf8")
    sub(ci.segment_path("000001"), b'"word two"', b'"word tw\xff"')
    utf8 = _j90_try(lambda: ci.segment("000001"))
    ci = fresh("msg_gone")
    ci.segment_path("000001").unlink()
    gone = _j90_try(lambda: ci.segment("000001"))
    # J90-3F: a segment and a shard that are not JSON (lib/storage_j90.mjs).
    ci = fresh("msg_seg_syntax")
    ci.segment_path("000001").write_bytes(b"{not json")
    seg_syntax = _j90_try(lambda: ci.segment("000001"))
    ci = fresh("msg_shard_syntax")
    for i in range(16):
        ci.shard_path(i).write_bytes(b"[1,")
    shard_syntax = _j90_try(lambda: ci.query(["word"]))
    out["messages"] = {"syntax": syntax, "utf8": utf8, "gone": gone, "seg_syntax": seg_syntax,
                       "shard_syntax": shard_syntax}
    # J90-3F: the temps a killed writer left (lib/storage_j90.mjs).
    ci = fresh("temps")

    def temps() -> list:
        return sorted(n for n in os.listdir(ci.dir) if n.endswith(".tmp"))

    _j90_plant_temps(ci.dir, _J90_COLD_TEMPS)
    before = temps()
    ci.add({"gamma": doc("gamma", "word three")})
    add = temps()
    _j90_plant_temps(ci.dir, [["seg-000001.json.18.tmp", "old"]])
    compacted = ci.compact()
    out["temps"] = {"before": before, "add": add, "compact": temps(), "compacted": compacted,
                    "query": [list(r) for r in ci.query(["word"])]}
    # J90-P7B: a shard is parsed again whenever its text is not the one last parsed (lib/storage_j90.mjs).
    ci = fresh("reparse")
    q1 = [list(r) for r in ci.query(["word"])]
    at = next(ci.shard_path(i) for i in range(16) if b'"word"' in ci.shard_path(i).read_bytes())
    kept = at.read_bytes()
    sub(at, b'"word":[["alpha","000001","description",1],["beta","000001","description",1]',
        b'"word":[["alpha","000001","description",1],["beta","000001","description",2]')
    same = len(at.read_bytes()) == len(kept)
    q2 = [list(r) for r in ci.query(["word"])]
    at.write_bytes(kept)
    out["reparse"] = {"q1": q1, "same": same, "q2": q2, "q3": [list(r) for r in ci.query(["word"])]}
    return out


def _j90_retention(d: Path) -> dict:
    from bantamkit.storage import retention as r
    from bantamkit.storage.hotindex import INDEX_DIR_ENV

    out: dict = {}
    saved = {k: os.environ.get(k) for k in (r.RETENTION_ENV, INDEX_DIR_ENV)}
    os.environ[r.RETENTION_ENV] = "on"
    os.environ[INDEX_DIR_ENV] = ""
    try:
        def bed(name: str) -> tuple[Path, Path]:
            home, root = d / name / "home", d / name / "root"
            (home / ".bantamkit").mkdir(parents=True)
            (root / ".shiftwork" / "archive").mkdir(parents=True)
            return home, root

        now = "2026-10-16T00:00:00.000Z"
        # a closed-looking job whose unit status is a list, beside an ordinary closed job
        home, root = bed("list_status")
        sw = root / ".shiftwork"
        (sw / "checkpoint-a.json").write_text(json.dumps({"plan": {"units": [{"status": []}]}}), encoding="utf-8")
        (sw / "checkpoint-b.json").write_text(json.dumps({"plan": {"units": [{"status": "done"}]}}), encoding="utf-8")
        _j90_pin(sw)
        out["list_status"] = {
            "run": _j90_try(lambda: r.run_retention(home, [root], now)),
            "left": sorted(os.listdir(sw)),
        }
        # a cold doc (the job index) with no `file`
        home, root = bed("no_file")
        cold = r.shiftwork_cold(home, root)
        doc = {"name": "j", "description": "", "type": "shiftwork", "keywords": ["x"], "links": [],
               "tags": [], "refs": [], "mtime_ns": "0", "size": 1}
        cold.add({"j": doc})
        cold.add({"k": dict(doc, name="k", file=".shiftwork/archive/k.json.gz")})
        out["no_file_run"] = _j90_try(lambda: r.run_retention(home, [root], now))
        out["no_file_search"] = _j90_try(lambda: r.search_archived(root / ".shiftwork" / "checkpoint.json", "x", home))
        # J90-RF (F4): compaction keeps a job doc while `<root>/<file>` is a file, joined as Node's
        # `path.join` joins: an ABSOLUTE `file` is a path under the root, not the absolute file
        # (lib/storage_j90.mjs). 0.40.0's Python joined with `Path /` and kept those docs.
        home, root = bed("abs_file")
        (root / "real.json").write_text("{}", encoding="utf-8")
        outside = d / "abs_file" / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        cold = r.shiftwork_cold(home, root)

        def jdoc(name: str, file: str) -> dict:
            return {"name": name, "description": "alpha", "file": file, "type": "project", "keywords": [],
                    "links": [], "tags": [], "refs": [], "mtime_ns": "1", "size": 1}

        cold.add({"a": jdoc("a", str(outside)), "b": jdoc("b", "real.json"), "c": jdoc("c", "gone.json"),
                  "d": jdoc("d", "../root/real.json"), "f": jdoc("f", str(root / "real.json"))})
        cold.add({"e": jdoc("e", "real.json")})
        ran = _j90_try(lambda: r.run_retention(home, [root], now))
        out["abs_file"] = {
            "compacted": len(ran["compacted"]) if isinstance(ran, dict) and "compacted" in ran else ran,
            "names": sorted(n for n, *_ in r.shiftwork_cold(home, root).query(["alpha"])),
        }
        # J90-1F: an OSError in search_archived's RETRY (after a ColdIndexError): the live segment
        # renumbered 000002, every shard corrupt, and a DIRECTORY where the rebuild writes 000001.
        import gzip

        home, root = bed("retry_oserror")
        (root / ".shiftwork" / "archive" / "j.json.gz").write_bytes(
            gzip.compress(json.dumps({".shiftwork/checkpoint-j.json": "alpha word"}).encode())
        )
        cp = root / ".shiftwork" / "checkpoint.json"
        first = _j90_try(lambda: r.search_archived(cp, "alpha", home))
        c = r.shiftwork_cold(home, root).dir
        seg = json.loads((c / "seg-000001.json").read_text(encoding="utf-8"))
        seg["id"] = "000002"
        (c / "seg-000002.json").write_text(json.dumps(seg), encoding="utf-8")
        (c / "seg-000001.json").unlink()
        man = json.loads((c / "manifest.json").read_text(encoding="utf-8"))
        man["segments"][0]["id"] = "000002"
        (c / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
        for i in range(16):
            (c / f"shard-{i:02d}.json").write_text("{", encoding="utf-8")
        (c / "seg-000001.json").mkdir()
        out["retry_oserror"] = {"first": first, "retry": _j90_try(lambda: r.search_archived(cp, "alpha", home))}
        # retention.json with a byte that is not UTF-8 outside `ran_at`
        home, _ = bed("due")
        r.state_path(home).write_bytes(b'{"ran_at":"2026-10-16T00:00:00.000Z","note":"\xff"}')
        out["due_invalid_utf8"] = r.due(home, "2026-10-16T01:00:00.000Z")
        out["parse_now"] = [
            _j90_try(lambda s=s: r.parse_now(s))
            for s in ("2026-10-16T00:00:00Z", "2026-10-16T00:00:00.123Z", "0001-01-01T00:00:00Z",
                      "2024-02-29T23:59:59.999Z", "2023-02-29T00:00:00Z", "0000-01-01T00:00:00Z",
                      "2026-10-16T24:00:00Z", "2026-10-16T00:00:60Z", "2026-10-16 00:00:00Z",
                      "2026-10-16T00:00:00", "x", "")
        ]
        out["parse_now_nonstr"] = _j90_try(lambda: r.parse_now(5))
        out["constants"] = [r.RETENTION_ENV, r.SKILL_AUDIT_ENV, r.TTL_S, r.LEDGER_DAYS, r.LOG_DAYS,
                            r.JOB_DAYS, r.STATE_NAME, r.SEARCH_MAX]
        # J90-3F: a run removes the archive and state temps a killed run left (lib/storage_j90.mjs).
        home, root = bed("temps")
        _j90_plant_temps(root / ".shiftwork" / "archive", [
            ["old.json.gz.4242.tmp", "old"], ["new.json.gz.4243.tmp", "fresh"], ["notes.md.4242.tmp", "old"],
            ["x.json.gz.12a.tmp", "old"],
        ])
        _j90_plant_temps(home / ".bantamkit", [
            ["retention.json.77.tmp", "old"], ["retention.json.78.tmp", "fresh"], ["other.json.79.tmp", "old"],
        ])

        def tmps_in(x: Path) -> list:
            return sorted(n for n in os.listdir(x) if n.endswith(".tmp"))

        out["temps"] = {
            "run": _j90_try(lambda: r.run_retention(home, [root], now)),
            "archive": tmps_in(root / ".shiftwork" / "archive"),
            "state": tmps_in(home / ".bantamkit"),
        }
        # J90-3: the opt-out switch read through JS `trim` (lib/storage_j90.mjs).
        out["env_switch"] = []
        for v in ("off\u001c", "\u0085off", "\ufeffoff", " OFF\t", "off\u3000"):
            os.environ[r.RETENTION_ENV] = v
            out["env_switch"].append(r.enabled())
        os.environ[r.RETENTION_ENV] = "on"
        # J90-3: the error a failed sweep records (lib/storage_j90.mjs).
        audit = os.environ.get(r.SKILL_AUDIT_ENV)
        os.environ[r.SKILL_AUDIT_ENV] = "off"
        home, root = bed("child_error")
        code = r.child_main([str(root), str(home)], now="2026-10-16T00:00:00.000Zx")
        out["child_error"] = [code, json.loads(r.state_path(home).read_text(encoding="utf-8")).get("error")]
        # J90-3F: an audit that raises something that is not an OSError (lib/storage_j90.mjs).
        from bantamkit import skillreport

        os.environ[r.SKILL_AUDIT_ENV] = "on"
        home, root = bed("child_audit")
        real_daily = skillreport.daily

        def broke(*_a, **_k):
            raise TypeError("audit broke")

        skillreport.daily = broke
        try:
            audited = _j90_try(lambda: r.child_main([str(root), str(home)], now=now))
        finally:
            skillreport.daily = real_daily
        st = json.loads(r.state_path(home).read_text(encoding="utf-8"))
        out["child_audit"] = [audited, "report" in st, st.get("error")]
        os.environ[r.SKILL_AUDIT_ENV] = "off"
        if audit is None:
            os.environ.pop(r.SKILL_AUDIT_ENV, None)
        else:
            os.environ[r.SKILL_AUDIT_ENV] = audit
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return out


def _j90_lock(d: Path) -> dict:
    import stat as _stat

    from bantamkit.storage import lock

    t = d / "target"
    with lock.exclusive(t) as held:
        mode = _stat.S_IMODE(os.stat(f"{t}.lock").st_mode)
    # J90-1F: a wait for a lock another writer holds, with the WALL clock stepped back 1 s (or on
    # 5 s) after the first reading. The wait is measured on a monotonic clock, so it ends after
    # about `wait_ms` either way: `[held, waited < 1000 ms]`.
    import time as _time

    real = _time.time
    clock = []
    for jump in (-1.0, 5.0):
        Path(f"{t}.lock").write_bytes(b"")
        calls = [0]

        def stepped(jump=jump, calls=calls):
            calls[0] += 1
            return real() + (jump if calls[0] > 1 else 0.0)

        _time.time = stepped
        t0 = _time.monotonic()
        try:
            with lock.exclusive(t, wait_ms=200, stale_ms=60_000) as got:
                pass
        finally:
            _time.time = real
        clock.append([got, (_time.monotonic() - t0) * 1000 < 1000, (_time.monotonic() - t0) * 1000 >= 150])
    os.unlink(f"{t}.lock")
    return {"mode": [held, oct(mode)], "clock": clock,
            "constants": [lock.LOCK_WAIT_MS, lock.LOCK_STALE_MS, lock.LOCK_POLL_MS]}


def storage_j90(req: dict) -> dict:
    d = Path(req["dir"])
    d.mkdir(parents=True, exist_ok=True)
    os.umask(0o022)  # the lock mode is permission bits after the umask: pinned on both sides
    return {"index": _j90_index, "cold": _j90_cold, "retention": _j90_retention, "lock": _j90_lock}[
        req["section"]
    ](d)


SUITES = {
    "storage-j90": storage_j90,
    "storage-cold": storage_cold,
    "storage-index": storage_index,
    "storage-lock": storage_lock,
    "storage-log": storage_log,
    "storage-retention": storage_retention,
}


def main() -> None:
    req = json.loads(sys.stdin.read())
    json.dump(SUITES[req["suite"]](req), sys.stdout)


if __name__ == "__main__":
    main()
