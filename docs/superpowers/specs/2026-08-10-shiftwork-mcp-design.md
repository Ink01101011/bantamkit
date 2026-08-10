# Shift-Work MCP Flavor Design

**Date:** 2026-08-10
**Status:** Approved (user-directed, 2026-08-10 — opened after LoopGuard
merged as v0.12.0). Reshape of the deferred MCP flavor: "ทำ mcp ต่อกับ claude แล้วให้ claude ใช้เมื่อต้องการ spawn agent
เพื่อใช้เป็น dogfood" — connect the MCP to Claude Code, and the
orchestrating Claude session uses it around agent spawns.
**Depends on:** v0.11.0 shift-work v1 (checkpoint schema asset +
driver semantics — the MCP flavor mirrors the driver, never diverges).

## 1. Problem

The driver flavor spawns `claude -p` sessions from outside; the MCP
flavor serves the *inverse* topology: an already-running Claude session
orchestrates subagents and needs clock-in/clock-out state discipline.
Today that state lives in ad-hoc task-brief files and a gitignored
ledger — unvalidated, unaccounted, invisible to the experiment
instrument. The checkpoint contract already encodes exactly what a
spawned agent needs and what it must hand back; the MCP tools make the
orchestrator read and write it under schema validation.

## 2. Design

### 2.1 Three tools on the existing `bantamkit-mcp` server (mcpserver.py)

- `shiftwork_clock_in(checkpoint: str)` — read + full-schema-validate
  the checkpoint file (via `load_schema("shiftwork-checkpoint")` +
  the `schema_error` engine, same as sessions do under the driver);
  refuse (structured error, not exception) when `handoff.open_questions`
  is non-empty (ESCALATE semantics) or all units are done/dropped
  (SUCCESS semantics); otherwise return the unit at `plan.cursor`:
  `{unit, role, invariants, handoff, do_not, files}` — the brief the
  orchestrator hands to the spawned agent verbatim.
