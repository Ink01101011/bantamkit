"""The price table: the three properties, the rounding, and the refusal that is the default.

The port half is `runtime-ts/test/pricing.test.mjs` and the live differential between the two
is `tools/conformance/suites/pricing.mjs`. This file is the in-runtime half, so a mutation
that survives the pins is visible without a Node on PATH.

WHAT IS ASSERTED HERE AND NOT THERE: every number below is a TYPED literal rather than the other
runtime's answer -- a differential between two implementations that were both changed is green
(`feedback/differential-is-blind-to-symmetric-regression`).

#316 G1 (J87-3): `bantamkit.pricing` now runs the module ts2py generates from `pricing.ts`, and
the tests whose exact input a `--suite pricing` case already compares (with Node's value pinned
by the same-named test in `runtime-ts/test/pricing.test.mjs`) were retired; `docs/porting.md`
(*Generated modules*) lists each with the case that covers it. What stays is what the suite does
not reach: the Python-only inputs (a float count, a Python `True`, an env-var route, tuples), the
shim's surface (`TOKEN_CLASSES` is a tuple), and inputs the suite does not spell.
"""

from __future__ import annotations

import json

import pytest

from bantamkit.assets import assets_root
from bantamkit.pricing import (
    MAX_SAFE_INT,
    MICROS_PER_UNIT,
    PRICES_ENV,
    RATE_UNIT,
    TOKEN_CLASSES,
    PriceTableError,
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


# ------------------------------------------------------------- the shipped table is empty


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


def test_a_usage_missing_a_class_refuses_rather_than_defaulting_it():
    answer = price_tokens(table({"m": RATE}), "m", {"input_tokens": 1})
    assert answer == {
        "unavailable": "usage is missing token class 'cache_creation_input_tokens' -- all "
        "four of input_tokens, cache_creation_input_tokens, cache_read_input_tokens, "
        "output_tokens must be given, because a missing count is not a zero"
    }


def test_the_usage_is_checked_before_the_model_is_looked_up():
    """Both wrong at once, and the caller is told about their call rather than their table."""
    answer = price_tokens(table({"m": RATE}), "not-a-model", {"input_tokens": 1})
    assert "usage is missing token class" in answer["unavailable"]


# ------------------------------------------------------------------ the money arithmetic


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


def test_an_operator_supplied_table_is_read_through_the_env_var(tmp_path, monkeypatch):
    """The whole route by which a rate is allowed to enter the system: the operator's file,
    the operator's date, the operator's source."""
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps({**HEAD, "rates": {"m": RATE}}), encoding="utf-8")
    monkeypatch.setenv(PRICES_ENV, str(mine))
    got = load_price_table()
    assert got["rates"]["m"]["recorded"] == "2026-09-11"
    assert price_tokens(got, "m", usage(input_tokens=1_000_000))["amount"] == "3.000000"


# ------------------------------------------------- the shim over the generated module (#316 G1)


def test_the_table_error_is_still_a_bantam_error_and_reads_as_its_sentence():
    from bantamkit.client import BantamError

    with pytest.raises(BantamError) as exc:
        validate_price_table([])
    assert type(exc.value) is PriceTableError
    assert str(exc.value) == "price table must be a JSON object"
    assert exc.value.args == ("price table must be a JSON object",)


def test_a_path_object_and_none_are_still_accepted(tmp_path, monkeypatch):
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps({**HEAD, "rates": {}}), encoding="utf-8")
    assert load_price_table(mine)["rates"] == {}
    monkeypatch.setenv(PRICES_ENV, str(mine))
    assert load_price_table(None)["rates"] == {}


def test_a_top_level_tuple_is_refused_with_the_sentence_it_had():
    assert price_tokens(table({"m": RATE}), "m", tuple(usage())) == {
        "unavailable": "usage must be a mapping of token class to count"
    }
    with pytest.raises(PriceTableError) as exc:
        validate_price_table(("a",))
    assert str(exc.value) == "price table must be a JSON object"


@pytest.mark.parametrize(
    "model", ["toString", "constructor", "__proto__", "hasOwnProperty", "valueOf"]
)
def test_a_model_named_like_an_object_prototype_member_is_not_priced(model):
    """#316 G1 (J87-3F): an own-key lookup in `pricing.ts`, so such a name is an unknown model on
    both sides (Node priced it at $0.00 before). Its own key is still found, `__proto__` too."""
    assert price_tokens(table({"m": RATE}), model, usage(input_tokens=1)) == {
        "unavailable": f"no rate recorded for model {model!r} -- add one with its date and "
        "source, or point BANTAMKIT_PRICES at a table that has it"
    }
    # The usage is still checked first.
    assert "usage is missing" in price_tokens(table({"m": RATE}), model, {})["unavailable"]
    own_table = table({model: RATE})
    assert list(own_table["rates"]) == [model]
    own = price_tokens(own_table, model, usage(input_tokens=1_000_000))
    assert own["micros"] == 3_000_000
