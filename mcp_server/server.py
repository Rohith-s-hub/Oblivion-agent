"""
mcp_server/server.py — Main CLI Entry point for Oblivion MCP Server.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from mcp_server.auth import get_or_create_token
from mcp_server.transports.stdio import run_stdio
from mcp_server.transports.sse import run_sse


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="oblivion mcp",
        description="Oblivion Model Context Protocol (MCP) server.",
    )
    parser.add_argument(
        "--mode",
        choices=["stdio", "sse"],
        default=None,
        help="Transport mode (default: stdio, auto-switches to sse if --port/--sse is specified)",
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Shorthand for --mode sse",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind host for SSE mode (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8767,
        help="Port for SSE mode (default: 8767)",
    )
    parser.add_argument(
        "--tier",
        choices=["safe", "standard", "full"],
        default="standard",
        help="Tool permission tier: safe (read-only), standard (read+write), full (bash+git+tests)",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Target workspace folder (default: last used workspace or cwd)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Bearer token for authentication (generated if omitted in SSE mode)",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable bearer token authentication in SSE mode",
    )
    return parser.parse_args(args)


def main(custom_args: list[str] | None = None) -> None:
    if custom_args is None:
        custom_args = sys.argv[1:]

    # If first arg is 'mcp', strip it
    if custom_args and custom_args[0] == "mcp":
        custom_args = custom_args[1:]

    args = parse_args(custom_args)

    # Resolve mode
    mode = args.mode
    if args.sse:
        mode = "sse"
    elif mode is None:
        mode = "stdio"

    try:
        if mode == "sse":
            token = None
            if not args.no_auth:
                token = get_or_create_token(args.token)
            run_sse(
                host=args.host,
                port=args.port,
                tier=args.tier,
                workspace=args.workspace,
                token=token,
            )
        else:
            asyncio.run(run_stdio(tier=args.tier, workspace=args.workspace))
    except KeyboardInterrupt:
        print("\n[oblivion-mcp] shutdown cleanly", file=sys.stderr)


if __name__ == "__main__":
    main()
