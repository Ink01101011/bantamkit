"""Reference side of the `skill-propose` conformance suite (#206 Task 11).

Imports `bantamkit.skillpropose` rather than copying it. The Node half runs the same op list
against `runtime-ts/dist/skillpropose.js` with an interpreter written to this table. Every op
runs in order in ONE bed; `home` and `cwd` name directories under it. Any string in an op may
hold `<bed>`, replaced by the bed's path before the op runs; every path in an answer is masked
back to `<bed>`.

    {"op": "put", "home", "rel", "text"}                      -> {}
    {"op": "render", "home", "cwd", "action", "target", "level", "now", "sampler"}
        -> {"text", "calls", "tree"}
    {"op": "line", "home", "env"?}                            -> {"line", "tree"}
    {"op": "render_line", "items"}                            -> {"line"}
    {"op": "event_item", "event"}                             -> {"item"}
    {"op": "constants"}                                       -> [...]

`sampler` is null (the client declared no sampling) or `{"answer": str | null}`: the stub
answers that text (null: no text, which the drafter counts unreachable), and `calls` is the
SHA-256 of `system NUL user` of every request it was sent. `env` is the value of
`BANTAMKIT_SKILL_AUDIT` for that op (absent or null: unset). `tree` is every entry under the
op's home: a file with its text, a directory as `<path>/`, a symlink as `<path> -> <target>`.

    {"bed": <dir>, "ops": [...]} -> {"results": [...]}
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skillpropose as sp


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


def tree(home: str) -> list[str]:
    out: list[str] = []

    def walk(d: str) -> None:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return
        for n in names:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, home).replace(os.sep, "/")
            if os.path.islink(p):
                out.append(f"{rel} -> {os.readlink(p).replace(os.sep, '/')}")
            elif os.path.isdir(p):
                out.append(f"{rel}/")
                walk(p)
            else:
                with open(p, "rb") as fh:
                    out.append(f"{rel}: {fh.read().decode('utf-8', 'replace')}")

    walk(home)
    return out


def run(op: dict, bed: str):
    kind = op["op"]
    if kind == "constants":
        return [
            sp.SKILL_PROPOSE_NAME,
            sp.SKILL_PROPOSE_PROMPT_TITLE,
            sp.SKILL_PROPOSE_PROMPT_DESCRIPTION,
            [list(a) for a in sp.ARGUMENTS],
            list(sp.ACTIONS),
            sp.COMMAND,
            sp.SAMPLING_MAX_TOKENS,
            sp.HANDOFF_DIR,
            sp.LINE_MAX_BYTES,
            sp.EMPTY,
        ]
    if kind == "render_line":
        return {"line": sp.render_line(op["items"])}
    if kind == "event_item":
        return {"item": sp.event_item(op["event"])}
    home = os.path.join(bed, op["home"])
    if kind == "put":
        p = Path(home) / op["rel"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(op["text"].encode("utf-8"))
        return {}
    if kind == "render":
        calls: list[str] = []
        sampler = None
        if op.get("sampler") is not None:
            answer = op["sampler"].get("answer")

            def sampler(system: str, user: str) -> str | None:
                calls.append(hashlib.sha256(f"{system}\0{user}".encode()).hexdigest())
                return answer

        cwd = os.path.join(bed, op["cwd"])
        os.makedirs(cwd, exist_ok=True)
        text = sp.render(
            op.get("action"), op.get("target"), op.get("level"), home, cwd, op["now"], sampler
        )
        return {"text": text, "calls": calls, "tree": tree(home)}
    if kind == "line":
        env = op.get("env")
        old = os.environ.pop("BANTAMKIT_SKILL_AUDIT", None)
        if env is not None:
            os.environ["BANTAMKIT_SKILL_AUDIT"] = env
        try:
            line = sp.session_line(home)
        finally:
            os.environ.pop("BANTAMKIT_SKILL_AUDIT", None)
            if old is not None:
                os.environ["BANTAMKIT_SKILL_AUDIT"] = old
        return {"line": line, "tree": tree(home)}
    raise ValueError(f"unknown op {kind}")


def main() -> None:
    payload = json.loads(sys.stdin.read())
    bed = payload["bed"]
    results = []
    for op in payload["ops"]:
        results.append(mask(run(sub(op, bed), bed), bed))
    sys.stdout.write(json.dumps({"results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
