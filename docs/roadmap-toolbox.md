# Roadmap — bantamkit as the master agent toolbox

Goal, set 2026-08-27: the agent gets cheaper and smarter **without anyone triggering it**.
Two axes: token cost per session, and lessons that survive across sessions and projects.

## Where the ecosystem stands (web survey, 2026-08-27)

Legend: [M] measured by the source itself · [I] independently measured · [K] marketing.

**Table-stakes — the host already does it, do not rebuild:**
- Small always-loaded memory index + topic files read on demand (Claude Code auto-memory).
- Deferred tool schemas and skill bodies (Tool Search; `ENABLE_TOOL_SEARCH`) — [M] 85 % fewer
  schema tokens, internal.
- Compaction that re-injects CLAUDE.md, the memory index, ≤5 recent files and invoked skills;
  `PreCompact` steering; `SessionStart[compact]` hooks.
- Server-side context editing (API only, not in Claude Code) — [M] +29 %, 84 % tokens, internal.

**What is still open — where a personal toolbox can differentiate:**
- **Retrieval precision.** SWE-ContextBench [I]: Mem0 24.2 % resolve *below* the 26.3 %
  no-memory baseline; memory helps only when retrieval is precise. Nobody ships a precision gate.
- **Consolidation without collapse.** ACE [M] shows rewrite-everything summaries erode detail;
  auto-dream is unreleased and unmeasured. Delta updates, never full rewrites.
- **Compaction-aware read dedupe.** `read-once` [M] saved 40 % of read tokens in one session
  with a 20-minute TTL guess; a ledger that *knows* compaction happened needs no guess.
- **Cache-safe injection.** Per-turn hook output that lands before the stable prefix defeats
  prompt caching. Nobody documents this.
- **Real measurement.** Every hook tool reports char/4 estimates; nobody closes the loop
  against `usage` in the transcripts.

## Built 2026-08-27 — `docs/hooks.md`

Idea 1 (compaction-aware read gate), 2 (Stop-hook reflection into the validated store), and 3
(precision-capped SessionStart/UserPromptSubmit injection) from the ranked list below landed
as `tools/hooks/bantamkit-hook.mjs`. Profile layer seeded with 20 feedback/user facts.

## Built 2026-08-27 — `memory_compact` (#7), branch `feat/memory-compact-tool`

`memory_compact` is served ninth by both runtimes (9fc8607 runtime-py, 2c208f4 runtime-ts),
and `memory_save`'s refused-budget reply now ends by naming it. Measured: both launchers
answer `tools/list` with ten tools since #8 landed (`test_served_tool_count_records.py`;
nine when this row was written, 2026-08-27 — the gate did not see it because
`` `tools/list` `` sat between "answer" and "with"; widening that regex is a runtime-py
follow-up, row 8), and
`node tools/conformance/run.mjs --all` compares the story end to end — refusal, compaction,
retry, every shape of `reserve`, the event-log records — in 33 new `wire` cases, four of
them hardened by review (195 -> 232 in the suite, 4841 -> 4878 overall, 0 failures;
`docs/conformance.md`). The hook still compacts at 90 %
of budget on its own; the tool is the on-refusal path the model reaches itself. The
"refused-budget saves per week" number is not measured yet — it needs the event log on in a
real session, which is #4's territory.

Follow-up, registered 2026-08-28 (not fixed here): the `PostToolUse` hook opens
`Memory.layered(cwd)` at the DEFAULT 24000-byte budget while the server honours
`--index-budget N`, so under a non-default budget the 90 % band is measured against the
wrong denominator and only the tool's half applies. The hook should read the flag (or the
server should publish its budget somewhere the hook can read) before the two halves are
one mechanism at every budget.

## Ranked backlog — (gain) / (build cost)

