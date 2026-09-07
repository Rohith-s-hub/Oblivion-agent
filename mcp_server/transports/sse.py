"""
mcp_server/transports/sse.py — Dual SSE + REST Server for Claude MCP and ChatGPT Actions.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

from mcp.server.sse import SseServerTransport
from mcp_server.core import create_mcp_app, get_allowed_tools
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS


def create_sse_app(tier: str = "standard", workspace: str | None = None, token: str | None = None) -> Starlette:
    mcp_app = create_mcp_app(tier=tier, workspace=workspace)
    sse_transport = SseServerTransport("/messages/")
    allowed_tools = get_allowed_tools(tier)

    def check_auth(request: Request) -> bool:
        if not token:
            return True
        # 1. Check Authorization Bearer header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            if auth_header[7:].strip() == token:
                return True
        # 2. Check X-API-Key / X-Token header
        if request.headers.get("x-api-key") == token or request.headers.get("x-token") == token:
            return True
        # 3. Check query param
        if request.query_params.get("token") == token or request.query_params.get("api_key") == token:
            return True
        return False

    # ── MCP SSE Endpoints (for Claude.ai, Cursor, Windsurf) ────────────────
    async def handle_sse(request: Request) -> Response:
        if not check_auth(request):
            return JSONResponse({"error": "Unauthorized: invalid or missing Bearer token"}, status_code=401)

        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_app.run(
                streams[0],
                streams[1],
                mcp_app.create_initialization_options(),
            )
        return Response(status_code=200)

    async def handle_messages(request: Request) -> Response:
        if not check_auth(request):
            return JSONResponse({"error": "Unauthorized: invalid or missing Bearer token"}, status_code=401)
        return await sse_transport.handle_post_message(request.scope, request.receive, request._send)

    # ── REST API Endpoints (for ChatGPT Actions, Canva, Zapier) ───────────
    async def handle_health(request: Request) -> Response:
        ws = os.getenv("WORKSPACE_DIR", os.getcwd())
        return JSONResponse({
            "status": "ok",
            "server": "oblivion-agent",
            "tier": tier,
            "workspace": ws,
            "tools_count": len(allowed_tools),
            "auth_required": bool(token),
        })

    async def handle_list_tools(request: Request) -> Response:
        if not check_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        tools = [s for s in TOOL_SCHEMAS if s["name"] in allowed_tools]
        return JSONResponse({"tools": tools})

    async def handle_call_tool(request: Request) -> Response:
        if not check_auth(request):
            return JSONResponse({"error": "Unauthorized: invalid Bearer token"}, status_code=401)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        tool_name = body.get("name") or body.get("tool")
        arguments = body.get("arguments") or body.get("args") or {}

        if not tool_name or tool_name not in allowed_tools:
            return JSONResponse({"error": f"Tool '{tool_name}' not available in tier '{tier}'"}, status_code=400)

        if tool_name not in TOOL_FUNCTIONS:
            return JSONResponse({"error": f"Tool '{tool_name}' not implemented"}, status_code=404)

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: TOOL_FUNCTIONS[tool_name](**arguments),
            )
            return JSONResponse({"success": True, "tool": tool_name, "result": str(result)})
        except Exception as e:
            return JSONResponse({"success": False, "tool": tool_name, "error": f"{type(e).__name__}: {e}"}, status_code=500)

    # ── Auto-Generated Strict OpenAPI 3.0 Schema for ChatGPT Actions ───────
    async def handle_openapi_schema(request: Request) -> Response:
        host = request.headers.get("host", "localhost:8767")
        scheme = "https" if ("pinggy" in host or "trycloudflare" in host or "ngrok" in host) else "http"
        base_url = f"{scheme}://{host}"

        schema = {
            "openapi": "3.0.1",
            "info": {
                "title": "Oblivion Agent Tools",
                "description": "Bridge to local Oblivion agent running on user machine",
                "version": "3.4.0",
            },
            "servers": [{"url": base_url}],
            "paths": {
                "/health": {
                    "get": {
                        "summary": "Check server health",
                        "operationId": "getHealth",
                        "responses": {
                            "200": {
                                "description": "Server status",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "status": {"type": "string"},
                                                "server": {"type": "string"},
                                                "tier": {"type": "string"},
                                                "workspace": {"type": "string"},
                                                "tools_count": {"type": "integer"},
                                                "auth_required": {"type": "boolean"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "/api/tools/call": {
                    "post": {
                        "summary": "Execute an Oblivion tool",
                        "operationId": "callOblivionTool",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["name"],
                                        "properties": {
                                            "name": {
                                                "type": "string",
                                                "description": "Tool name (e.g. project_map, read_file, search_code, write_file, edit_file)"
                                            },
                                            "arguments": {
                                                "type": "object",
                                                "description": "Tool arguments dictionary"
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "Execution result",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "success": {"type": "boolean"},
                                                "tool": {"type": "string"},
                                                "result": {"type": "string"},
                                                "error": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return JSONResponse(schema)

    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/messages/", endpoint=handle_messages, methods=["POST"]),
        Route("/health", endpoint=handle_health, methods=["GET"]),
        Route("/api/tools", endpoint=handle_list_tools, methods=["GET"]),
        Route("/api/tools/call", endpoint=handle_call_tool, methods=["POST"]),
        Route("/openapi.json", endpoint=handle_openapi_schema, methods=["GET"]),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    return Starlette(debug=False, routes=routes, middleware=middleware)


def run_sse(
    host: str = "127.0.0.1",
    port: int = 8767,
    tier: str = "standard",
    workspace: str | None = None,
    token: str | None = None,
) -> None:
    starlette_app = create_sse_app(tier=tier, workspace=workspace, token=token)
    ws = workspace or os.getenv("WORKSPACE_DIR", os.getcwd())

    print(f"⚡ [oblivion-mcp] Mode: SSE + REST Dual Network Server", file=sys.stderr)
    print(f"📂 [oblivion-mcp] Workspace: {ws}", file=sys.stderr)
    print(f"🛡️ [oblivion-mcp] Tool Tier: {tier.upper()}", file=sys.stderr)
    print(f"🌐 [oblivion-mcp] Listening on: http://{host}:{port}/sse", file=sys.stderr)
    if token:
        print(f"🔑 [oblivion-mcp] Auth Token: {token}", file=sys.stderr)
    uvicorn.run(starlette_app, host=host, port=port, log_level="warning")
