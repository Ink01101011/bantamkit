---
name: feedback-worktree-pytest-tests-mains-source
description: running pytest from a bantamkit worktree silently tests main's source,
  not the worktree's - set PYTHONPATH or every number is about the wrong tree
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-18'
links: []
---

In bantamkit, `.venv/bin/python -m pytest runtime-py -q` run from a `git worktree`
executes **that worktree's tests against the MAIN checkout's source**.

    .venv/lib/python3.12/site-packages/_editable_impl_bantamkit.pth
      -> /Users/kktest/Documents/Claude/Projects/bantamkit/runtime-py/src

and `runtime-py/tests/conftest.py` inserts nothing into `sys.path`. The editable
install hard-points at main. The fix is
`PYTHONPATH=<worktree>/runtime-py/src .venv/bin/python -m pytest ...`.

**Why:** this fails silently and plausibly. Tests come from the worktree, source comes
from main, and the run reports a normal-looking pass count. It is invisible unless a
traceback happens to print a `../bantamkit/runtime-py/src/...` path. Worse, the static
AST gates use `REPO_ROOT = Path(__file__).resolve().parents[2]`, so *they* always scan
the correct tree — the hybrid is partly right, which is why it survives review. I
reported "1609 passed on the trial branch" from such a run; the real number under
`PYTHONPATH` was different, and a merge had landed 10 failures the wrong-source run
could not see.

**How to apply:** every brief that asks a unit to measure the suite in a worktree must
name `PYTHONPATH=<worktree>/runtime-py/src` explicitly. When a unit reports a suite
number from a worktree, ask which source tree it ran against before believing it. This
is the same rule as [[feedback-verify-against-the-run-not-the-source]] pointed one level
lower: it is not enough to run it, you have to know what "it" was. Related:
[[feedback-gate-counts-are-co-moving]], [[project-job31-windows-fixes]].
