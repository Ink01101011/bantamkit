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
| **1 — Core** | deterministic mechanics, proven cross-model: agent loop, gate control flow, memory store, filegraph ledger/cache, token accounting | `agent.py`, `memory/`, `filegraph.py`, gate mechanics in `critique.py` / `structured.py`, `textutil.py` |
| **2 — Contract** | everything the model reads or writes: instruction/feedback/evidence wording (data) + outbound parsing (code) | `contract.py` + `assets/contracts/`; rubrics, skills, tool schemas in `assets/` |
| **3 — Transport** | wire protocol, retries, timeouts, (future) server capability detection | `client.py` |
| **4 — Policy/Profile** | tunables as named data: turn budgets, retry caps, evidence budgets | `profile.py` + `assets/profiles/` |
| **5 — Composition** | user-owned recipes: `Agent.use(...)`, eval configs (`lean`/`full` are named compositions), the MCP server | `mcpserver.py`, `examples/`, eval config wiring |

**Measurement** is not a product layer — it is the boundary keeper:
`evalrun.py` produces the evidence, the claims-transfer table in the eval
docs is the regression test that contract hasn't leaked into core, and
`tests/test_layers.py` enforces the boundary mechanically (golden
byte-identity for every contract string, core-purity scan, import
direction, profile-value guard). New primitives must measure uplift on
more than one model before promotion.

## How the layers interact

Core imports wording from `contract` and numbers from `profile` — never
the reverse (`test_layers.py::test_import_direction` fails the suite if
`contract.py` or `profile.py` ever imports core). Constructor arguments
always win over profile defaults; `None` means "resolve from the default
profile". The default profile ships today's values, which are
4b-calibrated — that calibration is now *named data with a comment saying
so* instead of silent constants.

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

- Tool-observation wording is still inline in `filegraph.py` (repeat
  annotations) and `memory/component.py` (save feedback). It is
  model-facing, but it measured fine cross-model, so it moves in a later
  contract cycle, not this one.
- Only the `default` contract and profile exist. Per-model/per-tier
  variants are the P2 and P6 work that lands on top of this seam.
