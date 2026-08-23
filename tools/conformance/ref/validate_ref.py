"""Reference side of the validator conformance suite.

Same stance as the other three: this IMPORTS `bantamkit.contract` and calls the real
`jsonschema` and the real `json`, rather than restating what they do. The drift alarm is the
differential itself.

Every string that must survive byte-exactly travels as base64, including the SCHEMAS: a
schema is sent as its raw JSON TEXT so that each side runs its own decoder over the same
bytes. Handing over a pre-parsed object would silently erase the int/float distinction that
`{instance!r}` prints, which is one of the things under test.

    {"op": "schema_error", "cases": [{"schema": b64_json_text, "output": b64}]}
        -> {"results": [b64 | {"error": {"type": str, "message": b64}}]}

    {"op": "raw_decode", "texts": [b64]}
        -> {"results": [{"repr": b64, "end": int} | {"error": {"type": str, "message": b64}}]}

    {"op": "extract_json", "texts": [b64]}
        -> {"results": [{"repr": b64} | {"error": {"type": str, "message": b64}}]}

    {"op": "float_repr", "texts": [str]}   # each a Python float literal
        -> {"reprs": [str]}

    {"op": "contract", "name": str}
        -> {"data": {key: b64}} | {"error": {...}}

    {"op": "iter_errors", "cases": [{"schema": b64_json_text, "instance": b64_json_text}]}
        -> {"results": [{"trace": [{"path": [...], "kw": str|None, "msg": b64}],
                         "best": {...}|None}]}
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

import jsonschema
from bantamkit.contract import extract_json, load_contract, schema_error
from jsonschema.exceptions import best_match


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8", "surrogatepass")


def caught(exc: BaseException) -> dict:
    return {"error": {"type": type(exc).__name__, "message": b64(str(exc))}}


def main() -> None:
    # stdin is a byte protocol: decode it as utf-8, not through the ANSI code page.
    # See the note in tools/conformance/ref/codec_ref.py.
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = payload["op"]

    if op == "schema_error":
        results = []
        for case in payload["cases"]:
            schema = json.loads(unb64(case["schema"]))
            try:
                answer = schema_error(unb64(case["output"]), schema)
            except BaseException as e:  # noqa: BLE001 - the escape IS the measurement
                results.append(caught(e))
            else:
                results.append(None if answer is None else b64(answer))
        json.dump({"results": results}, sys.stdout)
        return

    if op == "raw_decode":
        results = []
        for text in payload["texts"]:
            try:
                obj, end = json.JSONDecoder().raw_decode(unb64(text))
            except BaseException as e:  # noqa: BLE001
                results.append(caught(e))
            else:
                results.append({"repr": b64(repr(obj)), "end": end})
        json.dump({"results": results}, sys.stdout)
        return

    if op == "extract_json":
        results = []
        for text in payload["texts"]:
            try:
                obj = extract_json(unb64(text))
            except BaseException as e:  # noqa: BLE001
                results.append(caught(e))
            else:
                results.append({"repr": b64(repr(obj))})
        json.dump({"results": results}, sys.stdout)
        return

    if op == "float_repr":
        json.dump({"reprs": [repr(float(t)) for t in payload["texts"]]}, sys.stdout)
        return

    if op == "contract":
        try:
            data = load_contract(payload["name"])
        except BaseException as e:  # noqa: BLE001
            json.dump(caught(e), sys.stdout)
            return
        json.dump({"data": {k: b64(v) for k, v in data.items()}}, sys.stdout)
        return

    if op == "iter_errors":
        results = []
        for case in payload["cases"]:
            schema = json.loads(unb64(case["schema"]))
            instance = json.loads(unb64(case["instance"]))
            try:
                validator = jsonschema.validators.validator_for(schema)(schema)
                errors = list(validator.iter_errors(instance))
            except BaseException as e:  # noqa: BLE001
                results.append(caught(e))
                continue
            trace = [
                {
                    "path": [str(p) for p in e.absolute_path],
                    "kw": e.validator,
                    "msg": b64(e.message),
                }
                for e in errors
            ]
            chosen = best_match(errors)
            results.append(
                {
                    "trace": trace,
                    "best": None
                    if chosen is None
                    else {
                        "path": [str(p) for p in chosen.absolute_path],
                        "kw": chosen.validator,
                        "msg": b64(chosen.message),
                    },
                },
            )
        json.dump({"results": results}, sys.stdout)
        return

    raise SystemExit(f"unknown op {op!r}")


if __name__ == "__main__":
    main()
