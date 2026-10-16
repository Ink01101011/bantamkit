# Recall by Meaning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo every multi-unit run goes through the shiftwork tools (CLAUDE.md); the unit map is at the end.

**Goal:** Make the UserPromptSubmit hook and `memory_recall` inject fewer, more relevant facts, including for Thai prompts (issue #199, milestone 0.37.0-beta).

**Architecture:** A new retrieval module per runtime holds the script-aware tokenizer (`tokenize_v2`), a BM25F scorer, the gate and the ranker. A new usage module holds an append-only usage ledger, kept apart from the fact files. `Memory.recall_outcome` (the hook and the tool share it) now pools candidates from every layer, scores them once, gates and ranks them. Fact files gain an optional `keywords` field and lose `last_recalled` writes. Old facts are read-repaired when the agent first uses them.

**Tech Stack:** Python 3.10+ (`runtime-py`, stdlib only: `unicodedata`, `math`, `json`, `hashlib`); TypeScript on Node ≥ 20 (`runtime-ts`, no new dependency); conformance harness `tools/conformance/run.mjs`; pytest; `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-15-recall-by-meaning-design.md` (D1–D8).

## Global Constraints

- Every feature lands in BOTH `runtime-py/` and `runtime-ts/` in the same unit, with a conformance case comparing the two (CLAUDE.md, "Two runtimes, one surface").
- No new runtime dependency on either side. The npm install stays pure Node, with no Python at runtime.
- Must run on Windows and macOS. The only lock primitive is `O_EXCL` (Python `os.O_CREAT | os.O_EXCL`, Node `flag: 'wx'`), as `hookadapter` uses it.
- The hook writes nothing: no usage event and no fact file.
- Hook p50 on Node may rise by at most 5 ms over the ~38 ms measured after #172.
- Bar, fixed before any number exists:
  - precision@inject ≥ 0.8 on gold;
  - recall@3 on gold ≥ the current engine's;
  - Thai-prompt recall@3 > 0;
  - hook p50 rise ≤ 5 ms.
- The gold set is held out: no constant may be tuned on it.
- Every new conformance case:
  - is proven red by a one-sided mutation;
  - at least one symmetric mutation per suite is proven red by a per-side literal (`literalCases` shape in `tools/conformance/suites/recall-gate.mjs:398`).
- Never weaken or delete an existing case. A case that pins old behaviour on purpose is changed only where this plan names it, with the user ruling cited.
- Probes use a throwaway `HOME` under `$TMPDIR` and never touch the real `~/.bantamkit` or `~/.claude`.
- Conformance runs with `TMPDIR=<scratchpad>/cleantmp/` and after `cd runtime-ts && npm run build`.
- Gates before every commit:
  - `.venv/bin/python -m pytest runtime-py/tests -q`
  - `cd runtime-ts && npm test`
  - `.venv/bin/ruff check runtime-py tools`
  - `node tools/conformance/run.mjs --all`

## Start state

- Cut the implementation branch `feat/199-recall-by-meaning` from `main` **after** the 0.36.0 PR (job67) merges. It changes `assets/tools/*.json` (`additionalProperties: false`, `title`, `annotations`), and Task 3 edits `memory_save.json` on top of that.
- Fresh tree: `python3 -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"`, then `cd runtime-ts && npm ci && npm run sync-assets && npm run build`.
- Today the recall score is `len(tokens(name+" "+description) & tokens(query))`:
  - Python: `runtime-py/src/bantamkit/memory/store.py:300` (`tokens`) and `:695` (`recall`).
  - Node: `runtime-ts/src/memory/store.ts:450` (`tokens`) and `:953` (`recall`).
  - The gate is `RECALL_MIN_SCORE_RATIO = 0.0`, applied per layer.
  - The hook calls `recall_outcome(prompt, 3, stamp=False)` at `runtime-py/src/bantamkit/hookadapter.py:1203` (Node mirror in `runtime-ts/src/hookadapter.ts`).
- `tokens` (v1) and `jaccard` stay unchanged: dream/dedupe depends on them (spec, out of scope).

## File Structure

| File | Responsibility |
|---|---|
| `runtime-py/src/bantamkit/memory/retrieval.py` (new) | `tokenize_v2`, `Bm25Scorer`, `gate`, `rank`, every tuning constant |
| `runtime-ts/src/memory/retrieval.ts` (new) | Byte-for-byte port of the above |
| `runtime-py/src/bantamkit/memory/usage.py` (new) | `UsageLedger`: path, append, decayed weights, last use, keyword copies, fold |
| `runtime-ts/src/memory/usage.ts` (new) | Port of the above |
| `runtime-py/src/bantamkit/memory/store.py` | `Fact.keywords`; `save(..., keywords=())`; `candidates()`; `recall` routed through retrieval; no `last_recalled` writes; `repair()` |
| `runtime-ts/src/memory/store.ts`, `factfile.ts` | Same on Node; `formatFact` writes `keywords` |
| `runtime-py/src/bantamkit/memory/component.py`, `runtime-ts/src/memory/component.ts` | `recall_outcome`/`recallOutcome` pools candidates across layers, then scores, gates and ranks once; records usage; read-repairs |
| `assets/tools/memory_save.json` | `keywords` parameter |
| `assets/` MCP instructions (the file `mcpserver.py` serves as `instructions`) | One sentence on `keywords` in the user's language |
| `tools/conformance/suites/recall-retrieval.mjs` + `ref/retrieval_ref.py` (new) | Tokenizer, BM25, gate, ranker parity |
| `tools/conformance/suites/recall-usage.mjs` + `ref/usage_ref.py` (new) | Ledger parity |
| `tools/conformance/suites/store.mjs`, `recall-gate.mjs`, `recall-strings.mjs` | `keywords` round-trip; the T7 gate change; read-repair |
| `tools/eval/recall/` (new) | `mine_silver.py`, `build_gold.py`, `score.py`, `bar.json`, `gold-label.html` |
| `tools/release/publish.sh` | Prerelease version mapping (Task 9) |
| `docs/memory.md`, `docs/porting.md`, `docs/hooks.md` | The new behaviour, and divergence rows if any |

---

### Task 0: Eval harness, silver set, predeclared bar, baseline

**Files:**
- Create: `tools/eval/recall/bar.json`, `tools/eval/recall/mine_silver.py`, `tools/eval/recall/score.py`, `tools/eval/recall/build_gold.py`, `tools/eval/recall/test_eval_recall.py`
- Output (gitignored, under `.shiftwork/notes-<job>/`): `silver.jsonl`, `gold-candidates.jsonl`, `baseline.json`

**Interfaces:**
- Produces:
  - `score.py --engine {v1,v2} --set {silver,gold} --labels <jsonl> --store-root <dir> --profile-root <dir>` prints one JSON line `{"precision_at_inject": float, "recall_at_3": float, "thai_recall_at_3": float, "n": int}`.
  - `mine_silver.py --projects ~/.claude/projects --out silver.jsonl` writes lines `{"prompt": str, "positives": [fact_name], "thai": bool, "session": str}`.
  - `build_gold.py --silver silver.jsonl --n 50 --thai-min 20 --k 5 --out gold-candidates.jsonl` writes lines `{"id": int, "prompt": str, "candidates": [fact_name x5], "thai": bool}`.

- [ ] **Step 1: Commit the bar before anything is measured**

```json
{
  "declared": "2026-10-15",
  "spec": "docs/superpowers/specs/2026-10-15-recall-by-meaning-design.md",
  "precision_at_inject_min": 0.8,
  "recall_at_3_min": "baseline_v1_gold",
  "thai_recall_at_3_min_exclusive": 0.0,
  "hook_p50_rise_ms_max": 5.0,
  "gold_is_held_out": true
}
```

Run: `git add tools/eval/recall/bar.json && git commit -m "eval(recall): declare the bar before any number exists (#199)"`

- [ ] **Step 2: Write the failing tests for the miner and the scorer**

```python
# tools/eval/recall/test_eval_recall.py
import json
from pathlib import Path

from tools.eval.recall.mine_silver import mine_transcript, is_thai
from tools.eval.recall.score import metrics


def _line(obj):
    return json.dumps(obj) + "\n"


def test_prompt_followed_by_recall_call_labels_positive(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        _line({"type": "user", "message": {"content": "ช่วยดู release lessons หน่อย"}})
        + _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__bantamkit__memory_recall",
             "input": {"query": "release-0-35-4-out-on-both-registries"}}]}})
    )
    rows = list(mine_transcript(t, known={"release-0-35-4-out-on-both-registries"}))
    assert rows == [{"prompt": "ช่วยดู release lessons หน่อย",
                     "positives": ["release-0-35-4-out-on-both-registries"],
                     "thai": True, "session": "s"}]


def test_read_of_memory_file_labels_positive(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        _line({"type": "user", "message": {"content": "what did we decide on tags"}})
        + _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/x/memory/merge-authorized-standing-tag-withheld.md"}}]}})
    )
    rows = list(mine_transcript(t, known={"merge-authorized-standing-tag-withheld"}))
    assert rows[0]["positives"] == ["merge-authorized-standing-tag-withheld"]
    assert rows[0]["thai"] is False


def test_is_thai():
    assert is_thai("กิน context ไหม") and not is_thai("eats context?")


def test_metrics_precision_and_recall():
    injected = {1: ["a", "b"], 2: [], 3: ["c"]}
    gold = {1: {"a"}, 2: {"d"}, 3: {"x"}}
    ranked = {1: ["a", "b", "z"], 2: ["d", "q", "r"], 3: ["c", "x", "y"]}
    m = metrics(injected, ranked, gold, thai_ids={2})
    assert m["precision_at_inject"] == 1 / 3      # a ok, b no, c no
    assert m["recall_at_3"] == 3 / 3              # a, d, x all inside top 3
    assert m["thai_recall_at_3"] == 1.0
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `.venv/bin/python -m pytest tools/eval/recall/test_eval_recall.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.eval.recall.mine_silver'` (add an empty `tools/eval/recall/__init__.py` and `tools/eval/__init__.py` if the package root needs them; check how `tools/` is imported by existing tests first: `grep -rn "from tools\." runtime-py/tests tools | head`).

- [ ] **Step 4: Implement the miner and the scorer**

```python
# tools/eval/recall/mine_silver.py
"""Silver labels: a user prompt is positive for a fact the agent then asked for by name or read."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterator

_THAI = re.compile(r"[฀-๿]")
_MEMFILE = re.compile(r"/memory/([a-z0-9][a-z0-9-]*)\.md$")


def is_thai(text: str) -> bool:
    return bool(_THAI.search(text))


def _user_text(msg: dict) -> str | None:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(parts) if parts else None
    return None


def mine_transcript(path: Path, known: set[str]) -> Iterator[dict]:
    prompt: str | None = None
    hits: list[str] = []

    def flush():
        if prompt and hits:
            yield {"prompt": prompt, "positives": sorted(set(hits)),
                   "thai": is_thai(prompt), "session": path.stem}

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") or {}
        if rec.get("type") == "user":
            text = _user_text(msg)
            if text is not None and not text.startswith("<"):
                yield from flush()
                prompt, hits = text.strip(), []
        elif rec.get("type") == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                inp = b.get("input") or {}
                if b.get("name", "").endswith("memory_recall"):
                    q = str(inp.get("query", ""))
                    if q in known:
                        hits.append(q)
                elif b.get("name") == "Read":
                    m = _MEMFILE.search(str(inp.get("file_path", "")))
                    if m and m.group(1) in known:
                        hits.append(m.group(1))
    yield from flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", type=Path, required=True)
    ap.add_argument("--known", type=Path, nargs="+", required=True,
                    help="store roots whose facts/*.md names are the label space")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    known = {p.stem for root in a.known for p in (root / "facts").glob("*.md")}
    known |= {p.stem for root in a.known for p in root.glob("*.md")}  # auto-memory dirs
    with a.out.open("w", encoding="utf-8") as out:
        for t in sorted(a.projects.rglob("*.jsonl")):
            for row in mine_transcript(t, known):
                out.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
```

```python
# tools/eval/recall/score.py
"""Score an engine against labels. Prints one JSON line; never tunes anything."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def metrics(injected: dict[int, list[str]], ranked: dict[int, list[str]],
            gold: dict[int, set[str]], thai_ids: set[int]) -> dict[str, float]:
    inj = [(i, n) for i, names in injected.items() for n in names]
    precision = sum(1 for i, n in inj if n in gold[i]) / len(inj) if inj else 0.0

    def r3(ids):
        ids = [i for i in ids if gold[i]]
        if not ids:
            return 0.0
        return sum(len(set(ranked[i][:3]) & gold[i]) / len(gold[i]) for i in ids) / len(ids)

    return {"precision_at_inject": precision, "recall_at_3": r3(list(gold)),
            "thai_recall_at_3": r3([i for i in gold if i in thai_ids]), "n": len(gold)}


def _engine(name: str, store_root: Path, profile_root: Path):
    """Return (inject(prompt)->[names], rank(prompt)->[names]) over a COPY of the stores."""
    from bantamkit.memory.component import Memory
    m = Memory.layered_for_eval(project=store_root, profile=profile_root, engine=name)
    return (lambda p: [f.name for f in m.inject_candidates(p)],
            lambda p: [f.name for f in m.rank_all(p)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["v1", "v2"], required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    a = ap.parse_args()
    rows = [json.loads(x) for x in a.labels.read_text(encoding="utf-8").splitlines() if x]
    inject, rank = _engine(a.engine, a.store_root, a.profile_root)
    gold = {i: set(r["positives"]) for i, r in enumerate(rows)}
    print(json.dumps(metrics({i: inject(r["prompt"]) for i, r in enumerate(rows)},
                             {i: rank(r["prompt"]) for i, r in enumerate(rows)},
                             gold, {i for i, r in enumerate(rows) if r["thai"]})))


if __name__ == "__main__":
    main()
```

`Memory.layered_for_eval`, `inject_candidates` and `rank_all` are added in Task 5. Until then `score.py --engine v1` runs through a shim in the same file that calls today's `Memory.recall_outcome(prompt, 3, stamp=False)` for inject and `k=50` for rank. Write that shim now as the `v1` branch of `_engine`, and keep it afterwards as the baseline engine:

```python
    if name == "v1":
        from bantamkit.memory.component import Memory
        import os
        os.environ["BANTAMKIT_MEMORY_DIR"] = str(profile_root)
        m = Memory.layered(start=store_root)
        names = lambda o: [h.name for h in o.hits]  # recall_outcome exposes hits; check the field name
        return (lambda p: names(m.recall_outcome(p, 3, stamp=False)),
                lambda p: names(m.recall_outcome(p, 50, stamp=False)))
```

Before relying on `o.hits`, confirm what `recall_outcome` returns: `grep -n "class RecallOutcome" -A15 runtime-py/src/bantamkit/memory/component.py`. Use the field that carries the facts.

- [ ] **Step 5: Run the tests to see them pass**

Run: `.venv/bin/python -m pytest tools/eval/recall/test_eval_recall.py -q`
Expected: `4 passed`

- [ ] **Step 6: Mine silver, build gold candidates, measure the v1 baseline on COPIES of the real stores**

```bash
N=.shiftwork/notes-<job>; mkdir -p $N/stores
cp -R ~/.bantamkit/memory $N/stores/profile && cp -R .bantamkit/memory $N/stores/project
.venv/bin/python tools/eval/recall/mine_silver.py --projects ~/.claude/projects \
  --known $N/stores/profile $N/stores/project ~/.claude/projects/-Users-kktest-Documents-Claude-Projects-bantamkit/memory \
  --out $N/silver.jsonl
.venv/bin/python tools/eval/recall/build_gold.py --silver $N/silver.jsonl --n 50 --thai-min 20 --k 5 --out $N/gold-candidates.jsonl
.venv/bin/python tools/eval/recall/score.py --engine v1 --labels $N/silver.jsonl \
  --store-root $N/stores/project --profile-root $N/stores/profile | tee $N/baseline-silver.json
```

`build_gold.py` picks 50 silver prompts: at least 20 with `thai: true`, the rest by stratified random sampling with `random.Random(199)`. For each it lists 5 candidates: the silver positives, plus the v1 top hits, plus random facts, deduplicated and capped at 5. It never writes labels.

Expected: three files exist, and `baseline-silver.json` is one JSON line. Record every count in the unit note.

- [ ] **Step 7: Gold labelling page (orchestrator publishes it; the user labels)**

Create `tools/eval/recall/gold-label.html`:
- one static page that reads `gold-candidates.jsonl` pasted into a textarea;
- shows each prompt with five ✓/✗ toggles;
- has an "Export" button that downloads `gold-labels.jsonl`, one line per prompt: `{"id", "prompt", "positives": [...], "thai"}`.

The orchestrator publishes it as an artifact. The labels come back to `.shiftwork/notes-<job>/gold-labels.jsonl`. **Do not score gold in this task.**

- [ ] **Step 8: Commit**

```bash
git add tools/eval/recall/bar.json tools/eval/recall/mine_silver.py tools/eval/recall/score.py \
  tools/eval/recall/build_gold.py tools/eval/recall/test_eval_recall.py tools/eval/recall/gold-label.html
git commit -m "eval(recall): silver miner, gold candidate builder, scorer, labelling page (#199)"
```

---

### Task 1: `tokenize_v2` in both runtimes, with conformance

**Files:**
- Create: `runtime-py/src/bantamkit/memory/retrieval.py`, `runtime-ts/src/memory/retrieval.ts`, `runtime-py/tests/test_memory_retrieval.py`, `runtime-ts/test/retrieval.test.mjs`, `tools/conformance/suites/recall-retrieval.mjs`, `tools/conformance/ref/retrieval_ref.py`

**Interfaces:**
- Produces:
  - Python `tokenize_v2(text: str) -> list[str]`
  - Node `export function tokenizeV2(text: string): string[]`

  The result is a list, not a set: BM25 needs term frequency.

- [ ] **Step 1: Write the failing tests (same table on both sides)**

```python
# runtime-py/tests/test_memory_retrieval.py
import pytest
from bantamkit.memory.retrieval import tokenize_v2

CASES = [
    ("Release Lessons 0.35.9", ["release", "lessons", "0", "35", "9"]),
    ("กินบริบท", ["กิ", "ิน", "นบ", "บร", "ริ", "ิบ", "บท"]),
    ("B กิน context ไหม", ["b", "กิ", "ิน", "context", "ไห", "หม"]),
    ("ก", ["ก"]),
    ("记忆检索", ["记忆", "忆检", "检索"]),
    ("ｆｕｌｌｗｉｄｔｈ", ["fullwidth"]),
    ("café naïve", ["café", "naïve"]),
    ("🚀 ship-it!", ["ship", "it"]),
    ("", []),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_tokenize_v2(text, expected):
    assert tokenize_v2(text) == expected
```

```js
// runtime-ts/test/retrieval.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tokenizeV2 } from '../dist/memory/retrieval.js';

const CASES = [
  ['Release Lessons 0.35.9', ['release', 'lessons', '0', '35', '9']],
  ['กินบริบท', ['กิ', 'ิน', 'นบ', 'บร', 'ริ', 'ิบ', 'บท']],
  ['B กิน context ไหม', ['b', 'กิ', 'ิน', 'context', 'ไห', 'หม']],
  ['ก', ['ก']],
  ['记忆检索', ['记忆', '忆检', '检索']],
  ['ｆｕｌｌｗｉｄｔｈ', ['fullwidth']],
  ['café naïve', ['café', 'naïve']],
  ['🚀 ship-it!', ['ship', 'it']],
  ['', []],
];
for (const [text, expected] of CASES) {
  test(`tokenizeV2 ${JSON.stringify(text)}`, () => assert.deepEqual(tokenizeV2(text), expected));
}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_memory_retrieval.py -q`. Expected: `ModuleNotFoundError`.
Run: `cd runtime-ts && npm run build && node --test test/retrieval.test.mjs`. Expected: `Cannot find module …/retrieval.js`.

- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/memory/retrieval.py
"""Retrieval for recall (#199): script-aware tokens, BM25F, the gate and the ranker.

Byte-identical to runtime-ts/src/memory/retrieval.ts; `recall-retrieval` conformance pins it.
`store.tokens` (v1) is NOT replaced: dream/dedupe's Jaccard still runs on it.
"""
from __future__ import annotations

import unicodedata

# Scripts written WITHOUT spaces between words. Codepoint ranges, not a Unicode-database
# lookup, so the two runtimes cannot disagree through different Unicode versions.
_NOSPACE = (
    (0x0E00, 0x0E7F),  # Thai
    (0x0E80, 0x0EFF),  # Lao
    (0x1000, 0x109F),  # Myanmar
    (0x1780, 0x17FF),  # Khmer
    (0x3040, 0x30FF),  # Hiragana, Katakana
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified
)


def _nospace(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _NOSPACE)


def _wordchar(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LNM"


def tokenize_v2(text: str) -> list[str]:
    s = unicodedata.normalize("NFKC", text).lower()
    out: list[str] = []
    word: list[str] = []
    run: list[str] = []

    def flush_word():
        if word:
            out.append("".join(word))
            word.clear()

    def flush_run():
        if len(run) == 1:
            out.append(run[0])
        else:
            out.extend(run[i] + run[i + 1] for i in range(len(run) - 1))
        run.clear()

    for ch in s:
        if _nospace(ord(ch)):
            flush_word()
            run.append(ch)
        elif _wordchar(ch):
            flush_run()
            word.append(ch)
        else:
            flush_word()
            flush_run()
    flush_word()
    flush_run()
    return out
```

- [ ] **Step 4: Implement (Node)**

```ts
// runtime-ts/src/memory/retrieval.ts
/**
 * Port of runtime-py/src/bantamkit/memory/retrieval.py. The reference is Python; every
 * difference is a defect unless docs/porting.md rules it.
 */
const NOSPACE: Array<[number, number]> = [
  [0x0e00, 0x0e7f], [0x0e80, 0x0eff], [0x1000, 0x109f], [0x1780, 0x17ff],
  [0x3040, 0x30ff], [0x3400, 0x4dbf], [0x4e00, 0x9fff],
];
const nospace = (cp: number): boolean => NOSPACE.some(([lo, hi]) => cp >= lo && cp <= hi);
const WORDCHAR = /^[\p{L}\p{N}\p{M}]$/u;

export function tokenizeV2(text: string): string[] {
  const s = text.normalize('NFKC').toLowerCase();
  const out: string[] = [];
  let word = '';
  let run: string[] = [];
  const flushWord = () => { if (word) { out.push(word); word = ''; } };
  const flushRun = () => {
    if (run.length === 1) out.push(run[0]!);
    else for (let i = 0; i + 1 < run.length; i++) out.push(run[i]! + run[i + 1]!);
    run = [];
  };
  for (const ch of s) {               // iterates code points, as Python's str does
    if (nospace(ch.codePointAt(0)!)) { flushWord(); run.push(ch); }
    else if (WORDCHAR.test(ch)) { flushRun(); word += ch; }
    else { flushWord(); flushRun(); }
  }
  flushWord();
  flushRun();
  return out;
}
```

- [ ] **Step 5: Run the unit tests to see them pass**

Run both commands from Step 2. Expected: Python `9 passed`; Node `pass 9`, `fail 0`.

- [ ] **Step 6: Write the conformance suite (differential plus per-side literals)**

`tools/conformance/ref/retrieval_ref.py` follows `recall_gate_ref.py`'s protocol:
- strings travel as base64;
- `sys.path.insert(0, …/runtime-py/src)`;
- request `{"op": "tokenize", "texts": [b64...]}` returns `{"tokens": [[b64...], ...]}`.

`tools/conformance/suites/recall-retrieval.mjs`:

```js
export const name = 'recall-retrieval';
export const summary = 'tokenize v2, BM25F, gate and ranker: Python against Node (#199)';
const CORPUS = [
  'Release Lessons 0.35.9', 'กินบริบท', 'B กิน context ไหม', 'ก', '记忆检索', 'ｆｕｌｌｗｉｄｔｈ',
  'café naïve', '🚀 ship-it!', '', 'ภาษาไทยปน English 123', 'ΣΊΣΥΦΟΣ', 'é', 'ﬁ ligature',
  'ไม่มีช่องว่างเลยสักนิดเดียว', 'tab\tand\nnewline', 'カタカナとひらがな',
];
export async function run(ctx) {
  const r = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'retrieval.js')).href);
  const py = ctx.runPython(REF, { op: 'tokenize', texts: CORPUS.map(b64) });
  const cases = [];
  CORPUS.forEach((t, i) => cases.push({
    name: `tokenizeV2 ${JSON.stringify(t)}`, kind: 'json',
    expected: py.tokens[i].map(unb64), actual: r.tokenizeV2(t),
  }));
  // Per-side literals: a symmetric regression (both sides changed alike) is invisible above.
  const LIT = { 'B กิน context ไหม': ['b', 'กิ', 'ิน', 'context', 'ไห', 'หม'] };
  for (const [t, want] of Object.entries(LIT)) {
    cases.push({ name: `literal node ${t}`, kind: 'json', expected: want, actual: r.tokenizeV2(t) });
    const p = ctx.runPython(REF, { op: 'tokenize', texts: [b64(t)] }).tokens[0].map(unb64);
    cases.push({ name: `literal py ${t}`, kind: 'json', expected: want, actual: p });
  }
  return { cases, notes: [] };
}
```

Copy the imports and the `b64`/`unb64`/`REF` preamble from `recall-gate.mjs:52-70`. Check the exact case-object keys `run.mjs` expects (`kind` values) against `recall-gate.mjs` before you write.

- [ ] **Step 7: Prove the suite guards**

Run: `TMPDIR=<cleantmp> node tools/conformance/run.mjs --suite recall-retrieval`. Expected: `PASS … 0 failures`.

Run each mutation on an rsync copy of the tree, never in place:
- **M1:** Node `flushRun` emits unigrams instead of bigrams. Expect red on node only.
- **M2:** Python NFKC is dropped. Expect red on the fullwidth and ligature rows.
- **M3 (symmetric):** both sides add `0x0E00-0x0E7F` to word chars, so Thai becomes whole words. Expect red only on the two literal cases.

Record the red counts in the note.

- [ ] **Step 8: Commit**

```bash
git add runtime-py/src/bantamkit/memory/retrieval.py runtime-ts/src/memory/retrieval.ts \
  runtime-py/tests/test_memory_retrieval.py runtime-ts/test/retrieval.test.mjs \
  tools/conformance/suites/recall-retrieval.mjs tools/conformance/ref/retrieval_ref.py
