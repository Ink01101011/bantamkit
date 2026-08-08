# MCP Adapter Design

**Date:** 2026-08-08
**Status:** Approved (scope chosen by user: memory + validation, no server-side model)
**Depends on:** team-ready (PR #5/#6, v0.2.0)

## 1. Problem

Teammates run agents that are not bantamkit `Agent`s — Claude Code, Codex,
local LLM harnesses. Those agents cannot use bantamkit's primitives today.
The deployment model is fixed by prior decision: **per-person instances, no
shared stores** — each person runs their own server against their own
project/profile memory.

## 2. Goal

A stdio MCP server, `bantamkit-mcp`, exposing the primitives that carry value
without a server-side model:

- **Tools**
  - `memory_save(type, name, description, body, links?)` — writes the project
    layer; identical semantics and reply strings as the library component
    (duplicate nudge, budget error, validation error).
  - `memory_recall(query, k?)` — reads across `Memory.layered()` layers:
    writable project store, read-only grants, read-only `~/.bantamkit/memory`
    profile; corrupt/absent read-only layers skipped.
  - `validate_json(output, schema)` — runs the existing `schema_error` logic;
    returns `{valid: bool, feedback: str | null}` where `feedback` is the same
    pointed revision message `SchemaGate` issues, so any external agent gets
    the measured schema-repair loop.
- **Resources** — `bantamkit://skills/{name}` and `bantamkit://rubrics/{name}`
  serving the asset pack verbatim (skills as markdown, rubrics as YAML). A
  caller can run our critique rubrics with its *own* model — critique value
  transfers without the server holding a client.
- **Instructions** — the server's `instructions` field is
  `assets/skills/memory.md`, so connecting clients receive memory usage
  guidance automatically.

## 3. Design decisions

- **SDK:** official `mcp` Python SDK, pinned `mcp>=2.0`, as an optional extra
  `bantamkit[mcp]` — the core library gains no dependency. Verified against
  the installed 2.0.0: high-level `MCPServer` (name/instructions/version),
  `@server.tool()` registration, `run_stdio_async()`, resource templates, and
  `mcp.Client(server)` in-memory transport for offline tests.
- **Single source of schemas:** the MCP `inputSchema` for the two memory tools
  is the asset pack's `assets/tools/*.json` `parameters` object, applied over
  the SDK's signature-derived schema after registration. A conformance test
  asserts the advertised schema equals the asset JSON exactly — if an SDK
  upgrade breaks the override, the test fails loudly. (Call-time argument
  validation still follows the handler signature, which mirrors the same
  schema.)
- **Module:** `runtime-py/src/bantamkit/mcpserver.py` (named to avoid
  confusion with the `mcp` SDK package), console script
  `bantamkit-mcp = bantamkit.mcpserver:main`.
- **Store selection:** default `Memory.layered()` from cwd — per-person,
  per-project, matching how MCP clients set a working directory per project.
  Flags: `--start DIR` (discovery start), `--store PATH` (single non-layered
  store), `--k N` (recall default budget, default 3). `--store` and `--start`
  are mutually exclusive.
- **Reuse over rewrite:** the server calls the existing `Memory` component's
  handlers — the same code path agents use — not a reimplementation. The
  handlers already return `"error: ..."` strings for recoverable failures,
  which map directly to MCP text results; unexpected exceptions surface as
  MCP tool errors and never kill the server.
- **Version:** bump to 0.3.0 in this cycle; tag `v0.3.0` post-merge, same
  release flow as v0.2.0.

## 4. Testing

All offline, in the existing pytest suite and CI:

- `Client(server)` in-memory session: `list_tools` shows exactly the three
  tools; memory tool schemas byte-equal the asset pack JSON.
- save → recall round-trip against a tmp project store; layered recall pulls
  from a seeded read-only profile layer without stamping it.
- `validate_json`: valid output, schema violation (pointed feedback), and
  unparseable JSON (parse feedback).
- Resources: listing includes skills/rubrics; reading returns file contents;
  unknown name errors cleanly.
- CLI: `--store`/`--start` exclusivity rejected; `--k` reaches recall.

## 5. Docs

`docs/mcp.md`: what the server exposes, per-person model (explicitly: no
shared stores), install (`pip install "bantamkit[mcp]"` — both git forms),
client setup for Claude Code (`claude mcp add bantamkit -- bantamkit-mcp`),
Codex, and generic stdio JSON config; flags table. README: docs list entry +
one line under Recommended defaults pointing external-agent users at the MCP
server. `docs/install.md`: extras note.

## 6. Success criteria

1. End-to-end stdio smoke (controller): launch the real `bantamkit-mcp`
   subprocess and, over an actual stdio MCP session, `memory_save` then
   `memory_recall` round-trips against a real project store. (In-session
   Claude Code attachment can't be exercised from inside this session; the
   docs carry the `claude mcp add` setup.)
2. Offline suite covers §4 and passes in CI alongside the existing 164 tests;
   ruff clean.
3. Tool schemas advertised over MCP are byte-identical to the asset pack.
4. Core install (`pip install bantamkit`) still works without `mcp` installed;
   `bantamkit-mcp` without the extra fails with a clear message naming
   `pip install "bantamkit[mcp]"`.

## 7. Out of scope

- Model-backed tools (critique scoring, structured completion) — needs the
  grounded-critique work first.
- HTTP/SSE transport, auth — per-person stdio only.
- Shared stores, locking, store provisioning.
- Admin ops (compact/archive) over MCP.
- Eval-over-MCP config.
- TS port.
