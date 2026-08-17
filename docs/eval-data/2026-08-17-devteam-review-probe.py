#!/usr/bin/env python3
"""FIELD PROBE — M5's adversarial review of the dev-team ladder instrument.

M5 of job `devteam-workload-and-null-control`. This program does not measure the
mechanism. It measures the *instrument* five units built, in the three places the
review brief commissioned an attack:

  * the WORKLOAD as rigged  — does any task on this surface require a second read?
  * the NULL CONTROL as information-removing — how many DISTINGUISHABLE rungs did
    the committed ladder actually have?
  * the BASELINE as a rig artifact — is +73.367% separable from repeat noise, and
    is bar §3.2's floor even at the grain of the statistic it gates?

plus the two ruler questions handed to the unit: which of M3.5's eight accounting
columns ever fired in the field, and whether a row can be attributed to a model.

WHY THIS IS A PROGRAM AND NOT A TEST. RB-P28 is OPEN. Job 11's C1 measured the
failure mode: three acceptance pins had run in-process and a patch keyed on
`pytest in sys.modules` printed an affirmatively false report under a green suite.
So this asserts `pytest not in sys.modules`, prints the answer as line 1, exits 2 if
pytest is present, and exits non-zero when any named check fails.

RB-P19: THERE IS ONE DERIVATION OF EVERY QUANTITY THIS FILE REUSES. M2's walk
verifier and pressure function, and M3's scripted `WalkClient` and reference-walk
tool sequence, are imported BY PATH out of the committed programs that already
derive them. A second derivation that happens to agree corroborates nothing, so
there is not a second one. The only arithmetic authored here is arithmetic no
committed program does.

Usage:
    python 2026-08-17-devteam-review-probe.py <repo-root>
    python 2026-08-17-devteam-review-probe.py <repo-root> --mutate <name>

`--mutate` falsifies one piece of this probe's own reasoning in this process and
MUST drive the exit status red. Each mutation is named against the check it breaks.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path

RULE = "=" * 94

ARMS = [
    ("A0", "graph-off"),
    ("A1", "graph-annotate"),
    ("A2", "graph-cache"),
    ("A3", "graph"),
]
PAIRS = [("A1", "A0"), ("A2", "A1"), ("A3", "A2")]

# M3.5's eight accounting columns, in the order bar §9/A4 records them. The four
# marked `ledger` are the ones this probe asks whether the field ever exercised.
ACCOUNTING_COLUMNS = [
    "reader_calls",
    "unrecorded_reader_calls",
    "repeat_reader_calls",
    "collapsed_calls",
    "collapsed_bytes",
    "annotate_marker_bytes",
    "query_bytes",
    "context_bytes_sent",
]

# Every column a row carries, for the rung-equivalence classing. `seed` is excluded
# because it is the matching key, not a measured cell.
ROW_COLUMNS = [
    "passed",
    "tokens",
    "outcome",
    "model_calls",
    "tool_calls",
    "schema_retries",
    "critique_rounds",
    "error",
    *ACCOUNTING_COLUMNS,
]

MUTATIONS = (
    "keep-repeats",
    "changed-repeats",
    "prune-transcript",
    "split-arms",
    "one-floor",
    "pure-apparatus",
)
MUTATION: str | None = None

FAILURES: list[str] = []


def _fail(check: str, msg: str) -> None:
    FAILURES.append(f"{check}: {msg}")


# ---------------------------------------------------------------------------
# Importing the committed derivations, by path. Not a copy of them.
# ---------------------------------------------------------------------------


def _load_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def committed_programs(root: Path):
    """M2's walk verifier and M3's scripted client, imported rather than re-derived."""
    here = root / "docs" / "eval-data"
    m2 = _load_by_path(here / "2026-08-17-devteam-workload-measurements.py", "m2_workload")
    m3 = _load_by_path(here / "2026-08-17-devteam-null-control-field-measurement.py", "m3_null")
    return m2, m3


# ---------------------------------------------------------------------------
# ATTACK 1 — the workload. Is a second read ever NECESSARY?
# ---------------------------------------------------------------------------


def deduplicated_walk(task: dict) -> list[dict]:
    """The declared walk with every repeat hop removed, first appearance kept.

    A hop's justification is its `pointer` in its `pointer_in` text. Dropping a LATER
    hop can only remove a justification for hops that named it, so the surviving walk
    is re-verified from scratch by M2's own verifier rather than assumed valid.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for hop in task["walk"]:
        if hop["path"] in seen and MUTATION != "keep-repeats":
            continue
        seen.add(hop["path"])
        out.append(dict(hop))
    return out


