# Storage: indexes, logs, the cold tier and Retention

Issue #204, milestone 0.37.0-beta, built in job69 (commits `3fa3f06`..`f780012`, reviewed in
J69-8). Spec: `docs/superpowers/specs/2026-10-15-storage-layer-design.md`. Both runtimes carry
the same layer, `runtime-py/src/bantamkit/storage/` and `runtime-ts/src/storage/`, and six
conformance suites compare them (`storage-log`, `storage-lock`, `storage-index`, `storage-cold`,
`storage-retention`, `storage-tiers`; see `docs/conformance.md`).

**Files stay the source of truth.** Fact Markdown and checkpoint JSON are still what you edit,
diff and commit. Every index below is derived: delete it and the next reader rebuilds it, with
nothing lost.

## Where things live

| Path | What | Who writes it | Safe to delete? |
|---|---|---|---|
| `~/.bantamkit/index/<sha16>.json` | Hot-index HEAD for one fact source | recall, lookup, every store write (write-through) | yes, rebuilt on the next read |
| `~/.bantamkit/index/<sha16>.postings-NN.json`, `.words-NN.json` | 16 + 16 term-hash shards of that index | same | yes |
| `~/.bantamkit/index/<sha16>.qterms.json` | #207's term cache: the store's queries sidecar (`~/.bantamkit/queries/<sha16>.json`) with every qdoc already tokenized, stamped with the sha1 of the sidecar bytes it came from (J72-30) | any recall of a store that has a sidecar, in both runtimes, byte for byte | yes; a cache whose sha1 is not the sidecar's is never used, and the next recall rebuilds it |
| `~/.bantamkit/cold/<name>/` | Cold index: `manifest.json`, `seg-<id>.json`, `shard-NN.json` | `memory_recall(include_archived)`, `shiftwork_status(search)`, Retention | yes, rebuilt from the archives on the next search |
| `~/.bantamkit/hooks/hook-log.jsonl` + `.N.gz` | The hook log and its rotated segments | the hook | the `.gz` files are history; see *Logs* |
| `~/.bantamkit/usage/<store>.jsonl` + `.N.gz` | #199's usage ledger | recall and save | it feeds ranking; do not |
| `~/.bantamkit/touch/<repo-id>.jsonl` + `.N.gz` | #200's touch log: one line per Read/Edit/Write, per fact used, per file a Bash turn changed; paths only (`docs/touch.md`) | the hook (PostToolUse, Stop) | it feeds the graph's weak half and the SessionStart summary; deleting it forgets what was touched |
| `~/.bantamkit/graph/<repo-id>.json` | #200's touch graph, a derived index (file -> facts) | the hook (UserPromptSubmit), `memory_recall({file})` | yes, rebuilt on the next load |
| `~/.bantamkit/hooks/ledger-<session>.seq.json`, `.turn.json` | #200's per-session tool-call counter and the turn's `git status` snapshot | the hook | yes; Retention's 7-day ledger rule prunes them |
| `~/.bantamkit/hooks/git-probe.json` | #208's kept answer to "can the `git` on PATH run": `{"key","ok"}`, `key` hashing the candidate's path, mtime and size; believed for 600 s (`docs/touch.md`, *Errors*) | the hook (PostToolUse), both runtimes, byte for byte | yes; the next PostToolUse runs `git --version` again |
| `~/.bantamkit/retention.json` | When Retention last ran, and its report | the Retention child | yes; Retention then runs at the next session start |
| `<repo>/.shiftwork/archive/<job>.json.gz` | A closed job, archived | Retention | **no**: once written, it is the only copy |

`<sha16>` is the first 16 hex characters of the SHA-256 of the source directory's real path, so
two checkouts of one repo get two indexes and a symlinked path gets the same one. The index is
never written inside a store, because the project store is committed and the index must not be.

**`BANTAMKIT_INDEX_DIR`** moves both the hot indexes (`<dir>/<sha16>*.json`) and the cold
indexes (`<dir>/cold/<name>/`) to another directory. Nothing else moves: stores, logs and
`retention.json` stay where they are. The test runners on both sides and the conformance harness
set it to a scratch directory, so no test writes the operator's `~/.bantamkit/index`. An
operator rarely needs it; it exists so a run can be isolated.

## Capability tiers (S2)

