"""The price table: the three properties, the rounding, and the refusal that is the default.

The port half is `runtime-ts/test/pricing.test.mjs` and the live differential between the two
is `tools/conformance/suites/pricing.mjs`. This file is the in-runtime half, so a mutation
that survives the pins is visible without a Node on PATH.

WHAT IS ASSERTED HERE AND NOT THERE: the shipped asset's emptiness, which is a claim about
this repository rather than about agreement, and every number below is a TYPED literal rather
than the other runtime's answer -- a differential between two implementations that were both
changed is green (`feedback/differential-is-blind-to-symmetric-regression`).
"""

from __future__ import annotations

import json

import pytest

from bantamkit.assets import assets_root
from bantamkit.pricing import (
    CURRENCY,
    MAX_SAFE_INT,
    MICROS_PER_UNIT,
    PRICE_SCHEMA_VERSION,
    PRICES_ENV,
    RATE_UNIT,
    TOKEN_CLASSES,
    TOKENS_PER_RATE_UNIT,
    PriceTableError,
    format_micros,
    load_price_table,
    price_table_path,
    price_tokens,
    validate_price_table,
)

HEAD = {
    "schema_version": 1,
    "currency": "USD",
    "unit": "micro_usd_per_million_tokens",
}

# $3.00 / $15.00 per million, spelled in micro-USD. NOT a real price -- a round arithmetic
# bed, and it is a fixture rather than an asset for exactly the reason this whole unit exists.
RATE = {
    "recorded": "2026-09-11",
    "source": "this test file, which is not a price source",
    "input_tokens": 3_000_000,
    "cache_creation_input_tokens": 3_750_000,
    "cache_read_input_tokens": 300_000,
    "output_tokens": 15_000_000,
}


def table(rates: dict) -> dict:
    return validate_price_table({**HEAD, "rates": rates})


def usage(**kwargs: int) -> dict:
    return {cls: kwargs.get(cls, 0) for cls in TOKEN_CLASSES}


# --------------------------------------------------------------------------- the constants


def test_the_four_token_classes_are_the_hosts_own_usage_fields():
    # Typed, not derived. These are the four keys `token-ledger.mjs` reads off the host's
    # `usage` block; a fifth appearing here silently would price something the ledger never
    # counted, and a rename would price nothing at all.
    assert TOKEN_CLASSES == (
        "input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
    )


def test_the_units_are_what_they_say():
    assert PRICES_ENV == "BANTAMKIT_PRICES"
    assert PRICE_SCHEMA_VERSION == 1
    assert CURRENCY == "USD"
    assert RATE_UNIT == "micro_usd_per_million_tokens"
    assert TOKENS_PER_RATE_UNIT == 1_000_000
    assert MICROS_PER_UNIT == 1_000_000
    assert MAX_SAFE_INT == 9_007_199_254_740_991


# ------------------------------------------------------------- the shipped table is empty


def test_the_shipped_table_prices_nothing():
    """The claim this unit is built on, asserted rather than described.

    `assets/pricing/default.json` ships with no rates because nothing in this repository or
    on the machine it was built on carries a published price, and a rate recalled by a
    language model is the unfalsifiable figure this program refuses. This test is what makes
    pasting one in a deliberate, visible act rather than a quiet one.
    """
    shipped = load_price_table(str(assets_root() / "pricing" / "default.json"))
    assert shipped["rates"] == {}
    assert shipped["schema_version"] == 1
    assert shipped["currency"] == "USD"
    assert shipped["unit"] == "micro_usd_per_million_tokens"


def test_the_refusal_is_the_default_answer_with_the_shipped_table():
    shipped = load_price_table(str(assets_root() / "pricing" / "default.json"))
    answer = price_tokens(shipped, "any-model-at-all", usage(input_tokens=1_000_000))
    assert answer == {
        "unavailable": "no rate recorded for model 'any-model-at-all' -- add one with its "
        "date and source, or point BANTAMKIT_PRICES at a table that has it"
    }
    # The shape that matters: there is no cost key to mistake for a real one.
    assert "micros" not in answer
    assert "amount" not in answer


def test_price_table_path_prefers_the_env_var(monkeypatch):
    monkeypatch.setenv(PRICES_ENV, "/nowhere/at/all.json")
    assert price_table_path() == "/nowhere/at/all.json"
    monkeypatch.delenv(PRICES_ENV)
    assert price_table_path().endswith("pricing/default.json")


# ----------------------------------------------------- property 1: classes priced apart


