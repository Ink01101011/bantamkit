"""Layer 4 (Policy/Profile): the price table, and the arithmetic that turns tokens into money.

WHY THIS EXISTS. `docs/roadmap-agent-stack.md` AS-1 measured it: bantamkit has counted tokens
since `tools/ledger/token-ledger.mjs` shipped and has never once converted one into money.
`grep -rniE 'usd|price|cost_per|per_million' runtime-py/src tools/ledger` finds no currency
anywhere -- only `evalrun`'s fixture tool named `price_lookup` and the English word *price*
used metaphorically in prose.

WHY IT SHIPS WITH NO RATES, AND WHY THAT IS THE FINISHED THING RATHER THAN HALF OF IT.
This toolbox is offline by standing property, and nothing in the repository or on the machine
this was built on carries a published rate -- probed, not assumed: `per_million|perMillion|
MTok|per million token` over the whole checkout and over `~/.claude/plugins` returns nothing
that is a rate. So any number written into `assets/pricing/default.json` here would have been
*recalled by a language model*, and a recalled price printed as money is exactly the
unfalsifiable figure this program refuses -- worse than most, because money reads as
authoritative. The table therefore ships empty, an operator supplies rates as THEIR fact with
THEIR date, and the refusal below is the DEFAULT answer rather than an edge case.

THE THREE PROPERTIES THIS FILE HOLDS, each named where it lives.

1. TOKEN CLASSES ARE PRICED SEPARATELY. `token-ledger.mjs` accumulates `input_tokens`,
   `cache_creation_input_tokens`, `cache_read_input_tokens` and `output_tokens` off the host's
   own `usage` blocks, deduped by `requestId`, and the ledger's whole point is that these are
   not the same token: `docs/ledger.md`'s first run measured 98.1 % of every prompt as
   cache_read. A table with one rate per model would average that away and be wrong in the
   direction of the cache -- which is the direction that matters here. So `TOKEN_CLASSES` is
   the unit of pricing everywhere: a rate is a per-class map, the answer carries a per-class
   `breakdown`, and there is no scalar rate anywhere in this module to average with.

2. A RATE IS A FACT WITH A DATE. `_rate` refuses at LOAD time any entry without `recorded`
   and `source` -- it is not possible to put a number in this table without saying when it was
   read and where from. And a computed cost carries the rate it used, verbatim, under `rate`,
   so the arithmetic is re-derivable from the answer alone.

3. A MODEL WITH NO RATE IS REFUSED, NEVER ZEROED. Same discipline as `build_identity`'s
   `{"unavailable": "<reason>"}` (`mcpserver._unavailable`): a missing fact is named, never
   substituted. `$0.00` for an unpriced model is the worst possible output, so there is no code
   path that produces one. The single exception is stated and is not a substitution: a class
   with ZERO tokens contributes zero whatever the rate is, so an unpriced class is only fatal
   when tokens were actually spent on it.

MONEY IS AN INTEGER, NEVER A FLOAT. Every figure here is micro-USD (1e-6 USD) as a Python
`int`, and rates are micro-USD per 1,000,000 tokens. Nothing is ever a float and nothing is
ever formatted by a locale: `format_micros` builds the decimal string out of integer division
and a zero-pad. This is deliberate and it is the arm most likely to have diverged -- a float
that prints `0.30000000000000004` on one side and `0.3` on the other is a real divergence found
late, and `repomap`'s J45-7 already lost time to `json.dumps(0.0)` != `JSON.stringify(0)`.
Cents were rejected because they cannot hold the answer: 1,234 tokens at $3/M is $0.003702,
which rounds to zero cents.

Rounding is HALF-UP on non-negative integers -- `(n * rate + 500000) // 1000000` -- and not
either language's `round`, because Python's is banker's rounding and JavaScript's
`Math.round` is half-toward-positive-infinity, so on `0.5` they disagree by one micro-USD.
The breakdown is rounded per class and the total is the SUM OF THE ROUNDED PARTS, so the
printed parts always add up to the printed total.

2**53-1 IS THE CEILING, ON BOTH SIDES, BY THE SAME SENTENCE. The port cannot hold a larger
integer exactly, and `assets/tools/bantamkit_read.json` already uses this bound for `offset`
for the same reason. Rather than let Python silently answer where Node cannot, both refuse.

`runtime-ts/src/pricing.ts` is the port, arm for arm, and
`tools/conformance/suites/pricing.mjs` is the gate that compares them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bantamkit.assets import assets_root
from bantamkit.client import BantamError

PRICES_ENV = "BANTAMKIT_PRICES"
PRICE_SCHEMA_VERSION = 1
CURRENCY = "USD"
RATE_UNIT = "micro_usd_per_million_tokens"

#: A rate is micro-USD per this many tokens.
TOKENS_PER_RATE_UNIT = 1_000_000

#: Micro-USD in one USD. Also the rounding divisor, hence `_HALF` below.
MICROS_PER_UNIT = 1_000_000
_HALF = MICROS_PER_UNIT // 2

#: The largest integer both runtimes represent exactly.
MAX_SAFE_INT = 2**53 - 1

#: The four classes the host's own `usage` block distinguishes, in the order the ledger
#: accumulates them. This tuple is the unit of pricing; see property 1 in the module docstring.
TOKEN_CLASSES = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
_CLASSES = ", ".join(TOKEN_CLASSES)

_TABLE_KEYS = ("schema_version", "currency", "unit", "note", "rates")
_RATE_META = ("recorded", "source")


class PriceTableError(BantamError):
    """The table on disk is malformed.

    This RAISES rather than returning `{"unavailable": ...}`, and the split is deliberate: a
    broken price table is an operator configuration fault that must stop and name itself,
    while an unpriced model is a normal, expected answer that a caller keeps working past.
    """


def _is_count(value: object) -> bool:
    """A non-negative integer both runtimes hold exactly, however JSON spelled it.

    TWO HOLES ARE CLOSED HERE AND EACH IS A MEASURED DIVERGENCE CLASS, NOT A HYPOTHETICAL.

    `bool`: `True == 1` and `isinstance(True, int)` are both true in Python, so JSON `true`
    would be accepted as the rate 1. Node has no such hole -- a JSON boolean is a boolean
    there -- so without the exclusion the two runtimes disagree about one malformed table.

    `float`: `json.loads('3000000.0')` is a `float` here and `3000000` -- indistinguishable
    from the integer -- in `JSON.parse`. A Python-side "must be an int" rule would therefore
    refuse a document the port accepts, over a spelling. So an INTEGRAL float is accepted and
    `_as_count` narrows it, which makes the two sides agree on both the verdict and the value
    that is later echoed back under `rate`.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= MAX_SAFE_INT
    if isinstance(value, float):
        return value.is_integer() and 0 <= value <= MAX_SAFE_INT
    return False


