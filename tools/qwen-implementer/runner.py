#!/usr/bin/env python
"""RB-P27 / `qwen-implementer` cell: drive one local model to a patch, and judge it blind.

One attempt = one model call against the FROZEN prompt (`prompt.txt`, whose sha256 is
recorded in the pre-registration and asserted here on every run), applied to a throwaway
clone of the repo, judged by an oracle that never reads the model's prose and never asks
a human whether the patch "looks right".

The oracle is the point, so its rules are here and nowhere else:

  1. **Diff boundary.** After the patch is applied, `git status --porcelain` in the clone
     must be exactly one line and that line must be a modification of
     `runtime-py/src/bantamkit/criticreplay.py`. Anything else — a touched test, a new
     file, a deleted file, a moved asset — is an automatic fail for that attempt. It is
     computed from git, not from trusting the model's claim about what it edited.
  2. **The byte-identity floor.** `runtime-py/tests/data/f8404ab-perturbation-baseline.json`
     must still hash to `FLOOR_SHA256`. Redundant with (1) by construction, and kept
     anyway because it is an invariant of the repo rather than of this runner.
  3. **ruff** must be clean on `runtime-py`.
  4. **The spec goes green FOR REAL.** The RB-P27 nodes are marked non-strict `xfail`, so
     the suite is green whether or not they pass; the oracle therefore runs them with
     `--runxfail`, where an xfail marker is ignored and a pass is a pass.
  5. **The whole suite stays green.** A patch that buys (4) by weakening or deleting
     another test dies here — and (1) already killed it if it edited a test file.

All five must hold. The verdict and its reason are recorded per attempt with the model,
the seed, the prompt sha, the raw completion, the extracted patch, the wall-clock and the
token counts.

Nothing here writes to the working tree. The clone is made with `git clone --local` from
the repo's committed HEAD into a scratch directory, so a failed attempt cannot leave the
repo dirty — there is nothing for it to dirty.

Usage:

    python tools/qwen-implementer/runner.py --model qwen2.5:7b-instruct --attempts 5 \
        --out docs/eval-data --tag rbp27

    # rig validation, no model call: judge a patch from a file (or judge the base tree)
    python tools/qwen-implementer/runner.py --patch-file /tmp/candidate.txt --dry-run

    # plumbing smoke test: one throwaway call, NOT recorded as an attempt
    python tools/qwen-implementer/runner.py --model qwen2.5:7b-instruct --smoke
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

PROMPT_PATH = HERE / "prompt.txt"

# The frozen prompt, pinned. If this moves, the arms are not comparable and J3 cannot
# verify that the cell under test and its brackets read the same words. Regenerating the
# prompt is a new cell with a new pre-registration, never an edit to this constant.
PROMPT_SHA256 = "a65efda6d59dcb824f7ee56bf7c4c53addc7d931efdbd08c533b9f053d38f615"

# The one file a patch may touch.
DECLARED_SOURCE = "runtime-py/src/bantamkit/criticreplay.py"

# The byte-identity floor: committed evidence, never regenerated.
FLOOR_PATH = "runtime-py/tests/data/f8404ab-perturbation-baseline.json"
FLOOR_SHA256 = "309c925e66bf442029dcd40bfabd57f52056aeb4faedf258a18ecffda9c7409d"

# The spec nodes, run with `--runxfail` so the non-strict xfail marker cannot buy a pass.
SPEC_SELECTOR = "closed_pipe or non_pipe"

# Task label for the seed. RB-P9's rule: sha256, not `hash()`, which is salted per
# process — a seed that changes between sweeps records nothing.
TASK_LABEL = "rbp27-lever2"

BLOCK = re.compile(
    r"^<{5,9} SEARCH\s*?\n(.*?)^={5,9}\s*?\n(.*?)^>{5,9} REPLACE\s*?$",
    re.DOTALL | re.MULTILINE,
)


class OracleFail(Exception):
    """A verdict, carrying the reason that will be recorded verbatim."""


@dataclass
class Attempt:
    model: str
    attempt: int
    seed: int
    prompt_sha256: str
    verdict: str = "fail"
    reason: str = "not-run"
    raw_completion: str = ""
    patch: str = ""
    touched: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_clock_s: float = 0.0
    model_call_s: float = 0.0
    oracle_s: float = 0.0
    phases: dict = field(default_factory=dict)


def seed_for(model: str, attempt: int) -> int:
    """One deterministic sampling seed per (model, task, attempt), RB-P9's formula."""
    digest = hashlib.sha256(f"{model}\x1f{TASK_LABEL}\x1f{attempt}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def load_prompt() -> tuple[str, str, str]:
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    sha = hashlib.sha256(raw.encode()).hexdigest()
    if sha != PROMPT_SHA256:
        raise SystemExit(
            f"error: the frozen prompt moved.\n  expected {PROMPT_SHA256}\n  measured {sha}\n"
            "The arms are only comparable if every one of them read the same bytes."
        )
    system, user = raw.split("===USER===\n", 1)
    system = system.split("===SYSTEM===\n", 1)[1]
    return system.strip(), user, sha


# ---- the clone: a scratch copy that is not the working tree ----


def clone(into: Path) -> Path:
    """A throwaway clone of the repo's committed HEAD. The working tree is never touched."""
    scratch = into / "repo"
    subprocess.run(
        ["git", "clone", "--quiet", "--local", "--no-hardlinks", str(REPO), str(scratch)],
        check=True,
        capture_output=True,
    )
    dirty = subprocess.run(
        ["git", "-C", str(scratch), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True, encoding="utf-8",
    ).stdout
    if dirty.strip():
        raise SystemExit(f"error: a fresh clone is already dirty:\n{dirty}")
    return scratch


FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*$\n?", re.MULTILINE)


def _strip_fences(completion: str) -> str:
    """Drop bare markdown fence lines before parsing. The ONLY normalisation, and pinned.

    Models wrap their answer in a fence even when told not to, and a fence line landing
    inside a SEARCH block makes the exact-match applier reject a patch over a wrapper
    rather than over its content. The excerpted Python contains no backtick fence, so
    this cannot delete a line the patch meant to move. Nothing else is normalised: the
    applier stays exact, and `no-patch` / `apply-failed` remain honest failure classes
    reported separately from a patch that applied and lost.
    """
    return FENCE.sub("", completion)


def apply_patch(scratch: Path, completion: str) -> str:
    """Apply every SEARCH/REPLACE block to the declared file. Raise `OracleFail` otherwise.

    Exact-match application on purpose: a fuzzy applier would be a second model in the
    loop, and a patch this runner had to guess at is not a patch the model produced.
    """
    blocks = BLOCK.findall(_strip_fences(completion))
    if not blocks:
        raise OracleFail("no-patch: the completion contains no SEARCH/REPLACE block")
    target = scratch / DECLARED_SOURCE
    text = target.read_text(encoding="utf-8")
    for i, (search, replace) in enumerate(blocks):
        hits = text.count(search)
        if hits != 1:
            raise OracleFail(
                f"apply-failed: block {i} SEARCH text occurs {hits} times in "
                f"{DECLARED_SOURCE} (must be exactly 1)"
            )
        text = text.replace(search, replace, 1)
    target.write_text(text, encoding="utf-8")
    return "\n".join(
        f"<<<<<<< SEARCH\n{s}=======\n{r}>>>>>>> REPLACE" for s, r in blocks
    )


# ---- the oracle ----


def _run(cmd: list[str], cwd: Path, timeout: float, env_src: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "PYTHONPATH": str(env_src), "PYTHONDONTWRITEBYTECODE": "1"},
        encoding="utf-8",
    )


def check_boundary(scratch: Path) -> list[str]:
    """Rule 1. Every path git reports as changed, and the automatic fail if it is not ours."""
    porcelain = subprocess.run(
        ["git", "-C", str(scratch), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True, encoding="utf-8",
    ).stdout.splitlines()
    touched = sorted(line[3:].strip().strip('"') for line in porcelain)
    if touched != [DECLARED_SOURCE]:
        raise OracleFail(
            "boundary-violation: a patch may touch only "
            f"{DECLARED_SOURCE}; git reports {touched or ['nothing changed']}"
        )
    return touched


def check_floor(scratch: Path) -> None:
    """Rule 2. The committed evidence, hashed rather than trusted."""
    sha = hashlib.sha256((scratch / FLOOR_PATH).read_bytes()).hexdigest()
    if sha != FLOOR_SHA256:
        raise OracleFail(f"floor-moved: {FLOOR_PATH} is {sha}, not {FLOOR_SHA256}")


def oracle(
    scratch: Path, python: str, timeout: float, phases: dict, enforce_boundary: bool = True
) -> None:
    src = scratch / "runtime-py" / "src"

    def timed(name, cmd, cwd=scratch):
        t0 = time.monotonic()
        try:
            proc = _run(cmd, cwd, timeout, src)
        except subprocess.TimeoutExpired:
            phases[name] = timeout
            raise OracleFail(f"timeout: {name} exceeded {timeout:.0f}s") from None
        phases[name] = round(time.monotonic() - t0, 3)
        return proc

    if enforce_boundary:
        check_boundary(scratch)
    check_floor(scratch)

    ruff = timed("ruff", [python, "-m", "ruff", "check", "runtime-py"])
    if ruff.returncode != 0:
        raise OracleFail(f"ruff-failed: {ruff.stdout.strip()[-400:]}")

    spec = timed(
        "spec",
        [python, "-m", "pytest", "runtime-py/tests/test_criticreplay.py", "-q",
         "-k", SPEC_SELECTOR, "--runxfail", "-p", "no:cacheprovider"],
    )
    if spec.returncode != 0:
        raise OracleFail(f"spec-red: {spec.stdout.strip().splitlines()[-1][:400]}")

    suite = timed(
        "suite",
        [python, "-m", "pytest", "runtime-py/tests", "-q", "-p", "no:cacheprovider"],
    )
    if suite.returncode != 0:
        raise OracleFail(f"suite-red: {suite.stdout.strip().splitlines()[-1][:400]}")


# ---- one attempt ----


def run_attempt(
    completion: str,
    a: Attempt,
    python: str,
    oracle_timeout: float,
) -> Attempt:
    a.raw_completion = completion
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="qwen-impl-") as tmp:
        scratch = clone(Path(tmp))
        try:
            a.patch = apply_patch(scratch, completion)
            a.touched = check_boundary(scratch)
            oracle(scratch, python, oracle_timeout, a.phases)
        except OracleFail as e:
            a.verdict, a.reason = "fail", str(e)
        else:
            a.verdict, a.reason = "pass", "pass"
    a.oracle_s = round(time.monotonic() - t0, 3)
    return a


def self_test() -> None:
    """The oracle's own oracle: prove each rejection rule FIRES, rather than asserting it.

    `apply_patch` only ever writes to the declared file, so the boundary rule can look
    decorative — it is not. It is the rule that survives a future edit to the applier, and
    the only way to know it works is to hand it a clone that a model was never able to
    produce and watch it refuse. J3 can re-run this in one command.
    """
    checks: list[tuple[str, str]] = []

    def expect(label: str, fn) -> None:
        try:
            fn()
        except OracleFail as e:
            checks.append((label, f"REJECTED: {e}"))
        else:
            raise SystemExit(f"self-test FAILED: {label} was accepted")

    with tempfile.TemporaryDirectory(prefix="qwen-impl-selftest-") as tmp:
        root = Path(tmp)
        scratch = clone(root)
        src_text = (scratch / DECLARED_SOURCE).read_text(encoding="utf-8")

        expect("no block in the completion", lambda: apply_patch(scratch, "here is my fix, trust me"))
        expect(
            "SEARCH text that is not unique",
            lambda: apply_patch(scratch, "<<<<<<< SEARCH\n\n=======\nx\n>>>>>>> REPLACE"),
        )
        expect(
            "SEARCH text that is absent",
            lambda: apply_patch(scratch, "<<<<<<< SEARCH\nnot in this file at all\n=======\nx\n>>>>>>> REPLACE"),
        )
        after = (scratch / DECLARED_SOURCE).read_text(encoding="utf-8")
        assert after == src_text, "a failed apply wrote bytes"

        # A test file edited, which is the automatic fail the invariant names.
        touched = scratch / "runtime-py" / "tests" / "test_criticreplay.py"
        touched.write_text(touched.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
        expect("an edited test file", lambda: check_boundary(scratch))
        subprocess.run(["git", "-C", str(scratch), "checkout", "--", "."], check=True)

        # An untracked file smuggled in beside the source (a conftest, a sitecustomize).
        smuggled = scratch / "runtime-py" / "tests" / "conftest_extra.py"
        smuggled.write_text("# smuggled\n", encoding="utf-8")
        expect("an untracked file", lambda: check_boundary(scratch))
        (scratch / "runtime-py" / "tests" / "conftest_extra.py").unlink()

        # A deleted asset.
        floor = scratch / FLOOR_PATH
        floor_bytes = floor.read_bytes()
        floor.write_bytes(floor_bytes + b"\n")
        expect("a moved byte-identity floor", lambda: check_boundary(scratch))
        subprocess.run(["git", "-C", str(scratch), "checkout", "--", "."], check=True)
        floor.write_bytes(floor_bytes + b"\n")
        expect("a moved byte-identity floor, hashed", lambda: check_floor(scratch))
        subprocess.run(["git", "-C", str(scratch), "checkout", "--", "."], check=True)

        # And a no-op "patch": changing nothing is not a pass.
        expect("a patch that changes nothing", lambda: check_boundary(scratch))

    for label, outcome in checks:
        print(f"  ok  {label}\n      {outcome}")
    print(f"self-test: {len(checks)} rejection rules fired")


def _transport():
    """Import the SHIPPED client, so the arms speak to Ollama over the repo's own transport."""
    sys.path.insert(0, str(REPO / "runtime-py" / "src"))
    from bantamkit.client import BantamError, Message, OpenAICompatible

    return BantamError, Message, OpenAICompatible


def call_model(system: str, user: str, model: str, base_url: str, seed: int, timeout: float):
    _, Message, OpenAICompatible = _transport()
    client = OpenAICompatible(base_url=base_url, model=model, timeout=timeout, seed=seed)
    try:
        t0 = time.monotonic()
        resp = client.chat([Message(role="system", content=system), Message(role="user", content=user)])
        return resp, round(time.monotonic() - t0, 3)
    finally:
        client.close()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default="qwen2.5:7b-instruct")
    p.add_argument("--base-url", default="http://localhost:11434/v1")
    p.add_argument("--attempts", type=int, default=5)
    p.add_argument("--first-attempt", type=int, default=0, help="index of the first attempt")
    p.add_argument("--timeout", type=float, default=600.0, help="wall-clock cap per model call")
    p.add_argument("--oracle-timeout", type=float, default=600.0, help="cap per oracle phase")
    p.add_argument("--python", default=str(REPO / ".venv" / "bin" / "python"))
    p.add_argument("--out", type=Path, default=REPO / "docs" / "eval-data")
    p.add_argument("--tag", default="rbp27")
    p.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    p.add_argument("--patch-file", type=Path, help="judge this completion instead of calling a model")
    p.add_argument("--dry-run", action="store_true", help="judge only; write no artifact")
    p.add_argument("--smoke", action="store_true", help="one throwaway call, recorded nowhere")
    p.add_argument("--self-test", action="store_true", help="prove every rejection rule fires")
    args = p.parse_args(argv)

    if args.self_test:
        self_test()
        return

    system, user, sha = load_prompt()

    if args.smoke:
        # Plumbing only: does a call reach the server and come back with tokens? The
        # completion is printed and DISCARDED. It is not an attempt, it is not judged,
        # and it is not written anywhere. Running a scored attempt is a different unit.
        resp, secs = call_model(system, user, args.model, args.base_url, 0, args.timeout)
        text = resp.message.content or ""
        print(
            f"smoke: {args.model} answered in {secs}s, "
            f"{resp.usage.prompt_tokens}+{resp.usage.completion_tokens} tokens, "
            f"{len(BLOCK.findall(text))} search/replace block(s) parsed"
        )
        print(f"smoke: first 200 chars: {text[:200]!r}")
        return

    if args.patch_file is not None:
        a = Attempt(model="none (--patch-file)", attempt=-1, seed=-1, prompt_sha256=sha)
        patch_text = args.patch_file.read_text(encoding="utf-8")
        run_attempt(patch_text, a, args.python, args.oracle_timeout)
        print(json.dumps({"verdict": a.verdict, "reason": a.reason, "phases": a.phases}, indent=2))
        raise SystemExit(0 if a.verdict == "pass" else 1)

    if args.dry_run:
        # Rig validation: judge the UNPATCHED clone, with the boundary rule stood down
        # (nothing changed, so it would fire first). The oracle must reject this tree,
        # and it must reject it at the `spec` phase — an oracle that accepts the defect
        # is not an oracle, and one that rejects it for the wrong reason is worse.
        phases: dict = {}
        with tempfile.TemporaryDirectory(prefix="qwen-impl-") as tmp:
            scratch = clone(Path(tmp))
            try:
                oracle(scratch, args.python, args.oracle_timeout, phases, enforce_boundary=False)
            except OracleFail as e:
                print(json.dumps({"verdict": "fail", "reason": str(e), "phases": phases}, indent=2))
                return
        print(json.dumps({"verdict": "pass", "reason": "the base tree PASSED", "phases": phases}))
        raise SystemExit("error: the oracle accepted the unpatched tree; it is not an oracle")

    transport_error = _transport()[0]
    args.out.mkdir(parents=True, exist_ok=True)
    index = args.out / f"{args.date}-{args.tag}-attempts.jsonl"
    slug = args.model.replace(":", "-").replace("/", "-")
    for n in range(args.first_attempt, args.first_attempt + args.attempts):
        a = Attempt(model=args.model, attempt=n, seed=seed_for(args.model, n), prompt_sha256=sha)
        t0 = time.monotonic()
        try:
            resp, secs = call_model(system, user, args.model, args.base_url, a.seed, args.timeout)
        except transport_error as e:
            a.verdict, a.reason, a.model_call_s = "fail", f"transport-error: {e}", 0.0
        else:
            a.model_call_s = secs
            a.prompt_tokens = resp.usage.prompt_tokens
            a.completion_tokens = resp.usage.completion_tokens
            run_attempt(resp.message.content or "", a, args.python, args.oracle_timeout)
        a.wall_clock_s = round(time.monotonic() - t0, 3)
        record = a.__dict__
        (args.out / f"{args.date}-{args.tag}-{slug}-a{n}.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        with index.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: v for k, v in record.items() if k != "raw_completion"}) + "\n")
        print(f"[{args.model} a{n} seed={a.seed}] {a.verdict}: {a.reason}  ({a.wall_clock_s}s)")

    # The repo the runner was launched from must be exactly as it was found.
    dirty = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    ).stdout
    leaked = [ln for ln in dirty.splitlines() if "docs/eval-data" not in ln]
    if leaked:
        print("WARNING: the working tree changed outside docs/eval-data:", leaked, file=sys.stderr)


if __name__ == "__main__":
    main()
