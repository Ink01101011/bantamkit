"""Python arms of the ts2py conformance suite: the GENERATED planner and `bantamkit.workplan`.

    {"fixture": str, "generated": str} -> {"generated": [answer], "legacy": [answer]}
    {"lower": {"runtime": str, "inputs": [str]}} -> {"lower": [answer]}   (J89-7)
    {"sort": {"runtime": str, "arrays": [[number | "NaN"]]}} -> {"sort": [answer]}   (J90-P2)
    {"adapters": {"classes": [str], "scratch": str}} -> {"adapters": {...}}   (J90-P5)

`fixture` is `tools/conformance/fixtures/workplan-cases.json`, read HERE with `json.load` and
never handed over as a payload: the payload travels through `JSON.stringify`, which would turn
the file's `3.0` into `3` and `-0.0` into `0` before Python ever saw them, and those are exactly
the values whose Python type is under test. `generated` is the module ts2py wrote into the
run's scratch a moment ago, imported by path so no stale copy on `sys.path` can answer for it.

Each answer is the planner's result as compact JSON text with non-ASCII kept, which is the
spelling `JSON.stringify` gives on the Node side, so key order is compared too. A planner that
raises answers `RAISED <type>: <message>` instead, so a crash is one red case that names itself.

The legacy arm imports `bantamkit.workplan` from this checkout's `runtime-py/src`, whatever
serves that name: the hand-written planner today, the generated one once #314 switches.

`lower` (J89-7) imports the ts2py runtime at `runtime` by path and answers `_js_m_toLowerCase` of
each input, or `RAISED <type>: <message>` where it refuses.

`sort` (J90-P2) imports the runtime the same way and sorts each array (`"NaN"` is NaN) with
`_js_m_sort` under each comparator of `_COMPARATORS`, the Python spelling of the suite's
JavaScript one: per array, `String()` of every item of each answer joined by `,`, then the calls
the first comparator was made, each `a<b`.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import workplan as legacy


def _load(path: str):
    spec = importlib.util.spec_from_file_location("ts2py_generated_workplan", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import the generated module at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _answer(module, nodes) -> str:
    try:
        result = module.plan(copy.deepcopy(nodes))
    except Exception as exc:  # noqa: BLE001 - the crash IS the answer under test
        return f"RAISED {type(exc).__name__}: {exc}"
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _lower(runtime, text: str) -> str:
    try:
        return runtime._js_m_toLowerCase(text)
    except Exception as exc:  # noqa: BLE001 - the refusal IS the answer under test
        return f"RAISED {type(exc).__name__}: {exc}"


def _comparators(rt):
    # Each the JavaScript comparator of the same index in `suites/ts2py.mjs` (`SORTS`).
    num, mod, add, mul = rt._js_num, rt._js_mod, rt._js_add, rt._js_mul
    return [
        lambda a, b, *_: num(num(a) - num(b)),
        lambda a, b, *_: num(num(b) - num(a)),
        lambda a, b, *_: 1 if rt._js_gt(a, b) else 0,
        lambda a, b, *_: num(mod(add(mul(a, 7), mul(b, 3)), 5) - 2),
    ]


def _sort(rt, items) -> list[str]:
    items = [float("nan") if x == "NaN" else x for x in items]
    out = []
    calls = []

    def logged(a, b, *_):
        calls.append(rt._js_str(a) + "<" + rt._js_str(b))
        return rt._js_num(rt._js_num(a) - rt._js_num(b))

    for compare in [logged, *_comparators(rt)[1:]]:
        try:
            got = rt._js_m_sort(list(items), compare)
            out.append(",".join(rt._js_str(x) for x in got))
        except Exception as exc:  # noqa: BLE001 - the crash IS the answer under test
            out.append(f"RAISED {type(exc).__name__}: {exc}")
    out.append(" ".join(calls))
    return out


def _dicts_in(value, out):
    # Every plain dict reachable from an adapter's answer (through lists, dicts and `_JsMap`s).
    from bantamkit._generated._ts2py_runtime import _JsMap

    work = [value]
    while work:
        item = work.pop()
        if isinstance(item, dict):
            out.append(item)
            work.extend(item.values())
        elif isinstance(item, list):
            work.extend(item)
        elif isinstance(item, _JsMap):
            work.extend(item._entries.values())
    return out


def _adapters(request) -> dict:
    """J90-P5: what each adapter object REALLY provides. A class: its `_js_own` (the members
    `_js_object_get` answers; anything else is `undefined`). A dict producer: every dict it built
    over sample inputs that reach each of its shapes, as `{key: str literal or null}` so the Node
    side can match a discriminant (`kind`, `t`)."""
    import types

    from bantamkit._generated import _ts2py_adapters as adapters
    from bantamkit.memory import component

    classes = {name: sorted(getattr(adapters, name)._js_own) for name in request["classes"]}
    fact = Path(request["scratch"]) / "native_fact.md"
    fact.parent.mkdir(parents=True, exist_ok=True)
    fact.write_text(
        "---\nname: a-fact\ndescription: a fact\ntype: project\nlinks: [b]\n---\nbody\n",
        encoding="utf-8",
    )
    samples = {
        "parse_native": [adapters.parse_native(str(fact))],
        "py_relative_scan": [adapters.py_relative_scan("met 3 days ago and yesterday, then")],
        "parse_config_document": [
            adapters.parse_config_document(text) for text in ("", "- 1\n", "a: [x, 1]\nb: 2\n")
        ],
        "parse_json": [adapters.parse_json('{"a": [1, 1.5, "s", true, null, {}]}')],
        "file_links": [adapters.file_links(str(fact), [])],
        "component._context_in": [
            component._context_in(
                types.SimpleNamespace(weights={}, strong_window=["p"], graph=None)
            )
        ],
    }
    dicts = {
        name: [
            {k: (v if isinstance(v, str) else None) for k, v in d.items()}
            for answer in answers
            for d in _dicts_in(answer, [])
        ]
        for name, answers in samples.items()
    }
    return {"classes": classes, "dicts": dicts}


def main() -> None:
    request = json.load(sys.stdin)
    if "adapters" in request:
        sys.stdout.write(json.dumps({"adapters": _adapters(request["adapters"])}))
        return
    if "sort" in request:
        runtime = _load(request["sort"]["runtime"])
        sys.stdout.write(json.dumps({"sort": [_sort(runtime, a) for a in request["sort"]["arrays"]]}))
        return
    if "lower" in request:
        runtime = _load(request["lower"]["runtime"])
        sys.stdout.write(
            json.dumps({"lower": [_lower(runtime, t) for t in request["lower"]["inputs"]]})
        )
        return
    with open(request["fixture"], encoding="utf-8") as handle:
        cases = json.load(handle)
    generated = _load(request["generated"])
    out = {
        "generated": [_answer(generated, case["input"]) for case in cases],
        "legacy": [_answer(legacy, case["input"]) for case in cases],
    }
    # ASCII envelope: the answers inside keep their non-ASCII, and stdout's encoding cannot
    # mangle what it never sees.
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
