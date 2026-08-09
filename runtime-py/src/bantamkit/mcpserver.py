"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
from importlib import metadata
from typing import Any

from bantamkit.assets import assets_root, load_skill, load_tool
from bantamkit.evalrun import schema_error
from bantamkit.memory import Memory

try:
    from mcp.server import MCPServer
except ImportError:  # surfaced as a clear SystemExit in main()
    MCPServer = None  # type: ignore[assignment]

_INSTALL_HINT = 'bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"'

VALIDATE_DESCRIPTION = (
    "Validate candidate output text against a JSON Schema. Returns {valid, feedback}; "
    "when invalid, feed the feedback back to the model and retry."
)


def _version() -> str:
    try:
        return metadata.version("bantamkit")
    except metadata.PackageNotFoundError:
        return "0.0.0"


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
            "feedback": f"{error}\nReturn ONLY a JSON object matching the schema.",
        }

    # Advertise the asset pack's schemas verbatim: one source of truth for every
    # transport. Call-time argument validation still follows the handler signatures
    # above, which mirror the same schemas. _tool_manager is SDK-internal; the
    # schema-equality test fails loudly if an SDK upgrade moves it.
    for tool_name, asset in (("memory_save", save_asset), ("memory_recall", recall_asset)):
        server._tool_manager.get_tool(tool_name).parameters = asset.parameters

    @server.resource("bantamkit://skills/{name}")
    def skill_resource(name: str) -> str:
        return load_skill(name)

    @server.resource("bantamkit://rubrics/{name}")
    def rubric_resource(name: str) -> str:
        path = assets_root() / "rubrics" / f"{name}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"unknown rubric asset: {name}")
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
