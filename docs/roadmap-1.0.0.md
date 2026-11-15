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

### Read cost, the unknown this phase found

The generated read costs 830 µs per frontmatter against 21 µs for the libyaml path it replaced and
181 µs for pure `yaml.safe_load` (684 real frontmatters, best of 3); `MemoryStore._facts()` over 91
facts is 82 ms against 4.6 ms. The JS-semantics support layer is the cost, not the codec's logic.
Every module #316 moves will pay the same per-operation overhead, so #316 needs a budget for it
before G3/G4 (recall and the hot index read every fact), and probably a ts2py unit that lowers
the common helpers (`_js_get`, `_js_strict_eq`, UTF-16 length) to plain Python where the types are
known. That unit is not in the estimate below.

### Estimate for #316, by dependency group

**Method (rerunnable).** A census walked every `runtime-ts/src/*.ts` module with the TypeScript
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
