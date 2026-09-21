"""The update record: where it is read from, what the five states are, and what it never does.

EVERY STATE HERE IS CONSTRUCTED BY WRITING A RECORD. Both installs on the machine this was
written on are 0.35.1, so there is no naturally stale install to point at, and a test that
waited for one would be a test that passes on a Tuesday. Nothing below reaches the network
either — there is nothing in `updatecheck` that could, and one node asserts exactly that off
the parsed source rather than off this sentence.

THE HOME IS REDIRECTED IN EVERY NODE THAT TOUCHES A PATH. `updatecheck` derives its path from
`_home()` and nothing else — the same seam `hostinstall._home` is — so pointing that at
`tmp_path` makes the redirection total and no node here can read, or notice, the operator's
own record.

THE VERSION PAIRS ARE THE AWKWARD ONES ON PURPOSE. `0.35.1` against `0.36.0` is the pair every
implementation gets right, including a wrong one, so it is the floor and not the proof. The
pair that decides anything is `0.9.0` against `0.10.0`, where a string compare says the index
is BEHIND and would print `ahead` over a genuinely stale install.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from bantamkit import selfupdate, updatecheck
from bantamkit.updatecheck import (
    SOURCE_ABSENT,
    SOURCE_RECORD,
    SOURCE_UNREADABLE,
    STATE_AHEAD,
    STATE_AVAILABLE,
    STATE_CURRENT,
    STATE_NEVER,
    STATE_UNREADABLE,
)

SRC = Path(updatecheck.__file__)

CHECKED_AT = "2026-09-19T21:04:11Z"
DATE = "2026-09-19"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home nobody lives in, with the `.bantamkit` a real machine would already have."""
    root = tmp_path / "home"
    (root / ".bantamkit").mkdir(parents=True)
    monkeypatch.setattr(updatecheck, "_home", lambda: root)
    return root


def write_record(home: Path, text: str) -> Path:
    """The record, exactly as given — including the shapes no writer would produce."""
    path = home / ".bantamkit" / "update-check.json"
    path.write_text(text, encoding="utf-8")
    return path


def record(npm: str = "0.36.0", pypi: str = "0.36.0", checked_at: str = CHECKED_AT) -> str:
    """The well-formed record from the spec: both registries, because they are two."""
    return json.dumps(
        {
            "checked_at": checked_at,
            "npm": {"package": "bantamkit-mcp", "latest": npm},
            "pypi": {"distribution": "bantamkit", "latest": pypi},
        }
    )


# --- the five sentences ------------------------------------------------------------------
# Golden bytes, spelled out here rather than imported and compared to themselves. `runtime-ts`
# copies the constants; this node is what notices if someone edits one on one side only,
# before the conformance suite gets a chance to.


def test_the_five_sentences_are_these_bytes():
    assert updatecheck.UPDATE_NEVER == "update: never checked."
    assert updatecheck.UPDATE_AVAILABLE == (
        "update: {program} {installed} is running; the package index has {latest} — run "
        "`{program} --update`, then reconnect the host."
    )
    assert updatecheck.UPDATE_CURRENT == "update: {program} {installed} is current as of {date}."
    assert updatecheck.UPDATE_AHEAD == (
        "update: {program} {installed} is ahead of the package index, which has {latest}."
    )
    assert updatecheck.UPDATE_UNREADABLE == "update: the update record could not be read."


def test_the_sentences_name_the_command_and_never_a_package():
    """`bantamkit` is the PyPI distribution and `bantamkit-mcp` is the npm package.

    Only the COMMAND is the same word on both sides, so only the command can appear in a
    sentence `runtime-ts` copies verbatim. A sentence naming a distribution would be one the
    port has to change, and a changed sentence is a divergence nobody declared.
    """
    assert updatecheck.PROGRAM == "bantamkit-mcp"
    assert updatecheck.PROGRAM is selfupdate.PROGRAM
    for sentence in (
        updatecheck.UPDATE_NEVER,
        updatecheck.UPDATE_AVAILABLE,
        updatecheck.UPDATE_CURRENT,
        updatecheck.UPDATE_AHEAD,
        updatecheck.UPDATE_UNREADABLE,
    ):
        rendered = sentence.format(
            program=updatecheck.PROGRAM, installed="0.35.1", latest="0.36.0", date=DATE
        )
        assert "bantamkit-mcp" in rendered or "bantamkit" not in rendered
        assert selfupdate.DISTRIBUTION not in rendered.replace("bantamkit-mcp", "")


