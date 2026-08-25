"""
tools/preview.py - Live Web Browser Preview Tool for Oblivion AI

Serves the current workspace over a background HTTP server and launches
the user's default web browser to view generated HTML/web pages.
"""
from __future__ import annotations

import http.server
import os
import socketserver
import threading
import webbrowser
from pathlib import Path

_preview_server: socketserver.TCPServer | None = None
_preview_port: int = 8000


def _get_workspace() -> Path:
    return Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that suppresses verbose console logging."""
    def log_message(self, format, *args):
        pass  # keep terminal clean


def _start_background_server(workspace_dir: Path, port: int = 8000) -> int:
    """Start an HTTP server in a background thread if not already running."""
    global _preview_server, _preview_port

    if _preview_server is not None:
        return _preview_port

    # Try requested port or find next available port
    for try_port in range(port, port + 20):
        try:
            # Custom handler serving workspace directory
            def handler_factory(*args, **kwargs):
                return QuietHTTPRequestHandler(*args, directory=str(workspace_dir), **kwargs)

            # Allow address reuse
            socketserver.TCPServer.allow_reuse_address = True
            server = socketserver.TCPServer(("127.0.0.1", try_port), handler_factory)
            
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            _preview_server = server
            _preview_port = try_port
            return try_port
        except OSError:
            continue

    return port


def open_preview(path: str = "index.html", port: int = 8000) -> str:
    """
    Serve workspace over a local HTTP server and open path in default web browser.

    path: Workspace-relative path to HTML file (e.g. 'index.html' or 'pages/about.html')
    port: Preferred port (default 8000)
    """
    ws = _get_workspace()
    
    # Clean up relative path
    clean_path = path.strip().lstrip("/")
    if not clean_path:
        clean_path = "index.html"

    target_file = ws / clean_path
    if not target_file.exists():
        # Check if file exists anywhere in workspace root
        if (ws / "index.html").exists():
            clean_path = "index.html"
            target_file = ws / "index.html"
        else:
            return f"Error: File '{path}' does not exist in workspace {ws}."

    # Start or reuse HTTP server
    active_port = _start_background_server(ws, port=port)
    url = f"http://127.0.0.1:{active_port}/{clean_path}"

    # Open in system default web browser
    try:
        webbrowser.open(url)
        return f"🌐 [PREVIEW LIVE] Opened {url} in your default browser."
    except Exception as e:
        return f"Started HTTP server at {url}, but failed to launch browser: {e}"
