"""Reference side of the shift-work conformance suite.

Same stance as the other four: this IMPORTS `bantamkit.shiftwork` and lets the real
`json`, the real `jsonschema` and the real `pathlib` answer, rather than restating what
they do. The drift alarm is the differential itself.

The ONE thing the harness does to the reference is pin its clock. `shiftwork._timestamp`
reads `time.time()`, and a differential that could not fix that would be comparing two
different seconds. The module's own `import time` is rebound to a shim on the module
OBJECT — a harness-side monkeypatch, in this process only. `runtime-py` is not modified.

Every string that must survive byte-exactly travels as base64 — file CONTENTS especially,
since the whole property under test is what bytes land on disk.

    {"op": "dumps", "cases": [{"text": b64_json_text, "indent": int|null, "sort": bool}]}
        -> {"results": [b64 | {"error": {...}}]}

    {"op": "timestamp", "values": [float]}
        -> {"stamps": [str]}

    {"op": "os_replace", "cases": [{"src": str, "dst": str, "create": bool}]}
        -> {"results": [b64_of_str_OSError]}

    {"op": "session", "cases": [{"name": str, "dir": str, "file": str,
                                 "checkpoint": b64|null, "calls": [...]}]}
        -> {"results": [{"steps": [{"result": b64_json_text,
                                    "checkpoint": b64|null, "log": b64|null,
                                    "tmp_left": bool}]}]}

A call is one of

    {"fn": "clock_in", "unit_id": str|null}
    {"fn": "status"}
    {"fn": "clock_out", "unit": str, "status": str, "now": float,
     "handoff_patch": b64_json_text|null, "history_entry": b64_json_text|null,
     "accounting": b64_json_text|null, "chmod": int|null}
    {"fn": "chmod", "path": str, "mode": int}          # set up a write failure
    {"fn": "mkdir", "path": str}                       # plant a directory in the way

A session case may also carry `"assets": <dir>`, which sets `BANTAMKIT_ASSETS` for that
case's calls and puts the environment back afterwards. Both runtimes honour that override
(`bantamkit/assets.py` and `runtime-ts/src/assets.ts`, same precedence), and it is the ONLY
way to reach the AS-2 empty-allowed-list branch: with the shipped schema, `minItems: 1`
refuses `roles: {implementer: []}` during the read and the model check is never called. The
suite points it at a pack whose checkpoint schema has lost that one keyword, which is the
shape the ruling is about — the schema is a SHARED asset, so a differential cannot see it
move, and a check whose safety rests on it fails open the day it does.

`handoff_patch`, `history_entry` and `accounting` travel as JSON TEXT and each side runs
its OWN decoder over the same bytes, so `{"tokens": 5.0}` stays a float on both sides.
That is the exact route; the lossy one (a value already through an SDK's `JSON.parse`) is
carried as a ruled case in the suite and never reaches here.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import shiftwork


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def b64b(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8", "surrogatepass")


def caught(exc: BaseException) -> dict:
    return {"error": {"type": type(exc).__name__, "message": b64(str(exc))}}


class _FrozenTime:
    """`time`, with `time()` pinned. Everything else is the real module."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def __getattr__(self, name: str):
        return getattr(time, name)


CLOCK = _FrozenTime()
shiftwork.time = CLOCK  # harness-side only; runtime-py on disk is untouched


def read_bytes(path: Path) -> str | None:
    try:
        return b64b(path.read_bytes())
    except OSError:
        return None


def main() -> None:
    # stdin is a byte protocol: decode it as utf-8, not through the ANSI code page.
    # See the note in tools/conformance/ref/codec_ref.py.
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = payload["op"]

    if op == "dumps":
        results = []
        for case in payload["cases"]:
            try:
                value = json.loads(unb64(case["text"]))
                results.append(
                    b64(json.dumps(value, indent=case.get("indent"), sort_keys=case.get("sort", False))),
                )
            except BaseException as e:  # noqa: BLE001 - the escape IS the measurement
                results.append(caught(e))
        json.dump({"results": results}, sys.stdout)
        return

    if op == "os_replace":
        # `pyReplace` is shiftwork's only two-filename syscall, and `OSError.__str__`
        # prints BOTH when `filename2` is set. Nothing in the session corpus can reach it
        # (a rename whose target directory is gone cannot be staged through clock_out), so
        # the sentence is measured directly rather than left to a defensive branch nobody
        # ever ran.
        results = []
        for case in payload["cases"]:
            src = Path(case["src"])
            if case.get("create", True):
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_text("x", encoding="utf-8")
            try:
                os.replace(str(src), case["dst"])
            except OSError as e:
                results.append(b64(str(e)))
            else:
                results.append(b64("(no error)"))
        json.dump({"results": results}, sys.stdout)
        return

    if op == "timestamp":
        json.dump({"stamps": [shiftwork._timestamp(v) for v in payload["values"]]}, sys.stdout)
        return

    if op == "session":
        results = []
        for case in payload["cases"]:
            root = Path(case["dir"])
            root.mkdir(parents=True, exist_ok=True)
            path = root / case["file"] if case["file"] else root
            if case.get("checkpoint") is not None:
                path.write_bytes(base64.b64decode(case["checkpoint"]))
            target = case.get("target", str(path))
            previous_assets = os.environ.get("BANTAMKIT_ASSETS")
            if case.get("assets"):
                os.environ["BANTAMKIT_ASSETS"] = case["assets"]
            steps = []
            for call in case["calls"]:
                fn = call["fn"]
                if fn == "chmod":
                    os.chmod(root / call["path"] if call["path"] else root, call["mode"])
                    steps.append({"result": b64("null"), "checkpoint": None, "log": None, "tmp_left": False})
                    continue
                if fn == "mkdir":
                    (root / call["path"]).mkdir(parents=True, exist_ok=True)
                    steps.append({"result": b64("null"), "checkpoint": None, "log": None, "tmp_left": False})
                    continue
                if fn == "clock_in":
                    answer = shiftwork.clock_in(target, call.get("unit_id"))
                elif fn == "status":
                    answer = shiftwork.status(target)
                elif fn == "clock_out":
                    CLOCK.now = call["now"]
                    answer = shiftwork.clock_out(
                        target,
                        call["unit"],
                        call["status"],
                        None if call.get("handoff_patch") is None else json.loads(unb64(call["handoff_patch"])),
                        None if call.get("history_entry") is None else json.loads(unb64(call["history_entry"])),
                        None if call.get("accounting") is None else json.loads(unb64(call["accounting"])),
                    )
                else:  # pragma: no cover - a typo in the suite, not a difference
                    raise SystemExit(f"unknown fn {fn!r}")
                tmp = Path(str(path) + ".tmp")
                steps.append(
                    {
                        # NOT sort_keys: the key ORDER of the returned dict is part of what
                        # the model reads, and a sorted comparison would hide a reordering.
                        "result": b64(json.dumps(answer)),
                        "checkpoint": read_bytes(path),
                        "log": read_bytes(Path(str(path) + ".log.jsonl")),
                        "tmp_left": tmp.exists(),
                    },
                )
            if case.get("assets"):
                if previous_assets is None:
                    del os.environ["BANTAMKIT_ASSETS"]
                else:
                    os.environ["BANTAMKIT_ASSETS"] = previous_assets
            results.append({"steps": steps})
        json.dump({"results": results}, sys.stdout)
        return

    raise SystemExit(f"unknown op {op!r}")


if __name__ == "__main__":
    main()
