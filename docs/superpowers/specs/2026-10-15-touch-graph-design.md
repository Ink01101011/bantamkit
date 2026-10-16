# What the agent touched, linked to what it remembers

**Issue #200**, milestone 0.37.0-beta. It depends on **#204**, the storage layer: the touch log uses #204's log
segment and the graph is one of #204's derived indexes. It extends **#199**: #199's Ranker reserves a `w_context`
slot, and this design fills it.

This design was agreed with the user on 2026-10-15. Every decision below is the user's.

## What is wrong today

- The filegraph hook (`hookadapter` `_pre_tool_use_read`) keeps a per-transcript READ ledger, one file per session.
  Its only use is refusing one repeat Read.
- It records no Edit or Write. It links nothing to anything. Nothing in it outlives the session, and recall never
  reads it.
- So when an agent edits `store.ts`, nothing tells it about the facts the project learned about `store.ts`. A new
  session, or one that has just been compacted, starts with no record of what was being changed.

## Decisions

| # | Question | Decision |
|---|---|---|
| E1 | Who consumes the graph? | **A**: #199's Ranker (`w_context`). **B**: a short touch summary at SessionStart and after compact. **C**: an optional `file` argument on `memory_recall`, so no 15th tool is added. Every tool definition costs context in every session, and agents rarely call a new tool. |
| E2 | How does a fact relate to a file? | **Strong edge**: the fact names the file by path. **Weak edge**: the fact was saved or recalled within ±20 tool calls of a touch on the file, in the same session, decayed with the 14-day half-life the usage ledger uses. |
| E3 | May a file edge admit a fact past #199's gate? | **Only under conditions.** A strong edge to a file touched within the last 20 tool calls may admit **at most 1** fact per prompt. The injected line is labelled `[via <file>]`. A weak edge never admits. |
| E4 | How are references written and shown? | The agent writes paths as it already does. Indexing resolves them: renames are followed through git, and a `#symbol` is kept while a `:line` collapses to the file. Paths are displayed and accepted as the **shortest unique suffix** (`store.ts`, or `memory/store.ts` when that is ambiguous). There is no opaque code: an encoded path is no shorter in tokens, and a lookup table costs the tokens back. |
| E5 | Writes made by Bash | These are captured **once per turn**: `git status` at UserPromptSubmit is compared with `git status` at Stop. Files changed by Bash are recorded as `op: write, via: bash-turn`. Reads made through Bash are not captured. |

## Architecture

```
PostToolUse ──► touch log (#204 log segment) ──┐
UserPromptSubmit/Stop git status ─ bash-turn ──┤
facts + git ──► ref extractor ─────────────────┴─► graph (#204 derived index)
                                                     ├─► (A) Ranker w_context + conditional admission
                                                     ├─► (B) SessionStart / post-compact summary
                                                     └─► (C) memory_recall({file})
```

1. **Touch log.** It lives at `~/.bantamkit/touch/<repo-id>.jsonl` and is a #204 log segment.
   - One line per touch: `{ts, session, seq, op: read|edit|write, path, via?}`.
   - `path` is repo-relative.
   - `repo-id` is a hash of the realpath of the git toplevel. Outside a git repository nothing is recorded.
   - The ops recorded are Read, Edit, MultiEdit, Write and NotebookEdit from PostToolUse. bash-turn writes come in
     from Stop.
   - Paths only. The touch log never stores file content.
2. **Ref extractor.** It reads each fact's description, keywords and body for path-like references: `path`,
   `path:line` or `path#symbol`. Each reference is resolved against `git ls-files` and followed through git
   renames. A URL is never treated as a path. Each resolved reference produces a strong edge.
3. **Weak edges.** These come from co-occurrence between the touch log and the usage-ledger events, for the same
   session within ±20 tool calls. bash-turn writes are counted at turn granularity. The usage ledger gains an
   optional `session` field for this.
4. **Graph.** A #204 derived index at `~/.bantamkit/graph/<repo-id>.json`. Its fingerprint is git HEAD, plus the
   touch-log size, plus the store fingerprints. It is rebuilt lazily when used, and always rebuildable.
