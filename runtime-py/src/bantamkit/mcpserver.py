"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import bantamkit
from bantamkit import __version__, shiftwork
from bantamkit.assets import AssetNotFound, assets_root, load_skill, load_tool
from bantamkit.contract import schema_error, schema_retry_feedback
from bantamkit.memory import Memory

try:
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ResourceError
except ImportError:  # surfaced as a clear SystemExit in main()
    MCPServer = None  # type: ignore[assignment]
    ResourceError = None  # type: ignore[assignment]

_INSTALL_HINT = 'bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"'

VALIDATE_DESCRIPTION = (
    "Validate candidate output text against a JSON Schema. Returns {valid, feedback}; "
    "when invalid, feed the feedback back to the model and retry."
)

CLOCK_IN_DESCRIPTION = (
    "Shift-work clock-in: schema-validate the checkpoint file and return the brief for "
    "the unit at plan.cursor — {unit, role, invariants, handoff, do_not, files} — to hand "
    "to the spawned agent verbatim. Structured refusals, never exceptions: "
    "result=escalate when handoff.open_questions is non-empty, result=success when every "
    "unit is done or dropped, result=error when the checkpoint fails validation."
)

CLOCK_OUT_DESCRIPTION = (
    "Shift-work clock-out: record a finished unit — set its status, advance plan.cursor, "
    "merge handoff_patch, push history_entry onto the 5-entry ring — validating the whole "
    "mutated document against the checkpoint schema BEFORE an atomic write (a failure "
    "writes nothing and returns result=error). Every success appends one accounting line "
    "(unit, role, status, ts, plus your accounting fields, e.g. tokens/duration/model) to "
    "<checkpoint>.log.jsonl."
)

STATUS_DESCRIPTION = (
    "Shift-work status: read-only progress summary of a checkpoint — units by status, "
    "cursor, open-question count, last history entry. Never mutates."
)

BUILD_IDENTITY_DESCRIPTION = (
    "Which bantamkit build is answering you, readable mid-call. Returns `build_id` — a "
    "content fingerprint of the running source and the asset pack it loads — plus the "
    "paths it was computed over. Call it when one MCP server name may resolve to more "
    "than one install: two endpoints reporting the same `version` are the SAME build "
    "only if their `build_id` matches, because a version string moves on release bumps "
    "and not on builds. Any fact that cannot be derived comes back as "
    '{"unavailable": "<reason>"} and is named in the `unavailable` list — never omitted, '
    "never a placeholder that reads as a value. Takes no arguments and reads no state."
)

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
    `__pycache__` is excluded: bytecode is derived, and including it would make one build
    fingerprint differently before and after its first import.
    """
    located = getattr(bantamkit, "__file__", None)
    if not located:
        raise _Undetermined("bantamkit has no __file__; the running code is not on disk")
    root = Path(located).resolve().parent
    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
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


def build_server(memory: Memory) -> Any:
    """Assemble the MCP server around one Memory instance (the per-person state)."""
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    server = MCPServer(SERVER_NAME, instructions=load_skill("memory"), version=_version())

    save_asset = load_tool("memory_save")
    recall_asset = load_tool("memory_recall")

    @server.tool(name="memory_save", description=save_asset.description)
    def memory_save(
        type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> str:
        return memory.save(type, name, description, body, links)

    @server.tool(name="memory_recall", description=recall_asset.description)
    def memory_recall(query: str, k: int | None = None) -> str:
        if k is not None:
            k = max(1, min(k, 5))  # the advertised schema's bounds; clients may ignore it
        return memory.recall(query, k)

    @server.tool(name="validate_json", description=VALIDATE_DESCRIPTION)
    def validate_json(output: str, schema: dict[str, Any]) -> dict[str, Any]:
        error = schema_error(output, schema)
        if error is None:
            return {"valid": True, "feedback": None}
        return {
            "valid": False,
            "feedback": schema_retry_feedback(error),
        }

    @server.tool(name="shiftwork_clock_in", description=CLOCK_IN_DESCRIPTION)
    def shiftwork_clock_in(checkpoint: str) -> dict[str, Any]:
        return shiftwork.clock_in(checkpoint)

    @server.tool(name="shiftwork_clock_out", description=CLOCK_OUT_DESCRIPTION)
    def shiftwork_clock_out(
        checkpoint: str,
        unit_id: str,
        status: str,
        handoff_patch: dict[str, Any],
        history_entry: dict[str, Any],
        accounting: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return shiftwork.clock_out(
            checkpoint, unit_id, status, handoff_patch, history_entry, accounting
        )

    @server.tool(name="shiftwork_status", description=STATUS_DESCRIPTION)
    def shiftwork_status(checkpoint: str) -> dict[str, Any]:
        return shiftwork.status(checkpoint)

    # A TOOL and not a resource or an `initialize` field, because the gap RB-P84 names is
    # an AGENT MID-CALL: the host reads `serverInfo` once at handshake and the
    # tool-calling model never sees it, and `resources/read` is a host-facing surface
    # most clients never expose to the model at all. A tool is in `tools/list`, so the
    # model that just received a `memory_recall` answer can ask who answered it.
    @server.tool(name="build_identity", description=BUILD_IDENTITY_DESCRIPTION)
    def build_identity_tool() -> dict[str, Any]:
        return build_identity()

    # Advertise the asset pack's schemas verbatim: one source of truth for every
    # transport. Call-time argument validation still follows the handler signatures
    # above, which mirror the same schemas. _tool_manager is SDK-internal; the
    # schema-equality test fails loudly if an SDK upgrade moves it.
    for tool_name, asset in (("memory_save", save_asset), ("memory_recall", recall_asset)):
        server._tool_manager.get_tool(tool_name).parameters = asset.parameters

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
        return path.read_text()

    return server


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bantamkit-mcp",
        description="bantamkit MCP server (stdio): per-person memory + JSON validation.",
    )
    parser.add_argument("--k", type=int, default=3, help="default recall budget (default: 3)")
    stores = parser.add_mutually_exclusive_group()
    stores.add_argument("--store", help="single memory store path (disables layering)")
    stores.add_argument(
        "--start", help="directory to start project-store discovery from (default: cwd)"
    )
    return parser.parse_args(argv)


def _build_memory(args: argparse.Namespace) -> Memory:
    if args.k < 1:
        raise SystemExit("--k must be >= 1")
    if args.store is not None:
        if not args.store:
            raise SystemExit("--store requires a non-empty path")
        return Memory(store=args.store, k=args.k)
    return Memory.layered(start=args.start, k=args.k)


def main() -> None:
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    args = _parse_args()
    server = build_server(_build_memory(args))
    asyncio.run(server.run_stdio_async())
