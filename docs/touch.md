# The touch graph (#200)

What the agent touched, linked to what it remembers. Spec:
`docs/superpowers/specs/2026-10-15-touch-graph-design.md`; plan:
`docs/superpowers/plans/2026-10-16-touch-graph.md`. Both runtimes implement every part below
(`runtime-py/src/bantamkit/touch/`, `runtime-ts/src/touch/`), and six conformance suites compare
them (`touch-log`, `touch-refs`, `touch-turn`, `touch-graph`, `touch-context`, `touch-summary`,
plus the `memory-recall-file` session in `wire` and the v5 rows in `storage-index`).

Every number on this page was measured on the branch `feat/199-recall-by-meaning`; the commit is
named next to it. **Every gold number is UNVALIDATED**: gold pass 2 was labelled by a model judge
(user ruling: the agent labels gold itself), and no user label checked it.

## In one paragraph

PostToolUse appends one line per Read, Edit, MultiEdit, Write and NotebookEdit to a per-repo
touch log, and a Bash turn's writes are found by diffing two `git status` snapshots. Facts are
linked to files two ways: a **strong** edge when the fact's text names the file, a **weak**
edge when the fact was recalled or saved within 20 tool calls of a touch in the same session.
The graph feeds three consumers: (A) the ranker's `w_context` slot and an optional
`[via <file>]` admission, (B) one short line at SessionStart, and (C) `memory_recall({file})`.
**What ships on by default is B and C.** A's ranking weight is `W_CONTEXT = 0.0` (silver could not
tune it) and the via admission is off (gold pass 2 measured its precision at 0.150 against a bar
of 0.8), so with the defaults the ranker orders exactly as #199 does.

## The touch log

