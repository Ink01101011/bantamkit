"""The real-pair tripwire, and an honest account of the half of it CI cannot run.

READ THIS BEFORE TRUSTING A GREEN HERE. This file is deliberately split in two, and the
two halves buy different things:

  LOCAL-ONLY (one node, `test_the_two_real_memory_stores_have_not_drifted_apart`).
      It compares the two stores that actually exist on the developer's machine. It
      CANNOT run on a CI runner and it is not a defect that it does not: `.bantamkit/
      memory/` is gitignored (`.gitignore:10`, and `git ls-files .bantamkit` returns 0
      files, measured 2026-08-22), and `~/.claude/projects/<slug>/memory` is a per-user
      directory that no checkout produces. A fresh clone therefore has neither root, so
      this node skips there, and A TEST THAT SKIPS IS NOT A GATE. Its entire value is
      that it goes red on THIS machine, on the next run after the two stores drift.

  CI-REACHABLE (the rest of this file, plus all of `test_memory_divergence.py`).
      Everything the local-only node depends on is pinned over synthetic fixtures that
      a runner can build: the comparison logic and `store_availability()` live in
      `test_memory_divergence.py`, and this file pins `_precondition()` -- the branch
      that decides skip-versus-fail -- because that branch is written HERE and MS1's
      suite therefore does not reach it. Without those nodes the skip-versus-fail
      decision would be code that only ever executes on one laptop.

The non-vacuity of the comparison is proven by the CI-reachable half. The local-only
node inherits it; it does not establish it.

WHY THE PAIR DRIFTS AT ALL, which is the thing that makes this node worth its keep. The
two stores are keyed on DIFFERENT THINGS. The bantamkit store is per-REPO
(`<repo>/.bantamkit/memory`, one for every worktree of this checkout); the native store
is per-SESSION-LAUNCH-CWD (`~/.claude/projects/<slug>/memory`, a different slug for every
directory a session was started in). So a second session working a sibling worktree
writes its facts into the SAME bantamkit store and a DIFFERENT native store, and the pair
diverges without anybody editing memory by hand. That is not hypothetical: it happened
during the run that wrote this file. MS2 measured the pair clean at 64=64 at 23:35 on
2026-08-22, and by 23:50 a concurrent job had saved
`public-install-is-pure-node-by-ruling` through the shared MCP -- 65 vs 64, and
`find ~/.claude/projects -name 'public-install-is-pure-node-by-ruling.md'` found it in no
native store at all. Fifteen minutes.

The consequence, stated so the next reader is not ambushed by it: THIS NODE'S OUTCOME IS A
FUNCTION OF MACHINE STATE, NOT OF THE DIFF. A red here is usually not the change you are
holding. Read the names it prints before you touch anything.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bantamkit.memory.divergence import (
    ABSENT,
    PRESENT,
    UNREADABLE,
    StoreAvailability,
    bantamkit_store_root,
    compare_stores,
    native_store_root,
    store_availability,
)

RECONCILE = """
This node compares the two real memory stores on this machine, so a red here is a
statement about the machine and not necessarily about your branch. To resolve:
  * "only in A" -> copy the named fact into the native store in native shape.
  * "only in B" -> save it through the bantamkit MCP so its writer owns the file.
  * "body differs" -> resolve BY HAND from the two bodies. Never by mtime: recall()
    rewrites last_recalled on every hit, so the stamps record who READ a fact.
  * "description differs" -> the knowledge already agrees; reconcile the recall key.
  * "unparseable" -> go and open the file that is named.
Rerun outside pytest with:
  PYTHONPATH=runtime-py/src .venv/bin/python -c \\
    "from bantamkit.memory.divergence import compare_stores; print(compare_stores().explain())"
