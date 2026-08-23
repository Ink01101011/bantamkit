"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from typing import Any

import bantamkit
from bantamkit import __version__, shiftwork
from bantamkit.assets import AssetNotFound, assets_root, load_skill, load_tool_asset
from bantamkit.client import BantamError
from bantamkit.contract import schema_error, schema_retry_feedback
from bantamkit.eventlog import EventLog
from bantamkit.mcpreport import build_report as build_mcp_report
from bantamkit.mcpreport import resolve_event_log_path
from bantamkit.memory import DEFAULT_INDEX_BUDGET, Memory

try:
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ResourceError
    from mcp.server.mcpserver.tools import Tool as SDKTool
except ImportError:  # surfaced as a clear SystemExit in main()
    MCPServer = None  # type: ignore[assignment]
    ResourceError = None  # type: ignore[assignment]
    SDKTool = None  # type: ignore[assignment]

_INSTALL_HINT = 'bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"'

SERVER_NAME = "bantamkit"


def _version() -> str:
    """The version this checkout declares — never the one the last install recorded.

    RB-P45: `metadata.version("bantamkit")` reads the installed dist-info, and a *stale*
    editable install is not a `PackageNotFoundError`, so the old body could not fall back
    — it returned a confidently wrong number. `__version__` is the same bytes hatchling
    builds the wheel from, is already imported by the time this module exists, and has no
    failure mode to fall back from.
    """
    return __version__


class _Undetermined(Exception):
    """A build fact that could not be derived, carrying WHY. Never becomes a value."""


def _unavailable(reason: str) -> dict[str, str]:
    """The shape an underivable fact takes on the wire.

    `RB-P51`'s rule is that "could not determine" must never read as a value. A sentinel
    string (`""`, `"unknown"`, `"none"`) is the defect that rule names: it sits in a
    field typed as a path or a digest and a caller comparing fields reads it as one. An
    object cannot — every derivable field here is a string, an int or a bool, so a caller
    that got a dict knows it got no answer, and the key it must read is the reason.

    What this does NOT buy, said plainly: two servers that both failed to derive the same
    fact carry the same object and compare equal on it. Unavailability is visible, not
    discriminating. That is why `build_id` refuses to exist at all when one of its inputs
    is unavailable, instead of hashing the failure text into something that looks like an
    identity and agrees with every other failure.
    """
    return {"unavailable": reason}


def _tree_digest(root: Path, files: list[Path]) -> str:
    """sha256 over (relative path, size, bytes) of every file, in sorted path order.

    Paths are folded in so that moving a file is a different build, and sizes so that a
    concatenation cannot be re-partitioned into the same stream. The digest is over the
    CONTENT and its layout under `root` — never over `root` itself — which is the whole
    reason two installs of one build at two different paths fingerprint identically while
    one edited line anywhere does not.
    """
    running = hashlib.sha256()
    for path in files:
        payload = path.read_bytes()
        running.update(path.relative_to(root).as_posix().encode("utf-8"))
        running.update(b"\0%d\0" % len(payload))
        running.update(payload)
    return "sha256:" + running.hexdigest()