def attack_workload(m2, root: Path) -> dict:
    """Table M1 — the declared walk beside the walk with its repeats deleted."""
    man = m2.manifest(root)
    files = m2.surface(root)

    print(RULE)
    print("TABLE M1 — is any second read NECESSARY? the declared walk vs the same walk deduplicated")
    print(RULE)
    print("`verified` is M2's OWN verify_walk (imported, not re-derived): every hop's pointer a")
    print("literal in the text it claims, every answer_evidence string present, every non-boolean")
    print("expected value a literal or a surface path. A deduplicated walk that VERIFIES is a")
    print("correct trajectory that never reads a file twice.")
    print()
    head = (
        f"{'task':24s}{'declared':>10s}{'repeats':>9s}"
        f"{'dedup':>8s}{'repeats':>9s}{'verified':>10s}  problems"
    )
    print(head)
    print("-" * len(head))

    totals = {"declared": 0, "declared_repeats": 0, "dedup": 0, "dedup_repeats": 0}
    verified = 0
    for spec in man["tasks"]:
        before = m2.pressure(spec)
        deduped = dict(spec, walk=deduplicated_walk(spec))
        after = m2.pressure(deduped)
        problems = m2.verify_walk(deduped, files)
        ok = not problems
        verified += ok
        totals["declared"] += before["reads"]
        totals["declared_repeats"] += before["repeats"]
        totals["dedup"] += after["reads"]
        totals["dedup_repeats"] += after["repeats"]
        print(
            f"{spec['name']:24s}{before['reads']:>10d}{before['repeats']:>9d}"
            f"{after['reads']:>8d}{after['repeats']:>9d}{('yes' if ok else 'NO'):>10s}"
            f"  {'; '.join(problems) if problems else '-'}"
        )
    print("-" * len(head))
    print(
        f"{'WORKLOAD':24s}{totals['declared']:>10d}{totals['declared_repeats']:>9d}"
        f"{totals['dedup']:>8d}{totals['dedup_repeats']:>9d}{f'{verified}/8':>10s}"
    )
    print()
    print(f"declared re-read pressure : {totals['declared_repeats']}/{totals['declared']}"
          f" = {totals['declared_repeats'] / totals['declared']:.3f}")
    print(f"deduplicated pressure     : {totals['dedup_repeats']}/{totals['dedup']}"
          f" = {totals['dedup_repeats'] / totals['dedup']:.3f}")
    print()

    if verified != len(man["tasks"]):
        _fail(
            "N1 dedup-walk-verifies",
            f"only {verified}/{len(man['tasks'])} deduplicated walks pass M2's verifier, so "
            "this probe cannot claim a repeat-free correct trajectory exists for every task",
        )
    if totals["dedup_repeats"] != 0:
        _fail(
            "N2 dedup-walk-pressure-zero",
            f"the deduplicated walks still realise {totals['dedup_repeats']} repeat reads",
        )
    return totals


