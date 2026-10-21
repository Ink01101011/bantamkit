FAIL — one blocking finding (B1: the sidecar BOM parity gap, which loses data and lets one runtime's cache change the other's ranking). Everything else passes.

# J72-29: review of #207 amendment 3 (`bantamkit-207q`, `feat/207-recall-queries`, cf42033..c83bb2c)

I am the reviewer. I edited no tracked file in the worktree and made no commit there (`git status --short | wc -l` gave 0 before
and after, and HEAD is still c83bb2c). There are two writes in the shared tree: this note, and one `reproduction` line in
`gold-looks.jsonl`. Every probe ran with HOME/USERPROFILE, `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off` inside
`<scratchpad>/j7229/`. My scripts are in `<scratchpad>/j7229/{scripts,bom,cc}`, the mutations in `<scratchpad>/j7229/mut*.sh`,
and the gates in `<scratchpad>/j7229/gates.sh`.

## Blocking

### B1 — a sidecar that starts with a UTF-8 BOM gets two different answers, and the derived cache carries Node's answer into Python
- **Where:** `runtime-ts/src/memory/queries.ts:63` (`docOfBytes`) and `:233` (`sidecarEntries`). Both decode with
  `new TextDecoder('utf-8', { fatal: true })`, whose default `ignoreBOM: false` strips the BOM. Python
  (`queries.py` `_doc_of`) decodes with `"utf-8"`, keeps the BOM, and `json.loads` refuses it.
- **Introduced here:** `queries.ts` is new in this diff (dc691eb). This is not something main already had.
- **Breaks the repo's own rule:** `docs/porting.md:341` says "One UTF-8 decoder in the package, with `ignoreBOM: true`, in
  `pyDecodeUtf8`". J57-5b closed this same gap for the update record. There is no divergence row and no `ruling:`.
  CLAUDE.md treats this as "a way for the two to disagree about a user's data".