"""


def _precondition(*availabilities: StoreAvailability) -> tuple[str, str]:
    """Can the real-pair comparison run here? Returns ("run"|"skip"|"fail", reason).

    Pure, so CI can execute every branch of it against hand-built inputs.

    UNREADABLE is checked BEFORE ABSENT and outranks it, and the ordering is the whole
    design. "There is no store here" means this machine is not the one the gate is for,
    which is a legitimate skip. "There is something here and I cannot read it" is a
    FINDING -- a file where a directory belongs, a dangling symlink, a directory that
    will not list -- and folding that into the skip would let a real breakage buy itself
    a green. If one root is absent and the other is broken, the breakage is what gets
    reported.
    """
    broken = [a for a in availabilities if a.state == UNREADABLE]
    if broken:
        return "fail", "; ".join(a.reason for a in broken)
    missing = [a for a in availabilities if a.state == ABSENT]
    if missing:
        return "skip", "; ".join(a.reason for a in missing)
    return "run", ""


# ---- LOCAL-ONLY: the tripwire. Skips on CI, by construction, and says so. ----


def test_the_two_real_memory_stores_have_not_drifted_apart():
    """The two stores on THIS machine hold the same facts.

    Not weakened to a warning: the point of a tripwire is that somebody has to look.
    """
    bantam = bantamkit_store_root()
    native = native_store_root()
    verdict, reason = _precondition(store_availability(bantam), store_availability(native))

    if verdict == "fail":
        pytest.fail(
            "a memory store root exists on this machine and cannot be read. That is a "
            "finding, not an absence, so this node does not skip it:\n  " + reason
        )
    if verdict == "skip":
        pytest.skip(
            "no two real memory stores on this machine, so there is nothing for the "
            "cross-store tripwire to compare and it FAILS TO MEASURE whether they agree. "
            "Expected on any CI runner: .bantamkit/memory/ is gitignored and "
            "~/.claude/ is not part of a checkout. The comparison logic itself is "
            "covered by tests/test_memory_divergence.py, which needs neither. Reason: "
            + reason
        )

    report = compare_stores(bantam, native)
    assert report.clean, "\n" + report.explain() + RECONCILE


# ---- CI-REACHABLE: the skip-versus-fail branch written above ----


def test_two_present_stores_are_compared():
    assert _precondition(
        StoreAvailability("/a", PRESENT, ""), StoreAvailability("/b", PRESENT, "")
    ) == ("run", "")


def test_an_absent_store_is_a_skip_and_carries_its_reason():
    verdict, reason = _precondition(
        StoreAvailability("/a", PRESENT, ""),
        StoreAvailability("/b", ABSENT, "no directory at /b"),
    )
    assert verdict == "skip"
    assert "/b" in reason


def test_an_unreadable_store_is_a_failure_not_a_skip():
    """The distinction this whole node exists to make."""
    verdict, reason = _precondition(
        StoreAvailability("/a", PRESENT, ""),
        StoreAvailability("/b", UNREADABLE, "/b exists but is not a directory"),
    )
    assert verdict == "fail"
    assert "not a directory" in reason


def test_unreadable_outranks_absent_when_both_are_wrong():
    """Otherwise a broken store hides behind a missing one and the run goes green."""
    verdict, reason = _precondition(
        StoreAvailability("/a", ABSENT, "no directory at /a"),
        StoreAvailability("/b", UNREADABLE, "/b is a directory that cannot be listed"),
    )
    assert verdict == "fail"
    assert "cannot be listed" in reason
    assert "no directory at /a" not in reason


def test_the_tripwire_reddens_on_a_pair_that_has_drifted(tmp_path):
    """The local-only node's assertion, run against a synthetic pair, so CI proves it
    is capable of red without needing either real root.

    This is the node that stops the tripwire from being a green that means nothing.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "facts").mkdir(parents=True)
    b.mkdir()
    front_a = "---\nname: shared\ndescription: d\ntype: project\n---\n\n"
    front_b = "---\nname: shared\ndescription: d\nmetadata:\n  type: project\n---\n\n"
    (a / "facts" / "shared.md").write_text(front_a + "agreed body\n", encoding="utf-8")
    (b / "shared.md").write_text(front_b + "agreed body\n", encoding="utf-8")
    (a / "facts" / "only-a.md").write_text(
        "---\nname: only-a\ndescription: d\ntype: project\n---\n\nx\n", encoding="utf-8"
    )

    verdict, _ = _precondition(store_availability(a), store_availability(b))
    assert verdict == "run"

    report = compare_stores(a, b)
    assert report.clean is False
    # The failure text a reader would actually get names the fact, not just a count.
    message = report.explain() + RECONCILE
    assert "only-a" in message
    assert "only in A (1)" in message

    (b / "only-a.md").write_text(
        "---\nname: only-a\ndescription: d\nmetadata:\n  type: project\n---\n\nx\n",
        encoding="utf-8",
    )
    assert compare_stores(a, b).clean is True


