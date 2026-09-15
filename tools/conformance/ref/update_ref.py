"""Reference side of `--update`: every arm of `selfupdate.update`, driven offline.

WHY THIS IS NOT `cli_ref.py`. The `cli` suite compares two PROCESSES, and every other argv
line it drives is decided entirely by bytes the harness controls. `--update` is not: the
answer depends on what a package index says, and there is no environment variable on either
runtime that redirects the lookup. There is deliberately no such variable — an env var that
repoints an updater's registry is a real surface with a real hazard, and inventing one so a
test could reach it would be building a product feature for the gate.

So this reaches the two seams the implementers built INTO the flag instead: `fetch` and
`installer`, both keyword arguments of `selfupdate.update` with real defaults. Every arm
below is therefore reachable with NO NETWORK and with NO INSTALLER EVER RUN — the command
is captured and handed back as data, which is the only way a conformance case can compare
`pip install --upgrade bantamkit` against `npm install --global bantamkit-mcp@latest`
without one of the two actually happening to the machine running the suite.

WHAT THIS DID NOT COVER UNTIL J51-6, KEPT AS THE RECORD. The dispatch in
`mcpserver._run_update` — which stream each outcome is written to and whether the process
exits 0 or 1 — was not compared, because the Node counterpart (`runUpdate`) took its install
shape from `currentInstall()` with no seam, and the two halves of this harness are not
installed alike (the reference is imported from an editable install, the port is run out of
`runtime-ts/dist`). Comparing those two answers would have compared two ENVIRONMENTS, which
is the trap `install_ref.py`'s docstring names.

THAT SENTENCE STOPPED BEING TRUE AT J51-5 (`01cee52`), which gave `runUpdate` an `install`
option (default `currentInstall`). So the `dispatch` payload below drives `_run_update`
itself, with the install shape HANDED IN on both sides rather than read off either machine:
here by replacing `mcpserver.current_install`, `mcpserver._version` and
`selfupdate.update` for the duration of one arm — the idiom
`runtime-py/tests/test_selfupdate.py` already uses for the same function, and no product
surface — and on the port through `runUpdate`'s own options. `HOME` and `USERPROFILE` are set
per arm too, because the port's `ephemeral` branch reads a kept install under `homedir()` and
the reference, which never looks, must be handed the same home to make "never looks" a
measurement.

    {"dispatch": [{"id", "installed", "shape" | "undetermined", "source", "home", "latest",
                   "installer": {"code", "output"}, "raise", "reason"}, ...]}
        -> {"dispatch": {id: {"exit": int, "stdout": b64, "stderr": b64, "command": str|None}}}

THE INDEX DOCUMENT IS BUILT ON THIS SIDE, and that is the declared divergence rather than a
convenience. PyPI answers `{"info": {"version": …}}` and the npm registry answers
`{"version": …}` at the top level; each side is handed a document its own registry would
actually return, so what the arms compare is that the same SITUATION produces the same
sentence. An arm that wants the same BYTES on both sides — every garbage arm — passes
`body` instead, and then neither side gets to interpret a shape the other could not see.

    {"arms": [...], "compare": [[installed, latest], ...]}
        -> {"arms": {id: result}, "compare": [int, ...], "constants": {...}, "index": {...}}

`PYTHONPATH` is not set for reference scripts, so the checkout's own `runtime-py/src` is put
at the FRONT of `sys.path` here for the reason `cli_ref.py` pins it (RB-P55): a worktree has
no install of its own and would otherwise silently measure main's source.
"""

from __future__ import annotations

import base64
import json
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "runtime-py" / "src"))

#: A MISSING MODULE IS DATA, NOT A CRASH, and this was MEASURED rather than anticipated.
#: `run.mjs`'s `runPython` calls `die()` on a non-zero exit from a reference script, so an
#: `ImportError` here does not fail the `update` cases — it takes down the WHOLE HARNESS,
#: every suite, with a traceback instead of a case. That is exactly what reverting `--update`
#: on the reference side did to the first version of this file. `cli_ref.py` already carries
#: the rule for this ("THIS SCRIPT ALWAYS EXITS 0 ... the inner exit code is DATA"), and the
#: absence of the module under test is the most important datum there is: it is the defect.
try:
    from bantamkit import selfupdate