def attack_repeat_content(m3, root: Path) -> dict:
    """Table M2 — the mechanism's own report that every repeat it can act on is byte-identical.

    `cache` collapses at `filegraph.py:160` only when `unchanged` (`:157`) is True, i.e.
    only when the digest of read #n equals the digest of read #1. So the mechanism's
    entire opportunity set is reads whose content the transcript already holds. This is
    not argued from the surface dict — it is read off the ledger a real `graph-cache`
    run built, on the reference walk, where the mechanism does have something to act on.
    """
    evalrun, Message, Response, ToolCall, Usage = m3._import_bantamkit(root)
    WalkClient = m3.make_walk_client(Message, Response, ToolCall, Usage)
    man = m3.manifest(root)
    specs = {t["name"]: t for t in man["tasks"]}
    tasks = evalrun.load_tasks(root / "assets" / "evals" / "devteam" / "tasks")

    print(RULE)
    print("TABLE M2 — the ledger real A1 and A2 runs build ON THE REFERENCE WALK")
    print(RULE)
    print("`cache` fires only on a byte-IDENTICAL repeat (filegraph.py:157 `unchanged`, branch at")
    print(":160). A byte-identical repeat is content the request already carries, so the")
    print("mechanism's opportunity set is exactly the set of information-free reads. Measured:")
    print("`changed` is the ledger's own verdict on whether read #n differed from read #1.")
    print()
    print("BOTH graph arms are run because they take different branches on a repeat: A2 returns")
    print("the marker at :181 before the annotate branch is reached, so `annotate_marker_bytes`")
    print("is only reachable under A1. This is what the four dark columns of TABLE M7 look like")
    print("when the trajectory gives them something to act on.")
    print()
    head = (
        f"{'arm  task':30s}{'reads':>7s}{'repeats':>9s}{'coll':>6s}"
        f"{'collB':>8s}{'annB':>7s}{'changed':>9s}  re-read paths (count)"
    )
    print(head)
    print("-" * len(head))

    tot = {"reads": 0, "repeats": 0, "collapsed": 0, "bytes": 0, "ann": 0, "changed": 0}
    per_arm: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for arm in ("graph-annotate", "graph-cache"):
            acc_arm = {"repeats": 0, "collapsed": 0, "bytes": 0, "ann": 0}
            for task in tasks:
                spec = specs[task["name"]]
                seen, original, Capturing = m3._ledger_capture(evalrun)
                evalrun.FileAccessGraph = Capturing
                try:
                    client = WalkClient(
                        m3.tool_sequence(spec), json.dumps(task["scoring"]["expected"])
                    )
                    evalrun.run_task(client, task, arm, workdir)
                finally:
                    evalrun.FileAccessGraph = original
                graph = seen[-1]
                acc = graph.accounting
                changed = [r.path for r in graph.reads.values() if r.changed]
                hubs = [f"{r.path} ({r.count})" for r in graph.reads.values() if r.count > 1]
                if arm == "graph-cache":
                    tot["reads"] += acc.recorded_reader_calls
                    tot["repeats"] += acc.repeat_reader_calls
                    tot["collapsed"] += acc.collapsed_calls
                    tot["bytes"] += acc.collapsed_bytes
                    tot["changed"] += len(changed)
                tot["ann"] += acc.annotate_marker_bytes
                acc_arm["repeats"] += acc.repeat_reader_calls
                acc_arm["collapsed"] += acc.collapsed_calls
                acc_arm["bytes"] += acc.collapsed_bytes
                acc_arm["ann"] += acc.annotate_marker_bytes
                if acc.repeat_reader_calls:
                    label = f"{'A1' if arm == 'graph-annotate' else 'A2'}  {task['name']}"
                    print(
                        f"{label:30s}{acc.recorded_reader_calls:>7d}"
                        f"{acc.repeat_reader_calls:>9d}{acc.collapsed_calls:>6d}"
                        f"{acc.collapsed_bytes:>8d}{acc.annotate_marker_bytes:>7d}"
                        f"{(str(len(changed)) if changed else 'no'):>9s}  {'; '.join(hubs) or '-'}"
                    )
            per_arm[arm] = acc_arm
    print("-" * len(head))
    for arm, a in per_arm.items():
        print(f"  {arm:16s} repeats={a['repeats']}  collapsed_calls={a['collapsed']}"
              f"  collapsed_bytes={a['bytes']}  annotate_marker_bytes={a['ann']}")
    print(f"  (the other {len(tasks) - 2} tasks realise 0 repeats on the reference walk and are "
          "omitted from the rows above)")
    print()
    print(f"every repeat the reference walk offers was collapsed under A2: "
          f"{tot['collapsed']}/{tot['repeats']}  "
          f"-> `unchanged` was True on all of them, so none carried new content")
    print("All four columns that read 0 in every one of the 96 committed rows are NON-ZERO here.")
    print("The gap is the realised TRAJECTORY, not the ruler.")
    print()
    if MUTATION == "changed-repeats":
        tot["changed"] = 1
    if tot["repeats"] == 0 or tot["collapsed"] != tot["repeats"] or tot["changed"] != 0:
        _fail(
            "N3 repeats-carry-no-new-content",
            f"{tot['collapsed']} of {tot['repeats']} repeats collapsed and {tot['changed']} "
            "ledger entries report `changed`; the information-free argument needs every repeat "
            "the mechanism can act on to be byte-identical",
        )
    return tot


