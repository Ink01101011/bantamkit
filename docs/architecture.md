# Architecture: the 5-layer model

bantamkit is organized into five layers plus a measurement harness. The
rule is strict and non-negotiable: **a change lives in exactly one layer.**
If a diff touches two layers, split it. The boundary test: can you change
one layer without touching the others — swap the verdict wording without
touching gate logic, swap a profile without touching prompts, swap the
server without touching anything?

The model was ratified after the cross-model sweep
([Eval → Cross-model results](eval.md#cross-model-results)) measured where
n=1 calibration had leaked: every cross-model failure clustered in
model-facing wording and parsing, while the mechanics underneath
transferred fine. The layer split makes that seam physical
(spec: `superpowers/specs/2026-08-10-layer-separation-design.md`).

## The layers

| layer | owns | lives in |
|---|---|---|
| **1 — Core** | deterministic mechanics, proven cross-model: agent loop, gate control flow, memory store, filegraph ledger/cache, token accounting, dependency-graph batching | `agent.py`, `memory/` (most of it compiled from TypeScript into `_generated/`: [Generated modules](#generated-modules-where-they-sit)), `filegraph.py`, gate mechanics in `critique.py` / `structured.py`, `textutil.py`, `workplan.ts` (the Kahn batcher: pure computation over the nodes it is handed — `workplan.ts` imports nothing, and the Python compiled from it, `_generated/workplan.py`, imports only `_ts2py_runtime`; the shim `workplan.py` adds `typing.Any`. Read off the files rather than asserted by a gate; see the note below) |
| **2 — Contract** | everything the model reads or writes: instruction/feedback/evidence wording (data) + outbound parsing (code) | `contract.py` + `assets/contracts/`; rubrics, skills, tool schemas in `assets/` |
| **3 — Transport** | wire protocol, retries, timeouts, (future) server capability detection | `client.py` |
| **4 — Policy/Profile** | tunables as named data: turn budgets, retry caps, evidence budgets | `profile.py` + `assets/profiles/` |
| **5 — Composition** | user-owned recipes: `Agent.use(...)`, eval configs (`lean`/`full` are named compositions), the MCP server | `mcpserver.py`, `eventlog.py` (the MCP event log — a deployment diagnostic, off unless an operator asks for it: [eventlog.md](eventlog.md)), `mcpreport.py` (the read-only analyst over that log and the host's: [mcpreport.md](mcpreport.md)), `shiftwork.py` (the shift-work adapter surface — its logic imports no `mcp`, only `mcpserver.py` does), `examples/`, eval config wiring |

**Measurement** is not a product layer — it is the boundary keeper:
`evalrun.py` produces the evidence, the claims-transfer table in the eval
docs is the regression test that contract hasn't leaked into core, and
`tests/test_layers.py` enforces the boundary mechanically (golden
byte-identity for every contract string, core-purity scan, import
direction, profile-value guard). New primitives must measure uplift on
more than one model before promotion.

## Generated modules: where they sit

Part of runtime-py is not hand-written. The TypeScript in `runtime-ts/src` is the one source
for these modules, and `tools/ts2py` (a Rust compiler built on oxc; its subset is
`tools/ts2py/SUBSET.md`, its rules `tools/ts2py/RULES.md`) compiles them into
`runtime-py/src/bantamkit/_generated/`, where they are committed:

| generated module | TypeScript source | layer | Python shim (the public name) |
|---|---|---|---|
| `workplan.py` | `workplan.ts` | 1 — Core | `bantamkit/workplan.py` |
| `pyyaml.py`, `factfile.py` | `memory/pyyaml.ts`, `memory/factfile.ts` | 1 — Core | `bantamkit/memory/factcodec.py` |
| `store.py`, `native.py`, `retrieval.py`, `usage.py`, `queries.py`, `layers.py`, `dream.py`, `component.py` | `memory/*.ts`, same names | 1 — Core | `bantamkit/memory/<name>.py` |
| `pricing.py`, `tokenledger.py`, `jobbudget.py` | `pricing.ts`, `tokenledger.ts`, `jobbudget.ts` | 1 — Core (token accounting) | `bantamkit/<name>.py` |
| `logsegment.py` | `storage/logsegment.ts` | 1 — Core | `bantamkit/storage/logsegment.py` |
| `eventlog.py` | `eventlog.ts` | 5 — Composition | `bantamkit/eventlog.py` |
| `_ts2py_runtime.py`, `_ts2py_adapters.py` | `tools/ts2py/src/runtime.py`, `adapters.py` | support, no layer | — |

A generated module stays in the layer its TypeScript source is in; generation moves no
boundary. Two seams keep it there:

- **The shim.** Every generated module is reached through a hand-written module under the old
  name, which keeps the public Python API (snake_case names, dataclasses, `Path` arguments,
  Python exceptions) and converts values at the crossing. A caller imports the shim, never
  `_generated/`.
- **The adapters.** An import the compiler does not compile (a hand-written Python module, a
  Node builtin such as `node:fs`) resolves only through a row in `tools/ts2py/src/adapters.rs`,
  written in `tools/ts2py/src/adapters.py`; each row names why the Python is the same function
  and the measurement that pins it. An import with no compiled module and no row is a compile
  error. JS semantics the subset needs (`===`, UTF-16 strings, `sort`) are in
  `_ts2py_runtime.py`.

To change one of these modules, edit the TypeScript and regenerate
([Install → Working on a generated module](install.md#working-on-a-generated-module));
`docs/porting.md` (*Generated modules*) has the full history and every ruling.

## How the layers interact

Core imports wording from `contract` and numbers from `profile` — never
the reverse (`test_layers.py::test_import_direction` fails the suite if
`contract.py` or `profile.py` ever imports core). Constructor arguments
always win over profile defaults; `None` means "resolve from the default
profile". The default profile ships today's values, which are
4b-calibrated — that calibration is now *named data with a comment saying
so* instead of silent constants.

Two rules got sharper in the 2026-08-11 RB-P round, without any boundary
moving:

- **Core may not assume a property of the deployment; Composition affirms
  it.** `CritiqueGate`'s verdict memo needs sampling to be *deterministic*,
  and one adapter (`OpenAICompatible`) covers Ollama, llama.cpp, vLLM and
  OpenRouter — where a pinned seed is best-effort. Layer 1 can check the
  seed mechanically and does; it cannot check the backend, so it refuses to
  guess. `CritiqueGate(deterministic_sampling=...)` defaults **off**, and
  the eval harness — Layer 5, which chose the endpoint — affirms it for
  itself. A library correctness argument that rests on a deployment choice
  the library does not make belongs at the layer that made the choice.
- **A critic paired with a task whose source was withheld is a recipe
  defect, not a gate defect.** RB-P8's guard lives in Layer 5 for that
  reason. Degrading `GroundedCritiqueGate` to pass through on empty
  evidence would have been a Layer-1 change that made every consumer's
  grounded gate defeatable by calling no tools — the opposite of what it is
  attached to do. When the mechanism is behaving correctly and the
  composition is wrong, the composition is what changes.

## What this buys

- **Contract iteration without core risk.** The P2/P4 fixes (tiered
  verdict contract, constrained decoding, answer-repair) edit
  `assets/contracts/` and `contract.py` only; the mechanics that measured
  correct on four models stay untouched.
- **The TS port shrinks.** Layers 2 + 4 are pure asset-pack data, shared
  verbatim across runtimes. A port implements Layers 1 + 3 and whatever
  Layer-5 surface it wants; the words and numbers come from the same
  files this runtime reads.
- **Recalibration becomes explicit.** Changing a budget means editing a
  named profile in a reviewable diff — and `test_layers.py` fails if the
  *default* profile drifts from its documented values without the guard
  being updated deliberately.

## Known debt

- **"Layer 1 imports no `mcp` and touches no filesystem" is a sentence, not an
  assertion.** `test_layers.py::test_core_purity` scans a core module for leaked
  *contract literals*; `test_import_direction` runs over `contract.py` and
  `profile.py` only. Neither one reads a core module's import list, and there is
  no Node counterpart to either — `runtime-ts` has no layer test at all. So the
  purity of `workplan.ts` is true today by inspection (it imports nothing; the
  generated `workplan.py` imports only `_ts2py_runtime` and its shim adds
  `typing.Any`) and would stay green if someone added `import json, pathlib`
  tomorrow. Repo-wide and pre-existing: it
  is the property every Layer 1 row here claims.
- Tool-observation wording is still inline in `filegraph.py` (repeat
  annotations) and `memory/component.ts` (save feedback; runtime-py runs it
  compiled, as `_generated/component.py`). It is
  model-facing, but it measured fine cross-model, so it moves in a later
  contract cycle, not this one.
- The agent↔component protocol is duck-typed and undeclared, so it can
  widen silently. `Memory.setup` now hard-requires `Agent.add_batch_scope`
  (`2dbe162`); nothing states that requirement except the `AttributeError`
  a non-conforming agent would raise. A declared protocol for what a
  component may expect of its agent is Layer-1 work waiting for a second
  component to need it.
- Only the `default` contract and profile exist. Per-model/per-tier
  variants are the P6 work that lands on top of this seam. (P2's tier —
  constrained decoding via `response_format` with a 400-fallback memo —
  shipped in v0.9.0; the tool-argument boundary is covered generically
  by `Agent`'s schema coercion from the same cycle.)
