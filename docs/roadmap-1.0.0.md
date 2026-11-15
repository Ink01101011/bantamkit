# Roadmap 1.0.0 — single TypeScript source for npm and PyPI

Tracking issue: #312. Phases, in rollout order: #313 baseline → #314 Rust TS→Python pilot
(workplan) → #315 fact-file codec → #316 migrate runtime + consolidate tests → #317 minify and
harden → #318 release candidate and publish.

## #313 baseline (measured at `865538b9`, 2026-11-15, macOS arm64, Node 26.13.0, CPython in `.venv`)

Every number below was produced by a command run on that commit. The scripts that are not
already in the repository are listed under *How each number was taken* so they can be rerun;
none of these figures is a budget yet. #313 says to capture first and agree budgets after.

### Measurements

| What | npm `bantamkit-mcp` 0.40.0 | PyPI `bantamkit` 0.40.0 |
|---|---|---|
| Source lines (`src/`) | 53,258 in 75 `.ts` files | 48,301 in 71 `.py` files |
| Test lines | 45,835 (`runtime-ts/test*`) | 74,334 in 133 files (`runtime-py/tests`) |
| Shared conformance harness | 63,678 lines, 52 suites (`tools/conformance`) | — |
| Packed artifact | tarball 1,004,330 B, 257 files, unpacked 3,319,977 B | wheel 898,098 B; sdist 1,713,863 B |
| Build time (wall) | `tsc` 1.88 s | `python -m build --wheel --sdist` 2.88 s |
| Cold start → `tools/list` answered (n=5, median) | 116 ms (111–122) | 363 ms (357–752) |
| Tools served | 16 | 16 |
| Runtime floor | `node >=20` | `requires-python >=3.11` (classifiers 3.11, 3.12) |
| Runtime deps | `@modelcontextprotocol/sdk` 1.32.2 (exact) | `httpx>=0.27`, `jsonschema>=4.21`, `pyyaml>=6.0`; extra `mcp>=2.3,<2.4` |

| Gate | Result | Wall |
|---|---|---|
| `node tools/conformance/run.mjs --all` | PASS 20,893 cases: 3,721 byte-identical, 9,114 exact-string, 8,058 structural, 186 ruled-different, 0 failures | 730.9 s |
| `pytest runtime-py/tests -q` | 5,108 passed, 58 skipped, 2 deselected, 3 xfailed | 451.7 s |
| `bantamkit-mcp -h`, both runtimes (`COLUMNS=100`) | byte-identical, 27 lines | — |

OS coverage: these numbers are macOS only. Windows and Linux are the CI matrix
(`.github/workflows/ci.yml`), and Actions is off on this account, so #318's matrix run must
use another route. That route is still to be decided.

### Public surfaces

**CLI.** Both `-h` outputs are byte-identical. Flags: `--assets-root --force --help --hook
--index-budget --install --install-hooks --mcp-report --remove-hooks --start --statusline
--store --update --yes`. Bins differ: npm also ships `bantamkit-memory` (`dist/memory/cli.js`);
PyPI reaches the same CLI as `python -m bantamkit.memory` (`memory/__main__.py`) and
declares no script for it.

**MCP.** The same 16 tools on both servers: the 14 in `docs/mcp.md` plus `memory_queries`
and `shiftwork_draft`. **`docs/mcp.md` still says "Fourteen tools"; it is stale.** Definitions
are shared assets (`assets/tools/*.json`, 21 files: the 16 served plus `bantamkit_read`,
`repo_map`, `document_list`, `document_read` and `file_graph`, which are not served).

**Library APIs — the two packages barely overlap. This is the largest #313 finding.**

- npm `index.ts` exports the store (`MemoryStore`, `Memory`, dream, layers, factfile,
  eventlog, contract, assets, shiftwork) **and the CPython-emulation layer**: `pyjson`,
  `pyjsonschema`, `memory/pyyaml`, `memory/pyfs` (≈35 `py*` OS/path helpers).
- PyPI `bantamkit` exports an **agent library npm has no counterpart for**: `Agent`,
  `ModelClient`, `OpenAICompatible` (via `httpx`), `CritiqueGate`, `GroundedCritiqueGate`,
  `Rubric`, `run_suite`, `format_report`, `CONFIGS`, `FileAccessGraph`, `LoopGuard`,
  `structured`, `extract_json`, and their errors.
- Shared names: `Memory`, `MemoryStore`, `BantamError`, `extract_json`/`extractJson`.

Modules on one side only (module path without extension). A package's `index.ts` and its
`__init__.py` count as the same module (`index`, `storage/index` and `touch/index` pair with
`bantamkit/`, `storage/` and `touch/__init__.py`). `memory/__init__.py` is a re-export with no
TypeScript file.

- **Python only (16):** agent budget criticreplay critique docmanifest evalrun filegraph loopguard
  mcpserver mcpstdio memory/__main__ memory/divergence pdfread profile structured textutil
- **TypeScript only (21):** charsets cli errors htmlentities mcp/identity mcp/pyargs
  mcp/sdkjson mcp/server mcp/status mcp/transport memory/cli memory/factfile memory/pyfs
  memory/pyyaml npminstall pyargparse pyjson pyjsonschema pysem skilllabel
  storage/retention-child
- **Both:** 54.

### Two decisions #312 does not settle yet

1. **The Python-only agent library** (`agent`, `critique`, `criticreplay`,
   `evalrun`, `filegraph`, `loopguard`, `structured`, `budget`, `profile`, `textutil`,
   `pdfread`, `docmanifest`, `memory/divergence`; 8,879 lines). #316 says "cover
   Python-only public APIs". The options were: port it to TypeScript (npm gains it), keep it
   hand-written Python on top of the generated core, or retire it in 1.0.0 as a breaking change.
   **Ruled 2026-11-15 by the maintainer: it stays hand-written Python** on top of the generated
   core. It is neither ported nor retired.
