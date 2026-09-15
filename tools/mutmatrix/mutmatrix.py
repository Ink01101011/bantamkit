#!/usr/bin/env python3
"""Run a whole mutation matrix in ONE invocation, and report it as N of M.

WHY THIS EXISTS. Red-demonstration discipline says a node that cannot be reddened is
not a test, so every unit here reports mutations as `N of M`. Done by hand that is
three tool calls per mutation — apply, run, revert — plus a fourth to prove the tree
came back clean. Sixteen units across two jobs spent 826 tool calls at a measured
~2,514 tokens each, and roughly 40 of those mutations were run one call at a time.

`tools/pinharness/pinned.py` already batches, but only for the exit-status contract
ledger and only in its own schema. This is the same loop with nothing contract-specific
in it: hand it any list of edits and it applies, runs, reverts and reports each one.

    mutmatrix.py run spec.json                 # whole matrix
    mutmatrix.py run spec.json --only M2,M4    # iterate on two
    mutmatrix.py check spec.json               # anchors only, no pytest, milliseconds

THREE REFUSALS, EACH BECAUSE THE ALTERNATIVE IS A LIE.

  * A RED BASELINE stops everything. "This mutation was caught" is unreadable when
    something was already failing, and the run would attribute a pre-existing failure
    to whichever edit happened to be applied.
  * AN ANCHOR THAT DOES NOT MATCH EXACTLY ONCE stops everything, before any edit. Zero
    is the stale anchor `#64` left in the pinharness ledger, where the sweep would have
    reported `UNPINNED` for a claim it never tested. Two or more is quieter and worse:
    `str.replace` rewrites every site, so the mutation under test stops being the
    mutation the spec describes.
  * A DIRTY TREE AFTER A REVERT stops everything. A mutation that leaves the worktree
    modified poisons every later row, and a cross-unit collision earlier in this
    programme did exactly that for eight consecutive runs before anyone noticed.

WHAT A ROW MEANS. `RED` is not "the suite failed" — it is "at least one node failed AND
the run collected". A non-zero exit with an empty FAILED list is `BROKEN`: an import
error or a syntax error, a tree that never ran, and counting it as caught is how a
mutation gets credit for breaking the build rather than for being detected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

RED, GREEN, BROKEN = "RED", "GREEN", "BROKEN"
FAILED_LINE = re.compile(r"^FAILED (\S+)", re.M)
ERROR_LINE = re.compile(r"^ERROR (\S+)", re.M)
# An ANSI CSI sequence (`ESC[31m`, `ESC[0m`, ...). Stripped from the child's stdout BEFORE
# anything is parsed: with `FORCE_COLOR` / `PY_COLORS` in the environment, or `--color=yes`
# in a spec's pytest_args, pytest writes `ESC[31mFAILED ESC[0m node`, `^FAILED ` matches
# nothing, and a caught mutation is reported BROKEN. Stripping on the READ side rather than
# asking the child for `--color=no` or scrubbing its env is deliberate: the child's args are
# the spec author's and its env is the one the suite under mutation runs in, so neither is
# this tool's to change. Uncoloured output contains no ESC byte, so it parses exactly as it
# did before.
ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class Mutation:
    label: str
    path: str
    anchor: str
    replacement: str
    why: str = ""
    expect: str = RED  # a control row declares GREEN and is not a failure when it is


def _load(spec: Path) -> tuple[list[Mutation], list[str]]:
    doc = json.loads(spec.read_text(encoding="utf-8"))
    muts = [Mutation(**m) for m in doc["mutations"]]
    return muts, list(doc.get("pytest_args") or ["runtime-py/tests", "-q", "--no-header"])


def _anchor_counts(repo: Path, muts: list[Mutation]) -> list[str]:
    problems = []
    for m in muts:
        target = repo / m.path
        if not target.is_file():
            problems.append(f"{m.label}: {m.path} does not exist")
            continue
        n = target.read_text(encoding="utf-8").count(m.anchor)
        if n != 1:
            problems.append(f"{m.label}: anchor appears {n}x in {m.path} (must be exactly 1)")
    return problems


def _porcelain(repo: Path) -> str:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        capture_output=True, text=True, encoding="utf-8", check=False,
    ).stdout
    return "\n".join(row for row in out.splitlines() if not row.startswith("??")).strip()


def _pytest(repo: Path, args: list[str], env_python: str) -> tuple[str, list[str], str]:
    """Run pytest with a FRESH bytecode cache, and split ERROR from FAILED.

    THE CACHE IS NOT AN OPTIMISATION HERE, IT IS A CORRECTNESS BUG. CPython invalidates a
    `.pyc` on (mtime, size). A mutation whose replacement is the SAME LENGTH as its
    anchor — `n * 2` to `n * 3`, the most natural kind to write — leaves both unchanged
    when the edit lands inside one filesystem mtime tick, so the interpreter reuses the
    stale bytecode and RUNS THE UNMUTATED CODE. The row then reads GREEN, and a mutation
    that was never applied is reported as one nothing caught. Measured directly: the same
    rig gives GREEN for `n * 2` -> `n * 3` and RED for `n * 2` -> `n * 33`.

    A per-invocation `PYTHONPYCACHEPREFIX` puts every run's cache in its own directory, so
    there is never a prior entry to reuse. `PYTHONDONTWRITEBYTECODE` alone would not do
    it: it stops writing, not reading, and the stale entry is already on disk.

    ERROR and FAILED are counted apart because they mean different things. A node that
    FAILED ran and disagreed. A file that ERRORed never ran — a syntax error or a bad
    import — and crediting the mutation with that is giving it a mark for breaking the
    build rather than for being detected.
    """
    cache = tempfile.mkdtemp(prefix="mutmatrix-pyc-")
    env = dict(os.environ)
    env["PYTHONPYCACHEPREFIX"] = cache
    # Pin the child pytest's stdout codec: on Windows the locale codec would encode this
    # module's own em dashes as cp1252, the decode below would raise inside subprocess's
    # daemon reader thread, and communicate() would hand back stdout=None.
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        done = subprocess.run(
            [env_python, "-m", "pytest", *args], cwd=repo, env=env,
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    stdout = ANSI_CSI.sub("", done.stdout)
    lines = [row for row in stdout.strip().splitlines() if row.strip()]
    tail = lines[-1] if lines else "(pytest produced no output)"
    failed = FAILED_LINE.findall(stdout)
    errored = ERROR_LINE.findall(stdout)
    if done.returncode == 0:
        return GREEN, [], tail
    if failed:
        return RED, failed, tail
    return BROKEN, errored, tail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("run", "check"))
    ap.add_argument("spec", type=Path)
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--only", help="comma-separated labels")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    muts, pytest_args = _load(args.spec)
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        muts = [m for m in muts if m.label in want]
        missing = want - {m.label for m in muts}
        if missing:
            print(f"no such mutation(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    if not muts:
        print("the spec selects no mutations; 0 of 0 would read as 100%", file=sys.stderr)
        return 2

    problems = _anchor_counts(args.repo, muts)
    if problems:
        print("the spec is stale before anything ran:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    if args.action == "check":
        print(f"OK — {len(muts)} anchor(s) each match exactly once")
        return 0

    dirty = _porcelain(args.repo)
    if dirty:
        print(f"the worktree is dirty before the sweep:\n{dirty}", file=sys.stderr)
        return 1

    verdict, _f, base_tail = _pytest(args.repo, pytest_args, args.python)
    if verdict != GREEN:
        print(f"BASELINE IS NOT GREEN: {base_tail}", file=sys.stderr)
        print("Every 'this was caught' row would be unreadable.", file=sys.stderr)
        return 1
    print(f"baseline: {base_tail}", flush=True)

    rows = []
    for m in muts:
        target = args.repo / m.path
        original = target.read_text(encoding="utf-8")
        target.write_text(original.replace(m.anchor, m.replacement, 1), encoding="utf-8")
        started = time.monotonic()
        got, failed, tail = _pytest(args.repo, pytest_args, args.python)
        target.write_text(original, encoding="utf-8")
        left = _porcelain(args.repo)
        rows.append({
            "label": m.label, "verdict": got, "expected": m.expect,
            "as_expected": got == m.expect, "failed_nodes": failed,
            "tail": tail, "seconds": round(time.monotonic() - started, 1),
            "clean_after_revert": not left, "why": m.why,
        })
        flag = "" if got == m.expect else f"  <-- EXPECTED {m.expect}"
        print(
            f"  {got:<6} {m.label:<8} {len(failed):>3} node(s)  {tail[:44]:<44}{flag}",
            flush=True,
        )
        if left:
            print(f"STOPPING: {m.label} left the tree dirty:\n{left}", file=sys.stderr)
            return 1

    must = [r for r in rows if r["expected"] == RED]
    ok = sum(1 for r in must if r["verdict"] == RED)
    controls = len(rows) - len(must)
    extra = "" if not controls else f" ({controls} declared control row(s))"
    print(f"\n{ok} of {len(must)} must-be-red mutations were caught{extra}")
    broken = [r["label"] for r in rows if r["verdict"] == BROKEN]
    if broken:
        print(
            "BROKEN (non-zero exit, empty FAILED list — the tree did not run): "
            + ", ".join(broken)
        )
    if args.out:
        args.out.write_text(
            json.dumps({"baseline": base_tail, "rows": rows}, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.out}")
    return 0 if ok == len(must) and not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
