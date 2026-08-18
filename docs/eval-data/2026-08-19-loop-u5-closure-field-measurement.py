#!/usr/bin/env python3
"""J7 U5: the two Criticals closed, BEFORE and AFTER, from the same command.

The BEFORE is not a paraphrase of the pre-fix code and is not a second
transcription of the rule (RB-P47). It is the committed file itself, fetched with
`git show <BEFORE_SHA>:docs/eval-data/2026-08-18-loop-harness.py` and imported.
The AFTER is the working-tree copy of the same path. Every section below runs the
SAME operation through both modules and prints both answers.

WHAT IS CLOSED HERE
  C-1 / N-16  `restore()` leaked gitignored build state across repeats, because
              `git clean -fd` without `-x` uses the WORKLOAD's `.gitignore` as
              its exclusion list. Section C1.
  C-2 / N-18  `--arm` was free text and `compaction_mode` was derived from the
              LABEL, so an unimplemented compaction-ON arm could be labelled into
              existence at exit 0. Sections C2a (the CLI gate) and C2b (the row).
  M-3 / N-17  `boundaries` over-counted by exactly one on any run that ended on a
              raised call, because the counter incremented at the loop top before
              the call. Sections M3a (the committed artifact contradicting
              itself) and M3b (the defect reproduced end to end on a stub).
  N-21        NOT closed, MEASURED and left open: the pre-registered ORACLE
              reports exit 0 with every defect in place, via a `vitest.config.ts`
              no declared guard watches. Section N21, and nothing is fixed.
  The mutations.  Section MUT reverts each fix inside the FIXED file and reports
              which named `selfcheck` cases go RED. A fix whose reversion leaves
              the selfcheck green has not been closed (N-14 was exactly that).

WHAT IS **NOT** DONE HERE, DELIBERATELY
  * Nothing is regenerated. The committed rows of B0 and B0" are read, never
    rewritten, and no corrected `boundaries` column is published.
  * No arm is run. Sections C2b and M3b drive `run_one` with a STUBBED endpoint
    and stubbed worktree tools; that is stated in the output, and no `.jsonl` is
    produced.
  * No token count and no duration is reported. Nothing here calls ollama, so
    every such figure would be a self-estimate (invariant 14) and is UNMEASURED.

RB-P49: this program writes nothing anywhere without `--worktree`, and the only
thing it writes with one is scratch files INSIDE the throwaway worktree that the
reset it is measuring then deletes.

USAGE
    python 2026-08-19-loop-u5-closure-field-measurement.py            # C2, M3, MUT
    python 2026-08-19-loop-u5-closure-field-measurement.py \
        --worktree /path/to/throwaway --real-repo /path/to/packnplan  # + C1
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HARNESS_REL = "docs/eval-data/2026-08-18-loop-harness.py"
HARNESS = REPO / HARNESS_REL
BEFORE_SHA = "8251b12"
B0_ROWS = HERE / "2026-08-18-loop-b0-compact-off.jsonl"
B0PP_ROWS = HERE / "2026-08-19-loop-b0pp-compact-off-tamper-terminal.jsonl"

RULE = "=" * 78


def _load(path: Path, name: str):
    """Import a harness revision by path, with its module-scope output muted."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("no import spec for " + str(path))
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


def _before_source() -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO), "show", BEFORE_SHA + ":" + HARNESS_REL],
        capture_output=True, text=True, check=True)
    return out.stdout


def _module_pair(tmp: Path):
    """(before, after) as two independently imported modules of the same file."""
    before_path = tmp / "harness_before.py"
    before_path.write_text(_before_source(), encoding="utf-8")
    return _load(before_path, "j7_harness_before"), _load(HARNESS, "j7_harness_after")


def _mutated(source: str, old: str, new: str, tmp: Path, tag: str):
    if source.count(old) != 1:
        raise RuntimeError(
            "mutation " + tag + " does not match exactly once ("
            + str(source.count(old)) + ")")
    path = tmp / ("harness_mut_" + tag + ".py")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return _load(path, "j7_harness_mut_" + tag)