def _as_count(value: object) -> int:
    """The `int` behind an accepted count. Only ever called after `_is_count`."""
    return int(value)  # type: ignore[arg-type]


def _sorted_by_code_point(names) -> list[str]:
    """Sorted by code point, so "which key is named first" is not a function of dict order.

    JSON object order survives `json.loads` here but NOT `JSON.parse` in the port, where
    integer-like keys are reordered ahead of the rest. Naming the code-point-least offender
    makes the two answer the same sentence for the same file.
    """
    return sorted(names)


def _is_date(value: object) -> bool:
    """`YYYY-MM-DD`, shape and range only -- deliberately not a calendar.

    A real calendar check would be `datetime.date`, which the port has no equivalent of
    without writing a third leap-year rule. Shape plus 1<=month<=12 and 1<=day<=31 is what
    both sides can hold identically; 2026-02-31 passes and that is a known, stated limit.
    """
    if not isinstance(value, str) or len(value) != 10:
        return False
    if value[4] != "-" or value[7] != "-":
        return False
    for part in (value[0:4], value[5:7], value[8:10]):
        for ch in part:
            if ch < "0" or ch > "9":
                return False
    month = int(value[5:7])
    day = int(value[8:10])
    return 1 <= month <= 12 and 1 <= day <= 31


def _reject_constant(name: str) -> float:
    raise ValueError(name)


def decode_price_json(text: str) -> object:
    """The decode both runtimes must agree on, in one place so the gate can reach it.

    `parse_constant` closes CPython's non-standard extension: `json.loads` accepts the bare
    tokens `NaN`, `Infinity` and `-Infinity` and `JSON.parse` rejects them. Left alone, a
    table carrying one of the three is "not valid JSON" in the port and a DIFFERENT sentence
    here -- a divergence over a document neither side wants. Raises `ValueError`
    (`json.JSONDecodeError` is one) exactly when `JSON.parse` throws.
    """
    return json.loads(text, parse_constant=_reject_constant)


def price_table_path() -> str:
    """`$BANTAMKIT_PRICES` verbatim if set, else the shipped table in the asset pack.

    The override wins even when it is wrong -- same arm order and same reasoning as
    `assets.assets_root()`: an override that points nowhere must fail naming itself rather
    than fall through to a table the operator did not ask for.
    """
    env = os.environ.get(PRICES_ENV)
    if env:
        return env
    return str(assets_root() / "pricing" / "default.json")


