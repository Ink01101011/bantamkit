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

   FINDING (J46-25, 2026-09-10): that lookback is exactly three lines, not "nearby" —
   so a marker sitting on the third line above its claim is already at the edge of the
   window, and an edit that inserts one more line between the two (a wrapped sentence
   gaining a clause, a new bullet) silently un-exempts the claim with no diff to the
   marker or the claim themselves. Measured on the tracked tree the same day: four
   markers already sit at that maximum distance (`test_mcpserver.py`,
   `test_status_surface.py`, `test_tool_manifest.py`, and this file's own
   `test_the_served_count_is_spellable_by_this_gate` docstring). Nothing is wrong with
   them today; the risk is that the failure surfaces later, in an unrelated job, as a
   mystery red rather than as a diff anyone reviewed. Prefer putting the marker on the
   claiming line itself (distance zero) when the prose allows it.

THE TWO BLANKET EXEMPTIONS, and why each is principled rather than convenient.

1. The files in `tools/amendguard/ledger.json`'s `amend_only` list. Those files
   cannot be edited in place at all — they are an append-only record of what was
   measured on a date, so EVERY figure in them is dated by construction and a gate
   demanding they track today's surface would be demanding the impossible. The list
   is read from the ledger rather than spelled here, so the two cannot drift.

2. The frozen snapshot directories in `FROZEN_SNAPSHOTS`. Added J55-2b, 2026-09-19,
   after J55-1 (`3619715`) committed `tools/conformance/fixtures/codec-corpus/facts/` —
   fact files copied BYTE FOR BYTE out of this machine's live memory store on a date —
   and two of them turned this gate red for saying 11 where the surface is now 12.
   Both sentences are dated on their face — quoted here from dated records, not
   asserted about today, so each carries the marker on its OWN line at distance zero
   (J46-25: a marker three lines up is one inserted line away from silently lapsing,
   and this paragraph proved it while being written):

     (served-tools: dated) "RULED by the user 2026-09-05 … both advertise the same 11 tools"
     (served-tools: dated) "installed cold from their public registry … both serve 11 tools"

   They were true when they were written and they are not claims about today, which is
   the exact category paragraph 2 above describes — and this gate exists to catch "a
   claim about today that stopped being true", never to correct history.

   It is the amendguard category and then some. An `amend_only` file may at least be
   APPENDED to, so a marker could in principle be written into one. A frozen snapshot
   may not be touched at all: the fixture's README stakes the whole codec suite on
   these being the bytes Python actually wrote — "a codec that round-trips only its
   own output is the failure this suite exists to catch". Editing two of the frozen
   facts to carry `served-tools: dated` would satisfy this gate by falsifying that
   claim and by silently repairing the evidence a differential suite is built on. So
   the snapshot is exempted and the bytes stay as Python wrote them.

   NARROWED J55-5, 2026-09-19, to `codec-corpus/facts/` from the whole of
   `codec-corpus/`. The justification above is that every figure in a byte-for-byte
   snapshot is dated by construction, and only `facts/` is byte-for-byte. `README.md`
   is hand-written and re-edited on every re-freeze, and `index.md` was edited on the
   way in (the excluded rows removed) and again when a fact was dropped; neither is
   bounded by `FROZEN_FACTS`, which counts `facts/*.md` alone, so a tool count written
   into either of them moved no file count and reddened nothing. Zero claims matched in
   those two files at the time, so this changed no verdict — it closed the gap before it
   opened. MEASURED both ways on the day, by appending one line to the fixture's
   `README.md` and running this node against each root in turn: the old root passed
   (`1 passed`), the narrowed root failed and named the file and line. The probe line,
   which is a fabricated claim and not a record of any surface:

     (served-tools: dated) "PROBE (temporary): both launchers serve 3 tools."

   Why this is NOT an unbounded hole. It names a directory rather than the two files
   that happen to trip it today (two is this month's accident; the category is the
   directory), and what may enter that directory is itself gated: adding or removing
   a file there reddens `frozen corpus: the committed fixture is intact` in
   `tools/conformance/suites/codec.mjs` unless `FROZEN_FACTS` moves in the same
   commit. The exemption is therefore as wide as a reviewed, deliberate re-freeze and
   no wider, and `test_the_frozen_snapshot_exemption_names_a_directory_and_stops_there`
   holds it to path boundaries so a `codec-corpus-v2/` sibling is not swept in.

   It is spelled HERE and not added to `amend_only`, deliberately: that list is read
   by amendguard as well, so widening it would subject the fixture to the
   record-vs-pointer rule — a different gate, a different layer, and a second silent
   effect the ledger's own `not_covered` note warns about in as many words.

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

