# One storage layer for everything the agent keeps

**Issue #204**, milestone 0.37.0-beta. It must land before #199's J68-5 (gate and ranker) and before #200 (the touch
graph). Both of those consume it.

Status: **APPROVED in direction by the user 2026-10-15** ("สนใจ" on: build it ourselves on the hot/cold plan, borrow the
`docs` / `links` / `tags` index shape and index `[[wiki links]]` as strong edges for #200). Detail below stands as
written unless the user amends it.

## What is wrong today (measured 2026-10-15)

- **The stores are files with no index and no retention:**

  | store | size | problem |
  |---|---|---|
  | facts (profile 45 + project 134 files) | ~940 KB | |
  | `~/.bantamkit/hooks/ledger-*.json` | 213 files, 4.4 MB | never pruned |
  | `hook-log.jsonl` | 2.3 MB, 9,064 lines | no rotation found |
  | `.shiftwork/` | 11 MB, 1,472 files | |
  | Claude Code auto-memory | 478 files | #199 J68-11 will read it |

- **Recall parses every fact file on every call, and the hook calls it on every prompt.** Node `MemoryStore.recall`,
  real fact files, mean of 5 runs:

  | facts | recall time |
  |---|---|
  | 180 | 5 ms |
  | 1,000 | 21 ms |
  | 5,000 | 111 ms |

- **A JSON index is cheap to load at the sizes that matter.** Parse time for a synthetic index with postings:

  | docs | file size | Node | Python |
  |---|---|---|---|
  | 500 | 0.27 MB | 1.2 ms | 1.5 ms |
  | 5,000 | 2.2 MB | 7.5 ms | 11 ms |
  | 50,000 | 22 MB | 73 ms | 130 ms |

- **The number of live facts is already bounded by design.** The 24,000-byte index budget caps each store at roughly a
  hundred-odd facts; the project store's index is 75 lines and 16.6 KB today. What grows without bound is the archive,
  the logs, auto-memory and `.shiftwork`.

## Prior art (checked 2026-10-15)

- **Basic Memory** keeps Markdown as the source of truth and SQLite as a derived, rebuildable index, linked by
  `[[wiki links]]` and served over MCP. It confirms the direction we chose. It is Python-only and GPL-3, so we borrow
  ideas, never code.
- **MarkdownDB (`mddb`)** indexes Markdown into SQLite as files, tags and links. It is JS-only.
- **Mem0, Zep/Graphiti and Letta** solve a different problem: vector or graph servers, often with LLM extraction. That
  breaks our requirements of offline use, zero dependencies, Windows support and low-end hardware.
- **`node:sqlite`** is reported stable from Node 24 by a third-party source, not yet confirmed against Node's own docs.
  We support `engines.node >=20`.

## Decisions

| # | Decision |
|---|---|
| S1 | **Files stay the source of truth.** Fact Markdown and checkpoint JSON remain hand-editable and git-diffable. Every index can be deleted and rebuilt with nothing lost. |
| S2 | **Capability tiers.** (1) **Core**, for any MCP client: indexes, logs, retention and every tool. It never needs a hook or a host directory. (2) **Hook**: automatic injection, the touch log and the touch summary. (3) **Host data**: the auto-memory index. Tiers 2 and 3 may be absent, silently, but never as an error, and never by slowing or breaking tier 1. `bantamkit_status` names the active tiers. |
| S3 | **Hot and cold.** The hot index is a small JSON **head** file (df, avgdl, per-doc metadata, fingerprint) plus postings **sharded 16 ways by term hash**; a recall loads the head and only the shards its query terms hash to. *Amended 2026-10-15 by the user ("เลือก A"), replacing "a single JSON file": J69-2 measured a single file at 5,000 facts as 5.5 MB, 43 ms (Python) / 27 ms (Node) just to load, above the 15 ms bar; the bar stays, the layout changed.* The cold index is immutable JSON segments plus a manifest, with postings sharded 16 ways by term hash. It is read only when someone searches, never on the hook path. |
| S4 | **Retention.** Per-session ledgers are deleted after 7 days. Log lines are folded after 30 days and old segments gzipped. Closed `.shiftwork` jobs are archived 7 days after closing. Facts are NEVER archived by age; they stay budget- and usage-based, with "stalest" read from #199's usage ledger. |
| S5 | **Backend interface.** `HotIndex` and `ColdIndex` are interfaces with a JSON backend now. The switch to an SQLite+FTS5 backend is recorded as a trigger: `engines.node >= 24` **and** `node:sqlite` confirmed stable in Node's own docs. Consumers (#199, #200) do not change when it switches. |
| S6 | **Borrowed schema.** The index keeps `docs`, `links` (frontmatter `links` plus `[[wiki links]]`), `tags` and `refs` (path references, for #200). |

## Components (both runtimes, one `storage` module each)

1. **`HotIndex`**
   - **Location:** `~/.bantamkit/index/<sha16(realpath(source))>.json`. Never inside a store, because the project store
     is committed and the index must not be.
   - **Contents:** head `{version, fingerprint, docs, df, avgdl, shards}` plus `postings-<00..15>.json`, tokens from
     #199's `tokenize_v2`, shard = a stable hash of the term mod 16, identical on both runtimes. A shard whose
     fingerprint does not match the head is treated as a missing index (rebuild).
   - **Python YAML speed:** fact frontmatter is parsed with libyaml's `CSafeLoader` when present; on any parse error
     the same text is re-parsed with the pure `SafeLoader`, so error text never changes. J69-2 measured 0.9 s of a
     1.50 s full build in pure-Python YAML against the 1 s bar.
   - **Sources:** every fact layer, plus auto-memory as read-only tier 3. Nothing is ever written into Claude Code's
     directory.
   - **API:** `docs()`, `query(terms)`, `refresh("fast" | "full")`.
     - **fast:** one `stat` of the source directory. Every writer we ship uses temp-plus-rename, which moves the
       directory mtime.
     - **full:** a `stat` of every file. It runs at SessionStart or every 10 minutes, and catches editors that write
       in place.
   - **Writes:** temp file plus rename.
   - **Failure:** a version mismatch, a missing index or an unreadable index all trigger a rebuild.
2. **`LogSegment`**
   - **API:** `append(obj)`, `read(since)`, `fold(older_than, reducer)`, `rotate()`.
   - **Rotation:** old segments are gzipped with stdlib on both sides.
   - **Lock:** the existing O_EXCL lock.
   - **Moves onto it:**
     - #199's usage ledger: J68-4's `fold` becomes its reducer, and the line format is unchanged.
     - #200's touch log.
     - `hook-log.jsonl`: the existing file becomes segment 0.
     - The event log.
   - **Not moved:** `<checkpoint>.log.jsonl`. `clock_out` reads its brief lines to decide whether a unit was briefed,
     and folding them would change that answer.
3. **`ColdIndex`**
   - **Format:** immutable segments plus `manifest.json` plus 16 term-hash shards.
   - **Sources:** fact `archive/`, archived `.shiftwork` jobs, and folded log aggregates.
   - **Reached through:**
     - an optional `include_archived` argument on `memory_recall`;
     - a cross-job shiftwork search, the same tool family, no new tool.
4. **`Retention`**
   - **Trigger:**
     - once a day, gated by a TTL in `~/.bantamkit/retention.json`;
     - started by SessionStart when hooks exist, or by MCP server start when they do not;
     - runs as a detached, silent child, like update-probe.
   - **A closed job:** every unit is done or dropped.
   - **Its archive:** `.shiftwork/archive/<job>.json.gz`, one JSON bundle of the job's files, gzipped, then indexed
     into `ColdIndex`. JSON plus gzip rather than tar, because Node ships no tar.
   - **Opt-out:** `BANTAMKIT_RETENTION=off`, honoured identically on both runtimes.

## Data flow

- **Hook (UserPromptSubmit):** a fast refresh (one stat per source), then one JSON read, then #199's scorer on the
  postings. No fact file is parsed on this path unless the index must be rebuilt.
- **Writes** (`save`, `compact`, `restore`, `dream`): the store writes the fact atomically, then updates the hot index
  in the same process. If the index update fails, the index is marked stale and the next reader rebuilds it.
- **Concurrent writers:** the last write wins. A reader whose fingerprint check fails rebuilds, so the index is never
  trusted over the files.
- **Retention:**
  1. Write the archive.
  2. Re-read it and verify its hash.
  3. Only then delete the originals.
  4. On any failure, delete nothing and log it.

## Migration

- **Usage ledger and event log:** same line format, so no rewrite is needed.
- **`hook-log.jsonl`:** becomes segment 0, and rotation starts from it.
- **Per-session ledgers:** the format is unchanged; retention starts pruning entries older than 7 days.
- **Existing `archive/` facts:** indexed into `ColdIndex` on the first retention run.
- **Index `version` bump:** triggers a rebuild, never a parse of an old shape.

## Error handling

| Case | Behaviour |
|---|---|
| Index directory unwritable | Score from an in-memory index built per call (today's speed, the slow path). `bantamkit_status` reports it. |
| Index corrupt or wrong version | Rebuild. |
| Log segment unwritable | Drop the event and count it. Never fail the caller. |
| Retention child fails or times out | Nothing is deleted. The failure is logged and retried at the next day's TTL. |
| Open `.shiftwork` job | Never archived, at any age. |
| A delete would follow an unverified archive | Refused. Verify first, always. |

## Testing

Conformance (Python against Node). Every case is proven red by a one-sided mutation, and each suite has at least one
symmetric mutation caught only by a per-side literal.

- **Hot index:**
  - the index bytes are deterministic: keys sorted, numbers formatted per #199's `pyRound9`;
  - `query` results;
  - an in-place edit is missed by fast refresh and caught by full refresh, and both behaviours are pinned;
  - rebuild after corruption and after a version bump.
- **`LogSegment`:**
  - append, fold and rotate;
  - gzip output is compared **after decompression**. The compressed bytes differ between zlib builds, and a `ruling:`
    case pins that difference.
- **Retention:**
  - the 7-day boundaries;
  - verify-before-delete;
  - an open job is never touched;
  - the once-a-day TTL;
  - opt-out.
- **MCP-only host profile:** no hook, no auto-memory. Tier 1 runs complete on both runtimes.

## Bar (declared before any number exists)

- Hook recall p50 with 180 facts is **no slower than today's 5 ms**.
- With 5,000 facts it is **≤ 15 ms**, against 111 ms today.
- A full hot-index build over 5,000 facts takes **≤ 1 s**.
- Retention deletes **zero** files that are not verified in an archive or past their TTL, on a fixture tree with
  planted traps.

## Order

job69 = #204, then rebase job68, then J68-5 scores through `HotIndex`, then #199 continues, then #200.

## Out of scope

- A real-time file watcher. mtime and TTL are enough.
- Embedding search.
- Syncing across machines.
- An SQLite backend before the S5 trigger.
