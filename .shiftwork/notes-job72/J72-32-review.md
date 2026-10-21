PASS — B1 is fixed on both sides, the new case bites, and the pyDecodeUtf8 reorder keeps the accept/refuse set, the text and the refusal message. No blocking finding.

# J72-32: re-review of the B1 fix (`bantamkit-207q`, `feat/207-recall-queries`, c83bb2c..d5703bc)

Reviewer. No edit to a tracked file in the worktree and no commit there (`git status --short | wc -l` = 0, HEAD d5703bc,
before and after). The only shared-tree write is this note. Every probe ran with HOME/USERPROFILE, `BANTAMKIT_INDEX_DIR`,
`BANTAMKIT_RETENTION=off` and TMPDIR inside `<scratchpad>/j7232/` (`env.sh`), except the dev fidelity run, which uses
HOME=`<scratchpad>/j7228/home` as J72-28/31 did. Scripts: `<scratchpad>/j7232/{scripts,mut.sh,muts.sh,muts2.sh,gates.sh}`.

## 1. B1 repro: PASS
`bash <scratchpad>/j7229/bom/run.sh` (log `j7232/bom-repro.log`):
- A (Python first) and B (Node first): `read_sidecar`/`readSidecar` `[]` and `layer_terms`/`layerTerms` `[]` on all four reads.
- C (write over the BOM sidecar): both sides leave `['b']` and the file starts `{"f` (BOM gone, replaced as malformed).
- Caches (`bash j7232/scripts/cache.sh`, a separate index dir per side): BOM sidecar gives
  `{"facts":{},"sidecar":"87f2bb…","v":1}` on both, `cmp` identical. Control without the BOM gives
  `{"facts":{"a":[2,["deploy",1,"staging",1]]},…}` on both, also identical.

## 2. The case bites: PASS
Rsync copies of HEAD, `PYTHONPATH=<copy>/runtime-py/src` (each printed `bantamkit.__file__` inside the copy),
`--suite recall-queries` unless named (`bash j7232/muts.sh`, `muts2.sh`; logs in `j7232/mut/`):

| mutation | result |
|---|---|
| CONTROL (HEAD) | PASS 446, 0 failures |
| REVQ: `queries.ts` reverted to c83bb2c | **17 failures**, all `sidecar/bom` |
| REVQ_SYM: REVQ plus Python `_doc_of` reading `utf-8-sig` (both sides strip) | **16 failures**, all literal or per-side-vs-no-sidecar cases; every differential green |
| REVPYFS: only `pyfs.ts` reverted (validator first) | PASS 446, 0 failures (expected: the reorder is perf only) |
| PYFS_STRIPBOM: `STRICT_UTF8` without `ignoreBOM: true` | `--suite store` **1** (`utf-8 strict decode over 226 sequences`), recall-queries **17** |
| MSG: validator reason `'invalid continuation byte'` respelled | `--suite store` **1** (the same codec case). CONTROL_STORE PASS 382 |

MSG shows the loop still runs on every refusal and the codec case still compares messages after the reorder.
PYFS_STRIPBOM shows the shared decoder instance's BOM setting is guarded twice.

## 3. No other decoder bypasses `pyDecodeUtf8`: PASS, with one deviation that I accept
`git diff cf42033..HEAD -- runtime-ts/src`, grepped for `TextDecoder|toString(|.decode(|utf-?8|readFileSync|JSON.parse|parseJson`:
- `queries.ts`: `docOfBytes`, `cached` and `sidecarEntries` all decode through `pyDecodeUtf8`. Every other
  `readFileSync` in the diff feeds `createHash` (raw bytes; no decode).
- `pyfs.ts`: `STRICT_UTF8` is the decoder inside `pyDecodeUtf8` itself.
- `hookadapter.ts:1464` `previousPrompt` keeps `new TextDecoder('utf-8', { fatal: false, ignoreBOM: true })`.
  **Ruling: accept the deviation.** It ports `raw.decode("utf-8", errors="replace")` (`hookadapter.py:1321`), which
  `pyDecodeUtf8` (strict) cannot do. `ignoreBOM: true` keeps the BOM. Measured on 14 transcripts
  (`j7232/scripts/{ppmk.py,pp.py,pp.mjs}`): a leading BOM on the only candidate, a BOM then a second prompt, a BOM-only
  line, U+FEFF inside text, `\xff\xfe`, a surrogate `ED A0 80`, overlong `C0 AF` and `E0 80 AF`, `F4 90 80 80`,
  `F5…`, truncated 3- and 4-byte sequences mid-line and at EOF, and valid Thai and emoji. Python and Node return equal
  strings on all 14, U+FFFD counts included. For example, the leading BOM on the only candidate gives `""` on both
  sides (`json.loads` and `parseJson` both refuse it).

