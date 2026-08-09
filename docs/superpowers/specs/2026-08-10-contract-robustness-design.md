# Contract Robustness Design (P1 + P2 + P4)

**Date:** 2026-08-10
**Status:** Approved (user-authorized P1–P9 queue). Every fix below is
grounded in transcript diagnosis from the v0.8.1 `--transcripts` probes —
the first products of the measurement-integrity cycle.
**Depends on:** layer separation (v0.8.0), measurement integrity (v0.8.1).

## 1. Problems, as actually measured

Two 27-run seeded probes (`memory` config, 9 recall tasks × 3 repeats,
transcripts on; evidence JSONLs + diagnosis reports committed under
`docs/eval-data/`) overturned both standing hypotheses:

- **P1 on 3b is not "recalls but answers wrong".** 18/27 failures never
  searched the store: `memory_recall` crashed at the argument boundary —
  17× the model sent `k` as the JSON *string* `"10"` and
  `Memory.recall()` died comparing int to str; 1× it omitted `query`.
  6/27 emitted pseudo-tool-calls as prose (never executed). Only 3/27
  were genuine synthesis failures. Retrieval itself was perfect: every
  executed recall returned the needed fact first-hit.
- **P4 on 7b is format abandonment, not broken JSON.** 11/16 failures
  had the *correct* fact in the final message but zero JSON anywhere —
  after recalling correctly, the model detoured into spurious
  `memory_save` calls (5 runs burning turns on `error:` observations
  because the store's name pattern `^[a-z0-9][a-z0-9-]*$` rejects the
  snake_case names it invents), then answered in fluent prose, the
  "ONLY this JSON" instruction a turn too far away. 0 tool-arg errors —
  3b's disease is absent on 7b. Leniency in the extractor would not
  help; the content is right and the JSON is simply missing.
- **P2, verified live:** Ollama's OpenAI-compat endpoint accepts
  `response_format: {"type": "json_schema", ...}` and returns
  schema-compliant output even from 3b. The critic's verdicts —
  `schema-exhausted` ×22/×17 (3b full/grounded), ×15/×10 (7b) in the
  cross-model sweep — can be decode-constrained instead of prompt-begged.
- **Instrumentation gap found by the probes:** runs that die of
  `MaxTurnsExceeded` write transcripts with `messages: []` — the
  exception discards the transcript exactly when it is most needed.

## 2. Design

### 2.1 P1a — tool-argument schema coercion (Layer 1)

`Agent._dispatch` coerces arguments against the tool's declared
parameter schema before calling the handler: for each argument whose
schema type is `integer`/`number`/`boolean` and whose value is a string,
attempt the obvious conversion (`int(v)` / `float(v)` /
`{"true": True, "false": False}` case-insensitive); leave everything
else untouched, and on conversion failure pass the original value
through so today's error path fires unchanged. Well-typed calls are
byte-identical no-ops.

Implementation: a small pure helper `coerce_arguments(arguments: dict,
parameters: dict) -> dict` in `agent.py` (schema walk over
`parameters["properties"]`, top level only — nested objects are out of
scope until a model is measured sending them wrong).

### 2.2 P1b — memory name normalization (Layer 1, store-adjacent)

`Memory.save` normalizes `name` (and `links`) before store validation:
lowercase, `_` and spaces → `-`. The store's validation pattern itself
does not change — the component adapts the model's spelling to the
store's contract, the same direction as P1a. The normalized name is
what the save-result message reports, so the model sees the canonical
form.

### 2.3 P2 — constrained-decoding tier for `structured()` (Layers 2+3)

- **Layer 3:** `OpenAICompatible.chat(...)` gains
  `response_format: dict | None = None` (sent verbatim when set, like
  `seed`). The client also carries a memo
  `self._response_format_unsupported: bool` — when a request with
  `response_format` fails with HTTP 400, the client retries that call
  once without it and memoizes, so later calls skip the tier silently.
  That single 400-retry IS the capability detection: no probe request,
  no server allowlist.
- **Layer 2:** `structured()` becomes tiered. Tier 1: pass
  `response_format={"type": "json_schema", "json_schema": {"name":
  "output", "schema": schema}}` on every attempt. Capability
  duck-typing, same spirit as the seed: a client that understands the
  kwarg exposes the `_response_format_unsupported` attribute
  (`OpenAICompatible` initializes it `False`); `structured()` sends the
  kwarg only when `hasattr(client, "_response_format_unsupported")` and
  it is falsy. Fake clients without the attribute are never sent it. The system instruction and
  parse+validate+retry loop stay exactly as today (tier 2/3): a
  constrained server makes retries rare, an ignoring server changes
  nothing, and validation still gates because `response_format`
  enforcement is only as good as the server. No new wording, so no
  contract-asset change.