`~/.bantamkit/touch/<repo-id>.jsonl`, a #204 `LogSegment` (append under the O_EXCL lock).
`<repo-id>` is the first 16 hex characters of SHA-256 over the realpath of the git toplevel,
with a leading drive letter upper-cased first (`repo_id` / `repoId`, #208): `c:\x` and `C:\x`
are one repository on both runtimes, whichever case each one's realpath returns on Windows. A
POSIX toplevel has no drive letter, so its id is unchanged.
The toplevel is found by walking up from the event's `cwd` for `.git`, a directory or a
`gitdir:` file (a linked worktree or a submodule). Finding it costs stats, never a subprocess.
Outside a git repository nothing is written, not even the counter.

Line shapes, keys in this order (the bytes are `LogSegment`'s):

| line | shape | written by |
|---|---|---|
| touch | `{"ts","session","seq","op","path"}`, `op` one of `read`, `edit`, `write` | PostToolUse |
| bash-turn write | the touch shape plus `"via":"bash-turn","from":<seq>` | Stop |
| use | `{"ts","session","seq","op":"use","fact","kind"}`, `kind` one of `recall_hit`, `save` | PostToolUse of `mcp__bantamkit__memory_recall` / `memory_save` |
| folded | `{"ts","session":"","seq":0,"op":"folded","path","n"}` | a fold: Retention, or an append over the cap (*Errors*). `n` is clamped to +/- `TOUCH_N_CAP` = 2^53 - 1 per row and after each sum (#208): two `n: 1.7e308` rows summed to `Infinity` in Node, its line could not be written and the bound never held, while Python wrote a 309-digit integer Node reads back as a double |

- `path` is repo-relative with `/` separators on every OS. A file outside the toplevel makes no
  line. `NotebookEdit` reads `notebook_path`; the others read `file_path`. MultiEdit and
  NotebookEdit are `edit`.
- **Paths only.** No line ever holds file content.
- **A Bash call is never a touch line**, and a read made through Bash (`cat`, `grep`) is never
  captured. Parsing shell commands guesses wrong (spec, Out of scope).
- `ts` is the ledger stamp `YYYY-MM-DDTHH:MM:SSZ`.

### `seq`, the per-session counter

`seq` is the session's tool-call ordinal: EVERY tool call of the session inside a repo counts,
Bash included, so "within 20 tool calls" means 20 calls and not 20 touches. It lives in
`~/.bantamkit/hooks/ledger-<session>.seq.json` (`{"seq":N}`), read, incremented and written
(temp then rename) under the O_EXCL lock. PostCompact unlinks only `ledger-<session>.json`, so
the counter survives a compaction; Retention's 7-day ledger rule prunes it.

### `use` lines, and why the server does not write them

The spec puts the session on the usage ledger. The MCP server cannot know it: no tool argument
and no server state carries a session id or a tool-call ordinal. The PostToolUse hook sees both,
so it writes the `use` lines into the touch log and the usage ledger is unchanged (spec
deviation, plan Q1, settled 2026-10-16).

`use_names` reads a `memory_recall` reply one `\n`-separated line at a time with an anchored
`USE_HEADER` (`^(?:\[[^\]\n]+\] )*\[([^\]\n]+)\] \([a-z]+\) `), never a multiline regex, because
JavaScript's `m` flag also starts a line after `\r`, U+2028 and U+2029. **A body line spelled like
a header is also matched:** the reply's own headers and such a line cannot be told apart. Both
runtimes do this; it is shared behaviour, not a divergence.

## bash-turn

UserPromptSubmit saves a `git status --porcelain=v1 -z -uall` snapshot, `path -> [xy, mtime_ns,
size]`, at the current `seq` in `~/.bantamkit/hooks/ledger-<session>.turn.json`. It runs before
the short-prompt and slash-command skip, because a command's turn can still run Bash. Stop takes a
second snapshot and records every path whose triple moved as a `write` line with
`via: "bash-turn"` and `from` = the turn's seq, unless an `edit` or `write` line of this session
after `from` already names it (an Edit is never counted twice). A path already dirty before the
turn is caught by its stat moving. A rename keys on its destination. Stop then re-saves the
snapshot, so a second Stop in one turn (the save nudge's continuation) records nothing twice.

A use co-occurs with a bash-turn write when its seq lies in `(from, seq]`, which is what "turn
granularity" means here.

Every `git` call: an argv list and no shell; `GIT_OPTIONAL_LOCKS=0` (so `git status` never takes
`index.lock` beside the user's own git), `LC_ALL=C`, `GIT_TERMINAL_PROMPT=0`,
`-c core.quotepath=off`, `-z` where git offers it, a 2,000 ms timeout, and "no answer" on any
failure.

## References: strong edges

The hot index (#204) fills its reserved `refs` slot, so the graph never parses a fact file. The
index version is **5**; a version-4 head is rebuilt on its next read. A fact's refs are
extracted from its description, each keyword, then its body (a `[native]` doc: description and
body).

- A reference is a path-like token that holds a `/` or ends in `.<letter><up to 7 alnum>`:
  `memory/store.ts`, `store.ts`, `store.ts:120` (the `:line` collapses to the file),
  `store.ts#pooledRanking` (the `#symbol` is kept). A bare name with no `/` and no extension
  (`Makefile`, `README`) is never a reference.
- Every URL span is blanked first, so a URL is never a path.
- The regex is ASCII-only with explicit classes (no `\w`, `\s`, `\b`), because Python's `\w`
  takes Thai letters and JavaScript's does not.
- **Resolution** (`resolve_ref`) against `git ls-files`: an exact tracked path; else the
  longest tracked file the reference ends with as `.../f`; else the tracked files ending with
  `/<ref>`. **One match is an edge; several are ambiguous and make no edge**; none is followed
  through git's renames (`git log --name-status -M --diff-filter=R HEAD`, the newest rename of a
  path winning, up to 32 hops). An absolute path inside the toplevel is made relative.

### Shortest unique suffix

Paths are shown and accepted as the fewest trailing components that still resolve to exactly
that file: `store.ts`, or `memory/store.ts` when another `store.ts` is tracked. There is no
opaque code: an encoded path is no shorter in tokens, and a lookup table costs them back
(spec E4).

## The graph

`~/.bantamkit/graph/<repo-id>.json`, a #204 derived index: delete it and the next load rebuilds
it. Two halves, each with its own print (spec deviation: one print over all three inputs would
rebuild the git half, two subprocesses, after every tool call):

| half | shape | rebuilt when |
|---|---|---|
| `strong` | `path -> [[fact, symbol or null], ...]` | `strong_print` moves: `sha16` of the graph version, git HEAD + the ref it names + the git index's `mtime_ns:size` (read from files, no subprocess), and each layer's hot-index head print. A commit, a `git add` or a fact write moves it; a tool call does not. |
| `weak` | `path -> fact -> [ts, ...]` (newest 32 distinct stamps) | `weak_print` moves: the touch log's live size and segment count. |

The file also carries `files` (the `ls-files` list it was built against). Writes are temp then
rename under the O_EXCL lock; the bytes are `hotindex.dumps`, so either runtime reads the
other's file. A read-only layer that cannot be read contributes no edges; the project layer
failing fails the strong half. **Any failure is "no graph"**, and no graph is today's recall.

## (A) `w_context` and the via admission

At UserPromptSubmit the hook reads this session's rows from the last 64 KiB of the touch log and
takes the `window`: the paths read, edited or written in the session's last `TOUCH_WINDOW = 20`
tool calls, most recent first. With a graph, `context_weights` gives every linked fact a `ctx`:

- **1.0** for a strong edge to a window path;
- otherwise `min(1, CONTEXT_WEAK_SHARE × Σ 0.5^(age_days / 14))` over its weak co-use stamps
  (`CONTEXT_WEAK_SHARE = 0.5`, the usage ledger's 14-day half-life).

`ctx` enters #199's ranker as `+ W_CONTEXT × ctx` inside the weight, clamped to `[0, 1]`.
**`W_CONTEXT = 0.0` ships** (see *The bar*), so the weight changes nothing today. While
`W_CONTEXT == 0` and the via path is off (`VIA_ON` false and `BANTAMKIT_VIA` not `on`), the hook
builds no context at all: no touch-log read, no graph load or rebuild (T200-10). The reply is
the same bytes either way (`touch-bound` compares the default reply with the via-on reply minus
its via line); only the UserPromptSubmit record's `context: <n>` count is absent. When either
is on, the context is built and `context: <n>` counts the facts that carried a weight. Measured
on the Node hook, 20,000 touch lines, 15 cold runs, a Read before each prompt
(`.shiftwork/notes-job70/T200-9-scale.mjs`): UserPromptSubmit p50 101.5 / 103.2 ms before,
57.7 / 57.8 ms after.

**The via admission (E3).** When on, ONE fact the gate did not pick is appended after the k
gated hits: the first window path (most recent first) that holds a strong-edge fact not already
shown, its heaviest such fact by `weight_of(type, stale, 0, 1)`, ties by name. Weak edges never
admit. The header ends with the suffix ` [via <shortest unique suffix>]`:

```
[project] [store-pool-weights] (project) why Pool.weights is per type [via store.ts]
```

A suffix and not a prefix, because the hook's `RECALL_HEADER` would stop matching a prefixed
line and drop it. So a prompt can get k+1 lines; the hook's 700-byte cap drops whole lines from
the end, the via line first (plan Q2). A via fact is never stamped, repaired or counted as use.
The record of a prompt that injected one carries `via: <name>`.

**Off by default.** `VIA_ON = False` in both `touch/context.*`. `BANTAMKIT_VIA=on` turns it on,
`BANTAMKIT_VIA=off` forces it off; any other value keeps the default. Read on every call.

## (B) The summaries

SessionStart appends one line of at most **600 bytes of UTF-8** (cut on a character boundary),
its own part of the injection, outside the 3,000-byte memory blocks. Silence is no line. Reads
are never listed. The log record carries `touchBytes`.

- **`startup` / `resume` / `clear`**: the previous session in this repo (the session other than
  this one whose latest touch is newest; a tie goes to the smaller id). Its edited files (edit and
  write lines, bash-turn included, most recent first, three named), the commits whose committer
  date lies in `[first touch, last touch + 1800 s]` (`git log --format=%s`, three named, each
  subject cut at 60 bytes), and how many files `git status` shows uncommitted now:

  ```
  [bantamkit touch] last session here (2026-10-15, 3 h ago): edited 12 files — store.ts, retrieval.ts, factfile.ts (+9); commits: J68-3 keywords (#199); uncommitted: 4 files
  ```

  Ages read `just now`, `N min ago`, `N h ago` (under 48 h), `N d ago`.
- **`compact`**: this session's edits before the compaction, up to ten named (plan Q4: the fresh
  context is where it is read; PreCompact already lists the reads):

  ```
  [bantamkit touch] edited in this session before compaction: store.ts, retrieval.ts (+3)
  ```

Git runs only when the touch log has something to say.

## (C) `memory_recall({file})`

`memory_recall` takes an optional `file` (`assets/tools/memory_recall.json`; `required` is now
`[]`), so no tool is added. The repo is the SERVER's working directory's. `file` is stripped and
`\` is read as `/`, then resolved by the same suffix rule. The reply's first line is the history
line:

```
[file] store.ts — last touched 2026-10-16 (edit); last commit 3021312 feat(memory): ...
```

(`last touched never` when the log has no row for it; the commit part only when `git log -1`
names one.) Then the linked facts formatted as a recall formats them: strong edges in graph
order, then weak ones by decayed weight, at most `max(k, 3)`. Nothing is stamped, repaired or
counted as use. With `file`, any `query` is ignored and the second line says so (plan Q5).

The six sentences, byte-identical on both runtimes:

| when | sentence |
|---|---|
| neither `query` nor `file` (a tool ERROR) | `memory_recall needs a query or a file.` |
| the server's cwd is not in a repo | `memory_recall file needs a git repository; the server's working directory is not inside one.` |
| no tracked file matches | `No tracked file in this repository matches "<file>".` |
| several match | `"<file>" matches <n> tracked files: <a>, <b>, ... (+k). Pass a longer suffix.` (five shown) |
| the file has no linked fact | `No memory is linked to <suffix>.` (after the history line) |
| `query` came with `file` | `(query ignored: file was given)` (the reply's second line) |

## Errors: the graph is an enhancement

No failure in `touch/` fails a hook or a recall. Every entry point catches and degrades to "no
context".

| case | behaviour |
|---|---|
| touch log unwritable | the line is skipped; the hook log gets `{"touch":"miss"}`, and `bantamkit_status` prints `touch: <n> missed writes (hook log)` (`touch: none` when there is no touch directory and no miss) |
| corrupt line | skipped, and counted on the log's `logs: touch/<repo-id> <bytes> (<n> rotated, <n> skipped)` status line |
| not inside a git repository | nothing is written; no bash-turn, no summary, no context |
| `git` not on PATH, or one that cannot run, inside a repository | nothing is written, not even the counter (T200-10, #208). A stat walk finds the candidate: each non-empty `PATH` entry in order; on POSIX `<dir>/git` must be a regular file with an execute bit (a symlink to one counts), on Windows `<dir>/git<ext>` for each extension of `PATHEXT` (`.COM;.EXE;.BAT;.CMD` when unset) that a no-shell spawn can run, `.exe` or `.com` only: a `git.cmd` / `git.bat` is never a candidate. No candidate is no git, with no subprocess. The first candidate then runs as `<candidate> --version` (no shell, 2 s bound) and must exit 0: the macOS `/usr/bin/git` shim with no Command Line Tools exits 1, so it is no git. The answer is kept in `~/.bantamkit/hooks/git-probe.json` as `{"key","ok"}` (`key` = sha256 of the candidate's path and `mtime_ns:size`, 16 hex) and believed while the file's mtime is within `GIT_PROBE_TTL_S` = 600 s of now, so the PostToolUse arm pays the spawn (about 10 ms measured on macOS) once per ten minutes, not per call; both runtimes write the same bytes and read each other's. Cached per process too, by PATH and PATHEXT. Everything else that needs git is silent too: no bash-turn, no summary, no graph, and `memory_recall({file})` answers the no-match sentence |
| log growth | Two folds into one `folded` line per path keeping its last `ts` and count, `use` lines dropped: Retention's through `LogSegment.fold`, and the bound on append. **On append** (T200-10, T200-11): an append that leaves the live log over `TOUCH_LOG_CAP_BYTES = 1,000,000` takes the O_EXCL lock and rewrites the file (temp then rename) as `bound_body` of it, and ONLY while that lock is actually held: when the 2 s wait runs out the fold is skipped (the append itself already went ahead, as every storage writer does), so no rewrite ever runs unlocked and a line appended under the lock is never lost to the rename; and no line an unlocked appender (one whose own 2 s lock wait ran out) writes is lost either: since #208 it writes under a marker, and the bound keeps the old file by a hard link, waits for the markers present after its rename and carries the old file's growth over verbatim, read to EOF (`docs/storage.md`, *Logs*). Before #208 a line landing after the read and before the rename could be lost; the forced probe of `.shiftwork/notes-job73/B1.md` (30 processes x 100 lines, half of them forced unlocked) kept 2,433-2,995 of 3,000 before and 3,000 of 3,000 in every run after, on both runtimes. `bound_body`: (1) every earlier `folded` row and every line with `ts <=` the `ts` of the first object line ending past the byte midpoint (`<=`, so a log written within one second still folds) go to the reducer; the other lines are kept as written. (2) When the kept lines alone are over `TOUCH_LOG_FOLD_TARGET_BYTES = 750,000` (no `ts` past the midpoint, or `ts` out of order) they are folded too. (3) **Aging rule:** while the result is over 750,000 bytes, folded rows are dropped **oldest `ts` first** (ties by path, code-point order). **What it drops:** a dropped row takes that path's touch count and last-touch time with it, so the strong/weak graph and the SessionStart summary forget a path that has not been touched for the longest; in case (2) the kept lines' `session`, `seq`, `via`/`from` and their `use` lines are folded away too. Every rewrite therefore ends at or under 750,000 bytes, whatever the mix of distinct paths, and the next one waits for at least 250,000 bytes of new lines: an append under the cap never rewrites. Before T200-11 a folded block over half the cap (about 4,400 paths of 40 characters) was re-folded into itself on every append, the file stayed over the cap and grew, and under parallel hooks lines were lost (`.shiftwork/notes-job70/T200-10-rereview.md`). Measured (`.shiftwork/notes-job70/T200-11.md`): an ordinary just-over-cap log, the folding append 8.96 ms (Node), a plain one 0.13 ms, 1,000,030 bytes to 495,083; the re-review's stuck log (6,000 folded rows), the folding append 19.48 ms Node / 27.79 ms Python, the plain append after it 0.16 / 0.13 ms, 1,000,032 bytes to 749,976. A fold that fails is silent and never fails the hook. This is the only bound while Retention is off. **Retention** (`docs/storage.md`) folds a log once a live line is older than 30 days (old `use` weight is below 0.23 of a fresh one), and rotates an idle log; with Retention off the 1 MB bound drops `use` rows and session detail sooner than 30 days would. |
| graph build fails | `w_context` is 0 and no via; recall is #199's |

## The eval and the bar

Declared in `tools/eval/recall/bar-touch.json` at 440e59c, before any number existed.

| criterion | bar | measured | verdict |
|---|---|---|---|
| via admission precision, gold pass 2 | ≥ 0.8 | **0.150** (20 prompts, 0d33d03, UNVALIDATED) | **MISSED: the via path ships off** |
| overall precision@inject | ≥ #199 v2 | identical to #199 by construction: `W_CONTEXT = 0.0` and via off leave the ranking unchanged (pooled gold view `ctx` = `ctx0` = 0.347, UNVALIDATED) | holds |
| PostToolUse p50 rise (Node hook) | ≤ 2 ms | at most +1.2 ms (T200-1); 0.0 / −0.2 ms (T200-5) | PASS |
| Stop `git status` p50, this repo | ≤ 30 ms | 20.2 / 19.7 ms (T200-3) | PASS |

Reported, not gated: UserPromptSubmit and Stop each cost +14–16 ms p50 (one `git status`,
T200-3); SessionStart +45 ms p50 when a previous session exists (T200-6). Whether sessions that
got a B summary re-read fewer files is **not measured yet**: no session had run with B when the
eval ran. The hook log's SessionStart `touchBytes` is the field to split them by.

**Silver could not tune `W_CONTEXT`** (07c8fa2). 238 prompts over 15 sessions of this repository,
93 with a non-empty window, **1 with a positive**. Every one of the 20 grid points
(`W_CONTEXT ∈ {0, 0.1, 0.2, 0.4, 0.8}` × `CONTEXT_WEAK_SHARE ∈ {0, 0.25, 0.5, 1.0}`) scored
precision@inject 0.0 and recall@3 0.0, so the declared rule (best recall@3 at no precision cost,
ties to the smaller weight) kept `W_CONTEXT = 0.0` and `CONTEXT_WEAK_SHARE = 0.5`. `W_CONTEXT`
multiplies the weight of facts that already scored and cannot admit one; the single positive
scored nothing under BM25.

**Gold pass 2** (0d33d03): 20 prompts where the forced-on via path admitted a fact, 76 pooled
candidates across views, labelled by a blind model judge (the `; via <file>` cue removed from its
prompts). Pooled scores (`score_pooled.py`):

| view | precision@inject | recall@3 | Thai recall@3 | injected |
|---|---|---|---|---|
| `ctx0` (no context) | 0.347 | 0.744 | 0.722 | 49 |
| `ctx` (shipped, `W_CONTEXT` 0.0) | 0.347 | 0.744 | 0.722 | 49 |
| `ctx_probe` (`W_CONTEXT` 0.8; scored, not tunable on gold) | 0.347 | 0.782 | 0.806 | 49 |
| `ctx_via` (ranked + via line) | 0.290 | 0.897 | 0.889 | 69 |
| via line alone | **0.150** | 0.179 | 0.194 | 20 |

The `ctx_probe` gain is gold-only evidence and did not set `W_CONTEXT`: gold is held out.
`W_CONTEXT` stays 0.0 until a silver set with enough touch positives exists. The private inputs
(prompts, fact text, session ids) stay gitignored under `.shiftwork/notes-job70/`; only numbers
are committed (`tuning-touch.json`, `via-pooled-result.jsonl`).

Rerun the gold scores (inputs are private, on the machine that ran the eval):

```sh
N=.shiftwork/notes-job70
.venv/bin/python -m tools.eval.recall.score_pooled --gold $N/via-gold-empty.jsonl \
  --candidates $N/via-gold-candidates.jsonl --pool-targets $N/via-judge-targets.jsonl \
  --pool-labels $N/gold-labels-via.jsonl --injections $N/via-injections.json
```

## Spec deviations (each settled before or during the build)

1. Weak-edge `use` events are written by the hook into the touch log; the usage ledger gains no
   `session` (above).
2. The graph has two prints, one per half (above).
3. bash-turn lines carry `from`, so turn granularity is computable.
4. The via label is a suffix; the via fact is a k+1th line, cut first by the 700-byte cap.
5. `VIA_ON = False` until a gold pass measures ≥ 0.8; `BANTAMKIT_VIA` is new operator surface
   the spec does not name.
6. "After compact" is SessionStart with `source == "compact"`.
7. `memory_recall`'s `required` is `[]`; `file` ignores `query` and says so.
8. An ambiguous bare reference makes no edge.
9. The B commit window is `[first touch, last touch + 1800 s]`.
10. Touch-log retention folds at 30 days.
11. Gold pass 2 had no user labels: the user ruled the agent labels gold itself, so the
    spec's seeded 10-prompt user subset and `gold_merge.py` check did not run, and every gold
    number is UNVALIDATED.
12. The eval replays subagent tool calls into `seq` (the hook counts them under the parent's
    session), while prompts and silver hits stay main-thread only.

## What was not done

- **Windows: unmeasured.** There is no Windows machine and GitHub Actions stays off. The checks
  the plan lists, none of them run: `relpath` across a `C:\` vs `D:\` cwd answers none; a
  `.git`-file worktree; `git` absent from PATH; 20 parallel PostToolUse processes giving `seq`
  1..20 with no gap. The last three were run on macOS at 0d33d03 on both runtimes
  (`.shiftwork/notes-job70/T200-9.md`); the `PATHEXT` rule runs only simulated (`windows: true`
  over POSIX directories, `touch-bound`). Since #208 the repo id no longer depends on whether
  Python's and Node's realpath agree on a Windows drive letter's case: the drive letter is
  upper-cased before hashing on both sides, held by construction and pinned by `touch-bound`
  feeding both sides `c:\...` and `C:\...`. STILL UNMEASURED on real Windows: whether the two
  realpaths agree on anything else (a `\\?\` prefix, a short 8.3 name, a junction, the case of a
  directory below the drive), any of which would still split the id; that a no-shell spawn of
  `git.exe` behaves as the probe assumes; and the `git.cmd` rule, which runs only simulated.
- `W_CONTEXT` is untuned (0.0) and the via path is off: consumer A is inert by default, and
  since T200-10 it costs nothing while it is.
- Re-reads after a B summary: no data yet.
