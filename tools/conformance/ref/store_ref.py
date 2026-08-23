"""Reference side of the MemoryStore conformance suite.

WHY THIS ONE IMPORTS `bantamkit` AND `codec_ref.py` DOES NOT
------------------------------------------------------------
`codec_ref.py` copies the six-line `_write_fact` expression on purpose, so that editing the
store makes the harness disagree with it and go red. That trade does not carry over here:
the store is three hundred lines of stateful filesystem behaviour, and a hand copy would be
a SECOND implementation needing its own review — the exact thing the port is trying not to
have two of.

The drift alarm is not lost, it moves. This suite runs the SAME op against two copies of one
directory and diffs the whole tree, so any change to `store.py` that changes a byte turns the
suite red immediately: the port stops matching the new reference. That is a stronger alarm
than a copy going stale, because it fires on behaviour rather than on text.

Protocol: one JSON request on stdin, one JSON response on stdout. Every string that must
survive byte-exactly travels as base64.

    {"op": "run", "root": <path>, "today": "YYYY-MM-DD", "index_budget": int|null,
     "k": int|null, "create": bool, "calls": [{"op": ..., "args": [...]}, ...]}
      -> {"results": [<result>|{"error": {...}}, ...]}

    {"op": "strerror", "names": ["EACCES", ...]}  -> {"strerror": {name: text}}
    {"op": "decode",   "seqs": [[byte, ...]]}     -> {"decoded": [{...}]}
    {"op": "tokens",   "texts_b64": [...]}        -> {"tokens": [[...]]}
    {"op": "jaccard",  "pairs": [[[tok], [tok]]]}  -> {"jaccard": [float]}
    {"op": "sortpaths","dir": str, "names": [...]}-> {"sorted": [...]}
    {"op": "paths",    "joins": [[part, ...]], "suffixes": [[path, suffix]]}
      -> {"joined": [...], "suffixed": [...]}
"""

from __future__ import annotations

import base64
import errno as errno_mod
import json
import os
import sys
from pathlib import Path, PurePath

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory.store import MemoryStore, _jaccard, _tokens


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8", "surrogatepass")


def fact_json(fact) -> dict:
    """A `Fact` as JSON. `name` and friends are whatever the frontmatter resolved to."""
    # A field is `None` on BOTH sides or a string on both: `None` stays JSON null rather
    # than becoming the text "None", because the two runtimes spell their null differently
    # and comparing the SPELLING here would hide whether the values agree. Where Python's
    # spelling of `None` is what lands on disk, `pyText` reproduces it — see the index line.
    return {
        "name": None if fact.name is None else b64(str(fact.name)),
        "description": None if fact.description is None else b64(str(fact.description)),
        "type": None if fact.type is None else b64(str(fact.type)),
        "body": b64(fact.body),
        "links": [b64(str(link)) for link in fact.links],
        "last_recalled": None if fact.last_recalled is None else b64(str(fact.last_recalled)),
        "created": None if fact.created is None else b64(str(fact.created)),
    }


def error_json(e: BaseException) -> dict:
    """Type name and message. Both reach the model through `component.Memory`."""
    return {"error": {"type": type(e).__name__, "message": b64(str(e))}}


def run_calls(request: dict) -> dict:
    results = []
    kwargs = {}
    if request.get("index_budget") is not None:
        kwargs["index_budget"] = request["index_budget"]
    if request.get("k") is not None:
        kwargs["k"] = request["k"]
    today = request["today"]
    try:
        store = MemoryStore(
            request["root"], today=lambda: today, create=request.get("create", True), **kwargs
        )
    except BaseException as e:  # noqa: BLE001 — the constructor's failure is a result too
        return {"results": [error_json(e)]}

    for call in request["calls"]:
        op = call["op"]
        try:
            if op == "save":
                type_, name, description, body, links = call["args"]
                r = store.save(
                    unb64(type_), unb64(name), unb64(description), unb64(body),
                    tuple(unb64(x) for x in links),
                )
                # `similar` is the OTHER fact's `name` field verbatim, and `_facts` puts
                # whatever the YAML resolved to in there — an `int` for `name: 7`. `str()`
                # for the same reason `fact_json` uses it.
                results.append({"status": r.status, "name": b64(r.name),
                                "similar": None if r.similar is None else b64(str(r.similar))})
            elif op == "recall":
                query, k, stamp = call["args"]
                hits = store.recall(unb64(query), k, stamp)
                results.append([fact_json(f) for f in hits])
            elif op == "index_text":
                results.append({"index_text": b64(store.index_text())})
            else:
                raise ValueError(f"unknown call op {op!r}")
        except BaseException as e:  # noqa: BLE001 — every failure is part of the comparison
            results.append(error_json(e))
    return {"results": results}


