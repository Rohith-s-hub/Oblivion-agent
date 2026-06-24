import subprocess
import os
from dotenv import load_dotenv


# ── DANGER PATTERNS: ALWAYS require approval regardless of env setting ──────
DANGER_PATTERNS = [
    "rm -rf",
    "rm -fr",
    "rm  -rf",      # extra space variants
    ":(){ :|:& };:",  # fork bomb
    "mkfs",
    "dd if=",
    "> /dev/sda",
    "format c:",
    "del /f /s /q",
    "git push --force",
    "git reset --hard origin",
    "drop database",
    "drop table",
    "truncate table",
]


def is_dangerous_command(cmd: str) -> bool:
    """Returns True if this command needs forced approval no matter what."""
    cmd_lower = cmd.lower().strip()
    for pattern in DANGER_PATTERNS:
        if pattern in cmd_lower:
            return True
    return False

BLOCKED = {"rm -rf /", "rm -rf ~", ":(){ :|:& };:", "mkfs", "dd if=/dev/zero", "sudo rm -rf"}


def run_bash(command: str, timeout: int = 30) -> str:
    if any(b in command.lower() for b in BLOCKED):
        return f"Blocked command: {command}"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=os.getenv("WORKSPACE_DIR", ".")
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"[stderr]\n{result.stderr.strip()}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# start_server — spawn a long-running process in the background WITHOUT blocking
# ─────────────────────────────────────────────────────────────────────────────
import time as _time
import socket as _socket

_RUNNING_SERVERS = []


def start_server(command: str, port: int = 0, wait_seconds: int = 3) -> str:
    """Start a long-running server process in the background.

    Args:
      command: shell command (e.g. 'npm start', 'flask run')
      port: optional port to poll for readiness (0 = skip check)
      wait_seconds: seconds to wait before checking (default 3)
    """
    if any(b in command.lower() for b in BLOCKED):
        return "Blocked command: " + command

    workspace = os.getenv("WORKSPACE_DIR", ".")
    log_path = "/tmp/oblivion-server-{0}.log".format(int(_time.time()))

    try:
        log_file = open(log_path, "w")
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=workspace,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        _RUNNING_SERVERS.append({"pid": proc.pid, "command": command, "log": log_path})
    except Exception as e:
        return "Error starting server: {0}".format(e)

    _time.sleep(wait_seconds)

    poll = proc.poll()
    if poll is not None:
        try:
            with open(log_path) as f:
                log_tail = f.read()[-500:]
        except Exception:
            log_tail = "(could not read log)"
        lines = [
            "Server CRASHED after starting (exit code {0}).".format(poll),
            "Command: " + command,
            "Log tail:",
            log_tail,
            "Common fixes: run 'npm install' first, check the port isn't in use, check syntax.",
        ]
        return "\n".join(lines)

    port_status = ""
    if port > 0:
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            s.close()
            if result == 0:
                port_status = "\nPort {0} is OPEN — server is accepting connections.".format(port)
            else:
                port_status = "\nPort {0} not yet open (server may still be starting).".format(port)
        except Exception as e:
            port_status = "\n(port check failed: {0})".format(e)

    out = [
        "Server started in background.",
        "PID: {0}".format(proc.pid),
        "Command: " + command,
        "Working dir: " + workspace,
        "Log file: " + log_path,
        "Tail logs with: tail -f " + log_path,
        "Stop with: kill {0}".format(proc.pid),
    ]
    return "\n".join(out) + port_status


def list_servers() -> str:
    """List currently tracked background servers."""
    if not _RUNNING_SERVERS:
        return "No background servers tracked in this session."
    lines = ["Running background servers:"]
    for s in _RUNNING_SERVERS:
        try:
            os.kill(s["pid"], 0)
            status = "ALIVE"
        except ProcessLookupError:
            status = "DEAD"
        except PermissionError:
            status = "ALIVE (other owner)"
        lines.append("  PID {0} [{1}]  {2}  log={3}".format(s["pid"], status, s["command"], s["log"]))
    return "\n".join(lines)


def stop_server(pid: int) -> str:
    """Stop a background server by PID."""
    global _RUNNING_SERVERS
    try:
        os.kill(pid, 15)
        _RUNNING_SERVERS = [s for s in _RUNNING_SERVERS if s["pid"] != pid]
        return "Sent SIGTERM to PID {0}.".format(pid)
    except ProcessLookupError:
        return "PID {0} not found (may have already exited).".format(pid)
    except Exception as e:
        return "Error stopping PID {0}: {1}".format(pid, e)