def test_a_file_where_a_store_root_belongs_is_unreadable_not_absent(tmp_path):
    """End to end through the real probe, not just the pure branch."""
    impostor = tmp_path / "memory"
    impostor.write_text("this is not a store\n", encoding="utf-8")

    verdict, reason = _precondition(store_availability(impostor))

    assert verdict == "fail"
    assert "is not a directory" in reason


def test_a_root_that_was_never_created_is_absent(tmp_path):
    verdict, reason = _precondition(store_availability(tmp_path / "never-made"))
    assert verdict == "skip"
    assert "no directory at" in reason


def test_a_root_that_denies_listing_is_unreadable_not_absent(tmp_path):
    """Deliberately NOT a `windows_cannot_construct` skipif, and the reason is a ledger.

    `_WINDOWS_ONLY_SKIPS` in test_criticreplay.py pins the population of Windows-only
    skips at THREE and calls itself "every node in the suite that a Windows runner does
    not execute" -- but `_windows_only_skip_conditions()` only scans two named modules,
    so a fourth marked skip added from this file would have made that docstring false
    without reddening anything. Verified by running the suite with the mark in place:
    1792 passed, and the register node stayed green at three.

    So the platform question is MEASURED here instead of asserted by a mark: the node
    tries to construct the scenario and reports honestly when it cannot. That works on
    Windows (where chmod does not restrict a directory listing) and under any uid that
    bypasses the mode bits, and it leaves the register's population correct at three.
    """
    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, 0o000)
    try:
        try:
            list(locked.iterdir())
        except OSError:
            constructed = True
        else:
            constructed = False
        if constructed:
            verdict, reason = _precondition(store_availability(locked))
    finally:
        os.chmod(locked, 0o700)

    if not constructed:
        pytest.skip(
            "this platform lets a 0o000 directory be listed (Windows, or a uid that "
            "bypasses the mode bits), so the scenario cannot be constructed and this "
            "run FAILS TO MEASURE that a store root which exists but denies listing is "
            "reported as a finding rather than as an absent store. The other two "
            "unreadable shapes -- a file where a directory belongs, and a dangling "
            "symlink -- are constructible everywhere and are pinned by their own nodes."
        )
    assert verdict == "fail"
    assert "cannot be listed" in reason


# ---- END OF THE SCANNED REGION ----
#
# The guard below reads this file and rejects a real-root call anywhere between the
# CI-REACHABLE marker and this line. It has to stop here, because the guard necessarily
# spells out the very names it is looking for.


def test_the_local_only_node_is_the_only_one_here_that_touches_a_real_root():
    """The split claimed in this module's docstring, checked rather than asserted in prose.

    A CI-reachable node that quietly reached for `~/.claude` would make this file's
    green depend on the machine it ran on, which is exactly the thing the split exists
    to prevent.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    scanned = source.split("# ---- CI-REACHABLE", 1)[1].split("# ---- END OF THE SCANNED", 1)[0]
    # Non-vacuity: the region has to actually contain the nodes, or this guard passes by
    # scanning nothing.
    assert scanned.count("\ndef test_") >= 5
    for forbidden in ("bantamkit_store_root(", "native_store_root("):
        assert forbidden not in scanned, f"a CI-reachable node in this file calls {forbidden}"
