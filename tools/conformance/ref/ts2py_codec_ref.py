"""Python arms of the ts2py-codec suite: runtime-py as it ships, as it was, and the GENERATED codec.

    {"generated": <dir holding the package>, "package": <name>,
     "files": [path, ...], "facts": [fact, ...]}
      -> {"py":     {"files": [{"parse": ..., "rt": ...}], "facts": [format]},
          "before": {"files": [{"parse": ..., "rt": ...}], "facts": [format]},
          "gen":    {"files": [{"parse": ..., "rt": ...}], "facts": [format]}}

`py` is runtime-py as it ships: since #315 (J86-3) the store reads and writes through the
generated codec first and PyYAML where it refuses (`memory/factcodec.py`). `before` is the same
store with both names pointed at the PyYAML fallbacks (`pyyaml_only`), which is runtime-py as it
was before the switch.

THE RUNTIME-PY ARM CALLS THE STORE, IT DOES NOT COPY IT. `load_frontmatter` is the function
`MemoryStore._read_fact` parses a frontmatter with, `_read_fact` is the read a recall stamp
starts from, and `_fact_text` is the serialiser `_write_fact` writes. Neither method reads
`self` (measured: both bodies hold no `self.`), so they are called unbound with `None` for
`self`; if one ever starts reading the instance, this arm raises AttributeError and the suite
goes red naming it, rather than drifting. The only lines here that restate the store are the
three that open `_read_fact` and have no function of their own: `read_text`, the
`split("---\\n", 2)` unpack and `body.strip()`.

THE GENERATED ARM imports the package ts2py wrote into this run's scratch a moment ago, by
path, so no stale copy on `sys.path` can answer for it.

What each answer is:

  parse   {"meta": [[key, value], ...], "body": str} or {"error": "<Name>: <message>"}
  rt      the text a read-then-write leaves (runtime-py: `_fact_text(_read_fact(path))`;
          generated: `format_fact(parse_fact_text(decode_fact_bytes(bytes)))`), or
          {"error": ...}
  format  `_fact_text(Fact(...))` / `format_fact({...})` of a fact built from the request

A value is canonical so the two languages can be compared as JSON: a `str` is itself, `None`
is null, a list is a list, a mapping is `{"map": [[key, value], ...]}`, and every other scalar
is `{"t": type name, "s": str(), "y": safe_dump's plain spelling, "b": bool()}` -- the four
things the store can observe about a `PyScalar` (`pyyaml.ts`). A Python key that is not a
`str` (`on:` is `True`) is `{"key": <canonical>}`.

A typed value in a fact travels as `{"plain": "<yaml text>"}`: runtime-py resolves it with
`yaml.safe_load` (that is how a store comes to hold an `int` in a `str` field), the generated
codec with its own `construct_plain`, Node with `constructPlain`.
"""

from __future__ import annotations

import datetime
import importlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory import factcodec
from bantamkit.memory import store as store_module
from bantamkit.memory.store import Fact, MemoryStore


def _err(exc: BaseException) -> dict:
    # A generated `_JsError` carries the JS `name` (`Error`, `TypeError`) as an attribute; a
    # Python exception has only its class name.
    name = getattr(exc, "name", None)
    if not isinstance(name, str):
        name = type(exc).__name__
    return {"error": f"{name}: {exc}"}


def _plain_yaml(value) -> str:
    text = yaml.safe_dump({"k": value}, allow_unicode=True, width=10**9)
    assert text.startswith("k: ") and text.endswith("\n"), text
    return text[3:-1]


def canon_py(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list):
        return [canon_py(v) for v in value]
    if isinstance(value, dict):
        return {"map": [[_py_key(k), canon_py(v)] for k, v in value.items()]}
    if isinstance(value, (bool, int, float, datetime.date)):
        # The type's name as CPython spells it in `'<name>' object is not iterable`, which is
        # what `PyScalar.pyType` carries: `int`, but `datetime.date`.
        kind = type(value)
        name = (
            kind.__qualname__
            if kind.__module__ == "builtins"
            else f"{kind.__module__}.{kind.__qualname__}"
        )
        return {"t": name, "s": str(value), "y": _plain_yaml(value), "b": bool(value)}
    raise TypeError(f"no canonical form for {type(value).__name__}")


def canon_gen(value, scalar_type):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list):
        return [canon_gen(v, scalar_type) for v in value]
    if isinstance(value, scalar_type):
        return {"t": value.pyType, "s": value.text, "y": value.yaml, "b": value.truthy}
    if isinstance(value, dict):
        return {"map": [[k, canon_gen(v, scalar_type)] for k, v in value.items()]}
    raise TypeError(f"no canonical form for generated {type(value).__name__}")


# ------------------------------------------------------------------------------ runtime-py


