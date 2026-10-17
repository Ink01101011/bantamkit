# Recall queries + session head (#207 amendment 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship G6 (likely-prompt queries scored as one extra BM25 vector, plus a short-prompt session head on the hook) in
`runtime-py` and `runtime-ts`, with no embedding, no local model and no network, gated by conformance and reproduced
against the probe's G6 lists.

**Architecture:** Each store gets a sidecar `<home>/.bantamkit/queries/<store-key>.json`. Recall reads every layer's
sidecar before it pools. When any sidecar holds an entry, `_pooled` ranks with a new dense scorer, `QueryScorer`. It
plugs into the #207 §1 `Scorer` seam that is already on main (`retrieval.py:259`, `retrieval.ts:306`). Its column is
`bm25_segments(head terms) + QUERY_WEIGHT * bm25_scores(prompt, qdocs)`. When no sidecar holds anything, the
recall is today's BM25F call, unchanged. The hook alone builds the head from a bounded tail read of
`transcript_path`. `memory_save` gains `queries`, and a fifteenth MCP tool, `memory_queries`, lists the facts that
have none and writes queries for them.

**Tech Stack:** Python 3.12 (`runtime-py`, pytest, ruff), TypeScript/Node (`runtime-ts`, `node:test`), the
conformance harness `tools/conformance/run.mjs` (suites are discovered from `tools/conformance/suites/`).