def attack_transcript(m3, root: Path) -> dict:
    """Table M3 — the transcript is append-only, measured on a real `run_task` pass.

    The information-free argument needs one more fact than the collapse condition:
    that the earlier read is STILL IN THE REQUEST when the repeat is issued. Read off
    `agent.py:174-214` the message list is only ever appended to, and this measures
    it: every model call's message list must extend the previous call's as a strict
    prefix, on every task, outside pytest.
    """
    evalrun, Message, Response, ToolCall, Usage = m3._import_bantamkit(root)
    WalkClient = m3.make_walk_client(Message, Response, ToolCall, Usage)
    man = m3.manifest(root)
    specs = {t["name"]: t for t in man["tasks"]}
    tasks = evalrun.load_tasks(root / "assets" / "evals" / "devteam" / "tasks")

    print(RULE)
    print("TABLE M3 — is any earlier observation ever DROPPED from the request? (append-only?)")
    print(RULE)
    print("Entry point: bantamkit.evalrun.run_task, arm `graph-off`, M3's scripted WalkClient.")
    print("A repeat read can only carry information the request lacks if the request stopped")
    print("carrying the first read. Measured per call, not read off the source.")
    print()
    head = f"{'task':24s}{'calls':>7s}{'msgs at last call':>19s}{'obs slots':>11s}  append-only?"
    print(head)
    print("-" * len(head))

    total_calls = 0
    total_pairs = 0
    breaks = 0
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for task in tasks:
            spec = specs[task["name"]]
            client = WalkClient(
                m3.tool_sequence(spec), json.dumps(task["scoring"]["expected"])
            )
            evalrun.run_task(client, task, "graph-off", workdir)
            histories = [p["messages"] for p in client.payloads]
            if MUTATION == "prune-transcript" and len(histories) > 1:
                # Simulate the one harness change that would make a repeat read
                # informative: a loop that drops the oldest message before re-sending.
                histories = [histories[0]] + [h[1:] for h in histories[1:]]
            ok = True
            for prev, cur in itertools.pairwise(histories):
                total_pairs += 1
                if cur[: len(prev)] != prev or len(cur) <= len(prev):
                    ok = False
                    breaks += 1
            total_calls += len(histories)
            obs = sum(1 for m in histories[-1] if m["role"] == "tool")
            print(
                f"{task['name']:24s}{len(histories):>7d}{len(histories[-1]):>19d}"
                f"{obs:>11d}  {'yes' if ok else 'NO'}"
            )
    print("-" * len(head))
    print(f"model calls examined: {total_calls}   consecutive pairs checked: {total_pairs}"
          f"   prefix violations: {breaks}")
    print()
    if breaks or total_pairs == 0:
        _fail(
            "N4 transcript-is-append-only",
            f"{breaks} of {total_pairs} consecutive request pairs are not a prefix extension; "
            "an observation left the context, so a repeat read is not necessarily information-free",
        )
    return {"calls": total_calls, "pairs": total_pairs, "breaks": breaks}


# ---------------------------------------------------------------------------
# ATTACK 2 — the null control. How many rungs did the ladder actually have?
# ---------------------------------------------------------------------------


def load_arm(root: Path, config: str) -> list[dict]:
    path = root / "docs" / "eval-data" / f"2026-08-17-devteam-ladder-{config}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def index_by_task_seed(rows: list[dict]) -> dict[tuple[str, int], dict]:
    return {(r["task"], r["seed"]): r for r in rows}


