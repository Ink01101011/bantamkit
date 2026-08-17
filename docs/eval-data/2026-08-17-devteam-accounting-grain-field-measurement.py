#!/usr/bin/env python
"""Field measurement of bar §8's accounting grain, OUTSIDE pytest.

    .venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py .
    .venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py . \
        --mutate discard

M3.5 of job `devteam-workload-and-null-control`, dated 2026-08-17.

WHY THIS IS A FIELD MEASUREMENT AND NOT A TEST. RB-P28 is OPEN: job 11's C1 showed a
patch keyed on `pytest in sys.modules` printing an affirmatively false report under a
green suite. So this is a standalone program in a fresh interpreter. It imports nothing
from `runtime-py/tests`, defines no fixture, declares no node, and asserts
`pytest not in sys.modules` before it measures — printed as line 1 of its report.

TWO ENTRY POINTS, ON PURPOSE.

  PASS 1 — `bantamkit.evalrun.run_task` in this process, with the `FileAccessGraph`
  captured by an observation-only subclass. The capture is NOT the delivery route any
  more; it is the REFERENCE the columns are checked against. Bar §7.2 recorded that this
  wrapping was the only way to see the ledger at all.

  PASS 2 — the real CLI, `python -m bantamkit.evalrun --config graph-off
  --tasks assets/evals/devteam/tasks --json <file>`, in a SUBPROCESS, against a local
  OpenAI-compatible endpoint this program serves. Bar §7.2 said the `--tasks`/`--json`
  path "cannot reach it at all, so no committed JSONL can carry the number". Pass 2 is
  that claim being retested end to end: the JSONL rows are read back off disk and
  compared, task by task, with pass 1.

ONE ARM ONLY: `graph-off`. It is the null control, it costs nothing, and it is the arm
whose whole purpose is to report the OPPORTUNITY (columns 1-2) without acting on it
(columns 3-6 are 0 by construction with all three flags off). NO LADDER DELTA, NO ARM
CONTRAST AND NO TOKEN SAVING IS COMPUTED OR PRINTED ANYWHERE IN THIS FILE — Δ%(A1−A0),
Δ%(A2−A1), Δ%(A3−A2) and every `graph`-vs-anything figure are M4's.

WHAT IT CAN AND CANNOT MAKE REAL. The trajectory is a deterministic scripted walk of the
manifest's verified reference walk — real observation bytes, real tool roster, real
score, real ledger, real serialized request, and in pass 2 a real HTTP round trip
through `OpenAICompatible`. It cannot make real a MODEL's trajectory, and its token
figures are the endpoint's own `ceil(bytes/4)` surrogate, never a tokenizer. Both limits
are inherited from M3 and are restated rather than quietly dropped.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RULE = "=" * 78
ARM = "graph-off"
ACCOUNTING_COLUMNS = (
    "reader_calls",
    "unrecorded_reader_calls",
    "repeat_reader_calls",
    "collapsed_calls",
    "collapsed_bytes",
    "annotate_marker_bytes",
    "query_bytes",
    "context_bytes_sent",
)


def _import_bantamkit(root: Path):
    sys.path.insert(0, str(root / "runtime-py" / "src"))
    from bantamkit import evalrun
    from bantamkit.client import Message, Response, ToolCall, Usage

    return evalrun, Message, Response, ToolCall, Usage


def manifest(root: Path) -> dict:
    import yaml

    return yaml.safe_load((root / "assets" / "evals" / "devteam" / "manifest.yaml").read_text())


def tool_sequence(spec: dict, prompt: str) -> list[tuple[str, str | None]]:
    """The reference walk as tool calls.

    Byte-for-byte the rule `2026-08-17-devteam-workload-measurements.py:154-164` states
    and M3's field program reused, so this walks the SAME trajectory Table 3 verified:
    one `list_files` first iff the prompt names it or a hop reads its pointer out of the
    listing, then one `read_file` per hop in order.
    """
    needs_list = "list_files" in prompt or any(
        hop.get("pointer_in") == "listing" for hop in spec["walk"]
    )
    seq: list[tuple[str, str | None]] = [("list_files", None)] if needs_list else []
    return seq + [("read_file", hop["path"]) for hop in spec["walk"]]


# --------------------------------------------------------------------------------------
# pass 1 — run_task in this process, with the ledger captured as the reference
# --------------------------------------------------------------------------------------


def make_walk_client(Message, Response, ToolCall, Usage):
    class WalkClient:
        """Deterministic scripted ModelClient that walks a declared reference path.

        Records the `messages`/`tools` objects it was handed, so column 7 can be checked
        against `evalrun.request_wire_bytes` recomputed over the very same arguments
        rather than against a second spelling of the serializer.
        """

        model = "walk-client/deterministic"

        def __init__(self, calls: list[tuple[str, str | None]], answer: str):
            self.script = list(calls)
            self.answer = answer
            self.seed: int | None = None  # duck-typed by run_task
            self.requests: list[tuple[list, list | None]] = []

        def chat(self, messages, tools=None, response_format=None):
            self.requests.append((list(messages), list(tools) if tools else None))
            if self.script:
                name, path = self.script.pop(0)
                args = {"path": path} if path is not None else {}
                reply = Message(
                    role="assistant",
                    tool_calls=[ToolCall(id=f"c{len(self.requests)}", name=name, arguments=args)],
                )
                completion = json.dumps(args)
            else:
                reply = Message(role="assistant", content=self.answer)
                completion = self.answer
            prompt_tokens = math.ceil(
                len(json.dumps([m.to_wire() for m in messages]).encode()) / 4
            )
            return Response(
                message=reply,
                usage=Usage(prompt_tokens, math.ceil(len(completion.encode()) / 4)),
            )

    return WalkClient


def capture_graphs(evalrun, discard: bool):
    """Observation-only capture of the graph a run builds — plus the falsifying mutation.

    `discard=True` reinstates exactly the defect this unit closed: the ledger keeps
    counting and the COLUMN stops carrying it. Applied in this process so the mutation is
    reproducible without editing a file; the pytest-node mutation was done the other way,
    by editing the source, because a node has to run against mutated source to be a pin.
    """
    seen: list = []
    original = evalrun.FileAccessGraph

    class Capturing(original):  # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen.append(self)

        def _record(self, tool, path, observation):
            out = super()._record(tool, path, observation)
            if discard:
                self.accounting.repeat_reader_calls = 0
            return out

    return seen, original, Capturing


def pass1(evalrun, WalkClient, tasks, specs, workdir: Path, discard: bool) -> list[dict]:
    rows = []
    for task in tasks:
        spec = specs[task["name"]]
        client = WalkClient(
            tool_sequence(spec, task["prompt"]), json.dumps(task["scoring"]["expected"])
        )
        seen, original, Capturing = capture_graphs(evalrun, discard)
        evalrun.FileAccessGraph = Capturing
        try:
            result = evalrun.run_task(client, task, ARM, workdir / task["name"])
        finally:
            evalrun.FileAccessGraph = original
        ledger = seen[-1].reads if seen else {}
        recomputed = sum(evalrun.request_wire_bytes(m, t) for m, t in client.requests)
        rows.append(
            {
                "task": task["name"],
                "passed": result.passed,
                "model_calls": result.model_calls,
                "ledger_reads": sum(r.count for r in ledger.values()),
                "ledger_distinct": len(ledger),
                "ledger_repeats": sum(r.count - 1 for r in ledger.values()),
                "recomputed_context_bytes": recomputed,
                **{name: getattr(result, name) for name in ACCOUNTING_COLUMNS},
            }
        )
    return rows


# --------------------------------------------------------------------------------------
# pass 2 — the real CLI, over HTTP, into a JSONL file
# --------------------------------------------------------------------------------------


def make_endpoint(scripts: dict[str, list[tuple[str, str | None]]], answers: dict[str, str]):
    """A minimal OpenAI-compatible chat-completions endpoint that replays the walk.

    Keyed on the user prompt, which is unique per task, and stepped by how many `tool`
    messages the request already carries — so it is stateless and the harness's own
    transcript drives it. `usage` is the same `ceil(bytes/4)` surrogate M3 used, computed
    here on the SERVER side over the received body, which is what makes pass 2 a real
    round trip through `OpenAICompatible._parse` rather than a fake in disguise.
    """

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # BaseHTTPRequestHandler's own naming convention
            body = self.rfile.read(int(self.headers["Content-Length"]))
            request = json.loads(body)
            prompt = next(m["content"] for m in request["messages"] if m["role"] == "user")
            script = scripts[prompt]
            done = sum(1 for m in request["messages"] if m["role"] == "tool")
            if done < len(script):
                name, path = script[done]
                args = {"path": path} if path is not None else {}
                completion = json.dumps(args)
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"c{done}",
                            "type": "function",
                            "function": {"name": name, "arguments": completion},
                        }
                    ],
                }
            else:
                completion = answers[prompt]
                message = {"role": "assistant", "content": completion}
            out = json.dumps(
                {
                    "choices": [{"message": message}],
                    "usage": {
                        "prompt_tokens": math.ceil(len(body) / 4),
                        "completion_tokens": math.ceil(len(completion.encode()) / 4),
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass  # the report is the output; an access log would bury it

    return Handler


def pass2(root: Path, tasks, specs, jsonl: Path) -> tuple[list[dict], str, int]:
    scripts = {t["prompt"]: tool_sequence(specs[t["name"]], t["prompt"]) for t in tasks}
    answers = {t["prompt"]: json.dumps(t["scoring"]["expected"]) for t in tasks}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_endpoint(scripts, answers))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    command = [
        sys.executable,
        "-m",
        "bantamkit.evalrun",
        "--base-url",
        base_url,
        "--model",
        "walk-endpoint",
        "--config",
        ARM,
        "--tasks",
        "assets/evals/devteam/tasks",
        "--json",
        str(jsonl),
    ]
    try:
        proc = subprocess.run(
            command, cwd=root, capture_output=True, text=True, timeout=300, check=False
        )
    finally:
        server.shutdown()
        server.server_close()
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    printable = " ".join(command).replace(str(jsonl), "<jsonl>").replace(sys.executable, "python")
    return rows, printable, proc.returncode


# --------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".", type=Path)
    ap.add_argument(
        "--mutate",
        choices=("discard",),
        help="Falsifying mutation: keep counting in the ledger but stop carrying the "
        "count in the column — the defect this unit closed. The run MUST fail (exit 1) "
        "for the checks below to be pins.",
    )
    args = ap.parse_args()
    root = args.root.resolve()
    discard = args.mutate == "discard"

    if "pytest" in sys.modules:
        print("FATAL: pytest is imported. This program is the field measurement, not a node.")
        return 2

    evalrun, Message, Response, ToolCall, Usage = _import_bantamkit(root)
    WalkClient = make_walk_client(Message, Response, ToolCall, Usage)
    specs = {t["name"]: t for t in manifest(root)["tasks"]}
    tasks = evalrun.load_tasks(root / "assets" / "evals" / "devteam" / "tasks")

    print(RULE)
    print("FIELD MEASUREMENT — bar §8's accounting grain, outside pytest")
    print(RULE)
    print(f"pytest in sys.modules: {'pytest' in sys.modules}   (must be False)")
    print(f"pass 1 entry point:    bantamkit.evalrun.run_task  ({evalrun.__file__})")
    print("pass 2 entry point:    python -m bantamkit.evalrun  (subprocess, over HTTP)")
    print(f"tasks loaded via:      evalrun.load_tasks(assets/evals/devteam/tasks)  n={len(tasks)}")
    print(f"arm:                   {ARM} only — no ladder delta is computed here")
    print(f"arm flags:             {evalrun.GRAPH_CONFIGS[ARM]}")
    if discard:
        print("MUTATION APPLIED:      the column stops carrying repeat_reader_calls")
    print()

    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        rows = pass1(evalrun, WalkClient, tasks, specs, Path(tmp), discard)
        jsonl = Path(tmp) / "graph-off.jsonl"
        cli_rows, cli_command, cli_rc = pass2(root, tasks, specs, jsonl)
        raw_row = json.dumps(
            next((r for r in cli_rows if r["repeat_reader_calls"] > 0), cli_rows[0] if cli_rows else {}),
            indent=2,
        )

    print(RULE)
    print("TABLE C — pass 1: the columns a run now records, against the ledger it built")
    print(RULE)
    hdr = (
        f"{'task':<24}{'read':>5}{'unrec':>6}{'rept':>5}{'coll':>5}{'collB':>6}"
        f"{'annB':>5}{'qryB':>5}{'ctxB':>8}{'ledger r/d/rep':>17}{'ok':>5}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        reconciles = (
            r["reader_calls"] - r["unrecorded_reader_calls"] == r["ledger_reads"]
            and r["repeat_reader_calls"] == r["ledger_repeats"]
            and r["context_bytes_sent"] == r["recomputed_context_bytes"]
        )
        print(
            f"{r['task']:<24}{r['reader_calls']:>5}{r['unrecorded_reader_calls']:>6}"
            f"{r['repeat_reader_calls']:>5}{r['collapsed_calls']:>5}{r['collapsed_bytes']:>6}"
            f"{r['annotate_marker_bytes']:>5}{r['query_bytes']:>5}{r['context_bytes_sent']:>8}"
            f"{f'{r["ledger_reads"]}/{r["ledger_distinct"]}/{r["ledger_repeats"]}':>17}"
            f"{('yes' if reconciles else 'NO'):>5}"
        )
        if r["reader_calls"] - r["unrecorded_reader_calls"] != r["ledger_reads"]:
            failures.append(f"{r['task']}: A1 recorded reader calls != sum(FileRead.count)")
        if r["repeat_reader_calls"] != r["ledger_repeats"]:
            failures.append(
                f"{r['task']}: A2 repeat_reader_calls={r['repeat_reader_calls']} but the "
                f"ledger holds {r['ledger_repeats']}"
            )
        if r["context_bytes_sent"] != r["recomputed_context_bytes"]:
            failures.append(f"{r['task']}: A3 context_bytes_sent != the serialized requests")
        if not r["passed"]:
            failures.append(f"{r['task']}: A4 the reference walk did not score")
    print("-" * len(hdr))
    print(
        f"{'WORKLOAD':<24}{sum(r['reader_calls'] for r in rows):>5}"
        f"{sum(r['unrecorded_reader_calls'] for r in rows):>6}"
        f"{sum(r['repeat_reader_calls'] for r in rows):>5}"
        f"{sum(r['collapsed_calls'] for r in rows):>5}"
        f"{sum(r['collapsed_bytes'] for r in rows):>6}"
        f"{sum(r['annotate_marker_bytes'] for r in rows):>5}"
        f"{sum(r['query_bytes'] for r in rows):>5}"
        f"{sum(r['context_bytes_sent'] for r in rows):>8}"
        f"{f'{sum(r["ledger_reads"] for r in rows)}/'
           f'{sum(r["ledger_distinct"] for r in rows)}/'
           f'{sum(r["ledger_repeats"] for r in rows)}':>17}"
    )
    print()
    print("read=reader_calls  unrec=unrecorded_reader_calls  rept=repeat_reader_calls")
    print("coll=collapsed_calls  collB/annB/qryB/ctxB = the four byte columns.")
    print(f"Columns 3-6 read 0 across the board BY CONSTRUCTION: {ARM} has all three")
    print("flags off, so nothing collapses, nothing is annotated and no tool is registered.")
    print("That is the null control reporting OPPORTUNITY without acting on it.")
    print()

    # Vacuity guard, not a pinned quantity: if nothing in the workload ever repeated a
    # read, the demonstration would be empty and pass/pass would mean nothing. The
    # per-task numbers themselves are reported, never asserted (RB-P14 Gate 2).
    if sum(r["ledger_repeats"] for r in rows) == 0 and not discard:
        failures.append("V1 no task realised any repeat read — the demonstration is vacuous")

    print(RULE)
    print("TABLE D — pass 2: the SAME number off the CLI's own JSONL, per task")
    print(RULE)
    print(f"  $ {cli_command}")
    print(f"  exit status: {cli_rc}    rows written: {len(cli_rows)}")
    print()
    hdr = (
        f"{'task':<24}{'config':>10}{'read':>6}{'unrec':>6}{'rept':>5}"
        f"{'ctxB':>8}{'pass1 rept':>11}{'ok':>5}"
    )
    print(hdr)
    print("-" * len(hdr))
    by_task = {r["task"]: r for r in rows}
    for row in cli_rows:
        p1 = by_task.get(row["task"], {})
        agree = row["repeat_reader_calls"] == p1.get("repeat_reader_calls")
        print(
            f"{row['task']:<24}{row['config']:>10}{row['reader_calls']:>6}"
            f"{row['unrecorded_reader_calls']:>6}{row['repeat_reader_calls']:>5}"
            f"{row['context_bytes_sent']:>8}{p1.get('repeat_reader_calls', '?'):>11}"
            f"{('yes' if agree else 'NO'):>5}"
        )
        missing = [c for c in ACCOUNTING_COLUMNS if c not in row]
        if missing:
            failures.append(f"{row['task']}: B1 JSONL row lacks {', '.join(missing)}")
        if not agree:
            failures.append(
                f"{row['task']}: B2 the CLI row says repeat_reader_calls="
                f"{row['repeat_reader_calls']}, pass 1 says {p1.get('repeat_reader_calls')}"
            )
    print("-" * len(hdr))
    if cli_rc != 0:
        failures.append(f"B3 the CLI exited {cli_rc}")
    if len(cli_rows) != len(tasks):
        failures.append(f"B4 the CLI wrote {len(cli_rows)} rows for {len(tasks)} tasks")
    print()
    print("One JSONL row verbatim, as `--json` appended it:")
    print(raw_row)
    print()

    print(RULE)
    print("VERDICT")
    print(RULE)
    if failures:
        print(f"FAILED — {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        if discard:
            print()
            print("EXPECTED: the mutation is supposed to falsify these checks. A red run")
            print("here is the pin, not a defect.")
        return 1
    print(f"PASSED — on all {len(rows)} workload tasks: the recorded columns reconcile with")
    print("the ledger the run built, column 7 reconciles with the serializer it mirrors,")
    print("and the same realised repeat-read count is readable off the CLI's own JSONL —")
    print("the artifact bar §7.2 measured as unreachable at 26e81a0.")
    if discard:
        print()
        print("UNEXPECTED: the mutation changed NOTHING. Under the v0.21.0 pinning bar")
        print("that means these checks do not pin the claim.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