git commit -m "feat(memory): script-aware tokenize_v2 in both runtimes, conformance-pinned (#199)"
```

---

### Task 2: BM25F scorer

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/retrieval.py`, `runtime-ts/src/memory/retrieval.ts`, both unit-test files from Task 1, `tools/conformance/suites/recall-retrieval.mjs`, `tools/conformance/ref/retrieval_ref.py`

**Interfaces:**
- Consumes: `tokenize_v2` / `tokenizeV2`.
- Produces:
  - Python `Doc(name: str, description: str, keywords: tuple[str, ...])`, plus `bm25_scores(query: str, docs: list[Doc]) -> list[float]` (same order as `docs`).
  - Node `interface Doc { name: string; description: string; keywords: string[] }`, plus `bm25Scores(query: string, docs: Doc[]): number[]`.
  - Constants: `BM25_K1 = 1.2`, `BM25_B = 0.75`, `FIELD_BOOST = {name: 2.0, description: 1.0, keywords: 2.0}`. `SCORE_ROUND = 9` decimals, applied before any comparison or sort.

- [ ] **Step 1: Failing tests**

```python
from bantamkit.memory.retrieval import Doc, bm25_scores

def test_bm25_rare_term_beats_common_term():
    docs = [Doc("a-context", "context context job", ()), Doc("b-tag", "release tag withheld", ()),
            Doc("c-job", "job context notes", ())]
    s = bm25_scores("tag context", docs)
    assert s[1] > s[0] and s[1] > s[2]

def test_bm25_thai_keyword_hits_english_fact():
    docs = [Doc("release-lessons", "how to run a release", ("ปล่อยเวอร์ชัน", "release")),
            Doc("other", "unrelated", ())]
    s = bm25_scores("ปล่อยเวอร์ชันยังไง", docs)
    assert s[0] > 0 and s[1] == 0

def test_bm25_empty_query_scores_zero():
    assert bm25_scores("", [Doc("x", "y", ())]) == [0.0]

def test_bm25_is_rounded():
    s = bm25_scores("alpha", [Doc("alpha", "alpha beta", ()), Doc("b", "beta", ())])
    assert s[0] == round(s[0], 9)
```

