"""Reference side of the `pricing` conformance suite — tokens into money.

WHY THIS IMPORTS `bantamkit` RATHER THAN COPYING THE ARITHMETIC. Same trade every other
reference here makes: a hand copy would be a THIRD implementation needing its own review, and
the drift alarm would then be between the copy and the module rather than between the two
runtimes. This runs the real `bantamkit.pricing` against inputs the suite spells, so any edit
to `pricing.py` that moves a byte reddens the port immediately.

EVERY SENTENCE TRAVELS AS BASE64. The refusal and fault strings are the whole product here —
they are what an operator reads when a model has no rate — and a sentence that went through a
JSON string escape on one side and not the other would compare the escapers rather than the
sentences. Same reason `dream_ref.py` and `repomap_ref.py` do it.

EVERY TABLE TRAVELS AS ITS RAW JSON TEXT, never as a decoded object, because the two decoders
are half of what is under test: `json.loads` accepts `NaN`/`Infinity` and `JSON.parse` does
not, and `3000000.0` survives as a float here and as an integer there.

THE NORMALISED TABLE IS EMITTED AS ORDERED PAIRS, not as an object. `JSON.parse` hoists
integer-like keys ahead of the rest and orders them numerically, so a `rates` object keyed by
a model literally named `10` cannot be made to iterate the same on both sides. Emitting
`[[name, [[key, value], ...]], ...]` in code-point order makes the CONTENT comparable and
makes the one thing that is not claimed visible in the wire shape instead of hidden in it.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"op": "validate", "tables": [<b64 of the table's JSON text>, ...]}
      -> {"out": [{"table": <pairs>} | {"error": <b64 sentence>}, ...]}

    {"op": "price", "table": <b64>, "cases": [{"model": <str>, "usage": <b64>}, ...]}
      -> {"out": [<result with every string b64'd>, ...]}

    {"op": "format", "micros": [<int>, ...]} -> {"out": [<b64>, ...]}

    {"op": "load", "paths": [<str>, ...]}
      -> {"out": [{"error": <b64>} | {"table": <pairs>}, ...]}

    {"op": "constants"} -> the pinned names and numbers
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import pricing


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")


def pairs(mapping: dict) -> list:
    """A mapping as `[[key, value], ...]` in the mapping's own order, recursing one level."""
    out = []
    for key, value in mapping.items():
        out.append([key, pairs(value) if isinstance(value, dict) else value])
    return out


def table_pairs(table: dict) -> list:
    out = []
    for key, value in table.items():
        if key == "rates":
            out.append([key, [[model, pairs(rate)] for model, rate in value.items()]])
        elif key == "note":
            out.append([key, b64(value)])
        else:
            out.append([key, value])
    return out


def run_validate(request: dict) -> dict:
    out = []
    for encoded in request["tables"]:
        text = unb64(encoded)
        try:
            raw = pricing.decode_price_json(text)
        except ValueError:
            # `undecodable` is this op's own word, not a runtime sentence: the runtimes'
            # decoders phrase their faults differently by design (`validate.mjs` covers that
            # separately), and what THIS op claims is only that they agree on WHICH
            # documents decode at all. The sentence a caller sees for an undecodable table
            # is the `load` op's business, where the path is part of it.
            out.append({"error": b64("undecodable")})
            continue
        try:
            out.append({"table": table_pairs(pricing.validate_price_table(raw))})
        except pricing.PriceTableError as exc:
            out.append({"error": b64(str(exc))})
    return {"out": out}


def result_view(result: dict) -> dict:
    if "unavailable" in result:
        return {"unavailable": b64(result["unavailable"])}
    return {
        "model": b64(result["model"]),
        "currency": result["currency"],
        "micros": result["micros"],
        "amount": b64(result["amount"]),
        "breakdown": pairs(result["breakdown"]),
        "rate": pairs(result["rate"]),
    }


def run_price(request: dict) -> dict:
    table = pricing.validate_price_table(pricing.decode_price_json(unb64(request["table"])))
    out = []
    for case in request["cases"]:
        usage = pricing.decode_price_json(unb64(case["usage"]))
        out.append(result_view(pricing.price_tokens(table, unb64(case["model"]), usage)))
    return {"out": out}


def run_format(request: dict) -> dict:
    return {"out": [b64(pricing.format_micros(m)) for m in request["micros"]]}


def run_load(request: dict) -> dict:
    out = []
    for path in request["paths"]:
        try:
            out.append({"table": table_pairs(pricing.load_price_table(path))})
        except pricing.PriceTableError as exc:
            out.append({"error": b64(str(exc))})
    return {"out": out}


def run_constants() -> dict:
    return {
        "PRICES_ENV": pricing.PRICES_ENV,
        "PRICE_SCHEMA_VERSION": pricing.PRICE_SCHEMA_VERSION,
        "CURRENCY": pricing.CURRENCY,
        "RATE_UNIT": pricing.RATE_UNIT,
        "TOKENS_PER_RATE_UNIT": pricing.TOKENS_PER_RATE_UNIT,
        "MICROS_PER_UNIT": pricing.MICROS_PER_UNIT,
        "MAX_SAFE_INT": pricing.MAX_SAFE_INT,
        "TOKEN_CLASSES": list(pricing.TOKEN_CLASSES),
    }


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "validate":
        out = run_validate(request)
    elif op == "price":
        out = run_price(request)
    elif op == "format":
        out = run_format(request)
    elif op == "load":
        out = run_load(request)
    elif op == "constants":
        out = run_constants()
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