def test_each_token_class_is_priced_by_its_own_rate():
    answer = price_tokens(
        table({"m": RATE}),
        "m",
        usage(
            input_tokens=1_000_000,
            cache_creation_input_tokens=1_000_000,
            cache_read_input_tokens=1_000_000,
            output_tokens=1_000_000,
        ),
    )
    # One million of each, so each class's micro-USD IS its per-million rate. Four DIFFERENT
    # numbers is the assertion: a single averaged rate would make them equal.
    assert answer["breakdown"] == {
        "input_tokens": 3_000_000,
        "cache_creation_input_tokens": 3_750_000,
        "cache_read_input_tokens": 300_000,
        "output_tokens": 15_000_000,
    }
    assert answer["micros"] == 22_050_000
    assert answer["amount"] == "22.050000"


def test_the_breakdown_sums_to_the_total():
    answer = price_tokens(
        table({"m": RATE}),
        "m",
        usage(input_tokens=1_234_567, cache_read_input_tokens=7_654_321, output_tokens=999),
    )
    assert sum(answer["breakdown"].values()) == answer["micros"]


def test_cache_read_is_cheaper_than_fresh_input_at_the_same_count():
    """The whole reason the ledger separates the classes, as an asserted inequality.

    `docs/ledger.md` measured 98.1 % of every prompt as cache_read. A table that priced one
    rate per model would report those tokens at the fresh-input rate and overstate the bill by
    an order of magnitude on this fixture.
    """
    one = usage(input_tokens=1_000_000)
    two = usage(cache_read_input_tokens=1_000_000)
    assert price_tokens(table({"m": RATE}), "m", two)["micros"] < price_tokens(
        table({"m": RATE}), "m", one
    )["micros"]


# ------------------------------------------------------ property 2: a rate has a date


def test_a_rate_without_a_date_is_refused_at_load():
    with pytest.raises(PriceTableError) as exc:
        table({"m": {"source": "s", "input_tokens": 1}})
    assert str(exc.value) == (
        "price table rate 'm' is missing 'recorded' -- a rate with no date is not a fact"
    )


def test_a_rate_without_a_source_is_refused_at_load():
    with pytest.raises(PriceTableError) as exc:
        table({"m": {"recorded": "2026-09-11", "input_tokens": 1}})
    assert str(exc.value) == (
        "price table rate 'm' is missing 'source' -- a rate with no source cannot be re-derived"
    )


@pytest.mark.parametrize(
    "recorded",
    ["11-09-2026", "2026-9-11", "2026-13-01", "2026-09-00", "2026-09-1x", "", "20260911"],
)
def test_a_recorded_that_is_not_a_date_is_refused(recorded):
    with pytest.raises(PriceTableError) as exc:
        table({"m": {"recorded": recorded, "source": "s", "input_tokens": 1}})
    assert str(exc.value) == (
        "price table rate 'm' has a 'recorded' that is not a YYYY-MM-DD date"
    )


def test_the_date_check_is_shape_and_range_only_which_is_a_stated_limit():
    # 2026-02-31 is not a day. It passes, and the module says so: a real calendar would be
    # `datetime.date` here and a third leap-year rule in the port.
    assert table({"m": {"recorded": "2026-02-31", "source": "s", "input_tokens": 1}})


def test_the_rate_that_produced_a_cost_travels_with_it():
    answer = price_tokens(table({"m": RATE}), "m", usage(input_tokens=1_000_000))
    assert answer["rate"] == RATE
    # Re-derivable from the answer alone: count x rate / 1e6, no other input needed.
    assert answer["breakdown"]["input_tokens"] == (
        1_000_000 * answer["rate"]["input_tokens"] // MICROS_PER_UNIT
    )


# ---------------------------------------------- property 3: a missing rate is not a zero


def test_an_unpriced_model_refuses_rather_than_costing_nothing():
    answer = price_tokens(table({"m": RATE}), "other", usage(input_tokens=1_000_000))
    assert answer == {
        "unavailable": "no rate recorded for model 'other' -- add one with its date and "
        "source, or point BANTAMKIT_PRICES at a table that has it"
    }


def test_a_class_with_tokens_and_no_rate_refuses():
    partial = table({"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": 3_000_000}})
    answer = price_tokens(partial, "m", usage(input_tokens=10, cache_read_input_tokens=5))
    assert answer == {
        "unavailable": "rate for model 'm' does not price 'cache_read_input_tokens', and 5 "
        "such tokens were used -- a missing rate is not a zero"
    }


def test_a_class_with_no_rate_and_no_tokens_is_not_a_refusal():
    """The one arm that answers zero, and it invents nothing: zero tokens cost zero under
    any rate whatsoever, so nothing has been substituted for a missing fact."""
    partial = table({"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": 3_000_000}})
    answer = price_tokens(partial, "m", usage(input_tokens=1_000_000))
    assert answer["micros"] == 3_000_000
    assert answer["breakdown"]["cache_read_input_tokens"] == 0