| # | Idea | Mechanism | Measure it by |
|---|---|---|---|
| ~~4~~ | ~~**Real token ledger from transcripts**~~ — built in PR 79 (784201e, `tools/ledger/token-ledger.mjs`, `docs/ledger.md`) | ~~Parse `usage.input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` per turn from `~/.claude/projects/*/*.jsonl`, attribute to tool calls; surface in `bantamkit_status` and the statusline.~~ Reads `usage` per `requestId` off the host's transcripts, tool calls and `tool_result` bytes by name, repeated Reads; bytes stay bytes and are labelled `est` if ever divided by 4. | It *is* the measurement. Not yet surfaced in `bantamkit_status` or the statusline. |
| 5 | **Bounded consolidation ("dream") for the store** | Merge duplicates, absolutise dates, newer-wins on contradiction, emit a diff, hard cap on index bytes; run from a `SessionEnd`/cron, never a full rewrite (ACE). | Duplicate count and index bytes over time; recall top-1 identical before/after on a fixed query set. |
| 6 | **Precision gate on injection** | Only inject a recall hit whose score clears a threshold; log hit → "was the name later passed to `memory_recall` or quoted?" | Hit rate per 100 injections; SWE-ContextBench says a low rate is a loss, so cut the threshold until it rises. |
| ~~7~~ | ~~**`memory_compact` as an MCP tool (both runtimes + conformance case)**~~ — built, see above | ~~`Memory.compact()` exists at `component.py:486` and is written for a model; only registration is missing.~~ The hook compacts at 90 %; the tool is the model's path on refusal. | Refused-budget saves per week → 0 (#4 exists now; still unmeasured). |
| 8 | **docread as an MCP tool** — `bantamkit_read` landed 2026-08-28 (job43, branch `feat/bantamkit-read-tool`: 92661f7 asset, bf9d0a9 runtime-py, ed3d23f + ce46fc3 runtime-ts, 96273f1 conformance) | ~~expose `bantamkit_read(path, range)` returning head + skeleton + "expand" handle~~ Served tenth by both runtimes: `path` alone returns the manifest (kind, parts, omissions); `part`/`offset`/`limit` pages rows under evalrun's ceilings (50 rows, 200 max, 3072 bytes). Node reads text/docx/xlsx/html/mhtml byte-identical to Python (3,333 real files, 71 of 77 fixtures); pdf/doc/rtf are **ruled** refusals on Node until job44 ports `pdfread`, which lifts the ruling. Conformance 4878 -> 5542 cases (`docread` suite + `bantamkit_read` wire sessions; `node tools/conformance/run.mjs --all` at ab43bc9: 5542 cases, 115 ruled-different, 0 failures; after F4 on 2026-08-28: 5760 cases, 116 ruled-different, 0 failures — the 116th is utf-7, `docs/porting.md` "utf-7 on Node"). **filegraph dropped from this row:** `FileAccessGraph` is constructed only at `evalrun.py:1733` for evalrun's own `Agent`, and the `PreToolUse` hook's read ledger already covers the operator's reads (`docs/hooks.md`). | Measured in bytes, not tokens (`docs/eval-data/2026-08-28-bantamkit-read-bytes.md`, `tools/ledger/read-bytes.mjs`): manifest + first page, Python, over `~/Downloads` — pdf n=40 median 4,270 B (mean 16,768, one 241-page pdf returns a 357,083 B manifest), xlsx n=6 median 3,929 B (5 paged, mean 9,735; the sixth's first sheet has 0 rows, so page 0 is a `refused-offset` reply of 87 B on both servers — re-measured at F4 after the ledger's refusal tally was fixed, `read-bytes.mjs` now counts `error: `-prefixed replies as refusals, 0 manifest / 1 page refused of 48), docx n=2 median 3,207 B; Node byte-identical on every xlsx/docx. Host `Read` on the same files: xlsx refused (167 B, 817 real tokens round trip), 2-page pdf shipped whole as a document block (5,995 real tokens). Follow-up: the page is capped at 3,072 B but the manifest is not — cap it before the mean is small on every file. Follow-up (F4, registered 2026-08-28): paging is O(N²) in the row window — `mcpserver.py:948` and `runtime-ts/src/mcp/server.ts:457` call `docread.extract(path)` afresh on EVERY `bantamkit_read`, so a caller walking a 12,001-row sheet in 200-row pages re-parses the whole workbook 61 times; fix on both sides = a single-entry cache keyed on (realpath, size, mtime_ns), with a conformance case that reads a file, rewrites it in place, and reads again. Tokens per `bantamkit_read` call need a host session with the tool registered (#4's ledger reads them). **Follow-ups registered by job43 G3 (2026-08-29), each with the line that shows it:** (a) OOXML is read from disk twice per `extract` — `sniff` opens the archive (`runtime-ts/src/docread.ts:593` `ZipReader.open(path)`) and the extractor opens it again (`docread.ts:1037` `openZip` → `ZipReader.open`, called at 1925/1945), two `readFileSync` per call; hand the sniffed reader down. (b) The manifest-entry dict `{document, kind, parts, omissions, …}` is hand-copied three times — `runtime-py/src/bantamkit/evalrun.py:1296`, `runtime-py/src/bantamkit/mcpserver.py:954` and `runtime-ts/src/mcp/server.ts:486` — with no shared helper and no test that the eval harness and the MCP server render the same manifest for the same file. (c) `OFFSET_MAXIMUM` (2**53 - 1) is spelled in three places — `assets/tools/bantamkit_read.json:24` `maximum`, `runtime-py/src/bantamkit/mcpserver.py:624`, `runtime-ts/src/mcp/pyargs.ts:62` — with no test tying the two runtime constants to the asset's number. (d) `Part.textBytes` (`runtime-ts/src/docread.ts:422`) joins the whole text to measure one number; count bytes per row instead. (e) `<!ATTLIST>` default attribute values are applied by the reference's expat and skipped by the port's internal-subset walk (`docread.ts:1319`); no OOXML writer emits one, so no fixture measures it — `docs/porting.md`, "Gaps the differential cannot see". (f) A zip member past 536,870,888 bytes raises `ERR_STRING_TOO_LONG` on the port (V8's string ceiling; honest, not silent) where the reference reads it — reported in `docs/porting.md`'s gaps, not matched, because a 512 MiB fixture per run is not a cost the suite pays. (g) `runtime-py/tests/test_served_tool_count_records.py`'s `CLAIM` regex needs `answers? \S* with` (or similar, strictly wider) so "answer `tools/list` with nine tools" is a claim it sees — the line above at #7 outlived the tenth tool unseen until G3 read it. **Round 3 (H1/H2/H3, 2026-08-29):** (e) is CLOSED as a gap and is now a ruling — `attlist.xlsx` shows the two sides differing (`SHARED` / `0`), `docs/porting.md` "`<!ATTLIST>` defaults on Node". **Follow-ups registered by H3, each with the line that shows it:** (h) `runtime-py/src/bantamkit/evalrun.py:1334` still answers a zero-row part with `document_offset_past_end`, whose sentence reads `numbered 0 to -1`; `mcpserver.py:1004` and `runtime-ts/src/mcp/server.ts` answer `"<part>" in <path> has no rows` since H1 (pinned on the wire, `read: id 12`), so the eval harness and the MCP server render different sentences for the same file — the third copy of (b)'s hand-copied manifest. (i) Per-server `Document` cache: the F4 follow-up above (a single-entry cache keyed on realpath, size, mtime_ns) is still open on both sides; `mcpserver.py` and `server.ts` still call `docread.extract(path)` on every call. (j) `ZipReader` reads the archive from disk twice per `extract` — (a) above, still open after H2 (`runtime-ts/src/docread.ts:1062` `ZipReader.from(readFileSync(...))`). (k) html and mhtml are read UNBOUNDED on both sides — `runtime-py/src/bantamkit/docread.py:1239` `path.read_bytes()` and `runtime-ts/src/docread.ts:2953`/`:2986` `readFileSync` — where plain text stops at `TEXT_MAX_BYTES` (`docread.py:193`, 16 MiB, `docread.py:1341`); a 1 GB `.html` is held whole. (l) `OFFSET_MAXIMUM` (2**53 - 1) and the `[1, 200]` limit clamp (`mcpserver.py:968` `max(1, min(limit, docread.PAGE_MAX_ROWS))`, `server.ts:455`, `assets/tools/bantamkit_read.json:30` `maximum: 200`) are literals in three places with no test tying the runtimes' constants to the asset's numbers — (c) above, widened to the row ceiling. (m) `tools/ledger/read-bytes.mjs:136`: a manifest whose `firstPart` is `null` (a zero-part document) is tallied as a manifest row with `pageRefused: null`, so the ledger's refusal count neither counts it nor names it. (n) `runtime-ts/src/docread.ts` carries its own `pyStrip` (`:83`), `cmpCodepoint` (`:189`) and `pyRepr` (`:216`) beside `memory/factfile.ts:61` `pyStrip` and `memory/pyfs.ts:835` `cmpCodepoint` — duplicate ports of the same CPython semantics, to be unified in one module. (o) CJK codecs decode through ICU's `TextDecoder` and not CPython's tables: H2 measured 300 random byte strings per codec against `bytes.decode(codec, "replace")` (seed 7) — euc_jp 297, euc_kr 296, cp932 295, gb18030 292, gbk 278, shift_jis 268, big5 208, big5hkscs 205, cp949 192, gb2312 141 of 300 match; the residual is ICU's table against CPython's and is not pinned by any conformance case (the `charsets` suite pins the single-byte tables and, for the ten CJK codecs, only which lone high bytes are characters). (p) The 300,000-cell row (H2's `Math.max` fix) has no conformance fixture: the smallest deflated xlsx that shows it is 1,501,739 bytes, over the 1 MB ceiling; held by `runtime-ts/test/docread.test.mjs:267` alone. |
| ~~9~~ | ~~**PreCompact steering from the ledger**~~ — built in PR 78 (b3625d9, `docs/hooks.md` `PreCompact` row) | ~~Emit "preserve: files X, Y; open shiftwork unit Z" from the read ledger + checkpoint.~~ Emits exactly that from the hook's read ledger and the open `.shiftwork/checkpoint.json` cursor. | Post-compaction re-reads of files already read pre-compaction — measurable now with #4, not yet measured. |
| 10 | **Repo map on demand (aider-style)** | tree-sitter defs → PageRank biased to the current unit's files → 1 K-token budget. Vendor "70×" graph numbers are [K]; build only after #4 shows discovery tokens dominate. | Discovery-phase tokens per unit. |

#4 exists (`docs/ledger.md`): any claim of "X % saved" is read off it or is not made.

## Sources

Anthropic context management · Tool Search · Claude Code hooks/memory/context-window docs ·
SWE-ContextBench (arXiv 2602.08316) · ACE (arXiv 2510.04618) · GEPA (arXiv 2507.19457) ·
CODESKILL (arXiv 2605.25430) · SWE-MeM (arXiv 2606.28434) · A-MEM (arXiv 2502.12110) ·
Zep vs Mem0 LoCoMo rebuttal · `read-once` and claude-mem file-read gates · aider repo map.
