"""The real-pair tripwire, and an honest account of the half of it CI cannot run.

READ THIS BEFORE TRUSTING A GREEN HERE. This file is deliberately split in two, and the
two halves buy different things:

  LOCAL-ONLY (one node, `test_the_two_real_memory_stores_have_not_drifted_apart`),
  MARKED `realpair` AND DESELECTED FROM THE DEFAULT RUN.
      It compares the two stores that actually exist on the developer's machine. It
      CANNOT run on a CI runner and it is not a defect that it does not: `.bantamkit/
      memory/` is gitignored (`.gitignore:10`, and `git ls-files .bantamkit` returns 0
      files, measured 2026-08-22), and `~/.claude/projects/<slug>/memory` is a per-user
      directory that no checkout produces. A fresh clone therefore has neither root, so
      this node skips there, and A TEST THAT SKIPS IS NOT A GATE. Its entire value is
      that it goes red on THIS machine, on the next run after the two stores drift.

      It is deselected by default because its outcome is a function of machine state and
      not of the diff -- see the `markers` note in `runtime-py/pyproject.toml` for the
      measurement behind that, and note that DESELECTED IS NOT GREEN: pytest reports it
      as `1 deselected` and asserts nothing about the stores. RUN IT WITH:

          PYTHONPATH=runtime-py/src .venv/bin/python -m pytest runtime-py/tests -m realpair

      The memory job and the shift closeout own that command. A green DEFAULT suite now
      says nothing whatsoever about whether the two memory stores agree.

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
mechanism is WRITER ASYMMETRY: THE TWO STORES HAVE NO WRITER IN COMMON. No source file
under `runtime-py/` writes anything to `~/.claude` (measured 2026-08-22), so the
bantamkit MCP writes only `<repo>/.bantamkit/memory` and Claude Code's auto-memory writes
only the native store. EVERY `memory_save` therefore diverges the pair by +1 until a
human mirrors it by hand -- and this program's mandated workflow is one job per context,
write memory, clear. That is not hypothetical: it happened during the run that wrote this
file. MS2 measured the pair clean at 64=64 at 23:35 on 2026-08-22, and by 23:50 a
concurrent job had saved `public-install-is-pure-node-by-ruling` through the shared MCP
-- 65 vs 64. Fifteen minutes.

AN EARLIER VERSION OF THIS PARAGRAPH BLAMED KEYING, and MS4 refuted it from the evidence
already in front of it. The claim was that the bantamkit store is per-REPO while the
native store is per-SESSION-LAUNCH-CWD, so a session in a sibling worktree splits the
pair. Keying IS real -- `~/.claude/projects/<slug>` is named for the launch cwd, and
`native_store_root()` reconstructs the slug for exactly that reason -- but it is not what
moved this pair and it has never moved it: no bantamkit WORKTREE has a native store at
all, and the five scratchpad probe slugs are EMPTY. MS3's own `find`, which found
`public-install-is-pure-node-by-ruling.md` in NO native store rather than in a second
one, is the result that says so. Keying is a second mechanism, currently unexercised;
asymmetry is the one firing. The commit message that carried the wrong version is
history and stays wrong; this is the copy that gets read.

The consequence, stated so the next reader is not ambushed by it: THIS NODE'S OUTCOME IS A
FUNCTION OF MACHINE STATE, NOT OF THE DIFF. A red here is usually not the change you are
holding. Read the names it prints before you touch anything.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import REAL_PAIR_MARK, _no_ambient_memory_pin

from bantamkit.memory.divergence import (
    ABSENT,
    PRESENT,
    UNREADABLE,
    StoreAvailability,
    bantamkit_store_availability,
    compare_stores,
    native_store_root,
    store_availability,
    unaccounted_writer_env,
)
from bantamkit.memory.layers import MEMORY_DIR_ENV

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


# ---- LOCAL-ONLY: the tripwire. Deselected by default; skips on CI; says so in both. ----


@pytest.mark.realpair
def test_the_two_real_memory_stores_have_not_drifted_apart():
    """The two stores on THIS machine hold the same facts.

    Not weakened to a warning: the point of a tripwire is that somebody has to look. It
    gave up its seat in the default run instead of giving up its teeth -- see the module
    docstring and the `markers` note in `runtime-py/pyproject.toml`.
    """
    # Before comparing anything: is this resolver even looking where the writer writes?
    # The population register in memory/divergence.py is the CI-reachable half of this
    # question and would have reddened the default run already -- but a `-m realpair`
    # run DESELECTS that node, so the one command that reaches this node has to ask for
    # itself. Otherwise the opt-in run is the one place a wrong store can answer.
    unaccounted = unaccounted_writer_env()
    if unaccounted:
        pytest.fail(
            "the memory writer honours "
            + ", ".join(sorted(unaccounted))
            + " and bantamkit_store_root() does not, so this node cannot know it is "
            "reading the store that is actually being written. See ACCOUNTED_WRITER_ENV "
            "in bantamkit/memory/divergence.py."
        )

    # `bantamkit_store_availability()` and not `store_availability(bantamkit_store_root())`:
    # under a pin the resolver can RAISE, and a raise here is a collection-time crash for
    # a situation this file already has a verdict for. It arrives as UNREADABLE, which
    # `_precondition` turns into a fail, because a store the operator named and cannot be
    # read is a finding and never an absence.
    bantam = bantamkit_store_availability()
    native = native_store_root()
    verdict, reason = _precondition(bantam, store_availability(native))

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

    report = compare_stores(Path(bantam.root), native)
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


def test_the_ambient_pin_survives_into_a_realpair_node(monkeypatch, tmp_path):
    """The autouse fixture in conftest.py must not disarm the one node it would disarm.

    `_no_ambient_memory_pin` clears `BANTAMKIT_MEMORY_DIR` for every node in this suite,
    which is right for every node that asks a question about the code and wrong for the
    one node that asks a question about the operator's machine: under a pin, the store
    the writer uses IS the pinned one, and comparing the abandoned repo store instead
    reports clean about a store nobody writes.

    The fixture function is CALLED here rather than read, because the arrangement that
    matters is what it DOES with a marked node, and a source scan would pass over a
    fixture that had been renamed out from under the marker.
    """
    pin = tmp_path / "pinned"
    pin.mkdir()
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pin))
    body = _no_ambient_memory_pin.__wrapped__

    marked = SimpleNamespace(keywords={REAL_PAIR_MARK: True, "some_other_key": True})
    body(marked, monkeypatch)
    assert os.environ.get(MEMORY_DIR_ENV) == str(pin), (
        "a realpair node was stripped of the operator's pin, so the tripwire would "
        "compare a store nobody is writing to"
    )

    unmarked = SimpleNamespace(keywords={"test_something_else": True})
    body(unmarked, monkeypatch)
    assert MEMORY_DIR_ENV not in os.environ, (
        "an ordinary node kept the operator's ambient pin, so its verdict can come from "
        "the environment instead of from the code"
    )


OPT_IN_COMMAND = (
    "PYTHONPATH=runtime-py/src .venv/bin/python -m pytest runtime-py/tests -m realpair"
)


def test_the_realpair_arrangement_is_the_one_documented_here(tmp_path):
    """The deselection, and the command that undoes it, read out of the config itself.

    Three things have to stay true together or the local-only node becomes a node that
    runs NOWHERE, which is worse than the red it was moved out of the way of: the marker
    has to be registered, the default run has to deselect it, and the registered
    description has to carry the exact command that selects it. The last one is what
    makes the command discoverable from the code -- `pytest --markers` prints it, and no
    reader has to have seen the brief or the commit that made this choice.
    """
    config = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    options = config["tool"]["pytest"]["ini_options"]

    registered = [m for m in options.get("markers", []) if m.startswith("realpair:")]
    assert len(registered) == 1, "the realpair marker is not registered in pyproject.toml"
    assert OPT_IN_COMMAND in registered[0], (
        "the registered marker description must spell the command that runs the node, "
        "or the only way to find it is to have read the commit that hid it"
    )
    assert options.get("addopts") == ["-m", "not realpair"], (
        "the default run no longer deselects the realpair node; either it is back in "
        "every unrelated unit's suite, or the deselection moved somewhere this cannot see"
    )


def test_exactly_one_node_in_this_file_is_deselected_by_default():
    """The mark is a seat given up, so the population that gave one up is pinned.

    Same reasoning as `_WINDOWS_ONLY_SKIPS`: a second node acquiring this mark would
    leave the default suite quieter with nothing turning red to say so.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    decorated = re.findall(r"^@pytest\.mark\.realpair\ndef (\w+)", source, re.M)

    assert decorated == ["test_the_two_real_memory_stores_have_not_drifted_apart"]


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
    for forbidden in (
        "bantamkit_store_root(",
        "native_store_root(",
        "bantamkit_store_availability(",
    ):
        assert forbidden not in scanned, f"a CI-reachable node in this file calls {forbidden}"


