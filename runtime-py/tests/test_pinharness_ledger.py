"""The contract ledger's anchors must still exist in the source they name.

WHY THIS FILE EXISTS, AND IT IS NOT HYPOTHETICAL. `tools/pinharness/pinned.py` measures
what fraction of the exit-status contract is PINNED — a claim is pinned when a mutation
that makes it false turns a node it NAMED red. It mutates by finding an `anchor` string
in a source file and replacing it. When the source moves, the anchor stops matching and
`assert_anchors_apply` refuses the whole sweep before it starts.

That happened. `W13`, merged in `#64`, replaced `criticreplay`'s two `except` clauses with
one clause plus `_stdout_reader_is_gone`. `B01` and `B02` anchored on the text
`except (OSError, UnicodeEncodeError) as e:` inside the arm that moved, so both matched 0x
and the harness could not run at all:

    MutationError: the ledger is stale before the sweep even starts:
      B01 edit 0: anchor appears 0x in runtime-py/src/bantamkit/criticreplay.py
      B02 edit 0: anchor appears 0x in runtime-py/src/bantamkit/criticreplay.py

**Nothing said so.** No CI job runs anything under `tools/` — `grep -n "tools/"
.github/workflows/ci.yml` returns nothing for all seven programs there — so the instrument
sat dark from the moment `#64` merged until somebody ran it by hand a day later. That is
`RB-P41` one step worse than the shape it names: not "a field program guarded only by CI",
but guarded by nobody.

WHAT THIS FILE DOES AND DELIBERATELY DOES NOT DO. It does NOT run the sweep — that is
~1 minute of pytest per claim, 35 claims, far too slow for every push, and running it here
would make the suite depend on the suite. It checks only the cheap invariant the sweep
asserts first: **every anchor still appears exactly once in the file it names.** That is
the entire failure `#64` caused, it costs milliseconds, and it is the difference between
learning about a dark instrument in a day and learning about it in a quarter.

`pins` is checked the same way and for the same reason: a claim naming a node id that no
longer exists cannot be pinned by it, and the sweep would report `UNPINNED` for a claim it
never actually tested — a false negative that reads exactly like a real one.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "tools" / "pinharness" / "contract-ledger.json"


def _claims():
    return json.loads(LEDGER.read_text(encoding="utf-8"))["claims"]


def test_the_ledger_is_where_the_harness_looks_for_it():
    """A moved ledger is the same outage with a different message."""
    assert LEDGER.is_file(), f"{LEDGER} is gone; tools/pinharness/pinned.py takes it by path"
    claims = _claims()
    assert claims, "an empty ledger measures nothing and would report 0/0 = 100%"


def test_every_anchor_still_appears_exactly_once_in_the_file_it_names():
    """The invariant `#64` broke. Exactly once, not at least once.

    A count of 0 is the stale anchor that stops the sweep. A count of 2+ is worse and
    quieter: `str.replace` would rewrite BOTH sites, so the mutation under test would no
    longer be the mutation the claim describes, and the verdict would be about something
    nobody wrote down.
    """
    stale = []
    for c in _claims():
        anchor = c.get("anchor")
        if anchor is None:
            continue
        path = REPO_ROOT / c["path"]
        if not path.is_file():
            stale.append(f"{c['cid']}: {c['path']} does not exist")
            continue
        n = path.read_text(encoding="utf-8").count(anchor)
        if n != 1:
            stale.append(f"{c['cid']}: anchor appears {n}x in {c['path']}")
    assert not stale, (
        "the pinharness ledger is stale and its sweep would refuse to run:\n  "
        + "\n  ".join(stale)
        + "\n\nRe-anchor onto the surviving text WITHOUT changing what the mutation does; "
        "see the 2026-08-22 re-anchor of B01/B02 for the shape."
    )


def test_every_claim_names_a_node_prefix_that_the_suite_still_collects():
    """A claim whose `pins` no longer match any node reports UNPINNED for a claim that was
    never tested — a false negative indistinguishable from a real one."""
    collected = set()
    for f in (REPO_ROOT / "runtime-py" / "tests").glob("test_*.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("def test_"):
                collected.add(s[4:].split("(", 1)[0])
    orphans = []
    for c in _claims():
        for pin in c.get("pins") or []:
            if not any(name.startswith(pin) or name == pin for name in collected):
                orphans.append(f"{c['cid']}: pins {pin!r}, which matches no test function")
    assert not orphans, "\n  ".join(["the ledger pins nodes that no longer exist:"] + orphans)
