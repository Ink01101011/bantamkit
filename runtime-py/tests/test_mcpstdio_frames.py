"""job66/J66-3: the frames the SDK's stdin reader used to drop, and the daemon reader (#148, #181).

The differential against the port is the `j66-3:` block of `tools/conformance/suites/wire.mjs`,
which drives both real servers over stdio. What is here is `mcpstdio` alone.
"""

from __future__ import annotations

import asyncio
import io

import pytest

from bantamkit.mcpstdio import _DaemonLines, malformed_frame_error

PARSE = '{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}'
INVALID = '{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Invalid Request"}}'


def _frame(line: str) -> str | None:
    error = malformed_frame_error(line)
    return None if error is None else error.model_dump_json(by_alias=True, exclude_unset=True)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("{not json\n", PARSE),
        ("NaN\n", PARSE),
        ('[{"jsonrpc":"2.0","id":901,"method":"ping"}]\n', INVALID),
        ("[]\n", INVALID),
        ("42\n", INVALID),
        ('"a string"\n', INVALID),
        ('{"jsonrpc":"2.0","id":5}\n', INVALID),
        ('{"id":6,"method":"ping"}\n', INVALID),
        ('{"jsonrpc":"2.0","id":"s","method":3}\n', INVALID),
        ('{"jsonrpc":"2.0","id":7,"method":"ping","params":[]}\n', INVALID),
        ('{"jsonrpc":"1.0","id":8,"method":"ping"}\n', INVALID),
        ('{"jsonrpc":"2.0","id":3,"method":"ping","params":{"_meta":{"x":"\\ud800"}}}\n', INVALID),
        ('{"jsonrpc":"2.0","id":4,"method":"ping","params":{"_meta":{"x":NaN}}}\n', PARSE),
    ],
)
def test_148_a_frame_the_sdk_drops_is_answered_with_id_null(line, expected):
    assert _frame(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "\n",
        '{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
        '{"jsonrpc":"2.0","id":123456789012345678901234567890,"method":"ping"}\n',
        # Not a str and not an int: pydantic reads a notification, which is not answered.
        '{"jsonrpc":"2.0","id":1.0,"method":"ping"}\n',
        '{"jsonrpc":"2.0","id":null,"method":"ping"}\n',
        '{"jsonrpc":"2.0","id":10,"method":"ping","extra":1}\n',
        '{"jsonrpc":"2.0","id":11,"method":"ping","params":null}\n',
    ],
)
def test_148_a_frame_the_sdk_reads_is_left_to_the_sdk(line):
    assert malformed_frame_error(line) is None


def test_181_the_daemon_reader_yields_every_line_then_stops():
    async def collect() -> list[str]:
        return [line async for line in _DaemonLines(io.StringIO("a\nb\n\nc"))]

    assert asyncio.run(collect()) == ["a\n", "b\n", "\n", "c"]
