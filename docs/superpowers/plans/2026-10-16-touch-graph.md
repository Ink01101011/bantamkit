# Touch Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo every multi-unit run goes through the shiftwork tools (CLAUDE.md); the unit map is at the end.

**Goal:** Record what the agent touched (Read, Edit, Write, and the files a Bash turn changed), link those files to the facts that name them or were used next to them, and feed that graph to #199's ranker (`w_context`), a bounded `[via <file>]` admission, a short touch summary at SessionStart and after compaction, and an optional `file` argument on `memory_recall` (issue #200, milestone 0.37.0-beta).

**Architecture:**
- A new core package per runtime, `touch/`, holds six parts. `repo` finds the git toplevel without a subprocess and runs `git` when it must. `log` is the touch log, a #204 `LogSegment` at `~/.bantamkit/touch/<repo-id>.jsonl`, plus a per-session tool-call counter. `refs` extracts path references from fact text, resolves them through `git ls-files` and renames, and owns the shortest-unique-suffix rule. `bashturn` diffs two `git status` snapshots. `graph` is the derived index at `~/.bantamkit/graph/<repo-id>.json`. `context` turns the graph and this session's last 20 tool calls into ranker weights and the via pick. `summary` writes the B lines.
- The hot index (#204) fills its reserved `refs` slot, so the graph never parses a fact file.
- Consumers: the UserPromptSubmit hook passes a `TouchContext` into `Memory.recall_outcome`; SessionStart appends one B line; `memory_recall` gains `file`.

**Tech Stack:** Python 3.10+ stdlib (`subprocess`, `json`, `hashlib`, `re`, `os`); TypeScript on Node ≥ 20 (`node:child_process`, `node:fs`, `node:crypto`), no new dependency; `git` on PATH is optional (absent git = no touch features, everything else works); conformance harness `tools/conformance/run.mjs`; pytest; `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-15-touch-graph-design.md` (E1–E5, APPROVED; Gold line amended in 18da75c).

## Global Constraints

- Every feature lands in BOTH `runtime-py/` and `runtime-ts/` in the same task, with a conformance case comparing the two (CLAUDE.md, "Two runtimes, one surface"): same tool schema, same error sentence, same exit code. A deliberate divergence needs a `docs/porting.md` row, a `ruling:` case and, for a refusal, a non-ruled refusal-bit case.
- No new runtime dependency on either side. The npm install stays pure Node, with no Python at runtime.
- Must run on Windows and macOS. The only lock primitive is `O_EXCL` (`storage/lock.exclusive` / `exclusive` in `runtime-ts/src/storage/lock.ts`). Paths in the touch log and graph are repo-relative with `/` separators on every OS.
- **The graph is an enhancement. No failure in `touch/` may fail a hook or a recall** (spec, Error handling). Every entry point catches and degrades to "no context".
- **No git, or not inside a repo: nothing is recorded**, no rename following, no bash-turn, no B summary, `w_context` is 0.
- **Paths only.** The touch log never stores file content.
- **Reads made through Bash are never captured; a Bash call is never a touch line.**
- Every `git` call: argv list, no shell; env `GIT_OPTIONAL_LOCKS=0` (so `git status` never takes `index.lock` beside the user's own git), `LC_ALL=C`, `GIT_TERMINAL_PROMPT=0`; `-c core.quotepath=off`; NUL-separated output (`-z`) wherever git offers it; timeout `GIT_TIMEOUT_MS = 2000`; any failure returns `None`.
- Every regex shared by the two runtimes is ASCII-only and spelled with explicit classes (`[A-Za-z0-9_]`, never `\w`, `\s` or `\b`): the two engines disagree on Unicode classes (see `retrieval.stale`'s docstring, `runtime-py/src/bantamkit/memory/retrieval.py:278`).
- **Do not retune #199's constants** (`GATE_FLOOR`, `GATE_RATIO`, `W_TYPE`, `W_FRESH_DEMOTE`, `W_USAGE`, `W_FLOOR`): job68's J68-7 owns them. `W_CONTEXT` is the slot #199 reserved for #200 (`retrieval.py:262`, comment "the #200 slot"); only Task 8 sets its value, on #200's silver set, after J68-7 has frozen the rest.
- **Bar, declared before any number exists (Task 0 commits it first):**
  - precision of the via admission path ≥ **0.8** on gold pass 2. Otherwise the path ships **off by default** (`VIA_ON = False`) and `w_context` ranking stays on;
  - overall precision@inject no lower than #199 v2's gold precision@inject (J68-7's `gold-result.json`);
  - PostToolUse hook p50 rises by at most **2 ms** (Node hook, the shipped one);
  - the Stop `git status` p50 is at most **30 ms** on this repo.
  - Reported, not gated: whether sessions that received a B summary re-read fewer files.
- The #200 gold set is held out: `W_CONTEXT` and `CONTEXT_WEAK_SHARE` are tuned on silver only.
- **SAFETY:** every test and probe runs with `HOME` and `USERPROFILE` set to a throwaway dir, `BANTAMKIT_INDEX_DIR=<scratch>/index`, `BANTAMKIT_RETENTION=off`. Never write the real `~/.bantamkit` or `~/.claude`; never edit `~/.claude/settings.json`; never delete `~/.bantamkit/retention.json`.
- Conformance runs with `TMPDIR=<own scratchpad>/cleantmp/` after `cd runtime-ts && npm run build`.
- **Mutations:** every new conformance case is proven red by a one-sided mutation, run on an rsync copy of the tree (never on the working tree a sibling unit holds); each new suite carries at least one symmetric mutation caught only by a per-side literal (`literalCases`, shape at `tools/conformance/suites/recall-usage.mjs:338`). The copy-and-run script, saved per unit as `.shiftwork/notes-<job>/<unit>-mut.sh`:

```bash
#!/bin/bash
# usage: mut.sh <ID> <suite...> -- copy the tree, apply mutation <ID> with mut.py, build, run the suites
set -u
REPO=/Users/kktest/Documents/Claude/Projects/bantamkit
HERE=<own scratchpad>/mut
ID=$1; shift
M=$HERE/copy-$ID; CT=$HERE/ct-$ID; FH=$HERE/home-$ID
rm -rf "$M" "$CT" "$FH"; mkdir -p "$CT" "$FH"
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork "$REPO/" "$M/"
ln -s "$REPO/runtime-ts/node_modules" "$M/runtime-ts/node_modules"
"$REPO/.venv/bin/python" "$HERE/mut.py" "$M" "$ID" || exit 2
(cd "$M/runtime-ts" && npm run build >/dev/null 2>&1) || { echo BUILD FAILED; exit 3; }
for s in "$@"; do
  echo "== suite $s"
  (cd "$M" && HOME=$FH USERPROFILE=$FH TMPDIR=$CT BANTAMKIT_RETENTION=off BANTAMKIT_INDEX_DIR=$FH/index \
     PYTHONPATH=$M/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=$REPO/.venv/bin/python \
     node tools/conformance/run.mjs --suite "$s" 2>&1 | grep -E "✖|^(PASS|FAIL)")
done
```

  `mut.py <copy> <ID>` does one exact `str.replace` on one file per ID and exits 2 when the old text is not found (so a mutation that silently misses cannot report "green").
- Never weaken or delete an existing case. A case that pins old behaviour is changed only where this plan names it, citing `#200` in the case name, before and after recorded in the unit note.
- Gates before every commit:
  - `.venv/bin/python -m pytest runtime-py/tests -q`
  - `cd runtime-ts && npm run build && npm test`
  - `.venv/bin/ruff check runtime-py tools`
  - `node tools/conformance/run.mjs --all`
- Commit only your own files by explicit path (`git add <paths> && git diff --cached --stat`); never `-a`/`-A`. No push, tag, bump or publish on this branch.

## Start state

- **Branch:** `feat/199-recall-by-meaning`, after job68 closes (J68-7 tuned and gold-scored, J68-8 docs/reviewer done). #200 ships in 0.37.0-beta.1 with #199 and #204.
- Fresh tree: `python3 -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"`, then `cd runtime-ts && npm ci && npm run sync-assets && npm run build`.
- **The ranker slot:** `W_CONTEXT = 0.0` at `runtime-py/src/bantamkit/memory/retrieval.py:262`, used as `+ W_CONTEXT * 0.0` inside `weight_of` (`:310`). Node: `runtime-ts/src/memory/retrieval.ts:309` and `weightOf` at `:358`. Per-row weights are built by `Pool.weights` (`runtime-py/src/bantamkit/memory/store.py:423`; Node `poolWeights`, `runtime-ts/src/memory/store.ts:584`) inside `pooled_ranking` (`store.py:527`; Node `pooledRanking`, `store.ts:653`), called by `pick_hits` (`store.py:578`; Node `pickHits`, `store.ts:708`) from `Memory._pooled` (`runtime-py/src/bantamkit/memory/component.py:623`).
- **The hook calls** `m.recall_outcome(prompt, 3, stamp=False)` in `_user_prompt_submit` (`runtime-py/src/bantamkit/hookadapter.py:1206`); Node `m.recallOutcome(prompt, 3, RECALL_MIN_SCORE_RATIO, false)` (`runtime-ts/src/hookadapter.ts:1343`). Injected headers are parsed with `RECALL_HEADER = ^\[([^\]]+)\] \[([^\]]+)\] \(([a-z]+)\) (.*)$` (`hookadapter.py:1154`).
- **PostToolUse is already registered matcher-less** (`HOOK_EVENTS`, `runtime-py/src/bantamkit/hostinstall.py:465`), and dispatch runs `_append_usage_event` for every tool (`hookadapter.py:2454`). No hook registration changes in this plan.
- **The hot index reserves `refs`**: `_DOC_LIST = ("keywords", "links", "tags", "refs")` (`runtime-py/src/bantamkit/storage/hotindex.py:186`), always written `[]` (`:870`, `:894`); spec S6 of #204 names it "path references, for #200". `INDEX_VERSION = 4` (`:82`).
- **The MCP server has no session id.** `mcpserver.py` never reads one (`grep -n session_id runtime-py/src/bantamkit/mcpserver.py` is empty), and no tool argument carries one, so the usage ledger (written by the server, `component.py:705` `_use`) cannot learn a session or a tool-call ordinal. See "Spec deviations" below.
- `memory_recall`'s schema lives in `assets/tools/memory_recall.json` (`required: ["query"]`); handlers at `runtime-py/src/bantamkit/mcpserver.py:1497` and `runtime-ts/src/mcp/server.ts:593`; the J69-5 `include_archived` wire block at `tools/conformance/suites/wire.mjs:548` is the template for a new argument.
- Eval harness: `tools/eval/recall/{score.py,bar.json,build_gold.py,mine_silver.py,gold-label.html}`. `gold-label.html` normalises each row to `{id, prompt, candidates, thai}` (`:121`), so pass 2 puts the touch context inside `prompt`.

## Spec deviations resolved in this plan (each also in `.shiftwork/notes-job70p/P-200.md`)

1. **Weak-edge "use" events are recorded by the hook into the touch log, not by the server into the usage ledger.** The spec says "the usage ledger gains an optional `session` field". The server cannot know the session or the tool-call ordinal (Start state). The PostToolUse hook sees both for `mcp__bantamkit__memory_recall` and `memory_save` calls, so it appends `{ts, session, seq, op: "use", fact, kind}` lines to the touch log. The usage ledger is untouched. *(Open question Q1.)*
2. **`seq` counts every tool call of the session in the repo**, kept in `~/.bantamkit/hooks/ledger-<session>.seq.json` under the O_EXCL lock. PostCompact unlinks only `ledger-<session>.json` (`hookadapter.py:2055`), so the counter survives compaction; Retention's 7-day ledger rule (`_LEDGER = ledger-[\s\S]*\.json`, `storage/retention.py:71`) prunes it.
3. **bash-turn lines carry `from`**, the seq at the turn's snapshot, so "turn granularity" is computable: a use co-occurs with a bash-turn write when its seq lies in `(from, seq]`.
4. **The graph has two fingerprints**, one per half: `strong` keys on git HEAD + the git index stat + each layer's index-head print; `weak` keys on the touch-log size. One fingerprint over all three (the spec's wording) would rebuild the git half, two subprocesses, after every tool call.
5. **The `[via <file>]` label is a suffix**: `[project] [name] (type) description [via store.ts]`. A prefix would stop `RECALL_HEADER` from matching and the hook would drop the line.
6. **The via fact is appended after the k gated hits** (so up to k+1 lines), then the existing 700-byte `_cap_lines` cap drops whole lines from the end, the via line first. *(Open question Q2.)*
7. **`VIA_ON = False` until Task 8 measures gold pass 2 ≥ 0.8.** "Ships off by default if it misses" is read as "on only once it has passed". An operator switch `BANTAMKIT_VIA=on|off` (both runtimes, documented) overrides the default; it is new surface the spec does not name, added so the path can be exercised end to end before the default flips. *(Open question Q3.)*
8. **"After compact" is SessionStart with `source == "compact"`**, the injection the fresh context receives. PreCompact's read list is unchanged. *(Open question Q4.)*
9. **`memory_recall`'s `required` becomes `[]`.** A call with neither `query` nor `file` raises `memory_recall needs a query or a file.` on both runtimes. With `file`, any `query` is ignored and the reply's first line says so. *(Open question Q5.)*
10. **A bare reference that matches several tracked files makes no edge** (ambiguous); an absolute path inside the toplevel is made relative; one outside it resolves by suffix like any other.
11. **B commit window:** commits whose committer date lies in `[first touch, last touch + SUMMARY_COMMIT_GRACE_S]` with `SUMMARY_COMMIT_GRACE_S = 1800`, because the commit usually follows the session's last edit.
12. **Touch-log retention:** lines older than 30 days fold into one `{"op":"folded", path, last, n}` line per path, so "last touched" survives; uses older than 30 days are dropped (their weak weight is below 0.5^(30/14) ≈ 0.23 of a fresh one).

## File Structure

| File | Responsibility |
|---|---|
| `runtime-py/src/bantamkit/touch/__init__.py`, `runtime-ts/src/touch/index.ts` (new) | Re-exports, one line per module |
| `touch/repo.py`, `touch/repo.ts` (new) | `find_repo`, `Repo`, `git`, `head_print`, `ls_files`, `renames`, `relpath` |
| `touch/log.py`, `touch/log.ts` (new) | `TouchLog`, `next_seq`/`current_seq`, `touch_reducer`, `use_names` |
| `touch/refs.py`, `touch/refs.ts` (new) | `extract_refs`, `fact_refs`, `FileSet`, `resolve_ref`, `shortest_suffix` |
| `touch/bashturn.py`, `touch/bashturn.ts` (new) | `snapshot`, `changed`, `save_turn`, `load_turn` |
| `touch/graph.py`, `touch/graph.ts` (new) | `TouchGraph`, `build_strong`, `build_weak` |
| `touch/context.py`, `touch/context.ts` (new) | `TouchContext`, `window`, `context_weights`, `via_pick`, the #200 constants |
| `touch/summary.py`, `touch/summary.ts` (new) | `last_session_line`, `compact_line`, `age_text` |
| `touch/recallfile.py`, `touch/recallfile.ts` (new) | The five `memory_recall({file})` sentences and the touch-history line |
| `runtime-py/src/bantamkit/hookadapter.py`, `runtime-ts/src/hookadapter.ts` | PostToolUse touch/use lines; UserPromptSubmit snapshot + context; Stop bash-turn; SessionStart B line |
| `memory/retrieval.*`, `memory/store.*`, `memory/component.*` | `ctx` argument in `weight_of`; `context` threaded to `rank`; `recall_outcome(context=)`; `recall_file` |
| `storage/hotindex.*` | `refs` filled; `INDEX_VERSION = 5` |
| `storage/tiers.*`, `storage/retention.*` | touch logs in the status `logs:` lines, a `touch:` miss line; touch-log fold |
| `mcpserver.py`, `runtime-ts/src/mcp/server.ts`, `assets/tools/memory_recall.json` | `file` argument |
| `tools/conformance/suites/touch-log.mjs`, `touch-refs.mjs`, `touch-turn.mjs`, `touch-graph.mjs`, `touch-context.mjs`, `touch-summary.mjs` + `ref/touch_ref.py` (new); `wire.mjs`, `storage-index.mjs` | Parity |
| `tools/eval/recall/bar-touch.json`, `mine_touch_silver.py`, `score_touch.py`, `build_via_gold.py`, `tune_context.py`, `bench_touch.mjs`, `test_eval_touch.py` (new) | Eval and the bar |
| `docs/touch.md` (new), `docs/memory.md`, `docs/hooks.md`, `docs/storage.md`, `docs/conformance.md`, `docs/porting.md` | Docs |

---

### Task 0: Declare the bar; measure the latency baseline

**Files:**
- Create: `tools/eval/recall/bar-touch.json`, `tools/eval/recall/bench_touch.mjs`
- Output (gitignored): `.shiftwork/notes-<job>/T200-0.md`, `baseline-latency.json`

**Interfaces:**
- Produces: `node tools/eval/recall/bench_touch.mjs <label> <cli.js> [--git <repo>]` prints one JSON line `{"label": str, "event": str, "p50_ms": float, "p95_ms": float, "n": int}` per event (`PostToolUse-Read`, `PostToolUse-Bash`, `UserPromptSubmit`, `Stop`, `SessionStart`), plus with `--git` one line `{"event": "git-status", ...}` timing `git status --porcelain=v1 -z -uall` in `<repo>` alone.

- [ ] **Step 1: Commit the bar before anything is measured**

```json
{
  "declared": "2026-10-16",
  "spec": "docs/superpowers/specs/2026-10-15-touch-graph-design.md",
  "via_precision_gold_min": 0.8,
  "via_off_by_default_if_missed": true,
  "precision_at_inject_min": "j68_7_v2_gold_precision_at_inject",
  "posttooluse_p50_rise_ms_max": 2.0,
  "stop_git_status_p50_ms_max": 30.0,
  "latency_runtime": "node runtime-ts/dist/cli.js --hook, 15 cold runs per event, throwaway HOME",
  "git_status_repo": "this repository at the measuring commit",
  "gold_is_held_out": true,
  "gold_pass": 2,
  "gold_rows_max": 50,
  "gold_seed": 200,
  "eval_scope": "sessions whose cwd is this repository (strong edges resolve against its ls-files)",
  "unlabelled_injection_counts_as": "not relevant",
  "reported_not_gated": ["re-reads after a B summary"]
}
```

Run: `git add tools/eval/recall/bar-touch.json && git diff --cached --stat && git commit -m "eval(touch): declare the #200 bar before any number exists (#200)"`

- [ ] **Step 2: Write `bench_touch.mjs`** by copying `.shiftwork/notes-job67/J67-5-bench.mjs` (its throwaway-HOME bed, 15 cold `spawnSync` runs per event, p50/p95) into `tools/eval/recall/bench_touch.mjs`, and adding:
  - `--git <repo>`: the bed's project directory is `git init`-ed with one committed file `a.txt` and one untracked `b.txt`, so PostToolUse/Stop find a repo;
  - a `PostToolUse-Read` payload `{"hook_event_name":"PostToolUse","tool_name":"Read","tool_input":{"file_path":"<proj>/a.txt"},"session_id":"bench","cwd":"<proj>"}` and a `PostToolUse-Bash` payload with `tool_name: "Bash"`;
  - the `git-status` line: 15 runs of `spawnSync('git', ['-c','core.quotepath=off','status','--porcelain=v1','-z','-uall'], {cwd: repo, env: {...process.env, GIT_OPTIONAL_LOCKS: '0', LC_ALL: 'C'}})` against the repo given.

  Every run sets `HOME`, `USERPROFILE`, `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off` to the bed.
- [ ] **Step 3: Baseline.** `cd runtime-ts && npm run build`, then
  `node tools/eval/recall/bench_touch.mjs base runtime-ts/dist/cli.js --git $PWD > .shiftwork/notes-<job>/baseline-latency.json`.
  Expected: five event lines and one `git-status` line. Record the load average beside them (`uptime`), because siblings building move p50 by several ms (J67-5 note).
- [ ] **Step 4: Commit** `bench_touch.mjs` (`eval(touch): hook latency bench with a git bed (#200)`).

---

### Task 1: The touch log, the per-session counter, and the PostToolUse arm

**Files:**
- Create: `runtime-py/src/bantamkit/touch/{__init__,repo,log}.py`, `runtime-ts/src/touch/{index,repo,log}.ts`, `runtime-py/tests/test_touch_log.py`, `runtime-ts/test/touch-log.test.mjs`, `tools/conformance/suites/touch-log.mjs`, `tools/conformance/ref/touch_ref.py`
- Modify: `runtime-py/src/bantamkit/hookadapter.py` (dispatch at `:2454`), `runtime-ts/src/hookadapter.ts` (dispatch in `runHook`, `:2591`); `runtime-py/src/bantamkit/storage/tiers.py` (`_logs` at `:136`, `status_lines` at `:180`), `runtime-ts/src/storage/tiers.ts` (`logs` at `:121`); `runtime-py/src/bantamkit/storage/retention.py` (`_fold_logs` at `:242`) and `runtime-ts/src/storage/retention.ts`

**Interfaces:**
- Produces (Python; Node mirrors in camelCase):
  - `Repo(top: str, gitdir: str, id: str)` — `top` is the realpath of the toplevel, `id = sha16(top)` (`storage.hotindex.sha16`).
  - `find_repo(cwd: str) -> Repo | None`: walks up from `cwd` for `.git` (a directory, or a file `gitdir: <path>`); no subprocess.
  - `relpath(repo: Repo, path: str) -> str | None`: realpath of `path` relative to `repo.top` with `/` separators; `None` outside the toplevel or for the toplevel itself.
  - `git(repo: Repo, args: list[str], timeout_ms: int = GIT_TIMEOUT_MS) -> str | None` (stdout as UTF-8, `errors="replace"`).
  - `TouchLog(home: Path, repo_id: str)`: `.path = home/.bantamkit/touch/<repo_id>.jsonl`; `.append_touch(session, seq, op, path, via=None, frm=None, ts=None) -> bool`; `.append_use(session, seq, fact, kind, ts=None) -> bool`; `.read() -> list[dict]`; `.tail(session: str, after_seq: int) -> list[dict]` (this session's rows with `seq > after_seq`, read from the last `TOUCH_TAIL_BYTES` of the live file); `.skipped: int`.
  - Line shapes, key order fixed: touch `{"ts","session","seq","op","path"}` + `"via"` + `"from"` when given; use `{"ts","session","seq","op":"use","fact","kind"}` with `kind ∈ {"recall_hit","save"}`. Bytes are `storage.logsegment.dumps_line`.
  - `next_seq(state_dir: str, session: str) -> int` (lock, read, +1, write, return); `current_seq(state_dir, session) -> int` (0 when absent).
  - `TOUCH_OPS = {"Read": "read", "Edit": "edit", "MultiEdit": "edit", "Write": "write", "NotebookEdit": "edit"}`; the path is `tool_input.file_path`, or `tool_input.notebook_path` for NotebookEdit.
  - `use_names(tool: str, tool_input: dict, response: Any) -> list[tuple[str, str]]`: `(fact, kind)` pairs. `memory_save` → `[(tool_input.name, "save")]` when a string; `memory_recall` → one `recall_hit` per header line of the response text matched by `USE_HEADER = ^(?:\[[^\]\n]+\] )*\[([^\]\n]+)\] \([a-z]+\) ` (multiline), in order, deduped. The response text is the string itself, or the `text` fields of a list of `{"type":"text"}` blocks joined by `\n`, or the same under a dict's `content`/`result` key.
  - `touch_reducer(rows: list[dict]) -> list[dict]`: one `{"ts": last_ts, "session": "", "seq": 0, "op": "folded", "path": p, "n": count}` per path, in path order; `use` rows are dropped.
  - Constants: `GIT_TIMEOUT_MS = 2000`, `TOUCH_TAIL_BYTES = 65536`.
  - Hook arm `_record_touch(run: HookRun, payload: dict) -> None` (Node `recordTouch`), called from the PostToolUse dispatch before `_append_usage_event`.
  - `bantamkit_status` gains `logs: touch/<id> …` lines (from `_logs`) and one line `touch: <n> missed writes (hook log)` counting hook-log rows with `"touch": "miss"`; `touch: none` when the touch directory does not exist.

- [ ] **Step 1: Failing tests (Python; mirror every one in `touch-log.test.mjs`)**

```python
# runtime-py/tests/test_touch_log.py
import json
import subprocess
from pathlib import Path

from bantamkit.touch.log import TouchLog, current_seq, next_seq, touch_reducer, use_names
from bantamkit.touch.repo import find_repo, relpath


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "src" / "a.py").write_text("x\n", encoding="utf-8")
    return r


def test_find_repo_walks_up_and_ids_the_realpath(tmp_path):
    r = _repo(tmp_path)
    found = find_repo(str(r / "src"))
    assert found is not None and Path(found.top) == r.resolve() and len(found.id) == 16
    assert find_repo(str(tmp_path)) is None


def test_relpath_is_slash_separated_and_none_outside(tmp_path):
    r = _repo(tmp_path)
    repo = find_repo(str(r))
    assert relpath(repo, str(r / "src" / "a.py")) == "src/a.py"
    assert relpath(repo, str(tmp_path / "elsewhere.py")) is None


def test_touch_line_bytes(tmp_path):
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    assert log.append_touch("s1", 3, "edit", "src/a.py", ts="2026-10-16T00:00:00Z")
    assert log.append_touch("s1", 9, "write", "b.txt", via="bash-turn", frm=4, ts="2026-10-16T00:00:01Z")
    assert log.append_use("s1", 10, "fact-a", "recall_hit", ts="2026-10-16T00:00:02Z")
    assert log.path.read_text(encoding="utf-8").splitlines() == [
        '{"ts":"2026-10-16T00:00:00Z","session":"s1","seq":3,"op":"edit","path":"src/a.py"}',
        '{"ts":"2026-10-16T00:00:01Z","session":"s1","seq":9,"op":"write","path":"b.txt","via":"bash-turn","from":4}',
        '{"ts":"2026-10-16T00:00:02Z","session":"s1","seq":10,"op":"use","fact":"fact-a","kind":"recall_hit"}',
    ]


def test_tail_is_this_session_after_seq(tmp_path):
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    for seq, session in [(1, "s1"), (2, "s2"), (5, "s1"), (6, "s1")]:
        log.append_touch(session, seq, "read", f"f{seq}", ts="2026-10-16T00:00:00Z")
    assert [r["seq"] for r in log.tail("s1", 1)] == [5, 6]


def test_corrupt_line_is_skipped_and_counted(tmp_path):
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    log.append_touch("s1", 1, "read", "a", ts="2026-10-16T00:00:00Z")
    with log.path.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    assert len(log.read()) == 1 and log.skipped == 1


def test_unwritable_log_answers_false(tmp_path):
    (tmp_path / "home" / ".bantamkit").mkdir(parents=True)
    (tmp_path / "home" / ".bantamkit" / "touch").write_text("a file, not a dir")
    assert TouchLog(tmp_path / "home", "0123456789abcdef").append_touch("s", 1, "read", "a") is False


def test_seq_counts_up_per_session(tmp_path):
    state = str(tmp_path / "state")
    assert current_seq(state, "s1") == 0
    assert [next_seq(state, "s1") for _ in range(3)] == [1, 2, 3]
    assert next_seq(state, "s2") == 1 and current_seq(state, "s1") == 3


def test_use_names_from_recall_reply_and_save():
    reply = "[project] [fact-a] (project) d\nbody\n\n[profile] [fact-b] (feedback) e\nbody [x] (y) z"
    assert use_names("mcp__bantamkit__memory_recall", {"query": "q"}, [{"type": "text", "text": reply}]) == [
        ("fact-a", "recall_hit"), ("fact-b", "recall_hit")]
    assert use_names("mcp__bantamkit__memory_recall", {}, "[solo] (user) one-layer header\nb") == [("solo", "recall_hit")]
    assert use_names("mcp__bantamkit__memory_save", {"name": "n1"}, "saved") == [("n1", "save")]
    assert use_names("Bash", {"command": "ls"}, "x") == []


def test_reducer_keeps_last_touch_per_path_and_drops_uses():
    rows = [
        {"ts": "2026-09-01T00:00:00Z", "session": "a", "seq": 1, "op": "read", "path": "p"},
        {"ts": "2026-09-02T00:00:00Z", "session": "a", "seq": 2, "op": "edit", "path": "p"},
        {"ts": "2026-09-03T00:00:00Z", "session": "a", "seq": 3, "op": "use", "fact": "f", "kind": "save"},
    ]
    assert touch_reducer(rows) == [
        {"ts": "2026-09-02T00:00:00Z", "session": "", "seq": 0, "op": "folded", "path": "p", "n": 2}]
```

Plus two hook tests in `runtime-py/tests/test_hookadapter.py`, using that file's existing `run_hook` fixture with a sandboxed `HOME`:

```python
def test_post_tool_use_records_edit_and_never_bash(tmp_path, monkeypatch):
    home = tmp_path / "home"; monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("USERPROFILE", str(home))
    r = tmp_path / "repo"; (r / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for tool, ti in [("Edit", {"file_path": str(r / "src" / "a.py")}), ("Bash", {"command": "cat src/a.py"}),
                     ("Read", {"file_path": str(r / "src" / "a.py")})]:
        _run_hook({"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti,
                   "session_id": "s1", "cwd": str(r)})
    lines = [json.loads(x) for x in next((home / ".bantamkit" / "touch").glob("*.jsonl")).read_text().splitlines()]
    assert [(x["op"], x["path"], x["seq"]) for x in lines] == [("edit", "src/a.py", 1), ("read", "src/a.py", 3)]


def test_post_tool_use_outside_a_repo_records_nothing(tmp_path, monkeypatch):
    home = tmp_path / "home"; monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("USERPROFILE", str(home))
    (tmp_path / "plain").mkdir()
    _run_hook({"hook_event_name": "PostToolUse", "tool_name": "Edit",
               "tool_input": {"file_path": str(tmp_path / "plain" / "a.py")}, "session_id": "s1", "cwd": str(tmp_path / "plain")})
    assert not (home / ".bantamkit" / "touch").exists()
```

`_run_hook` is the helper the file already uses to feed a payload on stdin (`grep -n "def _run\|run_hook(" runtime-py/tests/test_hookadapter.py | head`); use it as it is. Seq 3 for the Read is right: the Bash call between them is counted, not recorded.

- [ ] **Step 2: Run them and see them fail.**
Run: `.venv/bin/python -m pytest runtime-py/tests/test_touch_log.py -q`
Expected: `ModuleNotFoundError: No module named 'bantamkit.touch'`.

- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/touch/repo.py
"""The git repository a hook or a recall runs in (#200). Finding it costs stats, never a subprocess."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from bantamkit.storage.hotindex import sha16

GIT_TIMEOUT_MS = 2000
_GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}


@dataclass(frozen=True)
class Repo:
    top: str     # realpath of the toplevel
    gitdir: str  # the repository's git directory (a worktree's own, for a linked worktree)
    id: str      # sha16(top)


def find_repo(cwd: str) -> Repo | None:
    try:
        here = os.path.realpath(cwd)
    except (OSError, ValueError):
        return None
    while True:
        dot = os.path.join(here, ".git")
        try:
            if os.path.isdir(dot):
                return Repo(here, dot, sha16(here))
            if os.path.isfile(dot):
                with open(dot, encoding="utf-8", errors="replace") as f:
                    first = f.readline().strip()
                if first.startswith("gitdir:"):
                    gd = first[len("gitdir:"):].strip()
                    gd = gd if os.path.isabs(gd) else os.path.join(here, gd)
                    return Repo(here, os.path.realpath(gd), sha16(here))
        except OSError:
            return None
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def relpath(repo: Repo, path: str) -> str | None:
    try:
        real = os.path.realpath(path)
        rel = os.path.relpath(real, repo.top)
    except (OSError, ValueError):  # ValueError: another drive on Windows
        return None
    if rel == "." or rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        return None
    return rel.replace(os.sep, "/")


def git(repo: Repo, args: list[str], timeout_ms: int = GIT_TIMEOUT_MS) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell
            ["git", "-c", "core.quotepath=off", *args],
            cwd=repo.top, capture_output=True, timeout=timeout_ms / 1000,
            env={**os.environ, **_GIT_ENV},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")
```

```python
# runtime-py/src/bantamkit/touch/log.py
"""The touch log (#200): one line per Read/Edit/Write the agent made, per fact it used, per file a
Bash turn changed. A #204 LogSegment; paths only, never content."""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bantamkit.storage.lock import exclusive
from bantamkit.storage.logsegment import LogSegment, _load, _split

TOUCH_OPS = {"Read": "read", "Edit": "edit", "MultiEdit": "edit", "Write": "write", "NotebookEdit": "edit"}
TOUCH_TAIL_BYTES = 65536
USE_HEADER = re.compile(r"^(?:\[[^\]\n]+\] )*\[([^\]\n]+)\] \([a-z]+\) ", re.MULTILINE)
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")  # the ledger file-name rule, `hookadapter._LEDGER_UNSAFE`


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class TouchLog:
    def __init__(self, home: Path | str, repo_id: str) -> None:
        self.path = Path(home) / ".bantamkit" / "touch" / f"{repo_id}.jsonl"
        self.skipped = 0

    def _seg(self) -> LogSegment:
        return LogSegment(self.path)

    def append_touch(self, session: str, seq: int, op: str, path: str, via: str | None = None,
                     frm: int | None = None, ts: str | None = None) -> bool:
        row: dict[str, Any] = {"ts": ts or _now(), "session": session, "seq": seq, "op": op, "path": path}
        if via is not None:
            row["via"] = via
        if frm is not None:
            row["from"] = frm
        return self._seg().append(row)

    def append_use(self, session: str, seq: int, fact: str, kind: str, ts: str | None = None) -> bool:
        return self._seg().append(
            {"ts": ts or _now(), "session": session, "seq": seq, "op": "use", "fact": fact, "kind": kind})

    def read(self) -> list[dict[str, Any]]:
        seg = self._seg()
        rows = seg.read()
        self.skipped = seg.skipped
        return rows

    def tail(self, session: str, after_seq: int) -> list[dict[str, Any]]:
        self.skipped = 0
        try:
            with open(self.path, "rb") as f:
                end = f.seek(0, os.SEEK_END)
                f.seek(max(0, end - TOUCH_TAIL_BYTES))
                data = f.read()
        except OSError:
            return []
        lines = _split(data)
        if end > TOUCH_TAIL_BYTES and lines:
            lines = lines[1:]  # the first line may be cut by the seek
        out = []
        for line in lines:
            row = _load(line)
            if row is None:
                self.skipped += 1
                continue
            seq = row.get("seq")
            if row.get("session") == session and isinstance(seq, int) and not isinstance(seq, bool) and seq > after_seq:
                out.append(row)
        return out


def _seq_path(state_dir: str, session: str) -> str:
    return os.path.join(state_dir, f"ledger-{_UNSAFE.sub('_', session or 'nosession')}.seq.json")


def current_seq(state_dir: str, session: str) -> int:
    try:
        with open(_seq_path(state_dir, session), encoding="utf-8") as f:
            v = json.load(f).get("seq")
    except (OSError, ValueError, AttributeError):
        return 0
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def next_seq(state_dir: str, session: str) -> int:
    p = _seq_path(state_dir, session)
    os.makedirs(state_dir, exist_ok=True)
    with exclusive(p):
        n = current_seq(state_dir, session) + 1
        tmp = f"{p}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"seq": n}, separators=(",", ":")))
        os.replace(tmp, p)
    return n


def _text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("content", "result"):
            if key in response:
                return _text(response[key])
        return ""
    if isinstance(response, list):
        return "\n".join(b["text"] for b in response
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return ""


def use_names(tool: str, tool_input: dict[str, Any], response: Any) -> list[tuple[str, str]]:
    if tool == "mcp__bantamkit__memory_save":
        name = tool_input.get("name")
        return [(name, "save")] if isinstance(name, str) and name else []
    if tool == "mcp__bantamkit__memory_recall":
        seen: list[str] = []
        for m in USE_HEADER.finditer(_text(response)):
            if m.group(1) not in seen:
                seen.append(m.group(1))
        return [(n, "recall_hit") for n in seen]
    return []


def touch_reducer(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[Any]] = {}
    for r in rows:
        if r.get("op") in ("read", "edit", "write", "folded") and isinstance(r.get("path"), str):
            n = r.get("n", 1) if r.get("op") == "folded" else 1
            ts = r.get("ts") if isinstance(r.get("ts"), str) else ""
            cur = by.setdefault(r["path"], ["", 0])
            cur[0] = max(cur[0], ts)
            cur[1] += n if isinstance(n, int) and not isinstance(n, bool) else 1
    return [{"ts": by[p][0], "session": "", "seq": 0, "op": "folded", "path": p, "n": by[p][1]}
            for p in sorted(by)]
```

Hook arm, in `hookadapter.py` beside `_append_usage_event`:

```python
def _record_touch(run: HookRun, payload: dict[str, Any]) -> None:
    """One touch or use line per PostToolUse in a git repo (#200). Never raises, never emits."""
    try:
        repo = find_repo(str(payload.get("cwd") or os.getcwd()))
        if repo is None:
            return
        session = _js_str(payload.get("session_id") or "")
        seq = next_seq(run.state, session)  # EVERY tool call counts, Bash included
        tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else ""
        ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        log = TouchLog(run.home, repo.id)
        ok = True
        op = TOUCH_OPS.get(tool)
        if op is not None:
            raw = ti.get("notebook_path" if tool == "NotebookEdit" else "file_path")
            rel = relpath(repo, raw) if isinstance(raw, str) and raw else None
            if rel is not None:
                ok = log.append_touch(session, seq, op, rel)
        for fact, kind in use_names(tool, ti, payload.get("tool_response")):
            ok = log.append_use(session, seq, fact, kind) and ok
        if not ok:
            _log(run, {"event": "PostToolUse", "touch": "miss", "tool": tool})
    except Exception:  # noqa: BLE001 - the graph is an enhancement (#200, Error handling)
        _log(run, {"event": "PostToolUse", "touch": "miss"})
```

Dispatch (`hookadapter.py:2454`): `_record_touch(run, payload)` first, then `_append_usage_event(run, payload)` as today. A rotate is not done here: Retention (below) folds and rotates, so the 2 ms PostToolUse budget pays one locked append only.

Status: `_logs` (`tiers.py:136`) appends `(f"touch/{n[:-6]}", base / "touch" / n)` for each `*.jsonl` in `base / "touch"`, sorted, after the usage ledgers. `status_lines` gains `touch_line(home)` after `*log_lines(home)`: `touch: none` when `<home>/.bantamkit/touch` is not a directory, else `touch: <n> missed writes (hook log)` where `n` counts rows of `LogSegment(<home>/.bantamkit/hooks/hook-log.jsonl).read()` with `row.get("touch") == "miss"`.

Retention (`retention.py:242`, `_fold_logs`): for each `*.jsonl` under `base / "touch"`, `seg.fold(cutoff_iso, touch_reducer)` with the same 30-day cutoff the usage ledgers use, then the existing 30-days-idle `rotate(0)` path through the same `logs` list.

- [ ] **Step 4: Implement (Node)** `runtime-ts/src/touch/{repo,log,index}.ts` with the same names in camelCase:
  - `findRepo` uses `fs.realpathSync.native`, `fs.statSync(...).isDirectory()/isFile()`; `relPath` uses `path.relative` and replaces `path.sep` with `/`;
  - `git` uses `spawnSync('git', ['-c', 'core.quotepath=off', ...args], {cwd, env: {...process.env, ...GIT_ENV}, timeout: GIT_TIMEOUT_MS, windowsHide: true, encoding: 'buffer'})` and `stdout.toString('utf8')`; `null` on `error`, a signal, or a non-zero status;
  - `TouchLog` builds on `LogSegment` from `../storage/index.js`; rows are built as object literals in the key order above so `JSON.stringify` writes the Python bytes;
  - `nextSeq` takes `exclusive` from `../storage/lock.js` and writes temp-then-`renameSync`;
  - `USE_HEADER = /^(?:\[[^\]\n]+\] )*\[([^\]\n]+)\] \([a-z]+\) /gm`;
  - `recordTouch(run, input)` in `hookadapter.ts`, called first in the `PostToolUse` case of `runHook`; `tiers.ts` `logs` and a `touchLine`; `retention.ts` folds `touch/*.jsonl` through `touchReducer`.

  Every `fs` error is caught and becomes `false`, `0`, `[]` or a `touch: miss` hook-log record.
- [ ] **Step 5: Run the unit tests to see them pass** (`.venv/bin/python -m pytest runtime-py/tests/test_touch_log.py runtime-py/tests/test_hookadapter.py -q`; `cd runtime-ts && npm run build && node --test test/touch-log.test.mjs`).
- [ ] **Step 6: Conformance `touch-log.mjs` + `ref/touch_ref.py`.**
  - `touch_ref.py` takes `{"op": ..., ...}` scripts against `bantamkit.touch` (it imports, never copies, as `usage_ref.py`'s docstring explains): `append_touch`, `append_use`, `read`, `tail`, `skipped`, `bytes`, `next_seq`, `current_seq`, `use_names`, `reduce`, `find_repo` (answers `{top_rel, id_len}` with `top` made relative to the bed), `relpath`.
  - Module cases: the line bytes for each op and for `via`+`from`; Thai and astral paths; a corrupt line; `tail` across a cut first line (a log over `TOUCH_TAIL_BYTES`); `use_names` over a string reply, a block list, a `{"content": [...]}` dict, a body line that looks like a header but follows `\n` mid-body (it IS matched: the reply's own headers and a body line are indistinguishable, so this case pins the behaviour, documented in `docs/touch.md`), and a Bash tool; the reducer over folded + live rows; `find_repo` from a nested dir, a `.git` file (linked worktree), and no repo.
  - Hook cases, two processes over one bed (copy `runHook` and `bed` from `tools/conformance/suites/hooks.mjs:185-220`): the bed is `git init`-ed by the harness; the payload script Edit, Bash, Read, Write outside the repo, NotebookEdit, a `memory_recall` with a two-header reply, a `memory_save`; compare the touch-log bytes with `ts` masked to `<ts>` and the `.seq.json` bytes. A second bed with no `.git` compares "no touch directory".
  - `bantamkit_status`: the `logs: touch/<id>` line (id masked) and the `touch:` line after one forced miss (the touch path made a file).
  - Literals per side: the first touch line's bytes (ts masked) `{"ts":"<ts>","session":"s1","seq":1,"op":"edit","path":"src/a.py"}`; for the hook script Edit(1), Bash(2), Read(3), Write outside the repo(4), NotebookEdit(5), memory_recall with two headers(6), memory_save(7), the recorded `[op, seq]` list `[["edit",1],["read",3],["edit",5],["use",6],["use",6],["use",7]]`; `[false, false]` for the unwritable append.
  - Mutations (`mut.sh`): Node records Bash as `write` (red: hook bytes); Python stores the absolute path (red: hook bytes); Node does not count Bash in `seq` (red: seq bytes); symmetric: both drop `seq` from the touch line (red only on the first-line literal).
- [ ] **Step 7: Run the gates and commit** (`feat(touch): the touch log, a per-session tool-call counter, PostToolUse touch and use lines (#200)`).

---

### Task 2: Ref extractor, renames, shortest unique suffix; the hot index fills `refs`

**Files:**
- Create: `runtime-py/src/bantamkit/touch/refs.py`, `runtime-ts/src/touch/refs.ts`, `runtime-py/tests/test_touch_refs.py`, `runtime-ts/test/touch-refs.test.mjs`, `tools/conformance/suites/touch-refs.mjs`
- Modify: `runtime-py/src/bantamkit/touch/repo.py` + `.ts` (`ls_files`, `renames`, `head_print`); `runtime-py/src/bantamkit/storage/hotindex.py` (`_parse`, `:870`/`:894`; `INDEX_VERSION` `:82`) + `runtime-ts/src/storage/hotindex.ts`; `tools/conformance/ref/touch_ref.py`; `tools/conformance/suites/storage-index.mjs` (only the version literal, see Step 6)

**Interfaces:**
- Produces:
  - `extract_refs(text: str) -> list[str]`: raw references in first-appearance order, deduped; a `:line` or `:a-b` suffix is dropped, a `#symbol` is kept as `path#symbol`.
  - `fact_refs(description: str, keywords: list[str], body: str) -> list[str]`: `extract_refs` over `description`, each keyword, then `body`, deduped in that order.
  - `FileSet(files: list[str])` with `.files: set[str]` and `.matches(p: str) -> list[str]`: `[p]` when `p` is tracked; else the tracked files `f` that `p` ends with as `".../" + f` (longest first), when any; else the tracked files that end with `"/" + p`, sorted.
  - `resolve_ref(raw: str, fs: FileSet, renames: dict[str, str], top: str) -> tuple[str, str | None] | None`: `(path, symbol)`; `None` when missing or ambiguous.
  - `shortest_suffix(path: str, fs: FileSet) -> str`: the fewest trailing components `s` with `fs.matches(s) == [path]`; the full path when none is shorter.
  - `ls_files(repo) -> list[str] | None` (`git ls-files -z`); `renames(repo) -> dict[str, str] | None` (old → current, from `git log --format= --name-status -M -z --diff-filter=R HEAD`, chains followed up to 32 hops, a rename back to a tracked path ignored); `head_print(repo) -> str` (sha16 of `HEAD`'s bytes, the loose ref it names or `packed-refs`' `mtime_ns:size`, and `<gitdir>/index`'s `mtime_ns:size`; files read directly, a linked worktree's `commondir` followed).
  - `REF_RE` (both runtimes, identical source text):
    `(?<![A-Za-z0-9_./~-])(/?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*)(?::[0-9]+(?:-[0-9]+)?|#([A-Za-z_][A-Za-z0-9_.]*))?`
    A match is a reference only when it holds a `/` or ends in `.<letter>[A-Za-z0-9]{0,7}`. Before matching, every `[a-z][a-z0-9+.-]*://[^ \t\n<>"')]*` span is replaced by spaces of the same length (a URL is never a path).
  - Hot index docs carry `refs = fact_refs(...)` for `"facts"` sources and `extract_refs(description + "\n" + body)` for `"native"` ones; `INDEX_VERSION = 5`.

- [ ] **Step 1: Failing tests (Python; mirror them in Node)**

```python
# runtime-py/tests/test_touch_refs.py
import subprocess
from pathlib import Path

from bantamkit.touch.refs import FileSet, extract_refs, fact_refs, resolve_ref, shortest_suffix
from bantamkit.touch.repo import find_repo, ls_files, renames

FILES = ["runtime-ts/src/memory/store.ts", "runtime-py/src/bantamkit/memory/store.py",
         "a/store.ts", "b/a/store.ts", "docs/memory.md", "Makefile"]


def test_extract_kinds():
    t = ("see runtime-ts/src/memory/store.ts:450 and store.py#recall, docs/memory.md:10-20, "
         "not https://github.com/x/y/blob/main/docs/memory.md nor 0.37.0 nor e.g. this")
    assert extract_refs(t) == ["runtime-ts/src/memory/store.ts", "store.py#recall", "docs/memory.md", "e.g"]


def test_extract_keeps_order_and_dedupes_across_fields():
    assert fact_refs("store.ts first", ["docs/memory.md", "store.ts"], "body names src/Makefile.") == [
        "store.ts", "docs/memory.md", "src/Makefile"]


def test_bare_name_without_extension_is_not_a_ref():
    assert extract_refs("run Makefile then README") == []


def test_resolve_exact_suffix_ambiguous_missing_absolute():
    fs = FileSet(FILES)
    assert resolve_ref("docs/memory.md", fs, {}, "/r") == ("docs/memory.md", None)
    assert resolve_ref("store.py#recall", fs, {}, "/r") == ("runtime-py/src/bantamkit/memory/store.py", "recall")
    assert resolve_ref("store.ts", fs, {}, "/r") is None            # three tracked store.ts
    assert resolve_ref("nope/x.py", fs, {}, "/r") is None
    assert resolve_ref("/r/docs/memory.md", fs, {}, "/r") == ("docs/memory.md", None)
    assert resolve_ref("/elsewhere/bantamkit/docs/memory.md", fs, {}, "/r") == ("docs/memory.md", None)


def test_resolve_follows_renames():
    fs = FileSet(FILES)
    assert resolve_ref("old/memory.md", fs, {"old/memory.md": "docs/memory.md"}, "/r") == ("docs/memory.md", None)


def test_shortest_suffix_round_trips():
    fs = FileSet(FILES)
    assert shortest_suffix("docs/memory.md", fs) == "memory.md"
    assert shortest_suffix("runtime-ts/src/memory/store.ts", fs) == "memory/store.ts"
    assert shortest_suffix("a/store.ts", fs) == "a/store.ts"        # exact match wins over b/a/store.ts
    for f in FILES:
        assert fs.matches(shortest_suffix(f, fs)) == [f]


def test_git_mv_old_path_still_resolves(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    def g(*a): subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (r / "old.py").write_text("x\n"); g("add", "."); g("commit", "-qm", "one")
    g("mv", "old.py", "new.py"); g("commit", "-qm", "two")
    repo = find_repo(str(r))
    fs = FileSet(ls_files(repo))
    assert resolve_ref("old.py", fs, renames(repo), repo.top) == ("new.py", None)
```

Add to `runtime-py/tests/test_storage_hotindex.py`: a fact whose body says `see docs/memory.md:3` and whose keywords hold `store.py#recall` indexes `refs == ["store.py#recall", "docs/memory.md"]`, and a version-4 head on disk is rebuilt (the existing version-bump test pattern in that file: `grep -n "INDEX_VERSION" runtime-py/tests/test_storage_hotindex.py`).

- [ ] **Step 2: Run them and see them fail** (`ModuleNotFoundError: No module named 'bantamkit.touch.refs'`).
- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/touch/refs.py
"""Path references in fact text, resolved against the repo (#200, E4). ASCII classes only: the
two runtimes' regex engines disagree on Unicode classes."""
from __future__ import annotations

import re

REF_RE = re.compile(
    r"(?<![A-Za-z0-9_./~-])(/?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*)"
    r"(?::[0-9]+(?:-[0-9]+)?|#([A-Za-z_][A-Za-z0-9_.]*))?"
)
URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^ \t\n<>\"')]*")
_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
RENAME_HOPS = 32


def _blank(m: re.Match[str]) -> str:
    return " " * len(m.group(0))


def extract_refs(text: str) -> list[str]:
    out: list[str] = []
    for m in REF_RE.finditer(URL_RE.sub(_blank, text)):
        path, sym = m.group(1).rstrip("."), m.group(2)  # a sentence's full stop is not the path's
        if not path or ("/" not in path and not _EXT.search(path)):
            continue
        raw = f"{path}#{sym}" if sym else path
        if raw not in out:
            out.append(raw)
    return out


def fact_refs(description: str, keywords: list[str], body: str) -> list[str]:
    out: list[str] = []
    for text in [description, *keywords, body]:
        for r in extract_refs(text if isinstance(text, str) else str(text)):
            if r not in out:
                out.append(r)
    return out


class FileSet:
    def __init__(self, files: list[str]) -> None:
        self.files = set(files)
        self._sorted = sorted(self.files)

    def matches(self, p: str) -> list[str]:
        if p in self.files:
            return [p]
        deeper = sorted((f for f in self._sorted if p.endswith("/" + f)), key=lambda f: (-len(f), f))
        if deeper:
            return deeper[:1]
        return [f for f in self._sorted if f.endswith("/" + p)]


def resolve_ref(raw: str, fs: FileSet, renames: dict[str, str], top: str) -> tuple[str, str | None] | None:
    path, _, sym = raw.partition("#")
    if path.startswith(top + "/"):
        path = path[len(top) + 1:]
    path = path.rstrip("/")
    if path.startswith("./"):
        path = path[2:]
    for _ in range(RENAME_HOPS):
        found = fs.matches(path)
        if len(found) == 1:
            return found[0], (sym or None)
        if len(found) > 1 or path not in renames:
            return None
        path = renames[path]
    return None


def shortest_suffix(path: str, fs: FileSet) -> str:
    parts = path.split("/")
    for k in range(1, len(parts)):
        s = "/".join(parts[-k:])
        if fs.matches(s) == [path]:
            return s
    return path
```

A bare tracked name with no extension and no `/` (`Makefile`, `README`) is never a reference: matching every capitalised word against `ls-files` would guess. In `repo.py`:

```python
def ls_files(repo: Repo) -> list[str] | None:
    out = git(repo, ["ls-files", "-z"])
    return None if out is None else [p for p in out.split("\0") if p]


def renames(repo: Repo) -> dict[str, str] | None:
    out = git(repo, ["log", "--format=", "--name-status", "-M", "-z", "--diff-filter=R", "HEAD"])
    if out is None:
        return None
    f = [x for x in out.split("\0") if x != ""]
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(f):
        if f[i].startswith("R") and i + 2 < len(f):
            pairs.append((f[i + 1], f[i + 2]))
            i += 3
        else:
            i += 1
    out_map: dict[str, str] = {}
    for old, new in pairs:  # newest first: the first rename seen of a path is its latest
        out_map.setdefault(old, new)
    return out_map


def head_print(repo: Repo) -> str:
    def stat(p: str) -> str:
        try:
            st = os.stat(p)
            return f"{st.st_mtime_ns}:{st.st_size}"
        except OSError:
            return "-"
    def read(p: str) -> str:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                return fh.read().strip()
        except OSError:
            return "-"
    common = repo.gitdir
    cd = read(os.path.join(repo.gitdir, "commondir"))
    if cd != "-":
        common = os.path.realpath(os.path.join(repo.gitdir, cd))
    head = read(os.path.join(repo.gitdir, "HEAD"))
    ref = ""
    if head.startswith("ref: "):
        name = head[5:]
        ref = read(os.path.join(common, *name.split("/")))
        if ref == "-":
            ref = "packed:" + stat(os.path.join(common, "packed-refs"))
    key = "\0".join([head, ref, stat(os.path.join(repo.gitdir, "index"))])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
```

(`repo.py` imports `hashlib`.) Node `renames` is the same loop. The `i + 2 < len(f)` guard is strict on purpose: a cut last record (git killed by the timeout) is skipped, never read past the end.

Hot index (`hotindex.py:870` and `:894`): replace `"refs": []` with `"refs": fact_refs(str(fact.description), [str(k) for k in fact.keywords], str(fact.body))` and, for native, `"refs": extract_refs(f"{stored.description}\n{stored.body}")` (import inside the function, as the module's docstring requires for `bantamkit.memory`). `INDEX_VERSION = 5` with a comment line `# 5 (#200): docs carry their path references in refs; a version-4 head is rebuilt.`

- [ ] **Step 4: Implement (Node)** `refs.ts` with the same regex source text (JS supports lookbehind on Node ≥ 20), `String.prototype.replace` with a function for the URL blanking, the same `FileSet` sort keys (`(-length, code point)`), `repo.ts` additions, and `hotindex.ts` refs + `INDEX_VERSION = 5`.
- [ ] **Step 5: Run the unit tests to see them pass.**
- [ ] **Step 6: Conformance `touch-refs.mjs`.**
  - A corpus of 40 fact texts, each tagged with what it aims at: plain path, `path:line`, `path:a-b`, `path#symbol`, absolute inside and outside the toplevel, a missing path, an ambiguous bare name, a URL holding a path, `0.37.0`, a path next to Thai text (`ไฟล์ store.py`), CRLF, a trailing `/`, a `~/` path, a symbol with dots (`#Memory.recall_outcome`). Compare `extract_refs` and `fact_refs` output.
  - `resolve_ref` over the corpus against the `FILES` fixture plus a renames map with a chain `a → b → c` and a cycle `x → y → x` (resolves to nothing after 32 hops on both sides).
  - A fixture git repo built by the harness once (`git init`, commit, `git mv old.py new.py`, commit, `git mv new.py src/new.py`, commit): compare `ls_files`, `renames`, and `resolve_ref("old.py")` = `src/new.py`.
  - `shortest_suffix` for every fixture file and the round trip `matches(shortest_suffix(f)) == [f]`.
  - `storage-index.mjs`: every case keeps comparing the two sides; the one per-side literal that pins `version: 4` (find it: `grep -n "version" tools/conformance/suites/storage-index.mjs`) becomes `5`, renamed with `#200 refs` in its name; a new fixture fact with a path reference compares the `refs` field of both indexes.
  - Literals per side: `extract_refs` of the `test_extract_kinds` text; `shortest_suffix("runtime-ts/src/memory/store.ts") == "memory/store.ts"`.
  - Mutations: Node drops the URL blanking (red: URL corpus row); Python `\w` in place of `[A-Za-z0-9_]` (red: the Thai-adjacent row, because Python's `\w` takes Thai letters); Node prefers the shallowest deeper match (red: absolute-outside row); symmetric: both keep `:line` in the raw ref (red only on the literal).
- [ ] **Step 7: Run the gates and commit** (`feat(touch): path references in facts, resolved through git renames; shortest unique suffix; index v5 fills refs (#200)`).

---

### Task 3: bash-turn

**Files:**
- Create: `runtime-py/src/bantamkit/touch/bashturn.py`, `runtime-ts/src/touch/bashturn.ts`, `runtime-py/tests/test_touch_bashturn.py`, `runtime-ts/test/touch-bashturn.test.mjs`, `tools/conformance/suites/touch-turn.mjs`
- Modify: `hookadapter.py` (`_user_prompt_submit` `:1206` opens the turn before its short-prompt skip; `run_hook` Stop branch closes it before `_maybe_dream`), `hookadapter.ts` (`userPromptSubmit` `:1327`, `Stop` case); `tools/conformance/ref/touch_ref.py`

**Interfaces:**
- Consumes: `find_repo`, `git`, `TouchLog`, `current_seq` (Task 1).
- Produces:
  - `snapshot(repo: Repo) -> dict[str, list[Any]] | None`: from `git status --porcelain=v1 -z -uall`, each entry `path -> [xy, mtime_ns as decimal string or "-", size or -1]` (the rename form `R  new\0old` keys on `new`); `None` when git fails.
  - `changed(before: dict, after: dict) -> list[str]`: sorted paths whose entry was added, removed, or whose `[xy, mtime_ns, size]` differs.
  - `save_turn(state_dir: str, session: str, snap: dict, seq: int) -> None` to `<state>/ledger-<safe>.turn.json` as `{"seq": seq, "status": snap}` (temp-then-rename); `load_turn(state_dir, session) -> tuple[int, dict] | None`.
  - Hook: `_turn_open(run, payload)` (UserPromptSubmit) and `_turn_close(run, payload)` (Stop). Close: load the turn; take a new snapshot; for each changed path NOT explained by an `edit`/`write` row of this session in `TouchLog.tail(session, turn_seq)`, append `op: "write", via: "bash-turn", from: turn_seq` at `seq = current_seq(...)`; then `save_turn` the new snapshot at the current seq, so a second Stop in one turn records nothing twice.

- [ ] **Step 1: Failing tests**

```python
# runtime-py/tests/test_touch_bashturn.py
import subprocess
from pathlib import Path

from bantamkit.touch.bashturn import changed, load_turn, save_turn, snapshot
from bantamkit.touch.repo import find_repo


def _repo(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    def g(*a): subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (r / "a.txt").write_text("1\n"); (r / "dirty.txt").write_text("1\n"); g("add", "."); g("commit", "-qm", "c")
    (r / "dirty.txt").write_text("2\n")  # dirty before the turn
    return r


def test_diff_sees_new_modified_and_redirtied(tmp_path):
    r = _repo(tmp_path); repo = find_repo(str(r))
    before = snapshot(repo)
    (r / "a.txt").write_text("changed by bash\n")
    (r / "new" ).mkdir(); (r / "new" / "n.txt").write_text("n\n")
    (r / "dirty.txt").write_text("3, longer\n")      # already dirty: only the stat moves
    assert changed(before, snapshot(repo)) == ["a.txt", "dirty.txt", "new/n.txt"]


def test_revert_to_clean_is_a_change(tmp_path):
    r = _repo(tmp_path); repo = find_repo(str(r))
    before = snapshot(repo)
    (r / "dirty.txt").write_text("1\n")
    assert changed(before, snapshot(repo)) == ["dirty.txt"]


def test_turn_round_trip(tmp_path):
    save_turn(str(tmp_path), "s/1", {"a": ["??", "1", 2]}, 7)
    assert load_turn(str(tmp_path), "s/1") == (7, {"a": ["??", "1", 2]})
    assert (tmp_path / "ledger-s_1.turn.json").exists()
```

And a hook test in `test_hookadapter.py`: UserPromptSubmit, then a PostToolUse Edit of `a.txt`, then (outside any tool) `b.txt` written and `a.txt` written again, then Stop → the touch log holds exactly one `bash-turn` line, for `b.txt`, with `from` equal to the seq at UserPromptSubmit (the Edit explains `a.txt`); a second Stop adds nothing.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/touch/bashturn.py
"""Writes made by Bash, once per turn (#200, E5): `git status` at UserPromptSubmit against `git
status` at Stop. A path already dirty before the turn is caught by its stat moving."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .repo import Repo, git

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def snapshot(repo: Repo) -> dict[str, list[Any]] | None:
    out = git(repo, ["status", "--porcelain=v1", "-z", "-uall"])
    if out is None:
        return None
    fields = out.split("\0")
    snap: dict[str, list[Any]] = {}
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if xy[0] in "RC":
            i += 1  # the source path follows; the entry keys on the destination
        try:
            st = os.stat(os.path.join(repo.top, *path.split("/")))
            snap[path] = [xy, str(st.st_mtime_ns), st.st_size]
        except OSError:
            snap[path] = [xy, "-", -1]
    return snap


def changed(before: dict[str, list[Any]], after: dict[str, list[Any]]) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def _turn_path(state_dir: str, session: str) -> str:
    return os.path.join(state_dir, f"ledger-{_UNSAFE.sub('_', session or 'nosession')}.turn.json")


def save_turn(state_dir: str, session: str, snap: dict[str, list[Any]], seq: int) -> None:
    p = _turn_path(state_dir, session)
    os.makedirs(state_dir, exist_ok=True)
    tmp = f"{p}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"seq": seq, "status": snap}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    os.replace(tmp, p)


def load_turn(state_dir: str, session: str) -> tuple[int, dict[str, list[Any]]] | None:
    try:
        with open(_turn_path(state_dir, session), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("seq"), int) or not isinstance(d.get("status"), dict):
        return None
    return d["seq"], d["status"]
```

Hook arms (each wrapped in `try/except Exception` that logs `{"event": ..., "touch": "miss"}`):

```python
def _turn_open(run: HookRun, payload: dict[str, Any]) -> None:
    repo = find_repo(str(payload.get("cwd") or os.getcwd()))
    if repo is None:
        return
    snap = snapshot(repo)
    if snap is not None:
        session = _js_str(payload.get("session_id") or "")
        save_turn(run.state, session, snap, current_seq(run.state, session))


def _turn_close(run: HookRun, payload: dict[str, Any]) -> None:
    repo = find_repo(str(payload.get("cwd") or os.getcwd()))
    if repo is None:
        return
    session = _js_str(payload.get("session_id") or "")
    turn = load_turn(run.state, session)
    if turn is None:
        return
    frm, before = turn
    after = snapshot(repo)
    if after is None:
        return
    log = TouchLog(run.home, repo.id)
    explained = {r["path"] for r in log.tail(session, frm) if r.get("op") in ("edit", "write")}
    seq = current_seq(run.state, session)
    for p in changed(before, after):
        if p not in explained:
            log.append_touch(session, seq, "write", p, via="bash-turn", frm=frm)
    save_turn(run.state, session, after, seq)
```

`_turn_open` is the first statement of `_user_prompt_submit`, before the `PROMPT_MIN_CHARS` / `/command` skip (a slash command's turn can still run Bash). `_turn_close` runs in the Stop branch of `run_hook` before `_maybe_dream`, also when `stop_hook_active` is set (the save nudge's continuation is part of the same turn, and the re-saved snapshot prevents a double count).

Before committing, check nothing else globs the hook state as ledgers: `grep -rn "ledger-" runtime-py/src runtime-ts/src`. The only reader by pattern is Retention's 7-day `_LEDGER` rule, which is the pruning these files want.

- [ ] **Step 4: Implement (Node)** with the same names; `fs.statSync(p, {bigint: true}).mtimeNs.toString()` for the nanosecond string (Python's `st_mtime_ns`), `Number(st.size)`; `JSON.stringify` of an object whose keys are inserted in sorted order (build the `status` map from `Object.keys(snap).sort()`), so the turn file bytes match Python's `sort_keys=True` output.
- [ ] **Step 5: Run the unit tests to see them pass.**
- [ ] **Step 6: Conformance `touch-turn.mjs`.**
  - Module: `snapshot` → `changed` over a harness-built repo (staged, unstaged, untracked in a new dir, a rename, a deletion, a file dirty before and touched again, a revert to clean); compare the changed lists and the `.turn.json` bytes with every `mtime_ns` masked to `<ns>`.
  - Hook: the Step 1 hook scenario on both sides, comparing touch-log bytes (ts masked).
  - Literals per side: the Step 1 changed list `["a.txt","dirty.txt","new/n.txt"]`; the hook's single bash-turn line.
  - Mutations: Node keys a rename on the source path (red: rename row); Python double-counts an Edit (drops the `explained` filter) (red: hook bytes); Node does not re-save the snapshot at Stop (red: second-Stop bytes); symmetric: both ignore the stat for an already-dirty path (red only on the literal).
- [ ] **Step 7: Latency.** `node tools/eval/recall/bench_touch.mjs after runtime-ts/dist/cli.js --git $PWD` → record the `git-status` and `Stop` p50 in the unit note. Expected: `git-status` p50 ≤ 30 ms on this repo; if not, re-run with the load average noted, and if it is still over, report it (the bar is gated in Task 8, not here).
- [ ] **Step 8: Run the gates and commit** (`feat(touch): writes made by Bash captured once per turn from two git status snapshots (#200)`).

---

### Task 4: The graph index

**Files:**
- Create: `runtime-py/src/bantamkit/touch/graph.py`, `runtime-ts/src/touch/graph.ts`, `runtime-py/tests/test_touch_graph.py`, `runtime-ts/test/touch-graph.test.mjs`, `tools/conformance/suites/touch-graph.mjs`
- Modify: `tools/conformance/ref/touch_ref.py`

**Interfaces:**
- Consumes: `Repo`, `ls_files`, `renames`, `head_print` (Task 2), `FileSet`, `resolve_ref` (Task 2), `TouchLog.read` (Task 1); each layer's `store.index()` (`MemoryStore.index`, `runtime-py/src/bantamkit/memory/store.py:775`; `NativeStore.index`, `native.py:59`) `.docs()` → `{name: {"refs": [...], ...}}`.
- Produces:
  - `GRAPH_VERSION = 1`, `WEAK_SPAN = 20`, `WEAK_TS_MAX = 32`.
  - `build_strong(layer_refs: list[dict[str, list[str]]], fs: FileSet, renames: dict[str, str], top: str) -> dict[str, list[list[Any]]]`: `path -> [[fact, symbol|None], ...]`, facts in first-layer-first then name order, one entry per (fact, symbol).
  - `build_weak(rows: list[dict]) -> dict[str, dict[str, list[str]]]`: `path -> fact -> [ts...]` (newest `WEAK_TS_MAX`, ascending). A pair is counted for a `use` row and a touch row of the same session when `abs(use.seq - touch.seq) <= WEAK_SPAN`, or, for a `bash-turn` touch, when `from < use.seq <= seq`; the timestamp kept is the use's.
  - `TouchGraph(home: Path, repo: Repo)`: `.path = home/.bantamkit/graph/<repo.id>.json`; `.load(layers: list[tuple[str, Any]]) -> dict | None` returns `{"version", "strong_print", "weak_print", "files", "strong", "weak"}`, rebuilding a half only when its print moved, writing temp-then-rename under `exclusive(path)`; any failure returns `None` and the caller treats it as "no graph".
  - `strong_print = sha16(json([GRAPH_VERSION, head_print(repo), [index head print per layer]]))` where a layer's print is its index head's `shards` map dumped (`hotindex.dumps`), `"-"` when unreadable; `weak_print = f"{size of the touch log live file}:{count of its .gz segments}"`.
  - File bytes: `hotindex.dumps` of the dict (sorted keys, compact separators, `ensure_ascii=False`), so both runtimes write the same file.

- [ ] **Step 1: Failing tests**

```python
# runtime-py/tests/test_touch_graph.py
from bantamkit.touch.graph import build_strong, build_weak
from bantamkit.touch.refs import FileSet

FS = FileSet(["src/a.py", "src/b.py", "docs/x.md"])


def test_strong_edges_first_layer_first_then_name():
    layers = [{"zeta": ["a.py#run"], "alpha": ["src/a.py", "missing.py"]}, {"alpha": ["docs/x.md"]}]
    assert build_strong(layers, FS, {}, "/r") == {
        "src/a.py": [["alpha", None], ["zeta", "run"]],
        "docs/x.md": [["alpha", None]],
    }


def _t(seq, path, session="s", **kw):
    return {"ts": f"2026-10-16T00:00:{seq:02d}Z", "session": session, "seq": seq, "op": "edit", "path": path, **kw}


def _u(seq, fact, session="s"):
    return {"ts": f"2026-10-16T00:00:{seq:02d}Z", "session": session, "seq": seq, "op": "use", "fact": fact, "kind": "recall_hit"}


def test_weak_window_is_plus_minus_twenty_same_session():
    rows = [_t(1, "src/a.py"), _u(21, "f"), _u(22, "g"), _u(5, "h", session="other")]
    assert build_weak(rows) == {"src/a.py": {"f": ["2026-10-16T00:00:21Z"]}}


def test_weak_bash_turn_counts_the_turn():
    rows = [_u(3, "f"), _u(9, "g"), _t(9, "b.txt", op="write", via="bash-turn", **{"from": 3})]
    assert build_weak(rows) == {"b.txt": {"g": ["2026-10-16T00:00:09Z"]}}
```

Plus `TouchGraph.load` tests over a real temp repo and a `MemoryStore` with one fact naming `src/a.py`: the first load writes the file; a second load with nothing changed does not rewrite it (compare `mtime_ns`); appending a touch line rebuilds `weak` only (assert `ls_files` is not called, by monkeypatching `bantamkit.touch.graph.ls_files` to raise after the first load); a commit moves `strong_print`; a corrupt graph file is rebuilt; a store that raises from `docs()` makes `load` return `None`.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/touch/graph.py
"""The touch graph (#200): file -> facts, a #204 derived index. Delete it and the next load rebuilds it."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import hashlib

from bantamkit.storage.hotindex import dumps
from bantamkit.storage.lock import exclusive

from .log import TouchLog
from .refs import FileSet, resolve_ref
from .repo import Repo, head_print, ls_files, renames

GRAPH_VERSION = 1
WEAK_SPAN = 20
WEAK_TS_MAX = 32


def build_strong(layer_refs: list[dict[str, list[str]]], fs: FileSet, ren: dict[str, str],
                 top: str) -> dict[str, list[list[Any]]]:
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


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def build_weak(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    by_session: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for r in rows:
        s, seq = r.get("session"), _int(r.get("seq"))
        if not isinstance(s, str) or seq is None or not isinstance(r.get("ts"), str):
            continue
        touches, uses = by_session.setdefault(s, ([], []))
        if r.get("op") == "use" and isinstance(r.get("fact"), str):
            uses.append(r)
        elif r.get("op") in ("read", "edit", "write") and isinstance(r.get("path"), str):
            touches.append(r)
    out: dict[str, dict[str, list[str]]] = {}
    for touches, uses in by_session.values():
        for t in touches:
            frm = _int(t.get("from"))
            for u in uses:
                if t.get("via") == "bash-turn" and frm is not None:
                    hit = frm < u["seq"] <= t["seq"]
                else:
                    hit = abs(u["seq"] - t["seq"]) <= WEAK_SPAN
                if hit:
                    out.setdefault(t["path"], {}).setdefault(u["fact"], []).append(u["ts"])
    for facts in out.values():
        for f in facts:
            facts[f] = sorted(set(facts[f]))[-WEAK_TS_MAX:]
    return out


class TouchGraph:
    def __init__(self, home: Path | str, repo: Repo) -> None:
        self.home = Path(home)
        self.repo = repo
        self.path = self.home / ".bantamkit" / "graph" / f"{repo.id}.json"
        self.log = TouchLog(self.home, repo.id)

    def _weak_print(self) -> str:
        try:
            size = os.stat(self.log.path).st_size
        except OSError:
            size = -1
        return f"{size}:{len(self.log._seg().segments())}"

    def _strong_print(self, layers: list[tuple[str, Any]]) -> str:
        prints = []
        for _, store in layers:
            try:
                idx = store.index()
                idx.refresh("fast")
                prints.append(dumps(idx._loaded().get("shards")))
            except Exception:  # noqa: BLE001 - an unreadable layer prints as "-"
                prints.append("-")
        return sha16_text(json.dumps([GRAPH_VERSION, head_print(self.repo), prints]))

    def load(self, layers: list[tuple[str, Any]]) -> dict[str, Any] | None:
        try:
            old = self._read()
            sp, wp = self._strong_print(layers), self._weak_print()
            if old and old["strong_print"] == sp and old["weak_print"] == wp:
                return old
            data = dict(old) if old else {"version": GRAPH_VERSION, "files": [], "strong": {}, "weak": {},
                                          "strong_print": "", "weak_print": ""}
            if data["strong_print"] != sp:
                files = ls_files(self.repo)
                ren = renames(self.repo)
                if files is None or ren is None:
                    return None
                refs = [{n: list(d.get("refs") or []) for n, d in store.index().docs().items()} for _, store in layers]
                data.update(files=files, strong=build_strong(refs, FileSet(files), ren, self.repo.top), strong_print=sp)
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
        keys = {"version", "strong_print", "weak_print", "files", "strong", "weak"}
        return d if isinstance(d, dict) and set(d) == keys and d["version"] == GRAPH_VERSION else None

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(self.path):
            tmp = f"{self.path}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(dumps(data) + "\n")
            os.replace(tmp, self.path)


def sha16_text(text: str) -> str:
    """sha16 of a STRING (`hotindex.sha16` hashes a realpath, so it cannot be reused here)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
```

Before relying on `idx._loaded().get("shards")`, read `HotIndex._loaded` (`hotindex.py:453`) and use the public accessor if one returns the head's `shards` map; if none does, add `HotIndex.head_print() -> str` (dumps of `shards`) in both runtimes in this task, with a unit test per side, and call that instead.

A layer whose `docs()` raises fails the strong rebuild, and `load` returns `None` (spec: graph build fails → `w_context` 0). A read-only layer that is merely missing contributes `{}`: wrap each layer's `docs()` in its own `try` that yields `{}` for a non-writable layer and re-raises for the writable one, mirroring `_pooled` (`component.py:653-660`).

- [ ] **Step 4: Implement (Node)** `graph.ts` with the same names, `dumpIndex` (the `hotindex.ts` export) for the bytes, `exclusive` for the write, `fs.renameSync` for temp-then-rename.
- [ ] **Step 5: Run the unit tests to see them pass.**
- [ ] **Step 6: Conformance `touch-graph.mjs`.**
  - `build_strong` and `build_weak` over fixture scripts: a fact named in two layers, a symbol edge, the ±20 boundary (`seq` 20 apart: an edge; 21 apart: none), two sessions, a bash-turn with `from`, a use at `seq == from` (not in the turn), duplicate timestamps, 40 uses of one pair (`WEAK_TS_MAX` cut).
  - `TouchGraph.load` over a harness-built repo + a store with three facts: compare the graph file bytes after the first load, after a touch line (only `weak`/`weak_print` move), after a commit (`strong_print` moves). `ts` values are fixed by the script; prints are masked to `<print>` because they include `mtime_ns`.
  - Literals per side: `build_strong` of the Step 1 fixture; the boundary pair `[edge at 20, no edge at 21]`.
  - Mutations: Node `<` for `<=` on `WEAK_SPAN` (red: boundary); Python lets a use at `seq == from` into a bash-turn (red); Node rebuilds strong on every weak change (red: a per-side probe counting `lsFiles` calls through a `touch_ref`/Node hook counter, `{"op":"load_twice_count_ls"}` → `1`); symmetric: both `WEAK_SPAN = 19` (red only on the boundary literal).
- [ ] **Step 7: Run the gates and commit** (`feat(touch): the touch graph, a derived index with a git half and a touch-log half (#200)`).

---

### Task 5: `w_context` in the ranker and the via admission path

**Files:**
- Create: `runtime-py/src/bantamkit/touch/context.py`, `runtime-ts/src/touch/context.ts`, `runtime-py/tests/test_touch_context.py`, `runtime-ts/test/touch-context.test.mjs`, `tools/conformance/suites/touch-context.mjs`
- Modify: `runtime-py/src/bantamkit/memory/retrieval.py` (`weight_of` `:310`, `weight` `:305`, `rank`), `runtime-ts/src/memory/retrieval.ts` (`weightOf` `:358`); `runtime-py/src/bantamkit/memory/store.py` (`Pool.weights` `:423`, `pooled_ranking` `:527`, `pick_hits` `:578`), `runtime-ts/src/memory/store.ts` (`poolWeights` `:584`, `pooledRanking` `:653`, `pickHits` `:708`); `runtime-py/src/bantamkit/memory/component.py` (`RecallOutcome` `:65`, `recall_outcome` `:506`, `_pooled` `:623`), `runtime-ts/src/memory/component.ts` (`recallOutcome` `:605`); `hookadapter.py` (`_user_prompt_submit` `:1206`), `hookadapter.ts` (`userPromptSubmit` `:1327`)

**Interfaces:**
- Consumes: `TouchGraph.load` (Task 4), `TouchLog.tail`, `current_seq` (Task 1), `shortest_suffix`, `FileSet` (Task 2), `USAGE_HALF_LIFE_DAYS` (`memory/usage.py:49`).
- Produces:
  - `retrieval.weight_of(type_: str, is_stale: bool, u: float, ctx: float = 0.0) -> float`: the existing sum with `W_CONTEXT * ctx` in place of `W_CONTEXT * 0.0`; `ctx` clamped into `[0, 1]`, a NaN is 0. `W_CONTEXT` stays `0.0` here (Task 8 sets it); every existing call site is unchanged because `ctx` defaults to 0.
  - `Pool.weights(usage, context: Mapping[str, float] | None = None)`: rows whose name has `context[name] > 0` are re-weighed with it, after the usage pass, by the same bisect walk.
  - `pooled_ranking(..., context=None)`, `pick_hits(..., context=None)` pass it through. Node: `poolWeights(p, usage, context?)`, `pooledRanking(..., context?)`, `pickHits(..., context?)`.
  - `touch.context`: `TOUCH_WINDOW = 20`, `CONTEXT_WEAK_SHARE = 0.5`, `VIA_MAX = 1`, `VIA_ON = False`.
    - `TouchContext(weights: dict[str, float], strong_window: list[str], graph: dict | None)`, frozen.
    - `window(rows: list[dict], seq: int) -> list[str]`: paths of this session's `read`/`edit`/`write` rows with `seq > seq_now - TOUCH_WINDOW`, most recent first, deduped.
    - `context_weights(graph: dict, paths: list[str], now: str) -> dict[str, float]`: a fact with a strong edge to a window path weighs `1.0`; otherwise `min(1.0, CONTEXT_WEAK_SHARE * Σ_paths Σ_ts 0.5 ** (age_days / USAGE_HALF_LIFE_DAYS))` over its weak edges; rounded to 9 places.
    - `via_pick(graph: dict, paths: list[str], exclude: set[str], weigh: Callable[[str], float | None]) -> tuple[str, str] | None`: walk `paths` (most recent first); for the first path with a strong-edge fact not in `exclude` for which `weigh(fact)` is not `None`, pick the fact with the highest `weigh`, ties by name; return `(fact, path)`. Weak edges never admit.
    - `via_label(path: str, graph: dict) -> str`: `f" [via {shortest_suffix(path, FileSet(graph['files']))}]"`.
    - `VIA_ENV = "BANTAMKIT_VIA"`; `via_enabled() -> bool`: the env value `on` → True, `off` → False, anything else (unset included) → `VIA_ON`. An operator switch, documented in `docs/touch.md`, read on every call (so a test can set it), the same on both runtimes; the conformance hook cases use it to exercise the path while `VIA_ON` is False.
  - `Memory.recall_outcome(..., context: TouchContext | None = None)`: `context.weights` goes to `pick_hits`; when `VIA_ON` and `context.graph` and fewer than `VIA_MAX` via lines so far, `via_pick` over `context.strong_window` with `exclude` = the picked names and `weigh = lambda n: retrieval weight of the fact found by name across the layers (None when no layer holds it)`; the via fact's header is the ordinary `_header(label, fact)` + `via_label`, appended after the gated headers; its formatted entry likewise after the gated entries in `reply`. `RecallOutcome.via: str | None` names the via fact. A via fact is never stamped, repaired or counted as usage (the hook passes `stamp=False`; the tool path never passes `context`).
  - Hook: `_touch_context(run, payload, m: Memory) -> TouchContext | None`, called by `_user_prompt_submit` and passed as `context=`; every error is `None`. The hook log record gains `"via": <name>` when a via line was injected and `"context": <number of facts with ctx > 0>`.

- [ ] **Step 1: Failing tests (Python; mirror them in Node)**

```python
# runtime-py/tests/test_touch_context.py
import pytest

from bantamkit.memory import retrieval
from bantamkit.memory.retrieval import weight_of
from bantamkit.touch import context as tc

G = {"files": ["src/a.py", "src/b.py", "docs/x.md"],
     "strong": {"src/a.py": [["fa", None], ["fb", None]], "docs/x.md": [["fx", None]]},
     "weak": {"src/b.py": {"fw": ["2026-10-16T00:00:00Z", "2026-10-02T00:00:00Z"]}}}


def _row(seq, path, op="edit"):
    return {"ts": "2026-10-16T00:00:00Z", "session": "s", "seq": seq, "op": op, "path": path}


def test_ctx_defaults_to_zero_and_is_clamped(monkeypatch):
    monkeypatch.setattr(retrieval, "W_CONTEXT", 0.5)
    assert weight_of("project", False, 0.0) == pytest.approx(1.1)
    assert weight_of("project", False, 0.0, 1.0) == pytest.approx(1.6)
    assert weight_of("project", False, 0.0, 7.0) == pytest.approx(1.6)


def test_window_is_last_twenty_calls_most_recent_first():
    rows = [_row(1, "docs/x.md"), _row(25, "src/a.py"), _row(30, "src/b.py", "read"), _row(31, "src/a.py")]
    assert tc.window(rows, 31) == ["src/a.py", "src/b.py"]          # seq 1 is outside 31-20


def test_context_weights_strong_full_weak_partial():
    w = tc.context_weights(G, ["src/a.py", "src/b.py"], "2026-10-16T00:00:00Z")
    assert w["fa"] == 1.0 and w["fb"] == 1.0
    assert w["fw"] == pytest.approx(round(0.5 * (1.0 + 0.5), 9))
    assert "fx" not in w


def test_via_strong_only_window_only_one_fact():
    weigh = {"fa": 1.1, "fb": 1.3, "fw": 9.0, "fx": 9.0}.get
    assert tc.via_pick(G, ["src/b.py", "src/a.py"], set(), weigh) == ("fb", "src/a.py")   # fw is weak: never
    assert tc.via_pick(G, ["src/a.py"], {"fb"}, weigh) == ("fa", "src/a.py")
    assert tc.via_pick(G, [], set(), weigh) is None                                     # docs/x.md not in window


def test_via_label_uses_shortest_suffix():
    assert tc.via_label("src/a.py", G) == " [via a.py]"


def test_via_switch(monkeypatch):
    monkeypatch.delenv("BANTAMKIT_VIA", raising=False)
    assert tc.via_enabled() is tc.VIA_ON
    monkeypatch.setenv("BANTAMKIT_VIA", "on"); assert tc.via_enabled() is True
    monkeypatch.setenv("BANTAMKIT_VIA", "off"); monkeypatch.setattr(tc, "VIA_ON", True); assert tc.via_enabled() is False
    monkeypatch.setenv("BANTAMKIT_VIA", "yes"); assert tc.via_enabled() is True   # not on/off: the default
```

And in `runtime-py/tests/test_hookadapter.py`, with `monkeypatch.setenv("BANTAMKIT_VIA", "on")` (and once with `monkeypatch.setattr("bantamkit.touch.context.VIA_ON", True)` and the env unset, so both switches are covered), a git bed whose store holds `fa` ("notes about src/a.py", a description the prompt does not match) and `gate-fact` (matches the prompt): after a PostToolUse Edit of `src/a.py`, a UserPromptSubmit injects `gate-fact`'s header and then `[project] [fa] (project) notes about src/a.py [via a.py]`, exactly once; with the env `off` the via line is absent even when `VIA_ON` is patched True; with the Edit 21 calls back (21 Bash PostToolUse calls between) it is absent; and the fact file bytes are unchanged and no usage ledger line is written (`#199`'s "the hook writes nothing").

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/touch/context.py
"""What the session touched, as ranking context (#200, E1-A and E3)."""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bantamkit.memory.usage import USAGE_HALF_LIFE_DAYS, _parse

from .refs import FileSet, shortest_suffix

TOUCH_WINDOW = 20
CONTEXT_WEAK_SHARE = 0.5
VIA_MAX = 1
VIA_ON = False  # Task 8 sets this from gold pass 2 (bar: via precision >= 0.8)
VIA_ENV = "BANTAMKIT_VIA"


@dataclass(frozen=True)
class TouchContext:
    weights: dict[str, float]
    strong_window: list[str]
    graph: dict[str, Any] | None


def window(rows: list[dict[str, Any]], seq_now: int) -> list[str]:
    out: list[str] = []
    for r in sorted(rows, key=lambda r: -r["seq"]):
        if r.get("op") in ("read", "edit", "write") and r["seq"] > seq_now - TOUCH_WINDOW:
            if r["path"] not in out:
                out.append(r["path"])
    return out


def context_weights(graph: dict[str, Any], paths: list[str], now: str) -> dict[str, float]:
    t_now = _parse(now)
    out: dict[str, float] = {}
    for p in paths:
        for fact, _sym in graph["strong"].get(p, []):
            out[fact] = 1.0
    weak: dict[str, float] = {}
    for p in paths:
        for fact, stamps in graph["weak"].get(p, {}).items():
            for ts in stamps:
                age = max(0.0, (t_now - _parse(ts)) / 86400.0)
                weak[fact] = weak.get(fact, 0.0) + 0.5 ** (age / USAGE_HALF_LIFE_DAYS)
    for fact, w in weak.items():
        if fact not in out:
            out[fact] = round(min(1.0, CONTEXT_WEAK_SHARE * w), 9)
    return out


def via_pick(graph: dict[str, Any], paths: list[str], exclude: set[str],
             weigh: Callable[[str], float | None]) -> tuple[str, str] | None:
    for p in paths:
        best: tuple[float, str] | None = None
        for fact, _sym in graph["strong"].get(p, []):
            if fact in exclude:
                continue
            w = weigh(fact)
            if w is None:
                continue
            if best is None or (-w, fact) < (-best[0], best[1]):
                best = (w, fact)
        if best is not None:
            return best[1], p
    return None


def via_label(path: str, graph: dict[str, Any]) -> str:
    return f" [via {shortest_suffix(path, FileSet(graph['files']))}]"


def via_enabled() -> bool:
    v = os.environ.get(VIA_ENV)
    return True if v == "on" else False if v == "off" else VIA_ON
```

(`_parse` is `usage.py:72`; import it under that name, or promote it to `parse_ts` in both runtimes if the reviewer of Task 1 asked for no private imports.)

`retrieval.py`:

```python
def weight(c: Candidate, usage: Mapping[str, float], context: Mapping[str, float] | None = None) -> float:
    return weight_of(c.type, stale(c.description), usage.get(c.name, 0.0), (context or {}).get(c.name, 0.0))


def weight_of(type_: str, is_stale: bool, u: float, ctx: float = 0.0) -> float:
    u = u if u > 0.0 else 0.0
    ctx = 0.0 if not (ctx > 0.0) else (1.0 if ctx > 1.0 else ctx)  # NaN and negatives are no context
    w = (
        W_TYPE.get(type_, W_TYPE_OTHER)
        + (W_FRESH_DEMOTE if is_stale else 0.0)
        + W_USAGE * math.log1p(u)
        + W_CONTEXT * ctx
    )
    return w if w > W_FLOOR else W_FLOOR
```

`rank(..., context=None)` passes `context` into `weight`. `Pool.weights(self, usage, context=None)`: after the existing usage loop, for each `name, c` in `(context or {}).items()` with `c > 0`, bisect the name's rows and set `out[i] = weight_of(type, i in stale_ids, usage.get(name, 0.0), c)`. `pooled_ranking(pools, q, ratio, usage, context=None)` calls `p.weights(used, context)`; `pick_hits(..., dedupe=False, context=None)` passes it.

`component.py`: `RecallOutcome` gains `via: str | None = None` (last field, default, so every constructor call stays valid). `recall_outcome(..., context=None)` → `_pooled(query, budget, min_ratio, context)` → `pick_hits(..., context=context.weights if context else None)`. After `picked`:

```python
via_entry = None
if context is not None and context.graph is not None and _touch_context_mod.via_enabled():
    names = {fact.name for _, fact in picked}
    found: dict[str, tuple[str, Fact]] = {}

    def weigh(n: str) -> float | None:
        for label, store, _w in self._layers:
            try:
                f = store.lookup(n, stamp=False)
            except (BantamError, OSError, UnicodeDecodeError):
                f = None
            if f is not None:
                found[n] = (label, f)
                return weight_of(str(f.type), stale(str(f.description)), 0.0, 1.0)
        return None

    pick = via_pick(context.graph, context.strong_window, names, weigh)
    if pick is not None:
        via_entry = (*found[pick[0]], via_label(pick[1], context.graph))
```

Read the real `lookup` signature first (`store.py:1427`; Node `lookup` in `store.ts`) and pass exactly what a non-stamping lookup needs; the native layer's `lookup` too (`native.py`). The via entry's header is `self._header(label, fact) + suffix`, its formatted entry `self._header(label, fact) + suffix + "\n" + fact.body`; both go after the gated ones, and `counts["returned"]` counts it. With no gated hit and a via pick, the outcome is `answered` with the via entry alone. Import `bantamkit.touch.context` as a module (`_touch_context_mod`) so a test's `monkeypatch.setattr(..., "VIA_ON", True)` is seen.

Hook (`hookadapter.py`):

```python
def _touch_context(run: HookRun, payload: dict[str, Any], m: Memory) -> TouchContext | None:
    try:
        repo = find_repo(str(payload.get("cwd") or os.getcwd()))
        if repo is None:
            return None
        session = _js_str(payload.get("session_id") or "")
        seq = current_seq(run.state, session)
        rows = TouchLog(run.home, repo.id).tail(session, seq - TOUCH_WINDOW)
        paths = window(rows, seq)
        if not paths:
            return None
        graph = TouchGraph(run.home, repo).load([(label, store) for label, store, _ in m._layers])
        if graph is None:
            return None
        return TouchContext(context_weights(graph, paths, _stamp()), paths, graph)
    except Exception:  # noqa: BLE001 - no context is the enhancement's only failure mode
        return None
```

`_user_prompt_submit` calls `m.recall_outcome(prompt, 3, stamp=False, context=_touch_context(run, payload, m))`. `_stamp()` is the hook's own ISO second (`hookadapter.py:203`); check it produces `YYYY-MM-DDTHH:MM:SSZ` (the usage ledger's `_TS`) and, if it carries milliseconds, format `now` with `utc_now()` (`store.py`) instead. `_score_header` strips a trailing ` [via …]` before scoring, so the logged score is the fact's own.

- [ ] **Step 4: Implement (Node)**, the same names in camelCase. `W_CONTEXT` becomes `export let W_CONTEXT = 0.0` with `export function setContextWeight(x: number): void` (an ES module importer cannot assign an imported binding; Python's tests and eval assign `retrieval.W_CONTEXT` directly). `recallOutcome(query, k, minRatio, stamp, includeArchived, context?)` takes `context` as the sixth positional parameter (the existing five are positional, `component.ts:605`). `weightOf(type, isStale, usage, ctx = 0.0)`.
- [ ] **Step 5: Run the unit tests, then `--all`.** Expected: every existing `recall-*`, `store` and `hooks` case stays green, because `W_CONTEXT = 0.0`, `VIA_ON = False` and no existing bed has a touch log. A red here is a bug in the threading; investigate, do not update a case.
- [ ] **Step 6: Conformance `touch-context.mjs`.**
  - Module: `window`, `context_weights`, `via_pick`, `via_label` over fixture graphs (the boundary `seq_now - 20`, a fact with both a strong and a weak edge (strong wins, 1.0), decay at 0/14/28 days, a cap at 1.0 with many weak stamps, an `exclude` that empties the first path so the second path answers, ties by name).
  - `weight_of` with `ctx ∈ {0, 0.5, 1, 7, -1, NaN}` at `W_CONTEXT = 0.5`, passed through a `touch_ref` override op (the ref assigns `retrieval.W_CONTEXT` in-process; the Node side calls `setContextWeight` from Step 4).
  - Hook, two processes over one git bed (as Task 1's hook cases), with `BANTAMKIT_VIA=on` in the hook's env (the operator switch from Step 3). Compare the UserPromptSubmit stdout bytes for: a strong edge in the window (via line injected), the same edge 21 calls back (none), only a weak edge (none), two strong facts (one line), a via fact already injected earlier in the session (suppressed by the existing seen-set), no git (stdout as before #200).
  - Literals per side: the via line bytes `[project] [fa] (project) notes about src/a.py [via a.py]`; `via_pick` of the Step 1 fixture `["fb","src/a.py"]`.
  - Mutations: Node lets a weak edge admit (red: weak-only bed); Python admits two via facts (red: two-strong bed); Node ignores the 20-call window (red: 21-calls bed); Python drops the `[via …]` suffix (red: stdout); symmetric: both prefix the label instead of suffixing (red only on the literal, and on both sides' stdout cases being empty, since `RECALL_HEADER` stops matching — record which in the note).
- [ ] **Step 7: Hook latency.** `node tools/eval/recall/bench_touch.mjs after runtime-ts/dist/cli.js --git $PWD`. Record UserPromptSubmit p50 before/after in the note (not gated by #200's bar; #199's ≤ 5 ms UserPromptSubmit rise applies to #199 only, so report the number and, if the snapshot + graph load add more than 5 ms, say so in the note for the reviewer).
- [ ] **Step 8: Run the gates and commit** (`feat(touch): w_context ranks by what the session touched; one [via <file>] fact past the gate, off until gold (#200)`).

---

### Task 6: The B summaries

**Files:**
- Create: `runtime-py/src/bantamkit/touch/summary.py`, `runtime-ts/src/touch/summary.ts`, `runtime-py/tests/test_touch_summary.py`, `runtime-ts/test/touch-summary.test.mjs`, `tools/conformance/suites/touch-summary.mjs`
- Modify: `hookadapter.py` (`_session_start` `:989`), `hookadapter.ts` (`sessionStart` `:1108`)

**Interfaces:**
- Consumes: `TouchLog.read`, `find_repo`, `git`, `ls_files` (Tasks 1–2), `FileSet`, `shortest_suffix`.
- Produces:
  - `SUMMARY_MAX = 600`, `SUMMARY_COMMIT_GRACE_S = 1800`, `SUMMARY_FILES = 3`, `SUMMARY_COMMITS = 3`, `SUMMARY_SUBJECT_MAX = 60`, `COMPACT_FILES = 10`.
  - `age_text(seconds: float) -> str`: `<1 min` → `"just now"`; `< 3600` → `f"{m} min ago"`; `< 172800` → `f"{h} h ago"`; else `f"{d} d ago"` (floors).
  - `previous_session(rows: list[dict], current: str) -> tuple[str, list[dict]] | None`: the session other than `current` (and not `""`, the folded rows) whose latest touch `ts` is greatest, with its touch rows.
  - `last_session_line(rows, now: str, display: Callable[[str], str], commits: list[str], uncommitted: int) -> str`: from one session's touch rows; `""` when it edited nothing and `commits` is empty.
    Shape: `[bantamkit touch] last session here ({YYYY-MM-DD}, {age}): edited {n} file(s) — {a}, {b}, {c} (+{n-3}); commits: {s1}; {s2}; {s3} (+{m-3}); uncommitted: {u} file(s)`. "edited" counts distinct paths with `op` `edit` or `write` (bash-turn included), listed most-recently-touched first, each through `display` (the shortest unique suffix); the `(+k)` parts appear only when `k > 0`; `; commits: …` only when there are commits, each subject cut by `_cap_bytes(subject, SUMMARY_SUBJECT_MAX)`; `; uncommitted: …` only when `u > 0`; with zero edits the `edited …` part reads `edited no files`. The whole line through `_cap_bytes(line, SUMMARY_MAX)`.
  - `compact_line(rows, session: str, display) -> str`: `[bantamkit touch] edited in this session before compaction: {a}, {b}, … (+k)`, at most `COMPACT_FILES` names, `""` when none; capped at `SUMMARY_MAX`.
  - Hook: `_touch_summary(run, payload) -> str` builds the inputs (`git log --format=%s --since=<first ts> --until=<last ts + grace> HEAD` newest first; `git status --porcelain=v1 -z -uall` count) and returns the line; SessionStart appends it as its own part just before the "Toolbox is live" part when non-empty, for `source == "compact"` the `compact_line` of this session instead. Its bytes do not count against `SESSION_INJECT_MAX`'s 3000 bytes (separate block, spec). The SessionStart log record gains `"touchBytes": <bytes>`.

- [ ] **Step 1: Failing tests**

```python
# runtime-py/tests/test_touch_summary.py
from bantamkit.touch.summary import age_text, compact_line, last_session_line, previous_session


def _r(seq, path, op="edit", session="old", ts=None, **kw):
    return {"ts": ts or f"2026-10-15T10:00:{seq:02d}Z", "session": session, "seq": seq, "op": op, "path": path, **kw}


ROWS = [_r(1, "src/store.ts"), _r(2, "src/retrieval.ts", "read"), _r(3, "src/retrieval.ts"),
        _r(4, "src/factfile.ts", "write"), _r(5, "x.txt", "write", via="bash-turn", **{"from": 4}),
        _r(6, "y.txt"), _r(7, "now.py", session="current", ts="2026-10-15T13:00:00Z")]


def test_age_text():
    assert [age_text(s) for s in (5, 120, 3 * 3600, 3 * 86400)] == ["just now", "2 min ago", "3 h ago", "3 d ago"]


def test_previous_session_skips_current_and_folded():
    rows = ROWS + [{"ts": "2026-10-16T00:00:00Z", "session": "", "seq": 0, "op": "folded", "path": "p", "n": 3}]
    sid, mine = previous_session(rows, "current")
    assert sid == "old" and len(mine) == 6


def test_line_shape_and_silence():
    _, mine = previous_session(ROWS, "current")
    line = last_session_line(mine, "2026-10-15T13:00:06Z", lambda p: p.split("/")[-1],
                             ["feat: one (#199)", "fix: two"], 4)
    assert line == ("[bantamkit touch] last session here (2026-10-15, 3 h ago): edited 5 files — "
                    "y.txt, x.txt, factfile.ts (+2); commits: feat: one (#199); fix: two; uncommitted: 4 files")
    reads_only = [_r(1, "a", "read")]
    assert last_session_line(reads_only, "2026-10-15T13:00:00Z", str, [], 9) == ""


def test_cap_is_600_bytes_in_bytes():
    _, mine = previous_session(ROWS, "current")
    line = last_session_line(mine, "2026-10-15T13:00:06Z", lambda p: "ไทย" * 40 + p, ["ก" * 300] * 3, 1)
    assert len(line.encode("utf-8")) <= 600
    line.encode("utf-8").decode("utf-8")  # never split inside a character


def test_compact_lists_edits_only():
    rows = [_r(1, "a.py", session="s"), _r(2, "b.py", "read", session="s"), _r(3, "c.py", "write", session="s")]
    assert compact_line(rows, "s", str) == "[bantamkit touch] edited in this session before compaction: c.py, a.py"
    assert compact_line([_r(1, "a.py", "read", session="s")], "s", str) == ""
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python)** `summary.py` exactly to the Interfaces block: pure functions over rows; `now` and timestamps parsed with the usage ledger's parser; the cap with a copy of `hookadapter._cap_bytes` semantics (import it into `touch/summary.py` would invert the layer direction, so put `cap_bytes` in `touch/summary.py` and have nothing else change). Hook `_touch_summary`:

```python
def _touch_summary(run: HookRun, payload: dict[str, Any]) -> str:
    try:
        repo = find_repo(str(payload.get("cwd") or os.getcwd()))
        if repo is None:
            return ""
        rows = TouchLog(run.home, repo.id).read()
        files = ls_files(repo) or []
        fs = FileSet(files)
        display = lambda p: shortest_suffix(p, fs) if p in fs.files else p  # noqa: E731
        session = _js_str(payload.get("session_id") or "")
        if payload.get("source") == "compact":
            return compact_line(rows, session, display)
        prev = previous_session(rows, session)
        if prev is None:
            return ""
        _, mine = prev
        first, last = min(r["ts"] for r in mine), max(r["ts"] for r in mine)
        until = shift_ts(last, SUMMARY_COMMIT_GRACE_S)
        log = git(repo, ["log", "--format=%s", f"--since={first}", f"--until={until}", "HEAD"]) or ""
        status = git(repo, ["status", "--porcelain=v1", "-z", "-uall"]) or ""
        uncommitted = len([e for e in status.split("\0") if len(e) >= 4 and e[2] == " "])
        return last_session_line(mine, _stamp(), display, [s for s in log.split("\n") if s], uncommitted)
    except Exception:  # noqa: BLE001
        return ""
```

`shift_ts(ts, seconds) -> str` lives in `summary.py` (same ISO format). In the `-z` status the source path of a rename is a separate NUL field without the `XY ` prefix, which `e[2] == " "` excludes; check the count on a rename in the unit test. Git reads `--since=2026-10-15T10:00:01Z` as UTC because of the `Z`; pin it in a test with `TZ=Asia/Bangkok` set for the git subprocess.

- [ ] **Step 4: Implement (Node)**, same names; `Buffer.byteLength` for the cap check and a byte-boundary cut identical to `capBytes` (`hookadapter.ts:276`).
- [ ] **Step 5: Run the unit tests to see them pass.** Then `--all`: every existing SessionStart case stays green (their beds have no touch log, so the line is empty and nothing is appended).
- [ ] **Step 6: Conformance `touch-summary.mjs`.**
  - Module: `age_text` at each boundary (59 s, 60 s, 3599 s, 3600 s, 172799 s, 172800 s); `previous_session` with ties on the latest `ts` (broken by session id, code point; add that rule to both and to the docstring); `last_session_line` over fixtures: Thai and astral file names near the cap, exactly 600 bytes, 601 bytes, many commits, zero edits with commits, the `display` callback as a fixed table; `compact_line` with 12 edits.
  - Hook: SessionStart `startup` and `compact` over one git bed with a seeded touch log and two commits made by the harness at fixed `GIT_COMMITTER_DATE`s; compare stdout with the age masked (`\d+ (min|h|d) ago|just now` → `<age>`).
  - Literals per side: the Step 1 line bytes; `len(bytes)` of the cap fixture `== 600`.
  - Mutations: Node counts characters, not bytes, for the cap (red: Thai fixture); Python lists reads (red); Node lists reads after compact (red); symmetric: both cap at 601 (red only on the literal).
- [ ] **Step 7: Run the gates and commit** (`feat(touch): a 600-byte summary of the last session at SessionStart, and this session's edits after compaction (#200)`).

---

### Task 7: `memory_recall({file})`

**Files:**
- Create: `runtime-py/src/bantamkit/touch/recallfile.py`, `runtime-ts/src/touch/recallfile.ts`, `runtime-py/tests/test_touch_recall_file.py`, `runtime-ts/test/touch-recall-file.test.mjs`
- Modify: `assets/tools/memory_recall.json`; `runtime-py/src/bantamkit/mcpserver.py` (`memory_recall` `:1497`), `runtime-ts/src/mcp/server.ts` (`case 'memory_recall'` `:593`); `runtime-py/src/bantamkit/memory/component.py`, `runtime-ts/src/memory/component.ts` (`recall_file`); `tools/conformance/suites/wire.mjs` (a block after J69-5's at `:548`)

**Interfaces:**
- Consumes: `find_repo`, `git`, `TouchGraph`, `TouchLog`, `FileSet`, `shortest_suffix`.
- Produces:
  - Schema: `file: {"type": "string", "description": "A tracked file, or the shortest unique suffix of one (store.ts, memory/store.ts). Returns the facts linked to it and when it was last touched; query is then ignored."}`; `required: []`; `description` gains one sentence: `"Pass file instead of query to see the memories linked to a file."` `npm run sync-assets` copies the asset to the Node side.
  - Sentences (both runtimes, byte-identical, constants in `touch/recallfile.*`):
    - `RECALL_NEEDS_QUERY_OR_FILE = "memory_recall needs a query or a file."` — raised as `MemoryValidationError` (a tool error, as `MIN_RATIO_RANGE` is, `store.py:164`).
    - `FILE_NOT_IN_REPO = "memory_recall file needs a git repository; the server's working directory is not inside one."`
    - `FILE_UNKNOWN = 'No tracked file in this repository matches "{file}".'`
    - `FILE_AMBIGUOUS = '"{file}" matches {n} tracked files: {names}. Pass a longer suffix.'` with `names` the matches' shortest suffixes sorted by code point, the first 5 joined by `", "`, and `" (+k)"` when more.
    - `FILE_NO_FACTS = "No memory is linked to {suffix}."`
    - `QUERY_IGNORED = "(query ignored: file was given)"`
  - Reply: line 1 `[file] {suffix} — last touched {YYYY-MM-DD} ({op}){; last commit {sha7} {subject}}`, or `last touched never` when the touch log has no row for it; then, when `query` was also given, line 2 `QUERY_IGNORED`; then a blank line and the linked facts formatted exactly as a recall formats them (`Memory._format`): strong edges first in the graph's order, then weak edges by decayed weight descending, then name; at most `max(k, self.k)` facts; `FILE_NO_FACTS` in their place when there are none. Last commit from `git log -1 --format=%h%x00%s -- <path>`.
  - `Memory.recall_file(file: str, k: int | None = None, query: str | None = None) -> RecallOutcome` (status `answered`, `none` for the four non-error sentences).

- [ ] **Step 1: Failing tests** (Python; mirror in Node): over a git bed with `src/memory/store.ts`, `other/store.ts`, `docs/x.md` and a store holding `fa` ("about memory/store.ts"):
  - `recall_file("memory/store.ts")` reply starts `[file] memory/store.ts — last touched never` and holds `fa`'s formatted entry;
  - `recall_file("store.ts")` reply is `"store.ts" matches 2 tracked files: memory/store.ts, other/store.ts. Pass a longer suffix.`;
  - `recall_file("nope.py")` reply is `No tracked file in this repository matches "nope.py".`;
  - `recall_file("docs/x.md")` holds `No memory is linked to x.md.`;
  - outside a repo: `FILE_NOT_IN_REPO`;
  - the server handler with neither argument raises the tool error `memory_recall needs a query or a file.`;
  - with both, line 2 is `(query ignored: file was given)`;
  - after a touch line for `src/memory/store.ts`, line 1 reads `last touched 2026-10-16 (edit)`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python)** `recallfile.py` (the sentences and `history_line(repo, path, rows, display) -> str`) and `Memory.recall_file` in `component.py`, which: finds the repo from `os.getcwd()` (`storage.tiers.current_cwd`); loads `TouchGraph(Path.home(), repo).load(...)`; on `None` falls back to `ls_files` + no edges (so a graph failure still answers the history line, and the facts part reads `FILE_NO_FACTS`); resolves `file` with `FileSet(files).matches(file.strip().replace("\\", "/"))`; looks the linked facts up with the non-stamping lookup used in Task 5. The handler:

```python
def memory_recall(query: str | None = None, k: int | None = None,
                  include_archived: bool | None = None, file: str | None = None) -> str:
    if k is not None:
        k = max(1, min(k, 5))
    with _record_raise(log, "memory_recall"):
        if file is not None:
            outcome = memory.recall_file(file, k, query)
        elif query is None:
            raise MemoryValidationError(RECALL_NEEDS_QUERY_OR_FILE)
        elif include_archived:
            outcome = memory.recall_outcome(query, k, include_archived=True)
        else:
            outcome = memory.recall_outcome(query, k)
    ...  # detail and log.record exactly as today, plus detail["file"] = True when file was given
```

Keep the existing long comments of the handler in place. `_from_manifest(memory_recall, "memory_recall")` (`mcpserver.py:2016`) checks the function signature against the manifest; run `pytest -k manifest` to confirm the new parameter is accepted, and read `_from_manifest` if it is not.
- [ ] **Step 4: Implement (Node)**: `asText(args.get('file'))` when present; `recallFile` on the component; the same error through `recordRaise`.
- [ ] **Step 5: Run the unit tests to see them pass.**
- [ ] **Step 6: Conformance in `wire.mjs`** (a `memory-recall-file` block modelled on J69-5's `memory-archived`): a bed `git init`-ed by the harness with the three files committed, two saves (one naming `memory/store.ts`), then `tools/list` (the schema with `file`, `required: []`, compared byte for byte on both SDKs); calls `{file:"memory/store.ts"}`, `{file:"store.ts"}`, `{file:"nope.py"}`, `{file:"docs/x.md"}`, `{file:"store.ts", query:"x"}`, `{}` (the error), `{file: 3}` (the argument layer's refusal on both SDKs), `{file: null, query: "x"}` (an ordinary recall), `{file:"memory\\store.ts"}` (a Windows separator accepted). A second bed with no git compares `FILE_NOT_IN_REPO`.
  - Literals per side: the `FILE_UNKNOWN` reply bytes for `nope.py` (the spec's "byte-identical across runtimes" sentence, pinned per side so a reworded sentence on both sides is red); the error text of `{}`; and the refusal bit (`isError: true`) of `{}`.
  - Mutations: Node's `FILE_UNKNOWN` without the quotes (red); Python accepts an ambiguous suffix by taking the first match (red); Node does not normalise `\` (red); symmetric: both reword `FILE_UNKNOWN` (red only on the literal).
- [ ] **Step 7: Run the gates and commit** (`feat(memory): memory_recall({file}) lists the facts linked to a file and when it was last touched (#200)`).

---

### Task 8: Eval — silver, tune `W_CONTEXT`, gold pass 2, the bar

**Files:**
- Create: `tools/eval/recall/mine_touch_silver.py`, `score_touch.py`, `build_via_gold.py`, `tune_context.py`, `test_eval_touch.py`
- Modify: `runtime-py/src/bantamkit/memory/retrieval.py` + `retrieval.ts` (`W_CONTEXT`), `touch/context.py` + `context.ts` (`CONTEXT_WEAK_SHARE`, `VIA_ON`)
- Output (gitignored, `.shiftwork/notes-<job>/`): `touch-silver.jsonl`, `tuning-touch.json`, `via-gold-candidates.jsonl`, `via-gold-result.json`, `latency.json`

**Interfaces:**
- Produces:
  - `mine_touch_silver.py --projects <copy of ~/.claude/projects> --repo <this repo> --out touch-silver.jsonl [--rows-out touch-rows.jsonl]`: one line per user prompt in a session whose `cwd` realpath is `--repo`: `{"prompt": str, "session": str, "window": [repo-relative path, most recent first], "positives": [fact], "thai": bool}`. `--rows-out` also writes the transcripts as touch-log rows (`read`/`edit`/`write` per file tool, `use` per `memory_recall` hit or memory-file Read), `seq` being the tool call's ordinal in its session and `ts` its transcript timestamp. The window is the touched files (Read/Edit/MultiEdit/Write/NotebookEdit `file_path` made repo-relative) among the 20 tool calls before the prompt. A fact is positive when the agent then used it in that prompt's window (the `mine_silver.py` rule: a `memory_recall` naming it or a Read of its file) **and** it has a strong edge to a file in `window` (refs resolved against `--repo`'s current `git ls-files` and renames). Rows with an empty window are kept with `positives: []` (they score precision only).
  - `score_touch.py --labels <jsonl> --store-root <copy> --profile-root <copy> --repo <repo> [--w-context x] [--weak-share y] [--via on|off]` prints `{"precision_at_inject": float, "recall_at_3": float, "via_precision": float, "via_n": int, "n": int}`. It builds `Memory.layered_for_eval` over the copies; points `HOME` at a scratch dir and writes `--rows touch-rows.jsonl` into that scratch touch log, keeping only rows timestamped before each scored prompt (so no edge comes from the future: one graph per distinct cut-off, cached by cut-off); builds a `TouchGraph` against `--repo`; makes a `TouchContext` from each row's `window`; and calls `recall_outcome(prompt, 3, stamp=False, context=ctx)`.
  - `build_via_gold.py --silver touch-silver.jsonl --n 50 --seed 200 ... --out via-gold-candidates.jsonl` writes gold-label rows `{"id", "prompt": "<prompt> — touched: <a>, <b>, <c>; via <suffix>", "candidates": [via fact], "thai"}` for prompts where the via path admits a fact (run with `VIA_ON` forced on).
  - `tune_context.py` grid on silver only: `W_CONTEXT ∈ {0, 0.1, 0.2, 0.4, 0.8}`, `CONTEXT_WEAK_SHARE ∈ {0, 0.25, 0.5, 1.0}`; objective: maximise recall@3 subject to precision@inject on silver ≥ the `--w-context 0` row's precision@inject (context must not cost precision). Writes `tuning-touch.json` with every point and the choice.

- [ ] **Step 1: Failing tests** in `test_eval_touch.py`: a two-prompt fake transcript (copy the `_line` helper from `test_eval_recall.py:8`) where an Edit of `src/a.py` precedes the second prompt and the agent then recalls `fa`, whose description names `src/a.py`: the miner writes the window `["src/a.py"]` and `positives: ["fa"]`; a Bash call in the 20 is counted but adds no path; a third prompt 21 calls later has an empty window. `score_touch` over a store copy with `fa` and `--via on` reports `via_n == 1` and `via_precision == 1.0` against labels marking `fa` positive.
- [ ] **Step 2: Run them and see them fail. Step 3: Implement the four scripts. Step 4: Run them and see them pass.**
- [ ] **Step 5: Mine and tune.** Copy `~/.claude/projects` to the scratchpad first (read-only use of the copy; never the original path as `--projects`); copy the project and profile stores likewise. Run the miner, then `tune_context.py`. Copy the chosen `W_CONTEXT` into BOTH `retrieval.py` and `retrieval.ts`, and `CONTEXT_WEAK_SHARE` into both `context.*`. Run all four gates (conformance literals that pinned `W_CONTEXT = 0.0`-dependent weights are module cases with explicit overrides, so none should move; a red is investigated, not updated). Commit the constants with the tuning summary in the message (`perf(touch): W_CONTEXT and the weak share tuned on #200 silver (#200)`).
- [ ] **Step 6: Build gold pass 2 and stop for the user.** `build_via_gold.py` → `via-gold-candidates.jsonl`. The orchestrator hands the user `tools/eval/recall/gold-label.html` with that file (the page is reused unchanged: it keeps `{id, prompt, candidates, thai}`, `:121`, and the touch context is inside `prompt`). The user saves `via-gold-labels.jsonl`. **This unit ends here** with status `blocked: user gold pass 2`; the scoring step is the next unit.
- [ ] **Step 7: Score gold once** (separate unit, after the labels exist):
  - `score_touch.py --labels via-gold-labels.jsonl --via on` → `via_precision`. PASS iff ≥ 0.8.
  - Overall precision@inject: `score_touch.py` over #199's `gold-labels.jsonl` rows re-joined to their sessions by prompt text (`mine_touch_silver.py --match-prompts gold-labels.jsonl`), with the tuned context and `--via` set as decided; an injected fact absent from a row's labelled candidates counts as not relevant (declared in `bar-touch.json`). PASS iff ≥ J68-7's v2 gold precision@inject.
  - Latency: `bench_touch.mjs after …` interleaved with `base` (the Task 0 build checked out into the scratchpad) three rounds; PASS iff PostToolUse-Read p50 rise ≤ 2 ms and `git-status` p50 ≤ 30 ms.
  - Write all numbers, with the commit measured at, to `via-gold-result.json` and the note.
  - **Decision:** via PASS → set `VIA_ON = True` in both `context.*`, run the gates, commit (`feat(touch): the via path on by default, gold pass 2 precision <x> (#200)`). Via MISS → `VIA_ON` stays `False`, `w_context` stays on; nothing else changes. Any other criterion MISS → change nothing; the orchestrator takes it to the user.
- [ ] **Step 8: Reported, not gated.** From the hook logs of the scratch-copied `~/.bantamkit/hooks/hook-log.jsonl` (only if the user has run a build with #200 for some days; otherwise state "no data yet"): sessions with `touchBytes > 0` at SessionStart against those without, mean count of PreToolUse Read `refuse`/`allow` records per session. Report in the note.

---

### Task 9: Docs, Windows check, reviewer

**Files:**
- `docs/touch.md` (new): the touch log (path, line shapes, what is and is not recorded, the `use` lines and why the server cannot write them), the counter, bash-turn, the graph and its two prints, `w_context`, the via path and its default, the B lines with the exact shapes, `memory_recall({file})` with the six sentences, the error table, the eval and the bar with the measured numbers.
- `docs/memory.md`: `w_context`, the via line, `memory_recall`'s `file`.
- `docs/hooks.md`: what PostToolUse, UserPromptSubmit, Stop and SessionStart now do; the files under `~/.bantamkit/hooks/` (`ledger-*.seq.json`, `ledger-*.turn.json`).
- `docs/storage.md`: `touch/` and `graph/` under `~/.bantamkit`, the index v5 `refs`, retention of touch logs.
- `docs/conformance.md`: the six new suites.
- `docs/porting.md`: divergence rows if any (expected none); the Task 1 `use_names` body-line behaviour is a shared behaviour, not a divergence.
- `runtime-py/tests/test_layers.py`: add `"touch"` to `FORBIDDEN_IMPORTS` (`:225`), so `contract.py`/`profile.py` cannot import it.

- [ ] **Step 1: Write the docs.** Every number comes from the Task 8 note, with the commit it was measured at.
- [ ] **Step 2: Windows.** Run `npm test` and the six touch suites on the Windows box (or list it as a manual step for the user, as job69's Task 8 did): `relpath` across a `C:\` vs `D:\` cwd answers `None`; a `.git` file worktree; `git` absent from PATH (every touch feature silent, every hook green); 20 parallel PostToolUse processes against one session give `seq` 1..20 with no gap and 20 touch lines.
- [ ] **Step 3: Reviewer unit (Opus).** It reads the diff against the branch point of Task 0, reruns the four gates and every mutation listed in Tasks 1–7, checks every spec section maps to code (E1–E5, Error handling rows, Testing bullets, the bar), and reports blockers.
- [ ] **Step 4: Commit the docs** (`docs(touch): the touch graph — log, refs, bash-turn, graph, w_context, via, summaries, memory_recall file (#200)`).

---

### Task 10: Fix the reviewer's blockers

- [ ] One commit per blocker, each with the case that proves it red before and green after, both runtimes in the same commit; rerun the four gates; the reviewer re-checks only the blocker list.

---

## Shiftwork unit map (#200 checkpoint; the orchestrator names the job)

| Unit | Task | Depends on | Role / model |
|---|---|---|---|
| T200-0 | Task 0 bar + latency baseline | job68 closed | implementer / claude-opus-5-5 |
| T200-1 | Task 1 touch log + counter + PostToolUse | T200-0 | implementer / claude-opus-5-5 |
| T200-2 | Task 2 refs + renames + suffix + index v5 | T200-0 | implementer / claude-opus-5-5 |
| T200-3 | Task 3 bash-turn | T200-1 | implementer / claude-opus-5-5 |
| T200-4 | Task 4 graph | T200-1, T200-2 | implementer / claude-opus-5-5 |
| T200-5 | Task 5 w_context + via | T200-4 | implementer / claude-opus-5-5 |
| T200-6 | Task 6 B summaries | T200-3, T200-2 | implementer / claude-opus-5-5 |
| T200-7 | Task 7 memory_recall({file}) | T200-4 | implementer / claude-opus-5-5 |
| T200-8a | Task 8 Steps 1–6: silver, tune, build gold pass 2 | T200-5, T200-6, T200-7 | implementer / claude-opus-5-5 |
| T200-8b | Task 8 Steps 7–8: score gold once, set VIA_ON | T200-8a, **gold pass 2 labels from the user** | implementer / claude-opus-5-5 |
| T200-9 | Task 9 docs + Windows + reviewer | T200-8b | reviewer / claude-opus-5-5 |
| T200-10 | blockers from T200-9 | T200-9 | implementer / claude-opus-5-5 |

**Width:**
- Wave 1: T200-1, T200-2 (different new modules; T200-2 also edits `storage/hotindex.*`, T200-1 edits `storage/tiers.*` and `retention.*`; both edit `tools/conformance/ref/touch_ref.py`, so T200-2 creates its ops in a separate section and the second to clock out rebases its section onto the first's, never overwriting it).
- Wave 2: T200-3, T200-4 (T200-3 edits `hookadapter.*` UserPromptSubmit/Stop; T200-4 touches no hook).
- Wave 3: T200-5, T200-6, T200-7 all edit `hookadapter.*` or `component.*`: run T200-5 first, then T200-6 and T200-7 together (T200-6 edits only `_session_start`; T200-7 only `component.recall_file` and the servers).

**The one user step inside the job:** labelling gold pass 2 (`via-gold-candidates.jsonl` in `gold-label.html`). T200-8b waits on it.

**Release:** #200 ships in 0.37.0-beta.1 with #199 and #204 (the bump, the `publish` step and the tag are the user's, after merge).

## Open questions for the user (from the spec; not guessed)

- **Q1.** The spec puts the session on the usage ledger; the server cannot know it, so this plan records weak-edge uses in the touch log from the hook. Keep that, or is there a session source for the MCP server this plan missed?
- **Q2.** Does the via fact take a 4th line (this plan), or replace the 3rd gated hit when all three slots are full?
- **Q3.** Is "off until gold pass 2 passes" the intended default for the beta, given the beta may be cut before the user labels pass 2?
- **Q4.** "After compact": SessionStart(`source=compact`) in the fresh context (this plan), or PreCompact's output to the summariser beside the read list?
- **Q5.** `memory_recall` with both `file` and `query`: ignore the query and say so (this plan), or filter/order the linked facts by the query?

## Amendments (orchestrator, 2026-10-16, after P-200)

The open questions above are settled as follows; each answer keeps a property the spec already fixes.
- **Q1 → keep the plan.** Weak-edge "use" events come from the hook into the touch log. The spec's property is
  same-session co-occurrence within ±20 tool calls; only the hook knows the session and the ordinal. The usage
  ledger does not gain `session`. Record this as a spec deviation in `docs/touch.md` (Task 9).
- **Q2 → 4th line.** E3 says a via fact is admitted past the gate, so it never displaces a gated hit; the 700-byte cap
  cuts it first.
- **Q3 → off.** The spec's bar says the path ships off by default unless pass 2 measures ≥ 0.8; a beta cut before
  pass 2 is scored has measured nothing, so `VIA_ON = False` and `BANTAMKIT_VIA=on` opts in.
- **Q4 → SessionStart(`source=compact`).** The spec says PreCompact already lists reads and the summary "adds only
  the edits"; the fresh context is where it is read.
- **Q5 → ignore the query and say so.** E1(C) defines `file` as returning the facts linked to that file plus a
  history line; filtering by query is not in the spec.
- **Gold pass 2 judge (user ruling 2026-10-16, spec amended).** Task 8a builds `via-gold-candidates.jsonl`, then a
  blind judge unit labels it (it reads only a judge-input file holding the prompt, its touch context and the fact
  text — no silver, no engine output), and the user labels a 10-prompt subset picked by a declared seed. Task 8b runs
  `tools/eval/recall/gold_merge.py` (bar from `bar-touch.json` `gold_judge`, same thresholds as #199's `bar.json`) and
  scores gold once only if it passed. Task 0 declares that `gold_judge` block in `bar-touch.json` before any number.
- **Start condition relaxed for T200-0..T200-7.** They change no #199 constant and produce no eval number, so they may
  start before job68 closes, provided no job68 unit is running in the tree at the same time on `retrieval.*`,
  `store.*` or `hookadapter.*`. T200-8a still waits on J68-7's frozen constants.
