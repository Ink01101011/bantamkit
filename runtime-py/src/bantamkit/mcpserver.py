"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

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


def _version() -> str:
    """The version this checkout declares — never the one the last install recorded.

    RB-P45: `metadata.version("bantamkit")` reads the installed dist-info, and a *stale*
    editable install is not a `PackageNotFoundError`, so the old body could not fall back
    — it returned a confidently wrong number. `__version__` is the same bytes hatchling
    builds the wheel from, is already imported by the time this module exists, and has no
    failure mode to fall back from.
    """
    return __version__


def build_server(memory: Memory) -> Any:
    """Assemble the MCP server around one Memory instance (the per-person state)."""
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    server = MCPServer("bantamkit", instructions=load_skill("memory"), version=_version())

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