- `TrackingClient` passes `response_format` through (its `chat` gains
  the same optional kwarg with default None — fake clients that lack it
  are never sent it, duck-typed at the call site).

### 2.4 P4 — `JsonAnswerGate` (Layer 1 mechanics + contract wording)

New component in `structured.py`: a post-hook (no transcript needed)
that fires only when the final output contains no extractable JSON —
`extract_json` raises — and then returns one pointed feedback from a new
contract template:

```yaml
json_answer_retry: "Your answer contains no JSON. Restate your final answer as ONLY the JSON requested by the task, with no prose around it."
```

One retry per run (`max_attempts` from a new `json_answer` profile
section, default 1); a second JSON-less answer passes through unchanged
(fail-open — the gate must never turn a scorable wrong answer into an
exception; scoring stays the judge). It does not validate against any
schema — that is `SchemaGate`'s job; this gate only rescues the
"content right, JSON missing" mechanism the probe measured.

Eval wiring (Measurement): `memory`, `lean`, and `full` attach
`JsonAnswerGate` for tasks scored `json_equal`. `bare` does not — it
stays the floor. This changes what those config names measure;
recorded honestly in the docs and versioned (v0.9.0), same precedent as
`full` adopting the grounded critic in v0.5.0.

### 2.5 Transcripts survive MaxTurnsExceeded (Core + Measurement)

`MaxTurnsExceeded` gains a `messages` attribute (the transcript up to
the raise); `Agent.run` attaches it. `run_task` uses
`getattr(caught, "messages", [])` as the transcript fallback so
turns-exhausted runs stop writing `messages: []`. (`tool_calls` in the
TaskResult keeps reading 0 for gate-raised runs — existing documented
behavior, unchanged this cycle to keep JSONL semantics stable.)

### 2.6 Measurement bars (before/after, seeded, ≥2 models)

Targeted calibration runs, committed as evidence JSONLs (the probes are
the "before"; same tasks, repeats and now-pinned seeds):

1. **P1a/P1b bar (3b):** `memory` on the 9 recall tasks × 3 — tool-arg
   error observations 18 → 0; passes strictly above the probe's 0/27.
2. **P4 bar (7b):** same cell — malformed-final 11 → ≤3; passes
   strictly above 11/27.
3. **P2 bar (3b + 7b):** `grounded` config, full 22-task suite × 3 —
   `schema-exhausted` outcomes → 0 on both models; score not below the
   cross-model sweep's cell (3b 13/66, 7b 24/66).
4. **No-regression bar (4b, the reference):** `memory` + `full` on the
   full suite × 3 — scores not below 57/66 and 66/66 respectively.
   (4b was already well-typed and JSON-compliant; the gates should be
   no-ops there.)

A bar miss is a measured negative: it gets a problem entry and an
attack plan, not a silent re-scope (standing rule).

### 2.7 Docs + version

`docs/eval.md`: config-matrix note (`JsonAnswerGate` in
memory/lean/full), Measured-problems section updated — P1 reframed with
the probe evidence (root cause: argument-type fragility; the old
recall-but-wrong framing corrected), P4 mechanism named, P2 marked
fixed-pending-resweep, calibration tables for the four bars.
`docs/architecture.md` known-debt list updated (P1a covers the tool
boundary generically). Version **v0.9.0** (new component + config
semantics change), tag, pinned-install verify.

## 3. Testing

Offline (fake clients): coercion table-driven tests (str-int, str-float,
str-bool, non-string passthrough, unknown keys, conversion failure →
original value, no properties → no-op); name normalization cases;
tiered `structured()` (tier-1 kwarg present when supported, absent after
a 400 memo, absent for clients without the kwarg); `JsonAnswerGate`
(fires only on unparseable output, one retry, fail-open second miss,
never fires on parseable-but-wrong JSON); `MaxTurnsExceeded.messages`
present and used by the transcript writer. Live bars per §2.6.

## 4. Success criteria

1. All offline tests green (279 + new), ruff clean, CI green.
2. All four §2.6 bars met, evidence JSONLs committed.
3. Docs updated per §2.7; PR merged (pre-authorized); v0.9.0 tagged;
   pinned install verified.

## 5. Out of scope

- P6 (turn budgets) and P3 (TokenBudget) — next cycle, on top of these
  results.
- Full 528-run re-sweeps per model (a dedicated re-baseline/docs cycle
  after the P-queue lands; targeted bars carry this cycle).
- Nested-object argument coercion; array item coercion.
- Prose pseudo-tool-call rescue (3b's 6/27 — needs its own design;
  recorded as residual in the P1 entry).
- Any rubric, task, or prompt-convention edit; temperature pinning.
- MCP surface changes.