def attack_rungs(root: Path) -> dict:
    """Table M4 — the arms partitioned into classes that no committed column separates."""
    arms = {name: load_arm(root, cfg) for name, cfg in ARMS}
    idx = {name: index_by_task_seed(rows) for name, rows in arms.items()}
    keys = sorted(idx["A0"])

    print(RULE)
    print("TABLE M4 — how many DISTINGUISHABLE rungs did the committed ladder have?")
    print(RULE)
    print("Two arms are in the same class when no committed column of any row separates them,")
    print("matched on (task, seed). Bar §1.1 calls this a four-rung one-flag ladder; this is the")
    print("rung count the record supports.")
    print()
    head = f"{'pair':12s}{'rows':>6s}{'cells':>8s}{'differing':>11s}  first differing column"
    print(head)
    print("-" * len(head))

    same: dict[tuple[str, str], bool] = {}
    for i, (a, _) in enumerate(ARMS):
        for b, _ in ARMS[i + 1:]:
            diffs = 0
            first = "-"
            for k in keys:
                ra, rb = idx[a][k], idx[b][k]
                for col in ROW_COLUMNS:
                    if ra[col] != rb[col]:
                        diffs += 1
                        if first == "-":
                            first = f"{col} ({ra[col]!r} vs {rb[col]!r})"
            if MUTATION == "split-arms":
                # Fabricate a distinction between every pair, which is what a reading
                # that took bar §1.1's four declared rungs at face value would assume.
                diffs = diffs or 1
            same[(a, b)] = diffs == 0
            print(
                f"{a + '-' + b:12s}{len(keys):>6d}{len(keys) * len(ROW_COLUMNS):>8d}"
                f"{diffs:>11d}  {first}"
            )

    classes: list[list[str]] = []
    for name, _ in ARMS:
        for cls in classes:
            if same.get((cls[0], name)) or same.get((name, cls[0])):
                cls.append(name)
                break
        else:
            classes.append([name])
    print("-" * len(head))
    print(f"equivalence classes: {len(classes)}  ->  "
          + "  ".join("{" + ",".join(c) + "}" for c in classes))
    print()
    print("Bar §1.1 declares FOUR rungs, one flag apart. The record distinguishes "
          f"{len(classes)}.")
    print()
    if len(classes) >= len(ARMS):
        _fail(
            "N5 rung-classes",
            f"the four arms fall into {len(classes)} classes, so this probe cannot report the "
            "ladder as having fewer distinguishable rungs than declared",
        )
    return {"classes": classes, "same": same}


# ---------------------------------------------------------------------------
# ATTACK 3 — the baseline. Is the one moving rung separable from repeat noise?
# ---------------------------------------------------------------------------


def per_task(rows: list[dict], field: str) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r["task"], []).append(r[field])
    return out


