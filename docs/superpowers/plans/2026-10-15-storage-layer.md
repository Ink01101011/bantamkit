# Storage Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo every multi-unit run goes through the shiftwork tools (CLAUDE.md); the unit map is at the end.

**Goal:** Build one storage layer in both runtimes for every agent-facing store: a derived hot index, a shared append-only log segment, a cold index, and daily retention. Recall then stops parsing every fact file on every prompt, and nothing on disk grows without bound (issue #204, milestone 0.37.0-beta).

**Architecture:**
- **Source of truth stays as files:** fact Markdown and checkpoint JSON.
- **New modules:** `storage/` in each runtime holds four parts. `HotIndex` is a single deterministic JSON file per source. `LogSegment` is append-only JSONL with fold and gzip rotation under an O_EXCL lock. `ColdIndex` is immutable segments plus a manifest plus 16 term-hash shards. `Retention` is a daily, detached, verify-before-delete job.
- **Capability tiers:** tier 1 is core and needs only an MCP client; tier 2 needs host hooks; tier 3 needs host data. Tiers 2 and 3 degrade silently.

**Tech Stack:** Python 3.10+ stdlib (`json`, `gzip`, `hashlib`, `os`); TypeScript on Node ≥ 20 (`node:fs`, `node:zlib`, `node:crypto`), no new dependency; the conformance harness `tools/conformance/run.mjs`.

**Spec:** `docs/superpowers/specs/2026-10-15-storage-layer-design.md` (S1–S6).

## Global Constraints

- Both runtimes, in the same unit, with a conformance case (CLAUDE.md "Two runtimes, one surface").
- No new runtime dependency on either side; pure Node at npm runtime; Windows-safe.
- **Files are the source of truth.** Every index can be deleted and rebuilt with nothing lost.
- **Hot path:** the hook reads one index file after one directory `stat`. No fact file is parsed unless the index must be rebuilt.
- **Bar, declared before any number exists:**
  - recall p50 with 180 facts is no slower than 5 ms;
  - recall with 5,000 facts is ≤ 15 ms, against 111 ms today;
  - a full hot build over 5,000 facts takes ≤ 1 s;
  - retention deletes zero files that are not verified in an archive or past their TTL.
- **Retention windows:** ledgers 7 days; log lines folded after 30 days with old segments gzipped; closed `.shiftwork` jobs archived 7 days after closing. Facts are NEVER archived by age.
- **Never move `<checkpoint>.log.jsonl` onto `LogSegment`.** `clock_out` reads its brief lines.
- **Gzip:** conformance compares gzip output after decompression. The compressed bytes are a `ruling:` difference.
- **Mutations:** every new case is proven red by a one-sided mutation, plus one symmetric mutation per suite that is caught only by a per-side literal.
- **Probes and runs:** use a throwaway `HOME` under `$TMPDIR`. Run conformance with `TMPDIR=<own scratchpad>/cleantmp/` after `cd runtime-ts && npm run build`.
- **Gates before each commit:** pytest, `npm test`, `ruff check runtime-py tools`, and `node tools/conformance/run.mjs --all`.
- **No version bump on this branch.**

## Start state

- **Branch:** `feat/199-recall-by-meaning`, the same branch as job68, because job68's units are paused waiting for this layer. The `HotIndex` postings use #199's `tokenize_v2`, which is already on this branch (J68-1, `runtime-py/src/bantamkit/memory/retrieval.py`, `runtime-ts/src/memory/retrieval.ts`).
- **Recall today:** `MemoryStore.recall` loops over `self.facts()`. In Python see `store.py:695`; in Node, `store.ts:953`.
- **The usage ledger is already a log** (J68-4): `runtime-py/src/bantamkit/memory/usage.py` (`UsageLedger`, `fold`) and `runtime-ts/src/memory/usage.ts`.
- **The hook log** is written by `_log` in `runtime-py/src/bantamkit/hookadapter.py:205`, to `<state>/hook-log.jsonl`, plus its Node mirror.
- **Per-session ledgers** are `<state>/ledger-<session>.json`; the path comes from `hookadapter.py:349`.
- **The event log** is `runtime-py/src/bantamkit/eventlog.py` and `runtime-ts/src/eventlog.ts`, gated by `BANTAMKIT_EVENT_LOG`.

## File Structure

| File | Responsibility |
|---|---|
| `runtime-py/src/bantamkit/storage/__init__.py`, `runtime-ts/src/storage/index.ts` | Re-exports |
| `runtime-py/src/bantamkit/storage/lock.py`, `runtime-ts/src/storage/lock.ts` | The O_EXCL lock, lifted from `usage` and `hookadapter` into one place |
| `runtime-py/src/bantamkit/storage/logsegment.py`, `runtime-ts/src/storage/logsegment.ts` | `LogSegment` |
| `runtime-py/src/bantamkit/storage/hotindex.py`, `runtime-ts/src/storage/hotindex.ts` | `HotIndex` |
| `runtime-py/src/bantamkit/storage/coldindex.py`, `runtime-ts/src/storage/coldindex.ts` | `ColdIndex` |
| `runtime-py/src/bantamkit/storage/retention.py`, `runtime-ts/src/storage/retention.ts` | `Retention` |
| `runtime-py/src/bantamkit/storage/tiers.py`, `runtime-ts/src/storage/tiers.ts` | Capability tiers and the status lines |
| `tools/conformance/suites/storage-log.mjs`, `storage-index.mjs`, `storage-cold.mjs`, `storage-retention.mjs` + `ref/storage_ref.py` | Parity suites |
| `docs/storage.md` (new), `docs/memory.md`, `docs/hooks.md`, `docs/conformance.md`, `docs/porting.md` | Docs |

---

### Task 1: The shared lock and `LogSegment`

**Files:**
- Create: `storage/__init__`, `lock`, `logsegment` (both runtimes); `runtime-py/tests/test_storage_log.py`, `runtime-ts/test/storage-log.test.mjs`, `tools/conformance/suites/storage-log.mjs`, `tools/conformance/ref/storage_ref.py`
- Modify: `runtime-py/src/bantamkit/memory/usage.py`, `runtime-ts/src/memory/usage.ts`. These import the lock from `storage/lock` instead of their own copy; the behaviour does not change.

**Interfaces:**
- Produces (Python; Node mirrors it in camelCase):
  - `exclusive(path: Path, wait_ms=2000, stale_ms=10000, poll_ms=5)`, a context manager.
  - `LogSegment(path: Path)` with these members:
    - `.append(obj: dict) -> bool`: writes one line, `json.dumps(obj, ensure_ascii=False, separators=(",", ":"))`, under the lock. Never raises `OSError`.
    - `.read() -> list[dict]`: reads the live file and every `<path>.<n>.gz` in order. Corrupt lines are skipped and counted in `.skipped`.
    - `.fold(older_than: str, reducer: Callable[[list[dict]], list[dict]]) -> None`: lines with `ts < older_than` are replaced by the reducer's output, written temp-then-rename under the lock.
    - `.rotate(max_bytes: int) -> bool`: when the live file exceeds `max_bytes`, it is gzipped to `<path>.<n>.gz` and the live file starts empty.
  - Constants: `ROTATE_BYTES = 1_000_000`.
- Line bytes must match J68-4's `usage` format exactly, so the usage ledger moves onto `LogSegment` with no rewrite. Read the shape from `.shiftwork/notes-job68/J68-4.md`.

- [ ] **Step 1: Failing tests (Python; mirror them in Node)**

```python
import gzip, json
from bantamkit.storage import LogSegment

def test_append_read_roundtrip(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    assert seg.append({"ts": "2026-10-15T00:00:00Z", "k": "ก"})
    assert (tmp_path / "x.jsonl").read_bytes() == '{"ts":"2026-10-15T00:00:00Z","k":"ก"}\n'.encode()
    assert seg.read() == [{"ts": "2026-10-15T00:00:00Z", "k": "ก"}]

def test_rotate_then_read_spans_gz(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    for i in range(50):
        seg.append({"ts": f"2026-10-{1 + i % 28:02d}T00:00:00Z", "i": i})
    assert seg.rotate(max_bytes=100) is True
    assert (tmp_path / "x.jsonl.1.gz").exists() and (tmp_path / "x.jsonl").read_bytes() == b""
    seg.append({"ts": "2026-10-15T00:00:00Z", "i": 50})
    assert [r["i"] for r in seg.read()] == list(range(51))

def test_fold_replaces_only_old_lines(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    seg.append({"ts": "2026-09-01T00:00:00Z", "n": 1}); seg.append({"ts": "2026-09-02T00:00:00Z", "n": 2})
    seg.append({"ts": "2026-10-15T00:00:00Z", "n": 3})
    seg.fold("2026-09-15T00:00:00Z", lambda old: [{"ts": "2026-09-15T00:00:00Z", "sum": sum(r["n"] for r in old)}])
    assert seg.read() == [{"ts": "2026-09-15T00:00:00Z", "sum": 3}, {"ts": "2026-10-15T00:00:00Z", "n": 3}]

def test_corrupt_line_skipped_and_counted(tmp_path):
    p = tmp_path / "x.jsonl"; p.write_text('{"ts":"a"}\n{bad\n', encoding="utf-8")
    seg = LogSegment(p); assert seg.read() == [{"ts": "a"}] and seg.skipped == 1

def test_unwritable_returns_false(tmp_path):
    (tmp_path / "d").write_text("file, not dir")
    assert LogSegment(tmp_path / "d" / "x.jsonl").append({"ts": "a"}) is False
```

- [ ] **Step 2: Run them and see them fail** (`ModuleNotFoundError: bantamkit.storage`).
- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/storage/lock.py
"""The one O_EXCL lock every storage writer takes (was copied in hookadapter and memory/usage)."""
from __future__ import annotations
import os, time
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def exclusive(path: Path, wait_ms: int = 2000, stale_ms: int = 10000, poll_ms: int = 5):
    lock = f"{path}.lock"
    deadline = time.monotonic() + wait_ms / 1000
    held = False
    while not held and time.monotonic() < deadline:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)); held = True
        except OSError:
            try:
                if time.time() - os.stat(lock).st_mtime > stale_ms / 1000:
                    os.unlink(lock)
            except OSError:
                pass
            time.sleep(poll_ms / 1000)
    try:
        yield held
    finally:
        if held:
            try: os.unlink(lock)
            except OSError: pass
