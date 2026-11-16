"""Python arms of the ts2py conformance suite: the GENERATED planner and `bantamkit.workplan`.

    {"fixture": str, "generated": str} -> {"generated": [answer], "legacy": [answer]}
    {"lower": {"runtime": str, "inputs": [str]}} -> {"lower": [answer]}   (J89-7)

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


def main() -> None:
    request = json.load(sys.stdin)
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