def load_price_table(path: str | None = None) -> dict:
    """Read and validate a price table. `path` is used VERBATIM in every message it appears in.

    Not normalised, because `Path("./x")` is `x` here and `./x` in the port, and the fault
    sentence would then differ over a path neither runtime chose.
    """
    label = price_table_path() if path is None else str(path)
    file = Path(label)
    if not file.exists():
        raise PriceTableError(f"price table not found: {label}")
    try:
        raw = decode_price_json(file.read_text(encoding="utf-8"))
    except ValueError:
        # The decoder's own text is NOT quoted. `validate.mjs` covers the two decoders'
        # sentences separately and they are not identical everywhere; quoting one here would
        # make every malformed table a divergence, over bytes that name the same fault.
        raise PriceTableError(f"price table is not valid JSON: {label}") from None
    return validate_price_table(raw)


def validate_price_table(raw: object) -> dict:
    """Every rule the table must satisfy, each with its own sentence.

    Returns a NORMALISED table rather than the input: the top-level keys in a fixed order,
    rate names in code-point order, and every count narrowed to an `int`. The normalisation
    is what makes the table comparable between the runtimes -- `3000000.0` survives as a
    float here and as an integer there, and the file's own key order survives `json.loads`
    but not `JSON.parse`.

    ONE THING IS NOT CLAIMED AND THE CONFORMANCE SUITE CANONICALISES AROUND IT: the ORDER of
    `rates` for a model name JavaScript reads as an array index. `{"10": ..., "9": ...}`
    iterates `10, 9` here (code point) and `9, 10` there (numeric), and no amount of care on
    this side changes it. The CONTENT is identical and the suite compares the rates as a
    code-point-sorted list of pairs for exactly that reason; nothing else in this module keys
    an object by a model name.
    """
    if not isinstance(raw, dict):
        raise PriceTableError("price table must be a JSON object")
    unknown = _sorted_by_code_point(k for k in raw if k not in _TABLE_KEYS)
    if unknown:
        raise PriceTableError(f"price table has unknown key {unknown[0]!r}")
    # No parsed VALUE is ever interpolated into a sentence below -- only key names and
    # integers this module computed. A parsed value would drag the two runtimes' number
    # formatting into the message (JSON `2.0` is `2.0` here and `2` there), which is a
    # serialiser divergence wearing an error message's clothes.
    version = raw.get("schema_version")
    if not _is_count(version) or version != PRICE_SCHEMA_VERSION:
        raise PriceTableError("price table schema_version must be the integer 1")
    if raw.get("currency") != CURRENCY:
        raise PriceTableError("price table currency must be the string 'USD'")
    if raw.get("unit") != RATE_UNIT:
        raise PriceTableError(
            "price table unit must be the string 'micro_usd_per_million_tokens'"
        )
    if "note" in raw and not isinstance(raw["note"], str):
        raise PriceTableError("price table note must be a string")
    rates = raw.get("rates")
    if not isinstance(rates, dict):
        raise PriceTableError("price table rates must be a JSON object")
    out: dict = {
        "schema_version": PRICE_SCHEMA_VERSION,
        "currency": CURRENCY,
        "unit": RATE_UNIT,
    }
    if "note" in raw:
        out["note"] = raw["note"]
    out["rates"] = {
        model: _validate_rate(model, rates[model]) for model in _sorted_by_code_point(rates)
    }
    return out


def _validate_rate(model: str, rate: object) -> dict:
    if not isinstance(rate, dict):
        raise PriceTableError(f"price table rate {model!r} must be a JSON object")
    known = _RATE_META + TOKEN_CLASSES
    unknown = _sorted_by_code_point(k for k in rate if k not in known)
    if unknown:
        raise PriceTableError(f"price table rate {model!r} has unknown key {unknown[0]!r}")
    # Property 2, enforced where it cannot be skipped: at load, before any arithmetic.
    if "recorded" not in rate:
        raise PriceTableError(
            f"price table rate {model!r} is missing 'recorded' -- a rate with no date is not a fact"
        )
    if not _is_date(rate["recorded"]):
        raise PriceTableError(
            f"price table rate {model!r} has a 'recorded' that is not a YYYY-MM-DD date"
        )
    if "source" not in rate:
        raise PriceTableError(
            f"price table rate {model!r} is missing 'source' -- a rate with no source "
            f"cannot be re-derived"
        )
    if not isinstance(rate["source"], str) or rate["source"] == "":
        raise PriceTableError(
            f"price table rate {model!r} has a 'source' that is not a non-empty string"
        )
    for cls in TOKEN_CLASSES:
        if cls in rate and not _is_count(rate[cls]):
            raise PriceTableError(
                f"price table rate {model!r} prices {cls!r} with something that is not a "
                f"non-negative integer below 2**53"
            )
    if not any(cls in rate for cls in TOKEN_CLASSES):
        raise PriceTableError(f"price table rate {model!r} prices no token class at all")
    return _rate_view({**rate, **{c: _as_count(rate[c]) for c in TOKEN_CLASSES if c in rate}})