```

```python
# runtime-py/src/bantamkit/storage/logsegment.py
"""Append-only JSONL with fold and gzip rotation (#204 S3/S4)."""
from __future__ import annotations
import gzip, json, os, secrets
from pathlib import Path
from typing import Callable
from .lock import exclusive

ROTATE_BYTES = 1_000_000

def _line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"

class LogSegment:
    def __init__(self, path: Path) -> None:
        self.path = Path(path); self.skipped = 0

    def _segments(self) -> list[Path]:
        n = 1; out = []
        while (p := Path(f"{self.path}.{n}.gz")).exists():
            out.append(p); n += 1
        return out

    def append(self, obj: dict) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with exclusive(self.path):
                with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(_line(obj))
            return True
        except OSError:
            return False

    def _parse(self, text: str) -> list[dict]:
        out = []
        for raw in text.split("\n"):
            if not raw:
                continue
            try:
                v = json.loads(raw)
                if isinstance(v, dict): out.append(v); continue
            except ValueError:
                pass
            self.skipped += 1
        return out

    def read(self) -> list[dict]:
        self.skipped = 0; out: list[dict] = []
        for seg in self._segments():
            try: out += self._parse(gzip.decompress(seg.read_bytes()).decode("utf-8", "replace"))
            except OSError: self.skipped += 1
        try: out += self._parse(self.path.read_text(encoding="utf-8", errors="replace"))
        except OSError: pass
        return out

    def _rewrite(self, rows: list[dict]) -> None:
        tmp = Path(f"{self.path}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        with open(tmp, "x", encoding="utf-8", newline="\n") as f:
            f.write("".join(_line(r) for r in rows))
        os.replace(tmp, self.path)

    def fold(self, older_than: str, reducer: Callable[[list[dict]], list[dict]]) -> None:
        with exclusive(self.path):
            rows = self._parse(self.path.read_text(encoding="utf-8", errors="replace")) if self.path.exists() else []
            old = [r for r in rows if str(r.get("ts", "")) < older_than]
            if not old:
                return
            self._rewrite(reducer(old) + [r for r in rows if str(r.get("ts", "")) >= older_than])

    def rotate(self, max_bytes: int = ROTATE_BYTES) -> bool:
        with exclusive(self.path):
            try:
                if self.path.stat().st_size <= max_bytes: return False
                data = self.path.read_bytes()
            except OSError:
                return False
            target = Path(f"{self.path}.{len(self._segments()) + 1}.gz")
            target.write_bytes(gzip.compress(data, mtime=0))
            self.path.write_bytes(b"")
            return True
```

`fold` only folds the live file. Rotated `.gz` segments are folded by `Retention` (Task 6), which reads them, reduces them and rewrites them as one `.gz`.

- [ ] **Step 4: Implement (Node).** Mirror the Python in `runtime-ts/src/storage/lock.ts` and `logsegment.ts`:
  - **lock:** `fs.openSync(lock, 'wx')`, with the same wait, stale and poll timing. Node has no sync sleep, so use `Atomics.wait` on a `SharedArrayBuffer`, as J68-4 did; reuse it.
  - **compression:** `zlib.gzipSync(data)`. Its header mtime is already 0; check the header bytes `1f 8b 08 00 00000000`.
  - **reading:** `zlib.gunzipSync`.
  - **line format:** `JSON.stringify(obj) + '\n'`. Key order follows insertion order on both sides.
  - **temp file:** `${path}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`, opened with `wx`, then `renameSync`.
- [ ] **Step 5: Move `usage` onto the shared lock.** In `usage.py` and `usage.ts`, replace each runtime's private lock with `storage/lock`. Run `--suite recall-usage`; expect 0 failures, so the bytes did not change.
- [ ] **Step 6: Conformance `storage-log.mjs`.** Run the same scripted appends, rotate and fold on each side, then compare:
  - the live file bytes;
  - `read()` output;
  - the decompressed bytes of every `.gz`;
  - `skipped`.

  Add a `ruling:` case: the raw `.gz` bytes may differ between zlib builds. Pin the decompressed equality beside it as a non-ruled case. Per-side literal: after the fold fixture, `read()` equals the exact list.

  Mutations, each with its red count recorded:
  - Node folds rows `ts <= older_than`;
  - Python forgets the `.gz` segments in `read`;
  - both sides drop `ensure_ascii=False`, i.e. JSON.stringify escaping (symmetric);
  - Node does not reset the live file after rotate.
- [ ] **Step 7: Run the gates and commit** (`feat(storage): shared O_EXCL lock and LogSegment, both runtimes (#204)`).

---

### Task 2: `HotIndex`

**Files:**
- Create: `storage/hotindex` (both runtimes), `runtime-py/tests/test_storage_hotindex.py`, `runtime-ts/test/storage-hotindex.test.mjs`, `tools/conformance/suites/storage-index.mjs` (plus ops in `storage_ref.py`)

**Interfaces:**
- Consumes: `tokenize_v2` / `tokenizeV2` (J68-1).
- Produces (Python; Node mirrors it in camelCase):
  - `HotIndex(source: Path, kind: Literal["facts", "native"], home: Path)`
    - The index file is at `home/.bantamkit/index/<sha16(realpath(source) as utf-8)>.json`.
    - A `"facts"` source is `<store>/facts/*.md`. A `"native"` source is `<dir>/*.md` excluding `MEMORY.md`, and is read-only.
  - `.refresh(mode: Literal["fast", "full"]) -> Literal["fresh", "rebuilt", "patched"]`
  - `.docs() -> dict[str, Doc]`, where `Doc = {file, name, description, type, keywords, links, tags, refs, mtime_ns, size}`:
    - `links` is frontmatter `links` plus every `[[x]]` in the body;
    - `tags` is frontmatter `tags` when it is a list of strings;
    - `refs` stays empty until #200 fills it.
  - `.postings() -> dict[str, list[[name, field, tf]]]`, with fields `name`, `description` and `keywords`.
  - `.df() -> dict[str, int]` and `.avgdl() -> float`. `avgdl` uses #199's `FIELD_BOOST` weights, which live in `retrieval`.
  - Constants: `INDEX_VERSION = 1`, `FULL_REFRESH_EVERY_S = 600`.
- **On-disk shape** (deterministic: `json.dumps(…, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`; floats through `pyRound9`):
  `{"version":1,"kind":"facts","source":"<realpath>","dir_mtime_ns":N,"full_at":"<iso>","files":{"<file>":[mtime_ns,size]},"docs":{...},"postings":{...},"df":{...},"avgdl":x}`
- **Parsing:** each fact file is parsed with the store's existing parser, so the index reads exactly what recall reads today. In Python that is `MemoryStore._facts` internals; check the reusable function with `grep -n "def _parse_fact\|def _read_fact\|def _facts" runtime-py/src/bantamkit/memory/store.py`. A `native` file is parsed with the frontmatter reader `divergence.py` uses for the native dir (`grep -n "def " runtime-py/src/bantamkit/memory/divergence.py | head`). An unparsable file is left out of `docs` and listed under `"skipped": {file: reason}`.

- [ ] **Step 1: Failing tests (Python; mirror them in Node)**

```python
from bantamkit.storage import HotIndex

def _fact(d, name, desc, kw=None, body="b", links=None):
    kwl = "".join(f"- {k}\n" for k in (kw or []))
    (d / "facts").mkdir(parents=True, exist_ok=True)
    (d / "facts" / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\n"
        f"links: {links or []}\n" + (f"keywords:\n{kwl}" if kw else "") + f"---\n\n{body}\n", encoding="utf-8")

def test_build_then_fast_is_fresh(tmp_path):
    _fact(tmp_path / "s", "a", "release tag", kw=["ปล่อย"])
    hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home")
    assert hi.refresh("fast") == "rebuilt"
    assert hi.refresh("fast") == "fresh"
    assert hi.docs()["a"]["keywords"] == ["ปล่อย"] and "ปล" in hi.postings()

def test_new_file_via_rename_is_seen_by_fast(tmp_path):
    _fact(tmp_path / "s", "a", "x"); hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home"); hi.refresh("fast")
    _fact(tmp_path / "s", "b", "y")  # write_text creates a new entry: dir mtime moves
    assert hi.refresh("fast") in ("patched", "rebuilt") and "b" in hi.docs()

def test_in_place_edit_missed_by_fast_caught_by_full(tmp_path):
    _fact(tmp_path / "s", "a", "old words"); hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home"); hi.refresh("full")
    p = tmp_path / "s" / "facts" / "a.md"
    import os; st = os.stat(tmp_path / "s" / "facts")
    p.write_text(p.read_text(encoding="utf-8").replace("old words", "new words"), encoding="utf-8")
    os.utime(tmp_path / "s" / "facts", ns=(st.st_atime_ns, st.st_mtime_ns))  # editor that writes in place
    assert hi.refresh("fast") == "fresh" and "old" in hi.postings()
    assert hi.refresh("full") == "patched" and "new" in hi.postings() and "old" not in hi.postings()

def test_corrupt_index_is_rebuilt(tmp_path):
    _fact(tmp_path / "s", "a", "x"); hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home"); hi.refresh("fast")
    hi.path.write_text("{not json", encoding="utf-8")
    assert hi.refresh("fast") == "rebuilt" and "a" in hi.docs()

def test_wiki_links_are_indexed(tmp_path):
    _fact(tmp_path / "s", "a", "x", body="see [[release-lessons]] and [[b]]", links=["c"])
    hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home"); hi.refresh("fast")
    assert hi.docs()["a"]["links"] == ["c", "release-lessons", "b"]

def test_native_source_is_never_written(tmp_path):
    n = tmp_path / "native"; n.mkdir(); (n / "MEMORY.md").write_text("- [x](x.md)\n")
    (n / "x.md").write_text("---\nname: x\ndescription: d\nmetadata:\n  type: feedback\n---\n\nb\n")
    before = {p.name: p.read_bytes() for p in n.iterdir()}
    hi = HotIndex(n, "native", tmp_path / "home"); hi.refresh("full")
    assert {p.name: p.read_bytes() for p in n.iterdir()} == before and hi.docs()["x"]["type"] == "feedback"
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python).** `refresh` works as follows:
  - **Load:** read the index file. If it is missing, unparsable, or its `version`, `kind` or `source` differs, rebuild.
  - **fast:**
    - `os.stat(dir).st_mtime_ns == dir_mtime_ns` and `now - full_at < FULL_REFRESH_EVERY_S` → `"fresh"`.
    - The directory mtime moved → list the directory, then parse only files that are new or whose `(mtime_ns, size)` differ, and drop files that are gone → `"patched"`.
    - The `full_at` age has expired → behave as full.
  - **full:** stat every file and patch exactly as above, then set `full_at`.
  - **After patching:** recompute `df` and `avgdl` from the docs, which is O(docs) and cheap. Write temp-then-rename under `exclusive(path)`.
  - **Index directory unwritable:** keep the result in memory and set `self.persisted = False`. `bantamkit_status` reports this (Task 7).

  Keep the code in one file, with private helpers `_parse_fact(path) -> Doc | (None, reason)`, `_postings(docs)` and `_write()`.
- [ ] **Step 4: Implement (Node)** the same way. Match bytes using the deterministic dump. Node has no `sort_keys`, so write a `stableStringify` that sorts keys by code point (Python's `sort_keys` order). Check first whether one exists: `grep -rn "sortKeys\|stableStringify\|sort_keys" runtime-ts/src | head`.
- [ ] **Step 5: Conformance `storage-index.mjs`.** Use the same fixture store and native directory on both sides:
  - compare the index bytes byte for byte, after replacing `full_at` and `source` with markers;
  - compare `docs`, `postings`, `df` and `avgdl`;
  - compare the refresh results over a scripted sequence: build, fast, add, in-place edit, full, corrupt, rebuild;
  - check that the native directory is unchanged.

  Per-side literals: the `refresh` result sequence, and `links` for the wiki-link fixture.

  Mutations:
  - Node ignores the `full_at` age;
  - Python's fast mode stats every file, which the in-place case must catch as `"patched"` where `"fresh"` was expected;
  - both sides drop wiki links (symmetric);
  - Node writes unsorted keys.
- [ ] **Step 6: Bench script.** Add `tools/eval/storage/bench_hotindex.mjs` and `.py`. Build 5,000 synthetic facts, then time:
  - the full build, against the ≤ 1 s bar;
  - `refresh("fast")` followed by load and `docs()`.

  Record both runtimes in the note.
- [ ] **Step 7: Run the gates and commit** (`feat(storage): HotIndex — deterministic derived index per source, fast/full refresh (#204)`).

---

### Task 3: Recall reads through `HotIndex`; writes are write-through

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/store.py`, `runtime-ts/src/memory/store.ts` (`recall`, `lookup`, `save`, `compact`, `restore`, archive moves), `component.py`/`component.ts` (the layered walk), `dream.py`/`dream.ts` (writes)
- Test: the existing memory suites. Every `store`, `recall-gate`, `recall-strings` and `hooks` case must stay green unchanged, because the index is invisible.

**Interfaces:**
- Consumes: `HotIndex` (Task 2).
- Produces: `MemoryStore.index() -> HotIndex`, built lazily, with `home=Path.home()`.
  - `recall` scores from `index().docs()` in exactly today's v1 way: token overlap on name and description, the same order and the same gate. #199's J68-5 later swaps the scorer onto `postings()`.
  - Every write calls `index().refresh("fast")` after the atomic file write. Because the directory mtime moved, this patches only the written file.
  - `lookup(name)` reads `docs()` to find the file, then parses that one file for the body.

- [ ] **Step 1: Failing test, the bar.** `runtime-py/tests/test_storage_bar.py`:
  - build 5,000 facts in `tmp_path`;
  - warm the index with one `recall`;
  - time 20 more recalls;
  - assert p50 ≤ 15 ms.

  Mirror it in Node. Today's code gives about 111 ms, so the test is red.
- [ ] **Step 2: Implement.** Keep the public behaviour byte-identical: the reply strings, the order, and the skipped-file reporting, which now comes from `index().skipped`.
  - If `persisted` is false, recall still works from the in-memory index, the slow path.
  - Every writer goes through one helper, `_after_write()`, that refreshes the index.
- [ ] **Step 3: Run the whole conformance suite.** Expect 0 failures. Any red is a behaviour change: investigate it, do not re-pin it.
- [ ] **Step 4: Bars.** Run the bench and record recall p50 at 180 facts (≤ 5 ms) and at 5,000 facts (≤ 15 ms) on both runtimes. Record the hook p50 the J67-5 way (`.shiftwork/notes-job67/J67-5.md`).
- [ ] **Step 5: Run the gates and commit** (`perf(memory): recall reads a derived index; writes patch it (#204)`).

---

### Task 4: Logs move onto `LogSegment`

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/usage.py`, `runtime-ts/src/memory/usage.ts`. `UsageLedger` keeps its API, stores through `LogSegment`, and its `fold` becomes the reducer that `LogSegment.fold` calls.
- Modify: `hookadapter.py`/`hookadapter.ts` `_log` / `log` (hook-log), and `eventlog.py`/`eventlog.ts` (the event log's appender).
- Test: `recall-usage`, `hooks` and `eventlog` suites, which must stay green with identical bytes, plus one new rotate case per log.

**Interfaces:**
- Consumes: `LogSegment` (Task 1).
- Produces: none new. The paths and line formats do not change, so the existing `hook-log.jsonl` becomes segment 0 automatically.

- [ ] **Step 1: Failing test.** For each of the three logs, when `ROTATE_BYTES` is patched to 200, writing until it rotates produces `<name>.1.gz`, and `read()` still returns every line. Test both runtimes.
- [ ] **Step 2: Implement.** Each appender calls `LogSegment(path).append(obj)`, then `seg.rotate()` every 100th append. To make that count cheap, use the file size from the `stat` the append already did.
- [ ] **Step 3: Gates.** The `hooks` suite compares hook-log lines; it must stay at 0 failures.
- [ ] **Step 4: Commit** (`refactor(storage): usage ledger, hook-log and event log write through LogSegment (#204)`).

---

### Task 5: `ColdIndex` and `memory_recall({include_archived})`

**Files:**
- Create: `storage/coldindex` (both runtimes), `tools/conformance/suites/storage-cold.mjs`
- Modify: `assets/tools/memory_recall.json` (an optional boolean `include_archived`, default `false`), the `memory_recall` handlers and argument models in both runtimes, and the served-surface and packaging literals, taking each value from the failure output.

**Interfaces:**
- Produces:
  - `ColdIndex(name: str, home: Path)`, at `home/.bantamkit/cold/<name>/`, containing `manifest.json` (`{version, segments: [ {id, docs, created} ]}`), `seg-<id>.json` (docs) and `shard-<00..15>.json`, which hold postings keyed by `sha256(term)[0] % 16`.
  - `.add(docs: dict[str, Doc]) -> str`: writes a new immutable segment, merges its terms into the shards, and returns the segment id.
  - `.query(terms: list[str]) -> list[(name, segment_id, tf_sum)]`: reads only the shards the terms hash to.
  - `.compact()`: merges every segment into one. Retention calls it once a day.
- `include_archived: true` scores `archive/` facts from `ColdIndex("facts-archive-<store_id>")`. Archived hits come after live hits and are tagged `[archived]`. Without the flag, output is byte-identical to today's.

- [ ] **Step 1: Failing tests.**
  - `add` twice, then `query` reads at most `len(set(shard(t) for t in terms))` shard files. Count the opens with a monkeypatched `open` in Python; in Node, count through a `fs` wrapper the module exposes for tests.
  - `compact` keeps the `query` results identical.
  - The `[archived]` tag appears only when `include_archived` is set.
- [ ] **Step 2: Implement both runtimes.** On the first retention run, or the first `include_archived` call, the existing `archive/` is indexed.
- [ ] **Step 3: Conformance.**
  - the manifest bytes, with `created` masked;
  - the shard bytes;
  - the `query` results;
  - `memory_recall` with the flag on and off, through the wire session, with per-side literals.

  Mutations: Node hashes to 8 shards; Python forgets the segment id; and a symmetric case where archived hits come before live hits.
- [ ] **Step 4: Run the gates and commit** (`feat(storage): ColdIndex; memory_recall include_archived (#204)`).

---

### Task 6: `Retention`

**Files:**
- Create: `storage/retention` (both runtimes), `tools/storage/retention-child.mjs` (the detached entry point in the checkout) plus `dist` wiring so the npm package can run it, and `tools/conformance/suites/storage-retention.mjs`
- Modify: the SessionStart arm in `hookadapter.py`/`hookadapter.ts` (spawn once a day), the MCP server startup in `mcpserver.py`/`server.ts` (spawn once a day when the host has no hooks: no `SessionStart` within the TTL), and `shiftwork_status` (an optional `search` argument over archived jobs; its asset and literals change)

**Interfaces:**
- Produces:
  - `run_retention(home: Path, roots: list[Path], now: str) -> RetentionReport`:
    - deletes `hooks/ledger-*.json` files older than 7 days, judged by mtime;
    - folds log lines older than 30 days through each log's reducer: `usage` sums decayed weights, `hook-log` and `eventlog` count by `event`/`tool` per day;
    - gzips old segments;
    - archives every `.shiftwork` job in `roots` whose checkpoint has every unit done or dropped and whose last change is more than 7 days old, into `.shiftwork/archive/<job>.json.gz` (`{relative path: utf8 text | base64 bytes}`). It writes the archive, re-reads and hashes it, and only then deletes the originals. It then adds the job to `ColdIndex("shiftwork-<repo_id>")`.
  - TTL: `~/.bantamkit/retention.json` `{"ran_at": iso}`, at most once per 24 h.
  - `BANTAMKIT_RETENTION=off` makes it a no-op on both sides.
  - `RetentionReport = {deleted, folded, rotated, archived, refused: [{path, reason}]}`.
- `shiftwork_status({checkpoint, search?: str})`: when `search` is given, the response gains a `search` key listing `{job, file, line}` hits from the cold index. Without `search`, the output is byte-identical.

- [ ] **Step 1: Failing tests, run on a trap fixture.** The tree contains:
  - an 8-day-old ledger, which must be deleted;
  - a 6-day-old ledger, which must stay;
  - an OPEN job 30 days old, which must stay;
  - a closed job 8 days old, which must be archived and then deleted;
  - a closed job 6 days old, which must stay;
  - a closed job whose archive write is made to fail (monkeypatch), which must stay and appear in `refused`;
  - `BANTAMKIT_RETENTION=off`, under which nothing changes.

  Assert the tree before and after exactly, as file lists plus hashes.
- [ ] **Step 2: Implement both runtimes.** The spawn uses the update-probe pattern: `detached: true`, `stdio: 'ignore'`, `.unref()`. It never runs inline in a hook.
- [ ] **Step 3: Conformance.** Same trap fixture on both sides; compare the trees and the reports. Per-side literals: the deleted list and the refused list. Mutations:
  - Node deletes before verifying;
  - Python treats an open job as closed;
  - a symmetric change of the 7-day window to 6.
- [ ] **Step 4: Run the gates and commit** (`feat(storage): daily retention — prune, fold, rotate, archive closed jobs, verify before delete (#204)`).

---

### Task 7: Capability tiers and status

**Files:**
- Create: `storage/tiers` (both runtimes)
- Modify: the `bantamkit_status` renderers in both runtimes, and their literals, taken from the failures.
- Create: `tools/conformance/suites/storage-tiers.mjs`: an MCP-only host profile with no hooks registered and no native directory.

**Interfaces:**
- Produces: `tiers(home, cwd) -> {"core": True, "hook": bool, "host_data": bool}`.
  - `hook` is true when the host settings carry bantamkit hooks, read the way `hostinstall` reads them.
  - `host_data` is true when the native resolver answers a directory.
- New `bantamkit_status` lines:
  - `storage: core on; hooks on|off; host data on|off`
  - one `index <kind> <short-source>: <docs> docs, <bytes> bytes, <persisted|in-memory>` line per hot index
  - `logs: <name> <bytes> (<segments> rotated, <skipped> skipped)`
  - `retention: last ran <iso>|never; refused <n>`

- [ ] **Step 1: Failing test.** On the MCP-only profile, every tool runs through a wire session and answers. The status block says `hooks off; host data off`. No tier-2 or tier-3 path raises.
- [ ] **Step 2: Implement both runtimes.** **Step 3: Conformance**, with per-side literals of the status lines. **Step 4: Run the gates and commit.**

---

### Task 8: Docs and reviewer

- [ ] **Docs.**
  - New `docs/storage.md`: the tiers, the hot/cold model, retention, and the SQLite trigger from S5.
  - `docs/memory.md`: recall goes through the index.
  - `docs/hooks.md`: the retention spawn.
  - `docs/conformance.md`: the 5 new suite rows and the suite count.
  - `docs/porting.md`: a gzip-bytes ruling row.
  - Every number quoted comes from the task notes, with the commit it was measured at.
- [ ] **Windows.** Run the retention trap fixture and the `LogSegment` lock under 20 parallel appenders on Windows, or list it as a manual step for the user.
- [ ] **Reviewer unit.** Re-derive all gates on a clean build, re-run every listed mutation, map every spec section to code, and check the four bars. End with MERGEABLE or BLOCKED.

---

## Shiftwork unit map (job69 checkpoint, same branch as job68)

| Unit | Task | Depends on | Role |
|---|---|---|---|
| J69-1 | Task 1 lock + LogSegment | — | implementer / claude-opus-5-5 |
| J69-2 | Task 2 HotIndex | — | implementer |
| J69-3 | Task 3 recall through HotIndex | J69-2 | implementer |
| J69-4 | Task 4 logs onto LogSegment | J69-1 | implementer |
| J69-5 | Task 5 ColdIndex + include_archived | J69-1, J69-3 | implementer |
| J69-6 | Task 6 Retention | J69-4, J69-5 | implementer |
| J69-7 | Task 7 tiers + status | J69-6 | implementer |
| J69-8 | Task 8 docs + Windows + reviewer | J69-7 | reviewer / claude-opus-5-5 |
| J69-9 | blockers | J69-8 | implementer |

- **Wave 1 is J69-1 and J69-2.** Their files are disjoint. Both add a `storage/__init__` re-export, so J69-1 creates the file and J69-2 appends one line, following the shared-file rule.
- **After J69-9,** job68 resumes at J68-5, which scores through `HotIndex.postings()`.