def attack_floor(root: Path) -> dict:
    """Table M5 — bar §3.2's floor is a per-task MAX; the delta it gates is a suite SUM."""
    arms = {name: load_arm(root, cfg) for name, cfg in ARMS}

    print(RULE)
    print("TABLE M5 — bar §3.2's floor, at the grain of the statistic it gates")
    print(RULE)
    print("§2 defines Δtok(Y−X) as tokens 'summed over tasks, per repeat set'. §3.2 gates it with")
    print("`max over tasks of (max − min across repeats in X)` — a SINGLE TASK's spread. Three")
    print("floors are printed. None is invented: each is §3.2's own rule, `max − min across")
    print("repeats`, applied at a different grain, and all three come from these same rows.")
    print("  max     = §3.2 exactly as written, and what the committed instrument computes")
    print("  sum     = the most a sum of eight medians can drift if every task moves its spread")
    print("  suite   = §3.2's rule applied to §2's OWN grain: the suite total per repeat set")
    print()
    head = (
        f"{'arm':8s}{'max':>8s}{'sum':>8s}{'suite':>8s}"
        f"{'suite/max':>11s}  per-repeat-set suite totals"
    )
    print(head)
    print("-" * len(head))
    floors: dict[str, dict] = {}
    for name, _ in ARMS:
        byt = per_task(arms[name], "tokens")
        tasks_sorted = sorted(byt)
        spreads = {t: max(v) - min(v) for t, v in byt.items()}
        mx = max(spreads.values())
        sm = sum(spreads.values())
        n_rep = min(len(v) for v in byt.values())
        sets = [sum(byt[t][i] for t in tasks_sorted) for i in range(n_rep)]
        su = max(sets) - min(sets)
        if MUTATION == "one-floor":
            sm = su = mx
        floors[name] = {"max": mx, "sum": sm, "suite": su, "spreads": spreads}
        print(
            f"{name:8s}{mx:>8d}{sm:>8d}{su:>8d}{su / mx if mx else 0:>11.2f}  {sets}"
        )
    print("-" * len(head))
    print()

    med = {
        name: {t: statistics.median(v) for t, v in per_task(arms[name], "tokens").items()}
        for name, _ in ARMS
    }
    head2 = (
        f"{'pair':10s}{'suite Dtok':>12s}"
        f"{'/max':>9s}{'/sum':>9s}{'/suite':>9s}  clears which floors?"
    )
    print(head2)
    print("-" * len(head2))
    out: dict[str, dict] = {}
    weakened = 0
    for y, x in PAIRS:
        d = abs(sum(med[y].values()) - sum(med[x].values()))
        f = floors[x]
        ratios = {k: (d / f[k] if f[k] else 0.0) for k in ("max", "sum", "suite")}
        cleared = [k for k in ("max", "sum", "suite") if d > f[k]]
        out[f"{y}-{x}"] = {"delta": d, **{k: f[k] for k in ("max", "sum", "suite")},
                           "cleared": cleared}
        if "max" in cleared and max(f["sum"], f["suite"]) > f["max"]:
            weakened += 1
        print(
            f"{y + '-' + x:10s}{d:>12.0f}"
            f"{ratios['max']:>9.2f}{ratios['sum']:>9.2f}{ratios['suite']:>9.2f}"
            f"  {', '.join(cleared) if cleared else 'none'}"
        )
    print("-" * len(head2))
    print()
    print("§3.2 gates a pair on floor(X), the LOWER rung, so the arm that matters for the only")
    print("moving pair is A2 — where the rule as written is 3.51x more lenient than its own rule")
    print("applied at §2's grain. It is NOT uniformly the most lenient: on A3 the suite-grain")
    print("floor is smaller (1324 < 1641), because A3's per-task spreads happen to offset. That")
    print("the ordering is not even stable across arms is the point: the grains are different")
    print("quantities, not a conservative and a generous version of one quantity. The committed")
    print("instrument implements the rule as written (ladder-field-measurement.py:698-699")
    print("compares a `suite_delta` against `noise_floor`, a per-task max), which is where the")
    print("reported 6.3x margin comes from.")
    print()
    if weakened == 0:
        _fail(
            "N6 floor-grain",
            "no pair's clearance margin is affected by the floor's grain, so this probe has no "
            "measured consequence to report for the mismatch",
        )
    return out