## 4. `pyDecodeUtf8` reorder, package-wide: PASS
- **J72-31's `equiv.mjs`.** I read it. It covers every 1-, 2- and 3-byte input exhaustively, so it covers:
  - overlongs `C0`/`C1` and `E0 80–9F`
  - surrogates `ED A0–BF`
  - the BOM
  - truncation at end of buffer for 2-, 3- and 4-byte leads
  - lone continuation bytes

  It also covers F0–FF × all × all × 20 selected fourth bytes. That reaches `F4 90+`/`F5–FF` (above U+10FFFF) and
  the `F0 80–8F` overlongs. **Gap:** every input is 4 bytes or shorter. Node's `TextDecoder` takes SIMD fast paths on
  long buffers, which no ≤4-byte input reaches.
- **I closed that gap** with `j7232/scripts/long.mjs`, HEAD `pyDecodeUtf8` against c83bb2c's
  (`j7231/old/runtime-ts/dist/memory/pyfs.js`; its src is byte-equal to `git show c83bb2c:…/pyfs.ts`). It compares
  ok/text, or error class/message/start/end, over:
  - 20,000 random buffers of 1–5,000 bytes (valid 1–4-byte chars, BOMs, and 0–2 injected bad sequences)
  - every bad and valid sequence at offsets 0–199 inside 64 B, 1 KiB and 64 KiB ASCII blocks
  - 1 MiB buffers with bad bytes at 16-, 32- and 64-byte boundaries and at the end
  - BOM-led buffers up to 70 KB (U+FEFF kept, length L+1)
  - all 2,042 files in the worktree (excluding .git, node_modules, .venv, dist)

  Result: `{"n":37537,"accepted":12509,"refused":25028,"diff":0,…,"state":"ok"}`. Every refusal is still a
  `PyUnicodeDecodeError`, with the same message and span as before.
- **Shared-instance state.** After a refused truncated `61 E2 82`, a lone `AC` is still refused, and `E2 82 AC` then
  decodes to €. No state leaks between calls (`state: ok`).
- **Codec suite.** The `utf-8 strict decode over 226 sequences, the decoded text included` case compares messages and
  text. It goes red under MSG and under PYFS_STRIPBOM (item 2), and it is green at HEAD.

## 5. Gates at d5703bc (`bash j7232/gates.sh`, log `j7232/gates.out`): all green
- ruff: `All checks passed!`
- `npm run build && npm test`: `tests 1877 / pass 1830 / fail 0`
- pytest: `4072 passed, 58 skipped, 2 deselected, 3 xfailed in 308.37s (0:05:08)`
- `--all`: `PASS: 17161 cases, 3035 byte-identical, 8625 exact-string, 5501 structural, 181 ruled-different, 0 failures`

## 6. Q9 and Q10: PASS
- **lat28, one run.** `node $P/J72-28-scripts/lat28.mjs <scratchpad>/j7228 11` ran alone; I started it only after
  the gates and mutations had finished. Output in `j7232/lat.out`. Cells are p50_of_diffs / diff_of_p50s, in ms:

  | mode | sc rise | nosc rise | bar |
  |---|---|---|---|
  | indexed | 3.77 / 3.27 | 2.21 / 2.14 | ≤ 5 PASS |
  | unindexed | −0.04 / 1.69 | −4.92 / −2.81 | ≤ 5 PASS |

  The log tallies equal J72-28/30/31's (indexed sc inject 180 / suppress 480; main 185/442/22), so every arm did the
  recall. The N1 margin from J72-29 has widened: unindexed sc went from 4.48–4.90 to −0.04/1.69.
- **Dev fidelity.** Python `fidelity28.py dev` gives `{"prompts": 60, "inject_equal": 60, "head_used": 31}`, and Node
  `fidelity28.mjs dev` gives `{"prompts":60,"inject_equal":60,"head_used":31}`. `fid-dev.json` is md5-unchanged.
- **No gold.** No gold file was read, and `gold-looks.jsonl` is unchanged (its last line is still J72-29's
  reproduction).

## Non-blocking
- **N1.** `equiv.mjs` alone does not cover long buffers. Item 4's `long.mjs` covers them. If the docs/porting.md
  sentence "checked over 64,028,929 inputs" is ever cited as the only proof, add the long-buffer half.
- **N2.** `previousPrompt` is now the one `TextDecoder` outside `pyDecodeUtf8` that this diff added. A `porting.md`
  line naming it as the replace-mode exception (as `mcpreport.ts` and `docread.ts` already are in practice) would keep
  the "one decoder" sentence literally true. This is wording, not behaviour.

## Real ~/.bantamkit
- **Before and after:** `ls -la ~/.bantamkit ~/.bantamkit/index ~/.bantamkit/hooks | wc -l` gave 422.
  `retention.json` was 16060 B, mtime 1792114813, inode 183388298.
- `~/.bantamkit/queries` does not exist, and `~/.bantamkit/index` holds 0 `qterms` files.
