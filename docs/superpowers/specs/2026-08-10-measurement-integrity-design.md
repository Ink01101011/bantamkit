# Measurement Integrity Design (P8 + P7 + P9)

**Date:** 2026-08-10
**Status:** Approved (part of the user-authorized P1–P9 queue; problems and
fix directions ratified in the cross-model docs — eval.md "Measured
problems → attack plan")
**Depends on:** layer separation (PR #13, v0.8.0)

## 1. Problem

Three defects in the measurement harness itself, all measured by the
cross-model sweep, all blocking the diagnosis or verification of the
remaining problems:

- **P8 — no post-hoc transcripts.** `evalrun` discards each run's message
  list after scoring. P1 (3b recalls-but-answers-wrong) cannot be
  diagnosed without reading what the model actually said; today that
  means re-running sweeps with ad-hoc printing.
- **P7 — `MaxTurnsExceeded` counted as `transport-error`.**
  `classify_outcome` maps any unrecognized `BantamError` to
  `transport-error`. All 10 of the 3b sweep's transport-errors are
  literally turn exhaustion — an agent-behavior failure, not
  infrastructure. The taxonomy lies about where the problem is.
- **P9 — no temperature/seed pinning.** Neither `client.py` nor
  `evalrun.py` sends sampling options, so every run samples at the
  server's default temperature with a random seed. Cost already paid:
  the graph-vs-bare exact-equality no-op check degraded to "statistical
  similarity" (8/20, 3/20, 4/20 off-family cell divergences on 3b/7b/14b
  are sampling noise, unfalsifiable against real leakage).

## 2. Design

### 2.1 P8 — `--transcripts DIR` (Measurement only)

- `run_task(...)` gains `transcripts_dir: Path | None = None` and
  `repeat: int = 0`. When set, after scoring (pass or fail, including
  caught `BantamError`s) it writes
  `<transcripts_dir>/<config>--<task>--r<repeat>.json`:

  ```json
  {
    "task": "...", "config": "...", "repeat": 0,
    "passed": false, "outcome": "wrong-answer", "seed": 1234567890,
    "output": "...final answer or null...",
    "messages": [{"role": "...", "content": "...", "tool_calls": [
        {"id": "...", "name": "...", "arguments": {}}],
        "tool_call_id": null}]
  }
  ```

  Message serialization is a small `_message_dict(m)` helper in
  `evalrun.py` (role, content, tool_calls (id/name/arguments),
  tool_call_id — exactly the `Message` fields).
- On the `structured` config path there is no agent transcript
  (documented existing limitation) — the file is still written with
  `messages: []` so tooling can rely on one file per run.
- `run_suite` gains `transcripts_dir` and passes it through with the
  repeat index; `main` gains `--transcripts DIR` (creates the directory,
  `parents=True, exist_ok=True`).
- Failure isolation: transcript writing is wrapped so an I/O error warns
  on stderr and never alters a result (measurement must not change what
  it measures).

### 2.2 P7 — `turns-exhausted` outcome (Measurement only)

In `classify_outcome`, before the generic `error is not None` branch:

```python
    if isinstance(error, MaxTurnsExceeded):
        return "turns-exhausted"
```

(`MaxTurnsExceeded` imported from `bantamkit.agent`.) Additive taxonomy
change: `transport-error` now means transport again. Docs note in
eval.md's outcome list; historical JSONLs keep their recorded values —
the cross-model section already footnotes the mislabel and is not
rewritten.

### 2.3 P9 — deterministic seed per run (Transport + Measurement)

- **Transport:** `OpenAICompatible.__init__` gains `seed: int | None =
  None`; when set, `"seed": self.seed` is added to the request payload
  the same way `tools` is. Nothing else in the client changes. (OpenAI
  chat-completions and Ollama's OpenAI-compat endpoint both accept
  `seed`; servers that ignore it degrade to today's behavior.)
- **Measurement:** `evalrun` computes one seed per (model, task, repeat):

  ```python
  def run_seed(model: str, task_name: str, repeat: int) -> int:
      digest = hashlib.sha256(f"{model}\x1f{task_name}\x1f{repeat}".encode()).digest()
      return int.from_bytes(digest[:4], "big")
  ```

  Stable across processes (no Python `hash()`), 32-bit (safe for every
  server). **Config is deliberately excluded** so all configs of a
  (task, repeat) share the seed — `bare` vs `graph` off-family becomes
  exact-equality-falsifiable again, and config comparisons stop paying a
  sampling-noise tax on the first call of each run.
- `run_task` computes the seed from `getattr(client, "model", "")` +
  task + repeat and applies it with duck-typing: if the client has a
  `seed` attribute (`OpenAICompatible` does after this cycle), set it
  for the run; otherwise skip. The `chat()` signature does not change,
  so every existing fake client in the tests keeps working.
- `TaskResult` gains `seed: int | None` — recorded **only when actually
  applied** (a seed the client ignored would be provenance fiction).
  New trailing JSONL field, additive; old JSONLs simply lack it.
- Temperature stays untouched (out of scope — pinning it changes what
  the suite measures; seed alone restores replayability).
- Honesty bound, documented in eval.md: llama.cpp/Ollama under
  concurrent load is not bit-deterministic even with a seed — the
  invariant is "replayable modulo server nondeterminism", enforced as
  exact equality only when it holds and investigated (not hand-waved)
  when it does not.

### 2.4 Docs

`docs/eval.md`: `--transcripts` in the "Run it" flag list; the outcome
taxonomy list gains `turns-exhausted`; a short "Seeds" note in Reading
the report (what is pinned, what is not, the honesty bound). No re-runs
this cycle — the next sweep (any of P2/P4/P6 verification) exercises the
seeded path and its no-op check.

## 3. Testing

Offline, no server: 
- P8: run a fake-client task with transcripts on → file exists, JSON
  round-trips, fields match the run (incl. a tool-calling task and a
  gate-raising task); I/O failure (unwritable dir) does not change the
  TaskResult.
- P7: a run whose agent raises `MaxTurnsExceeded` classifies
  `turns-exhausted`, not `transport-error`; a genuine `TransportError`
  still classifies `transport-error`.
- P9: `run_seed` golden values (stability across processes is the
  point — hardcode two expected ints); same (task, repeat) across
  configs → same seed; different repeat → different seed; fake client
  asserts `seed` appears in the request payload when set and is absent
  when None; `TaskResult.seed` lands in the JSONL line.
- Suite stays green (257 + new).

## 4. Success criteria

1. All three fixes land with tests; CI green; ruff clean.
2. JSONL line gains `seed`; transcript files appear under
   `--transcripts`; `turns-exhausted` appears in reports where MaxTurns
   fires.
3. v0.8.1 bump (patch: measurement/transport additions, no
   contract/profile/API break), tag, pinned install verified.
4. PR merged (pre-authorized).

## 5. Out of scope

- P1/P2/P4 fixes (next cycle — they consume this cycle's transcripts and
  seeds).
- Temperature pinning; per-model profiles; `options` beyond `seed`.
- Re-running any sweep; rewriting historical JSONLs or their doc tables.
- Server capability detection (P2's tier selection does that).
