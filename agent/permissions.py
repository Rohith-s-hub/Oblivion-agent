"""
agent/permissions.py - Tier-based permission system for tool execution.

Three tiers:
  read        - auto-execute, no approval prompt
  mutate      - approval required (bypassable via /trust or /auto)
  destructive - approval + hardcoded critical path check (NEVER bypassable)

The destructive tier is dynamic: run_bash commands are inspected against
CRITICAL_PATTERNS and CRITICAL_PATHS. If ANY match, the command becomes
destructive and requires approval even under /auto mode.
"""
from __future__ import annotations
from typing import Optional


# ================== TIER ASSIGNMENTS ==================

TOOL_TIERS = {
    # READ TIER - auto-execute, silent
    "read_file": "read",
    "list_dir": "read",
    "grep_files": "read",
    "file_exists": "read",
    "search_code": "read",
    "find_symbol": "read",
    "list_symbols": "read",
    "find_callers": "read",
    "project_map": "read",
    "recall": "read",
    "verify_code": "read",
    "list_servers": "read",
    "plan_task": "read",
    # Git read tools
    "git_status": "read",
    "git_diff":   "read",
    "git_log":    "read",
    "git_branch": "read",
    # Test runner - read tier (runs tests, never modifies files)
    "run_tests":  "read",
    "test_file":  "read",

    # MUTATE TIER - approval required, bypassable via /trust or /auto
    "write_file": "mutate",
    "edit_file": "mutate",
    "insert_after": "mutate",
    "create_dir": "mutate",
    "new_workspace": "mutate",
    "remember": "mutate",
    "start_server": "mutate",
    "stop_server": "mutate",
    # Git mutate tools
    "git_commit": "mutate",
    "git_undo":   "mutate",
    # Batch edit - mutate tier (single approval for multiple files)
    "batch_edit":  "mutate",
    "batch_apply": "mutate",

    # DESTRUCTIVE TIER (1 tool - dynamic classification)
    "run_bash": "destructive",  # subclassified by command content
}


# Tools that expose network endpoints - must disclose bind address in prompt
NETWORK_EXPOSING = {"start_server"}


# ================== HARDCODED SAFETY RULES ==================
# These ALWAYS require explicit approval, even under /auto mode.

CRITICAL_PATTERNS = [
    "rm -rf", "rm -fr", "rm  -rf",
    "mkfs", "dd if=",
    "> /dev/sd", "> /dev/nvme",
    ":(){ :|:& };:",  # fork bomb
    "chmod -R 777",
    "chown -R",
    "git push --force", "git push -f",
    "git reset --hard origin",
    "drop database", "drop table", "truncate table",
    "> /etc/", "> /boot/", "> /root/",
    "sudo rm", "sudo dd",
]

CRITICAL_PATHS = [
    "/etc", "/boot", "/sys", "/proc",
    "/root", "/usr/bin", "/usr/sbin",
    ".ssh", ".git/objects", ".git/refs",
]


def classify_tool(tool_name: str, args: dict) -> str:
    """Return 'read', 'mutate', or 'destructive' for a tool call.

    For run_bash, dynamically inspects the command against CRITICAL_PATTERNS
    and CRITICAL_PATHS to determine if it should be destructive.
    """
    tier = TOOL_TIERS.get(tool_name, "mutate")  # unknown -> safe default

    if tier == "destructive":
        return _classify_bash(args.get("command", ""))
    return tier


def _classify_bash(command: str) -> str:
    """Subclassify a bash command as destructive or mutate."""
    if not command:
        return "mutate"
    cmd_lower = command.lower().strip()

    for pattern in CRITICAL_PATTERNS:
        if pattern in cmd_lower:
            return "destructive"

    for path in CRITICAL_PATHS:
        # Check if path appears as an argument (with space before or at start)
        if " " + path in command or command.startswith(path):
            return "destructive"

    # Single naked "/" is dangerous (rm /, ls /, > /) - context matters
    if " / " in command or command.endswith(" /"):
        return "destructive"

    return "mutate"


def needs_approval(tool_name: str, args: dict, session_state: dict) -> tuple[bool, str]:
    """Return (needs_approval, reason).

    reason is one of: 'read', 'trusted', 'auto', 'mutate', 'destructive'
    Used for logging/debugging. User just sees prompt or no prompt.
    """
    tier = classify_tool(tool_name, args)

    if tier == "read":
        return False, "read"

    if tier == "destructive":
        # ALWAYS prompts. /auto cannot bypass. /trust cannot bypass.
        return True, "destructive"

    # tier == "mutate"
    trusted_tools = session_state.get("trusted_tools", set())
    if tool_name in trusted_tools:
        return False, "trusted"

    if session_state.get("auto_mode"):
        return False, "auto"

    return True, "mutate"


def network_disclosure(tool_name: str, args: dict) -> Optional[str]:
    """For network-exposing tools, return the bind address disclosure.

    Shown in approval prompt to reveal network exposure risk.
    Returns None if not a network-exposing tool.
    """
    if tool_name not in NETWORK_EXPOSING:
        return None

    command = args.get("command", "")
    port = args.get("port", 0)

    if "0.0.0.0" in command:
        return f"NETWORK: Will bind to 0.0.0.0:{port or '?'} - accessible from any network on this machine"
    if "--host" in command:
        parts = command.split("--host")
        if len(parts) > 1:
            host = parts[1].split()[0].strip()
            if host and host != "127.0.0.1" and host != "localhost":
                return f"NETWORK: Will bind to {host}:{port or '?'} - review exposure"

    return f"NETWORK: Will bind to localhost:{port or '?'} - local only"


# ================== TRUST GROUPS ==================
# Named groups for /trust <group> command

TRUST_GROUPS = {
    "edit": {"write_file", "edit_file", "insert_after"},
    "all-mutate": {t for t, tier in TOOL_TIERS.items() if tier == "mutate"},
    "workspace": {"create_dir", "new_workspace"},
    "server": {"start_server", "stop_server"},
}


def expand_trust_group(group: str) -> set:
    """Return the set of tool names for a named trust group."""
    return TRUST_GROUPS.get(group, set())
