"""Reference side of the `skill-file` conformance suite — the Agent Skills file (#206 Task 1).

Imports `bantamkit.skillfile` rather than copying it (a hand copy would agree by
construction). The suite sends a list of ops; this answers one result per op, and the Node
half of the suite runs the same list against `dist/skillfile.js` with an interpreter written
to the same table:

    {"op": "parse", "text"}                      -> {"doc"} | {"error"}
    {"op": "validate", "doc", "dirname"?}        -> [sentence, ...]
    {"op": "validate_text", "text", "dirname"?}  -> [sentence, ...] | {"error"}
    {"op": "hash", "text"}                       -> hex
    {"op": "edited", "text"}                     -> bool
    {"op": "render", "doc"}                      -> {"text"} | {"error"}
    {"op": "roundtrip", "doc"}                   -> {"doc"} | {"error"}   (parse(render(doc)))
    {"op": "stamp", "text", "updates"}           -> {"text"} | {"error"}
    {"op": "write", "target", "files", "fail_at"?}          -> {"error"?, "tree"}
    {"op": "replace", "target", "files", "now", "fail_at"?} -> {"backup"?, "error"?, "tree"}
    {"op": "absent", "name", "now"}              -> {"backup"}
    {"op": "undo", "name", "target"}             -> {"said"} | {"error"}, plus "tree"
    {"op": "history", "target", "version"}       -> {"error"?, "tree"}
    {"op": "stamp_dir", "now"}                   -> {"stamp"} | {"error"}
    {"op": "state_write", "state"}               -> {"tree"}
    {"op": "state_read", "raw"?}                 -> {"state"} | {"error"}
    {"op": "state_plant", "plant"}               -> {"error"?, "tree", "victim", "state"} | {"skipped"}

    {"bed": <dir>, "ops": [...]} -> {"results": [...]}

Paths in ops are relative to the bed; every path in an answer is made relative to it again
(`<bed>`), so the two sides' beds compare. `tree` is every path under the bed with each
file's bytes as base64. A non-`SkillFileError` failure (the injected one) answers
`{"error": "raised"}`: the property under test is what is left on disk, not the message.

`fail_at` replaces one seam for one op: `write` fails the SECOND file write after writing
it (so a partial temp dir exists), `fsync` fails every fsync, `rename` fails every rename,
`rename2` fails only the second rename (old aside, new in fails, old must come back).
A metadata value that is not str/list/dict travels as `{"py": type(v).__name__}`.

`state_plant` (#250) writes a state, plants a `symlink` to `<bed>/victim` (or a `file`) at the
temp name the next state write will use (the temp seam is pinned to `<target>.<kind>-planted`,
the name an attacker predicts), writes again, answers, then removes what it planted. `victim`
and `state` are the bytes left as UTF-8 text. A side that cannot make a symlink answers
`{"skipped": true}`. In `tree` a symlink is the string `"symlink"`, never its target's bytes.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skillfile as sf


def plain(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    return {"py": type(v).__name__}


def doc_out(d: sf.SkillDoc) -> dict:
    return {
        "name": d.name,
        "description": d.description,
        "metadata": plain(d.metadata),
        "body": d.body,
    }


def doc_in(o: dict) -> sf.SkillDoc:
    return sf.SkillDoc(o["name"], o["description"], dict(o.get("metadata", {})), o.get("body", ""))


def tree(bed: Path) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(bed):
        for n in dirnames:
            out[Path(dirpath, n).relative_to(bed).as_posix() + "/"] = None
        for n in filenames:
            p = Path(dirpath, n)
            if p.is_symlink():
                out[p.relative_to(bed).as_posix()] = "symlink"
                continue
            out[p.relative_to(bed).as_posix()] = base64.b64encode(p.read_bytes()).decode("ascii")
    return dict(sorted(out.items()))


def rel(bed: Path, s: str) -> str:
    return s.replace(str(bed), "<bed>")


def seams(fail_at):
    saved = (sf._write, sf._fsync, sf._rename)
    if fail_at == "write":
        calls = [0]
        real = sf._write

        def w(path, data):
            calls[0] += 1
            real(path, data)
            if calls[0] == 2:
                raise OSError("injected")

        sf._write = w
    elif fail_at == "fsync":

        def f(fd):
            raise OSError("injected")

        sf._fsync = f
    elif fail_at in ("rename", "rename2"):
        calls = [0]
        real = sf._rename

        def r(src, dst):
            calls[0] += 1
            if fail_at == "rename" or calls[0] == 2:
                raise OSError("injected")
            real(src, dst)

        sf._rename = r
    return saved


def guarded(bed: Path, fn) -> dict:
    try:
        out = fn() or {}
    except sf.SkillFileError as e:
        out = {"error": rel(bed, str(e))}
    except OSError:
        out = {"error": "raised"}
    return out


def files_in(o: dict) -> dict:
    return {k: base64.b64decode(v) for k, v in o.items()}


def run(bed: Path, op: dict):
    kind = op["op"]
    if kind == "parse":
        return guarded(bed, lambda: {"doc": doc_out(sf.parse_skill(op["text"]))})
    if kind == "validate":
        return sf.validate(doc_in(op["doc"]), op.get("dirname"))
    if kind == "validate_text":
        return guarded(
            bed, lambda: {"found": sf.validate(sf.parse_skill(op["text"]), op.get("dirname"))}
        )
    if kind == "hash":
        return sf.canonical_hash(op["text"])
    if kind == "edited":
        return sf.is_edited(op["text"])
    if kind == "render":
        return guarded(bed, lambda: {"text": sf.render(doc_in(op["doc"]))})
    if kind == "roundtrip":
        return guarded(bed, lambda: {"doc": doc_out(sf.parse_skill(sf.render(doc_in(op["doc"]))))})
    if kind == "stamp":
        return guarded(bed, lambda: {"text": sf.stamp(op["text"], op["updates"])})
    if kind == "stamp_dir":
        return guarded(bed, lambda: {"stamp": sf.backup_stamp(op["now"])})
    if kind in ("write", "replace", "absent", "undo", "history"):
        saved = seams(op.get("fail_at"))
        try:
            if kind == "write":
                out = guarded(
                    bed, lambda: sf.write_dir_atomic(bed / op["target"], files_in(op["files"]))
                )
            elif kind == "replace":
                out = guarded(
                    bed,
                    lambda: {
                        "backup": sf.replace_dir_atomic(
                            bed / op["target"], files_in(op["files"]), bed / "backups", op["now"]
                        )
                        .relative_to(bed)
                        .as_posix()
                    },
                )
            elif kind == "absent":
                out = guarded(
                    bed,
                    lambda: {
                        "backup": sf.backup_absent(bed / "backups", op["name"], op["now"])
                        .relative_to(bed)
                        .as_posix()
                    },
                )
            elif kind == "undo":
                out = guarded(
                    bed, lambda: {"said": sf.undo(bed / "backups", op["name"], bed / op["target"])}
                )
            else:
                out = guarded(bed, lambda: sf.history_add(bed / op["target"], op["version"]))
        finally:
            sf._write, sf._fsync, sf._rename = saved
        out["tree"] = tree(bed)
        return out
    if kind == "state_write":
        sf.write_state(bed / "home", op["state"])
        return {"tree": tree(bed)}
    if kind == "state_read":
        if "raw" in op:
            p = sf.state_path(bed / "home")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(base64.b64decode(op["raw"]))
        return guarded(bed, lambda: {"state": sf.read_state(bed / "home")})
    if kind == "state_plant":
        home = bed / "home"
        sf.write_state(home, {"skills": {"before": {}}})
        victim = bed / "victim"
        victim.write_bytes(b"KEEP")
        planted = Path(f"{sf.state_path(home)}.tmp-planted")
        if op["plant"] == "symlink":
            try:
                os.symlink(victim, planted)
            except OSError:
                victim.unlink()
                return {"skipped": True}
        else:
            planted.write_bytes(b"THEIRS")
        saved_temp = sf._temp
        sf._temp = lambda target, k: f"{target}.{k}-planted"
        try:
            out = guarded(bed, lambda: sf.write_state(home, {"skills": {"injected": {}}}))
        finally:
            sf._temp = saved_temp
        out["tree"] = tree(bed)
        out["victim"] = victim.read_text(encoding="utf-8")
        out["state"] = sf.state_path(home).read_text(encoding="utf-8")
        planted.unlink(missing_ok=True)  # a writer that follows the link renames it away
        victim.unlink()
        return out
    raise SystemExit(f"skillfile_ref: unknown op {kind!r}")


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    bed = Path(req["bed"])
    json.dump({"results": [run(bed, op) for op in req["ops"]]}, sys.stdout)


if __name__ == "__main__":
    main()
