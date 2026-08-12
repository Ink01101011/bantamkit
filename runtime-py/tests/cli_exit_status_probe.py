"""The CLI in a REAL process, so a shell can read its own `$?`.

RB-P24's independent method. A test that calls `main()` and catches `SystemExit`
verifies a RETURN PATH; it does not verify what a CI job's `$?` is — the two differ
the moment anything between `main` and the interpreter swallows or rewrites the
status. So the exit-status contract is pinned by running this file as a process and
reading the status the shell reports.

The ONLY thing patched here is the client constructor: `criticreplay.OpenAICompatible`
becomes a scripted critic, so no request leaves the machine. Argument parsing, the
guard, the artifacts, the printed table and the status decision are all the shipped
`main()` on the shipped path. Patching the status logic, or calling anything other
than `main`, would make this probe agree with itself instead of measuring the CLI.

Not collected by pytest (the filename is deliberately not `test_*`);
`test_criticreplay.py` runs it through `/bin/sh` and reads `$?`.

    python cli_exit_status_probe.py --rubric L=<path> --transcripts <dir> \\
        --base-url http://x --model fake-14b [...]
"""

from __future__ import annotations

import json
import sys

from bantamkit import criticreplay
from bantamkit.client import Message, Response, Usage


class _ScriptedCritic:
    """Always scores 9. The status contract is about the guard, never about the score."""

    def __init__(self, model: str = "fake-14b"):
        self.model = model
        self.seed = None
        self._response_format_unsupported = False

    def chat(self, messages, tools=None, response_format=None):
        return Response(
            message=Message(
                role="assistant",
                content=json.dumps({"reasoning": "r", "score": 9, "feedback": "f"}),
            ),
            usage=Usage(100, 20),
        )


if __name__ == "__main__":
    criticreplay.OpenAICompatible = lambda **kw: _ScriptedCritic(kw.get("model", "fake-14b"))
    criticreplay.main(sys.argv[1:])
