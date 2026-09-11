"""`bantamkit-mcp --update`: what it prints, what it refuses, and what it never runs.

NOT ONE NODE IN THIS FILE REACHES THE NETWORK OR RUNS AN INSTALLER. A test that asked PyPI
would fail on a plane and pass for the wrong reason off a cache, and a test that ran
`pip install --upgrade bantamkit` would rewrite the developer's own environment mid-suite.
`selfupdate.update` therefore takes both as keyword arguments with real defaults — `fetch`
and `installer` — and every arm below is exercised through a substitute. The installer
command is CAPTURED and asserted on; it is never executed.

THE VERSION PAIRS ARE CHOSEN TO BE AWKWARD ON PURPOSE. `0.30.0` against `0.30.0` and
`0.30.0` against `0.31.0` are the pair on which every implementation agrees, including a
wrong one, so they are here as the floor and not as the proof. The pairs that decide
anything are `0.9.0` against `0.10.0` (where a string compare says the index is BEHIND) and
an index that really is behind, which is what a machine running a checkout build looks like
and where an implementation that only tested equality would run an installer and report a
downgrade as a success.
"""

from __future__ import annotations

import ast
import json
import shlex
import sys
from pathlib import Path

import pytest

# The scanner the no-network gate is built on, imported rather than copied: a second AST
# walker asserting the same property is exactly the duplicated-derived-answer defect the
# `cli` suite exists to catch, and this one has its own four-row red-proof next door.
from test_install_shape import _names_reached_by

from bantamkit import selfupdate
from bantamkit.selfupdate import Origin, UpdateRefused, compare_versions, update

SRC = Path(selfupdate.__file__)


def _payload(version: str) -> str:
    """What `pypi.org/pypi/bantamkit/json` answers, reduced to the field that is read."""
    return json.dumps({"info": {"name": "bantamkit", "version": version}})


def _fetch(version: str):
    """A stub index that answers one version and records that it was asked."""
    calls: list[tuple[str, float]] = []

    def fetch(url: str, timeout: float) -> str:
        calls.append((url, timeout))
        return _payload(version)

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _installer_that_must_not_run(command):
    raise AssertionError(f"an installer ran when nothing should have: {command}")


def _recording_installer(code: int = 0, output: str = "Successfully installed bantamkit-0.31.0"):
    commands: list[list[str]] = []

    def installer(command: list[str]) -> tuple[int, str]:
        commands.append(list(command))
        return code, output

    installer.commands = commands  # type: ignore[attr-defined]
    return installer


REGISTRY = Origin("registry", "/does/not/matter")


# --- the two answers that change nothing ---------------------------------------------


def test_the_same_version_says_up_to_date_and_runs_no_installer():
    """The word the user asked for, and the numbers that make it checkable.

    "ถ้า match ให้แสดงคำ uptodate" — so `up to date.` is asserted as a whole line and not as a
    substring, because a line that happened to contain the phrase inside a longer sentence
    would satisfy a substring check and not the request.
    """
    fetch = _fetch("0.30.0")
    report = update(
        "0.30.0", REGISTRY, fetch=fetch, installer=_installer_that_must_not_run
    )

    assert report.splitlines() == [
        "bantamkit-mcp 0.30.0 is installed; the package index has 0.30.0.",
        "up to date.",
    ]
    assert fetch.calls == [(selfupdate.INDEX_URL, selfupdate.DEFAULT_TIMEOUT_SECONDS)]


def test_an_index_behind_the_installed_version_installs_nothing():
    """The state a checkout build is actually in, and the one an equality test cannot see.

    An implementation that branched on `installed != latest` alone would run the upgrade
    here, watch pip correctly do nothing because the requirement is already satisfied, and
    then print `updated bantamkit-mcp from 0.31.0 to 0.30.0` — a remedy that exits 0 having
    changed anything at all, which is the J46-4 defect with a downgrade painted on it.
    """
    report = update(
        "0.31.0", REGISTRY, fetch=_fetch("0.30.0"), installer=_installer_that_must_not_run
    )

    assert report.splitlines() == [
        "bantamkit-mcp 0.31.0 is installed; the package index has 0.30.0.",
        "the installed version is ahead of the package index; there is nothing to update to.",
    ]