# --- the five states ---------------------------------------------------------------------


def test_no_record_is_never_checked(home):
    status = updatecheck.update_status("0.35.1")
    assert status.state == STATE_NEVER
    assert status.line == "update: never checked."


def test_running_behind_the_index_says_run_update_and_reconnect(home):
    write_record(home, record(pypi="0.36.0"))
    status = updatecheck.update_status("0.35.1")
    assert status.state == STATE_AVAILABLE
    assert status.line == (
        "update: bantamkit-mcp 0.35.1 is running; the package index has 0.36.0 — run "
        "`bantamkit-mcp --update`, then reconnect the host."
    )


def test_running_the_index_version_is_current_as_of_the_recorded_date(home):
    write_record(home, record(pypi="0.35.1"))
    status = updatecheck.update_status("0.35.1")
    assert status.state == STATE_CURRENT
    assert status.line == "update: bantamkit-mcp 0.35.1 is current as of 2026-09-19."


def test_running_ahead_of_the_index_says_so(home):
    write_record(home, record(pypi="0.35.1"))
    status = updatecheck.update_status("0.36.0")
    assert status.state == STATE_AHEAD
    assert status.line == (
        "update: bantamkit-mcp 0.36.0 is ahead of the package index, which has 0.35.1."
    )


def test_a_record_that_is_not_json_is_unreadable(home):
    write_record(home, "<html>captive portal</html>")
    status = updatecheck.update_status("0.35.1")
    assert status.state == STATE_UNREADABLE
    assert status.line == "update: the update record could not be read."


def test_the_ten_ordering_that_a_string_compare_gets_backwards(home):
    """`0.9.0` against `0.10.0`: string order says the index is behind. It is ahead.

    This is the pair `selfupdate._version_key` exists for, and the reason this module imports
    that comparator instead of writing a second one. An implementation that compared strings
    would print `ahead` at a genuinely stale install and the operator would never update.
    """
    write_record(home, record(pypi="0.10.0"))
    assert updatecheck.update_status("0.9.0").state == STATE_AVAILABLE
    write_record(home, record(pypi="0.9.0"))
    assert updatecheck.update_status("0.10.0").state == STATE_AHEAD


def test_padding_makes_an_unpadded_release_agree(home):
    """`0.36` and `0.36.0` are one release on either registry, so they are `current`."""
    write_record(home, record(pypi="0.36"))
    assert updatecheck.update_status("0.36.0").state == STATE_CURRENT


def test_there_is_no_second_comparator():
    """The ordering is `selfupdate.compare_versions` itself, not a copy that agrees today."""
    assert updatecheck.compare_versions is selfupdate.compare_versions
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "compare_versions" not in defined
    assert "_version_key" not in defined


# --- this runtime reads the PyPI key ------------------------------------------------------


def test_python_reads_pypi_and_node_reads_npm(home):
    """The divergence row, pinned: the two keys are asked separately and can disagree.

    A record whose registries disagree is not hypothetical — job56 shipped exactly one (npm
    at a stale dist while PyPI was current). If this reader took whichever key it found
    first, that day's record would have told a Python operator the wrong thing.
    """
    write_record(home, record(npm="0.99.0", pypi="0.35.1"))
    assert updatecheck.KEY == "pypi"
    assert updatecheck.update_status("0.35.1").state == STATE_CURRENT
    assert updatecheck.update_status("0.35.1", key="npm").state == STATE_AVAILABLE


# --- every malformed shape lands in unreadable, and none of them raises --------------------

MALFORMED = {
    "not json at all": "not json at all",
    "empty file": "",
    "whitespace only": "   \n",
    "a json list": "[]",
    "a bare json number": "7",
    "a bare json string": '"0.36.0"',
    "json null": "null",
    "no key for this runtime": json.dumps({"checked_at": CHECKED_AT, "npm": {"latest": "0.36.0"}}),
    "the key is not an object": json.dumps({"checked_at": CHECKED_AT, "pypi": "0.36.0"}),
    "no latest in the key": json.dumps({"checked_at": CHECKED_AT, "pypi": {"dist": "bantamkit"}}),
    "latest is null": json.dumps({"checked_at": CHECKED_AT, "pypi": {"latest": None}}),
    "latest is a number": json.dumps({"checked_at": CHECKED_AT, "pypi": {"latest": 36}}),
    "latest is empty": json.dumps({"checked_at": CHECKED_AT, "pypi": {"latest": ""}}),
    "latest is not a version": json.dumps(
        {"checked_at": CHECKED_AT, "pypi": {"latest": "nightly"}}
    ),
    "latest is v-prefixed": json.dumps({"checked_at": CHECKED_AT, "pypi": {"latest": "v0.36.0"}}),
    "no checked_at": json.dumps({"pypi": {"latest": "0.36.0"}}),
    "checked_at is null": json.dumps({"checked_at": None, "pypi": {"latest": "0.36.0"}}),
    "checked_at is a number": json.dumps({"checked_at": 1758315851, "pypi": {"latest": "0.36.0"}}),
    "checked_at is prose": json.dumps({"checked_at": "yesterday", "pypi": {"latest": "0.36.0"}}),
    "checked_at is a locale date": json.dumps(
        {"checked_at": "19/09/2026", "pypi": {"latest": "0.36.0"}}
    ),
}


