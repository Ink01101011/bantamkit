---
name: project-compaction-mcp-alive-but-unwired
description: why compaction contributes zero today - the server is alive with 19 tools
  but attached to no client, and every bantamkit primitive passes its functional check
type: project
created: '2026-08-21'
last_recalled: '2026-09-15'
links:
- project-token-levers-measured-on-real-corpus
- reference-token-lever-assets
---

Functional check run 2026-08-21, PASS/FAIL per primitive against real input, not a vibe.

**compaction-mcp is ALIVE and NOT WIRED.** A real MCP stdio handshake succeeded: `serverInfo {name: compaction-mcp, version: 0.1.0}`, protocol `2024-11-05`, **19 tools** — `context_status, context_compact, context_trim, context_clear, handoff_brief, turn_add, files_track, files_untrack, files_rehydrate, read_offloaded, offload_store, offload_fetch, recall, rules_set, rules_append, rules_get, ledger_record, ledger_query, ledger_snapshot` — stderr `ready (mode=passthrough, summarizer=direct, model=qwen2.5-coder:14b)`.

**But it is registered with no Claude Code client.** The only root-scope MCP server is `bantamkit`; project-scoped are `aikktest` and `kkskills`. **It cannot compact anything it is not attached to, so its measured value in the loop is exactly zero — and that is a CONFIGURATION fact, not a capability fact.** Also stale: `dist` reports 0.1.0 while `package.json` says 0.1.1.

**Every bantamkit primitive PASSES**, each with evidence:
- `Memory` save/recall — saved, recalled by query, and a re-save under the same name returned `status='saved'` as an update rather than a duplicate.
- `FileAccessGraph` — 3 real reads of one file: 1st returned 1,098 B verbatim, 2nd and 3rd collapsed to the `[file-graph]` marker. `reader_calls=3, repeat_reader_calls=2, collapsed_calls=2, collapsed_bytes=1922`. The mechanism works; the opportunity set on real traffic is what is empty.
- MCP `memory_recall` / `memory_save` / `validate_json` — the last non-vacuously: it rejected a deliberate type error naming the path, `at 'tokens': 'not-an-integer' is not of type 'integer'`.
- `shiftwork_status` / `clock_in` / `clock_out` — clock_out's **first call correctly REFUSED** (`'outcome' is a required property`), proving validate-before-write; the second wrote atomically, advanced the cursor, and appended the accounting line.
- `build_identity` — `version 0.25.0`, `build_id sha256:2aa25085…`, 22 code files / 78 assets, and it refuses `git_commit` with a stated reason rather than a placeholder.

So the "graph/memory/compaction works 100%" half of the user's goal is **already true for bantamkit's own primitives**; the only gap is that compaction-mcp is attached to nothing. Wiring it is a configuration change with a measurable before/after, and it is the cheapest thing on the compaction axis.

See [[project-token-levers-measured-on-real-corpus]], [[reference-token-lever-assets]].