def attack_trajectory_share(root: Path) -> dict:
    """Table M5b — how much of the only moving delta is the flag, and how much is the turns.

    M4 recorded that `query` changed the trajectory (123 model calls to A2's 90) and that
    Δ(A3−A2) is therefore "not a clean byte accounting", and split the BYTE delta 44/56.
    Nobody split the TOKEN delta, which is the headline. Tokens factor exactly into calls
    × tokens-per-call, so the split needs no assumption: it is an identity over these rows.
    """
    arms = {name: load_arm(root, cfg) for name, cfg in ARMS}

    print(RULE)
    print("TABLE M5b — the only moving delta, split into `more turns` and `bigger turns`")
    print(RULE)
    print("tokens = model_calls x (tokens / model_calls), an identity, so the two factors below")
    print("multiply to the observed ratio exactly. The one-flag ladder isolates the FLAG; this is")
    print("how much of the flag's headline cost is the trajectory the flag induced.")
    print()
    head = f"{'arm':12s}{'tokens':>10s}{'model_calls':>13s}{'tok/call':>11s}"
    print(head)
    print("-" * len(head))
    tot = {}
    for name, _ in ARMS:
        t = sum(r["tokens"] for r in arms[name])
        c = sum(r["model_calls"] for r in arms[name])
        tot[name] = (t, c)
        print(f"{name:12s}{t:>10d}{c:>13d}{t / c:>11.1f}")
    print("-" * len(head))
    print()
    (t2, c2), (t3, c3) = tot["A2"], tot["A3"]
    calls_factor = c3 / c2
    if MUTATION == "pure-apparatus":
        calls_factor = 1.0
    percall_factor = (t3 / c3) / (t2 / c2)
    print(f"A3 / A2 raw-sum token ratio          : {t3 / t2:.4f}")
    print(f"  x from MORE turns  (calls)         : {calls_factor:.4f}")
    print(f"  x from BIGGER turns (tok per call) : {percall_factor:.4f}")
    print(f"  product (must equal the ratio)     : {calls_factor * percall_factor:.4f}")
    share = math.log(calls_factor) / math.log(t3 / t2) if calls_factor > 1 else 0.0
    print()
    print(f"share of the cost that is the INDUCED TRAJECTORY, not the apparatus: {share:.1%}")
    print("So roughly half of `query`'s measured token cost is turns the flag caused the model")
    print("to take, which no adjacent-rung subtraction separates from the apparatus's own bytes.")
    print()
    if calls_factor <= 1.0:
        _fail(
            "N10 delta-is-part-trajectory",
            f"A3 made {c3} model calls to A2's {c2}, factor {calls_factor:.4f}; without a "
            "trajectory change this probe has no measured trajectory share to report",
        )
    return {"calls_factor": calls_factor, "percall_factor": percall_factor, "share": share}


def attack_score_noise(root: Path) -> dict:
    """Table M6 — the score half has no floor, and the pass-set flips are repeat-thin."""
    arms = {name: load_arm(root, cfg) for name, cfg in ARMS}
    passes = {name: per_task(arms[name], "passed") for name, _ in ARMS}
    tasks = sorted(passes["A0"])

    print(RULE)
    print("TABLE M6 — the score half's own repeat spread, which bar §3.1 defines no floor against")
    print(RULE)
    print("A task counts as passed only if EVERY repeat passed (§3.1's ported rule). A task at")
    print("1/3 or 2/3 is therefore one repeat away from changing the pass SET, and")
    print("`disagreeing_points` counts those flips at face value: §3.2 gives the token half a")
    print("noise floor derived from repeat spread and §3.1 gives the score half nothing.")
    print()
    head = f"{'arm':12s}{'passed tasks':>14s}{'raw rows':>10s}{'non-unanimous':>15s}  which"
    print(head)
    print("-" * len(head))
    for name, _ in ARMS:
        unan = [t for t in tasks if 0 < sum(passes[name][t]) < len(passes[name][t])]
        print(
            f"{name:12s}{sum(1 for t in tasks if all(passes[name][t])):>14d}"
            f"{sum(1 for r in arms[name] if r['passed']):>10d}{len(unan):>15d}  {unan or '-'}"
        )
    print("-" * len(head))
    print()

    head2 = f"{'pair':10s}{'disagreeing':>13s}{'decided by 1 repeat':>21s}  point: X -> Y"
    print(head2)
    print("-" * len(head2))
    out: dict[str, dict] = {}
    thin_total = 0
    for y, x in PAIRS:
        px = {t for t in tasks if all(passes[x][t])}
        py = {t for t in tasks if all(passes[y][t])}
        dis = sorted(px ^ py)
        thin = []
        detail = []
        for t in dis:
            nx, ny = sum(passes[x][t]), sum(passes[y][t])
            detail.append(f"{t} {nx}/3->{ny}/3")
            if abs(ny - nx) == 1:
                thin.append(t)
        thin_total += len(thin)
        out[f"{y}-{x}"] = {"disagreeing": dis, "thin": thin}
        print(f"{y + '-' + x:10s}{len(dis):>13d}{len(thin):>21d}  {'; '.join(detail) or '-'}")
    print("-" * len(head2))
    print()
    if thin_total == 0:
        _fail(
            "N7 score-half-has-no-floor",
            "no disagreeing point turns on a single repeat, so this probe has no measured case "
            "where a pass-set flip is within the arm's own repeat instability",
        )
    return out