except ImportError as exc:  # pragma: no cover - reachable only with the feature reverted
    selfupdate = None  # type: ignore[assignment]
    IMPORT_ERROR: str | None = str(exc)
else:
    IMPORT_ERROR = None


def index_document(version: str) -> str:
    """What PyPI would answer for that version. The port builds the npm shape instead."""
    return json.dumps({"info": {"version": version}})


def run_arm(arm: dict) -> dict:
    """One arm: the report or the refusal, plus what the two seams were actually handed.

    `seen` is not decoration. It is how the case pins that the caller's timeout reaches the
    fetch and that the flag asks its OWN index URL — two facts the report text cannot show,
    and the second of which is the divergence this whole unit is pricing.
    """
    seen: dict = {"url": None, "timeout": None, "command": None}

    def fetch(url: str, timeout: float) -> str:
        seen["url"] = url
        seen["timeout"] = timeout
        failure = arm.get("raise")
        if failure == "timeout":
            raise TimeoutError(arm.get("reason", "timed out"))
        if failure == "unreachable":
            raise OSError(arm.get("reason", "unreachable"))
        if arm.get("body") is not None:
            return str(arm["body"])
        return index_document(str(arm["latest"]))

    def installer(command: list[str]) -> tuple[int, str]:
        seen["command"] = shlex.join(command)
        spec = arm.get("installer") or {}
        return int(spec.get("code", 0)), str(spec.get("output", ""))

    kwargs: dict = {"fetch": fetch, "installer": installer}
    if arm.get("timeout") is not None:
        kwargs["timeout"] = float(arm["timeout"])
    try:
        text = selfupdate.update(
            str(arm["installed"]),
            selfupdate.Origin(str(arm["shape"]), str(arm.get("source", ""))),
            **kwargs,
        )
        ok = True
    except selfupdate.UpdateRefused as exc:
        text = str(exc)
        ok = False
    return {"ok": ok, "text": text, **seen}


def constants() -> dict:
    """Every named sentence, so one case reddens when any of them drifts on one side."""
    names = (
        "PROGRAM",
        "COMPARISON",
        "UP_TO_DATE",
        "AHEAD",
        "UPDATING",
        "PRINTED",
        "UPDATED",
        "RESTART",
        "NO_ROUTE",
        "TIMED_OUT",
        "UNREACHABLE",
        "NOT_A_VERSION",
        "COMMAND_FAILED",
        "SHAPE_UNKNOWN",
        "NOT_JSON",
        "NO_VERSION_FIELD",
        "NO_OUTPUT",
    )
    return {name: getattr(selfupdate, name) for name in names}


def absent(payload: dict) -> dict:
    """The whole answer shape, with the module's absence in every field. See `IMPORT_ERROR`.

    `text` stays a STRING so the suite's splitters, byte cases and per-side literals all keep
    working and redden with a legible value rather than throwing a second time on an object
    that has no `.split`. The port's half of this suite does the same thing for the same
    reason, and the two markers are worded the same way on purpose.
    """
    gone = {"THE REFERENCE HAS NO --update": IMPORT_ERROR}
    gone_text = f"THE REFERENCE HAS NO --update: {IMPORT_ERROR}"
    arms = payload.get("arms", [])
    return {
        "gone": IMPORT_ERROR,
        "arms": {
            str(arm["id"]): {"ok": None, "text": gone_text, "url": None, "timeout": None, "command": None}
            for arm in arms
        },
        "compare": [None for _ in payload.get("compare", [])],
        "constants": gone,
        "index": gone,
        "routes": gone,
    }


