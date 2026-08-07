# Team-Ready Design

**Date:** 2026-08-07
**Status:** Approved (scope agreed in session; user: "team-ready ต่อ")
**Depends on:** suite-hardening (PR #4, merged to `main` as `ef27603`)

## 1. Problem

Teammates are about to install and run bantamkit as individuals — each person
their own clone or pinned install, their own memory stores, later their own MCP
instance. Nothing is shared. Today the repo assumes its one author: no CI guards
a PR, there is no pinned ref to install from, the README never says which
composition to actually use, and there is no runnable example to start from.

## 2. Deliverables

1. **CI** — GitHub Actions workflow: ruff + full pytest suite on every PR and
   on pushes to `main`, Python 3.11 and 3.12 (declared floor + version in use).
   The suite is offline by design (fake clients); CI needs no model endpoint.
2. **Pinned install** — bump `runtime-py/pyproject.toml` version `0.1.0 →
   0.2.0`; document `pip install "bantamkit @ git+ssh://git@github.com/
   Ink01101011/bantamkit.git@v0.2.0#subdirectory=runtime-py"` in
   `docs/install.md` plus a maintainer "releasing" note (tag on `main` after
   merge). The wheel already bundles the asset pack (`force-include ../assets`),
   so a pinned install needs no `BANTAMKIT_ASSETS`.
3. **README recommended defaults** — a short section stating the measured
   guidance: always attach `Memory`; use `structured()` for schema'd output;
   skip `CritiqueGate` on small instruct models (measured +41% tokens, zero
   extra passes); prefer instruct over thinking variants.
4. **examples/** — three runnable scripts + an examples README, public API
   only, endpoint via `BANTAMKIT_BASE_URL` / `BANTAMKIT_MODEL` env vars
   (defaults: local Ollama, `qwen3:4b-instruct`):
   `01_quickstart.py` (agent + tool + Memory — the measured lean shape),
   `02_structured_extraction.py` (`structured()`),
   `03_layered_memory.py` (`Memory.layered()` — per-person stores).

## 3. Design decisions

- **Branch/PR:** `feat/team-ready` branched off `main` (PR #4 merged first, at
  the user's word, so the README blurb can cite the merged sweep numbers
  without stacking).
- **Lint scope:** package via `ruff check .` from `runtime-py/` (its pyproject
  carries the config); examples via
  `ruff check --config runtime-py/pyproject.toml examples` from repo root.
- **Tag creation** (`v0.2.0`) happens on `main` only after the user's merge
  word — documented, not executed, in this cycle.
- **Verification split:** implementers verify syntax/lint/tests offline; the
  controller smoke-runs all three examples against local Ollama before the PR.

## 4. Success criteria

1. Workflow YAML is valid and its exact commands pass locally (ruff clean on
   both targets, 164 tests pass) on the venv.
2. All three examples run end-to-end against local Ollama and are ruff-clean.
3. README + install docs updated; version is 0.2.0.
4. Release step documented; nothing tagged until the merge word.

## 5. Out of scope

- PyPI publishing, wheel artifacts in CI, coverage, badges, release automation.
- MCP adapter (next phase, own cycle).
- Shared memory stores, locking, grants provisioning (per-person instances).
- `runtime-ts`.
- Any change to eval suite, tasks, or scoring.
