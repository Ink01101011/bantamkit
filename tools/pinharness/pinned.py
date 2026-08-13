"""Measure what fraction of the exit-status contract's claims are actually PINNED.

A claim is PINNED when a mutation that makes it false turns at least one node red.
Anything else is a sentence the suite would keep green while it became a lie.

This is the instrument behind the ">80% measurable" target. It reports two numbers,
separately and on purpose:

  behaviour-pinned   the claim is about what the tool DOES, and breaking the doing
                     is caught. This is the number that matters.
  prose-pinned       the claim is a committed sentence, and deleting or reversing
                     the SENTENCE is caught. Weaker: a prose guard can be green
                     while the behaviour it describes is broken, and K4 demonstrated
                     exactly that (renaming `parser.error` silenced the epilog check).

Two hazards this harness exists to avoid, both hit for real in job 10:

  1. A `git worktree` does NOT isolate this suite. `bantamkit` is installed editable
     against the MAIN repo, so pytest inside a worktree imports the MAIN tree's
     module and in-process nodes silently test unmutated source. PYTHONPATH is
     pinned to the worktree's runtime-py/src for every run, and a self-test asserts
     the pin took effect before any measurement is believed.
  2. A `.replace()` that matched nothing looks exactly like a fix that works. Every
     mutation asserts its anchor is present EXACTLY once and that the file changed.

CALIBRATE BEFORE YOU BELIEVE IT. `calibration.json` is not a measurement — it is two
mutations whose answer was already known, taken by hand at `3981efd`: one that MUST come
back red (restoring the old unqualified epilog claim, which the roster node catches) and
one that MUST come back green (K4's I7 attack, the full three-edit restoration, which
nothing caught there). An instrument that has not been shown to distinguish a pinned
claim from an unpinned one is not evidence about either, so run it on that commit first
and check both answers; if either flips, the harness is broken and nothing it says about
any other claim may be believed. (At `ff58237` CAL-GREEN comes back PINNED, and that is
the fix landing, not the calibration passing — calibrate on `3981efd`.)

Usage, from the repo root:
    .venv/bin/python tools/pinharness/pinned.py . 3981efd tools/pinharness/calibration.json
    .venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/contract-ledger.json \
        --out /tmp/ledger.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class MutationError(RuntimeError):
    """Raised when a mutation did not apply. Never swallowed: a mutation that did
    not apply produces a green run that means nothing, which is worse than a crash."""


@dataclass
class Claim:
    cid: str
    kind: str  # "behaviour" | "prose"
    claim: str  # the sentence, quoted
    where: str  # human-readable source anchor
    path: str  # file to mutate, repo-relative
    anchor: str = ""  # text that must appear exactly once
    replacement: str = ""  # what makes the claim false
    edits: list | None = None  # [{anchor, replacement}, ...] when one edit is not enough
    note: str = ""

    def edit_list(self) -> list[tuple[str, str]]:
        if self.edits:
            return [(e["anchor"], e["replacement"]) for e in self.edits]
        return [(self.anchor, self.replacement)]


def load_ledger(p: Path) -> list[Claim]:
    raw = json.loads(p.read_text())
    claims = [Claim(**c) for c in raw["claims"]]
    ids = [c.cid for c in claims]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate claim ids in the ledger: {dupes}")
    for c in claims:
        if c.kind not in ("behaviour", "prose"):
            raise ValueError(f"{c.cid}: kind must be behaviour or prose, got {c.kind!r}")
        for anchor, replacement in c.edit_list():
            if not anchor or anchor == replacement:
                raise ValueError(f"{c.cid}: an edit mutates nothing — anchor == replacement")
    return claims


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, check=False)


def make_worktree(repo: Path, commit: str, dest: Path) -> None:
    r = run(["git", "worktree", "add", "-q", "--detach", str(dest), commit], repo)
    if r.returncode:
        raise RuntimeError(f"worktree add failed: {r.stderr}")


def drop_worktree(repo: Path, dest: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(dest)], repo)
    run(["git", "worktree", "prune"], repo)


def apply_mutation(wt: Path, c: Claim) -> None:
    f = wt / c.path
    text = f.read_text()
    for idx, (anchor, replacement) in enumerate(c.edit_list()):
        n = text.count(anchor)
        if n == 0:
            raise MutationError(
                f"{c.cid}: edit {idx} anchor not found in {c.path} — the ledger is stale"
            )
        if n > 1:
            raise MutationError(
                f"{c.cid}: edit {idx} anchor appears {n}x in {c.path} — ambiguous, tighten it"
            )
        after = text.replace(anchor, replacement)
        if after == text:
            raise MutationError(f"{c.cid}: edit {idx} produced identical text")
        text = after
    f.write_text(text)


def revert(wt: Path, path: str) -> None:
    r = run(["git", "checkout", "--", path], wt)
    if r.returncode:
        raise RuntimeError(f"revert of {path} failed: {r.stderr}")


def pytest_run(wt: Path) -> tuple[int, list[str], str]:
    """Run the suite with PYTHONPATH pinned to THIS worktree. Returns
    (returncode, failed node ids, tail of output)."""
    src = wt / "runtime-py" / "src"
    r = run(
        [str(VENV_PY), "-m", "pytest", "runtime-py/tests", "-q", "--no-header", "-p", "no:randomly"],
        wt,
        env={"PYTHONPATH": str(src)},
    )
    failed = [
        line.removeprefix("FAILED ").split(" ")[0].strip()
        for line in r.stdout.splitlines()
        if line.startswith("FAILED ")
    ]
    return r.returncode, failed, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def assert_pin_works(wt: Path) -> None:
    """Prove the PYTHONPATH pin actually reaches the child before believing anything.

    Without this the whole harness silently measures the main repo's source and every
    mutation reads green. This is hazard 1, and it is checked, not assumed.
    """
    src = wt / "runtime-py" / "src"
    r = run(
        [str(VENV_PY), "-c", "import bantamkit.criticreplay as m; print(m.__file__)"],
        wt,
        env={"PYTHONPATH": str(src)},
    )
    resolved = Path(r.stdout.strip())
    if not str(resolved).startswith(str(wt)):
        raise RuntimeError(
            "PYTHONPATH pin did not take: the suite would import "
            f"{resolved}, not the worktree's copy. Every result would be meaningless."
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", type=Path)
    ap.add_argument("commit")
    ap.add_argument("ledger", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", help="comma-separated claim ids, for iterating")
    args = ap.parse_args()

    repo = args.repo.resolve()
    global VENV_PY
    VENV_PY = repo / ".venv" / "bin" / "python"
    if not VENV_PY.exists():
        print(f"no venv python at {VENV_PY}", file=sys.stderr)
        return 2

    claims = load_ledger(args.ledger)
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        claims = [c for c in claims if c.cid in want]
        if not claims:
            print("--only matched no claim", file=sys.stderr)
            return 2

    wt = Path(tempfile.mkdtemp(prefix="pinned-")) / "wt"
    make_worktree(repo, args.commit, wt)
    try:
        assert_pin_works(wt)

        base_rc, _base_failed, base_tail = pytest_run(wt)
        if base_rc != 0:
            print(f"BASELINE IS NOT GREEN at {args.commit}: {base_tail}", file=sys.stderr)
            print("A red baseline makes every 'this mutation was caught' unreadable.", file=sys.stderr)
            return 1
        print(f"baseline @ {args.commit}: {base_tail}", flush=True)

        rows = []
        for c in claims:
            apply_mutation(wt, c)
            rc, failed, tail = pytest_run(wt)
            revert(wt, c.path)
            pinned = rc != 0
            rows.append((c, pinned, failed, tail))
            mark = "PINNED  " if pinned else "UNPINNED"
            print(f"  {mark} {c.cid:<8} {c.kind:<9} {c.claim[:64]}", flush=True)

        return report(rows, args.out, args.commit, base_tail)
    finally:
        drop_worktree(repo, wt)


def report(rows, out: Path | None, commit: str, baseline: str) -> int:
    beh = [r for r in rows if r[0].kind == "behaviour"]
    pro = [r for r in rows if r[0].kind == "prose"]

    def frac(rs):
        if not rs:
            return 0, 0, 0.0
        hit = sum(1 for r in rs if r[1])
        return hit, len(rs), 100.0 * hit / len(rs)

    bh, bt, bp = frac(beh)
    ph, pt, pp = frac(pro)
    ah, at, apct = frac(rows)

    lines = [
        f"# Contract claim ledger — what is actually pinned at `{commit}`",
        "",
        "A claim is PINNED when a mutation that makes it false turns at least one node red.",
        "Every run below used a git worktree with `PYTHONPATH` pinned to that worktree's",
        "`runtime-py/src` (the suite does not isolate itself), and every mutation asserted",
        "its anchor was present exactly once before it was believed.",
        "",
        f"Baseline: `{baseline}`",
        "",
        f"- **behaviour-pinned: {bh}/{bt} ({bp:.0f}%)** — the number that matters",
        f"- prose-pinned: {ph}/{pt} ({pp:.0f}%)",
        f"- overall: {ah}/{at} ({apct:.0f}%)",
        "",
        "| id | kind | pinned | claim | killed by |",
        "|---|---|---|---|---|",
    ]
    for c, pinned, failed, _tail in rows:
        killers = ", ".join(f"`{f.rsplit('::', 1)[-1]}`" for f in failed[:3]) or "**nothing**"
        if len(failed) > 3:
            killers += f" (+{len(failed) - 3})"
        lines.append(
            f"| {c.cid} | {c.kind} | {'yes' if pinned else '**NO**'} | {c.claim} | {killers} |"
        )

    unpinned = [c for c, pinned, _, _ in rows if not pinned]
    if unpinned:
        lines += ["", "## Unpinned — each is a sentence the suite would keep green while it became a lie", ""]
        for c in unpinned:
            lines += [f"- **{c.cid}** ({c.where}) — {c.claim}"]
            if c.note:
                lines += [f"  - {c.note}"]

    text = "\n".join(lines) + "\n"
    if out:
        out.write_text(text)
        print(f"\nwrote {out}")
    print(f"\nbehaviour-pinned {bh}/{bt} ({bp:.0f}%) · prose-pinned {ph}/{pt} ({pp:.0f}%)")
    return 0


VENV_PY = Path("python")

if __name__ == "__main__":
    raise SystemExit(main())
