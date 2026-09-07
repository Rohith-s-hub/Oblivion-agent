"""
mcp_server/manager.py — Async & Non-blocking Manager for Oblivion MCP & Web Connectors.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mcp_server.auth import get_or_create_token
from mcp_server.core import get_allowed_tools

_STATE = {
    "server_process": None,
    "tunnel_process": None,
    "port": 8767,
    "tier": "standard",
    "token": None,
    "tunnel_url": None,
    "is_running": False,
}
_LOCK = threading.Lock()


def get_mcp_status() -> dict[str, Any]:
    with _LOCK:
        srv_proc = _STATE["server_process"]
        is_alive = srv_proc is not None and srv_proc.poll() is None

        tun_proc = _STATE["tunnel_process"]
        tun_alive = tun_proc is not None and tun_proc.poll() is None

        if not is_alive and _STATE["is_running"]:
            _STATE["is_running"] = False

        if not tun_alive:
            _STATE["tunnel_url"] = None

        allowed = get_allowed_tools(_STATE["tier"])

        return {
            "running": is_alive,
            "port": _STATE["port"],
            "tier": _STATE["tier"],
            "token": _STATE["token"],
            "tools_count": len(allowed),
            "tunnel_active": tun_alive and _STATE["tunnel_url"] is not None,
            "tunnel_url": _STATE["tunnel_url"],
            "local_sse_url": f"http://127.0.0.1:{_STATE['port']}/sse" if is_alive else None,
            "web_connector_url": (
                f"{_STATE['tunnel_url']}/sse?token={_STATE['token']}"
                if (tun_alive and _STATE["tunnel_url"])
                else None
            ),
        }


def start_server(port: int = 8767, tier: str = "standard", token: str | None = None) -> dict[str, Any]:
    with _LOCK:
        if _STATE["server_process"] and _STATE["server_process"].poll() is None:
            return get_mcp_status()

        try:
            subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
            time.sleep(0.3)
        except Exception:
            pass

        tok = get_or_create_token(token)
        _STATE["port"] = port
        _STATE["tier"] = tier
        _STATE["token"] = tok

        py_bin = sys.executable
        agent_dir = str(Path(__file__).resolve().parent.parent)

        cmd = [
            py_bin,
            "-m",
            "mcp_server.server",
            "--sse",
            "--port",
            str(port),
            "--tier",
            tier,
            "--token",
            tok,
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=agent_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _STATE["server_process"] = proc
        _STATE["is_running"] = True
        time.sleep(0.5)

    return get_mcp_status()


def start_tunnel(port: int = 8767, timeout: float = 6.0) -> str | None:
    with _LOCK:
        if _STATE["tunnel_process"] and _STATE["tunnel_process"].poll() is None:
            if _STATE["tunnel_url"]:
                return _STATE["tunnel_url"]

        cmd = [
            "ssh",
            "-p",
            "443",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            f"-R0:localhost:{port}",
            "a.pinggy.io",
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        _STATE["tunnel_process"] = proc

    # Make stdout non-blocking
    try:
        os.set_blocking(proc.stdout.fileno(), False)
    except Exception:
        pass

    found_url = None
    buf = ""
    deadline = time.time() + timeout

    # Regex matches all pinggy domains (.run.pinggy-free.link, .free.pinggy.net, .pinggy.link)
    pattern = re.compile(r"https://[a-zA-Z0-9.-]+(?:pinggy-free\.link|free\.pinggy\.net|pinggy\.link)")

    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            chunk = proc.stdout.read()
            if chunk:
                buf += chunk
                matches = pattern.findall(buf)
                for m in matches:
                    if "dashboard" not in m:
                        found_url = m
                        break
                if found_url:
                    break
        except Exception:
            pass
        time.sleep(0.1)

    with _LOCK:
        _STATE["tunnel_url"] = found_url

    return found_url


def stop_all() -> None:
    with _LOCK:
        if _STATE["tunnel_process"]:
            try:
                _STATE["tunnel_process"].terminate()
                _STATE["tunnel_process"].kill()
            except Exception:
                pass
            _STATE["tunnel_process"] = None
            _STATE["tunnel_url"] = None

        if _STATE["server_process"]:
            try:
                _STATE["server_process"].terminate()
                _STATE["server_process"].kill()
            except Exception:
                pass
            _STATE["server_process"] = None
            _STATE["is_running"] = False

        try:
            subprocess.run(["fuser", "-k", f"{_STATE['port']}/tcp"], capture_output=True)
        except Exception:
            pass