def test_the_index_being_behind_is_decided_numerically_not_alphabetically():
    """`0.9.0` vs `0.10.0`: a string compare calls the index behind and skips a real update.

    This is the pair the docstring at the top of the file promises. It is not hypothetical
    — bantamkit shipped 0.9.0 and then 0.10.0 — and it is the one case where "different, so
    update" and "greater, so do not" disagree about the direction rather than the fact.
    """
    installer = _recording_installer()
    report = update("0.9.0", REGISTRY, fetch=_fetch("0.10.0"), installer=installer)

    assert "0.9.0" > "0.10.0", "the premise: a plain string compare gets this backwards"
    assert installer.commands, "the update must have been attempted"
    assert "updated bantamkit-mcp from 0.9.0 to 0.10.0." in report.splitlines()


@pytest.mark.parametrize(
    ("installed", "latest", "expected", "why"),
    [
        ("0.30.0", "0.30.0", 0, "identical"),
        ("0.30", "0.30.0", 0, "a missing component is zero, not a difference"),
        ("0.30.0", "0.30.0.1", -1, "a longer index version is ahead"),
        ("0.9.0", "0.10.0", -1, "numeric, not alphabetic"),
        ("0.10.0", "0.9.0", 1, "and the same in reverse"),
        ("1.0.0", "0.99.99", 1, "the major component dominates"),
        ("0.31.0", "0.31.0rc1", -1, "a non-numeric component sorts after every number"),
    ],
)
def test_compare_versions_orders_the_pairs_the_sentences_depend_on(
    installed, latest, expected, why
):
    """The comparator, pinned pair by pair, because three sentences branch on its sign.

    The last row is the documented WRONG answer by PEP 440 — a release candidate is not
    newer than its release — and it is pinned rather than fixed. `_version_key`'s docstring
    carries the reason: bantamkit has never published a prerelease to either registry, and
    implementing PEP 440 would be a second and much larger thing for `runtime-ts` to
    reproduce exactly. What this row buys is that both runtimes are wrong in the SAME
    direction, which is a thing a conformance case can compare and a reader can check.
    """
    assert compare_versions(installed, latest) == expected, why


# --- the answer that changes something ------------------------------------------------


def test_a_newer_index_runs_the_upgrade_command_and_the_command_is_captured_not_run():
    """The command is this interpreter's own pip, by absolute path, and it is asserted whole.

    A bare `pip` would upgrade whichever environment is first on `PATH`, which on a machine
    running the server out of a venv is not the environment being served — an update that
    reports success and changes nothing the server will ever load.
    """
    installer = _recording_installer()
    report = update("0.30.0", REGISTRY, fetch=_fetch("0.31.0"), installer=installer)

    assert installer.commands == [
        [sys.executable, "-m", "pip", "install", "--upgrade", "bantamkit"]
    ]
    assert report.splitlines() == [
        "bantamkit-mcp 0.30.0 is installed; the package index has 0.31.0.",
        f"updating from the package index: {shlex.join(installer.commands[0])}",
        "the command printed:",
        "Successfully installed bantamkit-0.31.0",
        "updated bantamkit-mcp from 0.30.0 to 0.31.0.",
        "restart the server: a running bantamkit-mcp keeps serving the code it loaded at "
        "startup, so bantamkit_status will report 0.30.0 until the host reconnects.",
    ]


def test_the_success_report_names_the_restart_and_the_stale_number_it_will_keep_reporting():
    """AS-7's first reason, measured 2026-09-07, is the reason this line is not optional.

    `runtime-ts/dist/` was rebuilt at 0.30.0 at 08:58 and `bantamkit_status` kept answering
    `version 0.29.1` until the host reconnected at 09:03. So the sentence must name the OLD
    version — the number the caller will go on seeing — and not the new one, which is the
    number a reader would expect and which would make the line useless.
    """
    report = update("0.29.1", REGISTRY, fetch=_fetch("0.30.0"), installer=_recording_installer())
    restart = report.splitlines()[-1]

    assert restart.startswith("restart the server:")
    assert "will report 0.29.1 until the host reconnects." in restart
    assert "0.30.0" not in restart, "naming the NEW version here is the confusion AS-7 predicted"


