# Recall JSON Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-anchor the five offline tests broken by the recall json_equal promotion, pin the converted contract, bump 0.6.0.

**Architecture:** The task-file conversion and calibration are controller work (already committed with evidence). This plan is the one code task: tests + version.

**Tech Stack:** Python 3.11+, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-recall-json-scoring-design.md`.
- All nine recall tasks now score `json_equal` with prompts ending `Answer with ONLY this JSON, nothing else: {...}` — already on the branch; do not modify task YAMLs.
- `contains`-semantics tests must keep asserting the same semantics (case-insensitivity, punctuation boundaries, digit-grouping rejection) — re-anchored on inline task dicts, not on suite tasks.
- Version bumps to `0.6.0` in `runtime-py/pyproject.toml`.
- Line length 100; ruff clean; tests via `.venv/bin/python -m pytest` from repo root `/Users/kktest/Documents/Claude/Projects/bantamkit`.
- Conventional commits ending with a blank line then `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Re-anchor offline tests; pin the converted contract; bump 0.6.0

**Files:**
- Modify: `runtime-py/tests/test_evalrun.py`
- Modify: `runtime-py/pyproject.toml`

**Interfaces:**
- Consumes: `score_output(task: dict, output, messages)` accepts a plain dict — only `task["scoring"]["kind"]` and `["expected"]` are read by the `contains` path.
- Produces: nothing new — tests only.

- [ ] **Step 1: Confirm the five failures**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py -q`
Expected: exactly these FAIL — `test_score_contains_case_insensitive`, `test_score_contains_allows_punctuation_and_hyphens_around_the_term`, `test_score_contains_rejects_comma_grouped_superstrings`, `test_outcome_wrong_answer_for_contains_task`, `test_run_task_memory_config_seeds_store`.

- [ ] **Step 2: Re-anchor the three contains-semantics tests on inline dicts**

Replace their bodies (same names, same assertions, no suite-task dependency):

```python
def contains_task(expected):
    return {"scoring": {"kind": "contains", "expected": expected}}


def test_score_contains_case_insensitive():
    task = contains_task(["atlas"])
    assert score_output(task, "It is owned by Team ATLAS.", []) is True
    assert score_output(task, "no idea", []) is False


def test_score_contains_matches_on_word_boundaries_not_substrings():
    """`100` inside `1000` is a wrong answer, not a pass."""
    task = contains_task(["100"])
    assert score_output(task, "The total stock value is 100.", []) is True
    assert score_output(task, "The total stock value is 1000", []) is False
    assert score_output(task, "It is 4100 in total", []) is False
    assert score_output(task, "100.50 dollars", []) is True  # `.` is not a word character


def test_score_contains_allows_punctuation_and_hyphens_around_the_term():
    task = contains_task(["ship-prod"])
    assert score_output(task, "Run `make ship-prod` from the root.", []) is True
    assert score_output(task, "Run make ship-production.", []) is False


def test_score_contains_rejects_comma_grouped_superstrings():
    task = contains_task(["200"])
    assert score_output(task, "The quota is 200 requests per minute.", []) is True
    assert score_output(task, "It handles 1,200 requests per minute.", []) is False
    assert score_output(task, "About 200, give or take.", []) is True
```

Note: `test_score_contains_matches_on_word_boundaries_not_substrings` currently uses `get_task("shop-total")`, which still scores `contains` — converting it to the inline dict anyway makes every contains-semantics test suite-independent in one sweep. Keep its docstring's meaning.

- [ ] **Step 3: Fix the outcome test with a still-`contains` suite task**

```python
def test_outcome_wrong_answer_for_contains_task(tmp_path):
    result = run_task(
        FakeClient([assistant(content="I have no idea what the total is")]),
        get_task("shop-total"),
        "bare",
        tmp_path,
    )
    assert result.passed is False and result.outcome == "wrong-answer"
```

(`shop-total` keeps `contains` scoring; a non-JSON wrong answer must classify `wrong-answer`, not `malformed-output` — that split is what this test exists to pin.)

- [ ] **Step 4: Update the memory-seeds test's scripted answer**

In `test_run_task_memory_config_seeds_store`, change the second scripted response `assistant(content="Run make ship-prod.")` to `assistant(content='{"command": "make ship-prod"}')`. Every assertion stays: `result.passed is True`, and the recall observation still contains `[deploy-command]` and `make ship-prod`.

- [ ] **Step 5: Pin the converted contract**

Add (top-level `import pytest` if the file lacks it):

```python
RECALL_TASKS = [
    "recall-audit-retention",
    "recall-cache-ttl",
    "recall-db-port",
    "recall-deploy",
    "recall-env-endpoint",
    "recall-oncall",
    "recall-oncall-rotation",
    "recall-org-quota",
    "recall-owner",
]


@pytest.mark.parametrize("name", RECALL_TASKS)
def test_recall_tasks_score_json_equal(name):
    """Dump-the-store answers must not pass: recall tasks demand an exact JSON answer."""
    task = get_task(name)
    assert task["scoring"]["kind"] == "json_equal"
    assert "Answer with ONLY this JSON" in task["prompt"]
```

- [ ] **Step 6: Bump version**

`runtime-py/pyproject.toml`: `version = "0.5.0"` → `version = "0.6.0"`.

- [ ] **Step 7: Full suite + ruff**

Run: `.venv/bin/python -m pytest runtime-py -q && .venv/bin/python -m ruff check runtime-py`
Expected: all pass (206 + 9 new − net per collection), ruff clean.

- [ ] **Step 8: Commit**

```bash
git add runtime-py/tests/test_evalrun.py runtime-py/pyproject.toml
git commit -m "test(eval): re-anchor contains-semantics tests inline; pin recall json_equal contract; bump 0.6.0"
```

---

## Controller-run measurement (after Task 1)

Full reference sweep 7 × 20 × 3 = 420 runs → `docs/eval-data/2026-08-09-recall-json-sweep.jsonl`; rewrite eval.md Current results (demote previous table to historical), record the conversion outcome; final review; PR.
