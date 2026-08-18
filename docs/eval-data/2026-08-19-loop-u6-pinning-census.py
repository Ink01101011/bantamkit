#!/usr/bin/env python3
"""J7 U6: the pinning census — how many of the instrument's own cases are PINNED.

Bar section 9 requires that "the field program reports its own pinned-vs-unpinned
count as a number, not as 'no red'". U5's closure reports the three mutations and
their RED counts (0 / 4 / 5 / 5) and reports the selfcheck as "48 cases, 0 RED".
Neither of those is the census: "48 cases, 0 RED" is exactly the "no red" form the
bar forbids, and a per-mutation RED count says how wide each mutation reaches
without saying how much of the instrument no mutation reaches at all.

This program answers the question the bar asked, over two axes, both counted from
the OUTPUT and never from a source grep (RB-P48, invariant 7).

  CENSUS A -- the selfcheck's INTERNAL pinning. Every case is printed with a label
              the harness author chose: "green:" (the check on unmutated input),
              "RED:" (the same check on an input mutated in the DATA), or neither
              (a note that records a quantity). The count of "RED:"-labelled cases
              is the number of falsifying inputs the instrument carries.

  CENSUS B -- the instrument's EXTERNAL pinning. U5's three committed mutations
              are re-applied to the harness SOURCE and the reddened case set is
              collected. A case in that set is demonstrated load-bearing: revert
              the line and this case says so. A case outside it is UNPINNED --
              which does NOT mean vacuous (census A may still pin it from the data
              side) and does mean no committed source mutation demonstrates it.

  REGISTER  -- the RB-P ceiling on `feat/instrument-hygiene`, read with a regex
              that is not digit-bounded. The closure's section 8.1 used
              `grep -o 'RB-P5[4-9]'`, which cannot match RB-P60 however many
              exist. Reported as a measurement; UNMEASURED if the ref is absent.

WHAT IS **NOT** DONE HERE
  * No arm is run, nothing is regenerated, no `.jsonl` is read or written, and
    nothing is written anywhere on disk except inside a `TemporaryDirectory`
    (RB-P49).
  * No RB-P number is minted. J7's findings are N-nn, internal to the write-ups.
  * No token count and no duration is reported: nothing here calls ollama, so
    every such figure would be a self-estimate and is UNMEASURED (invariant 14).

USAGE
    python 2026-08-19-loop-u6-pinning-census.py
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HARNESS_REL = "docs/eval-data/2026-08-18-loop-harness.py"
HARNESS = REPO / HARNESS_REL
U5_PROGRAM = HERE / "2026-08-19-loop-u5-closure-field-measurement.py"
HYGIENE_REF = "feat/instrument-hygiene"
CLOSURE_REGEX = "RB-P5[4-9]"
HONEST_REGEX = r"RB-P[0-9]+"

RULE = "=" * 78


def _load(path: Path, name: str):
    """Import a program by path with its module-scope output suppressed."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("no import spec for " + str(path))
    module = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        spec.loader.exec_module(module)
    return module


