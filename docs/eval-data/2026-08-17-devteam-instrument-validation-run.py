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
        check=False,
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
        committed = out.read_text()
        if committed != text:
            print(f"FAILED — regenerating {ARTIFACT} does not reproduce the committed bytes.")
            print(f"  committed: {len(committed)} B, {committed.count(chr(10))} rows")
            print(f"  regenerated: {len(text)} B, {text.count(chr(10))} rows")
            return 1
        print(RULE)
        print(f"OK — {ARTIFACT} regenerates byte-identically ({len(text)} B, {len(rows)} rows).")
        print(RULE)
        return 0

    out.write_text(text)
    print(RULE)
    print(f"WROTE {out.relative_to(root)} — {len(rows)} rows, {len(text)} B.")
    print("It is an instrument-validation artifact: evidence that four COLUMNS work on a real")
    print("entry point, and evidence of nothing else. Label:")
    print("  docs/eval-data/2026-08-17-devteam-instrument-validation.md")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
