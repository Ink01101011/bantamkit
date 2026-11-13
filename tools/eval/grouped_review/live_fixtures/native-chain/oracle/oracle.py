"""Hidden oracle for native-chain. Host-only: never copied into an agent workspace."""

import importlib


def _fn(module, name):
    return getattr(importlib.import_module(f"ledgerkit.{module}"), name)


def _raises(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError(f"expected ValueError for {args!r}")


def a_format():
    parse = _fn("money", "parse_amount")
    assert parse("$1,234.50") == 123450
    assert parse("  7 ") == 700
    assert parse("0.5") == 50
    assert parse("-3") == -300
    assert parse("-$4.20") == -420


def a_rounding():
    parse = _fn("money", "parse_amount")
    assert parse("0.125") == 13
    assert parse("2.675") == 268
    assert parse("-0.125") == -13
    assert parse("1.004") == 100


def a_invalid():
    parse = _fn("money", "parse_amount")
    for bad in ("", "   ", "abc", "1.2.3", "NaN", "Infinity"):
        _raises(parse, bad)


def b_total():
    line = _fn("lines", "line_total")
    assert line(3, "$2.50") == 750
    assert line(2, "1,000") == 200000
    assert line(1, "0.005") == 1


def b_discount():
    line = _fn("lines", "line_total")
    assert line(1, "0.10", 25) == 7
    assert line(3, "10.00", 10) == 2700
    assert line(4, "1.00", 100) == 0
    assert line(1, "0.30", 50) == 15


def b_validation():
    line = _fn("lines", "line_total")
    _raises(line, 0, "1.00")
    _raises(line, -2, "1.00")
    _raises(line, 1, "1.00", -1)
    _raises(line, 1, "1.00", 101)


def c_totals():
    summary = _fn("invoice", "invoice_summary")
    got = summary([(2, "3.00", 0), (1, "$1,000", 10)], 10)
    assert got == {"subtotal": 90600, "tax": 9060, "total": 99660}
    assert summary([(1, "5", 0)], "7.5") == {"subtotal": 500, "tax": 38, "total": 538}


def c_tax_rounding():
    summary = _fn("invoice", "invoice_summary")
    assert summary([(1, "1.50", 0)], 7)["tax"] == 11
    assert summary([(1, "1.49", 0)], 7)["tax"] == 10
    assert summary([(3, "0.05", 0)], 10)["tax"] == 2


def c_empty():
    summary = _fn("invoice", "invoice_summary")
    assert summary([], 20) == {"subtotal": 0, "tax": 0, "total": 0}
    assert summary(iter([(1, "2.00", 0)]), 0) == {"subtotal": 200, "tax": 0, "total": 200}


CRITERIA = {
    "A-format": a_format,
    "A-rounding": a_rounding,
    "A-invalid": a_invalid,
    "B-total": b_total,
    "B-discount": b_discount,
    "B-validation": b_validation,
    "C-totals": c_totals,
    "C-tax-rounding": c_tax_rounding,
    "C-empty": c_empty,
}
