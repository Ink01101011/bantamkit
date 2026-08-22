#!/usr/bin/env python3
"""INSTRUMENT-VALIDATION RUN — the four dark accounting columns, on a real entry point.

M6 of job `devteam-workload-and-null-control`, dated 2026-08-17, closing C2 of M5's
review ([F2](2026-08-17-devteam-review.md)): four of M3.5's eight accounting columns —
`repeat_reader_calls`, `collapsed_calls`, `collapsed_bytes`, `annotate_marker_bytes` —
read 0 in every one of the 96 committed ladder rows, and `annotate_marker_bytes` reads
0 even in A1, the arm whose only purpose is to annotate. RB-P28: the suite is not
evidence, so those four columns were pinned by nodes and by nothing else.

    python 2026-08-17-devteam-instrument-validation-run.py <repo-root>
    python 2026-08-17-devteam-instrument-validation-run.py <repo-root> --check

`--check` regenerates the artifact into a temporary file and requires it to be
BYTE-IDENTICAL to the committed one, so the committed rows are reproducible rather than
merely present. It writes nothing.

AMENDED 2026-08-17, J2/U1, filed as RB-P46 — the sentence above is kept as written and
this note is attached to it rather than replacing it. Byte-identity is still the first
thing `--check` tries and still the strongest result it can print. When it fails, the
check no longer stops there: it falls back to comparing **the committed file's own key
list**, row by row, allowing exactly the columns DECLARED in
`ADDITIVE_KEYS_THE_ARTIFACT_PREDATES` to be present on the regenerated side and absent
from the committed one. That is the same additive-field convention `evalrun.py` documents
in place and has now exercised three times, applied to the CHECKER instead of only to the
writer. What is deliberately NOT relaxed: the row count is still exact; every key the
committed file carries is compared by its serialised bytes, so `200` versus `200.0` still
fails; an UNDECLARED new key fails; a committed key deleted from the artifact fails; and
the committed keys reordered among themselves fail. Declaring a column is a dated edit to
a named tuple, so drift stays deliberate and recorded. Why this repair rather than
regenerating the `.jsonl`: see Amendment 3 of
`2026-08-17-devteam-instrument-validation.md`.

WHAT THIS RUN IS. Two `GRAPH_CONFIGS` arms — `graph-annotate` and `graph-cache` — over
the eight dev-team tasks, one pass each, driven through `bantamkit.evalrun.run_task`
(the same function `evalrun.main` calls per task, config and repeat) by M3's scripted
`WalkClient` replaying the manifest's verified reference walk. BOTH arms are needed
because they take different branches on a repeat: `cache` returns the collapse marker at
`filegraph.py:181` before the annotate branch is reached, so `annotate_marker_bytes` is
only reachable under `graph-annotate`.

WHAT THIS RUN IS NOT, and this is the whole reason it is a separate artifact with a
separate name. **This is not a fifth arm.** It is not a ladder measurement, its figures
are not comparable with A0-A3, and **no Δ% may be computed from it** (DO-NOT 21). It is
evidence that four COLUMNS work on a real entry point — that when a trajectory offers
the mechanism something to act on, the ledger records it and the row carries it. It is
NOT evidence that the mechanism saves anything: the arms' own realised repeat count at a
real endpoint is 0 on all eight tasks (bar §5 R3), and a scripted walk cannot change
that. Nothing in this file computes a delta, a ratio or a saving.

Three fences, mechanical rather than promised:
  * every row carries `kind: instrument-validation` and `ladder_arm: false`;
  * the filename is deliberately outside `2026-08-17-devteam-ladder-<config>.jsonl`, the
    only four names the ladder instrument loads;
  * there is exactly ONE row per (task, arm), so every per-task repeat spread is 0 and
    bar §3.2's floor is DEGENERATE on this artifact by the ladder instrument's own
    `floor_is_degenerate` — no delta computed from it could clear a floor even if
    someone ignored the label.

The client is a deterministic scripted walker, so `tokens` here is the payload-derived
surrogate `ceil(bytes/4)` (M3's note, bar §9/A1) and NOT an endpoint's `Usage`. That is
another reason no figure from this artifact belongs beside the ladder's arms, and it is
stated rather than hidden. The columns this artifact exists for — the six the ledger
sources — are real: the ledger is the same object the harness builds in a live run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

RULE = "=" * 94

# Both graph arms, because a repeat takes a different branch under each.
ARMS = ("graph-annotate", "graph-cache")

ARTIFACT = "2026-08-17-devteam-instrument-validation.jsonl"

DARK_COLUMNS = (
    "repeat_reader_calls",
    "collapsed_calls",
    "collapsed_bytes",
    "annotate_marker_bytes",
)

# RB-P46, 2026-08-17. Columns added to the row AFTER this artifact was committed, so
# the committed rows cannot carry them and `--check` must not read their absence as a
# failure to reproduce. Every entry is a dated, deliberate declaration — an undeclared
# new key still turns `--check` red, which is what keeps this from being a hole. Adding
# a column means adding a line here and amending the artifact's record; it is not a
# licence to stop checking.
#   * `model` — added by RB-P38's fix (J2/U1), the column that names which model
#     answered. This artifact's rows were written at `9561e8c`, before it existed.
ADDITIVE_KEYS_THE_ARTIFACT_PREDATES = ("model",)


def _load_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_rows(root: Path) -> list[dict]:
    """One `run_task` row per (task, arm), in a stable order, through M3's derivations.

    RB-P19: the scripted client, the reference-walk tool sequence and the manifest
    loader are IMPORTED from M3's committed field program rather than re-derived here,
    so there is one definition of "the reference walk" in this repo and this run walks
    the same trajectory M2's verifier verified and M3 and M3.5 priced.
    """
    m3 = _load_by_path(
        root / "docs" / "eval-data" / "2026-08-17-devteam-null-control-field-measurement.py",
        "m3_null",
    )
    evalrun, Message, Response, ToolCall, Usage = m3._import_bantamkit(root)
    WalkClient = m3.make_walk_client(Message, Response, ToolCall, Usage)
    specs = {t["name"]: t for t in m3.manifest(root)["tasks"]}
    tasks = evalrun.load_tasks(root / "assets" / "evals" / "devteam" / "tasks")

    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for arm in ARMS:
            for task in tasks:
                spec = specs[task["name"]]
                client = WalkClient(
                    m3.tool_sequence(spec), json.dumps(task["scoring"]["expected"])
                )
                result = evalrun.run_task(client, task, arm, workdir / arm)
                row = asdict(result)
                # The label travels WITH the numbers, on every row, because a caveat
                # that lives only in a document does not survive a copy-paste
                # (invariant 7). These three keys are why this file can never be
                # mistaken for one of the ladder's four arms.
                row["kind"] = "instrument-validation"
                row["ladder_arm"] = False
                row["client"] = WalkClient.model
                rows.append(row)
    return rows


def render(rows: list[dict]) -> str:
    return "".join(json.dumps(row) + "\n" for row in rows)


def compare_on_committed_keys(
    committed_text: str, regenerated: list[dict]
) -> tuple[list[str], list[str]]:
    """Compare regenerated rows against the committed file ON THE COMMITTED KEY SET.

    RB-P46. Returns `(problems, added_keys)`. `problems` is empty exactly when the
    committed file reproduces under the convention: the same row count; every
    regenerated key absent from the committed row is one of the DECLARED additions in
    `ADDITIVE_KEYS_THE_ARTIFACT_PREDATES`; the regenerated key list with those declared
    additions removed equals the committed row's key list exactly, in order; and the
    regenerated row restricted to the committed keys serialises to the committed line
    character for character. `added_keys` names the declared additions actually seen.

    This is not a loosening invented for convenience. It is the additive-field
    convention `evalrun.py` documents for the row, applied to the checker: a column
    added after the artifact was committed must not turn a reproduction check red, and
    NOTHING else may pass. The declaration is what makes that precise instead of
    permissive, and three of the four properties below were established by mutating a
    scratch copy rather than by assertion:

      * an UNDECLARED new key fails, wherever it sits. Tolerating unknown keys by
        position was tried first (the committed list as a strict prefix of the
        regenerated one) and is WRONG for this artifact: `model` is trailing on
        `TaskResult`, but `build_rows` appends `kind`, `ladder_arm` and `client` after
        `asdict()`, so in the ROW's key order the new column lands mid-list. The
        control went red. Position cannot carry this rule; a declaration can;
      * a key the committed file carries that the regenerated row does not fails, and
        so does a committed key DELETED from the artifact — it becomes an undeclared
        key on the regenerated side. A set-difference version of this function PASSED
        that mutation, which is the wrong repair wearing the right result;
      * the committed keys reordered among themselves fails;
      * a value that differs fails on serialised bytes, so `200` versus `200.0` fails.

    Adding the next column therefore means declaring it here, in a dated line, which is
    the point: the drift becomes a deliberate act with a record instead of a checker
    that quietly stops checking.
    """
    problems: list[str] = []
    committed_lines = [line for line in committed_text.splitlines() if line.strip()]
    if len(committed_lines) != len(regenerated):
        problems.append(
            f"row count: committed {len(committed_lines)}, "
            f"regenerated {len(regenerated)}"
        )
        return problems, []

    added: list[str] = []
    for index, (line, regen) in enumerate(
        zip(committed_lines, regenerated, strict=True)
    ):
        committed_keys = list(json.loads(line))
        residual = [
            key
            for key in regen
            if key in committed_keys or key not in ADDITIVE_KEYS_THE_ARTIFACT_PREDATES
        ]
        for key in regen:
            if key not in committed_keys and key not in added:
                added.append(key)
        if residual != committed_keys:
            problems.append(
                f"row {index}: the regenerated keys are not the committed keys plus "
                f"declared additions, so this is not an additive change"
            )
            problems.append(f"    committed keys:            {committed_keys}")
            problems.append(f"    regenerated, undeclared:   {residual}")
            continue
        projected = json.dumps({key: regen[key] for key in committed_keys})
        if projected != line:
            problems.append(f"row {index}: differs on a key the committed file carries")
            problems.append(f"    committed:   {line}")
            problems.append(f"    regenerated: {projected}")
    return problems, added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate and require byte-identity with the committed artifact; writes nothing",
    )
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    out = root / "docs" / "eval-data" / ARTIFACT

    print(RULE)
    print("INSTRUMENT-VALIDATION RUN — the four dark accounting columns, outside pytest")
    print(RULE)
    print(f"pytest in sys.modules: {'pytest' in sys.modules}   (must be False)")
    if "pytest" in sys.modules:
        print("FATAL: pytest is imported. This program is the evidence, not a node.")
        return 2
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    ).stdout.strip()
    print(f"repo root:             {root}")
    print(f"git HEAD:              {head or 'unknown'}")
    print("entry point:           bantamkit.evalrun.run_task (one pass per task and arm)")
    print(f"arms:                  {', '.join(ARMS)}  (a repeat branches differently in each)")
    print("client:                M3's scripted WalkClient on the verified reference walk")
    print(f"mode:                  {'--check (writes nothing)' if args.check else 'write'}")
    print("NOT a fifth arm:       no delta, no ratio and no saving is computed in this file")
    print()

    rows = build_rows(root)
    text = render(rows)

    hdr = (
        f"{'arm':16s}{'task':26s}{'read':>5s}{'unrec':>6s}{'rept':>5s}{'coll':>5s}"
        f"{'collB':>7s}{'annB':>6s}{'qryB':>6s}{'passed':>8s}"
    )
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        print(
            f"{row['config']:16s}{row['task']:26s}{row['reader_calls']:>5}"
            f"{row['unrecorded_reader_calls']:>6}{row['repeat_reader_calls']:>5}"
            f"{row['collapsed_calls']:>5}{row['collapsed_bytes']:>7}"
            f"{row['annotate_marker_bytes']:>6}{row['query_bytes']:>6}"
            f"{row['passed']!s:>8}"
        )
    print("-" * len(hdr))
    print()
    print("Rows carrying a non-zero value, per column that was dark in all 96 ladder rows:")
    for col in DARK_COLUMNS:
        hits = [f"{r['config']}/{r['task']}={r[col]}" for r in rows if r[col]]
        print(f"  {col:24s}{len(hits):>3} of {len(rows)} rows   {', '.join(hits) or '(none)'}")
    print()
    print("`collapsed_bytes` and `annotate_marker_bytes` are SIGNED and unclamped (bar §9/A4):")
    print("the collapse marker is 98-103 B and this surface's median file is 392 B, so a")
    print("collapse can COST bytes. Nothing here is floored at zero.")
    print()

    if args.check:
        if not out.exists():
            print(f"FAILED — {ARTIFACT} does not exist, so there is nothing to check against.")
            return 1
        committed = out.read_text(encoding="utf-8")
        if committed == text:
            print(RULE)
            print(
                f"OK — {ARTIFACT} regenerates byte-identically "
                f"({len(text)} B, {len(rows)} rows)."
            )
            print(RULE)
            return 0
        # Not byte-identical. RB-P46: that alone is not a failure, because the row is
        # under an additive trailing-field convention and a new column changes the
        # bytes without changing anything the committed file asserts. Fall back to the
        # committed file's OWN key set. Row count and every shared key stay exact.
        problems, added = compare_on_committed_keys(committed, rows)
        print(f"  committed: {len(committed)} B, {committed.count(chr(10))} rows")
        print(f"  regenerated: {len(text)} B, {text.count(chr(10))} rows")
        print(f"  keys the regenerated rows add: {', '.join(added) or '(none)'}")
        if problems:
            print(f"FAILED — regenerating {ARTIFACT} does not reproduce the committed rows.")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print(RULE)
        print(
            f"OK — {ARTIFACT} reproduces on every key the committed file carries "
            f"({committed.count(chr(10))} rows), and is NOT byte-identical: the "
            f"regenerated rows add {len(added)} DECLARED key(s) the committed file "
            f"predates ({', '.join(added)}). Additive only — no committed key changed, "
            f"none went missing, none moved, and the row count is unchanged."
        )
        print(RULE)
        return 0

    out.write_text(text, encoding="utf-8")
    print(RULE)
    print(f"WROTE {out.relative_to(root)} — {len(rows)} rows, {len(text)} B.")
    print("It is an instrument-validation artifact: evidence that four COLUMNS work on a real")
    print("entry point, and evidence of nothing else. Label:")
    print("  docs/eval-data/2026-08-17-devteam-instrument-validation.md")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
