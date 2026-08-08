# Grounded Critique Design

**Date:** 2026-08-09
**Status:** Approved (evidence = tool call/observation pairs; additive gate; eval re-measurement in scope)
**Depends on:** MCP adapter (PR #7, v0.3.0)

## 1. Problem

The measured gap from suite-hardening: `CritiqueGate`'s critic sees only
`(task, output)`. It cannot verify tool-derived facts. In calibration the
model answered `total: 247` / `212` on shop-basket-total (true 131) and the
critic accepted every wrong answer — zero critique-exhausted, zero rescues.
Both tool-arithmetic candidates were dropped as non-discriminating: nothing
in the toolkit could catch an answer that contradicts the tool evidence.

Mechanically: `Agent.run()` holds the transcript (`messages`, including
`role="tool"` observations) at the `_first_feedback` call site but never
passes it to post-hooks, whose contract is `Callable[[str, str], str | None]`.

## 2. Goal

A critique gate that sees the tool evidence, so the critic can check the
answer against what the tools actually returned — and a re-measurement
showing whether that closes the measured gap.

## 3. Design decisions

### 3.1 Evidence plumbing (additive, no breakage)

- `Agent.run()` passes `messages` into `_first_feedback`.
- `_first_feedback` calls hooks that declare a class/instance attribute
  `wants_transcript = True` as `hook(task, output, messages)`; every other
  hook keeps the existing `hook(task, output)` call. Plain `getattr`
  dispatch — no signature inspection.
- `_post_hooks` annotation loosens to `Callable[..., str | None]`.
- Existing hooks (`SchemaGate`, `CritiqueGate`, user hooks) are untouched
  and keep working.

### 3.2 Evidence rendering: tool pairs only

The critic sees tool call/observation pairs, not the full transcript —
targets exactly the measured failure (tool-derived facts) without flooding a
small critic model with assistant chatter.

- Module-level `render_evidence(messages, budget=4096) -> str` in
  `critique.py`: for each `ToolCall` in assistant messages, pair it with the
  `role="tool"` message matching its `tool_call_id`; one line per pair:
  `price_lookup({"item": "widget"}) -> widget: 25`
  (name, JSON args via `json.dumps`, observation text; a call with no
  matching observation renders `-> (no observation)`).
- No tool calls in the run → returns `(no tool calls were made)`.
- Result truncated with the existing `agent.truncate()` at `budget` bytes
  (same marker behavior as observation truncation).

### 3.3 `GroundedCritiqueGate`

New class in `critique.py`, subclassing `CritiqueGate` — the existing gate
is not modified in behavior:

- `CritiqueGate.__call__` body moves to a `_judge(self, **fields)` helper
  (format prompt with fields → `structured()` → threshold / rounds /
  feedback logic, identical strings). `CritiqueGate.__call__(task, output)`
  becomes `return self._judge(task=task, output=output)`.
- `GroundedCritiqueGate(rubric="grounded-completion", client=None,
  max_rounds=3, evidence_budget=4096)`; class attribute
  `wants_transcript = True`.
- `__call__(task, output, messages)` → `self._judge(task=task,
  output=output, evidence=render_evidence(messages, self.evidence_budget))`.
- Grounded rubrics must contain `{evidence}` in addition to
  `{task}`/`{output}`; `GroundedCritiqueGate.__init__` validates this and
  raises `BantamError` naming the missing placeholder. (`load_rubric` stays
  as-is; extra placeholders are legal for plain rubrics.)
- `rounds_used` / `CritiqueExhausted` semantics inherited unchanged, so
  eval instrumentation (`critique_rounds`, `critique-exhausted` outcome)
  works without changes.

### 3.4 Rubric asset

`assets/rubrics/grounded-completion.yaml` — threshold 7, same score/feedback
schema as `task-completion`. Prompt keeps the content-only stance (no format
pedantry, refusals score 0-4) and adds the grounding instruction: the tool
evidence is the ground truth; recompute any numbers from the evidence; if
the answer contradicts the evidence, score 0-4 and state the correct values
from the evidence in the feedback. Contains `{task}`, `{evidence}`,
`{output}`.

The rubric is automatically served by the MCP server as
`bantamkit://rubrics/grounded-completion` — no MCP changes.

### 3.5 Eval config

- `CONFIGS` gains `"grounded"` after `"critique"`:
  `["bare", "structured", "critique", "grounded", "memory", "lean", "full"]`.
- `run_task`: `config == "grounded"` wires
  `GroundedCritiqueGate("grounded-completion", client=tracking)` — gate
  only, the same position `critique` occupies, so critique-vs-grounded
  isolates the evidence effect. `full` keeps the blind gate this cycle
  (additive; whether `full` should switch is a question for the sweep data).
- Restore the two dropped tool-arithmetic candidates verbatim from git
  history (`41832df`) into `assets/evals/candidates/`: `shop-basket-total`
  (price_lookup, expected total 131) and `shop-restock` (stock_lookup,
  expected sprocket/17). Fixtures already carry doohickey and sprocket.

### 3.6 Version

Bump to 0.4.0 in this cycle; tag `v0.4.0` post-merge on the user's word,
same release flow as v0.3.0.

## 4. Measurement plan (controller runs live, qwen3:4b-instruct)

1. **Calibration:** candidates dir × configs `bare`, `critique`, `grounded`
   × 3 repeats. Promotion bar (same shape as suite-hardening): a candidate
   promotes when bare fails ≥2/3 **and** grounded passes ≥2/3; `critique` is
   the control showing evidence, not extra rounds, makes the difference.
2. **Promote or record:** promoted tasks move into `assets/evals/tasks/`
   (candidates dir emptied). If grounded does not rescue, tune the rubric
   once, re-calibrate; if it still fails, drop the candidates again and
   record the measured negative in docs — same tune-once-then-drop rule as
   before.
3. **Reference sweep:** all 7 configs × final suite × 3 repeats; update
   docs/eval.md Current results (headline, rescue matrix, discriminating
   count) and append evidence JSONL under docs/eval-data/.

## 5. Testing (offline, in CI)

- `render_evidence`: single pair, multiple pairs across turns, no tool
  calls, missing observation, truncation at budget.
- Grounded rubric validation: rubric without `{evidence}` raises
  `BantamError` naming it.
- `GroundedCritiqueGate` with a fake client: above threshold → `None`;
  below → feedback string (identical format to `CritiqueGate`);
  `CritiqueExhausted` after `max_rounds`; `rounds_used` counts.
- Plumbing: a `wants_transcript` hook receives the transcript containing
  the `role="tool"` observations; a plain 2-arg hook alongside it still
  works; existing `CritiqueGate` behavior unchanged.
- Eval wiring: `grounded` in `CONFIGS`; `run_task` on a fake client uses
  the grounded gate and reports `critique_rounds`.
- Asset conformance: `grounded-completion.yaml` loads via `load_rubric`,
  threshold 7, contains all three placeholders.

## 6. Docs

- `docs/usage.md`: GroundedCritiqueGate section (when to prefer it over
  CritiqueGate, evidence_budget, rubric contract incl. `{evidence}`).
- `docs/eval.md`: `grounded` config row in the config table; Current
  results updated from the sweep.
- README: one line in the components list.

## 7. Success criteria

1. Offline suite (existing 185 + new tests) passes in CI; ruff clean.
2. Existing hooks and `CritiqueGate` behavior byte-identical (no changed
   feedback strings, no signature breaks).
3. Calibration answers the measured question: either the tool-arithmetic
   tasks promote (grounded rescues what critique cannot) or the negative is
   recorded honestly in docs after one rubric tune.
4. docs/eval.md Current results reflect the post-change sweep with evidence
   JSONL committed.

## 8. Out of scope

- Changing `CritiqueGate`'s critic or `full`'s gate choice (data first).
- Full-transcript evidence mode, deterministic recompute hooks.
- MCP changes (rubric resource is automatic).
- Retry budgets, LLM-judge scoring semantics, TS port.
