# Recall Embedding (round two) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo every multi-unit run goes through the shiftwork tools (CLAUDE.md); the unit map is at the end.

**Goal:** Put recall's scorer behind a `Scorer` interface in both runtimes (shippable alone), then add an opt-in ollama embedding scorer that ranks every fact of every layer by cosine, with a derived vector cache, a strict BM25 fallback, operator fill paths, status lines and a predeclared eval (issue #207).

**Architecture:** Recall is columnar. `pooled_ranking` (Python `runtime-py/src/bantamkit/memory/store.py:540`, Node `runtime-ts/src/memory/store.ts:666`) concatenates every layer's `Pool`, scores the concatenation once with `bm25_segments`, and orders it with `rank_columns`. The `Scorer` replaces only that one scoring call. `Bm25fScorer` wraps it unchanged. `CosineScorer` reads one float32 vector per pooled row from a per-store vector cache beside the hot index. A query is embedded before recall by `Memory.prepare(query)`, which is sync in Python and async in Node. That keeps `recall_outcome` synchronous on both sides. If the backend is off or failing, or a row has no vector, the whole recall is ranked by BM25, byte for byte as before.

**Tech Stack:** Python 3.11+ (`runtime-py`, stdlib only: `urllib.request`, `array`, `hashlib`, `functools`, `threading`); TypeScript on Node ≥ 20 (`runtime-ts`, `node:http` request with `agent: false` and a total-deadline timer (never global `fetch`, see Global Constraints), no new dependency); conformance harness `tools/conformance/run.mjs`; pytest; `node --test`; ollama over loopback HTTP (opt-in, never a dependency).

**Spec:** `docs/superpowers/specs/2026-10-17-recall-embedding-design.md` (D1–D10, approved 2026-10-17, commit 6df4084). Deviations this plan had to resolve against the code are listed in `.shiftwork/notes-job71p/P-207.md`.

## Global Constraints

- Every feature lands in BOTH `runtime-py/` and `runtime-ts/` in the same task, with a conformance case comparing the two. That covers the same tool schema, the same error sentence and the same exit code (CLAUDE.md, "Two runtimes, one surface").
- **User rulings 2026-10-17 (answers to P-207's open questions; binding):**
  - Q1: `OLLAMA_HOST=0.0.0.0` (and `::`) counts as loopback, but the request goes to `127.0.0.1` (or `::1`): `parse_host` rewrites the unspecified address before building `base`, so no request ever targets `0.0.0.0`. Spec D7 amended to match.
  - Q2: the hook-log `scorer` key appears only when embedding is configured, so the off path stays byte-identical to 0.37.0-beta.1.
  - Q3: the ≤ 100 ms embedding-on budget gates the **Node** hook only (the one that ships). The Python hook's p50 rise is measured and reported in `latency.json` and the note, never a pass/fail line.
- Orchestrator rule (privacy): the Node HTTP client is `node:http` with `agent: false`, never global `fetch` (proxy env, see Task 2 Step 4); a unit test asserts `embed.ts` contains no `fetch(`.
- A deliberate divergence costs three things: a row in `docs/porting.md`, a `ruling:` case, and, for a refusal, a second unruled case on the refusal bit. This plan has exactly one: the memory CLI's prog spelling inside the new `vectors:` fix line (Task 4).
- No new runtime dependency on either side. The npm install stays pure Node, with no Python at runtime (spec D2).
- The embedding backend is ollama over HTTP and is **opt-in**: `BANTAMKIT_EMBED=ollama`. When it is unset or empty, or holds any other value, embedding is off.
- `BANTAMKIT_EMBED_MODEL` defaults to `bge-m3` (D3). `OLLAMA_HOST` defaults to `http://localhost:11434`.
- Only a loopback `OLLAMA_HOST` is accepted (`localhost`, `127.0.0.0/8`, `::1`). Any other host is refused once at startup and then treated as off (D7). The Python client builds its opener with `ProxyHandler({})`, so no proxy variable can route fact text off the machine.
- Dense cosine runs over **every fact in every layer**. There is no fusion with BM25 (D4).
- Latency (D5, user):
  - With embedding ON: the hook p50 rise is ≤ 100 ms with the model warm, and the query embed has a hard 150 ms total timeout.
  - With embedding OFF: #199's ≤ 5 ms rise over 0.37.0-beta.1 still holds.
- Fallback (D6): if the backend does not answer, times out or lacks the model, or the vector cache does not cover every pooled row, the WHOLE recall is ranked by BM25. Scores are never mixed. The hook never errors on this path.
- Bar (D8, user), copied verbatim into `tools/eval/recall/bar.json` before any number exists. PASS needs both of these on the same pooled gold:
  - embedding view precision@inject ≥ BM25 view + 0.05;
  - recall@3 ≥ BM25 view.
- The #199 bar of 0.8 stays as it is and is still reported as missed.
- Gate (D9): `EMBED_GATE`, an absolute cosine threshold. It is tuned on **silver** only and frozen before gold is scored. The gold set is held out from every tuning step.
- Windows (D10): it is not measured, and the docs say so. The code path has no platform branch.
- Float parity:
  - Vectors are stored as float32 little-endian.
  - Cosine is computed in float64, with sequential summation in index order on both sides. Python uses `functools.reduce(operator.add, map(operator.mul, a, b), 0.0)`, never `sum` or `math.sumprod`; `sum` is compensated since 3.12 (`retrieval.py:240` already says so).
  - The result is rounded to `SCORE_ROUND = 9`. Python uses `round`; Node uses `pyRound9` (`runtime-ts/src/memory/retrieval.ts:121`).
- Never weaken or delete an existing conformance case. The existing `recall-retrieval`, `recall-gate`, `recall-usage` and `recall-strings` suites stay unchanged and are the gate for the Task 0 refactor.
- Every new conformance case is proven red by a one-sided mutation run on an **rsync copy** of the tree, never in place. Each suite also carries one symmetric mutation that only a per-side literal catches (`literalCases` shape, `tools/conformance/suites/recall-gate.mjs:469`).
- **SAFETY:**
  - Every test and probe runs with `HOME` and `USERPROFILE` set to a throwaway dir, `BANTAMKIT_INDEX_DIR=<scratch>/index` and `BANTAMKIT_RETENTION=off`.
  - Never write the real `~/.bantamkit` or `~/.claude`.
  - Never edit `~/.claude/settings.json`.
  - Never delete `~/.bantamkit/retention.json`.
- **PRIVACY:** The repo is public.
  - Prompts, fact bodies, fact names from a private store, injections and judge labels stay under `.shiftwork/` (gitignored). Only aggregate numbers and code go into commits.
  - The private files are named by path only: `.shiftwork/notes-job68/*`, `.shiftwork/notes-job71/*`.
- Conformance runs with `TMPDIR=<scratchpad>/cleantmp/` and only after `cd runtime-ts && npm run build`.
- Gates before every commit:
  - `.venv/bin/python -m pytest runtime-py/tests -q`
  - `cd runtime-ts && npm run build && npm test`
  - `.venv/bin/ruff check runtime-py tools`
  - `node tools/conformance/run.mjs --all`
- Commit only your own files, by explicit path. Never `git add -A`, `-a`, checkout, stash, reset or rebase. No push, tag, bump or publish. End every commit with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **On a MISS (spec §6.7):** only Task 0 ships. Tasks 1–4 stay on a local branch, unmerged and unpushed. The miss is recorded on #207, and the bar stays where it is.

## Start state

- Branch `design/207-recall-embedding` at 6df4084, off main 71ba1e4 = 0.37.0-beta.1. Cut the implementation branch `feat/207-recall-embedding` from it. **Never switch to or push `feat/199-recall-by-meaning`.**
- Fresh tree: `python3 -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"`, then `cd runtime-ts && npm ci && npm run build`.
- Code facts, verified at 6df4084:
  - The BM25 call that the `Scorer` replaces is `scores = bm25_segments(q, n, total, df, lengths, segs)` at `runtime-py/src/bantamkit/memory/store.py:579`, inside `pooled_ranking` (`:540-592`). Node has it at `runtime-ts/src/memory/store.ts:699`, inside `pooledRanking` (`:666-709`).
  - The early return that drops a recall in which no row holds a query term is `store.py:557` / `store.ts:677`. A dense scorer must skip it, because a Thai prompt shares no token with an English fact.
  - `rank_columns` is at `retrieval.py:349` (`retrieval.ts:385`). It reads `GATE_FLOOR` at call time, and `tools/eval/recall/tune.py` rebinds that module global, so the floor must stay a call-time read.
  - Pool rows:
    - `pool_of` (`store.py:455`, `store.ts:614`) keeps only facts holding a query term.
    - `MemoryStore._pool_indexed` (`store.py:1390`) keeps every doc of the index.
    - `NativeStore.pool` (`native.py:146`, `native.ts:145`) is the same, after `pool_without`.
    - So only the files path needs a `full` mode for dense scoring.
  - The hot index (`runtime-py/src/bantamkit/storage/hotindex.py`):
    - The path is `<index dir>/<sha16(source)>.json`, built at `hotindex.py:333`. Node builds it at `hotindex.ts:500`.
    - `INDEX_DIR_ENV` is at `:89` (`hotindex.ts:66`).
    - The head's `cols` hold name, file, length, type and stale, but no description (`_columns`, `:974`).
    - The description and keywords live in line 2's `docs` (`HotIndex.docs_unchecked`, `:364`).
    - The one serialiser is `dumps` (`:131`), `dumpIndex` in Node (`hotindex.ts:246`).
  - The lock is `storage/lock.py:26` `exclusive(path)`, a context manager yielding `held`. Node has `storage/lock.ts:21` `exclusive(target, body)`, whose body is synchronous.
  - Recall entry points:
    - The hook: `hookadapter.py:1289` and `hookadapter.ts:1401`. The Node handler `userPromptSubmit` (`:1380`) is synchronous, and its caller `runHook` (`:2766`) is async.
    - The tool: `mcpserver.py:1527-1529` and `mcp/server.ts:612`. `runTool` (`server.ts:514`) is synchronous, and its caller (`:1306`) is an async request handler.
    - The eval: `component.py:926` `inject_candidates` and `:930` `rank_all`.
  - Status lines end with `read-repaired:` and the usage `status_line` at `mcpserver.py:1021-1024` and `mcp/status.ts:497-500`.
  - Memory CLI:
    - Python: `runtime-py/src/bantamkit/memory/__main__.py`, `_PROG = "python -m bantamkit.memory"` (`:58`), subparsers `:117-151`, `_COMMANDS` `:285`.
    - Node: `runtime-ts/src/memory/cli.ts`, `PROG = 'bantamkit-memory'` (`:91`), parser-as-data `PARSER` (`:176`), `COMMANDS` (`:457`).
    - The spec's `bantamkit memory embed` therefore spells as `python -m bantamkit.memory embed` / `bantamkit-memory embed`.
  - The MCP server start is `mcpserver.py:2996` and `cli.ts:900-912`. The memory it builds carries the native layer from `native_memory_dir` (`hookadapter.py:643`).
  - The conformance harness:
    - `ctx.runPython` is `spawnSync` (`run.mjs:173`), so a stub server must be a **child process**, not an in-process listener.
    - `run.mjs:294-298` already sets `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off`.
    - New suites are discovered by file name (`run.mjs:82`).

## File Structure

| File | Responsibility |
|---|---|
| `runtime-py/src/bantamkit/memory/retrieval.py` | + `Columns`, `Scorer` protocol, `Bm25fScorer`, `BM25F`, `EMBED_GATE`; `rank_columns(..., floor=None)` |
| `runtime-ts/src/memory/retrieval.ts` | The same, byte-for-byte port |
| `runtime-py/src/bantamkit/memory/store.py` | `pooled_ranking`/`pick_hits` take `scorer` and `rows`; `pool_of(..., full=False)`; `MemoryStore.pool(..., full=False)` |
| `runtime-ts/src/memory/store.ts` | The same |
| `runtime-py/src/bantamkit/memory/native.py`, `runtime-ts/src/memory/native.ts` | `NativeStore.pool(..., full=False)` |
| `runtime-py/src/bantamkit/memory/vectors.py` (new) | Embed text, key, model slug, cache path, read/write, `cosine`, `row_vectors`, `CosineScorer`, `fill`, `coverage` |
| `runtime-ts/src/memory/vectors.ts` (new) | Port of the above (`fill` async) |
| `runtime-py/src/bantamkit/memory/embed.py` (new) | Env config, loopback rule, refusal sentence, HTTP client with total deadline, `prepare`, status lines |
| `runtime-ts/src/memory/embed.ts` (new) | Port of the above (async) |
| `runtime-py/src/bantamkit/memory/component.py`, `runtime-ts/src/memory/component.ts` | `Memory.embed`, `Memory.prepare`, `Memory.fallbacks`; `recall_outcome(..., scorer=None)`; `RecallOutcome.scorer`/`.fallback`; embed after save/repair; `vector_coverage` |
| `runtime-py/src/bantamkit/hookadapter.py`, `runtime-ts/src/hookadapter.ts` | Prepare before recall; `scorer`/`fallback` in the UserPromptSubmit log rows |
| `runtime-py/src/bantamkit/mcpserver.py`, `runtime-ts/src/mcp/server.ts`, `runtime-ts/src/mcp/status.ts`, `runtime-ts/src/cli.ts` | Prepare in `memory_recall`; flush pending embeds (Node); start-up fill; status lines |
| `runtime-py/src/bantamkit/memory/__main__.py`, `runtime-ts/src/memory/cli.ts` | `embed` subcommand |
| `tools/conformance/lib/ollama-stub.mjs` (new) | Deterministic loopback ollama, a child process |
| `tools/conformance/suites/recall-embed.mjs` + `tools/conformance/ref/embed_ref.py` (new) | Cache, scorer, fallback, host, CLI, status and hook-log parity |
| `tools/conformance/suites/memorycli.mjs`, `wire.mjs` | `embed -h` byte-identical; the `vectors:` fix-line ruling |
| `tools/eval/recall/bar.json`, `tune_embed.py`, `inject_embed.py`, `bench_embed.mjs` (new) | Predeclared bar, gate tuning on silver, embed-view injections, latency |
| `docs/memory.md`, `docs/status.md`, `docs/porting.md`, `docs/conformance.md`, `docs/hooks.md` | Behaviour, status lines, divergence row, suite, log fields |

---

### Task 0: `Scorer` interface and `Bm25fScorer` (byte-identical; shippable alone)

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/retrieval.py` (after `bm25_scores`, `:228-246`; `rank_columns`, `:349-361`)
- Modify: `runtime-ts/src/memory/retrieval.ts` (after `bm25Scores`, `:275`; `rankColumns`, `:385-400`)
- Modify: `runtime-py/src/bantamkit/memory/store.py` (`pooled_ranking` `:540-592`, `pick_hits` `:595-645`)
- Modify: `runtime-ts/src/memory/store.ts` (`pooledRanking` `:666-709`, `pickHits` `:723`)
- Test: `runtime-py/tests/test_memory_retrieval.py`, `runtime-ts/test/retrieval.test.mjs`

**Interfaces:**
- Produces (Python, `bantamkit.memory.retrieval`):

```python
class Columns(NamedTuple):
    q: list[str]
    n: int
    total: float
    df: Mapping[str, int]
    lengths: list[float]
    segs: Mapping[str, list[Any]]

class Scorer(Protocol):
    dense: bool               # True: column() reads row vectors, and the term-hit early exit is skipped
    fallback: str | None      # set when a dense scorer gave the recall back to BM25
    def label(self) -> str: ...        # "bm25f" | "ollama <model>"
    def used(self) -> str: ...         # label(), or "bm25f" once fallback is set
    def floor(self) -> float: ...      # GATE_FLOOR (read at call time) | EMBED_GATE
    def column(self, cols: Columns, vecs: list[Any] | None) -> list[float] | None: ...

class Bm25fScorer: ...        # dense=False; fallback given at construction
BM25F: Bm25fScorer            # the shared off-path instance, fallback None
EMBED_GATE = 0.0              # Task 5 tunes it on silver
def rank_columns(scores, weights, ratio=GATE_RATIO, floor: float | None = None) -> list[int]
```

- Produces (Python, `bantamkit.memory.store`): `pooled_ranking(pools, q, ratio, usage, context=None, scorer: Scorer = BM25F, rows=None)` and `pick_hits(..., context=None, scorer: Scorer = BM25F, rows=None)`. Here `rows: Callable[[int, Pool], list[Any] | None] | None` gives one vector per row of the live pool at that layer index.
- Produces (Node): `interface Columns`, `interface Scorer`, `class Bm25fScorer`, `BM25F`, `EMBED_GATE`, `rankColumns(scores, weights, ratio = GATE_RATIO, floor: number | null = null)`, `pooledRanking(pools, q, ratio, usage, context = null, scorer: Scorer = BM25F, rows: RowsOf | null = null)`, `pickHits(..., context, scorer = BM25F, rows = null)`, where `type RowsOf = (layer: number, pool: Pool) => Array<Float32Array | null> | null`.

- [ ] **Step 1: Write the failing tests**

```python
# runtime-py/tests/test_memory_retrieval.py (append)
from bantamkit.memory import retrieval
from bantamkit.memory.retrieval import BM25F, Bm25fScorer, Columns, bm25_segments, rank_columns


def test_bm25f_scorer_column_is_bm25_segments():
    cols = Columns(["a"], 3, 6.0, {"a": 2}, [2.0, 2.0, 2.0], {"a": [0, 2, 2.0]})
    assert BM25F.column(cols, None) == bm25_segments(*cols)
    assert BM25F.dense is False and BM25F.fallback is None
    assert BM25F.label() == "bm25f" and BM25F.used() == "bm25f"


def test_bm25f_floor_reads_gate_floor_at_call_time(monkeypatch):
    monkeypatch.setattr(retrieval, "GATE_FLOOR", 1.5)
    assert BM25F.floor() == 1.5


def test_fallback_scorer_reports_bm25f_and_its_reason():
    s = Bm25fScorer("timeout")
    assert s.used() == "bm25f" and s.fallback == "timeout"


def test_rank_columns_explicit_floor_overrides_gate_floor():
    assert rank_columns([0.3, 0.6, 0.0], [1.0, 1.0, 1.0], 0.0, 0.5) == [1]
    assert rank_columns([0.3, 0.6, 0.0], [1.0, 1.0, 1.0], 0.0) == [1, 0]


def test_pooled_ranking_honours_a_rebound_gate_floor(monkeypatch):
    # tune.py rebinds retrieval.GATE_FLOOR between grid points; the scorer must read it per call.
    from bantamkit.memory.store import Fact, pool_of, pooled_ranking

    facts = [
        Fact("alpha-one", "alpha bravo", "project", "", [], None),
        Fact("beta-two", "alpha", "project", "", [], None),
    ]
    q = ["alpha", "bravo"]
    every = list(pooled_ranking([pool_of(facts, q)], q, 0.0, dict))
    assert len(every) == 2
    monkeypatch.setattr(retrieval, "GATE_FLOOR", 10.0)
    assert list(pooled_ranking([pool_of(facts, q)], q, 0.0, dict)) == []
```

```js
// runtime-ts/test/retrieval.test.mjs (append; add BM25F, Bm25fScorer to the import list at :8-25)
test('BM25F column is bm25Segments, floor read at call time', () => {
  const cols = { q: ['a'], n: 3, total: 6, df: new Map([['a', 2]]), lengths: [2, 2, 2], segs: new Map([['a', [0, 2, 2]]]) };
  assert.deepEqual(BM25F.column(cols, null), bm25Segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs));
  assert.equal(BM25F.dense, false);
  assert.equal(BM25F.used(), 'bm25f');
  assert.equal(new Bm25fScorer('timeout').used(), 'bm25f');
  assert.equal(new Bm25fScorer('timeout').fallback, 'timeout');
});
test('rankColumns explicit floor', () => {
  assert.deepEqual(rankColumns([0.3, 0.6, 0], [1, 1, 1], 0, 0.5), [1]);
  assert.deepEqual(rankColumns([0.3, 0.6, 0], [1, 1, 1], 0), [1, 0]);
});
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_memory_retrieval.py -q -k "bm25f or explicit_floor or fallback_scorer"`
Expected: FAIL with `ImportError: cannot import name 'BM25F'`.
Run: `cd runtime-ts && npm run build && node --test test/retrieval.test.mjs`
Expected: FAIL, because `BM25F` is undefined.

- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/memory/retrieval.py — after bm25_scores
class Columns(NamedTuple):
    """The pooled collection `pooled_ranking` hands a scorer: BM25's inputs, in `bm25_segments` order."""

    q: list[str]
    n: int
    total: float
    df: Mapping[str, int]
    lengths: list[float]
    segs: Mapping[str, list[Any]]


class Scorer(Protocol):
    """What ranks the pooled rows (#207 D1). Only the score column changes; gate, weights and
    the inject cap stay where they are. `column` returns `None` when it cannot score every row;
    the caller then ranks the whole recall with BM25F and the scorer's `fallback` says why."""

    dense: bool
    fallback: str | None

    def label(self) -> str: ...
    def used(self) -> str: ...
    def floor(self) -> float: ...
    def column(self, cols: Columns, vecs: list[Any] | None) -> list[float] | None: ...


class Bm25fScorer:
    """Today's scorer, unchanged: `bm25_segments` over the pooled columns."""

    dense = False

    def __init__(self, fallback: str | None = None) -> None:
        self.fallback = fallback

    def label(self) -> str:
        return "bm25f"

    def used(self) -> str:
        return "bm25f"

    def floor(self) -> float:
        return GATE_FLOOR  # a call-time read: tune.py rebinds the module global

    def column(self, cols: Columns, vecs: list[Any] | None) -> list[float]:
        return bm25_segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs)


BM25F = Bm25fScorer()
```