def py_parse(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
        _, front, body = text.split("---\n", 2)
        meta = store_module.load_frontmatter(front)
        if not isinstance(meta, dict):
            return {"error": "frontmatter is not a mapping"}
        return {"meta": [[_py_key(k), canon_py(v)] for k, v in meta.items()], "body": body.strip()}
    except Exception as exc:  # noqa: BLE001 - the refusal IS the answer under test
        return _err(exc)


def _py_key(k):
    return k if isinstance(k, str) else {"key": canon_py(k)}


def py_rt(path: Path):
    try:
        # J89-4b: `_read_fact` is the generated store's `readFact`, a method of an instance (the
        # hand-written one never read `self`); a reader that never creates anything.
        reader = MemoryStore(path.parent, create=False)
        return reader._fact_text(reader._read_fact(path, None))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def _py_value(v):
    if isinstance(v, dict) and "plain" in v:
        return yaml.safe_load(v["plain"])
    if isinstance(v, list):
        return [_py_value(x) for x in v]
    return v


def py_format(fact: dict):
    try:
        built = Fact(
            name=_py_value(fact["name"]),
            description=_py_value(fact["description"]),
            type=_py_value(fact["type"]),
            body=fact["body"],
            links=_py_value(fact["links"]),
            last_recalled=_py_value(fact["last_recalled"]),
            created=_py_value(fact["created"]),
            outcome=_py_value(fact.get("outcome")),
            status=_py_value(fact.get("status")),
            keywords=list(fact.get("keywords") or []),
            extra={k: _py_value(v) for k, v in fact.get("extra", [])},
        )
        return MemoryStore._fact_text(None, built)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ------------------------------------------------------------------------------- generated


def gen_arms(gen_dir: str, package: str):
    sys.path.insert(0, gen_dir)
    factfile = importlib.import_module(f"{package}.factfile")
    pyyaml = importlib.import_module(f"{package}.pyyaml")
    scalar = pyyaml.PyScalar

    def parse(data: bytes) -> dict:
        try:
            parsed = factfile.parse_fact_text(factfile.decode_fact_bytes(data))
            return {
                "meta": [[k, canon_gen(v, scalar)] for k, v in parsed["meta"].items()],
                "body": parsed["body"],
            }
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    def rt(data: bytes):
        try:
            return factfile.format_fact(factfile.parse_fact_text(factfile.decode_fact_bytes(data)))
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    def value(v):
        if isinstance(v, dict) and "plain" in v:
            return pyyaml.construct_plain(v["plain"])
        if isinstance(v, list):
            return [value(x) for x in v]
        return v

    def fmt(fact: dict):
        try:
            built = {k: value(v) for k, v in fact.items() if k not in ("extra", "body")}
            built["body"] = fact["body"]
            if "extra" in fact:
                built["extra"] = [[k, value(v)] for k, v in fact["extra"]]
            return factfile.format_fact(built)
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    return parse, rt, fmt


# ------------------------------------------------------------------- runtime-py before #315


@contextmanager
def pyyaml_only():
    """runtime-py as it was before #315 (J86-3): every fact file read and written by PyYAML.

    The store reads through `store.load_frontmatter` and writes through `store.fact_text`, both
    from `memory/factcodec.py`, whose PyYAML fallbacks ARE the pre-#315 code. Pointing the two
    names at the fallbacks gives the old store exactly, so the `before` arm answers what
    runtime-py answered before the switch, and the suite can hold the switch to the user's
    ruling: nothing moved but the two classes it names.
    """
    # J89-4b: the generated store reaches the codec through `factcodec.held_frontmatter` /
    # `held_fact_text`, which call factcodec's own `load_frontmatter` / `fact_text`; both modules'
    # names are pointed at the fallbacks.
    saved = store_module.load_frontmatter, store_module.fact_text
    saved_codec = factcodec.load_frontmatter, factcodec.fact_text
    store_module.load_frontmatter = factcodec.load_frontmatter = factcodec._pyyaml_load
    store_module.fact_text = factcodec.fact_text = factcodec._pyyaml_fact_text
    try:
        yield
    finally:
        store_module.load_frontmatter, store_module.fact_text = saved
        factcodec.load_frontmatter, factcodec.fact_text = saved_codec


def py_arm(files, facts):
    return {
        "files": [{"parse": py_parse(p), "rt": py_rt(p)} for p in files],
        "facts": [py_format(f) for f in facts],
    }


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    gen_parse, gen_rt, gen_format = gen_arms(request["generated"], request["package"])
    files = [Path(p) for p in request["files"]]
    with pyyaml_only():
        before = py_arm(files, request["facts"])
    out = {
        "py": py_arm(files, request["facts"]),
        "before": before,
        "gen": {
            "files": [
                {"parse": gen_parse(p.read_bytes()), "rt": gen_rt(p.read_bytes())} for p in files
            ],
            "facts": [gen_format(f) for f in request["facts"]],
        },
    }
    # ASCII envelope: lone surrogates and every non-ASCII character travel as \u escapes.
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