def test_an_installer_that_fails_refuses_and_hands_back_what_the_command_said():
    """A non-zero installer is not a success with a warning, and its output is not summarised.

    The command's own words are the only thing that says WHY, so they are carried into the
    refusal verbatim. Without them the operator's next move is to re-run by hand the command
    that just failed, which is the whole of what this flag was supposed to save.
    """
    installer = _recording_installer(code=1, output="ERROR: Could not find a version")
    with pytest.raises(UpdateRefused) as caught:
        update("0.30.0", REGISTRY, fetch=_fetch("0.31.0"), installer=installer)

    assert str(caught.value).splitlines() == [
        f"the update command exited 1: {shlex.join(installer.commands[0])}",
        "bantamkit-mcp 0.30.0 is still installed; nothing was changed.",
        "the command printed:",
        "ERROR: Could not find a version",
    ]


def test_an_installer_that_printed_nothing_still_reports_in_one_shape():
    """`(nothing)` rather than a line that is sometimes absent — one shape for the port."""
    report = update(
        "0.30.0", REGISTRY, fetch=_fetch("0.31.0"), installer=_recording_installer(output="  \n")
    )

    assert report.splitlines()[2:4] == ["the command printed:", "(nothing)"]


# --- the shapes this flag will not touch ----------------------------------------------


SHAPELESS = ("local-file", "linked", "checkout", "ephemeral")


@pytest.mark.parametrize("shape", SHAPELESS)
def test_a_shape_with_no_registry_route_refuses_and_names_the_real_route(shape):
    """Four of the five shapes have nothing to update from an index, and each says so itself.

    AS-7's third reason, which survived the reversal: running a registry install against a
    tree the operator manages with `git` is worse than doing nothing. So the installer is
    asserted never to have been reached, and the refusal has to carry the shape word AND a
    route, because "I will not do that" without "here is how" is the half-answer this flag
    was built to replace.
    """
    with pytest.raises(UpdateRefused) as caught:
        update(
            "0.29.0",
            Origin(shape, "/tmp/an-origin"),
            fetch=_fetch("0.30.0"),
            installer=_installer_that_must_not_run,
        )

    message = str(caught.value)
    assert message.startswith(
        "bantamkit-mcp 0.29.0 is installed and the package index has 0.30.0, "
        f"but this is a {shape} install, which --update will not touch. "
    )
    assert len(message.splitlines()) == 1, "a one-line refusal, like every --install refusal"
    assert "{" not in message, "an unsubstituted placeholder reached the operator"


def test_the_four_routes_are_four_different_sentences():
    """A table that answered the same thing four times would pass the test above unchanged.

    That is the vacuity the parametrised node cannot see: it checks each shape's refusal
    against its own shape word, which is interpolated from the same argument, so a `ROUTES`
    whose four values were one string would be green four times over.
    """
    rendered = {
        shape: selfupdate.ROUTES[shape].format(
            source="/tmp/an-origin", distribution=selfupdate.DISTRIBUTION, latest="0.30.0"
        )
        for shape in SHAPELESS
    }

    assert len(set(rendered.values())) == len(SHAPELESS), rendered
    assert "registry" not in selfupdate.ROUTES, (
        "`registry` is the shape this flag DOES update; a route for it is unreachable text"
    )
    assert set(selfupdate.ROUTES) | {"registry"} == set(mcpserver_install_shapes()), (
        "`ROUTES` plus `registry` must cover `INSTALL_SHAPES` exactly — a shape with no row "
        "falls through to the no-route-recorded refusal, which is a guess-free answer but "
        "not an answer"
    )


def mcpserver_install_shapes():
    from bantamkit.mcpserver import INSTALL_SHAPES

    return INSTALL_SHAPES


