"""
mcp_server/transports/stdio.py — Stdio runner for Claude Desktop & local pipes.
"""
from __future__ import annotations
import os
import sys
from mcp.server.stdio import stdio_server
from mcp_server.core import create_mcp_app

async def run_stdio(tier: str = "standard", workspace: str | None = None) -> None:
    app = create_mcp_app(tier=tier, workspace=workspace)
    active_ws = os.getenv("WORKSPACE_DIR", os.getcwd())

    print(f"[oblivion-mcp] mode: stdio | tier: {tier} | workspace: {active_ws}", file=sys.stderr)
    print(f"[oblivion-mcp] ready - listening on stdio", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )
