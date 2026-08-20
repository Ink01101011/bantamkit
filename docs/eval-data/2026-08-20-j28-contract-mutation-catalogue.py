#!/usr/bin/env python3
"""RB-P89. A committed, rerunnable must-be-red catalogue over the contract asset's strings.

Every provenance comment in `docs/eval.md` that quotes a laundering measurement attributes it
to "a Z2 mutation script over a `git archive` tree" — a script that was never committed and no
longer exists. So the program's central anti-laundering discipline has been a procedure
re-improvised each time, and `RB-P89` is what that costs: `c2cfb89`'s `M5` reworded
`tool_argument_types` (the frame) and never reworded `tool_argument_type` (the item), so the one
node that reddens ONLY on the item was invisible to a catalogue that had been re-run with every
column checked. An unmeasured check is not a passed one (`RB-P51`), applied to the mutation.

WHAT THIS MEASURES

For each top-level string of `assets/contracts/default.yaml`, reword that string and only that
string, run the whole `runtime-py/tests` suite against the reworded asset pack, and record which
test nodes go red that were not red at baseline. A string is then one of:

  PINNED-BY-NAME   at least one newly-red node's NAME declares that it asserts wording
                   (`_verbatim`, `_bytes`, `golden`, `wording`, `phrasing`). Such a node is
                   entitled to redden on a rewording: that is the claim its name makes.
  LAUNDERING       nodes went red and NOT ONE of them declares wording in its name. Every red
                   is a node whose name promises a different claim; the rewording is laundering
                   into its column. This is the class section S named and section T made a
                   procedure for.
  UNPINNED         nothing went red. The string can be reworded into anything and the suite
                   stays green. Nobody has ever measured this figure.
  BROKEN           the tree did not collect. Not evidence about anything; exits non-zero.

The verdict is derived from the node NAME by a fixed predicate applied identically to all 34
keys. The author does not get to choose which nodes count — that is the loophole
`2026-08-14-pinning-harness-false-positives.md` filed and could not close, closed here for this
one surface by giving up the per-claim `pins` list entirely.

Separately, and for every string including the PINNED-BY-NAME ones, the newly-red nodes that do
NOT declare wording are listed as `laundered`. Those are individual `RB-P89` instances even when
the string as a whole is pinned by a node that does name its reason.

COVERAGE — what is mutated, what is not, and why

  MUTATED   the 33 top-level double-quoted scalars of `assets/contracts/default.yaml`. Every
            one of them is a model-facing sentence. 32 of the 33 produce a real mutant under
            `--mode prose`; the 33rd (`document_error`) needs `--mode whole` and is EXCLUDED
            with its reason printed otherwise.
  NOT       `name: default` (line 1). It is the pack's identifier, not a sentence any model
            reads; rewording it is an identity change and not a rewording. Laundering under a
            change to `name` is UNMEASURED.
  NOT       the PLACEHOLDER NAMES inside each string (`{tool}`, `{problems}`, ...). A renamed
            placeholder is a `KeyError` at format time, not a rewording, and would report a
            crash rather than a pin. Laundering under a placeholder rename is UNMEASURED.
  NOT       the YAML comments. They are not loaded and cannot be asserted on. (`--calibrate`
            mutates one deliberately, as its negative control.)
  NOT       any asset outside `assets/contracts/default.yaml`: the tool schemas, the profiles,
            the skills. Laundering under those is UNMEASURED by this program.
  NOT       `runtime-ts`. This runs `runtime-py/tests` only; the TypeScript suite is not
            covered and laundering there is UNMEASURED.

MUTATION SHAPE

  --mode prose (default)  every alphabetic word of the string's LITERAL text is reworded, except
                          a leading `error: ` marker, which is machine-readable structure rather
                          than prose. This is the shape `M5` had.
  --mode whole            the same, including the leading `error: ` marker. The two modes differ
                          only on the 7 strings that carry that marker; on every other key the
                          two mutants are byte-identical and one run answers both.

Rewording is `word -> word[0] + "q" + word[1:]`, applied to every alphabetic run. It is not a
synonym swap: it is strictly more sensitive than one, because a node asserting ANY word of the
sentence reddens under it, and that is the question a pinning catalogue asks. Placeholders and
backslash escapes are never touched, so every mutant still formats.

A string with no alphabetic run has its PUNCTUATION rewritten instead — `evidence_line` is
`"{name}({arguments}) -> {observation}"` and its punctuation is the whole of what it says. One
string is still a no-op and so still EXCLUDED: `document_error` under `--mode prose`, which is
the `error: ` marker and `{detail}` and nothing else. `--mode whole` mutates it.

RUN IT (from the repository root; ~31s per key, so pass --jobs)

    PYTHONPATH=$PWD/runtime-py/src python3 \
      docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --jobs 5

    ... --calibrate      run only the two known answers; exits 1 if either fails
    ... --mode whole     the `error: ` marker included
    ... --only KEY       one key (repeatable)
    ... --out FILE       write the table to FILE. NOT the committed
                         `2026-08-20-j28-contract-mutation-catalogue.md`, which is a written
                         record around this table and would be overwritten by it.

`--calibrate` is the reason any number here may be read. An instrument that grades evidence may
not grade itself, so it is measured against two answers known by hand:

    CAL-RED    reword `schema_instruction`, which `test_layers.py::test_schema_instruction_bytes`
               pins by name  ->  must read PINNED-BY-NAME
    CAL-GREEN  reword a yaml COMMENT and no string at all  ->  must read UNPINNED

CAL-GREEN is the control the pinning harness lost in 2026-08-14: without it, an instrument that
reports every string PINNED cannot be told from a detector stuck on. Both must come back or the
run exits non-zero.
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "assets" / "contracts" / "default.yaml"
TESTS = "runtime-py/tests"

# A node whose NAME declares that it asserts the contract's wording. Applied identically to
# every key; nothing here is per-string, so no author chooses a string's killers.
WORDING_TOKENS = ("verbatim", "bytes", "golden", "wording", "phrasing")

KEY_LINE = re.compile(r'^([a-z_][a-z0-9_]*): (.*)$')
# Ordered alternation: escapes and placeholders are consumed before any word inside them can be.
TOKENS = re.compile(r'\\.|\{[^{}]*\}|[A-Za-z]+|.', re.DOTALL)
ERROR_MARKER = "error: "
# The fallback for a string that is nothing but placeholders and punctuation. `evidence_line`
# is `"{name}({arguments}) -> {observation}"`: it carries no word to reword, and a catalogue
# that skipped it would leave the one string whose whole content is structure UNMEASURED.
PUNCTUATION = {"(": "[", ")": "]", "-": "=", ">": "*", ":": ";", ".": "!", ",": ";", "/": "|"}


def reword(literal: str, *, keep_marker: bool) -> str:
    """Reword every alphabetic run of `literal`, leaving placeholders and escapes untouched.

    A string with no alphabetic run at all falls back to rewriting its punctuation, which is
    the whole of what such a string says.
    """
    prefix = ""
    if keep_marker and literal.startswith(ERROR_MARKER):
        prefix, literal = ERROR_MARKER, literal[len(ERROR_MARKER):]
    tokens = TOKENS.findall(literal)
    out = [token[0] + "q" + token[1:] if token.isalpha() else token for token in tokens]
    if out == tokens:
        out = [PUNCTUATION.get(token, token) for token in tokens]
    return prefix + "".join(out)


def contract_keys(text: str) -> list[tuple[str, int, str]]:
    """Every top-level key of the contract, as (key, line index, raw value text)."""
    keys = []
    for i, line in enumerate(text.splitlines()):
        m = KEY_LINE.match(line)
        if m:
            keys.append((m.group(1), i, m.group(2)))
    return keys


def mutate_contract(text: str, key: str, *, keep_marker: bool) -> str:
    """Return `text` with exactly `key`'s quoted value reworded. Raises if it is not quoted."""
    lines = text.splitlines(keepends=True)
    for _key, index, value in contract_keys(text):
        if _key != key:
            continue
        if not (value.startswith('"') and value.rstrip().endswith('"')):
            raise ValueError(f"{key}: not a double-quoted scalar; excluded by the coverage note")
        raw = value.rstrip()
        body = raw[1:-1]
        mutant = reword(body, keep_marker=keep_marker)
        if mutant == body:
            raise ValueError(f"{key}: the rewording is a no-op; it would measure nothing")
        lines[index] = lines[index].replace(raw, '"' + mutant + '"', 1)
        return "".join(lines)
    raise KeyError(key)


