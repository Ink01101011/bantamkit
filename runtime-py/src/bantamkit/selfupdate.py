"""Ask the package index what the latest version is, and update when it differs — `--update`.

WHAT THIS OVERTURNS, AND WHAT SURVIVES THE OVERTURNING. `docs/roadmap-agent-stack.md` AS-7
is headed "Tell the operator they are stale; do NOT build `--update`", and `6e506ca` wrote
that down along with `runtime-ts/README.md#updating`'s "There is no `bantamkit-mcp --update`,
deliberately". The user asked for the flag on 2026-09-11 — "เพิ่ม task add update option
เมื่อพิมพ์ให้ไปเช็ค latest version ถ้า mismatch ให้ update auto ถ้า match ให้แสดงคำ uptodate" — so the
flag is built. That is not relitigated here.

But three of AS-7's four reasons were measured facts, not opinions, and a fact does not stop
being true because the decision above it changed. They do not refuse the flag; they decide
what it prints:

1. **A running server keeps serving the code it loaded at startup.** Measured 2026-09-07:
   `runtime-ts/dist/` was rebuilt at 0.30.0 at 08:58 and `bantamkit_status` kept answering
   `version 0.29.1` until the host reconnected at 09:03. So `RESTART` below is not advice
   appended for politeness — it is the only reason a successful update is not a lie. An
   `--update` that printed success and let the caller go on talking to the old process
   would be the confusion AS-7 predicted, and shipping it would have proved AS-7 right.
2. **Most install shapes have nothing to update from a registry.** `ROUTES` below answers
   per shape and NEVER runs an installer for a shape that did not come from the index —
   writing a registry install into a tree the operator manages with `git` is worse than
   doing nothing, and doing nothing while exiting 0 is the J46-4 defect.
3. **It needs the network**, which nothing else in this toolbox does. So: only on this
   flag's own path, never on `bantamkit_status`, never at startup; an explicit timeout; and
   an offline failure is a NAMED refusal on stderr with a non-zero exit, never a traceback.

The fourth reason — that the two-runtime rule makes this expensive, because npm and PyPI are
different registries — is a cost, and J46-31 pays it with a `docs/porting.md` divergence row,
a `ruling:` conformance case, and the non-ruled companion that compares the refusal bit.

## THE SENTENCES ARE THE PRODUCT, AND THIS MODULE IS WHERE THE PORT READS THEM

Every string `--update` can print is a named constant below. J46-30 copies them into
`runtime-ts` BYTE FOR BYTE, the way J46-5 copied J46-4's. Only three things are allowed to
differ between the runtimes, because they are genuinely different objects and not different
spellings of one object:

* the URL asked (`pypi.org` vs `registry.npmjs.org`) and the JSON path the version sits at;
* the command an update runs (`pip install --upgrade` vs `npm install -g`);
* the per-shape route sentences in `ROUTES`, which name those commands.

`COMPARISON`, `UP_TO_DATE`, `AHEAD`, `RESTART`, `UPDATED`, `NO_ROUTE`, `TIMED_OUT`,
`UNREACHABLE`, `NOT_A_VERSION` and `COMMAND_FAILED` are shape-for-shape and byte-for-byte
identical on both sides. They deliberately say `bantamkit-mcp` and never `bantamkit`: the
PyPI distribution is `bantamkit` and the npm package is `bantamkit-mcp`, but the command the
operator typed is `bantamkit-mcp` on both, so naming the command keeps the prose identical
and still names something true.

Layer 5 (Composition): this module reaches the network and shells out to an installer.
Nothing in the runtime imports it — `mcpserver.py` calls it from the flag and returns before
a store or a transport exists, the same shape `--assets-root` and `--install` use.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from bantamkit import __version__

#: The command the operator typed, on BOTH runtimes. Not the distribution name — see the
#: module docstring: PyPI has `bantamkit`, npm has `bantamkit-mcp`, and only this word is
#: the same on both, so only this word can appear in a sentence the port copies verbatim.
PROGRAM = "bantamkit-mcp"

#: The PyPI distribution this interpreter would upgrade. Divergent by construction.
DISTRIBUTION = "bantamkit"

#: The one URL this toolbox ever fetches. Divergent by construction.
INDEX_URL = f"https://pypi.org/pypi/{DISTRIBUTION}/json"

#: Explicit, and short enough that a person who typed the flag does not think it hung.
#: AS-7(3): the network is not on any other path here, so nothing else inherits this.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: What stands in for an installer that printed nothing, so the report has ONE shape rather
#: than a line that is sometimes there. A conditional line is a second thing to port.
NO_OUTPUT = "(nothing)"

# --- the sentences ------------------------------------------------------------------
# Every one of these is copied into `runtime-ts` byte for byte by J46-30. Changing one is a
# change to both runtimes and to the `update` conformance suite, never to this file alone.

#: Line 1 of every report, and the opening of the no-route refusal. It carries BOTH numbers
#: because "up to date" without them is unfalsifiable by the person reading it.
COMPARISON = "{program} {installed} is installed; the package index has {latest}."

#: The user asked for this word specifically: "ถ้า match ให้แสดงคำ uptodate".
UP_TO_DATE = "up to date."

#: The registry BEHIND the installed version. A real state, not a curiosity: a checkout
#: build, or a release that has not been published yet, both land here. Running the
#: installer anyway would print "updated 0.31.0 to 0.30.0" for a `pip` run that correctly
#: did nothing — a remedy that exits 0 having changed nothing.
AHEAD = "the installed version is ahead of the package index; there is nothing to update to."

#: What the command is about to run. The command itself is divergent; this line is not.
UPDATING = "updating from the package index: {command}"

#: The installer's own words, never summarised. Both runtimes print the block the same way.
PRINTED = "the command printed:"

UPDATED = "updated {program} from {installed} to {latest}."

#: AS-7(1), measured. This is the line that makes the success true rather than plausible.
RESTART = (
    "restart the server: a running {program} keeps serving the code it loaded at startup, "
    "so bantamkit_status will report {installed} until the host reconnects."
)

# --- the refusals -------------------------------------------------------------------
# Raised as `UpdateRefused`; the caller prints `error: <message>` on stderr and exits 1.
# Exit 1 and not 0 for ALL of them, including the no-route one: an operator who typed
# `--update` asked for an update, and a command that exits 0 having changed nothing is the
# J46-4 defect. Exit 1 and not 2, because argparse already owns 2 for a usage error and
# `--update` is not one.

NO_ROUTE = (
    "{program} {installed} is installed and the package index has {latest}, but this is a "
    "{shape} install, which --update will not touch. {route}"
)

TIMED_OUT = (
    "the package index did not answer within {timeout} seconds; --update needs the network, "
    "and nothing was changed."
)

UNREACHABLE = (
    "the package index could not be reached: {reason}; --update needs the network, and "
    "nothing was changed."
)

NOT_A_VERSION = (
    "the package index answered, but not with a version for {program}: {why}; nothing was "
    "changed."
)

#: Multi-line on purpose. The installer's output is the only thing that says WHY it failed,
#: and a refusal that swallowed it would send the operator to re-run the command by hand.
COMMAND_FAILED = (
    "the update command exited {code}: {command}\n"
    "{program} {installed} is still installed; nothing was changed.\n"
    "{printed}\n"
    "{output}"
)

#: The install shape itself could not be derived — `mcpserver._Undetermined`, which is what
#: a `pip install git+https://...` origin raises: an origin that is neither an index nor a
#: path on this machine. That exception already carries the operator's next step, so this
#: sentence quotes it rather than paraphrasing it, and refuses rather than picking a route.
SHAPE_UNKNOWN = (
    "--update could not tell how this install was made, so it will not guess an update "
    "route: {reason}"
)

#: The two ways a well-formed HTTP response can still not carry a version, as the `{why}`
#: of `NOT_A_VERSION`. Both runtimes ask a different URL and read a different JSON path, so
#: what is compared is that the same two failures produce the same two sentences.
NOT_JSON = "the response is not JSON"
NO_VERSION_FIELD = "the response carries no version string"

#: Per shape, what the real update route is — the answer to "then how DO I update this?".
#: DIVERGENT BY CONSTRUCTION and registered in `docs/porting.md` by J46-31: these name pip
#: and a Python tree; the port names npm and a built one.
#:
#: `registry` is absent on purpose. It is the one shape that HAS a route through this flag,
#: so a sentence telling its operator to go do it by hand would never be reachable, and an
#: unreachable sentence is one more thing for the port to copy and for nobody to check.
#:
#: `ephemeral` is here even though `mcpserver._derive_install` never answers it — a `pipx
#: run` / `uvx` environment is not distinguishable from an ordinary venv without
#: pattern-matching cache directory names, which is a guess this surface does not make, and
#: that is a declared divergence with a row already. The word is in `INSTALL_SHAPES` on both
#: sides, so the table answers all of it rather than leaving the port a hole to invent.
ROUTES = {
    "local-file": (
        "It was installed from the file {source}, which is not the package index: reinstall "
        "it from that path, or run pip install --upgrade {distribution} to move it onto the "
        "index."
    ),
    "linked": (
        "It is an editable install of the tree at {source}: update that tree where it was "
        "cloned, with git pull."
    ),
    "checkout": (
        "It is running out of a source tree at {source} that no installer recorded: update "
        "that tree where it was cloned, with git pull."
    ),
    "ephemeral": (
        "It is running from an environment that is discarded after the run, so there is "
        "nothing here to update: the next run fetches {latest} by itself."
    ),
}


class UpdateRefused(Exception):
    """A refusal carrying the sentence the operator should read. Never a traceback.

    The same contract `hostinstall.InstallError` has, and for the same reason: `--update`
    can fail for four reasons that are all somebody else's to fix, and a stack trace names
    none of them.
    """


@dataclass(frozen=True)
class Origin:
    """The install shape and the path it can be pointed at, as `--update` needs them.

    DELIBERATELY NOT `mcpserver.Install`. `mcpserver` imports this module for the flag, so
    importing `Install` back would be a cycle; and this keeps the whole decision table
    testable by constructing a shape directly, including the `ephemeral` one this runtime
    never derives. `mcpserver._run_update` does the one-line translation.

    `source` is what `ROUTES` interpolates: the recorded origin for `local-file`/`linked`,
    and the running package directory for `checkout` — which has no recorded origin at all,
    because no installer wrote one, and whose tree IS the thing to update.
    """

    shape: str
    source: str


def latest_from_index_payload(text: str) -> str:
    """The version string out of PyPI's JSON, or a named refusal. Pure — no network here.

    SPLIT FROM THE FETCH SO THE GARBAGE CASE IS TESTED THROUGH THE REAL PARSER. A test that
    stubbed a parsed version would prove nothing about what happens when a captive-portal
    login page comes back with a 200, which is the realistic shape of "the index answered
    and it was not the index".
    """
    try:
        payload = json.loads(text)
    except ValueError:
        raise UpdateRefused(
            NOT_A_VERSION.format(program=PROGRAM, why=NOT_JSON)
        ) from None
    version = ""
    if isinstance(payload, dict):
        info = payload.get("info")
        if isinstance(info, dict) and isinstance(info.get("version"), str):
            version = info["version"].strip()
    if not version:
        raise UpdateRefused(NOT_A_VERSION.format(program=PROGRAM, why=NO_VERSION_FIELD))
    return version


def fetch_index(url: str = INDEX_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    """The ONLY network call in this codebase. One request, one timeout, two failure words.

    THE IMPORT IS FUNCTION-LOCAL AND THAT IS NOT AN EVASION. `mcpserver._file_url_path`
    hand-rolls `url2pathname` precisely because `urllib.request` drags `http.client` and
    `socket` in behind it; a server that never reaches this flag should not pay that at
    import time. The no-network gate in `runtime-py/tests/test_install_shape.py` guards
    eleven named functions in `mcpserver.py` — since J46-32 it is RED on a function-local
    import and on `__import__` too — and this function is in neither that module nor that
    set, which is the point: the network lives in exactly one function that the gate's
    eleven cannot reach.

    THE CONTRACT WITH `update` IS THE EXCEPTION TYPE, because that is what decides which
    sentence the operator reads. `TimeoutError` means the clock ran out; any other `OSError`
    means it could not be reached, and its `str()` is what `UNREACHABLE` interpolates. An
    injected fetch in a test raises the same two to exercise the same two arms.
    """
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    request = Request(  # noqa: S310 - https literal, not caller-supplied
        url,
        headers={"Accept": "application/json", "User-Agent": f"{PROGRAM}/{__version__}"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except HTTPError as exc:
        raise OSError(f"HTTP {exc.code} {exc.reason}") from None
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            raise TimeoutError(str(reason)) from None
        raise OSError(str(reason) or exc.__class__.__name__) from None
    # `replace` rather than `strict`: a body that is not UTF-8 is not a version either, and
    # it should reach `latest_from_index_payload` and be refused BY NAME, not raise here.
    return raw.decode("utf-8", "replace")


def upgrade_command() -> list[str]:
    """What a `registry` install upgrades with, on THIS interpreter.

    `sys.executable -m pip` and never a bare `pip`: the server may be running from a venv
    whose `pip` is not the one first on `PATH`, and upgrading the wrong environment is a
    failure that reports success. The same reason `hostinstall.this_command()` records an
    absolute console-script path rather than a name to look up.
    """
    return [sys.executable, "-m", "pip", "install", "--upgrade", DISTRIBUTION]


def run_installer(command: list[str]) -> tuple[int, str]:
    """Run the installer, capture what it said, return both. The only side effect here.

    CAPTURED RATHER THAN INHERITED so that the report has one shape whether or not anybody
    is watching, and so that a test can inject a substitute and assert on the command
    WITHOUT a real install ever running. `stderr` is folded into `stdout` because pip
    writes its resolution notes to one and its warnings to the other, and an operator
    reading a failure needs them interleaved in the order they happened.
    """
    done = subprocess.run(  # noqa: S603 - argv list built here, never a shell string
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return done.returncode, done.stdout.decode("utf-8", "replace")


def _version_key(version: str) -> list[tuple[int, int, str]]:
    """A dotted version as something orderable, deterministically, without claiming PEP 440.

    Split on `.`; a component that is all digits sorts as a NUMBER, anything else sorts as
    a STRING after every number in that position. So `0.9.0 < 0.10.0` (the thing a plain
    string compare gets wrong and the reason this exists) and `0.31.0 < 0.31.0rc1`.

    THE PRERELEASE ORDERING IS WRONG BY PEP 440 AND RIGHT BY THIS FUNCTION'S CONTRACT, and
    it is spelled out rather than fixed because bantamkit has never published a prerelease
    to either registry: implementing PEP 440 here would be a second, larger thing for
    `runtime-ts` to reproduce exactly, in service of a case neither index can currently
    return. What matters is that both runtimes are wrong in the SAME direction, which a
    conformance case can pin and a reader can check. If a prerelease is ever published,
    this is the function to fix — in both runtimes, in one job.
    """
    key: list[tuple[int, int, str]] = []
    for part in version.split("."):
        if part.isdigit():
            key.append((0, int(part), ""))
        else:
            key.append((1, 0, part))
    return key


def compare_versions(installed: str, latest: str) -> int:
    """-1 when the index is ahead, 0 when they agree, 1 when the installed version is ahead.

    The shorter of the two is padded with numeric zeros, so `0.30` and `0.30.0` agree —
    which is what a person means by them and what both registries would print for one
    release.
    """
    left, right = _version_key(installed), _version_key(latest)
    pad = (0, 0, "")
    while len(left) < len(right):
        left.append(pad)
    while len(right) < len(left):
        right.append(pad)
    if left == right:
        return 0
    return 1 if left > right else -1


#: The `checked_at` stamp's shape, spelled rather than defaulted. `datetime.isoformat()`
#: renders `+00:00` and `Date.prototype.toISOString` renders `.000Z`, so a record written by
#: the two runtimes would differ in bytes neither reader cares about. Both sides render this
#: one shape instead, and `runtime-ts` strips its milliseconds to reach it.
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def record_update(latest: str, now: str | None = None) -> bool:
    """Put the version this flag just fetched into the record `bantamkit_status` reads.

    NO SECOND NETWORK CALL AND NO NEW FAILURE MODE, which is the whole reason the writer is
    here rather than anywhere a reader could reach. `update` already holds `latest` — it was
    parsed out of the answer the operator's own `--update` asked for — so this writes what is
    in hand. `updatecheck` reads that file and NEVER writes it; the split is structural and
    both halves are gated (`test_updatecheck.py::test_the_source_writes_nothing_and_reaches_
    no_network`), so a future reader cannot grow a write by accident.

    `updatecheck` IS IMPORTED INSIDE THE BODY, and not for style. `updatecheck` imports
    `PROGRAM` and `compare_versions` from THIS module at its top level, so a module-level
    import here would be a cycle that fails at interpreter start. The function-local import
    is the direction that works, and `_names_reached_by` in `test_selfupdate.py` sees it —
    `bantamkit.updatecheck` is on that gate's allowlist by name.

    IT CREATES NO DIRECTORY. `<homedir>/.bantamkit` is made by an install, and a `--update`
    run on a machine that has never had one writes nothing rather than deciding where this
    toolbox's home directory should be. A cwd-relative `.bantamkit` is a MEMORY STORE (J54-3)
    and the path here comes from `updatecheck.record_path()`, which hangs off `_home()`.

    THE OTHER RUNTIME'S KEY IS LEFT EXACTLY AS FOUND. npm and PyPI are two registries that
    can disagree at one version number — job56 shipped a day where they did — so this fills
    `updatecheck.KEY` and copies the rest of the record through untouched. An UNREADABLE
    record is replaced rather than merged: there is nothing in it to preserve.

    AMENDED 2026-09-21 (job62, J62-13). The paragraph above was true of the two ENTRIES and
    false of the record, because this writer also stamped the record's own `checked_at` —
    the fallback that dates every entry without a stamp of its own. Overwriting it is what
    destroyed the only record of when the OTHER registry was last asked, and the other
    runtime's reader then dated its stale number by a check of a registry it does not read
    (measured, `updatecheck`'s docstring). So:

    THIS WRITER STAMPS ITS OWN ENTRY AND NEVER THE RECORD'S `checked_at`. The record's stamp
    means "a writer refreshed this record AS A WHOLE", and `--update` holds one registry's
    answer by construction — it is the version this flag itself fetched, and there is no
    second network call here to get the other one. `tools/hooks/update-probe.mjs` is the only
    writer that asks both, so it is the only one that may write that field.

    TWO CONSEQUENCES, BOTH WANTED. A record this writer creates from nothing carries no
    record-level stamp at all, so the hook's 24 h TTL treats it as DUE rather than fresh and
    the probe runs and fills the other half — where before, an operator running `--update`
    more often than daily starved the probe indefinitely. And on a merge, the entry this
    writer did not fill keeps falling back to the record's OLD stamp, which is exactly when
    that entry was last written.

    TEMP FILE AND RENAME, so a reader never sees half a record: `os.replace` is atomic on
    POSIX and on Windows, and the temp file is made in the SAME directory so the rename is
    never across a filesystem.

    RETURNS whether it wrote, and RAISES FOR NOTHING. A failed write must not turn a
    successful `--update` into a failure: the operator's install was updated either way, and
    the worst case is a status line that still says `never checked`.
    """
    # The MODULE is named in the import so the gate's allowlist can name it too: a
    # `from bantamkit import updatecheck` records only `bantamkit`, which would let any
    # sibling module in under the same allowance.
    from bantamkit.updatecheck import KEY, SOURCE_RECORD, load_record, record_path

    path = record_path()
    directory = path.parent
    if not directory.is_dir():
        return False
    source, existing = load_record(path)
    payload: dict[str, object] = dict(existing) if source == SOURCE_RECORD and existing else {}
    stamp = now or datetime.now(UTC).strftime(STAMP)
    payload[KEY] = {"distribution": DISTRIBUTION, "latest": latest, "checked_at": stamp}
    try:
        body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    except (TypeError, ValueError):
        return False
    try:
        handle, temporary = tempfile.mkstemp(
            dir=str(directory), prefix=".update-check-", suffix=".json"
        )
    except OSError:
        return False
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False
    return True


def update(
    installed: str,
    origin: Origin,
    *,
    fetch: Callable[[str, float], str] = fetch_index,
    installer: Callable[[list[str]], tuple[int, str]] = run_installer,
    url: str = INDEX_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """The whole flag: ask the index, compare, and act — or refuse, by name.

    THE TWO SEAMS ARE `fetch` AND `installer`, and they are keyword arguments with real
    defaults rather than module globals a test monkeypatches. A test that reaches PyPI fails
    on a plane and passes for the wrong reason off a cache; a test that ran a real installer
    would rewrite the developer's own environment. Both substitutes are handed in here, so
    every arm below is reachable offline and the installer command is CAPTURED, never run.

    THE INDEX IS ASKED BEFORE THE SHAPE IS JUDGED, and that order is deliberate. The user
    asked the flag to go and check the latest version; an operator on a checkout that is
    five releases behind is owed that number even though this flag will not be the thing
    that installs it. The shape decides the ACTION, never whether the question is asked.
    """
    try:
        body = fetch(url, timeout)
    except TimeoutError:
        raise UpdateRefused(TIMED_OUT.format(timeout=_seconds(timeout))) from None
    except OSError as exc:
        raise UpdateRefused(UNREACHABLE.format(reason=exc)) from None

    latest = latest_from_index_payload(body)

    # THE RECORD IS WRITTEN HERE AND NOT IN ONE OF THE ARMS BELOW, because what it records is
    # "the index said X on this date" — which is true the moment the fetch returned, whatever
    # this flag then decides to do about it. An operator whose shape has no route gets the
    # refusal AND a `bantamkit_status` that now knows the number; one who is already current
    # gets a line that says so with a date. The return value is deliberately dropped: a record
    # that could not be written is not a reason to fail an update that worked.
    record_update(latest)

    header = COMPARISON.format(program=PROGRAM, installed=installed, latest=latest)
    order = compare_versions(installed, latest)
    if order == 0:
        return f"{header}\n{UP_TO_DATE}"
    if order > 0:
        return f"{header}\n{AHEAD}"

    if origin.shape != "registry":
        route = ROUTES.get(origin.shape)
        if route is None:
            # An unknown shape word is a fact about THIS code being behind
            # `INSTALL_SHAPES`, not about the operator's machine, and inventing a route for
            # it would be the guess the whole install-shape surface refuses to make.
            route = (
                f"There is no recorded update route for a {origin.shape} install, so "
                "--update will not guess one."
            )
        raise UpdateRefused(
            NO_ROUTE.format(
                program=PROGRAM,
                installed=installed,
                latest=latest,
                shape=origin.shape,
                route=route.format(
                    source=origin.source, distribution=DISTRIBUTION, latest=latest
                ),
            )
        )

    command = upgrade_command()
    rendered = shlex.join(command)
    code, output = installer(command)
    printed = output.strip() or NO_OUTPUT
    if code != 0:
        raise UpdateRefused(
            COMMAND_FAILED.format(
                code=code,
                command=rendered,
                program=PROGRAM,
                installed=installed,
                printed=PRINTED,
                output=printed,
            )
        )
    return "\n".join(
        (
            header,
            UPDATING.format(command=rendered),
            PRINTED,
            printed,
            UPDATED.format(program=PROGRAM, installed=installed, latest=latest),
            RESTART.format(program=PROGRAM, installed=installed),
        )
    )


def _seconds(timeout: float) -> str:
    """`10` rather than `10.0`, because the sentence is read by a person, not parsed.

    Node renders a whole number without a fractional part by default, so spelling it here
    is what keeps `TIMED_OUT` byte-identical across the two runtimes instead of ruled.
    """
    if float(timeout).is_integer():
        return str(int(timeout))
    return str(timeout)
