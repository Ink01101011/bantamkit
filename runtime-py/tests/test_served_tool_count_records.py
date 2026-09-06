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
from conftest import windows_cannot_construct
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[2]
LEDGER = REPO / "tools" / "amendguard" / "ledger.json"

WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}

#: The spelled numbers, as ONE regex alternation built from `WORDS` rather than typed out.
#
# J45-11 had to teach this table the word "thirteen" before the thirteenth tool's records
# could be seen at all -- without it, every "thirteen tools" record would have been
# INVISIBLE to this gate rather than red, which is strictly worse than no gate. The table
# was then typed in THREE places (here and twice inside `CLAIM`), so the next tool would
# have hit the same cliff in three spots at once. It is derived now, so there is one list.
#
# Longest first: `re`'s alternation is ordered, and while backtracking does eventually
# reach `sixteen` after `six` fails to be followed by `tools`, ordering makes that a
# property of the pattern rather than of the engine's backtracking.
#
# The table still ENDS somewhere, and `test_the_served_count_is_spellable_by_this_gate`
# is what makes that ending loud instead of silent: the day the surface outgrows the
# table, that node goes red and names the word to add.
_SPELLED = "|".join(sorted(WORDS, key=lambda w: (-len(w), w)))

#: A count of tools immediately preceded by a verb that makes it a claim about
#: what a server answers. Deliberately narrow — see the module docstring.
#
# `answers?...with` / `answered...with` allow up to 20 chars between the verb and "with"
# (same bound already used below for `surface`). Widened 2026-09-06 (register item (g),
# served-tools: dated — the surface was ten then): `docs/roadmap-toolbox.md` row 8 said
# "both launchers answer `tools/list` with ten tools" and the old `answers? with` /
# `answered with` alternatives required the two words adjacent, so a backticked token
# between them made the whole sentence invisible to this gate — the row outlived the
# tenth tool unseen until it was read by hand.
CLAIM = re.compile(
    r"(?:serves?|serving|served|answers?[^.\n]{0,20}with|answered[^.\n]{0,20}with|registers?|registered"
    r"|exactly|surface[^.\n]{0,20}"
    # "the same N tools" / "of the N [served] tools": a count that names the whole served
    # surface by reference to it rather than with a verb. Widened 2026-08-27 after two
    # records outlived the ninth tool unseen (served-tools: dated — the surface was nine):
    # `serves the same eight tools` and `one of the eight served tools`; the widened form
    # went red on six lines, this comment's included, before any of them was fixed.
    r"|the same|of the)\s+"
    # `-tool` (hyphenated singular) OR `tools`. Widened again 2026-08-28 after the two
    # memory-CLI module headers outlived the ninth tool (served-tools: dated — they said
    # "the seven-tool surface", which is as much a count of the served surface as "seven
    # tools" is; the widened form went red on both before either was fixed). Bare
    # singular `tool` stays OUT: "17 of the 18 tool-argument failures" is not a count.
    rf"({_SPELLED}|\d+)(?:-tool|[-\s]+(?:served[-\s]+)?tools)\b"
    # And the noun-first form with no verb at all: "the N-tool surface".
    rf"|\b({_SPELLED}|\d+)-tool\s+surface\b",
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


def _require_node_build() -> None:
    """Refuse a Node-launcher probe when the build it needs is not there, and say which.

    THIS IS NOT IN `_served`, and review found out why: `_served` is also how the PYTHON
    launcher is asked, and `test_every_stated_tool_count_matches_what_is_served` needs
    nothing from `runtime-ts/dist/`. With the check inside the helper, a fresh clone or a
    worktree failed a CPython-only test with a message about a Node artefact it never uses.

    `runtime-ts/dist/` is gitignored build output, so it is absent in a fresh clone, in a
    worktree, and in any run before `npm run build`. The launcher's own "cannot load the Node
    build" message goes to STDERR, which `stdio_client` does not surface — what the test
    reported instead was `MCPError(-32000, 'Connection closed')`, which reads like a protocol
    fault and sends the reader to the server.
    """
    dist = REPO / "runtime-ts" / "dist" / "cli.js"
    if not dist.exists():
        raise AssertionError(
            f"the Node build is absent at {dist}, so the launcher exits before it speaks MCP.\n"
            "  runtime-ts/dist/ is gitignored build output; a fresh clone, a worktree and a\n"
            "  job that never runs npm all lack it.\n"
            "  Fix: npm ci --prefix runtime-ts && npm run build --prefix runtime-ts"
        )


def _served(command: str, args: list[str] | None = None) -> list[str]:
    return asyncio.run(_served_names(command, args or []))


# --------------------------------------------------------------- the live surface

_POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "PRICED: `tools/bantamkit-mcp` is `#!/bin/sh` and Windows has no POSIX shell "
        "to run it — RB-P101, an open item with its own job. THE SENTENCE THAT USED TO "
        "FOLLOW THIS ONE — 'The Node launcher below is asked on every platform' — WAS "
        "FALSE: `tools/bantamkit-mcp-node` is a POSIX shell script too, and Windows "
        "answers `OSError: [WinError 193] %1 is not a valid Win32 application`. Measured "
        "on the first Windows CI run in weeks, 2026-09-05. Both launchers are POSIX-only "
        "until one of them gets a `.cmd`."
    ),
)


