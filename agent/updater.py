"""
agent/updater.py — Check PyPI for newer versions of oblivion-agent.

Used by the /update slash command and the boot-time update check.
"""
from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from typing import Optional

import httpx

PACKAGE_NAME = "oblivion-agent"
PYPI_JSON_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
CHECK_TIMEOUT = 5  # seconds


def current_version() -> str:
    """Return installed version of oblivion-agent. 'dev' if not installed properly."""
    try:
        return _pkg_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "dev"


def latest_version() -> Optional[dict]:
    """Query PyPI for the latest published version. Returns dict or None on failure.

    Returns:
      {"version": "2.9.0", "summary": "...", "release_date": "2026-06-23"}
    """
    try:
        r = httpx.get(PYPI_JSON_URL, timeout=CHECK_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        info = data.get("info", {})
        latest = info.get("version", "")
        if not latest:
            return None
        # Find release date for this version
        releases = data.get("releases", {})
        files = releases.get(latest, [])
        upload_time = files[0].get("upload_time", "")[:10] if files else ""
        return {
            "version": latest,
            "summary": info.get("summary", ""),
            "release_date": upload_time,
            "project_url": info.get("project_url", f"https://pypi.org/project/{PACKAGE_NAME}/"),
        }
    except Exception:
        return None


def _parse_version(v: str) -> tuple:
    """'2.10.1' -> (2, 10, 1). Handles non-numeric like 'dev' -> (0,0,0)."""
    parts = []
    for x in v.split("."):
        try:
            parts.append(int(x.split("-")[0].split("+")[0]))
        except (ValueError, IndexError):
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def has_update() -> Optional[dict]:
    """Check if a newer version exists. Returns dict with 'current' + 'latest' or None.

    Returns None if:
      - Network error
      - Already on latest
      - Local dev install
    """
    current = current_version()
    if current == "dev":
        return None
    latest_info = latest_version()
    if not latest_info:
        return None
    latest = latest_info["version"]
    if _parse_version(latest) > _parse_version(current):
        return {
            "current": current,
            "latest": latest,
            "release_date": latest_info.get("release_date", ""),
            "summary": latest_info.get("summary", ""),
            "project_url": latest_info.get("project_url", ""),
        }
    return None


def install_update() -> dict:
    """Run pip install --upgrade oblivion-agent in the current Python env.

    Returns {"ok": bool, "output": str, "new_version": str}
    """
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min for pip install
        )
        ok = proc.returncode == 0
        output = (proc.stdout + "\n" + proc.stderr).strip()
        # Try to read the new version (importlib metadata is cached, so use pip show)
        new_version = "?"
        try:
            show = subprocess.run(
                [sys.executable, "-m", "pip", "show", PACKAGE_NAME],
                capture_output=True, text=True, timeout=10,
            )
            for line in show.stdout.splitlines():
                if line.startswith("Version:"):
                    new_version = line.split(":", 1)[1].strip()
                    break
        except Exception:
            pass
        return {"ok": ok, "output": output, "new_version": new_version}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "pip install timed out after 5min", "new_version": "?"}
    except Exception as e:
        return {"ok": False, "output": f"{type(e).__name__}: {e}", "new_version": "?"}


def changelog_url(version: str = None) -> str:
    """Return GitHub release URL for a version."""
    v = version or current_version()
    return f"https://github.com/Rohith-s-hub/Oblivion-agent/releases/tag/v{v}"