Mirror the same four tests in `retrieval.test.mjs`, with `bm25Scores` and `{name, description, keywords: [...]}`.

- [ ] **Step 2: Run them and see them fail** (`ImportError` and `bm25Scores is not a function`).

- [ ] **Step 3: Implement (Python, appended to retrieval.py)**

```python
import math
from dataclasses import dataclass

BM25_K1 = 1.2
BM25_B = 0.75
FIELD_BOOST = (("name", 2.0), ("description", 1.0), ("keywords", 2.0))
SCORE_ROUND = 9


@dataclass(frozen=True)
class Doc:
    name: str
    description: str
    keywords: tuple[str, ...]


def _fields(d: Doc) -> dict[str, list[str]]:
    # The kebab name is words too: "release-lessons" -> ["release", "lessons"].
    return {"name": tokenize_v2(d.name), "description": tokenize_v2(d.description),
            "keywords": tokenize_v2(" ".join(d.keywords))}


def bm25_scores(query: str, docs: list[Doc]) -> list[float]:
    q = list(dict.fromkeys(tokenize_v2(query)))  # unique, first-seen order
    if not q or not docs:
        return [0.0] * len(docs)
    tf: list[dict[str, float]] = []
    lens: list[float] = []
    for d in docs:
        f = _fields(d)
        weights: dict[str, float] = {}
        length = 0.0
        for field, boost in FIELD_BOOST:
            for t in f[field]:
                weights[t] = weights.get(t, 0.0) + boost
            length += boost * len(f[field])
        tf.append(weights)
        lens.append(length)
    n = len(docs)
    avgdl = (sum(lens) / n) or 1.0
    out: list[float] = []
    for weights, dl in zip(tf, lens):
        s = 0.0
        for t in q:
            w = weights.get(t, 0.0)
            if w == 0.0:
                continue
            df = sum(1 for other in tf if t in other)
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            s += idf * (w * (BM25_K1 + 1.0)) / (w + BM25_K1 * (1.0 - BM25_B + BM25_B * dl / avgdl))
        out.append(round(s, SCORE_ROUND))
    return out
```