def _code_fingerprint() -> tuple[str, int, Path]:
    """Fingerprint the source the interpreter imported this package from.

    `bantamkit.__file__` is the same resolution the import system already performed, so
    this reads the tree that is actually serving the call — not a checkout that happens
    to be nearby, which is exactly the confusion `RB-P55` names inside a worktree.

    TWO EXCLUSIONS, AND THE SECOND WAS MEASURED RATHER THAN REASONED. `__pycache__`
    because bytecode is derived, and a build must not fingerprint differently before and
    after its first import. `<package>/assets/` because THE ASSET PACK LIVES INSIDE THE
    PACKAGE IN A WHEEL and beside the repository root in a checkout (`RB-P85`,
    `docs/install.md`, `assets_root()`), while carrying eleven `.py` files of its own
    (`assets/evals/devteam/repo/`): a walk that swept them in counted 22 files from an
    editable checkout and 33 from a wheel-shaped install OF IDENTICAL CONTENT, and
    reported the two as different builds. That is the false positive this whole surface
    exists to avoid — a machine's user-scope wheel and project-scope editable install of
    one commit are ONE build. The pack is fingerprinted in full by `_assets_fingerprint`,
    so nothing goes unmeasured; it is measured once, under the field that names it.
    """
    located = getattr(bantamkit, "__file__", None)
    if not located:
        raise _Undetermined("bantamkit has no __file__; the running code is not on disk")
    root = Path(located).resolve().parent
    packed_assets = root / "assets"
    files = sorted(
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not p.is_relative_to(packed_assets)
    )
    if not files:
        # A digest over nothing is a constant, and two servers that both computed one
        # would agree — the vacuity this whole surface exists to prevent.
        raise _Undetermined(f"no .py source found under {root}")
    try:
        return _tree_digest(root, files), len(files), root
    except OSError as exc:
        raise _Undetermined(f"unreadable source under {root}: {exc}") from None


def _assets_fingerprint() -> tuple[str, int, Path]:
    """Fingerprint the asset pack this build would load.

    Every file, not just the ones some loader knows about: `assets_root()` is a directory
    the server reads at call time, and a pack carrying an extra or an edited file is a
    different pack whether or not today's code opens it. `contracts/default.yaml` is the
    reason — `RB-P84` measured it as the one asset that differed between two live builds
    while no resource template exposed it, so it was invisible on every probed surface.
    """
    try:
        root = assets_root()
    except AssetNotFound as exc:
        raise _Undetermined(f"assets_root() could not resolve a pack: {exc}") from None
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise _Undetermined(f"asset pack at {root} contains no files")
    try:
        return _tree_digest(root, files), len(files), root
    except OSError as exc:
        raise _Undetermined(f"unreadable asset under {root}: {exc}") from None


