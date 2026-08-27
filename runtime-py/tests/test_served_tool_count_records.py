"""Every record that states how many tools are served, against what is served.

WHAT THIS EXISTS FOR. "seven tools" survived as a record in three layers after
the surface became eight, and job40's C1 found it by reading, not by running.
Nothing in this tree compared a STATED count against a SERVED one. C8B designed
this gate and did not build it; this is that design.

THE TWO THINGS C8B'S DESIGN INSISTS ON, and why each is here.

1. **It keys on a live `tools/list` from BOTH launchers, never on a constant.**
   A gate holding its own copy of the number is just a fourth place for the
   number to go stale, and it would go stale in the direction that hides the
   defect: someone adding a tool edits the constant and the gate keeps passing.
   So the expected value is whatever the servers actually answer, and the two
   launchers are asked separately — a count that drifted on one side only is the
   parity failure this repository's whole conformance layer exists to catch.

2. **Dated and hypothetical records are exempt BY AN EXPLICIT MARKER, never by
   tense.** C8B's recommendation, quoted: tense-sniffing English "is the part
   that will be wrong". This gate scans its own source, so the examples below
   carry the marker they document — it caught itself the moment it became a
   tracked file, which is the shortest demonstration of it there is.
   (served-tools: dated) A sentence like "would have served ten tools instead of
   seven" is not a claim about today and must not be forced to say eight, while
   "the agent surface is still exactly eight tools" is a claim about today and
   must break the day it stops being one. No regex can tell those apart. A
   marker can, and it costs the writer four words.

   The marker is `served-tools: dated` on the claiming line or on any of the
   three lines above it.

THE ONE BLANKET EXEMPTION, and why it is principled rather than convenient:
the files in `tools/amendguard/ledger.json`'s `amend_only` list. Those files
cannot be edited in place at all — they are an append-only record of what was
measured on a date, so EVERY figure in them is dated by construction and a gate
demanding they track today's surface would be demanding the impossible. The list
is read from the ledger rather than spelled here, so the two cannot drift.

WHAT THIS DELIBERATELY DOES NOT DO. It does not try to find every sentence about
tools. The pattern is narrow on purpose — a count immediately preceded by a
serving verb — because a gate that fires on "the two tools said" would be turned
off within a week. Measured at the commit that added it, by the gate's own
census over the tracked tree: **19 hits** — **10 live claims** (every one saying 8,
which is what both launchers answer), **4 inside `amend_only` files**, and
**5 carrying the marker**. Five of those nineteen are in THIS FILE, which the
census counts like any other: a gate exempt from itself is a gate with a hole
shaped like its own documentation. A claim phrased outside the pattern is not
caught, and that is a known hole rather than a hidden one.

NON-VACUITY, measured 2026-08-25 by mutating BOTH OPERANDS in turn and reverting
(served-tools: dated — the surface was eight then; `memory_compact` made it nine):

  * the RECORD side — `serving 8 tools` -> `serving 7 tools` in `docs/status.md`:
    RED, naming `docs/status.md:46` and `:56`, "says 7, served is 8".
  * the SERVED side — `assets/tools/validate_json.json` moved out of the pack:
    RED on two nodes at once, because every one of the nine live records is now
    stale against a surface of seven.

The second is the direction that matters and the one a constant could not have
caught: nobody edited a record, and the gate still went red.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[2]
LEDGER = REPO / "tools" / "amendguard" / "ledger.json"

WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}

#: A count of tools immediately preceded by a verb that makes it a claim about
#: what a server answers. Deliberately narrow — see the module docstring.
CLAIM = re.compile(
    r"(?:serves?|serving|served|answers? with|answered with|registers?|registered"
    r"|exactly|surface[^.\n]{0,20})\s+"
    r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+tools\b",
    re.IGNORECASE,
)

MARKER = "served-tools: dated"


def _amend_only() -> list[str]:
    return list(json.loads(LEDGER.read_text(encoding="utf-8"))["amend_only"])


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    paths = []
    for rel in out.split("\0"):
        if not rel:
            continue
        path = REPO / rel
        if path.suffix in {".png", ".jpg", ".gz", ".tgz", ".zip", ".pdf"}:
            continue
        if not path.is_file():
            continue
        paths.append(path)
    return paths


async def _served_names(command: str, args: list[str]) -> list[str]:
    params = StdioServerParameters(command=command, args=args, env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return sorted(tool.name for tool in (await session.list_tools()).tools)


def _served(command: str, args: list[str] | None = None) -> list[str]:
    return asyncio.run(_served_names(command, args or []))


# --------------------------------------------------------------- the live surface

_POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "PRICED: `tools/bantamkit-mcp` is `#!/bin/sh` and Windows has no POSIX shell "
        "to run it — RB-P101, an open item with its own job. The Node launcher below "
        "is asked on every platform."
    ),
)


@_POSIX_ONLY
def test_both_launchers_serve_the_same_tools() -> None:
    """The parity half. A count that drifted on one side only dies here."""
    python_side = _served(str(REPO / "tools" / "bantamkit-mcp"))
    node_side = _served(str(REPO / "tools" / "bantamkit-mcp-node"))
    assert python_side == node_side, (
        "the two launchers do not serve the same tools\n"
        f"  python: {python_side}\n"
        f"  node  : {node_side}"
    )
    assert python_side, "a launcher that serves NOTHING would satisfy equality"


@_POSIX_ONLY
def test_every_stated_tool_count_matches_what_is_served() -> None:
    """The records half, keyed on the servers rather than on a number kept here."""
    served = len(_served(str(REPO / "tools" / "bantamkit-mcp")))
    assert served > 0

    exempt_globs = _amend_only()
    offenders: list[str] = []
    checked = 0
    exempt_by_ledger = 0
    exempt_by_marker = 0

    for path in _tracked_text_files():
        rel = path.relative_to(REPO).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        ledgered = any(Path(rel).match(glob) for glob in exempt_globs)
        for number, line in enumerate(lines, start=1):
            match = CLAIM.search(line)
            if match is None:
                continue
            if ledgered:
                exempt_by_ledger += 1
                continue
            # The marker may sit on the claiming line or on any of the THREE lines above
            # it. Three, because prose wraps and the sentence that dates a figure is
            # often not the sentence that carries it; still tight enough that a marker
            # cannot reach a claim in a different paragraph.
            context = "\n".join(lines[max(0, number - 4) : number])
            if MARKER in context:
                exempt_by_marker += 1
                continue
            checked += 1
            token = match.group(1).lower()
            stated = WORDS.get(token, None)
            if stated is None:
                stated = int(token)
            if stated != served:
                offenders.append(f"{rel}:{number}: says {stated}, served is {served}")

    assert not offenders, (
        "records state a served-tool count that the servers do not answer.\n"
        "Either the record is stale, or it is a dated/hypothetical statement and wants\n"
        f"`{MARKER}` on its own line or the line above.\n" + "\n".join(offenders)
    )
    # The gate must not pass by finding nothing. If the pattern stops matching, that is
    # a defect in the gate and it says so here rather than going quiet.
    assert checked >= 5, (
        f"only {checked} live claims matched — the pattern has probably stopped matching "
        f"(ledger-exempt {exempt_by_ledger}, marker-exempt {exempt_by_marker})"
    )


def test_the_node_launcher_serves_the_same_count_on_every_platform() -> None:
    """The half that runs on Windows too, so the matrix is not blind to the port."""
    if shutil.which("node") is None:  # pragma: no cover - node is a hard dependency here
        pytest.skip("node is not on PATH")
    names = _served(str(REPO / "tools" / "bantamkit-mcp-node"))
    assert names, "the Node launcher served no tools at all"
