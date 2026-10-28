"""Reference side of the `skill-improve` conformance suite (#206 Task 10a).

Imports `bantamkit.skillinstall` (and `skilldraft`, `skillmine`) rather than copying them. The
Node half of the suite runs the same op list against `runtime-ts/dist/` with an interpreter
written to this table. Every op runs in order in ONE bed; `home` names a directory under it.
Any string in an op may hold `<bed>`, replaced by the bed's path before the op runs; every path
in an answer is masked back to `<bed>`.

    {"op": "constants"} -> [JUDGE_USES, VERDICT_KEPT, VERDICT_ROLLED_BACK, HISTORY_DIR, VERSION_KINDS]
    {"op": "install", "home", "name", "text", "now"}  -> {"tree"} (an approved, user-level install)
    {"op": "mkdir", "home", "rel"}                    -> {}
    {"op": "append", "home", "rel", "text"}           -> {}
    {"op": "write", "home", "rel", "text"}            -> {} (parents made)
    {"op": "set_stats", "home", "name", "version", "stats"} -> {} (merged into that version's record)
    {"op": "new_version", "home", "name", "text", "now", "kind", "fail_at"?}
        -> {"said"} | {"error"}, plus "state", "tree"
    {"op": "stats_step", "home", "sources", "now"}    -> {"returned_state"} | {"error"}, plus "state"
    {"op": "judge_step", "home", "now", "fail_at"?}   -> {"events", "returned_state"} | {"error"},
        plus "state", "tree"
    {"op": "edited", "home", "name"}                  -> edited_by_hand(state entry)
    {"op": "gate", "home", "text", "own"?}            -> the gate's reasons (`own`: a skill name)
    {"op": "daily", "home", "now"}                    -> {"state", "tree"} (`BANTAMKIT_SKILL_AUDIT=on`,
        `BANTAMKIT_SKILL_AUTO=off` for the op; `tree` leaves out the miner's own two files, whose
        `ms` is a wall time)

Part 2 (#206 Task 10b):

    {"op": "constants2"} -> [TUNE_MIN_INJECTS, FALSE_FIRE_TUNE, MISS_TUNE, PITFALL_CHARS,
        TOGETHER_SESSIONS, TOGETHER_SHARE, ITEM_KINDS, TUNE_KINDS]
    {"op": "improve_prompt", "kinds", "text", "doc", "ids", "counts"} -> [system, user]
    {"op": "diff", "old", "new"} -> skill_diff
    {"op": "pitfall", "id", "failure"} -> pitfall_line
    {"op": "improve_step", "home", "sources", "doc", "now", "drafter"?, "env"?}
        -> {"events", "returned_state"} | {"error"}, plus "state", "tree". `drafter`: absent is no
        drafter; `{"answer": <text>}` a stub labelled `endpoint stub`; `"unreachable"` one that
        cannot be reached. `env` (job73 C13b): the value of `BANTAMKIT_SKILL_AUTO` for the op;
        absent or null is UNSET (the 0.37.0 default, off), not the harness's pinned `off`.
    {"op": "render", "home", "action", "target", "now", "answer"?} -> {"said"}, plus "state",
        "tree" (`answer`: a sampling client that answers it)

`fail_at: "rename3"` makes the third rename of the op raise (an OSError; the Node side raises an
Error with an errno code): the backup is in, the live directory is aside, the new one is not.
`tree` is every file and symlink under the op's home: a file's text, a symlink as
`-> <its target>`, a directory as `<path>/`.

    {"bed": <dir>, "ops": [...]} -> {"results": [...]}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skilldraft as sd
from bantamkit import skillfile as sf
from bantamkit import skillinstall as si
from bantamkit import skillmine as sm

MINER_FILES = ("skill-miner-cache.json", "skill-proposals.json")


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


def tree(root: Path, bed: str, skip: tuple[str, ...] = ()) -> dict:
    out = {}
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames + filenames:
            p = Path(dirpath, n)
            rel = p.relative_to(root).as_posix()
            if rel in skip:
                continue
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


def cluster(name: str) -> dict:
    return {
        "evidence": [{"id": "job1/U1", "ok": True, "ts": "2026-01-01T00:00:00Z"}],
        "id": f"c-{name}",
        "keywords": ["k1"],
        "level": "user",
        "members": 3,
        "source": "shiftwork",
        "status": "pending",
        "successes": 3,
        "top": None,
    }


class Stub:
    label = "endpoint stub"

    def __init__(self, answer):
        self.answer = answer

    def ask(self, system, user):
        if self.answer is None:
            raise OSError("unreachable")
        return self.answer


def run(bed: Path, op: dict):
    b = str(bed)
    op = sub(op, b)
    kind = op["op"]
    home = bed / op["home"] if "home" in op else bed
    if kind == "constants":
        return [
            si.JUDGE_USES,
            si.VERDICT_KEPT,
            si.VERDICT_ROLLED_BACK,
            si.HISTORY_DIR,
            list(si.VERSION_KINDS),
        ]
    if kind == "install":
        si.install(cluster(op["name"]), op["text"], None, home, op["now"], False)
        return {"tree": mask(tree(home, b), b)}
    if kind == "constants2":
        return [
            si.TUNE_MIN_INJECTS,
            list(si.FALSE_FIRE_TUNE),
            si.MISS_TUNE,
            si.PITFALL_CHARS,
            si.TOGETHER_SESSIONS,
            list(si.TOGETHER_SHARE),
            list(si.ITEM_KINDS),
            list(sd.TUNE_KINDS),
        ]
    if kind == "improve_prompt":
        b = sd.improve_bundle(op["doc"], "c-x", op["ids"])
        return list(sd.improve_prompt(op["kinds"], op["text"], b, op["counts"]))
    if kind == "diff":
        return si.skill_diff(op["old"], op["new"])
    if kind == "pitfall":
        return si.pitfall_line(op["id"], op["failure"])
    if kind == "render":
        from bantamkit import skillpropose as sp

        answer = op.get("answer")
        sampler = (lambda s, u: answer) if answer is not None else None
        said = sp.render(op["action"], op["target"], None, home, None, op["now"], sampler)
        return mask({"said": said, "state": sf.read_state(home), "tree": tree(home, b)}, b)
    if kind == "mkdir":
        (home / op["rel"]).mkdir(parents=True, exist_ok=True)
        return {}
    if kind == "append":
        p = home / op["rel"]
        p.write_bytes(p.read_bytes() + op["text"].encode("utf-8"))
        return {}
    if kind == "write":
        p = home / op["rel"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(op["text"].encode("utf-8"))
        return {}
    if kind == "set_stats":

        def change(state: dict) -> None:
            versions = state["skills"][op["name"]]["versions"]
            versions.setdefault(op["version"], {}).update(op["stats"])

        sf.update_state(home, change)
        return {}
    if kind == "edited":
        return si.edited_by_hand(sf.read_state(home)["skills"][op["name"]])
    if kind == "gate":
        own = sf.skills_root(home) / op["own"] if op.get("own") else None
        got = sd.gate(op["text"], sd.bundle(cluster("x")), home, None, own=own)
        return mask(got.reasons, b)
    if kind == "daily":
        saved = {k: os.environ.get(k) for k in ("BANTAMKIT_SKILL_AUDIT", "BANTAMKIT_SKILL_AUTO")}
        os.environ["BANTAMKIT_SKILL_AUDIT"] = "on"
        os.environ["BANTAMKIT_SKILL_AUTO"] = "off"
        try:
            sm.daily(home, None, op["now"])
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        skip = tuple(f".bantamkit/{n}" for n in MINER_FILES)
        return mask({"state": sf.read_state(home), "tree": tree(home, b, skip)}, b)
    saved_rename = sf._rename
    if op.get("fail_at") == "rename3":
        calls = [0]

        def rename(src, dst):
            calls[0] += 1
            if calls[0] == 3:
                raise OSError("injected")
            saved_rename(src, dst)

        sf._rename = rename
    out: dict = {}
    try:
        if kind == "new_version":
            out["said"] = si.new_version(op["name"], op["text"], home, op["now"], op["kind"])
        elif kind == "stats_step":
            state = sf.read_state(home)
            si.stats_step(state, op["sources"], home, op["now"])
            out["returned_state"] = state
        elif kind == "improve_step":
            state = sf.read_state(home)
            d = op.get("drafter")
            chain = [] if d is None else [Stub(None if d == "unreachable" else d["answer"])]
            saved_auto = os.environ.get(si.AUTO_ENV)
            if op.get("env") is None:
                os.environ.pop(si.AUTO_ENV, None)
            else:
                os.environ[si.AUTO_ENV] = op["env"]
            try:
                out["events"] = si.improve_step(
                    state, op["sources"], op.get("doc"), home, None, op["now"], chain
                )
            finally:
                if saved_auto is None:
                    os.environ.pop(si.AUTO_ENV, None)
                else:
                    os.environ[si.AUTO_ENV] = saved_auto
            out["returned_state"] = state
        elif kind == "judge_step":
            state = sf.read_state(home)
            out["events"] = si.judge_step(state, home, op["now"])
            out["returned_state"] = state
        else:
            raise SystemExit(f"skillimprove_ref: unknown op {kind!r}")
    except sf.SkillFileError as e:
        out = {"error": str(e)}
    except OSError:
        out = {"error": "OSError"}
    finally:
        sf._rename = saved_rename
    out["state"] = sf.read_state(home)
    if kind != "stats_step":
        out["tree"] = tree(home, b)
    return mask(out, b)


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    bed = Path(req["bed"])
    json.dump({"results": [run(bed, op) for op in req["ops"]]}, sys.stdout)


if __name__ == "__main__":
    main()
