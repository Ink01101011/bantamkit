# File-Access Graph Design

**Date:** 2026-08-09
**Status:** Approved (user: start the file-access graph cycle; all three
mechanisms; per-run + optional persist; verify-on-repeat correctness)
**Depends on:** recall-json-scoring (PR #10, v0.6.0)

## 1. Problem

Small-model agents re-read files they have already read and pick the wrong
tool for repeat access. Every re-read dumps the full content into context
again — wasted tokens, and on a 4B model the bloat degrades accuracy. The
agent has no record of *what it already read, with which tool, and whether
it changed*. User-stated goal: a graph mapping files-already-read + the
tool that read them, making file reads faster (fewer tokens) and more
accurate (model knows its own access history).

## 2. Design decisions

### 2.1 `FileAccessGraph` component (tool-wrapping)

New module `runtime-py/src/bantamkit/filegraph.py`, following the
`Memory` component pattern (`setup(agent)`; attached via `Agent.use`).

```python
FileAccessGraph(readers={"read_file": "path"}, annotate=True,
                cache=True, query=True)
```

- `readers` maps tool name → the argument holding the file path. The graph
  only sees declared readers — that boundary is pinned by tests (§3).
- `setup(agent)` wraps the handler of every already-registered matching
  `ToolDef`, **and** replaces `agent.register_tool` with a delegate that
  wraps matching tools registered later — attach order cannot silently
  create a blind spot. Tools appended directly to `agent.tools` (bypassing
  `register_tool`) remain the one documented, test-pinned gap.
- Each successful read records an edge:
  `(path, tool, read_index, sha256(observation), count)`. Paths are
  normalized with `posixpath.normpath` so `./config.yaml` and
  `config.yaml` are one node. Handler errors (observation starting with
  `error:` or a raised exception) are never recorded as reads and never
  cached.
- **The write path is deterministic Python — no model in the loop.**
  Correctness is proven offline, not calibrated.

The three mechanisms, each independently toggleable:

- **`annotate`** (accuracy): on a *repeat* read, prefix the observation
  with one line: `[file-graph] read #N of {path} via {tool} — unchanged
  since your last read` (or `— CHANGED`). First reads pass through byte-identical
  to a graph-less run, so a run with no repeats is indistinguishable from
  `bare` — clean comparability.
- **`cache`** (speed, verify-on-repeat): the wrapper **always executes the
  real handler**, hashes the result, and only when the hash matches the
  previous read returns the short marker
  `[file-graph] {path} unchanged since your last read ({n} bytes not
  repeated)`
  instead of the full content. Changed content passes through in full.
  What is saved is model tokens, not disk I/O — staleness is impossible by
  construction. `cache=True` implies the annotate line lives inside the
  marker; `annotate=True, cache=False` prefixes the note but returns full
  content.
- **`query`**: registers a `file_graph` tool (asset-pack schema, no
  required args) returning the compact map — one line per node:
  `{path} — {count} read(s) via {tool}, last {unchanged|changed}`. Empty
  graph returns `no files read yet`. When enabled, `add_system` attaches a
  short `file-graph` skill snippet (asset pack) telling the model the tool
  exists and to consult it before re-reading.

**Persistence (opt-in):** `save(path)` / `load(path)` — JSON round-trip of
the edge list. Per-run in-memory remains the core; persistence ships as
API + tests only, with no uplift claim (measuring cross-session uplift is
out of scope, §5).

### 2.2 Eval builtin file tools + workspace fixtures

The suite has no file tools today. Add to `BUILTIN_TOOLS` in `evalrun.py`
(same pattern as the shop tools):

- `read_file(path)` — returns the content of `path` from the task's new
  `workspace:` mapping (path → content) in the YAML; unknown path returns
  `error: unknown file '{path}'. available: {sorted list}`.
- `list_files()` — returns the sorted workspace paths.

Tasks using them list `tools: [read_file, list_files]` and carry a
`workspace:` block. No `schema` keys (config semantics stay comparable);
scoring is `json_equal` with exact-JSON prompts, same as the converted
recall family.

### 2.3 `file-nav` candidate family + calibration

- 4–6 candidates in `assets/evals/candidates/`, family `file-nav`:
  answers require composing facts from 2–3 files among bulky distractor
  files, with prompts that induce full exploration — sized so a graph-less
  4B run re-reads and bloats context.
- New eval config `graph` = `bare` + `FileAccessGraph` (all three
  mechanisms on, `readers` declaring `read_file`; `list_files` takes no
  path argument and is not a reader) — joins `CONFIGS`.
  On tasks without file tools the graph wraps nothing, so `graph` must
  match `bare` there — a falsifiable no-op check the sweep verifies.
- Calibration (qwen3:4b-instruct, 3 repeats) also runs two ablations that
  do **not** join `CONFIGS`: `graph-annotate` (annotate only) and
  `graph-cache` (cache+annotate, no query) — attributing which mechanism
  moves the number.
- **Promotion bar per task** (either clears it; record which):
  1. *Score discriminator* (primary): `bare` ≤1/3 **and** `graph` ≥2/3.
  2. *Efficiency discriminator*: both ≥2/3 **and** `graph` total tokens
     ≥25% below `bare` on that task.
  Candidates clearing neither stay unpromoted, numbers recorded in docs.
  This family may honestly discriminate on efficiency rather than score —
  the bar says so upfront instead of pretending otherwise.

### 2.4 Re-measurement

Full reference sweep after promotion: 8 configs × (20 + promoted) tasks ×
3 repeats, new JSONL under `docs/eval-data/`, Current results rewritten
(previous table demoted to the historical section, established pattern).
Falsifiable expectations: `graph` = `bare` on all non-file tasks;
converted recall and shop cells unchanged for existing configs.

### 2.5 Version

0.7.0 (new primitive + new config + suite growth). Tag `v0.7.0`
post-merge on the user's word.

## 3. Testing (offline, in CI)

- Wrapper records every declared-reader call; undeclared tools bypass and
  are **not** recorded (the documented coverage boundary, pinned).
- Late registration: a matching tool registered *after* `use(graph)` is
  wrapped (the `register_tool` delegate); direct `agent.tools.append`
  bypass pinned as the known gap.
- Normalization: `./a.yaml` and `a.yaml` are one node.
- Verify-on-repeat: repeat with identical content → marker; repeat with
  changed content → full content + `CHANGED` annotation; marker never
  claims `unchanged` without a fresh handler execution (assert call
  count).
- Error observations are not recorded and not cached.
- `annotate=True, cache=False` returns full content + note; first reads
  byte-identical to unwrapped output.
- `file_graph` tool output shape; empty-graph sentinel; system snippet
  attached only when `query=True`.
- `save`/`load` JSON round-trip restores dedupe/cache behavior.
- `read_file`/`list_files` handlers against a workspace fixture, unknown
  path error shape.
- Conformance: `workspace` shape validated for `file-nav` tasks; family
  balance and suite floor updated with promotions.
- Config wiring: `graph` config attaches `FileAccessGraph` with
  `read_file` declared as reader; fake-client test asserting the cache marker appears on a
  scripted repeat read.

## 4. Success criteria

1. Calibration data decides every candidate's fate; promoted tasks hold
   their bar (score or efficiency, recorded per task) in the full sweep.
2. `graph` ties `bare` on non-file tasks in the sweep (no-op check).
3. Offline suite + ruff green in CI.
4. docs/eval.md documents the new family, the `graph` config, ablation
   attribution, and per-candidate outcomes with numbers.
5. v0.7.0 pinned install verifiable post-merge.

## 5. Out of scope

- Measuring persistence uplift across sessions (`save`/`load` ship with
  offline tests only; no live claim).
- MCP exposure of the graph; TS port.
- File-change watching beyond content-hash comparison at read time.
- Generic call-graphs for non-file tools; wrapping tools without a path
  argument.
- Real-filesystem edge cases (symlinks, case-insensitive FS) — synthetic
  workspaces only; documented caveat.
