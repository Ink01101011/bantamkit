"""`pattern`, top-level scalars and clipped feedback (job65 J65-7: #131, #132, #152, #153).

The reference half of `runtime-ts/test/patterns.test.mjs`; `tools/conformance/suites/
validate.mjs` (`pattern/`) compares the two runtimes answer for answer.

- #131: the dialect is `re`'s, and the port translates it; a construct the port cannot
  translate faithfully is ANSWERED with one sentence on both runtimes, eagerly.
- #132: a document's patterns share a 500 ms budget, the search runs in a killable child, and
  a `ping` sent behind a catastrophic validation is answered within a second.
- #152: `"x"`, `1.0` and `null` are JSON documents.
- #153: an offending value is quoted at most 200 codepoints, a sentence at most 1000.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from bantamkit import contract
from bantamkit.contract import schema_error

REFUSED = (
    " is not supported: this validator refuses inline flags, look-behind, backreferences, "
    "atomic groups, possessive quantifiers, conditional groups and \\N{...} escapes"
)


def s_of(pattern: str) -> dict:
    return {"properties": {"s": {"pattern": pattern}}}


def test_the_issue_131_probes_keep_the_reference_verdicts():
    assert schema_error(json.dumps({"s": "๑๒๓"}), s_of(r"^\d+$")) is None
    assert schema_error(json.dumps({"s": "ไทย"}), s_of(r"^\w+$")) is None
    assert schema_error(json.dumps({"s": "a\n"}), s_of("^a$")) is None
    assert (
        schema_error(json.dumps({"s": "abcZ"}), s_of(r"c\Z"))
        == "JSON does not match schema at 's': 'abcZ' does not match 'c\\\\Z'"
    )
    assert schema_error(json.dumps({"s": "a"}), s_of("(?P<x>a)")) is None


@pytest.mark.parametrize(
    "pattern",
    [
        "(?i)a",
        "(?<=a)b",
        "(a)\\1",
        "(?P<n>a)(?P=n)",
        "(?>a)",
        "a*+",
        "(a)?(?(1)b|c)",
        "\\N{DIGIT ONE}",
        "\\N{NOPE}",
    ],
)
def test_a_construct_outside_the_shared_dialect_is_answered_eagerly(pattern):
    # `{"n": 1}` never reaches `s`: the refusal is the schema's, like check_schema's compile.
    assert schema_error('{"n": 1}', s_of(pattern)) == f"the pattern {pattern!r}{REFUSED}"


def test_the_default_flag_and_a_broken_pattern_are_not_the_refusal():
    assert schema_error('{"s": "a"}', s_of("(?u)^a$")) is None
    assert not contract._pattern_unsupported("(")  # left to check_schema, which raises
    with pytest.raises(Exception, match="regex"):
        schema_error('{"n": 1}', s_of("("))


def test_a_catastrophic_pattern_is_refused_at_the_budget():
    started = time.monotonic()
    answer = schema_error(json.dumps({"s": "a" * 40 + "!"}), s_of("^(a+)+$"))
    took = time.monotonic() - started
    assert answer == (
        "the pattern '^(a+)+$' did not finish within the 500 ms this validator allows a "
        "document's patterns; rewrite it so it cannot backtrack catastrophically, as (a+)+$ does"
    )
    assert took < 2.0, took
    # The child that was killed is replaced, and the clock is per validation.
    assert schema_error(json.dumps({"s": "aaa"}), s_of("^(a+)+$")) is None


def test_the_budget_reaches_every_keyword_that_searches():
    boom = "a" * 40 + "!"
    schema = {"patternProperties": {"^(a+)+$": {}}, "additionalProperties": False}
    assert "did not finish within the 500 ms" in schema_error(json.dumps({boom: 1}), schema)


def test_a_ping_behind_a_catastrophic_validate_json_is_answered_within_a_second(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=tmp_path,
        env=env,
    )
    frames: queue.Queue[dict] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            frames.put(json.loads(line))

    threading.Thread(target=pump, daemon=True).start()

    def send(frame: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(frame) + "\n").encode())
        proc.stdin.flush()

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            }
        )
        assert frames.get(timeout=30)["id"] == 1
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        t0 = time.monotonic()
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "validate_json",
                    "arguments": {
                        "output": json.dumps({"x": "a" * 40 + "!"}),
                        "schema": {"properties": {"x": {"pattern": "^(a+)+$"}}},
                    },
                },
            }
        )
        time.sleep(0.02)
        send({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        at: dict[int, float] = {}
        got: dict[int, dict] = {}
        while len(got) < 2:
            frame = frames.get(timeout=30)
            got[frame["id"]] = frame
            at[frame["id"]] = time.monotonic() - t0
        assert at[3] < 1.0, at
        body = json.loads(got[2]["result"]["content"][0]["text"])
        assert body["valid"] is False
        assert "did not finish within the 500 ms" in body["feedback"]
    finally:
        proc.kill()
        proc.wait()


def test_a_top_level_scalar_is_a_json_document():
    assert schema_error('"just a string"', {"type": "string"}) is None
    assert schema_error("1.0", {"type": "number"}) is None
    assert schema_error("null", {"type": "null"}) is None
    assert (
        schema_error('"x"', {"type": "integer"})
        == "JSON does not match schema at 'root': 'x' is not of type 'integer'"
    )
    assert (
        schema_error("42 is the answer", {})
        == "output was not parseable JSON: no JSON object found in output"
    )


def test_the_offending_value_is_clipped():
    big = schema_error(json.dumps({"x": "y" * (1 << 20)}), {"properties": {"x": {"maxLength": 10}}})
    assert big == f"JSON does not match schema at 'x': '{'y' * 199}…(1048378 more) is too long"
    key = schema_error(json.dumps({"k" * 5000: 1}), {"additionalProperties": False})
    assert len(key) < 1100
    assert key.endswith("more)")
    astral = schema_error(json.dumps({"x": "😀" * 300}), {"properties": {"x": {"maxLength": 1}}})
    assert astral == f"JSON does not match schema at 'x': '{'😀' * 199}…(102 more) is too long"
