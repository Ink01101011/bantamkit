# Recall by meaning, round two: a Scorer interface and an opt-in embedding backend

**Issue #207** (the follow-up to #199). Branch `design/207-recall-embedding`, cut from main
`71ba1e4` (0.37.0-beta.1). The user agreed this design on 2026-10-17. Decisions marked **(user)**
are the user's. Decisions marked **(default)** are the orchestrator's, made where the user did not
rule, and the user accepted them with the rest of the design.

> **Shipped state (job71, 2026-10-17).** The D8 bar MISSED, so per §6.7 only §1 (the `Scorer` interface
> and `Bm25fScorer`) ships. The ollama scorer, vector cache, `memory embed`, the status lines and the
> `BANTAMKIT_EMBED*` / `OLLAMA_HOST` / `EMBED_GATE` surfaces described below were built and measured but
> are NOT in this tree; they stay on the local `feat/207-recall-embedding` branch. Results:
> docs/memory.md (#207 note) and the issue.

## Why round two

#199 shipped a pooled BM25F ranker and missed its predeclared bar. On pooled gold, view B scored
precision@inject 0.432 against a bar of 0.8. The gold is UNVALIDATED: the calibrated judge agreed
with the user at 0.68 with kappa 0.24, against a bar of 0.9 and 0.6. The #199 spec's rule on a miss
is to report it, never move the bar, and only then consider the embedding half of D6. It also put
the scorer behind a `Scorer` interface, which the shipped code does not have (job68 reviewer
finding F3).

## The prep probe (2026-10-17, before any design)

Every probe ran on this machine against the frozen copies in `.shiftwork/notes-job68/`. Nothing
left the machine. The scripts are in `.shiftwork/notes-job71/`: `fp_class.py`, `emb_probe.py` and
`bm25_ranks.py`.

**Where B's wrong injections come from.** Of B_shipped's 79 wrong injections, 69 are auto-memory
facts of the prompt's own project. That leaves 9 from the shared project or profile stores and 1
with no known home. Same project, wrong topic, is the whole problem. Scoping by project cannot fix
it. Only a better sense of meaning can.

**Ranking judged pairs.** The test set is the 415 judged (prompt, fact) pairs: gold candidates plus
pool targets, 139 of them positive. Each method keeps its top 139 pairs, the same volume B injects,
and precision is measured on those. No constant was tuned on gold.

| method | AUC | precision |
|---|---|---|
| BM25F rank, B view (sanity: equals shipped) | 0.652 | 0.432 |
| nomic-embed-text (English) | 0.58 | 0.396 |
| **bge-m3 (multilingual)** | **0.69** | **0.518** |
| BM25 + bge-m3, z-score sum 1:1 | 0.649 | 0.496 |
| BM25 + bge-m3, RRF k=60 | 0.609 | 0.439 |

**Latency.** With bge-m3 warm in ollama (on GPU), embedding one query takes p50 67.3 ms and p90
71.9 ms (21 queries). A cold load takes seconds.

**Reading the probe.**
- Only a multilingual model helps.
- Fusing BM25 with the embedding does not beat the embedding alone.
- The gain of about +0.09 is real but nowhere near 0.8.
- The judged pairs were selected by v1 and BM25, so this is a direction, not a measurement. A
  dense ranker will inject facts that nobody has judged yet, and the measurement must pool those
  (D8).

## Decisions

| # | Topic | Decision |
|---|---|---|
| D1 | Interface | Add a `Scorer` in both runtimes. `Bm25fScorer` is its first implementation, with byte-identical output. **(user, from #199 D6)** |
| D2 | Backend | Ollama over HTTP, **opt-in**. It adds no npm or PyPI dependency, so the npm install stays pure Node. Both runtimes call the same server and get the same vectors. **(user)** |
| D3 | Model | Default `bge-m3`, the best on the probe and the only one of the two that helps on Thai. `BANTAMKIT_EMBED_MODEL` overrides it. **(default)** |
| D4 | Ranking | Dense cosine over **every fact in every layer**, not a rerank of BM25's hits. A Thai prompt that matches an English fact shares no tokens with it, so BM25 cannot propose that fact. No fusion, because the probe measured fusion as worse. **(default)** |
| D5 | Latency | A new budget that applies only when embedding is on: hook p50 rise ≤ 100 ms with the model warm, and a hard timeout of 150 ms on the query embed. When embedding is off, #199's ≤ 5 ms bar still holds. **(user)** |
| D6 | Fallback | If the backend does not answer, times out, lacks the model, or the vector cache does not cover every fact, the whole prompt is ranked by BM25. Scores are never mixed. The hook never errors on this path. **(default)** |
| D7 | Locality | Only a loopback `OLLAMA_HOST` is accepted (`localhost`, `127.0.0.0/8`, `::1`). The unspecified address `0.0.0.0` (or `::`), a common ollama server setting, is accepted too, but the request goes to `127.0.0.1` (or `::1`) **(user, 2026-10-17)**. Any other host is refused once at startup and then treated as off, because fact text must not leave the machine. Neither client consults a proxy. **(default)** |
| D8 | Bar | Declared in `tools/eval/recall/bar.json` before any measurement. Pass = embedding view precision@inject ≥ BM25 view + 0.05 **and** recall@3 ≥ BM25 view, both on the same pooled gold. The #199 bar of 0.8 stays as it is and is still reported as missed. **(user)** |
| D9 | Gate | An absolute cosine threshold `EMBED_GATE`, chosen on **silver** and frozen before gold is scored. The existing inject cap and display are unchanged. **(default)** |
| D10 | Windows | Not measured, because no Windows machine is available. The docs say so. The code path is plain HTTP to localhost plus a binary file read, with no platform branch. **(default)** |

## Design

### 1. `Scorer` (both runtimes)

There is one operation: `rank(query, pool) -> [(score, fact)]`, sorted by score descending with
ties broken by name. The pool is what `_pooled` assembles today. The scorer only replaces the call
to the BM25F functions. The gate (`GATE_FLOOR`, `GATE_RATIO`, or `EMBED_GATE` for the embedding
scorer), the type, fresh and usage weights, and the inject cap stay in `component`.

- `Bm25fScorer` wraps today's `bm25_postings`/`bm25_pooled`. Its acceptance test is the existing
  `recall-retrieval` and `recall-gate` conformance suites, unchanged, plus pytest and npm test
  unchanged.
- This unit is shippable alone. If D8 misses, it is the only part of #207 that ships.

### 2. `OllamaScorer`

- **Switch.** `BANTAMKIT_EMBED=ollama` turns it on. Unset, or any other value, means off. A value
  other than `ollama` or empty gets one status line naming it.
- **Settings.** `BANTAMKIT_EMBED_MODEL` defaults to `bge-m3`. `OLLAMA_HOST` defaults to
  `http://localhost:11434`, the variable ollama itself reads.
- **Query.** At prompt time it sends one `POST /api/embed` with `{"model", "input": [query],
  "keep_alive": "30m"}`, using a 150 ms total timeout.
- **Fact vectors.** It reads fact vectors from the cache (§3) and never embeds a fact on the hook
  path.
- **Score.** The score is cosine in float64, computed from float32 vectors with sequential
  summation in index order, so Python and Node produce the same double.
- **Text embedded per fact.** `name` with hyphens turned into spaces, then `": "`, then the
  description, then the keywords joined with spaces. This is what the probe embedded, plus the
  keywords.
- **Query input.** The query is the prompt, cut to its first 2,000 characters. The probe used the
  same cut. The hook does not cut prompts today, so this cut is new and applies only to the embed
  request. BM25 still sees the whole prompt.

### 3. Vector cache, a derived index in the style of #204

- **Location.** `<index dir>/<store-hash>.vectors-<model-slug>.bin` sits next to the postings
  files, under `BANTAMKIT_INDEX_DIR` or `~/.bantamkit/index`. Like every derived index, deleting it
  loses nothing.
- **Format.**
  - A JSON head line holds `{v, model, dim, count}`.
  - Each record then holds a 16-byte key, `dim` float32 values in little-endian order, and nothing
    else.
  - The key is the first 16 bytes of the sha256 of the embedded text, so editing a fact makes its
    old vector miss. The model name is in the file name, so switching models never reads stale
    vectors.
- **Writes.** Writes happen under the #204 lock and use write-temp-then-rename.
- **Filling the cache.** The cache gets filled in three ways:
  - `memory_save` and read-repair embed the fact they wrote. The embed is best-effort: a failure
    leaves the vector missing and the save still succeeds.
  - A new operator command, `bantamkit memory embed` (Python `python -m bantamkit.memory embed`,
    with the same subcommand on the Node CLI), embeds every missing fact in batches of 32 and
    prints `embedded N, already M, failed K`. It exits 0 unless the backend is unreachable or
    refused (exit 2, with a sentence naming the reason and the fix).
  - When the MCP server starts with embedding on, it runs the same fill detached and never blocks
    startup.
- **Coverage.** Coverage is complete when every fact in the prompt's pool has a vector under the
  current model. Anything less is fallback (D6).

### 4. Reporting

`bantamkit_status` gains these lines, in both runtimes with the same sentences:

- The active scorer: `scorer: bm25f` or `scorer: ollama bge-m3`.
- Cache coverage: `vectors: 640 of 655 facts (bge-m3)`, plus a fix line
  (`run bantamkit memory embed`) when coverage is short.
- Fallbacks since the server started, counted by reason: `unreachable`, `timeout`, `no-model`,
  `coverage`, `refused-host`.

The hook adds nothing to the injected block. Its log row records `scorer` and, on fallback,
`fallback: <reason>`, so the eval can tell the two apart.

### 5. Parity and conformance

Each part of the job has its own conformance case:

| Part | Conformance case |
|---|---|
| `Scorer` refactor | The existing recall suites, unchanged, are the gate. |
| `OllamaScorer` | A new `recall-embed` suite runs against a **stub ollama** the harness starts on a loopback port. The stub returns deterministic vectors (hash of text → seeded unit vector, dim 8). Cases: ranking order over a mixed Thai/English pool; gate cut; coverage-short → BM25 (output equals the BM25 case byte for byte); timeout (stub sleeps 300 ms) → BM25 with reason; unreachable port → BM25; non-loopback host refused, with the same sentence on both sides; and a model the stub does not have → `no-model`. |
| Cache | A `.bin` written by Python is read by Node and the reverse, with identical rankings. A changed description misses. A changed model name misses. |
| CLI | `memory embed` output and exit codes are the same on both sides. The `-h` text is byte-identical. |
| Status | The new lines, compared per side. |

### 6. Measurement (job71 eval units)

1. **Declare first.** Write the `bar.json` `embedding` section (D5, D8, D9) and commit it before
   any number exists.
2. **Choose `EMBED_GATE` on silver.** Use the per-session silver (`silver.jsonl` with the
   auto-memory copies) and the same objective `tune.py` used for `GATE_RATIO`. Freeze the result in
   `tuning-embed.json`.
3. **Inject.** Run the embedding view (B layering, frozen stores, a sandboxed HOME, a real ollama
   with bge-m3) on the 50 gold prompts and record the injections.
4. **Pool.** Any injected fact nobody has judged goes to the calibrated judge. It gets the same
   examples file as J68-18 (`pool-judge-examples.jsonl`), is blind to engine and scores, and writes
   private output under `.shiftwork/`.
5. **Score.** `score_pooled.py` scores every view (v1, A, B, embed) against the enlarged pool. The
   report says PASS or MISS against D8, and every gold number is UNVALIDATED.
6. **Latency.** Measure hook p50 with embedding off (≤ 5 ms rise against 0.37.0-beta.1) and on with
   the model warm (≤ 100 ms rise). The timeout path is exercised by the stub.
7. **On a miss.** Ship §1 only. Leave `OllamaScorer` unmerged, keep its branch local, record the
   miss on #207, and keep the bar where it is.

### Privacy

The repo is public. Prompts, fact bodies, injections and judge labels stay under `.shiftwork/`
(gitignored) exactly as in job68. Only aggregate numbers and code go into commits. The release is
again a clean branch off `main`.

## Out of scope

- A bundled in-process model, ONNX or wasm. It was rejected for package weight and float
  divergence between the two runtimes (D2).
- Fusing BM25 with the embedding (measured worse).
- Validating gold. It stays UNVALIDATED. A better judge is a separate issue if the user wants one.
- Remote embedding endpoints (D7).
- Windows measurement (D10).