def mutate_comment(text: str) -> str:
    """CAL-GREEN: change a yaml COMMENT, which no loaded string can carry."""
    for i, line in enumerate(text.splitlines()):
        if line.startswith("# "):
            lines = text.splitlines(keepends=True)
            lines[i] = lines[i].replace("# ", "# CAL-GREEN, a comment nobody loads. ", 1)
            return "".join(lines)
    raise ValueError("no comment to mutate")


def run_suite(contract_text: str, workdir: Path) -> tuple[int, set[str]]:
    """Run the whole suite against an asset pack whose contract is `contract_text`."""
    pack = workdir / "assets"
    shutil.copytree(REPO / "assets", pack)
    (pack / "contracts" / "default.yaml").write_text(contract_text)
    env = dict(os.environ)
    env["BANTAMKIT_ASSETS"] = str(pack)
    env["PYTHONPATH"] = str(REPO / "runtime-py" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TESTS, "-q", "--tb=no",
         "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=REPO, env=env, capture_output=True, text=True, check=False,
    )
    failed = {
        line.split(" ", 1)[1].split(" - ")[0].strip()
        for line in proc.stdout.splitlines()
        if line.startswith("FAILED ")
    }
    collected = re.search(r"^(ERROR|INTERNALERROR)", proc.stdout, re.MULTILINE)
    if collected and not failed:
        return 2, set()
    return (0 if proc.returncode == 0 else 1), failed


