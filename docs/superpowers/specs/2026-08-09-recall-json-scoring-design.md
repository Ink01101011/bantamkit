# Recall JSON Scoring Design

**Date:** 2026-08-09
**Status:** Approved (user: start the conversion cycle)
**Depends on:** hardening-v0.5 (PR #9, v0.5.0)

## 1. Problem

All nine memory-recall tasks score with `contains`, so any output containing
the expected term passes — including a model that recalls correctly and then
dumps the entire recalled blob (or the whole store index) instead of
answering. The tasks measure recall but not extraction. This is the
"dump-passes" backlog item recorded in suite-hardening.

## 2. Design decisions

### 2.1 Conversion pattern: prompt-driven JSON, no schema key

Each converted task follows the shop-task pattern already in the suite:

- The prompt's final instruction becomes
  `Answer with ONLY this JSON, nothing else: {"<key>": <placeholder>}`.
- `scoring` becomes `kind: json_equal` with the exact expected object.
- **No `schema` key is added** — `structured`/`lean`/`full` therefore do
  not attach `SCHEMA_INSTRUCTION`/`SchemaGate` to these tasks, and config
  semantics stay comparable across families (json_equal shop tasks already
  work exactly this way).

Target shapes (expected objects, from the seeded facts):

| task | expected |
|---|---|
| recall-audit-retention | `{"days": 400}` |
| recall-cache-ttl | `{"seconds": 240}` |
| recall-db-port | `{"port": 5433}` |
| recall-deploy | `{"command": "make ship-prod"}` |
| recall-env-endpoint | `{"url": "https://api.example-prod.io/v3/reports"}` |
| recall-oncall | `{"name": "Nadia"}` |
| recall-oncall-rotation | `{"name": "Priya"}` |
| recall-org-quota | `{"total": 200}` |
| recall-owner | `{"team": "Atlas"}` |

Everything else in each YAML (memory_setup, the memory-nudge sentence,
family) is unchanged.

### 2.2 Calibration before promotion

Conversions land as `assets/evals/candidates/` copies first. Calibration:
configs `bare`, `memory`, `lean` × 9 candidates × 3 repeats (81 live runs,
qwen3:4b-instruct). Promotion bar per task — stricter than the grounded
cycle because these replace already-stable 3/3 cells:

- `bare` 0/3 (still fails without a store) **and**
- `memory` 3/3 **and** `lean` 3/3 (the conversion introduces no noise).

Promoted conversions overwrite their `assets/evals/tasks/` originals;
failures keep the original `contains` task and are recorded in docs with
their calibration numbers (known brittleness candidates: `deploy`'s command
string, `env-endpoint`'s composed URL, number-vs-string type slips).
Candidates dir is emptied either way.

### 2.3 Offline test updates

Tests that lean on recall tasks' `contains` scoring re-anchor:

- `test_score_contains_case_insensitive` and
  `test_score_contains_allows_punctuation_and_hyphens_around_the_term`
  currently read `recall-owner` / `recall-deploy` — they switch to inline
  task dicts (`score_output` takes a plain dict), keeping the same
  assertions about `contains` semantics.
- `test_run_task_memory_config_seeds_store` (scripted answer
  `"Run make ship-prod."`) updates its scripted final answer to the JSON
  form if `recall-deploy` promotes; its real assertion (the seeded fact
  comes back in the recall observation) is unchanged.
- `test_outcome_critique_exhausted_counts_rounds` (uses `recall-owner`,
  asserts failure) is scoring-agnostic — verify, expect no change.
- Suite floor (≥20 tasks) and family balance are unaffected.

### 2.4 Re-measurement

Full reference sweep after promotion: 7 configs × 20 tasks × 3 repeats =
420 runs, new JSONL under `docs/eval-data/`, Current results rewritten
(current table demoted to the historical section, same as previous cycles).
Expected movement (falsifiable): `memory`/`lean`/`full` recall cells stay
3/3 under the stricter scoring; if instead the family gets noisy, the noisy
tasks stay `contains` (per §2.2 the bar already filters this — the sweep is
the confirmation at scale).

### 2.5 Version

0.6.0 (suite semantics change). Tag `v0.6.0` post-merge on the user's word.

## 3. Testing (offline, in CI)

- The re-anchored `contains` tests (§2.3) pass without referencing recall
  tasks.
- Conformance suite passes with the converted YAMLs (families/floor
  unchanged).
- A new test pins the converted contract for one promoted task: its
  `scoring.kind == "json_equal"` and its prompt contains
  `Answer with ONLY this JSON` (guards against a future edit reverting the
  dump-pass fix silently).

## 4. Success criteria

1. Calibration data decides every task's fate; promoted tasks keep
   bare 0/3 vs memory/lean 3/3 in the full sweep.
2. Offline suite + ruff green in CI.
3. docs/eval.md Current results reflect the new sweep; conversion outcomes
   (including any kept-contains tasks) recorded with numbers.
4. v0.6.0 pinned install verifiable post-merge.

## 5. Out of scope

- New scoring kinds; changes to shop/extract tasks or tool_trace.
- Schema keys on recall tasks (would change config semantics per task).
- TS port phase 2.