- `shiftwork_clock_out(checkpoint: str, unit_id: str, status: str,
  handoff_patch: dict, history_entry: dict, accounting: dict | None)`
  — apply the session's result: set unit status (schema enum), advance
  `plan.cursor`, merge handoff, push the history ring (maxItems 5,
  driver-identical truncation), then validate the WHOLE resulting
  document against the schema BEFORE writing; write atomically
  (tmp + rename, the driver's pattern). Validation failure = nothing
  written, error returned. **Accounting (user requirement — "เก็บผล"):**
  every successful clock_out also APPENDS one line to
  `<checkpoint>.log.jsonl` beside the checkpoint — unit id, role,
  status, ts, plus the orchestrator-reported `accounting` fields
  (tokens, duration, model) — the same shape as the driver's
  per-session JSONL, so the history ring's 5-entry cap never loses
  measurement data and driver-flavor vs MCP-flavor runs are comparable
  on one format. The log is append-only and never read by the tools.
- `shiftwork_status(checkpoint: str)` — read-only progress summary
  (units by status, cursor, open questions count, last history entry).
  Never mutates.

No lock tool: the MCP topology has one orchestrator by construction;
the driver's O_EXCL lock guards *cross-process* races, which the
`.superpowers`-style single-session use does not have. Documented, and
clock_out re-validates before writing so a concurrent driver run fails
validation-visibly rather than corrupting.

### 2.2 Claude Code wiring (the "ต่อกับ claude" half — two scopes)

- **Project scope (this repo):** `.mcp.json` committed at repo root —
  `bantamkit-mcp` from the repo venv; every session in bantamkit sees
  the tools with zero setup.
- **User scope (user requirement — "ทดสอบกับ session อื่นๆ บนงานจริง"):**
  the tools must reach sessions in OTHER projects (code-fix, code-trace
  jobs). docs/mcp.md documents the one-liner
  (`claude mcp add bantamkit --scope user -- <pinned-install>/bin/bantamkit-mcp …`)
  against the pinned wheel install, and as part of this cycle the
  server is actually registered user-scope on this machine and
  smoke-tested from a session OUTSIDE the repo (bar 3). Checkpoint
  path convention for arbitrary projects: `.shiftwork/checkpoint.json`
  in the target repo (log lands beside it); the tools take an explicit
  path, so the convention is documentation, not code.

docs/mcp.md gains the shiftwork section (tool schemas,
ESCALATE/SUCCESS refusal semantics, dogfood workflow, both scopes).

### 2.3 Dogfood workflow (the "ให้ claude ใช้" half — docs + policy)

docs/shiftwork.md gains an "Orchestrator flavor" section: plan once
into a checkpoint (planner role = the session itself), then per unit:
`shiftwork_clock_in` → dispatch subagent with the returned brief →
`shiftwork_clock_out` with status + handoff + accounting. The first
real job is the full re-baseline sweep cycle (watched first run, per
the v1 condition).

**Standing policy (user requirement — "เรียกใช้เสมอ"):** MCP tools are
visible to every session, but nothing makes a session reach for them
unprompted — so the rule ships as a short, copyable policy block:
any multi-unit orchestration (≥2 planned units, or any
spec→plan→implement / bugfix / code-trace job that fans out agents)
MUST run its agent spawns through clock_in/clock_out; one-off ad-hoc
spawns (a single search or review with no plan behind it) are exempt —
no unit to clock, checkpoint-per-spawn is overhead without
measurement value. The block is committed in TWO places this cycle:
the repo's CLAUDE.md (covers bantamkit sessions) and the user-level
`~/.claude/CLAUDE.md` (covers every other project on this machine —
the "session อื่นๆ" case; project memory does not travel across
cwd's, user-level CLAUDE.md does). docs/shiftwork.md carries the same
block for copying into any other machine/project.

**Role → model mapping (user question — "default หรือ random"):**
never random, and never silently inherited: `clock_in` returns the
unit's `role`, the orchestrator maps role → model when spawning
(documented recommendation: planner = session model, implementer =
cheapest tier the brief supports — a brief with complete code is
transcription, reviewer = mid-tier floor, judgment-heavy review =
session model), and `clock_out`'s accounting line RECORDS the model
actually used per unit, so every run is auditable after the fact.
This mirrors the driver's explicit `driver.yaml` role dispatch — the
MCP flavor moves the decision to the orchestrator but keeps it
explicit and logged.

**Real-job shape (user's examples — แก้ code / ไล่ code):** the
checkpoint schema is already task-agnostic; docs/shiftwork.md adds a
worked example checkpoint for a code-fix job (units: reproduce →
locate → fix → verify, reviewer role on the fix unit) so the first
non-bantamkit dogfood run starts from a template, not a blank file.

## 3. Bars

1. Offline: clock_in returns the cursor unit's brief byte-faithfully;
   refuses on open_questions / all-done; clock_out round-trips a valid
   update (re-read passes schema), rejects an invalid status enum and
   an over-long history ring without writing; atomicity (failure leaves
   prior bytes); tools registered on the same server instance as
   memory_save (one server, one entry point).
2. Example checkpoint from v1 (`tools/shiftwork/example-checkpoint`)
   drives a full clock_in → clock_out → clock_in cycle in tests.
3. Live: `.mcp.json` resolves in a real Claude Code session on this
   machine; one watched dogfood unit executed end-to-end (recorded in
   the PR body, not automated).

## 4. Success criteria

Tests green (477 + new), ruff clean, CI green; tools live on
`bantamkit-mcp` with the schema-validated round-trip proven offline;
`.mcp.json` committed; user-scope registration done and smoke-tested
from a session outside the repo; CLAUDE.md policy blocks committed
(repo) and installed (user-level); docs (mcp.md + shiftwork.md)
updated incl. the code-fix example checkpoint and role→model mapping;
v0.13.0; PR merged (pre-authorized); tag; pinned install verified.

## 5. Out of scope

The N-sessions-vs-one experiment itself (separate item; this ships its
instrument); retro automation; spawning sessions from the MCP server
(impossible by design); multi-orchestrator locking; driver changes.

**Deferred follow-up (user question, 2026-08-10 — qwen subagents):**
Claude-Code-spawned subagents are Claude-only; local qwen enters as an
implementer role via a bantamkit runner (bantamkit `Agent` + Ollama)
reading the same clock_in brief — the checkpoint contract is already
model-agnostic and the accounting line already records model-per-unit.
Two measured prerequisites before any qwen unit writes code: (1) a
write-tool primitive (eval workspaces are deliberately read-only
today; nothing in the toolkit writes files), (2) a measured
code-writing bar — the suite has no code-write family, and per project
ethos small-model code-writing is a claim to measure (qwen-coder tier
+ verbatim-code briefs + stronger-model reviewer), not assume.
Code-READING units (ไล่ code) are already in evidence via the file-nav
family. This whole item is the natural second dogfood experiment after
the re-baseline job.
