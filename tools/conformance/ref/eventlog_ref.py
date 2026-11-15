"""Reference side of the `eventlog` conformance suite — the MCP event log (#316 G2, job88 J88-1).

Imports `bantamkit.eventlog` rather than copying it, for the reason every reference here gives: a
hand copy would be a third implementation that agrees with the module by construction.

Before this suite the event log was compared only THROUGH a session (`wire`'s `eventlog` block:
the record stream a real server writes, `ts` masked) and through `storage-log`'s `ev` op (one
record shape, the plain `.1` rotation). Its public functions — `format_timestamp`,
`encode_record`, `resolve_path`, `default_path`, `EventLog.from_env` and `raised` — were held only
by per-side unit tests, each to its own author's reading.

EVERY ANSWER IS DATA, NEVER A RAISE OUT OF THIS PROCESS: an input that makes one runtime raise is
a finding, so an exception travels as `{"raises": <type name>}` and the harness still reaches its
summary line. Bytes travel as base64. A detail object travels BY NAME (`DETAILS`), because a JSON
payload cannot carry `1.0`, `NaN`, `2**64` or a lone surrogate to both sides intact; each side
builds the named value in code, the Node half from its own table of the same names.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"op": "constants"}
      -> {"EVENT_LOG_ENV", "DEFAULT_RELATIVE_PATH", "CAP_BYTES", "SCHEMA_VERSION"}
    {"op": "timestamps", "ms": [n, ...]}            -> {"out": [str | {"raises": name}, ...]}
    {"op": "encode", "cases": [[ms, tool, outcome, detail name], ...]}
                                                     -> {"out": [{"b64"} | {"raises"}, ...]}
    {"op": "resolve", "store": str, "raws": [str | null, ...]}
                                                     -> {"out": [str | null, ...], "default": str}
    {"op": "from_env", "store": str, "envs": [{...}, ...]}
                                                     -> {"out": [{"enabled", "path", "requires_dir"}]}
    {"op": "beds", "beds": [{"root", "setup": [[kind, rel, text?], ...], "log": {...},
                             "calls": [[...], ...]}]}
      -> {"out": [{"calls": [null | {"raises"}], "write_failed", "enabled", "tree"}, ...]}

A bed's `log` is `{"from_env": {"store": rel, "env": {...}}}` or `{"path": rel, "cap": n}` (a
literal path the operator spells, a trailing `/` included, reaches the module only through the
environment, so a bed that needs one spells it in `env`);
its calls are `["record", tool, outcome, detail name]` or `["raised", tool, errno name]`. `tree`
lists every entry under `root` in code-point order as `[rel, "<dir>"]` or `[rel, b64 bytes]`.
"""

from __future__ import annotations

import base64
import errno
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import eventlog

#: The detail objects both halves build in code, by name (the Node half's `DETAILS` matches).
DETAILS = {
    "empty": lambda: {},
    "tokens": lambda: {"result": "saved", "count": 3, "dedup": False},
    "unsorted": lambda: {"z": 1, "a": True, "m": "x"},
    "non_ascii_keys": lambda: {"ก": 1, "ｚ": 2, "😀": 3, "a": 4},
    "non_ascii_value": lambda: {"v": "ไทย😀"},
    "ints": lambda: {"n": -5, "z": 0, "max": 9007199254740991},
    "proto_key": lambda: json.loads('{"__proto__": 1, "a": 2}'),
    "integer_keys": lambda: {"10": 1, "9": 2, "a": 3},
    "float_integral": lambda: {"f": 1.0},
    "float_exponent": lambda: {"f": 1e-7},
    "nan": lambda: {"n": float("nan")},
    "lone_surrogate": lambda: {"s": "x\ud800y"},
    "bigint": lambda: {"b": 2**64},
    "neg_zero": lambda: {"z": -0.0},
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _raises(exc: BaseException) -> dict:
    return {"raises": type(exc).__name__}


def _tree(root: Path) -> list:
    out = []

    def visit(d: Path, prefix: str) -> None:
        for name in sorted(os.listdir(d)):
            p = d / name
            rel = f"{prefix}{name}"
            if p.is_dir() and not p.is_symlink():
                out.append([rel, "<dir>"])
                visit(p, f"{rel}/")
            else:
                out.append([rel, _b64(p.read_bytes())])

    if root.exists():
        visit(root, "")
    return out


def _path_or_none(p) -> str | None:
    return None if p is None else str(p)


def run_bed(bed: dict) -> dict:
    root = Path(bed["root"])
    root.mkdir(parents=True, exist_ok=True)
    for step in bed.get("setup", []):
        kind, rel = step[0], step[1]
        target = root / rel
        if kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(step[2].encode("utf-8"))
    spec = bed["log"]
    if "from_env" in spec:
        log = eventlog.EventLog.from_env(
            root / spec["from_env"]["store"], spec["from_env"]["env"], clock=lambda: 0
        )
    else:
        log = eventlog.EventLog(
            root / spec["path"], cap_bytes=spec.get("cap", eventlog.CAP_BYTES), clock=lambda: 0
        )
    calls = []
    for call in bed.get("calls", []):
        try:
            if call[0] == "record":
                log.record(call[1], call[2], DETAILS[call[3]]())
            else:
                code = getattr(errno, call[2], None)
                exc = OSError(code if code is not None else 99999, "probe")
                log.raised(call[1], exc)
            calls.append(None)
        except Exception as exc:  # noqa: BLE001 - a raise is an answer here
            calls.append(_raises(exc))
    return {
        "calls": calls,
        "write_failed": log.write_failed,
        "enabled": log.enabled,
        "tree": _tree(root),
    }


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = req["op"]
    if op == "constants":
        out = {
            "EVENT_LOG_ENV": eventlog.EVENT_LOG_ENV,
            "DEFAULT_RELATIVE_PATH": list(eventlog.DEFAULT_RELATIVE_PATH),
            "CAP_BYTES": eventlog.CAP_BYTES,
            "SCHEMA_VERSION": eventlog.SCHEMA_VERSION,
        }
    elif op == "timestamps":
        res = []
        for ms in req["ms"]:
            try:
                res.append(eventlog.format_timestamp(ms))
            except Exception as exc:  # noqa: BLE001
                res.append(_raises(exc))
        out = {"out": res}
    elif op == "encode":
        res = []
        for ms, tool, outcome, name in req["cases"]:
            try:
                res.append(
                    {"b64": _b64(eventlog.encode_record(ms, tool, outcome, DETAILS[name]()))}
                )
            except Exception as exc:  # noqa: BLE001
                res.append(_raises(exc))
        out = {"out": res}
    elif op == "resolve":
        store = Path(req["store"])
        out = {
            "out": [_path_or_none(eventlog.resolve_path(store, raw)) for raw in req["raws"]],
            "default": str(eventlog.default_path(store)),
        }
    elif op == "from_env":
        res = []
        for env in req["envs"]:
            log = eventlog.EventLog.from_env(Path(req["store"]), env, clock=lambda: 0)
            res.append(
                {
                    "enabled": log.enabled,
                    "path": _path_or_none(log.path),
                    "requires_dir": _path_or_none(log.requires_dir),
                }
            )
        out = {"out": res}
    elif op == "beds":
        out = {"out": [run_bed(b) for b in req["beds"]]}
    else:
        raise SystemExit(f"eventlog_ref: unknown op {op!r}")
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