def measure(contract_text: str) -> tuple[int, set[str]]:
    with tempfile.TemporaryDirectory(prefix="j28-catalogue-") as tmp:
        return run_suite(contract_text, Path(tmp))


def node_name(nodeid: str) -> str:
    return nodeid.split("::")[-1].split("[")[0]


def names_wording(nodeid: str) -> bool:
    name = node_name(nodeid)
    return any(token in name for token in WORDING_TOKENS)


def classify(rc: int, new_red: set[str]) -> str:
    if rc == 2:
        return "BROKEN"
    if not new_red:
        return "UNPINNED"
    if any(names_wording(n) for n in new_red):
        return "PINNED-BY-NAME"
    return "LAUNDERING"


def measure_key(key: str, base_text: str, baseline: set[str], keep_marker: bool) -> dict:
    started = time.time()
    try:
        mutant = mutate_contract(base_text, key, keep_marker=keep_marker)
    except ValueError as exc:
        return {"key": key, "verdict": "EXCLUDED", "why": str(exc),
                "new_red": [], "laundered": [], "named": []}
    rc, failed = measure(mutant)
    new_red = sorted(failed - baseline)
    row = {
        "key": key,
        "verdict": classify(rc, set(new_red)),
        "new_red": new_red,
        "named": [n for n in new_red if names_wording(n)],
        "laundered": [n for n in new_red if not names_wording(n)],
        "seconds": round(time.time() - started, 1),
    }
    print(f"  {row['verdict']:<15} {key:<28} {len(new_red)} new red", flush=True)
    return row


