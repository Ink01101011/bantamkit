"""Reference side of the `skill-promote` conformance suite (#206 Task 9).

Imports `bantamkit.skillpromote` rather than copying it. The Node half of the suite runs the
same op list against `runtime-ts/dist/skillpromote.js` with an interpreter written to this
table. Every op runs in order in ONE bed; `home` names a directory under it, `cwd` (optional)
a directory under it too. Any string in an op may hold `<bed>`, replaced by the bed's path
before the op runs; every path in an answer is masked back to `<bed>`.

    {"op": "constants"}  -> [PROMOTE_USES, PROMOTE_DAYS, BUDGET_DEFAULT, BUDGET_ENV, MODE_SYMLINK, MODE_COPY]
    {"op": "budget", "env"}                                -> skill_budget() with the env value
    {"op": "install", "home", "name", "level", "top"?, "now"} -> {"tree"} (an approved install)
    {"op": "mkdir" | "write" | "symlink", "home", "rel", "text"? | "target"?} -> {}
    {"op": "append", "home", "rel", "text"}                -> {}
    {"op": "promote", "home", "name", "cwd"?, "now", "budget", "symlink_fails"?, "env"?}
        -> {"result": {ok, mode, reason}} | {"error"}, plus "state", "tree"
    {"op": "demote", "home", "name"}                       -> {"said"} | {"error"}, plus "state", "tree"
    {"op": "promote_step", "home", "uses", "cwd"?, "now", "budget", "symlink_fails"?, "auto"?}
        -> {"events", "state"} | {"error"}, plus "tree"
    {"op": "layer", "home"}                                -> the `[skill]` layer's offered names

`symlink_fails` makes the symlink call raise: `EPERM`, `EACCES`, `ENOENT` (an errno), or
`WIN1314` (Windows' privilege error: an `OSError` whose `winerror` is 1314; libuv reports the
same failure as `EPERM`, which is what the Node side raises). `env` is the value of
`BANTAMKIT_SKILL_BUDGET` for that op (absent or null: unset). `auto` (job73 C15) is the value
of `BANTAMKIT_SKILL_AUTO` for that op (absent or null: UNSET, the 0.37.0 default, off — not the
harness's pinned `off`); automatic promotion follows it. `tree` is every file and symlink
under the op's home: a file's text, a symlink as `-> <its target>`, a directory as `<path>/`.

    {"bed": <dir>, "ops": [...]} -> {"results": [...]}
"""

from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skillfile as sf
from bantamkit import skillinstall as si
from bantamkit import skillpromote as sp
from bantamkit.memory.skills import SkillStore


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
        for n in dirnames + filenames:
            p = Path(dirpath, n)
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                out[rel] = "-> " + os.readlink(p).replace(bed, "<bed>")
            elif p.is_dir():
                out[rel + "/"] = None
            else:
                try:
                    text = p.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    text = "<not utf-8>"
                out[rel] = text.replace(bed, "<bed>")
    return dict(sorted(out.items()))


def draft(name: str) -> str:
    return (
        f"---\nname: {name}\ndescription: Does {name}. Use when {name} is asked.\n---\n\n"
        "## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n"
        "## Pitfalls\n\nNone.\n\n## Example\n\nx\n"
    )


def cluster(name: str, level: str, top: str | None) -> dict:
    return {
        "evidence": [{"id": "job1/U1", "ok": True, "ts": "2026-01-01T00:00:00Z"}],
        "id": f"c-{name}",
        "keywords": ["k1"],
        "level": level,
        "members": 3,
        "source": "shiftwork",
        "status": "pending",
        "successes": 3,
        "top": top,
    }


def failing(kind: str):
    def symlink(target: str, link: str) -> None:
        if kind == "WIN1314":
            e = OSError(errno.EINVAL, "A required privilege is not held by the client")
            e.winerror = 1314  # type: ignore[attr-defined]
            raise e
        code = getattr(errno, kind)
        raise OSError(code, os.strerror(code))

    return symlink


def run(bed: Path, op: dict):
    b = str(bed)
    op = sub(op, b)
    kind = op["op"]
    home = bed / op["home"] if "home" in op else bed
    cwd = str(bed / op["cwd"]) if op.get("cwd") else None
    saved_env = os.environ.get(sp.BUDGET_ENV)
    if op.get("env") is None:
        os.environ.pop(sp.BUDGET_ENV, None)
    else:
        os.environ[sp.BUDGET_ENV] = op["env"]
    saved_auto = os.environ.get(si.AUTO_ENV)
    if op.get("auto") is None:
        os.environ.pop(si.AUTO_ENV, None)
    else:
        os.environ[si.AUTO_ENV] = op["auto"]
    try:
        if kind == "constants":
            return [
                sp.PROMOTE_USES,
                sp.PROMOTE_DAYS,
                sp.BUDGET_DEFAULT,
                sp.BUDGET_ENV,
                sp.MODE_SYMLINK,
                sp.MODE_COPY,
            ]
        if kind == "budget":
            return sp.skill_budget()
        if kind == "mkdir":
            (home / op["rel"]).mkdir(parents=True, exist_ok=True)
            return {}
        if kind == "write":
            p = home / op["rel"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(op["text"].encode("utf-8"))
            return {}
        if kind == "append":
            p = home / op["rel"]
            p.write_bytes(p.read_bytes() + op["text"].encode("utf-8"))
            return {}
        if kind == "symlink":
            p = home / op["rel"]
            p.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(op["target"], p, target_is_directory=True)
            return {}
        if kind == "layer":
            store = SkillStore([sf.skills_root(home)], home)
            return [f.name for f in store.candidates()]
        if kind == "install":
            top = str(bed / op["top"]) if op.get("top") else None
            si.install(
                cluster(op["name"], op["level"], top), draft(op["name"]), None, home, op["now"], False
            )
            return {"tree": mask(tree(home, b), b)}
        symlink = failing(op["symlink_fails"]) if op.get("symlink_fails") else None
        out: dict = {}
        try:
            if kind == "promote":
                got = sp.promote(
                    op["name"], home, cwd, op["now"], op.get("budget"), symlink=symlink
                )
                out["result"] = got.as_dict()
            elif kind == "demote":
                out["said"] = sp.demote(op["name"], home)
            elif kind == "promote_step":
                state = sf.read_state(home)
                out["events"] = sp.promote_step(
                    state, op["uses"], home, cwd, op["now"], op.get("budget"), symlink=symlink
                )
                out["returned_state"] = state
            else:
                raise SystemExit(f"skillpromote_ref: unknown op {kind!r}")
        except sf.SkillFileError as e:
            out = {"error": str(e)}
        out["state"] = sf.read_state(home)
        out["tree"] = tree(home, b)
        return mask(out, b)
    finally:
        if saved_env is None:
            os.environ.pop(sp.BUDGET_ENV, None)
        else:
            os.environ[sp.BUDGET_ENV] = saved_env
        if saved_auto is None:
            os.environ.pop(si.AUTO_ENV, None)
        else:
            os.environ[si.AUTO_ENV] = saved_auto


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    bed = Path(req["bed"])
    json.dump({"results": [run(bed, op) for op in req["ops"]]}, sys.stdout)


if __name__ == "__main__":
    main()