@_POSIX_ONLY
def test_both_launchers_serve_the_same_tools() -> None:
    """The parity half. A count that drifted on one side only dies here."""
    python_side = _served(str(REPO / "tools" / "bantamkit-mcp"))
    _require_node_build()
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
            token = (match.group(1) or match.group(2)).lower()
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


@windows_cannot_construct(
    because=(
        "`tools/bantamkit-mcp-node` is a POSIX shell script and Windows cannot execute one "
        "— measured 2026-09-05, `OSError: [WinError 193] %1 is not a valid Win32 "
        "application`. Its NAME says 'on every platform' and that was aspiration, not "
        "measurement: there is no `.cmd` launcher for either runtime yet"
    ),
    unmeasured=(
        "that the Node launcher serves the same tool count on Windows as it does on POSIX. "
        "Nothing here has ever asked it on Windows, so a Windows-only drift in the served "
        "surface would be invisible until a `.cmd` launcher exists to ask through"
    ),
)
def test_the_node_launcher_serves_the_same_count_on_every_platform() -> None:
    """The half that runs on Windows too, so the matrix is not blind to the port."""
    if shutil.which("node") is None:  # pragma: no cover - node is a hard dependency here
        pytest.skip("node is not on PATH")
    _require_node_build()
    names = _served(str(REPO / "tools" / "bantamkit-mcp-node"))
    assert names, "the Node launcher served no tools at all"


# ------------------------------------------------- the gate's own blind spot, made loud


