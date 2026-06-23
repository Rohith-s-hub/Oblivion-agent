"""
mcp_server/server.py — Expose Oblivion's tools via Model Context Protocol.

Lets external clients (Claude Desktop, Cursor, Zed, etc.) use Oblivion's
code understanding without launching the TUI. Runs over stdio.

Exposed tools (READ-ONLY for safety in v1):
  - read_file           — read any file in workspace
  - list_dir            — list directory contents
  - grep_files          — exact-text search
  - file_exists         — check existence
  - search_code         — hybrid semantic + symbol search
  - find_symbol         — exact function/class lookup
  - list_symbols        — outline a file
  - find_callers        — references to a symbol
  - project_map         — workspace tree
  - recall              — read workspace memory

Workspace is set via WORKSPACE_DIR env var, passed by the client.

Usage:
  Direct test:        oblivion mcp
  Claude Desktop:     see https://modelcontextprotocol.io/quickstart/user
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

# Load Oblivion config so paths + workspace work the same as in TUI
from agent.paths import load_config_env
load_config_env()

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS


# ── Safety: only expose read-only tools in v1 ────────────────────────────────
SAFE_TOOLS = {
    "read_file",
    "list_dir",
    "grep_files",
    "file_exists",
    "search_code",
    "find_symbol",
    "list_symbols",
    "find_callers",
    "project_map",
    "recall",
}


def _oblivion_schema_to_mcp(schema: dict) -> Tool:
    """Convert one entry from Oblivion's TOOL_SCHEMAS to an MCP Tool object."""
    properties = {}
    required = []
    for param_name, param_spec in schema.get("parameters", {}).items():
        json_type = {
            "string": "string",
            "integer": "integer",
            "boolean": "boolean",
        }.get(param_spec.get("type", "string"), "string")
        properties[param_name] = {
            "type": json_type,
            "description": param_spec.get("description", ""),
        }
        if param_spec.get("required"):
            required.append(param_name)

    return Tool(
        name=schema["name"],
        description=schema["description"],
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": required,
        },
    )


# ── Build the server ─────────────────────────────────────────────────────────
app = Server("oblivion")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Tell MCP clients which Oblivion tools are available."""
    out = []
    for schema in TOOL_SCHEMAS:
        if schema["name"] in SAFE_TOOLS:
            out.append(_oblivion_schema_to_mcp(schema))
    return out


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a tool call from the MCP client."""
    if name not in SAFE_TOOLS:
        return [TextContent(
            type="text",
            text=f"Error: tool '{name}' is not exposed via MCP (read-only mode).",
        )]

    if name not in TOOL_FUNCTIONS:
        return [TextContent(
            type="text",
            text=f"Error: unknown tool '{name}'.",
        )]

    try:
        # Run sync tool in thread pool so we don't block the event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: TOOL_FUNCTIONS[name](**arguments),
        )
        return [TextContent(type="text", text=str(result))]
    except TypeError as e:
        return [TextContent(
            type="text",
            text=f"Error: bad arguments to {name}: {e}",
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=f"Error running {name}: {type(e).__name__}: {e}",
        )]


# ── Entry point ──────────────────────────────────────────────────────────────
async def _run() -> None:
    """Async runner — wires stdin/stdout to the MCP server."""
    workspace = os.getenv("WORKSPACE_DIR", os.getcwd())
    print(f"[oblivion-mcp] workspace = {workspace}", file=sys.stderr)
    print(f"[oblivion-mcp] exposed tools = {len(SAFE_TOOLS)} (read-only)", file=sys.stderr)
    print(f"[oblivion-mcp] ready - listening on stdio", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main() -> None:
    """Sync entry point called by the `oblivion mcp` subcommand."""
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n[oblivion-mcp] shutdown", file=sys.stderr)


if __name__ == "__main__":
    main()
