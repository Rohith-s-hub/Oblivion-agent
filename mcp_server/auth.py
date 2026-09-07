"""
mcp_server/auth.py — Token authentication helper for Oblivion network MCP.
"""
from __future__ import annotations
import os
import secrets
import sys

def get_or_create_token(custom_token: str | None = None) -> str:
    """Return explicit token, or OBLIVION_MCP_TOKEN from env, or generate a random one."""
    if custom_token:
        return custom_token
    env_token = os.getenv("OBLIVION_MCP_TOKEN")
    if env_token:
        return env_token
    token = secrets.token_hex(16)
    return token
