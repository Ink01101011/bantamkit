"""The reference side of the stale-install signal: one answer per record, per registry key.

WHAT THIS SCRIPT DOES NOT DO: build a fixture. Every record below arrives as a PATH the suite
wrote, and both runtimes are handed the SAME absolute path — so `latest` is compared with the
bytes that produced it, the way `install_ref.py` shares one `origins/` directory between its
two halves. A suite that wrote its own copy here would be comparing two fixtures.

THE ONE THING THIS SCRIPT OWNS IS `HOME`. `updatecheck.record_path()` and
`selfupdate.record_update()` resolve against `Path.home()` and nothing else, so the arms that
exercise them get a scratch home per side, set here, per arm — the same idiom `update_ref.py`
uses and for the same reason: the developer's own `~/.bantamkit/update-check.json` is a real
file with a real version number in it, and a harness that wrote a fixture version into it
would be a defect this job has already measured once.

NOTHING HERE REACHES THE NETWORK. `updatecheck` cannot (that is its whole design), and
`selfupdate.record_update` is the WRITER half — it writes what `--update` already fetched and
asks nobody anything. `selfupdate.update`, the one function in that module that does reach a
registry, is not called by this script and not imported by name.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from bantamkit import selfupdate, updatecheck


def _listing(directory: str) -> list[str] | None:
    """The directory's entries, sorted, or `None` when there is no directory to list."""
    try:
        return sorted(os.listdir(directory))
    except OSError:
        return None


def _text(path: str) -> str | None:
    """The file as text, or `None`. Used to prove a writer left the bytes it claims."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _home(home: str) -> None:
    """Point `Path.home()` at a directory nobody lives in. Both names, for Windows."""
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home


def read_arm(arm: dict, key: str) -> dict:
    """One record, one running version, one registry key — the whole answer.

    `raised` is a FIELD and not an exception, because "this reader never raises" is the claim
    under test: a shape that escaped would otherwise kill the script and cost the operator a
    stack trace instead of a red case naming the arm.
    """
    try:
        source, record = updatecheck.load_record(Path(arm["path"]))
        status = updatecheck.decide(arm["installed"], source, record, key)
        # The one-call surface, over the same path: it must land on the same sentence as the
        # two-step route, or the two entry points have drifted inside one runtime.
        line = updatecheck.update_line(arm["installed"], key, Path(arm["path"]))
        # And the convenience reader, which must agree with `load_record`'s second half.
        again = updatecheck.read_record(Path(arm["path"]))
    except BaseException as exc:  # noqa: BLE001 — nothing may escape; see the docstring
        return {"raised": f"{type(exc).__name__}: {exc}"}
    return {
        "raised": None,
        "source": source,
        "state": status.state,
        "line": status.line,
        "line_via_update_line": line,
        "record": record,
        "read_record_agrees": again == record,
    }


def write_arm(arm: dict) -> dict:
    """One `--update` writing what it already fetched, into a home the suite constructed."""
    _home(arm["home"])
    directory = os.path.join(arm["home"], updatecheck.RECORD_DIR)
    path = os.path.join(directory, updatecheck.RECORD_NAME)
    try:
        wrote = selfupdate.record_update(arm["latest"], arm["now"])
    except BaseException as exc:  # noqa: BLE001 — a failed write may not fail an update
        return {"raised": f"{type(exc).__name__}: {exc}"}
    body = _text(path)
    try:
        parsed = json.loads(body) if body is not None else None
    except ValueError:
        parsed = None
    return {
        "raised": None,
        "wrote": wrote,
        "listing": _listing(directory),
        "body": body,
        "record": parsed,
        # The path the writer used, relative to the home it was given: the two sides live in
        # two different scratch homes, so the absolute strings cannot be compared and the
        # SUFFIX is the part that has to agree.
        "path_under_home": os.path.relpath(str(updatecheck.record_path()), arm["home"]).replace(os.sep, "/"),
    }


def default_arm(arm: dict) -> dict:
    """A read through the DEFAULT path, under a home with nothing in it.

    Two claims in one arm: the path hangs off the home directory (never a cwd), and a read
    creates neither the file nor the `.bantamkit` directory around it.
    """
    _home(arm["home"])
    # A cwd with a `.bantamkit` of its own, so a reader that resolved relative to one would
    # find a DIFFERENT file and say so. `.bantamkit` under a cwd is a memory store (J54-3).
    os.chdir(arm["cwd"])
    status = updatecheck.update_status(arm["installed"])
    return {
        "state": status.state,
        "line": status.line,
        "path_under_home": os.path.relpath(str(updatecheck.record_path()), arm["home"]).replace(os.sep, "/"),
        "home_listing": _listing(arm["home"]),
        "cwd_listing": _listing(os.path.join(arm["cwd"], ".bantamkit")),
    }


def main() -> int:
    payload = json.loads(sys.stdin.read())
    answers = {
        key: {arm["id"]: read_arm(arm, key) for arm in payload["arms"]}
        for key in payload["keys"]
    }
    print(
        json.dumps(
            {
                "constants": {
                    "PROGRAM": updatecheck.PROGRAM,
                    "KEY": updatecheck.KEY,
                    "RECORD_DIR": updatecheck.RECORD_DIR,
                    "RECORD_NAME": updatecheck.RECORD_NAME,
                    "STATES": list(updatecheck.STATES),
                    "SOURCES": [
                        updatecheck.SOURCE_ABSENT,
                        updatecheck.SOURCE_UNREADABLE,
                        updatecheck.SOURCE_RECORD,
                    ],
                    "STAMP": selfupdate.STAMP,
                },
                "sentences": {
                    "never": updatecheck.UPDATE_NEVER,
                    "available": updatecheck.UPDATE_AVAILABLE,
                    "current": updatecheck.UPDATE_CURRENT,
                    "ahead": updatecheck.UPDATE_AHEAD,
                    "unreadable": updatecheck.UPDATE_UNREADABLE,
                },
                # The program constant is not merely equal to `selfupdate`'s, it IS it — the
                # reference imports it. The port declares its own and pins the equality in its
                # unit tests, which is why this bit travels rather than the claim.
                "program_is_selfupdates": updatecheck.PROGRAM is selfupdate.PROGRAM,
                "answers": answers,
                "defaults": {arm["id"]: read_arm(arm, updatecheck.KEY) for arm in payload["arms"]},
                "writes": {arm["id"]: write_arm(arm) for arm in payload["writes"]},
                "default_path": default_arm(payload["default_path"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