| Tier | Needs | Gives | When absent |
|---|---|---|---|
| core | an MCP client | every tool, the hot and cold indexes, the logs, Retention (started by the server) | — |
| hook | bantamkit's hooks in `~/.claude/settings.json` or the project's `.claude/settings{,.local}.json` | automatic injection, the session read ledger, Retention started at SessionStart | silently absent; core is unchanged |
| host data | a host auto-memory directory the native resolver finds | the native index | silently absent |

`bantamkit_status` names them on its storage line (`storage: core on; hooks on|off; host data
on|off`) and follows it with one `index` line per memory layer, one `logs` line and one
`retention` line. See `docs/status.md`. The `storage-tiers` suite drives every one of the 14
tools on an MCP-only profile (no hook, no host data) to pin that tier 1 runs complete alone.

## The hot index

Recall used to parse every fact file on every call, and the hook calls it on every prompt. It
now reads a derived index:

- **HEAD** (`<sha16>.json`): version, source, kind, the directory's mtime, per-file
  `(mtime_ns, size)`, per-doc metadata, `df`, `avgdl`, and the fingerprints of 32 shards. Since
  index version 4 (#199, J68-5) it is ONE JSON object written in TWO LINES: the first holds what
  a recall reads (the stamps, the shard fingerprints, `skipped`, `loose`, and `cols`: per doc, in
  name order, its name, file, BM25 length, type and staleness); the second holds `files`,
  `docs`, `df` and `lens`, and is parsed only by a patch or a full read. At 5,000 facts the
  second line is 1.5 MB of JSON a hook never parses.
- **Shards**: `postings-00..15` (#199's `tokenize_v2` postings, the ranker's input) and
  `words-00..15` (the v1 recall words; nothing reads them since J68-5). A posting list is
  run-length segments over doc ids, `[start, count, tf_name, tf_description, tf_keywords, ...]`,
  so a term every doc holds the same way is five numbers. A term's shard is
  `int(sha256(term)[:8], 16) % 16`, the same on both runtimes. A query loads the HEAD's first
  line and only the shards its words hash to.
- **Refresh.** `fast` is one `stat` of the source directory: every writer bantamkit ships writes
  temp-then-rename, which moves the directory's mtime. `full` stats every file and catches an
  editor that writes in place; it runs when the HEAD's `full_at` is more than 600 s old.
- **Write-through.** `save`, `compact`, `archive`, `restore`, `dream` and a recall's stamp refresh
  an existing index in the same process. A write-through that fails drops the in-memory copy; the
  next reader patches from disk.
- **When the index is NOT used.** If any fact file is unreadable, a name is held by two files, or
  a name is not a string, recall and lookup read the files as before, so the answer never
  changes. That store pays the old cost on every call; `bantamkit_status` still prints its line.
- **Failure.** A missing, corrupt or wrong-version HEAD, or a shard whose fingerprint does not
  match the HEAD, is rebuilt. An index directory that cannot be written gives an index built per
  call (the old speed), and `bantamkit_status` prints `in-memory` instead of `persisted`.

**Coarse-mtime filesystems.** `fast` trusts the directory mtime. On a filesystem whose mtime
resolution is a second or more (HFS+, FAT/exFAT), a second write in the same second as the
index's last refresh is not seen by `fast`, only by the next `full` refresh (at most 600 s
later). APFS, ext4 and NTFS have sub-microsecond mtimes and are not affected. This was left as
is (J69-3 open item 2, J69-8): the stale window is bounded and the files still decide every
exact-name lookup.

### Index version 5: `refs` (#200)

Since `INDEX_VERSION = 5` (job70, #200) every doc's reserved `refs` list is filled: the path
references its text names (a fact: description, each keyword, then body; a `[native]` doc:
description and body), as `extract_refs` finds them (`docs/touch.md`, *References*). The touch
graph reads them from the index and never parses a fact file. A version-4 head is rebuilt on its
next read. `HotIndex.head_print()` (the head's `dir_mtime_ns`, `full_at` and shard prints,
dumped) is the graph's per-layer print: a body-only edit moves no posting but does move `refs`,
so the shard prints alone would leave the graph stale.

## The cold tier

Facts that compaction moved to `archive/`, and jobs that Retention archived, are searchable
without being loaded on the hook path:

- **`memory_recall` with `include_archived: true`** also searches every layer's `archive/`.
  Archived matches come after the live ones, tagged `[archived]`, and are never stamped. Without
  the flag, recall is unchanged. The index is `~/.bantamkit/cold/facts-archive-<store id>/`.
- **`shiftwork_status` with `search: "<words>"`** searches the jobs archived under that
  checkpoint's `.shiftwork/archive/` and answers `search: [{job, file, line}]`: every line (1-based)
  of an archived file that holds every word of the query, at most 50. Without `search`, the reply
  is unchanged. The index is `~/.bantamkit/cold/shiftwork-<repo id>/`.

A cold index is immutable segments plus a manifest plus 16 term-hash shards. It is read only
when one of those two calls asks, never by the hook.

## Logs

`LogSegment` is an append-only JSONL file under the shared O_EXCL lock. **No line is lost to a
rewrite (#208).** A fold, a rotation and the touch bound rewrite the live file only while the
lock is actually held (a 2 s wait that runs out skips the rewrite; the next call retries). An
append whose own wait ran out still writes, unlocked, but under a marker
`<name>.<pid>.<hex>.writing` it creates before opening the log and removes after its line is
written. The rewrite keeps the old file by a hard link `<name>.<pid>.<hex>.keep`, renames the new
body in, waits for every marker present after the rename to go (one older than 10 s is a dead
appender's and is removed; the wait is capped at 5 s), and appends what the old file grew past
what it read, read to EOF. A file system without hard links is never rewritten. A directory that
refuses the lock file (`EACCES`, `EPERM`, `EROFS`, no lock file there: a read-only usage or touch
directory) gives the lock up at once instead of waiting 2 s on every save and recall.

The hook log and the
usage ledger rotate once an append leaves the live file past 1,000,000 bytes: the live file is
gzipped whole into `<name>.1.gz` (then `.2.gz`, ...) and a fresh live file starts. Nothing is
dropped by rotation. To read a log whole, read the segments in number order, then the live
file:

```sh
cd ~/.bantamkit/hooks
for n in $(ls hook-log.jsonl.*.gz 2>/dev/null | sed 's/.*\.\([0-9]*\)\.gz/\1/' | sort -n); do
  gzip -dc "hook-log.jsonl.$n.gz"
done; cat hook-log.jsonl
```

`tools/ledger/injection-precision.mjs` reads the segments that way since J69-8. The event log
(`BANTAMKIT_EVENT_LOG`) appends through `LogSegment` but keeps its own documented two-file `.1`
rotation (`docs/eventlog.md`).

## Retention

Once a day, a detached and silent child does five things, in this order:

1. **Ledgers.** Deletes `~/.bantamkit/hooks/ledger-*.json` (per-session read ledgers) whose mtime
   is MORE than 7 days old. Nothing archives them: past their TTL they are not needed.
2. **Logs.** Folds every LIVE hook-log line older than 30 days into one
   `{"ts": "<day>T00:00:00.000Z", "event": "Folded", "counts": {...}}` row per day, counting each
   `event` (or `event/tool`). Folds each usage ledger's lines older than 30 days through its own
   reducer, at the cutoff, so the weights it keeps are unchanged. Rotated `.N.gz` segments are
   never rewritten. The event log is not folded.
3. **Idle logs.** A log whose live file was last written more than 30 days ago is gzipped into its
   next segment.
4. **Closed jobs.** In the `.shiftwork/` directly under the session's working directory (no
   walk-up), a job whose units are ALL `done` or `dropped`, and whose newest file is more than 7
   days old, is bundled into `.shiftwork/archive/<job>.json.gz`. The bundle holds the checkpoint,
   its `.log.jsonl`, and every regular file under `briefs-<job>/` and `notes-<job>/`. A
   `briefs-<job>` or `notes-<job>` that is a link to another directory is not followed (J69-8).
5. **Cold indexes.** Archived jobs are indexed for `shiftwork_status(search)`; every cold index is
   compacted, dropping names whose archive file is gone.

**Touch logs (#200).** Step 2 also folds each `touch/<repo-id>.jsonl` once its live file holds a
line older than 30 days that is not already a `folded` row: every `read`/`edit`/`write` line
becomes one `{"op":"folded","path","ts","n"}` row per path keeping its last `ts` and its count,
and old `use` lines are dropped. A second pass is a no-op. Step 3 rotates an idle touch log like
any other. The touch log is never rotated on append, but since T200-10 it is FOLDED on append:
an append that leaves the live file over `TOUCH_LOG_CAP_BYTES = 1,000,000` folds its older half
the same way, under the same lock and only while it is actually held, ageing folded rows out
oldest `ts` first until the file is at or under `TOUCH_LOG_FOLD_TARGET_BYTES = 750,000`
(T200-11; `docs/touch.md`, *Errors*), so with Retention off the live size stays under the cap
rather than 30 days of activity. Measured at 0d33d03 on a synthetic log (Node hook, 15 cold runs,
`.shiftwork/notes-job70/T200-9.md`): a `UserPromptSubmit` after a tool call costs 60 ms p50 on an
empty log, 101 ms at 20,000 lines (1.9 MB) and 146 ms at 60,000 (5.6 MB), because the graph's
weak half re-reads the whole log; this repository's real eval corpus held about 1,300 rows.
Since T200-10 that cost is not paid while the context is inert (`W_CONTEXT = 0`, via off): the
same bench measures 57.7 / 57.8 ms p50 against 101.5 / 103.2 ms before
(`.shiftwork/notes-job70/T200-10.md`).

**Facts are never archived by age.** Compaction (budget- and usage-based) is still the only thing
that moves a fact to `archive/`.

### Verify, then delete

A job's files are deleted only after all of this holds, in order; any failure deletes nothing
and lists the job under `refused` in `retention.json`:

1. The archive is written temp-then-rename and flushed to the disk (`fsync` of the file, and of
   its directory on POSIX; J69-8).
2. It is read back, decompressed, and its SHA-256 matches what was bundled.
3. Every original is read again and still has the bytes that were bundled (a live session may
   have written one since), and the checkpoint is still closed.

An open job, a checkpoint that does not parse (a BOM, a `NaN`, broken JSON), an empty plan, and
an existing archive of the same name with different content are never touched.

### What it will do to a repository

Measured by J69-6 on a COPY of this repository's `.shiftwork/` (2026-10-16): 25 closed jobs
archived, `.shiftwork` 11 MB → 8.9 MB, 0 deleted outside them, 0 refused. A path such as
`.shiftwork/notes-job64/J64-2.md` that a memory or a commit message cites is then inside
`.shiftwork/archive/job64.json.gz`, not at its path. To find it, use `shiftwork_status(search=…)`,
or read the bundle, which is JSON of `{relative path: text | {"base64": bytes}}`:

```sh
python3 -c "import gzip,json,sys; b=json.loads(gzip.decompress(open(sys.argv[1],'rb').read())); print(b[sys.argv[2]])" \
  .shiftwork/archive/job64.json.gz .shiftwork/notes-job64/J64-2.md
```

To put a whole job back, write each key of the bundle to its path (a `{"base64": …}` value is
binary). Retention never re-archives a job whose archive already holds the same bytes.

### When it runs

- **Trigger.** The `SessionStart` hook calls it; the MCP server calls it at start too, but stands
  down when the hook log was written within the last 24 h (a hook is installed and will do it).
- **Once a day.** `~/.bantamkit/retention.json` holds `{"ran_at": "<ISO>"}`, then
  `{"ran_at", "report": {archived, compacted, deleted, folded, refused, rotated}}` or
  `{"ran_at", "error": "<class>"}`. It is due again 24 h after `ran_at`. The claim is taken under
  the lock before the run, so two sessions starting together run it once; a run that fails is
  retried the next day.
- **Which home.** The child is started as `python -m bantamkit.storage.retention <cwd> <home>` or
  `node dist/storage/retention-child.js <cwd> <home>` (`tools/storage/retention-child.mjs` is the
  checkout's entry to the same file). It acts on the home named on its command line, never one it
  derives, and does nothing without both arguments. (J69-6's first draft derived it; a test that
  passed a scratch home ran it on a real one.)
- **No home, no run.** Without `~/.bantamkit` it does nothing.

### Turning it off

`BANTAMKIT_RETENTION=off` (also `0`, `false`, `no`, any case) makes the spawn, the child and the
run no-ops on both runtimes; `bantamkit_status` then prints `retention: off; …`. Set it where the
process that would start it gets its environment: the `env` block of `~/.claude/settings.json`
covers the hooks, and the MCP entry's `env` covers the server.

```json
{ "env": { "BANTAMKIT_RETENTION": "off" } }
```

The test runners on both sides and the conformance harness set it suite-wide; a retention test
turns it back on only for its own scratch home.

## Numbers, and where they come from

The bar was declared before any number existed (spec, *Bar*).

| Bar | Measured | Where |
|---|---|---|
| hook recall p50, 180 facts, ≤ 5 ms | Python 0.85 ms, Node 0.74 ms | J69-3 note, `d2a14d0` |
| hook recall p50, 5,000 facts, ≤ 15 ms | Python 13.22 ms, Node 12.45 ms (re-run in J69-8: see below) | J69-3 note, `d2a14d0` |
| full build, 5,000 facts, ≤ 1 s | Python 755.5 ms, Node 458.3 ms | J69-3 note, `d2a14d0` |
| Retention deletes zero unverified files | 0 on the trap fixture, both runtimes | `storage-retention`, J69-6 note, `f178c66` |

End to end (`UserPromptSubmit`, cold spawn, 5,000 facts in each of two stores), wall p50 before →
after: Node 162.0 → 58.8 ms, Python 1256.1 → 410.5 ms (J69-3 note, `d2a14d0`).

Re-run by J69-8 on 2026-10-16 (tree `f780012` plus J69-8's retention fixes, which do not touch
the recall path), this Mac, load average about 2, three runs of `bench_recall` each:

| | Python | Node | bar |
|---|---|---|---|
| hook recall p50, 180 facts | 0.83 / 0.84 / 0.84 ms | 0.73 / 0.70 / 0.69 ms | ≤ 5 ms |
| hook recall p50, 5,000 facts | 12.48 / 12.35 / 12.61 ms | 11.80 / 11.47 / 11.51 ms | ≤ 15 ms |
| same, reading the files (the old path) | 227 / 235 / 230 ms | 102 / 103 / 102 ms | — |
| full build, 5,000 facts (`bench_hotindex`, median of 5) | 723.0 ms | 430.9 ms | ≤ 1,000 ms |

The 5,000-fact margin is about 2.4 ms (Python) and 3.2 ms (Node): thin, but every run held it.
Most of the cost is parsing the HEAD's `docs` (1.84 MB at 5,000 facts), which recall needs only
for its `k` hits; that is the next lever if a slower machine misses the bar.

```sh
TMPDIR=$(mktemp -d) .venv/bin/python tools/eval/storage/bench_recall.py
TMPDIR=$(mktemp -d) node tools/eval/storage/bench_recall.mjs
TMPDIR=$(mktemp -d) .venv/bin/python tools/eval/storage/bench_hotindex.py --runs 5
TMPDIR=$(mktemp -d) node tools/eval/storage/bench_hotindex.mjs --runs 5
```

## Windows

Not measured: there is no Windows machine in this project's loop, and GitHub Actions stays off.
What was checked statically (J69-8) is listed here so the manual run knows what to look at:

- **The lock** is `open(O_CREAT | O_EXCL)` on `<path>.lock` (`os.open` / `fs.openSync(..., 'wx')`),
  which Windows supports, with a stale-lock break after 10 s and a 2 s wait after which the body
  runs unlocked (an append) or is skipped (a rewrite). A delete-pending lock file answers access
  denied on Windows; it is still there, so the fail-fast rule above keeps waiting for it.
- **A rewrite** (#208) takes a hard link (`os.link` / `fs.linkSync`, NTFS supports it) and then
  renames over the live file; a Python appender holding the file open makes that rename fail on
  Windows, so the rewrite is skipped and retried, and nothing is lost.
- **Renames** are `os.replace` / `fs.renameSync` onto an existing file. Windows refuses that while
  another process holds the target open without `FILE_SHARE_DELETE`, so a reader holding a HEAD
  open at the instant of a write would make that write fail. A failed write-through is already
  handled (the in-memory copy is dropped and the next reader patches), and a failed archive
  write is refused with nothing deleted.
- **Gzip** is the stdlib on both sides (`gzip` / `node:zlib`), compared after decompression.
- **Directory fsync** is skipped on Windows (it cannot open a directory); the file is fsynced.
- **The detached child** uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` (Python) and
  `detached: true, stdio: 'ignore'` (Node).

**The manual step** (the plan's Task 8): on Windows, run `.venv\Scripts\python -m pytest
runtime-py/tests/test_storage_retention.py runtime-py/tests/test_storage_log.py -q`, `cd
runtime-ts && npm test`, and `node tools/conformance/run.mjs --suite storage-retention --suite
storage-log`, then 20 parallel appenders on one `LogSegment` (each appending 500 lines) and check
that the file holds 10,000 parseable lines.

## The SQLite trigger (S5)

`HotIndex` and `ColdIndex` are interfaces with a JSON backend. They switch to SQLite + FTS5 only
when both hold: `engines.node >= 24` in `runtime-ts/package.json`, and `node:sqlite` documented as
stable in Node's own docs. Consumers (#199's ranker, #200's touch graph) do not change when it
switches.
