"""The cold index: immutable segments, a manifest, and 16 term-hash shards (#204, S3).

`ColdIndex(name, home)` lives at `home/.bantamkit/cold/<name>/` (or `<cold_dir>/<name>/`):

- `seg-<id>.json`  `{"id", "docs": {name: doc}}`, written once and never changed;
- `manifest.json`  `{"version", "segments": [{"id", "docs": [name, ...], "created"}, ...]}`,
  oldest first;
- `shard-<00..15>.json`  `{"terms": {term: [[name, segment_id, field, tf], ...]}}`, a term in
  shard `shard_of(term)` -- the hot index's hash, so both indexes cut terms the same way.

A doc is the hot index's doc (`HotIndex.parse_file`). Postings are #199's `tokenize_v2` over
`name`, `description` and `keywords`, as the hot index's `postings` are.

THE MANIFEST DECIDES. A name held by several segments belongs to the NEWEST one that lists it;
a shard row whose segment does not own its name is not read. So a write lands in an order a
crash cannot make a reader trust: the segment file, then every shard with the new rows (and
without any row the manifest no longer vouches for), then the manifest that makes them live.
`compact()` merges every segment into one the same way and drops the old rows afterwards.

It is DERIVED, like the hot index: `reset()` empties it and the caller re-adds its sources.
It is read only when someone searches (`memory_recall` with `include_archived`), never on the
hook path. Reads go through the builtin `open`, so a test can count them.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .hotindex import SHARDS, _iso, dumps, shard_of
from .lock import exclusive

COLD_VERSION = 1
_ID = re.compile(r"^[0-9]{6}$")


class ColdIndexError(Exception):
    """A manifest, segment or shard that is not what this module wrote: `reset()` and re-add."""


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.loads(fh.read())


def _is_rows(v: Any) -> bool:
    return isinstance(v, list) and all(
        isinstance(r, list)
        and len(r) == 4
        and isinstance(r[0], str)
        and isinstance(r[1], str)
        and isinstance(r[2], str)
        and isinstance(r[3], int)
        and not isinstance(r[3], bool)
        for r in v
    )


class ColdIndex:
    def __init__(self, name: str, home: Path | str, cold_dir: Path | str | None = None):
        bad = not isinstance(name, str) or not name or name in (".", "..")
        if bad or re.search(r"[/\\]", name):
            raise ValueError(f"unknown cold index name: {name!r}")
        self.name = name
        base = Path(cold_dir) if cold_dir is not None else Path(home) / ".bantamkit" / "cold"
        self.dir = base / name
        self.manifest_path = self.dir / "manifest.json"

    # ------------------------------------------------------------------ paths

    def segment_path(self, segment_id: str) -> Path:
        return self.dir / f"seg-{segment_id}.json"

    def shard_path(self, i: int) -> Path:
        return self.dir / f"shard-{i:02d}.json"

    # ------------------------------------------------------------------ reads

    def manifest(self) -> dict[str, Any]:
        """The manifest; an absent one is empty. One this module did not write raises."""
        try:
            data = _read_json(self.manifest_path)
        except FileNotFoundError:
            return {"version": COLD_VERSION, "segments": []}
        except (OSError, ValueError) as e:
            raise ColdIndexError(f"cold index manifest unreadable: {e}") from e
        segs = data.get("segments") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or data.get("version") != COLD_VERSION
            or not isinstance(segs, list)
            or not all(
                isinstance(s, dict)
                and isinstance(s.get("id"), str)
                and _ID.match(s["id"])
                and isinstance(s.get("docs"), list)
                and all(isinstance(n, str) for n in s["docs"])
                and isinstance(s.get("created"), str)
                for s in segs
            )
        ):
            raise ColdIndexError("cold index manifest is not this version's shape")
        return data

    def owners(self) -> dict[str, str]:
        """Each name -> the newest segment that lists it."""
        out: dict[str, str] = {}
        for seg in self.manifest()["segments"]:
            for n in seg["docs"]:
                out[n] = seg["id"]
        return out

    def segment(self, segment_id: str) -> dict[str, dict[str, Any]]:
        """One segment's docs."""
        try:
            data = _read_json(self.segment_path(segment_id))
        except (OSError, ValueError) as e:
            raise ColdIndexError(f"cold index segment {segment_id} unreadable: {e}") from e
        docs = data.get("docs") if isinstance(data, dict) else None
        if not isinstance(docs, dict) or data.get("id") != segment_id:
            raise ColdIndexError(f"cold index segment {segment_id} is not this version's shape")
        return docs

    def doc(self, name: str) -> dict[str, Any] | None:
        """The live doc for `name` (its newest segment's), or `None`."""
        seg = self.owners().get(name)
        if seg is None:
            return None
        return self.segment(seg).get(name)

    def all_docs(self) -> list[dict[str, Any]]:
        """Every doc of every segment, shadowed ones included, oldest segment first."""
        out: list[dict[str, Any]] = []
        for seg in self.manifest()["segments"]:
            out.extend(self.segment(seg["id"]).values())
        return out

    def docs(self) -> dict[str, dict[str, Any]]:
        """`{name: doc}`, each name's newest version."""
        out: dict[str, dict[str, Any]] = {}
        for seg in self.manifest()["segments"]:
            out.update(self.segment(seg["id"]))
        return out

    def _shard(self, i: int) -> dict[str, list[list[Any]]]:
        try:
            data = _read_json(self.shard_path(i))
        except (OSError, ValueError) as e:
            raise ColdIndexError(f"cold index shard {i:02d} unreadable: {e}") from e
        terms = data.get("terms") if isinstance(data, dict) else None
        if not isinstance(terms, dict) or not all(_is_rows(v) for v in terms.values()):
            raise ColdIndexError(f"cold index shard {i:02d} is not this version's shape")
        return terms

    def query(self, terms: Any) -> list[tuple[str, str, int]]:
        """`[(name, segment_id, tf_sum)]`, best first then by name.

        Reads the manifest and only the shards `terms` hash to.
        """
        owners = self.owners()
        if not owners:
            return []
        by_shard: dict[int, list[str]] = {}
        for t in sorted(set(terms)):
            by_shard.setdefault(shard_of(t), []).append(t)
        sums: Counter[str] = Counter()
        for i in sorted(by_shard):
            table = self._shard(i)
            for t in by_shard[i]:
                for name, seg, _field, tf in table.get(t, ()):
                    if owners.get(name) == seg:
                        sums[name] += tf
        ranked = sorted(sums)
        ranked.sort(key=sums.__getitem__, reverse=True)
        return [(n, owners[n], sums[n]) for n in ranked]

    # ----------------------------------------------------------------- writes

    def add(self, docs: dict[str, dict[str, Any]]) -> str:
        """A new immutable segment holding `docs`; its terms merged into the shards. Its id."""
        with exclusive(self._lock_path()):
            manifest = self.manifest()
            seg_id = self._next_id(manifest)
            self._publish(manifest, seg_id, docs, replace=False)
        return seg_id

    def compact(self, keep: Callable[[dict[str, Any]], bool] | None = None) -> str | None:
        """Every segment merged into one (newest version of each name). `None` when already one.

        `keep(doc)` (Retention, J69-6) drops every name whose newest doc it refuses -- a fact
        restored out of `archive/`, a job archive that is gone -- and then a single segment is
        rewritten too, when anything was dropped.
        """
        with exclusive(self._lock_path()):
            manifest = self.manifest()
            old = [s["id"] for s in manifest["segments"]]
            if not old or (len(old) == 1 and keep is None):
                return None
            merged: dict[str, dict[str, Any]] = {}
            for seg in old:
                merged.update(self.segment(seg))
            if keep is not None:
                kept = {n: d for n, d in merged.items() if keep(d)}
                if len(old) == 1 and len(kept) == len(merged):
                    return None
                merged = kept
            seg_id = self._next_id(manifest)
            self._publish(manifest, seg_id, merged, replace=True)
            for seg in old:
                try:
                    self.segment_path(seg).unlink()
                except OSError:
                    pass
        return seg_id

    def reset(self) -> None:
        """Empty the index: every file this module writes is removed."""
        try:
            names = os.listdir(self.dir)
        except OSError:
            return
        for n in names:
            if n == "manifest.json" or re.match(r"^(seg-.*|shard-[0-9]{2})\.json$", n):
                try:
                    (self.dir / n).unlink()
                except OSError:
                    pass

    def _lock_path(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        return self.manifest_path

    def _next_id(self, manifest: dict[str, Any]) -> str:
        last = max((int(s["id"]) for s in manifest["segments"]), default=0)
        return f"{last + 1:06d}"

    def _publish(
        self, manifest: dict[str, Any], seg_id: str, docs: dict[str, dict[str, Any]], replace: bool
    ) -> None:
        """Segment, shards with the new rows, manifest; then (compact) shards without the old."""
        from bantamkit.memory.retrieval import FIELD_BOOST, tokenize_v2

        names = sorted(docs)
        self._write(self.segment_path(seg_id), dumps({"id": seg_id, "docs": docs}))
        new_rows: list[dict[str, list[list[Any]]]] = [{} for _ in range(SHARDS)]
        for name in names:
            d = docs[name]
            text = {
                "name": d["name"],
                "description": d["description"],
                "keywords": " ".join(d["keywords"]),
            }
            for field, _boost in FIELD_BOOST:
                for term, tf in Counter(tokenize_v2(text[field])).items():
                    new_rows[shard_of(term)].setdefault(term, []).append([name, seg_id, field, tf])
        live = {s["id"] for s in manifest["segments"]}
        tables = self._tables()
        self._write_shards(tables, live, new_rows)
        segments = [] if replace else list(manifest["segments"])
        segments.append({"id": seg_id, "docs": names, "created": _iso(time.time())})
        self._write(self.manifest_path, dumps({"version": COLD_VERSION, "segments": segments}))
        if replace:
            self._write_shards(self._tables(), {seg_id}, None)

    def _tables(self) -> list[dict[str, list[list[Any]]]]:
        """Every shard's terms; a missing or unreadable shard is an empty one (it is rewritten)."""
        out = []
        for i in range(SHARDS):
            try:
                out.append(self._shard(i))
            except ColdIndexError:
                out.append({})
        return out

    def _write_shards(
        self,
        tables: list[dict[str, list[list[Any]]]],
        keep: set[str],
        add: list[dict[str, list[list[Any]]]] | None,
    ) -> None:
        for i in range(SHARDS):
            terms: dict[str, list[list[Any]]] = {}
            for term, rows in tables[i].items():
                kept = [r for r in rows if r[1] in keep]
                if kept:
                    terms[term] = kept
            if add is not None:
                for term, rows in add[i].items():
                    terms.setdefault(term, []).extend(rows)
            self._write(self.shard_path(i), dumps({"terms": terms}))

    def _write(self, path: Path, text: str) -> None:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8", newline="\n")
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