def test_a_usage_missing_a_class_refuses_rather_than_defaulting_it():
    answer = price_tokens(table({"m": RATE}), "m", {"input_tokens": 1})
    assert answer == {
        "unavailable": "usage is missing token class 'cache_creation_input_tokens' -- all "
        "four of input_tokens, cache_creation_input_tokens, cache_read_input_tokens, "
        "output_tokens must be given, because a missing count is not a zero"
    }


def test_a_usage_with_an_extra_key_refuses_rather_than_ignoring_it():
    answer = price_tokens(table({"m": RATE}), "m", {**usage(input_tokens=1), "service_tier": 0})
    assert answer == {
        "unavailable": "usage has unknown token class 'service_tier' -- the price table "
        "prices exactly input_tokens, cache_creation_input_tokens, "
        "cache_read_input_tokens, output_tokens"
    }


def test_the_usage_is_checked_before_the_model_is_looked_up():
    """Both wrong at once, and the caller is told about their call rather than their table."""
    answer = price_tokens(table({"m": RATE}), "not-a-model", {"input_tokens": 1})
    assert "usage is missing token class" in answer["unavailable"]


# ------------------------------------------------------------------ the money arithmetic


def test_a_half_micro_usd_rounds_up_and_not_to_even():
    """`round()` is banker's rounding here and half-toward-+inf in the port.

    At one micro-USD per two tokens, an odd count lands on an exact half. `round` would
    answer 0, 2, 2 for these three; half-up answers 1, 2, 3, and so does the port.
    """
    half = table({"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": 500_000}})
    got = [price_tokens(half, "m", usage(input_tokens=n))["micros"] for n in (1, 3, 5)]
    assert got == [1, 2, 3]
    assert got != [round(0.5), round(1.5), round(2.5)]


@pytest.mark.parametrize(
    "micros,text",
    [
        (0, "0.000000"),
        (1, "0.000001"),
        (999_999, "0.999999"),
        (1_000_000, "1.000000"),
        (1_000_001, "1.000001"),
        (3_702, "0.003702"),
        (1_234_567_890, "1234.567890"),
        (MAX_SAFE_INT, "9007199254.740991"),
    ],
)
def test_format_micros_is_built_from_integers(micros, text):
    assert format_micros(micros) == text


def test_a_sub_cent_cost_survives_which_is_why_this_is_not_cents():
    # 1,234 tokens at $3.00/M is $0.003702 -- zero cents. A cents representation loses the
    # entire figure, which is the reason for micro-USD.
    answer = price_tokens(table({"m": RATE}), "m", usage(input_tokens=1_234))
    assert answer["micros"] == 3_702
    assert answer["amount"] == "0.003702"


def test_a_cost_above_two_to_the_53_refuses_rather_than_answering_wrong():
    answer = price_tokens(table({"m": RATE}), "m", usage(input_tokens=MAX_SAFE_INT))
    assert answer == {
        "unavailable": "cost for model 'm' exceeds 2**53-1 micro-USD, which is the largest "
        "integer both runtimes represent exactly"
    }


@pytest.mark.parametrize("bad", [-1, 1.5, True, MAX_SAFE_INT + 1, "1", None])
def test_a_count_that_is_not_a_count_refuses(bad):
    answer = price_tokens(table({"m": RATE}), "m", usage(input_tokens=bad))
    assert answer == {
        "unavailable": "usage token class 'input_tokens' is not a non-negative integer below 2**53"
    }


def test_an_integral_float_count_is_a_count():
    # `JSON.parse('1234.0')` is `1234` in the port and cannot be told from the integer, so
    # refusing the spelling here would be a divergence over nothing.
    assert price_tokens(table({"m": RATE}), "m", usage(input_tokens=1234.0))["micros"] == 3_702


# ------------------------------------------------------------------ the table validator


def test_true_is_not_the_rate_one():
    # `isinstance(True, int)` is true and `True == 1`; the port has no such hole, so without
    # the explicit exclusion the two runtimes disagree about this one document.
    with pytest.raises(PriceTableError) as exc:
        table({"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": True}})
    assert "is not a non-negative integer below 2**53" in str(exc.value)


def test_the_normalised_table_narrows_an_integral_float_rate():
    got = table({"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": 3_000_000.0}})
    assert got["rates"]["m"]["input_tokens"] == 3_000_000
    assert isinstance(got["rates"]["m"]["input_tokens"], int)