Add `EMBED_GATE = 0.0` after `W_FLOOR` (`:263`), with the comment `# #207 D9: the embedding scorer's absolute cosine floor; Task 5 tunes it on silver only.` Add `Protocol` to the `typing` import.

`rank_columns`:

```python
def rank_columns(
    scores: list[float], weights: list[float], ratio: float = GATE_RATIO, floor: float | None = None
) -> list[int]:
    ...
    best = max(scores, default=0.0)
    least = max(GATE_FLOOR if floor is None else floor, ratio * best)
```

Leave the rest of the body as it is.

`store.py` `pooled_ranking`. Replace `:557` with the guard below, `:579` with the scorer call, and `:584` with the floor:

```python
    live = [(i, p) for i, p in enumerate(pools) if p is not None]
    if not scorer.dense and not any(p.segs.get(t) for _, p in live for t in q):
        return iter(())
    ...  # the column assembly, unchanged
    cols = Columns(q, n, total, df, lengths, segs)
    scores = scorer.column(cols, _row_vectors(live, rows)) if scorer.dense else None
    if scores is None:
        if scorer.dense and not any(p.segs.get(t) for _, p in live for t in q):
            return iter(())
        scores = BM25F.column(cols, None)
        floor = BM25F.floor()
    else:
        floor = scorer.floor()
    used = usage()
    ...
    order = rank_columns(scores, weights, ratio, floor)
```

With `scorer = BM25F` this is the same sequence of operations as today: `column` is `bm25_segments`, and `floor` is `GATE_FLOOR` read at call time.

```python
def _row_vectors(live: list[tuple[int, Pool]], rows: Any) -> list[Any] | None:
    """One vector per pooled row, layer by layer, or `None` when any layer cannot say."""
    if rows is None:
        return None
    out: list[Any] = []
    for i, p in live:
        got = rows(i, p)
        if got is None or len(got) != len(p.names):
            return None
        out += got
    return out
```

