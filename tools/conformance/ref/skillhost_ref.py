"""Reference side of `tools/conformance/suites/skill-host.mjs` (#205 Task 2): the product's own
`bantamkit.skillhost`, one answer per op, each the product's serialisation in base64.

    {"op": "usage", "projects", "now", "known": [..] | null}  -> b64(dumps(UsageScan.summary()))
    {"op": "gather", "home", "cwd": str | null, "now"}         -> b64(dumps(Gathered.as_dict()))

Task 3 (`skillreport`):

    {"op": "record", "home", "cwd", "now", "no_usage"?}  -> b64(dumps(record))
    {"op": "render", "home", "cwd", "now", "no_usage"?}  -> b64(render_report(record))
    {"op": "propose", "home", "cwd", "now", "usage": {..} | null, "span_days"}
                                                        -> b64(dumps(propose(...)))

`record`/`render` are `run_live`; with `no_usage` they gather, drop `usage` and build — the only
way a bed with roots has no measurement. `propose` scans the gathered roots and calls
`propose` with the usage and span given, so a missing measurement can be shown at 30 days.

Task 4 (the daily run). An op's `env` is applied for that op only (a value null unsets it):

    {"op": "put", "path", "data": b64}                  -> b64("")  (writes the bytes, parents made)
    {"op": "resurface", "home"}                         -> b64("")  (surfaced = every finding's
                                                           key + "gone\t\t", written back)
    {"op": "daily", "home", "cwd", "now"}               -> b64(skill-audit.json) | null
    {"op": "status", "home", "env"}                     -> b64(status_line(home))
    {"op": "child", "base", "home", "cwd", "now", "env", "fresh": "both"|"audit"|null}
        -> b64(dumps({"audit": skill-audit.json | null, "state": retention.json | null,
                      "changed": [every path under `base` whose bytes or mtime_ns changed]}))

    {"op": "spawn", "home", "env"}                      -> b64(maybe_spawn's word)  (retention.json
                                                           is first stamped at the wall clock, so
                                                           the answer is `off` or `fresh`, never a
                                                           spawned child)

`child` runs `retention.child_main([cwd, home], now)` in process; `fresh` first removes both
state files (or only `skill-audit.json`), BEFORE the snapshot is taken.

`dumps` is `storage.hotindex.dumps`, which `hotindex.ts` `dumpIndex` mirrors byte for byte.
"""

import base64
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skillaudit, skillhost, skillreport
from bantamkit.storage import retention
from bantamkit.storage.hotindex import dumps
from bantamkit.storage.retention import parse_now


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _read(p: Path) -> str | None:
    try:
        return p.read_bytes().decode("utf-8")
    except OSError:
        return None


def _snapshot(base: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, dirs, files in os.walk(base):
        for name in dirs + files:
            p = Path(dirpath) / name
            st = p.lstat()
            if p.is_symlink():
                what = f"link {os.readlink(p)}"
            elif p.is_dir():
                # A directory's mtime moves with any lock file; adds and removes show as paths.
                out[p.relative_to(base).as_posix()] = "dir"
                continue
            else:
                what = hashlib.sha256(p.read_bytes()).hexdigest()
            out[p.relative_to(base).as_posix()] = f"{what} {st.st_mtime_ns}"
    return out


def _with_env(env: dict | None, fn):
    saved = {k: os.environ.get(k) for k in (env or {})}
    try:
        for k, v in (env or {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _task4(op: dict) -> str | None:
    if op["op"] == "put":
        p = Path(op["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(base64.b64decode(op["data"]))
        return _b64("")
    if op["op"] == "resurface":
        path = skillreport.state_path(op["home"])
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["surfaced"] = [skillreport.surface_key(f) for f in rec["findings"]] + ["gone\t\t"]
        path.write_text(json.dumps(rec), encoding="utf-8")
        return _b64("")
    if op["op"] == "daily":
        skillreport.daily(op["home"], op["cwd"], op["now"])
        text = _read(skillreport.state_path(op["home"]))
        return None if text is None else _b64(text)
    if op["op"] == "status":
        return _b64(_with_env(op.get("env"), lambda: skillreport.status_line(op["home"])))
    if op["op"] == "spawn":
        home = Path(op["home"])
        retention.state_path(home).write_text(
            json.dumps({"ran_at": retention.now_stamp()}), encoding="utf-8"
        )
        return _b64(_with_env(op.get("env"), lambda: retention.maybe_spawn(home, str(home))))
    if op["op"] == "child":
        home = Path(op["home"])
        if op.get("fresh") in ("both", "audit"):
            skillreport.state_path(home).unlink(missing_ok=True)
        if op.get("fresh") == "both":
            retention.state_path(home).unlink(missing_ok=True)
        base = Path(op["base"])
        before = _snapshot(base)
        _with_env(
            op.get("env"), lambda: retention.child_main([op["cwd"], str(home)], now=op["now"])
        )
        after = _snapshot(base)
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        return _b64(
            dumps(
                {
                    "audit": _read(skillreport.state_path(home)),
                    "state": _read(retention.state_path(home)),
                    "changed": changed,
                }
            )
        )
    raise ValueError(f"unknown op {op['op']!r}")


def _one(op: dict) -> str | None:
    if op["op"] in ("put", "resurface", "daily", "status", "child", "spawn"):
        return _task4(op)
    now = parse_now(op["now"])
    if op["op"] == "usage":
        known = None if op.get("known") is None else frozenset(op["known"])
        return _b64(
            dumps(skillhost.count_skill_usage(Path(op["projects"]), now, known=known).summary())
        )
    if op["op"] == "gather":
        adapter = skillhost.select_adapter(op["home"])
        return _b64(dumps(adapter.gather(op["home"], op["cwd"], now).as_dict()))
    if op["op"] in ("record", "render"):
        if op.get("no_usage"):
            g = skillhost.select_adapter(op["home"]).gather(op["home"], op["cwd"], now)
            rec = skillreport.build_record(dataclasses.replace(g, usage=None), op["now"])
        else:
            rec = skillreport.run_live(op["home"], op["cwd"], op["now"])
        return _b64(dumps(rec) if op["op"] == "record" else skillreport.render_report(rec))
    if op["op"] == "propose":
        g = skillhost.select_adapter(op["home"]).gather(op["home"], op["cwd"], now)
        found = skillaudit.scan_roots(list(g.roots), list(g.enabled), g.versions)
        return _b64(dumps(skillreport.propose(found, op["usage"], op["span_days"], g.sources)))
    raise ValueError(f"unknown op {op['op']!r}")


def main() -> None:
    req = json.loads(sys.stdin.read())
    json.dump({"answers": [_one(op) for op in req["ops"]]}, sys.stdout)


if __name__ == "__main__":
    main()
