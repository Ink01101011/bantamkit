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

## Ranked backlog — (gain) / (build cost)

| # | Idea | Mechanism | Measure it by |
|---|---|---|---|
| 4 | **Real token ledger from transcripts** | Parse `usage.input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` per turn from `~/.claude/projects/*/*.jsonl`, attribute to tool calls; surface in `bantamkit_status` and the statusline. | It *is* the measurement — retires every char/4 estimate in this repo. |
| 5 | **Bounded consolidation ("dream") for the store** | Merge duplicates, absolutise dates, newer-wins on contradiction, emit a diff, hard cap on index bytes; run from a `SessionEnd`/cron, never a full rewrite (ACE). | Duplicate count and index bytes over time; recall top-1 identical before/after on a fixed query set. |
| 6 | **Precision gate on injection** | Only inject a recall hit whose score clears a threshold; log hit → "was the name later passed to `memory_recall` or quoted?" | Hit rate per 100 injections; SWE-ContextBench says a low rate is a loss, so cut the threshold until it rises. |
| 7 | **`memory_compact` as an MCP tool (both runtimes + conformance case)** | `Memory.compact()` exists at `component.py:486` and is written for a model; only registration is missing. The hook compacts today; the tool lets the model do it on refusal. | Refused-budget saves per week → 0. |
| 8 | **docread / filegraph as MCP tools** | The reader that clears 80 % on binary docs is reachable only from the Python `Agent`; expose `bantamkit_read(path, range)` returning head + skeleton + "expand" handle. Both runtimes, same schema. | Mean `tool_result` tokens per read of a pdf/docx. |
| 9 | **PreCompact steering from the ledger** | Emit "preserve: files X, Y; open shiftwork unit Z" from the read ledger + checkpoint. | Post-compaction re-reads of files already read pre-compaction. |
| 10 | **Repo map on demand (aider-style)** | tree-sitter defs → PageRank biased to the current unit's files → 1 K-token budget. Vendor "70×" graph numbers are [K]; build only after #4 shows discovery tokens dominate. | Discovery-phase tokens per unit. |

Out of scope until #4 exists: any claim of "X % saved" — the ledger is the denominator.

## Sources

Anthropic context management · Tool Search · Claude Code hooks/memory/context-window docs ·
SWE-ContextBench (arXiv 2602.08316) · ACE (arXiv 2510.04618) · GEPA (arXiv 2507.19457) ·
CODESKILL (arXiv 2605.25430) · SWE-MeM (arXiv 2606.28434) · A-MEM (arXiv 2502.12110) ·
Zep vs Mem0 LoCoMo rebuttal · `read-once` and claude-mem file-read gates · aider repo map.