- [ ] **Step 4: Implement (Node, appended to retrieval.ts)**

```ts
export const BM25_K1 = 1.2;
export const BM25_B = 0.75;
export const FIELD_BOOST: ReadonlyArray<[keyof Doc, number]> = [['name', 2.0], ['description', 1.0], ['keywords', 2.0]];
export const SCORE_ROUND = 9;
export interface Doc { name: string; description: string; keywords: string[] }

/** Python's round(x, 9): round-half-even on the decimal value. */
export function pyRound9(x: number): number {
  return Number(x.toFixed(SCORE_ROUND)) === x ? x : roundHalfEven(x, SCORE_ROUND);
}
```

Python's `round()` is round-half-even on the exact binary value. `toFixed` is round-half-up on the decimal expansion. Search for an existing port first: `grep -rn "half.even\|pyRound\|roundHalfEven" runtime-ts/src`, and reuse it if one exists. If none exists, implement `roundHalfEven` by computing `Math.round(x * 1e9) / 1e9`, then correcting the exact-half case with a `toPrecision(17)` check, and pin it with a conformance case over 1,000 random doubles against the Python reference (op `round9`). Ties at 1e-9 almost never occur in BM25 output, but the case makes sure they cannot split the ranking.

```ts
function fields(d: Doc): Record<'name' | 'description' | 'keywords', string[]> {
  return { name: tokenizeV2(d.name), description: tokenizeV2(d.description), keywords: tokenizeV2(d.keywords.join(' ')) };
}

export function bm25Scores(query: string, docs: Doc[]): number[] {
  const q = [...new Set(tokenizeV2(query))];
  if (q.length === 0 || docs.length === 0) return docs.map(() => 0.0);
  const tf: Array<Map<string, number>> = [];
  const lens: number[] = [];
  for (const d of docs) {
    const f = fields(d);
    const weights = new Map<string, number>();
    let length = 0;
    for (const [field, boost] of FIELD_BOOST) {
      for (const t of f[field as 'name']) weights.set(t, (weights.get(t) ?? 0) + boost);
      length += boost * f[field as 'name'].length;
    }
    tf.push(weights);
    lens.push(length);
  }
  const n = docs.length;
  const avgdl = lens.reduce((a, b) => a + b, 0) / n || 1.0;
  return tf.map((weights, i) => {
    let s = 0;
    for (const t of q) {
      const w = weights.get(t) ?? 0;
      if (w === 0) continue;
      let df = 0;
      for (const other of tf) if (other.has(t)) df += 1;
      const idf = Math.log(1.0 + (n - df + 0.5) / (df + 0.5));
      s += (idf * (w * (BM25_K1 + 1.0))) / (w + BM25_K1 * (1.0 - BM25_B + (BM25_B * lens[i]!) / avgdl));
    }
    return pyRound9(s);
  });
}
```

The summation order must match Python's: unique query tokens in first-seen order, and fields in `FIELD_BOOST` order. `Math.log` and `math.log` can differ in the last ulp. Rounding to 9 decimals absorbs that, and the conformance case below is what proves it on this corpus.

- [ ] **Step 5: Run the unit tests to see them pass** (both sides: the 4 new tests plus the 9 from Task 1).

- [ ] **Step 6: Conformance**

Add `op: "bm25"` to `retrieval_ref.py` (`{"query": b64, "docs": [{"name", "description", "keywords"} as b64]}` → `{"scores": [float]}`). In `recall-retrieval.mjs`, add one fixture store of 12 docs (mixed Thai and English, plus a doc with `keywords`) and 10 queries. Compare `scores` as JSON (`kind: 'json'`) and also compare the argsort. Add one per-side literal: the index of the top doc for `"tag context"` is `1` on each side.

Mutations:
- **M4:** Node `BM25_B = 0.0`.
- **M5:** Python drops the `keywords` field.
- **M6 (symmetric):** both sides use `idf = 1`. Must be red on the literal.

