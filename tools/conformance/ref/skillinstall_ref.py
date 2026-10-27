"""Reference side of the `skill-install` conformance suite (#206 Task 7).

Imports `bantamkit.skillinstall` rather than copying it. The Node half of the suite runs the
same op list against `runtime-ts/dist/skillinstall.js` with an interpreter written to this
table. Every op runs in order in ONE bed; `home` names a directory under it. Any string in an
op may hold `<bed>`, which is replaced by the bed's path before the op runs, and every path in
an answer is masked back to `<bed>`.

    {"op": "evidence", "cluster", "name", "level"}            -> {"text"}
    {"op": "install", "home", "cluster", "text", "level", "now", "auto", "fail_at"?}
        -> {"installed": {name, level, path, event, entry}} | {"error"}, plus "status", "tree"
    {"op": "auto", "home", "proposals", "now"}                -> {"events", "statuses", "state"} | {"error"}, plus "tree"
    {"op": "probation", "home", "uses", "now"}                -> {"events", "state"} | {"error"}, plus "tree"
    {"op": "undo", "home", "name"}                            -> {"said"} | {"error"}, plus "tree"
    {"op": "edit", "home", "rel", "find", "replace"}          -> {"tree"}
    {"op": "mkdir", "home", "rel"}                            -> {}
    {"op": "constants"}                                       -> [AUTO_PER_DAY, AUTO_LIVE_MAX, PROBATION_DAYS, KEYWORDS_MAX, EVIDENCE_PROJECT_CHARS, EVIDENCE_USER_CHARS, AUTO_ENV]

Every op may carry `"env"`: the value of `BANTAMKIT_SKILL_AUTO` for that op (absent or null:
unset). `fail_at: "rename2"` fails the second rename `skillfile` makes (the install's directory
rename, after the absent backup's); `"write3"` fails the third file write AFTER writing it (the
absent marker, SKILL.md, then evidence.md), so a skill written in place would be left half. `tree` is every file under the op's home with its text,
`<bed>` masked; a directory is `<path>/`. A non-`SkillFileError` failure answers
`{"error": "raised"}`: what is left on disk is the property, not the message.

    {"bed": <dir>, "ops": [...]} -> {"results": [...]}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skillfile as sf
from bantamkit import skillinstall as si


def sub(v, bed: str):
    if isinstance(v, str):
        return v.replace("<bed>", bed)
    if isinstance(v, list):
        return [sub(x, bed) for x in v]
    if isinstance(v, dict):
        return {k: sub(x, bed) for k, x in v.items()}
    return v


def mask(v, bed: str):
    if isinstance(v, str):
        return v.replace(bed, "<bed>")
    if isinstance(v, list):
        return [mask(x, bed) for x in v]
    if isinstance(v, dict):
        return {k: mask(x, bed) for k, x in v.items()}
    return v


def tree(root: Path, bed: str) -> dict:
    out = {}
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames:
            out[Path(dirpath, n).relative_to(root).as_posix() + "/"] = None
        for n in filenames:
            p = Path(dirpath, n)
            try:
                text = p.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                text = "<not utf-8>"
            out[p.relative_to(root).as_posix()] = text.replace(bed, "<bed>")
    return dict(sorted(out.items()))


def run(bed: Path, op: dict):
    b = str(bed)
    op = sub(op, b)
    kind = op["op"]
    home = bed / op["home"] if "home" in op else bed
    saved_env = os.environ.get(si.AUTO_ENV)
    if op.get("env") is None:
        os.environ.pop(si.AUTO_ENV, None)
    else:
        os.environ[si.AUTO_ENV] = op["env"]
    saved_rename = sf._rename
    saved_write = sf._write
    try:
        if kind == "constants":
            return [
                si.AUTO_PER_DAY,
                si.AUTO_LIVE_MAX,
                si.PROBATION_DAYS,
                si.KEYWORDS_MAX,
                si.EVIDENCE_PROJECT_CHARS,
                si.EVIDENCE_USER_CHARS,
                si.AUTO_ENV,
            ]
        if kind == "evidence":
            return {"text": si.evidence_markdown(op["cluster"], op["name"], op["level"])}
        if kind == "mkdir":
            (home / op["rel"]).mkdir(parents=True, exist_ok=True)
            return {}
        if kind == "edit":
            p = home / op["rel"]
            p.write_bytes(p.read_bytes().replace(op["find"].encode(), op["replace"].encode()))
            return {"tree": tree(home, b)}
        if op.get("fail_at") == "rename2":
            calls = [0]

            def rename(src, dst):
                calls[0] += 1
                if calls[0] == 2:
                    raise OSError("injected")
                saved_rename(src, dst)

            sf._rename = rename
        if op.get("fail_at") == "write3":
            writes = [0]

            def write(path, data):
                writes[0] += 1
                saved_write(path, data)
                if writes[0] == 3:
                    raise OSError("injected")

            sf._write = write
        out: dict = {}
        try:
            if kind == "install":
                cluster = op["cluster"]
                got = si.install(
                    cluster, op["text"], op.get("level"), home, op["now"], op["auto"]
                )
                out["installed"] = {
                    "name": got.name,
                    "level": got.level,
                    "path": got.path,
                    "event": got.event,
                    "entry": got.entry,
                }
            elif kind == "auto":
                props = op["proposals"]
                state = sf.read_state(home)
                out["events"] = si.auto_step(props, state, home, op["now"])
                out["statuses"] = [r.get("status") for r in props["clusters"]]
                out["state"] = state
            elif kind == "probation":
                state = sf.read_state(home)
                out["events"] = si.probation_step(state, op["uses"], home, op["now"])
                out["state"] = state
            elif kind == "undo":
                out["said"] = si.undo(op["name"], home)
            else:
                raise SystemExit(f"skillinstall_ref: unknown op {kind!r}")
        except sf.SkillFileError as e:
            out = {"error": str(e)}
        except OSError:
            out = {"error": "raised"}
        if kind == "install":
            out["status"] = op["cluster"].get("status")
        out["tree"] = tree(home, b)
        return mask(out, b)
    finally:
        sf._rename = saved_rename
        sf._write = saved_write
        if saved_env is None:
            os.environ.pop(si.AUTO_ENV, None)
        else:
            os.environ[si.AUTO_ENV] = saved_env


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    bed = Path(req["bed"])
    json.dump({"results": [run(bed, op) for op in req["ops"]]}, sys.stdout)


if __name__ == "__main__":
    main()