def build_identity() -> dict[str, Any]:
    """What this build can honestly say about itself, over the protocol.

    `RB-P84`: two `bantamkit` endpoints are registered under one name on a developer
    machine, both are spawned, and their advertised surfaces were byte-identical over
    6864 bytes. `tools/mcpdrift/mcpdrift.py` closes that from OUTSIDE — it tells a person
    two endpoints differ. This closes the other half: an agent holding a tool result can
    ask which build produced it, mid-call, without reading the server's filesystem.

    THE FIELD THAT IS THE ANSWER IS `build_id`, and it is deliberately computed from
    content alone — server name, declared version, code digest, asset digest. `version`
    is echoed but is not identity: it moves on release bumps, it has already lied in this
    program (`RB-P45`, a `v0.25.0` checkout advertising `0.3.0`), and refreshing a pinned
    install from HEAD leaves both endpoints reading one number while one keeps drifting
    forward. `package_path`, `assets_root` and `interpreter` are LOCATION, reported
    because they are what a person acts on, and kept out of `build_id` because two
    installs of one build at two paths are one build.

    WHAT IS REFUSED, and it is a refusal rather than a gap: no commit. See `git_commit`.

    WHAT THIS DOES NOT COVER, stated so the gap is visible rather than implied: the
    dependency tree. `mcp_sdk_version` is reported for the one SDK that shapes every
    answer on this wire, and nothing else is — two builds whose `pydantic` differs
    fingerprint identically here. `tools/mcpdrift/mcpdrift.py`'s `recall_bad_arg_type`
    probe is the surface that catches that, and it is a person's instrument, not this one.
    """
    identity: dict[str, Any] = {"server_name": SERVER_NAME, "version": _version()}

    try:
        digest, count, root = _code_fingerprint()
        identity["code_digest"] = digest
        identity["code_files"] = count
        identity["package_path"] = str(root)
    except _Undetermined as exc:
        for field_name in ("code_digest", "code_files", "package_path"):
            identity[field_name] = _unavailable(str(exc))

    try:
        digest, count, root = _assets_fingerprint()
        identity["assets_digest"] = digest
        identity["assets_files"] = count
        identity["assets_root"] = str(root)
    except _Undetermined as exc:
        for field_name in ("assets_digest", "assets_files", "assets_root"):
            identity[field_name] = _unavailable(str(exc))

    # Location, never identity: `BANTAMKIT_ASSETS` redirects the pack, so whether the
    # root was chosen by the operator or resolved by the package is a fact a caller
    # comparing two endpoints needs. A bool, so it is never confusable with a missing one.
    identity["assets_root_from_env"] = bool(os.environ.get("BANTAMKIT_ASSETS"))

    identity["git_commit"] = _unavailable(
        "refused, not missing. An installed wheel carries no repository at all, and "
        "reading a checkout's HEAD would describe the TREE rather than the bytes that "
        "were imported — an edited working copy serves different code under an unchanged "
        "sha, which is precisely the confusion RB-P84 filed. A commit reported that way "
        "would be a value that is sometimes a lie; `code_digest` is derived from the "
        "bytes themselves and cannot be."
    )

    identity["interpreter"] = sys.executable or _unavailable(
        "sys.executable is empty; this interpreter cannot name its own binary"
    )
    identity["python_version"] = platform.python_version()
    identity["python_implementation"] = platform.python_implementation()
    try:
        # The SDK's OWN version, from the only source there is for a third-party dist.
        # This is NOT a rollback of RB-P45: bantamkit's version still comes from
        # `__version__` (see `_version`), this number is never used for it, and it is
        # kept OUT of `build_id` for the same reason RB-P45 gives — an editable install's
        # dist-info can be stale, so it is reported as environment, not as identity.
        identity["mcp_sdk_version"] = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        identity["mcp_sdk_version"] = _unavailable(
            "no installed distribution metadata for `mcp`; the SDK is importable but "
            "not pip-recorded, so its version is not knowable here"
        )

    identity_inputs = ("server_name", "version", "code_digest", "assets_digest")
    inputs = {key: identity[key] for key in identity_inputs}
    missing = sorted(key for key, value in inputs.items() if isinstance(value, dict))
    if missing:
        identity["build_id"] = _unavailable(
            "computed from server_name, version, code_digest and assets_digest; could "
            f"not derive {', '.join(missing)}. A build_id short of an input would agree "
            "with every other build that lost the same input, so none is reported."
        )
    else:
        canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
        identity["build_id"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    identity["unavailable"] = sorted(
        key
        for key, value in identity.items()
        if isinstance(value, dict) and "unavailable" in value
    )
    return identity


def _from_manifest(fn: Callable[..., Any], name: str) -> Any:
    """Bind one handler to its manifest entry — description, BOTH schemas, and the surface.

    The asset pack under `assets/tools/` is the tool contract for every runtime that
    serves this surface, so the schema has to arrive WITH the registration rather than be
    corrected onto it afterwards. Until this function existed, `build_server` registered
    each handler by decorator (description from a Python constant, schema derived from the
    signature) and then reached through a private attribute of the SDK's tool manager to
    overwrite two of the schemas after the fact. The served bytes were right, but only for
    as long as that attribute stayed reachable under that name: an SDK that renamed it
    would have gone back to advertising whatever the Python signature says, silently, and
    a port to a second runtime would have had to re-read Python to learn the contract.

    `MCPServer(..., tools=[...])` is the public seam. The object handed to the constructor
    already carries the manifest's description and schema, so registration and truth are
    one step. `from_function` still derives `fn_metadata` from the signature, and that is
    what validates arguments at CALL time; the signatures mirror the manifest. Only what
    is ADVERTISED changes hands here, and it now has exactly one source.

    `output_schema` goes through the same seam by a different route. It is not a field on
    the SDK's `Tool`; it is a `cached_property` returning `fn_metadata.output_schema`, and
    `MCPServer.list_tools` copies it straight onto the wire's `outputSchema`. Putting the
    manifest's value in the instance dict is what a `cached_property` reads first, so the
    override lands — and it lands on the ADVERTISEMENT ONLY, because the call path
    (`FuncMetadata.convert_result`) consults `fn_metadata`, which is untouched. That is
    the same division `parameters` already has: the manifest says what is promised, the
    signature still says what is enforced.

    The `surfaces` check is what makes that field load-bearing. `assets/tools/` serves the
    eval agent too, and a manifest entry that does not claim `mcp` must not become a tool
    on this server — otherwise the field is a comment, and a port that trusts it would
    serve a different set of tools than this runtime does.
    """
    asset = load_tool_asset(name)
    if "mcp" not in asset["surfaces"]:
        raise BantamError(
            f"tool asset {name!r} does not claim the mcp surface: {asset['surfaces']}"
        )
    tool = SDKTool.from_function(fn, name=asset["name"], description=asset["description"])
    return tool.model_copy(
        update={"parameters": asset["parameters"], "output_schema": asset["output_schema"]}
    )


@contextmanager
def _record_raise(log: EventLog, tool: str) -> Iterator[None]:
    """Record the TYPE of anything that escapes, then let it escape unchanged.

    The host already logs that a tool failed and how long it took; what it cannot say is
    which exception the component threw — and the one place it tried, it leaked an
    argument value doing it (`eventlog.py`'s docstring, measured). So: `type(exc).__name__`
    and nothing else, via `EventLog.raised`, which has no other input available to it.

    `BaseException` rather than `Exception` deliberately. A `KeyboardInterrupt` or a
    `SystemExit` out of a handler is exactly the shape whose cause is hardest to
    reconstruct afterwards, the record costs one line, and the `raise` is unconditional
    — nothing here decides whether the tool fails, only whether the failure was written
    down. `EventLog.record` swallows its own `OSError`, so this cannot mask the original.
    """
    try:
        yield
    except BaseException as exc:
        log.raised(tool, exc)
        raise


def _record_result(log: EventLog, tool: str, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a shiftwork handler and record its `result` — the register's OWN verdict.

    Every `shiftwork` entry point answers a dict whose `result` key is the decision it
    made: `brief`, `escalate`, `success`, `ok`, `status`, `error`. `clock_in` returning
    `escalate` is the sharp case — the register's whole stop-and-ask contract, invisible
    in the host's log because the tool call succeeded. Reading the key is reading the
    decision; nothing here inspects a `reason` string, which is prose and can carry a
    checkpoint path.

    `raised` is the outcome for an ESCAPING EXCEPTION and is spelled differently from
    `error` on purpose: `result: "error"` is a refusal the register composed and returned
    normally, and collapsing the two would lose the only distinction between a checkpoint
    that was rejected and a handler that fell over.
    """
    with _record_raise(log, tool):
        answer = call()
    log.record(tool, str(answer.get("result", "unknown")))
    return answer


def build_server(memory: Memory, log: EventLog | None = None) -> Any:
    """Assemble the MCP server around one Memory instance (the per-person state).

    `log` is the event-log sink (`docs/eventlog.md`), resolved from `BANTAMKIT_EVENT_LOG`
    when the caller does not supply one and DISABLED unless that variable asks for it.
    It is a parameter and not only an environment read so that a test can inject a fixed
    clock and a scratch path without setting a process-wide variable — the same seam
    `runtime-ts` needs for its half of the conformance case.

    EVERY HANDLER BELOW RECORDS FROM A DECISION, NEVER FROM ITS REPLY. `memory_save`
    reads `SaveOutcome.status`, `memory_recall` reads `RecallOutcome.status`, the three
    shiftwork tools read the register's own `result` key, `validate_json` reads the
    `valid` bool it is about to return, and `build_identity` reads the length of the
    `unavailable` list it computed. Not one of them looks at the words. That is the
    property `test_eventlog.py::test_the_record_does_not_move_when_the_reply_wording_
    does` holds: change a reply's wording and the record must be byte-identical.
    """
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    if log is None:
        log = EventLog.from_env(memory.store.root)

    def memory_save(
        type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> str:
        with _record_raise(log, "memory_save"):
            outcome = memory.save_outcome(type, name, description, body, links)
        if log.enabled:
            # Only when a log is actually on: `index_accounting` re-parses `facts/`, and
            # a diagnostic must not put that on the path of an operator who did not ask
            # for one. Headroom is left to the reader rather than stored — it is
            # `budget - index_bytes`, and a derived field is a second thing to keep true.
            index_bytes, budget = memory.index_accounting()
            detail: dict[str, Any] = {"budget": budget}
            if index_bytes is not None:
                detail["index_bytes"] = index_bytes
            log.record("memory_save", outcome.status, detail)
        return outcome.reply

    def memory_recall(query: str, k: int | None = None) -> str:
        if k is not None:
            k = max(1, min(k, 5))  # the advertised schema's bounds; clients may ignore it
        with _record_raise(log, "memory_recall"):
            outcome = memory.recall_outcome(query, k)
        detail = {
            "budget": outcome.budget,
            "candidates": outcome.candidates,
            "layers": outcome.layers,
            "reached": outcome.reached,
            "returned": outcome.returned,
            "unreadable": outcome.unreadable,
        }
        if outcome.source is not None:
            detail["source"] = outcome.source
        log.record("memory_recall", outcome.status, detail)
        return outcome.reply

    def validate_json(output: str, schema: dict[str, Any]) -> dict[str, Any]:
        with _record_raise(log, "validate_json"):
            error = schema_error(output, schema)
        if error is None:
            log.record("validate_json", "valid")
            return {"valid": True, "feedback": None}
        log.record("validate_json", "invalid")
        return {
            "valid": False,
            "feedback": schema_retry_feedback(error),
        }

    def shiftwork_clock_in(checkpoint: str) -> dict[str, Any]:
        return _record_result(log, "shiftwork_clock_in", lambda: shiftwork.clock_in(checkpoint))

    def shiftwork_clock_out(
        checkpoint: str,
        unit_id: str,
        status: str,
        handoff_patch: dict[str, Any],
        history_entry: dict[str, Any],
        accounting: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _record_result(
            log,
            "shiftwork_clock_out",
            lambda: shiftwork.clock_out(
                checkpoint, unit_id, status, handoff_patch, history_entry, accounting
            ),
        )

    def shiftwork_status(checkpoint: str) -> dict[str, Any]:
        return _record_result(log, "shiftwork_status", lambda: shiftwork.status(checkpoint))

    # A TOOL and not a resource or an `initialize` field, because the gap RB-P84 names is
    # an AGENT MID-CALL: the host reads `serverInfo` once at handshake and the
    # tool-calling model never sees it, and `resources/read` is a host-facing surface
    # most clients never expose to the model at all. A tool is in `tools/list`, so the
    # model that just received a `memory_recall` answer can ask who answered it.
    def build_identity_tool() -> dict[str, Any]:
        with _record_raise(log, "build_identity"):
            identity = build_identity()
        # The COUNT of underivable fields, not the fields and not the digests. A code
        # digest is by construction different in the two runtimes — they fingerprint two
        # different trees (`docs/porting.md`'s divergence table says so about `build_id`)
        # — so putting one in a record that a conformance case byte-compares would make
        # the record unportable to buy nothing the tool's own reply does not already say.
        log.record(
            "build_identity",
            "partial" if identity["unavailable"] else "complete",
            {"unavailable": len(identity["unavailable"])},
        )
        return identity

    # The served surface, in one place, read out of the asset pack. Adding a tool here
    # without an asset raises AssetNotFound at startup — the manifest cannot drift behind
    # the server, because the server cannot start without it.
    tools = [
        _from_manifest(memory_save, "memory_save"),
        _from_manifest(memory_recall, "memory_recall"),
        _from_manifest(validate_json, "validate_json"),
        _from_manifest(shiftwork_clock_in, "shiftwork_clock_in"),
        _from_manifest(shiftwork_clock_out, "shiftwork_clock_out"),
        _from_manifest(shiftwork_status, "shiftwork_status"),
        _from_manifest(build_identity_tool, "build_identity"),
    ]

    server = MCPServer(
        SERVER_NAME,
        instructions=load_skill("memory"),
        version=_version(),
        tools=tools,
    )

    @server.resource("bantamkit://skills/{name}")
    def skill_resource(name: str) -> str:
        try:
            return load_skill(name)
        except AssetNotFound:
            raise ResourceError(f"unknown skill asset: {name}") from None

    @server.resource("bantamkit://rubrics/{name}")
    def rubric_resource(name: str) -> str:
        path = assets_root() / "rubrics" / f"{name}.yaml"
        if not path.is_file():
            raise ResourceError(f"unknown rubric asset: {name}")
        return path.read_text(encoding="utf-8")

    return server


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bantamkit-mcp",
        description="bantamkit MCP server (stdio): per-person memory + JSON validation.",
    )
    # POSITION IS WIRE-VISIBLE. argparse prints optionals in the order they were added, so
    # this line -- not any format string -- decides where `[--assets-root]` sits in the
    # generated usage, and the Node formatter has to reproduce that. It goes FIRST, beside
    # the `-h` argparse adds for us, because those two share a property nothing below them
    # has: they print and return 0 without a memory store, a transport, or a server. Every
    # flag after them configures a server that is actually going to run.
    parser.add_argument(
        "--assets-root",
        action="store_true",
        help="print the resolved asset pack root and its file count, then exit",
    )
    parser.add_argument("--k", type=int, default=3, help="default recall budget (default: 3)")
    # The index is loaded into every prompt, so its ceiling is a deployment decision.
    # It had no flag: 4096 was reachable only by editing `store.py`, which made
    # `docs/memory.md`'s "lifecycle is an operator decision" true of the design and
    # false of the deployment. Lifecycle ACTIONS stay off this process — it speaks MCP
    # over stdout — and live on `python -m bantamkit.memory`.
    parser.add_argument(
        "--index-budget",
        type=int,
        default=DEFAULT_INDEX_BUDGET,
        metavar="BYTES",
        help=f"memory index byte budget (default: {DEFAULT_INDEX_BUDGET})",
    )
    # WHY THIS IS A FLAG ON THIS PROCESS AND NOT A NEW ENTRY POINT.
    # `memory/__main__.py` argues lifecycle needs a stream it owns, because this process
    # speaks MCP over stdout. True of a RUNNING server; not true of a flag that prints and
    # returns before any transport exists -- `--assets-root` above is the precedent. And it
    # is decisive here rather than merely convenient: `runtime-ts/package.json` declares
    # exactly one bin, `bantamkit-mcp`, so anything hung off `python -m ...` is unreachable
    # in a pure-npx install, which is the shipped product.
    #
    # POSITION IS DELIBERATE AND IT IS NOT BESIDE `-h`. `--assets-root` sits first because
    # it needs NOTHING; this one honours `--store`/`--start` to find the event log, so it
    # reads after the flags it consumes. The second reason is measured: the first line of
    # the wrapped usage is pinned in two places -- this repo's
    # `test_assets_root_appears_in_the_generated_help_in_the_documented_position` and the
    # `cli` conformance suite's reference precondition -- and at the 80-column fallback the
    # line breaks after `[--index-budget BYTES]`. Adding here leaves that line byte-identical;
    # adding before it would move it and turn a differential suite into a re-baselining one.
    parser.add_argument(
        "--mcp-report",
        action="store_true",
        help="print an analysis of the host MCP log joined with bantamkit's event log, then exit",
    )
    stores = parser.add_mutually_exclusive_group()
    stores.add_argument("--store", help="single memory store path (disables layering)")
    stores.add_argument(
        "--start", help="directory to start project-store discovery from (default: cwd)"
    )
    return parser.parse_args(argv)


def _build_memory(args: argparse.Namespace) -> Memory:
    if args.k < 1:
        raise SystemExit("--k must be >= 1")
    if args.index_budget < 1:
        raise SystemExit("--index-budget must be >= 1")
    if args.store is not None:
        if not args.store:
            raise SystemExit("--store requires a non-empty path")
        return Memory(store=args.store, k=args.k, index_budget=args.index_budget)
    return Memory.layered(start=args.start, k=args.k, index_budget=args.index_budget)


def _print_mcp_report(args: argparse.Namespace) -> None:
    """`--mcp-report`: the joined report on stdout, then return. No transport, no server.

    Same discipline as `_print_assets_root`: written through `sys.stdout.buffer`, because
    `sys.stdout` is a text stream with newline translation and on Windows `print` would
    emit CRLF where Node's `process.stdout.write` emits LF.

    NOTHING HERE IS WRITTEN. `mcpreport` opens the host's log read-only, creates no
    directory under its root, and `resolve_event_log_path` designates a store path without
    bringing a store into existence. The report is an observation, not a session.
    """
    text = build_mcp_report(
        dict(os.environ),
        resolve_event_log_path(dict(os.environ), store=args.store, start=args.start),
    )
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def _print_assets_root() -> None:
    """`--assets-root`: two lines on stdout, then return -- no store, no transport, no server.

    THE TWO RUNTIMES PRINT DIFFERENT PATHS ON PURPOSE. Do not "fix" that. Python resolves
    the repo-root `assets/` (or the copy packaged inside `bantamkit/`); Node resolves
    `runtime-ts/assets/`, which `scripts/sync-assets.mjs` vendors at prepack time. The two
    trees are byte-identical file for file, but they live at different paths by
    construction and always will, so line 1 is NOT comparable across runtimes. What IS
    comparable, and what the conformance case pins: exactly two lines, the shape
    `<root>\\n<count> files\\n`, the same COUNT on both sides, exit 0, stdout not stderr,
    empty stderr, and no transport started.

    Written through `sys.stdout.buffer` rather than `print`, because `sys.stdout` is a text
    stream with newline translation: on Windows `print` would emit CRLF where Node's
    `process.stdout.write` emits LF, and a byte-comparing conformance runner would call
    that a divergence. UTF-8 is what Node's `Buffer.from(string)` uses, so the encoding
    matches too.
    """
    root = assets_root()
    files = sum(1 for path in root.rglob("*") if path.is_file())
    sys.stdout.buffer.write(f"{root}\n{files} files\n".encode())
    sys.stdout.buffer.flush()


def main() -> None:
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    args = _parse_args()
    # Before `_build_memory`, which touches the filesystem, and before the server exists at
    # all -- the Node arm returns from `main` here too, ahead of `new RawStdioTransport()`.
    if args.assets_root:
        _print_assets_root()
        return
    if args.mcp_report:
        _print_mcp_report(args)
        return
    server = build_server(_build_memory(args))
    asyncio.run(server.run_stdio_async())


# `python -m bantamkit.mcpserver` is the invocation a host config reaches for when the
# console script is not on PATH. Without this guard the module imported fine, defined
# `main`, and exited 0 with nothing on either stream; the client saw CONNECTION_CLOSED,
# which names the symptom and not the cause. Measured 2026-08-21 before this line:
# `.venv/bin/python -m bantamkit.mcpserver` -> exit 0, stdout 0 bytes, stderr 0 bytes.
if __name__ == "__main__":
    main()