def _unavailable(reason: str) -> dict:
    """`build_identity`'s shape, on purpose: one key, and the key IS the refusal."""
    return {"unavailable": reason}


def format_micros(micros: int) -> str:
    """Micro-USD as a fixed-6-decimal string, built from integers only.

    Non-negative input only; every producer in this module is a sum of non-negative products.
    """
    return f"{micros // MICROS_PER_UNIT}.{micros % MICROS_PER_UNIT:06d}"


def price_tokens(table: dict, model: str, usage: dict) -> dict:
    """The cost of one `usage` block under one model's rate, or a named refusal.

    `table` must be a table `validate_price_table` returned. Its counts are `int` by then,
    which is what lets the arithmetic below be integer-only.

    THE ORDER OF THE CHECKS IS PART OF THE CONTRACT. The usage is validated BEFORE the model
    is looked up, so a caller who passed a malformed usage is told that, rather than being
    sent to edit a price table over a bug in the call.

    THE USAGE MUST CARRY ALL FOUR CLASSES AND NOTHING ELSE. A real `usage` block also carries
    `service_tier` and friends; the caller names the four fields explicitly rather than
    splatting the block, which is the same rule `assets.load_tool` follows for the same
    reason -- a loader that passes a dict through grows a surface every time the source grows
    a key. Here the stake is higher: a token class silently ignored is money silently
    dropped, and a class silently defaulted to zero is money silently invented.
    """
    if not isinstance(model, str):
        return _unavailable("model must be a string")
    if not isinstance(usage, dict):
        return _unavailable("usage must be a mapping of token class to count")
    extra = _sorted_by_code_point(k for k in usage if k not in TOKEN_CLASSES)
    if extra:
        return _unavailable(
            f"usage has unknown token class {extra[0]!r} -- the price table prices "
            f"exactly {_CLASSES}"
        )
    for cls in TOKEN_CLASSES:
        if cls not in usage:
            return _unavailable(
                f"usage is missing token class {cls!r} -- all four of {_CLASSES} must be "
                f"given, because a missing count is not a zero"
            )
        if not _is_count(usage[cls]):
            return _unavailable(
                f"usage token class {cls!r} is not a non-negative integer below 2**53"
            )

    rate = table.get("rates", {}).get(model)
    if rate is None:
        return _unavailable(
            f"no rate recorded for model {model!r} -- add one with its date and source, or "
            f"point {PRICES_ENV} at a table that has it"
        )

    breakdown: dict[str, int] = {}
    total = 0
    for cls in TOKEN_CLASSES:
        count = _as_count(usage[cls])
        if cls not in rate:
            # Zero tokens cost zero under ANY rate, so this arm invents nothing. Any other
            # count with no rate is property 3 and is refused rather than silently dropped.
            if count != 0:
                return _unavailable(
                    f"rate for model {model!r} does not price {cls!r}, and {count} such "
                    f"tokens were used -- a missing rate is not a zero"
                )
            micros = 0
        else:
            micros = (count * rate[cls] + _HALF) // MICROS_PER_UNIT
        breakdown[cls] = micros
        total += micros

    if total > MAX_SAFE_INT:
        return _unavailable(
            f"cost for model {model!r} exceeds 2**53-1 micro-USD, which is the largest "
            f"integer both runtimes represent exactly"
        )

    return {
        "model": model,
        "currency": CURRENCY,
        "micros": total,
        "amount": format_micros(total),
        "breakdown": breakdown,
        "rate": _rate_view(rate),
    }


def _rate_view(rate: dict) -> dict:
    """The rate that produced a cost, echoed in a fixed key order so the answer is re-derivable.

    Fixed order rather than the file's own order, because the file's order is not stable
    across the two JSON parsers and this dict is compared byte for byte by the conformance
    suite.
    """
    view = {"recorded": rate["recorded"], "source": rate["source"]}
    for cls in TOKEN_CLASSES:
        if cls in rate:
            view[cls] = rate[cls]
    return view