5. **Consumers.**
   - **(A) Ranker.** It adds `w_context`: full weight for a strong edge, partial weight for a weak edge, using
     files touched in this session's last 20 calls. The admission path is E3.
   - **(B) Summary.**
     - **At SessionStart:** the previous session in this repo, at most **600 bytes**, kept separate from the
       3000-byte profile block. For example:
       `[bantamkit touch] last session here (2026-10-15, 3 h ago): edited 12 files — store.ts, retrieval.ts, factfile.ts (+9); commits: J68-3 keywords (#199); uncommitted: 4 files`.
     - **After compact:** the files this session edited. PreCompact already lists the files read, so this adds
       only the edits.
     - The summary is silent when there is nothing to say. Reads are never listed.
   - **(C) `memory_recall({file})`.**
     - It returns the facts linked to that file, plus one touch-history line for the file: when it was last
       touched, and the commit or issue from `git log`.
     - It accepts a suffix.
     - An unknown file gets one sentence, the same on both runtimes.
6. **Issue and unit links** are not captured. They are read from `git log` at query time, because commit subjects
   already carry `(#199)` and `J68-3`.

## Data flow

- **PostToolUse** (Read/Edit/Write family): append one touch line. Reads nothing.
- **UserPromptSubmit:**
  - snapshot `git status` for the bash-turn diff;
  - read the tail of the touch log to get this session's last 20 touches;
  - hand those touches to the Ranker and to the admission path.
- **Stop:** run `git status` again and diff it with the snapshot. Changed files that no Edit or Write in this turn
  explains are appended as `via: bash-turn`.
- **SessionStart / post-compact:** build the B summary from the touch log and `git log`.
- **The graph** is rebuilt only when its fingerprint changed.

## Error handling

The graph is an enhancement. No failure here may fail a hook or a recall.

| Case | Behaviour |
|---|---|
| Touch log unwritable | Skip it and count the miss in `bantamkit_status`. |
| Corrupt line | Skip it and count it. |
| No git, or not inside a repo | Nothing is recorded. There is no rename following, no bash-turn and no B summary, and `w_context` is 0. Everything else works. |
| Log over its cap | Fold through #204's log segment, under the O_EXCL lock. |
| Graph build fails | `w_context` is 0, and recall behaves as without #200. |

## Testing

Conformance (Python against Node), per CLAUDE.md. Every case is proven red by a one-sided mutation, and each
suite has at least one symmetric mutation caught only by a per-side literal.

- **Touch-log lines:** each op's line shape, and that a Bash call is never recorded as a touch.
- **Ref extractor** over a corpus of fact texts: `path`, `path:line`, `path#symbol`, a missing path, and a URL.
- **Renames:** in a fixture git repo with `git mv`, the old path still resolves.
- **Shortest unique suffix:** nested duplicate names, and the round trip from suffix back to the full path.
- **bash-turn:** the snapshot diff, and that an Edit is not double-counted.
- **Admission path:** strong edges only, the 20-call window, at most 1 fact, and the `[via …]` label. Each rule
  has a case that goes red when the rule is removed.
- **B summary:** the 600-byte cap measured in bytes, silence, and post-compact listing edits only.
- **`memory_recall({file})`:** a suffix is accepted, and the unknown-file sentence is byte-identical across
  runtimes.

## Evaluation and the bar

The eval extends #199's harness (`tools/eval/recall/`):

- **Silver:** a fact the agent used after touching a file it names, within the previous 20 calls.
- **Gold:** a separate, second labelling pass over `[via …]` candidates, built once #200 runs. The user ruled
  this on 2026-10-16 ("two passes"): #199's 50-prompt gold set is labelled now so #199 can close, and #200's
  candidates cannot exist before #200 is built. The page is `tools/eval/recall/gold-label.html`, reused.
  Pass 2 uses #199's method (user ruling 2026-10-16, "same as #199"): a blind model judge labels every candidate,
  the user labels a seeded 10-prompt subset, and `tools/eval/recall/gold_merge.py` accepts the judge only when raw
  agreement ≥ 0.9 and Cohen's kappa ≥ 0.6 over the subset; otherwise the user labels the rest.
- **Bar, declared before any number exists:**
  - precision of the via admission path ≥ **0.8** on gold. Otherwise the path ships **off by default**, and
    `w_context` ranking stays on;
  - overall precision@inject no lower than #199 v2;
  - PostToolUse hook p50 rises by at most **2 ms**;
  - the Stop `git status` p50 is at most **30 ms** on this repo.
- **Reported, not gated:** whether sessions that received a B summary re-read fewer files.

## Order

#204 (storage layer) → #199 J68-5 onward → #200, which needs J68-5's Ranker.

## Out of scope

- Reads made through Bash (`cat`, `grep`). Parsing shell commands guesses wrong.
- Line-number binding, because lines drift.
- Indexing across repositories. Each repo has its own graph.
- Embeddings. If they are ever needed, that is #199's fallback lever.