`pick_hits` gains `scorer: Scorer = BM25F, rows: Any = None` after `context`, and passes them to `pooled_ranking(pools, q, ratio, weights, context, scorer, rows)`.

- [ ] **Step 4: Implement (Node).** `retrieval.ts`:

```ts
export interface Columns {
  q: readonly string[]; n: number; total: number;
  df: ReadonlyMap<string, number>; lengths: readonly number[]; segs: ReadonlyMap<string, number[]>;
}
export interface Scorer {
  readonly dense: boolean;
  fallback: string | null;
  label(): string;
  used(): string;
  floor(): number;
  column(cols: Columns, vecs: ReadonlyArray<Float32Array | null> | null): number[] | null;
}
export class Bm25fScorer implements Scorer {
  readonly dense = false;
  constructor(public fallback: string | null = null) {}
  label(): string { return 'bm25f'; }
  used(): string { return 'bm25f'; }
  floor(): number { return GATE_FLOOR; }
  column(cols: Columns): number[] {
    return bm25Segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs);
  }
}
export const BM25F = new Bm25fScorer();
export const EMBED_GATE = 0.0;
```

In `rankColumns`, add `floor: number | null = null` and change one line to `const least = Math.max(floor ?? GATE_FLOOR, ratio * best);`.

`store.ts` `pooledRanking` mirrors Step 3 line for line. The guard is `if (!scorer.dense && !live.some(...)) return;`. The column is `const cols = { q, n, total, df, lengths, segs }`. `rowVectors(live, rows)` returns `Array<Float32Array|null> | null`, and on `scores === null` the code takes the BM25F column and floor. `pickHits` forwards `scorer` and `rows`.

- [ ] **Step 5: Run the tests and every recall suite, unchanged**

Run: `.venv/bin/python -m pytest runtime-py/tests -q`. Expected: all pass.
Run: `cd runtime-ts && npm run build && npm test`. Expected: all pass.
Run: `TMPDIR=<cleantmp> node tools/conformance/run.mjs --suite recall-retrieval && node tools/conformance/run.mjs --suite recall-gate && node tools/conformance/run.mjs --suite recall-usage && node tools/conformance/run.mjs --suite recall-strings`
Expected: each prints `PASS`, with the same case count as on 6df4084. Record the counts from a run on 6df4084 first.

- [ ] **Step 6: Prove the refactor is guarded (rsync copy, never in place)**
  - **M0a:** Python `pooled_ranking` passes `floor=0.0` instead of `scorer.floor()`. Expect red on `test_pooled_ranking_honours_a_rebound_gate_floor` only. A floor frozen at 0.0 is invisible to every conformance case, because the shipped `GATE_FLOOR` is 0.0.
  - **M0b:** Node `Bm25fScorer.column` passes `cols.lengths.slice().reverse()`. Expect `recall-gate` and `recall-retrieval` red on cases ranking two or more docs of different length.
  - Record both red counts in the note.

- [ ] **Step 7: Commit**

```bash
git add runtime-py/src/bantamkit/memory/retrieval.py runtime-ts/src/memory/retrieval.ts \
  runtime-py/src/bantamkit/memory/store.py runtime-ts/src/memory/store.ts \
  runtime-py/tests/test_memory_retrieval.py runtime-ts/test/retrieval.test.mjs && git diff --cached --stat
git commit -m "refactor(memory): Scorer interface; Bm25fScorer wraps the pooled BM25F call, byte-identical (#207 D1)"
```

---

### Task 1: The vector cache (format, key, lock, cross-runtime read/write)

**Files:**
- Create: `runtime-py/src/bantamkit/memory/vectors.py`, `runtime-ts/src/memory/vectors.ts`
- Create: `runtime-py/tests/test_memory_vectors.py`, `runtime-ts/test/vectors.test.mjs`
- Create: `tools/conformance/suites/recall-embed.mjs`, `tools/conformance/ref/embed_ref.py` (the cache cases; Task 2 adds the rest)

**Interfaces:**
- Consumes: `hotindex.dumps` / `dumpIndex`; `storage.lock.exclusive`; `retrieval.SCORE_ROUND`; `pyRound9`.
- Produces (Python `bantamkit.memory.vectors`; Node names in camelCase):

```python
CACHE_VERSION = 1
def embed_text(name: str, description: str, keywords: Sequence[str]) -> str
    # f"{name.replace('-', ' ')}: {description}" + (" " + " ".join(keywords) if keywords else "")
def embed_key(text: str) -> bytes          # sha256(utf-8)[:16]; Node: hex string of the same 16 bytes
def model_slug(model: str) -> str          # every char outside [A-Za-z0-9._-] becomes "-"
def vector_path(index_path: Path | str, model: str) -> Path   # <dir>/<stem>.vectors-<slug>.bin
def to_f32(vec: Sequence[float]) -> array  # array('f'); Node: Float32Array.from(vec)
class VectorCache:  # .model .dim .get(key) -> array('f') | None ; len()
def read_vectors(path, model) -> VectorCache | None   # None: absent, corrupt, other model
def write_vectors(path, model, dim, new: Mapping[bytes, Sequence[float]]) -> bool   # merge under lock
def cosine(q: array, qq: float, v: array) -> float    # qq = dot(q, q); rounded to SCORE_ROUND
def dot(a, b) -> float                                # sequential, index order
```

- File bytes:
  - The first line is `dumps({"count": N, "dim": D, "model": M, "v": 1})` followed by `\n`. `dumps` sorts keys, so the order is count, dim, model, v.
  - Then N records, sorted by key bytes. Each record is the 16-byte key followed by D float32 values, little-endian.
  - Nothing else follows.

- [ ] **Step 1: Failing tests (Python)**

```python
# runtime-py/tests/test_memory_vectors.py
import math
import struct
from pathlib import Path

from bantamkit.memory.vectors import (
    cosine, dot, embed_key, embed_text, model_slug, read_vectors, to_f32, vector_path, write_vectors,
)


def test_embed_text_spells_name_description_keywords():
    assert embed_text("tag-policy", "tags are withheld", ["tag"]) == "tag policy: tags are withheld tag"
    assert embed_text("a-b", "d", []) == "a b: d"


def test_key_is_sha256_prefix():
    assert embed_key("tag policy: tags are withheld until the user rules tag").hex() == (
        "28ed69cf92e0c424fddaaafc1ef560a6"
    )


def test_slug_and_path():
    assert model_slug("nomic-embed-text:latest") == "nomic-embed-text-latest"
    assert vector_path("/x/abc.json", "bge-m3") == Path("/x/abc.vectors-bge-m3.bin")


def test_round_trip_bytes_and_merge(tmp_path: Path):
    p = tmp_path / "h.vectors-m.bin"
    k1, k2 = embed_key("b"), embed_key("a")
    assert write_vectors(p, "m", 2, {k1: [1.0, 0.5]})
    assert write_vectors(p, "m", 2, {k2: [0.25, -1.0]})
    raw = p.read_bytes()
    head, body = raw.split(b"\n", 1)
    assert head == b'{"count":2,"dim":2,"model":"m","v":1}'
    first, second = sorted([k1, k2])
    assert body[:16] == first and len(body) == 2 * (16 + 8)
    c = read_vectors(p, "m")
    assert c is not None and list(c.get(k1)) == [1.0, 0.5] and list(c.get(k2)) == [0.25, -1.0]
    assert read_vectors(p, "other") is None


def test_dim_change_drops_old_records(tmp_path: Path):
    p = tmp_path / "v.bin"
    write_vectors(p, "m", 2, {embed_key("a"): [1.0, 0.0]})
    write_vectors(p, "m", 3, {embed_key("b"): [1.0, 0.0, 0.0]})
    c = read_vectors(p, "m")
    assert c.dim == 3 and c.get(embed_key("a")) is None and len(c) == 1


def test_corrupt_file_reads_as_none(tmp_path: Path):
    p = tmp_path / "v.bin"
    p.write_bytes(b'{"count":3,"dim":2,"model":"m","v":1}\n' + b"\0" * 10)
    assert read_vectors(p, "m") is None


def test_cosine_literal_bits():
    q, v = to_f32([0.6, 0.8, 0.0]), to_f32([1.0, 0.0, 0.0])
    got = cosine(q, dot(q, q), v)
    assert struct.pack(">d", got).hex() == struct.pack(">d", round(q[0] / math.sqrt(dot(q, q)), 9)).hex()
    assert cosine(q, dot(q, q), to_f32([0.0, 0.0, 0.0])) == 0.0
```

- [ ] **Step 2: Failing tests (Node).** `runtime-ts/test/vectors.test.mjs` imports `../dist/memory/vectors.js`, after `import './_sandbox.mjs';`. It asserts the same six behaviours with the same literals: the text `'tag policy: tags are withheld tag'`, the key hex `'28ed69cf92e0c424fddaaafc1ef560a6'`, the slug, the path, the round-trip head bytes `{"count":2,"dim":2,"model":"m","v":1}`, the dim change, the corrupt file and zero-norm cosine `0`.

Run both test files. Expected: FAIL, because the module is not found.

- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/memory/vectors.py
"""The vector cache (#207 §3): a DERIVED index beside the hot index; deleting it loses nothing.

`<index dir>/<sha16(store)>.vectors-<model-slug>.bin`: a `dumps` head line, then records sorted
by key, each a 16-byte key (sha256 of the embedded text) and `dim` float32 LE values. The model
is in the name AND the head, so another model's vectors are never read; an edited fact has a new
key, so its old vector simply misses.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
import os
import re
import sys
from array import array
from collections.abc import Mapping, Sequence
from functools import reduce
from pathlib import Path
from typing import Any

from bantamkit.memory.retrieval import SCORE_ROUND
from bantamkit.storage.hotindex import dumps
from bantamkit.storage.lock import exclusive

CACHE_VERSION = 1
KEY_BYTES = 16
_SLUG = re.compile(r"[^A-Za-z0-9._-]")
_LITTLE = sys.byteorder == "little"


def embed_text(name: str, description: str, keywords: Sequence[str]) -> str:
    text = f"{name.replace('-', ' ')}: {description}"
    return text + (" " + " ".join(keywords) if keywords else "")


def embed_key(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).digest()[:KEY_BYTES]


def model_slug(model: str) -> str:
    return _SLUG.sub("-", model)


def vector_path(index_path: Path | str, model: str) -> Path:
    p = Path(index_path)
    return p.with_name(f"{p.stem}.vectors-{model_slug(model)}.bin")


def to_f32(vec: Sequence[float]) -> array:
    return array("f", vec)


def _f32_bytes(vec: Sequence[float]) -> bytes:
    a = array("f", vec)
    if not _LITTLE:
        a.byteswap()
    return a.tobytes()


class VectorCache:
    def __init__(self, model: str, dim: int, records: dict[bytes, bytes]) -> None:
        self.model, self.dim, self._records = model, dim, records

    def __len__(self) -> int:
        return len(self._records)

    def raw(self) -> dict[bytes, bytes]:
        return self._records

    def get(self, key: bytes) -> array | None:
        b = self._records.get(key)
        if b is None:
            return None
        a = array("f")
        a.frombytes(b)
        if not _LITTLE:
            a.byteswap()
        return a


def read_vectors(path: Path | str, model: str) -> VectorCache | None:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    cut = raw.find(b"\n")
    if cut < 0:
        return None
    try:
        head = json.loads(raw[:cut].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(head, dict) or head.get("v") != CACHE_VERSION or head.get("model") != model:
        return None
    dim, count = head.get("dim"), head.get("count")
    if type(dim) is not int or type(count) is not int or dim < 1 or count < 0:
        return None
    size = KEY_BYTES + 4 * dim
    body = raw[cut + 1 :]
    if len(body) != count * size:
        return None
    records = {
        body[o : o + KEY_BYTES]: body[o + KEY_BYTES : o + size] for o in range(0, len(body), size)
    }
    return VectorCache(model, dim, records)


def write_vectors(
    path: Path | str, model: str, dim: int, new: Mapping[bytes, Sequence[float]]
) -> bool:
    """Merge `new` into the cache under the #204 lock, temp-then-rename. False: not written."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(p) as held:
            if not held:
                return False
            old = read_vectors(p, model)
            records = dict(old.raw()) if old is not None and old.dim == dim else {}
            for key, vec in new.items():
                if len(vec) == dim:
                    records[key] = _f32_bytes(vec)
            head = dumps({"count": len(records), "dim": dim, "model": model, "v": CACHE_VERSION})
            data = head.encode("utf-8") + b"\n" + b"".join(k + records[k] for k in sorted(records))
            tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
            try:
                tmp.write_bytes(data)
                os.replace(tmp, p)
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
    except OSError:
        return False
    return True