def test_a_pin_the_writer_cannot_use_reaches_the_precondition_as_a_failure(monkeypatch, tmp_path):
    """The junction the local-only node relies on, run where CI can reach it.

    It lives BELOW the scanned region only because it must name
    `bantamkit_store_availability(`, which the guard above forbids inside that region.
    It reads no real root all the same, and not by luck: the writer consults the pin
    before it walks anywhere, so a pin it refuses raises before any store on this machine
    is touched. Set a pin CI can also set, and the answer is the same everywhere.

    Three unusable pins, one verdict. Without this the crash would surface as an error at
    collection, in a file whose whole design is that a store it cannot read is a REPORTED
    finding.
    """
    for bad, expected in (
        ("relative/store", "absolute path"),
        (str(tmp_path / "never-created"), "unreachable"),
        (str(tmp_path / "a-file.md"), "not a directory"),
    ):
        (tmp_path / "a-file.md").write_text("not a store\n", encoding="utf-8")
        monkeypatch.setenv(MEMORY_DIR_ENV, bad)

        availability = bantamkit_store_availability()
        verdict, reason = _precondition(availability, StoreAvailability("/b", PRESENT, ""))

        assert availability.state == UNREADABLE, bad
        assert verdict == "fail", bad
        assert expected in reason, (bad, reason)
        assert bad in reason, "the reason must name the pin the operator actually set"