- **Measured** (`bash <scratchpad>/j7229/bom/run.sh`; one sidecar holds fact `a`, written with a leading BOM):

  | step | Python | Node |
  |---|---|---|
  | A. read, Python run first (fresh index dir) | `read_sidecar []`, `layer_terms []` | `readSidecar ['a']`, but `layerTerms []` (it used Python's cache, same sha1) |
  | B. read, Node run first (fresh index dir) | `read_sidecar []`, but `layer_terms ['a']` (it used Node's cache) | `readSidecar ['a']`, `layerTerms ['a']` |
  | C. `write_entries({'b': ...})` | the BOM file is "malformed" and replaced: **`a` is lost**, leaving facts `['b']` | merged: `['a', 'b']` |

- **What goes wrong:**
  - Whether a recall scores fact `a`'s queries depends on which runtime built `<index>/<sha16>.qterms.json` first. That holds
    in both runtimes, and within one runtime the ranking can disagree with its own `readSidecar`/coverage (row A, Node).
  - A Python `memory_save`/`memory_queries` write silently deletes every other entry in that sidecar.
  - `queries: N of M` and the S12 nudge also differ by runtime.
  - The sidecar is written by bantamkit, so a BOM comes from a hand edit or an editor. That is the same Windows-editor case J57-5b
    accepted.
- **No case guards it:** mutation BOMFIX (both Node decoders set to `ignoreBOM: true`, so Node refuses as Python does) stays
  **GREEN** in `--suite recall-queries` (PASS 415, 0 failures).
- **To unblock (one unit per runtime, plus a conformance case):**
  1. Pick a direction and use it in BOTH readers. Either Node keeps the BOM (`ignoreBOM: true`, so the file is refused as in
     Python), or Python reads `utf-8-sig` (accepted, J57-5b's direction).
  2. Add a recall-queries case: a BOM sidecar read, ranked, and written-merged, as a differential plus a per-side literal, so a
     symmetric change also goes red.
  3. Prove the case red with today's code.
- The cache needs no change: it is keyed on the raw bytes and already refuses a BOM on both sides.

## Non-blocking

- **N1 — Q9 margin is thin.** Every arm passes, but by 0.1–1.1 ms (item 3 below). A slower machine or a later change to the
  scoring path can tip it, so rerun lat28 after the B1 fix.
- **N2 — the head changes behaviour without a sidecar.** That is by design (Q3). The no-sidecar *ranking* is byte-identical to B
  (item 4), but the no-sidecar *hook* is not B for short prompts that have a transcript. J72-28 shows it: main logs 22
  `none:empty-no-match` that nosc does not. The release notes should say so; it is not a defect.
- **N3 — a deeply nested sidecar is the same class as the accepted transcript edge.** Python `_doc_of` catches only
  `UnicodeDecodeError`/`ValueError`, so a ~1000-deep sidecar raises `RecursionError` out of `layer_terms`. Not probed. I am
  listing it only because it is a different file from the accepted transcript edge.
- **N4 — mutation script trap for whoever reruns.** `mut.sh`-style runs pass `--python $R/.venv/bin/python`, whose editable
  install points at `$R`.
  - `queries_ref.py:50` inserts its own tree's `runtime-py/src`, so the in-process cases do test the copy.
  - A Python mutation that only the stdio-server cases (13, 16, 19) would see is tested against `$R`, not the copy, unless
    `PYTHONPATH=<copy>/runtime-py/src` is set.
  - My runs set it and printed `bantamkit.__file__` inside each copy.

## Checks, with evidence

**1. Both runtimes, one surface (Q1–Q12, rulings 1–8): PASS** apart from B1.
- I read the diffs of `queries.{py,ts}`, `component.{py,ts}`, `hookadapter.{py,ts}`, `store`, `native`, `mcpserver.py` and
  `mcp/{server,status,pyargs}.ts`. Every surface has a counterpart:
  - `memory_save.queries` (`opt('queries','listStr')` / `list[str] | None`)
  - `memory_queries` (`opt('facts','listDict')`), appended last on both sides
  - S1–S12 spelled identically; S10/S11 via `_queries_line`/`queriesLine`
  - S12 in both SessionStart blocks, each in its own try
  - head constants 80/500/262144 and every-row pooling on both sides
  - rulings 3, 4 and 5 implemented identically
- Ruling 8 is pinned by `test_strip_nospace_blanks_each_nospace_code_point_before_nfkc` and the matching `queries.test.mjs:30`.
- No CLI flag was touched; `__main__.py` and `cli.ts` change only a docstring word.
- The served surface is compared by `--all` (wire, hooks and instructions suites, item 7).

**2. Fidelity (Q10): PASS.** Fresh sandbox `<scratchpad>/j7229/s29`: stores rsynced from J72-28's copy, sidecars re-loaded by
the product.
- `fidelity29.py load`: 441 q2d rows, 440 landed, 1 clash, 756/756 rows read back.
- **Dev:** Python `dev` **60/60** (head 31), Node `fidelity28.mjs dev` **60/60** (head 31).
- **Cache both ways:**
  - Node read Python's 5 caches.
  - I then deleted the caches and Node rebuilt them; they are byte-identical to Python's (`diff` of `md5 -r` empty).
  - Python dev after that: 60/60.
- **Gold, run as a reproduction, not a look:**
  - `fidelity29.py` is J72-28's script with only the unit tag and note changed.
  - It appended `{"ts": "2026-10-18T05:05:20+0700", "unit": "J72-29", "kind": "reproduction", "of": "J72-22 look 6", "policy": <J72-22 look-start block>, "note": "post-J72-30 fidelity check, not a look; scores nothing"}`
    BEFORE any gold file was read.
  - Python **50/50** (head 16), Node **50/50**.
  - Nothing was scored.
- **J72-28's line came first:** it is stamped 03:34:18, and its `fid-gold.json` mtime is 03:34:24. The script appends before
  any import or gold read.

**3. Latency (Q9): PASS, with a thin margin (N1).** I reran `node $P/J72-28-scripts/lat28.mjs <scratchpad>/j7229/s29 11` twice,
alone on the machine.
- Setup: Node v25.2.1, 60 prompts, 5 sidecars, a 309,832-byte fixture.
- Sidecar rise over main (2eb426b, whose product code equals cf42033's: `git diff --stat 2eb426b cf42033 -- runtime-*/src tools/hooks` is empty):

  | mode | run 1: diff of p50s / p50 of diffs | run 2 | spread | bar |
  |---|---|---|---|---|
  | indexed | 4.23 / 4.38 | 3.86 / 4.53 | 0.37 / 0.15 | ≤ 5 PASS |
  | unindexed | 4.48 / 4.91 | 4.90 / 4.75 | 0.42 / 0.16 | ≤ 5 PASS |

- The no-sidecar arm rises indexed 2.95/2.94 and 2.53/2.93, unindexed −0.53/−1.08 and −0.17/−0.98.
- The p90 of diffs is 5.87–6.71. The bar is the p50.
- The hook-log action tallies equal J72-28/J72-30's in every arm, so every arm did the recall.
- **The method is sound:**
  - the real `tools/hooks/bantamkit-hook.mjs` is spawned for every run
  - arms are interleaved per prompt on one bed
  - one discarded warm run in indexed mode
  - median of 11 runs, same machine
  - sidecar present (sc) and absent (nosc)
  - "unindexed" also deletes the qterms cache, so it is the worst case

**4. No-sidecar path = B: PASS.** With HOME empty (no sidecar), on the 60 dev prompts, I hashed `inject_candidates`,
`rank_all(10)` and the full `recall_outcome` reply (`scripts/nosc.{py,mjs}`):
- Python HEAD `3a638b70…` = main `3a638b70…`
- Node HEAD `35ffacf5…` = main `35ffacf5…`
- No `~/.bantamkit` was created in that HOME.
- The diff does not touch the `recall-*` (other than the new suite) or `storage-index` suites; they are green in `--all`.

**5. Conformance bites: PASS.** Rsync copies, `PYTHONPATH` set to each copy, `--suite recall-queries` unless named.
- CONTROL: PASS 415, 0 failures.
- Red counts from the plan's list: M1 **42**, M2 **20**, M3 (both sides) **6** (the QUERY_WEIGHT literals ×2 and the inject
  literals ×4), M5 **4**, M6 **2**, M7 **4**, M13 **12**.
- J72-30's cache check: M14b, Node uses the cache without the sha1 check, **27**.
- **Feature deleted on BOTH sides, so only literals can catch it:**
  - D2 head off: 8 red, and 2 more in `--suite hooks`.
  - D3 S12 off: 4 red in `--suite hooks`.
  - D5 every_row ignored: 5 red.
  - D6 save never writes queries: 4 red. tsc reported an error on the Node half, but it still emitted the mutated file; only
    the 4 expected cases went red.
- **Only gap found:** BOMFIX stays green (B1).
- **J72-30 cache behaviour** (`cc/run.sh`):
  - 12 Python and 12 Node processes building one cache at once, 3 rounds: every output equal, no `.tmp` left, the final
    cache valid.
  - Read-only index dir, index dir that is a file, cache path that is a directory: rows are still returned, nothing raises.
  - Editing the sidecar after the cache was built: both sides read the new terms.

**6. Privacy: PASS.** I scanned the 5,240 added lines of `git diff cf42033..HEAD`:
- 0 of 60 dev prompts appear.
- 0 of 2,636 q2d queries of 15+ characters appear.
- 1 of 504 fact names appears: `differential-is-blind-to-symmetric-regression`, which is already in 10 public files at cf42033.
- 1 of 12,500 body lines appears: a quote of public `runtime-ts/src/shiftwork.ts`.
- The sidecar path is `home/.bantamkit/queries/<sha16(root)>.json` (`sidecarPath`/`sidecar_path`; the BOM probe wrote there).
  `BANTAMKIT_INDEX_DIR` does not move it.

**7. Gates at c83bb2c** (`bash <scratchpad>/j7229/gates.sh`): all green.
- `npm run build && npm test`: `tests 1876 / pass 1829 / fail 0`
- `ruff check runtime-py tools`: `All checks passed!`
- `pytest runtime-py/tests -q`: `4071 passed, 58 skipped, 2 deselected, 3 xfailed in 307.57s`
- `node tools/conformance/run.mjs --all`: `PASS: 17130 cases, 3035 byte-identical, 8625 exact-string, 5470 structural, 181 ruled-different, 0 failures`

**8. No embedding, ollama or network: PASS.**
- The diff's added lines contain 0 of `ollama|node:http|embed`, and none of http/socket/fetch/urllib outside docs.
- At runtime (`scripts/net.{mjs,py}`), over 60 sidecar recalls with head, coverage and missing:
  - Node: 0 `fetch` calls. Its network-builtin list equals main's: `internal/net, dns/utils, net, internal/dgram, dgram`, which
    `child_process` pulls in; no `http`.
  - Python: 0 socket/urllib/http audit events. 31 network modules are imported, the same count as main.

## Real ~/.bantamkit
- Before: `ls -la ~/.bantamkit ~/.bantamkit/index ~/.bantamkit/hooks | wc -l` gave 422. `retention.json` was 16060 B, mtime
  Oct 16 08:40:13 2026, inode 183388298.
- After: identical, with no `qterms` file and no `~/.bantamkit/queries`.