@_POSIX_ONLY
def test_the_served_count_is_spellable_by_this_gate() -> None:
    """The number of tools served must be a word this gate can READ, or the gate is blind.

    THIS IS THE HOLE J45-11 FELL INTO AND PATCHED WITHOUT CLOSING. `WORDS` stopped at
    "twelve"; the thirteenth tool landed; and every "thirteen tools" record in the tree
    was INVISIBLE to `test_every_stated_tool_count_matches_what_is_served` rather than
    red. Nothing failed. J45-11 found it by hand, added "thirteen", and left the table
    ending one tool further out — so the fourteenth tool would have repeated it exactly.
    Measured before this node existed (2026-09-07, review J45-12). The widened `CLAIM`
    went RED on the second line below the moment it was widened, which is this change's
    own non-vacuity proof — so the marker underneath is load-bearing, not decoration.

    served-tools: dated — a probe transcript, not today's surface:

        'serves thirteen tools'  -> MATCH, token 'thirteen', WORDS -> 13
        'serves fourteen tools'  -> INVISIBLE, no token at all

    A gate that goes QUIET when the surface grows is worse than no gate, because the
    `checked >= 5` floor in the records node keeps passing on the twelve older claims
    while the new ones are unread. So the ending of the table is asserted against the
    LIVE surface: the day the servers answer a count `WORDS` cannot spell, this node
    goes red and names the word to add.

    It keys on `tools/list` for the module docstring's reason — a constant here would be
    one more copy of the number to go stale, in the direction that hides the defect.
    """
    served = len(_served(str(REPO / "tools" / "bantamkit-mcp")))
    assert served > 0

    spelled = {value: word for word, value in WORDS.items()}
    assert served in spelled, (
        f"the servers answer {served} tools and `WORDS` cannot spell it — every record "
        f"written as a WORD rather than a digit is now invisible to this gate rather "
        f"than checked.\n  Fix: add the word for {served} to `WORDS`; `CLAIM` is built "
        f"from it, so there is nothing else to edit.\n  Table ends at "
        f"{max(WORDS.values())} ({spelled[max(WORDS.values())]})."
    )

    word = spelled[served]
    for line in (
        f"serves {word} tools",
        f"the {word}-tool surface",
        f"serves the same {word} tools",
        f"both launchers answer `tools/list` with {word} tools",
    ):
        match = CLAIM.search(line)
        assert match is not None, f"CLAIM cannot see a live-shaped claim: {line!r}"
        token = (match.group(1) or match.group(2)).lower()
        assert WORDS.get(token) == served, (
            f"{line!r} matched but resolved to {WORDS.get(token)!r}, not {served}"
        )

    # And the pattern must still refuse the number BELOW the surface in the same shapes,
    # or "spellable" would be satisfied by a regex that matched everything.
    stale = spelled.get(served - 1)
    assert stale is not None
    match = CLAIM.search(f"serves {stale} tools")
    assert match is not None
    assert WORDS[(match.group(1) or match.group(2)).lower()] == served - 1


# --------------------------------------------------------------- register item (g)


def test_claim_sees_a_token_between_the_verb_and_with() -> None:
    """Register (g): `docs/roadmap-toolbox.md` row 8 outlived the tenth tool unseen because
    a backticked token sits between "answer" and "with" -- "both launchers answer
    `tools/list` with ten tools" -- and the old `answers? with` / `answered with`
    alternatives require the two words to be adjacent.

    This is a direct, file-scoped regression: it exercises CLAIM against the escaped
    shape itself rather than against whatever `docs/roadmap-toolbox.md` currently says,
    so it stays meaningful even if that file's wording changes later.

    served-tools: dated -- these fixtures quote a past, escaped sentence and are not
    claims about today's surface; the gate's own census counts them (see the module
    docstring), which is exactly why they need the marker rather than an exemption.
    """
    # served-tools: dated
    escaped = "both launchers answer `tools/list` with ten tools since #8 landed"
    match = CLAIM.search(escaped)
    assert match is not None, (
        f"CLAIM does not see the row 8 item (g) escaped shape -- still invisible: {escaped!r}"
    )
    token = (match.group(1) or match.group(2)).lower()
    assert WORDS.get(token) == 10, f"matched the wrong count: {token!r}"

    # The past-tense sibling from the same item's quoted example ("answered ... with").
    # served-tools: dated
    escaped_answered = "the server answered `tools/list` with nine tools"
    match2 = CLAIM.search(escaped_answered)
    assert match2 is not None, (
        f"CLAIM does not see the 'answered <token> with' shape: {escaped_answered!r}"
    )


def test_claim_still_matches_every_previously_caught_shape() -> None:
    """`strictly wider` is the register's word: every alternative CLAIM caught before this
    widening must still match. One sentence per existing alternative, plus the two
    adjacent-verb forms the widening must not lose.
    """
    still_good = [
        "bantamkit serves 13 tools",
        "serving 13 tools, 1 prompt, 2 resource templates",
        "the servers served 13 tools",
        "both launchers answer with thirteen tools",  # adjacent, no token in between
        "the CLI answered with thirteen tools",  # adjacent, past tense
        "registers thirteen tools",
        "registered thirteen tools",
        "the surface is still exactly thirteen tools",
        "serves the same thirteen tools",
        "one of the thirteen served tools",
        "the thirteen-tool surface",
    ]
    for line in still_good:
        assert CLAIM.search(line) is not None, f"widening lost a previously-matched shape: {line!r}"