def test_the_two_shapes_with_a_recorded_origin_print_that_origin():
    """`local-file` and `linked` are the shapes J46-11 gives a `source`, so the path is used.

    Without this the table could name a route and drop the one fact that makes it
    actionable, and every assertion above would still pass.
    """
    for shape in ("local-file", "linked"):
        with pytest.raises(UpdateRefused) as caught:
            update(
                "0.29.0",
                Origin(shape, "/tmp/where-it-came-from"),
                fetch=_fetch("0.30.0"),
                installer=_installer_that_must_not_run,
            )
        assert "/tmp/where-it-came-from" in str(caught.value), shape


def test_a_shape_word_this_table_has_never_heard_of_refuses_rather_than_guessing():
    """`INSTALL_SHAPES` growing a sixth word must not silently take the installer path.

    The fallthrough is a refusal that says so, which is a fact about this code being behind
    the vocabulary rather than a fact about the operator's machine — and it is still exit 1
    and still runs nothing.
    """
    with pytest.raises(UpdateRefused) as caught:
        update(
            "0.29.0",
            Origin("something-new", ""),
            fetch=_fetch("0.30.0"),
            installer=_installer_that_must_not_run,
        )

    assert "There is no recorded update route for a something-new install" in str(caught.value)


# --- the network, refused by name -----------------------------------------------------


def test_unreachable_and_garbage_are_two_different_refusals():
    """Two failures a single "could not check" sentence would have merged into one.

    They need different sentences because they need different next moves: one is the
    operator's network, the other is something answering on port 443 that is not the index
    — a captive portal login page with a 200, which is the realistic shape of this.
    """
    def offline(url: str, timeout: float) -> str:
        raise OSError("[Errno 8] nodename nor servname provided")

    def garbage(url: str, timeout: float) -> str:
        return "<html><body>Sign in to the guest network</body></html>"

    with pytest.raises(UpdateRefused) as unreachable:
        update("0.30.0", REGISTRY, fetch=offline, installer=_installer_that_must_not_run)
    with pytest.raises(UpdateRefused) as not_json:
        update("0.30.0", REGISTRY, fetch=garbage, installer=_installer_that_must_not_run)

    assert str(unreachable.value) == (
        "the package index could not be reached: [Errno 8] nodename nor servname provided; "
        "--update needs the network, and nothing was changed."
    )
    assert str(not_json.value) == (
        "the package index answered, but not with a version for bantamkit-mcp: the response "
        "is not JSON; nothing was changed."
    )
    assert str(unreachable.value) != str(not_json.value)


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("<html>", "not JSON at all"),
        ("[]", "JSON, but not an object"),
        ('{"info": {}}', "an object with no version"),
        ('{"info": {"version": ""}}', "a version that is the empty string"),
        ('{"info": {"version": 30}}', "a version that is not a string"),
        ('{"version": "0.31.0"}', "the right word at the wrong path"),
    ],
)
def test_every_shape_of_garbage_is_refused_rather_than_installed(body, why):
    """A body that is not a version must never reach the comparison, let alone the installer.

    The last row is the one that matters most: `{"version": ...}` is npm's shape, not PyPI's,
    and a reader who ported the parser by eye would accept it here. It is garbage on this
    side and it is refused as garbage.
    """
    with pytest.raises(UpdateRefused) as caught:
        update(
            "0.30.0",
            REGISTRY,
            fetch=lambda url, timeout: body,
            installer=_installer_that_must_not_run,
        )

    assert str(caught.value).startswith(
        "the package index answered, but not with a version for bantamkit-mcp:"
    ), why