def _selfcheck_lines(module) -> list[str]:
    """Run a module's own `selfcheck` and return its per-case lines verbatim."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        module.cmd_selfcheck(argparse.Namespace())
    return [ln for ln in buf.getvalue().splitlines()
            if ln.strip().startswith("[ok ]") or ln.strip().startswith("[RED]")]


def _case_id(line: str) -> str:
    """The case's identity: everything after the verdict marker.

    The harness prints a FIXED descriptive string beside each case, never the
    value it got, so a case's line is byte-identical whether it is green or red.
    That is what makes the green run and the mutated run comparable at all.
    """
    return line.split("] ", 1)[1].strip()


def _is_red(line: str) -> bool:
    return line.strip().startswith("[RED]")


def _mutate(source: str, old: str, new: str, tmp: Path, tag: str):
    if source.count(old) != 1:
        raise RuntimeError("mutation " + tag + " matches "
                           + str(source.count(old)) + " times, not once")
    path = tmp / ("harness_mut_" + tag + ".py")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return _load(path, "j7_u6_mut_" + tag)


# --------------------------------------------------------------------- census A
def census_a(lines: list[str]) -> int:
    print(RULE)
    print("CENSUS A  the selfcheck's INTERNAL pinning, counted from its own output")
    print(RULE)
    red_label = [ln for ln in lines if "RED:" in ln]
    green_label = [ln for ln in lines if "green:" in ln and "RED:" not in ln]
    notes = [ln for ln in lines
             if "RED:" not in ln and "green:" not in ln]
    total = len(lines)
    print("  cases printed                                      " + str(total))
    print("  labelled `RED:`  -- a falsifying input, asserted    "
          + str(len(red_label)) + " of " + str(total))
    print("  labelled `green:` -- the same check, unmutated      "
          + str(len(green_label)) + " of " + str(total))
    print("  unlabelled notes -- a quantity recorded, not paired "
          + str(len(notes)) + " of " + str(total))
    ok = len(red_label) + len(green_label) + len(notes) == total
    print()
    print("  the three classes partition the cases: " + ("yes" if ok else "NO"))
    print("  NOTE: a `RED:` case mutates the DATA the check reads. It does not")
    print("        demonstrate that the harness LINE under it is load-bearing;")
    print("        that is census B, and the two do not answer each other.")
    return 0 if ok else 1


# --------------------------------------------------------------------- census B
def census_b(lines: list[str], mutations, tmp: Path) -> int:
    print(RULE)
    print("CENSUS B  the instrument's EXTERNAL pinning -- U5's committed mutations")
    print(RULE)
    source = HARNESS.read_text(encoding="utf-8")
    all_cases = [_case_id(ln) for ln in lines]
    baseline_red = [c for ln, c in zip(lines, all_cases) if _is_red(ln)]
    print("  unmutated selfcheck: " + str(len(baseline_red)) + " RED of "
          + str(len(all_cases)))
    bad = 0 if not baseline_red else 1

    pinned: set[str] = set()
    for tag, what, old, new in mutations:
        module = _mutate(source, old, new, tmp, tag)
        mlines = _selfcheck_lines(module)
        red = {_case_id(ln) for ln in mlines if _is_red(ln)}
        unknown = red - set(all_cases)
        pinned |= red - unknown
        print()
        print("  mutation " + tag + " -- " + what)
        print("    " + str(len(red)) + " RED")
        if unknown:
            print("    ** " + str(len(unknown)) + " reddened case(s) are not in the "
                  "baseline case list -- the mutation changed the case set")
            bad += 1
        if not red:
            print("    ** GREEN under mutation -- this fix is NOT closed")
            bad += 1

    unpinned = [c for c in all_cases if c not in pinned]
    print()
    print("  " + RULE[:74])
    print("  THE COUNT, as a number and not as `no red`:")
    print("    PINNED   by at least one committed source mutation  "
          + str(len(pinned)) + " of " + str(len(all_cases)))
    print("    UNPINNED by every committed source mutation         "
          + str(len(unpinned)) + " of " + str(len(all_cases)))
    print("  " + RULE[:74])
    print()
    print("  the UNPINNED cases, named rather than summarised:")
    for c in unpinned:
        print("    - " + c)
    print()
    print("  READ THIS THE NARROW WAY. `UNPINNED` here means: no mutation committed")
    print("  by this job reverts a harness line that this case would catch. It does")
    print("  NOT mean the case is vacuous -- most of these are `RED:` cases in")
    print("  census A, i.e. falsified from the DATA side. The honest reading is that")
    print("  J7 mutated the two lines it FIXED and left the rest of the instrument")
    print("  unmutated, which is a disclosed gap and is the reason for this count.")
    return 0 if not bad else 1


# --------------------------------------------------------------------- register
def _resolve_ref() -> str:
    """The ref's SHA. The branch is LIVE, so the name is not a pin (invariant 13)."""
    try:
        return subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", HYGIENE_REF],
            capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _grep_ref(pattern: str) -> tuple[bool, list[str]]:
    """Read `docs/eval.md` at an unmerged ref and return the sorted RB-P matches."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "show", HYGIENE_REF + ":docs/eval.md"],
            capture_output=True, text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return False, []
    found = sorted(set(re.findall(pattern, out)),
                   key=lambda s: int(re.sub(r"\D", "", s)))
    return True, found


def section_register() -> int:
    print(RULE)
    print("REGISTER  what the closure's own regex could not have seen")
    print(RULE)
    reachable, honest = _grep_ref(HONEST_REGEX)
    if not reachable:
        print("  UNMEASURED -- `" + HYGIENE_REF + "` is not present in this "
              "checkout.")
        print("  The finding is not weakened by that; it is simply not measured "
              "in this invocation.")
        return 0
    _, narrow = _grep_ref(CLOSURE_REGEX)
    high_honest = [s for s in honest if int(re.sub(r"\D", "", s)) >= 54]
    print("  ref                        " + HYGIENE_REF + " @ " + _resolve_ref())
    print("  closure section 8.1 regex  " + CLOSURE_REGEX
          + "   -> " + str(len(narrow)) + " distinct: " + " ".join(narrow))
    print("  digit-unbounded regex      " + HONEST_REGEX
          + " -> " + str(len(high_honest)) + " distinct >= 54: "
          + " ".join(high_honest))
    missed = [s for s in high_honest if s not in narrow]
    print()
    if missed:
        print("  MISSED BY THE CLOSURE'S REGEX: " + " ".join(missed))
        print("  `RB-P5[4-9]` cannot match a two-digit tail past 59 however many")
        print("  exist, so the closure's `RB-P54 through RB-P59` is an artefact of")
        print("  the instrument, not a reading of the register. The next free")
        print("  number is " + "RB-P"
              + str(max(int(re.sub(r"\D", "", s)) for s in honest) + 1)
              + " AT THIS SHA, and an orchestrator that took")
        print("  `the next one after` the closure's ceiling would have collided a")
        print("  THIRD time tonight.")
    else:
        print("  the two regexes agree; nothing above the closure's ceiling.")
    print()
    print("  THE CEILING IS A SNAPSHOT, NOT A PIN. That ref is a LIVE branch and it")
    print("  moved under this unit inside one session: at `8544768` the register")
    print("  topped out at RB-P60, and the reading above is a later commit. Re-run")
    print("  this section at the moment of minting; do not carry the number.")
    print("  Nothing is minted here. The `docs/eval.md` filing of J7's findings is")
    print("  DEFERRED until `" + HYGIENE_REF + "` lands, at which point the")
    print("  numbers are read at HEAD and assigned by the orchestrator.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="J7 U6 pinning census")
    ap.parse_args()

    print(RULE)
    print("J7 U6 -- the pinning census over " + HARNESS_REL)
    print("  mutations are U5's, imported from " + U5_PROGRAM.name)
    print(RULE)
    print()

    harness = _load(HARNESS, "j7_u6_harness")
    lines = _selfcheck_lines(harness)
    u5 = _load(U5_PROGRAM, "j7_u6_u5_program")

    bad = 0
    bad += census_a(lines)
    print()
    with tempfile.TemporaryDirectory() as td:
        bad += census_b(lines, u5.MUTATIONS, Path(td))
    print()
    bad += section_register()

    print()
    print(RULE)
    print("OVERALL: " + ("every section closed as declared" if not bad
                         else str(bad) + " section(s) did not"))
    print(RULE)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
