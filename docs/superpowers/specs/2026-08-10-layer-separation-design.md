# Layer Separation Design

**Date:** 2026-08-10
**Status:** Approved (user-directed 2026-08-10: restructure NOW, before the
P1–P9 robustness fixes — the codebase is still small; waiting lets it bloat)
**Depends on:** cross-model sweep (PR #12) — the measurement that localized
every cross-model failure to contract wording/parsing, not core mechanics.

## 1. Problem

The 5-layer model is ratified (core / contract / transport / policy /
composition) but not physical. Layer-2 material — the words the model
reads and the parsing of what it writes — is inlined inside core files,
and Layer-4 tunables are hardcoded constructor defaults, silently
4b-calibrated:

- `structured.py`: the schema instruction (`"Return ONLY a JSON object
  matching this JSON Schema. No prose.\n"`), the retry feedback line, and
  `extract_json` live beside the retry mechanics. The instruction is
  *duplicated* in `evalrun.py` (`SCHEMA_INSTRUCTION`), and the retry line
  is duplicated in `SchemaGate`.
- `critique.py`: the critique feedback wording (`"A reviewer scored your
  answer …/10 … Revise and answer again."`) and evidence rendering
  (`render_evidence`, the `name(args) -> observation` line format and
  `"(no tool calls were made)"`) live beside the round-counting mechanics.
- Tunables `max_turns=10`, `observation_budget=4096`, `max_rounds=3`,
  `max_retries=3`, `max_attempts=3`, `evidence_budget=4096` are scattered
  constructor defaults with no named home.

The P2/P4 fixes must iterate on exactly these strings per model tier.
Landing them before the split means editing core files per contract
change — the leak the cross-model sweep just measured. This cycle makes
the seam physical **with byte-identical behavior** so the fixes land into
separated layers.

## 2. Design

### 2.1 Layer 2 — `contract.py` + `assets/contracts/default.yaml`

New asset `assets/contracts/default.yaml` carries every model-facing
string as data (language-agnostic — the TS port shares it verbatim):

```yaml
name: default
schema_instruction: "Return ONLY a JSON object matching this JSON Schema. No prose.\n"
schema_retry: "{error}\nReturn ONLY a JSON object matching the schema."
critique_feedback: "A reviewer scored your answer {score}/10 (needs >= {threshold}). Feedback: {feedback}\nRevise and answer again."
evidence_line: "{name}({arguments}) -> {observation}"
evidence_empty: "(no tool calls were made)"
```

New module `runtime-py/src/bantamkit/contract.py` (Layer-2 code: loading,
rendering, outbound parsing):

- `load_contract(name="default") -> Contract` (cached; `AssetNotFound` on
  missing, missing-key validation on load)
- `schema_instruction(schema) -> str`, `schema_retry_feedback(error) -> str`,
  `critique_feedback(score, threshold, feedback) -> str`
- `render_evidence(messages, budget=…) -> str` (moves from critique.py)
- `extract_json(text)` (moves from structured.py — outbound parsing is
  Layer 2)

`truncate` (used by both the agent loop's observation budget and evidence
rendering) moves to a new neutral utility module
`runtime-py/src/bantamkit/textutil.py` so `contract.py` never imports
from core; `agent.py` re-exports it (back-compat — `critique.py` and
tests import it from there today).

Core files keep their mechanics and import wording from `contract`:
`structured.py` keeps `structured()`/`StructuredOutputError`; `critique.py`
keeps the gates, `Rubric`, `load_rubric`; `evalrun.py` drops its duplicate
`SCHEMA_INSTRUCTION` and `SchemaGate` retry line in favor of the contract
functions. **Back-compat re-exports stay** (additive rule):
`bantamkit.structured.extract_json`, `bantamkit.critique.render_evidence`,
and the `bantamkit` package root exports keep working.

Exception/exception-message text (`CritiqueExhausted`,
`StructuredOutputError`, tool-dispatch error strings) is *not* moved: the
model never reads exception text — it is measurement/user-facing. Tool
*observation* wording the model does read (`filegraph.py` repeat notes,
memory save feedback) is deliberately left in place this cycle — named
secondary debt, see Out of scope.

### 2.2 Layer 4 — `profile.py` + `assets/profiles/default.yaml`

```yaml
name: default
agent: {max_turns: 10, observation_budget: 4096}
structured: {max_retries: 3}
schema_gate: {max_attempts: 3}
critique: {max_rounds: 3, evidence_budget: 4096}
```

New module `runtime-py/src/bantamkit/profile.py`: `load_profile(name="default")
-> Profile` (cached, validated). Components resolve defaults through it:
constructor signatures change from `max_turns: int = 10` to
`max_turns: int | None = None`, resolving `None` from the default profile
at construction. **Explicit arguments always win**; the default profile
carries exactly today's values, so behavior is byte-identical. The asset
comment marks the values as 4b-calibrated (the honest state the sweep
measured). Transport tunables (`client.py` timeout/retries) stay where
they are — Layer 3 config was never 4b-calibrated and is out of scope.

### 2.3 Measurement — boundary regression tests

New `runtime-py/tests/test_layers.py`, the boundary keeper made
executable:

1. **Golden byte-identity:** every rendered contract string equals the
   pre-split literal, hardcoded in the test (e.g.
   `schema_instruction(s) == "Return ONLY a JSON object matching this
   JSON Schema. No prose.\n" + json.dumps(s)`). This is the proof the
   refactor changed zero prompt bytes.
2. **Core purity:** read the source of `agent.py`, `structured.py`,
   `critique.py`, `evalrun.py`; assert the moved fragments
   (`"Return ONLY"`, `"A reviewer scored"`, `"(no tool calls"`) no longer
   appear there.
3. **Import direction:** `contract.py` and `profile.py` import nothing
   from `agent`/`critique`/`structured`/`evalrun` (source-scan) — the
   contract can change without core noticing, never the reverse.
4. **Profile guard:** the default profile's values equal the documented
   pre-split defaults — a silent recalibration fails the suite.

### 2.4 Docs + versioning

- New `docs/architecture.md`: the ratified 5-layer model, what lives
  where after this cycle (files/assets per layer), the no-mixing rule,
  and the measurement-as-boundary-keeper role. README gets a one-line
  pointer.
- Version bump to **v0.8.0** + tag (new public module + two new asset
  directories = new surface), pinned-install verification per the usual
  gate.

### 2.5 Commit discipline

One commit per layer, per the no-mixing rule: (1) Layer 2 extraction,
(2) Layer 4 extraction, (3) Measurement tests, (4) docs/version. A core
file appearing in commits 1–2 only loses literals and gains imports.

## 3. Testing

- All 240 existing tests must pass **unmodified** — any test edit means
  behavior moved, which fails the cycle's byte-identical bar.
- New `test_layers.py` per §2.3 (golden / purity / import-direction /
  profile-guard) plus unit tests for `load_contract`/`load_profile` error
  paths (missing asset, missing key).
- No eval re-runs: byte-identical prompts + unchanged defaults mean the
  existing sweeps remain valid evidence. (A behavior diff would show up
  as a golden-test failure long before an eval could.)

## 4. Success criteria

1. 240 existing tests green unmodified; new layer tests green; ruff
   clean; CI green.
2. `grep` finds no model-facing literal in core modules (enforced
   permanently by the purity test).
3. `assets/contracts/default.yaml` + `assets/profiles/default.yaml`
   exist; TS-port surface for Layers 2+4 is now pure data.
4. PR merged (pre-authorized), v0.8.0 tagged, pinned install verified.

## 5. Out of scope

- Tiered/tolerant contracts and constrained decoding — that is P2's
  cycle; this cycle only builds the seam it lands into.
- Per-model contracts or profiles — only `default` ships.
- Tool-observation wording in `filegraph.py` / `memory/component.py`
  (model-facing but proven cross-model in the sweep; recorded as
  secondary debt for a later contract cycle).
- Layer-3 (`client.py`) tunables and capability detection — P9/P2 work.
- Any behavior change, any prompt-byte change, any default-value change.
- TS port, MCP surface changes, eval suite changes.