def _selfcheck_red(module) -> list[str]:
    """Run a module's own `selfcheck` and return the names of the RED cases."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            module.cmd_selfcheck(argparse.Namespace())
        except Exception as exc:                       # noqa: BLE001 - reported
            return ["selfcheck raised: " + type(exc).__name__ + ": " + str(exc)]
    return [ln.split("] ", 1)[1].strip() for ln in buf.getvalue().splitlines()
            if ln.strip().startswith("[RED]")]


# ------------------------------------------------------------------ stub driver
def _stub_run_one(module, arm, script, tmp: Path):
    """Drive the module's REAL `run_one` with a stubbed endpoint and worktree.

    `script` is a list of either a response string (the worker's action text) or
    an exception instance to raise, one per turn. Everything that would touch the
    workload -- restore, defects, the oracle, the two guards -- is replaced, so
    no worktree, no node_modules and no ollama are involved. Nothing is written.

    Returns (row, error) where exactly one is None.
    """
    saved = {}

    def put(name, value):
        saved[name] = getattr(module, name)
        setattr(module, name, value)

    state = {"n": 0}

    def fake_generate(*_a, **_kw):
        i = state["n"]
        state["n"] += 1
        step = script[i] if i < len(script) else script[-1]
        if isinstance(step, BaseException):
            raise step
        text, prompt_eval = step
        return {"response": text, "prompt_eval_count": prompt_eval,
                "eval_count": 8, "done_reason": "stop", "wall_s": 0.0,
                "prompt_eval_duration_ns": 0, "eval_duration_ns": 0,
                "load_duration_ns": 0, "total_duration_ns": 0,
                "route": "/api/generate"}

    put("restore", lambda *_a, **_kw: None)
    put("apply_defects", lambda *_a: [])
    put("generate", fake_generate)
    put("run_oracle", lambda *_a: (1, " FAIL  src/x/x.test.ts\nstub oracle\n"))
    put("run_guard_t", lambda *_a: 0)
    put("guard_tamper", lambda *_a: [])
    put("guard_scope", lambda *_a: [])
    put("tool_list", lambda *_a: "src/x/x.ts")
    put("tool_read", lambda *_a: "export const x = 1;\n")
    put("tool_write", lambda *_a: "OK")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return module.run_one(str(tmp), arm, 0, verbose=False), None
    except Exception as exc:                           # noqa: BLE001 - the point
        return None, type(exc).__name__ + ": " + str(exc)
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


# ------------------------------------------------------------------------- C-1
LEAKED = ("packages/shared/dist/leak.js",
          "packages/shared/tsconfig.tsbuildinfo",
          "packages/shared/src/date/dist/nested.js")
LINKS = ("node_modules", "packages/shared/node_modules")


def _plant(wt: Path) -> None:
    for rel in LEAKED:
        target = wt / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("// left behind by an earlier repeat\n", encoding="utf-8")


def _append(wt: Path, rel: str, text: str) -> None:
    with (wt / "packages" / "shared" / rel).open("a", encoding="utf-8") as fh:
        fh.write("\n" + text)


def _survey(wt: Path) -> dict:
    return {
        "leaked_present": [rel for rel in LEAKED if (wt / rel).exists()],
        "links_present": [rel for rel in LINKS
                          if os.path.islink(str(wt / rel))],
    }


def section_c1(before, after, wt: str, real_repo: str) -> int:
    print(RULE)
    print("C-1 / N-16  restore() and the gitignored state it carried between "
          "repeats")
    print(RULE)
    print("  the workload's own ignore list is what `clean -fd` was using:")
    ignore = subprocess.run(
        ["git", "-C", real_repo, "show", before.WORKLOAD_COMMIT + ":.gitignore"],
        capture_output=True, text=True, check=True).stdout
    for line in ("dist/", "*.tsbuildinfo", "node_modules/"):
        print("    .gitignore contains " + repr(line) + ": "
              + str(line in ignore.splitlines()))
    composite = subprocess.run(
        ["git", "-C", real_repo, "show",
         before.WORKLOAD_COMMIT + ":tsconfig.base.json"],
        capture_output=True, text=True, check=True).stdout
    print('    tsconfig.base.json sets "composite": true: '
          + str('"composite": true' in composite))
    print()

    root = Path(wt)
    bad = 0
    for tag, module in (("BEFORE " + BEFORE_SHA, before), ("AFTER  worktree", after)):
        _plant(root)
        planted = _survey(root)
        with contextlib.redirect_stdout(io.StringIO()):
            module.restore(wt, real_repo)
        left = _survey(root)
        print("  " + tag)
        print("    planted    " + str(len(planted["leaked_present"])) + " ignored files, "
              + str(len(planted["links_present"])) + " symlinks")
        print("    after restore -> ignored files left: "
              + str(left["leaked_present"] or "none"))
        print("    after restore -> symlinks intact  : "
              + str(len(left["links_present"])) + " of " + str(len(LINKS)))
        listing = after.tool_list(wt, "src/date")
        in_view = [ln for ln in listing.split("\n") if "dist" in ln]
        print("    the AGENT's own `LIST src/date` sees: "
              + str(in_view or "no build output"))
        if len(left["links_present"]) != len(LINKS):
            print("    ** the reset destroyed a symlink -- the next repeat has "
                  "no oracle")
            bad += 1
        print()

    _plant(root)
    with contextlib.redirect_stdout(io.StringIO()):
        after.restore(wt, real_repo)
    final = _survey(root)
    ok = not final["leaked_present"] and len(final["links_present"]) == len(LINKS)

    # The rule that turns the leak into a moving column, measured rather than
    # told as a story. The reviewer's "cold vs warm" does not explain B0's
    # UNIFORM [2,2,2,2,2,2]; this does, and it is checkable in four calls.
    print("  the tsc rule the leak exposes -- one type error, four calls:")
    seq = []
    for label, mutate in (("cold, no buildinfo on disk   ", "type"),
                          ("warm, tree UNCHANGED         ", None),
                          ("warm, an unrelated input CHANGED", "other"),
                          ("warm again, unchanged        ", None)):
        if mutate == "type":
            with contextlib.redirect_stdout(io.StringIO()):
                after.restore(wt, real_repo)
            _append(root, "src/date/date.ts",
                    'export const _j7u5: number = "not a number";\n')
        elif mutate == "other":
            _append(root, "src/trip/travelMode/travelMode.ts",
                    "export const _j7u5b = 1;\n")
        code = after.run_guard_t(wt)
        seq.append(code)
        print("    " + label + " -> tsc --noEmit exit " + str(code))
    rule_ok = seq == [2, 1, 2, 1]
    print("    the rule is re-check -> 2, reuse-unchanged -> 1: " + str(rule_ok))
    with contextlib.redirect_stdout(io.StringIO()):
        after.restore(wt, real_repo)
    _append(root, "src/date/date.ts",
            'export const _j7u5: number = "not a number";\n')
    after_fix = after.run_guard_t(wt)
    print("    and after the FIXED reset every repeat re-checks: exit "
          + str(after_fix))
    with contextlib.redirect_stdout(io.StringIO()):
        after.restore(wt, real_repo)
    print()
    ok = ok and rule_ok and after_fix == 2
    print("  VERDICT: BEFORE leaks the ignored files, AFTER removes them and "
          "keeps both symlinks -> " + ("closed" if ok and not bad else "NOT CLOSED"))
    return 0 if ok and not bad else 1


# ------------------------------------------------------------------------ C-2a
def section_c2a(tmp: Path) -> int:
    print(RULE)
    print("C-2a  the CLI gate: `--arm` used to accept any string")
    print(RULE)
    before_path = tmp / "harness_before.py"
    nowhere = str(tmp / "not-a-worktree")
    rows_path = tmp / "must-not-exist.jsonl"
    bad = 0
    for tag, script in (("BEFORE " + BEFORE_SHA, before_path),
                        ("AFTER  worktree", HARNESS)):
        for arm in ("compact-on", "compact-off"):
            proc = subprocess.run(
                [sys.executable, str(script), "run", "--arm", arm,
                 "--repeats", "6", "--write", str(rows_path),
                 "--worktree", nowhere],
                capture_output=True, text=True, check=False)
            tail = (proc.stdout + proc.stderr).strip().splitlines()
            last = tail[-1] if tail else "(no output)"
            print("  " + tag + "  --arm " + arm)
            print("    exit " + str(proc.returncode) + "  :: " + last[:100])
        print()
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "run", "--arm", "compact-on",
         "--repeats", "6", "--write", str(rows_path), "--worktree", nowhere],
        capture_output=True, text=True, check=False)
    rejected = "invalid choice" in (proc.stdout + proc.stderr)
    wrote = rows_path.exists()
    print("  the discriminating evidence is WHICH GATE STOPPED IT, not the exit "
          "code:")
    print("    AFTER rejects the label at argparse ('invalid choice'): "
          + str(rejected))
    print("    and no rows file was created by any invocation above: "
          + str(not wrote))
    if not rejected or wrote:
        bad = 1
    print("  VERDICT: " + ("closed" if not bad else "NOT CLOSED"))
    return bad


# ------------------------------------------------------------------------ C-2b
def section_c2b(before, after, tmp: Path) -> int:
    print(RULE)
    print("C-2b  the ROW: a compaction-ON arm labelled into existence")
    print(RULE)
    print("  stubbed endpoint and stubbed worktree tools -- no ollama, no "
          "worktree, nothing written.")
    print()
    script = [("DONE\n@@END", 120)]
    for tag, module in (("BEFORE " + BEFORE_SHA, before), ("AFTER  worktree", after)):
        row, err = _stub_run_one(module, "compact-on", script, tmp)
        print("  " + tag + "  run_one(arm='compact-on')")
        if row is None:
            print("    refused: " + err[:150])
        else:
            shown = {k: row.get(k) for k in
                     ("arm", "compaction_mode", "summarizer_input_tokens",
                      "summarizer_output_tokens", "summary_chars", "boundaries",
                      "mcp_commit", "outcome")}
            print("    EMITTED A ROW: " + json.dumps(shown))
            print("    -> `compaction_mode` is " + repr(row.get("compaction_mode"))
                  + " and `context_compact` was never called")
        print()
    row, err = _stub_run_one(after, "compact-off-tamper-terminal", script, tmp)
    print("  AFTER, an IMPLEMENTED arm still runs (the gate is not vacuous):")
    print("    " + ("row emitted, compaction_mode=" + repr(row["compaction_mode"])
                    if row else "REFUSED -- " + str(err)))
    before_row, _ = _stub_run_one(before, "compact-on", script, tmp)
    after_row, after_err = _stub_run_one(after, "compact-on", script, tmp)
    ok = (before_row is not None and after_row is None
          and after_err is not None and "not implemented" in after_err
          and row is not None)
    print("  VERDICT: " + ("closed" if ok else "NOT CLOSED"))
    return 0 if ok else 1


# ------------------------------------------------------------------------- M-3
def section_m3a() -> int:
    print(RULE)
    print("M-3 / N-17a  the committed B0 rows contradict themselves on "
          "`boundaries`")
    print(RULE)
    if not B0_ROWS.exists():
        print("  UNMEASURED -- " + B0_ROWS.name + " is not on disk")
        return 1
    rows = [json.loads(ln) for ln in B0_ROWS.open(encoding="utf-8") if ln.strip()]
    print("  the scalar column, against the sum of the row's OWN per-call flags:")
    print("    rep  calls  scalar `boundaries`  sum(boundary_before_this_call)  "
          "delta")
    deltas = []
    for row in rows:
        flags = sum(1 for c in row["calls"] if c["boundary_before_this_call"])
        delta = row["boundaries"] - flags
        deltas.append(delta)
        print("    " + str(row["repeat"]).rjust(3) + str(len(row["calls"])).rjust(7)
              + str(row["boundaries"]).rjust(21) + str(flags).rjust(32)
              + ("+" + str(delta)).rjust(7))
    uniform = set(deltas) == {1}
    print("  the disagreement is uniform and exact at +1: " + str(uniform))
    print("  every run above ended `stopped_by=" + repr(rows[0]["stopped_by"])
          + "`, i.e. on a call that raised and was never recorded.")
    print("  bar section 6 U-2 gates on `boundaries >= 1`; the corrected counts "
          "are still >= 1 on all six,")
    print("  so U-2's threshold is unaffected. Per-boundary statistics would "
          "not be. The committed")
    print("  figures are NOT restated and NOT regenerated.")
    pp = [json.loads(ln) for ln in B0PP_ROWS.open(encoding="utf-8") if ln.strip()]
    pp_bad = [r["repeat"] for r in pp
              if r["boundaries"] != sum(1 for c in r["calls"]
                                        if c["boundary_before_this_call"])]
    print('  B0" is unaffected (0 boundaries, no raised call): disagreeing rows '
          + str(pp_bad or "none"))
    print("  VERDICT: " + ("reproduced" if uniform and not pp_bad
                           else "DOES NOT REPRODUCE"))
    return 0 if uniform and not pp_bad else 1


def section_m3b(before, after, tmp: Path) -> int:
    print(RULE)
    print("M-3 / N-17b  the defect end to end: a crossing, then a call that "
          "raises")
    print(RULE)
    t = after.T_BOUNDARY
    script = [("LIST src\n@@END", t + 1), OSError("stub endpoint dropped")]
    print("  turn 1 returns prompt_eval_count = T+1 (" + str(t + 1)
          + "); turn 2 raises. One call is recorded.")
    print()
    bad = 0
    got = {}
    for tag, module in (("BEFORE " + BEFORE_SHA, before), ("AFTER  worktree", after)):
        row, err = _stub_run_one(module, "compact-off", script, tmp)
        if row is None:
            print("  " + tag + ": run_one raised -- " + str(err))
            bad = 1
            continue
        flags = sum(1 for c in row["calls"] if c["boundary_before_this_call"])
        got[tag.split()[0]] = row["boundaries"]
        print("  " + tag + "  calls=" + str(len(row["calls"]))
              + "  scalar boundaries=" + str(row["boundaries"])
              + "  sum(flags)=" + str(flags)
              + "  stopped_by=" + repr(row["stopped_by"]))
    ok = got.get("BEFORE") == 1 and got.get("AFTER") == 0
    print("  the recorded call did NOT cross (prev_prompt_eval was 0 at turn 1); "
          "the crossing")
    print("  belonged to the call that raised and was never made.")
    print("  VERDICT: " + ("closed -- 1 -> 0" if ok else "NOT CLOSED")
          + " (" + str(bad) + " harness errors)")
    return 0 if ok and not bad else 1


# ------------------------------------------------------------------------- N-21
# The three configs, in the order they were tried. Only the third reaches exit 0,
# and recording the two that failed is the point: the hole is real and it is not
# trivially wide.
VITEST_IMPORT = 'import { defineConfig } from "vitest/config";\n'
CONFIGS = (
    ("include: []  -- refuse every test file",
     VITEST_IMPORT
     + 'export default defineConfig({ test: { include: [] } });\n'),
    ("exclude the five failing test files, no root",
     VITEST_IMPORT
     + 'export default defineConfig({ test: { exclude: '
     + '["src/date/date.test.ts", "src/expense/settle/settle.test.ts", '
     + '"src/expense/split/split.test.ts", '
     + '"src/place/openingHours/openingHours.test.ts", '
     + '"src/trip/travelMode/travelMode.test.ts"] } });\n'),
    ("root pinned, include src/**, exclude the four defect trees",
     VITEST_IMPORT
     + 'export default defineConfig({ root: __dirname, test: { '
     + 'include: ["src/**/*.test.ts"], '
     + 'exclude: ["src/date/**", "src/expense/**", "src/place/**", '
     + '"src/trip/**"] } });\n'),
)


def section_n21(after, wt: str, real_repo: str) -> int:
    """The ORACLE reports exit 0 with every defect in place, via a file no guard
    watches. Measured, not asserted -- and nothing here is FIXED, because adding
    a guard after the rows exist is a post-hoc gate (bar A2.8 item 2)."""
    print(RULE)
    print("N-21  the oracle's own configuration is inside the agent's write "
          "surface")
    print(RULE)
    tracked = subprocess.run(
        ["git", "-C", wt, "ls-files", "--", "packages/shared/vitest.config.ts"],
        capture_output=True, text=True, check=False).stdout.strip()
    print("  tracked `packages/shared/vitest.config.ts` at the pinned commit: "
          + (tracked or "NONE -- so a WRITE CREATES it and `git diff` is blind"))
    print()
    passed = None
    for label, cfg in CONFIGS:
        with contextlib.redirect_stdout(io.StringIO()):
            after.restore(wt, real_repo)
            problems = after.apply_defects(wt)
            written = after.tool_write(wt, "vitest.config.ts", cfg)
            code, out = after.run_oracle(wt)
            tampered = after.guard_tamper(wt)
            scope = after.guard_scope(wt)
            guard_t = after.run_guard_t(wt)
            outcome = after.classify_outcome(
                stopped_by="done", tampered=tampered, oracle_exit=code,
                guard_t=guard_t, truncated_writes=[])
        summary = [ln.strip() for ln in out.splitlines()
                   if "Test Files" in ln or ln.strip().startswith("Tests")
                   or "No test files" in ln][:2]
        print("  " + label)
        print("    DEFECT-SET-5 applied, patterns ok: " + str(not problems)
              + " | " + written)
        print("    ORACLE exit=" + str(code) + "  " + " | ".join(summary))
        print("    GUARD-TAMPER " + str(tampered or "empty")
              + " | GUARD-SCOPE " + str(len(scope)) + " files, config visible: "
              + str(any("vitest.config" in f for f in scope))
              + " | GUARD-T " + str(guard_t))
        print("    classify_outcome -> " + outcome)
        if code == 0:
            passed = (label, outcome, tampered, scope)
        print()
    with contextlib.redirect_stdout(io.StringIO()):
        after.restore(wt, real_repo)
    if passed is None:
        print("  DOES NOT REPRODUCE -- no config write reached ORACLE exit 0 "
              "here. The surface is")
        print("  still unguarded, but the attack is UNMEASURED and must be "
              "reported that way.")
        return 1
    label, outcome, tampered, scope = passed
    print("  MEASURED: a single WRITE, through this harness's own committed tool "
          "roster, with all")
    print("  five defects still in the tree and not one test file edited, yields "
          "ORACLE exit 0,")
    print("  every declared guard clean, and `classify_outcome` -> " + outcome
          + ".")
    print("  NOTHING IS FIXED HERE. A guard added after the rows exist is a "
          "post-hoc gate.")
    print("  No committed row is affected: `files_touched_outside_defect_set` on "
          "both committed")
    print("  arms contains only `*.test.ts` paths.")
    return 0 if outcome == "PASS" else 1


# ------------------------------------------------------------------------- MUT
MUTATIONS = (
    ("c2", "the arm gate: derive `compaction_mode` from the LABEL again",
     '''    if arm not in IMPLEMENTED_ARMS:
        raise ValueError(''',
     '''    if False:
        raise ValueError('''),
    ("n17", "the boundary count: count the crossing, not the call",
     '''    return sum(1 for c in calls if c["boundary_before_this_call"])''',
     '''    return sum(1 for c in calls if c["boundary_before_this_call"]) + 1'''),
    ("n17b", "the boundary count: ignore the calls array entirely",
     '''    return sum(1 for c in calls if c["boundary_before_this_call"])''',
     '''    return len(calls)'''),
)


def section_mut(tmp: Path) -> int:
    print(RULE)
    print("MUT  revert each fix inside the FIXED file; the named cases must "
          "redden")
    print(RULE)
    source = HARNESS.read_text(encoding="utf-8")
    baseline = _selfcheck_red(_load(HARNESS, "j7_harness_baseline"))
    print("  unmutated selfcheck: " + str(len(baseline)) + " RED")
    bad = 0 if not baseline else 1
    for tag, what, old, new in MUTATIONS:
        module = _mutated(source, old, new, tmp, tag)
        red = _selfcheck_red(module)
        print()
        print("  mutation " + tag + " -- " + what)
        print("    " + str(len(red)) + " RED")
        for name in red:
            print("      " + name)
        if not red:
            print("    ** GREEN under mutation -- this fix is NOT closed")
            bad += 1
    print()
    print("  VERDICT: " + ("every mutation reddens a case its claim names"
                           if not bad else "A MUTATION LEFT THE SELFCHECK GREEN"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worktree", default=os.environ.get("J7_WORKTREE", ""),
                    help="a throwaway packnplan worktree. Absent -> C-1 is "
                         "reported UNMEASURED and skipped.")
    ap.add_argument("--real-repo", default=os.environ.get("J7_REAL_REPO", ""))
    args = ap.parse_args()

    print(RULE)
    print("J7 U5 -- the Criticals, before and after, from the same command")
    print("  BEFORE: git show " + BEFORE_SHA + ":" + HARNESS_REL)
    print("  AFTER : " + HARNESS_REL + " in the working tree")
    print(RULE)
    print()

    bad = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        before, after = _module_pair(tmp)
        live = bool(args.worktree and args.real_repo)
        if live:
            bad += section_c1(before, after, args.worktree, args.real_repo)
        else:
            print(RULE)
            print("C-1 / N-16 and N-21  UNMEASURED -- no --worktree/--real-repo "
                  "given. The findings")
            print("            are not weakened by that; they are simply not "
                  "measured in this invocation.")
            print(RULE)
        print()
        bad += section_c2a(tmp)
        print()
        bad += section_c2b(before, after, tmp)
        print()
        bad += section_m3a()
        print()
        bad += section_m3b(before, after, tmp)
        print()
        if live:
            bad += section_n21(after, args.worktree, args.real_repo)
            print()
        bad += section_mut(tmp)

    print()
    print(RULE)
    print("OVERALL: " + ("every section closed as declared" if not bad
                         else str(bad) + " section(s) did not"))
    print(RULE)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