def main() -> None:
    request = json.load(sys.stdin)
    op = request["op"]
    if op == "run":
        out = run_calls(request)
    elif op == "strerror":
        out = {
            "strerror": {
                name: os.strerror(getattr(errno_mod, name))
                for name in request["names"]
                if hasattr(errno_mod, name)
            },
            "missing": [n for n in request["names"] if not hasattr(errno_mod, n)],
        }
    elif op == "decode":
        decoded = []
        for seq in request["seqs"]:
            raw = bytes(seq)
            try:
                # The TEXT, not just ok/not-ok: `TextDecoder` defaults to eating a leading
                # UTF-8 BOM and CPython's codec keeps it, and an ok/not-ok comparison cannot
                # see the difference.
                decoded.append({"ok": True, "text": b64(raw.decode("utf-8"))})
            except UnicodeDecodeError as e:
                decoded.append({"ok": False, "message": str(e)})
        out = {"decoded": decoded}
    elif op == "oserror":
        # `str(OSError)` and pathlib's symlink-loop `RuntimeError`, both of which use `%r`
        # for the path. Real syscalls on real paths, because the point is the path a failing
        # call actually reports and not one hand-assembled here.
        messages = []
        for kind, a, b in request["cases"]:
            a, b = unb64(a), unb64(b)
            try:
                if kind == "unlink":
                    os.unlink(a)
                elif kind == "replace":
                    os.replace(a, b)
                elif kind == "mkdir":
                    os.mkdir(a)
                elif kind == "read":
                    Path(a).read_text(encoding="utf-8")
                elif kind == "resolve":
                    Path(a).resolve()
                else:
                    raise SystemExit(f"unknown oserror kind {kind!r}")
                messages.append({"ok": True})
            except (OSError, RuntimeError) as e:
                messages.append({"type": type(e).__name__, "message": b64(str(e))})
        out = {"messages": messages}
    elif op == "sortnames":
        # `recall`'s tie-break, isolated. Each list is [[score, "<yaml scalar text>"], ...];
        # both runtimes CONSTRUCT the name from the same frontmatter spelling, so what is
        # compared is `sorted(key=(-score, name))` itself — the order when it succeeds and
        # the TypeError text when it does not.
        out = {"lists": []}
        for spec in request["lists"]:
            pairs = [(score, yaml.safe_load("k: " + text)["k"]) for score, text in spec]
            try:
                order = sorted(range(len(pairs)), key=lambda i: (-pairs[i][0], pairs[i][1]))
                out["lists"].append({"order": order})
            except TypeError as e:
                out["lists"].append({"error": str(e)})
    elif op == "jaccard":
        out = {"jaccard": [_jaccard(set(a), set(b)) for a, b in request["pairs"]]}
    elif op == "tokens":
        out = {"tokens": [sorted(_tokens(unb64(t))) for t in request["texts_b64"]]}
    elif op == "sortpaths":
        base = Path(request["dir"])
        out = {"sorted": [b64(p.name) for p in sorted(base / unb64(n) for n in request["names"])]}
    elif op == "paths":
        out = {
            "joined": [b64(str(PurePath(*[unb64(p) for p in parts]))) for parts in request["joins"]],
            "suffixed": [
                b64(str(PurePath(unb64(p)).with_suffix(unb64(s)))) for p, s in request["suffixes"]
            ],
        }
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
