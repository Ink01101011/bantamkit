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

TWO MORE FRAMES THE SDK DROPPED ARE ANSWERED (job66/#148). A line that is not JSON, or JSON
that is not a JSON-RPC message (a batch array, a bare number, a request with no `jsonrpc`), went
the same way: the reader's parse failed, the exception went to the session, nothing was sent.
JSON-RPC 2.0 section 5.1 prescribes an answer with `id: null`, so the wrapper now asks the SDK's
own adapter first and, where the SDK would drop the line, answers `-32700 Parse error` (the
standard library's `json` cannot read it either) or `-32600 Invalid Request` (it can). The
port writes the same two frames from `runtime-ts/src/mcp/transport.ts`; the `wire` suite
compares them. A blank line still goes to the SDK and is still dropped, as the port skips it.

A HOST THAT CLOSED ITS READ END ENDS THE SESSION QUIETLY (job66/#181). Measured before this
change: a 3 MB answer written to a closed stdout raised `BrokenPipeError` out of the SDK's writer,
and the process then HUNG until stdin closed -- the reader is a blocking `readline` on an anyio
worker thread, which a cancelled task group must wait for -- and only then died, exit 1, with an
exception-group traceback. Stdin is now read on a DAEMON thread, so a cancelled reader is
abandoned rather than awaited, and the broken pipe is caught: exit 0, nothing on stderr, the
same as the port and the same as stdin EOF.

PRIVATE SDK NAMES, ON PURPOSE. `_claim_fd`, `_open_stdin_diversion`, `_UnownedTextWrapper`
and `MCPServer._lowlevel_server` are not public API. They are what `stdio_server()` and
`run_stdio_async()` themselves use, the SDK is upper-capped in `runtime-py/pyproject.toml`
(CLAUDE.md), and passing our own stdin without the claim would leave fd 0 readable by every
child a handler spawns. A rename inside the cap fails at import or at first use, loudly.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
from collections.abc import AsyncIterator
from typing import Any

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


def _no_constant(name: str) -> Any:
    raise ValueError(f"not JSON: {name}")


def malformed_frame_error(line: str) -> types.JSONRPCError | None:
    """The `id: null` error for a line the SDK's reader would drop, or `None` (#148).

    `-32700` when the line is not JSON at all -- `NaN` and `Infinity` included, which
    `json.loads` would otherwise accept and JSON does not -- and `-32600` when it is JSON
    but not a message the SDK's own adapter accepts. A blank line is `None`: it is skipped,
    not answered, on both runtimes.
    """
    if not line.strip():
        return None
    # pydantic's parser reads `NaN` and `Infinity` where JSON has none; the port's
    # `JSON.parse` does not. Only a line spelling one can hold one, so only that line pays.
    if ("NaN" in line or "Infinity" in line) and not _is_strict_json(line):
        return _error(-32700, "Parse error")
    try:
        types.jsonrpc_message_adapter.validate_json(line, by_name=False)
    except Exception:  # noqa: BLE001 - the SDK's reader catches exactly this broadly
        pass
    else:
        return None
    # A lone surrogate lands here too: `json` reads it, pydantic's parser does not.
    if _is_strict_json(line):
        return _error(-32600, "Invalid Request")
    return _error(-32700, "Parse error")


def _is_strict_json(line: str) -> bool:
    try:
        json.loads(line, parse_constant=_no_constant)
    except ValueError:
        return False
    return True


def _error(code: int, message: str) -> types.JSONRPCError:
    error = types.ErrorData(code=code, message=message)
    return types.JSONRPCError(jsonrpc="2.0", id=None, error=error)


class _DaemonLines:
    """The lines of a text stream, read on a DAEMON thread (#181).

    `anyio.wrap_file` reads on a worker thread the task group has to wait for, so a session
    whose stdout broke could not end until stdin did. A daemon thread is abandoned instead.
    One line is read ahead at most: the thread blocks until the loop has taken the last one.
    """

    def __init__(self, text: Any) -> None:
        self._text = text

    def __aiter__(self) -> AsyncIterator[str]:
        return self._lines()

    async def _lines(self) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1)

        def pump() -> None:
            try:
                for line in self._text:
                    asyncio.run_coroutine_threadsafe(queue.put(line), loop).result()
            except (OSError, ValueError, RuntimeError):
                pass  # the fd was released or the loop is gone: nobody is reading any more
            finally:
                try:
                    asyncio.run_coroutine_threadsafe(queue.put(None), loop)
                except RuntimeError:
                    pass

        threading.Thread(target=pump, name="bantamkit-stdin", daemon=True).start()
        while (line := await queue.get()) is not None:
            yield line


class _Lines:
    """The SDK's stdin, with the lone-surrogate `tools/call` frames answered and withheld,
    and the frames the SDK would drop answered `-32700`/`-32600` (#148)."""

    def __init__(self, inner: Any, tools: frozenset[str]) -> None:
        self._inner = inner
        self._tools = tools
        self.write_stream: Any = None

    def __aiter__(self) -> AsyncIterator[str]:
        return self._lines()

    async def _lines(self) -> AsyncIterator[str]:
        async for line in self._inner:
            response: types.JSONRPCResponse | types.JSONRPCError | None = None
            if self.write_stream is not None:
                response = refusal_for(line, self._tools) or malformed_frame_error(line)
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
        lines = _Lines(_DaemonLines(text), tools)
        async with _sdk_stdio.stdio_server(stdin=lines) as (read_stream, write_stream):  # type: ignore[arg-type]
            lines.write_stream = write_stream
            lowlevel = server._lowlevel_server
            await lowlevel.run(read_stream, write_stream, lowlevel.create_initialization_options())
    except* (BrokenPipeError, ConnectionResetError):
        # The host closed its read end (#181): the session is over, exactly as on stdin EOF.
        pass
    finally:
        if release is not None:
            release()
