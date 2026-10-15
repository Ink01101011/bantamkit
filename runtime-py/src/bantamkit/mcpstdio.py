"""The stdio transport, with the one frame the SDK drops answered (job65/#160).

WHY THIS EXISTS. JSON can spell a lone surrogate (`"\\ud800"`), and a client that sends one in
a tool argument used to get NO ANSWER AT ALL from this server: the SDK's stdin reader parses
each line with pydantic's JSON parser, which rejects the escape as invalid JSON, hands the
exception to the session and moves on -- no id was read, so nothing is ever sent back and the
caller waits forever (measured: `tools/call` timed out at 8 s, a later `ping` on the same pipe
answered). The port, meanwhile, accepted the argument and wrote U+FFFD into the fact file.

Both runtimes now refuse it by name, as a tool error: `Error executing tool <name>: argument
'<path>' holds a lone surrogate (U+XXXX), which is not text; nothing was done`. The port says it
from `runtime-ts/src/mcp/pyargs.ts` (`loneSurrogateArgument`, the same walk). Here it has to be
said BEFORE the SDK parses the line, so the reader is wrapped: a line is looked at only when it
carries a `\\uD8..`-`\\uDF..` escape, re-read with the standard library's `json` (which keeps a
lone surrogate as a code point), and answered only when it is a `tools/call` request with an id,
for a tool this server serves, whose arguments hold one. Every other line goes to the SDK
byte for byte, as before -- including a lone surrogate anywhere else in a frame, which the SDK
still drops (the malformed-frame class, not this one).

PRIVATE SDK NAMES, ON PURPOSE. `_claim_fd`, `_open_stdin_diversion`, `_UnownedTextWrapper`
and `MCPServer._lowlevel_server` are not public API. They are what `stdio_server()` and
`run_stdio_async()` themselves use, the SDK is upper-capped in `runtime-py/pyproject.toml`
(CLAUDE.md), and passing our own stdin without the claim would leave fd 0 readable by every
child a handler spawns. A rename inside the cap fails at import or at first use, loudly.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import AsyncIterator
from typing import Any

import anyio
import mcp_types as types
from mcp.server import stdio as _sdk_stdio
from mcp.shared.message import SessionMessage

# A surrogate code point that survives `json.loads` is lone: a pair becomes one code point.
_LONE = re.compile("[\ud800-\udfff]")
# Only a line spelling a surrogate escape can hold one; every other line skips the re-read.
_ESCAPE = re.compile(r"\\u[dD][89a-fA-F][0-9a-fA-F]{2}")


def lone_surrogate_argument(arguments: Any) -> str | None:
    """The refusal sentence for the first lone surrogate in `arguments`, or `None`.

    `<path>` is the top-level argument, then `[i]` for a list item and `.key` for a dict
    member, first in document order. Keys are not inspected.
    """

    def walk(value: Any, where: str) -> str | None:
        if isinstance(value, str):
            found = _LONE.search(value)
            if found is None:
                return None
            return (
                f"argument '{where}' holds a lone surrogate (U+{ord(found.group()):04X}), "
                f"which is not text; nothing was done"
            )
        if isinstance(value, list):
            for i, item in enumerate(value):
                if (hit := walk(item, f"{where}[{i}]")) is not None:
                    return hit
        if isinstance(value, dict):
            for key, item in value.items():
                if (hit := walk(item, f"{where}.{key}")) is not None:
                    return hit
        return None

    if not isinstance(arguments, dict):
        return None
    for key, item in arguments.items():
        if (hit := walk(item, key)) is not None:
            return hit
    return None


def refusal_for(line: str, tools: frozenset[str]) -> types.JSONRPCResponse | None:
    """The response for a `tools/call` frame carrying a lone surrogate, or `None`."""
    if _ESCAPE.search(line) is None:
        return None
    try:
        frame = json.loads(line)
    except ValueError:
        return None
    if not isinstance(frame, dict) or frame.get("method") != "tools/call" or "id" not in frame:
        return None
    request_id = frame["id"]
    if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
        return None
    params = frame.get("params")
    if not isinstance(params, dict) or params.get("name") not in tools:
        return None
    sentence = lone_surrogate_argument(params.get("arguments"))
    if sentence is None:
        return None
    # Built as the SDK's own tool-error frame is serialised (`text` before `type`), so the
    # bytes on the wire are the ones every other tool error carries.
    return types.JSONRPCResponse(
        jsonrpc="2.0",
        id=request_id,
        result={
            "content": [
                {"text": f"Error executing tool {params['name']}: {sentence}", "type": "text"}
            ],
            "isError": True,
        },
    )


class _Lines:
    """The SDK's stdin, with the lone-surrogate `tools/call` frames answered and withheld."""

    def __init__(self, inner: Any, tools: frozenset[str]) -> None:
        self._inner = inner
        self._tools = tools
        self.write_stream: Any = None

    def __aiter__(self) -> AsyncIterator[str]:
        return self._lines()

    async def _lines(self) -> AsyncIterator[str]:
        async for line in self._inner:
            response = refusal_for(line, self._tools) if self.write_stream is not None else None
            if response is None:
                yield line
            else:
                await self.write_stream.send(SessionMessage(response))


async def serve_stdio(server: Any) -> None:
    """`server.run_stdio_async()`, with the reader wrapped (see the module docstring)."""
    tools = frozenset(tool.name for tool in await server.list_tools())
    buffer, release = _sdk_stdio._claim_fd(0, sys.stdin, "rb", _sdk_stdio._open_stdin_diversion)
    try:
        text = _sdk_stdio._UnownedTextWrapper(buffer, encoding="utf-8", errors="replace")
        lines = _Lines(anyio.wrap_file(text), tools)
        async with _sdk_stdio.stdio_server(stdin=lines) as (read_stream, write_stream):  # type: ignore[arg-type]
            lines.write_stream = write_stream
            lowlevel = server._lowlevel_server
            await lowlevel.run(read_stream, write_stream, lowlevel.create_initialization_options())
    finally:
        if release is not None:
            release()