def test_a_timeout_is_its_own_refusal_and_names_the_number_of_seconds():
    """The timeout is explicit, so the sentence says what it was — and says it as `10`.

    `10.0` here and `10` on the Node side would be a one-character divergence in a sentence
    that is otherwise identical, and a one-character divergence costs a `docs/porting.md`
    row and a ruling for nothing. `_seconds` is what keeps it from costing that.
    """
    def slow(url: str, timeout: float) -> str:
        raise TimeoutError("timed out")

    with pytest.raises(UpdateRefused) as caught:
        update("0.30.0", REGISTRY, fetch=slow, installer=_installer_that_must_not_run)

    assert str(caught.value) == (
        "the package index did not answer within 10 seconds; --update needs the network, "
        "and nothing was changed."
    )


def test_the_timeout_is_the_one_the_caller_passed_and_reaches_the_fetch():
    """The number in the sentence is the number the fetch was given, not a second constant."""
    seen: list[float] = []

    def slow(url: str, timeout: float) -> str:
        seen.append(timeout)
        raise TimeoutError("timed out")

    with pytest.raises(UpdateRefused) as caught:
        update(
            "0.30.0",
            REGISTRY,
            fetch=slow,
            installer=_installer_that_must_not_run,
            timeout=2.5,
        )

    assert seen == [2.5]
    assert "within 2.5 seconds" in str(caught.value)


def test_a_timeout_is_not_swallowed_by_the_unreachable_arm():
    """`TimeoutError` IS an `OSError`, so the order of the two except clauses is load-bearing.

    Reverse them and every timeout reads as "could not be reached", which names the wrong
    problem and sends the operator to check a network that is working.
    """
    assert issubclass(TimeoutError, OSError), "the premise this node exists for"


# --- the network lives in exactly one function ----------------------------------------


NETWORK_FREE = {
    "latest_from_index_payload",
    "upgrade_command",
    "run_installer",
    "_version_key",
    "compare_versions",
    "update",
    "_seconds",
}
#: What the offline half of this module may touch. `fetch_index` is deliberately absent:
#: it is the one function allowed to reach `urllib`, and it is checked separately below.
ALLOWED = {
    "Callable",
    "DEFAULT_TIMEOUT_SECONDS",
    "DISTRIBUTION",
    "INDEX_URL",
    "NOT_A_VERSION",
    "NOT_JSON",
    "NO_OUTPUT",
    "NO_VERSION_FIELD",
    "NO_ROUTE",
    "Origin",
    "PRINTED",
    "PROGRAM",
    "ROUTES",
    "RESTART",
    "TIMED_OUT",
    "UNREACHABLE",
    "UPDATED",
    "UPDATING",
    "UP_TO_DATE",
    "AHEAD",
    "COMPARISON",
    "COMMAND_FAILED",
    "UpdateRefused",
    "_seconds",
    "_version_key",
    "compare_versions",
    "fetch_index",
    "json",
    "latest_from_index_payload",
    "run_installer",
    "shlex",
    "subprocess",
    "sys",
    "upgrade_command",
}


def test_the_network_lives_in_exactly_one_function_of_this_module():
    """AS-7(3) survived the reversal: the network is on this flag's path and on no other.

    Read structurally, with the scanner `test_install_shape.py` proves red four ways —
    module-level import, function-local import, `__import__`, and a comment that must stay
    green. Every function of `selfupdate` EXCEPT `fetch_index` is scanned; a `urllib` that
    appeared in any of them, at any level, reddens this.

    The complement is asserted too. A gate that only checked the offline half would stay
    green if `fetch_index` stopped fetching and the call moved somewhere this list forgot to
    name, so the scanner is run over `fetch_index` on its own and `urllib.request` must be
    there.

    RED-PROOF, measured 2026-09-11 against a copy of `src/` with a function-local
    `import urllib.request` plus a `urlopen(INDEX_URL)` added to the top of
    `compare_versions` — the shape the node below proves on a sample, run here against the
    real module: `a new name reached the offline half of --update: ['urllib.request']`.
    """
    source = SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}

    assert NETWORK_FREE | {"fetch_index"} == defined, (
        "a function was added to or renamed in `selfupdate` and this gate does not cover it: "
        f"{sorted(defined ^ (NETWORK_FREE | {'fetch_index'}))}"
    )
    escaped = _names_reached_by(source, NETWORK_FREE, set(vars(selfupdate))) - ALLOWED
    assert not escaped, f"a new name reached the offline half of --update: {sorted(escaped)}"

    fetching = _names_reached_by(source, {"fetch_index"}, set(vars(selfupdate)))
    assert "urllib.request" in fetching, (
        "`fetch_index` no longer imports the request module; either the network moved "
        "somewhere this gate is not looking, or this gate is now pointed at nothing"
    )