def calibrate(base_text: str, baseline: set[str], keep_marker: bool) -> int:
    print("calibration — two answers known by hand")
    red = measure_key("schema_instruction", base_text, baseline, keep_marker)
    ok_red = red["verdict"] == "PINNED-BY-NAME"
    print(f"  CAL-RED    expected PINNED-BY-NAME   measured {red['verdict']}"
          f"   {'OK' if ok_red else 'FAILED'}")
    rc, failed = measure(mutate_comment(base_text))
    green = sorted(failed - baseline)
    ok_green = rc == 0 and not green
    print(f"  CAL-GREEN  expected UNPINNED         measured "
          f"{'UNPINNED' if ok_green else 'RED: ' + ', '.join(green)}"
          f"   {'OK' if ok_green else 'FAILED'}")
    return 0 if (ok_red and ok_green) else 1


def render(rows: list[dict], mode: str, commit: str, baseline: set[str]) -> str:
    live = [r for r in rows if r["verdict"] != "EXCLUDED"]
    by = {v: [r for r in live if r["verdict"] == v] for v in
          ("PINNED-BY-NAME", "LAUNDERING", "UNPINNED", "BROKEN")}
    laundered_rows = [r for r in live if r["laundered"]]
    out = [
        "# The contract surface's must-be-red catalogue",
        "",
        (f"Generated by `docs/eval-data/{Path(__file__).name}` at `{commit}`, "
         f"mode `{mode}`, over `{TESTS}`."),
        f"Baseline failures: {len(baseline)}. Keys in the asset: {len(rows)}.",
        "",
        "| key | verdict | new red | of which name wording | of which do not |",
        "|---|---|---:|---:|---:|",
    ]
    for r in rows:
        out.append(f"| `{r['key']}` | {r['verdict']} | {len(r['new_red'])} | "
                   f"{len(r['named'])} | {len(r['laundered'])} |")
    out += [
        "",
        "## The three numbers",
        "",
        (f"- pinned by at least one node that names its reason: "
         f"**{len(by['PINNED-BY-NAME'])} of {len(live)}**"),
        (f"- pinned ONLY by nodes whose names promise a different claim (laundering): "
         f"**{len(by['LAUNDERING'])} of {len(live)}**"),
        f"- pinned by nothing at all: **{len(by['UNPINNED'])} of {len(live)}**",
        f"- broken mutants (not evidence): **{len(by['BROKEN'])}**",
        "",
        (f"Strings with at least one laundering node, pinned or not: "
         f"**{len(laundered_rows)} of {len(live)}**."),
        "",
        "## Every laundering instance, by string",
        "",
    ]
    if not laundered_rows:
        out.append("None.")
    for r in laundered_rows:
        out.append(f"- `{r['key']}` ({r['verdict']})")
        for node in r["laundered"]:
            out.append(f"  - `{node}`")
    out += ["", "## Strings pinned by nothing", ""]
    out.append(", ".join(f"`{r['key']}`" for r in by["UNPINNED"]) or "None.")
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("prose", "whole"), default="prose")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--json")
    args = ap.parse_args()

    keep_marker = args.mode == "prose"
    base_text = CONTRACT.read_text()
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, check=False).stdout.strip()
    # A dirty tree is not the commit it names, and a table headed with a commit it was not
    # measured at is the defect this whole program exists to make checkable.
    if subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                      capture_output=True, text=True, check=False).stdout.strip():
        commit += "-dirty"
    print(f"repo {REPO}\nmode {args.mode}  commit {commit}")

    rc, baseline = measure(base_text)
    print(f"baseline: rc={rc}, {len(baseline)} failing nodes")
    if rc != 0:
        print("the unmutated tree is not green; nothing measured here would be evidence")
        return 2

    if args.calibrate:
        return calibrate(base_text, baseline, keep_marker)

    keys = [k for k, _, _ in contract_keys(base_text)]
    if args.only:
        keys = [k for k in keys if k in args.only]
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        rows = list(pool.map(lambda k: measure_key(k, base_text, baseline, keep_marker), keys))

    report = render(rows, args.mode, commit, baseline)
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report)
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2) + "\n")
    return 1 if any(r["verdict"] == "BROKEN" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
