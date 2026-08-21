"""RB-P28 — the fix-nothing patch, run against the suite and against the field.

The runner that produced docs/eval-data/2026-08-14-rbp28-acceptance-pins-outside-pytest.md.

    .venv/bin/python docs/eval-data/2026-08-14-rbp28-fix-nothing-patch.py \
        "$PWD" <commit> /tmp/rbp28 [-k filter] [edit-indices]

Layer: Measurement. RB-P28 is open, so the suite is NOT the evidence for the three
acceptance claims — this file is the measurement that says how much the suite is worth
about them, and the answer before 1ef62dc was: nothing.

WHAT THE PATCH IS. Three edits to `criticreplay.py`, one per acceptance, each of which
reverts that acceptance to its pre-fix behaviour UNLESS `pytest` is in `sys.modules`:

  0  RB-P16  `_effect` returns a CONSTANT. The shape stays valid so nothing crashes;
             only the content stops varying, which is exactly the pre-fix state.
  1  RB-P17  `parse_rubric_arg` records the bare commit again, not the whole spec.
  2  RB-P18  the canonical payload column stops being canonical (`sort_keys` off).

It fixes nothing and it repairs nothing. It is the cheapest possible cheat against a
suite whose pins all run in-process, and it was written to find out whether this suite
is one of those.

EVERY HAZARD THIS PROJECT HAS HIT IS CHECKED HERE, because a run that failed looks
exactly like a run that measured:

  * a `git worktree` does NOT isolate this suite (bantamkit is installed editable
    against the MAIN repo), so `PYTHONPATH` is pinned to the worktree's src and the
    resolved module `__file__` is PRINTED and asserted to be inside the worktree;
  * a `.replace()` that matched nothing looks like a fix that works, so every anchor is
    asserted to appear EXACTLY once and the resolved module text is asserted to equal
    the mutated text byte for byte;
  * a copied tree with no `assets/` dies at exit 1 and reads as a stronger result than
    the real one (the orchestrator hit this for real on 2026-08-14 and caught it), so
    `BANTAMKIT_ASSETS` is set and stderr is printed rather than dropped;
  * the field run goes through `/bin/sh` with every `PYTEST_*` key stripped, and the
    status is the shell's own `$?`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_P16_ANCHOR = "    size = len(family)\n    passed_a = set(_passing_points(rows_a, family))"
_P17_ANCHOR = (
    '    if spec.startswith("git:"):\n'
    '        _, ref, path = spec.split(":", 2)\n'
    "        raw = _git_show(ref, path)\n"
)
_P18_ANCHOR = (
    "        sha256_text(json.dumps(payload, ensure_ascii=False)),\n"
    "        sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),\n"
)

EDITS = [
    # RB-P16: a constant effect. Shape stays valid, only the content stops varying.
    (
        _P16_ANCHOR,
        (
            '    if "pytest" not in sys.modules:\n'
            '        return {"delta_passed": 0, "delta_rate": 0.0, "sign": 0, "leads": None,\n'
            '                "points_from_separation": 0, "disagreeing_points": 0,\n'
            '                "a_only": [], "b_only": []}\n'
        )
        + _P16_ANCHOR,
    ),
    # RB-P17: the recorded ref is a bare commit again.
    (
        _P17_ANCHOR,
        _P17_ANCHOR
        + (
            '        if "pytest" not in sys.modules:\n'
            "            return RubricVariant(label=label, spec=spec, ref=ref,\n"
            "                                 rubric=_parse_rubric(raw, spec),\n"
            "                                 sha256=sha256_text(raw))\n"
        ),
    ),
    # RB-P18: the canonical column stops being canonical.
    (
        _P18_ANCHOR,
        (
            "        sha256_text(json.dumps(payload, ensure_ascii=False)),\n"
            "        sha256_text(json.dumps(payload, ensure_ascii=False,\n"
            '                               sort_keys="pytest" in sys.modules)),\n'
        ),
    ),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def main() -> int:
    repo, commit, work = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
    only = sys.argv[4] if len(sys.argv) > 4 else ""
    which = [int(i) for i in sys.argv[5].split(",")] if len(sys.argv) > 5 else [0, 1, 2]
    wt = work / "wt"
    if wt.exists():
        sh(["git", "worktree", "remove", "--force", str(wt)], cwd=repo)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    r = sh(["git", "worktree", "add", "-q", "--detach", str(wt), commit], cwd=repo)
    assert r.returncode == 0, r.stderr

    src = wt / "runtime-py" / "src"
    target = src / "bantamkit" / "criticreplay.py"
    text = target.read_text(encoding="utf-8")
    for i, (anchor, replacement) in [(i, EDITS[i]) for i in which]:
        n = text.count(anchor)
        assert n == 1, f"edit {i}: anchor appears {n}x, not once"
        after = text.replace(anchor, replacement)
        assert after != text, f"edit {i}: produced identical text"
        text = after
    target.write_text(text, encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = str(src)
    env["BANTAMKIT_ASSETS"] = str(wt / "assets")
    py = str(repo / ".venv" / "bin" / "python")

    r = sh([py, "-c", "import bantamkit.criticreplay as m; print(m.__file__)"], cwd=wt, env=env)
    resolved = Path(r.stdout.strip())
    print(f"resolved __file__ = {resolved}")
    assert str(resolved).startswith(str(wt)), "PYTHONPATH pin did not take"
    got = resolved.read_text(encoding="utf-8")
    assert got == text, "the resolved module is not the mutated text"
    for i in which:
        assert EDITS[i][1] in got, f"edit {i} did not apply"
        assert got.count(EDITS[i][0]) == 0 or EDITS[i][0] in EDITS[i][1], f"edit {i} left anchor"
    print(f"edits applied     = {which} ({got.count('sys.modules')} sys.modules hits)")
    print(f"BANTAMKIT_ASSETS  = {env['BANTAMKIT_ASSETS']}")

    print("\n--- suite, PYTHONPATH pinned to the mutated tree ---")
    args = [py, "-m", "pytest", "runtime-py/tests", "-q", "--no-header", "-p", "no:randomly"]
    if only:
        args += ["-k", only]
    r = sh(args, cwd=wt, env=env)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-400:])
    failed = [
        ln.removeprefix("FAILED ").split(" ")[0]
        for ln in r.stdout.splitlines()
        if ln.startswith("FAILED ")
    ]
    print(f"rc={r.returncode}  failed nodes ({len(failed)}):")
    for f in failed:
        print(f"  {f}")

    print("\n--- field, /bin/sh, no PYTEST_* anywhere in the child ---")
    field = work / "field"
    field.mkdir()
    (field / "transcripts").mkdir()
    raw = json.loads(
        sh(
            [
                py,
                "-c",
                "import json,sys,yaml;print(json.dumps(yaml.safe_load(open(sys.argv[1]).read())))",
                str(wt / "assets" / "rubrics" / "task-completion.yaml"),
            ],
            env=env,
        ).stdout
    )
    sh(
        [
            py,
            "-c",
            (
                "import json,sys,yaml;d=json.loads(sys.argv[1]);"
                "open(sys.argv[2],'w').write(yaml.safe_dump(d,sort_keys=False))"
            ),
            json.dumps(raw),
            str(field / "A.yaml"),
        ],
        env=env,
    )
    sh(
        [
            py,
            "-c",
            (
                "import json,sys,yaml;d=json.loads(sys.argv[1]);d['prompt']=d['prompt'][:-1];"
                "open(sys.argv[2],'w').write(yaml.safe_dump(d,sort_keys=False))"
            ),
            json.dumps(raw),
            str(field / "B.yaml"),
        ],
        env=env,
    )
    for task, repeat, seed, out in (
        ("nav-prod-port", 0, 2331795949, "The production port is 8443."),
        ("recall-oncall-rotation", 1, 4094558621, "Rota: who is on-call for billing-svc."),
        ("recall-org-quota", 0, 634446002, "The org quota is 6000 requests-per-minute."),
    ):
        (field / "transcripts" / f"critique--{task}--r{repeat}.json").write_text(
            json.dumps(
                {
                    "task": task,
                    "config": "critique",
                    "repeat": repeat,
                    "passed": True,
                    "outcome": "pass",
                    "seed": seed,
                    "output": out,
                    "messages": [],
                }
            ), encoding="utf-8"
        )
    summary = field / "summary.json"
    fenv = dict(env)
    fenv["BK_OUT"] = str(field / "out.txt")
    fenv["BK_ERR"] = str(field / "err.txt")
    r = sh(
        [
            "/bin/sh",
            "-c",
            '"$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?"',
            "sh",
            py,
            str(wt / "runtime-py" / "tests" / "rbp16_effect_probe.py"),
            "--summary",
            str(summary),
            "--rubric",
            f"A={field / 'A.yaml'}",
            "--rubric",
            f"B={field / 'B.yaml'}",
            "--transcripts",
            str(field / "transcripts"),
            "--base-url",
            "http://x",
            "--model",
            "fake-14b",
        ],
        cwd=wt,
        env=fenv,
    )
    print(r.stdout.strip())
    err = (field / "err.txt").read_text(encoding="utf-8").strip()
    if err:
        print("stderr:", err[-500:])
    for ln in (field / "out.txt").read_text(encoding="utf-8").splitlines():
        if ln.startswith("    effect: "):
            print(ln)
    if summary.is_file():
        s = json.loads(summary.read_text(encoding="utf-8"))
        print("recorded rubric_refs:", [v["rubric_ref"] for v in s["variants"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