2. **The TypeScript emulations of CPython** (`pyjson`, `pyjsonschema`, `memory/pyyaml`,
   `memory/pyfs`, `pyargparse`, `pysem`; 6,829 lines). They exist so Node writes the bytes
   CPython writes. Compiled *to* Python they are either redundant (the generated code could call
   `json`, `yaml` and `pathlib`) or a fidelity risk (generated code standing in for CPython's own).
   #314's supported subset has to say which target gets the native library and which gets the
   emulation.

### Dependency order: migration groups for #316

Internal import depth of `runtime-ts/src`: 0 means the module imports nothing internal, and
depth is the longest import chain down to such a module. The graph is not acyclic. A
depth-first walk in file order cuts **19 back-edges**, which point into 9 modules: `memory/pyfs`,
`memory/store`, `skillfile`, `storage/retention`, `hookadapter`, `memory/component`,
`memory/skills`, `skillmine`, `skillinstall`. The depths below depend on that cut order. A
different walk shifts some modules by a level; an independent walk put `pyjson` at 0 and
topped out at 20. Each cycle has to be broken first or migrated as one unit.

| Depth | Modules (lines) |
|---|---|
| 0 | charsets errors htmlentities jobbudget npminstall storage/lock workplan (1,269) |
| 1–2 | pyjson storage/logsegment updatecheck mcp/pyargs mcp/sdkjson memory/usage pysem (2,721) |
| 3–4 | client experiment memory/pyfs memory/retrieval skillaudit touch/* assets docread mcp/transport memory/pyyaml pyargparse pyjsonschema repomap skilllabel (14,930) |
| 5–8 | mcp/identity memory/factfile pricing replynative contract selfupdate storage/hotindex tokenledger storage/coldindex touch/graph memory/store touch/index (9,158) |
| 9–15 | eventlog hostinstall memory/dream memory/layers memory/native memory/queries mcpreport memory/cli storage/tiers skillhost statusline skilldraft skillpromote skillreport skillinstall skillmine storage/retention (12,373) |
| 16–21 | shiftwork skillfile storage/index storage/retention-child memory/skills skillpropose memory/component hookadapter index mcp/status mcp/server cli (12,807) |

### Every surface: its migration group and the check that guards it

| Surface | Group | Compatibility check (existing) |
|---|---|---|
| `workplan`, `pricing` | G1 pure core | suites `workplan`, `pricing` |
| `jobbudget` | G1 pure core | **missing**: only per-side tests (`test_jobbudget.py`, `jobbudget.test.mjs`); no conformance suite compares the two |
| JSON output (`pyjson`) | G2 codecs | `wire`, `validate`, `store` byte-identical cases |
| JSON Schema feedback (`validate_json`) | G2 codecs | suite `validate` |
| Fact files (YAML front matter) | G2 codecs → **#315** | suites `codec`, `store`; real corpus `.bantamkit/memory` |
| Event log, token ledger, log segments | G2 codecs | suites `tokenledger`, `storage-log` (`storage/logsegment` is covered only through these two; no suite names it directly) |
| Memory store, recall, dream, layers, queries, usage | G3 memory | `store`, `dream`, `recall-*`, `memorycli` |
| Hot/cold index, tiers, retention, lock | G4 storage | `storage-*` (6 suites) |
| Shift-work checkpoint + `.log.jsonl` | G5 shiftwork | `shiftwork`, `shiftwork-draft` |
| Skills (audit, miner, draft, file, host, install, layer, promote, propose, improve) | G6 skills | 10 `skill*` suites |
| Hooks, touch, reply-native, statusline | G7 hooks | `hooks`, `touch-*` (7), `reply-native`, `statusline` |
| Document reader, charsets, repo map | G8 reader | `docread`, `charsets`, `repomap` |
| Install, self-update, update check, MCP report | G9 install | `install`, `updatecheck`, `mcpreport`, `version` |
| MCP server, CLI, argparse, OS seam (`pyfs`) | G10 adapters (stay per runtime) | `wire`, `cli`, `instructions` |
| Python-only agent library (except `client`) | G11, decision 1 above | pytest only; **no cross-runtime check exists** |
| LLM client (`client`) | G11 | suite `llm-client` |
| Reading files written by earlier releases | all | **missing**: no suite opens a store written by 0.39/0.40. #315 and #318 must add one |

### Against #313's acceptance criterion

Every public surface and stored format above has a migration group. Three have **no
cross-runtime compatibility check yet**, and these are the open items #313 leaves for later
phases:

- `jobbudget`: per-side tests only. #316 adds a suite when the module migrates.
- The Python-only agent library: pytest only. This is by ruling, since it stays Python, so a
  cross-runtime check does not apply. #316 must keep its pytest coverage green against the
  generated core.
- Stores written by earlier releases: no suite opens one. #315 adds this for fact files, and
  #318 adds it for whole stores.

### How each number was taken

- Lines: `find <src> -name '*.ts|*.py' | xargs wc -l`; tests via `git ls-files … | xargs wc -l`.
- npm size: `npm pack --dry-run --json --ignore-scripts` in `runtime-ts` (packs the `dist`
  already built from this commit; `tsc` was rerun on the same tree).
- Wheel/sdist: `.venv/bin/python -m build --wheel --sdist --outdir <tmp> runtime-py`.
- Cold start: spawn the server with `--store <fresh tmp>`, send `initialize`, then
  `notifications/initialized` and `tools/list`, and time until the `tools/list` reply. n=5
  per side, run in sequence on an idle machine. The script was kept out of the repository; a
  rerun needs only those four steps.
- Dependency depth: a regex walk over `from './x.js'` and `import('./x.js')` in `runtime-ts/src`,
  with depth = longest chain to a leaf and back-edges reported as cycles.

## #314 pilot: `workplan` generated by ts2py (measured 2026-11-15 on `feat/314-ts2py-pilot`, macOS arm64, Node 26.13.0, cargo 1.100.0)

`runtime-ts/src/workplan.ts` is now the only planner source. `tools/ts2py` compiles it to
`runtime-py/src/bantamkit/_generated/workplan.py`, which is committed with its support module,
and `bantamkit.workplan` serves that code. The hand-written Python planner is retired. How to
regenerate, the freshness gate, and the 8 Python-side parity fixes are in `docs/porting.md`,
*Generated modules*.

| What | Before (hand-written) | After (generated) |
|---|---|---|
| Python planner lines | `workplan.py` 311 | generated `workplan.py` 162 + shim `workplan.py` 50; support `_ts2py_runtime.py` 555, shared by any future generated module |
| TypeScript source | `workplan.ts` 280 | unchanged |
| `test_workplan.py` | 423 lines, cases typed inline | 104 lines (155 tests), reads the shared fixture; plus `test_ts2py_fresh.py` 66 lines |
| Shared expected answers | none | `fixtures/workplan-cases.json`: 148 cases (graph 21, core 53, ts 21, py 13, adversarial 40) |
| `--suite ts2py` | 451 cases, 8 ruled-different (legacy findings) | 448 cases, 0 ruled-different, 0 failures; includes a byte-compare of the committed generated files against a fresh compile |
| `--suite workplan` | 290 cases, 0 failures | 294 cases, 0 failures (`tool/no-id` unchanged; 4 new cases for a missing `id` after an earlier fault, which Node had answered differently) |
| Python vs TypeScript on the shared cases | 139 of 147 match | 148 of 148 match |
| Random-graph differential (generated Python vs Node `dist/workplan.js`) | not run | 100,000 JSON graphs, 0 mismatches (review J85-R); 60,000 more with integers past the double range, 0 mismatches after the J85-5 fix |
| Wheel | 898,098 B (#313 baseline; `runtime-py` unchanged since) | 901,232 B (+3,134 B) |
| Rust needed to build or install the wheel | no | no (generated files committed; wheel checked to contain `bantamkit/_generated/*`) |

| ts2py timing | Wall |
|---|---|
| Compile `workplan.ts` (release binary, n=20) | median 2.3 ms (2.2–3.1) |
| `cargo run --release` of an already-built compiler, n=3 | 0.20–0.80 s |
| Cold release build of the compiler (fresh target dir, crates already in the cargo cache) | 18.8 s |

| Gate on the switched tree | Result | Wall |
|---|---|---|
| `node tools/conformance/run.mjs --all` | PASS 21,336 cases: 3,721 byte-identical, 9,556 exact-string, 8,059 structural, 186 ruled-different, 0 failures | 680.1 s |
| `pytest runtime-py/tests -q` | 5,240 passed, 58 skipped, 2 deselected, 3 xfailed | 405.3 s |

How the numbers were taken: line counts with `wc -l` (the hand-written planner via
`git show 271019a8:runtime-py/src/bantamkit/workplan.py`). Compile time with a Python
`perf_counter` loop over `tools/ts2py/target/release/ts2py runtime-ts/src/workplan.ts -o <tmp>
--runtime-module ._ts2py_runtime`. Cold build with `CARGO_TARGET_DIR=<tmp> cargo build --release`.
Wheel with `.venv/bin/python -m build --wheel --sdist --outdir <tmp> runtime-py`.
"Before" suite counts are J85-4's verified run at `271019a8`.

## #315 fact-file codec: generated by ts2py (measured 2026-11-15 on `feat/315-codec`, macOS arm64, Node 26.13.0, CPython 3.12.13, PyYAML 6.0.3)

`runtime-ts/src/memory/factfile.ts` and `pyyaml.ts` (2,003 lines) are compiled by `tools/ts2py`
to `runtime-py/src/bantamkit/_generated/factfile.py` (643) and `pyyaml.py` (750), which are
committed. Since J86-3 runtime-py's memory store reads and writes every fact file through them,
falling back to real PyYAML only where they refuse (user ruling 2026-11-15, option A). The seam,
the adapters, the two classes that moved and the measured read cost are in `docs/porting.md`,
*Generated modules* → *The fact-file codec*.

### Compiler rules (J86-1, `tools/ts2py/RULES.md`)

| Ledger | Count |
|---|---|
| J85 rules reused unchanged | 32 of 59 (54%) |
| J85 rules extended | 27 of 59 (46%) |
| new in J86 | 44 (43% of the 103 rules the codec needed) |
| adapter entries | 4: `pyFloatRepr` (`repr(float)`), `pyStrip` (`str.strip()`), `TextDecoder.decode`, `Date` (3 getters) |

Semantic gaps the codec met and closed, each pinned by a cargo test whose expected value came from
Node (`tools/ts2py/SUBSET.md`): classes (fields, constructors, methods, getters, `this`,
`instanceof`, `Object.freeze`), `Error` subclasses with `throw`, `switch`, `for(;;)`, compound and
chained assignment, closures needing `nonlocal`, default parameters, destructuring and object
spread, `*` `/` `%` with JS semantics (`-0`, `Infinity`, `NaN`, the sign of `%`), BigInt kept
exact, UTF-16 positions in every string operation, regex `g`, `\x`/`\u` escapes and fixed-width
lookbehind. J86-4 then found one gap in the TypeScript itself, not in ts2py: `formatFact` threw on
a nested `metadata:` mapping that runtime-py wrote (478 of 495 Claude Code native files); fixed
in TS, so the generated code got it by recompiling.

### Differential results (J86-2, rerun by J86-3 against the switched runtime-py)

| Input class | Inputs | generated = Node | runtime-py now vs before the switch |
|---|---|---|---|
| seeded fuzz (seed 315: 1,200 facts, their 1,200 texts, 1,500 hand-written frontmatters) | 2,700 read, 1,200 formatted | 0 differences | moved only in the two ruled classes: `yaml11-breaks` 71/71 and `pyyaml-refuses` 27/27 now read as Node; 0 other inputs moved; 0 of 1,200 writes changed |
| files written by bantamkit 0.27.0, 0.35.9, 0.36.2, 0.39.3 (PyPI) | 40 | 0 differences | 0 moved; all 40 read alike by all three, pinned by `EXPECTED.json` |
| scratch copies of the real stores on this machine | 802 | 0 differences | 0 moved; 478 nested-metadata files written alike; 6 reads and 0 writes took the PyYAML fallback |

`--suite ts2py-codec`: PASS 227 cases, 2 ruled-different (`node-refuses`, `non-text-key`), 0
failures. `--suite ts2py`: PASS 452 cases (the F4 byte-compare now covers all five generated files
and lists the directory).

| Gate on the switched tree (J86-3) | Result | Wall |
|---|---|---|
| `node tools/conformance/run.mjs --all` | PASS 21,594 cases: 3,733 byte-identical, 9,694 exact-string, 8,167 structural, 190 ruled-different, 0 failures | 702 s |
| `pytest runtime-py/tests -q` | 5,266 passed, 58 skipped, 2 deselected, 3 xfailed | 440.0 s |

### Read cost, the unknown this phase found, and what J86-5 did about it

J86-3 measured the generated read at 830 µs per frontmatter against 21 µs for the libyaml path it
replaced and 181 µs for pure `yaml.safe_load` (684 real frontmatters, best of 3), and
`MemoryStore._facts()` over 91 facts at 82 ms against 4.6 ms. **Correction (J86-5):** most of that
was not the general per-operation overhead of the JS-semantics layer but one quadratic: every
`s[i]` and `s.length` on a non-ASCII string recomputed the whole string's UTF-16 view (an O(n)
`max()` or `encode` per read), so a scanner walking a Thai or emoji description char by char was
O(n²). The profile before J86-5 (cProfile, 3 passes over the corpus, 3.57 s): `isinstance` 14.5 M
calls, `max` 181 k calls 0.43 s self, `_js_strict_eq` 1.2 M, `_js_get` 727 k, `_js_same_value_zero`
991 k. After (1.43 s, same work): `_js_get` 0.17 s self, then a flat tail (`_js_m_includes`,
`_scan_quoted`, `resolve_implicit_tag`, `_js_code_units`, `_js_len`), `max` 0.017 s.

What changed, semantics untouched:

- **Runtime fast paths** (`tools/ts2py/src/runtime.py`): `===`, `+`, `<` `<=` `>` `>=` take two
  plain ints inside ±2^53 or two `str` directly; `s[i]`/`xs[i]` with a plain int index;
  `.length` of an ASCII string is `len`; `[...].includes(str)`; `codePointAt(int)`;
  `fromCodePoint(int in 0..0x10FFFF)`; `push`/dispatch on a list. Each tests its own precondition
  at run time with `type(x) is` (so a bool, a float or an int past 2^53 goes the general way) and
  returns what the general path returns. `_js_code_units` of a non-ASCII string is memoised
  (a pure function of the value; bounded at 512 entries and 65,536 characters). Pinned by
  `semantics.rs::fast_paths_answer_exactly_as_the_general_paths_and_js_do`, whose expected line is
  Node's for the same source; five mutants (bound dropped from `===`, from `+`, `isinstance` for
  `type is` in `>`, the units view skipped in `s[i]`, `str(element)` in `includes`) each turn it red.
- **A read cache in the adapter** (`factcodec.load_frontmatter`): keyed by the frontmatter text
  itself (not path/mtime/size, which a same-size edit within one mtime tick would fool), only the
  generated codec's answers kept, every hit a fresh copy of its lists and dicts; bounded at 4,096
  texts of at most 32 KiB. A SessionStart parses 316 frontmatters for ~190 files, and the server
  re-read every fact on every save.

No lowering rule changed, so the five generated modules are byte-identical; only
`_ts2py_runtime.py` moved.

**Before / after** (J86-5 harness, scratchpad `j86-5/bench.py` + `inproc.py`: scratch copies of
the repo store (91 facts + 80 archived), `~/.bantamkit/memory` (98 + 38) and Claude Code's native
store for this repo (208 files) under a throwaway HOME; n = 7, medians; hooks and the CLI are
process wall time with cold imports; the rest in-process. Pre-#315 is `f6a5b74e` in a scratch
worktree; "J86-3" is `76751838`.)

| Operation | pre-#315 | J86-3 | J86-5 | vs pre-#315 |
|---|---|---|---|---|
| hook SessionStart, index warm | 376.8 ms | 549.1 ms | 419.3 ms | +11.3% |
| hook UserPromptSubmit, index warm | 384.5 ms | 380.0 ms | 386.8 ms | +0.6% |
| hook SessionStart, no index (cold build) | 584.6 ms | 928.9 ms | 620.8 ms | +6.2% |
| hook UserPromptSubmit, no index | 598.5 ms | 763.8 ms | 634.8 ms | +6.1% |
| `python -m bantamkit.memory list` | 120.5 ms | 195.7 ms | 139.4 ms | +15.7% |
| `memory_recall`, long-lived server | 2.10 ms | 2.84 ms | 1.99 ms | -5.0% |
| `memory_recall`, first call in a process | 4.81 ms | — | 5.24 ms | +8.8% |
| `memory_save`, long-lived server | 4.60 ms | 78.5 ms | 2.40 ms | -47.8% |
| **`memory_save`, first call in a process** | 4.65 ms | — | 20.99 ms | **+351%** |
| **hot index build from nothing** (in-process) | 37.8 ms | 113.8 ms | 54.9 ms | **+45%** |
| **cold index build from nothing** (in-process) | 31.6 ms | 61.0 ms | 41.2 ms | **+30%** |
| `MemoryStore._facts()`, 91 facts, caches cold / warm | 4.56 / 4.51 ms | 78.5 ms | 20.9 / 2.40 ms | +359% / -47% |
| one frontmatter, first parse, caches cold (517 files) | 21 µs | 360 µs¹ | 145 µs | ≤ 200 µs bar met |

¹ best of 3 (no cache existed then); J86-3's own figure on 684 files was 830 µs.

**The bar** (no user-facing operation more than 20% slower at the median; a frontmatter parse at
most 200 µs) **is met for every hook, the CLI, recall, a long-lived server's save, and the parse;
it is NOT met for the three whole-store cold parses in bold.** Those are N files × ~145 µs against
N × 21 µs for libyaml: a cache cannot help the first read of a text in a process, and the hooks
absorb it only because their fixed ~370 ms of process start dominates. In absolute terms the first
`memory_save` of a server's life costs +16 ms and a from-nothing index build +17 ms (hot) / +10 ms
(cold); the user-facing hook that performs that build is +6.2%.

What the floor is made of now: per-character scanner loops (`_scan_quoted` builds a string one
`push` at a time through ~8 helper calls per character) and `resolve_implicit_tag` (~12 calls per
frontmatter, each walking 8 resolvers through `_js_get`/`_js_m_includes`/`_js_m_test`), about 30%
each. Options left, with their costs:

1. **Type-directed lowering in ts2py** (the brief's first preference, not done here): track
   locals proven `number`/`string` from their initialisers and every assignment, so `i + 1`,
   `i < s.length`, `s[i]` lower to plain Python. Needs a fact lattice over `let` reassignment and
   closures, cargo tests per fact, and the full differential; parameters stay unproven (the Python
   adapter is a caller TypeScript cannot check). Estimated 1.5-2x on the scanners: closes the hot
   index build to roughly +20%, not the first save.
2. **Change the TypeScript scanners** (`factfile.ts`, outside this unit's layer): scan a quoted
   scalar by `indexOf`/regex chunks instead of per character; behaviour-neutral for Node, guarded
   by `--suite ts2py-codec`/`codec`. Probably the largest single gain on quoted descriptions.
3. **A persistent parse cache** (e.g. beside the hot index): would make the first read in a
   process cheap, but it is a new on-disk artifact in one runtime only, so it would need a ruling
   under the two-runtimes rule.
4. Accept the three cold paths (+10 to +17 ms absolute, once per process).

Every module #316 moves still pays some per-operation overhead; the fast paths above are shared by
all generated code, so it is smaller than J86-3 feared, but #316's G3/G4 should be re-measured
with this harness rather than budgeted from either number here.

### Estimate for #316, by dependency group

**Method (rerunnable: `node tools/ts2py/census.mjs`, after `cd runtime-ts && npm ci`; one JSON
row per group below, then the totals row. Committed by J86-6 and rerun 2026-11-15 under Node
v26.13.0 at `ac433783` and at `76751838`, where this table was first written: every row below
reproduced, both times).** A census walked every `runtime-ts/src/*.ts` module with the TypeScript
5.9.3 compiler API (`ts.createSourceFile`, no type checker). It counted (a) executable syntax kinds,
with type-only syntax and trivia skipped, and (b) builtin call names: a global (`JSON.parse`,
`Buffer.from`, `new Promise()`), a method name that exists on a JS builtin prototype (`.forEach`,
`.subarray`), and any call into a Node builtin import (`node:fs:statSync`). Calls to functions the
module declares or imports from another `src` module are user code and were not counted. An item
is *lowered* when it occurs in a module ts2py already compiles (`workplan`, `memory/factfile`,
`memory/pyyaml`: 76 kinds, 56 call names). A call into a Node builtin or a Node global (`Buffer`,
`process`, `Date`, `URL`, timers) is an *adapter*, not a rule. Groups are taken in #313's order
and each group's items count as lowered for every later group (G10 last, since it stays per
runtime). Two calibration points convert items to rules: J85 compiled `workplan` (68 items) with
59 rules, 0.87 rules per item; J86 met 64 items new over `workplan` (30 kinds, 34 call names) and
wrote 71 rules (44 new + 27 extended), 1.11 per item. Rules = new items × [0.87, 1.11]. Units =
ceil(rules / 71) compiler units + 3 (a differential, the switch, a review: J86-2, J86-3, J86-R)
for the low end, and ceil(rules / 59) + 3 + ceil(lines / 2,003) (one fix unit per codec-sized
slice of source, as J86-4 was) for the high end. Generated Python lines = TS lines × [0.58, 0.70]
(`workplan` 162/280, the codec 1,393/2,003).

| Group (remaining modules) | TS lines | New syntax kinds | New builtin calls | Adapters (Node calls) | Rules | Units | Generated Python lines |
|---|---|---|---|---|---|---|---|
| G1 pure core (`pricing`, `jobbudget`) | 551 | 5: `**`, `try`/`catch` (2 kinds), a template literal with no substitution, `?.` | 5 | 3 (`path.join`, `fs.existsSync`, `fs.readFileSync`) | 9–11 | 4–5 | 320–386 |
| G2 codecs (`pyjson`, `pyjsonschema`, `eventlog`, `tokenledger`, `storage/logsegment`, `pysem`) | 4,469 | 8: `super`, `<<`, `\|`, `\|=`, `&`, `??=`, `yield`, `import * as` | 28 | 24 (`vm.Script`, `fs` open/write/rename/stat, `crypto.randomBytes`, `Date.now`, …) | 31–40 | 4–7 | 2,592–3,128 |
| G3 memory (`store`, `retrieval`, `dream`, `layers`, `queries`, `usage`, `cli`, `native`, `component`) | 8,530 | 3: `>>`, postfix `++`/`--`, `<<=` | 27 | 8 (`os.homedir`, `crypto.createHash`, `process.cwd`, …) | 26–33 | 4–9 | 4,947–5,971 |
| G4 storage (`hotindex`, `coldindex`, `tiers`, `retention`, `retention-child`, `lock`, `index`) | 2,806 | 4: `override`, `import.meta`, `await`, dynamic `import()` | 5 | 7 (`child_process.spawn`, `fs.fsyncSync`, `url.fileURLToPath`, …) | 8–10 | 4–6 | 1,627–1,964 |
| G5 shiftwork | 2,444 | 0 | 0 | 2 (`child_process.spawnSync`, `path.isAbsolute`) | 0 | 3–5 | 1,418–1,711 |
| G6 skills (11 modules) | 8,843 | 3: computed property name, `/=`, `delete` | 5 | 5 (`fs.realpathSync`, `fs.mkdtempSync`, `os.tmpdir`, symlinks) | 7–9 | 4–9 | 5,129–6,190 |
| G7 hooks (`hookadapter`, `replynative`, `statusline`, 9 `touch/*`) | 5,280 | 1: `for await` (`hookadapter` reading stdin) | 4 | 3 (`fs.accessSync`, `Date.parse`, `Buffer.allocUnsafe`) | 4–6 | 4–7 | 3,062–3,696 |
| G8 reader (`docread`, `charsets`, `repomap`, `htmlentities`) | 5,278 | 4: `^`, `>>>`, `&=`, `abstract` (`docread`) | 5 | 2 (`zlib.inflateRawSync`, `path.normalize`) | 8–10 | 4–7 | 3,061–3,695 |
| G9 install (`hostinstall`, `selfupdate`, `updatecheck`, `mcpreport`, `npminstall`) | 3,559 | 0 | 0 | 3 (`fs.chmodSync`, `fs.copyFileSync`, `new URL`) | 0 | 3–5 | 2,064–2,491 |
| G11 `client` (if decision 1 moves it) | 308 | 0 | 0 | 2 (`new Promise`, `setTimeout`) | 0 | 3–4 | 179–216 |
| not in #313's table (`contract`, `assets`, `errors`, `experiment`, `index`) | 1,147 | 0 | 0 | 0 new | 0 | 3–4 | 665–803 |
| **G1–G9, G11 and the unassigned five** | **43,215** | **28** | **79** | **59** | **93–119** | **40–68** | **25,064–30,251** |
| G10 adapters (`cli`, `pyargparse`, `memory/pyfs`, 6 `mcp/*`), stays per runtime | 7,861 | (1: `void`) | (6) | — | not compiled | — | — |

The pyfs seam is the largest adapter surface and is not in the adapter column: 25 modules import
25 distinct names from `memory/pyfs.ts` (62 exports), and since pyfs ports CPython's `os`
behaviour, each of those becomes a Python-native adapter where Python IS the reference (the
justification J86-1 used for `pyFloatRepr`).

**Known biases of the method.** (1) It counts syntax and names, not semantics: `try`/`catch`
appears new in every group (53 modules catch), but what a caught Node `fs` error must look like
to a Python caller (an `OSError` with CPython's `errno` and sentence) is adapter work the count
does not see. (2) `async`/`await` (11 modules) and generators (13 modules) are one kind each, but
lowering them is a control-flow change, not a rule; G4, G7, G9 and G11 carry most of it, so their
high ends are the likelier ones. (3) A method name is counted once whatever its receiver, so
`.keys` on a `Map` and on an `Object` look like one lowered item; the real rule count is higher
where receivers differ. (4) Two calibration points only, both on pure code with no I/O. (5) The
cumulative order assumes groups move in #313's order; another order moves items between rows but
not the total. (6) Units are J86's shape (compile, differential, switch, review, fixes); a group
whose differential finds pre-existing disagreements, as J86-2 found five, costs a ruling round
the estimate does not include.

**Remaining unknowns.** The per-operation overhead above and whether a ts2py optimisation unit
removes it; the error-shape contract across the pyfs seam (every `catch` over an `fs` call); how
`async` lowers (Python `asyncio`, or synchronous with the Node event loop's ordering reproduced);
the 19 import cycles #313 measured, each to be broken or moved as one unit; G11 decision 1; and
whether the hand-written readers left on `yaml.safe_load` (`hookadapter`'s native mirror,
`skillfile`, `divergence`) move with G7/G6/G3 under their own rulings.

## #316 J87-2: type-directed lowering in ts2py (measured 2026-11-15 on `feat/316-g1`, macOS arm64, Node 26.13.0, CPython 3.12.13)

The #315 read cost was carried here (the J86-5 table above: three cold paths over the 20% bar),
with the J86-R2 finding that a data field named like a builtin method was refused by name.
Both came from ts2py using no type information. J87-2 makes ts2py use the types the TypeScript
declares wherever the compiler can PROVE them, and lowers to cheaper exact Python only under that
proof (`tools/ts2py/SUBSET.md`, *Types*; ledger `tools/ts2py/RULES.md`, J87 rules).

**Mechanism.** oxc gives an AST and no type checker; `tsc`'s types are not proofs of a Python
value (`any`, `as`, `!`, `JSON.parse`, adapters). So ts2py infers facts locally from what it
controls (literals, the operations it lowers, every assignment, every return, every call site)
and finds them by a greatest fixpoint over the module: lower, observe, lower again until a round
observes exactly what it assumed. A function with guardable parameter annotations gets a typed
body; whatever can reach it with an unproven value (Python, an adapter, another module, an
unproven call site) enters through a guard under the function's own name (`type(s) is str`,
`_js_is_double(n)`, ...) that runs the typed body or the J86 untyped one. `const` bindings are
narrowed by guards that exit (`if (w === undefined) throw`, `ch === "'" || ch === '"'`).

**Same answers.** The generated modules changed (typed bodies and guards; 2,414 lines against
1,558) and answer exactly as before:

| Check | Result |
|---|---|
| `--suite ts2py` / `ts2py-codec` / `workplan` / `codec` / `store` | PASS 452 / 228 (2 ruled) / 294 / 519 (10 ruled) / 389 (10 ruled), 0 failures each |
| workplan fuzz (`fuzz_gen.mjs` regenerated from `dist`, `fuzz_cmp.py`), seeds 1-3, 11-15 | 8 x 5,000 graphs, 0 mismatches |
| `j86-r/readfuzz.py 1 20000`, `writefuzz.py 1 5000` | no DIFF line; stats identical to `b1a6d257` (`fallback 17142, ruled-skip 1746, gen 1112`; `gen 4981, fb 19`) |
| `j86-r/fastpath.py` (runtime vs J86-5's original) | 44,000 calls, 0 diffs |
| per-input differential, `b1a6d257` against this branch (readfuzz/writefuzz generators, seeds 1-3; raw generated parse, the store's load, the store's write) | 75,000 answers, byte-identical |
| the 14 new helpers against the general helpers (any argument) | 120,000 calls, 0 diffs (cargo test runs 30,000; two mutants caught) |
| `pytest runtime-py/tests -q` | 5,295 passed, 58 skipped, 2 deselected, 3 xfailed (414.8 s) |
| `node tools/conformance/run.mjs --all` | PASS 22,753 cases, 198 ruled-different, 0 failures (697 s) |

**Measured.** J86-5's harness unchanged (scratchpad `j86-5/bench.py` + `inproc.py`, fresh scratch
copies of the repo store, `~/.bantamkit/memory` and this repo's Claude Code native store under a
throwaway HOME; hooks and the CLI as process wall time with cold imports, the rest in-process;
n = 9 runs, medians). All three trees were measured back to back in one sitting: pre-#315 is
`f6a5b74e`, J86-5 is `b1a6d257` (both `git archive` copies of `runtime-py/src`), J87-2 is this
branch.

| Operation | pre-#315 | J86-5 (`b1a6d257`) | J87-2 | vs pre-#315 | bar (+20%) |
|---|---|---|---|---|---|
| hook SessionStart, index warm | 368.3 ms | 404.4 ms | 385.0 ms | +4.5% | met |
| hook UserPromptSubmit, index warm | 380.3 ms | 375.8 ms | 380.4 ms | +0.1% | met |
| hook SessionStart, no index (cold build) | 570.1 ms | 619.7 ms | 587.6 ms | +3.1% | met |
| hook UserPromptSubmit, no index | 576.1 ms | 627.8 ms | 600.1 ms | +4.2% | met |
| `python -m bantamkit.memory list` | 116.8 ms | 136.0 ms | 129.2 ms | +10.6% | met |
| `memory_recall`, long-lived server | 2.02 ms | 2.04 ms | 2.02 ms | +0.1% | met |
| `memory_recall`, first call in a process | 4.94 ms | 5.51 ms | 5.10 ms | +3.2% | met |
| `memory_save`, long-lived server | 4.51 ms | 2.39 ms | 2.60 ms | -42.2% | met |
| `memory_save`, first call in a process | 4.87 ms | 21.0 ms | 11.3 ms | +130.9% | **NOT met** |
| hot index build from nothing (in-process) | 37.2 ms | 54.2 ms | 43.9 ms | +18.0% | met |
| cold index build from nothing (in-process) | 31.8 ms | 40.8 ms | 35.0 ms | +10.0% | met |
| `MemoryStore._facts()`, 91 facts, caches cold | 4.50 ms | 20.8 ms | 11.3 ms | +151.5% | **NOT met** |
| `MemoryStore._facts()`, 91 facts, caches warm | 4.46 ms | 2.34 ms | 2.37 ms | -46.8% | met |
| one frontmatter, first parse, caches cold | 20 µs | 144 µs | 58 µs | +189.6% | ≤ 200 µs: met |

**The bar is met for every operation but the first read of a whole store in a process**:
`memory_save`'s first call (+131%, +6.4 ms) and the `_facts()` cold parse it consists of
(+152%). Both hot and cold index builds are now inside 20% (+18.0%, +10.0%), and a frontmatter's
first parse is 58 µs (median, 518 files) against the 200 µs bar. The floor: `_facts()` cold over
the repo store parses 93 frontmatters in 8.1 ms (about 87 µs each, these files carry link and
keyword lists), against about 0.2 ms through libyaml; the rest of `_facts()` is unchanged. What is
left after J87-2 is no longer dispatch: it is spread over the scanners' inherent per-line work (a
regex `exec` on a slice per entry, `indexOf`/`slice`/two `replace`s per plain-scalar line,
`resolve_implicit_tag` per scalar, a join of per-character pushes in quoted scalars), each now a
direct helper or plain Python. Options, none taken here:

1. **Flow-sensitive facts** (a binding's fact per program point rather than met over the
   function): the one remaining unproven position is where one assignment cannot be proven;
   small further gains, a large analysis.
2. **Change the TypeScript scanners** (`factfile.ts`, outside this unit's layer): fewer slices and
   per-character pushes; behaviour-neutral for Node, guarded by `ts2py-codec`/`codec`.
3. **A persistent parse cache**: a new on-disk artifact in one runtime, so it needs a ruling under
   the two-runtimes rule.
4. Accept: +6.4 ms once per process for the first save.

Carried, not fixed: the J85 rule that a call of a function annotated `: boolean` is a known bool
(`bool_fns`) trusts a return annotation, which J87's own rules do not; it changes `and`/`or` and
conditions only, and no divergence was observed, but it is not a proof.
**Closed by J87-3:** the rule is dropped. A call now proves what every `return` of the body proved
(the fixpoint's return facts), never the annotation; `tests/types.rs`
(`a_boolean_return_annotation_is_not_proof`) pins a `: boolean` function that returns its `any`
argument, lowered with JS truthiness and answering Node's `["yes","no",false,"and","or",false,1]`,
where J87-2's compiler answered `["no","yes",true,...]`. One committed line moved
(`factfile.py`, `py_list`: `value.truthy` is now tested with `_js_truthy`), with no answer changed.

## #316 J87-3: G1 (`pricing`, `jobbudget`) generated by ts2py (measured 2026-11-15 on `feat/316-g1`, macOS arm64, Node 26.13.0, CPython 3.12.13)

`runtime-ts/src/pricing.ts` and `jobbudget.ts` are compiled by `tools/ts2py` to
`runtime-py/src/bantamkit/_generated/pricing.py` and `jobbudget.py`, committed, and
`bantamkit.pricing` / `bantamkit.jobbudget` serve them through shims. The hand-written Python is
retired. The shims' conveniences, the adapters, the fs error shape, the behaviour changes (all
toward Node), one pending ruling and the retired tests are in `docs/porting.md`, *Generated
modules* → *Pricing and the job budget*.

| What | Census estimate (#315) | Actual |
|---|---|---|
| TypeScript lines | 551 | 560 (`jobbudget.ts` grew in J87-1F; the census rerun at this tree says 560) |
| New syntax kinds | 5: `**`, `try` / `catch` (2), a template with no substitution, `?.` | 4 needed a rule (`**` of literals, `try`, `catch`, one optional read); the no-substitution template was already lowered. Plus 2 the census counts as known kinds: a C-style `for` with clauses, a spread argument to `Math.min` |
| New builtin calls | 5 (6 at this tree) | 5: `JSON.parse`, `Number.isFinite`, `Math.trunc`, `.splice`, `.reduce`; plus `Number.MAX_SAFE_INTEGER` and `process.env` |
| Rules | 9-11 (10-12 at this tree) | **17: 11 new, 6 extended** (J86 rules 2, 10, 20, 34; J85 rules 36, 52); every other rule reused unchanged (`tools/ts2py/RULES.md`, J87-3) |
| Adapters | 3 (`path.join`, `fs.existsSync`, `fs.readFileSync`) | **9 rows**: those 3, `process.env`, and 4 where Python is the reference (`pyRepr`, `cmpCodepoint`, `assetsRoot`, `BantamError`), which the census reads as user code because they import uncompiled `src` modules |
| Generated Python lines | 320-386 | 519 (`pricing.py` 340, `jobbudget.py` 179): J87-2's typed bodies and guarded entries write five functions twice |
| Runtime support | — | 11 names added (`_js_catch`, `_js_json_parse`, `_js_py_value`, ...); no existing helper changed; `_ts2py_runtime.py` 1,889 → 2,062 lines, `_ts2py_adapters.py` 60 → 369 |
| Units | 4-5 | 1 compiler-and-switch unit (J87-3), after J87-1 / J87-1F / J87-1G (the differential and its fixes) and J87-2 (type facts) |

**Adapter measurements** (against Node 26.13): `path.join` 60,000 random joins equal on posix and
41,055 on win32 (18,945 refused by the colon and device-name subset); `readFileSync(p, 'utf8')`
30,000 byte strings and 2,000 files equal; `existsSync` 18 path shapes equal.

**The #315 unknown "error shape across the pyfs seam"**, for the fs adapters G1 needed: an fs error
reaches the Python caller as CPython's own `OSError` from `open()` (class, errno, strerror,
filename, args, text), whether a generated `catch` rethrows it or nothing catches it; a generated
`catch` catches only what JS could have thrown, so a subset refusal is never swallowed
(`tools/ts2py/tests/g1.rs`, `fs_errors_reach_python_as_cpython_raises_them`).

**Differential.** `--suite pricing` 84 cases (3 new `load:` cases: a directory, an invalid UTF-8
byte, a BOM; the directory case crashes the hand-written Python with `IsADirectoryError`, the
divergence the switch closes), `--suite jobbudget` 1,149 cases with **0 ruled** (J87-1G left 1,141
with 8 ruled: the 4 `ruled:` budget inputs and 3 `ruled checkpoint limit:` cases went stale, 10
failures, the moment Python switched, and are now ordinary cases pinned per side). Found and not
fixed (`docs/porting.md`, pending a ruling): a model named like an `Object.prototype` member
(`toString`, `constructor`, `__proto__`) is priced at $0.00 by Node; the Python shim keeps the
hand-written refusal.

**Red proofs.** A line appended to the committed `_generated/pricing.py`, then to `jobbudget.py`:
`--suite ts2py` `committed/pricing.py` / `committed/jobbudget.py` red (1 of 454 each). One newline
appended to `pricing.ts` and `jobbudget.ts`: `test_ts2py_fresh.py` 2 failed, 11 passed. The
`: boolean` probe against J87-2's compiler (`e6655be7`): `a_boolean_return_annotation_is_not_proof`
red.

**Cost** (n = 9, medians; before = `e6655be7`; full numbers in `docs/porting.md`): `import
bantamkit` 88.2 → 88.3 ms; the modules' own imports +0.09 ms (pricing) and +0.05 ms (jobbudget);
warm `price_tokens` 1.5 → 22.3 µs, a table's decode + validate 21 → 156 µs, a 42-line budget +
refusal 11 → 113 µs, all over 20% and all the JS-semantics runtime; `shiftwork.plan_batches` with a
budget +2.1% (12.49 → 12.76 ms).

| Gate on the switched tree | Result |
|---|---|
| `cargo test --release` (tools/ts2py) / clippy `-D warnings` / fmt | 55 passed, 0 failed / clean / clean |
| `--suite ts2py` / `pricing` / `jobbudget` / `workplan` / `codec` / `ts2py-codec` | PASS 454 / 84 / 1,149 / 294 / 519 (10 ruled) / 228 (2 ruled), 0 failures each |
| `cd runtime-ts && npm test` | 2,503 tests: 2,456 pass, 0 fail, 47 skipped |
| `pytest runtime-py/tests -q` | 5,286 passed, 58 skipped, 2 deselected, 3 xfailed (430.1 s) |
| `node tools/conformance/run.mjs --all` | PASS 22,766 cases: 3,734 byte-identical, 10,846 exact-string, 8,186 structural, 190 ruled-different (J87-2: 198; the 8 jobbudget rulings closed), 0 failures |