#: Directories holding a FROZEN, byte-for-byte snapshot of something measured on a date.
#
# See blanket exemption 2 in the module docstring for why these are exempt and why the
# rule names a directory rather than the files inside it that trip the gate today.
# Repo-relative, POSIX separators, no trailing slash.
FROZEN_SNAPSHOTS = ("tools/conformance/fixtures/codec-corpus/facts",)


def _is_frozen_snapshot(rel: str) -> bool:
    """Is this repo-relative path inside (or equal to) a frozen snapshot directory?

    Path boundaries, not string prefixes: `codec-corpus-v2/x.md` and `codec-corpus.md`
    both start with an exempt directory's spelling and neither is inside it.
    """
    return any(rel == root or rel.startswith(f"{root}/") for root in FROZEN_SNAPSHOTS)


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
    exempt_by_snapshot = 0

    for path in _tracked_text_files():
        rel = path.relative_to(REPO).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        ledgered = any(Path(rel).match(glob) for glob in exempt_globs)
        frozen = _is_frozen_snapshot(rel)
        for number, line in enumerate(lines, start=1):
            match = CLAIM.search(line)
            if match is None:
                continue
            if ledgered:
                exempt_by_ledger += 1
                continue
            if frozen:
                exempt_by_snapshot += 1
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
        f"(ledger-exempt {exempt_by_ledger}, marker-exempt {exempt_by_marker}, "
        f"snapshot-exempt {exempt_by_snapshot})"
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
        "bantamkit serves 14 tools",
        "serving 14 tools, 1 prompt, 2 resource templates",
        "the servers served 14 tools",
        "both launchers answer with fourteen tools",  # adjacent, no token in between
        "the CLI answered with fourteen tools",  # adjacent, past tense
        "registers fourteen tools",
        "registered fourteen tools",
        "the surface is still exactly fourteen tools",
        "serves the same fourteen tools",
        "one of the fourteen served tools",
        "the fourteen-tool surface",
    ]
    for line in still_good:
        assert CLAIM.search(line) is not None, f"widening lost a previously-matched shape: {line!r}"


# ------------------------------------------- the second blanket exemption, bounded


def test_the_frozen_snapshot_exemption_names_a_directory_and_stops_there() -> None:
    """The frozen-snapshot exemption must be a DIRECTORY rule, and must not leak past it.

    J55-2b added the second blanket exemption. The failure mode a two-filename exemption
    has is that it is spelled from today's accident: two of the frozen facts happen to
    state a count. The third one to do so — the next time the corpus is re-frozen — would
    be red with nobody having changed the gate's reasoning. So the rule names the
    directory, and this node is what keeps it a directory rule.

    The opposite failure is a prefix match that is not a path match: a future
    `codec-corpus-v2/` or `codec-corpus.md` sitting beside the snapshot would be silently
    exempt for no reason at all. Hence the sibling assertions below.
    """
    assert FROZEN_SNAPSHOTS, "an empty exemption list would make every assertion here vacuous"

    for rel in FROZEN_SNAPSHOTS:
        assert (REPO / rel).is_dir(), (
            f"{rel} is exempted as a frozen snapshot directory but is not a directory — "
            "an exemption naming nothing is a hole with no subject"
        )
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", rel],
            cwd=REPO,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        assert tracked.strip("\0"), (
            f"{rel} is exempted but git tracks nothing under it, so the exemption covers "
            "no file this gate would ever have scanned"
        )

    inside = f"{FROZEN_SNAPSHOTS[0]}/facts/some-fact.md"
    assert _is_frozen_snapshot(inside), f"the directory rule does not cover {inside!r}"
    assert _is_frozen_snapshot(FROZEN_SNAPSHOTS[0]), "the directory itself is not covered"

    for outside in (
        f"{FROZEN_SNAPSHOTS[0]}-v2/facts/some-fact.md",
        f"{FROZEN_SNAPSHOTS[0]}.md",
        "docs/status.md",
        "runtime-py/tests/test_served_tool_count_records.py",
    ):
        assert not _is_frozen_snapshot(outside), (
            f"the exemption reaches {outside!r}, which is not inside a frozen snapshot"
        )