def test_this_gate_reddens_when_the_network_moves_into_the_offline_half():
    """The mutation, run — a gate nobody has watched fail is a comment with an assert in it.

    `compare_versions` is chosen because it is the most innocuous function in the module and
    the least likely to be read closely by the next person; if the gate catches a `urlopen`
    there it catches one anywhere.
    """
    mutated = (
        "def compare_versions(installed, latest):\n"
        "    import urllib.request\n"
        "    urllib.request.urlopen('https://pypi.org/pypi/bantamkit/json')\n"
        "    return 0\n"
    )

    assert _names_reached_by(mutated, {"compare_versions"}) - ALLOWED, (
        "the gate let a function-local urlopen through the offline half"
    )
    assert not _names_reached_by(
        "def compare_versions(installed, latest):\n"
        "    # urllib.request is never called here\n"
        "    return 0\n",
        {"compare_versions"},
    ) - ALLOWED, "the gate reddened on a comment, and the next person will delete it"


def test_only_the_update_flag_reaches_this_module_from_the_server():
    """Nothing on a host's path may reach a network call. Structural, over `mcpserver`'s AST.

    AS-7(b) was explicit that a dependency-free toolbox must not grow a network call in its
    health check, and the user asked for a flag rather than a background checker. So the
    claim is not "we didn't do that" — it is that exactly one function in `mcpserver.py`
    mentions `selfupdate` at all, and it is the one the flag calls.

    RED-PROOF, measured 2026-09-11 on this tree: adding `selfupdate.fetch_index` to
    `build_identity`'s body makes this node fail with
    `functions reaching selfupdate: ['_run_update', 'build_identity']`.
    """
    from bantamkit import mcpserver

    source = Path(mcpserver.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    reaching = sorted(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if "selfupdate" in _names_reached_by(source, {node.name}, set(vars(mcpserver)))
    )

    assert reaching == ["_run_update"], f"functions reaching selfupdate: {reaching}"


# --- the flag, on the CLI -------------------------------------------------------------


def test_update_defaults_off_so_a_bare_invocation_still_serves():
    """The production invocation passes no arguments. It must not go to a registry."""
    from bantamkit.mcpserver import _parse_args

    assert _parse_args([]).update is False
    assert _parse_args(["--update"]).update is True


def test_the_flag_writes_the_report_to_stdout_and_exits_zero(monkeypatch, capsysbinary):
    """stdout, LF, exit 0 — the shape every printing flag on this parser already has."""
    from bantamkit import mcpserver

    monkeypatch.setattr(mcpserver, "current_install", lambda: mcpserver.Install("registry"))
    monkeypatch.setattr(mcpserver.selfupdate, "update", lambda *a, **k: "a\nb")

    mcpserver._run_update()

    captured = capsysbinary.readouterr()
    assert captured.out == b"a\nb\n"
    assert captured.err == b""


def test_a_refusal_goes_to_stderr_with_the_error_prefix_and_exits_one(monkeypatch, capsysbinary):
    """Exit 1 and not 0: `--update` that changed nothing must not look like one that did.

    This is the J46-4 defect named in this unit's brief, and the no-route arm is the one it
    would have bitten — the operator is told the truth and the shell is told it failed.
    """
    from bantamkit import mcpserver

    def refuse(*_args, **_kwargs):
        raise selfupdate.UpdateRefused("nope, and here is why")

    monkeypatch.setattr(mcpserver, "current_install", lambda: mcpserver.Install("checkout"))
    monkeypatch.setattr(mcpserver.selfupdate, "update", refuse)

    with pytest.raises(SystemExit) as caught:
        mcpserver._run_update()

    assert caught.value.code == 1
    captured = capsysbinary.readouterr()
    assert captured.out == b""
    assert captured.err == b"error: nope, and here is why\n"


def test_an_underivable_install_shape_refuses_and_quotes_the_reason(monkeypatch, capsysbinary):
    """`pip install git+https://…` — neither an index nor a path, so no route is guessed.

    `_Undetermined`'s own message already names the next step ("reinstalling from that same
    URL"), so it is quoted rather than paraphrased into a second, weaker sentence.
    """
    from bantamkit import mcpserver

    def undetermined():
        raise mcpserver._Undetermined("its origin is a git URL")

    monkeypatch.setattr(mcpserver, "current_install", undetermined)
    monkeypatch.setattr(
        mcpserver.selfupdate, "update", lambda *a, **k: pytest.fail("reached the index anyway")
    )

    with pytest.raises(SystemExit) as caught:
        mcpserver._run_update()

    assert caught.value.code == 1
    assert capsysbinary.readouterr().err == (
        b"error: --update could not tell how this install was made, so it will not guess an "
        b"update route: its origin is a git URL\n"
    )


def test_the_shape_handed_to_selfupdate_is_the_one_the_installed_detector_derived(monkeypatch):
    """AS-7(a)'s answer, used — not a second detector written beside it.

    `current_install()` was built at `da97b52` as a module-level function taking no
    arguments precisely so this flag could ask it, and a second copy of a derived answer is
    the defect the `cli` suite exists to catch. A `checkout` carries no recorded origin, so
    the running package directory stands in — which is not a guess: it is where the code
    being executed lives, and it is the tree the route tells the operator to `git pull`.
    """
    from bantamkit import mcpserver

    seen: list[tuple[str, Origin]] = []
    monkeypatch.setattr(mcpserver, "current_install", lambda: mcpserver.Install("checkout"))
    monkeypatch.setattr(
        mcpserver.selfupdate,
        "update",
        lambda installed, origin, **_k: seen.append((installed, origin)) or "ok",
    )

    mcpserver._run_update()

    (installed, origin) = seen[0]
    assert installed == mcpserver._version()
    assert origin.shape == "checkout"
    assert Path(origin.source) == Path(mcpserver.bantamkit.__file__).resolve().parent


def test_the_flag_returns_before_a_store_or_a_transport_could_exist(monkeypatch):
    """Same discipline as `--assets-root`: every road to a server is a detonator.

    Somebody who typed `--update` has not asked for a `.bantamkit/memory` directory in
    whatever cwd they were standing in, and has certainly not asked for a stdio server on a
    process that is about to be replaced on disk.
    """
    from bantamkit import mcpserver

    def boom(*_args, **_kwargs):
        raise AssertionError("--update reached the server path")

    monkeypatch.setattr(sys, "argv", ["bantamkit-mcp", "--update"])
    monkeypatch.setattr(mcpserver, "_run_update", lambda: None)
    monkeypatch.setattr(mcpserver, "_build_memory", boom)
    monkeypatch.setattr(mcpserver, "build_server", boom)
    monkeypatch.setattr(mcpserver.asyncio, "run", boom)

    mcpserver.main()  # returns; does not raise SystemExit, so the exit code is 0


def test_update_is_in_the_generated_help_without_moving_the_pinned_first_line(monkeypatch):
    """The flag is discoverable, and the line three other nodes pin is byte-identical.

    `test_assets_root_appears_in_the_generated_help_in_the_documented_position`,
    `test_mcpreport.py` and the `cli` conformance suite all pin the first line of the
    80-column usage. Registering `--update` before `--mcp-report` would have moved it and
    turned a differential suite into a re-baselining one, which is what this pins — the
    flag being present is the cheap half of the assertion, and the first line is the rest.
    """
    from bantamkit.mcpserver import _build_parser

    monkeypatch.setenv("COLUMNS", "80")
    text = _build_parser().format_help()

    assert text.splitlines()[0] == (
        "usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]"
    )
    assert "  --update              check the package index and update this install if it" in text