_add, _mul = operator.add, operator.mul


def dot(a: Any, b: Any) -> float:
    """Σ a[i]*b[i] from 0.0 in index order -- the port's plain loop, to the bit (never `sum`)."""
    return reduce(_add, map(_mul, a, b), 0.0)


def cosine(q: Any, qq: float, v: Any) -> float:
    vv = dot(v, v)
    if qq == 0.0 or vv == 0.0:
        return 0.0
    return round(dot(q, v) / (math.sqrt(qq) * math.sqrt(vv)), SCORE_ROUND)
```

Note: `"surrogatepass"` keeps a fact text with a lone surrogate hashable. Node's `createHash().update(str, 'utf8')` writes U+FFFD for a lone surrogate, so the two keys differ on such a text. Do not paper over that. Add a `recall-embed` case for a lone-surrogate description:
  - expected: both sides treat the fact as uncovered and fall back to BM25, which is the same visible answer;
  - if they disagree on the fallback, change Python to `encode("utf-8", "replace")` with `"�"` substitution to match Node, and pin it with a literal.

- [ ] **Step 4: Implement (Node).** `runtime-ts/src/memory/vectors.ts` is the same module:
  - `embedKey(text)` returns `createHash('sha256').update(text, 'utf8').digest().subarray(0, 16).toString('hex')`.
  - Records are `Map<string, Buffer>`, keyed by hex.
  - `get(key)` copies the record into a fresh `ArrayBuffer` and returns a `Float32Array` view. Every supported Node target is little-endian; assert `os.endianness() === 'LE'` once at module load, and on `BE` return `null` from `readVectors`, so the cache is "absent" and recall falls back.
  - Sort by `Buffer.compare` over the key bytes.
  - The head is `dumpIndex({count, dim, model, v: 1})`.
  - Writes go through `exclusive(path, (held) => { ... })` with the temp name `${name}.${process.pid}.tmp` and `renameSync`.
  - `dot` is a plain `for` loop from `0`, `s += a[i] * b[i]`.
  - `cosine` returns `pyRound9(dot(q, v) / (Math.sqrt(qq) * Math.sqrt(vv)))` and `0` on a zero norm.

- [ ] **Step 5: The cache conformance cases** (`recall-embed.mjs` + `embed_ref.py`)

`embed_ref.py` protocol (stdin JSON → stdout JSON; strings that must survive travel as base64):

```
{"op": "write", "path": p, "model": m, "dim": d, "records": [[b64 text, [floats]], ...]}  -> {"ok": bool}
{"op": "read",  "path": p, "model": m, "keys": [b64 text, ...]} -> {"vectors": [[hex32 f32 bits...] | null, ...]}
{"op": "cosine", "q": [floats], "rows": [[floats], ...]} -> {"bits": [hex16, ...]}
{"op": "text_key", "facts": [[b64 name, b64 desc, [b64 kw...]], ...]} -> {"keys": [hex, ...]}
```

Cases, each `kind: 'json'` unless noted:
  1. `text_key` over 12 facts (ASCII, Thai, a hyphenated name, empty keywords, emoji, NFKC-sensitive). The result must equal Node's `embedKey(embedText(...))`.
  2. **Python writes, Node reads:** the bytes Node reads back equal what Python wrote, compared as float32 bits.
  3. **Node writes, Python reads:** the same, the other way.
  4. **Both writers produce byte-identical files** for the same records (`kind: 'bytes'`).
  5. The `cosine` bits over 20 random-but-seeded rows (dims 8 and 1024). Generate the seed rows on the Node side with a fixed LCG `x = (x * 1103515245 + 12345) % 2**31` and pass them to Python.
  6. A changed description makes the old key miss on both sides (`get` → null).
  7. A changed model name reads as absent on both sides.
  8. **Per-side literal:** the key hex of `embedText('tag-policy', 'tags are withheld until the user rules', ['tag'])` is `28ed69cf92e0c424fddaaafc1ef560a6`, through `literalCases`.

Copy the `b64`/`unb64`/`REF` preamble and `literalCases` from `recall-gate.mjs:52-70` and `:469`.

- [ ] **Step 6: Prove it guards (rsync copy)**
  - **M1a:** Node sorts records by hex string descending. Expect red on case 4 only.
  - **M1b:** Python `dot` uses `sum(map(_mul, a, b))`. Expect red on case 5 for the dim-1024 rows (compensated summation). If no row reddens, add rows until one does, and record which.
  - **M1c (symmetric):** both sides drop `": "` from `embed_text`. Expect red only on the literal of case 8.
  - Record the red counts in the note.

- [ ] **Step 7: Gates and commit**

```bash
git add runtime-py/src/bantamkit/memory/vectors.py runtime-ts/src/memory/vectors.ts \
  runtime-py/tests/test_memory_vectors.py runtime-ts/test/vectors.test.mjs \
  tools/conformance/suites/recall-embed.mjs tools/conformance/ref/embed_ref.py && git diff --cached --stat
git commit -m "feat(memory): derived vector cache, float32 LE, keyed by embedded text, read and written by both runtimes (#207 §3)"
```

---

### Task 2: `OllamaScorer` path — config, loopback rule, client, `CosineScorer`, fallback, stub ollama

**Files:**
- Create: `runtime-py/src/bantamkit/memory/embed.py`, `runtime-ts/src/memory/embed.ts`
- Create: `tools/conformance/lib/ollama-stub.mjs`
- Create: `runtime-py/tests/test_memory_embed.py`, `runtime-ts/test/embed.test.mjs`
- Modify: `runtime-py/src/bantamkit/memory/vectors.py`, `runtime-ts/src/memory/vectors.ts` (`row_vectors`, `CosineScorer`)
- Modify: `store.py` / `store.ts` (`pool_of(..., full=False)`, `MemoryStore.pool(..., full=False)`)
- Modify: `native.py` / `native.ts` (`NativeStore.pool(..., full=False)`)
- Modify: `component.py` / `component.ts` (`Memory.embed`, `prepare`, `fallbacks`, `recall_outcome(..., scorer=None)`, `_pooled`, `RecallOutcome.scorer`/`.fallback`, `layered_for_eval(engine="embed")`, `inject_candidates`, `rank_all`)
- Modify: `hookadapter.py:1289`, `hookadapter.ts:1380-1405` (prepare before recall; Node `userPromptSubmit` becomes `async`)
- Modify: `mcpserver.py:1527-1529`, `mcp/server.ts` (`memory_recall` prepares; Node prepares in the async handler before `runTool` and passes the scorer in)
- Modify: `tools/conformance/suites/recall-embed.mjs`, `tools/conformance/ref/embed_ref.py`

**Interfaces:**
- Consumes: Task 0's `Scorer`, `BM25F`, `Bm25fScorer`, `EMBED_GATE`, and `pick_hits(..., scorer, rows)`. Task 1's `vectors.*`.
- Produces (Python `bantamkit.memory.embed`; Node camelCase, async where marked):

```python
EMBED_ENV = "BANTAMKIT_EMBED"; MODEL_ENV = "BANTAMKIT_EMBED_MODEL"; HOST_ENV = "OLLAMA_HOST"
DEFAULT_MODEL = "bge-m3"; DEFAULT_HOST = "http://localhost:11434"
QUERY_TIMEOUT_MS = 150; SAVE_TIMEOUT_MS = 2000; FILL_TIMEOUT_MS = 30000
FILL_BATCH = 32; QUERY_MAX_CHARS = 2000; KEEP_ALIVE = "30m"
REASONS = ("unreachable", "timeout", "no-model", "coverage", "refused-host")

@dataclass(frozen=True)
class EmbedConfig:
    on: bool             # BANTAMKIT_EMBED == "ollama" and the host is loopback
    model: str
    base: str | None     # "http://127.0.0.1:11434" — the normalised loopback base, None when refused/off
    refused: str | None  # the raw OLLAMA_HOST that was refused
    unknown: str | None  # a BANTAMKIT_EMBED value other than "" / "ollama"
    def configured(self) -> bool: return self.on or self.refused is not None

def parse_host(raw: str) -> tuple[str, str] | None   # (base, host) or None (refused / garbled)
def is_loopback(host: str) -> bool
def refused_host_sentence(raw: str) -> str
def unknown_value_sentence(value: str) -> str
def config_from_env(env: Mapping[str, str] = os.environ) -> EmbedConfig
class EmbedFailure(Exception): reason: str           # one of REASONS
def embed_texts(config, texts: Sequence[str], timeout_ms: int) -> list[list[float]]   # Node: async
def prepare(config, query: str) -> Scorer                                              # Node: async
```

- Produces (`vectors`): `class CosineScorer(qvec: array, model: str)`, with `dense=True`, `label()="ollama <model>"` and `floor()=retrieval.EMBED_GATE` (a call-time read), and `row_vectors(store, pool, model) -> list[array | None] | None`.
- Produces (`component`):
  - `Memory.embed: EmbedConfig`, `Memory.fallbacks: dict[str, int]` (keys `REASONS`), `Memory.prepare(query) -> Scorer` (Node `async prepare(query): Promise<Scorer>`).
  - `recall_outcome(..., scorer: Scorer | None = None)`. Node puts `scorer: Scorer | null = null` as the 7th positional parameter of `recallOutcome`.
  - `RecallOutcome.scorer: str = "bm25f"` and `RecallOutcome.fallback: str | None = None`.

- [ ] **Step 1: The stub ollama** (`tools/conformance/lib/ollama-stub.mjs`, a child process)

```js
#!/usr/bin/env node
// Deterministic loopback ollama for the recall-embed suite (#207 §5). A CHILD process: the
// harness's runPython is spawnSync, which would starve an in-process listener.
//   node ollama-stub.mjs --models bge-m3[,other] [--delay-ms 300] [--dim 8] [--log <file>]
// Prints "listening <port>\n" on stdout once bound to 127.0.0.1:0. POST /api/embed
// {model, input:[...]} -> {model, embeddings:[...]}; an unknown model -> 404 like ollama.
// The vector of a text: sha256(utf8) bytes b, raw[i] = (b[i] - 127.5) / 127.5 for i < dim,
// divided by its sequential L2 norm. --log appends each request body as one JSON line.
import { createHash } from 'node:crypto';
import { appendFileSync } from 'node:fs';
import { createServer } from 'node:http';

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const models = new Set(arg('--models', 'bge-m3').split(','));
const delay = Number(arg('--delay-ms', '0'));
const dim = Number(arg('--dim', '8'));
const log = arg('--log', null);

export function stubVector(text, d = 8) {
  const b = createHash('sha256').update(text, 'utf8').digest();
  const raw = [];
  for (let i = 0; i < d; i += 1) raw.push((b[i % 32] - 127.5) / 127.5);
  let n = 0;
  for (const x of raw) n += x * x;
  n = Math.sqrt(n);
  return raw.map((x) => x / n);
}

