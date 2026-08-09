# Cross-Model Sweep Design

**Date:** 2026-08-09
**Status:** Approved (user: start the cycle; model set = 3b + 7b + 14b;
prune unused local models)
**Depends on:** file-access-graph (PR #11, v0.7.0)

## 1. Problem

Every measured claim in the docs — the ship-config guidance, the
structured tax, the critique verdicts, the graph rescue — rests on one
model: `qwen3:4b-instruct`. n=1 external validity is the project's
biggest open risk. This cycle re-runs the frozen v0.7.0 suite on three
more models and re-scopes every claim to the models it actually holds on.

## 2. Design decisions

### 2.1 Matrix

8 configs × 22 tasks × 3 repeats = 528 runs per model, on:

| model | axis | source |
|---|---|---|
| `llama3.2:3b` | cross-family, small end | pulled (~2GB) |
| `qwen2.5:7b-instruct` | size up, near-family | local |
| `qwen2.5:14b-instruct` | ceiling reference (outside the 1–8B target band) | local |

= 1,584 new runs, sequential per model in the order 3b → 7b → 14b
(fast signal first). `qwen3:4b-instruct` is the existing reference —
its 2026-08-09 528-run sweep (`2026-08-09-filegraph-sweep.jsonl`) is
reused, not re-run. Evidence: one JSONL per model,
`docs/eval-data/2026-08-09-crossmodel-<slug>.jsonl`. Thinking-model
variants stay excluded (measured impractical for critique configs in the
v1 cycle); `qwen3:4b` (thinking) was deleted locally to free disk.

### 2.2 Rules

- **The suite, rubrics, prompts, and configs are frozen at v0.7.0.** A
  model that fails a rubric or task is a data point, not a bug — no
  per-model tuning, no task edits, no rubric forks. If a harness *defect*
  surfaces (crash, mis-scoring), it gets a normal SDD fix; behavior
  differences do not.
- No version bump — this cycle ships docs + evidence only (same pattern
  as the install-docs PR #6).
- Per-request timeout 180s (14b headroom).

### 2.3 Falsifiable predictions (written before measuring)

1. **Memory transfers:** recall goes ~0/27 storeless → ~27/27 with a
   store on every model. If it does not, the core claim of the project
   needs re-scoping.
2. **Structured tax holds on 7b/14b** (`schema_retries = 0`); 3b is
   exploratory — retries > 0 there would be SchemaGate's first positive
   measurement.
3. **Saturation on the big end:** 7b/14b likely pass file-nav and
   shop-basket-total under `bare`, dissolving the graph/grounded rescues
   into saturation — recorded as scope-of-value (those primitives earn
   their keep at the small end), not as failure.
4. **Critique risk on the small end:** on 3b, critique-family configs
   (`critique`, `grounded`, `full`) risk net-negative score or token
   blowups (the v1 7b smoke showed critique net-negative).
5. **The graph no-op check is structural:** `graph` matches `bare` on
   every off-family cell on every model. A violation would indicate a
   harness defect (see §2.2), not a model difference.

### 2.4 Docs

- `docs/eval.md` gains a `## Cross-model results` section after Current
  results: per-model summary tables (config × score/tokens/score-per-1k),
  a compact per-family view where a family's story differs by model, and
  a **claims-transfer table** — each Recommended-defaults claim × each
  model: holds / partially / does not hold, with the number that decides
  it.
- `README.md` Recommended defaults re-scoped honestly: claims that
  survive all four models stay unqualified; 4b-specific claims get their
  scope named inline.
- The reference (4b) Current results section itself is unchanged — no
  demotion this cycle; cross-model is an addition, not a replacement.

## 3. Testing

No code changes planned → offline suite must simply stay green (240
tests). If a harness defect fix becomes necessary (§2.2), it follows the
normal SDD task + review flow with tests.

## 4. Success criteria

1. 1,584 runs complete; three JSONLs committed under `docs/eval-data/`.
2. Every §2.3 prediction explicitly confirmed or refuted in the docs
   with numbers.
3. Claims-transfer table covers every Recommended-defaults bullet.
4. README claims re-scoped to match the data; CI green.

## 5. Out of scope

- Per-model rubric/task/prompt tuning; suite changes of any kind.
- Model-specific ship configs in code.
- Additional models beyond the four; re-running the 4b reference.
- TS port phase 2.