@pytest.mark.parametrize("shape", sorted(MALFORMED), ids=sorted(MALFORMED))
def test_every_malformed_shape_is_unreadable_and_nothing_raises(home, shape):
    write_record(home, MALFORMED[shape])
    status = updatecheck.update_status("0.35.1")
    assert status.state == STATE_UNREADABLE
    assert status.line == "update: the update record could not be read."


# --- a UTF-8 BOM -------------------------------------------------------------------------
# NOT A DIVERGENCE, AND THESE NODES ARE WHY. Until J57-5b this module opened the record with
# `encoding="utf-8"`, `json.loads` refused the leading BOM by name, and the record was
# `unreadable` HERE while the port's `TextDecoder` stripped the BOM and answered `available` —
# one file, two answers. What has to be accepted is the three bytes `EF BB BF`, whoever wrote
# them: a record a reader can plainly act on is not a shape it cannot act on. Both sides accept
# it now. The bytes are written as BYTES below, never through an encoder that might add or eat
# one.
#
# AMENDED 2026-09-21 (J62-16). This block used to name PowerShell's `Set-Content`/`Out-File`
# defaults as the source of those bytes. Measured in `mcr.microsoft.com/powershell:latest`,
# PowerShell 7.4.2 writes NO BOM from any of `Set-Content`, `Out-File`, `>` or `Add-Content`;
# only an explicit `-Encoding utf8BOM` produces one. Windows PowerShell 5.1 is UNMEASURED here
# — it needs a Windows kernel this machine does not have. The cases below never depended on the
# writer; see `updatecheck.load_record`'s docstring for the full amendment.

BOM = b"\xef\xbb\xbf"


def write_bytes_record(home: Path, raw: bytes) -> Path:
    """The record as exact bytes — the only way to put a BOM on disk without trusting a codec."""
    path = home / ".bantamkit" / "update-check.json"
    path.write_bytes(raw)
    return path


@pytest.mark.parametrize(
    ("installed", "latest", "state", "line"),
    [
        (
            "0.35.1",
            "0.36.0",
            STATE_AVAILABLE,
            "update: bantamkit-mcp 0.35.1 is running; the package index has 0.36.0 — run "
            "`bantamkit-mcp --update`, then reconnect the host.",
        ),
        (
            "0.35.1",
            "0.35.1",
            STATE_CURRENT,
            "update: bantamkit-mcp 0.35.1 is current as of 2026-09-19.",
        ),
        (
            "0.36.0",
            "0.35.1",
            STATE_AHEAD,
            "update: bantamkit-mcp 0.36.0 is ahead of the package index, which has 0.35.1.",
        ),
    ],
    ids=["available", "current", "ahead"],
)
def test_a_record_with_a_utf_8_bom_lands_where_the_same_record_without_one_does(
    home, installed, latest, state, line
):
    """Three states, one record, with and without the BOM: the BOM may move neither."""
    body = record(pypi=latest)
    write_bytes_record(home, BOM + body.encode("utf-8"))
    with_bom = updatecheck.update_status(installed)
    assert (with_bom.state, with_bom.line) == (state, line)

    write_bytes_record(home, body.encode("utf-8"))
    without = updatecheck.update_status(installed)
    assert (with_bom.state, with_bom.line) == (without.state, without.line)


def test_a_bom_in_front_of_a_broken_record_is_still_unreadable(home):
    """The control. Accepting the BOM is not accepting whatever follows it."""
    write_bytes_record(home, BOM + b'{"checked_at": "2026-09-19T21:04:11Z"\n')
    status = updatecheck.update_status("0.35.1")
    assert status.state == STATE_UNREADABLE
    assert status.line == "update: the update record could not be read."