if (process.argv[1] && process.argv[1].endsWith('ollama-stub.mjs')) {
  createServer((req, res) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      if (log) appendFileSync(log, `${body}\n`);
      const send = () => {
        let msg;
        try { msg = JSON.parse(body); } catch { res.writeHead(400).end('{}'); return; }
        if (req.url !== '/api/embed' || req.method !== 'POST') { res.writeHead(404).end('{}'); return; }
        if (!models.has(msg.model)) {
          res.writeHead(404, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: `model "${msg.model}" not found, try pulling it first` }));
          return;
        }
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ model: msg.model, embeddings: msg.input.map((t) => stubVector(t, dim)) }));
      };
      if (delay > 0) setTimeout(send, delay); else send();
    });
  }).listen(0, '127.0.0.1', function () { process.stdout.write(`listening ${this.address().port}\n`); });
}
```

The suite starts each stub with `spawn(process.execPath, [STUB, ...])`, reads the port from the first stdout line, and kills it in a `finally`. That keeps `--all` self-contained. A stub crash fails the suite with a named case, not a stack trace.

- [ ] **Step 2: Failing unit tests**

```python
# runtime-py/tests/test_memory_embed.py
import pytest

from bantamkit.memory import embed
from bantamkit.memory.embed import config_from_env, parse_host, refused_host_sentence


@pytest.mark.parametrize("raw,base", [
    ("", "http://localhost:11434"),
    ("localhost", "http://localhost:11434"),
    ("127.0.0.1:9", "http://127.0.0.1:9"),
    ("http://127.255.0.1:11434/", "http://127.255.0.1:11434"),
    ("[::1]:8080", "http://[::1]:8080"),
    ("::1", "http://[::1]:11434"),
    ("HTTP://LOCALHOST:1", "http://localhost:1"),
    ("0.0.0.0", "http://127.0.0.1:11434"),
    ("0.0.0.0:9", "http://127.0.0.1:9"),
    ("[::]:8080", "http://[::1]:8080"),
])
def test_loopback_hosts_are_accepted(raw, base):
    assert parse_host(raw)[0] == base


@pytest.mark.parametrize("raw", [
    "10.0.0.1", "example.com", "128.0.0.1", "127.0.0", "127.0.0.256",
    "localhost.evil.com", "[::2]", "ftp://localhost", "localhost:abc", "localhost:0", "localhost:70000",
    "127.0.0.1:１２", "0:0:0:0:0:0:0:1",
])
def test_other_hosts_are_refused(raw):
    assert parse_host(raw) is None


def test_switch_and_refusal():
    assert not config_from_env({}).on
    c = config_from_env({"BANTAMKIT_EMBED": "ollama", "OLLAMA_HOST": "10.0.0.1"})
    assert not c.on and c.refused == "10.0.0.1" and c.configured()
    assert config_from_env({"BANTAMKIT_EMBED": "yes"}).unknown == "yes"
    assert config_from_env({"BANTAMKIT_EMBED": "ollama"}).model == "bge-m3"
    assert refused_host_sentence("10.0.0.1") == (
        'OLLAMA_HOST "10.0.0.1" is not a loopback address; embedding is off, because fact text '
        "must not leave this machine. Use localhost, 127.0.0.1 or ::1."
    )


def test_prepare_off_is_the_shared_bm25f():
    from bantamkit.memory.retrieval import BM25F
    assert embed.prepare(config_from_env({}), "q") is BM25F
