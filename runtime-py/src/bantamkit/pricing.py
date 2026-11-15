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

**Generated, not hand-written (#316 G1, J87-3).** The arithmetic and every refusal are
`bantamkit/_generated/pricing.py`, compiled from `runtime-ts/src/pricing.ts` by `tools/ts2py`
(`docs/porting.md`, *Generated modules*; do not edit it, regenerate it), so the two runtimes now
run one source and `tools/conformance/suites/pricing.mjs` compares them. This module keeps the
public surface the hand-written one had:

- `TOKEN_CLASSES` is a tuple (the generated module, like the TypeScript, holds a list).
- `PriceTableError` is the generated class; it subclasses `bantamkit.client.BantamError` through
  the `BantamError` adapter, so `except BantamError` still catches it, and `str(exc)` is the
  sentence.
- `load_price_table(path=None)`: `None` (or no argument) is the default path, and any other value
  is used as `str(path)`, so a `pathlib.Path` works as it did.
- `validate_price_table` and `price_tokens` answer Python values lifted as Node's `fromJs` lifts the
  TypeScript's (`_js_py_value`): an integral count is an `int` however JSON spelled it.
- `decode_price_json` is `JSON.parse`: numbers are JS numbers (`3000000.0` reads as the int
  `3000000`, an integer past 2**53 as the double it rounds to), and a malformed text raises a
  `ValueError` whose text is CPython's decoder message, as before.
- A top-level `tuple` handed to `validate_price_table` or as `price_tokens`'s usage is handed over
  as a `list`, so it is refused with the sentence it was refused with before (JS has no tuple; the
  generated code would refuse it as outside the subset). Nested values are passed through.
- A `model` that is no key of the table's `rates` but a name JavaScript finds on `Object.prototype`
  (`toString`, `constructor`, `__proto__`, ...) answers "no rate recorded", as any unknown model
  does, and a table may name a model `__proto__` like any other: `pricing.ts` looks a model up and
  builds the rates by own key only (#316 G1, J87-3F), so the generated code answers this itself.
"""

from __future__ import annotations

from bantamkit._generated import pricing as _generated
from bantamkit._generated._ts2py_runtime import _JS_UNDEFINED, _js_py_value
from bantamkit._generated.pricing import (
    CURRENCY,
    MAX_SAFE_INT,
    MICROS_PER_UNIT,
    PRICE_SCHEMA_VERSION,
    PRICES_ENV,
    RATE_UNIT,
    TOKENS_PER_RATE_UNIT,
    PriceTableError,
    decode_price_json,
    format_micros,
    price_table_path,
)

__all__ = [
    "CURRENCY",
    "MAX_SAFE_INT",
    "MICROS_PER_UNIT",
    "PRICES_ENV",
    "PRICE_SCHEMA_VERSION",
    "RATE_UNIT",
    "TOKENS_PER_RATE_UNIT",
    "TOKEN_CLASSES",
    "PriceTableError",
    "decode_price_json",
    "format_micros",
    "load_price_table",
    "price_table_path",
    "price_tokens",
    "validate_price_table",
]

#: The four classes the host's own `usage` block distinguishes, in the order the ledger
#: accumulates them. This tuple is the unit of pricing; see property 1 in the module docstring.
TOKEN_CLASSES = tuple(_generated.TOKEN_CLASSES)


def load_price_table(path: str | None = None) -> dict:
    """Read and validate a price table. `path` is used VERBATIM in every message it appears in."""
    return _js_py_value(_generated.load_price_table(_JS_UNDEFINED if path is None else str(path)))


def validate_price_table(raw: object) -> dict:
    """Every rule the table must satisfy, each with its own sentence; a NORMALISED table back."""
    raw = list(raw) if isinstance(raw, tuple) else raw
    return _js_py_value(_generated.validate_price_table(raw))


def price_tokens(table: dict, model: str, usage: dict) -> dict:
    """The cost of one `usage` block under one model's rate, or `{"unavailable": <reason>}`."""
    usage = list(usage) if isinstance(usage, tuple) else usage
    return _js_py_value(_generated.price_tokens(table, model, usage))