Spec: `docs/superpowers/specs/2026-10-18-recall-queries-design.md` (commit 444e427, amendment 3, posted to #207).
Where it conflicts with `2026-10-17-recall-embedding-design.md`, it supersedes that spec.

## Global Constraints

Copied verbatim from the spec, then the job's standing invariants:

- "Q2 | Score | `s = bm25f(head) + QUERY_WEIGHT · bm25(prompt, qdoc)`, with `QUERY_WEIGHT = 1.0`. `qdoc(f)` is f's queries joined with `"\n"`, after every character of a no-space script (the class `tokenize_v2` splits into bigrams) has been replaced by a space. `bm25` is the product's `bm25_scores` over the pool's qdocs, so its document frequencies come from those qdocs, with the product's k1 and b. A fact with no queries has an empty qdoc and scores 0. The sum is the column `rank_columns` gates and weights. Gate, weights and inject cap are unchanged. **(measured, frozen by look 6)**"
- "Q3 | Head | Hook only, since it alone has `transcript_path`. When the prompt has fewer than 80 code points, the BM25F query becomes `prompt + "\n" + prev[:500 code points]`. The query vector (Q2) still uses the bare prompt. `prev` is the latest main-chain user prompt before the current one, found in the last 256 KiB of the transcript with one bounded read. "Main chain" means not `isSidechain`, not `isMeta`, `type: user`, with text content that does not start with `<` or `[Request interrupted`. Any read or parse failure means no head, and the hook never errors on this path. `memory_recall` (MCP) never uses a head. **(measured)**"
- "Q1 | Where queries live | A sidecar file per store, `<home>/.bantamkit/queries/<store-key>.json`. `<store-key>` is the key the hot index already uses for that store. The file holds `{"v": 1, "facts": {<name>: {"queries": [..], "sha": <sha1 of the fact file text when written>}}}`. All layers use it, including native facts, which bantamkit must not write. The fact-file format is unchanged."
- "Q5 | Writing queries | `memory_save` takes an optional `queries`: an array of at most 8 strings, each at most 200 code points. They are written to the sidecar after the fact is saved. Writing them is best-effort: a failure there never fails the save."
- "Q9 | Latency | Bar: an off-path hook p50 rise of at most 5 ms."
- "Q11 | W10 / ollama | It stays unmerged on its local branch. Nothing in this amendment loads `node:http` or calls ollama. **(user)**"
- "Q12 | Windows | Not measured. The code is plain file IO with no platform branch."
- "A feature lands in both runtimes in the same job, each with conformance cases"
- "Out of scope: Embedding of any kind, local models, and network calls. Native-fact `keywords:` being ignored by both hot indexes. Validating gold."
- Invariants (job72): throwaway HOME/USERPROFILE, `BANTAMKIT_INDEX_DIR`, `BANTAMKIT_RETENTION=off` for every test,
  probe and gate. Pathspec commits only. No push, tag, bump or publish. Never copy private eval data into a tracked
  file. Gold looks are rationed and logged in `.shiftwork/notes-job72/gold-looks.jsonl`. `tools/eval/recall/bar.json`
  never moves. Do not retune #199 constants (`GATE_FLOOR`, `GATE_RATIO`, `W_*`). Do not switch to or push
  `feat/199-recall-by-meaning`.
- Gates before each commit, all from this worktree's own `.venv` and build. They are listed after the Self-review
  section, under "Gates (every task)".

---

## Shared constants: one number, two homes

| constant | value | Python | Node |
|---|---|---|---|
| `QUERY_WEIGHT` | `1.0` | `runtime-py/src/bantamkit/memory/retrieval.py`, beside `BM25_K1` (line 76) | `runtime-ts/src/memory/retrieval.ts`, beside `BM25_K1` |
| `HEAD_SHORT` | `80` (code points, strict `<`) | `runtime-py/src/bantamkit/hookadapter.py`, beside `PROMPT_INJECT_MAX` (budgets block, line 138) | `runtime-ts/src/hookadapter.ts`, beside `PROMPT_INJECT_MAX` |
| `HEAD_CUT` | `500` (code points) | same as `HEAD_SHORT` | same as `HEAD_SHORT` |
| `TAIL_BYTES` | `262144` | same as `HEAD_SHORT` | same as `HEAD_SHORT` |
| `MAX_QUERIES` | `8` | new `runtime-py/src/bantamkit/memory/queries.py` | new `runtime-ts/src/memory/queries.ts` |
| `MAX_QUERY_CHARS` | `200` (code points) | `memory/queries.py` | `memory/queries.ts` |
| `LIST_LIMIT` | `10` | `memory/queries.py` | `memory/queries.ts` |
| `BODY_EXCERPT` | `600` (code points) | `memory/queries.py` | `memory/queries.ts` |
| `SIDECAR_VERSION` | `1` | `memory/queries.py` | `memory/queries.ts` |
| `QUERIES_DIR` | `"queries"` | `memory/queries.py` | `memory/queries.ts` |

Every constant gets a per-side literal case in Task 3, as `recall-gate.mjs` does for `RECALL_MIN_SCORE_RATIO`.
A literal case is the only kind that catches a change made identically on both sides.

## `<store-key>`: the exact derivation

The key is the hot index's file stem, `sha16(realpath(store root))`:

- Python: `bantamkit.storage.hotindex.sha16(path)` (`hotindex.py:113`). It equals `memory.usage.store_id`
  (`usage.py:87`).
- Node: `sha16(p)` from `runtime-ts/src/storage/hotindex.ts:225`. It equals `storeId` (`memory/usage.ts:95`) and uses
  the module's own `realpath`, which resolves a path that does not exist the way `os.path.realpath` does.

"Store root" means the same thing the index uses:

- `MemoryStore`: `store.root`, which is the directory that holds `facts/`. `MemoryStore.index()` builds
  `HotIndex(self.root, "facts", ...)` (`store.py:892`).
- `NativeStore`: `store.root`, the auto-memory directory itself (`native.py:65`).

So `sidecar_path(home, root) = home / ".bantamkit" / "queries" / f"{sha16(root)}.json"`, where `home` is
`Path.home()` on Python and `os.homedir()` on Node. Those are the same `home` that `UsageLedger` uses
(`component.py` `usage()`, `component.ts` `usage()`). `BANTAMKIT_INDEX_DIR` does NOT move the sidecar. That
variable moves indexes only (`store.py:879-881`), and the sidecar is not derived from anything, so it is not an index.

## Index / version bump: none

- The hot index stores neither scores nor anything a query wrote. Its rows are names, files, lengths, types, stale
  flags and postings (`hotindex.py` `HEAD_KEYS`/`TAIL_KEYS`, lines 91-96). Scores are computed per call in
  `pooled_ranking` (`store.py:592`).
- `HotIndex` caches its head and shards per process, keyed on the head file's stat (`hotindex.py:330-345`). The
  sidecar is read outside that cache, once per recall. A sidecar write is therefore visible to the next recall in
  the same long-lived MCP server with no invalidation. A grep for `lru_cache` or `functools.cache` under
  `memory/` and `storage/` finds nothing.
- `INDEX_VERSION` stays 5 (`hotindex.py:83`). The sidecar carries its own `"v": 1`. A reader treats any other `v`
  as an absent sidecar.

## Every new user-visible sentence, verbatim

Each sentence is spelled once here. Both runtimes hold it byte for byte, and Task 3 pins every one of them.

| id | where | text |
|---|---|---|
| S1 | `check_queries`, too many | `queries: at most 8 per fact, got {n}` |
| S2 | `check_queries`, too long (1-based `i`) | `queries: each at most 200 characters; query {i} has {n}` |
| S3 | `check_queries`, wrong type | `queries must be a list of strings` |
| S4 | `memory_save` reply suffix when the sidecar write fails | ` (queries not written: the sidecar could not be saved)` |
| S5 | `memory_queries` refusal, malformed item (0-based `i`) | `facts[{i}] must be an object with a name and queries` |
| S6 | `memory_queries` refusal, unknown layer | `facts[{i}]: no layer named '{layer}'; layers are {labels}` (`labels` = layer labels joined by `", "`) |
| S7 | `memory_queries` refusal, unknown fact | `facts[{i}]: no fact named '{name}' in {where}` (`where` = `layer '{layer}'`, or `any layer`) |
| S8 | `memory_queries` refusal, limits | `facts[{i}]: ` + S1 / S2 / S3 |
| S9 | `memory_queries` refusal, write failed | `the sidecar could not be saved` |
| S10 | `bantamkit_status` line | `queries: {n} of {m} facts` |
| S11 | `bantamkit_status` line when the walk raises | `queries: unavailable` |
| S12 | SessionStart line, only when `n < m` | `[bantamkit] {m - n} of {m} facts have no likely-prompt queries yet; call mcp__bantamkit__memory_queries with {} to list them and write their queries.` |

The wire shape of `memory_queries`:

- Called with `{}` (or `facts` omitted or null), it returns
  `{"result": "missing", "facts": [{"layer", "name", "description", "body"}], "remaining": <int>, "instructions": <text of assets/skills/memory-queries.md>}`.
- Called with `{"facts": [...]}`, it returns `{"result": "written", "written": <int>, "remaining": <int>}`.
- On a refusal it returns `{"result": "error", "reason": <S5..S9>}`. That is the refusal shape `work_plan` already
  uses (`workplan.py:143`).

`remaining` counts the facts still missing queries after the call.

## File map

| file | change | layer |
|---|---|---|
| `runtime-py/src/bantamkit/memory/retrieval.py` | `QUERY_WEIGHT`, `strip_nospace`, `QueryScorer` | 1 |
| `runtime-py/src/bantamkit/memory/queries.py` | NEW: sidecar path/read/write, `qdoc`, `check_queries`, `fact_sha`, constants | 1 |
| `runtime-py/src/bantamkit/memory/store.py` | `pool_of(..., every_row=False)` (507), `MemoryStore.pool(..., every_row=False)` (1453) | 1 |
| `runtime-py/src/bantamkit/memory/native.py` | `NativeStore.pool(..., every_row=False)` (146) | 1 |
| `runtime-py/src/bantamkit/memory/component.py` | `save`/`save_outcome` `queries` (394/406); `recall_outcome(head=)` (522); `_pooled(head=)` + scorer wiring (773); `inject_candidates`/`rank_all(head=)` (926/930); `queries_missing`, `queries_write`, `queries_coverage` | 1 |
| `assets/tools/memory_save.json` | `queries` parameter | 2 |
| `assets/tools/memory_queries.json` | NEW manifest | 2 |
| `assets/skills/memory.md` | "## Likely-prompt queries" section | 2 |
| `assets/skills/memory-queries.md` | NEW: the generator instructions (Q7), returned by `memory_queries {}` | 2 |
| `runtime-py/src/bantamkit/mcpserver.py` | `memory_save(queries=)` (1480), `memory_queries` handler + `tools` entry (2031-2045), S10/S11 in `status_report` (after 1024) | 5 |
| `runtime-py/src/bantamkit/hookadapter.py` | `HEAD_*`/`TAIL_BYTES`, `_previous_prompt`, `_head_query`, wired at 1289; S12 in `_session_start` (after 1072) | 5 |
| `runtime-py/tests/data/served-tool-surface.json` | golden: fifteenth tool | test |
| `runtime-ts/src/memory/retrieval.ts` | `QUERY_WEIGHT`, `stripNospace`, `QueryScorer`; `Scorer.column` vecs widened to `ReadonlyArray<unknown>` (314) | 1 |
| `runtime-ts/src/memory/queries.ts` | NEW, mirrors `queries.py` | 1 |
| `runtime-ts/src/memory/store.ts` | `poolOf(..., everyRow=false)` (616), `MemoryStore.pool(..., everyRow)` (1405), `RowsOf` widened (737) | 1 |
| `runtime-ts/src/memory/native.ts` | `NativeStore.pool(..., everyRow)` (145) | 1 |
| `runtime-ts/src/memory/component.ts` | `save`/`saveOutcome` `queries` (456/475); `recallOutcome(..., head)` (623); `pooled(..., head)` (795); `injectCandidates`/`rankAll(head)` (927/932); `queriesMissing`, `queriesWrite`, `queriesCoverage` | 1 |
| `runtime-ts/src/pysem.ts` | `pyLstrip`, `pyTruthy` | 1 |
| `runtime-ts/src/mcp/pyargs.ts` | `memory_save` `opt('queries','listStr')` (109-112); `memory_queries: { model: 'memory_queriesArguments', fields: [opt('facts','listDict')] }` | 5 |
| `runtime-ts/src/mcp/server.ts` | `MCP_TOOLS` += `'memory_queries'` (113-128, appended LAST); `case 'memory_save'` (575) passes `queries`; `case 'memory_queries'` | 5 |
| `runtime-ts/src/mcp/status.ts` | S10/S11 after `statusLine(...)` (500) | 5 |
| `runtime-ts/src/hookadapter.ts` | `previousPrompt`, `headQuery`, wired at 1401; S12 in `sessionStart` (after 1178) | 5 |
| `tools/conformance/suites/recall-queries.mjs` + `tools/conformance/ref/queries_ref.py` | NEW suite | gate |
| `tools/conformance/suites/hooks.mjs` | head cases + S12 cases | gate |
| `tools/conformance/suites/instructions.mjs` | rows for S12 and `memory-queries.md` naming `memory_queries` | gate |
| `docs/memory.md`, `docs/mcp.md`, `docs/hooks.md`, `docs/conformance.md`, `README.md` | the sidecar, the fifteenth tool, the head, the new suite | doc |

Every commit holds one layer: the Layer 1 core, the Layer 2 assets and the Layer 5 composition each go in their own
commit (CLAUDE.md, `docs/architecture.md` "The layers").

---

### Task 1: Python: sidecar, scorer, save/backfill surfaces, status, head

Six commits, one per sub-task, in order. Every sub-task is TDD: test first, red, code, green, gates, commit.

**Files:** as in the file map, Python rows plus `assets/`. Tests:
- `runtime-py/tests/test_memory_queries.py` (NEW): sidecar, scorer, pool, save and backfill.
- `runtime-py/tests/test_hookadapter.py`: head and S12.
- `runtime-py/tests/test_status_surface.py`: S10/S11.
- `runtime-py/tests/test_tool_manifest.py`: the golden.

**Interfaces (produces, Python):**

```python
# memory/retrieval.py
QUERY_WEIGHT: float = 1.0
def strip_nospace(text: str) -> str: ...
class QueryScorer:            # satisfies retrieval.Scorer (line 259)
    dense = True
    fallback: str | None = None
    def __init__(self, prompt: str) -> None: ...
    def label(self) -> str: ...          # "bm25f+queries"
    def used(self) -> str: ...           # "bm25f+queries"
    def floor(self) -> float: ...        # GATE_FLOOR, read at call time
    def column(self, cols: Columns, vecs: list[Any] | None) -> list[float] | None: ...

# memory/queries.py
SIDECAR_VERSION = 1; MAX_QUERIES = 8; MAX_QUERY_CHARS = 200; LIST_LIMIT = 10; BODY_EXCERPT = 600
QUERIES_DIR = "queries"; WRITE_FAILED = "the sidecar could not be saved"
def sidecar_path(home: Path, root: str | Path) -> Path: ...
def read_sidecar(path: Path) -> dict[str, list[str]]: ...       # never raises
def qdoc(queries: list[str]) -> str: ...
def check_queries(queries: Any) -> list[str]: ...               # raises MemoryValidationError(S1|S2|S3)
def fact_sha(path: Path | None) -> str: ...                      # "" when unreadable or None
def write_entries(path: Path, entries: dict[str, tuple[list[str], str] | None]) -> None: ...  # raises OSError
def status_line(n: int, m: int) -> str: ...                      # S10

# memory/store.py
def pool_of(facts: list[Fact], q: list[str], every_row: bool = False) -> Pool: ...
MemoryStore.pool(self, q, skipped=None, every_row: bool = False) -> Pool
# memory/native.py
NativeStore.pool(self, q, skipped=None, shadow=frozenset(), every_row: bool = False) -> Pool

# memory/component.py (Memory)
save(type, name, description, body, links=None, keywords=None, queries=None) -> str
save_outcome(type, name, description, body, links=None, keywords=None, queries=None) -> SaveOutcome
recall_outcome(query, k=None, min_ratio=..., *, stamp=True, include_archived=False, context=None,
               head: str | None = None) -> RecallOutcome
inject_candidates(prompt: str, head: str | None = None) -> list[Fact]
rank_all(prompt: str, depth: int = 50, head: str | None = None) -> list[Fact]
queries_missing(limit: int = LIST_LIMIT) -> dict[str, Any]       # {"result": "missing", ...}
queries_write(facts: list[Any]) -> dict[str, Any]                # {"result": "written"|"error", ...}
queries_coverage() -> tuple[int, int]                            # (n with queries, m facts)

# hookadapter.py
HEAD_SHORT = 80; HEAD_CUT = 500; TAIL_BYTES = 262144
def _previous_prompt(transcript: str, current: str) -> str: ...  # "" when none; never raises
def _head_query(prompt: str, transcript: str) -> str | None: ...
```

`head` means "the BM25F query text when it is not `query`". The hook passes the composed
`prompt + "\n" + prev[:500]`; everyone else passes `None`.

#### 1.1 `retrieval.py`: `strip_nospace`, `QUERY_WEIGHT`, `QueryScorer`

- [ ] **Step 1: Write the failing tests** in `runtime-py/tests/test_memory_queries.py`.

```python
"""#207 amendment 3: likely-prompt queries (Q1, Q2, Q5, Q6, Q8). Mirrored in runtime-ts/test/queries.test.mjs;
`recall-queries` conformance compares the two runtimes."""
import json
from pathlib import Path

import pytest

from bantamkit.memory import queries as Q
from bantamkit.memory.retrieval import (
    BM25F, GATE_FLOOR, QUERY_WEIGHT, Columns, Doc, QueryScorer, bm25_scores, bm25_segments, strip_nospace,
)


def test_query_weight_is_one():
    assert QUERY_WEIGHT == 1.0


def test_strip_nospace_blanks_each_nospace_code_point_before_nfkc():
    assert strip_nospace("deploy กินบริบท ok") == "deploy " + " " * 7 + " ok"
    assert strip_nospace("记忆 x") == "   x"
    # Halfwidth katakana (U+FF76) is NOT in a no-space range BEFORE NFKC, so it survives: the probe stripped the raw
    # text, and fidelity (Q10) needs the same order. tokenize_v2 later NFKCs it into katakana.
    assert strip_nospace("ｶ") == "ｶ"


def test_query_scorer_adds_the_qdoc_vector_unrounded():
    cols = Columns(["deploy"], 2, 2.0, {"deploy": 1}, [1.0, 1.0], {"deploy": [0, 1, 2.0]})
    vecs = [Q.qdoc(["how do I deploy"]), Q.qdoc([])]
    a = bm25_segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs)
    b = bm25_scores("deploy", [Doc("", v, ()) for v in vecs])
    got = QueryScorer("deploy").column(cols, vecs)
    assert got == [x + QUERY_WEIGHT * y for x, y in zip(a, b, strict=True)]
    assert got[1] == a[1]  # an empty qdoc scores 0


def test_query_scorer_without_vectors_gives_the_recall_back_to_bm25f():
    cols = Columns([], 0, 0.0, {}, [], {})
    assert QueryScorer("x").column(cols, None) is None
    assert QueryScorer("x").dense is True and QueryScorer("x").floor() == GATE_FLOOR
    assert BM25F.dense is False


def test_a_thai_only_query_scores_zero_after_stripping():
    assert bm25_scores("ดีพลอย", [Doc("", Q.qdoc(["ดีพลอยยังไง"]), ())]) == [0.0]
```

- [ ] **Step 2: Run them and confirm they fail.** Run
  `.venv/bin/python -m pytest runtime-py/tests/test_memory_queries.py -q`. Expected: ImportError on `QUERY_WEIGHT`.
- [ ] **Step 3: Implement.** In `retrieval.py`, add the constant after `SCORE_ROUND` (line 80), the function after
  `_nospace` (line 31), and the class after `BM25F = Bm25fScorer()` (line 294).

```python
# #207 amendment 3 (Q2): the weight on the likely-prompt vector. Frozen by gold look 6; never tuned on gold.
QUERY_WEIGHT = 1.0


def strip_nospace(text: str) -> str:
    """Every code point of a no-space script replaced by one space, on the RAW text (before NFKC).

    Q2's qdoc keeps only the spaced-script tokens of a query: the Thai bigrams were measured as noise (J72-20).
    The order matters for fidelity: the probe stripped first and tokenized after.
    """
    return "".join(" " if _nospace(ord(ch)) else ch for ch in text)


class QueryScorer:
    """BM25F over the pooled columns plus `QUERY_WEIGHT` times BM25 of the bare prompt over each row's qdoc
    (#207 amendment 3, Q2). Dense: `vecs` is one qdoc string per pooled row, in row order (`pooled_ranking`'s
    `rows`), so a row whose name or description holds no prompt term can still be lifted by its queries."""

    dense = True

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        self.fallback: str | None = None

    def label(self) -> str:
        return "bm25f+queries"

    def used(self) -> str:
        return "bm25f+queries"

    def floor(self) -> float:
        return GATE_FLOOR

    def column(self, cols: Columns, vecs: list[Any] | None) -> list[float] | None:
        if vecs is None:
            return None
        a = bm25_segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs)
        b = bm25_scores(self.prompt, [Doc("", v, ()) for v in vecs])
        # NOT rounded: the probe summed two rounded columns and `rank_columns` rounds `score * weight`.
        return [x + QUERY_WEIGHT * y for x, y in zip(a, b, strict=True)]
```

- [ ] **Step 4: Run the tests and confirm they pass.** Same command. Expected: 5 passed (`test_memory_queries.py`
  grows over the next sub-tasks).
- [ ] **Step 5: Commit.**
  `git add runtime-py/src/bantamkit/memory/retrieval.py runtime-py/tests/test_memory_queries.py && git commit -m "feat(memory): QueryScorer and strip_nospace (#207 amendment 3, Q2)" -- runtime-py/src/bantamkit/memory/retrieval.py runtime-py/tests/test_memory_queries.py`

#### 1.2 `queries.py`: the sidecar module (Q1, Q5 limits)

- [ ] **Step 1: Write the failing tests** (append to `test_memory_queries.py`).

```python
from bantamkit.memory.store import MemoryValidationError
from bantamkit.storage.hotindex import sha16


def test_sidecar_path_is_the_index_key(tmp_path):
    root = tmp_path / "store"
    assert Q.sidecar_path(tmp_path / "h", root) == tmp_path / "h" / ".bantamkit" / "queries" / f"{sha16(root)}.json"


def test_round_trip_bytes_are_sorted_compact_utf8(tmp_path):
    p = tmp_path / "q.json"
    Q.write_entries(p, {"b-fact": (["วิธี deploy", "how to deploy"], "ab"), "a-fact": (["x"], "")})
    assert p.read_text(encoding="utf-8") == (
        '{"facts":{"a-fact":{"queries":["x"],"sha":""},"b-fact":{"queries":["วิธี deploy","how to deploy"],'
        '"sha":"ab"}},"v":1}'
    )
    assert Q.read_sidecar(p) == {"a-fact": ["x"], "b-fact": ["วิธี deploy", "how to deploy"]}
    Q.write_entries(p, {"a-fact": None})
    assert Q.read_sidecar(p) == {"b-fact": ["วิธี deploy", "how to deploy"]}


@pytest.mark.parametrize("text", [
    "", "not json", "[]", '{"v":2,"facts":{}}', '{"v":1.0,"facts":{"a":{"queries":["x"]}}}',
    '{"v":true,"facts":{"a":{"queries":["x"]}}}', '{"v":1,"facts":[]}',
])
def test_a_malformed_sidecar_reads_as_absent(tmp_path, text):
    p = tmp_path / "q.json"
    p.write_text(text, encoding="utf-8")
    assert Q.read_sidecar(p) == {}


def test_malformed_entries_are_skipped_one_by_one(tmp_path):
    p = tmp_path / "q.json"
    p.write_text('{"v":1,"facts":{"a":{"queries":["x",1]},"b":{"queries":[]},"c":"x","d":{"queries":["ok"]}}}',
                 encoding="utf-8")
    assert Q.read_sidecar(p) == {"d": ["ok"]}


def test_invalid_utf8_reads_as_absent(tmp_path):
    p = tmp_path / "q.json"
    p.write_bytes(b'{"v":1,"facts":{"a":{"queries":["\xff"]}}}')
    assert Q.read_sidecar(p) == {}


def test_missing_sidecar_reads_as_absent(tmp_path):
    assert Q.read_sidecar(tmp_path / "nope.json") == {}


def test_limits_use_the_spec_sentences():
    with pytest.raises(MemoryValidationError, match=r"^queries: at most 8 per fact, got 9$"):
        Q.check_queries(["q"] * 9)
    with pytest.raises(MemoryValidationError, match=r"^queries: each at most 200 characters; query 2 has 201$"):
        Q.check_queries(["ok", "x" * 201])
    with pytest.raises(MemoryValidationError, match=r"^queries must be a list of strings$"):
        Q.check_queries(["ok", 3])
    assert Q.check_queries(["\U0001F414" * 200]) == ["\U0001F414" * 200]  # code points, not UTF-16 units


def test_qdoc_joins_with_newline_then_strips():
    assert Q.qdoc(["ไป deploy", "ship it"]) == "   deploy\nship it"
```

- [ ] **Step 2: Run them and confirm they fail.** Same pytest command. Expected: ImportError on `queries`.
- [ ] **Step 3: Implement `runtime-py/src/bantamkit/memory/queries.py`.**

```python
"""Likely-prompt queries (#207 amendment 3): the per-store sidecar, its limits, and the qdoc a recall scores.

`<home>/.bantamkit/queries/<sha16(realpath(store root))>.json`, the hot index's key (`hotindex.sha16`), holding
`{"v": 1, "facts": {<name>: {"queries": [...], "sha": <sha1 of the fact file when written>}}}`. Derived from
nothing and owned by nobody's facts: deleting it loses recall quality only. Byte-identical to
runtime-ts/src/memory/queries.ts; `recall-queries` conformance pins both.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..storage.hotindex import dumps, sha16
from ..storage.lock import exclusive
from .retrieval import strip_nospace
from .store import MemoryValidationError

SIDECAR_VERSION = 1
MAX_QUERIES = 8
MAX_QUERY_CHARS = 200
LIST_LIMIT = 10
BODY_EXCERPT = 600
QUERIES_DIR = "queries"
WRITE_FAILED = "the sidecar could not be saved"


def sidecar_path(home: Path, root: str | Path) -> Path:
    return Path(home) / ".bantamkit" / QUERIES_DIR / f"{sha16(root)}.json"


def _doc(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or type(doc.get("v")) is not int or doc["v"] != SIDECAR_VERSION:
        return None
    if not isinstance(doc.get("facts"), dict):
        return None
    return doc


def read_sidecar(path: Path) -> dict[str, list[str]]:
    """`{name: queries}` for every well-formed, non-empty entry; `{}` for a sidecar that is absent or malformed."""
    doc = _doc(path)
    out: dict[str, list[str]] = {}
    if doc is None:
        return out
    for name, entry in doc["facts"].items():
        if not isinstance(entry, dict):
            continue
        qs = entry.get("queries")
        if isinstance(qs, list) and qs and all(isinstance(x, str) for x in qs):
            out[name] = qs
    return out


def qdoc(queries: list[str]) -> str:
    return strip_nospace("\n".join(queries))


def check_queries(queries: Any) -> list[str]:
    if not isinstance(queries, list) or not all(isinstance(x, str) for x in queries):
        raise MemoryValidationError("queries must be a list of strings")
    if len(queries) > MAX_QUERIES:
        raise MemoryValidationError(f"queries: at most {MAX_QUERIES} per fact, got {len(queries)}")
    for i, x in enumerate(queries, 1):
        if len(x) > MAX_QUERY_CHARS:
            raise MemoryValidationError(
                f"queries: each at most {MAX_QUERY_CHARS} characters; query {i} has {len(x)}"
            )
    return queries


def fact_sha(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def write_entries(path: Path, entries: dict[str, tuple[list[str], str] | None]) -> None:
    """Merge `entries` into the sidecar under its lock; `None` removes a name. A malformed sidecar is replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(path):
        doc = _doc(path) or {"v": SIDECAR_VERSION, "facts": {}}
        for name, entry in entries.items():
            if entry is None:
                doc["facts"].pop(name, None)
            else:
                doc["facts"][name] = {"queries": list(entry[0]), "sha": entry[1]}
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(dumps(doc), encoding="utf-8", newline="\n")
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise


def status_line(n: int, m: int) -> str:
    return f"queries: {n} of {m} facts"
```

  Check `storage/lock.py:26` `exclusive(...)` before you use it. Its signature may take more than the path. Follow
  how `hotindex.py:709` calls it.
- [ ] **Step 4: Run the tests and confirm they pass.** Same command. Run `.venv/bin/ruff check runtime-py tools`.
- [ ] **Step 5: Commit** `runtime-py/src/bantamkit/memory/queries.py` and `runtime-py/tests/test_memory_queries.py`
  with a pathspec commit: `feat(memory): the queries sidecar (#207 amendment 3, Q1/Q5)`.

#### 1.3 Pool every row, wire the scorer into `_pooled`, `save(queries)`, backfill, coverage

**Why every row (read this before you code).** A `Pool` built from the FILES holds only the facts that carry a
query term (`store.py:440-450` docstring, `pool_of` line 514 `if mine:`). A pool built from the INDEX holds every
fact. The probe's qdoc collection was every pooled row of index pools: its `row_vectors` recorded every row, and
those rows matched `dev-rows.json`. If a files pool kept hit rows only, a fact whose queries match the prompt but
whose name and description do not could never be ranked. Q2's `n`/`df` over the qdocs would also differ between the
files path and the index path. That would break the identity the index promises today (`_pool_indexed` docstring:
"the index and the files give the same bits"). So when any sidecar holds an entry, every pool must hold every fact
as a row. A zero-score row is never admitted (`rank_columns`: `x > 0.0`), and adding one cannot reorder the others
(the sort is stable and ids stay in name order). With no sidecar the pools are exactly today's.

- [ ] **Step 1: Write the failing tests** (append). They use `tmp_path` stores, `monkeypatch.setenv("HOME", ...)`,
  `USERPROFILE`, `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off`, the same way the existing component tests set
  them up (follow `runtime-py/tests/test_memory_component.py`'s fixtures).

```python
from bantamkit.memory.component import Memory


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    for k in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(k, str(h))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    return h


def _mem(tmp_path):
    m = Memory(tmp_path / "proj")
    m.save("project", "release-steps", "how the package goes out", "Run publish.sh, then verify on npm.")
    m.save("project", "lint-rules", "ruff config for tools", "ruff check runtime-py tools")
    return m


def test_no_sidecar_is_byte_identical_to_b(tmp_path, home):
    m = _mem(tmp_path)
    before = m.recall_outcome("how do I ship the package", 3, stamp=False).reply
    assert not (home / ".bantamkit" / "queries").exists()
    assert m.recall_outcome("how do I ship the package", 3, stamp=False).reply == before


def test_a_query_alone_admits_a_fact_bm25f_misses(tmp_path, home):
    m = _mem(tmp_path)
    assert [f.name for f in m.inject_candidates("publish to npm registry")] == []  # "npm" is in the body only
    Q.write_entries(Q.sidecar_path(home, m.store.root), {"release-steps": (["publish to npm registry"], "")})
    assert [f.name for f in m.inject_candidates("publish to npm registry")] == ["release-steps"]


def test_files_path_and_index_path_agree_with_a_sidecar(tmp_path, home):
    m = _mem(tmp_path)
    Q.write_entries(Q.sidecar_path(home, m.store.root), {"lint-rules": (["which linter config"], "")})
    indexed = [f.name for f in m.rank_all("which linter config")]
    with m.store.snapshot():  # `_indexed` returns None inside a snapshot: the files answer
        files = [f.name for f in m.rank_all("which linter config")]
    assert files == indexed == ["lint-rules"]


def test_head_feeds_bm25f_only(tmp_path, home):
    m = _mem(tmp_path)
    assert [f.name for f in m.inject_candidates("and then?")] == []
    got = m.inject_candidates("and then?", head="and then?\nruff config")
    assert [f.name for f in got] == ["lint-rules"]


def test_save_writes_queries_and_refuses_bad_ones(tmp_path, home):
    m = Memory(tmp_path / "proj")
    o = m.save_outcome("project", "a-fact", "d", "b", queries=["q one", "q two"])
    assert o.status == "saved" and o.reply == "saved 'a-fact'"
    side = Q.read_sidecar(Q.sidecar_path(home, m.store.root))
    assert side == {"a-fact": ["q one", "q two"]}
    raw = json.loads(Q.sidecar_path(home, m.store.root).read_text(encoding="utf-8"))
    assert raw["facts"]["a-fact"]["sha"] == Q.fact_sha(m.store.root / "facts" / "a-fact.md")
    bad = m.save_outcome("project", "b-fact", "d", "b", queries=["q"] * 9)
    assert bad.status == "refused-validation" and bad.reply == "error: queries: at most 8 per fact, got 9"
    assert not (m.store.root / "facts" / "b-fact.md").exists()


def test_save_survives_an_unwritable_sidecar(tmp_path, home):
    (home / ".bantamkit").mkdir()
    (home / ".bantamkit" / "queries").write_text("a file, not a directory", encoding="utf-8")
    m = Memory(tmp_path / "proj")
    o = m.save_outcome("project", "a-fact", "d", "b", queries=["q"])
    assert o.status == "saved"
    assert o.reply == "saved 'a-fact' (queries not written: the sidecar could not be saved)"


def test_queries_missing_and_write(tmp_path, home):
    m = _mem(tmp_path)
    got = m.queries_missing()
    assert got["result"] == "missing" and got["remaining"] == 2
    assert [(f["layer"], f["name"]) for f in got["facts"]] == [("project", "lint-rules"), ("project", "release-steps")]
    assert got["facts"][1]["body"].startswith("Run publish.sh, then verify on npm.")
    assert got["instructions"].startswith("# Likely-prompt queries")
    w = m.queries_write([{"name": "lint-rules", "queries": ["which linter"]}])
    assert w == {"result": "written", "written": 1, "remaining": 1}
    assert m.queries_coverage() == (1, 2)
    assert m.queries_write([{"name": "nope", "queries": ["x"]}]) == {
        "result": "error", "reason": "facts[0]: no fact named 'nope' in any layer"}
    assert m.queries_write([{"name": "lint-rules", "layer": "zzz", "queries": ["x"]}]) == {
        "result": "error", "reason": "facts[0]: no layer named 'zzz'; layers are project"}
    assert m.queries_write([{"queries": ["x"]}]) == {
        "result": "error", "reason": "facts[0] must be an object with a name and queries"}
    assert m.queries_write([{"name": "lint-rules", "queries": ["x"] * 9}]) == {
        "result": "error", "reason": "facts[0]: queries: at most 8 per fact, got 9"}
```

  The second test's first assertion depends on BM25F not indexing the body. That is true today: `FIELD_BOOST` holds
  `name`, `description` and `keywords` (`retrieval.py:79`). If it fails, change the prompt rather than the
  assertion, so the property "a query alone admits a fact" is kept. The `layers are project` text assumes the bare
  `Memory(store)` has one layer (`component.py:291`).
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**

  `store.py` `pool_of` (line 507): add `every_row: bool = False`, keep a fact when `mine or every_row`, and set
  `every=None` when `every_row`, since every name is then a row:

```python
def pool_of(facts: list[Fact], q: list[str], every_row: bool = False) -> Pool:
    ...
        mine = {t: weights[t] for t in q if t in weights}
        for t in mine:
            df[t] += 1
        if mine or every_row:
            held.append((doc.name, length, _text(fact.type), stale(doc.description), fact, mine))
    ...
        every=None if every_row else [_text(fact.name) for fact in facts],
```

  `MemoryStore.pool` (1453) passes `every_row` through to its `pool_of(...)` fallback only, because the index path
  already holds every row. Do the same in `NativeStore.pool` (`native.py:146`), for both of its `pool_of` calls.

  `component.py` `_pooled` (773): add `head: str | None = None`. Before the layer walk, read every layer's sidecar:

```python
        from . import queries as _queries

        home = Path.home()
        sides = [_queries.read_sidecar(_queries.sidecar_path(home, store.root)) for _, store, _ in self._layers]
        every_row = any(sides)
        q = query_terms(query if head is None else head)
        ...
                if native:
                    pool = store.pool(q, skipped=left_out, shadow=shadow, every_row=every_row)
                else:
                    pool = store.pool(q, skipped=left_out, every_row=every_row)
        ...
        def repool(i):  # every_row passed to pool_of as well
        ...
        scorer: Scorer = BM25F
        rows = None
        if every_row:
            docs = [{n: _queries.qdoc(v) for n, v in side.items()} for side in sides]
            scorer = QueryScorer(query)
            rows = lambda i, p: [docs[i].get(n, "") for n in p.names]  # noqa: E731
        hits = pick_hits(stores, pools, q, budget, min_ratio, lambda: ledger.weights(now), repool,
                         dedupe=True, context=..., scorer=scorer, rows=rows)
```

  `pick_hits` (`store.py:675`) already takes `scorer` and `rows` and hands them to `pooled_ranking`. A layer whose
  pool is `None` (unreadable) is skipped by `_row_vectors` through `live`, so its sidecar is never consulted. Its
  index in `docs` still lines up, because `rows(i, p)` receives the layer index.

  `recall_outcome` (522): add a keyword-only `head: str | None = None` and pass it to `_pooled` at line 633. The
  exact-name walk and `_archived_hits` keep using `query`. `inject_candidates`/`rank_all` (926/930) gain
  `head=None` and pass it. `recall()` and the MCP `memory_recall` never pass a head (Q3).

  `save_outcome` (406): add `queries: list[str] | None = None`. Run `check_queries` FIRST, before the duplicate
  check and the save. A bad value returns `SaveOutcome(reply=f"error: {e}", status="refused-validation")`, the
  same exit `MemoryValidationError` already takes. After the `status="saved"` exit is reached and before it
  returns, write the entry when `queries is not None`:

```python
        tail = ""
        if queries is not None:
            try:
                fact = self.store.lookup(result.name, stamp=False, skipped=[])
                sha = _queries.fact_sha(fact.source if fact is not None else None)
                path = _queries.sidecar_path(Path.home(), self.store.root)
                _queries.write_entries(path, {result.name: (queries, sha)} if queries else {result.name: None})
            except OSError:
                tail = f" (queries not written: {_queries.WRITE_FAILED})"
        return SaveOutcome(reply=f"saved '{result.name}'" + note + tail, status="saved")
```

  `queries=[]` removes the entry. Omitting `queries` leaves the entry untouched (see Open question 3). `save()`
  (394) gains `queries=None` and passes it; that is how the agent surface (`component.py:363`) gets it.

  `queries_missing`, `queries_write` and `queries_coverage` share one walk, `_named_facts()`. It returns the
  `(layer_index, label, store, sorted_names)` of every readable layer, in precedence order, with names held by an
  earlier layer removed. Names come from `store.pool([], skipped=[])` (native: `shadow=` the names seen so far) then
  `.all_names()`, `_text`'d and sorted by code point. A read-only layer that raises
  `(BantamError, OSError, UnicodeDecodeError)` is skipped; the project layer re-raises, as `_pooled` does.
  - `queries_coverage()` returns `(n, m)`. `m` counts every name the walk yields. `n` counts those with a non-empty
    entry in their own layer's sidecar.
  - `queries_missing(limit)` takes the first `limit` names that have no entry. It resolves each one with
    `store.lookup(name, stamp=False, skipped=[])` and returns `{"layer": label, "name", "description",
    "body": body[:BODY_EXCERPT]}`, along with `remaining` and
    `"instructions": load_skill("memory-queries")` (`assets.py:89`). Skip a name whose lookup returns `None`; it
    does not count as remaining.
  - `queries_write(facts)` validates EVERY item before it writes anything:
    - The item is a dict, with `name` a non-empty str and `queries` present. Otherwise S5.
    - If `layer` is given, it is a str that equals a layer label. Otherwise S6, listing the labels in precedence
      order.
    - The fact exists: `lookup` in that layer, or in the first layer that holds it when `layer` is omitted.
      Otherwise S7.
    - `check_queries` passes. Otherwise S8.

    The first failure refuses the whole call with `{"result": "error", "reason": ...}`. Then it groups the writes
    per layer sidecar (`fact_sha(fact.source)`), calls `write_entries` once per sidecar, maps `OSError` to S9, and
    returns `{"result": "written", "written": len(facts), "remaining": <missing after>}`.

- [ ] **Step 4: Run the tests and confirm they pass.** Run all of `runtime-py/tests -q`. The whole suite must stay
  green, and a no-sidecar recall must still be byte-identical to today's.
- [ ] **Step 5: Commit** the `store.py`, `native.py`, `component.py` and test paths:
  `feat(memory): score likely-prompt queries in the pooled ranker; save and backfill them (#207 amendment 3)`.

#### 1.4 Assets (Layer 2): manifests and instructions

- [ ] **Step 1: Write the failing test.** In `runtime-py/tests/test_tool_manifest.py`, find the golden test
  (`test_the_golden_records_the_order_the_wire_actually_serves`). Regenerate
  `runtime-py/tests/data/served-tool-surface.json` the way that test's docstring says, so `memory_queries` is the
  fifteenth entry. That happens in 1.5; here only the asset loaders are tested:

```python
def test_memory_queries_asset_and_instructions_load():
    from bantamkit.assets import load_skill, load_tool
    t = load_tool("memory_queries")
    assert t.name == "memory_queries"
    assert load_skill("memory-queries").startswith("# Likely-prompt queries")
    assert "queries" in load_tool("memory_save").parameters["properties"]
```

- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Write the assets.**

  In `assets/tools/memory_save.json`, add a property beside `keywords`:

```json
      "queries": {
        "type": "array",
        "items": {"type": "string"},
        "description": "The prompts a user would type when this fact is what they need: three in the user's language and three in English, at most 8, each at most 200 characters"
      }
```

  `assets/tools/memory_queries.json` (NEW):

```json
{
  "name": "memory_queries",
  "title": "Likely-prompt queries for saved facts",
  "description": "Call with {} to list up to 10 facts that have no likely-prompt queries yet, with what to write for them. Call with {\"facts\": [{\"name\", \"layer\"?, \"queries\"}]} to store queries you wrote. Recall matches a prompt against these queries.",
  "surfaces": ["mcp"],
  "parameters": {
    "type": "object",
    "properties": {
      "facts": {
        "anyOf": [
          {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "layer": {"type": "string", "description": "project, profile, extra:<name> or native; optional: the first layer holding the name"},
            "queries": {"type": "array", "items": {"type": "string"}}
          }, "required": ["name", "queries"]}},
          {"type": "null"}
        ],
        "description": "Omit to list the facts missing queries"
      }
    },
    "title": "memory_queriesArguments",
    "additionalProperties": false
  },
  "output_schema": {"type": "object", "additionalProperties": true, "title": "memory_queriesDictOutput"},
  "annotations": {"readOnlyHint": false, "destructiveHint": false, "openWorldHint": false}
}
```

  Write it in the formatting of `work_plan.json`, which is the house style (indent 2). Then check that
  `tools/list` serves it the way `_from_manifest` builds `work_plan`'s schema. In particular, check whether
  `parameters` must carry `required` and whether pydantic adds `"title": "Facts"`. Copy whatever `work_plan.json`
  does for an optional list.

  `assets/skills/memory-queries.md` (NEW) holds the Q7 text, from the J72-19 generator brief:

```markdown
# Likely-prompt queries

For each fact, write the prompts a user would type to a coding assistant when this fact is what they need.

- Three in the user's own language and three in English (`queries` holds all six, the user's language first).
- Short: 5 to 25 words. Vary them: one direct question, one task request, one terse follow-up.
- Keep technical terms in English where the user would: commands, file names, product names, error codes.
- Use only what the fact says. Do not invent facts, do not just restate the fact's name, and never copy more than
  five words of the body verbatim.

Store them with `memory_queries` (`{"facts": [{"name": ..., "layer": ..., "queries": [...]}]}`), or pass
`queries` to `memory_save` when you save the fact.
```

  In `assets/skills/memory.md`, insert after "## Writing the description":

```markdown
## Likely-prompt queries

When you save, also pass `queries`: three prompts in the user's language and three in English that a user would
type when this fact is what they need. Short and varied, technical terms kept in English, never more than five
words copied from the body. When `memory_queries` lists facts without queries, write theirs.
```

- [ ] **Step 4: Run the test and confirm it passes.** Then run the whole pytest suite: `test_layers.py`
  golden byte-identity and the `memory.md` pins named by
  `git grep -ln "skills/memory.md" runtime-py/tests runtime-ts/test` may need their goldens regenerated. Do that the
  way each test's docstring says, never by weakening the test.
- [ ] **Step 5: Commit** the four asset paths, the test and any regenerated golden:
  `feat(assets): memory_queries manifest, queries on memory_save, the Q7 instructions (#207 amendment 3)`.

#### 1.5 `mcpserver.py` (Layer 5): `memory_save(queries)`, `memory_queries`, status line

- [ ] **Step 1: Write the failing tests.**
  - `runtime-py/tests/test_mcpserver.py`: a stdio round trip that calls `memory_queries` with `{}`, then
    `{"facts":[...]}`, then a refused item. Follow the existing in-process client helper in that file.
  - `runtime-py/tests/test_status_surface.py`: the status report holds `queries: 0 of 0 facts` as its last line
    before any problems block. With one fact that has queries it holds `queries: 1 of 1 facts`. With
    `Memory.queries_coverage` monkeypatched to raise `OSError` it holds `queries: unavailable`.
  - The served-tool golden: 15 tools, `memory_queries` LAST.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**

```python
    def memory_save(type: str, name: str, description: str, body: str, links: list[str] | None = None,
                    keywords: list[str] | None = None, queries: list[str] | None = None) -> str:
        with _record_raise(log, "memory_save"):
            outcome = memory.save_outcome(type, name, description, body, links, keywords, queries)
        ...

    def memory_queries(facts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return _noted_dict(_record_result(
            log, "memory_queries",
            lambda: memory.queries_missing() if facts is None else memory.queries_write(facts)))
```

  Append `_from_manifest(memory_queries, "memory_queries")` LAST in `tools` (after `shiftwork_plan`, line 2045). Read
  the ordering comment at 2014-2029 first: appending is the only edit that keeps every other tool where it is.

  In `status_report`, add this after `memory_usage.status_line(...)` (line 1024):

```python
        _queries_line(memory),
```

  with:

```python
def _queries_line(memory: Memory) -> str:
    try:
        return memory_queries_mod.status_line(*memory.queries_coverage())
    except Exception:  # noqa: BLE001 - a status report never raises over one line
        return "queries: unavailable"
```

- [ ] **Step 4: Run the tests and confirm they pass.** Run the full pytest suite and ruff.
- [ ] **Step 5: Commit** `mcpserver.py`, the tests and the golden: `feat(mcp): memory_queries, the fifteenth tool; queries on memory_save and in status (#207 amendment 3)`.

#### 1.6 `hookadapter.py` (Layer 5): the head (Q3) and the SessionStart nudge (Q8)

- [ ] **Step 1: Write the failing tests** in `runtime-py/tests/test_hookadapter.py`. The helper `rec(**kw)` dumps
  one JSONL record.

```python
from bantamkit import hookadapter as H


def _rec(text=None, *, content=None, **kw):
    r = {"type": "user", "message": {"content": text if content is None else content}, **kw}
    return json.dumps(r, ensure_ascii=False)


def test_previous_prompt_rules(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join([
        _rec("first prompt"),
        _rec("side", isSidechain=True),
        _rec("meta", isMeta=True),
        _rec("<command-name>/clear</command-name>"),
        _rec("[Request interrupted by user]"),
        _rec(content=[{"type": "tool_result", "content": "x"}]),
        json.dumps({"type": "assistant", "message": {"content": "hi"}}),
        _rec(content=[{"type": "text", "text": "  second "}, {"type": "text", "text": "part"}]),
        "not json",
        _rec("current"),
    ]) + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "current") == "second \npart"
    assert H._previous_prompt(str(t), "other") == "current"


def test_previous_prompt_drops_the_partial_first_line_of_the_tail(tmp_path):
    t = tmp_path / "t.jsonl"
    head = _rec("x" * (H.TAIL_BYTES + 10))  # this whole line straddles the 256 KiB boundary
    t.write_text(head + "\n" + _rec("kept") + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == "kept"
    t.write_text(head + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == ""


def test_previous_prompt_never_raises(tmp_path):
    assert H._previous_prompt(str(tmp_path / "missing.jsonl"), "x") == ""
    assert H._previous_prompt(str(tmp_path), "x") == ""  # a directory
    assert H._previous_prompt("", "x") == ""


def test_head_query_only_for_short_prompts(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(_rec("p" * 600) + "\n", encoding="utf-8")
    assert H._head_query("ok?", str(t)) == "ok?\n" + "p" * 500
    assert H._head_query("x" * 79, str(t)) is not None
    assert H._head_query("x" * 80, str(t)) is None
    assert H._head_query("\U0001F414" * 79, str(t)) is not None  # 79 code points, 158 UTF-16 units
    assert H._head_query("ok?", str(tmp_path / "none.jsonl")) is None
```

  End to end: a `UserPromptSubmit` payload with a short prompt and a `transcript_path` whose previous prompt names a
  fact must inject that fact. The same payload without `transcript_path` must not. Follow the existing
  `_user_prompt_submit` tests in this file.

  SessionStart: a project store with one fact and no sidecar must put S12 in the context: `[bantamkit] 1 of 1 facts
  have no likely-prompt queries yet; call mcp__bantamkit__memory_queries with {} to list them and write their
  queries.` After `queries_write`, it must not. With zero facts there is no line.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**

```python
# #207 amendment 3 (Q3): the session head. A prompt shorter than HEAD_SHORT code points borrows the session's
# previous prompt (its first HEAD_CUT code points) for its BM25F query; the queries vector keeps the bare prompt.
HEAD_SHORT = 80
HEAD_CUT = 500
TAIL_BYTES = 262144
_NOT_A_PROMPT = ("<", "[Request interrupted")


def _user_text(message: dict[str, Any]) -> str | None:
    """`tools/eval/recall/mine_silver._user_text`, the rule the measured head was built with."""
    c = message.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(parts) if parts else None
    return None


def _previous_prompt(transcript: str, current: str) -> str:
    """The latest main-chain user prompt before `current`, from ONE read of the transcript's last TAIL_BYTES.

    A tail that does not start at byte 0 drops everything through its first newline (a cut line). Records are
    split on "\\n" only. A trailing run of prompts equal to `current` is dropped: the host may or may not have
    written the current prompt before this hook runs. Any failure is "" -- the hook never errors here.
    """
    try:
        if not transcript:
            return ""
        with open(transcript, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            start = max(0, size - TAIL_BYTES)
            f.seek(start)
            raw = f.read(TAIL_BYTES)
        if start > 0:
            cut = raw.find(b"\n")
            raw = b"" if cut < 0 else raw[cut + 1 :]
        prompts: list[str] = []
        for line in raw.decode("utf-8", errors="replace").split("\n"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict) or r.get("isSidechain") or r.get("isMeta") or r.get("type") != "user":
                continue
            msg = r.get("message")
            if not isinstance(msg, dict):
                continue
            x = _user_text(msg)
            if x is None or not x.strip() or x.lstrip().startswith(_NOT_A_PROMPT):
                continue
            prompts.append(x.strip())
        while prompts and prompts[-1] == current:
            prompts.pop()
        return prompts[-1] if prompts else ""
    except Exception:  # noqa: BLE001 - Q3: any failure is no head
        return ""


def _head_query(prompt: str, transcript: str) -> str | None:
    if len(prompt) >= HEAD_SHORT:
        return None
    prev = _previous_prompt(transcript, prompt)
    return f"{prompt}\n{prev[:HEAD_CUT]}" if prev else None
```

  At line 1289, change the call to read the head first:
  `head = _head_query(prompt, _js_str(payload.get("transcript_path") or ""))` and then
  `o = m.recall_outcome(prompt, 3, stamp=False, context=touch, head=head)`.

  In `_session_start`, add this after the Toolbox `parts.append(...)` (1066-1072), in its own try:

```python
    try:
        n, m_ = Memory.layered(cwd, native=native.dir).queries_coverage()
        if n < m_:
            parts.append(
                f"[bantamkit] {m_ - n} of {m_} facts have no likely-prompt queries yet; call "
                "mcp__bantamkit__memory_queries with {} to list them and write their queries."
            )
    except Exception as e:  # noqa: BLE001 - a nudge is never worth a dead session
        _log(run, {"event": "SessionStart", "warn": f"queries: {_message(e)}"})
```

- [ ] **Step 4: Run the tests and confirm they pass.** Run the full suite and ruff.
- [ ] **Step 5: Commit** `hookadapter.py` and its tests:
  `feat(hooks): the short-prompt session head and the queries nudge (#207 amendment 3, Q3/Q8)`.

---

### Task 2: Node: the same surfaces in `runtime-ts/src/`

Mirror Task 1 name for name (snake_case to camelCase) and sentence for sentence. Python is the reference: every
difference is a defect unless `docs/porting.md` rules it (`retrieval.ts:4-5`). Run
`cd runtime-ts && npm ci && npm run build && npm run sync-assets` once. Then before every test run,
`npm run build && npm run sync-assets`; `sync-assets` copies the Task 1.4 assets into the package.

**Files:** as in the file map, Node rows. Tests:
- `runtime-ts/test/queries.test.mjs` (NEW): the ports of `test_memory_queries.py`, every case with the same
  expected values.
- `runtime-ts/test/hookadapter.test.mjs`: head and S12.
- `runtime-ts/test/server.test.mjs`: tool list of fifteen, `memory_queries` round trip, status line.
- `runtime-ts/test/retrieval.test.mjs`: `QUERY_WEIGHT`, `stripNospace`, `QueryScorer`.

Every test file starts with `import './_sandbox.mjs';` (`test/_sandbox.mjs`).

**Interfaces (produces, Node):**

```ts
// memory/retrieval.ts
export const QUERY_WEIGHT = 1.0;
export function stripNospace(text: string): string;          // iterate by CODE POINT: for (const ch of text)
export class QueryScorer implements Scorer {                   // dense = true; label/used 'bm25f+queries'
  constructor(prompt: string);
  column(cols: Columns, vecs: ReadonlyArray<unknown> | null): number[] | null;
}
// Scorer.column's vecs is widened from ReadonlyArray<Float32Array | null> to ReadonlyArray<unknown> (line 314);
// RowsOf (store.ts:737) likewise. No dense scorer exists on main besides this one.

// memory/queries.ts
export const SIDECAR_VERSION = 1, MAX_QUERIES = 8, MAX_QUERY_CHARS = 200, LIST_LIMIT = 10, BODY_EXCERPT = 600;
export const QUERIES_DIR = 'queries'; export const WRITE_FAILED = 'the sidecar could not be saved';
export function sidecarPath(home: string, root: string): string;          // uses storage/hotindex.ts sha16
export function readSidecar(p: string): Map<string, string[]>;            // never throws
export function qdoc(queries: readonly string[]): string;
export function checkQueries(queries: unknown): string[];                 // throws MemoryValidationError(S1|S2|S3)
export function factSha(p: string | null): string;
export function writeEntries(p: string, entries: Map<string, [string[], string] | null>): void;
export function statusLine(n: number, m: number): string;

// memory/store.ts / native.ts
export function poolOf(facts: readonly Fact[], q: readonly string[], everyRow = false): Pool;
MemoryStore.pool(q, skipped?, everyRow = false); NativeStore.pool(q, skipped?, shadow = EMPTY, everyRow = false)

// memory/component.ts (Memory)
save(type, name, description, body, links = null, keywords = null, queries: string[] | null = null): string;
saveOutcome(..., queries: string[] | null = null): SaveOutcome;
recallOutcome(query, k = null, minRatio = ..., stamp = true, includeArchived = false, context = null,
              head: string | null = null): RecallOutcome;
injectCandidates(prompt: string, head: string | null = null): Fact[];
rankAll(prompt: string, depth = 50, head: string | null = null): Fact[];
queriesMissing(limit = LIST_LIMIT): Record<string, unknown>;
queriesWrite(facts: unknown[]): Record<string, unknown>;
queriesCoverage(): [n: number, m: number];

// pysem.ts
export function pyLstrip(s: string): string;     // ^PY_WS_CLASS+ removed
export function pyTruthy(v: unknown): boolean;   // Python truthiness of a parsed JSON value

// hookadapter.ts
export const HEAD_SHORT = 80, HEAD_CUT = 500, TAIL_BYTES = 262144;
export function previousPrompt(transcript: string, current: string): string;
export function headQuery(prompt: string, transcript: string): string | null;
```

Port traps. Each one is a parity case in Task 3:

1. **Code points, not UTF-16 units.** Use `[...s].length` and `Array.from(s).slice(0, n).join('')` for the 80, 500,
   200 and 600 limits. `String.length` is wrong for astral characters (`hookadapter.py:1256-1259` pins the same
   trap for `chars`).
2. **Read the sidecar with `parseJson` from `runtime-ts/src/pyjson.ts:568`, not `JSON.parse`.** Python's
   `type(v) is int` rejects `1.0` and `true`. `JSON.parse` collapses `1.0` to `1`, and only a PyValue keeps the
   difference. Decode with `new TextDecoder('utf-8', { fatal: true })`: Python's strict decode raises on `\xff`.
3. **Transcript lines use Python's json semantics** (`parseJson`; `NaN` is accepted, as `json.loads` accepts it).
   `isSidechain`/`isMeta` are tested with `pyTruthy`. `x.strip()` is `pyStrip`, and `x.lstrip().startswith` is
   `pyLstrip(x).startsWith`. The tail decodes with a non-fatal `TextDecoder` (U+FFFD), which is Python's
   `errors="replace"`.
4. **Write the sidecar with `dumpIndex`** (`storage/hotindex.ts:246`: sortKeys by code point, `ensureAscii: false`,
   compact separators) under `exclusive` from `storage/lock.ts:21`. Use a tmp file `<name>.<pid>.tmp`, then
   `renameSync`.
5. **`QueryScorer.column` sums without rounding**, exactly as the Python one does.
6. **Order the `memory_queries` list with `cmpCodepoint`** (`pysem.ts:78`), never `.sort()`.

Sub-tasks 2.1 to 2.6 mirror 1.1 to 1.6, one commit each, with the same TDD steps. The tests are the Python ones,
ported with identical inputs and identical expected strings. Each port's code is the Python code of the same
sub-task with the traps above applied. The MCP wiring is listed here because it has no Python shape:

- `mcp/pyargs.ts` `ARG_MODELS` (108): `memory_save.fields` gains `opt('queries', 'listStr')`. Add
  `memory_queries: { model: 'memory_queriesArguments', fields: [opt('facts', 'listDict')] }`. `listDict` is what
  `work_plan` uses (line 232).
- `mcp/server.ts`: append `'memory_queries'` LAST in `MCP_TOOLS` (113-128). Update the doc comment's "The
  fourteen" to "The fifteen". In `case 'memory_save'` (575), read `queries` exactly as `keywords` is read (577-578)
  and pass it to `saveOutcome`. Add `case 'memory_queries'`. Its answer goes through the same result-recording path
  `work_plan` uses (`grep -n "case 'work_plan'" runtime-ts/src/mcp/server.ts`):
  `facts === null ? memory.queriesMissing() : memory.queriesWrite(facts)`.
- `mcp/status.ts` (500): add `queriesLine(memory)` after `statusLine(...)`, with the same try/catch to
  `queries: unavailable`.
- `hookadapter.ts` (1401): `const head = headQuery(prompt, String(input.transcript_path ?? ''));` and pass it as
  `recallOutcome`'s 7th argument. In `sessionStart`, add S12 after the Toolbox line (1178), in its own try.

**Done when:** `cd runtime-ts && npm test` is green and prints its final count line. Every Python test of Task 1 has
a Node twin with the same expected values. `node tools/conformance/run.mjs --suite wire` is green: it compares
`tools/list` frame by frame, so the fifteenth tool must match byte for byte.

---

### Task 3: Conformance: the spec's "Parity and conformance" cases, wired into `--all`

**Files:**
- Create: `tools/conformance/suites/recall-queries.mjs` (`export const name = 'recall-queries'`). It is
  discovered by directory (`run.mjs:23`), so nothing in `run.mjs` changes.
- Create: `tools/conformance/ref/queries_ref.py`, the Python side. Follow `ref/retrieval_ref.py` and
  `ref/recall_gate_ref.py`: one JSON request in, one JSON answer out, every bed under the harness scratch with
  `HOME`, `USERPROFILE`, `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off` pinned per side.
- Modify: `tools/conformance/suites/hooks.mjs` for the head end to end and S12. Use the payload shapes at 2355 and
  2575.
- Modify: `tools/conformance/suites/instructions.mjs`. Add clause-(a) rows: S12 names `memory_queries`, and
  `memory-queries.md` names `memory_queries` and `memory_save`'s `queries`. Both must resolve on the served
  surface of each side.
- Modify: `docs/conformance.md`: add a suite row with the measured mutation reds.

Each case below is differential (Python and Node agree) unless marked **literal**. A literal case compares EACH side
to a typed constant and is the only kind that sees a symmetric regression (`recall-gate.mjs` header).

**Ranking**
1. `rank/mixed`: a mixed Thai/English pool (project + profile + native layers, a name shadowed between project and
   native), sidecars on two layers. Compare the ranked `injectCandidates`/`inject_candidates` names and
   `rankAll(depth 10)`. Add a **literal** of the expected names per side.
2. `rank/no-queries-fact`: facts with no entry score exactly their BM25F (the per-row column, through a ref hook
   on `QueryScorer.column`).
3. `rank/thai-only-query`: a qdoc made only of Thai scores 0. **Literal** `0.0` per side.
4. `rank/query-only-hit`: a prompt with no BM25F term hit but a qdoc hit injects the fact. **Literal** names.
5. `rank/no-sidecar-is-b`: the same tree with no sidecar. Each side's `recall_outcome` reply must be
   byte-identical to the reply that side gives with the `queries` reading forced off. The ref has a flag that skips
   reading sidecars, so this case compares B to B on one side. Plus a differential.
6. `rank/files-equals-index`: the same recall inside `snapshot()` (files path) and outside it (index path), with a
   sidecar. All four answers must be equal.
7. `sidecar/malformed`: each malformed text from `test_a_malformed_sidecar_reads_as_absent`, plus `\xff` and a
   per-entry bad shape. The `readSidecar` maps must be equal, with a **literal** `{}` per side for the whole-file
   cases.

**Head**
8. `head/rules`: the Task 1.6 transcript fixture (short and long prompt, sidechain, meta, `<command-name>`,
   interrupted, tool_result-only, text-block list, a not-JSON line, current prompt last), compared through
   `previousPrompt`. Add a **literal** per side.
9. `head/boundary`: a first line cut at the 256 KiB boundary; a file of exactly `TAIL_BYTES`; one byte over.
10. `head/missing`: a missing file, a directory, `""`. **Literal** `""`.
11. `head/short-limit`: `headQuery` at 79, 80 and 81 code points, plus an astral 79-code-point prompt. **Literal**
    null/non-null.
12. `hooks/userpromptsubmit-head`: in `hooks.mjs`, both hook processes on one bed with a transcript must inject the
    same names, and the head must change the inject relative to the same payload without `transcript_path`.

**Write paths**
13. `save/sidecar-bytes`: `memory_save` with `queries` over each server's stdio. The two sidecar files must be
    byte-identical; `sha` is computed from identical fact bytes, so it is equal.
14. `save/cross-read`: a Python-written sidecar read by Node gives the same ranking, and the reverse.
15. `save/limits`: 9 queries, a 201-code-point query, an astral 200-code-point query (accepted), and a non-string
    item through the component API. Each refusal is a **literal** sentence (S1/S2/S3) per side.
16. `save/write-fails`: `queries` is a file, not a directory. The reply ends with S4 on both sides, and the fact is
    saved.
17. `memory_queries/list`: same `{"result":"missing",...}` document, including `remaining`, the 600-code-point body
    cut and the instructions text.
18. `memory_queries/write` and `memory_queries/refusals`: S5, S6, S7, S8 and S9. Each is a **literal** sentence per
    side, and the sidecar is byte-unchanged after a refusal.

**Reporting**
19. `status/queries-line`: S10 for `0 of 0`, `1 of 2`, `2 of 2`; S11 under an unreadable project store. Each
    `bantamkit_status` line is compared per side, and the whole report minus `build` is compared.
20. `sessionstart/nudge`: S12 present when `n < m`, absent when `n == m` or `m == 0` (in `hooks.mjs`).
21. `constants`: every row of the shared-constants table, **literal** per side.
22. The tool count, the `memory_queries` schema and the `memory_save` schema are already compared byte for byte by
    `wire.mjs`'s `tools/list`. Check that `--suite wire` names `memory_queries`. No CLI `-h` text is touched.

**Mutations: each case proven red.** Run them on an rsync copy with the plan's `mut.sh`, never in place. Record the
red count for each in the note and in `docs/conformance.md`.

| # | mutation (one side unless stated) | must redden |
|---|---|---|
| M1 | Node `stripNospace` returns its input | 3, 1 |
| M2 | Python `QUERY_WEIGHT = 0.5` | 21, 1 |
| M3 | BOTH sides `QUERY_WEIGHT = 0.5` | 21 (literal only) |
| M4 | Node `HEAD_SHORT` compares `prompt.length` (UTF-16) | 11 |
| M5 | Python keeps the cut first line of the tail | 9 |
| M6 | Node does not skip `isSidechain` | 8 |
| M7 | Python `pool_of` ignores `every_row` | 6, 4 |
| M8 | Node `dumpIndex` without `sortKeys` in `writeEntries` | 13 |
| M9 | Python S2 says "chars" for "characters" | 15 |
| M10 | Node `QueryScorer.dense = false` | 4 |
| M11 | Node `readSidecar` uses `JSON.parse` | 7 (`v: 1.0`) |
| M12 | Python status line "query" for "queries" | 19 |
| M13 | Node drops the trailing-current-prompt rule | 8 |

- [ ] **Step 1:** Write `queries_ref.py` and the suite with cases 1 to 11 and 13 to 21. Run
  `TMPDIR=<scratch>/cleantmp/ node tools/conformance/run.mjs --suite recall-queries`. It must be green on the Task
  1 + 2 tree.
- [ ] **Step 2:** Add cases 12 and 20 to `hooks.mjs` and the rows to `instructions.mjs`. Run those suites and
  `--suite wire`.
- [ ] **Step 3:** Run M1 to M13 on rsync copies and record the red counts. A mutation that stays green means its
  case does not guard anything: fix the case, never the mutation
  (`prove-the-case-red-before-claiming-it-guards`).
- [ ] **Step 4:** Run `TMPDIR=<scratch>/cleantmp/ node tools/conformance/run.mjs --all` and quote its final PASS
  line.
- [ ] **Step 5:** Commit the suite, the ref, `hooks.mjs`, `instructions.mjs` and `docs/conformance.md` with a
  pathspec commit: `test(conformance): recall-queries suite and head/nudge cases (#207 amendment 3)`.

---

### Task 4: Measurement: Q10 fidelity and Q9 latency

This is private work in the MAIN checkout (`/Users/kktest/Documents/Claude/Projects/bantamkit`). Scripts go under
`.shiftwork/notes-job72/J72-<n>-scripts/`, and only the scripts and the note are force-added. No eval text reaches a
tracked file. The product under test is THIS worktree's code: run with
`/Users/kktest/Documents/Claude/Projects/bantamkit-207q/.venv/bin/python` and confirm `bantamkit.__file__` is inside
`bantamkit-207q`. Sandbox `HOME`/`USERPROFILE`/`BANTAMKIT_INDEX_DIR`/`BANTAMKIT_RETENTION=off`, and snapshot the
real `~/.bantamkit` before and after.

**Q10, fidelity** (a reproduction of the look-6 policy, not a new look):

- [ ] **Step 1: Load the sidecars.**
  1. rsync the frozen stores (`$S/stores`, the J72-20 layout) into the sandbox.
  2. For every frozen fact file, read its J72-19 row (`cache/J72-19-q2d.q*.jsonl`) by `gen_kw.key(name, desc, kws,
     body)`, as `probe20.py`'s `fmap` does.
  3. Write `queries = th + en` into the sidecar of the store copy that holds the fact. Use `queries.write_entries`
     at `queries.sidecar_path(sandbox_home, <store copy root>)`, with `fact_sha(file)`.
  4. Assert that every q2d key landed (`probe20.py`'s coverage assertions).
- [ ] **Step 2: Dev, 60 of 60.** For each dev prompt, compute `prev1 = prev[id][-1][:500]` from
  `cache/J72-12-prev.jsonl` and `head = prompt + "\n" + prev1` when `len(prompt) < 80 and prev1`, else `None`. Then
  call `Memory.layered_for_eval(project=..., profile=..., native=...).inject_candidates(prompt, head=head)`.
  - Assert the names equal `probe20` results `inject["G6-G5-l1.0"][id]` for 60 of 60.
  - Then rerun with `prev` from the product's own `hookadapter._previous_prompt(<the prompt's transcript>,
    prompt)`, wherever the transcript is still on disk (read-only on `~/.claude/projects`). Report how many of the
    60 agree with the J72-12 `prev`. This measures the head-extraction deviation in Open question 1, and is never
    tuned against it.
- [ ] **Step 3: Gold, 50 of 50.** Gold follows the same procedure with `goldlook22.py`'s `prev` rule.
  - BEFORE any gold file is read, append one line to `.shiftwork/notes-job72/gold-looks.jsonl`:
    `{"kind": "reproduction", "of": "J72-22 look 6", ...}`. It is not a look. Ask the orchestrator first if that
    line shape is not acceptable (Open question 6).
  - Assert the names equal `J72-22-gold-inject-G6.json` for 50 of 50.
  - Score nothing. The look-6 numbers stand.
- [ ] **Step 4: Repeat Steps 2 and 3 through the Node product**, `runtime-ts/dist/memory/component.js`
  `Memory.layeredForEval(...).injectCandidates(prompt, head)`, on the same sandbox. Assert 60/60 and 50/50 again.
- [ ] **Step 5: On any mismatch, stop.** Print the first differing prompt's id (never its text) and both lists, and
  report it. Never adjust the product to fit unless the plan's PROPERTY was violated.

**Q9, latency** (the real Node hook, `tools/hooks/bantamkit-hook.mjs`):

- [ ] **Step 6: Bench.** Bench `UserPromptSubmit` over the 60 dev prompts.
  - Pass a short-prompt `transcript_path` fixture of at least 256 KiB, built from synthetic records with no private
    text.
  - Compare three arms on the same sandbox: main `2eb426b` built in a separate worktree, this branch with no
    sidecar, and this branch with the loaded sidecars.
  - Take 11 runs per prompt and the median per prompt, then p50/p90/max over prompts, unindexed and indexed. Follow
    `J72-20-scripts/lat20.mjs` / `J72-22-scripts/lat22.mjs`.
  - Bar: the p50 rise is at most 5 ms (Q9).
- [ ] **Step 7: Report the rise.** Report the rise of the sidecar arm over main, and of the no-sidecar arm over
  main, which must be about 0. If the bar fails, report it and stop; do not optimize inside this unit (Open question
  7 names the fallback).
- [ ] **Step 8: Commit the scripts and the note** in the MAIN checkout on `feat/207-recall-embedding` with a
  pathspec `git add -f`.

---

## Open questions and ambiguities (named, not resolved silently)

1. **The head's "current prompt" rule differs from the measured one.** The eval (`goldlook22.py:151-202`, J72-12
   `prev.py`) takes the prompt before the FIRST occurrence of the current prompt in the whole transcript. The hook
   cannot know where "the current one" is. The host may or may not have written it before `UserPromptSubmit` runs.
   The plan drops a trailing run of entries equal to the current prompt and takes the last remaining one. The two
   rules differ:
   - when the user repeated a prompt earlier in the session;
   - when the previous prompt lies before the 256 KiB tail;
   - when a record holds a raw U+2028 or U+2029. The eval split with `str.splitlines()`; the product splits on
     `"\n"`.

   Task 4 Step 2 counts the agreement. The ruling needed: is this rule acceptable, or must the hook first verify
   (one real transcript, read-only) whether the current prompt is already written?
2. **Pool rows: the files path must hold every fact once a sidecar exists.** This is the `every_row` change in 1.3.
   Q2 says "over the pool's qdocs", but a files pool holds hit rows only. The plan picks every fact, which
   reproduces the probe's index-path pools and keeps the files path equal to the index path. Confirm.
3. **`queries` omitted versus `[]` on `memory_save`.** The plan treats `[]` as delete and omission as untouched. An
   updated fact then keeps stale queries until they are rewritten. The `sha` is recorded but, per the plan, read by
   nobody: scoring cannot check it without reading every fact file, which the hook must not do. The open choice is
   whether `memory_queries {}` should also list facts whose current file sha differs from the recorded one. That
   costs one read per fact at list time, which is affordable, but the spec does not say.
4. **Limit violations refuse the whole save.** Q5 says writing queries "is best-effort: a failure there never fails
   the save", and the parity section says "Limits are enforced with the same sentences". The plan reads a limit
   violation as a caller error and refuses before anything is written (`refused-validation`). An IO failure is the
   best-effort case (S4). The alternative is to save the fact and drop the queries with a note.
5. **What `queries: N of M facts` counts.** The plan counts distinct names over all readable layers in precedence
   order: a name held by two layers counts once, at its first layer, and native names shadowed by a bantamkit layer
   are dropped. The spec only says "facts". The project store alone would be the other reading.
6. **Gold in Q10.** The spec calls it "a reproduction of the look-6 policy, not a new look", yet it reads gold
   prompts again. The plan logs a `reproduction` line in `gold-looks.jsonl` before reading gold. Confirm the line,
   or rule that no line is written.
7. **Q9 risk.** Every recall with a sidecar tokenizes every qdoc of every layer: about 6 prompts per fact, NFKC and
   tokenize, in a fresh hook process. `probe20.py`'s COST block measured only `bm25_scores` in Python on the probe's
   stores. A 5,000-fact store is untested. If Task 4 busts 5 ms, the fallback is a derived per-sidecar term cache,
   which is a format and spec change. It is not planned here.
8. **Duplicate names inside one store** (two files claiming one name, which only happens on the files path) share
   one sidecar entry. The probe keyed on content. Rare, and unmeasured.
9. **Orphaned entries.** `memory_dream`/`memory_compact` archive or merge facts and leave their sidecar entries
   behind. Those entries are harmless: coverage counts live facts only. Nothing collects them; nothing in the spec
   asks.
10. **Unit boundary versus the clock-in invariant.** The invariant reads "Both runtimes + a conformance case in the
    same unit", while this brief orders Python, then Node, then conformance as separate units. Repo CLAUDE.md allows
    separate units inside ONE job ("separate units of work — but they belong to the SAME job"). On that reading the
    job is not done before Task 3 lands. If the invariant is meant literally, Tasks 1 to 3 must be one unit.
11. **Halfwidth katakana and CJK compatibility ideographs** (U+FF66-FF9D, U+F900-FAFF) are not in `_NOSPACE`
    before NFKC but become no-space after it. Stripping before tokenizing, as the probe did, leaves them as bigrams.
    The plan reproduces this for fidelity and pins it in `test_strip_nospace...`. It is a quirk, not a choice.

## Self-review against the spec

- Every spec row maps to a sub-task:
  - Q1 → 1.2/2.2
  - Q2 → 1.1, 1.3, 2.1, 2.3
  - Q3 → 1.6/2.6
  - Q4 → 1.3: `_pooled` serves both `recall_outcome` and `inject_candidates`
  - Q5 → 1.3, 1.5
  - Q6 → 1.3, 1.4, 1.5
  - Q7 → 1.4
  - Q8 → 1.5, 1.6
  - Q9, Q10 → Task 4
  - Q11: nothing imports `node:http`; check with `git grep -n "node:http" runtime-ts/src`, which finds nothing new
  - Q12: no platform branch
- Every parity bullet maps to Task 3 cases 1 to 22.
- No step says "TBD". Where a step defers to an existing file's convention, the file and line are named.
- The names are consistent across tasks: `QueryScorer`, `strip_nospace`/`stripNospace`, `read_sidecar`/`readSidecar`,
  `write_entries`/`writeEntries`, `queries_missing`/`queriesMissing`, `queries_write`/`queriesWrite`,
  `queries_coverage`/`queriesCoverage`, `_previous_prompt`/`previousPrompt`, `_head_query`/`headQuery`, `head`.

## Gates (every task)

- `.venv/bin/python -m pytest runtime-py/tests -q`
- `cd runtime-ts && npm run build && npm run sync-assets && npm test`
- `.venv/bin/ruff check runtime-py tools`
- `TMPDIR=<scratch>/cleantmp/ node tools/conformance/run.mjs --suite <touched>`, and `--all` before the final commit
  of Task 3.

Quote each gate's final count line in the unit note.