def test_the_normalised_table_has_a_fixed_key_order():
    got = validate_price_table(
        {"rates": {}, "unit": RATE_UNIT, "currency": "USD", "schema_version": 1}
    )
    assert list(got) == ["schema_version", "currency", "unit", "rates"]
    with_note = validate_price_table({**HEAD, "note": "hello", "rates": {}})
    assert list(with_note) == ["schema_version", "currency", "unit", "note", "rates"]


def test_the_offender_named_is_the_code_point_least_one():
    with pytest.raises(PriceTableError) as exc:
        validate_price_table({**HEAD, "zeta": 1, "alpha": 1, "rates": {}})
    assert str(exc.value) == "price table has unknown key 'alpha'"


@pytest.mark.parametrize(
    "raw,message",
    [
        ([], "price table must be a JSON object"),
        ("x", "price table must be a JSON object"),
        (
            {**HEAD, "schema_version": 2, "rates": {}},
            "price table schema_version must be the integer 1",
        ),
        (
            {**HEAD, "schema_version": True, "rates": {}},
            "price table schema_version must be the integer 1",
        ),
        ({**HEAD, "currency": "EUR", "rates": {}}, "price table currency must be the string 'USD'"),
        (
            {**HEAD, "unit": "usd_per_token", "rates": {}},
            "price table unit must be the string 'micro_usd_per_million_tokens'",
        ),
        ({**HEAD, "note": 7, "rates": {}}, "price table note must be a string"),
        ({**HEAD, "rates": []}, "price table rates must be a JSON object"),
        ({**HEAD, "rates": {"m": []}}, "price table rate 'm' must be a JSON object"),
        (
            {**HEAD, "rates": {"m": {**RATE, "cached_tokens": 1}}},
            "price table rate 'm' has unknown key 'cached_tokens'",
        ),
        (
            {**HEAD, "rates": {"m": {"recorded": "2026-09-11", "source": ""}}},
            "price table rate 'm' has a 'source' that is not a non-empty string",
        ),
        (
            {**HEAD, "rates": {"m": {"recorded": "2026-09-11", "source": "s"}}},
            "price table rate 'm' prices no token class at all",
        ),
        (
            {**HEAD, "rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": -1}}},
            "price table rate 'm' prices 'input_tokens' with something that is not a "
            "non-negative integer below 2**53",
        ),
    ],
)
def test_every_table_fault_has_its_own_sentence(raw, message):
    with pytest.raises(PriceTableError) as exc:
        validate_price_table(raw)
    assert str(exc.value) == message


# ------------------------------------------------------------------------------- loading


def test_a_missing_table_names_the_path_it_looked_at(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(PriceTableError) as exc:
        load_price_table(str(missing))
    assert str(exc.value) == f"price table not found: {missing}"


def test_an_undecodable_table_does_not_quote_the_decoder(tmp_path):
    """The sentence names the file and stops there.

    The two runtimes' JSON decoders phrase their own faults differently -- `validate.mjs`
    covers that separately -- so quoting one would make every malformed table a divergence
    over bytes that name the same fault.
    """
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema_version": 1,', encoding="utf-8")
    with pytest.raises(PriceTableError) as exc:
        load_price_table(str(broken))
    assert str(exc.value) == f"price table is not valid JSON: {broken}"


def test_a_bare_infinity_is_not_valid_json_here_either(tmp_path):
    """CPython's `json.loads` accepts `Infinity`; `JSON.parse` does not, and the module
    closes the hole with `parse_constant` so both answer the same sentence."""
    weird = tmp_path / "inf.json"
    weird.write_text(
        '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", '
        '"rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": Infinity}}}',
        encoding="utf-8",
    )
    with pytest.raises(PriceTableError) as exc:
        load_price_table(str(weird))
    assert str(exc.value) == f"price table is not valid JSON: {weird}"
    # And the hole is real: the stock decoder takes it.
    stock = json.loads(weird.read_text(encoding="utf-8"))
    assert stock["rates"]["m"]["input_tokens"] == float("inf")


def test_an_operator_supplied_table_is_read_through_the_env_var(tmp_path, monkeypatch):
    """The whole route by which a rate is allowed to enter the system: the operator's file,
    the operator's date, the operator's source."""
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps({**HEAD, "rates": {"m": RATE}}), encoding="utf-8")
    monkeypatch.setenv(PRICES_ENV, str(mine))
    got = load_price_table()
    assert got["rates"]["m"]["recorded"] == "2026-09-11"
    assert price_tokens(got, "m", usage(input_tokens=1_000_000))["amount"] == "3.000000"