def test_a_bom_is_stripped_and_not_smuggled_into_the_parsed_record(home):
    """`load_record` returns the record itself — no leading `\ufeff` anywhere in a key."""
    write_bytes_record(home, BOM + record(pypi="0.36.0").encode("utf-8"))
    source, parsed = updatecheck.load_record()
    assert source == SOURCE_RECORD
    assert parsed is not None
    assert list(parsed) == ["checked_at", "npm", "pypi"]
    assert not any(key.startswith("\ufeff") for key in parsed)


def test_undecodable_bytes_are_unreadable_and_do_not_raise(home):
    """A half-written record, or one from a writer that raced. Bytes, not text."""
    (home / ".bantamkit" / "update-check.json").write_bytes(b'{"checked_at": "\xff\xfe"}')
    assert updatecheck.update_status("0.35.1").state == STATE_UNREADABLE


def test_a_directory_where_the_record_should_be_is_unreadable(home):
    """Something IS there and this reader cannot use it — which is not `never checked`."""
    (home / ".bantamkit" / "update-check.json").mkdir()
    assert updatecheck.update_status("0.35.1").state == STATE_UNREADABLE


def test_a_missing_bantamkit_directory_is_never_checked(tmp_path, monkeypatch):
    """The state of a fresh machine. Not an error, and NOT a reason to create the directory.

    The writer creates no directory either (it writes only when `.bantamkit` already exists),
    so this is the state a machine that has installed nothing else stays in.
    """
    root = tmp_path / "bare-home"
    root.mkdir()
    monkeypatch.setattr(updatecheck, "_home", lambda: root)
    assert updatecheck.update_status("0.35.1").state == STATE_NEVER
    assert not (root / ".bantamkit").exists()


def test_a_bantamkit_that_is_a_file_is_never_checked(tmp_path, monkeypatch):
    """`ENOTDIR`: nothing is at the path, so the operator is exactly where an unchecked one is."""
    root = tmp_path / "odd-home"
    root.mkdir()
    (root / ".bantamkit").write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(updatecheck, "_home", lambda: root)
    assert updatecheck.update_status("0.35.1").state == STATE_NEVER


# --- read_record and load_record ----------------------------------------------------------


def test_load_record_names_which_of_the_two_nothings_it_found(home):
    assert updatecheck.load_record() == (SOURCE_ABSENT, None)
    write_record(home, "{oops")
    assert updatecheck.load_record() == (SOURCE_UNREADABLE, None)
    write_record(home, record())
    source, parsed = updatecheck.load_record()
    assert source == SOURCE_RECORD
    assert parsed["pypi"]["latest"] == "0.36.0"


def test_read_record_returns_the_object_or_none(home):
    assert updatecheck.read_record() is None
    write_record(home, record())
    assert updatecheck.read_record()["checked_at"] == CHECKED_AT


def test_decide_is_pure_and_needs_no_filesystem(tmp_path, monkeypatch):
    """The state is decided from the record alone — no path, no clock, no home.

    `_home` is pointed at a directory that does not exist: if `decide` reached a disk at all,
    this node is where that shows up.
    """
    monkeypatch.setattr(updatecheck, "_home", lambda: tmp_path / "nowhere")
    parsed = json.loads(record(pypi="0.36.0"))
    assert updatecheck.decide("0.35.1", SOURCE_RECORD, parsed).state == STATE_AVAILABLE
    assert updatecheck.decide("0.35.1", SOURCE_ABSENT, None).state == STATE_NEVER
    assert updatecheck.decide("0.35.1", SOURCE_UNREADABLE, None).state == STATE_UNREADABLE


def test_update_line_is_the_line_of_update_status(home):
    write_record(home, record(pypi="0.36.0"))
    assert updatecheck.update_line("0.35.1") == updatecheck.update_status("0.35.1").line


def test_an_explicit_path_is_read_instead_of_the_home_one(home, tmp_path):
    """The seam the conformance harness drives, so it need not own a HOME."""
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(record(pypi="0.36.0"), encoding="utf-8")
    write_record(home, record(pypi="0.35.1"))
    assert updatecheck.update_status("0.35.1", path=elsewhere).state == STATE_AVAILABLE
    assert updatecheck.update_status("0.35.1").state == STATE_CURRENT


# --- the date is sliced, never rendered ---------------------------------------------------


