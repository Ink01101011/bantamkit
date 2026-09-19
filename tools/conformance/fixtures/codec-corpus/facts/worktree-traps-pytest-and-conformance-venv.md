---
name: worktree-traps-pytest-and-conformance-venv
description: why pytest and the conformance harness misbehave in a bantamkit git worktree
  — the PYTHONPATH trap and the four test_conformance_harness_resilience failures
  that are not a regression
type: reference
created: '2026-09-18'
last_recalled: null
links:
- feedback-worktree-pytest-tests-mains-source
- feedback-gate-counts-are-co-moving
- exflow-as-shiftwork-dag-measured
---

Measured 2026-09-18 in /Users/kktest/Documents/Claude/Projects/bantamkit/.claude/worktrees/exflow-agent-tools (cut from main 6666d8b). Two traps, both worktree-only, neither a product defect.

1. PYTHONPATH. The repo venv has bantamkit installed pointing at MAIN's source. From a worktree, `.venv/bin/python -c "import bantamkit"` resolves to `/Users/.../bantamkit/runtime-py/src/bantamkit/__init__.py` — main's tree. Every pytest number then describes the wrong tree. Fix, verified both ways: `env PYTHONPATH=<worktree>/runtime-py/src /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -m pytest ...`. (This is the general lesson in [[feedback-worktree-pytest-tests-mains-source]]; what is new here is the exact reproduction and the `env` form the sandbox accepts — an inline `PYTHONPATH=... cmd` prefix gets REFUSED in a worktree-isolated session as too complex to verify, `env VAR=... cmd` is accepted.)

2. FOUR failures in runtime-py/tests/test_conformance_harness_resilience.py, all one cause. The rig hardcodes `REPO = Path(__file__).resolve().parents[2]` and `VENV_PYTHON = REPO/".venv"/"bin"/"python"`, then passes `--python <that path>` EXPLICITLY to run.mjs. A git worktree has no `.venv`, so run.mjs answers "reference interpreter not found". BANTAMKIT_CONFORMANCE_PYTHON does NOT help — an explicit `--python` wins at run.mjs:111. run.mjs ITSELF already handles worktrees (falls back to `git rev-parse --git-common-dir`, its own comment at line 106); only the TEST RIG does not. Symlinking `.venv` into the worktree does not work either: `.gitignore` line 1 is `.venv/` with a trailing slash, which matches a directory and not a symlink, so the symlink shows up as untracked.

BASELINE at 6666d8b in that worktree, after `cd runtime-ts && npm install && npm run build`: pytest `4 failed, 2862 passed, 57 skipped, 2 deselected, 3 xfailed`. WITHOUT the build it is 6 failed — the extra two are test_served_tool_count_records.py, which compares the two launchers and needs runtime-ts/dist to exist. `ruff check runtime-py tools` -> 10 errors, ALL under tools/ (amendguard 2, mutmatrix 3, conformance/ref 5), NONE under runtime-py; CLAUDE.md's ruff command was recently widened from `runtime-py` to `runtime-py tools`, which is what brought them into scope.

Side effects to revert after running the suite in a worktree: `npm install` rewrites runtime-ts/package-lock.json, and the conformance tests append to tools/shiftwork/example-codefix-checkpoint.json.log.jsonl.