- [ ] **Step 7: Run the gates and commit** (`feat(memory): BM25F scorer over name/description/keywords (#199)`).

---

### Task 3: the `keywords` fact field

**Files:**
- Modify:
  - Python: `runtime-py/src/bantamkit/memory/store.py` (`Fact`, `_facts` parse, the fact formatter, `save`), `runtime-py/src/bantamkit/memory/component.py` (`Memory.save` passes it through), `runtime-py/src/bantamkit/mcpserver.py` (`memory_save` argument model)
  - Node: `runtime-ts/src/memory/factfile.ts` (`Fact`, `formatFact`), `runtime-ts/src/memory/store.ts` (parse, `save`), `runtime-ts/src/memory/component.ts`, `runtime-ts/src/mcp/` (`memory_save` dispatch and `pyargs`)
  - Assets: `assets/tools/memory_save.json`, plus the MCP instructions asset (find it: `grep -rln "Write it to match the future recall QUERY" assets`)
  - Tests: `tools/conformance/suites/store.mjs`, `tools/conformance/suites/wire.mjs` (served schema literal), `runtime-ts/test/packaging.test.mjs` (byte literal), `served-tool-surface.json`
- Test: `runtime-py/tests/test_memory.py`, `runtime-ts/test/store.test.mjs`

**Interfaces:**
- Produces:
  - `Fact.keywords: list[str]` (Python, default `[]`) and `keywords?: string[]` (Node). Read from frontmatter `keywords` when it is a list of strings. Any other shape is refused with `fact '<name>' in <file>: keywords must be a list of strings`.
  - `save(type, name, description, body, links=(), keywords=())`.
  - `formatFact` writes `keywords` **only when non-empty**, between `links` and the closing `---`. An empty list is omitted, so the bytes of a fact that never had keywords do not change.

- [ ] **Step 1: Failing tests**

```python
def test_save_writes_keywords_and_reads_them_back(tmp_path):
    s = MemoryStore(tmp_path, create=True)
    s.save("project", "release-lessons", "how to run a release", "body", keywords=("ปล่อยเวอร์ชัน", "publish"))
    text = (tmp_path / "facts" / "release-lessons.md").read_text(encoding="utf-8")
    assert "keywords:\n- ปล่อยเวอร์ชัน\n- publish\n" in text
    assert s.lookup("release-lessons", stamp=False).keywords == ["ปล่อยเวอร์ชัน", "publish"]

def test_fact_without_keywords_is_byte_identical_to_before(tmp_path):
    s = MemoryStore(tmp_path, create=True)
    s.save("project", "plain", "a plain fact", "body")
    assert "keywords" not in (tmp_path / "facts" / "plain.md").read_text(encoding="utf-8")

def test_keywords_wrong_shape_is_refused(tmp_path):
    (tmp_path / "facts").mkdir(parents=True)
    (tmp_path / "facts" / "bad.md").write_text(
        "---\nname: bad\ndescription: d\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\nkeywords: nope\n---\n\nb\n",
        encoding="utf-8")
    with pytest.raises(MemoryValidationError, match="keywords must be a list of strings"):
        MemoryStore(tmp_path).lookup("bad", stamp=False)
```

Mirror all three in `runtime-ts/test/store.test.mjs`.

Check how the YAML dumper renders non-ASCII. Python `yaml.safe_dump(allow_unicode=?)` decides whether Thai is written raw or escaped. Read the existing dumper (`grep -n "safe_dump\|allow_unicode" runtime-py/src/bantamkit/memory/store.py`). Then set the expected bytes in the test to whatever the reference writes, and make Node's `safeDumpMapping` match it. Do not change the reference's existing escaping for other fields.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement both sides.** Python:

```python
# store.py, Fact
    keywords: list[str] = field(default_factory=list)

# in _facts, beside links=list(meta.get("links") or []):
            raw_kw = meta.get("keywords", [])
            if not (isinstance(raw_kw, list) and all(isinstance(k, str) for k in raw_kw)):
                raise MemoryValidationError(
                    f"fact '{name}' in {path.name}: keywords must be a list of strings")
            ...
            keywords=list(raw_kw),
```

In the formatter, append `("keywords", fact.keywords)` to the mapping only when `fact.keywords` is non-empty. Node does the same in `formatFact`:

```ts
  const pairs: Array<[string, unknown]> = [
    ['name', fact.name], ['description', fact.description], ['type', fact.type],
    ['created', fact.created ?? null], ['last_recalled', fact.last_recalled ?? null], ['links', fact.links],
  ];
  if (fact.keywords && fact.keywords.length > 0) pairs.push(['keywords', fact.keywords]);
  const front = safeDumpMapping(pairs);
```

`last_recalled` is still written here. Task 5 stops writing it.

- [ ] **Step 4: Tool schema and instructions**

Add to `assets/tools/memory_save.json` `parameters.properties`:

```json
"keywords": {
  "type": "array",
  "items": {"type": "string"},
  "description": "Words the user will type when they need this fact, in the user's own language as well as English (e.g. Thai and English terms)"
}
```

Add one line to the MCP instructions under "Writing the description":
`Fill keywords with the words the user will actually type, in their language — recall matches those too.`
Then run `npm run sync-assets` and update the byte and schema literals that `npm test` and `--suite wire` name in their failure output. Take the new numbers from the failure messages, never from a guess.

- [ ] **Step 5: Conformance.** In `store.mjs`, add a scenario that saves with Thai keywords on both sides and compares the trees byte for byte, plus the wrong-shape refusal sentence on both sides. Mutation: Node writes `keywords: []` for an empty list. Expected: red on the byte-identical tree case.
- [ ] **Step 6: Run the four gates and commit** (`feat(memory): optional keywords on a fact, saved and served in both runtimes (#199)`).

---

### Task 4: Usage ledger

**Files:**
- Create: `runtime-py/src/bantamkit/memory/usage.py`, `runtime-ts/src/memory/usage.ts`, `runtime-py/tests/test_memory_usage.py`, `runtime-ts/test/usage.test.mjs`, `tools/conformance/suites/recall-usage.mjs`, `tools/conformance/ref/usage_ref.py`

**Interfaces:**
- Produces (Python; Node mirrors it in camelCase):
  - `store_id(store_root: Path) -> str`: the first 16 hex characters of `sha256(realpath(store_root) as UTF-8)`.
  - `UsageLedger(home: Path, store_root: Path)`. The path is `home/.bantamkit/usage/<store_id>.jsonl`, and `home` comes from `Path.home()` at the call site so tests can sandbox `HOME`.
  - `.append(fact: str, kind: Literal["recall_hit", "body_read", "save", "seed"], ts: str, keywords: list[str] | None = None) -> bool`. It returns False when the write failed, and never raises `OSError`.
  - `.weights(now: str) -> dict[str, float]`: `Σ 0.5 ** (age_days / USAGE_HALF_LIFE_DAYS)` over `recall_hit`, `body_read` and `seed` events, plus folded weights.
  - `.last_used(fact: str) -> str | None`: the latest `ts` of a use event.
  - `.keywords_copy(fact: str) -> list[str] | None`: the keywords from the latest `save` event.
  - `.skipped: int`: corrupt lines skipped on the last read.
  - `.fold(now: str) -> None`: runs when the line count exceeds `LEDGER_FOLD_LINES`.
- Constants: `USAGE_HALF_LIFE_DAYS = 14.0`, `LEDGER_FOLD_LINES = 5000`, `LOCK_WAIT_MS`/`LOCK_STALE_MS`/`LOCK_POLL_MS` copied from `hookadapter`'s ledger lock values.
- Line format: `json.dumps(obj, ensure_ascii=False, separators=(",", ":"))` with keys in the order `ts, fact, kind, keywords?, weight?`. Node uses `JSON.stringify` with the same key order. Both produce the same bytes for these shapes; the conformance case proves it.

- [ ] **Step 1: Failing tests**