def test_the_date_is_the_prefix_of_checked_at_and_not_a_locale_rendering(home):
    """A rendered date would make the two runtimes disagree on a machine set to another locale.

    So the assertion is on the BYTES of the prefix, and on the absence of anything a renderer
    would have added — a month name, a slash, a time.
    """
    write_record(home, record(pypi="0.35.1", checked_at="2026-01-02T03:04:05Z"))
    line = updatecheck.update_line("0.35.1")
    assert line == "update: bantamkit-mcp 0.35.1 is current as of 2026-01-02."
    assert "Jan" not in line and "/" not in line and "03:04" not in line


def test_a_bare_date_with_no_time_is_still_a_date(home):
    write_record(home, record(pypi="0.35.1", checked_at="2026-09-19"))
    assert updatecheck.update_line("0.35.1").endswith("current as of 2026-09-19.")


def test_a_stale_checked_at_does_not_become_a_state_of_its_own(home):
    """NO TTL LIVES IN THIS READER, and this is the node that would go red if one were added.

    A record from 2019 that says the index has what is running is still `current`: the
    comparison is running-versus-recorded, and freshness is the writer's problem alone.
    """
    write_record(home, record(pypi="0.35.1", checked_at="2019-01-01T00:00:00Z"))
    status = updatecheck.update_status("0.35.1")
    assert status.state == STATE_CURRENT
    assert status.line == "update: bantamkit-mcp 0.35.1 is current as of 2019-01-01."


def test_an_old_record_cannot_manufacture_a_false_stale(home):
    """The self-correcting half of the no-TTL argument: update, and the line goes quiet."""
    write_record(home, record(pypi="0.36.0", checked_at="2019-01-01T00:00:00Z"))
    assert updatecheck.update_status("0.35.1").state == STATE_AVAILABLE
    assert updatecheck.update_status("0.36.0").state == STATE_CURRENT
    assert updatecheck.update_status("0.37.0").state == STATE_AHEAD


# --- two stamps, and which one dates which number (J62-13, 2026-09-21) --------------------
#
# An ENTRY's `checked_at` is when THAT registry answered; the record's is when a writer
# refreshed the record AS A WHOLE, and is the fallback for an entry without one. Before this,
# a writer that filled ONE key stamped the record — so the reader of the OTHER key dated its
# stale number by a check that never touched its registry. The port's half of these is
# `runtime-ts/test/updatecheck.test.mjs`; the two are compared in
# `tools/conformance/suites/updatecheck.mjs`.


def _two_stamps(pypi_stamp: object = ..., npm_stamp: str = "2026-09-20T09:12:00Z") -> str:
    """A record stamped 2026-09-19, with an entry stamp of 2026-09-20 on npm."""
    pypi: dict[str, object] = {"distribution": "bantamkit", "latest": "0.36.0"}
    if pypi_stamp is not ...:
        pypi["checked_at"] = pypi_stamp
    return json.dumps(
        {
            "checked_at": "2026-09-19T21:04:11Z",
            "npm": {"package": "bantamkit-mcp", "latest": "0.36.0", "checked_at": npm_stamp},
            "pypi": pypi,
        }
    )


def test_an_entrys_own_stamp_dates_that_entrys_number(home):
    """One file, two keys, TWO DATES — and this reader takes the one that dates ITS number."""
    write_record(home, _two_stamps())
    assert updatecheck.update_line("0.36.0", "pypi").endswith("current as of 2026-09-19.")
    assert updatecheck.update_line("0.36.0", "npm").endswith("current as of 2026-09-20.")


def test_an_entry_without_a_stamp_falls_back_to_the_records(home):
    """The fallback is not a leniency: such an entry WAS last written by a whole-record write.

    This is the arm that keeps every record written before J62-13 answering byte for byte as
    it did, which is why the whole pre-existing conformance table stayed green.
    """
    write_record(home, record(pypi="0.35.1", checked_at="2026-01-02T03:04:05Z"))
    assert updatecheck.update_line("0.35.1") == (
        "update: bantamkit-mcp 0.35.1 is current as of 2026-01-02."
    )


def test_a_record_with_no_record_level_stamp_is_read_through_the_entrys(home):
    """What `--update` leaves on a machine that had no record: an entry stamp and nothing else.

    Before this, such a record was `could not be read` — which is why `record_update` used to
    stamp the record and why fixing THAT alone would have broken the fresh-install path.
    """
    entry = {
        "distribution": "bantamkit",
        "latest": "0.36.0",
        "checked_at": "2026-09-20T09:12:00Z",
    }
    write_record(home, json.dumps({"pypi": entry}))
    assert updatecheck.update_line("0.36.0") == (
        "update: bantamkit-mcp 0.36.0 is current as of 2026-09-20."
    )


