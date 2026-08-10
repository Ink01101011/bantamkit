# LoopGuard Design

**Date:** 2026-08-10
**Status:** Approved (user-directed queue 2, item 2 — opened after
budget-visibility merged as v0.11.1). Grounded in the 12-run transcript
diagnosis (`loop-diagnosis` probe, 3b graph nav + 7b memory recall under
`patient`).
**Depends on:** the P6 refutation (turns don't convert loops) and the
probe finding that looping is a *tool-observation* phenomenon.

## 1. Measured problem

Models loop by re-calling tools, never by re-stating prose: in 6 looping
runs the model burned 6–16 call no-info tails (byte-identical
observations coming back), while max observation-repeat in every passing
run was 2. Two flavors: identical (tool, args) re-calls (3b), and
paraphrased-args churn where only the observation repeats (7b). Critically,
both 7b turns-exhausted runs already **held the correct answer** while
looping — conversion is sitting there.

## 2. Design

- **`LoopGuard` (Layer 1, new `loopguard.py`)** — tool-wrapping component
  in the FileAccessGraph mold: `setup` wraps every registered tool
  handler; per (tool name), it hashes each observation and counts
  consecutive-identity streaks (keyed on observation bytes, NOT call
  args — the 7b paraphrase churn makes args-identity blind).
- **Two-stage intervention, injection-only** (a component cannot and
  must not stop the agent loop — never swallow a scorable answer):
  - streak hits `inject_at` (default 3): prepend the loop note to the
    observation (prepended, not appended — review finding: an appended
    note is eaten by observation truncation exactly on the oversized
    no-info tails it targets; FileAccessGraph's markers survive for the
    same reason) — "(you have now received this exact result {count}
    times; it will not change. Do something different or give your
    final answer now)".
  - streak hits `warn_at` (default 5): prepend the hard wording —
    "(STOP calling tools. Give your final answer now, in exactly the
    format the task asked for.)".
- Wording = two new contract templates (`loop_note`, `loop_warn` —
  Layer 2 asset); thresholds = new profile section `loop_guard`
  (Layer 4). Counters reset per `setup` (per run) and on any
  non-identical observation from that tool (streaks, not totals — a
  legitimately repeated read later in a long run must not trip it;
  probe data shows streaks are what discriminate). v1 exception-path
  limitation: raising errors and unknown-tool observations do not
  streak — the guard counts only observations produced by tool
  returns, and the wrapper resets that tool's streak on a raise.
- **Eval wiring (Measurement):** calibration-only configs
  `graph-guarded` (= `graph` + LoopGuard) and `memory-guarded`
  (= `memory` + LoopGuard), mirroring the BUDGET_CONFIGS mapping
  pattern. Not in headline CONFIGS.

## 3. Bars (seeded; probes are the before)

1. 3b `graph-guarded`, nav tasks ×3 under `patient`: the injection
   fires on the previously-looping seeds; outcomes reported as measured
   (conversion hoped, honesty first — 3b's flail may resist wording).
2. 7b `memory-guarded`, recall-audit-retention + recall-org-quota ×3
   under `patient`: the two held-answer loops are the conversion
   targets.
3. No-regression: 4b `memory-guarded` full suite ×3 vs the seeded 59/66
   memory cell — expect near-no-op (4b's max streak measured ≤2 ⇒ guard
   silent); any fired injection on 4b is itself a finding.
4. Offline: streak counting (reset on different obs), stage thresholds,
   wording bytes from the asset, wrap-all-tools including late
   registrations? (v1: tools registered after setup are unwrapped —
   documented; eval attaches LoopGuard last so it wraps everything).

## 4. Success criteria

Tests green (447 + new), ruff clean, CI green; bars run and documented in
eval.md (new LoopGuard subsection under the measured-problems narrative,
outcomes reported as measured — conversion hoped, honesty first);
per-layer commits (component / contract asset / profile / measurement);
v0.12.0 (new component + new asset surface, the FileAccessGraph
precedent); PR merged (pre-authorized); tag; pinned install verified.

## 5. Out of scope

Force-finalize (stripping tools / stopping the loop); assistant-prose
repetition detection (measured non-signature); headline adoption;
cross-run memory of loops.