def run_dispatch_arm(arm: dict) -> dict:
    """One `_run_update` call, with everything it would read off the machine handed in.

    The streams are captured as BYTES off `sys.stdout.buffer` / `sys.stderr.buffer`, which is
    what `_run_update` writes through, and `SystemExit` is the exit code — the function never
    returns one. Every replaced name is put back in a `finally`, so one arm cannot leak its
    shape into the next.
    """
    import io
    import os

    from bantamkit import mcpserver

    seen: dict = {"command": None}

    def fetch(url: str, timeout: float) -> str:
        failure = arm.get("raise")
        if failure == "unreachable":
            raise OSError(arm.get("reason", "unreachable"))
        return index_document(str(arm["latest"]))

    def installer(command: list[str]) -> tuple[int, str]:
        seen["command"] = shlex.join(command)
        spec = arm.get("installer") or {}
        return int(spec.get("code", 0)), str(spec.get("output", ""))

    def install() -> object:
        if arm.get("undetermined") is not None:
            raise mcpserver._Undetermined(str(arm["undetermined"]))
        return mcpserver.Install(str(arm["shape"]), arm.get("source"))

    real_update = selfupdate.update
    saved = {
        "current_install": mcpserver.current_install,
        "_version": mcpserver._version,
    }
    saved_env = {key: os.environ.get(key) for key in ("HOME", "USERPROFILE")}
    saved_streams = (sys.stdout, sys.stderr)
    out, err = io.BytesIO(), io.BytesIO()
    # Held by name and DETACHED before the streams are put back: a `TextIOWrapper` that is
    # dropped closes the buffer under it, and the bytes are read after that.
    wrappers = (io.TextIOWrapper(out, encoding="utf-8"), io.TextIOWrapper(err, encoding="utf-8"))
    code = 0
    try:
        mcpserver.current_install = install  # type: ignore[assignment]
        mcpserver._version = lambda: str(arm["installed"])  # type: ignore[assignment]
        selfupdate.update = lambda installed, origin, **_k: real_update(  # type: ignore[assignment]
            installed, origin, fetch=fetch, installer=installer
        )
        os.environ["HOME"] = str(arm["home"])
        os.environ["USERPROFILE"] = str(arm["home"])
        sys.stdout, sys.stderr = wrappers
        try:
            mcpserver._run_update()
        except SystemExit as exc:
            code = int(exc.code) if isinstance(exc.code, int) else 1
    finally:
        for wrapper in wrappers:
            wrapper.flush()
            wrapper.detach()
        sys.stdout, sys.stderr = saved_streams
        selfupdate.update = real_update  # type: ignore[assignment]
        mcpserver.current_install = saved["current_install"]  # type: ignore[assignment]
        mcpserver._version = saved["_version"]  # type: ignore[assignment]
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return {
        "exit": code,
        "stdout": base64.b64encode(out.getvalue()).decode("ascii"),
        "stderr": base64.b64encode(err.getvalue()).decode("ascii"),
        "command": seen["command"],
    }


def dispatch(payload: dict) -> dict:
    """The `dispatch` payload, with a missing module or server carried as data like the rest."""
    arms = payload.get("dispatch", [])
    try:
        from bantamkit import mcpserver  # noqa: F401
    except ImportError as exc:  # pragma: no cover - reachable only with the feature reverted
        gone = f"THE REFERENCE HAS NO --update DISPATCH: {exc}"
        return {"dispatch": {str(arm["id"]): {"exit": None, "stdout": "", "stderr": "", "command": gone} for arm in arms}}
    return {"dispatch": {str(arm["id"]): run_dispatch_arm(arm) for arm in arms}}


def main() -> None:
    payload = json.load(sys.stdin)
    if "dispatch" in payload:
        if selfupdate is None:
            gone = f"THE REFERENCE HAS NO --update: {IMPORT_ERROR}"
            json.dump(
                {"dispatch": {str(a["id"]): {"exit": None, "stdout": "", "stderr": "", "command": gone} for a in payload["dispatch"]}},
                sys.stdout,
            )
            return
        json.dump(dispatch(payload), sys.stdout)
        return
    if selfupdate is None:
        json.dump(absent(payload), sys.stdout)
        return
    answer = {
        "arms": {str(arm["id"]): run_arm(arm) for arm in payload.get("arms", [])},
        "compare": [
            selfupdate.compare_versions(str(a), str(b)) for a, b in payload.get("compare", [])
        ],
        "constants": constants(),
        # The divergence that produces no opcode in any report, pinned as a per-side literal
        # because no differential can see it: the URL asked, and the document shape read.
        "index": {
            "url": selfupdate.INDEX_URL,
            "document": index_document("0.31.0"),
            "timeout": selfupdate.DEFAULT_TIMEOUT_SECONDS,
        },
        "routes": sorted(selfupdate.ROUTES),
    }
    json.dump(answer, sys.stdout)


if __name__ == "__main__":
    main()