@pytest.mark.parametrize("bad", ["yesterday", "19/09/2026", 20260920, None, ""])
def test_a_garbage_entry_stamp_is_unreadable_and_never_falls_back(home, bad):
    """ONE SELECTION, THEN ONE RULE — not two rules, and not the more flattering of two dates.

    The record's own stamp here is perfectly good. An entry that CARRIES the name is the
    entry's answer, so a garbage value there is unreadable exactly as a garbage top-level one
    is. A reader that fell back would date this number by a check of the other registry, which
    is the defect this whole change exists to remove.
    """
    write_record(home, _two_stamps(pypi_stamp=bad))
    assert updatecheck.update_status("0.36.0", "pypi").state == STATE_UNREADABLE
    # …and the key whose stamp is fine is unaffected: one bad entry is not a bad record.
    assert updatecheck.update_status("0.36.0", "npm").state == STATE_CURRENT


# --- what this module never does ----------------------------------------------------------


def _tree(root: Path) -> dict[str, tuple[int, int, bytes]]:
    """Every file under `root` as (size, mtime_ns, bytes) — enough to notice any write."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            out[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns, path.read_bytes())
    return out


def test_a_read_leaves_the_filesystem_byte_unchanged(home):
    write_record(home, record(pypi="0.36.0"))
    before = _tree(home)
    for _ in range(3):
        updatecheck.update_status("0.35.1")
        updatecheck.read_record()
        updatecheck.load_record()
        updatecheck.record_path()
    assert _tree(home) == before


def test_nothing_here_creates_a_cwd_relative_bantamkit(home, tmp_path, monkeypatch):
    """`.bantamkit` relative to a cwd is a MEMORY STORE (J54-3). This module never builds one.

    The cwd is a directory that has none, the home has one, and every entry point is called —
    including the ones that find nothing, because "it was missing so I made it" is the shape
    of the defect this guards.
    """
    workdir = tmp_path / "some-repo"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    (home / ".bantamkit" / "update-check.json").unlink(missing_ok=True)

    updatecheck.record_path()
    updatecheck.read_record()
    updatecheck.load_record()
    updatecheck.update_status("0.35.1")
    updatecheck.update_line("0.35.1")
    write_record(home, record(pypi="0.36.0"))
    updatecheck.update_line("0.35.1")

    assert not (workdir / ".bantamkit").exists()
    assert list(workdir.iterdir()) == []
    assert os.getcwd() == str(workdir)


def test_the_record_path_hangs_off_home_and_not_the_cwd(home, tmp_path, monkeypatch):
    """The path does not move when the cwd does — which is the whole of J54-3's lesson."""
    workdir = tmp_path / "a-repo"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    path = updatecheck.record_path()
    assert path.is_absolute()
    assert path == home / ".bantamkit" / "update-check.json"
    assert workdir not in path.parents
    monkeypatch.chdir(tmp_path)
    assert updatecheck.record_path() == path


def test_the_source_writes_nothing_and_reaches_no_network():
    """Off the PARSED source, not off a sentence in a docstring.

    Two properties in one walk, because they are the same kind of claim: every name this
    module can reach must be in neither the writing set nor the network set. An AST carries
    no comments and a string is not a `Name`, so the prose above stays invisible to this and
    a call goes red — which is why this is a parse and not a `grep`.
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    network = {"urllib", "urllib.request", "urllib.error", "http", "http.client", "socket",
               "ssl", "requests", "httpx", "subprocess"}
    assert not (imported & network), imported & network
    assert imported == {"__future__", "json", "re", "dataclasses", "pathlib", "typing",
                        "bantamkit.selfupdate"}

    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute):
                called.add(target.attr)
            elif isinstance(target, ast.Name):
                called.add(target.id)
    writing = {"mkdir", "makedirs", "write_text", "write_bytes", "touch", "rename", "replace",
               "unlink", "open", "urlopen", "__import__", "import_module"}
    assert not (called & writing), called & writing


def test_the_states_are_five_and_named():
    assert updatecheck.STATES == (
        STATE_NEVER,
        STATE_AVAILABLE,
        STATE_CURRENT,
        STATE_AHEAD,
        STATE_UNREADABLE,
    )
    assert len(set(updatecheck.STATES)) == 5
