"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

import bantamkit
from bantamkit import __version__, shiftwork
from bantamkit.assets import AssetNotFound, assets_root, load_skill, load_tool
from bantamkit.contract import schema_error, schema_retry_feedback
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
    """Bind one handler to its manifest entry — name, description AND input schema.

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
    """
    asset = load_tool(name)
    tool = SDKTool.from_function(fn, name=asset.name, description=asset.description)
    return tool.model_copy(update={"parameters": asset.parameters})


def build_server(memory: Memory) -> Any:
    """Assemble the MCP server around one Memory instance (the per-person state)."""
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)

    def memory_save(
        type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> str:
        return memory.save(type, name, description, body, links)

    def memory_recall(query: str, k: int | None = None) -> str:
        if k is not None:
            k = max(1, min(k, 5))  # the advertised schema's bounds; clients may ignore it
        return memory.recall(query, k)

    def validate_json(output: str, schema: dict[str, Any]) -> dict[str, Any]:
        error = schema_error(output, schema)
        if error is None:
            return {"valid": True, "feedback": None}
        return {
            "valid": False,
            "feedback": schema_retry_feedback(error),
        }

    def shiftwork_clock_in(checkpoint: str) -> dict[str, Any]:
        return shiftwork.clock_in(checkpoint)

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

    def shiftwork_status(checkpoint: str) -> dict[str, Any]:
        return shiftwork.status(checkpoint)

    # A TOOL and not a resource or an `initialize` field, because the gap RB-P84 names is
    # an AGENT MID-CALL: the host reads `serverInfo` once at handshake and the
    # tool-calling model never sees it, and `resources/read` is a host-facing surface
    # most clients never expose to the model at all. A tool is in `tools/list`, so the
    # model that just received a `memory_recall` answer can ask who answered it.
    def build_identity_tool() -> dict[str, Any]:
        return build_identity()

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


def main() -> None:
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    args = _parse_args()
    server = build_server(_build_memory(args))
    asyncio.run(server.run_stdio_async())


# `python -m bantamkit.mcpserver` is the invocation a host config reaches for when the
# console script is not on PATH. Without this guard the module imported fine, defined
# `main`, and exited 0 with nothing on either stream; the client saw CONNECTION_CLOSED,
# which names the symptom and not the cause. Measured 2026-08-21 before this line:
# `.venv/bin/python -m bantamkit.mcpserver` -> exit 0, stdout 0 bytes, stderr 0 bytes.
if __name__ == "__main__":
    main()
