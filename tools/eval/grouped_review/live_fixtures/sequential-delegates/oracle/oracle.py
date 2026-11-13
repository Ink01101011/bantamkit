"""Hidden oracle for sequential-delegates. Host-only: never copied into a workspace."""

import importlib
from datetime import UTC, datetime


def _fn(module, name):
    return getattr(importlib.import_module(f"logscan.{module}"), name)


def _rec(hour, minute, second=0, level="INFO", component="api", day=2):
    ts = datetime(2026, 1, day, hour, minute, second, tzinfo=UTC)
    return {"ts": ts, "level": level, "component": component, "message": "m"}


def a_fields():
    parse = _fn("parse", "parse_line")
    got = parse("2026-03-04T05:06:07Z ERROR db: timeout: retry in 5s \n")
    assert got == {
        "ts": datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
        "level": "ERROR",
        "component": "db",
        "message": "timeout: retry in 5s",
    }, got
    assert got["ts"].tzinfo is not None


def a_level():
    parse = _fn("parse", "parse_line")
    assert parse("2026-03-04T05:06:07Z warn cache: cold")["level"] == "WARN"
    assert parse("2026-03-04T05:06:07Z Debug cache: hot")["level"] == "DEBUG"
    assert parse("2026-03-04T05:06:07Z TRACE cache: cold") is None
    assert parse("2026-03-04T05:06:07Z FATAL cache: cold") is None


def a_invalid():
    parse = _fn("parse", "parse_line")
    for bad in (
        "",
        "   ",
        "2026-03-04T05:06:07Z INFO",
        "2026-03-04T05:06:07Z INFO no colon here",
        "2026-03-04T05:06:07Z INFO : empty component",
        "2026-13-04T05:06:07Z INFO api: bad month",
        "2026-03-04 05:06:07 INFO api: wrong stamp",
    ):
        assert parse(bad) is None, bad


def b_boundary():
    count = _fn("window", "count_by_window")
    got = count([_rec(10, 4, 59), _rec(10, 5, 0), _rec(10, 9, 59), _rec(10, 0, 0)], 5)
    assert got == {"2026-01-02T10:00Z": 2, "2026-01-02T10:05Z": 2}, got
    assert count([_rec(23, 59, 59)], 60) == {"2026-01-02T23:00Z": 1}


def b_order():
    count = _fn("window", "count_by_window")
    got = count([_rec(9, 30), _rec(8, 1), _rec(0, 0, day=3), _rec(8, 14)], 15)
    assert list(got.items()) == [
        ("2026-01-02T08:00Z", 2),
        ("2026-01-02T09:30Z", 1),
        ("2026-01-03T00:00Z", 1),
    ], got


def b_validation():
    count = _fn("window", "count_by_window")
    for bad in (0, -5, 7):
        try:
            count([_rec(1, 1)], bad)
        except ValueError:
            continue
        raise AssertionError(f"minutes={bad} must raise ValueError")
    assert count([], 1440) == {}


def c_filter():
    top = _fn("report", "top_components")
    records = [_rec(1, 1, level="ERROR", component="db"), _rec(1, 2, level="INFO"),
               _rec(1, 3, level="ERROR", component="db"), _rec(1, 4, level="WARN")]
    assert top(records, "error") == [("db", 2)]
    assert top(records, "DEBUG") == []


def c_ranking():
    top = _fn("report", "top_components")
    names = ["web", "api", "db", "api", "web", "cache", "db"]
    records = [_rec(1, i, level="WARN", component=n) for i, n in enumerate(names)]
    assert top(records, "WARN", 10) == [("api", 2), ("db", 2), ("web", 2), ("cache", 1)]


def c_limit():
    top = _fn("report", "top_components")
    names = ["a", "b", "c", "d", "a"]
    records = [_rec(1, i, level="INFO", component=n) for i, n in enumerate(names)]
    assert top(records, "INFO") == [("a", 2), ("b", 1), ("c", 1)]
    assert top(records, "INFO", 1) == [("a", 2)]
    assert top(records, "INFO", 0) == []


CRITERIA = {
    "A-fields": a_fields,
    "A-level": a_level,
    "A-invalid": a_invalid,
    "B-boundary": b_boundary,
    "B-order": b_order,
    "B-validation": b_validation,
    "C-filter": c_filter,
    "C-ranking": c_ranking,
    "C-limit": c_limit,
}