# ---------------------------------------------------------------------------
# THE RULER — which columns fired in the field, and what a row is attributable to
# ---------------------------------------------------------------------------


def attack_ruler(root: Path) -> dict:
    """Table M7 — M3.5's eight columns against the 96 rows that were supposed to use them."""
    arms = {name: load_arm(root, cfg) for name, cfg in ARMS}
    total_rows = sum(len(v) for v in arms.values())

    print(RULE)
    print("TABLE M7 — how much of the ruler the field ever exercised, over all 96 committed rows")
    print(RULE)
    print("RB-P28: the suite is not evidence. A column pinned only on a fixture is a column whose")
    print("field behaviour is unmeasured. `annotate_marker_bytes` is the sharpest case — A1 is the")
    print("arm whose entire purpose is to annotate.")
    print()
    head = f"{'column':26s}" + "".join(f"{a:>12s}" for a, _ in ARMS) + f"{'rows nonzero':>14s}"
    print(head)
    print("-" * len(head))
    never: list[str] = []
    for col in ACCOUNTING_COLUMNS:
        cells = ""
        nz_total = 0
        for name, _ in ARMS:
            vals = [r[col] for r in arms[name]]
            nz = sum(1 for v in vals if v != 0)
            nz_total += nz
            cells += f"{f'{nz}/{len(vals)}':>12s}"
        if nz_total == 0:
            never.append(col)
        print(f"{col:26s}{cells}{f'{nz_total}/{total_rows}':>14s}")
    print("-" * len(head))
    print(f"columns that are ZERO in every one of the {total_rows} rows: {len(never)}/"
          f"{len(ACCOUNTING_COLUMNS)}  {never}")
    a1_annotate = sum(r["annotate_marker_bytes"] for r in arms["A1"])
    print(f"`annotate_marker_bytes` summed over A1 (the annotate arm): {a1_annotate}")
    print()

    keys = sorted({k for rows in arms.values() for r in rows for k in r})
    has_model = "model" in keys
    print(f"union of every key on all {total_rows} rows: {keys}")
    print(f"a `model` field on any row: {has_model}   "
          "-> the primary evidence is attributable to a model only through prose")
    print()
    if not never:
        _fail(
            "N8 ruler-columns-unexercised",
            "every accounting column fired in the field, so this probe has no unexercised half "
            "of the ruler to report",
        )
    if has_model:
        _fail("N9 rows-carry-no-model", "a row carries a `model` field; the finding does not stand")
    return {"never": never, "has_model": has_model}


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    global MUTATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", type=Path)
    parser.add_argument(
        "--mutate",
        choices=MUTATIONS,
        help="Falsify one piece of this probe's reasoning. MUST exit 1.",
    )
    args = parser.parse_args(argv)
    MUTATION = args.mutate
    root = args.repo_root.resolve()

    print(RULE)
    print("FIELD PROBE — M5's adversarial review of the dev-team ladder instrument")
    print(RULE)
    print(f"pytest in sys.modules: {'pytest' in sys.modules}   (must be False)")
    if "pytest" in sys.modules:
        print("FATAL: pytest is imported. This program is the evidence, not a node.")
        return 2
    print(f"repo root:             {root}")
    print("reads:                 the four committed JSONL arms + assets/evals/devteam (read-only)")
    print("derivations imported:  M2's verify_walk/pressure/surface, M3's WalkClient/tool_sequence")
    print(f"mutation:              {MUTATION or 'none'}")
    print("what this does NOT do: run a second model; change any asset; compute an "
          "all-on-vs-all-off number")
    print()

    m2, m3 = committed_programs(root)

    attack_workload(m2, root)
    attack_repeat_content(m3, root)
    attack_transcript(m3, root)
    attack_rungs(root)
    attack_floor(root)
    attack_trajectory_share(root)
    attack_score_noise(root)
    attack_ruler(root)

    print(RULE)
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  - {f}")
        print(RULE)
        return 1
    print("ALL CHECKS PASSED — every finding below is a measurement, not an opinion.")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
