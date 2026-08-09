# Hardening v0.5 Design

**Date:** 2026-08-09
**Status:** Approved (user: execute the full backlog; TS port and suite-scoring
changes deferred — see §6)
**Depends on:** grounded-critique (PR #8, v0.4.0)

## 1. Problem

Four backlog items left by prior cycles, all small, all shippable together:

1. `Memory._save`/`_recall` are private but are the component's real API —
   the MCP server calls them across the underscore boundary
   (`mcpserver.py:47,53`).
2. `render_evidence` keys observations by `tool_call_id` in a dict — two
   calls sharing an id both render the *last* observation (grounded-critique
   final review, Task 2 Minor-3). Real endpoints issue unique ids; some
   local OpenAI-compatible servers reuse them, and evidence fidelity is the
   whole point of the grounded gate.
3. A missing rubric/skill resource surfaces to MCP clients as the generic
   `Error creating resource from template ...` — the pointed
   `unknown rubric asset: <name>` detail is lost (verified live: the SDK
   wraps arbitrary exceptions but passes `ResourceError` messages through).
4. The 420-run sweep showed `full`'s blind critic is a measured liability:
   `full` fails shop-basket-total 0/3 while the grounded gate passes it 3/3.
   The sweep kept `full` blind so critique-vs-grounded stayed clean; that
   comparison is banked, so `full` can now adopt the grounded gate.

## 2. Design decisions

### 2.1 Public `Memory.save` / `Memory.recall`

- Add public methods on the memory component with the exact signatures of
  the private ones: `save(type, name, description, body, links=None) -> str`
  and `recall(query, k=None) -> str`; the bodies move to the public names
  and `_save`/`_recall` become one-line delegating aliases (kept
  indefinitely — additive, nothing breaks).
- `mcpserver.py` switches to the public names.
- `docs/memory.md` documents the two methods as the programmatic API
  (same reply strings the agent tools see).

### 2.2 `render_evidence` forward-scan pairing

- Replace the id→observation dict with an in-order scan: walk `messages`
  once; each tool call pairs with the **first unconsumed** `role="tool"`
  message carrying its `tool_call_id` that appears **after** the assistant
  message making the call. Consumed observations are not reused.
- Unique-id transcripts render byte-identically to today (existing tests
  unchanged). Duplicate-id transcripts now pair positionally instead of
  giving every call the last observation.
- A call with no matching later observation still renders
  `-> (no observation)`; the no-calls sentinel and truncation are untouched.

### 2.3 MCP `ResourceError` detail

- Import `ResourceError` from `mcp.server.mcpserver.exceptions` inside the
  existing `try: ... except ImportError` block (same guarded-internal
  pattern as the `_tool_manager` schema override; the offline test fails
  loudly if an SDK upgrade moves it).
- `rubric_resource` raises `ResourceError(f"unknown rubric asset: {name}")`
  instead of `FileNotFoundError`; clients now receive that message verbatim
  (verified against SDK 2.0.0: `except (ResourceError, MCPError): raise`
  passes it through, everything else is wrapped generically).
- Same treatment for `skill_resource`: wrap `load_skill`'s `AssetNotFound`
  into `ResourceError(f"unknown skill asset: {name}")`.

### 2.4 `full` adopts the grounded gate

- `run_task`: `full` wires `GroundedCritiqueGate(client=tracking)` instead
  of `CritiqueGate("task-completion", client=tracking)`; `critique` keeps
  the blind gate (it remains the blind-vs-grounded control).
- Config table in `docs/eval.md` updated; `full` re-measured live
  (20 tasks × 3 repeats = 60 runs) and the Current results `full` row
  replaced with a footnote stating the row's provenance (post-swap run,
  own JSONL) — the other six rows keep the 2026-08-09 sweep numbers, which
  this change does not touch.
- Expected outcome (falsifiable): `full` picks up shop-basket-total; token
  cost rises (reasoning-field scoring). If the re-run instead *loses* runs
  net, the swap is reverted and the negative recorded.

### 2.5 Version

0.5.0 (public API addition + `full` semantics change). Tag `v0.5.0`
post-merge on the user's word.

## 3. Testing (offline, in CI)

- Public API: `save`/`recall` round-trip on a tmp store; reply strings
  identical to `_save`/`_recall`; aliases still work; MCP server tools hit
  the public methods (existing MCP round-trip tests keep passing).
- Pairing: duplicate-id transcript — two calls id `c1` with two
  observations pair in order; observation-before-call does not pair;
  existing unique-id tests unchanged.
- ResourceError: in-memory client reading a missing rubric/skill gets an
  error whose message contains `unknown rubric asset: <name>` /
  `unknown skill asset: <name>`.
- `full` wiring: fake-client test asserting `full` uses the grounded gate
  (critic prompt contains the evidence line); existing `full` tests updated
  to grounded-rubric verdict scripts.

## 4. Measurement (controller, live, qwen3:4b-instruct)

`full` config only: 20 × 3 = 60 runs, JSONL to
`docs/eval-data/2026-08-09-full-grounded-rerun.jsonl`; update eval.md
`full` row + narrative bullet; README untouched (its numbers cite
memory/lean, unchanged).

## 5. Success criteria

1. Suite + ruff green in CI; existing tests pass with only the `full`
   verdict-script updates §3 names.
2. MCP clients see pointed messages for missing resources.
3. `full` re-run: shop-basket-total rescued (else revert per §2.4).
4. Docs match code (memory.md API section, eval.md config table + row).

## 6. Out of scope

- Recall-task scoring conversion (`contains` → `json_equal`) and other
  suite-semantics changes — needs its own calibration cycle.
- Removing the unused sprocket fixture (harmless data).
- TS port phase 2 — separate project, own brainstorming cycle.
- MCP transport/auth changes; new tools.
