#!/usr/bin/env python
"""Field measurement of the `graph-off` null control, OUTSIDE pytest.

    .venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py .
    .venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py . --mutate cache
    .venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py . --mutate query
    .venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py . --mutate annotate

M3 of job `devteam-workload-and-null-control`, dated 2026-08-17.

WHY THIS IS A FIELD MEASUREMENT AND NOT A TEST. RB-P28 is OPEN: job 11's C1 showed
a patch keyed on `pytest in sys.modules` printing an affirmatively false report
under a green suite. So this file is a standalone program in a fresh interpreter.
It imports nothing from `runtime-py/tests`, defines no fixture, has no pytest
node, and asserts `pytest not in sys.modules` before it measures — printed as
line 1 of the report. The entry point under measurement is
`bantamkit.evalrun.run_task`, the same function `evalrun.main` calls per (task,
config, repeat), reached through the same `load_tasks` loader the `--tasks` flag
uses. Exit status is 0 only when every check below holds.

WHAT IT CAN AND CANNOT MAKE REAL. The model client is a deterministic scripted
walker (`WalkClient`), the same device M1 and M2 used, replaying the manifest's
verified reference walk. It makes real: the observation bytes, the tool roster,
the system prompt, the serialized request payload, the score, and the ledger.
It CANNOT make real: an endpoint's `Usage`. Token figures here are a payload-
derived surrogate — `ceil(bytes/4)` over the exact request the repo's own
serializer would POST (`client.py:155-161`) — so they are a deterministic
function OF THE OBSERVATIONS, which is the property `conftest.FakeClient`'s fixed
`Usage` lacks (bar §9/A1). Assumption inherited from the workload doc's Table 5b:
tokens monotone in bytes. It is stated, not hidden.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import tempfile
from pathlib import Path

RULE = "=" * 78
ARMS = ("bare", "graph-off")


def _import_bantamkit(root: Path):
    sys.path.insert(0, str(root / "runtime-py" / "src"))
    from bantamkit import evalrun
    from bantamkit.client import Message, Response, ToolCall, Usage

    return evalrun, Message, Response, ToolCall, Usage


def manifest(root: Path) -> dict:
    import yaml

    return yaml.safe_load((root / "assets" / "evals" / "devteam" / "manifest.yaml").read_text(
        encoding="utf-8"
    ))


def tool_sequence(task: dict) -> list[tuple[str, str | None]]:
    """The reference walk as tool calls.

    Byte-for-byte the rule of `2026-08-17-devteam-workload-measurements.py:154-164`,
    so this run walks the SAME trajectory Table 3 verified and Table 5 priced: one
    `list_files` first iff the prompt names it or a hop reads its pointer out of the
    listing, then one `read_file` per hop in order.
    """
    needs_list = "list_files" in task["prompt"] or any(
        hop.get("pointer_in") == "listing" for hop in task["walk"]
    )
    seq: list[tuple[str, str | None]] = [("list_files", None)] if needs_list else []
    return seq + [("read_file", hop["path"]) for hop in task["walk"]]


def make_walk_client(Message, Response, ToolCall, Usage):
    class WalkClient:
        """Deterministic scripted ModelClient that walks a declared reference path.

        Two differences from `conftest.FakeClient`, both load-bearing here:

        1. `usage` is computed from the serialized request payload, so it MOVES when
           the observations move. `FakeClient` returns a fixed `Usage`, which is why
           the token half of the null-control claim was unpinned (bar §9/A1).
        2. It records the exact payload dict, not just the messages, so the tool
           roster and the system prompt are in the compared bytes too.
        """

        model = "walk-client/deterministic"

        def __init__(self, calls: list[tuple[str, str | None]], answer: str):
            self.script = list(calls)
            self.answer = answer
            self.seed: int | None = None  # duck-typed by run_task; identical across arms
            self.payloads: list[dict] = []
            self.usage_per_call: list[tuple[int, int]] = []

        def chat(self, messages, tools=None, response_format=None):
            payload: dict = {
                "model": self.model,
                "messages": [m.to_wire() for m in messages],
            }
            if tools:
                payload["tools"] = [t.to_wire() for t in tools]
            if self.seed is not None:
                payload["seed"] = self.seed
            if response_format is not None:
                payload["response_format"] = response_format
            self.payloads.append(copy.deepcopy(payload))

            if self.script:
                name, path = self.script.pop(0)
                args = {"path": path} if path is not None else {}
                reply = Message(
                    role="assistant",
                    tool_calls=[ToolCall(id=f"c{len(self.payloads)}", name=name, arguments=args)],
                )
                completion = json.dumps({"name": name, "arguments": args})
            else:
                reply = Message(role="assistant", content=self.answer)
                completion = self.answer
            prompt_tokens = math.ceil(len(json.dumps(payload).encode()) / 4)
            completion_tokens = math.ceil(len(completion.encode()) / 4)
            self.usage_per_call.append((prompt_tokens, completion_tokens))
            return Response(message=reply, usage=Usage(prompt_tokens, completion_tokens))

        # ---- the quantities the comparison reads ----

        def observations(self) -> list[list[str]]:
            return [
                [m["content"] for m in p["messages"] if m["role"] == "tool"] for p in self.payloads
            ]

        def rosters(self) -> list[list[str]]:
            return [
                [t["function"]["name"] for t in p.get("tools", [])] for p in self.payloads
            ]

        def systems(self) -> list[str | None]:
            return [
                next((m["content"] for m in p["messages"] if m["role"] == "system"), None)
                for p in self.payloads
            ]

        def payload_bytes(self) -> list[bytes]:
            return [json.dumps(p, sort_keys=False).encode() for p in self.payloads]

    return WalkClient


def _run_arm(evalrun, WalkClient, task: dict, spec: dict, arm: str, workdir: Path):
    client = WalkClient(tool_sequence(spec), json.dumps(task["scoring"]["expected"]))
    result = evalrun.run_task(client, task, arm, workdir)
    return client, result


def _ledger_capture(evalrun):
    """Capture the FileAccessGraph instance run_task builds and DISCARDS.

    Observation only: the subclass adds no behaviour, no counter and no TaskResult
    column — `__init__` appends `self` to a list and returns. It exists because
    `run_task` never returns the graph and never calls `save()` (bar §7.2), so a
    script cannot read the ledger without wrapping the constructor. That is a
    finding for M3.5, not a column: nothing here is written to a JSONL row.
    """
    seen: list = []
    original = evalrun.FileAccessGraph

    class Capturing(original):  # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen.append(self)

    return seen, original, Capturing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".", type=Path)
    ap.add_argument(
        "--mutate",
        choices=("cache", "annotate", "query"),
        help="Falsifying mutation: flip this flag True in GRAPH_CONFIGS['graph-off'] "
        "before measuring. The run MUST fail (exit 1) for the checks to be pins.",
    )
    args = ap.parse_args()
    root = args.root.resolve()

    if "pytest" in sys.modules:
        print("FATAL: pytest is imported. This program is the field measurement, not a node.")
        return 2

    evalrun, Message, Response, ToolCall, Usage = _import_bantamkit(root)
    WalkClient = make_walk_client(Message, Response, ToolCall, Usage)
    man = manifest(root)
    specs = {t["name"]: t for t in man["tasks"]}
    tasks = evalrun.load_tasks(root / "assets" / "evals" / "devteam" / "tasks")

    print(RULE)
    print("FIELD MEASUREMENT — the `graph-off` null control vs `bare`, outside pytest")
    print(RULE)
    print(f"pytest in sys.modules: {'pytest' in sys.modules}   (must be False)")
    print(f"entry point:           bantamkit.evalrun.run_task  ({evalrun.__file__})")
    print(f"tasks loaded via:      evalrun.load_tasks(assets/evals/devteam/tasks)  n={len(tasks)}")
    print(f"client:                {WalkClient.model} (scripted; usage = ceil(payload bytes/4))")
    print(f"arms:                  {' vs '.join(ARMS)}")
    if args.mutate:
        evalrun.GRAPH_CONFIGS["graph-off"] = dict(
            evalrun.GRAPH_CONFIGS["graph-off"], **{args.mutate: True}
        )
        print(f"MUTATION APPLIED:      graph-off {args.mutate}=True -> "
              f"{evalrun.GRAPH_CONFIGS['graph-off']}")
    else:
        print(f"graph-off flags:       {evalrun.GRAPH_CONFIGS['graph-off']}")
    print(f"graph-off is calibration-only: in CONFIG_CHOICES="
          f"{'graph-off' in evalrun.CONFIG_CHOICES}, in CONFIGS="
          f"{'graph-off' in evalrun.CONFIGS}")
    print()

    failures: list[str] = []
    rows: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for task in tasks:
            spec = specs[task["name"]]
            clients, results = {}, {}
            for arm in ARMS:
                clients[arm], results[arm] = _run_arm(
                    evalrun, WalkClient, task, spec, arm, workdir
                )
            b, o = clients["bare"], clients["graph-off"]
            rb, ro = results["bare"], results["graph-off"]

            # --- pass 2: the same graph-off run, with the discarded ledger captured ---
            seen, original, Capturing = _ledger_capture(evalrun)
            evalrun.FileAccessGraph = Capturing
            try:
                cap_client, cap_result = _run_arm(
                    evalrun, WalkClient, task, spec, "graph-off", workdir
                )
            finally:
                evalrun.FileAccessGraph = original
            ledger = seen[-1].reads if seen else {}
            reads = sum(r.count for r in ledger.values())
            repeats = sum(r.count - 1 for r in ledger.values())

            obs_calls = len(b.observations())
            obs_bytes = sum(len(x.encode()) for turn in b.observations() for x in turn)
            row = {
                "task": task["name"],
                "calls": obs_calls,
                "obs": sum(len(turn) for turn in b.observations()),
                "obs_bytes": obs_bytes,
                "identical_obs": b.observations() == o.observations(),
                "identical_payload": b.payload_bytes() == o.payload_bytes(),
                "identical_roster": b.rosters() == o.rosters(),
                "identical_system": b.systems() == o.systems(),
                "no_marker": not any(
                    "[file-graph]" in x for turn in o.observations() for x in turn
                ),
                "passed": (rb.passed, ro.passed),
                "tokens": (rb.tokens, ro.tokens),
                "ledger_reads": reads,
                "ledger_distinct": len(ledger),
                "ledger_repeats": repeats,
                "ledger_populated": bool(ledger),
                "pass2_identical": (
                    cap_client.payload_bytes() == b.payload_bytes()
                    and (cap_result.passed, cap_result.tokens) == (ro.passed, ro.tokens)
                ),
            }
            rows.append(row)

            name = task["name"]
            if not row["identical_obs"]:
                failures.append(f"{name}: O1 tool observations differ bare vs graph-off")
            if not row["identical_payload"]:
                failures.append(f"{name}: O6 request payload bytes differ bare vs graph-off")
            if not row["identical_roster"]:
                failures.append(f"{name}: O2 tool roster differs bare vs graph-off")
            if not row["identical_system"]:
                failures.append(f"{name}: O3 system prompt differs bare vs graph-off")
            if not row["no_marker"]:
                failures.append(f"{name}: O4 a [file-graph] marker reached the model")
            if rb.passed is not ro.passed:
                failures.append(f"{name}: O5 score differs at a fixed trajectory")
            if rb.tokens != ro.tokens:
                failures.append(
                    f"{name}: O7 tokens differ — bare={rb.tokens} graph-off={ro.tokens}"
                )
            if not row["ledger_populated"]:
                failures.append(f"{name}: L1 the ledger is EMPTY under graph-off")
            if not row["pass2_identical"]:
                failures.append(f"{name}: L2 the capture pass diverged from the measured run")

    print(RULE)
    print("TABLE A — byte identity, all 8 workload tasks (bare vs graph-off)")
    print(RULE)
    hdr = (
        f"{'task':<24}{'calls':>6}{'obs':>5}{'obs B':>7}{'obs=':>6}"
        f"{'payload=':>10}{'roster=':>9}{'system=':>9}{'marker?':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['task']:<24}{r['calls']:>6}{r['obs']:>5}{r['obs_bytes']:>7}"
            f"{('yes' if r['identical_obs'] else 'NO'):>6}"
            f"{('yes' if r['identical_payload'] else 'NO'):>10}"
            f"{('yes' if r['identical_roster'] else 'NO'):>9}"
            f"{('yes' if r['identical_system'] else 'NO'):>9}"
            f"{('none' if r['no_marker'] else 'PRESENT'):>9}"
        )
    print("-" * len(hdr))

    def tally(key: str) -> str:
        return f"{sum(bool(r[key]) for r in rows)}/{len(rows)}"

    print(
        f"{'TOTAL':<24}{sum(r['calls'] for r in rows):>6}"
        f"{sum(r['obs'] for r in rows):>5}{sum(r['obs_bytes'] for r in rows):>7}"
        f"{tally('identical_obs'):>6}{tally('identical_payload'):>10}"
        f"{tally('identical_roster'):>9}{tally('identical_system'):>9}"
        f"{tally('no_marker'):>9}"
    )
    print()

    print(RULE)
    print("TABLE B — score and tokens at a fixed trajectory, and the ledger that is kept")
    print(RULE)
    hdr = (
        f"{'task':<24}{'passed b/o':>11}{'tok bare':>10}{'tok off':>9}{'Δtok':>6}"
        f"{'reads':>7}{'distinct':>9}{'repeats':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        tb, to = r["tokens"]
        pb, po = r["passed"]
        print(
            f"{r['task']:<24}{f'{int(pb)}/{int(po)}':>11}{tb:>10}{to:>9}{to - tb:>6}"
            f"{r['ledger_reads']:>7}{r['ledger_distinct']:>9}{r['ledger_repeats']:>8}"
        )
    print("-" * len(hdr))
    tb = sum(r["tokens"][0] for r in rows)
    to = sum(r["tokens"][1] for r in rows)
    pass_b = sum(r["passed"][0] for r in rows)
    pass_o = sum(r["passed"][1] for r in rows)
    print(
        f"{'WORKLOAD':<24}{f'{pass_b}/{pass_o}':>11}"
        f"{tb:>10}{to:>9}{to - tb:>6}"
        f"{sum(r['ledger_reads'] for r in rows):>7}"
        f"{sum(r['ledger_distinct'] for r in rows):>9}"
        f"{sum(r['ledger_repeats'] for r in rows):>8}"
    )
    print()
    print("`reads`/`distinct`/`repeats` are the REALISED counts, read off the")
    print("FileAccessGraph this script captured. The harness at HEAD still discards it:")
    print("the numbers above are reachable only because this script wrapped the")
    print("constructor. That is M3.5's finding, not a column — no JSONL row carries them.")
    print()

    print(RULE)
    print("VERDICT")
    print(RULE)
    if failures:
        print(f"FAILED — {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        if args.mutate:
            print()
            print(f"EXPECTED: the mutation graph-off {args.mutate}=True is supposed to")
            print("falsify these checks. A red run here is the pin, not a defect.")
        return 1
    print(f"PASSED — all {len(rows)} tasks: observations, request payload, tool roster,")
    print("system prompt, score and payload-derived tokens are byte-identical between")
    print("`bare` and `graph-off`, and the ledger is populated on every one of them.")
    if args.mutate:
        print()
        print(f"UNEXPECTED: the mutation graph-off {args.mutate}=True changed NOTHING.")
        print("Under the v0.21.0 pinning bar that means these checks do not pin the claim.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