```

`runtime-ts/test/embed.test.mjs` carries the same tables and the same sentence literal.

- [ ] **Step 3: Implement `embed.py`**

```python
"""The opt-in ollama backend (#207 D2, D7): env config, the loopback rule, one HTTP client."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from bantamkit.memory.retrieval import BM25F, Bm25fScorer, Scorer

# ... the constants, EmbedConfig and EmbedFailure exactly as listed under Interfaces ...


def forced_on(env: Mapping[str, str] = os.environ) -> EmbedConfig:
    """The config the operator CLI and the eval use: the switch treated as on, the host rule kept."""
    return config_from_env({**env, EMBED_ENV: "ollama"})


def is_loopback(host: str) -> bool:
    if host in ("localhost", "::1"):
        return True
    parts = host.split(".")
    if len(parts) != 4 or not all(p and len(p) <= 3 and all("0" <= c <= "9" for c in p) for p in parts):
        return False
    return all(int(p) <= 255 for p in parts) and int(parts[0]) == 127


def parse_host(raw: str) -> tuple[str, str] | None:
    """OLLAMA_HOST as ollama reads it, accepted only when loopback (#207 D7). Hand-written, not
    `urlsplit`/WHATWG `URL`: those normalise `127.1` and friends differently between runtimes."""
    s = raw.strip() or DEFAULT_HOST
    scheme = "http"
    if "://" in s:
        scheme, s = s.split("://", 1)
        scheme = scheme.lower()
        if scheme not in ("http", "https"):
            return None
    s = s.split("/", 1)[0]
    if s.startswith("["):
        end = s.find("]")
        if end < 0:
            return None
        host, rest = s[1:end], s[end + 1 :]
        if rest and not rest.startswith(":"):
            return None
        port = rest[1:]
    elif s.count(":") == 1:
        host, port = s.split(":")
    else:
        host, port = s, ""  # no port, or a bare IPv6 literal
    port = port or "11434"
    if not all("0" <= c <= "9" for c in port) or not 1 <= int(port) <= 65535:
        return None
    host = host.lower()
    if not is_loopback(host):
        return None
    netloc = f"[{host}]" if ":" in host else host
    return f"{scheme}://{netloc}:{int(port)}", host


def refused_host_sentence(raw: str) -> str:
    return (
        f"OLLAMA_HOST {json.dumps(raw, ensure_ascii=False)} is not a loopback address; embedding is "
        "off, because fact text must not leave this machine. Use localhost, 127.0.0.1 or ::1."
    )


def unknown_value_sentence(value: str) -> str:
    return (
        f"BANTAMKIT_EMBED {json.dumps(value, ensure_ascii=False)} is not a backend; embedding is "
        "off (set it to ollama, or unset it)."
    )


def config_from_env(env: Mapping[str, str] = os.environ) -> EmbedConfig:
    value = env.get(EMBED_ENV, "")
    model = env.get(MODEL_ENV, "") or DEFAULT_MODEL
    unknown = value if value not in ("", "ollama") else None
    if value != "ollama":
        return EmbedConfig(False, model, None, None, unknown)
    raw = env.get(HOST_ENV, "")
    got = parse_host(raw)
    if got is None:
        return EmbedConfig(False, model, None, raw, None)
    return EmbedConfig(True, model, got[0], None, None)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(url: str, body: bytes, timeout_s: float) -> bytes:
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with _OPENER.open(req, timeout=timeout_s) as r:
        return r.read()


def embed_texts(config: EmbedConfig, texts: Sequence[str], timeout_ms: int) -> list[list[float]]:
    """One POST /api/embed under a TOTAL deadline (the socket timeout alone is per operation)."""
    if not config.on or config.base is None:
        raise EmbedFailure("refused-host" if config.refused is not None else "unreachable")
    body = json.dumps({"model": config.model, "input": list(texts), "keep_alive": KEEP_ALIVE}).encode()
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["raw"] = _post(f"{config.base}/api/embed", body, timeout_ms / 1000)
        except BaseException as e:  # noqa: BLE001 - classified below, on the caller's thread
            box["error"] = e

    t = threading.Thread(target=run, name="bantamkit-embed", daemon=True)
    t.start()
    t.join(timeout_ms / 1000)
    if t.is_alive():
        raise EmbedFailure("timeout")
    e = box.get("error")
    if isinstance(e, urllib.error.HTTPError):
        raise EmbedFailure("no-model" if e.code == 404 else "unreachable")
    if isinstance(e, TimeoutError) or (
        isinstance(e, urllib.error.URLError) and isinstance(e.reason, TimeoutError)
    ):
        raise EmbedFailure("timeout")
    if e is not None:
        raise EmbedFailure("unreachable")
    try:
        data = json.loads(box["raw"])
        vecs = data["embeddings"]
        ok = (
            isinstance(vecs, list) and len(vecs) == len(texts) and vecs
            and all(isinstance(v, list) and len(v) == len(vecs[0]) > 0 for v in vecs)
            and all(type(x) in (int, float) for v in vecs for x in v)
        )
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise EmbedFailure("unreachable")
    return [[float(x) for x in v] for v in vecs]


def prepare(config: EmbedConfig, query: str) -> Scorer:
    if config.refused is not None:
        return Bm25fScorer("refused-host")
    if not config.on:
        return BM25F
    try:
        [vec] = embed_texts(config, [query[:QUERY_MAX_CHARS]], QUERY_TIMEOUT_MS)
    except EmbedFailure as e:
        return Bm25fScorer(e.reason)
    from bantamkit.memory.vectors import CosineScorer, to_f32
    return CosineScorer(to_f32(vec), config.model)
```

`QUERY_MAX_CHARS` counts **code points** on both sides. Node cuts with `Array.from(query).slice(0, QUERY_MAX_CHARS).join('')`. BM25 still sees the whole prompt.

- [ ] **Step 4: Implement `embed.ts`.**
  - The same functions and the same sentences.
  - `embedTexts` is `async`. It sends `POST ${base}/api/embed` with `http.request({host, port, path: '/api/embed', method: 'POST', agent: false, headers: {'Content-Type': 'application/json', 'Content-Length': <byte length>}})` from `node:http`, body `JSON.stringify({model, input, keep_alive: KEEP_ALIVE})`. **Never global `fetch`**: on Node ≥ 24, `NODE_USE_ENV_PROXY=1` makes `fetch` honour `HTTP_PROXY`, which would carry fact text off the machine; `node:http` with `agent: false` never consults a proxy (the Python side's `ProxyHandler({})` is the same rule).
  - One total-deadline timer of `timeoutMs` covers connect, send and the whole response body; when it fires it calls `req.destroy()` with an error whose `name` is `'TimeoutError'`, and the timer is cleared on every exit path.
  - Error mapping:
    - The `'TimeoutError'` above becomes `timeout`. Any other request or socket error becomes `unreachable`.
    - `statusCode === 404` becomes `no-model`; any other non-2xx becomes `unreachable`.
    - The body is collected as Buffers, decoded UTF-8 and `JSON.parse`d; a parse error is `unreachable`.
  - The shape checks are those of Python. The client lives in `memory/embed.ts`; check that `runtime-ts/test/selfupdate.test.mjs:676` ("cli.ts is the ONLY module in src/ that reaches this one") still passes, since it pins imports of `selfupdate.js`, not `fetch`.

- [ ] **Step 5: `CosineScorer` and `row_vectors` (`vectors.py`; the Node port is the same)**

```python
class CosineScorer:
    """Dense cosine over every pooled row (#207 D4). `column` is None -- and `fallback` becomes
    "coverage" -- unless every row has a vector of the query's dimension (D6)."""

    dense = True

    def __init__(self, qvec: array, model: str) -> None:
        self.qvec, self.model, self.fallback = qvec, model, None
        self._qq = dot(qvec, qvec)

    def label(self) -> str:
        return f"ollama {self.model}"

    def used(self) -> str:
        return "bm25f" if self.fallback is not None else self.label()

    def floor(self) -> float:
        from bantamkit.memory import retrieval
        return retrieval.EMBED_GATE  # a call-time read, as tune_embed.py rebinds it

    def column(self, cols: Any, vecs: list[Any] | None) -> list[float] | None:
        dim = len(self.qvec)
        if vecs is None or any(v is None or len(v) != dim for v in vecs):
            self.fallback = "coverage"
            return None
        q, qq = self.qvec, self._qq
        return [cosine(q, qq, v) for v in vecs]


def _pool_texts(store: Any, pool: Any) -> list[str] | None:
    """The embedded text of each pooled row: the parsed facts, else the index's docs (line 2)."""
    if pool.facts is not None:
        return [embed_text(str(f.name), str(f.description), list(f.keywords or ())) for f in pool.facts]
    try:
        docs = store.index().docs_unchecked()
    except (OSError, ValueError):
        return None
    out = []
    for name in pool.names:
        d = docs.get(name)
        if not isinstance(d, dict):
            return None
        desc, kw = d.get("description"), d.get("keywords")
        if not isinstance(desc, str) or not isinstance(kw, list) or not all(isinstance(k, str) for k in kw):
            return None
        out.append(embed_text(name, desc, kw))
    return out


def row_vectors(store: Any, pool: Any, model: str) -> list[array | None] | None:
    texts = _pool_texts(store, pool)
    if texts is None:
        return None
    cache = read_vectors(vector_path(store.index().path, model), model)
    if cache is None:
        return [None] * len(texts) if texts else []
    return [cache.get(embed_key(t)) for t in texts]
```

- [ ] **Step 6: Full pools, and the scorer wired into `Memory`**
  - `pool_of(facts, q, full=False)`. With `full=True` every fact is a row, including those whose `mine` is empty, still sorted by name. The BM25 statistics `n`, `total` and `df` do not change, so BM25 over a full pool admits exactly what it admits over a partial one: an empty row scores 0, and `rank_columns` admits only `x > 0`.
  - `MemoryStore.pool(q, skipped, full=False)` passes `full` to `pool_of` on the files path only; the index path is already full. `NativeStore.pool(q, skipped, shadow, full=False)` does the same on its two `pool_of` calls.
  - In `component.py` `Memory.__init__` (and Node's `constructor`, `component.ts:360`):
    - `self.embed = embed.config_from_env()`.
    - `self.fallbacks = dict.fromkeys(embed.REASONS, 0)`.
    - If `self.embed.refused` is set, `self.fallbacks["refused-host"] = 1`. "Refused once at startup" means once per process.
    - `def prepare(self, query): return embed.prepare(self.embed, query)`.
  - In `_pooled(query, budget, min_ratio, context=None, scorer=BM25F)`:
    - Call `store.pool(q, skipped=left_out, full=scorer.dense)` (native gets `shadow` as today) and `repool` with the same `full`.
    - `rows = (lambda i, p: vectors.row_vectors(stores[i], p, scorer.model)) if scorer.dense else None`.
    - `pick_hits(..., context=..., scorer=scorer, rows=rows)`.
  - In `recall_outcome(..., context=None, scorer=None)`:
    - `scorer = scorer or BM25F`, passed to `_pooled`.
    - Every returned `RecallOutcome` (built with `dataclasses.replace` at the two return sites, and at the `_lookup_by_name` early return) gets `scorer=scorer.used()` and `fallback=scorer.fallback`.
    - When `scorer.fallback` is set and is not `"refused-host"`, `self.fallbacks[scorer.fallback] += 1`.
  - `inject_candidates`/`rank_all` pass `self.prepare(prompt)` as the scorer.
  - `layered_for_eval(..., engine)` accepts `"embed"`: the memory it builds sets `mem.embed = embed.forced_on()`. It refuses an `"embed"` engine whose host is refused, with `ValueError(refused_host_sentence(raw))`.
- [ ] **Step 7: Callers**
  - Python hook (`hookadapter.py:1289`): `o = m.recall_outcome(prompt, 3, stamp=False, context=touch, scorer=m.prepare(prompt))`.
  - Node hook: `userPromptSubmit` becomes `async function userPromptSubmit(run, input): Promise<void>`. `const scorer = await m.prepare(prompt);` comes before `ask`, and `ask` passes it as the 7th argument. `runHook`'s `case 'UserPromptSubmit': return userPromptSubmit(run, input);` already sits in an async function.
  - `memory_recall`:
    - Python: `memory.recall_outcome(query, k, ..., scorer=memory.prepare(query))` on the query arm only; the `file` arm is unchanged.
    - Node: in the async handler at `server.ts:1306`, compute `const scorer = name === 'memory_recall' && <query arm> ? await memory.prepare(query) : null` and add a `scorer` parameter to `runTool` that the `memory_recall` case passes into `recallOutcome`. Off-path this is `BM25F` with no await of any network.

- [ ] **Step 8: The scorer conformance cases** (append to `recall-embed.mjs`; ref ops `layered_recall` and `host`)
  - Bed: one project store with 4 facts, all `type: project`:
    - `memory-budget` / `ดัชนีความจำเกินงบ` / `[budget]`
    - `release-notes` / `how the release pipeline publishes to npm` / `[publish, npm]`
    - `tag-policy` / `tags are withheld until the user rules` / `[tag]`
    - `thai-deploy` / `ขั้นตอน deploy ขึ้นเซิร์ฟเวอร์` / `[]`
  - Query: `ช่วยดู release ให้หน่อย`.
  - Each side fills its own copy's cache through its own `embed_texts` against stub A (`--models bge-m3 --dim 8`), then recalls with `BANTAMKIT_EMBED=ollama`, `OLLAMA_HOST=http://127.0.0.1:<A>`, and the `HOME`/`BANTAMKIT_INDEX_DIR` of its own bed.
  - Cases:
    1. **Ranking order** over the mixed Thai/English pool: the names returned, plus `scorer`/`fallback`, compared Py vs Node.
    2. **Per-side literal** (case 1's answer): `['memory-budget', 'tag-policy']`, `scorer: 'ollama bge-m3'`, `fallback: null`. Computed with the stub's vector rule and the spec's text rule. The cosines are 0.395150724 for `memory-budget`, 0.099080494 for `tag-policy`, −0.371848625 for `thai-deploy` and −0.480147985 for `release-notes`; at `EMBED_GATE = 0.0` only the two positive cosines are admitted.
    3. **Gate cut:** with `retrieval.EMBED_GATE` overridden to `0.2` on both sides (Python by setattr in the ref, Node by an exported `setEmbedGate` test seam mirroring `setContextWeight`, `retrieval.ts:356`), the answer is `['memory-budget']` on both.
    4. **Coverage short:** delete one record from the cache (`write` op over all but `thai-deploy`). The answer equals the BM25 answer of the same bed with embedding off, **byte for byte** (`kind: 'string'` over the joined reply), with `fallback: 'coverage'`. The BM25 answer is `['release-notes']`.
    5. **Timeout:** stub B, `--delay-ms 300`. The answer equals case 4's BM25 reply byte for byte, with `fallback: 'timeout'`.
    6. **Unreachable:** a port taken from a stub that was then killed. The answer is BM25, with `fallback: 'unreachable'`.
    7. **No model:** `BANTAMKIT_EMBED_MODEL=nope` against stub A. The answer is BM25, with `fallback: 'no-model'`.
    8. **Refused host:** the `host` op over the 23 strings of the Step 2 tables, returning `[base | null]` per string. The table is compared Py vs Node, plus the `refused_host_sentence('10.0.0.1')` bytes (`kind: 'string'`).
    9. **Refusal bit, unruled:** for `OLLAMA_HOST=10.0.0.1`, both sides report `on: false, refused: '10.0.0.1'`, and the recall's `fallback` is `'refused-host'`.
    10. **Request bytes:** stub A's `--log` file. Each side's query request, parsed as JSON, must be equal. That covers the `input` cut at 2,000 code points for a prompt of 1,999 ASCII characters plus 3 astral emoji, the `model`, and `keep_alive: '30m'`.
    11. **Lone-surrogate description** (Task 1 Step 3): the same visible answer on both sides.
    12. **Py-written cache, Node ranks:** Python fills the cache and Node recalls from that same index dir, and the reverse. Both rankings equal case 1.

- [ ] **Step 9: Prove it guards (rsync copy)**
  - **M2a:** Node `parseHost` maps `0.0.0.0` to `http://0.0.0.0:11434` instead of `http://127.0.0.1:11434`. Expect red on case 8 only.
  - **M2b:** Python `prepare` cuts at `QUERY_MAX_CHARS` UTF-16 units: `query.encode('utf-16-le')[:4000].decode('utf-16-le', 'ignore')`. Expect red on case 10.
  - **M2c:** Node `CosineScorer.column` returns cosines of the available rows instead of `null` on a missing vector. Expect red on case 4.
  - **M2d:** Python maps HTTP 404 to `unreachable`. Expect red on case 7.
  - **M2e (symmetric):** both sides drop the `scorer.dense` guard, so the term-hit early return fires. Expect red only on case 2's literal, because no fact shares a token with the query except `release-notes`.
  - Record the red counts.

- [ ] **Step 10: Gates and commit**

```bash
git add runtime-py/src/bantamkit/memory/embed.py runtime-ts/src/memory/embed.ts \
  runtime-py/src/bantamkit/memory/vectors.py runtime-ts/src/memory/vectors.ts \
  runtime-py/src/bantamkit/memory/store.py runtime-ts/src/memory/store.ts \
  runtime-py/src/bantamkit/memory/native.py runtime-ts/src/memory/native.ts \
  runtime-py/src/bantamkit/memory/component.py runtime-ts/src/memory/component.ts \
  runtime-py/src/bantamkit/memory/retrieval.py runtime-ts/src/memory/retrieval.ts \
  runtime-py/src/bantamkit/hookadapter.py runtime-ts/src/hookadapter.ts \
  runtime-py/src/bantamkit/mcpserver.py runtime-ts/src/mcp/server.ts \
  runtime-py/tests/test_memory_embed.py runtime-ts/test/embed.test.mjs \
  tools/conformance/lib/ollama-stub.mjs tools/conformance/suites/recall-embed.mjs \
  tools/conformance/ref/embed_ref.py && git diff --cached --stat
git commit -m "feat(memory): opt-in ollama scorer — loopback-only, dense cosine over every layer, whole-recall BM25 fallback (#207 D2-D7)"
```

---

### Task 3: Fill paths — save and read-repair embed, `memory embed` CLI, start-up fill

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/vectors.py`, `runtime-ts/src/memory/vectors.ts` (`fill`, `FillResult`, `coverage`)
- Modify: `component.py` (`save_outcome` `:406-489`, `_repair` `:875`), `component.ts` (`saveOutcome` `:475`, the repair site; `pendingEmbeds`, `flushEmbeds`)
- Modify: `runtime-ts/src/mcp/server.ts` (await `memory.flushEmbeds()` after a `memory_save` or `memory_recall` call)
- Modify: `runtime-py/src/bantamkit/memory/__main__.py` (`embed` subparser, `_cmd_embed`), `runtime-ts/src/memory/cli.ts` (`PARSER` entry, async `main`)
- Modify: `runtime-py/src/bantamkit/mcpserver.py:2996` and `runtime-ts/src/cli.ts:907` (start-up fill)
- Modify: `tools/conformance/suites/recall-embed.mjs`, `embed_ref.py`, `tools/conformance/suites/memorycli.mjs` (`embed -h`)
- Test: `runtime-py/tests/test_memory_vectors.py`, `runtime-ts/test/vectors.test.mjs`, `runtime-ts/test/memory-cli.test.mjs`, `runtime-py/tests/test_memory.py`

**Interfaces:**
- Consumes: Task 2's `EmbedConfig`, `embed_texts`, `EmbedFailure`, `FILL_BATCH`, `FILL_TIMEOUT_MS`, `SAVE_TIMEOUT_MS`. Task 1's cache.
- Produces:
  - `@dataclass FillResult(embedded: int, already: int, failed: int, abort: str | None)`.
  - `fill(memory, config, timeout_ms=FILL_TIMEOUT_MS) -> FillResult` (Node `async fill(...)`).
  - `coverage(memory, model) -> tuple[int, int]` (have, total).
  - `Memory.vector_coverage() -> tuple[int, int]`.
  - Node `Memory.flushEmbeds(): Promise<void>`.

- [ ] **Step 1: Failing tests**
  - `fill` over a store of 70 facts against a stub, with the stub's `--log`. The result is `embedded 70, already 0, failed 0`. The log holds 3 requests with 32, 32 and 6 inputs. A second run gives `embedded 0, already 70, failed 0`.
  - After `save_outcome` with embedding on (stub up), the saved fact's key is in the cache. With the stub down, the reply is still `saved '<name>'`, and the vector is missing.
  - Python `_cmd_embed` against a dead port prints the unreachable sentence to stderr and returns 2.

- [ ] **Step 2: Implement `fill` (Python; the Node port is the same, async)**

```python
def fill(memory: Any, config: Any, timeout_ms: int | None = None) -> FillResult:
    """Embed every fact the cache lacks, per layer, in batches of FILL_BATCH; each batch is
    written as it lands, so an interrupted fill keeps what it got (#207 §3)."""
    from bantamkit.memory.embed import FILL_BATCH, FILL_TIMEOUT_MS, EmbedFailure, embed_texts

    timeout_ms = FILL_TIMEOUT_MS if timeout_ms is None else timeout_ms
    result = FillResult(0, 0, 0, None)
    for _label, store, _w in memory.layer_stores():
        try:
            facts = store.candidates()
        except (OSError, ValueError):
            continue
        path = vector_path(store.index().path, config.model)
        cache = read_vectors(path, config.model)
        want: dict[bytes, str] = {}
        for f in facts:
            t = embed_text(str(f.name), str(f.description), list(f.keywords or ()))
            k = embed_key(t)
            if cache is not None and cache.get(k) is not None:
                result.already += 1
            elif k not in want:
                want[k] = t
        keys = list(want)
        for i in range(0, len(keys), FILL_BATCH):
            batch = keys[i : i + FILL_BATCH]
            try:
                vecs = embed_texts(config, [want[k] for k in batch], timeout_ms)
            except EmbedFailure as e:
                if e.reason in ("unreachable", "no-model", "refused-host"):
                    result.abort = e.reason
                    result.failed += len(keys) - i
                    return result
                result.failed += len(batch)
                continue
            if write_vectors(path, config.model, len(vecs[0]), dict(zip(batch, vecs, strict=True))):
                result.embedded += len(batch)
            else:
                result.failed += len(batch)
    return result
```

`coverage(memory, model)` walks the same layers and counts the facts whose key is in that layer's cache. It is sync on both sides, because it only reads files.

- [ ] **Step 3: Save and read-repair.**
  - Python `save_outcome`: after the `usage().append(...)` at `:486`, add `if self.embed.on: self._embed_now(self.store, [(result.name, description, list(keywords or ()))])`.
  - `_repair`: for each fact it actually rewrote, add `self._embed_now(store, [...])`.
  - `_embed_now(store, rows)` calls `embed_texts(self.embed, texts, SAVE_TIMEOUT_MS)` and writes with `write_vectors`. It catches `EmbedFailure` and `OSError` and does nothing on failure, because the save already succeeded (#123).
  - Node: `saveOutcome` and the repair site push `{ store, rows }` onto `this.pendingEmbeds`. `async flushEmbeds()` drains it with the same calls. `server.ts`'s async handler calls `await memory.flushEmbeds()` after `runTool` returns for `memory_save` and `memory_recall`, so on both runtimes the vector exists when the tool reply is sent.
- [ ] **Step 4: The CLI.**
  - Python `_parse_args` adds, after `restore`:

```python
    common(subs.add_parser(
        "embed", help="embed every fact the vector cache lacks (ollama, BANTAMKIT_EMBED_MODEL)"
    ))
```

  - `_cmd_embed(args)`: `--store` builds `Memory(store=...)`; otherwise it builds `Memory.layered(start=args.start, index_budget=args.budget, native=native_memory_dir(str(Path.home())))`. The config is `embed.forced_on()`. The CLI fills whether or not the switch is on, so an operator can fill before turning embedding on.
  - Outcomes:
    - On a refused host: stderr `f"{_PROG} embed: {refused_host_sentence(raw)}"`, exit 2.
    - Otherwise `fill`, then stdout `embedded N, already M, failed K`.
    - On `abort == "unreachable"`: stderr `f"{_PROG} embed: ollama did not answer at {base}. Start it with `ollama serve`, or point OLLAMA_HOST at it."`, exit 2.
    - On `abort == "no-model"`: `f"{_PROG} embed: ollama has no model {model}. Pull it with `ollama pull {model}`."`, exit 2.
    - Else exit 0.
  - `_COMMANDS` cannot hold it, because it takes no store. Dispatch `embed` before `_open` in `main`.
  - Node: add `{ name: 'embed', help: '<same>', parser: sub('embed', common()) }` to `PARSER.subcommands` after `restore`. `main` becomes `async`; the top-level `try` becomes `process.exitCode = await main(...)`. Every other command stays synchronous inside it.
  - The memorycli suite's `PY_PROG`/`NODE_PROG` substitution (`memorycli.mjs:219-220`) covers the two prefixes. Add `embed -h` at widths 80, 200 and 40 to the suite's help matrix, which is the existing loop over subcommands. Extend its list, and keep the paired `-raw` ruling, as the porting row requires.
- [ ] **Step 5: Start-up fill.**
  - Python, after `maybe_spawn(...)` at `mcpserver.py:2999`:

```python
    if server_memory.embed.on:
        import threading
        from bantamkit.memory import vectors
        threading.Thread(
            target=lambda: _quietly(vectors.fill, server_memory, server_memory.embed),
            name="bantamkit-embed-fill", daemon=True,
        ).start()
```

    Here `server_memory` is the value `_build_memory(args)` returned, now bound to a name, and `_quietly` swallows every exception.
  - Node, after `maybeSpawnRetention(...)` at `cli.ts:910`: `if (memory.embed.on) void fill(memory, memory.embed).catch(() => undefined);`. It is never awaited, so startup is never blocked.
- [ ] **Step 6: Conformance cases** (`recall-embed.mjs`)
  1. `fill` over a 70-fact bed: the counts line, and the stub request log (batch sizes `[32, 32, 6]`) Py vs Node.
  2. Each CLI's stdout, stderr (after the prog substitution) and exit code for:
     - a live stub;
     - a dead port, which exits 2;
     - `BANTAMKIT_EMBED_MODEL=nope`, which exits 2;
     - `OLLAMA_HOST=10.0.0.1`, which exits 2.
  3. `memory_save` through each MCP server over stdio. Copy the session helper from `wire.mjs`. The reply bytes are equal, and the cache holds the saved fact's key on both sides.
  4. **Per-side literal:** the `embed` subcommand help line `embed every fact the vector cache lacks (ollama, BANTAMKIT_EMBED_MODEL)`.
- [ ] **Step 7: Prove it guards (rsync copy)**
  - **M3a:** Node `FILL_BATCH = 16`. Expect red on case 1.
  - **M3b:** Python exits 1 on unreachable. Expect red on case 2.
  - **M3c:** Node skips `flushEmbeds` after `memory_save`. Expect red on case 3.
  - **M3d (symmetric):** both help strings change. Expect red only on literal 4.
- [ ] **Step 8: Gates and commit** (`feat(memory): fill the vector cache — on save and repair, bantamkit memory embed, and at server start (#207 §3)`). Add every file in **Files** by explicit path, and run `git diff --cached --stat` in the same command.

---

### Task 4: Status lines and hook-log fields

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/embed.py`, `runtime-ts/src/memory/embed.ts` (`status_lines`)
- Modify: `runtime-py/src/bantamkit/mcpserver.py:1024` (after the usage line), `runtime-ts/src/mcp/status.ts:500`
- Modify: `runtime-py/src/bantamkit/hookadapter.py` (`_user_prompt_submit`, the four `_log` rows `:1293-1410`), `runtime-ts/src/hookadapter.ts` (the same four rows)
- Modify: `tools/conformance/suites/recall-embed.mjs`, `tools/conformance/suites/wire.mjs` (the fix-line ruling), `docs/porting.md` (extend the `index-budget-low` remedy row, `:355`)
- Test: `runtime-py/tests/test_status_surface.py`, `runtime-ts/test/server.test.mjs`, `runtime-py/tests/test_hookadapter.py`, `runtime-ts/test/hookadapter.test.mjs`

**Interfaces:**
- Consumes: `Memory.embed`, `Memory.fallbacks`, `Memory.vector_coverage()`, `RecallOutcome.scorer`/`.fallback`.
- Produces: `status_lines(config, fallbacks, coverage: tuple[int, int] | None, prog: str) -> list[str]`. The exact lines:

```
scorer: bm25f                                         (always; embedding off, refused or unknown)
scorer: ollama bge-m3                                 (config.on)
embedding: <unknown_value_sentence>                   (config.unknown)
embedding: <refused_host_sentence>                    (config.refused)
vectors: 640 of 655 facts (bge-m3)                    (config.on)
vectors: run python -m bantamkit.memory embed         (config.on and have < total; Node: bantamkit-memory embed)
embed fallbacks since start: unreachable 0, timeout 2, no-model 0, coverage 1, refused-host 0   (configured())
```

- The hook-log row gains `"scorer": o.scorer` and, when it is set, `"fallback": o.fallback`, only when `m.embed.configured()`. With embedding off, every hook-log row is byte-identical to 0.37.0-beta.1.

- [ ] **Step 1: Failing tests.**
  - `status_report` with embedding off ends with `scorer: bm25f`, and every earlier line is unchanged.
  - With embedding on and 1 of 2 facts covered, the last four lines are exactly the above, with that runtime's prog.
  - A UserPromptSubmit run with embedding on and a timed-out stub logs `"scorer": "bm25f", "fallback": "timeout"`.
  - The same run with embedding off has no `scorer` key.
  - Find the tests that pin the whole status text by grepping for `read-repaired:` in `runtime-py/tests` and `runtime-ts/test`, and append `scorer: bm25f` to their expected text. This is the only change to an existing expectation, and it is the spec §4 addition.
- [ ] **Step 2: Implement `status_lines`** (Python; the Node port is the same):

```python
def status_lines(config: EmbedConfig, fallbacks: Mapping[str, int],
                 coverage: tuple[int, int] | None, prog: str) -> list[str]:
    out = [f"scorer: ollama {config.model}" if config.on else "scorer: bm25f"]
    if config.unknown is not None:
        out.append(f"embedding: {unknown_value_sentence(config.unknown)}")
    if config.refused is not None:
        out.append(f"embedding: {refused_host_sentence(config.refused)}")
    if config.on and coverage is not None:
        have, total = coverage
        out.append(f"vectors: {have} of {total} facts ({config.model})")
        if have < total:
            out.append(f"vectors: run {prog} embed")
    if config.configured():
        out.append("embed fallbacks since start: "
                   + ", ".join(f"{r} {fallbacks.get(r, 0)}" for r in REASONS))
    return out
```

  - `mcpserver.status_report` appends `*embed.status_lines(memory.embed, memory.fallbacks, memory.vector_coverage() if memory.embed.on else None, "python -m bantamkit.memory")` after `memory_usage.status_line(...)`.
  - `status.ts` appends the same with `'bantamkit-memory'`, read from `package.json`'s `bin` the same way the degraded-report test does (`docs/porting.md:355`).
  - Fallbacks count the MCP server's own recalls (`memory_recall`). Each hook process counts its own and records it in its log row; the docs say so.
- [ ] **Step 3: Hook rows.** In `_user_prompt_submit` (and Node's `userPromptSubmit`):

```python
    scoring: dict[str, Any] = (
        {"scorer": o.scorer, **({"fallback": o.fallback} if o.fallback else {})}
        if m.embed.configured() else {}
    )
```

  Spread `**scoring` into the four rows (`none`, `no-headers`, `suppress`, `inject`) right after `**degraded`.
- [ ] **Step 4: Conformance cases.**
  1. `status_lines` Py vs Node over 6 configs: off; on and full; on and short; unknown value; refused host; on with fallbacks `{timeout: 2, coverage: 1}`. The prog is substituted on the reference side only.
  2. **Ruling (in `wire.mjs`, beside `status-degraded: the remedy lines, raw`):** `status: the vectors fix line, raw`. It differs by prog. An unruled `…, after the one substitution` sits over the same bytes.
  3. The hook-log `scorer`/`fallback` fields. Run both hook CLIs over the four-fact bed (use the spawn helper `runHook` from `tools/conformance/suites/hooks.mjs:185`, copied) with stub A, then with stub B (timeout), then with embedding off. Compare the parsed last row of `~/.bantamkit/hooks/hook-log.jsonl` in each side's sandboxed HOME, restricted to the keys `action`, `scorer` and `fallback`.
  4. **Per-side literal:** with embedding off, the row has no `scorer` key on either side.
  - Add the `docs/porting.md` row text to the `index-budget-low` remedy row at `:355`: "…and since #207 the `vectors: run … embed` fix line, ruled in `wire.mjs` as `status: the vectors fix line, raw`."
- [ ] **Step 5: Prove it guards (rsync copy)**
  - **M4a:** Node orders the fallback reasons alphabetically. Expect red on case 1.
  - **M4b:** Python writes `scorer` with embedding off. Expect red on case 3.
  - **M4c:** Node removes the prog substitution need by printing `python -m bantamkit.memory`. Expect red on the ruling, as a stale ruling.
  - **M4d (symmetric):** both sides add `scorer` with embedding off. Expect red only on literal 4.
- [ ] **Step 6: Gates and commit** (`feat(status): scorer, vector coverage and fallback lines; scorer and fallback in the hook log (#207 §4)`), by explicit path, with `git diff --cached --stat`.

---

### Task 5: Measurement — bar first, EMBED_GATE on silver, inject on gold, pool, score, latency

**Files:**
- Modify: `tools/eval/recall/bar.json` (Step 1, alone, before anything else in this task)
- Create: `tools/eval/recall/tune_embed.py`, `tools/eval/recall/inject_embed.py`, `tools/eval/recall/bench_embed.mjs`
- Modify: `runtime-py/src/bantamkit/memory/retrieval.py`, `runtime-ts/src/memory/retrieval.ts` (`EMBED_GATE`, the frozen value)
- Output (private, gitignored): `.shiftwork/notes-job71/tuning-embed.json`, `pool-injections-embed.json`, `pool-judge-embed-targets.jsonl`, `gold-labels-pool-embed.jsonl`, `pooled-result-embed.jsonl`, `latency.json`

- [ ] **Step 1: Declare the bar (commit before any number exists).** Add to `bar.json`:

```json
  "embedding": {
    "declared": "2026-10-17",
    "spec": "docs/superpowers/specs/2026-10-17-recall-embedding-design.md",
    "pass": "embedding view precision@inject >= BM25 view precision@inject + 0.05 AND embedding view recall@3 >= BM25 view recall@3, both on the same pooled gold",
    "precision_at_inject_margin_over_bm25": 0.05,
    "recall_at_3_min": "bm25_view_same_pooled_gold",
    "bar_199_precision_at_inject_min_still_reported": 0.8,
    "hook_p50_rise_ms_max_embedding_on_warm": 100.0,
    "query_embed_timeout_ms": 150,
    "hook_p50_rise_ms_max_embedding_off": 5.0,
    "embed_gate_tuned_on": "silver only; frozen in tuning-embed.json before gold is scored",
    "gold_is_held_out": true,
    "gold_is_unvalidated": true,
    "on_miss": "ship the Scorer refactor only; OllamaScorer stays on a local branch; record the miss on #207; the bar does not move"
  }
```

Run: `git add tools/eval/recall/bar.json && git diff --cached --stat && git commit -m "eval(recall): declare the #207 embedding bar before any number exists"`.

- [ ] **Step 2: `tune_embed.py`.** Copy `tune.py`'s silver reading, views and selection rule (`tools/eval/recall/tune.py:1-30`, `:76-144`). The grid is `EMBED_GATE ∈ {0.30, 0.325, …, 0.70}` (17 points), rebound on `retrieval.EMBED_GATE` per point and restored after. The objective is read on view B, with `--precision-min 0.85`. Recall runs through `Memory.layered_for_eval(..., engine="embed", native=...)` with `BANTAMKIT_EMBED=ollama`, a real ollama with `bge-m3` warm, a sandboxed HOME, and `BANTAMKIT_INDEX_DIR=<scratch>/index`. First fill the cache of every store copy with `python -m bantamkit.memory embed --store <copy>` and of the auto-memory copies through `vectors.fill` on a layered eval memory. It writes `tuning-embed.json` with every point and the chosen one. **It never reads gold**: assert every row has `session`, as `tune.py` does.
- [ ] **Step 3: Freeze.** Copy the chosen value into `EMBED_GATE` in BOTH `retrieval.py` and `retrieval.ts`. Update the Task 2 conformance literals (cases 2 and 3) to what the frozen gate admits on the four-fact bed. Recompute the expected list with the cosines given in Task 2 Step 8: a fact is admitted iff its cosine is > 0 and ≥ `EMBED_GATE`. Run all four gates, then commit `perf(memory): EMBED_GATE tuned on silver (#207 D9)` with the tuning summary in the message.
- [ ] **Step 4: Inject on gold.** `inject_embed.py` reads the 50 gold prompts (`.shiftwork/notes-job68/gold-labels.jsonl`), the frozen store copies (`.shiftwork/notes-job68/stores/`) and the session map. It picks the B view's native copy per gold row exactly as `.shiftwork/notes-job68/J68-17-inject.py` does; read that file for the rule. It runs `inject_candidates` with `engine="embed"`, and writes `pool-injections-embed.json` = the existing `pool-injections.json` plus an `"embed"` view. Every hook-log row must have `scorer: ollama bge-m3` and no `fallback`. Count any fallback and report it; a fallback rate above 0 makes the run void until the cache is full.
- [ ] **Step 5: Pool.**
  - Every injected (prompt, fact) pair in the `embed` view that has no label in `gold-labels.jsonl` ∪ `gold-labels-pool.jsonl` goes to the calibrated judge.
  - The judge is a separate model, blind to engine and scores, and is given `.shiftwork/notes-job68/pool-judge-examples.jsonl` exactly as J68-18 did (`.shiftwork/notes-job68/J68-18.md`).
  - Its output goes to `.shiftwork/notes-job71/gold-labels-pool-embed.jsonl` only.
- [ ] **Step 6: Score.**
  - Run `score_pooled.py` over every view (`v1`, `A`, `B`, `embed`) against the enlarged pool, writing `pooled-result-embed.jsonl`.
  - The report says PASS or MISS against `bar.json.embedding`, with the numbers. Every gold number is labelled UNVALIDATED (`bar.json.gold_judge_calibrated.on_miss`), and the #199 0.8 line is reported as missed.
- [ ] **Step 7: Latency.**
  - `bench_embed.mjs` builds a bed that copies one frozen store (`--store <copy>`) into a throwaway HOME's project, then runs N=30 cold `node <cli.js> --hook` UserPromptSubmit runs with a fixed English prompt. It prints `{"label","p50_ms","p95_ms","n"}`. Derive it from `tools/eval/recall/bench_touch.mjs`'s bed and env.
  - Runs:
    - (a) the 0.37.0-beta.1 build (`git archive 71ba1e4 runtime-ts`, then `npm ci && npm run build` in scratch), embedding off;
    - (b) this branch, embedding off;
    - (c) this branch, embedding on, with the model warmed by one discarded call and the cache full.
  - Pass rules: (b) − (a) ≤ 5 ms, and (c) − (b) ≤ 100 ms.
  - The timeout path is already exercised by the stub (Task 2, case 5).
  - Also run the same bed through the Python hook (`.venv/bin/python -m bantamkit.mcpserver --hook` on the same payloads; verify the module entry with `-h` first, off and on warm) and record its p50 rise as `py_*` fields: reported only, never a PASS/MISS line (user ruling Q3).
  - Write `latency.json`.
- [ ] **Step 8: On a MISS (spec §6.7).** Change nothing in product code. The orchestrator stops, records the miss on #207 with the aggregate numbers only, and keeps the bar. Tasks 1–4 stay on the local branch `feat/207-recall-embedding`, unmerged and unpushed. The release branch is cut from `main` with Task 0's commit only (cherry-picked). On a PASS, Task 6 proceeds over all of it.
- [ ] **Step 9: Commit** `tune_embed.py`, `inject_embed.py` and `bench_embed.mjs` (`eval(recall): #207 embedding view, gate tuning, latency bench`). The numbers go into the note, not the repo.

---

### Task 6: Docs, Windows note, reviewer

**Files:**
- `docs/memory.md`: the `Scorer`; the embedding switch and its three variables; loopback-only; the vector cache (path, format, "deleting it loses nothing"); the fill paths; the fallback rule; the off-by-default guarantee.
- `docs/status.md`: the new status lines, verbatim, and that fallback counts are per process.
- `docs/hooks.md`: the `scorer`/`fallback` log fields, present only when embedding is configured.
- `docs/porting.md`: the extended remedy row (Task 4). Check whether any other divergence appeared. The expected answer is none; the Python total deadline uses a daemon thread, so it matches Node's `AbortSignal.timeout`.
- `docs/conformance.md`: the `recall-embed` suite, its stub, and its case count.

- [ ] **Step 1: Write the docs.**
  - Every number comes from the Task 5 note, with the commit it was measured at.
  - On a MISS, write only the `Scorer` paragraph, the shipped scope, and a sentence that the embedding backend was measured and missed, linking #207.
- [ ] **Step 2: Windows (D10).** Write in `docs/memory.md`: "Not measured on Windows: no Windows machine was available. The path is plain HTTP to localhost and one binary file read, with no platform branch." Do not claim a Windows run.
- [ ] **Step 3: Reviewer unit (Opus).**
  - Read the diff against `main`.
  - Rerun the four gates and every mutation named in Tasks 0–4 on rsync copies.
  - Check that every spec section (§1–§6, D1–D10) maps to code or to a stated deviation in `.shiftwork/notes-job71p/P-207.md`.
  - Check that the default-off path writes no new hook-log key and changes no status line other than the appended `scorer: bm25f`.
  - Report blockers. A blocker unit fixes them.
- [ ] **Step 4: Commit the docs** (`docs(memory): recall round two — Scorer, opt-in ollama scorer, vector cache, status (#207)`).

---

### Task 7: Fix the reviewer's blockers

- [ ] One commit per blocker, each with the case or test that proves it.
- [ ] Rerun the four gates.
- [ ] Hand back to the orchestrator for merge. Merging is the user's standing permission; tag, bump and publish are not part of this job.

---

## Shiftwork unit map (job71 checkpoint)

| Unit | Task | Depends on | Role / model |
|---|---|---|---|
| J71-0 | Task 0 Scorer + Bm25fScorer | — | implementer / claude-opus-5-5 |
| J71-1 | Task 1 vector cache | — | implementer / claude-opus-5-5 |
| J71-5a | Task 5 Step 1 only (declare the bar) | — | implementer / claude-opus-5-5 |
| J71-2 | Task 2 OllamaScorer + stub + recall-embed | J71-0, J71-1 | implementer / claude-opus-5-5 |
| J71-3 | Task 3 fill paths + CLI | J71-2 | implementer / claude-opus-5-5 |
| J71-4 | Task 4 status + hook log | J71-3 | implementer / claude-opus-5-5 |
| J71-5 | Task 5 Steps 2–9 (silver gate, gold, pool, score, latency) | J71-4, J71-5a | implementer / claude-opus-5-5 |
| J71-6 | Task 6 docs + Windows note + reviewer | J71-5 | reviewer / claude-opus-5-5 |
| J71-7 | blockers from J71-6 | J71-6 | implementer / claude-opus-5-5 |

**Width:**
- Wave 1 is J71-0, J71-1 and J71-5a. They share no file:
  - J71-0 edits `retrieval.*` and `store.*`;
  - J71-1 creates `vectors.*` and `recall-embed.mjs`;
  - J71-5a edits `bar.json` only.
- Commit by explicit path only: the memory note `shared-git-index-race-between-parallel-units` is why.
- Everything after wave 1 is sequential. J71-2, J71-3 and J71-4 all edit `component.*`, `hookadapter.*` or `mcpserver.py`/`server.ts`, and no two concurrent units may edit retrieval, component or hookadapter.

**User steps inside the job:**
- None for labels: the calibrated judge labels the pool, per the user's ruling that the agent does all labelling.
- On a MISS, the orchestrator stops and asks before anything ships.