```python
def test_weights_decay_by_half_life(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "recall_hit", "2026-10-01T00:00:00Z")
    led.append("a", "recall_hit", "2026-10-15T00:00:00Z")
    w = led.weights("2026-10-15T00:00:00Z")
    assert w["a"] == pytest.approx(1.0 + 0.5)

def test_save_events_do_not_count_as_use(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "save", "2026-10-15T00:00:00Z", keywords=["x"])
    assert led.weights("2026-10-15T00:00:00Z").get("a", 0.0) == 0.0
    assert led.keywords_copy("a") == ["x"]

def test_corrupt_line_is_skipped_and_counted(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "recall_hit", "2026-10-15T00:00:00Z")
    with led.path.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    assert led.weights("2026-10-15T00:00:00Z")["a"] == 1.0 and led.skipped == 1

def test_unwritable_ledger_returns_false(tmp_path):
    (tmp_path / ".bantamkit").mkdir()
    (tmp_path / ".bantamkit" / "usage").write_text("a file, not a dir")
    assert UsageLedger(tmp_path, tmp_path / "store").append("a", "recall_hit", "2026-10-15T00:00:00Z") is False

def test_fold_preserves_weights(tmp_path, monkeypatch):
    monkeypatch.setattr("bantamkit.memory.usage.LEDGER_FOLD_LINES", 10)
    led = UsageLedger(tmp_path, tmp_path / "store")
    for d in range(1, 13):
        led.append("a", "recall_hit", f"2026-10-{d:02d}T00:00:00Z")
    before = led.weights("2026-10-15T00:00:00Z")["a"]
    led.fold("2026-10-15T00:00:00Z")
    assert len(led.path.read_text(encoding="utf-8").splitlines()) == 1
    assert led.weights("2026-10-15T00:00:00Z")["a"] == pytest.approx(before)
```

