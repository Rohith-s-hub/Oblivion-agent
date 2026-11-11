"""
mcp_server/auth.py — Token authentication helper for Oblivion network MCP.
"""
from __future__ import annotations
import os
import secrets
import sys
from pathlib import Path

_TOKEN_FILE = Path.home() / ".ai-agent" / "rest_token"

def get_or_create_token(custom_token: str | None = None) -> str:
    """Return explicit token, or OBLIVION_MCP_TOKEN from env, or a token
    persisted on disk, or generate+persist a new one."""
    if custom_token:
        return custom_token
    env_token = os.getenv("OBLIVION_MCP_TOKEN")
    if env_token:
        return env_token
    try:
        if _TOKEN_FILE.exists():
            existing = _TOKEN_FILE.read_text().strip()
            if existing:
                return existing
    except Exception:
        pass
    token = secrets.token_hex(16)
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(token)
        _TOKEN_FILE.chmod(0o600)
    except Exception:
        pass
    return token
