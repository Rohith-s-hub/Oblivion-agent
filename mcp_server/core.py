"""
mcp_server/core.py — Unified MCP Server with 3-tier tools, resources, and prompts.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    Resource,
    Prompt,
    PromptArgument,
    PromptMessage,
)

from agent.paths import load_config_env, load_last_workspace
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

load_config_env()

# ── 3-Tier Security Partitioning ──────────────────────────────────────────
SAFE_TOOLS = {
    "read_file", "list_dir", "grep_files", "file_exists",
    "search_code", "find_symbol", "list_symbols", "find_callers",
    "project_map", "recall", "git_status", "git_diff", "git_log",
    "search_stock_images", "web_search", "fetch_page",
    "search_stackoverflow", "lookup_package", "list_servers", "verify_code"
}

WRITE_TOOLS = {
    "write_file", "edit_file", "insert_after", "create_dir",
    "batch_edit", "remember", "plan_task", "switch_workspace",
    "new_workspace", "open_preview", "finish"
}

DANGEROUS_TOOLS = {
    "run_bash", "run_tests", "test_file", "git_commit",
    "git_branch", "git_undo", "start_server", "stop_server"
}

def get_allowed_tools(tier: str) -> set[str]:
    """Resolve active tools by tier: safe, standard (safe+write), full (all)."""
    tier = (tier or "standard").lower()
    if tier == "safe":
        return set(SAFE_TOOLS)
    if tier == "full":
        return set(SAFE_TOOLS | WRITE_TOOLS | DANGEROUS_TOOLS)
    # Default: standard
    return set(SAFE_TOOLS | WRITE_TOOLS)


def oblivion_schema_to_mcp(schema: dict) -> Tool:
    """Convert Oblivion tool schema to an MCP Tool object."""
    properties = {}
    required = []
    for param_name, param_spec in schema.get("parameters", {}).items():
        json_type = {
            "string": "string",
            "integer": "integer",
            "boolean": "boolean",
            "array": "array",
            "object": "object",
        }.get(param_spec.get("type", "string"), "string")
        properties[param_name] = {
            "type": json_type,
            "description": param_spec.get("description", ""),
        }
        if param_spec.get("required"):
            required.append(param_name)

    return Tool(
        name=schema["name"],
        description=schema.get("description", ""),
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": required,
        },
    )


def create_mcp_app(tier: str = "standard", workspace: str | None = None) -> Server:
    """Factory creating a configured MCP server instance."""
    app = Server("oblivion")
    allowed = get_allowed_tools(tier)

    if workspace:
        os.environ["WORKSPACE_DIR"] = workspace
    elif not os.environ.get("WORKSPACE_DIR"):
        last_ws = load_last_workspace()
        if last_ws:
            os.environ["WORKSPACE_DIR"] = last_ws

    # ── Tools ─────────────────────────────────────────────────────────────
    @app.list_tools()
    async def list_tools() -> list[Tool]:
        out = []
        seen = set()
        for schema in TOOL_SCHEMAS:
            name = schema["name"]
            if name in allowed and name not in seen:
                out.append(oblivion_schema_to_mcp(schema))
                seen.add(name)
        return out

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name not in allowed:
            return [TextContent(
                type="text",
                text=f"Error: Tool '{name}' is disabled in tier '{tier}'.",
            )]

        if name not in TOOL_FUNCTIONS:
            return [TextContent(
                type="text",
                text=f"Error: Unknown tool '{name}'.",
            )]

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: TOOL_FUNCTIONS[name](**arguments),
            )
            return [TextContent(type="text", text=str(result))]
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error running {name}: {type(e).__name__}: {e}",
            )]

    # ── Resources ─────────────────────────────────────────────────────────
    @app.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(
                uri="workspace://tree",
                name="Workspace File Tree",
                description="Live folder and file hierarchy of the current Oblivion workspace.",
                mimeType="text/plain",
            ),
            Resource(
                uri="workspace://plan",
                name="Active Plan",
                description="Current task plan (.oblivion/plan.json) if available.",
                mimeType="application/json",
            ),
            Resource(
                uri="workspace://memory",
                name="Project Memory",
                description="Workspace persistent memory (MEMORY.md).",
                mimeType="text/markdown",
            ),
        ]

    @app.read_resource()
    async def read_resource(uri: str) -> str:
        ws = os.getenv("WORKSPACE_DIR", os.getcwd())
        ws_path = Path(ws)

        if uri == "workspace://tree":
            try:
                from tools.filesystem import project_map
                return project_map()
            except Exception as e:
                return f"Error reading tree: {e}"

        if uri == "workspace://plan":
            plan_file = ws_path / ".oblivion" / "plan.json"
            if plan_file.exists():
                return plan_file.read_text(encoding="utf-8")
            return '{"status": "no active plan"}'

        if uri == "workspace://memory":
            mem_file = ws_path / "MEMORY.md"
            if mem_file.exists():
                return mem_file.read_text(encoding="utf-8")
            return "# No memory saved yet."

        raise ValueError(f"Unknown resource URI: {uri}")

    # ── Prompts ───────────────────────────────────────────────────────────
    @app.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name="plan_feature",
                description="Plan a new feature or project from scratch before writing code.",
                arguments=[
                    PromptArgument(
                        name="goal",
                        description="Description of what you want to build.",
                        required=True,
                    )
                ],
            ),
            Prompt(
                name="review_code",
                description="Review current workspace for syntax, bugs, and best practices.",
                arguments=[],
            ),
        ]

    @app.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> list[PromptMessage]:
        args = arguments or {}
        if name == "plan_feature":
            goal = args.get("goal", "New feature")
            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            f"You are Oblivion M.E.E.R.A. coding assistant.\n"
                            f"Create an architectural step-by-step plan for: {goal}.\n"
                            f"Use `plan_task` tool to lock the plan before modifying files."
                        ),
                    ),
                )
            ]
        if name == "review_code":
            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text="Inspect the current workspace files, run syntax/tests checks, and suggest improvements.",
                    ),
                )
            ]
        raise ValueError(f"Unknown prompt name: {name}")

    return app
