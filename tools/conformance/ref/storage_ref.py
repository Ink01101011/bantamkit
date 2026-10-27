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
    {"op": "bytesruled"}                       -> b64 | null   (`bytes`, compared by a ruling)

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


def _log_bed(bed: dict) -> list:
    seg = LogSegment(Path(bed["path"]))
    out: list = []
    for op in bed["ops"]:
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
        else:
            raise SystemExit(f"storage_ref: unknown storage-log op {kind!r}")
    return out


def storage_log(req: dict) -> dict:
    return {"beds": [_log_bed(b) for b in req.get("beds", [])]}


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


SUITES = {
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