Mirror all five in `usage.test.mjs`.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/memory/usage.py
"""Usage ledger (#199, D5): append-only events beside, never inside, the fact files."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

USAGE_HALF_LIFE_DAYS = 14.0
LEDGER_FOLD_LINES = 5000
LOCK_WAIT_MS = 2000      # copy the exact values from hookadapter's _LEDGER_LOCK_* constants
LOCK_STALE_MS = 10000
LOCK_POLL_MS = 10
_USE = ("recall_hit", "body_read", "seed")


def store_id(store_root: Path) -> str:
    real = os.path.realpath(store_root)
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]


def _parse(ts: str) -> float:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()


class UsageLedger:
    def __init__(self, home: Path, store_root: Path) -> None:
        self.path = home / ".bantamkit" / "usage" / f"{store_id(store_root)}.jsonl"
        self.skipped = 0

    def _events(self) -> list[dict]:
        self.skipped = 0
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                e = json.loads(line)
                if isinstance(e, dict) and isinstance(e.get("fact"), str) and isinstance(e.get("ts"), str):
                    out.append(e)
                    continue
            except json.JSONDecodeError:
                pass
            self.skipped += 1
        return out

    def append(self, fact: str, kind: str, ts: str, keywords: list[str] | None = None) -> bool:
        obj: dict = {"ts": ts, "fact": fact, "kind": kind}
        if keywords is not None:
            obj["keywords"] = list(keywords)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock():
                with self.path.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(line)
            return True
        except OSError:
            return False

    def weights(self, now: str) -> dict[str, float]:
        t_now = _parse(now)
        w: dict[str, float] = {}
        for e in self._events():
            if e.get("kind") == "folded":
                age = (t_now - _parse(e["ts"])) / 86400.0
                w[e["fact"]] = w.get(e["fact"], 0.0) + float(e["weight"]) * 0.5 ** (age / USAGE_HALF_LIFE_DAYS)
            elif e.get("kind") in _USE:
                age = max(0.0, (t_now - _parse(e["ts"])) / 86400.0)
                w[e["fact"]] = w.get(e["fact"], 0.0) + 0.5 ** (age / USAGE_HALF_LIFE_DAYS)
        return w

    def last_used(self, fact: str) -> str | None:
        ts = [e["ts"] for e in self._events() if e["fact"] == fact and e.get("kind") in (*_USE, "folded")]
        return max(ts) if ts else None

    def keywords_copy(self, fact: str) -> list[str] | None:
        found = None
        for e in self._events():
            if e["fact"] == fact and e.get("kind") == "save" and isinstance(e.get("keywords"), list):
                found = [k for k in e["keywords"] if isinstance(k, str)]
        return found

    def fold(self, now: str) -> None:
        """Fold every use into one `folded` line per fact (weight at `now`), keep the latest save."""
        ...
```

Finish `fold` under the lock:
1. Read the events.
2. Compute `weights(now)` and the latest `save` event per fact.
3. Write `{"ts": now, "fact", "kind": "folded", "weight": w}` per fact, plus each latest save line, to `<path>.<pid>.<8 hex>.tmp` opened with O_EXCL.
4. `os.replace` onto `path`.

`_lock()` is a context manager with the same O_EXCL loop as `hookadapter.py:414-438`, on `<path>.lock`. A writer that cannot take the lock within `LOCK_WAIT_MS` proceeds without it, because losing an event is better than failing a recall. `append` calls `fold` when the read line count exceeds `LEDGER_FOLD_LINES`, after its own write.

- [ ] **Step 4: Implement (Node)** in `runtime-ts/src/memory/usage.ts` with the same names in camelCase:
  - `createHash('sha256')` and `fs.realpathSync.native`;
  - `fs.openSync(lock, 'wx')` for the lock;
  - `fs.appendFileSync(path, line, {encoding: 'utf8'})` for appends;
  - the same temp-and-rename for fold;
  - `Date.parse(ts)` for timestamps, and `Math.pow(0.5, age / USAGE_HALF_LIFE_DAYS)`.

  Every `fs` error is caught and turned into the `false` return or an empty read, never thrown out.
- [ ] **Step 5: Run the unit tests to see them pass.**
- [ ] **Step 6: Conformance `recall-usage.mjs`**
  - Each side appends the same event script into its own sandboxed `HOME`.
  - Compare the ledger bytes, the `weights` (rounded to 9 places), `last_used`, `keywords_copy`, `skipped` after one corrupt line, and the bytes after `fold`.
  - Per-side literal: `weights` for the two-event decay fixture equals `1.5` on each side.
  - Mutations:
    - Node half-life 7: expect red.
    - Python counts `save` as use: expect red.
    - Symmetric `0.5 → 0.6`: expect red on the literal.
  - Windows note in the suite header: the lock path is exercised on macOS here; the Windows run is a manual step in Task 8.
- [ ] **Step 7: Run the gates and commit** (`feat(memory): usage ledger beside the store, decayed weights, fold under lock (#199)`).

---

### Task 5: Gate and ranker, wired into recall and the hook; stop writing `last_recalled`

**Files:**
- Modify:
  - `runtime-py/src/bantamkit/memory/retrieval.py`, `runtime-ts/src/memory/retrieval.ts` (`gate`, `rank`)
  - `runtime-py/src/bantamkit/memory/store.py`, `runtime-ts/src/memory/store.ts` (`candidates()`, `recall` routed through retrieval, `_stamp`/`stamp` → usage)
  - `runtime-py/src/bantamkit/memory/component.py`, `runtime-ts/src/memory/component.ts` (`recall_outcome` pools candidates across layers; adds `layered_for_eval`, `inject_candidates` and `rank_all` for `score.py`)
  - `runtime-py/src/bantamkit/hookadapter.py`, `runtime-ts/src/hookadapter.ts` (only if the call shape changes)
  - Every reader of `last_recalled`: find them with `grep -rn "last_recalled" runtime-py/src runtime-ts/src`; `compact` eviction is one of them
  - `tools/conformance/suites/recall-gate.mjs`, `recall-strings.mjs`, `store.mjs`

**Interfaces:**
- Consumes: `bm25_scores`, `Doc`, `UsageLedger.weights` / `.last_used`.
- Produces:
  - `gate(scores: list[float]) -> list[bool]`: True iff `s > 0 and s >= GATE_FLOOR and s >= GATE_RATIO * max(scores)`.
  - `rank(items: list[Candidate], scores: list[float], usage: dict[str, float]) -> list[int]`: indices of the eligible items, best first.
    - `Candidate(name: str, description: str, type: str, layer_order: int, keywords: tuple[str, ...])`.
    - `final = score * max(0.1, W_TYPE[type] + w_fresh + W_USAGE * log1p(usage.get(name, 0)) + W_CONTEXT * 0.0)`, rounded to 9 places.
    - Sort key: `(-final, layer_order, name)`.
  - Constants, with initial values that keep today's behaviour until Task 7 tunes them:
    - `GATE_FLOOR = 0.0`, `GATE_RATIO = RECALL_MIN_SCORE_RATIO` (0.0);
    - `W_TYPE = {"feedback": 1.3, "project": 1.1, "reference": 1.0, "user": 1.0}`;
    - `W_FRESH_DEMOTE = -0.5`, applied when `re.match(r"^\s*(SUPERSEDED|CLOSED|REFUTED)\b", description)`;
    - `W_USAGE = 0.2`;
    - `W_CONTEXT = 0.0` (the #200 slot).

- [ ] **Step 1: Failing tests (Python; mirror them in Node)**

```python
def test_gate_never_admits_zero():
    assert gate([0.0, 1.0]) == [False, True]

def test_rank_feedback_beats_reference_at_equal_score():
    c = [Candidate("r", "d", "reference", 0, ()), Candidate("f", "d", "feedback", 0, ())]
    assert rank(c, [1.0, 1.0], {}) == [1, 0]

def test_rank_superseded_is_demoted():
    c = [Candidate("old", "SUPERSEDED: x", "project", 0, ()), Candidate("new", "x", "project", 0, ())]
    assert rank(c, [1.0, 0.9], {}) == [1, 0]

def test_rank_usage_orders_but_never_admits():
    c = [Candidate("a", "d", "project", 0, ()), Candidate("b", "d", "project", 0, ())]
    assert rank(c, [1.0, 0.0], {"b": 100.0}) == [0]

def test_project_layer_breaks_ties_before_profile():
    c = [Candidate("z", "d", "project", 1, ()), Candidate("a", "d", "project", 0, ())]
    assert rank(c, [1.0, 1.0], {}) == [1, 0]

def test_hook_recall_writes_nothing(tmp_path, monkeypatch):
    # sandboxed HOME; a store with one fact; run the hook's recall path
    ...  # assert: fact file bytes unchanged AND no usage ledger file exists

def test_tool_recall_appends_recall_hit_and_not_last_recalled(tmp_path, monkeypatch):
    ...  # assert: fact file bytes unchanged; ledger has one recall_hit line for the hit
```

Write the two `...` bodies out in full against the real fixtures in `runtime-py/tests/test_memory_component.py`. Copy the store-building helper used there (`grep -n "def _store\|def make_store\|tmp_path" runtime-py/tests/test_memory_component.py | head`). The assertions are as commented.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**
  - **`gate` and `rank`:** as specified above, appended to `retrieval.py` and `retrieval.ts`.
  - **`MemoryStore.candidates(skipped=None) -> list[Fact]`:** the existing `_facts` listing, made public. In Node it is `candidates(skipped?)`.
  - **`Memory.recall_outcome(query, k, min_ratio=..., stamp=True)`:**
    1. Collect `(fact, layer_order)` from every layer in the order the layers are walked today: project = 0, extras = 1.., profile = last.
    2. Build `Doc`s and run `bm25_scores` **once over the pooled list**.
    3. Apply `gate`, then `rank` with `usage = UsageLedger(Path.home(), project_root).weights(now)`. When there is no project layer, the ledger keys on the first layer.
    4. Take `[:k]`.
    5. When `stamp` is true, call `append(name, "recall_hit", now)` for each hit **instead of** writing `last_recalled`.

    Keep the reply text format and the `[project]` / `[profile]` / `[extra:<name>]` tags exactly as they are. `recall-strings.mjs` pins them. The per-layer `min_ratio` semantics become pooled. That is a deliberate change from spec D3, and `docs/memory.md` is updated in Task 8.
  - **`lookup(name, stamp=True)`:** a hit appends `body_read` instead of stamping.
  - **`MemoryStore.recall` (the `--store` single-layer path):** the same pipeline with one layer.
  - **`compact` eviction and every other `last_recalled` reader:** `ledger.last_used(name) or fact.last_recalled or fact.created`.
- [ ] **Step 4: Run the unit tests, then `--all`.** Expected red, which you investigate and do not paper over:
  - `recall-gate` cases that pin per-layer gating. The ladder cases stay green with `GATE_RATIO = 0.0`. The layered cases may change, because pooling changes which top score the ratio is taken against.
  - `recall-strings` and `store` cases that compare trees after a recall: the fact files no longer change, and a ledger appears under `HOME`.

  For each red, decide whether it pins old behaviour on purpose. If it does, update the expected value **only** when this plan or spec D3/D5 names the change, cite `#199 D3` or `#199 D5` in the case name, and record before and after in the note. If a red is not explained by D3 or D5, stop and report it.
- [ ] **Step 5: Conformance.** Extend `recall-retrieval.mjs` with `gate` and `rank` over the Task 2 fixture plus a usage map. Extend `recall-strings.mjs` with a layered scenario that has a Thai `keywords` fact, so a Thai prompt recalls it on both sides with identical reply bytes. Mutations:
  - Node drops the `layer_order` tie-break.
  - Python counts hook injections as usage.
  - Symmetric `W_TYPE.feedback = 1.0`: must be red on a per-side literal.
- [ ] **Step 6: Hook latency.**
  - Run the measurement J67-5 used (find its command in `.shiftwork/notes-job67/J67-5.md`) before and after, with the same sandboxed store of 150 facts.
  - Expected: Node p50 rises by ≤ 5 ms. If it rises more, profile `bm25_scores` first (per-call `df` is O(q·n²)), precompute `df` once per call, then re-measure.
- [ ] **Step 7: Run the gates and commit** (`feat(memory): BM25 gate+ranker pooled across layers; usage replaces last_recalled writes (#199)`).

---

### Task 6: Read-repair

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/store.py`, `runtime-ts/src/memory/store.ts` (`repair(fact, ledger) -> bool`), `component.py`, `component.ts` (call it on the tool's hits only), `runtime-py/src/bantamkit/memory/component.py` and `runtime-ts/src/memory/component.ts` status counters, `bantamkit_status` output in both runtimes
- Test: `runtime-py/tests/test_memory.py`, `runtime-ts/test/store.test.mjs`, `tools/conformance/suites/store.mjs`

**Interfaces:**
- Produces:
  - `MemoryStore.repair(fact: Fact, ledger: UsageLedger, now: str) -> bool`. It returns True when it rewrote the file.
    - An old-format fact is one whose frontmatter has a non-null `last_recalled`, or whose `keywords` are missing while `ledger.keywords_copy(name)` is non-empty.
    - The repair appends `seed` at `last_recalled` (formatted `YYYY-MM-DDT00:00:00Z`), sets `keywords` from the copy, writes the fact with `last_recalled: null` through the existing atomic `writeFact`/`_write`, and returns True.
    - The format keeps the `last_recalled: null` line, so files stay parseable by 0.35.x.
  - **Unknown frontmatter keys survive (register row (mmmm), user ruling 2026-10-15).** Today a stamp rewrite drops any hand-written key (e.g. `priority: high`). `Fact` gains an ordered `extra` mapping of every frontmatter key the store does not own; the formatter re-emits them after the owned keys, in their original order, so neither `save` nor `repair` nor any other rewrite loses them. YAML comments cannot survive `safe_load` and are documented as lost. Add a test per side and a conformance tree case: a fact with `priority: high` keeps it through save, tool recall and repair.
  - The `bantamkit_status` memory section gains the line `read-repaired: <n> this process` and `usage ledger: <path> (<lines> lines, <skipped> skipped)`. Both runtimes must match, and the `recall-strings`/status cases pin it.

- [ ] **Step 1: Failing tests**

```python
def test_old_fact_is_repaired_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    s = MemoryStore(tmp_path / "store", create=True)
    s.save("project", "old", "an old fact", "b")
    p = tmp_path / "store" / "facts" / "old.md"
    p.write_text(p.read_text(encoding="utf-8").replace("last_recalled: null", "last_recalled: '2026-10-01'"), encoding="utf-8")
    led = UsageLedger(tmp_path / "home", tmp_path / "store")
    f = s.lookup("old", stamp=False)
    assert s.repair(f, led, "2026-10-15T00:00:00Z") is True
    assert "last_recalled: null" in p.read_text(encoding="utf-8")
    assert led.last_used("old") == "2026-10-01T00:00:00Z"
    assert s.repair(s.lookup("old", stamp=False), led, "2026-10-15T00:00:00Z") is False

def test_keywords_stripped_by_old_runtime_are_restored(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    s = MemoryStore(tmp_path / "store", create=True)
    led = UsageLedger(tmp_path / "home", tmp_path / "store")
    s.save("project", "kw", "fact", "b", keywords=("ปล่อย",))
    led.append("kw", "save", "2026-10-15T00:00:00Z", keywords=["ปล่อย"])
    p = tmp_path / "store" / "facts" / "kw.md"
    p.write_text(p.read_text(encoding="utf-8").replace("keywords:\n- ปล่อย\n", ""), encoding="utf-8")  # what 0.35.9 does
    assert s.repair(s.lookup("kw", stamp=False), led, "2026-10-15T00:00:00Z") is True
    assert s.lookup("kw", stamp=False).keywords == ["ปล่อย"]

def test_hook_path_never_repairs(tmp_path, monkeypatch):
    ...  # same old fact; run the hook recall; assert the file bytes are unchanged
```

`Memory.save` must append the `save` event, with keywords, to the ledger. Add that in this task if Task 5 did not.

- [ ] **Step 2: Run them and see them fail.** **Step 3: Implement both sides.** **Step 4: Run them and see them pass.**
- [ ] **Step 5: Conformance in `store.mjs`.**
  - A 0.35.9-shaped fact (non-null `last_recalled`) is repaired on the first tool recall, giving identical trees on both sides.
  - A second recall leaves the tree byte-unchanged.
  - The hook path leaves it unchanged.
  - Mutations:
    - Node repairs on the hook path: expect red.
    - Python repairs on every recall: expect red on the second-recall tree case.
- [ ] **Step 6: Run the gates and commit** (`feat(memory): read-repair old facts on first use; restore keywords an old runtime dropped (#199)`).

---

### Task 7: Tune on silver, freeze, score gold once

**Files:**
- Modify: the constants in `runtime-py/src/bantamkit/memory/retrieval.py` and `runtime-ts/src/memory/retrieval.ts` (`GATE_FLOOR`, `GATE_RATIO`, `W_*`), `tools/conformance/suites/recall-gate.mjs` (the relative-gate case, see below), `tools/eval/recall/tune.py` (new)
- Output: `.shiftwork/notes-<job>/tuning.json`, `gold-result.json`

- [ ] **Step 1: Write `tune.py`**
  - Grid search on the **silver set only**:
    - `GATE_FLOOR ∈ {0, 0.5, 1, 1.5, 2, 3}`
    - `GATE_RATIO ∈ {0, 0.3, 0.5, 0.7}`
    - `W_USAGE ∈ {0, 0.1, 0.2, 0.4}`
    - `W_TYPE.feedback ∈ {1.0, 1.3, 1.6}`
  - Objective: maximise recall@3 subject to precision@inject ≥ 0.85 on silver. The extra margin over the 0.8 bar is because silver is noisy.
  - It writes `tuning.json` with every grid point's metrics and the chosen point.
  - Constants are passed as overrides through `Memory.layered_for_eval(..., overrides={...})`, which Task 5 must accept for exactly these keys.
- [ ] **Step 2: Run it, then copy the chosen constants into BOTH `retrieval.py` and `retrieval.ts`.** Commit the constants with the tuning summary in the message.
- [ ] **Step 3: The deliberate case change.**
  - `recall-gate.mjs`'s RELATIVE-GATE case pins "the gate can never suppress a recall" (three facts all scoring 1 at `min_ratio = 1.0` return all three). With `GATE_FLOOR > 0`, a uniformly weak field can now return nothing. That is spec D2, the user's ruling 2026-10-15.
  - Do not delete the case. Rename it with `#199 D2` and change the expected value to what the floor yields.
  - Add a sibling case proving that a fact scoring at or above `GATE_FLOOR` is still admitted at `min_ratio = 1.0`.
  - If the tuned `GATE_FLOOR` is 0, the case stays as it is and nothing changes here.
- [ ] **Step 4: Run all four gates.**
- [ ] **Step 5: Score gold ONCE**
  - Run `score.py --engine v1` and then `--engine v2` on `gold-labels.jsonl`. Write both lines to `gold-result.json`.
  - Compare against `bar.json`. The v1 gold recall@3 is the `recall_at_3_min`.
  - Report PASS or MISS per criterion with the numbers.
  - On a MISS, change nothing. The orchestrator takes it to the user (spec: an embedding backend is the next lever).
- [ ] **Step 6: Commit** `tune.py` and the constants (`perf(memory): gate and weights tuned on silver; gold scored once (#199)`). The gold result goes in the note, not in the repo.

---

### Task 8: Docs, Windows check, reviewer

**Files:**
- `docs/memory.md`: recall ranking, the `keywords` field, the usage ledger, read-repair, and the pooled gate, replacing the per-layer gate paragraph.
- `docs/hooks.md`: the hook writes nothing; injection precision.
- `docs/porting.md`: any divergence rows (expected none).
- `docs/conformance.md`: the two new suites.
- `runtime-ts/README.md` / `runtime-py/README.md` module-API lines, if they list memory modules.
- `CHANGELOG` / release notes, if the repo keeps them (`ls CHANGELOG* docs/release*`).

- [ ] **Step 1: Write the docs.** Every number you quote must come from the Task 7 note, with the commit it was measured at.
- [ ] **Step 2: Windows.**
  - Run `npm test` and the `recall-usage` suite on the Windows box (or the Docker route from job63, if it covers Node on Windows; if not, list it as a manual step for the user).
  - Ledger append under concurrent writers: 20 parallel `node -e` appenders against one ledger. Expect exactly 20 lines.
- [ ] **Step 3: Reviewer unit (Opus).** It reads the diff against `main`, reruns the four gates and every mutation listed in Tasks 1–7, and checks that every spec section maps to code. It reports blockers. A blocker unit fixes them.
- [ ] **Step 4: Commit the docs** (`docs(memory): recall by meaning — ranking, keywords, usage ledger, read-repair (#199)`).

---

### Task 9: Prerelease plumbing for 0.37.0-beta

`tools/release/publish.sh` phase 0 requires `package.json` = `__init__.__version__` exactly. A beta is spelled `0.37.0-beta.1` on npm (semver) and `0.37.0b1` on PyPI (PEP 440), so the preflight refuses it as it stands. A beta must also go to npm under `--tag beta`, so that `@latest`, which every user config runs, does not move to it.

**Files:**
- Modify: `tools/release/publish.sh` (version mapping and dist-tag), plus its test if one exists (`ls tools/release`)
- Modify: `docs/release-npm.md`

- [ ] **Step 1: Failing test.** If `tools/release` has a test harness, add a case for preflight with `__version__ = "0.37.0b1"` and `package.json` `"0.37.0-beta.1"`, expecting both `ok` lines. If it has none, add `tools/release/test_version_map.sh` asserting the output of `map_pep440_to_semver 0.37.0b1` is `0.37.0-beta.1`, the same for `0.37.0rc2 → 0.37.0-rc.2`, and that `0.36.0` passes through unchanged.
- [ ] **Step 2: Implement.**

```bash
map_pep440_to_semver() {   # 0.37.0b1 -> 0.37.0-beta.1 ; 0.37.0rc2 -> 0.37.0-rc.2 ; 0.36.0 -> 0.36.0
  printf '%s\n' "$1" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+)a([0-9]+)$/\1-alpha.\2/; s/^([0-9]+\.[0-9]+\.[0-9]+)b([0-9]+)$/\1-beta.\2/; s/^([0-9]+\.[0-9]+\.[0-9]+)rc([0-9]+)$/\1-rc.\2/'
}
```

- Phase 0 compares `package.json` and the lock file against `map_pep440_to_semver "$version"`.
- The `npm publish` line adds `--tag beta` when the mapped version contains `-`. A stable release behaves exactly as before.
- The PyPI wheelhouse pin in `runtime-py/README.md` uses the PEP 440 spelling.
- [ ] **Step 3: Dry run.**
  - In a scratchpad worktree, bump to `0.37.0b1` / `0.37.0-beta.1` and run `tools/release/publish.sh --dry-run`.
  - Expected: phase 0 shows every version check `ok`, and the dry run prints `npm publish … --tag beta`.
  - Do not publish. Publishing is the user's step.
- [ ] **Step 4: Commit** (`release: prerelease versions map PEP 440 <-> semver and publish under the beta dist-tag`).

---

## Shiftwork unit map (job68 checkpoint)

| Unit | Task | Depends on | Role / model |
|---|---|---|---|
| J68-0 | Task 0 eval harness + silver + baseline | — | implementer / claude-opus-5-5 |
| J68-1 | Task 1 tokenize_v2 | — | implementer / claude-opus-5-5 |
| J68-2 | Task 2 BM25F | J68-1 | implementer |
| J68-3 | Task 3 keywords field | J68-1 | implementer |
| J68-4 | Task 4 usage ledger | — | implementer |
| J68-5 | Task 5 gate+ranker wiring | J68-2, J68-3, J68-4 | implementer |
| J68-6 | Task 6 read-repair | J68-5 | implementer |
| J68-7 | Task 7 tune + gold | J68-0, J68-6, **gold labels from the user** | implementer |
| J68-8 | Task 8 docs + Windows + reviewer | J68-7 | reviewer / claude-opus-5-5 |
| J68-9 | Task 9 prerelease plumbing | — | implementer |
| J68-10 | blockers from J68-8 | J68-8 | implementer |

**Width:**
- Wave 1: J68-0, J68-1, J68-4, J68-9.
- Wave 2: J68-2, J68-3. They share `retrieval.*` and `store.*` only at different hunks, but both edit `recall-retrieval.mjs`, so run them one after the other.

**The one user step inside the job:** labelling gold. J68-7 waits on `gold-labels.jsonl`.

**Release:** after merge, bump to `0.37.0b1` / `0.37.0-beta.1`; the user runs `publish-0.37.0-beta.1.command`; then create the tag `v0.37.0-beta.1`, a GitHub prerelease, and move milestone 0.37.0-beta items as they close. #200 gets its own brainstorm, spec and plan inside the same milestone before the beta is cut, or a second beta (`b2`) carries it. That is the user's call when #199 lands.
