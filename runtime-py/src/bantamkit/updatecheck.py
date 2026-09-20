"""The update record on disk, and the five-state line `bantamkit_status` prints from it.

NOTHING HERE REACHES THE NETWORK, AND THAT IS THE WHOLE DESIGN. `selfupdate.py:29-31` keeps
AS-7's third reason alive after the flag itself was granted: the network lives "only on this
flag's own path, never on `bantamkit_status`, never at startup". Measured 2026-09-19 on this
machine, one registry GET costs 0.14-0.46 s on a good network and 10.0 s
(`selfupdate.DEFAULT_TIMEOUT_SECONDS`) on a captive one, against a 0.09 s cold stdio boot —
1.5x to 100x the entire server start, once per session per registered endpoint. So this
module opens ONE file and asks nobody anything. A writer outside both runtimes (the hook,
and `--update` out of the answer it already fetched) puts the number there; this module only
reads it.

WHAT THIS IS NOT. A newer version existing is NOT a degraded condition — ruled 2026-09-19 on
top of `mcpserver.py:906`'s "a footer on every result is noise". The server is serving
correctly; what is true is that a newer one exists. So nothing here is a `Condition`, nothing
here flips `Degraded`, and nothing here appears in `degraded_notice`.

NO TTL LIVES IN THIS READER. The comparison is between the version that is RUNNING and the
version the record last saw, so a stale record cannot manufacture a false "you are stale": if
the operator updated since, running >= recorded and the line goes quiet by itself. Freshness
is the writer's problem alone, which is what keeps every state here observed rather than
inferred, with no timer anywhere in a runtime.

## The record

    <homedir>/.bantamkit/update-check.json

    {"checked_at": "2026-09-19T21:04:11Z",
     "npm":  {"package": "bantamkit-mcp", "latest": "0.36.0"},
     "pypi": {"distribution": "bantamkit", "latest": "0.36.0"}}

Both registries, because they are two registries. THIS runtime reads `pypi.latest`; the Node
runtime reads `npm.latest`. That split is the `docs/porting.md` divergence row — the same
genuinely-different-object as `--update`'s URL row, not a new kind of one.

THE PATH RESOLVES AGAINST `Path.home()` AND NOTHING ELSE. A `.bantamkit` directory relative
to a cwd is a MEMORY STORE, and creating one by accident is a defect class this repo has
already paid for (J54-3, `hostinstall.ts:362`). Nothing in this module writes, creates, or
mkdirs anything — not the file, not the directory — so a missing record is a state with its
own sentence rather than an error or a reason to write.

## THE SENTENCES ARE THE PRODUCT

The five below are named constants and are copied into `runtime-ts` BYTE FOR BYTE, the way
J46-30 copied `selfupdate`'s. Like those, they name the COMMAND `PROGRAM` — `bantamkit-mcp`,
the one word that is true on npm and on PyPI both — and never a package name, because the
PyPI distribution is `bantamkit` and the npm package is `bantamkit-mcp` and a sentence naming
either one could not be identical on both sides.

`{date}` is the `YYYY-MM-DD` PREFIX of `checked_at`, never a locale rendering: a rendered
date would make the two runtimes disagree on a machine set to another locale, and the
`current` state names a date because the record may be months old and "current" without one
would be a claim the record cannot support.

"then reconnect the host" is not politeness. It is measured reason 1 in `selfupdate.py:13-20`
— a running server keeps serving the code it loaded at startup — and an update line that did
not say so would be the confusion AS-7 predicted.

## What counts as unreadable

EVERY shape this reader cannot act on, and it NEVER raises for any of them: bytes that are
not UTF-8, text that is not JSON, JSON that is not an object, no key for this runtime, a
`latest` that is absent or is not a version, and a missing or unparseable `checked_at`. A
leading UTF-8 BOM is NOT one of them — see `load_record`: both runtimes accept it, which is
what `tools/conformance/suites/updatecheck.mjs`'s BOM arms prove and why it is not a
`docs/porting.md` divergence row. The
`checked_at` rule is unconditional rather than applied only to the `current` sentence: a
record that cannot say when it was written is not a record, and one rule is one thing for the
port to reproduce instead of two.

Both checks are deliberately SHAPE checks and not parsers — a `YYYY-MM-DD` prefix, and a
dotted version whose first component is digits — because a `datetime` parse and a PEP 440
parse are each a second, larger thing for `runtime-ts` to reproduce exactly, in service of
strings neither writer here can produce. Same reasoning as `selfupdate._version_key`'s.

Version ordering is `selfupdate.compare_versions`, imported rather than reimplemented. There
is no second comparator in this codebase and this module does not add one.

Layer 5 (Composition): this module reads a file off the operator's home directory and exists
to be called from `mcpserver.bantamkit_status`. It imports no `mcp` and reaches no network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bantamkit.selfupdate import PROGRAM, compare_versions

__all__ = [
    "PROGRAM",
    "KEY",
    "RECORD_DIR",
    "RECORD_NAME",
    "UPDATE_NEVER",
    "UPDATE_AVAILABLE",
    "UPDATE_CURRENT",
    "UPDATE_AHEAD",
    "UPDATE_UNREADABLE",
    "STATE_NEVER",
    "STATE_AVAILABLE",
    "STATE_CURRENT",
    "STATE_AHEAD",
    "STATE_UNREADABLE",
    "STATES",
    "SOURCE_ABSENT",
    "SOURCE_UNREADABLE",
    "SOURCE_RECORD",
    "UpdateStatus",
    "record_path",
    "load_record",
    "read_record",
    "decide",
    "update_status",
    "update_line",
]

#: The key of the record THIS runtime reads. Divergent by construction: `runtime-ts` reads
#: `npm`. Registered as a `docs/porting.md` divergence row by J57-5.
KEY = "pypi"

#: The two path components, spelled once. `.bantamkit` under a HOME is this toolbox's own
#: directory; `.bantamkit` under a cwd is a memory store, and this module never builds one.
RECORD_DIR = ".bantamkit"
RECORD_NAME = "update-check.json"

# --- the sentences ------------------------------------------------------------------
# Copied into `runtime-ts` byte for byte by J57-2. Changing one is a change to both runtimes
# and to the conformance suite, never to this file alone.

#: No record at all. The state of a machine that has never been checked and of one that has
#: been offline since it was installed — deliberately the same state, because they are the
#: same fact about what is known.
UPDATE_NEVER = "update: never checked."

#: The whole point of the feature. `{latest}` and `{installed}` are BOTH here so the reader
#: can falsify the claim, the same reason `selfupdate.COMPARISON` carries both.
UPDATE_AVAILABLE = (
    "update: {program} {installed} is running; the package index has {latest} — run "
    "`{program} --update`, then reconnect the host."
)

#: Names the date because the record may be months old.
UPDATE_CURRENT = "update: {program} {installed} is current as of {date}."

#: A real state, not a curiosity: a checkout build, or a release not yet published, lands
#: here — the same pair `selfupdate.AHEAD` exists for.
UPDATE_AHEAD = (
    "update: {program} {installed} is ahead of the package index, which has {latest}."
)

#: One sentence for every malformed shape. It does not name WHICH shape: the operator cannot
#: act differently on any of them, and a per-shape sentence would be N more strings to port.
UPDATE_UNREADABLE = "update: the update record could not be read."

# --- the states -----------------------------------------------------------------------
# The names are what the non-ruled conformance companion compares: given one record and one
# running version, both runtimes must land in the SAME state, whichever key each one read.

STATE_NEVER = "never"
STATE_AVAILABLE = "available"
STATE_CURRENT = "current"
STATE_AHEAD = "ahead"
STATE_UNREADABLE = "unreadable"
STATES = (STATE_NEVER, STATE_AVAILABLE, STATE_CURRENT, STATE_AHEAD, STATE_UNREADABLE)

# --- what the loader found --------------------------------------------------------------
# Three outcomes and not two, because "there is no file" and "there is a file I cannot read"
# are different sentences. Collapsing them would print `never checked` over a corrupted
# record, which is the one wrong thing a reader of this file can do.

SOURCE_ABSENT = "absent"
SOURCE_UNREADABLE = "unreadable"
SOURCE_RECORD = "record"

#: `0.36.0`, and `0.31.0rc1` too — a first component of digits and dotted parts after it.
#: NOT a PEP 440 parse: see the module docstring. `v1.2.3` and `nightly` are not versions
#: here, and neither registry serves either.
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9A-Za-z_+-]+)*$")

#: The `YYYY-MM-DD` prefix, and only the prefix. Whatever follows it is the writer's
#: business: this module never renders a date, it slices one.
_DATE_PREFIX = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})")


@dataclass(frozen=True)
class UpdateStatus:
    """Which of the five states, and the one line that says so.

    Both halves are returned because the conformance gate needs the STATE (the bit that must
    not differ between runtimes) while `bantamkit_status` needs the LINE (the bit an operator
    reads). Deriving either from the other would be a second decision somewhere.
    """

    state: str
    line: str


def _home() -> Path:
    """`Path.home()`, behind a name so a test can point it somewhere nobody lives.

    The same seam `hostinstall._home` is, for the same reason: every path in this module is
    derived from this one call, so redirecting it is total.
    """
    return Path.home()


def record_path() -> Path:
    """`<homedir>/.bantamkit/update-check.json`. Never relative to a cwd — see the docstring.

    Returns a path whether or not anything is at it. Nothing here creates either component.
    """
    return _home() / RECORD_DIR / RECORD_NAME


def load_record(path: Path | None = None) -> tuple[str, dict[str, Any] | None]:
    """`(SOURCE_*, record)`. Opens one file, creates nothing, and never raises.

    `ENOENT` and `ENOTDIR` are ABSENT — in both, nothing is at the path, and a `.bantamkit`
    that is a regular file leaves the operator in exactly the position of one who has never
    been checked. Every other `OSError` (a directory where the record should be, a mode that
    cannot be read) is UNREADABLE, because something IS there and this reader cannot use it.
    Undecodable bytes and bad JSON are UNREADABLE for the same reason.

    `utf-8-sig` AND NOT `utf-8`, AND THAT IS A PARITY FIX, NOT A PREFERENCE. `json.loads`
    refuses a leading BOM by name (`Unexpected UTF-8 BOM (decode using utf-8-sig)`), while the
    port's `new TextDecoder('utf-8', {fatal: true})` strips one before `JSON.parse` ever sees
    it — so the same file was `unreadable` here and `available` there until J57-5b. PowerShell's
    `Set-Content` and `Out-File` write UTF-8 WITH a BOM by default, so a Windows operator who
    opens this record and saves it again produces exactly those bytes; a record a reader can
    plainly act on is not "a shape this reader cannot act on". `utf-8-sig` strips a LEADING BOM
    and is `utf-8` in every other respect: bytes that are not UTF-8 still raise here and are
    still UNREADABLE.
    """
    target = record_path() if path is None else Path(path)
    try:
        text = target.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, NotADirectoryError):
        return (SOURCE_ABSENT, None)
    except (OSError, ValueError):
        # `UnicodeDecodeError` is a `ValueError`; `IsADirectoryError` and `PermissionError`
        # are `OSError`s. None of them may escape: every failure here is a state.
        return (SOURCE_UNREADABLE, None)
    try:
        payload = json.loads(text)
    except ValueError:
        return (SOURCE_UNREADABLE, None)
    if not isinstance(payload, dict):
        # A list or a bare number is well-formed JSON and is not a record.
        return (SOURCE_UNREADABLE, None)
    return (SOURCE_RECORD, payload)


def read_record(path: Path | None = None) -> dict[str, Any] | None:
    """The parsed record, or `None` when there is not one. Creates nothing, never raises.

    `None` deliberately does NOT say which of absent-or-unreadable it was — a caller that
    needs the difference calls `load_record`, which is the one this module's own decision
    uses. This is the convenience surface for a caller that only wants the object.
    """
    return load_record(path)[1]


def _latest_in(record: dict[str, Any], key: str) -> str | None:
    """`record[key]["latest"]` when it is a version string, else `None`. No exceptions."""
    entry = record.get(key)
    if not isinstance(entry, dict):
        return None
    latest = entry.get("latest")
    if not isinstance(latest, str):
        return None
    latest = latest.strip()
    return latest if _VERSION.match(latest) else None


def _checked_date(record: dict[str, Any]) -> str | None:
    """The `YYYY-MM-DD` prefix of `checked_at`, or `None`. Sliced, never rendered."""
    checked_at = record.get("checked_at")
    if not isinstance(checked_at, str):
        return None
    found = _DATE_PREFIX.match(checked_at.strip())
    return found.group(1) if found else None


def decide(
    installed: str,
    source: str,
    record: dict[str, Any] | None,
    key: str = KEY,
) -> UpdateStatus:
    """The five-state decision, pure: no filesystem, no clock, no network, no TTL.

    Split from the reading so the conformance harness and the tests can construct a state
    directly and so the only thing that touches a disk is `load_record`.
    """
    if source == SOURCE_ABSENT:
        return UpdateStatus(STATE_NEVER, UPDATE_NEVER)
    if source != SOURCE_RECORD or not isinstance(record, dict):
        return UpdateStatus(STATE_UNREADABLE, UPDATE_UNREADABLE)
    date = _checked_date(record)
    latest = _latest_in(record, key)
    if date is None or latest is None:
        return UpdateStatus(STATE_UNREADABLE, UPDATE_UNREADABLE)
    order = compare_versions(installed, latest)
    if order < 0:
        return UpdateStatus(
            STATE_AVAILABLE,
            UPDATE_AVAILABLE.format(program=PROGRAM, installed=installed, latest=latest),
        )
    if order == 0:
        return UpdateStatus(
            STATE_CURRENT,
            UPDATE_CURRENT.format(program=PROGRAM, installed=installed, date=date),
        )
    return UpdateStatus(
        STATE_AHEAD,
        UPDATE_AHEAD.format(program=PROGRAM, installed=installed, latest=latest),
    )


def update_status(
    installed: str,
    key: str = KEY,
    path: Path | None = None,
) -> UpdateStatus:
    """Read the record and decide. The whole reader, in one call, for `bantamkit_status`."""
    source, record = load_record(path)
    return decide(installed, source, record, key)


def update_line(
    installed: str,
    key: str = KEY,
    path: Path | None = None,
) -> str:
    """Exactly one of the five sentences. Always a line: there is no silent state here."""
    return update_status(installed, key, path).line
