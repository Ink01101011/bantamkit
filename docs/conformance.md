# The conformance harness

`tools/conformance/run.mjs` runs the Python runtime and the Node runtime over the same
inputs and diffs their answers. It is the only reason the claim "the two runtimes write the
same bytes" is a measurement rather than an opinion.

```
node tools/conformance/run.mjs --all
node tools/conformance/run.mjs --suite store
node tools/conformance/run.mjs --list
```

Exit code is `0` on pass, `1` on any failure, `2` on a usage error or a missing reference
interpreter.

## Why a Python lives inside a Node port's test tooling

It is a **development-time** dependency of the harness. The shipped package declares
`files: ["dist", "assets"]`, so nothing under `tools/` is published, and `npm test` never
invokes this. The "no Python at runtime" ruling is about what a teammate downloads from npm.

Deleting the reference would mean the byte-compatibility claim rests on someone having read
two sources and agreed they match — which is the check that has never once caught the
difference that mattered. Every defect this job found in the port was found by running both
sides, not by reading either.

## The forty suites

| suite | what it compares |
|---|---|
| `cli` | the `bantamkit-mcp` command line as a process: stdout, stderr, exit code. **Extended 2026-09-11 by J46-28** to the question of WHO is on the other end of stdin: the bare invocation at a real terminal (the help, on stdout, exit 0), the bare invocation over a pipe driven with a real `initialize`, and `--store` at a terminal, which still SERVES because the empty argv is a scope and not a second signal. Five of its cases are NOT differential — what each side printed at a terminal, which stream carried it, that it is that runtime's own `-h` bytes, that a flagged terminal launch served, and that a piped bare launch answered — because a revert applied to BOTH runtimes leaves every differential green: measured, `--suite cli` goes from 4 failures on a one-sided revert to **3** on the two-sided one, and the differential `bare-at-a-tty/stdout` is one of the cases that goes back to passing |
| `charsets` | `runtime-ts/src/charsets.ts` against the live CPython codec registry: the file against what `runtime-ts/scripts/charsets-table.py` writes today (header excluded), all 256 bytes of every single-byte codec decoded by the reference against the port's table, the alias map and the module list |
| `codec` | fact-file frontmatter: emit byte-identically, and parse each other |
| `dream` | the cross-layer consolidation: one pair of stores materialised twice, `dream()` run on both, and three things compared per scenario — the returned `DreamResult`, the project directory byte for byte, and the profile directory byte for byte. Two of its cases are NOT differential: the mtime tie-break and the day-arithmetic calendar edge are rules written on both sides and asserted on neither, so they are pinned as typed literals against each runtime separately |
| `docread` | the reader as a library: `sniff`, the rows per part, the omission dicts, every `DocumentReadError` sentence and the `page()` window over the same 99 paths (96 files, plus `''`, `a/b/.` and `/dev/zero`, which are not), plus the thirteen checked-in fixtures under `runtime-py/tests/data/docread/` (a checked-in name wins over a built one), `a\x00b`, three `charset-<label>.eml` parts over the charset table's five bytes and the `<xmp>` 4301-digit charref, and the rulings — pdf/doc/rtf (refused on Node), bzip2/lzma (read by the reference, refused on Node by method number), utf-7, RFC 2231 and `<!ATTLIST>` defaults (both read, one row apart) — each with its refusal-bit companions |
| `instructions` | **the sentences the runtimes DELIVER against the surfaces they SERVE** (job60, after job59 found fourteen drifted imperatives): the `initialize` instructions block, all fourteen tool descriptions and inputSchemas, the served skills, the hook's four emitted sentences, a real `memory_save` budget refusal, and the two CLAUDE.md files, each read as a CLAIM and then exercised in the shape the sentence describes. It is NOT differential: `expected` is what the sentence promises and `actual` is what the surface answered, run once PER SERVER and named `<clause>/<row>/<side>/<what>`, so a drift both runtimes share is red twice rather than green once — five clauses: (a) every name a sentence uses resolves on the surface it names, (b) a served sub-schema is what the writer enforces, (c) a modal promise ("never refuses", "Required") survives a call that tests it, (d) every backticked command in the repo CLAUDE.md runs from a throwaway worktree, (e) a value one tool advertises (`plan.ready`) is accepted by the tool it points at or the description says it is not. Baseline at 56772d8: 56 cases, 42 red; the fixes are the job's other units, and the case count is what F4's mutation pass is measured against. F3 added row 58 — the operator CLI's unlistable-`archive/` refusal, run as `status` over a `chmod 311` archive on each side, guard case first — so the suite is 60 cases, and its only intended red is the user-level `~/.claude/CLAUDE.md` half of row 51, which the repo cannot edit **AMENDED 2026-09-26 (job64, J64-4): 60 cases became 70** (68 on a runner with no user-level `~/.claude/CLAUDE.md`; `BANTAMKIT_INSTRUCTIONS_USER_CLAUDE_MD` names it) — clause (c) `j64`: the new `memory_recall` description and `k` description as string literals per side, and the two behaviours they promise (an exact name answers that fact alone; `k: 1` over three matches answers three) exercised over MCP per side. Reverting the description reddens 2, removing the `k` floor 2, removing the name walk 2 **AMENDED 2026-10-20 (#222, TDQS): 82 cases became 126.** Clause (d) `tdqs`: for every served tool, per side, the list of input-schema properties with no non-empty `description` (one level under `properties`, `items` and `anyOf`) is expected empty (+30), and for the seven tools whose answer is a JSON object rather than a `result` string, the `outputSchema` names its keys and describes each (+14). RED-THEN-GREEN on the live pack, not a mutation: the first run reddened `shiftwork_clock_out` (`history_entry.unit`, `.outcome`, `.notes` undescribed) and `shiftwork_status` (`search.items.{job,file,line}` undescribed) on both sides, 4 failures, and the pack was fixed to it. The `j64` `memory_recall-description-wording` literal moved to the rewritten sentence, which still carries the floor and exact-name claims word for word; row 57 reddened on the rewrite until the `ready`/clockable sentence it reads for was put back |
| `hooks` | **the hook adapter, the hook installer and the export into the host's own auto-memory** (job62, J62-8), as two PROCESSES driven over ONE bed: each scenario builds its bed at one absolute path, runs the reference, restores the bed from a pristine copy and runs the port, so nothing compared is a path difference. Five surfaces: the ten `native*` fields of the `SessionStart` record and every byte the export left in the host directory (NOT stdout — what the export changes in the injected block is an absence); the one divergence it has, `nativeError`'s OS sentence, ruled with a non-ruled refusal-BIT companion and per-side literals beside it; `--install-hooks`' written `settings.json`, ruled on the recorded command and compared byte for byte everywhere else, plus the no-terminal refusal that must write nothing; and `docs/porting.md` rows 7 and 8 — the 600/400 cut counted in UTF-16 code units against code points, and the `.shiftwork` scan's `localeCompare` tie-break against a code-point sort — MEASURED here for the first time, ruled because they exist and not because they are wanted, each with the companion that says the divergence is a cut point or a tie-break and nothing else. Every hook run asserts the adapter followed its throwaway `HOME` before a byte it wrote is read **AMENDED 2026-09-20 (job62, J62-10, review): 42 cases became 56, and every one of the fourteen closes a hole this reviewer MEASURED rather than suspected.** (a) *what A writes*, pinned per side — the export's bytes were held by a differential and by a summary of COUNTS, so changing the exported file's own body prose in BOTH runtimes to say *"bantamkit rewrites this file every session"* left this suite at 42/0 and left both runtimes' unit tests green too; one exported file and the host index A appended to are now literals. (b) `prompt-fingerprint`, the third code-unit/code-point defect, ruled with an unruled `sha256`/`bytes` companion and per-side literals — `docs/porting.md` had argued no case could reach it, which was wrong, because this suite already reads hook log records. (c) `stale-install`, the one `docs/porting.md` row job62 added that nothing compared, now ruled with the block-minus-the-line compared unruled and the bit pinned per side. Six surfaces, not five **AMENDED 2026-09-21 (job62, J62-21): 56 cases became 69.** J62-20 gave `--remove-hooks` its first thirteen cases in either direction — the flag had none before, which is how it shipped with no consent gate and rewrote the operator's real `~/.claude/settings.json` with no terminal and no `--yes`. The thirteen are its four states, each refusal with the per-side literal beside the differential: `remove-hooks-no-tty` (exit 2, nothing written), `remove-hooks-declined` (exit 1, over ONE `pty.openpty()` from `ref/cli_tty_ref.py`), `remove-hooks-yes` (the four-line plan, the settings byte for byte, and a backup pinned by its CONTENTS rather than by a count — a dated backup is one file per day, so `backups`/`backupsAdded` both survive deleting `backup()` outright), and `remove-hooks-noop` (exit 0 BEFORE the gate). Nothing in the block is ruled different, so the suite's ruled-different count is unchanged at 7 and `--all`'s at 161. Each state seeds its OWN pair of homes: the first draft shared one pair and 8 of the 13 were vacuous. Printed 2026-09-21: `--suite hooks` **69 cases, 7 ruled-different, 0 failures**; `--all` **8833 cases, 161 ruled-different, 0 failures** **AMENDED 2026-09-21 (job63, J63-4): 69 cases had become 81 by J62-22; 81 became 105.** The hook-marker PRESENCE property (J62-22: an entry is bantamkit's because the `bantamkit` key is ON the inner hook object, never because of its value, so a release that writes a different value cannot orphan the last one's entries) was held only by each runtime's unit test and was INVISIBLE to this suite: rewriting both `_is_ours`/`isOurs` to a value test (`hook.get(HOOK_MARKER_KEY) == HOOK_MARKER_VALUE` / `hook[HOOK_MARKER_KEY] === HOOK_MARKER_VALUE`) left `--suite hooks` at 81 cases, 0 failures, because every bed carried the current value and the mutation was symmetric. The new `hook-marker-presence` block seeds marker-bearing entries whose value is NOT the current one — `"some-future-release"`, `""`, `0`, `1`, `false`, `null`, `{"v":1}` — one pair of homes per value, runs `--remove-hooks --yes` on each side, and pins per side that the report said `removed bantamkit hooks from …` and that the file left behind holds NO hook object carrying the key while the foreign entry in the same event survived; and `--install-hooks --yes` over seven stale foreign-valued entries, pinned at seven entries, none duplicated. RED-THEN-GREEN, measured: the same symmetric mutation now reddens exactly the 16 per-side literals and leaves the 8 differentials green (**105 cases, 16 failures**); the mutation on ONE side alone reddens 16 on either side (the 8 differentials plus that side's 8 literals). Nothing is ruled, so ruled-different stays 7. Printed 2026-09-21 with source unmutated: `--suite hooks` **105 cases, 7 ruled-different, 0 failures** **AMENDED 2026-09-26 (job64, reviewed by J64-7): 105 cases became 147.** Three blocks, each pinned per side because each property is absolute and a symmetric regression is invisible to a differential: `inject-no-stamp` (+12, J64-1 — an injecting `UserPromptSubmit` leaves every fact file's sha256, mtime_ns and `last_recalled:` line unchanged), `inject-dedupe` (+23, J64-2 — a context is not shown a fact name twice; reset on compaction and `clear`; `hits == injected + dropped + suppressed`), `dream-fingerprint` (+7, J64-3 — a recall, a re-date or a touch leaves the Stop fingerprint; content moves it). Re-run by the reviewer on a worktree copy, each mutation applied to BOTH runtimes: hook stamping restored → 4 failures; dedupe disabled → 10; `clear` reset removed → 4; seen-set keyed by session only → 6; fingerprint back to size + mtime → 4 — every one a per-side literal, every differential green. Nothing ruled, so ruled-different stays 7. Printed 2026-09-26: `--suite hooks` **147 cases, 7 ruled-different, 0 failures**; `--all` **9014 cases, 161 ruled-different, 0 failures**. Same job, other suites: `wire` 345 → 348 (J64-1's per-side `memory_recall stamps` literal, 2 failures when both MCP handlers stop stamping), `store` 256 → 260, `recall-strings` 103 → 123, `recall-gate` 37 → 41 (J64-4) **AMENDED 2026-09-26 (job64, J64-8, re-reviewed by J64-9): 147 cases became 152.** J64-7 found the port's seen-set test `name in seen` walking `Object.prototype`, so a fact named `constructor` — the one prototype key `NAME_RE` admits — was suppressed by Node on the first prompt of a fresh context while Python injected it; no bed held that name, so all 147 stayed green. `inject-dedupe` (g) adds a store holding `constructor` with per-side literals for both prompts and a two-prompt differential (+5). RED-THEN-GREEN, measured by the reviewer on a worktree copy with only the `Object.hasOwn` source hunk reverted: **152 cases, 2 failures** (the port's (g) literal and the differential); the reference is a `dict` and never had the defect. Nothing ruled, so ruled-different stays 7. Printed 2026-09-26: `--suite hooks` **152 cases, 7 ruled-different, 0 failures**; `--all` **9019 cases, 161 ruled-different, 0 failures** **AMENDED 2026-09-26 (PR 112 review): 152 cases became 161.** `typeof [] === 'object'`, so the port took an array at the whole ledger, at `injected`, or at `injected[<context>]` for the object it expected, kept the seen names as array properties that `JSON.stringify` drops, and injected again on every prompt; the reference's `isinstance(..., dict)` replaces each with an empty one. `inject-dedupe` (h) pre-writes each of the three shapes and pins per side that the second prompt suppresses, with a two-prompt differential per shape (+9). RED-THEN-GREEN, measured with the port's `Array.isArray` guards reverted: **161 cases, 6 failures**. Nothing ruled, so ruled-different stays 7. Printed 2026-09-26: `--suite hooks` **161 cases, 7 ruled-different, 0 failures**; `--all` **9028 cases, 161 ruled-different, 0 failures** **AMENDED job73 A5 (#205 Task 5):** scenario 21, `skill-audit-line`, runs SessionStart with no record and then twice over a home holding a five-finding `skill-audit.json`: stdout and the log's `skillAuditBytes` side to side, and per side the first block is the no-record block plus the 199-byte line, the second is the no-record block byte for byte (`skillAuditBytes` 0, 199, 0). Since job73 A6 (the orchestrator's ruling) those starts run with `BANTAMKIT_SKILL_AUDIT` unset over a `retention.json` stamped now (so no daily child spawns), and one more start between the record and the first runs with the switch `off`: it is the no-record block, `skillAuditBytes` 0, and the record is left byte-identical (`surfaced` not written) — so the bytes read 0, 0, 199, 0 |
| `mcpreport` | `--mcp-report` as a process, over one synthetic host-log/event-log pair |
| `install` | install-shape self-diagnosis (AS-7a) over ELEVEN matched installs BUILT PER RUN — a real `.dist-info` with a real `direct_url.json` on the reference side, a real `node_modules` with npm's real hidden lockfile on the port side — because the two runtimes' OWN installs are not alike in this harness and comparing them compares environments, not code. Shape, origin, reason, `install_source_exists`, the refusal bit and the whole `install-source-missing` sentence, path included: the origin is shared between the two halves so nothing is relativised into agreement. Four ruled divergences, each with the non-ruled companion `docs/porting.md` requires |
| `memorycli` | `bantamkit-memory` against `python -m bantamkit.memory` as processes: the transcript of every step, the exit codes, and the store afterwards |
| `pricing` | AS-1(b)'s price table: a token count converted into money. Every table travels as raw JSON TEXT so both decoders are under test, every sentence as base64, and the normalised table as ORDERED PAIRS because `JSON.parse` hoists an integer-like model name and `json.loads` does not — the one ordering the two runtimes are NOT claimed to share. 81 cases over the validator's every fault sentence, the four token classes priced separately, the per-class refusal, the 2**53-1 ceiling and `format_micros`. Six of its cases are NOT differential: the constants, the half-up rounding at the exact half and **the shipped table's emptiness** are pinned as typed literals against each runtime separately — the last of those is what makes pasting an unsourced rate into `assets/pricing/default.json` a visible act, and a differential cannot see it because both sides read the same file |
| `recall-gate` | roadmap #6's precision gate: the same store and the same `min_ratio` through both runtimes — which facts survive, the directory afterwards (a gated fact must not be stamped), and which ratios are refused. The ladder scores 4/3/2/1 so a floor can land EXACTLY on a fact: `0.5 * 4` is 2.0 and `0.25 * 4` is 1.0, exact in IEEE754 on both sides, and those are the only inputs that separate `>=` from `>`. `NaN`, `Infinity` and `-Infinity` are constructed inside each reference because JSON has no literal for them, and the constant is compared as its IEEE754 BITS because `json.dumps(0.0)` is `0.0` where `JSON.stringify(0)` is `0`. Four of its cases are NOT differential: the value of the constant, the at-threshold admission, the relative-gate property and the refusal sentence are each written twice and asserted on neither side, so they are pinned as typed literals against each runtime separately |
| `recall-queries` | #207 amendment 3, likely-prompt queries and the session head (job72 J72-27), through `ref/queries_ref.py` against `runtime-ts/dist` in-process, plus both servers over stdio for the write and status paths: (1) a mixed Thai/English pool over project, profile and native layers (a name shadowed between project and native), sidecars on two layers, seven prompts compared on `inject_candidates`, `rank_all(10)`, the `recall_outcome` reply and every `QueryScorer.column` call as IEEE-754 bits (a ref hook on both sides records the BM25F column and the summed one); (2) every empty-qdoc row scores exactly its BM25F; (3) a Thai-only query blanks to spaces and scores 0.0; (4) a prompt with no BM25F term injects the fact its queries hold, on the index path and the files path; (5) no sidecar, the read forced off and a sidecar holding only an orphan all give B byte for byte; (6) the files path (Python `snapshot()`, and an unparseable fact file on both sides) ranks what the index path ranks; (7) every malformed sidecar and entry, `v: 1.0` and a `\xff` byte included; (8-11) `_previous_prompt`/`previousPrompt` over the rules fixture, the 256 KiB tail boundary (a straddling line, a ghost record after the cut, exactly `TAIL_BYTES`, one byte over) and missing paths, and `_head_query`/`headQuery` at 79/80/81 code points and an astral 79; (13) `memory_save` with `queries` over each server's stdio leaves byte-identical sidecars; (14) each side's sidecar ranks the same in the other runtime; (15-16) S1-S4 and the refused save; (17-18) `memory_queries` list, write, S5-S9, the sidecars byte-unchanged after every refusal; (19) S10/S11 over `bantamkit_status` and the whole report minus the build line; (21) every shared constant; (22) fifteen tools and the `memory_queries`/`memory_save.queries` schemas; (23, J72-30) the derived term cache `<index dir>/<sha16>.qterms.json`: built on a missing cache with python and node bytes identical (ASCII, the sidecar's sha1, no cache for a layer with no sidecar), each side reading the other's (inode and mtime unchanged) and ranking as its own, a cache of OLD sidecar bytes never used (a fact only its stale queries held is not injected) and rewritten, a malformed and a deleted cache rebuilt byte for byte; the trace records the tokenized rows the scorer is handed. J72-30 MUTATIONS (rsync copies, control green, PASS 415): M14 Node uses a cache without checking its `sidecar` sha1 27, M15 the same in Python 27, M16 Python writes the terms unsorted 3, M17 Node never writes the cache 10, M18 Node never reads its own cache (always rebuilds) 1 (cross-read: the file is replaced). (24, J72-31) a sidecar whose bytes start with a UTF-8 BOM is MALFORMED on both sides, as CPython's `utf-8` codec plus `json.loads` make it: read as no sidecar, coverage and the missing list equal to the same bed with that sidecar deleted, seven prompts ranked as that bed, a project cache of `{"facts":{}}` with identical bytes, and a `memory_queries` write that replaces the file rather than merging into it; each one python against node, per side against the no-sidecar bed, and typed. J72-31 MUTATIONS: c83bb2c itself (Node stripping the BOM) 17; BOTH sides stripping it (Python `utf-8-sig` on that copy) 16, every one a literal or per-side case, with every differential green. Literals per side wherever a symmetric change would hide. The hook processes (12, the head end to end; 20, S12) are in `hooks.mjs`, the sentences' surfaces in `instructions.mjs`. MUTATIONS, measured 2026-10-18 on rsync copies (control green, PASS 341): `--suite recall-queries` reds M1 Node `stripNospace` returns its input 17, M2 Python `QUERY_WEIGHT = 0.5` 10, M3 the same on BOTH sides 4 (the constant literals and one inject literal; every differential green), M4 Node `HEAD_SHORT` on UTF-16 length 2, M5 Python keeps the tail's cut first line 4, M6 Node does not skip `isSidechain` 2 (and 2 in `--suite hooks`), M7 Python `pool_of` ignores `every_row` 4, M8 Node sidecar written without `sortKeys` 18, M9 Python S2 says "chars" 7, M10 Node `QueryScorer.dense = false` 22, M11 Node `readSidecar` through `JSON.parse` 2 (`v: 1.0`), M12 Python status line "query" 8, M13 Node keeps the trailing current prompt 12. M6 was GREEN in this suite on the first draft — the rules fixture never put the sidechain record last — and the `* record last` fixtures were added for it |
| `recall-retrieval` | #199's retrieval module (job68 J68-1, J68-2, J68-5: tokenizer, BM25F, gate and ranker): `tokenize_v2` / `tokenizeV2` over a 16-input corpus — Thai, Thai mixed with English, CJK, kana, emoji, combining marks, NFKC-sensitive input (fullwidth, the `ﬁ` ligature), final sigma, whitespace controls — each token list compared as JSON with every string travelling as base64. The no-space scripts are named by CODEPOINT RANGE, not by a Unicode-database script lookup, so two Unicode versions cannot split a run differently. Six cases are NOT differential: three inputs (Thai mixed with English, fullwidth, CJK) pinned as typed literals per side. Measured 2026-10-15 on an rsync copy: Node emitting unigrams for a no-space run → 8 failures; Python dropping NFKC → 3; the Thai range removed on BOTH sides → 2, the two Thai literals and no differential. BM25F (J68-2): `bm25_scores` / `bm25Scores` over a 12-doc Thai/English fixture with `keywords` for 10 queries, the scores AND the argsort they induce compared as JSON; one per-side literal (top doc for `"tag context"` is 1). Node's `pyRound9` is pinned to Python's `round(x, 9)` bit for bit over 1,000 seeded doubles in five groups (uniform, exact ties `j/1024`, near ties, random finite bits, small signed) plus a per-side tie literal. Measured 2026-10-15 on an rsync copy: Node `BM25_B = 0` → 10 failures; Python dropping `keywords` → 10; `idf = 1` on BOTH sides → 2, the two literals and no differential; Node `pyRound9` via `toFixed` → 2; via `Math.round(x * 1e9) / 1e9` → 4 EXTENDED by J68-5 (index v4): `bm25_segments` over 60 seeded run-length runs and `rank_columns` over 60 seeded (layer, name)-ordered runs, each side held to its OWN per-doc formula (`bm25_postings` over the runs expanded, `rank`) and to the other side, as bits. Measured 2026-10-16: BOTH sides scoring a run on its first doc's length → 2, the per-side self-consistency cases only; Python breaking a final tie toward the later id → 2 **RE-RUN by the reviewer (job68 J68-8) at `05d486e`, every plan-listed mutation on an rsync copy (`.shiftwork/notes-job68/J68-8.md`):** Node unigrams → 19; Python without NFKC → 11; the Thai range removed on BOTH sides → 2 (the two Thai literals); Node `BM25_B = 0` → 11; Python `keywords` boost 0 → 10; `idf = 1` on BOTH sides → 2 (the two literals); Node without the layer tie-break → 4; `W_TYPE.feedback = 1.0` on BOTH sides → 2 (the two per-side literals). Same run, other suites: Node writing `keywords: []` → `store` 23, `wire` 2; Node half-life 7 → `recall-usage` 18; Python counting `save` as use → 30; decay base 0.6 on BOTH sides → 4 (literals only); Python's hook path counting usage → `hooks` 3; Node repairing on the hook path → `store` 6; Python repairing on every recall → `store` 4 |
| `recall-strings` | the binding layer: every sentence an empty recall can produce |
| `recall-usage` | the usage ledger (#199, D5, job68 J68-4): one event script run by each runtime into its own throwaway home against ONE hashed store root, so the ledger's file name, every byte it writes, the decayed `weights` (as nine-decimal text, the fold's own spelling), `last_used`, `keywords_copy`, the skipped-line count over thirteen refused lines (bad JSON, `NaN`, a date that does not exist, a non-finite or non-numeric folded weight, an array, a blank line, a cut line) and the bytes after a `fold` — explicit and past the threshold — are compared; `store_id` over a real path, a symlink to it and two paths that do not exist. The fixtures carry what each side had to do on purpose: keywords `ensure_ascii=False` writes raw (Thai, an astral emoji, U+2028, a C0 control), a lone surrogate, CRLF lines, invalid UTF-8 inside a kept save line, and facts named `__proto__` and `constructor`. Four cases are NOT differential: the two-event decay fixture pinned at `1.5` per side, and the unwritable append pinned at `false` per side. Measured 2026-10-15 on a copy: Node half-life 7 → 12 failures; Python counting `save` as use → 15; the decay base 0.5 → 0.6 on BOTH sides → 2, the two literals and no differential. The lock and the temp-then-rename fold are exercised on macOS only; the Windows run is Task 8's manual step |
| `storage-index` | `HotIndex`, the derived per-source index (#204, S3/S6, job69 J69-2): four op scripts run by each runtime over its own copy of one bed, every file and directory mtime pinned to whole seconds, with the bed path and the wall-clock `full_at` replaced by markers before anything is compared. Compared: the index file BYTE FOR BYTE after every step (`json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`, every `mtime_ns` a decimal string because it is past 2**53), `docs`, `postings`, `df`, `avgdl` (as `repr`), `skipped`, and the refresh result at every step of a script that builds, refreshes fast, adds a file, edits one IN PLACE (fast answers `fresh`, full answers `patched`), lets `full_at` expire (fast behaves as full), removes the file that won a duplicate name, and corrupts the index four ways (bad JSON, `version`, `source`, `kind`, a `files` entry of the wrong shape); a native directory (the `metadata.type` shape, `links`/`tags` nested under `metadata:` as indented block sequences, a top-level `type`, no type, no name, `MEMORY.md`, a directory named `*.md`); an unwritable index directory; a store with no `facts/` yet; and `sha16` over a real path, a symlink and two paths that do not exist. Fixtures: Thai and an astral emoji written raw, facts named `__proto__` and `constructor`, a YAML-integer name and description, the store's own refusal sentences. Eight cases are NOT differential: the facts script's refresh sequence, the wiki-link fixture's `links`, the nested native `links`/`tags`, and the native tree (bytes and mtimes) unchanged by a refresh, each per side. Measured 2026-10-15 on rsync copies: Node ignoring the `full_at` age → 3 failures; Python's fast mode statting every file → 4; BOTH sides dropping wiki links → 4, all literals, no differential; Node writing unsorted keys → 7; Node's native reader ignoring `metadata.type` → 5; Python's duplicate rule keeping the LAST file → 11; Node escaping non-ASCII → 6; BOTH sides touching each native file they read → 2, the tree literals only; Node reading only column-0 block sequences → 5; BOTH sides ignoring `links`/`tags` under `metadata:` → 2, the literals only. EXTENDED by J69-3 (user ruling A: a HEAD plus postings sharded 16 ways by term hash, `INDEX_VERSION` 2) to 176 cases over seven scenarios: every shard file compared byte for byte, `shard_of` over pinned terms (literal per side), `query`/`query_words`, `loose`, a version-1 index and a doc of the wrong shape, a shard that is stale (valid JSON, wrong fingerprint), missing or not JSON read by a fresh `HotIndex` (rebuilt to the same bytes, its terms never trusted); and `MemoryStore` through the index: every `recall`/`lookup` answered as shipped AND with the index refused, which must agree and (per-side literals) be index-answered on a clean store and file-answered when a file is skipped or a name is not a string (Python's 9-before-10), write-through (a fast refresh after a save and a stamped lookup is `fresh`), `BANTAMKIT_INDEX_DIR` moving the head and its 32 shards, a store nobody can list refused with the store's sentence even with a fresh index, and the YAML refusal sentence (Python's is the pure SafeLoader's, never libyaml's; the text itself is the existing `store` ruling, re-pinned with a refusal-bit case). Measured 2026-10-16 on rsync copies (of 176): Node `shardOf` mod 15 → 16; Python trusting a shard past its fingerprint → 4; Node breaking name ties backwards → 9; Python writing nothing through → 3; BOTH sides answering from the index past a skipped file or a loose name → 9, literals and the ruling only; Python not probing the listing → 3; Node not probing → 3; Python using libyaml's refusal → 1; Node never re-deriving on a patch → 10; BOTH sides ignoring `BANTAMKIT_INDEX_DIR` → 2, the literals only; Node trusting a malformed doc in `docs()` → 2. macOS only; the Windows run is Task 8's manual step EXTENDED by J68-5 (#199, `INDEX_VERSION` 4: a two-line head with per-doc `cols`, postings as run-length segments over doc ids) to 197 cases: a v4 scenario (raw `segments`, a head whose second line is replaced — a recall still answers from the first line and leaves the file alone, a `docs` read rebuilds it) and two tie scenarios (two facts tied on every score whose names run opposite to their files, answered by the index and by the files); per-side literals pin the segments of a four-fact store, the two-line head, and the name tie-break on both paths. Measured 2026-10-16 on rsync copies (of 191, then 197): Python never merging a run → 17; BOTH sides scoring a run on its first doc's length → 2, the literals only; Node parsing the whole head → 2; Node's files pool not sorted by name → 4; Python's → 4 EXTENDED by job70 T200-2 (#200, `INDEX_VERSION` 5: every doc's `refs` holds the path references of its text, `fact_refs` over description, keywords and body for a store and `extract_refs` over description and body for a native file) to 205 cases: two v5 scenarios (a fact naming paths through `:line`, `#symbol`, a URL, a Thai-adjacent path, CRLF; a fact naming none; a native file) whose `docs` and index BYTES are compared, and one per-side literal pinning their `refs` and `version: 5` (no case had pinned `version: 4` per side, so the literal is new rather than renamed). Measured 2026-10-17 on rsync copies (of 205): Node's native docs keeping `refs: []` -> 3; Python's index left at version 4 -> 15; BOTH sides keeping `refs: []` -> 2, the literals only |
| `storage-cold` | `ColdIndex` and `memory_recall(include_archived)` (#204, S3, job69 J69-5): two op scripts run by each runtime over its own bed. Direct: two `add`s (the second shadowing a name), `query` (name, owning segment, summed tf), `docs`, `compact` (to one segment, same answers), a corrupt shard and a wrong-version manifest (both refused as `ColdIndexError`), `reset`, and every index file compared after each step — segments, 16 term-hash shards (`shard_of`, the hot index's hash) and the manifest with its wall-clock `created` masked. Over a store with pinned mtimes: `Memory.recall_outcome` with the flag off and on (archived hits after live ones, tagged `[archived]`, never stamped), an exact-name miss, an empty query, a malformed archived file, `restore` and `archive` between calls, an archived file rewritten (a newer segment shadows it), and the store's own cold index bytes after each move. Fixtures: Thai, an astral emoji, docs named `__proto__` and `constructor`, keywords. Six cases are NOT differential: the query after compaction, the shards a query opens (derived from the hot index's `shardOf`), the flag-on reply and the flag-off reply, each per side. The `wire` suite carries the MCP half: a `memory-archived` session (flag absent/false/true, archived-only, exact name, and the argument layer: `"notabool"`, `1`, `null`, `"true"`, `1.5`) with a per-side literal, and the `memory_compact` archive-listing case now expects the one fact that session plants. 51 cases. Measured 2026-10-16 on rsync copies: Node hashing to 8 shards → 10 failures; Python's `query` forgetting the segment id → 4; Node's archive sync keyed on the file name alone (a rewritten archived fact never re-indexed) → 3; Python's manifest giving a name to its OLDEST segment → 3; BOTH sides putting archived hits before live ones → 2 here and 2 in `wire`, the per-side literals only; Node's MCP handler dropping the flag → 0 here, 6 in `wire`; BOTH MCP handlers dropping it → 2 in `wire`, the per-side literals only. macOS only |
| `storage-log` | `LogSegment` and the shared O_EXCL lock (#204, S3/S4, job69 J69-1): seven op scripts run by each runtime in its own directory compare the live file's BYTES after every write, `read()` across rotated segments and the live file, the skipped count, `rotate` at its boundary (`size` does not rotate, `size - 1` does), each segment's DECOMPRESSED bytes, a fold through one of three named reducers (only `ts < older_than` is reduced; the boundary row, a numeric `ts` and a missing `ts` are kept; newer lines are kept as read, CRLF and `1.0` included), an unwritable directory and a missing log. Fixtures: Thai, an astral emoji, U+2028/U+2029/U+0085, DEL, C0 controls, a lone surrogate, keys `__proto__` and `constructor`; eight refused line shapes, invalid UTF-8 in a kept line, a cut line an append must not swallow, a corrupt segment and one past a numbering gap. One `ruling:` case: the raw `.gz` bytes are each zlib's own (`docs/porting.md`). Eight cases are NOT differential: the gzip header and zero mtime, the first line's raw UTF-8 bytes, the rows after the `sum_n` fold, and the unwritable append's `false`, each per side. Measured 2026-10-15 on a copy: Node folding `ts <= older_than` → 6 failures; Python's `read` skipping `.gz` → 4; both sides escaping non-ASCII → 2, the two first-line literals and no differential; Node not emptying the live file after rotate → 10. macOS only; the Windows run is Task 8's manual step **AMENDED 2026-10-15 (job69 J69-4, Task 4): the usage ledger, the hook log and the event log write through `LogSegment` now.** Four scenarios were added at the end, so no earlier case moved (185 → 221 cases): `.size` after an append; `fold_lines`, the line-level fold the usage ledger's reducer runs through (`older_than: null` folds the whole live file); the event log, which appends through `LogSegment` and keeps its own plain `.1` rotation, pinned per side (no `.gz`, the repaired cut line in the first `.1`); and a second `ruling:` case, a caller's float and integer-like key spelled by each serialiser (`docs/porting.md`), with a non-ruled `read` and a literal per side. The other logs' rotate cases live with their suites: `recall-usage` gained a 200-byte `rotate` scenario plus a per-side literal (167 → 208), and `hooks` gained `hook-log-rotate` over a seeded 1,000,000-byte log (221 → 227). Measured on rsync copies: Node's event log bypassing `LogSegment` → 2; Python's event log rotating into `.gz` → 3; both doing so → 2, the per-side literals only; Python's `fold_lines(null)` leaving a no-object file alone → 1; Node's `.size` leaving the line out → 2; Python normalising `1.0` → 1, its literal only; Node's line fold re-serialising kept lines → 3 here and 2 in `recall-usage` |
| `storage-retention` | Retention, the daily verify-before-delete job (#204, S4, job69 J69-6): one trap fixture, built identically for each side with pinned mtimes, run through `run_retention` / `runRetention`, and the whole tree compared after every run as `[relative path, sha256]` (a `.gz` file hashed AFTER decompression; `retention.json` content compared through the `child` op). Traps: an OPEN job 30 days old, a closed job 6 days old, a closed job whose newest file is 6 days old, a ledger exactly 7 days old, a non-ledger name, an unreadable checkpoint, an empty plan, a checkpoint behind a BOM, an older archive of the same name that differs, a FILE where the archive directory goes, a fact 400 days old. Also: the hook-log fold rows (a row AT the 30-day cutoff kept, an earlier fold merged, a row with no `event`), the usage fold at the cutoff, an idle log rotated, the job cold index bytes (manifest `created` and store id masked), `shiftwork_status(search)` hits, a second run that changes nothing, a ghost doc pruned at compaction, the once-a-day TTL (23:59:59.999 fresh, 24 h due, a stamp ahead due, garbage due), and `BANTAMKIT_RETENTION=off`. Thirteen cases are NOT differential: files gone, the deleted, refused and archived lists, the opt-out report, the search hits and the folded hook log, each per side. The `wire` suite carries the MCP half: a `shiftwork-search` session (`search` absent, a hit, `""`, `null`, a refused `5`, a missing checkpoint, Thai) with a per-side literal. 57 cases. Measured 2026-10-16 on rsync copies: Node deleting before verifying → 23 failures; Python treating an open job as closed → 19; BOTH 7-day windows moved to 6 → 4, the per-side literals only; Python deleting a ledger exactly 7 days old → 11; Node's fold forgetting `tool` → 9; Node's search matching ANY word → 2; Python's TTL inclusive at 24 h → 1; Node ignoring the opt-out → 4; Node's usage fold computed at now → 9; Node rotating a live log → 13; Python's compaction ignoring the prune → 1; Python skipping a failed archive write → 4 (the verify still refused the delete); Node's MCP handler dropping `search` → 0 here, 5 in `wire`; BOTH handlers dropping it → 2 in `wire`, the per-side literals only. macOS only. **AMENDED 2026-10-16 (job69 J69-8, review): a fifth scenario, a closed job whose `notes-<job>` is a LINK to a directory outside `.shiftwork/`** (a Windows junction, which needs no privilege; a directory symlink on POSIX). Both runtimes used to bundle the file behind the link and then delete it through the link; now neither walks it. The tree helpers on both sides list a link as `<link>` and never descend it (no earlier scenario has a link, so no earlier case moved; 57 → 66 cases). Two literals per side: the file behind the link survives and the link stays; the archive holds only the job's own two files. Measured on rsync copies: BOTH sides following the link → 4, the four literals only; Python alone following it → 4 (the tree and archive differentials + the two python literals). Vacuity probes on cases no earlier mutation had reddened: Node accepting a wrong-version cold manifest → `storage-cold` 1 (`#17 query`); Python's `reset` leaving the shards → `storage-cold` 1 (`#19 files`); Node treating a `ran_at` ahead of now as fresh → 1 (`#06 due 2026-10-15T23:59:59.999Z`). The verify step's "changed since bundled" refusal is reachable by no case here (it needs a write between bundle and delete) and is pinned by a unit test per side instead: removing it → `test_storage_retention.py` 1 failed, `storage-retention.test.mjs` fail 1, this suite still green. |
| `storage-tiers` | Capability tiers and the storage lines of `bantamkit_status` (#204, S2, job69 J69-7), over the wire: four sessions driven exactly as `wire` drives them (`ref/wire_ref.py` against `wire.mjs`'s `runNode`), both runtimes over identical scratch paths rebuilt before each side, one mask (line 2's build digest; `build_identity`'s reply compared by `isError` alone). The MCP-ONLY host profile — a HOME with no `.claude/`, no hook, no native directory, a cwd with no project settings — calls every one of the fifteen served tools (#207 amendment 3 added `memory_queries` to the session list; it lists and writes nothing) plus the `bantamkit_status` prompt and compares every frame; a HOOKED profile (a marked hook in the user's settings beside someone else's, an `autoMemoryDirectory` holding `MEMORY.md`, a hook log with a rotated `.1.gz` segment and an unparseable line, a usage ledger with a `NaN` line, a retention record with one refusal); a hook registered only in the project's `.claude/settings.local.json`; and an index directory that cannot be created (`BANTAMKIT_INDEX_DIR` under a file), where recall still answers. Literals per side: the storage block on each profile (`storage: core on; hooks on|off; host data on|off`, the index line with its byte count shape-checked per side and compared across sides, `logs: <name> <bytes> (<n> rotated, <n> skipped)` with the harness's own byte counts, `retention: off; last ran …; refused <n>`), every served tool answering without `isError`, the tools driven equal to what `tools/list` serves, and recall over the unwritable index. The `wire` suite's status sessions compare the same block (it follows the update line, so no earlier line moved). **AMENDED 2026-10-17 (job70 T200-1, #200): every storage block gains `touch: none` between the logs and retention**, and the block reader takes `touch` lines. macOS only |
| `repomap` | roadmap #10's ranked definition map: the walk, the per-file scan (comment-stripped digest, definitions, reference-set digest), the whole edge map, every node's IEEE-754 SCORE BITS, every rendered listing as bytes, every omission, and the `repo_map` tool's rendered reply — over five purpose-built trees (ordinary, boundary, astral, single-file, document-frequency) and 8 budget calls plus per-tree foci, and 7 `pagerank` scenarios with no filesystem at all. Every float travels as its big-endian bit pattern and every string as base64, because a differential comparing `String(x)` measures the serialisers. **The corpus is BUILT, never this repository**: J45-10 measured three wrong answers from mapping the checkout while writing into it, one of which scored four equivalent mutants as KILLED. Five of its cases are NOT differential — the constants, the astral-plane tie-break, the omission vocabulary, the reply tail and the empty-listing sentence are pinned as typed literals against each runtime separately, and the tie-break is the one rule NO Python test can make non-vacuous (CPython's `str` comparison IS code-point comparison), so only a case can prove the two agree |
| `shiftwork` | the checkpoint writer: `ensure_ascii`, `sort_keys`, separators, `5.0` **AMENDED 2026-09-21 (job63, J63-2, roadmap (eee)): as uid 0 the suite WITHHOLDS its three `chmod 0o555` sessions and the four per-side rows that read one of them, and prints their count and names in a note (`… skipped as uid 0: root ignores permission bits, so an unwritable directory cannot be made — …`), because root cannot make the directory unwritable and the arm silently never armed: measured in `bk-linux:gates3` on this tree as root, the two `readonly-directory-*` sessions were GREEN with nothing proved (every row they have is a differential over two identical successes) and `briefed/clock-in-on-an-unwritable-log` was RED on its two per-side literal rows, 2 failures; with the abstention, root prints the note and 0 failures, uid 1000 prints no note and 0 failures with the arms running, and the uid test mutated to never fire sends the root run back to 2 failures. Printed 2026-09-21 as root: 56 cases skipped, 1703 run, 0 failures; as uid 1000 and on the host: 1759 run, 0 failures. Privileges are not dropped instead, because `readonly-directory-after-the-log-line` depends on appending to a log root created while the directory is read-only, which a dropped euid cannot do** |
| `skillaudit` | the catalogue auditor: the whole `Audit` document over the committed nineteen-skill fixture tree, every finding kind, every omission and every refusal sentence. **Added to this table 2026-09-07 by J45-11, which found it missing** — the suite has run in `--all` since job44 and the header said "fourteen" over fourteen rows for fifteen suites, so a reader counting this page was one short and nothing compared the page against `--list`. **AMENDED job73 A1 (#205 Task 1, commit 23307a6): 94 cases became 114.** An `audit_roots` op audits several labelled roots as one catalogue: 16 differential documents (one root, whose findings equal `audit`'s; the fixture plus a scratch user root with a solo-check collision, a `race condition` quoter and a `deadlock-hunt` sharing a plugin skill's bare name, both counted per Amendment A1; three roots with a newer `dup-kit/1.2.0` in a second plugin root; ten refusals) and 4 per-side literals. The 94 earlier cases are unchanged, which is the guard on `audit`'s refactor. Mutations on rsync copies: port drops the label prefix 7 red; reference dedupes per root 6; reference resolves versions per root 1; port dedupes by bare name across the plugin root 6; BOTH dedupe by bare name 2, the per-side literals only |
| `skill-host` | the skill audit's host adapters (#205, job73 A2): `skillhost` against its port over seven beds (twelve since A3) built at one path under the scratch and rebuilt before each side — the Claude Code adapter's roots (`plugins, project, user`), the `enabledPlugins` winner per id and the file it won in (a BOM settings file skipped), the version chosen from `installed_plugins.json` (the project install for this cwd first), and the 30-day call counts: a `Skill` tool_use deduped by `id`, a typed `/<skill>` command record deduped by `uuid` and counted only when it names a skill the roots hold, subagent transcripts walked, an older file not read, a strictly undecodable line skipped, a symlinked directory not walked. The Null adapter answers `usage: null`. Literals per side pin the counts, the spans (30, 12), the two-shape total and the version choice. Since job73 A3 (Task 3) every bed also runs `skillreport`'s `record` and `render` (the stored record and the report a person reads), and five `report-*` beds pin the disable proposals: exactly `alpha@mk` with its settings line as a zero-context hunk; nothing under 30 days (D2), nothing when one skill of the plugin was called (D3), the hand-edit sentence for a minified file, the line inside `enabledPlugins` and not an earlier one (D4, CRLF); a `propose` op shows a missing measurement proposes nothing at 30 days (D1), and a switched-on `"@"` proves a personal skill is never grouped into a plugin. Each side must leave every settings file byte-identical (K2). The mode-000 transcript row is POSIX-only and the symlink bed is skipped on win32. Since job73 A4 (Task 4) every bed also gets a `.bantamkit/` and runs `status` (never ran; `BANTAMKIT_SKILL_AUDIT=off`; `BANTAMKIT_RETENTION=off`, which must NOT print `off; `), `daily` (the bytes of `skill-audit.json`), `status` after it, and `status` over a corrupt file, a wrong version, an error record and a BOM; `report-full` and `claude-full` carry `surfaced` over a day later. A thirteenth bed, `daily-trap`, runs the Retention child in process over a retention trap (a ledger 8 days old, a hook-log line past 30 days, an idle usage log, a closed job 8 days old): with retention off and the audit on, a snapshot of every path and mtime before and after must differ ONLY in `retention.json`'s claim and `skill-audit.json` (Amendment A3, J69-6's class); a second child the same day neither audits nor sweeps; both off does nothing; retention on and the audit off sweeps and writes no record; and `maybe_spawn`, over a `retention.json` stamped at the wall clock (so no child starts), answers `off` only when BOTH switches are off, `fresh` otherwise. Literals per side pin each of those. Since job73 A5 (Task 5, the SessionStart line) every bed also runs `daily`, `line` twice, `daily` a day later and `line` again: the second call and the call after the next day's run are null on every bed (nothing repeats), and every line any bed makes is at most 200 UTF-8 bytes. A fourteenth bed, `session-line`, puts hand-made records first and pins per side: the plan's five-finding record names exactly its 199-byte `LINE` then null, with all five keys in `surfaced`; all surfaced is null with the file unchanged (the 0-byte bar); a 29-day span holds a `never-invoked` back, 30 names it; a Thai item is clipped on a code point with `…`; an error record and a corrupt file are silent, the corrupt file unchanged; a malformed finding is skipped. Mutations S1 (port writes no `surfaced`), S2 (reference cap 300), S3 (port clips by UTF-16 units), S4 (reference ignores the 30 days) and S5 (both emit `0 new`, symmetric: literals only) are each red. Since job73 A6 the `line` op carries an `env` (the audit switch unset by default, since the harness runs with it off), and `line FULL, audit off` pins per side that `BANTAMKIT_SKILL_AUDIT=off` silences the line over unseen findings and leaves the record unchanged (the orchestrator's ruling). Since job73 A6 (Task 6, the `skill_audit` MCP prompt) two wire sessions, driven as `storage-tiers` drives them, run over `claude-full` (its transcript stamps and mtimes moved to the wall clock, because the server's `now` is live) and `null`: `prompts/list`, `prompts/get skill_audit`, `prompts/get bantamkit_status`, `prompts/get nope` and `tools/call bantamkit_status`, each frame compared as canonical JSON with the build digest masked; literals per side pin the names `["bantamkit_status", "skill_audit"]`, the `null` bed's text (the could-not-run sentence and the tail), the `claude-full` report then the tail, `-32602` for `nope`, status line 3 `serving 15 tools, 2 prompts, 2 resource templates`, and the settings file byte-identical (K2). 430 cases at job73 A6. Mutations P1 (port lists the prompts in the other order), P2 (reference guard still refuses `skill_audit`), P3 (port tail drops `ask me before applying it`), P4 (both `SERVED_PROMPTS` stay 1, symmetric: literals only), P5/P6 (one side's line ignores the switch) are each red |
| `statusline` | `--statusline` as a process, over synthetic event logs ([statusline.md](statusline.md)) |
| `store` | save/recall/index: the directory after the call, byte for byte |
| `tokenledger` | AS-1(c)'s transcript ledger: what a session cost, read off the host's own transcripts. The whole `as_json()` document over a FROZEN corpus in git (`tools/ledger/fixtures/token-ledger/`) plus five corpora built into the harness scratch — the walk order as a sequence, the `requestId` dedupe across files, every omission subject, the four argument refusals with the class that raised each, the 2**53 ceiling, and the cost, whose default answer over the shipped price table is the REFUSAL. **It never reads `~/.claude/projects`**: the operator scripts under `tools/ledger/` do, and J46-1 measured two runs of one of them on one day disagreeing because the session in between added a call — a differential over a live corpus is a case that goes red for a reason nobody caused and is then "fixed" by weakening it. Six of its cases are NOT differential: the omission vocabulary, the committed corpus's headline counts and the shipped table's refusal are pinned as typed literals against each runtime separately, because a `requestId` dedupe deleted from BOTH sides leaves two runtimes agreeing perfectly on a wrong number |
| `touch-bound` | The three reviewer fixes of #200 (job70 T200-10) and the re-review's blocker (T200-11). Module calls through `ref/touch_ref.py` (`run_bound`) against `bantamkit.touch` and in-process against `dist/touch/index.js`: `git_on_path` over sixteen PATH fixtures (an executable `git`, one without an execute bit, a directory named `git`, empty entries, an empty PATH, a symlink and a dangling one, the separator of the other OS; simulated Windows with `PATHEXT` `.EXE`, unset, `.COM;.BAT`, a bare `git`, empty `;` entries), `fold_cutoff` over eight byte strings (empty, junk at the midpoint, no object past it, a missing / empty / numeric `ts`, a cut last line, a Thai path that makes bytes and UTF-16 units disagree), and four touch-log beds compared as bytes after an append (under the cap; over it, twice; over it within one second; a `use` append over it). Four hook beds as PROCESSES, the reference then the port: PostToolUse Read and Edit with no git on PATH and with git through a symlinked PATH dir; UserPromptSubmit after an Edit in the default state and with `BANTAMKIT_VIA=on` (touch directory, `[op, seq, path]`, counter, graph directory, the UserPromptSubmit records without `ts`/`ms`, every run's exit/stdout/stderr). Literals per side: the sixteen `git_on_path` answers, the eight cutoffs, the bounded log's `[size <= 1,000,000, folded line first, the new line last]`, 46 lines after a one-second fold, no touch directory and no counter with no git, `[[read,1,src/a.py],[edit,2,src/a.py]]` and `{"seq":2}` with git, no graph directory and no `context` key by default, one graph file and `context` 1 with via on, and the default reply equal to the via-on reply minus its via line. 84 cases at T200-10. Measured 2026-10-17 on rsync copies (`.shiftwork/notes-job70/T200-10.md`): Node recording with no git -> 4; Python recording with no git -> 4; Node ignoring `PATHEXT` -> 2; Python ignoring the execute bit -> 2; BOTH recording with no git -> 2, the literals only; Node building the dead context -> 3; BOTH building it -> 2, the literals only; Python's cap at 2 MB -> 7; BOTH never bounding -> 6, the literals only; Node folding `<` the midpoint second -> 12; Node measuring the midpoint in UTF-16 units -> 2. **T200-11 (the bound holds, no thrash, no fold without the lock):** six `bound_body` byte strings compared as bytes (a folded block alone over half the cap, 6,000 distinct paths; alone over the cap, 12,000; no `ts` on any line; `ts` out of order; an ordinary just-over-cap log; empty) and three beds of their own ops (`held`): the 6,000-path stuck log, one append, then four more past the target; a fresh `<log>.lock` held through an append and a direct `bound`; `bound` on a directory. Literals per side: every body at or under 750,000 bytes; the stuck fold `[under the target, the kept folded rows a suffix of the (ts, path) order, no more dropped than needed, 3843 kept, the new line last]`; the four later appends `[past the target, plain appends]`; the held lock `[raw bytes plus the line, bound false, unchanged after]`; `bound` on a directory false. 117 cases. Measured 2026-10-17 on rsync copies (`.shiftwork/notes-job70/T200-11.md`): Node never ageing -> 7; Python never ageing -> 7; BOTH ageing the newest first -> 2, the literals only; BOTH without the whole-file fold -> 2, the literals only; Node ageing only to the cap -> 8; BOTH -> 6, the literals; Node folding over the target -> 2; Python folding unlocked -> 3; Node -> 3; BOTH -> 2, the literals only; Node letting an error out of `bound` -> 2; BOTH -> 2, the literals only. macOS only |
| `touch-context` | `w_context` in the ranker and the via admission path (#200, Task 5, job70 T200-5). One request to `ref/touch_ref.py` (`run_context`) against `bantamkit.touch.context` and `bantamkit.memory.retrieval`, the same calls in-process against `dist/touch/context.js` and `dist/memory/retrieval.js`: `window` over six row lists (the unit test's, the `seq_now - 20` boundary, uses and folded lines, equal seqs and repeats, malformed seq and path, empty); `context_weights` over six graphs (the unit test's, decay at 0/14/28 days and a future stamp, the 1.0 cap, a fact with a strong and a weak edge whose weak share is 0.5 so strong must win, a bad stamp skipped, a path outside the graph, no paths), compared as sorted `[fact, ctx]` pairs; `via_pick` over eight (weak never admits, exclude, an exclude that empties the first path, a fact no layer holds, ties by name, the first path beats a heavier later one, nothing in the window, nothing weighs); `via_label` over four; `weight_of` at `W_CONTEXT = 0.5` (assigned in-process by the ref, `setContextWeight` on the Node side) for `ctx` in {0, 0.5, 1, 7, -1, NaN} over three types; `via_enabled` over eight `BANTAMKIT_VIA`/`VIA_ON` pairs. The hook: six beds per side (git repo, project store in it) run as `--hook` processes with `BANTAMKIT_VIA=on`: a strong edge in the window, the edge 21 calls back, only a weak edge, two strong facts, a via fact already shown, no git; every run's exit/stdout/stderr and every UserPromptSubmit log record (`ts`/`ms` removed; it carries `context` and `via`). Per side: the via line bytes `[project] [fa] (project) notes about src/a.py [via a.py]`, `via_pick` of the unit fixture `["fb", "src/a.py"]`, the via-line count per bed `[1,0,0,1,1,0]` and the `context` count per bed `[1,null,1,2,1,null]`. 43 cases. Measured 2026-10-17 on rsync copies (`.shiftwork/notes-job70/T200-5.md`): Node letting a weak edge admit -> 5; Python admitting two via facts -> 3; Node ignoring the 20-call window -> 6; Python dropping the `[via ...]` suffix -> 8; BOTH prefixing the label instead -> 4, the literals and per-side counts only (`RECALL_HEADER` stops matching, so both sides inject nothing and every differential stays green); Node not capping `ctx` at 1 -> 1; Python letting a weak share overwrite a strong edge -> 1 |
| `touch-graph` | The touch graph, a derived index with a git half and a touch-log half (#200, Task 4, job70 T200-4). One request to `ref/touch_ref.py` (`run_graph`) against `bantamkit.touch.graph`, the same calls in-process against `dist/touch/graph.js`. Compared as `dumpIndex` strings (the bytes the file holds): `build_strong` over four fixtures (the unit test's; a fact in two layers, symbol edges, a rename, an ambiguous bare name, `__proto__` and a numeric path; no layers; a layer of no refs) and `build_weak` over eleven row lists (the `WEAK_SPAN` boundary above and below the touch, two sessions, a bash turn's `(from, seq]`, a bash turn with no `from`, duplicate timestamps, forty uses cut to `WEAK_TS_MAX`, `__proto__` and numeric keys, malformed rows, several touches of one path). `TouchGraph.load` over one bed per runtime built by the same script (a git repo with one `git mv`, a three-fact project store, a read-only layer naming a fact again): sixteen steps (first load, unchanged load, touch and use lines, a bash-turn line, a load with PATH empty, a commit, a fact write, a corrupt file), each load's data and file bytes with the strong print masked (it folds in `mtime_ns`; the weak print is compared as is), whether the file was rewritten and which print moved. Two shared beds: a graph one runtime wrote is fresh to the other (not rewritten, same data). Per side: `[rewritten, moved]` at seven steps, `build_strong` of the unit test fixture, and `[edge at 20 apart, edge at 21 apart] == [true, false]`. 30 cases. Measured 2026-10-17 on rsync copies (`.shiftwork/notes-job70/T200-4.md`): Node `<` for `<=` on `WEAK_SPAN` -> 8; Python letting a use at `seq == from` into a bash turn -> 6; Node rebuilding the git half on a weak-only change -> 3 (the PATH-empty load answers null); BOTH `WEAK_SPAN = 19` -> 2, the boundary literals only; Node's index print over the shards alone -> 2 (cross-runtime freshness); Node not deduping timestamps -> 2; Python not sorting fact names -> 3 |
| `touch-log` | The touch log, the per-session tool-call counter and the PostToolUse arm (#200, Task 1, job70 T200-1). Nine module scenarios run as op scripts by `ref/touch_ref.py` (`run_log`) against `bantamkit.touch` and in-process against `dist/touch/index.js`: the line bytes of each op (`via`/`from` only when given; Thai, an astral emoji, U+2028 and a lone surrogate in a path), bad lines skipped and counted by `read` and `tail`, `tail` across a first line the seek cut (a log over `TOUCH_TAIL_BYTES`), the counter and its `ledger-<session>.seq.json` bytes (the ledger file-name rule, junk files read as 0), an unwritable touch directory and state directory, `use_names` over a string reply, content blocks, a `content`/`result` dict, a body line spelled like a header (it IS matched) and `\r`/U+2028/U+2029 before a header (never a line start on either side; JavaScript's `m` flag would make it one), the per-path fold in code-point order, `find_repo` (nested, a `.git` file, a missing cwd, no repo) and `relpath` (outside, the toplevel, a symlink out, a missing file), and Retention folding a touch log then settling. Three hook beds as PROCESSES at one path, the reference first and the port after a rebuild: a git repo driven by Edit, Bash, Read, Write outside the repo, NotebookEdit, a two-header `memory_recall` and a `memory_save` (touch-log bytes with `ts` masked, the counter bytes, exit/stdout/stderr, the status lines); no repo (no touch directory, no counter); an unwritable touch path (one `touch: miss`, counted by the status). Literals per side: the first touch line, the `[op, seq]` list `[[edit,1],[read,3],[edit,5],[use,6],[use,6],[use,7]]`, the counter after seven calls, no directory and no counter outside a repo, `[false, false]` for the unwritable appends, and the three status blocks. 122 cases. Measured 2026-10-17 on rsync copies (`.shiftwork/notes-job70/T200-1.md`): Node recording Bash as a write → 4; Python storing the absolute path → 4; Node not counting Bash in `seq` → 4; BOTH dropping `seq` from the touch line → 4, the per-side literals only; Node reading headers with the `m` flag → 1; Node ordering folded paths by UTF-16 unit → 1. macOS only |
| `touch-refs` | Path references in fact text and their resolution through git (#200, E4, Task 2, job70 T200-2). One request to `ref/touch_ref.py` (`run_refs`) against `bantamkit.touch`, the same calls in-process against `dist/touch/refs.js` and `dist/touch/repo.js`. Compared: `extract_refs` over a 41-row tagged corpus (plain path, `path:line`, `path:a-b`, `path#symbol`, absolute inside and outside the toplevel, a missing path, an ambiguous bare name, URLs holding paths in the path, the query and the userinfo, other schemes, `0.37.0`, Thai spaced and Thai DIRECTLY before a path, CRLF, a trailing `/`, `~/` paths, a symbol with dots, abbreviations, a sentence full stop, bare names with no extension, repeats, `./`, quotes, an astral emoji, dotfiles, flags, a Windows path as text, extension lengths, `:abc`, `#123`, `a//b.py`, the empty text); `fact_refs` over four description/keywords/body triples; `resolve_ref` over every raw reference the corpus yields plus fifteen picked ones, against a nine-file fixture set (three `store.ts`, a Thai and an astral path, `__proto__/x.py`) and a renames map holding a chain and a cycle (nothing after 32 hops); `FileSet.matches` over nine probes; `shortest_suffix` and its round trip for every fixture file; and over ONE fixture git repo the harness builds (`old.py` -> `new.py` -> `src/new.py` by two `git mv`, then `dup.py` added and moved twice so the newest rename must win): `ls_files`, `renames` in git's order, `resolve_ref` and `head_print`. Not differential, per side: `matches(shortest_suffix(f)) == [f]` for every file, `extract_refs` of the unit test's kinds text, `shortest_suffix("runtime-ts/src/memory/store.ts") == "memory/store.ts"`, and the fixture repo's `resolve_ref("old.py") == src/new.py`. Measured 2026-10-17 on rsync copies (of 126): Node not blanking URLs -> 2 (the query/userinfo row and other schemes; a plain `https://h/a/b.md` yields nothing even unblanked, because every component follows a `/` the lookbehind refuses); Python spelling the lookbehind `\\w` -> 2 (Thai directly before a path); Node preferring the SHALLOWEST deeper match -> 2; Python's renames keeping the OLDEST rename of a path -> 2; BOTH sides keeping `:line` in the raw reference -> 2, the literals only |
| `touch-summary` | The B summaries (#200, E1-B, Task 6, job70 T200-6): one line at SessionStart about the previous session in this repo, and after a compaction this session's edits, at most 600 BYTES. One request to `ref/touch_ref.py` (`run_summary`) against `bantamkit.touch.summary`, the same calls in-process against `dist/touch/index.js`, `display` a fixed table on both sides: `age_text` at every boundary (0, 59, 60, 3599, 3600, 172799, 172800 s, a negative age, 3 d); `previous_session` over eight row lists (the unit test's, a folded row, a tie on the latest `ts` between U+FFFF, U+1F600 and `b` — code point says U+FFFF, UTF-16 would say U+1F600 — a plain tie, only the current session, use rows / a non-date `ts` / a non-string session, the latest touch deciding over an earlier edit, empty); `last_session_line` over twelve (the unit test's, reads only, zero edits with five commits, seven long Thai subjects, two Thai/astral fixtures cut near the cap, uncapped lines of exactly 600 and 601 bytes ending in Thai and of 600 and 602 ending in an emoji, a non-date `ts`, non-integer seqs); `compact_line` over six (twelve edits, edits only, reads only, another session, a repeat, ten long Thai names); `uncommitted_count` over six `-z` statuses (a rename whose source has a space third, a copy, Thai); `shift_ts` over three (midnight, year end, a leap day). Three SessionStart hook beds as PROCESSES at one path under `TZ=Asia/Bangkok`, the reference first and the port after a rebuild, over a git repo with two commits at fixed `GIT_COMMITTER_DATE`s, one before the window: `startup` and `compact` over a seeded touch log, `resume` with none; exit/stdout/stderr compared with the age masked. Literals per side: the unit test's line bytes, the exactly-600-byte line kept whole (600), the 601-byte one cut to 598, the two Thai/astral lines cut to within a character of 600, the code-point tie, the hook's startup line (`edited 3 files — b.txt, 😀.txt, src/store.ts; commits: J68-3 keywords (#199); uncommitted: 2 files`), the compact line, no line without a touch log. 63 cases. Measured 2026-10-17 on rsync copies (`.shiftwork/notes-job70/T200-6.md`): Node capping characters, not bytes -> 8; Python listing reads -> 9; Node listing reads after compact -> 4; BOTH capping at 601 -> 4, the literals only; Node breaking a tie by UTF-16 -> 2; Python counting a rename's source -> 1; Node handing git the window without the `Z` (read as local time) -> 2; Python appending the line after the toolbox part -> 2. macOS only |
| `touch-turn` | Writes made by Bash, captured once per turn from two `git status --porcelain=v1 -z -uall` snapshots (#200, E5, Task 3, job70 T200-3). Four module scenarios run as op scripts by `ref/touch_ref.py` (`run_turn`) against `bantamkit.touch` and in-process against `dist/touch/index.js`, each over its own repo built the same way (a commit, then one file dirtied before the turn), every `mtime_ns` masked to `<ns>`: the unit test's new / modified / already-dirty-and-touched-again paths; every status form at once (staged, unstaged, untracked in a new directory, a `git mv` rename keyed on its destination, a deletion as `"-"`/`-1`, a Thai and astral path) with `changed` both ways and against itself, the `ledger-<session>.turn.json` bytes (sorted keys, the ledger file-name rule) and `load_turn`; a revert to clean; and git failing (a `.git` git refuses), no repo, a path named `__proto__`, five junk turn files and an integral float `seq`. Three hook beds as PROCESSES at one path, the reference first and the port after a rebuild: a Bash call, a short UserPromptSubmit (the skip still opens the turn), an Edit, then writes made outside any tool, Stop, a second Stop under `stop_hook_active`, then a `/clear` turn with a Bash write; no repo; a Stop with no open turn. Compared after each Stop: the touch-log bytes (`ts` masked), the turn file (`mtime_ns` masked), and every run's exit/stdout/stderr. Literals per side: the changed list `["a.txt","dirty.txt","new/n.txt"]`, the one bash-turn line (`b.txt`, `from` 1, `seq` 2; the Edit explains `a.txt`), the log unchanged by the second Stop, the slash-command turn's `d.txt` line, nothing written outside a repo, no touch log at a Stop with no turn. 74 cases. Measured 2026-10-17 on rsync copies (`.shiftwork/notes-job70/T200-3.md`): Node keying a rename on its source -> 5; Python dropping the Edit filter -> 6; Node not re-saving the snapshot at Stop -> 4 (the turn file; the touch log holds because the first Stop's own line explains the path); BOTH ignoring the stat of an already-dirty path -> 2, the literals only; BOTH opening the turn after the short-prompt skip -> 4, the literals only. macOS only |
| `updatecheck` | the stale-install signal (J57): one record on disk, five states, two registry keys. 42 arms — 38 record shapes plus four PATH shapes (nothing there, a path under a regular file, a directory, a mode nobody may read) — each written ONCE and handed to both runtimes as the same absolute path, then answered by each under `pypi` AND under `npm`: the loader's outcome, the state, the parsed record and the whole sentence. Plus the five sentences byte for byte, the five rendered lines against hand-written literals, every arm's state against a hand-written table per side, that not one shape RAISES on either side, that a read creates NOTHING (the fixture directory afterwards, and a home a default-path read left as empty as it found it), and six writer arms over `selfupdate.record_update` / `recordUpdate` — what it wrote, what it refused to create, the temp file it did not leave behind, and the other registry's entry it left exactly as found. Three `ruling:` cases carry the one deliberate difference; `HOME` and `USERPROFILE` are redirected on both sides for every arm. Nothing is held out of the tables. **The UTF-8 BOM the first cut of this suite found is closed (J57-5b)**: a well-formed record carrying a BOM — the three bytes `EF BB BF`, whoever wrote them (amended 2026-09-21, J62-16: this used to read "what Windows PowerShell writes by default"; PowerShell 7.4.2 measured in `mcr.microsoft.com/powershell:latest` writes NO BOM by default from any of `Set-Content`, `Out-File`, `>` or `Add-Content`, and Windows PowerShell 5.1 is unmeasured for want of a Windows kernel) — was `unreadable` on the reference (`json.loads` refuses a BOM) and a live `available` on the port (`TextDecoder` strips it), and the fix was in the RUNTIME, toward both sides ACCEPTING it: the reference reads with `utf-8-sig`, the port is unchanged. It is deliberately NOT a ruling — nobody chose the difference, and there is none left. Four arms hold it: the same record at three running versions (`available` / `current` / `ahead`, identical to the same record without a BOM) and `unreadable/bom-not-json`, the control that says stripping a BOM does not make broken bytes readable. **AMENDED 2026-09-21 (job62, J62-13): 50 arms now, over 38 record shapes plus the same four PATH shapes, and the six writer arms pin one more thing.** The record grew a SECOND kind of stamp: an entry's own `checked_at` (when that registry answered) beside the record's (when a writer refreshed the whole record), because two of the three writers fill ONE key and both stamped the record — so the runtime reading the other key dated its stale number by a check that never asked its registry. Eight new arms: the entry stamp winning under both keys, the partial-probe record where the DATE is key-sensitive although the state is not, a record with no record-level stamp at all (what `--update` leaves on a fresh machine, and `unreadable` before this), and three garbage entry stamps that stay `unreadable` although the record's own stamp is good — one selection, then one rule. The writer literals pin that `--update` stamps its own entry and never the record's, and that a merge leaves the record's stamp where it was. Every one was seen red first: the defect restored on ONE side reddens the differential and the literals; restored on BOTH it reddens only the literals, 12 of them, which is the symmetric-regression shape this repo has been bitten by three times; and a mutation that drops the record-level FALLBACK reddens the arms that pin it, so no line here is green in only one direction. |
| `validate` | the validator, in six sections: (1) `schema_error`, every sentence a schema failure can produce, with the dialects and the one resource (job65) and `job.roles` as a literal on each side; (2) the CPython decoder's text; (3) `extract_json`'s arms; (4) `repr(float)`; (5) the contract asset, key for key; (6) the asset loaders take a BARE name (#145): `loadTool`/`loadSchema`/`loadSkill` over nine names each plus `../schemas/x` for `loadTool` (28 names), compared side to side and pinned as a literal `AssetNotFound: <kind> asset name is not a bare name: <name>` on each side |
| `version` | one version, two registry spellings (job68 J68-12, user ruling 2026-10-15): both servers as processes over three FIXTURE trees built per run — a copy of `runtime-py/src/bantamkit` declaring `0.36.0` / `0.37.0b1` / `0.37.0rc2` and a copy of `runtime-ts/dist` beside a `package.json` declaring `0.36.0` / `0.37.0-beta.1` / `0.37.0-rc.2`, so no manifest is bumped — driven in lock-step through `initialize` and `build_identity`. A stable version is byte-identical on both surfaces; a prerelease DIFFERS (four `ruling:` cases, porting.md "a prerelease version's spelling"), and beside each ruling a non-ruled case compares the reference's answer mapped through `pep440ToSemver` with the port's. Each side's spelling is also pinned as a per-side literal, and `pep440ToSemver` is compared with `publish.sh`'s own `map_pep440_to_semver`, run by bash. `wire`'s `build_identity: version agrees` and `cli`'s four `…/handshake` frame comparisons import the same mapping and apply it to the reference's answer |
| `wire` | the MCP surface: fifteen tools, one prompt, two templates, and the frames themselves — including a `retired` session over `repo_map` and `bantamkit_read`, refused by name on both sides with the event log on, now that job50 I5 (2026-09-12) retired them from the roster and removed the six sessions that used to exercise the reader over the wire (`read`, `read-ruled`, `read-edges`, `read-round2`, `read-round3`, `read-cache`); the reader's own parity stays gated at the library layer, `tools/conformance/suites/docread.mjs` |
| `workplan` | the dependency planner: `plan()` over 21 real graphs — `{id, depends_on}` extracted ONCE from `plan.units` of every checkpoint in `.shiftwork/`, 228 units, and written into the suite as LITERAL DATA — plus a synthetic corpus of the edges (empty input, a single node, priority ties, an order in which insertion-order tie-breaking is observable), the three graph refusals and the node-shape refusals of #127 (`nodes[<i>] must be an object`, `.id must be a string`, `.depends_on must be a list of strings`, `.priority must be an integer`, and a shape refusal beating a duplicate id), each compared both as the whole answer and as the bare sentence; `shiftwork_plan` over the tracked template copied into scratch and over the four refusals a checkpoint can produce before the graph is reached, as `json.dumps` TEXT; and the `work_plan` TOOL over stdio on both servers, which is the only place a node with no `depends_on` can be compared at all — the reference defaults it in `workplan.plan` and the port in `planNodes`, so the core cannot carry that case and the schema's `required` keeps it out of `shiftwork_plan`. 86 of its cases are NOT differential: each graph's batch WIDTHS, each graph's FIRST BATCH and the corpus's own headline (21 graphs, 228 units, 126 batches) are pinned as typed numbers and typed id lists against each runtime separately, and they are teeth against two different mutations — measured 2026-09-19, reversing the order inside a batch reddens 35 cases and NO width case, while emitting one node per batch on BOTH sides at once reddens 52 literal cases and NOT ONE differential one. There is no `ruling:` case here, deliberately: nothing in the planner is supposed to differ |

`cli`, `mcpreport`, `memorycli` and `statusline` are the odd ones out and deliberately so:
every other suite compares two library functions, and that comparison cannot see which stream
a message lands on or what the process exits with. Those four spawn both CLIs and diff the
three things only a process has. `mcpreport` and `statusline` reuse `ref/cli_ref.py` rather
than adding a second reference script — it already is "spawn the CLI with this argv and hand
back both streams", which is their question with a different argv. `memorycli` carries its
own `ref/memorycli_ref.py` because it compares a fourth thing those three do not: the store
on disk after every step.

**Amendment, 2026-09-11 (J46-28): `cli` now carries a second script, and the sentence above
is the reason to explain why.** `ref/cli_tty_ref.py` is not a second "spawn the CLI with this
argv" — it is a TERMINAL. Both runtimes discriminate a person from a host on `stdin.isatty()`
/ `process.stdin.isTTY`, so comparing their answers needs a real pty on fd 0 of each, and Node
has no pty in its standard library. The alternative was two different fakes, one per runtime,
and a differential over two fakes measures the fakes. So this one script allocates a single
`pty.openpty()` and runs **either** side over it — the only script under `ref/` that runs the
port as well as the reference, and the reason it is allowed to is that what it contributes is
the harness's terminal, not either runtime's behaviour. Where the platform has no pty
(Windows) it answers `{"unsupported": …}` and the suite emits a note naming what went
unmeasured, rather than a case nobody earned.

Suites are discovered by **directory listing**, not by a registry someone has to remember to
edit. Drop a module in `suites/` and it runs.

## The four kinds of case

Each case is `{ name, kind, expected, actual, ruling? }` where `expected` is Python's answer
and `actual` is Node's.

- **`bytes`** — compared as buffers. The strongest claim; satisfies `--require-byte-identical`.
- **`string`** — compared as text.
- **`json`** — compared structurally.
- **`ruling:`** — a case that is **supposed** to differ. It carries the reason, it is
  *required* to differ, and **a ruling whose case has quietly started matching also fails**,
  with `STALE RULING: the case no longer differs`.

### A ruling pins the wording, not the outcome

This distinction cost a defect once and is the harness's sharpest edge, so read it twice.

A `ruling:` case fails when the two sides **match**. That means a ruling can only ever prove
"these two sentences still differ" — it cannot prove "both sides still refuse". If the Node
side silently went back to *answering* where Python refuses, all 50 `checkSchema` rulings
would have stayed green, because an answer and a refusal are also different strings.

So wherever the *refusal itself* is the property, it gets **its own non-ruled case comparing
the refusal bit** alongside the ruling that compares the words. Both exist today for
`checkSchema`, for the constructor-less YAML tags, and for the reader's pdf/doc/rtf rulings
in `docread` and `wire` — where each ruled fixture also carries a literal saying which side
is *required* to refuse it, so a port that quietly started reading a PDF fails as loudly as
a reference that stopped. The utf-7 ruling in `docread` is the inverse shape: both sides
*read* the file and the row differs by one codepoint, so its companion pins that neither
side refuses and that everything around the ruled row (kind, part count, row count,
omissions) still matches.

### Rulings have to be shown to have teeth

The review unit found **3 of 19** rulings that could never have failed: one compared a JS
`str.replace` against itself (differs iff the text has a newline, i.e. always), and two
compared `'(valid)'` against `'null'` while *both* runtimes said valid, because their
instances were arrays and `minimum`/`pattern` never fired.

If you add or touch a ruling, demonstrate it: make the case match and confirm the run goes
red with `STALE RULING`.

## Finding the reference interpreter

In order:

1. `--python <path>` or `BANTAMKIT_CONFORMANCE_PYTHON`
2. `<repo>/.venv/bin/python`, `<repo>/.venv/Scripts/python.exe`
3. the same two under the **main** worktree, resolved via `git rev-parse --git-common-dir`

Step 3 matters because the harness is usually run from a worktree, where `.venv` is a symlink
that may not resolve. CI has no `.venv` at all, so the workflow writes
`BANTAMKIT_CONFORMANCE_PYTHON=$(python -c 'import sys; print(sys.executable)')` into
`GITHUB_ENV` before the step.

### The reference at the 3.11 floor

`runtime-py/pyproject.toml` declares `requires-python = ">=3.11"`, and no gate this repository
owns runs the reference there: the venv is 3.12, CI's conformance job pins 3.12, and Actions is
off. So until 2026-09-21 (roadmap row (ddd)) a contributor on 3.11 had `--suite store` exit 2
and `--all` stop at `store`: `ref/store_ref.py`'s `winpaths` op calls `ntpath.splitroot`, which
CPython added in 3.12 (`docker run --rm python:3.11-slim python -c
"import ntpath;print(hasattr(ntpath,'splitroot'))"` prints `False`). The floor stays at 3.11 and
the abort is gone: the one case that needs 3.12, `ntpath.splitroot and PureWindowsPath parsing,
on every platform`, is asked ONLY of a 3.12+ reference. `suites/store.mjs` asks `store_ref.py`
a `version` op first (`sys.version_info`; one extra reference child per run, nothing added to
`ctx`) and below 3.12 WITHHOLDS the case — it is sent to neither side — and prints a `note:`
that names it, counts it (1) and gives the reason: the port was written to 3.12's
`PureWindowsPath`, which 3.12 rewrote over `os.path.splitroot`, and 3.11's is a different
algorithm that nobody chose. Measured (J63-1's probe over the 26 suite raws plus 18 edges):
3.11 answers `absolute`, `parsed`, `parents`, `str` and `name` differently for `//a`, `///a`,
`////a/b`, `//a/`, `//`, `\\`, `\\\`, `//?`, `\\.\PhysicalDrive0`, `//?/unc/srv/share/x` and
`é:/x`, and joins `PureWindowsPath('C:/a', 'C:b')` to `C:\a\b` against 3.12's `C:b`, while
`ntpath.join`, `ntpath.split`, `ntpath.isabs`, `.suffix` and `splitroot` itself agree on every
row. That is why it is a withheld case and not a `ruling:` — a ruling is for a difference
somebody chose — and not a `skip` inside a helper: the note is the shape this harness already
uses for a case the platform cannot measure (`instructions.mjs` on win32, `shiftwork.mjs` as
uid 0). At 3.12+ nothing is withheld and the case list is what it was.

J63-1 first closed the abort the other way: a verbatim port of 3.12's `splitroot` bound in the
reference where the stdlib had none, and a `node --test` pinning the port against 44 triples on
both interpreters. With the case withheld below 3.12 and the native function present at 3.12+,
that port was code no configuration executed, so J63-1b removed it and its test. Both, and the
44-row proof that `splitroot` itself is identical across the two interpreters, stay reachable in
git at `71cd230` (`git show 71cd230:tools/conformance/ref/store_ref.py`,
`git show 71cd230:tools/conformance/splitroot-fallback.test.mjs`). The call site is the plain
`ntpath.splitroot(r)` again, under a comment naming where the 3.12 requirement is decided.

To run the reference AT the floor there is no host gate; the one that counts is Docker, and
the whole recipe is:

```
printf 'FROM python:3.11-slim\nRUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nodejs npm git >/dev/null && rm -rf /var/lib/apt/lists/*\nRUN pip install -q --root-user-action=ignore pyyaml jsonschema httpx\n' | docker build -q -t bk-py311-node:j63-1 -
docker run --rm -v "$PWD":/src -w /src -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/src/runtime-py/src \
  -e BANTAMKIT_CONFORMANCE_PYTHON=/usr/local/bin/python bk-py311-node:j63-1 \
  sh -c 'git config --global --add safe.directory /src; node tools/conformance/run.mjs --suite store'
```

Measured 2026-09-21 with the reference on 3.11.16 against this tree: `--suite store` prints
`PASS` with `0 failures`, one case fewer than the host's run of the same tree, and the note
`1 case withheld below Python 3.12 (the reference is 3.11.16): ...`. Seen red before it was
trusted (J63-1b note): with the floor test mutated so it never withholds, the 3.11 reference is
asked the op and aborts on `AttributeError: module 'ntpath' has no attribute 'splitroot'` (exit
2, no cases); on a copy of the tree with `71cd230`'s port put back, the same mutation reddens
exactly that one case with its old first-difference line (`first difference at byte 25`,
`absolute[2]` for `////a/b`; 1 failure). Mutated the other way, so it withholds at every
version, the HOST run stays green one case short with a note that reads `the reference is
3.12.13`: no gate pins the case count (counts co-move with the tree), so until J63-5 that
direction was caught only by reading the note. J63-5 added one per-side literal beside the
arm — `winpaths is armed exactly when the reference is 3.12+, against a literal`, `{armed}`
against the version the reference reported — and measured it: under that `< 99` mutation the
host goes `1 failures` (`{"armed":true}` expected, `{"armed":false}` got); unmutated, the host
runs 256 cases and the 3.11 image 255 with the note, both at 0 failures.

`--all` no longer stops at `store`: measured 2026-09-21 (J63-1) as root in that image, before
the withhold, all 23 suites ran — 8841 cases, 12 failures, of which one was the case now
withheld; the other eleven (an argparse wording that 3.11 quotes and 3.12 does not, the chmod
arms that root cannot be denied, a `python3.11` interpreter name, a `~root` ruling that goes
stale when root is the current user) are named in the J63-1 note and are not this row's.

## A reference child that stops answering

Each reference script is bounded at **600 s**, killed with `SIGKILL`, and reported as its
own failure naming the script, the interpreter, and whether the child had written anything:

```
conformance: reference script did not finish within 600s and was killed
  script : .../tools/conformance/ref/store_ref.py
  python : .../.venv/bin/python
  stdout : nothing at all
  stderr : nothing at all
```

The bound is measured, not chosen. Instrumenting `runPython` over a full `--all` run timed
355 calls; the slowest was `store_ref.py` at **50,139 ms** and everything else finished under
1.5 s. 600 s is twelve times the slowest honest call, which leaves an order of magnitude for a
Windows runner and still lands far short of anything a working call reaches.

It exists because `spawnSync` waits forever. On 2026-09-05 a full run sat for **1h09m** with a
`shiftwork_ref.py` child stuck and produced no output at all — no case, no note, no error — and
ended only because it was killed by hand.

`.github/workflows/ci.yml` also caps each job at 30 minutes, and the ordering is deliberate:
the job cap kills the runner and reports "took too long", which names nothing, so this bound is
set to fire first and say which script it was.

**Demonstrating the arm** — `BANTAMKIT_CONFORMANCE_REF_TIMEOUT_MS` overrides the bound so the
failure can be watched rather than asserted:

```
BANTAMKIT_CONFORMANCE_REF_TIMEOUT_MS=1 node tools/conformance/run.mjs --suite validate
```

exits 2 and names `validate_ref.py`. Under an override the message says so and prints the
default instead of claiming the twelve-times-headroom sentence, which would be false. The
override is a demonstration seam, not a knob for slow machines: if a real call needs more than
ten minutes, the call is the thing to look at.

## Reading the output

```
✔ store: 185 cases (97 json, 88 bytes), 0 differed
  note: [store] live index: 13472 bytes on disk, 13472 bytes rebuilt, 65 lines, 10528 bytes of headroom under the 24000 default
  ...
PASS: 6132 cases, 1500 byte-identical, 3267 exact-string, 1365 structural, 123 ruled-different, 0 failures
```

(The totals are a sample from one run and move with the suites: measured 4841 at `2c208f4`,
4874 once the `memory-compact` wire session landed — 33 cases — and 4878 after its review
hardened four of them, all on 2026-08-27; 4880 at `ce46fc3`, then 5512 on 2026-08-28 when
the `docread` suite landed — 575 cases, 8 ruled — and the `wire` suite grew from 232 to 289
with the `bantamkit_read` sessions, 7 of them ruled; 5600 at c8a62aa with 2 failures — the `badcd.xlsx` constructor-name artefact in the docread suite's `errorOf`, fixed in F4 — and 5760 after F4 on 2026-08-28: `docread` 633 -> 774 (9 ruled, the utf-7 ruling added), `wire` 289 -> 308 with the `read-edges` session; 116 ruled-different, 0 failures; 5855 at 905965a (job43 G2) with 6 failures — bzip2.docx and lzma.docx pending their ruling — and 5954 after G3 on 2026-08-29: `docread` 869 -> 935 (12 ruled: bzip2, lzma and RFC 2231 added, the seven checked-in fixtures and `a\x00b` read), `wire` 308 -> 341 with the `read-round2` session (20 ruled); 122 ruled-different, 0 failures; and 6132 after round 3's H3 on 2026-08-29 — at 643e323 the `docread` suite did not START, a name-collision throw over the checked-in `corrupt-deflate.docx`, lifted so the checked-in bytes win — `docread` 935 -> 990 (13 ruled: the `<!ATTLIST>` ruling added with its both-read companions; six round-3 checked-in fixtures, three `charset-<label>.eml` parts and the `<xmp>` charref unruled), `wire` 341 -> 371 with the `read-round3` session (unruled, 20 ruled unchanged), and the new `charsets` suite, 93 cases (`node tools/conformance/run.mjs --all`: 6132 cases, 123 ruled-different, 0 failures).

**AMENDED 2026-09-04, review round 4 (M6 / I3-F4): the `6132 cases, 123 ruled-different,
0 failures` above did NOT reproduce, and one of the two reasons was a defect.** Measured at
`952586e`, the same command answered `6199 cases, 125 ruled-different, 0 failures`. The CASE
total legitimately co-moves with the operator's live memory store — that is a standing fact of
the corpus-backed suites, and CI, which has no store, says so in its own notes. The RULED count
must not, and it moved because two more rulings had landed since; a ruled count is a decision
total, not a corpus function, and the record read as if the whole triple were rerunnable.
Worse, at that same commit the command FAILED on a clean checkout: `runtime-ts/assets/` is
gitignored and only `prepack` creates it, so the `--assets-root` ruling went stale and the gate
went red on any tree that had not published a tarball. That is fixed in this round — the `cli`
suite vendors the pack itself and asserts it as a precondition — so the number below is the
first one in this paragraph that a fresh clone can reproduce.

**Measured at `1cf8df2`, on this branch, by running it:**

```
PASS: 6280 cases, 1535 byte-identical, 3271 exact-string, 1474 structural,
      127 ruled-different, 0 failures
```

Against `6199 / 125` at `952586e`: **+81 cases and +2 rulings**, and every one of them is
named. The two new rulings are `hz.eml` and `iso2022kr.eml` (`docs/porting.md`, "`hz` and
`iso-2022-kr` on Node") — the divergence H1 uncovered, priced this round. The cases: `codec`
and `store` +2 for I3b's corpus-integrity gates; `cli` +1 for the pack precondition; `docread`
999 -> 1062 (the fixture-shadow declaration; `max-column.xlsx`, `xfd-column.xlsx`,
`iso2022jp.eml`, `hz.eml`, `iso2022kr.eml` and three `charset-raises-*.eml`, plus the two
column-ceiling literals — and twelve cases that appeared because six `charset-*.eml` fixtures
stopped being refused, see the note below); `memorycli` 210 -> 212 for the two eviction-order
literals; `charsets` 93 -> 88, which is a DROP, because H1 (`666f14f`) removed seven byte
tables that were never byte codecs and this round added two key-set cases (86 + 2); `wire`
371 unchanged, one case removed and one added.

**AMENDED 2026-09-05, twice, on the `feat/tool-usage-ledger` branch.** The `archive <name>`
subcommand took the run to `6294 / 130` — `memorycli` 212 -> 250 and three new rulings, all
of them the `archive -h` help form joining the four that were already ruled. Review round 5
of that subcommand then took it to:

```
PASS: 6316 cases, 1560 byte-identical, 3272 exact-string, 1484 structural,
      130 ruled-different, 0 failures
```

**+22 cases, no new ruling**, every one of them in `memorycli` (250 -> 272) and every one
added because a mutation showed the existing case could not see the thing it was named for:
two `unreadable-*-archive` rows reaching the two new "could not be stat'd" sentences that
NOTHING referenced (both were corrupted in the Node build and `--all` stayed at 0 failures);
two typed-literal `content-of-…` cases on the already-archived refusal, because
`archived-names: ['alpha']` is what the refusal AND the overwrite both leave; one
`archived-at-step-2` literal, because a round trip's CLOSING state is also what a jointly
dead archive/restore pair leaves; and two name-validation scenarios. The mutation counts are
in the commit messages.

**A number in this paragraph that was measuring nothing:** the three `charset-<label>.eml`
cases counted in the `6132` line above sent their bytes `8bit`, which made the file's HEAD
undecodable, so the container sniffed `unknown` and BOTH runtimes refused before any codec was
consulted. They were green and they pinned a refusal. Corrected to `quoted-printable` this
round; the cases they now generate are real.)

**AMENDED 2026-09-06 — job44 (`fix/job44-register-drain`), the register-drain job.** Measured
at the tree that bumps the version to 0.29.2, on Node v25.2.1 and `.venv` CPython 3.12.13,
with the runner given a message of its own — `pytest` and `run.mjs --all` in one message hang
each other, measured at over an hour with a stuck reference child, and about two minutes apart:

<!-- provenance: value=6662 cases, 149 ruled-different, 0 failures; commit=f484c70 plus this commit's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 6662 cases, 1614 byte-identical, 3397 exact-string, 1651 structural,
      149 ruled-different, 0 failures
```

Per suite, at that tree: `validate` 3015, `docread` 1107, `shiftwork` 596, `codec` 510,
`wire` 417, `memorycli` 310, `store` 186, `charsets` 148, `cli` 106, `recall-strings` 96,
`skillaudit` 94, `statusline` 52, `mcpreport` 25 — every one at 0 differed.

**AMENDED 2026-09-06 — job45 (`feat/job45-dream-precision-repomap`), roadmap row 5.** The
`dream` suite landed: 78 cases over 18 scenarios and a 16-term day-arithmetic boundary.

<!-- provenance: value=6760 cases, 149 ruled-different, 0 failures; commit=3f9bb55 plus job45's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 6760 cases, 1654 byte-identical, 3397 exact-string, 1709 structural,
      149 ruled-different, 0 failures
```

Per suite, at that tree: `validate` 3015, `docread` 1169, `shiftwork` 596, `codec` 468,
`wire` 417, `memorycli` 310, `store` 186, `charsets` 148, `cli` 106, `recall-strings` 96,
`skillaudit` 94, `dream` **78**, `statusline` 52, `mcpreport` 25 — every one at 0 differed.

**THE TOTAL WENT DOWN BEFORE IT WENT UP, AND THE CAUSE IS THE OPERATOR'S STORE, NOT THIS
JOB.** Job45's own baseline run, before a line of the new suite existed, measured **6682**
against the 6724 job45's plan recorded — a fall of 42 with the suite code unchanged.
`codec.mjs` generates exactly THREE cases per corpus fact (emit, python-parses-node,
node-parses-python) over 65 adversarial facts plus the live project store, so 42 is 14 facts:
`codec` 510 -> 468, and 510 is precisely the number the job44 provenance line above records
when that store held 101 facts. It holds 87 now. `CORPUS_FLOOR` is 32, deliberately far below
any real store, so a shrink of that size passes silently — the floor exists to catch a corpus
that resolved to nothing, not to pin a number that moves whenever the operator saves or
archives a fact. Quote a total against the tree AND the store it was taken on.

Non-vacuity for the new suite is measured rather than asserted: **17 mutants applied and 17
killed**, each restored and sha256-verified. Fifteen were one-sided and reddened between 1 and
21 differential cases apiece. **The other two were symmetric** — the mtime tie-break flipped on
both runtimes at once, and the calendar edge moved by one day on both at once — and each
reddened exactly 2 cases, both of them literals, and not one differential case. That is the
shape `differential-is-blind-to-symmetric-regression` names, caught here by design.

**AMENDED 2026-09-07 — job45 (`feat/job45-dream-precision-repomap`), roadmap row 6.** The
`recall-gate` suite landed: 37 cases over 11 store scenarios, 3 layered scenarios, the
constant, and four literal pairs.

<!-- provenance: value=6797 cases, 149 ruled-different, 0 failures; commit=3f9bb55 plus job45's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 6797 cases, 1667 byte-identical, 3406 exact-string, 1724 structural,
      149 ruled-different, 0 failures
```

Per suite, at that tree: `validate` 3015, `docread` 1169, `shiftwork` 596, `codec` 468,
`wire` 417, `memorycli` 310, `store` 186, `charsets` 148, `cli` 106, `recall-strings` 96,
`skillaudit` 94, `dream` 78, `statusline` 52, `recall-gate` **37**, `mcpreport` 25 — every
one at 0 differed.

**THE WHOLE DELTA IS THE NEW SUITE, and that is checked rather than assumed.** 6760 -> 6797
is +37, and diffing the per-suite lines of the two runs — one taken before a line of the new
suite existed, one after — shows every other suite at a byte-identical count. The operator's
store held 87 facts for both runs, so `codec`'s 3-cases-per-fact did not move this time. It
is still the reason a total must be quoted against the tree AND the store.

Non-vacuity: **22 mutants applied on a `cp -R` copy, 21 killed and 1 equivalent by design.**
A control run on the unmutated copy is green, so a red result is the mutation. Eighteen were
one-sided — twelve against the reference, six against the port — and reddened between 1 and
17 differential cases apiece; the survivor is the gate
moved below the top-`k` slice, which both runtimes' implementers independently proved
equivalent (the survivors are always a prefix of the score-sorted list), so this suite
deliberately writes NO case that could distinguish the placement. Two of the one-sided
mutants are worth naming because they each pin ONE case: the range check MOVED to after the
facts are read — not deleted, so every readable store still refuses correctly — is seen by
exactly one case, the unreadable-store ordering; and a floor that ignores the ratio entirely
(`floor = max(...)`) is the only mutation an explicit `0.0` can see, which is what a no-op
default means.

**Four more symmetric mutants, and each reddened only literals.** The constant flipped on
both runtimes at once, the sentence respelled on both, `>=` weakened to `>` on both, and the
floor made absolute on both: **zero differential cases red** in every one of the four, and 2,
2, 4 and 2 literal cases respectively. That is `differential-is-blind-to-symmetric-regression`
measured a second time, on a second suite.

**Two vacuous cases were found and dealt with, both tree comparisons that survived all 22
mutants.** One was repaired: a multi-ratio scenario whose call list began at `0.0` stamped
every fact on the first call, so its end state was saturated and no later call could change
it — the list is now `1.0 -> 0.6 -> 0.5`, none of which admits the weakest fact, and the tree
reddens under three mutants. The other was DELETED: the unreadable-store scenario cannot
write a byte under any mutation of this rule, so its tree case could not fail. The claim it
was meant to carry — a refused ratio touches no disk — is made non-vacuously by the six-ratio
scenario over a readable store, whose tree reddens when the range check is deleted and `-0.1`
stamps all four facts.

**What job44 added, as its own units measured it** (the totals between the `6316` above and
this one are recorded where they were made — row 11 of `docs/roadmap-toolbox.md` for
`skill_audit`, and `docs/eval-data/` for the units here — rather than re-derived as
arithmetic in this paragraph):

* **`charsets` 88 -> 148, 0 -> 12 rulings** (unit U18). The CJK residual is pinned against a
  recipe checked in at `tools/conformance/ref/cjk_ref.py` instead of a script nobody kept.
  Each codec gets one ruling and four NON-ruled literal companions — match count, a digest of
  CPython's own answers, a digest of ICU's own answers, and the first disagreeing input with
  both answers. **The justification for the companions is a probe, not taste:** appending the
  same string to BOTH sides for all ten codecs left every ruling green and every match count
  green while 30 anchor cases went red, so a ruling-only pin would have passed that run.
* **`docread`: the `bzip2Styles` ruling, two non-ruled disclosure companions, and a CONTROL**
  (unit U17). The control is `deflate-date-styles.xlsx`, the same `xl/styles.xml` content and
  CRC behind method 8 instead of 12, pinned as a literal on both sides — without it, a reader
  that stopped resolving date styles altogether would make the ruling start MATCHING and be
  reported as stale, which reads as good news.
* **+82 cases in one change: `docread` +29, `memorycli` +38, `wire` +15** (unit U3), covering
  every behaviour change the job landed, with `ruled-different` unmoved at 149 — every case
  added is an unruled comparison or a typed literal. New machinery came with them: a summaries
  protocol in `docread_ref.py` (rows as SHA-256 plus counts and edges) so a 16 MiB fixture
  costs one digest rather than two 16 MiB comparisons; `links:` fixture support in `memorycli`
  with a Windows symlink probe that skips by name; and a `{conformance: write}` driver
  directive honoured in lock-step by both wire loops and never forwarded to the server.

**The mutations are the reason to believe any of it, and two are worth quoting.** Removing the
`lexists` guard from BOTH sides made both mutants agree on "a filesystem error stopped the move
of back" — a sentence false about a move nobody attempted — and the differential was blind to
it. Keying the document cache on `realpath` alone on both sides left the differential green
while the typed literals went red. Every mutation this job applied was applied SYMMETRICALLY,
and in every case the differential stayed green while the typed literal went red, which is the
whole reason the literals are there.

**Not everything measured this job became a case, and one refusal is deliberate.** The zlib
damaged-member cause clause differs between the two runtimes on macOS (803 of 6,306 co-raising
inputs) and not at all against a stock madler zlib, because the phrase comes from whichever
`libz` the reference is linked against. Its expected value is a function of the HOST, so a
ruling would be red where the sides agree and a parity case red where they do not; it is
recorded in `docs/porting.md`'s gaps with the corpus and the commands, and NO case was written.

**AMENDED 2026-09-10 — job46 (`feat/job46-register-and-agent-stack`), `docs/porting.md`
register item 7.** The band in which `compact` was a no-op is closed on both runtimes, and the
gate for it is `wire.mjs`'s new `index-band` session plus a ceiling-parity sweep in
`store.mjs`. This entry records a RED the harness found and a red it could not have found.

<!-- provenance: value=7064 cases, 149 ruled-different, 0 failures; commit=55575c3 plus J46-6's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 7064 cases, 1790 byte-identical, 3423 exact-string, 1851 structural,
      149 ruled-different, 0 failures
```

Against the commit this unit started from (`55575c3`): **7034 cases, 149 ruled-different, 1
failure**. The delta is +30 cases — `store` 186 -> 189 and `wire` 417 -> 444, every other suite
at a byte-identical count — and `ruled-different` did not move, so nothing in the job became a
deliberate divergence.

**THE ONE FAILURE WAS ALREADY THERE, AND THE UNIT THAT CAUSED IT COULD NOT HAVE SEEN IT.**
`memorycli/compact-spares-feedback-until-the-other-classes-are-gone/archived-names` pinned
`['cpj','dpj']` as a literal. Bisected by RUNNING rather than reasoned: green at `6e506ca`
(310 cases, 0 differed), green at `181744a`, **11 differed at `87cc1f7`** — the reference-only
commit — and 1 differed at `55575c3` once the port caught up. `87cc1f7`'s own verify was
`.venv/bin/python -m pytest runtime-py/tests -q`, which does not run this harness at all, so a
unit that changed a memory-store default had no gate that could see the suite comparing the
two runtimes over that default. **The verify for a unit that changes shared-store behaviour is
`--suite <the suites that drive that store>` beside its own unit tests**, not the unit tests
alone.

The repair is an explicit `--reserve 62` on that scenario, not a bumped literal. Bumping it to
the three names the new default archives would also be green and would make the case's answer
identical to its sibling `compact-archives-feedback-once-nothing-else-is-left`, so the pair
would stop separating "the priority holds" from "the priority is not a veto" — the only thing
the pair exists for. An explicit reserve is what every eviction-order node here already passes,
so the case fails on ORDER and never on reserve policy. Checked: under a symmetric removal of
the class rank from both runtimes the repaired case still goes red.

**Non-vacuity, and the symmetric one is the finding.** Three mutations, each applied to a
`cp -R`/`git checkout` copy and reverted, with a green control either side:

* `Math.floor` -> `Math.trunc` in the port's `undegradedIndexCeiling`: **2 red**, both new
  ceiling cases.
* the `- 1` dropped from the same expression: **2 red** — and with the corpus trimmed to
  budgets that are NOT multiples of ten, the ceiling case goes **GREEN** under that same
  mutation. That is why the corpus carries a membership case pinning that both divisibility
  classes are still in it.
* **the default reserve reverted to `budget - largest line` on BOTH runtimes at once** — the
  exact change job46 made, undone symmetrically. `--suite memorycli`: **310 cases, 0 failures,
  green.** `--suite wire`: every per-frame differential comparison **green**, and 6 red, all of
  them per-side literals. A fourth mutation, the eviction class rank removed from both sides,
  reddened 4 literals in `wire` and 2 in `memorycli` and again not one differential case.

So the differential half of this harness was blind to the whole of register item 7 in both
directions, which is why `index-band`'s four assertions per side are literals and not one
runtime's answer handed to the other.

**GitHub Actions is off for this account — it bills the user — so nothing here was checked by
CI and nothing in this repository should be written as if it were.** The substitute is four
local gates, each run alone. At this tree:

<!-- provenance: value=2416 passed, 4 skipped, 1 deselected, 3 xfailed; commit=f484c70 plus this commit's working tree; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=All checks passed!; commit=f484c70 plus this commit's working tree; command=.venv/bin/ruff check runtime-py -->
<!-- provenance: value=595 tests, 593 pass, 0 fail, 2 skipped; commit=f484c70 plus this commit's working tree; command=cd runtime-ts && npm test -->
`.venv/bin/python -m pytest runtime-py/tests -q` **2416 passed, 4 skipped, 1 deselected,
3 xfailed**, with `grep -iE 'warnings summary|Warning'` over the run returning nothing;
`.venv/bin/ruff check runtime-py` **All checks passed!**; `cd runtime-ts && npm test`
**595 tests, 593 pass, 0 fail, 2 skipped**; and the `--all` line above. A pass count is a
function of repo content rather than of test code, so each is quoted with the tree it was
measured at and none of them is a standing number.

**AMENDED 2026-09-19 (J55-3) — the lint gate is wider than the stamp above records.** That
stamp is left exactly as it was written: `.venv/bin/ruff check runtime-py` really did print
`All checks passed!` at `f484c70`, and editing the command inside a stamp to today's
spelling would claim a run nobody made. Since job54 the gate is
`.venv/bin/ruff check runtime-py tools`, with the rule set it applies to `tools/` pinned in
`tools/ruff.toml` (J55-2). Re-measured here rather than restated:

<!-- provenance: value=All checks passed!; commit=bb9a246 plus this commit's working tree; command=.venv/bin/ruff check runtime-py tools -->
`.venv/bin/ruff check runtime-py tools` **All checks passed!** at `bb9a246` plus this
commit's working tree. That is the command to run today; the narrow one above is a record.

**AMENDED 2026-09-19 (J57-5) — the `updatecheck` suite landed, and `--all` is RED by one
case on purpose.** Measured at `56772d8` plus this commit's working tree, each command run
alone:

<!-- provenance: value=8481 cases, 2394 byte-identical, 3432 exact-string, 2655 structural, 154 ruled-different, 1 failures; commit=56772d8 plus this commit's working tree; command=node tools/conformance/run.mjs --all -->
<!-- provenance: value=2985 passed, 57 skipped, 2 deselected, 3 xfailed; commit=56772d8 plus this commit's working tree; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=All checks passed!; commit=56772d8 plus this commit's working tree; command=.venv/bin/ruff check runtime-py tools -->
<!-- provenance: value=1127 tests, 1080 pass, 0 fail, 47 skipped; commit=56772d8 plus this commit's working tree; command=cd runtime-ts && npm test -->
<!-- provenance: value=15 pass, 0 fail; commit=56772d8 plus this commit's working tree; command=node --test 'tools/hooks/*.test.mjs' -->
```
FAIL: 8481 cases, 2394 byte-identical, 3432 exact-string, 2655 structural, 154 ruled-different, 1 failures
```

against a baseline, taken on the same tree before a line of the suite existed, of `PASS: 8322
cases, 2373 byte-identical, 3427 exact-string, 2522 structural, 151 ruled-different, 0
failures`. **+159 cases, +3 rulings, +1 failure, and every other suite byte-identical in its
own line** — the delta is entirely the new suite. The one failure is the UTF-8-BOM arm
described in the suite table above: a real disagreement between the two readers, found by
writing the gate, not a regression in it. `.venv/bin/python -m pytest runtime-py/tests -q`
**2985 passed, 57 skipped, 2 deselected, 3 xfailed**; `.venv/bin/ruff check runtime-py tools`
**All checks passed!**; `cd runtime-ts && npm test` **1127 tests, 1080 pass, 0 fail, 47
skipped**; `node --test 'tools/hooks/*.test.mjs'` **15 pass, 0 fail**. That line is
SUPERSEDED by the J57-5b amendment below, which closed the failure; it is kept because it is
the measurement that found the defect.

**AMENDED AGAIN 2026-09-19 (J57-5b) — the BOM arm is closed IN THE RUNTIME and `--all` is
green.** `updatecheck.py` now reads the record with `utf-8-sig`, so both sides ACCEPT a
leading BOM — the three bytes `EF BB BF`, whoever wrote them, and bantamkit must work on
Windows. *(Amended 2026-09-21, J62-16: this used to read "PowerShell writes one by default".
Measured in `mcr.microsoft.com/powershell:latest`, PowerShell 7.4.2 writes NO BOM from
`Set-Content`, `Out-File`, `>` or `Add-Content`; only `-Encoding utf8BOM` does. Windows
PowerShell 5.1 is unmeasured — no Windows kernel here. The arms never depended on the writer.)*
`updatecheck.ts` is unchanged, its `TextDecoder` having stripped the BOM all along. The
held-out arm moved into the compared tables as three arms over the same BOM'd record at three
running versions, plus `unreadable/bom-not-json` as the control — so the suite grew by 7
cases and lost its failure. It is deliberately NOT a `ruling:`: nobody chose that difference
and there is none left to assert (see [porting.md](porting.md)). Measured at `56772d8` plus
this commit's working tree, each command run alone:

<!-- provenance: value=8488 cases, 2394 byte-identical, 3432 exact-string, 2662 structural, 154 ruled-different, 0 failures; commit=56772d8 plus this commit's working tree; command=node tools/conformance/run.mjs --all -->
<!-- provenance: value=2990 passed, 57 skipped, 2 deselected, 3 xfailed; commit=56772d8 plus this commit's working tree; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=All checks passed!; commit=56772d8 plus this commit's working tree; command=.venv/bin/ruff check runtime-py tools -->
<!-- provenance: value=1132 tests, 1085 pass, 0 fail, 47 skipped; commit=56772d8 plus this commit's working tree; command=cd runtime-ts && npm test -->
<!-- provenance: value=15 pass, 0 fail; commit=56772d8 plus this commit's working tree; command=node --test 'tools/hooks/*.test.mjs' -->
```
PASS: 8488 cases, 2394 byte-identical, 3432 exact-string, 2662 structural, 154 ruled-different, 0 failures
```

**+7 cases, +0 rulings, -1 failure against the J57-5 line, and every other suite
byte-identical in its own line.** THE NEW CASES ARE NOT VACUOUS, measured both ways on this
tree: with `encoding="utf-8"` put back in `updatecheck.py` the same run printed `FAIL: … 9
failures` (the three BOM arms under each key, plus the three summary tables that carry them),
and with `ignoreBOM: true` put into `updatecheck.ts` the port's own
`test/updatecheck.test.mjs` went **4 fail**. `.venv/bin/python -m pytest runtime-py/tests -q`
**2990 passed, 57 skipped, 2 deselected, 3 xfailed**; `.venv/bin/ruff check runtime-py tools`
**All checks passed!**; `cd runtime-ts && npm test` **1132 tests, 1085 pass, 0 fail, 47
skipped**; `node --test 'tools/hooks/*.test.mjs'` **15 pass, 0 fail**.

**And a measurement about this harness, taken by accident and worth keeping.** The first
`--all` of this unit was run WHILE `pytest` was running, and `ref/validate_ref.py` — which
finishes in well under a minute on an idle machine — was still going at ten minutes and was
SIGKILLed by the reference timeout, ending the run. The bound did exactly what its comment
says it does, and named the script. The lesson is for the operator, not the code: **run the
gates one at a time**, or a starved reference child looks exactly like a hang.

**The notes are part of the result, not decoration.** Several measurements this project
depends on exist only there — the live index byte count, the corpus SHA on both sides, how
many emitted files carry PyYAML's 80-column wrap, and the one remaining `NOT MEASURED HERE`
item that only a Windows runner can settle.

A failure prints both sides in full:

```
✖ store/os.replace names both paths
    python : "[WinError 3] The system cannot find the path specified: '…' -> '…'"
    node   : "[Errno 2] No such file or directory: '…' -> '…'"
```

## The real store is copied, never opened in place

**The size of that store is not written down here on purpose (corrected 2026-09-04, review
round 4).** Three places used to say "the real 65-fact store" — this line and the `codec` and
`store` suite headers — while the store was at 99 facts / 20,767 bytes when this line was last
read. A count of a directory the operator writes to every day cannot be kept true in prose, and
a wrong one reads as a claim about the corpus a case was measured over. Every run prints
today's number in its own notes (`real corpus: N facts copied from …`, and `live index: N bytes
on disk`), and the corpus-integrity case added by I3b is what makes a SHRINKING corpus a
failure rather than a smaller number. These are pointers, not records, so they are corrected in
place.

The `store` suite uses the live fact store as a fixture because synthetic facts do not carry
the shapes real ones do. It **copies it to scratch with
`cpSync(..., { preserveTimestamps: true })`** and runs there. Timestamps are preserved so the
`created`-from-mtime fallback reads the same number on both sides instead of two `cp` clock
samples.

Never point a suite at a store it does not own. A defect in exactly this area destroyed a
13,472-byte index once already.

**AMENDED 2026-09-19 — `codec` no longer reads the live store at all (J55-1).** It generates
exactly three cases per corpus fact, so reading a gitignored directory the operator writes to
all day made the suite's SIZE an input nobody could reproduce: job54 recorded 8166, 8169 and
8172 cases from `--all` at one unchanged commit, and J55-1 measured `--suite codec` going
**390 → 393 → 390** at `2b5c2ad` across one `memory_save` and its removal, with no code
change. Its real half is now **57 fact files frozen in git** at
`tools/conformance/fixtures/codec-corpus/`, copied byte for byte out of the live store on
2026-09-19 with four left out and named in that fixture's `README.md`; the adversarial set is
unchanged at 65. `--corpus` / `$BANTAMKIT_CONFORMANCE_CORPUS` therefore steer `store` only.
Measured at `2b5c2ad` plus this change, three consecutive runs and a run with an extra fact in
the live store: **379 cases, 0 failures** every time. The floor case is kept and joined by a
typed literal pinning the exact committed file count — `CORPUS_FLOOR` is 32 and would sit green
through a fixture that lost twenty files. Shown red rather than asserted: removing one fact
reds 1 case at 376, halving the corpus to 28 reds 2 at 292, deleting the fixture reds 2 at 208.

## Platform

The harness runs on ubuntu and Windows in CI. Two results are **Windows-only by
construction**. The first has since been read off a runner, so its note now carries the
measurement and cites the run; only the second still prints `NOT MEASURED HERE` on macOS or
Linux:

- **The index-budget arithmetic.** `write_text` translates `\n` to `\r\n` on Windows while
  `_check_index_budget` counts the untranslated text. Measured on the runner as exactly one
  byte per line: `index.md` 42 bytes on disk against 41 counted (1 line), a fact file 134
  against 124 (10 lines), a checkpoint 2609 against 2516 (93 lines). CPython gates the
  translation on `#ifdef MS_WINDOWS`, so macOS cannot construct the state. **The port now
  reproduces the arithmetic**, difference included: the budget counts the LF text and the
  writer translates, so the disk file is one byte per line larger than the number checked —
  on both runtimes, on both platforms.
- **The Win32 message table.** `FormatMessage for every winerror the port claims to render`
  asks `ctypes.FormatError` for all fifteen wordings, and `ctypes.FormatError` exists only on
  Windows. Off Windows the case does not run and the notes say so.

**The CRLF ruling is gone.** It was the only ruling in the codec suite and it is now two
ordinary cases: `toCrlf` against CPython's own `newline="\r\n"` translation, and
`Path.write_text` on whatever platform is running. Both are decidable everywhere.

Set `.gitattributes` to `* -text`. Without it, `core.autocrlf` on the Windows runner image
changes the working-tree bytes and the same commit produces a different `assets_digest`.
